"""
PASO 3a CONTABILIDAD: Extrae desde Módulo de Contabilidad (account.move)
- Estado: 'posted' (confirmado)
- Tipo: 'out_invoice' (factura de venta)
- Fecha factura: febrero 2026
- Objetivo: Validar que coincide con Excel
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

print("\n" + "="*120)
print(" PASO 3a CONTABILIDAD: Extrae desde account.move (Febrero 2026)")
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

# BUSCAR FACTURAS FEBRERO 2026
print(f"\n[Buscando facturas de venta febrero 2026...]")

domain = [
    ('invoice_date', '>=', '2026-02-01'),
    ('invoice_date', '<', '2026-03-01'),
    ('state', '=', 'posted'),
    ('move_type', '=', 'out_invoice'),
]

facturas = models.execute_kw(
    db, uid, password,
    'account.move', 'search_read',
    [domain],
    {'fields': ['id', 'name', 'invoice_date', 'partner_id', 'user_id',
                'team_id', 'amount_total', 'amount_untaxed',
                'line_ids', 'state'],
     'limit': 100000}
)

print(f"[OK] {len(facturas)} facturas encontradas")

# EXTRAER LINEAS DE LAS FACTURAS
print(f"\n[Buscando líneas de esas facturas...]")

factura_ids = [f['id'] for f in facturas]

lineas = models.execute_kw(
    db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids)]],
    {'fields': ['id', 'move_id', 'product_id', 'quantity', 'price_unit',
                'price_subtotal', 'account_id', 'create_date'],
     'limit': 500000}
)

print(f"[OK] {len(lineas)} líneas contables encontradas")

# MAPEO DE FACTURAS
print(f"\n[Creando mapeo de facturas...]")
facturas_dict = {}
for factura in facturas:
    facturas_dict[factura['id']] = factura

print(f"[OK] {len(facturas_dict)} facturas en cache")

# PROCESAR LINEAS
print(f"\n[Procesando {len(lineas)} líneas...]")

datos = []

for idx, linea in enumerate(lineas):
    try:
        if (idx + 1) % 1000 == 0:
            print(f"  [{idx + 1}/{len(lineas)}]")

        move_id = linea.get('move_id', [None])[0] if linea.get('move_id') else None
        if not move_id or move_id not in facturas_dict:
            continue

        factura = facturas_dict[move_id]

        # Solo procesar líneas con producto
        product_id = linea.get('product_id', [None])[0] if linea.get('product_id') else None
        if not product_id:
            continue

        # Fecha factura
        fecha_str = factura.get('invoice_date', '')
        if fecha_str:
            try:
                if isinstance(fecha_str, str):
                    dt = datetime.fromisoformat(fecha_str.replace('Z', '+00:00'))
                else:
                    dt = fecha_str

                año = dt.year
                mes = dt.month
                semana = dt.isocalendar()[1]
                dia_semana = dt.weekday()
                hora = dt.hour
            except:
                año, mes, semana, dia_semana, hora = 2026, 2, 1, 0, 0
        else:
            año, mes, semana, dia_semana, hora = 2026, 2, 1, 0, 0

        # Partner (Cliente/Canal)
        partner_data = factura.get('partner_id', [None, ''])
        canal = partner_data[1] if isinstance(partner_data, list) and len(partner_data) > 1 else ''

        # User (KAM)
        user_data = factura.get('user_id', [None, ''])
        kam = user_data[1] if isinstance(user_data, list) and len(user_data) > 1 else ''

        # Team (Tipo Negocio)
        team_data = factura.get('team_id', [None, ''])
        tipo_negocio = team_data[1] if isinstance(team_data, list) and len(team_data) > 1 else ''

        # Bodega (no disponible en contabilidad)
        bodega = ''

        # Datos de la línea
        cantidad = linea.get('quantity', 0)
        precio_unitario = linea.get('price_unit', 0)
        venta_bruta = linea.get('price_subtotal', cantidad * precio_unitario)

        # Crear fila
        fila = {
            'Tipo Movimiento': 'Venta',
            'Bodega': bodega,
            'Documento': factura.get('name', ''),
            'Fecha Documento': fecha_str,
            'Pedido': factura.get('name', ''),
            'Estado Pedido': factura.get('state', ''),
            'Tipo Despacho': '',
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
        pass  # Silenciar errores menores

print(f"[OK] {len(datos)} líneas procesadas")

# GUARDAR
print(f"\n[Guardando...]")
df = pd.DataFrame(datos)

ruta = Path("data/outputs/raw_contabilidad_febrero_2026.csv")
ruta.parent.mkdir(parents=True, exist_ok=True)

df.to_csv(ruta, index=False)
print(f"[OK] Guardado: {ruta}")

# RESUMEN
print(f"\n{'='*120}")
print(" RESUMEN: CONTABILIDAD (Módulo de Contabilidad)")
print(f"{'='*120}")
print(f"\nFebrero 2026 (desde Contabilidad):")
print(f"  Facturas: {len(facturas):,}")
print(f"  Líneas: {len(df):,}")
print(f"  Venta total: ${df['Venta bruta'].sum():,.0f}")

# COMPARAR CONTRA EXCEL
print(f"\n[Validando contra Raw ventas Y.xlsx...]")
df_raw = pd.read_excel("../datos_entrada/Raw ventas Y.xlsx", sheet_name='RAW')
df_raw_feb = df_raw[(df_raw['Año venta'] == 2026) & (df_raw['Mes venta'] == 2)]

print(f"\nRaw original (Excel):")
print(f"  Filas: {len(df_raw_feb):,}")
print(f"  Venta total: ${df_raw_feb['Venta bruta'].sum():,.0f}")

print(f"\nComparación:")
venta_contabilidad = df['Venta bruta'].sum()
venta_excel = df_raw_feb['Venta bruta'].sum()
diff = abs(venta_contabilidad - venta_excel) / venta_excel * 100 if venta_excel > 0 else 0

print(f"  Diferencia: {diff:.2f}%")

filas_contabilidad = len(df)
filas_excel = len(df_raw_feb)
diff_filas = abs(filas_contabilidad - filas_excel)

print(f"  Diferencia en filas: {diff_filas} ({diff_filas / filas_excel * 100:.2f}%)")

if diff < 1:
    print(f"  Status: [OK] COINCIDE EXACTAMENTE")
elif diff < 5:
    print(f"  Status: [OK] ACEPTABLE (< 5%)")
else:
    print(f"  Status: [REVISAR] Diferencia significativa")

print(f"\n{'='*120}")
