"""
📦 Existencias — memoria de la auditoría de inventario.

El contenido NO vive en este repositorio (es público): es un adjunto privado de Odoo
(ir.attachment sin registro asociado), que Odoo solo deja leer a quien lo creó y a los
administradores. La página pide la clave de Odoo y lo lee con el usuario de la sesión,
así que el control de acceso lo hace Odoo y no depende de credenciales guardadas.

Visible solo para CONT_EXISTENCIAS_EMAILS (secret) o, por defecto, Andrés.
"""
import base64
import os

import requests
import streamlit as st

from views._cont_auth import get_cont_user

ADJUNTO = "MEMORIA_AUDITORIA_EXISTENCIAS.md"
DEFAULT_EMAILS = ["andres@grupoeter.cl", "andres@unionx.cl"]


def emails_autorizados() -> list[str]:
    try:
        val = st.secrets.get("CONT_EXISTENCIAS_EMAILS")
    except Exception:
        val = None
    if isinstance(val, str) and val.strip():
        return [e.strip().lower() for e in val.split(",") if e.strip()]
    if isinstance(val, (list, tuple)) and val:
        return [str(e).strip().lower() for e in val]
    return DEFAULT_EMAILS


def puede_ver(email: str | None) -> bool:
    return bool(email) and email.lower() in emails_autorizados()


def _rpc(url: str, service: str, method: str, args: list):
    r = requests.post(f"{url}/jsonrpc", timeout=60, json={
        "jsonrpc": "2.0", "method": "call", "id": 1,
        "params": {"service": service, "method": method, "args": args}})
    j = r.json()
    if "error" in j:
        msg = j["error"].get("data", {}).get("message") or j["error"].get("message", "")
        raise RuntimeError(msg)
    return j["result"]


def _leer_memoria(login: str, password: str) -> dict:
    url = os.environ.get("ODOO_URL", "https://unionxb2b.odoo.com")
    db = os.environ.get("ODOO_DB", "bmya-innovatek-sh-prd-6981800")
    uid = _rpc(url, "common", "login", [db, login, password])
    if not uid:
        raise PermissionError("Clave de Odoo incorrecta.")
    res = _rpc(url, "object", "execute_kw", [db, uid, password, "ir.attachment", "search_read",
               [[("name", "=", ADJUNTO), ("res_model", "=", False)]],
               {"fields": ["datas", "write_date"], "order": "write_date desc", "limit": 1}])
    if not res:
        raise FileNotFoundError("Tu usuario de Odoo no tiene acceso a la memoria, o todavía no está cargada.")
    return {"texto": base64.b64decode(res[0]["datas"]).decode("utf-8"),
            "actualizado": res[0]["write_date"]}


def render():
    user = get_cont_user() or {}
    if not puede_ver(user.get("email")):
        st.warning("Esta sección no está habilitada para tu usuario.")
        return

    st.markdown("## 📦 Existencias · memoria de auditoría")

    memo = st.session_state.get("_cont_memoria_existencias")
    if memo is None:
        st.caption("El documento se guarda en Odoo, no en la app. Ingresa tu clave de Odoo para abrirlo.")
        with st.form("cont_memo_existencias"):
            clave = st.text_input("Clave de Odoo", type="password")
            abrir = st.form_submit_button("Abrir memoria", type="primary")
        if not abrir:
            return
        if not clave:
            st.error("Ingresa tu clave de Odoo.")
            return
        try:
            with st.spinner("Leyendo desde Odoo…"):
                memo = _leer_memoria(user["email"], clave)
        except Exception as e:
            st.error(str(e) or "No se pudo leer la memoria.")
            return
        st.session_state["_cont_memoria_existencias"] = memo

    c1, c2 = st.columns([4, 1])
    c1.caption(f"Versión cargada en Odoo el {memo['actualizado'][:16]} UTC")
    if c2.button("Recargar", key="cont_memo_recargar"):
        st.session_state.pop("_cont_memoria_existencias", None)
        st.rerun()
    st.download_button("Descargar (.md)", memo["texto"].encode("utf-8"),
                       file_name="MEMORIA_AUDITORIA_EXISTENCIAS.md", mime="text/markdown")
    st.divider()
    st.markdown(memo["texto"])
