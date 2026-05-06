#!/usr/bin/env python3
"""Sincroniza TODO Abril (1-18) desde Odoo"""
import sys
from pathlib import Path
from datetime import datetime
import sqlite3
import pandas as pd

PROJECT_ROOT = Path(".")
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.config import Config

db_path = "C:/Users/LENOVO/Desktop/finanzas-unionx-app/maestra_ventas.db"

print("[SYNC] ABRIL COMPLETO (1-18)")
print("=" * 70)

odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)

print("\n[1] Extrayendo órdenes...")
ordenes = odoo.search_read('sale.order', [
    ('date_order', '>=', '2026-04-01 00:00:00'),
    ('date_order', '<=', '2026-04-18 23:59:59'),
    ('state', 'in', ['sale', 'done']),
], ['id', 'name', 'date_order', 'amount_total', 'warehouse_id', 'channel', 'invoice_ids'], limit=100000)

print(f"    Órdenes: {len(ordenes):,}")

orden_ids = [o['id'] for o in ordenes]
ordenes_dict = {o['id']: o for o in ordenes}
invoice_ids_all = list({inv_id for o in ordenes for inv_id in (o.get('invoice_ids') or [])})

print("[2] Extrayendo líneas...")
lineas = odoo.search_read('sale.order.line', [
    ('order_id', 'in', orden_ids)
], ['id', 'order_id', 'product_id', 'product_uom_qty', 'price_subtotal', 'purchase_price'], limit=500000)

print(f"    Líneas: {len(lineas):,}")

print("[3] Extrayendo facturas y NC...")
facturas = odoo.execute_in_batches('account.move', invoice_ids_all, [
    'id', 'name', 'invoice_date', 'amount_total', 'reversed_entry_id'
], batch_size=50) if invoice_ids_all else []

nc_ids = [nc['id'] for nc in odoo.search_read('account.move', [
    ('move_type', '=', 'out_refund'),
    ('invoice_date', '>=', '2026-04-01 00:00:00'),
    ('invoice_date', '<=', '2026-04-18 23:59:59'),
    ('state', '=', 'posted'),
], {'fields': ['id'], 'limit': 10000})]

ncs = odoo.execute_in_batches('account.move', nc_ids, [
    'id', 'name', 'invoice_date', 'amount_total', 'reversed_entry_id'
], batch_size=50) if nc_ids else []

print(f"    Facturas: {len(facturas):,}")
print(f"    NC: {len(ncs):,}")

# Neteo
nc_por_factura = {}
for nc in ncs:
    factura_id = None
    if nc.get('reversed_entry_id'):
        factura_id = nc['reversed_entry_id'][0] if isinstance(nc['reversed_entry_id'], (list, tuple)) else nc['reversed_entry_id']
    if factura_id:
        if factura_id not in nc_por_factura:
            nc_por_factura[factura_id] = 0
        nc_por_factura[factura_id] += abs(nc.get('amount_total', 0))

totales_netos = {}
for factura in facturas:
    factura_id = factura['id']
    nc_total = nc_por_factura.get(factura_id, 0)
    totales_netos[factura_id] = factura['amount_total'] - nc_total

# Construir
print("[4] Construyendo dataset...")

factura_a_orden = {}
for orden in ordenes:
    for inv_id in (orden.get('invoice_ids') or []):
        factura_a_orden[inv_id] = orden['id']

rows = []
for linea in lineas:
    orden_id = linea['order_id'][0] if linea['order_id'] else None
    orden = ordenes_dict.get(orden_id, {})
    if not orden:
        continue

    factura_id = None
    for inv_id in (orden.get('invoice_ids') or []):
        factura_id = inv_id
        break

    precio_linea = linea.get('price_subtotal', 0)
    venta_neta = precio_linea
    if factura_id and factura_id in totales_netos:
        orden_amount = orden.get('amount_total', 0)
        if orden_amount > 0:
            venta_neta = precio_linea * (totales_netos[factura_id] / orden_amount)

    rows.append({
        'tipo_movimiento': 'Venta',
        'documento': orden.get('name', ''),
        'fecha_venta': orden.get('date_order', '').split(' ')[0] if orden.get('date_order') else '',
        'producto': '',
        'cantidad': linea.get('product_uom_qty', 0),
        'venta_bruta': venta_neta,
        'costo_unitario': linea.get('purchase_price', 0),
        'costo_total': linea.get('purchase_price', 0) * linea.get('product_uom_qty', 0),
        'margen_final': venta_neta - (linea.get('purchase_price', 0) * linea.get('product_uom_qty', 0)),
        'bodega': '',
        'canal': '',
        'estado_pedido': '',
    })

for nc in ncs:
    factura_id = None
    if nc.get('reversed_entry_id'):
        factura_id = nc['reversed_entry_id'][0] if isinstance(nc['reversed_entry_id'], (list, tuple)) else nc['reversed_entry_id']
    orden_id = factura_a_orden.get(factura_id)
    if orden_id:
        nc_amount = abs(nc.get('amount_total', 0))
        rows.append({
            'tipo_movimiento': 'Devolución',
            'documento': nc.get('name', ''),
            'fecha_venta': nc.get('invoice_date', '').split(' ')[0] if nc.get('invoice_date') else '',
            'producto': '',
            'cantidad': 1,
            'venta_bruta': -nc_amount,
            'costo_unitario': 0,
            'costo_total': 0,
            'margen_final': -nc_amount,
            'bodega': '',
            'canal': '',
            'estado_pedido': '',
        })

df = pd.DataFrame(rows)
print(f"    Rows: {len(df):,}")

print("[5] Insertando en BD...")
conn = sqlite3.connect(db_path, timeout=60)
cursor = conn.cursor()

cursor.execute("DELETE FROM ventas WHERE fecha_venta >= '2026-04-01'")
df.to_sql('ventas', conn, if_exists='append', index=False, chunksize=500)

cursor.execute("""INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
    VALUES (?, ?, ?, ?, ?, ?)""",
    (datetime.now().isoformat(), 'Odoo (sincronizador_v2)',
     len(df), df['fecha_venta'].min(), df['fecha_venta'].max(), 'sync'))

conn.commit()
conn.close()

print(f"[OK] {len(df):,} filas insertadas\n")

# Verificar
print("[6] RESULTADO FINAL:")
print("=" * 70)
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""SELECT fecha_venta, COUNT(*) lineas, ROUND(SUM(venta_bruta), 0) venta
    FROM ventas WHERE fecha_venta >= '2026-04-01'
    GROUP BY fecha_venta ORDER BY fecha_venta""")

print("\nPOR DÍA:")
total_all = 0
for fecha, lineas, venta in cur.fetchall():
    print(f"  {fecha}: {lineas:>6,} líneas | ${venta:>16,.0f}")
    total_all += venta

print("-" * 70)
print(f"  TOTAL ABRIL (ODOO): ${total_all:>16,.0f}")
print("=" * 70)
conn.close()
