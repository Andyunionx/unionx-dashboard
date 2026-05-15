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
    cargar_gav,
    cargar_ventas_canal_ln,
    distribuir_monto_a_dimension,
    driver_default,
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
# RENDER
# ============================================================
def render():
    with st.sidebar:
        st.markdown("### 📈 **P&L por LN**")
        st.caption("Margen real por canal/KAM/LN")
        st.divider()

    st.title("📈 P&L por Línea de Negocio")
    st.caption(
        "Cruce KAM (oficial) + Costos Operativos + GAV del P&L corporativo. "
        "Filtros multi-dimensión y desglose flexible."
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

    # ─── FILTROS (compactos, agrupados visualmente) ─────────────────────
    st.markdown(
        '<div style="background:#F8FAFC;padding:14px 18px;border-radius:10px;'
        'border:1px solid #E2E8F0;margin-bottom:14px;">'
        '<div style="font-weight:600;color:#475569;font-size:0.85rem;'
        'margin-bottom:10px;">🎛️ FILTROS</div>',
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
    st.markdown(
        f'<div style="background:#EFF6FF;border-left:4px solid #3B82F6;'
        f'padding:8px 14px;border-radius:4px;margin-bottom:14px;'
        f'font-size:0.88rem;color:#1E40AF;">'
        f'<strong>Período activo:</strong> {periodo_label} · '
        f'meses {sorted(set(meses_sel))} · '
        f'desglosado por <strong>{_label_dim(desglose)}</strong>'
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
        df_costos = cargar_costos_operativos(year, meses_sel, escenario="FCST")
        df_ventas = cargar_ventas_canal_ln(
            year, meses_sel,
            canales=canales_f, kams=kams_f, tipos_negocio=lns_f,
        )
        gav_total = cargar_gav(year, meses_sel)

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

    # ─── Resumen consolidado ────────────────────────────────────────────
    res = contribucion_total(
        year=year, meses=meses_sel,
        canales=canales_f, kams=kams_f, tipos_negocio=lns_f,
    )
    venta_total = res.get("venta", 0)
    contrib_total = res.get("contribucion", 0)
    costo_op_total = df_costos["monto"].sum() if not df_costos.empty else 0
    ebit_total = contrib_total - costo_op_total - gav_total
    mc_pct = res.get("mc_pct", 0)
    ebit_pct = (ebit_total / venta_total * 100) if venta_total else 0

    st.markdown("### 📊 Consolidado del período (con filtros)")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Venta REAL", f"${_fmt_clp(venta_total / 1000)} M")
    k2.metric("Contribución", f"${_fmt_clp(contrib_total / 1000)} M",
              delta=_fmt_pct(mc_pct))
    k3.metric("Costo OP", f"${_fmt_clp(costo_op_total / 1000)} M")
    k4.metric("GAV", f"${_fmt_clp(gav_total / 1000)} M")
    k5.metric("EBIT estimado", f"${_fmt_clp(ebit_total / 1000)} M",
              delta=_fmt_pct(ebit_pct))

    st.divider()

    # ─── Tabs ───────────────────────────────────────────────────────────
    tab_pyl, tab_drivers, tab_detalle, tab_help = st.tabs([
        "💰 P&L (7 líneas)",
        "🎚️ Drivers",
        "📋 Detalle",
        "ℹ️ Cómo se calcula",
    ])

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

    # Recuperar override
    driver_override = st.session_state.get("fin_pyl_driver_override", {})

    # ─── CALCULAR DISTRIBUCIONES ────────────────────────────────────────
    costo_op_por_dim = {}
    if not df_costos.empty and not df_ventas.empty:
        for _, c in df_costos.iterrows():
            cc = c["centro_costo"]
            driver = driver_override.get(cc, driver_default(cc))
            asignacion = distribuir_monto_a_dimension(
                c["monto"], df_ventas, driver, dimension=desglose,
            )
            for k, v in asignacion.items():
                costo_op_por_dim[k] = costo_op_por_dim.get(k, 0) + v

    gav_por_dim = distribuir_monto_a_dimension(
        gav_total, df_ventas, "venta", dimension=desglose,
    ) if (gav_total > 0 and not df_ventas.empty) else {}

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

            st.markdown("---")
            _render_insights(df_pyl_table, desglose)

    # ─── TAB DETALLE ────────────────────────────────────────────────────
    with tab_detalle:
        st.markdown("### 📋 Costos a distribuir")
        if df_costos.empty:
            st.info("Sin costos en el período.")
        else:
            df_show = df_costos.copy()
            df_show["driver"] = df_show["centro_costo"].apply(
                lambda cc: driver_override.get(cc, driver_default(cc))
            )
            df_show["monto_M"] = (df_show["monto"] / 1000).round(0)
            df_show = df_show[[
                "sub_area", "centro_costo", "tipo_costo", "monto_M", "driver"
            ]].rename(columns={
                "sub_area": "Sub-área",
                "centro_costo": "Centro de Costo",
                "tipo_costo": "F/V",
                "monto_M": "Monto (M$)",
                "driver": "Driver",
            })
            st.dataframe(df_show, use_container_width=True, hide_index=True)

            tot_fijo = df_costos[df_costos["tipo_costo"] == "FIJO"]["monto"].sum()
            tot_var = df_costos[df_costos["tipo_costo"] == "VARIABLE"]["monto"].sum()
            st.markdown(
                f"**Totales:** Fijo `${_fmt_clp(tot_fijo / 1000)} M` · "
                f"Variable `${_fmt_clp(tot_var / 1000)} M` · "
                f"Total `${_fmt_clp((tot_fijo + tot_var) / 1000)} M`"
            )
            st.markdown(f"**+ GAV (P&L corporativo):** `${_fmt_clp(gav_total / 1000)} M`")

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
| 6 | **Costos P&L GAV** | P&L corporativo | `Gastos Administración y Venta` distribuido por `% venta` |
| 7 | **EBIT** | Calculado | `Margen de Contribución − Costos OP − GAV` |

#### Filtros disponibles
- **Año** · **Trimestre / Mes(es)** · **Canal** · **KAM** · **Línea de Negocio**
- Los filtros se aplican simultáneamente a las 4 fuentes
- Vacío = "todos"

#### Desglose flexible
La tabla se desglosa por la dimensión que elijas:
- **Canal de Venta** — rentabilidad por marketplace/canal
- **Línea de Negocio** — comparar Marketplace vs Páginas propias vs Distribución
- **KAM** — performance del equipo comercial

#### Drivers de distribución del Costo OP

| Tipo de Costo | Driver default | Por qué |
|---|---|---|
| REMUNERACIONES | # pedidos | Operadores procesan pedidos |
| INSUMOS | # unidades | Cartón/etiquetas escalan con volumen físico |
| ARRIENDOS | # pedidos | Proxy de uso de bodega |
| HONORARIOS, SEGUROS, GASTOS OFICINA | % venta | Servicios proporcionales al revenue |
| MOVILIZACIÓN, MANTENCIÓN | # pedidos | Cada despacho/uso de equipo |
| SUSCRIPCIÓN/SOFTWARE | equitativo | SaaS independiente del volumen |

#### Driver de GAV
**Fijo en `% venta`** — los gastos administrativos del corporativo se asocian
naturalmente al revenue generado por cada canal/LN/KAM.
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
                txt = _fmt_clp(v / 1000)
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
        "Cifras en M$ · (números) = negativos · MC% / EBIT% sobre venta de la columna"
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
            f"EBIT abs: `${_fmt_clp(ebits[mejor] / 1000)} M`"
        )
    with c2:
        if ebits_pct[peor] < 0:
            st.error(
                f"⚠️ **Pierde plata:** {peor}  \n"
                f"EBIT %: `{_fmt_pct(ebits_pct[peor])}`  \n"
                f"EBIT abs: `${_fmt_clp(ebits[peor] / 1000)} M`"
            )
        else:
            st.warning(
                f"📉 **Menos rentable:** {peor}  \n"
                f"EBIT %: `{_fmt_pct(ebits_pct[peor])}`  \n"
                f"EBIT abs: `${_fmt_clp(ebits[peor] / 1000)} M`"
            )
    with c3:
        if perdiendo:
            st.error(
                f"🚨 **Costos > Contribución** en:  \n"
                + "  \n".join(f"• {c}" for c in perdiendo[:5])
            )
        else:
            st.success("✅ Todos los segmentos relevantes cubren su asignación de costos.")
