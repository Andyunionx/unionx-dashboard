"""One-shot: limpia filas duplicadas literales del parquet ventas.

Detecta y elimina filas DUPLICADAS en todas las columnas clave (pedido, sku,
fecha_venta, documento, tipo_movimiento, venta_bruta, cantidad). Solo si
TODAS coinciden, se considera dup real.

Backup automatico antes de modificar.
"""
from pathlib import Path
from datetime import datetime
import warnings

import pandas as pd

warnings.filterwarnings('ignore')
PROJECT_ROOT = Path(__file__).resolve().parent

# Clave estricta: si TODAS estas columnas son iguales en 2+ filas, una sobra
KEY_COLS = ['pedido', 'sku', 'fecha_venta_str', 'documento', 'tipo_movimiento',
            'venta_bruta_r', 'cantidad']


def limpiar(parquet_path: Path) -> dict:
    print(f'\n=== {parquet_path.name} ===')
    df = pd.read_parquet(parquet_path)
    n_pre = len(df)
    monto_pre = float(pd.to_numeric(df['venta_bruta'], errors='coerce').fillna(0).sum())
    print(f'  Filas antes: {n_pre:,}')
    print(f'  Venta bruta antes: ${monto_pre/1e6:.2f}M')

    # Convertir category a object para evitar problemas con cartesian product
    for c in df.columns:
        if str(df[c].dtype) == 'category':
            df[c] = df[c].astype('object')

    # Normalizar columnas para comparacion
    df['fecha_venta_str'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    df['venta_bruta_r'] = pd.to_numeric(df['venta_bruta'], errors='coerce').fillna(0).round(2)
    df['cantidad'] = pd.to_numeric(df['cantidad'], errors='coerce').fillna(0)

    # Dedup: keep='first'
    df_dedup = df.drop_duplicates(subset=KEY_COLS, keep='first')

    # Limpiar columnas helper
    df_dedup = df_dedup.drop(columns=['fecha_venta_str', 'venta_bruta_r'])

    n_post = len(df_dedup)
    monto_post = float(pd.to_numeric(df_dedup['venta_bruta'], errors='coerce').fillna(0).sum())
    extras = n_pre - n_post
    delta_monto = monto_post - monto_pre

    print(f'  Filas despues: {n_post:,} (-{extras:,})')
    print(f'  Venta bruta despues: ${monto_post/1e6:.2f}M (delta: ${delta_monto/1e6:+.2f}M)')

    # Backup
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = parquet_path.with_suffix(f'.bak_predup_{ts}.parquet')
    parquet_path.rename(backup)
    print(f'  Backup: {backup.name}')

    # Guardar dedupd
    df_dedup.to_parquet(parquet_path, index=False, compression='zstd', compression_level=3)
    new_size = parquet_path.stat().st_size / (1024 * 1024)
    print(f'  Guardado: {new_size:.1f} MB')

    return {
        'file': parquet_path.name,
        'filas_pre': n_pre,
        'filas_post': n_post,
        'extras_quitadas': extras,
        'monto_pre_mm': monto_pre / 1e6,
        'monto_post_mm': monto_post / 1e6,
        'delta_monto_mm': delta_monto / 1e6,
        'backup': str(backup),
    }


def main():
    paths = [
        PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet',
        PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet',
    ]
    resultados = []
    for p in paths:
        if p.exists():
            resultados.append(limpiar(p))

    print(f'\n=== RESUMEN ===')
    total_extras = sum(r['extras_quitadas'] for r in resultados)
    total_delta = sum(r['delta_monto_mm'] for r in resultados)
    print(f'Total filas quitadas: {total_extras:,}')
    print(f'Total monto neto: ${total_delta:+.2f}M')


if __name__ == '__main__':
    main()
