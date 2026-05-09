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
    kpi_merma_odoo, kpi_ajustes_inventario,
    plan_auditoria_semanal, productividad_periodo, forecast_volumen_picking,
)
from views._ops_data_helper import (
    get_equipo_mes, set_equipo_mes,
    get_capacidad_bodega, set_capacidad_bodega,
    add_cycle_count, get_cycle_counts, kpi_exactitud_inventario,
    set_merma_mes, get_merma_mes, kpi_merma_operativa,
    calcular_horas_estandar_mes, get_storage_status,
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
        "📋 Datos manuales",         # 0 — primero (instantáneo)
        "📊 Resumen",                # 1
        "📦 OTIF (B2C/B2B)",         # 2
        "🎯 Picking & Productividad", # 3
        "📥 Recepciones",            # 4
        "🔍 Auditoría inventario",   # 5 ← NUEVO (cycle counts + merma + plan semanal)
        "📈 Tendencia mensual",      # 6
        "🛒 Análisis pedidos",       # 7
    ])

    # ============================================================
    # TAB 0 — DATOS MANUALES (primero para garantizar render)
    # No toca Odoo. Aparece instantáneo.
    # ============================================================
    try:
        with tabs[0]:
            st.markdown("### 📋 Carga de datos manuales")
            st.caption("Datos que NO vienen de Odoo. Renderiza instantáneo.")

            # Status del storage (Turso o JSON)
            ss = get_storage_status()
            if ss["turso_alcanzable"]:
                st.success(f"💾 **Persistencia: {ss['storage_actual']}** · "
                           "Datos guardados sobreviven re-deploys.")
            else:
                st.warning(
                    f"⚠️ **Persistencia: {ss['storage_actual']}** · "
                    f"{ss.get('advertencia', '')} "
                    "Para activar Turso: setear `LIBSQL_URL` y `LIBSQL_AUTH_TOKEN` "
                    "en Streamlit Secrets."
                )

            sub_tabs_dm = st.tabs([
                "👥 Equipo bodega",
                "🏭 Capacidad (m³ pausado)",
            ])
            st.caption(
                "ℹ️ **Cycle counts** y **Merma** ahora son automáticos desde Odoo "
                "(`stock.move` → ubicación `Inventory adjustment` y modelo `stock.scrap`). "
                "Los encontrás en la tab **🔍 Auditoría inventario**."
            )

            with sub_tabs_dm[0]:
                st.markdown("#### Equipo bodega — horas trabajadas por mes")
                st.caption(
                    "Necesario para calcular productividad picking (líneas/h). "
                    "Horario estándar UnionX: L-J 8-18 con 1h almuerzo (9h) · V 8-15 con 1h almuerzo (6h) "
                    "= 42 hrs/sem por persona."
                )
                mes_input = st.text_input("Mes (YYYY-MM)",
                                           value=datetime.now().strftime("%Y-%m"),
                                           key="eq_mes_top")
                actual_eq = get_equipo_mes(mes_input) or {}

                c1, c2 = st.columns(2)
                personas = c1.number_input("Personas activas", min_value=0, max_value=200, step=1,
                                            value=int(actual_eq.get("personas") or 0),
                                            key="eq_personas_top")
                horas = c2.number_input("Horas total trabajadas en el mes", min_value=0.0, step=10.0,
                                         value=float(actual_eq.get("horas_total") or 0),
                                         key="eq_horas_top")

                # Botón calcular automático con horario estándar
                ce1, ce2 = st.columns([1, 1])
                with ce1:
                    if st.button("📐 Calcular horas estándar del mes",
                                 key="eq_calc_btn", use_container_width=True):
                        if personas > 0:
                            calc = calcular_horas_estandar_mes(mes_input, int(personas))
                            if calc.get("error"):
                                st.error(calc["error"])
                            else:
                                st.session_state['eq_horas_top'] = float(calc["horas_total"])
                                st.success(
                                    f"✅ Calculado: {calc['horas_total']} h "
                                    f"({calc['n_lj']} L-J × 9h + {calc['n_v']} V × 6h "
                                    f"= {calc['horas_persona']} h/persona × {personas})"
                                )
                                st.rerun()
                        else:
                            st.warning("Ingresá # personas primero")
                with ce2:
                    if st.button("💾 Guardar equipo", key="eq_save_top",
                                 type="primary", use_container_width=True):
                        if set_equipo_mes(mes_input, int(personas), float(horas)):
                            st.success(f"✅ Guardado para {mes_input}")
                            st.cache_data.clear()
                        else:
                            st.error("❌ Error guardando")

            with sub_tabs_dm[1]:
                st.markdown("#### Capacidad de bodega")
                st.warning(
                    "🚧 **m³ pausado — Roadmap H2** · Requiere dimensiones de **caja master** "
                    "(no la unidad individual). Mientras tanto, **Ocupación bodega** se mide por "
                    "**# posiciones** (Tab Resumen)."
                )
                actual_cap = get_capacidad_bodega() or {}
                current_m3 = actual_cap.get("m3_totales") or 0.0
                m3 = st.number_input("Capacidad total m³ (informativo)",
                                      min_value=0.0, step=10.0,
                                      value=float(current_m3), key="cap_m3_top")
                if st.button("💾 Guardar capacidad", key="cap_save_top"):
                    if set_capacidad_bodega(float(m3)):
                        st.success(f"✅ Capacidad: {m3:,.0f} m³")
                    else:
                        st.error("❌ Error guardando")
                if actual_cap.get("fecha_actualizacion"):
                    st.caption(f"Última actualización: {actual_cap['fecha_actualizacion'][:16]}")

    except Exception as e:
        st.error(f"❌ Error en Tab Datos manuales: {type(e).__name__}: {e}")

    # ============================================================
    # TAB 1 — RESUMEN
    # ============================================================
    with tabs[1]:
        st.markdown("### KPIs principales — comparado con benchmarks de mercado")

        # Snapshot pre-calculado por GH Action a 00:00 y 12:00 Chile.
        # Lectura instantánea (no toca Odoo en runtime).
        from views._ops_kpis_snapshot import snapshot_status
        ss_st = snapshot_status()

        if ss_st["existe"] and ss_st["fresco"]:
            st.success(f"📸 {ss_st['leyenda']}")
        elif ss_st["existe"]:
            st.warning(f"📸 {ss_st['leyenda']}")
        else:
            st.error(
                f"📸 {ss_st['leyenda']} · "
                "GH Action `sync_kpis_wms.yml` debe correr para generar snapshot."
            )

        # Botón opcional para refresh manual on-demand
        with st.expander("🔄 Forzar refresh ahora (consultar Odoo en vivo, lento)",
                         expanded=False):
            st.caption("30-90s. Solo necesario si el snapshot falló o querés datos al minuto.")
            if st.button("🔄 Recargar desde Odoo", key="resumen_force_refresh"):
                st.session_state['resumen_loaded'] = True
                st.cache_data.clear()
                st.rerun()

        if st.session_state.get('resumen_loaded') or not ss_st["existe"]:
            # Modo Odoo en vivo (refresh manual o snapshot vacío)
            if not ss_st["existe"]:
                st.warning(
                    "Snapshot vacío. Ejecutando queries Odoo en vivo "
                    "(30-90s primera vez)…"
                )

            # Cargar datos (defensivo: cualquier crash no debe romper Tabs 2-6)
            otif_b2c = _safe_wms(kpi_otif, dias=30, canal_b2b=False)
            otif_b2b = _safe_wms(kpi_otif, dias=30, canal_b2b=True)
            pick_acc = _safe_wms(kpi_pick_accuracy, dias=30)
            tiempo_rec = _safe_wms(kpi_tiempo_recepcion, dias=90)
            ofr = _safe_wms(kpi_ofr, dias=30)
            oct = _safe_wms(kpi_oct, dias=30)
            exactitud = _safe_wms(kpi_exactitud_inventario, dias=30, default={"valor": None, "total": 0})
            # Merma: priorizar Odoo (stock.scrap) sobre manual
            merma_odoo_t = _safe_wms(kpi_merma_odoo, dias=90, default={"valor": None, "n_scraps": 0})
            merma_manual = _safe_wms(kpi_merma_operativa, default={"valor": None, "n_meses": 0})
            if merma_odoo_t.get("valor") is not None:
                merma = merma_odoo_t
                merma["fuente"] = "Odoo (90d)"
            else:
                merma = merma_manual
                merma["fuente"] = "Manual"
            # Cobertura: priorizar ajustes de inventario Odoo sobre cycle counts manuales
            ajustes_t = _safe_wms(kpi_ajustes_inventario, desde_fecha="2026-04-01",
                                  default={"cobertura_pct": None, "n_skus_unicos": 0})
            if ajustes_t.get("cobertura_pct") is not None:
                cobertura = {
                    "valor": ajustes_t.get("cobertura_pct"),
                    "n_auditados": ajustes_t.get("n_skus_unicos", 0),
                    "total_skus": ajustes_t.get("total_skus_activos", 0),
                    "fuente": "Odoo ajustes desde 2026-04",
                }
            else:
                cobertura = _safe_wms(kpi_cobertura_cycle_counts, meses=12, default={"valor": None})
                cobertura["fuente"] = "Cycle counts manuales"

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

            # Cobertura cycle counts (Odoo ajustes con fallback manual)
            v = cobertura.get("valor")
            sem, color = _semaforo(v, 0.80, 0.50, mayor_es_mejor=True)
            sub_cob = cobertura.get('fuente', '')
            c10.markdown(_kpi_card("Cobertura ajustes inventario",
                                   f"{v*100:.1f}%" if v is not None else "—",
                                   f"Bench: ≥80% · {cobertura.get('n_auditados', 0)}/{cobertura.get('total_skus', 0)} · {sub_cob}",
                                   color, sem), unsafe_allow_html=True)

            # Merma operativa (Odoo stock.scrap con fallback manual)
            v = merma.get("valor")
            sem, color = _semaforo(v, 0.005, amarillo_max=0.01, mayor_es_mejor=False)
            sub_merma = merma.get('fuente', '')
            c11.markdown(_kpi_card("Merma operativa",
                                   f"{v*100:.2f}%" if v is not None else "—",
                                   f"Bench: ≤0.5% · {sub_merma}",
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
        else:
            # Modo snapshot: lectura instantánea del JSON pre-calculado
            from views._ops_kpis_snapshot import cargar_snapshot
            snap = cargar_snapshot()
            kpis = snap.get("kpis", {})

            otif_b2c = kpis.get("otif_b2c_30d", {})
            otif_b2b = kpis.get("otif_b2b_30d", {})
            pick_acc = kpis.get("pick_accuracy_30d", {})
            tiempo_rec = kpis.get("tiempo_recepcion_90d", {})
            ofr = kpis.get("ofr_30d", {})
            oct = kpis.get("oct_30d", {})
            merma = kpis.get("merma_odoo_90d", {})
            ajustes = kpis.get("ajustes_inventario", {})

            # Productividad/equipo (manuales — siempre frescos desde Turso)
            mes_actual = datetime.now().strftime("%Y-%m")
            equipo = get_equipo_mes(mes_actual) or {}
            lineas_mes = kpis.get("lineas_mes_actual", {})

            # Fila 1: Cumplimiento al cliente
            st.markdown("#### 📦 Cumplimiento al cliente (Odoo)")
            c1, c2, c3, c4 = st.columns(4)

            v = otif_b2c.get("valor")
            sem, color = _semaforo(v, 0.97, 0.92, mayor_es_mejor=True)
            c1.markdown(_kpi_card("OTIF B2C",
                                   f"{v*100:.1f}%" if v is not None else "—",
                                   f"Bench: 92-97% · {otif_b2c.get('total_pickings', 0)} pickings",
                                   color, sem), unsafe_allow_html=True)

            v = otif_b2b.get("valor")
            sem, color = _semaforo(v, 0.98, 0.95, mayor_es_mejor=True)
            c2.markdown(_kpi_card("OTIF B2B",
                                   f"{v*100:.1f}%" if v is not None else "—",
                                   f"Bench: 95-98% · {otif_b2b.get('total_pickings', 0)} pickings",
                                   color, sem), unsafe_allow_html=True)

            v = ofr.get("valor")
            sem, color = _semaforo(v, 0.95, 0.85, mayor_es_mejor=True)
            c3.markdown(_kpi_card("OFR (cumplim. SO)",
                                   f"{v*100:.1f}%" if v is not None else "—",
                                   f"Bench: ≥95% · {ofr.get('cumplidos', 0)}/{ofr.get('total_con_pickings', 0)} SO",
                                   color, sem), unsafe_allow_html=True)

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

            v = pick_acc.get("valor")
            sem, color = _semaforo(v, 0.995, 0.98, mayor_es_mejor=True)
            c5.markdown(_kpi_card("Pick Accuracy",
                                   f"{v*100:.2f}%" if v is not None else "—",
                                   f"Bench: ≥99.5% · {pick_acc.get('total', 0)} moves",
                                   color, sem), unsafe_allow_html=True)

            v = tiempo_rec.get("valor")
            sem, color = _semaforo(v, 24, amarillo_max=72, mayor_es_mejor=False)
            c6.markdown(_kpi_card("Tiempo recepción",
                                   f"{v:.0f}h" if v is not None else "—",
                                   f"Bench: 24-72h · {tiempo_rec.get('n_recepciones', 0)} recep.",
                                   color, sem), unsafe_allow_html=True)

            # Productividad
            if equipo and equipo.get("horas_total", 0) > 0:
                lineas = lineas_mes.get("lineas", 0)
                horas = equipo.get("horas_total", 0)
                v = lineas / horas if horas else None
                sem, color = _semaforo(v, 60, 40, mayor_es_mejor=True)
                c7.markdown(_kpi_card("Productividad picking",
                                       f"{v:.0f} líneas/h" if v is not None else "—",
                                       f"Bench: 60-120 · {lineas:,} L / {horas:,.0f}h ({mes_actual})",
                                       color, sem), unsafe_allow_html=True)
            else:
                c7.markdown(_kpi_card("Productividad picking", "—",
                                       f"Cargá horas equipo {mes_actual}", "#94A3B8"),
                            unsafe_allow_html=True)

            # Ocupación bodega
            try:
                from views.shared import cached_stock
                stock_data = cached_stock()
                ocup_pct = stock_data.get("ocupacion", {}).get("pct", 0) if stock_data else 0
                ocup_total = stock_data.get("ocupacion", {}).get("total", 0) if stock_data else 0
                ocup_occ = stock_data.get("ocupacion", {}).get("occupied", 0) if stock_data else 0
                sem, color = _semaforo(ocup_pct/100, 0.85, amarillo_max=0.95, mayor_es_mejor=False)
                c8.markdown(_kpi_card("Ocupación bodega",
                                       f"{ocup_pct:.0f}%" if ocup_total else "—",
                                       f"{ocup_occ}/{ocup_total} posiciones",
                                       color, sem), unsafe_allow_html=True)
            except Exception:
                c8.markdown(_kpi_card("Ocupación bodega", "—", "Sin datos", "#94A3B8"),
                            unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # Fila 3: Calidad inventario (snapshot tiene merma + ajustes Odoo)
            st.markdown("#### 🟡 Calidad del inventario")
            c9, c10, c11, c12 = st.columns(4)

            cob_pct = ajustes.get("cobertura_pct")
            sem, color = _semaforo(cob_pct, 0.80, 0.50, mayor_es_mejor=True)
            c9.markdown(_kpi_card("Cobertura ajustes inv.",
                                   f"{cob_pct*100:.1f}%" if cob_pct is not None else "—",
                                   f"Bench: ≥80% · {ajustes.get('n_skus_unicos', 0)}/{ajustes.get('total_skus_activos', 0)}",
                                   color, sem), unsafe_allow_html=True)

            v = merma.get("valor")
            sem, color = _semaforo(v, 0.005, amarillo_max=0.01, mayor_es_mejor=False)
            c10.markdown(_kpi_card("Merma operativa",
                                   f"{v*100:.2f}%" if v is not None else "—",
                                   f"Bench: ≤0.5% · {merma.get('n_scraps', 0)} scraps (90d)",
                                   color, sem), unsafe_allow_html=True)

            n_pers = equipo.get("personas", 0)
            n_horas = equipo.get("horas_total", 0)
            c11.markdown(_kpi_card("Equipo bodega (mes)",
                                   f"{n_pers} personas" if n_pers else "—",
                                   f"{n_horas:,.0f}h totales {mes_actual}",
                                   "#1F4E79" if n_pers else "#94A3B8"),
                         unsafe_allow_html=True)

            # Tipo cambio: usar últimas 30d como referencia
            n_aj = ajustes.get("n_ajustes", 0)
            c12.markdown(_kpi_card("# Ajustes inventario", f"{n_aj:,}",
                                   "Desde 2026-04 (modulo Odoo)", "#1F4E79"),
                         unsafe_allow_html=True)

            st.divider()

            # Tabla benchmarks
            st.markdown("### 📋 Matriz de benchmarks vs mercado")
            bench = [
                {"KPI": "OTIF B2C", "Tu valor":
                    f"{otif_b2c.get('valor',0)*100:.1f}%" if otif_b2c.get('valor') else "—",
                 "Benchmark": "92-97%", "Fuente": "E-com chileno"},
                {"KPI": "OTIF B2B", "Tu valor":
                    f"{otif_b2b.get('valor',0)*100:.1f}%" if otif_b2b.get('valor') else "—",
                 "Benchmark": "95-98%", "Fuente": "Cadenas retail Chile"},
                {"KPI": "OFR (Order Fulfillment)", "Tu valor":
                    f"{ofr.get('valor',0)*100:.1f}%" if ofr.get('valor') else "—",
                 "Benchmark": "≥ 95%", "Fuente": "Plan estratégico UnionX"},
                {"KPI": "OCT (Order Cycle Time)", "Tu valor":
                    f"{oct.get('valor',0):.0f}h" if oct.get('valor') else "—",
                 "Benchmark": "<24h B2C / <72h B2B", "Fuente": "E-com Chile"},
                {"KPI": "Pick Accuracy", "Tu valor":
                    f"{pick_acc.get('valor',0)*100:.2f}%" if pick_acc.get('valor') else "—",
                 "Benchmark": "≥ 99.5%", "Fuente": "WMS multicategoría"},
                {"KPI": "Tiempo recepción", "Tu valor":
                    f"{tiempo_rec.get('valor',0):.0f}h" if tiempo_rec.get('valor') else "—",
                 "Benchmark": "24-72 horas", "Fuente": "Importadores"},
                {"KPI": "Cobertura ajustes inv.", "Tu valor":
                    f"{cob_pct*100:.1f}%" if cob_pct else "—",
                 "Benchmark": "≥ 80%", "Fuente": "Best practice WMS"},
                {"KPI": "Merma operativa", "Tu valor":
                    f"{v*100:.2f}%" if v else "—",
                 "Benchmark": "≤ 0.5%", "Fuente": "Retail multicategoría"},
            ]
            st.dataframe(pd.DataFrame(bench), use_container_width=True, hide_index=True)

            # Errores capturados en el snapshot
            errs_snap = snap.get("errores", [])
            if errs_snap:
                with st.expander(f"🐛 Errores en snapshot ({len(errs_snap)})", expanded=False):
                    for e in errs_snap:
                        st.code(e)

    # ============================================================
    # TAB 2 — OTIF
    # ============================================================
    with tabs[2]:
        st.markdown("### 📦 OTIF (On-Time In-Full)")
        st.caption("Pickings entregados a tiempo Y completos. On-Time = date_done ≤ scheduled_date · In-Full = qty_done ≥ product_uom_qty")

        # ── Acceso al reporte OTIF de Drive (Apps Script) ─────────────
        OTIF_DRIVE_URL = "https://script.google.com/a/macros/unionx.cl/s/AKfycbz7eDhT9yZLXCVVPu5aSOpee-ANf2gtGSyNXtQYkStbzzr4S-s-lMyV4WL3LDwezMJs/exec"
        with st.container(border=True):
            cda, cdb = st.columns([3, 1])
            with cda:
                st.markdown("**📊 Reporte OTIF detallado (Google Drive)**")
                st.caption(
                    "Vista alternativa con análisis manual desde planilla. "
                    "Requiere login con cuenta @unionx.cl. "
                    "*Roadmap H2: integración nativa leyendo el Sheet fuente con gspread.*"
                )
            with cdb:
                st.link_button("🔗 Abrir reporte Drive", OTIF_DRIVE_URL,
                               use_container_width=True, type="primary")

        st.divider()
        st.markdown("#### OTIF calculado desde Odoo (live)")

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
    with tabs[3]:
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

        # ============================================================
        # PRODUCTIVIDAD DETALLADA (día / semana / mes) + FORECAST
        # ============================================================
        st.markdown("#### ⚡ Productividad operativa por período")
        mes_actual = datetime.now().strftime("%Y-%m")
        equipo_t = _safe_wms(get_equipo_mes, mes_actual, default={}) or {}

        if not equipo_t or not equipo_t.get("horas_total"):
            st.info(f"📋 Cargá horas equipo de {mes_actual} en Tab Datos manuales → Equipo bodega.")
        else:
            lineas_t = _safe_wms(kpi_lineas_pickeadas_mes, mes_actual, default={"lineas": 0})
            horas = equipo_t.get("horas_total", 0)
            personas = equipo_t.get("personas", 0)
            lineas = lineas_t.get("lineas", 0)
            prod_actual = lineas / horas if horas else 0

            # Cards mes actual
            ck1, ck2, ck3, ck4 = st.columns(4)
            ck1.metric("Productividad mes actual", f"{prod_actual:.0f} líneas/h",
                       help="Benchmark: 60-120 líneas/h B2C")
            ck2.metric(f"Equipo {mes_actual}", f"{personas} personas")
            ck3.metric(f"Líneas {mes_actual}", f"{lineas:,}")
            ck4.metric(f"Horas {mes_actual}", f"{horas:,.0f}h")

            st.divider()

            # Sub-tabs por período
            prod_subtabs = st.tabs(["📅 Por día (últimos 30d)",
                                     "📆 Por semana (últimas 12)",
                                     "🗓️ Por mes (últimos 6)",
                                     "🔮 Forecast 3 meses"])

            with prod_subtabs[0]:
                st.markdown("##### Productividad diaria")
                if st.button("📥 Cargar datos diarios", type="primary",
                             key="prod_d_btn"):
                    st.session_state['prod_d_loaded'] = True
                if st.session_state.get('prod_d_loaded'):
                    with st.spinner("Consultando 30 días Odoo…"):
                        prod_d = _safe_wms(productividad_periodo, periodo="dia",
                                           n_periodos=30, default={"items": []})
                    if prod_d.get("items"):
                        df_d = pd.DataFrame(prod_d["items"])
                        # Productividad diaria asumiendo horas/día estándar
                        horas_dia_promedio = horas / 21  # 21 días hábiles aprox
                        df_d["lineas_h"] = (df_d["n_lineas_pickeadas"] / horas_dia_promedio).round(1)

                        # Charts
                        cc1, cc2 = st.columns(2)
                        with cc1:
                            st.markdown("**Pedidos / día**")
                            st.bar_chart(df_d.set_index("periodo")["n_pedidos"], height=240)
                        with cc2:
                            st.markdown("**Líneas pickeadas / día**")
                            st.bar_chart(df_d.set_index("periodo")["n_lineas_pickeadas"], height=240)
                        st.markdown("**Unidades despachadas / día**")
                        st.line_chart(df_d.set_index("periodo")["n_unidades_despachadas"], height=240)

                        # Tabla
                        df_show = df_d[["periodo", "n_pedidos", "n_lineas_pickeadas",
                                        "n_unidades_despachadas", "uds_por_pedido", "lineas_h"]].rename(
                            columns={"periodo": "Día", "n_pedidos": "Pedidos",
                                     "n_lineas_pickeadas": "Líneas",
                                     "n_unidades_despachadas": "Unidades",
                                     "uds_por_pedido": "Uds/pedido",
                                     "lineas_h": "Líneas/h*"})
                        df_show["Uds/pedido"] = df_show["Uds/pedido"].round(1)
                        st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)
                        st.caption(f"*Productividad asumiendo {horas_dia_promedio:.0f}h/día equipo")
                else:
                    st.info("👆 Click 'Cargar datos diarios'.")

            with prod_subtabs[1]:
                st.markdown("##### Productividad semanal")
                if st.button("📥 Cargar datos semanales", type="primary",
                             key="prod_s_btn"):
                    st.session_state['prod_s_loaded'] = True
                if st.session_state.get('prod_s_loaded'):
                    with st.spinner("Consultando 12 semanas Odoo…"):
                        prod_s = _safe_wms(productividad_periodo, periodo="semana",
                                           n_periodos=12, default={"items": []})
                    if prod_s.get("items"):
                        df_s = pd.DataFrame(prod_s["items"])
                        horas_sem = horas / 4.33
                        df_s["lineas_h"] = (df_s["n_lineas_pickeadas"] / horas_sem).round(1)

                        cs1, cs2 = st.columns(2)
                        cs1.markdown("**Pedidos / semana**")
                        cs1.bar_chart(df_s.set_index("periodo")["n_pedidos"], height=240)
                        cs2.markdown("**Líneas / semana**")
                        cs2.bar_chart(df_s.set_index("periodo")["n_lineas_pickeadas"], height=240)
                        st.markdown("**Unidades despachadas / semana**")
                        st.line_chart(df_s.set_index("periodo")["n_unidades_despachadas"], height=240)

                        df_show = df_s[["periodo", "n_pedidos", "n_lineas_pickeadas",
                                        "n_unidades_despachadas", "lineas_h"]].rename(
                            columns={"periodo": "Semana", "n_pedidos": "Pedidos",
                                     "n_lineas_pickeadas": "Líneas",
                                     "n_unidades_despachadas": "Unidades",
                                     "lineas_h": "Líneas/h*"})
                        st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)
                        st.caption(f"*Productividad asumiendo {horas_sem:.0f}h/semana equipo")
                else:
                    st.info("👆 Click 'Cargar datos semanales'.")

            with prod_subtabs[2]:
                st.markdown("##### Productividad mensual")
                if st.button("📥 Cargar datos mensuales", type="primary",
                             key="prod_m_btn"):
                    st.session_state['prod_m_loaded'] = True
                if st.session_state.get('prod_m_loaded'):
                    with st.spinner("Consultando 6 meses Odoo…"):
                        prod_m = _safe_wms(productividad_periodo, periodo="mes",
                                           n_periodos=6, default={"items": []})
                    if prod_m.get("items"):
                        df_m = pd.DataFrame(prod_m["items"])
                        # Asumir mismas horas todos los meses (proxy)
                        df_m["lineas_h"] = (df_m["n_lineas_pickeadas"] / horas).round(1)

                        cm1, cm2 = st.columns(2)
                        cm1.markdown("**Pedidos / mes**")
                        cm1.bar_chart(df_m.set_index("periodo")["n_pedidos"], height=240)
                        cm2.markdown("**Líneas / mes**")
                        cm2.bar_chart(df_m.set_index("periodo")["n_lineas_pickeadas"], height=240)
                        st.markdown("**Productividad líneas/h por mes**")
                        st.line_chart(df_m.set_index("periodo")["lineas_h"], height=240)

                        df_show = df_m[["periodo", "n_pedidos", "n_lineas_pickeadas",
                                        "n_unidades_despachadas", "uds_por_pedido", "lineas_h"]].rename(
                            columns={"periodo": "Mes", "n_pedidos": "Pedidos",
                                     "n_lineas_pickeadas": "Líneas",
                                     "n_unidades_despachadas": "Unidades",
                                     "uds_por_pedido": "Uds/pedido",
                                     "lineas_h": "Líneas/h"})
                        df_show["Uds/pedido"] = df_show["Uds/pedido"].round(1)
                        st.dataframe(df_show, use_container_width=True, hide_index=True)
                else:
                    st.info("👆 Click 'Cargar datos mensuales'.")

            with prod_subtabs[3]:
                st.markdown("##### 🔮 Forecast volumen 3 meses adelante")
                st.caption(
                    "**Fuente: Forecast Prophet del dashboard ventas** (incluye trend, "
                    "estacionalidad semanal/anual, holidays Chile, eventos comerciales). "
                    "Convertido a líneas/uds/pedidos usando ratio histórico líneas/$ "
                    "de últimos 3 meses."
                )
                if st.button("📥 Calcular forecast operacional", type="primary", key="fc_btn"):
                    st.session_state['fc_loaded'] = True
                if st.session_state.get('fc_loaded'):
                    with st.spinner("Cargando forecast ventas + calculando ratios…"):
                        fc = _safe_wms(forecast_volumen_picking, meses_adelante=3,
                                       default={"forecast": [], "error": None})
                    if fc.get("error"):
                        st.warning(fc["error"])
                    elif fc.get("forecast"):
                        st.success(f"📊 Fuente: {fc.get('fuente', 'Prophet')}")

                        # Ratios aplicados (transparencia)
                        ratios = fc.get("ratios_aplicados", {})
                        with st.expander("ℹ️ Ratios históricos aplicados (últimos N meses)", expanded=False):
                            r1, r2, r3 = st.columns(3)
                            r1.metric("Líneas / $1MM",
                                      f"{ratios.get('lineas_por_clp', 0):.1f}",
                                      help="Por cada $1MM CLP vendido se pickean N líneas")
                            r2.metric("Unidades / $1MM",
                                      f"{ratios.get('uds_por_clp', 0):.1f}")
                            r3.metric("Pedidos / $1MM",
                                      f"{ratios.get('pedidos_por_clp', 0):.1f}")
                            st.caption(f"Promedio últimos {ratios.get('n_meses_promedio', 0)} meses · "
                                       f"Productividad actual: {fc.get('productividad_actual_lineas_h', 0):.0f} L/h")

                        st.markdown("##### Proyección próximos 3 meses")
                        df_fc = pd.DataFrame(fc["forecast"])
                        # Formato CLP
                        df_fc["venta_str"] = df_fc["venta_proj_clp"].apply(lambda v: f"${v/1e6:,.0f}MM")
                        df_show_fc = df_fc[["mes", "tipo_proyeccion", "venta_str", "vs_ly_pct",
                                            "pedidos_proj", "lineas_proj", "unidades_proj",
                                            "horas_necesarias_estim", "horas_disponibles_estandar",
                                            "cobertura_pct", "alerta"]].rename(columns={
                            "mes": "Mes",
                            "tipo_proyeccion": "Tipo",
                            "venta_str": "Venta proj.",
                            "vs_ly_pct": "% vs LY",
                            "pedidos_proj": "Pedidos",
                            "lineas_proj": "Líneas",
                            "unidades_proj": "Unidades",
                            "horas_necesarias_estim": "Hrs necesarias",
                            "horas_disponibles_estandar": "Hrs disponibles",
                            "cobertura_pct": "Cobertura %",
                            "alerta": "Estado",
                        })
                        df_show_fc["Cobertura %"] = df_show_fc["Cobertura %"].apply(
                            lambda v: f"{v:.0f}%" if v is not None else "—")
                        df_show_fc["% vs LY"] = df_show_fc["% vs LY"].apply(
                            lambda v: f"{v:+.1f}%" if v else "—")
                        st.dataframe(df_show_fc, use_container_width=True, hide_index=True)

                        # Banda de confianza Prophet (low/high)
                        with st.expander("📊 Banda de confianza forecast Prophet (low/high)"):
                            df_band = df_fc[["mes", "venta_proj_clp_low", "venta_proj_clp",
                                             "venta_proj_clp_high"]].copy()
                            for c in ["venta_proj_clp_low", "venta_proj_clp", "venta_proj_clp_high"]:
                                df_band[c] = df_band[c].apply(lambda v: f"${v/1e6:,.0f}MM")
                            df_band.columns = ["Mes", "Banda baja (P10)", "Punto medio", "Banda alta (P90)"]
                            st.dataframe(df_band, use_container_width=True, hide_index=True)

                        # Histórico+forecast en gráfico
                        st.markdown("##### Histórico + Forecast (líneas pickeadas)")
                        hist_items = fc.get("historico", [])
                        if hist_items:
                            df_combo = pd.concat([
                                pd.DataFrame([{"mes": h["periodo"], "lineas": h["n_lineas_pickeadas"],
                                               "tipo": "Histórico"} for h in hist_items]),
                                pd.DataFrame([{"mes": f["mes"], "lineas": f["lineas_proj"],
                                               "tipo": "Forecast"} for f in fc["forecast"]]),
                            ])
                            chart_combo = df_combo.pivot_table(index="mes", columns="tipo",
                                                                 values="lineas").fillna(0)
                            st.line_chart(chart_combo, height=300)

                        # Recomendación
                        criticos = [f for f in fc["forecast"]
                                    if f.get("cobertura_pct") and f["cobertura_pct"] < 100]
                        if criticos:
                            st.warning(
                                f"⚠️ **{len(criticos)} de 3 meses proyectados tienen cobertura <100%.** "
                                "Considerar contratación adicional o redistribución de horas extra. "
                                f"Equipo actual: {fc.get('n_personas_actual', 0)} personas."
                            )
                        else:
                            st.success("✅ Equipo actual cubre la demanda proyectada en los próximos 3 meses.")
                else:
                    st.info("👆 Click 'Calcular forecast operacional'. Lee proyección Prophet del dashboard ventas.")

    # ============================================================
    # TAB 4 — RECEPCIONES
    # ============================================================
    with tabs[4]:
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
    # TAB 5 — AUDITORÍA INVENTARIO (cycle counts + plan + merma)
    # ============================================================
    with tabs[5]:
        st.markdown("### 🔍 Auditoría de inventario")
        st.caption(
            "Cycle counts (ajustes Odoo) · Plan auditoría semanal por prioridad de rotación · "
            "Merma (stock.scrap) · Todo automático desde Odoo."
        )

        au_subtabs = st.tabs([
            "📋 Cycle counts (ajustes)",
            "📅 Plan auditoría semanal",
            "📉 Merma operativa",
        ])

        # ── 5.1 Cycle counts (ajustes inventario) ─────────────────────
        with au_subtabs[0]:
            st.markdown("#### Ajustes de inventario hechos en Odoo")
            st.caption(
                "Lee `stock.move` con location virtual `Inventory adjustment`. "
                "Cada ajuste = cycle count CON discrepancia (los exactos no generan move)."
            )

            if st.button("📥 Cargar inventarios desde Odoo", type="primary",
                         key="inv_load_btn_au"):
                st.session_state['inv_loaded_au'] = True

            if st.session_state.get('inv_loaded_au'):
                with st.spinner("Consultando Odoo (stock.move ajustes)…"):
                    inv = _safe_wms(kpi_ajustes_inventario,
                                    desde_fecha="2026-04-01",
                                    default={"n_ajustes": 0, "error": None})

                if inv.get("error") and inv.get("n_ajustes", 0) == 0:
                    st.warning(inv["error"])
                elif inv.get("n_ajustes", 0) == 0:
                    st.info("Sin ajustes de inventario registrados desde 2026-04-01")
                else:
                    ck1, ck2, ck3, ck4 = st.columns(4)
                    ck1.metric("Total ajustes", f"{inv.get('n_ajustes', 0):,}")
                    ck2.metric("SKUs únicos ajustados", f"{inv.get('n_skus_unicos', 0):,}")
                    cob = inv.get("cobertura_pct")
                    if cob is not None:
                        ic = "🟢" if cob >= 0.80 else ("🟡" if cob >= 0.50 else "🔴")
                        ck3.metric(f"{ic} Cobertura", f"{cob*100:.1f}%",
                                   help=f"{inv.get('n_skus_unicos', 0)} / "
                                        f"{inv.get('total_skus_activos', 0)} SKUs activos")
                    else:
                        ck3.metric("Cobertura", "—")
                    valor_neto = inv.get("valor_neto", 0)
                    ck4.metric("$ Neto ajustes", f"${valor_neto:,.0f}",
                               delta="surplus" if valor_neto > 0 else "pérdida")

                    st.markdown("##### Detalle financiero")
                    cs1, cs2 = st.columns(2)
                    cs1.metric("✅ $ Surplus (encontrado)",
                               f"${inv.get('valor_surplus', 0):,.0f}")
                    cs2.metric("❌ $ Pérdidas (faltante)",
                               f"${inv.get('valor_perdidas', 0):,.0f}")

                    st.markdown("##### Top SKUs con más ajustes")
                    if inv.get("top_skus_ajustados"):
                        df_top = pd.DataFrame(inv["top_skus_ajustados"])
                        df_top["valor_neto"] = df_top["valor_neto"].apply(lambda v: f"${v:,.0f}")
                        df_top.columns = ["SKU", "# Ajustes", "Qty surplus",
                                          "Qty pérdida", "$ neto"]
                        st.dataframe(df_top, use_container_width=True, hide_index=True,
                                     height=300)

                    with st.expander(f"📋 Ver últimos {len(inv.get('detalle', []))} ajustes"):
                        if inv.get("detalle"):
                            df_det = pd.DataFrame(inv["detalle"])
                            df_det["valor"] = df_det["valor"].apply(lambda v: f"${v:,.0f}")
                            st.dataframe(df_det, use_container_width=True,
                                         hide_index=True, height=400)

                    st.caption(f"Datos desde {inv.get('desde')} · Cache 10 min")
            else:
                st.info("👆 Click 'Cargar inventarios desde Odoo'. Query 15-30s.")

        # ── 5.2 Plan auditoría semanal (priorización) ────────────────
        with au_subtabs[1]:
            st.markdown("#### 📅 Plan auditoría semanal — priorización por rotación")
            st.caption(
                "Top SKUs por rotación que NO tengan cycle count reciente. "
                "El operario debería empezar por estos para maximizar impacto en exactitud."
            )

            ca, cb, cc = st.columns(3)
            with ca:
                top_n = st.slider("# SKUs a sugerir", 20, 200, 50, key="plan_topn")
            with cb:
                dias_sin = st.slider("Sin auditar hace > N días", 7, 90, 30, key="plan_dias_sin")
            with cc:
                dias_rot = st.slider("Ventana rotación (días)", 30, 180, 90, key="plan_dias_rot")

            if st.button("📥 Generar plan", type="primary", key="plan_btn"):
                st.session_state['plan_loaded'] = True
                st.session_state['plan_params'] = (top_n, dias_sin, dias_rot)

            if st.session_state.get('plan_loaded'):
                p_top, p_sin, p_rot = st.session_state.get('plan_params', (top_n, dias_sin, dias_rot))
                with st.spinner("Calculando plan (queries Odoo)…"):
                    plan = _safe_wms(plan_auditoria_semanal,
                                     top_n_priorizar=p_top,
                                     dias_sin_ajuste=p_sin,
                                     dias_rotacion=p_rot,
                                     default={"plan": [], "error": None})

                if plan.get("error"):
                    st.warning(plan["error"])
                elif not plan.get("plan"):
                    st.success("✅ Todos los top movers tienen cycle counts recientes")
                else:
                    cap = plan.get("capacidad", {})
                    pk1, pk2, pk3, pk4 = st.columns(4)
                    pk1.metric("SKUs sugeridos", f"{len(plan['plan']):,}")
                    pk2.metric("Equipo", f"{cap.get('n_personas', 0)} personas")
                    pk3.metric("Capacidad / mes",
                               f"{cap.get('skus_audit_mes', 0):,} SKUs",
                               help="Asumiendo 5% de horas dedicado + 3 SKUs/h/persona")
                    pk4.metric("Capacidad / semana",
                               f"{cap.get('skus_audit_semana', 0):,} SKUs")

                    st.markdown("##### 🎯 Plan priorizado (ordenado por score)")
                    df_plan = pd.DataFrame(plan["plan"])
                    df_plan["valor_stock_actual"] = df_plan["valor_stock_actual"].apply(
                        lambda v: f"${v:,.0f}")
                    df_show = df_plan[[
                        "sku", "qty_movida_period", "n_movs_period",
                        "qty_stock_actual", "valor_stock_actual", "prioridad_score",
                    ]].rename(columns={
                        "sku": "SKU",
                        "qty_movida_period": f"Qty movida ({p_rot}d)",
                        "n_movs_period": f"# Movs ({p_rot}d)",
                        "qty_stock_actual": "Qty en stock",
                        "valor_stock_actual": "$ en stock",
                        "prioridad_score": "Score",
                    })
                    st.dataframe(df_show, use_container_width=True, hide_index=True, height=420)

                    # Descarga
                    import io
                    out_p = io.BytesIO()
                    with pd.ExcelWriter(out_p, engine='openpyxl') as w:
                        pd.DataFrame(plan["plan"]).to_excel(w, index=False, sheet_name='Plan auditoria')
                    out_p.seek(0)
                    st.download_button(
                        label=f"📥 Descargar plan (Excel · {len(plan['plan']):,})",
                        data=out_p.getvalue(),
                        file_name=f"Plan_auditoria_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        key="dl_plan_au",
                        use_container_width=True,
                    )

                    st.caption(f"💡 Sugerencia: el operario audita ~"
                               f"{cap.get('skus_audit_semana', 50)//5} SKUs/día (L-V) "
                               f"para cubrir el plan en una semana.")
            else:
                st.info("👆 Configurá parámetros y click 'Generar plan'.")

        # ── 5.3 Merma operativa ──────────────────────────────────────
        with au_subtabs[2]:
            st.markdown("#### 📉 Merma operativa (Odoo · stock.scrap)")
            st.caption(
                "Lee `stock.scrap` state=done con valor del move asociado. "
                "Compara contra valor inventario actual para % merma."
            )

            col_v, _ = st.columns([1, 3])
            with col_v:
                dias_merma = st.selectbox("Ventana (días)",
                                          [30, 60, 90, 180, 365],
                                          index=2, key="merma_dias_au")

            if st.button("📥 Cargar merma desde Odoo", type="primary",
                         key="merma_load_btn_au"):
                st.session_state['merma_loaded_au'] = True
                st.session_state['merma_dias_val_au'] = dias_merma

            if st.session_state.get('merma_loaded_au'):
                with st.spinner("Consultando stock.scrap…"):
                    m_dias = st.session_state.get('merma_dias_val_au', dias_merma)
                    merma_o = _safe_wms(kpi_merma_odoo, dias=m_dias,
                                        default={"valor": None, "error": None})

                if merma_o.get("error") and merma_o.get("n_scraps", 0) == 0:
                    st.warning(merma_o["error"])
                elif merma_o.get("n_scraps", 0) == 0:
                    st.success("✅ Sin scraps registrados en la ventana seleccionada")
                else:
                    mk1, mk2, mk3, mk4 = st.columns(4)
                    v_pct = merma_o.get("valor")
                    ic = "🟢" if v_pct and v_pct <= 0.005 else \
                         ("🟡" if v_pct and v_pct <= 0.01 else "🔴")
                    mk1.metric(f"{ic} % Merma",
                               f"{v_pct*100:.2f}%" if v_pct is not None else "—",
                               help="Benchmark: ≤ 0.5%")
                    mk2.metric("$ Mermado total",
                               f"${merma_o.get('valor_mermado', 0):,.0f}")
                    mk3.metric("Unidades mermadas",
                               f"{merma_o.get('qty_mermada', 0):,.0f}")
                    mk4.metric("# Scraps", f"{merma_o.get('n_scraps', 0):,}")

                    st.caption(f"Inventario referencia: ${merma_o.get('valor_inventario_referencia', 0):,.0f}")

                    st.markdown("##### Top SKUs mermados (por valor)")
                    if merma_o.get("top_skus"):
                        df_top_m = pd.DataFrame(merma_o["top_skus"])
                        df_top_m["valor_mermado"] = df_top_m["valor_mermado"].apply(
                            lambda v: f"${v:,.0f}")
                        df_top_m.columns = ["SKU", "Qty mermada", "$ mermado", "# Scraps"]
                        st.dataframe(df_top_m, use_container_width=True, hide_index=True,
                                     height=300)

                    with st.expander(f"📋 Ver últimos {len(merma_o.get('detalle', []))} scraps"):
                        if merma_o.get("detalle"):
                            df_det_m = pd.DataFrame(merma_o["detalle"])
                            df_det_m["valor"] = df_det_m["valor"].apply(
                                lambda v: f"${v:,.0f}")
                            st.dataframe(df_det_m, use_container_width=True,
                                         hide_index=True, height=400)
            else:
                st.info("👆 Click 'Cargar merma desde Odoo'. Query 10-20s.")

    # ============================================================
    # TAB 6 — TENDENCIA MENSUAL (LAZY)
    # ============================================================
    with tabs[6]:
        st.markdown("### 📈 Tendencia mes a mes")
        st.caption("Evolución de OTIF B2C/B2B + Pick Accuracy en los últimos meses")

        col_m, col_btn = st.columns([1, 1])
        with col_m:
            n_meses = st.selectbox("Meses históricos", [3, 6, 9, 12], index=1, key="tend_meses")
        with col_btn:
            st.caption(" ")
            if st.button("📥 Calcular tendencia (30-60s)", type="primary",
                         key="tend_load", use_container_width=True):
                st.session_state['tend_loaded'] = True
                st.session_state['tend_meses_val'] = n_meses

        if not st.session_state.get('tend_loaded'):
            st.info("👆 Click para calcular la tendencia. Query pesada (1 cálculo por mes).")
            tend = []
        else:
            with st.spinner(f"Calculando tendencia {n_meses} meses…"):
                tend = _safe_wms(tendencia_mensual,
                                  meses=st.session_state.get('tend_meses_val', n_meses),
                                  default=[])

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
    # TAB 6 — ANÁLISIS PEDIDOS (Odoo) — LAZY
    # ============================================================
    with tabs[7]:
        st.markdown("### 🛒 Análisis de pedidos (Odoo)")
        st.caption("Pedidos · unidades · venta agregada cruzando SKU · canal · categoría · marca")

        col_v, col_btn = st.columns([1, 1])
        with col_v:
            ventana = st.selectbox("Ventana análisis (días)", [30, 60, 90, 180, 365],
                                   index=2, key="an_ventana")
        with col_btn:
            st.caption(" ")
            if st.button("📥 Cargar análisis (puede tardar)", type="primary",
                         key="an_load", use_container_width=True):
                st.session_state['an_loaded'] = True
                st.session_state['an_ventana_val'] = ventana

        if not st.session_state.get('an_loaded'):
            st.info("👆 Click 'Cargar análisis' para consultar Odoo. "
                    "Queries pesadas (sale.order + sale.order.line) — 30-90s la primera vez.")

        # Solo ejecutar si el usuario lo solicitó explícitamente
        if st.session_state.get('an_loaded'):
            from views._ops_analytics_helper import (
                ventas_por_mes, top_skus, ventas_por_canal,
                ventas_por_categoria, ventas_por_marca, detalle_pedidos,
            )

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
