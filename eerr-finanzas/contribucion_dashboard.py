"""
Dashboard Analisis de Contribucion UnionX — 6 vistas
  Tab 1: Resultados Generales (BI Comercial, YoY 2025 vs 2026)
  Tab 2: Resultado vs Presupuesto
  Tab 3: Comercial vs Contable
  Tab 4: Vista KAM  (vista personal consolidada)
  Tab 5: Oportunidades (insights analiticos automaticos)
  Tab 6: Administracion (carga mensual de datos — solo admin)

Fuente: data/planillas/Analisis_Contribucion_2026_V06.xlsx
"""
import os
from datetime import datetime
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
import plotly.express as px
import plotly.graph_objects as go

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Source of truth: paths centralizados en shared_paths.py (config/sources_of_truth.yaml)
import sys as _sys
if BASE_DIR not in _sys.path:
    _sys.path.insert(0, BASE_DIR)
try:
    import shared_paths as _sp
    XLSX_PATH  = str(_sp.CONTRIBUCION)
    BACKUP_DIR = str(_sp.BACKUPS_DIR)
except Exception:
    # Fallback si shared_paths no disponible
    XLSX_PATH  = os.path.join(BASE_DIR, "data", "planillas", "Analisis_Contribucion_2026_V06.xlsx")
    BACKUP_DIR = os.path.join(BASE_DIR, "data", "planillas", "backups")

MESES = {1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",
         7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"}

# Solo configurar pagina si corremos standalone (no embebido via runpy)
try:
    if not st.session_state.get("_embedded_context"):
        st.set_page_config(
            page_title="Contribucion UnionX",
            page_icon="📊",
            layout="wide",
            initial_sidebar_state="expanded",
        )
except Exception:
    pass  # ya seteado, ignorar

# ── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main .block-container{padding:1.2rem 1.5rem 1rem 1.5rem;max-width:100%;}
  section[data-testid="stSidebar"]{background:linear-gradient(180deg,#0D1B2A 0%,#1B2838 100%);width:270px!important;}
  section[data-testid="stSidebar"] *{color:#CBD5E1!important;}
  section[data-testid="stSidebar"] .stSelectbox label,
  section[data-testid="stSidebar"] .stMultiSelect label{font-size:.8rem!important;font-weight:600;text-transform:uppercase;letter-spacing:.5px;}
  section[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.1)!important;}
  .kpi-card{background:white;border-radius:12px;padding:16px 18px;text-align:center;
    box-shadow:0 1px 3px rgba(0,0,0,.08);border:1px solid #E2E8F0;transition:transform .15s;height:100%;}
  .kpi-card:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.1);}
  .kpi-label{font-size:.72rem;color:#64748B;text-transform:uppercase;letter-spacing:.8px;font-weight:600;margin-bottom:4px;}
  .kpi-value{font-size:1.45rem;font-weight:700;color:#1E293B;line-height:1.2;}
  .kpi-value.blue{color:#1F4E79;} .kpi-value.red{color:#DC2626;}
  .kpi-value.green{color:#16A34A;} .kpi-value.orange{color:#EA580C;}
  .kpi-value.purple{color:#7C3AED;}
  .kpi-sub{font-size:.72rem;color:#94A3B8;margin-top:2px;}
  .kpi-delta-pos{color:#16A34A;font-weight:600;} .kpi-delta-neg{color:#DC2626;font-weight:600;}
  .section-header{font-size:1rem;font-weight:700;color:#1E293B;padding:8px 0 6px 0;
    border-bottom:2px solid #1F4E79;margin-bottom:12px;letter-spacing:.3px;}
  .insight-card{border-radius:10px;padding:14px 16px;margin-bottom:8px;border-left:4px solid #1F4E79;}
  .insight-red{background:#FEF2F2;border-left-color:#DC2626;}
  .insight-green{background:#F0FDF4;border-left-color:#16A34A;}
  .insight-yellow{background:#FEFCE8;border-left-color:#CA8A04;}
  .insight-blue{background:#EFF6FF;border-left-color:#1F4E79;}
  .insight-title{font-weight:700;font-size:.85rem;color:#1E293B;margin-bottom:3px;}
  .insight-body{font-size:.8rem;color:#475569;}
  #MainMenu{visibility:hidden;} footer{visibility:hidden;} .stDeployButton{display:none;}
</style>
""", unsafe_allow_html=True)


# ── HELPERS ─────────────────────────────────────────────────────────────────
def fmt_money(v):
    try:
        v = float(v)
        if not np.isfinite(v): return "$0"
        if abs(v) >= 1e9: return f"${v/1e9:.2f}B"
        if abs(v) >= 1e6: return f"${v/1e6:.1f}M"
        if abs(v) >= 1e3: return f"${v/1e3:.0f}K"
        return f"${v:,.0f}"
    except Exception: return "$0"


def fmt_pct(v, dec=1):
    try:
        v = float(v)
        return f"{v:.{dec}f}%" if np.isfinite(v) else "-"
    except Exception: return "-"


def sign_color(v):
    try: return "green" if float(v) >= 0 else "red"
    except Exception: return "blue"


def kpi_card(col, label, value_str, sub="", color="blue"):
    if sub:
        pos = sub.startswith("+") or (
            not sub.startswith("-") and
            sub.lstrip("$").replace(".","").replace(",","").replace("%","").isnumeric()
        )
        cls = "kpi-delta-pos" if pos else "kpi-delta-neg"
        sub_html = f"<div class='kpi-sub {cls}'>{sub}</div>"
    else:
        sub_html = ""
    col.markdown(f"""
    <div class='kpi-card'>
      <div class='kpi-label'>{label}</div>
      <div class='kpi-value {color}'>{value_str}</div>
      {sub_html}
    </div>""", unsafe_allow_html=True)


def insight_card(col, title, body, tipo="blue"):
    col.markdown(f"""
    <div class='insight-card insight-{tipo}'>
      <div class='insight-title'>{title}</div>
      <div class='insight-body'>{body}</div>
    </div>""", unsafe_allow_html=True)


def clean_num_df(df):
    for c in df.columns:
        if df[c].dtype == object:
            converted = pd.to_numeric(
                df[c].astype(str)
                     .str.replace(r"[\$,\s]", "", regex=True)
                     .str.replace(r"^\-$", "0", regex=True),
                errors="coerce"
            )
            if converted.notna().sum() > len(df) * 0.3:
                df[c] = converted.fillna(0)
    return df.fillna(0)


# ── CARGA DE DATOS ───────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner="Cargando datos...")
def load_all():
    bi   = pd.read_excel(XLSX_PATH, sheet_name="BI Comercial")
    pres = pd.read_excel(XLSX_PATH, sheet_name="Resultado vs Presupuesto")
    cont = pd.read_excel(XLSX_PATH, sheet_name="Comercial vs Contable")

    for df in (bi, pres, cont):
        df = clean_num_df(df)

    bi   = clean_num_df(bi)
    pres = clean_num_df(pres)
    cont = clean_num_df(cont)

    for df in (bi, pres, cont):
        df["Mes"]       = pd.to_numeric(df["Mes"], errors="coerce").fillna(0).astype(int)
        df["MesNombre"] = df["Mes"].map(MESES)

    return bi, pres, cont


bi_raw, pres_raw, cont_raw = load_all()


@st.cache_data(ttl=600)
def compute_canal_metrics(bi_df):
    """
    Compara MISMO PERÍODO: filtra 2025 a los meses que tienen datos 2026.
    Retorna métricas por canal, por negocio, lista de meses y string descriptivo.
    """
    meses_2026 = sorted(bi_df[bi_df["Venta 2026"] > 0]["Mes"].unique().tolist())
    bi_sp = bi_df[bi_df["Mes"].isin(meses_2026)].copy()

    def _enrich(df_grp):
        d = df_grp.copy()
        d["% Margen 26"]   = d["Margen 2026"]        / d["Venta 2026"].replace(0, np.nan) * 100
        d["% Margen 25"]   = d["Margen 2025"]        / d["Venta 2025"].replace(0, np.nan) * 100
        d["% Com 26"]      = d["Total Com. 2026"]    / d["Venta 2026"].replace(0, np.nan) * 100
        d["% Com 25"]      = d["Total Com. 2025"]    / d["Venta 2025"].replace(0, np.nan) * 100
        d["% Contrib 26"]  = d["Contribución 2026"]  / d["Venta 2026"].replace(0, np.nan) * 100
        d["% Contrib 25"]  = d["Contribución 2025"]  / d["Venta 2025"].replace(0, np.nan) * 100
        d["Δ Venta %"]     = (d["Venta 2026"] - d["Venta 2025"]) / d["Venta 2025"].replace(0, np.nan) * 100
        d["Δ Margen pp"]   = d["% Margen 26"]  - d["% Margen 25"]
        d["Δ Com pp"]      = d["% Com 26"]     - d["% Com 25"]
        d["Δ Contrib pp"]  = d["% Contrib 26"] - d["% Contrib 25"]
        d["Δ Venta $"]     = d["Venta 2026"]   - d["Venta 2025"]
        d["Δ Contrib $"]   = d["Contribución 2026"] - d["Contribución 2025"]
        return d

    agg_cols = {
        "Venta 2025": "sum", "Venta 2026": "sum",
        "Margen 2025": "sum", "Margen 2026": "sum",
        "Contribución 2025": "sum", "Contribución 2026": "sum",
        "Total Com. 2025": "sum", "Total Com. 2026": "sum",
    }

    canal_m = bi_sp.groupby(["Canal", "Negocio"]).agg(agg_cols).reset_index()
    canal_m = _enrich(canal_m)
    canal_m = canal_m[(canal_m["Venta 2026"] > 0) | (canal_m["Venta 2025"] > 0)].copy()

    # Scoring de semáforo
    def _semaforo(row):
        score = 0
        if row["Δ Venta %"] > 5:       score += 1
        if row["Δ Venta %"] < -15:     score -= 1
        if row["Δ Contrib pp"] > 1:    score += 1.5
        if row["Δ Contrib pp"] < -1.5: score -= 1.5
        if row["Δ Com pp"] < -1:       score += 0.5
        if row["Δ Com pp"] > 2:        score -= 1
        if row["% Contrib 26"] < 15:   score -= 0.5
        if score > 1.5:   return "🟢 Alto"
        if score >= 0:    return "🟡 Medio"
        return "🔴 Alerta"

    canal_m["Semaforo"] = canal_m.apply(_semaforo, axis=1)

    neg_m = bi_sp.groupby("Negocio").agg(agg_cols).reset_index()
    neg_m = _enrich(neg_m)

    nombres_meses = [MESES[m] for m in meses_2026 if m in MESES]
    periodo_str = f"{nombres_meses[0]}–{nombres_meses[-1]}" if len(nombres_meses) > 1 else nombres_meses[0]

    return canal_m, neg_m, meses_2026, periodo_str


# Pre-compute globally (using full bi_raw — sidebar filters applied per-tab)
_canal_m_global, _neg_m_global, _meses_2026, _periodo_str = compute_canal_metrics(bi_raw)


# ── SIDEBAR ──────────────────────────────────────────────────────────────────
st.sidebar.markdown("### FILTROS")

anos_pres = sorted(pres_raw["Año"].dropna().unique().tolist(), reverse=True)
ano_sel   = st.sidebar.selectbox("Año (Tab 2 & 3)", [str(int(a)) for a in anos_pres], index=0)

negocios_all = ["(Todos)"] + sorted(bi_raw["Negocio"].dropna().unique().tolist())
neg_sel      = st.sidebar.selectbox("Negocio", negocios_all)

canales_all = sorted(bi_raw["Canal"].dropna().unique().tolist())
can_sel     = st.sidebar.multiselect("Canal", canales_all, default=[])

kams_all = sorted(bi_raw["KAM"].dropna().unique().tolist())
kam_sel  = st.sidebar.multiselect("KAM", kams_all, default=[])

trims    = ["(Todos)", "Q1", "Q2", "Q3", "Q4"]
trim_sel = st.sidebar.selectbox("Trimestre", trims)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "<div style='font-size:.75rem;opacity:.7'>Fuente: Analisis Contribucion 2026 V06<br>"
    f"BI: {len(bi_raw):,} | Pres: {len(pres_raw):,} | Cont: {len(cont_raw):,}</div>",
    unsafe_allow_html=True,
)


def apply_filters(df, has_year=False):
    d = df.copy()
    if has_year:
        d = d[d["Año"].astype(str).str.strip() == ano_sel]
    if neg_sel != "(Todos)" and "Negocio" in d.columns:
        d = d[d["Negocio"] == neg_sel]
    if can_sel and "Canal" in d.columns:
        d = d[d["Canal"].isin(can_sel)]
    if kam_sel and "KAM" in d.columns:
        d = d[d["KAM"].isin(kam_sel)]
    if trim_sel != "(Todos)" and "Trimestre" in d.columns:
        d = d[d["Trimestre"] == trim_sel]
    return d


bi   = apply_filters(bi_raw,   has_year=False)
pres = apply_filters(pres_raw, has_year=True)
cont = apply_filters(cont_raw, has_year=True)

# ── ENCABEZADO ───────────────────────────────────────────────────────────────
st.markdown("""
<div style='display:flex;justify-content:space-between;align-items:center;padding:4px 0 10px 0;'>
  <div>
    <div style='font-size:1.5rem;font-weight:700;color:#1E293B;'>Analisis de Contribucion</div>
    <div style='font-size:.82rem;color:#64748B;'>UnionX &mdash; Dashboard BI</div>
  </div>
</div>
""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Resultados Generales",
    "🎯 vs Presupuesto",
    "⚖️ Comercial vs Contable",
    "👤 Vista KAM",
    "💡 Oportunidades",
    "⚙️ Administración",
])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — RESULTADOS GENERALES
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown(f"<div style='font-size:.78rem;color:#94A3B8;margin-bottom:12px;'>Filas filtradas: {len(bi):,}</div>", unsafe_allow_html=True)

    v26 = bi["Venta 2026"].sum();      v25 = bi["Venta 2025"].sum()
    m26 = bi["Margen 2026"].sum();     m25 = bi["Margen 2025"].sum()
    k26 = bi["Contribución 2026"].sum(); k25 = bi["Contribución 2025"].sum()
    c26 = bi["Costo 2026"].sum()
    tc26 = bi["Total Com. 2026"].sum()

    dv = (v26 - v25) / v25 * 100 if v25 else 0
    dk = (k26 - k25) / k25 * 100 if k25 else 0

    st.markdown('<div class="section-header">KPIs Principales — Comparacion YoY</div>', unsafe_allow_html=True)
    cols = st.columns(5)
    kpi_card(cols[0], "Venta 2026",       fmt_money(v26),  f"{'+' if dv>=0 else ''}{dv:.1f}% vs 2025",         "blue")
    kpi_card(cols[1], "Costo 2026",        fmt_money(c26),  f"{(c26/v26*100 if v26 else 0):.1f}% s/venta",       "orange")
    kpi_card(cols[2], "Margen 2026",       fmt_money(m26),  f"{(m26/v26*100 if v26 else 0):.1f}% s/venta",       "green" if m26>=0 else "red")
    kpi_card(cols[3], "Comisiones 2026",   fmt_money(tc26), f"{(tc26/v26*100 if v26 else 0):.1f}% s/venta",      "orange")
    kpi_card(cols[4], "Contribucion 2026", fmt_money(k26),  f"{(k26/v26*100 if v26 else 0):.1f}% s/venta",       "green" if k26>=0 else "red")

    st.markdown("")
    cols2 = st.columns(5)
    kpi_card(cols2[0], "Venta 2025",        fmt_money(v25), "", "blue")
    kpi_card(cols2[1], "Margen 2025",       fmt_money(m25), f"{(m25/v25*100 if v25 else 0):.1f}% s/venta", "green" if m25>=0 else "red")
    kpi_card(cols2[2], "Contribucion 2025", fmt_money(k25), f"{(k25/v25*100 if v25 else 0):.1f}% s/venta", "green" if k25>=0 else "red")
    kpi_card(cols2[3], "Δ Venta YoY",       fmt_money(v26-v25), f"{'+' if dv>=0 else ''}{dv:.1f}%",       sign_color(dv))
    kpi_card(cols2[4], "Δ Contribucion YoY",fmt_money(k26-k25), f"{'+' if dk>=0 else ''}{dk:.1f}%",       sign_color(dk))

    st.markdown("<br>", unsafe_allow_html=True)

    # Evolucion mensual
    st.markdown('<div class="section-header">Evolucion Mensual YoY</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 2])
    with c1:
        ev = bi[bi["Mes"]>0].groupby("Mes").agg({
            "Venta 2025":"sum","Venta 2026":"sum",
            "Contribución 2025":"sum","Contribución 2026":"sum",
        }).reset_index().sort_values("Mes")
        ev["MesNombre"] = ev["Mes"].map(MESES)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=ev["MesNombre"], y=ev["Venta 2025"], name="Venta 2025", marker_color="#94A3B8", opacity=0.85))
        fig.add_trace(go.Bar(x=ev["MesNombre"], y=ev["Venta 2026"], name="Venta 2026", marker_color="#1F4E79"))
        fig.add_trace(go.Scatter(x=ev["MesNombre"], y=ev["Contribución 2025"], name="Contrib 2025", mode="lines+markers", line=dict(color="#CBD5E1", width=2, dash="dot"), yaxis="y2"))
        fig.add_trace(go.Scatter(x=ev["MesNombre"], y=ev["Contribución 2026"], name="Contrib 2026", mode="lines+markers", line=dict(color="#16A34A", width=3), yaxis="y2"))
        fig.update_layout(title="Venta (barras) y Contribucion (lineas) por Mes",
                          barmode="group", height=370, margin=dict(l=10,r=10,t=40,b=10),
                          yaxis=dict(title="Venta $", tickformat="$,.0s"),
                          yaxis2=dict(title="Contribucion $", overlaying="y", side="right", tickformat="$,.0s"),
                          legend=dict(orientation="h", y=-0.18), plot_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        pc = bi.groupby("Canal")["Venta 2026"].sum().reset_index()
        pc = pc[pc["Venta 2026"]>0].sort_values("Venta 2026", ascending=False).head(10)
        fig2 = px.pie(pc, values="Venta 2026", names="Canal", hole=0.55,
                      color_discrete_sequence=px.colors.sequential.Blues_r)
        fig2.update_traces(textposition="outside", textinfo="label+percent")
        fig2.update_layout(title="Mix Venta 2026 por Canal (top 10)", height=370,
                           margin=dict(l=10,r=10,t=40,b=10), showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    # Por Negocio
    st.markdown('<div class="section-header">Resultado por Linea de Negocio</div>', unsafe_allow_html=True)
    c3, c4 = st.columns(2)
    gb_neg = bi.groupby("Negocio").agg({"Venta 2025":"sum","Venta 2026":"sum","Contribución 2025":"sum","Contribución 2026":"sum"}).reset_index()
    gb_neg = gb_neg[gb_neg["Venta 2026"]>0].sort_values("Venta 2026", ascending=False)
    with c3:
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(x=gb_neg["Negocio"], y=gb_neg["Venta 2025"], name="Venta 2025", marker_color="#94A3B8", opacity=0.85))
        fig3.add_trace(go.Bar(x=gb_neg["Negocio"], y=gb_neg["Venta 2026"], name="Venta 2026", marker_color="#1F4E79"))
        fig3.update_layout(title="Venta 2025 vs 2026 por Negocio", barmode="group", height=350,
                           margin=dict(l=10,r=10,t=40,b=60), yaxis=dict(tickformat="$,.0s"),
                           xaxis=dict(tickangle=-20), legend=dict(orientation="h",y=-0.3), plot_bgcolor="white")
        st.plotly_chart(fig3, use_container_width=True)
    with c4:
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(x=gb_neg["Negocio"], y=gb_neg["Contribución 2025"], name="Contrib 2025", marker_color="#86EFAC", opacity=0.85))
        fig4.add_trace(go.Bar(x=gb_neg["Negocio"], y=gb_neg["Contribución 2026"], name="Contrib 2026", marker_color="#16A34A"))
        fig4.update_layout(title="Contribucion 2025 vs 2026 por Negocio", barmode="group", height=350,
                           margin=dict(l=10,r=10,t=40,b=60), yaxis=dict(tickformat="$,.0s"),
                           xaxis=dict(tickangle=-20), legend=dict(orientation="h",y=-0.3), plot_bgcolor="white")
        st.plotly_chart(fig4, use_container_width=True)

    # Ranking KAM + Treemap
    st.markdown('<div class="section-header">Ranking KAM y Composicion</div>', unsafe_allow_html=True)
    c5, c6 = st.columns(2)
    with c5:
        rk = bi.groupby("KAM").agg({"Venta 2026":"sum","Contribución 2026":"sum"}).reset_index()
        rk = rk[rk["Venta 2026"]>0].copy()
        rk["% Contrib"] = (rk["Contribución 2026"] / rk["Venta 2026"] * 100).round(1)
        rk = rk.sort_values("Contribución 2026", ascending=True).tail(12)
        fig5 = go.Figure(go.Bar(y=rk["KAM"], x=rk["Contribución 2026"], orientation="h",
                                 marker_color="#1F4E79",
                                 text=[f"{v:.1f}%" for v in rk["% Contrib"]], textposition="outside"))
        fig5.update_layout(title="Ranking KAM por Contribucion 2026", height=390,
                           margin=dict(l=10,r=60,t=40,b=10), xaxis=dict(tickformat="$,.0s"), plot_bgcolor="white")
        st.plotly_chart(fig5, use_container_width=True)
    with c6:
        tm = bi.groupby(["Negocio","Canal"])["Venta 2026"].sum().reset_index()
        tm = tm[tm["Venta 2026"]>0]
        if len(tm):
            fig6 = px.treemap(tm, path=["Negocio","Canal"], values="Venta 2026",
                              color="Venta 2026", color_continuous_scale="Blues")
            fig6.update_layout(title="Composicion Negocio > Canal (Venta 2026)", height=390, margin=dict(l=10,r=10,t=40,b=10))
            st.plotly_chart(fig6, use_container_width=True)

    # Heatmap
    st.markdown('<div class="section-header">Heatmap Contribucion 2026 — Canal x Mes</div>', unsafe_allow_html=True)
    hm = bi[bi["Mes"]>0].groupby(["Canal","Mes"])["Contribución 2026"].sum().reset_index()
    hm_piv = hm.pivot(index="Canal", columns="Mes", values="Contribución 2026").fillna(0)
    hm_piv = hm_piv.loc[hm_piv.sum(axis=1).sort_values(ascending=False).head(15).index]
    hm_piv.columns = [MESES.get(int(m), m) for m in hm_piv.columns]
    fig7 = px.imshow(hm_piv, aspect="auto", color_continuous_scale="RdYlGn", color_continuous_midpoint=0, text_auto=".2s")
    fig7.update_layout(title="Top 15 canales", height=390, margin=dict(l=10,r=10,t=40,b=10))
    st.plotly_chart(fig7, use_container_width=True)

    # Tabla
    st.markdown('<div class="section-header">Detalle Filtrado</div>', unsafe_allow_html=True)
    show = ["Negocio","Canal","KAM","MesNombre","Trimestre",
            "Venta 2026","Costo 2026","Margen 2026","Total Com. 2026","Contribución 2026",
            "Venta 2025","Contribución 2025","Δ Venta $","Δ Venta %","Δ Contribución $","Δ Contribución %"]
    show = [c for c in show if c in bi.columns]
    tabla_bi = bi[show][(bi["Venta 2026"]!=0)|(bi["Venta 2025"]!=0)]
    st.dataframe(tabla_bi, use_container_width=True, height=320, hide_index=True,
                 column_config={c: st.column_config.NumberColumn(format="$%d") for c in show if "$" in c or "Venta" in c or "Costo" in c or "Margen" in c or "Com." in c or "Contribuc" in c} |
                                {c: st.column_config.NumberColumn(format="%.1f%%") for c in show if "%" in c})
    st.download_button("Descargar CSV", tabla_bi.to_csv(index=False).encode("utf-8-sig"), "bi_comercial.csv", "text/csv")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — vs PRESUPUESTO
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown(f"<div style='font-size:.78rem;color:#94A3B8;margin-bottom:12px;'>Año: {ano_sel} — Filas: {len(pres):,}</div>", unsafe_allow_html=True)

    if len(pres) == 0:
        st.warning("Sin datos para los filtros seleccionados.")
    else:
        meta_v = pres["Meta Venta ($)"].sum();           res_v  = pres["Resultado Venta ($)"].sum()
        meta_k = pres["Meta Contribución ($)"].sum();    res_k  = pres["Resultado Contribución ($)"].sum()
        pct_v  = res_v / meta_v * 100 if meta_v else 0; pct_k  = res_k / meta_k * 100 if meta_k else 0

        st.markdown('<div class="section-header">KPIs Cumplimiento de Metas</div>', unsafe_allow_html=True)
        cols = st.columns(4)
        kpi_card(cols[0], "Meta Venta",        fmt_money(meta_v), "", "blue")
        kpi_card(cols[1], "Resultado Venta",   fmt_money(res_v),  f"Δ {fmt_money(res_v-meta_v)} vs meta", sign_color(res_v-meta_v))
        kpi_card(cols[2], "Meta Contribucion", fmt_money(meta_k), "", "blue")
        kpi_card(cols[3], "Resultado Contrib", fmt_money(res_k),  f"Δ {fmt_money(res_k-meta_k)} vs meta", sign_color(res_k-meta_k))

        st.markdown("")
        cols2 = st.columns(4)
        kpi_card(cols2[0], "% Cumpl. Venta",     f"{pct_v:.1f}%", "", sign_color(pct_v-100))
        kpi_card(cols2[1], "Δ Venta vs Meta",     fmt_money(res_v-meta_v),  f"{'+' if pct_v>=100 else ''}{pct_v-100:.1f}pp", sign_color(pct_v-100))
        kpi_card(cols2[2], "% Cumpl. Contrib",    f"{pct_k:.1f}%", "", sign_color(pct_k-100))
        kpi_card(cols2[3], "Δ Contrib vs Meta",   fmt_money(res_k-meta_k),  f"{'+' if pct_k>=100 else ''}{pct_k-100:.1f}pp", sign_color(pct_k-100))

        st.markdown("<br>", unsafe_allow_html=True)

        # Meta vs Resultado por Negocio
        st.markdown('<div class="section-header">Meta vs Resultado por Negocio</div>', unsafe_allow_html=True)
        ca, cb = st.columns(2)
        gb_n = pres.groupby("Negocio").agg({"Meta Venta ($)":"sum","Resultado Venta ($)":"sum"}).reset_index()
        gb_n = gb_n[gb_n["Meta Venta ($)"]>0].sort_values("Meta Venta ($)", ascending=False)
        with ca:
            fig_pv = go.Figure()
            fig_pv.add_trace(go.Bar(x=gb_n["Negocio"], y=gb_n["Meta Venta ($)"], name="Meta", marker_color="#94A3B8", opacity=0.85))
            fig_pv.add_trace(go.Bar(x=gb_n["Negocio"], y=gb_n["Resultado Venta ($)"], name="Resultado", marker_color="#1F4E79"))
            fig_pv.update_layout(title="Venta: Meta vs Resultado", barmode="group", height=350,
                                  margin=dict(l=10,r=10,t=40,b=60), yaxis=dict(tickformat="$,.0s"),
                                  xaxis=dict(tickangle=-20), legend=dict(orientation="h",y=-0.3), plot_bgcolor="white")
            st.plotly_chart(fig_pv, use_container_width=True)
        gb_nk = pres.groupby("Negocio").agg({"Meta Contribución ($)":"sum","Resultado Contribución ($)":"sum"}).reset_index()
        gb_nk = gb_nk[gb_nk["Meta Contribución ($)"]>0].sort_values("Meta Contribución ($)", ascending=False)
        with cb:
            fig_pk = go.Figure()
            fig_pk.add_trace(go.Bar(x=gb_nk["Negocio"], y=gb_nk["Meta Contribución ($)"], name="Meta", marker_color="#86EFAC", opacity=0.85))
            fig_pk.add_trace(go.Bar(x=gb_nk["Negocio"], y=gb_nk["Resultado Contribución ($)"], name="Resultado", marker_color="#16A34A"))
            fig_pk.update_layout(title="Contribucion: Meta vs Resultado", barmode="group", height=350,
                                  margin=dict(l=10,r=10,t=40,b=60), yaxis=dict(tickformat="$,.0s"),
                                  xaxis=dict(tickangle=-20), legend=dict(orientation="h",y=-0.3), plot_bgcolor="white")
            st.plotly_chart(fig_pk, use_container_width=True)

        # % Cumplimiento por KAM
        st.markdown('<div class="section-header">Cumplimiento por KAM</div>', unsafe_allow_html=True)
        cc, cd = st.columns(2)
        def cum_bar(col, df_g, meta_c, res_c, title):
            g = df_g.groupby("KAM").agg({meta_c:"sum", res_c:"sum"}).reset_index()
            g = g[g[meta_c]>0].copy()
            g["% Cumpl."] = g[res_c] / g[meta_c] * 100
            g = g.sort_values("% Cumpl.", ascending=True)
            colors = ["#16A34A" if v>=100 else "#DC2626" for v in g["% Cumpl."]]
            fig = go.Figure(go.Bar(y=g["KAM"], x=g["% Cumpl."], orientation="h", marker_color=colors,
                                    text=[f"{v:.1f}%" for v in g["% Cumpl."]], textposition="outside"))
            fig.add_vline(x=100, line_dash="dash", line_color="#64748B", line_width=1.5)
            fig.update_layout(title=title, height=340, showlegend=False,
                               margin=dict(l=10,r=60,t=40,b=10), xaxis=dict(ticksuffix="%"), plot_bgcolor="white")
            col.plotly_chart(fig, use_container_width=True)
        cum_bar(cc, pres, "Meta Venta ($)", "Resultado Venta ($)", "% Cumplimiento Venta por KAM")
        cum_bar(cd, pres, "Meta Contribución ($)", "Resultado Contribución ($)", "% Cumplimiento Contribucion por KAM")

        # Evolucion mensual cumplimiento
        st.markdown('<div class="section-header">Evolucion Mensual de Cumplimiento</div>', unsafe_allow_html=True)
        ev_p = pres[pres["Mes"]>0].groupby("Mes").agg({
            "Meta Venta ($)":"sum","Resultado Venta ($)":"sum",
            "Meta Contribución ($)":"sum","Resultado Contribución ($)":"sum",
        }).reset_index()
        ev_p["% Cumpl. Venta"]   = ev_p["Resultado Venta ($)"]          / ev_p["Meta Venta ($)"].replace(0,np.nan) * 100
        ev_p["% Cumpl. Contrib"] = ev_p["Resultado Contribución ($)"]   / ev_p["Meta Contribución ($)"].replace(0,np.nan) * 100
        ev_p["MesNombre"] = ev_p["Mes"].map(MESES)
        ev_p = ev_p.sort_values("Mes")
        fig_ev = go.Figure()
        fig_ev.add_trace(go.Scatter(x=ev_p["MesNombre"], y=ev_p["% Cumpl. Venta"],
                                     name="% Cumpl. Venta", mode="lines+markers",
                                     line=dict(color="#1F4E79", width=3), marker=dict(size=8)))
        fig_ev.add_trace(go.Scatter(x=ev_p["MesNombre"], y=ev_p["% Cumpl. Contrib"],
                                     name="% Cumpl. Contrib", mode="lines+markers",
                                     line=dict(color="#16A34A", width=3), marker=dict(size=8)))
        fig_ev.add_hline(y=100, line_dash="dash", line_color="#DC2626",
                          annotation_text="Meta 100%", annotation_position="bottom right")
        fig_ev.update_layout(title="Evolucion % Cumplimiento Mensual", height=320,
                              margin=dict(l=10,r=10,t=40,b=10), yaxis=dict(ticksuffix="%"),
                              legend=dict(orientation="h",y=-0.15), plot_bgcolor="white")
        st.plotly_chart(fig_ev, use_container_width=True)

        # Tabla
        st.markdown('<div class="section-header">Detalle Filtrado</div>', unsafe_allow_html=True)
        cp = ["Negocio","Canal","KAM","MesNombre","Trimestre",
              "Meta Venta ($)","Resultado Venta ($)","Δ Venta ($)","% Cumpl. Venta",
              "Meta Contribución ($)","Resultado Contribución ($)","Δ Contribución ($)","% Cumpl. Contri","Estado"]
        cp = [c for c in cp if c in pres.columns]
        st.dataframe(pres[cp], use_container_width=True, height=320, hide_index=True,
                     column_config={c: st.column_config.NumberColumn(format="$%d") for c in cp if "$" in c} |
                                    {c: st.column_config.NumberColumn(format="%.1f%%") for c in cp if "%" in c})
        st.download_button("Descargar CSV", pres[cp].to_csv(index=False).encode("utf-8-sig"),
                           "presupuesto.csv", "text/csv", key="dl_pres")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — COMERCIAL vs CONTABLE
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    st.info(
        "**Nota:** Los datos de conciliacion Contable estan disponibles desde **2026**. "
        "En 2025 la mayoria de filas aparece como 'SIN DATOS' o 'SIN CONTABLE' porque "
        "el registro contable detallado por canal comenzo ese año."
    )
    st.markdown(f"<div style='font-size:.78rem;color:#94A3B8;margin-bottom:12px;'>Año: {ano_sel} — Filas: {len(cont):,}</div>", unsafe_allow_html=True)

    if len(cont) == 0:
        st.warning("Sin datos para los filtros seleccionados.")
    else:
        cont_con = cont[cont["Alerta"].isin(["ALINEADO","DIF 5-20%","DIF >20%"])] if "Alerta" in cont.columns else cont
        cont_sin = cont[cont["Alerta"].isin(["SIN CONTABLE","SIN DATOS","SIN KAM"])]  if "Alerta" in cont.columns else pd.DataFrame()

        v_kam = cont["Venta KAM ($)"].sum();         v_cnt = cont["Venta Contable ($)"].sum()
        k_kam = cont["Contribución KAM ($)"].sum();  k_cnt = cont["Contribución Cont. ($)"].sum()
        m_kam = cont["Margen KAM ($)"].sum();        m_cnt = cont["Margen Contable ($)"].sum()
        dk_cnt = cont["Δ Contribución ($)"].sum()

        st.markdown('<div class="section-header">KPIs Comercial vs Contable</div>', unsafe_allow_html=True)

        with st.columns([3,1])[1]:
            alertas_count = cont["Alerta"].value_counts().to_dict() if "Alerta" in cont.columns else {}
            lines = [f"**{v}** {k}" for k,v in alertas_count.items()]
            st.info(" | ".join(lines))

        cols = st.columns(4)
        kpi_card(cols[0], "Venta KAM",           fmt_money(v_kam), "", "blue")
        kpi_card(cols[1], "Venta Contable",       fmt_money(v_cnt), f"Δ {fmt_money(v_cnt-v_kam)}", sign_color(v_cnt-v_kam))
        kpi_card(cols[2], "Contribucion KAM",     fmt_money(k_kam), "", "green" if k_kam>=0 else "red")
        kpi_card(cols[3], "Contribucion Contable",fmt_money(k_cnt), f"Δ {fmt_money(dk_cnt)}", sign_color(dk_cnt))

        st.markdown("")
        cols2 = st.columns(4)
        kpi_card(cols2[0], "Margen KAM",      fmt_money(m_kam), f"{(m_kam/v_kam*100 if v_kam else 0):.1f}% s/venta", "green" if m_kam>=0 else "red")
        kpi_card(cols2[1], "Margen Contable",  fmt_money(m_cnt), f"{(m_cnt/v_cnt*100 if v_cnt else 0):.1f}% s/venta", "green" if m_cnt>=0 else "red")
        kpi_card(cols2[2], "Filas con Contable",   str(len(cont_con)), f"de {len(cont)} totales", "blue")
        kpi_card(cols2[3], "Sin Conciliar",   str(len(cont_sin)), "requieren atencion", "orange")

        st.markdown("<br>", unsafe_allow_html=True)

        # KAM vs Contable por Negocio
        st.markdown('<div class="section-header">KAM vs Contable por Negocio</div>', unsafe_allow_html=True)
        ce, cf = st.columns(2)
        gb_cn = cont.groupby("Negocio").agg({"Venta KAM ($)":"sum","Venta Contable ($)":"sum"}).reset_index()
        gb_cn = gb_cn[gb_cn["Venta KAM ($)"]>0].sort_values("Venta KAM ($)", ascending=False)
        with ce:
            fig_cv = go.Figure()
            fig_cv.add_trace(go.Bar(x=gb_cn["Negocio"], y=gb_cn["Venta KAM ($)"], name="KAM", marker_color="#1F4E79"))
            fig_cv.add_trace(go.Bar(x=gb_cn["Negocio"], y=gb_cn["Venta Contable ($)"], name="Contable", marker_color="#F97316", opacity=0.85))
            fig_cv.update_layout(title="Venta KAM vs Contable", barmode="group", height=350,
                                  margin=dict(l=10,r=10,t=40,b=60), yaxis=dict(tickformat="$,.0s"),
                                  xaxis=dict(tickangle=-20), legend=dict(orientation="h",y=-0.3), plot_bgcolor="white")
            st.plotly_chart(fig_cv, use_container_width=True)
        gb_ck = cont.groupby("Negocio").agg({"Contribución KAM ($)":"sum","Contribución Cont. ($)":"sum"}).reset_index()
        gb_ck = gb_ck[gb_ck["Contribución KAM ($)"]>0].sort_values("Contribución KAM ($)", ascending=False)
        with cf:
            fig_ck = go.Figure()
            fig_ck.add_trace(go.Bar(x=gb_ck["Negocio"], y=gb_ck["Contribución KAM ($)"], name="KAM", marker_color="#16A34A"))
            fig_ck.add_trace(go.Bar(x=gb_ck["Negocio"], y=gb_ck["Contribución Cont. ($)"], name="Contable", marker_color="#F59E0B", opacity=0.85))
            fig_ck.update_layout(title="Contribucion KAM vs Contable", barmode="group", height=350,
                                  margin=dict(l=10,r=10,t=40,b=60), yaxis=dict(tickformat="$,.0s"),
                                  xaxis=dict(tickangle=-20), legend=dict(orientation="h",y=-0.3), plot_bgcolor="white")
            st.plotly_chart(fig_ck, use_container_width=True)

        # Δ Contribucion por Canal + KAM overlay
        st.markdown('<div class="section-header">Brecha por Canal y por KAM</div>', unsafe_allow_html=True)
        cg, ch = st.columns(2)
        with cg:
            dc = cont.groupby("Canal")["Δ Contribución ($)"].sum().reset_index()
            dc = dc[dc["Δ Contribución ($)"]!=0].sort_values("Δ Contribución ($)", ascending=True).head(20)
            fig_dc = go.Figure(go.Bar(y=dc["Canal"], x=dc["Δ Contribución ($)"], orientation="h",
                                       marker_color=["#16A34A" if v>=0 else "#DC2626" for v in dc["Δ Contribución ($)"]],
                                       text=[fmt_money(v) for v in dc["Δ Contribución ($)"]], textposition="outside"))
            fig_dc.add_vline(x=0, line_color="#64748B", line_width=1)
            fig_dc.update_layout(title="Δ Contribucion (KAM − Contable) por Canal",
                                  height=420, showlegend=False,
                                  margin=dict(l=10,r=80,t=40,b=10), xaxis=dict(tickformat="$,.0s"), plot_bgcolor="white")
            st.plotly_chart(fig_dc, use_container_width=True)
        with ch:
            kcc = cont.groupby("KAM").agg({"Contribución KAM ($)":"sum","Contribución Cont. ($)":"sum"}).reset_index()
            kcc = kcc[kcc["Contribución KAM ($)"]>0].sort_values("Contribución KAM ($)", ascending=True)
            fig_kcc = go.Figure()
            fig_kcc.add_trace(go.Bar(y=kcc["KAM"], x=kcc["Contribución KAM ($)"], orientation="h", name="KAM", marker_color="#16A34A", opacity=0.9))
            fig_kcc.add_trace(go.Bar(y=kcc["KAM"], x=kcc["Contribución Cont. ($)"], orientation="h", name="Contable", marker_color="#F59E0B", opacity=0.9))
            fig_kcc.update_layout(title="Contribucion KAM vs Contable por KAM",
                                   barmode="overlay", height=420,
                                   margin=dict(l=10,r=10,t=40,b=10), xaxis=dict(tickformat="$,.0s"),
                                   legend=dict(orientation="h",y=-0.1), plot_bgcolor="white")
            st.plotly_chart(fig_kcc, use_container_width=True)

        # Evolucion mensual
        st.markdown('<div class="section-header">Evolucion Mensual de Brechas</div>', unsafe_allow_html=True)
        ev_c = cont[cont["Mes"]>0].groupby("Mes").agg({
            "Contribución KAM ($)":"sum","Contribución Cont. ($)":"sum","Δ Contribución ($)":"sum",
        }).reset_index().sort_values("Mes")
        ev_c["MesNombre"] = ev_c["Mes"].map(MESES)
        fig_evc = go.Figure()
        fig_evc.add_trace(go.Bar(x=ev_c["MesNombre"], y=ev_c["Contribución KAM ($)"], name="Contrib KAM", marker_color="#16A34A", opacity=0.85))
        fig_evc.add_trace(go.Bar(x=ev_c["MesNombre"], y=ev_c["Contribución Cont. ($)"], name="Contrib Contable", marker_color="#F59E0B", opacity=0.85))
        fig_evc.add_trace(go.Scatter(x=ev_c["MesNombre"], y=ev_c["Δ Contribución ($)"], name="Δ",
                                      mode="lines+markers", line=dict(color="#DC2626", width=2.5), yaxis="y2"))
        fig_evc.update_layout(title="Contribucion KAM vs Contable por Mes + Δ (linea)",
                               barmode="group", height=340,
                               margin=dict(l=10,r=10,t=40,b=10),
                               yaxis=dict(title="$", tickformat="$,.0s"),
                               yaxis2=dict(title="Δ $", overlaying="y", side="right", tickformat="$,.0s"),
                               legend=dict(orientation="h",y=-0.18), plot_bgcolor="white")
        st.plotly_chart(fig_evc, use_container_width=True)

        # Heatmap alertas
        if "Alerta" in cont.columns:
            st.markdown('<div class="section-header">Mapa de Alertas por Canal</div>', unsafe_allow_html=True)
            ac = cont.groupby(["Canal","Alerta"]).size().reset_index(name="n")
            ap = ac.pivot(index="Canal", columns="Alerta", values="n").fillna(0)
            top_c = cont.groupby("Canal")["Venta KAM ($)"].sum().nlargest(15).index
            ap = ap.loc[ap.index.intersection(top_c)]
            if len(ap):
                fig_al = px.imshow(ap, aspect="auto", color_continuous_scale="RdYlGn_r", text_auto=True)
                fig_al.update_layout(title="Distribucion de Alertas — top 15 canales por venta",
                                      height=360, margin=dict(l=10,r=10,t=40,b=10))
                st.plotly_chart(fig_al, use_container_width=True)

        # Tabla
        st.markdown('<div class="section-header">Detalle Filtrado</div>', unsafe_allow_html=True)
        cc_cols = ["Negocio","Canal","KAM","MesNombre","Trimestre",
                   "Venta KAM ($)","Margen KAM ($)","Total Com. KAM ($)","Contribución KAM ($)",
                   "Venta Contable ($)","Margen Contable ($)","Total Com. Cont. ($)","Contribución Cont. ($)",
                   "Δ Venta ($)","Δ Contribución ($)","% Δ Venta","% Δ Contribución","Alerta"]
        cc_cols = [c for c in cc_cols if c in cont.columns]
        st.dataframe(cont[cc_cols], use_container_width=True, height=320, hide_index=True,
                     column_config={c: st.column_config.NumberColumn(format="$%d") for c in cc_cols if "$" in c} |
                                    {c: st.column_config.NumberColumn(format="%.1f%%") for c in cc_cols if "%" in c})
        st.download_button("Descargar CSV", cont[cc_cols].to_csv(index=False).encode("utf-8-sig"),
                           "comercial_contable.csv", "text/csv", key="dl_cont")


# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — VISTA KAM
# ════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("""
    <div style='background:#EFF6FF;border-radius:10px;padding:12px 16px;margin-bottom:16px;border-left:4px solid #1F4E79;'>
      <div style='font-weight:700;color:#1E293B;font-size:.9rem;'>Vista personal por KAM</div>
      <div style='color:#475569;font-size:.8rem;margin-top:2px;'>
        Selecciona un KAM para ver su rendimiento consolidado: BI comercial, cumplimiento de metas y diferencias contables.
        Los filtros del sidebar (Negocio, Canal, Trimestre) siguen aplicando.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Selector KAM dentro del tab (vista personal = 1 KAM a la vez)
    kams_tab4 = [k for k in kams_all if k != "TODOS"]
    kam4 = st.selectbox("Selecciona KAM", kams_tab4, key="kam4_sel")

    def filter_for_kam(df, has_year=False):
        d = df.copy()
        if has_year:
            d = d[d["Año"].astype(str).str.strip() == "2026"]
        if neg_sel != "(Todos)" and "Negocio" in d.columns:
            d = d[d["Negocio"] == neg_sel]
        if can_sel and "Canal" in d.columns:
            d = d[d["Canal"].isin(can_sel)]
        if trim_sel != "(Todos)" and "Trimestre" in d.columns:
            d = d[d["Trimestre"] == trim_sel]
        return d[d["KAM"] == kam4]

    bi4   = filter_for_kam(bi_raw,   has_year=False)
    pres4 = filter_for_kam(pres_raw, has_year=True)
    cont4 = filter_for_kam(cont_raw, has_year=True)

    if len(bi4) == 0:
        st.warning(f"No hay datos de BI para {kam4} con los filtros actuales.")
    else:
        # ── Resumen KAM ────────────────────────────────────────────────────
        v26k = bi4["Venta 2026"].sum(); v25k = bi4["Venta 2025"].sum()
        k26k = bi4["Contribución 2026"].sum(); k25k = bi4["Contribución 2025"].sum()
        dvk  = (v26k-v25k)/v25k*100 if v25k else 0
        dkk  = (k26k-k25k)/k25k*100 if k25k else 0
        n_canales = bi4["Canal"].nunique()

        st.markdown(f'<div class="section-header">Resumen {kam4} — {n_canales} canales activos</div>', unsafe_allow_html=True)
        cols = st.columns(5)
        kpi_card(cols[0], "Venta 2026",     fmt_money(v26k), f"{'+' if dvk>=0 else ''}{dvk:.1f}% vs 2025", "blue")
        kpi_card(cols[1], "Venta 2025",     fmt_money(v25k), "", "blue")
        kpi_card(cols[2], "Contrib 2026",   fmt_money(k26k), f"{(k26k/v26k*100 if v26k else 0):.1f}% s/venta", "green" if k26k>=0 else "red")
        kpi_card(cols[3], "Contrib 2025",   fmt_money(k25k), f"{(k25k/v25k*100 if v25k else 0):.1f}% s/venta", "green" if k25k>=0 else "red")
        kpi_card(cols[4], "Δ Contribucion", fmt_money(k26k-k25k), f"{'+' if dkk>=0 else ''}{dkk:.1f}%", sign_color(dkk))

        # Cumplimiento presupuesto si hay datos
        if len(pres4) > 0:
            meta_vk = pres4["Meta Venta ($)"].sum(); res_vk = pres4["Resultado Venta ($)"].sum()
            meta_kk = pres4["Meta Contribución ($)"].sum(); res_kk = pres4["Resultado Contribución ($)"].sum()
            pct_vk = res_vk/meta_vk*100 if meta_vk else 0
            pct_kk = res_kk/meta_kk*100 if meta_kk else 0
            st.markdown("")
            cols2 = st.columns(4)
            kpi_card(cols2[0], "Meta Venta",        fmt_money(meta_vk), "", "blue")
            kpi_card(cols2[1], "% Cumpl. Venta",    f"{pct_vk:.1f}%",   f"Δ {fmt_money(res_vk-meta_vk)}", sign_color(pct_vk-100))
            kpi_card(cols2[2], "Meta Contribucion", fmt_money(meta_kk), "", "blue")
            kpi_card(cols2[3], "% Cumpl. Contrib",  f"{pct_kk:.1f}%",   f"Δ {fmt_money(res_kk-meta_kk)}", sign_color(pct_kk-100))

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Cuadrante Comercial por Canal ──────────────────────────────────
        st.markdown(f'<div class="section-header">Cuadrante Comercial — Canales de {kam4} ({_periodo_str} 2025 vs 2026)</div>', unsafe_allow_html=True)
        st.caption("Comparación mismo período. Tamaño = Venta 2026. Color = variación de comisiones (azul=bajaron ✓, rojo=subieron ✗).")

        bi4_sp = bi4[bi4["Mes"].isin(_meses_2026)]
        ch4_q = bi4_sp.groupby("Canal").agg({
            "Venta 2025":"sum","Venta 2026":"sum",
            "Margen 2025":"sum","Margen 2026":"sum",
            "Contribución 2025":"sum","Contribución 2026":"sum",
            "Total Com. 2025":"sum","Total Com. 2026":"sum",
        }).reset_index()
        ch4_q = ch4_q[(ch4_q["Venta 2026"]>0)|(ch4_q["Venta 2025"]>0)].copy()
        ch4_q["% Contrib 26"] = ch4_q["Contribución 2026"] / ch4_q["Venta 2026"].replace(0,np.nan)*100
        ch4_q["% Com 26"]     = ch4_q["Total Com. 2026"]   / ch4_q["Venta 2026"].replace(0,np.nan)*100
        ch4_q["% Com 25"]     = ch4_q["Total Com. 2025"]   / ch4_q["Venta 2025"].replace(0,np.nan)*100
        ch4_q["% Margen 26"]  = ch4_q["Margen 2026"]       / ch4_q["Venta 2026"].replace(0,np.nan)*100
        ch4_q["% Margen 25"]  = ch4_q["Margen 2025"]       / ch4_q["Venta 2025"].replace(0,np.nan)*100
        ch4_q["Δ Venta %"]    = (ch4_q["Venta 2026"]-ch4_q["Venta 2025"])/ch4_q["Venta 2025"].replace(0,np.nan)*100
        ch4_q["Δ Margen pp"]  = ch4_q["% Margen 26"] - ch4_q["% Margen 25"]
        ch4_q["Δ Com pp"]     = ch4_q["% Com 26"]    - ch4_q["% Com 25"]
        ch4_q["Δ Contrib pp"] = ch4_q["% Contrib 26"] - ch4_q["Contribución 2025"]/ch4_q["Venta 2025"].replace(0,np.nan)*100
        ch4_q_clean = ch4_q.dropna(subset=["Δ Venta %","% Contrib 26"])

        if len(ch4_q_clean) >= 2:
            avg_contrib = ch4_q_clean["% Contrib 26"].mean()
            fig_quad = go.Figure()

            # Color scale: azul si Δ Com pp <= 0 (bueno), rojo si > 0
            for _, row in ch4_q_clean.iterrows():
                color = "#1F4E79" if row["Δ Com pp"] <= 0 else "#DC2626"
                size  = max(12, min(60, float(row["Venta 2026"])/2e6))
                fig_quad.add_trace(go.Scatter(
                    x=[row["Δ Venta %"]], y=[row["% Contrib 26"]],
                    mode="markers+text",
                    marker=dict(size=size, color=color, opacity=0.85, line=dict(width=1.5, color="white")),
                    text=[row["Canal"]], textposition="top center",
                    textfont=dict(size=10),
                    hovertemplate=(
                        f"<b>{row['Canal']}</b><br>"
                        f"Δ Venta: {row['Δ Venta %']:+.1f}%<br>"
                        f"% Contrib: {row['% Contrib 26']:.1f}%<br>"
                        f"Margen: {row['% Margen 26']:.1f}% (Δ{row['Δ Margen pp']:+.1f}pp)<br>"
                        f"Com: {row['% Com 26']:.1f}% (Δ{row['Δ Com pp']:+.1f}pp)<br>"
                        f"Venta: {fmt_money(row['Venta 2026'])}<extra></extra>"
                    ),
                    name=row["Canal"],
                    showlegend=False,
                ))

            fig_quad.add_vline(x=0, line_color="#94A3B8", line_width=1.5, line_dash="dash")
            fig_quad.add_hline(y=avg_contrib, line_color="#94A3B8", line_width=1.5, line_dash="dash",
                                annotation_text=f"Promedio {avg_contrib:.1f}%", annotation_position="right")

            xmax = ch4_q_clean["Δ Venta %"].abs().max()*1.2 or 50
            ymax = ch4_q_clean["% Contrib 26"].max()*1.15 or 60
            ymin = min(0, ch4_q_clean["% Contrib 26"].min()*1.2)

            for (tx, ty, label, bg) in [
                (xmax*0.65,  ymax*0.92,  "CRECER ✓",   "#F0FDF4"),
                (-xmax*0.82, ymax*0.92,  "DEFENDER",   "#EFF6FF"),
                (xmax*0.65,  ymin*0.5 if ymin<0 else avg_contrib*0.4, "OPTIMIZAR", "#FEFCE8"),
                (-xmax*0.82, ymin*0.5 if ymin<0 else avg_contrib*0.4, "REVISAR ✗", "#FEF2F2"),
            ]:
                fig_quad.add_annotation(x=tx, y=ty, text=label, showarrow=False,
                                         font=dict(size=11, color="#64748B"), bgcolor=bg,
                                         bordercolor="#E2E8F0", borderwidth=1, borderpad=4)

            fig_quad.update_layout(
                height=420, margin=dict(l=10,r=10,t=20,b=10),
                xaxis=dict(title="Δ Venta % (mismo período YoY)", ticksuffix="%", zeroline=False),
                yaxis=dict(title="% Contribución 2026", ticksuffix="%", zeroline=False),
                plot_bgcolor="white",
            )
            st.plotly_chart(fig_quad, use_container_width=True)
        else:
            st.info("Datos insuficientes para el cuadrante con los filtros actuales.")

        # ── Tabla Comercial vs Contable ────────────────────────────────────────
        st.markdown(
            f'<div class="section-header">Comercial vs Contable — {kam4} (2026)</div>',
            unsafe_allow_html=True,
        )

        cont4_2026 = filter_for_kam(cont_raw, has_year=True)

        if len(cont4_2026) > 0:
            tbl_cont = cont4_2026.groupby("Canal").agg({
                "Venta KAM ($)":         "sum",
                "Venta Contable ($)":    "sum",
                "Margen KAM ($)":        "sum",
                "Margen Contable ($)":   "sum",
                "Total Com. KAM ($)":    "sum",
                "Total Com. Cont. ($)":  "sum",
                "Contribución KAM ($)":  "sum",
                "Contribución Cont. ($)":"sum",
                "Alerta":               "first",
            }).reset_index()

            v0 = tbl_cont["Venta KAM ($)"].replace(0, np.nan)
            vc = tbl_cont["Venta Contable ($)"].replace(0, np.nan)
            tbl_cont["% Margen KAM"]   = tbl_cont["Margen KAM ($)"]       / v0  * 100
            tbl_cont["% Margen Cont"]  = tbl_cont["Margen Contable ($)"]  / vc  * 100
            tbl_cont["% Com KAM"]      = tbl_cont["Total Com. KAM ($)"]   / v0  * 100
            tbl_cont["% Com Cont"]     = tbl_cont["Total Com. Cont. ($)"] / vc  * 100
            tbl_cont["% Contrib KAM"]  = tbl_cont["Contribución KAM ($)"] / v0  * 100
            tbl_cont["% Contrib Cont"] = tbl_cont["Contribución Cont. ($)"]/ vc * 100
            tbl_cont["Δ Venta"]        = tbl_cont["Venta KAM ($)"]        - tbl_cont["Venta Contable ($)"]
            tbl_cont["Δ Margen"]       = tbl_cont["Margen KAM ($)"]       - tbl_cont["Margen Contable ($)"]
            tbl_cont["Δ Com"]          = tbl_cont["Total Com. KAM ($)"]   - tbl_cont["Total Com. Cont. ($)"]
            tbl_cont["Δ Contrib"]      = tbl_cont["Contribución KAM ($)"] - tbl_cont["Contribución Cont. ($)"]

            tbl_cont = tbl_cont[tbl_cont["Venta KAM ($)"] > 0].sort_values("Venta KAM ($)", ascending=False)

            # ── KPIs resumen de brechas ─────────────────────────────────────
            dv_tot = tbl_cont["Δ Venta"].sum()
            dm_tot = tbl_cont["Δ Margen"].sum()
            dc_tot = tbl_cont["Δ Com"].sum()
            dk_tot = tbl_cont["Δ Contrib"].sum()
            cols_kpi = st.columns(4)
            kpi_card(cols_kpi[0], "Δ Venta total",       fmt_money(dv_tot),
                     "KAM − Contable", sign_color(dv_tot))
            kpi_card(cols_kpi[1], "Δ Margen directo",    fmt_money(dm_tot),
                     "KAM − Contable", sign_color(dm_tot))
            kpi_card(cols_kpi[2], "Δ Comisiones",        fmt_money(dc_tot),
                     "KAM − Contable", sign_color(-dc_tot))
            kpi_card(cols_kpi[3], "Δ Contribucion",      fmt_money(dk_tot),
                     "KAM − Contable", sign_color(dk_tot))

            st.markdown("<br>", unsafe_allow_html=True)

            # ── Tabla con agrupación visual de bloques ──────────────────────
            # Generar HTML table para tener control total de colores y formato
            alerta_cfg = {
                "ALINEADO":     ("#F0FDF4", "#16A34A", "🟢"),
                "DIF 5-20%":    ("#FEFCE8", "#CA8A04", "🟡"),
                "DIF >20%":     ("#FEF2F2", "#DC2626", "🔴"),
                "SIN CONTABLE": ("#F8FAFC", "#94A3B8", "⚪"),
                "SIN DATOS":    ("#F8FAFC", "#CBD5E1", "⚪"),
                "SIN KAM":      ("#F8FAFC", "#64748B", "⚪"),
            }

            def _cd(val, inverse=False):
                """Celda delta: texto con color CSS inline (sin span anidado)."""
                try:
                    v = float(val)
                    good  = (v >= 0) if not inverse else (v <= 0)
                    color = "#16A34A" if good else "#DC2626"
                    arrow = "▲" if v > 0 else ("▼" if v < 0 else "—")
                    return f'{arrow} {fmt_money(abs(v))}', color
                except Exception:
                    return "—", "#94A3B8"

            def _pct(val):
                try:
                    v = float(val)
                    return f"{v:.1f}%" if np.isfinite(v) else "—"
                except Exception:
                    return "—"

            def td(content, align="right", color="", bold=False, muted=False, small_sub=""):
                """Genera un <td> con estilo inline, sin etiquetas anidadas."""
                styles = [f"padding:8px 10px", f"text-align:{align}", "white-space:nowrap"]
                if color:    styles.append(f"color:{color}")
                if bold:     styles.append("font-weight:700")
                if muted:    styles.append("opacity:.65")
                style = ";".join(styles)
                text = content
                if small_sub:
                    text = f"{content} · {small_sub}"
                return f'<td style="{style}">{text}</td>'

            def td_delta(val, inverse=False):
                txt, color = _cd(val, inverse)
                return td(txt, color=color, bold=True)

            # Filas de datos
            rows_html = ""
            for _, r in tbl_cont.iterrows():
                bg, border, icon = alerta_cfg.get(r["Alerta"], ("#F8FAFC", "#94A3B8", "⚪"))
                rows_html += f'<tr style="border-left:4px solid {border};background:{bg};border-bottom:1px solid #F1F5F9;">'
                rows_html += td(f'{icon} {r["Canal"]}', align="left", bold=True)
                # VENTA
                rows_html += td(fmt_money(r["Venta KAM ($)"]))
                rows_html += td(fmt_money(r["Venta Contable ($)"]), muted=True)
                rows_html += td_delta(r["Δ Venta"])
                # MARGEN
                rows_html += td(fmt_money(r["Margen KAM ($)"]),
                                small_sub=_pct(r["% Margen KAM"]))
                rows_html += td(fmt_money(r["Margen Contable ($)"]),
                                small_sub=_pct(r["% Margen Cont"]), muted=True)
                rows_html += td_delta(r["Δ Margen"])
                # COMISIONES
                rows_html += td(fmt_money(r["Total Com. KAM ($)"]),
                                small_sub=_pct(r["% Com KAM"]))
                rows_html += td(fmt_money(r["Total Com. Cont. ($)"]),
                                small_sub=_pct(r["% Com Cont"]), muted=True)
                rows_html += td_delta(r["Δ Com"], inverse=True)
                # CONTRIBUCION
                rows_html += td(fmt_money(r["Contribución KAM ($)"]),
                                small_sub=_pct(r["% Contrib KAM"]), bold=True)
                rows_html += td(fmt_money(r["Contribución Cont. ($)"]),
                                small_sub=_pct(r["% Contrib Cont"]), muted=True)
                rows_html += td_delta(r["Δ Contrib"])
                rows_html += "</tr>"

            # Fila TOTAL
            def _tot(col): return tbl_cont[col].sum()
            tv  = _tot("Venta KAM ($)");       tvc  = _tot("Venta Contable ($)")
            tm  = _tot("Margen KAM ($)");      tmc  = _tot("Margen Contable ($)")
            tco = _tot("Total Com. KAM ($)");  tcoc = _tot("Total Com. Cont. ($)")
            tk  = _tot("Contribución KAM ($)"); tkc = _tot("Contribución Cont. ($)")

            def td_tot(content, muted=False, small_sub=""):
                sty = "padding:8px 10px;text-align:right;color:white;font-weight:700;white-space:nowrap"
                if muted: sty += ";opacity:.65"
                text = f"{content} · {small_sub}" if small_sub else content
                return f'<td style="{sty}">{text}</td>'

            def td_tot_delta(val, inverse=False):
                txt, color = _cd(val, inverse)
                return f'<td style="padding:8px 10px;text-align:right;color:{color};font-weight:700;white-space:nowrap;">{txt}</td>'

            rows_html += f"""
            <tr style="background:#1E293B;border-top:2px solid #334155;">
              <td style="padding:8px 10px;color:white;font-weight:700;letter-spacing:.5px;">TOTAL</td>
              {td_tot(fmt_money(tv))}
              {td_tot(fmt_money(tvc), muted=True)}
              {td_tot_delta(tv - tvc)}
              {td_tot(fmt_money(tm), small_sub=_pct(tm/tv*100 if tv else 0))}
              {td_tot(fmt_money(tmc), muted=True)}
              {td_tot_delta(tm - tmc)}
              {td_tot(fmt_money(tco), small_sub=_pct(tco/tv*100 if tv else 0))}
              {td_tot(fmt_money(tcoc), muted=True)}
              {td_tot_delta(tco - tcoc, inverse=True)}
              {td_tot(fmt_money(tk), small_sub=_pct(tk/tv*100 if tv else 0))}
              {td_tot(fmt_money(tkc), muted=True)}
              {td_tot_delta(tk - tkc)}
            </tr>"""

            hs  = "background:#1F4E79;color:white;font-size:.72rem;font-weight:700;padding:8px 10px;text-align:right;white-space:nowrap;letter-spacing:.3px;"
            hsl = "background:#1F4E79;color:white;font-size:.72rem;font-weight:700;padding:8px 10px;text-align:left;"
            gh  = "background:#0D1B2A;color:#94A3B8;font-size:.68rem;font-weight:700;text-align:center;letter-spacing:1px;padding:5px 8px;text-transform:uppercase;"

            full_html = f"""<!DOCTYPE html><html><head>
            <meta charset="utf-8">
            <style>
              body{{margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:transparent;}}
              .wrap{{overflow-x:auto;border-radius:10px;border:1px solid #E2E8F0;}}
              table{{width:100%;border-collapse:collapse;font-size:13px;}}
              tr:hover td{{background:rgba(31,78,121,.05)!important;}}
              .legend{{font-size:11px;color:#94A3B8;padding:6px 2px 0 2px;line-height:1.6;}}
            </style></head><body>
            <div class="wrap">
            <table>
              <thead>
                <tr>
                  <th rowspan="2" style="{hsl}">Canal</th>
                  <th colspan="3" style="{gh}">VENTA</th>
                  <th colspan="3" style="{gh}">MARGEN DIRECTO</th>
                  <th colspan="3" style="{gh}">COMISIONES</th>
                  <th colspan="3" style="{gh}">CONTRIBUCIÓN</th>
                </tr>
                <tr>
                  <th style="{hs}">KAM</th><th style="{hs}">Contable</th><th style="{hs}">Δ</th>
                  <th style="{hs}">KAM</th><th style="{hs}">Contable</th><th style="{hs}">Δ</th>
                  <th style="{hs}">KAM</th><th style="{hs}">Contable</th><th style="{hs}">Δ</th>
                  <th style="{hs}">KAM</th><th style="{hs}">Contable</th><th style="{hs}">Δ</th>
                </tr>
              </thead>
              <tbody>{rows_html}</tbody>
            </table>
            </div>
            <div class="legend">
              🟢 Alineado &nbsp;|&nbsp; 🟡 Dif. 5–20% &nbsp;|&nbsp;
              🔴 Dif. &gt;20% &nbsp;|&nbsp; ⚪ Sin datos contables &nbsp;|&nbsp;
              Δ <span style="color:#16A34A;font-weight:600;">verde</span> = favorable &nbsp;|&nbsp;
              Δ <span style="color:#DC2626;font-weight:600;">rojo</span> = desfavorable.
              Comisiones: verde = KAM pagó menos que contable (mejor).
              Valores con · muestran % sobre venta del mismo origen.
            </div>
            </body></html>"""

            row_h = 42
            table_h = len(tbl_cont) * row_h + 140  # header + legend
            components.html(full_html, height=table_h, scrolling=False)

            csv_kam_cont = tbl_cont.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Descargar CSV",
                csv_kam_cont,
                f"kam_{kam4}_comercial_vs_contable.csv",
                "text/csv",
                key="dl_kam_cont",
            )
        else:
            st.info(f"Sin datos contables para {kam4} en 2026 con los filtros actuales.")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Canales del KAM ────────────────────────────────────────────────
        st.markdown(f'<div class="section-header">Canales de {kam4} — detalle YoY</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)

        with c1:
            # Ranking canales por Contribución 2026
            ch4 = bi4.groupby("Canal").agg({
                "Venta 2025":"sum","Venta 2026":"sum",
                "Contribución 2025":"sum","Contribución 2026":"sum",
                "Total Com. 2026":"sum",
            }).reset_index()
            ch4 = ch4[ch4["Venta 2026"]>0].copy()
            ch4["% Contrib 26"] = (ch4["Contribución 2026"]/ch4["Venta 2026"]*100).round(1)
            ch4["Δ Venta %"]    = ((ch4["Venta 2026"]-ch4["Venta 2025"])/ch4["Venta 2025"].replace(0,np.nan)*100)
            ch4 = ch4.sort_values("Contribución 2026", ascending=True)

            fig_c1 = go.Figure()
            fig_c1.add_trace(go.Bar(y=ch4["Canal"], x=ch4["Contribución 2025"], name="2025",
                                     orientation="h", marker_color="#94A3B8", opacity=0.8))
            fig_c1.add_trace(go.Bar(y=ch4["Canal"], x=ch4["Contribución 2026"], name="2026",
                                     orientation="h", marker_color="#16A34A"))
            fig_c1.update_layout(title=f"Contribucion por Canal — {kam4}", barmode="overlay",
                                  height=max(300, len(ch4)*32+80),
                                  margin=dict(l=10,r=10,t=40,b=10),
                                  xaxis=dict(tickformat="$,.0s"),
                                  legend=dict(orientation="h",y=-0.08), plot_bgcolor="white")
            st.plotly_chart(fig_c1, use_container_width=True)

        with c2:
            # % Margen y % Contribucion por canal
            ch4_mg = bi4.groupby("Canal").agg({
                "Venta 2026":"sum","Margen 2026":"sum","Contribución 2026":"sum",
            }).reset_index()
            ch4_mg = ch4_mg[ch4_mg["Venta 2026"]>0].copy()
            ch4_mg["% Margen"]  = ch4_mg["Margen 2026"] / ch4_mg["Venta 2026"] * 100
            ch4_mg["% Contrib"] = ch4_mg["Contribución 2026"] / ch4_mg["Venta 2026"] * 100
            ch4_mg = ch4_mg.sort_values("Venta 2026", ascending=False).head(15)

            fig_c2 = go.Figure()
            fig_c2.add_trace(go.Bar(x=ch4_mg["Canal"], y=ch4_mg["% Margen"], name="% Margen", marker_color="#86EFAC"))
            fig_c2.add_trace(go.Bar(x=ch4_mg["Canal"], y=ch4_mg["% Contrib"], name="% Contribucion", marker_color="#1F4E79"))
            fig_c2.update_layout(title=f"Rentabilidad % por Canal — {kam4}", barmode="group",
                                  height=max(300, len(ch4_mg)*22+100),
                                  margin=dict(l=10,r=10,t=40,b=80),
                                  yaxis=dict(ticksuffix="%"),
                                  xaxis=dict(tickangle=-35),
                                  legend=dict(orientation="h",y=-0.35), plot_bgcolor="white")
            st.plotly_chart(fig_c2, use_container_width=True)

        # ── Evolucion mensual del KAM ──────────────────────────────────────
        st.markdown(f'<div class="section-header">Evolucion Mensual — {kam4}</div>', unsafe_allow_html=True)
        ev4 = bi4[bi4["Mes"]>0].groupby("Mes").agg({
            "Venta 2025":"sum","Venta 2026":"sum",
            "Contribución 2025":"sum","Contribución 2026":"sum",
        }).reset_index().sort_values("Mes")
        ev4["MesNombre"] = ev4["Mes"].map(MESES)

        fig_ev4 = go.Figure()
        fig_ev4.add_trace(go.Bar(x=ev4["MesNombre"], y=ev4["Venta 2025"], name="Venta 2025", marker_color="#94A3B8", opacity=0.85))
        fig_ev4.add_trace(go.Bar(x=ev4["MesNombre"], y=ev4["Venta 2026"], name="Venta 2026", marker_color="#1F4E79"))
        fig_ev4.add_trace(go.Scatter(x=ev4["MesNombre"], y=ev4["Contribución 2025"], name="Contrib 2025",
                                      mode="lines+markers", line=dict(color="#CBD5E1",width=2,dash="dot"), yaxis="y2"))
        fig_ev4.add_trace(go.Scatter(x=ev4["MesNombre"], y=ev4["Contribución 2026"], name="Contrib 2026",
                                      mode="lines+markers", line=dict(color="#16A34A",width=3), yaxis="y2"))
        fig_ev4.update_layout(barmode="group", height=320,
                               margin=dict(l=10,r=10,t=20,b=10),
                               yaxis=dict(title="Venta $", tickformat="$,.0s"),
                               yaxis2=dict(title="Contribucion $", overlaying="y", side="right", tickformat="$,.0s"),
                               legend=dict(orientation="h",y=-0.18), plot_bgcolor="white")
        st.plotly_chart(fig_ev4, use_container_width=True)

        # ── Contable del KAM ───────────────────────────────────────────────
        if len(cont4) > 0:
            st.markdown(f'<div class="section-header">Brechas Contables — {kam4}</div>', unsafe_allow_html=True)
            cont4_agg = cont4.groupby("Canal").agg({
                "Contribución KAM ($)":"sum","Contribución Cont. ($)":"sum","Δ Contribución ($)":"sum","Alerta":"first",
            }).reset_index().sort_values("Δ Contribución ($)", ascending=True)

            c3, c4_ = st.columns(2)
            with c3:
                fig_cont4 = go.Figure(go.Bar(
                    y=cont4_agg["Canal"], x=cont4_agg["Δ Contribución ($)"], orientation="h",
                    marker_color=["#16A34A" if v>=0 else "#DC2626" for v in cont4_agg["Δ Contribución ($)"]],
                    text=[f"{fmt_money(v)} ({r})" for v,r in zip(cont4_agg["Δ Contribución ($)"], cont4_agg["Alerta"])],
                    textposition="outside",
                ))
                fig_cont4.add_vline(x=0, line_color="#64748B", line_width=1)
                fig_cont4.update_layout(title=f"Δ Contribucion por Canal — {kam4}",
                                         height=max(300, len(cont4_agg)*30+80),
                                         showlegend=False,
                                         margin=dict(l=10,r=120,t=40,b=10),
                                         xaxis=dict(tickformat="$,.0s"), plot_bgcolor="white")
                st.plotly_chart(fig_cont4, use_container_width=True)

            with c4_:
                canales_sin = cont4[cont4["Alerta"].isin(["SIN CONTABLE","SIN DATOS","SIN KAM"])]["Canal"].unique().tolist()
                canales_dif = cont4[cont4["Alerta"].isin(["DIF >20%","DIF 5-20%"])]["Canal"].unique().tolist()
                canales_ok  = cont4[cont4["Alerta"]=="ALINEADO"]["Canal"].unique().tolist()
                st.markdown(f"""
                <div style='padding:12px;background:white;border-radius:10px;border:1px solid #E2E8F0;'>
                  <div style='font-weight:700;color:#1E293B;margin-bottom:8px;'>Estado de canales de {kam4}</div>
                  <div style='font-size:.82rem;margin-bottom:6px;'><span style='color:#16A34A;font-weight:700;'>✓ Alineados ({len(canales_ok)}):</span><br>
                    {', '.join(canales_ok) if canales_ok else '—'}</div>
                  <div style='font-size:.82rem;margin-bottom:6px;'><span style='color:#CA8A04;font-weight:700;'>⚠ Con diferencia ({len(canales_dif)}):</span><br>
                    {', '.join(canales_dif) if canales_dif else '—'}</div>
                  <div style='font-size:.82rem;'><span style='color:#DC2626;font-weight:700;'>✗ Sin conciliar ({len(canales_sin)}):</span><br>
                    {', '.join(canales_sin) if canales_sin else '—'}</div>
                </div>
                """, unsafe_allow_html=True)

        # Tabla resumen canales
        st.markdown(f'<div class="section-header">Tabla Resumen de Canales — {kam4}</div>', unsafe_allow_html=True)
        resumen_canales = bi4.groupby("Canal").agg({
            "Venta 2025":"sum","Venta 2026":"sum",
            "Margen 2026":"sum","Total Com. 2026":"sum","Contribución 2026":"sum","Contribución 2025":"sum",
        }).reset_index()
        resumen_canales = resumen_canales[resumen_canales["Venta 2026"]>0].copy()
        resumen_canales["% Contrib 26"] = (resumen_canales["Contribución 2026"]/resumen_canales["Venta 2026"]*100).round(1)
        resumen_canales["Δ Venta %"]    = ((resumen_canales["Venta 2026"]-resumen_canales["Venta 2025"]) / resumen_canales["Venta 2025"].replace(0,np.nan)*100).round(1)
        resumen_canales = resumen_canales.sort_values("Venta 2026", ascending=False)
        st.dataframe(resumen_canales, use_container_width=True, height=300, hide_index=True,
                     column_config={
                         "Venta 2025": st.column_config.NumberColumn(format="$%d"),
                         "Venta 2026": st.column_config.NumberColumn(format="$%d"),
                         "Margen 2026": st.column_config.NumberColumn(format="$%d"),
                         "Total Com. 2026": st.column_config.NumberColumn(format="$%d"),
                         "Contribución 2026": st.column_config.NumberColumn(format="$%d"),
                         "Contribución 2025": st.column_config.NumberColumn(format="$%d"),
                         "% Contrib 26": st.column_config.NumberColumn(format="%.1f%%"),
                         "Δ Venta %": st.column_config.NumberColumn(format="%.1f%%"),
                     })


# ════════════════════════════════════════════════════════════════════════════
# TAB 5 — OPORTUNIDADES (análisis profesional mismo período)
# ════════════════════════════════════════════════════════════════════════════
with tab5:
    # ── Datos mismo período ────────────────────────────────────────────────────
    bi_op   = apply_filters(bi_raw,   has_year=False)
    cont_op = apply_filters(cont_raw, has_year=False)
    cont_op = cont_op[cont_op["Año"].astype(str).str.strip() == "2026"]
    pres_op = apply_filters(pres_raw, has_year=False)
    pres_op = pres_op[pres_op["Año"].astype(str).str.strip() == "2026"]

    canal_sp, neg_sp, _, _ = compute_canal_metrics(bi_op)
    canal_sp = canal_sp[canal_sp["Venta 2026"] > 0].copy()

    # ── Contexto ───────────────────────────────────────────────────────────────
    st.info(
        f"**Comparación mismo período: {_periodo_str} 2025 vs {_periodo_str} 2026.** "
        "Se excluyen meses sin datos 2026 para que los deltas sean comparables."
    )

    # Totales del período
    tv26 = canal_sp["Venta 2026"].sum();          tv25 = canal_sp["Venta 2025"].sum()
    tk26 = canal_sp["Contribución 2026"].sum();   tk25 = canal_sp["Contribución 2025"].sum()
    tc26 = canal_sp["Total Com. 2026"].sum();     tc25 = canal_sp["Total Com. 2025"].sum()
    tm26 = canal_sp["Margen 2026"].sum();         tm25 = canal_sp["Margen 2025"].sum()
    dv_t = (tv26 - tv25) / tv25 * 100 if tv25 else 0
    dk_t = (tk26 - tk25) / tk25 * 100 if tk25 else 0
    pct_m26 = tm26 / tv26 * 100 if tv26 else 0
    pct_m25 = tm25 / tv25 * 100 if tv25 else 0
    pct_c26 = tc26 / tv26 * 100 if tv26 else 0
    pct_c25 = tc25 / tv25 * 100 if tv25 else 0

    # ── Resumen ejecutivo ──────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Resumen Ejecutivo del Período</div>', unsafe_allow_html=True)
    c0 = st.columns(5)
    kpi_card(c0[0], "Venta acumulada",    fmt_money(tv26),
             f"{dv_t:+.1f}% vs mismo per. 2025", sign_color(dv_t))
    kpi_card(c0[1], "Margen directo",     fmt_money(tm26),
             f"{pct_m26:.1f}% s/v ({pct_m26-pct_m25:+.1f}pp)", sign_color(pct_m26 - pct_m25))
    kpi_card(c0[2], "Comisiones totales", fmt_money(tc26),
             f"{pct_c26:.1f}% s/v ({pct_c26-pct_c25:+.1f}pp)", sign_color(-(pct_c26 - pct_c25)))
    kpi_card(c0[3], "Contribucion",       fmt_money(tk26),
             f"{tk26/tv26*100:.1f}% s/v ({dk_t:+.1f}%)", sign_color(dk_t))
    n_alertas = len(canal_sp[canal_sp["Semaforo"].str.startswith("🔴")])
    n_buenos  = len(canal_sp[canal_sp["Semaforo"].str.startswith("🟢")])
    kpi_card(c0[4], "Canales activos", str(len(canal_sp)),
             f"🟢 {n_buenos}  🔴 {n_alertas}", "blue")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Scorecard de canales ───────────────────────────────────────────────────
    st.markdown('<div class="section-header">Scorecard de Canales — Visión Integral</div>', unsafe_allow_html=True)
    st.caption("Todos los canales activos ordenados por Venta 2026. Barras de progreso = nivel absoluto.")

    sc = canal_sp.sort_values("Venta 2026", ascending=False).copy()
    sc_show = sc[["Canal","Negocio","% Margen 26","Δ Margen pp",
                  "% Com 26","Δ Com pp","% Contrib 26","Δ Contrib pp",
                  "Δ Venta %","Semaforo"]].copy()
    sc_show["Venta 2026"] = sc["Venta 2026"]
    sc_show = sc_show[["Canal","Negocio","Venta 2026","Δ Venta %",
                        "% Margen 26","Δ Margen pp","% Com 26","Δ Com pp",
                        "% Contrib 26","Δ Contrib pp","Semaforo"]]
    for col_r in ["Δ Venta %","Δ Margen pp","Δ Com pp","Δ Contrib pp"]:
        sc_show[col_r] = sc_show[col_r].round(1)
    for col_r in ["% Margen 26","% Com 26","% Contrib 26"]:
        sc_show[col_r] = sc_show[col_r].round(1)

    st.dataframe(
        sc_show, use_container_width=True, height=420, hide_index=True,
        column_config={
            "Venta 2026":   st.column_config.NumberColumn("Venta 2026", format="$%d"),
            "Δ Venta %":    st.column_config.NumberColumn("Δ Venta %",    format="%+.1f%%"),
            "% Margen 26":  st.column_config.ProgressColumn("Margen%",   min_value=0, max_value=80, format="%.1f%%"),
            "Δ Margen pp":  st.column_config.NumberColumn("Δ Margen pp",  format="%+.1fpp"),
            "% Com 26":     st.column_config.ProgressColumn("Com%",       min_value=0, max_value=50, format="%.1f%%"),
            "Δ Com pp":     st.column_config.NumberColumn("Δ Com pp",     format="%+.1fpp"),
            "% Contrib 26": st.column_config.ProgressColumn("Contrib%",   min_value=0, max_value=60, format="%.1f%%"),
            "Δ Contrib pp": st.column_config.NumberColumn("Δ Contrib pp", format="%+.1fpp"),
            "Semaforo":     st.column_config.TextColumn("Estado", width="small"),
        },
    )
    csv_sc = sc_show.to_csv(index=False).encode("utf-8-sig")
    st.download_button("Descargar Scorecard CSV", csv_sc, "scorecard_canales.csv", "text/csv", key="dl_sc")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Análisis por Línea de Negocio ──────────────────────────────────────────
    st.markdown('<div class="section-header">Análisis por Línea de Negocio</div>', unsafe_allow_html=True)
    neg_filt = neg_sp[neg_sp["Venta 2026"] > 0].copy()

    cn1, cn2 = st.columns(2)
    with cn1:
        neg_s = neg_filt.sort_values("Δ Venta %", ascending=True)
        colors_neg = ["#16A34A" if v >= 0 else "#DC2626" for v in neg_s["Δ Venta %"]]
        fig_neg = go.Figure(go.Bar(
            y=neg_s["Negocio"], x=neg_s["Δ Venta %"], orientation="h",
            marker_color=colors_neg,
            text=[f"{v:+.1f}%" for v in neg_s["Δ Venta %"]],
            textposition="outside",
        ))
        fig_neg.add_vline(x=0, line_color="#64748B", line_width=1)
        fig_neg.update_layout(title=f"Δ Venta % por Negocio ({_periodo_str} YoY)",
                               height=320, showlegend=False,
                               margin=dict(l=10,r=70,t=40,b=10),
                               xaxis=dict(ticksuffix="%"), plot_bgcolor="white")
        st.plotly_chart(fig_neg, use_container_width=True)

    with cn2:
        neg_s2 = neg_filt.sort_values("Δ Contrib pp", ascending=True)
        colors_neg2 = ["#16A34A" if v >= 0 else "#DC2626" for v in neg_s2["Δ Contrib pp"]]
        fig_neg2 = go.Figure(go.Bar(
            y=neg_s2["Negocio"], x=neg_s2["Δ Contrib pp"], orientation="h",
            marker_color=colors_neg2,
            text=[f"{v:+.1f}pp" for v in neg_s2["Δ Contrib pp"]],
            textposition="outside",
        ))
        fig_neg2.add_vline(x=0, line_color="#64748B", line_width=1)
        fig_neg2.update_layout(title=f"Δ Contribución pp por Negocio ({_periodo_str} YoY)",
                                height=320, showlegend=False,
                                margin=dict(l=10,r=70,t=40,b=10),
                                xaxis=dict(ticksuffix="pp"), plot_bgcolor="white")
        st.plotly_chart(fig_neg2, use_container_width=True)

    # Cards insight por negocio (top 3 más interesantes: mayor spread)
    neg_sorted = neg_filt.copy()
    neg_sorted["abs_delta"] = neg_sorted["Δ Contrib pp"].abs()
    neg_sorted = neg_sorted.sort_values("abs_delta", ascending=False)
    cols_neg = st.columns(min(len(neg_sorted), 3))
    for i, (_, row) in enumerate(neg_sorted.iterrows()):
        if i >= 3: break
        tipo = "red" if row["Δ Contrib pp"] < -5 else "yellow" if row["Δ Contrib pp"] < 0 else "green"
        av = "↑" if row["Δ Venta %"] >= 0 else "↓"
        ak = "↑" if row["Δ Contrib pp"] >= 0 else "↓"
        insight_card(
            cols_neg[i],
            f"{row['Negocio']} — {av}{abs(row['Δ Venta %']):.1f}% venta | {ak}{abs(row['Δ Contrib pp']):.1f}pp contrib",
            (f"Venta: {fmt_money(row['Venta 2026'])} | Margen: {row['% Margen 26']:.1f}%"
             f" ({row['Δ Margen pp']:+.1f}pp) | Comis: {row['% Com 26']:.1f}%"
             f" ({row['Δ Com pp']:+.1f}pp) | Contrib: {row['% Contrib 26']:.1f}%"),
            tipo,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Cuadrante Estratégico ──────────────────────────────────────────────────
    st.markdown('<div class="section-header">Cuadrante Estratégico — Crecimiento vs Rentabilidad</div>', unsafe_allow_html=True)
    st.caption(f"Canales con Venta >$500K en {_periodo_str} 2026. Azul = comisiones bajaron (bueno). Rojo = comisiones subieron.")

    cq1, cq2 = st.columns([3, 1])
    with cq1:
        canal_plot = canal_sp.dropna(subset=["Δ Venta %", "Δ Contrib pp"]).copy()
        canal_plot = canal_plot[canal_plot["Venta 2026"] > 5e5]

        fig_q = go.Figure()
        for _, row in canal_plot.iterrows():
            color = "#1F4E79" if row["Δ Com pp"] <= 0 else "#DC2626"
            size  = max(10, min(55, float(row["Venta 2026"]) / 3e6))
            show_label = row["Venta 2026"] > 1.5e7
            fig_q.add_trace(go.Scatter(
                x=[row["Δ Venta %"]], y=[row["Δ Contrib pp"]],
                mode="markers+text" if show_label else "markers",
                marker=dict(size=size, color=color, opacity=0.82,
                            line=dict(width=1.5, color="white")),
                text=[row["Canal"]] if show_label else [],
                textposition="top center", textfont=dict(size=9),
                hovertemplate=(
                    f"<b>{row['Canal']}</b> ({row['Negocio']})<br>"
                    f"Δ Venta: {row['Δ Venta %']:+.1f}%<br>"
                    f"Δ Contrib: {row['Δ Contrib pp']:+.1f}pp → {row['% Contrib 26']:.1f}%<br>"
                    f"Margen: {row['% Margen 26']:.1f}% ({row['Δ Margen pp']:+.1f}pp)<br>"
                    f"Comis: {row['% Com 26']:.1f}% ({row['Δ Com pp']:+.1f}pp)<br>"
                    f"Venta: {fmt_money(row['Venta 2026'])}<extra></extra>"
                ),
                name=row["Canal"], showlegend=False,
            ))

        fig_q.add_vline(x=0, line_color="#CBD5E1", line_width=1.5, line_dash="dash")
        fig_q.add_hline(y=0, line_color="#CBD5E1", line_width=1.5, line_dash="dash")

        xr = max(canal_plot["Δ Venta %"].abs().quantile(0.9) * 1.3, 30) if len(canal_plot) else 50
        yr = max(canal_plot["Δ Contrib pp"].abs().quantile(0.9) * 1.3, 10) if len(canal_plot) else 20

        quadrants = [
            ( xr*0.55,  yr*0.70, "ESTRELLAS ✓\nCrece + mejora rentabilidad",  "#F0FDF4"),
            (-xr*0.75,  yr*0.70, "EFICIENTES\nBaja venta, sube margen",        "#EFF6FF"),
            ( xr*0.55, -yr*0.70, "VOLUMEN ⚠\nCrece pero comprime margen",      "#FEFCE8"),
            (-xr*0.75, -yr*0.70, "CRÍTICOS ✗\nBaja venta y rentabilidad",      "#FEF2F2"),
        ]
        for tx, ty, label, bg in quadrants:
            fig_q.add_annotation(x=tx, y=ty, text=label, showarrow=False, align="center",
                                  font=dict(size=10, color="#475569"), bgcolor=bg,
                                  bordercolor="#E2E8F0", borderwidth=1, borderpad=5)

        fig_q.add_annotation(x=0, y=yr * 1.08,
                               text="🔵 Comis bajaron  🔴 Comis subieron",
                               showarrow=False, font=dict(size=10, color="#64748B"))
        fig_q.update_layout(
            height=460, margin=dict(l=10, r=10, t=30, b=10),
            xaxis=dict(title="Δ Venta % (mismo período YoY)", ticksuffix="%", zeroline=False),
            yaxis=dict(title="Δ Contribución pp", ticksuffix="pp", zeroline=False),
            plot_bgcolor="white",
        )
        st.plotly_chart(fig_q, use_container_width=True)

    with cq2:
        st.markdown("**Watchlist — zona crítica:**")
        criticos = canal_sp[
            (canal_sp["Δ Contrib pp"] < -3) | (canal_sp["Δ Com pp"] > 3)
        ].sort_values("Venta 2026", ascending=False)
        if len(criticos) == 0:
            st.success("Sin canales en zona crítica.")
        for _, row in criticos.head(8).iterrows():
            problemas = []
            if row["Δ Contrib pp"] < -3:  problemas.append(f"Contrib {row['Δ Contrib pp']:+.1f}pp")
            if row["Δ Com pp"] > 3:       problemas.append(f"Com +{row['Δ Com pp']:.1f}pp")
            if row["Δ Venta %"] < -15:    problemas.append(f"Venta {row['Δ Venta %']:+.1f}%")
            st.markdown(f"""
            <div style='background:#FEF2F2;border-radius:8px;padding:8px 12px;margin-bottom:6px;
                        border-left:3px solid #DC2626;'>
              <div style='font-weight:700;font-size:.82rem;'>{row['Canal']}</div>
              <div style='font-size:.74rem;color:#64748B;'>{row['Negocio']}<br>{" | ".join(problemas)}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("**Zona ESTRELLAS:**")
        estrellas = canal_sp[
            (canal_sp["Δ Venta %"] > 5) & (canal_sp["Δ Contrib pp"] > 1)
        ].sort_values("Venta 2026", ascending=False)
        if len(estrellas) == 0:
            st.info("Ningún canal en zona estrellas con los filtros actuales.")
        for _, row in estrellas.head(5).iterrows():
            st.markdown(f"""
            <div style='background:#F0FDF4;border-radius:8px;padding:8px 12px;margin-bottom:6px;
                        border-left:3px solid #16A34A;'>
              <div style='font-weight:700;font-size:.82rem;'>{row['Canal']}</div>
              <div style='font-size:.74rem;color:#64748B;'>Venta {row['Δ Venta %']:+.1f}% | Contrib {row['Δ Contrib pp']:+.1f}pp</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Presión de comisiones ──────────────────────────────────────────────────
    st.markdown('<div class="section-header">Estructura de Comisiones — ¿Dónde sube el costo comercial?</div>', unsafe_allow_html=True)
    com_data = canal_sp[canal_sp["Venta 2026"] > 2e6].sort_values("% Com 26", ascending=False).copy()

    cc1, cc2 = st.columns(2)
    with cc1:
        fig_com = go.Figure()
        fig_com.add_trace(go.Bar(x=com_data["Canal"], y=com_data["% Com 25"],
                                  name="Com% 2025", marker_color="#CBD5E1", opacity=0.9))
        fig_com.add_trace(go.Bar(x=com_data["Canal"], y=com_data["% Com 26"],
                                  name="Com% 2026", marker_color="#F97316"))
        fig_com.update_layout(title="% Comisiones / Venta — 2025 vs 2026",
                               barmode="group", height=360,
                               margin=dict(l=10,r=10,t=40,b=80),
                               yaxis=dict(title="%", ticksuffix="%"),
                               xaxis=dict(tickangle=-40),
                               legend=dict(orientation="h", y=-0.35),
                               plot_bgcolor="white")
        st.plotly_chart(fig_com, use_container_width=True)

    with cc2:
        delta_com = canal_sp[canal_sp["Venta 2026"] > 2e6].sort_values("Δ Com pp", ascending=False)
        colors_dc = ["#DC2626" if v > 0 else "#16A34A" for v in delta_com["Δ Com pp"]]
        fig_dcom = go.Figure(go.Bar(
            x=delta_com["Canal"], y=delta_com["Δ Com pp"],
            marker_color=colors_dc,
            text=[f"{v:+.1f}pp" for v in delta_com["Δ Com pp"]],
            textposition="outside",
        ))
        fig_dcom.add_hline(y=0, line_color="#64748B", line_width=1)
        fig_dcom.update_layout(title="Δ Comisiones pp (rojo = subieron, verde = bajaron)",
                                height=360, showlegend=False,
                                margin=dict(l=10,r=10,t=40,b=80),
                                yaxis=dict(ticksuffix="pp"),
                                xaxis=dict(tickangle=-40),
                                plot_bgcolor="white")
        st.plotly_chart(fig_dcom, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Cross-selling: disparidad de rentabilidad ──────────────────────────────
    st.markdown('<div class="section-header">Oportunidad Cross-Selling — Mismo catálogo, distinta rentabilidad</div>', unsafe_allow_html=True)
    st.caption("Dentro del mismo Negocio hay canales muy rentables y otros poco rentables. Spread alto = oportunidad de replicar el modelo ganador.")

    cx1, cx2 = st.columns([3, 2])
    with cx1:
        canal_plot2 = canal_sp[canal_sp["% Contrib 26"].between(-20, 80)].copy()
        fig_cross = px.strip(
            canal_plot2, x="Negocio", y="% Contrib 26",
            color="Negocio", hover_name="Canal",
            hover_data={"Venta 2026": ":$,.0f", "% Contrib 26": ":.1f", "% Com 26": ":.1f"},
            labels={"% Contrib 26": "% Contribución 2026"},
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_cross.add_hline(y=0, line_dash="dash", line_color="#DC2626", line_width=1)
        fig_cross.update_traces(jitter=0.4, marker=dict(size=10, opacity=0.75))
        fig_cross.update_layout(title="% Contribución por canal dentro de cada negocio",
                                  height=400, showlegend=False,
                                  margin=dict(l=10,r=10,t=40,b=10),
                                  yaxis=dict(ticksuffix="%"), plot_bgcolor="white")
        st.plotly_chart(fig_cross, use_container_width=True)

    with cx2:
        neg_disp = canal_sp.groupby("Negocio")["% Contrib 26"].agg(
            Min="min", Max="max", Promedio="mean",
            Spread=lambda x: x.max() - x.min()
        ).reset_index().sort_values("Spread", ascending=False)

        st.markdown("**Spread de rentabilidad por negocio:**")
        for _, row in neg_disp.iterrows():
            spread = row["Spread"]
            color  = "#DC2626" if spread > 20 else "#CA8A04" if spread > 10 else "#16A34A"
            grp    = canal_sp[canal_sp["Negocio"] == row["Negocio"]]
            best   = grp.loc[grp["% Contrib 26"].idxmax(), "Canal"] if len(grp) else "—"
            worst  = grp.loc[grp["% Contrib 26"].idxmin(), "Canal"] if len(grp) else "—"
            st.markdown(f"""
            <div style='background:white;border-radius:8px;padding:10px 14px;margin-bottom:8px;
                        border:1px solid #E2E8F0;border-left:4px solid {color};'>
              <div style='font-weight:700;font-size:.85rem;color:#1E293B;'>{row["Negocio"]}</div>
              <div style='font-size:.76rem;color:#475569;margin-top:3px;'>
                Spread: <b>{spread:.1f}pp</b> &nbsp;|&nbsp; Prom: {row['Promedio']:.1f}%<br>
                ✓ Mejor: <b>{best}</b> ({grp['% Contrib 26'].max():.1f}%)<br>
                ✗ Peor:&nbsp; <b>{worst}</b> ({grp['% Contrib 26'].min():.1f}%)
              </div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Brechas contables ──────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Brechas Contables — Foco de Conciliación</div>', unsafe_allow_html=True)

    if "Alerta" in cont_op.columns and len(cont_op) > 0:
        alerta_res = cont_op.groupby("Alerta").agg(
            n=("Canal", "count"), delta=("Δ Contribución ($)", "sum")
        ).reset_index()
        cont_dif = cont_op[cont_op["Alerta"].isin(["DIF >20%", "DIF 5-20%"])]

        cb1, cb2 = st.columns([2, 1])
        with cb1:
            if len(cont_dif) > 0:
                dif_a = cont_dif.groupby(["Canal", "Alerta"]).agg({
                    "Contribución KAM ($)": "sum",
                    "Contribución Cont. ($)": "sum",
                    "Δ Contribución ($)": "sum",
                }).reset_index().sort_values("Δ Contribución ($)", key=abs, ascending=False).head(15)
                fig_b = go.Figure()
                for at, grp in dif_a.groupby("Alerta"):
                    fig_b.add_trace(go.Bar(
                        y=grp["Canal"], x=grp["Δ Contribución ($)"], orientation="h",
                        name=at,
                        marker_color="#DC2626" if at == "DIF >20%" else "#F59E0B",
                        text=[fmt_money(v) for v in grp["Δ Contribución ($)"]],
                        textposition="outside",
                    ))
                fig_b.add_vline(x=0, line_color="#64748B", line_width=1)
                fig_b.update_layout(title="Δ Contribución KAM − Contable",
                                     height=max(300, len(dif_a) * 28 + 80),
                                     margin=dict(l=10, r=80, t=40, b=10),
                                     xaxis=dict(tickformat="$,.0s"),
                                     legend=dict(orientation="h", y=-0.1),
                                     plot_bgcolor="white")
                st.plotly_chart(fig_b, use_container_width=True)
            else:
                st.success("Sin canales con diferencias contables >5% en el período filtrado.")

        with cb2:
            alerta_color_map = {
                "ALINEADO": "#16A34A", "DIF 5-20%": "#F59E0B", "DIF >20%": "#DC2626",
                "SIN CONTABLE": "#94A3B8", "SIN DATOS": "#CBD5E1", "SIN KAM": "#64748B",
            }
            st.markdown("**Estado de conciliación:**")
            for _, row in alerta_res.sort_values("n", ascending=False).iterrows():
                col_a = alerta_color_map.get(row["Alerta"], "#94A3B8")
                st.markdown(f"""
                <div style='display:flex;justify-content:space-between;align-items:center;
                            background:white;border-radius:8px;padding:8px 12px;margin-bottom:6px;
                            border:1px solid #E2E8F0;border-left:4px solid {col_a};'>
                  <div style='font-weight:700;font-size:.82rem;'>{row["Alerta"]}</div>
                  <div style='font-size:.76rem;color:#64748B;'>{int(row["n"])} filas | {fmt_money(row["delta"])}</div>
                </div>""", unsafe_allow_html=True)
            st.caption("Prioridad: DIF >20% y DIF 5-20% coordinando con contabilidad.")
    else:
        st.info("Sin datos de conciliación para el período filtrado.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Concentración Pareto ───────────────────────────────────────────────────
    st.markdown('<div class="section-header">Concentración de Ingresos — Riesgo de Dependencia</div>', unsafe_allow_html=True)

    canal_pareto = canal_sp.sort_values("Venta 2026", ascending=False).copy()
    total_venta_op = canal_pareto["Venta 2026"].sum()
    if total_venta_op > 0:
        canal_pareto["Acum%"] = canal_pareto["Venta 2026"].cumsum() / total_venta_op * 100
    else:
        canal_pareto["Acum%"] = 0
    top5_pct = canal_pareto.head(5)["Venta 2026"].sum() / total_venta_op * 100 if total_venta_op else 0

    cp1, cp2 = st.columns([3, 1])
    with cp1:
        curva = canal_pareto.head(20).copy()
        curva["% Venta"] = curva["Venta 2026"] / total_venta_op * 100 if total_venta_op else 0
        fig_par = go.Figure()
        fig_par.add_trace(go.Bar(x=curva["Canal"], y=curva["% Venta"],
                                  marker_color="#1F4E79", opacity=0.85, name="% Venta"))
        fig_par.add_trace(go.Scatter(x=curva["Canal"], y=curva["Acum%"],
                                      mode="lines+markers", name="% Acumulado",
                                      line=dict(color="#DC2626", width=2.5), yaxis="y2"))
        fig_par.add_hline(y=80, line_dash="dot", line_color="#CA8A04", yref="y2",
                           annotation_text="80% acumulado", annotation_position="bottom right")
        fig_par.update_layout(title="Curva de Pareto — Top 20 canales",
                               height=380, margin=dict(l=10, r=10, t=40, b=80),
                               xaxis=dict(tickangle=-40),
                               yaxis=dict(title="% Venta", ticksuffix="%"),
                               yaxis2=dict(title="% Acum", overlaying="y", side="right", ticksuffix="%"),
                               legend=dict(orientation="h", y=-0.35), plot_bgcolor="white")
        st.plotly_chart(fig_par, use_container_width=True)

    with cp2:
        st.markdown("**Top 5 canales:**")
        for i, (_, row) in enumerate(canal_pareto.head(5).iterrows(), 1):
            pct = row["Venta 2026"] / total_venta_op * 100 if total_venta_op else 0
            st.markdown(f"""
            <div style='background:white;border-radius:8px;padding:10px 14px;margin-bottom:8px;
                        border:1px solid #E2E8F0;border-left:4px solid #1F4E79;'>
              <div style='font-size:.72rem;color:#94A3B8;'>#{i} {row["Negocio"]}</div>
              <div style='font-weight:700;font-size:.85rem;'>{row["Canal"]}</div>
              <div style='font-size:.76rem;color:#475569;margin-top:2px;'>
                {fmt_money(row["Venta 2026"])} · <b>{pct:.1f}%</b><br>
                Contrib {row["% Contrib 26"]:.1f}% | Δ Venta {row["Δ Venta %"]:+.1f}%
              </div>
            </div>""", unsafe_allow_html=True)
        riesgo = "ALTO" if top5_pct > 60 else "MODERADO" if top5_pct > 45 else "BAJO"
        col_r  = "#DC2626" if top5_pct > 60 else "#CA8A04" if top5_pct > 45 else "#16A34A"
        st.markdown(f"""
        <div style='background:white;border-radius:8px;padding:12px 14px;border:2px solid {col_r};
                    margin-top:8px;text-align:center;'>
          <div style='font-size:.75rem;color:#64748B;'>Riesgo concentración</div>
          <div style='font-size:1.4rem;font-weight:700;color:{col_r};'>{riesgo}</div>
          <div style='font-size:.78rem;color:#475569;'>Top 5 = {top5_pct:.0f}% ingresos</div>
        </div>""", unsafe_allow_html=True)



# ── TAB 6: ADMINISTRACIÓN ────────────────────────────────────────────────────
with tab6:
    _sess_user  = st.session_state.get("username", "")
    # Roles desde auth_config.yaml (single source of truth)
    try:
        from auth_helper import get_user_roles, has_role, has_any_role
        _roles = get_user_roles(_sess_user)
        _is_admin   = has_role(_roles, "admin")
        _can_upload = has_any_role(_roles, ["admin", "uploader"])
    except Exception:
        # Fallback hardcoded por si auth_helper no esta disponible
        _is_admin   = _sess_user in ("andres",)
        _can_upload = _sess_user in ("andres", "gabriela")

    if not _can_upload:
        st.markdown("""
        <div style='text-align:center;padding:80px 20px;'>
          <div style='font-size:3.5rem;'>🔒</div>
          <div style='font-size:1.15rem;font-weight:700;color:#1E293B;margin-top:14px;'>Acceso restringido</div>
          <div style='font-size:.88rem;color:#64748B;margin-top:6px;'>
            Esta sección es solo para administradores.<br>Iniciá sesión con una cuenta con permisos de admin.
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("#### Carga mensual de datos")
        st.caption(
            "Subí el Excel actualizado cada mes. El sistema respalda el archivo anterior "
            "automáticamente y el dashboard se actualiza al instante."
        )

        # ── Archivo actual ──────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("**Archivo activo**")

        if os.path.exists(XLSX_PATH):
            _fsize  = os.path.getsize(XLSX_PATH)
            _fmtime = datetime.fromtimestamp(os.path.getmtime(XLSX_PATH)).strftime("%d/%m/%Y %H:%M")
            _fname  = os.path.basename(XLSX_PATH)
            st.markdown(f"""
            <div style='background:white;border-radius:10px;padding:14px 18px;
                        border:1px solid #E2E8F0;display:flex;align-items:center;gap:18px;'>
              <div style='font-size:2.2rem;'>📄</div>
              <div>
                <div style='font-weight:700;color:#1E293B;font-size:.92rem;'>{_fname}</div>
                <div style='font-size:.78rem;color:#64748B;margin-top:4px;'>
                  {_fsize/1024:.0f} KB &nbsp;·&nbsp; Última modificación: {_fmtime}
                </div>
              </div>
            </div>""", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            with open(XLSX_PATH, "rb") as _f:
                st.download_button(
                    "⬇️ Descargar archivo actual",
                    _f.read(),
                    _fname,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_current",
                )
        else:
            st.error(f"Archivo no encontrado: `{XLSX_PATH}`")

        # ── Subir nueva versión ─────────────────────────────────────────────
        st.markdown("---")
        st.markdown("**Subir nueva versión**")
        st.caption(
            "Arrastrá o seleccioná el Excel. "
            "El archivo debe tener las hojas: **BI Comercial**, **Resultado vs Presupuesto**, **Comercial vs Contable**."
        )

        _uploaded = st.file_uploader(
            "Seleccioná el archivo Excel (.xlsx)",
            type=["xlsx"],
            key="admin_uploader",
        )

        if _uploaded is not None:
            _up_size = _uploaded.size / 1024
            st.success(f"Listo para cargar: **{_uploaded.name}** — {_up_size:.0f} KB")

            _col_btn, _col_warn = st.columns([1, 3])
            with _col_btn:
                _confirmar = st.button("✅ Confirmar y reemplazar", type="primary")
            with _col_warn:
                st.warning("Esto reemplazará el archivo activo. El anterior quedará respaldado.")

            if _confirmar:
                try:
                    # 1. Crear directorio de backups
                    os.makedirs(BACKUP_DIR, exist_ok=True)

                    # 2. Respaldar archivo actual
                    if os.path.exists(XLSX_PATH):
                        _ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
                        _base_name   = os.path.splitext(os.path.basename(XLSX_PATH))[0]
                        _backup_name = f"{_base_name}_{_ts}.xlsx"
                        _backup_path = os.path.join(BACKUP_DIR, _backup_name)
                        with open(XLSX_PATH, "rb") as _f_old, open(_backup_path, "wb") as _f_bak:
                            _f_bak.write(_f_old.read())

                    # 3. Guardar nuevo archivo
                    _bytes = _uploaded.read()
                    with open(XLSX_PATH, "wb") as _f_new:
                        _f_new.write(_bytes)

                    # 4. Invalidar caches
                    load_all.clear()
                    compute_canal_metrics.clear()

                    st.success(
                        f"Archivo actualizado exitosamente. "
                        f"Respaldo guardado como `{_backup_name}`."
                    )
                    st.rerun()

                except Exception as _e:
                    st.error(f"Error al guardar el archivo: {_e}")

        # ── Historial de versiones ──────────────────────────────────────────
        st.markdown("---")
        st.markdown("**Historial de versiones (últimas 10)**")

        _backups = []
        if os.path.exists(BACKUP_DIR):
            _backups = sorted(
                [f for f in os.listdir(BACKUP_DIR) if f.endswith(".xlsx")],
                reverse=True,
            )[:10]

        if _backups:
            for _i, _bname in enumerate(_backups):
                _bpath  = os.path.join(BACKUP_DIR, _bname)
                _bsize  = os.path.getsize(_bpath) / 1024
                _bmtime = datetime.fromtimestamp(os.path.getmtime(_bpath)).strftime("%d/%m/%Y %H:%M")
                _bc1, _bc2, _bc3 = st.columns([4, 2, 1])
                with _bc1:
                    st.markdown(
                        f"<span style='font-size:.82rem;color:#475569;'>{_bname}</span>",
                        unsafe_allow_html=True,
                    )
                with _bc2:
                    st.caption(f"{_bsize:.0f} KB · {_bmtime}")
                with _bc3:
                    with open(_bpath, "rb") as _fb:
                        st.download_button(
                            "⬇️",
                            _fb.read(),
                            _bname,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_bak_{_i}",
                            help=f"Descargar {_bname}",
                        )
        else:
            st.info("Sin versiones anteriores todavía. Aparecerán aquí después de la primera carga.")

        # ── Notificar carga al equipo ──────────────────────────────────────
        st.markdown("---")
        st.markdown("**📤 Notificar carga al equipo**")
        if st.button("Notificar última carga al equipo (con preview)", key="notify_team_btn"):
            st.session_state.show_notify_team = True

        if st.session_state.get("show_notify_team"):
            try:
                import sys as _sys
                _proj_root = os.path.dirname(BASE_DIR) if os.path.basename(BASE_DIR) == "data" else BASE_DIR
                if _proj_root not in _sys.path:
                    _sys.path.insert(0, _proj_root)
                from email_preview import preview_y_enviar
                _last_bk = _backups[0] if _backups else None
                _cuerpo = f"""
                <div style="font-family:Arial,sans-serif;padding:20px;">
                  <h2 style="color:#1F4E79;">📊 Análisis de Contribución actualizado</h2>
                  <p>Cargado el <b>{datetime.now().strftime('%d/%m/%Y %H:%M')}</b> por <b>{_sess_user}</b>.</p>
                  <p>Archivo activo: <code>{os.path.basename(XLSX_PATH)}</code></p>
                  <p>Último backup: <code>{_last_bk or 'N/A'}</code></p>
                  <p>Revisá el dashboard en http://localhost:8501</p>
                </div>
                """
                _result = preview_y_enviar(
                    asunto=f"Carga Análisis Contribución - {datetime.now().strftime('%d/%m/%Y')}",
                    cuerpo_html=_cuerpo,
                    modo="reporte",
                    key_prefix="contrib_notify",
                )
                if _result:
                    st.session_state.show_notify_team = False
            except Exception as _e_notify:
                st.error(f"No se pudo cargar email_preview: {_e_notify}")

        st.markdown("---")
        st.caption(
            "Los respaldos se guardan en `data/planillas/backups/`. "
            "Para agregar nuevos usuarios con acceso al dashboard, "
            "editá `eerr-finanzas/auth_config.yaml` y generá el hash con `_gen_hash.py`."
        )


# ── FOOTER ───────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='text-align:center;color:#94A3B8;font-size:.72rem;padding:20px 0 10px 0;'>"
    "UnionX — Analisis de Contribucion 2026 V06 | Dashboard BI</div>",
    unsafe_allow_html=True,
)
