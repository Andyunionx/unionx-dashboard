"""
PASO 3a MODALIDAD: Extrae Contabilidad y Ventas separando BODEGA vs FULFILLMENT

Objetivo: Entender la diferencia entre modalidades

Filtros:
- Contabilidad: Excluir liquidación factura (l10n_latam_document_type_id = 43)
- Ventas: Filtrar por field fulfillment
- Fecha: Usar invoice_date / order_date para febrero 2026
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

print("\n" + "="*120)
print(" EXTRACCION POR MODALIDAD: Contabilidad y Ventas (Febrero 2026)")
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

print(f"\n[Conectado - UID: {uid}]")

# ============================================================================
# PARTE A: CONTABILIDAD - CON Y SIN LIQUIDACION FACTURA
# ============================================================================

print(f"\n{'='*120}")
print(" CONTABILIDAD (account.move.line)")
print(f"{'='*120}")

print(f"\n[PASO A1] Extrayendo CON liquidación factura (código 43)...")

domain_con_liq = [
    ('invoice_date', '>=', '2026-02-01'),
    ('invoice_date', '<', '2026-03-01'),
    ('move_type', '=', 'out_invoice'),
    ('state', '=', 'posted'),
]

facturas_con_liq = models.execute_kw(
    db, uid, password,
    'account.move', 'search_read',
    [domain_con_liq],
    {'fields': ['id', 'name', 'l10n_latam_document_type_id'],
     'limit': 100000}
)

print(f"[OK] {len(facturas_con_liq):,} facturas")

factura_ids_con_liq = [f['id'] for f in facturas_con_liq]

lineas_con_liq = models.execute_kw(
    db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids_con_liq)]],
    {'fields': ['move_id', 'product_id', 'quantity', 'price_subtotal'],
     'limit': 500000}
)

lineas_con_liq_filtradas = [
    l for l in lineas_con_liq
    if l.get('product_id') and l.get('price_subtotal', 0) > 0
]

venta_con_liq = sum(l.get('price_subtotal', 0) for l in lineas_con_liq_filtradas)

print(f"[OK] {len(lineas_con_liq_filtradas):,} líneas positivas (product_id>0, venta>0)")
print(f"     Venta total: ${venta_con_liq:,.0f}")

# Clasificar por tipo de documento
doc_types = {}
for fact in facturas_con_liq:
    doc_type = fact.get('l10n_latam_document_type_id', [None, ''])
    doc_type_name = doc_type[1] if isinstance(doc_type, list) else str(doc_type)
    if doc_type_name not in doc_types:
        doc_types[doc_type_name] = 0
    doc_types[doc_type_name] += 1

print(f"\nTipos de documento:")
for doc, count in sorted(doc_types.items()):
    print(f"  {doc:30s} : {count:6,d}")

# Ahora SIN liquidación factura
print(f"\n[PASO A2] Extrayendo SIN liquidación factura (excluyendo código 43)...")

domain_sin_liq = [
    ('invoice_date', '>=', '2026-02-01'),
    ('invoice_date', '<', '2026-03-01'),
    ('move_type', '=', 'out_invoice'),
    ('state', '=', 'posted'),
    ('l10n_latam_document_type_id', '!=', 43),  # Excluir liquidación factura
]

facturas_sin_liq = models.execute_kw(
    db, uid, password,
    'account.move', 'search_read',
    [domain_sin_liq],
    {'fields': ['id', 'name', 'l10n_latam_document_type_id'],
     'limit': 100000}
)

print(f"[OK] {len(facturas_sin_liq):,} facturas")

factura_ids_sin_liq = [f['id'] for f in facturas_sin_liq]

lineas_sin_liq = models.execute_kw(
    db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids_sin_liq)]],
    {'fields': ['move_id', 'product_id', 'quantity', 'price_subtotal'],
     'limit': 500000}
)

lineas_sin_liq_filtradas = [
    l for l in lineas_sin_liq
    if l.get('product_id') and l.get('price_subtotal', 0) > 0
]

venta_sin_liq = sum(l.get('price_subtotal', 0) for l in lineas_sin_liq_filtradas)

print(f"[OK] {len(lineas_sin_liq_filtradas):,} líneas positivas")
print(f"     Venta total: ${venta_sin_liq:,.0f}")

# ============================================================================
# PARTE B: VENTAS - CON Y SIN FULFILLMENT
# ============================================================================

print(f"\n{'='*120}")
print(" VENTAS (sale.order.line)")
print(f"{'='*120}")

print(f"\n[PASO B1] Extrayendo CON fulfillment...")

domain_ventas_con_full = [
    ('create_date', '>=', '2026-02-01'),
    ('create_date', '<', '2026-03-01'),
    ('state', 'in', ['sale', 'done']),
]

ordenes_con_full = models.execute_kw(
    db, uid, password,
    'sale.order', 'search_read',
    [domain_ventas_con_full],
    {'fields': ['id', 'name', 'fulfillment'],
     'limit': 100000}
)

print(f"[OK] {len(ordenes_con_full):,} órdenes")

orden_ids_con_full = [o['id'] for o in ordenes_con_full]

lineas_ventas_con_full = models.execute_kw(
    db, uid, password,
    'sale.order.line', 'search_read',
    [[('order_id', 'in', orden_ids_con_full)]],
    {'fields': ['order_id', 'product_id', 'product_uom_qty', 'price_subtotal'],
     'limit': 500000}
)

lineas_ventas_con_full_filtradas = [
    l for l in lineas_ventas_con_full
    if l.get('product_id') and l.get('price_subtotal', 0) > 0
]

venta_ventas_con_full = sum(l.get('price_subtotal', 0) for l in lineas_ventas_con_full_filtradas)

print(f"[OK] {len(lineas_ventas_con_full_filtradas):,} líneas positivas")
print(f"     Venta total: ${venta_ventas_con_full:,.0f}")

# Análisis de fulfillment
fulfillment_types = {}
for orden in ordenes_con_full:
    full = orden.get('fulfillment', '')
    if full not in fulfillment_types:
        fulfillment_types[full] = 0
    fulfillment_types[full] += 1

print(f"\nTipos fulfillment:")
for full, count in sorted(fulfillment_types.items(), key=lambda x: str(x[0])):
    print(f"  {str(full):30s} : {count:6,d}")

# Ahora SIN fulfillment
print(f"\n[PASO B2] Extrayendo SIN fulfillment (solo bodega)...")

# Filtrar órdenes sin fulfillment o con fulfillment vacio
ordenes_sin_full = [o for o in ordenes_con_full if not o.get('fulfillment') or o.get('fulfillment', '').strip() == '']

print(f"[OK] {len(ordenes_sin_full):,} órdenes sin fulfillment")

orden_ids_sin_full = [o['id'] for o in ordenes_sin_full]

lineas_ventas_sin_full = models.execute_kw(
    db, uid, password,
    'sale.order.line', 'search_read',
    [[('order_id', 'in', orden_ids_sin_full)]],
    {'fields': ['order_id', 'product_id', 'product_uom_qty', 'price_subtotal'],
     'limit': 500000}
)

lineas_ventas_sin_full_filtradas = [
    l for l in lineas_ventas_sin_full
    if l.get('product_id') and l.get('price_subtotal', 0) > 0
]

venta_ventas_sin_full = sum(l.get('price_subtotal', 0) for l in lineas_ventas_sin_full_filtradas)

print(f"[OK] {len(lineas_ventas_sin_full_filtradas):,} líneas positivas")
print(f"     Venta total: ${venta_ventas_sin_full:,.0f}")

# ============================================================================
# PARTE C: COMPARACION CON EXCEL
# ============================================================================

print(f"\n{'='*120}")
print(" COMPARACION CON EXCEL")
print(f"{'='*120}")

ruta_excel = Path(__file__).parent.parent / "datos_entrada/Raw ventas Y.xlsx"
df_raw = pd.read_excel(ruta_excel, sheet_name='RAW')
df_raw_feb = df_raw[(df_raw['Año venta'] == 2026) & (df_raw['Mes venta'] == 2)]

venta_excel = df_raw_feb['Venta bruta'].sum()
filas_excel = len(df_raw_feb)

print(f"\nExcel (baseline):")
print(f"  Líneas: {filas_excel:,}")
print(f"  Venta: ${venta_excel:,.0f}")

# Tabla de comparación
print(f"\n{'='*120}")
print(f"{'FUENTE':<40} {'LINEAS':>12} {'VENTA':>20} {'DIFF %':>12}")
print(f"{'='*120}")

print(f"{'Excel (baseline)':<40} {filas_excel:>12,} ${venta_excel:>19,.0f} {0:>11.2f}%")
print(f"{'Contabilidad CON liq.factura':<40} {len(lineas_con_liq_filtradas):>12,} ${venta_con_liq:>19,.0f} {(venta_con_liq/venta_excel-1)*100:>11.2f}%")
print(f"{'Contabilidad SIN liq.factura':<40} {len(lineas_sin_liq_filtradas):>12,} ${venta_sin_liq:>19,.0f} {(venta_sin_liq/venta_excel-1)*100:>11.2f}%")
print(f"{'Ventas CON fulfillment':<40} {len(lineas_ventas_con_full_filtradas):>12,} ${venta_ventas_con_full:>19,.0f} {(venta_ventas_con_full/venta_excel-1)*100:>11.2f}%")
print(f"{'Ventas SIN fulfillment':<40} {len(lineas_ventas_sin_full_filtradas):>12,} ${venta_ventas_sin_full:>19,.0f} {(venta_ventas_sin_full/venta_excel-1)*100:>11.2f}%")

print(f"\n{'='*120}")
print(" INSIGHT")
print(f"{'='*120}")

print(f"\nLiquidación Factura impact:")
print(f"  Líneas excluidas: {len(lineas_con_liq_filtradas) - len(lineas_sin_liq_filtradas):,}")
print(f"  Venta excluida: ${venta_con_liq - venta_sin_liq:,.0f}")

print(f"\nFulfillment impact (Ventas):")
print(f"  Líneas excluidas: {len(lineas_ventas_con_full_filtradas) - len(lineas_ventas_sin_full_filtradas):,}")
print(f"  Venta excluida: ${venta_ventas_con_full - venta_ventas_sin_full:,.0f}")

print(f"\n{'='*120}")
