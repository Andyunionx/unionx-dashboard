"""Dumpea las tablas Turso planif_* a parquet local — fallback de la app.

Cuando Turso bloquea reads (BLOCKED / forbidden), las vistas de la app
Planificación caen automáticamente a estos parquets (ver
views/planning/_data_helpers.py:_try_turso_or_parquet).

Tablas snapshot:
  - planif_master_sku
  - planif_stock_baseline
  - planif_transito_baseline
  - planif_stock_live
  - planif_transito_live
  - planif_ventas_diarias_sku
  - planif_forecast_manual

Output:
  data/planificacion/snapshots/<tabla>.parquet  (compresión zstd)

Diseñado para correr 1× día (post sync_planificacion.py) cuando Turso esté disponible.
No requiere acción manual: si Turso está bloqueado, el script reporta error y termina sin tocar los parquets existentes (mantiene última versión válida).

Uso:
    python extract_planif_snapshots.py            # todas las tablas
    python extract_planif_snapshots.py --tabla planif_stock_live  # solo una
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent
SNAPSHOTS_DIR = PROJECT_ROOT / 'data' / 'planificacion' / 'snapshots'
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
META_PATH = SNAPSHOTS_DIR / '_meta.json'


def _cargar_env():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_cargar_env()
URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')

if not URL or not TOKEN:
    print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no seteados", flush=True)
    sys.exit(1)


# Tabla → (sql_query, dtype_normalizers)
TABLAS = {
    'planif_master_sku': (
        "SELECT sku, id_categoria, marca, categoria_padre, categoria_hijo, "
        "descripcion, total, categoria_producto, pct_proyeccion_vta, "
        "ranking_comercial, stock_hoy FROM planif_master_sku",
        None,
    ),
    'planif_stock_baseline': (
        "SELECT snapshot_date, sku, marca, producto, stock_total, total_full, "
        "bodega_principal, full_meli, full_fala, full_paris, full_ripley, "
        "tiendas, reserva, transito_full_fala, transito_full_meli, costo, valoracion "
        "FROM planif_stock_baseline",
        None,
    ),
    'planif_transito_baseline': (
        "SELECT snapshot_date, sku, variante, pi, status, tipo_transporte, nro_pedido, "
        "cantidad, costo_uni_usd, gift_box_envio, costo_ingreso_clp, "
        "fecha_embarque, fecha_eta_chile, fecha_eta_bodega, mes, stock_actual, "
        "tipo_categoria, valor_usd_total, marca FROM planif_transito_baseline",
        None,
    ),
    'planif_stock_live': (
        "SELECT sku, producto, marca, categoria, stock_total, stock_disponible, "
        "stock_reservado, valor_total_clp, ca1_hijas, full_meli, full_fala, "
        "full_paris, full_ripley, volcan, duty_travel, reserva, tiendas, "
        "marketing, otros, ts_snapshot FROM planif_stock_live",
        None,
    ),
    'planif_transito_live': (
        "SELECT sku, producto, pi, status, transporte, nro_pedido, cantidad, "
        "costo_unitario_usd, costo_total_usd, costo_ingreso_clp, "
        "fecha_embarque, fecha_eta_chile, fecha_eta_bodega, ts_actualizado "
        "FROM planif_transito_live",
        None,
    ),
    'planif_ventas_diarias_sku': (
        "SELECT sku, fecha, unidades, venta_neta, margen_front "
        "FROM planif_ventas_diarias_sku",
        None,
    ),
    'planif_forecast_manual': (
        "SELECT sku, mes, unidades, fuente, ts_actualizado "
        "FROM planif_forecast_manual WHERE unidades IS NOT NULL",
        None,
    ),
}


def _turso_query(sql: str, timeout: int = 180, retries: int = 3):
    """HTTP v2/pipeline directo (igual que views/planning/_data_helpers.py)."""
    headers = {'Authorization': f'Bearer {TOKEN}'}
    body = {'requests': [{'type': 'execute', 'stmt': {'sql': sql}}, {'type': 'close'}]}
    last = None
    for i in range(retries):
        try:
            r = requests.post(f'{URL}/v2/pipeline', json=body, headers=headers, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            first = data.get('results', [{}])[0]
            if first.get('type') == 'error':
                err = first.get('error', {})
                raise RuntimeError(f"{err.get('code', 'ERROR')}: {err.get('message', '?')}")
            return first.get('response', {}).get('result', {})
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(2 ** i)
    raise last


def _result_to_df(result: dict) -> pd.DataFrame:
    """Convierte respuesta Turso v2 (cols + rows con {type,value}) a DataFrame."""
    cols = [c.get('name') for c in result.get('cols', [])]
    rows = result.get('rows', [])
    data = [[v.get('value') for v in row] for row in rows]
    return pd.DataFrame(data, columns=cols)


def snapshot_tabla(tabla: str) -> dict:
    sql, _ = TABLAS[tabla]
    t0 = time.time()
    print(f"[{tabla}] consultando Turso...", flush=True)
    result = _turso_query(sql)
    df = _result_to_df(result)
    dur = time.time() - t0
    out_path = SNAPSHOTS_DIR / f'{tabla}.parquet'
    if df.empty:
        # No sobrescribir parquet existente con tabla vacía (puede ser problema temporal)
        if out_path.exists():
            print(f"  ⚠ Turso devolvió 0 filas. NO sobreescribo parquet existente.", flush=True)
            return {'tabla': tabla, 'filas': 0, 'segundos': dur, 'skipped': True}
        # Si no existe, lo creamos vacío (con schema)
        df.to_parquet(out_path, compression='zstd', compression_level=9, index=False)
        return {'tabla': tabla, 'filas': 0, 'segundos': dur, 'creado_vacio': True}
    df.to_parquet(out_path, compression='zstd', compression_level=9, index=False)
    print(f"  OK {len(df):,} filas en {dur:.1f}s → {out_path.relative_to(PROJECT_ROOT)}", flush=True)
    return {'tabla': tabla, 'filas': len(df), 'segundos': dur}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tabla', help='Solo dumpear esta tabla')
    args = parser.parse_args()

    tablas_a_correr = [args.tabla] if args.tabla else list(TABLAS.keys())
    if args.tabla and args.tabla not in TABLAS:
        print(f"[ERROR] tabla desconocida: {args.tabla}. Disponibles: {list(TABLAS.keys())}")
        return 1

    print(f"=== Extract Planif Snapshots — {datetime.now()} ===\n", flush=True)
    resultados = []
    errores = []
    for tabla in tablas_a_correr:
        try:
            resultados.append(snapshot_tabla(tabla))
        except Exception as e:
            msg = str(e)
            errores.append({'tabla': tabla, 'error': msg})
            print(f"  ✗ FAIL: {type(e).__name__}: {msg[:120]}", flush=True)

    # Meta del último run
    meta = {
        'generado_en': datetime.now().isoformat(),
        'resultados': resultados,
        'errores': errores,
    }
    META_PATH.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str),
                          encoding='utf-8')
    print(f"\n[OK] Meta: {META_PATH.relative_to(PROJECT_ROOT)}", flush=True)
    return 0 if not errores else 2


if __name__ == '__main__':
    sys.exit(main())
