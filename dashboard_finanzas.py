"""
Dashboard UnionX — APP FINANZAS.

Entry point dedicado al área Finanzas (Resultados, Caja, Balance & KT,
Planificación, Costos, Alertas financieras). Repo compartido con apps de
Operaciones y Ventas pero deploy y secrets independientes.

Diferencias clave:
  - Auth: SSO contra Odoo (mismo patrón que Operaciones, app aparte)
    El user ingresa su email+password de Odoo. Se valida con Odoo XML-RPC.
    Solo emails en FIN_ALLOWED_EMAILS pueden entrar.
  - Odoo: usa OPS_ODOO_USER + OPS_ODOO_PASSWORD (cuenta servicio para datos)
    o ANDRES_ODOO_PASSWORD (mismo Odoo, distinta cuenta servicio).
  - Navegación: secciones financieras del Plan Estratégico Unificado 2026-2028.

Despliegue Streamlit Cloud:
  - URL sugerida: unionx-finanzas.streamlit.app
  - Secrets propios: FIN_ALLOWED_EMAILS, FIN_COOKIE_SECRET (+ Odoo y Turso compartidos)
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
    "ANDRES_ODOO_PASSWORD",
    "ODOO_URL",
    "ODOO_DB",
    "FIN_COOKIE_SECRET",
):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

# Alias: views/shared.py usa ANDRES_ODOO_PASSWORD; copiar desde OPS si solo está ese.
if not os.environ.get("ANDRES_ODOO_PASSWORD") and os.environ.get("OPS_ODOO_PASSWORD"):
    os.environ["ANDRES_ODOO_PASSWORD"] = os.environ["OPS_ODOO_PASSWORD"]

st.set_page_config(
    page_title="UnionX Finanzas",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS global (mismo estilo que Operaciones)
st.markdown("""
<style>
    .main .block-container {padding: 1.2rem 1.5rem 1rem 1.5rem; max-width: 100%;}
    section[data-testid="stSidebar"] {background: linear-gradient(180deg, #064E3B 0%, #022C22 100%); width: 270px !important;}
    section[data-testid="stSidebar"] * {color: #D1FAE5 !important;}
    section[data-testid="stSidebar"] hr {border-color: rgba(255,255,255,0.1) !important;}
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .stDeployButton {display: none;}
</style>
""", unsafe_allow_html=True)


# ============================================================
# AUTENTICACIÓN — SSO Odoo
# ============================================================
with st.sidebar:
    st.markdown("## 💰 **UnionX Finanzas**")
    st.caption("Plan Estratégico 2026-2028")
    st.divider()

from views._fin_auth import require_login_fin, get_fin_user, logout_fin  # noqa: E402

require_login_fin()

# Indicador de sesión + logout en sidebar
with st.sidebar:
    user = get_fin_user()
    if user:
        st.caption(f"👤 {user['email']}")
        if st.button("Cerrar sesión", use_container_width=True, key="fin_logout"):
            logout_fin()
    st.divider()


# ============================================================
# NAVEGACIÓN JERÁRQUICA — secciones del Plan Finanzas
# ============================================================
from views.fin_ejecutiva import render as render_fin_ejecutiva
from views.fin_resultados import render as render_fin_resultados
from views.fin_caja import render as render_fin_caja
from views.fin_balance_kt import render as render_fin_balance_kt
from views.fin_planificacion import render as render_fin_planificacion
from views.fin_costos import render as render_fin_costos
from views.fin_contribucion import render as render_fin_contribucion
from views.fin_alertas import render as render_fin_alertas
from views.sistema_alertas import render as render_sistema_alertas
from views.sistema_seguridad import render as render_sistema_seguridad

pages = {
    "📊 Vista Ejecutiva": [
        st.Page(render_fin_ejecutiva, title="5 Pilares Estratégicos", icon="🎯",
                url_path="fin-ejecutiva", default=True),
    ],
    "💵 Resultados (P&L)": [
        st.Page(render_fin_resultados, title="P&L Mensual + YTD", icon="💵",
                url_path="fin-resultados"),
        st.Page(render_fin_contribucion, title="Análisis de Contribución", icon="📈",
                url_path="fin-contribucion"),
    ],
    "💧 Caja & Tesorería": [
        st.Page(render_fin_caja, title="Flujo Proyectado 90d", icon="💧",
                url_path="fin-caja"),
    ],
    "🏦 Balance & KT": [
        st.Page(render_fin_balance_kt, title="Balance + Capital de Trabajo", icon="🏦",
                url_path="fin-balance-kt"),
    ],
    "📋 Planificación": [
        st.Page(render_fin_planificacion, title="Real vs Ppto + Forecast cierre", icon="📋",
                url_path="fin-planificacion"),
    ],
    "💸 Costos": [
        st.Page(render_fin_costos, title="EERR clasificado + costos por área", icon="💸",
                url_path="fin-costos"),
    ],
    "🔔 Alertas Finanzas": [
        st.Page(render_fin_alertas, title="Margen, caja, presupuesto", icon="🔔",
                url_path="fin-alertas"),
    ],
    "⚙️ Sistema": [
        st.Page(render_sistema_alertas, title="Salud servicios", icon="🚨",
                url_path="fin-sistema-alertas"),
        st.Page(render_sistema_seguridad, title="Seguridad", icon="🔐",
                url_path="fin-sistema-seguridad"),
    ],
}

pg = st.navigation(pages)
pg.run()
