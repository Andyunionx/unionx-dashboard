"""
Vista Alertas de Negocio — sincronizadas con app Operaciones.

Lee tabla `alertas` de Turso. Compartida con https://unionx-operaciones.streamlit.app/
"""
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from views.alertas_helper import (
    listar_alertas, marcar_resuelta, contar_abiertas, crear_tabla_alertas,
)


SEVERITY_BADGE = {
    'critical': ('🔴', '#DC2626', '#FEE2E2'),
    'warning':  ('🟡', '#EA580C', '#FEF3C7'),
    'info':     ('🔵', '#1E40AF', '#DBEAFE'),
}


def _render_alerta_card(alerta: dict):
    sev = alerta.get('severity', 'info')
    emoji, border_color, bg_color = SEVERITY_BADGE.get(sev, SEVERITY_BADGE['info'])
    fecha = alerta.get('fecha_creada', '')[:19].replace('T', ' ')
    target = alerta.get('target_apps', '')
    contexto = alerta.get('contexto') or {}

    # Tarjeta visual
    st.markdown(f"""
    <div style="background:{bg_color};border-left:4px solid {border_color};padding:14px 18px;margin:8px 0;border-radius:6px;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;">
            <div style="flex:1;">
                <div style="font-size:1.05rem;font-weight:600;color:#1E293B;">
                    {emoji} {alerta.get('titulo', '?')}
                </div>
                <div style="font-size:0.85rem;color:#475569;margin-top:4px;">
                    {alerta.get('mensaje', '')}
                </div>
                <div style="font-size:0.7rem;color:#94A3B8;margin-top:6px;">
                    #{alerta['id']} · {fecha} · target: {target} · tipo: {alerta.get('tipo')}
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Botones de acción
    c1, c2, c3, c4 = st.columns([1, 1, 1, 4])
    with c1:
        if st.button("✓ Resolver", key=f"res_{alerta['id']}"):
            usuario = st.session_state.get('username', '?')
            if marcar_resuelta(alerta['id'], usuario, status='resuelta'):
                st.success(f"Alerta #{alerta['id']} resuelta")
                st.cache_data.clear()
                st.rerun()
    with c2:
        if st.button("👁 Reconocer", key=f"ack_{alerta['id']}"):
            usuario = st.session_state.get('username', '?')
            if marcar_resuelta(alerta['id'], usuario, status='reconocida'):
                st.info(f"Alerta #{alerta['id']} reconocida")
                st.cache_data.clear()
                st.rerun()
    with c3:
        if contexto:
            with st.popover("📋 Contexto"):
                st.json(contexto)


@st.cache_data(ttl=120)  # cache 2 min
def _cargar_alertas(target_app, status):
    return listar_alertas(target_app=target_app, status=status, limit=200)


@st.cache_data(ttl=120)
def _contar_abiertas(target_app):
    return contar_abiertas(target_app=target_app)


def _render_view(target_app: str, key_prefix: str):
    """Render compartido. target_app filtra alertas a 'ventas' u 'operaciones'."""
    crear_tabla_alertas()

    with st.sidebar:
        st.markdown("### 🔔 **Alertas Negocio**")
        st.caption(f"App actual: {target_app} · bus compartido")
        st.markdown("---")
        if st.button("🔄 Refrescar", width='stretch', type="primary", key=f"{key_prefix}_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("🔔 Alertas de Negocio")
    st.caption(f"Filtradas para target_app='{target_app}'. Bus Turso compartido entre Ventas y Operaciones.")

    counts = _contar_abiertas(target_app=target_app)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Críticas", counts['critical'])
    c2.metric("🟡 Warnings", counts['warning'])
    c3.metric("🔵 Info", counts['info'])
    c4.metric("📊 Total abiertas", counts['total'])

    if counts['total'] == 0:
        st.success("✅ No hay alertas abiertas. Todo en orden.")
        with st.expander("Ver alertas resueltas (últimas 50)"):
            cerradas = _cargar_alertas(target_app=target_app, status='resuelta')[:50]
            if cerradas:
                df = pd.DataFrame([{
                    'ID': a['id'],
                    'Tipo': a['tipo'],
                    'Severity': a['severity'],
                    'Título': a['titulo'],
                    'Creada': a['fecha_creada'][:19].replace('T', ' '),
                } for a in cerradas])
                st.dataframe(df, width='stretch', hide_index=True)
            else:
                st.caption("Sin histórico aún.")
        return

    st.divider()

    tab_crit, tab_warn, tab_info, tab_all = st.tabs([
        f"🔴 Críticas ({counts['critical']})",
        f"🟡 Warnings ({counts['warning']})",
        f"🔵 Info ({counts['info']})",
        "📋 Todas",
    ])
    abiertas = _cargar_alertas(target_app=target_app, status='open')

    with tab_crit:
        criticas = [a for a in abiertas if a['severity'] == 'critical']
        if not criticas:
            st.success("✅ Sin alertas críticas")
        for a in criticas:
            _render_alerta_card(a)
    with tab_warn:
        warns = [a for a in abiertas if a['severity'] == 'warning']
        if not warns:
            st.success("✅ Sin warnings")
        for a in warns:
            _render_alerta_card(a)
    with tab_info:
        infos = [a for a in abiertas if a['severity'] == 'info']
        if not infos:
            st.info("Sin alertas informativas")
        for a in infos:
            _render_alerta_card(a)
    with tab_all:
        for a in abiertas:
            _render_alerta_card(a)

    st.divider()

    with st.expander("📜 Historial reciente de alertas resueltas (últimas 30)"):
        resueltas = _cargar_alertas(target_app=target_app, status='resuelta')[:30]
        if resueltas:
            df = pd.DataFrame([{
                'ID': a['id'],
                'Severity': a['severity'],
                'Título': a['titulo'],
                'Resuelta': a.get('contexto', {}).get('resuelta_por', '?'),
                'Creada': a['fecha_creada'][:19].replace('T', ' '),
            } for a in resueltas])
            st.dataframe(df, width='stretch', hide_index=True, height=300)
        else:
            st.caption("Sin histórico")


def render():
    """Vista para app de Ventas."""
    _render_view(target_app='ventas', key_prefix='alert_neg_ventas')


def render_ops():
    """Vista para app de Operaciones."""
    _render_view(target_app='operaciones', key_prefix='alert_neg_ops')
