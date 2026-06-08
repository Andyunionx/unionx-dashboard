"""Helper compartido: compacta tipos de DataFrame ventas antes de guardar parquet.
Reduce RAM ~70% (object → category, float64 → float32). Crítico para que Streamlit Cloud no crashee.
"""
import pandas as pd

_TEXT_COLS_CAT = [
    'canal','marca','categoria_macro','categoria_padre','categoria_hijo',
    'categoria_comercial','tipo_movimiento','tipo_despacho','tipo_negocio',
    'tipo_marca','tipo_compra','kam','estado_canal','estado_sku','estado_pedido',
    'pack','proveedor','dia_semana','bodega',
]
_INT_COLS = ['anio_venta','mes_venta','semana_venta','hora_venta_num']
_FLOAT_COLS = [
    'cantidad','venta_bruta','venta_neta','costo_unitario','costo_total',
    'margen_front','comision_pct','comision','logistica','marketing','margen_final',
]


def compactar_ventas(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica tipos compactos in-place. Devuelve el mismo DataFrame.

    Idempotente: si ya está compactado, no hace daño.
    """
    df = df.copy()
    for c in _TEXT_COLS_CAT:
        if c in df.columns and df[c].dtype != 'category':
            df[c] = df[c].astype('category')
    for c in _INT_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype('int32')
    for c in _FLOAT_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype('float32')
    return df


def mem_mb(df: pd.DataFrame) -> float:
    """Memoria del DataFrame en MB."""
    return df.memory_usage(deep=True).sum() / 1e6
