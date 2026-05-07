"""
Pagina Alertas - Sistema de alertas en tiempo real (10 criterios).

Muestra:
- Alertas activas (ultima evaluacion)
- Historico (ultimos 90 dias) con drill-down
- Configuracion de thresholds
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
sys.path.insert(0, str(PARENT))

from auth_helper import require_login
require_login()

# Imports despues de auth
from sistema_alertas_tiempo_real import SistemaAlertas, UrgenciaAlerta  # noqa: E402

st.set_page_config(page_title="Alertas - UnionX", page_icon="🚨", layout="wide")
st.title("🚨 Alertas en Tiempo Real")
st.caption("10 criterios automaticos | Persistencia: data/alertas_historial.json")

PROJECT_ROOT = PARENT.parent
HISTORIAL_PATH = PROJECT_ROOT / "data" / "alertas_historial.json"

# === SECCION 1: Resumen ===
sistema = SistemaAlertas()
historial = sistema.historial

col1, col2, col3, col4 = st.columns(4)
hace_24h = datetime.now() - timedelta(hours=24)
recientes_24h = [
    h for h in historial
    if datetime.fromisoformat(h.get("timestamp", "1970-01-01")) >= hace_24h
]

criticas = [h for h in recientes_24h if "CRITICA" in (h.get("urgencia", "")).upper()]
moderadas = [h for h in recientes_24h if "MODERADA" in (h.get("urgencia", "")).upper()]
info = [h for h in recientes_24h if "INFORM" in (h.get("urgencia", "")).upper()]

col1.metric("Total ultimas 24h", len(recientes_24h))
col2.metric("🔴 Criticas", len(criticas))
col3.metric("🟡 Moderadas", len(moderadas))
col4.metric("🔵 Informativas", len(info))

st.divider()

# === SECCION 2: Forzar evaluacion AHORA ===
with st.expander("🔄 Evaluar alertas ahora (manual)"):
    st.write("Fuerza evaluacion contra los datos actuales sin esperar al trigger del Lunes 9 AM.")
    if st.button("Evaluar ahora"):
        try:
            from orquestador_reportes import OrquestadorReportes
            orq = OrquestadorReportes()
            datos = orq._preparar_datos_alertas()
            alertas = sistema.evaluar(
                datos.get('rentabilidad', {}),
                datos.get('operaciones', {}),
                datos.get('comex', {}),
                datos.get('flujo', {}),
            )
            st.success(f"✓ {len(alertas)} alertas detectadas")
            sistema.enviar_alertas()  # respeta dedup + GMAIL_DRY_RUN
            st.info("Email/Slack disparado (o draft si GMAIL_DRY_RUN=1)")
        except Exception as e:
            st.error(f"Error: {e}")

st.divider()

# === SECCION 2.5: Reenviar alertas activas (con preview) ===
if recientes_24h and st.button("📤 Reenviar últimas 24h por email (con preview)"):
    st.session_state.alerts_show_preview = True

if st.session_state.get("alerts_show_preview") and recientes_24h:
    from email_preview import preview_y_enviar
    bullets = "".join(
        f"<li><b>{h.get('id')}</b> - {h.get('nombre')} ({h.get('urgencia')}) "
        f"valor={h.get('valor_actual')}</li>"
        for h in recientes_24h[:50]
    )
    cuerpo = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
      <h2 style="color:#d32f2f;">🚨 Alertas activas - últimas 24h</h2>
      <p>Total: <b>{len(recientes_24h)}</b> (Críticas: {len(criticas)} · Moderadas: {len(moderadas)} · Info: {len(info)})</p>
      <ul>{bullets}</ul>
    </div>
    """
    result = preview_y_enviar(
        asunto=f"[ALERTAS] Resumen 24h UnionX - {datetime.now().strftime('%d/%m/%Y')}",
        cuerpo_html=cuerpo,
        modo="alerta",
        key_prefix="alerts_resend",
    )
    if result:
        st.session_state.alerts_show_preview = False

st.divider()

# === SECCION 3: Historial ===
st.subheader("📜 Historial de alertas")
if not historial:
    st.info("Aun no hay historial. Las alertas se registraran a partir de la primera evaluacion.")
else:
    import pandas as pd
    df = pd.DataFrame(historial)
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df = df.sort_values('timestamp', ascending=False)

    # Filtros
    fcol1, fcol2 = st.columns(2)
    dias = fcol1.slider("Ultimos N dias", 1, 90, 7)
    urgencias = fcol2.multiselect("Urgencia", df['urgencia'].dropna().unique().tolist(),
                                   default=df['urgencia'].dropna().unique().tolist())

    cutoff = datetime.now() - timedelta(days=dias)
    df_filt = df[(df['timestamp'] >= cutoff) & (df['urgencia'].isin(urgencias))]

    st.dataframe(df_filt, use_container_width=True, hide_index=True)
    st.caption(f"Mostrando {len(df_filt)} de {len(df)} entradas totales")

st.divider()

# === SECCION 4: Configuracion thresholds ===
st.subheader("⚙️ Thresholds configurados")
thresholds = SistemaAlertas.THRESHOLDS
for alerta_id, params in thresholds.items():
    with st.expander(f"{alerta_id}"):
        for k, v in params.items():
            st.write(f"**{k}**: `{v}`")

st.caption("Editar thresholds: modificar `SistemaAlertas.THRESHOLDS` en `eerr-finanzas/sistema_alertas_tiempo_real.py`")
