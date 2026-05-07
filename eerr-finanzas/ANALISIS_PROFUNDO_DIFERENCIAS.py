"""
ANALISIS PROFUNDO: Causa raíz de cada diferencia
- Qué está faltando por canal
- Qué líneas no se mapean
- Patrones de discrepancia
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
import os
from dotenv import load_dotenv

print("\n" + "="*130)
print(" ANALISIS PROFUNDO: Causa Raíz de Diferencias")
print("="*130)

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

# ============================================================================
# CARGAR DATOS
# ============================================================================

print(f"\n[CARGANDO DATOS...]")

# Excel
ruta_excel = Path(__file__).parent.parent / "datos_entrada/Raw ventas Y.xlsx"
df_excel = pd.read_excel(ruta_excel, sheet_name='RAW')
df_excel_feb = df_excel[(df_excel['Año venta'] == 2026) & (df_excel['Mes venta'] == 2)].copy()

# Contabilidad
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
    {'fields': ['id', 'name', 'partner_id', 'l10n_latam_document_type_id', 'amount_total'],
     'limit': 100000}
)

factura_ids = [f['id'] for f in facturas]

lineas = models.execute_kw(
    db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids)]],
    {'fields': ['move_id', 'product_id', 'quantity', 'price_subtotal'],
     'limit': 500000}
)

facturas_dict = {f['id']: f for f in facturas}

conta_datos = []
for linea in lineas:
    if not linea.get('product_id') or linea.get('price_subtotal', 0) <= 0:
        continue

    move_id = linea.get('move_id', [None])[0] if linea.get('move_id') else None
    if move_id not in facturas_dict:
        continue

    factura = facturas_dict[move_id]
    partner = factura.get('partner_id', [None, ''])
    canal_odoo = partner[1] if isinstance(partner, list) else ''

    conta_datos.append({
        'Canal Odoo': canal_odoo,
        'Documento': factura.get('name', ''),
        'Venta': linea.get('price_subtotal', 0),
    })

df_conta = pd.DataFrame(conta_datos)

print(f"[OK] Datos cargados")

# ============================================================================
# PARTE 1: ANALIZAR CANALES CON DIFERENCIA > 10%
# ============================================================================

print(f"\n{'='*130}")
print(" PARTE 1: CANALES CON DIFERENCIA SIGNIFICATIVA")
print(f"{'='*130}")

# Agrupar ambos
excel_por_canal = df_excel_feb.groupby('Canal')['Venta bruta'].sum().reset_index()
excel_por_canal.columns = ['Canal', 'Venta Excel']

conta_por_canal = df_conta.groupby('Canal Odoo')['Venta'].sum().reset_index()
conta_por_canal.columns = ['Canal Odoo', 'Venta Conta']

# Top 5 canales Excel con mayor diferencia
top_canales_excel = excel_por_canal.nlargest(10, 'Venta Excel')

print(f"\nTOP 5 CANALES CON MAYOR IMPACTO EN DIFERENCIA:")

for idx, (_, row_excel) in enumerate(top_canales_excel.head(5).iterrows()):
    canal = row_excel['Canal']
    venta_excel = row_excel['Venta Excel']

    # Buscar en contabilidad
    conta_match = conta_por_canal[conta_por_canal['Canal Odoo'].str.contains(canal, case=False, na=False)]

    print(f"\n{idx+1}. {canal}")
    print(f"   Excel: ${venta_excel:,.0f}")
    print(f"   Contabilidad (búsqueda): {len(conta_match)} registros encontrados")

    if len(conta_match) > 0:
        venta_conta_total = conta_match['Venta Conta'].sum()
        print(f"   Venta Contab: ${venta_conta_total:,.0f}")
        print(f"   Diferencia: ${venta_excel - venta_conta_total:,.0f} ({(venta_excel - venta_conta_total)/venta_excel*100:.1f}%)")

        for _, row_conta in conta_match.iterrows():
            print(f"     - {row_conta['Canal Odoo']}: ${row_conta['Venta Conta']:,.0f}")
    else:
        print(f"   ** NO SE ENCUENTRA EN CONTABILIDAD **")
        print(f"   Diferencia: ${venta_excel:,.0f} (100%)")

# ============================================================================
# PARTE 2: ANALIZAR DOCUMENTOS NO MAPEADOS
# ============================================================================

print(f"\n{'='*130}")
print(" PARTE 2: LINEAS NO MAPEADAS EN CONTABILIDAD")
print(f"{'='*130}")

# Canales en Contabilidad que no están en Excel
canales_excel_list = set(excel_por_canal['Canal'].unique())
canales_conta_list = set(conta_por_canal['Canal Odoo'].unique())

canales_solo_conta = canales_conta_list - canales_excel_list

print(f"\nCanales EN Contabilidad pero NO en Excel: {len(canales_solo_conta)}")

solo_conta_venta = conta_por_canal[conta_por_canal['Canal Odoo'].isin(canales_solo_conta)].copy()
solo_conta_venta = solo_conta_venta.sort_values('Venta Conta', ascending=False)

print(f"\nTop 15 por venta:")
total_solo_conta = 0
for idx, row in solo_conta_venta.head(15).iterrows():
    print(f"  {row['Canal Odoo']:40s} : ${row['Venta Conta']:>12,.0f}")
    total_solo_conta += row['Venta Conta']

total_remaining = solo_conta_venta[15:]['Venta Conta'].sum()
print(f"  {'[Otros ' + str(len(canales_solo_conta)-15) + ' canales]':40s} : ${total_remaining:>12,.0f}")
print(f"  {'TOTAL NO MAPEADO':40s} : ${total_solo_conta + total_remaining:>12,.0f}")

# ============================================================================
# PARTE 3: DISTRIBUCION DE DEVOLUCIONES Y AJUSTES
# ============================================================================

print(f"\n{'='*130}")
print(" PARTE 3: ANALISIS DE DEVOLUCIONES Y AJUSTES")
print(f"{'='*130}")

# Excel
excel_ventas = df_excel_feb[df_excel_feb['Tipo Movimiento'] == 'Venta']['Venta bruta'].sum()
excel_devoluciones = df_excel_feb[df_excel_feb['Tipo Movimiento'] == 'Devolucion']['Venta bruta'].sum()

print(f"\nExcel - Tipo Movimiento:")
print(f"  Ventas:     ${excel_ventas:>12,.0f}")
print(f"  Devoluciones: ${excel_devoluciones:>12,.0f}")
print(f"  NETO:       ${excel_ventas + excel_devoluciones:>12,.0f}")

# Contabilidad por tipo de documento
conta_positivas = df_conta[df_conta['Venta'] > 0].copy()
conta_negativas = df_conta[df_conta['Venta'] <= 0].copy()

print(f"\nContabilidad - Líneas Positivas/Negativas:")
print(f"  Positivas:  ${conta_positivas['Venta'].sum():>12,.0f}")
print(f"  Negativas:  ${conta_negativas['Venta'].sum():>12,.0f}")
print(f"  NETO:       ${conta_positivas['Venta'].sum() + conta_negativas['Venta'].sum():>12,.0f}")

# ============================================================================
# PARTE 4: ANALISIS DE ESTADOS Y MODALIDADES
# ============================================================================

print(f"\n{'='*130}")
print(" PARTE 4: ANALISIS POR TIPO DE DOCUMENTO Y ESTADO")
print(f"{'='*130}")

# Obtener tipo de documento
facturas_con_tipo = []
for fact in facturas:
    doc_type = fact.get('l10n_latam_document_type_id', [None, ''])
    doc_type_name = doc_type[1] if isinstance(doc_type, list) else ''

    facturas_con_tipo.append({
        'id': fact['id'],
        'Tipo Doc': doc_type_name,
        'Monto': fact.get('amount_total', 0)
    })

df_tipos = pd.DataFrame(facturas_con_tipo)

print(f"\nFacturas por tipo de documento:")
for tipo_doc, grupo in df_tipos.groupby('Tipo Doc'):
    print(f"  {tipo_doc:35s} : {len(grupo):6,d} facturas, ${grupo['Monto'].sum():>12,.0f}")

# ============================================================================
# PARTE 5: RESUMEN DE HALLAZGOS
# ============================================================================

print(f"\n{'='*130}")
print(" RESUMEN DE HALLAZGOS")
print(f"{'='*130}")

total_excel = excel_por_canal['Venta Excel'].sum()
total_conta = conta_por_canal['Venta Conta'].sum()

print(f"\n1. MAPEO DE CANALES:")
print(f"   Canales en Excel: {len(canales_excel_list)}")
print(f"   Canales en Contabilidad: {len(canales_conta_list)}")
print(f"   Canales mapeables: {len(canales_excel_list & canales_conta_list)}")
print(f"   Canales SOLO en Excel: {len(canales_excel_list - canales_conta_list)}")
print(f"   Canales SOLO en Contabilidad: {len(canales_conta_list - canales_excel_list)}")

print(f"\n2. DIFERENCIA TOTAL:")
print(f"   Excel: ${total_excel:>12,.0f}")
print(f"   Contabilidad: ${total_conta:>12,.0f}")
print(f"   Faltante: ${total_excel - total_conta:>12,.0f} ({(total_excel - total_conta)/total_excel*100:.2f}%)")

print(f"\n3. CAUSAS IDENTIFICADAS:")
print(f"   a) Canales sin mapeo: ${total_solo_conta:>12,.0f}")
print(f"   b) Canales mapeados pero con diferencia:")

mapeados = conta_por_canal[~conta_por_canal['Canal Odoo'].isin(canales_solo_conta)].copy()
if len(mapeados) > 0:
    merged = excel_por_canal.merge(
        mapeados.rename(columns={'Canal Odoo': 'Canal'}),
        on='Canal',
        how='inner'
    )
    merged['Diferencia'] = merged['Venta Excel'] - merged['Venta Conta']
    diferencia_mapeada = merged[merged['Diferencia'] > 0]['Diferencia'].sum()
    print(f"      ${diferencia_mapeada:>12,.0f}")

print(f"\n4. VALIDACION:")
print(f"   Suma de causas: ${total_solo_conta + diferencia_mapeada:>12,.0f}")
print(f"   Diferencia total: ${total_excel - total_conta:>12,.0f}")
print(f"   Varianza: ${abs((total_solo_conta + diferencia_mapeada) - (total_excel - total_conta)):>12,.0f}")

print(f"\n{'='*130}")
