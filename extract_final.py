#!/usr/bin/env python3
"""Extrae datos de Abril con fechas correctas desde órdenes"""
import sys, sqlite3, pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path("G:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA")
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.config import Config

print("[1] Conectando a Odoo...")
odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)

print("[2] Extrayendo líneas de Abril...")
lines = odoo.search_read('sale.order.line', [
    ('order_id.date_order', '>=', '2026-04-01'),
    ('order_id.date_order', '<=', '2026-04-18')
], ['id', 'order_id', 'product_id', 'product_uom_qty', 'price_subtotal'], limit=100000)

print(f"     Encontradas: {len(lines)} líneas")

# Paso 2: Obtener ALL órdenes en el período (solo id y date_order)
print("[3] Obteniendo órdenes...")
orders = odoo.search_read('sale.order', [
    ('date_order', '>=', '2026-04-01'),
    ('date_order', '<=', '2026-04-18')
], ['id', 'date_order'], limit=100000)

orders_map = {order['id']: order['date_order'][:10] for order in orders}
print(f"     Órdenes encontradas: {len(orders_map)}\n")

# Paso 3: Mapear líneas con fechas correctas
rows = []
for line in lines:
    try:
        order_id = line['order_id'][0]
        order_name = line['order_id'][1]
        order_date = orders_map.get(order_id, '2026-04-18')  # Fallback
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
    except Exception as e:
        print(f"WARN: {e}")
        pass

df = pd.DataFrame(rows)
print(f"[4] Datos preparados: {len(df):,} filas\n")

# Insertar en BD
db = "C:/Users/LENOVO/Desktop/finanzas-unionx-app/maestra_ventas.db"

try:
    conn = sqlite3.connect(db, timeout=60)
    cursor = conn.cursor()

    print("[5] Limpiando Abril previo...")
    cursor.execute("DELETE FROM ventas WHERE fecha_venta >= '2026-04-01' AND fecha_venta <= '2026-04-18'")

    print("[6] Insertando...")
    df.to_sql('ventas', conn, if_exists='append', index=False, chunksize=500)

    cursor.execute("""INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), 'Odoo (Abril final con fechas OK)',
         len(df), df['fecha_venta'].min(), df['fecha_venta'].max(), 'final'))

    conn.commit()
    conn.close()
    print(f"\n[OK] {len(df):,} insertados!\n")

    # Verificar
    conn = sqlite3.connect(db)
    cur = conn.cursor()

    cur.execute("""SELECT fecha_venta, COUNT(*) ordenes, ROUND(SUM(venta_bruta), 0) venta
        FROM ventas WHERE fecha_venta >= '2026-04-01' GROUP BY fecha_venta ORDER BY fecha_venta""")

    print("=" * 60)
    print("VENTA ABRIL 2026 (FINAL):")
    print("=" * 60)
    total = 0
    for fecha, ordenes, venta in cur.fetchall():
        print(f"  {fecha}: {ordenes:>6,} ordenes | ${venta:>16,.0f}")
        total += venta

    print("-" * 60)
    print(f"  TOTAL: {sum([row[1] for row in cur.execute('SELECT fecha_venta, COUNT(*) FROM ventas WHERE fecha_venta >= \"2026-04-01\" GROUP BY fecha_venta').fetchall()]):>6,} ordenes | ${total:>16,.0f}")
    print("=" * 60)
    conn.close()

except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
