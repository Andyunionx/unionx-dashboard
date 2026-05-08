"""Cruce: Top 30 SKUs por venta + estado de stock."""
import pandas as pd
import streamlit as st

from views.shared import cached_stock, kpi_card, COLOR_VENTA, COLOR_MARGEN, COLOR_NEGATIVO, COLOR_NEUTRO


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
        st.markdown("### 🔥 **Bestsellers + Stock**")
        st.caption("Top SKUs por venta cruzados con su stock actual")
        st.markdown("---")
        if st.button("🔄 Refrescar Odoo", use_container_width=True, type="primary", key="bs_refresh"):
            cached_stock.clear()
            st.rerun()

    st.title("🔥 Bestsellers + Stock")
    st.caption("Top SKUs por venta cruzados con stock actual y estado de cobertura")

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

    horizonte = st.radio("Horizonte de venta:", ["30 días", "90 días"], horizontal=True, key="bs_horiz")
    col_venta = 'Vta 30d $' if horizonte == "30 días" else 'Vta 90d $'
    col_qty = 'Vta 30d Qty' if horizonte == "30 días" else 'Vta 90d Qty'

    df_top = df_sku[df_sku[col_venta] > 0].sort_values(col_venta, ascending=False).head(30).copy()

    cols = st.columns(4)
    cols[0].markdown(kpi_card("SKUs en Top", str(len(df_top)), f"Top 30 por venta {horizonte}", COLOR_VENTA), unsafe_allow_html=True)
    cols[1].markdown(kpi_card(f"Venta total {horizonte}", f"${df_top[col_venta].sum()/1e6:,.1f}M", "", COLOR_MARGEN), unsafe_allow_html=True)
    cols[2].markdown(kpi_card("Stock Unidades", f"{df_top['Qty'].sum():,.0f}", "", COLOR_VENTA), unsafe_allow_html=True)
    cols[3].markdown(kpi_card("Stock Valor", f"${df_top['Valor'].sum()/1e6:,.1f}M", "", COLOR_MARGEN), unsafe_allow_html=True)

    st.divider()

    n_quiebre = (df_top['Semaforo'].str.contains('QUIEBRE|CRITICO', na=False)).sum()
    n_bajo = (df_top['Semaforo'].str.contains('BAJO', na=False)).sum()

    if n_quiebre > 0:
        st.error(f"⚠️ {n_quiebre} de los top 30 bestsellers están en **CRÍTICO/QUIEBRE** — riesgo alto de venta perdida")
    if n_bajo > 0:
        st.warning(f"⚠️ {n_bajo} bestsellers con stock BAJO (30-89 días) — programar reposición")
    if n_quiebre == 0 and n_bajo == 0:
        st.success("✅ Todos los bestsellers tienen stock saludable")

    st.divider()

    cols = [c for c in ['SKU', 'Producto', 'Categoria', 'Marca', col_qty, col_venta,
                         'Qty', 'Valor', 'Dias Stock', 'Rot 30d Uds', 'Semaforo'] if c in df_top.columns]
    st.dataframe(
        df_top[cols].style.map(_color_sem, subset=['Semaforo']).format({
            col_qty: '{:,.0f}', col_venta: '${:,.0f}',
            'Qty': '{:,.0f}', 'Valor': '${:,.0f}',
            'Dias Stock': '{:,.0f}', 'Rot 30d Uds': '{:.2f}x',
        }),
        height=550, use_container_width=True, hide_index=True,
    )
