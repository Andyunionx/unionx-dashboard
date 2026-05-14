"""Vista núcleo: Triada Proyectada por SKU × semana.

Toma el baseline al 11/05 + ventas reales acumuladas + tránsito con ETAs
+ forecast manual (opcional) → proyecta stock semana a semana y señala
cuándo cada SKU cruza a quiebre.

Sin forecast manual cargado, la demanda futura asume 0 → el stock solo
cae por ventas reales y sube por tránsitos. Es el piso conservador.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from views.planning._core import proyectar_stock_semanal
from views.planning._data_helpers import (
    BASELINE_DATE,
    cargar_planif_stock_baseline,
    cargar_planif_stock_live,
    cargar_planif_transito_live,
    cargar_planif_ventas_diarias,
)


def render():
    st.title("🎯 Triada Proyectada")
    st.caption(
        f"Stock baseline ({BASELINE_DATE}) − ventas reales (acumuladas desde el baseline) "
        f"+ tránsito (con ETAs) − forecast futuro = stock proyectado por semana."
    )

    # ---- Cargar fuentes ----
    with st.spinner("Cargando baseline + live..."):
        df_base = cargar_planif_stock_baseline()
        df_ventas = cargar_planif_ventas_diarias()
        df_trans = cargar_planif_transito_live()
        df_live = cargar_planif_stock_live()

    if df_base.empty:
        st.error(
            "No hay baseline cargado. Corre `extract_baseline_planificacion.py` "
            "para subir el snapshot al 11/05."
        )
        st.stop()

    # ---- KPIs top ----
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SKUs baseline", f"{len(df_base):,}")
    c2.metric("Días ventas acumuladas",
              (pd.Timestamp.today().normalize() - pd.Timestamp(BASELINE_DATE)).days)
    c3.metric("SKUs con venta desde baseline",
              f"{df_ventas['sku'].nunique() if not df_ventas.empty else 0:,}")
    c4.metric("Tránsito vigente (PIs)",
              f"{df_trans['pi'].nunique() if not df_trans.empty else 0:,}")

    st.divider()

    # ---- Controles ----
    cc1, cc2, cc3 = st.columns([1, 1, 2])
    horizonte = cc1.slider("Horizonte (semanas)", 4, 24, 12, step=4,
                            help="Cuántas semanas hacia adelante proyectar")
    incluir_forecast = cc2.checkbox(
        "Usar forecast manual", value=False,
        help="Si no hay forecast cargado, la demanda futura asume 0 (piso conservador)",
    )

    # Forecast manual: pendiente (vista propia en otra pestaña). Por ahora vacío.
    df_forecast = None
    if incluir_forecast:
        st.info("Forecast manual aún no implementado — usando demanda futura = 0 igual.")

    # ---- Calcular proyección ----
    with st.spinner(f"Proyectando stock semana 1 a {horizonte}..."):
        df_proy = proyectar_stock_semanal(
            df_baseline=df_base,
            df_ventas_diarias=df_ventas,
            df_transito=df_trans,
            df_forecast_manual=df_forecast,
            baseline_date=BASELINE_DATE,
            horizonte_semanas=horizonte,
        )

    if df_proy.empty:
        st.warning("Sin SKUs para proyectar.")
        st.stop()

    # ---- KPIs proyección ----
    st.markdown("### Resumen proyección")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("SKUs proyectados", f"{len(df_proy):,}")
    n_quiebre = int(df_proy['sem_quiebre'].notna().sum())
    k2.metric("SKUs con quiebre proyectado", f"{n_quiebre:,}",
              help="Quiebre dentro del horizonte (stock_proyectado < 0)")
    n_cr = int((df_proy['sem_quiebre'].fillna(99) <= 4).sum())
    k3.metric("🔴 Quiebre < 4 semanas", f"{n_cr:,}")
    n_ur = int((df_proy['sem_quiebre'].fillna(99).between(5, 8)).sum())
    k4.metric("🟠 Quiebre 5-8 semanas", f"{n_ur:,}")

    st.divider()

    # ---- Filtros ----
    f1, f2, f3 = st.columns([1, 1, 2])
    marcas = ['(todas)'] + sorted(df_proy['marca'].dropna().unique().tolist())
    marca_sel = f1.selectbox("Marca", marcas)
    solo_quiebre = f2.checkbox("Solo SKUs con quiebre proyectado", value=False)
    busqueda = f3.text_input("Buscar SKU / producto", placeholder="Texto libre")

    view = df_proy.copy()
    if marca_sel != '(todas)':
        view = view[view['marca'] == marca_sel]
    if solo_quiebre:
        view = view[view['sem_quiebre'].notna()]
    if busqueda:
        q = busqueda.lower()
        view = view[
            view['sku'].astype(str).str.lower().str.contains(q, na=False)
            | view['producto'].astype(str).str.lower().str.contains(q, na=False)
        ]

    # Ordenar por urgencia (sem_quiebre ASC, NaN al final)
    view = view.sort_values('sem_quiebre', na_position='last')

    st.markdown(f"### Tabla por SKU ({len(view):,} de {len(df_proy):,})")
    st.caption("Stock baseline = foto al 11/05. Stock sem N = proyección al final de la semana N.")

    # Estilos: gradiente rojo (negativos) → amarillo (bajos) → verde (positivos)
    semana_cols = [c for c in view.columns if c.startswith('stock_sem_')]
    column_config = {
        'sku': st.column_config.TextColumn('SKU', width='small'),
        'marca': st.column_config.TextColumn('Marca', width='small'),
        'producto': st.column_config.TextColumn('Producto', width='medium'),
        'stock_baseline': st.column_config.NumberColumn('Stock 11/05', format='%.0f'),
        'ventas_acum': st.column_config.NumberColumn('Ventas acum', format='%.0f'),
        'transito_llegado': st.column_config.NumberColumn('Trán llegado', format='%.0f'),
        'stock_hoy_est': st.column_config.NumberColumn('Stock hoy est.', format='%.0f',
                                                       help='baseline − ventas + tránsito_llegado'),
        'transito_pendiente': st.column_config.NumberColumn('Trán pendiente', format='%.0f'),
        'forecast_total': st.column_config.NumberColumn('Forecast total', format='%.0f'),
        'sem_quiebre': st.column_config.NumberColumn('Sem quiebre', format='%.0f',
                                                      help='Primera semana con stock proyectado < 0'),
    }
    for c in semana_cols:
        w = c.replace('stock_sem_', '')
        column_config[c] = st.column_config.NumberColumn(f'Sem +{w}', format='%.0f')

    # Aplicar styling con gradiente en cols de proyección
    try:
        sty = view.style.background_gradient(
            cmap='RdYlGn', subset=semana_cols, vmin=-50, vmax=200,
        ).format({c: '{:,.0f}' for c in (['stock_baseline', 'ventas_acum',
                                          'transito_llegado', 'stock_hoy_est',
                                          'transito_pendiente', 'forecast_total']
                                          + semana_cols)})
        st.dataframe(sty, use_container_width=True, hide_index=True,
                     column_config=column_config, height=600)
    except Exception:
        # Fallback sin styling si falla
        st.dataframe(view, use_container_width=True, hide_index=True,
                     column_config=column_config, height=600)

    # ---- Download ----
    st.download_button(
        "⬇️ Descargar proyección CSV",
        data=view.to_csv(index=False).encode('utf-8'),
        file_name=f"triada_proyectada_{pd.Timestamp.today().strftime('%Y%m%d')}.csv",
        mime='text/csv',
    )

    # ---- Validación baseline contra live ----
    st.divider()
    with st.expander("🔍 Validación baseline vs stock live", expanded=False):
        if df_live.empty:
            st.warning("No hay stock_live cargado. Corre `sync_planificacion.py` o "
                        "espera al cron de 06:00 AM.")
        else:
            # Comparar: stock_baseline − ventas_acum ≈ stock_live
            df_val = df_proy[['sku', 'stock_baseline', 'ventas_acum', 'stock_hoy_est']].copy()
            df_val = df_val.merge(
                df_live[['sku', 'stock_total']].rename(columns={'stock_total': 'stock_live'}),
                on='sku', how='left',
            )
            df_val['stock_live'] = df_val['stock_live'].fillna(0)
            df_val['gap'] = df_val['stock_hoy_est'] - df_val['stock_live']
            df_val['gap_pct'] = df_val.apply(
                lambda r: (r['gap'] / r['stock_baseline'] * 100) if r['stock_baseline'] > 0 else None,
                axis=1,
            )

            n_match = int((df_val['gap'].abs() < 1).sum())
            n_diff = len(df_val) - n_match
            top_gap = df_val[df_val['gap'].abs() > 5].nlargest(20, 'gap', keep='all')

            v1, v2, v3 = st.columns(3)
            v1.metric("SKUs OK (gap < 1)", f"{n_match:,}")
            v2.metric("SKUs con gap > 1", f"{n_diff:,}")
            v3.metric("Gap absoluto total", f"{df_val['gap'].abs().sum():,.0f}")

            st.caption("Top 20 SKUs con mayor gap absoluto:")
            st.dataframe(top_gap, use_container_width=True, hide_index=True)

            st.info(
                "💡 Gap = stock_baseline − ventas_acum − stock_live. Si es positivo, "
                "el live tiene MENOS unidades de lo esperado por la triada (movimientos "
                "no contabilizados, mermas, ajustes Odoo). Si es negativo, el live tiene "
                "MÁS unidades (compras recibidas no en tránsito o bodegas no mapeadas)."
            )
