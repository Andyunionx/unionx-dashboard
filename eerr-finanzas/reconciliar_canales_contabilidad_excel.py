"""
RECONCILIACION: Identificar qué líneas de Contabilidad no están en Excel

Estrategia:
1. Extraer facturas desde Contabilidad (solo positivas)
2. Agrupar por Canal (partner_id)
3. Comparar línea a línea con Excel
4. Identificar facturas huérfanas
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

print("\n" + "="*120)
print(" RECONCILIACION: Canales Contabilidad vs Excel")
print("="*120)

# Conectar
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(str(env_path))
password = os.getenv("ANDRES_ODOO_PASSWORD")

url = "https://unionxb2b.odoo.com"
db = "bmya-innovatek-sh-prd-6981800"
usuario = "andres@grupoeter.cl"

common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, usuario, password, {})
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# PASO 1: EXTRAER DESDE CONTABILIDAD (solo positivas)
print(f"\n[PASO 1] Extrayendo desde Contabilidad (líneas positivas)...")

domain = [
    ('invoice_date', '>=', '2026-02-01'),
    ('invoice_date', '<', '2026-03-01'),
    ('move_type', '=', 'out_invoice'),
    ('state', '=', 'posted'),
]

facturas = models.execute_kw(
    db, uid, password,
    'account.move', 'search_read',
    [domain],
    {'fields': ['id', 'name', 'invoice_date', 'partner_id'],
     'limit': 100000}
)

factura_ids = [f['id'] for f in facturas]

lineas_raw = models.execute_kw(
    db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids)]],
    {'fields': ['id', 'move_id', 'product_id', 'quantity', 'price_subtotal'],
     'limit': 500000}
)

# Filtrar solo positivas
lineas_positivas = [l for l in lineas_raw if l.get('product_id') and l.get('price_subtotal', 0) > 0]

print(f"[OK] {len(lineas_positivas):,} líneas positivas con producto")

# PASO 2: AGRUPAR POR FACTURA Y CANAL
print(f"\n[PASO 2] Agrupando por factura y canal...")

facturas_dict = {f['id']: f for f in facturas}

resumen_facturas = {}

for linea in lineas_positivas:
    move_id = linea.get('move_id', [None])[0] if linea.get('move_id') else None
    if move_id not in facturas_dict:
        continue

    factura = facturas_dict[move_id]
    partner_data = factura.get('partner_id', [None, ''])
    canal = partner_data[1] if isinstance(partner_data, list) and len(partner_data) > 1 else 'SIN_CANAL'

    factura_num = factura.get('name', '')

    if factura_num not in resumen_facturas:
        resumen_facturas[factura_num] = {
            'canal': canal,
            'lineas': 0,
            'venta': 0,
            'move_id': move_id
        }

    resumen_facturas[factura_num]['lineas'] += 1
    resumen_facturas[factura_num]['venta'] += linea.get('price_subtotal', 0)

print(f"[OK] {len(resumen_facturas):,} facturas únicas")

# PASO 3: CARGAR EXCEL Y COMPARAR NÚMEROS GENERALES
print(f"\n[PASO 3] Cargando Excel...")

ruta_excel = Path(__file__).parent.parent / "datos_entrada/Raw ventas Y.xlsx"
df_raw = pd.read_excel(ruta_excel, sheet_name='RAW')
df_raw_feb = df_raw[(df_raw['Año venta'] == 2026) & (df_raw['Mes venta'] == 2)]

print(f"[OK] Excel: {len(df_raw_feb):,} líneas")

# PASO 4: COMPARAR TOP CANALES
print(f"\n[PASO 4] Comparando TOP 10 canales...")

# Canales desde Contabilidad
conta_canales = {}
for fact in resumen_facturas.values():
    canal = fact['canal']
    if canal not in conta_canales:
        conta_canales[canal] = {'lineas': 0, 'venta': 0}
    conta_canales[canal]['lineas'] += fact['lineas']
    conta_canales[canal]['venta'] += fact['venta']

# Canales desde Excel
excel_canales = df_raw_feb.groupby('Canal').agg({
    'Venta bruta': 'sum'
}).reset_index()
excel_canales.columns = ['Canal', 'Venta']
excel_canales['Lineas'] = df_raw_feb.groupby('Canal').size().values

print(f"\nExcel - TOP 10 canales:")
print(excel_canales.nlargest(10, 'Venta')[['Canal', 'Lineas', 'Venta']].to_string(index=False))

print(f"\nContabilidad - TOP 10 canales:")
conta_df = pd.DataFrame([
    {'Canal': k, 'Lineas': v['lineas'], 'Venta': v['venta']}
    for k, v in conta_canales.items()
])
print(conta_df.nlargest(10, 'Venta')[['Canal', 'Lineas', 'Venta']].to_string(index=False))

# PASO 5: IDENTIFICAR CANALES FALTANTES
print(f"\n[PASO 5] Identificando canales faltantes...")

canales_excel = set(excel_canales['Canal'].unique())
canales_conta = set(conta_df['Canal'].unique())

faltantes_en_conta = canales_excel - canales_conta
solo_en_conta = canales_conta - canales_excel

if faltantes_en_conta:
    print(f"\nCanales EN EXCEL pero NO en Contabilidad ({len(faltantes_en_conta)}):")
    for canal in sorted(faltantes_en_conta):
        excel_lineas = excel_canales[excel_canales['Canal'] == canal]['Lineas'].values[0]
        excel_venta = excel_canales[excel_canales['Canal'] == canal]['Venta'].values[0]
        print(f"  {canal:40s} | {excel_lineas:6,d} líneas | ${excel_venta:12,.0f}")

if solo_en_conta:
    print(f"\nCanales EN CONTABILIDAD pero NO en Excel ({len(solo_en_conta)}):")
    for canal in sorted(solo_en_conta)[:20]:  # Mostrar top 20
        conta_lineas = conta_df[conta_df['Canal'] == canal]['Lineas'].values[0]
        conta_venta = conta_df[conta_df['Canal'] == canal]['Venta'].values[0]
        print(f"  {canal:40s} | {conta_lineas:6,d} líneas | ${conta_venta:12,.0f}")

print(f"\n{'='*120}")
print(f"CONCLUSION")
print(f"{'='*120}")
print(f"\nCanales Excel: {len(canales_excel)}")
print(f"Canales Contabilidad: {len(canales_conta)}")
print(f"Diferencia: {len(solo_en_conta)} canales extras en Contabilidad")

print(f"\n{'='*120}")
