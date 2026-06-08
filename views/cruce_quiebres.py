"""Cruce: Quiebres con demanda activa (alerta crítica)."""
import pandas as pd
import plotly.express as px
import streamlit as st

from views.shared import cached_stock, kpi_card, COLOR_NEGATIVO, COLOR_VENTA, COLOR_COSTO


SEM_DISPLAY = {
    'QUIEBRE': '🔴 QUIEBRE', 'CRITICO': '🔴 CRITICO', 'BAJO': '🟡 BAJO',
    'OPTIMO': '🟢 OPTIMO', 'SOBRESTOCK': '🔵 SOBRESTOCK', 'SIN VENTA': '⚪ SIN VENTA',
}


def render():
    with st.sidebar:
        st.markdown("### 🚨 **Quiebres con Demanda**")
        st.caption("SKUs en quiebre que SÍ están vendiendo")
        st.markdown("---")
        if st.button("🔄 Refrescar Odoo", width='stretch', type="primary", key="qb_refresh"):
            cached_stock.clear()
            st.rerun()

    st.title("🚨 Quiebres / Críticos con Demanda Activa")
    st.caption("SKUs sin stock o con < 30 días, pero que vendieron en últimos 30 días. **Acción: priorizar reposición.**")

    try:
        stock = cached_stock()
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    df_sku = pd.DataFrame(stock['skus'])
    if df_sku.empty:
        st.warning("Sin datos")
        return

    df_sku['Semaforo'] = df_sku['Semaforo'].map(SEM_DISPLAY).fillna(df_sku['Semaforo'])

    df_q = df_sku[
        df_sku['Semaforo'].str.contains('QUIEBRE|CRITICO', na=False)
        & (df_sku['Vta 30d Qty'] > 0)
    ].copy()

    if df_q.empty:
        st.success("✅ No hay SKUs en quiebre con demanda activa")
        return

    df_q['Vta Diaria'] = df_q['Vta 30d Qty'] / 30
    df_q['Precio Prom'] = df_q['Vta 30d $'] / df_q['Vta 30d Qty'].replace(0, 1)
    df_q['Riesgo Venta 30d $'] = (df_q['Vta Diaria'] * 30 * df_q['Precio Prom']).round(0)

    cols = st.columns(3)
    cols[0].markdown(kpi_card("SKUs en Riesgo", str(len(df_q)), "Quiebre + demanda activa", COLOR_NEGATIVO), unsafe_allow_html=True)
    cols[1].markdown(kpi_card("Venta últimos 30d", f"${df_q['Vta 30d $'].sum()/1e6:,.1f}M", "Demanda real", COLOR_VENTA), unsafe_allow_html=True)
    cols[2].markdown(kpi_card("Venta en Riesgo (30d)", f"${df_q['Riesgo Venta 30d $'].sum()/1e6:,.1f}M",
                              "Si no se repone", COLOR_COSTO), unsafe_allow_html=True)

    st.divider()

    df_q = df_q.sort_values('Riesgo Venta 30d $', ascending=False)

    cols = [c for c in ['SKU', 'Producto', 'Categoria', 'Marca', 'Qty', 'Vta 30d Qty',
                         'Vta 30d $', 'Precio Prom', 'Riesgo Venta 30d $', 'Dias Stock', 'Semaforo'] if c in df_q.columns]
    st.dataframe(
        df_q[cols].style.format({
            'Qty': '{:,.0f}', 'Vta 30d Qty': '{:,.0f}',
            'Vta 30d $': '${:,.0f}', 'Precio Prom': '${:,.0f}',
            'Riesgo Venta 30d $': '${:,.0f}', 'Dias Stock': '{:,.0f}',
        }),
        height=500, width='stretch', hide_index=True,
    )

    st.markdown("#### Top 15 mayor riesgo de venta perdida")
    df_chart = df_q.head(15).copy()
    df_chart['Label'] = df_chart.apply(
        lambda r: (str(r['SKU'])[:20] if r.get('SKU') else str(r.get('Producto', ''))[:25]),
        axis=1,
    )
    fig = px.bar(df_chart, x='Label', y='Riesgo Venta 30d $',
                 color='Marca', text='Riesgo Venta 30d $',
                 labels={'Label': 'SKU', 'Riesgo Venta 30d $': 'Riesgo $'})
    fig.update_layout(xaxis_tickangle=-45, height=400, margin=dict(t=20, b=120),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside', textfont_size=9)
    st.plotly_chart(fig, width='stretch')
