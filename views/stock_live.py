"""Stock LIVE — vista mínima: Stock Total + Por Bodega + Descarga."""
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


def render():
    with st.sidebar:
        st.markdown("### 📦 **Stock LIVE**")
        st.caption("Inventario en tiempo real")
        st.markdown("---")
        if st.button("🔄 Refrescar Odoo", width='stretch', type="primary", key="stock_refresh"):
            cached_stock.clear()
            st.rerun()

    try:
        data = cached_stock()
    except Exception as e:
        st.error(f"❌ Error consultando Odoo: {type(e).__name__}: {e}")
        return

    df_sku = pd.DataFrame(data['skus'])
    df_det = pd.DataFrame(data['detalle'])
    if df_sku.empty:
        st.warning("Sin datos de stock")
        return

    df_sku['Semaforo'] = df_sku['Semaforo'].map(SEM_DISPLAY).fillna(df_sku['Semaforo'])

    # Filtros sidebar (defensivos)
    with st.sidebar:
        st.markdown("##### Filtros")
        sku_f = []
        if 'SKU' in df_sku.columns:
            sku_options = sorted([s for s in df_sku['SKU'].dropna().unique() if s])
            sku_f = st.multiselect("SKU", sku_options, default=[], placeholder="Buscar SKU...", key="stock_sku")

        cat_f = "Todas"
        if 'Categoria' in df_sku.columns:
            cat_options = sorted([c for c in df_sku['Categoria'].dropna().unique() if c])
            cat_f = st.selectbox("Categoría", ["Todas"] + cat_options, key="stock_cat")

        marca_f = "Todas"
        if 'Marca' in df_sku.columns:
            marca_options = sorted([m for m in df_sku['Marca'].dropna().unique() if m])
            marca_f = st.selectbox("Marca", ["Todas"] + marca_options, key="stock_marca")

        bod_f = "Todas"
        if 'Bodega' in df_det.columns:
            bod_options = sorted([b for b in df_det['Bodega'].dropna().unique() if b])
            bod_f = st.selectbox("Bodega", ["Todas"] + bod_options, key="stock_bod")

    df_f = df_sku.copy()
    if sku_f and 'SKU' in df_f.columns:
        df_f = df_f[df_f['SKU'].isin(sku_f)]
    if cat_f != "Todas" and 'Categoria' in df_f.columns:
        df_f = df_f[df_f['Categoria'] == cat_f]
    if marca_f != "Todas" and 'Marca' in df_f.columns:
        df_f = df_f[df_f['Marca'] == marca_f]
    if bod_f != "Todas" and 'Bodega' in df_f.columns:
        df_f = df_f[df_f['Bodega'].astype(str).str.contains(bod_f, na=False)]

    # Header
    st.title("📦 Stock LIVE")
    gen = data.get('metadata', {}).get('generado_en', datetime.now().isoformat())
    try:
        gen_fmt = datetime.fromisoformat(gen).strftime('%d/%m/%Y %H:%M')
    except Exception:
        gen_fmt = gen[:16]
    st.caption(f"Inventario en tiempo real desde Odoo · Generado: {gen_fmt} · Cache 5 min")

    # KPIs principales
    total_val = float(df_f['Valor'].sum()) if 'Valor' in df_f.columns else 0
    total_qty = float(df_f['Qty'].sum()) if 'Qty' in df_f.columns else 0
    n_skus = len(df_f)

    cols = st.columns(3)
    cols[0].markdown(kpi_card("Valor Inventario", f"${total_val/1e6:,.1f}M", f"{n_skus:,} SKUs activos", COLOR_VENTA), unsafe_allow_html=True)
    cols[1].markdown(kpi_card("Unidades en stock", f"{total_qty:,.0f}", "", COLOR_MARGEN), unsafe_allow_html=True)
    cols[2].markdown(kpi_card("SKUs activos", f"{n_skus:,}", "", COLOR_VENTA), unsafe_allow_html=True)

    st.divider()

    # Tabs reducidos: Stock Total + Por Bodega
    tab1, tab2 = st.tabs(["📊 Stock Total", "🏭 Por Bodega"])

    with tab1:
        st.markdown("### Stock Total Empresa")
        cols = [c for c in [
            'SKU', 'Producto', 'Categoria', 'Marca', 'Qty', 'Reservada', 'Disponible',
            'Costo Unit', 'Valor', 'Semaforo',
        ] if c in df_f.columns]
        dfd = df_f[cols].sort_values('Valor', ascending=False) if 'Valor' in df_f.columns else df_f[cols]

        st.dataframe(
            dfd.style.map(_color_sem, subset=['Semaforo']).format({
                'Qty': '{:,.0f}', 'Reservada': '{:,.0f}', 'Disponible': '{:,.0f}',
                'Costo Unit': '${:,.0f}', 'Valor': '${:,.0f}',
            }),
            height=520, width='stretch', hide_index=True,
        )
        st.caption(f"{len(dfd):,} SKUs · Valor total: ${dfd['Valor'].sum() if 'Valor' in dfd.columns else 0:,.0f}")

        # Descarga Excel del Stock Total
        if st.button("📥 Descargar Stock Total (Excel)", key="dl_stock_total", width='stretch'):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as w:
                dfd.to_excel(w, index=False, sheet_name='Stock Total')
            output.seek(0)
            st.download_button(
                label=f"💾 Confirmar descarga ({len(dfd):,} filas)",
                data=output,
                file_name=f"Stock_total_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                key="dl_stock_total_btn",
                width='stretch',
            )

    with tab2:
        st.markdown("### Detalle por Bodega y Ubicación")
        df_d2 = df_det.copy()
        if sku_f and 'SKU' in df_d2.columns:
            df_d2 = df_d2[df_d2['SKU'].isin(sku_f)]
        if cat_f != "Todas" and 'Categoria' in df_d2.columns:
            df_d2 = df_d2[df_d2['Categoria'] == cat_f]
        if bod_f != "Todas" and 'Bodega' in df_d2.columns:
            df_d2 = df_d2[df_d2['Bodega'].astype(str).str.contains(bod_f, na=False)]

        cols2 = [c for c in ['Bodega', 'Ubicacion', 'Tipo', 'SKU', 'Producto', 'Categoria',
                              'Marca', 'Qty', 'Reservada', 'Disponible', 'Costo Unit', 'Valor'] if c in df_d2.columns]
        if 'Valor' in df_d2.columns:
            df_d2_sorted = df_d2[cols2].sort_values(['Bodega', 'Valor'], ascending=[True, False])
        else:
            df_d2_sorted = df_d2[cols2]

        st.dataframe(
            df_d2_sorted.style.format({
                'Qty': '{:,.0f}', 'Reservada': '{:,.0f}', 'Disponible': '{:,.0f}',
                'Costo Unit': '${:,.0f}', 'Valor': '${:,.0f}',
            }),
            height=520, width='stretch', hide_index=True,
        )
        st.caption(f"{len(df_d2):,} líneas · Valor: ${df_d2['Valor'].sum() if 'Valor' in df_d2.columns else 0:,.0f}")

        if st.button("📥 Descargar Por Bodega (Excel)", key="dl_stock_bodega", width='stretch'):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as w:
                df_d2_sorted.to_excel(w, index=False, sheet_name='Stock por Bodega')
            output.seek(0)
            st.download_button(
                label=f"💾 Confirmar descarga ({len(df_d2):,} filas)",
                data=output,
                file_name=f"Stock_por_bodega_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                key="dl_stock_bodega_btn",
                width='stretch',
            )

    st.markdown("---")
    total_locs = data.get('metadata', {}).get('total_locations', 0)
    st.caption(f"Stock UnionX · {datetime.now().strftime('%d/%m/%Y %H:%M')} · Odoo {total_locs} ubicaciones · Cache 5 min")
