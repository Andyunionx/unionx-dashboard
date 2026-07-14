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

# Marca inferible por prefijo de SKU cuando no hay marca en ningún lado ni en la Matriz.
# Solo se aplica a filas con marca vacía (nunca pisa una marca existente).
PREFIJO_MARCA = {"LH": "Lhotse", "DN": "Dinasty"}


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


def heal_marca(df, verbose=True):
    """P1b — rellena marca vacía sin re-extraer: (1) self-heal con la marca conocida
    del mismo SKU (moda), (2) inferencia por prefijo de SKU (PREFIJO_MARCA).
    Nunca pisa una marca ya existente. Solo toca la columna `marca`."""
    log = print if verbose else (lambda *a, **k: None)
    if "marca" not in df.columns or "sku" not in df.columns:
        return df
    marca = df["marca"].astype(str).str.strip()
    marca = marca.mask(marca.str.lower().isin({"none", "nan", "false", "0", "-", "sin marca"}), "")
    sku = df["sku"].astype(str).str.strip()
    sku_valido = sku.ne("") & sku.str.lower().ne("false")
    vacia = marca.eq("") & sku_valido
    n0 = int(vacia.sum())
    if n0 == 0:
        df["marca"] = marca
        log("  [P1b] marca: nada que rellenar")
        return df
    # 1) self-heal — moda de la marca conocida por SKU
    conocida = marca.ne("")
    if conocida.any():
        moda = marca[conocida].groupby(sku[conocida]).agg(
            lambda s: s.mode().iat[0] if len(s.mode()) else s.iloc[0])
        fill = sku.map(moda)
        heal = vacia & fill.notna()
        marca = marca.where(~heal, fill)
        n1 = int(heal.sum())
    else:
        n1 = 0
    # 2) prefijo de SKU (solo lo que sigue vacío)
    resta = marca.eq("") & sku_valido
    pref = sku.str.upper().str[:2].map(PREFIJO_MARCA)
    pmask = resta & pref.notna()
    marca = marca.where(~pmask, pref)
    n2 = int(pmask.sum())
    df["marca"] = marca
    log(f"  [P1b] marca: {n1} filas por SKU + {n2} por prefijo (quedan {n0 - n1 - n2} sin marca)")
    return df


def aplicar_mejoras(df, con_nc_backfill=True, verbose=True):
    """Aplica P1 (atributos por SKU), P5 (es_despacho) y opcional P3 (backfill NC).
    Vectorizado y sin copia para soportar el histórico (~414k filas)."""
    log = print if verbose else (lambda *a, **k: None)

    # P1 — pisar atributos por SKU (merge vectorizado, 1 join en vez de 9 .map)
    try:
        matriz = _cargar_matriz()  # {sku_norm: {pcol: val}}
        mrows = [{"_sk": k, **{p: v for p, v in rec.items()}} for k, rec in matriz.items()]
        mdf = pd.DataFrame(mrows).rename(columns={c: f"_m_{c}" for c in set(MATRIZ_MAP.values())})
        df["_sk"] = df["sku"].astype(str).str.strip().str.lower()
        df = df.merge(mdf, on="_sk", how="left")
        n_match = int(df["_m_producto"].notna().sum()) if "_m_producto" in df.columns else 0
        for pcol in set(MATRIZ_MAP.values()):
            mc = f"_m_{pcol}"
            if mc in df.columns and pcol in df.columns:
                df[pcol] = df[mc].where(df[mc].notna(), df[pcol])
                df[pcol] = df[pcol].astype(str).replace({"None": "", "nan": ""})
        df = df.drop(columns=[c for c in df.columns if c.startswith("_m_")] + ["_sk"])
        log(f"  [P1] atributos pisados desde Matriz ({n_match:,} filas con SKU en Matriz)")
    except Exception as e:
        log(f"  [P1] omitido: {type(e).__name__}: {e}")
        df = df.drop(columns=[c for c in df.columns if c.startswith("_m_") or c == "_sk"], errors="ignore")

    # P1b — self-heal de marca vacía (mismo SKU + prefijo)
    df = heal_marca(df, verbose=verbose)

    # P5 — flag es_despacho (vectorizado, sin concatenar todo)
    pat = "despacho|flete|env[ií]o|shipping"
    marca_l = df["marca"].astype(str).str.lower()
    prod_l = df["producto"].astype(str).str.lower()
    df["es_despacho"] = marca_l.str.contains(pat, regex=True, na=False) | prod_l.str.contains(pat, regex=True, na=False)
    log(f"  [P5] es_despacho: {int(df['es_despacho'].sum()):,} filas")

    # P5c — envíos NO son proveedores nacionales (no tienen proveedor). Se saca el
    # despacho de tipo_compra='Compra' → 'Envío' para que no infle el margen directo
    # de proveedores nacionales en el reporte de rentabilidad (Andrés 14-jul).
    if "tipo_compra" in df.columns:
        env = df["es_despacho"] & df["tipo_compra"].astype(str).str.strip().str.lower().ne("envío")
        n_env = int(env.sum())
        df.loc[env, "tipo_compra"] = "Envío"
        log(f"  [P5c] tipo_compra='Envío' en {n_env:,} filas de despacho (fuera de proveedores nacionales)")

    # P5b — sanity de costo: filas con cruce de campo (cantidad≈venta → costo_total absurdo).
    # Se corrige a cantidad=1 y costo_total=costo_unitario (evita margen −billones).
    try:
        vn = pd.to_numeric(df["venta_neta"], errors="coerce")
        ct = pd.to_numeric(df["costo_total"], errors="coerce")
        cu = pd.to_numeric(df["costo_unitario"], errors="coerce")
        absurd = ct > (10 * vn.abs() + 100000)
        if absurd.any():
            df.loc[absurd, "cantidad"] = 1
            df.loc[absurd, "costo_total"] = cu[absurd]
            df.loc[absurd, "margen_front"] = vn[absurd] - cu[absurd]
            df.loc[absurd, "margen_final"] = vn[absurd] - cu[absurd]
            log(f"  [P5b] {int(absurd.sum())} filas con costo absurdo corregidas (cantidad=1)")
    except Exception as e:
        log(f"  [P5b] omitido: {e}")

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
