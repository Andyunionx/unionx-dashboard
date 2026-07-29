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


def fmt_pesos(v):
    """Monto completo formato chileno: $48.155.075 (sin aproximar al millon).
    Pedido por el equipo (Trinidad 15-jun) para revisar el detalle real."""
    if v is None or pd.isna(v):
        return "—"
    return f"${int(round(v)):,.0f}".replace(",", ".")


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


def render_contrib_filters(df: pd.DataFrame, prefix: str = "contrib", *, with_anio=True, with_trim=True,
                           with_mes=True, with_negocio=True, with_canal=True, with_kam=True) -> dict:
    """
    Renderiza barra de filtros al tope (en columnas), devuelve dict con selecciones.

    Aplicar luego con: df_f = aplicar_filtros(df, filtros)
    """
    st.markdown("##### 🔍 Filtros")
    cols = []
    columns_pedidas = []
    if with_anio and 'AÑO' in df.columns:
        columns_pedidas.append('anio')
    if with_trim and 'Trimestre' in df.columns:
        columns_pedidas.append('trim')
    if with_mes and 'Mes' in df.columns:
        columns_pedidas.append('mes')
    if with_negocio and 'Negocio' in df.columns:
        columns_pedidas.append('negocio')
    if with_canal and 'Canal' in df.columns:
        columns_pedidas.append('canal')
    if with_kam and 'KAM' in df.columns:
        columns_pedidas.append('kam')

    if not columns_pedidas:
        return {}

    cols = st.columns(len(columns_pedidas))
    selecciones = {}
    idx = 0

    if 'anio' in columns_pedidas:
        with cols[idx]:
            anios = sorted([str(a).replace('.', '') for a in df['AÑO'].dropna().unique() if a])
            selecciones['anio'] = st.multiselect("Año", anios, default=[], key=f"{prefix}_anio")
        idx += 1

    if 'trim' in columns_pedidas:
        with cols[idx]:
            trims = sorted([t for t in df['Trimestre'].dropna().unique() if t])
            selecciones['trim'] = st.multiselect("Trimestre", trims, default=[], key=f"{prefix}_trim")
        idx += 1

    if 'mes' in columns_pedidas:
        with cols[idx]:
            meses = sorted([m for m in df['Mes'].dropna().unique() if m],
                           key=lambda x: int(str(x).split('.')[0]) if str(x).split('.')[0].isdigit() else 99)
            selecciones['mes'] = st.multiselect("Mes", meses, default=[], key=f"{prefix}_mes")
        idx += 1

    if 'negocio' in columns_pedidas:
        with cols[idx]:
            negs = sorted([n for n in df['Negocio'].dropna().unique() if n])
            selecciones['negocio'] = st.multiselect("Línea Negocio", negs, default=[], key=f"{prefix}_neg")
        idx += 1

    if 'canal' in columns_pedidas:
        with cols[idx]:
            canales = sorted([c for c in df['Canal'].dropna().unique() if c])
            selecciones['canal'] = st.multiselect("Canal", canales, default=[], key=f"{prefix}_canal")
        idx += 1

    if 'kam' in columns_pedidas:
        with cols[idx]:
            kams = sorted([k for k in df['KAM'].dropna().unique() if k])
            selecciones['kam'] = st.multiselect("KAM", kams, default=[], key=f"{prefix}_kam")
        idx += 1

    return selecciones


# Canales NO comerciales — no pertenecen al portafolio de ningún KAM. Se excluyen
# de los análisis por KAM/canal (igual que EXCLUIR_CANAL en la vista Conciliación).
EXCLUIR_CANAL_NO_COMERCIAL = {"eattouch", "postventa", "marketing"}


def _canal_norm(s):
    import unicodedata
    s = str(s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def excluir_no_comerciales(df: pd.DataFrame) -> pd.DataFrame:
    """Saca canales no comerciales (Marketing/Postventa/Eattouch) que en las hojas
    fuente vienen etiquetados a un KAM pero no son parte de su portafolio."""
    if df is None or df.empty or 'Canal' not in df.columns:
        return df
    return df[df['Canal'].map(lambda c: _canal_norm(c) not in EXCLUIR_CANAL_NO_COMERCIAL)]


def aplicar_filtros(df: pd.DataFrame, sel: dict) -> pd.DataFrame:
    """Aplica las selecciones de render_contrib_filters al DataFrame."""
    df_f = df.copy()
    if sel.get('anio'):
        df_f = df_f[df_f['AÑO'].astype(str).str.replace('.', '', regex=False).isin(sel['anio'])]
    if sel.get('trim'):
        df_f = df_f[df_f['Trimestre'].isin(sel['trim'])]
    if sel.get('mes'):
        df_f = df_f[df_f['Mes'].astype(str).isin([str(m) for m in sel['mes']])]
    if sel.get('negocio'):
        df_f = df_f[df_f['Negocio'].isin(sel['negocio'])]
    if sel.get('canal'):
        df_f = df_f[df_f['Canal'].isin(sel['canal'])]
    if sel.get('kam'):
        df_f = df_f[df_f['KAM'].isin(sel['kam'])]
    return df_f
