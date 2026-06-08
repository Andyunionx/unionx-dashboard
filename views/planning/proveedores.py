"""Módulo: Maestro de proveedores.

Fuente final: Drive (sheet a definir con tercero). Mientras tanto, lee
data/planificacion/proveedores_master.parquet (vacío al arranque).

La UI permite:
- Ver el maestro tal cual
- Identificar SKUs vendidos cuyo proveedor no está en el maestro (gaps)
- Cruce con tránsito COMEX (qué proveedores tienen pedidos activos)
- Cruce con maestra de importaciones (validación de costo EXW vs lo declarado)
"""
import pandas as pd
import streamlit as st

from views.planning._data_helpers import (
    cargar_proveedores_master,
    cargar_transito,
    cargar_ventas_historicas,
    PROVEEDORES_SCHEMA,
)


def render():
    st.title("🏭 Maestro de Proveedores")
    st.caption("Información estructural de proveedores: costo EXW, lead times, crédito, MOQ, contacto.")

    df_prov = cargar_proveedores_master()

    if df_prov.empty:
        st.warning(
            "**Esperando carga del maestro.** El archivo `data/planificacion/proveedores_master.parquet` "
            "está vacío. Cuando esté listo el Drive del tercero, correr "
            "`python extract_proveedores_master.py` para sincronizar."
        )
        with st.expander("📋 Schema esperado", expanded=True):
            st.markdown("El maestro debe contener estas columnas:")
            st.code("\n".join(f"- {c}" for c in PROVEEDORES_SCHEMA), language="markdown")
            st.markdown(
                "Ver `data/planificacion/proveedores_master.template.md` para detalle de cada campo."
            )
        _mostrar_gaps_proveedor_sin_maestro()
        return

    # Hay datos: vista normal
    st.success(f"✅ {len(df_prov)} proveedores cargados")

    tab1, tab2, tab3 = st.tabs(["📋 Maestro completo", "🔍 Gaps (SKUs sin proveedor)", "🚢 Cruce con tránsito"])

    with tab1:
        st.dataframe(df_prov, width='stretch', hide_index=True)
        st.caption(f"Total: {len(df_prov)} proveedores")

    with tab2:
        _mostrar_gaps_proveedor_sin_maestro(df_prov)

    with tab3:
        _mostrar_cruce_con_transito(df_prov)


def _mostrar_gaps_proveedor_sin_maestro(df_prov: pd.DataFrame = None):
    """SKUs que aparecen en ventas pero su proveedor no está en el maestro."""
    st.markdown("#### Proveedores con ventas pero sin ficha en el maestro")
    df_ventas = cargar_ventas_historicas(meses=12)
    if df_ventas.empty or 'proveedor' not in df_ventas.columns:
        st.info("Sin datos de ventas históricas para cruzar.")
        return

    proveedores_ventas = (
        df_ventas[df_ventas['proveedor'].notna() & (df_ventas['proveedor'] != '')]
        .groupby('proveedor')
        .agg(skus=('sku', 'nunique'), uds=('cantidad', 'sum'),
             venta=('venta_neta', 'sum'))
        .reset_index()
        .sort_values('venta', ascending=False)
    )

    if df_prov is not None and not df_prov.empty:
        proveedores_master = set(df_prov['nombre'].dropna().str.lower())
        proveedores_ventas['en_maestro'] = proveedores_ventas['proveedor'].str.lower().isin(proveedores_master)
        gaps = proveedores_ventas[~proveedores_ventas['en_maestro']]
    else:
        gaps = proveedores_ventas
        gaps['en_maestro'] = False

    st.caption(f"{len(gaps)} proveedores con venta últimos 12 meses sin ficha completa")
    st.dataframe(
        gaps[['proveedor', 'skus', 'uds', 'venta']].head(50),
        width='stretch', hide_index=True,
        column_config={
            'venta': st.column_config.NumberColumn('Venta 12m', format='$%.0f'),
            'uds': st.column_config.NumberColumn('Unidades', format='%.0f'),
        },
    )


def _mostrar_cruce_con_transito(df_prov: pd.DataFrame):
    """Proveedores que tienen pedidos en tránsito ahora mismo."""
    df_transito = cargar_transito()
    if df_transito.empty:
        st.info("Sin tránsito activo. Correr extract_comex_transito.py.")
        return

    # El tránsito viene del Drive de Martín — no necesariamente trae 'proveedor' explícito.
    # Lo inferimos del cruce sku → dim_productos si está disponible.
    st.info(
        "**Pendiente integración**: cruzar PIs activas con el maestro de proveedores "
        "(requiere que el maestro tenga la columna `proveedor_id` mapeada al `proveedor` de dim_productos)."
    )
    st.dataframe(df_transito.head(20), width='stretch', hide_index=True)
