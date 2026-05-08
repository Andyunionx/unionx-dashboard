"""Cruce: Rotación de inventario 30d / 90d (cuántas veces rota el stock)."""
import pandas as pd
import plotly.express as px
import streamlit as st

from views.shared import cached_stock


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
        st.markdown("### 📈 **Rotación**")
        st.caption("Velocidad de rotación de inventario")
        st.markdown("---")
        if st.button("🔄 Refrescar", use_container_width=True, type="primary", key="rot_refresh"):
            cached_stock.clear()
            st.rerun()

    st.title("📈 Rotación de Inventario")
    st.caption(
        "**Rotación** = Venta del período / Stock actual. Si Rot = 1.0x, el inventario rota 1 vez en el período. "
        "Rot > 1 = alta rotación. Rot < 0.3 = baja rotación (stock lento)."
    )

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

    cmap_r = {
        '🔴 QUIEBRE': '#EF4444', '🔴 CRITICO': '#F87171', '🟡 BAJO': '#F59E0B',
        '🟢 OPTIMO': '#10B981', '🔵 SOBRESTOCK': '#3B82F6', '⚪ SIN VENTA': '#CBD5E1',
    }

    rot_tab1, rot_tab2 = st.tabs(["📊 Rotación 30 días", "📊 Rotación 90 días"])

    with rot_tab1:
        if 'Rot 30d Uds' in df_sku.columns and 'Vta 30d Qty' in df_sku.columns:
            df_rot30 = df_sku[df_sku['Vta 30d Qty'] > 0].sort_values('Rot 30d Uds', ascending=False).head(25).copy()
            if len(df_rot30) > 0:
                rot_prom = df_rot30['Rot 30d Uds'].mean()

                c1, c2, c3 = st.columns(3)
                c1.metric("SKUs con rotación", len(df_rot30))
                c2.metric("Rot promedio top 25", f"{rot_prom:.2f}x")
                c3.metric("Mejor rotación", f"{df_rot30['Rot 30d Uds'].max():.2f}x")

                st.divider()

                df_chart = df_rot30.head(20).copy()
                df_chart['Label'] = df_chart.apply(
                    lambda r: (str(r['SKU'])[:15] if r.get('SKU') and not str(r['SKU']).isdigit() else str(r.get('Producto', ''))[:25]),
                    axis=1,
                )
                fig_r30 = px.bar(
                    df_chart, x='Label', y='Rot 30d Uds', color='Semaforo',
                    color_discrete_map=cmap_r, text='Rot 30d Uds',
                    labels={'Label': 'Producto', 'Rot 30d Uds': 'Rotación 30d (veces)'},
                )
                fig_r30.update_layout(
                    xaxis_tickangle=-45, height=420, margin=dict(t=20, b=120),
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    xaxis=dict(showgrid=False, type='category'),
                    yaxis=dict(showgrid=True, gridcolor='#F1F5F9'),
                )
                fig_r30.update_traces(texttemplate='%{text:.1f}x', textposition='outside', textfont_size=9)
                st.plotly_chart(fig_r30, use_container_width=True)

                cols_r30 = [c for c in [
                    'SKU', 'Producto', 'Categoria', 'Marca', 'Qty', 'Vta 30d Qty', 'Rot 30d Uds',
                    'Costo Vta 30d', 'Valor', 'Rot 30d $', 'Dias Stock', 'Semaforo',
                ] if c in df_rot30.columns]
                st.dataframe(
                    df_rot30[cols_r30].style.map(_color_sem, subset=['Semaforo']).format({
                        'Qty': '{:,.0f}', 'Vta 30d Qty': '{:,.0f}', 'Rot 30d Uds': '{:.2f}x',
                        'Costo Vta 30d': '${:,.0f}', 'Valor': '${:,.0f}', 'Rot 30d $': '{:.2f}x',
                        'Dias Stock': '{:,.0f}',
                    }),
                    height=420, use_container_width=True, hide_index=True,
                )
            else:
                st.info("Sin SKUs con ventas en 30 días.")
        else:
            st.info("Datos de rotación no disponibles.")

    with rot_tab2:
        if 'Rot 90d Uds' in df_sku.columns and 'Vta 90d Qty' in df_sku.columns:
            df_rot90 = df_sku[df_sku['Vta 90d Qty'] > 0].sort_values('Rot 90d Uds', ascending=False).head(25).copy()
            if len(df_rot90) > 0:
                rot_prom = df_rot90['Rot 90d Uds'].mean()

                c1, c2, c3 = st.columns(3)
                c1.metric("SKUs con rotación", len(df_rot90))
                c2.metric("Rot promedio top 25", f"{rot_prom:.2f}x")
                c3.metric("Mejor rotación", f"{df_rot90['Rot 90d Uds'].max():.2f}x")

                st.divider()

                df_chart90 = df_rot90.head(20).copy()
                df_chart90['Label'] = df_chart90.apply(
                    lambda r: (str(r['SKU'])[:15] if r.get('SKU') and not str(r['SKU']).isdigit() else str(r.get('Producto', ''))[:25]),
                    axis=1,
                )
                fig_r90 = px.bar(
                    df_chart90, x='Label', y='Rot 90d Uds', color='Semaforo',
                    color_discrete_map=cmap_r, text='Rot 90d Uds',
                    labels={'Label': 'Producto', 'Rot 90d Uds': 'Rotación 90d (veces)'},
                )
                fig_r90.update_layout(
                    xaxis_tickangle=-45, height=420, margin=dict(t=20, b=120),
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    xaxis=dict(showgrid=False, type='category'),
                    yaxis=dict(showgrid=True, gridcolor='#F1F5F9'),
                )
                fig_r90.update_traces(texttemplate='%{text:.1f}x', textposition='outside', textfont_size=9)
                st.plotly_chart(fig_r90, use_container_width=True)

                cols_r90 = [c for c in [
                    'SKU', 'Producto', 'Categoria', 'Marca', 'Qty', 'Vta 90d Qty', 'Rot 90d Uds',
                    'Costo Vta 90d', 'Valor', 'Rot 90d $', 'Dias Stock', 'Semaforo',
                ] if c in df_rot90.columns]
                st.dataframe(
                    df_rot90[cols_r90].style.map(_color_sem, subset=['Semaforo']).format({
                        'Qty': '{:,.0f}', 'Vta 90d Qty': '{:,.0f}', 'Rot 90d Uds': '{:.2f}x',
                        'Costo Vta 90d': '${:,.0f}', 'Valor': '${:,.0f}', 'Rot 90d $': '{:.2f}x',
                        'Dias Stock': '{:,.0f}',
                    }),
                    height=420, use_container_width=True, hide_index=True,
                )
            else:
                st.info("Sin SKUs con ventas en 90 días.")
        else:
            st.info("Datos de rotación no disponibles.")
