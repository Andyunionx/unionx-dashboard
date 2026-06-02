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
MES_ACTUAL_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
CUTOFF_HISTORICO = '2026-06-02'  # 1-jun foto fija en histórico parquet; Turso solo desde 2-jun


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
@st.cache_resource(show_spinner=False)
def _read_historico_parquet():
    """Lectura del parquet histórico (no cambia día a día).
    cache_resource: zero overhead vs cache_data que serializa el DataFrame en cada acceso.
    """
    if not HISTORICO_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(HISTORICO_PARQUET)
    print(f"[historico_parquet] {len(df):,} filas cargadas desde {HISTORICO_PARQUET.name}", flush=True)
    return df


# Path estable del SQLite local (mtime-based invalidation, no depende de cache_resource ttl).
_LOCAL_DB_PATH = Path(tempfile.gettempdir()) / 'unionx_dashboard_local_v4.db'
_LOCAL_DB_TTL_S = 900  # 15 min


def get_local_db_path():
    """SQLite local combinando histórico (parquet) + live (Turso).

    Estrategia de invalidación:
    1. Por mtime del archivo (>15 min → rebuild)
    2. Por contenido: si estamos en Cyber pero el SQLite no tiene venta de
       hoy/junio, está stale → rebuild forzado.
    """
    if not os.environ.get('LIBSQL_URL'):
        return str(DB_PATH)

    if _LOCAL_DB_PATH.exists():
        age = _time.time() - _LOCAL_DB_PATH.stat().st_mtime
        if age < _LOCAL_DB_TTL_S:
            # Validar contenido: si estamos en Cyber, verificar que tenga junio
            hoy_str = datetime.now().strftime('%Y-%m-%d')
            if '2026-06-01' <= hoy_str <= '2026-06-06':
                try:
                    _c = sqlite3.connect(str(_LOCAL_DB_PATH))
                    venta_jun = _c.execute(
                        "SELECT COALESCE(SUM(venta_bruta),0) FROM ventas WHERE fecha_venta >= '2026-06-01'"
                    ).fetchone()[0]
                    _c.close()
                    if venta_jun < 1_000_000:
                        print(f"[Local DB] Cache stale (junio ${venta_jun:,.0f} < $1M), rebuild", flush=True)
                        try:
                            _LOCAL_DB_PATH.unlink()
                        except Exception:
                            pass
                        return _build_local_db()
                except Exception as e:
                    print(f"[Local DB] Validate cache failed: {e}", flush=True)
            return str(_LOCAL_DB_PATH)

    return _build_local_db()


def _build_local_db():
    """Construye el SQLite local desde histórico parquet + Turso live."""
    if not os.environ.get('LIBSQL_URL'):
        return str(DB_PATH)

    import time as _t
    build_started = _t.time()

    print(f"[Local DB] Build {datetime.now()}", flush=True)

    libsql_url = os.environ['LIBSQL_URL'].rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    def turso_query(sql, retries=3, timeout_s=90):
        body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
        last = None
        for i in range(retries):
            try:
                r = requests.post(f"{libsql_url}/v2/pipeline", json=body, headers=headers, timeout=timeout_s)
                r.raise_for_status()
                return r.json()['results'][0]['response']['result']
            except (requests.exceptions.RequestException, KeyError) as e:
                last = e
                _t.sleep(1 + i * 2)  # 1s, 3s, 5s
        raise last

    # Usar path estable v4 (mtime-based invalidation)
    tmp_path = _LOCAL_DB_PATH
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

    def _normalize_fecha_venta(df: pd.DataFrame) -> pd.DataFrame:
        """Convierte fecha_venta a string YYYY-MM-DD (sin timestamp) para que
        queries con BETWEEN '2026-05-01' AND '2026-05-25' incluyan el día 25."""
        if 'fecha_venta' in df.columns:
            df = df.copy()
            df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
        return df

    # Parquet histórico (cacheado por separado para no re-leerlo si invalida la DB local)
    df_hist = _read_historico_parquet()
    if not df_hist.empty:
        print(f"[Local DB] Insertando {len(df_hist):,} filas histórico parquet...", flush=True)
        df_hist = _normalize_fecha_venta(df_hist)
        df_hist[cols_v].to_sql('ventas', conn, if_exists='append', index=False, chunksize=5000, method='multi')
        print(f"[Local DB] Histórico insertado OK", flush=True)

    # Mes actual: SIEMPRE desde Turso para reflejar últimos cambios (NCs retro, facturas
    # manuales, inserts del Task Scheduler de 5min). Una sola query ~4-5s para ~11K filas.
    # Parquet pre-generado por GH Actions queda como fallback si Turso falla.
    turso_rows_loaded = 0
    chunks_turso = 0
    turso_error = None
    try:
        result = turso_query(
            f"SELECT {cols_csv} FROM ventas WHERE fecha_venta >= '{CUTOFF_HISTORICO}'"
        )
        rows = result['rows']
        if rows:
            flat = [tuple(c.get('value') if isinstance(c, dict) else c for c in r) for r in rows]
            conn.executemany(insert_sql, flat)
            conn.commit()
            turso_rows_loaded = len(rows)
            chunks_turso = 1
            print(f"[Local DB] Mes actual Turso: {len(rows):,} filas", flush=True)
    except Exception as e:
        turso_error = f"{type(e).__name__}: {str(e)[:120]}"
        print(f"[Local DB][WARN] Turso fallo ({turso_error}), intentando parquet fallback...", flush=True)
        if MES_ACTUAL_PARQUET.exists():
            try:
                df_mes = pd.read_parquet(MES_ACTUAL_PARQUET)
                df_mes = _normalize_fecha_venta(df_mes)
                df_mes[cols_v].to_sql('ventas', conn, if_exists='append', index=False, chunksize=500, method='multi')
                turso_rows_loaded = len(df_mes)
                chunks_turso = 1
                print(f"[Local DB] Fallback parquet: {len(df_mes):,} filas (hasta {df_mes['fecha_venta'].max()})", flush=True)
            except Exception as e2:
                print(f"[Local DB][WARN] Fallback parquet también falló: {type(e2).__name__}", flush=True)

    # dim_productos + metadata (con fallback)
    cols_p = ['sku', 'producto', 'categoria_macro', 'categoria_padre', 'categoria_hijo',
              'categoria_comercial', 'estado_sku', 'pack', 'marca', 'proveedor', 'tipo_marca', 'tipo_compra']
    try:
        result = turso_query(f"SELECT {','.join(cols_p)} FROM dim_productos")
        rows = result['rows']
        if rows:
            flat = [tuple(c.get('value') if isinstance(c, dict) else c for c in r) for r in rows]
            conn.executemany(
                f"INSERT OR IGNORE INTO dim_productos ({','.join(cols_p)}) VALUES ({','.join(['?']*len(cols_p))})",
                flat,
            )
    except Exception as e:
        print(f"[Local DB][WARN] dim_productos: {type(e).__name__}", flush=True)

    cols_m = ['fecha_carga', 'fuente', 'filas_cargadas', 'fecha_min_datos', 'fecha_max_datos', 'tipo']
    try:
        result = turso_query(f"SELECT {','.join(cols_m)} FROM metadata_cargas")
        rows = result['rows']
        if rows:
            flat = [tuple(c.get('value') if isinstance(c, dict) else c for c in r) for r in rows]
            conn.executemany(
                f"INSERT INTO metadata_cargas ({','.join(cols_m)}) VALUES ({','.join(['?']*len(cols_m))})",
                flat,
            )
            conn.commit()
    except Exception as e:
        print(f"[Local DB][WARN] metadata_cargas: {type(e).__name__}", flush=True)

    # Stats finales
    n_ventas = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
    max_fecha = conn.execute("SELECT MAX(fecha_venta) FROM ventas").fetchone()[0]

    # VALIDACIÓN: si estamos en Cyber (1-jun a 6-jun 2026), el mes actual debe
    # tener venta. Si la query a Turso devolvió 0 (sync en curso), no servir
    # este SQLite vacío — borrarlo para que la próxima request lo reconstruya.
    hoy_str = datetime.now().strftime('%Y-%m-%d')
    if '2026-06-01' <= hoy_str <= '2026-06-06':
        venta_hoy = conn.execute(
            "SELECT COALESCE(SUM(venta_bruta),0) FROM ventas WHERE fecha_venta >= '2026-06-01'"
        ).fetchone()[0]
        if venta_hoy < 1_000_000:  # menos de $1M en junio = data parcial probable
            print(f"[Local DB] WARN: venta junio {venta_hoy:,.0f} < $1M — Turso sync probable. "
                  f"Borrando SQLite y reintentando.", flush=True)
            conn.close()
            try:
                tmp_path.unlink()
            except Exception:
                pass
            # Reintentar UNA vez después de 10s (espera que termine sync Turso)
            _t.sleep(10)
            return _build_local_db()

    print(f"[Local DB] BUILD COMPLETO: {n_ventas:,} filas, max fecha {max_fecha}", flush=True)

    # Guardar stats para que el sidebar las muestre
    global _DB_BUILD_STATS
    _DB_BUILD_STATS = {
        'filas_total': n_ventas,
        'filas_historico': len(df_hist) if not df_hist.empty else 0,
        'filas_turso': turso_rows_loaded,
        'chunks_turso': chunks_turso,
        'turso_error': turso_error,
        'max_fecha': max_fecha,
        'build_duration_s': round(_t.time() - build_started, 1),
        'built_at': datetime.now().isoformat(timespec='seconds'),
        'local_path': str(tmp_path),
    }
    conn.close()
    return str(tmp_path)


_DB_BUILD_STATS: dict = {}


def get_db_build_stats() -> dict:
    """Stats del último build del SQLite local. Vacío si nunca se construyó."""
    return dict(_DB_BUILD_STATS)


def force_refresh_db_local():
    """Limpia TODOS los caches y borra archivo SQLite local para forzar reconstrucción."""
    # Borrar archivo físico → próxima llamada a get_local_db_path() rebuild
    try:
        if _LOCAL_DB_PATH.exists():
            _LOCAL_DB_PATH.unlink()
    except Exception:
        pass
    cached_health.clear()
    cached_filtros.clear()
    try:
        _cached_kpis_inner.clear()
        cached_mensual.clear()
        cached_diaria.clear()
        _cached_semanal_inner.clear()
        _cached_canales_inner.clear()
        _cached_top_skus_inner.clear()
    except Exception:
        pass


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
@st.cache_data(ttl=600)
def cached_filtros():
    return get_service().get_filtros_disponibles()


def _params_from_filtros(desde, hasta, f: dict | None = None) -> dict:
    """Construye el dict de params para los métodos del service desde dict de filtros."""
    p = {'fecha_desde': desde, 'fecha_hasta': hasta}
    if not f:
        return p
    for k in ('canal', 'marca', 'categoria_padre', 'categoria_hijo',
              'tipo_negocio', 'kam', 'producto', 'sku'):
        v = f.get(k)
        if v:
            p[k] = v
    if f.get('categoria'):  # backward compat
        p['categoria'] = f['categoria']
    return p


def _filtros_to_key(f: dict | None) -> str:
    """Serializa filtros a string estable para cache key."""
    import json
    if not f:
        return ""
    # Ordenar para que el orden no afecte el hash
    return json.dumps(f, sort_keys=True, default=str)


@st.cache_data(ttl=60)
def _cached_kpis_inner(desde, hasta, key_filtros):
    import json
    f = json.loads(key_filtros) if key_filtros else {}
    return get_service().get_kpis_yoy(_params_from_filtros(desde, hasta, f))


def cached_kpis(desde, hasta, filtros: dict | None = None):
    return _cached_kpis_inner(desde, hasta, _filtros_to_key(filtros))


@st.cache_data(ttl=60)
def cached_mensual():
    return get_service().get_tendencia_mensual_yoy()


@st.cache_data(ttl=60)
def cached_diaria(anio, mes):
    return get_service().get_tendencia_diaria_yoy(anio, mes)


@st.cache_data(ttl=60)
def _cached_semanal_inner(anio, mes, key_filtros):
    import json
    f = json.loads(key_filtros) if key_filtros else {}
    return get_service().get_tendencia_semanal_yoy(anio, mes, _params_from_filtros(None, None, f))


def cached_semanal(anio, mes, filtros: dict | None = None):
    return _cached_semanal_inner(anio, mes, _filtros_to_key(filtros))


@st.cache_data(ttl=60)
def _cached_canales_inner(desde, hasta, key_filtros):
    import json
    f = json.loads(key_filtros) if key_filtros else {}
    return get_service().get_por_canal_yoy(_params_from_filtros(desde, hasta, f))


def cached_canales(desde, hasta, filtros: dict | None = None):
    return _cached_canales_inner(desde, hasta, _filtros_to_key(filtros))


@st.cache_data(ttl=60)
def _cached_top_skus_inner(desde, hasta, key_filtros, limit):
    import json
    f = json.loads(key_filtros) if key_filtros else {}
    return get_service().get_top_skus_yoy(_params_from_filtros(desde, hasta, f), limit=limit)


def cached_top_skus(desde, hasta, filtros: dict | None = None, limit: int = 20):
    return _cached_top_skus_inner(desde, hasta, _filtros_to_key(filtros), limit)


@st.cache_data(ttl=600)
def cached_health():
    """Health check. Si Turso/servicio cuelga, devuelve degraded en lugar de crashear."""
    try:
        return get_service().health()
    except Exception as e:
        # ReadTimeout, ConnectionError, etc → no romper el dashboard
        return {
            'status': 'degraded',
            'error': type(e).__name__,
            'message': str(e)[:120],
            'fuente': 'fallback',
        }


# ============================================================
# Stock LIVE (cache 5 min)
# ============================================================
STOCK_DIR = PROJECT_ROOT / 'data' / 'stock'


@st.cache_data(ttl=900, show_spinner="Cargando snapshot de stock…")
def cached_stock():
    """
    Stock LIVE: prefiere parquets pre-computados (rápido <1s) sobre Odoo (30-60s).
    Los parquets se actualizan cada 3h vía GH Actions sync_stock.yml.
    Si no hay parquets, fallback a Odoo en vivo.
    """
    import json

    skus_path = STOCK_DIR / 'skus.parquet'
    detalle_path = STOCK_DIR / 'detalle.parquet'
    meta_path = STOCK_DIR / 'metadata.json'

    if skus_path.exists() and meta_path.exists():
        # Modo rápido: leer parquets
        df_skus = pd.read_parquet(skus_path)
        df_detalle = pd.read_parquet(detalle_path) if detalle_path.exists() else pd.DataFrame()
        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)

        return {
            'metadata': {
                'generado_en': meta.get('generado_en'),
                'total_skus': meta.get('total_skus', 0),
                'total_quants': meta.get('total_quants', 0),
                'total_locations': meta.get('total_locations', 0),
            },
            'kpis': meta.get('kpis', {}),
            'ocupacion': meta.get('ocupacion', {}),
            'semaforo': meta.get('semaforo', []),
            'valor_bodega': meta.get('valor_bodega', []),
            'skus': df_skus.to_dict(orient='records'),
            'detalle': df_detalle.to_dict(orient='records') if not df_detalle.empty else [],
        }

    # Fallback: consultar Odoo en vivo
    from app.services.stock_advanced_service import StockAdvancedService
    from app.core.odoo_client import OdooClient

    odoo_password = (
        st.secrets.get('ANDRES_ODOO_PASSWORD')
        or os.environ.get('ANDRES_ODOO_PASSWORD')
    )
    if not odoo_password:
        raise RuntimeError(
            "Sin parquet en data/stock/ y ANDRES_ODOO_PASSWORD no seteado. "
            "Esperar 1ra ejecución del workflow sync_stock.yml o configurar secret."
        )

    odoo = OdooClient(
        url='https://unionxb2b.odoo.com',
        db='bmya-innovatek-sh-prd-6981800',
        username='andres@grupoeter.cl',
        password=str(odoo_password),
    )
    return StockAdvancedService(odoo).extract_full(progress_callback=None)


@st.cache_data(ttl=900, show_spinner="Consultando ventas por canal últimos 30 días…")
def cached_ventas_canal_30d():
    """Ventas últimos 30 días por SKU+canal.
    Estrategia: Turso primero (más fresco), fallback parquet local si Turso falla."""
    desde = (datetime.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')

    # Intento 1: Turso (más fresco)
    url = os.environ.get('LIBSQL_URL', '').rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    if url:
        sql = f"""
            SELECT sku, canal, tipo_negocio,
                   ROUND(SUM(cantidad), 0) as cantidad,
                   ROUND(SUM(venta_bruta), 0) as venta
            FROM ventas
            WHERE fecha_venta >= '{desde}' AND tipo_movimiento = 'Venta'
            GROUP BY sku, canal, tipo_negocio
        """
        try:
            body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
            r = requests.post(
                f"{url}/v2/pipeline", json=body,
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                timeout=300,
            )
            r.raise_for_status()
            rows = r.json()['results'][0]['response']['result']['rows']
            if rows:
                return pd.DataFrame([{
                    'SKU': row[0]['value'],
                    'Canal': row[1]['value'],
                    'Tipo Negocio': row[2]['value'],
                    'Cantidad': float(row[3]['value']) if row[3]['value'] else 0,
                    'Venta': float(row[4]['value']) if row[4]['value'] else 0,
                } for row in rows])
        except (KeyError, requests.exceptions.RequestException) as e:
            print(f"[cached_ventas_canal_30d] Turso falló ({type(e).__name__}), fallback parquet", flush=True)

    # Fallback: parquet hist + mes_actual
    try:
        df_hist = _read_historico_parquet()
        df_mes = pd.read_parquet(MES_ACTUAL_PARQUET) if MES_ACTUAL_PARQUET.exists() else pd.DataFrame()
        cols_keep = ['sku', 'canal', 'tipo_negocio', 'cantidad', 'venta_bruta', 'fecha_venta', 'tipo_movimiento']
        parts = [d[cols_keep] for d in (df_hist, df_mes) if not d.empty]
        if not parts:
            return pd.DataFrame()
        df = pd.concat(parts, ignore_index=True)
        df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
        mask = (df['fecha_venta'] >= desde) & (df['tipo_movimiento'] == 'Venta')
        df = df[mask]
        if df.empty:
            return pd.DataFrame()
        g = df.groupby(['sku', 'canal', 'tipo_negocio'], dropna=False).agg(
            cantidad=('cantidad', 'sum'), venta=('venta_bruta', 'sum')
        ).reset_index()
        g['cantidad'] = g['cantidad'].round(0)
        g['venta'] = g['venta'].round(0)
        return g.rename(columns={'sku': 'SKU', 'canal': 'Canal',
                                  'tipo_negocio': 'Tipo Negocio',
                                  'cantidad': 'Cantidad', 'venta': 'Venta'})
    except Exception as e:
        print(f"[cached_ventas_canal_30d] Fallback parquet también falló: {e}", flush=True)
        return pd.DataFrame()


# ============================================================
# Filtros sidebar (compartidos para vistas de Ventas)
# ============================================================
def render_filters_sidebar(prefix="ventas"):
    """[Legacy sidebar] Multi-select en sidebar.
    NOTA: deprecada, usar render_ventas_filters_top() para vista al tope."""
    return render_ventas_filters_top(prefix)


def render_ventas_filters_top(prefix="ventas"):
    """Filtros al tope (multi-select). Dos filas para mejor visibilidad."""
    filtros_disp = cached_filtros()

    st.markdown("##### 🔍 Filtros")

    # Fila 1: KAM, Tipo Negocio, Canal, Marca
    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    with r1c1:
        f_kam = st.multiselect("KAM", filtros_disp.get('kams', []),
                                default=[], key=f"{prefix}_kam")
    with r1c2:
        f_tn = st.multiselect("Línea Negocio", filtros_disp.get('tipos_negocio', []),
                               default=[], key=f"{prefix}_tn")
    with r1c3:
        f_canal = st.multiselect("Canal", filtros_disp.get('canales', []),
                                  default=[], key=f"{prefix}_canal")
    with r1c4:
        f_marca = st.multiselect("Marca", filtros_disp.get('marcas', []),
                                  default=[], key=f"{prefix}_marca")

    # Fila 2: Cat Padre, Cat Hija, Producto, SKU
    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    with r2c1:
        f_cat_padre = st.multiselect("Categoría Padre", filtros_disp.get('categorias_padre', []),
                                      default=[], key=f"{prefix}_catpadre")
    with r2c2:
        f_cat_hijo = st.multiselect("Categoría Hija", filtros_disp.get('categorias_hijo', []),
                                     default=[], key=f"{prefix}_cathijo")
    with r2c3:
        f_producto = st.multiselect("Producto", filtros_disp.get('productos', []),
                                     default=[], key=f"{prefix}_prod",
                                     placeholder="Buscar producto...")
    with r2c4:
        f_sku = st.multiselect("SKU", filtros_disp.get('skus', []),
                                default=[], key=f"{prefix}_sku",
                                placeholder="Buscar SKU...")

    f = {
        'canal': f_canal or None,
        'marca': f_marca or None,
        'categoria_padre': f_cat_padre or None,
        'categoria_hijo': f_cat_hijo or None,
        'tipo_negocio': f_tn or None,
        'kam': f_kam or None,
        'producto': f_producto or None,
        'sku': f_sku or None,
    }

    activos = []
    for k, v in f.items():
        if v:
            if isinstance(v, list):
                activos.append(f"{k}=[{len(v)}]")
            else:
                activos.append(f"{k}={v}")
    if activos:
        st.caption("Filtros activos: " + " · ".join(activos))

    return f


def render_dashboard_actions_sidebar(prefix="ventas"):
    """Botones de acción en sidebar (refrescar / forzar sync)."""
    st.sidebar.divider()
    if st.sidebar.button("🔄 Refrescar caché", use_container_width=True, key=f"{prefix}_refrescar"):
        st.cache_data.clear()
        st.rerun()
    if st.sidebar.button("⚡ Forzar sync desde Turso", use_container_width=True, key=f"{prefix}_force"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()


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
