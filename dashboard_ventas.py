"""
Dashboard UnionX — Entry point con navegación jerárquica.
Auth + st.navigation con secciones: Ventas / Stock / Cruce.
"""
import os
import sys
from pathlib import Path

import streamlit as st
import streamlit_authenticator as stauth
import yaml

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

# Streamlit Cloud: exponer secretos como env vars
for _key in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN', 'ANDRES_ODOO_PASSWORD'):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

st.set_page_config(
    page_title="Dashboard UnionX",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# AUTENTICACIÓN
# ============================================================
def _to_plain(obj):
    """Convierte recursivamente objetos Secrets de Streamlit a dicts/lists planos mutables."""
    if hasattr(obj, 'items') and not isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


def _load_auth_config():
    if 'auth' in st.secrets:
        return _to_plain(st.secrets['auth'])
    cfg_path = PROJECT_ROOT / 'auth_config.yaml'
    if cfg_path.exists():
        with open(cfg_path, encoding='utf-8') as f:
            return yaml.safe_load(f)
    return None


auth_config = _load_auth_config()
if not auth_config:
    st.error("No hay configuración de autenticación.")
    st.stop()

authenticator = stauth.Authenticate(
    auth_config['credentials'],
    auth_config['cookie']['name'],
    auth_config['cookie']['key'],
    auth_config['cookie']['expiry_days'],
)
try:
    authenticator.login(location='main', key='login_main')
except Exception:
    pass

# Audit log: registrar intento de login (success/fail)
try:
    from views.audit import log_login, crear_tabla_audit
    crear_tabla_audit()  # idempotente, primera vez crea
    if st.session_state.get('authentication_status') is True and not st.session_state.get('_audit_logged'):
        log_login(st.session_state.get('username', '?'), exito=True)
        st.session_state['_audit_logged'] = True
    elif st.session_state.get('authentication_status') is False:
        log_login(st.session_state.get('username', '?'), exito=False)
except Exception:
    pass  # No bloquear login si audit falla

if st.session_state.get('authentication_status') is False:
    st.error('Usuario o contraseña incorrectos')
    st.stop()
elif st.session_state.get('authentication_status') is None:
    st.warning('Por favor ingresa tu usuario y contraseña')
    st.stop()

# Autenticado
with st.sidebar:
    authenticator.logout('Cerrar sesión', 'sidebar')
    st.write(f"👤 **{st.session_state.get('name', '')}**")

    # Badge de alertas abiertas (cacheado 5min para no pegar Turso en cada render)
    @st.cache_data(ttl=300, show_spinner=False)
    def _badge_contar_abiertas(target_app: str) -> dict:
        from views.alertas_helper import contar_abiertas, crear_tabla_alertas
        crear_tabla_alertas()
        return contar_abiertas(target_app=target_app)

    try:
        counts = _badge_contar_abiertas('ventas')
        if counts['total'] > 0:
            badge_color = '#DC2626' if counts['critical'] > 0 else '#EA580C' if counts['warning'] > 0 else '#1E40AF'
            partes = []
            if counts['critical']: partes.append(f"🔴 {counts['critical']}")
            if counts['warning']: partes.append(f"🟡 {counts['warning']}")
            if counts['info']: partes.append(f"🔵 {counts['info']}")
            st.markdown(
                f"<div style='background:{badge_color}15;border-left:3px solid {badge_color};padding:6px 10px;border-radius:4px;font-size:0.85rem;'>"
                f"<b>{counts['total']} alertas</b> · {' · '.join(partes)}</div>",
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    # Indicador del estado de la DB local (visible si Turso falló o no cargó)
    try:
        from views.shared import get_db_build_stats, force_refresh_db_local
        stats = get_db_build_stats()
        if stats:
            turso_n = stats.get('filas_turso', 0)
            err = stats.get('turso_error')
            max_f = stats.get('max_fecha', '?')
            if err or turso_n == 0:
                # Diagnóstico extra: contar FAC 097825 (Sodimac) en la DB local
                try:
                    import sqlite3 as _sq
                    local_path = stats.get('local_path', '')
                    if local_path and Path(local_path).exists():
                        _c = _sq.connect(local_path)
                        _has_sodimac = _c.execute("SELECT COUNT(*) FROM ventas WHERE documento='FAC 097825'").fetchone()[0]
                        _total_filas = _c.execute("SELECT COUNT(*) FROM ventas WHERE fecha_venta BETWEEN '2026-05-01' AND '2026-05-31'").fetchone()[0]
                        _bruta_mayo = _c.execute("SELECT ROUND(SUM(venta_bruta),0) FROM ventas WHERE fecha_venta BETWEEN '2026-05-01' AND '2026-05-31'").fetchone()[0] or 0
                        _c.close()
                        _diag = f"<br>📋 Sodimac: {_has_sodimac} | Mayo: {_total_filas:,} filas, ${_bruta_mayo:,.0f}"
                    else:
                        _diag = "<br>(no local_path)"
                except Exception as _e:
                    _diag = f"<br>diag err: {type(_e).__name__}"

                st.markdown(
                    "<div style='background:#FEE2E215;border-left:3px solid #DC2626;"
                    "padding:6px 10px;border-radius:4px;font-size:0.8rem;'>"
                    f"⚠️ <b>Turso no cargó</b><br>"
                    f"Hist: {stats.get('filas_historico',0):,} · Turso: {turso_n:,}<br>"
                    f"Max fecha: {max_f}<br>"
                    f"Built: {stats.get('built_at','?')[-8:]}{_diag}<br>"
                    f"<span style='color:#991B1B'>{(err or '—')[:80]}</span>"
                    "</div>", unsafe_allow_html=True,
                )
            else:
                st.caption(
                    f"📊 DB local: {stats.get('filas_total',0):,} filas · "
                    f"Turso {turso_n:,} en {stats.get('chunks_turso',0)} chunks · "
                    f"max {max_f}"
                )
            if st.button("🔄 Forzar recarga DB", width='stretch', key="force_db_refresh"):
                force_refresh_db_local()
                st.rerun()
    except Exception:
        pass

    st.divider()

# Auto-refresh cada 15 min via JS (alineado con TTL del cache local SQLite).
# Después de 15 min, el cache expiró → reload trae data fresca.
st.markdown(
    """<script>setTimeout(function(){window.location.reload();}, 900000);</script>""",
    unsafe_allow_html=True,
)


# ============================================================
# NAVEGACIÓN JERÁRQUICA
# ============================================================
from views.ventas_general import render as render_ventas_general
from views.ventas_semanal import render as render_ventas_semanal
from views.ventas_carga import render as render_ventas_carga
from views.ventas_descarga import render as render_ventas_descarga
from views.stock_live import render as render_stock_live
from views.cruce_bestsellers import render as render_cruce_bestsellers
from views.cruce_quiebres import render as render_cruce_quiebres
from views.cruce_sobrestock import render as render_cruce_sobrestock
from views.cruce_cobertura import render as render_cruce_cobertura
from views.cruce_rotacion import render as render_cruce_rotacion
from views.contribucion_general import render as render_contrib_general
from views.contribucion_meta import render as render_contrib_meta
from views.contribucion_kam import render as render_contrib_kam
from views.contribucion_comercial_contable import render as render_contrib_comercial_contable
from views.contribucion_conciliacion import render as render_contrib_conciliacion
from views.contribucion_oportunidades import render as render_contrib_oportunidades
from views.contribucion_administracion import render as render_contrib_administracion
from views.sistema_alertas import render as render_sistema_alertas
from views.sistema_seguridad import render as render_sistema_seguridad
from views.alertas_negocio import render as render_alertas_negocio
from views.ops_comex import render as render_comex
from views.ventas_cyber import render as render_ventas_cyber

pages = {
    "📊 Ventas": [
        st.Page(render_ventas_general, title="Vista General", icon="📈", url_path="ventas-general", default=True),
        st.Page(render_ventas_semanal, title="Vista Semanal", icon="📅", url_path="ventas-semanal"),
        st.Page(render_ventas_cyber, title="Cyber 2026", icon="🛍️", url_path="ventas-cyber"),
        st.Page(render_ventas_descarga, title="Descargar RAW", icon="⬇️", url_path="ventas-descarga"),
        st.Page(render_ventas_carga, title="Cargar offline", icon="📤", url_path="ventas-carga"),
    ],
    "📦 Stock": [
        st.Page(render_stock_live, title="Stock LIVE", icon="📦", url_path="stock-live"),
        st.Page(render_comex, title="COMEX en tránsito", icon="🚢", url_path="stock-comex"),
    ],
    "💼 Contribución": [
        st.Page(render_contrib_general, title="Resultados Generales", icon="📊", url_path="contrib-general"),
        st.Page(render_contrib_meta, title="vs Presupuesto", icon="🎯", url_path="contrib-meta"),
        st.Page(render_contrib_comercial_contable, title="Comercial vs Contable", icon="⚖️", url_path="contrib-comercial-contable"),
        st.Page(render_contrib_conciliacion, title="Conciliación", icon="🌉", url_path="contrib-conciliacion"),
        st.Page(render_contrib_kam, title="Vista KAM", icon="👤", url_path="contrib-kam"),
        st.Page(render_contrib_oportunidades, title="Oportunidades", icon="💡", url_path="contrib-oportunidades"),
        st.Page(render_contrib_administracion, title="Administración", icon="🛠️", url_path="contrib-admin"),
    ],
    "🔄 Análisis cruzado": [
        st.Page(render_cruce_bestsellers, title="Bestsellers", icon="🔥", url_path="cruce-bestsellers"),
        st.Page(render_cruce_quiebres, title="Quiebres con demanda", icon="🚨", url_path="cruce-quiebres"),
        st.Page(render_cruce_sobrestock, title="Sobrestock", icon="💰", url_path="cruce-sobrestock"),
        st.Page(render_cruce_cobertura, title="Cobertura por canal", icon="📊", url_path="cruce-cobertura"),
        st.Page(render_cruce_rotacion, title="Rotación inventario", icon="📈", url_path="cruce-rotacion"),
    ],
    "🔔 Alertas": [
        st.Page(render_alertas_negocio, title="Negocio", icon="🔔", url_path="alertas-negocio"),
    ],
    "⚙️ Sistema": [
        st.Page(render_sistema_alertas, title="Salud servicios", icon="🚨", url_path="sistema-salud"),
        st.Page(render_sistema_seguridad, title="Seguridad", icon="🔐", url_path="sistema-seguridad"),
    ],
}

pg = st.navigation(pages)
pg.run()
