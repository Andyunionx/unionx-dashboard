"""
Helper de carga de datos de la app Contabilidad.
Lee parquets generados por extract_contabilidad_*.py.
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from views._parquet_source import read_parquet_smart
except ImportError:
    from _parquet_source import read_parquet_smart

PROJECT_ROOT = Path(__file__).parent.parent
COB_DIR = PROJECT_ROOT / "data" / "contabilidad" / "cobranza"
CC_DIR = PROJECT_ROOT / "data" / "contabilidad" / "centro_costos"


@st.cache_data(ttl=300)
def _load_parquet(path: Path) -> pd.DataFrame:
    # Opción C: lee desde GitHub Raw (si PARQUET_BASE_URL) o local. Fallback local.
    return read_parquet_smart(path)


# ─── COBRANZA ──────────────────────────────────────────────────────
def documentos_no_conciliados() -> pd.DataFrame:
    return _load_parquet(COB_DIR / "documentos_no_conciliados.parquet")


def notas_credito() -> pd.DataFrame:
    return _load_parquet(COB_DIR / "notas_credito.parquet")


def pedidos_venta() -> pd.DataFrame:
    return _load_parquet(COB_DIR / "pedidos_venta.parquet")


@st.cache_data(ttl=300)
def cobranza_resumen() -> dict:
    p = COB_DIR / "resumen.json"
    if p.exists():
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return {}


def listar_uploads_pagos_portales() -> list[Path]:
    return sorted((COB_DIR / "pagos_portales").glob("*"))


def listar_uploads_cartolas_cobranza() -> list[Path]:
    return sorted((COB_DIR / "cartolas_bancarias").glob("*"))


# ─── CENTRO DE COSTOS ──────────────────────────────────────────────
def cc_movimientos_procesados() -> pd.DataFrame:
    return _load_parquet(CC_DIR / "movimientos_procesados.parquet")


def cc_pendientes_revision() -> pd.DataFrame:
    return _load_parquet(CC_DIR / "pendientes_revision.parquet")


@st.cache_data(ttl=300)
def cc_resumen() -> dict:
    p = CC_DIR / "resumen.json"
    if p.exists():
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return {}


def listar_libros_compras() -> list[Path]:
    return sorted((CC_DIR / "libros_compras").glob("*.xlsx"))


def listar_cartolas_cc() -> list[Path]:
    return sorted((CC_DIR / "cartolas_bancarias").glob("*.xlsx"))


def memoria_existe() -> bool:
    return (CC_DIR / "memoria_cuentas.xlsx").exists()


# ─── HELPERS DE FORMATO ────────────────────────────────────────────
def fmt_clp(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"${v:,.0f}"


def fmt_clp_m(v) -> str:
    """Formato CLP en millones."""
    if v is None or pd.isna(v):
        return "—"
    return f"${v/1e6:,.1f}M"
