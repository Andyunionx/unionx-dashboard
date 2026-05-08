"""
Resultados Generales — KPIs YoY + Evolución mensual + Mix por canal.

Fuente: Google Sheet 'Análisis de Resultados' (datos KAM crudos por mes/canal/KAM).
"""
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from views.contribucion_loader import cargar_hoja, parsear_columnas_numericas, fmt_pesos_M, fmt_pct


COLS_NUM = [
    'Venta KAM', 'Venta REAL KAM', 'Costo Venta KAM',
    'Margen Directo KAM', 'Comisión Venta KAM', 'Comisión Envío KAM',
    'Marketing KAM', 'Total Comisiones KAM', 'Resultado Contribución KAM',
]


def _kpi_card(label: str, value: str, sub: str = "", color: str = "blue") -> str:
    return f"""<div style="background:white;border-radius:12px;padding:16px 18px;text-align:center;
        box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #E2E8F0;height:100%;">
        <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;margin-bottom:4px;">{label}</div>
        <div style="font-size:1.5rem;font-weight:700;color:{color};line-height:1.2;">{value}</div>
        <div style="font-size:0.7rem;color:#94A3B8;margin-top:2px;">{sub}</div>
    </div>"""


def render():
    with st.sidebar:
        st.markdown("### 💼 **Contribución**")
        st.caption("Resultados Generales")
        st.markdown("---")
        if st.button("🔄 Refrescar Sheet", use_container_width=True, type="primary", key="cgen_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("📊 Análisis de Contribución")
    st.caption("UnionX — Dashboard BI · Fuente: 'Análisis de Resultados' · Cache 5 min · "
               "[Abrir Sheet](https://docs.google.com/spreadsheets/d/1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4/)")

    try:
        df = cargar_hoja("Análisis de Resultados")
    except Exception as e:
        st.error(f"❌ Error leyendo Sheet: {type(e).__name__}: {e}")
        return

    if df.empty:
        st.warning("Sin datos")
        return

    df = parsear_columnas_numericas(df, COLS_NUM)

    # Filtros sidebar
    with st.sidebar:
        st.markdown("##### Filtros")
        anios = sorted([int(a) if str(a).isdigit() else a for a in df['AÑO'].dropna().unique() if a])
        # Negocio
        negocios_opt = sorted([n for n in df['Negocio'].dropna().unique() if n])
        f_negocio = st.multiselect("Negocio", negocios_opt, default=[], key="cgen_neg")
        # Canal
        canales_opt = sorted([c for c in df['Canal'].dropna().unique() if c])
        f_canal = st.multiselect("Canal", canales_opt, default=[], key="cgen_canal")
        # KAM
        kams_opt = sorted([k for k in df['KAM'].dropna().unique() if k])
        f_kam = st.multiselect("KAM", kams_opt, default=[], key="cgen_kam")
        # Mes
        meses_opt = sorted([int(m) if str(m).isdigit() else m for m in df['Mes'].dropna().unique() if m])
        f_mes = st.multiselect("Mes", meses_opt, default=[], key="cgen_mes")

    # Aplicar filtros
    df_f = df.copy()
    if f_negocio:
        df_f = df_f[df_f['Negocio'].isin(f_negocio)]
    if f_canal:
        df_f = df_f[df_f['Canal'].isin(f_canal)]
    if f_kam:
        df_f = df_f[df_f['KAM'].isin(f_kam)]
    if f_mes:
        df_f = df_f[df_f['Mes'].astype(str).isin([str(m) for m in f_mes])]

    st.caption(f"Filas filtradas: {len(df_f):,}")

    # Calcular KPIs por año
    def _kpis_anio(df_a):
        return {
            'venta': df_a['Venta REAL KAM'].sum() if 'Venta REAL KAM' in df_a.columns else 0,
            'costo': df_a['Costo Venta KAM'].sum() if 'Costo Venta KAM' in df_a.columns else 0,
            'margen': df_a['Margen Directo KAM'].sum() if 'Margen Directo KAM' in df_a.columns else 0,
            'comisiones': df_a['Total Comisiones KAM'].sum() if 'Total Comisiones KAM' in df_a.columns else 0,
            'contrib': df_a['Resultado Contribución KAM'].sum() if 'Resultado Contribución KAM' in df_a.columns else 0,
        }

    df_2026 = df_f[df_f['AÑO'].astype(str).isin(['2026', '2.026'])]
    df_2025 = df_f[df_f['AÑO'].astype(str).isin(['2025', '2.025'])]

    k26 = _kpis_anio(df_2026)
    k25 = _kpis_anio(df_2025)

    def _pct_venta(metric, venta):
        return f"{metric/venta*100:.1f}% s/venta" if venta else "—"

    def _delta_yoy(actual, base):
        if not base or base == 0:
            return None, "—"
        delta = (actual - base) / abs(base) * 100
        signo = "+" if delta >= 0 else ""
        return delta, f"{signo}{delta:.1f}% vs 2025"

    # ===== KPIs PRINCIPALES =====
    st.markdown("### KPIs Principales — Comparación YoY")
    st.markdown("---")

    # Fila 1: año actual (2026)
    delta_v, delta_v_txt = _delta_yoy(k26['venta'], k25['venta'])
    color_v = '#1E40AF' if not delta_v else ('#16A34A' if delta_v >= 0 else '#DC2626')

    cols = st.columns(5)
    cols[0].markdown(_kpi_card("Venta 2026", fmt_pesos_M(k26['venta']), delta_v_txt, color_v), unsafe_allow_html=True)
    cols[1].markdown(_kpi_card("Costo 2026", fmt_pesos_M(k26['costo']), _pct_venta(k26['costo'], k26['venta']), '#EA580C'), unsafe_allow_html=True)
    cols[2].markdown(_kpi_card("Margen 2026", fmt_pesos_M(k26['margen']), _pct_venta(k26['margen'], k26['venta']), '#16A34A'), unsafe_allow_html=True)
    cols[3].markdown(_kpi_card("Comisiones 2026", fmt_pesos_M(k26['comisiones']), _pct_venta(k26['comisiones'], k26['venta']), '#DC2626'), unsafe_allow_html=True)
    cols[4].markdown(_kpi_card("Contribución 2026", fmt_pesos_M(k26['contrib']), _pct_venta(k26['contrib'], k26['venta']), '#16A34A'), unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # Fila 2: año anterior + deltas YoY
    delta_c, _ = _delta_yoy(k26['contrib'], k25['contrib'])
    color_dv = '#16A34A' if delta_v and delta_v >= 0 else '#DC2626'
    color_dc = '#16A34A' if delta_c and delta_c >= 0 else '#DC2626'
    delta_v_abs = (k26['venta'] - k25['venta'])
    delta_c_abs = (k26['contrib'] - k25['contrib'])

    cols2 = st.columns(5)
    cols2[0].markdown(_kpi_card("Venta 2025", fmt_pesos_M(k25['venta']), "", '#1E40AF'), unsafe_allow_html=True)
    cols2[1].markdown(_kpi_card("Margen 2025", fmt_pesos_M(k25['margen']), _pct_venta(k25['margen'], k25['venta']), '#16A34A'), unsafe_allow_html=True)
    cols2[2].markdown(_kpi_card("Contribución 2025", fmt_pesos_M(k25['contrib']), _pct_venta(k25['contrib'], k25['venta']), '#16A34A'), unsafe_allow_html=True)
    cols2[3].markdown(_kpi_card("Δ Venta YoY", fmt_pesos_M(delta_v_abs),
                                 f"{delta_v:+.1f}%" if delta_v is not None else "—", color_dv), unsafe_allow_html=True)
    cols2[4].markdown(_kpi_card("Δ Contribución YoY", fmt_pesos_M(delta_c_abs),
                                 f"{delta_c:+.1f}%" if delta_c is not None else "—", color_dc), unsafe_allow_html=True)

    st.divider()

    # ===== EVOLUCIÓN MENSUAL =====
    st.markdown("### Evolución Mensual YoY")

    col_m1, col_m2 = st.columns([3, 2])

    with col_m1:
        st.markdown("##### Venta (barras) y Contribución (líneas) por Mes")
        df_mes = df_f.copy()
        df_mes['Mes_int'] = pd.to_numeric(df_mes['Mes'], errors='coerce')
        df_mes = df_mes.dropna(subset=['Mes_int'])
        df_mes['Mes_int'] = df_mes['Mes_int'].astype(int)

        agg_mes = df_mes.groupby(['AÑO', 'Mes_int']).agg({
            'Venta REAL KAM': 'sum',
            'Resultado Contribución KAM': 'sum',
        }).reset_index()
        agg_mes['AÑO_str'] = agg_mes['AÑO'].astype(str).str.replace('.', '', regex=False)

        fig = go.Figure()
        # Barras Venta
        for anio in ['2025', '2026']:
            df_a = agg_mes[agg_mes['AÑO_str'] == anio]
            if len(df_a) > 0:
                fig.add_trace(go.Bar(
                    name=f'Venta {anio}', x=df_a['Mes_int'], y=df_a['Venta REAL KAM'],
                    marker_color='#94A3B8' if anio == '2025' else '#1E40AF',
                    yaxis='y',
                ))
        # Líneas Contribución
        for anio in ['2025', '2026']:
            df_a = agg_mes[agg_mes['AÑO_str'] == anio]
            if len(df_a) > 0:
                fig.add_trace(go.Scatter(
                    name=f'Contrib {anio}', x=df_a['Mes_int'], y=df_a['Resultado Contribución KAM'],
                    mode='lines+markers',
                    line=dict(color='#10B981' if anio == '2026' else '#CBD5E1', width=2.5),
                    yaxis='y2',
                ))

        fig.update_layout(
            barmode='group', height=380,
            xaxis=dict(title='Mes', dtick=1),
            yaxis=dict(title='Venta ($)', tickformat=',.0f'),
            yaxis2=dict(title='Contribución ($)', overlaying='y', side='right', tickformat=',.0f'),
            margin=dict(t=20, b=40, l=40, r=40),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_m2:
        st.markdown("##### Mix Venta 2026 por Canal (top 10)")
        df_mix = df_2026.groupby('Canal').agg({'Venta REAL KAM': 'sum'}).reset_index()
        df_mix = df_mix.sort_values('Venta REAL KAM', ascending=False).head(10)
        if len(df_mix):
            fig_mix = px.pie(
                df_mix, names='Canal', values='Venta REAL KAM', hole=0.5,
                color_discrete_sequence=px.colors.sequential.Blues_r,
            )
            fig_mix.update_layout(
                height=380, margin=dict(t=20, b=20, l=20, r=20),
                paper_bgcolor='rgba(0,0,0,0)',
                legend=dict(orientation='v', yanchor='middle', y=0.5, xanchor='left', x=1.05, font=dict(size=10)),
            )
            fig_mix.update_traces(textinfo='label+percent', textfont_size=11)
            st.plotly_chart(fig_mix, use_container_width=True)

    st.divider()

    # ===== TABLA DETALLE =====
    with st.expander("📋 Detalle filas (datos crudos filtrados)", expanded=False):
        cols_show = [c for c in [
            'AÑO', 'Mes', 'Trimestre', 'Negocio', 'Canal', 'KAM',
            'Venta REAL KAM', 'Costo Venta KAM', 'Margen Directo KAM',
            'Total Comisiones KAM', 'Resultado Contribución KAM',
        ] if c in df_f.columns]
        df_show = df_f[cols_show].copy()
        for c in ['Venta REAL KAM', 'Costo Venta KAM', 'Margen Directo KAM', 'Total Comisiones KAM', 'Resultado Contribución KAM']:
            if c in df_show.columns:
                df_show[c] = df_show[c].apply(fmt_pesos_M)
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)
