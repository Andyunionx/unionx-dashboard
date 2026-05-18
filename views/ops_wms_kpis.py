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
    kpi_cobertura_cycle_counts,
    kpi_merma_odoo, kpi_ajustes_inventario,
    plan_auditoria_semanal, productividad_periodo, forecast_volumen_picking,
)
from views._ops_data_helper import (
    get_equipo_mes, set_equipo_mes,
    get_capacidad_bodega, set_capacidad_bodega,
    add_cycle_count, get_cycle_counts, kpi_exactitud_inventario,
    set_merma_mes, get_merma_mes, kpi_merma_operativa,
    calcular_horas_estandar_mes, get_storage_status,
    get_config_equipo, set_config_equipo, get_horas_mes_efectivas,
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
        "🔍 Auditoría inventario",   # 5 (cycle counts + merma + plan semanal)
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
                st.markdown("#### 👥 Equipo bodega")
                st.caption(
                    "**Configuración base constante.** Las horas mensuales se calculan "
                    "automáticamente con el calendario + horario UnionX (L-J 9h + V 6h)."
                )

                # ── Configuración base (singleton) ──────────────────────
                cfg = get_config_equipo()
                with st.container(border=True):
                    st.markdown("##### ⚙️ Configuración base")
                    cb1, cb2, cb3 = st.columns([1, 1, 1])
                    n_pers = cb1.number_input("Personas activas",
                                               min_value=0, max_value=200, step=1,
                                               value=int(cfg.get("n_personas") or 5),
                                               key="cfg_personas",
                                               help="Si cambia (contratación/baja), actualizá acá")
                    hrs_sem = cb2.number_input("Hrs/sem por persona",
                                                min_value=20.0, max_value=60.0, step=1.0,
                                                value=float(cfg.get("horas_semana_persona") or 42),
                                                key="cfg_hrs_sem",
                                                help="Default: 42 (L-J 9h + V 6h)")
                    cb3.markdown("&nbsp;", unsafe_allow_html=True)
                    if cb3.button("💾 Guardar config", key="cfg_save",
                                  type="primary", use_container_width=True):
                        if set_config_equipo(int(n_pers), float(hrs_sem)):
                            st.success("✅ Configuración guardada")
                            st.cache_data.clear()
                            st.rerun()

                # ── Vista automática mes actual ─────────────────────────
                mes_actual = datetime.now().strftime("%Y-%m")
                horas_efec = get_horas_mes_efectivas(mes_actual)

                st.markdown(f"##### 📅 Mes actual: {mes_actual}")
                col_h1, col_h2, col_h3, col_h4 = st.columns(4)
                col_h1.metric("Personas", f"{horas_efec.get('n_personas', 0)}")
                col_h2.metric("Horas/persona mes",
                              f"{horas_efec.get('horas_persona', 0):,.0f}h")
                col_h3.metric("Horas equipo total",
                              f"{horas_efec.get('horas_total', 0):,.0f}h")
                fuente_label = "🟢 Auto (calendario)" if horas_efec.get("fuente") == "auto" else "🟡 Override manual"
                col_h4.metric("Fuente", fuente_label)
                st.caption(f"💡 {horas_efec.get('detalle', '')}")

                # ── Tabla mensual del año ───────────────────────────────
                with st.expander("📊 Ver horas calculadas para todos los meses del año actual"):
                    import pandas as pd
                    anio = datetime.now().year
                    rows = []
                    for m in range(1, 13):
                        m_str = f"{anio}-{m:02d}"
                        h = get_horas_mes_efectivas(m_str)
                        rows.append({
                            "Mes": m_str,
                            "Personas": h.get("n_personas", 0),
                            "L-J": h.get("n_lj", 0),
                            "V": h.get("n_v", 0),
                            "Hrs/persona": h.get("horas_persona", 0),
                            "Hrs equipo": h.get("horas_total", 0),
                            "Fuente": h.get("fuente", ""),
                        })
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

                # ── Override manual opcional (vacaciones, ausencias, etc.) ──
                with st.expander("✏️ Override manual de un mes (vacaciones, ausencias)"):
                    st.caption(
                        "Solo si necesitás ajustar un mes específico (ej: alguien estuvo de "
                        "vacaciones 1 semana). Lo cargado acá pisa el cálculo automático."
                    )
                    om1, om2, om3 = st.columns([1, 1, 1])
                    mes_ov = om1.text_input("Mes (YYYY-MM)",
                                             value=mes_actual, key="ov_mes")
                    actual_ov = get_equipo_mes(mes_ov) or {}
                    ov_pers = om2.number_input("Personas (este mes)",
                                                min_value=0, max_value=200, step=1,
                                                value=int(actual_ov.get("personas") or n_pers),
                                                key="ov_pers")
                    ov_horas = om3.number_input("Horas totales (este mes)",
                                                 min_value=0.0, step=10.0,
                                                 value=float(actual_ov.get("horas_total") or 0),
                                                 key="ov_horas")
                    if st.button("💾 Guardar override", key="ov_save"):
                        if set_equipo_mes(mes_ov, int(ov_pers), float(ov_horas)):
                            st.success(f"✅ Override guardado para {mes_ov}")
                            st.cache_data.clear()
                            st.rerun()

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
        try:
            st.markdown("### KPIs principales — comparado con benchmarks de mercado")

            # Estrategia: snapshot precalculado por GH Action 2x/día (00:00 y 12:00 Chile).
            # Si snapshot fresco → instantáneo. Si no → consulta Odoo en vivo con cache 12h.
            from views._ops_kpis_snapshot import snapshot_status
            ss_st = snapshot_status()

            # Banner: siempre mostrar última info disponible (sin alarma si es viejo)
            if ss_st["existe"]:
                edad = ss_st.get("edad_horas", 0)
                if edad <= 26:
                    st.success(f"📸 Datos al {ss_st['generado_en'][:16]} · {edad:.0f}h atrás (próxima actualización auto: 00:00 Chile)")
                else:
                    st.info(f"📸 Última actualización: {ss_st['generado_en'][:16]} · {edad:.0f}h atrás (snapshot del día anterior — datos en vivo se regeneran 00:00 Chile)")
            else:
                st.info("📸 Generando primer snapshot…")

            # Botón sutil para forzar bypass de cache (solo si necesario)
            with st.expander("🔄 Forzar refresh ahora (limpiar cache 12h)", expanded=False):
                if st.button("🔄 Limpiar cache + recargar", key="resumen_force_refresh"):
                    st.cache_data.clear()
                    st.rerun()

            # SIEMPRE renderizar con la última info disponible del snapshot
            if ss_st["existe"]:
                # Modo snapshot: lectura instantánea del JSON
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
                _eq_efec = get_horas_mes_efectivas(mes_actual)
                equipo = {"personas": _eq_efec.get("n_personas", 0),
                          "horas_total": _eq_efec.get("horas_total", 0),
                          "fuente": _eq_efec.get("fuente", "")}
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

            # ─────────────────────────────────────────────────────────────
            # 📊 TOTAL PEDIDOS (B2B vs B2C) — mes / semana / día
            # ─────────────────────────────────────────────────────────────
            st.markdown("---")
            st.markdown("### 📊 Total Pedidos por período (B2B vs B2C)")

            with st.expander("ℹ️ Regla de clasificación B2B/B2C", expanded=False):
                st.markdown("""
**No hay flag B2B/B2C directo en las ventas históricas.** Aplicamos esta regla
operativa (definida por Andrés):

#### 🅱️ B2B si se cumple CUALQUIERA de estas condiciones:

**1. La `bodega` es una bodega de fulfillment externo** (olas internas
   desde CA1/Carrascal a los retailers):
   - `Bodega Fulfillment Mercado Libre`
   - `Bodega Fulfillment Falabella`
   - `Bodega Fulfillment Paris`
   - `Bodega Fulfillment Ripley`
   - `Bodega Fulfillment Walmart`

**2. El `canal` es uno de los retailers / B2B directos:**
   - `UnionX B2B`
   - `Falabella tienda` (Falabella Retail)
   - `Paris tienda` (Cencosud Retail)
   - `Walmart tienda` (Walmart Retail)
   - `Ripley tienda`
   - `El Volcan`
   - `Dimarsa`

**3. El `canal` contiene `"B2B"`** (catch-all para variantes futuras).

**4. El `tipo_negocio`** es `Distribución` o `Corporativo`.

#### 🅲️ B2C = todo lo demás
(Marketplace consumer final, Páginas propias web, Fidelización, Marketing)

> **Nota:** Las ventas con canal=*Mercado Libre* desde `Bodega Fulfillment ML`
> cuentan como B2B porque son **olas de envío interno al fulfillment** de ML,
> no ventas directas a consumidor final.
                """)

            from views._ops_pedidos_helper import (
                cargar_ventas_para_pedidos, pedidos_por_periodo,
                kpis_volumen_por_periodo, detalle_canales_por_segmento,
            )
            import plotly.graph_objects as go
            from datetime import datetime as _dt_pb

            df_v = cargar_ventas_para_pedidos()
            if df_v.empty:
                st.info("Sin datos de ventas históricas. Correr `python actualizar_raw_historico.py`.")
            else:
                # ─── Selector de MÉTRICA (aplica a los 3 sub-tabs) ──────
                METRICAS = {
                    "📦 Pedidos": ("pedidos", "Pedidos únicos"),
                    "🔢 Unidades": ("unidades", "Unidades despachadas"),
                    "📋 Líneas": ("lineas", "SKU-líneas pickeadas"),
                }
                metrica_label = st.radio(
                    "Métrica a visualizar:",
                    list(METRICAS.keys()),
                    horizontal=True,
                    key="kpi_b2b_metrica",
                )
                metrica_key, metrica_subtitulo = METRICAS[metrica_label]

                sub_tabs_ped = st.tabs([
                    "🗓️ Mes (últimos 12)",
                    "📅 Semana (últimas 12)",
                    "📆 Día (últimos 30)",
                    "📊 Tabla combinada (3 métricas)",
                    "🔍 Auditoría regla",
                ])

                def _render_pedidos(df_pivot, titulo_periodo, subtitulo_metrica):
                    if df_pivot.empty:
                        st.info("Sin datos.")
                        return
                    # KPIs del último período
                    ult = df_pivot.iloc[-1]
                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric(f"Total ({titulo_periodo} actual)",
                               f"{int(ult['Total']):,}".replace(",", "."))
                    k2.metric("B2C", f"{int(ult['B2C']):,}".replace(",", "."))
                    k3.metric("B2B", f"{int(ult['B2B']):,}".replace(",", "."))
                    k4.metric("% B2B", f"{ult['% B2B']:.1f}%")

                    # Gráfico barras apiladas
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        x=df_pivot.index, y=df_pivot["B2C"],
                        name="B2C", marker_color="#3B82F6",
                        hovertemplate="<b>%{x}</b><br>B2C: %{y:,.0f}<extra></extra>",
                    ))
                    fig.add_trace(go.Bar(
                        x=df_pivot.index, y=df_pivot["B2B"],
                        name="B2B", marker_color="#F59E0B",
                        hovertemplate="<b>%{x}</b><br>B2B: %{y:,.0f}<extra></extra>",
                    ))
                    fig.update_layout(
                        barmode="stack", height=320,
                        margin=dict(t=20, b=40, l=60, r=20),
                        yaxis=dict(title=subtitulo_metrica, tickformat=",.0f"),
                        xaxis=dict(title=titulo_periodo),
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        legend=dict(orientation="h", y=1.08, x=0),
                        hovermode="x unified",
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # Tabla
                    df_display = df_pivot.copy()
                    for c in ["B2B", "B2C", "Total"]:
                        df_display[c] = df_display[c].astype(int)
                    st.dataframe(
                        df_display.style.format({
                            "B2B": "{:,.0f}",
                            "B2C": "{:,.0f}",
                            "Total": "{:,.0f}",
                            "% B2B": "{:.1f}%",
                        }),
                        use_container_width=True,
                    )

                with sub_tabs_ped[0]:
                    _render_pedidos(
                        pedidos_por_periodo(df_v, "mes", 12, metrica_key),
                        "Mes", metrica_subtitulo,
                    )
                with sub_tabs_ped[1]:
                    _render_pedidos(
                        pedidos_por_periodo(df_v, "semana", 12, metrica_key),
                        "Semana", metrica_subtitulo,
                    )
                with sub_tabs_ped[2]:
                    _render_pedidos(
                        pedidos_por_periodo(df_v, "dia", 30, metrica_key),
                        "Día", metrica_subtitulo,
                    )

                with sub_tabs_ped[3]:
                    st.markdown(
                        "**Tabla combinada:** Pedidos + Unidades + Líneas "
                        "por período, separado B2B/B2C. Útil para calcular "
                        "KPIs derivados (unid/pedido, líneas/pedido, etc.)."
                    )
                    granul = st.radio(
                        "Granularidad",
                        ["Mes (últimos 12)", "Semana (últimas 12)", "Día (últimos 30)"],
                        horizontal=True, key="combo_granul",
                    )
                    if "Mes" in granul:
                        df_combo = kpis_volumen_por_periodo(df_v, "mes", 12)
                    elif "Semana" in granul:
                        df_combo = kpis_volumen_por_periodo(df_v, "semana", 12)
                    else:
                        df_combo = kpis_volumen_por_periodo(df_v, "dia", 30)

                    if df_combo.empty:
                        st.info("Sin datos.")
                    else:
                        # KPIs derivados
                        df_kpis = df_combo.copy()
                        df_kpis["Unid/Pedido B2B"] = (
                            df_kpis["Unidades B2B"] / df_kpis["Pedidos B2B"]
                        ).replace([float("inf"), -float("inf")], 0).fillna(0).round(2)
                        df_kpis["Unid/Pedido B2C"] = (
                            df_kpis["Unidades B2C"] / df_kpis["Pedidos B2C"]
                        ).replace([float("inf"), -float("inf")], 0).fillna(0).round(2)
                        df_kpis["Líneas/Pedido B2B"] = (
                            df_kpis["Líneas B2B"] / df_kpis["Pedidos B2B"]
                        ).replace([float("inf"), -float("inf")], 0).fillna(0).round(2)
                        df_kpis["Líneas/Pedido B2C"] = (
                            df_kpis["Líneas B2C"] / df_kpis["Pedidos B2C"]
                        ).replace([float("inf"), -float("inf")], 0).fillna(0).round(2)

                        st.dataframe(
                            df_kpis.style.format({
                                "Pedidos B2B": "{:,.0f}",
                                "Pedidos B2C": "{:,.0f}",
                                "Pedidos Total": "{:,.0f}",
                                "Unidades B2B": "{:,.0f}",
                                "Unidades B2C": "{:,.0f}",
                                "Unidades Total": "{:,.0f}",
                                "Líneas B2B": "{:,.0f}",
                                "Líneas B2C": "{:,.0f}",
                                "Líneas Total": "{:,.0f}",
                                "% B2B (pedidos)": "{:.1f}%",
                                "Unid/Pedido B2B": "{:.2f}",
                                "Unid/Pedido B2C": "{:.2f}",
                                "Líneas/Pedido B2B": "{:.2f}",
                                "Líneas/Pedido B2C": "{:.2f}",
                            }),
                            use_container_width=True,
                            height=480,
                        )

                        st.caption(
                            "**Cómo se calcula:** Pedidos = `nunique(pedido)` · "
                            "Unidades = `sum(cantidad)` solo movimientos Venta · "
                            "Líneas = `nunique(pedido + sku)` (SKU-líneas pickeadas)."
                        )
                with sub_tabs_ped[4]:
                    st.markdown(
                        "**Auditoría:** detalle por (canal × bodega × segmento) "
                        "para validar la clasificación."
                    )
                    _hoy = _dt_pb.now()
                    cau1, cau2 = st.columns(2)
                    with cau1:
                        y_au = st.selectbox(
                            "Año", sorted(df_v["fecha_venta"].dt.year.unique(),
                                            reverse=True),
                            key="audit_b2b_year",
                        )
                    with cau2:
                        meses_disp_au = sorted(
                            df_v[df_v["fecha_venta"].dt.year == y_au]["fecha_venta"]
                                .dt.month.unique()
                        )
                        m_au = st.selectbox(
                            "Mes", meses_disp_au,
                            index=len(meses_disp_au) - 1,
                            key="audit_b2b_mes",
                        )
                    det = detalle_canales_por_segmento(df_v, year=int(y_au), month=int(m_au))
                    if det.empty:
                        st.info("Sin datos.")
                    else:
                        b2b_filas = det[det["segmento"] == "B2B"]
                        b2c_filas = det[det["segmento"] == "B2C"]
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown(f"##### 🅱️ B2B — {int(b2b_filas['n_pedidos'].sum()):,} pedidos".replace(",", "."))
                            st.dataframe(
                                b2b_filas[["canal", "bodega", "n_pedidos"]].rename(columns={
                                    "canal": "Canal",
                                    "bodega": "Bodega",
                                    "n_pedidos": "# Pedidos",
                                }),
                                use_container_width=True, hide_index=True,
                                height=400,
                            )
                        with c2:
                            st.markdown(f"##### 🅲️ B2C — {int(b2c_filas['n_pedidos'].sum()):,} pedidos".replace(",", "."))
                            st.dataframe(
                                b2c_filas[["canal", "bodega", "n_pedidos"]].rename(columns={
                                    "canal": "Canal",
                                    "bodega": "Bodega",
                                    "n_pedidos": "# Pedidos",
                                }),
                                use_container_width=True, hide_index=True,
                                height=400,
                            )
                        st.caption(
                            "Si ves un canal/bodega clasificado incorrectamente, "
                            "decime y ajustamos la regla en `_ops_pedidos_helper.py`."
                        )

        # ============================================================
        # TAB 2 — OTIF
        except Exception as _e_tab:
            st.error(f"❌ Error en Tab 1: {type(_e_tab).__name__}: {_e_tab}")
            import traceback as _tb
            with st.expander("🐛 Ver traceback completo"):
                st.code(_tb.format_exc())

    # ============================================================
    with tabs[2]:
        try:
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
            st.markdown("### 📊 Dashboard OTIF Union X")
            st.caption("CONTROL DE GESTION / LOGISTICA — Mismo formato del reporte Apps Script (corte 26-25)")

            # Datos PRECALCULADOS en snapshot para no bloquear el render
            from views._ops_kpis_snapshot import cargar_snapshot as _cs_otif
            snap_otif_data = _cs_otif().get("otif_drive", {})

            # Selector AÑO + MES con comparativo año a año
            cortes_data = snap_otif_data.get("cortes_disponibles", [])
            if cortes_data and snap_otif_data.get("dashboard_por_corte"):
                # Construir mapa año → meses disponibles
                anios_meses = {}
                for c in cortes_data:
                    a, m = c["anio"], c["mes"]
                    anios_meses.setdefault(a, []).append((m, c["key"], c["label"]))
                anios_disp = sorted(anios_meses.keys(), reverse=True)
                nombres_mes = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

                col_anio, col_mes, col_comp = st.columns([1, 1, 1])
                with col_anio:
                    st.markdown("**AÑO**")
                    anio_sel = st.selectbox("anio", anios_disp, index=0,
                                              key="otif_anio", label_visibility="collapsed")
                with col_mes:
                    st.markdown("**MES**")
                    meses_anio = sorted(anios_meses.get(anio_sel, []), key=lambda x: x[0], reverse=True)
                    if meses_anio:
                        mes_keys = [k for (m, k, _) in meses_anio]
                        mes_labels = {k: f"{nombres_mes[m-1]} {anio_sel}" for (m, k, _) in meses_anio}
                        corte_sel = st.selectbox("mes", mes_keys, index=0,
                                                  format_func=lambda k: mes_labels.get(k, k),
                                                  key="otif_mes_sel", label_visibility="collapsed")
                        # Construir clave del año anterior mismo mes (para comparativo)
                        mes_num = next((m for (m, k, _) in meses_anio if k == corte_sel), None)
                    else:
                        st.warning("Sin meses para este año")
                        corte_sel = None
                        mes_num = None
                with col_comp:
                    st.markdown("**COMPARAR CON**")
                    opciones_comp_dict = {"(Sin comparativo)": None}
                    todos_cortes = snap_otif_data.get("dashboard_por_corte", {})

                    if corte_sel and mes_num:
                        # 1. Mes anterior calendario
                        if mes_num == 1:
                            mes_ant_key = f"{anio_sel - 1}-12"
                            mes_ant_num, mes_ant_anio = 12, anio_sel - 1
                        else:
                            mes_ant_key = f"{anio_sel}-{mes_num - 1:02d}"
                            mes_ant_num, mes_ant_anio = mes_num - 1, anio_sel
                        if mes_ant_key in todos_cortes:
                            opciones_comp_dict[
                                f"📅 Mes anterior — {nombres_mes[mes_ant_num-1]} {mes_ant_anio}"
                            ] = mes_ant_key

                        # 2. Mismo mes año anterior
                        same_my_key = f"{anio_sel - 1}-{mes_num:02d}"
                        if same_my_key in todos_cortes:
                            opciones_comp_dict[
                                f"📆 Mismo mes año anterior — {nombres_mes[mes_num-1]} {anio_sel - 1}"
                            ] = same_my_key

                        # 3. Mes con volumen similar
                        n_ord_actual = todos_cortes.get(corte_sel, {}).get("resumen", {}).get("n_ordenes", 0)
                        if n_ord_actual > 0:
                            candidatos = []
                            for k, dash_k in todos_cortes.items():
                                if k == corte_sel or k in opciones_comp_dict.values():
                                    continue
                                n_k = dash_k.get("resumen", {}).get("n_ordenes", 0)
                                if n_k > 0:
                                    candidatos.append((abs(n_k - n_ord_actual), k, n_k))
                            candidatos.sort()
                            if candidatos:
                                _, k_sim, n_sim = candidatos[0]
                                a_sim, m_sim = map(int, k_sim.split("-"))
                                opciones_comp_dict[
                                    f"📊 Volumen similar — {nombres_mes[m_sim-1]} {a_sim} ({n_sim:,} órd)"
                                ] = k_sim

                        # 4. Resto de meses
                        for c in cortes_data:
                            k = c["key"]
                            if k == corte_sel or k in opciones_comp_dict.values():
                                continue
                            opciones_comp_dict[
                                f"   {nombres_mes[c['mes']-1]} {c['anio']}"
                            ] = k

                    comp_sel_label = st.selectbox("comp",
                                                   list(opciones_comp_dict.keys()),
                                                   index=0,
                                                   key="otif_comp",
                                                   label_visibility="collapsed")
                    comp_key = opciones_comp_dict.get(comp_sel_label)

                dash = snap_otif_data.get("dashboard_por_corte", {}).get(corte_sel, {})
                if not dash or dash.get("error"):
                    st.warning(f"⚠️ {dash.get('error', 'Sin datos para este corte')}")
                else:
                    opc = dash.get("opciones_filtros", {})
                    col_cou, col_cli, col_serv, col_btn = st.columns([1, 1, 1, 1])
                    with col_cou:
                        st.markdown("**COURIER**")
                        f_cou = st.selectbox("cou", opc.get("couriers", ["Todos"]),
                                              key="otif_f_cou", label_visibility="collapsed")
                    with col_cli:
                        st.markdown("**CLIENTE / MARKETPLACE**")
                        f_cli = st.selectbox("cli", opc.get("clientes", ["Todos"]),
                                              key="otif_f_cli", label_visibility="collapsed")
                    with col_serv:
                        st.markdown("**TIPO DE SERVICIO**")
                        f_serv = st.selectbox("serv", opc.get("servicios", ["Todos"]),
                                                key="otif_f_serv", label_visibility="collapsed")

                    # Si hay filtros activos, recalcular en runtime (solo este corte)
                    if f_cou != "Todos" or f_cli != "Todos" or f_serv != "Todos":
                        from views._ops_otif_drive import dashboard_otif_corte as _dash_fn
                        with st.spinner("Aplicando filtros…"):
                            dash = _dash_fn(corte_sel, courier=f_cou,
                                            cliente=f_cli, servicio=f_serv)

                    r = dash.get("resumen", {})
                    corte_info = dash.get("corte", {})
                    # Resolver comparativo
                    r_comp = None
                    if comp_key:
                        dash_comp = snap_otif_data.get("dashboard_por_corte", {}).get(comp_key, {})
                        r_comp = dash_comp.get("resumen", {}) if dash_comp else None
                    st.caption(f"Periodo: **{corte_info.get('label', '')}** · "
                               f"**{r.get('n_ordenes', 0):,} órdenes** · "
                               f"Snapshot: {snap_otif_data.get('generado_en', '')[:16]}")

                    # Helper: formato CLP chileno: $1.234.567 (sin abreviar)
                    def _clp(v):
                        try:
                            return f"${v:,.0f}".replace(",", ".")
                        except Exception:
                            return f"${v}"

                    # Helper: delta vs comparativo (formato breve)
                    def _delta_pct(actual, comp):
                        if comp is None or comp == 0:
                            return None
                        diff_pct = (actual - comp) / comp * 100
                        return f"{diff_pct:+.1f}% vs comp."

                    def _delta_pp(actual, comp):
                        """Delta en puntos porcentuales para %s."""
                        if comp is None:
                            return None
                        return f"{(actual - comp)*100:+.1f} pp vs comp."

                    # ── 5 KPI CARDS principales (formato CLP completo) ────
                    k1, k2, k3, k4, k5 = st.columns(5)

                    canc_clp = r.get("cancelacion_clp", 0)
                    canc_comp = (r_comp or {}).get("cancelacion_clp")
                    canc_delta = _delta_pct(canc_clp, canc_comp) if canc_comp else ""
                    k1.markdown(f"""
                        <div style="background:#1e293b;border-radius:8px;padding:12px;border:1px solid #334155;height:100%;">
                          <div style="color:#94a3b8;font-size:0.7rem;letter-spacing:0.5px;">$ CANCELACIÓN (TOTAL CLP)</div>
                          <div style="color:#ef4444;font-size:1.5rem;font-weight:700;line-height:1.3;">{_clp(canc_clp)}</div>
                          <div style="color:#94a3b8;font-size:0.75rem;">{r.get('n_canceladas', 0)} órdenes afectadas</div>
                          <div style="color:#94a3b8;font-size:0.7rem;font-style:italic;">{canc_delta}</div>
                          <div style="height:3px;background:#ef4444;border-radius:2px;margin-top:4px;"></div>
                        </div>
                    """, unsafe_allow_html=True)

                    quie_clp = r.get("quiebre_clp", 0)
                    quie_comp = (r_comp or {}).get("quiebre_clp")
                    quie_delta = _delta_pct(quie_clp, quie_comp) if quie_comp else ""
                    k2.markdown(f"""
                        <div style="background:#1e293b;border-radius:8px;padding:12px;border:1px solid #334155;height:100%;">
                          <div style="color:#94a3b8;font-size:0.7rem;letter-spacing:0.5px;">$ QUIEBRE (TOTAL CLP)</div>
                          <div style="color:#eab308;font-size:1.5rem;font-weight:700;line-height:1.3;">{_clp(quie_clp)}</div>
                          <div style="color:#94a3b8;font-size:0.75rem;">{r.get('n_quiebres', 0)} órdenes afectadas</div>
                          <div style="color:#94a3b8;font-size:0.7rem;font-style:italic;">{quie_delta}</div>
                          <div style="height:3px;background:#eab308;border-radius:2px;margin-top:4px;"></div>
                        </div>
                    """, unsafe_allow_html=True)

                    ns_e = r.get("ns_empresa_pct") or 0
                    ns_e_comp = (r_comp or {}).get("ns_empresa_pct")
                    ns_e_delta = _delta_pp(ns_e, ns_e_comp) if ns_e_comp is not None else ""
                    k3.markdown(f"""
                        <div style="background:#1e293b;border-radius:8px;padding:12px;border:1px solid #334155;height:100%;">
                          <div style="color:#94a3b8;font-size:0.7rem;letter-spacing:0.5px;">NS EMPRESA</div>
                          <div style="color:#22c55e;font-size:1.6rem;font-weight:700;line-height:1.3;">{ns_e*100:.1f}%</div>
                          <div style="color:#94a3b8;font-size:0.75rem;">Entregas a tiempo al courier</div>
                          <div style="color:#94a3b8;font-size:0.7rem;font-style:italic;">{ns_e_delta}</div>
                          <div style="height:3px;background:#22c55e;border-radius:2px;margin-top:4px;width:{min(100, ns_e*100):.0f}%;"></div>
                        </div>
                    """, unsafe_allow_html=True)

                    ns_c = r.get("ns_courier_pct") or 0
                    ns_c_comp = (r_comp or {}).get("ns_courier_pct")
                    ns_c_delta = _delta_pp(ns_c, ns_c_comp) if ns_c_comp is not None else ""
                    k4.markdown(f"""
                        <div style="background:#1e293b;border-radius:8px;padding:12px;border:1px solid #334155;height:100%;">
                          <div style="color:#94a3b8;font-size:0.7rem;letter-spacing:0.5px;">NS COURIER</div>
                          <div style="color:#22c55e;font-size:1.6rem;font-weight:700;line-height:1.3;">{ns_c*100:.1f}%</div>
                          <div style="color:#94a3b8;font-size:0.75rem;">Entregas a tiempo al cliente</div>
                          <div style="color:#94a3b8;font-size:0.7rem;font-style:italic;">{ns_c_delta}</div>
                          <div style="height:3px;background:#22c55e;border-radius:2px;margin-top:4px;width:{min(100, ns_c*100):.0f}%;"></div>
                        </div>
                    """, unsafe_allow_html=True)

                    otif_t = r.get("otif_total_pct") or 0
                    otif_t_comp = (r_comp or {}).get("otif_total_pct")
                    otif_t_delta = _delta_pp(otif_t, otif_t_comp) if otif_t_comp is not None else ""
                    k5.markdown(f"""
                        <div style="background:#1e293b;border-radius:8px;padding:12px;border:2px solid #8b5cf6;height:100%;">
                          <div style="color:#94a3b8;font-size:0.7rem;letter-spacing:0.5px;">OTIF TOTAL</div>
                          <div style="color:#8b5cf6;font-size:1.6rem;font-weight:700;line-height:1.3;">{otif_t*100:.1f}%</div>
                          <div style="color:#94a3b8;font-size:0.75rem;">{r.get('n_ordenes', 0)} órd / {r.get('n_otif_ok', 0)} OTIF</div>
                          <div style="color:#94a3b8;font-size:0.7rem;font-style:italic;">{otif_t_delta}</div>
                          <div style="height:3px;background:#8b5cf6;border-radius:2px;margin-top:4px;width:{min(100, otif_t*100):.0f}%;"></div>
                        </div>
                    """, unsafe_allow_html=True)

                    st.markdown("<br>", unsafe_allow_html=True)

                    # ── OTIF por Cliente (pivot) ─────────────────────────
                    col_left, col_right = st.columns([1, 1])

                    with col_left:
                        st.markdown("##### OTIF por Cliente")
                        st.caption("Pivot por marketplace; verde = alto cumplimiento, rojo = atención urgente")
                        por_cli = dash.get("por_cliente", [])
                        if por_cli:
                            df_cli = pd.DataFrame(por_cli)
                            df_cli["NS_EMP_PCT_STR"] = df_cli["NS_EMP_PCT"].apply(lambda v: f"{v*100:.1f}%")
                            df_cli["NS_COU_PCT_STR"] = df_cli["NS_COU_PCT"].apply(lambda v: f"{v*100:.1f}%")
                            df_cli["OTIF_PCT_STR"] = df_cli["OTIF_PCT"].apply(lambda v: f"{v*100:.1f}%")
                            df_show = df_cli[["CLIENTE", "ORDENES", "A_TPO_EMP", "NS_EMP_PCT_STR",
                                              "A_TPO_COU", "NS_COU_PCT_STR", "OTIF", "OTIF_PCT_STR"]].rename(
                                columns={"CLIENTE": "CLIENTE", "ORDENES": "ORDENES",
                                         "A_TPO_EMP": "A TPO EMP", "NS_EMP_PCT_STR": "NS EMP %",
                                         "A_TPO_COU": "A TPO COU", "NS_COU_PCT_STR": "NS COU %",
                                         "OTIF": "OTIF", "OTIF_PCT_STR": "OTIF %"})

                            # Coloreado verde/rojo
                            def _color_otif(val):
                                try:
                                    pct = float(val.rstrip("%")) / 100
                                    if pct >= 0.95:
                                        return "color:#22c55e;font-weight:600"
                                    elif pct >= 0.80:
                                        return "color:#eab308"
                                    else:
                                        return "color:#ef4444;font-weight:600"
                                except Exception:
                                    return ""

                            st.dataframe(
                                df_show.style.map(_color_otif, subset=["NS EMP %", "NS COU %", "OTIF %"]),
                                use_container_width=True, hide_index=True, height=420
                            )

                    with col_right:
                        st.markdown("##### Pareto de Quiebres")
                        st.caption("SKUs con mayor monto de quiebre y % acumulado · Regla 80/20")
                        pareto = dash.get("pareto_quiebres", [])
                        if pareto:
                            df_par = pd.DataFrame(pareto)
                            df_par["monto_MM"] = (df_par["monto"] / 1e6).round(2)
                            df_par["pct_acum_pct"] = (df_par["pct_acumulado"] * 100).round(1)

                            # Gráfico combinado (barras monto + línea acumulada)
                            import plotly.graph_objects as go
                            fig = go.Figure()
                            fig.add_trace(go.Bar(
                                x=df_par[df_par.columns[0]], y=df_par["monto_MM"],
                                name="Monto Quiebre $MM", marker_color="#eab308", yaxis="y1"
                            ))
                            fig.add_trace(go.Scatter(
                                x=df_par[df_par.columns[0]], y=df_par["pct_acum_pct"],
                                name="% Acumulado", mode="lines+markers",
                                line=dict(color="#8b5cf6", width=2),
                                marker=dict(size=6),
                                yaxis="y2"
                            ))
                            fig.update_layout(
                                height=380,
                                template="plotly_dark",
                                showlegend=True,
                                legend=dict(orientation="h", yanchor="bottom", y=1.05),
                                yaxis=dict(title="Monto $MM", side="left"),
                                yaxis2=dict(title="% Acumulado", side="right",
                                            overlaying="y", range=[0, 100]),
                                xaxis=dict(tickangle=-45),
                                margin=dict(t=40, b=80),
                            )
                            st.plotly_chart(fig, use_container_width=True)

                            df_show_p = df_par[[df_par.columns[0], "monto_MM",
                                                "n_ordenes", "pct_acum_pct"]].rename(
                                columns={df_par.columns[0]: "SKU",
                                         "monto_MM": "Monto $MM",
                                         "n_ordenes": "# Órdenes",
                                         "pct_acum_pct": "% Acum"})
                            with st.expander("📋 Tabla detallada"):
                                st.dataframe(df_show_p, use_container_width=True, hide_index=True)
                        else:
                            st.info("Sin quiebres registrados en este corte")

                    st.divider()

            if snap_otif_data.get("error"):
                st.warning(f"⚠️ {snap_otif_data['error']}")
                st.caption("Próx. actualización snapshot: día 01 y 10 de cada mes o trigger manual")
            elif not cortes_data:
                st.warning("⚠️ Sin cortes disponibles del Sheet OTIF.")

            # Sección antigua mensual eliminada — se reemplazó por dashboard
            # estilo Apps Script arriba (formato corte 26-25).
            # Tendencia mensual + Top pedidos tarde quedan en expander:
            if snap_otif_data.get("por_mes"):
                with st.expander("📈 Tendencia mensual + Top pedidos tarde (vista anterior)"):
                    df_meses = pd.DataFrame(snap_otif_data["por_mes"])
                    chart = df_meses[["MES", "otif_empresa_pct", "otif_courier_pct", "otif_total_pct"]].rename(
                        columns={"otif_empresa_pct": "Empresa",
                                 "otif_courier_pct": "Courier",
                                 "otif_total_pct": "Total E2E"})
                    st.line_chart(chart.set_index("MES"), height=240)

        # ============================================================
        # TAB 3 — PICKING & OFR/OCT (snapshot + lazy fallback)
        except Exception as _e_tab:
            st.error(f"❌ Error en Tab 2: {type(_e_tab).__name__}: {_e_tab}")
            import traceback as _tb
            with st.expander("🐛 Ver traceback completo"):
                st.code(_tb.format_exc())

    # ============================================================
    with tabs[3]:
        try:
            st.markdown("### 🎯 Pick Accuracy + OFR + OCT + Productividad")

            # Snapshot precalculado (si existe) — instantáneo
            from views._ops_kpis_snapshot import (
                cargar_snapshot, snapshot_status, get_pick_ventana,
            )
            ss_pick = snapshot_status()
            snap_pick = cargar_snapshot()

            col_p, col_p2 = st.columns([1, 3])
            with col_p:
                dias_p = st.selectbox("Ventana", [7, 14, 30, 60, 90], index=2, key="pick_dias")

            # Banner del snapshot
            if ss_pick["existe"]:
                with col_p2:
                    st.success(f"📸 {ss_pick['leyenda']} — datos instantáneos")

            # Estrategia: snapshot 30d (instantáneo) → fallback Odoo en vivo (cache 12h)
            usar_snapshot_pick = (
                ss_pick["existe"] and dias_p == 30
            )

            # Siempre mostrar snapshot (aunque sea viejo). Si la ventana
            # específica está en pick_ventanas, usarla. Si no, usar 30d default.
            kpis_snap = snap_pick.get("kpis", {}) if snap_pick else {}
            pick_ventanas_snap = snap_pick.get("pick_ventanas", {}) if snap_pick else {}

            # Pick Accuracy: usar la ventana exacta si existe en snapshot
            pick_acc_t = pick_ventanas_snap.get(f"{dias_p}d") or kpis_snap.get("pick_accuracy_30d", {})
            # OFR y OCT solo se calculan para 30d en el snapshot
            ofr_t = kpis_snap.get("ofr_30d", {})
            oct_t = kpis_snap.get("oct_30d", {})
            if dias_p != 30 and (not ofr_t or not oct_t):
                with col_p2:
                    st.caption(f"ℹ️ OFR/OCT mostrados son siempre 30d (snapshot)")

            # Pick Accuracy
            st.markdown("#### Pick Accuracy")
            st.caption(
                "⚠️ **Métrica débil sin escaneo de código de barras.** Mide consistencia "
                "interna (qty pickeada = qty pedida en Odoo), NO el error físico real. "
                "Ver 'Devoluciones por error' abajo para el dato del cliente."
            )
            if pick_acc_t.get("error"):
                st.warning(pick_acc_t["error"])
            else:
                c1, c2, c3 = st.columns(3)
                v = pick_acc_t.get('valor', 0) or 0
                c1.metric("Pick Accuracy (sistema)", f"{v*100:.2f}%",
                          delta=f"{pick_acc_t.get('errores', 0)} errores",
                          help="Consistencia qty pickeada vs pedida en Odoo")
                c2.metric("Total moves done", f"{pick_acc_t.get('total', 0):,}")
                c3.metric("Errores qty mismatch", f"{pick_acc_t.get('errores', 0):,}")

            # Pick Accuracy REAL: devoluciones por error
            st.markdown("##### 📦 Tasa de devoluciones (Pick Accuracy real)")
            st.caption("Pickings tipo return desde clientes / # despachos. Refleja errores que el cliente detectó.")
            kpis_snap_pa = snap_pick.get("kpis", {}) if snap_pick else {}
            dev_30d = kpis_snap_pa.get("devoluciones_picking_error_30d", {})
            dev_90d = kpis_snap_pa.get("devoluciones_picking_error_90d", {})
            cd1, cd2, cd3 = st.columns(3)
            v30 = dev_30d.get("valor")
            cd1.metric("Devoluciones 30d", f"{v30*100:.2f}%" if v30 is not None else "—",
                       delta=f"{dev_30d.get('n_devoluciones', 0)} dev. / {dev_30d.get('n_despachos', 0)} despachos")
            v90 = dev_90d.get("valor")
            cd2.metric("Devoluciones 90d", f"{v90*100:.2f}%" if v90 is not None else "—",
                       delta=f"{dev_90d.get('n_devoluciones', 0)} dev. / {dev_90d.get('n_despachos', 0)} despachos")
            cd3.metric("Pick Accuracy REAL 30d",
                       f"{(1-v30)*100:.2f}%" if v30 is not None else "—",
                       help="100% - tasa devoluciones. Es la métrica que el cliente ve.")

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
            _eq_efec_t = get_horas_mes_efectivas(mes_actual)
            equipo_t = {"personas": _eq_efec_t.get("n_personas", 0),
                        "horas_total": _eq_efec_t.get("horas_total", 0),
                        "fuente": _eq_efec_t.get("fuente", "")}

            if not equipo_t or not equipo_t.get("horas_total"):
                st.info(f"📋 Cargá horas equipo de {mes_actual} en Tab Datos manuales → Equipo bodega.")
            else:
                horas_mes = equipo_t.get("horas_total", 0)
                personas = equipo_t.get("personas", 0)
                # Snapshot data
                snap_prod_pre = snap_pick if 'snap_pick' in dir() else cargar_snapshot()
                meses_data_pre = (snap_prod_pre.get("productividad_meses_12m", {}) or {}).get("items", [])
                sem_data_pre = (snap_prod_pre.get("productividad_semanas_mes_actual", {}) or {}).get("items", [])
                dias_data_pre = (snap_prod_pre.get("productividad_dias_14d", {}) or {}).get("items", [])

                # ════════════════════════════════════════════════════════
                # SELECTOR DE PERÍODO (NUEVO)
                # ════════════════════════════════════════════════════════
                sp1, sp2, sp3 = st.columns([1, 2, 2])
                with sp1:
                    tipo_periodo = st.selectbox("Período",
                        ["Mes", "Semana", "Día", "Año"],
                        index=0, key="prod_tipo_periodo")

                # Construir opciones específicas según tipo
                opciones_periodo = []
                if tipo_periodo == "Mes":
                    opciones_periodo = [m.get("periodo", "") for m in meses_data_pre if m.get("periodo")]
                    opciones_periodo = list(reversed(opciones_periodo))  # mes más reciente primero
                elif tipo_periodo == "Semana":
                    opciones_periodo = [s.get("periodo", "") for s in sem_data_pre if s.get("periodo")]
                    opciones_periodo = list(reversed(opciones_periodo))
                elif tipo_periodo == "Día":
                    opciones_periodo = [d.get("periodo", "") for d in dias_data_pre if d.get("periodo")]
                    opciones_periodo = list(reversed(opciones_periodo))
                elif tipo_periodo == "Año":
                    anios = sorted({m.get("periodo", "")[:4] for m in meses_data_pre if m.get("periodo")},
                                   reverse=True)
                    opciones_periodo = [a for a in anios if a]

                with sp2:
                    if opciones_periodo:
                        periodo_sel = st.selectbox(f"Seleccionar {tipo_periodo.lower()}",
                                                    opciones_periodo, index=0,
                                                    key="prod_periodo_sel")
                    else:
                        st.warning("Sin datos en snapshot")
                        periodo_sel = None
                with sp3:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    st.caption(f"Equipo: {personas} personas · Horario base: L-J 9h + V 6h")

                # ════════════════════════════════════════════════════════
                # CALCULAR DATOS Y HORAS SEGÚN PERÍODO SELECCIONADO
                # ════════════════════════════════════════════════════════
                # Defaults para Mes actual
                n_pedidos_p = n_lineas_p = n_uds_p = 0
                horas_p = 0       # horas totales del período (equipo)
                n_dias_p = 21     # días hábiles del período
                horas_dia_p = 0   # horas calendarias del día tipo
                label_p = mes_actual

                if periodo_sel and tipo_periodo == "Mes":
                    label_p = periodo_sel
                    data_p = next((m for m in meses_data_pre if m.get("periodo") == periodo_sel), {})
                    n_pedidos_p = data_p.get("n_pedidos", 0)
                    n_lineas_p = data_p.get("n_lineas", 0)
                    n_uds_p = data_p.get("n_unidades", 0)
                    # Calcular horas reales del mes con calendario
                    try:
                        from views._ops_data_helper import calcular_horas_estandar_mes
                        h_calc = calcular_horas_estandar_mes(periodo_sel, personas)
                        horas_p = h_calc.get("horas_total", horas_mes)
                        n_dias_p = h_calc.get("n_dias_habiles", 21)
                    except Exception:
                        horas_p = horas_mes
                        n_dias_p = 21
                    horas_dia_p = horas_p / n_dias_p if n_dias_p else 0

                elif periodo_sel and tipo_periodo == "Semana":
                    label_p = periodo_sel
                    data_p = next((s for s in sem_data_pre if s.get("periodo") == periodo_sel), {})
                    n_pedidos_p = data_p.get("n_pedidos", 0)
                    n_lineas_p = data_p.get("n_lineas", 0)
                    n_uds_p = data_p.get("n_unidades", 0)
                    n_dias_p = 5
                    horas_dia_p = (4 * 9 + 6) / 5  # promedio L-V = 8.4h
                    horas_p = horas_dia_p * n_dias_p * personas  # ~210h equipo

                elif periodo_sel and tipo_periodo == "Día":
                    label_p = periodo_sel
                    data_p = next((d for d in dias_data_pre if d.get("periodo") == periodo_sel), {})
                    n_pedidos_p = data_p.get("n_pedidos", 0)
                    n_lineas_p = data_p.get("n_lineas", 0)
                    n_uds_p = data_p.get("n_unidades", 0)
                    n_dias_p = 1
                    # Detectar V (viernes)
                    es_viernes = "Fri" in periodo_sel or "Vie" in periodo_sel
                    horas_dia_p = 6 if es_viernes else 9
                    horas_p = horas_dia_p * personas

                elif periodo_sel and tipo_periodo == "Año":
                    label_p = periodo_sel
                    meses_anio = [m for m in meses_data_pre if m.get("periodo", "").startswith(periodo_sel)]
                    n_pedidos_p = sum(m.get("n_pedidos", 0) for m in meses_anio)
                    n_lineas_p = sum(m.get("n_lineas", 0) for m in meses_anio)
                    n_uds_p = sum(m.get("n_unidades", 0) for m in meses_anio)
                    # Calcular horas anuales reales
                    try:
                        from views._ops_data_helper import calcular_horas_estandar_mes
                        horas_p = sum(
                            calcular_horas_estandar_mes(f"{periodo_sel}-{m:02d}", personas).get("horas_total", 0)
                            for m in range(1, 13)
                        )
                        n_dias_p = 252  # aprox días hábiles año
                    except Exception:
                        horas_p = horas_mes * 12
                        n_dias_p = 252
                    horas_dia_p = horas_p / n_dias_p if n_dias_p else 8.4

                # Compat con variables antiguas usadas abajo
                n_pedidos_mes = n_pedidos_p
                n_lineas_mes = n_lineas_p
                n_uds_mes = n_uds_p
                horas = horas_p
                n_dias_habiles = n_dias_p

                # KPI cards: 3 dimensiones × 3 vistas (persona/día · hora equipo · día equipo)
                st.markdown(f"##### 📊 Productividad {label_p} · {personas} personas · {horas:,.0f}h totales · {n_dias_habiles} días hábiles")
                st.caption(
                    "Pedido = 1 cliente atendido · Línea = 1 SKU distinto pickeado · "
                    "Unidad = 1 ítem físico tomado · Más detalle abajo."
                )

                # ════════════════════════════════════════════════════════
                # PRE-CÁLCULOS
                # ════════════════════════════════════════════════════════
                # Horario UnionX: L-J 9h + V 6h => promedio (4*9+6)/5 = 8.4h/día
                # Por mes: 21 días hábiles aprox
                horas_dia_calendar = horas / n_dias_habiles if n_dias_habiles else 0  # ~8.4h/día calendar
                # POR PERSONA (cada operario individual)
                ped_pers_dia = (n_pedidos_mes / personas / n_dias_habiles) if (personas and n_dias_habiles) else 0
                lin_pers_dia = (n_lineas_mes / personas / n_dias_habiles) if (personas and n_dias_habiles) else 0
                uds_pers_dia = (n_uds_mes / personas / n_dias_habiles) if (personas and n_dias_habiles) else 0
                ped_pers_h = (ped_pers_dia / horas_dia_calendar) if horas_dia_calendar else 0
                lin_pers_h = (lin_pers_dia / horas_dia_calendar) if horas_dia_calendar else 0
                uds_pers_h = (uds_pers_dia / horas_dia_calendar) if horas_dia_calendar else 0
                # POR DÍA EQUIPO ENTERO (todos trabajando juntos)
                ped_eq_dia = n_pedidos_mes / n_dias_habiles if n_dias_habiles else 0
                lin_eq_dia = n_lineas_mes / n_dias_habiles if n_dias_habiles else 0
                uds_eq_dia = n_uds_mes / n_dias_habiles if n_dias_habiles else 0
                # POR HORA REAL del día (en 1h calendar, cuánto procesa el equipo entero)
                ped_eq_h = ped_eq_dia / horas_dia_calendar if horas_dia_calendar else 0
                lin_eq_h = lin_eq_dia / horas_dia_calendar if horas_dia_calendar else 0
                uds_eq_h = uds_eq_dia / horas_dia_calendar if horas_dia_calendar else 0
                # Mix
                lineas_x_pedido = (n_lineas_mes / n_pedidos_mes) if n_pedidos_mes else 0
                uds_x_pedido = (n_uds_mes / n_pedidos_mes) if n_pedidos_mes else 0

                # FILA 1 — Por persona (lo que produce CADA operario)
                st.markdown(f"**🧑 Por persona** — lo que produce **cada operario individualmente**")
                ck1, ck2, ck3 = st.columns(3)
                ck1.metric("Pedidos / persona / día", f"{ped_pers_dia:.1f}",
                           delta=f"{ped_pers_h:.2f} ped/persona/h")
                ck2.metric("Líneas / persona / día", f"{lin_pers_dia:.1f}",
                           delta=f"{lin_pers_h:.2f} lín/persona/h",
                           help="Bench: 60-120 lín/persona/h B2C (depende del mix)")
                ck3.metric("Unidades / persona / día", f"{uds_pers_dia:.1f}",
                           delta=f"{uds_pers_h:.2f} uds/persona/h")

                # FILA 2 — Por hora REAL del día (TODO el equipo trabajando junto)
                st.markdown(
                    f"**⏱️ Por hora del día** — lo que produce **el equipo entero** "
                    f"en 1 hora calendaria (jornada típica: {horas_dia_calendar:.1f}h/día)"
                )
                ch1, ch2, ch3 = st.columns(3)
                ch1.metric("Pedidos / hora", f"{ped_eq_h:.1f}",
                           delta=f"{personas} personas trabajando juntas",
                           help=f"En 1h del día, el equipo entero ({personas} pers.) procesa {ped_eq_h:.1f} pedidos. "
                                f"= {ped_eq_dia:.0f} ped/día / {horas_dia_calendar:.1f}h jornada")
                ch2.metric("Líneas / hora", f"{lin_eq_h:.1f}",
                           delta=f"{personas} personas trabajando juntas",
                           help=f"En 1h del día, el equipo procesa {lin_eq_h:.1f} líneas (todos los SKUs distintos)")
                ch3.metric("Unidades / hora", f"{uds_eq_h:.1f}",
                           delta=f"{personas} personas trabajando juntas",
                           help=f"En 1h del día, el equipo mueve {uds_eq_h:.1f} unidades físicas")

                # FILA 3 — Equipo entero por día (totales agregados)
                st.markdown(f"**⚙️ Por día (equipo entero)** — totales del día")
                ce1, ce2, ce3, ce4 = st.columns(4)
                ce1.metric("Pedidos / día", f"{ped_eq_dia:,.0f}",
                           delta=f"≈ {ped_eq_h:.1f}/h del día")
                ce2.metric("Líneas / día", f"{lin_eq_dia:,.0f}",
                           delta=f"≈ {lin_eq_h:.1f}/h del día")
                ce3.metric("Unidades / día", f"{uds_eq_dia:,.0f}",
                           delta=f"≈ {uds_eq_h:.1f}/h del día")
                ce4.metric("Mix promedio", f"{lineas_x_pedido:.2f} lín/ped",
                           delta=f"{uds_x_pedido:.1f} uds/ped",
                           help="Mix bajo (1 SKU/pedido) = pedidos chicos, picking más rápido")

                st.divider()

                # Sub-tabs por período NATURAL (calendario, no rolling)
                prod_subtabs = st.tabs(["🗓️ Por mes (últimos 12)",
                                         "📆 Por semana (mes actual)",
                                         "📅 Por día (últimos 14)",
                                         "🔮 Forecast 3 meses"])

                # Leer snapshot precalculado
                snap_prod = snap_pick if 'snap_pick' in dir() else cargar_snapshot()
                prod_meses_data = (snap_prod.get("productividad_meses_12m", {}) or {}).get("items", [])
                prod_sem_data = (snap_prod.get("productividad_semanas_mes_actual", {}) or {}).get("items", [])
                prod_dias_data = (snap_prod.get("productividad_dias_14d", {}) or {}).get("items", [])

                # Helper para enriquecer df con productividad por persona/día/hora
                def _enrich_prod(df, horas_periodo, dias_periodo=1, n_personas=personas):
                    """Agrega columnas: ped_pers_dia, ped_pers_h, lin_pers_dia, ..."""
                    if df.empty or n_personas <= 0:
                        return df
                    horas_persona = horas_periodo / n_personas if n_personas else 0
                    df["ped_per_h"] = (df["n_pedidos"] / horas_periodo).round(2) if horas_periodo else 0
                    df["lin_per_h"] = (df["n_lineas"] / horas_periodo).round(2) if horas_periodo else 0
                    df["uds_per_h"] = (df["n_unidades"] / horas_periodo).round(2) if horas_periodo else 0
                    df["ped_per_pers_dia"] = (df["n_pedidos"] / n_personas / dias_periodo).round(1) if dias_periodo else 0
                    df["lin_per_pers_dia"] = (df["n_lineas"] / n_personas / dias_periodo).round(1) if dias_periodo else 0
                    df["uds_per_pers_dia"] = (df["n_unidades"] / n_personas / dias_periodo).round(1) if dias_periodo else 0
                    df["ped_per_pers_h"] = (df["n_pedidos"] / n_personas / horas_persona).round(2) if horas_persona else 0
                    df["lin_per_pers_h"] = (df["n_lineas"] / n_personas / horas_persona).round(2) if horas_persona else 0
                    df["uds_per_pers_h"] = (df["n_unidades"] / n_personas / horas_persona).round(2) if horas_persona else 0
                    return df

                # ── Por MES (calendario) ─────────────────────────────────
                with prod_subtabs[0]:
                    st.markdown("##### Productividad por mes calendario")
                    if prod_meses_data:
                        df_m = pd.DataFrame(prod_meses_data)
                        df_m = _enrich_prod(df_m, horas_periodo=horas, dias_periodo=21)

                        cm1, cm2, cm3 = st.columns(3)
                        cm1.markdown("**Pedidos / mes**")
                        cm1.bar_chart(df_m.set_index("periodo")["n_pedidos"], height=240)
                        cm2.markdown("**Líneas / mes**")
                        cm2.bar_chart(df_m.set_index("periodo")["n_lineas"], height=240)
                        cm3.markdown("**Unidades / mes**")
                        cm3.bar_chart(df_m.set_index("periodo")["n_unidades"], height=240)

                        st.markdown("**Productividad (líneas/persona/h) — tendencia mensual**")
                        st.line_chart(df_m.set_index("periodo")["lin_per_pers_h"], height=200)

                        st.markdown("##### 📋 Tabla detalle (totales + por persona)")
                        df_show = df_m[["periodo", "n_pedidos", "n_lineas", "n_unidades",
                                        "ped_per_pers_dia", "lin_per_pers_dia", "uds_per_pers_dia",
                                        "ped_per_pers_h", "lin_per_pers_h", "uds_per_pers_h"]].rename(
                            columns={"periodo": "Mes",
                                     "n_pedidos": "Pedidos", "n_lineas": "Líneas", "n_unidades": "Uds",
                                     "ped_per_pers_dia": "Ped/persona/día",
                                     "lin_per_pers_dia": "Lín/persona/día",
                                     "uds_per_pers_dia": "Uds/persona/día",
                                     "ped_per_pers_h": "Ped/persona/h",
                                     "lin_per_pers_h": "Lín/persona/h",
                                     "uds_per_pers_h": "Uds/persona/h"})
                        st.dataframe(df_show, use_container_width=True, hide_index=True)
                        st.caption(f"Asume {personas} personas constantes. Mes hábil = 21 días.")
                    else:
                        st.info("Sin datos en snapshot. Esperá próxima actualización 00:00 Chile.")

                # ── Por SEMANA (mes actual) ──────────────────────────────
                with prod_subtabs[1]:
                    st.markdown(f"##### Productividad por semana — {mes_actual}")
                    if prod_sem_data:
                        df_s = pd.DataFrame(prod_sem_data)
                        horas_sem = horas / 4.33 if horas else 0
                        df_s = _enrich_prod(df_s, horas_periodo=horas_sem, dias_periodo=5)

                        cs1, cs2, cs3 = st.columns(3)
                        cs1.markdown("**Pedidos / semana**")
                        cs1.bar_chart(df_s.set_index("periodo")["n_pedidos"], height=200)
                        cs2.markdown("**Líneas / semana**")
                        cs2.bar_chart(df_s.set_index("periodo")["n_lineas"], height=200)
                        cs3.markdown("**Unidades / semana**")
                        cs3.bar_chart(df_s.set_index("periodo")["n_unidades"], height=200)

                        df_show = df_s[["periodo", "n_pedidos", "n_lineas", "n_unidades",
                                        "ped_per_pers_dia", "lin_per_pers_dia", "uds_per_pers_dia",
                                        "ped_per_pers_h", "lin_per_pers_h", "uds_per_pers_h"]].rename(
                            columns={"periodo": "Semana",
                                     "n_pedidos": "Pedidos", "n_lineas": "Líneas", "n_unidades": "Uds",
                                     "ped_per_pers_dia": "Ped/persona/día",
                                     "lin_per_pers_dia": "Lín/persona/día",
                                     "uds_per_pers_dia": "Uds/persona/día",
                                     "ped_per_pers_h": "Ped/persona/h",
                                     "lin_per_pers_h": "Lín/persona/h",
                                     "uds_per_pers_h": "Uds/persona/h"})
                        st.dataframe(df_show, use_container_width=True, hide_index=True)
                        st.caption(f"Asume {personas} personas, ~{horas_sem:.0f}h/semana, 5 días hábiles.")
                    else:
                        st.info("Sin datos en snapshot.")

                # ── Por DÍA (últimos 14) ─────────────────────────────────
                with prod_subtabs[2]:
                    st.markdown("##### Productividad por día (últimos 14)")
                    if prod_dias_data:
                        df_d = pd.DataFrame(prod_dias_data)
                        horas_dia = horas / 21 if horas else 0
                        df_d = _enrich_prod(df_d, horas_periodo=horas_dia, dias_periodo=1)

                        cd1, cd2, cd3 = st.columns(3)
                        cd1.markdown("**Pedidos / día**")
                        cd1.bar_chart(df_d.set_index("periodo")["n_pedidos"], height=200)
                        cd2.markdown("**Líneas / día**")
                        cd2.bar_chart(df_d.set_index("periodo")["n_lineas"], height=200)
                        cd3.markdown("**Unidades / día**")
                        cd3.bar_chart(df_d.set_index("periodo")["n_unidades"], height=200)

                        df_show = df_d[["periodo", "n_pedidos", "n_lineas", "n_unidades",
                                        "ped_per_pers_dia", "lin_per_pers_dia", "uds_per_pers_dia",
                                        "ped_per_pers_h", "lin_per_pers_h", "uds_per_pers_h"]].rename(
                            columns={"periodo": "Día",
                                     "n_pedidos": "Pedidos", "n_lineas": "Líneas", "n_unidades": "Uds",
                                     "ped_per_pers_dia": "Ped/persona/día",
                                     "lin_per_pers_dia": "Lín/persona/día",
                                     "uds_per_pers_dia": "Uds/persona/día",
                                     "ped_per_pers_h": "Ped/persona/h",
                                     "lin_per_pers_h": "Lín/persona/h",
                                     "uds_per_pers_h": "Uds/persona/h"})
                        st.dataframe(df_show, use_container_width=True, hide_index=True)
                        st.caption(f"Asume {personas} personas, ~{horas_dia:.1f}h/día hábil. Sáb/Dom = 0 esperado.")
                    else:
                        st.info("Sin datos en snapshot.")

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
        # TAB 4 — RECEPCIONES (snapshot + lazy fallback)
        except Exception as _e_tab:
            st.error(f"❌ Error en Tab 3: {type(_e_tab).__name__}: {_e_tab}")
            import traceback as _tb
            with st.expander("🐛 Ver traceback completo"):
                st.code(_tb.format_exc())

    # ============================================================
    with tabs[4]:
        try:
            st.markdown("### 📥 Recepciones")
            st.caption("Tiempo entre fecha programada y fecha efectiva de recepción de embarques")

            from views._ops_kpis_snapshot import (
                cargar_snapshot as _cs_rec, snapshot_status as _ss_rec,
                get_recepcion_ventana as _grv,
            )
            ss_rec = _ss_rec()
            snap_rec = _cs_rec()

            col_r, col_r2 = st.columns([1, 3])
            with col_r:
                dias_r = st.selectbox("Ventana", [30, 60, 90, 180, 365], index=2, key="rec_dias")

            if ss_rec["existe"]:
                with col_r2:
                    st.success(f"📸 {ss_rec['leyenda']}")

            usar_snap_rec = ss_rec["existe"]

            # Siempre mostrar la última info disponible del snapshot
            rec = _grv(dias_r) or snap_rec.get("kpis", {}).get("tiempo_recepcion_90d", {})

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

            # Volumen movs: siempre del snapshot (90d)
            vol = snap_rec.get("kpis", {}).get("volumen_movs_90d", {})
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
        except Exception as _e_tab:
            st.error(f"❌ Error en Tab 4: {type(_e_tab).__name__}: {_e_tab}")
            import traceback as _tb
            with st.expander("🐛 Ver traceback completo"):
                st.code(_tb.format_exc())

    # ============================================================
    with tabs[5]:
        try:
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
        except Exception as _e_tab:
            st.error(f"❌ Error en Tab 5: {type(_e_tab).__name__}: {_e_tab}")
            import traceback as _tb
            with st.expander("🐛 Ver traceback completo"):
                st.code(_tb.format_exc())

