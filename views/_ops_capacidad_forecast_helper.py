"""
Helper de visualización del forecast de capacidad bodega 90 días.

Lee data/capacidad/forecast_diario.parquet + forecast_resumen.json
(generado por extract_capacidad_forecast.py).

Incluye:
  - KPIs estado actual (ocupación %, m³ disp, pallets disp)
  - Gráfico Plotly: m³ ocupado vs capacidad + entradas (PIs) + salidas (forecast)
  - Tabla diaria con alertas semáforo
  - Insights automáticos de slotting/distribución según el escenario
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
FC_PARQUET = PROJECT_ROOT / 'data' / 'capacidad' / 'forecast_diario.parquet'
FC_RESUMEN = PROJECT_ROOT / 'data' / 'capacidad' / 'forecast_resumen.json'


@st.cache_data(ttl=900)
def _cargar_forecast() -> tuple[pd.DataFrame, dict]:
    df = pd.DataFrame()
    resumen = {}
    if FC_PARQUET.exists():
        df = pd.read_parquet(FC_PARQUET)
        df['fecha'] = pd.to_datetime(df['fecha'])
    if FC_RESUMEN.exists():
        try:
            resumen = json.load(open(FC_RESUMEN, encoding='utf-8'))
        except Exception:
            pass
    return df, resumen


def _color_pct(pct: float) -> str:
    if pct >= 100:
        return '#DC2626'
    if pct >= 90:
        return '#EA580C'
    if pct >= 70:
        return '#F59E0B'
    return '#16A34A'


def _kpi_card(label: str, value: str, sub: str = '', color: str = '#1F4E79') -> str:
    return f"""<div style="background:white;border-radius:12px;padding:16px 18px;text-align:center;
        box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #E2E8F0;height:100%;">
        <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;margin-bottom:4px;">{label}</div>
        <div style="font-size:1.5rem;font-weight:700;color:{color};line-height:1.2;">{value}</div>
        <div style="font-size:0.7rem;color:#94A3B8;margin-top:2px;">{sub}</div>
    </div>"""


def _generar_insights(df: pd.DataFrame, resumen: dict) -> list[dict]:
    """Genera insights de slotting/distribución basados en el escenario detectado."""
    insights = []
    cap = resumen.get('capacidad_bodega_m3', 0)
    estado = resumen.get('estado_actual', {})
    pico = resumen.get('pico_proyectado', {})
    minimo = resumen.get('minimo_proyectado', {})
    pct_hoy = estado.get('pct_ocupacion_hoy', 0)
    pct_pico = pico.get('pct_ocupacion', 0)
    pct_min = minimo.get('pct_ocupacion', 0)
    primer_critico = resumen.get('primer_critico')
    primer_atencion = resumen.get('primer_atencion')
    entrante = resumen.get('m3_total_entrante_horizonte', 0)
    saliente = resumen.get('m3_total_saliente_horizonte', 0)

    # 1. Saturación cercana
    if primer_critico:
        dias = (pd.to_datetime(primer_critico).date() - datetime.now().date()).days
        if dias <= 7:
            insights.append({
                'tipo': '🔴 CRÍTICO',
                'titulo': f'Bodega se llena en {dias} días ({primer_critico})',
                'accion': (
                    "**Acción urgente:**\n"
                    "1. Adelantar campañas/promos de SKUs sobrestockeados (liquidación)\n"
                    "2. Mover SKUs C (baja rotación) a bodega externa o consolidar fragmentos\n"
                    "3. Negociar con couriers tiempo extra de almacenaje en CD\n"
                    "4. Renegociar ETAs con Steven (delay de 1-2 semanas en próximos PIs)"
                ),
            })
        elif dias <= 30:
            insights.append({
                'tipo': '🟠 ALERTA',
                'titulo': f'Bodega proyecta llenarse en {dias} días',
                'accion': (
                    "**Plan a 30 días:**\n"
                    "1. Revisar slotting: consolidar fragmentos (ver sub-tab '🆓 Slots liberables')\n"
                    "2. Liquidar SKUs sin venta 60+ días\n"
                    "3. Pre-empacar pedidos B2B para liberar espacio fluido\n"
                    "4. Confirmar con Andrés capacidad real o revisar el cálculo (actualmente "
                    f"asumiendo {cap:,.0f} m³ totales)"
                ),
            })

    # 2. Sub-utilización
    if pct_hoy < 30 and pct_pico < 50:
        insights.append({
            'tipo': '🟡 EFICIENCIA',
            'titulo': f'Bodega sub-utilizada ({pct_hoy:.0f}% hoy, pico {pct_pico:.0f}%)',
            'accion': (
                "**Oportunidad de eficiencia:**\n"
                "1. Renegociar arriendo o sub-arrendar zona ociosa\n"
                "2. Recibir más volumen importable (adelantar PIs futuros)\n"
                "3. Consolidar bodegas si hay >1 ubicación → reducir costo logístico\n"
                "4. Re-slotting agresivo: TODOS los SKUs A en zona caliente cerca de packing"
            ),
        })

    # 3. Quiebre proyectado de stock
    if pct_min < 5:
        primer_quiebre = df[df['m3_ocupado'] < 50].iloc[0] if (df['m3_ocupado'] < 50).any() else None
        if primer_quiebre is not None:
            dias_q = (primer_quiebre['fecha'].date() - datetime.now().date()).days
            insights.append({
                'tipo': '🔴 RIESGO QUIEBRE',
                'titulo': f'Stock total proyecta quiebre en {dias_q} días ({primer_quiebre["fecha"].date()})',
                'accion': (
                    "**Plan de aprovisionamiento:**\n"
                    "1. Comparar forecast venta vs PIs en tránsito — está saliendo MÁS de lo "
                    f"que entra ({saliente:,.0f} m³ vs {entrante:,.0f} m³ próximos 90d)\n"
                    "2. Adelantar siguiente PI con Steven (transporte aéreo si es posible)\n"
                    "3. Revisar SKUs con quiebre crítico (sub-tab 'Stock Total' filtro 'CRÍTICO')\n"
                    "4. Si forecast es realista → necesario agregar PI grande en próximas 4 semanas"
                ),
            })

    # 4. Concentración temporal de entradas
    eventos = resumen.get('dias_con_entrada_transito', [])
    if eventos:
        df_ev = pd.DataFrame(eventos)
        df_ev['fecha'] = pd.to_datetime(df_ev['fecha'])
        # Detectar pico de entrada (>2x el promedio)
        avg_ent = df_ev['m3'].mean()
        picos_ent = df_ev[df_ev['m3'] > avg_ent * 2]
        if not picos_ent.empty:
            top = picos_ent.iloc[0]
            insights.append({
                'tipo': '🔵 PLANIFICACIÓN',
                'titulo': f'Entrada grande de {top["m3"]:,.0f} m³ el {top["fecha"].date()}',
                'accion': (
                    "**Preparar bodega para recepción:**\n"
                    f"1. Liberar al menos {top['m3']*1.2:,.0f} m³ con anticipación (buffer 20%)\n"
                    "2. Asignar slots cercanos a recepción para SKUs A esperados\n"
                    "3. Coordinar staff extra ese día para recepción/check-in\n"
                    "4. Revisar % cobertura volumen del PI (sub-tab COMEX → '📐 Volumen / Pallets')"
                ),
            })

    # 5. Sin alertas → proactivo
    if not insights:
        insights.append({
            'tipo': '🟢 OK',
            'titulo': f'Capacidad balanceada — pico {pct_pico:.0f}% en horizonte 90d',
            'accion': (
                "**Optimizaciones nice-to-have:**\n"
                "1. Re-slotting periódico de SKUs A para reducir OCT (sub-tab 'Slotting subóptimo')\n"
                "2. Revisar SKUs dormidas >30d (sub-tab 'Uso de posiciones') y liquidar\n"
                "3. Auditar volumen mal cargado en Odoo (excluidos del cálculo)"
            ),
        })

    return insights


def render_forecast_capacidad():
    """Render principal del forecast de capacidad bodega."""
    st.markdown("### 📥 Forecast de capacidad bodega — 90 días")

    df, resumen = _cargar_forecast()

    if df.empty or not resumen:
        st.warning(
            "⏳ Sin datos. Correr `python extract_capacidad_forecast.py` "
            "(o esperar al cron de `sync_comex.yml` que corre cada 3h)."
        )
        return

    # Header con metadata
    cap = resumen.get('capacidad_bodega_m3', 0)
    cap_fuente = resumen.get('capacidad_fuente', '')
    cap_pal = resumen.get('capacidad_pallets', 0)
    asunc = resumen.get('asunciones', {})

    st.caption(
        f"🕒 Generado: {resumen.get('generado_en','')[:19]} · "
        f"Capacidad: **{cap:,.0f} m³** ({cap_pal:,.0f} pallets) [{cap_fuente}] · "
        f"📐 Asunciones: posición = {asunc.get('m3_por_posicion', 1.8)} m³ "
        f"(1×1,2×1,5m), pallet apilable = {asunc.get('m3_por_pallet_apilable', 1.2)} m³"
    )

    # KPIs estado actual
    estado = resumen.get('estado_actual', {})
    pct_hoy = estado.get('pct_ocupacion_hoy', 0)
    color_hoy = _color_pct(pct_hoy)

    pico = resumen.get('pico_proyectado', {})
    minimo = resumen.get('minimo_proyectado', {})

    cols = st.columns(4)
    cols[0].markdown(_kpi_card(
        "Ocupación HOY",
        f"{pct_hoy:.0f}%",
        f"{estado.get('m3_ocupado_hoy', 0):,.0f} m³ / {cap:,.0f} m³",
        color_hoy,
    ), unsafe_allow_html=True)
    cols[1].markdown(_kpi_card(
        "Pallets disponibles HOY",
        f"{estado.get('pallets_disp_hoy', 0):,.0f}",
        f"de {cap_pal:,.0f} totales",
        '#16A34A',
    ), unsafe_allow_html=True)
    cols[2].markdown(_kpi_card(
        "Pico próximos 90d",
        f"{pico.get('pct_ocupacion', 0):.0f}%",
        f"{pico.get('m3_ocupado', 0):,.0f} m³ el {pico.get('fecha','')[:10]}",
        _color_pct(pico.get('pct_ocupacion', 0)),
    ), unsafe_allow_html=True)
    cols[3].markdown(_kpi_card(
        "Mínimo próximos 90d",
        f"{minimo.get('pct_ocupacion', 0):.0f}%",
        f"{minimo.get('m3_ocupado', 0):,.0f} m³ el {minimo.get('fecha','')[:10]}",
        '#DC2626' if minimo.get('pct_ocupacion', 0) < 10 else '#16A34A',
    ), unsafe_allow_html=True)

    # Banner con primer evento crítico
    if resumen.get('primer_critico'):
        dias = (pd.to_datetime(resumen['primer_critico']).date() - datetime.now().date()).days
        st.error(
            f"🔴 **BODEGA SE LLENA EN {dias} DÍAS** ({resumen['primer_critico']}) "
            "— ver insights al final"
        )
    elif resumen.get('primer_atencion'):
        dias = (pd.to_datetime(resumen['primer_atencion']).date() - datetime.now().date()).days
        st.warning(
            f"🟠 Atención: bodega supera 90% en {dias} días ({resumen['primer_atencion']})"
        )

    st.divider()

    # ============= GRÁFICO PRINCIPAL ============================
    st.markdown("##### 📊 Evolución m³ ocupado vs capacidad")

    fig = go.Figure()

    # Área de capacidad (gris claro fondo)
    fig.add_trace(go.Scatter(
        x=df['fecha'], y=[cap] * len(df),
        mode='lines', name='Capacidad total',
        line=dict(color='#CBD5E1', width=2, dash='dash'),
        fill='tonexty' if False else None,
        hovertemplate='Capacidad: %{y:,.0f} m³<extra></extra>',
    ))

    # Línea de ocupación (azul)
    fig.add_trace(go.Scatter(
        x=df['fecha'], y=df['m3_ocupado'],
        mode='lines', name='Ocupado proyectado',
        line=dict(color='#1F4E79', width=3),
        fill='tozeroy', fillcolor='rgba(31,78,121,0.15)',
        hovertemplate='%{x|%d/%m}<br>Ocupado: %{y:,.0f} m³<br>'
                       'Pallets: %{customdata[0]:,.0f}<br>'
                       'Ocupación: %{customdata[1]:.1f}%<extra></extra>',
        customdata=df[['pallets_ocupados', 'pct_ocupacion']].values,
    ))

    # Línea umbrales 70% y 90%
    fig.add_hline(y=cap * 0.9, line=dict(color='#EA580C', width=1, dash='dot'),
                   annotation_text='90%', annotation_position='right')
    fig.add_hline(y=cap * 0.7, line=dict(color='#F59E0B', width=1, dash='dot'),
                   annotation_text='70%', annotation_position='right')

    # Marcadores entradas (PIs)
    df_ent = df[df['m3_entrante_dia'] > 0]
    if not df_ent.empty:
        fig.add_trace(go.Scatter(
            x=df_ent['fecha'], y=df_ent['m3_ocupado'],
            mode='markers', name='Entrada PI',
            marker=dict(symbol='triangle-up', size=14, color='#16A34A',
                         line=dict(color='white', width=2)),
            hovertemplate='%{x|%d/%m}<br><b>Entra %{customdata:,.0f} m³</b><extra></extra>',
            customdata=df_ent['m3_entrante_dia'],
        ))

    fig.update_layout(
        height=420,
        xaxis=dict(title='Fecha'),
        yaxis=dict(title='m³', tickformat=',.0f'),
        hovermode='x unified',
        margin=dict(t=20, b=40, l=60, r=20),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', y=1.05, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"🟢 Triángulos = días con llegada de PI · "
        f"Total entrante 90d: {resumen.get('m3_total_entrante_horizonte', 0):,.0f} m³ · "
        f"Total saliente 90d: {resumen.get('m3_total_saliente_horizonte', 0):,.0f} m³ "
        "(forecast venta × volumen unitario)"
    )

    st.divider()

    # ============= INSIGHTS ============================
    st.markdown("##### 💡 Insights & acciones recomendadas")
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

    # ============= TABLA DETALLE ============================
    with st.expander("📋 Detalle diario (próximos 90 días)", expanded=False):
        df_show = df.copy()
        df_show['fecha'] = df_show['fecha'].dt.date
        df_show = df_show[['fecha', 'm3_ocupado', 'm3_entrante_dia',
                           'm3_saliente_dia', 'm3_disponible',
                           'pallets_ocupados', 'pallets_disp',
                           'pct_ocupacion', 'alerta']]
        df_show.columns = ['Fecha', 'm³ Ocup', 'Entra', 'Sale',
                           'm³ Disp', 'Pal Ocup', 'Pal Disp',
                           '% Ocup', 'Estado']
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)

    # ============= ANOMALÍAS STOCK ACTUAL ============================
    anom_count = resumen.get('stock_anomalies_count', 0)
    if anom_count > 0:
        with st.expander(
            f"⚠️ {anom_count} SKUs en stock con volumen anómalo "
            "(excluidos del cálculo)", expanded=False,
        ):
            st.caption(
                "Estos SKUs tienen `product.template.volume` cargado en cm³ "
                "u otra unidad por error. Corregir en Odoo para que el cálculo "
                "de capacidad sea más preciso."
            )
            top = resumen.get('top_stock_anomalies', [])
            if top:
                df_anom = pd.DataFrame(top)
                df_anom.columns = ['SKU', 'Vol unit Odoo (anómalo)', 'Stock unidades']
                st.dataframe(df_anom, use_container_width=True, hide_index=True)
