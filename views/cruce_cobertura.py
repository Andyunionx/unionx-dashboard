"""Cruce: Cobertura de stock por canal de venta."""
import pandas as pd
import plotly.express as px
import streamlit as st

from views._shared import cached_stock, cached_ventas_canal_30d


SEM_DISPLAY = {
    'QUIEBRE': '🔴 QUIEBRE', 'CRITICO': '🔴 CRITICO', 'BAJO': '🟡 BAJO',
    'OPTIMO': '🟢 OPTIMO', 'SOBRESTOCK': '🔵 SOBRESTOCK', 'SIN VENTA': '⚪ SIN VENTA',
}


def _color_sem(val):
    s = str(val)
    if "QUIEBRE" in s or "CRITICO" in s:
        return "background-color:#FEE2E2; color:#991B1B; font-weight:600"
    if "BAJO" in s:
        return "background-color:#FEF3C7; color:#92400E; font-weight:600"
    if "OPTIMO" in s:
        return "background-color:#D1FAE5; color:#065F46; font-weight:600"
    if "SOBRESTOCK" in s:
        return "background-color:#DBEAFE; color:#1E40AF; font-weight:600"
    return "color:#94A3B8"


def render():
    with st.sidebar:
        st.markdown("### 📊 **Cobertura por Canal**")
        st.caption("Stock soportando ventas por canal")
        st.markdown("---")
        if st.button("🔄 Refrescar todo", use_container_width=True, type="primary", key="cob_refresh"):
            cached_stock.clear()
            cached_ventas_canal_30d.clear()
            st.rerun()

    st.title("📊 Cobertura de Stock por Canal")
    st.caption("Cuánto stock soporta la venta de cada canal en próximos 30 días")

    try:
        stock = cached_stock()
    except Exception as e:
        st.error(f"❌ Error stock: {e}")
        return

    df_sku = pd.DataFrame(stock['skus'])
    df_sku['Semaforo'] = df_sku['Semaforo'].map(SEM_DISPLAY).fillna(df_sku['Semaforo'])

    df_v_canal = cached_ventas_canal_30d()

    if df_v_canal.empty:
        st.warning("Sin ventas en últimos 30 días o error consultando Turso")
        return

    st.markdown("#### Top 15 canales por venta últimos 30 días")
    df_canal_total = df_v_canal.groupby('Canal').agg({
        'Cantidad': 'sum', 'Venta': 'sum', 'SKU': 'nunique',
    }).reset_index().rename(columns={'SKU': 'SKUs distintos'})
    df_canal_total = df_canal_total.sort_values('Venta', ascending=False).head(15)

    fig_can = px.bar(df_canal_total, x='Canal', y='Venta', text='Venta',
                     labels={'Venta': 'Venta últimos 30d'},
                     color='Venta', color_continuous_scale='Blues')
    fig_can.update_layout(xaxis_tickangle=-45, height=400, margin=dict(t=20, b=100),
                          paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                          showlegend=False)
    fig_can.update_traces(texttemplate='$%{text:,.0f}', textposition='outside', textfont_size=9)
    st.plotly_chart(fig_can, use_container_width=True)

    st.divider()

    canal_sel = st.selectbox(
        "Ver detalle de un canal específico:",
        options=['Todos'] + df_canal_total['Canal'].tolist(),
        key='cruce_canal_sel',
    )

    df_v_filt = df_v_canal[df_v_canal['Canal'] == canal_sel].copy() if canal_sel != 'Todos' else df_v_canal.copy()

    df_join = df_v_filt.merge(
        df_sku[['SKU', 'Producto', 'Marca', 'Qty', 'Valor', 'Vta 30d Qty', 'Dias Stock', 'Semaforo']],
        on='SKU', how='left',
    )

    df_join['% Venta este canal'] = (df_join['Cantidad'] / df_join['Vta 30d Qty'].replace(0, 1) * 100).round(1)
    df_join['Cobertura este canal (días)'] = (df_join['Qty'] / (df_join['Cantidad'] / 30).replace(0, 1)).round(0)

    venta_canal = df_v_filt['Venta'].sum()
    skus_canal = df_v_filt['SKU'].nunique()
    stock_total = df_join['Qty'].sum() if 'Qty' in df_join.columns else 0
    valor_total = df_join['Valor'].sum() if 'Valor' in df_join.columns else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Venta 30d", f"${venta_canal/1e6:,.1f}M")
    c2.metric("SKUs vendidos", skus_canal)
    c3.metric("Stock total (todos)", f"{stock_total:,.0f}")
    c4.metric("Valor stock", f"${valor_total/1e6:,.1f}M")

    st.divider()

    cols = [c for c in ['SKU', 'Producto', 'Marca', 'Canal', 'Cantidad', 'Venta', '% Venta este canal',
                         'Qty', 'Vta 30d Qty', 'Dias Stock', 'Cobertura este canal (días)', 'Semaforo'] if c in df_join.columns]
    df_show = df_join[cols].sort_values('Venta', ascending=False)
    st.dataframe(
        df_show.style.map(_color_sem, subset=['Semaforo']).format({
            'Cantidad': '{:,.0f}', 'Venta': '${:,.0f}', '% Venta este canal': '{:.1f}%',
            'Qty': '{:,.0f}', 'Vta 30d Qty': '{:,.0f}',
            'Dias Stock': '{:,.0f}', 'Cobertura este canal (días)': '{:,.0f}',
        }),
        height=500, use_container_width=True, hide_index=True,
    )
