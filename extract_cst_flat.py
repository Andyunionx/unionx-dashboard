"""
Extract brand-level monthly cost projections from REPORTE CST FLAT.
Saves planif_cst_flat_snapshot.parquet for the Coberturas tab.

Usage: python extract_cst_flat.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import openpyxl
import pandas as pd
from pathlib import Path

EXCEL_PATH = Path(r"C:\Users\felip\Desktop\UNIONX\FORECAST FINAL SKU\FORECAST FINAL SKU 26-27 V2.xlsx")
SHEET_NAME = "REPORTE CST FLAT"
OUT_PATH   = Path(__file__).parent / "data" / "planificacion" / "snapshots" / "planif_cst_flat_snapshot.parquet"

# Column indices (0-based) from header inspection:
# [0]=Marca  [4]=SKU  [6]=StockHoy CST  [7]=Cobert.ACT
# AGO26: [26]=StkIni  [28]=Llegadas  [29]=S+P  [30]=Venta  [31]=Cobert
# SEP26: [32]=StkIni  [33]=Llegadas  [34]=S+P  [35]=Venta  [36]=Cobert
# OCT26: [37]=StkIni  [38]=Llegadas  [39]=S+P  [40]=Venta  [41]=Cobert

MONTHS = {
    '2026-08': {'stk_ini': 26, 'llegadas': 28, 'venta': 30},
    '2026-09': {'stk_ini': 32, 'llegadas': 33, 'venta': 35},
    '2026-10': {'stk_ini': 37, 'llegadas': 38, 'venta': 40},
}

_MARCA_NORM = {
    'Lhotse': 'Lhotse', 'Simplit': 'Simplit', 'Levo': 'Levo',
    'Xroad': 'Xroad',   'Bandú': 'Bandú',     'T-Care': 'T-Care',
    'UMA': 'UMA',
    'Dynamo TL': 'Dynamo Tools', 'Dynamo': 'Dynamo Tools',
    'Dinamo Tools': 'Dynamo Tools', 'Dynamo Tools': 'Dynamo Tools',
}

print(f"Leyendo {EXCEL_PATH} ...")
wb = openpyxl.load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
ws = wb[SHEET_NAME]
all_rows = list(ws.iter_rows(values_only=True))
print(f"  {len(all_rows)} filas leídas")

records = []
for r in all_rows[1:]:
    marca_raw = r[0]
    if not marca_raw:
        continue
    marca = _MARCA_NORM.get(str(marca_raw).strip(), str(marca_raw).strip())
    stk_hoy = float(r[6] or 0)

    row = {'marca': marca, 'stock_hoy_cst': stk_hoy}
    for mes, cols in MONTHS.items():
        row[f'{mes}_stk_ini']  = float(r[cols['stk_ini']]  or 0)
        row[f'{mes}_llegadas'] = float(r[cols['llegadas']] or 0)
        row[f'{mes}_venta']    = float(r[cols['venta']]    or 0)
    records.append(row)

df_raw = pd.DataFrame(records)

# Aggregate to brand level (sum all numeric columns)
df_brand = df_raw.groupby('marca', as_index=False).sum(numeric_only=True)

# Convert to $M
cols_m = [c for c in df_brand.columns if c != 'marca']
for c in cols_m:
    df_brand[c] = df_brand[c] / 1e6

# Recompute brand-level S+P and Cobert (not stored in parquet, computed on the fly in app)
print("\n=== Brand totals ($M) ===")
propias = ['Lhotse', 'Simplit', 'Levo', 'Xroad', 'Dynamo Tools', 'Bandú', 'T-Care', 'UMA']
for _, r in df_brand[df_brand['marca'].isin(propias)].iterrows():
    print(f"\n  {r['marca']}")
    print(f"    Stock Hoy:  {r['stock_hoy_cst']:.1f}M")
    for mes in ['2026-08', '2026-09', '2026-10']:
        lleg = r[f'{mes}_llegadas']
        vta  = r[f'{mes}_venta']
        print(f"    {mes}: Leg={lleg:.1f}M  Vta={vta:.1f}M")

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
df_brand.to_parquet(str(OUT_PATH), index=False)
print(f"\n✅ Saved {len(df_brand)} marcas → {OUT_PATH}")
