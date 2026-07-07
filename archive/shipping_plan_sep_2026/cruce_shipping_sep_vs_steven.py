"""Cruce: UnionX 'Shipping Plan September V.02' (Detail_SZ + Detail_NB) vs
Steven 'Shipping Plan B-Jun.30th' (SHENZHEN + NINGBO).

Por cada SKU que UnionX quiere cargar en septiembre, identifica:
  - Si Steven lo tiene en su plan B
  - En qué embarque (sección)
  - Cuántas unidades carga Steven vs UnionX

Embarques esperados en Steven B:
  - SZ-04, 40HQ
  - SZ-03-08, 40HQ
  - SZ-01 (623)
  - SZ-02 (623)
  - IMP OP 350-26 40HQ
  - NB-01
"""
import pandas as pd, sys, re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

UX = "data/planillas/Shipping Plan September V.02.xlsx"
SV = "data/comex/Shipping Plan B-Jun.30th.xls"
OUT = "data/comex/Cruce_Shipping_Sep_vs_StevenB.xlsx"


def parsear_steven(sheet):
    """Devuelve lista de items con su embarque/sección asignada."""
    df = pd.read_excel(SV, sheet_name=sheet, header=None)
    items = []
    seccion_actual = None
    header_cols = None
    for i, row in df.iterrows():
        vals = [v for v in row.values if pd.notna(v)]
        if not vals: continue
        first = str(vals[0]).strip()

        # Detectar separador de sección: "1.SZ-04,40HQ", "2.SZ-03-08,40HQ", etc.
        m = re.match(r'^\d+\.(.+)$', first)
        if m and len(vals) <= 2:
            seccion_actual = m.group(1).strip()
            continue

        # Detectar header
        if first == 'No' and 'Model' in str(vals[1] if len(vals)>1 else ''):
            header_cols = [str(v).strip() for v in row.values]
            continue

        # Detectar fila de data (No es un número)
        try:
            no = int(first)
        except:
            continue

        if header_cols is None or seccion_actual is None: continue

        item = {}
        for j, col in enumerate(header_cols):
            if j < len(row.values):
                item[col] = row.values[j]
        item['__seccion'] = seccion_actual
        items.append(item)
    return items


print("Parseando Steven Plan B...")
steven_sz = parsear_steven('SHENZHEN')
steven_nb = parsear_steven('NINGBO')
print(f"  SHENZHEN: {len(steven_sz)} items en secciones: {sorted(set(i['__seccion'] for i in steven_sz))}")
print(f"  NINGBO:   {len(steven_nb)} items en secciones: {sorted(set(i['__seccion'] for i in steven_nb))}")

# Unir y normalizar SKU
def normalizar_sku(v):
    s = str(v).strip() if pd.notna(v) else ''
    return s

steven_todos = []
for it in steven_sz + steven_nb:
    sku = normalizar_sku(it.get('SKU'))
    qty = pd.to_numeric(it.get('Qty'), errors='coerce')
    model = normalizar_sku(it.get('Model'))
    desc = str(it.get('DESCRIPTON', '') or '').strip()[:50]
    steven_todos.append({
        'embarque_steven': it['__seccion'],
        'sku': sku,
        'model': model,
        'desc': desc,
        'qty_steven': qty if pd.notna(qty) else 0,
    })

# UnionX V02
print("\nParseando UnionX V02...")
ux_sz = pd.read_excel(UX, sheet_name='Detail_SZ')
ux_nb = pd.read_excel(UX, sheet_name='Detail_NB')
ux = pd.concat([ux_sz, ux_nb], ignore_index=True)
ux['SKU'] = ux['SKU'].astype(str).str.strip()
print(f"  Detail_SZ: {len(ux_sz)} filas")
print(f"  Detail_NB: {len(ux_nb)} filas")
print(f"  Total UnionX: {len(ux)} SKUs")

# === CRUCE
print("\n" + "="*120)
print("CRUCE — UnionX V02 vs Steven Plan B Jun 30th")
print("="*120)

rows = []
for _, r in ux.iterrows():
    sku_ux = str(r['SKU']).strip()
    units_ux = pd.to_numeric(r['Units'], errors='coerce') or 0
    # Buscar SKU en Steven (por SKU exacto)
    matches = [s for s in steven_todos if s['sku'] == sku_ux]

    if matches:
        for m in matches:
            rows.append({
                'Contenedor UnionX': r['Container'],
                'CRD UnionX': r.get('CRD'),
                'ETA UnionX': r.get('ETA'),
                'Brand': r.get('Brand'),
                'SKU': sku_ux,
                'Descripción': str(r['Description'])[:50] if pd.notna(r['Description']) else '',
                'Units UnionX': units_ux,
                'Embarque Steven': m['embarque_steven'],
                'Model Steven': m['model'],
                'Qty Steven': m['qty_steven'],
                'Diferencia': m['qty_steven'] - units_ux,
                'Estado': 'OK' if abs(m['qty_steven'] - units_ux) < 1 else ('SOBRA' if m['qty_steven'] > units_ux else 'FALTA'),
            })
    else:
        rows.append({
            'Contenedor UnionX': r['Container'],
            'CRD UnionX': r.get('CRD'),
            'ETA UnionX': r.get('ETA'),
            'Brand': r.get('Brand'),
            'SKU': sku_ux,
            'Descripción': str(r['Description'])[:50] if pd.notna(r['Description']) else '',
            'Units UnionX': units_ux,
            'Embarque Steven': '(no encontrado)',
            'Model Steven': '',
            'Qty Steven': 0,
            'Diferencia': -units_ux,
            'Estado': '❌ NO EN STEVEN',
        })

# DataFrame resultado
res = pd.DataFrame(rows)
print(f"\nTotal filas de cruce: {len(res)}")
print()
print(res.to_string(index=False))

# === Resumen por embarque Steven
print("\n" + "="*100)
print("RESUMEN: ¿Dónde están cargando los SKUs UnionX?")
print("="*100)
g = res.groupby('Embarque Steven').agg(
    skus=('SKU','count'),
    unidades_steven=('Qty Steven','sum'),
    unidades_unionx=('Units UnionX','sum'),
).reset_index()
print(g.to_string(index=False))

# === SKUs UnionX no encontrados en Steven
print("\n" + "="*100)
print("SKUs UnionX que NO están en Steven Plan B")
print("="*100)
no_match = res[res['Embarque Steven'] == '(no encontrado)']
print(f"Total: {len(no_match)} SKUs ({no_match['Units UnionX'].sum():,.0f} unidades)")
print(no_match[['Contenedor UnionX', 'SKU', 'Brand', 'Descripción', 'Units UnionX']].to_string(index=False))

# === Exportar Excel
res.to_excel(OUT, index=False, sheet_name='Cruce')
print(f"\n[OK] Excel: {OUT}")
