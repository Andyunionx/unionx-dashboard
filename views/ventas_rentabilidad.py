"""Rentabilidad — P&L de contribución por línea de negocio / canal / categoría / marca / SKU.

Waterfall: Venta neta → Costo → Margen Front → (−) Comisión / Logística / Marketing
→ Margen Final (Contribución), con % sobre venta.

Costos variables (Comisión/Logística/Marketing) = filas 'Otros costos' del RAW. COMPLETOS
para Falabella + Mercado Libre (planilla de Nicole por SKU+fecha); en otros canales pueden
venir parciales → su contribución queda subestimada (el Margen Front sí es correcto en todos).
"""
import calendar
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from views.shared import (
    _get_duck_conn, _parquet_version, fmt_money, fmt_pct,
    render_health_header, render_dashboard_actions_sidebar,
)

YEAR = 2026
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
MESES_FULL = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
              "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
DIMS = {
    "Línea de Negocio": "tipo_negocio",
    "Canal": "canal",
    "Categoría macro": "categoria_macro",
    "Categoría comercial": "categoria_comercial",
    "Marca": "marca",
    "SKU": "sku",
}
CANALES_COMPLETOS = ("Falabella", "Mercado Libre")


def _periodos():
    hoy = datetime.now().strftime("%Y-%m-%d")
    fin = lambda m: f"{YEAR}-{m:02d}-{calendar.monthrange(YEAR, m)[1]:02d}"
    p = {f"YTD {YEAR}": (f"{YEAR}-01-01", hoy),
         "1er semestre (Ene–Jun)": (f"{YEAR}-01-01", fin(6)),
         "2do semestre (Jul–Dic)": (f"{YEAR}-07-01", fin(12))}
    for i, (a, b) in enumerate([(1, 3), (4, 6), (7, 9), (10, 12)], 1):
        p[f"Q{i} ({MESES[a-1]}–{MESES[b-1]})"] = (f"{YEAR}-{a:02d}-01", fin(b))
    for m in range(1, 13):
        p[MESES_FULL[m - 1]] = (f"{YEAR}-{m:02d}-01", fin(m))
    return p


def _sql_in(col, valores):
    if not valores:
        return ""
    lst = ",".join("'" + str(x).replace("'", "''") + "'" for x in valores)
    return f" AND {col} IN ({lst})"


@st.cache_data(ttl=300, show_spinner="Calculando rentabilidad…")
def _rentabilidad(desde, hasta, canales, negocios, dim_col, _v):
    con = _get_duck_conn(_v)
    where = (f"fecha_venta >= '{desde}' AND fecha_venta <= '{hasta}'"
             + _sql_in("canal", canales) + _sql_in("tipo_negocio", negocios))
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


@st.cache_data(ttl=300, show_spinner="Preparando descarga…")
def _export_bytes(desde, hasta, canales, negocios, _v):
    """Excel detallado (una fila por Año×Mes×LíneaNegocio×Canal×Cat×Marca×SKU) para pivotear."""
    con = _get_duck_conn(_v)
    where = (f"fecha_venta >= '{desde}' AND fecha_venta <= '{hasta}'"
             + _sql_in("canal", canales) + _sql_in("tipo_negocio", negocios))
    q = f"""
        SELECT anio_venta "Año", mes_venta "Mes", tipo_negocio "Línea Negocio", canal "Canal",
               categoria_macro "Cat macro", categoria_padre "Cat padre", categoria_comercial "Cat comercial",
               marca "Marca", sku "SKU", any_value(producto) "Producto",
               sum(TRY_CAST(venta_neta AS DOUBLE))  "Venta neta",
               sum(TRY_CAST(costo_total AS DOUBLE)) "Costo",
               sum(TRY_CAST(margen_front AS DOUBLE)) "Margen Front",
               sum(TRY_CAST(comision AS DOUBLE))    "Comisión",
               sum(TRY_CAST(logistica AS DOUBLE))   "Logística",
               sum(TRY_CAST(marketing AS DOUBLE))   "Marketing",
               sum(TRY_CAST(margen_final AS DOUBLE)) "Contribución",
               sum(TRY_CAST(cantidad AS DOUBLE))    "Unidades"
        FROM ventas WHERE {where}
        GROUP BY 1,2,3,4,5,6,7,8,9 ORDER BY "Venta neta" DESC
    """
    det = con.execute(q).fetchdf()
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        det.to_excel(xw, sheet_name="Detalle", index=False)
    return buf.getvalue(), len(det)


@st.cache_data(ttl=300)
def _opciones(_v):
    con = _get_duck_conn(_v)
    can = con.execute("SELECT DISTINCT canal FROM ventas WHERE canal IS NOT NULL AND canal <> '' ORDER BY 1").fetchdf()["canal"].tolist()
    neg = con.execute("SELECT DISTINCT tipo_negocio FROM ventas WHERE tipo_negocio IS NOT NULL AND tipo_negocio <> '' ORDER BY 1").fetchdf()["tipo_negocio"].tolist()
    return can, neg


@st.cache_data(ttl=300)
def _alarmas(desde, hasta, _v):
    """Alarmas de baja rentabilidad por SKU x canal. Solo Falabella + ML (costos completos)."""
    con = _get_duck_conn(_v)
    excl = "NOT COALESCE(es_despacho, false) AND producto NOT LIKE 'Nota de Cr%' AND sku <> ''"
    sk = con.execute(f"""
        SELECT sku, canal, any_value(producto) prod, any_value(categoria_macro) cat,
               sum(TRY_CAST(venta_neta AS DOUBLE)) venta,
               sum(TRY_CAST(margen_final AS DOUBLE)) contrib,
               sum(TRY_CAST(cantidad AS DOUBLE)) uds
        FROM ventas WHERE canal IN ('Falabella','Mercado Libre')
          AND fecha_venta BETWEEN '{desde}' AND '{hasta}' AND {excl}
        GROUP BY sku, canal
    """).fetchdf()
    sk = sk[sk["venta"] > 0].copy()
    sk["cpct"] = sk["contrib"] / sk["venta"] * 100
    neg = sk[(sk["contrib"] < 0) & (sk["venta"] > 5e5)].sort_values("contrib")
    delg = sk[(sk["cpct"] >= 0) & (sk["cpct"] < 10) & (sk["venta"] > 1e6)].sort_values("cpct")
    f = sk[sk.canal == "Falabella"].set_index("sku")
    m = sk[sk.canal == "Mercado Libre"].set_index("sku")
    b = pd.DataFrame({"prod": f["prod"], "cp_fa": f["cpct"], "cp_ml": m["cpct"],
                      "v_fa": f["venta"], "v_ml": m["venta"]}).dropna(subset=["cp_fa", "cp_ml"])
    b["vtot"] = b["v_fa"] + b["v_ml"]
    b["gap"] = b["cp_fa"] - b["cp_ml"]
    brecha = b[(b["gap"].abs() > 15) & (b["vtot"] > 5e6)]
    brecha = brecha.reindex(brecha["gap"].abs().sort_values(ascending=False).index)
    return neg, delg, brecha


def render():
    render_health_header("💰 Rentabilidad — Contribución por SKU / canal")
    render_dashboard_actions_sidebar(prefix="rent")
    st.caption("P&L de contribución desde el RAW (Comisión/Logística/Marketing reales de "
               "Falabella + Mercado Libre, planilla de Nicole por SKU+fecha).")

    v = _parquet_version()
    canales_all, negocios_all = _opciones(v)
    periodos = _periodos()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        per = st.selectbox("Período", list(periodos.keys()), index=0, key="rent_per")
    with c2:
        canales = st.multiselect("Canal (vacío = todos)", canales_all, default=[], key="rent_canal")
    with c3:
        negocios = st.multiselect("Línea de Negocio (vacío = todas)", negocios_all, default=[], key="rent_neg")
    with c4:
        dim_lbl = st.selectbox("Abrir por", list(DIMS.keys()), index=0, key="rent_dim")
    desde, hasta = periodos[per]
    dim_col = DIMS[dim_lbl]

    # Descarga: tabla detallada (pivotable) con toda la info del filtro actual
    try:
        xls_bytes, n_export = _export_bytes(desde, hasta, tuple(canales), tuple(negocios), v)
        st.download_button(
            f"⬇️ Descargar tabla detallada para pivote ({n_export:,} filas)".replace(",", "."),
            data=xls_bytes, file_name=f"Rentabilidad_{per.split(' ')[0]}_{YEAR}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="rent_dl")
    except Exception as e:
        st.caption(f"(descarga no disponible: {type(e).__name__}: {str(e)[:80]})")

    try:
        df = _rentabilidad(desde, hasta, tuple(canales), tuple(negocios), dim_col, v)
    except Exception as e:
        st.error(f"Error calculando rentabilidad: {e}")
        return
    if df.empty:
        st.warning("Sin datos en el período/filtro.")
        return

    tot = {k: float(df[k].sum()) for k in ["venta", "costo", "mf", "com", "log", "mkt", "contrib"]}
    vt = tot["venta"] or 1.0
    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Venta neta", fmt_money(tot["venta"]))
    k2.metric("Margen Front", fmt_money(tot["mf"]), delta=f"{tot['mf']/vt*100:.1f}% s/venta", delta_color="off")
    k3.metric("Com + Log + Mkt", fmt_money(-(tot["com"] + tot["log"] + tot["mkt"])),
              delta=f"{(tot['com']+tot['log']+tot['mkt'])/vt*100:.1f}% s/venta", delta_color="off")
    k4.metric("Contribución", fmt_money(tot["contrib"]), delta=f"{tot['contrib']/vt*100:.1f}% s/venta", delta_color="off")

    st.markdown(f"### P&L de contribución — {per}")
    pl = pd.DataFrame([
        ("Venta neta", tot["venta"], 100.0),
        ("(−) Costo de venta", -tot["costo"], -tot["costo"]/vt*100),
        ("= Margen Front", tot["mf"], tot["mf"]/vt*100),
        ("(−) Comisión", -tot["com"], -tot["com"]/vt*100),
        ("(−) Logística", -tot["log"], -tot["log"]/vt*100),
        ("(−) Marketing", -tot["mkt"], -tot["mkt"]/vt*100),
        ("= Contribución", tot["contrib"], tot["contrib"]/vt*100),
    ], columns=["Línea", "Monto", "% s/venta"])
    pl["Monto"] = pl["Monto"].map(fmt_money)
    pl["% s/venta"] = pl["% s/venta"].map(lambda x: fmt_pct(x))
    st.dataframe(pl, width="stretch", hide_index=True)

    st.markdown(f"### Por {dim_lbl}")
    d = df.copy()
    d["% MF"] = (d["mf"] / d["venta"].replace(0, pd.NA) * 100).map(lambda x: fmt_pct(x))
    d["% Contrib"] = (d["contrib"] / d["venta"].replace(0, pd.NA) * 100).map(lambda x: fmt_pct(x))
    for c in ["venta", "costo", "mf", "com", "log", "mkt", "contrib"]:
        d[c] = d[c].map(fmt_money)
    d = d.rename(columns={"dim": dim_lbl, "venta": "Venta", "costo": "Costo", "mf": "Margen Front",
                          "com": "Comisión", "log": "Logística", "mkt": "Marketing",
                          "contrib": "Contribución", "n": "Líneas"})
    cols = [dim_lbl, "Venta", "Costo", "Margen Front", "% MF", "Comisión", "Logística",
            "Marketing", "Contribución", "% Contrib", "Líneas"]
    st.dataframe(d[cols], width="stretch", hide_index=True, height=520)

    # ---- Alarmas de rentabilidad (Fala+ML, período del filtro) ----
    st.markdown("### 🚨 Alarmas de rentabilidad")
    st.caption("Solo Falabella + Mercado Libre (costos completos). Período según el filtro de arriba.")
    neg, delg, brecha = _alarmas(desde, hasta, v)
    a1, a2, a3 = st.columns(3)
    a1.metric("🔴 Contribución negativa", f"{len(neg)} SKU",
              f"{fmt_money(neg['contrib'].sum())} destruidos" if len(neg) else "sin casos", delta_color="off")
    a2.metric("🟠 Margen delgado (<10%)", f"{len(delg)} SKU",
              f"{fmt_money(delg['venta'].sum())} en venta" if len(delg) else "sin casos", delta_color="off")
    a3.metric("🔵 Brecha entre canales (>15pp)", f"{len(brecha)} SKU",
              "vender en el canal rentable" if len(brecha) else "sin casos", delta_color="off")

    def _tbl_sku(df, extra=None):
        t = df.copy()
        t["Venta"] = t["venta"].map(fmt_money)
        t["Contribución"] = t["contrib"].map(fmt_money)
        t["% Contrib"] = t["cpct"].map(lambda x: fmt_pct(x))
        t = t.rename(columns={"canal": "Canal", "prod": "Producto", "cat": "Categoría"})
        return t[["Canal", "Producto", "Categoría", "Venta", "Contribución", "% Contrib"]]

    with st.expander(f"🔴 Contribución negativa — destruyen valor ({len(neg)})", expanded=len(neg) > 0):
        st.dataframe(_tbl_sku(neg), width="stretch", hide_index=True) if len(neg) else st.caption("Sin casos.")
    with st.expander(f"🟠 Margen delgado <10% con venta >$1M ({len(delg)})"):
        st.dataframe(_tbl_sku(delg), width="stretch", hide_index=True) if len(delg) else st.caption("Sin casos.")
    with st.expander(f"🔵 Misma SKU, brecha >15pp entre canales ({len(brecha)})"):
        if len(brecha):
            bb = brecha.copy()
            bb["Mejor en"] = bb["gap"].map(lambda g: "Falabella" if g > 0 else "Mercado Libre")
            bb["% Falabella"] = bb["cp_fa"].map(lambda x: fmt_pct(x))
            bb["% Mercado Libre"] = bb["cp_ml"].map(lambda x: fmt_pct(x))
            bb["Brecha (pp)"] = bb["gap"].map(lambda x: f"{abs(x):.0f}")
            bb["Venta comb."] = bb["vtot"].map(fmt_money)
            st.dataframe(bb.reset_index()[["prod", "% Falabella", "% Mercado Libre", "Brecha (pp)", "Mejor en", "Venta comb."]]
                         .rename(columns={"prod": "Producto"}), width="stretch", hide_index=True)
        else:
            st.caption("Sin casos.")

    seleccion_incompleta = (not canales) or any(c not in CANALES_COMPLETOS for c in canales)
    if seleccion_incompleta:
        st.caption("⚠️ Comisión/Logística/Marketing están **completos solo para Falabella y Mercado Libre** "
                   "(planilla de Nicole). En otros canales vienen parciales → su **Contribución queda "
                   "subestimada** (el Margen Front sí es correcto en todos).")
