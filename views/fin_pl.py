"""
Vista P&L / Resultado (EERR) — App Finanzas.
Replica la pestaña de resultado de la planilla (fuente: Fcst EERR, el resultado
validado en los reportes). Cascada + vertical (% s/venta) + YoY.
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 📊 **P&L / Resultado**")
        st.caption("EERR mensual · vertical · YoY")
        st.divider()

    st.title("📊 P&L / Resultado (EERR)")
    st.caption("Estado de resultados · análisis vertical (% s/venta) · comparación interanual · MM CLP")

    periodos = P.pl_periodos()
    if not periodos:
        st.warning("⏳ Sin datos de P&L. Correr `python extract_finanzas_planificacion.py`.")
        return

    year, month, modo = UI.selector_periodo(periodos, key="pl_periodo", con_modo=True)

    pm = None  # período anterior (horizontal)
    if modo == "Mes":
        cur = P.pl_mes(year, month)
        prev = P.pl_mes(year - 1, month)
        py, pmo = (year, month - 1) if month > 1 else (year - 1, 12)
        pm = P.pl_mes(py, pmo)
        pm_lbl = P.label_mes(py, pmo)
        etiqueta = P.label_mes(year, month)
    else:
        cur = P.pl_rango(year, 1, month)
        prev = P.pl_rango(year - 1, 1, month)
        etiqueta = f"Ene–{P.MESES[month - 1]} {year}"

    venta = cur.get("venta")

    # ─── KPIs ───────────────────────────────────────────────
    st.markdown(f"### 🎯 {etiqueta}")
    c = st.columns(5)
    UI.kpi(c[0], "Venta", P.fmt_mm(venta),
           f"YoY {P.fmt_var(P.yoy(venta, prev.get('venta')))}", UI.NAVY)
    mc = cur.get("mg_contrib")
    UI.kpi(c[1], "Margen contribución", P.fmt_mm(mc),
           f"{P.fmt_pct_venta(mc, venta)} s/venta · YoY {P.fmt_var(P.yoy(mc, prev.get('mg_contrib')))}", UI.BLUE)
    ebit = cur.get("ebit")
    UI.kpi(c[2], "EBIT", P.fmt_mm(ebit),
           f"{P.fmt_pct_venta(ebit, venta)} s/venta", UI.color_umbral(ebit, 1, 0) if ebit is not None else UI.INK)
    ebitda = cur.get("ebitda")
    UI.kpi(c[3], "EBITDA", P.fmt_mm(ebitda),
           f"YoY {P.fmt_var(P.yoy(ebitda, prev.get('ebitda')))}", UI.BLUE)
    ut = cur.get("utilidad")
    UI.kpi(c[4], "Utilidad", P.fmt_mm(ut),
           f"{P.fmt_pct_venta(ut, venta)} s/venta", UI.GOOD if (ut or 0) >= 0 else UI.BAD)

    # ─── Cascada ────────────────────────────────────────────
    UI.waterfall_pl(cur, f"Cascada de resultado — {etiqueta} (MM CLP)")

    # ─── Puente YoY de la utilidad ──────────────────────────
    lbl_prev = (P.label_mes(year - 1, month) if modo == "Mes"
                else f"Ene–{P.MESES[month - 1]} {str(year - 1)[2:]}")
    du = (cur.get("utilidad") or 0) - (prev.get("utilidad") or 0)
    UI.puente_yoy(cur, prev, lbl_prev, etiqueta,
                  f"Qué explica que la utilidad {'mejore' if du >= 0 else 'caiga'} "
                  f"{P.fmt_mm(abs(du))} vs {year - 1} (MM CLP)")

    # ─── Evolución mensual del año ──────────────────────────
    ser = P.pl_mensual_series(year)
    ser_p = P.pl_mensual_series(year - 1)
    if ser:
        mss = sorted(ser)
        cats = [P.MESES[m - 1] for m in mss]
        v_cur = [ser[m]["venta"] for m in mss]
        v_prev = [ser_p.get(m, {}).get("venta") for m in mss]
        tot_c = sum(v for v in v_cur if v)
        tot_p = sum(v for v in v_prev if v)
        crec = (tot_c / tot_p - 1) * 100 if tot_p else None
        UI.barras_agrupadas(
            cats, {str(year - 1): v_prev, str(year): v_cur},
            (f"La venta {year} corre {crec:+.0f}% sobre {year - 1} (MM CLP, mensual)".replace(".", ",")
             if crec is not None else f"Venta mensual {year} vs {year - 1} (MM CLP)"),
            alto=300)

        mcp_cur = [ser[m]["mc_pct"] for m in mss]
        mcp_prev = [ser_p.get(m, {}).get("mc_pct") for m in mss]
        proms = [v for v in mcp_cur if v is not None]
        prom = sum(proms) / len(proms) if proms else None
        UI.linea_evolucion(
            cats, [(str(year), mcp_cur), (str(year - 1), mcp_prev)],
            (f"El margen de contribución se mueve en torno al {prom:.0f}% de la venta"
             if prom is not None else "Margen de contribución mensual (% s/venta)"),
            unidad="% s/venta", alto=280)

    # ─── Tabla P&L (vertical + horizontal + YoY) ────────────
    st.markdown("#### Estado de resultados")
    st.caption("**Vertical:** % s/venta · **Horizontal:** Δ vs mes anterior · **YoY:** vs mismo período año anterior")
    filas = []
    for k, nombre, _sub in P.PL_ORDEN:
        v = cur.get(k)
        fila = {
            "Línea": nombre,
            etiqueta: P.fmt_mm(v),
            "% s/venta": P.fmt_pct_venta(v, venta),
        }
        if pm is not None:
            fila[f"Δ vs {pm_lbl}"] = P.fmt_var(P.yoy(v, pm.get(k)))
        fila["YoY"] = P.fmt_var(P.yoy(v, prev.get(k)))
        filas.append(fila)
    st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)
    st.caption("Fuente: Planificación Financiera 2026 · hoja Fcst EERR (2026 ene–jul real, ago–dic forecast).")
