"""
Vista Foto del Mes — App Finanzas.

Pantalla ejecutiva con:
  - 6 KPIs grandes (Venta · Mg Contribución · GAV · EBIT · EBITDA · Resultado Neto)
  - Cada KPI: Real | Meta | Var% vs Meta | Var% vs YoY | Tendencia 12m
  - Análisis vertical (cada línea como % de Venta)
  - Análisis horizontal (variación mes-a-mes y año-a-año)
  - Tabla resumen YTD vs Ppto vs YoY (de la hoja Resumen YTD)

Fuente: pyl_mensual.parquet + metas_2026.parquet + resumen_ytd.parquet +
         dashboard_data.parquet
"""
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views._fin_data import (
    pyl, metas_2026, resumen_ytd, dashboard_data, info_actualizacion,
    fmt_clp, fmt_pct, fmt_pct_simple,
)


MESES_ES = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}


def _kpi_card(label: str, valor: str, meta: str, var_pct, color_var: str = "#1F4E79") -> str:
    """Card HTML estilo finanzas."""
    var_class = "var-neu"
    if var_pct is not None and not pd.isna(var_pct):
        var_class = "var-pos" if var_pct >= 0 else "var-neg"

    var_str = ""
    if var_pct is not None and not pd.isna(var_pct):
        var_str = f'<span class="{var_class}">{var_pct:+.1f}% vs Meta</span>'

    return f"""<div class="fin-kpi">
        <div class="label">{label}</div>
        <div class="valor" style="color:{color_var};">{valor}</div>
        <div class="meta">Meta: {meta}<br>{var_str}</div>
    </div>"""


def _ultimo_mes_con_datos(df: pd.DataFrame) -> tuple[int, int]:
    """Devuelve (year, month) del último mes con datos reales en P&L."""
    if df.empty:
        return datetime.now().year, datetime.now().month
    ultimo = df.sort_values(["year", "month"]).iloc[-1]
    return int(ultimo["year"]), int(ultimo["month"])


def render():
    with st.sidebar:
        st.markdown("### 📸 **Foto del mes**")
        st.caption("Cierre + análisis V/H")
        st.divider()

    st.title("📸 Foto del mes")
    st.caption("Cierre mensual + análisis vertical y horizontal · base: P&L histórico")

    df_pyl = pyl()
    df_metas = metas_2026()
    df_resumen = resumen_ytd()
    df_dash = dashboard_data()

    if df_pyl.empty:
        st.warning(
            "⏳ Sin datos. Correr `python extract_finanzas_planificacion.py` "
            "(debería estar en data/finanzas/pyl_mensual.parquet)."
        )
        return

    # ─── SELECTOR DE MES ──────────────────────────────────────────────────
    df_pyl_2026 = df_pyl[df_pyl["year"] == 2026]
    if df_pyl_2026.empty:
        st.warning("Sin datos 2026 en la hoja P&L")
        return

    meses_disp = sorted(df_pyl_2026["month"].unique(), reverse=True)
    default_mes = meses_disp[0] if meses_disp else 1

    col_sel1, col_sel2 = st.columns([1, 3])
    with col_sel1:
        mes_sel = st.selectbox(
            "Mes",
            options=meses_disp,
            index=0,
            format_func=lambda m: f"{MESES_ES[m]} 2026",
            key="fin_foto_mes_sel",
        )
    with col_sel2:
        st.markdown("")  # spacer

    # ─── KPIs PRINCIPALES (Real | Meta | Var) ────────────────────────────
    # Tomamos de la hoja Dashboard Data que ya tiene los KPIs preparados
    # Cada concepto: "Venta Meta", "Venta Resultado", "Venta Var%", etc.
    st.markdown(f"### {MESES_ES[mes_sel]} 2026 · KPIs principales")

    def _get_dash_val(concepto_base: str, sufijo: str) -> float | None:
        """Lookup en dashboard_data por concepto + mes."""
        row = df_dash[
            (df_dash["concepto"] == f"{concepto_base} {sufijo}")
            & (df_dash["mes_num"] == mes_sel)
        ]
        return float(row["valor"].iloc[0]) if not row.empty else None

    kpis = [
        ("Venta", "Venta", "#1F4E79", False),
        ("Contribución", "Contrib.", "#16A34A", False),
        ("GAV", "GAV", "#7C3AED", True),    # GAV: var positiva es buena (gastaste menos)
        ("EBIT", "EBIT", "#0D9488", False),
    ]
    cols = st.columns(len(kpis))
    for col, (label, base, color, inverted) in zip(cols, kpis):
        meta = _get_dash_val(base, "Meta")
        real = _get_dash_val(base, "Resultado")
        var_pct = _get_dash_val(base, "Var%")

        if real is None:
            valor_str = "—"
            meta_str = fmt_clp(meta) if meta else "—"
            var_disp = None
        else:
            valor_str = fmt_clp(real)
            meta_str = fmt_clp(meta) if meta else "—"
            # var_pct viene como decimal en dashboard_data
            var_disp = var_pct * 100 if var_pct is not None else None
            if inverted and var_disp is not None:
                var_disp = -var_disp  # invertir para GAV
        col.markdown(_kpi_card(label, valor_str, meta_str, var_disp, color),
                     unsafe_allow_html=True)

    st.divider()

    # ─── ANÁLISIS VERTICAL: cada línea como % de Venta del mes ────────────
    st.markdown("### 📊 Análisis Vertical — % de Venta del mes")
    st.caption("Cada línea del P&L como porcentaje de los Ingresos por Ventas del mes")

    pyl_mes = df_pyl_2026[df_pyl_2026["month"] == mes_sel].copy()
    if pyl_mes.empty:
        st.info(f"Sin datos para {MESES_ES[mes_sel]} 2026")
    else:
        # Venta del mes (línea "Ingresos por Ventas" en sección)
        venta_row = pyl_mes[pyl_mes["linea"].str.contains("Ingresos por Ventas", na=False)]
        venta = float(venta_row["valor"].iloc[0]) if not venta_row.empty else None

        if venta and venta > 0:
            pyl_mes["pct_venta"] = pyl_mes["valor"] / venta
            # Mismo mes año anterior para comparar V%
            pyl_mes_ant = df_pyl[
                (df_pyl["year"] == 2025) & (df_pyl["month"] == mes_sel)
            ].copy()
            if not pyl_mes_ant.empty:
                venta_ant_row = pyl_mes_ant[
                    pyl_mes_ant["linea"].str.contains("Ingresos por Ventas", na=False)
                ]
                venta_ant = (float(venta_ant_row["valor"].iloc[0])
                              if not venta_ant_row.empty else None)
                if venta_ant and venta_ant > 0:
                    pyl_mes_ant["pct_venta_ant"] = pyl_mes_ant["valor"] / venta_ant
                else:
                    pyl_mes_ant["pct_venta_ant"] = None

                merged = pyl_mes.merge(
                    pyl_mes_ant[["linea", "pct_venta_ant", "valor"]],
                    on="linea", how="left", suffixes=("", "_ant"),
                )
                merged["delta_pp"] = merged["pct_venta"] - merged["pct_venta_ant"]
            else:
                merged = pyl_mes.copy()
                merged["pct_venta_ant"] = None
                merged["delta_pp"] = None
                merged["valor_ant"] = None

            # Filtrar líneas con monto >0.5% para no inundar
            merged = merged[merged["pct_venta"].abs() > 0.005].copy()
            merged = merged.sort_values("valor", ascending=False)

            df_show = pd.DataFrame({
                "Línea": merged["linea"].str[:50],
                "Sección": merged["seccion"].str[:25],
                f"Valor {MESES_ES[mes_sel]} 26": merged["valor"].apply(
                    lambda v: f"${v:,.0f} M"),
                "% Venta": merged["pct_venta"].apply(lambda v: f"{v*100:+.1f}%"),
                "% Venta año ant": merged["pct_venta_ant"].apply(
                    lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "—"),
                "Δ pp YoY": merged["delta_pp"].apply(
                    lambda v: f"{v*100:+.1f}pp" if pd.notna(v) else "—"),
            })
            st.dataframe(df_show, width='stretch', hide_index=True, height=420)
            st.caption(
                f"Venta {MESES_ES[mes_sel]} 2026: ${venta:,.0f} M · "
                f"Líneas con peso ≥ 0.5% mostradas. "
                "Δ pp = puntos porcentuales vs mismo mes año anterior."
            )

    st.divider()

    # ─── ANÁLISIS HORIZONTAL: tendencia 12m ──────────────────────────────
    st.markdown("### 📈 Análisis Horizontal — tendencia últimos 12 meses")
    st.caption("Evolución mensual de las líneas clave del P&L")

    # Líneas clave para tendencia
    LINEAS_CLAVE = [
        ("Ingresos por Ventas", "#1F4E79"),
        ("Margen Frontal", "#0EA5E9"),
        ("Margen Contribución", "#16A34A"),
        ("Resultado Operacional (EBIT)", "#7C3AED"),
        ("EBITDA", "#0D9488"),
    ]

    fig = go.Figure()
    for nombre_buscar, color in LINEAS_CLAVE:
        df_linea = df_pyl[df_pyl["linea"].str.contains(nombre_buscar, na=False, case=False)]
        if df_linea.empty:
            continue
        df_linea = df_linea.sort_values("fecha").tail(24)
        fig.add_trace(go.Scatter(
            x=df_linea["fecha"], y=df_linea["valor"],
            mode="lines+markers", name=nombre_buscar,
            line=dict(color=color, width=2.5),
            marker=dict(size=6),
            hovertemplate=f"<b>{nombre_buscar}</b><br>%{{x|%b %Y}}: $%{{y:,.0f}} M<extra></extra>",
        ))

    fig.update_layout(
        height=380,
        xaxis=dict(title="Mes"),
        yaxis=dict(title="M CLP", tickformat=",.0f"),
        hovermode="x unified",
        margin=dict(t=20, b=40, l=70, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.05, x=0),
    )
    st.plotly_chart(fig, width='stretch')

    st.divider()

    # ─── RESUMEN YTD ─────────────────────────────────────────────────────
    st.markdown("### 📋 Resumen YTD 2026 vs Ppto vs Año anterior")
    st.caption("Tomado directamente de la hoja Resumen YTD del archivo")

    if not df_resumen.empty:
        df_show = df_resumen.copy()
        # Filtrar solo conceptos con datos numéricos
        df_show = df_show.dropna(subset=["ytd_2026"])

        def _fmt(v):
            if v is None or pd.isna(v):
                return "—"
            return f"${v:,.0f} M"

        def _fmt_pct(v):
            if v is None or pd.isna(v):
                return "—"
            return f"{v * 100:+.1f}%"

        df_disp = pd.DataFrame({
            "Concepto": df_show["concepto"].str[:45],
            "YTD 2026": df_show["ytd_2026"].apply(_fmt),
            "YTD Ppto": df_show["ytd_ppto"].apply(_fmt),
            "YTD 2025": df_show["ytd_2025"].apply(_fmt),
            "Var % vs Ppto": df_show["var_pct_ppto"].apply(_fmt_pct),
            "Var % YoY": df_show["var_pct_yoy"].apply(_fmt_pct),
        })
        st.dataframe(df_disp, width='stretch', hide_index=True, height=400)
    else:
        st.info("Sin datos de Resumen YTD")
