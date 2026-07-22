#!/usr/bin/env python3
"""
Descarga datos de ventas del mes actual desde Turso y guarda ventas_mes_actual.parquet.

Úsalo manualmente o vía GitHub Actions (.github/workflows/sync_ventas_diario.yml).

Uso:
    python sync_ventas_mes_actual.py                  # desde CUTOFF_HISTORICO hasta hoy
    python sync_ventas_mes_actual.py --desde 2026-06-01  # override fecha inicio

Requiere env vars: LIBSQL_URL, LIBSQL_AUTH_TOKEN
  - Local: cargadas desde .env automáticamente
  - GH Actions: definir como secrets en el repo
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
PARQUET_PATH = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
SHARED_PATH  = PROJECT_ROOT / 'views' / 'shared.py'

COLS = [
    'tipo_movimiento', 'bodega', 'documento', 'fecha_documento', 'pedido',
    'estado_pedido', 'tipo_despacho', 'sku', 'canal', 'fecha_venta',
    'hora_venta', 'producto', 'categoria_macro', 'categoria_padre',
    'categoria_hijo', 'categoria_comercial', 'estado_sku', 'pack', 'marca',
    'proveedor', 'tipo_marca', 'tipo_compra', 'tipo_negocio', 'kam',
    'estado_canal', 'anio_venta', 'mes_venta', 'semana_venta', 'dia_semana',
    'hora_venta_num', 'cantidad', 'venta_bruta', 'costo_unitario',
    'costo_total', 'margen_front', 'comision_pct', 'comision', 'logistica',
    'marketing', 'margen_final', 'venta_neta',
]

NUMERIC_COLS = {
    'anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num',
    'cantidad', 'venta_bruta', 'costo_unitario', 'costo_total',
    'margen_front', 'comision_pct', 'comision', 'logistica',
    'marketing', 'margen_final', 'venta_neta',
}


def _load_env():
    if os.environ.get('LIBSQL_URL') and os.environ.get('LIBSQL_AUTH_TOKEN'):
        return
    env_path = PROJECT_ROOT / '.env'
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            k = k.strip()
            if k in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN') and not os.environ.get(k):
                os.environ[k] = v.strip().strip('"').strip("'")


def _leer_cutoff() -> str:
    m = re.search(r"CUTOFF_HISTORICO\s*=\s*['\"](\d{4}-\d{2}-\d{2})['\"]",
                  SHARED_PATH.read_text(encoding='utf-8'))
    return m.group(1) if m else '2026-01-01'


def _turso_query(sql: str, retries: int = 5, timeout_s: int = 120) -> dict:
    url = os.environ['LIBSQL_URL'].rstrip('/')
    tok = os.environ['LIBSQL_AUTH_TOKEN']
    hdr = {'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}
    body = {'requests': [{'type': 'execute', 'stmt': {'sql': sql}}, {'type': 'close'}]}
    last = None
    for i in range(retries):
        try:
            r = requests.post(f"{url}/v2/pipeline", json=body, headers=hdr, timeout=timeout_s)
            r.raise_for_status()
            return r.json()['results'][0]['response']['result']
        except (requests.exceptions.RequestException, KeyError) as e:
            last = e
            wait = min(30, 2 + i * 5)
            print(f"   [retry {i+1}/{retries}] {type(e).__name__}: esperando {wait}s...")
            time.sleep(wait)
    raise last


def _descargar_ventas(desde: str, hasta: str, chunk: int = 5000) -> pd.DataFrame:
    print(f"[1] Descargando ventas Turso: {desde} - {hasta}")
    cols_csv = ','.join(COLS)
    last_rowid = 0
    chunks = []
    n = 0
    while True:
        sql = (f"SELECT rowid, {cols_csv} FROM ventas "
               f"WHERE fecha_venta >= '{desde}' AND fecha_venta <= '{hasta}' "
               f"AND rowid > {last_rowid} ORDER BY rowid LIMIT {chunk}")
        result = _turso_query(sql)
        rows = result['rows']
        if not rows:
            break
        flat = []
        for r in rows:
            vals = [c.get('value') if isinstance(c, dict) else c for c in r]
            last_rowid = int(vals[0])
            flat.append(vals[1:])
        chunks.append(pd.DataFrame(flat, columns=COLS))
        n += len(rows)
        print(f"   chunk {len(chunks)}: +{len(rows):,} (total {n:,})")
        if len(rows) < chunk:
            break
    if not chunks:
        return pd.DataFrame(columns=COLS)
    return pd.concat(chunks, ignore_index=True)


def _castear(df: pd.DataFrame) -> pd.DataFrame:
    df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce')
    df['fecha_venta'] = df['fecha_venta'].dt.strftime('%Y-%m-%d')
    for c in NUMERIC_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    cols_texto = [c for c in COLS if c not in NUMERIC_COLS and c != 'fecha_venta']
    for c in cols_texto:
        if c in df.columns:
            df[c] = df[c].astype(object).where(df[c].notna(), '').astype(str).replace('nan', '')
    return df


def main():
    # ⛔ DEPRECADO (21-jul-2026): este script lee de TURSO, que está MUERTO desde
    # may-2026 (migración a Parquet+DuckDB). Bajaba datos viejos/incompletos y PISABA
    # el ventas_mes_actual.parquet bueno del extract Odoo → clobber de julio (20 y 21-jul,
    # $373M→$147M y $411M→$122M). La ÚNICA fuente válida es
    # extract_mes_actual_a_parquet.py --source odoo (pulso / sync_mes_actual).
    # No sobrescribe nada salvo que se fuerce con FORCE_TURSO_SYNC=1.
    if os.environ.get('FORCE_TURSO_SYNC') != '1':
        print("[DESHABILITADO] sync_ventas_mes_actual.py usa Turso (muerto) y clobbea "
              "el mes_actual bueno. NO se sobrescribe. Fuente válida: "
              "extract_mes_actual_a_parquet.py --source odoo. Forzar: FORCE_TURSO_SYNC=1.")
        sys.exit(0)

    _load_env()
    if not os.environ.get('LIBSQL_URL') or not os.environ.get('LIBSQL_AUTH_TOKEN'):
        print("[ERROR] LIBSQL_URL / LIBSQL_AUTH_TOKEN no definidos (ni en env ni en .env)")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument('--desde', default=None,
                        help='Fecha inicio YYYY-MM-DD (default: CUTOFF_HISTORICO de views/shared.py)')
    parser.add_argument('--hasta', default=None,
                        help='Fecha fin YYYY-MM-DD (default: hoy)')
    args = parser.parse_args()

    desde = args.desde or _leer_cutoff()
    hasta  = args.hasta  or date.today().strftime('%Y-%m-%d')

    print(f"Rango: {desde} - {hasta}")

    df = _descargar_ventas(desde, hasta)

    if df.empty:
        print("[WARN] Sin datos en el rango. ventas_mes_actual.parquet no actualizado.")
        sys.exit(0)

    df = _castear(df)
    total_venta = pd.to_numeric(df['venta_neta'], errors='coerce').sum()
    print(f"\n[2] Total descargado: {len(df):,} filas | Venta neta: ${total_venta/1e6:.1f}M")

    # Stats por mes
    df['_mes'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.to_period('M').astype(str)
    print("\n   Por mes:")
    for mes, v in df.groupby('_mes')['venta_neta'].apply(
        lambda x: pd.to_numeric(x, errors='coerce').sum()
    ).items():
        print(f"     {mes}: ${v/1e6:.1f}M")
    df = df.drop(columns='_mes')

    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    df[COLS].to_parquet(PARQUET_PATH, index=False)
    size_mb = PARQUET_PATH.stat().st_size / 1e6
    print(f"\n[OK] Guardado {PARQUET_PATH} ({size_mb:.1f} MB)")


if __name__ == '__main__':
    main()
