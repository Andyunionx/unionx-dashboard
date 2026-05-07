"""
ANALISIS DETALLADO: Comparar Excel vs Contabilidad por tipo de documento

Objetivo: Encontrar exactamente dónde están las diferencias
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

print("\n" + "="*120)
print(" COMPARACION DETALLADA: Excel vs Contabilidad por Tipo de Documento")
print("="*120)

# ============================================================================
# PARTE A: EXTRAER DESDE CONTABILIDAD
# ============================================================================

print(f"\n[PASO 1] Extrayendo desde Contabilidad (con tipos de documento)...")

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(str(env_path))
password = os.getenv("ANDRES_ODOO_PASSWORD")

url = "https://unionxb2b.odoo.com"
db = "bmya-innovatek-sh-prd-6981800"
usuario = "andres@grupoeter.cl"

common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, usuario, password, {})
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# Extraer facturas con tipos
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
    {'fields': ['id', 'name', 'invoice_date', 'partner_id', 'l10n_latam_document_type_id',
                'l10n_latam_document_number', 'amount_total'],
     'limit': 100000}
)

print(f"[OK] {len(facturas):,} facturas")

# Extraer líneas
factura_ids = [f['id'] for f in facturas]

lineas = models.execute_kw(
    db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids)]],
    {'fields': ['move_id', 'product_id', 'quantity', 'price_subtotal'],
     'limit': 500000}
)

# Filtrar positivas
lineas_positivas = [l for l in lineas if l.get('product_id') and l.get('price_subtotal', 0) > 0]

print(f"[OK] {len(lineas_positivas):,} líneas positivas")

# Mapear facturas y crear resultado
facturas_dict = {f['id']: f for f in facturas}

conta_datos = []

for linea in lineas_positivas:
    move_id = linea.get('move_id', [None])[0] if linea.get('move_id') else None
    if move_id not in facturas_dict:
        continue

    factura = facturas_dict[move_id]

    # Tipo de documento
    doc_type = factura.get('l10n_latam_document_type_id', [None, ''])
    doc_type_name = doc_type[1] if isinstance(doc_type, list) else str(doc_type)

    # Canal
    partner = factura.get('partner_id', [None, ''])
    canal = partner[1] if isinstance(partner, list) else str(partner)

    conta_datos.append({
        'Documento': factura.get('name', ''),
        'Tipo Doc': doc_type_name,
        'Canal': canal,
        'Venta': linea.get('price_subtotal', 0),
    })

df_conta = pd.DataFrame(conta_datos)

print(f"[OK] DataFrame Contabilidad creado: {len(df_conta):,} filas")

# ============================================================================
# PARTE B: CARGAR EXCEL
# ============================================================================

print(f"\n[PASO 2] Cargando Excel...")

ruta_excel = Path(__file__).parent.parent / "datos_entrada/Raw ventas Y.xlsx"
df_excel = pd.read_excel(ruta_excel, sheet_name='RAW')
df_excel_feb = df_excel[(df_excel['Año venta'] == 2026) & (df_excel['Mes venta'] == 2)]

print(f"[OK] {len(df_excel_feb):,} filas")

# Ver qué columnas tiene Excel
print(f"\nColumnas Excel:")
for col in df_excel_feb.columns[:15]:
    print(f"  - {col}")

# ============================================================================
# PARTE C: ANALISIS POR TIPO DE DOCUMENTO - CONTABILIDAD
# ============================================================================

print(f"\n{'='*120}")
print(" ANALISIS CONTABILIDAD: Distribucion por Tipo de Documento")
print(f"{'='*120}")

conta_por_doc = df_conta.groupby('Tipo Doc').agg({
    'Venta': ['sum', 'count']
}).reset_index()

conta_por_doc.columns = ['Tipo Doc', 'Venta Total', 'Líneas']
conta_por_doc = conta_por_doc.sort_values('Venta Total', ascending=False)

print(f"\nDetalle por tipo de documento:")
print(conta_por_doc.to_string(index=False))

total_conta = conta_por_doc['Venta Total'].sum()
print(f"\nTOTAL: ${total_conta:,.0f} en {conta_por_doc['Líneas'].sum():,} líneas")

# ============================================================================
# PARTE D: ANALISIS EXCEL
# ============================================================================

print(f"\n{'='*120}")
print(" ANALISIS EXCEL: Distribucion por Tipo Movimiento / Documento")
print(f"{'='*120}")

# Ver si existe columna de tipo de movimiento
if 'Tipo Movimiento' in df_excel_feb.columns:
    excel_por_tipo = df_excel_feb.groupby('Tipo Movimiento').agg({
        'Venta bruta': ['sum', 'count']
    }).reset_index()

    excel_por_tipo.columns = ['Tipo Movimiento', 'Venta Total', 'Líneas']
    excel_por_tipo = excel_por_tipo.sort_values('Venta Total', ascending=False)

    print(f"\nDetalle por Tipo Movimiento:")
    print(excel_por_tipo.to_string(index=False))

    total_excel = excel_por_tipo['Venta Total'].sum()
    print(f"\nTOTAL: ${total_excel:,.0f} en {excel_por_tipo['Líneas'].sum():,} líneas")
else:
    print(f"[INFO] No existe columna 'Tipo Movimiento' en Excel")

# ============================================================================
# PARTE E: COMPARACION DIRECTA - TOP CANALES
# ============================================================================

print(f"\n{'='*120}")
print(" COMPARACION: TOP 15 CANALES (Excel vs Contabilidad)")
print(f"{'='*120}")

# Excel por canal
excel_por_canal = df_excel_feb.groupby('Canal').agg({
    'Venta bruta': 'sum'
}).reset_index()

excel_por_canal.columns = ['Canal', 'Venta Excel']
excel_por_canal = excel_por_canal.sort_values('Venta Excel', ascending=False)

# Contabilidad por canal
conta_por_canal = df_conta.groupby('Canal').agg({
    'Venta': 'sum'
}).reset_index()

conta_por_canal.columns = ['Canal', 'Venta Conta']
conta_por_canal = conta_por_canal.sort_values('Venta Conta', ascending=False)

# Merge
merged = excel_por_canal.merge(conta_por_canal, on='Canal', how='outer').fillna(0)
merged['Diferencia'] = merged['Venta Excel'] - merged['Venta Conta']
merged['Diff %'] = (merged['Diferencia'] / merged['Venta Excel'] * 100).where(merged['Venta Excel'] != 0, 0)
merged = merged.sort_values('Venta Excel', ascending=False)

print(f"\n{'Canal':<40} {'Excel':>15} {'Contab':>15} {'Diferencia':>15} {'Diff %':>10}")
print("="*95)

for idx, row in merged.head(15).iterrows():
    canal = str(row['Canal'])[:40]
    excel_val = row['Venta Excel']
    conta_val = row['Venta Conta']
    diff = row['Diferencia']
    diff_pct = row['Diff %']

    print(f"{canal:<40} ${excel_val:>14,.0f} ${conta_val:>14,.0f} ${diff:>14,.0f} {diff_pct:>9.2f}%")

# ============================================================================
# PARTE F: IDENTIFICAR DISCREPANCIAS
# ============================================================================

print(f"\n{'='*120}")
print(" DISCREPANCIAS SIGNIFICATIVAS")
print(f"{'='*120}")

# Canales en Excel pero no en Contabilidad (o con diferencia > 10%)
discrepancias = merged[
    (merged['Venta Excel'] > 0) &
    ((merged['Venta Conta'] == 0) | (abs(merged['Diff %']) > 10))
].sort_values('Venta Excel', ascending=False)

print(f"\nCanales con DIFERENCIA > 10% (primeros 20):")
print(f"\n{'Canal':<40} {'Excel':>15} {'Contab':>15} {'Diff %':>10}")
print("="*80)

for idx, row in discrepancias.head(20).iterrows():
    canal = str(row['Canal'])[:40]
    excel_val = row['Venta Excel']
    conta_val = row['Venta Conta']
    diff_pct = row['Diff %']

    print(f"{canal:<40} ${excel_val:>14,.0f} ${conta_val:>14,.0f} {diff_pct:>9.2f}%")

# ============================================================================
# PARTE G: SUMMARY
# ============================================================================

print(f"\n{'='*120}")
print(" RESUMEN NUMERICO")
print(f"{'='*120}")

total_excel = excel_por_canal['Venta Excel'].sum()
total_conta = conta_por_canal['Venta Conta'].sum()
diff_total = total_excel - total_conta
diff_pct_total = (diff_total / total_excel * 100) if total_excel > 0 else 0

print(f"\nExcel total:        ${total_excel:>15,.0f}")
print(f"Contabilidad total: ${total_conta:>15,.0f}")
print(f"Diferencia:         ${diff_total:>15,.0f} ({diff_pct_total:+.2f}%)")

# Canales que cierran
cierra = merged[abs(merged['Diff %']) < 1]
print(f"\nCanales que CIERRAN (< 1% diferencia): {len(cierra)}")

# Canales con diferencia
no_cierra = merged[abs(merged['Diff %']) >= 1]
print(f"Canales con DIFERENCIA (>= 1%): {len(no_cierra)}")

print(f"\n{'='*120}")
