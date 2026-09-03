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
    section[data-testid="stSidebar"] {background: linear-gradient(180deg, #1F3864 0%, #14243F 100%); width: 270px !important;}
    section[data-testid="stSidebar"] * {color: #DBE7F5 !important;}
    section[data-testid="stSidebar"] hr {border-color: rgba(255,255,255,0.12) !important;}
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
        if st.button("Cerrar sesión", width='stretch', key="fin_logout"):
            logout_fin()

    # Info de actualización
    from views._fin_data import info_actualizacion  # noqa
    st.divider()
    st.caption(info_actualizacion())


# ============================================================
# NAVEGACIÓN — estructurada según la Planificación Financiera 2026
# (Fase 1: réplica read-only de P&L, Balance, Indicadores, Deuda, KT)
# ============================================================
from views.fin_resumen import render as render_fin_resumen  # noqa
from views.fin_pl import render as render_fin_pl  # noqa
from views.fin_eerr_cuenta import render as render_fin_eerr_cuenta  # noqa
from views.fin_balance import render as render_fin_balance  # noqa
from views.fin_pl_bancos import render as render_fin_pl_bancos  # noqa
from views.fin_kt import render as render_fin_kt  # noqa
from views.fin_deuda import render as render_fin_deuda  # noqa
from views.fin_ppe import render as render_fin_ppe  # noqa
from views.fin_otros import render as render_fin_otros  # noqa
from views.fin_presupuesto import render as render_fin_presupuesto  # noqa
from views.fin_forecast_cierre import render as render_fin_forecast  # noqa
from views.fin_indicadores import render as render_fin_indicadores  # noqa
from views.fin_comparativo import render as render_fin_comparativo  # noqa
from views.fin_analisis import render as render_fin_analisis  # noqa
from views.fin_valorizacion import render as render_fin_valorizacion  # noqa

pages = {
    "🎯 Resumen": [
        st.Page(render_fin_resumen, title="Resumen Ejecutivo YTD", icon="🎯",
                url_path="fin-resumen", default=True),
    ],
    "📊 Estados Financieros": [
        st.Page(render_fin_pl, title="P&L / Resultado (EERR)", icon="📊",
                url_path="fin-pl"),
        st.Page(render_fin_eerr_cuenta, title="EERR por Cuenta", icon="📒",
                url_path="fin-eerr-cuenta"),
        st.Page(render_fin_balance, title="Balance (EEFF)", icon="🏦",
                url_path="fin-balance"),
        st.Page(render_fin_pl_bancos, title="P&L Bancos (anual)", icon="🏛️",
                url_path="fin-pl-bancos"),
    ],
    "💵 Presupuesto & Forecast": [
        st.Page(render_fin_presupuesto, title="Presupuesto vs Real", icon="💵",
                url_path="fin-presupuesto"),
        st.Page(render_fin_forecast, title="Forecast Cierre 2026", icon="🔮",
                url_path="fin-forecast"),
    ],
    "📐 Detalle / Schedules": [
        st.Page(render_fin_kt, title="Capital de Trabajo (KT)", icon="📦",
                url_path="fin-kt"),
        st.Page(render_fin_deuda, title="Deuda & Préstamos", icon="💳",
                url_path="fin-deuda"),
        st.Page(render_fin_ppe, title="PP&E (Activo Fijo)", icon="🏗️",
                url_path="fin-ppe"),
        st.Page(render_fin_otros, title="Otros Activos/Pasivos", icon="🗂️",
                url_path="fin-otros"),
    ],
    "📈 Análisis": [
        st.Page(render_fin_indicadores, title="Indicadores Financieros", icon="📈",
                url_path="fin-indicadores"),
        st.Page(render_fin_comparativo, title="Análisis Comparativo", icon="⚖️",
                url_path="fin-comparativo"),
        st.Page(render_fin_analisis, title="Análisis Financiero", icon="🧭",
                url_path="fin-analisis"),
        st.Page(render_fin_valorizacion, title="Valorización (DCF)", icon="💎",
                url_path="fin-valorizacion"),
    ],
}

pg = st.navigation(pages)
pg.run()
