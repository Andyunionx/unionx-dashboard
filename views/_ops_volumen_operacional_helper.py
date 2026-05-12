"""
Helper de visualización del volumen operacional proyectado.

Lee data/capacidad/volumen_operacional_diario.parquet + resumen.json
(generado por extract_volumen_operacional.py).

Muestra:
  - KPIs: pedidos/líneas/unidades total horizonte
  - Carga del equipo (% capacidad histórica P90)
  - Días de sobrecarga proyectados
  - Top semanas por volumen (planificación staff)
  - Gráfico diario con alertas semáforo
  - Insights: cuándo refuerzo, qué semanas bloquear vacaciones, etc.
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
VO_PARQUET = PROJECT_ROOT / 'data' / 'capacidad' / 'volumen_operacional_diario.parquet'
VO_RESUMEN = PROJECT_ROOT / 'data' / 'capacidad' / 'volumen_operacional_resumen.json'


@st.cache_data(ttl=900)
def _cargar() -> tuple[pd.DataFrame, dict]:
    df = pd.DataFrame()
    resumen = {}
    if VO_PARQUET.exists():
        df = pd.read_parquet(VO_PARQUET)
        df['fecha'] = pd.to_datetime(df['fecha'])
    if VO_RESUMEN.exists():
        try:
            resumen = json.load(open(VO_RESUMEN, encoding='utf-8'))
        except Exception:
            pass
    return df, resumen


def _color_carga(pct: float) -> str:
    if pct >= 110:
        return '#DC2626'
    if pct >= 90:
        return '#EA580C'
    if pct >= 70:
        return '#F59E0B'
    return '#16A34A'


def _kpi(label: str, value: str, sub: str = '', color: str = '#1F4E79') -> str:
    return f"""<div style="background:white;border-radius:12px;padding:16px 18px;text-align:center;
        box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #E2E8F0;height:100%;">
        <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;margin-bottom:4px;">{label}</div>
        <div style="font-size:1.5rem;font-weight:700;color:{color};line-height:1.2;">{value}</div>
        <div style="font-size:0.7rem;color:#94A3B8;margin-top:2px;">{sub}</div>
    </div>"""


def _generar_insights(df: pd.DataFrame, resumen: dict) -> list[dict]:
    insights = []
    cap = resumen.get('capacidad_pedidos_dia', 0)
    totales = resumen.get('totales_horizonte', {})
    pico = resumen.get('pico', {})
    primer_sob = resumen.get('primer_sobrecarga')

    dias_sob = totales.get('dias_sobrecarga', 0)
    dias_at = totales.get('dias_atencion', 0)

    # Sobrecarga proyectada
    if primer_sob:
        dias = (pd.to_datetime(primer_sob['fecha']).date() - datetime.now().date()).days
        if dias <= 14:
            insights.append({
                'tipo': '🔴 SOBRECARGA INMINENTE',
                'titulo': (f'Primer día de sobrecarga en {dias} días '
                            f'({primer_sob["fecha"]}) — '
                            f'{primer_sob["pedidos_a_procesar"]:.0f} pedidos vs cap {cap:.0f}/día'),
                'accion': (
                    "**Acción urgente esta semana:**\n"
                    "1. Confirmar disponibilidad de personal de refuerzo (extras, horas extra)\n"
                    "2. Pre-empacar pedidos B2B grandes en días de baja carga previos\n"
                    "3. Considerar adelantar despachos del fin de semana (cargar S+D al jueves/viernes)\n"
                    "4. Coordinar con couriers ventana de retiro extendida"
                ),
            })
        elif dias <= 30:
            insights.append({
                'tipo': '🟠 SOBRECARGA PRÓXIMA',
                'titulo': f'Primer pico de sobrecarga en {dias} días',
                'accion': (
                    "**Plan a 30 días:**\n"
                    "1. Bloquear vacaciones del equipo en esa ventana\n"
                    "2. Capacitar/incorporar staff temporal anticipado\n"
                    "3. Revisar slotting para los SKUs A esperados"
                ),
            })

    # Carga distribuida concentrada en pocas semanas
    top_sem = resumen.get('top_semanas_volumen', [])
    if top_sem and len(top_sem) >= 2:
        max_sem = top_sem[0]
        if max_sem.get('dias_sobrecarga', 0) > 0 or max_sem.get('dias_atencion', 0) > 1:
            insights.append({
                'tipo': '🔵 CONCENTRACIÓN SEMANAL',
                'titulo': (f"Semana {max_sem['semana']} pico: "
                            f"{max_sem['pedidos']:,} pedidos · "
                            f"{max_sem['dias_sobrecarga']}d sobrecarga + "
                            f"{max_sem['dias_atencion']}d atención"),
                'accion': (
                    "**Planificación staff:**\n"
                    "1. Reforzar equipo esa semana específica (turnos extra, freelance)\n"
                    "2. Pre-empacar pedidos masivos B2B 2 días antes\n"
                    "3. Avisar a Steven/COMEX para evitar recepciones en esos días"
                ),
            })

    # Si es laboral siguiente y carga alta
    df_lab = df[df['es_laboral']].copy()
    if not df_lab.empty:
        prox_5d = df_lab.head(5)
        carga_prox_avg = prox_5d['pct_carga_equipo'].mean()
        if carga_prox_avg > 90:
            insights.append({
                'tipo': '🟠 CARGA SEMANA EN CURSO',
                'titulo': f'Próximos 5 días laborales promedio {carga_prox_avg:.0f}% carga',
                'accion': (
                    "**Acción inmediata:**\n"
                    "1. Activar protocolo de día pico (turnos extendidos)\n"
                    "2. Priorizar pedidos urgentes/courier strict\n"
                    "3. Diferir pedidos B2B no críticos a semana siguiente"
                ),
            })

    # Sub-utilizado
    if dias_sob == 0 and dias_at == 0:
        max_pct = pico.get('pct_carga_equipo', 0)
        if max_pct < 60:
            insights.append({
                'tipo': '🟡 EQUIPO SUB-UTILIZADO',
                'titulo': f'Pico próximos 90d apenas {max_pct:.0f}% capacidad',
                'accion': (
                    "**Oportunidades:**\n"
                    "1. Reasignar tiempo a auditorías cycle counts más frecuentes\n"
                    "2. Re-slotting agresivo (ahora hay ventana sin presión)\n"
                    "3. Capacitación cruzada del equipo en estaciones poco usadas\n"
                    "4. Revisar dimensionamiento real del equipo (¿optimizable?)"
                ),
            })

    if not insights:
        insights.append({
            'tipo': '🟢 OPERACIÓN BALANCEADA',
            'titulo': f'{dias_sob} días sobrecarga · {dias_at} días atención en 90d',
            'accion': (
                "**Optimizaciones nice-to-have:**\n"
                "1. Mantener monitoreo diario · alertas activas funcionan\n"
                "2. Proyectar staff de refuerzo solo para los días marcados arriba"
            ),
        })

    return insights


def render_volumen_operacional():
    st.markdown("### 📊 Volumen operacional proyectado — necesidades del equipo")

    df, resumen = _cargar()
    if df.empty or not resumen:
        st.warning(
            "⏳ Sin datos. Correr `python extract_volumen_operacional.py` "
            "(o esperar al cron de `sync_forecast.yml` diario / `sync_comex.yml` cada 3h)."
        )
        return

    ratios = resumen.get('ratios_equipo', {})
    cap = resumen.get('capacidad_pedidos_dia', 0)
    st.caption(
        f"🕒 Generado: {resumen.get('generado_en','')[:19]} · "
        f"📊 **Modelo**: forecast venta diaria (Prophet anchored) "
        f"× ratio {ratios.get('uds_por_pedido',0):.2f} uds/pedido (histórico {ratios.get('n_dias_observados',0)}d) "
        f"= pedidos proyectados/día · "
        f"**Capacidad equipo P90**: {cap:.0f} pedidos/día (lo que pueden hacer en buen día)"
    )

    # KPIs
    t = resumen.get('totales_horizonte', {})
    pico = resumen.get('pico', {})
    cols = st.columns(4)
    cols[0].markdown(_kpi(
        "Pedidos próximos 90d",
        f"{t.get('pedidos_proyectados', 0):,}",
        f"{t.get('pedidos_proyectados', 0)/65:.0f}/día laboral promedio (~65 días)",
        '#1F4E79',
    ), unsafe_allow_html=True)
    cols[1].markdown(_kpi(
        "Líneas pickeadas 90d",
        f"{t.get('lineas_proyectadas', 0):,}",
        f"{ratios.get('lineas_por_pedido', 0):.2f} líneas/pedido",
        '#1F4E79',
    ), unsafe_allow_html=True)
    cols[2].markdown(_kpi(
        "Días sobrecarga (>110%)",
        f"{t.get('dias_sobrecarga', 0)}",
        f"+ {t.get('dias_atencion', 0)} días atención (90-110%)",
        '#DC2626' if t.get('dias_sobrecarga', 0) > 0 else '#16A34A',
    ), unsafe_allow_html=True)
    cols[3].markdown(_kpi(
        "Pico día próximos 90d",
        f"{pico.get('pedidos_a_procesar', 0):.0f} ped",
        f"{pico.get('pct_carga_equipo', 0):.0f}% carga · {pico.get('fecha','')[:10]}",
        _color_carga(pico.get('pct_carga_equipo', 0)),
    ), unsafe_allow_html=True)

    # Banner alerta
    primer_sob = resumen.get('primer_sobrecarga')
    if primer_sob:
        dias = (pd.to_datetime(primer_sob['fecha']).date() - datetime.now().date()).days
        st.error(
            f"🔴 **SOBRECARGA EN {dias} DÍAS** — {primer_sob['fecha']} con "
            f"{primer_sob['pedidos_a_procesar']:.0f} pedidos ({primer_sob['pct_carga_equipo']:.0f}% carga). "
            "Ver insights al final."
        )

    st.divider()

    # ─── GRÁFICO DIARIO ──────────────────────────────────────────────────
    st.markdown("##### 📈 Pedidos/día proyectados vs capacidad equipo")

    fig = go.Figure()
    # Capacidad
    fig.add_trace(go.Scatter(
        x=df['fecha'], y=[cap] * len(df),
        mode='lines', name=f'Capacidad equipo ({cap:.0f}/día)',
        line=dict(color='#CBD5E1', width=2, dash='dash'),
        hovertemplate='Capacidad P90: %{y:.0f}<extra></extra>',
    ))

    # Pedidos (laborales en barras, no laborales en gris)
    df_lab = df[df['es_laboral']]
    df_nolab = df[~df['es_laboral']]

    fig.add_trace(go.Bar(
        x=df_lab['fecha'], y=df_lab['pedidos_a_procesar'],
        name='Pedidos a procesar (laboral)',
        marker_color=df_lab['pct_carga_equipo'].apply(
            lambda v: '#DC2626' if v >= 110 else ('#EA580C' if v >= 90 else
                       ('#F59E0B' if v >= 70 else '#1F4E79'))
        ),
        hovertemplate='%{x|%a %d/%m}<br>Pedidos: %{y:.0f}<br>'
                       'Carga: %{customdata:.0f}%<extra></extra>',
        customdata=df_lab['pct_carga_equipo'],
    ))

    if not df_nolab.empty:
        fig.add_trace(go.Bar(
            x=df_nolab['fecha'], y=df_nolab['pedidos_proyectados'],
            name='Demanda S/D (acumula al lunes)',
            marker_color='#94A3B8',
            opacity=0.4,
            hovertemplate='%{x|%a %d/%m}<br>Demanda: %{y:.0f}<br>(no laboral)<extra></extra>',
        ))

    fig.add_hline(y=cap * 1.1, line=dict(color='#DC2626', width=1, dash='dot'),
                   annotation_text='110%', annotation_position='right')
    fig.add_hline(y=cap * 0.9, line=dict(color='#EA580C', width=1, dash='dot'),
                   annotation_text='90%', annotation_position='right')

    fig.update_layout(
        height=380, barmode='overlay',
        xaxis=dict(title='Fecha'),
        yaxis=dict(title='Pedidos/día'),
        margin=dict(t=20, b=40, l=60, r=20),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', y=1.05, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "🟦 OK · 🟡 carga alta (70-90%) · 🟠 atención (90-110%) · 🔴 sobrecarga (>110%) · "
        "Demanda S/D se acumula al lunes (bodega no opera fin de semana)"
    )

    st.divider()

    # ─── TOP SEMANAS ────────────────────────────────────────────────────
    top_sem = resumen.get('top_semanas_volumen', [])
    if top_sem:
        st.markdown("##### 📅 Top semanas por volumen (planificación staff)")
        df_sem = pd.DataFrame(top_sem)
        df_sem['pedidos'] = df_sem['pedidos'].apply(lambda v: f'{v:,}')
        df_sem['lineas'] = df_sem['lineas'].apply(lambda v: f'{v:,}')
        df_sem['unidades'] = df_sem['unidades'].apply(lambda v: f'{v:,}')
        df_sem['estado'] = df_sem.apply(
            lambda r: ('🔴 sobrecarga' if r['dias_sobrecarga'] > 0
                        else ('🟠 atención' if r['dias_atencion'] > 0 else '🟢 OK')),
            axis=1,
        )
        df_sem.columns = ['Semana', 'Pedidos', 'Líneas', 'Unidades',
                           'Días sobrecarga', 'Días atención', 'Estado']
        st.dataframe(df_sem, use_container_width=True, hide_index=True, height=280)

    st.divider()

    # ─── INSIGHTS ────────────────────────────────────────────────────────
    st.markdown("##### 💡 Insights & acciones")
    insights = _generar_insights(df, resumen)
    for ins in insights:
        if ins['tipo'].startswith('🔴'):
            st.error(f"**{ins['tipo']} — {ins['titulo']}**")
            st.markdown(ins['accion'])
        elif ins['tipo'].startswith('🟠'):
            st.warning(f"**{ins['tipo']} — {ins['titulo']}**")
            st.markdown(ins['accion'])
        elif ins['tipo'].startswith('🟡') or ins['tipo'].startswith('🔵'):
            st.info(f"**{ins['tipo']} — {ins['titulo']}**")
            st.markdown(ins['accion'])
        else:
            st.success(f"**{ins['tipo']} — {ins['titulo']}**")
            st.markdown(ins['accion'])

    st.divider()

    # ─── DETALLE DIARIO ─────────────────────────────────────────────────
    with st.expander("📋 Detalle diario (próximos 90 días)", expanded=False):
        df_show = df.copy()
        df_show['fecha'] = df_show['fecha'].dt.date
        df_show['dia'] = pd.to_datetime(df_show['fecha']).dt.strftime('%a').str.upper()
        df_show = df_show[['fecha', 'dia', 'pedidos_a_procesar', 'lineas_a_procesar',
                            'unidades_a_procesar', 'pct_carga_equipo', 'alerta',
                            'sku_distintos']]
        df_show.columns = ['Fecha', 'Día', 'Pedidos', 'Líneas', 'Unidades',
                            '% Carga', 'Estado', 'SKUs distintos']
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=420)
