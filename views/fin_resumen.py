"""
Vista Resumen Ejecutivo YTD — App Finanzas.
Dashboard de una pantalla: cascada P&L acumulada (YTD) + comparativo
Real vs Presupuesto (Meta) vs Año anterior (YoY) + salud financiera.

Nota: la hoja "Resumen YTD" de la planilla está un año desfasada (su columna YTD
muestra 2025); este módulo calcula el YTD en vivo desde las hojas fuente
(Fcst EERR + Metas 2026 + EEFF ratios), por lo que los números son los vigentes.
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 🎯 **Resumen YTD**")
        st.caption("Real vs Ppto vs Año anterior")
        st.divider()

    st.title("🎯 Resumen Ejecutivo YTD")
    st.caption("Acumulado del año · Real vs Presupuesto (Meta) vs Año anterior · MM CLP")

    periodos = P.pl_periodos()
    if not periodos:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    year, month = UI.selector_periodo(periodos, key="res_periodo")
    real = P.pl_rango(year, 1, month)
    meta = P.presupuesto_ytd(year, month, "Meta")
    ry = P.pl_rango(year - 1, 1, month)
    etiqueta = f"Ene–{P.MESES[month - 1]} {year}"
    venta = real.get("venta")

    # ─── Hero KPIs (Real · vs Meta · YoY) ───────────────────
    st.markdown(f"### 📌 {etiqueta}")
    c = st.columns(4)

    def _hero(col, nombre, key, color, invertido=False):
        r = real.get(key)
        vm = P.yoy(r, meta.get(key))
        vy = P.yoy(r, ry.get(key))
        meta_txt = (f"vs Ppto {P.fmt_var(vm)}" if meta.get(key) is not None else "") + \
                   (f"  ·  YoY {P.fmt_var(vy)}" if vy is not None else "")
        UI.kpi(col, nombre, P.fmt_mm(r), meta_txt, color)

    _hero(c[0], "Venta", "venta", UI.NAVY)
    _hero(c[1], "Margen contribución", "mg_contrib", UI.BLUE)
    _hero(c[2], "GAV", "gav", UI.TEAL)
    _hero(c[3], "EBITDA", "ebitda", UI.BLUE)

    # ─── Cascada YTD ────────────────────────────────────────
    UI.waterfall_pl(real, f"Cascada de resultado — {etiqueta} (MM CLP)")

    # ─── Puente YoY de la utilidad ──────────────────────────
    du = (real.get("utilidad") or 0) - (ry.get("utilidad") or 0)
    UI.puente_yoy(real, ry, f"Ene–{P.MESES[month - 1]} {str(year - 1)[2:]}", etiqueta,
                  f"Qué explica que la utilidad {'mejore' if du >= 0 else 'caiga'} "
                  f"{P.fmt_mm(abs(du))} vs {year - 1} (MM CLP)")

    # ─── Comparativo YTD ────────────────────────────────────
    st.markdown("#### Comparativo — Real vs Presupuesto vs Año anterior")
    filas = []
    for k, nombre, _sub in P.PL_ORDEN:
        r = real.get(k)
        mt = meta.get(k)
        r25 = ry.get(k)
        filas.append({
            "Línea": nombre,
            "Real": P.fmt_mm(r),
            "Ppto": P.fmt_mm(mt) if mt is not None else "—",
            "vs Ppto": P.fmt_var(P.yoy(r, mt)) if mt is not None else "—",
            f"{year - 1}": P.fmt_mm(r25),
            "YoY": P.fmt_var(P.yoy(r, r25)),
            "% s/venta": P.fmt_pct_venta(r, venta),
        })
    st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)

    # ─── Capital de trabajo (KPIs) ──────────────────────────
    st.markdown(f"#### Capital de trabajo · {P.label_mes(year, month)}")
    k = P.kt_mes(year, month)
    kp = P.kt_mes(year - 1, month)
    ck = st.columns(4)
    UI.kpi(ck[0], "Existencias", P.fmt_mm(k.get("existencias")),
           f"YoY {P.fmt_var(P.yoy(k.get('existencias'), kp.get('existencias')))}", UI.NAVY)
    UI.kpi(ck[1], "Capital de trabajo neto", P.fmt_mm(k.get("ktneto")), "Exist. + CxC − CxP", UI.BLUE)
    meses = k.get("meses_exist")
    UI.kpi(ck[2], "Meses de inventario", (f"{meses:.1f}".replace(".", ",") if meses else "—"),
           "mercado ~3-5,5 meses", UI.color_umbral(meses, 3.5, 5.5, invertido=True) if meses else UI.INK)
    uso = k.get("uso")
    UI.kpi(ck[3], "Uso de bodega", (f"{uso*100:.0f}%" if uso else "—"),
           "capacidad ocupada", UI.color_umbral(uso, 0.85, 0.7) if uso else UI.INK)

    # ─── Salud financiera (ratios vs benchmark de mercado) ──
    st.markdown(f"#### Salud financiera vs mercado · {P.label_mes(year, month)}")
    yp, mp = year - 1, month
    cc = st.columns(4)

    def _ratio_tile(col, nombre, prefix):
        a = P.ratio_val(year, month, prefix)
        b = P.ratio_val(yp, mp, prefix)
        bench = next((x[5] for x in P.RATIO_CATALOGO if x[0] == prefix), "")
        sem = P.semaforo_ratio(prefix, a)
        color = {"🟢": UI.GOOD, "🟡": UI.AMBER, "🔴": UI.BAD}.get(sem, UI.INK)
        UI.kpi(col, nombre, P.fmt_ratio(a, "x"),
               f"{P.label_mes(yp, mp)}: {P.fmt_ratio(b, 'x')} · mercado {bench} {sem}", color)

    _ratio_tile(cc[0], "Razón corriente", "Ratio Liquidez - Razón Corriente")
    _ratio_tile(cc[1], "Deuda fin. / EBITDA", "Razón de Deuda Financiera Ebitda")
    _ratio_tile(cc[2], "Cobertura gastos fin.", "Cobertura Gastos")
    _ratio_tile(cc[3], "Rotación inventarios", "Rotación de Inventarios")

    st.caption("🟢 cumple / 🟡 cerca / 🔴 bajo el benchmark de mercado · "
               "Fuente: Planificación Financiera 2026 · Fcst EERR (real) + Metas 2026 (presupuesto) + "
               "EEFF (ratios). El YTD se calcula en vivo (la hoja «Resumen YTD» de la planilla está desfasada).")
