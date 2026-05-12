"""
Vista Caja & Tesorería — App Finanzas.

Flujo de caja proyectado 90 días: saldo actual + entradas (cobranzas)
+ salidas (pagos a proveedores, sueldos, impuestos) → semáforo diario.

Estado: 🟡 Stub — pendiente construir desde Odoo.
"""
import streamlit as st


def render():
    with st.sidebar:
        st.markdown("### 💧 **Caja & Tesorería**")
        st.caption("Flujo proyectado 90d")
        st.divider()

    st.title("💧 Flujo de Caja Proyectado 90 días")
    st.caption("Saldo bancos + cobranzas esperadas - pagos programados · semáforo diario")

    st.info(
        "🟡 **Vista en construcción.** Núcleo de la app — herramienta de "
        "gestión diaria de tesorería.\n\n"
        "**Tabs propuestos:**\n\n"
        "**Tab 1 — Posición HOY:**\n"
        "- Saldo consolidado bancos (suma `account.move` por journal banco)\n"
        "- Cuentas por cobrar B2B (DSO actual)\n"
        "- Cuentas por pagar (DPO actual)\n"
        "- Días de caja: saldo / (gastos mensuales / 30)\n\n"
        "**Tab 2 — Forecast 30/60/90d:**\n"
        "- Cobranzas esperadas por vencimiento (factura emitida + plazo)\n"
        "- Pagos programados (sueldos día 5, IVA día 12, proveedores por vencimiento)\n"
        "- Saldo proyectado diario → línea con umbral mínimo\n"
        "- Alerta automática si saldo cae bajo umbral en algún día\n\n"
        "**Tab 3 — Cuentas por cobrar:**\n"
        "- Aging buckets: vigente / 1-30d / 31-60d / 61-90d / +90d\n"
        "- Top deudores con drill-down a facturas\n"
        "- % morosidad B2B\n\n"
        "**Tab 4 — Cuentas por pagar:**\n"
        "- Vencimientos próximos 30d\n"
        "- Top acreedores\n"
        "- Sugerencia de priorización por monto/criticidad\n\n"
        "**Fuentes Odoo:**\n"
        "- `account.move` (filtro out_invoice/in_invoice) con `invoice_date_due`\n"
        "- `account.payment` para conciliar lo cobrado/pagado\n"
        "- `res.partner` para identificar B2B vs particulares"
    )
