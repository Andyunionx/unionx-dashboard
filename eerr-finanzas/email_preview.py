"""
Componente reusable de Streamlit para previsualizar y enviar emails.

Uso (dentro de cualquier page):

    from email_preview import preview_y_enviar

    if st.button("📤 Enviar Reporte al CEO"):
        preview_y_enviar(
            asunto="Reporte semanal",
            cuerpo_html="<p>Hola CEO...</p>",
            adjuntos=["data/outputs/reporte_1.xlsx"],
            modo="reporte",  # o "alerta"
        )

Respeta automaticamente la env var GMAIL_DRY_RUN=1 (si esta activa,
crea borrador en lugar de enviar) y muestra el modo en la UI.
"""
import os
import sys
from pathlib import Path
from typing import List, Optional

import streamlit as st


def _get_destinatarios(modo: str) -> str:
    """Devuelve string con destinatarios (TO + CC) segun el modo."""
    if modo == "reporte":
        to = os.environ.get("CEO_EMAIL", "andres@unionx.cl")
        cc = os.environ.get("CEO_CC", "")
    else:  # alerta
        to = os.environ.get("ALERT_EMAIL_TO", "andres@unionx.cl")
        cc = ""
    s = f"To: {to}"
    if cc:
        s += f" | CC: {cc}"
    return s


def preview_y_enviar(
    asunto: str,
    cuerpo_html: str,
    adjuntos: Optional[List[str]] = None,
    modo: str = "reporte",
    key_prefix: str = "email_prev",
) -> Optional[str]:
    """Render del preview + boton confirmar. Devuelve message_id si se envio.

    Args:
        asunto: subject del email
        cuerpo_html: HTML body
        adjuntos: lista de paths
        modo: 'reporte' o 'alerta' (define destinatario y wrapper a usar)
        key_prefix: para evitar colisiones de keys cuando hay multiples preview

    Returns:
        message_id si se envio o creo draft, None si el usuario no confirmo aun.
    """
    is_dry = os.environ.get("GMAIL_DRY_RUN") == "1"

    with st.expander(f"📧 Preview: {asunto}", expanded=True):
        st.markdown(f"**📨 Destinatarios**\n\n`{_get_destinatarios(modo)}`")
        st.markdown(f"**📝 Asunto**\n\n`{asunto}`")

        if adjuntos:
            adj_names = [Path(a).name for a in adjuntos if Path(a).exists()]
            adj_missing = [Path(a).name for a in adjuntos if not Path(a).exists()]
            st.markdown("**📎 Adjuntos**")
            for n in adj_names:
                st.text(f"  ✓ {n}")
            for n in adj_missing:
                st.text(f"  ✗ {n} (no encontrado)")
        else:
            st.markdown("**📎 Adjuntos** — sin adjuntos")

        st.markdown("**👁️ Preview del cuerpo (HTML)**")
        st.components.v1.html(cuerpo_html, height=350, scrolling=True)

        st.markdown("---")
        if is_dry:
            st.warning("📝 **Modo borrador activo** (`GMAIL_DRY_RUN=1`) — quedará en Gmail Borradores.")
        else:
            st.error("🚀 **Modo envío real** — se enviará apenas confirmes.")

        col1, col2 = st.columns([1, 3])
        with col1:
            confirmar = st.button(
                "✅ Confirmar y enviar" if not is_dry else "✅ Crear borrador",
                type="primary",
                key=f"{key_prefix}_confirm",
            )

        if confirmar:
            try:
                # Importar shared_email del project root
                project_root = Path(__file__).resolve().parent.parent
                if str(project_root) not in sys.path:
                    sys.path.insert(0, str(project_root))
                from shared_email import enviar_reporte_ceo, enviar_alerta

                if modo == "reporte":
                    msg_id = enviar_reporte_ceo(asunto, cuerpo_html, adjuntos or [])
                else:
                    # Para alertas: el modulo necesita nombre + urgencia, los infiero del asunto
                    nombre = asunto.replace("[ALERTA", "").split("]", 1)[-1].strip() or "Alerta"
                    urgencia = "CRITICA" if "CRITICA" in asunto.upper() else "MODERADA"
                    msg_id = enviar_alerta(nombre, urgencia, cuerpo_html, adjuntos or [])

                if msg_id and msg_id.startswith("[DRAFT]"):
                    st.success(f"📝 Borrador creado: `{msg_id}`. Revisalo en Gmail.")
                else:
                    st.success(f"📤 Email enviado: `{msg_id}`")
                return msg_id
            except Exception as e:
                st.error(f"❌ Error al enviar: {e}")
                return None
    return None


def construir_html_resumen_reportes(reportes: dict, fecha) -> str:
    """Genera HTML para email de reportes ejecutivos al CEO.

    Args:
        reportes: dict con keys reporte_1, reporte_2, reporte_3 (paths) y alertas (list)
        fecha: datetime
    """
    return f"""
    <div style="font-family: Arial, sans-serif; padding: 20px; max-width: 600px;">
      <h2 style="color: #1F4E79;">📊 Reportes Ejecutivos UnionX</h2>
      <p>Fecha de ejecución: <b>{fecha.strftime('%d/%m/%Y %H:%M')}</b></p>
      <ul>
        <li>Reporte 1 (Rentabilidad): {'✓' if reportes.get('reporte_1') else '—'}</li>
        <li>Reporte 2 (KPIs Operacionales): {'✓' if reportes.get('reporte_2') else '—'}</li>
        <li>Reporte 3 (Planificación Financiera): {'✓' if reportes.get('reporte_3') else '—'}</li>
        <li>Alertas activas: <b>{len(reportes.get('alertas') or [])}</b></li>
      </ul>
      <p style="color: #64748B; font-size: 0.9em;">
        Generado automaticamente desde el dashboard UnionX.
      </p>
    </div>
    """
