#!/usr/bin/env python3
import sys, sqlite3, pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path("G:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA")
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.config import Config

print("[1] Extrayendo 14-18 abril (SIN restriccion de estado)...")
odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)

lines = odoo.search_read('sale.order.line', [
    ('order_id.date_order', '>=', '2026-04-14'),
    ('order_id.date_order', '<=', '2026-04-18')
], ['order_id', 'product_id', 'product_uom_qty', 'price_subtotal'], limit=100000)

print(f"     Encontradas: {len(lines)} lineas")

rows = []
for line in lines:
    try:
        order_name = line['order_id'][1] if line.get('order_id') else 'UNKNOWN'
        order_date = line['order_id'][2][:10] if line.get('order_id') and len(line['order_id']) > 2 else datetime.now().strftime('%Y-%m-%d')
        product_name = line['product_id'][1] if line.get('product_id') else ''

        rows.append({
            'documento': order_name,
            'fecha_venta': order_date,
            'producto': product_name[:80] if product_name else '',
            'cantidad': line.get('product_uom_qty', 0),
            'venta_bruta': line.get('price_subtotal', 0),
            'costo_total': 0,
            'margen_final': line.get('price_subtotal', 0),
            'tipo_movimiento': 'Venta',
        })
    except:
        pass

df = pd.DataFrame(rows)
print(f"     Convertidas: {len(df)} filas\n")

db = "C:/Users/LENOVO/Desktop/finanzas-unionx-app/maestra_ventas.db"
conn = sqlite3.connect(db, timeout=30)
cursor = conn.cursor()

# Deduplicar
for _, row in df.iterrows():
    cursor.execute(
        "DELETE FROM ventas WHERE documento = ? AND fecha_venta = ? AND venta_bruta = ?",
        (row['documento'], row['fecha_venta'], row['venta_bruta'])
    )

df.to_sql('ventas', conn, if_exists='append', index=False, chunksize=500)

cursor.execute("""
    INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
    VALUES (?, ?, ?, ?, ?, ?)
""", (
    datetime.now().isoformat(),
    'Odoo (sin restriccion estado)',
    len(df),
    df['fecha_venta'].min(),
    df['fecha_venta'].max(),
    'full_extract'
))

conn.commit()
conn.close()
print(f"[OK] {len(df):,} registros insertados!\n")

# Verificar
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("""
SELECT fecha_venta, COUNT(*) ordenes, ROUND(SUM(venta_bruta), 0) venta
FROM ventas WHERE fecha_venta >= '2026-04-01'
GROUP BY fecha_venta ORDER BY fecha_venta
""")

print("RESUMEN FINAL - Venta por día (Abril 2026):")
total = 0
for fecha, ordenes, venta in cur.fetchall():
    print(f"  {fecha}: {ordenes:,} | ${venta:>15,.0f}")
    total += venta

print(f"\nTotal Abril: ${total:,.0f}")
conn.close()
