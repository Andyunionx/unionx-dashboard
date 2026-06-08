"""
Vista KAM — ranking + drill por canal.

Fuente: 'Comparación Resultados Kam'.
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from views.contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas, fmt_pesos_M,
    render_contrib_filters, aplicar_filtros,
)


COLS_NUM = [
    'Venta KAM', 'Margen Directo KAM', ' Comisión Venta KAM', 'Comisión Envío KAM',
    ' Marketing KAM', ' Resultado Contribución KAM',
    'Resultado Venta Contable', ' Venta Real Contable', ' Margen Front Contable',
    'Comisión Venta Contable', 'Comisión Logística Contable', 'Marketing Contable',
    'Total Contribución Contable',
]


def render():
    with st.sidebar:
        st.markdown("### 👤 **Vista KAM**")
        st.caption("Ranking y drill por KAM/Canal")
        st.markdown("---")
        if st.button("🔄 Refrescar Sheet", width='stretch', type="primary", key="ckam_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("👤 Vista por KAM")
    st.caption("Ranking de KAMs + drill-down por canal")

    try:
        df = cargar_hoja("Comparación Resultados Kam")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    if df.empty:
        st.warning("Sin datos")
        return

    df = parsear_columnas_numericas(df, COLS_NUM)

    # Filtros al tope (esta hoja no tiene AÑO/Mes/Trim, solo KAM/Canal)
    sel = render_contrib_filters(df, prefix="ckam", with_anio=False, with_trim=False, with_mes=False, with_negocio=False)
    df = aplicar_filtros(df, sel)
    st.caption(f"Filas: {len(df):,}")
    st.markdown("---")

    # Aggregate por KAM
    df_kam = df.groupby('KAM').agg({
        'Venta KAM': 'sum',
        'Margen Directo KAM': 'sum',
        ' Resultado Contribución KAM': 'sum',
    }).reset_index().rename(columns={' Resultado Contribución KAM': 'Contribución KAM'})
    df_kam = df_kam.sort_values('Venta KAM', ascending=False)

    # KPIs top 3
    if len(df_kam) >= 3:
        c1, c2, c3 = st.columns(3)
        c1.metric(f"🥇 {df_kam.iloc[0]['KAM']}", fmt_pesos_M(df_kam.iloc[0]['Venta KAM']),
                  delta=f"Contrib: {fmt_pesos_M(df_kam.iloc[0]['Contribución KAM'])}")
        c2.metric(f"🥈 {df_kam.iloc[1]['KAM']}", fmt_pesos_M(df_kam.iloc[1]['Venta KAM']),
                  delta=f"Contrib: {fmt_pesos_M(df_kam.iloc[1]['Contribución KAM'])}")
        c3.metric(f"🥉 {df_kam.iloc[2]['KAM']}", fmt_pesos_M(df_kam.iloc[2]['Venta KAM']),
                  delta=f"Contrib: {fmt_pesos_M(df_kam.iloc[2]['Contribución KAM'])}")
        st.divider()

    # Bar chart Ranking
    st.markdown("### Ranking por Venta")
    fig = px.bar(df_kam.head(15), x='KAM', y='Venta KAM', text='Venta KAM',
                 color='Contribución KAM', color_continuous_scale='Blues')
    fig.update_layout(height=380, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      xaxis_tickangle=-30, yaxis=dict(tickformat=',.0f'))
    fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside', textfont_size=9)
    st.plotly_chart(fig, width='stretch')

    st.divider()

    # Drill-down por KAM
    st.markdown("### Drill-down por KAM")
    kam_sel = st.selectbox("Elegir KAM", sorted(df['KAM'].dropna().unique().tolist()), key="ckam_drill")
    df_drill = df[df['KAM'] == kam_sel]

    cols_show = [c for c in [
        'Canal', 'Venta KAM', 'Margen Directo KAM', ' Comisión Venta KAM',
        'Comisión Envío KAM', ' Marketing KAM', ' Resultado Contribución KAM',
    ] if c in df_drill.columns]
    df_show = df_drill[cols_show].copy()
    for c in cols_show:
        if c != 'Canal' and c in df_show.columns:
            df_show[c] = df_show[c].apply(fmt_pesos_M)
    st.dataframe(df_show, width='stretch', hide_index=True, height=400)
