"""
Vista P&L por Línea de Negocio — App Finanzas.

Construye P&L COMPLETO por canal (y por línea de negocio en cascada) cruzando
3 fuentes:

  1. Sheet KAM "Análisis de Resultados" (oficial)
     → Venta REAL · Costo Venta · Margen Directo · Comisiones · Contribución

  2. Sheet OPERACIONES (extraído a costo_operativo.parquet)
     → Costo operativo por CC × sub_area (asociado a Grupo Eter como holding)

  3. Parquet ventas_historico
     → # pedidos · # unidades · venta neta por canal y tipo_negocio (LN)

La distribución del costo operativo a cada canal usa drivers configurables
por tipo de costo. Defaults inteligentes (REMUNERACIONES → pedidos, INSUMOS →
unidades, ARRIENDOS → pedidos, SEGUROS → venta, etc.) con override manual
en la UI.
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from views._ops_contrib_helper import contribucion_por_canal, contribucion_periodo
from views._fin_distribucion import (
    DRIVER_DEFAULT_POR_CC,
    armar_pyl_por_canal,
    cargar_costos_operativos,
    cargar_ventas_canal_ln,
    distribuir_costo_a_canales,
    driver_default,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Paleta P&L (mismo estilo que ops_costo_operativo)
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


# ============================================================
# RENDER
# ============================================================
def render():
    with st.sidebar:
        st.markdown("### 📈 **P&L por LN**")
        st.caption("Margen real por canal y línea de negocio")
        st.divider()

    st.title("📈 P&L por Línea de Negocio")
    st.caption(
        "Margen real por CANAL y por LÍNEA DE NEGOCIO, cruzando contribución "
        "oficial KAM con distribución del costo operativo del holding"
    )

    # ─── Selectores de período ──────────────────────────────────────────
    year_actual = datetime.now().year
    col1, col2, col3 = st.columns([1, 2, 2])
    with col1:
        year = st.selectbox("Año", [year_actual, year_actual - 1], index=0)
    with col2:
        periodo = st.radio(
            "Período",
            ["YTD", "Q1 (E-M)", "Q2 (A-J)", "Q3 (J-S)", "Q4 (O-D)", "Mes específico"],
            horizontal=True, index=0,
        )

    if periodo == "YTD":
        meses_sel = list(range(1, datetime.now().month + 1)) if year == year_actual else list(range(1, 13))
        periodo_label = f"YTD {year}"
    elif periodo.startswith("Q1"):
        meses_sel = [1, 2, 3]
        periodo_label = f"Q1 {year}"
    elif periodo.startswith("Q2"):
        meses_sel = [4, 5, 6]
        periodo_label = f"Q2 {year}"
    elif periodo.startswith("Q3"):
        meses_sel = [7, 8, 9]
        periodo_label = f"Q3 {year}"
    elif periodo.startswith("Q4"):
        meses_sel = [10, 11, 12]
        periodo_label = f"Q4 {year}"
    else:
        with col3:
            mes = st.number_input("Mes", min_value=1, max_value=12,
                                   value=datetime.now().month, step=1)
        meses_sel = [mes]
        periodo_label = f"{mes:02d}/{year}"

    st.markdown(f"**Período seleccionado:** `{periodo_label}` · meses {meses_sel}")
    st.divider()

    # ─── Cargar inputs ──────────────────────────────────────────────────
    with st.spinner("📥 Cargando datos (KAM + Costos OP + Ventas)..."):
        df_contrib = contribucion_por_canal(year, meses_sel)
        df_costos = cargar_costos_operativos(year, meses_sel, escenario="FCST")
        df_ventas = cargar_ventas_canal_ln(year, meses_sel)

    # Validaciones
    if df_contrib.empty:
        st.error(
            "❌ Sin datos de contribución KAM para el período. "
            "Verifica acceso al Sheet `Análisis de Resultados` o cambia de período."
        )
        return
    if df_costos.empty:
        st.warning(
            "⚠️ Sin costos operativos FCST para el período. "
            "El P&L mostrará solo Contribución (sin asignación de costo OP)."
        )
    if df_ventas.empty:
        st.warning(
            "⚠️ Sin ventas históricas para el período. "
            "No se puede distribuir costo operativo (faltan drivers)."
        )

    # ─── Resumen consolidado ────────────────────────────────────────────
    res = contribucion_periodo(year, meses_sel)
    venta_total = res.get("venta_real_clp", 0)
    contrib_total = res.get("contribucion_clp", 0)
    costo_op_total = df_costos["monto"].sum() if not df_costos.empty else 0
    ebit_total = contrib_total - costo_op_total
    mc_pct = res.get("mc_pct", 0)
    ebit_pct = (ebit_total / venta_total * 100) if venta_total else 0

    st.markdown("### 📊 Consolidado del período")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Venta REAL", f"${_fmt_clp(venta_total / 1000)} M")
    k2.metric("Contribución", f"${_fmt_clp(contrib_total / 1000)} M",
              delta=_fmt_pct(mc_pct))
    k3.metric("Costo OP asignar", f"${_fmt_clp(costo_op_total / 1000)} M")
    k4.metric("EBIT estimado", f"${_fmt_clp(ebit_total / 1000)} M",
              delta=_fmt_pct(ebit_pct))
    k5.metric("Canales activos", f"{len(df_contrib)}")

    st.divider()

    # ─── Tabs ───────────────────────────────────────────────────────────
    tab_pyl, tab_drivers, tab_ln, tab_detalle, tab_help = st.tabs([
        "💰 P&L por Canal",
        "🎚️ Drivers de distribución",
        "🏷️ Por Línea de Negocio",
        "📋 Detalle de costos",
        "ℹ️ Cómo se calcula",
    ])

    # ─────────────────────────────────────────────────────────────────────
    # TAB DRIVERS (primero, porque condiciona el P&L)
    # ─────────────────────────────────────────────────────────────────────
    with tab_drivers:
        st.markdown(
            "### 🎚️ Configuración de drivers por Centro de Costo\n"
            "Cada CC se distribuye a los canales según un driver. "
            "Edita la tabla abajo para sobrescribir el driver default."
        )
        st.info(
            "**Drivers disponibles:**\n"
            "- 🟢 `pedidos` — proporcional a # pedidos del canal "
            "(operadores procesan pedidos)\n"
            "- 🟡 `unidades` — proporcional a # unidades despachadas "
            "(insumos físicos: cartón, etiquetas)\n"
            "- 🔵 `venta` — proporcional a venta neta del canal "
            "(servicios proporcionales al revenue: seguros, asesoría)\n"
            "- ⚪ `equitativo` — reparto igual entre canales activos "
            "(SaaS, suscripciones)"
        )

        if df_costos.empty:
            st.warning("Sin costos para configurar.")
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
                use_container_width=True,
                hide_index=True,
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

            # Reconstruir override
            driver_override = {}
            for _, r in edited.iterrows():
                cc = r["Centro de Costo"]
                if r["Driver"] != driver_default(cc):
                    driver_override[cc] = r["Driver"]

            # Guardar en session_state para que tab P&L lo use
            st.session_state["fin_pyl_driver_override"] = driver_override

            if driver_override:
                st.success(
                    f"✏️ {len(driver_override)} CC con driver personalizado: "
                    f"{', '.join(list(driver_override.keys())[:5])}"
                    f"{'...' if len(driver_override) > 5 else ''}"
                )
            else:
                st.caption("✓ Usando todos los drivers default.")

        # Tabla resumen de defaults
        st.markdown("---")
        st.markdown("**Mapping default por tipo de costo:**")
        df_defaults = pd.DataFrame([
            {"Centro de Costo": k, "Driver default": v}
            for k, v in DRIVER_DEFAULT_POR_CC.items()
            if "Ó" not in k and "Á" not in k and "Í" not in k  # evitar duplicados acentos
        ])
        st.dataframe(df_defaults, use_container_width=True, hide_index=True)

    # Recuperar override de session_state
    driver_override = st.session_state.get("fin_pyl_driver_override", {})

    # Distribuir
    df_distrib = pd.DataFrame()
    if not df_costos.empty and not df_ventas.empty:
        df_distrib = distribuir_costo_a_canales(df_costos, df_ventas, driver_override)

    # ─────────────────────────────────────────────────────────────────────
    # TAB P&L POR CANAL
    # ─────────────────────────────────────────────────────────────────────
    with tab_pyl:
        st.markdown("### 💰 P&L por Canal de Venta")
        st.caption(
            f"Período `{periodo_label}` · Contribución oficial KAM + "
            f"costo operativo distribuido"
        )

        df_pyl = armar_pyl_por_canal(df_contrib, df_distrib)
        if df_pyl.empty:
            st.warning("Sin datos para construir el P&L.")
        else:
            # Renderizar HTML
            html = _render_pyl_html(df_pyl)
            st.markdown(html, unsafe_allow_html=True)

            # Insights
            st.markdown("---")
            _render_insights_canal(df_pyl)

    # ─────────────────────────────────────────────────────────────────────
    # TAB POR LÍNEA DE NEGOCIO
    # ─────────────────────────────────────────────────────────────────────
    with tab_ln:
        st.markdown("### 🏷️ Resumen por Línea de Negocio")
        st.caption(
            "Las líneas de negocio se identifican por `tipo_negocio` en ventas: "
            "Marketplace · Páginas propias · Fidelización · Distribución · Corporativo"
        )

        if df_ventas.empty:
            st.warning("Sin datos de ventas para clasificar por LN.")
        else:
            # Sumar pedidos/unidades/venta por LN
            ln_summary = df_ventas.groupby("tipo_negocio", as_index=False).agg(
                n_pedidos=("n_pedidos", "sum"),
                n_unidades=("n_unidades", "sum"),
                venta_neta=("venta_neta", "sum"),
            ).sort_values("venta_neta", ascending=False)

            # Asignar costo OP por LN proporcional a ventas (default driver venta)
            costo_op_total_distrib = (
                df_distrib["monto"].sum() if not df_distrib.empty else 0
            )
            total_venta_ln = ln_summary["venta_neta"].sum()
            ln_summary["costo_op_asignado"] = (
                ln_summary["venta_neta"] / total_venta_ln * costo_op_total_distrib
                if total_venta_ln > 0 else 0
            )

            # MC% promedio aplicado proporcional al consolidado
            ln_summary["contribucion_est"] = ln_summary["venta_neta"] * (mc_pct / 100)
            ln_summary["ebit_est"] = (
                ln_summary["contribucion_est"] - ln_summary["costo_op_asignado"]
            )
            ln_summary["mc_pct"] = mc_pct
            ln_summary["ebit_pct"] = (
                ln_summary["ebit_est"] / ln_summary["venta_neta"] * 100
            ).where(ln_summary["venta_neta"] > 0, 0)

            # Formato display
            df_disp = ln_summary[[
                "tipo_negocio", "venta_neta", "n_pedidos", "n_unidades",
                "contribucion_est", "costo_op_asignado", "ebit_est",
                "mc_pct", "ebit_pct",
            ]].rename(columns={
                "tipo_negocio": "Línea de Negocio",
                "venta_neta": "Venta",
                "n_pedidos": "# Pedidos",
                "n_unidades": "# Unidades",
                "contribucion_est": "Contribución (est)",
                "costo_op_asignado": "Costo OP",
                "ebit_est": "EBIT (est)",
                "mc_pct": "MC %",
                "ebit_pct": "EBIT %",
            })

            st.dataframe(
                df_disp.style.format({
                    "Venta": "${:,.0f}",
                    "# Pedidos": "{:,.0f}",
                    "# Unidades": "{:,.0f}",
                    "Contribución (est)": "${:,.0f}",
                    "Costo OP": "${:,.0f}",
                    "EBIT (est)": "${:,.0f}",
                    "MC %": "{:.1f}%",
                    "EBIT %": "{:.1f}%",
                }).background_gradient(subset=["EBIT %"], cmap="RdYlGn", vmin=-20, vmax=30),
                use_container_width=True,
                hide_index=True,
            )

            st.info(
                "ℹ️ **Limitación actual:** la contribución por LN se estima "
                "aplicando el MC% consolidado a la venta de cada LN. Para tener "
                "MC real por LN necesitaríamos que el Sheet KAM segmente también "
                "por línea de negocio, no solo por canal. **Roadmap H2:** "
                "agregar columna `tipo_negocio` en el Sheet KAM."
            )

    # ─────────────────────────────────────────────────────────────────────
    # TAB DETALLE
    # ─────────────────────────────────────────────────────────────────────
    with tab_detalle:
        st.markdown("### 📋 Detalle de costos a distribuir")

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

        if not df_distrib.empty:
            st.markdown("---")
            st.markdown("### 🎯 Distribución resultante por canal")
            pivot = df_distrib.pivot_table(
                index="centro_costo",
                columns="canal",
                values="monto",
                aggfunc="sum",
                fill_value=0,
            )
            pivot["TOTAL"] = pivot.sum(axis=1)
            pivot = (pivot / 1000).round(0)
            st.dataframe(
                pivot.style.format("{:,.0f}").background_gradient(cmap="Blues"),
                use_container_width=True,
            )

    # ─────────────────────────────────────────────────────────────────────
    # TAB AYUDA
    # ─────────────────────────────────────────────────────────────────────
    with tab_help:
        st.markdown("""
### 🧭 Cómo se construye este P&L

#### Paso 1 — Contribución por canal (KAM)
Lectura del Sheet **"Análisis de Resultados"** del KAM. Para cada canal:
```
Contribución = Margen Directo KAM − Total Comisiones KAM
             = (Venta − Costo Venta) − (Com. Venta + Com. Envío + Marketing)
```
Esta es la **fuente oficial** del margen por canal.

#### Paso 2 — Costo Operativo del holding
Lectura del Sheet **OPERACIONES** (vía `costo_operativo.parquet`). Como el
costo operativo está cargado a **Grupo Eter** (holding), no a un canal
específico, hay que distribuirlo.

#### Paso 3 — Distribución a canales (drivers)
Cada **Centro de Costo** se distribuye proporcionalmente a un **driver**
del canal. La elección del driver depende de la naturaleza del costo:

| Tipo de Costo | Driver default | Lógica |
|---|---|---|
| REMUNERACIONES | # pedidos | Operadores procesan pedidos |
| INSUMOS (cartón, etiquetas) | # unidades | Escala con volumen físico |
| ARRIENDOS | # pedidos | Proxy de uso de bodega |
| HONORARIOS | % venta | Asesoría/servicios escalan con revenue |
| SEGUROS | % venta | Cobertura proporcional al stock movido |
| MOVILIZACIÓN | # pedidos | Cada despacho genera transporte |
| MANTENCIÓN | # pedidos | Uso de equipos |
| GASTOS OFICINA | % venta | Servicios generales |
| SUSCRIPCIÓN/SW | equitativo | SaaS independiente del volumen |

**Override manual:** en la tab "🎚️ Drivers" puedes cambiar el driver de
cada CC individualmente. La asignación se recalcula al instante.

#### Paso 4 — P&L final
```
Venta REAL              ← KAM
(-) Costo Venta         ← KAM
= Margen Directo
(-) Comisiones          ← KAM (venta + envío + marketing)
= Contribución          ← KAM oficial
(-) Costo OP asignado   ← Distribuido por drivers
= EBIT por canal
```

#### Limitaciones conocidas
- **MC por LN estimado:** se aplica el MC% consolidado a cada LN (el
  Sheet KAM no segmenta por línea de negocio todavía). Roadmap H2: pedir
  a KAM agregar columna `tipo_negocio`.
- **Arriendo bodega:** ideal sería m³ ocupado, hoy usamos # pedidos.
- **Costo OP de Grupo Eter holding:** se distribuye proporcionalmente
  asumiendo que apoya a todos los canales (no hay servicios exclusivos).
        """)


# ============================================================
# RENDERIZADO HTML DEL P&L
# ============================================================
def _render_pyl_html(df_pyl: pd.DataFrame) -> str:
    """Genera HTML estilo Excel con colores y subtotales destacados."""
    canales = [c for c in df_pyl.columns if c not in ("Línea P&L", "TOTAL")]
    cols_orden = ["Línea P&L"] + canales + ["TOTAL"]

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
        es_subtotal = label in ("Margen Directo", "Contribución", "EBIT")
        es_pct = label in ("MC %", "EBIT %")
        es_costo_op = label == "Costo Op asignado"

        if es_subtotal:
            bg = "#F1F5F9"
            font_weight = "700"
            color = COLOR_SUBTOTAL
            border = "border-top:1px solid #94A3B8;"
        elif label == "EBIT" or label == "EBIT %":
            bg = "#0F172A"
            font_weight = "700"
            color = "white"
            border = "border-top:2px solid #0F172A;"
        else:
            bg = "white"
            font_weight = "400"
            color = "#1E293B"
            border = ""

        html.append(
            f'<tr style="background:{bg};color:{color};font-weight:{font_weight};{border}">'
        )
        # Label
        html.append(
            f'<td style="padding:8px 12px;text-align:left;">{label}</td>'
        )
        # Valores
        for col in canales + ["TOTAL"]:
            v = row[col]
            if es_pct:
                txt = _fmt_pct(v)
                # Color según signo
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
                txt = _fmt_clp(v / 1000)  # mostrar en M
                # Color: rojo para negativos, verde para positivos
                if v < 0:
                    val_color = COLOR_NEGATIVO if not (label in ("EBIT",)) else color
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
        "Cifras en M$ · (números) = negativos · MC% / EBIT% sobre venta del canal"
        "</p>"
    )
    return "".join(html)


def _render_insights_canal(df_pyl: pd.DataFrame):
    """Insights automáticos del P&L."""
    canales = [c for c in df_pyl.columns if c not in ("Línea P&L", "TOTAL")]
    if not canales:
        return

    # Extraer EBIT y EBIT% por canal
    fila_ebit = df_pyl[df_pyl["Línea P&L"] == "EBIT"]
    fila_ebit_pct = df_pyl[df_pyl["Línea P&L"] == "EBIT %"]
    fila_venta = df_pyl[df_pyl["Línea P&L"] == "Venta REAL"]
    fila_contrib = df_pyl[df_pyl["Línea P&L"] == "Contribución"]
    fila_cop = df_pyl[df_pyl["Línea P&L"] == "Costo Op asignado"]

    if fila_ebit.empty:
        return

    ebits = {c: fila_ebit.iloc[0][c] for c in canales}
    ebits_pct = {c: fila_ebit_pct.iloc[0][c] for c in canales}
    ventas = {c: fila_venta.iloc[0][c] for c in canales}
    contribs = {c: fila_contrib.iloc[0][c] for c in canales}
    cops = {c: -fila_cop.iloc[0][c] for c in canales}  # convertir a positivo

    # Filtrar canales con venta significativa (>1% del total)
    venta_total = sum(ventas.values())
    canales_relevantes = [c for c in canales if ventas[c] > venta_total * 0.01]

    if not canales_relevantes:
        return

    mejor = max(canales_relevantes, key=lambda c: ebits_pct[c])
    peor = min(canales_relevantes, key=lambda c: ebits_pct[c])
    canales_perdiendo = [c for c in canales_relevantes if cops[c] > contribs[c]]

    st.markdown("### 💡 Insights")
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
        if canales_perdiendo:
            st.error(
                f"🚨 **Costo OP > Contribución** en:  \n"
                + "  \n".join(f"• {c}" for c in canales_perdiendo[:5])
            )
        else:
            st.success(
                "✅ **Todos los canales relevantes** cubren su costo operativo asignado."
            )
