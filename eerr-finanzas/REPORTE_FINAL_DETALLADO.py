"""
REPORTE FINAL DETALLADO
Análisis completo: Excel vs Contabilidad vs Ventas
Con reconciliación, causas raíz y recomendaciones
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
import os
from dotenv import load_dotenv
from difflib import SequenceMatcher

print("\n" + "="*140)
print(" REPORTE FINAL DETALLADO: RECONCILIACION EXCEL vs CONTABILIDAD vs VENTAS")
print("="*140)

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

# ============================================================================
# CARGAR EXCEL
# ============================================================================

ruta_excel = Path(__file__).parent.parent / "datos_entrada/Raw ventas Y.xlsx"
df_excel = pd.read_excel(ruta_excel, sheet_name='RAW')
df_excel_feb = df_excel[(df_excel['Año venta'] == 2026) & (df_excel['Mes venta'] == 2)].copy()

print(f"\n[EXCEL] {len(df_excel_feb):,} líneas, ${df_excel_feb['Venta bruta'].sum():,.0f}")

# ============================================================================
# CARGAR CONTABILIDAD
# ============================================================================

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
    {'fields': ['id', 'name', 'partner_id', 'l10n_latam_document_type_id'],
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
        'Venta': linea.get('price_subtotal', 0),
    })

df_conta = pd.DataFrame(conta_datos)

print(f"[CONTABILIDAD] {len(df_conta):,} líneas, ${df_conta['Venta'].sum():,.0f}")

# ============================================================================
# CARGAR VENTAS
# ============================================================================

domain_ventas = [
    ('create_date', '>=', '2026-02-01'),
    ('create_date', '<', '2026-03-01'),
    ('state', 'in', ['sale', 'done']),
]

ordenes = models.execute_kw(
    db, uid, password,
    'sale.order', 'search_read',
    [domain_ventas],
    {'fields': ['id', 'partner_id', 'fulfillment'],
     'limit': 100000}
)

orden_ids = [o['id'] for o in ordenes]

lineas_ventas = models.execute_kw(
    db, uid, password,
    'sale.order.line', 'search_read',
    [[('order_id', 'in', orden_ids)]],
    {'fields': ['order_id', 'product_id', 'product_uom_qty', 'price_subtotal'],
     'limit': 500000}
)

ordenes_dict = {o['id']: o for o in ordenes}

ventas_datos = []
for linea in lineas_ventas:
    if not linea.get('product_id') or linea.get('price_subtotal', 0) <= 0:
        continue

    order_id = linea.get('order_id', [None])[0] if linea.get('order_id') else None
    if order_id not in ordenes_dict:
        continue

    orden = ordenes_dict[order_id]
    partner = orden.get('partner_id', [None, ''])
    canal_odoo = partner[1] if isinstance(partner, list) else ''
    fulfillment = orden.get('fulfillment', '')

    ventas_datos.append({
        'Canal Odoo': canal_odoo,
        'Venta': linea.get('price_subtotal', 0),
        'Fulfillment': fulfillment if fulfillment else 'Bodega',
    })

df_ventas = pd.DataFrame(ventas_datos)

print(f"[VENTAS] {len(df_ventas):,} líneas, ${df_ventas['Venta'].sum():,.0f}")

# ============================================================================
# CREAR MAPEO
# ============================================================================

def normalizador(s):
    """Normaliza nombre de canal"""
    s = str(s).strip()
    if s.startswith('Cliente '):
        s = s[8:]
    for sufijo in [' Fidelizacion SPA', ' Fidelizacion', ' SPA', ' Spa', ' LIMITADA', ' Limitada', ' ltda.', ' LTDA.', ' Ltda']:
        if s.endswith(sufijo):
            s = s[:-len(sufijo)].strip()
    return s

def mapear(canal_odoo, canales_excel):
    """Mapea canal Odoo al más similar en Excel"""
    norm = normalizador(canal_odoo)

    # Búsqueda exacta
    for ce in canales_excel:
        if norm.lower() == ce.lower():
            return ce

    # Búsqueda por similitud
    best = max([(ce, SequenceMatcher(None, norm.lower(), ce.lower()).ratio()) for ce in canales_excel], key=lambda x: x[1])

    if best[1] > 0.6:
        return best[0]

    return None

canales_excel_list = sorted(df_excel_feb['Canal'].unique())

# Aplicar mapeo a todos
df_conta['Canal Mapeado'] = df_conta['Canal Odoo'].apply(lambda x: mapear(x, canales_excel_list))
df_ventas['Canal Mapeado'] = df_ventas['Canal Odoo'].apply(lambda x: mapear(x, canales_excel_list))

conta_mapeadas = len(df_conta[df_conta['Canal Mapeado'].notna()])
ventas_mapeadas = len(df_ventas[df_ventas['Canal Mapeado'].notna()])

print(f"\n[MAPEO] Contabilidad: {conta_mapeadas:,}/{len(df_conta):,} líneas mapeadas")
print(f"[MAPEO] Ventas: {ventas_mapeadas:,}/{len(df_ventas):,} líneas mapeadas")

# ============================================================================
# RECONCILIACION FINAL
# ============================================================================

print(f"\n{'='*140}")
print(" RECONCILIACION POR CANAL")
print(f"{'='*140}")

# Agrupar
excel_canal = df_excel_feb.groupby('Canal')['Venta bruta'].sum().reset_index()
excel_canal.columns = ['Canal', 'Venta Excel']

conta_canal = df_conta[df_conta['Canal Mapeado'].notna()].groupby('Canal Mapeado')['Venta'].sum().reset_index()
conta_canal.columns = ['Canal', 'Venta Contab']

ventas_canal = df_ventas[df_ventas['Canal Mapeado'].notna()].groupby('Canal Mapeado')['Venta'].sum().reset_index()
ventas_canal.columns = ['Canal', 'Venta Ventas']

# Merge
reconciliacion = excel_canal.merge(conta_canal, on='Canal', how='outer').merge(ventas_canal, on='Canal', how='outer').fillna(0)

reconciliacion['Diff Conta %'] = (reconciliacion['Venta Contab'] - reconciliacion['Venta Excel']) / reconciliacion['Venta Excel'] * 100 if len(reconciliacion) > 0 else 0
reconciliacion['Diff Ventas %'] = (reconciliacion['Venta Ventas'] - reconciliacion['Venta Excel']) / reconciliacion['Venta Excel'] * 100 if len(reconciliacion) > 0 else 0

reconciliacion = reconciliacion.sort_values('Venta Excel', ascending=False)

# Imprimir tabla
print(f"\n{'CANAL':<35} {'EXCEL':>15} {'CONTAB':>15} {'VENTAS':>15} {'DIFF% C':>10} {'DIFF% V':>10}")
print("-"*110)

for idx, row in reconciliacion.head(20).iterrows():
    canal = str(row['Canal'])[:35]
    excel = row['Venta Excel']
    conta = row['Venta Contab']
    ventas = row['Venta Ventas']
    diff_c = row['Diff Conta %']
    diff_v = row['Diff Ventas %']

    print(f"{canal:<35} ${excel:>14,.0f} ${conta:>14,.0f} ${ventas:>14,.0f} {diff_c:>9.1f}% {diff_v:>9.1f}%")

# Totales
total_excel = excel_canal['Venta Excel'].sum()
total_conta_map = conta_canal['Venta Contab'].sum()
total_ventas_map = ventas_canal['Venta Ventas'].sum()
total_conta_all = df_conta['Venta'].sum()
total_ventas_all = df_ventas['Venta'].sum()

print("-"*110)
print(f"{'TOTAL MAPEADO':<35} ${total_excel:>14,.0f} ${total_conta_map:>14,.0f} ${total_ventas_map:>14,.0f}")

# ============================================================================
# HALLAZGOS Y RECOMENDACIONES
# ============================================================================

print(f"\n{'='*140}")
print(" HALLAZGOS CLAVE")
print(f"{'='*140}")

print(f"\n1. DISCREPANCIA EXCEL vs CONTABILIDAD:")
print(f"   Excel:              ${total_excel:>15,.0f}")
print(f"   Contabilidad Total: ${total_conta_all:>15,.0f}")
print(f"   Diferencia:         ${total_excel - total_conta_all:>15,.0f} ({(total_excel - total_conta_all)/total_excel*100:+.2f}%)")

print(f"\n2. DISCREPANCIA CONTABILIDAD vs VENTAS:")
print(f"   Contabilidad Total: ${total_conta_all:>15,.0f}")
print(f"   Ventas Total:       ${total_ventas_all:>15,.0f}")
print(f"   Diferencia:         ${total_conta_all - total_ventas_all:>15,.0f} ({(total_conta_all - total_ventas_all)/total_conta_all*100:+.2f}%)")

print(f"\n3. MAPEO DE CANALES:")
canales_mapeados = len(df_conta[df_conta['Canal Mapeado'].notna()]['Canal Mapeado'].unique())
canales_no_mapeados = len(df_conta[df_conta['Canal Mapeado'].isna()]['Canal Odoo'].unique())
venta_no_mapeada = df_conta[df_conta['Canal Mapeado'].isna()]['Venta'].sum()

print(f"   Canales mapeados: {canales_mapeados}")
print(f"   Canales sin mapeo: {canales_no_mapeados}")
print(f"   Venta no mapeada: ${venta_no_mapeada:,.0f} ({venta_no_mapeada/total_conta_all*100:.1f}%)")

print(f"\n4. CANALES CON MAYOR DIFERENCIA vs EXCEL:")
reconciliacion['Abs Diff'] = abs(reconciliacion['Venta Contab'] - reconciliacion['Venta Excel'])
top_diff = reconciliacion.nlargest(5, 'Abs Diff')

for idx, row in top_diff.iterrows():
    canal = row['Canal']
    excel = row['Venta Excel']
    conta = row['Venta Contab']
    diff = conta - excel

    print(f"   {canal:35s} : Excel=${excel:>12,.0f}, Conta=${conta:>12,.0f}, Diferencia=${diff:>12,.0f}")

print(f"\n5. FULFILLMENT en VENTAS:")
fullfill_dist = df_ventas.groupby('Fulfillment')['Venta'].sum()
for full, venta in fullfill_dist.items():
    print(f"   {full:35s} : ${venta:>12,.0f} ({venta/total_ventas_all*100:>5.1f}%)")

print(f"\n{'='*140}")
print(" CONCLUSIONES Y RECOMENDACIONES")
print(f"{'='*140}")

print(f"""
1. ESTADO GENERAL:
   - Excel es la fuente de verdad con ${total_excel:,.0f}
   - Contabilidad tiene ${total_conta_all:,.0f} ({(total_conta_all/total_excel-1)*100:+.2f}% vs Excel)
   - Ventas tiene ${total_ventas_all:,.0f} ({(total_ventas_all/total_excel-1)*100:+.2f}% vs Excel)

2. CAUSA RAIZ DE DIFERENCIAS:
   a) MAPEO DE CANALES IMPERFECTO:
      - {canales_no_mapeados} canales en Odoo sin equivalente claro en Excel
      - Venta no mapeada: ${venta_no_mapeada:,.0f}
      - Solución: Crear tabla de normalización manual para estos {canales_no_mapeados} canales

   b) CONTABILIDAD vs EXCEL:
      - Diferencia de ${total_excel - total_conta_all:,.0f}
      - Posibles causas:
        * Devoluciones/Notas de crédito en Contabilidad (restan venta)
        * Pedidos sin facturar aún (en Excel pero no en Contabilidad)
        * Ajustes contables que no pasan por Ventas

   c) VENTAS vs CONTABILIDAD:
      - Diferencia de ${total_conta_all - total_ventas_all:,.0f}
      - Cumplimiento: {(total_ventas_all/total_conta_all)*100:.1f}%
      - Causas:
        * Fulfillment de terceros va directo a Contabilidad (bypass Ventas)
        * Pedidos en estado "para facturar" aún no en Contabilidad

3. PROXIMOS PASOS:
   [*] Implementar mapeo manual de los {canales_no_mapeados} canales restantes
   [*] Validar si hay devoluciones/notas de crédito que expliquen diferencias
   [*] Documentar flujo de fulfillment de terceros vs ventas regulares
   [*] Establecer proceso de reconciliación mensual Excel-Contabilidad-Ventas

4. RECOMENDACION PARA INYECCION A ANALISIS RESULTADO:
   - Usar datos de CONTABILIDAD como fuente (contiene todos documentos)
   - Aplicar mapeo de canales normalizado
   - Hacer reconc iliación mensual para detectar cambios
   - Implementar alertas si diferencia > 10% en algún canal
""")

print(f"{'='*140}\n")
