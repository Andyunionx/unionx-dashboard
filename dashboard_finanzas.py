"""
Dashboard UnionX — APP FINANZAS.

Entry point dedicado al área Finanzas. Lee data/planillas/Planificación
Financiera 2026.xlsx (vía parquets pre-extraídos en data/finanzas/) y
genera dashboards interactivos sin modificar el archivo origen.

Despliegue Streamlit Cloud:
  - URL sugerida: unionx-finanzas.streamlit.app
  - Secrets: FIN_ALLOWED_EMAILS, FIN_COOKIE_SECRET (+ ODOO_*)

Actualización:
  - Andrés modifica el Excel → commit + push
  - Cron `sync_finanzas.yml` corre `extract_finanzas_planificacion.py`
  - Parquets se regeneran → app refresca cache automáticamente
"""
import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

# Streamlit Cloud secrets → env vars
for _key in ("LIBSQL_URL", "LIBSQL_AUTH_TOKEN", "OPS_ODOO_USER",
              "OPS_ODOO_PASSWORD", "ANDRES_ODOO_PASSWORD",
              "ODOO_URL", "ODOO_DB", "FIN_COOKIE_SECRET"):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

if not os.environ.get("ANDRES_ODOO_PASSWORD") and os.environ.get("OPS_ODOO_PASSWORD"):
    os.environ["ANDRES_ODOO_PASSWORD"] = os.environ["OPS_ODOO_PASSWORD"]

st.set_page_config(
    page_title="UnionX Finanzas",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main .block-container {padding: 1.2rem 1.5rem 1rem 1.5rem; max-width: 100%;}
    section[data-testid="stSidebar"] {background: linear-gradient(180deg, #064E3B 0%, #022C22 100%); width: 270px !important;}
    section[data-testid="stSidebar"] * {color: #D1FAE5 !important;}
    section[data-testid="stSidebar"] hr {border-color: rgba(255,255,255,0.1) !important;}
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .stDeployButton {display: none;}

    /* KPI cards estilo finanzas */
    .fin-kpi {
        background: white; border-radius: 12px; padding: 18px 20px;
        border: 1px solid #E2E8F0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        height: 100%;
    }
    .fin-kpi .label {font-size: 0.72rem; color: #64748B; text-transform: uppercase;
                      letter-spacing: 0.5px; font-weight: 600; margin-bottom: 6px;}
    .fin-kpi .valor {font-size: 1.6rem; font-weight: 700; color: #1E293B; line-height: 1.1;}
    .fin-kpi .meta {font-size: 0.72rem; color: #64748B; margin-top: 8px;
                     padding-top: 8px; border-top: 1px solid #F1F5F9;}
    .fin-kpi .var-pos {color: #16A34A; font-weight: 600;}
    .fin-kpi .var-neg {color: #DC2626; font-weight: 600;}
    .fin-kpi .var-neu {color: #F59E0B; font-weight: 600;}
</style>
""", unsafe_allow_html=True)


# ============================================================
# AUTH
# ============================================================
with st.sidebar:
    st.markdown("## 💰 **UnionX Finanzas**")
    st.caption("Control de gestión")
    st.divider()

from views._fin_auth import require_login_fin, get_fin_user, logout_fin  # noqa
require_login_fin()

with st.sidebar:
    user = get_fin_user()
    if user:
        st.caption(f"👤 {user['email']}")
        if st.button("Cerrar sesión", use_container_width=True, key="fin_logout"):
            logout_fin()

    # Info de actualización
    from views._fin_data import info_actualizacion  # noqa
    st.divider()
    st.caption(info_actualizacion())


# ============================================================
# NAVEGACIÓN
# ============================================================
from views.fin_foto_mes import render as render_fin_foto_mes  # noqa
from views.fin_pyl_cc import render as render_fin_pyl_cc  # noqa
from views.fin_pyl_linea_negocio import render as render_fin_pyl_ln  # noqa
from views.fin_caja_deuda_kt import render as render_fin_caja_kt  # noqa
from views.fin_forecast_cierre import render as render_fin_forecast  # noqa

pages = {
    "🎯 Resumen": [
        st.Page(render_fin_foto_mes, title="Foto del mes (V/H)", icon="📸",
                url_path="fin-foto-mes", default=True),
    ],
    "💵 P&L Control de Gestión": [
        st.Page(render_fin_pyl_cc, title="P&L por Centro de Costo", icon="💵",
                url_path="fin-pyl-cc"),
        st.Page(render_fin_pyl_ln, title="P&L por Línea de Negocio", icon="📈",
                url_path="fin-pyl-ln"),
    ],
    "💧 Caja & Balance": [
        st.Page(render_fin_caja_kt, title="Caja, Deuda & KT", icon="💧",
                url_path="fin-caja-kt"),
    ],
    "🎯 Forecast": [
        st.Page(render_fin_forecast, title="Cierre proyectado año", icon="🎯",
                url_path="fin-forecast"),
    ],
}

pg = st.navigation(pages)
pg.run()
