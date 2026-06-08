"""
vs Presupuesto — cumplimiento de Meta de Venta y Contribución.

Fuente: 'Analisis Meta vs Resultados' (drill por AÑO/Negocio/Canal/KAM/Mes/Trim).
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from views.contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas, fmt_pesos_M,
    render_contrib_filters, aplicar_filtros,
)


COLS_NUM = ['Meta Venta', 'Resultado Venta', 'Meta Contribución', 'Resultado Contribución']


def render():
    with st.sidebar:
        st.markdown("### 🎯 **vs Presupuesto**")
        st.caption("Cumplimiento de meta")
        st.markdown("---")
        if st.button("🔄 Refrescar Sheet", width='stretch', type="primary", key="cmeta_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("🎯 Contribución vs Presupuesto")
    st.caption("Cumplimiento de Meta de Venta y Contribución por dimensión")

    try:
        df = cargar_hoja("Analisis Meta vs Resultados")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    if df.empty:
        st.warning("Sin datos")
        return

    df = parsear_columnas_numericas(df, COLS_NUM)

    # Filtros al tope
    sel = render_contrib_filters(df, prefix="cmeta")
    df_f = aplicar_filtros(df, sel)
    st.caption(f"Filas filtradas: {len(df_f):,} de {len(df):,}")
    st.markdown("---")

    # KPIs consolidados
    meta_v = df_f['Meta Venta'].sum() if 'Meta Venta' in df_f.columns else 0
    real_v = df_f['Resultado Venta'].sum() if 'Resultado Venta' in df_f.columns else 0
    meta_c = df_f['Meta Contribución'].sum() if 'Meta Contribución' in df_f.columns else 0
    real_c = df_f['Resultado Contribución'].sum() if 'Resultado Contribución' in df_f.columns else 0

    pct_v = (real_v / meta_v * 100) if meta_v else 0
    pct_c = (real_c / meta_c * 100) if meta_c else 0

    color_v = '🟢' if pct_v >= 100 else ('🟡' if pct_v >= 85 else '🔴')
    color_c = '🟢' if pct_c >= 100 else ('🟡' if pct_c >= 85 else '🔴')

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Meta Venta", fmt_pesos_M(meta_v))
    c2.metric("Real Venta", fmt_pesos_M(real_v))
    c3.metric(f"{color_v} % Cumpl. Venta", f"{pct_v:.1f}%")
    c4.metric("Meta Contrib", fmt_pesos_M(meta_c))
    c5.metric("Real Contrib", fmt_pesos_M(real_c))
    c6.metric(f"{color_c} % Cumpl. Contrib", f"{pct_c:.1f}%")

    st.divider()

    # Por Trimestre
    if 'Trimestre' in df_f.columns:
        st.markdown("### Por Trimestre")
        df_t = df_f.groupby('Trimestre').agg({
            'Meta Venta': 'sum', 'Resultado Venta': 'sum',
            'Meta Contribución': 'sum', 'Resultado Contribución': 'sum',
        }).reset_index()
        df_t['% Venta'] = (df_t['Resultado Venta'] / df_t['Meta Venta'] * 100).round(1)
        df_t['% Contrib'] = (df_t['Resultado Contribución'] / df_t['Meta Contribución'] * 100).round(1)

        c1, c2 = st.columns(2)
        with c1:
            fig_v = px.bar(df_t, x='Trimestre', y=['Meta Venta', 'Resultado Venta'],
                           barmode='group', title="Meta vs Real — Venta",
                           color_discrete_map={'Meta Venta': '#94A3B8', 'Resultado Venta': '#1E40AF'})
            fig_v.update_layout(height=320, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                yaxis=dict(tickformat=',.0f'))
            st.plotly_chart(fig_v, width='stretch')
        with c2:
            fig_c = px.bar(df_t, x='Trimestre', y=['Meta Contribución', 'Resultado Contribución'],
                           barmode='group', title="Meta vs Real — Contribución",
                           color_discrete_map={'Meta Contribución': '#94A3B8', 'Resultado Contribución': '#10B981'})
            fig_c.update_layout(height=320, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                yaxis=dict(tickformat=',.0f'))
            st.plotly_chart(fig_c, width='stretch')

    st.divider()

    # Tabla detalle
    st.markdown("### Detalle")
    cols_show = [c for c in ['AÑO', 'Trimestre', 'Mes', 'Negocio', 'Canal', 'KAM',
                              'Meta Venta', 'Resultado Venta', 'Meta Contribución', 'Resultado Contribución']
                 if c in df_f.columns]
    df_show = df_f[cols_show].copy()
    if 'Meta Venta' in df_show.columns:
        df_show['% Cumpl V'] = (df_show['Resultado Venta'] / df_show['Meta Venta'].replace(0, 1) * 100).round(1).astype(str) + '%'
        df_show['% Cumpl C'] = (df_show['Resultado Contribución'] / df_show['Meta Contribución'].replace(0, 1) * 100).round(1).astype(str) + '%'
        for c in ['Meta Venta', 'Resultado Venta', 'Meta Contribución', 'Resultado Contribución']:
            df_show[c] = df_show[c].apply(fmt_pesos_M)
    st.dataframe(df_show, width='stretch', hide_index=True, height=500)
