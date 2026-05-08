"""Vista Semanal Ventas — análisis por semana del mes."""
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views.shared import (
    cached_semanal, fmt_int, fmt_money, render_filters_sidebar, render_health_header,
)


def render():
    render_health_header("📅 Vista Semanal — Ventas")
    f = render_filters_sidebar(prefix="ventas_sem")

    st.subheader("📅 Análisis semanal")
    c1, c2 = st.columns([1, 1])
    with c1:
        anio_sel = st.selectbox("Año", options=[2026, 2025, 2024], index=0, key="anio_sem")
    with c2:
        mes_sel = st.selectbox(
            "Mes",
            options=list(range(1, 13)),
            format_func=lambda m: ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                                    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'][m - 1],
            index=datetime.now().month - 1,
            key="mes_sem",
        )

    sem = cached_semanal(anio_sel, mes_sel, f['canal'], f['marca'], f['categoria'], f['tipo_negocio'], f['kam'])
    df_w = pd.DataFrame(sem)

    if not len(df_w):
        st.info("Sin datos para ese período.")
        return

    # KPIs totales del mes
    ty_v = df_w['venta_ty'].sum()
    ly_v = df_w['venta_ly'].sum()
    ty_m = df_w['margen_ty'].sum()
    ly_m = df_w['margen_ly'].sum()
    ty_u = df_w['unidades_ty'].sum()
    ly_u = df_w['unidades_ly'].sum()
    var_v = (ty_v - ly_v) / abs(ly_v) * 100 if ly_v else 0
    var_m = (ty_m - ly_m) / abs(ly_m) * 100 if ly_m else 0
    var_u = (ty_u - ly_u) / abs(ly_u) * 100 if ly_u else 0

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Venta Bruta del mes", fmt_money(ty_v),
                  delta=f"{var_v:+.1f}% vs LY ({fmt_money(ly_v)})")
    with c2:
        st.metric("Margen Frontal del mes", fmt_money(ty_m),
                  delta=f"{var_m:+.1f}% vs LY")
    with c3:
        st.metric("Unidades del mes", fmt_int(ty_u),
                  delta=f"{var_u:+.1f}% vs LY")

    st.divider()

    # Gráfico de barras semanales
    st.markdown("##### Comparativa semanal")
    fig_w = go.Figure()
    fig_w.add_trace(go.Bar(name='LY', x=df_w['label'], y=df_w['venta_ly'], marker_color='#bfbfbf'))
    fig_w.add_trace(go.Bar(name='TY', x=df_w['label'], y=df_w['venta_ty'], marker_color='#1890ff'))
    fig_w.update_layout(
        barmode='group', height=350, hovermode='x',
        yaxis=dict(tickformat=',.0f', title='Venta Bruta ($)'),
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    st.plotly_chart(fig_w, use_container_width=True)

    # Tabla detalle
    st.markdown("##### Detalle por semana")
    df_view = df_w.copy()
    df_view['Semana'] = df_view['label']
    df_view['Período'] = df_view['desde'] + ' → ' + df_view['hasta']
    df_view['Venta TY'] = df_view['venta_ty'].apply(fmt_money)
    df_view['Venta LY'] = df_view['venta_ly'].apply(fmt_money)
    df_view['Var %'] = df_view['var_venta_pct'].apply(lambda v: f"{v:+.1f}%" if v is not None else '—')
    df_view['Mg TY'] = df_view['margen_ty'].apply(fmt_money)
    df_view['Unid TY'] = df_view['unidades_ty'].apply(fmt_int)
    df_view['% Mg'] = (df_view['margen_ty'] / df_view['venta_neta_ty'].replace(0, 1) * 100).round(1).astype(str) + '%'
    st.dataframe(
        df_view[['Semana', 'Período', 'Venta TY', 'Venta LY', 'Var %', 'Mg TY', 'Unid TY', '% Mg']],
        hide_index=True, use_container_width=True,
    )
