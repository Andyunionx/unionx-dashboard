"""
Vista Costo Operativo — App Operaciones (formato P&L estilo gerencial).

3 sub-tabs:
  1. 📊 P&L Operaciones (cierre Q/mes)
  2. 🔎 Detalle por Centro de Costo
  3. 📋 Informe de Gestión (insights automáticos)

Datos:
  - Costos: Sheet OPERACIONES 2025-2026 (Ppto + FCST=Real según Andrés)
  - Ventas + Margen: módulo Ventas (data/historico/ventas_historico.parquet)

Modelo "Fcst = Real": el FCST del Sheet representa lo efectivamente gastado/
proyectado. La comparación Ppto vs Real es la métrica primaria.

Sin desglose por canal en primera instancia (foco: cerrar costo operativo
total empresa antes de distribuir por LN).
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

MESES_ES = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}
MESES_FULL = {1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO", 6: "JUNIO",
              7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE",
              11: "NOVIEMBRE", 12: "DICIEMBRE"}

# Sub-áreas del P&L (orden del Excel de Andrés)
SUB_AREAS_PNL = ["LOGISTICA", "OPERACIONES", "POSTVENTA", "GRUPO ETER", "UNIONX"]


# ============================================================
# DATA LOADING
# ============================================================
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


@st.cache_data(ttl=600)
def _cargar_ventas_mensual() -> pd.DataFrame:
    """Lee parquet histórico Ventas y agrega por mes (M CLP)."""
    if not VENTAS_HIST.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(VENTAS_HIST)
        df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce")
        df = df.dropna(subset=["fecha_venta"])
        df["year"] = df["fecha_venta"].dt.year
        df["month"] = df["fecha_venta"].dt.month
        agg = df.groupby(["year", "month"], as_index=False).agg(
            venta_bruta=("venta_bruta", "sum"),
            venta_neta=("venta_neta", "sum"),
            margen_front=("margen_front", "sum"),
            margen_final=("margen_final", "sum"),
            n_pedidos=("pedido", "nunique"),
        )
        # CLP raw → M CLP (mismo orden que Sheet)
        for c in ["venta_bruta", "venta_neta", "margen_front", "margen_final"]:
            agg[c + "_m"] = agg[c] / 1000
        return agg
    except Exception:
        return pd.DataFrame()


# ============================================================
# HELPERS DE FORMATO
# ============================================================
def _fmt_clp_m(v, signo: bool = False):
    """Formato '$1,234' o '($1,234)' (negativo entre paréntesis estilo contable)."""
    if v is None or pd.isna(v) or v == 0:
        return "—"
    abs_v = abs(v)
    sign = "" if v >= 0 else "−" if not signo else ""
    if v < 0 and signo:
        return f"({abs_v:,.0f})"
    return f"{sign}{abs_v:,.0f}"


def _fmt_pct(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%"


def _color_var(v: float, es_costo: bool = True) -> str:
    """Color para variación. Costos: var positiva (más gasto) es mala."""
    if v is None or pd.isna(v):
        return "#94A3B8"
    if es_costo:
        return "#16A34A" if v <= 5 else "#EA580C" if v <= 15 else "#DC2626"
    return "#16A34A" if v >= -5 else "#EA580C" if v >= -15 else "#DC2626"


# ============================================================
# AGGREGATORS
# ============================================================
def _gasto_por_sub_area(df: pd.DataFrame, year: int, meses: list[int],
                         escenario: str) -> dict[str, float]:
    """Devuelve {sub_area: monto} del FCST/PPTO GASTO del año/meses."""
    f = df[
        (df["year"] == year)
        & (df["month"].isin(meses))
        & (df["escenario"] == escenario)
        & (df["kpi"] == "GASTO")
    ]
    return f.groupby("sub_area")["valor"].sum().to_dict()


def _venta_periodo(df_v: pd.DataFrame, year: int, meses: list[int]) -> float:
    if df_v.empty:
        return 0
    f = df_v[(df_v["year"] == year) & (df_v["month"].isin(meses))]
    return f["venta_bruta_m"].sum()


# ============================================================
# TAB 1: P&L OPERACIONES
# ============================================================
def _tab_pnl(df_costo: pd.DataFrame, df_venta: pd.DataFrame, year: int, meses: list[int]):
    st.markdown(f"#### 📊 P&L Operaciones — {year}")
    st.caption(
        "Fuente: Costos = Sheet OPERACIONES (Ppto + Fcst) · "
        "Venta = módulo Ventas. **Fcst = Real** según convención Andrés."
    )

    if not meses:
        st.info("Selecciona al menos un mes")
        return

    # Construir filas: Ingresos | Gastos por sub-área | Total | Margen
    rows = []
    venta_ppto_total_acum = 0  # No tenemos Ppto Venta para Ops, usamos Real
    venta_real_total_acum = 0
    total_ppto_gastos_acum = 0
    total_real_gastos_acum = 0

    # Cabecera de columnas: por mes + acumulado
    columnas = []
    for m in meses:
        columnas.append(("mes", m))
    columnas.append(("acum", None))

    # ───── INGRESOS POR VENTA ─────
    for col_tipo, mes in columnas:
        if col_tipo == "mes":
            v_real = _venta_periodo(df_venta, year, [mes])
        else:
            v_real = _venta_periodo(df_venta, year, meses)
        # Ppto venta = Real (módulo Ventas no tiene ppto de venta operacional)
        if col_tipo == "mes":
            pass

    def _cell(ppto, real, es_costo=True, venta_real=None):
        var_pct = ((real - ppto) / abs(ppto) * 100) if ppto else None
        s_vta = (real / venta_real * 100) if (venta_real and venta_real != 0) else None
        return ppto, real, var_pct, s_vta

    # Construir DataFrame de display
    headers = ["Concepto"]
    for m in meses:
        headers += [f"Ppto {MESES_ES[m]}", f"Real {MESES_ES[m]}",
                    f"% Var {MESES_ES[m]}", f"% s/Vta {MESES_ES[m]}"]
    headers += ["PPTO Acum", "REAL Acum", "% Var Acum", "% s/Vta Acum"]

    data_rows = []

    # Venta
    venta_row = ["INGRESOS POR VENTA"] + [""] * (len(headers) - 1)
    data_rows.append(venta_row)
    venta_ppto_real_row = ["Venta Real"]
    venta_acum = _venta_periodo(df_venta, year, meses)
    for m in meses:
        v = _venta_periodo(df_venta, year, [m])
        venta_ppto_real_row += [_fmt_clp_m(v), _fmt_clp_m(v), "—", "—"]
    venta_ppto_real_row += [_fmt_clp_m(venta_acum), _fmt_clp_m(venta_acum), "—", "—"]
    data_rows.append(venta_ppto_real_row)

    data_rows.append([""] * len(headers))

    # GASTOS por sub-área
    data_rows.append(["GASTOS OPERACIONES"] + [""] * (len(headers) - 1))

    sub_area_data = {sa: {"ppto_meses": [], "real_meses": [],
                            "ppto_acum": 0, "real_acum": 0} for sa in SUB_AREAS_PNL}
    for sa in SUB_AREAS_PNL:
        for m in meses:
            ppto = _gasto_por_sub_area(df_costo, year, [m], "PPTO").get(sa, 0)
            real = _gasto_por_sub_area(df_costo, year, [m], "FCST").get(sa, 0)
            sub_area_data[sa]["ppto_meses"].append(ppto)
            sub_area_data[sa]["real_meses"].append(real)
        sub_area_data[sa]["ppto_acum"] = _gasto_por_sub_area(
            df_costo, year, meses, "PPTO").get(sa, 0)
        sub_area_data[sa]["real_acum"] = _gasto_por_sub_area(
            df_costo, year, meses, "FCST").get(sa, 0)

    for sa in SUB_AREAS_PNL:
        sa_label = sa.title() if sa != "UNIONX" else "UnionX"
        sa_label = sa_label if sa != "GRUPO ETER" else "Grupo Eter"
        row = [sa_label]
        for i, m in enumerate(meses):
            ppto = sub_area_data[sa]["ppto_meses"][i]
            real = sub_area_data[sa]["real_meses"][i]
            v_mes = _venta_periodo(df_venta, year, [m])
            var = ((abs(real) - abs(ppto)) / abs(ppto) * 100) if ppto else None
            s_v = (abs(real) / v_mes * 100) if v_mes else None
            row += [_fmt_clp_m(ppto), _fmt_clp_m(real),
                    _fmt_pct(var), f"{s_v:.1f}%" if s_v else "—"]
        # Acum
        ppto_a = sub_area_data[sa]["ppto_acum"]
        real_a = sub_area_data[sa]["real_acum"]
        var_a = ((abs(real_a) - abs(ppto_a)) / abs(ppto_a) * 100) if ppto_a else None
        s_v_a = (abs(real_a) / venta_acum * 100) if venta_acum else None
        row += [_fmt_clp_m(ppto_a), _fmt_clp_m(real_a),
                _fmt_pct(var_a), f"{s_v_a:.1f}%" if s_v_a else "—"]
        data_rows.append(row)

    # TOTAL GASTOS OPS
    total_row = ["TOTAL GASTOS OPS"]
    total_ppto_a = sum(sub_area_data[sa]["ppto_acum"] for sa in SUB_AREAS_PNL)
    total_real_a = sum(sub_area_data[sa]["real_acum"] for sa in SUB_AREAS_PNL)
    for i, m in enumerate(meses):
        t_p = sum(sub_area_data[sa]["ppto_meses"][i] for sa in SUB_AREAS_PNL)
        t_r = sum(sub_area_data[sa]["real_meses"][i] for sa in SUB_AREAS_PNL)
        v_mes = _venta_periodo(df_venta, year, [m])
        var = ((abs(t_r) - abs(t_p)) / abs(t_p) * 100) if t_p else None
        s_v = (abs(t_r) / v_mes * 100) if v_mes else None
        total_row += [_fmt_clp_m(t_p), _fmt_clp_m(t_r),
                       _fmt_pct(var), f"{s_v:.1f}%" if s_v else "—"]
    var_a = ((abs(total_real_a) - abs(total_ppto_a)) / abs(total_ppto_a) * 100) if total_ppto_a else None
    s_v_a = (abs(total_real_a) / venta_acum * 100) if venta_acum else None
    total_row += [_fmt_clp_m(total_ppto_a), _fmt_clp_m(total_real_a),
                   _fmt_pct(var_a), f"{s_v_a:.1f}%" if s_v_a else "—"]
    data_rows.append(total_row)

    data_rows.append([""] * len(headers))

    # MARGEN OPERATIVO
    data_rows.append(["MARGEN OPERATIVO"] + [""] * (len(headers) - 1))
    margen_row = ["Vta Real + Gastos Ops"]
    for i, m in enumerate(meses):
        v_mes = _venta_periodo(df_venta, year, [m])
        t_r = sum(sub_area_data[sa]["real_meses"][i] for sa in SUB_AREAS_PNL)
        margen = v_mes + t_r  # gastos son negativos
        margen_row += ["", _fmt_clp_m(margen), "", ""]
    margen_acum = venta_acum + total_real_a
    margen_row += ["", _fmt_clp_m(margen_acum), "", ""]
    data_rows.append(margen_row)

    # % Margen Operativo
    margen_pct_row = ["% Margen Operativo"]
    for i, m in enumerate(meses):
        v_mes = _venta_periodo(df_venta, year, [m])
        t_r = sum(sub_area_data[sa]["real_meses"][i] for sa in SUB_AREAS_PNL)
        margen = v_mes + t_r
        pct = (margen / v_mes * 100) if v_mes else None
        margen_pct_row += ["", f"{pct:.1f}%" if pct is not None else "—", "", ""]
    pct_acum = (margen_acum / venta_acum * 100) if venta_acum else None
    margen_pct_row += ["", f"{pct_acum:.1f}%" if pct_acum is not None else "—", "", ""]
    data_rows.append(margen_pct_row)

    df_show = pd.DataFrame(data_rows, columns=headers)
    st.dataframe(df_show, use_container_width=True, hide_index=True, height=520)

    # KPIs resumen abajo
    st.markdown("---")
    cols = st.columns(4)
    cols[0].metric("Venta Real Acum", f"${venta_acum:,.0f} M")
    cols[1].metric("Gastos Ops Acum", f"${abs(total_real_a):,.0f} M",
                    f"{var_a:+.1f}% vs Ppto" if var_a is not None else None,
                    delta_color="inverse")
    cols[2].metric("Margen Operativo Acum", f"${margen_acum:,.0f} M")
    cols[3].metric("% Margen Op Acum", f"{pct_acum:.1f}%" if pct_acum else "—")

    # Descarga Excel
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df_show.to_excel(w, sheet_name="P&L Operaciones", index=False)
    st.download_button(
        "📥 Descargar P&L Operaciones (Excel)",
        data=buf.getvalue(),
        file_name=f"PnL_Operaciones_{year}_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ============================================================
# TAB 2: DETALLE POR CENTRO DE COSTO
# ============================================================
def _tab_detalle_cc(df_costo: pd.DataFrame, df_venta: pd.DataFrame,
                     year: int, meses: list[int]):
    st.markdown(f"#### 🔎 Detalle por Centro de Costo — {year}")
    st.caption(
        "Drill-down: Sub-área › Centro de Costo › Cuenta Analítica · "
        "Ppto vs Real (Fcst) · Desviación + % s/Venta"
    )

    if not meses:
        st.info("Selecciona al menos un mes")
        return

    venta_acum = _venta_periodo(df_venta, year, meses)

    # Filtro: solo gastos del año seleccionado
    df_cc = df_costo[
        (df_costo["year"] == year)
        & (df_costo["month"].isin(meses))
        & (df_costo["kpi"] == "GASTO")
    ].copy()

    if df_cc.empty:
        st.info("Sin datos en el período seleccionado")
        return

    # Agregar por (centro_costo, cuenta_analitica, escenario, month)
    df_pivot = df_cc.pivot_table(
        index=["centro_costo", "cuenta_analitica"],
        columns=["escenario", "month"],
        values="valor",
        aggfunc="sum",
        fill_value=0,
    )

    # Aplanar columnas
    df_flat = df_cc.groupby(["centro_costo", "cuenta_analitica", "escenario"])["valor"].sum().unstack("escenario", fill_value=0)
    if "PPTO" not in df_flat.columns:
        df_flat["PPTO"] = 0
    if "FCST" not in df_flat.columns:
        df_flat["FCST"] = 0
    df_flat["Desv"] = df_flat["FCST"] - df_flat["PPTO"]
    df_flat["% Var"] = df_flat.apply(
        lambda r: ((abs(r["FCST"]) - abs(r["PPTO"])) / abs(r["PPTO"]) * 100)
                   if r["PPTO"] else None,
        axis=1,
    )
    df_flat["% s/Vta"] = df_flat["FCST"].apply(
        lambda v: (abs(v) / venta_acum * 100) if venta_acum else None
    )
    df_flat = df_flat.reset_index().sort_values(
        ["centro_costo", "FCST"], ascending=[True, True]
    )

    df_show = pd.DataFrame({
        "Centro de Costo": df_flat["centro_costo"].str[:35],
        "Cuenta Analítica": df_flat["cuenta_analitica"].str[:35],
        "Ppto Acum": df_flat["PPTO"].apply(_fmt_clp_m),
        "Real Acum": df_flat["FCST"].apply(_fmt_clp_m),
        "Desv $": df_flat["Desv"].apply(_fmt_clp_m),
        "% Var": df_flat["% Var"].apply(_fmt_pct),
        "% s/Vta": df_flat["% s/Vta"].apply(
            lambda v: f"{v:.2f}%" if pd.notna(v) else "—"),
    })
    st.dataframe(df_show, use_container_width=True, hide_index=True, height=560)

    # Descarga Excel con detalle mensual completo
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df_pivot.to_excel(w, sheet_name="Detalle CC mensual")
        df_flat.to_excel(w, sheet_name="Detalle CC acum", index=False)
    st.download_button(
        "📥 Descargar Detalle (Excel mensual + acumulado)",
        data=buf.getvalue(),
        file_name=f"Detalle_CC_{year}_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ============================================================
# TAB 3: INFORME DE GESTIÓN
# ============================================================
def _tab_informe_gestion(df_costo: pd.DataFrame, df_venta: pd.DataFrame,
                          year: int, meses: list[int], periodo_label: str):
    st.markdown(f"#### 📋 Informe de Gestión — Operaciones {periodo_label} {year}")
    st.caption("Análisis automático generado a partir de Ppto vs Real (Fcst)")

    if not meses:
        st.info("Selecciona al menos un mes")
        return

    venta_acum = _venta_periodo(df_venta, year, meses)

    # ─── 1. ANÁLISIS DE VARIACIONES ────────────────────────────────
    st.markdown("### 1. Análisis de Variaciones (Ppto vs Real)")

    sa_data = []
    for sa in SUB_AREAS_PNL:
        ppto = _gasto_por_sub_area(df_costo, year, meses, "PPTO").get(sa, 0)
        real = _gasto_por_sub_area(df_costo, year, meses, "FCST").get(sa, 0)
        desv = real - ppto  # negativo si real < ppto (sobregasto si más negativo)
        sobregasto = abs(real) - abs(ppto)  # positivo = gastó más de lo presupuestado
        pct = (sobregasto / abs(ppto) * 100) if ppto else None
        sa_data.append({
            "sub_area": sa,
            "ppto": ppto,
            "real": real,
            "sobregasto": sobregasto,
            "pct": pct,
        })

    df_sa = pd.DataFrame(sa_data)
    # Top 3 sobregasto (más positivo = peor)
    top_3 = df_sa[df_sa["sobregasto"] > 0].nlargest(3, "sobregasto")

    if not top_3.empty:
        st.markdown(f"**Top {len(top_3)} sub-áreas con mayor sobregasto vs presupuesto:**")
        # Driver principal: para cada sub-área, top 1 cuenta_analitica con mayor desv
        rows_top = []
        for _, r in top_3.iterrows():
            sa = r["sub_area"]
            df_sa_detail = df_costo[
                (df_costo["year"] == year)
                & (df_costo["month"].isin(meses))
                & (df_costo["sub_area"] == sa)
                & (df_costo["kpi"] == "GASTO")
            ]
            piv = df_sa_detail.groupby(["centro_costo", "cuenta_analitica", "escenario"])["valor"].sum().unstack("escenario", fill_value=0)
            if "PPTO" not in piv.columns:
                piv["PPTO"] = 0
            if "FCST" not in piv.columns:
                piv["FCST"] = 0
            piv["sobregasto"] = piv["FCST"].abs() - piv["PPTO"].abs()
            top_driver = piv.nlargest(1, "sobregasto")
            if not top_driver.empty:
                cc, cuenta = top_driver.index[0]
                ppto_d = top_driver["PPTO"].iloc[0]
                real_d = top_driver["FCST"].iloc[0]
                driver = f"{cuenta or cc}: real {_fmt_clp_m(real_d)} vs ppto {_fmt_clp_m(ppto_d)}"
            else:
                driver = "—"

            sa_label = sa.title() if sa not in ("UNIONX", "GRUPO ETER") else sa.replace("GRUPO ETER", "Grupo Eter").replace("UNIONX", "UnionX")
            rows_top.append({
                "Sub-Área": sa_label,
                "Ppto": _fmt_clp_m(r["ppto"]),
                "Real": _fmt_clp_m(r["real"]),
                "Desviación": f"({_fmt_clp_m(r['sobregasto'])})" if r["sobregasto"] > 0 else _fmt_clp_m(r["sobregasto"]),
                "% Desv.": _fmt_pct(r["pct"]),
                "Driver principal": driver[:70],
            })
        st.dataframe(pd.DataFrame(rows_top), use_container_width=True, hide_index=True)
    else:
        st.success("✅ No hay sub-áreas con sobregasto vs presupuesto")

    # Impacto en margen
    sobregasto_total = df_sa[df_sa["sobregasto"] > 0]["sobregasto"].sum()
    if sobregasto_total > 0 and venta_acum > 0:
        impacto_pp = sobregasto_total / venta_acum * 100
        st.markdown(
            f"**Impacto en margen:**  El sobregasto acumulado de "
            f"{len(top_3)} sub-áreas es ~${sobregasto_total:,.0f} M. "
            f"Sobre la venta del período (${venta_acum:,.0f} M), esto representa "
            f"**{impacto_pp:.2f} pp de margen perdido**. Por cada $1,000 adicionales "
            f"en sobregasto, el margen cae ~{1000/venta_acum*100:.3f}%."
        )

    # Nota positiva: sub-área que ahorró
    df_ahorro = df_sa[df_sa["sobregasto"] < -100]  # ahorró > $100 M
    if not df_ahorro.empty:
        ah_top = df_ahorro.nsmallest(1, "sobregasto").iloc[0]
        sa_label = ah_top["sub_area"].title() if ah_top["sub_area"] not in ("UNIONX", "GRUPO ETER") else ah_top["sub_area"].replace("GRUPO ETER", "Grupo Eter").replace("UNIONX", "UnionX")
        # % del total
        total_real_abs = sum(abs(r["real"]) for _, r in df_sa.iterrows())
        peso = (abs(ah_top["real"]) / total_real_abs * 100) if total_real_abs else 0
        st.success(
            f"✅ **Nota positiva: {sa_label}** — la sub-área más relevante "
            f"({peso:.0f}% del gasto total de Ops) — cerró "
            f"${abs(ah_top['sobregasto']):,.0f} M bajo presupuesto "
            f"({ah_top['pct']:.1f}%), compensando los sobrecostos menores."
        )

    st.divider()

    # ─── 2. COMPARATIVO vs FORECAST ───────────────────────────────
    st.markdown("### 2. Comparativo vs Forecast")
    st.caption("Dado que **Fcst = Real** en este modelo, la comparación Ppto vs Real refleja la eficiencia de la proyección inicial.")

    total_ppto = df_sa["ppto"].sum()
    total_real = df_sa["real"].sum()
    ahorro = abs(total_ppto) - abs(total_real)  # positivo = ahorró
    pct_ahorro = (ahorro / abs(total_ppto) * 100) if total_ppto else None

    df_resumen = pd.DataFrame([{
        "Resumen Gasto Ops": "Total Gastos Operacionales",
        "Ppto": _fmt_clp_m(total_ppto),
        "Real": _fmt_clp_m(total_real),
        "Ahorro/(Sobrecosto)": (_fmt_clp_m(ahorro) if ahorro >= 0
                                 else f"({_fmt_clp_m(-ahorro)})"),
        "% Var": _fmt_pct(-pct_ahorro) if pct_ahorro is not None else "—",
    }])
    st.dataframe(df_resumen, use_container_width=True, hide_index=True)

    # Ineficiencias detectadas (gasto puntual mes alto)
    st.markdown("**⚠️ Ineficiencias no previstas detectadas:**")
    ineficiencias = []
    df_mes = df_costo[
        (df_costo["year"] == year)
        & (df_costo["month"].isin(meses))
        & (df_costo["escenario"] == "FCST")
        & (df_costo["kpi"] == "GASTO")
    ]
    # Por (sub_area, cuenta_analitica): ¿algún mes outlier vs promedio?
    for (sa, ct), g in df_mes.groupby(["sub_area", "cuenta_analitica"]):
        if len(g) < 2:
            continue
        montos = g["valor"].abs()
        avg = montos.mean()
        max_m = montos.max()
        if max_m > avg * 2 and max_m > 500:  # outlier > 2x promedio Y > $500M
            mes_max = g.loc[g["valor"].abs().idxmax(), "mes_text"]
            ineficiencias.append(
                f"- **{sa or '?'} / {ct or '?'}**: {mes_max.title()} concentra "
                f"un pago atípico (${max_m:,.0f} M vs ${avg:,.0f} M promedio). "
                "Posible facturación anual o cambio de plan no presupuestado."
            )
    if ineficiencias:
        for i in ineficiencias[:5]:
            st.markdown(i)
    else:
        st.markdown("- Sin outliers significativos detectados en el período")

    st.divider()

    # ─── 3. IMPACTO EN VENTAS ────────────────────────────────────
    st.markdown("### 3. Impacto en Ventas — picos de venta vs eficiencia operativa")

    # Tabla mes a mes con venta + gasto + ratio
    rows_iv = []
    for m in meses:
        venta = _venta_periodo(df_venta, year, [m])
        gasto = abs(sum(_gasto_por_sub_area(df_costo, year, [m], "FCST").get(sa, 0)
                          for sa in SUB_AREAS_PNL))
        ratio = (gasto / venta * 100) if venta else None
        rows_iv.append({
            "Mes": MESES_ES[m],
            "Venta Real": _fmt_clp_m(venta),
            "Gasto Ops": _fmt_clp_m(gasto),
            "Costo/Venta %": f"{ratio:.1f}%" if ratio else "—",
            "Status": ("🟢 OK" if ratio and ratio <= 12
                        else ("🟡 Atención" if ratio and ratio <= 14
                              else "🔴 Alerta")),
        })
    st.dataframe(pd.DataFrame(rows_iv), use_container_width=True, hide_index=True)

    venta_total = sum(_venta_periodo(df_venta, year, [m]) for m in meses)
    gasto_total = abs(sum(
        _gasto_por_sub_area(df_costo, year, meses, "FCST").get(sa, 0)
        for sa in SUB_AREAS_PNL
    ))
    ratio_total = (gasto_total / venta_total * 100) if venta_total else None

    st.markdown(
        f"**Resumen período {periodo_label}:** "
        f"Ratio Costo Ops / Venta = **{ratio_total:.1f}%** "
        f"({'🟢 dentro' if ratio_total and ratio_total <= 12 else '🟠 sobre'} "
        f"benchmark Plan UnionX 8-12%)" if ratio_total else ""
    )


# ============================================================
# RENDER PRINCIPAL
# ============================================================
def render():
    with st.sidebar:
        st.markdown("### 💰 **Costo Operativo**")
        st.caption("P&L · Detalle CC · Informe Gestión")
        st.divider()

    st.title("💰 Costo Operativo Total — Operaciones")
    st.caption(
        "Cierre P&L estilo gerencial · costos del Sheet OPERACIONES + "
        "venta del módulo Ventas · sin desglose por canal (foco: cerrar costo "
        "operativo total empresa)"
    )

    df_costo, res = _cargar()
    df_venta = _cargar_ventas_mensual()

    if df_costo.empty:
        st.warning("⏳ Sin datos. Correr `python extract_ops_costo_operativo.py`")
        return

    st.caption(
        f"🕒 Costos generado: {res.get('generado_en','')[:19]} · "
        f"Ventas parquet: {VENTAS_HIST.stat().st_mtime if VENTAS_HIST.exists() else '?'}"
    )

    # ─── SELECTORES PERÍODO ──────────────────────────────────────────
    st.divider()
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        years = sorted(df_costo["year"].dropna().unique().astype(int).tolist())
        year_sel = st.selectbox("Año", years,
                                  index=len(years) - 1 if years else 0)
    with col2:
        modo = st.selectbox("Período", ["Q1", "Q2", "Q3", "Q4", "YTD", "Mes específico"])
    with col3:
        meses_disp = sorted(df_costo[df_costo["year"] == year_sel]["month"]
                              .dropna().unique().astype(int).tolist())
        if modo == "Q1":
            meses_sel = [1, 2, 3]
            periodo_label = "Q1"
        elif modo == "Q2":
            meses_sel = [4, 5, 6]
            periodo_label = "Q2"
        elif modo == "Q3":
            meses_sel = [7, 8, 9]
            periodo_label = "Q3"
        elif modo == "Q4":
            meses_sel = [10, 11, 12]
            periodo_label = "Q4"
        elif modo == "YTD":
            meses_sel = sorted(meses_disp)
            periodo_label = f"YTD ({MESES_ES.get(min(meses_sel),'?')}-{MESES_ES.get(max(meses_sel),'?')})"
        else:
            mes_unico = st.selectbox(
                "Mes", meses_disp,
                format_func=lambda m: MESES_ES.get(m, str(m)),
            )
            meses_sel = [mes_unico]
            periodo_label = MESES_ES.get(mes_unico, str(mes_unico))

        # Intersectar con meses disponibles
        meses_sel = [m for m in meses_sel if m in meses_disp]
        st.caption(f"📅 **{periodo_label} {year_sel}** · "
                    f"meses cargados: {[MESES_ES[m] for m in meses_sel]}")

    st.divider()

    # ─── 3 SUB-TABS ──────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "📊 P&L Operaciones",
        "🔎 Detalle por Centro de Costo",
        "📋 Informe de Gestión",
    ])
    with tab1:
        _tab_pnl(df_costo, df_venta, year_sel, meses_sel)
    with tab2:
        _tab_detalle_cc(df_costo, df_venta, year_sel, meses_sel)
    with tab3:
        _tab_informe_gestion(df_costo, df_venta, year_sel, meses_sel, periodo_label)
