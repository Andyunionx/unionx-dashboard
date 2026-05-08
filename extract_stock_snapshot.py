#!/usr/bin/env python3
"""
Extrae snapshot de Stock desde Odoo y guarda parquets en data/stock/.
Diseñado para correr en GitHub Actions cada 3h.

Genera:
- data/stock/skus.parquet      (df_agg: 1 fila por SKU con KPIs)
- data/stock/detalle.parquet   (df_full: 1 fila por quant en bodega)
- data/stock/metadata.json     (timestamp, contadores)
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.services.stock_advanced_service import StockAdvancedService
from app.core.odoo_client import OdooClient

ODOO_URL = 'https://unionxb2b.odoo.com'
ODOO_DB = 'bmya-innovatek-sh-prd-6981800'
ODOO_USER = 'andres@grupoeter.cl'
ODOO_PASSWORD = os.environ.get('ANDRES_ODOO_PASSWORD')

if not ODOO_PASSWORD:
    print("[ERROR] ANDRES_ODOO_PASSWORD no seteado", flush=True)
    sys.exit(1)

OUTPUT_DIR = PROJECT_ROOT / 'data' / 'stock'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"=== Extracción Stock Snapshot — {datetime.now()} ===", flush=True)

# Conectar a Odoo
print("[1/3] Conectando a Odoo...", flush=True)
odoo = OdooClient(url=ODOO_URL, db=ODOO_DB, username=ODOO_USER, password=ODOO_PASSWORD)
service = StockAdvancedService(odoo)

# Extract
print("[2/3] Extrayendo stock + ventas 90d...", flush=True)
data = service.extract_full(progress_callback=None)

# Guardar parquets
print("[3/3] Guardando parquets...", flush=True)
df_skus = pd.DataFrame(data['skus'])
df_detalle = pd.DataFrame(data['detalle'])

# Optimizar tipos para parquet más chico
for c in df_skus.columns:
    if df_skus[c].dtype == 'object':
        df_skus[c] = df_skus[c].astype(str)
for c in df_detalle.columns:
    if df_detalle[c].dtype == 'object':
        df_detalle[c] = df_detalle[c].astype(str)

df_skus.to_parquet(OUTPUT_DIR / 'skus.parquet', compression='zstd', compression_level=9, index=False)
df_detalle.to_parquet(OUTPUT_DIR / 'detalle.parquet', compression='zstd', compression_level=9, index=False)

# Metadata + KPIs (para acceso rápido sin leer parquet)
meta = {
    'generado_en': datetime.now().isoformat(),
    'total_skus': len(df_skus),
    'total_quants': len(df_detalle),
    'total_locations': data.get('metadata', {}).get('total_locations', 0),
    'kpis': data.get('kpis', {}),
    'ocupacion': data.get('ocupacion', {}),
    'semaforo': data.get('semaforo', []),
    'valor_bodega': data.get('valor_bodega', []),
}
with open(OUTPUT_DIR / 'metadata.json', 'w', encoding='utf-8') as f:
    json.dump(meta, f, indent=2, default=str)

print(f"  ✓ skus.parquet     ({len(df_skus):,} filas, {(OUTPUT_DIR/'skus.parquet').stat().st_size/1024:.1f} KB)", flush=True)
print(f"  ✓ detalle.parquet  ({len(df_detalle):,} filas, {(OUTPUT_DIR/'detalle.parquet').stat().st_size/1024:.1f} KB)", flush=True)
print(f"  ✓ metadata.json    ({len(meta['kpis'])} KPIs, {len(meta['semaforo'])} semaforo entries)", flush=True)
print(f"\n[OK] Snapshot generado", flush=True)
