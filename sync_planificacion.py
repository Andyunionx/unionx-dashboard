#!/usr/bin/env python3
"""
Sync diario de Planificación (Fase 2).

Llena 3 tablas Turso con la "foto live" del día, contra la baseline al 11/05:
  - planif_ventas_diarias_sku  → ventas reales por SKU x día desde 2026-05-11
  - planif_stock_live          → foto stock por SKU agregado por categoría de bodega
  - planif_transito_live       → tránsito vigente (parquet comex/transito.parquet)

Diseñado para correr en GitHub Actions cron 06:00 AM Chile (09:00 UTC) y vía workflow_dispatch.
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

BASELINE_DATE = '2026-05-11'   # foto inicial — ventas reales se acumulan desde acá
TRANSITO_PARQUET = PROJECT_ROOT / 'data' / 'comex' / 'transito.parquet'


# ============================================================
# Turso helpers (retry + reconexión)
# ============================================================
def _new_client():
    import libsql_client
    return libsql_client.create_client_sync(
        url=os.environ['LIBSQL_URL'],
        auth_token=os.environ['LIBSQL_AUTH_TOKEN'],
    )


def exec_retry(sql, args=None, max_retries=4, base_wait=5, label=''):
    last = None
    for a in range(1, max_retries + 1):
        c = None
        try:
            c = _new_client()
            rs = c.execute(sql, args) if args is not None else c.execute(sql)
            c.close()
            return rs
        except Exception as e:
            last = e
            if c:
                try: c.close()
                except: pass
            if a < max_retries:
                w = base_wait * (2 ** (a - 1))
                print(f"  {label} retry {a} ({type(e).__name__}) en {w}s...", flush=True)
                time.sleep(w)
    raise last


def _f(v):
    """to_float robusto contra NaN/None/str."""
    import math
    if v is None: return None
    if isinstance(v, float) and math.isnan(v): return None
    if isinstance(v, str):
        v = v.replace(',', '.').strip()
        if not v or v.lower() in ('nan', 'nat', 'none'): return None
        try:
            f = float(v)
            return None if math.isnan(f) else f
        except: return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except: return None


def _s(v):
    """to_str robusto."""
    import math
    if v is None: return None
    if isinstance(v, float) and math.isnan(v): return None
    s = str(v).strip()
    if not s or s.lower() in ('nan', 'nat', 'none'): return None
    return s


# ============================================================
# SCHEMA — crea tablas si no existen
# ============================================================
def crear_tablas():
    for sql, label in [
        ("""CREATE TABLE IF NOT EXISTS planif_ventas_diarias_sku (
            sku TEXT, fecha TEXT,
            unidades REAL, venta_neta REAL, margen_front REAL,
            ts_actualizado TEXT,
            PRIMARY KEY (sku, fecha)
        )""", "ventas"),
        ("""CREATE TABLE IF NOT EXISTS planif_stock_live (
            sku TEXT PRIMARY KEY,
            producto TEXT, marca TEXT, categoria TEXT,
            stock_total REAL, stock_disponible REAL, stock_reservado REAL,
            valor_total_clp REAL,
            ca1_hijas REAL, full_meli REAL, full_fala REAL,
            full_paris REAL, full_ripley REAL,
            volcan REAL, duty_travel REAL, reserva REAL,
            tiendas REAL, marketing REAL, otros REAL,
            ts_snapshot TEXT
        )""", "stock"),
        ("""CREATE TABLE IF NOT EXISTS planif_transito_live (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT, producto TEXT, pi TEXT, status TEXT,
            transporte TEXT, nro_pedido TEXT,
            cantidad REAL, costo_unitario_usd REAL, costo_total_usd REAL,
            costo_ingreso_clp REAL,
            fecha_embarque TEXT, fecha_eta_chile TEXT, fecha_eta_bodega TEXT,
            ts_actualizado TEXT
        )""", "transito"),
    ]:
        exec_retry(sql, label=f'[create-{label}]')
    print(f"[schema] Tablas creadas/existen: planif_ventas_diarias_sku, planif_stock_live, planif_transito_live", flush=True)


# ============================================================
# 1. Ventas diarias por SKU desde 2026-05-11
# ============================================================
def sync_ventas_diarias():
    print(f"\n[ventas] Pulling Turso ventas desde {BASELINE_DATE}...", flush=True)
    rs = exec_retry(
        """SELECT sku, fecha_venta,
                  SUM(COALESCE(cantidad,0)) AS unid,
                  SUM(COALESCE(venta_bruta,0)) AS venta_bruta,
                  SUM(COALESCE(margen_front,0)) AS margen
           FROM ventas
           WHERE fecha_venta >= ?
             AND sku IS NOT NULL AND sku != ''
           GROUP BY sku, fecha_venta""",
        [BASELINE_DATE], label='[ventas-pull]'
    )
    rows = list(rs.rows)
    print(f"  Filas agregadas: {len(rows):,}", flush=True)

    if not rows:
        print(f"  Sin ventas desde {BASELINE_DATE}. Skip.", flush=True)
        return

    # DELETE + INSERT (idempotente — pisa todo lo desde BASELINE_DATE)
    exec_retry(
        "DELETE FROM planif_ventas_diarias_sku WHERE fecha >= ?",
        [BASELINE_DATE], label='[ventas-del]'
    )

    ts = datetime.now().isoformat(timespec='seconds')
    cols = 'sku, fecha, unidades, venta_neta, margen_front, ts_actualizado'
    ph = '(' + ','.join('?' * 6) + ')'
    inserted = 0
    batch = 100
    for i in range(0, len(rows), batch):
        chunk = rows[i:i+batch]
        sql = f"INSERT INTO planif_ventas_diarias_sku ({cols}) VALUES " + ','.join([ph] * len(chunk))
        flat = []
        for r in chunk:
            flat.extend([_s(r[0]), _s(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), ts])
        rs = exec_retry(sql, flat, label=f'  [ventas-ins b{i//batch+1}]')
        inserted += rs.rows_affected
    print(f"  Insertados: {inserted:,} filas", flush=True)


# ============================================================
# 2. Stock live desde Odoo (extracción directa)
# ============================================================
def _clasificar_bodega(bodega_path: str) -> str:
    """Mapea bodega Odoo a categoría agregada."""
    if not bodega_path:
        return 'otros'
    b = bodega_path.upper()
    # Fulfillment marketplaces
    if 'BFML' in b or 'FULL ML' in b or 'FULFILLMENT ML' in b:
        return 'full_meli'
    if 'BFP' in b and 'PARIS' in b or 'FULL PARIS' in b:
        return 'full_paris'
    if 'BFP' in b or 'FULL FAL' in b or 'FULL FALABELLA' in b:
        return 'full_fala'
    if 'BFR' in b or 'FULL RIP' in b or 'FULL RIPLEY' in b:
        return 'full_ripley'
    if 'BFW' in b or 'WALMART' in b:
        return 'otros'  # Walmart no está en lista del user
    # CA1 / Stock + hijas
    if 'CA1' in b or '/STOCK' in b or b.endswith('STOCK') or 'BODEGA PRINCIPAL' in b:
        return 'ca1_hijas'
    # Volcán
    if 'VOLCÁN' in b or 'VOLCAN' in b or 'EL VOLCAN' in b:
        return 'volcan'
    # Duty Travel
    if 'DUTY' in b or 'TRAVEL' in b:
        return 'duty_travel'
    # Reserva
    if 'RESERVA' in b:
        return 'reserva'
    # Tiendas / Marketing / PV
    if 'BPV' in b or 'POST VENTA' in b or 'OUTLET' in b or 'TIENDA' in b:
        return 'tiendas'
    if 'BMP' in b or 'MARKETING' in b or 'MK' in b:
        return 'marketing'
    return 'otros'


def sync_stock_live():
    print(f"\n[stock] Conectando a Odoo...", flush=True)
    from app.core.odoo_client import OdooClient
    from app.services.stock_advanced_service import StockAdvancedService

    odoo = OdooClient(
        url='https://unionxb2b.odoo.com',
        db='bmya-innovatek-sh-prd-6981800',
        username='andres@grupoeter.cl',
        password=os.environ['ANDRES_ODOO_PASSWORD'],
    )
    svc = StockAdvancedService(odoo)

    print(f"  Extrayendo stock + ventas 90d (3-5 min)...", flush=True)
    t0 = time.time()
    data = svc.extract_full(progress_callback=None)
    print(f"  Listo en {time.time()-t0:.0f}s", flush=True)

    df = pd.DataFrame(data['detalle'])
    if df.empty:
        print("  Sin detalle de stock. Skip.", flush=True)
        return

    # Categorizar bodega
    df['categoria_bodega'] = df['Bodega'].apply(_clasificar_bodega)

    # Agregar por SKU x categoria_bodega
    pivot = df.pivot_table(
        index='SKU', columns='categoria_bodega', values='Qty', aggfunc='sum', fill_value=0
    ).reset_index()

    # Asegurar todas las cols esperadas (rellena con 0 si no existe)
    for col in ['ca1_hijas', 'full_meli', 'full_fala', 'full_paris', 'full_ripley',
                'volcan', 'duty_travel', 'reserva', 'tiendas', 'marketing', 'otros']:
        if col not in pivot.columns:
            pivot[col] = 0

    # Totales agregados por SKU
    df_agg_skus = pd.DataFrame(data['skus'])
    df_agg = df.groupby('SKU').agg(
        producto=('Producto', 'first'),
        marca=('Marca', 'first'),
        categoria=('Categoria', 'first'),
        stock_total=('Qty', 'sum'),
        stock_disponible=('Disponible', 'sum'),
        stock_reservado=('Reservada', 'sum'),
        valor_total_clp=('Valor', 'sum'),
    ).reset_index()

    final = df_agg.merge(pivot, on='SKU', how='left').fillna(0)
    print(f"  SKUs agregados: {len(final):,}", flush=True)

    # Upsert: REPLACE entera tabla
    exec_retry("DELETE FROM planif_stock_live", label='[stock-del]')

    ts = datetime.now().isoformat(timespec='seconds')
    cols = ('sku, producto, marca, categoria, stock_total, stock_disponible, '
            'stock_reservado, valor_total_clp, ca1_hijas, full_meli, full_fala, '
            'full_paris, full_ripley, volcan, duty_travel, reserva, tiendas, '
            'marketing, otros, ts_snapshot')
    ph = '(' + ','.join('?' * 20) + ')'
    inserted = 0
    batch = 100
    rows_list = []
    for _, r in final.iterrows():
        sku = _s(r['SKU'])
        if not sku:
            continue
        rows_list.append((
            sku, _s(r.get('producto')), _s(r.get('marca')), _s(r.get('categoria')),
            _f(r.get('stock_total')), _f(r.get('stock_disponible')),
            _f(r.get('stock_reservado')), _f(r.get('valor_total_clp')),
            _f(r.get('ca1_hijas')), _f(r.get('full_meli')), _f(r.get('full_fala')),
            _f(r.get('full_paris')), _f(r.get('full_ripley')),
            _f(r.get('volcan')), _f(r.get('duty_travel')), _f(r.get('reserva')),
            _f(r.get('tiendas')), _f(r.get('marketing')), _f(r.get('otros')),
            ts,
        ))

    for i in range(0, len(rows_list), batch):
        chunk = rows_list[i:i+batch]
        sql = f"INSERT INTO planif_stock_live ({cols}) VALUES " + ','.join([ph] * len(chunk))
        flat = [x for r in chunk for x in r]
        try:
            rs = exec_retry(sql, flat, label=f'  [stock-ins b{i//batch+1}]', max_retries=2)
            inserted += rs.rows_affected
        except Exception as e:
            print(f"    batch falló, row-by-row...", flush=True)
            for r in chunk:
                try:
                    sql_one = f"INSERT INTO planif_stock_live ({cols}) VALUES " + ph
                    rs = exec_retry(sql_one, list(r), label=f'    [stock r]', max_retries=1)
                    inserted += rs.rows_affected
                except Exception as ee:
                    print(f"    ✗ FAIL sku={r[0]!r}: {type(ee).__name__}", flush=True)
    print(f"  Insertados: {inserted:,} SKUs", flush=True)


# ============================================================
# 3. Tránsito live desde parquet
# ============================================================
def sync_transito_live():
    print(f"\n[transito] Leyendo {TRANSITO_PARQUET}...", flush=True)
    if not TRANSITO_PARQUET.exists():
        print(f"  No existe parquet. Skip.", flush=True)
        return

    df = pd.read_parquet(TRANSITO_PARQUET)
    df = df[df['sku'].notna()].copy()
    print(f"  {len(df):,} filas de tránsito", flush=True)

    exec_retry("DELETE FROM planif_transito_live", label='[transito-del]')

    ts = datetime.now().isoformat(timespec='seconds')

    def _date(v):
        if v is None or pd.isna(v): return None
        if hasattr(v, 'isoformat'):
            return v.isoformat()[:10]
        s = str(v).strip()
        return s[:10] if s and s.lower() != 'nat' else None

    rows = []
    for _, r in df.iterrows():
        rows.append((
            _s(r.get('sku')), _s(r.get('producto')), _s(r.get('pi')), _s(r.get('status')),
            _s(r.get('transporte')), _s(r.get('nro_pedido')),
            _f(r.get('cantidad')), _f(r.get('costo_unitario_usd')),
            _f(r.get('costo_total_usd')), _f(r.get('costo_ingreso_clp')),
            _date(r.get('fecha_embarque')), _date(r.get('fecha_eta_chile')),
            _date(r.get('fecha_eta_bodega')),
            ts,
        ))

    cols = ('sku, producto, pi, status, transporte, nro_pedido, '
            'cantidad, costo_unitario_usd, costo_total_usd, costo_ingreso_clp, '
            'fecha_embarque, fecha_eta_chile, fecha_eta_bodega, ts_actualizado')
    ph = '(' + ','.join('?' * 14) + ')'
    inserted = 0
    batch = 100
    for i in range(0, len(rows), batch):
        chunk = rows[i:i+batch]
        sql = f"INSERT INTO planif_transito_live ({cols}) VALUES " + ','.join([ph] * len(chunk))
        flat = [x for r in chunk for x in r]
        rs = exec_retry(sql, flat, label=f'  [transito-ins b{i//batch+1}]')
        inserted += rs.rows_affected
    print(f"  Insertados: {inserted:,} filas", flush=True)


# ============================================================
# Main
# ============================================================
def main():
    print(f"=== SYNC PLANIFICACIÓN — {datetime.now().isoformat()} ===\n", flush=True)

    # Cargar .env local si existe (en GH Actions vienen como env vars del runner)
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    for v in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN', 'ANDRES_ODOO_PASSWORD'):
        if not os.environ.get(v):
            print(f"[ERROR] env var {v} no seteada", flush=True)
            return 1

    crear_tablas()

    # 1) Ventas (rápido, viene de Turso)
    try:
        sync_ventas_diarias()
    except Exception as e:
        print(f"[ERROR ventas] {type(e).__name__}: {str(e)[:200]}", flush=True)

    # 2) Stock live (lento — extracción Odoo)
    try:
        sync_stock_live()
    except Exception as e:
        print(f"[ERROR stock] {type(e).__name__}: {str(e)[:200]}", flush=True)
        import traceback
        traceback.print_exc()

    # 3) Tránsito live (rápido — parquet)
    try:
        sync_transito_live()
    except Exception as e:
        print(f"[ERROR transito] {type(e).__name__}: {str(e)[:200]}", flush=True)

    print(f"\n=== SYNC COMPLETO ===", flush=True)

    # Resumen
    for tbl in ['planif_ventas_diarias_sku', 'planif_stock_live', 'planif_transito_live']:
        try:
            rs = exec_retry(f"SELECT COUNT(*) FROM {tbl}", label=f'[count-{tbl}]', max_retries=2)
            print(f"  {tbl}: {rs.rows[0][0]:,} filas", flush=True)
        except Exception as e:
            print(f"  {tbl}: error count ({type(e).__name__})", flush=True)

    return 0


if __name__ == '__main__':
    sys.exit(main())
