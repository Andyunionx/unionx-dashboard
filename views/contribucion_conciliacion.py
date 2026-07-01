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
                                 construir_b2b, calcular_b2b, calcular_detalle,
                                 _norm, _mes_num, _origen_glosa, num, MES_NOM)

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
    # NC desde el RAW (fuente de verdad = devoluciones Odoo), reemplaza nc_detalle_h1
    # en la reconciliación para que calce con el desglose. Devoluciones registradas en
    # 2026, por canal × origen (mismo criterio que calcular_detalle).
    if PARQUET.exists():
        ncraw = duckdb.connect().execute(f"""
            SELECT canal,
                   CAST(substr(CAST(fecha_documento AS VARCHAR),6,2) AS INTEGER) reg_mes,
                   anio_venta oa, mes_venta om,
                   -sum(TRY_CAST(venta_neta AS DOUBLE)) neto
            FROM '{PARQUET.as_posix()}'
            WHERE tipo_movimiento='Devolución'
              AND substr(CAST(fecha_documento AS VARCHAR),1,4)='2026'
              AND CAST(substr(CAST(fecha_documento AS VARCHAR),6,2) AS INTEGER) BETWEEN 1 AND 5
            GROUP BY 1,2,3,4
        """).fetchdf()
        conkam = {_norm(c): c for c in b["canales"]}
        canal_kam = dict(zip(b["datos"]["Canal"], b["datos"]["KAM"]))
        filas = []
        for _, r in ncraw.iterrows():
            d = conkam.get(_norm(r.canal))
            if not d:
                continue
            om = int(r.om or 0)
            filas.append({"Mes": MES_NOM[int(r.reg_mes)], "Canal": d, "KAM": canal_kam.get(d, ""),
                          "OrigenAnio": int(r.oa or 0),
                          "OrigenMes": MES_NOM[om] if 1 <= om <= 12 else "",
                          "Neto": float(r.neto or 0)})
        if filas:
            b["nc_tab"] = (pd.DataFrame(filas)
                           .groupby(["Mes", "Canal", "KAM", "OrigenAnio", "OrigenMes"], as_index=False)["Neto"].sum())
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


@st.cache_data(ttl=3600, show_spinner="Cargando detalle RAW…")
def _detalle_components(canales, canal_kam_items, canal_negocio_items):
    """Componentes del P&L detallado desde el RAW (ingresos/NC) + glosas (comisiones).
    Solo canales con KAM comercial. Devuelve (raw_comp, glosas_comp)."""
    conkam = {_norm(c): c for c in canales}          # norm -> nombre display
    canal_kam = dict(canal_kam_items)
    canal_neg = dict(canal_negocio_items)
    con = duckdb.connect()
    P = PARQUET.as_posix()
    # es_despacho puede no existir en el histórico deployado → usar FALSE (todo producto)
    existentes = set(con.execute(f"SELECT * FROM '{P}' LIMIT 0").df().columns)
    desp = "es_despacho" if "es_despacho" in existentes else "FALSE"
    ing = con.execute(f"""
        SELECT mes_venta mes, canal,
               CASE WHEN {desp} THEN 'ing_envio' ELSE 'ing_prod' END tipo,
               sum(TRY_CAST(venta_neta AS DOUBLE)) venta, sum(TRY_CAST(costo_total AS DOUBLE)) costo
        FROM '{P}' WHERE anio_venta=2026 AND mes_venta BETWEEN 1 AND 5 AND tipo_movimiento='Venta'
        GROUP BY 1,2,3""").fetchdf()
    nc = con.execute(f"""
        SELECT CAST(substr(CAST(fecha_documento AS VARCHAR),6,2) AS INTEGER) mes, canal,
               anio_venta oa, mes_venta om,
               sum(TRY_CAST(venta_neta AS DOUBLE)) venta, sum(TRY_CAST(costo_total AS DOUBLE)) costo
        FROM '{P}' WHERE tipo_movimiento='Devolución'
          AND substr(CAST(fecha_documento AS VARCHAR),1,4)='2026'
          AND CAST(substr(CAST(fecha_documento AS VARCHAR),6,2) AS INTEGER) BETWEEN 1 AND 5
        GROUP BY 1,2,3,4""").fetchdf()
    rows = []
    for _, r in ing.iterrows():
        d = conkam.get(_norm(r.canal))
        if not d:
            continue
        rows.append({"Canal": d, "KAM": canal_kam.get(d, ""), "Negocio": canal_neg.get(d, ""), "Tipo": r.tipo, "Mes": int(r.mes),
                     "OrigenAnio": 0, "OrigenMes": 0, "Venta": float(r.venta or 0), "Costo": float(r.costo or 0)})
    for _, r in nc.iterrows():
        d = conkam.get(_norm(r.canal))
        if not d:
            continue
        rows.append({"Canal": d, "KAM": canal_kam.get(d, ""), "Negocio": canal_neg.get(d, ""), "Tipo": "nc", "Mes": int(r.mes),
                     "OrigenAnio": int(r.oa or 0), "OrigenMes": int(r.om or 0),
                     "Venta": float(r.venta or 0), "Costo": float(r.costo or 0)})
    raw_comp = pd.DataFrame(rows)

    try:
        df_gl = cargar_hoja("Detalle Glosas 2026")
    except Exception:
        df_gl = pd.DataFrame()
    CATMAP = [("comision venta", "venta"), ("comision envio", "envio"), ("marketing", "mkt")]
    grows = []
    for _, r in df_gl.iterrows():
        d = conkam.get(_norm(r.get("Canal", "")))
        if not d:
            continue
        m = _mes_num(r.get("Mes", ""))
        if not m:
            continue
        oa, om = _origen_glosa(r.get("Glosa", ""), m)
        cn = _norm(r.get("Categoría Analítica", ""))
        cat = next((v for k, v in CATMAP if k in cn), "otro")
        grows.append({"Canal": d, "KAM": canal_kam.get(d, ""), "Negocio": canal_neg.get(d, ""), "Mes": int(m), "Cat": cat,
                      "OrigenAnio": int(oa), "OrigenMes": int(om), "Monto": num(r.get("Monto ($)", ""))})
    glosas_comp = pd.DataFrame(grows)
    return raw_comp, glosas_comp


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
    c1, c2, c3, c4 = st.columns(4)
    mes = c1.selectbox("Mes", MESES_OPT, index=0, key="ccon_mes")
    negocio = c2.selectbox("Línea de Negocio", ["TODOS"] + b.get("negocios", []), index=0, key="ccon_neg")
    canal = c3.selectbox("Canal", ["TODOS"] + b["canales"], index=0, key="ccon_canal")
    kam = c4.selectbox("KAM", ["TODOS"] + b["kams"], index=0, key="ccon_kam")

    R = calcular(b, mes, canal, kam, negocio)
    st.markdown("---")

    # ---- KPIs ----
    k1, k2, k3 = st.columns(3)
    k1.metric("Contribución Comercial", fmt_pesos(R["contrib_com"]))
    k2.metric("Contribución Contable", fmt_pesos(R["contrib_cont"]))
    k3.metric("Δ Contribución (Com − Cont)", fmt_pesos(R["delta_contrib"]))

    # ---- detalle RAW para complementar Venta y Comisiones (SECUNDARIO) ----
    # Si falla (p.ej. quirk de DuckDB en Cloud), la vista sigue mostrando el P&L de la
    # hoja + la reconciliación; solo se omite el desglose en gris.
    D = None
    try:
        canal_kam = dict(zip(b["datos"]["Canal"], b["datos"]["KAM"]))
        canal_neg = b.get("canal2negocio", {})
        raw_comp, glosas_comp = _detalle_components(tuple(b["canales"]), tuple(sorted(canal_kam.items())),
                                                    tuple(sorted(canal_neg.items())))
        D = calcular_detalle(raw_comp, glosas_comp, mes, canal, kam, negocio)
    except Exception as e:
        st.warning(f"Desglose del RAW no disponible ({type(e).__name__}) — muestro el P&L de la hoja. {str(e)[:100]}")

    # ---- P&L Comercial vs Contable + sub-filas de desglose (RAW) ----
    pyl = R["pyl"].copy()
    pv = pyl.set_index("Línea")
    gl = lambda ln, col: float(pv.loc[ln, col])
    # (Línea, comercial, contable, tipo). Todo el desglose del RAW (Odoo) es base CONTABLE:
    # la contable ≈ RAW neto (ingreso bruto − NC). El comercial sale de la hoja (KAM), no se desglosa.
    com_tot_c = gl("Comisión Venta", "Comercial") + gl("Comisión Envío", "Comercial") + gl("Marketing", "Comercial")
    com_tot_k = gl("Comisión Venta", "Contable") + gl("Comisión Envío", "Contable") + gl("Marketing", "Contable")
    pl = [("Venta", gl("Venta", "Comercial"), gl("Venta", "Contable"), "row")]
    if D is not None:  # sub-filas de desglose del RAW (solo si el detalle cargó)
        # Ingreso bruto = base CONTABLE; Devoluciones (NC) = lado COMERCIAL (impacto en la venta KAM).
        pl += [
            ("    · Ingreso por producto", None, D["ing_prod"], "memo"),
            ("    · Ingreso por envío", None, D["ing_env"], "memo"),
            ("    · Devoluciones del período", D["nc_per"], None, "memo"),
            ("    · Devoluciones otro período 2026", D["nc_o2026"], None, "memo"),
            ("    · Devoluciones 2025", D["nc_o2025"], None, "memo"),
        ]
    pl += [
        ("Costo de Venta", gl("Costo de Venta", "Comercial"), gl("Costo de Venta", "Contable"), "row"),
        ("= Margen Directo", gl("Margen Directo", "Comercial"), gl("Margen Directo", "Contable"), "bold"),
        ("Comisión Venta", gl("Comisión Venta", "Comercial"), gl("Comisión Venta", "Contable"), "row"),
        ("Comisión Envío", gl("Comisión Envío", "Comercial"), gl("Comisión Envío", "Contable"), "row"),
        ("Marketing", gl("Marketing", "Comercial"), gl("Marketing", "Contable"), "row"),
    ]
    if D is not None:
        pl.append(("    · Glosa otro período (timing)", None, -D["glosa_otro"], "memo"))
    pl += [
        ("= Total Comisiones", com_tot_c, com_tot_k, "bold"),
        ("= Contribución", gl("Contribución", "Comercial"), gl("Contribución", "Contable"), "head"),
    ]
    _f = lambda v: fmt_pesos(v) if v is not None else ""
    disp = pd.DataFrame([{
        "Línea": n, "Comercial": _f(com), "Contable": _f(cont),
        "Δ $ (Com−Cont)": _f(com - cont) if (com is not None and cont is not None) else "",
        "Δ %": (f"{(com - cont) / abs(cont) * 100:.1f}%" if (com is not None and cont not in (None, 0)) else ""),
    } for n, com, cont, _ in pl])

    def _sty_pl(row):
        t = pl[row.name][3]
        if t == "head":
            return ["background-color:#DCFCE7;font-weight:700"] * 5
        if t == "bold":
            return ["font-weight:700;background-color:#F1F5F9"] * 5
        if t == "memo":
            return ["color:#94A3B8;font-style:italic;font-size:0.92em"] * 5
        return [""] * 5

    # estructura % sobre venta (margen, comisiones c/u, marketing, margen contribución)
    vc = gl("Venta", "Comercial"); vk = gl("Venta", "Contable")
    fpct = lambda x, base: (f"{x/base*100:.1f}%" if base else "—")
    pct_df = pd.DataFrame([{"Línea": etq, "% Comercial": fpct(gl(ln, "Comercial"), vc),
                            "% Contable": fpct(gl(ln, "Contable"), vk)}
                           for ln, etq in [("Margen Directo", "Margen Directo"), ("Comisión Venta", "Comisión Venta"),
                                           ("Comisión Envío", "Comisión Envío"), ("Marketing", "Marketing"),
                                           ("Contribución", "Margen Contribución")]])

    col_pl, col_pct = st.columns([3, 2])
    with col_pl:
        st.markdown("### P&L (Comercial vs Contable)")
        st.dataframe(disp.style.apply(_sty_pl, axis=1), width="stretch", hide_index=True, height=500)
        st.caption("Filas en gris (·): **Ingreso producto/envío** (bruto) = base **contable**. "
                   "**Devoluciones (NC)** van en la columna **Comercial** (impacto en la venta KAM), abiertas "
                   "por período de origen. 'NC otro período 2026' solo se llena al elegir un mes (en YTD todo "
                   "2026 es 'del período').")
    with col_pct:
        st.markdown("### % sobre venta")
        st.dataframe(pct_df, width="stretch", hide_index=True)

    # ---- Devoluciones (NC) por origen: impacto en margen (lado comercial) ----
    if D is not None:
        st.markdown("#### 🔻 Devoluciones (NC) por período de origen — impacto en margen comercial")
        dev_rows = [
            ("Del período (origen 2026)", D["nc_per"], D["nc_per_c"]),
            ("Otro período 2026", D["nc_o2026"], D["nc_o2026_c"]),
            ("2025", D["nc_o2025"], D["nc_o2025_c"]),
        ]
        tot_v = sum(v for _, v, _ in dev_rows)
        tot_c = sum(c for _, _, c in dev_rows)
        dev_rows.append(("= Total devoluciones", tot_v, tot_c))
        dev_df = pd.DataFrame([{
            "Período de origen": n, "Venta (neto)": fmt_pesos(v), "Costo": fmt_pesos(c),
            "Margen Directo": fmt_pesos(v - c),
        } for n, v, c in dev_rows])
        _last = len(dev_rows) - 1
        dev_sty = dev_df.style.apply(
            lambda r: (["font-weight:700;background-color:#F1F5F9"] * 4 if r.name == _last else [""] * 4), axis=1)
        st.dataframe(dev_sty, width="stretch", hide_index=True)
        st.caption("Margen Directo = Venta − Costo (ambos negativos: la NC revierte la venta y su costo). "
                   "'Del período' = NC de ventas del mismo período; 'Otro período 2026' se llena al elegir un mes "
                   "(NC de otro mes de 2026); '2025' = NC de ventas del año anterior.")

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
