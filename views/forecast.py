"""
Vista Forecast — proyección de venta vía Prophet (entrenado por GH Actions diario).

Tabs:
1. Cierre del mes — proyección al último día del mes en curso
2. 30 / 60 / 90 días — KPIs por horizonte + serie diaria
3. Año — proyección 12 meses con tabla mensual + LY
4. Componentes — trend, weekly, yearly, holidays (diagnóstico Prophet)

Lee parquets pre-computados:
- data/forecast/forecast_diario.parquet (90d)
- data/forecast/forecast_anual.parquet (365d)
- data/forecast/forecast_canal.parquet
- data/forecast/forecast_componentes.parquet
- data/forecast/forecast_resumen.json
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views.shared import kpi_card, COLOR_VENTA, COLOR_MARGEN, COLOR_NEGATIVO, COLOR_NEUTRO


PROJECT_ROOT = Path(__file__).parent.parent
FC_DIR = PROJECT_ROOT / 'data' / 'forecast'


@st.cache_data(ttl=3600)
def _cargar_parquet(nombre: str) -> pd.DataFrame:
    p = FC_DIR / nombre
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if 'ds' in df.columns:
        df['ds'] = pd.to_datetime(df['ds'])
    return df


@st.cache_data(ttl=3600)
def _cargar_resumen() -> dict:
    p = FC_DIR / 'forecast_resumen.json'
    if not p.exists():
        return {}
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def _color_pct(pct: float | None) -> str:
    if pct is None:
        return COLOR_NEUTRO
    if pct < -10:
        return COLOR_NEGATIVO
    if pct < 0:
        return '#EA580C'
    return COLOR_MARGEN


def _fmt_pct(pct: float | None) -> str:
    return f"{pct:+.1f}% vs LY" if pct is not None else "Sin LY"


# ============================================================
# TAB 1 — Cierre del mes
# ============================================================
def _tab_cierre_mes(resumen: dict, fc_diario: pd.DataFrame):
    if not resumen:
        st.warning("Sin datos de proyección. Ejecutar el cron de forecast.")
        return

    venta_actual = resumen.get('venta_actual_mes', 0)
    venta_pend = resumen.get('venta_pendiente_estimada', 0)
    proyeccion = resumen.get('proyeccion_mes', 0)
    venta_ly = resumen.get('venta_ly_mes_completo', 0)
    pct_vs_ly = resumen.get('pct_vs_ly')

    cols = st.columns(4)
    cols[0].markdown(kpi_card(
        "Venta acumulada mes",
        f"${venta_actual/1e6:.1f}M",
        f"{resumen.get('dias_actuales', 0)} días corridos",
        COLOR_VENTA,
    ), unsafe_allow_html=True)
    cols[1].markdown(kpi_card(
        "Forecast pendiente",
        f"${venta_pend/1e6:.1f}M",
        f"{resumen.get('dias_pendientes', 0)} días por venir",
        COLOR_NEUTRO,
    ), unsafe_allow_html=True)
    cols[2].markdown(kpi_card(
        "Proyección fin de mes",
        f"${proyeccion/1e6:.1f}M",
        _fmt_pct(pct_vs_ly),
        _color_pct(pct_vs_ly),
    ), unsafe_allow_html=True)
    if venta_ly:
        cols[3].markdown(kpi_card(
            "LY mismo mes completo",
            f"${venta_ly/1e6:.1f}M",
            "Referencia LY",
            COLOR_NEUTRO,
        ), unsafe_allow_html=True)

    if fc_diario.empty:
        return

    # Chart 90 días con banda de confianza
    st.markdown("##### Proyección diaria — próximos 90 días")
    hoy = datetime.now().date()
    df_hist = fc_diario[fc_diario['ds'].dt.date <= hoy].copy()
    df_fut = fc_diario[fc_diario['ds'].dt.date > hoy].copy()

    fig = go.Figure()
    if not df_fut.empty:
        fig.add_trace(go.Scatter(x=df_fut['ds'], y=df_fut['yhat_upper'], mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=df_fut['ds'], y=df_fut['yhat_lower'], mode='lines', line=dict(width=0), fill='tonexty',
                                  fillcolor='rgba(30,64,175,0.15)', name='Banda 80%'))
        fig.add_trace(go.Scatter(x=df_fut['ds'], y=df_fut['yhat'], mode='lines', line=dict(color='#1E40AF', width=3, dash='dash'), name='Forecast'))
    if not df_hist.empty:
        fig.add_trace(go.Scatter(x=df_hist['ds'], y=df_hist['yhat'], mode='lines', line=dict(color='#94A3B8', width=2), name='Modelo (fitted)'))

    fig.update_layout(
        height=380, xaxis=dict(title='Fecha'), yaxis=dict(title='Venta diaria ($)', tickformat=',.0f'),
        margin=dict(t=20, b=40, l=60, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1), hovermode='x unified',
    )
    st.plotly_chart(fig, width='stretch')


# ============================================================
# TAB 2 — Horizontes 30 / 60 / 90 días
# ============================================================
def _tab_horizontes(resumen: dict, fc_diario: pd.DataFrame):
    horizontes = resumen.get('horizontes', {})
    if not horizontes:
        st.warning("Sin datos de horizontes. Re-ejecutar el cron.")
        return

    cols = st.columns(3)
    for i, h in enumerate(['30d', '60d', '90d']):
        d = horizontes.get(h, {})
        proy = d.get('proyeccion', 0)
        ly = d.get('venta_ly_mismo_rango', 0)
        pct = d.get('pct_vs_ly')
        cols[i].markdown(kpi_card(
            f"Próximos {h}",
            f"${proy/1e6:.1f}M",
            f"LY ${ly/1e6:.1f}M · {_fmt_pct(pct)}",
            _color_pct(pct),
        ), unsafe_allow_html=True)

    if fc_diario.empty:
        return

    # Selector de horizonte
    st.markdown("##### Detalle del horizonte")
    horizonte_sel = st.radio("Ventana", ['30 días', '60 días', '90 días'], horizontal=True, index=1, key='fc_h_radio')
    n_dias = int(horizonte_sel.split()[0])

    hoy = datetime.now().date()
    df_h = fc_diario[(fc_diario['ds'].dt.date > hoy) & (fc_diario['ds'].dt.date <= hoy + timedelta(days=n_dias))].copy()

    if df_h.empty:
        st.info("Sin datos para este horizonte")
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_h['ds'], y=df_h['yhat_upper'], mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=df_h['ds'], y=df_h['yhat_lower'], mode='lines', line=dict(width=0), fill='tonexty',
                              fillcolor='rgba(16,185,129,0.15)', name='Banda 80%'))
    fig.add_trace(go.Scatter(x=df_h['ds'], y=df_h['yhat'], mode='lines+markers', line=dict(color='#10B981', width=2.5),
                              marker=dict(size=4), name='Forecast'))
    fig.update_layout(
        height=360, xaxis=dict(title='Fecha'), yaxis=dict(title='Venta diaria ($)', tickformat=',.0f'),
        margin=dict(t=20, b=40, l=60, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1), hovermode='x unified',
    )
    st.plotly_chart(fig, width='stretch')

    # KPIs derivados
    promedio_diario = float(df_h['yhat'].mean())
    mejor_dia = df_h.loc[df_h['yhat'].idxmax()]
    peor_dia = df_h.loc[df_h['yhat'].idxmin()]
    cols2 = st.columns(3)
    cols2[0].metric("Promedio diario", f"${promedio_diario/1e6:.2f}M")
    cols2[1].metric("Mejor día proyectado", f"${mejor_dia['yhat']/1e6:.2f}M", f"{mejor_dia['ds'].strftime('%a %d-%b')}")
    cols2[2].metric("Peor día proyectado", f"${peor_dia['yhat']/1e6:.2f}M", f"{peor_dia['ds'].strftime('%a %d-%b')}")


# ============================================================
# TAB 3 — Año
# ============================================================
def _tab_anio(resumen: dict, fc_anual: pd.DataFrame):
    anio = resumen.get('anio_proyeccion', {})
    if not anio:
        st.warning("Sin proyección anual. Re-ejecutar el cron.")
        return

    venta_ytd = anio.get('venta_ytd', 0)
    proy_resto = anio.get('proyeccion_resto_anio', 0)
    proy_anio = anio.get('proyeccion_anio_completo', 0)
    venta_ly = anio.get('venta_anio_ly', 0)
    pct = anio.get('pct_anio_vs_ly')
    año_actual = resumen.get('anio', datetime.now().year)

    cols = st.columns(4)
    cols[0].markdown(kpi_card(
        f"Venta YTD {año_actual}",
        f"${venta_ytd/1e6:.0f}M",
        "Acumulado del año",
        COLOR_VENTA,
    ), unsafe_allow_html=True)
    cols[1].markdown(kpi_card(
        "Forecast resto del año",
        f"${proy_resto/1e6:.0f}M",
        "Proyección Prophet",
        COLOR_NEUTRO,
    ), unsafe_allow_html=True)
    cols[2].markdown(kpi_card(
        f"Proyección {año_actual} completo",
        f"${proy_anio/1e6:.0f}M",
        _fmt_pct(pct),
        _color_pct(pct),
    ), unsafe_allow_html=True)
    cols[3].markdown(kpi_card(
        f"Año LY ({año_actual - 1})",
        f"${venta_ly/1e6:.0f}M",
        "Referencia",
        COLOR_NEUTRO,
    ), unsafe_allow_html=True)

    # Tabla mensual
    tabla = anio.get('tabla_mensual', [])
    if tabla:
        st.markdown("##### Tabla mensual proyectada")
        df_t = pd.DataFrame(tabla)
        df_t['Mes'] = df_t['mes_nombre']
        df_t['Proyección'] = df_t['proyeccion'].apply(lambda v: f"${v/1e6:,.0f}M")
        df_t['LY'] = df_t['venta_ly'].apply(lambda v: f"${v/1e6:,.0f}M" if v > 0 else '—')
        df_t['Δ% vs LY'] = df_t['pct_vs_ly'].apply(lambda v: f"{v:+.1f}%" if v is not None else '—')
        df_t['Tipo'] = df_t['tipo'].map({'real': '✅ Real', 'mixto': '🔄 En curso', 'forecast': '📈 Forecast'})
        st.dataframe(df_t[['Mes', 'Proyección', 'LY', 'Δ% vs LY', 'Tipo']], width='stretch', hide_index=True)

        # Chart barras mes a mes (proyección vs LY)
        fig = go.Figure()
        meses = [r['mes_nombre'] for r in tabla]
        proys = [r['proyeccion'] / 1e6 for r in tabla]
        lys = [r['venta_ly'] / 1e6 for r in tabla]
        colors = ['#10B981' if r['tipo'] == 'real' else '#1E40AF' if r['tipo'] == 'forecast' else '#EA580C' for r in tabla]
        fig.add_trace(go.Bar(x=meses, y=lys, name=f'LY ({año_actual - 1})', marker_color='#94A3B8', opacity=0.6))
        fig.add_trace(go.Bar(x=meses, y=proys, name=f'Proy {año_actual}', marker_color=colors))
        fig.update_layout(
            barmode='group', height=380, yaxis=dict(title='Venta (M$)', tickformat=',.0f'),
            margin=dict(t=20, b=40, l=60, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        st.plotly_chart(fig, width='stretch')
        st.caption("🟢 Real (mes cerrado) · 🟠 En curso (real + forecast) · 🔵 Forecast puro")

    # Línea anual con banda
    if not fc_anual.empty:
        st.markdown("##### Proyección diaria — 365 días forward")
        hoy = datetime.now().date()
        df_h = fc_anual[fc_anual['ds'].dt.date <= hoy]
        df_f = fc_anual[fc_anual['ds'].dt.date > hoy]
        fig2 = go.Figure()
        if not df_f.empty:
            fig2.add_trace(go.Scatter(x=df_f['ds'], y=df_f['yhat_upper'], mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip'))
            fig2.add_trace(go.Scatter(x=df_f['ds'], y=df_f['yhat_lower'], mode='lines', line=dict(width=0), fill='tonexty',
                                       fillcolor='rgba(99,102,241,0.15)', name='Banda 80%'))
            fig2.add_trace(go.Scatter(x=df_f['ds'], y=df_f['yhat'], mode='lines', line=dict(color='#6366F1', width=2.5, dash='dash'), name='Forecast'))
        if not df_h.empty:
            fig2.add_trace(go.Scatter(x=df_h['ds'], y=df_h['yhat'], mode='lines', line=dict(color='#94A3B8', width=1.5), name='Histórico fitted'))
        fig2.update_layout(
            height=380, xaxis=dict(title='Fecha'), yaxis=dict(title='Venta diaria ($)', tickformat=',.0f'),
            margin=dict(t=20, b=40, l=60, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1), hovermode='x unified',
        )
        st.plotly_chart(fig2, width='stretch')


# ============================================================
# TAB 4 — Componentes Prophet
# ============================================================
def _tab_componentes(df_comp: pd.DataFrame):
    if df_comp.empty:
        st.info("Aún no hay componentes Prophet. Re-ejecutar el cron de forecast.")
        return

    st.markdown("Diagnóstico del modelo: descomposición de la serie en sus partes.")

    # Trend
    st.markdown("##### Tendencia (Trend)")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_comp['ds'], y=df_comp['trend'], mode='lines', line=dict(color='#1E40AF', width=2.5), name='Trend'))
    fig.update_layout(height=240, margin=dict(t=10, b=30, l=60, r=20),
                      yaxis=dict(title='Venta base ($)', tickformat=',.0f'),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, width='stretch')
    st.caption("Crecimiento orgánico del negocio sin estacionalidad ni eventos.")

    # Weekly
    if 'weekly' in df_comp.columns:
        st.markdown("##### Patrón semanal")
        df_w = df_comp[['ds', 'weekly']].copy()
        df_w['dow'] = df_w['ds'].dt.day_name()
        order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        df_w_avg = df_w.groupby('dow')['weekly'].mean().reindex(order).reset_index()
        df_w_avg['dow_es'] = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
        fig_w = go.Figure(go.Bar(x=df_w_avg['dow_es'], y=df_w_avg['weekly'],
                                  marker_color=['#10B981' if v >= 0 else '#DC2626' for v in df_w_avg['weekly']]))
        fig_w.update_layout(height=240, margin=dict(t=10, b=30, l=60, r=20),
                             yaxis=dict(title='Efecto sobre venta ($)', tickformat=',.0f'),
                             paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_w, width='stretch')
        st.caption("Cuánto suma o resta cada día de la semana respecto al promedio.")

    # Yearly
    if 'yearly' in df_comp.columns:
        st.markdown("##### Patrón anual (estacionalidad)")
        df_y = df_comp[['ds', 'yearly']].copy()
        df_y['dia_anio'] = df_y['ds'].dt.dayofyear
        df_y_avg = df_y.groupby('dia_anio')['yearly'].mean().reset_index()
        # Convertir día del año a fecha de referencia para tooltip
        df_y_avg['fecha_ref'] = pd.to_datetime('2025-01-01') + pd.to_timedelta(df_y_avg['dia_anio'] - 1, unit='D')
        fig_y = go.Figure()
        fig_y.add_trace(go.Scatter(x=df_y_avg['fecha_ref'], y=df_y_avg['yearly'],
                                    mode='lines', line=dict(color='#EA580C', width=2.5), fill='tozeroy',
                                    fillcolor='rgba(234,88,12,0.15)', name='Yearly'))
        fig_y.update_layout(height=260, margin=dict(t=10, b=30, l=60, r=20),
                             xaxis=dict(title='Día del año', tickformat='%b'),
                             yaxis=dict(title='Efecto sobre venta ($)', tickformat=',.0f'),
                             paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_y, width='stretch')
        st.caption("Picos ≈ Cyber Day (jun), Día Madre (may), CyberMonday (oct), Black Friday (nov), Navidad (dic).")

    # Holidays
    if 'holidays' in df_comp.columns:
        st.markdown("##### Eventos especiales (holidays)")
        df_h = df_comp[df_comp['holidays'].abs() > 0][['ds', 'holidays']].sort_values('ds')
        if not df_h.empty:
            fig_h = go.Figure(go.Bar(x=df_h['ds'], y=df_h['holidays'],
                                      marker_color=['#10B981' if v >= 0 else '#DC2626' for v in df_h['holidays']]))
            fig_h.update_layout(height=240, margin=dict(t=10, b=30, l=60, r=20),
                                 yaxis=dict(title='Boost del evento ($)', tickformat=',.0f'),
                                 paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_h, width='stretch')
            st.caption("Aporte de Cyber Day, CyberMonday, Black Friday, Día Madre/Padre, FFPP, Navidad y feriados Chile.")


# ============================================================
# TAB Jerarquia / SKU — desagregacion del forecast multi-nivel
# ============================================================
def _tab_jerarquia(fc_skus: pd.DataFrame, fc_marca_canal: pd.DataFrame,
                    fc_canal_jerar: pd.DataFrame, fc_categoria: pd.DataFrame,
                    fc_tipo_negocio: pd.DataFrame, df_comp_sku: pd.DataFrame,
                    meta_skus: dict):
    if fc_skus.empty:
        st.info("⏳ Forecast SKU x canal aun no generado. Correr extract_forecast_skus.py")
        return

    st.caption(f"🕒 Generado: {meta_skus.get('generado_en', '?')[:19]} · "
                f"{meta_skus.get('modelos_entrenados', 0)} modelos Prophet "
                f"({meta_skus.get('skus_unicos', 0)} SKUs × {meta_skus.get('canales_unicos', 0)} canales)")

    # Selector de nivel de desagregacion
    nivel = st.radio("Nivel de desagregacion",
                      ["Total", "Linea de negocio", "Canal", "Categoria", "Marca x Canal", "SKU"],
                      horizontal=True, key="fc_nivel")

    if nivel == "Total":
        df = fc_skus.groupby('ds', as_index=False)[['yhat', 'yhat_lower', 'yhat_upper']].sum()
        venta_total = df['yhat'].sum()
        st.metric(f"Proyeccion total proximos {len(df)} dias", f"${venta_total/1e6:.1f}M (unidades)")
        _chart_forecast(df, 'Total bottom-up')

    elif nivel == "Linea de negocio":
        if fc_tipo_negocio.empty:
            st.info("Sin datos de linea de negocio")
            return
        opciones = sorted([x for x in fc_tipo_negocio['tipo_negocio'].unique() if x])
        sel = st.selectbox("Linea de negocio", opciones, key="fc_tn")
        df = fc_tipo_negocio[fc_tipo_negocio['tipo_negocio'] == sel]
        st.metric(f"Proyeccion {sel}", f"${df['yhat'].sum()/1e6:.1f}M (unid)")
        _chart_forecast(df, sel)

    elif nivel == "Canal":
        if fc_canal_jerar.empty:
            return
        opciones = sorted(fc_canal_jerar['canal'].unique())
        sel = st.selectbox("Canal", opciones, key="fc_canal_jerar_sel")
        df = fc_canal_jerar[fc_canal_jerar['canal'] == sel]
        st.metric(f"Proyeccion {sel}", f"${df['yhat'].sum()/1e6:.1f}M (unid)")
        _chart_forecast(df, sel)

    elif nivel == "Categoria":
        if fc_categoria.empty:
            return
        opciones = sorted([x for x in fc_categoria['categoria_padre'].unique() if x])
        sel = st.selectbox("Categoria padre", opciones, key="fc_cat_sel")
        df = fc_categoria[fc_categoria['categoria_padre'] == sel]
        st.metric(f"Proyeccion {sel}", f"${df['yhat'].sum()/1e6:.1f}M (unid)")
        _chart_forecast(df, sel)

    elif nivel == "Marca x Canal":
        if fc_marca_canal.empty:
            return
        cols = st.columns(2)
        canal_sel = cols[0].selectbox("Canal", sorted(fc_marca_canal['canal'].unique()), key="fc_mc_canal")
        marcas = sorted([x for x in fc_marca_canal[fc_marca_canal['canal']==canal_sel]['marca'].unique() if x])
        marca_sel = cols[1].selectbox("Marca", marcas, key="fc_mc_marca")
        df = fc_marca_canal[(fc_marca_canal['canal']==canal_sel) & (fc_marca_canal['marca']==marca_sel)]
        st.metric(f"{marca_sel} en {canal_sel}", f"${df['yhat'].sum()/1e6:.2f}M (unid)")
        _chart_forecast(df, f"{marca_sel} - {canal_sel}")

    else:  # SKU
        skus_canales = fc_skus[['sku', 'canal']].drop_duplicates()
        cols = st.columns(2)
        canal_sel = cols[0].selectbox("Canal", sorted(skus_canales['canal'].unique()), key="fc_sku_canal")
        sub = skus_canales[skus_canales['canal'] == canal_sel]
        sku_sel = cols[1].selectbox(f"SKU ({len(sub)} disponibles)",
                                       sorted(sub['sku'].unique()), key="fc_sku_sku")

        df = fc_skus[(fc_skus['sku']==sku_sel) & (fc_skus['canal']==canal_sel)].copy()
        if df.empty:
            return

        producto = (df.iloc[0].get('producto') or '?')[:60]
        marca = df.iloc[0].get('marca') or '?'
        st.markdown(f"**SKU {sku_sel}** · {producto} · _{marca}_")
        col_kpi = st.columns(3)
        col_kpi[0].metric("Total proyectado (unid)", f"{df['yhat'].sum():.0f}")
        col_kpi[1].metric("Promedio diario", f"{df['yhat'].mean():.1f}")
        col_kpi[2].metric("Mejor dia", f"{df['yhat'].max():.0f}",
                           f"{df.loc[df['yhat'].idxmax(), 'ds'].strftime('%d-%b')}")

        _chart_forecast(df, f"SKU {sku_sel} en {canal_sel}")

        # Componentes explicables del SKU x canal
        if not df_comp_sku.empty:
            comp = df_comp_sku[(df_comp_sku['sku']==sku_sel) & (df_comp_sku['canal']==canal_sel)]
            if not comp.empty:
                st.markdown("##### Componentes del forecast (descomposicion Prophet)")
                # Sumar contribucion de cada componente sobre el periodo proyectado
                future_only = comp[comp['ds'] > pd.Timestamp.now()]
                if not future_only.empty:
                    descomp = {}
                    for c in ['trend', 'weekly', 'yearly', 'holidays',
                                'tuvo_stock', 'descuento_efectivo', 'promo_activa']:
                        if c in future_only.columns:
                            descomp[c] = float(future_only[c].sum())
                    if descomp:
                        df_d = pd.DataFrame([
                            {'componente': k, 'aporte': v} for k, v in descomp.items()
                        ]).sort_values('aporte', ascending=True)
                        fig = go.Figure(go.Bar(
                            x=df_d['aporte'], y=df_d['componente'],
                            orientation='h',
                            marker_color=['#10B981' if v >= 0 else '#DC2626' for v in df_d['aporte']],
                        ))
                        fig.update_layout(
                            height=280, margin=dict(t=10, b=30, l=140, r=20),
                            xaxis=dict(title='Aporte total al forecast (unid)'),
                            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                        )
                        st.plotly_chart(fig, width='stretch')
                        st.caption("Cuantas unidades aporta cada componente al forecast del periodo. Verde suma, rojo resta.")


def _chart_forecast(df: pd.DataFrame, titulo: str):
    """Helper: chart forecast con banda de confianza."""
    if df.empty:
        return
    fig = go.Figure()
    if 'yhat_upper' in df.columns:
        fig.add_trace(go.Scatter(x=df['ds'], y=df['yhat_upper'], mode='lines',
                                  line=dict(width=0), showlegend=False, hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=df['ds'], y=df['yhat_lower'], mode='lines',
                                  line=dict(width=0), fill='tonexty',
                                  fillcolor='rgba(99,102,241,0.15)', name='Banda 80%'))
    fig.add_trace(go.Scatter(x=df['ds'], y=df['yhat'], mode='lines+markers',
                              line=dict(color='#1E40AF', width=2.5), name=titulo))
    fig.update_layout(
        height=360, xaxis=dict(title='Fecha'), yaxis=dict(title='Forecast', tickformat=',.0f'),
        margin=dict(t=20, b=40, l=60, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        hovermode='x unified',
    )
    st.plotly_chart(fig, width='stretch')


# ============================================================
# TAB 5 — Por canal (mantenemos)
# ============================================================
def _tab_canales(fc_canal: pd.DataFrame):
    if fc_canal.empty:
        st.info("Sin forecast por canal disponible.")
        return
    canales = sorted(fc_canal['canal'].unique().tolist())
    canal_sel = st.selectbox("Canal", canales, key="fc_canal_sel")
    df_c = fc_canal[fc_canal['canal'] == canal_sel].copy()
    if df_c.empty:
        return

    total = df_c['yhat'].sum()
    st.metric(f"Proyección {canal_sel} próximos {len(df_c)} días", f"${total/1e6:.1f}M")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_c['ds'], y=df_c['yhat_upper'], mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=df_c['ds'], y=df_c['yhat_lower'], mode='lines', line=dict(width=0), fill='tonexty',
                              fillcolor='rgba(16,185,129,0.15)', name='Confianza 80%'))
    fig.add_trace(go.Scatter(x=df_c['ds'], y=df_c['yhat'], mode='lines+markers', line=dict(color='#10B981', width=2.5),
                              name=f'Forecast {canal_sel}'))
    fig.update_layout(height=360, xaxis=dict(title='Fecha'), yaxis=dict(title='Venta diaria ($)', tickformat=',.0f'),
                      margin=dict(t=20, b=40, l=60, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
    st.plotly_chart(fig, width='stretch')


# ============================================================
# TAB Validation (MAPE backtest)
# ============================================================
def _tab_validation(df_val: pd.DataFrame, summary: dict):
    if df_val.empty:
        st.info("⏳ Sin validation. Correr extract_forecast_validation.py.")
        return

    if summary:
        st.caption(f"🕒 Generado: {summary.get('generado_en','?')[:19]} · "
                    f"{summary.get('pares_con_mape', 0)} pares con MAPE")

    cols = st.columns(4)
    cols[0].metric("MAPE mediana", f"{summary.get('mape_pct_p50', 0):.0f}%",
                    "menor = mejor")
    cols[1].metric("MAPE p75", f"{summary.get('mape_pct_p75', 0):.0f}%")
    cols[2].metric("Sesgo global", f"{summary.get('sesgo_global_pct', 0):+.1f}%",
                    "venta predicha vs real")
    cols[3].metric("Pares evaluados", f"{summary.get('pares_validados', 0)}")

    st.markdown("##### Distribucion del MAPE por SKU x canal")
    df_clean = df_val.dropna(subset=['mape_pct'])
    fig = go.Figure(go.Histogram(x=df_clean['mape_pct'].clip(upper=200), nbinsx=40,
                                  marker_color='#1E40AF'))
    fig.update_layout(height=280, xaxis=dict(title='MAPE % (clipped at 200)'),
                       yaxis=dict(title='Pares (sku,canal)'),
                       margin=dict(t=20, b=40, l=60, r=20),
                       paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, width='stretch')

    st.markdown("##### Top 20 mejores y peores predicciones")
    cols = st.columns(2)
    cols[0].markdown("**Mejores (MAPE bajo):**")
    cols[0].dataframe(
        df_clean.nsmallest(20, 'mape_pct')[['sku', 'canal', 'mape_pct', 'venta_real_test', 'venta_pred_test', 'sesgo']],
        width='stretch', hide_index=True,
    )
    cols[1].markdown("**Peores (MAPE alto):**")
    cols[1].dataframe(
        df_clean.nlargest(20, 'mape_pct')[['sku', 'canal', 'mape_pct', 'venta_real_test', 'venta_pred_test', 'sesgo']],
        width='stretch', hide_index=True,
    )

    st.caption("MAPE = error % promedio. Sesgo positivo = sobre-estimamos. "
                "Con 1 año de historia y SKUs con poca venta, MAPE > 50% es esperable.")


# ============================================================
# TAB Pricing & Basket (elasticidad + complementariedad)
# ============================================================
def _tab_pricing_basket(df_elast_cat: pd.DataFrame, df_elast_sku: pd.DataFrame,
                        df_basket: pd.DataFrame):
    sub_tabs = st.tabs(["💰 Elasticidad por categoria", "📦 Elasticidad por SKU",
                         "🧺 Market basket (productos juntos)"])

    with sub_tabs[0]:
        if df_elast_cat.empty:
            st.info("Sin elasticidad. Correr extract_elasticidad_basket.py")
        else:
            st.markdown("Si bajo precio 10%, la venta sube |elasticidad| × 10% (modelo log-log).")
            df_show = df_elast_cat.copy()
            df_show = df_show.sort_values('elasticidad')
            fig = go.Figure(go.Bar(
                x=df_show['elasticidad'], y=df_show['categoria_padre'],
                orientation='h',
                marker_color=['#DC2626' if v < -0.5 else '#EA580C' if v < 0 else '#94A3B8' for v in df_show['elasticidad']],
            ))
            fig.update_layout(height=600, margin=dict(t=10, b=30, l=180, r=20),
                                xaxis=dict(title='Elasticidad-precio (negativo = elastica, baja precio sube venta)'),
                                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, width='stretch')
            st.caption("🟥 muy elasticas (precio sensible) · 🟧 elasticas suaves · ⬜ inelasticas/positivas (baja calidad de regresion o efecto Veblen)")
            with st.expander("📋 Tabla completa"):
                st.dataframe(df_show, width='stretch', hide_index=True)

    with sub_tabs[1]:
        if df_elast_sku.empty:
            st.info("Sin elasticidades por SKU.")
        else:
            st.markdown(f"**{len(df_elast_sku)} SKU x canal** con elasticidad calculada")
            df_show = df_elast_sku.sort_values('elasticidad')
            cols = st.columns(2)
            cols[0].markdown("**Mas elasticos (oportunidad de promo):**")
            cols[0].dataframe(df_show.head(15)[['sku', 'canal', 'elasticidad', 'r2', 'n_obs']],
                               width='stretch', hide_index=True)
            cols[1].markdown("**Menos elasticos (precio firme posible):**")
            cols[1].dataframe(df_show.tail(15)[['sku', 'canal', 'elasticidad', 'r2', 'n_obs']],
                               width='stretch', hide_index=True)

    with sub_tabs[2]:
        if df_basket.empty:
            st.info("Sin market basket. Correr extract_elasticidad_basket.py")
        else:
            st.markdown(f"**{len(df_basket)} pares de SKUs** comprados juntos en mismo pedido")
            st.caption("Lift > 1 = mas frecuente que lo esperado por azar. Confidence A→B = % pedidos con A que tambien tienen B")

            cols = st.columns(2)
            min_pedidos = cols[0].number_input("Min pedidos juntos", min_value=2, value=5, key="bsk_min")
            min_lift = cols[1].number_input("Min lift", min_value=1.0, value=2.0, step=0.5, key="bsk_lift")
            df_filt = df_basket[(df_basket['n_pedidos_juntos'] >= min_pedidos) & (df_basket['lift'] >= min_lift)]
            df_filt = df_filt.sort_values('lift', ascending=False).head(50)
            st.dataframe(
                df_filt[['sku_a', 'sku_b', 'n_pedidos_juntos', 'lift', 'confidence_a_to_b', 'confidence_b_to_a']],
                width='stretch', hide_index=True,
            )


# ============================================================
# TAB MinT (jerarquia reconciliada)
# ============================================================
def _tab_mint(df_recon: pd.DataFrame, mint_meta: dict):
    if df_recon.empty:
        st.info("⏳ Sin reconciliacion MinT.")
        return
    st.caption(f"🕒 Metodo: {mint_meta.get('metodo','?')} · {mint_meta.get('n_total_nodos',0)} nodos coherentes")

    nivel_sel = st.selectbox("Nivel jerarquico",
                              sorted(df_recon['nivel'].unique()), key="mint_nivel")
    df_nivel = df_recon[df_recon['nivel'] == nivel_sel]

    if nivel_sel == 'TOTAL':
        df_nodo = df_nivel
        st.metric(f"Total reconciliado 60d", f"{df_nodo['yhat'].sum():.0f} unid")
    else:
        nodos = sorted(df_nivel['nombre'].unique())
        sel = st.selectbox(f"Nodo en {nivel_sel}", nodos, key="mint_nodo")
        df_nodo = df_nivel[df_nivel['nombre'] == sel]
        st.metric(f"{sel} reconciliado 60d", f"{df_nodo['yhat'].sum():.0f} unid")

    if not df_nodo.empty:
        df_nodo = df_nodo.sort_values('ds')
        fig = go.Figure(go.Scatter(x=df_nodo['ds'], y=df_nodo['yhat'], mode='lines+markers',
                                    line=dict(color='#6366F1', width=2.5)))
        fig.update_layout(height=320, margin=dict(t=20, b=40, l=60, r=20),
                           yaxis=dict(title='Forecast (unid)', tickformat=',.0f'),
                           paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, width='stretch')

    st.caption("Todos los niveles suman exactamente — coherencia garantizada.")


# ============================================================
# TAB Demanda por evento (Fase 2: bottom-up SKU x canal anchored)
# ============================================================
def _tab_demanda_evento(df_dem: pd.DataFrame, df_skus_anchor: pd.DataFrame, reco: dict):
    if df_dem.empty:
        st.info("⏳ Sin demanda por evento. Correr extract_forecast_skus_anchored.py")
        return

    st.caption("Demanda esperada por **SKU × evento** = forecast Prophet base × boost(elasticidad×descuento) × lift basket. "
                "Stock futuro asumido disponible (la brecha contra stock = señal de compra).")

    # Reconciliacion summary
    if reco:
        cols = st.columns(4)
        cols[0].metric("Bottom-up SKUs", f"${reco.get('bottom_up_skus_anchored_$', 0)/1e6:.0f}M",
                        f"{reco.get('rango_dias', 0)} días")
        if reco.get('total_anchored_mismo_rango_$'):
            cols[1].metric("TOTAL anchored mismo rango", f"${reco['total_anchored_mismo_rango_$']/1e6:.0f}M")
            cols[2].metric("Cobertura SKUs top", f"{reco.get('cobertura_estimada_pct', 0):.0f}%",
                            "del TOTAL anchored")
            gap = reco.get('gap_pct', 0)
            cols[3].metric("Gap (cola larga)", f"{gap:+.1f}%",
                            "esperado negativo (top SKUs vs total)")

    st.divider()

    # Selector evento
    eventos_disp = sorted(df_dem['evento'].dropna().unique().tolist())
    if not eventos_disp:
        st.info("Sin eventos en horizonte")
        return

    sel_evento = st.selectbox("Evento", eventos_disp, key='dem_evento')
    df_e = df_dem[df_dem['evento'] == sel_evento].copy()

    if df_e.empty:
        return

    st.markdown(f"##### Demanda esperada en **{sel_evento}**")
    cols = st.columns(3)
    cols[0].metric("SKUs en evento", df_e['sku'].nunique())
    cols[1].metric("Unidades proyectadas", f"{df_e['unidades_proyectadas'].sum():,.0f}")
    boost_total = (df_e['unidades_proyectadas'].sum() / df_e['unidades_base_sin_boost'].sum() - 1) * 100 if df_e['unidades_base_sin_boost'].sum() > 0 else 0
    cols[2].metric("Boost total promedio", f"+{boost_total:.0f}%",
                    "vs Prophet sin anclas")

    # Top 30 SKUs por demanda
    top30 = df_e.groupby(['sku', 'producto', 'marca', 'categoria_padre', 'canal'], as_index=False, dropna=False).agg(
        unidades=('unidades_proyectadas', 'sum'),
        boost=('boost_promedio', 'mean'),
        lift_pct=('boost_lift_extra_pct', 'mean'),
    ).sort_values('unidades', ascending=False).head(30)
    top30['boost'] = top30['boost'].round(2).astype(str) + 'x'
    top30['lift_pct'] = top30['lift_pct'].round(1).astype(str) + '%'

    st.markdown("##### Top 30 SKUs × canal por demanda en este evento")
    st.dataframe(
        top30.rename(columns={
            'sku': 'SKU', 'producto': 'Producto', 'marca': 'Marca',
            'categoria_padre': 'Categoria', 'canal': 'Canal',
            'unidades': 'Unidades', 'boost': 'Boost evento', 'lift_pct': 'Δ% vs base',
        }),
        width='stretch', hide_index=True, height=600,
    )


# ============================================================
# Render principal
# ============================================================
def render():
    with st.sidebar:
        st.markdown("### 📈 **Forecast**")
        st.caption("Prophet + Holidays Chile")
        st.markdown("---")
        if st.button("🔄 Refrescar caché", width='stretch', type="primary", key="fc_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("📈 Forecast — Prophet + Holidays Chile")

    resumen = _cargar_resumen()
    fc_diario = _cargar_parquet('forecast_diario.parquet')
    fc_anual = _cargar_parquet('forecast_anual.parquet')
    fc_canal = _cargar_parquet('forecast_canal.parquet')
    df_comp = _cargar_parquet('forecast_componentes.parquet')
    fc_skus = _cargar_parquet('forecast_skus.parquet')
    fc_marca_canal = _cargar_parquet('forecast_jerarquico_marca_canal.parquet')
    fc_canal_jerar = _cargar_parquet('forecast_jerarquico_canal.parquet')
    fc_categoria = _cargar_parquet('forecast_jerarquico_categoria.parquet')
    fc_tipo_negocio = _cargar_parquet('forecast_jerarquico_tipo_negocio.parquet')
    df_comp_sku = _cargar_parquet('forecast_componentes_skus.parquet')
    df_validation = _cargar_parquet('forecast_validation.parquet')
    df_recon = _cargar_parquet('forecast_reconciled.parquet')
    df_elast_cat = _cargar_parquet('elasticidad_categoria.parquet')
    df_elast_sku = _cargar_parquet('elasticidad_sku.parquet')
    df_basket = _cargar_parquet('market_basket.parquet')
    meta_skus_path = FC_DIR / 'metadata_skus.json'
    meta_skus = json.load(open(meta_skus_path, encoding='utf-8')) if meta_skus_path.exists() else {}
    val_summary_path = FC_DIR / 'validation_summary.json'
    val_summary = json.load(open(val_summary_path, encoding='utf-8')) if val_summary_path.exists() else {}
    mint_meta_path = FC_DIR / 'mint_metadata.json'
    mint_meta = json.load(open(mint_meta_path, encoding='utf-8')) if mint_meta_path.exists() else {}

    if not resumen and fc_diario.empty:
        st.warning("⏳ Aún no hay forecasts. El cron diario corre 06:00 UTC. Manual: GitHub → Actions → 'Sync Forecast' → Run workflow.")
        return

    if resumen.get('generado_en'):
        st.caption(f"🕒 Generado: {resumen['generado_en'][:19]} · Eventos modelados: Cyber Day, CyberMonday, Black Friday, Día Madre/Padre, FFPP, Navidad + feriados Chile")

    df_dem_evento = _cargar_parquet('forecast_demanda_por_evento.parquet')
    df_skus_anchored = _cargar_parquet('forecast_skus_anchored.parquet')
    reco_path = FC_DIR / 'reconciliation_bottom_up.json'
    reco = json.load(open(reco_path, encoding='utf-8')) if reco_path.exists() else {}

    tabs = st.tabs([
        "📅 Cierre del mes", "📊 30 / 60 / 90 días", "📆 Año",
        "🔬 Componentes", "📈 Por canal", "🧬 Jerarquía / SKU",
        "🎯 Precision (MAPE)", "💰 Pricing & Basket", "🔗 MinT reconciliado",
        "🛒 Demanda por evento (SKU)",
    ])
    with tabs[0]:
        _tab_cierre_mes(resumen, fc_diario)
    with tabs[1]:
        _tab_horizontes(resumen, fc_diario)
    with tabs[2]:
        _tab_anio(resumen, fc_anual)
    with tabs[3]:
        _tab_componentes(df_comp)
    with tabs[4]:
        _tab_canales(fc_canal)
    with tabs[5]:
        _tab_jerarquia(fc_skus, fc_marca_canal, fc_canal_jerar, fc_categoria,
                        fc_tipo_negocio, df_comp_sku, meta_skus)
    with tabs[6]:
        _tab_validation(df_validation, val_summary)
    with tabs[7]:
        _tab_pricing_basket(df_elast_cat, df_elast_sku, df_basket)
    with tabs[8]:
        _tab_mint(df_recon, mint_meta)
    with tabs[9]:
        _tab_demanda_evento(df_dem_evento, df_skus_anchored, reco)
