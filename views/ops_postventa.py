"""
Vista Post-venta — Devoluciones, recovery, SERNAC.

Datos parcialmente automatizables:
  - Tasa devolución desde Odoo (account.move tipo out_refund)
  - El resto requiere Helpdesk H2 + tracking SERNAC manual
"""
import streamlit as st


def render():
    st.title("↩️ Post-venta — Devoluciones & SERNAC")
    st.caption(
        "Plan Estratégico · Tasa devolución ≤5% · Tiempo resolución ≤7 días · "
        "Recovery rate ≥70% · Reclamos SERNAC ≤0.5/1000 pedidos"
    )

    st.info(
        "🔧 **En construcción** — la tasa de devolución es calculable desde Odoo (`out_refund`). "
        "El resto requiere Helpdesk + tracking RMA."
    )

    st.divider()

    kpis = [
        ("Tasa de devolución", "≤ 5% B2C e-com", "% pedidos devueltos / despachados", "🟡 Odoo (out_refund)"),
        ("Devoluciones por causa raíz", "Mapeo trimestral", "Defectuoso / Error despacho / Expectativa / Retracto", "🔴 Tipificación manual"),
        ("Tiempo resolución devolución", "≤ 7 días", "Días entre solicitud y reembolso/cambio", "🟠 Helpdesk H2"),
        ("Reingreso al stock", "≤ 72 hrs", "Devolución recibida → stock disponible", "🟠 WMS H2"),
        ("Recovery rate", "≥ 70%", "% del valor original recuperado", "🟠 Tracking RMA H2"),
        ("Reclamos SERNAC", "≤ 0.5 / 1.000 pedidos", "Reclamos formales", "🔴 Manual (portal SERNAC)"),
        ("Costo logística inversa / pedido", "Tracking + meta a 6m", "Total devoluciones / N° pedidos devueltos", "🟡 P&L cuenta específica"),
        ("% Devoluciones evitables", "↓ 30% en 12m", "Por error operativo o descripción", "🔴 Tipificación + análisis"),
    ]

    import pandas as pd
    df = pd.DataFrame(kpis, columns=["KPI", "Meta", "Definición", "Fuente / Estado"])
    st.dataframe(df, width='stretch', hide_index=True)

    st.divider()

    st.markdown("### 🛣️ Roadmap Post-venta")
    st.markdown("""
- **🟡 H1 próximo:** Tasa de devolución desde Odoo (out_refund) + costo logística inversa desde P&L
- **🟠 H2 (3-6 meses):** Helpdesk omnicanal (Zendesk/Freshdesk) → desbloquea tiempos de resolución, FCR de devoluciones
- **🟠 H2:** Workflow RMA con tipificación causa raíz obligatoria al ingreso
- **🟠 H2:** Outlet o canal liquidación para producto reacondicionado (recovery rate)
- **🔵 H3:** Compliance proactivo SERNAC con scripts y plantillas legalmente revisadas
    """)
