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


# ============================================================
# Loaders Turso — tablas planif_* (Fases 1+2)
# ============================================================

BASELINE_DATE = '2026-05-11'


def _turso_client():
    """Crea cliente Turso bajo demanda usando env vars (Streamlit Cloud secrets)."""
    import os
    import libsql_client
    url = os.environ.get('LIBSQL_URL') or st.secrets.get('LIBSQL_URL')
    token = os.environ.get('LIBSQL_AUTH_TOKEN') or st.secrets.get('LIBSQL_AUTH_TOKEN')
    return libsql_client.create_client_sync(url=url, auth_token=token)


def _turso_df(sql: str, args: list | None = None) -> pd.DataFrame:
    """Helper: ejecuta SQL y devuelve DataFrame."""
    c = _turso_client()
    try:
        rs = c.execute(sql, args) if args else c.execute(sql)
        if not rs.rows:
            return pd.DataFrame(columns=rs.columns)
        return pd.DataFrame([list(r) for r in rs.rows], columns=rs.columns)
    finally:
        c.close()


@st.cache_data(ttl=900, show_spinner=False)
def cargar_planif_master() -> pd.DataFrame:
    """Master SKU de planificación (baseline FCST + augmentados desde ventas)."""
    try:
        return _turso_df(
            "SELECT sku, id_categoria, marca, categoria_padre, categoria_hijo, "
            "descripcion, total, categoria_producto, pct_proyeccion_vta, "
            "ranking_comercial, stock_hoy FROM planif_master_sku"
        )
    except Exception as e:
        st.warning(f"No pude leer planif_master_sku: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def cargar_planif_stock_baseline(snapshot_date: str = BASELINE_DATE) -> pd.DataFrame:
    """Stock baseline (foto al 11/05 10:00 desde Excel FCST)."""
    try:
        return _turso_df(
            "SELECT sku, marca, producto, stock_total, total_full, bodega_principal, "
            "full_meli, full_fala, full_paris, full_ripley, tiendas, reserva, "
            "transito_full_fala, transito_full_meli, costo, valoracion "
            "FROM planif_stock_baseline WHERE snapshot_date = ?", [snapshot_date]
        )
    except Exception as e:
        st.warning(f"No pude leer planif_stock_baseline: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def cargar_planif_transito_baseline(snapshot_date: str = BASELINE_DATE) -> pd.DataFrame:
    """Tránsito baseline (foto al 11/05 desde Excel FCST)."""
    try:
        return _turso_df(
            "SELECT sku, variante, pi, status, tipo_transporte, nro_pedido, "
            "cantidad, costo_uni_usd, gift_box_envio, costo_ingreso_clp, "
            "fecha_embarque, fecha_eta_chile, fecha_eta_bodega, mes, stock_actual, "
            "tipo_categoria, valor_usd_total, marca "
            "FROM planif_transito_baseline WHERE snapshot_date = ?", [snapshot_date]
        )
    except Exception as e:
        st.warning(f"No pude leer planif_transito_baseline: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def cargar_planif_ventas_diarias() -> pd.DataFrame:
    """Ventas reales agregadas SKU × día (desde 11/05). Sync diario."""
    try:
        df = _turso_df(
            "SELECT sku, fecha, unidades, venta_neta, margen_front "
            "FROM planif_ventas_diarias_sku"
        )
        if not df.empty:
            df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
            for c in ('unidades', 'venta_neta', 'margen_front'):
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        return df
    except Exception as e:
        st.warning(f"No pude leer planif_ventas_diarias_sku: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def cargar_planif_stock_live() -> pd.DataFrame:
    """Stock live de Odoo agregado por categoría de bodega. Sync diario."""
    try:
        df = _turso_df(
            "SELECT sku, producto, marca, categoria, stock_total, stock_disponible, "
            "stock_reservado, valor_total_clp, ca1_hijas, full_meli, full_fala, "
            "full_paris, full_ripley, volcan, duty_travel, reserva, tiendas, "
            "marketing, otros, ts_snapshot FROM planif_stock_live"
        )
        if not df.empty:
            num_cols = ['stock_total', 'stock_disponible', 'stock_reservado',
                        'valor_total_clp', 'ca1_hijas', 'full_meli', 'full_fala',
                        'full_paris', 'full_ripley', 'volcan', 'duty_travel',
                        'reserva', 'tiendas', 'marketing', 'otros']
            for c in num_cols:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        return df
    except Exception as e:
        st.warning(f"No pude leer planif_stock_live: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def cargar_planif_transito_live() -> pd.DataFrame:
    """Tránsito vigente con ETAs. Sync diario."""
    try:
        df = _turso_df(
            "SELECT sku, producto, pi, status, transporte, nro_pedido, cantidad, "
            "costo_unitario_usd, costo_total_usd, costo_ingreso_clp, "
            "fecha_embarque, fecha_eta_chile, fecha_eta_bodega "
            "FROM planif_transito_live"
        )
        if not df.empty:
            for c in ('fecha_embarque', 'fecha_eta_chile', 'fecha_eta_bodega'):
                df[c] = pd.to_datetime(df[c], errors='coerce')
            for c in ('cantidad', 'costo_unitario_usd', 'costo_total_usd', 'costo_ingreso_clp'):
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        return df
    except Exception as e:
        st.warning(f"No pude leer planif_transito_live: {e}")
        return pd.DataFrame()


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
