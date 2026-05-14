"""
Dashboard UnionX — APP PLANIFICACIÓN.

Entry point dedicado a Supply Chain Planning. Repo compartido con Ventas y
Operaciones pero deploy y secrets independientes en Streamlit Cloud.

Objetivos:
  - Planificar compras cruzando forecast, stock, tránsito y política de cobertura
  - Cruzar con caja proyectada (app finanzas-unionx) para ajustar plan
  - Entregar inteligencia para negociaciones con proveedores (volumen, EXW, cruzada)
  - Estrategia de liquidación para sobre-stock

Módulos:
  - Triada stock + llegadas + demanda (la vista núcleo)
  - Propuesta de compras (output priorizado)
  - Maestro de proveedores (lee Drive del tercero cuando esté)
  - Política de stock objetivo (editable por categoría comercial)
  - Análisis para negociación (volumen histórico, evolución EXW, cruzada)
  - Caja vs plan (hook a app finanzas, pendiente)
  - Liquidación (SKUs sobre-stock + descuento sugerido)
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

# Streamlit Cloud: exponer secretos como env vars
for _key in ("LIBSQL_URL", "LIBSQL_AUTH_TOKEN", "ANDRES_ODOO_PASSWORD"):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

st.set_page_config(
    page_title="UnionX Planificación",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# AUTH (yaml/bcrypt — mismo mecanismo que dashboard_ventas)
# ============================================================
def _to_plain(obj):
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
    auth_config['cookie']['name'] + '_planificacion',  # cookie distinta a la de Ventas
    auth_config['cookie']['key'],
    auth_config['cookie']['expiry_days'],
)
try:
    authenticator.login(location='main', key='login_main_plan')
except Exception:
    pass

if st.session_state.get('authentication_status') is False:
    st.error('Usuario o contraseña incorrectos')
    st.stop()
elif st.session_state.get('authentication_status') is None:
    st.warning('Ingresá tu usuario y contraseña para acceder a Planificación')
    st.stop()

# Autenticado
with st.sidebar:
    st.markdown("## 📦 **UnionX Planificación**")
    st.caption("Supply Chain Planning · 2026")
    authenticator.logout('Cerrar sesión', 'sidebar')
    st.write(f"👤 **{st.session_state.get('name', '')}**")
    st.divider()

# ============================================================
# NAVEGACIÓN
# ============================================================
from views.planning.triada import render as render_triada
from views.planning.compras import render as render_compras
from views.planning.proveedores import render as render_proveedores
from views.planning.politicas import render as render_politicas
from views.planning.negociacion import render as render_negociacion
from views.planning.caja import render as render_caja
from views.planning.liquidacion import render as render_liquidacion
from views.forecast import render as render_forecast

# Vistas fuente (reuso de app Ventas — replican exacto lo que ve Ventas)
from views.ventas_general import render as render_ventas_general
from views.stock_live import render as render_stock_live
from views.ops_comex import render as render_comex


def render_resumen():
    """Página de inicio: status de fuentes y resumen ejecutivo."""
    from views.planning._data_helpers import fuentes_status

    st.title("📦 Planificación — Resumen")
    st.caption("Estado de las fuentes de datos y atajos a los módulos.")

    st.markdown("### Status de fuentes")
    status = fuentes_status()
    cols = st.columns(3)
    for i, (nombre, info) in enumerate(status.items()):
        with cols[i % 3]:
            icon = "✅" if info['existe'] else "⚠️"
            st.markdown(f"**{icon} {nombre}**")
            st.caption(f"`{info['path']}`")
            if not info['existe']:
                st.caption("_Esperando carga_")

    st.divider()
    st.markdown("### Cómo usar la app")
    st.markdown("""
    1. **📐 Políticas** — cargar (o editar) los meses de cobertura objetivo por categoría comercial
    2. **🏭 Proveedores** — cargar maestro desde Drive (cuando lo tengamos del tercero)
    3. **🎯 Triada** — vista núcleo: stock + llegadas + demanda → cobertura proyectada
    4. **🛒 Propuesta de compras** — salida priorizada de qué comprar
    5. **🤝 Negociación** — análisis histórico para conversaciones con proveedores
    6. **💵 Caja** — cruce con app finanzas (pendiente integración)
    7. **🔻 Liquidación** — SKUs en sobre-stock candidatos a campaña
    """)


pages = {
    "🏠 Inicio": [
        st.Page(render_resumen, title="Resumen", icon="📦",
                url_path="pln-resumen", default=True),
    ],
    "📥 Información fuente": [
        st.Page(render_ventas_general, title="Ventas — Vista General", icon="📈",
                url_path="pln-fuente-ventas"),
        st.Page(render_stock_live, title="Stock LIVE", icon="📦",
                url_path="pln-fuente-stock"),
        st.Page(render_comex, title="COMEX en tránsito", icon="🚢",
                url_path="pln-fuente-comex"),
    ],
    "🔮 Forecast": [
        st.Page(render_forecast, title="Proyección Prophet (mes/30-60-90d/año/componentes)",
                icon="🔮", url_path="pln-forecast"),
    ],
    "🎯 Planificación": [
        st.Page(render_triada, title="Triada Stock+Llegadas+Demanda", icon="🎯",
                url_path="pln-triada"),
        st.Page(render_compras, title="Propuesta de compras", icon="🛒",
                url_path="pln-compras"),
    ],
    "⚙️ Configuración": [
        st.Page(render_politicas, title="Política de stock objetivo", icon="📐",
                url_path="pln-politicas"),
        st.Page(render_proveedores, title="Maestro proveedores", icon="🏭",
                url_path="pln-proveedores"),
    ],
    "📊 Inteligencia": [
        st.Page(render_negociacion, title="Análisis para negociación", icon="🤝",
                url_path="pln-negociacion"),
        st.Page(render_caja, title="Caja vs plan", icon="💵",
                url_path="pln-caja"),
        st.Page(render_liquidacion, title="Liquidación sobre-stock", icon="🔻",
                url_path="pln-liquidacion"),
    ],
}

pg = st.navigation(pages)
pg.run()
