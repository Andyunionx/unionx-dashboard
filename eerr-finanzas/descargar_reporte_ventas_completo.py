"""
DESCARGA REPORTE VENTAS COMPLETO - CON CATEGORIZACIÓN DE PRODUCTOS
Replica exactamente el reporte estándar de Odoo + agrega categorías desde Matriz Productos:
- 27 campos base (Total, Margen, Estado, Vendedor, Cliente, Canal, etc.)
- +4 campos categoría: Categoría macro, padre, hijo, comercial
- TOTAL: 31 campos

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

PERIODO_INICIO  = '2026-04-01 00:00:00'
PERIODO_FIN     = '2026-04-30 23:59:59'
PERIODO_NOMBRE  = 'abril_2026'

# ============================================================================

print("\n" + "="*120)
print(f" REPORTE VENTAS COMPLETO (24 campos) - {PERIODO_NOMBRE.upper()}")
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
# PASO 1: EXTRAER ORDENES (campos nivel orden)
# ============================================================================

print(f"\n[PASO 1] Extrayendo órdenes {PERIODO_NOMBRE}...")

ordenes = models.execute_kw(db, uid, password,
    'sale.order', 'search_read',
    [[
        ('date_order', '>=', PERIODO_INICIO),
        ('date_order', '<=', PERIODO_FIN),
        ('state', 'in', ['sale', 'done']),
    ]],
    {'fields': [
        'id', 'name',               # Referencia de pedido
        'date_order',               # Fecha creación
        'partner_id',               # Cliente
        'user_id',                  # Vendedor
        'amount_total',             # Total
        'margin',                   # Margen
        'state',                    # Estado
        'fulfillment',              # Fulfillment
        'channel',                  # Marketplace
        'channel_order_reference',  # Marketplace Reference
        'client_order_ref',         # Referencia cliente
        'invoice_ids',              # Para unir con Facturas
        'warehouse_id',             # Inventario (bodega)
        'yuju_pack_id',             # Campo 25: Yuju Pack Id
    ], 'limit': 200000}
)

print(f"[OK] {len(ordenes):,} órdenes")

orden_ids      = [o['id']        for o in ordenes]
ordenes_dict   = {o['id']: o    for o in ordenes}
invoice_ids_all = list({inv_id for o in ordenes for inv_id in (o.get('invoice_ids') or [])})

# ============================================================================
# PASO 2: EXTRAER LINEAS (campos nivel línea)
# ============================================================================

print(f"\n[PASO 2] Extrayendo líneas de venta...")

lineas = models.execute_kw(db, uid, password,
    'sale.order.line', 'search_read',
    [[('order_id', 'in', orden_ids)]],
    {'fields': [
        'id', 'name',           # Líneas/Referencia de pedido
        'order_id',
        'product_id',           # Líneas/Producto
        'product_uom_qty',      # Líneas/Cantidad
        'qty_delivered',        # Líneas/Cantidad real
        'purchase_price',       # Líneas/Coste
        'price_subtotal',       # Líneas/Subtotal
    ], 'limit': 500000}
)

print(f"[OK] {len(lineas):,} líneas")

# IDs de productos para buscar inventario y referencia interna
product_ids_all = list({l['product_id'][0] for l in lineas if l.get('product_id')})

# ============================================================================
# PASO 3: EXTRAER PRODUCTOS (inventario + referencia interna)
# ============================================================================

print(f"\n[PASO 3] Extrayendo productos ({len(product_ids_all):,} únicos)...")

# Por lotes de 500 para no sobrecargar la API
productos_dict = {}
batch_size = 500

for i in range(0, len(product_ids_all), batch_size):
    batch = product_ids_all[i:i+batch_size]
    prods = models.execute_kw(db, uid, password,
        'product.product', 'search_read',
        [[('id', 'in', batch)]],
        {'fields': ['id', 'default_code', 'qty_available'], 'limit': batch_size}
    )
    for p in prods:
        productos_dict[p['id']] = p

print(f"[OK] {len(productos_dict):,} productos cargados")

# ============================================================================
# PASO 4: EXTRAER FACTURAS
# ============================================================================

print(f"\n[PASO 4] Extrayendo facturas ({len(invoice_ids_all):,} facturas)...")

facturas_dict = {}

if invoice_ids_all:
    for i in range(0, len(invoice_ids_all), 500):
        batch = invoice_ids_all[i:i+500]
        facturas = models.execute_kw(db, uid, password,
            'account.move', 'search_read',
            [[('id', 'in', batch)]],
            {'fields': ['id', 'name', 'state', 'invoice_date', 'create_date', 'company_id', 'l10n_latam_document_number'],
             'limit': 500}
        )
        for f in facturas:
            facturas_dict[f['id']] = f

print(f"[OK] {len(facturas_dict):,} facturas cargadas")

# ============================================================================
# PASO 5: CONSTRUIR DATASET FINAL CON LOS 24 CAMPOS
# ============================================================================

print(f"\n[PASO 5] Construyendo reporte con 24 campos exactos...")

datos = []

for linea in lineas:
    order_id = linea['order_id'][0] if linea.get('order_id') else None
    if not order_id or order_id not in ordenes_dict:
        continue

    orden = ordenes_dict[order_id]

    # Producto
    product_id = linea['product_id'][0] if linea.get('product_id') else None
    producto_nombre = linea['product_id'][1] if linea.get('product_id') else ''
    producto_info = productos_dict.get(product_id, {})

    # Factura (tomar la primera vinculada a la orden)
    factura = None
    for inv_id in (orden.get('invoice_ids') or []):
        if inv_id in facturas_dict:
            factura = facturas_dict[inv_id]
            break

    # Margen calculado a nivel línea (evita duplicación en ordenes multi-línea)
    precio_subtotal = linea.get('price_subtotal', 0)
    costo_linea = linea.get('purchase_price', 0) * linea.get('product_uom_qty', 0)
    margen_linea = precio_subtotal - costo_linea

    fila = {
        # NIVEL ORDEN
        'Total':                    precio_subtotal,   # subtotal línea (sumable, sin IVA)
        'Margen':                   margen_linea,      # Subtotal - (Coste x Cantidad), nivel línea
        'Estado':                   orden.get('state', ''),
        'Vendedor':                 (orden.get('user_id') or [None,''])[1],
        'Fulfillment':              orden.get('fulfillment', '') or 'Bodega',
        'Marketplace':              orden.get('channel', ''),
        'Cliente':                  (orden.get('partner_id') or [None,''])[1],
        'Fecha creacion':           orden.get('date_order', ''),
        'Marketplace Reference':    orden.get('channel_order_reference', ''),
        'Referencia de pedido':     orden.get('name', ''),
        'Referencia cliente':       orden.get('client_order_ref', ''),

        # NIVEL LINEA
        'Lineas - Referencia de pedido':    linea.get('name', ''),
        'Lineas - Cantidad':                linea.get('product_uom_qty', 0),
        'Lineas - Producto':                producto_nombre,
        'Lineas - Referencia interna':      producto_info.get('default_code', ''),
        'Lineas - Coste':                   linea.get('purchase_price', 0),
        'Lineas - Cantidad real':           linea.get('qty_delivered', 0),
        'Lineas - Subtotal':                linea.get('price_subtotal', 0),

        # INVENTARIO = bodega de la orden
        'Inventario':               (orden.get('warehouse_id') or [None, ''])[1],

        # YUJU
        'Yuju Pack Id':             orden.get('yuju_pack_id') or '',

        # FACTURAS
        'Facturas - Creado en':     (factura or {}).get('create_date', ''),
        'Facturas - Empresa':       ((factura or {}).get('company_id') or [None,''])[1] if factura else '',
        'Facturas - Estado':        (factura or {}).get('state', ''),
        'Facturas - Fecha':         (factura or {}).get('invoice_date', ''),
        'Facturas - Numero':        (factura or {}).get('name', ''),
        'Facturas - Documento':     (factura or {}).get('l10n_latam_document_number', ''),
    }

    datos.append(fila)

df = pd.DataFrame(datos)

# ============================================================================
# PASO 6: ENRIQUECER CON MAESTRA CANALES + CATEGORIAS DE PRODUCTOS
# ============================================================================

print(f"\n[PASO 6] Enriqueciendo con Maestra Canales y categorías de productos...")

# Cargar Maestra Canales
ruta_maestra = Path(__file__).parent.parent / "data/planillas/Maestra Canales.xlsx"
maestra = pd.read_excel(ruta_maestra)

# Merge Canal por Cliente
df = df.merge(
    maestra.rename(columns={'Empresa': 'Cliente', 'Canal': 'Canal'}),
    on='Cliente', how='left'
)

# Cargar CanalxKam para Tipo Negocio, KAM, Estado Canal
ruta_canalxkam = Path(__file__).parent.parent / "data/planillas/Matriz productos.xlsx"
df_canalxkam = pd.read_excel(ruta_canalxkam, sheet_name='CanalxKam')
df_canalxkam = df_canalxkam[['Canal', 'Tipo Negocio', 'KAM', 'Estado Canal']].copy()

# Merge con CanalxKam por Canal
df = df.merge(df_canalxkam, on='Canal', how='left', suffixes=('', '_cxk'))

# Cargar Matriz Productos para categorías
ruta_matriz = Path(__file__).parent.parent / "data/planillas/Matriz productos.xlsx"
matriz_prod = pd.read_excel(ruta_matriz, sheet_name='Productos')

# Extraer solo columnas necesarias (SKU = Lineas - Referencia interna)
matriz_prod = matriz_prod[['SKU', 'Categoría macro', 'Categoría padre', 'Categoría hijo', 'Categoría comercial']].copy()
matriz_prod = matriz_prod.rename(columns={'SKU': 'Lineas - Referencia interna'})

# Merge con categorías por SKU
df = df.merge(matriz_prod, on='Lineas - Referencia interna', how='left')

# Cargar Comisiones y Logística Marketplace
print(f"\n[PASO 6B] Integrando comisiones y logística marketplace...")
ruta_mockup = Path(__file__).parent.parent / "data/planillas/Mockup raw Y.xlsx"
df_com_mkpl = pd.read_excel(ruta_mockup, sheet_name='Com Mkpl')
df_log_mkpl = pd.read_excel(ruta_mockup, sheet_name='Log Mkpl')

# Mapeo de canales del reporte a columnas en Com/Log Mkpl
mapeo_canales = {
    'Mercado Libre': 'Mercado Libre',
    'Falabella': 'Falabella',
    'Paris': 'Paris',
    'Paris tienda': 'Paris',
    'Ripley': 'Ripley',
    'Ripley tienda': 'Ripley',
    'Walmart': 'Walmart',
    'Walmart tienda': 'Walmart',
    'Kitchen Center': 'Kitchen Center',
}

# Rename en Com Mkpl para coincidencia con SKU
df_com_mkpl = df_com_mkpl.rename(columns={'SKU_HIJO': 'Lineas - Referencia interna'})
df_log_mkpl = df_log_mkpl.rename(columns={'SKU_HIJO': 'Lineas - Referencia interna'})

# Merge con comisiones
df = df.merge(df_com_mkpl[['Lineas - Referencia interna'] + list(mapeo_canales.values())].drop_duplicates(),
              on='Lineas - Referencia interna', how='left', suffixes=('', '_com'))

# Función para obtener comisión según canal
def obtener_comision_pct(row):
    canal = row['Canal']
    sku = row['Lineas - Referencia interna']

    # Si no hay mapeo del canal, retorna 0
    if canal not in mapeo_canales:
        return 0.0

    col_canal = mapeo_canales[canal]

    # Intenta obtener el valor de la columna correspondiente
    try:
        valor = row.get(col_canal, 0)
        if pd.isna(valor):
            return 0.0
        return float(valor) if valor else 0.0
    except:
        return 0.0

df['Comisión %'] = df.apply(obtener_comision_pct, axis=1)

# Calcular comisión en pesos
df['Comisión $ (Mkpl)'] = df['Total'] * (df['Comisión %'] / 100)

# Merge con logística (especial para Mercado Libre que tiene Colecta y Full)
# Primero, preparar df_log_mkpl con manejo especial para Mercado Libre
df_log_mkpl_prep = df_log_mkpl[['Lineas - Referencia interna']].drop_duplicates().copy()

# Agregar columnas de logística mapeadas
for col_reporte, col_log in mapeo_canales.items():
    if col_log == 'Mercado Libre':
        # Para Mercado Libre, tomar el máximo de Colecta y Full
        colecta = df_log_mkpl.set_index('Lineas - Referencia interna')['Mercado Libre Colecta']
        full = df_log_mkpl.set_index('Lineas - Referencia interna')['Mercado Libre Full']

        def max_ml(x):
            try:
                c = colecta.get(x, 0)
                f = full.get(x, 0)
                c = 0 if pd.isna(c) else (float(c) if isinstance(c, (int, float)) else 0)
                f = 0 if pd.isna(f) else (float(f) if isinstance(f, (int, float)) else 0)
                return max(c, f)
            except:
                return 0

        df_log_mkpl_prep['Mercado Libre'] = df_log_mkpl_prep['Lineas - Referencia interna'].apply(max_ml)
    elif col_log in df_log_mkpl.columns:
        df_log_mkpl_prep[col_log] = df_log_mkpl.set_index('Lineas - Referencia interna')[col_log]

df = df.merge(df_log_mkpl_prep, on='Lineas - Referencia interna', how='left', suffixes=('', '_log'))

# Función para obtener logística según canal
def obtener_logistica(row):
    canal = row['Canal']

    # Si no hay mapeo del canal, retorna 0
    if canal not in mapeo_canales:
        return 0.0

    col_canal = mapeo_canales[canal]

    # Intenta obtener el valor de la columna correspondiente
    try:
        valor = row.get(col_canal, 0)
        if pd.isna(valor):
            return 0.0
        return float(valor) if valor else 0.0
    except:
        return 0.0

df['Logística $ (Mkpl)'] = df.apply(obtener_logistica, axis=1)

print(f"[OK] Comisiones marketplace agregadas")
print(f"[OK] Logística marketplace agregada")

# Regla Web: subdividir por prefijo de Marketplace Reference
def resolver_canal(canal, ref):
    if canal != 'Web':
        return canal
    ref = str(ref or '')
    if ref.startswith('LH'):   return 'Lhotse web'
    elif ref.startswith('SH'): return 'Simplit web'
    elif ref.startswith('#'):  return 'UnionX web'
    return 'Web'

df['Canal'] = df.apply(lambda r: resolver_canal(r['Canal'], r['Marketplace Reference']), axis=1)

# Vacíos Canal → Union X B2B
df['Canal'] = df['Canal'].fillna('Union X B2B')

# Renombrar Marketplace → Linea de Negocio y limpiar False
df = df.rename(columns={'Marketplace': 'Linea de Negocio'})
df['Linea de Negocio'] = df['Linea de Negocio'].replace('False', '').replace(False, '')

# Columna Bodega Origen (junto a Inventario)
df['Bodega Origen'] = df['Inventario'].apply(
    lambda x: 'Fulfillment' if 'fulfillment' in str(x).lower() else 'Warehouse Unionx'
)

# Reordenar columnas en orden lógico
orden_columnas = [
    # IDENTIFICADORES Y REFERENCIAS
    'Referencia de pedido',
    'Referencia cliente',
    'Marketplace Reference',
    'Yuju Pack Id',
    'Lineas - Referencia de pedido',

    # FECHA Y CONTEXTO
    'Fecha creacion',
    'Estado',

    # CLIENTE Y VENDEDOR
    'Cliente',
    'Canal',
    'Tipo Negocio',
    'Vendedor',
    'Fulfillment',
    'Linea de Negocio',

    # BODEGA E INVENTARIO
    'Inventario',
    'Bodega Origen',

    # PRODUCTO
    'Lineas - Producto',
    'Lineas - Referencia interna',
    'Categoría macro',
    'Categoría padre',
    'Categoría hijo',
    'Categoría comercial',

    # CANTIDADES Y VALORES UNITARIOS
    'Lineas - Cantidad',
    'Lineas - Cantidad real',
    'Lineas - Coste',
    'Lineas - Subtotal',

    # FINANCIERO
    'Total',
    'Margen',
    'Comisión %',
    'Comisión $ (Mkpl)',
    'Logística $ (Mkpl)',

    # FACTURACIÓN
    'Facturas - Numero',
    'Facturas - Documento',
    'Facturas - Fecha',
    'Facturas - Estado',
    'Facturas - Empresa',
    'Facturas - Creado en',
]

# ============================================================================
# PASO 7: CALCULAR METRICAS FINANCIERAS
# ============================================================================

print(f"\n[PASO 7] Calculando métricas financieras...")

# Convertir a numéricas ANTES de filtrar columnas
df['Lineas - Coste'] = pd.to_numeric(df['Lineas - Coste'], errors='coerce').fillna(0)
df['Lineas - Cantidad'] = pd.to_numeric(df['Lineas - Cantidad'], errors='coerce').fillna(0)
df['Total'] = pd.to_numeric(df['Total'], errors='coerce').fillna(0)
df['Comisión $ (Mkpl)'] = pd.to_numeric(df['Comisión $ (Mkpl)'], errors='coerce').fillna(0)
df['Logística $ (Mkpl)'] = pd.to_numeric(df['Logística $ (Mkpl)'], errors='coerce').fillna(0)

# Calcular Costo Total, Margen Directo y Margen Final
df['Costo Total'] = df['Lineas - Coste'] * df['Lineas - Cantidad']
df['Margen Directo'] = df['Total'] - df['Costo Total']
df['Margen Final'] = df['Margen Directo'] - df['Comisión $ (Mkpl)'] - df['Logística $ (Mkpl)']

# Reordenar: mantener columnas base + calculadas
orden_columnas_con_metricas = orden_columnas + ['Costo Total', 'Margen Directo', 'Margen Final']
cols_existentes = [col for col in orden_columnas_con_metricas if col in df.columns]
df = df[cols_existentes]

print(f"[OK] {len(df):,} filas, {len(df.columns)} columnas")
print(f"[OK] Columnas: {list(df.columns)}")

# ============================================================================
# CREAR RESUMENES POR DIFERENTES DIMENSIONES
# ============================================================================

def crear_resumen(df_data, grupo_col, nombre_grupo):
    resumen = df_data.groupby(grupo_col).agg({
        'Total': 'sum',
        'Costo Total': 'sum',
        'Margen Directo': 'sum',
        'Comisión $ (Mkpl)': 'sum',
        'Logística $ (Mkpl)': 'sum',
        'Margen Final': 'sum'
    }).reset_index()

    resumen.columns = [nombre_grupo, 'Venta Neta', 'Costo', 'Margen Directo', 'Comisión', 'Logística', 'Margen Final']
    resumen['% Margen Final'] = (resumen['Margen Final'] / resumen['Venta Neta'] * 100).round(1)

    return resumen.sort_values('Venta Neta', ascending=False)

resumen_linea = crear_resumen(df, 'Linea de Negocio', 'Línea de Negocio')
resumen_canal = crear_resumen(df, 'Canal', 'Canal')
resumen_categoria = crear_resumen(df, 'Categoría macro', 'Categoría')
resumen_bodega = crear_resumen(df, 'Bodega Origen', 'Bodega')

print(f"[OK] Resúmenes creados")

# ============================================================================
# PASO 8: GUARDAR EN EXCEL CON MULTIPLES HOJAS Y CSV
# ============================================================================

print(f"\n[PASO 8] Guardando archivos...")

ruta_base = Path("data/outputs")
ruta_base.mkdir(parents=True, exist_ok=True)

# CSV (solo detalle línea con columnas seleccionadas)
ruta_csv = ruta_base / f"reporte_ventas_{PERIODO_NOMBRE}.csv"
df_csv = df.copy()
cols_csv = [
    'Referencia de pedido', 'Cliente', 'Canal', 'Linea de Negocio',
    'Lineas - Producto', 'Lineas - Referencia interna', 'Categoría macro', 'Categoría padre',
    'Lineas - Cantidad', 'Lineas - Coste', 'Total', 'Costo Total', 'Margen Directo',
    'Comisión $ (Mkpl)', 'Logística $ (Mkpl)', 'Margen Final', 'Bodega Origen',
    'Facturas - Numero', 'Facturas - Documento'
]
cols_csv_existentes = [c for c in cols_csv if c in df_csv.columns]
df_csv[cols_csv_existentes].to_csv(ruta_csv, index=False, encoding='utf-8')

# XLSX (detalle + múltiples resúmenes)
ruta_xlsx = ruta_base / f"reporte_ventas_{PERIODO_NOMBRE}.xlsx"

try:
    with pd.ExcelWriter(ruta_xlsx, engine='openpyxl') as writer:
        # Hoja 1: Detalle completo
        df.to_excel(writer, sheet_name='Ventas', index=False)

        # Hoja 2-5: Resúmenes
        resumen_linea.to_excel(writer, sheet_name='Resumen Linea Negocio', index=False)
        resumen_canal.to_excel(writer, sheet_name='Resumen Canal', index=False)
        resumen_categoria.to_excel(writer, sheet_name='Resumen Categoria', index=False)
        resumen_bodega.to_excel(writer, sheet_name='Resumen Bodega', index=False)

    print(f"[OK] CSV:  {ruta_csv}")
    print(f"[OK] XLSX: {ruta_xlsx}")
    print(f"\n[OK] Hojas generadas:")
    print(f"     1. Ventas (detalle {len(df):,} líneas)")
    print(f"     2. Resumen Linea Negocio ({len(resumen_linea)} dimensiones)")
    print(f"     3. Resumen Canal ({len(resumen_canal)} dimensiones)")
    print(f"     4. Resumen Categoria ({len(resumen_categoria)} dimensiones)")
    print(f"     5. Resumen Bodega ({len(resumen_bodega)} dimensiones)")

except Exception as e:
    print(f"[ERROR] Al guardar Excel: {e}")
    print(f"[FALLBACK] Guardando solo CSV...")

# ============================================================================
# RESUMEN
# ============================================================================

print(f"\n{'='*120}")
print(f" RESUMEN - {PERIODO_NOMBRE.upper()}")
print(f"{'='*120}")

print(f"\n  Ordenes:             {len(ordenes):>8,}")
print(f"  Lineas:              {len(df):>8,}")
print(f"  Total venta:         ${df['Lineas - Subtotal'].sum():>14,.0f}")
margen_por_orden = df.drop_duplicates('Referencia de pedido')['Margen'].sum()
print(f"  Margen total:        ${margen_por_orden:>14,.0f}")
print(f"  Clientes unicos:     {df['Cliente'].nunique():>8,}")
print(f"  Canales unicos:      {df['Canal'].nunique():>8,}")
print(f"  Productos unicos:    {df['Lineas - Producto'].nunique():>8,}")

print(f"\n  Distribucion por Canal:")
for canal, grp in df.groupby('Canal')['Lineas - Subtotal'].sum().nlargest(10).items():
    print(f"    {canal:<30}: ${grp:>12,.0f}")

print(f"\n  Distribucion por Bodega Origen:")
for bod, grp in df.groupby('Bodega Origen'):
    print(f"    {bod:<20}: ${grp['Lineas - Subtotal'].sum():>12,.0f}  ({len(grp):>6,} lineas)")

print(f"\n  Top 5 Lineas de Negocio:")
for mkt, venta in df.groupby('Linea de Negocio')['Lineas - Subtotal'].sum().nlargest(5).items():
    mkt_str = str(mkt)[:45] if mkt else '(Sin linea de negocio)'
    print(f"    {mkt_str:<45}: ${venta:>12,.0f}")

print(f"\n{'='*120}")
print(f" Archivos: data/outputs/reporte_ventas_{PERIODO_NOMBRE}.csv y .xlsx")
print(f"{'='*120}\n")
