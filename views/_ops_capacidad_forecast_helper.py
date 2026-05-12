"""
Helper de visualización del forecast de capacidad bodega 90 días.

Lee data/capacidad/forecast_diario.parquet + forecast_resumen.json
(generado por extract_capacidad_forecast.py).

Modelo:
  - Capacidad = # POSICIONES leaf de CA1/Stock (mismo dato que Stock LIVE >
    Uso de posiciones, no asunción).
  - Estado HOY = ocupadas vs libres reales según Odoo (quant_ids).
  - Forecast = pos_ocup_t = pos_ocup_t-1 + pallets_entrantes - pallets_salientes
  - Pallets entrantes: pallets_estim por PI con su ETA
  - Pallets salientes: m³ saliente forecast / m³ por pallet apilable
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
    """Insights de slotting/distribución basados en el escenario detectado."""
    insights = []
    estado = resumen.get('estado_actual', {})
    pico = resumen.get('pico_proyectado', {})
    pos_total = estado.get('posiciones_total', 0)
    pos_libres = estado.get('posiciones_libres_hoy', 0)
    pct_hoy = estado.get('pct_ocupacion_hoy', 0)
    pct_pico = pico.get('pct_ocupacion', 0)
    pos_pico = pico.get('posiciones_ocupadas', 0)
    primer_critico = resumen.get('primer_critico')
    primer_atencion = resumen.get('primer_atencion')
    pis_entrantes = resumen.get('pis_entrantes', [])
    pal_total_ent = resumen.get('pallets_total_entrantes_horizonte', 0)

    # ── 1. Choque PI vs posiciones libres ────────────────────────────────
    # Si las próximas semanas hay PIs cuyo total de pallets > posiciones libres,
    # alertar al user de un próximo choque incluso si no se "llena" globalmente
    # (ej: PI grande llega antes que se vacíe espacio por ventas).
    pis_30d = [pi for pi in pis_entrantes
                if (pd.to_datetime(pi['fecha_eta']).date() - datetime.now().date()).days <= 30]
    if pis_30d:
        pal_30d = sum(pi['pallets'] for pi in pis_30d)
        if pal_30d > pos_libres * 0.8:
            insights.append({
                'tipo': '🟠 ALERTA RECEPCIÓN 30D',
                'titulo': (f'Próximos 30d entran {pal_30d:,.0f} pallets de {len(pis_30d)} PIs'
                            f' vs {pos_libres} posiciones libres HOY'),
                'accion': (
                    "**Plan inmediato (no esperás a que se llene):**\n"
                    "1. Adelantar consolidación de SKUs fragmentados → revisar sub-tab "
                    "**🆓 Slots liberables**\n"
                    "2. Liquidar SKUs sin venta 60+d (sub-tab Stock Total filtro 'SIN VENTA')\n"
                    "3. Pre-empacar pedidos B2B grandes pendientes para sacarlos\n"
                    "4. Re-slotting de SKUs C de zona caliente a estanterías altas\n"
                    "5. Coordinar con Steven/Vicente posibles delays si capacidad no alcanza"
                ),
            })

    # ── 2. Saturación crítica (>90% en algún momento) ────────────────────
    if primer_critico:
        dias = (pd.to_datetime(primer_critico).date() - datetime.now().date()).days
        if dias <= 14:
            insights.append({
                'tipo': '🔴 BODEGA SE LLENA',
                'titulo': f'Saturación 100% proyectada en {dias} días ({primer_critico})',
                'accion': (
                    "**Acción urgente esta semana:**\n"
                    "1. Bloquear recepción de nuevos PIs hasta liberar al menos 50 posiciones\n"
                    "2. Movimiento masivo a bodega externa de SKUs lentos (>180d sin venta)\n"
                    "3. Promo flash 24-48h en SKUs sobrestockeados (top 20 por valor)\n"
                    "4. Renegociar ETAs con Steven (delay 1-2 semanas próximos PIs)\n"
                    "5. Revisar slotting subóptimo: SKUs A en zonas frías ocupando posiciones "
                    "que podrían usarse mejor"
                ),
            })

    if primer_atencion and not primer_critico:
        dias = (pd.to_datetime(primer_atencion).date() - datetime.now().date()).days
        insights.append({
            'tipo': '🟠 ATENCIÓN',
            'titulo': f'Bodega supera 90% en {dias} días ({primer_atencion})',
            'accion': (
                "**Plan a 30 días:**\n"
                "1. Consolidar fragmentos (sub-tab '🆓 Slots liberables')\n"
                "2. Liquidación moderada de SKUs sin venta 60+d\n"
                "3. Confirmar capacidad real (¿hay racks en altura no contados?)"
            ),
        })

    # ── 3. Sub-utilización ────────────────────────────────────────────────
    if pct_hoy < 50 and pct_pico < 60:
        insights.append({
            'tipo': '🟡 EFICIENCIA — sub-utilizada',
            'titulo': f'Bodega al {pct_hoy:.0f}% hoy, pico solo {pct_pico:.0f}%',
            'accion': (
                "**Oportunidades:**\n"
                f"1. Tenés ~{pos_libres - 50} posiciones que no se usan en 90d → "
                "sub-arrendar o consolidar bodegas\n"
                "2. Adelantar PIs futuros (ahorro flete por consolidación)\n"
                "3. Re-slotting agresivo: TODOS los SKUs A en zona caliente cerca de packing\n"
                "4. Renegociar arriendo si la zona ociosa supera 30% por 6+ meses"
            ),
        })

    # ── 4. Concentración temporal de entradas ────────────────────────────
    eventos = resumen.get('dias_con_entrada_transito', [])
    if eventos:
        df_ev = pd.DataFrame(eventos)
        df_ev['fecha'] = pd.to_datetime(df_ev['fecha'])
        avg_pal = df_ev['pallets'].mean()
        picos = df_ev[df_ev['pallets'] > avg_pal * 2]
        if not picos.empty:
            top = picos.iloc[0]
            insights.append({
                'tipo': '🔵 PLANIFICACIÓN RECEPCIÓN',
                'titulo': f'Entrada grande de {top["pallets"]:,.0f} pallets el {top["fecha"].date()}',
                'accion': (
                    "**Preparar bodega para recepción:**\n"
                    f"1. Liberar al menos {top['pallets']*1.2:,.0f} posiciones con anticipación\n"
                    "2. Asignar slots cercanos a recepción para SKUs A esperados\n"
                    "3. Coordinar staff extra ese día (recepción + check-in)\n"
                    "4. Revisar % cobertura volumen del PI (sub-tab COMEX → '📐 Volumen / Pallets')"
                ),
            })

    # ── 5. Demanda no cubierta (quiebres reales) ──────────────────────────
    sal_dbg = resumen.get('salidas_debug', {})
    no_cub = sal_dbg.get('demanda_no_cubierta_unidades_total', 0)
    sal_unid = sal_dbg.get('salidas_unidades_90d_total', 1)
    if no_cub > 0 and sal_unid > 0:
        pct_no_cub = no_cub / (no_cub + sal_unid) * 100
        if pct_no_cub > 15:
            insights.append({
                'tipo': '🔴 QUIEBRES PROYECTADOS',
                'titulo': (f'{no_cub:,.0f} unidades de demanda 90d NO se cumplen '
                            f'({pct_no_cub:.0f}% del total proyectado)'),
                'accion': (
                    "**Plan de aprovisionamiento urgente:**\n"
                    "1. Identificar SKUs con quiebre crítico (Stock Total → filtro 🔴 CRÍTICO/QUIEBRE)\n"
                    "2. Cruzar SKUs con quiebre vs PIs en tránsito — si NO viene en próximos 60d, "
                    "incluir en próxima orden a Steven\n"
                    "3. Para SKUs sin reposición programada → considerar transporte aéreo o "
                    "proveedor alternativo local\n"
                    "4. Revisar elasticidad: ¿se puede subir precio para enfriar demanda mientras "
                    "llega reposición? (data en app Ventas → Análisis pricing)"
                ),
            })

    # ── 6. Distribución espacial (slotting óptimo) ────────────────────────
    if pos_libres < pos_total * 0.10:
        insights.append({
            'tipo': '🔵 SLOTTING — zona caliente',
            'titulo': 'Pocas posiciones libres → slotting es crítico',
            'accion': (
                "**Re-distribución sugerida:**\n"
                "1. SKUs A (top 20% movimientos) → posiciones más cercanas a packing\n"
                "2. SKUs C (sin venta 90+d) → estanterías altas o bodega externa\n"
                "3. Consolidar SKUs con qty <5 fragmentados en múltiples slots\n"
                "4. Posiciones dormidas (stock pero sin movs >30d) → candidatas a reasignar"
            ),
        })

    # Sin alertas
    if not insights:
        insights.append({
            'tipo': '🟢 OK',
            'titulo': f'Capacidad balanceada — pico {pct_pico:.0f}% en horizonte 90d',
            'accion': (
                "**Optimizaciones nice-to-have:**\n"
                "1. Re-slotting periódico de SKUs A para reducir OCT\n"
                "2. Auditar SKUs dormidas >30d y liquidar\n"
                "3. Corregir SKUs con volumen anómalo en Odoo (excluidos del cálculo)"
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
    estado = resumen.get('estado_actual', {})
    cap_pos = resumen.get('capacidad_posiciones', 0)
    cap_fuente = resumen.get('capacidad_fuente', '')
    asunc = resumen.get('asunciones', {})

    st.caption(
        f"🕒 Generado: {resumen.get('generado_en','')[:19]} · "
        f"Capacidad: **{cap_pos:,} posiciones** CA1/Stock leaf [{cap_fuente}] · "
        f"📐 Asunciones: posición ≈ {asunc.get('m3_por_posicion', 1.8)} m³ "
        f"(1×1,2×1,5m), 1 pallet apilable ≈ {asunc.get('m3_por_pallet_apilable', 1.2)} m³"
    )

    # Cobertura de salidas (transparencia del modelo)
    sal_dbg = resumen.get('salidas_debug', {})
    if sal_dbg:
        sk_odoo = sal_dbg.get('sku_con_vol_odoo', 0)
        sk_fb = sal_dbg.get('sku_fallback', 0)
        dem_total = sal_dbg.get('demanda_total_unidades_horizonte', 0)
        dem_cump = sal_dbg.get('demanda_cumplida_unidades', 0)
        no_cub = sal_dbg.get('demanda_no_cubierta_unidades_total', 0)
        pct_cump = sal_dbg.get('pct_demanda_cumplida', 0)
        excluidos = sal_dbg.get('skus_no_fisicos_excluidos', [])
        st.caption(
            f"📤 **Salidas (90d)**: forecast venta {dem_total:,.0f} unid · "
            f"cumplible con stock+tránsito {dem_cump:,.0f} ({pct_cump:.0f}%) · "
            f"NO cubierta {no_cub:,.0f} unid (revisar SKUs específicos abajo) · "
            f"Cobertura volumen: {sk_odoo} SKUs Odoo + {sk_fb} fallback"
            + (f" · Excluidos no físicos: {', '.join(excluidos[:3])}" if excluidos else "")
        )

    # ─── KPIs estado actual (POSICIONES) ─────────────────────────────────
    pos_ocup_hoy = estado.get('posiciones_ocupadas_hoy', 0)
    pos_libres_hoy = estado.get('posiciones_libres_hoy', 0)
    pct_hoy = estado.get('pct_ocupacion_hoy', 0)
    color_hoy = _color_pct(pct_hoy)
    pico = resumen.get('pico_proyectado', {})
    minimo = resumen.get('minimo_proyectado', {})

    cols = st.columns(4)
    cols[0].markdown(_kpi_card(
        "Ocupación HOY",
        f"{pct_hoy:.0f}%",
        f"{pos_ocup_hoy} ocup / {cap_pos} totales",
        color_hoy,
    ), unsafe_allow_html=True)
    cols[1].markdown(_kpi_card(
        "Posiciones LIBRES hoy",
        f"{pos_libres_hoy}",
        f"de {cap_pos} ({pos_libres_hoy/cap_pos*100:.0f}% libre)" if cap_pos else "—",
        '#16A34A' if pos_libres_hoy > 100 else '#EA580C',
    ), unsafe_allow_html=True)
    cols[2].markdown(_kpi_card(
        "Pico próximos 90d",
        f"{pico.get('pct_ocupacion', 0):.0f}%",
        f"{pico.get('posiciones_ocupadas', 0):,.0f} pos el {pico.get('fecha','')[:10]}",
        _color_pct(pico.get('pct_ocupacion', 0)),
    ), unsafe_allow_html=True)
    cols[3].markdown(_kpi_card(
        "Mínimo próximos 90d",
        f"{minimo.get('pct_ocupacion', 0):.0f}%",
        f"{minimo.get('posiciones_ocupadas', 0):,.0f} pos el {minimo.get('fecha','')[:10]}",
        '#DC2626' if minimo.get('pct_ocupacion', 0) < 10 else '#16A34A',
    ), unsafe_allow_html=True)

    # ─── Banner alerta ───────────────────────────────────────────────────
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

    # ─── Cruce PIs entrantes vs posiciones libres ─────────────────────────
    pis_entrantes = resumen.get('pis_entrantes', [])
    if pis_entrantes:
        st.markdown("##### 🚢 Embarques entrantes vs posiciones disponibles")
        df_pis = pd.DataFrame(pis_entrantes)
        df_pis['fecha_eta'] = pd.to_datetime(df_pis['fecha_eta']).dt.date

        # Acumulado de pallets necesarios contra libres hoy
        df_pis_sorted = df_pis.sort_values('fecha_eta').copy()
        df_pis_sorted['pallets_acumulado'] = df_pis_sorted['pallets'].cumsum()
        df_pis_sorted['pos_libres_si_no_sale_nada'] = (pos_libres_hoy
                                                        - df_pis_sorted['pallets_acumulado'])
        df_pis_sorted['estado'] = df_pis_sorted['pos_libres_si_no_sale_nada'].apply(
            lambda v: '🔴 NO ENTRA' if v < 0 else ('🟠 AJUSTADO' if v < 30 else '🟢 ENTRA')
        )

        df_show = df_pis_sorted[[
            'pi', 'fecha_eta', 'transporte', 'unidades', 'm3', 'pallets',
            'pallets_acumulado', 'pos_libres_si_no_sale_nada', 'estado',
        ]].copy()
        df_show['unidades'] = df_show['unidades'].apply(lambda v: f'{v:,.0f}')
        df_show['m3'] = df_show['m3'].apply(lambda v: f'{v:,.1f}')
        df_show['pallets'] = df_show['pallets'].apply(lambda v: f'{v:,.0f}')
        df_show['pallets_acumulado'] = df_show['pallets_acumulado'].apply(lambda v: f'{v:,.0f}')
        df_show['pos_libres_si_no_sale_nada'] = df_show['pos_libres_si_no_sale_nada'].apply(
            lambda v: f'{v:,.0f}'
        )
        df_show.columns = ['PI', 'ETA bodega', 'Transp.', 'Unidades', 'm³',
                            'Pallets PI', 'Pallets acum.',
                            'Pos libres si no sale nada', 'Estado']
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=320)
        st.caption(
            "**Lógica de la columna 'Pos libres si no sale nada'**: "
            f"asume que se reciben todos los PIs SIN que salga nada por venta. "
            f"Si pasa a negativo, ese PI no entraría sin liberar espacio antes. "
            "El forecast del gráfico abajo SÍ considera salidas."
        )

    st.divider()

    # ─── GRÁFICO PRINCIPAL ────────────────────────────────────────────────
    st.markdown("##### 📊 Evolución posiciones ocupadas (con salidas forecast)")

    fig = go.Figure()

    # Capacidad total (línea horizontal punteada)
    fig.add_trace(go.Scatter(
        x=df['fecha'], y=[cap_pos] * len(df),
        mode='lines', name=f'Capacidad ({cap_pos} pos)',
        line=dict(color='#CBD5E1', width=2, dash='dash'),
        hovertemplate='Capacidad: %{y:,.0f} posiciones<extra></extra>',
    ))

    # Línea de ocupación
    fig.add_trace(go.Scatter(
        x=df['fecha'], y=df['posiciones_ocupadas'],
        mode='lines', name='Posiciones ocupadas',
        line=dict(color='#1F4E79', width=3),
        fill='tozeroy', fillcolor='rgba(31,78,121,0.15)',
        hovertemplate='%{x|%d/%m}<br>Ocupado: %{y:,.0f} pos<br>'
                       'Disponible: %{customdata[0]:,.0f}<br>'
                       'Ocupación: %{customdata[1]:.1f}%<extra></extra>',
        customdata=df[['posiciones_disp', 'pct_ocupacion']].values,
    ))

    # Umbrales
    fig.add_hline(y=cap_pos * 0.9, line=dict(color='#EA580C', width=1, dash='dot'),
                   annotation_text='90%', annotation_position='right')
    fig.add_hline(y=cap_pos * 0.7, line=dict(color='#F59E0B', width=1, dash='dot'),
                   annotation_text='70%', annotation_position='right')

    # Marcadores entradas (PIs)
    df_ent = df[df['pallets_entrantes_dia'] > 0]
    if not df_ent.empty:
        fig.add_trace(go.Scatter(
            x=df_ent['fecha'], y=df_ent['posiciones_ocupadas'],
            mode='markers', name='Entrada PI',
            marker=dict(symbol='triangle-up', size=14, color='#16A34A',
                         line=dict(color='white', width=2)),
            hovertemplate='%{x|%d/%m}<br><b>Entran %{customdata:,.0f} pallets</b><extra></extra>',
            customdata=df_ent['pallets_entrantes_dia'],
        ))

    fig.update_layout(
        height=420,
        xaxis=dict(title='Fecha'),
        yaxis=dict(title='Posiciones ocupadas', tickformat=',.0f'),
        hovermode='x unified',
        margin=dict(t=20, b=40, l=60, r=20),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', y=1.05, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"🟢 Triángulos = días con llegada de PI · "
        f"Total entrante 90d: {resumen.get('pallets_total_entrantes_horizonte', 0):,.0f} pallets · "
        f"Total saliente 90d: {resumen.get('pallets_total_salientes_horizonte', 0):,.0f} pallets "
        "(forecast venta convertido)"
    )

    st.divider()

    # ─── TOP SKUs NO CUBIERTOS (señal de reposición urgente) ──────────────
    sal_dbg = resumen.get('salidas_debug', {})
    top_no_cub = sal_dbg.get('top_no_cubiertos', [])
    if top_no_cub:
        st.markdown("##### 🔴 SKUs con quiebre proyectado (sin stock + sin tránsito)")
        st.caption(
            "Estos SKUs no alcanzan a cumplir la demanda forecast 90d. Si están "
            "**sin match en stock** = no tienen stock actual NI llegan en próximos PIs. "
            "Acción: incluir en la próxima orden a Steven o evaluar transporte aéreo."
        )
        df_nc = pd.DataFrame(top_no_cub)
        df_nc['unid_no_cubiertas'] = df_nc['unid_no_cubiertas'].apply(lambda v: f'{v:,.0f}')
        df_nc['sin_match_stock'] = df_nc['sin_match_stock'].apply(
            lambda v: '🔴 sin stock ni tránsito' if v else '🟡 stock insuficiente'
        )
        df_nc.columns = ['SKU', 'Unid demanda 90d NO cubierta', 'Estado']
        st.dataframe(df_nc.head(20), use_container_width=True, hide_index=True, height=420)
        st.caption(
            f"💡 Total no cubierto: {sal_dbg.get('demanda_no_cubierta_unidades_total', 0):,.0f} unidades "
            f"distribuidas en {sal_dbg.get('sku_sin_match_stock_count', 0)} SKUs sin reposición."
        )

    st.divider()

    # ─── INSIGHTS ────────────────────────────────────────────────────────
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

    # ─── DETALLE DIARIO ──────────────────────────────────────────────────
    with st.expander("📋 Detalle diario (próximos 90 días)", expanded=False):
        df_show = df.copy()
        df_show['fecha'] = df_show['fecha'].dt.date
        df_show = df_show[['fecha', 'posiciones_ocupadas', 'posiciones_disp',
                           'pallets_entrantes_dia', 'pallets_salientes_dia',
                           'pct_ocupacion', 'alerta']]
        df_show.columns = ['Fecha', 'Pos Ocup', 'Pos Disp',
                           'Pal Entran', 'Pal Salen', '% Ocup', 'Estado']
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)

    # ─── ANOMALÍAS STOCK ─────────────────────────────────────────────────
    anom_count = resumen.get('stock_anomalies_count', 0)
    if anom_count > 0:
        with st.expander(
            f"⚠️ {anom_count} SKUs en stock con volumen anómalo "
            "(excluidos del cálculo m³)", expanded=False,
        ):
            st.caption(
                "Estos SKUs tienen `product.template.volume` cargado en cm³ "
                "u otra unidad por error. No afecta el cálculo por POSICIONES "
                "(ese usa el dato real de Odoo) pero sí el m³ informativo. "
                "Corregir en Odoo cuando se pueda."
            )
            top = resumen.get('top_stock_anomalies', [])
            if top:
                df_anom = pd.DataFrame(top)
                df_anom.columns = ['SKU', 'Vol unit Odoo (anómalo)', 'Stock unidades']
                st.dataframe(df_anom, use_container_width=True, hide_index=True)
