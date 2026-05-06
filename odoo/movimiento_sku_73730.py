"""
Movimiento del SKU 73730 (Repisa 55x15x9 CM Metal Negro) en 2026.
Bodega principal: CA1 (warehouse completo: Stock + Input + Output + bins).
Diferencia salidas a venta (cliente) vs traslados internos a otras bodegas (CA2, etc.).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'archive', 'Junior Revenue'))
from odoo_connection import OdooConnection

odoo = OdooConnection(
    url="https://unionxb2b.odoo.com",
    username="andres@grupoeter.cl",
    password="ROTATED-2026-05-07",
    db_name="bmya-innovatek-sh-prd-6981800"
)
odoo.login()

SKU = "73730"
DESDE = "2026-01-01 00:00:00"
HASTA = "2026-05-05 23:59:59"

# 1) Producto
prod = odoo.search_read(
    "product.product",
    domain=[["default_code", "=", SKU]],
    fields=["id", "default_code", "name"]
)[0]
print(f"Producto: [{prod['default_code']}] {prod['name']} (id={prod['id']})\n")

# 2) Listar warehouses para identificar CA1 y "otras"
whs = odoo.search_read("stock.warehouse", domain=[],
                        fields=["id", "name", "code", "view_location_id", "lot_stock_id"])
print("Warehouses:")
ca1_wh_id = None
for wh in whs:
    print(f"  id={wh['id']} | code={wh['code']} | name={wh['name']} | view_loc={wh['view_location_id']} | lot_stock={wh['lot_stock_id']}")
    if wh['code'] == 'CA1' or 'CA1' in (wh['name'] or '') or 'Carrascal' in (wh['name'] or ''):
        ca1_wh_id = wh['id']

# 3) Todas las ubicaciones internas pertenecientes al warehouse CA1
ca1_locs = odoo.search_read(
    "stock.location",
    domain=[["warehouse_id", "=", ca1_wh_id], ["usage", "=", "internal"]],
    fields=["id", "complete_name"]
)
ca1_internal_ids = {l['id'] for l in ca1_locs}
ca1_stock_principal_ids = {l['id'] for l in ca1_locs
                            if l['complete_name'] == 'CA1/Stock'
                            or l['complete_name'].startswith('CA1/Stock/')}
print(f"\nWarehouse CA1: {len(ca1_internal_ids)} ubicaciones internas totales, "
      f"{len(ca1_stock_principal_ids)} dentro de CA1/Stock")

# 4) Stock actual en CA1/Stock (todos los bins)
quants = odoo.search_read(
    "stock.quant",
    domain=[["product_id", "=", prod['id']], ["location_id", "in", list(ca1_stock_principal_ids)]],
    fields=["quantity", "location_id"]
)
stock_actual_ca1stock = sum(q['quantity'] for q in quants)
quants_all_ca1 = odoo.search_read(
    "stock.quant",
    domain=[["product_id", "=", prod['id']], ["location_id", "in", list(ca1_internal_ids)]],
    fields=["quantity", "location_id"]
)
stock_actual_ca1total = sum(q['quantity'] for q in quants_all_ca1)
print(f"\nStock actual en CA1/Stock: {stock_actual_ca1stock}")
print(f"Stock actual en CA1 total (Stock+Input+Output): {stock_actual_ca1total}")

# 5) Movimientos: tomamos los que cruzan la frontera del warehouse CA1
moves = odoo.search_read(
    "stock.move",
    domain=[
        ["product_id", "=", prod['id']],
        ["state", "=", "done"],
        ["date", ">=", DESDE],
        ["date", "<=", HASTA],
        "|",
        ["location_id", "in", list(ca1_internal_ids)],
        ["location_dest_id", "in", list(ca1_internal_ids)],
    ],
    fields=["id", "date", "product_uom_qty", "quantity", "reference", "origin",
            "location_id", "location_dest_id", "picking_type_id"],
    limit=5000,
)

# Cachear ubicaciones y picking types
loc_ids = list({m['location_id'][0] for m in moves} | {m['location_dest_id'][0] for m in moves})
locs_info = {l['id']: l for l in odoo.read("stock.location", loc_ids,
                                           ["id", "complete_name", "usage", "warehouse_id"])}
ptype_ids = list({m['picking_type_id'][0] for m in moves if m.get('picking_type_id')})
ptypes = {pt['id']: pt for pt in odoo.read("stock.picking.type", ptype_ids,
                                            ["id", "name", "code"])}

salidas_venta = []          # CA1 -> customer
salidas_otra_bodega = []    # CA1 -> otra warehouse
salidas_otros = []          # CA1 -> ajustes/perdidas
entradas_compra = []        # supplier/produccion -> CA1
entradas_otra_bodega = []   # otra warehouse -> CA1
entradas_otros = []         # ajustes -> CA1

for m in moves:
    qty = m.get('quantity') or m.get('product_uom_qty') or 0.0
    src_id = m['location_id'][0]
    dst_id = m['location_dest_id'][0]
    src_in = src_id in ca1_internal_ids
    dst_in = dst_id in ca1_internal_ids
    if src_in and dst_in:
        continue   # interno a CA1, ignorar

    src = locs_info.get(src_id, {})
    dst = locs_info.get(dst_id, {})
    pt = ptypes.get(m['picking_type_id'][0]) if m.get('picking_type_id') else None
    pt_code = pt['code'] if pt else None
    pt_name = pt['name'] if pt else ''

    info = {
        "date": m['date'][:10],
        "qty": qty,
        "ref": m.get('reference') or '',
        "origin": m.get('origin') or '',
        "src": src.get('complete_name'),
        "dst": dst.get('complete_name'),
        "pt_name": pt_name,
    }

    if src_in and not dst_in:
        # salida de CA1
        if dst.get('usage') == 'customer':
            salidas_venta.append(info)
        elif dst.get('usage') == 'internal':
            salidas_otra_bodega.append(info)   # otra warehouse
        else:
            salidas_otros.append(info)         # ajustes / scrap / produccion
    elif dst_in and not src_in:
        if src.get('usage') == 'supplier':
            entradas_compra.append(info)
        elif src.get('usage') == 'internal':
            entradas_otra_bodega.append(info)
        else:
            entradas_otros.append(info)        # ajustes / produccion

# 6) Calculo del stock inicial al 01/01/2026
# delta = entradas_totales - salidas_totales (sobre warehouse CA1 completo)
def total(lst): return sum(x['qty'] for x in lst)
total_ent = total(entradas_compra) + total(entradas_otra_bodega) + total(entradas_otros)
total_sal = total(salidas_venta) + total(salidas_otra_bodega) + total(salidas_otros)
delta = total_ent - total_sal
stock_inicial_ca1total = stock_actual_ca1total - delta

# 7) Imprimir
def imprime(titulo, lista):
    print(f"\n--- {titulo} ({len(lista)} mov | total {total(lista):g}) ---")
    for x in sorted(lista, key=lambda z: z['date']):
        print(f"  {x['date']} | {x['qty']:>4g} | {x['ref']:<22} | origin={x['origin']:<22} | "
              f"{x['src']} -> {x['dst']} | {x['pt_name']}")

print("\n" + "=" * 95)
print("DETALLE DE MOVIMIENTOS 2026 - WAREHOUSE CA1 (frontera del warehouse)")
print("=" * 95)
imprime("SALIDAS POR VENTA (a clientes)", salidas_venta)
imprime("SALIDAS POR TRASLADO A OTRAS BODEGAS", salidas_otra_bodega)
imprime("SALIDAS OTROS (ajustes/scrap/produccion)", salidas_otros)
imprime("ENTRADAS POR COMPRA (proveedor)", entradas_compra)
imprime("ENTRADAS POR TRASLADO DE OTRAS BODEGAS", entradas_otra_bodega)
imprime("ENTRADAS OTROS (ajustes/produccion)", entradas_otros)

print("\n" + "=" * 95)
print("RESUMEN EJECUTIVO - SKU 73730 - WAREHOUSE CA1 (Bodega Carrascal)")
print("=" * 95)
print(f"Stock inicial al 01/01/2026 (CA1 total): {stock_inicial_ca1total:g}")
print(f"  + Entradas por compra:                 {total(entradas_compra):g}")
print(f"  + Entradas desde otras bodegas:        {total(entradas_otra_bodega):g}")
print(f"  + Entradas por ajustes/produccion:     {total(entradas_otros):g}")
print(f"  - Salidas por venta:                   {total(salidas_venta):g}")
print(f"  - Salidas a otras bodegas:             {total(salidas_otra_bodega):g}")
print(f"  - Salidas por ajustes/scrap:           {total(salidas_otros):g}")
print(f"  = Stock actual CA1 total:              {stock_actual_ca1total:g}")
print(f"     (de los cuales en CA1/Stock:        {stock_actual_ca1stock:g})")
check = stock_inicial_ca1total + total_ent - total_sal
print(f"  (cuadre: {check:g} vs actual {stock_actual_ca1total:g} -> diff {stock_actual_ca1total - check:g})")
