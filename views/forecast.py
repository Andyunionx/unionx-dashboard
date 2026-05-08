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
    st.plotly_chart(fig, use_container_width=True)


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
    st.plotly_chart(fig, use_container_width=True)

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
        st.dataframe(df_t[['Mes', 'Proyección', 'LY', 'Δ% vs LY', 'Tipo']], use_container_width=True, hide_index=True)

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
        st.plotly_chart(fig, use_container_width=True)
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
        st.plotly_chart(fig2, use_container_width=True)


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
    st.plotly_chart(fig, use_container_width=True)
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
        st.plotly_chart(fig_w, use_container_width=True)
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
        st.plotly_chart(fig_y, use_container_width=True)
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
            st.plotly_chart(fig_h, use_container_width=True)
            st.caption("Aporte de Cyber Day, CyberMonday, Black Friday, Día Madre/Padre, FFPP, Navidad y feriados Chile.")


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
    st.plotly_chart(fig, use_container_width=True)


# ============================================================
# Render principal
# ============================================================
def render():
    with st.sidebar:
        st.markdown("### 📈 **Forecast**")
        st.caption("Prophet + Holidays Chile")
        st.markdown("---")
        if st.button("🔄 Refrescar caché", use_container_width=True, type="primary", key="fc_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("📈 Forecast — Prophet + Holidays Chile")

    resumen = _cargar_resumen()
    fc_diario = _cargar_parquet('forecast_diario.parquet')
    fc_anual = _cargar_parquet('forecast_anual.parquet')
    fc_canal = _cargar_parquet('forecast_canal.parquet')
    df_comp = _cargar_parquet('forecast_componentes.parquet')

    if not resumen and fc_diario.empty:
        st.warning("⏳ Aún no hay forecasts. El cron diario corre 06:00 UTC. Manual: GitHub → Actions → 'Sync Forecast' → Run workflow.")
        return

    if resumen.get('generado_en'):
        st.caption(f"🕒 Generado: {resumen['generado_en'][:19]} · Eventos modelados: Cyber Day, CyberMonday, Black Friday, Día Madre/Padre, FFPP, Navidad + feriados Chile")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📅 Cierre del mes", "📊 30 / 60 / 90 días", "📆 Año", "🔬 Componentes", "📈 Por canal"])
    with tab1:
        _tab_cierre_mes(resumen, fc_diario)
    with tab2:
        _tab_horizontes(resumen, fc_diario)
    with tab3:
        _tab_anio(resumen, fc_anual)
    with tab4:
        _tab_componentes(df_comp)
    with tab5:
        _tab_canales(fc_canal)
