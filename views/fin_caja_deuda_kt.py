"""
Vista Caja, Deuda & Capital de Trabajo — App Finanzas.

KPIs financieros: liquidez, capital de trabajo, deuda, ratios.

Fuente: kt.parquet + deuda.parquet + analisis_financiero.parquet + resumen_ytd.parquet
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views._fin_data import (
    kt, deuda, analisis_financiero, resumen_ytd,
)


MESES_ES = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}


def render():
    with st.sidebar:
        st.markdown("### 💧 **Caja & Balance**")
        st.caption("Capital de trabajo + deuda")
        st.divider()

    st.title("💧 Caja, Deuda & Capital de Trabajo")
    st.caption("Capital de trabajo · meses inventario/CxC/CxP · deuda · ratios financieros")

    df_kt = kt()
    df_deuda = deuda()
    df_af = analisis_financiero()
    df_ytd = resumen_ytd()

    if df_kt.empty and df_deuda.empty:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    # ─── KPIs PRINCIPALES (último mes con datos) ─────────────────────────
    st.markdown("### 🎯 Estado actual")
    cols = st.columns(4)

    # Ratios desde Resumen YTD
    def _get_ytd(concepto: str) -> float | None:
        if df_ytd.empty:
            return None
        row = df_ytd[df_ytd["concepto"].str.contains(concepto, na=False, case=False)]
        if row.empty:
            return None
        return row["ytd_2026"].iloc[0]

    razon_corriente = _get_ytd("Ratio Liquidez - Raz")
    quick_ratio = _get_ytd("Quick Ratio")
    deuda_ebitda = _get_ytd("Deuda Financiera Ebit")
    cobertura = _get_ytd("Cobertura Gastos Fin")

    def _kpi_color(v, umbral_bueno, umbral_malo, invertido=False):
        if v is None or pd.isna(v):
            return "#94A3B8"
        if invertido:
            if v <= umbral_bueno:
                return "#16A34A"
            if v <= umbral_malo:
                return "#F59E0B"
            return "#DC2626"
        if v >= umbral_bueno:
            return "#16A34A"
        if v >= umbral_malo:
            return "#F59E0B"
        return "#DC2626"

    def _kpi_html(label, valor_str, meta_str, color):
        return f"""<div class="fin-kpi">
            <div class="label">{label}</div>
            <div class="valor" style="color:{color};">{valor_str}</div>
            <div class="meta">{meta_str}</div>
        </div>"""

    cols[0].markdown(_kpi_html(
        "Razón Corriente",
        f"{razon_corriente:.2f}" if razon_corriente else "—",
        "Meta ≥ 1.2 · saludable ≥ 2",
        _kpi_color(razon_corriente, 2.0, 1.2),
    ), unsafe_allow_html=True)
    cols[1].markdown(_kpi_html(
        "Quick Ratio",
        f"{quick_ratio:.2f}" if quick_ratio else "—",
        "Meta ≥ 1 · descuenta inventario",
        _kpi_color(quick_ratio, 1.0, 0.7),
    ), unsafe_allow_html=True)
    cols[2].markdown(_kpi_html(
        "Deuda / EBITDA",
        f"{deuda_ebitda:.1f}x" if deuda_ebitda else "—",
        "Meta ≤ 3.0x (Plan UnionX)",
        _kpi_color(deuda_ebitda, 3.0, 5.0, invertido=True),
    ), unsafe_allow_html=True)
    cols[3].markdown(_kpi_html(
        "Cobertura Gastos Fin.",
        f"{cobertura:.2f}x" if cobertura else "—",
        "Meta ≥ 3x (EBITDA / intereses)",
        _kpi_color(cobertura, 3.0, 1.5),
    ), unsafe_allow_html=True)

    st.divider()

    # ─── KT MENSUAL: CCC y componentes ───────────────────────────────────
    st.markdown("### 🔄 Capital de Trabajo — evolución mensual")

    if not df_kt.empty:
        # Líneas clave de KT
        lineas_kt = {
            "Existencias": "#1F4E79",
            "Cuentas por Cobrar Comerc": "#16A34A",
            "Cuentas por Pagar Comerc": "#DC2626",
            "Capital de trabajo neto": "#7C3AED",
        }
        fig = go.Figure()
        for nombre, color in lineas_kt.items():
            df_l = df_kt[
                df_kt["linea"].str.contains(nombre, na=False, case=False)
            ].copy().sort_values("fecha").tail(24)
            if df_l.empty:
                continue
            fig.add_trace(go.Scatter(
                x=df_l["fecha"], y=df_l["valor"],
                mode="lines+markers", name=nombre[:35],
                line=dict(color=color, width=2.5),
                marker=dict(size=6),
                hovertemplate=f"<b>{nombre}</b><br>%{{x|%b %Y}}: $%{{y:,.0f}} M<extra></extra>",
            ))
        fig.update_layout(
            height=350,
            xaxis=dict(title="Mes"),
            yaxis=dict(title="M CLP", tickformat=",.0f"),
            hovermode="x unified",
            margin=dict(t=20, b=40, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.05, x=0),
        )
        st.plotly_chart(fig, width='stretch')

        # Meses inventario / CxC / CxP (CCC)
        st.markdown("##### Meses de inventario · CxC · CxP")
        meses_kt = {}
        for label, search in [
            ("Meses de existencias móvil", "Meses de existencias m"),
            ("Meses de CxC", "Meses de CxC"),
            ("Meses de CxP", "Meses de CxP"),
        ]:
            df_l = df_kt[df_kt["linea"].str.contains(search, na=False)].copy()
            if not df_l.empty:
                ultimo = df_l.sort_values("fecha").iloc[-1]
                meses_kt[label] = ultimo["valor"]

        if meses_kt:
            cols2 = st.columns(len(meses_kt) + 1)
            for i, (label, val) in enumerate(meses_kt.items()):
                cols2[i].metric(label, f"{val:.1f} meses")
            # CCC = DIO + DSO - DPO (en meses)
            dio = meses_kt.get("Meses de existencias móvil", 0)
            dso = meses_kt.get("Meses de CxC", 0)
            dpo = meses_kt.get("Meses de CxP", 0)
            ccc = dio + dso - dpo
            cols2[-1].metric("CCC (calculado)", f"{ccc:.1f} meses",
                              f"≈ {ccc*30:.0f} días",
                              delta_color="inverse")

    st.divider()

    # ─── DEUDA FINANCIERA ────────────────────────────────────────────────
    st.markdown("### 🏦 Deuda Financiera — evolución")

    if not df_deuda.empty:
        # Saldo final por mes
        df_saldo = df_deuda[
            df_deuda["linea"].str.contains("Saldo final|saldo final", na=False, regex=True)
        ].copy().sort_values("fecha").tail(36)
        if not df_saldo.empty:
            # Agregar por fecha (puede haber múltiples filas si hay sub-secciones)
            df_agg = df_saldo.groupby("fecha", as_index=False)["valor"].sum()
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=df_agg["fecha"], y=df_agg["valor"],
                marker_color="#7C3AED",
                hovertemplate="%{x|%b %Y}<br>Saldo: $%{y:,.0f} M<extra></extra>",
            ))
            fig.update_layout(
                height=300,
                xaxis=dict(title="Mes"),
                yaxis=dict(title="Saldo deuda (M CLP)", tickformat=",.0f"),
                margin=dict(t=20, b=40, l=70, r=20),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                title="Saldo final deuda financiera",
            )
            st.plotly_chart(fig, width='stretch')

        # Gasto en intereses
        df_int = df_deuda[
            df_deuda["linea"].str.contains("Gasto en intereses", na=False)
        ].copy().sort_values("fecha").tail(12)
        if not df_int.empty:
            st.markdown("##### Gasto en intereses últimos 12 meses")
            df_int_show = pd.DataFrame({
                "Mes": df_int["fecha"].dt.strftime("%b %Y"),
                "Intereses": df_int["valor"].apply(lambda v: f"${v:,.0f} M"),
            })
            st.dataframe(df_int_show, width='stretch', hide_index=True, height=240)

    st.divider()

    # ─── ANÁLISIS FINANCIERO YTD ────────────────────────────────────────
    if not df_af.empty:
        st.markdown("### 📋 Análisis Financiero YTD (de la hoja del archivo)")
        df_show = df_af.copy().dropna(subset=["ytd_2026"])
        df_disp = pd.DataFrame({
            "Sección": df_show["seccion"].str[:30],
            "Concepto": df_show["concepto"].str[:45],
            "YTD 2025": df_show["ytd_2025"].apply(
                lambda v: f"${v:,.0f} M" if pd.notna(v) else "—"),
            "YTD 2026": df_show["ytd_2026"].apply(
                lambda v: f"${v:,.0f} M" if pd.notna(v) else "—"),
            "Nota": df_show["nota"].fillna("").str[:30],
        })
        st.dataframe(df_disp, width='stretch', hide_index=True, height=400)
