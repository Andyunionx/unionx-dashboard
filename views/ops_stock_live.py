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
        from views._ops_capacidad_helper import slots_liberables
        with st.spinner("Calculando KPIs operacionales…"):
            sl = _safe_call(slots_liberables, umbral_qty_chico=5, min_ubicaciones=2,
                            default={"items": [], "slots_liberables_total": 0, "skus_a_consolidar": 0})
            uso = _safe_call(uso_posiciones, dias=7, default={"valor": None, "error": None})
            alertas = _safe_call(alertas_operacionales, default=[]) or []

        kpis = data.get("kpis", {}) or {}
        # Ocupación por # posiciones (exacto, no depende de m³ caja master)
        uso_v = uso.get("valor", {}) if uso else {}
        total_pos = uso_v.get("total_posiciones", 0)
        n_vacias_h = uso_v.get("vacias", 0)
        n_ocup_h = total_pos - n_vacias_h
        ocup_pct_pos = (n_ocup_h / total_pos * 100) if total_pos else 0

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

        ocup_color = "#DC2626" if ocup_pct_pos > 90 else ("#EA580C" if ocup_pct_pos > 80 else "#16A34A")
        c3.markdown(_kpi_card_simple("Ocupación bodega",
                                      f"{ocup_pct_pos:.0f}%" if total_pos else "—",
                                      f"{n_ocup_h} / {total_pos} posiciones (exacto)",
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
            "📊 Volumen operacional (pedidos/líneas)",
        ])

        # ── 4.1 Disponibilidad por posición (m³ pausado, ahora # posiciones) ──
        with slot_subtabs[0]:
            st.warning(
                "🚧 **Métricas de m³ pausadas — Roadmap H2** · "
                "Odoo tiene `product.volume` (unidad individual) pero NO la **caja master**, "
                "que es lo que realmente ocupa espacio. Cuando se cargue caja master "
                "(campo Odoo o desde PI/PL del agente COMEX), reactivamos m³ con precisión."
            )
            st.markdown("### 📍 Disponibilidad por posición (datos exactos: # posiciones)")

            # Usar uso_posiciones (exacto, no depende de m³)
            from views._ops_stock_helper import uso_posiciones as _uso_pos
            uso_d = _safe_call(_uso_pos, dias=7, default={"valor": None, "detalle": {}, "error": None})

            if uso_d.get("error") or not uso_d.get("valor"):
                st.info("Sin datos de uso de posiciones desde Odoo")
            else:
                v = uso_d["valor"]
                det = uso_d.get("detalle", {}) or {}

                kc1, kc2, kc3, kc4 = st.columns(4)
                kc1.markdown(_kpi_card_simple("Total posiciones",
                                              f"{v.get('total_posiciones', 0)}",
                                              "Leaf de CA1/Stock", "#1F4E79"),
                             unsafe_allow_html=True)
                kc2.markdown(_kpi_card_simple("Vacías (disponibles)",
                                              f"{v.get('vacias', 0)}",
                                              f"{v.get('pct_vacias', 0)*100:.0f}% del total",
                                              "#16A34A"),
                             unsafe_allow_html=True)
                kc3.markdown(_kpi_card_simple("Activas (mov ≤7d)",
                                              f"{v.get('activas', 0)}",
                                              f"{v.get('pct_activas', 0)*100:.0f}% del total",
                                              "#1F4E79"),
                             unsafe_allow_html=True)
                kc4.markdown(_kpi_card_simple("Dormidas (sin mov >30d)",
                                              f"{v.get('dormidas', 0)}",
                                              f"{v.get('pct_dormidas', 0)*100:.0f}% del total",
                                              "#EA580C" if v.get('dormidas', 0) > 30 else "#94A3B8"),
                             unsafe_allow_html=True)

                st.divider()

                # Tabla unificada
                st.markdown("#### Detalle de posiciones (combinadas)")
                rows = []
                for p in det.get("vacias", []):
                    rows.append({"Posición": p.get("nombre", "?"), "Estado": "🟢 VACIA",
                                 "SKUs": p.get("n_skus", 0)})
                for p in det.get("activas", []):
                    rows.append({"Posición": p.get("nombre", "?"), "Estado": "🔵 ACTIVA",
                                 "SKUs": p.get("n_skus", 0)})
                for p in det.get("dormidas", []):
                    rows.append({"Posición": p.get("nombre", "?"), "Estado": "🟠 DORMIDA",
                                 "SKUs": p.get("n_skus", 0)})

                if rows:
                    df_pos = pd.DataFrame(rows).sort_values(["Estado", "Posición"])
                    st.dataframe(df_pos, use_container_width=True, hide_index=True, height=400)

                    out_pos = io.BytesIO()
                    with pd.ExcelWriter(out_pos, engine='openpyxl') as w:
                        df_pos.to_excel(w, index=False, sheet_name='Posiciones')
                    out_pos.seek(0)
                    st.download_button(
                        label=f"📥 Descargar posiciones (Excel · {len(df_pos):,} filas)",
                        data=out_pos.getvalue(),
                        file_name=f"Posiciones_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        key="ops_dl_posiciones",
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

        # ── 4.4 Forecast de capacidad bodega 90 días ─────────────────────
        with slot_subtabs[3]:
            from views._ops_capacidad_forecast_helper import render_forecast_capacidad
            render_forecast_capacidad()

        # ── 4.5 Volumen operacional (pedidos/líneas/uds proyectados) ────
        with slot_subtabs[4]:
            from views._ops_volumen_operacional_helper import render_volumen_operacional
            render_volumen_operacional()

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
