"""
Vista PP&E (Activo Fijo) — App Finanzas.
Roll-forward de activo fijo: bruto → depreciación → neto.
"""
import pandas as pd
import streamlit as st

from views import _fin_data as D
from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 🏗️ **PP&E (Activo Fijo)**")
        st.caption("Roll-forward · depreciación")
        st.divider()

    st.title("🏗️ PP&E — Activo Fijo")
    st.caption("Movimiento de activo fijo: bruto → depreciación acumulada → neto · MM CLP")

    periodos = P.ppe_periodos()
    if not periodos:
        st.warning("⏳ Sin datos de PP&E. Correr `python extract_finanzas_planificacion.py`.")
        return

    year, month = UI.selector_periodo(periodos, key="ppe_periodo")
    e = P.ppe_mes(year, month)
    ep = P.ppe_mes(year - 1, month)
    etiqueta = P.label_mes(year, month)

    # ─── KPIs ───────────────────────────────────────────────
    st.markdown(f"### 🎯 {etiqueta}")
    c = st.columns(4)
    UI.kpi(c[0], "Activo fijo neto", P.fmt_mm(e.get("neto")),
           f"YoY {P.fmt_var(P.yoy(e.get('neto'), ep.get('neto')))}", UI.NAVY)
    UI.kpi(c[1], "Activo fijo bruto", P.fmt_mm(e.get("bruto")), "costo histórico", UI.BLUE)
    UI.kpi(c[2], "Depreciación acumulada", P.fmt_mm(e.get("deprec_acum")), "acumulada a la fecha", UI.TEAL)
    UI.kpi(c[3], "Gasto depreciación (mes)", P.fmt_mm(e.get("gasto_deprec")), "cargo del mes", UI.AMBER)

    # ─── Roll-forward ───────────────────────────────────────
    st.markdown("#### Movimiento de activo fijo")
    tab = e.get("tabla")
    if tab is not None and not tab.empty:
        disp = pd.DataFrame({
            "Concepto": tab["linea"],
            etiqueta: tab["MM"].map(lambda v: P.fmt_mm(v)),
        })
        st.dataframe(disp, width="stretch", hide_index=True)

    # ─── Evolución del activo neto ──────────────────────────
    df = D.ppe()
    serie = df[df["linea"] == "Activo Fijo Neto"].sort_values("fecha")
    if not serie.empty:
        fechas = [f"{P.MESES[d.month-1]}-{str(d.year)[2:]}" for d in serie["fecha"]]
        UI.linea_evolucion(fechas, [("Activo fijo neto", (serie["valor"] / 1000).tolist())],
                           "Evolución del activo fijo neto (MM CLP)", alto=320)

    st.caption("Fuente: Planificación Financiera 2026 · hoja PP&E (miles de CLP → MM).")
