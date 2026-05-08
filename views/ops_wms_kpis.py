"""
Vista KPIs Operacionales / WMS — app Operaciones.

KPIs definidos por el user (matriz benchmarks de mercado):
  - Exactitud de inventario  (≥98%)
  - OTIF B2C                  (92-97%)
  - OTIF B2B                  (95-98%)
  - Pick accuracy             (≥99.5%)
  - Productividad picking     (60-120 líneas/h)
  - Tiempo de recepción       (24-72h)
  - Costo por pedido          (mensual)
  - Merma operativa           (≤0.5%)
  - Ocupación de bodega       (m3 ocupados / m3 disponibles)

Datos:
  - Odoo: OTIF, Pick Accuracy, Tiempo recepción
  - Manuales: Equipo bodega, Capacidad m3, Cycle counts, Merma
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from views._ops_wms_helper import (
    kpi_otif, kpi_pick_accuracy, kpi_tiempo_recepcion,
    kpi_volumen_movimientos, top_clientes_otif_problemas,
)
from views._ops_data_helper import (
    get_equipo_mes, set_equipo_mes,
    get_capacidad_bodega, set_capacidad_bodega,
    add_cycle_count, get_cycle_counts, kpi_exactitud_inventario,
    set_merma_mes, get_merma_mes, kpi_merma_operativa,
)


def _semaforo(valor, verde, amarillo_min=None, amarillo_max=None, mayor_es_mejor=True):
    """Semáforo según rango. Si mayor_es_mejor=False (ej tiempos), invierte la lógica."""
    if valor is None:
        return "⚪", "#94A3B8"
    if mayor_es_mejor:
        if valor >= verde:
            return "🟢", "#16A34A"
        if amarillo_min is not None and valor >= amarillo_min:
            return "🟡", "#EA580C"
        return "🔴", "#DC2626"
    else:
        if valor <= verde:
            return "🟢", "#16A34A"
        if amarillo_max is not None and valor <= amarillo_max:
            return "🟡", "#EA580C"
        return "🔴", "#DC2626"


def _kpi_card(label, value, sub="", color="#1F4E79", semaforo=""):
    return f"""<div style="background:white;border-radius:12px;padding:14px 16px;text-align:center;
        box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #E2E8F0;height:100%;">
        <div style="font-size:0.65rem;color:#64748B;text-transform:uppercase;letter-spacing:0.6px;font-weight:600;margin-bottom:3px;">{label}</div>
        <div style="font-size:1.4rem;font-weight:700;color:{color};line-height:1.2;">{semaforo} {value}</div>
        <div style="font-size:0.68rem;color:#94A3B8;margin-top:2px;">{sub}</div>
    </div>"""


def render():
    with st.sidebar:
        st.markdown("### 🎯 **KPIs WMS**")
        st.caption("Operación de bodega")
        st.markdown("---")
        if st.button("🔄 Refrescar Odoo", use_container_width=True, type="primary", key="wms_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("🎯 KPIs Operacionales — Logística WMS")
    st.caption("Plan Estratégico 2026-2028 · Cache 5 min · Datos Odoo + manuales")

    tabs = st.tabs([
        "📊 Resumen",
        "📦 OTIF (B2C / B2B)",
        "🎯 Picking",
        "📥 Recepciones",
        "📋 Datos manuales",
    ])

    # ============================================================
    # TAB 1 — RESUMEN
    # ============================================================
    with tabs[0]:
        st.markdown("### KPIs principales — comparado con benchmarks de mercado")

        # Cargar datos
        otif_b2c = kpi_otif(dias=30, canal_b2b=False)
        otif_b2b = kpi_otif(dias=30, canal_b2b=True)
        pick_acc = kpi_pick_accuracy(dias=30)
        tiempo_rec = kpi_tiempo_recepcion(dias=90)
        exactitud = kpi_exactitud_inventario(dias=30)
        merma = kpi_merma_operativa()
        capacidad = get_capacidad_bodega()

        mes_actual = datetime.now().strftime("%Y-%m")
        equipo = get_equipo_mes(mes_actual)

        # Fila 1: KPIs Odoo automáticos
        st.markdown("#### 🟢 Desde Odoo (automático)")
        c1, c2, c3, c4 = st.columns(4)

        # OTIF B2C
        v = otif_b2c.get("valor")
        sem, color = _semaforo(v, 0.97, 0.92, mayor_es_mejor=True)
        c1.markdown(_kpi_card("OTIF B2C",
                               f"{v*100:.1f}%" if v is not None else "—",
                               f"Benchmark: 92-97% · {otif_b2c.get('total_pickings', 0)} pickings",
                               color, sem), unsafe_allow_html=True)

        # OTIF B2B
        v = otif_b2b.get("valor")
        sem, color = _semaforo(v, 0.98, 0.95, mayor_es_mejor=True)
        c2.markdown(_kpi_card("OTIF B2B",
                               f"{v*100:.1f}%" if v is not None else "—",
                               f"Benchmark: 95-98% · {otif_b2b.get('total_pickings', 0)} pickings",
                               color, sem), unsafe_allow_html=True)

        # Pick Accuracy
        v = pick_acc.get("valor")
        sem, color = _semaforo(v, 0.995, 0.98, mayor_es_mejor=True)
        c3.markdown(_kpi_card("Pick Accuracy",
                               f"{v*100:.1f}%" if v is not None else "—",
                               f"Benchmark: ≥99.5% · {pick_acc.get('total', 0)} moves",
                               color, sem), unsafe_allow_html=True)

        # Tiempo recepción
        v = tiempo_rec.get("valor")
        sem, color = _semaforo(v, 24, amarillo_max=72, mayor_es_mejor=False)
        c4.markdown(_kpi_card("Tiempo recepción",
                               f"{v:.0f}h" if v is not None else "—",
                               f"Benchmark: 24-72h · {tiempo_rec.get('n_recepciones', 0)} recepciones",
                               color, sem), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Fila 2: KPIs manuales
        st.markdown("#### 🟡 Manuales (cargar en Tab 5)")
        c5, c6, c7, c8 = st.columns(4)

        # Exactitud inventario
        v = exactitud.get("valor")
        sem, color = _semaforo(v, 0.98, 0.95, mayor_es_mejor=True)
        c5.markdown(_kpi_card("Exactitud Inventario",
                               f"{v*100:.1f}%" if v is not None else "—",
                               f"Benchmark: ≥98% · {exactitud.get('total', 0)} cycle counts",
                               color, sem), unsafe_allow_html=True)

        # Productividad picking
        if equipo and equipo.get("horas_total"):
            # asumir que kpi_pick_accuracy nos da el total de moves (líneas)
            lineas = pick_acc.get("total", 0)
            horas = equipo.get("horas_total", 0)
            v = lineas / horas if horas else None
            sem, color = _semaforo(v, 60, 40, mayor_es_mejor=True)
            c6.markdown(_kpi_card("Productividad picking",
                                   f"{v:.0f} líneas/h" if v is not None else "—",
                                   f"Benchmark: 60-120 · {lineas:,} líneas en {horas}h",
                                   color, sem), unsafe_allow_html=True)
        else:
            c6.markdown(_kpi_card("Productividad picking", "—",
                                   "Falta cargar horas equipo (Tab 5)", "#94A3B8"),
                        unsafe_allow_html=True)

        # Merma operativa
        v = merma.get("valor")
        sem, color = _semaforo(v, 0.005, amarillo_max=0.01, mayor_es_mejor=False)
        c7.markdown(_kpi_card("Merma operativa",
                               f"{v*100:.2f}%" if v is not None else "—",
                               f"Benchmark: ≤0.5% · {merma.get('n_meses', 0)} meses",
                               color, sem), unsafe_allow_html=True)

        # Ocupación bodega (m3)
        m3_total = capacidad.get("m3_totales")
        if m3_total:
            # Necesitamos m3 ocupados — proxy: asumir ratio = ocupación posiciones
            from views.shared import cached_stock
            stock_data = cached_stock()
            ocup_pct = stock_data.get("ocupacion", {}).get("pct", 0) if stock_data else 0
            sem, color = _semaforo(ocup_pct/100, 0.85, amarillo_max=0.95, mayor_es_mejor=False)
            c8.markdown(_kpi_card("Ocupación m³ bodega",
                                   f"{ocup_pct:.0f}%",
                                   f"Capacidad: {m3_total:.0f} m³ totales",
                                   color, sem), unsafe_allow_html=True)
        else:
            c8.markdown(_kpi_card("Ocupación m³ bodega", "—",
                                   "Falta capacidad m³ (Tab 5)", "#94A3B8"),
                        unsafe_allow_html=True)

        st.divider()

        # Tabla resumen con benchmarks
        st.markdown("### 📋 Matriz de benchmarks vs mercado")
        bench = [
            {"KPI": "Exactitud de inventario", "Tu valor":
                f"{exactitud.get('valor',0)*100:.1f}%" if exactitud.get('valor') else "—",
             "Benchmark": "≥ 98% (clase mundial 99.5%)", "Fuente": "WMS-driven warehouses"},
            {"KPI": "OTIF B2C", "Tu valor":
                f"{otif_b2c.get('valor',0)*100:.1f}%" if otif_b2c.get('valor') else "—",
             "Benchmark": "92-97%", "Fuente": "E-com chileno marketplaces"},
            {"KPI": "OTIF B2B", "Tu valor":
                f"{otif_b2b.get('valor',0)*100:.1f}%" if otif_b2b.get('valor') else "—",
             "Benchmark": "95-98%", "Fuente": "Cadenas retail Chile"},
            {"KPI": "Pick Accuracy", "Tu valor":
                f"{pick_acc.get('valor',0)*100:.1f}%" if pick_acc.get('valor') else "—",
             "Benchmark": "≥ 99.5%", "Fuente": "E-com retail multicategoría"},
            {"KPI": "Tiempo recepción", "Tu valor":
                f"{tiempo_rec.get('valor',0):.0f}h" if tiempo_rec.get('valor') else "—",
             "Benchmark": "24-72 horas", "Fuente": "Importadores con WMS"},
            {"KPI": "Merma operativa", "Tu valor":
                f"{merma.get('valor',0)*100:.2f}%" if merma.get('valor') else "—",
             "Benchmark": "≤ 0.5% del inventario", "Fuente": "Retail multicategoría"},
        ]
        st.dataframe(pd.DataFrame(bench), use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 2 — OTIF
    # ============================================================
    with tabs[1]:
        st.markdown("### 📦 OTIF (Order Time In Full)")
        st.caption("Pickings entregados a tiempo Y completos. On-Time = date_done ≤ scheduled_date · In-Full = qty_done ≥ product_uom_qty")

        col_period, _ = st.columns([1, 3])
        with col_period:
            dias_otif = st.selectbox("Ventana", [7, 14, 30, 60, 90], index=2, key="otif_dias")

        otif_b2c = kpi_otif(dias=dias_otif, canal_b2b=False)
        otif_b2b = kpi_otif(dias=dias_otif, canal_b2b=True)

        st.markdown("#### B2C (clientes finales)")
        if otif_b2c.get("error"):
            st.warning(otif_b2c["error"])
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("OTIF total", f"{otif_b2c.get('valor', 0)*100:.1f}%")
            c2.metric("On-Time", f"{otif_b2c.get('on_time_pct', 0)*100:.1f}%",
                      delta=f"{otif_b2c.get('on_time', 0)} pickings")
            c3.metric("In-Full", f"{otif_b2c.get('in_full_pct', 0)*100:.1f}%",
                      delta=f"{otif_b2c.get('in_full', 0)} pickings")
            c4.metric("Total pickings", f"{otif_b2c.get('total_pickings', 0)}")

        st.markdown("#### B2B (empresas)")
        if otif_b2b.get("error"):
            st.warning(otif_b2b["error"])
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("OTIF total", f"{otif_b2b.get('valor', 0)*100:.1f}%")
            c2.metric("On-Time", f"{otif_b2b.get('on_time_pct', 0)*100:.1f}%",
                      delta=f"{otif_b2b.get('on_time', 0)} pickings")
            c3.metric("In-Full", f"{otif_b2b.get('in_full_pct', 0)*100:.1f}%",
                      delta=f"{otif_b2b.get('in_full', 0)} pickings")
            c4.metric("Total pickings", f"{otif_b2b.get('total_pickings', 0)}")

        st.divider()

        # Top clientes B2B con peor OTIF
        st.markdown("### 🏢 Top clientes B2B con peor OTIF")
        top = top_clientes_otif_problemas(dias=dias_otif, top_n=15)
        if top.get("valor"):
            df = pd.DataFrame(top["valor"])
            df["on_time_pct"] = (df["on_time_pct"] * 100).round(1).astype(str) + "%"
            df.columns = ["Cliente", "Total Pickings", "Tarde", "% On-Time"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Sin datos")

    # ============================================================
    # TAB 3 — PICKING
    # ============================================================
    with tabs[2]:
        st.markdown("### 🎯 Pick Accuracy + Productividad")

        col_p, _ = st.columns([1, 3])
        with col_p:
            dias_p = st.selectbox("Ventana", [7, 14, 30, 60, 90], index=2, key="pick_dias")

        pick_acc = kpi_pick_accuracy(dias=dias_p)

        if pick_acc.get("error"):
            st.warning(pick_acc["error"])
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Pick Accuracy", f"{pick_acc.get('valor', 0)*100:.2f}%",
                      delta=f"{pick_acc.get('errores', 0)} errores en {pick_acc.get('total', 0)} moves")
            c2.metric("Total moves done", f"{pick_acc.get('total', 0):,}")
            c3.metric("Errores (qty mismatch)", f"{pick_acc.get('errores', 0):,}")

        st.divider()

        # Productividad
        st.markdown("### ⚡ Productividad")
        mes_actual = datetime.now().strftime("%Y-%m")
        equipo = get_equipo_mes(mes_actual)

        if not equipo or not equipo.get("horas_total"):
            st.info("📋 Para calcular productividad necesitamos las horas del equipo bodega del mes. Cargá en Tab 5 → Equipo bodega.")
        else:
            lineas = pick_acc.get("total", 0)
            horas = equipo.get("horas_total", 0)
            personas = equipo.get("personas", 0)
            prod = lineas / horas if horas else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("Productividad", f"{prod:.0f} líneas/h",
                      help="Benchmark: 60-120 líneas/h B2C")
            c2.metric("Equipo", f"{personas} personas")
            c3.metric("Horas total mes", f"{horas:,.0f}h")

    # ============================================================
    # TAB 4 — RECEPCIONES
    # ============================================================
    with tabs[3]:
        st.markdown("### 📥 Recepciones")
        st.caption("Tiempo entre fecha programada y fecha efectiva de recepción de embarques")

        col_r, _ = st.columns([1, 3])
        with col_r:
            dias_r = st.selectbox("Ventana", [30, 60, 90, 180, 365], index=2, key="rec_dias")

        rec = kpi_tiempo_recepcion(dias=dias_r)

        if rec.get("error"):
            st.warning(rec["error"])
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Tiempo promedio", f"{rec.get('valor', 0):.1f} h")
            c2.metric("Recepciones", f"{rec.get('n_recepciones', 0)}")
            c3.metric("Más rápida", f"{rec.get('min', 0):.1f} h")
            c4.metric("Más lenta", f"{rec.get('max', 0):.1f} h")

            st.divider()
            st.markdown("#### Detalle últimas 20 recepciones")
            if rec.get("detalle"):
                st.dataframe(pd.DataFrame(rec["detalle"]),
                             use_container_width=True, hide_index=True)

        st.divider()

        # Volumen
        vol = kpi_volumen_movimientos(dias=dias_r)
        st.markdown("### 📊 Volumen movimientos por tipo")
        if vol.get("error"):
            st.warning(vol["error"])
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📥 Incoming", f"{vol.get('incoming', 0)}")
            c2.metric("📤 Outgoing", f"{vol.get('outgoing', 0)}")
            c3.metric("🔄 Internal", f"{vol.get('internal', 0)}")
            c4.metric("Total", f"{vol.get('total', 0)}")

    # ============================================================
    # TAB 5 — DATOS MANUALES
    # ============================================================
    with tabs[4]:
        st.markdown("### 📋 Carga de datos manuales")
        st.caption("Datos que NO vienen de Odoo y necesitan carga periódica.")

        st.warning(
            "⚠️ **Datos persistidos en JSON local.** En Streamlit Cloud, los datos se pierden "
            "al re-deploy. Para persistencia real (H2): migrar a Turso (libSQL). Por ahora cargar "
            "datos críticos al inicio de cada sesión."
        )

        # Sub-tabs
        sub_tabs = st.tabs([
            "👥 Equipo bodega",
            "🏭 Capacidad m³",
            "📋 Cycle counts",
            "📉 Merma",
        ])

        # ---- Equipo bodega ----
        with sub_tabs[0]:
            st.markdown("#### Equipo bodega — horas trabajadas por mes")

            mes_input = st.text_input("Mes (YYYY-MM)", value=datetime.now().strftime("%Y-%m"), key="eq_mes")
            actual = get_equipo_mes(mes_input)
            c1, c2 = st.columns(2)
            personas = c1.number_input("Personas activas", min_value=0, max_value=200, step=1,
                                        value=actual.get("personas", 0), key="eq_personas")
            horas = c2.number_input("Horas total trabajadas en el mes", min_value=0.0, step=10.0,
                                     value=float(actual.get("horas_total", 0)), key="eq_horas")
            if st.button("💾 Guardar equipo", key="eq_save"):
                if set_equipo_mes(mes_input, int(personas), float(horas)):
                    st.success(f"✅ Guardado para {mes_input}")
                else:
                    st.error("❌ Error guardando")

        # ---- Capacidad bodega ----
        with sub_tabs[1]:
            st.markdown("#### Capacidad de bodega")
            actual = get_capacidad_bodega()
            current_m3 = actual.get("m3_totales") or 0.0
            m3 = st.number_input("Capacidad total m³ disponibles", min_value=0.0, step=10.0,
                                  value=float(current_m3), key="cap_m3")
            if st.button("💾 Guardar capacidad", key="cap_save"):
                if set_capacidad_bodega(float(m3)):
                    st.success(f"✅ Capacidad actualizada: {m3:,.0f} m³")
                else:
                    st.error("❌ Error guardando")
            if actual.get("fecha_actualizacion"):
                st.caption(f"Última actualización: {actual['fecha_actualizacion'][:16]}")

        # ---- Cycle counts ----
        with sub_tabs[2]:
            st.markdown("#### Cycle counts (auditorías de inventario)")
            st.caption("Cargar resultados de cada cycle count para calcular Exactitud Inventario.")

            with st.form("cc_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                sku = c1.text_input("SKU", key="cc_sku")
                qty_sis = c2.number_input("Qty Sistema", min_value=0.0, step=1.0, key="cc_qsis")
                qty_fis = c3.number_input("Qty Física", min_value=0.0, step=1.0, key="cc_qfis")
                fecha = st.text_input("Fecha (YYYY-MM-DD)", value=datetime.now().strftime("%Y-%m-%d"), key="cc_fecha")
                nota = st.text_input("Nota (opcional)", key="cc_nota")
                if st.form_submit_button("➕ Agregar cycle count", type="primary"):
                    if sku and (qty_fis > 0 or qty_sis > 0):
                        if add_cycle_count(sku, qty_sis, qty_fis, fecha, nota):
                            st.success(f"✅ Agregado: {sku}")
                        else:
                            st.error("❌ Error guardando")
                    else:
                        st.warning("Ingresá SKU + cantidades")

            # Histórico
            counts = get_cycle_counts()
            if counts:
                st.markdown(f"##### Histórico ({len(counts)} cycle counts)")
                df = pd.DataFrame(counts[:50])
                st.dataframe(df, use_container_width=True, hide_index=True, height=300)

        # ---- Merma ----
        with sub_tabs[3]:
            st.markdown("#### Merma operativa por mes")
            mes_m = st.text_input("Mes (YYYY-MM)", value=datetime.now().strftime("%Y-%m"), key="m_mes")
            actual = get_merma_mes(mes_m)
            c1, c2 = st.columns(2)
            mermado = c1.number_input("Valor mermado ($)", min_value=0.0, step=1000.0,
                                       value=float(actual.get("valor_mermado", 0)), key="m_mer")
            inv_prom = c2.number_input("Valor inventario promedio ($)", min_value=0.0, step=10000.0,
                                        value=float(actual.get("valor_inv_promedio", 0)), key="m_inv")
            if mermado > 0 and inv_prom > 0:
                pct = mermado / inv_prom
                color = "🟢" if pct <= 0.005 else ("🟡" if pct <= 0.01 else "🔴")
                st.metric(f"{color} % Merma", f"{pct*100:.2f}%", help="Benchmark: ≤ 0.5%")
            if st.button("💾 Guardar merma", key="m_save"):
                if set_merma_mes(mes_m, float(mermado), float(inv_prom)):
                    st.success(f"✅ Guardado para {mes_m}")
                else:
                    st.error("❌ Error guardando")
