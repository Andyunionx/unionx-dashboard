"""
Vista Forecast & Cierre Proyectado — App Finanzas.
Bridge: Real YTD (ene→último mes real) + Forecast restante = Cierre proyectado,
comparado vs Presupuesto (Meta) y Año anterior. Fuente: Fcst EERR + Metas 2026.
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 🔮 **Forecast Cierre**")
        st.caption("Real YTD + Fcst restante")
        st.divider()

    st.title("🔮 Forecast — Cierre Proyectado 2026")
    st.caption("Real acumulado + Forecast restante = cierre proyectado · vs Presupuesto · vs Año anterior · MM CLP")

    periodos = P.pl_periodos()
    if not periodos:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    year = 2026
    _, cm = P.ultimo_mes_real([p for p in periodos if p[0] == year] or periodos)
    st.caption(f"📌 Último mes real: **{P.label_mes(year, cm)}** · resto = forecast")

    real = P.pl_rango(year, 1, cm)
    cierre = P.pl_rango(year, 1, 12)
    resto = {k: (cierre.get(k) or 0) - (real.get(k) or 0) for k in cierre}
    meta = P.presupuesto_ytd(year, 12, "Meta")
    y25 = P.pl_rango(year - 1, 1, 12)

    # ─── KPIs de cierre ─────────────────────────────────────
    st.markdown("### 🎯 Cierre proyectado 2026")
    c = st.columns(4)
    UI.kpi(c[0], "Venta", P.fmt_mm(cierre.get("venta")),
           f"Meta {P.fmt_mm(meta.get('venta'))} · YoY {P.fmt_var(P.yoy(cierre.get('venta'), y25.get('venta')))}", UI.NAVY)
    UI.kpi(c[1], "Contribución", P.fmt_mm(cierre.get("mg_contrib")),
           f"Meta {P.fmt_mm(meta.get('mg_contrib'))}", UI.BLUE)
    eb = cierre.get("ebitda")
    UI.kpi(c[2], "EBITDA", P.fmt_mm(eb),
           f"Meta {P.fmt_mm(meta.get('ebitda'))} · {P.fmt_var(P.yoy(eb, meta.get('ebitda')))} vs Ppto",
           UI.GOOD if (meta.get("ebitda") and eb and eb >= meta["ebitda"]) else UI.AMBER)
    ut = cierre.get("utilidad")
    UI.kpi(c[3], "Utilidad", P.fmt_mm(ut),
           f"Meta {P.fmt_mm(meta.get('utilidad'))}", UI.GOOD if (ut or 0) >= 0 else UI.BAD)

    # ─── Bridge ─────────────────────────────────────────────
    st.markdown("#### Bridge — Real YTD + Forecast restante → Cierre")
    filas = []
    for k, nombre, _sub in P.PL_ORDEN:
        mt = meta.get(k)
        cp = cierre.get(k)
        filas.append({
            "Línea": nombre,
            f"Real Ene–{P.MESES[cm-1]}": P.fmt_mm(real.get(k)),
            "+ Fcst restante": P.fmt_mm(resto.get(k)),
            "= Cierre proy.": P.fmt_mm(cp),
            "Meta año": P.fmt_mm(mt) if mt is not None else "—",
            "Gap vs Meta": P.fmt_mm(cp - mt) if (mt is not None and cp is not None) else "—",
            "YoY": P.fmt_var(P.yoy(cp, y25.get(k))),
        })
    st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)

    # ─── Evolución mensual: Real + Forecast vs Meta ─────────
    st.markdown("#### Evolución mensual — Real + Forecast vs Presupuesto")
    kpi_map = {"Venta": "venta", "Contribución": "mg_contrib", "GAV": "gav",
               "EBITDA": "ebitda", "Utilidad": "utilidad"}
    sel = st.selectbox("Línea", list(kpi_map.keys()), key="fcst_linea")
    key = kpi_map[sel]
    meses = list(range(1, 13))
    real_s, fcst_s = [], []
    for m in meses:
        v = P.pl_mes(year, m).get(key)
        if m <= cm:
            real_s.append(v); fcst_s.append(None)
        else:
            real_s.append(None); fcst_s.append(v)
    meta_serie = P.metas_serie(sel if sel in P.METAS_KPIS else "Venta", "Meta", year)
    xm = [P.MESES[m - 1] for m in meses]
    from views import _fin_echarts as ECH
    UI.titulo_grafico(f"{sel} — real + forecast contra presupuesto (MM CLP)")
    ECH.render(ECH.barras_linea(
        xm,
        [("Real", real_s, UI.BLUE), ("Forecast", fcst_s, "#B9C6CF")],
        linea_ref=("Presupuesto", [meta_serie.get(m) for m in meses]) if meta_serie else None,
    ), height=360)

    st.caption("Fuente: Planificación Financiera 2026 · Fcst EERR (real ene–jul + forecast) + Metas 2026 (presupuesto).")
