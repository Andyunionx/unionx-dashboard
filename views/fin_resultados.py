"""
Vista P&L Mensual + YTD — App Finanzas.

Estado de Resultados real con cruce ppto y YoY. Lectura desde EERR clasificado
+ planilla Planificación Financiera.

Estado: 🟡 Stub — pendiente conectar.
"""
import streamlit as st


def render():
    with st.sidebar:
        st.markdown("### 💵 **Resultados (P&L)**")
        st.caption("Mensual + YTD")
        st.divider()

    st.title("💵 P&L Mensual + YTD")
    st.caption("Estado de Resultados clasificado: real vs presupuesto vs año anterior")

    st.info(
        "🟡 **Vista en construcción.** Plan de tabs:\n\n"
        "**Tab 1 — P&L Mensual:**\n"
        "- Tabla mes actual (ingresos, COGS, margen bruto, gastos por área, EBITDA)\n"
        "- Comparado: mes vs mes anterior · vs mismo mes año anterior · vs ppto\n"
        "- Variaciones absolutas y % con semáforo\n\n"
        "**Tab 2 — P&L YTD:**\n"
        "- Acumulado año vs YTD año anterior vs YTD ppto\n"
        "- Drill-down por línea: ingresos, costos directos, gastos operacionales\n\n"
        "**Tab 3 — Tendencia mensual:**\n"
        "- Gráfico líneas: ingreso, margen bruto, EBITDA últimos 12-18 meses\n"
        "- Estacionalidad evidenciada\n\n"
        "**Tab 4 — Análisis variaciones:**\n"
        "- Top desviaciones del mes vs ppto (con explicación cuando esté cargada)\n"
        "- Bridge analysis (puente de variación de margen)\n\n"
        "**Fuentes:**\n"
        "- `data/eerr/` (EERR mensual clasificado por reglas)\n"
        "- `data/planillas/Planificación Financiera.xlsx` (ppto + balance)\n"
        "- Odoo `account.move.line` para drill-down"
    )
