"""
DESCARGA REPORTE VENTAS ESTÁNDAR ODOO - MARZO 2026
Replica exactamente la estructura del reporte estándar de Odoo
para un período específico (marzo 2026)
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

print("\n" + "="*130)
print(" DESCARGA: Reporte Ventas Estándar - Marzo 2026")
print("="*130)

# Conectar Odoo
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(str(env_path))
password = os.getenv("ANDRES_ODOO_PASSWORD")

url = "https://unionxb2b.odoo.com"
db = "bmya-innovatek-sh-prd-6981800"
usuario = "andres@grupoeter.cl"

common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, usuario, password, {})
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

print(f"\n[CONECTADO - UID: {uid}]")

# ============================================================================
# EXTRAER ORDENES DE VENTA - MARZO 2026
# ============================================================================

print(f"\n[PASO 1] Extrayendo órdenes de venta (Marzo 2026)...")

domain_ordenes = [
    ('date_order', '>=', '2026-03-01'),
    ('date_order', '<', '2026-04-01'),
    ('state', 'in', ['sale', 'done']),
]

ordenes = models.execute_kw(
    db, uid, password,
    'sale.order', 'search_read',
    [domain_ordenes],
    {'fields': ['id', 'name', 'date_order', 'partner_id', 'user_id', 'team_id',
                'amount_total', 'amount_untaxed', 'state', 'fulfillment', 'warehouse_id'],
     'limit': 100000}
)

print(f"[OK] {len(ordenes):,} órdenes encontradas")

# ============================================================================
# EXTRAER LINEAS DE VENTA
# ============================================================================

print(f"\n[PASO 2] Extrayendo líneas de venta...")

orden_ids = [o['id'] for o in ordenes]

lineas = models.execute_kw(
    db, uid, password,
    'sale.order.line', 'search_read',
    [[('order_id', 'in', orden_ids)]],
    {'fields': ['id', 'order_id', 'product_id', 'product_uom_qty', 'price_unit',
                'price_subtotal', 'create_date'],
     'limit': 500000}
)

print(f"[OK] {len(lineas):,} líneas encontradas")

# ============================================================================
# PROCESAR DATOS
# ============================================================================

print(f"\n[PASO 3] Procesando datos...")

ordenes_dict = {o['id']: o for o in ordenes}

datos = []

for linea in lineas:
    try:
        order_id = linea.get('order_id', [None])[0] if linea.get('order_id') else None
        if order_id not in ordenes_dict:
            continue

        orden = ordenes_dict[order_id]

        # Datos básicos
        numero_orden = orden.get('name', '')
        fecha_orden = orden.get('date_order', '')
        estado = orden.get('state', '')

        # Cliente
        partner = orden.get('partner_id', [None, ''])
        cliente = partner[1] if isinstance(partner, list) and len(partner) > 1 else ''

        # KAM
        user = orden.get('user_id', [None, ''])
        vendedor = user[1] if isinstance(user, list) and len(user) > 1 else ''

        # Team
        team = orden.get('team_id', [None, ''])
        tipo_negocio = team[1] if isinstance(team, list) and len(team) > 1 else ''

        # Producto
        product = linea.get('product_id', [None, ''])
        producto = product[1] if isinstance(product, list) and len(product) > 1 else ''

        # Cantidades y precios
        cantidad = linea.get('product_uom_qty', 0)
        precio_unitario = linea.get('price_unit', 0)
        venta_subtotal = linea.get('price_subtotal', 0)

        # Fulfillment
        fulfillment = orden.get('fulfillment', '')

        # Bodega
        warehouse = orden.get('warehouse_id', [None, ''])
        bodega = warehouse[1] if isinstance(warehouse, list) and len(warehouse) > 1 else ''

        # Fecha
        try:
            if isinstance(fecha_orden, str):
                dt = datetime.fromisoformat(fecha_orden.replace('Z', '+00:00'))
            else:
                dt = fecha_orden
            año = dt.year
            mes = dt.month
            dia = dt.day
            semana = dt.isocalendar()[1]
        except:
            año, mes, dia, semana = 2026, 3, 1, 1

        # Crear fila
        fila = {
            'Numero': numero_orden,
            'Fecha orden': fecha_orden,
            'Año': año,
            'Mes': mes,
            'Dia': dia,
            'Semana': semana,
            'Cliente': cliente,
            'Vendedor': vendedor,
            'Team': tipo_negocio,
            'Bodega': bodega,
            'Producto': producto,
            'Cantidad': cantidad,
            'Precio unitario': precio_unitario,
            'Subtotal': venta_subtotal,
            'Total orden': orden.get('amount_total', 0),
            'Total neto': orden.get('amount_untaxed', 0),
            'Estado': estado,
            'Fulfillment': fulfillment if fulfillment else 'Bodega',
        }

        datos.append(fila)

    except Exception as e:
        print(f"[ERROR] Procesando línea: {e}")
        continue

print(f"[OK] {len(datos):,} líneas procesadas")

# ============================================================================
# GUARDAR COMO CSV Y XLSX
# ============================================================================

print(f"\n[PASO 4] Guardando reportes...")

df = pd.DataFrame(datos)

# CSV
ruta_csv = Path("data/outputs/reporte_ventas_marzo_2026.csv")
ruta_csv.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(ruta_csv, index=False)
print(f"[OK] CSV: {ruta_csv}")

# XLSX
ruta_xlsx = Path("data/outputs/reporte_ventas_marzo_2026.xlsx")
df.to_excel(ruta_xlsx, index=False, sheet_name='Ventas')
print(f"[OK] XLSX: {ruta_xlsx}")

# ============================================================================
# RESUMEN
# ============================================================================

print(f"\n{'='*130}")
print(" RESUMEN - MARZO 2026")
print(f"{'='*130}")

print(f"\nOrdenes:     {len(ordenes):,}")
print(f"Líneas:      {len(df):,}")
print(f"Venta total: ${df['Subtotal'].sum():,.0f}")
print(f"Clientes:    {df['Cliente'].nunique()}")

# Por fulfillment
print(f"\nDistribución Fulfillment:")
for full, grupo in df.groupby('Fulfillment'):
    venta = grupo['Subtotal'].sum()
    lineas = len(grupo)
    print(f"  {full:20s} : ${venta:>12,.0f} ({lineas:>6,d} líneas)")

# Top 5 clientes
print(f"\nTop 5 Clientes:")
top_clientes = df.groupby('Cliente')['Subtotal'].sum().nlargest(5)
for cliente, venta in top_clientes.items():
    print(f"  {cliente:40s} : ${venta:>12,.0f}")

print(f"\n{'='*130}")
print(f"Archivos guardados en: data/outputs/")
print(f"{'='*130}\n")
