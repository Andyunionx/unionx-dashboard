"""
🔐 Login SSO Odoo para la app Finanzas — sesión persistente HMAC 8h.

Misma mecánica que _ops_auth pero independiente:
  - FIN_ALLOWED_EMAILS (Andrés + contabilidad)
  - Cookie "unionx_fin_session" separada de Operaciones
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


DEFAULT_ALLOWED_EMAILS = [
    "andres@grupoeter.cl",
    "andres@unionx.cl",
    "facturacion@melollevo.cl",
    "contabilidad@grupoeter.cl",
]
COOKIE_NAME = "unionx_fin_session"
COOKIE_MAX_AGE_HOURS = 8


def _cookie_secret() -> str:
    try:
        val = st.secrets.get("FIN_COOKIE_SECRET")
        if val:
            return str(val)
    except Exception:
        pass
    return os.environ.get("FIN_COOKIE_SECRET", "unionx-finanzas-change-me")


def _firmar(payload: str) -> str:
    return hmac.new(_cookie_secret().encode(), payload.encode(),
                     hashlib.sha256).hexdigest()


def _crear_cookie(email: str, uid: int) -> str:
    exp = int(time.time()) + COOKIE_MAX_AGE_HOURS * 3600
    payload = f"{email}|{uid}|{exp}"
    return f"{payload}|{_firmar(payload)}"


def _validar_cookie(cookie: str) -> dict | None:
    if not cookie or cookie.count("|") != 3:
        return None
    try:
        email, uid, exp, sig = cookie.split("|")
        if int(exp) < time.time():
            return None
        if not hmac.compare_digest(_firmar(f"{email}|{uid}|{exp}"), sig):
            return None
        return {"email": email, "uid": int(uid)}
    except Exception:
        return None


def _get_cookie_manager():
    try:
        import extra_streamlit_components as stx
        if "_fin_cookie_manager" not in st.session_state:
            st.session_state["_fin_cookie_manager"] = stx.CookieManager(key="fin_cookie_mgr")
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
        return False, f"Error Odoo: {type(e).__name__}: {str(e)[:100]}", 0


def _login_form():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("# 💰 UnionX Finanzas")
        st.caption("Login con tu usuario Odoo · sesión 8h")
        st.markdown("---")
        with st.form("fin_login", clear_on_submit=False):
            email = st.text_input("Email Odoo", placeholder="ej: andres@grupoeter.cl")
            password = st.text_input("Password Odoo", type="password")
            submit = st.form_submit_button("Ingresar", type="primary",
                                            width='stretch')
            if submit:
                if not email or not password:
                    st.error("Ingresá email y password")
                    return
                email_l = email.strip().lower()
                if email_l not in _get_allowed_emails():
                    st.error("Email no autorizado.")
                    return
                with st.spinner("Validando con Odoo…"):
                    ok, err, uid = _validar_odoo(email_l, password)
                if not ok:
                    st.error(err or "Login falló")
                    return
                st.session_state["fin_user"] = {"email": email_l, "uid": uid}
                _guardar_cookie(_crear_cookie(email_l, uid))
                st.success(f"Bienvenido {email_l}")
                time.sleep(0.3)
                st.rerun()


def require_login_fin():
    # Bypass SOLO local (gated por env var; nunca se activa en producción)
    if os.environ.get("FIN_DEV_BYPASS") == "1":
        st.session_state.setdefault("fin_user", {"email": "andres@unionx.cl", "uid": 0})
        return
    if st.session_state.get("fin_user"):
        return
    cookie = _leer_cookie()
    if cookie:
        valid = _validar_cookie(cookie)
        if valid and valid["email"] in _get_allowed_emails():
            st.session_state["fin_user"] = valid
            return
    _login_form()
    st.stop()


def logout_fin():
    _eliminar_cookie()
    st.session_state.pop("fin_user", None)
    st.rerun()


def get_fin_user() -> dict | None:
    return st.session_state.get("fin_user")
