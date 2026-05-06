#!/usr/bin/env python3
"""
Sincronizador de ventas Odoo -> SQLite (Maestra de Ventas)
Versión ultra-simple: solo datos básicos, sin complejidad.
"""
import sys
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import json
import traceback

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.config import Config

# Paths
DB_LOCAL = Path.home() / 'Desktop' / 'finanzas-unionx-app' / 'maestra_ventas.db'
DB_PROJECT = PROJECT_ROOT / 'data' / 'db' / 'maestra_ventas.db'
LOG_DIR = PROJECT_ROOT / 'logs'
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / 'sincronizador.log'
STATE_FILE = LOG_DIR / 'sync_state.json'

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Limpiar caracteres especiales
    msg_clean = msg.encode('ascii', 'ignore').decode('ascii')
    line = f"[{timestamp}] {msg_clean}"
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def get_db():
    return DB_LOCAL if DB_LOCAL.exists() else DB_PROJECT

def get_fecha_max_bd():
    db = get_db()
    try:
        conn = sqlite3.connect(str(db))
        cur = conn.cursor()
        cur.execute("SELECT MAX(fecha_venta) FROM ventas")
        result = cur.fetchone()[0]
        conn.close()
        return result
    except:
        return None

def save_sync_state(rows_synced):
    state = {
        'last_sync': datetime.now().isoformat(),
        'rows_synced': rows_synced
    }
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except:
        pass

def sync_ventas():
    log("=" * 80)
    log("SINCRONIZADOR VENTAS - Inicio")
    log("=" * 80)

    try:
        # [1] Período
        log("\n[1/3] Determinando período...")
        fecha_max = get_fecha_max_bd()
        if fecha_max:
            fecha_ini = (datetime.strptime(fecha_max, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
            log(f"      Desde BD: {fecha_max} > buscando desde {fecha_ini}")
        else:
            fecha_ini = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
            log(f"      Primera carga: buscando últimos 60 días")

        fecha_fin = datetime.now().strftime('%Y-%m-%d')
        log(f"      Hasta: {fecha_fin}\n")

        # [2] Extraer desde Odoo
        log("[2/3] Extrayendo desde Odoo...")
        odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)

        # Buscar directamente sale.order.line (sin restriccion de estado)
        domain = [
            ('order_id.date_order', '>=', fecha_ini),
            ('order_id.date_order', '<=', fecha_fin)
        ]

        lines = odoo.search_read('sale.order.line', domain,
            ['id', 'order_id', 'product_id', 'product_uom_qty', 'price_subtotal'],
            limit=100000)

        log(f"      Encontradas {len(lines)} líneas\n")

        if not lines:
            log("      [INFO] Sin datos nuevos\n")
            save_sync_state(0)
            log("=" * 80)
            log("[OK] COMPLETADA (0 registros)")
            log("=" * 80)
            return 0

        # [3] Insertar
        log("[3/3] Insertando en BD...")

        rows_data = []
        for line in lines:
            try:
                order_name = line['order_id'][1] if line.get('order_id') else 'UNKNOWN'
                product_name = line['product_id'][1] if line.get('product_id') else ''

                rows_data.append({
                    'documento': order_name,
                    'fecha_venta': line['order_id'][2][:10] if line.get('order_id') and len(line['order_id']) > 2 else datetime.now().strftime('%Y-%m-%d'),
                    'producto': product_name[:80],
                    'cantidad': line.get('product_uom_qty', 0),
                    'venta_bruta': line.get('price_subtotal', 0),
                    'costo_total': 0,
                    'margen_final': line.get('price_subtotal', 0),
                    'tipo_movimiento': 'Venta',
                })
            except Exception as e:
                log(f"      WARN: Línea {line.get('id')}: {e}")
                continue

        if not rows_data:
            log("      [INFO] Sin líneas válidas\n")
            save_sync_state(0)
            log("=" * 80)
            log("[OK] COMPLETADA (0 registros)")
            log("=" * 80)
            return 0

        df = pd.DataFrame(rows_data)
        db = get_db()
        conn = sqlite3.connect(str(db))

        # Deduplicar
        cursor = conn.cursor()
        for _, row in df.iterrows():
            cursor.execute(
                "DELETE FROM ventas WHERE documento = ? AND fecha_venta = ? AND venta_bruta = ?",
                (row['documento'], row['fecha_venta'], row['venta_bruta'])
            )

        # Insertar
        df.to_sql('ventas', conn, if_exists='append', index=False, chunksize=500)

        # Metadata
        cursor.execute("""
            INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            'Odoo',
            len(df),
            df['fecha_venta'].min(),
            df['fecha_venta'].max(),
            'sync'
        ))

        conn.commit()
        conn.close()

        log(f"      [OK] {len(df):,} registros insertados\n")

        save_sync_state(len(df))

        venta_total = df['venta_bruta'].sum()
        log("[RESUMEN]")
        log(f"      Registros: {len(df):,}")
        log(f"      Venta: ${venta_total:,.0f}")
        log("=" * 80)
        log("[OK] COMPLETADA")
        log("=" * 80)

        return len(df)

    except Exception as e:
        log(f"\n[ERROR] {e}")
        log(f"Traceback: {traceback.format_exc()}\n")
        save_sync_state(0)
        log("=" * 80)
        log("[FATAL] COMPLETADA CON ERRORES")
        log("=" * 80)
        return 0

if __name__ == '__main__':
    try:
        sync_ventas()
    except Exception as e:
        log(f"[FATAL] {e}\n{traceback.format_exc()}")
