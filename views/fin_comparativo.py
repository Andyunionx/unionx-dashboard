"""
Vista Análisis Comparativo — App Finanzas.
Real vs Año Anterior vs Presupuesto, línea por línea del P&L, con % s/venta
(Real vs Ppto) y Δ en puntos de margen. Frame: YTD acumulado (Ene→mes).
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def _pp(real, venta_r, meta, venta_m):
    if None in (real, venta_r, meta, venta_m) or venta_r == 0 or venta_m == 0:
        return None
    return (real / venta_r - meta / venta_m) * 100


def render():
    with st.sidebar:
        st.markdown("### ⚖️ **Análisis Comparativo**")
        st.caption("Real vs Ppto vs Año anterior")
        st.divider()

    st.title("⚖️ Análisis Comparativo")
    st.caption("Real vs Presupuesto vs Año anterior · % s/venta y Δ en puntos de margen · YTD · MM CLP")

    periodos = P.pl_periodos()
    if not periodos:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    year, month = UI.selector_periodo(periodos, key="comp_periodo")
    real = P.pl_rango(year, 1, month)
    meta = P.presupuesto_ytd(year, month, "Meta")
    ry = P.pl_rango(year - 1, 1, month)
    etiqueta = f"Ene–{P.MESES[month - 1]} {year}"
    vr = real.get("venta")
    vm = meta.get("venta")

    st.markdown(f"### 📌 {etiqueta}")

    # ─── Comparativo principal ──────────────────────────────
    st.markdown("#### Comparativo — Real · Presupuesto · Año anterior")
    filas = []
    for k, nombre, _sub in P.PL_ORDEN:
        r = real.get(k)
        mt = meta.get(k)
        r25 = ry.get(k)
        filas.append({
            "Línea": nombre,
            "Real": P.fmt_mm(r),
            "Ppto": P.fmt_mm(mt) if mt is not None else "—",
            "Δ vs Ppto": P.fmt_var(P.yoy(r, mt)) if mt is not None else "—",
            f"{year - 1}": P.fmt_mm(r25),
            "Δ YoY": P.fmt_var(P.yoy(r, r25)),
        })
    st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)

    # ─── Análisis de rentabilidad (% s/venta y Δpp) ─────────
    st.markdown("#### Rentabilidad — % sobre venta (Real vs Ppto)")
    filas2 = []
    for k, nombre, _sub in P.PL_ORDEN:
        if k == "venta":
            continue
        r = real.get(k)
        mt = meta.get(k)
        pp = _pp(r, vr, mt, vm) if mt is not None else None
        filas2.append({
            "Línea": nombre,
            "% s/venta Real": P.fmt_pct_venta(r, vr),
            "% s/venta Ppto": (f"{mt / vm * 100:.1f}%".replace(".", ",") if (mt is not None and vm) else "—"),
            "Δ puntos margen": (f"{pp:+.1f} pp".replace(".", ",") if pp is not None else "—"),
        })
    st.dataframe(pd.DataFrame(filas2), width="stretch", hide_index=True)

    # ─── Barras comparativas ────────────────────────────────
    cats = ["Venta", "Contribución", "GAV", "EBITDA"]
    keys = ["venta", "mg_contrib", "gav", "ebitda"]
    UI.barras_agrupadas(
        cats,
        {"Año ant.": [ry.get(k) for k in keys],
         "Ppto": [meta.get(k) for k in keys],
         "Real": [real.get(k) for k in keys]},
        f"Real vs Ppto vs Año anterior — {etiqueta} (MM CLP)")

    st.caption("Fuente: Planificación Financiera 2026 · Fcst EERR (real + año anterior) + Metas 2026 (presupuesto).")
