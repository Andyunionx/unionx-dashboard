#!/usr/bin/env python3
"""
Extractor Control de Gestión Presupuestario — Sheet de Andrés en Drive.

Descarga el Sheet "P&L 2025-2026" (formato largo, multi-dimensional) que
contiene:
  - PPTO (Venta / Costo / Gasto / Contribución) por mes
  - FCST (Venta / Costo / Gasto / Contribución) por mes
  - Por LÍNEA DE NEGOCIO × CANAL × CC × ÁREA × SUB-ÁREA × CUENTA ANALÍTICA

Sheet ID: 1NfIL-k00pUbF5ogsVnadP2wMAVc7oUKkOA7UMLOT-j0
Compartido con: union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com

Output:
  - data/finanzas/control_gestion.parquet (formato largo limpio)
  - data/finanzas/control_gestion_resumen.json (KPIs + dimensiones)

Cron: parte de sync_finanzas.yml (post-extract Excel + control gestión cada 6h).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
SHEET_ID = "1NfIL-k00pUbF5ogsVnadP2wMAVc7oUKkOA7UMLOT-j0"
CREDENTIALS = PROJECT_ROOT / "credentials.json"

OUT_DIR = PROJECT_ROOT / "data" / "finanzas"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PARQUET = OUT_DIR / "control_gestion.parquet"
OUT_RESUMEN = OUT_DIR / "control_gestion_resumen.json"


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

    Formatos:
      "1.234.567"  → 1,234,567 (punto = miles)
      "1.234,56"   → 1,234.56  (punto miles + coma decimal)
      "1234,56"    → 1234.56   (coma decimal)
      "-1.541"     → -1541     (punto = miles, NO decimal)
    """
    if s is None or s == "" or pd.isna(s):
        return 0.0
    t = str(s).strip().replace("$", "").replace(" ", "").replace("\xa0", "")
    if not t:
        return 0.0
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    elif "." in t:
        # Solo punto en CLP = separador de miles, NO decimal
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return 0.0


def _normalizar_tipo(t: str) -> tuple[str, str]:
    """('PPTO GASTO' | 'FCST CONTRIB') → (escenario, kpi)
    escenario in {'PPTO', 'FCST'}; kpi in {'VENTA','COSTO','GASTO','CONTRIB'}.
    """
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
    print(f"=== Extract Control de Gestión Sheet — {datetime.now().isoformat()} ===\n",
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

    # DataFrame
    df = pd.DataFrame(raw[1:], columns=raw[0])
    df.columns = [c.strip() for c in df.columns]
    # Filtrar filas vacías
    df = df[df.iloc[:, 0].astype(str).str.strip() != ""].copy()
    print(f"    {len(df):,} filas con datos", flush=True)

    # Renombrar cols a snake_case
    rename = {
        "AÑO": "year",
        "MES": "mes_text",
        "LINEA DE NEGOCIO": "linea_negocio",
        "CANAL": "canal",
        "TIPO DE COSTO": "tipo_costo",
        "CENTRO DE COSTOS": "centro_costo",
        "AREA EMPRESA": "area",
        "SUB-AREA": "sub_area",
        "CUENTA ANALITICA": "cuenta_analitica",
        "TOTAL": "valor_raw",
        "TIPO": "tipo_raw",
        # ─── Cols nuevas para distribución directa del GAV (roadmap 2026-05) ───
        # Todas opcionales. Si no existen en el Sheet, las filas quedan vacías
        # y la lógica de distribución cae al fallback heurístico de "venta".
        "METODO ASIGNACION":      "metodo_asignacion",
        "DESTINO TIPO NEGOCIO":   "destino_tipo_negocio",
        "DESTINO CATEGORIA":      "destino_categoria",
        "PCT ASIGNACION":         "pct_asignacion",
        "DESCRIPCION CARGO":      "descripcion_cargo",
    }
    # Mapear con tolerancia a variantes (encoding mangled, espacios, etc.)
    rename_actual = {}
    for col_orig in df.columns:
        c_norm = col_orig.upper().strip()
        for k_target, v_new in rename.items():
            k_norm = k_target.upper().strip()
            # Comparación tolerante a Ñ/N
            k_clean = k_norm.replace("Ñ", "N").replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
            c_clean = c_norm.replace("Ñ", "N").replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
            if k_clean == c_clean:
                rename_actual[col_orig] = v_new
                break
    df = df.rename(columns=rename_actual)

    print(f"    Columnas finales: {list(df.columns)[:12]}", flush=True)

    # ─── Normalización ──────────────────────────────────────────────────
    print(f"\n[2] Normalizando datos...", flush=True)

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    df["mes_text"] = df["mes_text"].astype(str).str.upper().str.strip()
    df["month"] = df["mes_text"].map(MES_TO_NUM).astype("Int64")

    # Parsear monto chileno
    df["valor"] = df["valor_raw"].apply(_parse_clp)

    # Tipo → escenario + kpi
    df[["escenario", "kpi"]] = df["tipo_raw"].apply(
        lambda t: pd.Series(_normalizar_tipo(t))
    )

    # Limpiar texto: strip, quitar espacios duplicados
    for c in ["linea_negocio", "canal", "tipo_costo", "centro_costo",
              "area", "sub_area", "cuenta_analitica"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip().str.upper()
            df[c] = df[c].str.replace(r"\s+", " ", regex=True)

    # ─── Cols del roadmap GAV directo (mantener case original para destino) ──
    # `metodo_asignacion` se normaliza a lowercase (es un enum).
    # `destino_tipo_negocio` y `destino_categoria` se mantienen tal cual
    # (deben coincidir con los valores del Sheet KAM / Odoo).
    # `pct_asignacion` se mantiene como string JSON crudo.
    # `descripcion_cargo` se mantiene tal cual (texto libre).
    if "metodo_asignacion" in df.columns:
        df["metodo_asignacion"] = (
            df["metodo_asignacion"].astype(str).str.strip().str.lower()
        )
        df.loc[df["metodo_asignacion"].isin(["nan", "none", ""]), "metodo_asignacion"] = ""
    for c in ["destino_tipo_negocio", "destino_categoria",
              "pct_asignacion", "descripcion_cargo"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
            df.loc[df[c].isin(["nan", "None", ""]), c] = ""

    # Filtrar válidas: tienen año, mes y escenario
    valid = df["year"].notna() & df["month"].notna() & (df["escenario"] != "")
    df = df[valid].copy()
    print(f"    Filas válidas: {len(df):,}", flush=True)

    # Fecha (1er día del mes)
    df["fecha"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str) + "-01",
        errors="coerce",
    )

    # ─── Validaciones soft de las cols nuevas del roadmap GAV directo ──────
    # No crashea — solo loguea warnings para que Andrés sepa qué falta llenar.
    metodos_validos = {"directo_canal", "directo_categoria", "mc_absoluto",
                        "equitativo", "venta", ""}
    warnings_gav = []
    if "metodo_asignacion" in df.columns:
        invalidos = df[~df["metodo_asignacion"].isin(metodos_validos)]
        if len(invalidos) > 0:
            ejemplos = invalidos["metodo_asignacion"].value_counts().head(5).to_dict()
            warnings_gav.append(
                f"  ⚠️  {len(invalidos)} filas con metodo_asignacion no reconocido: {ejemplos}"
            )

        # Validar que directo_canal tenga destino_tipo_negocio
        if "destino_tipo_negocio" in df.columns:
            mask = (df["metodo_asignacion"] == "directo_canal") & \
                   (df["destino_tipo_negocio"] == "")
            if mask.any():
                warnings_gav.append(
                    f"  ⚠️  {mask.sum()} filas con metodo=directo_canal pero sin destino_tipo_negocio"
                )

        # Validar que directo_categoria tenga destino_categoria
        if "destino_categoria" in df.columns:
            mask = (df["metodo_asignacion"] == "directo_categoria") & \
                   (df["destino_categoria"] == "")
            if mask.any():
                warnings_gav.append(
                    f"  ⚠️  {mask.sum()} filas con metodo=directo_categoria pero sin destino_categoria"
                )

        # Cobertura: % filas del GAV con método definido
        gasto_mask = df["kpi"] == "GASTO"
        if gasto_mask.any():
            con_metodo = (df.loc[gasto_mask, "metodo_asignacion"] != "").sum()
            total = gasto_mask.sum()
            pct = con_metodo / total * 100 if total else 0
            print(f"\n[GAV directo] Cobertura método: {con_metodo:,}/{total:,} filas ({pct:.0f}%)",
                  flush=True)

    if warnings_gav:
        print(f"\n[GAV directo] Warnings:", flush=True)
        for w in warnings_gav:
            print(w, flush=True)

    # ─── Guardar parquet ────────────────────────────────────────────────
    cols_out = ["fecha", "year", "month", "mes_text",
                "linea_negocio", "canal", "tipo_costo",
                "area", "sub_area", "centro_costo", "cuenta_analitica",
                "escenario", "kpi", "valor", "tipo_raw",
                # Cols nuevas del roadmap GAV directo
                "metodo_asignacion", "destino_tipo_negocio", "destino_categoria",
                "pct_asignacion", "descripcion_cargo"]
    df_out = df[[c for c in cols_out if c in df.columns]].copy()
    df_out.to_parquet(OUT_PARQUET, index=False)
    print(f"\n[3] Parquet guardado: {OUT_PARQUET.relative_to(PROJECT_ROOT)}", flush=True)

    # ─── Resumen ─────────────────────────────────────────────────────────
    by_escenario = df.groupby(["escenario", "kpi"])["valor"].sum().to_dict()
    by_lineanegocio = df.groupby("linea_negocio")["valor"].sum().to_dict()
    by_year = df.groupby("year")["valor"].sum().to_dict()

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
        "totales_por_linea_negocio": {k: round(v, 0) for k, v in by_lineanegocio.items()},
        "totales_por_year": {int(k): round(v, 0) for k, v in by_year.items() if pd.notna(k)},
    }

    with open(OUT_RESUMEN, "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=str)
    print(f"    Resumen: {OUT_RESUMEN.relative_to(PROJECT_ROOT)}", flush=True)

    print(f"\n=== RESUMEN ===")
    print(f"  Filas procesadas: {len(df):,}")
    print(f"  Años: {resumen['anios']}")
    print(f"  Líneas de negocio: {resumen['lineas_negocio']}")
    print(f"  Canales: {len(resumen['canales'])}")
    print(f"  Áreas: {len(resumen['areas'])}")
    print(f"  Centros de costo: {resumen['centros_costo_count']}")
    print(f"  Por escenario/KPI:")
    for k, v in resumen["totales_por_escenario_kpi"].items():
        print(f"    {k}: ${v:,.0f}")
    print(f"\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
