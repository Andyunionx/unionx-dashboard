"""
Vista Fulfillment Operativo — KPIs de bodega que requieren WMS o medición manual.

Diferente a Stock LIVE (que muestra inventario en tiempo real desde Odoo).
Acá medimos el DESEMPEÑO de la operación: OFR, accuracy, productividad.

Estado: STUB con uploaders manuales hoy. WMS H2 desbloqueará automatización.
"""
import streamlit as st


def render():
    st.title("📦 Fulfillment — Operación de bodega")
    st.caption(
        "Plan Estratégico 2026-2028 · OFR ≥97% · Inventory Accuracy ≥98% · "
        "Pick & Pack Accuracy ≥99.5% · Costo/pedido ↓10-15% YoY"
    )

    st.info(
        "🔧 **Stubs manuales** hoy. La automatización completa requiere WMS (H2 según el Plan). "
        "Mientras tanto, vamos a habilitar uploaders mensuales para que el equipo bodega cargue valores."
    )

    st.divider()

    kpis = [
        ("OFR — Order Fulfillment Rate", "≥ 97%", "% pedidos completos en SLA"),
        ("OCT B2C", "≤ 24 hrs", "Tiempo orden recibida → entrega courier"),
        ("OCT B2B", "≤ 48 hrs", "Idem B2B"),
        ("Pick & Pack Accuracy", "≥ 99.5%", "% pedidos sin error"),
        ("Inventory Accuracy", "≥ 98%", "Stock sistema vs físico (cycle counting)"),
        ("DOH — Días de inventario", "60-90 días", "Inventario / costo ventas diario"),
        ("Stockouts SKUs A", "≤ 3%", "% SKUs A sin stock con demanda"),
        ("Slow movers / obsoleto", "≤ 8% inventario", "Sin venta > 180 días"),
        ("Productividad picking", "60-120 líneas/hora B2C", "Picking por hora-persona"),
        ("Tiempo recepción contenedor", "≤ 48 hrs", "Llegada → disponible en stock"),
    ]

    import pandas as pd
    df = pd.DataFrame(kpis, columns=["KPI", "Meta", "Definición"])
    st.dataframe(df, width='stretch', hide_index=True)

    st.divider()

    st.markdown("### 🛣️ Roadmap Fulfillment Ops")
    st.markdown("""
- **🟢 Hoy:** Stock LIVE en tiempo real desde Odoo (semáforo, ocupación, slow movers, ABC)
- **🟡 H1 próximo:** Uploader mensual de OFR/OCT/Accuracy/Productividad
- **🟠 H2 (6-12 meses):** WMS o capa de medición sobre el sistema actual:
  - Timestamps de pick/pack/despacho automáticos
  - Cycle counting digital
  - Alertas en quiebre SKUs A
- **🟠 H2:** Forecast por SKU con ABC/XYZ que alimenta shipping plan COMEX
- **🔵 H3:** Slotting dinámico, automatización selectiva (sorting, picking ayudado)
    """)
