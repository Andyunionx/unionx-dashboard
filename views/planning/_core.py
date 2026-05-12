"""Lógica pura de planificación de compras.

Sin Streamlit, sin I/O, sin caches. Solo funciones que reciben DataFrames y
devuelven DataFrames. Testeable de manera aislada.

Conceptos:
- Posición de stock = stock_actual + llegadas_en_ventana - demanda_acumulada
- Cobertura (días) = stock_actual / venta_diaria_promedio
- Stock objetivo = venta_diaria_promedio * dias_objetivo (de la política)
- Requerimiento = max(0, stock_objetivo - posición_proyectada_en_lead_time)
- Trigger de compra = cobertura_dias < lead_time_total + buffer
"""
from __future__ import annotations

import pandas as pd


def calcular_venta_diaria(df_ventas: pd.DataFrame, ventana_dias: int = 90) -> pd.DataFrame:
    """Venta diaria promedio por SKU en los últimos N días.

    Returns: DataFrame con columnas [sku, venta_diaria_uds, ventana_dias_efectiva]
    """
    if df_ventas.empty:
        return pd.DataFrame(columns=['sku', 'venta_diaria_uds', 'ventana_dias_efectiva'])

    df = df_ventas.copy()
    corte = pd.Timestamp.today() - pd.Timedelta(days=ventana_dias)
    df = df[df['fecha_venta'] >= corte]
    if df.empty:
        return pd.DataFrame(columns=['sku', 'venta_diaria_uds', 'ventana_dias_efectiva'])

    g = df.groupby('sku').agg(
        uds_total=('cantidad', 'sum'),
        dias_distintos=('fecha_venta', lambda x: x.dt.normalize().nunique()),
    ).reset_index()
    g['venta_diaria_uds'] = g['uds_total'] / ventana_dias
    g['ventana_dias_efectiva'] = ventana_dias
    return g[['sku', 'venta_diaria_uds', 'ventana_dias_efectiva']]


def calcular_demanda_acumulada(df_forecast: pd.DataFrame, hasta: pd.Timestamp) -> pd.DataFrame:
    """Suma forecast desde hoy hasta la fecha dada por SKU.

    Returns: DataFrame con columnas [sku, demanda_uds, dias_horizonte]
    """
    if df_forecast.empty:
        return pd.DataFrame(columns=['sku', 'demanda_uds', 'dias_horizonte'])

    hoy = pd.Timestamp.today().normalize()
    df = df_forecast.copy()
    df = df[(df['fecha'] >= hoy) & (df['fecha'] <= hasta)]
    if df.empty:
        return pd.DataFrame(columns=['sku', 'demanda_uds', 'dias_horizonte'])

    col_uds = 'forecast_uds' if 'forecast_uds' in df.columns else (
        'yhat' if 'yhat' in df.columns else None
    )
    if col_uds is None:
        return pd.DataFrame(columns=['sku', 'demanda_uds', 'dias_horizonte'])

    g = df.groupby('sku')[col_uds].sum().reset_index().rename(
        columns={col_uds: 'demanda_uds'}
    )
    g['dias_horizonte'] = (hasta - hoy).days
    return g


def calcular_llegadas_en_ventana(df_transito: pd.DataFrame, hasta: pd.Timestamp) -> pd.DataFrame:
    """Suma unidades en tránsito con ETA bodega <= fecha dada por SKU.

    Returns: DataFrame con columnas [sku, llegadas_uds, pis]
    """
    if df_transito.empty:
        return pd.DataFrame(columns=['sku', 'llegadas_uds', 'pis'])

    hoy = pd.Timestamp.today().normalize()
    df = df_transito.copy()

    # SKUs cuya ETA bodega está entre hoy y hasta — si no hay ETA bodega, usar ETA Chile
    if 'fecha_eta_bodega' in df.columns:
        df['_eta'] = df['fecha_eta_bodega'].fillna(df.get('fecha_eta_chile'))
    elif 'fecha_eta_chile' in df.columns:
        df['_eta'] = df['fecha_eta_chile']
    else:
        return pd.DataFrame(columns=['sku', 'llegadas_uds', 'pis'])

    df = df[(df['_eta'] >= hoy) & (df['_eta'] <= hasta)]
    if df.empty:
        return pd.DataFrame(columns=['sku', 'llegadas_uds', 'pis'])

    cantidad_col = 'cantidad' if 'cantidad' in df.columns else 'unidades'
    g = df.groupby('sku').agg(
        llegadas_uds=(cantidad_col, 'sum'),
        pis=('pi', lambda x: ', '.join(sorted(set(map(str, x.dropna()))))),
    ).reset_index()
    return g


def construir_triada(
    df_stock: pd.DataFrame,
    df_transito: pd.DataFrame,
    df_forecast: pd.DataFrame,
    horizonte_dias: int = 60,
) -> pd.DataFrame:
    """Une stock actual + llegadas + demanda en una sola tabla por SKU.

    Args:
        df_stock: columnas [sku, stock_actual_uds, producto, categoria_comercial, ...]
        df_transito: salida de extract_comex_transito (sku, cantidad, fecha_eta_bodega)
        df_forecast: forecast diario por SKU
        horizonte_dias: ventana de proyección (default 60d)

    Returns:
        DataFrame con [sku, producto, categoria_comercial, stock_actual,
                       llegadas, demanda, posicion_proyectada, cobertura_dias]
    """
    hasta = pd.Timestamp.today().normalize() + pd.Timedelta(days=horizonte_dias)

    df_demanda = calcular_demanda_acumulada(df_forecast, hasta)
    df_llegadas = calcular_llegadas_en_ventana(df_transito, hasta)

    base = df_stock[['sku']].drop_duplicates() if not df_stock.empty else pd.DataFrame(columns=['sku'])
    if not df_transito.empty:
        base = pd.concat([base, df_transito[['sku']]]).drop_duplicates()
    if not df_forecast.empty:
        base = pd.concat([base, df_forecast[['sku']]]).drop_duplicates()

    if base.empty:
        return pd.DataFrame(columns=[
            'sku', 'producto', 'categoria_comercial', 'stock_actual',
            'llegadas', 'demanda', 'posicion_proyectada', 'cobertura_dias',
        ])

    out = base.merge(df_stock, on='sku', how='left') if not df_stock.empty else base
    out = out.merge(df_llegadas, on='sku', how='left')
    out = out.merge(df_demanda, on='sku', how='left')

    out['stock_actual'] = out.get('stock_actual_uds', out.get('Qty', 0)).fillna(0)
    out['llegadas'] = out['llegadas_uds'].fillna(0)
    out['demanda'] = out['demanda_uds'].fillna(0)
    out['posicion_proyectada'] = out['stock_actual'] + out['llegadas'] - out['demanda']

    # Cobertura = stock / demanda diaria promedio en el horizonte
    out['demanda_diaria'] = out['demanda'] / horizonte_dias
    out['cobertura_dias'] = out.apply(
        lambda r: (r['stock_actual'] / r['demanda_diaria']) if r['demanda_diaria'] > 0 else None,
        axis=1,
    )

    cols = ['sku', 'producto', 'categoria_comercial', 'stock_actual',
            'llegadas', 'demanda', 'posicion_proyectada', 'cobertura_dias', 'pis']
    return out[[c for c in cols if c in out.columns]]


def calcular_requerimiento(
    df_triada: pd.DataFrame,
    df_politicas: pd.DataFrame,
    df_proveedores: pd.DataFrame = None,
) -> pd.DataFrame:
    """Para cada SKU calcula cuánto comprar dado:
    - posición proyectada al final del horizonte
    - stock objetivo (= venta_diaria * meses_cobertura_objetivo * 30)
    - lead time del proveedor (producción + tránsito)

    Returns: DataFrame con [sku, requerimiento_uds, urgencia, dias_hasta_quiebre]
    """
    if df_triada.empty or df_politicas.empty:
        return pd.DataFrame(columns=['sku', 'requerimiento_uds', 'urgencia', 'dias_hasta_quiebre'])

    df = df_triada.merge(df_politicas, on='categoria_comercial', how='left')

    # Stock objetivo en unidades = demanda_diaria * meses_objetivo * 30
    df['stock_objetivo_uds'] = df['demanda_diaria'].fillna(0) * df['meses_cobertura_objetivo'].fillna(2) * 30
    df['requerimiento_uds'] = (df['stock_objetivo_uds'] - df['posicion_proyectada']).clip(lower=0)

    # Días hasta quiebre = stock_actual / demanda_diaria
    df['dias_hasta_quiebre'] = df.apply(
        lambda r: (r['stock_actual'] / r['demanda_diaria']) if r.get('demanda_diaria', 0) > 0 else None,
        axis=1,
    )

    # Urgencia
    def _urgencia(r):
        dias = r.get('dias_hasta_quiebre')
        if dias is None:
            return 'SIN_DEMANDA'
        if dias < 15:
            return 'CRITICO'
        if dias < 30:
            return 'URGENTE'
        if dias < 60:
            return 'NORMAL'
        return 'HOLGADO'

    df['urgencia'] = df.apply(_urgencia, axis=1)
    return df[['sku', 'producto', 'categoria_comercial', 'stock_actual',
               'demanda', 'posicion_proyectada', 'stock_objetivo_uds',
               'requerimiento_uds', 'dias_hasta_quiebre', 'urgencia']]


def metricas_por_sku(
    df_ventas: pd.DataFrame,
    df_stock_actual: pd.DataFrame,
    dias: int = 90,
) -> pd.DataFrame:
    """Métricas por SKU en los últimos N días: rotación, ROI, margen %.

    Args:
        df_ventas: ventas históricas con columnas
            [sku, fecha_venta, cantidad, costo_total, costo_unitario, venta_neta,
             margen_front, categoria_comercial]
        df_stock_actual: stock snapshot por SKU con columnas
            [sku, stock_actual_uds, capital_invertido]
            Vía `cached_stock()['skus']` (que usa default_code matching ventas).
            Si está vacío, rotación y ROI quedan en NaN.
        dias: ventana de análisis (afecta sólo agregación de ventas)

    Returns:
        DataFrame con [sku, categoria_comercial, uds_vendidas, venta_neta,
                       margen_total, margen_pct, stock_actual_uds, capital_invertido,
                       rotacion_anual, roi_periodo, dias_con_venta, cv_venta]
    """
    if df_ventas.empty:
        return pd.DataFrame()

    corte = pd.Timestamp.today().normalize() - pd.Timedelta(days=dias)
    df_v = df_ventas[df_ventas['fecha_venta'] >= corte].copy()
    if df_v.empty:
        return pd.DataFrame()
    df_v['sku'] = df_v['sku'].astype(str)

    # Agregado de ventas por SKU
    agg_v = df_v.groupby('sku').agg(
        uds_vendidas=('cantidad', 'sum'),
        venta_neta=('venta_neta', 'sum'),
        costo_total=('costo_total', 'sum'),
        margen_total=('margen_front', 'sum'),
        dias_con_venta=('fecha_venta', lambda s: s.dt.normalize().nunique()),
        venta_diaria_std=('cantidad', 'std'),
        venta_diaria_mean=('cantidad', 'mean'),
    ).reset_index()
    agg_v['categoria_comercial'] = df_v.groupby('sku')['categoria_comercial'].first().values

    # Stock actual + capital invertido (snapshot)
    if df_stock_actual is not None and not df_stock_actual.empty:
        df_s = df_stock_actual.copy()
        df_s['sku'] = df_s['sku'].astype(str)
        cols_stock = ['sku', 'stock_actual_uds', 'capital_invertido']
        df_s = df_s[[c for c in cols_stock if c in df_s.columns]]
    else:
        df_s = pd.DataFrame(columns=['sku', 'stock_actual_uds', 'capital_invertido'])

    out = agg_v.merge(df_s, on='sku', how='left')
    if 'stock_actual_uds' not in out.columns:
        out['stock_actual_uds'] = None
    if 'capital_invertido' not in out.columns:
        out['capital_invertido'] = None

    # Rotación anualizada = (uds vendidas / stock_actual) * (365 / días)
    # Proxy: stock actual como aproximación del promedio del período
    out['rotacion_anual'] = out.apply(
        lambda r: (r['uds_vendidas'] / r['stock_actual_uds']) * (365 / dias)
        if pd.notna(r['stock_actual_uds']) and r['stock_actual_uds'] > 0 else None,
        axis=1,
    )

    # ROI período = margen acumulado / capital invertido
    out['roi_periodo'] = out.apply(
        lambda r: r['margen_total'] / r['capital_invertido']
        if pd.notna(r['capital_invertido']) and r['capital_invertido'] > 0 else None,
        axis=1,
    )

    # Margen %
    out['margen_pct'] = out.apply(
        lambda r: r['margen_total'] / r['venta_neta'] * 100 if r['venta_neta'] > 0 else None,
        axis=1,
    )

    # Coeficiente de variación (estabilidad de la venta diaria)
    out['cv_venta'] = out.apply(
        lambda r: r['venta_diaria_std'] / r['venta_diaria_mean']
        if r['venta_diaria_mean'] and r['venta_diaria_mean'] > 0 else None,
        axis=1,
    )

    out['ventana_dias'] = dias
    return out[['sku', 'categoria_comercial', 'uds_vendidas', 'venta_neta',
                'margen_total', 'margen_pct', 'stock_actual_uds', 'capital_invertido',
                'rotacion_anual', 'roi_periodo', 'dias_con_venta', 'cv_venta', 'ventana_dias']]


def caracterizar_categorias(df_metricas: pd.DataFrame) -> pd.DataFrame:
    """Resume cómo se comporta empíricamente cada categoría comercial.

    Útil para validar si la taxonomía sigue siendo coherente con la realidad.
    """
    if df_metricas.empty:
        return pd.DataFrame()

    g = df_metricas.groupby('categoria_comercial').agg(
        n_skus=('sku', 'nunique'),
        uds_vendidas_total=('uds_vendidas', 'sum'),
        venta_neta_total=('venta_neta', 'sum'),
        margen_total=('margen_total', 'sum'),
        rotacion_anual_mediana=('rotacion_anual', 'median'),
        rotacion_anual_p75=('rotacion_anual', lambda s: s.quantile(0.75)),
        roi_periodo_mediano=('roi_periodo', 'median'),
        roi_periodo_p75=('roi_periodo', lambda s: s.quantile(0.75)),
        margen_pct_mediano=('margen_pct', 'median'),
        dias_con_venta_mediano=('dias_con_venta', 'median'),
        cv_venta_mediano=('cv_venta', 'median'),
        costo_inv_total=('capital_invertido', 'sum'),
    ).reset_index()

    total_venta = g['venta_neta_total'].sum()
    total_skus = g['n_skus'].sum()
    g['pct_venta'] = g['venta_neta_total'] / total_venta * 100 if total_venta else 0
    g['pct_skus'] = g['n_skus'] / total_skus * 100 if total_skus else 0
    g['margen_pct_agg'] = g.apply(
        lambda r: r['margen_total'] / r['venta_neta_total'] * 100
        if r['venta_neta_total'] > 0 else None,
        axis=1,
    )

    # Orden esperado: Diamante > Oro > Plata > Bronce > Nuevo > Pack > resto
    orden = {'Diamante': 1, 'Oro': 2, 'Plata': 3, 'Bronce': 4,
             'Nuevo': 5, 'Pack': 6, 'In/Out': 7, 'No aplica': 8}
    g['_orden'] = g['categoria_comercial'].map(orden).fillna(99)
    g = g.sort_values('_orden').drop(columns='_orden')
    return g


def detectar_drift_categorias(df_metricas: pd.DataFrame, top_pct: float = 0.20) -> pd.DataFrame:
    """SKUs cuya rotación + ROI no calzan con su categoría actual.

    Lógica simple:
    - Top top_pct de rotación entre TODOS los SKUs activos → candidatos a "Diamante"
    - Si el SKU está en top y NO es Diamante: candidato a PROMOVER
    - Si el SKU es Diamante y está en bottom 30%: candidato a DEGRADAR

    Args:
        df_metricas: salida de metricas_por_sku
        top_pct: proporción que define "élite" (default 20%)

    Returns:
        DataFrame con [sku, categoria_actual, categoria_sugerida, motivo, rotacion_anual, roi_periodo]
    """
    if df_metricas.empty:
        return pd.DataFrame()

    df = df_metricas.dropna(subset=['rotacion_anual']).copy()
    if df.empty:
        return pd.DataFrame()

    # Ranking por rotación
    df['rank_rot'] = df['rotacion_anual'].rank(pct=True, ascending=True)
    df['rank_roi'] = df['roi_periodo'].rank(pct=True, ascending=True)

    # Score combinado rotación + ROI (la definición de "Diamante")
    df['score'] = df[['rank_rot', 'rank_roi']].mean(axis=1)

    # Sugerencia por score
    def _categoria_sugerida(score):
        if score >= (1 - top_pct):
            return 'Diamante'
        if score >= 0.6:
            return 'Oro'
        if score >= 0.35:
            return 'Plata'
        return 'Bronce'

    df['categoria_sugerida'] = df['score'].apply(_categoria_sugerida)
    df['cat_actual_norm'] = df['categoria_comercial'].astype(str).str.strip()

    # Excluir categorías especiales (no aplica el ranking metálico)
    excluidas = {'In/Out', 'No aplica', '0', 'Nuevo', 'Pack'}
    df = df[~df['cat_actual_norm'].isin(excluidas)]
    # Sólo drift = donde sugerida ≠ actual
    df = df[df['categoria_sugerida'] != df['cat_actual_norm']]
    if df.empty:
        return pd.DataFrame()

    orden = {'Diamante': 4, 'Oro': 3, 'Plata': 2, 'Bronce': 1}
    df['motivo'] = df.apply(
        lambda r: 'PROMOVER (rotación/ROI > categoría actual)'
        if orden.get(r['categoria_sugerida'], 0) > orden.get(r['cat_actual_norm'], 0)
        else 'DEGRADAR (rotación/ROI < categoría actual)',
        axis=1,
    )

    return df[['sku', 'categoria_comercial', 'categoria_sugerida', 'motivo',
               'rotacion_anual', 'roi_periodo', 'margen_pct', 'uds_vendidas',
               'score']].rename(columns={'categoria_comercial': 'categoria_actual'})


def detectar_sobrestock(df_triada: pd.DataFrame, df_politicas: pd.DataFrame) -> pd.DataFrame:
    """SKUs con cobertura > política máxima (candidatos a liquidación)."""
    if df_triada.empty or df_politicas.empty:
        return pd.DataFrame(columns=['sku', 'cobertura_dias', 'exceso_uds'])

    df = df_triada.merge(df_politicas, on='categoria_comercial', how='left')
    df['cobertura_max_dias'] = df['meses_cobertura_maximo'].fillna(6) * 30
    df['exceso_uds'] = df.apply(
        lambda r: max(0, r['stock_actual'] - r['demanda_diaria'] * r['cobertura_max_dias'])
        if pd.notna(r.get('demanda_diaria')) else 0,
        axis=1,
    )
    return df[df['exceso_uds'] > 0][['sku', 'producto', 'categoria_comercial',
                                      'stock_actual', 'cobertura_dias',
                                      'cobertura_max_dias', 'exceso_uds']]
