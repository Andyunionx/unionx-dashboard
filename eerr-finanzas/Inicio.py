"""
UnionX Dashboards - Vista Ejecutiva (Nivel 1).

Landing del dashboard multipage. Muestra los 5 pilares estrategicos del Plan UnionX 2026-2028:
  Rentabilidad · Liquidez · Crecimiento · Eficiencia · Marca/Cliente

Cada pilar es una card con KPI central, meta, semaforo y enlace a la pagina de detalle.

Ejecutar: streamlit run eerr-finanzas/Inicio.py --server.port 8501
"""
import os
import sys
import streamlit as st
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT_ROOT))

st.set_page_config(
    page_title="UnionX Dashboards",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# CSS global
# ============================================================
st.markdown("""
<style>
    .main .block-container {padding: 1.2rem 1.5rem 1rem 1.5rem; max-width: 100%;}
    section[data-testid="stSidebar"] {background: linear-gradient(180deg, #0D1B2A 0%, #1B2838 100%); width: 270px !important;}
    section[data-testid="stSidebar"] * {color: #CBD5E1 !important;}
    section[data-testid="stSidebar"] hr {border-color: rgba(255,255,255,0.1) !important;}
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .stDeployButton {display: none;}

    .hero {
        background: linear-gradient(135deg, #1F4E79 0%, #0D1B2A 100%);
        color: white; border-radius: 16px; padding: 28px 32px; margin-bottom: 24px;
    }
    .hero h1 {margin: 0 0 8px 0; font-size: 1.8rem; font-weight: 700;}
    .hero p {margin: 0; opacity: 0.85; font-size: 0.95rem;}

    .pilar-card {
        background: white; border-radius: 14px; padding: 18px 20px;
        border: 1px solid #E2E8F0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        height: 100%; transition: all 0.2s;
    }
    .pilar-card:hover {transform: translateY(-2px); box-shadow: 0 8px 20px rgba(0,0,0,0.08);}
    .pilar-card .icono {font-size: 1.8rem; margin-bottom: 6px;}
    .pilar-card .nombre {font-size: 0.85rem; color: #64748B; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; margin-bottom: 4px;}
    .pilar-card .kpi {font-size: 0.78rem; color: #94A3B8; margin-bottom: 8px;}
    .pilar-card .valor {font-size: 1.6rem; font-weight: 700; color: #1E293B; line-height: 1.2;}
    .pilar-card .meta {font-size: 0.72rem; color: #64748B; margin-top: 6px; padding-top: 6px; border-top: 1px solid #F1F5F9;}
    .pilar-card .extra {font-size: 0.7rem; color: #94A3B8; margin-top: 4px; font-style: italic;}
    .pilar-card .semaforo {float: right; font-size: 1.4rem;}

    .nav-card {
        background: white; border-radius: 12px; padding: 16px 18px;
        border: 1px solid #E2E8F0; transition: all 0.2s;
    }
    .nav-card:hover {transform: translateY(-2px); border-color: #1F4E79;}
    .nav-card .icon {font-size: 1.6rem; margin-bottom: 8px;}
    .nav-card .title {font-size: 0.95rem; font-weight: 700; color: #1E293B;}
    .nav-card .desc {font-size: 0.78rem; color: #64748B; line-height: 1.45; margin-top: 4px;}
</style>
""", unsafe_allow_html=True)

# ============================================================
# AUTH
# ============================================================
from auth_helper import require_login, get_user_roles  # noqa: E402

authenticator, username, name = require_login()
roles = get_user_roles(username)

# ============================================================
# HERO
# ============================================================
st.markdown(f"""
<div class='hero'>
    <h1>🏢 UnionX — Panel de Control</h1>
    <p>Hola {name} · Vista ejecutiva alineada al Plan Estratégico 2026-2028 · 5 pilares con KPIs en vivo</p>
</div>
""", unsafe_allow_html=True)

# ============================================================
# 5 PILARES (Vista Ejecutiva)
# ============================================================

@st.cache_data(ttl=600, show_spinner="Calculando pilares estratégicos…")
def _cargar_pilares():
    from kpis_ejecutivos import get_kpis_pilares
    return get_kpis_pilares()


pilares = _cargar_pilares()

# Mapping pilar → página de detalle
LINKS_DETALLE = {
    "rentabilidad": ("📋 Planificación", "pages/4_📋_Planificacion.py"),
    "liquidez":     ("📋 Planificación", "pages/4_📋_Planificacion.py"),
    "crecimiento":  ("🛒 Comercial", "pages/6_🛒_Comercial.py"),
    "eficiencia":   ("📊 Contribución", "pages/2_📊_Contribucion.py"),
    "marca":        ("🛒 Comercial", "pages/6_🛒_Comercial.py"),
}

st.markdown("### 🎯 5 Pilares estratégicos · YTD")

with st.expander("ℹ️ ¿De dónde sale cada número?", expanded=False):
    st.markdown("""
| Pilar | KPI | Fuente exacta | Cálculo |
|---|---|---|---|
| 💰 **Rentabilidad** | EBIT % YTD | Hoja `Metas 2026` de `Planificación Financiera V51-04.xlsx` | EBIT YTD acumulado (filas 28-36) / Venta YTD acumulada (filas 1-9), del Ene al mes anterior al actual |
| 💧 **Liquidez** | CCC (días) | Odoo en vivo (`stock.quant`, `account.move` últimos 365 días) | DIO + DSO − DPO |
| 📈 **Crecimiento** | Ingresos YoY YTD | Odoo en vivo (`sale.order` 2026 vs 2025) | (Venta YTD 2026 − Venta YTD 2025) / Venta YTD 2025 |
| ⚡ **Eficiencia** | Margen Contribución YTD | Hoja `Metas 2026` de `Planificación Financiera V51-04.xlsx` | Contribución YTD (filas 10-18) / Venta YTD (filas 1-9) |
| 🎯 **Marca/Cliente** | Repeat Rate 180d | Odoo en vivo (`sale.order.partner_id` últimos 180 días) | Partners con ≥2 órdenes / total partners |

**Frecuencia:** cache de 10 minutos. Para forzar refresh: recargá la página (Ctrl+R).

**Archivo Planificación detectado dinámicamente:** se toma siempre el más reciente con patrón `Planificación Financiera V*.xlsx` en `Finanzas/Empresa/2026/Planificación Financiera/`.
    """)

cols = st.columns(5)
ORDEN = ["rentabilidad", "liquidez", "crecimiento", "eficiencia", "marca"]
for i, key in enumerate(ORDEN):
    p = pilares.get(key, {})
    icono = p.get("icono", "❓")
    nombre = p.get("nombre", "?")
    kpi_n = p.get("kpi_nombre", "—")
    valor = p.get("valor_fmt", "—")
    meta = p.get("meta", "—")
    sem = p.get("semaforo", "⚪")
    extra = p.get("extra", "")
    err = p.get("error")
    fuente = p.get("fuente", "")

    with cols[i]:
        st.markdown(f"""
        <div class='pilar-card'>
            <div class='semaforo'>{sem}</div>
            <div class='icono'>{icono}</div>
            <div class='nombre'>{nombre}</div>
            <div class='kpi'>{kpi_n}</div>
            <div class='valor'>{valor}</div>
            <div class='meta'>Meta: <b>{meta}</b></div>
            {f"<div class='extra'>{extra}</div>" if extra else ""}
        </div>
        """, unsafe_allow_html=True)
        if err:
            st.caption(f"⚠️ {err[:80]}")
        else:
            st.caption(f"📡 {fuente}")

st.divider()

# ============================================================
# Navegación a páginas de detalle
# ============================================================
st.markdown("### 🗂️ Áreas de detalle (Nivel 2)")
st.caption("Click en cualquier página del menú lateral para entrar al detalle.")

navrows = st.columns(4)
NAVPAGES = [
    ("📦", "Fulfillment", "Stock en vivo · ABC · Slow movers · Costo Operativo Total · stubs WMS H2"),
    ("💼", "Comercial", "AOV · Repeat · Top B2B · Margen canal · Análisis Contribución completo"),
    ("🚨", "Alertas", "10 alertas en tiempo real con persistencia y dedup"),
    ("📋", "Planificación", "P&L · EEFF · KT · Deuda · DIO/DSO/DPO/CCC · Indicadores YTD"),
]
for i, (icon, title, desc) in enumerate(NAVPAGES):
    with navrows[i]:
        st.markdown(f"""
        <div class='nav-card'>
            <div class='icon'>{icon}</div>
            <div class='title'>{title}</div>
            <div class='desc'>{desc}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

navrows2 = st.columns(4)
NAVPAGES2 = [
    ("🚢", "COMEX", "Próximamente · lead time · costo aterrizaje · ETA · cobertura cambiaria"),
    ("↩️", "Post-venta", "Próximamente · tasa devolución · recovery · SERNAC · causa raíz"),
    ("💬", "SAC", "Próximamente · FRT · NPS · CSAT · tickets/pedido (esperando Helpdesk H2)"),
    ("🚚", "Logística", "Próximamente · OTD · costo logístico · incidentes (esperando APIs courier H2)"),
]
for i, (icon, title, desc) in enumerate(NAVPAGES2):
    with navrows2[i]:
        st.markdown(f"""
        <div class='nav-card' style='opacity:0.55'>
            <div class='icon'>{icon}</div>
            <div class='title'>{title}</div>
            <div class='desc'>{desc}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ============================================================
# Footer con metadatos
# ============================================================
st.markdown(f"""
<div style='text-align:center; color:#94A3B8; font-size:0.72rem; padding:20px 0 10px 0;'>
    UnionX · {datetime.now().strftime('%d/%m/%Y %H:%M')} · Usuario: {username} · Roles: {', '.join(roles) or 'sin rol'}
    <br>Plan Estratégico 2026-2028 · Vista Ejecutiva con drill-down a 9 áreas
</div>
""", unsafe_allow_html=True)
