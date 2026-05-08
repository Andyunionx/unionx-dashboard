"""Vista General Ventas — KPIs YoY + tendencia mensual/diaria + por canal + top SKUs."""
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views._shared import (
    cached_canales, cached_diaria, cached_kpis, cached_mensual, cached_top_skus,
    fmt_int, fmt_money, fmt_pct, render_filters_sidebar, render_health_header,
)


def render():
    render_health_header("📊 Dashboard Ventas UnionX")
    f = render_filters_sidebar(prefix="ventas_gen")

    c1, c2 = st.columns([2, 3])
    with c1:
        hoy = datetime.now().date()
        ini_mes = hoy.replace(day=1)
        rango = st.date_input(
            "Período de análisis (TY)",
            value=(ini_mes, hoy),
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

    # KPIs
    try:
        kpis = cached_kpis(desde_str, hasta_str, f['canal'], f['marca'], f['categoria'], f['tipo_negocio'], f['kam'])
    except Exception as e:
        st.error(f"Error: {e}")
        return

    ty = kpis['ty']
    ly = kpis['ly']
    var = kpis['var_pct']
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Venta Bruta", fmt_money(ty['venta']),
                  delta=f"{var['venta']}% vs LY ({fmt_money(ly['venta'])})" if var['venta'] is not None else None,
                  help="Con IVA — comparable contra histórico")
    with col2:
        st.metric("Margen Frontal", fmt_money(ty['margen']),
                  delta=f"{var['margen']}% vs LY ({fmt_money(ly['margen'])})" if var['margen'] is not None else None,
                  help="Margen Front (sin descontar comisiones, logística, marketing)")
    with col3:
        st.metric("% Margen", fmt_pct(ty['pct_margen']),
                  delta=f"{var['pct_margen']:+.1f} pts vs LY" if var['pct_margen'] is not None else None,
                  help="vs Venta NETA sin IVA")
    with col4:
        st.metric("Unidades", fmt_int(ty['unidades']),
                  delta=f"{var['unidades']}% vs LY ({fmt_int(ly['unidades'])})" if var['unidades'] is not None else None)

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
    st.plotly_chart(fig_m, use_container_width=True)

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
        st.plotly_chart(fig_d, use_container_width=True)

    st.divider()

    # Por canal / Top SKUs
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Por Canal (TY vs LY)")
        df_c = pd.DataFrame(cached_canales(desde_str, hasta_str, f['canal'], f['marca'], f['categoria'], f['tipo_negocio'], f['kam']))
        if len(df_c):
            df_c['Var Venta %'] = df_c['var_venta_pct'].apply(lambda v: f"{v:+.1f}%" if v is not None else '—')
            df_c['Venta TY'] = df_c['venta_ty'].apply(fmt_money)
            df_c['Venta LY'] = df_c['venta_ly'].apply(fmt_money)
            df_c['% Mg'] = df_c['pct_margen'].apply(lambda v: f"{v:.1f}%" if v is not None else '—')
            st.dataframe(
                df_c[['canal', 'Venta TY', 'Venta LY', 'Var Venta %', '% Mg']],
                hide_index=True, use_container_width=True, height=400,
            )
    with col_b:
        st.subheader("Top 20 SKUs")
        df_s = pd.DataFrame(cached_top_skus(desde_str, hasta_str, f['canal'], f['marca'], f['categoria'], f['tipo_negocio'], f['kam'], 20))
        if len(df_s):
            df_s['Var %'] = df_s['var_venta_pct'].apply(lambda v: f"{v:+.1f}%" if v is not None else '—')
            df_s['Venta TY'] = df_s['venta'].apply(fmt_money)
            df_s['% Mg'] = df_s['pct_margen'].apply(lambda v: f"{v}%" if v is not None else '—')
            st.dataframe(
                df_s[['sku', 'producto', 'Venta TY', 'Var %', '% Mg']],
                hide_index=True, use_container_width=True, height=400,
            )
