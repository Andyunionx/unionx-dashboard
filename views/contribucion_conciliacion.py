"""
Conciliación Comercial vs Contable — P&L dinámico + reconciliación (con descarga Excel).

Selectores Mes / Canal / KAM. Muestra el P&L (Comercial | Contable | Δ) y la
reconciliación paso a paso (venta ajustada por devoluciones de otro período →
margen ajustado / costeo → comisiones de otro período y por caer →
contribución ajustada → diferencia por explicar). Botón para bajar el Excel
con fórmulas (mismos cálculos, recalcula con los filtros en Excel).

Scope = líneas de negocio Marketplace / Fidelización / Páginas Propias + canal
UnionX B2B (alineado con el crossover de devoluciones).
"""
from io import BytesIO
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from views.contribucion_loader import cargar_hoja, fmt_pesos
import views._conciliacion as _conc
from views._conciliacion import (construir_dataframes, calcular, construir_workbook,
                                 construir_b2b, calcular_b2b, calcular_detalle,
                                 _norm, _mes_num, _origen_glosa, num, MES_NOM)
# MES_MAX / MESES_OPT se leen vía _conc.* porque se auto-detectan del Sheet en runtime.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARQUET = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"
NC_DET = PROJECT_ROOT / "data" / "contabilidad" / "nc_detalle_h1.parquet"

SHEET_CONTRIB = "1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4"      # Análisis de Contribución
SHEET_SEGUIMIENTO = "1d7iN4M-AoNZvBEXxvGWYK5pJoXAI6VxzJIdjh12QNjM"  # Seguimiento contribución
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@st.cache_data(ttl=1800, show_spinner=False)
def _hoja_xlsx(sheet_id: str, tab: str) -> bytes:
    """Lee una hoja de un Drive (por id + pestaña, match tolerante) y la devuelve como .xlsx."""
    from views.contribucion_loader import _gspread_client
    gc = _gspread_client()
    sh = gc.open_by_key(sheet_id)
    ws = None
    for w in sh.worksheets():
        if _norm(w.title) == _norm(tab):
            ws = w
            break
    if ws is None:  # match parcial (ej. "Resumen 2026" con espacios/variantes)
        for w in sh.worksheets():
            if _norm(tab) in _norm(w.title) or _norm(w.title) in _norm(tab):
                ws = w
                break
    if ws is None:
        raise ValueError(f"pestaña '{tab}' no encontrada")
    vals = ws.get_all_values()
    df = pd.DataFrame(vals[1:], columns=vals[0]) if vals else pd.DataFrame()
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=ws.title[:31])
    return buf.getvalue()


@st.cache_data(ttl=300, show_spinner="Cargando conciliación…")
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
    # NC = Devolución del RAW (misma fuente que la venta), por canal × mes registro × origen.
    if PARQUET.exists():
        ncraw = duckdb.connect().execute(f"""
            SELECT canal,
                   CAST(substr(CAST(fecha_documento AS VARCHAR),6,2) AS INTEGER) reg_mes,
                   anio_venta oa, mes_venta om,
                   -sum(TRY_CAST(venta_neta AS DOUBLE)) neto
            FROM '{PARQUET.as_posix()}'
            WHERE tipo_movimiento='Devolución'
              AND substr(CAST(fecha_documento AS VARCHAR),1,4)='2026'
              AND CAST(substr(CAST(fecha_documento AS VARCHAR),6,2) AS INTEGER) BETWEEN 1 AND {_conc.MES_MAX}
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
    st.info("**Distribución + Corporativo (B2B) — responsable Nicolás.** Incluye los negocios "
            "Distribución y Corporativo (UnionX B2B, Sodimac, Dinasty, etc.). No tiene visión comercial "
            "separada, así que **resultado comercial = contable**. El presupuesto es el **total de "
            "Distribución** (cargado bajo Paris tienda); se compara el total vs ese total.")
    mes = st.selectbox("Mes", _conc.MESES_OPT, index=0, key="b2b_mes")
    R = calcular_b2b(b, mes)
    tot = R["tot"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Venta (resultado)", fmt_pesos(tot["Venta"]))
    c2.metric("Meta Venta", fmt_pesos(R["meta_venta"]),
              delta=f"{R['cumpl_venta']*100:.0f}% cumpl." if R["cumpl_venta"] else None)
    c3.metric("Contribución (resultado)", fmt_pesos(tot["Contribución"]))
    c4.metric("Meta Contribución", fmt_pesos(R["meta_contrib"]),
              delta=f"{R['cumpl_contrib']*100:.0f}% cumpl." if R["cumpl_contrib"] else None)
    st.markdown("### P&L Distribución + Corporativo (resultado = comercial = contable)")
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
    st.caption("Canales = negocios Distribución (Paris/Walmart/Falabella tienda, Dimarsa, Lokal, "
               "Casa Mila, Ferretería, etc.) + Corporativo (UnionX B2B, Sodimac, Dinasty, "
               "Concesionarios, Vinoteca). Presupuesto = total Distribución.")


@st.cache_data(ttl=300, show_spinner="Cargando detalle RAW…")
def _detalle_components(canales, canal_kam_items, canal_negocio_items):
    """Componentes del P&L detallado desde el RAW (ingresos/NC) + glosas (comisiones).
    Scope = líneas Marketplace/Fidelización/Páginas Propias + canal UnionX B2B. Devuelve (raw_comp, glosas_comp)."""
    conkam = {_norm(c): c for c in canales}          # norm -> nombre display
    canal_kam = dict(canal_kam_items)
    canal_neg = dict(canal_negocio_items)
    con = duckdb.connect()
    P = PARQUET.as_posix()
    # es_despacho puede no existir en el histórico deployado → usar FALSE (todo producto)
    existentes = set(con.execute(f"SELECT * FROM '{P}' LIMIT 0").df().columns)
    desp = "es_despacho" if "es_despacho" in existentes else "FALSE"
    # Scope = mismo del crossover (nivel LÍNEA del RAW): líneas de negocio + canal UnionX B2B.
    # Así ingreso y devoluciones calzan 1:1 con el archivo que analiza Gabriela.
    SCOPE_SQL = ("(tipo_negocio IN ('Marketplace','Fidelización','Páginas propias') "
                 "OR canal='UnionX B2B')")
    ing = con.execute(f"""
        SELECT mes_venta mes, canal,
               CASE WHEN {desp} THEN 'ing_envio' ELSE 'ing_prod' END tipo,
               sum(TRY_CAST(venta_neta AS DOUBLE)) venta, sum(TRY_CAST(costo_total AS DOUBLE)) costo
        FROM '{P}' WHERE anio_venta=2026 AND mes_venta BETWEEN 1 AND {_conc.MES_MAX} AND tipo_movimiento='Venta'
          AND {SCOPE_SQL}
        GROUP BY 1,2,3""").fetchdf()
    # NC = Devolución del RAW (misma fuente que la venta): venta bruta − NC = neto contable.
    nc = con.execute(f"""
        SELECT CAST(substr(CAST(fecha_documento AS VARCHAR),6,2) AS INTEGER) mes, canal,
               anio_venta oa, mes_venta om,
               COALESCE(NULLIF(TRIM(categoria_padre),''),'(sin categoría)') concepto,
               sum(TRY_CAST(venta_neta AS DOUBLE)) venta, sum(TRY_CAST(costo_total AS DOUBLE)) costo
        FROM '{P}' WHERE tipo_movimiento='Devolución'
          AND substr(CAST(fecha_documento AS VARCHAR),1,4)='2026'
          AND CAST(substr(CAST(fecha_documento AS VARCHAR),6,2) AS INTEGER) BETWEEN 1 AND {_conc.MES_MAX}
          AND {SCOPE_SQL}
        GROUP BY 1,2,3,4,5""").fetchdf()
    rows = []
    for _, r in ing.iterrows():
        d = conkam.get(_norm(r.canal)) or str(r.canal)   # display sheet, fallback al canal RAW
        rows.append({"Canal": d, "KAM": canal_kam.get(d, ""), "Negocio": canal_neg.get(d, ""), "Tipo": r.tipo, "Mes": int(r.mes),
                     "OrigenAnio": 0, "OrigenMes": 0, "Venta": float(r.venta or 0), "Costo": float(r.costo or 0)})
    for _, r in nc.iterrows():
        d = conkam.get(_norm(r.canal)) or str(r.canal)
        rows.append({"Canal": d, "KAM": canal_kam.get(d, ""), "Negocio": canal_neg.get(d, ""), "Tipo": "nc", "Mes": int(r.mes),
                     "OrigenAnio": int(r.oa or 0), "OrigenMes": int(r.om or 0), "Concepto": str(r.concepto),
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
               "Scope: Marketplace, Fidelización, Páginas Propias + canal UnionX B2B "
               "(mismo del crossover de devoluciones).")

    try:
        b = _bundle()
    except Exception as e:
        st.error(f"❌ Error cargando datos: {e}")
        return
    if b["datos"].empty:
        st.warning("Sin datos.")
        return

    vista = st.radio("Vista", ["⚖️ Comercial (KAM)", "🏭 Distribución + Corporativo (Nicolás)"],
                     horizontal=True, key="ccon_vista")
    st.markdown("---")
    if vista.startswith("🏭"):
        _render_b2b(b)
        return

    # ---- filtros (comercial) ----
    c1, c2, c3, c4 = st.columns(4)
    mes = c1.selectbox("Mes", _conc.MESES_OPT, index=0, key="ccon_mes")
    negocio = c2.selectbox("Línea de Negocio", ["TODOS"] + b.get("negocios", []), index=0, key="ccon_neg")
    canal = c3.selectbox("Canal", ["TODOS"] + b["canales"], index=0, key="ccon_canal")
    kam = c4.selectbox("KAM", ["TODOS"] + b["kams"], index=0, key="ccon_kam")

    R = calcular(b, mes, canal, kam, negocio)

    # ---- detalle RAW (Contable = RAW de ventas, única fuente). Se computa ANTES de los
    # KPIs para anclar la contable en el RAW. Si falla (quirk DuckDB Cloud), cae a la hoja.
    D = None
    try:
        canal_kam = dict(zip(b["datos"]["Canal"], b["datos"]["KAM"]))
        canal_neg = b.get("canal2negocio", {})
        raw_comp, glosas_comp = _detalle_components(tuple(b["canales"]), tuple(sorted(canal_kam.items())),
                                                    tuple(sorted(canal_neg.items())))
        D = calcular_detalle(raw_comp, glosas_comp, mes, canal, kam, negocio)
    except Exception as e:
        st.warning(f"Desglose del RAW no disponible ({type(e).__name__}) — muestro el P&L de la hoja. {str(e)[:100]}")

    contrib_cont = R["contrib_cont"]   # Contable = Sheet (el Drive de contribución)
    st.markdown("---")

    # ---- KPIs (Contribución Contable = Sheet) ----
    k1, k2, k3 = st.columns(3)
    k1.metric("Contribución Comercial", fmt_pesos(R["contrib_com"]))
    k2.metric("Contribución Contable", fmt_pesos(contrib_cont))
    k3.metric("Δ Contribución (Com − Cont)", fmt_pesos(R["contrib_com"] - contrib_cont))

    # ---- P&L Comercial vs Contable + sub-filas de desglose (RAW) ----
    pyl = R["pyl"].copy()
    pv = pyl.set_index("Línea")
    gl = lambda ln, col: float(pv.loc[ln, col])
    # (Línea, comercial, contable, tipo). Comercial y Contable = columnas del Sheet (el
    # Drive de contribución). El desglose de devoluciones bajo Venta viene del RAW (el
    # Sheet no lo abre por período de origen); D = Venta contable de la hoja.
    glosa_otro = D["glosa_otro"] if D is not None else 0.0
    com_tot_c = gl("Margen Directo", "Comercial") - gl("Contribución", "Comercial")
    com_tot_k = gl("Comisión Venta", "Contable") + gl("Comisión Envío", "Contable") + gl("Marketing", "Contable")
    pl = [("Venta", gl("Venta", "Comercial"), gl("Venta", "Contable"), "row")]
    if D is not None:  # desglose de devoluciones (RAW) bajo la Venta contable de la hoja. A − devol = D.
        cont_venta = gl("Venta", "Contable")
        devs = D["nc_per"] + D["nc_o2026"] + D["nc_o2025"]
        A = cont_venta - devs
        pl += [
            ("    A. Venta total neta (prod + envío)", None, A, "memo"),
            ("    B. (−) Devoluciones del período", None, D["nc_per"], "memo"),
            ("       (−) Devoluciones otro período 2026", None, D["nc_o2026"], "memo"),
            ("    C. (−) Devoluciones 2025", None, D["nc_o2025"], "memo"),
            ("    D. = Venta neta − devoluciones", None, cont_venta, "memo"),
        ]
    pl += [
        ("Costo de Venta", gl("Costo de Venta", "Comercial"), gl("Costo de Venta", "Contable"), "row"),
        ("= Margen Directo", gl("Margen Directo", "Comercial"), gl("Margen Directo", "Contable"), "bold"),
        ("Comisión Venta", gl("Comisión Venta", "Comercial"), gl("Comisión Venta", "Contable"), "row"),
        ("Comisión Envío", gl("Comisión Envío", "Comercial"), gl("Comisión Envío", "Contable"), "row"),
        ("Marketing", gl("Marketing", "Comercial"), gl("Marketing", "Contable"), "row"),
    ]
    if D is not None and glosa_otro:
        pl.append(("    · Glosa otro período (timing, RAW)", None, glosa_otro, "memo"))
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

    # estructura % sobre venta (margen, comisiones c/u, marketing, margen contribución).
    # Contable sobre la venta contable del RAW (ck), consistente con el P&L.
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
        st.caption("Filas en gris (·): **Ingreso producto/envío** (bruto) y **Devoluciones (NC)**, todo del "
                   "**RAW contable** (misma fuente que Vista General y los pulsos): venta bruta − NC = venta neta. "
                   "Devoluciones en la columna **Comercial** (impacto en la venta KAM), abiertas por período de "
                   "origen. 'NC otro período 2026' solo se llena al elegir un mes (en YTD todo 2026 es 'del período').")
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
        st.caption("Fuente: Devolución del **RAW contable** (misma fuente que la venta). 'Del período' = NC "
                   "de ventas del mismo período; 'Otro período 2026' se llena al elegir un mes; '2025' = NC de "
                   "ventas del año anterior. Dependiente del filtro (año/mes/trimestre/semestre).")
        # Concepto general al que corresponde la devolución (categoría)
        if D.get("nc_conceptos"):
            st.markdown("**Devoluciones por concepto (categoría)**")
            cc = [(n, v, c) for n, v, c in D["nc_conceptos"] if abs(v) > 0 or abs(c) > 0]
            cc_df = pd.DataFrame([{"Concepto": n, "Venta (neto)": fmt_pesos(v), "Costo": fmt_pesos(c),
                                   "Margen Directo": fmt_pesos(v - c)} for n, v, c in cc])
            st.dataframe(cc_df, width="stretch", hide_index=True, height=min(430, 45 + 35 * len(cc)))

    # ---- (7,9) Comisiones por período de origen (glosas del Drive Seguimiento) ----
    if D is not None:
        st.markdown("#### 💸 Comisiones por período de origen")
        com_rows = [
            ("Del período (origen 2026)", D["com_per"]),
            ("Otro período 2026", D["com_o2026"]),
            ("2025", D["com_o2025"]),
        ]
        tot_com = sum(v for _, v in com_rows)
        com_rows.append(("= Total comisiones (glosas)", tot_com))
        com_df = pd.DataFrame([{"Período de origen": n, "Comisión ($)": fmt_pesos(v)} for n, v in com_rows])
        _lc = len(com_rows) - 1
        com_sty = com_df.style.apply(
            lambda r: (["font-weight:700;background-color:#F1F5F9"] * 2 if r.name == _lc else [""] * 2), axis=1)
        c_a, c_b = st.columns([2, 3])
        with c_a:
            st.dataframe(com_sty, width="stretch", hide_index=True)
        with c_b:
            cat = D.get("com_per_cat", {})
            cat_df = pd.DataFrame([
                {"Comisión del período": "Comisión Venta", "$": fmt_pesos(cat.get("venta", 0))},
                {"Comisión del período": "Comisión Envío / Logística", "$": fmt_pesos(cat.get("envio", 0))},
                {"Comisión del período": "Marketing", "$": fmt_pesos(cat.get("mkt", 0))},
            ])
            st.dataframe(cat_df, width="stretch", hide_index=True)
        st.caption("Fuente: glosas del Drive **Seguimiento contribución** ('Detalle Glosas 2026'). Mismo criterio "
                   "que devoluciones: 'del período' = origen 2026 dentro del filtro; 'otro período 2026' y '2025' = "
                   "comisiones que caen en el período pero corresponden a otra fecha. Dependiente del filtro "
                   "(año/mes/trimestre/semestre).")

    # ---- (10) Diferencia por Margen Directo (efecto del margen contable/real) ----
    st.markdown("#### 📐 Diferencia por Margen Directo")
    mc = gl("Margen Directo", "Comercial"); mk = gl("Margen Directo", "Contable")
    vc_ = gl("Venta", "Comercial"); vk_ = gl("Venta", "Contable")
    tc = (mc / vc_ * 100) if vc_ else 0.0
    tk = (mk / vk_ * 100) if vk_ else 0.0
    efecto = vc_ * ((tk - tc) / 100)  # efecto en $ si la venta comercial rindiera al margen contable
    md_df = pd.DataFrame([
        {"Concepto": "Margen Directo Comercial", "Monto": fmt_pesos(mc), "% s/venta": f"{tc:.1f}%"},
        {"Concepto": "Margen Directo Contable (real)", "Monto": fmt_pesos(mk), "% s/venta": f"{tk:.1f}%"},
        {"Concepto": "Δ Margen Directo (Com − Cont)", "Monto": fmt_pesos(mc - mk), "% s/venta": f"{tc - tk:+.1f} pts"},
        {"Concepto": "Efecto si se tomara el margen contable (× venta comercial)", "Monto": fmt_pesos(efecto), "% s/venta": ""},
    ])
    st.dataframe(md_df, width="stretch", hide_index=True)
    st.caption("Cuánto cambia el margen directo si se usa la tasa **contable (real)** en vez de la comercial. "
               "Efecto = venta comercial × (tasa contable − tasa comercial).")

    # ---- (12) Descargas de los Drives ----
    st.markdown("### ⬇️ Descargas (Drive)")
    dl = [
        ("📄 Análisis de Resultados", SHEET_CONTRIB, "Análisis de Resultados", "Analisis_de_Resultados.xlsx"),
        ("📄 Resumen 2026 (Seguimiento)", SHEET_SEGUIMIENTO, "Resumen 2026", "Resumen_2026.xlsx"),
        ("📄 Detalle Glosas 2026", SHEET_CONTRIB, "Detalle Glosas 2026", "Detalle_Glosas_2026.xlsx"),
    ]
    cols_dl = st.columns(len(dl))
    for i, (label, sid, tab, fname) in enumerate(dl):
        with cols_dl[i]:
            try:
                st.download_button(label, data=_hoja_xlsx(sid, tab), file_name=fname,
                                   mime=MIME_XLSX, width='stretch', key=f"dl_{i}")
            except Exception as e:
                st.caption(f"⚠️ {label}: {type(e).__name__} — {str(e)[:70]}")
