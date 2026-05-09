"""
Helper para crear OdooClient con credenciales del usuario OPERACIONES.

Lee env vars (en Streamlit Cloud vienen de st.secrets):
  OPS_ODOO_USER       — usuario Odoo del equipo Operaciones (ej: ops@unionx.cl)
  OPS_ODOO_PASSWORD   — password de ese usuario

Si NO existen, falla con error informativo.

Uso:
    from views._ops_odoo_helper import get_ops_odoo_client
    odoo = get_ops_odoo_client()
    if odoo is None:
        st.error("Falta OPS_ODOO_PASSWORD en Streamlit Secrets")
        return
    # ... usar odoo.search_read(...)
"""
import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Asegurar sys.path para importar OdooClient del backend
_BACKEND = PROJECT_ROOT / "finanzas-unionx" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@st.cache_resource(show_spinner=False)
def get_ops_odoo_client():
    """Devuelve OdooClient autenticado con creds OPS, o None si no hay creds.

    Cache_resource = singleton durante la sesión Streamlit (no se recrea por reload).
    """
    user = os.environ.get("OPS_ODOO_USER", "").strip()
    pwd = os.environ.get("OPS_ODOO_PASSWORD", "").strip()
    if not user or not pwd:
        return None

    url = os.environ.get("ODOO_URL", "https://unionxb2b.odoo.com")
    db = os.environ.get("ODOO_DB", "bmya-innovatek-sh-prd-6981800")

    try:
        from app.core.odoo_client import OdooClient
        client = OdooClient(url, db, user, pwd)
        # Probar autenticación
        client.authenticate()
        return client
    except Exception as e:
        # Devolver None pero loggear el error en sidebar para diagnóstico
        st.sidebar.error(f"⚠️ OdooClient OPS error: {type(e).__name__}: {str(e)[:80]}")
        return None


def odoo_status_indicator():
    """Muestra en sidebar si la conexión Odoo OPS está OK.

    OPTIMIZADO: cachea el resultado en st.session_state para no llamar a
    get_ops_odoo_client() (que hace authenticate XML-RPC) en cada render.
    Antes esto causaba que el script se quedara "corriendo todo el rato"
    cuando Odoo SaaS estaba lento (sin timeout en authenticate).
    """
    # Cache en sesión: solo chequea 1 vez por sesión Streamlit
    cached = st.session_state.get('_ops_odoo_status_cached')
    if cached is not None:
        if cached:
            user = os.environ.get("OPS_ODOO_USER", "?")
            st.sidebar.success(f"🟢 Odoo OPS · {user}")
        else:
            st.sidebar.error("🔴 Odoo OPS · ver detalle al refrescar")
        return cached

    # Primera vez en esta sesión: chequear con timeout (15s en _make_proxy)
    try:
        client = get_ops_odoo_client()
        ok = client is not None
    except Exception as e:
        st.sidebar.warning(f"⚠️ Odoo OPS timeout/error: {type(e).__name__}")
        st.session_state['_ops_odoo_status_cached'] = False
        return False

    st.session_state['_ops_odoo_status_cached'] = ok
    if not ok:
        st.sidebar.error("🔴 Odoo OPS · sin credenciales")
        st.sidebar.caption(
            "Setear `OPS_ODOO_USER` y `OPS_ODOO_PASSWORD` "
            "en Streamlit Cloud Secrets."
        )
        return False
    user = os.environ.get("OPS_ODOO_USER", "?")
    st.sidebar.success(f"🟢 Odoo OPS · {user}")
    return True
