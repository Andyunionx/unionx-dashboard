"""
Vista Indicadores Financieros — App Finanzas.
Catálogo completo de ratios de la planilla (EEFF) con comparativo YoY y semáforos.
Espeja la sección de indicadores de los reportes financieros.
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 📈 **Indicadores**")
        st.caption("Ratios financieros · YoY")
        st.divider()

    st.title("📈 Indicadores Financieros")
    st.caption("Liquidez · Gestión · Endeudamiento y cobertura · Rentabilidad · comparación interanual (YoY)")

    periodos = P.ratios_periodos()
    if not periodos:
        st.warning("⏳ Sin ratios. Correr `python extract_finanzas_planificacion.py`.")
        return

    year, month = UI.selector_periodo(periodos, key="ind_periodo")
    yp, mp = year - 1, month  # mismo mes año anterior
    etiqueta = P.label_mes(year, month)
    prev_lbl = P.label_mes(yp, mp)

    # ─── KPIs destacados ────────────────────────────────────
    st.markdown(f"### 🎯 {etiqueta}  ·  comparado con {prev_lbl}")

    def _tile(col, nombre, prefix, fmt):
        a = P.ratio_val(year, month, prefix)
        b = P.ratio_val(yp, mp, prefix)
        bench = next((x[5] for x in P.RATIO_CATALOGO if x[0] == prefix), "")
        sem = P.semaforo_ratio(prefix, a)
        color = {"🟢": UI.GOOD, "🟡": UI.AMBER, "🔴": UI.BAD}.get(sem, UI.INK)
        meta = f"{prev_lbl}: {P.fmt_ratio(b, fmt)} · mercado {bench} {sem}"
        UI.kpi(col, nombre, P.fmt_ratio(a, fmt), meta, color)

    c = st.columns(4)
    _tile(c[0], "Deuda fin. / EBITDA", "Razón de Deuda Financiera Ebitda", "x")
    _tile(c[1], "Deuda fin. / Patrimonio", "Relación Deuda Patrimonio - CP", "x")
    _tile(c[2], "Cobertura gastos fin.", "Cobertura Gastos", "x")
    _tile(c[3], "Rotación inventarios", "Rotación de Inventarios", "x")

    # ─── Tabla completa por categoría ───────────────────────
    st.markdown("#### Catálogo de indicadores")
    tab = P.ratios_tabla(year, month, yp, mp)

    def _tend(row):
        a, b, mej = row["actual"], row["previo"], row["mejora"]
        if a is None or b is None:
            return "—"
        arrow = "▲" if a > b else ("▼" if a < b else "→")
        dot = "🟢" if mej else ("🔴" if mej is False else "⚪")
        return f"{dot} {arrow}"

    for cat in ["Liquidez", "Gestión", "Endeudamiento y cobertura", "Rentabilidad"]:
        sub = tab[tab["categoria"] == cat]
        if sub.empty:
            continue
        st.markdown(f"**{cat}**")
        disp = pd.DataFrame({
            "Indicador": sub["indicador"],
            etiqueta: [P.fmt_ratio(v, f) for v, f in zip(sub["actual"], sub["fmt"])],
            prev_lbl: [P.fmt_ratio(v, f) for v, f in zip(sub["previo"], sub["fmt"])],
            "YoY": [_tend(r) for _, r in sub.iterrows()],
            "Mercado": sub["benchmark"],
            "vs Mercado": sub["semaforo"],
        })
        st.dataframe(disp, width="stretch", hide_index=True)

    st.caption("**YoY:** 🟢 mejora / 🔴 deterioro vs mismo mes año anterior · "
               "**vs Mercado:** 🟢 cumple / 🟡 cerca / 🔴 bajo el benchmark de mercado · "
               "Fuente: Planificación Financiera 2026 · hoja EEFF (ratios).")
