"""
Vista P&L por Centro de Costo — App Finanzas.

Control de gestión presupuestario:
  - Tabla pivot: filas = códigos contables (4101-XX, 4201-XX, ...) por sección
                 columnas = meses
  - Vista: Real | Ppto | Var | Var% con semáforo
  - Click en CC → drill-down: tendencia 12m, top movimientos
  - Filtros: mes, sección, monto mínimo de variación

Fuente:
  - pyl_mensual.parquet (real histórico mensual)
  - ppto_2026.parquet (ppto por código contable)

Cuando se conecte el Drive de control de gestión, se sumará como tercera
fuente: Drive_CG.parquet con los datos de seguimiento mensual editables.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views._fin_data import pyl, ppto_2026


MESES_ES = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}


def _semaforo(var_pct, inverted: bool = False) -> str:
    if pd.isna(var_pct):
        return "—"
    val = -var_pct if inverted else var_pct
    if val >= 0.05:
        return "🟢"
    if val >= -0.05:
        return "🟡"
    return "🔴"


def render():
    with st.sidebar:
        st.markdown("### 💵 **P&L por CC**")
        st.caption("Control de gestión presupuestaria")
        st.divider()

    st.title("💵 P&L por Centro de Costo")
    st.caption(
        "Comparativo mes a mes: Real vs Presupuesto · por código contable · "
        "drill-down a cada centro"
    )

    df_pyl = pyl()
    df_ppto = ppto_2026()

    if df_ppto.empty:
        st.warning(
            "⏳ Sin datos. Correr `python extract_finanzas_planificacion.py` "
            "para regenerar parquets."
        )
        return

    # ─── FILTROS ─────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        meses_disp = sorted(df_ppto[df_ppto["year"] == 2026]["month"].unique())
        if not meses_disp:
            st.info("Sin meses 2026 en Ppto")
            return
        mes_sel = st.selectbox(
            "Mes a analizar",
            options=meses_disp,
            index=len(meses_disp) - 1,
            format_func=lambda m: f"{MESES_ES[m]} 2026",
        )
    with col2:
        secciones = sorted(df_ppto["seccion"].fillna("Sin sección").unique())
        seccion_sel = st.selectbox("Sección", ["Todas"] + secciones)
    with col3:
        umbral_var = st.slider(
            "Umbral variación (M$)", 0, 100, 0,
            help="Filtra CCs con variación absoluta menor a este monto",
        )

    st.divider()

    # ─── PREPARAR DATOS: Ppto vs Real (P&L) por mes y CC ─────────────────
    # P&L está por LINEA (no por código contable), Ppto está por CC.
    # Cruzamos por nombre de línea (mayúsculas/minúsculas pueden diferir).

    df_ppto_mes = df_ppto[(df_ppto["year"] == 2026) & (df_ppto["month"] == mes_sel)].copy()
    df_pyl_mes = df_pyl[(df_pyl["year"] == 2026) & (df_pyl["month"] == mes_sel)].copy()

    if seccion_sel != "Todas":
        df_ppto_mes = df_ppto_mes[df_ppto_mes["seccion"] == seccion_sel]

    # Normalizar nombres para match (uppercase strip)
    df_ppto_mes["linea_norm"] = df_ppto_mes["linea"].str.strip().str.upper()
    df_pyl_mes["linea_norm"] = df_pyl_mes["linea"].str.strip().str.upper()

    # Agregar P&L del mismo mes (sumar si hay duplicados de líneas)
    pyl_agg = df_pyl_mes.groupby("linea_norm", as_index=False)["valor"].sum()
    pyl_agg.rename(columns={"valor": "real"}, inplace=True)

    ppto_agg = df_ppto_mes.groupby(
        ["codigo_cc", "linea_norm", "linea", "seccion"], as_index=False
    )["valor_ppto"].sum()

    merged = ppto_agg.merge(pyl_agg, on="linea_norm", how="left")
    merged["real"] = merged["real"].fillna(0)
    merged["var_abs"] = merged["real"] - merged["valor_ppto"]
    merged["var_pct"] = merged.apply(
        lambda r: (r["var_abs"] / abs(r["valor_ppto"]))
                  if r["valor_ppto"] and abs(r["valor_ppto"]) > 0 else None,
        axis=1,
    )

    # Filtrar umbral
    if umbral_var > 0:
        merged = merged[merged["var_abs"].abs() >= umbral_var * 1000]  # M$ → CLP

    # Sección: determinar si es costo (var positiva es mala) o ingreso
    def _es_costo(seccion: str, linea: str) -> bool:
        s = (seccion or "").upper() + " " + (linea or "").upper()
        return "COSTO" in s or "GASTO" in s or "GAV" in s or "REMUNER" in s

    merged["es_costo"] = merged.apply(
        lambda r: _es_costo(r["seccion"], r["linea"]), axis=1
    )
    merged["sem"] = merged.apply(
        lambda r: _semaforo(r["var_pct"], inverted=r["es_costo"]), axis=1
    )

    if merged.empty:
        st.info("Sin datos que mostrar con los filtros actuales")
        return

    # ─── KPIs RESUMEN ────────────────────────────────────────────────────
    total_ppto = merged["valor_ppto"].sum()
    total_real = merged["real"].sum()
    total_var = total_real - total_ppto
    total_var_pct = (total_var / abs(total_ppto)) if total_ppto else 0

    cols = st.columns(4)
    cols[0].metric("CCs en vista", len(merged))
    cols[1].metric("Ppto total", f"${total_ppto/1e6:,.1f} MM")
    cols[2].metric("Real total", f"${total_real/1e6:,.1f} MM")
    cols[3].metric(
        "Variación", f"${total_var/1e6:+,.1f} MM",
        f"{total_var_pct*100:+.1f}%",
        delta_color="inverse" if (merged["es_costo"].mean() > 0.5) else "normal",
    )

    st.divider()

    # ─── TOP DESVIACIONES ────────────────────────────────────────────────
    st.markdown(f"### 🔴 Top 10 desviaciones — {MESES_ES[mes_sel]} 2026")
    top = merged.sort_values("var_abs", key=abs, ascending=False).head(10)

    df_top = pd.DataFrame({
        "": top["sem"],
        "Código": top["codigo_cc"].fillna("—"),
        "Línea": top["linea"].str[:40],
        "Sección": top["seccion"].str[:25],
        "Ppto": top["valor_ppto"].apply(lambda v: f"${v/1e6:+,.1f} MM"),
        "Real": top["real"].apply(lambda v: f"${v/1e6:+,.1f} MM"),
        "Var Abs": top["var_abs"].apply(lambda v: f"${v/1e6:+,.1f} MM"),
        "Var %": top["var_pct"].apply(lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "—"),
    })
    st.dataframe(df_top, width='stretch', hide_index=True, height=420)

    st.divider()

    # ─── TABLA COMPLETA ──────────────────────────────────────────────────
    st.markdown(f"### 📋 Detalle completo — {MESES_ES[mes_sel]} 2026")

    df_full = merged.sort_values(["seccion", "valor_ppto"], ascending=[True, False]).copy()
    df_show = pd.DataFrame({
        "": df_full["sem"],
        "Código": df_full["codigo_cc"].fillna("—"),
        "Línea": df_full["linea"].str[:40],
        "Sección": df_full["seccion"].str[:25],
        "Ppto": df_full["valor_ppto"].apply(lambda v: f"${v/1e6:+,.1f} MM"),
        "Real": df_full["real"].apply(lambda v: f"${v/1e6:+,.1f} MM"),
        "Var Abs": df_full["var_abs"].apply(lambda v: f"${v/1e6:+,.1f} MM"),
        "Var %": df_full["var_pct"].apply(lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "—"),
    })
    st.dataframe(df_show, width='stretch', hide_index=True, height=500)
    st.caption(
        f"Total: {len(df_full)} CCs. Semáforo: 🟢 cumple/mejor que ppto (±5%) · "
        "🟡 cerca del ppto · 🔴 desvío >5% (signo según sea costo o ingreso)."
    )

    st.divider()

    # ─── DRILL-DOWN POR CC ──────────────────────────────────────────────
    st.markdown("### 🔍 Drill-down por Centro de Costo")
    cc_opciones = ["— Selecciona un CC —"] + [
        f"{r['codigo_cc'] or '—'} · {r['linea'][:40]}"
        for _, r in df_full.iterrows()
    ]
    cc_sel = st.selectbox("Centro de costo", cc_opciones, key="fin_cc_drilldown")

    if cc_sel != "— Selecciona un CC —":
        linea_buscada = cc_sel.split(" · ", 1)[1]
        linea_norm = linea_buscada.strip().upper()
        # Tendencia 12m del Real (del P&L)
        df_tend_real = df_pyl[
            df_pyl["linea"].str.strip().str.upper() == linea_norm
        ].copy().sort_values("fecha").tail(24)
        # Tendencia 12m del Ppto
        df_tend_ppto = df_ppto[
            df_ppto["linea"].str.strip().str.upper() == linea_norm
        ].copy().sort_values("fecha")

        if df_tend_real.empty and df_tend_ppto.empty:
            st.info("Sin datos para este CC")
            return

        fig = go.Figure()
        if not df_tend_real.empty:
            fig.add_trace(go.Scatter(
                x=df_tend_real["fecha"], y=df_tend_real["valor"],
                mode="lines+markers", name="Real",
                line=dict(color="#1F4E79", width=3),
                marker=dict(size=8),
            ))
        if not df_tend_ppto.empty:
            fig.add_trace(go.Scatter(
                x=df_tend_ppto["fecha"], y=df_tend_ppto["valor_ppto"],
                mode="lines+markers", name="Ppto",
                line=dict(color="#94A3B8", width=2, dash="dash"),
                marker=dict(size=6),
            ))
        fig.update_layout(
            height=340,
            title=f"{linea_buscada} — Real vs Ppto",
            xaxis=dict(title="Mes"),
            yaxis=dict(title="CLP", tickformat=",.0f"),
            hovermode="x unified",
            margin=dict(t=50, b=40, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, width='stretch')
