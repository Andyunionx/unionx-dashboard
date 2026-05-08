"""
Vista Logística — Despacho y última milla.

Datos hoy: parcial calculable desde Odoo + cuenta P&L courier.
H2: APIs de couriers (Blue Express, Recíbelo) para OTD en tiempo real.
"""
import streamlit as st


def render():
    st.title("🚚 Logística — Despacho & Couriers")
    st.caption(
        "Plan Estratégico · Costo logístico/venta 8-12% · OTD ≥92% · "
        "Tasa incidentes ≤2% · Días entrega RM 1-3"
    )

    st.info(
        "🔧 **Parcial.** Costo logístico/venta es calculable desde P&L. OTD y tasa incidentes "
        "requieren APIs courier (H2)."
    )

    st.divider()

    kpis = [
        ("Costo logístico / pedido", "↓ 10-15% en 12m", "Costo courier / pedidos despachados", "🟡 P&L + Odoo"),
        ("Costo logístico / venta", "8-12% según ticket", "Costo logístico total / venta neta", "🟡 P&L + Odoo"),
        ("OTD — On-Time Delivery", "≥ 92%", "Pedidos entregados ≤ promesa al cliente", "🟠 API courier H2"),
        ("Tasa de incidentes", "≤ 2%", "Envíos con incidente / total envíos", "🟠 API courier H2"),
        ("Tasa de re-despacho", "≤ 1.5%", "Envíos que requieren reenvío", "🟠 API courier H2"),
        ("Días promedio entrega RM", "1-3 días hábiles", "Despacho → recepción cliente", "🟠 API courier H2"),
        ("Días promedio entrega regiones", "3-7 días hábiles", "Idem regiones", "🟠 API courier H2"),
    ]

    import pandas as pd
    df = pd.DataFrame(kpis, columns=["KPI", "Meta", "Definición", "Fuente / Estado"])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    st.markdown("### 🛣️ Roadmap Logística")
    st.markdown("""
- **🟡 H1 próximo:** Costo logístico/venta calculable (cuando se identifique cuenta courier en P&L)
- **🟠 H2 (3-6 meses):** Integrar APIs Blue Express y Recíbelo
  - OTD en tiempo real
  - Tasa de incidentes y re-despachos
  - Tracking unificado para SAC
- **🟠 H2:** Renegociación anual de tarifas courier basada en volumen consolidado
- **🟠 H2:** Conciliación automatizada de cobros de courier (vs facturas)
- **🔵 H3:** Mix de couriers gestionado por zona y SLA con ruteo automático
    """)
