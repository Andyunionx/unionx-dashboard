"""
Genera parquet con todo el histórico (hasta 2026-03-31) desde el SQLite local.
Se usa como cache estático para acelerar el dashboard.
"""
import os
import sys
import time
import sqlite3
import pandas as pd
from pathlib import Path

LOCAL_DB = Path(__file__).parent / 'data' / 'db' / 'maestra_ventas.db'
OUTPUT = Path(__file__).parent / 'data' / 'historico' / 'ventas_historico.parquet'
CUTOFF = '2026-04-01'  # menor que esta fecha = histórico estático

if not LOCAL_DB.exists():
    print(f"[ERROR] DB local no existe: {LOCAL_DB}", flush=True)
    sys.exit(1)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)

print(f"=== Generando parquet histórico (fecha_venta < {CUTOFF}) ===", flush=True)
print(f"  Source: {LOCAL_DB}", flush=True)
print(f"  Output: {OUTPUT}\n", flush=True)

t0 = time.time()
conn = sqlite3.connect(str(LOCAL_DB))
df = pd.read_sql(
    f"SELECT * FROM ventas WHERE fecha_venta < '{CUTOFF}'",
    conn
)
conn.close()
elapsed = time.time() - t0
print(f"[OK] {len(df):,} filas leídas en {elapsed:.0f}s", flush=True)
print(f"  Memoria DataFrame: {df.memory_usage(deep=True).sum() / 1024 / 1024:.1f} MB", flush=True)

# Compactar tipos (category + int32/float32) — crítico para RAM Streamlit Cloud
from compactar_parquet import compactar_ventas, mem_mb
df = compactar_ventas(df)
print(f"  Memoria DF post-compactar: {mem_mb(df):.1f} MB", flush=True)

# Guardar parquet con compresión zstd (más eficiente que snappy)
df.to_parquet(OUTPUT, compression='zstd', compression_level=9, index=False)
size_mb = OUTPUT.stat().st_size / 1024 / 1024
print(f"\n[OK] Guardado: {OUTPUT}", flush=True)
print(f"  Tamaño: {size_mb:.1f} MB", flush=True)
print(f"  Filas: {len(df):,}", flush=True)
print(f"  Rango fechas: {df['fecha_venta'].min()} → {df['fecha_venta'].max()}", flush=True)
