"""
Helper centralizado de autenticacion para todas las paginas.
Uso en cada pagina:

    from auth_helper import require_login, get_user_roles, has_role
    authenticator, username, name = require_login()
    roles = get_user_roles(username)
    if has_role(roles, 'admin'):
        # mostrar tab admin
"""
import os
from typing import List

import yaml
import streamlit as st
import streamlit_authenticator as stauth
from yaml.loader import SafeLoader

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "auth_config.yaml")


def get_user_roles(username: str) -> List[str]:
    """Devuelve lista de roles del usuario segun auth_config.yaml.

    Lectura directa (sin cache) para reflejar cambios en el yaml sin reiniciar.
    """
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.load(f, Loader=SafeLoader)
        return cfg.get("credentials", {}).get("usernames", {}).get(username, {}).get("roles", []) or []
    except Exception:
        return []


def has_role(roles: List[str], required: str) -> bool:
    """True si `required` esta en la lista de roles. Case-sensitive."""
    return required in (roles or [])


def has_any_role(roles: List[str], required_any: List[str]) -> bool:
    """True si al menos uno de los roles requeridos esta presente."""
    rs = set(roles or [])
    return any(r in rs for r in required_any)


@st.cache_data
def _load_config():
    """Solo el YAML se cachea — es data pura, sin widgets."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=SafeLoader)


def _load_authenticator():
    # Authenticate() internamente crea un CookieController (widget),
    # por eso NO puede ir dentro de @st.cache_resource.
    # Se instancia en cada rerun — es barato.
    config = _load_config()
    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )
    return authenticator, config


def require_login():
    """
    Muestra pantalla de login si no hay sesion.
    Si esta autenticado, retorna (authenticator, username, name).
    Si NO, detiene el script con st.stop().
    """
    authenticator, config = _load_authenticator()

    # Renderiza el widget de login (controla el estado en st.session_state)
    try:
        authenticator.login(
            location="main",
            fields={
                "Form name": "Acceso Dashboard UnionX",
                "Username": "Usuario",
                "Password": "Contrasena",
                "Login": "Ingresar",
            },
        )
    except Exception as e:
        st.error(f"Error de autenticacion: {e}")
        st.stop()

    auth_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")
    name = st.session_state.get("name")

    if auth_status is False:
        st.error("Usuario o contrasena incorrectos")
        st.stop()
    if auth_status is None:
        st.info("Por favor ingresa tus credenciales")
        st.stop()

    # Autenticado: agregar widget de logout en sidebar
    with st.sidebar:
        st.markdown(f"**Usuario:** {name}")
        authenticator.logout("Cerrar sesion", location="sidebar")
        st.markdown("---")

    return authenticator, username, name
