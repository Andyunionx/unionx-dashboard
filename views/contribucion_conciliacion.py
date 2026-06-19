"""
Conciliación Comercial vs Contable — P&L dinámico + reconciliación (con descarga Excel).

Selectores Mes / Canal / KAM. Muestra el P&L (Comercial | Contable | Δ) y la
reconciliación paso a paso (venta ajustada por devoluciones de otro período →
margen ajustado / costeo → comisiones de otro período y por caer →
contribución ajustada → diferencia por explicar). Botón para bajar el Excel
con fórmulas (mismos cálculos, recalcula con los filtros en Excel).

Solo canales con KAM comercial (Trinidad/Ignacia/Claudia/Nicole).
"""
from io import BytesIO
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from views.contribucion_loader import cargar_hoja, fmt_pesos
from views._conciliacion import (construir_dataframes, calcular, construir_workbook, MESES_OPT,
                                 construir_b2b, calcular_b2b)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARQUET = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"
NC_DET = PROJECT_ROOT / "data" / "contabilidad" / "nc_detalle_h1.parquet"


@st.cache_data(ttl=3600, show_spinner="Cargando conciliación…")
def _bundle():
    df_ar = cargar_hoja("Análisis de Resultados")
    try:
        df_gl = cargar_hoja("Detalle Glosas 2026")
    except Exception:
        df_gl = pd.DataFrame()
    try:
        df_meta = cargar_hoja("Analisis Meta vs Resultados")
    except Exception:
        df_meta = pd.DataFrame()
    nc = pd.read_parquet(NC_DET) if NC_DET.exists() else None
    nc2c = {}
    if nc is not None and PARQUET.exists():
        rows = duckdb.connect().execute(f"""
            SELECT documento, canal FROM '{PARQUET.as_posix()}'
            WHERE tipo_movimiento='Devolución' GROUP BY documento, canal
            QUALIFY row_number() OVER (PARTITION BY documento ORDER BY SUM(abs(venta_bruta)) DESC)=1
        """).fetchall()
        nc2c = {d: c for d, c in rows}
    b = construir_dataframes(df_ar, df_gl, nc, nc2c)
    b.update(construir_b2b(df_ar, df_meta))
    return b


def _render_b2b(b):
    """Bloque Distribución / B2B (Nicolás): P&L (comercial=contable) + vs Presupuesto total."""
    st.info("**Distribución (B2B) — responsable Nicolás.** No tiene visión comercial separada, "
            "así que **resultado comercial = contable**. El presupuesto no viene abierto por canal: "
            "es el **total de Distribución** (cargado bajo Paris tienda); se compara el total vs ese total.")
    mes = st.selectbox("Mes", MESES_OPT, index=0, key="b2b_mes")
    R = calcular_b2b(b, mes)
    tot = R["tot"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Venta (resultado)", fmt_pesos(tot["Venta"]))
    c2.metric("Meta Venta", fmt_pesos(R["meta_venta"]),
              delta=f"{R['cumpl_venta']*100:.0f}% cumpl." if R["cumpl_venta"] else None)
    c3.metric("Contribución (resultado)", fmt_pesos(tot["Contribución"]))
    c4.metric("Meta Contribución", fmt_pesos(R["meta_contrib"]),
              delta=f"{R['cumpl_contrib']*100:.0f}% cumpl." if R["cumpl_contrib"] else None)
    st.markdown("### P&L Distribución (resultado = comercial = contable)")
    pl = R["pl_canal"]
    if len(pl):
        tot_row = {"Canal": "TOTAL", **{k: tot.get(k, tot["Venta"] - tot["Costo"] if k == "Margen" else tot.get(k)) for k in
                                        ["Venta", "Margen", "Costo", "Comisión Venta", "Comisión Envío", "Marketing", "Contribución"]}}
        pl = pd.concat([pl, pd.DataFrame([tot_row])], ignore_index=True)
    pl_d = pl.copy()
    for c in ["Venta", "Costo", "Margen", "Comisión Venta", "Comisión Envío", "Marketing", "Contribución"]:
        if c in pl_d.columns:
            pl_d[c] = pl_d[c].map(fmt_pesos)
    st.dataframe(pl_d, width="stretch", hide_index=True)
    st.caption("Canales B2B = negocio Distribución (Paris/Walmart/Falabella tienda, Dimarsa, Lokal, "
               "Casa Mila, Ferretería, Amar, etc.). Comparación de presupuesto a nivel total.")


def render():
    with st.sidebar:
        st.markdown("### ⚖️ **Conciliación**")
        st.caption("Comercial vs Contable")
        st.markdown("---")
        if st.button("🔄 Refrescar datos", width="stretch", type="primary", key="ccon_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("⚖️ Conciliación Comercial vs Contable")
    st.caption("P&L dinámico + explicación de la diferencia (devoluciones, costeo, comisiones). "
               "Solo canales con KAM comercial.")

    try:
        b = _bundle()
    except Exception as e:
        st.error(f"❌ Error cargando datos: {e}")
        return
    if b["datos"].empty:
        st.warning("Sin datos.")
        return

    vista = st.radio("Vista", ["⚖️ Comercial (KAM)", "🏭 Distribución B2B (Nicolás)"],
                     horizontal=True, key="ccon_vista")
    st.markdown("---")
    if vista.startswith("🏭"):
        _render_b2b(b)
        return

    # ---- filtros (comercial) ----
    c1, c2, c3 = st.columns(3)
    mes = c1.selectbox("Mes", MESES_OPT, index=0, key="ccon_mes")
    canal = c2.selectbox("Canal", ["TODOS"] + b["canales"], index=0, key="ccon_canal")
    kam = c3.selectbox("KAM", ["TODOS"] + b["kams"], index=0, key="ccon_kam")

    R = calcular(b, mes, canal, kam)
    st.markdown("---")

    # ---- KPIs ----
    k1, k2, k3 = st.columns(3)
    k1.metric("Contribución Comercial", fmt_pesos(R["contrib_com"]))
    k2.metric("Contribución Contable", fmt_pesos(R["contrib_cont"]))
    k3.metric("Δ Contribución (Com − Cont)", fmt_pesos(R["delta_contrib"]))

    # ---- P&L + % sobre venta (al lado) ----
    pyl = R["pyl"].copy()
    disp = pyl.copy()
    for c in ["Comercial", "Contable", "Δ $ (Com−Cont)"]:
        disp[c] = disp[c].map(fmt_pesos)
    disp["Δ %"] = pyl["Δ %"].map(lambda v: f"{v*100:.1f}%" if v is not None and pd.notna(v) else "—")

    # estructura % sobre venta (margen, comisiones c/u, marketing, margen contribución)
    pv = pyl.set_index("Línea")
    vc = float(pv.loc["Venta", "Comercial"]); vk = float(pv.loc["Venta", "Contable"])
    fpct = lambda x, base: (f"{x/base*100:.1f}%" if base else "—")
    pct_rows = []
    for ln, etiqueta in [("Margen Directo", "Margen Directo"), ("Comisión Venta", "Comisión Venta"),
                         ("Comisión Envío", "Comisión Envío"), ("Marketing", "Marketing"),
                         ("Contribución", "Margen Contribución")]:
        pct_rows.append({"Línea": etiqueta,
                         "% Comercial": fpct(float(pv.loc[ln, "Comercial"]), vc),
                         "% Contable": fpct(float(pv.loc[ln, "Contable"]), vk)})
    pct_df = pd.DataFrame(pct_rows)

    col_pl, col_pct = st.columns([3, 2])
    with col_pl:
        st.markdown("### P&L")
        st.dataframe(disp, width="stretch", hide_index=True)
    with col_pct:
        st.markdown("### % sobre venta")
        st.dataframe(pct_df, width="stretch", hide_index=True)

    # ---- Reconciliación paso a paso ----
    st.markdown("### 🔎 Explicación de la diferencia (reconciliación paso a paso)")
    _ap = -R.get("aporte_canal", 0.0)  # aporte baja la comisión contable → explica parte de la brecha (positivo)
    filas = [
        ("Δ Contribución (Comercial − Contable)", R["delta_contrib"], "head"),
        ("① Venta comercial", R["venta_com"], ""),
        ("   (−) Devoluciones NC de otro período", -R["nc_otro"], "sub"),
        ("   = Venta ajustada", R["venta_aj"], "bold"),
        ("       (memo) NC del período", R["nc_del"], "memo"),
        ("② Margen a tasa comercial (× venta ajustada)", R["margen_aj_com"], ""),
        ("   (−) por diferencia de % de margen (costeo)", -R["costeo"], "sub"),
        ("   = Margen directo ajustado", R["margen_aj"], "bold"),
        ("       (comparar) Margen Directo Contable real", R["margen_cont_real"], "memo"),
        ("③ Comisiones de otro período (glosas, incl. 2025)", R["com_otro"], "sub"),
        ("   Comisiones por caer (no caída)", R["no_caida"], "sub"),
        ("       del cual: aporte del canal (Oportunidades Únicas, etc.)", _ap, "memo"),
        ("       del cual: provisión / aún por caer (resto)", R["no_caida"] - _ap, "memo"),
        ("④ Contribución ajustada (margen aj. − comisiones comerciales)", R["contrib_aj"], "bold"),
        ("   Contribución contable (real)", R["contrib_cont"], ""),
        ("   = Diferencia por EXPLICAR (ajustada − contable)", R["por_explicar"], "head"),
    ]
    rec = pd.DataFrame([{"Concepto": n, "Monto": v} for n, v, _ in filas])

    def _style(row):
        tipo = filas[row.name][2]
        if tipo == "head":
            return ["background-color:#DCFCE7;font-weight:700"] * 2
        if tipo == "bold":
            return ["font-weight:700"] * 2
        if tipo == "memo":
            return ["color:#94A3B8;font-style:italic"] * 2
        return [""] * 2

    sty = (rec.style.apply(_style, axis=1)
           .format({"Monto": lambda v: fmt_pesos(v)}))
    st.dataframe(sty, width="stretch", hide_index=True, height=560)
    st.caption("Regla 'otro período' según el filtro: si eliges un mes → todo lo que no es ese mes + 2025; "
               "si eliges YTD → solo 2025. La 'diferencia por explicar' es el residual que ni devoluciones, "
               "ni costeo, ni comisiones de otra fecha alcanzan a justificar.")

    # ---- descarga Excel ----
    st.markdown("---")
    try:
        wb = construir_workbook(b)
        buf = BytesIO()
        wb.save(buf)
        st.download_button(
            "⬇️ Descargar Excel (con fórmulas y selectores Mes/Canal/KAM)",
            data=buf.getvalue(),
            file_name="PyL_Comercial_vs_Contable_H1.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    except Exception as e:
        st.warning(f"No se pudo generar el Excel descargable: {e}")

    # ---- detalle (expanders) ----
    with st.expander("Detalle: NC por período de origen / Comisiones por estado"):
        st.markdown("**NC (devoluciones)** — neto por canal × origen")
        nc_d = b["nc_tab"].copy()
        if "Neto" in nc_d.columns:
            nc_d["Neto"] = nc_d["Neto"].map(fmt_pesos)
        st.dataframe(nc_d, width="stretch", hide_index=True)
        st.markdown("**Comisiones (glosas)** — monto por canal × período de origen")
        com_d = b["com_tab"].copy()
        if "Monto" in com_d.columns:
            com_d["Monto"] = com_d["Monto"].map(fmt_pesos)
        st.dataframe(com_d, width="stretch", hide_index=True)
