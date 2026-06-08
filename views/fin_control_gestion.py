"""
Vista Control de Gestión Presupuestario — App Finanzas.

Lee data/finanzas/control_gestion.parquet (extraído del Sheet de Andrés
"P&L 2025-2026" en Drive).

Permite explorar PPTO vs FCST en formato pivot dinámico con filtros por:
  - Año, Mes
  - Línea de Negocio (UNIONX / GRUPO ETER)
  - Canal (20 canales)
  - Área Empresa (12 áreas)
  - Centro de Costos (33 CCs)
  - Tipo de Costo (VARIABLE / FIJO)

Compara PPTO vs FCST con gap analysis. Cuando se sume el REAL del archivo
Planificación Financiera, se podrá hacer Real vs Ppto vs Fcst en 3 columnas.
"""
import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


PROJECT_ROOT = Path(__file__).parent.parent
PARQUET = PROJECT_ROOT / "data" / "finanzas" / "control_gestion.parquet"
RESUMEN = PROJECT_ROOT / "data" / "finanzas" / "control_gestion_resumen.json"


@st.cache_data(ttl=300)
def _cargar() -> tuple[pd.DataFrame, dict]:
    df = pd.DataFrame()
    res = {}
    if PARQUET.exists():
        df = pd.read_parquet(PARQUET)
        df["fecha"] = pd.to_datetime(df["fecha"])
    if RESUMEN.exists():
        try:
            res = json.load(open(RESUMEN, encoding="utf-8"))
        except Exception:
            pass
    return df, res


def _fmt_clp(v):
    if v is None or pd.isna(v) or v == 0:
        return "—"
    abs_v = abs(v)
    if abs_v >= 1_000_000:
        return f"${v/1e6:+,.1f}MM"
    if abs_v >= 1_000:
        return f"${v/1e3:+,.0f}M"
    return f"${v:+,.0f}M"


def _fmt_pct(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%"


def render():
    with st.sidebar:
        st.markdown("### 💵 **Control Gestión**")
        st.caption("PPTO vs FCST · Drive Sheet")
        st.divider()

    st.title("💵 Control de Gestión Presupuestario")
    st.caption(
        "Fuente: Sheet **P&L 2025-2026** (Drive) · "
        "PPTO y FCST por línea de negocio, canal, área y centro de costos"
    )

    df, res = _cargar()

    if df.empty:
        st.warning(
            "⏳ Sin datos. Correr `python extract_finanzas_control_gestion.py` "
            "(o esperar el cron `sync_finanzas.yml` cada 6h)."
        )
        return

    st.caption(
        f"🕒 Generado: {res.get('generado_en','')[:19]} · "
        f"{res.get('filas_procesadas',0):,} filas · "
        f"{len(res.get('canales',[]))} canales · "
        f"{res.get('centros_costo_count',0)} CCs"
    )

    # ─── FILTROS GLOBALES ────────────────────────────────────────────────
    st.divider()
    st.markdown("### 🔧 Filtros")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        years = sorted(df["year"].dropna().unique().astype(int).tolist())
        year_sel = st.multiselect("Año", years, default=years)
    with col2:
        meses = sorted(df["month"].dropna().unique().astype(int).tolist())
        meses_label = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
                       7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}
        mes_sel = st.multiselect(
            "Mes", meses, default=meses,
            format_func=lambda m: meses_label.get(m, str(m)),
        )
    with col3:
        lns = sorted(df["linea_negocio"].dropna().unique().tolist())
        ln_sel = st.multiselect("Línea Negocio", lns, default=lns)
    with col4:
        escenarios = sorted(df["escenario"].dropna().unique().tolist())
        esc_sel = st.multiselect("Escenario", escenarios, default=escenarios)

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        canales = sorted(df["canal"].dropna().unique().tolist())
        canal_sel = st.multiselect("Canal", canales, default=canales)
    with col6:
        areas = sorted(df["area"].dropna().unique().tolist())
        area_sel = st.multiselect("Área", areas, default=areas)
    with col7:
        tipos_costo = sorted(df["tipo_costo"].dropna().unique().tolist())
        tipo_sel = st.multiselect("Tipo Costo", tipos_costo, default=tipos_costo)
    with col8:
        kpis = sorted(df["kpi"].dropna().unique().tolist())
        kpi_sel = st.multiselect("KPI", kpis, default=kpis)

    # Aplicar filtros
    df_f = df[
        df["year"].isin(year_sel)
        & df["month"].isin(mes_sel)
        & df["linea_negocio"].isin(ln_sel)
        & df["escenario"].isin(esc_sel)
        & df["canal"].isin(canal_sel)
        & df["area"].isin(area_sel)
        & df["tipo_costo"].isin(tipo_sel)
        & df["kpi"].isin(kpi_sel)
    ].copy()

    st.caption(f"📊 {len(df_f):,} filas tras filtros (de {len(df):,} totales)")

    if df_f.empty:
        st.info("Sin datos con los filtros actuales")
        return

    st.divider()

    # ─── KPIs RESUMEN: PPTO vs FCST ───────────────────────────────────────
    st.markdown("### 💰 PPTO vs FCST — totales del periodo filtrado")

    # Pivot: KPI x Escenario
    kpi_pivot = df_f.pivot_table(
        index="kpi", columns="escenario",
        values="valor", aggfunc="sum", fill_value=0,
    )

    cols_kpi = st.columns(max(1, len(kpi_pivot.index)))
    for i, kpi_name in enumerate(kpi_pivot.index):
        with cols_kpi[i]:
            ppto = kpi_pivot.at[kpi_name, "PPTO"] if "PPTO" in kpi_pivot.columns else 0
            fcst = kpi_pivot.at[kpi_name, "FCST"] if "FCST" in kpi_pivot.columns else 0
            gap = fcst - ppto
            gap_pct = (gap / abs(ppto) * 100) if ppto else None

            # Para INGRESOS/CONTRIB: positivo es bueno · para COSTO/GASTO: negativo es bueno
            es_costo = kpi_name in ("COSTO", "GASTO")
            color_gap = "#94A3B8"
            if gap_pct is not None:
                bueno = (gap < 0) if es_costo else (gap > 0)
                color_gap = "#16A34A" if bueno else "#DC2626"

            st.markdown(
                f"""<div class="fin-kpi" style="border-left:4px solid {color_gap};">
                <div class="label">{kpi_name}</div>
                <div class="valor">{_fmt_clp(fcst)}</div>
                <div class="meta">
                    PPTO: {_fmt_clp(ppto)}<br>
                    GAP: <span style="color:{color_gap};font-weight:600;">
                    {_fmt_clp(gap)} ({_fmt_pct(gap_pct)})</span>
                </div></div>""",
                unsafe_allow_html=True,
            )

    st.divider()

    # ─── PIVOT DINÁMICO ──────────────────────────────────────────────────
    st.markdown("### 📊 Pivot Dinámico")

    pcol1, pcol2, pcol3 = st.columns(3)
    DIM_OPTIONS = ["centro_costo", "area", "sub_area", "cuenta_analitica",
                   "linea_negocio", "canal", "tipo_costo", "kpi"]
    with pcol1:
        rows_dim = st.selectbox("Filas (dimensión)", DIM_OPTIONS,
                                  index=0, key="cg_pivot_rows")
    with pcol2:
        cols_dim_options = ["mes_text", "year", "escenario", "kpi", "linea_negocio"]
        cols_dim = st.selectbox("Columnas", cols_dim_options, index=0, key="cg_pivot_cols")
    with pcol3:
        modo = st.radio("Vista", ["Solo PPTO", "Solo FCST", "FCST - PPTO (Gap)",
                                   "PPTO + FCST (lado a lado)"],
                         horizontal=False, key="cg_pivot_modo")

    pivot = None
    if modo == "Solo PPTO":
        pivot = (df_f[df_f["escenario"] == "PPTO"]
                 .pivot_table(index=rows_dim, columns=cols_dim,
                                values="valor", aggfunc="sum", fill_value=0))
    elif modo == "Solo FCST":
        pivot = (df_f[df_f["escenario"] == "FCST"]
                 .pivot_table(index=rows_dim, columns=cols_dim,
                                values="valor", aggfunc="sum", fill_value=0))
    elif modo == "FCST - PPTO (Gap)":
        pp = (df_f[df_f["escenario"] == "PPTO"]
              .pivot_table(index=rows_dim, columns=cols_dim,
                            values="valor", aggfunc="sum", fill_value=0))
        fc = (df_f[df_f["escenario"] == "FCST"]
              .pivot_table(index=rows_dim, columns=cols_dim,
                            values="valor", aggfunc="sum", fill_value=0))
        pivot = fc.subtract(pp, fill_value=0)
    else:  # lado a lado
        pivot = (df_f.pivot_table(index=rows_dim,
                                    columns=[cols_dim, "escenario"],
                                    values="valor", aggfunc="sum", fill_value=0))

    if pivot is not None and not pivot.empty:
        # Si las columnas son meses, ordenarlas
        if cols_dim == "mes_text":
            mes_order = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                         "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE",
                         "DICIEMBRE"]
            existing = [m for m in mes_order if m in pivot.columns]
            if existing:
                pivot = pivot[existing]

        # Agregar columna Total
        try:
            pivot["TOTAL"] = pivot.sum(axis=1)
        except Exception:
            pass

        # Formato CLP en miles
        pivot_disp = pivot.copy()
        for c in pivot_disp.columns:
            pivot_disp[c] = pivot_disp[c].apply(_fmt_clp)

        st.dataframe(pivot_disp, width='stretch', height=520)

        # Excel descarga
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            pivot.to_excel(w, sheet_name="Control Gestion")
        st.download_button(
            "📥 Descargar pivot en Excel",
            data=buf.getvalue(),
            file_name=f"control_gestion_pivot_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.divider()

    # ─── GRÁFICO MENSUAL: PPTO vs FCST por KPI ──────────────────────────
    st.markdown("### 📈 PPTO vs FCST mensual por KPI")

    df_mens = df_f.groupby(["fecha", "escenario", "kpi"], as_index=False)["valor"].sum()

    kpi_grafico = st.selectbox(
        "KPI a graficar", sorted(df_f["kpi"].unique()), index=0,
        key="cg_kpi_graf",
    )
    df_g = df_mens[df_mens["kpi"] == kpi_grafico].copy()

    if not df_g.empty:
        fig = go.Figure()
        for esc, color in [("PPTO", "#94A3B8"), ("FCST", "#1F4E79")]:
            df_e = df_g[df_g["escenario"] == esc].sort_values("fecha")
            if df_e.empty:
                continue
            fig.add_trace(go.Scatter(
                x=df_e["fecha"], y=df_e["valor"],
                mode="lines+markers", name=esc,
                line=dict(color=color, width=3 if esc == "FCST" else 2,
                           dash="dash" if esc == "PPTO" else "solid"),
                marker=dict(size=8),
                hovertemplate=f"<b>{esc}</b><br>%{{x|%b %Y}}: $%{{y:,.0f}}M<extra></extra>",
            ))
        fig.update_layout(
            height=360,
            title=f"{kpi_grafico} — PPTO vs FCST",
            xaxis=dict(title="Mes"),
            yaxis=dict(title="M CLP", tickformat=",.0f"),
            hovermode="x unified",
            margin=dict(t=50, b=40, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.05, x=0),
        )
        st.plotly_chart(fig, width='stretch')

    st.divider()

    # ─── GAP ANALYSIS: TOP DESVIACIONES ─────────────────────────────────
    st.markdown("### 🎯 Top desviaciones FCST vs PPTO por Centro de Costo")

    # Calcular gap por CC
    df_gap = df_f.pivot_table(
        index=["centro_costo", "area"], columns="escenario",
        values="valor", aggfunc="sum", fill_value=0,
    )
    if "PPTO" in df_gap.columns and "FCST" in df_gap.columns:
        df_gap["gap"] = df_gap["FCST"] - df_gap["PPTO"]
        df_gap["gap_pct"] = df_gap.apply(
            lambda r: (r["gap"] / abs(r["PPTO"]) * 100) if r["PPTO"] else None,
            axis=1,
        )
        df_gap_sorted = df_gap.sort_values("gap", key=abs, ascending=False).head(20).reset_index()

        df_show = pd.DataFrame({
            "Centro Costo": df_gap_sorted["centro_costo"].str[:35],
            "Área": df_gap_sorted["area"].str[:25],
            "PPTO": df_gap_sorted["PPTO"].apply(_fmt_clp),
            "FCST": df_gap_sorted["FCST"].apply(_fmt_clp),
            "Gap": df_gap_sorted["gap"].apply(_fmt_clp),
            "Gap %": df_gap_sorted["gap_pct"].apply(_fmt_pct),
        })
        st.dataframe(df_show, width='stretch', hide_index=True, height=420)

    st.divider()

    # ─── INFO ──────────────────────────────────────────────────────────
    with st.expander("ℹ️ Sobre los datos"):
        st.markdown(f"""
        **Fuente:** [Sheet P&L 2025-2026 en Drive](https://docs.google.com/spreadsheets/d/1NfIL-k00pUbF5ogsVnadP2wMAVc7oUKkOA7UMLOT-j0/edit)

        **Refresco automático:** cada 6 horas vía cron `sync_finanzas.yml`.
        También se refresca cuando hacés push de cambios al extractor o al
        archivo Excel local.

        **Refresco manual:** correr en terminal:
        ```
        python extract_finanzas_control_gestion.py
        ```

        **Estructura del Sheet:**
        - 9 dimensiones: Año, Mes, Línea Negocio, Canal, Tipo Costo, Centro
          Costos, Área, Sub-Área, Cuenta Analítica
        - 8 escenarios×KPI: PPTO_VENTA · PPTO_COSTO · PPTO_GASTO · PPTO_CONTRIB ·
          FCST_VENTA · FCST_COSTO · FCST_GASTO · FCST_CONTRIB

        **Próximo paso:** sumar el **REAL** desde el archivo Planificación
        Financiera (cruzando por mes + área/CC) para tener vista 3 columnas
        Real vs PPTO vs FCST.
        """)
