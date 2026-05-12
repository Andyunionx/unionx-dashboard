"""
Dashboard UnionX — APP CONTABILIDAD.

Entry point dedicado al área Contabilidad. Automatiza 2 flujos:
  💰 Cobranza        → documentos pendientes + cruce pagos + reporte CxC
  📊 Centro Costos   → libro compras + memoria cuentas + cartolas → Odoo

Despliegue Streamlit Cloud: unionx-contabilidad.streamlit.app
Secrets: CONT_ALLOWED_EMAILS, CONT_COOKIE_SECRET, ODOO_*
"""
import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

for _key in ("LIBSQL_URL", "LIBSQL_AUTH_TOKEN", "OPS_ODOO_USER",
              "OPS_ODOO_PASSWORD", "ANDRES_ODOO_PASSWORD",
              "ODOO_URL", "ODOO_DB", "CONT_COOKIE_SECRET"):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

if not os.environ.get("ANDRES_ODOO_PASSWORD") and os.environ.get("OPS_ODOO_PASSWORD"):
    os.environ["ANDRES_ODOO_PASSWORD"] = os.environ["OPS_ODOO_PASSWORD"]

st.set_page_config(
    page_title="UnionX Contabilidad",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Sidebar marrón/dorado para diferenciar de otras apps
st.markdown("""
<style>
    .main .block-container {padding: 1.2rem 1.5rem 1rem 1.5rem; max-width: 100%;}
    section[data-testid="stSidebar"] {background: linear-gradient(180deg, #44403C 0%, #1C1917 100%); width: 270px !important;}
    section[data-testid="stSidebar"] * {color: #FEF3C7 !important;}
    section[data-testid="stSidebar"] hr {border-color: rgba(255,255,255,0.1) !important;}
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .stDeployButton {display: none;}
</style>
""", unsafe_allow_html=True)


with st.sidebar:
    st.markdown("## 📚 **UnionX Contabilidad**")
    st.caption("Cobranza · Centro de Costos")
    st.divider()

from views._cont_auth import require_login_cont, get_cont_user, logout_cont  # noqa
require_login_cont()

with st.sidebar:
    user = get_cont_user()
    if user:
        st.caption(f"👤 {user['email']}")
        if st.button("Cerrar sesión", use_container_width=True, key="cont_logout"):
            logout_cont()
    st.divider()


# ─── NAVEGACIÓN ──────────────────────────────────────────────────────
from views.cont_cobranza import render as render_cont_cobranza  # noqa
from views.cont_centro_costos import render as render_cont_cc  # noqa

pages = {
    "💰 Cobranza": [
        st.Page(render_cont_cobranza, title="Documentos · Pagos · CxC", icon="💰",
                url_path="cont-cobranza", default=True),
    ],
    "📊 Centro de Costos": [
        st.Page(render_cont_cc, title="Libro Compras · Memoria · Odoo", icon="📊",
                url_path="cont-centro-costos"),
    ],
}

pg = st.navigation(pages)
pg.run()
