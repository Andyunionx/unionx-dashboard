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

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

# Streamlit Cloud: exponer secretos como env vars
for _key in (
    "LIBSQL_URL",
    "LIBSQL_AUTH_TOKEN",
    "PLN_ODOO_USER",
    "PLN_ODOO_PASSWORD",
    "ODOO_URL",
    "ODOO_DB",
):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

# Alias: views/shared.py compartido busca ANDRES_ODOO_PASSWORD.
if not os.environ.get("ANDRES_ODOO_PASSWORD") and os.environ.get("PLN_ODOO_PASSWORD"):
    os.environ["ANDRES_ODOO_PASSWORD"] = os.environ["PLN_ODOO_PASSWORD"]

st.set_page_config(
    page_title="UnionX Planificación",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

with st.sidebar:
    st.markdown("## 📦 **UnionX Planificación**")
    st.caption("Supply Chain Planning · 2026")
    st.divider()

# Auth: reutiliza el SSO Odoo de la app Operaciones (mismas credenciales)
from views._ops_auth import require_login_ops  # noqa: E402
require_login_ops()

from views._ops_odoo_helper import odoo_status_indicator  # noqa: E402
odoo_status_indicator()

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
