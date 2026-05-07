"""
Pagina Comercial — vista principal: Analisis de Contribucion completo.

NOTA (2026-05-05): la vista Odoo (AOV/repeat/B2B/margen canal/marketing) fue PAUSADA
por el usuario porque esta construyendo una skill aparte para la mirada Odoo del area
comercial. Cuando esa skill este lista, se reactiva la seccion Odoo de esta pagina.

Estructura actual:
  - Aviso de la pausa (banner informativo)
  - Dashboard Contribucion completo via runpy (los 6 tabs originales)

Autenticacion centralizada con auth_helper.
"""
import os
import runpy
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
PROJECT_ROOT = PARENT.parent
sys.path.insert(0, str(PARENT))
sys.path.insert(0, str(PROJECT_ROOT))

from auth_helper import require_login  # noqa: E402

require_login()

st.set_page_config(page_title="Comercial - UnionX", page_icon="💼", layout="wide")

# ============================================================================
# Banner de aviso (vista Odoo pausada)
# ============================================================================
with st.expander("ℹ️ Vista Odoo (AOV / Repeat / Top B2B / Margen canal) — pausada", expanded=False):
    st.caption(
        "La vista de KPIs comerciales calculados en vivo desde Odoo (AOV, Repeat customer rate, "
        "Top B2B, Margen por canal, Marketing) está **pausada temporalmente** — Andrés está "
        "construyendo una skill dedicada para esa mirada. Cuando la skill esté lista, esta sección "
        "vuelve a aparecer en este mismo dashboard."
    )

# ============================================================================
# Dashboard Contribucion (vista principal)
# ============================================================================
try:
    contrib_path = str(PARENT / "contribucion_dashboard.py")
    # Marcar contexto embebido para que contribucion_dashboard NO llame set_page_config()
    st.session_state["_embedded_context"] = True
    runpy.run_path(contrib_path, run_name="__contrib_in_comercial__")
except Exception as e:
    st.error(f"No se pudo cargar el dashboard de Contribución: {e}")
    st.info("Alternativa: abrir directamente http://localhost:8502 (standalone).")
finally:
    st.session_state["_embedded_context"] = False
