"""Módulo: Triada Stock + Llegadas + Demanda.

La vista núcleo de la app. Para cada SKU muestra:
- Stock actual (Odoo)
- Llegadas en tránsito (Drive Martín, COMEX)
- Demanda esperada (forecast SKU anchored)
- Posición proyectada al horizonte (stock + llegadas - demanda)
- Cobertura en días
- Semaforización por urgencia
"""
import pandas as pd
import streamlit as st

from views.planning._core import construir_triada
from views.planning._data_helpers import (
    cargar_forecast_sku,
    cargar_transito,
)
from views.shared import cached_stock


URGENCIA_COLOR = {
    'CRITICO': '🔴',
    'URGENTE': '🟠',
    'NORMAL': '🟡',
    'HOLGADO': '🟢',
    'SIN_DEMANDA': '⚪',
}


def render():
    st.title("🎯 Triada Stock + Llegadas + Demanda")
    st.caption("Por SKU: stock hoy + tránsito + forecast → posición proyectada y cobertura.")

    with st.sidebar:
        st.markdown("### ⚙️ Parámetros")
        horizonte = st.slider("Horizonte (días)", 30, 180, 60, step=15, key="plan_triada_horiz")
        if st.button("🔄 Refrescar fuentes", width='stretch', key="plan_triada_refresh"):
            cargar_forecast_sku.clear()
            cargar_transito.clear()
            cached_stock.clear()
            st.rerun()

    # ---- Cargar fuentes
    df_forecast = cargar_forecast_sku()
    df_transito = cargar_transito()

    try:
        stock = cached_stock()
        df_stock = pd.DataFrame(stock.get('skus', []))
    except Exception as e:
        st.error(f"Error cargando stock: {e}")
        df_stock = pd.DataFrame()

    # Normalizar columna stock_actual_uds
    if not df_stock.empty:
        col_qty = next((c for c in ('Qty', 'stock_actual_uds', 'stock_uds', 'cantidad') if c in df_stock.columns), None)
        if col_qty:
            df_stock = df_stock.rename(columns={col_qty: 'stock_actual_uds'})
        else:
            df_stock['stock_actual_uds'] = 0
        # Mantener columnas útiles
        keep = ['sku', 'stock_actual_uds']
        for c in ('Producto', 'producto', 'Categoria_Comercial', 'categoria_comercial'):
            if c in df_stock.columns:
                df_stock = df_stock.rename(columns={c: c.lower().replace('categoria_comercial', 'categoria_comercial').replace('producto', 'producto')})
                keep.append(c.lower())
        df_stock = df_stock[[c for c in df_stock.columns if c in keep + ['producto', 'categoria_comercial']]]
        df_stock = df_stock.loc[:, ~df_stock.columns.duplicated()]

    # ---- Status fuentes
    c1, c2, c3 = st.columns(3)
    c1.metric("SKUs con stock", len(df_stock) if not df_stock.empty else 0)
    c2.metric("SKUs en tránsito", df_transito['sku'].nunique() if not df_transito.empty else 0)
    c3.metric("SKUs con forecast", df_forecast['sku'].nunique() if not df_forecast.empty else 0)

    if df_stock.empty and df_forecast.empty and df_transito.empty:
        st.warning("Todas las fuentes están vacías. Ejecutar los extractores correspondientes.")
        return

    # ---- Construir triada
    df_triada = construir_triada(df_stock, df_transito, df_forecast, horizonte_dias=horizonte)

    if df_triada.empty:
        st.info("Sin datos para mostrar.")
        return

    # ---- KPIs top
    st.divider()
    df_con_demanda = df_triada[df_triada['demanda'] > 0]
    skus_quiebre = df_con_demanda[(df_con_demanda['cobertura_dias'].notna()) & (df_con_demanda['cobertura_dias'] < 30)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SKUs totales", len(df_triada))
    c2.metric("Con demanda forecast", len(df_con_demanda))
    c3.metric("Cobertura < 30d", len(skus_quiebre), delta=f"{len(skus_quiebre)/max(len(df_con_demanda),1)*100:.0f}%")
    c4.metric("Posición proyectada < 0", int((df_triada['posicion_proyectada'] < 0).sum()))

    # ---- Filtros
    st.divider()
    f1, f2 = st.columns(2)
    with f1:
        urgencias = sorted(df_triada['categoria_comercial'].dropna().unique()) if 'categoria_comercial' in df_triada.columns else []
        cats_sel = st.multiselect("Categoría comercial", options=urgencias, default=urgencias[:5] if urgencias else [])
    with f2:
        solo_riesgo = st.checkbox("Solo SKUs con cobertura < 60 días", value=True)

    df_view = df_triada.copy()
    if cats_sel and 'categoria_comercial' in df_view.columns:
        df_view = df_view[df_view['categoria_comercial'].isin(cats_sel)]
    if solo_riesgo:
        df_view = df_view[(df_view['cobertura_dias'].isna()) | (df_view['cobertura_dias'] < 60)]

    df_view = df_view.sort_values('cobertura_dias', ascending=True, na_position='last')

    # ---- Tabla
    st.markdown(f"#### {len(df_view)} SKUs (horizonte {horizonte} días)")
    cols_show = [c for c in [
        'sku', 'producto', 'categoria_comercial',
        'stock_actual', 'llegadas', 'demanda', 'posicion_proyectada',
        'cobertura_dias', 'pis',
    ] if c in df_view.columns]

    st.dataframe(
        df_view[cols_show].head(500),
        width='stretch', hide_index=True,
        column_config={
            'stock_actual': st.column_config.NumberColumn('Stock hoy', format='%.0f'),
            'llegadas': st.column_config.NumberColumn(f'Llegadas {horizonte}d', format='%.0f'),
            'demanda': st.column_config.NumberColumn(f'Demanda {horizonte}d', format='%.0f'),
            'posicion_proyectada': st.column_config.NumberColumn('Posición', format='%.0f'),
            'cobertura_dias': st.column_config.NumberColumn('Cobertura (d)', format='%.0f'),
        },
    )
    if len(df_view) > 500:
        st.caption(f"Mostrando primeras 500 de {len(df_view)} filas.")
