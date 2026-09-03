"""
Vista Capital de Trabajo (KT) — App Finanzas.
KT neto + doble-click a la composición de existencias (IW/IT/MP), meses y capacidad.
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 📦 **Capital de Trabajo**")
        st.caption("KT neto · existencias")
        st.divider()

    st.title("📦 Capital de Trabajo (KT)")
    st.caption("KT neto · composición de existencias (bodega/tránsito/MP) · meses de inventario · MM CLP")

    periodos = P.kt_periodos()
    if not periodos:
        st.warning("⏳ Sin datos de KT. Correr `python extract_finanzas_planificacion.py`.")
        return

    year, month = UI.selector_periodo(periodos, key="kt_periodo")
    k = P.kt_mes(year, month)
    kp = P.kt_mes(year - 1, month)
    etiqueta = P.label_mes(year, month)

    # ─── KPIs ───────────────────────────────────────────────
    st.markdown(f"### 🎯 {etiqueta}")
    c = st.columns(4)
    UI.kpi(c[0], "Existencias", P.fmt_mm(k.get("existencias")),
           f"YoY {P.fmt_var(P.yoy(k.get('existencias'), kp.get('existencias')))}", UI.NAVY)
    UI.kpi(c[1], "Capital de trabajo neto", P.fmt_mm(k.get("ktneto")),
           "Existencias + CxC − CxP", UI.BLUE)
    meses = k.get("meses_exist")
    UI.kpi(c[2], "Meses de inventario", f"{meses:.1f}".replace(".", ",") if meses else "—",
           f"objetivo ~3 · bodega {k.get('meses_iw', 0):.1f}".replace(".", ","),
           UI.color_umbral(meses, 3.5, 5.5, invertido=True) if meses else UI.INK)
    uso = k.get("uso")
    UI.kpi(c[3], "Uso de bodega", f"{uso*100:.0f}%" if uso else "—",
           f"{k.get('pos_tomadas', 0):.0f} / {k.get('cap_total', 0):.0f} posiciones",
           UI.color_umbral(uso, 0.85, 0.7) if uso else UI.INK)

    # ─── Composición existencias ────────────────────────────
    col1, col2 = st.columns([3, 2])
    with col1:
        UI.barh_composicion(
            [("Bodega (IW)", k.get("iw")), ("Tránsito (IT)", k.get("it")),
             ("Materias primas", k.get("mp"))],
            "El inventario está mayormente en bodega (MM CLP)")
    with col2:
        st.markdown("**Meses de inventario**")
        ex = k.get("existencias") or 1
        rows = [
            ("Bodega (IW)", k.get("iw"), k.get("meses_iw")),
            ("Tránsito (IT)", k.get("it"), k.get("meses_it")),
            ("Materias primas", k.get("mp"), k.get("meses_mp")),
            ("Total", k.get("existencias"), k.get("meses_exist")),
        ]
        disp = pd.DataFrame([{
            "Tipo": n, "Saldo": P.fmt_mm(v),
            "%": f"{(v or 0)/ex*100:.0f}%",
            "Meses": f"{m:.1f}".replace(".", ",") if m else "—",
        } for n, v, m in rows])
        st.dataframe(disp, width="stretch", hide_index=True)

    # ─── KT neto + ciclo ────────────────────────────────────
    st.markdown("#### Capital de trabajo y ciclo de caja")
    dso = (k.get("meses_cxc") or 0) * 30
    dpo = (k.get("meses_cxp") or 0) * 30
    dias_inv = (k.get("meses_exist") or 0) * 30
    ccc = dias_inv + dso - dpo
    col3, col4 = st.columns(2)
    with col3:
        st.dataframe(pd.DataFrame([
            {"Componente": "Existencias", "Valor": P.fmt_mm(k.get("existencias"))},
            {"Componente": "(+) Cuentas por cobrar", "Valor": P.fmt_mm(k.get("cxc"))},
            {"Componente": "(−) Cuentas por pagar", "Valor": P.fmt_mm(abs(k.get("cxp") or 0))},
            {"Componente": "(=) Capital de trabajo neto", "Valor": P.fmt_mm(k.get("ktneto"))},
        ]), width="stretch", hide_index=True)
    with col4:
        st.dataframe(pd.DataFrame([
            {"Ciclo de caja": "Días de inventario", "Días": f"{dias_inv:.0f}"},
            {"Ciclo de caja": "+ Días de cobro (DSO)", "Días": f"{dso:.0f}"},
            {"Ciclo de caja": "− Días de pago (DPO)", "Días": f"{dpo:.0f}"},
            {"Ciclo de caja": "= Ciclo de conversión", "Días": f"{ccc:.0f}"},
        ]), width="stretch", hide_index=True)

    # ─── Evolución de meses de inventario ───────────────────
    ser = P.kt_serie("Meses de existencias móvil")
    if not ser.empty:
        ser = ser[ser["valor"] > 0]
        fechas = [f"{P.MESES[d.month-1]}-{str(d.year)[2:]}" for d in ser["fecha"]]
        vals = ser["valor"].tolist()
        cierre = vals[-1]
        actual = meses or cierre
        tendencia = ("baja hacia" if cierre < actual - 0.2 else
                     ("sube hacia" if cierre > actual + 0.2 else "se mantiene en"))
        posicion = "aún sobre el mercado" if cierre > 5.5 else "entrando al rango de mercado"
        UI.linea_evolucion(
            fechas, [("Inventario", vals)],
            f"El inventario {tendencia} {cierre:.1f} meses al cierre — {posicion}".replace(".", ","),
            unidad="meses", alto=320, banda=(3.0, 5.5, "rango mercado 3–5,5"))
        st.caption("Serie de la hoja KT (últimos meses del año = forecast).")

    st.info("**El inventario es la palanca de caja.** Existencias de "
            + P.fmt_mm_md(k.get("existencias"))
            + f" = {meses:.1f}".replace(".", ",") + " meses"
            + f" (bodega {k.get('meses_iw', 0):.1f}".replace(".", ",")
            + f", objetivo ~3), con la bodega al {uso*100:.0f}% de capacidad. "
            "Bajar el inventario hacia el objetivo libera caja y alivia la presión de financiamiento.")
    st.caption("Fuente: Planificación Financiera 2026 · hoja KT (miles de CLP → MM).")
