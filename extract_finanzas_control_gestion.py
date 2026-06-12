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


_LINE_DIMS = ["year", "month", "linea_negocio", "canal", "tipo_costo", "area",
              "sub_area", "centro_costo", "cuenta_analitica"]

# Conceptos de REMUNERACIONES que pueden venir sin persona y SIN decimales de
# forma legítima (no son nómina por empleado), por lo que NO se tratan como
# nómina genérica duplicada.
_REMUN_EXC = ("LEYES", "BONO", "AGUINALDO", "GRATIF", "INDEMN", "HHEE")


def _limpiar_duplicados(df: pd.DataFrame) -> pd.DataFrame:
    """Red de seguridad ante errores de carga en el Sheet P&L.

    La fuente traía basura que inflaba el costo operativo ~80% en varios meses.
    Hay TRES mecanismos de duplicado, todos corregidos acá:

      1) FILAS FCST DUPLICADAS EXACTAS — la misma línea pegada 2+ veces. En un
         libro mayor en formato largo nunca hay dos líneas idénticas legítimas,
         así que se colapsan (afectaba sobre todo a marzo 2026).

      2) NÓMINA GENÉRICA DUPLICADA — en REMUNERACIONES conviven la nómina
         detallada (cada cargo con el NOMBRE de la persona en
         cuenta_analitica_persona) y una segunda nómina genérica (los mismos
         cargos sin persona y montos redondeados) que se suma encima y duplica
         el costo de personal (ej. abril 2026). Regla: SOLO en un (año, mes,
         área) donde existe nómina CON PERSONA, se eliminan las filas
         REMUNERACIONES SIN persona que NO sean leyes/bonos. La señal de persona
         es la única confiable: en meses sin esa columna (ene-mar) NO se toca
         nada, porque ahí un monto redondeado puede ser un cargo legítimo (p.ej.
         marzo trae GERENCIA/JEFATURA/ADMINISTRATIVO sin decimales y SON reales).

      3) FCST = PPTO (presupuesto copiado como forecast) — la pista la dio
         Andrés: una fila FCST duplicada tiene EXACTAMENTE el mismo monto que
         la PPTO de esa línea/mes (presupuesto recargado como real). Regla: se
         elimina la fila FCST cuyo (línea, monto) coincide con una PPTO **solo
         si existe OTRA fila FCST en la misma línea que NO sea igual a PPTO**
         (el real distinto). Así, en meses futuros donde FCST legítimamente ==
         PPTO (sin real aún) NO se borra nada.

    Loguea todo lo que elimina.
    """
    n0 = len(df)
    dims = [c for c in _LINE_DIMS if c in df.columns]

    # ── Paso 1: filas duplicadas exactas ────────────────────────────────
    df = df.drop_duplicates(subset=dims + ["escenario", "kpi", "valor"]).copy()
    n1 = len(df)
    if n0 - n1:
        print(f"    [limpieza] {n0 - n1:,} filas duplicadas exactas eliminadas",
              flush=True)

    # ── Paso 2: nómina genérica duplicada (señal = PERSONA) ──────────────
    if "centro_costo" in df.columns and "cuenta_analitica_persona" in df.columns:
        es_remun = df["centro_costo"] == "REMUNERACIONES"
        con_per = df["cuenta_analitica_persona"].astype(str).str.strip() != ""
        cta = df["cuenta_analitica"].astype(str).str.upper()
        es_exc = cta.apply(lambda c: any(k in c for k in _REMUN_EXC))

        # Grupos (año, mes, área) con nómina por empleado (con persona)
        det_keys = set(map(tuple,
            df[es_remun & con_per][["year", "month", "area"]].dropna().values))
        en_det = pd.Series(
            [(y, m, a) in det_keys for y, m, a in
             zip(df["year"], df["month"], df["area"])], index=df.index)
        # Duplicado = REMUN SIN persona, no-leyes, en grupo que SÍ tiene nómina con persona
        dup_nom = es_remun & ~con_per & ~es_exc & en_det
        # Solo nómina FCST (no tocar PPTO)
        if "escenario" in df.columns:
            dup_nom &= df["escenario"] == "FCST"
        if dup_nom.any():
            quitado = abs(df.loc[dup_nom, "valor"].sum())
            meses = sorted(df.loc[dup_nom, "mes_text"].unique().tolist())
            print(f"    [limpieza] {int(dup_nom.sum()):,} filas de nómina "
                  f"genérica duplicada eliminadas (${quitado * 1000:,.0f} CLP). "
                  f"Meses: {meses}", flush=True)
            df = df[~dup_nom].copy()

    # ── Paso 3: FCST = PPTO con hermano real ─────────────────────────────
    if {"escenario", "kpi"}.issubset(df.columns):
        gasto = df[df["kpi"] == "GASTO"]
        ppto_keys = set(map(tuple,
            gasto[gasto["escenario"] == "PPTO"][dims + ["valor"]]
            .round({"valor": 2}).values))

        fc = gasto[gasto["escenario"] == "FCST"].copy()
        if len(fc):
            fc["_esPPTO"] = [tuple(r) in ppto_keys
                             for r in fc[dims + ["valor"]].round({"valor": 2}).values]
            drop_idx = []
            for _, grp in fc.groupby(dims, dropna=False):
                # Solo si la línea está duplicada Y conviven copia-de-PPTO + real distinto
                if len(grp) > 1 and grp["_esPPTO"].any() and (~grp["_esPPTO"]).any():
                    drop_idx.extend(grp.index[grp["_esPPTO"]].tolist())
            if drop_idx:
                quitado = abs(df.loc[drop_idx, "valor"].sum())
                meses = sorted(df.loc[drop_idx, "mes_text"].unique().tolist())
                print(f"    [limpieza] {len(drop_idx):,} filas FCST=PPTO "
                      f"(presupuesto copiado) eliminadas (${quitado * 1000:,.0f} "
                      f"CLP). Meses: {meses}", flush=True)
                df = df.drop(index=drop_idx).copy()

    return df


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
        # Segunda cuenta analítica = persona/empleado específico del cargo.
        # Agregada al Sheet en mayo 2026, permite atribuir GAV nominalmente
        # (ej: GERENCIA → "BROWNE URZUA ANDRES"). Hoy poblada al 1%.
        "CUENTA ANALITICA1": "cuenta_analitica_persona",
        "TOTAL": "valor_raw",
        "TIPO": "tipo_raw",
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

    # cuenta_analitica_persona: limpiar pero NO uppercase (son nombres propios)
    if "cuenta_analitica_persona" in df.columns:
        df["cuenta_analitica_persona"] = (
            df["cuenta_analitica_persona"].astype(str).str.strip()
        )
        df.loc[df["cuenta_analitica_persona"].isin(["nan", "None", ""]),
                "cuenta_analitica_persona"] = ""

    # Filtrar válidas: tienen año, mes y escenario
    valid = df["year"].notna() & df["month"].notna() & (df["escenario"] != "")
    df = df[valid].copy()
    print(f"    Filas válidas: {len(df):,}", flush=True)

    # Red de seguridad: filas duplicadas exactas + doble nómina (ver docstring)
    print(f"\n[2b] Limpiando duplicados de la fuente...", flush=True)
    df = _limpiar_duplicados(df)
    print(f"    Filas tras limpieza: {len(df):,}", flush=True)

    # Fecha (1er día del mes)
    df["fecha"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str) + "-01",
        errors="coerce",
    )

    # ─── Cobertura de cuenta_analitica_persona (info útil para debug) ───
    if "cuenta_analitica_persona" in df.columns:
        gasto_mask = df["kpi"] == "GASTO"
        con_persona = (df.loc[gasto_mask, "cuenta_analitica_persona"] != "").sum()
        total_gasto = gasto_mask.sum()
        pct = con_persona / total_gasto * 100 if total_gasto else 0
        print(f"\n[CA1 persona] Cobertura GAV/GASTO: "
              f"{con_persona:,}/{total_gasto:,} filas ({pct:.1f}%)", flush=True)

    # ─── Guardar parquet ────────────────────────────────────────────────
    cols_out = ["fecha", "year", "month", "mes_text",
                "linea_negocio", "canal", "tipo_costo",
                "area", "sub_area", "centro_costo",
                "cuenta_analitica", "cuenta_analitica_persona",
                "escenario", "kpi", "valor", "tipo_raw"]
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
