"""
Vista General de Contribución Comercial.

Fuente: Google Sheet 'Análisis de Contribución' → hoja 'Resumen Resultados'
Muestra: KPIs consolidados Año/Mes/Negocio + tabla con margenes y comisiones %.
"""
import pandas as pd
import streamlit as st

from views._contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas,
    fmt_pesos_M, fmt_pct,
)


def render():
    st.title("📊 Contribución Comercial — Vista General")
    st.caption("Fuente: Google Sheet 'Análisis de Contribución' · Cache 5 min · "
               "[Abrir Sheet](https://docs.google.com/spreadsheets/d/1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4/)")

    if st.button("🔄 Refrescar", key="contrib_general_refresh"):
        st.cache_data.clear()
        st.rerun()

    try:
        df = cargar_hoja("Resumen Resultados")
    except Exception as e:
        st.error(f"❌ Error al leer Sheet: {type(e).__name__}: {e}")
        st.info("Verificá que el SA `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com` "
                "tenga acceso al Sheet, y que `gcp_service_account` esté configurado en Streamlit Secrets.")
        return

    if df.empty:
        st.warning("La hoja 'Resumen Resultados' está vacía.")
        return

    # Parsear columnas numéricas
    cols_num = ["SUM de Venta KAM", " Venta REAL KAM", "% Margen Directo",
                "% Comisión Venta", "% Comisión Envío", "% Marketing",
                "% Resultado Contribución", "SUM de AÑO"]
    cols_num = [c for c in cols_num if c in df.columns]
    df = parsear_columnas_numericas(df, cols_num)

    # Filtros
    c1, c2, c3 = st.columns(3)
    with c1:
        anios = sorted([a for a in df["AÑO"].dropna().unique() if a])
        anio_sel = st.selectbox("Año", ["Todos"] + anios, key="cgen_year")
    with c2:
        meses = sorted([m for m in df["Mes"].dropna().unique() if m and m != ""])
        mes_sel = st.selectbox("Mes", ["Todos"] + meses, key="cgen_mes")
    with c3:
        negocios = sorted([n for n in df["Negocio"].dropna().unique() if n])
        neg_sel = st.selectbox("Negocio", ["Todos"] + negocios, key="cgen_neg")

    df_f = df.copy()
    if anio_sel != "Todos":
        df_f = df_f[df_f["AÑO"] == anio_sel]
    if mes_sel != "Todos":
        df_f = df_f[df_f["Mes"] == mes_sel]
    if neg_sel != "Todos":
        df_f = df_f[df_f["Negocio"] == neg_sel]

    # KPIs consolidados
    venta_total = df_f[" Venta REAL KAM"].sum() if " Venta REAL KAM" in df_f.columns else 0
    venta_kam = df_f["SUM de Venta KAM"].sum() if "SUM de Venta KAM" in df_f.columns else 0
    margen_prom = df_f["% Margen Directo"].mean() if "% Margen Directo" in df_f.columns else 0
    contrib_prom = df_f["% Resultado Contribución"].mean() if "% Resultado Contribución" in df_f.columns else 0

    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("💰 Venta REAL", fmt_pesos_M(venta_total))
    k2.metric("👤 Venta KAM", fmt_pesos_M(venta_kam))

    color_m = "🟢" if margen_prom and margen_prom >= 0.40 else ("🟡" if margen_prom and margen_prom >= 0.27 else "🔴")
    k3.metric(f"{color_m} % Margen Directo", fmt_pct(margen_prom))

    color_c = "🟢" if contrib_prom and contrib_prom >= 0.27 else ("🟡" if contrib_prom and contrib_prom >= 0.20 else "🔴")
    k4.metric(f"{color_c} % Contrib. Resultado", fmt_pct(contrib_prom))

    st.divider()

    # Tabla
    st.markdown("### Detalle")
    df_show = df_f.copy()
    if " Venta REAL KAM" in df_show.columns:
        df_show[" Venta REAL KAM"] = df_show[" Venta REAL KAM"].apply(fmt_pesos_M)
    if "SUM de Venta KAM" in df_show.columns:
        df_show["SUM de Venta KAM"] = df_show["SUM de Venta KAM"].apply(fmt_pesos_M)
    for pct_col in ["% Margen Directo", "% Comisión Venta", "% Comisión Envío",
                    "% Marketing", "% Resultado Contribución"]:
        if pct_col in df_show.columns:
            df_show[pct_col] = df_show[pct_col].apply(fmt_pct)

    st.dataframe(df_show, use_container_width=True, hide_index=True, height=500)
    st.caption(f"{len(df_show)} filas · descargá la data desde el Sheet original si necesitás Excel")
