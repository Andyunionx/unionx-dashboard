"""
Vista Seguridad del Sistema — gestión de usuarios + auditoría.

- Lista de usuarios autorizados (Streamlit Secrets)
- Cambio de password del usuario actual
- Estado de credenciales del sistema (sin mostrar valores)
- Información de la sesión actual
- Links útiles a paneles de administración
"""
from datetime import datetime

import streamlit as st


def _check_secret_present(name: str) -> dict:
    """Verifica si un secret está presente. NO muestra el valor."""
    if name in st.secrets:
        val = str(st.secrets.get(name, ''))
        return {'presente': True, 'longitud': len(val), 'preview': val[:8] + '...' if len(val) > 8 else '***'}
    return {'presente': False, 'longitud': 0, 'preview': '—'}


def render():
    with st.sidebar:
        st.markdown("### 🔐 **Seguridad**")
        st.caption("Gestión de usuarios + auditoría")
        st.markdown("---")

    st.title("🔐 Seguridad del Sistema")
    st.caption("Gestión de usuarios autorizados + estado de credenciales")

    tab1, tab2, tab3 = st.tabs([
        "👥 Usuarios",
        "🔑 Mi cuenta",
        "🛡️ Credenciales del sistema",
    ])

    # ============================================================
    # TAB 1: USUARIOS
    # ============================================================
    with tab1:
        st.markdown("### Usuarios autorizados")
        st.caption("Estos usuarios pueden acceder al dashboard. Se gestionan en Streamlit Cloud → Secrets.")

        # Sesión actual
        nombre_actual = st.session_state.get('name', '?')
        usuario_actual = st.session_state.get('username', '?')
        st.info(f"👤 **Sesión actual**: `{usuario_actual}` ({nombre_actual})")

        st.divider()

        # Lista usuarios desde Secrets
        if 'auth' not in st.secrets or 'credentials' not in st.secrets['auth']:
            st.warning("No se encuentra config de auth en Secrets")
            return

        usernames = st.secrets['auth']['credentials'].get('usernames', {})
        if not usernames:
            st.warning("No hay usuarios configurados")
            return

        # Tabla
        st.markdown(f"**Total usuarios autorizados: {len(usernames)}**")
        for username, data in usernames.items():
            with st.container():
                c1, c2, c3, c4 = st.columns([1, 2, 2, 1])
                with c1:
                    if username == usuario_actual:
                        st.markdown("### 🟢")
                    else:
                        st.markdown("### 👤")
                with c2:
                    st.markdown(f"**{data.get('name', username)}**")
                    st.caption(f"@{username}")
                with c3:
                    st.markdown(data.get('email', '—'))
                with c4:
                    if username == usuario_actual:
                        st.caption("**Tú**")
            st.divider()

        # Pre-autorizados
        if 'preauthorized' in st.secrets['auth']:
            with st.expander("Emails pre-autorizados (registro libre)"):
                emails = st.secrets['auth']['preauthorized'].get('emails', [])
                for email in emails:
                    st.markdown(f"- {email}")

        st.divider()

        st.markdown("### ➕ Agregar usuario nuevo")
        st.markdown("""
        Para agregar un usuario:
        1. Generar hash bcrypt del password (te lo puedo generar yo si me pasas el password en plano)
        2. Pegar este bloque al final de Streamlit Cloud Secrets:

        ```toml
        [auth.credentials.usernames.NUEVO_USUARIO]
        email = "persona@unionx.cl"
        name = "Nombre Apellido"
        password = "$2b$12$...hash..."
        ```

        3. Agregar el email al bloque `[auth.preauthorized]`
        4. Save → Streamlit reinicia en ~30s
        """)

    # ============================================================
    # TAB 2: MI CUENTA
    # ============================================================
    with tab2:
        st.markdown("### Información de mi sesión")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Usuario", usuario_actual)
            st.metric("Nombre", nombre_actual)
        with col2:
            email = ''
            if 'auth' in st.secrets and 'credentials' in st.secrets['auth']:
                user_data = st.secrets['auth']['credentials'].get('usernames', {}).get(usuario_actual, {})
                email = user_data.get('email', '—')
            st.metric("Email", email)
            st.metric("Estado", "🟢 Autenticado")

        st.divider()

        st.markdown("### Cambiar mi password")
        st.caption("Por seguridad, cambiá el password temporal por uno propio. (Hoy esto pide al admin que actualice los Secrets — no es self-service automático aún.)")

        with st.form("cambiar_pwd"):
            current = st.text_input("Password actual", type="password")
            new1 = st.text_input("Nuevo password", type="password")
            new2 = st.text_input("Repetir nuevo password", type="password")
            submitted = st.form_submit_button("Generar hash + instrucciones")

            if submitted:
                if not new1 or not new2:
                    st.error("Ingresá el nuevo password en ambos campos")
                elif new1 != new2:
                    st.error("Los passwords no coinciden")
                elif len(new1) < 8:
                    st.error("Mínimo 8 caracteres")
                else:
                    try:
                        import bcrypt
                        hash_new = bcrypt.hashpw(new1.encode(), bcrypt.gensalt()).decode()
                        st.success("Hash generado.")
                        st.markdown("### Pasos para activarlo:")
                        st.markdown(f"""
                        1. Abrir https://share.streamlit.io/ → app → ⋮ → Settings → Secrets
                        2. Buscar el bloque `[auth.credentials.usernames.{usuario_actual}]`
                        3. Reemplazar la línea `password = "..."` por:
                        """)
                        st.code(f'password = "{hash_new}"', language='toml')
                        st.markdown("4. Save changes → Streamlit reinicia en ~30s → ya podés loguear con tu nuevo password")
                        st.info("⚠️ El admin del Streamlit Cloud (Andrés) debe hacer este paso. Si no sos admin, mandale el hash.")
                    except ImportError:
                        st.error("Falta paquete bcrypt en requirements.txt")

        st.divider()
        st.markdown("### Cerrar sesión")
        if st.button("🚪 Cerrar sesión", type="primary"):
            st.session_state['authentication_status'] = None
            st.rerun()

    # ============================================================
    # TAB 3: CREDENCIALES DEL SISTEMA
    # ============================================================
    with tab3:
        st.markdown("### Estado de credenciales")
        st.caption("Solo se muestra si el secret está presente. **Los valores nunca se exponen.**")

        secrets_critical = [
            ('LIBSQL_URL', 'Conexión Turso DB cloud', '🗄️'),
            ('LIBSQL_AUTH_TOKEN', 'Token Turso DB cloud', '🔑'),
            ('ANDRES_ODOO_PASSWORD', 'Password Odoo (Stock LIVE + Sync)', '🏢'),
            ('RESEND_API_KEY', 'API Resend (email diario)', '✉️'),
        ]

        for name, desc, icon in secrets_critical:
            check = _check_secret_present(name)
            col1, col2, col3, col4 = st.columns([1, 3, 3, 1])
            with col1:
                st.markdown(f"## {'🟢' if check['presente'] else '🔴'}")
            with col2:
                st.markdown(f"{icon} **{name}**")
                st.caption(desc)
            with col3:
                if check['presente']:
                    st.caption(f"Preview: `{check['preview']}` · longitud {check['longitud']}")
                else:
                    st.error("⚠️ NO seteado")
            with col4:
                pass

        st.divider()

        # Bloques compuestos
        st.markdown("### Bloques compuestos")
        col1, col2 = st.columns(2)

        with col1:
            present_gcp = 'gcp_service_account' in st.secrets
            st.markdown(f"## {'🟢' if present_gcp else '🔴'} `[gcp_service_account]`")
            st.caption("Service Account Google (Contribución)")
            if present_gcp:
                email_sa = st.secrets['gcp_service_account'].get('client_email', '?')
                st.caption(f"SA: `{email_sa}`")

        with col2:
            present_auth = 'auth' in st.secrets and 'credentials' in st.secrets['auth']
            st.markdown(f"## {'🟢' if present_auth else '🔴'} `[auth.credentials]`")
            st.caption("Usuarios + cookie de sesión")
            if present_auth:
                n_users = len(st.secrets['auth']['credentials'].get('usernames', {}))
                st.caption(f"{n_users} usuarios configurados")

        st.divider()

        st.markdown("### 🔗 Links de administración")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.link_button("🔐 Streamlit Secrets",
                           "https://share.streamlit.io/", use_container_width=True)
        with col2:
            st.link_button("☁️ Turso Console",
                           "https://app.turso.tech/", use_container_width=True)
        with col3:
            st.link_button("📧 Resend Dashboard",
                           "https://resend.com/dashboard", use_container_width=True)

        st.markdown(f"*Última carga: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
