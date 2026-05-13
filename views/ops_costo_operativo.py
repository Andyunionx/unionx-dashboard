"""
Vista Costo Operativo — App Operaciones.

Lee data/operaciones/costo_operativo.parquet extraído del Sheet
"OPERACIONES 2025-2026" en Drive (mantenido por Andrés).

Muestra:
  - KPIs: gasto operativo total, costo/pedido, costo/venta
  - Distribución por área y por canal
  - Pivot dinámico CC × mes con PPTO vs FCST
  - Tendencia mensual
  - Top desviaciones FCST vs PPTO
"""
import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


PROJECT_ROOT = Path(__file__).parent.parent
PARQUET = PROJECT_ROOT / "data" / "operaciones" / "costo_operativo.parquet"
RESUMEN = PROJECT_ROOT / "data" / "operaciones" / "costo_operativo_resumen.json"
WMS_SNAP = PROJECT_ROOT / "data" / "kpis_wms" / "snapshot.json"


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


@st.cache_data(ttl=300)
def _cargar_pedidos_mes() -> dict:
    """Lee snapshot WMS para obtener # pedidos por mes."""
    if not WMS_SNAP.exists():
        return {}
    try:
        snap = json.load(open(WMS_SNAP, encoding="utf-8"))
        p = snap.get("productividad_mes_6m", {})
        items = p.get("items", []) if isinstance(p, dict) else []
        return {
            it.get("periodo", ""): it.get("n_pedidos", 0)
            for it in items if it.get("n_pedidos", 0) > 0
        }
    except Exception:
        return {}


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


def _kpi_html(label, valor, meta, color="#1F4E79"):
    return f"""<div style="background:white;border-radius:12px;padding:16px 18px;
    border:1px solid #E2E8F0;border-left:4px solid {color};
    box-shadow:0 1px 3px rgba(0,0,0,0.05);height:100%;">
    <div style="font-size:0.72rem;color:#64748B;text-transform:uppercase;
    letter-spacing:0.5px;font-weight:600;margin-bottom:6px;">{label}</div>
    <div style="font-size:1.5rem;font-weight:700;color:#1E293B;line-height:1.1;">{valor}</div>
    <div style="font-size:0.72rem;color:#64748B;margin-top:8px;padding-top:8px;
    border-top:1px solid #F1F5F9;">{meta}</div></div>"""


def render():
    with st.sidebar:
        st.markdown("### 💰 **Costo Operativo**")
        st.caption("PPTO vs FCST · Drive Sheet")
        st.divider()

    st.title("💰 Costo Operativo Total")
    st.caption(
        "Fuente: Sheet **OPERACIONES 2025-2026** (Drive Andrés) · "
        "Plan Estratégico: costo/pedido ↓ 10-15% YoY · costo logístico/venta 8-12%"
    )

    df, res = _cargar()
    if df.empty:
        st.warning(
            "⏳ Sin datos. Correr `python extract_ops_costo_operativo.py` "
            "(o esperar al cron de sync_kpis_wms.yml)."
        )
        return

    st.caption(
        f"🕒 Generado: {res.get('generado_en','')[:19]} · "
        f"{res.get('filas_procesadas',0):,} filas · "
        f"{len(res.get('areas',[]))} áreas · "
        f"{res.get('centros_costo_count',0)} CCs"
    )

    # ─── FILTROS ────────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 🔧 Filtros")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        years = sorted(df["year"].dropna().unique().astype(int).tolist())
        year_sel = st.multiselect("Año", years,
                                    default=[max(years)] if years else [])
    with col2:
        meses = sorted(df["month"].dropna().unique().astype(int).tolist())
        meses_label = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
                       7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}
        mes_sel = st.multiselect(
            "Mes", meses, default=meses,
            format_func=lambda m: meses_label.get(m, str(m)),
        )
    with col3:
        areas = sorted(df["area"].dropna().unique().tolist())
        area_sel = st.multiselect("Área", areas, default=areas)
    with col4:
        canales = sorted(df["canal"].dropna().unique().tolist())
        canal_sel = st.multiselect("Canal", canales, default=canales)

    df_f = df[
        df["year"].isin(year_sel)
        & df["month"].isin(mes_sel)
        & df["area"].isin(area_sel)
        & df["canal"].isin(canal_sel)
    ].copy()

    if df_f.empty:
        st.info("Sin datos con los filtros actuales")
        return

    st.caption(f"📊 {len(df_f):,} filas tras filtros")
    st.divider()

    # ─── KPIs PRINCIPALES ────────────────────────────────────────────────
    st.markdown("### 💰 KPIs Costo Operativo")

    df_fcst_gasto = df_f[(df_f["escenario"] == "FCST") & (df_f["kpi"] == "GASTO")]
    df_ppto_gasto = df_f[(df_f["escenario"] == "PPTO") & (df_f["kpi"] == "GASTO")]
    df_fcst_venta = df_f[(df_f["escenario"] == "FCST") & (df_f["kpi"] == "VENTA")]
    df_fcst_contrib = df_f[(df_f["escenario"] == "FCST") & (df_f["kpi"] == "CONTRIB")]

    gasto_fcst = df_fcst_gasto["valor"].sum()
    gasto_ppto = df_ppto_gasto["valor"].sum()
    venta_fcst = df_fcst_venta["valor"].sum()
    contrib_fcst = df_fcst_contrib["valor"].sum()

    gap_gasto = gasto_fcst - gasto_ppto
    gap_gasto_pct = (gap_gasto / abs(gasto_ppto) * 100) if gasto_ppto else None
    costo_venta_pct = (abs(gasto_fcst) / abs(venta_fcst) * 100) if venta_fcst else None

    pedidos_dict = _cargar_pedidos_mes()
    total_ped = sum(pedidos_dict.values()) if pedidos_dict else 0
    costo_pedido = (abs(gasto_fcst) * 1_000_000 / total_ped) if total_ped else None

    cols = st.columns(4)
    cols[0].markdown(_kpi_html(
        "FCST Gasto Operativo",
        _fmt_clp(gasto_fcst),
        f"PPTO: {_fmt_clp(gasto_ppto)}<br>Gap: {_fmt_clp(gap_gasto)} ({_fmt_pct(gap_gasto_pct)})",
        "#DC2626",
    ), unsafe_allow_html=True)
    cols[1].markdown(_kpi_html(
        "FCST Venta",
        _fmt_clp(venta_fcst),
        f"Costo / Venta: <b>{f'{costo_venta_pct:.1f}%' if costo_venta_pct else '—'}</b> "
        f"(meta 8-12%)",
        "#16A34A",
    ), unsafe_allow_html=True)
    cols[2].markdown(_kpi_html(
        "FCST Contribución",
        _fmt_clp(contrib_fcst),
        f"Margen / Venta: <b>"
        f"{f'{contrib_fcst/venta_fcst*100:.1f}%' if venta_fcst else '—'}</b>",
        "#7C3AED",
    ), unsafe_allow_html=True)
    cols[3].markdown(_kpi_html(
        "Costo / Pedido",
        f"${costo_pedido:,.0f}" if costo_pedido else "—",
        f"FCST gasto / {total_ped:,.0f} pedidos<br>(snapshot WMS)",
        "#EA580C",
    ), unsafe_allow_html=True)

    st.divider()

    # ─── DISTRIBUCIÓN POR ÁREA ──────────────────────────────────────────
    st.markdown("### 📊 Distribución del gasto operativo por Área")

    by_area = (df_fcst_gasto.groupby("area")["valor"].sum().abs()
                              .sort_values(ascending=False))
    if not by_area.empty:
        fig = go.Figure(go.Bar(
            x=by_area.index, y=by_area.values,
            marker_color="#1F4E79",
            text=[_fmt_clp(-v) for v in by_area.values],
            textposition="outside",
            hovertemplate="%{x}<br>Gasto FCST: $%{y:,.0f}M<extra></extra>",
        ))
        fig.update_layout(
            height=350,
            xaxis=dict(title="Área"),
            yaxis=dict(title="Gasto FCST (M CLP, valor abs)", tickformat=",.0f"),
            margin=dict(t=20, b=40, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ─── PIVOT CC × MES ─────────────────────────────────────────────────
    st.markdown("### 📋 Centros de Costo × Mes — FCST Gasto")

    pivot = df_fcst_gasto.pivot_table(
        index="centro_costo", columns="mes_text",
        values="valor", aggfunc="sum", fill_value=0,
    )
    if not pivot.empty:
        mes_order = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                     "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE",
                     "DICIEMBRE"]
        existing = [m for m in mes_order if m in pivot.columns]
        if existing:
            pivot = pivot[existing]
        pivot["TOTAL"] = pivot.sum(axis=1)
        pivot = pivot.sort_values("TOTAL")

        pivot_disp = pivot.copy()
        for c in pivot_disp.columns:
            pivot_disp[c] = pivot_disp[c].apply(_fmt_clp)
        st.dataframe(pivot_disp, use_container_width=True, height=480)

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            pivot.to_excel(w, sheet_name="Costo Operativo CC")
        st.download_button(
            "📥 Descargar pivot Excel",
            data=buf.getvalue(),
            file_name=f"costo_operativo_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.divider()

    # ─── TENDENCIA MENSUAL ───────────────────────────────────────────────
    st.markdown("### 📈 Tendencia mensual FCST vs PPTO")

    df_tend_fcst = (df_fcst_gasto.groupby("fecha", as_index=False)["valor"].sum()
                                    .sort_values("fecha"))
    df_tend_ppto = (df_ppto_gasto.groupby("fecha", as_index=False)["valor"].sum()
                                    .sort_values("fecha"))

    if not df_tend_fcst.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_tend_fcst["fecha"], y=df_tend_fcst["valor"].abs(),
            name="FCST Gasto", marker_color="#DC2626", opacity=0.85,
            hovertemplate="%{x|%b %Y}<br>FCST: $%{y:,.0f}M<extra></extra>",
        ))
        if not df_tend_ppto.empty:
            fig.add_trace(go.Scatter(
                x=df_tend_ppto["fecha"], y=df_tend_ppto["valor"].abs(),
                name="PPTO", mode="lines+markers",
                line=dict(color="#94A3B8", width=2.5, dash="dash"),
                marker=dict(size=8),
                hovertemplate="%{x|%b %Y}<br>PPTO: $%{y:,.0f}M<extra></extra>",
            ))
        fig.update_layout(
            height=350,
            xaxis=dict(title="Mes"),
            yaxis=dict(title="Gasto operativo (M CLP, abs)", tickformat=",.0f"),
            hovermode="x unified",
            margin=dict(t=20, b=40, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.05, x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ─── TOP DESVIACIONES ───────────────────────────────────────────────
    st.markdown("### 🎯 Top desviaciones FCST vs PPTO por Centro de Costo")

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
        top = (df_gap.sort_values("gap", key=abs, ascending=False)
                     .head(15).reset_index())
        df_show = pd.DataFrame({
            "Centro Costo": top["centro_costo"].str[:35],
            "Área": top["area"].str[:25],
            "PPTO": top["PPTO"].apply(_fmt_clp),
            "FCST": top["FCST"].apply(_fmt_clp),
            "Gap": top["gap"].apply(_fmt_clp),
            "Gap %": top["gap_pct"].apply(_fmt_pct),
        })
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=420)
    else:
        st.info("Sin PPTO o FCST en los filtros actuales para gap analysis")

    st.divider()

    with st.expander("ℹ️ Sobre los datos"):
        st.markdown(f"""
        **Fuente:** [Sheet OPERACIONES 2025-2026](https://docs.google.com/spreadsheets/d/1WXoQYwDwYVXGBIacAUgTpzb-aYXm2BXgXA0_EucKo7M/edit)

        **Refresco automático:** cada 6h vía cron `sync_kpis_wms.yml`.

        **Refresco manual:**
        ```
        python extract_ops_costo_operativo.py
        ```

        **Dimensiones:** Año · Mes · LN · Canal · Tipo Costo (FIJO/VARIABLE) ·
        CC · Área · Sub-Área · Cuenta Analítica

        **Escenarios:** PPTO_VENTA · PPTO_COSTO · PPTO_GASTO · PPTO_CONTRIB ·
        FCST_VENTA · FCST_COSTO · FCST_GASTO · FCST_CONTRIB

        **Costo/Pedido:** cruzado con snapshot WMS (productividad mensual).
        """)
