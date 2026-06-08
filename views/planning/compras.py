"""Módulo: Propuesta de Compras.

Toma la triada + políticas + maestro proveedores y arma una lista priorizada
de qué SKU comprar, cuánto y a quién, considerando MOQ y lead times.
"""
import pandas as pd
import streamlit as st

from views.planning._core import calcular_requerimiento, construir_triada
from views.planning._data_helpers import (
    cargar_forecast_sku,
    cargar_politicas_stock,
    cargar_proveedores_master,
    cargar_transito,
)
from views.shared import cached_stock


def render():
    st.title("🛒 Propuesta de Compras")
    st.caption("SKU a comprar dado forecast, stock, tránsito y política de cobertura.")

    df_pol = cargar_politicas_stock()
    df_prov = cargar_proveedores_master()

    bloqueos = []
    if df_pol.empty:
        bloqueos.append("📐 **Política de stock objetivo** no cargada → ir a *Políticas*")
    if df_prov.empty:
        bloqueos.append("🏭 **Maestro de proveedores** no cargado → ir a *Proveedores* (el cálculo igual corre pero sin MOQ ni asignación)")

    if bloqueos:
        st.warning("Faltan inputs para una propuesta completa:")
        for b in bloqueos:
            st.markdown(f"- {b}")
        if df_pol.empty:
            st.stop()

    # Cargar fuentes
    df_forecast = cargar_forecast_sku()
    df_transito = cargar_transito()
    try:
        stock = cached_stock()
        df_stock = pd.DataFrame(stock.get('skus', []))
    except Exception as e:
        st.error(f"Error stock: {e}")
        return

    if not df_stock.empty:
        col_qty = next((c for c in ('Qty', 'stock_uds') if c in df_stock.columns), 'Qty')
        df_stock = df_stock.rename(columns={col_qty: 'stock_actual_uds'})
        cat_col = next((c for c in ('Categoria_Comercial', 'categoria_comercial') if c in df_stock.columns), None)
        if cat_col and cat_col != 'categoria_comercial':
            df_stock = df_stock.rename(columns={cat_col: 'categoria_comercial'})
        prod_col = next((c for c in ('Producto', 'producto') if c in df_stock.columns), None)
        if prod_col and prod_col != 'producto':
            df_stock = df_stock.rename(columns={prod_col: 'producto'})

    horizonte = st.slider("Horizonte (días)", 30, 180, 90, step=30, key="plan_compras_horiz")

    df_triada = construir_triada(df_stock, df_transito, df_forecast, horizonte_dias=horizonte)
    df_req = calcular_requerimiento(df_triada, df_pol)

    if df_req.empty:
        st.info("No hay requerimientos de compra calculables (faltan datos).")
        return

    df_req = df_req[df_req['requerimiento_uds'] > 0].copy()

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SKUs a comprar", len(df_req))
    c2.metric("Críticos", int((df_req['urgencia'] == 'CRITICO').sum()))
    c3.metric("Urgentes", int((df_req['urgencia'] == 'URGENTE').sum()))
    c4.metric("Unidades total", f"{int(df_req['requerimiento_uds'].sum()):,}")

    st.divider()
    urgencias_sel = st.multiselect(
        "Urgencia", options=['CRITICO', 'URGENTE', 'NORMAL', 'HOLGADO'],
        default=['CRITICO', 'URGENTE'],
    )
    df_view = df_req[df_req['urgencia'].isin(urgencias_sel)].sort_values('dias_hasta_quiebre', na_position='last')

    st.dataframe(
        df_view.head(500),
        width='stretch', hide_index=True,
        column_config={
            'stock_actual': st.column_config.NumberColumn('Stock', format='%.0f'),
            'demanda': st.column_config.NumberColumn(f'Demanda {horizonte}d', format='%.0f'),
            'posicion_proyectada': st.column_config.NumberColumn('Posición', format='%.0f'),
            'stock_objetivo_uds': st.column_config.NumberColumn('Objetivo', format='%.0f'),
            'requerimiento_uds': st.column_config.NumberColumn('A comprar', format='%.0f'),
            'dias_hasta_quiebre': st.column_config.NumberColumn('Días quiebre', format='%.0f'),
        },
    )

    if not df_prov.empty:
        st.info("✅ Con maestro de proveedores cargado, próximo paso: ajustar `requerimiento_uds` a MOQ y agrupar por proveedor.")
    else:
        st.info("ℹ️ Cuando se cargue el maestro de proveedores, se aplicará MOQ y agrupación por proveedor.")

    st.download_button(
        "⬇️ Descargar propuesta CSV",
        data=df_view.to_csv(index=False).encode('utf-8'),
        file_name=f"propuesta_compras_{pd.Timestamp.today().strftime('%Y%m%d')}.csv",
        mime='text/csv',
    )
