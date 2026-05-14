#!/usr/bin/env python3
"""
Descarga el mes actual desde Turso y lo guarda en parquet local.

El dashboard de Ventas usa este parquet para mostrar el mes en curso en lugar
de hacer chunks HTTP a Turso desde Streamlit Cloud (que sufre ReadTimeout por
latencia EU↔US).

Output: data/historico/ventas_mes_actual.parquet

Pensado para correr horario vía GH Actions (que está en US East, mismo
data-center que Turso → latencia <50ms, sin timeouts).

Uso:
    python extract_mes_actual_a_parquet.py
    python extract_mes_actual_a_parquet.py --mes 2026-05  # explícito
"""
import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
OUT_PATH = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'

# Mismas 40 cols del parquet histórico + venta_neta
COLS_DB = [
    'tipo_movimiento', 'bodega', 'documento', 'fecha_documento', 'pedido',
    'estado_pedido', 'tipo_despacho', 'sku', 'canal', 'fecha_venta',
    'hora_venta', 'producto', 'categoria_macro', 'categoria_padre',
    'categoria_hijo', 'categoria_comercial', 'estado_sku', 'pack', 'marca',
    'proveedor', 'tipo_marca', 'tipo_compra', 'tipo_negocio', 'kam',
    'estado_canal', 'anio_venta', 'mes_venta', 'semana_venta', 'dia_semana',
    'hora_venta_num', 'cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario',
    'costo_total', 'margen_front', 'comision_pct', 'comision', 'logistica',
    'marketing', 'margen_final',
]


def _load_env():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _mes_actual_yyyymm() -> str:
    return datetime.now().strftime('%Y-%m')


def _rango_mes(yyyymm: str) -> tuple[str, str]:
    año, mes = map(int, yyyymm.split('-'))
    desde = f"{año:04d}-{mes:02d}-01"
    if mes == 12:
        hasta = f"{año + 1:04d}-01-01"
    else:
        hasta = f"{año:04d}-{mes + 1:02d}-01"
    return desde, hasta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mes', default=None, help='YYYY-MM (default: mes actual)')
    args = parser.parse_args()

    _load_env()
    if not os.environ.get('LIBSQL_URL') or not os.environ.get('LIBSQL_AUTH_TOKEN'):
        print('[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no setados')
        sys.exit(1)

    mes = args.mes or _mes_actual_yyyymm()
    desde, hasta = _rango_mes(mes)
    print(f"[1] Descargando ventas {mes} ({desde} a {hasta}) desde Turso...")

    import libsql_client
    client = libsql_client.create_client_sync(
        url=os.environ['LIBSQL_URL'],
        auth_token=os.environ['LIBSQL_AUTH_TOKEN'],
    )

    t0 = time.time()
    cols_csv = ','.join(COLS_DB)
    # Trae todo el mes en una sola query (libsql_client es eficiente sobre HTTP)
    rs = client.execute(
        f"SELECT {cols_csv} FROM ventas "
        f"WHERE fecha_venta >= '{desde}' AND fecha_venta < '{hasta}' "
        f"ORDER BY fecha_venta"
    )
    elapsed = time.time() - t0
    print(f"   {len(rs.rows):,} filas en {elapsed:.1f}s")

    if not rs.rows:
        print(f"   [WARN] Sin filas en Turso para {mes}. Saliendo sin escribir parquet.")
        client.close()
        sys.exit(0)

    df = pd.DataFrame(rs.rows, columns=COLS_DB)
    # Forzar dtypes
    for c in ('cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario',
              'costo_total', 'margen_front', 'comision_pct', 'comision',
              'logistica', 'marketing', 'margen_final'):
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
    for c in ('anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num'):
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype('int64')
    cols_texto = [c for c in COLS_DB if c not in (
        'cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario', 'costo_total',
        'margen_front', 'comision_pct', 'comision', 'logistica', 'marketing',
        'margen_final', 'anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num',
        'fecha_venta',
    )]
    for c in cols_texto:
        df[c] = df[c].astype('object').where(df[c].notna(), '').astype(str).replace('nan', '')

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"\n[OK] Guardado {OUT_PATH} ({len(df):,} filas, {size_kb:.0f} KB)")
    print(f"     Rango fechas: {df['fecha_venta'].min()} a {df['fecha_venta'].max()}")
    print(f"     Venta bruta total: ${pd.to_numeric(df['venta_bruta']).sum():,.0f}")
    client.close()


if __name__ == '__main__':
    main()
