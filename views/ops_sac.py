"""
Vista SAC — Servicio al Cliente.

Estado: PLACEHOLDER hasta Helpdesk H2.
Todo aquí requiere integración con un sistema de tickets (Zendesk/Freshdesk).
"""
import streamlit as st


def render():
    st.title("💬 SAC — Servicio al Cliente")
    st.caption(
        "Plan Estratégico · FRT ≤1h · FCR ≥70% · NPS ≥50 · CSAT ≥4.3/5 · "
        "Tickets/pedido ≤0.10 · % Self-service ≥30%"
    )

    st.warning(
        "🟠 **Bloqueado por integración H2.** Todos los KPIs de SAC requieren un Helpdesk "
        "omnicanal (Zendesk, Freshdesk, Help Scout). Hoy no hay sistema de tickets unificado."
    )

    st.divider()

    kpis = [
        ("FRT — First Response Time", "≤ 1 hora horario hábil", "Tiempo promedio primera respuesta"),
        ("FCR — First Contact Resolution", "≥ 70%", "% casos resueltos en 1er contacto"),
        ("AHT — Average Handle Time", "Optimización continua", "Tiempo promedio resolución por canal"),
        ("CSAT", "≥ 4.3 / 5", "Satisfacción post-atención"),
        ("NPS", "≥ 50", "Net Promoter Score post-experiencia"),
        ("Tickets / pedido", "≤ 0.10", "N° tickets / N° pedidos"),
        ("% Consultas autoservicio", "≥ 30%", "Resueltas vía bot/FAQ sin agente"),
    ]

    import pandas as pd
    df = pd.DataFrame(kpis, columns=["KPI", "Meta", "Definición"])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    st.markdown("### 🛣️ Roadmap SAC")
    st.markdown("""
- **🟠 H2 (3-6 meses):** Implementar Helpdesk omnicanal (Zendesk recomendado por integraciones existentes)
  - Ingestión de WhatsApp Business API
  - Email + formulario web + marketplaces (ML, Falabella) en una vista única
  - Tipificación obligatoria por motivo de contacto
- **🟠 H2:** Página self-service de tracking de pedido (reduce tickets repetitivos 20-30%)
- **🟠 H2:** FAQ robusto + chatbot para consultas frecuentes
- **🔵 H3:** Voice of Customer estructurado: ciclo formal donde tickets alimentan mejoras producto/operación
    """)
