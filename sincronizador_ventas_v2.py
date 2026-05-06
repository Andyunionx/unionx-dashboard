#!/usr/bin/env python3
"""
Sincronizador de ventas ROBUSTO - Versión 2
Sin usar extract_to_raw_format() que tiene problemas de rendimiento.
Extrae directamente desde Odoo con neteo correcto según documento contable.
"""
import os
import sys
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.config import Config

# Resolución dinámica del path de la BD (env var > carpeta in-repo > Desktop legacy)
def _resolve_db_path() -> str:
    env_path = os.environ.get("MAESTRA_VENTAS_DB")
    if env_path:
        return env_path
    in_repo = PROJECT_ROOT / "data" / "db" / "maestra_ventas.db"
    if in_repo.exists():
        return str(in_repo)
    home_legacy = Path.home() / "Desktop" / "finanzas-unionx-app" / "maestra_ventas.db"
    if home_legacy.exists():
        return str(home_legacy)
    # Default si no existe ninguna: in-repo (será creada al ejecutar to_sql)
    in_repo.parent.mkdir(parents=True, exist_ok=True)
    return str(in_repo)


def sincronizar_ventas(fecha_inicio="2026-04-14", fecha_fin="2026-04-18"):
    """
    Extrae ventas desde Odoo directamente, sin extract_to_raw_format().

    Estrategia:
    1. Extraer órdenes confirmadas/completadas ('sale', 'done')
    2. Extraer líneas de venta (sale.order.line) con price_subtotal correcto
    3. Extraer facturas y NC, calcular neteo por factura
    4. Construir dataset con venta_neta correcta
    5. Insertar con deduplicación
    """

    db_path = _resolve_db_path()
    print(f"[*] BD: {db_path}")

    print("[1] Conectando a Odoo...")
    odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)

    # PASO 1: Extraer órdenes confirmadas (SOLO 'sale' y 'done')
    print("[2] Extrayendo órdenes confirmadas...")
    ordenes = odoo.search_read('sale.order', [
        ('date_order', '>=', f'{fecha_inicio} 00:00:00'),
        ('date_order', '<=', f'{fecha_fin} 23:59:59'),
        ('state', 'in', ['sale', 'done']),
    ], ['id', 'name', 'date_order', 'amount_total', 'warehouse_id', 'channel', 'invoice_ids'], limit=100000)

    print(f"     Órdenes: {len(ordenes)}")

    orden_ids = [o['id'] for o in ordenes]
    ordenes_dict = {o['id']: o for o in ordenes}
    invoice_ids_all = list({inv_id for o in ordenes for inv_id in (o.get('invoice_ids') or [])})

    # PASO 2: Extraer líneas de venta
    print("[3] Extrayendo líneas de venta...")
    lineas = odoo.search_read('sale.order.line', [
        ('order_id', 'in', orden_ids)
    ], ['id', 'order_id', 'product_id', 'product_uom_qty', 'price_subtotal', 'purchase_price'], limit=500000)

    print(f"     Líneas: {len(lineas)}")

    # PASO 3: Extraer facturas y NC
    print("[4] Extrayendo facturas y NC...")
    facturas = odoo.execute_in_batches('account.move', invoice_ids_all, [
        'id', 'name', 'invoice_date', 'move_type', 'amount_total', 'reversed_entry_id'
    ], batch_size=50) if invoice_ids_all else []

    # Extraer NC del período
    nc_ids = [nc['id'] for nc in odoo.search_read('account.move', [
        ('move_type', '=', 'out_refund'),
        ('invoice_date', '>=', f'{fecha_inicio} 00:00:00'),
        ('invoice_date', '<=', f'{fecha_fin} 23:59:59'),
        ('state', '=', 'posted'),
    ], {'fields': ['id'], 'limit': 10000})]

    ncs = odoo.execute_in_batches('account.move', nc_ids, [
        'id', 'name', 'invoice_date', 'amount_total', 'reversed_entry_id'
    ], batch_size=50) if nc_ids else []

    print(f"     Facturas: {len(facturas)}")
    print(f"     NC: {len(ncs)}")

    # PASO 4: Calcular neteo por factura
    nc_por_factura = {}
    for nc in ncs:
        factura_id = None
        if nc.get('reversed_entry_id'):
            factura_id = nc['reversed_entry_id'][0] if isinstance(nc['reversed_entry_id'], (list, tuple)) else nc['reversed_entry_id']

        if factura_id:
            if factura_id not in nc_por_factura:
                nc_por_factura[factura_id] = 0
            nc_por_factura[factura_id] += abs(nc.get('amount_total', 0))

    # Calcular totales netos por factura
    totales_netos = {}
    for factura in facturas:
        factura_id = factura['id']
        nc_total = nc_por_factura.get(factura_id, 0)
        totales_netos[factura_id] = factura['amount_total'] - nc_total

    # PASO 5: Construir dataset
    print("[5] Construyendo dataset...")

    # Mapeo factura_id → orden_id
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

        # Obtener factura y neteo
        factura_id = None
        for inv_id in (orden.get('invoice_ids') or []):
            factura_id = inv_id
            break

        # Venta de esta línea
        precio_linea = linea.get('price_subtotal', 0)

        # Aplicar neteo si aplica
        venta_neta = precio_linea
        if factura_id and factura_id in totales_netos:
            # Calcular ratio de neteo para esta línea
            orden_amount = orden.get('amount_total', 0)
            if orden_amount > 0:
                venta_neta = precio_linea * (totales_netos[factura_id] / orden_amount)

        # Producto
        producto_id = linea['product_id'][0] if linea['product_id'] else None

        rows.append({
            'tipo_movimiento': 'Venta',
            'documento': orden.get('name', ''),
            'fecha_venta': orden.get('date_order', '').split(' ')[0] if orden.get('date_order') else '',
            'producto': f"SKU_{producto_id}" if producto_id else 'Sin producto',
            'cantidad': linea.get('product_uom_qty', 0),
            'venta_bruta': venta_neta,
            'costo_unitario': linea.get('purchase_price', 0),
            'costo_total': linea.get('purchase_price', 0) * linea.get('product_uom_qty', 0),
            'margen_final': venta_neta - (linea.get('purchase_price', 0) * linea.get('product_uom_qty', 0)),
            'bodega': orden.get('warehouse_id', [None, ''])[1] if orden.get('warehouse_id') else 'Bodega Principal',
            'canal': orden.get('channel', 'Direct'),
            'estado_pedido': orden.get('state', 'sale'),
        })

    # Agregar NC como líneas separadas
    for nc in ncs:
        factura_id = None
        if nc.get('reversed_entry_id'):
            factura_id = nc['reversed_entry_id'][0] if isinstance(nc['reversed_entry_id'], (list, tuple)) else nc['reversed_entry_id']

        orden_id = factura_a_orden.get(factura_id)
        orden = ordenes_dict.get(orden_id, {})

        if orden:
            nc_amount = abs(nc.get('amount_total', 0))
            rows.append({
                'tipo_movimiento': 'Devolución',
                'documento': nc.get('name', ''),
                'fecha_venta': nc.get('invoice_date', '').split(' ')[0] if nc.get('invoice_date') else '',
                'producto': f"NC de {nc.get('name', 'NC')}",
                'cantidad': 1,
                'venta_bruta': -nc_amount,
                'costo_unitario': 0,
                'costo_total': 0,
                'margen_final': -nc_amount,
                'bodega': orden.get('warehouse_id', [None, ''])[1] if orden.get('warehouse_id') else 'Bodega Principal',
                'canal': orden.get('channel', 'Direct'),
                'estado_pedido': 'Devolución',
            })

    df = pd.DataFrame(rows)
    print(f"     Rows construidas: {len(df):,}")

    # PASO 6: Insertar en BD
    print("[6] Insertando en BD...")

    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()

    # Limpiar período
    cursor.execute(f"DELETE FROM ventas WHERE fecha_venta >= '{fecha_inicio}' AND fecha_venta <= '{fecha_fin}'")

    # Insertar
    df.to_sql('ventas', conn, if_exists='append', index=False, chunksize=500)

    # Metadata
    cursor.execute("""INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), f'Odoo (sincronizador_v2)',
         len(df), df['fecha_venta'].min(), df['fecha_venta'].max(), 'sync'))

    conn.commit()
    conn.close()

    print(f"[OK] {len(df):,} filas insertadas\n")

    # PASO 7: Verificar
    print("[7] Verificación:")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(f"""SELECT fecha_venta, COUNT(*) lineas, ROUND(SUM(venta_bruta), 0) venta
        FROM ventas WHERE fecha_venta >= '{fecha_inicio}' AND fecha_venta <= '{fecha_fin}'
        GROUP BY fecha_venta ORDER BY fecha_venta""")

    print("=" * 70)
    print(f"VENTA {fecha_inicio.upper()} A {fecha_fin.upper()} (SINCRONIZADOR V2):")
    print("=" * 70)

    total_venta = 0
    for fecha, lineas, venta in cur.fetchall():
        print(f"  {fecha}: {lineas:>6,} líneas | ${venta:>16,.0f}")
        total_venta += venta

    print("-" * 70)
    print(f"  TOTAL: ${total_venta:>16,.0f}")
    print("=" * 70)

    conn.close()

if __name__ == '__main__':
    sincronizar_ventas()
