"""
Administración — detalle de Glosas EERR + Provisiones + Fuera de mes.

Hojas: 'Detalle Glosas 2026', 'Detalle fact provisión 2026', 'Detalle fuera de mes'.
"""
import pandas as pd
import streamlit as st

from views.contribucion_loader import cargar_hoja


def render():
    with st.sidebar:
        st.markdown("### 🛠️ **Administración**")
        st.caption("Detalle EERR para auditoría")
        st.markdown("---")
        if st.button("🔄 Refrescar Sheets", use_container_width=True, type="primary", key="cadm_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("🛠️ Administración — Detalle EERR")
    st.caption("Auditoría de glosas, provisiones y partidas fuera de mes")

    tab1, tab2, tab3 = st.tabs([
        "📋 Glosas 2026",
        "📑 Facturas Provisión 2026",
        "📅 Fuera de Mes",
    ])

    with tab1:
        try:
            df = cargar_hoja("Detalle Glosas 2026")
        except Exception as e:
            st.error(f"❌ Error: {e}")
        else:
            if df.empty:
                st.info("Sin glosas registradas")
            else:
                # Filtros
                c1, c2, c3 = st.columns(3)
                with c1:
                    if 'Mes' in df.columns:
                        meses = sorted([m for m in df['Mes'].dropna().unique() if m])
                        f_mes = st.selectbox("Mes", ["Todos"] + meses, key="cadm_glosa_mes")
                    else:
                        f_mes = "Todos"
                with c2:
                    if 'Cuenta EERR' in df.columns:
                        cuentas = sorted([c for c in df['Cuenta EERR'].dropna().unique() if c])
                        f_cuenta = st.selectbox("Cuenta EERR", ["Todas"] + cuentas, key="cadm_glosa_cta")
                    else:
                        f_cuenta = "Todas"
                with c3:
                    if 'Canal' in df.columns:
                        canales = sorted([c for c in df['Canal'].dropna().unique() if c])
                        f_canal = st.selectbox("Canal", ["Todos"] + canales, key="cadm_glosa_canal")
                    else:
                        f_canal = "Todos"

                df_f = df.copy()
                if f_mes != "Todos":
                    df_f = df_f[df_f['Mes'] == f_mes]
                if f_cuenta != "Todas":
                    df_f = df_f[df_f['Cuenta EERR'] == f_cuenta]
                if f_canal != "Todos":
                    df_f = df_f[df_f['Canal'] == f_canal]

                st.caption(f"Filas: {len(df_f):,}")
                st.dataframe(df_f, use_container_width=True, hide_index=True, height=500)

    with tab2:
        try:
            df = cargar_hoja("Detalle fact provisión 2026")
        except Exception as e:
            st.error(f"❌ Error: {e}")
        else:
            if df.empty:
                st.info("Sin facturas en provisión")
            else:
                st.caption(f"Filas: {len(df):,}")
                st.dataframe(df, use_container_width=True, hide_index=True, height=500)

    with tab3:
        try:
            df = cargar_hoja("Detalle fuera de mes")
        except Exception as e:
            st.error(f"❌ Error: {e}")
        else:
            if df.empty:
                st.info("Sin partidas fuera de mes")
            else:
                st.caption(f"Filas: {len(df):,}")
                st.dataframe(df, use_container_width=True, hide_index=True, height=500)
