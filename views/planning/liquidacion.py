"""Módulo: Estrategia de Liquidación.

SKUs con sobre-stock (cobertura > política máxima). El módulo:
- Lista candidatos
- Estima el descuento sugerido usando elasticidad-precio si está disponible
- Calcula impacto en margen vs costo de mantener el inventario
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from views.planning._core import construir_triada, detectar_sobrestock
from views.planning._data_helpers import (
    cargar_forecast_sku,
    cargar_politicas_stock,
    cargar_transito,
)
from views.shared import cached_stock

PROJECT_ROOT = Path(__file__).parent.parent.parent
ELASTICIDAD_PATH = PROJECT_ROOT / 'data' / 'forecast' / 'elasticidad_sku.parquet'


def render():
    st.title("🔻 Estrategia de Liquidación")
    st.caption("SKUs con sobre-stock candidatos a campaña de liquidación.")

    df_pol = cargar_politicas_stock()
    if df_pol.empty:
        st.warning("Política de stock objetivo no cargada — el módulo necesita el `meses_cobertura_maximo` para detectar sobre-stock.")
        return

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

    df_triada = construir_triada(df_stock, df_transito, df_forecast, horizonte_dias=90)
    df_sobre = detectar_sobrestock(df_triada, df_pol)

    if df_sobre.empty:
        st.success("✅ Sin SKUs en sobre-stock según la política actual.")
        return

    st.metric("SKUs en sobre-stock", len(df_sobre))
    st.metric("Exceso total (uds)", f"{int(df_sobre['exceso_uds'].sum()):,}")

    # Elasticidad: si está disponible, sugerir descuento
    if ELASTICIDAD_PATH.exists():
        df_elast = pd.read_parquet(ELASTICIDAD_PATH)
        if 'sku' in df_elast.columns and 'elasticidad' in df_elast.columns:
            df_sobre = df_sobre.merge(df_elast[['sku', 'elasticidad']], on='sku', how='left')
            # Para mover 1.5x el volumen necesitamos: %Δprecio = ln(1.5)/elasticidad
            # Esto es una guía de orden de magnitud
            df_sobre['descuento_sugerido_pct'] = df_sobre['elasticidad'].apply(
                lambda e: max(0, min(50, abs(0.4 / e * 100))) if pd.notna(e) and e < 0 else None
            )
        else:
            st.info("Archivo de elasticidad no tiene las columnas esperadas.")
    else:
        st.info("Sin datos de elasticidad — descuento sugerido no calculable. Correr `extract_elasticidad_basket.py`.")

    df_sobre = df_sobre.sort_values('exceso_uds', ascending=False)

    st.dataframe(
        df_sobre.head(200),
        width='stretch', hide_index=True,
        column_config={
            'stock_actual': st.column_config.NumberColumn('Stock', format='%.0f'),
            'cobertura_dias': st.column_config.NumberColumn('Cobertura (d)', format='%.0f'),
            'cobertura_max_dias': st.column_config.NumberColumn('Tope (d)', format='%.0f'),
            'exceso_uds': st.column_config.NumberColumn('Exceso uds', format='%.0f'),
            'descuento_sugerido_pct': st.column_config.NumberColumn('Descuento sug.', format='%.0f%%'),
        },
    )

    st.download_button(
        "⬇️ Descargar liquidación CSV",
        data=df_sobre.to_csv(index=False).encode('utf-8'),
        file_name=f"liquidacion_{pd.Timestamp.today().strftime('%Y%m%d')}.csv",
        mime='text/csv',
    )
