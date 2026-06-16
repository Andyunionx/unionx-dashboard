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
from views._conciliacion import construir_dataframes, calcular, construir_workbook, MESES_OPT

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
    nc = pd.read_parquet(NC_DET) if NC_DET.exists() else None
    nc2c = {}
    if nc is not None and PARQUET.exists():
        rows = duckdb.connect().execute(f"""
            SELECT documento, canal FROM '{PARQUET.as_posix()}'
            WHERE tipo_movimiento='Devolución' GROUP BY documento, canal
            QUALIFY row_number() OVER (PARTITION BY documento ORDER BY SUM(abs(venta_bruta)) DESC)=1
        """).fetchall()
        nc2c = {d: c for d, c in rows}
    return construir_dataframes(df_ar, df_gl, nc, nc2c)


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

    # ---- filtros ----
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

    # ---- P&L ----
    st.markdown("### P&L")
    money = st.column_config.NumberColumn(format="$%d")
    pct = st.column_config.NumberColumn(format="%.1f%%")
    pyl = R["pyl"].copy()
    pyl["Δ %"] = pyl["Δ %"] * 100
    st.dataframe(pyl, width="stretch", hide_index=True,
                 column_config={"Comercial": money, "Contable": money, "Δ $ (Com−Cont)": money, "Δ %": pct})

    # ---- Reconciliación paso a paso ----
    st.markdown("### 🔎 Explicación de la diferencia (reconciliación paso a paso)")
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
        st.dataframe(b["nc_tab"], width="stretch", hide_index=True,
                     column_config={"Neto": money})
        st.markdown("**Comisiones (glosas)** — monto por canal × período de origen")
        st.dataframe(b["com_tab"], width="stretch", hide_index=True,
                     column_config={"Monto": money})
