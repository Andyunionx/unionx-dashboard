"""
🔐 Login SSO Odoo para la app Finanzas — sesión persistente HMAC 8h.

Misma mecánica que _ops_auth.py pero con:
  - FIN_ALLOWED_EMAILS (lista propia: gerencia + contabilidad)
  - Cookie key "unionx_fin_session" (separada de Operaciones)

Reglas:
1. Email + password de Odoo (su login normal)
2. Validamos contra Odoo XML-RPC: si UID > 0, autenticado
3. Filtramos contra FIN_ALLOWED_EMAILS
4. Cookie persistente HMAC (8h) → no pide re-login al refresh
"""
import hashlib
import hmac
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = PROJECT_ROOT / "finanzas-unionx" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# Lista de emails autorizados — fallback si no hay FIN_ALLOWED_EMAILS en Secrets
DEFAULT_ALLOWED_EMAILS = [
    "andres@grupoeter.cl",         # Andrés Browne — Gerente Finanzas + SC
    "andres@unionx.cl",            # Andrés Browne (cuenta UnionX)
    "facturacion@melollevo.cl",    # Yohana Grisman — facturación
    "contabilidad@grupoeter.cl",   # contabilidad Eter
]

COOKIE_NAME = "unionx_fin_session"
COOKIE_MAX_AGE_HOURS = 8


def _cookie_secret() -> str:
    """Secret para firmar cookie HMAC. Streamlit Secrets > env > fallback."""
    val = st.secrets.get("FIN_COOKIE_SECRET") if hasattr(st, "secrets") else None
    if val:
        return str(val)
    return os.environ.get("FIN_COOKIE_SECRET", "unionx-finanzas-fallback-change-me")


def _firmar(payload: str) -> str:
    """HMAC-SHA256 del payload con el secret."""
    return hmac.new(_cookie_secret().encode(), payload.encode(),
                     hashlib.sha256).hexdigest()


def _crear_cookie(email: str, uid: int) -> str:
    """email|uid|exp_timestamp|hmac"""
    exp = int(time.time()) + COOKIE_MAX_AGE_HOURS * 3600
    payload = f"{email}|{uid}|{exp}"
    sig = _firmar(payload)
    return f"{payload}|{sig}"


def _validar_cookie(cookie: str) -> dict | None:
    """Devuelve {email, uid} si la cookie es válida y no expiró, sino None."""
    if not cookie or cookie.count("|") != 3:
        return None
    try:
        email, uid, exp, sig = cookie.split("|")
        if int(exp) < time.time():
            return None
        payload = f"{email}|{uid}|{exp}"
        if not hmac.compare_digest(_firmar(payload), sig):
            return None
        return {"email": email, "uid": int(uid)}
    except Exception:
        return None


def _get_cookie_manager():
    """Lazy load del CookieManager (extra-streamlit-components)."""
    try:
        import extra_streamlit_components as stx
        if "_fin_cookie_manager" not in st.session_state:
            st.session_state["_fin_cookie_manager"] = stx.CookieManager(
                key="fin_cookie_mgr"
            )
        return st.session_state["_fin_cookie_manager"]
    except Exception:
        return None


def _leer_cookie() -> str | None:
    cm = _get_cookie_manager()
    if cm is None:
        return None
    try:
        return cm.get(cookie=COOKIE_NAME)
    except Exception:
        return None


def _guardar_cookie(value: str):
    cm = _get_cookie_manager()
    if cm is None:
        return
    try:
        cm.set(COOKIE_NAME, value,
                expires_at=datetime.now() + timedelta(hours=COOKIE_MAX_AGE_HOURS))
    except Exception:
        pass


def _eliminar_cookie():
    cm = _get_cookie_manager()
    if cm is None:
        return
    try:
        cm.delete(COOKIE_NAME)
    except Exception:
        pass


def _get_allowed_emails() -> list:
    """Emails autorizados. Streamlit Secrets > fallback hardcoded."""
    try:
        val = st.secrets.get("FIN_ALLOWED_EMAILS") if hasattr(st, "secrets") else None
    except Exception:
        val = None
    if val:
        if isinstance(val, str):
            return [e.strip().lower() for e in val.split(",") if e.strip()]
        if isinstance(val, (list, tuple)):
            return [str(e).strip().lower() for e in val if str(e).strip()]
    return [e.lower() for e in DEFAULT_ALLOWED_EMAILS]


def _validar_odoo(email: str, password: str) -> tuple[bool, str, int]:
    """Intenta auth contra Odoo. (ok, error, uid)"""
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
        st.markdown("# 💰 UnionX Finanzas")
        st.caption("Login con tu usuario Odoo · sesión válida 8 horas")
        st.markdown("---")

        with st.form("fin_login", clear_on_submit=False):
            email = st.text_input("Email Odoo", placeholder="ej: andres@grupoeter.cl")
            password = st.text_input("Password Odoo", type="password")
            submit = st.form_submit_button("Ingresar", type="primary",
                                            use_container_width=True)

            if submit:
                if not email or not password:
                    st.error("Ingresá email y password")
                    return
                email_l = email.strip().lower()
                if email_l not in _get_allowed_emails():
                    st.error("Email no autorizado para esta app. Pedile a Andrés agregar tu email.")
                    return
                with st.spinner("Validando con Odoo…"):
                    ok, err, uid = _validar_odoo(email_l, password)
                if not ok:
                    st.error(err or "Login falló")
                    return

                # Login OK: guardar session + cookie
                st.session_state["fin_user"] = {"email": email_l, "uid": uid}
                cookie_val = _crear_cookie(email_l, uid)
                _guardar_cookie(cookie_val)
                st.success(f"Bienvenido {email_l}")
                time.sleep(0.3)
                st.rerun()


def require_login_fin():
    """Bloquea hasta que el user esté autenticado. Llamar desde el entry point."""
    # 1. Si ya hay sesión activa, OK
    if st.session_state.get("fin_user"):
        return

    # 2. Intentar restaurar de cookie
    cookie = _leer_cookie()
    if cookie:
        valid = _validar_cookie(cookie)
        if valid and valid["email"] in _get_allowed_emails():
            st.session_state["fin_user"] = valid
            return

    # 3. No hay sesión → mostrar form y stop
    _login_form()
    st.stop()


def logout_fin():
    """Cierra sesión: borra cookie + session_state."""
    _eliminar_cookie()
    st.session_state.pop("fin_user", None)
    st.rerun()


def get_fin_user() -> dict | None:
    return st.session_state.get("fin_user")
