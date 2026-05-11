"""
Vista COMEX — Embarques activos + cruce con stock + forecast.

Lee data/comex/transito.parquet (extraído del sheet "Importaciones UnionX Integrada"
via extract_comex_transito.py).
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
COMEX_PARQUET = PROJECT_ROOT / 'data' / 'comex' / 'transito.parquet'
COMEX_RESUMEN = PROJECT_ROOT / 'data' / 'comex' / 'transito_resumen.json'
STOCK_LIVE = PROJECT_ROOT / 'data' / 'stock' / 'skus.parquet'
FC_SKUS_ANCHORED = PROJECT_ROOT / 'data' / 'forecast' / 'forecast_skus_anchored.parquet'


@st.cache_data(ttl=900)
def _cargar_transito():
    if not COMEX_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(COMEX_PARQUET)
    for col in ['fecha_embarque', 'fecha_eta_chile', 'fecha_eta_bodega']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
    return df


@st.cache_data(ttl=900)
def _cargar_stock_live():
    if not STOCK_LIVE.exists():
        return pd.DataFrame()
    return pd.read_parquet(STOCK_LIVE)


@st.cache_data(ttl=900)
def _cargar_forecast_skus():
    if not FC_SKUS_ANCHORED.exists():
        return pd.DataFrame()
    df = pd.read_parquet(FC_SKUS_ANCHORED)
    df['ds'] = pd.to_datetime(df['ds'])
    return df


def _tab_resumen(df: pd.DataFrame):
    if df.empty:
        st.info("Sin datos de tránsito.")
        return

    hoy = datetime.now().date()
    df_eta = df.dropna(subset=['fecha_eta_bodega']).copy()
    df_eta['dias_para_llegar'] = (df_eta['fecha_eta_bodega'].dt.date.apply(lambda d: (d - hoy).days))

    cols = st.columns(4)
    cols[0].metric("PIs en tránsito", df['pi'].nunique())
    cols[1].metric("SKUs en tránsito", df['sku'].nunique())
    cols[2].metric("Unidades totales", f"{df['cantidad'].sum():,.0f}")
    cols[3].metric("USD total estimado", f"${df['costo_total_usd'].sum()/1e3:,.0f}K")

    proximas = df_eta[(df_eta['dias_para_llegar'] >= 0) & (df_eta['dias_para_llegar'] <= 60)]
    cols2 = st.columns(3)
    cols2[0].metric("PIs llegando ≤30d", proximas[proximas['dias_para_llegar'] <= 30]['pi'].nunique())
    cols2[1].metric("PIs llegando 31-60d", proximas[(proximas['dias_para_llegar'] > 30) &
                                                       (proximas['dias_para_llegar'] <= 60)]['pi'].nunique())
    atrasadas = df_eta[df_eta['dias_para_llegar'] < 0]
    cols2[2].metric("PIs con ETA vencida", atrasadas['pi'].nunique(),
                     "Revisar status" if len(atrasadas) > 0 else "OK")


def _tab_por_pi(df: pd.DataFrame):
    if df.empty:
        return

    pi_agg = df.groupby(['pi', 'fecha_embarque', 'fecha_eta_chile', 'fecha_eta_bodega', 'transporte'],
                         dropna=False, as_index=False).agg(
        unidades=('cantidad', 'sum'),
        usd=('costo_total_usd', 'sum'),
        skus=('sku', 'nunique'),
    ).sort_values('fecha_eta_bodega')

    hoy = pd.Timestamp(datetime.now().date())
    pi_agg['dias_para_llegar'] = (pi_agg['fecha_eta_bodega'] - hoy).dt.days

    def status_emoji(d):
        if pd.isna(d):
            return '⚪ sin ETA'
        d = int(d)
        if d < 0:
            return f'🔴 vencido ({-d}d)'
        if d <= 14:
            return f'🟢 llega en {d}d'
        if d <= 30:
            return f'🟡 llega en {d}d'
        return f'⚪ llega en {d}d'

    pi_agg['Status'] = pi_agg['dias_para_llegar'].apply(status_emoji)
    pi_agg['USD'] = pi_agg['usd'].apply(lambda v: f'${v/1e3:,.1f}K')
    pi_agg['Unid'] = pi_agg['unidades'].apply(lambda v: f'{v:,.0f}')

    cols_show = ['pi', 'transporte', 'fecha_embarque', 'fecha_eta_chile', 'fecha_eta_bodega',
                  'skus', 'Unid', 'USD', 'Status']
    rename = {'pi': 'PI', 'transporte': 'Transporte', 'fecha_embarque': 'Embarque',
               'fecha_eta_chile': 'ETA Chile', 'fecha_eta_bodega': 'ETA Bodega',
               'skus': 'SKUs'}

    st.dataframe(pi_agg[cols_show].rename(columns=rename), use_container_width=True, hide_index=True, height=400)

    st.markdown("##### Timeline de llegadas a bodega")
    df_tl = pi_agg.dropna(subset=['fecha_eta_bodega']).sort_values('fecha_eta_bodega')
    if df_tl.empty:
        return
    fig = go.Figure()
    for _, r in df_tl.iterrows():
        fecha = r['fecha_eta_bodega']
        usd_k = r['usd'] / 1e3
        d = r['dias_para_llegar']
        color = '#DC2626' if d < 0 else '#10B981' if d <= 14 else '#EA580C' if d <= 30 else '#94A3B8'
        fig.add_trace(go.Scatter(
            x=[fecha], y=[usd_k],
            mode='markers+text',
            marker=dict(size=max(15, min(60, usd_k * 0.6)), color=color),
            text=[r['pi']], textposition='top center',
            hovertemplate=f"<b>{r['pi']}</b><br>ETA bodega: {fecha.date()}<br>USD: ${usd_k:.1f}K<br>SKUs: {r['skus']}<br>Unidades: {r['unidades']:,.0f}<extra></extra>",
            showlegend=False,
        ))
    fig.update_layout(
        height=380, xaxis=dict(title='ETA bodega'),
        yaxis=dict(title='USD valor PI (K)', tickformat=',.0f'),
        margin=dict(t=20, b=40, l=60, r=20),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Tamaño = USD del PI · 🟢 ≤14d · 🟡 15-30d · ⚪ >30d · 🔴 vencido")


def _tab_detalle_skus(df: pd.DataFrame):
    if df.empty:
        return

    pis_disp = sorted(df['pi'].dropna().unique())
    pi_sel = st.selectbox("PI", ["Todos"] + pis_disp, key="comex_pi_sel")

    df_show = df.copy() if pi_sel == "Todos" else df[df['pi'] == pi_sel]

    busqueda = st.text_input("Buscar SKU o producto", "", key="comex_search")
    if busqueda:
        mask = (df_show['sku'].str.contains(busqueda, case=False, na=False) |
                df_show['producto'].str.contains(busqueda, case=False, na=False))
        df_show = df_show[mask]

    cols_show = ['pi', 'sku', 'producto', 'cantidad', 'costo_unitario_usd', 'costo_total_usd',
                  'transporte', 'fecha_embarque', 'fecha_eta_bodega', 'nro_pedido']
    rename = {'pi': 'PI', 'sku': 'SKU', 'producto': 'Producto', 'cantidad': 'Cantidad',
               'costo_unitario_usd': 'USD/unid', 'costo_total_usd': 'USD total',
               'transporte': 'Transp.', 'fecha_embarque': 'Embarque', 'fecha_eta_bodega': 'ETA Bod',
               'nro_pedido': 'NPedido'}
    df_disp = df_show[cols_show].rename(columns=rename).sort_values(['ETA Bod', 'PI'])
    df_disp['Cantidad'] = df_disp['Cantidad'].apply(lambda v: f'{v:,.0f}' if pd.notna(v) else '-')
    df_disp['USD/unid'] = df_disp['USD/unid'].apply(lambda v: f'${v:,.2f}' if pd.notna(v) else '-')
    df_disp['USD total'] = df_disp['USD total'].apply(lambda v: f'${v:,.0f}' if pd.notna(v) else '-')
    st.caption(f"{len(df_disp):,} filas")
    st.dataframe(df_disp, use_container_width=True, hide_index=True, height=600)


def _tab_triangulacion(df_transito: pd.DataFrame, df_stock: pd.DataFrame, df_fc: pd.DataFrame):
    """Cierre del loop: stock presente + tránsito (ETA) + demanda forecast → señal de compra."""
    st.caption("**Triangulación demanda vs disponibilidad por SKU**. "
                "Stock presente + lo que llega por ETA + forecast demanda = brecha = señal de compra.")

    if df_transito.empty:
        st.info("Sin datos COMEX")
        return

    horizonte = st.select_slider("Horizonte de análisis", options=[30, 60, 90, 180], value=60, key="comex_hz")
    hoy = pd.Timestamp(datetime.now().date())
    cutoff = hoy + pd.Timedelta(days=horizonte)

    stock_sku = pd.Series(dtype='float64')
    if not df_stock.empty:
        col_qty = None
        for c in ['stock_total', 'total', 'cantidad_total', 'qty_total', 'on_hand']:
            if c in df_stock.columns:
                col_qty = c
                break
        if col_qty and 'sku' in df_stock.columns:
            stock_sku = df_stock.groupby('sku')[col_qty].sum()

    df_t = df_transito[df_transito['fecha_eta_bodega'] <= cutoff].copy()
    transito_sku = df_t.groupby('sku')['cantidad'].sum()

    demanda_sku = pd.Series(dtype='float64')
    if not df_fc.empty:
        fc_h = df_fc[(df_fc['ds'] > hoy) & (df_fc['ds'] <= cutoff)].copy()
        if 'yhat_anchored' in fc_h.columns:
            demanda_sku = fc_h.groupby('sku')['yhat_anchored'].sum()

    universo = set(stock_sku.index) | set(transito_sku.index) | set(demanda_sku.index)

    triang = pd.DataFrame({'sku': sorted(universo)})
    triang['stock_actual'] = triang['sku'].map(stock_sku).fillna(0)
    triang['en_transito'] = triang['sku'].map(transito_sku).fillna(0)
    triang['demanda_forecast'] = triang['sku'].map(demanda_sku).fillna(0)
    triang['disponibilidad_total'] = triang['stock_actual'] + triang['en_transito']
    triang['brecha'] = triang['demanda_forecast'] - triang['disponibilidad_total']
    triang['brecha_dias_stock'] = triang.apply(
        lambda r: (r['disponibilidad_total'] / (r['demanda_forecast'] / horizonte)) if r['demanda_forecast'] > 0 else 999,
        axis=1
    )

    triang = triang[triang['demanda_forecast'] > 0].copy()

    def categoria(r):
        if r['brecha'] > 0:
            if r['brecha_dias_stock'] < 15:
                return '🔴 Quiebre inminente'
            return '🟠 Brecha (necesita compra)'
        if r['brecha_dias_stock'] < 30:
            return '🟡 Stock justo'
        return '🟢 Stock suficiente'

    triang['estado'] = triang.apply(categoria, axis=1)

    cols = st.columns(4)
    cols[0].metric("SKUs evaluados", len(triang))
    cols[1].metric("🔴 Quiebre inminente", (triang['estado'] == '🔴 Quiebre inminente').sum())
    cols[2].metric("🟠 Necesita compra", (triang['estado'] == '🟠 Brecha (necesita compra)').sum())
    cols[3].metric("🟢 Stock suficiente", (triang['estado'] == '🟢 Stock suficiente').sum())

    st.markdown(f"##### SKUs con brecha (necesitan compra urgente) — horizonte {horizonte}d")
    df_show = triang[triang['brecha'] > 0].sort_values('brecha', ascending=False).head(50).copy()
    df_show['stock_actual'] = df_show['stock_actual'].apply(lambda v: f'{v:,.0f}')
    df_show['en_transito'] = df_show['en_transito'].apply(lambda v: f'{v:,.0f}')
    df_show['demanda_forecast'] = df_show['demanda_forecast'].apply(lambda v: f'{v:,.0f}')
    df_show['disponibilidad_total'] = df_show['disponibilidad_total'].apply(lambda v: f'{v:,.0f}')
    df_show['brecha'] = df_show['brecha'].apply(lambda v: f'+{v:,.0f}')
    df_show['brecha_dias_stock'] = df_show['brecha_dias_stock'].apply(lambda v: f'{v:.0f}d' if v < 999 else '∞')
    df_show.columns = ['SKU', 'Stock actual', 'En tránsito', f'Demanda {horizonte}d',
                        'Disp total', 'Brecha', 'Días stock', 'Estado']
    st.dataframe(df_show, use_container_width=True, hide_index=True, height=500)

    if df_stock.empty:
        st.warning("⚠️ Sin data de stock LIVE en `data/stock/skus.parquet`. La triangulación cruza solo COMEX vs Forecast.")


def render():
    with st.sidebar:
        st.markdown("### 🚢 **COMEX**")
        st.caption("Embarques en tránsito + triangulación")
        st.markdown("---")
        if st.button("🔄 Refrescar", use_container_width=True, type="primary", key="comex_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("🚢 COMEX — Embarques en tránsito")
    df = _cargar_transito()
    df_stock = _cargar_stock_live()
    df_fc = _cargar_forecast_skus()

    if COMEX_RESUMEN.exists():
        try:
            r = json.load(open(COMEX_RESUMEN, encoding='utf-8'))
            st.caption(f"🕒 Generado: {r.get('generado_en','')[:19]} · "
                        f"Fuente: sheet 'Importaciones UnionX Integrada' (Martin)")
        except Exception:
            pass

    if df.empty:
        st.warning("⏳ Sin datos. Correr `python extract_comex_transito.py`")
        return

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Resumen", "📋 Por PI / embarque", "📦 Detalle SKUs",
        "🎯 Triangulación demanda · stock · tránsito",
    ])
    with tab1:
        _tab_resumen(df)
    with tab2:
        _tab_por_pi(df)
    with tab3:
        _tab_detalle_skus(df)
    with tab4:
        _tab_triangulacion(df, df_stock, df_fc)
