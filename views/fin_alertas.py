"""
Vista Alertas Finanzas — App Finanzas.

10 alertas del Plan UnionX 2026-2028:
  4 críticas · 3 moderadas · 3 informativas

Estado: 🟡 Stub — pendiente conectar reglas + thresholds.
"""
import streamlit as st


def render():
    with st.sidebar:
        st.markdown("### 🔔 **Alertas Finanzas**")
        st.caption("Críticas / Moderadas / Info")
        st.divider()

    st.title("🔔 Alertas Financieras")
    st.caption("Sistema de alertas en tiempo real del Plan UnionX 2026-2028")

    st.info(
        "🟡 **Vista en construcción.**\n\n"
        "**🔴 Alertas Críticas (4):**\n"
        "1. **Margen contribución < 27%** — para canal o producto top 20\n"
        "2. **Quiebre de caja proyectado en 30d** — saldo bajo umbral mínimo\n"
        "3. **Desvío presupuesto > 10%** — en línea importante (>5% del total)\n"
        "4. **Retraso pago crítico** — proveedor estratégico o impuestos\n\n"
        "**🟡 Alertas Moderadas (3):**\n"
        "5. **DSO sube >10 días** vs mes anterior — ralentización cobranza B2B\n"
        "6. **Concentración cliente** — un cliente >25% de la cartera\n"
        "7. **Variación costo de venta** > 5% vs ppto sin justificación\n\n"
        "**🔵 Alertas Informativas (3):**\n"
        "8. **Mes con flujo negativo** — alerta temprana para acciones\n"
        "9. **Vencimiento deuda próxima** (60d antes)\n"
        "10. **Cierre contable atrasado** > 10 días post mes\n\n"
        "**Cada alerta:**\n"
        "- Estado actual (🔴 activa / 🟡 watch / 🟢 OK)\n"
        "- Valor actual vs threshold\n"
        "- Tendencia últimos 6 períodos\n"
        "- Acción sugerida (markdown)\n"
        "- Histórico de disparos\n\n"
        "**Integración:**\n"
        "- Reusar `evaluar_alertas.py` que ya existe en raíz\n"
        "- Cron `email_diario.yml` ya envía alertas críticas por email\n"
        "- Esta vista es para revisión interactiva + drill-down"
    )
