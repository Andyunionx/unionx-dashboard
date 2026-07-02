# -*- coding: utf-8 -*-
"""Integra los movimientos extra (Comisión/Logística/Marketing) de Falabella + Mercado
Libre desde el Sheet "Raw extras" de Nicole al histórico.

REEMPLAZA las filas 'Otros costos' de Falabella+ML 2026 del histórico por las líneas
por SKU+fecha del Sheet (el extract de Odoo las trae MUY subestimadas). Idempotente:
re-correrlo da el mismo resultado. Ver memoria [[raw_extras_com_log_mkt]].

⚠️ Si se re-congela un mes H1 con extract_congelar_mes (re-extrae de Odoo), PISA esta
integración → volver a correr este script.

Uso:  python integrar_extras_nicole.py
Requiere: credentials.json (service account con acceso al Sheet).
"""
import re
import shutil
from pathlib import Path

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

from extract_mes_actual_a_parquet import RAW_TO_DB

ROOT = Path(__file__).resolve().parent
HIST = ROOT / "data" / "historico" / "ventas_historico.parquet"
SHEET_ID = "1CvfW5x0-QWEuPIiJzg7wHJUTH50HuCUtE5fL8ADN-HQ"   # "Raw extras" (Nicole)
CANALES = ("Falabella", "Mercado Libre")
DIAS = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
NUM_COLS = ["cantidad", "venta_bruta", "costo_unitario", "costo_total", "margen_front",
            "comision_pct", "comision", "logistica", "marketing", "margen_final"]


def _num(s):
    s = str(s).strip()
    if not s:
        return 0.0
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _clean_sku(s):
    s = str(s).strip()
    return s.replace(".", "").split(",")[0] if re.fullmatch(r"[\d.,]+", s) else s


def _fix_fecha(s):
    s = str(s).strip()[:10]
    p = s.split("-")
    if len(p) == 3 and len(p[2]) == 4 and p[0].isdigit() and p[1].isdigit():
        return f"{p[2]}-{int(p[1]):02d}-{int(p[0]):02d}"   # d-mm-yyyy / dd-mm-yyyy → yyyy-mm-dd
    return s


def cargar_extras():
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly",
              "https://www.googleapis.com/auth/drive.readonly"]
    gc = gspread.authorize(Credentials.from_service_account_file(str(ROOT / "credentials.json"), scopes=scopes))
    vals = gc.open_by_key(SHEET_ID).get_worksheet(0).get_all_values()
    nd = pd.DataFrame(vals[1:], columns=vals[0]).rename(columns=RAW_TO_DB)
    for c in NUM_COLS:
        if c in nd.columns:
            nd[c] = nd[c].map(_num)
    nd["venta_neta"] = 0.0
    nd["sku"] = nd["sku"].map(_clean_sku)
    nd["fecha_venta"] = nd["fecha_venta"].map(_fix_fecha)
    if "fecha_documento" in nd.columns:
        nd["fecha_documento"] = nd["fecha_documento"].map(_fix_fecha)
    fv = pd.to_datetime(nd["fecha_venta"], errors="coerce")
    nd["anio_venta"] = fv.dt.year.fillna(0).astype("int64")
    nd["mes_venta"] = fv.dt.month.fillna(0).astype("int64")
    nd["semana_venta"] = fv.dt.isocalendar().week.fillna(0).astype("int64")
    nd["dia_semana"] = fv.dt.dayofweek.map(DIAS).fillna("")
    nd["hora_venta_num"] = 0
    nd["tipo_movimiento"] = "Otros costos"
    nd = nd[nd["canal"].isin(CANALES) & (nd["anio_venta"] == 2026) & nd["mes_venta"].between(1, 6)].copy()
    return nd


def main():
    nd = cargar_extras()
    print(f"[1] Nicole (Fala+ML, H1-2026): {len(nd):,} filas | "
          f"com ${nd['comision'].sum()/1e6:.1f}M log ${nd['logistica'].sum()/1e6:.1f}M mkt ${nd['marketing'].sum()/1e6:.1f}M")

    h = pd.read_parquet(HIST)
    cat_cols = [c for c in h.columns if str(h[c].dtype) == "category"]
    for c in cat_cols:
        h[c] = h[c].astype(object)
    for c in h.columns:
        if c not in nd.columns:
            nd[c] = False if c == "es_despacho" else (0 if pd.api.types.is_numeric_dtype(h[c].dtype) else "")
    nd = nd[h.columns.tolist()]
    for c in h.columns:
        if pd.api.types.is_numeric_dtype(h[c].dtype):
            nd[c] = pd.to_numeric(nd[c], errors="coerce").fillna(0).astype(h[c].dtype)
        elif h[c].dtype == bool:
            nd[c] = nd[c].astype(bool)
        else:
            nd[c] = nd[c].astype(str).replace("nan", "")

    fvh = h["fecha_venta"].astype(str)
    rm = (h["tipo_movimiento"] == "Otros costos") & h["canal"].isin(CANALES) & (fvh.str[:4] == "2026")
    print(f"[2] Quitando {int(rm.sum()):,} filas Otros costos Fala+ML 2026 (extract viejo)")
    h_new = pd.concat([h[~rm], nd], ignore_index=True)
    for c in cat_cols:
        h_new[c] = h_new[c].astype("category")

    assert set(h_new.columns) == set(h.columns), "columnas cambiaron"
    shutil.copy2(str(HIST), str(HIST) + ".bak_preextras")
    h_new.to_parquet(HIST, index=False, compression="zstd")
    print(f"[3] Guardado ({len(h_new):,} filas). Backup .bak_preextras")


if __name__ == "__main__":
    main()
