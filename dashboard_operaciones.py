"""
Dashboard UnionX — APP OPERACIONES.

Entry point dedicado al área Operaciones (COMEX, Fulfillment ops, Post-venta,
SAC, Logística, Costo Operativo). Repo compartido con la app de Ventas pero
deploy y secrets independientes.

Diferencias clave vs dashboard_ventas.py:
  - Auth: SSO contra Odoo (no streamlit_authenticator)
    El user ingresa su email+password de Odoo. Se valida con Odoo XML-RPC.
    Solo emails en OPS_ALLOWED_EMAILS pueden entrar.
  - Odoo: usa OPS_ODOO_USER + OPS_ODOO_PASSWORD (cuenta servicio para datos)
  - Navegación: secciones Ops del Plan Estratégico Unificado 2026-2028
"""
import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

# Streamlit Cloud: exponer secretos como env vars del SO para el resto del código
for _key in (
    "LIBSQL_URL",
    "LIBSQL_AUTH_TOKEN",
    "OPS_ODOO_USER",
    "OPS_ODOO_PASSWORD",
    "ODOO_URL",
    "ODOO_DB",
    # gcp_service_account es struct, se accede por st.secrets directo
):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

# Alias: views/shared.py (compartido con app Ventas) busca ANDRES_ODOO_PASSWORD.
# En la app Operaciones usamos OPS_ODOO_PASSWORD pero apunta al mismo Odoo,
# así que copiamos el valor a la env var que el código compartido espera.
if not os.environ.get("ANDRES_ODOO_PASSWORD") and os.environ.get("OPS_ODOO_PASSWORD"):
    os.environ["ANDRES_ODOO_PASSWORD"] = os.environ["OPS_ODOO_PASSWORD"]

st.set_page_config(
    page_title="UnionX Operaciones",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# AUTENTICACIÓN — SSO Odoo
# ============================================================
with st.sidebar:
    st.markdown("## 🚢 **UnionX Operaciones**")
    st.caption("Plan Estratégico 2026-2028")
    st.divider()

from views._ops_auth import require_login_ops  # noqa: E402

# Bloquea hasta que el user haga login con sus credenciales Odoo
require_login_ops()

# Indicador de estado Odoo OPS (sidebar)
from views._ops_odoo_helper import odoo_status_indicator  # noqa: E402
odoo_status_indicator()

# Auto-refresh DESACTIVADO (causaba re-render completo cada 5 min, sensación
# de "corriendo todo el rato"). El user puede refrescar manualmente con el
# botón "🔄 Refrescar Odoo" del sidebar de cada vista, o F5 del browser.
# Cache TTL de 5-15 min en helpers Odoo ya garantiza datos relativamente frescos.


# ============================================================
# NAVEGACIÓN JERÁRQUICA — secciones del Plan Operaciones
# ============================================================
from views.ops_comex import render as render_ops_comex
from views.ops_cyber_planner import render as render_ops_cyber
from views.ops_stock_live import render as render_ops_stock_live
from views.ops_wms_kpis import render as render_ops_wms
from views.ops_postventa import render as render_ops_postventa
from views.ops_sac import render as render_ops_sac
from views.ops_logistica import render as render_ops_logistica
from views.ops_costo_operativo import render as render_ops_costo
from views.ops_plan_estrategico import render as render_ops_plan
from views.sistema_alertas import render as render_sistema_alertas
from views.sistema_seguridad import render as render_sistema_seguridad
from views.alertas_negocio import render_ops as render_alertas_negocio_ops
from views.ops_asistente import render as render_ops_asistente

pages = {
    "🤖 Asistente IA": [
        st.Page(render_ops_asistente, title="Pregúntame", icon="🤖",
                url_path="ops-asistente"),
    ],
    "🚢 COMEX": [
        st.Page(render_ops_comex, title="Embarques activos", icon="📦",
                url_path="ops-comex", default=True),
    ],
    "📦 Fulfillment": [
        st.Page(render_ops_stock_live, title="Stock LIVE Operacional", icon="📦",
                url_path="ops-stock-live"),
        st.Page(render_ops_wms, title="KPIs WMS", icon="🎯",
                url_path="ops-wms-kpis"),
        st.Page(render_ops_costo, title="Costo Operativo Total", icon="💰",
                url_path="ops-costo-operativo"),
        st.Page(render_ops_cyber, title="Planificador Cyber / Peak Season", icon="🎯",
                url_path="ops-cyber-planner"),
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
    "🔔 Alertas": [
        st.Page(render_alertas_negocio_ops, title="Negocio", icon="🔔",
                url_path="ops-alertas-negocio"),
    ],
    "⚙️ Sistema": [
        st.Page(render_sistema_alertas, title="Salud servicios", icon="🚨",
                url_path="ops-sistema-alertas"),
        st.Page(render_sistema_seguridad, title="Seguridad", icon="🔐",
                url_path="ops-sistema-seguridad"),
    ],
}

pg = st.navigation(pages)
pg.run()
