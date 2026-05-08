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
    st.divider()

# Auto-refresh cada 5 min via JS
st.markdown(
    """<script>setTimeout(function(){window.location.reload();}, 300000);</script>""",
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
from views.contribucion_detalle import render as render_contrib_detalle
from views.sistema_alertas import render as render_sistema_alertas
from views.sistema_seguridad import render as render_sistema_seguridad

pages = {
    "📊 Ventas": [
        st.Page(render_ventas_general, title="Vista General", icon="📈", url_path="ventas-general", default=True),
        st.Page(render_ventas_semanal, title="Vista Semanal", icon="📅", url_path="ventas-semanal"),
        st.Page(render_ventas_descarga, title="Descargar RAW", icon="⬇️", url_path="ventas-descarga"),
        st.Page(render_ventas_carga, title="Cargar offline", icon="📤", url_path="ventas-carga"),
    ],
    "📦 Stock": [
        st.Page(render_stock_live, title="Stock LIVE", icon="📦", url_path="stock-live"),
    ],
    "💼 Contribución": [
        st.Page(render_contrib_general, title="Vista General", icon="📊", url_path="contrib-general"),
        st.Page(render_contrib_meta, title="Meta vs Resultado", icon="🎯", url_path="contrib-meta"),
        st.Page(render_contrib_kam, title="Por KAM", icon="👤", url_path="contrib-kam"),
        st.Page(render_contrib_detalle, title="Análisis detallado", icon="🔬", url_path="contrib-detalle"),
    ],
    "🔄 Análisis cruzado": [
        st.Page(render_cruce_bestsellers, title="Bestsellers", icon="🔥", url_path="cruce-bestsellers"),
        st.Page(render_cruce_quiebres, title="Quiebres con demanda", icon="🚨", url_path="cruce-quiebres"),
        st.Page(render_cruce_sobrestock, title="Sobrestock", icon="💰", url_path="cruce-sobrestock"),
        st.Page(render_cruce_cobertura, title="Cobertura por canal", icon="📊", url_path="cruce-cobertura"),
        st.Page(render_cruce_rotacion, title="Rotación inventario", icon="📈", url_path="cruce-rotacion"),
    ],
    "⚙️ Sistema": [
        st.Page(render_sistema_alertas, title="Alertas", icon="🚨", url_path="sistema-alertas"),
        st.Page(render_sistema_seguridad, title="Seguridad", icon="🔐", url_path="sistema-seguridad"),
    ],
}

pg = st.navigation(pages)
pg.run()
