"""
Vista Análisis Financiero — App Finanzas.
Réplica de la hoja 'Análisis Financiero 2026': flujo de caja (método indirecto),
estructura de deuda, KPIs con benchmark/semáforo, comparación 2026 vs 2025 y
recomendaciones.
"""
import pandas as pd
import streamlit as st

from views import _fin_data as D
from views import _fin_planilla as P
from views import _fin_ui as UI


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _money(s):
    v = _num(s)
    if v is None:
        return s if s else "—"
    if abs(v) >= 1000:
        return P.fmt_mm(v / 1000)
    return f"{v:.2f}".replace(".", ",") if v != int(v) else str(int(v))


def _asis(s):
    v = _num(s)
    if v is None:
        return s if s else ""
    if abs(v) < 5 and v != int(v):
        return f"{v:.2f}".replace(".", ",")
    return f"{v:,.0f}".replace(",", ".")


def render():
    with st.sidebar:
        st.markdown("### 🧭 **Análisis Financiero**")
        st.caption("Flujo caja · KPIs · recomendaciones")
        st.divider()

    st.title("🧭 Análisis Financiero 2026")
    st.caption("Flujo de caja (indirecto) · estructura de deuda · KPIs con benchmark · recomendaciones · MM CLP")

    df = D.analisis_fin_2026() if hasattr(D, "analisis_fin_2026") else None
    if df is None:
        # loader inline (por si no está en _fin_data)
        try:
            from views._fin_data import _load_parquet
            df = _load_parquet("analisis_fin_2026")
        except Exception:
            df = None
    if df is None or df.empty:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    def sec(nombre):
        return df[df["seccion"].str.contains(nombre, case=False, na=False)]

    # ─── 1. Flujo de caja ───────────────────────────────────
    st.markdown("#### 1 · Flujo de caja 2026 (método indirecto)")
    fc = sec("FLUJO DE CAJA")
    if not fc.empty:
        st.dataframe(pd.DataFrame({
            "Concepto": fc["c0"], "2025": fc["c1"].map(_money),
            "2026": fc["c2"].map(_money), "Nota": fc["c6"],
        }), width="stretch", hide_index=True)

    # ─── 2. Estructura de deuda ─────────────────────────────
    st.markdown("#### 2 · Estructura de deuda")
    de = sec("ESTRUCTURA DE DEUDA")
    if not de.empty:
        st.dataframe(pd.DataFrame({
            "Concepto": de["c0"], "Dic-2025": de["c1"].map(_money),
            "Dic-2026": de["c2"].map(_money), "Var": de["c3"].map(_asis),
        }), width="stretch", hide_index=True)

    # ─── 3. KPIs con benchmark/semáforo ─────────────────────
    st.markdown("#### 3 · KPIs financieros (con benchmark)")
    kp = sec("KPIs FINANCIEROS")
    if not kp.empty:
        st.dataframe(pd.DataFrame({
            "KPI": kp["c0"], "2025": kp["c1"].map(_asis), "2026": kp["c2"].map(_asis),
            "Benchmark": kp["c4"], "Estado": kp["c5"], "Nota": kp["c6"],
        }), width="stretch", hide_index=True)

    # ─── 4. Comparación 2026 vs 2025 ────────────────────────
    st.markdown("#### 4 · Comparación 2026 vs 2025")
    cp = sec("COMPARACIÓN")
    if not cp.empty:
        st.dataframe(pd.DataFrame({
            "Indicador": cp["c0"], "2025": cp["c1"].map(_money), "2026": cp["c2"].map(_money),
            "Var %": cp["c4"].map(lambda s: (f"{_num(s)*100:+.0f}%" if _num(s) is not None else "")),
            "Tendencia": cp["c6"],
        }), width="stretch", hide_index=True)

    # ─── 5. Recomendaciones ─────────────────────────────────
    st.markdown("#### 5 · Recomendaciones")
    rc = sec("RECOMENDACIONES")
    if not rc.empty:
        st.dataframe(pd.DataFrame({
            "Prioridad": rc["c0"], "Área": rc["c1"], "Situación": rc["c2"],
            "Benchmark": rc["c3"], "Acción recomendada": rc["c4"],
            "Impacto": rc["c5"], "Plazo": rc["c6"],
        }), width="stretch", hide_index=True)

    st.caption("Fuente: Planificación Financiera 2026 · hoja Análisis Financiero 2026 "
               "(cifras 2026 = forecast año completo; benchmarks y semáforos según la planilla).")
