"""
Vista Planificación — App Finanzas.

Real vs Presupuesto + Forecast cierre de año + Forecast accuracy + Análisis Financiero.

Estado: 🟡 Stub — pendiente migrar lógica desde pages/4_📋_Planificacion.py.
"""
import streamlit as st


def render():
    with st.sidebar:
        st.markdown("### 📋 **Planificación**")
        st.caption("Real vs Ppto + Forecast cierre")
        st.divider()

    st.title("📋 Planificación Financiera")
    st.caption("Real vs Presupuesto · Forecast cierre año · Análisis Financiero 2026")

    st.info(
        "🟡 **Vista en construcción.** Migrar y reorganizar lógica del Tab "
        "actual `pages/4_📋_Planificacion.py`.\n\n"
        "**Tabs propuestos:**\n\n"
        "**Tab 1 — Resumen YTD:**\n"
        "- KPIs mes actual + acumulado vs ppto vs YoY\n"
        "- Semáforo por línea (ventas, costos, EBITDA)\n"
        "- Forecast cierre año (anualizado simple + estacional)\n\n"
        "**Tab 2 — Real vs Ppto detalle:**\n"
        "- Tabla mensual con desviaciones por línea\n"
        "- Top 10 desviaciones con explicación cualitativa\n"
        "- Forecast accuracy (precisión histórica del ppto)\n\n"
        "**Tab 3 — Análisis Financiero 2026:**\n"
        "- Hoja Análisis Financiero 2026 (planilla actual)\n"
        "- Cálculos automáticos: ROE, ROA, EBITDA margin, etc.\n"
        "- Comparativos vs años anteriores\n\n"
        "**Tab 4 — Forecast:**\n"
        "- Proyección cierre año por línea (basada en run-rate + estacional)\n"
        "- Escenarios: pesimista / base / optimista\n"
        "- Ajuste por eventos conocidos (Cyber, Black, Navidad)\n\n"
        "**Tab 5 — Carga mensual (admin):**\n"
        "- Uploader del EERR + Balance del mes\n"
        "- Backup automático antes de sobrescribir\n"
        "- Validación de cuadre antes de aceptar\n\n"
        "**Fuentes:**\n"
        "- `data/planillas/Planificación Financiera.xlsx` (29 hojas)\n"
        "- `data/eerr/` (EERR mensual clasificado)"
    )
