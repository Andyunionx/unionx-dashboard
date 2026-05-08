"""Shared helpers, data loaders y filtros para todas las views."""
import os
import sqlite3
import sys
import tempfile
import time as _time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

# Streamlit Cloud: exponer secretos como env vars
for _key in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN', 'ANDRES_ODOO_PASSWORD'):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

from app.services.maestra_service import MaestraService
from db_client import get_db_path

DB_PATH = get_db_path()
HISTORICO_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
CUTOFF_HISTORICO = '2026-04-01'


# ============================================================
# Helpers de formato
# ============================================================
def fmt_money(v):
    if v is None or pd.isna(v):
        return "-"
    return f"${int(round(v)):,}".replace(",", ".")


def fmt_int(v):
    if v is None or pd.isna(v):
        return "-"
    return f"{int(round(v)):,}".replace(",", ".")


def fmt_pct(v, decimals=1):
    if v is None or pd.isna(v):
        return "-"
    return f"{v:.{decimals}f}%"


# ============================================================
# KPI cards estilo Contribución (custom HTML, colores)
# ============================================================
def kpi_card(label: str, value: str, sub: str = "", color: str = "#1E40AF") -> str:
    """Renderiza una KPI card estilizada. Usar con st.markdown(unsafe_allow_html=True)."""
    return f"""<div style="background:white;border-radius:12px;padding:16px 18px;text-align:center;
        box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #E2E8F0;height:100%;">
        <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;margin-bottom:4px;">{label}</div>
        <div style="font-size:1.5rem;font-weight:700;color:{color};line-height:1.2;">{value}</div>
        <div style="font-size:0.7rem;color:#94A3B8;margin-top:2px;">{sub}</div>
    </div>"""


# Paleta colores estándar
COLOR_VENTA = '#1E40AF'      # azul
COLOR_MARGEN = '#16A34A'     # verde
COLOR_COSTO = '#EA580C'      # naranja
COLOR_NEGATIVO = '#DC2626'   # rojo
COLOR_NEUTRO = '#64748B'     # gris


# ============================================================
# Local SQLite combinando parquet histórico + Turso live
# ============================================================
@st.cache_resource(ttl=300, show_spinner="Cargando datos (parquet histórico + Turso live)…")
def get_local_db_path():
    """SQLite local combinando histórico (parquet) + live (Turso). Auto-invalida 5 min."""
    if not os.environ.get('LIBSQL_URL'):
        return str(DB_PATH)

    print(f"[Local DB] Build {datetime.now()}", flush=True)

    libsql_url = os.environ['LIBSQL_URL'].rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    def turso_query(sql):
        body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
        r = requests.post(f"{libsql_url}/v2/pipeline", json=body, headers=headers, timeout=300)
        r.raise_for_status()
        return r.json()['results'][0]['response']['result']

    tmp_path = Path(tempfile.gettempdir()) / 'unionx_dashboard_local.db'
    if tmp_path.exists():
        tmp_path.unlink()

    conn = sqlite3.connect(str(tmp_path))

    schema_sql = [
        """CREATE TABLE ventas (
            tipo_movimiento TEXT, bodega TEXT, documento TEXT, fecha_documento TEXT,
            pedido TEXT, estado_pedido TEXT, tipo_despacho TEXT, sku TEXT, canal TEXT,
            fecha_venta TEXT, hora_venta TEXT, producto TEXT,
            categoria_macro TEXT, categoria_padre TEXT, categoria_hijo TEXT, categoria_comercial TEXT,
            estado_sku TEXT, pack TEXT, marca TEXT, proveedor TEXT,
            tipo_marca TEXT, tipo_compra TEXT, tipo_negocio TEXT, kam TEXT,
            estado_canal TEXT, anio_venta INT, mes_venta INT, semana_venta INT,
            dia_semana TEXT, hora_venta_num INT,
            cantidad REAL, venta_bruta REAL, venta_neta REAL, costo_unitario REAL, costo_total REAL,
            margen_front REAL, comision_pct REAL, comision REAL,
            logistica REAL, marketing REAL, margen_final REAL
        )""",
        """CREATE TABLE dim_productos (
            sku TEXT PRIMARY KEY, producto TEXT, categoria_macro TEXT, categoria_padre TEXT,
            categoria_hijo TEXT, categoria_comercial TEXT, estado_sku TEXT, pack TEXT,
            marca TEXT, proveedor TEXT, tipo_marca TEXT, tipo_compra TEXT
        )""",
        "CREATE TABLE metadata_cargas (fecha_carga TEXT, fuente TEXT, filas_cargadas INT, fecha_min_datos TEXT, fecha_max_datos TEXT, tipo TEXT)",
        "CREATE INDEX idx_ventas_fecha ON ventas(fecha_venta)",
        "CREATE INDEX idx_ventas_canal ON ventas(canal)",
        "CREATE INDEX idx_ventas_marca ON ventas(marca)",
        "CREATE INDEX idx_ventas_sku ON ventas(sku)",
    ]
    for sql in schema_sql:
        conn.execute(sql)
    conn.commit()

    cols_v = ['tipo_movimiento', 'bodega', 'documento', 'fecha_documento', 'pedido', 'estado_pedido',
              'tipo_despacho', 'sku', 'canal', 'fecha_venta', 'hora_venta', 'producto',
              'categoria_macro', 'categoria_padre', 'categoria_hijo', 'categoria_comercial',
              'estado_sku', 'pack', 'marca', 'proveedor', 'tipo_marca', 'tipo_compra', 'tipo_negocio',
              'kam', 'estado_canal', 'anio_venta', 'mes_venta', 'semana_venta', 'dia_semana',
              'hora_venta_num', 'cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario', 'costo_total',
              'margen_front', 'comision_pct', 'comision', 'logistica', 'marketing', 'margen_final']
    cols_csv = ','.join(cols_v)
    placeholders = ','.join(['?'] * len(cols_v))
    insert_sql = f"INSERT INTO ventas ({cols_csv}) VALUES ({placeholders})"

    # Parquet histórico
    if HISTORICO_PARQUET.exists():
        df_hist = pd.read_parquet(HISTORICO_PARQUET)
        df_hist[cols_v].to_sql('ventas', conn, if_exists='append', index=False, chunksize=5000, method='multi')

    # Live de Turso
    chunk_size = 50000
    last_rowid = 0
    while True:
        result = turso_query(
            f"SELECT rowid, {cols_csv} FROM ventas "
            f"WHERE fecha_venta >= '{CUTOFF_HISTORICO}' AND rowid > {last_rowid} "
            f"ORDER BY rowid LIMIT {chunk_size}"
        )
        rows = result['rows']
        if not rows:
            break
        flat = []
        for r in rows:
            vals = [c.get('value') if isinstance(c, dict) else c for c in r]
            last_rowid = int(vals[0])
            flat.append(tuple(vals[1:]))
        conn.executemany(insert_sql, flat)
        conn.commit()
        if len(rows) < chunk_size:
            break

    # dim_productos + metadata
    cols_p = ['sku', 'producto', 'categoria_macro', 'categoria_padre', 'categoria_hijo',
              'categoria_comercial', 'estado_sku', 'pack', 'marca', 'proveedor', 'tipo_marca', 'tipo_compra']
    result = turso_query(f"SELECT {','.join(cols_p)} FROM dim_productos")
    rows = result['rows']
    if rows:
        flat = [tuple(c.get('value') if isinstance(c, dict) else c for c in r) for r in rows]
        conn.executemany(
            f"INSERT OR IGNORE INTO dim_productos ({','.join(cols_p)}) VALUES ({','.join(['?']*len(cols_p))})",
            flat,
        )

    cols_m = ['fecha_carga', 'fuente', 'filas_cargadas', 'fecha_min_datos', 'fecha_max_datos', 'tipo']
    result = turso_query(f"SELECT {','.join(cols_m)} FROM metadata_cargas")
    rows = result['rows']
    if rows:
        flat = [tuple(c.get('value') if isinstance(c, dict) else c for c in r) for r in rows]
        conn.executemany(
            f"INSERT INTO metadata_cargas ({','.join(cols_m)}) VALUES ({','.join(['?']*len(cols_m))})",
            flat,
        )
        conn.commit()

    conn.close()
    return str(tmp_path)


def get_service():
    """Retorna MaestraService apuntando al SQLite local."""
    local_path = get_local_db_path()
    svc = MaestraService(local_path)

    def _force_local_conn(self=svc):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    svc._conn = _force_local_conn
    return svc


# ============================================================
# Cached queries
# ============================================================
@st.cache_data(ttl=300)
def cached_filtros():
    return get_service().get_filtros_disponibles()


@st.cache_data(ttl=300)
def cached_kpis(desde, hasta, canal, marca, categoria, tipo_negocio, kam):
    p = {'fecha_desde': desde, 'fecha_hasta': hasta}
    if canal: p['canal'] = canal
    if marca: p['marca'] = marca
    if categoria: p['categoria'] = categoria
    if tipo_negocio: p['tipo_negocio'] = tipo_negocio
    if kam: p['kam'] = kam
    return get_service().get_kpis_yoy(p)


@st.cache_data(ttl=300)
def cached_mensual():
    return get_service().get_tendencia_mensual_yoy()


@st.cache_data(ttl=300)
def cached_diaria(anio, mes):
    return get_service().get_tendencia_diaria_yoy(anio, mes)


@st.cache_data(ttl=300)
def cached_semanal(anio, mes, canal, marca, categoria, tipo_negocio, kam):
    p = {}
    if canal: p['canal'] = canal
    if marca: p['marca'] = marca
    if categoria: p['categoria'] = categoria
    if tipo_negocio: p['tipo_negocio'] = tipo_negocio
    if kam: p['kam'] = kam
    return get_service().get_tendencia_semanal_yoy(anio, mes, p)


@st.cache_data(ttl=300)
def cached_canales(desde, hasta, canal, marca, categoria, tipo_negocio, kam):
    p = {'fecha_desde': desde, 'fecha_hasta': hasta}
    if canal: p['canal'] = canal
    if marca: p['marca'] = marca
    if categoria: p['categoria'] = categoria
    if tipo_negocio: p['tipo_negocio'] = tipo_negocio
    if kam: p['kam'] = kam
    return get_service().get_por_canal_yoy(p)


@st.cache_data(ttl=300)
def cached_top_skus(desde, hasta, canal, marca, categoria, tipo_negocio, kam, limit):
    p = {'fecha_desde': desde, 'fecha_hasta': hasta}
    if canal: p['canal'] = canal
    if marca: p['marca'] = marca
    if categoria: p['categoria'] = categoria
    if tipo_negocio: p['tipo_negocio'] = tipo_negocio
    if kam: p['kam'] = kam
    return get_service().get_top_skus_yoy(p, limit=limit)


@st.cache_data(ttl=60)
def cached_health():
    return get_service().health()


# ============================================================
# Stock LIVE (cache 5 min)
# ============================================================
@st.cache_data(ttl=300, show_spinner="Consultando Odoo (puede tomar 30-60s)…")
def cached_stock():
    """Stock LIVE desde Odoo, cache 5 min."""
    from app.services.stock_advanced_service import StockAdvancedService
    from app.core.odoo_client import OdooClient

    # Leer password directo de st.secrets (no dependemos de Config import-time)
    odoo_password = (
        st.secrets.get('ANDRES_ODOO_PASSWORD')
        or os.environ.get('ANDRES_ODOO_PASSWORD')
    )
    if not odoo_password:
        raise RuntimeError(
            "ANDRES_ODOO_PASSWORD no está seteado en Streamlit Cloud Secrets. "
            "Settings → Secrets → agregar: ANDRES_ODOO_PASSWORD = \"...\""
        )

    odoo = OdooClient(
        url='https://unionxb2b.odoo.com',
        db='bmya-innovatek-sh-prd-6981800',
        username='andres@grupoeter.cl',
        password=str(odoo_password),
    )
    return StockAdvancedService(odoo).extract_full(progress_callback=None)


@st.cache_data(ttl=300, show_spinner="Consultando ventas por canal desde Turso…")
def cached_ventas_canal_30d():
    """Ventas últimos 30 días por SKU+canal desde Turso."""
    url = os.environ.get('LIBSQL_URL', '').rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    if not url:
        return pd.DataFrame()
    desde = (datetime.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
    sql = f"""
        SELECT sku, canal, tipo_negocio,
               ROUND(SUM(cantidad), 0) as cantidad,
               ROUND(SUM(venta_bruta), 0) as venta
        FROM ventas
        WHERE fecha_venta >= '{desde}' AND tipo_movimiento = 'Venta'
        GROUP BY sku, canal, tipo_negocio
    """
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    r = requests.post(
        f"{url}/v2/pipeline",
        json=body,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        timeout=300,
    )
    r.raise_for_status()
    rows = r.json()['results'][0]['response']['result']['rows']
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{
        'SKU': row[0]['value'],
        'Canal': row[1]['value'],
        'Tipo Negocio': row[2]['value'],
        'Cantidad': float(row[3]['value']) if row[3]['value'] else 0,
        'Venta': float(row[4]['value']) if row[4]['value'] else 0,
    } for row in rows])


# ============================================================
# Filtros sidebar (compartidos para vistas de Ventas)
# ============================================================
def render_filters_sidebar(prefix="ventas"):
    """Renderiza filtros en sidebar y devuelve dict {canal, marca, categoria, tipo_negocio, kam}."""
    filtros_disp = cached_filtros()

    st.sidebar.title("🎛️ Filtros")
    f_categoria = st.sidebar.selectbox(
        "Categoría", ["(Todas)"] + filtros_disp['categorias'], key=f"{prefix}_cat",
    )
    f_marca = st.sidebar.selectbox(
        "Marca", ["(Todas)"] + filtros_disp['marcas'], key=f"{prefix}_marca",
    )
    f_tipo_negocio = st.sidebar.selectbox(
        "Línea de Negocio", ["(Todas)"] + filtros_disp['tipos_negocio'], key=f"{prefix}_tn",
    )
    f_kam = st.sidebar.selectbox(
        "KAM", ["(Todos)"] + filtros_disp.get('kams', []), key=f"{prefix}_kam",
    )
    f_canal = st.sidebar.selectbox(
        "Canal de Venta", ["(Todos)"] + filtros_disp['canales'], key=f"{prefix}_canal",
    )

    f = {
        'canal': None if f_canal.startswith("(") else f_canal,
        'marca': None if f_marca.startswith("(") else f_marca,
        'categoria': None if f_categoria.startswith("(") else f_categoria,
        'tipo_negocio': None if f_tipo_negocio.startswith("(") else f_tipo_negocio,
        'kam': None if f_kam.startswith("(") else f_kam,
    }

    activos = [f"{k}={v}" for k, v in f.items() if v]
    if activos:
        st.sidebar.info("**Activos:** " + ", ".join(activos))

    st.sidebar.divider()
    if st.sidebar.button("🔄 Refrescar caché", use_container_width=True, key=f"{prefix}_refrescar"):
        st.cache_data.clear()
        st.rerun()
    if st.sidebar.button("⚡ Forzar sync desde Turso", use_container_width=True, key=f"{prefix}_force"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

    return f


def render_health_header(title: str):
    """Header con título + última sincronización (común a vistas de ventas)."""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title(title)
        st.caption("Análisis YoY (Year over Year) — Venta Bruta CON IVA, Margen Frontal vs Venta Neta")

    with col2:
        health = cached_health()
        atraso = health.get('atraso_horas')
        if atraso is not None:
            if atraso < 1:
                atraso_min = max(0, int(round(atraso * 60)))
                atraso_txt = f"{atraso_min} min"
                emoji = '🟢'
            elif atraso < 24:
                atraso_txt = f"{atraso}h"
                emoji = '🟢' if atraso < 2 else '🟡'
            else:
                atraso_txt = f"{atraso}h"
                emoji = '🔴'
        else:
            atraso_txt = "?"
            emoji = '⚪'

        ultima = health.get('ultima_carga')
        ultima_txt = "-"
        if ultima:
            try:
                d = datetime.fromisoformat(ultima)
                ultima_txt = d.strftime('%H:%M:%S')
            except Exception:
                ultima_txt = ultima[:19]

        st.metric(
            "Última sincronización",
            f"{emoji} {ultima_txt}",
            delta=f"hace {atraso_txt} | DB: {fmt_int(health.get('filas_total', 0))} filas",
        )
    return health
