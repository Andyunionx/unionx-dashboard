"""
Vista Forecast & Cierre Proyectado — App Finanzas.

Cierre proyectado del año combinando Real YTD + Fcst restante.
Compara contra Ppto y Meta. Gap analysis.

Fuente: pyl_mensual.parquet + ppto_2026.parquet + fcst_eerr.parquet + metas_2026.parquet
"""
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views._fin_data import pyl, ppto_2026, fcst_eerr, metas_2026


MESES_ES = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}


def render():
    with st.sidebar:
        st.markdown("### 🎯 **Forecast cierre**")
        st.caption("Real YTD + Fcst restante")
        st.divider()

    st.title("🎯 Forecast Cierre Año 2026")
    st.caption(
        "Bridge: Real acumulado YTD + Forecast restante = Cierre proyectado "
        "vs Ppto vs Meta"
    )

    df_pyl = pyl()
    df_ppto = ppto_2026()
    df_fcst = fcst_eerr()
    df_metas = metas_2026()

    if df_pyl.empty:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    # Mes actual con datos reales
    df_pyl_2026 = df_pyl[df_pyl["year"] == 2026]
    if df_pyl_2026.empty:
        st.warning("Sin datos 2026 en P&L")
        return
    ultimo_mes_real = int(df_pyl_2026["month"].max())
    st.caption(f"📌 Último mes con datos reales: **{MESES_ES[ultimo_mes_real]} 2026**")

    # ─── BRIDGE POR LÍNEA CLAVE ─────────────────────────────────────────
    st.markdown("### 📊 Bridge Real YTD + Fcst restante → Cierre proyectado")

    LINEAS_CLAVE = [
        "Ingresos por Ventas",
        "Margen Frontal",
        "Margen Contribución",
        "Resultado Operacional (EBIT)",
        "EBITDA",
    ]

    bridge_rows = []
    for nombre in LINEAS_CLAVE:
        # Real YTD
        df_real_ytd = df_pyl_2026[
            (df_pyl_2026["linea"].str.contains(nombre, na=False, case=False))
            & (df_pyl_2026["month"] <= ultimo_mes_real)
        ]
        real_ytd = df_real_ytd["valor"].sum() if not df_real_ytd.empty else 0

        # Fcst restante (meses futuros del año)
        if not df_fcst.empty:
            df_fcst_resto = df_fcst[
                (df_fcst["year"] == 2026)
                & (df_fcst["month"] > ultimo_mes_real)
                & (df_fcst["linea"].str.contains(nombre, na=False, case=False))
            ]
            fcst_resto = df_fcst_resto["valor_fcst"].sum() if not df_fcst_resto.empty else 0
        else:
            fcst_resto = 0

        # Ppto año completo
        if not df_ppto.empty:
            df_ppto_year = df_ppto[
                (df_ppto["year"] == 2026)
                & (df_ppto["linea"].str.contains(nombre, na=False, case=False))
            ]
            ppto_year = df_ppto_year["valor_ppto"].sum() if not df_ppto_year.empty else 0
        else:
            ppto_year = 0

        cierre_proy = real_ytd + fcst_resto
        gap_vs_ppto = cierre_proy - ppto_year if ppto_year else None

        bridge_rows.append({
            "Línea": nombre,
            "Real YTD": real_ytd,
            "Fcst restante": fcst_resto,
            "Cierre proyectado": cierre_proy,
            "Ppto año completo": ppto_year,
            "Gap vs Ppto": gap_vs_ppto,
        })

    df_bridge = pd.DataFrame(bridge_rows)
    if not df_bridge.empty:
        df_show = pd.DataFrame({
            "Línea": df_bridge["Línea"],
            "Real YTD": df_bridge["Real YTD"].apply(lambda v: f"${v:,.0f} M"),
            "+ Fcst restante": df_bridge["Fcst restante"].apply(lambda v: f"${v:,.0f} M"),
            "= Cierre proy.": df_bridge["Cierre proyectado"].apply(lambda v: f"${v:,.0f} M"),
            "Ppto año": df_bridge["Ppto año completo"].apply(lambda v: f"${v:,.0f} M"),
            "Gap vs Ppto": df_bridge["Gap vs Ppto"].apply(
                lambda v: f"${v:+,.0f} M" if pd.notna(v) else "—"),
        })
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=240)

    st.divider()

    # ─── GRÁFICO MENSUAL Real + Fcst vs Ppto ─────────────────────────────
    st.markdown("### 📈 Evolución mensual — Real + Fcst vs Presupuesto")

    linea_sel = st.selectbox(
        "Línea a graficar",
        LINEAS_CLAVE,
        index=0,
        key="fin_fcst_linea",
    )

    fig = go.Figure()
    # Real
    df_real_line = df_pyl[
        (df_pyl["year"] == 2026)
        & (df_pyl["linea"].str.contains(linea_sel, na=False, case=False))
        & (df_pyl["month"] <= ultimo_mes_real)
    ].sort_values("fecha")
    if not df_real_line.empty:
        fig.add_trace(go.Bar(
            x=df_real_line["fecha"], y=df_real_line["valor"],
            name="Real", marker_color="#1F4E79",
            hovertemplate="%{x|%b}<br>Real: $%{y:,.0f} M<extra></extra>",
        ))

    # Fcst
    if not df_fcst.empty:
        df_fcst_line = df_fcst[
            (df_fcst["year"] == 2026)
            & (df_fcst["month"] > ultimo_mes_real)
            & (df_fcst["linea"].str.contains(linea_sel, na=False, case=False))
        ].sort_values("fecha")
        if not df_fcst_line.empty:
            fig.add_trace(go.Bar(
                x=df_fcst_line["fecha"], y=df_fcst_line["valor_fcst"],
                name="Forecast", marker_color="#7C3AED", opacity=0.7,
                hovertemplate="%{x|%b}<br>Fcst: $%{y:,.0f} M<extra></extra>",
            ))

    # Ppto (línea)
    if not df_ppto.empty:
        df_ppto_line = df_ppto[
            (df_ppto["year"] == 2026)
            & (df_ppto["linea"].str.contains(linea_sel, na=False, case=False))
        ].sort_values("fecha")
        if not df_ppto_line.empty:
            fig.add_trace(go.Scatter(
                x=df_ppto_line["fecha"], y=df_ppto_line["valor_ppto"],
                name="Ppto", mode="lines+markers",
                line=dict(color="#DC2626", width=2.5, dash="dash"),
                marker=dict(size=8),
                hovertemplate="%{x|%b}<br>Ppto: $%{y:,.0f}<extra></extra>",
            ))

    fig.update_layout(
        height=380,
        title=f"{linea_sel} — 2026 mes a mes",
        xaxis=dict(title="Mes"),
        yaxis=dict(title="M CLP", tickformat=",.0f"),
        barmode="group",
        hovermode="x unified",
        margin=dict(t=50, b=40, l=70, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.05, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ─── METAS 2026 vs CIERRE ────────────────────────────────────────────
    if not df_metas.empty:
        st.markdown("### 🎯 Cumplimiento vs Metas 2026")

        kpis_meta = df_metas["kpi"].unique()
        rows_meta = []
        for kpi in kpis_meta:
            df_k = df_metas[df_metas["kpi"] == kpi]
            meta_total = df_k[df_k["tipo"] == "Meta"]["valor"].sum()
            real_total = df_k[
                (df_k["tipo"] == "Resultado") & (df_k["month"] <= ultimo_mes_real)
            ]["valor"].sum()
            real_2025 = df_k[df_k["tipo"] == "Resultado 2025"]["valor"].sum() if "Resultado 2025" in df_k["tipo"].values else 0
            rows_meta.append({
                "KPI": kpi,
                "Meta año": meta_total,
                "Real YTD": real_total,
                "% cumplido YTD": (real_total / meta_total * 100) if meta_total else None,
                "Real YTD 2025": real_2025,
            })
        df_meta_show = pd.DataFrame(rows_meta)
        df_meta_disp = pd.DataFrame({
            "KPI": df_meta_show["KPI"],
            "Meta año": df_meta_show["Meta año"].apply(lambda v: f"${v/1e6:,.1f} MM"),
            "Real YTD": df_meta_show["Real YTD"].apply(lambda v: f"${v/1e6:,.1f} MM"),
            "% cumplido": df_meta_show["% cumplido YTD"].apply(
                lambda v: f"{v:.1f}%" if pd.notna(v) else "—"),
            "Real YTD 2025": df_meta_show["Real YTD 2025"].apply(
                lambda v: f"${v/1e6:,.1f} MM" if v else "—"),
        })
        st.dataframe(df_meta_disp, use_container_width=True, hide_index=True, height=260)
