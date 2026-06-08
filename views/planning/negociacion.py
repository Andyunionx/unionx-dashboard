"""Módulo: Análisis histórico para negociaciones.

Información que potencia al equipo de productos/compras a la hora de
negociar con proveedores:

- Volumen histórico por SKU y por proveedor (uds y CLP)
- Evolución del costo unitario en el tiempo (para detectar inflación/devaluación)
- Compra cruzada: qué SKUs se compran al mismo proveedor (apalancamiento)
- Concentración: dependencia % por proveedor
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from views.planning._data_helpers import cargar_ventas_historicas


def render():
    st.title("🤝 Análisis para Negociación")
    st.caption("Volumen histórico, evolución de costos, compra cruzada — input para negociar mejor.")

    meses = st.slider("Ventana de análisis (meses)", 6, 36, 18, step=3, key="plan_neg_meses")
    df = cargar_ventas_historicas(meses=meses)

    if df.empty:
        st.warning("Sin datos de ventas históricas para analizar.")
        return

    if 'proveedor' not in df.columns:
        st.error("Columna 'proveedor' ausente en ventas históricas.")
        return

    df = df[df['proveedor'].notna() & (df['proveedor'].astype(str) != '')]

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Volumen por proveedor",
        "📈 Evolución costo unitario",
        "🔗 Compra cruzada",
        "🎯 Concentración",
    ])

    with tab1:
        _tab_volumen(df, meses)
    with tab2:
        _tab_evolucion_costo(df)
    with tab3:
        _tab_compra_cruzada(df)
    with tab4:
        _tab_concentracion(df)


def _tab_volumen(df: pd.DataFrame, meses: int):
    st.markdown(f"##### Top proveedores por volumen ({meses} meses)")
    g = df.groupby('proveedor').agg(
        skus=('sku', 'nunique'),
        uds=('cantidad', 'sum'),
        costo_total=('costo_total', 'sum'),
        venta_neta=('venta_neta', 'sum'),
    ).reset_index()
    g['margen_directo'] = g['venta_neta'] - g['costo_total']
    g = g.sort_values('costo_total', ascending=False).head(30)

    fig = px.bar(g.head(15), x='proveedor', y='costo_total', text='costo_total',
                 color='margen_directo', color_continuous_scale='RdYlGn',
                 labels={'costo_total': 'Compra acumulada (costo)', 'proveedor': 'Proveedor'})
    fig.update_layout(xaxis_tickangle=-45, height=420, margin=dict(t=20, b=120),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside', textfont_size=9)
    st.plotly_chart(fig, width='stretch')

    st.dataframe(
        g, width='stretch', hide_index=True,
        column_config={
            'costo_total': st.column_config.NumberColumn('Compra (costo)', format='$%.0f'),
            'venta_neta': st.column_config.NumberColumn('Venta neta', format='$%.0f'),
            'margen_directo': st.column_config.NumberColumn('Margen directo', format='$%.0f'),
        },
    )


def _tab_evolucion_costo(df: pd.DataFrame):
    st.markdown("##### Evolución del costo unitario por SKU")
    st.caption("Seleccionar SKU para ver si el costo subió en el tiempo.")

    if 'costo_unitario' not in df.columns:
        st.info("Columna 'costo_unitario' no disponible.")
        return

    # Top SKUs por volumen para que el selector tenga buenas defaults
    top_skus = df.groupby('sku')['cantidad'].sum().nlargest(50).index.tolist()
    sku_sel = st.selectbox("SKU", options=top_skus, key="plan_neg_sku_evol")

    if not sku_sel:
        return

    df_sku = df[df['sku'] == sku_sel].copy()
    df_sku['mes'] = df_sku['fecha_venta'].dt.to_period('M').dt.to_timestamp()
    g = df_sku.groupby('mes').agg(
        costo_prom=('costo_unitario', 'mean'),
        uds=('cantidad', 'sum'),
    ).reset_index()

    fig = px.line(g, x='mes', y='costo_prom', markers=True,
                  labels={'costo_prom': 'Costo unitario promedio CLP', 'mes': 'Mes'})
    fig.update_layout(height=360, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, width='stretch')

    if len(g) >= 2:
        inicial = g['costo_prom'].iloc[0]
        final = g['costo_prom'].iloc[-1]
        var = (final / inicial - 1) * 100 if inicial > 0 else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Costo inicial", f"${inicial:,.0f}")
        c2.metric("Costo actual", f"${final:,.0f}", delta=f"{var:+.1f}%")
        c3.metric("Unidades totales", f"{int(g['uds'].sum()):,}")


def _tab_compra_cruzada(df: pd.DataFrame):
    st.markdown("##### Compra cruzada por proveedor")
    st.caption("Cuántos SKUs distintos compramos al mismo proveedor (potencial palanca).")

    g = df.groupby('proveedor').agg(
        skus=('sku', 'nunique'),
        familias=('categoria_comercial', 'nunique') if 'categoria_comercial' in df.columns else ('sku', 'nunique'),
        uds=('cantidad', 'sum'),
        costo=('costo_total', 'sum'),
    ).reset_index().sort_values('costo', ascending=False).head(40)

    st.dataframe(
        g, width='stretch', hide_index=True,
        column_config={
            'costo': st.column_config.NumberColumn('Compra acumulada', format='$%.0f'),
        },
    )


def _tab_concentracion(df: pd.DataFrame):
    st.markdown("##### Concentración de compras")
    st.caption("Qué % del costo total depende de los top proveedores.")

    g = df.groupby('proveedor')['costo_total'].sum().sort_values(ascending=False).reset_index()
    total = g['costo_total'].sum()
    if total == 0:
        st.info("Sin costos para analizar.")
        return
    g['pct'] = g['costo_total'] / total * 100
    g['pct_acum'] = g['pct'].cumsum()

    fig = px.bar(g.head(20), x='proveedor', y='pct',
                 labels={'pct': '% del costo total', 'proveedor': 'Proveedor'})
    fig.update_layout(xaxis_tickangle=-45, height=400, paper_bgcolor='rgba(0,0,0,0)',
                      plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, width='stretch')

    n_para_80 = (g['pct_acum'] <= 80).sum() + 1
    st.info(f"📊 **{n_para_80} proveedores concentran el 80% de las compras** (de un total de {len(g)}).")
