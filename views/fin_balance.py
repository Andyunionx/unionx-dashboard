"""
Vista Balance General (EEFF) — App Finanzas.
Replica la pestaña EEFF: estado de situación con análisis vertical (% s/activos).
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 🏦 **Balance (EEFF)**")
        st.caption("Estado de situación · vertical")
        st.divider()

    st.title("🏦 Balance General (EEFF)")
    st.caption("Activos · Pasivos · Patrimonio · análisis vertical (% s/total activos) · MM CLP")

    periodos = P.balance_periodos()
    if not periodos:
        st.warning("⏳ Sin datos de balance. Correr `python extract_finanzas_planificacion.py`.")
        return

    year, month = UI.selector_periodo(periodos, key="bal_periodo")
    b = P.balance_mes(year, month)
    bp = P.balance_mes(year - 1, month)
    etiqueta = P.label_mes(year, month)
    ta = b.get("total_activos") or 1

    # ─── KPIs ───────────────────────────────────────────────
    st.markdown(f"### 🎯 {etiqueta}")
    c = st.columns(4)
    UI.kpi(c[0], "Total activos", P.fmt_mm(b.get("total_activos")),
           f"YoY {P.fmt_var(P.yoy(b.get('total_activos'), bp.get('total_activos')))}", UI.NAVY)
    UI.kpi(c[1], "Deuda financiera", P.fmt_mm(b.get("deuda_fin")),
           f"{(b.get('deuda_fin') or 0)/ta*100:.0f}% del activo", UI.BLUE)
    UI.kpi(c[2], "Patrimonio", P.fmt_mm(b.get("patrimonio")),
           f"YoY {P.fmt_var(P.yoy(b.get('patrimonio'), bp.get('patrimonio')))}",
           UI.GOOD if (b.get("patrimonio") or 0) >= 0 else UI.BAD)
    UI.kpi(c[3], "Existencias / activo", f"{(b.get('existencias') or 0)/ta*100:.0f}%",
           f"{P.fmt_mm(b.get('existencias'))} inmovilizado", UI.AMBER)

    # ─── Tabla balance (vertical + horizontal + YoY) ────────
    st.markdown("#### Estado de situación")
    st.caption("**Vertical:** % s/total activos · **Horizontal:** Δ vs mes anterior · **YoY:** vs año anterior")
    tab = P.balance_tabla(year, month)
    if not tab.empty:
        py, pmo = (year, month - 1) if month > 1 else (year - 1, 12)
        prev_m = P.balance_tabla(py, pmo)
        prev_y = P.balance_tabla(year - 1, month)
        map_m = dict(zip(prev_m["linea"], prev_m["MM"])) if not prev_m.empty else {}
        map_y = dict(zip(prev_y["linea"], prev_y["MM"])) if not prev_y.empty else {}
        disp = pd.DataFrame({
            "Cuenta": tab["linea"],
            etiqueta: tab["MM"].map(lambda v: P.fmt_mm(v)),
            "% act.": tab["pct"].map(lambda v: f"{v*100:.0f}%" if pd.notna(v) else "—"),
            f"Δ vs {P.label_mes(py, pmo)}": [P.fmt_var(P.yoy(v, map_m.get(l))) for l, v in zip(tab["linea"], tab["MM"])],
            "YoY": [P.fmt_var(P.yoy(v, map_y.get(l))) for l, v in zip(tab["linea"], tab["MM"])],
        })
        st.dataframe(disp, width="stretch", hide_index=True, height=560)

    # ─── Composición ────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        UI.barh_composicion(
            [("Existencias", b.get("existencias")), ("Cuentas por cobrar", b.get("cxc")),
             ("Otros act. corrientes", b.get("otros_ac")), ("Caja", b.get("caja")),
             ("Activo fijo (PP&E)", b.get("ppe"))],
            "El activo es principalmente inventario (MM CLP)")
    with col2:
        UI.barh_composicion(
            [("Deuda financiera", b.get("deuda_fin")), ("Cuentas por pagar", b.get("cxp")),
             ("Patrimonio", b.get("patrimonio"))],
            "Financiado sobre todo con deuda (MM CLP)")

    st.info(f"**El activo es {(b.get('existencias') or 0)/ta*100:.0f}% existencias.** "
            f"El balance está cargado de inventario ({P.fmt_mm(b.get('existencias'))}) y financiado con "
            f"deuda ({P.fmt_mm(b.get('deuda_fin'))}, {(b.get('deuda_fin') or 0)/ta*100:.0f}% del activo). "
            f"El patrimonio ({P.fmt_mm(b.get('patrimonio'))}) es delgado frente a la deuda.")
    st.caption("Fuente: Planificación Financiera 2026 · hoja EEFF (miles de CLP → MM).")
