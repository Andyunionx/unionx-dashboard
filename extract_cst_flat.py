"""
Extrae datos de cobertura por marca desde la hoja 'CST x Marca'.
Fuente: analisis_planificacion_JUL26 v2 subida.xlsx
Guarda planif_cst_flat_snapshot.parquet para la tab Coberturas.

Uso: python extract_cst_flat.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import openpyxl
import pandas as pd
from pathlib import Path

EXCEL_PATH = Path(r"C:\Users\felip\Desktop\UNIONX\FORECAST FINAL SKU\Analisis Planificacion\analisis_planificacion_JUL26 v2 subida.xlsx")
SHEET_NAME = "CST x Marca"
OUT_PATH   = Path(__file__).parent / "data" / "planificacion" / "snapshots" / "planif_cst_flat_snapshot.parquet"

# Columnas 0-based en "CST x Marca":
# [0]=Marca  [1]=StockHoyCSTraw  [2]=CobertACT
# AGO26: [3]=StkIni  [4]=Llegadas  [5]=S+P  [6]=Venta  [7]=Cobert
# SEP26: [8]=StkIni  [9]=Llegadas [10]=S+P [11]=Venta [12]=Cobert
# OCT26:[13]=StkIni [14]=Llegadas [15]=S+P [16]=Venta [17]=Cobert

MONTHS = {
    '2026-08': {'stk_ini': 3,  'llegadas': 4,  'venta': 6},
    '2026-09': {'stk_ini': 8,  'llegadas': 9,  'venta': 11},
    '2026-10': {'stk_ini': 13, 'llegadas': 14, 'venta': 16},
}

# Filas a ignorar (no son marcas individuales)
SKIP = {'TOTAL PROPIA', 'PROV. NACIONALES', 'TOTAL EMPRESA'}

_MARCA_NORM = {
    'Dynamo': 'Dynamo Tools',
    'Dynamo TL': 'Dynamo Tools',
    'Dinamo Tools': 'Dynamo Tools',
    'Dynamo Tools': 'Dynamo Tools',
    'Bandú': 'Bandú',
    'Bandu': 'Bandú',
}

print(f"Leyendo {EXCEL_PATH.name} ...")
wb = openpyxl.load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
ws = wb[SHEET_NAME]
all_rows = list(ws.iter_rows(values_only=True))
print(f"  {len(all_rows)} filas leídas")

records = []
for r in all_rows:
    marca_raw = r[0]
    if not marca_raw or not isinstance(marca_raw, str):
        continue
    marca_raw = marca_raw.strip()
    if marca_raw in SKIP or 'REPORTE' in marca_raw or 'Valores' in marca_raw:
        continue
    # Saltear fila de encabezados
    if marca_raw == 'Marca':
        continue

    marca = _MARCA_NORM.get(marca_raw, marca_raw)
    stk_hoy = float(r[1] or 0)

    cobert_act = float(r[2] or 0)
    row = {'marca': marca, 'stock_hoy_cst': stk_hoy / 1e6, 'cobert_act': cobert_act}
    for mes, cols in MONTHS.items():
        row[f'{mes}_stk_ini']  = float(r[cols['stk_ini']]  or 0) / 1e6
        row[f'{mes}_llegadas'] = float(r[cols['llegadas']] or 0) / 1e6
        row[f'{mes}_venta']    = float(r[cols['venta']]    or 0) / 1e6
    records.append(row)

df = pd.DataFrame(records)
print(f"\n=== Marcas encontradas ({len(df)}): {list(df['marca'])} ===")

print("\n=== Verificación vs Excel ($M) ===")
for _, r in df.iterrows():
    print(f"\n  {r['marca']}")
    print(f"    Stock Hoy: {r['stock_hoy_cst']:.1f}M")
    for mes in ['2026-08', '2026-09', '2026-10']:
        print(f"    {mes}: StkIni={r[f'{mes}_stk_ini']:.1f}M  Leg={r[f'{mes}_llegadas']:.1f}M  Vta={r[f'{mes}_venta']:.1f}M")

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(str(OUT_PATH), index=False)
print(f"\n✅ Guardado {len(df)} marcas → {OUT_PATH}")
