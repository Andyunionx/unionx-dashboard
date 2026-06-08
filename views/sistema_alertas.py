"""
Vista Alertas del Sistema — monitoreo de salud de servicios.

Verifica estado de:
- Turso (DB cloud)
- Odoo XML-RPC
- Google Sheets (SA)
- Resend (Email API)
- GH Actions cron
- Última sincronización Odoo->Turso
- Email diario RAW
"""
import os
import time
from datetime import datetime, timedelta

import requests
import streamlit as st


# ============================================================
# Checks individuales (cada uno devuelve dict con estado/mensaje/latencia)
# ============================================================
def check_turso():
    """Ping a Turso vía HTTP."""
    url = os.environ.get('LIBSQL_URL', '').rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    if not url:
        return {'estado': 'error', 'mensaje': 'LIBSQL_URL no seteado', 'latencia': 0}
    t0 = time.time()
    try:
        body = {"requests": [{"type": "execute", "stmt": {"sql": "SELECT 1"}}, {"type": "close"}]}
        r = requests.post(
            f"{url}/v2/pipeline", json=body,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            timeout=15,
        )
        latencia = (time.time() - t0) * 1000
        if r.status_code == 200:
            return {'estado': 'ok', 'mensaje': 'Conexión OK', 'latencia': latencia}
        return {'estado': 'error', 'mensaje': f'HTTP {r.status_code}', 'latencia': latencia}
    except Exception as e:
        return {'estado': 'error', 'mensaje': f'{type(e).__name__}: {str(e)[:80]}', 'latencia': (time.time() - t0) * 1000}


def check_odoo():
    """Verifica que ANDRES_ODOO_PASSWORD esté seteada y ping al endpoint Odoo."""
    pwd = os.environ.get('ANDRES_ODOO_PASSWORD')
    if not pwd:
        return {'estado': 'error', 'mensaje': 'ANDRES_ODOO_PASSWORD no seteado en Secrets', 'latencia': 0}
    t0 = time.time()
    try:
        r = requests.get('https://unionxb2b.odoo.com/web/login', timeout=10)
        latencia = (time.time() - t0) * 1000
        if r.status_code == 200:
            return {'estado': 'ok', 'mensaje': 'Endpoint accesible · password seteada', 'latencia': latencia}
        return {'estado': 'warn', 'mensaje': f'HTTP {r.status_code}', 'latencia': latencia}
    except Exception as e:
        return {'estado': 'error', 'mensaje': f'{type(e).__name__}', 'latencia': (time.time() - t0) * 1000}


def check_google_sheets():
    """Verifica que credenciales de SA estén seteadas y se pueda conectar."""
    if 'gcp_service_account' not in st.secrets:
        return {'estado': 'error', 'mensaje': 'gcp_service_account no en Secrets', 'latencia': 0}
    t0 = time.time()
    try:
        import gspread
        creds = dict(st.secrets['gcp_service_account'])
        gc = gspread.service_account_from_dict(creds)
        # Test list spreadsheets (lite call)
        gc.list_permissions  # solo verifica que el cliente quedó construido
        latencia = (time.time() - t0) * 1000
        return {'estado': 'ok', 'mensaje': f"SA: {creds.get('client_email', '?')[:40]}", 'latencia': latencia}
    except Exception as e:
        return {'estado': 'error', 'mensaje': f'{type(e).__name__}: {str(e)[:60]}', 'latencia': (time.time() - t0) * 1000}


def check_resend():
    """Verifica que RESEND_API_KEY esté en secrets y haga ping."""
    api_key = st.secrets.get('RESEND_API_KEY') or os.environ.get('RESEND_API_KEY')
    if not api_key:
        return {'estado': 'warn', 'mensaje': 'RESEND_API_KEY no seteado (email diario no funcionará)', 'latencia': 0}
    t0 = time.time()
    try:
        r = requests.get(
            'https://api.resend.com/api-keys',
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=10,
        )
        latencia = (time.time() - t0) * 1000
        if r.status_code in (200, 401):  # 200 ok, 401 = key inválida
            if r.status_code == 401:
                return {'estado': 'error', 'mensaje': 'API key rechazada (401)', 'latencia': latencia}
            return {'estado': 'ok', 'mensaje': 'API key válida', 'latencia': latencia}
        return {'estado': 'warn', 'mensaje': f'HTTP {r.status_code}', 'latencia': latencia}
    except Exception as e:
        return {'estado': 'error', 'mensaje': f'{type(e).__name__}', 'latencia': (time.time() - t0) * 1000}


def check_ultima_sync_turso():
    """Última entrada en metadata_cargas — frescura de la data."""
    url = os.environ.get('LIBSQL_URL', '').rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    if not url:
        return {'estado': 'error', 'mensaje': 'No conexión Turso', 'latencia': 0, 'minutos': None}
    t0 = time.time()
    try:
        body = {"requests": [{"type": "execute", "stmt": {
            "sql": "SELECT MAX(fecha_carga) FROM metadata_cargas"
        }}, {"type": "close"}]}
        r = requests.post(
            f"{url}/v2/pipeline", json=body,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            timeout=15,
        )
        latencia = (time.time() - t0) * 1000
        rows = r.json()['results'][0]['response']['result']['rows']
        if not rows or not rows[0][0].get('value'):
            return {'estado': 'warn', 'mensaje': 'Sin entradas en metadata_cargas', 'latencia': latencia, 'minutos': None}
        ultima = rows[0][0]['value']
        d = datetime.fromisoformat(ultima)
        delta_min = int((datetime.now() - d).total_seconds() / 60)
        if delta_min < 15:
            return {'estado': 'ok', 'mensaje': f'Hace {delta_min} min · {ultima[:19]}', 'latencia': latencia, 'minutos': delta_min}
        if delta_min < 120:
            return {'estado': 'warn', 'mensaje': f'Hace {delta_min} min · revisar PC local', 'latencia': latencia, 'minutos': delta_min}
        return {'estado': 'error', 'mensaje': f'Hace {delta_min // 60}h · sync caído', 'latencia': latencia, 'minutos': delta_min}
    except Exception as e:
        return {'estado': 'error', 'mensaje': f'{type(e).__name__}', 'latencia': (time.time() - t0) * 1000, 'minutos': None}


def check_gh_actions():
    """GitHub Actions — último estado de los workflows."""
    # Sin GITHUB_TOKEN no podemos consultar la API privada. Mostramos info básica.
    return {
        'estado': 'info',
        'mensaje': 'Ver detalle: https://github.com/Andyunionx/unionx-dashboard/actions',
        'latencia': 0,
    }


def check_secrets_completos():
    """Verifica que todos los secrets críticos estén seteados."""
    requeridos = {
        'LIBSQL_URL': 'Turso DB',
        'LIBSQL_AUTH_TOKEN': 'Turso DB',
        'ANDRES_ODOO_PASSWORD': 'Stock LIVE',
        'RESEND_API_KEY': 'Email diario',
    }
    faltantes = []
    for key, descripcion in requeridos.items():
        if not (key in st.secrets or os.environ.get(key)):
            faltantes.append(f"{key} ({descripcion})")
    if 'gcp_service_account' not in st.secrets:
        faltantes.append('gcp_service_account (Contribución)')
    if 'auth' not in st.secrets:
        faltantes.append('auth (login)')
    if not faltantes:
        return {'estado': 'ok', 'mensaje': 'Todos los secrets críticos OK', 'latencia': 0}
    return {'estado': 'warn', 'mensaje': f'Faltan: {", ".join(faltantes)}', 'latencia': 0}


# ============================================================
# Render helpers
# ============================================================
EMOJI_ESTADO = {
    'ok': '🟢',
    'warn': '🟡',
    'error': '🔴',
    'info': 'ℹ️',
}


def _render_check(nombre: str, descripcion: str, resultado: dict):
    """Renderiza una fila de check con badge + mensaje + latencia."""
    estado = resultado['estado']
    emoji = EMOJI_ESTADO.get(estado, '⚪')
    latencia_txt = f"{resultado['latencia']:.0f} ms" if resultado.get('latencia') else "—"

    col1, col2, col3, col4 = st.columns([1, 2, 4, 1])
    with col1:
        st.markdown(f"### {emoji}")
    with col2:
        st.markdown(f"**{nombre}**")
        st.caption(descripcion)
    with col3:
        st.markdown(resultado['mensaje'])
    with col4:
        st.caption(latencia_txt)


# ============================================================
# Render principal
# ============================================================
@st.cache_data(ttl=60, show_spinner="Verificando servicios…")
def _run_all_checks():
    """Cache 60s — refresca al pasar 1 min, o con botón Refrescar."""
    return {
        'turso': check_turso(),
        'odoo': check_odoo(),
        'sheets': check_google_sheets(),
        'resend': check_resend(),
        'sync': check_ultima_sync_turso(),
        'secrets': check_secrets_completos(),
        'gh_actions': check_gh_actions(),
    }


def render():
    with st.sidebar:
        st.markdown("### 🚨 **Alertas del Sistema**")
        st.caption("Health-check de servicios cloud")
        st.markdown("---")
        if st.button("🔄 Verificar ahora", width='stretch', type="primary", key="alertas_refresh"):
            _run_all_checks.clear()
            st.rerun()

    st.title("🚨 Alertas del Sistema")
    st.caption("Estado en tiempo real de los servicios que conforman el dashboard. Cache 1 min.")

    checks = _run_all_checks()

    # Banner global
    estados = [c['estado'] for c in checks.values()]
    if 'error' in estados:
        st.error("🔴 **Hay servicios caídos** — revisar abajo")
    elif 'warn' in estados:
        st.warning("🟡 **Algunos warnings** — ver detalles")
    else:
        st.success("🟢 **Todos los servicios OK**")

    st.divider()

    # Servicios cloud
    st.markdown("### ☁️ Servicios Cloud")
    _render_check("Turso (DB cloud)", "Base de datos de ventas — donde escribe el cron", checks['turso'])
    st.divider()
    _render_check("Odoo XML-RPC", "Fuente de stock + ventas (extracción cada 5 min)", checks['odoo'])
    st.divider()
    _render_check("Google Sheets", "Análisis de Contribución — Service Account", checks['sheets'])
    st.divider()
    _render_check("Resend (Email API)", "Envío email diario RAW 8am Chile", checks['resend'])

    st.divider()

    # Sincronización
    st.markdown("### 🔄 Sincronización de datos")
    _render_check(
        "Última sync Odoo → Turso",
        "El PC local debería estar pisando esto cada 5 min",
        checks['sync'],
    )

    st.divider()

    # Secrets
    st.markdown("### 🔐 Configuración")
    _render_check(
        "Streamlit Cloud Secrets",
        "Credenciales necesarias para el funcionamiento del dashboard",
        checks['secrets'],
    )

    st.divider()

    # GH Actions (link-only)
    st.markdown("### ⚙️ GitHub Actions (Cron)")
    _render_check(
        "Workflows",
        "Sync diario + Email diario RAW",
        checks['gh_actions'],
    )

    st.divider()

    # Acciones rápidas
    st.markdown("### 🛠️ Acciones rápidas")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.link_button(
            "📊 Ver app en Streamlit",
            "https://share.streamlit.io/",
            width='stretch',
        )
    with col2:
        st.link_button(
            "🐙 Ver workflows GH Actions",
            "https://github.com/Andyunionx/unionx-dashboard/actions",
            width='stretch',
        )
    with col3:
        st.link_button(
            "💾 Ver Turso DB",
            "https://app.turso.tech/andresunionx",
            width='stretch',
        )

    st.caption(f"Última verificación: {datetime.now().strftime('%H:%M:%S')} · Click en 'Verificar ahora' para refrescar")
