"""Vista General Ventas — KPIs YoY + tendencia mensual/diaria + por canal + top SKUs."""
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views.shared import (
    cached_canales, cached_diaria, cached_kpis, cached_mensual, cached_top_skus,
    fmt_int, fmt_money, fmt_pct,
    render_ventas_filters_top, render_dashboard_actions_sidebar, render_health_header,
    kpi_card, COLOR_VENTA, COLOR_MARGEN, COLOR_COSTO, COLOR_NEGATIVO,
)


def render():
    render_health_header("📊 Dashboard Ventas UnionX")
    render_dashboard_actions_sidebar(prefix="ventas_gen")

    f = render_ventas_filters_top(prefix="ventas_gen")
    st.markdown("---")

    c1, c2 = st.columns([2, 3])
    with c1:
        hoy = datetime.now().date()
        # Default: mes actual desde día 1 hasta hoy. Si hoy es día 1 el rango
        # default es solo día 1 (con su data); el usuario puede cambiar.
        ini_default = hoy.replace(day=1)
        fin_default = hoy
        rango = st.date_input(
            "Período de análisis (TY)",
            value=(ini_default, fin_default),
            max_value=hoy,
            format="YYYY-MM-DD",
            key="rango_general",
        )
    if isinstance(rango, tuple) and len(rango) == 2:
        desde, hasta = rango
    else:
        desde = ini_mes
        hasta = hoy
    desde_str = desde.strftime('%Y-%m-%d')
    hasta_str = hasta.strftime('%Y-%m-%d')

    with c2:
        st.write("")
        st.write("")
        st.caption(f"Comparado vs LY: {desde.replace(year=desde.year-1)} → {hasta.replace(year=hasta.year-1)}")

    # KPIs (filtros como dict)
    try:
        kpis = cached_kpis(desde_str, hasta_str, f)
    except Exception as e:
        st.error(f"Error: {e}")
        return

    ty = kpis['ty']
    ly = kpis['ly']
    var = kpis['var_pct']

    # KPIs estilo Contribución — TY arriba, LY + Δ abajo
    st.markdown("### KPIs Principales — Comparación YoY")
    st.markdown("---")

    def _color_delta(v):
        if v is None:
            return COLOR_NEGATIVO
        return COLOR_MARGEN if v >= 0 else COLOR_NEGATIVO

    def _delta_txt(v, ly_val=None):
        if v is None:
            return "—"
        signo = "+" if v >= 0 else ""
        if ly_val is not None:
            return f"{signo}{v}% vs LY"
        return f"{signo}{v}%"

    # Fila 1: TY (año actual)
    cols = st.columns(4)
    cols[0].markdown(kpi_card("Venta Bruta TY", fmt_money(ty['venta']),
                              _delta_txt(var['venta']), _color_delta(var['venta'])), unsafe_allow_html=True)
    cols[1].markdown(kpi_card("Margen Frontal TY", fmt_money(ty['margen']),
                              _delta_txt(var['margen']), _color_delta(var['margen'])), unsafe_allow_html=True)
    cols[2].markdown(kpi_card("% Margen TY", fmt_pct(ty['pct_margen']),
                              f"{var['pct_margen']:+.1f} pts vs LY" if var['pct_margen'] is not None else "—",
                              _color_delta(var['pct_margen'])), unsafe_allow_html=True)
    cols[3].markdown(kpi_card("Unidades TY", fmt_int(ty['unidades']),
                              _delta_txt(var['unidades']), _color_delta(var['unidades'])), unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # Fila 2: LY (año anterior)
    cols2 = st.columns(4)
    cols2[0].markdown(kpi_card("Venta Bruta LY", fmt_money(ly['venta']), "Año anterior", COLOR_VENTA), unsafe_allow_html=True)
    cols2[1].markdown(kpi_card("Margen Frontal LY", fmt_money(ly['margen']), "Año anterior", COLOR_MARGEN), unsafe_allow_html=True)
    cols2[2].markdown(kpi_card("% Margen LY", fmt_pct(ly['pct_margen']), "Año anterior", COLOR_MARGEN), unsafe_allow_html=True)
    cols2[3].markdown(kpi_card("Unidades LY", fmt_int(ly['unidades']), "Año anterior", COLOR_VENTA), unsafe_allow_html=True)

    st.divider()

    # Mensual
    st.subheader("📈 Evolución mensual: TY vs LY")
    mensual = cached_mensual()
    df_m = pd.DataFrame(mensual)
    df_m['mes_nombre'] = pd.Categorical(
        df_m['mes_nombre'],
        categories=['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'],
        ordered=True,
    )
    fig_m = go.Figure()
    fig_m.add_trace(go.Scatter(
        x=df_m['mes_nombre'], y=df_m['venta_ly'],
        name='LY', mode='lines+markers', line=dict(color='#bfbfbf', width=2),
        fill='tozeroy', fillcolor='rgba(140, 140, 140, 0.2)',
    ))
    fig_m.add_trace(go.Scatter(
        x=df_m['mes_nombre'], y=df_m['venta_ty'],
        name='TY', mode='lines+markers', line=dict(color='#1890ff', width=3),
        fill='tonexty', fillcolor='rgba(24, 144, 255, 0.3)',
    ))
    fig_m.update_layout(
        height=350, hovermode='x unified',
        yaxis=dict(tickformat=',.0f', title='Venta Bruta ($)'),
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    st.plotly_chart(fig_m, width='stretch')

    # Diaria
    st.subheader(f"📅 Tendencia diaria — {hasta.strftime('%B %Y')} vs LY")
    diaria = cached_diaria(hasta.year, hasta.month)
    df_d = pd.DataFrame(diaria)
    if len(df_d):
        fig_d = go.Figure()
        fig_d.add_trace(go.Scatter(
            x=df_d['dia'], y=df_d['venta_ly'],
            name='LY', mode='lines', line=dict(color='#8c8c8c', width=2, dash='dot'),
        ))
        fig_d.add_trace(go.Scatter(
            x=df_d['dia'], y=df_d['venta_ty'],
            name='TY', mode='lines+markers', line=dict(color='#1890ff', width=2),
        ))
        fig_d.update_layout(
            height=300, hovermode='x unified',
            xaxis=dict(title='Día del mes'),
            yaxis=dict(tickformat=',.0f', title='Venta Bruta ($)'),
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        st.plotly_chart(fig_d, width='stretch')

    st.divider()

    # Por canal / Top SKUs
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Por Canal (TY vs LY)")
        df_c = pd.DataFrame(cached_canales(desde_str, hasta_str, f))
        if len(df_c):
            df_c['Var Venta %'] = df_c['var_venta_pct'].apply(lambda v: f"{v:+.1f}%" if v is not None else '—')
            df_c['Venta TY'] = df_c['venta_ty'].apply(fmt_money)
            df_c['Venta LY'] = df_c['venta_ly'].apply(fmt_money)
            df_c['% Mg'] = df_c['pct_margen'].apply(lambda v: f"{v:.1f}%" if v is not None else '—')
            st.dataframe(
                df_c[['canal', 'Venta TY', 'Venta LY', 'Var Venta %', '% Mg']],
                hide_index=True, width='stretch', height=400,
            )
    with col_b:
        st.subheader("Top 20 SKUs")
        df_s = pd.DataFrame(cached_top_skus(desde_str, hasta_str, f, limit=20))
        if len(df_s):
            df_s['Var %'] = df_s['var_venta_pct'].apply(lambda v: f"{v:+.1f}%" if v is not None else '—')
            df_s['Venta TY'] = df_s['venta'].apply(fmt_money)
            df_s['% Mg'] = df_s['pct_margen'].apply(lambda v: f"{v}%" if v is not None else '—')
            st.dataframe(
                df_s[['sku', 'producto', 'Venta TY', 'Var %', '% Mg']],
                hide_index=True, width='stretch', height=400,
            )
