"""
Vista COMEX — Embarques activos + cruce con stock + forecast.

Lee data/comex/transito.parquet (extract_comex_desde_odoo.py — purchase.order
Topwill activas con receipt_status != 'full'). El Sheet de Martín se usa como
contraste para alertas (transito_alertas.json).
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
COMEX_ALERTAS = PROJECT_ROOT / 'data' / 'comex' / 'transito_alertas.json'
VALIDACION_ODOO = PROJECT_ROOT / 'data' / 'comex' / 'validacion_odoo.parquet'
VALIDACION_RESUMEN = PROJECT_ROOT / 'data' / 'comex' / 'validacion_odoo_resumen.json'
DIMENSIONES_PARQUET = PROJECT_ROOT / 'data' / 'comex' / 'dimensiones_skus.parquet'
DIMENSIONES_RESUMEN = PROJECT_ROOT / 'data' / 'comex' / 'dimensiones_resumen.json'
STOCK_LIVE = PROJECT_ROOT / 'data' / 'stock' / 'skus.parquet'
FC_SKUS_ANCHORED = PROJECT_ROOT / 'data' / 'forecast' / 'forecast_skus_anchored.parquet'


@st.cache_data(ttl=900)
def _cargar_alertas_comex() -> dict:
    if not COMEX_ALERTAS.exists():
        return {}
    try:
        return json.loads(COMEX_ALERTAS.read_text(encoding='utf-8'))
    except Exception:
        return {}


@st.cache_data(ttl=900)
def _cargar_transito():
    if not COMEX_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(COMEX_PARQUET)
    for col in ['fecha_embarque', 'fecha_eta_chile', 'fecha_eta_bodega']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
    # costo_ingreso_clp puede venir como string (Sheet legacy) o numérico (enriquecedor).
    # Normalizar a float para que la vista pueda comparar y agregar sin pelar tipos.
    if 'costo_ingreso_clp' in df.columns:
        df['costo_ingreso_clp'] = pd.to_numeric(df['costo_ingreso_clp'], errors='coerce')
    else:
        df['costo_ingreso_clp'] = pd.NA
    return df


@st.cache_data(ttl=900)
def _cargar_validacion_odoo() -> tuple[pd.DataFrame, dict]:
    """Validación PIs vs Odoo stock.move."""
    df = pd.DataFrame()
    resumen = {}
    if VALIDACION_ODOO.exists():
        df = pd.read_parquet(VALIDACION_ODOO)
    if VALIDACION_RESUMEN.exists():
        try:
            resumen = json.load(open(VALIDACION_RESUMEN, encoding='utf-8'))
        except Exception:
            pass
    return df, resumen


@st.cache_data(ttl=900)
def _cargar_dimensiones() -> tuple[pd.DataFrame, dict]:
    """Lee dimensiones por SKU (peso/volumen Odoo) + resumen por PI."""
    df = pd.DataFrame()
    resumen = {}
    if DIMENSIONES_PARQUET.exists():
        df = pd.read_parquet(DIMENSIONES_PARQUET)
    if DIMENSIONES_RESUMEN.exists():
        try:
            resumen = json.load(open(DIMENSIONES_RESUMEN, encoding='utf-8'))
        except Exception:
            pass
    return df, resumen


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


def _tab_resumen(df: pd.DataFrame, val_resumen: dict):
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

    # KPIs de costeo: cuántas filas tienen costo_ingreso_clp poblado vs pendientes
    n_filas = len(df)
    n_costeados = int(df['costo_ingreso_clp'].notna().sum()) if 'costo_ingreso_clp' in df.columns else 0
    n_pendientes = n_filas - n_costeados
    pct = (n_costeados / n_filas * 100) if n_filas else 0
    clp_total = float(df['costo_ingreso_clp'].sum()) if n_costeados else 0
    pis_pendientes_costo = (
        df[df['costo_ingreso_clp'].isna()]['pi'].nunique() if 'costo_ingreso_clp' in df.columns else 0
    )

    cols_c = st.columns(4)
    cols_c[0].metric("SKUs precosteados", f"{n_costeados:,}/{n_filas:,}", f"{pct:.0f}%")
    cols_c[1].metric("CLP internado", f"${clp_total/1e6:,.1f}MM",
                     "calculado sobre lo precosteado")
    cols_c[2].metric("SKUs pendientes precosteo", f"{n_pendientes:,}",
                     f"{pis_pendientes_costo} PIs" if pis_pendientes_costo else "OK")
    proximas = df_eta[(df_eta['dias_para_llegar'] >= 0) & (df_eta['dias_para_llegar'] <= 60)]
    cols_c[3].metric("PIs llegando ≤30d",
                      proximas[proximas['dias_para_llegar'] <= 30]['pi'].nunique())

    cols2 = st.columns(3)
    cols2[0].metric("PIs llegando 31-60d", proximas[(proximas['dias_para_llegar'] > 30) &
                                                       (proximas['dias_para_llegar'] <= 60)]['pi'].nunique())
    atrasadas = df_eta[df_eta['dias_para_llegar'] < 0]
    cols2[1].metric("PIs con ETA vencida", atrasadas['pi'].nunique(),
                     "Revisar status" if len(atrasadas) > 0 else "OK")
    sin_eta = df[df['fecha_eta_bodega'].isna()]['pi'].nunique() if 'fecha_eta_bodega' in df.columns else 0
    cols2[2].metric("PIs sin ETA cargada", sin_eta)

    # Validación Odoo: PIs probablemente ingresadas pero drive desactualizado
    if val_resumen:
        st.divider()
        st.markdown("##### 🔍 Cruce con Odoo (stock.move)")
        st.caption(f"Última validación: {val_resumen.get('generado_en','')[:19]}. "
                    "Detecta PIs ya ingresadas en Odoo pero que el drive aún marca en tránsito.")
        cols3 = st.columns(4)
        cols3[0].metric("🟢 PIs ya ingresadas", val_resumen.get('pis_ingresados', 0),
                         "drive desactualizado" if val_resumen.get('pis_ingresados', 0) > 0 else None)
        cols3[1].metric("🟡 Parciales", val_resumen.get('pis_parciales', 0))
        cols3[2].metric("🔴 Realmente pendientes", val_resumen.get('pis_pendientes', 0))
        cols3[3].metric("SKUs sin match Odoo", val_resumen.get('sku_no_match_odoo', 0))

        # Tabla con PIs ingresadas (alerta visible)
        pis_ingresados = [p for p in val_resumen.get('por_pi', []) if p['status_pi'] == '🟢 INGRESADO']
        if pis_ingresados:
            st.warning(f"⚠️ {len(pis_ingresados)} PI(s) parecen ya recibidas en Odoo. "
                        "Pedir a Martin actualizar 'Importaciones UnionX Integrada' (mover a EN BODEGA):")
            df_alert = pd.DataFrame(pis_ingresados)[
                ['pi', 'fecha_embarque', 'unidades_esperadas', 'unidades_recibidas', 'ratio_pi']
            ].rename(columns={
                'pi': 'PI', 'fecha_embarque': 'Embarque',
                'unidades_esperadas': 'Esperado', 'unidades_recibidas': 'Recibido (Odoo)',
                'ratio_pi': '% recibido',
            })
            df_alert['% recibido'] = (df_alert['% recibido'] * 100).round(1).astype(str) + '%'
            df_alert['Esperado'] = df_alert['Esperado'].apply(lambda v: f'{v:,.0f}')
            df_alert['Recibido (Odoo)'] = df_alert['Recibido (Odoo)'].apply(lambda v: f'{v:,.0f}')
            st.dataframe(df_alert, width='stretch', hide_index=True)


def _tab_por_pi(df: pd.DataFrame, val_resumen: dict | None = None):
    if df.empty:
        return

    pi_agg = df.groupby(['pi', 'fecha_embarque', 'fecha_eta_chile', 'fecha_eta_bodega', 'transporte'],
                         dropna=False, as_index=False).agg(
        unidades=('cantidad', 'sum'),
        usd=('costo_total_usd', 'sum'),
        skus=('sku', 'nunique'),
        filas=('sku', 'size'),
        filas_costeadas=('costo_ingreso_clp', lambda s: int(s.notna().sum())),
        clp_costeado=('costo_ingreso_clp', 'sum'),
    ).sort_values('fecha_eta_bodega')

    # Estado costeo por PI: completo / parcial / pendiente — comparado fila vs fila
    def _estado_costeo(row):
        fc = int(row['filas_costeadas'])
        ft = int(row['filas'])
        if fc == 0:
            return '⚠️ Pendiente'
        if fc < ft:
            return f'🟡 Parcial ({fc}/{ft})'
        return '✅ Completo'

    pi_agg['Costeo'] = pi_agg.apply(_estado_costeo, axis=1)
    pi_agg['CLP internado'] = pi_agg['clp_costeado'].apply(
        lambda v: f'${v/1e6:,.1f}MM' if v and v > 0 else '—'
    )

    # Merge con validacion Odoo
    val_map = {p['pi']: p for p in (val_resumen.get('por_pi', []) if val_resumen else [])}
    pi_agg['Odoo'] = pi_agg['pi'].map(lambda p: val_map.get(p, {}).get('status_pi', '⚪ -'))
    pi_agg['% recibido'] = pi_agg['pi'].map(
        lambda p: f"{val_map.get(p, {}).get('ratio_pi', 0)*100:.0f}%" if p in val_map else '-'
    )

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
                  'skus', 'Unid', 'USD', 'CLP internado', 'Costeo', 'Status', 'Odoo', '% recibido']
    rename = {'pi': 'PI', 'transporte': 'Transporte', 'fecha_embarque': 'Embarque',
               'fecha_eta_chile': 'ETA Chile', 'fecha_eta_bodega': 'ETA Bodega',
               'skus': 'SKUs'}

    st.dataframe(pi_agg[cols_show].rename(columns=rename), width='stretch', hide_index=True, height=400)

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
    st.plotly_chart(fig, width='stretch')
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
                  'costo_ingreso_clp', 'transporte', 'fecha_embarque', 'fecha_eta_bodega', 'nro_pedido']
    rename = {'pi': 'PI', 'sku': 'SKU', 'producto': 'Producto', 'cantidad': 'Cantidad',
               'costo_unitario_usd': 'USD/unid', 'costo_total_usd': 'USD total',
               'costo_ingreso_clp': 'CLP internado',
               'transporte': 'Transp.', 'fecha_embarque': 'Embarque', 'fecha_eta_bodega': 'ETA Bod',
               'nro_pedido': 'NPedido'}
    df_disp = df_show[cols_show].rename(columns=rename).sort_values(['ETA Bod', 'PI'])
    df_disp['Cantidad'] = df_disp['Cantidad'].apply(lambda v: f'{v:,.0f}' if pd.notna(v) else '-')
    df_disp['USD/unid'] = df_disp['USD/unid'].apply(lambda v: f'${v:,.2f}' if pd.notna(v) else '-')
    df_disp['USD total'] = df_disp['USD total'].apply(lambda v: f'${v:,.0f}' if pd.notna(v) else '-')
    df_disp['CLP internado'] = df_disp['CLP internado'].apply(
        lambda v: f'${v:,.0f}' if pd.notna(v) and v > 0 else 'Pendiente'
    )
    st.caption(f"{len(df_disp):,} filas")
    st.dataframe(df_disp, width='stretch', hide_index=True, height=600)


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
    st.dataframe(df_show, width='stretch', hide_index=True, height=500)

    if df_stock.empty:
        st.warning("⚠️ Sin data de stock LIVE en `data/stock/skus.parquet`. La triangulación cruza solo COMEX vs Forecast.")


def _tab_volumen_pallets(df_dim: pd.DataFrame, resumen_dim: dict):
    """Estimación m³ / pallets / containers por embarque, usando peso+volumen Odoo."""
    if df_dim.empty or not resumen_dim:
        st.info(
            "⏳ Sin datos de dimensiones. Correr "
            "`python extract_comex_dimensiones.py` (cruza SKUs en tránsito con "
            "peso/volumen de `product.template` en Odoo)."
        )
        return

    st.caption(
        f"🕒 Generado: {resumen_dim.get('generado_en','')[:19]} · "
        f"Fuente: Odoo `product.template` (weight, volume, packaging) · "
        f"Cruzado con SKUs de `data/comex/transito.parquet`."
    )

    cob_peso = resumen_dim.get('cobertura_peso_pct', 0)
    cob_vol = resumen_dim.get('cobertura_volumen_pct', 0)
    cob_vol_ok = resumen_dim.get('cobertura_volumen_confiable_pct', 0)
    sku_match = resumen_dim.get('sku_match_odoo', 0)
    sku_total = resumen_dim.get('sku_input', 0)
    sku_anom = resumen_dim.get('sku_volumen_anomalo', 0)
    sku_maestra = resumen_dim.get('sku_con_maestra_manual', 0)

    # Banner: estado de la maestra manual
    if sku_maestra > 0:
        st.success(
            f"✅ Maestra manual de cajas master activa — {sku_maestra} SKU(s) "
            "con override sobre Odoo (data/comex/maestra_cajas_master.json)."
        )
    else:
        st.info(
            "📥 **Sin maestra manual cargada.** Cuando tengas el archivo de "
            "unidades por caja master:\n"
            "1. Subir como `data/comex/maestra_cajas_master.json` (ver "
            "`maestra_cajas_master.EJEMPLO.json`) o `maestra_cajas_master.xlsx` "
            "con columnas `SKU | qty_caja_master | m3_caja_master | kg_caja_master`.\n"
            "2. Correr `python extract_comex_dimensiones.py` o esperar el cron "
            "(cada 3h vía `sync_comex.yml`).\n"
            "3. Esta tab se actualiza automáticamente con los nuevos m³/pallets."
        )

    # Header KPIs globales
    cols = st.columns(5)
    cols[0].metric("Unidades totales", f"{resumen_dim.get('unidades_totales', 0):,.0f}")
    cols[1].metric("Peso total", f"{resumen_dim.get('peso_total_kg', 0)/1000:,.1f} ton")
    cols[2].metric(
        "Volumen confiable",
        f"{resumen_dim.get('volumen_total_m3', 0):,.1f} m³",
        f"sin {sku_anom} SKUs anómalos" if sku_anom else None,
    )
    cols[3].metric("Pallets estimados", f"{resumen_dim.get('pallets_totales_estim', 0):,.1f}")
    cols[4].metric("Match Odoo", f"{sku_match}/{sku_total}",
                    f"{cob_peso:.0f}% peso · {cob_vol_ok:.0f}% vol OK")

    if cob_peso < 80 or cob_vol_ok < 80:
        st.warning(
            f"⚠️ Cobertura baja en Odoo (peso {cob_peso:.0f}% · volumen confiable "
            f"{cob_vol_ok:.0f}%). Las estimaciones por PI son **subestimaciones** "
            "— completar `weight` y `volume` en `product.template` o esperar la "
            "maestra de cajas master de Andrés."
        )

    # Bloque data quality: SKUs con volumen anómalo (mal cargado en Odoo)
    skus_anom_top = resumen_dim.get('skus_volumen_anomalo_top', [])
    if skus_anom_top:
        with st.expander(
            f"⚠️ {sku_anom} SKU(s) con volumen anómalo en Odoo "
            "(>1 m³/unidad — probablemente cargado en cm³ por error)",
            expanded=False,
        ):
            st.caption(
                "El campo `volume` en `product.template` debe estar en m³. "
                "Revisar y corregir en Odoo para que la estimación de m³/pallets "
                "sea más precisa. Mientras tanto, estos SKUs se EXCLUYEN del cálculo."
            )
            df_anom = pd.DataFrame(skus_anom_top)
            df_anom['volumen_unit_m3'] = df_anom['volumen_unit_m3'].apply(
                lambda v: f'{v:,.2f} m³ (¡anómalo!)'
            )
            df_anom.columns = ['SKU', 'Producto', 'Volumen unit Odoo']
            st.dataframe(df_anom, width='stretch', hide_index=True)

    asunc = resumen_dim.get('asunciones', {})
    st.caption(
        f"📐 Asunciones: 1 pallet ≈ {asunc.get('m3_por_pallet', 1.2)} m³ · "
        f"Container 20' ≈ {asunc.get('m3_container_20', 28)} m³ útiles · "
        f"Container 40' HC ≈ {asunc.get('m3_container_40hc', 67)} m³ útiles."
    )

    st.divider()

    # Tabla por PI
    st.markdown("##### 📦 Resumen por PI / embarque")
    pi_data = resumen_dim.get('por_pi', [])
    if pi_data:
        df_pi = pd.DataFrame(pi_data)
        # Formato visible
        df_show = df_pi[[
            'pi', 'transporte', 'fecha_embarque', 'fecha_eta_bodega',
            'skus_distintos', 'unidades_totales', 'peso_total_kg',
            'volumen_total_m3', 'pallets_estim', 'containers_20_estim',
            'containers_40hc_estim', 'cobertura_peso_pct', 'cobertura_volumen_pct',
        ]].copy()
        df_show['unidades_totales'] = df_show['unidades_totales'].apply(lambda v: f'{v:,.0f}')
        df_show['peso_total_kg'] = df_show['peso_total_kg'].apply(
            lambda v: f'{v/1000:,.2f} t' if v >= 1000 else f'{v:,.1f} kg'
        )
        df_show['volumen_total_m3'] = df_show['volumen_total_m3'].apply(lambda v: f'{v:,.2f} m³')
        df_show['pallets_estim'] = df_show['pallets_estim'].apply(lambda v: f'{v:,.1f}')
        df_show['containers_20_estim'] = df_show['containers_20_estim'].apply(lambda v: f'{v:,.2f}')
        df_show['containers_40hc_estim'] = df_show['containers_40hc_estim'].apply(lambda v: f'{v:,.2f}')
        df_show['cobertura_peso_pct'] = df_show['cobertura_peso_pct'].apply(lambda v: f'{v:.0f}%')
        df_show['cobertura_volumen_pct'] = df_show['cobertura_volumen_pct'].apply(lambda v: f'{v:.0f}%')
        df_show.columns = ['PI', 'Transp.', 'Embarque', 'ETA bodega', 'SKUs',
                            'Unidades', 'Peso', 'Volumen', 'Pallets', 'Cont 20\'',
                            'Cont 40\' HC', 'Cob. peso', 'Cob. vol']
        st.dataframe(df_show, width='stretch', hide_index=True, height=380)

    st.divider()

    # Detalle SKU por PI
    st.markdown("##### 🔍 Detalle SKU (cantidad × peso unit × vol unit)")
    pis_disp = sorted(df_dim['pi'].dropna().unique())
    pi_sel = st.selectbox("PI", ["Todos"] + pis_disp, key="comex_dim_pi_sel")
    df_d = df_dim.copy() if pi_sel == "Todos" else df_dim[df_dim['pi'] == pi_sel]

    cols_show = ['pi', 'sku', 'producto', 'cantidad',
                  'peso_unit_kg', 'peso_total_kg',
                  'volumen_unit_m3', 'volumen_total_m3',
                  'qty_caja_master', 'cajas_master_estim', 'match_odoo']
    df_disp = df_d[cols_show].copy()
    df_disp['cantidad'] = df_disp['cantidad'].apply(lambda v: f'{v:,.0f}')
    df_disp['peso_unit_kg'] = df_disp['peso_unit_kg'].apply(
        lambda v: f'{v:,.3f} kg' if v > 0 else '—'
    )
    df_disp['peso_total_kg'] = df_disp['peso_total_kg'].apply(
        lambda v: f'{v:,.1f} kg' if v > 0 else '—'
    )
    df_disp['volumen_unit_m3'] = df_disp['volumen_unit_m3'].apply(
        lambda v: f'{v:,.4f} m³' if v > 0 else '—'
    )
    df_disp['volumen_total_m3'] = df_disp['volumen_total_m3'].apply(
        lambda v: f'{v:,.3f} m³' if v > 0 else '—'
    )
    df_disp['qty_caja_master'] = df_disp['qty_caja_master'].apply(
        lambda v: f'{v:,.0f}' if pd.notna(v) and v > 0 else '—'
    )
    df_disp['cajas_master_estim'] = df_disp['cajas_master_estim'].apply(
        lambda v: f'{v:,.1f}' if pd.notna(v) and v > 0 else '—'
    )
    df_disp['match_odoo'] = df_disp['match_odoo'].apply(lambda v: '✅' if v else '🔴')
    df_disp.columns = ['PI', 'SKU', 'Producto', 'Cantidad', 'Peso unit', 'Peso total',
                        'Vol unit', 'Vol total', 'Caja master qty', 'Cajas estim', 'Odoo']
    st.caption(f"{len(df_disp):,} líneas")
    st.dataframe(df_disp, width='stretch', hide_index=True, height=420)

    # SKUs sin match
    sin_match = resumen_dim.get('skus_sin_match', [])
    if sin_match:
        with st.expander(f"🔴 SKUs sin match en Odoo ({len(sin_match)})", expanded=False):
            st.caption(
                "Estos SKUs no tienen registro en `product.product` por `default_code` "
                "ni por `barcode`. Verificar que el código del sheet COMEX coincida con Odoo."
            )
            st.code('\n'.join(sin_match[:50]) + ('\n…' if len(sin_match) > 50 else ''))


def _tab_alertas(alertas: dict):
    """Reconciliación Sheet (Drive Martín) vs Odoo (purchase.order Topwill)."""
    if not alertas:
        st.info(
            "Sin archivo `data/comex/transito_alertas.json`. Correr "
            "`python comparar_transito_sheet_vs_odoo.py` para generarlo."
        )
        return

    totales = alertas.get('totales', {})
    st.caption(f"🕒 Generado: {alertas.get('generado_en','')[:19]} · "
                f"Odoo (fuente principal) vs Sheet Martín (contraste)")

    cols = st.columns(5)
    cols[0].metric("PIs Odoo", totales.get('pis_odoo', 0))
    cols[1].metric("PIs Sheet", totales.get('pis_sheet', 0))
    cols[2].metric("Coinciden", totales.get('pis_en_ambos', 0))
    cols[3].metric("Solo Sheet", totales.get('pis_solo_sheet', 0),
                    "⚠️" if totales.get('pis_solo_sheet') else None,
                    delta_color="inverse")
    cols[4].metric("Solo Odoo", totales.get('pis_solo_odoo', 0))

    st.markdown("---")

    sheet_only = alertas.get('alertas_sheet_pero_no_odoo', [])
    if sheet_only:
        st.markdown("##### 📋 PIs en Sheet pero no en tránsito-Odoo activo")
        df_so = pd.DataFrame(sheet_only)
        if 'eta' in df_so.columns:
            df_so['eta'] = pd.to_datetime(df_so['eta'], errors='coerce')

        sin_po = df_so[df_so.get('categoria') == 'SIN_PO_ODOO']
        recibidos = df_so[df_so.get('categoria') == 'YA_RECIBIDO']
        otros = df_so[~df_so.get('categoria').isin(['SIN_PO_ODOO', 'YA_RECIBIDO'])]

        if not sin_po.empty:
            st.error(f"🔴 **{len(sin_po)} PI(s) SIN PO en Odoo** — acción requerida")
            st.dataframe(sin_po[['pi', 'skus', 'unidades', 'eta', 'razon']],
                          hide_index=True, width='stretch')
        if not recibidos.empty:
            st.warning(f"🟡 **{len(recibidos)} PI(s) ya recibido(s) en Odoo** — sugerir a Martín mover a 'EN BODEGA'")
            st.dataframe(recibidos[['pi', 'skus', 'unidades', 'eta', 'razon']],
                          hide_index=True, width='stretch')
        if not otros.empty:
            st.info(f"ℹ️ **{len(otros)} PI(s) en otro estado**")
            st.dataframe(otros[['pi', 'skus', 'unidades', 'eta', 'razon']],
                          hide_index=True, width='stretch')
    else:
        st.success("✅ Todos los PIs del Sheet están en el extract Odoo activo.")

    odoo_only = alertas.get('info_odoo_pero_no_sheet', [])
    if odoo_only:
        st.markdown("##### ℹ️ PIs en Odoo pero no en Sheet")
        st.caption("Embarques que el agente creó en Odoo pero el Sheet de Martín aún no refleja.")
        st.dataframe(pd.DataFrame(odoo_only), hide_index=True, width='stretch')

    warn = alertas.get('warn_qty_difieren', [])
    if warn:
        st.markdown("##### ⚖️ Cantidades por SKU difieren entre fuentes")
        st.caption("Mismo PI+SKU con qty distinta en Odoo vs Sheet. Probable error de parsing decimal o carga manual.")
        df_w = pd.DataFrame(warn)
        st.dataframe(df_w, hide_index=True, width='stretch')


def render():
    with st.sidebar:
        st.markdown("### 🚢 **COMEX**")
        st.caption("Embarques en tránsito")
        st.markdown("---")
        if st.button("🔄 Refrescar", width='stretch', type="primary", key="comex_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("🚢 COMEX — Embarques en tránsito")
    df = _cargar_transito()
    df_val, val_resumen = _cargar_validacion_odoo()
    df_dim, resumen_dim = _cargar_dimensiones()

    if COMEX_RESUMEN.exists():
        try:
            r = json.load(open(COMEX_RESUMEN, encoding='utf-8'))
            fuente = r.get('fuente', 'odoo')
            fuente_label = ("purchase.order Topwill (Odoo) — receipt_status != 'full'"
                             if fuente == 'odoo' else
                             "sheet 'Importaciones UnionX Integrada' (Martín)")
            st.caption(f"🕒 Generado: {r.get('generado_en','')[:19]} · Fuente: {fuente_label}")
        except Exception:
            pass

    if df.empty:
        st.warning("⏳ Sin datos. Correr `python extract_comex_desde_odoo.py`")
        return

    # Banner de alertas Sheet vs Odoo (sale antes de los tabs para visibilidad)
    alertas = _cargar_alertas_comex()
    if alertas and alertas.get('alertas_sheet_pero_no_odoo'):
        sin_po = [a for a in alertas['alertas_sheet_pero_no_odoo']
                   if a.get('categoria') == 'SIN_PO_ODOO']
        recibidos = [a for a in alertas['alertas_sheet_pero_no_odoo']
                      if a.get('categoria') == 'YA_RECIBIDO']
        if sin_po:
            pis = ', '.join(a['pi'] for a in sin_po)
            st.error(f"⚠️ **{len(sin_po)} PI(s) en Drive Sheet sin PO en Odoo** ({pis}) — "
                      "requieren acción (flete Vicente / precosteo / carga manual). Detalle en tab '🚨 Alertas'.")
        if recibidos:
            pis = ', '.join(a['pi'] for a in recibidos)
            st.warning(f"📦 **{len(recibidos)} PI(s) ya recibidos según Odoo** ({pis}) pero Martín "
                       "los mantiene en tránsito en su Sheet. Sugerir mover a 'EN BODEGA'.")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Resumen", "📋 Por PI / embarque", "📦 Detalle SKUs",
        "📐 Volumen / Pallets", "🚨 Alertas Sheet vs Odoo"
    ])
    with tab1:
        _tab_resumen(df, val_resumen)
    with tab2:
        _tab_por_pi(df, val_resumen)
    with tab3:
        _tab_detalle_skus(df)
    with tab4:
        _tab_volumen_pallets(df_dim, resumen_dim)
    with tab5:
        _tab_alertas(alertas)
