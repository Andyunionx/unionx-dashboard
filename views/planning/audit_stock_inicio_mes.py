"""Audit Stock Inicio Mes: planif_stock_baseline (11/05) vs Odoo real.

Confronta la triada teórica (baseline − ventas + tránsito) contra el stock_live
de Odoo. Detecta movimientos no contabilizados, mermas, ajustes, errores de
captura.

Validación: stock_fin_mes_actual_teorico ≈ stock_live (real Odoo)
  Si gap > umbral → bandera para investigar.
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from views.planning._core import proyectar_stock_mensual
from views.planning._data_helpers import (
    BASELINE_DATE,
    LINEAS_NEGOCIO_PLANIFICACION,
    cargar_planif_master,
    cargar_planif_stock_baseline,
    cargar_planif_stock_live,
    cargar_planif_transito_live,
    cargar_ventas_live_desde_baseline,
    cargar_ventas_year_minus_1,
)


def render():
    st.title("🔍 Audit Stock Inicio Mes")
    st.caption(
        f"Confronta la triada teórica (Stock baseline {BASELINE_DATE} − ventas reales + "
        f"tránsito llegado) contra el stock real de Odoo. Si calza → operación limpia. "
        f"Si hay gap → hay movimientos no contabilizados (mermas, ajustes, bodegas no mapeadas)."
    )

    # ---- Cargar fuentes ----
    with st.spinner("Cargando baseline + live + año pasado..."):
        df_base = cargar_planif_stock_baseline()
        df_master = cargar_planif_master()
        df_ventas = cargar_ventas_live_desde_baseline(
            lineas_negocio=tuple(LINEAS_NEGOCIO_PLANIFICACION),
        )
        df_trans = cargar_planif_transito_live()
        df_live = cargar_planif_stock_live()
        hoy_str = pd.Timestamp.today().strftime('%Y-%m-%d')
        y1 = cargar_ventas_year_minus_1(
            baseline_date=BASELINE_DATE, hoy=hoy_str,
            lineas_negocio=tuple(LINEAS_NEGOCIO_PLANIFICACION),
        )

    if df_base.empty:
        st.error("No hay baseline. Corre extract_baseline_planificacion.py.")
        st.stop()
    if df_live.empty:
        st.error("No hay stock_live de Odoo. Espera cron 06:00 AM o corre sync_planificacion.py.")
        st.stop()

    for d in (df_base, df_master, df_ventas, df_trans, df_live):
        if not d.empty and 'sku' in d.columns:
            d['sku'] = d['sku'].astype(str)

    # ---- Calcular triada proyectada para stock_fin_mes_actual ----
    df_proy = proyectar_stock_mensual(
        df_baseline=df_base, df_ventas=df_ventas, df_transito=df_trans,
        df_forecast_manual=None,
        baseline_date=BASELINE_DATE, horizonte_meses=1,
        ventas_y1_mismo=y1['mismo_periodo'], ventas_y1_resto=y1['resto_mes'],
    )

    # ---- Merge con stock_live ----
    df_audit = df_proy[['sku', 'stock_baseline', 'ventas_acum', 'venta_proy_mes_actual',
                          'transito_mes_actual', 'stock_fin_mes_actual']].copy()
    df_audit = df_audit.merge(
        df_live[['sku', 'stock_total', 'stock_disponible']].rename(
            columns={'stock_total': 'stock_live', 'stock_disponible': 'disponible_live'}
        ),
        on='sku', how='outer',
    )
    df_audit['stock_live'] = df_audit['stock_live'].fillna(0)
    df_audit['disponible_live'] = df_audit['disponible_live'].fillna(0)
    df_audit['stock_baseline'] = df_audit['stock_baseline'].fillna(0)
    df_audit['ventas_acum'] = df_audit['ventas_acum'].fillna(0)
    df_audit['transito_mes_actual'] = df_audit['transito_mes_actual'].fillna(0)
    df_audit['stock_fin_mes_actual'] = df_audit['stock_fin_mes_actual'].fillna(0)

    # Gap teórico vs real
    df_audit['gap'] = df_audit['stock_fin_mes_actual'] - df_audit['stock_live']
    df_audit['gap_abs'] = df_audit['gap'].abs()
    df_audit['gap_pct'] = df_audit.apply(
        lambda r: (r['gap'] / r['stock_baseline'] * 100) if r['stock_baseline'] > 0 else None,
        axis=1,
    )

    # Enriquecer con master
    if not df_master.empty:
        cols_m = [c for c in ['sku', 'marca', 'categoria_padre', 'categoria_hijo']
                  if c in df_master.columns]
        df_audit = df_audit.merge(df_master[cols_m].drop_duplicates(subset='sku'),
                                    on='sku', how='left')

    # ---- KPIs ----
    n_total = len(df_audit)
    n_match = int((df_audit['gap_abs'] < 1).sum())
    n_gap_chico = int(df_audit['gap_abs'].between(1, 10).sum())
    n_gap_grande = int((df_audit['gap_abs'] >= 10).sum())
    n_solo_planif = int((df_audit['stock_baseline'] > 0) & (df_audit['stock_live'] == 0))
    n_solo_odoo = int((df_audit['stock_baseline'] == 0) & (df_audit['stock_live'] > 0))

    st.markdown("### Resumen del audit")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("SKUs auditados", f"{n_total:,}")
    k2.metric("✅ Match (gap <1)", f"{n_match:,}",
              delta=f"{n_match/n_total*100:.1f}%" if n_total > 0 else "0%")
    k3.metric("🟡 Gap chico (1-10)", f"{n_gap_chico:,}")
    k4.metric("🔴 Gap grande (≥10)", f"{n_gap_grande:,}")
    k5.metric("Σ gap absoluto", f"{df_audit['gap_abs'].sum():,.0f} uds")

    st.divider()

    # Detalle interpretación
    with st.expander("ℹ️ Cómo leer los gaps", expanded=False):
        st.markdown(f"""
        **Fórmula**: `gap = stock_fin_mes_actual_teórico − stock_live`

        Donde `stock_fin_mes_actual_teórico = baseline(11/05) − ventas_reales + tránsito_llegado`

        **Interpretación**:
        - **Gap positivo** (teórico > real): la triada estima MÁS unidades de las que Odoo tiene.
          Causas posibles:
          - Mermas / ajustes de inventario no contabilizados como venta
          - Devoluciones de cliente que volvieron al stock pero no como NC
          - Pedidos cancelados que ya descontaron stock pero la venta no figura
          - Bodegas excluidas del filtro de líneas de negocio que sí mueven stock

        - **Gap negativo** (real > teórico): Odoo tiene MÁS unidades de las esperadas.
          Causas posibles:
          - Bodegas no mapeadas en el baseline (ej. nueva ubicación)
          - Compras recibidas que NO están en `data/comex/transito.parquet`
          - Ajustes de inventario positivos (encontrar stock perdido)

        **Filtro de ventas**: triada usa solo `{', '.join(LINEAS_NEGOCIO_PLANIFICACION)}`.
        Si hay venta significativa de Distribución/Corporativo, esos descuentos NO están
        en la fórmula y pueden inflar el gap positivo.
        """)

    # ---- Controles ----
    cc1, cc2, cc3 = st.columns([1, 1, 2])
    umbral_gap = cc1.slider("Umbral gap mínimo a mostrar", 0, 100, 5)
    marcas = ['(todas)'] + sorted(df_audit['marca'].dropna().unique().tolist()) if 'marca' in df_audit.columns else ['(todas)']
    marca_sel = cc2.selectbox("Marca", marcas)
    busqueda = cc3.text_input("Buscar SKU", placeholder="texto libre")

    view = df_audit[df_audit['gap_abs'] >= umbral_gap].copy()
    if marca_sel != '(todas)':
        view = view[view['marca'] == marca_sel]
    if busqueda:
        view = view[view['sku'].astype(str).str.lower().str.contains(busqueda.lower(), na=False)]
    view = view.sort_values('gap_abs', ascending=False)

    st.markdown(f"### Top SKUs con gap (≥ {umbral_gap} uds) — {len(view):,} SKUs")

    # ---- Tabs: por SKU / agrupado por marca / por cat padre ----
    tab1, tab2, tab3 = st.tabs(["📋 Por SKU", "🏷️ Por Marca", "📂 Por Cat Padre"])

    with tab1:
        cols_show = ['sku', 'marca', 'categoria_padre', 'categoria_hijo',
                      'stock_baseline', 'ventas_acum', 'transito_mes_actual',
                      'stock_fin_mes_actual', 'stock_live', 'gap', 'gap_pct']
        cols_show = [c for c in cols_show if c in view.columns]
        cfg = {
            'sku': st.column_config.TextColumn('SKU', width='small'),
            'marca': st.column_config.TextColumn('Marca', width='small'),
            'categoria_padre': st.column_config.TextColumn('Cat Padre', width='small'),
            'categoria_hijo': st.column_config.TextColumn('Cat Hijo', width='small'),
            'stock_baseline': st.column_config.NumberColumn('Stock 11/05', format='%.0f'),
            'ventas_acum': st.column_config.NumberColumn('Vta real', format='%.0f'),
            'transito_mes_actual': st.column_config.NumberColumn('Trán llegado', format='%.0f'),
            'stock_fin_mes_actual': st.column_config.NumberColumn('Teórico', format='%.0f',
                help='= baseline − ventas + tránsito mes actual'),
            'stock_live': st.column_config.NumberColumn('Real Odoo', format='%.0f'),
            'gap': st.column_config.NumberColumn('Gap (T − R)', format='%+.0f',
                help='positivo = teórico mayor a real'),
            'gap_pct': st.column_config.NumberColumn('Gap % baseline', format='%.1f%%'),
        }
        st.dataframe(view[cols_show].head(500), use_container_width=True,
                      hide_index=True, column_config=cfg, height=600)

        st.download_button(
            "⬇️ Descargar CSV completo",
            data=view.to_csv(index=False).encode('utf-8'),
            file_name=f"audit_stock_inicio_mes_{pd.Timestamp.today().strftime('%Y%m%d')}.csv",
            mime='text/csv',
        )

    def _agrupar(claves):
        if claves[0] not in view.columns:
            return None
        return view.groupby(claves, dropna=False).agg(
            n_skus=('sku', 'nunique'),
            stock_baseline=('stock_baseline', 'sum'),
            ventas_acum=('ventas_acum', 'sum'),
            transito_mes_actual=('transito_mes_actual', 'sum'),
            stock_fin_mes_actual=('stock_fin_mes_actual', 'sum'),
            stock_live=('stock_live', 'sum'),
            gap=('gap', 'sum'),
            gap_abs=('gap_abs', 'sum'),
        ).reset_index().sort_values('gap_abs', ascending=False)

    with tab2:
        g = _agrupar(['marca'])
        if g is None:
            st.warning("Sin columna marca.")
        else:
            st.markdown(f"**{len(g):,} marcas con gap ≥ {umbral_gap}**")
            st.dataframe(g, use_container_width=True, hide_index=True, height=500)

    with tab3:
        g = _agrupar(['categoria_padre'])
        if g is None:
            st.warning("Sin columna categoria_padre.")
        else:
            st.markdown(f"**{len(g):,} categorías padre con gap ≥ {umbral_gap}**")
            st.dataframe(g, use_container_width=True, hide_index=True, height=500)
