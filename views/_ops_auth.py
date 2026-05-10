"""
🔐 Login SSO contra Odoo para la app Operaciones — con sesión persistente.

Reemplaza streamlit_authenticator por validación directa contra Odoo XML-RPC.

Reglas:
1. El usuario ingresa email + password de Odoo (su login normal en odoo.com)
2. Validamos contra Odoo: si Odoo responde con UID > 0, está autenticado
3. Filtramos contra OPS_ALLOWED_EMAILS (lista en Streamlit Secrets o fallback hardcoded)
4. Si pasa ambos: dejamos entrar y guardamos en session_state
5. **Cookie persistente HMAC** (8h por default) para que no pida login en cada refresh

Beneficios:
- No mantenemos lista paralela de hashes bcrypt
- Si Andrés crea/desactiva user en Odoo → automáticamente se refleja
- Cada user usa SU password real de Odoo
- Sesión sobrevive recargas del browser hasta 8h (sin re-login)
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


# Lista de emails autorizados — fallback si no hay OPS_ALLOWED_EMAILS en Secrets
DEFAULT_ALLOWED_EMAILS = [
    "andres@grupoeter.cl",       # Andrés Browne — Gerencia Operaciones
    "bodega@grupoeter.cl",        # Gerardo Ortega — Bodega
    "gabriela@grupoeter.cl",      # Gabriela Pastran
    "facturacion@melollevo.cl",   # Yohana Grisman
]

SESSION_TTL_HOURS = 8
COOKIE_NAME = "ops_session"


def _get_secret() -> str:
    """Secret HMAC para firmar tokens. Estable entre re-deploys."""
    s = os.environ.get("OPS_AUTH_SECRET", "").strip()
    if s:
        return s
    # Fallback: derivar de LIBSQL_AUTH_TOKEN (siempre presente, no se rota)
    seed = os.environ.get("LIBSQL_AUTH_TOKEN", "") + "|ops_auth_v1"
    return hashlib.sha256(seed.encode()).hexdigest()


def _make_token(email: str, ttl_hours: int = SESSION_TTL_HOURS) -> str:
    """Token HMAC: email|expires|signature."""
    expires = int(time.time()) + ttl_hours * 3600
    msg = f"{email}|{expires}"
    sig = hmac.new(_get_secret().encode(), msg.encode(),
                   hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"


def _verify_token(token: str) -> str | None:
    """Devuelve email si token es válido y no expirado, None si no."""
    if not token:
        return None
    try:
        email, expires_str, sig = token.rsplit("|", 2)
        msg = f"{email}|{expires_str}"
        expected_sig = hmac.new(_get_secret().encode(), msg.encode(),
                                hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        if int(expires_str) < int(time.time()):
            return None  # expirado
        return email
    except Exception:
        return None


def _get_cookie_manager():
    """Singleton de CookieManager para evitar warnings 'duplicate key'."""
    if "_ops_cookie_mgr" not in st.session_state:
        try:
            import extra_streamlit_components as stx
            st.session_state["_ops_cookie_mgr"] = stx.CookieManager(
                key="ops_cookie_mgr_v1"
            )
        except ImportError:
            return None
    return st.session_state["_ops_cookie_mgr"]


def _read_cookie_token() -> str | None:
    """Lee token de cookie. Retorna None si no hay cookie o no se pudo leer."""
    mgr = _get_cookie_manager()
    if mgr is None:
        return None
    try:
        return mgr.get(cookie=COOKIE_NAME)
    except Exception:
        return None


def _write_cookie_token(token: str):
    """Guarda token en cookie con expiración."""
    mgr = _get_cookie_manager()
    if mgr is None:
        return
    try:
        mgr.set(
            COOKIE_NAME, token,
            expires_at=datetime.now() + timedelta(hours=SESSION_TTL_HOURS),
            key=f"set_cookie_{int(time.time())}",
        )
    except Exception as e:
        print(f"[ops_auth] Error guardando cookie: {e}")


def _delete_cookie_token():
    mgr = _get_cookie_manager()
    if mgr is None:
        return
    try:
        mgr.delete(COOKIE_NAME, key=f"del_cookie_{int(time.time())}")
    except Exception:
        pass


def _get_allowed_emails() -> list:
    """Lista de emails autorizados. Prioriza Streamlit Secrets, fallback a hardcoded."""
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
        st.caption("Login con tu usuario Odoo · sesión válida 8 horas")
        st.markdown("---")

        with st.form("ops_login", clear_on_submit=False):
            email = st.text_input("Email Odoo", placeholder="ej: bodega@grupoeter.cl")
            password = st.text_input("Password Odoo", type="password")
            submit = st.form_submit_button("Ingresar", type="primary",
                                           use_container_width=True)

            if submit:
                if not email or not password:
                    st.error("Ingresá email y password")
                    return

                # 1. Validar email autorizado
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

                # Auth OK → guardar en session + cookie persistente
                _set_session(email.strip().lower(), uid)
                token = _make_token(email.strip().lower())
                _write_cookie_token(token)
                st.success(f"✅ Bienvenido. Sesión válida {SESSION_TTL_HOURS}h.")
                time.sleep(0.5)
                st.rerun()

        st.markdown("---")
        st.caption(
            "💡 Usás tu mismo email y password de Odoo. "
            f"La sesión queda válida por {SESSION_TTL_HOURS}h (no necesitás re-login en cada refresh)."
        )


def _set_session(email: str, uid: int):
    """Configura st.session_state como autenticado."""
    st.session_state["ops_authenticated"] = True
    st.session_state["ops_email"] = email
    st.session_state["ops_uid"] = uid
    st.session_state["name"] = email.split("@")[0].title()
    st.session_state["authentication_status"] = True


def require_login_ops():
    """Bloquea la app hasta login. Si hay cookie válida, auto-loguea sin pedir password.

    Si está autenticado: muestra info en sidebar y deja seguir.
    Si no: muestra form de login y st.stop().
    """
    # 1. ¿Ya autenticado en esta sesión Streamlit?
    if st.session_state.get("ops_authenticated"):
        with st.sidebar:
            email = st.session_state.get("ops_email", "")
            st.markdown(f"👤 **{email}**")
            if st.button("Cerrar sesión", use_container_width=True, key="ops_logout"):
                _delete_cookie_token()
                for k in ["ops_authenticated", "ops_email", "ops_uid",
                          "name", "authentication_status"]:
                    st.session_state.pop(k, None)
                st.rerun()
            st.divider()
        return st.session_state["ops_email"]

    # 2. ¿Cookie válida? → auto-login
    token = _read_cookie_token()
    if token:
        email = _verify_token(token)
        if email:
            # Cookie válida → restaurar sesión sin pedir password
            _set_session(email, 0)  # uid no crítico para sesión restaurada
            with st.sidebar:
                st.markdown(f"👤 **{email}**")
                st.caption("🍪 Sesión restaurada")
                if st.button("Cerrar sesión", use_container_width=True,
                             key="ops_logout_cookie"):
                    _delete_cookie_token()
                    for k in ["ops_authenticated", "ops_email", "ops_uid",
                              "name", "authentication_status"]:
                        st.session_state.pop(k, None)
                    st.rerun()
                st.divider()
            return email

    # 3. No autenticado — mostrar form
    _login_form()
    st.stop()
