"""
Vista Deuda Financiera — App Finanzas.
Composición (COMEX / comerciales / socios), bancos COMEX y cronograma de cuotas.
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 💳 **Deuda & Préstamos**")
        st.caption("Composición · cuotas")
        st.divider()

    st.title("💳 Deuda Financiera y Préstamos")
    st.caption("Composición por tipo · bancos COMEX · cronograma de cuotas · MM CLP")

    periodos = P.deuda_periodos()
    if not periodos:
        st.warning("⏳ Sin datos de deuda. Correr `python extract_finanzas_planificacion.py`.")
        return

    year, month = UI.selector_periodo(periodos, key="deuda_periodo")
    etiqueta = P.label_mes(year, month)
    comp = P.deuda_composicion(year, month)
    total = comp.get("Total") or 0
    comex = comp.get("COMEX") or 0
    pres = P.prestamos_tabla()
    cuota_mes = pres["cuota_mensual"].sum() / 1e6 if not pres.empty else None
    dxe = P.ratio_val(year, month, "Razón de Deuda Financiera Ebitda")

    # ─── KPIs ───────────────────────────────────────────────
    st.markdown(f"### 🎯 {etiqueta}")
    c = st.columns(4)
    UI.kpi(c[0], "Deuda financiera total", P.fmt_mm(total), "COMEX + comerciales + socios", UI.NAVY)
    UI.kpi(c[1], "COMEX (USD, rotativo)", P.fmt_mm(comex),
           f"{comex/total*100:.0f}% del total" if total else "—", UI.BLUE)
    UI.kpi(c[2], "Cuota mensual (comerciales)", P.fmt_mm(cuota_mes),
           f"{int(pres['cuotas_pend'].max()) if not pres.empty else 0} cuotas máx." , UI.BLUE)
    UI.kpi(c[3], "Deuda / EBITDA", P.fmt_ratio(dxe, "x"),
           "apalancamiento", UI.color_umbral(dxe, 3.5, 5.0, invertido=True))

    # ─── Composición + bancos ───────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        UI.barh_composicion(
            [("COMEX (USD)", comex), ("Créditos comerciales", comp.get("Comercial")),
             ("Préstamo socios", comp.get("Socios"))],
            "Dos tercios de la deuda son COMEX (MM CLP)")
    with col2:
        bancos = P.deuda_bancos_comex(year, month)
        if bancos:
            UI.barh_composicion(
                sorted(bancos.items(), key=lambda kv: -kv[1]),
                "COMEX por banco (MM CLP)", pct=False)

    # ─── Detalle por bloque (saldo + intereses) ─────────────
    det = P.deuda_detalle(year, month)
    if det:
        caract = {"COMEX": "corto plazo, rotativo, USD", "Comercial": "cuotas, tasa ~0,7%/mes",
                  "Socios": "préstamo mutuo socios"}
        filas_d = []
        for r in det:
            s = r.get("saldo")
            filas_d.append({
                "Tipo de deuda": r["bloque"],
                "Saldo": P.fmt_mm(s),
                "% del total": (f"{s/total*100:.0f}%" if (s and total) else "—"),
                "Intereses (mes)": P.fmt_mm(r.get("intereses")),
                "Característica": caract.get(r["bloque"], ""),
            })
        filas_d.append({"Tipo de deuda": "Total", "Saldo": P.fmt_mm(total), "% del total": "100%",
                        "Intereses (mes)": P.fmt_mm(sum((r.get("intereses") or 0) for r in det)),
                        "Característica": ""})
        st.dataframe(pd.DataFrame(filas_d), width="stretch", hide_index=True)

    # ─── Evolución de la deuda total ────────────────────────
    ev = P.deuda_evolucion()
    if not ev.empty:
        ev = ev[ev["MM"] > 0]  # meses sin dato vienen como 0 → no graficar caídas falsas
    if not ev.empty:
        fechas = [f"{P.MESES[d.month-1]}-{str(d.year)[2:]}" for d in ev["fecha"]]
        UI.linea_evolucion(fechas, [("Deuda total", ev["MM"].tolist())],
                           "Evolución de la deuda financiera total (MM CLP)", alto=300)

    # ─── Cronograma de cuotas ───────────────────────────────
    st.markdown("#### Cuotas por pagar — créditos comerciales")
    if not pres.empty:
        pres = pres.sort_values("total", ascending=False)
        disp = pd.DataFrame({
            "Crédito": pres["credito"],
            "Cuotas pend.": pres["cuotas_pend"].map(lambda v: f"{v:.0f}" if pd.notna(v) else "—"),
            "Cuota mensual": pres["cuota_mensual"].map(lambda v: P.fmt_mm(v / 1e6, 1)),
            "Saldo": pres["total"].map(lambda v: P.fmt_mm(v / 1e6, 1)),
            "Vencimiento": pres["vencimiento"],
        })
        st.dataframe(disp, width="stretch", hide_index=True)

        UI.barh_composicion(
            [(str(n)[:22], v / 1e6) for n, v in zip(pres["credito"], pres["cuota_mensual"])],
            "Cuota mensual por crédito (MM CLP)", pct=False, dec=1)

        # Cronograma de amortización futura (compromisos por mes)
        proj = P.cuotas_proyeccion(year, month, horizonte=18)
        if proj:
            cats = [P.label_mes(y, m) for y, m, _ in proj]
            vals = [round(t, 1) for _, _, t in proj]
            UI.barras_agrupadas(
                cats, {"Cuotas comprometidas": vals},
                f"La carga de cuotas baja de {P.fmt_mm(vals[0])} a {P.fmt_mm(vals[-1])} "
                f"mensuales en 18 meses", alto=300)
            st.caption("Compromisos fijos de créditos comerciales (cuota mensual × cuotas "
                       "pendientes por crédito). No incluye el COMEX rotativo.")

        st.info("**Riesgos:** concentración (Itaú es el mayor crédito, a 2030) · "
                "el COMEX es rotativo y en USD → refinanciamiento + riesgo cambiario, "
                "fuera de este calendario de cuotas fijas.")
    st.caption("Fuente: Planificación Financiera 2026 · hojas Deuda financiera + PRESTAMOS COMERCIALES.")
