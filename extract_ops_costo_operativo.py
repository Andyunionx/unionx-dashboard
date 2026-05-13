#!/usr/bin/env python3
"""
Extractor Costo Operativo — Sheet de Andrés en Drive.

Descarga el Sheet "OPERACIONES 2025-2026" (formato largo, multi-dimensional)
con presupuesto y forecast de costos OPERACIONALES (filtrado solo a las áreas
de Operaciones — Logística, Postventa, SAC, etc.).

Sheet ID: 1WXoQYwDwYVXGBIacAUgTpzb-aYXm2BXgXA0_EucKo7M
Compartido con: union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com

Estructura idéntica al Sheet de Control de Gestión Finanzas pero filtrado:
  AÑO · MES · LINEA NEGOCIO · CANAL · TIPO COSTO · CENTRO COSTOS · ÁREA ·
  SUB-ÁREA · CUENTA ANALÍTICA · TOTAL · TIPO (PPTO_x / FCST_x)

Output:
  - data/operaciones/costo_operativo.parquet
  - data/operaciones/costo_operativo_resumen.json

Cron: parte de sync_kpis_wms.yml (refresca con KPIs operacionales).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
SHEET_ID = "1WXoQYwDwYVXGBIacAUgTpzb-aYXm2BXgXA0_EucKo7M"
CREDENTIALS = PROJECT_ROOT / "credentials.json"

OUT_DIR = PROJECT_ROOT / "data" / "operaciones"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PARQUET = OUT_DIR / "costo_operativo.parquet"
OUT_RESUMEN = OUT_DIR / "costo_operativo_resumen.json"


MES_TO_NUM = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}


def _conectar_sheets():
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(str(CREDENTIALS), scopes=scopes)
    return gspread.authorize(creds)


def _parse_clp(s):
    """Parser CLP chileno robusto.

    Formatos aceptados:
      - "1.234.567"     → 1,234,567 (punto = miles)
      - "1.234,56"      → 1,234.56  (punto miles + coma decimal)
      - "1234,56"       → 1234.56   (coma decimal)
      - "1234567"       → 1,234,567 (sin formato)
      - "-1.541"        → -1,541    (punto = miles, NO decimal)

    Heurística clave: si solo hay PUNTOS (sin coma) y el último grupo
    tiene 3 dígitos, son separadores de miles. Si tiene 1 o 2 dígitos
    DESPUÉS del punto, podría ser decimal — pero en CLP es muy raro,
    así que asumimos miles excepto cuando hay coma explícita.
    """
    if s is None or s == "" or pd.isna(s):
        return 0.0
    t = str(s).strip().replace("$", "").replace(" ", "").replace("\xa0", "")
    if not t:
        return 0.0
    if "," in t and "." in t:
        # Formato 1.234,56 → punto miles + coma decimal
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        # Solo coma → es decimal
        t = t.replace(",", ".")
    elif "." in t:
        # Solo punto → es separador de miles (CLP raramente usa decimal sin coma)
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return 0.0


def _normalizar_tipo(t: str) -> tuple[str, str]:
    if not t:
        return "", ""
    s = str(t).upper().strip()
    escenario = "PPTO" if s.startswith("PPTO") else ("FCST" if s.startswith("FCST") else "")
    if "VENTA" in s or "INGRESO" in s:
        kpi = "VENTA"
    elif "COSTO" in s:
        kpi = "COSTO"
    elif "GASTO" in s:
        kpi = "GASTO"
    elif "CONTRIB" in s:
        kpi = "CONTRIB"
    else:
        kpi = ""
    return escenario, kpi


def main():
    print(f"=== Extract Costo Operativo Sheet — {datetime.now().isoformat()} ===\n",
          flush=True)

    if not CREDENTIALS.exists():
        print(f"[ERROR] Falta credentials.json en {PROJECT_ROOT}", flush=True)
        return 1

    print(f"[1] Conectando Drive Sheets...", flush=True)
    gc = _conectar_sheets()
    sh = gc.open_by_key(SHEET_ID)
    print(f"    Sheet: {sh.title}", flush=True)
    ws = sh.sheet1
    raw = ws.get_all_values()
    print(f"    {len(raw)} filas raw", flush=True)

    df = pd.DataFrame(raw[1:], columns=raw[0])
    df.columns = [c.strip() for c in df.columns]
    df = df[df.iloc[:, 0].astype(str).str.strip() != ""].copy()
    print(f"    {len(df):,} filas con datos", flush=True)

    rename = {
        "AÑO": "year", "MES": "mes_text",
        "LINEA DE NEGOCIO": "linea_negocio", "CANAL": "canal",
        "TIPO DE COSTO": "tipo_costo", "CENTRO DE COSTOS": "centro_costo",
        "AREA EMPRESA": "area", "SUB-AREA": "sub_area",
        "CUENTA ANALITICA": "cuenta_analitica",
        "TOTAL": "valor_raw", "TIPO": "tipo_raw",
    }
    rename_actual = {}
    for col_orig in df.columns:
        c_norm = col_orig.upper().strip()
        for k_target, v_new in rename.items():
            k_clean = k_target.upper().replace("Ñ", "N").replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
            c_clean = c_norm.replace("Ñ", "N").replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
            if k_clean == c_clean:
                rename_actual[col_orig] = v_new
                break
    df = df.rename(columns=rename_actual)

    print(f"\n[2] Normalizando datos...", flush=True)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["mes_text"] = df["mes_text"].astype(str).str.upper().str.strip()
    df["month"] = df["mes_text"].map(MES_TO_NUM).astype("Int64")
    df["valor"] = df["valor_raw"].apply(_parse_clp)
    df[["escenario", "kpi"]] = df["tipo_raw"].apply(
        lambda t: pd.Series(_normalizar_tipo(t))
    )

    for c in ["linea_negocio", "canal", "tipo_costo", "centro_costo",
              "area", "sub_area", "cuenta_analitica"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip().str.upper()
            df[c] = df[c].str.replace(r"\s+", " ", regex=True)

    valid = df["year"].notna() & df["month"].notna() & (df["escenario"] != "")
    df = df[valid].copy()
    print(f"    Filas válidas: {len(df):,}", flush=True)

    df["fecha"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str) + "-01",
        errors="coerce",
    )

    cols_out = ["fecha", "year", "month", "mes_text",
                "linea_negocio", "canal", "tipo_costo",
                "area", "sub_area", "centro_costo", "cuenta_analitica",
                "escenario", "kpi", "valor", "tipo_raw"]
    df_out = df[[c for c in cols_out if c in df.columns]].copy()
    df_out.to_parquet(OUT_PARQUET, index=False)
    print(f"\n[3] Parquet guardado: {OUT_PARQUET.relative_to(PROJECT_ROOT)}", flush=True)

    by_escenario = df.groupby(["escenario", "kpi"])["valor"].sum().to_dict()
    by_area = df.groupby("area")["valor"].sum().to_dict()
    by_canal = df.groupby("canal")["valor"].sum().to_dict()
    by_tipo_costo = df.groupby("tipo_costo")["valor"].sum().to_dict()

    resumen = {
        "generado_en": datetime.now().isoformat(),
        "fuente": f"Drive Sheet {SHEET_ID}",
        "sheet_titulo": sh.title,
        "filas_procesadas": len(df),
        "anios": sorted(df["year"].dropna().unique().astype(int).tolist()),
        "lineas_negocio": sorted(df["linea_negocio"].unique().tolist()),
        "canales": sorted(df["canal"].unique().tolist()),
        "areas": sorted(df["area"].unique().tolist()),
        "centros_costo_count": df["centro_costo"].nunique(),
        "centros_costo_top20": df["centro_costo"].value_counts().head(20).to_dict(),
        "totales_por_escenario_kpi": {
            f"{e}_{k}": round(v, 0) for (e, k), v in by_escenario.items()
        },
        "totales_por_area": {k: round(v, 0) for k, v in by_area.items()},
        "totales_por_canal": {k: round(v, 0) for k, v in by_canal.items()},
        "totales_por_tipo_costo": {k: round(v, 0) for k, v in by_tipo_costo.items()},
    }

    with open(OUT_RESUMEN, "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=str)
    print(f"    Resumen: {OUT_RESUMEN.relative_to(PROJECT_ROOT)}", flush=True)

    print(f"\n=== RESUMEN ===")
    print(f"  Filas procesadas: {len(df):,}")
    print(f"  Años: {resumen['anios']}")
    print(f"  Áreas: {len(resumen['areas'])}")
    print(f"  CCs: {resumen['centros_costo_count']}")
    print(f"  Por escenario/KPI:")
    for k, v in resumen["totales_por_escenario_kpi"].items():
        print(f"    {k}: ${v:,.0f}")
    print(f"\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
