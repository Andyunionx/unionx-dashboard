"""Módulo: Política de stock objetivo + Caracterización por categoría.

La categoría comercial (Diamante/Oro/Plata/Bronce/Nuevo/Pack/In_Out) define
rotación y ROI. Este módulo combina:

1. 📐 **Política**: meses de inventario objetivo/min/max por categoría (config editable)
2. 📊 **Caracterización**: cómo se mueve EMPÍRICAMENTE cada categoría hoy
   (rotación anualizada, ROI, margen %, % participación)
3. 📈 **Movimiento por SKU**: evolución temporal del comportamiento de un SKU
4. 💡 **Propuestas**: SKUs cuya rotación + ROI no calzan con su categoría actual

Fuente: data/planificacion/stock_objetivo.parquet (editable).
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from views.planning._core import (
    caracterizar_categorias,
    detectar_drift_categorias,
    metricas_por_sku,
)
from views.planning._data_helpers import (
    cargar_politicas_stock,
    cargar_ventas_historicas,
    POLITICAS_SCHEMA,
    PLAN_DIR,
)
from views.shared import cached_stock


def render():
    st.title("📐 Políticas y Caracterización de Categorías")
    st.caption(
        "Categorización por rotación + ROI. Política de meses de inventario por categoría. "
        "Monitoreo de movimiento y propuestas de reclasificación."
    )

    tab_pol, tab_car, tab_mov, tab_drift = st.tabs([
        "📐 Política", "📊 Caracterización empírica",
        "📈 Movimiento por SKU", "💡 Propuestas de reclasificación",
    ])

    with tab_pol:
        _tab_politica()
    with tab_car:
        _tab_caracterizacion()
    with tab_mov:
        _tab_movimiento_sku()
    with tab_drift:
        _tab_drift()


# ============================================================
# Tab 1: Política (config editable)
# ============================================================
def _tab_politica():
    df_pol = cargar_politicas_stock()

    if df_pol.empty:
        st.warning(
            "**Sin política cargada.** El archivo `data/planificacion/stock_objetivo.parquet` está vacío."
        )
        st.markdown("##### Categorías comerciales detectadas en ventas")
        _mostrar_categorias_detectadas()

        st.markdown("##### Sugerencia inicial (Diamante/Oro/Plata/Bronce/Nuevo/Pack/In_Out)")
        df_default = _politica_default_sugerida()
        st.dataframe(df_default, width='stretch', hide_index=True)
        if st.button("💾 Guardar política inicial sugerida", type="primary"):
            df_default.to_parquet(PLAN_DIR / 'stock_objetivo.parquet', index=False)
            cargar_politicas_stock.clear()
            st.success("Guardado. Recargar la página.")
            st.rerun()

        with st.expander("📋 Schema esperado"):
            st.code("\n".join(f"- {c}" for c in POLITICAS_SCHEMA), language="markdown")
        return

    st.success(f"✅ Política definida para {len(df_pol)} categorías")
    edited = st.data_editor(
        df_pol,
        width='stretch',
        num_rows="dynamic",
        column_config={
            'meses_cobertura_objetivo': st.column_config.NumberColumn(min_value=0, max_value=12, step=0.25),
            'meses_cobertura_minimo': st.column_config.NumberColumn(min_value=0, max_value=6, step=0.25),
            'meses_cobertura_maximo': st.column_config.NumberColumn(min_value=0.5, max_value=24, step=0.25),
            'lead_time_buffer_dias': st.column_config.NumberColumn(min_value=0, max_value=60, step=5),
        },
    )
    if not edited.equals(df_pol):
        if st.button("💾 Guardar cambios", type="primary"):
            edited.to_parquet(PLAN_DIR / 'stock_objetivo.parquet', index=False)
            cargar_politicas_stock.clear()
            st.success("Política actualizada.")
            st.rerun()


# ============================================================
# Tab 2: Caracterización empírica
# ============================================================
def _tab_caracterizacion():
    st.markdown(
        "**Cómo se mueve hoy cada categoría.** Validación empírica de la taxonomía: "
        "Diamante DEBERÍA tener mayor rotación y ROI que Oro, etc."
    )

    dias = st.slider("Ventana de análisis (días)", 30, 365, 90, step=30, key="pln_pol_car_dias")
    df_metricas = _cargar_metricas_cache(dias)

    if df_metricas.empty:
        st.warning("Sin datos suficientes. Verificar ventas y stock histórico.")
        return

    df_cat = caracterizar_categorias(df_metricas)
    if df_cat.empty:
        st.warning("Sin categorías para caracterizar.")
        return

    # KPIs globales
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SKUs analizados", f"{int(df_cat['n_skus'].sum()):,}")
    c2.metric("Venta neta periodo", f"${df_cat['venta_neta_total'].sum() / 1e6:.1f}M")
    margen_total = df_cat['margen_total'].sum()
    venta_total = df_cat['venta_neta_total'].sum()
    margen_pct_global = margen_total / venta_total * 100 if venta_total else 0
    c3.metric("Margen % global", f"{margen_pct_global:.1f}%")
    c4.metric("Capital invertido (stock)", f"${df_cat['costo_inv_total'].sum() / 1e6:.1f}M")

    st.divider()

    # Tabla comparativa
    st.markdown("#### Comparativa por categoría")
    df_show = df_cat[['categoria_comercial', 'n_skus', 'pct_skus', 'pct_venta',
                       'rotacion_anual_mediana', 'roi_periodo_mediano',
                       'margen_pct_agg', 'dias_con_venta_mediano',
                       'cv_venta_mediano', 'costo_inv_total']].copy()

    st.dataframe(
        df_show,
        width='stretch', hide_index=True,
        column_config={
            'categoria_comercial': 'Categoría',
            'n_skus': st.column_config.NumberColumn('# SKUs', format='%d'),
            'pct_skus': st.column_config.NumberColumn('% SKUs', format='%.1f%%'),
            'pct_venta': st.column_config.NumberColumn('% Venta', format='%.1f%%'),
            'rotacion_anual_mediana': st.column_config.NumberColumn('Rot. anual (mediana)', format='%.2f'),
            'roi_periodo_mediano': st.column_config.NumberColumn(f'ROI {dias}d (mediano)', format='%.2f'),
            'margen_pct_agg': st.column_config.NumberColumn('Margen % agg', format='%.1f%%'),
            'dias_con_venta_mediano': st.column_config.NumberColumn('Días con venta', format='%.0f'),
            'cv_venta_mediano': st.column_config.NumberColumn('CV (estabilidad)', format='%.2f'),
            'costo_inv_total': st.column_config.NumberColumn('Capital invertido', format='$%.0f'),
        },
    )

    # Gráficos
    st.divider()
    g1, g2 = st.columns(2)
    with g1:
        fig = px.bar(df_cat, x='categoria_comercial', y='rotacion_anual_mediana',
                     color='categoria_comercial', text='rotacion_anual_mediana',
                     labels={'rotacion_anual_mediana': 'Rotación anual (mediana)',
                             'categoria_comercial': 'Categoría'},
                     title='Rotación anual por categoría')
        fig.update_traces(texttemplate='%{text:.1f}x', textposition='outside')
        fig.update_layout(height=380, showlegend=False, margin=dict(t=40, b=40),
                          paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, width='stretch')
    with g2:
        fig = px.bar(df_cat, x='categoria_comercial', y='roi_periodo_mediano',
                     color='categoria_comercial', text='roi_periodo_mediano',
                     labels={'roi_periodo_mediano': f'ROI {dias}d (mediano)',
                             'categoria_comercial': 'Categoría'},
                     title=f'ROI {dias}d por categoría')
        fig.update_traces(texttemplate='%{text:.2f}', textposition='outside')
        fig.update_layout(height=380, showlegend=False, margin=dict(t=40, b=40),
                          paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, width='stretch')

    # Diagnóstico
    st.divider()
    st.markdown("#### Coherencia de la taxonomía")
    _diagnosticar_coherencia(df_cat)


def _diagnosticar_coherencia(df_cat: pd.DataFrame):
    """Verifica si Diamante > Oro > Plata > Bronce en rotación + ROI."""
    orden_esperado = ['Diamante', 'Oro', 'Plata', 'Bronce']
    df_ord = df_cat[df_cat['categoria_comercial'].isin(orden_esperado)].copy()
    if len(df_ord) < 2:
        st.info("No hay suficientes categorías metálicas para diagnosticar.")
        return

    df_ord['_orden'] = df_ord['categoria_comercial'].map({c: i for i, c in enumerate(orden_esperado)})
    df_ord = df_ord.sort_values('_orden')

    rot_decreciente = df_ord['rotacion_anual_mediana'].is_monotonic_decreasing
    roi_decreciente = df_ord['roi_periodo_mediano'].is_monotonic_decreasing

    if rot_decreciente and roi_decreciente:
        st.success("✅ La rotación y el ROI decrecen de Diamante → Bronce. Taxonomía coherente.")
    else:
        msgs = []
        if not rot_decreciente:
            msgs.append("rotación no decrece monótonamente Diamante→Bronce")
        if not roi_decreciente:
            msgs.append("ROI no decrece monótonamente Diamante→Bronce")
        st.warning(f"⚠️ Inconsistencia detectada: {', '.join(msgs)}. Ver tab *Propuestas de reclasificación*.")


# ============================================================
# Tab 3: Movimiento por SKU
# ============================================================
def _tab_movimiento_sku():
    st.markdown("**Evolución del comportamiento de un SKU** — venta diaria mensual + rotación.")

    df_ventas = cargar_ventas_historicas(meses=12)
    if df_ventas.empty:
        st.warning("Sin datos de ventas históricas.")
        return

    # Selector: top SKUs por venta
    top_skus = df_ventas.groupby('sku').agg(
        producto=('producto', 'first'),
        venta_total=('venta_neta', 'sum'),
        categoria=('categoria_comercial', 'first'),
    ).reset_index().sort_values('venta_total', ascending=False).head(200)

    if top_skus.empty:
        st.warning("Sin SKUs con venta en los últimos 12 meses.")
        return

    top_skus['label'] = top_skus.apply(
        lambda r: f"{r['sku']} | {str(r['producto'])[:40]} | {r['categoria']}",
        axis=1,
    )
    sku_sel = st.selectbox(
        "Seleccionar SKU (top 200 por venta últimos 12m)",
        options=top_skus['sku'].tolist(),
        format_func=lambda s: top_skus.loc[top_skus['sku'] == s, 'label'].iloc[0],
        key='pln_mov_sku',
    )

    if not sku_sel:
        return

    df_sku = df_ventas[df_ventas['sku'] == sku_sel].copy()
    df_sku['mes'] = df_sku['fecha_venta'].dt.to_period('M').dt.to_timestamp()
    g = df_sku.groupby('mes').agg(
        uds=('cantidad', 'sum'),
        venta=('venta_neta', 'sum'),
        margen=('margen_front', 'sum'),
        costo=('costo_total', 'sum'),
    ).reset_index()
    g['margen_pct'] = g.apply(
        lambda r: r['margen'] / r['venta'] * 100 if r['venta'] > 0 else 0,
        axis=1,
    )

    cat = top_skus.loc[top_skus['sku'] == sku_sel, 'categoria'].iloc[0]
    st.markdown(f"##### Categoría actual: **{cat}**")

    c1, c2 = st.columns(2)
    with c1:
        fig = px.line(g, x='mes', y='uds', markers=True,
                      labels={'uds': 'Unidades vendidas', 'mes': 'Mes'},
                      title='Volumen mensual')
        fig.update_layout(height=340, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, width='stretch')
    with c2:
        fig = px.line(g, x='mes', y='margen_pct', markers=True,
                      labels={'margen_pct': 'Margen %', 'mes': 'Mes'},
                      title='Margen % mensual')
        fig.update_layout(height=340, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, width='stretch')

    # Tendencia
    if len(g) >= 4:
        inicial = g['uds'].iloc[:2].mean()
        final = g['uds'].iloc[-2:].mean()
        var = (final / inicial - 1) * 100 if inicial > 0 else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Uds prom inicio (2m)", f"{inicial:,.0f}")
        c2.metric("Uds prom fin (2m)", f"{final:,.0f}", delta=f"{var:+.0f}%")
        c3.metric("Meses con venta", g['uds'].gt(0).sum())

        if var > 30:
            st.info("📈 SKU **acelerando** — posible candidato a promover de categoría o aumentar cobertura.")
        elif var < -30:
            st.warning("📉 SKU **desacelerando** — revisar precio/promo o considerar degradar.")


# ============================================================
# Tab 4: Drift / Propuestas de reclasificación
# ============================================================
def _tab_drift():
    st.markdown(
        "**SKUs cuya rotación + ROI no calzan con su categoría actual.** "
        "Lista para revisión manual del equipo comercial."
    )

    dias = st.slider("Ventana (días)", 30, 365, 90, step=30, key="pln_drift_dias")
    top_pct = st.slider("Umbral 'élite' (% top de rotación+ROI)", 0.10, 0.40, 0.20, step=0.05,
                         key="pln_drift_top",
                         help="Top % define qué SKUs serían 'Diamante' según rotación+ROI")

    df_metricas = _cargar_metricas_cache(dias)
    if df_metricas.empty:
        st.warning("Sin datos.")
        return

    df_drift = detectar_drift_categorias(df_metricas, top_pct=top_pct)
    if df_drift.empty:
        st.success("✅ No hay SKUs con drift significativo respecto a su categoría.")
        return

    promover = df_drift[df_drift['motivo'].str.startswith('PROMOVER')]
    degradar = df_drift[df_drift['motivo'].str.startswith('DEGRADAR')]

    c1, c2, c3 = st.columns(3)
    c1.metric("SKUs con drift", len(df_drift))
    c2.metric("📈 Candidatos a PROMOVER", len(promover))
    c3.metric("📉 Candidatos a DEGRADAR", len(degradar))

    st.divider()
    df_drift = df_drift.sort_values('score', ascending=False)
    st.dataframe(
        df_drift.head(300),
        width='stretch', hide_index=True,
        column_config={
            'rotacion_anual': st.column_config.NumberColumn('Rotación anual', format='%.2f'),
            'roi_periodo': st.column_config.NumberColumn(f'ROI {dias}d', format='%.2f'),
            'margen_pct': st.column_config.NumberColumn('Margen %', format='%.1f%%'),
            'uds_vendidas': st.column_config.NumberColumn('Uds vendidas', format='%.0f'),
            'score': st.column_config.NumberColumn('Score (rot+ROI)', format='%.2f'),
        },
    )

    st.download_button(
        "⬇️ Descargar propuestas CSV",
        data=df_drift.to_csv(index=False).encode('utf-8'),
        file_name=f"propuestas_reclasificacion_{pd.Timestamp.today().strftime('%Y%m%d')}.csv",
        mime='text/csv',
    )


# ============================================================
# Helpers compartidos
# ============================================================
@st.cache_data(ttl=900, show_spinner="Calculando métricas por SKU…")
def _cargar_metricas_cache(dias: int) -> pd.DataFrame:
    df_v = cargar_ventas_historicas(meses=max(6, int(dias / 30) + 2))
    if df_v.empty:
        return pd.DataFrame()
    df_stock = _stock_actual_normalizado()
    return metricas_por_sku(df_v, df_stock, dias=dias)


def _stock_actual_normalizado() -> pd.DataFrame:
    """Devuelve stock snapshot por SKU con [sku, stock_actual_uds, capital_invertido].

    Lee de cached_stock() (data/stock/skus.parquet pre-generado por sync_stock.yml,
    con SKU en formato default_code matching ventas). Si falla, devuelve vacío.
    """
    try:
        stock = cached_stock()
        df = pd.DataFrame(stock.get('skus', []))
    except Exception as e:
        st.warning(f"No se pudo cargar stock vivo ({type(e).__name__}). Rotación y ROI quedarán en NaN.")
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()

    rename = {}
    if 'SKU' in df.columns:
        rename['SKU'] = 'sku'
    if 'Qty' in df.columns:
        rename['Qty'] = 'stock_actual_uds'
    if 'Valor' in df.columns:
        rename['Valor'] = 'capital_invertido'
    df = df.rename(columns=rename)
    cols = ['sku', 'stock_actual_uds', 'capital_invertido']
    return df[[c for c in cols if c in df.columns]]


def _mostrar_categorias_detectadas():
    df = cargar_ventas_historicas(meses=12)
    if df.empty or 'categoria_comercial' not in df.columns:
        st.info("Sin datos de ventas para detectar categorías.")
        return
    g = df.groupby('categoria_comercial').agg(
        skus=('sku', 'nunique'),
        uds=('cantidad', 'sum'),
        venta=('venta_neta', 'sum'),
    ).reset_index().sort_values('venta', ascending=False)
    st.dataframe(
        g, width='stretch', hide_index=True,
        column_config={'venta': st.column_config.NumberColumn('Venta 12m', format='$%.0f')},
    )


def _politica_default_sugerida() -> pd.DataFrame:
    df = cargar_ventas_historicas(meses=12)
    if df.empty or 'categoria_comercial' not in df.columns:
        return pd.DataFrame(columns=POLITICAS_SCHEMA)

    POLITICA_BASE = {
        'diamante':  {'objetivo': 1.5, 'minimo': 0.75, 'maximo': 3.0, 'comentario': 'Top sellers — no quebrar nunca'},
        'oro':       {'objetivo': 2.0, 'minimo': 1.0,  'maximo': 4.0, 'comentario': 'Alta rotación, recompra estable'},
        'plata':     {'objetivo': 2.5, 'minimo': 1.0,  'maximo': 4.5, 'comentario': 'Rotación media'},
        'bronce':    {'objetivo': 3.0, 'minimo': 1.5,  'maximo': 6.0, 'comentario': 'Rotación baja, lotes más grandes'},
        'nuevo':     {'objetivo': 2.0, 'minimo': 1.0,  'maximo': 4.0, 'comentario': 'Sin historia — conservador, revisar a 3 meses'},
        'pack':      {'objetivo': 2.5, 'minimo': 1.0,  'maximo': 5.0, 'comentario': 'Compuestos — depende de SKUs hijos'},
        'in/out':    {'objetivo': 0.0, 'minimo': 0.0,  'maximo': 1.0, 'comentario': 'Discontinuación — NO recomprar, candidato a liquidación'},
        'no aplica': {'objetivo': 0.0, 'minimo': 0.0,  'maximo': 2.0, 'comentario': 'Excluido del plan automático'},
    }

    categorias = df['categoria_comercial'].dropna().unique()
    defaults = []
    for cat in sorted(categorias, key=str):
        key = str(cat).strip().lower()
        if key in POLITICA_BASE:
            p = POLITICA_BASE[key]
            objetivo, minimo, maximo, comentario = p['objetivo'], p['minimo'], p['maximo'], p['comentario']
        else:
            objetivo, minimo, maximo, comentario = 2.5, 1.0, 5.0, '(no mapeada — revisar)'
        defaults.append({
            'categoria_comercial': cat,
            'meses_cobertura_objetivo': objetivo,
            'meses_cobertura_minimo': minimo,
            'meses_cobertura_maximo': maximo,
            'lead_time_buffer_dias': 15,
            'comentarios': comentario,
        })
    return pd.DataFrame(defaults)
