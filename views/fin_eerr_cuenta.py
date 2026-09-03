"""
Vista EERR Proyectado por Cuenta — App Finanzas.
Estado de resultados mensual con apertura por cuenta (todas las líneas del P&L),
real + forecast, con total anual. Análogo a FCST VENTAS 2026 pero para el P&L.
Fuente: hoja P&L (pyl_mensual).
"""
import pandas as pd
import streamlit as st

from views import _fin_data as D
from views import _fin_planilla as P


def render():
    with st.sidebar:
        st.markdown("### 📒 **EERR por Cuenta**")
        st.caption("P&L mensual · apertura por cuenta")
        st.divider()

    st.title("📒 EERR Proyectado por Cuenta")
    st.caption("Estado de resultados mensual con apertura por cuenta · real + forecast · MM CLP")

    df = D.pyl()
    if df is None or df.empty:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    years = sorted(df["year"].unique())
    c1, _ = st.columns([1, 4])
    with c1:
        year = st.selectbox("Año", years, index=len(years) - 1, key="eerr_cuenta_year")

    d = df[(df["year"] == year) & (~df["seccion"].astype(str).str.startswith("Resumen EERR"))].copy()
    if d.empty:
        st.warning("Sin detalle por cuenta para ese año.")
        return

    # cutoff real (para marcar meses reales vs forecast)
    cy, cm = P.ultimo_mes_real([(int(y), int(m)) for y, m in
                                d[["year", "month"]].drop_duplicates().itertuples(index=False)])
    corte = cm if cy == year else (12 if (cy, cm) > (year, 12) else 0)

    # orden de líneas (primera aparición en la hoja)
    orden = list(dict.fromkeys(d["linea"].tolist()))
    piv = d.pivot_table(index="linea", columns="month", values="valor", aggfunc="sum") / 1000
    piv = piv.reindex(orden)
    meses_disp = [m for m in range(1, 13) if m in piv.columns]

    def _lbl(m):
        return P.MESES[m - 1] + (" ·R" if m <= corte else " ·F")

    filas = []
    for ln in orden:
        row = {"Cuenta": ln}
        tot = 0.0
        for m in meses_disp:
            v = piv.loc[ln, m] if m in piv.columns else None
            row[_lbl(m)] = P.fmt_mm(v) if pd.notna(v) else "—"
            if pd.notna(v):
                tot += v
        row["Total año"] = P.fmt_mm(tot)
        filas.append(row)

    st.caption(f"**·R** = real (hasta {P.MESES[corte-1] if corte else '—'}) · **·F** = forecast. "
               "Cuentas en el orden del P&L.")
    st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True, height=640)
    st.caption("Fuente: Planificación Financiera 2026 · hoja P&L (miles de CLP → MM).")
