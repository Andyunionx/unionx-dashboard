"""
Helper para leer Margen de Contribución desde el Sheet "Análisis de
Contribución" hoja "Análisis de Resultados" (data oficial KAM).

Reemplaza el cálculo aproximado del parquet ventas_historico (margen_final)
por el cálculo real del KAM con sus comisiones reales por canal.

Estructura del Sheet:
  AÑO · Negocio · Canal · KAM · Mes · Trimestre · Venta KAM · NC Aportes ·
  Venta REAL KAM · Costo Venta KAM · Margen Directo KAM ·
  Comisión Venta KAM · Comisión Envío KAM · Marketing KAM ·
  Total Comisiones KAM · Resultado Contribución KAM

Cache: 30 min.
"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHEET_ID_CONTRIB = "1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4"


def _gspread_client():
    import gspread
    if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        return gspread.service_account_from_dict(creds_dict)
    cred_path = PROJECT_ROOT / "credentials.json"
    if cred_path.exists():
        return gspread.service_account(filename=str(cred_path))
    raise FileNotFoundError("No hay credentials para Sheets")


def _parse_num(val):
    """Parser chileno: '1.234.567' → 1234567 · '1.234,56' → 1234.56"""
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


# Estado de la última carga (para diagnóstico en la UI)
_LAST_LOAD_STATUS = {"ok": False, "error": None, "n_filas": 0,
                      "anios": [], "meses_por_anio": {}, "canales": [],
                      "kams": [], "tipos_negocio": []}


def estado_ultima_carga() -> dict:
    """Devuelve el estado de la última carga del Sheet KAM (para debug en la UI)."""
    return dict(_LAST_LOAD_STATUS)


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_contribucion_kam() -> pd.DataFrame:
    """Lee la hoja 'Análisis de Resultados' y devuelve DataFrame con
    columnas numéricas parseadas."""
    try:
        gc = _gspread_client()
        sh = gc.open_by_key(SHEET_ID_CONTRIB)
        ws = sh.worksheet("Análisis de Resultados")
        raw = ws.get_all_values()
        if not raw:
            _LAST_LOAD_STATUS.update({
                "ok": False,
                "error": "El Sheet existe pero está vacío (sin filas)."})
            return pd.DataFrame()

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

        # Normalizar columnas con posibles variantes de encoding
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

        # Cols numéricas
        cols_num = [
            "Venta KAM", "NC Aportes", "Venta REAL KAM", "Costo Venta KAM",
            "Margen Directo KAM", "Comisión Venta KAM", "Comisión Envío KAM",
            "Marketing KAM", "Total Comisiones KAM",
        ]
        # Buscar tolerante a encoding
        for c_target in cols_num:
            for c_actual in df.columns:
                # Comparación tolerante: ignora ñ/Ñ/acentos
                def _norm(s):
                    return (s.upper().replace("Ñ", "N").replace("Á", "A")
                              .replace("É", "E").replace("Í", "I")
                              .replace("Ó", "O").replace("Ú", "U"))
                if _norm(c_actual) == _norm(c_target):
                    df[c_target] = df[c_actual].apply(_parse_num)
                    break
            else:
                df[c_target] = 0

        # Calcular Resultado Contribución (no viene siempre)
        df["resultado_contrib"] = (
            df["Margen Directo KAM"] - df["Total Comisiones KAM"]
        )

        # Asegurar tipos
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
        df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")

        # Filtrar válidas
        df = df.dropna(subset=["year", "month"]).copy()
        df["year"] = df["year"].astype(int)
        df["month"] = df["month"].astype(int)

        # Guardar diagnóstico
        _LAST_LOAD_STATUS.update({
            "ok": True, "error": None, "n_filas": len(df),
            "anios": sorted(df["year"].unique().tolist()),
            "meses_por_anio": {
                int(y): sorted(df[df["year"] == y]["month"].unique().tolist())
                for y in df["year"].unique()
            },
            "canales": sorted(df["canal"].dropna().unique().tolist())
                       if "canal" in df.columns else [],
            "kams": sorted(df["kam"].dropna().unique().tolist())
                    if "kam" in df.columns else [],
            "tipos_negocio": sorted(df["tipo_negocio"].dropna().unique().tolist())
                              if "tipo_negocio" in df.columns else [],
        })

        return df
    except Exception as e:
        _LAST_LOAD_STATUS.update({
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        })
        return pd.DataFrame()


def contribucion_periodo(year: int, meses: list[int] | None = None,
                          canal: str | None = None,
                          tipo_negocio: str | None = None) -> dict:
    """Devuelve dict con totales del período seleccionado.

    Returns:
      {
        "venta_real_clp": float,
        "venta_real_m": float (M CLP),
        "costo_venta_clp": float,
        "margen_directo_clp": float,
        "comisiones_clp": float,
        "contribucion_clp": float,
        "contribucion_m": float (M CLP),
        "mc_pct": float (% margen contribución / venta),
        "n_filas": int,
      }
    """
    df = cargar_contribucion_kam()
    if df.empty:
        return {"error": "Sin datos contribución"}

    f = df[df["year"] == year].copy()
    if meses:
        f = f[f["month"].isin(meses)]
    if canal:
        f = f[f["canal"].str.contains(canal, case=False, na=False)]
    if tipo_negocio:
        f = f[f["tipo_negocio"].str.contains(tipo_negocio, case=False, na=False)]

    if f.empty:
        return {"error": "Sin datos en el período"}

    venta = float(f["Venta REAL KAM"].sum())
    costo = float(f["Costo Venta KAM"].sum())
    margen_dir = float(f["Margen Directo KAM"].sum())
    comisiones = float(f["Total Comisiones KAM"].sum())
    contrib = float(f["resultado_contrib"].sum())
    mc_pct = (contrib / venta * 100) if venta else 0

    return {
        "venta_real_clp": venta,
        "venta_real_m": venta / 1000,
        "costo_venta_clp": costo,
        "margen_directo_clp": margen_dir,
        "margen_directo_m": margen_dir / 1000,
        "comisiones_clp": comisiones,
        "contribucion_clp": contrib,
        "contribucion_m": contrib / 1000,
        "mc_pct": mc_pct,
        "n_filas": len(f),
    }


def contribucion_por_canal(year: int, meses: list[int] | None = None) -> pd.DataFrame:
    """Devuelve contribución agregada por canal."""
    df = cargar_contribucion_kam()
    if df.empty:
        return pd.DataFrame()
    f = df[df["year"] == year].copy()
    if meses:
        f = f[f["month"].isin(meses)]
    if f.empty:
        return pd.DataFrame()

    agg = f.groupby("canal", as_index=False).agg(
        venta=("Venta REAL KAM", "sum"),
        costo=("Costo Venta KAM", "sum"),
        margen_dir=("Margen Directo KAM", "sum"),
        comisiones=("Total Comisiones KAM", "sum"),
        contribucion=("resultado_contrib", "sum"),
    )
    agg["mc_pct"] = agg.apply(
        lambda r: (r["contribucion"] / r["venta"] * 100) if r["venta"] else 0,
        axis=1,
    )
    agg = agg.sort_values("venta", ascending=False)
    return agg


# ============================================================
# FUNCIONES MULTI-DIMENSIÓN (filtros + agrupaciones flexibles)
# ============================================================
def _aplicar_filtros(df: pd.DataFrame, year: int | None = None,
                     meses: list[int] | None = None,
                     canales: list[str] | None = None,
                     kams: list[str] | None = None,
                     tipos_negocio: list[str] | None = None,
                     trimestres: list[int] | None = None) -> pd.DataFrame:
    """Aplica filtros multi-dimensión al DataFrame KAM."""
    f = df.copy()
    if year is not None:
        f = f[f["year"] == year]
    if meses:
        f = f[f["month"].isin(meses)]
    if trimestres and "trimestre" in f.columns:
        tr_str = [f"Q{t}" if isinstance(t, int) else str(t) for t in trimestres]
        tr_num = [str(t) for t in trimestres]
        f = f[f["trimestre"].astype(str).isin(tr_str + tr_num)]
    if canales:
        f = f[f["canal"].isin(canales)]
    if kams and "kam" in f.columns:
        f = f[f["kam"].isin(kams)]
    if tipos_negocio and "tipo_negocio" in f.columns:
        f = f[f["tipo_negocio"].isin(tipos_negocio)]
    return f


def contribucion_filtrada(year: int | None = None,
                          meses: list[int] | None = None,
                          canales: list[str] | None = None,
                          kams: list[str] | None = None,
                          tipos_negocio: list[str] | None = None,
                          trimestres: list[int] | None = None,
                          desglose_por: str = "canal") -> pd.DataFrame:
    """Aplica filtros y agrupa por la dimensión `desglose_por`.

    desglose_por: una de {"canal", "kam", "tipo_negocio"}.

    Retorna DataFrame con columnas:
      [<desglose_por>, venta, costo, margen_dir, comisiones, contribucion, mc_pct]
    """
    df = cargar_contribucion_kam()
    if df.empty:
        return pd.DataFrame()

    f = _aplicar_filtros(df, year, meses, canales, kams, tipos_negocio, trimestres)
    if f.empty:
        return pd.DataFrame()

    if desglose_por not in f.columns:
        return pd.DataFrame()

    agg = f.groupby(desglose_por, as_index=False).agg(
        venta=("Venta REAL KAM", "sum"),
        costo=("Costo Venta KAM", "sum"),
        margen_dir=("Margen Directo KAM", "sum"),
        comisiones=("Total Comisiones KAM", "sum"),
        contribucion=("resultado_contrib", "sum"),
    )
    agg["mc_pct"] = agg.apply(
        lambda r: (r["contribucion"] / r["venta"] * 100) if r["venta"] else 0,
        axis=1,
    )
    return agg.sort_values("venta", ascending=False)


def contribucion_total(year: int | None = None,
                       meses: list[int] | None = None,
                       canales: list[str] | None = None,
                       kams: list[str] | None = None,
                       tipos_negocio: list[str] | None = None,
                       trimestres: list[int] | None = None) -> dict:
    """Totales consolidados con filtros aplicados."""
    df = cargar_contribucion_kam()
    if df.empty:
        return {}
    f = _aplicar_filtros(df, year, meses, canales, kams, tipos_negocio, trimestres)
    if f.empty:
        return {}
    venta = float(f["Venta REAL KAM"].sum())
    contrib = float(f["resultado_contrib"].sum())
    return {
        "venta": venta,
        "costo": float(f["Costo Venta KAM"].sum()),
        "margen_dir": float(f["Margen Directo KAM"].sum()),
        "comisiones": float(f["Total Comisiones KAM"].sum()),
        "contribucion": contrib,
        "mc_pct": (contrib / venta * 100) if venta else 0,
        "n_filas": len(f),
    }


def dimensiones_disponibles(year: int | None = None) -> dict:
    """Devuelve listas de valores disponibles para los selectores.

    Returns dict con: anios, meses, trimestres, canales, kams, tipos_negocio.
    """
    df = cargar_contribucion_kam()
    if df.empty:
        return {"canales": [], "kams": [], "tipos_negocio": [],
                "anios": [], "meses": [], "trimestres": []}

    f = df if year is None else df[df["year"] == year]

    return {
        "anios":         sorted(df["year"].unique().tolist()) if "year" in df.columns else [],
        "meses":         sorted(f["month"].unique().tolist()) if "month" in f.columns else [],
        "trimestres":    sorted(f["trimestre"].astype(str).unique().tolist())
                          if "trimestre" in f.columns else [],
        "canales":       sorted(f["canal"].dropna().unique().tolist())
                          if "canal" in f.columns else [],
        "kams":          sorted(f["kam"].dropna().unique().tolist())
                          if "kam" in f.columns else [],
        "tipos_negocio": sorted(f["tipo_negocio"].dropna().unique().tolist())
                          if "tipo_negocio" in f.columns else [],
    }
