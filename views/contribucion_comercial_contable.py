"""
Comercial vs Contable — comparación lado a lado de las dos visiones.

Fuente: 'Análisis de Resultados' (tiene ambas columnas KAM y Contable).
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views.contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas, fmt_pesos_M,
    render_contrib_filters, aplicar_filtros,
)


COLS_NUM = [
    'Venta REAL KAM', 'Costo Venta KAM', 'Margen Directo KAM', 'Total Comisiones KAM', 'Resultado Contribución KAM',
    'Venta Real Contable', 'Costo Venta Contable', 'Margen Front Contable', 'Resultado Comisiones Contable', 'Total Contribución Contable',
]


def render():
    with st.sidebar:
        st.markdown("### ⚖️ **Comercial vs Contable**")
        st.caption("Visión KAM vs Visión Contable")
        st.markdown("---")
        if st.button("🔄 Refrescar Sheet", width='stretch', type="primary", key="ccc_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("⚖️ Comercial vs Contable")
    st.caption("Comparación lateral entre la visión Comercial (KAM) y la visión Contable")

    try:
        df = cargar_hoja("Análisis de Resultados")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    if df.empty:
        st.warning("Sin datos")
        return

    df = parsear_columnas_numericas(df, COLS_NUM)

    # Filtros al tope
    sel = render_contrib_filters(df, prefix="ccc")
    df_f = aplicar_filtros(df, sel)
    st.caption(f"Filas filtradas: {len(df_f):,} de {len(df):,}")
    st.markdown("---")

    # Resumen comparativo
    metricas = [
        ('Venta', 'Venta REAL KAM', 'Venta Real Contable'),
        ('Costo', 'Costo Venta KAM', 'Costo Venta Contable'),
        ('Margen', 'Margen Directo KAM', 'Margen Front Contable'),
        ('Comisiones', 'Total Comisiones KAM', 'Resultado Comisiones Contable'),
        ('Contribución', 'Resultado Contribución KAM', 'Total Contribución Contable'),
    ]

    rows = []
    for label, col_kam, col_cont in metricas:
        v_kam = df_f[col_kam].sum() if col_kam in df_f.columns else 0
        v_cont = df_f[col_cont].sum() if col_cont in df_f.columns else 0
        delta = v_kam - v_cont
        delta_pct = (delta / v_cont * 100) if v_cont else 0
        rows.append({
            'Métrica': label,
            'KAM (Comercial)': v_kam,
            'Contable': v_cont,
            'Δ KAM-Contable': delta,
            '% Diff': f"{delta_pct:+.1f}%",
        })

    df_comp = pd.DataFrame(rows)

    # Tabla comparativa
    st.markdown("### Comparación KAM vs Contable")
    df_show = df_comp.copy()
    for c in ['KAM (Comercial)', 'Contable', 'Δ KAM-Contable']:
        df_show[c] = df_show[c].apply(fmt_pesos_M)

    st.dataframe(df_show, width='stretch', hide_index=True)

    # Gráfico comparativo
    st.markdown("### Visualización")
    fig = go.Figure()
    fig.add_trace(go.Bar(name='KAM (Comercial)', x=df_comp['Métrica'], y=df_comp['KAM (Comercial)'], marker_color='#1E40AF'))
    fig.add_trace(go.Bar(name='Contable', x=df_comp['Métrica'], y=df_comp['Contable'], marker_color='#94A3B8'))
    fig.update_layout(
        barmode='group', height=380,
        yaxis=dict(tickformat=',.0f'),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    st.plotly_chart(fig, width='stretch')

    # Detalle por canal
    st.divider()
    st.markdown("### Detalle por Canal — diferencias")
    df_canal = df_f.groupby('Canal').agg({
        'Venta REAL KAM': 'sum', 'Venta Real Contable': 'sum',
        'Resultado Contribución KAM': 'sum', 'Total Contribución Contable': 'sum',
    }).reset_index()
    df_canal['Δ Venta'] = df_canal['Venta REAL KAM'] - df_canal['Venta Real Contable']
    df_canal['Δ Contrib'] = df_canal['Resultado Contribución KAM'] - df_canal['Total Contribución Contable']
    df_canal = df_canal.sort_values('Δ Venta', key=abs, ascending=False).head(20)

    df_canal_show = df_canal.copy()
    for c in ['Venta REAL KAM', 'Venta Real Contable', 'Δ Venta',
              'Resultado Contribución KAM', 'Total Contribución Contable', 'Δ Contrib']:
        df_canal_show[c] = df_canal_show[c].apply(fmt_pesos_M)

    st.dataframe(df_canal_show, width='stretch', hide_index=True, height=400)
