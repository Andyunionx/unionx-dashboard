"""
Vista Otros Activos y Pasivos — App Finanzas.
Schedule de partidas no operativas (goodwill, impuestos, diferidos, etc.).
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 🗂️ **Otros Activos/Pasivos**")
        st.caption("Partidas no operativas")
        st.divider()

    st.title("🗂️ Otros Activos y Pasivos")
    st.caption("Goodwill · impuestos por recuperar/pagar · diferidos · anticipos · MM CLP")

    periodos = P.otros_periodos()
    if not periodos:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    year, month = UI.selector_periodo(periodos, key="otros_periodo")
    o = P.otros_mes(year, month)
    etiqueta = P.label_mes(year, month)

    # ─── KPIs ───────────────────────────────────────────────
    st.markdown(f"### 🎯 {etiqueta}")
    c = st.columns(3)
    UI.kpi(c[0], "Total otros activos", P.fmt_mm(o.get("total_activos")), "partidas no operativas", UI.NAVY)
    UI.kpi(c[1], "Total otros pasivos", P.fmt_mm(o.get("total_pasivos")), "partidas no operativas", UI.TEAL)
    UI.kpi(c[2], "Cambio neto (flujo)", P.fmt_mm(o.get("cambio_neto")),
           "aporte al flujo de caja", UI.BLUE)

    # ─── Detalle ────────────────────────────────────────────
    tab = o.get("tabla")
    if tab is not None and not tab.empty:
        col1, col2 = st.columns(2)
        act = tab[tab["seccion"].str.contains("Activo", case=False, na=False)]
        pas = tab[tab["seccion"].str.contains("Pasivo", case=False, na=False)]
        with col1:
            st.markdown("**Otros activos**")
            st.dataframe(pd.DataFrame({
                "Concepto": act["linea"], etiqueta: act["MM"].map(lambda v: P.fmt_mm(v)),
            }), width="stretch", hide_index=True)
        with col2:
            st.markdown("**Otros pasivos**")
            st.dataframe(pd.DataFrame({
                "Concepto": pas["linea"], etiqueta: pas["MM"].map(lambda v: P.fmt_mm(v)),
            }), width="stretch", hide_index=True)

    st.caption("Fuente: Planificación Financiera 2026 · hoja Otros (miles de CLP → MM). "
               "Alimenta el flujo de caja (variación de otros activos/pasivos).")
