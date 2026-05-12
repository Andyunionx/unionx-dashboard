"""Carga unificada de datos para la app Planificación.

Centraliza el acceso a:
- Forecast SKU (parquet)
- Stock actual (Turso vía views.shared.cached_stock)
- Tránsito COMEX (parquet)
- Ventas históricas (parquet + Turso)
- Maestro proveedores (parquet local, llenado desde Drive)
- Políticas de stock objetivo (parquet local)

Cada loader devuelve un DataFrame con columnas explícitas. Si la fuente
todavía no existe (típico en arranque del módulo), devuelve un DataFrame
vacío con el schema esperado para que la UI muestre "esperando carga"
en vez de explotar.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
PLAN_DIR = DATA_DIR / 'planificacion'


# ============================================================
# Schemas esperados (cuando el dato aún no exista, devolvemos vacío
# con estas columnas para que la UI no se rompa)
# ============================================================
PROVEEDORES_SCHEMA = [
    'proveedor_id', 'nombre', 'pais_origen', 'puerto_origen',
    'contacto_nombre', 'contacto_email', 'contacto_whatsapp',
    'moneda', 'incoterm', 'tipo_credito', 'dias_credito',
    'dias_produccion_min', 'dias_produccion_max',
    'dias_transito_min', 'dias_transito_max',
    'moq_unidades', 'moq_usd', 'moq_cbm', 'comentarios',
]

POLITICAS_SCHEMA = [
    'categoria_comercial', 'meses_cobertura_objetivo',
    'meses_cobertura_minimo', 'meses_cobertura_maximo',
    'lead_time_buffer_dias', 'comentarios',
]


@st.cache_data(ttl=900, show_spinner=False)
def cargar_forecast_sku() -> pd.DataFrame:
    """Forecast diario por SKU (anchored si existe, base si no)."""
    p_anchored = DATA_DIR / 'forecast' / 'forecast_skus_anchored.parquet'
    p_base = DATA_DIR / 'forecast' / 'forecast_skus.parquet'
    path = p_anchored if p_anchored.exists() else p_base
    if not path.exists():
        return pd.DataFrame(columns=['sku', 'fecha', 'forecast_uds', 'canal'])
    df = pd.read_parquet(path)
    if 'fecha' in df.columns:
        df['fecha'] = pd.to_datetime(df['fecha'])
    return df


@st.cache_data(ttl=900, show_spinner=False)
def cargar_transito() -> pd.DataFrame:
    """Importaciones en tránsito (Drive Martín)."""
    path = DATA_DIR / 'comex' / 'transito.parquet'
    if not path.exists():
        return pd.DataFrame(columns=['sku', 'pi', 'cantidad', 'costo_usd', 'fecha_eta_bodega'])
    df = pd.read_parquet(path)
    for c in ('fecha_embarque', 'fecha_eta_chile', 'fecha_eta_bodega'):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors='coerce')
    return df


@st.cache_data(ttl=900, show_spinner=False)
def cargar_ventas_historicas(meses: int = 24) -> pd.DataFrame:
    """Ventas históricas para análisis de negociación (volumen por SKU, evolución)."""
    path = DATA_DIR / 'historico' / 'ventas_historico.parquet'
    if not path.exists():
        return pd.DataFrame()
    import pyarrow.parquet as pq
    schema_cols = set(pq.ParquetFile(str(path)).schema.names)
    cols_deseadas = ['fecha_venta', 'sku', 'producto', 'marca', 'proveedor',
                     'categoria_comercial', 'cantidad', 'costo_total', 'costo_unitario',
                     'venta_neta', 'canal']
    cols = [c for c in cols_deseadas if c in schema_cols]
    df = pd.read_parquet(path, columns=cols)
    df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce')
    corte = pd.Timestamp.today() - pd.DateOffset(months=meses)
    return df[df['fecha_venta'] >= corte].copy()


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_stock_diario(dias: int = 120) -> pd.DataFrame:
    """Stock diario histórico, filtrado a los últimos N días para no traer 5M filas."""
    path = DATA_DIR / 'stock_historico' / 'stock_diario.parquet'
    if not path.exists():
        return pd.DataFrame(columns=['fecha', 'sku', 'bodega', 'cantidad'])
    df = pd.read_parquet(path)
    df['fecha'] = pd.to_datetime(df['fecha'])
    corte = pd.Timestamp.today().normalize() - pd.Timedelta(days=dias)
    return df[df['fecha'] >= corte].copy()


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_proveedores_master() -> pd.DataFrame:
    """Maestro de proveedores. Si no existe el parquet, devuelve schema vacío."""
    path = PLAN_DIR / 'proveedores_master.parquet'
    if not path.exists():
        return pd.DataFrame(columns=PROVEEDORES_SCHEMA)
    return pd.read_parquet(path)


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_politicas_stock() -> pd.DataFrame:
    """Política de stock objetivo por categoría comercial."""
    path = PLAN_DIR / 'stock_objetivo.parquet'
    if not path.exists():
        return pd.DataFrame(columns=POLITICAS_SCHEMA)
    return pd.read_parquet(path)


def fuentes_status() -> dict:
    """Diagnóstico: qué fuentes tienen datos y cuáles esperan carga."""
    fuentes = {
        'Forecast SKU': DATA_DIR / 'forecast' / 'forecast_skus_anchored.parquet',
        'Tránsito COMEX': DATA_DIR / 'comex' / 'transito.parquet',
        'Ventas histórico': DATA_DIR / 'historico' / 'ventas_historico.parquet',
        'Stock histórico': DATA_DIR / 'stock_historico' / 'stock_diario.parquet',
        'Maestro proveedores': PLAN_DIR / 'proveedores_master.parquet',
        'Política stock objetivo': PLAN_DIR / 'stock_objetivo.parquet',
    }
    return {k: {'existe': v.exists(), 'path': str(v.relative_to(PROJECT_ROOT))} for k, v in fuentes.items()}
