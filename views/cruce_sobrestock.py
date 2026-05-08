"""Cruce: Sobrestock con baja venta (capital inmovilizado)."""
import pandas as pd
import plotly.express as px
import streamlit as st

from views._shared import cached_stock


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
        st.markdown("### 💰 **Sobrestock**")
        st.caption("Capital inmovilizado")
        st.markdown("---")
        if st.button("🔄 Refrescar Odoo", use_container_width=True, type="primary", key="ss_refresh"):
            cached_stock.clear()
            st.rerun()

    st.title("💰 Sobrestock con Baja o Cero Venta")
    st.caption("Capital inmovilizado. **Acción: liquidación, promo, devolución.**")

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

    df_so = df_sku[df_sku['Semaforo'].str.contains('SOBRESTOCK|SIN VENTA', na=False)].copy()

    if df_so.empty:
        st.success("✅ No hay SKUs con sobrestock")
        return

    n_total = len(df_so)
    n_sin_venta = (df_so['Semaforo'].str.contains('SIN VENTA', na=False)).sum()
    valor_total = df_so['Valor'].sum()
    valor_sin_venta = df_so[df_so['Semaforo'].str.contains('SIN VENTA', na=False)]['Valor'].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SKUs sobrestock/sin venta", n_total)
    c2.metric("De los cuales sin venta 30d", n_sin_venta)
    c3.metric("Capital inmovilizado", f"${valor_total/1e6:,.1f}M")
    c4.metric("Inmovilizado sin venta", f"${valor_sin_venta/1e6:,.1f}M")

    st.divider()

    st.markdown("#### Capital inmovilizado por Categoría")
    df_cat = df_so.groupby('Categoria').agg({'Valor': 'sum', 'Qty': 'sum', 'SKU': 'count'}).reset_index()
    df_cat = df_cat.rename(columns={'SKU': 'N° SKUs'}).sort_values('Valor', ascending=False).head(15)
    fig_cat = px.bar(df_cat, x='Categoria', y='Valor', text='Valor', labels={'Valor': 'Capital inmovilizado $'})
    fig_cat.update_layout(xaxis_tickangle=-45, height=400, margin=dict(t=20, b=80),
                          paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    fig_cat.update_traces(texttemplate='$%{text:,.0f}', textposition='outside', textfont_size=9, marker_color='#3B82F6')
    st.plotly_chart(fig_cat, use_container_width=True)

    st.markdown("#### Capital inmovilizado por Marca")
    df_marca = df_so.groupby('Marca').agg({'Valor': 'sum', 'Qty': 'sum', 'SKU': 'count'}).reset_index()
    df_marca = df_marca.rename(columns={'SKU': 'N° SKUs'}).sort_values('Valor', ascending=False).head(15)
    st.dataframe(df_marca.style.format({'Valor': '${:,.0f}', 'Qty': '{:,.0f}'}),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Detalle de SKUs (ordenados por valor inmovilizado)")
    df_so = df_so.sort_values('Valor', ascending=False)
    cols = [c for c in ['SKU', 'Producto', 'Categoria', 'Marca', 'Qty', 'Valor',
                         'Vta 30d Qty', 'Vta 90d Qty', 'Dias Stock', 'Semaforo'] if c in df_so.columns]
    st.dataframe(
        df_so[cols].style.map(_color_sem, subset=['Semaforo']).format({
            'Qty': '{:,.0f}', 'Valor': '${:,.0f}',
            'Vta 30d Qty': '{:,.0f}', 'Vta 90d Qty': '{:,.0f}',
            'Dias Stock': '{:,.0f}',
        }),
        height=500, use_container_width=True, hide_index=True,
    )
