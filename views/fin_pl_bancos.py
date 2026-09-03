"""
Vista P&L Bancos — App Finanzas.
EERR anual histórico + márgenes + indicadores de cierre, para reporte a bancos.
Fuente: hoja **P&L** (pyl_mensual, consistente con el Fcst EERR), NO la pestaña
"P&L Bancos" (que estaba desactualizada).
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 🏛️ **P&L Bancos**")
        st.caption("EERR anual histórico")
        st.divider()

    st.title("🏛️ P&L Bancos — Histórico Anual")
    st.caption("Estado de resultados anual · márgenes · indicadores de cierre · MM CLP")

    piv = P.pl_anual()
    if piv is None or piv.empty:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    years = list(piv.columns)
    ycols = [str(y) for y in years]

    def g(linea):
        return piv.loc[linea] if linea in piv.index else pd.Series(index=years, dtype=float)

    # ─── EERR anual ─────────────────────────────────────────
    st.markdown("#### Estado de resultados anual")
    orden = ["Ingresos", "Costo de Venta", "Margen Bruto", "Gastos de Administración y Venta",
             "Resultado Operacional (EBIT)", "Resultado No Operacional",
             "Utilidad Antes de Impuestos", "EBITDA"]
    filas = []
    for ln in orden:
        s = g(ln)
        filas.append({"Línea": ln, **{str(y): P.fmt_mm(s.get(y)) for y in years}})
    st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)

    # ─── Evolución Ingresos + EBITDA (mismo eje) ────────────
    ing = g("Ingresos"); eb = g("EBITDA")
    UI.barras_agrupadas(ycols, {
        "Ingresos": [ing.get(y) for y in years],
        "EBITDA": [eb.get(y) for y in years],
    }, "Los ingresos se multiplican por 7 desde 2019 (MM CLP)", alto=340)

    # ─── Márgenes ───────────────────────────────────────────
    st.markdown("#### Márgenes (% s/ingresos)")
    ing_s = g("Ingresos")

    def _pct_row(nombre, linea):
        s = g(linea)
        return {"Margen": nombre, **{str(y): (f"{s.get(y)/ing_s.get(y)*100:.1f}%".replace(".", ",")
                                              if ing_s.get(y) else "—") for y in years}}
    st.dataframe(pd.DataFrame([
        _pct_row("Margen bruto %", "Margen Bruto"),
        _pct_row("Margen EBIT %", "Resultado Operacional (EBIT)"),
        _pct_row("Margen EBITDA %", "EBITDA"),
        _pct_row("Margen neto %", "Utilidad Antes de Impuestos"),
    ]), width="stretch", hide_index=True)

    # ─── Indicadores de cierre por año ──────────────────────
    st.markdown("#### Indicadores de cierre (diciembre de cada año)")
    ind_defs = [
        ("Razón corriente", "Ratio Liquidez - Razón Corriente", "x"),
        ("Deuda fin. / EBITDA", "Razón de Deuda Financiera Ebitda", "x"),
        ("Deuda fin. / Patrimonio", "Relación Deuda Patrimonio - CP", "x"),
        ("Cobertura gastos fin.", "Cobertura Gastos", "x"),
        ("ROE", "ROE", "p"),
    ]
    ryears = sorted(set().union(*[set(P.ratio_anual(pref).keys()) for _, pref, _ in ind_defs]))
    if ryears:
        filas_r = []
        for nombre, pref, fmt in ind_defs:
            vals = P.ratio_anual(pref)
            filas_r.append({"Indicador": nombre,
                            **{str(y): P.fmt_ratio(vals.get(y), fmt) for y in ryears}})
        st.dataframe(pd.DataFrame(filas_r), width="stretch", hide_index=True)

    st.caption("Fuente: hoja **P&L** de la Planificación Financiera 2026 (consistente con Fcst EERR) · "
               "indicadores desde EEFF. Reemplaza la pestaña «P&L Bancos» que estaba desfasada.")
