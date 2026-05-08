"""
Vista por KAM (Contribución).

Fuente: Sheet 'Análisis de Contribución' → 'Comparación Resultados Kam'
Muestra: ranking + drill-down KAM/Canal con margen, comisiones y resultado contribución.
"""
import pandas as pd
import streamlit as st

from views._contribucion_loader import cargar_hoja, parsear_columnas_numericas, fmt_pesos_M, fmt_pesos_K


def render():
    st.title("👤 Contribución — Por KAM")
    st.caption("Ranking de KAMs + drill-down por Canal · venta, margen y resultado contribución")

    if st.button("🔄 Refrescar", key="contrib_kam_refresh"):
        st.cache_data.clear()
        st.rerun()

    try:
        df = cargar_hoja("Comparación Resultados Kam")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    if df.empty:
        st.warning("Hoja vacía.")
        return

    cols_num = ["Venta KAM", "Margen Directo KAM", " Comisión Venta KAM",
                "Comisión Envío KAM", " Marketing KAM", " Resultado Contribución KAM",
                "Resultado Venta Contable", " Venta Real Contable", " Margen Front Contable",
                "Comisión Venta Contable", "Comisión Logística Contable", "Marketing Contable"]
    cols_num = [c for c in cols_num if c in df.columns]
    df = parsear_columnas_numericas(df, cols_num)

    # Forward-fill KAM (en el sheet aparece solo en 1ra fila del grupo)
    df["KAM"] = df["KAM"].replace("", pd.NA).ffill()

    # Filtros
    c1, c2 = st.columns(2)
    with c1:
        kams = sorted([k for k in df["KAM"].dropna().unique() if k])
        kam_sel = st.multiselect("KAM", kams, default=kams, key="ckam_kam")
    with c2:
        canales = sorted([c for c in df["Canal"].dropna().unique() if c])
        canal_sel = st.multiselect("Canal", canales, default=canales, key="ckam_canal")

    df_f = df.copy()
    if kam_sel:
        df_f = df_f[df_f["KAM"].isin(kam_sel)]
    if canal_sel:
        df_f = df_f[df_f["Canal"].isin(canal_sel)]

    if df_f.empty:
        st.warning("Sin filas con esos filtros.")
        return

    # Ranking por KAM (suma)
    st.divider()
    st.markdown("### 🏆 Ranking de KAMs (por venta total)")
    rank = df_f.groupby("KAM").agg({
        "Venta KAM": "sum",
        "Margen Directo KAM": "sum",
        " Resultado Contribución KAM": "sum",
    }).reset_index().sort_values("Venta KAM", ascending=False)

    rank["Margen %"] = rank["Margen Directo KAM"] / rank["Venta KAM"]
    rank["Contrib %"] = rank[" Resultado Contribución KAM"] / rank["Venta KAM"]

    # Render ranking
    rows_rank = []
    for i, (_, r) in enumerate(rank.iterrows(), 1):
        rows_rank.append({
            "#": i,
            "KAM": r["KAM"],
            "Venta": fmt_pesos_M(r["Venta KAM"]),
            "Margen Directo": fmt_pesos_M(r["Margen Directo KAM"]),
            "Margen %": f"{r['Margen %']*100:.1f}%" if pd.notna(r['Margen %']) else "—",
            "Contribución": fmt_pesos_M(r[" Resultado Contribución KAM"]),
            "Contrib %": f"{r['Contrib %']*100:.1f}%" if pd.notna(r['Contrib %']) else "—",
        })
    st.dataframe(pd.DataFrame(rows_rank), use_container_width=True, hide_index=True)

    # Drill-down por canal del KAM seleccionado
    st.divider()
    st.markdown("### 🔍 Detalle por KAM y Canal")

    rows_det = []
    for _, r in df_f.iterrows():
        rows_det.append({
            "KAM": r.get("KAM", ""),
            "Canal": r.get("Canal", ""),
            "Venta": fmt_pesos_M(r.get("Venta KAM")),
            "Margen Directo": fmt_pesos_M(r.get("Margen Directo KAM")),
            "Comis. Venta": fmt_pesos_K(r.get(" Comisión Venta KAM")),
            "Comis. Envío": fmt_pesos_K(r.get("Comisión Envío KAM")),
            "Marketing": fmt_pesos_K(r.get(" Marketing KAM")),
            "Contribución": fmt_pesos_M(r.get(" Resultado Contribución KAM")),
        })
    st.dataframe(pd.DataFrame(rows_det), use_container_width=True, hide_index=True, height=500)
