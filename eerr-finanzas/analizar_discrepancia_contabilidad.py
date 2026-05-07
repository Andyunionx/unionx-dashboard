"""
DIAGNOSTICO: ¿Por qué Contabilidad tiene más líneas pero menos dinero?

Hipótesis:
1. Las 12,623 líneas extra son devoluciones (quantity < 0)
2. O ajustes contables que no figuran en ventas
3. O notas de crédito del período
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

print("\n" + "="*120)
print(" DIAGNOSTICO: Análisis de Discrepancia Contabilidad")
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

# PASO 1: BUSCAR TODAS LAS LINEAS FEBRERO (sin filtro)
print(f"\n[PASO 1] Extrayendo TODAS las líneas de febrero...")

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
    {'fields': ['id', 'name', 'move_type'],
     'limit': 100000}
)

factura_ids = [f['id'] for f in facturas]

lineas_raw = models.execute_kw(
    db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids)]],
    {'fields': ['id', 'move_id', 'product_id', 'quantity', 'price_unit',
                'price_subtotal', 'account_id', 'create_date'],
     'limit': 500000}
)

print(f"[OK] {len(lineas_raw)} líneas totales")

# PASO 2: ANALIZAR POR CANTIDAD
print(f"\n[PASO 2] Analizando por cantidad...")

cantidad_positiva = sum(1 for l in lineas_raw if l.get('quantity', 0) > 0)
cantidad_negativa = sum(1 for l in lineas_raw if l.get('quantity', 0) < 0)
cantidad_cero = sum(1 for l in lineas_raw if l.get('quantity', 0) == 0)

print(f"  Líneas con quantity > 0: {cantidad_positiva:,}")
print(f"  Líneas con quantity < 0: {cantidad_negativa:,}")
print(f"  Líneas con quantity = 0: {cantidad_cero:,}")

# PASO 3: ANALIZAR POR PRODUCTO
print(f"\n[PASO 3] Analizando por producto...")

con_producto = sum(1 for l in lineas_raw if l.get('product_id'))
sin_producto = sum(1 for l in lineas_raw if not l.get('product_id'))

print(f"  Líneas con product_id: {con_producto:,}")
print(f"  Líneas sin product_id: {sin_producto:,}")

# PASO 4: ANÁLISIS DE VENTA BRUTA
print(f"\n[PASO 4] Análisis de venta bruta...")

venta_total_raw = sum(l.get('price_subtotal', 0) for l in lineas_raw)
venta_positiva = sum(l.get('price_subtotal', 0) for l in lineas_raw if l.get('price_subtotal', 0) > 0)
venta_negativa = sum(l.get('price_subtotal', 0) for l in lineas_raw if l.get('price_subtotal', 0) < 0)

print(f"  Venta bruta total: ${venta_total_raw:,.0f}")
print(f"  Venta positiva (ventas): ${venta_positiva:,.0f}")
print(f"  Venta negativa (devoluciones): ${venta_negativa:,.0f}")

# PASO 5: LINEAS FILTRADAS (solo positivas, con producto)
print(f"\n[PASO 5] Filtrando para match con Excel...")

lineas_filtradas = [
    l for l in lineas_raw
    if l.get('product_id') and l.get('quantity', 0) > 0 and l.get('price_subtotal', 0) > 0
]

venta_filtrada = sum(l.get('price_subtotal', 0) for l in lineas_filtradas)

print(f"  Líneas con: product_id=True, quantity>0, price_subtotal>0")
print(f"  Resultado: {len(lineas_filtradas):,} líneas, ${venta_filtrada:,.0f}")

# PASO 6: COMPARAR CON EXCEL
print(f"\n[PASO 6] Comparando con Excel...")

ruta_excel = Path(__file__).parent.parent / "datos_entrada/Raw ventas Y.xlsx"
df_raw = pd.read_excel(ruta_excel, sheet_name='RAW')
df_raw_feb = df_raw[(df_raw['Año venta'] == 2026) & (df_raw['Mes venta'] == 2)]

venta_excel = df_raw_feb['Venta bruta'].sum()
filas_excel = len(df_raw_feb)

print(f"  Excel: {filas_excel:,} líneas, ${venta_excel:,.0f}")
print(f"  Contabilidad filtrada: {len(lineas_filtradas):,} líneas, ${venta_filtrada:,.0f}")

diff_filas = len(lineas_filtradas) - filas_excel
diff_venta = venta_filtrada - venta_excel
pct_venta = (diff_venta / venta_excel * 100) if venta_excel > 0 else 0

print(f"\n  Diferencia filas: {diff_filas:,}")
print(f"  Diferencia venta: ${diff_venta:,.0f} ({pct_venta:+.2f}%)")

print(f"\n{'='*120}")
print(" RESUMEN")
print(f"{'='*120}")
print(f"\nEl problema es:")
print(f"  - {cantidad_negativa:,} líneas con quantity < 0 (devoluciones/ajustes)")
print(f"  - Venta negativa de ${abs(venta_negativa):,.0f}")
print(f"\nSi excluimos devoluciones:")
print(f"  - Tenemos {len(lineas_filtradas):,} líneas (diferencia: {diff_filas:+,})")
print(f"  - Venta de ${venta_filtrada:,.0f} (diferencia: {pct_venta:+.2f}%)")

if abs(pct_venta) < 5:
    print(f"\n[RESULTADO] Coincide con Excel dentro de tolerancia")
else:
    print(f"\n[RESULTADO] Aún hay {abs(diff_filas):,} líneas sin explicar")
    print(f"  Próximo paso: analizar qué canales faltan")

print(f"\n{'='*120}")
