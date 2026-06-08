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

import os
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from views._parquet_source import read_parquet_smart
except ImportError:
    from _parquet_source import read_parquet_smart

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
PLAN_DIR = DATA_DIR / 'planificacion'
SNAPSHOTS_DIR = PLAN_DIR / 'snapshots'

# Parquets de fallback cuando Turso bloquea reads (forbidden / BLOCKED).
# Los regenera extract_planif_snapshots.py cuando Turso vuelve a estar disponible.
FALLBACK_PARQUETS = {
    'planif_master_sku':            SNAPSHOTS_DIR / 'planif_master_sku.parquet',
    'planif_stock_baseline':        SNAPSHOTS_DIR / 'planif_stock_baseline.parquet',
    'planif_transito_baseline':     SNAPSHOTS_DIR / 'planif_transito_baseline.parquet',
    'planif_stock_live':            SNAPSHOTS_DIR / 'planif_stock_live.parquet',
    'planif_transito_live':         SNAPSHOTS_DIR / 'planif_transito_live.parquet',
    'planif_ventas_diarias_sku':    SNAPSHOTS_DIR / 'planif_ventas_diarias_sku.parquet',
    'planif_forecast_manual':       SNAPSHOTS_DIR / 'planif_forecast_manual.parquet',
}

# Baselines pre-existentes (compatibilidad con archivos ya en disco al 14-may).
# Si no existe el snapshot oficial, se usa este como segundo fallback.
LEGACY_FALLBACKS = {
    'planif_master_sku':        PLAN_DIR / 'baseline_master_sku_full.parquet',
    'planif_stock_baseline':    PLAN_DIR / 'baseline_stock_2026-05-11.parquet',
    'planif_transito_baseline': PLAN_DIR / 'baseline_transito_2026-05-11.parquet',
}


def _is_turso_blocked(err: Exception) -> bool:
    """Detecta si el error viene del bloqueo de reads de Turso."""
    msg = (str(err) or '').lower()
    return any(s in msg for s in (
        'blocked', 'forbidden', 'upgrade your plan', "'result'",
    ))


def _marcar_bypass(snapshot_path: Path, tabla: str):
    """Marca state de Streamlit para que la app muestre el banner."""
    try:
        st.session_state['_planif_turso_bypass'] = True
        files = st.session_state.setdefault('_planif_bypass_files', [])
        info = f"{tabla} ← {snapshot_path.name}"
        if info not in files:
            files.append(info)
        from datetime import datetime as _dt
        mtime = _dt.fromtimestamp(snapshot_path.stat().st_mtime)
        prev = st.session_state.get('_planif_bypass_oldest')
        if prev is None or mtime < prev:
            st.session_state['_planif_bypass_oldest'] = mtime
    except Exception:
        pass  # streamlit no inicializado (uso CLI)


def _try_turso_or_parquet(turso_fn, tabla: str, schema_cols: list | None = None,
                            silent: bool = False) -> pd.DataFrame:
    """Intenta Turso; si bloqueado, carga snapshot parquet.

    1. Ejecuta turso_fn() — debe devolver pd.DataFrame.
    2. Si falla con bloqueo: prueba FALLBACK_PARQUETS[tabla] → LEGACY_FALLBACKS[tabla].
    3. Si nada funciona, devuelve DataFrame vacío con schema (no rompe la UI).

    silent=True: no emite st.warning si todo falla. Para loaders que tienen
    su propio plan B (ej. cargar_planif_transito_live cae a comex/transito.parquet).

    Con PARQUET_ONLY=1 NO intenta Turso: va directo al snapshot parquet (Opción C:
    desde GitHub Raw si PARQUET_BASE_URL, si no local).
    """
    parquet_only = os.environ.get('PARQUET_ONLY') == '1'
    if not parquet_only:
        try:
            return turso_fn()
        except Exception as e:
            if not _is_turso_blocked(e):
                if not silent:
                    st.warning(f"No pude leer {tabla}: {e}")
                return pd.DataFrame(columns=schema_cols or [])
            # Turso bloqueado → cae a snapshot (mismo camino que parquet_only)

    for source_path in (FALLBACK_PARQUETS.get(tabla), LEGACY_FALLBACKS.get(tabla)):
        if source_path is None:
            continue
        try:
            df = read_parquet_smart(source_path)  # URL (Opción C) o local
        except Exception as e2:
            if not silent:
                st.warning(f"Snapshot {source_path.name} falló: {type(e2).__name__}: {e2}")
            continue
        if not df.empty:
            if not parquet_only:
                _marcar_bypass(source_path, tabla)
            return df
    if not silent and not parquet_only:
        st.warning(f"No pude leer {tabla} (Turso bloqueado y sin snapshot).")
    return pd.DataFrame(columns=schema_cols or [])


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
# Loaders Turso — tablas planif_* (Fases 1+2+3)
# ============================================================

BASELINE_DATE = '2026-05-11'


@st.cache_data(ttl=60, show_spinner=False)
def cargar_forecast_manual_mensual() -> pd.DataFrame:
    """Forecast PPTO por SKU × mes (formato 'YYYY-MM').

    Tabla `planif_forecast_manual` se llena con `extract_forecast_ppto_a_turso.py`
    leyendo del FCST FINAL XLSX las cols `Venta PPTO ENE26..ENE27`.
    """
    df = _try_turso_or_parquet(
        lambda: _turso_df(
            "SELECT sku, mes, unidades, fuente, ts_actualizado "
            "FROM planif_forecast_manual WHERE unidades IS NOT NULL"
        ),
        tabla='planif_forecast_manual',
        schema_cols=['sku', 'mes', 'unidades', 'fuente', 'ts_actualizado'],
    )
    if not df.empty:
        df['unidades'] = pd.to_numeric(df['unidades'], errors='coerce').fillna(0)
        df['sku'] = df['sku'].astype(str)
    return df


def _turso_client():
    """Crea cliente Turso bajo demanda usando env vars (Streamlit Cloud secrets)."""
    import os
    import libsql_client
    url = os.environ.get('LIBSQL_URL') or st.secrets.get('LIBSQL_URL')
    token = os.environ.get('LIBSQL_AUTH_TOKEN') or st.secrets.get('LIBSQL_AUTH_TOKEN')
    return libsql_client.create_client_sync(url=url, auth_token=token)


def _turso_df(sql: str, args: list | None = None) -> pd.DataFrame:
    """Helper: ejecuta SQL y devuelve DataFrame.

    Bypassea libsql_client 0.3.1 que crashea con KeyError('result') cuando
    Turso devuelve error (ej. plan bloqueado). Usa HTTP API v2/pipeline directo
    y propaga el mensaje real del servidor.
    """
    import os
    import requests
    url = os.environ.get('LIBSQL_URL') or st.secrets.get('LIBSQL_URL')
    token = os.environ.get('LIBSQL_AUTH_TOKEN') or st.secrets.get('LIBSQL_AUTH_TOKEN')

    # Build statement con args posicionales
    stmt = {'sql': sql}
    if args:
        stmt['args'] = [
            {'type': 'null', 'value': None} if v is None else
            {'type': 'integer', 'value': str(v)} if isinstance(v, bool) is False and isinstance(v, int) else
            {'type': 'float', 'value': float(v)} if isinstance(v, float) else
            {'type': 'text', 'value': str(v)}
            for v in args
        ]

    r = requests.post(
        f'{url}/v2/pipeline',
        headers={'Authorization': f'Bearer {token}'},
        json={'requests': [{'type': 'execute', 'stmt': stmt}, {'type': 'close'}]},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    results = data.get('results', [])
    if not results:
        return pd.DataFrame()
    first = results[0]
    if first.get('type') == 'error':
        err = first.get('error', {})
        raise RuntimeError(f"{err.get('code', 'ERROR')}: {err.get('message', '?')}")
    resp = first.get('response', {}).get('result', {})
    cols = [c.get('name') for c in resp.get('cols', [])]
    rows = resp.get('rows', [])
    # Cada row es lista de {type, value}
    data_rows = [[v.get('value') for v in row] for row in rows]
    return pd.DataFrame(data_rows, columns=cols)


@st.cache_data(ttl=900, show_spinner=False)
def cargar_planif_master() -> pd.DataFrame:
    """Master SKU de planificación (baseline FCST + augmentados desde ventas)."""
    return _try_turso_or_parquet(
        lambda: _turso_df(
            "SELECT sku, id_categoria, marca, categoria_padre, categoria_hijo, "
            "descripcion, total, categoria_producto, pct_proyeccion_vta, "
            "ranking_comercial, stock_hoy FROM planif_master_sku"
        ),
        tabla='planif_master_sku',
    )


@st.cache_data(ttl=900, show_spinner=False)
def cargar_planif_stock_baseline(snapshot_date: str = BASELINE_DATE) -> pd.DataFrame:
    """Stock baseline (foto al 11/05 10:00 desde Excel FCST)."""
    return _try_turso_or_parquet(
        lambda: _turso_df(
            "SELECT sku, marca, producto, stock_total, total_full, bodega_principal, "
            "full_meli, full_fala, full_paris, full_ripley, tiendas, reserva, "
            "transito_full_fala, transito_full_meli, costo, valoracion "
            "FROM planif_stock_baseline WHERE snapshot_date = ?", [snapshot_date]
        ),
        tabla='planif_stock_baseline',
    )


@st.cache_data(ttl=900, show_spinner=False)
def cargar_planif_transito_baseline(snapshot_date: str = BASELINE_DATE) -> pd.DataFrame:
    """Tránsito baseline (foto al 11/05 desde Excel FCST)."""
    return _try_turso_or_parquet(
        lambda: _turso_df(
            "SELECT sku, variante, pi, status, tipo_transporte, nro_pedido, "
            "cantidad, costo_uni_usd, gift_box_envio, costo_ingreso_clp, "
            "fecha_embarque, fecha_eta_chile, fecha_eta_bodega, mes, stock_actual, "
            "tipo_categoria, valor_usd_total, marca "
            "FROM planif_transito_baseline WHERE snapshot_date = ?", [snapshot_date]
        ),
        tabla='planif_transito_baseline',
    )


LINEAS_NEGOCIO_PLANIFICACION = ['Marketplace', 'Páginas propias', 'Fidelización']


@st.cache_data(ttl=900, show_spinner=False)
def cargar_ventas_year_minus_1(baseline_date: str, hoy: str,
                                lineas_negocio: tuple) -> dict:
    """Trae ventas del año pasado en 2 períodos: mismo y resto del mes.

    Args:
        baseline_date: '2026-05-11' (string ISO date)
        hoy: '2026-05-15'
        lineas_negocio: tupla de tipo_negocio para filtrar

    Returns:
        {
          'mismo_periodo': DataFrame [sku, uds]  ← 2025-05-11 → 2025-05-15
          'resto_mes':    DataFrame [sku, uds]  ← 2025-05-16 → 2025-05-31
        }
    """
    try:
        base = pd.Timestamp(baseline_date)
        hoy_ts = pd.Timestamp(hoy)
        fin_mes = (hoy_ts.replace(day=1) + pd.DateOffset(months=1)) - pd.Timedelta(days=1)

        py_base = (base - pd.DateOffset(years=1)).strftime('%Y-%m-%d')
        py_hoy = (hoy_ts - pd.DateOffset(years=1)).strftime('%Y-%m-%d')
        py_dia_sig = (hoy_ts - pd.DateOffset(years=1) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        py_fin_mes = (fin_mes - pd.DateOffset(years=1)).strftime('%Y-%m-%d')

        placeholders = ','.join(['?'] * len(lineas_negocio))
        # Mismo período: py_base → py_hoy (inclusive)
        sql_mismo = (f"SELECT sku, SUM(COALESCE(cantidad,0)) AS uds "
                     f"FROM ventas WHERE fecha_venta >= ? AND fecha_venta <= ? "
                     f"AND sku IS NOT NULL AND sku != '' "
                     f"AND tipo_negocio IN ({placeholders}) GROUP BY sku")
        sql_resto = (f"SELECT sku, SUM(COALESCE(cantidad,0)) AS uds "
                     f"FROM ventas WHERE fecha_venta >= ? AND fecha_venta <= ? "
                     f"AND sku IS NOT NULL AND sku != '' "
                     f"AND tipo_negocio IN ({placeholders}) GROUP BY sku")
        try:
            df_mismo = _turso_df(sql_mismo, [py_base, py_hoy] + list(lineas_negocio))
            df_resto = _turso_df(sql_resto, [py_dia_sig, py_fin_mes] + list(lineas_negocio))
        except Exception as e_turso:
            if not _is_turso_blocked(e_turso):
                raise
            # Fallback: agregamos desde parquet histórico local
            df_mismo, df_resto = _ventas_year_minus_1_desde_parquet(
                py_base, py_hoy, py_dia_sig, py_fin_mes, lineas_negocio,
            )
            _marcar_bypass(DATA_DIR / 'historico' / 'ventas_historico.parquet',
                            'ventas (year-1)')
        for d in (df_mismo, df_resto):
            if not d.empty:
                d['uds'] = pd.to_numeric(d['uds'], errors='coerce').fillna(0)
                d['sku'] = d['sku'].astype(str)
        return {
            'mismo_periodo': df_mismo,
            'resto_mes': df_resto,
            'rango_mismo': (py_base, py_hoy),
            'rango_resto': (py_dia_sig, py_fin_mes),
        }
    except Exception as e:
        st.warning(f"No pude leer ventas año pasado: {e}")
        return {'mismo_periodo': pd.DataFrame(), 'resto_mes': pd.DataFrame(),
                'rango_mismo': (None, None), 'rango_resto': (None, None)}


def _ventas_year_minus_1_desde_parquet(py_base, py_hoy, py_dia_sig, py_fin_mes,
                                         lineas_negocio: tuple) -> tuple:
    """Agrega ventas desde data/historico/ventas_historico.parquet."""
    p = DATA_DIR / 'historico' / 'ventas_historico.parquet'
    if not p.exists():
        return pd.DataFrame(columns=['sku', 'uds']), pd.DataFrame(columns=['sku', 'uds'])
    cols = ['fecha_venta', 'sku', 'cantidad', 'tipo_negocio']
    df = pd.read_parquet(p, columns=cols)
    df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    df = df[df['sku'].notna() & (df['sku'].astype(str) != '')]
    if lineas_negocio:
        df = df[df['tipo_negocio'].isin(list(lineas_negocio))]
    df_mismo = (df[(df['fecha_venta'] >= py_base) & (df['fecha_venta'] <= py_hoy)]
                .groupby('sku', as_index=False)['cantidad'].sum()
                .rename(columns={'cantidad': 'uds'}))
    df_resto = (df[(df['fecha_venta'] >= py_dia_sig) & (df['fecha_venta'] <= py_fin_mes)]
                .groupby('sku', as_index=False)['cantidad'].sum()
                .rename(columns={'cantidad': 'uds'}))
    return df_mismo, df_resto


@st.cache_data(ttl=300, show_spinner=False)
def cargar_ventas_live_desde_baseline(baseline_date: str = BASELINE_DATE,
                                       lineas_negocio: tuple = None) -> pd.DataFrame:
    """Ventas LIVE desde Turso `ventas` agregadas por SKU × día desde baseline.

    Va directo a `ventas` (live cada hora) y agrega on-the-fly. Cache 5 min.

    Args:
        baseline_date: filtra fecha_venta >= baseline_date
        lineas_negocio: si pasas tupla de tipo_negocio (ej. ('Marketplace','Páginas propias',
            'Fidelización')) filtra por esas. Si None, sin filtro de línea.
    """
    sql = ("SELECT sku, fecha_venta AS fecha, "
           "SUM(COALESCE(cantidad,0)) AS unidades, "
           "SUM(COALESCE(venta_bruta,0)) AS venta_neta, "
           "SUM(COALESCE(margen_front,0)) AS margen_front "
           "FROM ventas WHERE fecha_venta >= ? AND sku IS NOT NULL AND sku != '' ")
    args = [baseline_date]
    if lineas_negocio:
        placeholders = ','.join(['?'] * len(lineas_negocio))
        sql += f"AND tipo_negocio IN ({placeholders}) "
        args.extend(list(lineas_negocio))
    sql += "GROUP BY sku, fecha_venta"
    try:
        return _turso_df(sql, args)
    except Exception as e:
        if not _is_turso_blocked(e):
            st.warning(f"No pude leer ventas live: {e}")
            return pd.DataFrame()
        # Fallback: parquet ventas_mes_actual (que cubre baseline → hoy)
        return _ventas_live_desde_parquet(baseline_date, lineas_negocio)


def _ventas_live_desde_parquet(baseline_date: str, lineas_negocio: tuple) -> pd.DataFrame:
    """Agrega ventas live desde data/historico/ventas_mes_actual.parquet."""
    p = DATA_DIR / 'historico' / 'ventas_mes_actual.parquet'
    if not p.exists():
        st.warning(f"No existe fallback ventas_mes_actual.parquet")
        return pd.DataFrame(columns=['sku', 'fecha', 'unidades', 'venta_neta', 'margen_front'])
    cols = ['fecha_venta', 'sku', 'cantidad', 'venta_bruta', 'margen_front', 'tipo_negocio']
    df = pd.read_parquet(p, columns=[c for c in cols if c])
    df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce')
    df = df[df['fecha_venta'] >= pd.Timestamp(baseline_date)]
    df = df[df['sku'].notna() & (df['sku'].astype(str) != '')]
    if lineas_negocio:
        df = df[df['tipo_negocio'].isin(list(lineas_negocio))]
    out = (df.groupby(['sku', 'fecha_venta'], as_index=False)
             .agg(unidades=('cantidad', 'sum'),
                   venta_neta=('venta_bruta', 'sum'),
                   margen_front=('margen_front', 'sum')))
    out = out.rename(columns={'fecha_venta': 'fecha'})
    _marcar_bypass(p, 'ventas (live desde baseline)')
    return out


@st.cache_data(ttl=300, show_spinner=False)
def cargar_planif_ventas_diarias() -> pd.DataFrame:
    """Ventas reales agregadas SKU × día (desde 11/05). Sync diario."""
    df = _try_turso_or_parquet(
        lambda: _turso_df(
            "SELECT sku, fecha, unidades, venta_neta, margen_front "
            "FROM planif_ventas_diarias_sku"
        ),
        tabla='planif_ventas_diarias_sku',
    )
    if not df.empty:
        if 'fecha' in df.columns:
            df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
        for c in ('unidades', 'venta_neta', 'margen_front'):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def cargar_planif_stock_live() -> pd.DataFrame:
    """Stock live de Odoo agregado por categoría de bodega. Sync diario."""
    num_cols = ['stock_total', 'stock_disponible', 'stock_reservado',
                'valor_total_clp', 'ca1_hijas', 'full_meli', 'full_fala',
                'full_paris', 'full_ripley', 'volcan', 'duty_travel',
                'reserva', 'tiendas', 'marketing', 'otros']
    df = _try_turso_or_parquet(
        lambda: _turso_df(
            "SELECT sku, producto, marca, categoria, stock_total, stock_disponible, "
            "stock_reservado, valor_total_clp, ca1_hijas, full_meli, full_fala, "
            "full_paris, full_ripley, volcan, duty_travel, reserva, tiendas, "
            "marketing, otros, ts_snapshot FROM planif_stock_live"
        ),
        tabla='planif_stock_live',
    )
    if not df.empty:
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def cargar_planif_transito_live() -> pd.DataFrame:
    """Tránsito vigente con ETAs. Sync diario.

    Fallback adicional: si Turso bloqueado Y no hay snapshot, lee directamente
    `data/comex/transito.parquet` (Odoo extract — fuente nativa del agente).
    """
    df = _try_turso_or_parquet(
        lambda: _turso_df(
            "SELECT sku, producto, pi, status, transporte, nro_pedido, cantidad, "
            "costo_unitario_usd, costo_total_usd, costo_ingreso_clp, "
            "fecha_embarque, fecha_eta_chile, fecha_eta_bodega "
            "FROM planif_transito_live"
        ),
        tabla='planif_transito_live',
        silent=True,  # tiene plan B abajo (parquet COMEX), no contaminar UI
    )
    # Plan B: si vino vacío, leer directo del parquet Odoo
    if df.empty:
        comex_parquet = DATA_DIR / 'comex' / 'transito.parquet'
        if comex_parquet.exists():
            try:
                df = pd.read_parquet(comex_parquet)
                _marcar_bypass(comex_parquet, 'planif_transito_live (via comex/transito.parquet)')
            except Exception as e:
                st.warning(f"No pude leer fallback comex/transito.parquet: {e}")
    if not df.empty:
        for c in ('fecha_embarque', 'fecha_eta_chile', 'fecha_eta_bodega'):
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], errors='coerce')
        for c in ('cantidad', 'costo_unitario_usd', 'costo_total_usd', 'costo_ingreso_clp'):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df


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
