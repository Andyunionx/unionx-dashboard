"""
🔐 Login SSO contra Odoo para la app Operaciones.

Reemplaza streamlit_authenticator por validación directa contra Odoo XML-RPC.

Reglas:
1. El usuario ingresa email + password de Odoo (su login normal en odoo.com)
2. Validamos contra Odoo: si Odoo responde con UID > 0, está autenticado
3. Filtramos contra OPS_ALLOWED_EMAILS (lista en Streamlit Secrets o fallback hardcoded)
4. Si pasa ambos: dejamos entrar y guardamos en session_state

Beneficios:
- No mantenemos lista paralela de hashes bcrypt
- Si Andrés crea/desactiva user en Odoo → automáticamente se refleja
- Cada user usa SU password real de Odoo
- Para datos del dashboard: el dashboard sigue usando OPS_ODOO_USER (cuenta servicio)
"""
import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = PROJECT_ROOT / "finanzas-unionx" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# Lista de emails autorizados — fallback si no hay OPS_ALLOWED_EMAILS en Secrets
DEFAULT_ALLOWED_EMAILS = [
    "andres@grupoeter.cl",       # Andrés Browne — Gerencia Operaciones
    "bodega@grupoeter.cl",        # Gerardo Ortega — Bodega
    "gabriela@grupoeter.cl",      # Gabriela Pastran
    "facturacion@melollevo.cl",   # Yohana Grisman
]


def _get_allowed_emails() -> list:
    """Lista de emails autorizados. Prioriza Streamlit Secrets, fallback a hardcoded."""
    # Secret puede ser:
    #   OPS_ALLOWED_EMAILS = "email1@x.com,email2@y.com"
    # o:
    #   OPS_ALLOWED_EMAILS = ["email1@x.com", "email2@y.com"]
    val = st.secrets.get("OPS_ALLOWED_EMAILS")
    if val:
        if isinstance(val, str):
            return [e.strip().lower() for e in val.split(",") if e.strip()]
        if isinstance(val, (list, tuple)):
            return [str(e).strip().lower() for e in val if str(e).strip()]
    return [e.lower() for e in DEFAULT_ALLOWED_EMAILS]


def _validar_odoo(email: str, password: str) -> tuple[bool, str, int]:
    """Intenta autenticar contra Odoo. Devuelve (ok, mensaje_error, uid)."""
    try:
        from app.core.odoo_client import OdooClient
        url = os.environ.get("ODOO_URL", "https://unionxb2b.odoo.com")
        db = os.environ.get("ODOO_DB", "bmya-innovatek-sh-prd-6981800")

        client = OdooClient(url, db, email, password)
        uid = client.authenticate()
        if uid and uid > 0:
            return True, "", uid
        return False, "Credenciales inválidas", 0
    except Exception as e:
        return False, f"Error conectando a Odoo: {type(e).__name__}: {str(e)[:100]}", 0


def _login_form():
    """Render del formulario de login."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("# 🚢 UnionX Operaciones")
        st.caption("Login con tu usuario Odoo")
        st.markdown("---")

        with st.form("ops_login", clear_on_submit=False):
            email = st.text_input("Email Odoo", placeholder="ej: bodega@grupoeter.cl")
            password = st.text_input("Password Odoo", type="password")
            submit = st.form_submit_button("Ingresar", type="primary", use_container_width=True)

            if submit:
                if not email or not password:
                    st.error("Ingresá email y password")
                    return

                # 1. Validar que el email esté en la lista de autorizados
                allowed = _get_allowed_emails()
                if email.strip().lower() not in allowed:
                    st.error(
                        "❌ Tu email no está autorizado para esta app. "
                        "Contactá a Andrés para que te agregue."
                    )
                    return

                # 2. Validar credenciales contra Odoo
                with st.spinner("Validando con Odoo…"):
                    ok, err, uid = _validar_odoo(email.strip(), password)
                if not ok:
                    st.error(f"❌ {err}")
                    return

                # Auth OK → guardar en session
                st.session_state["ops_authenticated"] = True
                st.session_state["ops_email"] = email.strip().lower()
                st.session_state["ops_uid"] = uid
                # Para compatibilidad con vistas que usan st.session_state.get("name", ...):
                st.session_state["name"] = email.strip().split("@")[0].title()
                st.session_state["authentication_status"] = True
                st.rerun()

        st.markdown("---")
        st.caption(
            "💡 Usás tu mismo email y password de Odoo. "
            "Si tenés problemas para ingresar, verificá que tu cuenta Odoo esté activa."
        )


def require_login_ops():
    """Bloquea la app hasta que el user haga login. Llamar al inicio del entry point.

    Si está autenticado: muestra info en sidebar y deja seguir.
    Si no: muestra form de login y st.stop().
    """
    if st.session_state.get("ops_authenticated"):
        # Ya está logueado — render info sidebar
        with st.sidebar:
            email = st.session_state.get("ops_email", "")
            st.markdown(f"👤 **{email}**")
            if st.button("Cerrar sesión", use_container_width=True):
                for k in ["ops_authenticated", "ops_email", "ops_uid", "name", "authentication_status"]:
                    st.session_state.pop(k, None)
                st.rerun()
            st.divider()
        return st.session_state["ops_email"]

    # No autenticado — mostrar form
    _login_form()
    st.stop()
