#!/usr/bin/env python3
"""Extrae TODOS los datos de Abril con fechas correctas"""
import sys, sqlite3, pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path("G:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA")
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.config import Config

print("[1] Conectando a Odoo...")
odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)

print("[2] Extrayendo Abril 1-18...")
lines = odoo.search_read('sale.order.line', [
    ('order_id.date_order', '>=', '2026-04-01'),
    ('order_id.date_order', '<=', '2026-04-18')
], ['order_id', 'product_id', 'product_uom_qty', 'price_subtotal'], limit=100000)

print(f"     Encontradas: {len(lines)} líneas")

# Extraer IDs de órdenes únicas para obtener sus fechas
order_ids = list(set([line['order_id'][0] for line in lines if line.get('order_id')]))
print(f"     Órdenes únicas: {len(order_ids)}")

print("[3] Obteniendo fechas de órdenes...")
orders_map = {}
for order_id in order_ids:
    orders = odoo.search_read('sale.order', [('id', '=', order_id)], ['date_order'], limit=1)
    if orders:
        orders_map[order_id] = orders[0]['date_order'][:10]  # YYYY-MM-DD

print(f"     Fechas obtenidas: {len(orders_map)}\n")

rows = []
for line in lines:
    try:
        order_id = line['order_id'][0]
        order_name = line['order_id'][1]
        # Buscar la fecha en el mapa que creamos
        order_date = orders_map.get(order_id, datetime.now().strftime('%Y-%m-%d'))
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
        print(f"     WARN: {e}")

df = pd.DataFrame(rows)
print(f"[4] Datos preparados ({len(df):,} filas)...\n")

# Insertar
db = "C:/Users/LENOVO/Desktop/finanzas-unionx-app/maestra_ventas.db"

try:
    conn = sqlite3.connect(db, timeout=60)
    cursor = conn.cursor()

    # Borrar abril existente
    print("[5] Limpiando datos de Abril previos...")
    cursor.execute("DELETE FROM ventas WHERE fecha_venta >= '2026-04-01' AND fecha_venta <= '2026-04-18'")

    # Insertar nuevos
    print("[6] Insertando datos nuevos...")
    df.to_sql('ventas', conn, if_exists='append', index=False, chunksize=500)

    # Metadata
    cursor.execute("""
        INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        'Odoo (Abril completo con fechas correctas)',
        len(df),
        df['fecha_venta'].min(),
        df['fecha_venta'].max(),
        'full_month_correct'
    ))

    conn.commit()
    conn.close()
    print(f"\n[OK] {len(df):,} registros insertados!\n")

    # Verificar
    conn = sqlite3.connect(db)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*), SUM(venta_bruta) FROM ventas WHERE fecha_venta >= '2026-04-01'")
    total_april, venta_april = cur.fetchone()

    cur.execute("""
    SELECT fecha_venta, COUNT(*) ordenes, ROUND(SUM(venta_bruta), 0) venta
    FROM ventas WHERE fecha_venta >= '2026-04-01'
    GROUP BY fecha_venta ORDER BY fecha_venta
    """)

    print("RESULTADO - Venta Abril (completo):")
    for fecha, ordenes, venta in cur.fetchall():
        print(f"  {fecha}: {ordenes:,} ordenes | ${venta:>15,.0f}")

    print(f"\nTOTAL ABRIL: {total_april:,} ordenes | ${venta_april:>15,.0f}")
    conn.close()

except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
