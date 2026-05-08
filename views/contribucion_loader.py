"""
Loader compartido para las vistas de Contribución Comercial.

Lee el Google Sheet "Análisis de Contribución" usando un Service Account.

En Streamlit Cloud: lee credenciales desde st.secrets['gcp_service_account']
En local: lee desde credentials.json en raíz del proyecto

Cache: 5 minutos (igual que el resto del dashboard live).
"""
from pathlib import Path

import pandas as pd
import streamlit as st

# File ID del Google Sheet de Contribución
SHEET_ID = "1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@st.cache_resource(show_spinner=False)
def _gspread_client():
    """Cliente gspread reusable. Cache_resource = singleton durante la sesión."""
    import gspread

    # 1) Streamlit Cloud: secret 'gcp_service_account'
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        return gspread.service_account_from_dict(creds_dict)

    # 2) Local: credentials.json
    cred_path = PROJECT_ROOT / "credentials.json"
    if cred_path.exists():
        return gspread.service_account(filename=str(cred_path))

    raise FileNotFoundError(
        "No hay credenciales para Google Sheets. En Streamlit Cloud setear secret "
        "'gcp_service_account'. En local poner credentials.json en la raíz del proyecto."
    )


@st.cache_data(ttl=3600, show_spinner="Cargando datos de Contribución desde Google Sheets…")
def cargar_hoja(nombre_hoja: str) -> pd.DataFrame:
    """Lee una hoja del Sheet de Contribución y devuelve DataFrame.

    Cache: 1 hora (3600s). Para forzar refresh manual usar el botón
    '🔄 Refrescar' en cada vista (ejecuta st.cache_data.clear()).
    """
    gc = _gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(nombre_hoja)
    raw = ws.get_all_values()
    if not raw:
        return pd.DataFrame()

    # Deduplicar headers (algunas hojas tienen 'NC Aportes' 2 veces)
    raw_headers = raw[0]
    seen = {}
    headers = []
    for h in raw_headers:
        if h in seen:
            seen[h] += 1
            headers.append(f"{h}_dup{seen[h]}")
        else:
            seen[h] = 0
            headers.append(h)

    rows = raw[1:]
    df = pd.DataFrame(rows, columns=headers)
    df = df.dropna(how="all").reset_index(drop=True)
    return df


def parse_numero(val):
    """Convierte string con formato chileno (puntos miles, coma decimal) a float.

    Ejemplos:
      '22.043.655' -> 22043655.0
      '63%' -> 0.63
      '0,0%' -> 0.0
      '4.542.714' -> 4542714.0
    """
    if val is None or val == "":
        return None
    s = str(val).strip()
    if not s:
        return None
    # Detectar porcentaje
    is_pct = s.endswith("%")
    if is_pct:
        s = s[:-1].strip()
    # Quitar puntos de miles + reemplazar coma decimal
    s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
        if is_pct:
            return v / 100
        return v
    except ValueError:
        return None


def parsear_columnas_numericas(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Aplica parse_numero a columnas indicadas."""
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = df[c].apply(parse_numero)
    return df


def fmt_pesos_M(v, decimales=1):
    if v is None or pd.isna(v):
        return "—"
    return f"${v/1e6:,.{decimales}f}M"


def fmt_pesos_K(v, decimales=0):
    if v is None or pd.isna(v):
        return "—"
    return f"${v/1e3:,.{decimales}f}K"


def fmt_pct(v, decimales=1):
    if v is None or pd.isna(v):
        return "—"
    return f"{v*100:+.{decimales}f}%"


def color_cumplimiento(pct):
    """Devuelve color de semáforo según % cumplimiento (1.0 = 100%)."""
    if pct is None or pd.isna(pct):
        return "⚪"
    if pct >= 1.0:
        return "🟢"
    if pct >= 0.85:
        return "🟡"
    return "🔴"
