"""
Vista Stock LIVE — app Operaciones.

Combina:
  1. Stock disponible (tabla + descarga Excel) — vista clásica MD
  2. Lente OPERACIONAL (WMS): duplicados, uso posiciones, alertas

Datos en vivo desde Odoo (parquet pre-computado o cuenta servicio OPS_ODOO_USER).
Cache 5-15 min.
"""
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from views.shared import cached_stock, kpi_card, COLOR_VENTA, COLOR_MARGEN, COLOR_COSTO


SEM_DISPLAY = {
    'QUIEBRE': '🔴 QUIEBRE',
    'CRITICO': '🔴 CRITICO',
    'BAJO': '🟡 BAJO',
    'OPTIMO': '🟢 OPTIMO',
    'SOBRESTOCK': '🔵 SOBRESTOCK',
    'SIN VENTA': '⚪ SIN VENTA',
}


def _color_sem(val):
    s = str(val)
    if "QUIEBRE" in s or "CRITICO" in s:
        return "background-color:#FEE2E2; color:#991B1B; font-weight:600"
    if "BAJO" in s:
        return "background-color:#FEF3C7; color:#92400E; font-weight:600"
    if "OPTIMO" in s:
        return "background-color:#D1FAE5; color:#065F46; font-weight:600"
    if "SOBRESTOCK" in s:
        return "background-color:#DBEAFE; color:#1E40AF; font-weight:600"
    return "color:#94A3B8"


def _kpi_card_simple(label: str, value: str, sub: str = "", color: str = "#1F4E79") -> str:
    return f"""<div style="background:white;border-radius:12px;padding:16px 18px;text-align:center;
        box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #E2E8F0;height:100%;">
        <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;margin-bottom:4px;">{label}</div>
        <div style="font-size:1.5rem;font-weight:700;color:{color};line-height:1.2;">{value}</div>
        <div style="font-size:0.7rem;color:#94A3B8;margin-top:2px;">{sub}</div>
    </div>"""


def _safe_call(fn, *args, default=None, **kwargs):
    """Wrapper para que helpers Odoo que crasheen no tumben toda la vista."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        st.session_state.setdefault('_ops_stock_errors', []).append(
            f"{fn.__name__}: {type(e).__name__}: {str(e)[:120]}"
        )
        return default


def render():
    # ============================================================
    # SIDEBAR
    # ============================================================
    with st.sidebar:
        st.markdown("### 📦 **Stock LIVE**")
        st.caption("Disponibilidad + WMS Operacional")
        st.markdown("---")
        if st.button("🔄 Refrescar Odoo", use_container_width=True, type="primary", key="ops_stock_refresh"):
            st.cache_data.clear()
            st.session_state.pop('_ops_stock_errors', None)
            st.rerun()

    # ============================================================
    # CARGA DATOS (defensivo)
    # ============================================================
    try:
        data = cached_stock()
    except Exception as e:
        st.error(f"❌ Error consultando Odoo: {type(e).__name__}: {e}")
        return

    df_sku = pd.DataFrame(data.get('skus', []))
    df_det = pd.DataFrame(data.get('detalle', []))

    if df_sku.empty:
        st.warning("Sin datos de stock — verificar parquet o conexión Odoo")
        return

    # Display semáforo bonito
    if 'Semaforo' in df_sku.columns:
        df_sku['Semaforo'] = df_sku['Semaforo'].map(SEM_DISPLAY).fillna(df_sku['Semaforo'])

    # ============================================================
    # FILTROS SIDEBAR
    # ============================================================
    with st.sidebar:
        st.markdown("##### Filtros")
        sku_f = []
        if 'SKU' in df_sku.columns:
            sku_options = sorted([s for s in df_sku['SKU'].dropna().unique() if s])
            sku_f = st.multiselect("SKU", sku_options, default=[], placeholder="Buscar SKU…", key="ops_stock_sku")

        cat_f = "Todas"
        if 'Categoria' in df_sku.columns:
            cat_options = sorted([c for c in df_sku['Categoria'].dropna().unique() if c])
            cat_f = st.selectbox("Categoría", ["Todas"] + cat_options, key="ops_stock_cat")

        marca_f = "Todas"
        if 'Marca' in df_sku.columns:
            marca_options = sorted([m for m in df_sku['Marca'].dropna().unique() if m])
            marca_f = st.selectbox("Marca", ["Todas"] + marca_options, key="ops_stock_marca")

        bod_f = "Todas"
        if not df_det.empty and 'Bodega' in df_det.columns:
            bod_options = sorted([b for b in df_det['Bodega'].dropna().unique() if b])
            bod_f = st.selectbox("Bodega", ["Todas"] + bod_options, key="ops_stock_bod")

    # Aplicar filtros a df_sku
    df_f = df_sku.copy()
    if sku_f and 'SKU' in df_f.columns:
        df_f = df_f[df_f['SKU'].isin(sku_f)]
    if cat_f != "Todas" and 'Categoria' in df_f.columns:
        df_f = df_f[df_f['Categoria'] == cat_f]
    if marca_f != "Todas" and 'Marca' in df_f.columns:
        df_f = df_f[df_f['Marca'] == marca_f]
    if bod_f != "Todas" and 'Bodega' in df_f.columns:
        df_f = df_f[df_f['Bodega'].astype(str).str.contains(bod_f, na=False)]

    # ============================================================
    # HEADER
    # ============================================================
    st.title("📦 Stock LIVE")
    gen = data.get('metadata', {}).get('generado_en', datetime.now().isoformat())
    try:
        gen_fmt = datetime.fromisoformat(gen).strftime('%d/%m/%Y %H:%M')
    except Exception:
        gen_fmt = str(gen)[:16]
    st.caption(f"Inventario en tiempo real desde Odoo · Generado: {gen_fmt} · Cache 5-15 min")

    # KPIs cabecera
    total_val = float(df_f['Valor'].sum()) if 'Valor' in df_f.columns else 0
    total_qty = float(df_f['Qty'].sum()) if 'Qty' in df_f.columns else 0
    n_skus = len(df_f)

    cols = st.columns(3)
    cols[0].markdown(kpi_card("Valor Inventario", f"${total_val/1e6:,.1f}M",
                              f"{n_skus:,} SKUs activos", COLOR_VENTA), unsafe_allow_html=True)
    cols[1].markdown(kpi_card("Unidades en stock", f"{total_qty:,.0f}", "", COLOR_MARGEN),
                     unsafe_allow_html=True)
    cols[2].markdown(kpi_card("SKUs activos", f"{n_skus:,}", "", COLOR_VENTA),
                     unsafe_allow_html=True)

    st.divider()

    # ============================================================
    # TABS
    # ============================================================
    tabs = st.tabs([
        "📊 Stock Total",
        "🏭 Por Bodega",
        "🚦 Resumen Operacional",
        "📐 Eficiencia de slotting",
        "📍 Uso de posiciones",
        "🔁 Rotación",
        "⚠️ Alertas operacionales",
    ])

    # ============================================================
    # TAB 1 — STOCK TOTAL (descargable)
    # ============================================================
    with tabs[0]:
        st.markdown("### Stock Total Empresa")
        cols_st = [c for c in [
            'SKU', 'Producto', 'Categoria', 'Marca', 'Qty', 'Reservada', 'Disponible',
            'Costo Unit', 'Valor', 'Semaforo',
        ] if c in df_f.columns]
        dfd = df_f[cols_st].sort_values('Valor', ascending=False) if 'Valor' in df_f.columns else df_f[cols_st]

        st.dataframe(
            dfd.style.map(_color_sem, subset=['Semaforo']).format({
                'Qty': '{:,.0f}', 'Reservada': '{:,.0f}', 'Disponible': '{:,.0f}',
                'Costo Unit': '${:,.0f}', 'Valor': '${:,.0f}',
            }) if 'Semaforo' in dfd.columns else dfd.style.format({
                'Qty': '{:,.0f}', 'Reservada': '{:,.0f}', 'Disponible': '{:,.0f}',
                'Costo Unit': '${:,.0f}', 'Valor': '${:,.0f}',
            }),
            height=520, use_container_width=True, hide_index=True,
        )
        st.caption(f"{len(dfd):,} SKUs · Valor: ${dfd['Valor'].sum() if 'Valor' in dfd.columns else 0:,.0f}")

        # Descarga directa
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as w:
            dfd.to_excel(w, index=False, sheet_name='Stock Total')
        output.seek(0)
        st.download_button(
            label=f"📥 Descargar Stock Total (Excel · {len(dfd):,} filas)",
            data=output.getvalue(),
            file_name=f"Stock_total_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            key="ops_dl_stock_total",
            use_container_width=True,
        )

    # ============================================================
    # TAB 2 — POR BODEGA (descargable)
    # ============================================================
    with tabs[1]:
        st.markdown("### Detalle por Bodega y Ubicación")
        if df_det.empty:
            st.info("Sin detalle por bodega disponible")
        else:
            df_d2 = df_det.copy()
            if sku_f and 'SKU' in df_d2.columns:
                df_d2 = df_d2[df_d2['SKU'].isin(sku_f)]
            if cat_f != "Todas" and 'Categoria' in df_d2.columns:
                df_d2 = df_d2[df_d2['Categoria'] == cat_f]
            if bod_f != "Todas" and 'Bodega' in df_d2.columns:
                df_d2 = df_d2[df_d2['Bodega'].astype(str).str.contains(bod_f, na=False)]

            cols2 = [c for c in ['Bodega', 'Ubicacion', 'Tipo', 'SKU', 'Producto', 'Categoria',
                                 'Marca', 'Qty', 'Reservada', 'Disponible', 'Costo Unit', 'Valor']
                     if c in df_d2.columns]
            df_d2_sorted = (df_d2[cols2].sort_values(['Bodega', 'Valor'], ascending=[True, False])
                            if 'Valor' in df_d2.columns else df_d2[cols2])

            st.dataframe(
                df_d2_sorted.style.format({
                    'Qty': '{:,.0f}', 'Reservada': '{:,.0f}', 'Disponible': '{:,.0f}',
                    'Costo Unit': '${:,.0f}', 'Valor': '${:,.0f}',
                }),
                height=520, use_container_width=True, hide_index=True,
            )
            st.caption(f"{len(df_d2):,} líneas · Valor: ${df_d2['Valor'].sum() if 'Valor' in df_d2.columns else 0:,.0f}")

            output2 = io.BytesIO()
            with pd.ExcelWriter(output2, engine='openpyxl') as w:
                df_d2_sorted.to_excel(w, index=False, sheet_name='Stock por Bodega')
            output2.seek(0)
            st.download_button(
                label=f"📥 Descargar Por Bodega (Excel · {len(df_d2):,} filas)",
                data=output2.getvalue(),
                file_name=f"Stock_por_bodega_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                key="ops_dl_stock_bodega",
                use_container_width=True,
            )

    # ============================================================
    # TAB 3 — RESUMEN OPERACIONAL
    # ============================================================
    with tabs[2]:
        # Carga lazy (solo cuando el user entra al tab)
        from views._ops_stock_helper import uso_posiciones, alertas_operacionales
        from views._ops_capacidad_helper import (
            slots_liberables, disponibilidad_posiciones,
        )
        with st.spinner("Calculando KPIs operacionales…"):
            sl = _safe_call(slots_liberables, umbral_qty_chico=5, min_ubicaciones=2,
                            default={"items": [], "slots_liberables_total": 0, "skus_a_consolidar": 0})
            disp_t = _safe_call(disponibilidad_posiciones, default={"totales": {}, "config": {}})
            uso = _safe_call(uso_posiciones, dias=7, default={"valor": None, "error": None})
            alertas = _safe_call(alertas_operacionales, default=[]) or []

        kpis = data.get("kpis", {}) or {}
        tot_disp = disp_t.get("totales", {}) or {}

        c1, c2, c3 = st.columns(3)
        c1.markdown(_kpi_card_simple("SKUs activos", f"{n_skus:,}",
                                      f"${total_val/1e6:,.1f}M valor", "#1F4E79"),
                    unsafe_allow_html=True)

        n_lib = sl.get("slots_liberables_total", 0)
        n_skus_consolidar = sl.get("skus_a_consolidar", 0)
        c2.markdown(_kpi_card_simple("Slots liberables", f"{n_lib:,}",
                                      f"Consolidando {n_skus_consolidar} SKUs (frag ≤5)",
                                      "#16A34A" if n_lib > 0 else "#94A3B8"),
                    unsafe_allow_html=True)

        ocup_pct = tot_disp.get("pct_ocupacion", 0)
        ocup_color = "#DC2626" if ocup_pct > 90 else ("#EA580C" if ocup_pct > 80 else "#16A34A")
        c3.markdown(_kpi_card_simple("Ocupación bodega",
                                      f"{ocup_pct:.0f}%" if ocup_pct else "—",
                                      f"{tot_disp.get('m3_ocupado', 0):,.0f} / {tot_disp.get('m3_capacidad', 0):,.0f} m³",
                                      ocup_color),
                    unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        c4, c5, c6 = st.columns(3)
        if uso and uso.get("valor"):
            v = uso["valor"]
            c4.markdown(_kpi_card_simple("Posiciones activas (7d)", f"{v.get('activas', 0)}",
                                          f"{v.get('pct_activas', 0)*100:.0f}% del total", "#16A34A"),
                        unsafe_allow_html=True)
            c5.markdown(_kpi_card_simple("Posiciones dormidas", f"{v.get('dormidas', 0)}",
                                          "Stock pero sin mov >30d",
                                          "#EA580C" if v.get('dormidas', 0) > 30 else "#94A3B8"),
                        unsafe_allow_html=True)
            c6.markdown(_kpi_card_simple("Posiciones vacías", f"{v.get('vacias', 0)}",
                                          "Disponibles para asignar", "#1F4E79"),
                        unsafe_allow_html=True)
        else:
            c4.info("Uso posiciones: sin datos o error Odoo")

        st.markdown("<br>", unsafe_allow_html=True)

        c7, c8, c9 = st.columns(3)
        n_quiebre = kpis.get("n_quiebre_critico", 0)
        c7.markdown(_kpi_card_simple("Críticos / Quiebre", f"{n_quiebre}",
                                      "< 30 días stock o sin stock", "#DC2626"),
                    unsafe_allow_html=True)
        n_sobre = kpis.get("n_sobrestock", 0)
        c8.markdown(_kpi_card_simple("Sobrestock", f"{n_sobre}",
                                      "> 180 días con venta", "#1F4E79"),
                    unsafe_allow_html=True)
        n_sin = kpis.get("n_sin_venta", 0)
        c9.markdown(_kpi_card_simple("Sin venta 30d", f"{n_sin}",
                                      "Candidatos a liquidación", "#94A3B8"),
                    unsafe_allow_html=True)

        st.divider()

        if alertas:
            st.markdown("### ⚠️ Alertas activas")
            for a in alertas[:5]:
                sev = a.get("severidad", "")
                if sev == "CRITICA":
                    st.error(f"🔴 **{a.get('tipo')}** · {a.get('mensaje')}")
                elif sev == "ALTA":
                    st.warning(f"🟡 **{a.get('tipo')}** · {a.get('mensaje')}")
                else:
                    st.info(f"🔵 **{a.get('tipo')}** · {a.get('mensaje')}")
        else:
            st.success("✅ Sin alertas operacionales activas")

        # Mostrar errores si hay
        errs = st.session_state.get('_ops_stock_errors', [])
        if errs:
            with st.expander(f"🐛 Errores helpers Odoo ({len(errs)})", expanded=False):
                for e in errs[:10]:
                    st.code(e)

    # ============================================================
    # TAB 4 — EFICIENCIA DE SLOTTING
    # (capacidad m³ por posición, slots liberables, slotting subóptimo,
    #  forecast de capacidad para próximos embarques)
    # ============================================================
    with tabs[3]:
        from views._ops_capacidad_helper import (
            disponibilidad_posiciones, slots_liberables, slotting_suboptimo,
        )
        from views._ops_data_helper import (
            get_proximos_embarques, kpi_capacidad_recepcion,
        )

        st.markdown("### 📐 Eficiencia de slotting & capacidad de recepción")
        st.caption(
            "Disponibilidad real m³ por posición · Consolidación de fragmentos · "
            "Slotting óptimo SKUs A · Forecast capacidad para próximos embarques"
        )

        slot_subtabs = st.tabs([
            "📦 Disponibilidad m³ por posición",
            "🆓 Slots liberables (consolidar)",
            "🐢 Slotting subóptimo (relocar SKUs A)",
            "📥 Capacidad para próximos embarques",
        ])

        # ── 4.1 Disponibilidad m³ por posición ──────────────────────────
        with slot_subtabs[0]:
            disp = _safe_call(disponibilidad_posiciones, default={"posiciones": [], "totales": {}, "config": {}})
            if disp.get("error"):
                st.warning(f"⚠️ {disp['error']}")
            elif not disp.get("posiciones"):
                st.info("Sin datos de capacidad. Carga `m3_por_slot_default` en la pestaña KPIs WMS · Datos manuales.")
            else:
                tot = disp["totales"]
                cfg = disp.get("config", {})

                # KPI cards
                kc1, kc2, kc3, kc4 = st.columns(4)
                kc1.markdown(_kpi_card_simple("Capacidad total", f"{tot['m3_capacidad']:,.0f} m³",
                                              f"{tot['n_posiciones']} posiciones", "#1F4E79"),
                             unsafe_allow_html=True)
                kc2.markdown(_kpi_card_simple("Ocupado actual", f"{tot['m3_ocupado']:,.0f} m³",
                                              f"{tot['pct_ocupacion']:.1f}% del total",
                                              "#DC2626" if tot['pct_ocupacion'] > 85 else "#EA580C" if tot['pct_ocupacion'] > 70 else "#16A34A"),
                             unsafe_allow_html=True)
                kc3.markdown(_kpi_card_simple("Libre", f"{tot['m3_libre']:,.0f} m³",
                                              f"{tot['n_disponibles']} posiciones disp.", "#16A34A"),
                             unsafe_allow_html=True)
                kc4.markdown(_kpi_card_simple("Posiciones llenas", f"{tot['n_llenas']:,}",
                                              f"≥90% ocupación", "#EA580C"),
                             unsafe_allow_html=True)

                # Calidad del dato volumétrico
                with st.expander("ℹ️ Calidad del dato volumétrico", expanded=False):
                    fo = cfg.get("fuente_volumen_odoo", 0)
                    fc = cfg.get("fuente_volumen_categ", 0)
                    fs = cfg.get("fuente_volumen_sin_dato", 0)
                    total_p = fo + fc + fs
                    if total_p > 0:
                        st.markdown(
                            f"- **{fo:,}** productos con `volume` directo de Odoo ({fo/total_p*100:.0f}%)\n"
                            f"- **{fc:,}** productos con fallback m³ por categoría ({fc/total_p*100:.0f}%)\n"
                            f"- **{fs:,}** productos sin volumen — no contribuyen al cálculo ({fs/total_p*100:.0f}%)"
                        )
                    else:
                        st.info("Sin productos analizados")
                    cap_slot = cfg.get("m3_slot_default", 0)
                    if cap_slot > 0:
                        st.caption(f"Capacidad por slot asumida: **{cap_slot:.2f} m³** "
                                   f"(carga m³ por slot real en pestaña Datos manuales para mayor precisión)")
                    else:
                        st.warning("⚠️ Sin capacidad por slot definida → ocupación %  no calculable")

                # Filtros
                st.markdown("#### Detalle por posición")
                fc1, fc2 = st.columns([1, 3])
                with fc1:
                    estado_f = st.selectbox("Estado", ["Todas", "VACIA", "DISPONIBLE", "MEDIO", "LLENA"],
                                            key="ops_pos_estado")
                with fc2:
                    sort_f = st.selectbox("Ordenar por",
                        ["m³ libre (desc)", "% ocupación (asc)", "% ocupación (desc)", "Posición"],
                        key="ops_pos_sort")

                df_pos = pd.DataFrame(disp["posiciones"])
                if estado_f != "Todas":
                    df_pos = df_pos[df_pos["estado"] == estado_f]
                if sort_f == "m³ libre (desc)":
                    df_pos = df_pos.sort_values("m3_libre", ascending=False)
                elif sort_f == "% ocupación (asc)":
                    df_pos = df_pos.sort_values("pct_ocupacion", ascending=True)
                elif sort_f == "% ocupación (desc)":
                    df_pos = df_pos.sort_values("pct_ocupacion", ascending=False)
                else:
                    df_pos = df_pos.sort_values("posicion")

                st.dataframe(
                    df_pos[["posicion", "estado", "m3_capacidad", "m3_ocupado", "m3_libre",
                            "pct_ocupacion", "n_skus", "n_unidades", "calidad_dato"]].rename(columns={
                        "posicion": "Posición",
                        "estado": "Estado",
                        "m3_capacidad": "Cap (m³)",
                        "m3_ocupado": "Ocup (m³)",
                        "m3_libre": "Libre (m³)",
                        "pct_ocupacion": "% Ocup",
                        "n_skus": "SKUs",
                        "n_unidades": "Uds",
                        "calidad_dato": "Calidad dato",
                    }),
                    use_container_width=True, hide_index=True, height=480,
                )
                st.caption(f"{len(df_pos):,} posiciones mostradas")

                # Descarga
                out_pos = io.BytesIO()
                with pd.ExcelWriter(out_pos, engine='openpyxl') as w:
                    df_pos.to_excel(w, index=False, sheet_name='Posiciones m3')
                out_pos.seek(0)
                st.download_button(
                    label=f"📥 Descargar disponibilidad m³ (Excel · {len(df_pos):,} filas)",
                    data=out_pos.getvalue(),
                    file_name=f"Disponibilidad_m3_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    key="ops_dl_disp_m3",
                    use_container_width=True,
                )

        # ── 4.2 Slots liberables ────────────────────────────────────────
        with slot_subtabs[1]:
            st.markdown("### 🆓 Slots que liberás consolidando fragmentos")
            st.caption(
                "Lógica con tu setup: Odoo agrega bien CA1/Stock y dirige picking automáticamente, "
                "así que el problema NO es 'duplicados'. El problema real es **fragmentación**: "
                "un SKU con qty pequeñas en varios slots ocupando posiciones que podrían recibir embarques."
            )

            cs1, cs2 = st.columns(2)
            with cs1:
                umbral = st.slider("Qty 'fragmento' (consolidar a slot principal)",
                                   1, 50, 5, key="ops_slot_umbral")
            with cs2:
                min_ubi = st.selectbox("≥ ubicaciones", [2, 3, 4], index=0, key="ops_slot_minubi")

            sl = _safe_call(slots_liberables, umbral_qty_chico=umbral, min_ubicaciones=min_ubi,
                            default={"items": [], "slots_liberables_total": 0})

            if sl.get("error"):
                st.warning(f"⚠️ {sl['error']}")
            elif sl.get("items"):
                k1, k2 = st.columns(2)
                k1.markdown(_kpi_card_simple("Slots liberables",
                                              f"{sl['slots_liberables_total']:,}",
                                              "Si consolidás los fragmentos", "#16A34A"),
                            unsafe_allow_html=True)
                k2.markdown(_kpi_card_simple("SKUs a consolidar",
                                              f"{sl['skus_a_consolidar']:,}",
                                              f"con qty ≤ {umbral} en slots adicionales", "#1F4E79"),
                            unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                rows = []
                for d in sl["items"][:300]:
                    rows.append({
                        "SKU": d["sku"][:60],
                        "# Slots": d["n_ubicaciones"],
                        "Qty total": f"{d['qty_total']:,.0f}",
                        "Slot principal": d["slot_principal"],
                        "Qty principal": f"{d['qty_principal']:,.0f}",
                        "Slots a liberar": d["n_fragmentos"],
                        "Qty a mover": f"{d['qty_a_mover']:,.0f}",
                        "Detalle slots": " · ".join(d["slots_a_liberar"][:3]),
                    })
                df_sl = pd.DataFrame(rows)
                st.dataframe(df_sl, use_container_width=True, hide_index=True, height=480)

                # Descarga full
                df_sl_full = pd.DataFrame([{
                    "SKU": d["sku"], "# Slots": d["n_ubicaciones"],
                    "Qty total": d["qty_total"], "Valor total": d["valor_total"],
                    "Slot principal": d["slot_principal"], "Qty principal": d["qty_principal"],
                    "# Slots a liberar": d["n_fragmentos"],
                    "Slots a liberar": " · ".join(d["slots_a_liberar"]),
                    "Qty a mover": d["qty_a_mover"],
                } for d in sl["items"]])
                out_sl = io.BytesIO()
                with pd.ExcelWriter(out_sl, engine='openpyxl') as w:
                    df_sl_full.to_excel(w, index=False, sheet_name='Slots liberables')
                out_sl.seek(0)
                st.download_button(
                    label=f"📥 Descargar plan consolidación (Excel · {len(sl['items']):,})",
                    data=out_sl.getvalue(),
                    file_name=f"Slots_liberables_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    key="ops_dl_slots_lib",
                    use_container_width=True,
                )
            else:
                st.success("✅ No se detectan fragmentos consolidables — slotting óptimo")

        # ── 4.3 Slotting subóptimo ──────────────────────────────────────
        with slot_subtabs[2]:
            st.markdown("### 🐢 SKUs A en zona fría")
            st.caption(
                "Top SKUs por movimientos (zona caliente esperable: cerca de packing). "
                "Si están en zona de baja actividad → re-slotting a posiciones más cercanas reduce OCT."
            )

            cz1, cz2 = st.columns(2)
            with cz1:
                top_n_a = st.slider("Top N SKUs A", 20, 200, 50, key="ops_slot_topa")
            with cz2:
                ventana = st.slider("Ventana actividad (días)", 7, 90, 30, key="ops_slot_vent")

            su = _safe_call(slotting_suboptimo, top_n_a=top_n_a, dias_actividad=ventana,
                            default={"items": [], "n_skus_a_relocar": 0})

            if su.get("error"):
                st.warning(f"⚠️ {su['error']}")
            elif su.get("items"):
                ku1, ku2, ku3 = st.columns(3)
                ku1.markdown(_kpi_card_simple("SKUs A a relocar", f"{su['n_skus_a_relocar']:,}",
                                              f"Top {top_n_a} por movs en {ventana}d", "#EA580C"),
                             unsafe_allow_html=True)
                ku2.markdown(_kpi_card_simple("Zonas calientes detectadas",
                                              f"{su.get('n_zonas_calientes', 0)}",
                                              "Top 20% movimientos", "#16A34A"),
                             unsafe_allow_html=True)
                ku3.markdown(_kpi_card_simple("Zonas frías detectadas",
                                              f"{su.get('n_zonas_frias', 0)}",
                                              "Bottom 50% movimientos", "#94A3B8"),
                             unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                df_su = pd.DataFrame(su["items"])
                st.dataframe(
                    df_su.rename(columns={
                        "sku": "SKU",
                        "posicion_actual": "Posición actual",
                        "qty_en_slot": "Qty en slot",
                        "movimientos_30d": f"# Movs ({ventana}d)",
                        "qty_movida_30d": f"Qty movida ({ventana}d)",
                        "movs_posicion_actual": "Movs en su posición",
                    }),
                    use_container_width=True, hide_index=True, height=480,
                )

                out_su = io.BytesIO()
                with pd.ExcelWriter(out_su, engine='openpyxl') as w:
                    df_su.to_excel(w, index=False, sheet_name='Slotting suboptimo')
                out_su.seek(0)
                st.download_button(
                    label=f"📥 Descargar plan re-slotting (Excel · {len(su['items']):,})",
                    data=out_su.getvalue(),
                    file_name=f"Slotting_suboptimo_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    key="ops_dl_slot_sub",
                    use_container_width=True,
                )
            else:
                st.success("✅ Top SKUs A correctamente ubicados en zona caliente")

        # ── 4.4 Capacidad para próximos embarques ───────────────────────
        with slot_subtabs[3]:
            st.markdown("### 📥 Forecast de capacidad para embarques entrantes")
            st.caption(
                "Cruza disponibilidad m³ ahora vs próximos embarques cargados manualmente. "
                "Roadmap H2: lectura automática del agente COMEX (Steven PI/PL)."
            )

            disp_cap = _safe_call(disponibilidad_posiciones, default={"totales": {"m3_libre": 0}})
            m3_libre = disp_cap.get("totales", {}).get("m3_libre", 0)

            cap = kpi_capacidad_recepcion(m3_libre)
            embarques = get_proximos_embarques(solo_pendientes=True)

            kf1, kf2, kf3 = st.columns(3)
            kf1.markdown(_kpi_card_simple("m³ disponibles ahora", f"{m3_libre:,.0f}",
                                          "Suma posiciones libres", "#16A34A" if m3_libre > 50 else "#EA580C"),
                         unsafe_allow_html=True)
            kf2.markdown(_kpi_card_simple("m³ próximos 30d", f"{cap.get('m3_proximos_30d', 0):,.0f}",
                                          f"{len(embarques)} embarques cargados", "#1F4E79"),
                         unsafe_allow_html=True)
            ratio = cap.get("valor")
            ratio_color = "#16A34A" if ratio and ratio >= 1.2 else "#DC2626" if ratio and ratio < 1 else "#EA580C"
            kf3.markdown(_kpi_card_simple("Ratio capacidad",
                                          f"{ratio:.2f}x" if ratio else "—",
                                          "Disp / requerido (≥1.2 ideal)", ratio_color),
                         unsafe_allow_html=True)

            # Alerta capacidad
            if cap.get("proximo_embarque"):
                pe = cap["proximo_embarque"]
                if not cap.get("ok"):
                    st.error(
                        f"🔴 **Capacidad insuficiente para próximo embarque** · "
                        f"{pe.get('descripcion', 'embarque')} ({pe.get('m3', 0):.0f} m³) "
                        f"ETA {pe.get('eta', '?')} — disp actual {m3_libre:.0f} m³"
                    )
                else:
                    st.success(
                        f"✅ Próximo embarque entra: {pe.get('descripcion', 'embarque')} "
                        f"({pe.get('m3', 0):.0f} m³) ETA {pe.get('eta', '?')}"
                    )

            st.divider()

            # Lista próximos embarques
            st.markdown("#### Embarques cargados")
            if not embarques:
                st.info("Sin embarques cargados. Agregá uno en el formulario abajo.")
            else:
                df_emb = pd.DataFrame(embarques)
                df_emb = df_emb[["eta", "descripcion", "contenedores", "m3"]].rename(columns={
                    "eta": "ETA",
                    "descripcion": "Descripción",
                    "contenedores": "Contenedores",
                    "m3": "m³",
                })
                st.dataframe(df_emb, use_container_width=True, hide_index=True, height=200)

            # Form agregar embarque
            with st.expander("➕ Agregar próximo embarque", expanded=not embarques):
                from views._ops_data_helper import add_proximo_embarque, delete_proximo_embarque
                with st.form("form_emb_nuevo", clear_on_submit=True):
                    fc1, fc2, fc3 = st.columns([1, 2, 1])
                    eta_in = fc1.date_input("ETA", key="emb_eta")
                    desc_in = fc2.text_input("Descripción",
                                             placeholder="Steven – plancha pelo + secadores",
                                             key="emb_desc")
                    cont_in = fc3.number_input("Contenedores", min_value=1, value=1,
                                               key="emb_cont")
                    m3_in = st.number_input("Volumen total (m³)", min_value=0.0, value=67.0,
                                            help="40HC ≈ 67 m³ útil · 20GP ≈ 33 m³",
                                            key="emb_m3")
                    if st.form_submit_button("💾 Guardar embarque", type="primary",
                                              use_container_width=True):
                        ok = add_proximo_embarque(
                            eta=eta_in.strftime("%Y-%m-%d"),
                            m3=m3_in, descripcion=desc_in, contenedores=cont_in,
                        )
                        if ok:
                            st.success("✅ Embarque guardado")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("❌ Error guardando")

            if embarques:
                with st.expander("🗑️ Eliminar embarque cargado"):
                    from views._ops_data_helper import delete_proximo_embarque
                    idx_del = st.selectbox(
                        "Embarque a eliminar",
                        options=list(range(len(embarques))),
                        format_func=lambda i: f"{embarques[i]['eta']} · {embarques[i].get('descripcion', '')[:40]} · {embarques[i].get('m3', 0):.0f} m³",
                        key="emb_del_idx",
                    )
                    if st.button("🗑️ Eliminar", key="emb_del_btn"):
                        if delete_proximo_embarque(idx_del):
                            st.success("Eliminado")
                            st.cache_data.clear()
                            st.rerun()

    # ============================================================
    # TAB 5 — USO DE POSICIONES
    # ============================================================
    with tabs[4]:
        from views._ops_stock_helper import uso_posiciones, ranking_posiciones_actividad
        st.markdown("### 📍 Tasa de uso de posiciones (CA1/Stock)")
        st.caption(
            "Activas = movimientos en últimos 7d · Dormidas = stock sin movimientos >30d · "
            "Vacías = disponibles para asignar"
        )

        uso_t = _safe_call(uso_posiciones, dias=7, default={"valor": None, "error": None})

        if uso_t.get("error"):
            st.warning(f"⚠️ {uso_t['error']}")
        elif uso_t.get("valor"):
            v = uso_t["valor"]
            det = uso_t.get("detalle", {}) or {}

            sub_tabs = st.tabs([
                f"🟢 Activas ({v['activas']})",
                f"🟠 Dormidas ({v['dormidas']})",
                f"⚪ Vacías ({v['vacias']})",
                f"🔥 Más movimientos (30d)",
            ])

            with sub_tabs[0]:
                if det.get("activas"):
                    df_a = pd.DataFrame(det["activas"])
                    cols_drop = [c for c in ["location_id"] if c in df_a.columns]
                    df_a = df_a.drop(columns=cols_drop).rename(columns={"nombre": "Posición", "n_skus": "SKUs"})
                    st.dataframe(df_a, use_container_width=True, hide_index=True, height=400)
                else:
                    st.info("Sin datos")

            with sub_tabs[1]:
                if det.get("dormidas"):
                    st.warning(f"💡 Estas {v['dormidas']} posiciones tienen stock pero sin movimientos en >30d.")
                    df_d = pd.DataFrame(det["dormidas"])
                    cols_drop = [c for c in ["location_id"] if c in df_d.columns]
                    df_d = df_d.drop(columns=cols_drop).rename(columns={"nombre": "Posición", "n_skus": "SKUs"})
                    st.dataframe(df_d, use_container_width=True, hide_index=True, height=400)
                else:
                    st.success("✅ Sin posiciones dormidas")

            with sub_tabs[2]:
                if det.get("vacias"):
                    df_v = pd.DataFrame(det["vacias"])
                    cols_drop = [c for c in ["location_id"] if c in df_v.columns]
                    df_v = df_v.drop(columns=cols_drop).rename(columns={"nombre": "Posición", "n_skus": "SKUs"})
                    st.dataframe(df_v, use_container_width=True, hide_index=True, height=400)
                else:
                    st.warning("⚠️ Sin posiciones vacías — bodega saturada")

            with sub_tabs[3]:
                ranking = _safe_call(ranking_posiciones_actividad, dias=30, top_n=30, default=[])
                if ranking:
                    st.markdown("**Top posiciones con más movimientos en los últimos 30 días.**")
                    st.caption("Posiciones 'calientes' — los SKUs A deberían estar cerca del área de packing.")
                    st.dataframe(pd.DataFrame(ranking), use_container_width=True, hide_index=True, height=520)
                else:
                    st.info("Sin datos de movimientos")
        else:
            st.info("Uso de posiciones: sin datos disponibles")

    # ============================================================
    # TAB 6 — ROTACIÓN
    # ============================================================
    with tabs[5]:
        st.markdown("### 🔁 Rotación detallada")
        st.caption("Rotación = veces que el stock se renueva en el período")

        if df_f.empty:
            st.warning("Sin datos de SKUs")
        elif "Rot 30d Uds" not in df_f.columns:
            st.info("La data actual no incluye columnas de rotación. Refrescar Odoo o regenerar parquet.")
        else:
            df_r = df_f.copy()
            r30_avg = df_r.loc[df_r["Rot 30d Uds"] > 0, "Rot 30d Uds"].mean()
            r90_avg = df_r.loc[df_r.get("Rot 90d Uds", pd.Series([0])) > 0, "Rot 90d Uds"].mean() \
                      if "Rot 90d Uds" in df_r.columns else None

            cr1, cr2, cr3 = st.columns(3)
            cr1.metric("Rotación promedio 30d", f"{r30_avg:.2f}x" if pd.notna(r30_avg) else "—")
            cr2.metric("Rotación promedio 90d",
                       f"{r90_avg:.2f}x" if r90_avg is not None and pd.notna(r90_avg) else "—")
            if "Categoria" in df_r.columns:
                top_cat = df_r.groupby("Categoria")["Rot 30d Uds"].mean().nlargest(1)
                if len(top_cat):
                    cr3.metric("Top categoría rotación", top_cat.index[0],
                               delta=f"{top_cat.values[0]:.2f}x")

            st.divider()

            st.markdown("#### 🚀 Top 20 movers (mayor rotación 30d)")
            cols_top = [c for c in ["SKU", "Producto", "Categoria", "Qty", "Vta 30d Qty",
                                    "Rot 30d Uds", "Rot 90d Uds", "Semaforo"] if c in df_r.columns]
            if "Vta 30d Qty" in df_r.columns:
                top_movers = df_r[df_r["Vta 30d Qty"] > 0].nlargest(20, "Rot 30d Uds")[cols_top]
                st.dataframe(top_movers, use_container_width=True, hide_index=True)
            else:
                st.info("Sin columna Vta 30d Qty")

            st.markdown("#### 🐢 Bottom movers (sin venta 30d, con stock)")
            cols_bot = [c for c in ["SKU", "Producto", "Categoria", "Qty", "Vta 90d Qty",
                                    "Valor", "Semaforo"] if c in df_r.columns]
            if "Vta 30d Qty" in df_r.columns and "Qty" in df_r.columns:
                bottom = df_r[(df_r["Vta 30d Qty"] == 0) & (df_r["Qty"] > 0)]
                if "Valor" in bottom.columns:
                    bottom = bottom.nlargest(20, "Valor")
                st.dataframe(bottom[cols_bot], use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 7 — ALERTAS
    # ============================================================
    with tabs[6]:
        from views._ops_stock_helper import alertas_operacionales
        st.markdown("### ⚠️ Alertas operacionales")
        st.caption("Heurísticas calculadas en cada refresh sobre stock + movimientos + duplicaciones")

        alertas_t = _safe_call(alertas_operacionales, default=[]) or []
        if not alertas_t:
            st.success("✅ Sin alertas activas")
        else:
            for a in alertas_t:
                sev = a.get("severidad", "")
                if sev == "CRITICA":
                    icon = "🔴"; container = st.error
                elif sev == "ALTA":
                    icon = "🟡"; container = st.warning
                else:
                    icon = "🔵"; container = st.info
                with st.container(border=True):
                    container(f"{icon} **{a.get('tipo', '?')}** · {a.get('mensaje', '')}")
                    if a.get("accion"):
                        st.caption(f"💡 {a['accion']}")

    # Footer
    st.markdown("---")
    total_locs = data.get('metadata', {}).get('total_locations', 0)
    st.caption(f"Stock UnionX · {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
               f"Odoo {total_locs} ubicaciones · Cache 5-15 min")
