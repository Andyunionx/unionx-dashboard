"""
Vista P&L por Línea de Negocio — App Finanzas.

Construye un P&L COMPLETO con MONTOS REALES (no estimados) cruzando 4 fuentes:

  1. Sheet KAM "Análisis de Resultados" (oficial)
     → Venta REAL · Costo Venta · Margen Directo · Comisiones · Contribución
     → Segmentado por: Canal · KAM · Tipo Negocio (LN) · Año · Mes · Trimestre

  2. Sheet OPERACIONES (extraído a costo_operativo.parquet)
     → Costo operativo por CC × sub-área (asociado a Grupo Eter como holding)

  3. P&L corporativo (pyl_mensual.parquet)
     → "Gastos de Administración y Venta" (GAV) — distribuido por driver venta

  4. Parquet ventas_historico
     → # pedidos · # unidades · venta para drivers de distribución

Estructura del P&L (las 7 líneas que pidió Andrés):
  1. Ingreso por Venta
  2. Margen Directo
  3. Comisiones
  4. Margen de Contribución
  5. Costos Operativos (distribuidos por driver: pedidos / unidades / venta)
  6. Costos P&L GAV (distribuidos por % venta)
  7. EBIT

Filtros: Año · Trimestre · Mes · Canal · KAM · LN
Desglose elegible: Canal | LN | KAM
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from views._ops_contrib_helper import (
    contribucion_filtrada,
    contribucion_total,
    dimensiones_disponibles,
    estado_ultima_carga,
)
from views._fin_distribucion import (
    DRIVER_DEFAULT_POR_CC,
    cargar_costos_operativos,
    cargar_gav_corporativo,
    cargar_ventas_canal_ln,
    distribuir_monto_a_dimension,
    driver_default,
    driver_default_gav,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Paleta P&L
COLOR_HDR = "#1E293B"
COLOR_TOTAL = "#0F172A"
COLOR_SUBTOTAL = "#475569"
COLOR_POSITIVO = "#16A34A"
COLOR_NEGATIVO = "#DC2626"


# ============================================================
# FORMATTERS CHILENOS
# ============================================================
def _fmt_clp(v):
    """1.234.567 con paréntesis para negativos."""
    if v is None or pd.isna(v):
        return "—"
    n = abs(v)
    s = f"{n:,.0f}".replace(",", ".")
    return f"({s})" if v < 0 else s


def _fmt_pct(v, signo=False):
    if v is None or pd.isna(v):
        return "—"
    sig = "+" if (signo and v > 0) else ""
    return f"{sig}{v:.1f}%"


def _label_dim(d: str) -> str:
    return {"canal": "Canal", "tipo_negocio": "Línea de Negocio", "kam": "KAM"}.get(d, d)


# ============================================================
# HERO GLOBAL EMPRESA (sin filtros, KPIs + tendencia)
# ============================================================
def _hero_global_empresa(year: int):
    """Bloque al tope de la vista: KPIs consolidados YTD del año actual
    + mini-grafico tendencia mensual EBIT (real + proyectado a Dic).
    Independiente de los filtros — siempre muestra el agregado empresa.
    """
    import plotly.graph_objects as go
    from views._ops_forecast_costo_helper import (
        cargar_fcst_venta_mensual,
        cargar_costo_op_real_mensual,
    )

    hoy = datetime.now()
    # YTD = hasta mes-1 si es año actual (el mes corriente suele estar incompleto)
    if year == hoy.year:
        ytd_hasta = max(1, hoy.month - 1)
        meses_ytd = list(range(1, ytd_hasta + 1))
    else:
        ytd_hasta = 12
        meses_ytd = list(range(1, 13))

    # Consolidado YTD sin filtros (toda la empresa)
    res = contribucion_total(year=year, meses=meses_ytd)
    if not res:
        st.warning(f"⏳ Sin datos consolidados para {year}.")
        return

    df_costos_ytd = cargar_costos_operativos(year, meses_ytd, escenario="FCST")
    df_gav_ytd = cargar_gav_corporativo(year, meses_ytd, escenario="FCST")
    costo_op_ytd = float(df_costos_ytd["monto"].sum()) if not df_costos_ytd.empty else 0
    gav_ytd = float(df_gav_ytd["monto"].sum()) if not df_gav_ytd.empty else 0
    venta_ytd = res["venta"]
    contrib_ytd = res["contribucion"]
    ebit_ytd = contrib_ytd - costo_op_ytd - gav_ytd
    ebit_pct_ytd = (ebit_ytd / venta_ytd * 100) if venta_ytd else 0

    # ─── Card hero ────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,#064E3B 0%,#022C22 100%);'
        f'padding:18px 24px;border-radius:12px;color:white;margin-bottom:16px;">'
        f'<div style="font-size:0.75rem;letter-spacing:1.5px;opacity:0.7;'
        f'text-transform:uppercase;">🏢 Vista consolidada UnionX · YTD {year}</div>'
        f'<div style="font-size:0.85rem;opacity:0.85;margin-top:4px;">'
        f'Ene → {MESES_SHORT.get(ytd_hasta, str(ytd_hasta))} {year} · '
        f'todos los canales · todos los KAMs · todas las LNs · '
        f'fuente: KAM oficial + P&L Drive (FCST)</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("💰 Venta REAL", f"${_fmt_clp(venta_ytd / 1_000_000)} MM")
    k2.metric("📈 Margen Contrib.",
                f"${_fmt_clp(contrib_ytd / 1_000_000)} MM",
                delta=_fmt_pct(res.get("mc_pct", 0)))
    k3.metric("⚙️ Costo Operativo",
                f"${_fmt_clp(costo_op_ytd / 1_000_000)} MM")
    k4.metric("🏢 GAV Puro",
                f"${_fmt_clp(gav_ytd / 1_000_000)} MM",
                help="Áreas del P&L Drive EXCLUYENDO OPERACIONES, LOGISTICA, "
                     "POSTVENTA (esas ya están en Costo Operativo)")
    k5.metric("🎯 EBIT estimado",
                f"${_fmt_clp(ebit_ytd / 1_000_000)} MM",
                delta=_fmt_pct(ebit_pct_ytd))

    # ─── Mini tendencia mensual EBIT: Real + Proyectado ───────────
    try:
        df_trend = _calcular_tendencia_ebit_anual(year)
        if not df_trend.empty:
            fig = go.Figure()
            df_real = df_trend[df_trend["tipo"] == "Real"]
            df_proy = df_trend[df_trend["tipo"] == "Proyectado"]
            # Línea real (sólida)
            fig.add_trace(go.Scatter(
                x=df_real["mes_label"], y=df_real["ebit_mm"],
                mode="lines+markers",
                name="Real (FCST cerrado)",
                line=dict(color="#16A34A", width=3),
                marker=dict(size=8),
                hovertemplate="<b>%{x}</b><br>EBIT: $%{y:.1f} MM<extra></extra>",
            ))
            # Línea proyectada (punteada). Si hay ambos, unir con la última real.
            if not df_proy.empty:
                # Concatenar la última real al inicio del proyectado para enlazar
                if not df_real.empty:
                    ultima_real = df_real.iloc[-1:].copy()
                    df_proy_link = pd.concat([ultima_real, df_proy],
                                              ignore_index=True)
                else:
                    df_proy_link = df_proy
                fig.add_trace(go.Scatter(
                    x=df_proy_link["mes_label"], y=df_proy_link["ebit_mm"],
                    mode="lines+markers",
                    name="Proyectado (FCST)",
                    line=dict(color="#F59E0B", width=2, dash="dot"),
                    marker=dict(size=7, symbol="diamond"),
                    hovertemplate="<b>%{x}</b><br>EBIT proy: $%{y:.1f} MM<extra></extra>",
                ))
            fig.add_hline(y=0, line_color="#0F172A", line_width=1.5,
                            line_dash="solid")
            fig.update_layout(
                height=240,
                margin=dict(l=10, r=10, t=30, b=10),
                title=dict(
                    text=f"Tendencia EBIT mensual {year} · Real + Proyectado",
                    font=dict(size=13, color="#1E293B"),
                ),
                xaxis_title="", yaxis_title="MM CLP",
                plot_bgcolor="white",
                xaxis=dict(gridcolor="#F1F5F9"),
                yaxis=dict(gridcolor="#F1F5F9"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                              xanchor="right", x=1, font=dict(size=10)),
            )
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.caption(f"_(Tendencia mensual no disponible: {e})_")


def _calcular_tendencia_ebit_anual(year: int) -> pd.DataFrame:
    """Devuelve DataFrame con EBIT mes a mes mezclando:
      - Real: meses con FCST cerrado en el P&L (mes < mes actual del año en curso)
      - Proyectado: meses futuros usando FCST de venta + ratios historicos

    Cols: [mes, mes_label, tipo, venta_mm, contrib_mm, costo_op_mm, gav_mm,
            ebit_mm]
    """
    from views._ops_forecast_costo_helper import (
        cargar_fcst_venta_mensual,
        cargar_costo_op_real_mensual,
    )

    hoy = datetime.now()
    mes_actual = hoy.month if year == hoy.year else 13

    # Costo OP real mes a mes (del P&L Drive con escenario FCST)
    df_costo_real = cargar_costo_op_real_mensual(year=year)
    # En MILES de CLP (parquet original). Convertir a CLP enteros (× 1000).
    if not df_costo_real.empty:
        df_costo_real["costo_op_clp"] = df_costo_real["costo_op_total"] * 1000

    # Venta FCST mes a mes (del fcst_eerr.parquet)
    venta_fcst = cargar_fcst_venta_mensual(year=year)

    rows = []
    for m in range(1, 13):
        es_real = m < mes_actual
        # Ventas/MC del mes: usar contribucion_total filtrada por ese mes
        res_m = contribucion_total(year=year, meses=[m])
        venta_m = res_m.get("venta", 0) if res_m else 0
        contrib_m = res_m.get("contribucion", 0) if res_m else 0
        # Para meses proyectados: si no hay venta KAM aún, usar FCST de venta
        # y estimar MC con ratio MC% del YTD real
        if not es_real or venta_m == 0:
            venta_fcst_m = float(venta_fcst.get(m, 0))
            if venta_fcst_m > 0:
                venta_m = venta_fcst_m
                # MC% proyectado: usar ratio YTD real
                meses_ytd = list(range(1, max(1, hoy.month)))
                res_ytd = contribucion_total(year=year, meses=meses_ytd)
                mc_pct_ytd = res_ytd.get("mc_pct", 0) / 100 if res_ytd else 0.30
                contrib_m = venta_m * mc_pct_ytd

        # Costo OP del mes
        if not df_costo_real.empty and m in df_costo_real["mes"].values:
            costo_op_m = float(df_costo_real[df_costo_real["mes"] == m]
                                ["costo_op_clp"].iloc[0])
        else:
            costo_op_m = 0  # mes sin FCST cargado

        # GAV del mes (proporcional a venta — proxy hasta que tengamos GAV mensual)
        df_gav_m = cargar_gav_corporativo(year, [m], escenario="FCST")
        gav_m = float(df_gav_m["monto"].sum()) if not df_gav_m.empty else 0

        ebit_m = contrib_m - costo_op_m - gav_m

        rows.append({
            "mes": m,
            "mes_label": MESES_SHORT.get(m, str(m)),
            "tipo": "Real" if es_real else "Proyectado",
            "venta_mm": venta_m / 1_000_000,
            "contrib_mm": contrib_m / 1_000_000,
            "costo_op_mm": costo_op_m / 1_000_000,
            "gav_mm": gav_m / 1_000_000,
            "ebit_mm": ebit_m / 1_000_000,
        })
    df = pd.DataFrame(rows)
    # Filtrar meses sin nada de info (venta=0 Y costo_op=0)
    df = df[(df["venta_mm"] > 0) | (df["costo_op_mm"] > 0)].copy()
    return df


# Necesario para el hero (constante de meses cortos)
MESES_SHORT = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
                7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}


# ============================================================
# RENDER
# ============================================================
def render():
    # ─── CSS profesional ─────────────────────────────────────────────────
    st.markdown("""
    <style>
    /* Tipografía y spacing más profesional */
    .stMarkdown h1 { font-weight: 600; letter-spacing: -0.02em; color: #0F172A; }
    .stMarkdown h3 { font-weight: 600; color: #1E293B; margin-top: 1.2rem; }
    .stCaption { color: #64748B; }

    /* KPI metrics más cuidados */
    [data-testid="stMetric"] {
        background: white;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.75rem !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: #64748B !important;
        font-weight: 600;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
        font-weight: 700 !important;
        color: #0F172A !important;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.8rem !important;
        font-weight: 600 !important;
    }

    /* Cards de filtros */
    .pyl-filter-card {
        background: linear-gradient(180deg, #F8FAFC 0%, #F1F5F9 100%);
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 14px;
    }
    .pyl-filter-card-title {
        font-weight: 600;
        color: #475569;
        font-size: 0.78rem;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-bottom: 10px;
    }

    /* Banner período activo más sobrio */
    .pyl-banner {
        background: #EFF6FF;
        border-left: 3px solid #3B82F6;
        padding: 10px 16px;
        border-radius: 6px;
        margin-bottom: 16px;
        font-size: 0.88rem;
        color: #1E3A8A;
    }
    .pyl-banner-ok {
        background: #F0FDF4;
        border-left-color: #16A34A;
        color: #14532D;
    }
    .pyl-banner-warn {
        background: #FEF3C7;
        border-left-color: #F59E0B;
        color: #78350F;
    }
    .pyl-banner-error {
        background: #FEF2F2;
        border-left-color: #DC2626;
        color: #7F1D1D;
    }

    /* Tabs un poco más grandes */
    button[data-baseweb="tab"] {
        font-weight: 500;
    }
    </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### **P&L por LN**")
        st.caption("Margen real por canal · KAM · línea de negocio")
        st.divider()

    st.title("P&L por Línea de Negocio")
    st.caption(
        "Cruce de Contribución KAM (oficial) + Costos Operativos + GAV "
        "del Control de Gestión. Filtros multi-dimensión, desglose flexible "
        "y validación de calce con el P&L corporativo."
    )

    # ─── Cargar dimensiones disponibles ─────────────────────────────────
    dims = dimensiones_disponibles()
    estado = estado_ultima_carga()

    if not dims["anios"]:
        # Diagnóstico detallado
        st.error("❌ **Sin datos del Sheet KAM ni del parquet de fallback**")
        if estado.get("error"):
            st.code(f"Detalle del error: {estado['error']}", language="text")
        st.markdown(
            "**Para resolver:**\n"
            "- 🔧 **Solución rápida:** correr `python extract_kam_contribucion.py` "
            "localmente y commitear el parquet generado en `data/finanzas/contribucion_kam.parquet`\n"
            "- 🌐 **Solución de largo plazo:** agregar `gcp_service_account` a "
            "los Streamlit Secrets de la app Finanzas (copiando desde la app Operaciones)"
        )
        return

    # Banner si los datos vienen del parquet local (no del Sheet en vivo)
    if estado.get("fuente") == "parquet_local":
        from datetime import datetime as _dt
        from views._ops_contrib_helper import KAM_FALLBACK_PARQUET
        try:
            mod_ts = _dt.fromtimestamp(KAM_FALLBACK_PARQUET.stat().st_mtime)
            mod_str = mod_ts.strftime("%d/%m/%Y %H:%M")
        except Exception:
            mod_str = "fecha desconocida"
        st.info(
            f"📦 **Fuente: parquet local** (cache del Sheet KAM al {mod_str}). "
            f"Para datos en vivo, configurá `gcp_service_account` en Streamlit Secrets "
            f"de la app Finanzas."
        )

    # ─── HERO GLOBAL EMPRESA (KPIs + tendencia, antes de filtros) ─────
    # Año para el hero: el año actual (o el último disponible si no hay)
    _year_actual = datetime.now().year
    _year_hero = _year_actual if _year_actual in dims["anios"] else dims["anios"][-1]
    with st.spinner("📊 Cargando vista consolidada empresa..."):
        _hero_global_empresa(_year_hero)

    st.divider()

    # ─── FILTROS (compactos, agrupados visualmente) ─────────────────────
    st.markdown(
        '<div style="background:#F8FAFC;padding:14px 18px;border-radius:10px;'
        'border:1px solid #E2E8F0;margin-bottom:14px;">'
        '<div style="font-weight:600;color:#475569;font-size:0.85rem;'
        'margin-bottom:10px;">🎛️ FILTROS · profundizá por dimensión</div>',
        unsafe_allow_html=True,
    )

    # Fila 1: Año + Período + Selector específico
    f1c1, f1c2, f1c3 = st.columns([1, 2, 3])
    with f1c1:
        year_actual = datetime.now().year
        year_default = year_actual if year_actual in dims["anios"] else dims["anios"][-1]
        year = st.selectbox("📅 Año", dims["anios"],
                             index=dims["anios"].index(year_default),
                             label_visibility="visible")
    dims_year = dimensiones_disponibles(year)

    with f1c2:
        modo_periodo = st.radio(
            "🗓️ Período", ["YTD", "Trimestre", "Mes(es)"],
            horizontal=True, index=0,
        )

    meses_sel = []
    if modo_periodo == "YTD":
        if year == year_actual:
            meses_sel = list(range(1, datetime.now().month + 1))
        else:
            meses_sel = list(range(1, 13))
        periodo_label = f"YTD {year}"
        with f1c3:
            st.markdown(f"<div style='padding-top:28px;color:#64748B;'>"
                         f"Meses incluidos: <code>{meses_sel}</code></div>",
                         unsafe_allow_html=True)
    elif modo_periodo == "Trimestre":
        with f1c3:
            trim_options = ["Q1", "Q2", "Q3", "Q4"]
            trims = st.multiselect("Trimestre(s)", trim_options,
                                     default=[trim_options[0]],
                                     label_visibility="collapsed",
                                     placeholder="Selecciona Q1/Q2/Q3/Q4")
            mapa_q = {1: [1, 2, 3], 2: [4, 5, 6], 3: [7, 8, 9], 4: [10, 11, 12]}
            for t in trims:
                meses_sel.extend(mapa_q[int(t.replace("Q", ""))])
            periodo_label = f"{', '.join(trims) or '?'} {year}"
    else:
        with f1c3:
            meses_sel = st.multiselect(
                "Mes(es)", list(range(1, 13)),
                default=[datetime.now().month] if year == year_actual else [1],
                format_func=lambda m: f"{m:02d}",
                label_visibility="collapsed",
                placeholder="Selecciona uno o más meses",
            )
            periodo_label = f"Meses {meses_sel} {year}"

    # Fila 2: Filtros multi-dim
    f2c1, f2c2, f2c3 = st.columns(3)
    with f2c1:
        canales_sel = st.multiselect(
            "📺 Canal", dims_year["canales"], default=[],
            placeholder="Todos los canales",
        )
    with f2c2:
        kams_sel = st.multiselect(
            "👤 KAM", dims_year["kams"], default=[],
            placeholder="Todos los KAMs",
        )
    with f2c3:
        lns_sel = st.multiselect(
            "🏷️ Línea de Negocio", dims_year["tipos_negocio"], default=[],
            placeholder="Todas las LNs",
        )

    # Fila 3: Desglose
    f3c1, f3c2 = st.columns([2, 5])
    with f3c1:
        st.markdown("<div style='font-weight:600;color:#475569;padding-top:8px;'>"
                     "🔀 Desglosar por:</div>", unsafe_allow_html=True)
    with f3c2:
        desglose = st.radio(
            "Desglose", ["canal", "tipo_negocio", "kam"],
            format_func=lambda x: {
                "canal": "📺 Canal",
                "tipo_negocio": "🏷️ Línea de Negocio",
                "kam": "👤 KAM",
            }[x],
            horizontal=True, index=0, label_visibility="collapsed",
        )

    st.markdown("</div>", unsafe_allow_html=True)

    # Banner período activo
    hay_filtro_dim = bool(canales_sel or kams_sel or lns_sel)
    filtros_resumen = []
    if canales_sel:
        filtros_resumen.append(f"{len(canales_sel)} canal(es)")
    if kams_sel:
        filtros_resumen.append(f"{len(kams_sel)} KAM(s)")
    if lns_sel:
        filtros_resumen.append(f"{len(lns_sel)} LN(s)")
    filtros_txt = " · ".join(filtros_resumen) if filtros_resumen else "sin filtros (todo el universo)"

    st.markdown(
        f'<div class="pyl-banner">'
        f'<strong>Período activo:</strong> {periodo_label} · '
        f'desglose por <strong>{_label_dim(desglose)}</strong> · '
        f'<strong>Filtros:</strong> {filtros_txt}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ─── Cargar inputs filtrados ────────────────────────────────────────
    canales_f = canales_sel or None
    kams_f = kams_sel or None
    lns_f = lns_sel or None

    with st.spinner("📥 Cargando datos (KAM + Costos OP + Ventas + GAV)..."):
        df_contrib = contribucion_filtrada(
            year=year, meses=meses_sel,
            canales=canales_f, kams=kams_f, tipos_negocio=lns_f,
            desglose_por=desglose,
        )
        df_costos = cargar_costos_operativos(
            year, meses_sel, escenario="FCST",
            incluir_cuenta_analitica=True,
        )
        # IMPORTANTE: dos versiones de ventas
        # 1. df_ventas_drivers = TODA la venta del período (sin filtros)
        #    Se usa para calcular pesos de distribución del costo OP/GAV.
        #    Bug fix: si filtramos a "Canal=ML", df_ventas_filtrado tendría
        #    solo ML → pesos serían 100% para ML → ML recibiría TODO el
        #    costo operativo (que es ABSURDO porque ese costo es de toda
        #    la operación, no solo de ML).
        # 2. df_ventas_filtrado = solo lo del filtro, para mostrar
        #    volúmenes en tab Detalle.
        df_ventas_drivers = cargar_ventas_canal_ln(
            year, meses_sel,
            canales=None, kams=None, tipos_negocio=None,  # SIN FILTROS
        )
        df_ventas_filtrado = cargar_ventas_canal_ln(
            year, meses_sel,
            canales=canales_f, kams=kams_f, tipos_negocio=lns_f,
        )
        # Alias para retrocompatibilidad de las secciones que muestran info
        df_ventas = df_ventas_filtrado

        # GAV "puro" por área (sin duplicar lo operativo)
        df_gav = cargar_gav_corporativo(year, meses_sel, escenario="FCST")
        gav_total = df_gav["monto"].sum() if not df_gav.empty else 0

    if df_contrib.empty:
        st.error(
            f"❌ **Sin datos KAM para los filtros aplicados.**\n\n"
            f"- Período: `{periodo_label}` · meses {sorted(set(meses_sel))}\n"
            f"- Canales: `{canales_sel or 'todos'}`\n"
            f"- KAMs: `{kams_sel or 'todos'}`\n"
            f"- LNs: `{lns_sel or 'todas'}`"
        )
        meses_disponibles_anio = estado.get("meses_por_anio", {}).get(year, [])
        if meses_disponibles_anio:
            st.info(
                f"ℹ️ **El Sheet KAM tiene datos para {year} en los meses:** "
                f"`{meses_disponibles_anio}`. Probá con uno de esos."
            )
        else:
            anios_disp = estado.get("anios", [])
            st.info(
                f"ℹ️ **Años con datos en el Sheet:** `{anios_disp}`. "
                f"El año {year} no tiene datos cargados."
            )
        return

    # ─── Recuperar override drivers (desde tab Drivers en session_state) ─
    driver_override = st.session_state.get("fin_pyl_driver_override", {})

    # ─── DISTRIBUIR COSTOS AHORA (antes del resumen) ────────────────────
    # Necesitamos los montos asignados a las dimensiones VISIBLES para
    # calcular el EBIT correcto (no usar totales absolutos del período).
    valores_visibles = set(df_contrib[desglose].tolist())

    costo_op_por_dim = {}
    costo_op_drilldown = []
    if not df_costos.empty and not df_ventas_drivers.empty:
        for _, c in df_costos.iterrows():
            cc = c["centro_costo"]
            driver = driver_override.get(cc, driver_default(cc))
            asignacion = distribuir_monto_a_dimension(
                c["monto"], df_ventas_drivers, driver, dimension=desglose,
            )
            for k, v in asignacion.items():
                if k not in valores_visibles:
                    continue
                costo_op_por_dim[k] = costo_op_por_dim.get(k, 0) + v
                costo_op_drilldown.append({
                    "Sub-área": c["sub_area"],
                    "Centro de Costo": cc,
                    "Cuenta Analítica": c.get("cuenta_analitica", "—"),
                    "Driver": driver,
                    _label_dim(desglose): k,
                    "Monto": v,
                })

    gav_por_dim = {}
    gav_drilldown = []
    if not df_gav.empty and not df_ventas_drivers.empty:
        for _, g in df_gav.iterrows():
            area = g["area"]
            driver = driver_default_gav(area)
            asignacion = distribuir_monto_a_dimension(
                g["monto"], df_ventas_drivers, driver, dimension=desglose,
            )
            for k, v in asignacion.items():
                if k not in valores_visibles:
                    continue
                gav_por_dim[k] = gav_por_dim.get(k, 0) + v
                gav_drilldown.append({
                    "Área GAV": area,
                    "Driver": driver,
                    _label_dim(desglose): k,
                    "Monto": v,
                })

    # ─── Resumen consolidado (usa montos ASIGNADOS al filtro visible) ──
    res = contribucion_total(
        year=year, meses=meses_sel,
        canales=canales_f, kams=kams_f, tipos_negocio=lns_f,
    )
    venta_total = res.get("venta", 0)
    contrib_total = res.get("contribucion", 0)
    # MONTOS DEL PERÍODO (info — no afectados por filtro)
    costo_op_total_periodo = df_costos["monto"].sum() if not df_costos.empty else 0
    gav_total_periodo = df_gav["monto"].sum() if not df_gav.empty else 0
    # MONTOS ASIGNADOS A LOS FILTROS VISIBLES (lo que se resta para EBIT)
    costo_op_asignado = sum(costo_op_por_dim.values())
    gav_asignado = sum(gav_por_dim.values())
    ebit_total = contrib_total - costo_op_asignado - gav_asignado
    mc_pct = res.get("mc_pct", 0)
    ebit_pct = (ebit_total / venta_total * 100) if venta_total else 0

    st.markdown("### 📊 Consolidado del período (con filtros)")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Venta REAL", f"${_fmt_clp(venta_total / 1_000_000)} MM")
    k2.metric("Contribución", f"${_fmt_clp(contrib_total / 1_000_000)} MM",
              delta=_fmt_pct(mc_pct))
    k3.metric(
        "Costo OP asignado",
        f"${_fmt_clp(costo_op_asignado / 1_000_000)} MM",
        help=f"Total Costo OP del período: ${_fmt_clp(costo_op_total_periodo / 1_000_000)} MM. "
             f"Acá se muestra solo lo asignado a los filtros aplicados, según los drivers.",
    )
    k4.metric(
        "GAV asignado",
        f"${_fmt_clp(gav_asignado / 1_000_000)} MM",
        help=f"Total GAV puro del período: ${_fmt_clp(gav_total_periodo / 1_000_000)} MM. "
             f"GAV = control_gestion menos áreas operativas (sin duplicar con Costo OP). "
             f"Acá se muestra solo lo asignado a los filtros visibles.",
    )
    k5.metric("EBIT estimado", f"${_fmt_clp(ebit_total / 1_000_000)} MM",
              delta=_fmt_pct(ebit_pct))

    # ─── Cobertura del filtro (% que representa el subset filtrado) ────
    _render_cobertura_filtro(
        df_ventas_drivers, df_ventas_filtrado,
        costo_op_total_periodo, costo_op_asignado,
        gav_total_periodo, gav_asignado,
        hay_filtro=hay_filtro_dim,
    )

    # ─── Alarma de calce (¿la suma distribuida = total?) ───────────────
    _render_alarma_calce(
        df_costos, df_gav, df_ventas_drivers, df_contrib,
        desglose, driver_override,
    )

    st.divider()

    # ─── Tabs ───────────────────────────────────────────────────────────
    tab_pyl, tab_proy, tab_drivers, tab_detalle, tab_help, tab_roadmap = st.tabs([
        "💰 P&L (7 líneas)",
        "🔮 Proyección FCST",
        "🎚️ Drivers",
        "📋 Detalle",
        "ℹ️ Cómo se calcula",
        "🚀 Roadmap",
    ])

    # ─── TAB PROYECCIÓN FCST ────────────────────────────────────────────
    with tab_proy:
        _render_tab_proyeccion_fcst(year)

    # ─── TAB DRIVERS ────────────────────────────────────────────────────
    with tab_drivers:
        st.markdown(
            f"### 🎚️ Drivers por Centro de Costo\n"
            f"Cada CC se distribuye a los valores de la dimensión "
            f"`{_label_dim(desglose)}` según un driver."
        )
        st.info(
            "**Drivers disponibles:**\n"
            "- 🟢 `pedidos` — proporcional a # pedidos\n"
            "- 🟡 `unidades` — proporcional a # unidades despachadas\n"
            "- 🔵 `venta` — proporcional a venta neta\n"
            "- ⚪ `equitativo` — reparto igual"
        )

        if df_costos.empty:
            st.warning("Sin costos operativos para el período seleccionado.")
        else:
            df_drivers_ui = df_costos.copy()
            df_drivers_ui["driver"] = df_drivers_ui["centro_costo"].apply(driver_default)
            df_drivers_ui["monto_M"] = (df_drivers_ui["monto"] / 1000).round(0)
            df_drivers_ui = df_drivers_ui[
                ["sub_area", "centro_costo", "tipo_costo", "monto_M", "driver"]
            ].rename(columns={
                "sub_area": "Sub-área",
                "centro_costo": "Centro de Costo",
                "tipo_costo": "F/V",
                "monto_M": "Monto (M$)",
                "driver": "Driver",
            })

            edited = st.data_editor(
                df_drivers_ui,
                use_container_width=True, hide_index=True,
                disabled=["Sub-área", "Centro de Costo", "F/V", "Monto (M$)"],
                column_config={
                    "Driver": st.column_config.SelectboxColumn(
                        "Driver",
                        options=["pedidos", "unidades", "venta", "equitativo"],
                        required=True,
                    ),
                    "Monto (M$)": st.column_config.NumberColumn(
                        "Monto (M$)", format="%.0f"
                    ),
                },
                key="drivers_editor",
            )

            driver_override = {}
            for _, r in edited.iterrows():
                cc = r["Centro de Costo"]
                if r["Driver"] != driver_default(cc):
                    driver_override[cc] = r["Driver"]
            st.session_state["fin_pyl_driver_override"] = driver_override

            if driver_override:
                st.success(
                    f"✏️ {len(driver_override)} CC con driver personalizado: "
                    f"{', '.join(list(driver_override.keys())[:5])}"
                    f"{'...' if len(driver_override) > 5 else ''}"
                )

        st.markdown("---")
        st.markdown(
            "**Driver de GAV:** `% venta` (no editable — gastos administrativos "
            "del corporativo se asocian al revenue)."
        )

        st.markdown("---")
        st.markdown("**Mapping default por tipo de costo:**")
        df_defaults = pd.DataFrame([
            {"Centro de Costo": k, "Driver default": v}
            for k, v in DRIVER_DEFAULT_POR_CC.items()
            if "Ó" not in k and "Á" not in k and "Í" not in k
        ])
        st.dataframe(df_defaults, use_container_width=True, hide_index=True)

    # NOTA: la distribución (costo_op_por_dim, gav_por_dim, drilldowns)
    # ya se calculó arriba antes del resumen consolidado, para que los
    # KPIs reflejen la asignación correcta a los filtros visibles.

    # ─── TAB P&L ────────────────────────────────────────────────────────
    with tab_pyl:
        st.markdown(f"### 💰 P&L por **{_label_dim(desglose)}**")
        st.caption(
            f"Período `{periodo_label}` · Filtros: "
            f"{len(canales_sel) or 'todos'} canal(es), "
            f"{len(kams_sel) or 'todos'} KAM(s), "
            f"{len(lns_sel) or 'todas'} LN(s)"
        )

        df_pyl_table = _construir_pyl_7lineas(
            df_contrib, costo_op_por_dim, gav_por_dim, desglose,
        )

        if df_pyl_table.empty:
            st.warning("No hay datos para mostrar.")
        else:
            html = _render_pyl_html(df_pyl_table)
            st.markdown(html, unsafe_allow_html=True)

            # ─── Drill-down auto cuando hay filtros activos ────────
            _render_drilldown_filtrado(
                costo_op_drilldown=costo_op_drilldown,
                gav_drilldown=gav_drilldown,
                desglose=desglose,
                canales_sel=canales_sel, kams_sel=kams_sel, lns_sel=lns_sel,
                costo_op_asignado=costo_op_asignado,
                gav_asignado=gav_asignado,
                contrib_total=contrib_total,
            )

            # ─── Transparencia del GAV (áreas incluidas/excluidas) ─
            _render_transparencia_gav(df_gav, year, meses_sel)

            # Expander con cálculo del Costo OP y GAV (cómo se distribuye)
            with st.expander("🔬 ¿Cómo se calculan Costo OP y GAV?",
                              expanded=False):
                st.markdown(
                    f"**Costo Operativo total del período:** "
                    f"`${_fmt_clp(sum(c['monto'] for c in [{'monto': r['Monto']} for r in costo_op_drilldown]) / 1_000_000) if costo_op_drilldown else '0'} MM`"
                )
                ec1, ec2 = st.columns(2)
                with ec1:
                    st.markdown("**Costo OP por Centro de Costo:**")
                    if costo_op_drilldown:
                        df_op_resumen = pd.DataFrame(costo_op_drilldown)
                        agg_op = df_op_resumen.groupby(
                            ["Sub-área", "Centro de Costo", "Driver"],
                            as_index=False,
                        ).agg(Monto=("Monto", "sum"))
                        agg_op["Monto (MM$)"] = (agg_op["Monto"] / 1_000_000).round(1)
                        agg_op = agg_op[["Sub-área", "Centro de Costo",
                                          "Driver", "Monto (MM$)"]]
                        agg_op = agg_op.sort_values("Monto (MM$)", ascending=False)
                        st.dataframe(agg_op, use_container_width=True,
                                      hide_index=True, height=280)
                    else:
                        st.info("Sin costos OP en el período.")
                with ec2:
                    st.markdown("**GAV por área:**")
                    if gav_drilldown:
                        df_gav_resumen = pd.DataFrame(gav_drilldown)
                        agg_gav = df_gav_resumen.groupby(
                            ["Área GAV", "Driver"],
                            as_index=False,
                        ).agg(Monto=("Monto", "sum"))
                        agg_gav["Monto (MM$)"] = (agg_gav["Monto"] / 1_000_000).round(1)
                        agg_gav = agg_gav[["Área GAV", "Driver", "Monto (MM$)"]]
                        agg_gav = agg_gav.sort_values("Monto (MM$)", ascending=False)
                        st.dataframe(agg_gav, use_container_width=True,
                                      hide_index=True, height=280)
                    else:
                        st.info("Sin GAV en el período.")

                st.markdown(
                    "💡 **Para ver el detalle de cómo cada Centro de Costo se "
                    f"distribuye a cada {_label_dim(desglose).lower()}** (matriz "
                    "completa con todos los valores), andá al tab **'📋 Detalle'** → "
                    "Sección 3 y 4."
                )

            st.markdown("---")
            _render_insights(df_pyl_table, desglose)

    # ─── TAB DETALLE ────────────────────────────────────────────────────
    with tab_detalle:
        # ─── Sección 1: Costos OP a distribuir ──────────────────────────
        st.markdown("### 📋 1) Costos Operativos a distribuir")
        if df_costos.empty:
            st.info("Sin costos en el período.")
        else:
            df_show = df_costos.copy()
            df_show["driver"] = df_show["centro_costo"].apply(
                lambda cc: driver_override.get(cc, driver_default(cc))
            )
            df_show["monto_MM"] = (df_show["monto"] / 1_000_000).round(1)
            # Incluir cuenta_analitica si está disponible (desglose más fino)
            cols_show = ["sub_area", "centro_costo"]
            if "cuenta_analitica" in df_show.columns:
                cols_show.append("cuenta_analitica")
            cols_show.extend(["tipo_costo", "monto_MM", "driver"])
            df_show = df_show[cols_show].rename(columns={
                "sub_area": "Sub-área",
                "centro_costo": "Centro de Costo",
                "cuenta_analitica": "Cuenta Analítica",
                "tipo_costo": "F/V",
                "monto_MM": "Monto (MM$)",
                "driver": "Driver",
            })
            st.dataframe(df_show, use_container_width=True, hide_index=True,
                          height=380)

            tot_fijo = df_costos[df_costos["tipo_costo"] == "FIJO"]["monto"].sum()
            tot_var = df_costos[df_costos["tipo_costo"] == "VARIABLE"]["monto"].sum()
            st.markdown(
                f"**Totales OP:** Fijo `${_fmt_clp(tot_fijo / 1_000_000)} MM` · "
                f"Variable `${_fmt_clp(tot_var / 1_000_000)} MM` · "
                f"**Total `${_fmt_clp((tot_fijo + tot_var) / 1_000_000)} MM`**"
            )

        # ─── Sección 2: GAV "puro" por área ─────────────────────────────
        st.markdown("---")
        st.markdown("### 🏢 2) GAV por área (sin operativo)")
        st.caption(
            "Áreas del Control de Gestión Drive, **excluyendo** OPERACIONES, "
            "LOGÍSTICA y POSTVENTA (ya están en la tabla de arriba)."
        )
        if df_gav.empty:
            st.info("Sin GAV en el período.")
        else:
            df_gav_show = df_gav.copy()
            df_gav_show["driver"] = df_gav_show["area"].apply(driver_default_gav)
            df_gav_show["monto_MM"] = (df_gav_show["monto"] / 1_000_000).round(1)
            df_gav_show = df_gav_show[["area", "monto_MM", "driver"]].rename(columns={
                "area": "Área",
                "monto_MM": "Monto (MM$)",
                "driver": "Driver",
            })
            st.dataframe(df_gav_show, use_container_width=True, hide_index=True)
            st.markdown(
                f"**Total GAV puro:** `${_fmt_clp(gav_total / 1_000_000)} MM`"
            )

        # ─── Sección 3: Drilldown — Costo OP asignado a cada dimensión ─
        st.markdown("---")
        st.markdown(f"### 🎯 3) Drilldown: Costo OP asignado por {_label_dim(desglose)}")
        st.caption(
            f"Cómo cada Centro de Costo se reparte a cada {_label_dim(desglose).lower()} "
            f"según su driver."
        )
        if costo_op_drilldown:
            df_dr = pd.DataFrame(costo_op_drilldown)
            # Pivot: filas = CC, cols = dimensión, valor = monto
            pivot = df_dr.pivot_table(
                index=["Sub-área", "Centro de Costo", "Driver"],
                columns=_label_dim(desglose),
                values="Monto",
                aggfunc="sum",
                fill_value=0,
            )
            pivot["TOTAL"] = pivot.sum(axis=1)
            pivot = (pivot / 1_000_000).round(1)  # MM
            pivot = pivot.sort_values("TOTAL", ascending=False)
            try:
                styled = pivot.style.format("{:,.1f}").background_gradient(
                    cmap="Reds", subset=[c for c in pivot.columns if c != "TOTAL"]
                )
            except (ImportError, ModuleNotFoundError):
                styled = pivot.style.format("{:,.1f}")
            st.dataframe(styled, use_container_width=True)
            st.caption("Cifras en MM$. Cada fila se distribuye según su driver.")
        else:
            st.info("Sin distribución calculada.")

        # ─── Sección 4: Drilldown — GAV por área a cada dimensión ──────
        st.markdown("---")
        st.markdown(f"### 🏢 4) Drilldown: GAV asignado por {_label_dim(desglose)}")
        if gav_drilldown:
            df_gdr = pd.DataFrame(gav_drilldown)
            pivot_g = df_gdr.pivot_table(
                index=["Área GAV", "Driver"],
                columns=_label_dim(desglose),
                values="Monto",
                aggfunc="sum",
                fill_value=0,
            )
            pivot_g["TOTAL"] = pivot_g.sum(axis=1)
            pivot_g = (pivot_g / 1_000_000).round(1)
            pivot_g = pivot_g.sort_values("TOTAL", ascending=False)
            try:
                styled_g = pivot_g.style.format("{:,.1f}").background_gradient(
                    cmap="Blues", subset=[c for c in pivot_g.columns if c != "TOTAL"]
                )
            except (ImportError, ModuleNotFoundError):
                styled_g = pivot_g.style.format("{:,.1f}")
            st.dataframe(styled_g, use_container_width=True)
            st.caption("Cifras en MM$. Cada área se distribuye con su driver propio.")

        st.markdown("---")
        st.markdown(f"### 📊 Volumen por {_label_dim(desglose)}")
        if df_ventas.empty:
            st.info("Sin ventas en el período.")
        else:
            agg = df_ventas.groupby(desglose, as_index=False).agg(
                n_pedidos=("n_pedidos", "sum"),
                n_unidades=("n_unidades", "sum"),
                venta_neta=("venta_neta", "sum"),
            ).sort_values("venta_neta", ascending=False)
            agg["% venta"] = (agg["venta_neta"] / agg["venta_neta"].sum() * 100).round(1)

            st.dataframe(
                agg.style.format({
                    "n_pedidos": "{:,.0f}",
                    "n_unidades": "{:,.0f}",
                    "venta_neta": "${:,.0f}",
                    "% venta": "{:.1f}%",
                }),
                use_container_width=True, hide_index=True,
            )

    # ─── TAB AYUDA ──────────────────────────────────────────────────────
    with tab_help:
        st.markdown("""
### 🧭 Estructura del P&L (7 líneas)

| # | Línea | Origen | Cómo se calcula |
|---|---|---|---|
| 1 | **Ingreso por Venta** | Sheet KAM | `Venta REAL KAM` (suma con filtros) |
| 2 | **Margen Directo** | Sheet KAM | `Venta − Costo Venta` |
| 3 | **Comisiones** | Sheet KAM | `Comisión Venta + Comisión Envío + Marketing` |
| 4 | **Margen de Contribución** | Sheet KAM | `Margen Directo − Comisiones` ✅ oficial |
| 5 | **Costos Operativos** | Sheet OPERACIONES | Distribuido por driver según CC: `pedidos` / `unidades` / `venta` / `equitativo` |
| 6 | **Costos P&L GAV** | Control de Gestión Drive | Solo áreas NO operativas (sin OPS/LOG/PV); cada área distribuida con su driver |
| 7 | **EBIT** | Calculado | `Margen de Contribución − Costos OP − GAV puro` |

#### ⚙️ Unidades
**Todas las cifras se muestran en MM$ (millones de pesos chilenos).**
Internamente se trabaja en CLP enteros (KAM viene en CLP, Sheet OPERACIONES y
Control Gestión vienen en miles → se multiplican × 1000 para alinear).

#### 🚫 Cómo evitamos duplicar GAV con Costo OP
El P&L corporativo agrupa TODO el gasto bajo "Gastos de Administración y Venta".
Si lo sumáramos completo al Costo OP, duplicaríamos los gastos operativos.
Solución: usar el **Control de Gestión Drive** que separa por área. Excluimos
áreas operativas (OPERACIONES, LOGÍSTICA, POSTVENTA) que ya están en el Sheet
OPERACIONES, y nos quedamos con el "GAV puro" (COMERCIAL, FIN/ADMIN, GRUPO ETER,
MARKETING, LEGALES).

#### Drivers de distribución del Costo OP

| Tipo de Costo | Driver default | Por qué |
|---|---|---|
| REMUNERACIONES | # pedidos | Operadores procesan pedidos |
| INSUMOS | # unidades | Cartón/etiquetas escalan con volumen físico |
| ARRIENDOS | # unidades | Proxy de m³ ocupado en bodega |
| HONORARIOS, SEGUROS, GASTOS OFICINA | % venta | Servicios proporcionales al revenue |
| MOVILIZACIÓN, MANTENCIÓN | # pedidos | Cada despacho/uso de equipo |
| SUSCRIPCIÓN/SOFTWARE | equitativo | SaaS independiente del volumen |

#### Drivers de distribución del GAV (por área)

| Área | Driver default | Por qué |
|---|---|---|
| COMERCIAL | % venta | KAMs/comercial escalan con revenue |
| MARKETING | % venta | Inversión proporcional al canal |
| FINANZAS Y ADMIN | % venta | Backoffice escala con volumen $$ |
| GRUPO ETER | equitativo | Holding apoya a todos por igual |
| LEGALES Y NOTARIALES | equitativo | Servicios corporativos |

#### ⚠️ Limitación: GAV ↔ KAM
El GAV se distribuye con drivers genéricos por canal/LN. **No se puede
relacionar un KAM específico con su GAV asignado** — el control de gestión
no tiene esa segmentación. Pendiente futuro: armar tabla manual de "costos
fijos por canal" (gerente, KAM, planner, equipo producto) para tener
asignación directa.

#### Filtros disponibles
- **Año** · **Trimestre / Mes(es)** · **Canal** · **KAM** · **Línea de Negocio**
- Los filtros se aplican simultáneamente a las 4 fuentes
- Vacío = "todos"

#### Desglose flexible
La tabla se desglosa por la dimensión que elijas:
- **Canal de Venta** — rentabilidad por marketplace/canal
- **Línea de Negocio** — comparar Marketplace vs Páginas propias vs Distribución
- **KAM** — performance del equipo comercial
        """)

    # ─── TAB ROADMAP ────────────────────────────────────────────────────
    with tab_roadmap:
        st.markdown("## 🚀 Roadmap del P&L por LN")

        st.markdown("### ✅ Hecho hasta ahora")
        st.success("""
- ✅ Estructura 7 líneas (Venta → MD → Comisiones → MC → Costo OP → GAV → EBIT)
- ✅ Filtros multi-dim: Año · Período · Canal · KAM · LN
- ✅ Desglose flexible: Canal | LN | KAM
- ✅ Drivers configurables por CC
- ✅ GAV "puro" (sin duplicar con Costo OP)
- ✅ Drilldown costo OP con cuenta analítica
- ✅ Cobertura del filtro (% pedidos/unidades/venta)
- ✅ Alarma de calce (suma distribuida = total del período)
- ✅ Fallback parquet KAM (sin depender de credentials Sheet)
""")

        st.markdown("### 🔜 Próximas iteraciones (priorizadas)")

        st.markdown("""
**5. EBIT Mensual + Forecast** ⏳ *próximo*
- Vista evolución mensual del EBIT real por canal/LN/KAM
- Forecast EBIT futuro:
  - Costos variables: inducidos por forecast de venta (unidades/pedidos/venta por producto×canal)
  - Costos fijos: promedio histórico
  - GAV: promedio histórico
- Comparativa Real vs PPTO vs FCST
- Sensitivity: ¿qué pasa si crece la venta 10%?

**6. GAV más específico** ⏳ *próximo*
- Asignación directa de costos fijos por canal:
  - Gerente comercial → asignado a sus canales
  - KAM → su canal específico
  - Planner → línea(s) de negocio
  - Equipo producto → categoría/marca
- Tabla manual de mapping editable en UI
- Persistencia en Turso o JSON local
""")

        st.markdown("### 💡 Ideas adicionales (para discutir)")
        st.info("""
**Análisis comercial**
- 📊 Comparativa PPTO vs Real por canal (cumplimiento %)
- 📈 Gráfico waterfall del P&L (Venta → ... → EBIT con caídas visuales)
- 🏆 Top 5 canales que MÁS aportan EBIT (vs los que más restan)
- 🚨 Lista de canales que NUNCA logran cubrir su Costo OP+GAV

**Performance & alertas**
- 🔔 Alerta automática: canal con EBIT% < umbral (ej: < -10%)
- 📉 Tendencia: canales con EBIT% deteriorándose mes a mes
- 💸 Análisis de break-even por canal: ¿cuánta venta necesita para EBIT=0?

**Operacional**
- 📥 Export del P&L completo a Excel (con formato)
- 📅 Comparación período vs período anterior (Δ% / Δ$)
- 🔗 Link directo desde un canal/LN/KAM al detalle en la app de Ventas
- 📧 Reporte automático mensual al CEO con el P&L consolidado

**Drivers más finos**
- 📦 m³ ocupado por canal (en vez de # pedidos como proxy de bodega)
- ⏱️ Horas-hombre dedicadas por canal (para REMUNERACIONES)
- 💳 % pedidos con pago tarjeta (para comisiones bancarias)

**Modelado**
- 🎯 What-if: ajustar drivers manualmente y ver impacto en EBIT
- 🤖 Sugerir driver óptimo por CC usando regresión vs venta histórica
- 📊 Análisis de cohorts de clientes por canal
""")

        st.markdown("### 🐞 Limitaciones conocidas (técnicas)")
        st.warning("""
- ⚠️ **GAV ↔ KAM**: el control de gestión no segmenta GAV por KAM, así que la
  asignación a KAM individual es proxy (% venta del KAM). Se resuelve con
  el mapping manual de "costos fijos por canal" (item 6 arriba).
- ⚠️ **Arriendo**: hoy se distribuye por # unidades como proxy de m³.
  Lo ideal sería medir m³ reales por canal en bodega.
- ⚠️ **Canales fuera de KAM**: si hay un canal en ventas que no está en KAM,
  su porción de costo se "pierde" al filtrar (ver alarma de calce arriba).
""")

        st.markdown("### 📝 Pendiente del usuario")
        st.markdown("""
- ¿Querés que el cron `sync_finanzas.yml` corra el extractor del KAM también?
  Hoy hay que correr manualmente `python extract_kam_contribucion.py` cada vez
  que cambian datos en el Sheet KAM.
- ¿El driver default de cada CC tiene sentido o querés revisar alguno?
- ¿La lista de "áreas operativas a excluir" (OPERACIONES, LOGISTICA, POSTVENTA)
  es completa o falta alguna?
""")


# ============================================================
# CONSTRUCCIÓN DEL P&L (7 LÍNEAS)
# ============================================================
def _construir_pyl_7lineas(df_contrib: pd.DataFrame,
                            costo_op_por_dim: dict,
                            gav_por_dim: dict,
                            desglose: str) -> pd.DataFrame:
    """Devuelve DataFrame con filas = 7 líneas P&L + MC%/EBIT%, cols = valores + TOTAL."""
    if df_contrib.empty:
        return pd.DataFrame()

    valores = df_contrib[desglose].tolist()
    contrib_dict = df_contrib.set_index(desglose).to_dict("index")

    rows = []
    for label in [
        "Ingreso por Venta",
        "Margen Directo",
        "Comisiones",
        "Margen de Contribución",
        "Costos Operativos",
        "Costos P&L GAV",
        "EBIT",
    ]:
        row = {"Línea P&L": label}
        for v in valores:
            c = contrib_dict.get(v, {})
            venta = c.get("venta", 0)
            md = c.get("margen_dir", 0)
            com = c.get("comisiones", 0)
            mc = c.get("contribucion", 0)
            cop = costo_op_por_dim.get(v, 0)
            gav = gav_por_dim.get(v, 0)
            ebit = mc - cop - gav

            if label == "Ingreso por Venta":
                row[v] = venta
            elif label == "Margen Directo":
                row[v] = md
            elif label == "Comisiones":
                row[v] = -com
            elif label == "Margen de Contribución":
                row[v] = mc
            elif label == "Costos Operativos":
                row[v] = -cop
            elif label == "Costos P&L GAV":
                row[v] = -gav
            elif label == "EBIT":
                row[v] = ebit
        row["TOTAL"] = sum(row[v] for v in valores)
        rows.append(row)

    df = pd.DataFrame(rows)

    # Filas de % al final
    venta_t = sum(contrib_dict.get(v, {}).get("venta", 0) for v in valores)
    mc_t = sum(contrib_dict.get(v, {}).get("contribucion", 0) for v in valores)
    cop_t = sum(costo_op_por_dim.get(v, 0) for v in valores)
    gav_t = sum(gav_por_dim.get(v, 0) for v in valores)
    ebit_t = mc_t - cop_t - gav_t

    row_mcpct = {"Línea P&L": "MC %"}
    row_ebitpct = {"Línea P&L": "EBIT %"}
    for v in valores:
        c = contrib_dict.get(v, {})
        venta = c.get("venta", 0)
        mc = c.get("contribucion", 0)
        cop = costo_op_por_dim.get(v, 0)
        gav = gav_por_dim.get(v, 0)
        ebit = mc - cop - gav
        row_mcpct[v] = (mc / venta * 100) if venta else 0
        row_ebitpct[v] = (ebit / venta * 100) if venta else 0
    row_mcpct["TOTAL"] = (mc_t / venta_t * 100) if venta_t else 0
    row_ebitpct["TOTAL"] = (ebit_t / venta_t * 100) if venta_t else 0

    df = pd.concat([df, pd.DataFrame([row_mcpct, row_ebitpct])], ignore_index=True)
    return df


# ============================================================
# RENDERIZADO HTML DEL P&L
# ============================================================
def _render_pyl_html(df_pyl: pd.DataFrame) -> str:
    """Genera HTML estilo Excel con colores y subtotales destacados."""
    cols_valores = [c for c in df_pyl.columns if c not in ("Línea P&L", "TOTAL")]
    cols_orden = ["Línea P&L"] + cols_valores + ["TOTAL"]

    html = ['<div style="overflow-x:auto;">']
    html.append(
        '<table style="width:100%;border-collapse:collapse;font-size:13px;'
        'font-family:Inter,sans-serif;">'
    )

    # Header
    html.append(f'<thead><tr style="background:{COLOR_HDR};color:white;">')
    for col in cols_orden:
        align = "left" if col == "Línea P&L" else "right"
        html.append(
            f'<th style="padding:10px 12px;text-align:{align};'
            f'border-bottom:2px solid #0F172A;">{col}</th>'
        )
    html.append("</tr></thead>")

    # Body
    html.append("<tbody>")
    for _, row in df_pyl.iterrows():
        label = row["Línea P&L"]
        es_subtotal = label in ("Margen Directo", "Margen de Contribución")
        es_ebit = label == "EBIT"
        es_pct = label in ("MC %", "EBIT %")

        if es_ebit:
            bg = "#0F172A"
            font_weight = "700"
            color = "white"
            border = "border-top:2px solid #0F172A;"
        elif es_subtotal:
            bg = "#F1F5F9"
            font_weight = "700"
            color = COLOR_SUBTOTAL
            border = "border-top:1px solid #94A3B8;"
        elif es_pct:
            bg = "#FEFCE8"
            font_weight = "600"
            color = "#854D0E"
            border = ""
        else:
            bg = "white"
            font_weight = "400"
            color = "#1E293B"
            border = ""

        html.append(
            f'<tr style="background:{bg};color:{color};font-weight:{font_weight};{border}">'
        )
        html.append(f'<td style="padding:8px 12px;text-align:left;">{label}</td>')

        for col in cols_valores + ["TOTAL"]:
            v = row[col]
            if es_pct:
                txt = _fmt_pct(v)
                if v >= 35:
                    val_color = COLOR_POSITIVO
                elif v >= 15:
                    val_color = "#F59E0B"
                else:
                    val_color = COLOR_NEGATIVO
                html.append(
                    f'<td style="padding:8px 12px;text-align:right;'
                    f'color:{val_color};font-weight:600;">{txt}</td>'
                )
            else:
                txt = _fmt_clp(v / 1_000_000)
                if v < 0 and not es_ebit:
                    val_color = COLOR_NEGATIVO
                elif es_ebit and v < 0:
                    val_color = "#FCA5A5"
                else:
                    val_color = color
                html.append(
                    f'<td style="padding:8px 12px;text-align:right;'
                    f'color:{val_color};">{txt}</td>'
                )
        html.append("</tr>")

    html.append("</tbody></table></div>")
    html.append(
        '<p style="font-size:11px;color:#64748B;margin-top:6px;">'
        "Cifras en MM$ (millones de pesos) · (números) = negativos · "
        "MC% / EBIT% sobre venta de la columna"
        "</p>"
    )
    return "".join(html)


def _render_insights(df_pyl: pd.DataFrame, desglose: str):
    """Insights automáticos del P&L."""
    cols_valores = [c for c in df_pyl.columns if c not in ("Línea P&L", "TOTAL")]
    if not cols_valores:
        return

    fila_ebit = df_pyl[df_pyl["Línea P&L"] == "EBIT"]
    fila_ebit_pct = df_pyl[df_pyl["Línea P&L"] == "EBIT %"]
    fila_venta = df_pyl[df_pyl["Línea P&L"] == "Ingreso por Venta"]
    fila_mc = df_pyl[df_pyl["Línea P&L"] == "Margen de Contribución"]
    fila_cop = df_pyl[df_pyl["Línea P&L"] == "Costos Operativos"]
    fila_gav = df_pyl[df_pyl["Línea P&L"] == "Costos P&L GAV"]

    if fila_ebit.empty:
        return

    ebits = {c: fila_ebit.iloc[0][c] for c in cols_valores}
    ebits_pct = {c: fila_ebit_pct.iloc[0][c] for c in cols_valores}
    ventas = {c: fila_venta.iloc[0][c] for c in cols_valores}
    mcs = {c: fila_mc.iloc[0][c] for c in cols_valores}
    cops = {c: -fila_cop.iloc[0][c] for c in cols_valores}
    gavs = {c: -fila_gav.iloc[0][c] for c in cols_valores}

    venta_total = sum(ventas.values())
    relevantes = [c for c in cols_valores if ventas[c] > venta_total * 0.01]
    if not relevantes:
        return

    mejor = max(relevantes, key=lambda c: ebits_pct[c])
    peor = min(relevantes, key=lambda c: ebits_pct[c])
    perdiendo = [c for c in relevantes if (cops[c] + gavs[c]) > mcs[c]]

    st.markdown(f"### 💡 Insights por {_label_dim(desglose)}")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.success(
            f"🏆 **Más rentable:** {mejor}  \n"
            f"EBIT %: `{_fmt_pct(ebits_pct[mejor])}`  \n"
            f"EBIT abs: `${_fmt_clp(ebits[mejor] / 1_000_000)} MM`"
        )
    with c2:
        if ebits_pct[peor] < 0:
            st.error(
                f"⚠️ **Pierde plata:** {peor}  \n"
                f"EBIT %: `{_fmt_pct(ebits_pct[peor])}`  \n"
                f"EBIT abs: `${_fmt_clp(ebits[peor] / 1_000_000)} MM`"
            )
        else:
            st.warning(
                f"📉 **Menos rentable:** {peor}  \n"
                f"EBIT %: `{_fmt_pct(ebits_pct[peor])}`  \n"
                f"EBIT abs: `${_fmt_clp(ebits[peor] / 1_000_000)} MM`"
            )
    with c3:
        if perdiendo:
            st.error(
                f"🚨 **Costos > Contribución** en:  \n"
                + "  \n".join(f"• {c}" for c in perdiendo[:5])
            )
        else:
            st.success("✅ Todos los segmentos relevantes cubren su asignación de costos.")


# ============================================================
# COBERTURA DEL FILTRO (% del subset visible sobre total)
# ============================================================
def _render_cobertura_filtro(
    df_ventas_drivers: pd.DataFrame,
    df_ventas_filtrado: pd.DataFrame,
    costo_op_total_periodo: float,
    costo_op_asignado: float,
    gav_total_periodo: float,
    gav_asignado: float,
    hay_filtro: bool,
):
    """Si hay filtro activo, muestra qué % del universo total cubre el subset
    filtrado (en pedidos, unidades, venta) y cómo eso se traduce en costo
    asignado."""
    if not hay_filtro:
        return  # sin filtro = 100% siempre, no hace falta mostrar

    if df_ventas_drivers.empty or df_ventas_filtrado.empty:
        return

    pct_pedidos = (df_ventas_filtrado["n_pedidos"].sum() /
                    df_ventas_drivers["n_pedidos"].sum() * 100) if df_ventas_drivers["n_pedidos"].sum() else 0
    pct_unidades = (df_ventas_filtrado["n_unidades"].sum() /
                     df_ventas_drivers["n_unidades"].sum() * 100) if df_ventas_drivers["n_unidades"].sum() else 0
    pct_venta = (df_ventas_filtrado["venta_neta"].sum() /
                  df_ventas_drivers["venta_neta"].sum() * 100) if df_ventas_drivers["venta_neta"].sum() else 0

    pct_op = (costo_op_asignado / costo_op_total_periodo * 100) if costo_op_total_periodo else 0
    pct_gav = (gav_asignado / gav_total_periodo * 100) if gav_total_periodo else 0

    st.markdown(
        f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
        f'border-radius:8px;padding:12px 16px;margin:10px 0;font-size:0.85rem;">'
        f'<strong style="color:#475569;">📐 Cobertura del filtro vs universo total del período:</strong>'
        f'<div style="display:flex;gap:24px;margin-top:8px;flex-wrap:wrap;">'
        f'<div>🛒 Pedidos: <strong>{pct_pedidos:.1f}%</strong></div>'
        f'<div>📦 Unidades: <strong>{pct_unidades:.1f}%</strong></div>'
        f'<div>💰 Venta: <strong>{pct_venta:.1f}%</strong></div>'
        f'<div style="border-left:1px solid #CBD5E1;padding-left:24px;">'
        f'⚙️ Costo OP asignado: <strong>{pct_op:.1f}%</strong> '
        f'(${costo_op_asignado/1_000_000:,.1f}/{costo_op_total_periodo/1_000_000:,.1f} MM)'
        f'</div>'
        f'<div>🏢 GAV asignado: <strong>{pct_gav:.1f}%</strong> '
        f'(${gav_asignado/1_000_000:,.1f}/{gav_total_periodo/1_000_000:,.1f} MM)'
        f'</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# ALARMA DE CALCE (¿la suma distribuida = total del período?)
# ============================================================
def _render_alarma_calce(
    df_costos: pd.DataFrame,
    df_gav: pd.DataFrame,
    df_ventas_drivers: pd.DataFrame,
    df_contrib: pd.DataFrame,
    desglose: str,
    driver_override: dict,
):
    """Valida que la SUMA del costo OP + GAV distribuido a TODAS las
    dimensiones (no solo las visibles) cuadre con el total del período.

    Si no calza, indica que hay canales/LNs/KAMs en df_ventas que NO están
    en df_contrib (KAM no los tiene cargados) → su porción de costo
    quedaría 'huérfana' al usar valores_visibles.
    """
    if df_costos.empty or df_ventas_drivers.empty:
        return

    # Distribuir TODO sin filtrar a valores_visibles
    costo_op_distribuido_total = 0.0
    for _, c in df_costos.iterrows():
        cc = c["centro_costo"]
        driver = driver_override.get(cc, driver_default(cc))
        asig = distribuir_monto_a_dimension(
            c["monto"], df_ventas_drivers, driver, dimension=desglose,
        )
        costo_op_distribuido_total += sum(asig.values())

    gav_distribuido_total = 0.0
    for _, g in df_gav.iterrows():
        driver = driver_default_gav(g["area"])
        asig = distribuir_monto_a_dimension(
            g["monto"], df_ventas_drivers, driver, dimension=desglose,
        )
        gav_distribuido_total += sum(asig.values())

    costo_op_total = df_costos["monto"].sum()
    gav_total = df_gav["monto"].sum() if not df_gav.empty else 0

    # Diferencias en MM (tolerancia 0.1 MM = 100 mil CLP)
    dif_op = abs(costo_op_total - costo_op_distribuido_total) / 1_000_000
    dif_gav = abs(gav_total - gav_distribuido_total) / 1_000_000

    # Verificar canales en ventas que NO están en KAM
    valores_kam = set(df_contrib[desglose].tolist()) if not df_contrib.empty else set()
    valores_ventas = set(df_ventas_drivers[desglose].dropna().unique().tolist()) if desglose in df_ventas_drivers.columns else set()
    fuera_de_kam = valores_ventas - valores_kam

    if dif_op < 0.1 and dif_gav < 0.1 and not fuera_de_kam:
        st.markdown(
            f'<div class="pyl-banner pyl-banner-ok">'
            f'✅ <strong>Calce correcto:</strong> el 100% del Costo OP '
            f'(${costo_op_total/1_000_000:,.1f} MM) y del GAV '
            f'(${gav_total/1_000_000:,.1f} MM) está distribuido a los canales/LN/KAMs.'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        msgs = []
        if dif_op >= 0.1:
            msgs.append(
                f"💰 Costo OP: total ${costo_op_total/1_000_000:,.1f} MM "
                f"vs distribuido ${costo_op_distribuido_total/1_000_000:,.1f} MM "
                f"(diferencia ${dif_op:,.1f} MM)"
            )
        if dif_gav >= 0.1:
            msgs.append(
                f"🏢 GAV: total ${gav_total/1_000_000:,.1f} MM "
                f"vs distribuido ${gav_distribuido_total/1_000_000:,.1f} MM "
                f"(diferencia ${dif_gav:,.1f} MM)"
            )
        if fuera_de_kam:
            ejemplos = list(fuera_de_kam)[:5]
            msgs.append(
                f"⚠️ {len(fuera_de_kam)} {_label_dim(desglose).lower()}(s) en "
                f"ventas históricas <strong>NO están en KAM</strong>: "
                f"{', '.join(ejemplos)}{'...' if len(fuera_de_kam) > 5 else ''}. "
                f"Su porción de costo se 'pierde' al filtrar."
            )

        st.markdown(
            f'<div class="pyl-banner pyl-banner-warn">'
            f'⚠️ <strong>ALARMA DE CALCE:</strong><br>'
            + "<br>".join(f"• {m}" for m in msgs) +
            f'</div>',
            unsafe_allow_html=True,
        )


# ============================================================
# TAB PROYECCIÓN FCST (Ene-Dic mix Real + Proyectado)
# ============================================================
def _render_tab_proyeccion_fcst(year: int):
    """Tabla mensual Ene→Dic mezclando real (meses con FCST cerrado en
    P&L) + proyectado (resto del año basado en FCST de venta del Sheet
    Drive + ratios YTD).
    """
    import plotly.graph_objects as go

    st.markdown(f"### 🔮 Proyección anual {year} · Real + FCST")
    st.caption(
        "Vista del año completo. Meses **cerrados** muestran el dato real "
        "(escenario FCST del Sheet P&L Drive). Meses **futuros** se proyectan "
        "usando: (1) FCST de venta del P&L corporativo, (2) MC% promedio YTD, "
        "(3) Costo OP del FCST si está cargado o promedio últimos 3 meses, "
        "(4) GAV proporcional a venta. Cuando un mes se cierra en el Sheet "
        "Drive, pasa automáticamente de Proyectado a Real."
    )

    df_trend = _calcular_tendencia_ebit_anual(year)
    if df_trend.empty:
        st.warning("⏳ Sin datos suficientes para proyectar el año.")
        return

    # ─── Tabla mensual ─────────────────────────────────────────────
    df_show = df_trend.copy()
    df_show["Mes"] = df_show["mes_label"]
    df_show["Tipo"] = df_show["tipo"].apply(
        lambda t: "🟢 Real" if t == "Real" else "🟡 Proy"
    )
    df_show["Venta (MM)"] = df_show["venta_mm"].round(1)
    df_show["MC (MM)"] = df_show["contrib_mm"].round(1)
    df_show["MC %"] = df_show.apply(
        lambda r: round(r["contrib_mm"] / r["venta_mm"] * 100, 1)
                   if r["venta_mm"] else 0, axis=1)
    df_show["Costo OP (MM)"] = df_show["costo_op_mm"].round(1)
    df_show["GAV (MM)"] = df_show["gav_mm"].round(1)
    df_show["EBIT (MM)"] = df_show["ebit_mm"].round(1)
    df_show["EBIT %"] = df_show.apply(
        lambda r: round(r["ebit_mm"] / r["venta_mm"] * 100, 1)
                   if r["venta_mm"] else 0, axis=1)
    df_show = df_show[["Mes", "Tipo",
                        "Venta (MM)", "MC (MM)", "MC %",
                        "Costo OP (MM)", "GAV (MM)",
                        "EBIT (MM)", "EBIT %"]]

    # Fila total anual
    total_row = pd.DataFrame([{
        "Mes": "⬛ AÑO",
        "Tipo": "Real + Proy",
        "Venta (MM)": round(df_trend["venta_mm"].sum(), 1),
        "MC (MM)": round(df_trend["contrib_mm"].sum(), 1),
        "MC %": round(df_trend["contrib_mm"].sum()
                       / df_trend["venta_mm"].sum() * 100, 1)
                  if df_trend["venta_mm"].sum() else 0,
        "Costo OP (MM)": round(df_trend["costo_op_mm"].sum(), 1),
        "GAV (MM)": round(df_trend["gav_mm"].sum(), 1),
        "EBIT (MM)": round(df_trend["ebit_mm"].sum(), 1),
        "EBIT %": round(df_trend["ebit_mm"].sum()
                         / df_trend["venta_mm"].sum() * 100, 1)
                    if df_trend["venta_mm"].sum() else 0,
    }])
    df_show_full = pd.concat([df_show, total_row], ignore_index=True)

    st.dataframe(
        df_show_full,
        use_container_width=True, hide_index=True, height=520,
        column_config={
            "Venta (MM)": st.column_config.NumberColumn(format="$ %.1f"),
            "MC (MM)": st.column_config.NumberColumn(format="$ %.1f"),
            "MC %": st.column_config.NumberColumn(format="%.1f%%"),
            "Costo OP (MM)": st.column_config.NumberColumn(format="$ %.1f"),
            "GAV (MM)": st.column_config.NumberColumn(format="$ %.1f"),
            "EBIT (MM)": st.column_config.NumberColumn(format="$ %.1f"),
            "EBIT %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

    st.markdown("---")

    # ─── Resumen Real vs Proyectado ────────────────────────────────
    real = df_trend[df_trend["tipo"] == "Real"]
    proy = df_trend[df_trend["tipo"] == "Proyectado"]

    col_r, col_p, col_t = st.columns(3)
    with col_r:
        st.markdown("#### 🟢 Real (YTD cerrado)")
        st.metric("Meses", f"{len(real)}")
        st.metric("Venta YTD", f"${_fmt_clp(real['venta_mm'].sum())} MM")
        st.metric("EBIT YTD", f"${_fmt_clp(real['ebit_mm'].sum())} MM",
                    delta=_fmt_pct(real["ebit_mm"].sum()
                                    / real["venta_mm"].sum() * 100
                                    if real["venta_mm"].sum() else 0))
    with col_p:
        st.markdown("#### 🟡 Proyectado (FCST futuro)")
        st.metric("Meses", f"{len(proy)}")
        st.metric("Venta FCST", f"${_fmt_clp(proy['venta_mm'].sum())} MM")
        st.metric("EBIT FCST", f"${_fmt_clp(proy['ebit_mm'].sum())} MM",
                    delta=_fmt_pct(proy["ebit_mm"].sum()
                                    / proy["venta_mm"].sum() * 100
                                    if proy["venta_mm"].sum() else 0))
    with col_t:
        st.markdown("#### ⬛ TOTAL año proyectado")
        st.metric("Venta año", f"${_fmt_clp(df_trend['venta_mm'].sum())} MM")
        st.metric("MC año", f"${_fmt_clp(df_trend['contrib_mm'].sum())} MM")
        st.metric("EBIT año", f"${_fmt_clp(df_trend['ebit_mm'].sum())} MM",
                    delta=_fmt_pct(df_trend["ebit_mm"].sum()
                                    / df_trend["venta_mm"].sum() * 100
                                    if df_trend["venta_mm"].sum() else 0))

    # ─── Gráfico de barras apiladas Venta vs Costos ────────────────
    st.markdown("---")
    st.markdown("### 📊 Composición mensual: Venta · Costos · EBIT")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="MC", x=df_trend["mes_label"], y=df_trend["contrib_mm"],
        marker_color="#16A34A",
        text=[f"${v:.1f}" for v in df_trend["contrib_mm"]],
        textposition="inside", insidetextfont=dict(color="white", size=10),
    ))
    fig.add_trace(go.Bar(
        name="− Costo OP", x=df_trend["mes_label"],
        y=-df_trend["costo_op_mm"],
        marker_color="#DC2626",
        text=[f"$({v:.1f})" for v in df_trend["costo_op_mm"]],
        textposition="inside", insidetextfont=dict(color="white", size=10),
    ))
    fig.add_trace(go.Bar(
        name="− GAV", x=df_trend["mes_label"],
        y=-df_trend["gav_mm"],
        marker_color="#F59E0B",
        text=[f"$({v:.1f})" for v in df_trend["gav_mm"]],
        textposition="inside", insidetextfont=dict(color="white", size=10),
    ))
    fig.add_trace(go.Scatter(
        name="EBIT", x=df_trend["mes_label"], y=df_trend["ebit_mm"],
        mode="lines+markers+text",
        line=dict(color="#1E40AF", width=3),
        marker=dict(size=10, color="#1E40AF",
                      symbol=["circle" if t == "Real" else "diamond"
                                for t in df_trend["tipo"]]),
        text=[f"${v:.1f}" for v in df_trend["ebit_mm"]],
        textposition="top center", textfont=dict(size=10, color="#1E40AF"),
    ))
    fig.update_layout(
        height=440, barmode="relative",
        margin=dict(l=20, r=20, t=30, b=20),
        plot_bgcolor="white",
        xaxis=dict(gridcolor="#F1F5F9"),
        yaxis=dict(gridcolor="#F1F5F9", title="MM CLP"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                      xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "💡 Líneas con diamante en EBIT = mes proyectado. Círculo = mes real. "
        "MC y Costo OP/GAV se superponen apiladas para visualizar cuánto del "
        "MC consume cada bloque de costo."
    )


# ============================================================
# TRANSPARENCIA GAV (banner + áreas incluidas/excluidas)
# ============================================================
def _render_transparencia_gav(df_gav: pd.DataFrame, year: int,
                                 meses: list[int]):
    """Banner + expander con las áreas que entran y se excluyen del GAV.
    Hace visible que el GAV viene del Sheet P&L Drive y qué se descarta
    para no duplicar con el Costo Operativo.
    """
    from views._fin_distribucion import (
        AREAS_OPERATIVAS_EXCLUIR,
        CONTROL_GESTION_PARQUET,
    )

    # Banner permanente
    excluidas_str = " · ".join(sorted(AREAS_OPERATIVAS_EXCLUIR))
    st.markdown(
        f'<div class="pyl-banner">'
        f'🏢 <strong>GAV puro</strong> = áreas del <strong>P&L Drive '
        f'(Control de Gestión)</strong> EXCLUYENDO {{{excluidas_str}}}, '
        f'porque esas áreas ya se computaron en Costo Operativo y se '
        f'duplicarían. Distribución por driver (default = % venta).'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.expander("🔍 Ver detalle: áreas que entran y se excluyen del GAV",
                       expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### ✅ Áreas que SÍ entran al GAV")
            if df_gav.empty:
                st.info("Sin áreas con monto > 0 en el período.")
            else:
                df_in = df_gav.copy()
                df_in["Monto (MM)"] = (df_in["monto"] / 1_000_000).round(1)
                df_in = df_in[["area", "Monto (MM)"]].rename(
                    columns={"area": "Área"})
                st.dataframe(df_in, use_container_width=True,
                              hide_index=True, height=240)
                tot = df_gav["monto"].sum() / 1_000_000
                st.markdown(f"**Total GAV puro:** `${tot:,.1f} MM`")

        with c2:
            st.markdown("#### 🚫 Áreas excluidas (ya en Costo OP)")
            # Cargar las áreas operativas con sus montos para mostrar
            # cuánto se "esconde" para no duplicar
            try:
                if CONTROL_GESTION_PARQUET.exists():
                    df_ops = pd.read_parquet(CONTROL_GESTION_PARQUET)
                    df_ops = df_ops[
                        (df_ops["year"] == year)
                        & (df_ops["month"].isin(meses))
                        & (df_ops["escenario"] == "FCST")
                        & (df_ops["kpi"] == "GASTO")
                    ].copy()

                    def _norm(a):
                        if not a:
                            return ""
                        return (str(a).upper().strip()
                                .replace("Ó", "O").replace("Á", "A")
                                .replace("É", "E").replace("Í", "I")
                                .replace("Ú", "U"))

                    df_ops["area_norm"] = df_ops["area"].apply(_norm)
                    df_ops = df_ops[
                        df_ops["area_norm"].isin(AREAS_OPERATIVAS_EXCLUIR)
                    ].copy()
                    df_ops["valor_pos"] = df_ops["valor"].abs() * 1000
                    df_ops_agg = (df_ops.groupby("area", as_index=False)
                                    .agg(monto=("valor_pos", "sum")))
                    df_ops_agg["Monto (MM)"] = (df_ops_agg["monto"] / 1_000_000).round(1)
                    df_ops_agg = df_ops_agg[["area", "Monto (MM)"]].rename(
                        columns={"area": "Área (excluida)"})
                    st.dataframe(df_ops_agg, use_container_width=True,
                                  hide_index=True, height=240)
                    tot_ops = df_ops_agg["Monto (MM)"].sum()
                    st.markdown(
                        f"**Suma excluida (ya está en Costo OP):** "
                        f"`${tot_ops:,.1f} MM`"
                    )
            except Exception as e:
                st.caption(f"_(No se pudo leer áreas excluidas: {e})_")

        st.markdown("---")
        st.warning(
            "⚠️ **Limitación conocida del GAV:** algunos servicios "
            "corporativos (legales puntuales, asesorías estratégicas, "
            "seguros corporativos no asignados a área) pueden no estar "
            "cargados en el Sheet Drive todavía. El EBIT podría estar "
            "**sobreestimado** por ese gap. En el roadmap: completar el "
            "Sheet Drive con esas cuentas o agregar uploader manual."
        )


# ============================================================
# DRILL-DOWN AL FILTRAR (Costo OP y GAV por canal/LN/KAM filtrado)
# ============================================================
def _render_drilldown_filtrado(
    costo_op_drilldown: list, gav_drilldown: list,
    desglose: str, canales_sel: list, kams_sel: list, lns_sel: list,
    costo_op_asignado: float, gav_asignado: float, contrib_total: float,
):
    """Expander que se abre AUTO cuando hay filtros activos mostrando
    cómo se asignaron Costo OP y GAV a las dimensiones filtradas para
    llegar al EBIT visible.
    """
    hay_filtros = bool(canales_sel or kams_sel or lns_sel)

    filtros_txt_parts = []
    if canales_sel:
        filtros_txt_parts.append(f"📺 {len(canales_sel)} canal(es)")
    if kams_sel:
        filtros_txt_parts.append(f"👤 {len(kams_sel)} KAM(s)")
    if lns_sel:
        filtros_txt_parts.append(f"🏷️ {len(lns_sel)} LN(s)")
    filtros_txt = " + ".join(filtros_txt_parts) or "sin filtros"

    titulo = (f"💡 ¿Cómo se calculó el Costo OP y GAV con tus filtros "
              f"({filtros_txt})?")

    with st.expander(titulo, expanded=hay_filtros):
        if not hay_filtros:
            st.info(
                "ℹ️ Sin filtros activos: el Costo OP y GAV completos del "
                "período se distribuyen a TODOS los canales/LN/KAM. "
                "Aplicá un filtro arriba para ver el detalle de la "
                "asignación específica."
            )
            return

        st.markdown(
            f"**Resultado:** el filtro recibe `${costo_op_asignado / 1_000_000:.1f} MM` "
            f"de Costo OP + `${gav_asignado / 1_000_000:.1f} MM` de GAV. "
            f"Restando ambos al MC (`${contrib_total / 1_000_000:.1f} MM`) "
            f"da el EBIT mostrado arriba."
        )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"#### ⚙️ Costo OP asignado")
            if costo_op_drilldown:
                df_op = pd.DataFrame(costo_op_drilldown)
                df_op["Monto (MM)"] = (df_op["Monto"] / 1_000_000).round(2)
                df_op = df_op[[
                    "Sub-área", "Centro de Costo", "Driver",
                    _label_dim(desglose), "Monto (MM)"
                ]].sort_values("Monto (MM)", ascending=False)
                st.dataframe(df_op, use_container_width=True,
                              hide_index=True, height=320)
                st.caption(
                    f"💡 Cada CC se distribuye al {_label_dim(desglose).lower()} "
                    f"según el driver (pedidos/unidades/venta/equitativo). "
                    f"Sumá la columna Monto y obtenés el total restado."
                )
            else:
                st.info("Sin Costo OP asignado al filtro actual.")

        with c2:
            st.markdown(f"#### 🏢 GAV asignado")
            if gav_drilldown:
                df_g = pd.DataFrame(gav_drilldown)
                df_g["Monto (MM)"] = (df_g["Monto"] / 1_000_000).round(2)
                df_g = df_g[[
                    "Área GAV", "Driver", _label_dim(desglose), "Monto (MM)"
                ]].sort_values("Monto (MM)", ascending=False)
                st.dataframe(df_g, use_container_width=True,
                              hide_index=True, height=320)
                st.caption(
                    f"💡 GAV puro del P&L Drive. Áreas operativas (OPS, LOG, "
                    f"PV) NO entran porque ya están en Costo OP."
                )
            else:
                st.info("Sin GAV asignado al filtro actual.")
