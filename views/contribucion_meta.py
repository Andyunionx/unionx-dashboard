"""
Vista Meta vs Resultado (Contribución).

Fuente: Sheet 'Análisis de Contribución' → hoja 'Resumen General Meta - Resultad'
Muestra: % cumplimiento Venta y Contribución por Trimestre/Mes/Negocio con semáforos.
"""
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from views.contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas,
    fmt_pesos_M, fmt_pct, color_cumplimiento,
)


def render():
    st.title("🎯 Contribución — Meta vs Resultado")
    st.caption("Cumplimiento de meta de Venta y Contribución por Trimestre/Mes/Negocio")

    if st.button("🔄 Refrescar", key="contrib_meta_refresh"):
        st.cache_data.clear()
        st.rerun()

    try:
        df = cargar_hoja("Resumen General Meta - Resultad")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    if df.empty:
        st.warning("Hoja vacía.")
        return

    cols_num = [" Meta Venta", " Resultado Venta", "% Cumplimiento Venta",
                "Meta Contribución", "Resultado Contribución", " % Cumplimiento Contribución"]
    cols_num = [c for c in cols_num if c in df.columns]
    df = parsear_columnas_numericas(df, cols_num)

    # Filtros
    c1, c2 = st.columns(2)
    with c1:
        trimestres = sorted([t for t in df["Trimestre"].dropna().unique() if t])
        trim_sel = st.multiselect("Trimestre", trimestres, default=trimestres, key="cmeta_trim")
    with c2:
        negocios = sorted([n for n in df["Negocio"].dropna().unique() if n])
        neg_sel = st.multiselect("Negocio", negocios, default=negocios, key="cmeta_neg")

    df_f = df.copy()
    if trim_sel:
        df_f = df_f[df_f["Trimestre"].isin(trim_sel) | (df_f["Trimestre"] == "")]
    if neg_sel:
        df_f = df_f[df_f["Negocio"].isin(neg_sel) | (df_f["Negocio"] == "")]

    # Tabla con semáforos
    st.divider()
    st.markdown("### Cumplimiento por línea")
    rows = []
    for _, r in df_f.iterrows():
        cump_v = r.get("% Cumplimiento Venta")
        cump_c = r.get(" % Cumplimiento Contribución")
        rows.append({
            "Trimestre": r.get("Trimestre", ""),
            "Mes": r.get("Mes", ""),
            "Negocio": r.get("Negocio", ""),
            "Meta Venta": fmt_pesos_M(r.get(" Meta Venta")),
            "Real Venta": fmt_pesos_M(r.get(" Resultado Venta")),
            "🚦 Venta": f"{color_cumplimiento(cump_v)} {fmt_pct(cump_v)}",
            "Meta Contrib.": fmt_pesos_M(r.get("Meta Contribución")),
            "Real Contrib.": fmt_pesos_M(r.get("Resultado Contribución")),
            "🚦 Contrib.": f"{color_cumplimiento(cump_c)} {fmt_pct(cump_c)}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=500)

    # Gráfico: cumplimiento por Negocio
    st.divider()
    st.markdown("### Cumplimiento promedio por Negocio")
    df_neg = df_f[df_f["Negocio"] != ""].copy()
    if not df_neg.empty:
        agg = df_neg.groupby("Negocio").agg({
            "% Cumplimiento Venta": "mean",
            " % Cumplimiento Contribución": "mean",
        }).reset_index()

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=agg["Negocio"], y=agg["% Cumplimiento Venta"] * 100,
            name="% Cumpl. Venta", marker_color="#1F4E79",
        ))
        fig.add_trace(go.Bar(
            x=agg["Negocio"], y=agg[" % Cumplimiento Contribución"] * 100,
            name="% Cumpl. Contribución", marker_color="#16A34A",
        ))
        fig.add_hline(y=100, line_dash="dash", line_color="#94A3B8",
                      annotation_text="Meta 100%", annotation_position="top right")
        fig.update_layout(
            barmode="group", height=380,
            margin=dict(l=20, r=20, t=20, b=20),
            yaxis_title="% Cumplimiento",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)
