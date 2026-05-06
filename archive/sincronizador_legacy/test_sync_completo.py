#!/usr/bin/env python3
"""
Test: Sincronizador V2 para TODO Abril (1-18)
Combinado: Planilla (1-13) + Odoo (14-18)
"""
import sys
from pathlib import Path
from datetime import datetime
import sqlite3
import pandas as pd

PROJECT_ROOT = Path(".")
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.config import Config

db_path = "C:/Users/LENOVO/Desktop/finanzas-unionx-app/maestra_ventas.db"

print("[TEST] Sincronizador V2 - ABRIL COMPLETO (1-18)")
print("=" * 70)

try:
    odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)

    # Extraer órdenes completas (1-18)
    print("\n[1] Extrayendo órdenes...")
    ordenes = odoo.search_read('sale.order', [
        ('date_order', '>=', '2026-04-01 00:00:00'),
        ('date_order', '<=', '2026-04-18 23:59:59'),
        ('state', 'in', ['sale', 'done']),
    ], ['id', 'name', 'date_order', 'amount_total', 'warehouse_id', 'channel', 'invoice_ids'], limit=100000)

    print(f"    Órdenes: {len(ordenes):,}")

    orden_ids = [o['id'] for o in ordenes]
    ordenes_dict = {o['id']: o for o in ordenes}
    invoice_ids_all = list({inv_id for o in ordenes for inv_id in (o.get('invoice_ids') or [])})

    # Extraer líneas
    print("[2] Extrayendo líneas...")
    lineas = odoo.search_read('sale.order.line', [
        ('order_id', 'in', orden_ids)
    ], ['id', 'order_id', 'product_id', 'product_uom_qty', 'price_subtotal', 'purchase_price'], limit=500000)

    print(f"    Líneas: {len(lineas):,}")

    # Extraer facturas y NC
    print("[3] Extrayendo facturas y NC...")
    facturas = odoo.execute_in_batches('account.move', invoice_ids_all, [
        'id', 'name', 'invoice_date', 'move_type', 'amount_total', 'reversed_entry_id'
    ], batch_size=50) if invoice_ids_all else []

    nc_ids = [nc['id'] for nc in odoo.search_read('account.move', [
        ('move_type', '=', 'out_refund'),
        ('invoice_date', '>=', '2026-04-01 00:00:00'),
        ('invoice_date', '<=', '2026-04-18 23:59:59'),
        ('state', '=', 'posted'),
    ], {'fields': ['id'], 'limit': 10000})]

    ncs = odoo.execute_in_batches('account.move', nc_ids, [
        'id', 'name', 'invoice_date', 'amount_total', 'reversed_entry_id'
    ], batch_size=50) if nc_ids else []

    print(f"    Facturas: {len(facturas):,}")
    print(f"    NC: {len(ncs):,}")

    # Calcular neteo
    nc_por_factura = {}
    for nc in ncs:
        factura_id = None
        if nc.get('reversed_entry_id'):
            factura_id = nc['reversed_entry_id'][0] if isinstance(nc['reversed_entry_id'], (list, tuple)) else nc['reversed_entry_id']
        if factura_id:
            if factura_id not in nc_por_factura:
                nc_por_factura[factura_id] = 0
            nc_por_factura[factura_id] += abs(nc.get('amount_total', 0))

    totales_netos = {}
    for factura in facturas:
        factura_id = factura['id']
        nc_total = nc_por_factura.get(factura_id, 0)
        totales_netos[factura_id] = factura['amount_total'] - nc_total

    # Construir dataset
    print("[4] Construyendo dataset...")

    factura_a_orden = {}
    for orden in ordenes:
        for inv_id in (orden.get('invoice_ids') or []):
            factura_a_orden[inv_id] = orden['id']

    rows = []
    for linea in lineas:
        orden_id = linea['order_id'][0] if linea['order_id'] else None
        orden = ordenes_dict.get(orden_id, {})

        if not orden:
            continue

        factura_id = None
        for inv_id in (orden.get('invoice_ids') or []):
            factura_id = inv_id
            break

        precio_linea = linea.get('price_subtotal', 0)
        venta_neta = precio_linea

        if factura_id and factura_id in totales_netos:
            orden_amount = orden.get('amount_total', 0)
            if orden_amount > 0:
                venta_neta = precio_linea * (totales_netos[factura_id] / orden_amount)

        producto_id = linea['product_id'][0] if linea['product_id'] else None

        rows.append({
            'tipo_movimiento': 'Venta',
            'documento': orden.get('name', ''),
            'fecha_venta': orden.get('date_order', '').split(' ')[0] if orden.get('date_order') else '',
            'producto': f"SKU_{producto_id}" if producto_id else 'Sin producto',
            'cantidad': linea.get('product_uom_qty', 0),
            'venta_bruta': venta_neta,
            'costo_unitario': linea.get('purchase_price', 0),
            'costo_total': linea.get('purchase_price', 0) * linea.get('product_uom_qty', 0),
            'margen_final': venta_neta - (linea.get('purchase_price', 0) * linea.get('product_uom_qty', 0)),
            'bodega': orden.get('warehouse_id', [None, ''])[1] if orden.get('warehouse_id') else 'Bodega Principal',
            'canal': orden.get('channel', 'Direct'),
            'estado_pedido': orden.get('state', 'sale'),
        })

    # Agregar NC
    for nc in ncs:
        factura_id = None
        if nc.get('reversed_entry_id'):
            factura_id = nc['reversed_entry_id'][0] if isinstance(nc['reversed_entry_id'], (list, tuple)) else nc['reversed_entry_id']

        orden_id = factura_a_orden.get(factura_id)
        orden = ordenes_dict.get(orden_id, {})

        if orden:
            nc_amount = abs(nc.get('amount_total', 0))
            rows.append({
                'tipo_movimiento': 'Devolución',
                'documento': nc.get('name', ''),
                'fecha_venta': nc.get('invoice_date', '').split(' ')[0] if nc.get('invoice_date') else '',
                'producto': f"NC de {nc.get('name', 'NC')}",
                'cantidad': 1,
                'venta_bruta': -nc_amount,
                'costo_unitario': 0,
                'costo_total': 0,
                'margen_final': -nc_amount,
                'bodega': orden.get('warehouse_id', [None, ''])[1] if orden.get('warehouse_id') else 'Bodega Principal',
                'canal': orden.get('channel', 'Direct'),
                'estado_pedido': 'Devolución',
            })

    df = pd.DataFrame(rows)
    print(f"    Rows: {len(df):,}")

    # Insertar SOLO Odoo (14-18)
    print("[5] Insertando Odoo (14-18)...")
    df_odoo = df[df['fecha_venta'] >= '2026-04-14']

    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM ventas WHERE fecha_venta >= '2026-04-14'")
    df_odoo.to_sql('ventas', conn, if_exists='append', index=False, chunksize=500)

    cursor.execute("""INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), 'Odoo (sincronizador_v2)',
         len(df_odoo), '2026-04-14', '2026-04-18', 'sync'))

    conn.commit()
    conn.close()

    print(f"[OK] {len(df_odoo):,} filas Odoo insertadas\n")

    # Reportar
    print("[6] REPORTES FINALES:")
    print("=" * 70)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Por período
    cur.execute("""SELECT
        CASE WHEN fecha_venta < '2026-04-14' THEN 'Planilla 1-13' ELSE 'Odoo 14-18' END,
        COUNT(*), ROUND(SUM(venta_bruta), 0)
        FROM ventas WHERE fecha_venta >= '2026-04-01' AND fecha_venta <= '2026-04-18'
        GROUP BY CASE WHEN fecha_venta < '2026-04-14' THEN 1 ELSE 2 END
        ORDER BY 1""")

    print("\nPOR PERÍODO:")
    total_all = 0
    for periodo, lineas, venta in cur.fetchall():
        print(f"  {periodo:20s}: {lineas:>8,} líneas | ${venta:>16,.0f}")
        total_all += venta

    # Por día
    print("\nPOR DÍA:")
    cur.execute("""SELECT fecha_venta, COUNT(*), ROUND(SUM(venta_bruta), 0)
        FROM ventas WHERE fecha_venta >= '2026-04-01' AND fecha_venta <= '2026-04-18'
        GROUP BY fecha_venta ORDER BY fecha_venta""")

    for fecha, lineas, venta in cur.fetchall():
        print(f"  {fecha}: {lineas:>6,} líneas | ${venta:>16,.0f}")

    print("-" * 70)
    print(f"  TOTAL ABRIL: ${total_all:>16,.0f}")
    print("=" * 70)

    conn.close()

except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
