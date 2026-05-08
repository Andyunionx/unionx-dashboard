"""
Vista KPIs Operacionales / WMS — app Operaciones.

KPIs (matriz benchmarks de mercado + plan estratégico 2026-2028):
  - Exactitud de inventario  (≥98%)              — manual cycle counts
  - OTIF B2C                  (92-97%)            — Odoo
  - OTIF B2B                  (95-98%)            — Odoo
  - Pick accuracy             (≥99.5%)            — Odoo
  - OFR Order Fulfillment     (≥95%)              — Odoo
  - OCT Order Cycle Time      (<24h B2C / <72h B2B) — Odoo
  - Productividad picking     (60-120 líneas/h)   — Odoo + manual horas
  - Tiempo de recepción       (24-72h)            — Odoo
  - Cobertura cycle counts    (≥80% últimos 12m)  — manual
  - Merma operativa           (≤0.5%)             — manual
  - Ocupación bodega          (% posiciones)      — Odoo (m3 pausado H2)
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from views._ops_wms_helper import (
    kpi_otif, kpi_pick_accuracy, kpi_tiempo_recepcion,
    kpi_volumen_movimientos, top_clientes_otif_problemas,
    kpi_ofr, kpi_oct, kpi_lineas_pickeadas_mes,
    tendencia_mensual, kpi_cobertura_cycle_counts,
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


def _safe_wms(fn, *args, default=None, **kwargs):
    """Wrapper defensivo: cualquier crash se captura y se muestra al final."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        st.session_state.setdefault('_wms_errors', []).append(
            f"{fn.__name__}: {type(e).__name__}: {str(e)[:120]}"
        )
        return default if default is not None else {"valor": None, "error": f"{type(e).__name__}"}


def render():
    with st.sidebar:
        st.markdown("### 🎯 **KPIs WMS**")
        st.caption("Operación de bodega · Plan 2026-2028")
        st.markdown("---")
        if st.button("🔄 Refrescar Odoo", use_container_width=True, type="primary", key="wms_refresh"):
            st.cache_data.clear()
            st.session_state.pop('_wms_errors', None)
            st.rerun()

    st.title("🎯 KPIs Operacionales — Logística WMS")
    st.caption("Plan Estratégico 2026-2028 · Cache 5-10 min · Datos Odoo + manuales")

    tabs = st.tabs([
        "📊 Resumen",
        "📦 OTIF (B2C/B2B)",
        "🎯 Picking & OFR/OCT",
        "📥 Recepciones",
        "📈 Tendencia mensual",
        "🛒 Análisis pedidos",
        "📋 Datos manuales",
    ])

    # ============================================================
    # TAB 1 — RESUMEN
    # ============================================================
    with tabs[0]:
        st.markdown("### KPIs principales — comparado con benchmarks de mercado")

        # Cargar datos (defensivo: cualquier crash no debe romper Tabs 2-6)
        otif_b2c = _safe_wms(kpi_otif, dias=30, canal_b2b=False)
        otif_b2b = _safe_wms(kpi_otif, dias=30, canal_b2b=True)
        pick_acc = _safe_wms(kpi_pick_accuracy, dias=30)
        tiempo_rec = _safe_wms(kpi_tiempo_recepcion, dias=90)
        ofr = _safe_wms(kpi_ofr, dias=30)
        oct = _safe_wms(kpi_oct, dias=30)
        exactitud = _safe_wms(kpi_exactitud_inventario, dias=30, default={"valor": None, "total": 0})
        merma = _safe_wms(kpi_merma_operativa, default={"valor": None, "n_meses": 0})
        cobertura = _safe_wms(kpi_cobertura_cycle_counts, meses=12, default={"valor": None})

        mes_actual = datetime.now().strftime("%Y-%m")
        equipo = _safe_wms(get_equipo_mes, mes_actual, default={}) or {}
        lineas_mes = _safe_wms(kpi_lineas_pickeadas_mes, mes_actual, default={"lineas": 0})

        # Fila 1: Cumplimiento al cliente (OTIF + OFR + OCT)
        st.markdown("#### 📦 Cumplimiento al cliente (Odoo)")
        c1, c2, c3, c4 = st.columns(4)

        # OTIF B2C
        v = otif_b2c.get("valor")
        sem, color = _semaforo(v, 0.97, 0.92, mayor_es_mejor=True)
        c1.markdown(_kpi_card("OTIF B2C",
                               f"{v*100:.1f}%" if v is not None else "—",
                               f"Bench: 92-97% · {otif_b2c.get('total_pickings', 0)} pickings",
                               color, sem), unsafe_allow_html=True)

        # OTIF B2B
        v = otif_b2b.get("valor")
        sem, color = _semaforo(v, 0.98, 0.95, mayor_es_mejor=True)
        c2.markdown(_kpi_card("OTIF B2B",
                               f"{v*100:.1f}%" if v is not None else "—",
                               f"Bench: 95-98% · {otif_b2b.get('total_pickings', 0)} pickings",
                               color, sem), unsafe_allow_html=True)

        # OFR
        v = ofr.get("valor")
        sem, color = _semaforo(v, 0.95, 0.85, mayor_es_mejor=True)
        c3.markdown(_kpi_card("OFR (cumplim. SO)",
                               f"{v*100:.1f}%" if v is not None else "—",
                               f"Bench: ≥95% · {ofr.get('cumplidos', 0)}/{ofr.get('total_con_pickings', 0)} SO",
                               color, sem), unsafe_allow_html=True)

        # OCT
        v = oct.get("valor")
        sem, color = _semaforo(v, 24, amarillo_max=72, mayor_es_mejor=False)
        c4.markdown(_kpi_card("OCT (orden→despacho)",
                               f"{v:.0f}h" if v is not None else "—",
                               f"Bench: <24h B2C/<72h B2B · {oct.get('n_orders', 0)} SO",
                               color, sem), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Fila 2: Operación interna bodega
        st.markdown("#### 🎯 Operación interna bodega (Odoo)")
        c5, c6, c7, c8 = st.columns(4)

        # Pick Accuracy
        v = pick_acc.get("valor")
        sem, color = _semaforo(v, 0.995, 0.98, mayor_es_mejor=True)
        c5.markdown(_kpi_card("Pick Accuracy",
                               f"{v*100:.2f}%" if v is not None else "—",
                               f"Bench: ≥99.5% · {pick_acc.get('total', 0)} moves",
                               color, sem), unsafe_allow_html=True)

        # Tiempo recepción
        v = tiempo_rec.get("valor")
        sem, color = _semaforo(v, 24, amarillo_max=72, mayor_es_mejor=False)
        c6.markdown(_kpi_card("Tiempo recepción",
                               f"{v:.0f}h" if v is not None else "—",
                               f"Bench: 24-72h · {tiempo_rec.get('n_recepciones', 0)} recep.",
                               color, sem), unsafe_allow_html=True)

        # Productividad picking (sincronizada por mes actual)
        if equipo and equipo.get("horas_total", 0) > 0:
            lineas = lineas_mes.get("lineas", 0)
            horas = equipo.get("horas_total", 0)
            v = lineas / horas if horas else None
            sem, color = _semaforo(v, 60, 40, mayor_es_mejor=True)
            c7.markdown(_kpi_card("Productividad picking",
                                   f"{v:.0f} líneas/h" if v is not None else "—",
                                   f"Bench: 60-120 · {lineas:,} líneas / {horas:,.0f}h ({mes_actual})",
                                   color, sem), unsafe_allow_html=True)
        else:
            c7.markdown(_kpi_card("Productividad picking", "—",
                                   f"Cargá horas equipo {mes_actual} (Tab 6)", "#94A3B8"),
                        unsafe_allow_html=True)

        # Ocupación bodega — # posiciones (exacto)
        try:
            from views.shared import cached_stock
            stock_data = cached_stock()
            ocup_pct = stock_data.get("ocupacion", {}).get("pct", 0) if stock_data else 0
            ocup_total = stock_data.get("ocupacion", {}).get("total", 0) if stock_data else 0
            ocup_occ = stock_data.get("ocupacion", {}).get("occupied", 0) if stock_data else 0
            sem, color = _semaforo(ocup_pct/100, 0.85, amarillo_max=0.95, mayor_es_mejor=False)
            c8.markdown(_kpi_card("Ocupación bodega",
                                   f"{ocup_pct:.0f}%" if ocup_total else "—",
                                   f"{ocup_occ}/{ocup_total} posiciones · m³ pausado (H2)",
                                   color, sem), unsafe_allow_html=True)
        except Exception:
            c8.markdown(_kpi_card("Ocupación bodega", "—", "Sin datos stock", "#94A3B8"),
                        unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Fila 3: Calidad del inventario (manuales)
        st.markdown("#### 🟡 Calidad del inventario (manuales)")
        c9, c10, c11, c12 = st.columns(4)

        # Exactitud inventario
        v = exactitud.get("valor")
        sem, color = _semaforo(v, 0.98, 0.95, mayor_es_mejor=True)
        c9.markdown(_kpi_card("Exactitud Inventario",
                               f"{v*100:.1f}%" if v is not None else "—",
                               f"Bench: ≥98% · {exactitud.get('total', 0)} cycle counts",
                               color, sem), unsafe_allow_html=True)

        # Cobertura cycle counts
        v = cobertura.get("valor")
        sem, color = _semaforo(v, 0.80, 0.50, mayor_es_mejor=True)
        c10.markdown(_kpi_card("Cobertura cycle counts (12m)",
                               f"{v*100:.1f}%" if v is not None else "—",
                               f"Bench: ≥80% · {cobertura.get('n_auditados', 0)}/{cobertura.get('total_skus', 0)} SKUs",
                               color, sem), unsafe_allow_html=True)

        # Merma operativa
        v = merma.get("valor")
        sem, color = _semaforo(v, 0.005, amarillo_max=0.01, mayor_es_mejor=False)
        c11.markdown(_kpi_card("Merma operativa",
                               f"{v*100:.2f}%" if v is not None else "—",
                               f"Bench: ≤0.5% · {merma.get('n_meses', 0)} meses",
                               color, sem), unsafe_allow_html=True)

        # Equipo bodega
        n_pers = equipo.get("personas", 0)
        n_horas = equipo.get("horas_total", 0)
        c12.markdown(_kpi_card("Equipo bodega (mes)",
                               f"{n_pers} personas" if n_pers else "—",
                               f"{n_horas:,.0f}h totales {mes_actual}",
                               "#1F4E79" if n_pers else "#94A3B8"),
                     unsafe_allow_html=True)

        st.divider()

        # Tabla resumen con benchmarks
        st.markdown("### 📋 Matriz de benchmarks vs mercado")
        bench = [
            {"KPI": "OTIF B2C", "Tu valor":
                f"{otif_b2c.get('valor',0)*100:.1f}%" if otif_b2c.get('valor') else "—",
             "Benchmark": "92-97%", "Fuente": "E-com chileno marketplaces"},
            {"KPI": "OTIF B2B", "Tu valor":
                f"{otif_b2b.get('valor',0)*100:.1f}%" if otif_b2b.get('valor') else "—",
             "Benchmark": "95-98%", "Fuente": "Cadenas retail Chile"},
            {"KPI": "OFR (Order Fulfillment Rate)", "Tu valor":
                f"{ofr.get('valor',0)*100:.1f}%" if ofr.get('valor') else "—",
             "Benchmark": "≥ 95%", "Fuente": "Plan estratégico UnionX"},
            {"KPI": "OCT (Order Cycle Time)", "Tu valor":
                f"{oct.get('valor',0):.0f}h" if oct.get('valor') else "—",
             "Benchmark": "<24h B2C / <72h B2B", "Fuente": "E-com Chile"},
            {"KPI": "Pick Accuracy", "Tu valor":
                f"{pick_acc.get('valor',0)*100:.2f}%" if pick_acc.get('valor') else "—",
             "Benchmark": "≥ 99.5%", "Fuente": "E-com retail multicategoría"},
            {"KPI": "Tiempo recepción", "Tu valor":
                f"{tiempo_rec.get('valor',0):.0f}h" if tiempo_rec.get('valor') else "—",
             "Benchmark": "24-72 horas", "Fuente": "Importadores con WMS"},
            {"KPI": "Exactitud de inventario", "Tu valor":
                f"{exactitud.get('valor',0)*100:.1f}%" if exactitud.get('valor') else "—",
             "Benchmark": "≥ 98% (clase mundial 99.5%)", "Fuente": "WMS-driven warehouses"},
            {"KPI": "Cobertura cycle counts (12m)", "Tu valor":
                f"{cobertura.get('valor',0)*100:.1f}%" if cobertura.get('valor') else "—",
             "Benchmark": "≥ 80% SKUs auditados/año", "Fuente": "Best practice WMS"},
            {"KPI": "Merma operativa", "Tu valor":
                f"{merma.get('valor',0)*100:.2f}%" if merma.get('valor') else "—",
             "Benchmark": "≤ 0.5% del inventario", "Fuente": "Retail multicategoría"},
        ]
        st.dataframe(pd.DataFrame(bench), use_container_width=True, hide_index=True)

        # Expander con errores capturados (no rompe los otros tabs)
        errs = st.session_state.get('_wms_errors', [])
        if errs:
            with st.expander(f"🐛 Errores helpers Odoo capturados ({len(errs)})", expanded=False):
                for e in errs[:10]:
                    st.code(e)
                if st.button("🧹 Limpiar errores", key="wms_clear_errs"):
                    st.session_state['_wms_errors'] = []
                    st.rerun()

    # ============================================================
    # TAB 2 — OTIF
    # ============================================================
    with tabs[1]:
        st.markdown("### 📦 OTIF (On-Time In-Full)")
        st.caption("Pickings entregados a tiempo Y completos. On-Time = date_done ≤ scheduled_date · In-Full = qty_done ≥ product_uom_qty")

        col_period, _ = st.columns([1, 3])
        with col_period:
            dias_otif = st.selectbox("Ventana", [7, 14, 30, 60, 90], index=2, key="otif_dias")

        otif_b2c_t = _safe_wms(kpi_otif, dias=dias_otif, canal_b2b=False)
        otif_b2b_t = _safe_wms(kpi_otif, dias=dias_otif, canal_b2b=True)

        st.markdown("#### B2C (clientes finales)")
        if otif_b2c_t.get("error"):
            st.warning(otif_b2c_t["error"])
        else:
            c1, c2, c3, c4 = st.columns(4)
            v = otif_b2c_t.get('valor', 0) or 0
            c1.metric("OTIF total", f"{v*100:.1f}%")
            c2.metric("On-Time", f"{otif_b2c_t.get('on_time_pct', 0)*100:.1f}%",
                      delta=f"{otif_b2c_t.get('on_time', 0)} pickings")
            c3.metric("In-Full", f"{otif_b2c_t.get('in_full_pct', 0)*100:.1f}%",
                      delta=f"{otif_b2c_t.get('in_full', 0)} pickings")
            c4.metric("Total pickings", f"{otif_b2c_t.get('total_pickings', 0)}")

        st.markdown("#### B2B (empresas)")
        if otif_b2b_t.get("error"):
            st.warning(otif_b2b_t["error"])
        else:
            c1, c2, c3, c4 = st.columns(4)
            v = otif_b2b_t.get('valor', 0) or 0
            c1.metric("OTIF total", f"{v*100:.1f}%")
            c2.metric("On-Time", f"{otif_b2b_t.get('on_time_pct', 0)*100:.1f}%",
                      delta=f"{otif_b2b_t.get('on_time', 0)} pickings")
            c3.metric("In-Full", f"{otif_b2b_t.get('in_full_pct', 0)*100:.1f}%",
                      delta=f"{otif_b2b_t.get('in_full', 0)} pickings")
            c4.metric("Total pickings", f"{otif_b2b_t.get('total_pickings', 0)}")

        st.divider()

        st.markdown("### 🏢 Top clientes B2B con peor OTIF")
        top = _safe_wms(top_clientes_otif_problemas, dias=dias_otif, top_n=15,
                        default={"valor": [], "error": None})
        if top.get("valor"):
            df = pd.DataFrame(top["valor"])
            df["on_time_pct"] = (df["on_time_pct"] * 100).round(1).astype(str) + "%"
            df.columns = ["Cliente", "Total Pickings", "Tarde", "% On-Time"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Sin datos")

    # ============================================================
    # TAB 3 — PICKING & OFR/OCT
    # ============================================================
    with tabs[2]:
        st.markdown("### 🎯 Pick Accuracy + OFR + OCT + Productividad")

        col_p, _ = st.columns([1, 3])
        with col_p:
            dias_p = st.selectbox("Ventana", [7, 14, 30, 60, 90], index=2, key="pick_dias")

        pick_acc_t = _safe_wms(kpi_pick_accuracy, dias=dias_p)
        ofr_t = _safe_wms(kpi_ofr, dias=dias_p)
        oct_t = _safe_wms(kpi_oct, dias=dias_p)

        # Pick Accuracy
        st.markdown("#### Pick Accuracy")
        if pick_acc_t.get("error"):
            st.warning(pick_acc_t["error"])
        else:
            c1, c2, c3 = st.columns(3)
            v = pick_acc_t.get('valor', 0) or 0
            c1.metric("Pick Accuracy", f"{v*100:.2f}%",
                      delta=f"{pick_acc_t.get('errores', 0)} errores")
            c2.metric("Total moves done", f"{pick_acc_t.get('total', 0):,}")
            c3.metric("Errores (qty mismatch)", f"{pick_acc_t.get('errores', 0):,}")

        st.divider()

        # OFR
        st.markdown("#### OFR (Order Fulfillment Rate)")
        st.caption("¿Qué % de pedidos confirmados terminó completo (todos los pickings done)?")
        if ofr_t.get("error"):
            st.warning(ofr_t["error"])
        else:
            c1, c2, c3, c4 = st.columns(4)
            v = ofr_t.get('valor', 0) or 0
            c1.metric("OFR", f"{v*100:.1f}%")
            c2.metric("Cumplidos", f"{ofr_t.get('cumplidos', 0):,}")
            c3.metric("Parciales", f"{ofr_t.get('parciales', 0):,}")
            c4.metric("Sin iniciar", f"{ofr_t.get('sin_iniciar', 0):,}")

        st.divider()

        # OCT
        st.markdown("#### OCT (Order Cycle Time)")
        st.caption("Horas entre confirmación venta y primer despacho. Bench: <24h B2C, <72h B2B.")
        if oct_t.get("error"):
            st.warning(oct_t["error"])
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("OCT promedio", f"{oct_t.get('valor', 0):.1f}h")
            c2.metric("Mediana", f"{oct_t.get('mediana_h', 0):.1f}h")
            c3.metric("Más rápido", f"{oct_t.get('min_h', 0):.1f}h")
            c4.metric("Más lento", f"{oct_t.get('max_h', 0):.1f}h")

            with st.expander("🐌 Top 20 SO con OCT más alto"):
                if oct_t.get("detalle"):
                    st.dataframe(pd.DataFrame(oct_t["detalle"]),
                                 use_container_width=True, hide_index=True)

        st.divider()

        # Productividad
        st.markdown("#### ⚡ Productividad picking (sincronizada por mes)")
        mes_actual = datetime.now().strftime("%Y-%m")
        equipo_t = _safe_wms(get_equipo_mes, mes_actual, default={}) or {}
        lineas_t = _safe_wms(kpi_lineas_pickeadas_mes, mes_actual, default={"lineas": 0})

        if not equipo_t or not equipo_t.get("horas_total"):
            st.info(f"📋 Cargá horas equipo de {mes_actual} en Tab 6 → Equipo bodega.")
        else:
            lineas = lineas_t.get("lineas", 0)
            horas = equipo_t.get("horas_total", 0)
            personas = equipo_t.get("personas", 0)
            prod = lineas / horas if horas else 0
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Productividad", f"{prod:.0f} líneas/h",
                      help="Benchmark: 60-120 líneas/h B2C")
            c2.metric("Equipo", f"{personas} personas")
            c3.metric(f"Líneas {mes_actual}", f"{lineas:,}")
            c4.metric("Horas total mes", f"{horas:,.0f}h")

    # ============================================================
    # TAB 4 — RECEPCIONES
    # ============================================================
    with tabs[3]:
        st.markdown("### 📥 Recepciones")
        st.caption("Tiempo entre fecha programada y fecha efectiva de recepción de embarques")

        col_r, _ = st.columns([1, 3])
        with col_r:
            dias_r = st.selectbox("Ventana", [30, 60, 90, 180, 365], index=2, key="rec_dias")

        rec = _safe_wms(kpi_tiempo_recepcion, dias=dias_r)

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

        vol = _safe_wms(kpi_volumen_movimientos, dias=dias_r)
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
    # TAB 5 — TENDENCIA MENSUAL
    # ============================================================
    with tabs[4]:
        st.markdown("### 📈 Tendencia mes a mes")
        st.caption("Evolución de OTIF B2C/B2B + Pick Accuracy en los últimos meses")

        col_m, _ = st.columns([1, 3])
        with col_m:
            n_meses = st.selectbox("Meses históricos", [3, 6, 9, 12], index=1, key="tend_meses")

        with st.spinner(f"Calculando tendencia {n_meses} meses (puede tardar 30-60s)…"):
            tend = _safe_wms(tendencia_mensual, meses=n_meses, default=[])

        if not tend:
            st.info("Sin datos históricos disponibles")
        else:
            df_tend = pd.DataFrame(tend)
            # Convertir a porcentaje legible
            for col in ["otif_b2c", "otif_b2b", "pick_acc"]:
                if col in df_tend.columns:
                    df_tend[col + "_pct"] = (df_tend[col] * 100).round(1)

            # Gráfico líneas
            chart_data = df_tend.set_index("mes")[
                [c for c in ["otif_b2c_pct", "otif_b2b_pct", "pick_acc_pct"] if c in df_tend.columns]
            ].rename(columns={
                "otif_b2c_pct": "OTIF B2C (%)",
                "otif_b2b_pct": "OTIF B2B (%)",
                "pick_acc_pct": "Pick Accuracy (%)",
            })
            st.line_chart(chart_data, height=380)

            # Tabla detalle
            st.markdown("#### Detalle por mes")
            df_show = df_tend[[
                "mes",
                *[c for c in ["otif_b2c_pct", "otif_b2b_pct", "pick_acc_pct"] if c in df_tend.columns],
                "n_pickings", "n_b2c", "n_b2b",
            ]].rename(columns={
                "mes": "Mes",
                "otif_b2c_pct": "OTIF B2C %",
                "otif_b2b_pct": "OTIF B2B %",
                "pick_acc_pct": "Pick Acc %",
                "n_pickings": "# Pickings",
                "n_b2c": "B2C",
                "n_b2b": "B2B",
            })
            st.dataframe(df_show, use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 6 — ANÁLISIS PEDIDOS (Odoo)
    # ============================================================
    with tabs[5]:
        from views._ops_analytics_helper import (
            ventas_por_mes, top_skus, ventas_por_canal,
            ventas_por_categoria, ventas_por_marca, detalle_pedidos,
        )

        st.markdown("### 🛒 Análisis de pedidos (Odoo)")
        st.caption("Pedidos · unidades · venta agregada cruzando SKU · canal · categoría · marca")

        col_v, _ = st.columns([1, 3])
        with col_v:
            ventana = st.selectbox("Ventana análisis (días)", [30, 60, 90, 180, 365],
                                   index=2, key="an_ventana")

        analytics_subtabs = st.tabs([
            "📅 Por mes",
            "🏆 Top SKUs",
            "🛍️ Por canal (B2C/B2B)",
            "📦 Por categoría",
            "🏷️ Por marca",
            "🔍 Detalle pedidos",
        ])

        # ── 6.1 Por mes ────────────────────────────────────────────────
        with analytics_subtabs[0]:
            st.markdown("#### Pedidos / unidades / monto por mes")
            n_meses_a = st.selectbox("Meses históricos", [3, 6, 9, 12, 18, 24],
                                     index=3, key="an_meses")
            with st.spinner(f"Calculando {n_meses_a} meses…"):
                vm = _safe_wms(ventas_por_mes, meses=n_meses_a, default=[])

            if not vm:
                st.info("Sin datos")
            else:
                df_vm = pd.DataFrame(vm)

                # KPIs totales
                t_ped = df_vm["n_pedidos"].sum()
                t_uds = df_vm["n_unidades"].sum()
                t_mto = df_vm["monto"].sum()
                ck1, ck2, ck3, ck4 = st.columns(4)
                ck1.metric(f"Pedidos {n_meses_a}m", f"{t_ped:,}")
                ck2.metric(f"Unidades {n_meses_a}m", f"{t_uds:,}")
                ck3.metric(f"Venta {n_meses_a}m", f"${t_mto/1e6:,.1f}M")
                ck4.metric("Ticket promedio",
                           f"${(t_mto/t_ped):,.0f}" if t_ped else "—")

                st.markdown("##### Evolución mensual")
                # Gráfico pedidos + unidades (escalas distintas, 2 charts)
                gc1, gc2 = st.columns(2)
                with gc1:
                    st.markdown("**Pedidos por mes**")
                    st.bar_chart(df_vm.set_index("mes")["n_pedidos"], height=280)
                with gc2:
                    st.markdown("**Unidades por mes**")
                    st.bar_chart(df_vm.set_index("mes")["n_unidades"], height=280)
                st.markdown("**Venta ($ MM) por mes**")
                df_vm_m = df_vm.copy()
                df_vm_m["venta_MM"] = (df_vm_m["monto"] / 1e6).round(2)
                st.line_chart(df_vm_m.set_index("mes")["venta_MM"], height=280)

                # Tabla
                st.markdown("##### Tabla detalle")
                df_show = df_vm.copy()
                df_show["monto"] = df_show["monto"].apply(lambda v: f"${v:,.0f}")
                df_show["ticket_promedio"] = df_show["ticket_promedio"].apply(lambda v: f"${v:,.0f}")
                df_show.columns = ["Mes", "# Pedidos", "Unidades", "Monto", "Ticket prom."]
                st.dataframe(df_show, use_container_width=True, hide_index=True)

        # ── 6.2 Top SKUs ───────────────────────────────────────────────
        with analytics_subtabs[1]:
            st.markdown(f"#### Top SKUs (últimos {ventana} días)")
            top_n_sk = st.slider("Top N", 10, 100, 30, key="an_topn")
            with st.spinner("Consultando Odoo…"):
                ts = _safe_wms(top_skus, dias=ventana, top_n=top_n_sk,
                               default={"items": [], "error": None})
            if ts.get("error"):
                st.warning(ts["error"])
            elif ts.get("items"):
                df_ts = pd.DataFrame(ts["items"])
                df_ts["monto"] = df_ts["monto"].apply(lambda v: f"${v:,.0f}")
                df_ts["ticket_promedio_uds"] = df_ts["ticket_promedio_uds"].round(1)
                df_show = df_ts[["sku", "n_pedidos", "unidades", "monto", "ticket_promedio_uds"]].rename(
                    columns={"sku": "SKU", "n_pedidos": "# Pedidos",
                             "unidades": "Unidades", "monto": "Venta",
                             "ticket_promedio_uds": "Uds/pedido"})
                st.dataframe(df_show, use_container_width=True, hide_index=True, height=520)
                st.caption(f"Total SKUs distintos vendidos: {ts.get('total_skus_distintos', 0):,}")
            else:
                st.info("Sin datos")

        # ── 6.3 Por canal ──────────────────────────────────────────────
        with analytics_subtabs[2]:
            st.markdown(f"#### Mix por canal — últimos {ventana} días")
            with st.spinner("Consultando Odoo…"):
                vc = _safe_wms(ventas_por_canal, dias=ventana,
                               default={"items": [], "error": None})
            if vc.get("error"):
                st.warning(vc["error"])
            elif vc.get("items"):
                df_vc = pd.DataFrame(vc["items"])
                # KPIs comparativos
                cc1, cc2 = st.columns(2)
                for i, (col, row) in enumerate(zip([cc1, cc2], vc["items"])):
                    canal = row["canal"]
                    col.metric(f"Pedidos {canal}", f"{row['n_pedidos']:,}",
                               delta=f"{row['n_clientes']} clientes")
                    col.metric(f"Venta {canal}", f"${row['monto']/1e6:,.1f}M")
                    col.metric(f"Ticket prom. {canal}", f"${row['ticket_prom']:,.0f}")
                st.markdown("##### Tabla")
                df_show = df_vc.copy()
                df_show["monto"] = df_show["monto"].apply(lambda v: f"${v:,.0f}")
                df_show["ticket_prom"] = df_show["ticket_prom"].apply(lambda v: f"${v:,.0f}")
                st.dataframe(df_show, use_container_width=True, hide_index=True)

                # Pie chart simple via bar chart
                st.markdown("##### Distribución $ por canal")
                df_chart = pd.DataFrame(vc["items"]).set_index("canal")["monto"]
                st.bar_chart(df_chart, height=200)

        # ── 6.4 Por categoría ──────────────────────────────────────────
        with analytics_subtabs[3]:
            st.markdown(f"#### Mix por categoría — últimos {ventana} días")
            with st.spinner("Consultando Odoo…"):
                vcat = _safe_wms(ventas_por_categoria, dias=ventana,
                                 default={"items": [], "error": None})
            if vcat.get("error"):
                st.warning(vcat["error"])
            elif vcat.get("items"):
                df_vcat = pd.DataFrame(vcat["items"])
                df_show = df_vcat.copy()
                df_show["monto"] = df_show["monto"].apply(lambda v: f"${v:,.0f}")
                df_show.columns = ["Categoría", "Unidades", "Venta", "# SKUs"]
                st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)
                st.markdown("##### Top 10 categorías por venta")
                df_chart = df_vcat.head(10).set_index("categoria")["monto"]
                st.bar_chart(df_chart, height=300)

        # ── 6.5 Por marca ──────────────────────────────────────────────
        with analytics_subtabs[4]:
            st.markdown(f"#### Mix por marca — últimos {ventana} días")
            st.caption("Marca extraída del display_name (heurística). Si Odoo tiene un campo "
                       "custom de marca, se puede mejorar.")
            with st.spinner("Consultando Odoo…"):
                vm_marca = _safe_wms(ventas_por_marca, dias=ventana,
                                     default={"items": [], "error": None})
            if vm_marca.get("error"):
                st.warning(vm_marca["error"])
            elif vm_marca.get("items"):
                df_vm_marca = pd.DataFrame(vm_marca["items"])
                df_show = df_vm_marca.copy()
                df_show["monto"] = df_show["monto"].apply(lambda v: f"${v:,.0f}")
                df_show.columns = ["Marca", "Unidades", "Venta", "# SKUs"]
                st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)
                st.markdown("##### Top 10 marcas por venta")
                df_chart = df_vm_marca.head(10).set_index("marca")["monto"]
                st.bar_chart(df_chart, height=300)

        # ── 6.6 Detalle pedidos ────────────────────────────────────────
        with analytics_subtabs[5]:
            st.markdown(f"#### Detalle pedidos (últimos {ventana} días)")
            top_n_d = st.slider("Mostrar últimos N pedidos", 50, 1000, 200, key="an_topn_d")
            with st.spinner("Consultando Odoo…"):
                det = _safe_wms(detalle_pedidos, dias=ventana, top_n=top_n_d,
                                default={"items": [], "error": None})
            if det.get("error"):
                st.warning(det["error"])
            elif det.get("items"):
                df_det = pd.DataFrame(det["items"])

                # Filtros locales
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    canal_f = st.multiselect("Canal", ["B2C", "B2B"],
                                             default=["B2C", "B2B"], key="an_f_canal")
                with fc2:
                    cats_avail = sorted(df_det["categoria"].dropna().unique().tolist())
                    cat_f = st.multiselect("Categoría", cats_avail, key="an_f_cat")
                with fc3:
                    marcas_avail = sorted(df_det["marca"].dropna().unique().tolist())
                    marca_f = st.multiselect("Marca", marcas_avail, key="an_f_marca")

                df_f = df_det.copy()
                if canal_f:
                    df_f = df_f[df_f["canal"].isin(canal_f)]
                if cat_f:
                    df_f = df_f[df_f["categoria"].isin(cat_f)]
                if marca_f:
                    df_f = df_f[df_f["marca"].isin(marca_f)]

                st.dataframe(
                    df_f.assign(monto=lambda d: d["monto"].apply(lambda v: f"${v:,.0f}")),
                    use_container_width=True, hide_index=True, height=520,
                )
                st.caption(f"{len(df_f):,} líneas · {df_f['unidades'].sum():,} uds · "
                           f"${df_det.loc[df_f.index, 'monto'].sum():,.0f}")

                # Descarga
                import io
                out_det = io.BytesIO()
                with pd.ExcelWriter(out_det, engine='openpyxl') as w:
                    df_f.to_excel(w, index=False, sheet_name='Pedidos')
                out_det.seek(0)
                st.download_button(
                    label=f"📥 Descargar pedidos filtrados (Excel · {len(df_f):,})",
                    data=out_det.getvalue(),
                    file_name=f"Pedidos_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    key="an_dl_pedidos",
                    use_container_width=True,
                )

    # ============================================================
    # TAB 7 — DATOS MANUALES
    # ============================================================
    with tabs[6]:
        st.markdown("### 📋 Carga de datos manuales")
        st.caption("Datos que NO vienen de Odoo y necesitan carga periódica.")

        st.warning(
            "⚠️ **Datos persistidos en JSON local.** En Streamlit Cloud, se pierden "
            "al re-deploy. Para persistencia real (H2): migrar a Turso (libSQL). "
            "Por ahora cargar datos críticos al inicio de cada sesión."
        )

        sub_tabs = st.tabs([
            "👥 Equipo bodega",
            "🏭 Capacidad (m³ pausado)",
            "📋 Cycle counts",
            "📉 Merma",
        ])

        # ---- Equipo bodega ----
        with sub_tabs[0]:
            st.markdown("#### Equipo bodega — horas trabajadas por mes")
            st.caption("Necesario para calcular productividad picking (líneas/h)")

            mes_input = st.text_input("Mes (YYYY-MM)",
                                       value=datetime.now().strftime("%Y-%m"),
                                       key="eq_mes")
            actual = get_equipo_mes(mes_input)
            c1, c2 = st.columns(2)
            personas = c1.number_input("Personas activas", min_value=0, max_value=200, step=1,
                                        value=int(actual.get("personas", 0)), key="eq_personas")
            horas = c2.number_input("Horas total trabajadas en el mes", min_value=0.0, step=10.0,
                                     value=float(actual.get("horas_total", 0)), key="eq_horas")
            if st.button("💾 Guardar equipo", key="eq_save"):
                if set_equipo_mes(mes_input, int(personas), float(horas)):
                    st.success(f"✅ Guardado para {mes_input}")
                    st.cache_data.clear()
                else:
                    st.error("❌ Error guardando")

        # ---- Capacidad bodega (m³ pausado) ----
        with sub_tabs[1]:
            st.markdown("#### Capacidad de bodega")
            st.warning(
                "🚧 **m³ pausado — Roadmap H2** · Las métricas de m³ requieren las dimensiones "
                "de **caja master** (no la unidad individual de Odoo). Cuando se cargue caja master, "
                "se reactivan: m³ disponible por posición + capacidad para próximos embarques."
            )
            st.markdown("Mientras tanto, **Ocupación bodega** se mide por **# posiciones** (exacto, "
                       "ver Tab Resumen).")

            actual = get_capacidad_bodega()
            current_m3 = actual.get("m3_totales") or 0.0
            m3 = st.number_input("Capacidad total m³ (informativo, no usado activamente)",
                                  min_value=0.0, step=10.0, value=float(current_m3), key="cap_m3")
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
            st.caption("Cargar resultados para calcular Exactitud Inventario + Cobertura.")

            cobertura_t = _safe_wms(kpi_cobertura_cycle_counts, meses=12, default={"valor": None})
            if cobertura_t.get("valor") is not None:
                cv = cobertura_t["valor"]
                ic = "🟢" if cv >= 0.80 else ("🟡" if cv >= 0.50 else "🔴")
                st.metric(f"{ic} Cobertura últimos 12m",
                          f"{cv*100:.1f}%",
                          help=f"{cobertura_t.get('n_auditados', 0)} SKUs únicos auditados de "
                               f"{cobertura_t.get('total_skus', 0)} totales")

            with st.form("cc_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                sku = c1.text_input("SKU", key="cc_sku")
                qty_sis = c2.number_input("Qty Sistema", min_value=0.0, step=1.0, key="cc_qsis")
                qty_fis = c3.number_input("Qty Física", min_value=0.0, step=1.0, key="cc_qfis")
                fecha = st.text_input("Fecha (YYYY-MM-DD)",
                                       value=datetime.now().strftime("%Y-%m-%d"), key="cc_fecha")
                nota = st.text_input("Nota (opcional)", key="cc_nota")
                if st.form_submit_button("➕ Agregar cycle count", type="primary"):
                    if sku and (qty_fis > 0 or qty_sis > 0):
                        if add_cycle_count(sku, qty_sis, qty_fis, fecha, nota):
                            st.success(f"✅ Agregado: {sku}")
                            st.cache_data.clear()
                        else:
                            st.error("❌ Error guardando")
                    else:
                        st.warning("Ingresá SKU + cantidades")

            counts = get_cycle_counts()
            if counts:
                st.markdown(f"##### Histórico ({len(counts)} cycle counts)")
                df = pd.DataFrame(counts[:50])
                st.dataframe(df, use_container_width=True, hide_index=True, height=300)

        # ---- Merma ----
        with sub_tabs[3]:
            st.markdown("#### Merma operativa por mes")
            mes_m = st.text_input("Mes (YYYY-MM)",
                                   value=datetime.now().strftime("%Y-%m"), key="m_mes")
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
                    st.cache_data.clear()
                else:
                    st.error("❌ Error guardando")
