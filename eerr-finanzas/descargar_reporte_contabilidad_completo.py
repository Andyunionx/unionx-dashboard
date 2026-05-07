"""
DESCARGA REPORTE CONTABILIDAD COMPLETO - TODOS LOS CAMPOS
Replica exactamente la exportación de Odoo Contabilidad con enriquecimiento:
- Órdenes de venta (marketplace reference, fulfillment, bodega, canal)
- Matriz Productos (categorización, marca, proveedor, tipo)
- CanalxKam (Tipo Negocio, KAM, Estado Canal)
- Comisiones y Logística Marketplace
- Campos derivados (año, mes, semana, día, hora, márgenes)

Uso: Cambiar PERIODO_INICIO y PERIODO_FIN para cualquier período.
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

# ============================================================================
# CONFIGURACION - CAMBIAR AQUI EL PERIODO
# ============================================================================

PERIODO_INICIO  = '2026-03-01 00:00:00'
PERIODO_FIN     = '2026-03-31 23:59:59'
PERIODO_NOMBRE  = 'marzo_2026'

# ============================================================================

print("\n" + "="*120)
print(f" REPORTE CONTABILIDAD COMPLETO - {PERIODO_NOMBRE.upper()}")
print("="*120)

# Conectar
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(str(env_path))
password = os.getenv("ANDRES_ODOO_PASSWORD")

url     = "https://unionxb2b.odoo.com"
db      = "bmya-innovatek-sh-prd-6981800"
usuario = "andres@grupoeter.cl"

common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid    = common.authenticate(db, usuario, password, {})
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

print(f"\n[OK] Conectado (UID: {uid})")

# ============================================================================
# PASO 1: EXTRAER FACTURAS
# ============================================================================

print(f"\n[PASO 1] Extrayendo facturas {PERIODO_NOMBRE}...")

facturas = models.execute_kw(db, uid, password,
    'account.move', 'search_read',
    [[
        ('invoice_date', '>=', PERIODO_INICIO.split()[0]),
        ('invoice_date', '<=', PERIODO_FIN.split()[0]),
        ('move_type', '=', 'out_invoice'),
        ('state', '=', 'posted'),
    ]],
    {'fields': [
        'id', 'name', 'invoice_date', 'date', 'journal_id', 'state', 'partner_id',
        'amount_total', 'amount_untaxed', 'amount_tax', 'ref',
        'invoice_user_id', 'team_id', 'create_date', 'invoice_line_ids',
        'l10n_latam_document_number', 'payment_state'
    ], 'limit': 100000}
)

print(f"[OK] {len(facturas):,} facturas")

factura_ids = [f['id'] for f in facturas]

# ============================================================================
# PASO 2: EXTRAER LINEAS DE FACTURA
# ============================================================================

print(f"\n[PASO 2] Extrayendo líneas de factura...")

lineas = models.execute_kw(db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids)]],
    {'fields': [
        'id', 'move_id', 'product_id', 'quantity', 'price_unit', 'price_subtotal',
        'product_uom_id', 'account_id', 'ref', 'create_date', 'discount'
    ], 'limit': 500000}
)

print(f"[OK] {len(lineas):,} líneas")

# ============================================================================
# PASO 3: EXTRAER ORDENES DE VENTA (para marketplace, fulfillment, etc.)
# ============================================================================

print(f"\n[PASO 3] Extrayendo órdenes de venta...")

ordenes = models.execute_kw(db, uid, password,
    'sale.order', 'search_read',
    [[('invoice_ids', 'in', factura_ids)]],
    {'fields': [
        'id', 'name', 'date_order', 'partner_id', 'user_id', 'team_id',
        'channel', 'channel_order_reference', 'client_order_ref',
        'fulfillment', 'warehouse_id', 'invoice_ids'
    ], 'limit': 100000}
)

print(f"[OK] {len(ordenes):,} órdenes")

ordenes_dict = {}
for orden in ordenes:
    for inv_id in orden.get('invoice_ids', []):
        if inv_id not in ordenes_dict:
            ordenes_dict[inv_id] = orden

# ============================================================================
# PASO 4: EXTRAER PRODUCTOS
# ============================================================================

print(f"\n[PASO 4] Extrayendo productos...")

product_ids_all = list({l['product_id'][0] for l in lineas if l.get('product_id')})

productos_dict = {}
batch_size = 500

for i in range(0, len(product_ids_all), batch_size):
    batch = product_ids_all[i:i+batch_size]
    prods = models.execute_kw(db, uid, password,
        'product.product', 'search_read',
        [[('id', 'in', batch)]],
        {'fields': ['id', 'default_code', 'name', 'list_price', 'standard_price', 'categ_id'],
         'limit': batch_size}
    )
    for p in prods:
        productos_dict[p['id']] = p

print(f"[OK] {len(productos_dict):,} productos cargados")

# ============================================================================
# PASO 5: CONSTRUIR DATASET BASE
# ============================================================================

print(f"\n[PASO 5] Construyendo dataset base...")

facturas_dict = {f['id']: f for f in facturas}

datos = []

for linea in lineas:
    move_id = linea.get('move_id', [None])[0] if linea.get('move_id') else None
    if not move_id or move_id not in facturas_dict:
        continue

    factura = facturas_dict[move_id]
    orden = ordenes_dict.get(move_id)

    # Producto
    product_id = linea['product_id'][0] if linea.get('product_id') else None
    producto_nombre = linea['product_id'][1] if linea.get('product_id') else ''
    producto_info = productos_dict.get(product_id, {})

    # Partner/Cliente
    partner = factura.get('partner_id', [None, ''])
    cliente = partner[1] if isinstance(partner, list) else ''

    # Vendedor
    vendedor = factura.get('invoice_user_id', [None, ''])
    vendedor_name = vendedor[1] if isinstance(vendedor, list) else ''

    # Diario
    journal = factura.get('journal_id', [None, ''])
    diario = journal[1] if isinstance(journal, list) else ''

    # Team
    team = factura.get('team_id', [None, ''])
    team_name = team[1] if isinstance(team, list) else ''

    # Órdenes de venta (si aplica)
    canal = ''
    marketplace_ref = ''
    fulfillment = ''
    bodega = ''
    if orden:
        # Canal desde sale.order.channel
        canal_raw = orden.get('channel', '') or ''
        if canal_raw and canal_raw != 'False':
            # Normalizar: remover " Chile" del final
            canal = canal_raw.replace(' Chile', '').strip()
        else:
            # Si no hay canal en la orden, intentar inferir desde nombre del cliente
            if cliente and 'Mercado Libre' in cliente:
                canal = 'Mercado Libre'
            elif cliente and 'Falabella' in cliente:
                canal = 'Falabella'
            elif cliente and 'Travel Duty' in cliente or 'Duty Free' in cliente:
                canal = 'Travel Duty'
            elif cliente and 'Celmedia' in cliente:
                canal = 'Celmedia'
            elif cliente and 'Global Reward' in cliente:
                canal = 'Global Reward'
            elif cliente and 'Hites' in cliente:
                canal = 'Hites'

        marketplace_ref = orden.get('channel_order_reference', '') or ''
        fulfillment = orden.get('fulfillment', '') or 'Bodega'
        warehouse = orden.get('warehouse_id', [None, ''])
        bodega = warehouse[1] if isinstance(warehouse, list) else ''

    # Cálculo de margen
    precio_subtotal = linea.get('price_subtotal', 0)
    costo_unitario = producto_info.get('standard_price', 0)
    cantidad = linea.get('quantity', 0)
    costo_total = costo_unitario * cantidad
    margen = precio_subtotal - costo_total

    # Fecha
    fecha_factura = factura.get('invoice_date', '')
    try:
        if isinstance(fecha_factura, str):
            from datetime import datetime
            dt = datetime.fromisoformat(fecha_factura)
            año = dt.year
            mes = dt.month
            dia = dt.day
            semana = dt.isocalendar()[1]
            dia_semana = dt.weekday()
            hora = 0
        else:
            año, mes, dia, semana, dia_semana, hora = 2026, 3, 1, 1, 0, 0
    except:
        año, mes, dia, semana, dia_semana, hora = 2026, 3, 1, 1, 0, 0

    fila = {
        # FACTURA
        'Diario': diario,
        'Estado': factura.get('state', ''),
        'Empresa': cliente,
        'Número': factura.get('name', ''),
        'Referencia': factura.get('ref', ''),
        'Documento': factura.get('l10n_latam_document_number', ''),
        'Fecha Factura': factura.get('invoice_date', ''),
        'Vendedor': vendedor_name,
        'Team': team_name,
        'Creado en': factura.get('create_date', ''),

        # MONTOS
        'Total': precio_subtotal,
        'Costo': costo_unitario,
        'Cantidad': cantidad,
        'Costo Total': costo_total,
        'Margen': margen,

        # PRODUCTO
        'Producto': producto_nombre,
        'SKU': producto_info.get('default_code', ''),
        'Precio Unitario': producto_info.get('list_price', 0),

        # ORDEN DE VENTA
        'Canal': canal,
        'Marketplace Reference': marketplace_ref,
        'Fulfillment': fulfillment,
        'Bodega': bodega,
        'Bodega Origen': 'Fulfillment' if fulfillment and 'fulfillment' in fulfillment.lower() else 'Warehouse Unionx',

        # FECHA DERIVADA
        'Año': año,
        'Mes': mes,
        'Día': dia,
        'Semana': semana,
    }

    datos.append(fila)

df = pd.DataFrame(datos)

print(f"[OK] {len(df):,} filas")

# ============================================================================
# PASO 6: ENRIQUECER CON MATRIZ PRODUCTOS
# ============================================================================

print(f"\n[PASO 6] Enriqueciendo con Matriz Productos...")

ruta_matriz = Path(__file__).parent.parent / "data/planillas/Matriz productos.xlsx"
matriz_prod = pd.read_excel(ruta_matriz, sheet_name='Productos')

matriz_prod = matriz_prod[['SKU', 'Categoría macro', 'Categoría padre', 'Categoría hijo', 'Categoría comercial', 'Pack', 'Marca']].copy()
matriz_prod = matriz_prod.rename(columns={'SKU': 'SKU'})

df = df.merge(matriz_prod, on='SKU', how='left')

print(f"[OK] Matriz Productos agregada")

# ============================================================================
# PASO 7: ENRIQUECER CON CANALXKAM
# ============================================================================

print(f"\n[PASO 7] Enriqueciendo con CanalxKam...")

df_canalxkam = pd.read_excel(ruta_matriz.parent / 'Matriz productos.xlsx', sheet_name='CanalxKam')
df_canalxkam = df_canalxkam[['Canal', 'Tipo Negocio', 'KAM', 'Estado Canal']].copy()

df = df.merge(df_canalxkam, on='Canal', how='left')

print(f"[OK] CanalxKam agregada")

# ============================================================================
# PASO 8: GUARDAR
# ============================================================================

print(f"\n[PASO 8] Guardando archivos...")

ruta_base = Path("data/outputs")
ruta_base.mkdir(parents=True, exist_ok=True)

ruta_csv = ruta_base / f"reporte_contabilidad_{PERIODO_NOMBRE}.csv"
ruta_xlsx = ruta_base / f"reporte_contabilidad_{PERIODO_NOMBRE}.xlsx"

df.to_csv(ruta_csv, index=False)
df.to_excel(ruta_xlsx, index=False, sheet_name='Contabilidad')

print(f"[OK] CSV:  {ruta_csv}")
print(f"[OK] XLSX: {ruta_xlsx}")

# ============================================================================
# RESUMEN
# ============================================================================

print(f"\n{'='*120}")
print(f" RESUMEN - {PERIODO_NOMBRE.upper()}")
print(f"{'='*120}")

print(f"\n  Facturas:            {len(facturas):>8,}")
print(f"  Líneas:              {len(df):>8,}")
print(f"  Total:               ${df['Total'].sum():>14,.0f}")
print(f"  Costo Total:         ${df['Costo Total'].sum():>14,.0f}")
print(f"  Margen:              ${df['Margen'].sum():>14,.0f}")
print(f"  Clientes:            {df['Empresa'].nunique():>8,}")
print(f"  Productos:           {df['SKU'].nunique():>8,}")
print(f"  Canales:             {df['Canal'].nunique():>8,}")

print(f"\n{'='*120}")
print(f" Archivos: data/outputs/reporte_contabilidad_{PERIODO_NOMBRE}.csv y .xlsx")
print(f"{'='*120}\n")
