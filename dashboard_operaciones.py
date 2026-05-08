"""
Dashboard UnionX — APP OPERACIONES.

Entry point dedicado al área Operaciones (COMEX, Fulfillment ops, Post-venta,
SAC, Logística, Costo Operativo). Repo compartido con la app de Ventas pero
deploy y secrets independientes.

Diferencias clave vs dashboard_ventas.py:
  - Auth propio: el secret 'auth' acá lista usuarios del equipo Ops
  - Odoo dual: usa OPS_ODOO_USER + OPS_ODOO_PASSWORD (no ANDRES_*)
  - Navegación: secciones Ops del Plan Estratégico Unificado 2026-2028
"""
import os
import sys
from pathlib import Path

import streamlit as st
import streamlit_authenticator as stauth
import yaml

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

# Streamlit Cloud: exponer secretos como env vars del SO para el resto del código
for _key in (
    "LIBSQL_URL",
    "LIBSQL_AUTH_TOKEN",
    "OPS_ODOO_USER",
    "OPS_ODOO_PASSWORD",
    # gcp_service_account es struct, se accede por st.secrets directo
):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

st.set_page_config(
    page_title="UnionX Operaciones",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# AUTENTICACIÓN (mismo patrón que dashboard_ventas.py)
# ============================================================
def _to_plain(obj):
    if hasattr(obj, "items") and not isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


def _load_auth_config():
    if "auth" in st.secrets:
        return _to_plain(st.secrets["auth"])
    cfg_path = PROJECT_ROOT / "auth_config.yaml"
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return None


auth_config = _load_auth_config()
if not auth_config:
    st.error("No hay configuración de autenticación.")
    st.stop()

authenticator = stauth.Authenticate(
    auth_config["credentials"],
    auth_config["cookie"]["name"],
    auth_config["cookie"]["key"],
    auth_config["cookie"]["expiry_days"],
)
try:
    authenticator.login(location="main", key="login_main_ops")
except Exception:
    pass

if st.session_state.get("authentication_status") is False:
    st.error("Usuario o contraseña incorrectos")
    st.stop()
elif st.session_state.get("authentication_status") is None:
    st.warning("Por favor ingresa tu usuario y contraseña")
    st.stop()

# Autenticado
with st.sidebar:
    st.markdown("## 🚢 **UnionX Operaciones**")
    st.caption("Plan Estratégico 2026-2028")
    st.divider()
    authenticator.logout("Cerrar sesión", "sidebar")
    st.write(f"👤 **{st.session_state.get('name', '')}**")
    st.divider()

# Indicador de estado Odoo OPS (sidebar)
from views._ops_odoo_helper import odoo_status_indicator  # noqa: E402
odoo_status_indicator()

# Auto-refresh cada 5 min
st.markdown(
    """<script>setTimeout(function(){window.location.reload();}, 300000);</script>""",
    unsafe_allow_html=True,
)


# ============================================================
# NAVEGACIÓN JERÁRQUICA — secciones del Plan Operaciones
# ============================================================
from views.ops_comex import render as render_ops_comex
from views.ops_fulfillment_ops import render as render_ops_fulfillment
from views.ops_postventa import render as render_ops_postventa
from views.ops_sac import render as render_ops_sac
from views.ops_logistica import render as render_ops_logistica
from views.ops_costo_operativo import render as render_ops_costo
from views.ops_plan_estrategico import render as render_ops_plan
from views.sistema_alertas import render as render_sistema_alertas
from views.sistema_seguridad import render as render_sistema_seguridad

# Reutilizamos Stock LIVE de la app Ventas (mismo módulo, diferente sesión)
from views.stock_live import render as render_stock_live

pages = {
    "🚢 COMEX": [
        st.Page(render_ops_comex, title="Embarques activos", icon="📦",
                url_path="ops-comex", default=True),
    ],
    "📦 Fulfillment": [
        st.Page(render_stock_live, title="Stock LIVE", icon="📦",
                url_path="ops-stock-live"),
        st.Page(render_ops_fulfillment, title="Operación bodega", icon="🎯",
                url_path="ops-fulfillment"),
        st.Page(render_ops_costo, title="Costo Operativo Total", icon="💰",
                url_path="ops-costo-operativo"),
    ],
    "↩️ Post-venta": [
        st.Page(render_ops_postventa, title="Devoluciones & SERNAC", icon="↩️",
                url_path="ops-postventa"),
    ],
    "💬 SAC": [
        st.Page(render_ops_sac, title="Servicio al Cliente", icon="💬",
                url_path="ops-sac"),
    ],
    "🚚 Logística": [
        st.Page(render_ops_logistica, title="Despacho & Couriers", icon="🚚",
                url_path="ops-logistica"),
    ],
    "📋 Plan Estratégico": [
        st.Page(render_ops_plan, title="Roadmap H1/H2/H3", icon="📋",
                url_path="ops-plan"),
    ],
    "⚙️ Sistema": [
        st.Page(render_sistema_alertas, title="Alertas", icon="🚨",
                url_path="ops-sistema-alertas"),
        st.Page(render_sistema_seguridad, title="Seguridad", icon="🔐",
                url_path="ops-sistema-seguridad"),
    ],
}

pg = st.navigation(pages)
pg.run()
