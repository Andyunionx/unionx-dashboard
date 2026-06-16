# -*- coding: utf-8 -*-
"""
Overlay de mejoras al RAW (Nicole, 16-jun-2026) aplicables sin re-extraer Odoo.
`aplicar_mejoras(df)` se usa como post-proceso en el extract diario y también como
backfill one-shot vía CLI.

  P1) Pisar producto + atributos por SKU desde 'Matriz productos.xlsx'
      (1 descripción/categoría/marca por SKU, columnas completas).
  P5) Flag `es_despacho` (líneas de envío sin COGS → margen 100% esperado).
  P3) Backfill: en filas Devolución, fecha_venta = fecha de la VENTA ORIGINAL
      (desde cruce Odoo nc_detalle_h1). Para mes_actual el extract ya lo trae bien
      desde ventas_service; el backfill cubre el histórico congelado.

Uso CLI:  python mejoras_raw_overlay.py [--apply] [--parquet <ruta>]
"""
import argparse
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
MATRIZ = ROOT / "data" / "planillas" / "Matriz productos.xlsx"
NC_DET = ROOT / "data" / "contabilidad" / "nc_detalle_h1.parquet"

MATRIZ_MAP = {
    "Producto": "producto", "Categoría macro": "categoria_macro",
    "Categoría padre": "categoria_padre", "Categoría hijo": "categoria_hijo",
    "Categoría comercial": "categoria_comercial", "Marca": "marca",
    "Proveedor": "proveedor", "Pack": "pack", "In/out": "estado_sku",
}
DESPACHO_KEYS = ("despacho", "flete", "envio", "envío", "shipping")


def _norm(s):
    s = str(s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _cargar_matriz():
    import openpyxl
    wb = openpyxl.load_workbook(MATRIZ, read_only=True, data_only=True)
    ws = wb["Productos"] if "Productos" in wb.sheetnames else wb.active
    rows = list(ws.iter_rows(values_only=True))
    idx = {str(h).strip() if h else "": i for i, h in enumerate(rows[0])}
    iSKU = idx.get("SKU")
    m = {}
    for r in rows[1:]:
        if iSKU is None or len(r) <= iSKU or not r[iSKU]:
            continue
        rec = {}
        for mcol, pcol in MATRIZ_MAP.items():
            i = idx.get(mcol)
            if i is not None and i < len(r) and r[i] not in (None, ""):
                rec[pcol] = r[i]
        m[_norm(str(r[iSKU]).strip())] = rec
    return m


def aplicar_mejoras(df, con_nc_backfill=True, verbose=True):
    """Aplica P1 (atributos por SKU), P5 (es_despacho) y opcional P3 (backfill NC)."""
    df = df.copy()
    log = print if verbose else (lambda *a, **k: None)

    # P1 — pisar atributos por SKU
    try:
        matriz = _cargar_matriz()
        sk = df["sku"].apply(_norm)
        for pcol in set(MATRIZ_MAP.values()):
            if pcol not in df.columns:
                continue
            vals = sk.map(lambda s: matriz.get(s, {}).get(pcol))
            mask = vals.notna()
            df.loc[mask, pcol] = vals[mask].values
            df[pcol] = df[pcol].map(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
        log(f"  [P1] atributos pisados desde Matriz ({int(sk.isin(matriz).sum()):,} filas con SKU en Matriz)")
    except Exception as e:
        log(f"  [P1] omitido: {e}")

    # P5 — flag es_despacho
    txt = (df.get("marca", "").astype(str) + " " + df.get("producto", "").astype(str)
           + " " + df.get("sku", "").astype(str)).apply(_norm)
    df["es_despacho"] = txt.apply(lambda t: any(k in t for k in DESPACHO_KEYS))
    log(f"  [P5] es_despacho: {int(df['es_despacho'].sum()):,} filas")

    # P3 — backfill fecha_venta NC desde el cruce Odoo (solo histórico)
    if con_nc_backfill and NC_DET.exists() and "tipo_movimiento" in df.columns:
        nc = pd.read_parquet(NC_DET)
        nc_orig = {}
        for _, r in nc.iterrows():
            fo = str(r.get("Fecha venta original", ""))[:10]
            if len(fo) == 10 and fo[:4].isdigit():
                nc_orig[str(r["NC"]).strip()] = fo
        dev = df["tipo_movimiento"] == "Devolución"
        nueva = df.loc[dev, "documento"].astype(str).str.strip().map(nc_orig)
        mask = dev & nueva.notna()
        if mask.any():
            df.loc[mask, "fecha_venta"] = nueva[nueva.notna()].values
            fv = pd.to_datetime(df.loc[mask, "fecha_venta"], errors="coerce")
            df.loc[mask, "anio_venta"] = fv.dt.year
            df.loc[mask, "mes_venta"] = fv.dt.month
            df.loc[mask, "semana_venta"] = fv.dt.isocalendar().week.astype("Int64")
            df.loc[mask, "dia_semana"] = fv.dt.dayofweek
        log(f"  [P3] backfill fecha NC: {int(mask.sum()):,} filas")

    for c in ("anio_venta", "mes_venta", "semana_venta", "dia_semana"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype("int64")
    return df


def main(apply=False, parquet="data/historico/ventas_historico.parquet"):
    pq = ROOT / parquet
    df = pd.read_parquet(pq)
    print(f"Parquet: {parquet}  ({len(df):,} filas)")
    df = aplicar_mejoras(df)
    out = pq if apply else pq.with_name(pq.stem + "_MEJORADO.parquet")
    df.to_parquet(out, index=False)
    print(f"{'✓ APLICADO' if apply else '→ prueba'}: {out.relative_to(ROOT)}  ({len(df):,} filas, {df.shape[1]} cols)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--parquet", default="data/historico/ventas_historico.parquet")
    a = ap.parse_args()
    main(apply=a.apply, parquet=a.parquet)
