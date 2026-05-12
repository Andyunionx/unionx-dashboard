"""
Helper de carga de datos finanzas — lee parquets generados por
extract_finanzas_planificacion.py. Cache de 5 min.
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "finanzas"
RESUMEN_FILE = DATA_DIR / "resumen_general.json"


@st.cache_data(ttl=300)
def _load_parquet(name: str) -> pd.DataFrame:
    path = DATA_DIR / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def pyl() -> pd.DataFrame:
    """P&L histórico (2019-2026) en formato largo."""
    return _load_parquet("pyl_mensual")


def ppto_2026() -> pd.DataFrame:
    """Ppto 2026 por código contable (CC)."""
    return _load_parquet("ppto_2026")


def resumen_ytd() -> pd.DataFrame:
    """Resumen YTD vs Ppto vs YoY."""
    return _load_parquet("resumen_ytd")


def kt() -> pd.DataFrame:
    """Capital de Trabajo."""
    return _load_parquet("kt")


def deuda() -> pd.DataFrame:
    """Deuda financiera."""
    return _load_parquet("deuda")


def metas_2026() -> pd.DataFrame:
    """Metas 2026 mensuales (Venta/Contrib/GAV/EBIT/EBITDA × Meta/Real/Var)."""
    return _load_parquet("metas_2026")


def fcst_eerr() -> pd.DataFrame:
    """Forecast EERR."""
    return _load_parquet("fcst_eerr")


def dashboard_data() -> pd.DataFrame:
    """Hoja Dashboard Data pre-cocinada."""
    return _load_parquet("dashboard_data")


def analisis_financiero() -> pd.DataFrame:
    """Análisis Financiero YTD."""
    return _load_parquet("analisis_financiero")


@st.cache_data(ttl=300)
def resumen_general() -> dict:
    """Metadata: cuándo se generó, qué hojas se procesaron, etc."""
    if RESUMEN_FILE.exists():
        try:
            return json.load(open(RESUMEN_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def info_actualizacion() -> str:
    """Texto humano-amigable: '🕒 Datos del archivo: actualizado el X · extraído el Y'."""
    r = resumen_general()
    arch_mod = r.get("archivo_modificado", "")
    gen = r.get("generado_en", "")
    try:
        arch_mod_fmt = datetime.fromisoformat(arch_mod).strftime("%d/%m/%Y %H:%M")
    except Exception:
        arch_mod_fmt = arch_mod[:16]
    try:
        gen_fmt = datetime.fromisoformat(gen).strftime("%d/%m/%Y %H:%M")
    except Exception:
        gen_fmt = gen[:16]
    return f"📂 Archivo modificado: {arch_mod_fmt} · 🔄 Datos extraídos: {gen_fmt}"


# ============================================================
# FORMATTERS — útiles para todas las vistas
# ============================================================
def fmt_clp(v, miles: bool = True) -> str:
    """Formato CLP en miles (M$)."""
    if v is None or pd.isna(v):
        return "—"
    if miles:
        return f"${v:,.0f} M"
    return f"${v:,.0f}"


def fmt_pct(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v * 100:+.1f}%" if abs(v) < 10 else f"{v:+.0f}%"


def fmt_pct_simple(v) -> str:
    """% que ya viene como número (no decimal)."""
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%"


def color_var(pct: float, inverted: bool = False) -> str:
    """Color para variación. inverted=True para costos (var positiva es mala)."""
    if pct is None or pd.isna(pct):
        return "#94A3B8"
    if inverted:
        pct = -pct
    if pct >= 0.05:
        return "#16A34A"  # verde
    if pct >= -0.05:
        return "#F59E0B"  # amarillo
    return "#DC2626"  # rojo
