"""
Vista Análisis Detallado (Contribución) — drill-down completo.

Fuente: Sheet 'Análisis de Contribución' → 'Analisis Meta vs Resultados'
Muestra: tabla filtrable Año/Negocio/Canal/KAM/Mes/Trimestre con Meta vs Real.
"""
import pandas as pd
import streamlit as st

from views.contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas,
    fmt_pesos_M, fmt_pct, color_cumplimiento,
)


def render():
    st.title("🔬 Contribución — Análisis Detallado")
    st.caption("Drill-down completo: Año / Negocio / Canal / KAM / Mes / Trimestre — Meta vs Real")

    if st.button("🔄 Refrescar", key="contrib_det_refresh"):
        st.cache_data.clear()
        st.rerun()

    try:
        df = cargar_hoja("Analisis Meta vs Resultados")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    if df.empty:
        st.warning("Hoja vacía.")
        return

    cols_num = ["Meta Venta", "Resultado Venta", "Meta Contribución", "Resultado Contribución"]
    # Las columnas de % cumplimiento pueden estar como %.x o como float
    pct_cols = [c for c in df.columns if c.strip() == "%"]
    cols_num_full = cols_num + pct_cols
    cols_num_full = [c for c in cols_num_full if c in df.columns]
    df = parsear_columnas_numericas(df, cols_num_full)

    # Filtros (si hay datos)
    cf1, cf2, cf3 = st.columns(3)
    with cf1:
        anios = sorted([a for a in df["AÑO"].dropna().unique() if a])
        anio_sel = st.multiselect("Año", anios, default=anios[-2:] if len(anios) >= 2 else anios, key="cdet_year")
    with cf2:
        negocios = sorted([n for n in df["Negocio"].dropna().unique() if n])
        neg_sel = st.multiselect("Negocio", negocios, default=negocios, key="cdet_neg")
    with cf3:
        canales = sorted([c for c in df["Canal"].dropna().unique() if c])
        canal_sel = st.multiselect("Canal", canales, default=canales, key="cdet_canal")

    cf4, cf5 = st.columns(2)
    with cf4:
        kams = sorted([k for k in df["KAM"].dropna().unique() if k])
        kam_sel = st.multiselect("KAM", kams, default=kams, key="cdet_kam")
    with cf5:
        trimestres = sorted([t for t in df["Trimestre"].dropna().unique() if t])
        trim_sel = st.multiselect("Trimestre", trimestres, default=trimestres, key="cdet_trim")

    df_f = df.copy()
    if anio_sel:
        df_f = df_f[df_f["AÑO"].isin(anio_sel)]
    if neg_sel:
        df_f = df_f[df_f["Negocio"].isin(neg_sel)]
    if canal_sel:
        df_f = df_f[df_f["Canal"].isin(canal_sel)]
    if kam_sel:
        df_f = df_f[df_f["KAM"].isin(kam_sel)]
    if trim_sel:
        df_f = df_f[df_f["Trimestre"].isin(trim_sel)]

    if df_f.empty:
        st.info("Sin filas con esos filtros.")
        return

    # KPIs agregados
    st.divider()
    venta_total = df_f["Resultado Venta"].sum() if "Resultado Venta" in df_f.columns else 0
    contrib_total = df_f["Resultado Contribución"].sum() if "Resultado Contribución" in df_f.columns else 0
    meta_venta = df_f["Meta Venta"].sum() if "Meta Venta" in df_f.columns else 0
    meta_contrib = df_f["Meta Contribución"].sum() if "Meta Contribución" in df_f.columns else 0

    cump_v = (venta_total / meta_venta) if meta_venta else None
    cump_c = (contrib_total / meta_contrib) if meta_contrib else None
    contrib_pct = (contrib_total / venta_total) if venta_total else None

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("💰 Venta Real", fmt_pesos_M(venta_total),
              delta=f"vs Meta {fmt_pct(cump_v - 1)}" if cump_v else None)
    k2.metric("💎 Contrib. Real", fmt_pesos_M(contrib_total),
              delta=f"vs Meta {fmt_pct(cump_c - 1)}" if cump_c else None)
    k3.metric(f"{color_cumplimiento(cump_v)} % Cumpl. Venta", fmt_pct(cump_v))
    k4.metric(f"{color_cumplimiento(cump_c)} % Cumpl. Contrib.", fmt_pct(cump_c))

    if contrib_pct is not None:
        st.metric("📈 Margen Contribución (Real)", fmt_pct(contrib_pct))

    st.divider()

    # Tabla
    st.markdown(f"### Detalle ({len(df_f)} filas)")
    rows = []
    for _, r in df_f.iterrows():
        v_meta = r.get("Meta Venta")
        v_real = r.get("Resultado Venta")
        c_meta = r.get("Meta Contribución")
        c_real = r.get("Resultado Contribución")
        cv = v_real / v_meta if (v_meta and v_real) else None
        cc = c_real / c_meta if (c_meta and c_real) else None

        rows.append({
            "Año": r.get("AÑO", ""),
            "Q": r.get("Trimestre", ""),
            "Mes": r.get("Mes", ""),
            "Negocio": r.get("Negocio", ""),
            "Canal": r.get("Canal", ""),
            "KAM": r.get("KAM", ""),
            "Meta Venta": fmt_pesos_M(v_meta),
            "Real Venta": fmt_pesos_M(v_real),
            "🚦 V": f"{color_cumplimiento(cv)} {fmt_pct(cv)}",
            "Meta Contrib.": fmt_pesos_M(c_meta),
            "Real Contrib.": fmt_pesos_M(c_real),
            "🚦 C": f"{color_cumplimiento(cc)} {fmt_pct(cc)}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=520)
