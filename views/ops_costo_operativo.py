"""
Vista Costo Operativo — App Operaciones.

Foco: FCST operación real vs Venta + Pedidos (no PPTO — eso vive en Finanzas).

Métricas que se ven acá:
  - Costo operativo total FCST + YoY 2026 vs 2025
  - Composición Fijo / Variable + % de cada uno
  - Relación costo / venta % (benchmark Plan UnionX 8-12%)
  - Relación costo / pedido (cruce snapshot WMS productividad)
  - Costo / Contribución %
  - Tendencia eficiencia mensual (ratio costo/venta)
  - Proyección lineal costo según venta proyectada
  - Punto de equilibrio (costos fijos / margen contribución)
  - Designación de costos por línea de negocio (editor manual)
  - Top CCs creciendo más vs año anterior (alertas ineficiencias)
"""
import io
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


PROJECT_ROOT = Path(__file__).parent.parent
PARQUET = PROJECT_ROOT / "data" / "operaciones" / "costo_operativo.parquet"
RESUMEN = PROJECT_ROOT / "data" / "operaciones" / "costo_operativo_resumen.json"
WMS_SNAP = PROJECT_ROOT / "data" / "kpis_wms" / "snapshot.json"
VENTAS_HIST = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"


# Benchmarks Plan UnionX 2026-2028
BENCH_COSTO_VENTA_OK = 12.0      # ≤12% es óptimo
BENCH_COSTO_VENTA_ALERTA = 14.0  # >14% es problema


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
    """Snapshot WMS → {YYYY-MM: # pedidos}."""
    if not WMS_SNAP.exists():
        return {}
    try:
        snap = json.load(open(WMS_SNAP, encoding="utf-8"))
        for key in ("productividad_mes_6m", "productividad_meses_12m"):
            p = snap.get(key, {})
            items = p.get("items", []) if isinstance(p, dict) else []
            if items:
                return {
                    it.get("periodo", ""): it.get("n_pedidos", 0)
                    for it in items if it.get("n_pedidos", 0) > 0
                }
    except Exception:
        pass
    return {}


@st.cache_data(ttl=600)
def _cargar_ventas_mensual() -> pd.DataFrame:
    """Lee parquet histórico de ventas y agrega por mes:
    venta_bruta, venta_neta, margen_front, margen_final, n_pedidos."""
    if not VENTAS_HIST.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(VENTAS_HIST)
        # Filtrar solo ventas (excluir devoluciones para gross figure)
        # NOTA: si el user prefiere neto incluyendo NC, ajustar acá
        df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce")
        df = df.dropna(subset=["fecha_venta"])
        df["year"] = df["fecha_venta"].dt.year
        df["month"] = df["fecha_venta"].dt.month
        df["mes_iso"] = df["fecha_venta"].dt.strftime("%Y-%m")

        agg = df.groupby(["year", "month", "mes_iso"], as_index=False).agg(
            venta_bruta=("venta_bruta", "sum"),
            venta_neta=("venta_neta", "sum"),
            margen_front=("margen_front", "sum"),
            margen_final=("margen_final", "sum"),
            n_pedidos=("pedido", "nunique"),
            n_lineas=("sku", "count"),
            n_unidades=("cantidad", "sum"),
        )
        agg["fecha"] = pd.to_datetime(
            agg["year"].astype(str) + "-" + agg["month"].astype(str) + "-01"
        )
        return agg
    except Exception:
        return pd.DataFrame()


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
        st.caption("FCST real vs Venta + Pedidos")
        st.divider()

    st.title("💰 Costo Operativo Total")
    st.caption(
        "Resultado operación FCST × Venta × Pedidos · benchmark Plan UnionX "
        "8-12% costo/venta · base: Sheet OPERACIONES 2025-2026"
    )
    st.caption(
        "💡 **PPTO vs FCST se analiza en app Finanzas** (Control de Gestión). "
        "Acá el foco es la operación real proyectada vs ingresos."
    )

    df, res = _cargar()
    if df.empty:
        st.warning("⏳ Sin datos. Correr `python extract_ops_costo_operativo.py`")
        return

    st.caption(
        f"🕒 Generado: {res.get('generado_en','')[:19]} · "
        f"{res.get('filas_procesadas',0):,} filas · "
        f"{res.get('centros_costo_count',0)} CCs"
    )
    st.divider()

    # ─── FILTROS ────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([1, 2, 2])
    with col1:
        years = sorted(df["year"].dropna().unique().astype(int).tolist())
        year_actual = max(years) if years else 2026
        year_sel = st.selectbox("Año análisis", years,
                                  index=years.index(year_actual) if year_actual in years else len(years)-1)
    with col2:
        areas = sorted(df["area"].dropna().unique().tolist())
        area_sel = st.multiselect("Áreas (todas por default)", areas, default=areas)
    with col3:
        st.caption(
            "**Modelo:** la operación es UNA SOLA base que sirve a UNIONX + GRUPO ETER. "
            "Los gastos están consolidados; abajo podés asignar % por LN."
        )

    df_fcst = df[(df["escenario"] == "FCST") & df["area"].isin(area_sel)].copy()
    df_year = df_fcst[df_fcst["year"] == year_sel].copy()
    df_year_ant = df_fcst[df_fcst["year"] == year_sel - 1].copy()

    # ─── VENTAS REALES desde módulo Ventas (parquet histórico) ──────────
    # Mucho más completo que la columna VENTA del Sheet (que tiene solo
    # UNIONX subset). Convertido a M CLP para sumar con costos del Sheet.
    df_ventas_all = _cargar_ventas_mensual()
    df_ventas_year = pd.DataFrame()
    df_ventas_ant = pd.DataFrame()
    venta_year = 0
    venta_ant = 0
    margen_final_year = 0
    margen_front_year = 0
    pedidos_real_year = 0
    if not df_ventas_all.empty:
        df_ventas_year = df_ventas_all[df_ventas_all["year"] == year_sel]
        df_ventas_ant = df_ventas_all[df_ventas_all["year"] == year_sel - 1]
        # CLP raw → M CLP (dividir por 1000) para comparar con costos del Sheet
        venta_year = df_ventas_year["venta_bruta"].sum() / 1000
        venta_ant = df_ventas_ant["venta_bruta"].sum() / 1000
        margen_final_year = df_ventas_year["margen_final"].sum() / 1000
        margen_front_year = df_ventas_year["margen_front"].sum() / 1000
        pedidos_real_year = int(df_ventas_year["n_pedidos"].sum())

    # ─── KPIs PRINCIPALES (gasto del Sheet, venta del módulo Ventas) ─────
    gasto_year = df_year[df_year["kpi"] == "GASTO"]["valor"].sum()
    contrib_year = margen_final_year  # ← usa margen final del parquet ventas
    gasto_ant = df_year_ant[df_year_ant["kpi"] == "GASTO"]["valor"].sum()

    # Costos por tipo
    fijo = df_year[(df_year["kpi"] == "GASTO") & (df_year["tipo_costo"] == "FIJO")]["valor"].sum()
    variable = df_year[(df_year["kpi"] == "GASTO") & (df_year["tipo_costo"] == "VARIABLE")]["valor"].sum()
    total_clasif = abs(fijo) + abs(variable)
    pct_fijo = (abs(fijo) / total_clasif * 100) if total_clasif > 0 else 0
    pct_variable = (abs(variable) / total_clasif * 100) if total_clasif > 0 else 0

    # Ratios
    costo_venta = (abs(gasto_year) / abs(venta_year) * 100) if venta_year else None
    costo_venta_ant = (abs(gasto_ant) / abs(venta_ant) * 100) if venta_ant else None
    yoy_gasto = ((abs(gasto_year) / abs(gasto_ant) - 1) * 100) if gasto_ant else None

    # Pedidos: usar parquet ventas (más confiable que WMS snapshot)
    pedidos_year = pedidos_real_year
    if pedidos_year == 0:
        # Fallback a WMS snapshot
        pedidos_dict = _cargar_pedidos_mes()
        pedidos_year = sum(v for k, v in pedidos_dict.items()
                            if k.startswith(str(year_sel))) if pedidos_dict else 0
    costo_pedido = (abs(gasto_year) * 1_000_000 / pedidos_year) if pedidos_year else None

    # Costo / Margen contribución
    costo_margen = (abs(gasto_year) / abs(margen_final_year) * 100) if margen_final_year else None

    st.markdown(f"### 💰 KPIs principales {year_sel}")
    st.caption(
        f"💡 Venta + margen: módulo Ventas ({pedidos_year:,.0f} pedidos · "
        f"{_fmt_clp(venta_year)} venta bruta) · Costo: Sheet OPERACIONES"
    )

    # Fila 1: Costo total + Composición
    cols = st.columns(4)
    cols[0].markdown(_kpi_html(
        f"Costo Operativo FCST {year_sel}",
        _fmt_clp(gasto_year),
        (f"YoY vs {year_sel-1}: <b>{_fmt_pct(yoy_gasto)}</b>"
         if yoy_gasto is not None else f"Sin data {year_sel-1}"),
        "#DC2626" if yoy_gasto and yoy_gasto > 15 else "#1F4E79",
    ), unsafe_allow_html=True)

    color_cv = "#16A34A" if costo_venta and costo_venta <= BENCH_COSTO_VENTA_OK else (
        "#EA580C" if costo_venta and costo_venta <= BENCH_COSTO_VENTA_ALERTA else "#DC2626")
    cols[1].markdown(_kpi_html(
        "Costo / Venta %",
        f"{costo_venta:.1f}%" if costo_venta else "—",
        (f"Año ant: <b>{costo_venta_ant:.1f}%</b> · Bench <b>8-12%</b>"
         if costo_venta_ant else f"Benchmark Plan: <b>8-12%</b>"),
        color_cv,
    ), unsafe_allow_html=True)

    cols[2].markdown(_kpi_html(
        "Costo / Mg Contribución %",
        f"{costo_margen:.1f}%" if costo_margen else "—",
        f"Margen final año: <b>{_fmt_clp(margen_final_year)}</b><br>"
        f"(% del margen consumido por costo op)",
        "#7C3AED",
    ), unsafe_allow_html=True)

    cols[3].markdown(_kpi_html(
        "Costo / Pedido",
        f"${costo_pedido:,.0f}" if costo_pedido else "—",
        f"FCST / {pedidos_year:,.0f} pedidos<br>(módulo Ventas)",
        "#EA580C",
    ), unsafe_allow_html=True)

    # Fila 2: composición
    st.markdown("<br>", unsafe_allow_html=True)
    cols2 = st.columns(4)
    cols2[0].markdown(_kpi_html(
        "Venta Bruta",
        _fmt_clp(venta_year),
        f"YoY: <b>{_fmt_pct(((venta_year/venta_ant - 1)*100) if venta_ant else None)}</b><br>"
        f"Año ant: {_fmt_clp(venta_ant)}",
        "#16A34A",
    ), unsafe_allow_html=True)
    cols2[1].markdown(_kpi_html(
        "Margen Frontal",
        _fmt_clp(margen_front_year),
        f"Margen / Venta: <b>"
        f"{margen_front_year/venta_year*100:.1f}%</b>" if venta_year else "—",
        "#0EA5E9",
    ), unsafe_allow_html=True)
    cols2[2].markdown(_kpi_html(
        "Margen Final (contribución)",
        _fmt_clp(margen_final_year),
        f"Margen / Venta: <b>"
        f"{margen_final_year/venta_year*100:.1f}%</b>" if venta_year else "—",
        "#7C3AED",
    ), unsafe_allow_html=True)
    cols2[3].markdown(_kpi_html(
        "Composición Costo",
        f"{pct_fijo:.0f}% Fijo / {pct_variable:.0f}% Var",
        f"Fijo: <b>{_fmt_clp(fijo)}</b><br>Variable: <b>{_fmt_clp(variable)}</b>",
        "#1F4E79",
    ), unsafe_allow_html=True)

    st.divider()

    # ─── COSTOS vs VENTA vs CONTRIBUCION MENSUAL ─────────────────────────
    st.markdown("### 📈 Costo Operativo vs Venta vs Contribución — mensual")
    st.caption("Costo: Sheet OPERACIONES (FCST) · Venta + Margen: módulo Ventas (real)")

    # Costos mensuales del Sheet
    df_costos_m = (df_year[df_year["kpi"] == "GASTO"]
                    .groupby("fecha", as_index=False)["valor"].sum())
    df_costos_m["costo_abs"] = df_costos_m["valor"].abs()

    # Ventas mensuales del parquet (M CLP)
    df_v_m = df_ventas_year.copy() if not df_ventas_year.empty else pd.DataFrame()
    if not df_v_m.empty:
        df_v_m["venta_m"] = df_v_m["venta_bruta"] / 1000
        df_v_m["margen_m"] = df_v_m["margen_final"] / 1000

    if not df_costos_m.empty or not df_v_m.empty:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        if not df_costos_m.empty:
            fig.add_trace(go.Bar(
                x=df_costos_m["fecha"], y=df_costos_m["costo_abs"],
                name="Costo operativo (FCST)", marker_color="#DC2626", opacity=0.85,
                hovertemplate="%{x|%b %Y}<br>Costo: $%{y:,.0f}M<extra></extra>",
            ), secondary_y=False)
        if not df_v_m.empty:
            fig.add_trace(go.Scatter(
                x=df_v_m["fecha"], y=df_v_m["venta_m"],
                name="Venta bruta (real)", mode="lines+markers",
                line=dict(color="#16A34A", width=3),
                marker=dict(size=10),
                hovertemplate="%{x|%b %Y}<br>Venta: $%{y:,.0f}M<extra></extra>",
            ), secondary_y=False)
            fig.add_trace(go.Scatter(
                x=df_v_m["fecha"], y=df_v_m["margen_m"],
                name="Margen contribución", mode="lines+markers",
                line=dict(color="#7C3AED", width=2.5, dash="dot"),
                marker=dict(size=8),
                hovertemplate="%{x|%b %Y}<br>Margen: $%{y:,.0f}M<extra></extra>",
            ), secondary_y=False)

            # Ratio costo/venta % (eje derecho)
            df_merge = df_costos_m.merge(
                df_v_m[["fecha", "venta_m"]], on="fecha", how="inner"
            )
            if not df_merge.empty:
                df_merge["ratio_cv"] = df_merge["costo_abs"] / df_merge["venta_m"] * 100
                fig.add_trace(go.Scatter(
                    x=df_merge["fecha"], y=df_merge["ratio_cv"],
                    name="Costo/Venta %", mode="lines+markers",
                    line=dict(color="#EA580C", width=2.5),
                    marker=dict(size=7, symbol="diamond"),
                    hovertemplate="%{x|%b %Y}<br>Ratio: %{y:.1f}%<extra></extra>",
                ), secondary_y=True)
                fig.add_hline(y=BENCH_COSTO_VENTA_OK, line=dict(color="#16A34A", dash="dot"),
                               secondary_y=True, annotation_text="12% benchmark",
                               annotation_position="right")
                fig.update_yaxes(
                    title_text="Costo/Venta %", tickformat=".0f",
                    secondary_y=True,
                    range=[0, max(20, df_merge["ratio_cv"].max() * 1.2)],
                )

        fig.update_layout(
            height=420,
            xaxis=dict(title="Mes"),
            hovermode="x unified",
            margin=dict(t=20, b=40, l=70, r=70),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.05, x=0),
        )
        fig.update_yaxes(title_text="M CLP", tickformat=",.0f", secondary_y=False)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ─── COMPOSICIÓN FIJO vs VARIABLE ───────────────────────────────────
    st.markdown("### 🧊 Composición Fijo vs Variable")
    c1, c2 = st.columns([1, 2])

    with c1:
        if total_clasif > 0:
            fig_donut = go.Figure(go.Pie(
                labels=["Fijo", "Variable"],
                values=[abs(fijo), abs(variable)],
                hole=0.55,
                marker=dict(colors=["#1F4E79", "#EA580C"]),
                textinfo="label+percent",
                hovertemplate="%{label}<br>$%{value:,.0f}M (%{percent})<extra></extra>",
            ))
            fig_donut.update_layout(
                height=300, margin=dict(t=10, b=10, l=10, r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
            )
            st.plotly_chart(fig_donut, use_container_width=True)

    with c2:
        # Tendencia mensual fijo vs variable
        df_fv = (df_year[df_year["kpi"] == "GASTO"]
                  .groupby(["fecha", "tipo_costo"], as_index=False)["valor"].sum())
        df_fv["valor_abs"] = df_fv["valor"].abs()
        if not df_fv.empty:
            fig_fv = go.Figure()
            for tipo, color in [("FIJO", "#1F4E79"), ("VARIABLE", "#EA580C")]:
                d = df_fv[df_fv["tipo_costo"] == tipo].sort_values("fecha")
                if d.empty:
                    continue
                fig_fv.add_trace(go.Bar(
                    x=d["fecha"], y=d["valor_abs"],
                    name=tipo, marker_color=color,
                    hovertemplate=f"<b>{tipo}</b><br>%{{x|%b %Y}}: $%{{y:,.0f}}M<extra></extra>",
                ))
            fig_fv.update_layout(
                height=300, barmode="stack",
                xaxis=dict(title="Mes"),
                yaxis=dict(title="M CLP", tickformat=",.0f"),
                margin=dict(t=20, b=40, l=60, r=20),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", y=1.05, x=0),
            )
            st.plotly_chart(fig_fv, use_container_width=True)

    st.divider()

    # ─── COMPARATIVO YoY POR CC ─────────────────────────────────────────
    st.markdown(f"### 📊 Centros de Costo — {year_sel} vs {year_sel-1} (YoY)")
    df_cc_actual = (df_year[df_year["kpi"] == "GASTO"]
                     .groupby("centro_costo")["valor"].sum().abs())
    df_cc_ant = (df_year_ant[df_year_ant["kpi"] == "GASTO"]
                  .groupby("centro_costo")["valor"].sum().abs())
    cc_comp = pd.DataFrame({
        f"{year_sel-1}": df_cc_ant,
        f"{year_sel}": df_cc_actual,
    }).fillna(0)
    cc_comp["YoY abs"] = cc_comp[f"{year_sel}"] - cc_comp[f"{year_sel-1}"]
    cc_comp["YoY %"] = cc_comp.apply(
        lambda r: ((r[f"{year_sel}"] / r[f"{year_sel-1}"] - 1) * 100)
                   if r[f"{year_sel-1}"] > 0 else None,
        axis=1,
    )
    cc_comp = cc_comp.sort_values("YoY abs", ascending=False)

    df_show = pd.DataFrame({
        "Centro Costo": cc_comp.index,
        f"{year_sel-1}": cc_comp[f"{year_sel-1}"].apply(_fmt_clp),
        f"{year_sel}": cc_comp[f"{year_sel}"].apply(_fmt_clp),
        "YoY abs": cc_comp["YoY abs"].apply(_fmt_clp),
        "YoY %": cc_comp["YoY %"].apply(_fmt_pct),
    })
    st.dataframe(df_show, use_container_width=True, hide_index=True, height=380)

    # ─── INSIGHTS DE INEFICIENCIAS ──────────────────────────────────────
    st.markdown("### 🎯 Insights de ineficiencia")

    insights = []

    # 1. CCs con crecimiento desproporcionado YoY
    top_crec = cc_comp[(cc_comp[f"{year_sel-1}"] > 1000)
                         & (cc_comp["YoY %"].fillna(0) > 20)].head(5)
    if not top_crec.empty:
        for cc in top_crec.index:
            pct = top_crec.at[cc, "YoY %"]
            abs_yoy = top_crec.at[cc, "YoY abs"]
            insights.append({
                "tipo": "🟠 CC CRECIENDO DESPROPORCIONADO",
                "titulo": f"{cc}: {pct:+.0f}% YoY ({_fmt_clp(abs_yoy)})",
                "accion": (
                    f"**Acción:** auditar gastos de **{cc}**.\n"
                    f"- Revisar mes a mes si hay outliers\n"
                    f"- Comparar contra evolución de pedidos/venta del año\n"
                    f"- Si es fijo, evaluar renegociación. Si variable, revisar driver."
                ),
            })

    # 2. Costo/Venta arriba del benchmark
    if costo_venta and costo_venta > BENCH_COSTO_VENTA_ALERTA:
        insights.append({
            "tipo": "🔴 RATIO COSTO/VENTA SOBRE BENCHMARK",
            "titulo": f"{costo_venta:.1f}% vs Plan UnionX 8-12% (>{BENCH_COSTO_VENTA_ALERTA}% es crítico)",
            "accion": (
                "**Acción:**\n"
                "1. Identificar top 3 CCs con mayor peso (ver tabla arriba)\n"
                "2. Verificar si la venta del Sheet está completa "
                "(GRUPO ETER tiene poco/nada de venta cargada)\n"
                "3. Si Costo está bien medido pero falta venta → consolidar ingreso real\n"
                "4. Si Costo está sobre-estimado → revisar designación a UNIONX vs ETER"
            ),
        })

    # 3. Ratio fijo > variable (poca flexibilidad)
    if pct_fijo > 60:
        insights.append({
            "tipo": "🟡 ESTRUCTURA RÍGIDA",
            "titulo": f"{pct_fijo:.0f}% costos fijos — poca flexibilidad ante baja de ventas",
            "accion": (
                "**Acción:**\n"
                "1. Identificar costos fijos potencialmente convertibles a variables "
                "(ej: subcontratación de logística pico)\n"
                "2. Renegociar contratos largos para introducir % variable\n"
                "3. Evaluar consolidación de bodegas si la rígida es arriendo"
            ),
        })

    # 4. Sin ineficiencias
    if not insights:
        insights.append({
            "tipo": "🟢 OPERACIÓN EFICIENTE",
            "titulo": f"Costo/Venta {costo_venta:.1f}% bajo benchmark · sin CCs con crecimiento desproporcionado",
            "accion": (
                "Mantener monitoreo mensual. Buscar oportunidades de mejora:\n"
                "1. Auditar costos variables (mayor margen de optimización)\n"
                "2. Evaluar inversión en automatización (paga vs costos fijos actuales)"
            ),
        })

    for ins in insights:
        if ins["tipo"].startswith("🔴"):
            st.error(f"**{ins['tipo']} — {ins['titulo']}**")
        elif ins["tipo"].startswith("🟠"):
            st.warning(f"**{ins['tipo']} — {ins['titulo']}**")
        elif ins["tipo"].startswith("🟡"):
            st.info(f"**{ins['tipo']} — {ins['titulo']}**")
        else:
            st.success(f"**{ins['tipo']} — {ins['titulo']}**")
        st.markdown(ins["accion"])

    st.divider()

    # ─── PROYECCIÓN COSTO vs VENTA ──────────────────────────────────────
    st.markdown("### 🔮 Proyección de costo según FCST de venta")
    st.caption(
        "Si la operación es base única, escala con la venta. Regresión lineal "
        f"costo↔venta sobre {year_sel}. Permite simular qué costo tendrías si "
        "la venta sube/baja un X%."
    )

    # Usar venta real del módulo Ventas + costo del Sheet
    if not df_v_m.empty and not df_costos_m.empty:
        df_reg = df_costos_m.merge(
            df_v_m[["fecha", "venta_m"]], on="fecha", how="inner"
        )
        if df_reg.empty:
            venta_m = costo_m = np.array([])
        else:
            venta_m = df_reg["venta_m"].values
            costo_m = df_reg["costo_abs"].values
        mask = (venta_m > 0) & (costo_m > 0) if len(venta_m) > 0 else np.array([], dtype=bool)
        if mask.sum() >= 3:
            x = venta_m[mask]
            y = costo_m[mask]
            # Regresión lineal y = a*x + b
            a, b = np.polyfit(x, y, 1)
            r2 = np.corrcoef(x, y)[0, 1] ** 2

            col_sim1, col_sim2 = st.columns(2)
            with col_sim1:
                delta_venta = st.slider(
                    "Variación de venta proyectada (%)", -30, 50, 0, step=5,
                    key="costo_op_sim",
                )
                venta_avg = x.mean()
                venta_sim = venta_avg * (1 + delta_venta / 100)
                costo_sim = a * venta_sim + b
                ratio_sim = costo_sim / venta_sim * 100 if venta_sim > 0 else 0

                st.metric(
                    f"Venta simulada (promedio mensual)",
                    _fmt_clp(venta_sim),
                    f"{delta_venta:+d}%" if delta_venta else None,
                )
                st.metric(
                    "Costo proyectado",
                    _fmt_clp(costo_sim),
                    f"Ratio {ratio_sim:.1f}%",
                    delta_color="inverse",
                )

            with col_sim2:
                fig_reg = go.Figure()
                fig_reg.add_trace(go.Scatter(
                    x=x, y=y, mode="markers", name="Meses reales",
                    marker=dict(size=10, color="#1F4E79"),
                    hovertemplate="Venta: $%{x:,.0f}M<br>Costo: $%{y:,.0f}M<extra></extra>",
                ))
                # Línea regresión
                xx = np.linspace(x.min() * 0.7, x.max() * 1.3, 50)
                yy = a * xx + b
                fig_reg.add_trace(go.Scatter(
                    x=xx, y=yy, mode="lines", name=f"Regresión (R²={r2:.2f})",
                    line=dict(color="#DC2626", dash="dash"),
                ))
                # Punto simulado
                fig_reg.add_trace(go.Scatter(
                    x=[venta_sim], y=[costo_sim],
                    mode="markers+text", name="Simulación",
                    marker=dict(size=18, color="#EA580C", symbol="star"),
                    text=[f"{ratio_sim:.1f}%"], textposition="top center",
                ))
                fig_reg.update_layout(
                    height=300,
                    xaxis=dict(title="Venta mensual (M CLP)", tickformat=",.0f"),
                    yaxis=dict(title="Costo mensual (M CLP)", tickformat=",.0f"),
                    margin=dict(t=20, b=40, l=70, r=20),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_reg, use_container_width=True)
        else:
            st.info("Necesito al menos 3 meses con venta (real) y costo para regresión")
    else:
        st.info("Sin datos de venta (módulo Ventas) o costo (Sheet) para regresión")

    st.divider()

    # ─── PUNTO DE EQUILIBRIO ────────────────────────────────────────────
    st.markdown("### ⚖️ Punto de equilibrio")
    st.caption(
        "Venta necesaria para cubrir costos fijos (costos variables se "
        "asumen proporcionales a venta)."
    )

    fijo_mensual = abs(fijo) / 12 if fijo else 0  # promedio mes
    variable_mensual = abs(variable) / 12 if variable else 0
    venta_mensual_avg = abs(venta_year) / 12 if venta_year else 0
    # Margen contribución % = (Venta - Variable) / Venta
    mc_pct = ((venta_mensual_avg - variable_mensual) / venta_mensual_avg
               if venta_mensual_avg > 0 else 0)
    # Break-even venta = Fijo / MC%
    breakeven_venta = (fijo_mensual / mc_pct) if mc_pct > 0 else None
    holgura_pct = ((venta_mensual_avg / breakeven_venta - 1) * 100
                    if breakeven_venta and breakeven_venta > 0 else None)

    be_cols = st.columns(4)
    be_cols[0].metric("Costos Fijos mensuales", _fmt_clp(-fijo_mensual))
    be_cols[1].metric("Margen Contribución %",
                       f"{mc_pct*100:.1f}%" if mc_pct else "—")
    be_cols[2].metric("Venta para break-even", _fmt_clp(breakeven_venta))
    be_cols[3].metric(
        "Holgura vs venta actual",
        f"{holgura_pct:+.1f}%" if holgura_pct is not None else "—",
        delta_color="normal",
    )

    st.divider()

    # ─── DESIGNACIÓN POR LÍNEA DE NEGOCIO ────────────────────────────────
    st.markdown("### 🎯 Designación de Costos por Línea de Negocio")
    st.caption(
        "La operación es UNA SOLA pero sirve a varias LN. Asigná % de los "
        "costos fijos a cada LN según cuánto la usa. Default 100% UNIONX "
        "porque GRUPO ETER tiene su operación propia."
    )

    asig_default = pd.DataFrame({
        "Línea Negocio": ["UNIONX", "GRUPO ETER"],
        "% Asignación": [100.0, 0.0],
        "Driver sugerido": [
            "Pedidos del canal / total pedidos",
            "Pedidos del canal / total pedidos",
        ],
    })

    edited = st.data_editor(
        asig_default,
        column_config={
            "% Asignación": st.column_config.NumberColumn(
                "% Asignación", min_value=0, max_value=100, step=1, format="%.0f%%",
            ),
        },
        hide_index=True, use_container_width=True, num_rows="fixed",
    )

    total_pct = edited["% Asignación"].sum()
    if abs(total_pct - 100) > 0.1:
        st.warning(f"⚠️ Total de asignación: {total_pct:.0f}% (debería sumar 100%)")
    else:
        # Calcular cost-to-serve por LN
        st.markdown("##### 💵 Cost-to-serve por Línea de Negocio")
        df_serve = edited.copy()
        df_serve["Costo asignado"] = (df_serve["% Asignación"] / 100
                                        * abs(gasto_year))
        # Venta por LN: TODA la venta del módulo Ventas asignada a UNIONX
        # (módulo Ventas no separa LN — todo es UnionX consolidado).
        # GRUPO ETER queda sin venta porque tiene operación propia separada.
        venta_por_ln = {"UNIONX": venta_year, "GRUPO ETER": 0}
        df_serve["Venta LN"] = df_serve["Línea Negocio"].map(venta_por_ln).fillna(0)
        df_serve["Costo/Venta %"] = df_serve.apply(
            lambda r: (r["Costo asignado"] / r["Venta LN"] * 100)
                       if r["Venta LN"] > 0 else None,
            axis=1,
        )
        df_show_serve = pd.DataFrame({
            "Línea Negocio": df_serve["Línea Negocio"],
            "% Asignación": df_serve["% Asignación"].apply(lambda v: f"{v:.0f}%"),
            "Costo asignado": df_serve["Costo asignado"].apply(
                lambda v: f"${v/1000:,.0f}MM"),
            "Venta LN": df_serve["Venta LN"].apply(
                lambda v: f"${v/1000:,.0f}MM" if v > 0 else "—"),
            "Costo/Venta %": df_serve["Costo/Venta %"].apply(
                lambda v: f"{v:.1f}%" if pd.notna(v) else "—"),
        })
        st.dataframe(df_show_serve, use_container_width=True, hide_index=True)

    st.divider()

    # ─── DETALLE TABLA ───────────────────────────────────────────────────
    with st.expander("📋 Detalle: gasto por CC × mes (descarga Excel)"):
        df_fcst_gasto = df_year[df_year["kpi"] == "GASTO"]
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
            st.dataframe(pivot_disp, use_container_width=True, height=420)

            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                pivot.to_excel(w, sheet_name="Costo Op CC")
            st.download_button(
                "📥 Descargar Excel",
                data=buf.getvalue(),
                file_name=f"costo_operativo_{year_sel}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    with st.expander("ℹ️ Sobre el modelo"):
        st.markdown(f"""
        **Fuente:** [Sheet OPERACIONES 2025-2026](https://docs.google.com/spreadsheets/d/1WXoQYwDwYVXGBIacAUgTpzb-aYXm2BXgXA0_EucKo7M/edit) · refresca cada 12h vía cron.

        **Concepto clave:** la operación es **una sola base** que sirve a múltiples
        líneas de negocio (UNIONX + GRUPO ETER) y canales. Los gastos están
        consolidados en GRUPO ETER en el Sheet; la designación por LN se hace
        editando los % arriba.

        **Benchmarks Plan UnionX 2026-2028:**
        - Costo logístico / venta: 8-12% (óptimo) · 12-14% (alerta) · >14% (crítico)
        - Costo / pedido ↓ 10-15% YoY

        **PPTO vs FCST** (presupuesto vs forecast) se analiza en
        **app Finanzas → Control de Gestión** (mismo Sheet con dimensión Tipo).
        Acá el foco es **FCST real vs Venta y Pedidos**.
        """)
