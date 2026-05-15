#!/usr/bin/env python3
"""
Extractor del Sheet KAM "Análisis de Contribución" hoja "Análisis de Resultados".

Genera `data/finanzas/contribucion_kam.parquet` con la data oficial KAM:
  AÑO · Negocio · Canal · KAM · Mes · Trimestre · Venta · Costo Venta ·
  Margen Directo · Comisiones · Contribución (calculada)

Sheet ID: 1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4
Compartido con: union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com

Uso:
  python extract_kam_contribucion.py

El parquet generado se commitea al repo. La app Finanzas lo lee como
fallback si no tiene credentials para el Sheet en vivo (ver
views/_ops_contrib_helper.py:cargar_contribucion_kam).

Cron: agregar a sync_finanzas.yml o sync_ops.yml para mantener actualizado.
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
SHEET_ID = "1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4"
HOJA = "Análisis de Resultados"
CREDENTIALS = PROJECT_ROOT / "credentials.json"

OUT_DIR = PROJECT_ROOT / "data" / "finanzas"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PARQUET = OUT_DIR / "contribucion_kam.parquet"


def _parse_num(val):
    """Parser CLP chileno robusto."""
    if val is None or val == "" or pd.isna(val):
        return 0
    t = str(val).strip().replace("$", "").replace(" ", "").replace("\xa0", "")
    if not t:
        return 0
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    elif "." in t:
        t = t.replace(".", "")  # punto = miles en CLP
    try:
        return float(t)
    except ValueError:
        return 0


def _conectar():
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(str(CREDENTIALS), scopes=scopes)
    return gspread.authorize(creds)


def main():
    print(f"=== Extract KAM Contribución — {datetime.now().isoformat()} ===\n",
          flush=True)

    if not CREDENTIALS.exists():
        print(f"[ERROR] Falta credentials.json en {PROJECT_ROOT}", flush=True)
        return 1

    print(f"[1] Conectando Drive Sheets...", flush=True)
    gc = _conectar()
    sh = gc.open_by_key(SHEET_ID)
    print(f"    Sheet: {sh.title}", flush=True)

    print(f"[2] Leyendo hoja '{HOJA}'...", flush=True)
    ws = sh.worksheet(HOJA)
    raw = ws.get_all_values()
    print(f"    {len(raw)} filas raw", flush=True)
    if not raw:
        print("[ERROR] Hoja vacía", flush=True)
        return 1

    # Deduplicar headers
    seen = {}
    headers = []
    for h in raw[0]:
        if h in seen:
            seen[h] += 1
            headers.append(f"{h}_dup{seen[h]}")
        else:
            seen[h] = 0
            headers.append(h)

    df = pd.DataFrame(raw[1:], columns=headers)
    df = df.dropna(how="all").reset_index(drop=True)
    print(f"    {len(df):,} filas con datos", flush=True)
    print(f"    Cols: {list(df.columns)[:12]}", flush=True)

    # Normalizar columnas dimensión
    rename_map = {}
    for col in df.columns:
        if col.upper().startswith(("AÑO", "ANO", "AO")):
            rename_map[col] = "year"
        elif col == "Mes":
            rename_map[col] = "month"
        elif col == "Canal":
            rename_map[col] = "canal"
        elif col == "Negocio":
            rename_map[col] = "tipo_negocio"
        elif col == "KAM":
            rename_map[col] = "kam"
        elif col == "Trimestre":
            rename_map[col] = "trimestre"
    df = df.rename(columns=rename_map)

    # Cols numéricas (con tolerancia a encoding)
    cols_num = [
        "Venta KAM", "NC Aportes", "Venta REAL KAM", "Costo Venta KAM",
        "Margen Directo KAM", "Comisión Venta KAM", "Comisión Envío KAM",
        "Marketing KAM", "Total Comisiones KAM",
    ]

    def _norm(s):
        return (s.upper().replace("Ñ", "N").replace("Á", "A")
                  .replace("É", "E").replace("Í", "I")
                  .replace("Ó", "O").replace("Ú", "U"))

    for c_target in cols_num:
        for c_actual in df.columns:
            if _norm(c_actual) == _norm(c_target):
                df[c_target] = df[c_actual].apply(_parse_num)
                break
        else:
            df[c_target] = 0

    # Calcular contribución
    df["resultado_contrib"] = (
        df["Margen Directo KAM"] - df["Total Comisiones KAM"]
    )

    # Tipos
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")

    df = df.dropna(subset=["year", "month"]).copy()
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)

    # Limpiar columnas dimensión (strip + UPPER)
    for c in ["canal", "tipo_negocio", "kam", "trimestre"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    # Quedarnos con cols útiles
    cols_keep = ["year", "month"] + \
        [c for c in ["trimestre", "canal", "kam", "tipo_negocio"] if c in df.columns] + \
        cols_num + ["resultado_contrib"]
    df_out = df[cols_keep].copy()

    print(f"\n[3] Guardando parquet...", flush=True)
    df_out.to_parquet(OUT_PARQUET, index=False)
    print(f"    {OUT_PARQUET.relative_to(PROJECT_ROOT)} "
          f"({OUT_PARQUET.stat().st_size:,} bytes)", flush=True)

    print(f"\n=== RESUMEN ===")
    print(f"  Filas: {len(df_out):,}")
    print(f"  Años: {sorted(df_out['year'].unique().tolist())}")
    if "canal" in df_out.columns:
        print(f"  Canales: {df_out['canal'].nunique()}")
    if "kam" in df_out.columns:
        print(f"  KAMs: {df_out['kam'].nunique()}")
    if "tipo_negocio" in df_out.columns:
        print(f"  Líneas Negocio: {sorted(df_out['tipo_negocio'].unique().tolist())}")
    print(f"\n  Contribución total: ${df_out['resultado_contrib'].sum():,.0f}")
    print(f"  Venta REAL total:    ${df_out['Venta REAL KAM'].sum():,.0f}")
    print(f"\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
