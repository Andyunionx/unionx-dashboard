"""
Vista Balance & Capital de Trabajo — App Finanzas.

Balance comparado + DIO/DSO/DPO/CCC + Deuda + Cobertura intereses.

Estado: 🟡 Stub — pendiente migrar desde Planificacion.py + cálculos Odoo.
"""
import streamlit as st


def render():
    with st.sidebar:
        st.markdown("### 🏦 **Balance & KT**")
        st.caption("Activos · Pasivos · KT · Deuda")
        st.divider()

    st.title("🏦 Balance & Capital de Trabajo")
    st.caption("EEFF comparado + métricas de capital de trabajo + estructura de deuda")

    st.info(
        "🟡 **Vista en construcción.** Reemplaza el Tab 7 actual de "
        "`pages/4_📋_Planificacion.py` con vista dedicada y nuevos KPIs.\n\n"
        "**Tabs propuestos:**\n\n"
        "**Tab 1 — Balance comparado:**\n"
        "- Activos / Pasivos / Patrimonio mes vs mes anterior vs ppto\n"
        "- Variaciones absolutas y % con drill-down por línea\n\n"
        "**Tab 2 — Capital de Trabajo Operativo:**\n"
        "- DIO (Days Inventory Outstanding) — Inventario / (CMV/365)\n"
        "- DSO (Days Sales Outstanding) — CxC / (Ventas/365)\n"
        "- DPO (Days Payable Outstanding) — CxP / (Compras/365)\n"
        "- **CCC** = DIO + DSO − DPO con meta ≤90d\n"
        "- Tendencia 12m de cada métrica\n\n"
        "**Tab 3 — Deuda & Apalancamiento:**\n"
        "- Deuda financiera total + por banco + por plazo\n"
        "- Cronograma de vencimientos\n"
        "- Deuda/EBITDA (meta ≤3.0x)\n"
        "- Cobertura de intereses (EBITDA / gastos financieros)\n\n"
        "**Tab 4 — Ratios financieros:**\n"
        "- Liquidez corriente, Test ácido, ROE, ROA\n"
        "- Comparado vs benchmark del Plan UnionX\n\n"
        "**Fuentes:**\n"
        "- Odoo `stock.quant` + `account.move.line` (CMV) → DIO\n"
        "- `account.move` aged buckets → DSO/DPO/morosidad\n"
        "- `data/planillas/Planificación Financiera.xlsx` → presupuesto y deuda"
    )
