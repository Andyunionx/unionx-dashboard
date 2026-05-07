"""
RECONCILIACION FINAL: Excel vs Contabilidad vs Ventas
Análisis profundo con mapeo de canales y hallazgos detallados
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv
from difflib import SequenceMatcher

print("\n" + "="*130)
print(" RECONCILIACION FINAL: Excel vs Contabilidad vs Ventas (Febrero 2026)")
print("="*130)

# ============================================================================
# CONEXION ODOO
# ============================================================================

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
# PASO 1: CARGAR EXCEL Y OBTENER LISTA DE CANALES LIMPIOS
# ============================================================================

print(f"\n{'='*130}")
print(" PASO 1: CARGAR EXCEL")
print(f"{'='*130}")

ruta_excel = Path(__file__).parent.parent / "datos_entrada/Raw ventas Y.xlsx"
df_excel = pd.read_excel(ruta_excel, sheet_name='RAW')
df_excel_feb = df_excel[(df_excel['Año venta'] == 2026) & (df_excel['Mes venta'] == 2)]

canales_excel = df_excel_feb['Canal'].unique()
print(f"\n[OK] Excel cargado: {len(df_excel_feb):,} líneas")
print(f"[OK] {len(canales_excel)} canales únicos")

# Crear mapping de Excel
excel_mapping = df_excel_feb.groupby('Canal').agg({
    'Venta bruta': 'sum'
}).reset_index()
excel_mapping.columns = ['Canal', 'Venta Excel']
excel_mapping = excel_mapping.sort_values('Venta Excel', ascending=False)

print(f"\nTop 10 canales Excel:")
for idx, row in excel_mapping.head(10).iterrows():
    print(f"  {row['Canal']:40s} : ${row['Venta Excel']:>12,.0f}")

# ============================================================================
# PASO 2: EXTRAER CONTABILIDAD
# ============================================================================

print(f"\n{'='*130}")
print(" PASO 2: EXTRAER CONTABILIDAD")
print(f"{'='*130}")

domain_conta = [
    ('invoice_date', '>=', '2026-02-01'),
    ('invoice_date', '<', '2026-03-01'),
    ('move_type', '=', 'out_invoice'),
    ('state', '=', 'posted'),
]

facturas_conta = models.execute_kw(
    db, uid, password,
    'account.move', 'search_read',
    [domain_conta],
    {'fields': ['id', 'name', 'partner_id', 'l10n_latam_document_type_id', 'amount_total'],
     'limit': 100000}
)

factura_ids_conta = [f['id'] for f in facturas_conta]

lineas_conta = models.execute_kw(
    db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids_conta)]],
    {'fields': ['move_id', 'product_id', 'quantity', 'price_subtotal'],
     'limit': 500000}
)

facturas_dict = {f['id']: f for f in facturas_conta}

# Procesar contabilidad
conta_datos = []
for linea in lineas_conta:
    if not linea.get('product_id') or linea.get('price_subtotal', 0) <= 0:
        continue

    move_id = linea.get('move_id', [None])[0] if linea.get('move_id') else None
    if move_id not in facturas_dict:
        continue

    factura = facturas_dict[move_id]
    partner = factura.get('partner_id', [None, ''])
    canal_odoo = partner[1] if isinstance(partner, list) and len(partner) > 1 else ''

    # Tipo documento
    doc_type = factura.get('l10n_latam_document_type_id', [None, ''])
    doc_type_name = doc_type[1] if isinstance(doc_type, list) else ''

    conta_datos.append({
        'Canal Odoo': canal_odoo,
        'Tipo Doc': doc_type_name,
        'Venta': linea.get('price_subtotal', 0),
    })

df_conta = pd.DataFrame(conta_datos)
print(f"\n[OK] Contabilidad extraída: {len(df_conta):,} líneas")
print(f"[OK] ${df_conta['Venta'].sum():,.0f} en ventas")

canales_odoo = df_conta['Canal Odoo'].unique()
print(f"[OK] {len(canales_odoo)} canales únicos en Odoo")

# ============================================================================
# PASO 3: CREAR MAPEO DE CANALES AUTOMATICO
# ============================================================================

print(f"\n{'='*130}")
print(" PASO 3: MAPEO AUTOMATICO DE CANALES (Fuzzy Matching)")
print(f"{'='*130}")

def similarity(a, b):
    """Calcula similitud entre dos strings (0-1)"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def normalizador_canal(canal_odoo):
    """Extrae el 'core' del nombre de canal en Odoo"""
    # Remover prefijos comunes
    canal_clean = canal_odoo.strip()

    # "Cliente XXX" -> "XXX"
    if canal_clean.startswith('Cliente '):
        canal_clean = canal_clean[8:]

    # "XXX Fidelizacion SPA" -> "XXX"
    if 'Fidelizacion' in canal_clean:
        canal_clean = canal_clean.replace('Fidelizacion SPA', '').strip()
        canal_clean = canal_clean.replace('Fidelizacion', '').strip()

    # "XXX SPA" -> "XXX"
    if canal_clean.endswith(' SPA'):
        canal_clean = canal_clean[:-4].strip()

    # "XXX Spa" -> "XXX"
    if canal_clean.endswith(' Spa'):
        canal_clean = canal_clean[:-4].strip()

    # "XXX LIMITADA" -> "XXX"
    if canal_clean.endswith(' LIMITADA'):
        canal_clean = canal_clean[:-9].strip()

    # "XXX Limitada" -> "XXX"
    if canal_clean.endswith(' Limitada'):
        canal_clean = canal_clean[:-9].strip()

    # "XXX ltda." -> "XXX"
    if 'ltda.' in canal_clean.lower():
        canal_clean = canal_clean.replace('ltda.', '').replace('LTDA.', '').strip()

    # "XXX Ltda" -> "XXX"
    if canal_clean.endswith(' Ltda'):
        canal_clean = canal_clean[:-5].strip()

    return canal_clean

def mapear_canal(canal_odoo, canales_excel_list):
    """Mapea un canal de Odoo al más similar en Excel"""
    if not canal_odoo:
        return None

    canal_norm = normalizador_canal(canal_odoo)

    # Búsqueda exacta primero
    for canal_excel in canales_excel_list:
        if canal_norm.lower() == canal_excel.lower():
            return canal_excel

    # Búsqueda por similitud
    mejores = []
    for canal_excel in canales_excel_list:
        sim = similarity(canal_norm, canal_excel)
        mejores.append((canal_excel, sim))

    mejores.sort(key=lambda x: x[1], reverse=True)

    if mejores[0][1] > 0.6:  # Threshold de 60%
        return mejores[0][0]

    return None

# Crear mapping table
mapping_table = {}
canales_sin_mapeo = []

for canal_odoo in sorted(canales_odoo):
    canal_excel = mapear_canal(canal_odoo, list(canales_excel))

    if canal_excel:
        mapping_table[canal_odoo] = canal_excel
        print(f"  {canal_odoo:40s} => {canal_excel}")
    else:
        canales_sin_mapeo.append(canal_odoo)

if canales_sin_mapeo:
    print(f"\n[AVISO] {len(canales_sin_mapeo)} canales sin mapeo:")
    for canal in canales_sin_mapeo[:10]:
        print(f"  - {canal}")

# Aplicar mapping
df_conta['Canal Mapeado'] = df_conta['Canal Odoo'].map(mapping_table)

canales_mapeados = df_conta[df_conta['Canal Mapeado'].notna()].shape[0]
canales_no_mapeados = df_conta[df_conta['Canal Mapeado'].isna()].shape[0]

print(f"\n[OK] {canales_mapeados:,} líneas mapeadas")
print(f"[OK] {canales_no_mapeados:,} líneas SIN mapeo")

# ============================================================================
# PASO 4: RECONCILIACION CONTABILIDAD vs EXCEL
# ============================================================================

print(f"\n{'='*130}")
print(" PASO 4: RECONCILIACION CONTABILIDAD vs EXCEL")
print(f"{'='*130}")

# Agrupar Contabilidad por canal mapeado
conta_por_canal = df_conta[df_conta['Canal Mapeado'].notna()].groupby('Canal Mapeado').agg({
    'Venta': 'sum'
}).reset_index()
conta_por_canal.columns = ['Canal', 'Venta Contab']

# Merge con Excel
reconciliacion = excel_mapping.merge(conta_por_canal, on='Canal', how='outer').fillna(0)
reconciliacion['Diferencia'] = reconciliacion['Venta Excel'] - reconciliacion['Venta Contab']
reconciliacion['Diff %'] = (reconciliacion['Diferencia'] / reconciliacion['Venta Excel'] * 100).where(reconciliacion['Venta Excel'] > 0, 0)
reconciliacion = reconciliacion.sort_values('Venta Excel', ascending=False)

print(f"\n{'CANAL':<40} {'EXCEL':>15} {'CONTAB':>15} {'DIFERENCIA':>15} {'DIFF %':>10}")
print("="*95)

for idx, row in reconciliacion.head(20).iterrows():
    canal = str(row['Canal'])[:40]
    excel = row['Venta Excel']
    contab = row['Venta Contab']
    diff = row['Diferencia']
    diff_pct = row['Diff %']

    if excel > 0:
        print(f"{canal:<40} ${excel:>14,.0f} ${contab:>14,.0f} ${diff:>14,.0f} {diff_pct:>9.2f}%")

total_excel = reconciliacion['Venta Excel'].sum()
total_contab = reconciliacion['Venta Contab'].sum()

print("="*95)
print(f"{'TOTAL':<40} ${total_excel:>14,.0f} ${total_contab:>14,.0f} ${total_excel-total_contab:>14,.0f}")

# ============================================================================
# PASO 5: EXTRAER VENTAS
# ============================================================================

print(f"\n{'='*130}")
print(" PASO 5: EXTRAER VENTAS (sale.order.line)")
print(f"{'='*130}")

domain_ventas = [
    ('create_date', '>=', '2026-02-01'),
    ('create_date', '<', '2026-03-01'),
    ('state', 'in', ['sale', 'done']),
]

ordenes_ventas = models.execute_kw(
    db, uid, password,
    'sale.order', 'search_read',
    [domain_ventas],
    {'fields': ['id', 'partner_id', 'fulfillment', 'state'],
     'limit': 100000}
)

orden_ids = [o['id'] for o in ordenes_ventas]

lineas_ventas = models.execute_kw(
    db, uid, password,
    'sale.order.line', 'search_read',
    [[('order_id', 'in', orden_ids)]],
    {'fields': ['order_id', 'product_id', 'product_uom_qty', 'price_subtotal'],
     'limit': 500000}
)

ordenes_dict = {o['id']: o for o in ordenes_ventas}

# Procesar ventas
ventas_datos = []
for linea in lineas_ventas:
    if not linea.get('product_id') or linea.get('price_subtotal', 0) <= 0:
        continue

    order_id = linea.get('order_id', [None])[0] if linea.get('order_id') else None
    if order_id not in ordenes_dict:
        continue

    orden = ordenes_dict[order_id]
    partner = orden.get('partner_id', [None, ''])
    canal_odoo = partner[1] if isinstance(partner, list) and len(partner) > 1 else ''
    fulfillment = orden.get('fulfillment', '')

    ventas_datos.append({
        'Canal Odoo': canal_odoo,
        'Fulfillment': fulfillment if fulfillment else 'Bodega',
        'Venta': linea.get('price_subtotal', 0),
    })

df_ventas = pd.DataFrame(ventas_datos)
print(f"\n[OK] Ventas extraída: {len(df_ventas):,} líneas")
print(f"[OK] ${df_ventas['Venta'].sum():,.0f} en ventas")

# Aplicar mapping
df_ventas['Canal Mapeado'] = df_ventas['Canal Odoo'].map(mapping_table)

ventas_mapeadas = df_ventas[df_ventas['Canal Mapeado'].notna()].shape[0]
ventas_no_mapeadas = df_ventas[df_ventas['Canal Mapeado'].isna()].shape[0]

print(f"[OK] {ventas_mapeadas:,} líneas mapeadas")
print(f"[OK] {ventas_no_mapeadas:,} líneas SIN mapeo")

# ============================================================================
# PASO 6: COMPARACION CONTABILIDAD vs VENTAS
# ============================================================================

print(f"\n{'='*130}")
print(" PASO 6: COMPARACION CONTABILIDAD vs VENTAS (por modalidad)")
print(f"{'='*130}")

# Agrupar por canal y tipo de documento (Contabilidad)
conta_detalle = df_conta[df_conta['Canal Mapeado'].notna()].groupby(['Canal Mapeado', 'Tipo Doc']).agg({
    'Venta': 'sum'
}).reset_index()

# Agrupar por canal y fulfillment (Ventas)
ventas_detalle = df_ventas[df_ventas['Canal Mapeado'].notna()].groupby(['Canal Mapeado', 'Fulfillment']).agg({
    'Venta': 'sum'
}).reset_index()

print(f"\nContabilidad - Distribución por Tipo de Documento:")
conta_por_doc = df_conta[df_conta['Canal Mapeado'].notna()].groupby('Tipo Doc').agg({
    'Venta': 'sum'
}).reset_index()

for idx, row in conta_por_doc.iterrows():
    print(f"  {row['Tipo Doc']:35s} : ${row['Venta']:>12,.0f}")

print(f"\nVentas - Distribución por Fulfillment:")
ventas_por_full = df_ventas[df_ventas['Canal Mapeado'].notna()].groupby('Fulfillment').agg({
    'Venta': 'sum'
}).reset_index()

for idx, row in ventas_por_full.iterrows():
    print(f"  {row['Fulfillment']:35s} : ${row['Venta']:>12,.0f}")

# ============================================================================
# PASO 7: RESUMEN FINAL
# ============================================================================

print(f"\n{'='*130}")
print(" RESUMEN FINAL - TOTALES")
print(f"{'='*130}")

total_excel_final = df_excel_feb['Venta bruta'].sum()
total_conta_mapeado = df_conta[df_conta['Canal Mapeado'].notna()]['Venta'].sum()
total_conta_sin_mapeo = df_conta[df_conta['Canal Mapeado'].isna()]['Venta'].sum()
total_conta_total = df_conta['Venta'].sum()
total_ventas_mapeado = df_ventas[df_ventas['Canal Mapeado'].notna()]['Venta'].sum()

print(f"\n{'MÉTRICA':<50} {'MONTO':>20} {'% vs EXCEL':>15}")
print("="*85)
print(f"{'Excel (Baseline)':<50} ${total_excel_final:>19,.0f} {0:>14.2f}%")
print(f"{'Contabilidad (mapeado)':<50} ${total_conta_mapeado:>19,.0f} {(total_conta_mapeado/total_excel_final-1)*100:>14.2f}%")
print(f"{'Contabilidad (sin mapeo)':<50} ${total_conta_sin_mapeo:>19,.0f} {(total_conta_sin_mapeo/total_excel_final-1)*100:>14.2f}%")
print(f"{'Contabilidad (TOTAL)':<50} ${total_conta_total:>19,.0f} {(total_conta_total/total_excel_final-1)*100:>14.2f}%")
print(f"{'Ventas (mapeado)':<50} ${total_ventas_mapeado:>19,.0f} {(total_ventas_mapeado/total_excel_final-1)*100:>14.2f}%")

# ============================================================================
# PASO 8: ANALISIS DE DIFERENCIAS RAIZ
# ============================================================================

print(f"\n{'='*130}")
print(" ANALISIS DE DIFERENCIAS - CAUSAS RAIZ")
print(f"{'='*130}")

print(f"\n1. CONTABILIDAD vs EXCEL (después del mapeo):")
print(f"   Excel:        ${total_excel_final:>12,.0f}")
print(f"   Contabilidad: ${total_conta_mapeado:>12,.0f}")
print(f"   Diferencia:   ${total_excel_final - total_conta_mapeado:>12,.0f} ({(total_excel_final - total_conta_mapeado)/total_excel_final*100:+.2f}%)")

diff_Excel_Conta = total_excel_final - total_conta_mapeado
print(f"\n   Hipótesis: La diferencia de ${abs(diff_Excel_Conta):,.0f} puede ser por:")
if diff_Excel_Conta > 0:
    print(f"   - Líneas en Excel que NO están en Contabilidad (canceladas, rechazadas, sin facturar)")
    print(f"   - Devoluciones en Contabilidad que restan venta (ya consideradas en Excel)")
    print(f"   - Diferencia de fechas (fecha_documento vs fecha_factura)")
else:
    print(f"   - Contabilidad incluye transacciones que Excel excluye (ajustes, créditos)")

print(f"\n2. CONTABILIDAD vs VENTAS (después del mapeo):")
print(f"   Contabilidad: ${total_conta_mapeado:>12,.0f}")
print(f"   Ventas:       ${total_ventas_mapeado:>12,.0f}")
print(f"   Diferencia:   ${total_conta_mapeado - total_ventas_mapeado:>12,.0f} ({(total_conta_mapeado - total_ventas_mapeado)/total_conta_mapeado*100:+.2f}%)")

diff_Conta_Ventas = total_conta_mapeado - total_ventas_mapeado
print(f"\n   Hipótesis: La diferencia de ${abs(diff_Conta_Ventas):,.0f} puede ser por:")
if diff_Conta_Ventas > 0:
    print(f"   - Devoluciones/Notas de Crédito en Contabilidad (líneas negativas)")
    print(f"   - Pedidos que pasaron a Contabilidad pero NO a Ventas (fulfillment de terceros)")
    print(f"   - Estados: Ventas filtra por 'sale/done' pero Contabilidad incluye 'posted'")
else:
    print(f"   - Ventas incluye órdenes sin facturar aún (estado 'para facturar')")

print(f"\n3. EXCEL vs VENTAS (la cadena completa):")
print(f"   Excel:  ${total_excel_final:>12,.0f}")
print(f"   Ventas: ${total_ventas_mapeado:>12,.0f}")
print(f"   Diferencia: ${total_excel_final - total_ventas_mapeado:>12,.0f} ({(total_excel_final - total_ventas_mapeado)/total_excel_final*100:+.2f}%)")

print(f"\n{'='*130}")
print(" CONCLUSION")
print(f"{'='*130}")

print(f"\nLa cadena de datos es:")
print(f"  Ventas (sale.order) => Contabilidad (account.move) => Excel (Raw ventas)")
print(f"\nDisipadores de valor:")
print(f"  - Ordenes 'para facturar': En Ventas pero no en Contabilidad")
print(f"  - Devoluciones/Notas de Credito: En Contabilidad restando venta")
print(f"  - Fulfillment de terceros: Van directo a Contabilidad, bypass Ventas")
print(f"  - Diferencia de mapeo: {len(mapping_table)} canales mapeados de {len(canales_odoo)} unicos en Odoo")

print(f"\n{'='*130}")
