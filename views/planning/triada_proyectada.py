"""Vista núcleo: Triada Proyectada por SKU × mes.

Toma el baseline al 11/05 + ventas LIVE (Turso ventas, agregado por SKU)
+ tránsito con ETAs + forecast manual (opcional, mensual) → proyecta
stock mes a mes y señala cuándo cada SKU cruza a quiebre.

Sin forecast manual cargado, la demanda futura asume 0 → el stock solo
cae por ventas reales y sube por tránsitos. Es el piso conservador.
"""
from __future__ import annotations

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


def _kpi_metric(col, label, value, help=None):
    col.metric(label, value, help=help)


def _agrupar(df: pd.DataFrame, claves: list, horiz: int) -> pd.DataFrame:
    """Agrega df por las claves dadas, sumando unidades. Ordena desc por stock fin mes actual."""
    if df.empty:
        return df
    stock_cols = [f'stock_mes_{i}' for i in range(1, horiz + 1)]
    trans_cols = [f'transito_mes_{i}' for i in range(1, horiz + 1)]
    agg_dict = {
        'sku': 'nunique',
        'stock_baseline': 'sum',
        'ventas_acum': 'sum',
        'venta_y1_mismo': 'sum',
        'venta_y1_resto': 'sum',
        'venta_proy_mes_actual': 'sum',
        'transito_mes_actual': 'sum',
        'stock_fin_mes_actual': 'sum',
        'transito_pendiente_3m': 'sum',
        'forecast_total': 'sum',
    }
    for c in stock_cols + trans_cols:
        if c in df.columns:
            agg_dict[c] = 'sum'

    g = df.groupby(claves, dropna=False).agg(agg_dict).reset_index()
    g = g.rename(columns={'sku': 'n_skus'})
    return g.sort_values('stock_fin_mes_actual', ascending=False)


def render():
    st.title("🎯 Triada Proyectada")
    st.caption(
        f"Stock baseline ({BASELINE_DATE}) − venta proy mes (real + curva 2025 × crecimiento) "
        f"+ tránsito (con ETAs) − forecast manual meses futuros = stock proyectado mensual. "
        f"Ventas filtradas: **{' + '.join(LINEAS_NEGOCIO_PLANIFICACION)}**."
    )

    # ---- Cargar fuentes ----
    with st.spinner("Cargando baseline + master + live + año pasado..."):
        df_base = cargar_planif_stock_baseline()
        df_master = cargar_planif_master()
        # Ventas filtradas por líneas de negocio: Marketplace + Páginas propias + Fidelización
        df_ventas = cargar_ventas_live_desde_baseline(
            lineas_negocio=tuple(LINEAS_NEGOCIO_PLANIFICACION),
        )
        df_trans = cargar_planif_transito_live()
        df_live = cargar_planif_stock_live()
        # Año pasado (mismo período + resto del mes) para proyección estacional
        hoy_str = pd.Timestamp.today().strftime('%Y-%m-%d')
        y1 = cargar_ventas_year_minus_1(
            baseline_date=BASELINE_DATE, hoy=hoy_str,
            lineas_negocio=tuple(LINEAS_NEGOCIO_PLANIFICACION),
        )

    if df_base.empty:
        st.error("No hay baseline cargado. Corre `extract_baseline_planificacion.py`.")
        st.stop()

    # ---- Normalizar SKU tipos para merge ----
    for d in (df_base, df_master, df_ventas, df_trans):
        if not d.empty and 'sku' in d.columns:
            d['sku'] = d['sku'].astype(str)

    # ---- KPIs top ----
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SKUs baseline", f"{len(df_base):,}")
    c2.metric("Días desde baseline",
              (pd.Timestamp.today().normalize() - pd.Timestamp(BASELINE_DATE)).days)
    c3.metric("SKUs con venta (live)",
              f"{df_ventas['sku'].nunique() if not df_ventas.empty else 0:,}")
    c4.metric("PIs en tránsito", f"{df_trans['pi'].nunique() if not df_trans.empty else 0:,}")

    st.divider()

    # ---- Controles ----
    cc1, cc2, cc3 = st.columns([1, 1, 1])
    horizonte = cc1.slider("Horizonte (meses)", 3, 18, 12, step=3)
    ocultar_sin_stock = cc2.checkbox(
        "Ocultar SKUs sin stock ni tránsito", value=True,
        help="SKUs inactivos (sin baseline, sin ventas, sin tránsito)",
    )
    mostrar_transito_desg = cc3.checkbox(
        "Desagregar tránsito por mes", value=False,
        help="Agregar cols Trán Mes +1, +2, ... mostrando llegadas por mes",
    )

    # Forecast manual: aún no implementado
    df_forecast = None

    # ---- Calcular proyección (estacional con curva 2025 + crecimiento por SKU) ----
    with st.spinner(f"Proyectando stock mes 1 a {horizonte}..."):
        df_proy = proyectar_stock_mensual(
            df_baseline=df_base,
            df_ventas=df_ventas,
            df_transito=df_trans,
            df_forecast_manual=df_forecast,
            baseline_date=BASELINE_DATE,
            horizonte_meses=horizonte,
            ventas_y1_mismo=y1['mismo_periodo'],
            ventas_y1_resto=y1['resto_mes'],
        )

    if df_proy.empty:
        st.warning("Sin SKUs para proyectar.")
        st.stop()

    # ---- Enriquecer con master (marca + cat padre + cat hijo) ----
    if not df_master.empty:
        cols_master = ['sku', 'marca', 'categoria_padre', 'categoria_hijo', 'ranking_comercial']
        cols_present = [c for c in cols_master if c in df_master.columns]
        # Sobrescribir marca del baseline con la del master (más limpia)
        df_proy = df_proy.drop(columns=['marca'], errors='ignore').merge(
            df_master[cols_present].drop_duplicates(subset='sku'),
            on='sku', how='left',
        )

    # ---- Filtrar SKUs muertos (sin actividad) ----
    # "Sin stock" = sin baseline + sin ventas desde baseline + sin tránsito = SKU inactivo
    # Mantenemos visibles los en quiebre actual (stock_fin_mes_actual ≤ 0) si tienen actividad
    if ocultar_sin_stock:
        mask = (
            (df_proy['stock_baseline'] > 0)
            | (df_proy['ventas_acum'] > 0)
            | (df_proy['transito_pendiente_3m'] > 0)
            | (df_proy['transito_mes_actual'] > 0)
        )
        df_proy = df_proy[mask].copy()

    # ---- Limpieza marca/categorías para agrupación ----
    for c in ('marca', 'categoria_padre', 'categoria_hijo'):
        if c in df_proy.columns:
            df_proy[c] = df_proy[c].fillna('(sin clasificar)').replace(
                {'nan': '(sin clasificar)', 'None': '(sin clasificar)', '': '(sin clasificar)'}
            )

    # ---- KPIs proyección ----
    st.markdown("### Resumen proyección")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("SKUs activos", f"{len(df_proy):,}")
    n_quiebre = int(df_proy['mes_quiebre'].notna().sum())
    k2.metric("Quiebre proyectado", f"{n_quiebre:,}",
              help="SKUs que cruzan stock < 0 dentro del horizonte")
    n_cr = int((df_proy['mes_quiebre'].fillna(99) <= 1).sum())
    k3.metric("🔴 Quiebre YA o mes 1", f"{n_cr:,}",
              help="Mes 0 = ya en quiebre (stock hoy ≤ 0). Mes 1 = quiebre proyectado en el mes 1.")
    n_ur = int((df_proy['mes_quiebre'].fillna(99).between(2, 3)).sum())
    k4.metric("🟠 Quiebre mes 2-3", f"{n_ur:,}")

    st.divider()

    # ---- Tabs: SKU detalle / Agrupación ----
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Por SKU",
        "🏷️ Por Marca",
        "📂 Marca → Cat Padre",
        "📁 Marca → Cat Padre → Cat Hijo",
    ])

    stock_cols = [f'stock_mes_{i}' for i in range(1, horizonte + 1)]
    trans_cols = [f'transito_mes_{i}' for i in range(1, horizonte + 1)]
    mes_actual_nombre = pd.Timestamp.today().strftime('%b %Y').lower()
    column_config_base = {
        'stock_baseline': st.column_config.NumberColumn('Stock 11/05', format='%.0f',
            help='Foto del Excel FCST al 11/05 10:00'),
        'ventas_acum': st.column_config.NumberColumn('Ventas post-11/05', format='%.0f',
            help='Ventas reales acumuladas desde 11/05 (LIVE Turso, líneas filtradas)'),
        'run_rate_diario': st.column_config.NumberColumn('Run-rate (u/día)', format='%.2f',
            help='Promedio diario = ventas_acum / días_transcurridos_post_baseline'),
        'venta_y1_mismo': st.column_config.NumberColumn('Vta 2025 mismo per', format='%.0f',
            help='Ventas año pasado en mismo rango de días (11→hoy)'),
        'venta_y1_resto': st.column_config.NumberColumn('Vta 2025 resto mes', format='%.0f',
            help='Ventas año pasado del resto del mes (hoy+1 → fin mes)'),
        'crec_vs_y1': st.column_config.NumberColumn('Crec vs 2025', format='%.2fx',
            help='Crecimiento = ventas 2026 mismo per / ventas 2025 mismo per. Cap [0.2x..5x]. Si no hay venta 2025 → fallback run-rate.'),
        'fuente_proy_mes': st.column_config.TextColumn('Fuente proy', width='small',
            help='estacional = usa curva 2025 × crecimiento. run-rate = fallback lineal'),
        'venta_proy_mes_actual': st.column_config.NumberColumn(f'Venta proy {mes_actual_nombre}', format='%.0f',
            help='Proyección de venta TOTAL del mes = real_acum + (venta 2025 resto × crecimiento)'),
        'transito_mes_actual': st.column_config.NumberColumn(f'Trán {mes_actual_nombre}', format='%.0f',
            help='Tránsito con ETA dentro del mes actual (ya recibido o por recibir)'),
        'stock_fin_mes_actual': st.column_config.NumberColumn(f'Stock fin {mes_actual_nombre}', format='%.0f',
            help='= baseline − venta proyectada mes + tránsito mes'),
        'transito_pendiente_3m': st.column_config.NumberColumn('Trán pend +3m', format='%.0f',
            help='Tránsito por llegar en los próximos 3 meses (mes +1, +2, +3)'),
        'forecast_total': st.column_config.NumberColumn('Fcst total', format='%.0f',
            help='Forecast manual total cargado para los meses futuros'),
        'mes_quiebre': st.column_config.NumberColumn('Mes quiebre', format='%.0f',
            help='0 = ya en quiebre. N = stock < 0 al fin del mes +N'),
    }
    for c in stock_cols:
        w = c.replace('stock_mes_', '')
        column_config_base[c] = st.column_config.NumberColumn(f'Stock fin Mes +{w}', format='%.0f',
            help=f'Stock al final del mes +{w} = stock fin mes anterior − ventas/fcst mes +{w} + tránsito mes +{w}')
    for c in trans_cols:
        w = c.replace('transito_mes_', '')
        column_config_base[c] = st.column_config.NumberColumn(f'Trán Mes +{w}', format='%.0f',
            help=f'Tránsito que llega en el mes +{w}')

    # ---- Tab 1: por SKU ----
    with tab1:
        # Filtros
        f1, f2, f3 = st.columns([1, 1, 2])
        marcas = ['(todas)'] + sorted(df_proy['marca'].dropna().unique().tolist())
        marca_sel = f1.selectbox("Marca", marcas, key='sku_marca')
        solo_quiebre = f2.checkbox("Solo SKUs con quiebre", value=False, key='sku_quiebre')
        busqueda = f3.text_input("Buscar SKU / producto", placeholder="texto libre", key='sku_buscar')

        view = df_proy.copy()
        if marca_sel != '(todas)':
            view = view[view['marca'] == marca_sel]
        if solo_quiebre:
            view = view[view['mes_quiebre'].notna()]
        if busqueda:
            q = busqueda.lower()
            view = view[
                view['sku'].astype(str).str.lower().str.contains(q, na=False)
                | view['producto'].astype(str).str.lower().str.contains(q, na=False)
            ]
        view = view.sort_values('stock_fin_mes_actual', ascending=False)

        st.markdown(f"**{len(view):,} de {len(df_proy):,} SKUs** (ordenado por stock fin mes actual)")
        col_config_sku = dict(column_config_base)
        col_config_sku.update({
            'sku': st.column_config.TextColumn('SKU', width='small'),
            'marca': st.column_config.TextColumn('Marca', width='small'),
            'categoria_padre': st.column_config.TextColumn('Cat Padre', width='small'),
            'categoria_hijo': st.column_config.TextColumn('Cat Hijo', width='small'),
            'producto': st.column_config.TextColumn('Producto', width='medium'),
        })
        cols_show = ['sku', 'marca', 'categoria_padre', 'categoria_hijo', 'producto',
                     'stock_baseline', 'ventas_acum', 'venta_y1_mismo', 'venta_y1_resto',
                     'crec_vs_y1', 'fuente_proy_mes', 'venta_proy_mes_actual',
                     'transito_mes_actual', 'stock_fin_mes_actual',
                     'transito_pendiente_3m', 'forecast_total',
                     'mes_quiebre'] + stock_cols
        if mostrar_transito_desg:
            cols_show = cols_show + trans_cols
        cols_show = [c for c in cols_show if c in view.columns]
        try:
            sty = view[cols_show].style.background_gradient(
                cmap='RdYlGn', subset=[c for c in stock_cols if c in cols_show],
                vmin=-50, vmax=500,
            )
            st.dataframe(sty, use_container_width=True, hide_index=True,
                         column_config=col_config_sku, height=600)
        except Exception:
            st.dataframe(view[cols_show], use_container_width=True, hide_index=True,
                         column_config=col_config_sku, height=600)

        st.download_button(
            "⬇️ Descargar CSV",
            data=view[cols_show].to_csv(index=False).encode('utf-8'),
            file_name=f"triada_proyectada_sku_{pd.Timestamp.today().strftime('%Y%m%d')}.csv",
            mime='text/csv', key='dl_sku',
        )

    def _render_grupo(g, label_claves, vmax):
        col_config_g = dict(column_config_base)
        col_config_g['n_skus'] = st.column_config.NumberColumn('SKUs', format='%d')
        for k in label_claves:
            col_config_g[k[0]] = st.column_config.TextColumn(k[1], width=k[2])
        # cols a mostrar
        base_cols = (list(c[0] for c in label_claves) + ['n_skus', 'stock_baseline',
                     'ventas_acum', 'venta_y1_mismo', 'venta_y1_resto',
                     'venta_proy_mes_actual', 'transito_mes_actual',
                     'stock_fin_mes_actual', 'transito_pendiente_3m',
                     'forecast_total']) + stock_cols
        if mostrar_transito_desg:
            base_cols = base_cols + trans_cols
        cols_show = [c for c in base_cols if c in g.columns]
        try:
            sty = g[cols_show].style.background_gradient(
                cmap='RdYlGn', subset=[c for c in stock_cols if c in cols_show],
                vmin=-50, vmax=vmax,
            )
            st.dataframe(sty, use_container_width=True, hide_index=True,
                         column_config=col_config_g, height=600)
        except Exception:
            st.dataframe(g[cols_show], use_container_width=True, hide_index=True,
                         column_config=col_config_g, height=600)

    # ---- Tab 2: por Marca ----
    with tab2:
        g = _agrupar(df_proy, ['marca'], horizonte)
        st.markdown(f"**{len(g):,} marcas activas** (ordenado por stock fin mes actual)")
        _render_grupo(g, [('marca', 'Marca', 'medium')], vmax=2000)

    # ---- Tab 3: Marca → Cat Padre ----
    with tab3:
        if 'categoria_padre' not in df_proy.columns:
            st.warning("Sin columna categoria_padre disponible (master no cargado).")
        else:
            g = _agrupar(df_proy, ['marca', 'categoria_padre'], horizonte)
            st.markdown(f"**{len(g):,} grupos Marca × Cat Padre**")
            _render_grupo(g, [('marca', 'Marca', 'small'),
                              ('categoria_padre', 'Cat Padre', 'medium')], vmax=1000)

    # ---- Tab 4: Marca → Cat Padre → Cat Hijo ----
    with tab4:
        if 'categoria_hijo' not in df_proy.columns:
            st.warning("Sin columna categoria_hijo disponible (master no cargado).")
        else:
            g = _agrupar(df_proy, ['marca', 'categoria_padre', 'categoria_hijo'], horizonte)
            st.markdown(f"**{len(g):,} grupos Marca × Cat Padre × Cat Hijo**")
            _render_grupo(g, [('marca', 'Marca', 'small'),
                              ('categoria_padre', 'Cat Padre', 'small'),
                              ('categoria_hijo', 'Cat Hijo', 'medium')], vmax=500)

    # ---- Validación expandible ----
    st.divider()
    with st.expander("🔍 Validación baseline vs stock live (Odoo)", expanded=False):
        if df_live.empty:
            st.warning("No hay stock_live cargado. Corre sync o espera cron 06:00 AM.")
        else:
            df_val = df_proy[['sku', 'marca', 'stock_baseline', 'ventas_acum', 'stock_fin_mes_actual']].copy()
            df_val = df_val.merge(
                df_live[['sku', 'stock_total']].rename(columns={'stock_total': 'stock_live'}),
                on='sku', how='left',
            )
            df_val['stock_live'] = df_val['stock_live'].fillna(0)
            df_val['gap'] = df_val['stock_fin_mes_actual'] - df_val['stock_live']

            v1, v2, v3 = st.columns(3)
            v1.metric("SKUs match (gap < 1)", f"{int((df_val['gap'].abs() < 1).sum()):,}")
            v2.metric("SKUs con gap", f"{int((df_val['gap'].abs() >= 1).sum()):,}")
            v3.metric("Gap absoluto total", f"{df_val['gap'].abs().sum():,.0f}")

            top_gap = df_val[df_val['gap'].abs() > 5].copy()
            top_gap['abs_gap'] = top_gap['gap'].abs()
            st.caption("Top 30 SKUs con mayor gap:")
            st.dataframe(top_gap.nlargest(30, 'abs_gap').drop(columns='abs_gap'),
                         use_container_width=True, hide_index=True)
            st.info(
                "Gap = stock_fin_mes_actual − stock_live (Odoo). Positivo = la triada "
                "estima más stock del que hay en Odoo (movimientos no contabilizados, "
                "mermas). Negativo = Odoo tiene más (bodegas no mapeadas, compras "
                "recibidas no tracked en tránsito)."
            )
