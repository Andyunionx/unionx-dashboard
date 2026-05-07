"""
PASO 3a SIMPLE: Extrae SOLO lo que existe en Odoo
Mantiene máxima compatibilidad con Raw ventas Y.xlsx
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

print("\n" + "="*120)
print(" PASO 3a SIMPLE: Extrae RAW desde Odoo (Campos confirmados)")
print("="*120)

# Conectar
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(str(env_path))
password = os.getenv("ANDRES_ODOO_PASSWORD")

if not password:
    print("[ERROR] Password no configurado")
    exit(1)

url = "https://unionxb2b.odoo.com"
db = "bmya-innovatek-sh-prd-6981800"
usuario = "andres@grupoeter.cl"

print(f"\n[Conectando a Odoo...]")
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, usuario, password, {})

if not uid:
    print("[ERROR] Autenticación fallida")
    exit(1)

print(f"[OK] Conectado (UID: {uid})")

models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# BUSCAR ORDENES DE FEBRERO 2026 (para obtener los IDs)
print(f"\n[Buscando órdenes febrero 2026...]")

domain = [
    ('create_date', '>=', '2026-02-01'),
    ('create_date', '<', '2026-03-01'),
    ('state', 'in', ['sale', 'done']),
]

orden_ids = models.execute_kw(
    db, uid, password,
    'sale.order', 'search',
    [domain],
    {'limit': 100000}
)

print(f"[OK] {len(orden_ids)} órdenes encontradas")

# EXTRAER LINEAS DE ESAS ORDENES
print(f"\n[Buscando líneas de esas órdenes...]")

lineas = models.execute_kw(
    db, uid, password,
    'sale.order.line', 'search_read',
    [[('order_id', 'in', orden_ids)]],
    {'fields': ['id', 'order_id', 'product_id', 'product_uom_qty', 'price_unit',
                'price_subtotal', 'create_date'],
     'limit': 500000}
)

print(f"[OK] {len(lineas)} líneas de productos encontradas")

# OBTENER DATOS DE ORDENES (cache)
print(f"\n[Cargando datos de órdenes...]")
ordenes_dict = {}
ordenes_data = models.execute_kw(
    db, uid, password,
    'sale.order', 'search_read',
    [[('id', 'in', orden_ids)]],
    {'fields': ['id', 'name', 'create_date', 'state', 'partner_id', 'user_id',
                'team_id', 'warehouse_id', 'amount_total', 'fulfillment'],
     'limit': 100000}
)

for orden in ordenes_data:
    ordenes_dict[orden['id']] = orden

print(f"[OK] {len(ordenes_dict)} órdenes en cache")

# PROCESAR LINEAS
print(f"\n[Procesando {len(lineas)} líneas...]")

datos = []

for idx, linea in enumerate(lineas):
    try:
        if (idx + 1) % 1000 == 0:
            print(f"  [{idx + 1}/{len(lineas)}]")

        order_id = linea.get('order_id', [None])[0] if linea.get('order_id') else None
        if not order_id or order_id not in ordenes_dict:
            continue

        orden = ordenes_dict[order_id]

        # Fecha
        fecha_str = orden.get('create_date', '')
        if fecha_str:
            try:
                dt = datetime.fromisoformat(fecha_str.replace('Z', '+00:00'))
                año = dt.year
                mes = dt.month
                semana = dt.isocalendar()[1]
                dia_semana = dt.weekday()
                hora = dt.hour
            except:
                año, mes, semana, dia_semana, hora = 2026, 2, 1, 0, 0
        else:
            año, mes, semana, dia_semana, hora = 2026, 2, 1, 0, 0

        # Partner (Canal)
        partner_data = orden.get('partner_id', [None, ''])
        canal = partner_data[1] if isinstance(partner_data, list) and len(partner_data) > 1 else ''

        # User (KAM)
        user_data = orden.get('user_id', [None, ''])
        kam = user_data[1] if isinstance(user_data, list) and len(user_data) > 1 else ''

        # Team (Tipo Negocio)
        team_data = orden.get('team_id', [None, ''])
        tipo_negocio = team_data[1] if isinstance(team_data, list) and len(team_data) > 1 else ''

        # Warehouse (Bodega)
        warehouse_data = orden.get('warehouse_id', [None, ''])
        bodega = warehouse_data[1] if isinstance(warehouse_data, list) and len(warehouse_data) > 1 else ''

        # Datos de la línea
        cantidad = linea.get('product_uom_qty', 0)
        precio_unitario = linea.get('price_unit', 0)
        venta_bruta = linea.get('price_subtotal', cantidad * precio_unitario)

        # Crear fila
        fila = {
            'Tipo Movimiento': 'Venta',
            'Bodega': bodega,
            'Documento': '',  # No disponible
            'Fecha Documento': fecha_str,
            'Pedido': orden.get('name', ''),
            'Estado Pedido': orden.get('state', ''),
            'Tipo Despacho': orden.get('fulfillment', ''),
            'SKU': '',
            'Canal': canal,
            'Fecha Venta': fecha_str,
            'Hora Venta': f"{hora:02d}:00:00" if hora else '',
            'Producto': '',
            'Categoría macro': '',
            'Categoría padre': '',
            'Categoría hijo': '',
            'Categoría comercial': '',
            'Estado SKU': '',
            'Pack': '',
            'Marca': '',
            'Proveedor': '',
            'Tipo Marca': '',
            'Tipo Compra': '',
            'Tipo Negocio': tipo_negocio,
            'KAM': kam,
            'Estado Canal': '',
            'Año venta': año,
            'Mes venta': mes,
            'Semana venta': semana,
            'Día semana': dia_semana,
            'Hora venta': hora,
            'Cantidad': cantidad,
            'Venta bruta': venta_bruta,
            'Costo Unitario': 0,
            'Costo Total': 0,
            'Margen Front': venta_bruta,
            'Comision %': 0,
            'Comisión': 0,
            'Logística': 0,
            'Marketing': 0,
            'Mg final': venta_bruta,
        }

        datos.append(fila)

    except Exception as e:
        print(f"  [AVISO] Error en línea {idx}: {str(e)[:50]}")

print(f"[OK] {len(datos)} órdenes procesadas")

# GUARDAR
print(f"\n[Guardando...]")
df = pd.DataFrame(datos)

ruta = Path("data/outputs/raw_odoo_febrero_2026.csv")
ruta.parent.mkdir(parents=True, exist_ok=True)

df.to_csv(ruta, index=False)
print(f"[OK] Guardado: {ruta}")

# RESUMEN
print(f"\n{'='*120}")
print(" RESUMEN")
print(f"{'='*120}")
print(f"\nFebrero 2026 (desde Odoo):")
print(f"  Órdenes: {len(df):,}")
print(f"  Venta total: ${df['Venta bruta'].sum():,.0f}")
print(f"  Margen total: ${df['Margen Front'].sum():,.0f}")

# COMPARAR CONTRA RAW EXCEL
print(f"\n[Validando contra Raw ventas Y.xlsx...]")
df_raw = pd.read_excel("../datos_entrada/Raw ventas Y.xlsx", sheet_name='RAW')
df_raw_feb = df_raw[(df_raw['Año venta'] == 2026) & (df_raw['Mes venta'] == 2)]

print(f"\nRaw original (Excel):")
print(f"  Filas: {len(df_raw_feb):,}")
print(f"  Venta total: ${df_raw_feb['Venta bruta'].sum():,.0f}")

print(f"\nComparación:")
venta_odoo = df['Venta bruta'].sum()
venta_excel = df_raw_feb['Venta bruta'].sum()
diff = abs(venta_odoo - venta_excel) / venta_excel * 100 if venta_excel > 0 else 0

print(f"  Diferencia: {diff:.2f}%")

if diff < 5:
    print(f"  Status: RAZONABLE (pequeñas diferencias por estructura)")
else:
    print(f"  Status: REVISAR (diferencia significativa)")

print(f"\n{'='*120}")
print(" LISTO PARA VALIDACION Y INYECCION")
print(f"{'='*120}")
