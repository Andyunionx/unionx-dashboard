"""
Vista KAM — ranking + drill por canal, con desglose de comisiones.

Fuente: 'Análisis de Resultados' (atribucion KAM<->Canal completa).
Antes usaba 'Comparación Resultados Kam', una hoja resumida incompleta donde
varios KAM solo tenian 1 canal (ej. Trinidad solo "Abc"). 'Análisis de
Resultados' tiene todos los canales por KAM + el desglose de comisiones.
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from views.contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas, fmt_pesos_M, fmt_pesos,
    render_contrib_filters, aplicar_filtros,
)

# Columnas KAM (comercial) en 'Análisis de Resultados'
COL_VENTA = 'Venta REAL KAM'
COL_MARGEN = 'Margen Directo KAM'
COL_COM_VENTA = 'Comisión Venta KAM'
COL_COM_ENVIO = 'Comisión Envío KAM'
COL_MKT = 'Marketing KAM'
COL_CONTRIB = 'Resultado Contribución KAM'
COLS_NUM = [COL_VENTA, COL_MARGEN, COL_COM_VENTA, COL_COM_ENVIO, COL_MKT, COL_CONTRIB]


def render():
    with st.sidebar:
        st.markdown("### 👤 **Vista KAM**")
        st.caption("Ranking y drill por KAM/Canal")
        st.markdown("---")
        if st.button("🔄 Refrescar Sheet", width='stretch', type="primary", key="ckam_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("👤 Vista por KAM")
    st.caption("Ranking de KAMs + drill-down por canal, con desglose de comisiones")

    try:
        df = cargar_hoja("Análisis de Resultados")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return
    if df.empty:
        st.warning("Sin datos")
        return

    df = parsear_columnas_numericas(df, COLS_NUM)

    # Filtros al tope (esta hoja SI tiene AÑO/Mes/Trim/Negocio/Canal/KAM)
    sel = render_contrib_filters(df, prefix="ckam")
    df = aplicar_filtros(df, sel)
    # Solo filas con venta (evita filas-mes vacias que ensucian el ranking)
    df = df[df[COL_VENTA] != 0]
    st.caption(f"Filas: {len(df):,}")
    st.markdown("---")

    if df.empty:
        st.info("Sin filas con venta para los filtros seleccionados.")
        return

    # Aggregate por KAM
    df_kam = df.groupby('KAM').agg(
        venta=(COL_VENTA, 'sum'),
        margen=(COL_MARGEN, 'sum'),
        contrib=(COL_CONTRIB, 'sum'),
    ).reset_index().sort_values('venta', ascending=False)

    # KPIs top 3
    if len(df_kam) >= 3:
        c1, c2, c3 = st.columns(3)
        for col, (_, r) in zip((c1, c2, c3), df_kam.head(3).iterrows()):
            col.metric(r['KAM'], fmt_pesos(r['venta']),
                       delta=f"Contrib: {fmt_pesos(r['contrib'])}")
        st.divider()

    # Ranking por venta
    st.markdown("### Ranking por Venta")
    fig = px.bar(df_kam.head(15), x='KAM', y='venta', text='venta',
                 color='contrib', color_continuous_scale='Blues')
    fig.update_layout(height=380, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      xaxis_tickangle=-30, yaxis=dict(tickformat=',.0f', title='Venta'))
    fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside', textfont_size=9)
    st.plotly_chart(fig, width='stretch')

    st.divider()

    # Drill-down por KAM con desglose de comisiones
    st.markdown("### Drill-down por KAM — canales y comisiones")
    kam_sel = st.selectbox("Elegir KAM", sorted(df['KAM'].dropna().unique().tolist()), key="ckam_drill")
    df_drill = df[df['KAM'] == kam_sel].groupby('Canal').agg(
        Venta=(COL_VENTA, 'sum'),
        **{'Margen Directo': (COL_MARGEN, 'sum'),
           'Comisión Venta': (COL_COM_VENTA, 'sum'),
           'Comisión Envío': (COL_COM_ENVIO, 'sum'),
           'Marketing': (COL_MKT, 'sum'),
           'Contribución': (COL_CONTRIB, 'sum')}
    ).reset_index().sort_values('Venta', ascending=False)

    # Fila total
    if len(df_drill):
        tot = {'Canal': 'TOTAL'}
        for c in ['Venta', 'Margen Directo', 'Comisión Venta', 'Comisión Envío', 'Marketing', 'Contribución']:
            tot[c] = df_drill[c].sum()
        df_drill = pd.concat([df_drill, pd.DataFrame([tot])], ignore_index=True)

    # st.dataframe con NUMEROS reales + column_config -> el descargable trae
    # el monto completo, no el string aproximado (pedido P4 Trinidad).
    money = st.column_config.NumberColumn(format="$%d")
    st.dataframe(
        df_drill, width='stretch', hide_index=True, height=420,
        column_config={c: money for c in ['Venta', 'Margen Directo', 'Comisión Venta',
                                           'Comisión Envío', 'Marketing', 'Contribución']},
    )
    st.caption("💡 El botón de descarga (esquina sup. der. de la tabla) exporta los montos completos en CSV.")
