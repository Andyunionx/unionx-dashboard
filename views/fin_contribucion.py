"""
Vista Análisis de Contribución — App Finanzas.

Margen contribución por canal (B2C, B2B, marketplaces) cruzando ventas
Odoo con costos directos + comisiones + logística.

Estado: 🟡 Stub — pendiente migrar lógica desde eerr-finanzas/contribucion_dashboard.py.
"""
import streamlit as st


def render():
    with st.sidebar:
        st.markdown("### 📈 **Contribución**")
        st.caption("Margen por canal")
        st.divider()

    st.title("📈 Análisis de Contribución")
    st.caption("Margen contribución por canal · ventas - costos directos - comisiones - logística")

    st.info(
        "🟡 **Vista en construcción.** Migrar lógica desde "
        "`eerr-finanzas/contribucion_dashboard.py` (6 tabs ya existentes).\n\n"
        "**Tabs propuestos:**\n"
        "1. **Resultados Generales** — BI Comercial YoY 2025 vs 2026 por canal\n"
        "2. **Real vs Presupuesto** — desviaciones por canal con drill-down\n"
        "3. **Comercial vs Contable** — cruce ventas Odoo vs EERR clasificado\n"
        "4. **Vista KAM** — performance por ejecutivo de cuenta (B2B)\n"
        "5. **Oportunidades** — insights analíticos automáticos (margen bajo, "
        "concentración, mix shift)\n"
        "6. **Administración** — uploader mensual con backup + cache invalidation\n\n"
        "**Fuente:** `data/planillas/Analisis_Contribucion_2026_V06.xlsx` "
        "(skill `distribucion-comisiones-canal` la mantiene actualizada)."
    )
