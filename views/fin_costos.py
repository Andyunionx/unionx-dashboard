"""
Vista Costos — App Finanzas.

EERR clasificado por las 88 reglas + costos por área + distribución a canales.

Estado: 🟡 Stub — pendiente integrar eerr_classifier + visualización.
"""
import streamlit as st


def render():
    with st.sidebar:
        st.markdown("### 💸 **Costos**")
        st.caption("EERR clasificado + por área")
        st.divider()

    st.title("💸 Análisis de Costos")
    st.caption("EERR clasificado por 88 reglas · costos por área / centro / canal")

    st.info(
        "🟡 **Vista en construcción.** Integrar `eerr-finanzas/eerr_classifier.py` "
        "(que ya existe y funciona).\n\n"
        "**Tabs propuestos:**\n\n"
        "**Tab 1 — Costos por área:**\n"
        "- Pie chart distribución gastos por área (Ventas, Operaciones, Admin, "
        "Marketing, Finanzas)\n"
        "- Tabla detalle con drill-down por centro de costo\n"
        "- Comparado mes vs mes anterior vs ppto\n\n"
        "**Tab 2 — Costos por centro:**\n"
        "- Top 20 centros de costo por monto\n"
        "- Línea negocio (Recíbelo, Blue Express, Grupo Eter, Control Aportes)\n"
        "- Variación YoY\n\n"
        "**Tab 3 — Distribución a canales:**\n"
        "- Output del skill `distribucion-comisiones-canal`\n"
        "- Costo unitario por canal (B2B / B2C / Marketplaces)\n"
        "- Cruce con margen contribución para ver rentabilidad neta\n\n"
        "**Tab 4 — Sin clasificar (data quality):**\n"
        "- Gastos que las 88 reglas no lograron clasificar\n"
        "- Sugerencias de nuevas reglas\n"
        "- Botón para auto-clasificar y re-procesar\n\n"
        "**Tab 5 — Histórico clasificación:**\n"
        "- Log de cambios de reglas\n"
        "- Re-clasificación masiva si se actualiza alguna regla\n\n"
        "**Fuentes:**\n"
        "- `eerr-finanzas/eerr_classifier.py` (motor de 88 reglas)\n"
        "- `eerr-finanzas/REGLAS_CLASIFICACION.json`\n"
        "- `data/outputs/` (EERR clasificado en JSON + Excel + HTML)"
    )
