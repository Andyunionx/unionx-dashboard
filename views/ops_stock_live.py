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
        "🔄 SKUs duplicados",
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
        from views._ops_stock_helper import (
            skus_duplicados, uso_posiciones, alertas_operacionales,
        )
        with st.spinner("Calculando KPIs operacionales…"):
            dup = _safe_call(skus_duplicados, min_ubicaciones=2, default={"valor": [], "total": 0, "valor_total": 0})
            uso = _safe_call(uso_posiciones, dias=7, default={"valor": None, "error": None})
            alertas = _safe_call(alertas_operacionales, default=[]) or []

        kpis = data.get("kpis", {}) or {}
        ocup = data.get("ocupacion", {}) or {}

        c1, c2, c3 = st.columns(3)
        c1.markdown(_kpi_card_simple("SKUs activos", f"{n_skus:,}",
                                      f"${total_val/1e6:,.1f}M valor", "#1F4E79"),
                    unsafe_allow_html=True)

        n_dup = dup.get("total", 0) if dup else 0
        valor_dup = dup.get("valor_total", 0) if dup else 0
        c2.markdown(_kpi_card_simple("SKUs duplicados", f"{n_dup:,}",
                                      f"${valor_dup/1e6:,.1f}M en >1 ubicación",
                                      "#EA580C" if n_dup > 50 else "#1F4E79"),
                    unsafe_allow_html=True)

        ocup_pct = ocup.get("pct", 0) if ocup else 0
        ocup_color = "#DC2626" if ocup_pct > 90 else ("#EA580C" if ocup_pct > 80 else "#16A34A")
        c3.markdown(_kpi_card_simple("Ocupación CA1/Stock", f"{ocup_pct}%",
                                      f"{ocup.get('occupied', 0)} / {ocup.get('total', 0)} posiciones",
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
    # TAB 4 — SKUs DUPLICADOS
    # ============================================================
    with tabs[3]:
        from views._ops_stock_helper import skus_duplicados
        st.markdown("### 🔄 SKUs en múltiples ubicaciones físicas")
        st.caption(
            "Detectar SKUs duplicados ayuda a: (1) reducir errores de picking, "
            "(2) consolidar capital atado, (3) liberar posiciones para nuevos embarques."
        )

        col_n1, col_n2 = st.columns([1, 3])
        with col_n1:
            min_ubic = st.selectbox("Filtrar ≥ ubicaciones", [2, 3, 4, 5], index=0, key="ops_dup_minloc")
        dup_t = _safe_call(skus_duplicados, min_ubicaciones=min_ubic, default={"valor": [], "total": 0, "valor_total": 0})
        with col_n2:
            st.markdown(f"**Total SKUs con ≥{min_ubic} ubicaciones:** {dup_t.get('total', 0):,} · "
                        f"**Valor total:** ${dup_t.get('valor_total', 0)/1e6:,.1f}M")

        if dup_t.get("error"):
            st.warning(f"⚠️ {dup_t['error']}")
        elif dup_t.get("valor"):
            data_dup = dup_t["valor"]
            rows = []
            for d in data_dup[:200]:
                rows.append({
                    "SKU": d["sku"][:60],
                    "# Ubicaciones": d["n_ubicaciones"],
                    "Qty Total": f"{d['qty_total']:,.0f}",
                    "Valor": f"${d['valor']/1e3:,.0f} K",
                    "Ubicaciones": " · ".join(d["ubicaciones"][:5]),
                    "Sugerencia consolidar": d["principal"],
                })
            if rows:
                df_dup = pd.DataFrame(rows)
                st.dataframe(df_dup, use_container_width=True, hide_index=True, height=520)
                st.caption(f"Mostrando {len(rows)} de {len(data_dup)}. Ordenado por valor.")

                # Descargar
                out_dup = io.BytesIO()
                df_dup_full = pd.DataFrame([{
                    "SKU": d["sku"], "# Ubicaciones": d["n_ubicaciones"],
                    "Qty Total": d["qty_total"], "Valor": d["valor"],
                    "Ubicaciones": " · ".join(d["ubicaciones"]),
                    "Sugerencia consolidar": d["principal"],
                    "Qty en principal": d.get("qty_principal", 0),
                } for d in data_dup])
                with pd.ExcelWriter(out_dup, engine='openpyxl') as w:
                    df_dup_full.to_excel(w, index=False, sheet_name='SKUs duplicados')
                out_dup.seek(0)
                st.download_button(
                    label=f"📥 Descargar SKUs duplicados (Excel · {len(data_dup):,})",
                    data=out_dup.getvalue(),
                    file_name=f"Stock_duplicados_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    key="ops_dl_dup",
                    use_container_width=True,
                )
            else:
                st.info("Sin SKUs con ese filtro.")
        else:
            st.info("Sin datos.")

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
