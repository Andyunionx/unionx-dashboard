"""
Oportunidades — brechas grandes Meta vs Real (canales/KAMs lejos de la meta).

Fuente: 'Analisis Meta vs Resultados'.
"""
import pandas as pd
import streamlit as st

from views.contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas, fmt_pesos_M,
    render_contrib_filters, aplicar_filtros,
)


COLS_NUM = ['Meta Venta', 'Resultado Venta', 'Meta Contribución', 'Resultado Contribución']


def render():
    with st.sidebar:
        st.markdown("### 💡 **Oportunidades**")
        st.caption("Brechas vs meta")
        st.markdown("---")
        if st.button("🔄 Refrescar Sheet", use_container_width=True, type="primary", key="copo_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("💡 Oportunidades — Brechas vs Meta")
    st.caption("Canales/KAMs/Negocios lejos de la meta — priorizar acciones")

    try:
        df = cargar_hoja("Analisis Meta vs Resultados")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    if df.empty:
        st.warning("Sin datos")
        return

    df = parsear_columnas_numericas(df, COLS_NUM)

    # Filtros al tope
    sel = render_contrib_filters(df, prefix="copo")
    df_f = aplicar_filtros(df, sel)
    st.caption(f"Filas filtradas: {len(df_f):,} de {len(df):,}")
    st.markdown("---")

    # Calcular brecha (gap) por entidad
    df_f['Gap Venta $'] = df_f['Resultado Venta'].fillna(0) - df_f['Meta Venta'].fillna(0)
    df_f['Gap Contrib $'] = df_f['Resultado Contribución'].fillna(0) - df_f['Meta Contribución'].fillna(0)
    df_f['% Cumpl Venta'] = (df_f['Resultado Venta'].fillna(0) / df_f['Meta Venta'].replace(0, 1) * 100).round(1)
    df_f['% Cumpl Contrib'] = (df_f['Resultado Contribución'].fillna(0) / df_f['Meta Contribución'].replace(0, 1) * 100).round(1)

    # ===== Brechas más grandes (peor cumplimiento) =====
    st.markdown("### 🔴 Mayores brechas — Venta")
    st.caption("Donde el Real es más bajo que la Meta (mayor oportunidad)")

    df_neg_v = df_f[df_f['Gap Venta $'] < 0].sort_values('Gap Venta $').head(15).copy()
    if not df_neg_v.empty:
        cols = [c for c in ['Trimestre', 'Mes', 'Negocio', 'Canal', 'KAM',
                             'Meta Venta', 'Resultado Venta', 'Gap Venta $', '% Cumpl Venta'] if c in df_neg_v.columns]
        df_show = df_neg_v[cols].copy()
        for c in ['Meta Venta', 'Resultado Venta', 'Gap Venta $']:
            if c in df_show.columns:
                df_show[c] = df_show[c].apply(fmt_pesos_M)
        df_show['% Cumpl Venta'] = df_show['% Cumpl Venta'].astype(str) + '%'
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=380)
    else:
        st.success("✅ No hay brechas negativas")

    st.divider()

    # ===== Sobre-cumplimiento (oportunidad inversa) =====
    st.markdown("### 🟢 Mayores excesos — Venta")
    st.caption("Donde el Real supera la Meta (replicar en otros canales/KAMs)")

    df_pos_v = df_f[df_f['Gap Venta $'] > 0].sort_values('Gap Venta $', ascending=False).head(15).copy()
    if not df_pos_v.empty:
        cols = [c for c in ['Trimestre', 'Mes', 'Negocio', 'Canal', 'KAM',
                             'Meta Venta', 'Resultado Venta', 'Gap Venta $', '% Cumpl Venta'] if c in df_pos_v.columns]
        df_show = df_pos_v[cols].copy()
        for c in ['Meta Venta', 'Resultado Venta', 'Gap Venta $']:
            if c in df_show.columns:
                df_show[c] = df_show[c].apply(fmt_pesos_M)
        df_show['% Cumpl Venta'] = df_show['% Cumpl Venta'].astype(str) + '%'
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=380)

    st.divider()

    # ===== Brechas Contribución =====
    st.markdown("### 🔴 Mayores brechas — Contribución")
    st.caption("Donde el Real de contribución está bajo la meta")

    df_neg_c = df_f[df_f['Gap Contrib $'] < 0].sort_values('Gap Contrib $').head(15).copy()
    if not df_neg_c.empty:
        cols = [c for c in ['Trimestre', 'Mes', 'Negocio', 'Canal', 'KAM',
                             'Meta Contribución', 'Resultado Contribución', 'Gap Contrib $', '% Cumpl Contrib'] if c in df_neg_c.columns]
        df_show = df_neg_c[cols].copy()
        for c in ['Meta Contribución', 'Resultado Contribución', 'Gap Contrib $']:
            if c in df_show.columns:
                df_show[c] = df_show[c].apply(fmt_pesos_M)
        df_show['% Cumpl Contrib'] = df_show['% Cumpl Contrib'].astype(str) + '%'
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=380)
