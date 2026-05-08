"""
Vista Forecast — proyección de venta vía Prophet (entrenado por GH Actions diario).

Lee parquets pre-computados:
- data/forecast/forecast_diario.parquet
- data/forecast/forecast_canal.parquet
- data/forecast/forecast_resumen.json
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views.shared import kpi_card, COLOR_VENTA, COLOR_MARGEN, COLOR_NEGATIVO, COLOR_NEUTRO


PROJECT_ROOT = Path(__file__).parent.parent
FC_DIR = PROJECT_ROOT / 'data' / 'forecast'


@st.cache_data(ttl=3600)
def _cargar_forecast_diario():
    p = FC_DIR / 'forecast_diario.parquet'
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df['ds'] = pd.to_datetime(df['ds'])
    return df


@st.cache_data(ttl=3600)
def _cargar_forecast_canal():
    p = FC_DIR / 'forecast_canal.parquet'
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df['ds'] = pd.to_datetime(df['ds'])
    return df


@st.cache_data(ttl=3600)
def _cargar_resumen():
    p = FC_DIR / 'forecast_resumen.json'
    if not p.exists():
        return {}
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def render():
    with st.sidebar:
        st.markdown("### 📈 **Forecast**")
        st.caption("Proyección con Prophet")
        st.markdown("---")
        if st.button("🔄 Refrescar caché", use_container_width=True, type="primary", key="fc_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("📈 Forecast — Proyección con Prophet")
    st.caption("Modelo entrenado diariamente con histórico completo · GH Actions cron 06:00 UTC")

    resumen = _cargar_resumen()
    fc_diario = _cargar_forecast_diario()

    if not resumen and fc_diario.empty:
        st.warning("⏳ Aún no hay forecasts generados. El primer GH Actions corre a las 06:00 UTC. "
                   "También podés disparar manual: GitHub → Actions → 'Sync Forecast' → Run workflow.")
        return

    # ===== KPIs proyección fin de mes =====
    if resumen:
        st.markdown("### Proyección fin de mes")
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

        color_proy = COLOR_MARGEN
        if pct_vs_ly is not None:
            if pct_vs_ly < -10:
                color_proy = COLOR_NEGATIVO
            elif pct_vs_ly < 0:
                color_proy = '#EA580C'

        cols[2].markdown(kpi_card(
            "Proyección fin de mes",
            f"${proyeccion/1e6:.1f}M",
            f"{pct_vs_ly:+.1f}% vs LY" if pct_vs_ly is not None else "Sin LY",
            color_proy,
        ), unsafe_allow_html=True)

        if venta_ly:
            cols[3].markdown(kpi_card(
                "LY mismo mes completo",
                f"${venta_ly/1e6:.1f}M",
                "Referencia LY",
                COLOR_NEUTRO,
            ), unsafe_allow_html=True)

        st.caption(f"Generado: {resumen.get('generado_en', '')[:19]} · Mes: {resumen.get('mes', '')}")
        st.divider()

    # ===== Forecast diario total =====
    if not fc_diario.empty:
        st.markdown("### Forecast diario — próximos 60 días")

        hoy = datetime.now().date()
        # Separar histórico (fitted) vs futuro
        df_hist = fc_diario[fc_diario['ds'].dt.date <= hoy].copy()
        df_fut = fc_diario[fc_diario['ds'].dt.date > hoy].copy()

        fig = go.Figure()
        # Banda confianza futuro
        if not df_fut.empty:
            fig.add_trace(go.Scatter(
                x=df_fut['ds'], y=df_fut['yhat_upper'],
                mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip',
            ))
            fig.add_trace(go.Scatter(
                x=df_fut['ds'], y=df_fut['yhat_lower'],
                mode='lines', line=dict(width=0), fill='tonexty',
                fillcolor='rgba(30,64,175,0.15)', name='Banda confianza 80%',
            ))
            fig.add_trace(go.Scatter(
                x=df_fut['ds'], y=df_fut['yhat'],
                mode='lines', line=dict(color='#1E40AF', width=3, dash='dash'),
                name='Forecast',
            ))
        if not df_hist.empty:
            fig.add_trace(go.Scatter(
                x=df_hist['ds'], y=df_hist['yhat'],
                mode='lines', line=dict(color='#94A3B8', width=2),
                name='Modelo (histórico fitted)',
            ))

        fig.update_layout(
            height=420,
            xaxis=dict(title='Fecha'),
            yaxis=dict(title='Venta diaria ($)', tickformat=',.0f'),
            margin=dict(t=20, b=40, l=60, r=20),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            hovermode='x unified',
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("La línea punteada azul es el forecast. La banda celeste es el intervalo de confianza al 80%.")

        st.divider()

    # ===== Forecast por canal =====
    fc_canal = _cargar_forecast_canal()
    if not fc_canal.empty:
        st.markdown("### Forecast por canal — próximos 30 días")
        canales = sorted(fc_canal['canal'].unique().tolist())
        canal_sel = st.selectbox("Elegir canal", canales, key="fc_canal_sel")
        df_c = fc_canal[fc_canal['canal'] == canal_sel].copy()

        if not df_c.empty:
            total_proyectado = df_c['yhat'].sum()
            st.metric(f"Proyección {canal_sel} próximos 30 días", f"${total_proyectado/1e6:.1f}M")

            fig_c = go.Figure()
            fig_c.add_trace(go.Scatter(
                x=df_c['ds'], y=df_c['yhat_upper'],
                mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip',
            ))
            fig_c.add_trace(go.Scatter(
                x=df_c['ds'], y=df_c['yhat_lower'],
                mode='lines', line=dict(width=0), fill='tonexty',
                fillcolor='rgba(16,185,129,0.15)', name='Confianza 80%',
            ))
            fig_c.add_trace(go.Scatter(
                x=df_c['ds'], y=df_c['yhat'],
                mode='lines+markers', line=dict(color='#10B981', width=2.5),
                name=f'Forecast {canal_sel}',
            ))
            fig_c.update_layout(
                height=380,
                xaxis=dict(title='Fecha'),
                yaxis=dict(title='Venta diaria ($)', tickformat=',.0f'),
                margin=dict(t=20, b=40, l=60, r=20),
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            )
            st.plotly_chart(fig_c, use_container_width=True)

            with st.expander("📋 Tabla forecast por día"):
                df_show = df_c[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].copy()
                df_show['ds'] = df_show['ds'].dt.strftime('%Y-%m-%d')
                df_show.columns = ['Fecha', 'Forecast', 'Mín (80%)', 'Máx (80%)']
                for c in ['Forecast', 'Mín (80%)', 'Máx (80%)']:
                    df_show[c] = df_show[c].apply(lambda v: f"${v:,.0f}")
                st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)
