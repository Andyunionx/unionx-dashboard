"""Rentabilidad — P&L de contribución por canal / categoría / marca / SKU, desde el RAW.

Waterfall: Venta neta → Costo → Margen Front → (−) Comisión / Logística / Marketing
→ Margen Final (Contribución), con % sobre venta.

Los costos variables (Comisión/Logística/Marketing) salen de las filas 'Otros costos'
del RAW. Están COMPLETOS para Falabella + Mercado Libre (planilla de Nicole, por SKU+fecha);
en otros canales pueden venir parciales, por lo que su contribución queda subestimada.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from views.shared import (
    _get_duck_conn, _parquet_version, fmt_money, fmt_pct,
    render_health_header, render_dashboard_actions_sidebar,
)

DIMS = {
    "Canal": "canal",
    "Categoría macro": "categoria_macro",
    "Categoría comercial": "categoria_comercial",
    "Marca": "marca",
    "SKU": "sku",
}
# Canales con costos variables completos (planilla Nicole). El resto queda subestimado.
CANALES_COMPLETOS = ("Falabella", "Mercado Libre")


@st.cache_data(ttl=300, show_spinner="Calculando rentabilidad…")
def _rentabilidad(desde, hasta, canal, dim_col, _v):
    con = _get_duck_conn(_v)
    where = f"fecha_venta >= '{desde}' AND fecha_venta <= '{hasta}'"
    if canal != "TODOS":
        where += f" AND canal = '{canal}'"
    q = f"""
        SELECT COALESCE(NULLIF(CAST({dim_col} AS VARCHAR), ''), '(sin dato)') dim,
               sum(TRY_CAST(venta_neta AS DOUBLE))  AS venta,
               sum(TRY_CAST(costo_total AS DOUBLE)) AS costo,
               sum(TRY_CAST(margen_front AS DOUBLE)) AS mf,
               sum(TRY_CAST(comision AS DOUBLE))    AS com,
               sum(TRY_CAST(logistica AS DOUBLE))   AS log,
               sum(TRY_CAST(marketing AS DOUBLE))   AS mkt,
               sum(TRY_CAST(margen_final AS DOUBLE)) AS contrib,
               count(*) AS n
        FROM ventas WHERE {where}
        GROUP BY 1 ORDER BY venta DESC
    """
    return con.execute(q).fetchdf()


@st.cache_data(ttl=300)
def _canales(_v):
    con = _get_duck_conn(_v)
    return con.execute("SELECT DISTINCT canal FROM ventas WHERE canal IS NOT NULL AND canal <> '' ORDER BY 1").fetchdf()["canal"].tolist()


def render():
    render_health_header("💰 Rentabilidad — Contribución por SKU / canal")
    render_dashboard_actions_sidebar(prefix="rent")
    st.caption("P&L de contribución desde el RAW (incluye Comisión/Logística/Marketing reales de "
               "Falabella + Mercado Libre, planilla de Nicole por SKU+fecha).")

    v = _parquet_version()
    hoy = datetime.now().date()

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        rango = st.date_input("Período (fecha de venta)", value=(hoy.replace(month=1, day=1), hoy),
                              max_value=hoy, format="YYYY-MM-DD", key="rent_rango")
    desde, hasta = rango if isinstance(rango, tuple) and len(rango) == 2 else (hoy.replace(month=1, day=1), hoy)
    with c2:
        canal = st.selectbox("Canal", ["TODOS"] + _canales(v), index=0, key="rent_canal")
    with c3:
        dim_lbl = st.selectbox("Abrir por", list(DIMS.keys()), index=0, key="rent_dim")
    dim_col = DIMS[dim_lbl]

    try:
        df = _rentabilidad(desde.strftime("%Y-%m-%d"), hasta.strftime("%Y-%m-%d"), canal, dim_col, v)
    except Exception as e:
        st.error(f"Error calculando rentabilidad: {e}")
        return
    if df.empty:
        st.warning("Sin datos en el período/filtro.")
        return

    # Totales
    tot = {k: float(df[k].sum()) for k in ["venta", "costo", "mf", "com", "log", "mkt", "contrib"]}
    vt = tot["venta"] or 1.0
    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Venta neta", fmt_money(tot["venta"]))
    k2.metric("Margen Front", fmt_money(tot["mf"]), delta=f"{tot['mf']/vt*100:.1f}% s/venta", delta_color="off")
    k3.metric("Com + Log + Mkt", fmt_money(-(tot["com"] + tot["log"] + tot["mkt"])),
              delta=f"{(tot['com']+tot['log']+tot['mkt'])/vt*100:.1f}% s/venta", delta_color="off")
    k4.metric("Contribución", fmt_money(tot["contrib"]), delta=f"{tot['contrib']/vt*100:.1f}% s/venta", delta_color="off")

    # P&L resumen (waterfall vertical)
    st.markdown("### P&L de contribución (total del filtro)")
    pl = pd.DataFrame([
        {"Línea": "Venta neta", "Monto": tot["venta"], "% s/venta": 100.0},
        {"Línea": "(−) Costo de venta", "Monto": -tot["costo"], "% s/venta": -tot["costo"]/vt*100},
        {"Línea": "= Margen Front", "Monto": tot["mf"], "% s/venta": tot["mf"]/vt*100},
        {"Línea": "(−) Comisión", "Monto": -tot["com"], "% s/venta": -tot["com"]/vt*100},
        {"Línea": "(−) Logística", "Monto": -tot["log"], "% s/venta": -tot["log"]/vt*100},
        {"Línea": "(−) Marketing", "Monto": -tot["mkt"], "% s/venta": -tot["mkt"]/vt*100},
        {"Línea": "= Contribución", "Monto": tot["contrib"], "% s/venta": tot["contrib"]/vt*100},
    ])
    st.dataframe(pl, width="stretch", hide_index=True, column_config={
        "Monto": st.column_config.NumberColumn(format="$%d"),
        "% s/venta": st.column_config.NumberColumn(format="%.1f%%"),
    })

    # Detalle por dimensión
    st.markdown(f"### Por {dim_lbl}")
    d = df.copy()
    d["% MF"] = d["mf"] / d["venta"].replace(0, pd.NA) * 100
    d["% Contrib"] = d["contrib"] / d["venta"].replace(0, pd.NA) * 100
    d = d.rename(columns={"dim": dim_lbl, "venta": "Venta", "costo": "Costo", "mf": "Margen Front",
                          "com": "Comisión", "log": "Logística", "mkt": "Marketing",
                          "contrib": "Contribución", "n": "Líneas"})
    cols = [dim_lbl, "Venta", "Costo", "Margen Front", "% MF", "Comisión", "Logística",
            "Marketing", "Contribución", "% Contrib", "Líneas"]
    money = st.column_config.NumberColumn(format="$%d")
    pct = st.column_config.NumberColumn(format="%.1f%%")
    st.dataframe(d[cols], width="stretch", hide_index=True, height=520, column_config={
        c: money for c in ["Venta", "Costo", "Margen Front", "Comisión", "Logística", "Marketing", "Contribución"]
    } | {"% MF": pct, "% Contrib": pct})

    if canal == "TODOS" or canal not in CANALES_COMPLETOS:
        st.caption("⚠️ Comisión/Logística/Marketing están **completos solo para Falabella y Mercado Libre** "
                   "(planilla de Nicole). En otros canales estos costos vienen parciales, así que su "
                   "**Contribución queda subestimada** (Margen Front sí es correcto en todos).")
