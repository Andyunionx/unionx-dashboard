"""
Vista Costo Operativo — App Operaciones.

Replica visual del Excel gerencial de Andrés (3 vistas):
  📊 P&L Operaciones (cierre Q/mes)
  🔎 Detalle por Centro de Costo
  📋 Informe de Gestión

Formato:
  - Headers azul oscuro / blanco (corporativo)
  - Sub-headers por mes en gris
  - Filas: Ingresos verde claro · Gastos detalle blanco · Total amarillo · Margen azul
  - Números contables: negativos en (paréntesis) y rojo
  - Variaciones coloreadas según signo
  - Columna ACUMULADO destacada con header más oscuro

Datos:
  - Costos: Sheet OPERACIONES 2025-2026 (Drive)
  - Venta: módulo Ventas (parquet histórico)
"""
import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).parent.parent
PARQUET = PROJECT_ROOT / "data" / "operaciones" / "costo_operativo.parquet"
RESUMEN = PROJECT_ROOT / "data" / "operaciones" / "costo_operativo_resumen.json"
VENTAS_HIST = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"

MESES_ES = {1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO",
            6: "JUNIO", 7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE",
            10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE"}
MESES_SHORT = {k: v[:3].title() for k, v in MESES_ES.items()}

SUB_AREAS_PNL = ["LOGISTICA", "OPERACIONES", "POSTVENTA", "GRUPO ETER", "UNIONX"]
SUB_AREA_LABEL = {
    "LOGISTICA": "Logística", "OPERACIONES": "Operaciones",
    "POSTVENTA": "Postventa", "GRUPO ETER": "Grupo Eter", "UNIONX": "UnionX",
}

# ============================================================
# BENCHMARKS — Operadores 3PL fulfillment LATAM
# ============================================================
# Fuentes públicas: pricing 3PL CL/LATAM 2024-2025 (Bsale, Yunigo, Recíbelo,
# Adexus 3PL, Mainvia). Costo all-in incluye: storage + pick&pack + shipping
# label + handling. Excluye flete a cliente final (es passthrough).
#
# Para una operación con AOV ~$30K-50K CLP y volumen >5K pedidos/mes:
#   3PL premium (con SLA garantizado, integraciones API): 12-18% costo/venta
#   3PL standard (volumen masivo, sin SLA fuerte): 8-14%
#   In-house optimizado (caso UnionX target): 6-10%
#   In-house no optimizado: 14-22%
#
# Comparativa con costo/pedido (más justa que costo/venta para fulfillment):
#   3PL LATAM CL: $1.500-3.500 CLP por pedido (incluye storage + p&p)
#   In-house bien optimizado: $800-1.800 CLP por pedido
BENCH_3PL_VENTA_PCT_BAJO = 8.0      # in-house optimizado
BENCH_3PL_VENTA_PCT_MEDIO = 14.0    # 3PL standard
BENCH_3PL_VENTA_PCT_ALTO = 18.0     # 3PL premium / in-house ineficiente
BENCH_COSTO_POR_PEDIDO_BAJO = 1500   # CLP, 3PL standard
BENCH_COSTO_POR_PEDIDO_ALTO = 3500   # CLP, 3PL premium


# ============================================================
# DATA
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
        for c in ["venta_bruta", "venta_neta", "margen_front", "margen_final"]:
            agg[c + "_m"] = agg[c] / 1000  # CLP → M CLP
        return agg
    except Exception:
        return pd.DataFrame()


# ============================================================
# FORMATO CONTABLE
# ============================================================
def _fmt_num(v, decimals: int = 0) -> str:
    """Formato chileno: '32.615' o '(32.615)' para negativos."""
    if v is None or pd.isna(v) or v == 0:
        return "—"
    abs_v = abs(v)
    if decimals == 0:
        s = f"{abs_v:,.0f}".replace(",", ".")
    else:
        s = f"{abs_v:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"({s})" if v < 0 else s


def _fmt_pct(v) -> str:
    if v is None or pd.isna(v):
        return ""
    s = f"{abs(v):,.1f}%".replace(".", ",")
    return f"({s})" if v < 0 else s


def _color_var(v, es_costo: bool = True) -> str:
    """Color según signo. Costo: positivo (mas gasto) es malo. Margen: positivo es bueno."""
    if v is None or pd.isna(v):
        return "#64748B"
    if es_costo:
        if v > 5:
            return "#DC2626"
        if v > 0:
            return "#EA580C"
        return "#16A34A"
    if v > 0:
        return "#16A34A"
    if v > -5:
        return "#EA580C"
    return "#DC2626"


def _td(content, color="#1E293B", bg="#FFFFFF", weight="400", align="right",
         border_l: str = "", border_r: str = "", padding="6px 10px"):
    border = ""
    if border_l:
        border += f"border-left:{border_l};"
    if border_r:
        border += f"border-right:{border_r};"
    return (f'<td style="padding:{padding};color:{color};background:{bg};'
            f'font-weight:{weight};text-align:{align};{border}'
            f'font-size:12px;">{content}</td>')


def _th(content, bg="#1F4E79", color="#FFFFFF", colspan=1,
         align="center", padding="8px 10px", border_l=""):
    cs = f' colspan="{colspan}"' if colspan > 1 else ""
    border = f"border-left:{border_l};" if border_l else ""
    return (f'<th{cs} style="padding:{padding};background:{bg};color:{color};'
            f'text-align:{align};font-size:11px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.3px;{border}">{content}</th>')


# ============================================================
# AGGREGATORS
# ============================================================
def _gasto_subarea(df: pd.DataFrame, year: int, meses: list[int],
                    escenario: str) -> dict[str, float]:
    f = df[
        (df["year"] == year) & (df["month"].isin(meses))
        & (df["escenario"] == escenario) & (df["kpi"] == "GASTO")
    ]
    return f.groupby("sub_area")["valor"].sum().to_dict()


def _venta_periodo(df_v: pd.DataFrame, year: int, meses: list[int]) -> float:
    """Venta NETA del período (M CLP) — neta = bruta − devoluciones/NC."""
    if df_v.empty:
        return 0
    f = df_v[(df_v["year"] == year) & (df_v["month"].isin(meses))]
    return f["venta_neta_m"].sum()


def _gasto_subarea_tipo(df: pd.DataFrame, year: int, meses: list[int],
                          escenario: str, tipo_costo: str) -> dict[str, float]:
    """Gasto por sub-área filtrado por tipo_costo (FIJO/VARIABLE)."""
    f = df[
        (df["year"] == year) & (df["month"].isin(meses))
        & (df["escenario"] == escenario) & (df["kpi"] == "GASTO")
        & (df["tipo_costo"] == tipo_costo)
    ]
    return f.groupby("sub_area")["valor"].sum().to_dict()


def _tipo_costo_predominante(df: pd.DataFrame, year: int, meses: list[int],
                                cc: str) -> str:
    """Devuelve 'FIJO' o 'VARIABLE' según qué tipo predomine para el CC."""
    f = df[
        (df["year"] == year) & (df["month"].isin(meses))
        & (df["centro_costo"] == cc) & (df["kpi"] == "GASTO")
        & (df["escenario"] == "FCST")
    ]
    if f.empty:
        return ""
    counts = f.groupby("tipo_costo")["valor"].sum().abs().sort_values(ascending=False)
    return counts.index[0] if len(counts) > 0 else ""


# ============================================================
# TAB 1: P&L OPERACIONES (HTML)
# ============================================================
def _tab_pnl(df_costo: pd.DataFrame, df_venta: pd.DataFrame,
              year: int, meses: list[int], periodo_label: str):
    st.markdown(
        f"<h3 style='color:#1F4E79;margin:0 0 4px 0;'>"
        f"P&L OPERACIONES — CIERRE {periodo_label} {year}</h3>"
        f"<p style='color:#64748B;font-size:12px;margin:0 0 16px 0;'>"
        f"Fuente: Data_Gastos | Fcst = Real</p>",
        unsafe_allow_html=True,
    )

    if not meses:
        st.info("Selecciona al menos un mes")
        return

    # Datos por sub-area por mes y acumulado
    sub_data = {sa: {"ppto_m": [], "real_m": [], "ppto_a": 0, "real_a": 0}
                  for sa in SUB_AREAS_PNL}
    for sa in SUB_AREAS_PNL:
        for m in meses:
            sub_data[sa]["ppto_m"].append(
                _gasto_subarea(df_costo, year, [m], "PPTO").get(sa, 0))
            sub_data[sa]["real_m"].append(
                _gasto_subarea(df_costo, year, [m], "FCST").get(sa, 0))
        sub_data[sa]["ppto_a"] = _gasto_subarea(df_costo, year, meses, "PPTO").get(sa, 0)
        sub_data[sa]["real_a"] = _gasto_subarea(df_costo, year, meses, "FCST").get(sa, 0)

    venta_meses = [_venta_periodo(df_venta, year, [m]) for m in meses]
    venta_acum = _venta_periodo(df_venta, year, meses)

    # Totales gastos
    total_ppto_m = [sum(sub_data[sa]["ppto_m"][i] for sa in SUB_AREAS_PNL)
                     for i in range(len(meses))]
    total_real_m = [sum(sub_data[sa]["real_m"][i] for sa in SUB_AREAS_PNL)
                     for i in range(len(meses))]
    total_ppto_a = sum(sub_data[sa]["ppto_a"] for sa in SUB_AREAS_PNL)
    total_real_a = sum(sub_data[sa]["real_a"] for sa in SUB_AREAS_PNL)

    # Margen
    margen_meses = [v + r for v, r in zip(venta_meses, total_real_m)]
    margen_acum = venta_acum + total_real_a

    def _row_data(label, valores_meses, ppto_meses=None, es_total=False,
                    es_seccion=False, bg_label=None, color_label="#1E293B",
                    bg_row=None, italic=False):
        """Genera <tr>...</tr> para una fila del P&L."""
        font_w = "700" if es_total or es_seccion else "400"
        font_style = "italic" if italic else "normal"
        bg_row = bg_row or "#FFFFFF"
        bg_label_use = bg_label or bg_row
        cells = []
        # Etiqueta
        label_html = (f'<td style="padding:6px 12px;background:{bg_label_use};'
                       f'color:{color_label};font-weight:{font_w};font-size:12px;'
                       f'font-style:{font_style};text-align:left;">{label}</td>')
        cells.append(label_html)
        # Por mes (4 cols cada uno)
        # Si es solo etiqueta de sección, no agregar valores (se completan con vacío)
        return cells

    # ─── Construcción HTML ────────────────────────────────────────────
    n_cols_mes = len(meses)
    total_cols = 1 + n_cols_mes * 4 + 4  # label + 4xmes + 4 acum

    # Header 1: meses agrupados
    header_row1 = ["<tr>"]
    header_row1.append(_th("CONCEPTO", bg="#1F4E79", padding="10px 12px",
                            align="left"))
    for m in meses:
        header_row1.append(_th(MESES_ES[m], colspan=4, bg="#1F4E79",
                                 border_l="2px solid #FFFFFF"))
    header_row1.append(_th(f"ACUMULADO {periodo_label}", colspan=4,
                             bg="#0D3A5F", border_l="2px solid #FFFFFF"))
    header_row1.append("</tr>")

    # Header 2: Ppto/Real/%Var/%s/Vta repetido
    header_row2 = ["<tr>"]
    header_row2.append(_th("", bg="#2C5F8D", padding="6px 12px"))
    for i in range(n_cols_mes + 1):  # +1 acumulado
        bg = "#0D3A5F" if i == n_cols_mes else "#2C5F8D"
        bl = "2px solid #FFFFFF" if i == 0 else ""
        for j, sub in enumerate(["Ppto", "Real", "% Var", "% s/Vta"]):
            border_l = "2px solid #FFFFFF" if j == 0 else ""
            header_row2.append(_th(sub, bg=bg, padding="5px 8px",
                                     border_l=border_l))
    header_row2.append("</tr>")

    # ─── ROWS ────────────────────────────────────────────────────────
    rows_html = []

    # Sección INGRESOS
    rows_html.append(
        f'<tr><td colspan="{total_cols}" style="background:#E8F5E9;'
        f'color:#1B5E20;padding:8px 12px;font-weight:700;font-size:12px;'
        f'text-transform:uppercase;letter-spacing:0.5px;">INGRESOS POR VENTA</td></tr>'
    )
    # Venta Ppto (no tenemos, dejamos vacío) — agregamos solo Venta Real
    venta_row = ["<tr>"]
    venta_row.append(_td("Venta Neta", bg="#FFFFFF", weight="600", align="left",
                          color="#1E293B"))
    for v_mes in venta_meses:
        venta_row.append(_td(_fmt_num(v_mes), bg="#FFFFFF", color="#1E293B",
                              border_l="1px solid #E2E8F0"))
        venta_row.append(_td(_fmt_num(v_mes), bg="#FFFFFF", color="#1E293B",
                              weight="600"))
        venta_row.append(_td("—", bg="#FFFFFF", color="#94A3B8"))
        venta_row.append(_td("—", bg="#FFFFFF", color="#94A3B8"))
    venta_row.append(_td(_fmt_num(venta_acum), bg="#F1F5F9", color="#1E293B",
                          border_l="2px solid #1F4E79"))
    venta_row.append(_td(_fmt_num(venta_acum), bg="#F1F5F9", color="#1E293B",
                          weight="700"))
    venta_row.append(_td("—", bg="#F1F5F9", color="#94A3B8"))
    venta_row.append(_td("—", bg="#F1F5F9", color="#94A3B8"))
    venta_row.append("</tr>")
    rows_html.append("".join(venta_row))

    # Comentario % Var Real vs Ppto (vacío porque no tenemos Ppto venta)
    rows_html.append(f'<tr><td colspan="{total_cols}" style="background:#FFFFFF;'
                      f'padding:4px 12px;color:#94A3B8;font-style:italic;'
                      f'font-size:11px;">% Var Real vs Ppto: sin Ppto Venta cargado</td></tr>')

    # Espacio
    rows_html.append(f'<tr><td colspan="{total_cols}" style="height:6px;background:#FAFBFC;"></td></tr>')

    # Sección GASTOS
    rows_html.append(
        f'<tr><td colspan="{total_cols}" style="background:#FFEBE6;'
        f'color:#9F2A0E;padding:8px 12px;font-weight:700;font-size:12px;'
        f'text-transform:uppercase;letter-spacing:0.5px;">GASTOS OPERACIONES</td></tr>'
    )

    for sa in SUB_AREAS_PNL:
        row = ["<tr>"]
        row.append(_td(SUB_AREA_LABEL[sa], bg="#FFFFFF", align="left",
                        weight="500", color="#1E293B"))
        for i, m in enumerate(meses):
            ppto = sub_data[sa]["ppto_m"][i]
            real = sub_data[sa]["real_m"][i]
            v_m = venta_meses[i]
            var = ((abs(real) - abs(ppto)) / abs(ppto) * 100) if ppto else None
            sv = (abs(real) / v_m * 100) if v_m else None
            color_var_c = _color_var(var, es_costo=True)
            row.append(_td(_fmt_num(ppto), bg="#FFFFFF", color="#475569",
                            border_l="1px solid #E2E8F0"))
            row.append(_td(_fmt_num(real), bg="#FFFFFF", color="#1E293B",
                            weight="600"))
            row.append(_td(_fmt_pct(var) if var is not None else "—",
                            bg="#FFFFFF", color=color_var_c, weight="600"))
            row.append(_td(_fmt_pct(sv) if sv is not None else "—",
                            bg="#FFFFFF", color="#64748B"))
        # Acumulado
        ppto_a = sub_data[sa]["ppto_a"]
        real_a = sub_data[sa]["real_a"]
        var_a = ((abs(real_a) - abs(ppto_a)) / abs(ppto_a) * 100) if ppto_a else None
        sv_a = (abs(real_a) / venta_acum * 100) if venta_acum else None
        color_var_ac = _color_var(var_a, es_costo=True)
        row.append(_td(_fmt_num(ppto_a), bg="#F1F5F9", color="#475569",
                        border_l="2px solid #1F4E79"))
        row.append(_td(_fmt_num(real_a), bg="#F1F5F9", color="#1E293B",
                        weight="700"))
        row.append(_td(_fmt_pct(var_a) if var_a is not None else "—",
                        bg="#F1F5F9", color=color_var_ac, weight="700"))
        row.append(_td(_fmt_pct(sv_a) if sv_a is not None else "—",
                        bg="#F1F5F9", color="#475569"))
        row.append("</tr>")
        rows_html.append("".join(row))

    # TOTAL GASTOS OPS
    row = ["<tr>"]
    row.append(_td("TOTAL GASTOS OPS", bg="#FFE082", align="left",
                    weight="700", color="#7F4F00"))
    for i in range(len(meses)):
        t_p = total_ppto_m[i]
        t_r = total_real_m[i]
        v_m = venta_meses[i]
        var = ((abs(t_r) - abs(t_p)) / abs(t_p) * 100) if t_p else None
        sv = (abs(t_r) / v_m * 100) if v_m else None
        color_var_c = _color_var(var, es_costo=True)
        row.append(_td(_fmt_num(t_p), bg="#FFE082", color="#7F4F00", weight="700",
                        border_l="1px solid #E2E8F0"))
        row.append(_td(_fmt_num(t_r), bg="#FFE082", color="#7F4F00", weight="700"))
        row.append(_td(_fmt_pct(var) if var is not None else "—",
                        bg="#FFE082", color=color_var_c, weight="700"))
        row.append(_td(_fmt_pct(sv) if sv is not None else "—",
                        bg="#FFE082", color="#7F4F00", weight="700"))
    var_a = ((abs(total_real_a) - abs(total_ppto_a)) / abs(total_ppto_a) * 100) if total_ppto_a else None
    sv_a = (abs(total_real_a) / venta_acum * 100) if venta_acum else None
    row.append(_td(_fmt_num(total_ppto_a), bg="#FFB74D", color="#7F4F00", weight="700",
                    border_l="2px solid #1F4E79"))
    row.append(_td(_fmt_num(total_real_a), bg="#FFB74D", color="#7F4F00", weight="700"))
    row.append(_td(_fmt_pct(var_a) if var_a is not None else "—",
                    bg="#FFB74D", color=_color_var(var_a, es_costo=True), weight="700"))
    row.append(_td(_fmt_pct(sv_a) if sv_a is not None else "—",
                    bg="#FFB74D", color="#7F4F00", weight="700"))
    row.append("</tr>")
    rows_html.append("".join(row))

    # Espacio
    rows_html.append(f'<tr><td colspan="{total_cols}" style="height:8px;background:#FAFBFC;"></td></tr>')

    # Sección MARGEN
    rows_html.append(
        f'<tr><td colspan="{total_cols}" style="background:#E3F2FD;'
        f'color:#0D47A1;padding:8px 12px;font-weight:700;font-size:12px;'
        f'text-transform:uppercase;letter-spacing:0.5px;">MARGEN OPERATIVO</td></tr>'
    )

    # Vta + Gastos
    row = ["<tr>"]
    row.append(_td("Vta Real + Gastos Ops", bg="#FFFFFF", align="left",
                    weight="700", color="#0D47A1"))
    for i in range(len(meses)):
        v_m = venta_meses[i]
        m = margen_meses[i]
        row.append(_td("", bg="#FFFFFF", border_l="1px solid #E2E8F0"))
        row.append(_td(_fmt_num(m), bg="#FFFFFF", color="#0D47A1", weight="700"))
        row.append(_td("", bg="#FFFFFF"))
        row.append(_td("", bg="#FFFFFF"))
    row.append(_td("", bg="#BBDEFB", border_l="2px solid #1F4E79"))
    row.append(_td(_fmt_num(margen_acum), bg="#BBDEFB", color="#0D47A1", weight="700"))
    row.append(_td("", bg="#BBDEFB"))
    row.append(_td("", bg="#BBDEFB"))
    row.append("</tr>")
    rows_html.append("".join(row))

    # % Margen Operativo
    row = ["<tr>"]
    row.append(_td("% Margen Operativo", bg="#FFFFFF", align="left",
                    weight="600", color="#0D47A1", padding="6px 12px"))
    for i in range(len(meses)):
        v_m = venta_meses[i]
        m = margen_meses[i]
        pct = (m / v_m * 100) if v_m else None
        row.append(_td("", bg="#FFFFFF", border_l="1px solid #E2E8F0"))
        row.append(_td(_fmt_pct(pct) if pct is not None else "—",
                        bg="#FFFFFF", color="#0D47A1", weight="700"))
        row.append(_td("", bg="#FFFFFF"))
        row.append(_td("", bg="#FFFFFF"))
    pct_a = (margen_acum / venta_acum * 100) if venta_acum else None
    row.append(_td("", bg="#BBDEFB", border_l="2px solid #1F4E79"))
    row.append(_td(_fmt_pct(pct_a) if pct_a is not None else "—",
                    bg="#BBDEFB", color="#0D47A1", weight="700"))
    row.append(_td("", bg="#BBDEFB"))
    row.append(_td("", bg="#BBDEFB"))
    row.append("</tr>")
    rows_html.append("".join(row))

    # Tabla completa
    table_html = (
        '<div style="overflow-x:auto;border:1px solid #E2E8F0;border-radius:6px;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;">'
        f'<thead>{"".join(header_row1)}{"".join(header_row2)}</thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        '</table></div>'
    )
    st.markdown(table_html, unsafe_allow_html=True)

    # KPIs abajo
    st.markdown("<br>", unsafe_allow_html=True)
    cols = st.columns(4)
    cols[0].metric("Venta Real Acum", _fmt_num(venta_acum))
    cols[1].metric("Gastos Ops Acum", _fmt_num(abs(total_real_a)),
                    f"{var_a:+.1f}% vs Ppto" if var_a is not None else None,
                    delta_color="inverse")
    cols[2].metric("Margen Op Acum", _fmt_num(margen_acum))
    cols[3].metric("% Margen Op", f"{pct_a:.1f}%" if pct_a else "—")


# ============================================================
# TAB 2: DETALLE POR CC (HTML)
# ============================================================
def _tab_detalle_cc(df_costo: pd.DataFrame, df_venta: pd.DataFrame,
                     year: int, meses: list[int], periodo_label: str):
    st.markdown(
        f"<h3 style='color:#1F4E79;margin:0 0 4px 0;'>"
        f"ANÁLISIS FINANCIERO OPERACIONES — DETALLE POR CC {periodo_label} {year}</h3>"
        f"<p style='color:#64748B;font-size:12px;margin:0 0 16px 0;'>"
        f"Desglose por Sub-Área › Centro de Costo › Cuenta Analítica | Ppto vs Real (Fcst) | Fuente: Data_Gastos</p>",
        unsafe_allow_html=True,
    )

    if not meses:
        st.info("Selecciona al menos un mes")
        return

    venta_acum = _venta_periodo(df_venta, year, meses)

    df_cc = df_costo[
        (df_costo["year"] == year) & (df_costo["month"].isin(meses))
        & (df_costo["kpi"] == "GASTO")
    ].copy()
    if df_cc.empty:
        st.info("Sin datos en el período")
        return

    # Pivot: por CC, cuenta_analitica, escenario, mes
    rows_html = []
    n_meses = len(meses)
    # Header 1
    header_row1 = ["<tr>"]
    header_row1.append(_th("CC / Cuenta Analítica", bg="#1F4E79",
                            padding="10px 12px", align="left"))
    header_row1.append(_th("PPTO", colspan=n_meses + 1, bg="#1F4E79",
                            border_l="2px solid #FFFFFF"))
    header_row1.append(_th("REAL", colspan=n_meses + 1, bg="#A03A20",
                            border_l="2px solid #FFFFFF"))
    header_row1.append(_th("DESV. $", bg="#5E3A1B",
                            border_l="2px solid #FFFFFF"))
    header_row1.append(_th("% Var", bg="#5E3A1B"))
    header_row1.append(_th(f"% s/Vta {periodo_label}", bg="#5E3A1B"))
    header_row1.append("</tr>")

    # Header 2: meses
    header_row2 = ["<tr>"]
    header_row2.append(_th("", bg="#2C5F8D", padding="5px"))
    for m in meses:
        header_row2.append(_th(f"Ppto {MESES_SHORT[m]}", bg="#2C5F8D",
                                 padding="5px 8px",
                                 border_l="1px solid #FFFFFF" if m == meses[0] else ""))
    header_row2.append(_th(f"PPTO {periodo_label}", bg="#0D3A5F",
                             padding="5px 8px",
                             border_l="1px solid #FFFFFF"))
    for m in meses:
        header_row2.append(_th(f"Real {MESES_SHORT[m]}", bg="#B85B47",
                                 padding="5px 8px",
                                 border_l="1px solid #FFFFFF" if m == meses[0] else ""))
    header_row2.append(_th(f"REAL {periodo_label}", bg="#7F2C16",
                             padding="5px 8px",
                             border_l="1px solid #FFFFFF"))
    header_row2.append(_th("", bg="#5E3A1B", padding="5px",
                             border_l="2px solid #FFFFFF"))
    header_row2.append(_th("", bg="#5E3A1B", padding="5px"))
    header_row2.append(_th("", bg="#5E3A1B", padding="5px"))
    header_row2.append("</tr>")

    # Filas: agrupar por CC, dentro detalle por cuenta_analitica
    df_cc_grp = (df_cc.groupby(["centro_costo", "cuenta_analitica",
                                  "escenario", "month"])
                       ["valor"].sum().reset_index())
    cc_order = (df_cc.groupby("centro_costo")["valor"].sum().abs()
                       .sort_values(ascending=False).index.tolist())

    bg_alt = ["#FFFFFF", "#F8FAFC"]

    for cc in cc_order:
        # Header de CC con TIPO COSTO + total + % s/venta
        cc_data = df_cc[df_cc["centro_costo"] == cc]
        tipo_pred = _tipo_costo_predominante(df_costo, year, meses, cc)
        cc_real_total = cc_data[cc_data["escenario"] == "FCST"]["valor"].sum()
        cc_ppto_total = cc_data[cc_data["escenario"] == "PPTO"]["valor"].sum()
        cc_pct_vta = (abs(cc_real_total) / venta_acum * 100) if venta_acum else 0

        # Tag color según tipo
        tipo_tag = ""
        if tipo_pred == "FIJO":
            tipo_tag = ('<span style="background:#1F4E79;color:#FFFFFF;'
                          'padding:2px 8px;border-radius:10px;font-size:10px;'
                          'margin-left:8px;font-weight:700;">FIJO</span>')
        elif tipo_pred == "VARIABLE":
            tipo_tag = ('<span style="background:#EA580C;color:#FFFFFF;'
                          'padding:2px 8px;border-radius:10px;font-size:10px;'
                          'margin-left:8px;font-weight:700;">VARIABLE</span>')

        cc_summary = (f'{cc or "—"}{tipo_tag}'
                       f'<span style="float:right;font-weight:600;color:#1E40AF;'
                       f'font-size:11px;">Real: {_fmt_num(cc_real_total)} · '
                       f'{cc_pct_vta:.2f}% s/Vta</span>')
        rows_html.append(
            f'<tr><td colspan="{1 + (n_meses+1)*2 + 3}" '
            f'style="background:#DBEAFE;color:#1E40AF;padding:6px 12px;'
            f'font-weight:700;font-size:11px;text-transform:uppercase;'
            f'letter-spacing:0.5px;">{cc_summary}</td></tr>'
        )

        # Cuentas analíticas dentro del CC
        cuentas = df_cc[df_cc["centro_costo"] == cc]["cuenta_analitica"].dropna().unique()
        for idx, cta in enumerate(sorted(cuentas)):
            bg = bg_alt[idx % 2]
            f_ct = df_cc[(df_cc["centro_costo"] == cc)
                          & (df_cc["cuenta_analitica"] == cta)]
            row = ["<tr>"]
            row.append(_td(f"  {cta}", bg=bg, align="left", color="#1E293B",
                            padding="5px 12px 5px 28px"))

            ppto_ms = []
            real_ms = []
            for m in meses:
                p = f_ct[(f_ct["escenario"] == "PPTO")
                          & (f_ct["month"] == m)]["valor"].sum()
                r = f_ct[(f_ct["escenario"] == "FCST")
                          & (f_ct["month"] == m)]["valor"].sum()
                ppto_ms.append(p)
                real_ms.append(r)
                row.append(_td(_fmt_num(p), bg=bg, color="#475569",
                                border_l="1px solid #E2E8F0" if m == meses[0] else ""))
            ppto_a = sum(ppto_ms)
            real_a = sum(real_ms)
            row.append(_td(_fmt_num(ppto_a), bg="#E0E7FF" if bg == "#FFFFFF" else "#C7D2FE",
                            color="#1E293B", weight="700",
                            border_l="2px solid #1F4E79"))
            for i, m in enumerate(meses):
                row.append(_td(_fmt_num(real_ms[i]), bg=bg, color="#1E293B",
                                border_l="1px solid #E2E8F0" if i == 0 else ""))
            row.append(_td(_fmt_num(real_a), bg="#FED7D2" if bg == "#FFFFFF" else "#FBCAB8",
                            color="#1E293B", weight="700",
                            border_l="2px solid #A03A20"))
            desv = real_a - ppto_a
            var = ((abs(real_a) - abs(ppto_a)) / abs(ppto_a) * 100) if ppto_a else None
            sv = (abs(real_a) / venta_acum * 100) if venta_acum else None
            row.append(_td(_fmt_num(desv), bg=bg,
                            color=_color_var(var, es_costo=True), weight="600",
                            border_l="2px solid #5E3A1B"))
            row.append(_td(_fmt_pct(var) if var is not None else "—",
                            bg=bg, color=_color_var(var, es_costo=True), weight="600"))
            row.append(_td(f"{sv:.2f}%".replace(".", ",") if sv else "—",
                            bg=bg, color="#64748B"))
            row.append("</tr>")
            rows_html.append("".join(row))

    table_html = (
        '<div style="overflow-x:auto;border:1px solid #E2E8F0;border-radius:6px;'
        'max-height:680px;overflow-y:auto;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;">'
        f'<thead style="position:sticky;top:0;z-index:1;">{"".join(header_row1)}{"".join(header_row2)}</thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        '</table></div>'
    )
    st.markdown(table_html, unsafe_allow_html=True)

    # Excel descarga
    df_export = df_cc.pivot_table(
        index=["centro_costo", "cuenta_analitica"],
        columns=["escenario", "month"], values="valor",
        aggfunc="sum", fill_value=0,
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df_export.to_excel(w, sheet_name="Detalle CC")
    st.download_button(
        "📥 Descargar Excel",
        data=buf.getvalue(),
        file_name=f"Detalle_CC_{periodo_label}_{year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ============================================================
# TAB 3: INFORME DE GESTIÓN (HTML estilizado)
# ============================================================
def _tab_informe(df_costo: pd.DataFrame, df_venta: pd.DataFrame,
                  year: int, meses: list[int], periodo_label: str):
    st.markdown(
        f"<h3 style='color:#1F4E79;margin:0 0 4px 0;'>"
        f"INFORME DE ANÁLISIS DE GESTIÓN — OPERACIONES {periodo_label} {year}</h3>"
        f"<p style='color:#64748B;font-size:12px;margin:0 0 16px 0;'>"
        f"Management Report | Cierre Trimestral | Área: Operaciones | "
        f"Fuente: PL Operaciones {periodo_label} → Data_Gastos | Fcst = Real</p>",
        unsafe_allow_html=True,
    )

    if not meses:
        st.info("Selecciona al menos un mes")
        return

    venta_acum = _venta_periodo(df_venta, year, meses)

    # ─── 1. ANÁLISIS DE VARIACIONES ────────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:16px 0 12px 0;font-weight:700;font-size:13px;'
        'letter-spacing:0.5px;">1. ANÁLISIS DE VARIACIONES (Ppto vs Real)</div>',
        unsafe_allow_html=True,
    )
    st.markdown(f"<p style='font-size:13px;margin:0 0 8px 0;'>"
                f"<b>Top 3 Sub-Áreas con mayor sobregasto vs presupuesto:</b></p>",
                unsafe_allow_html=True)

    sa_data = []
    for sa in SUB_AREAS_PNL:
        ppto = _gasto_subarea(df_costo, year, meses, "PPTO").get(sa, 0)
        real = _gasto_subarea(df_costo, year, meses, "FCST").get(sa, 0)
        sobregasto = abs(real) - abs(ppto)
        pct = (sobregasto / abs(ppto) * 100) if ppto else None
        sa_data.append({"sa": sa, "ppto": ppto, "real": real,
                          "sobregasto": sobregasto, "pct": pct})
    df_sa = pd.DataFrame(sa_data)
    top_3 = df_sa[df_sa["sobregasto"] > 0].nlargest(3, "sobregasto")

    # Tabla top 3 con HTML
    if not top_3.empty:
        rows = []
        rows.append(
            "<tr>"
            + _th("#", bg="#1F4E79", padding="8px") + _th("Sub-Área", bg="#1F4E79", align="left")
            + _th(f"Ppto {periodo_label}", bg="#1F4E79")
            + _th(f"Real {periodo_label}", bg="#1F4E79")
            + _th("Desviación", bg="#1F4E79")
            + _th("% Desv.", bg="#1F4E79")
            + _th("Driver principal", bg="#1F4E79", align="left")
            + "</tr>"
        )
        for i, (_, r) in enumerate(top_3.iterrows(), 1):
            sa = r["sa"]
            # Driver: top cuenta analítica con mayor sobregasto
            df_sd = df_costo[
                (df_costo["year"] == year) & (df_costo["month"].isin(meses))
                & (df_costo["sub_area"] == sa) & (df_costo["kpi"] == "GASTO")
            ]
            piv = (df_sd.groupby(["cuenta_analitica", "escenario"])["valor"]
                          .sum().unstack("escenario", fill_value=0))
            if "PPTO" not in piv.columns:
                piv["PPTO"] = 0
            if "FCST" not in piv.columns:
                piv["FCST"] = 0
            piv["sg"] = piv["FCST"].abs() - piv["PPTO"].abs()
            top_d = piv.nlargest(1, "sg")
            driver = "—"
            if not top_d.empty:
                cta = top_d.index[0]
                rmax = top_d.iloc[0]
                # Buscar en qué mes pasó
                mes_max = df_sd[df_sd["cuenta_analitica"] == cta].sort_values(
                    "valor", key=lambda s: s.abs(), ascending=False
                )["mes_text"].iloc[0] if not df_sd[df_sd["cuenta_analitica"] == cta].empty else "?"
                driver = (f"{cta}: {mes_max[:3].title()} ${abs(rmax['FCST']):,.0f} "
                          f"vs ppto ${abs(rmax['PPTO']):,.0f}").replace(",", ".")
            rows.append(
                "<tr>"
                + _td(str(i), bg="#FFFFFF", color="#1E293B", weight="700", align="center")
                + _td(SUB_AREA_LABEL[sa], bg="#FFFFFF", color="#DC2626",
                       weight="700", align="left")
                + _td(_fmt_num(r["ppto"]), bg="#FFFFFF", color="#475569")
                + _td(_fmt_num(r["real"]), bg="#FFFFFF", color="#1E293B", weight="600")
                + _td(_fmt_num(-r["sobregasto"]), bg="#FFFFFF",
                       color="#DC2626", weight="700")
                + _td(_fmt_pct(r["pct"]), bg="#FFFFFF",
                       color="#DC2626", weight="700")
                + _td(driver, bg="#FFFFFF", color="#475569", align="left",
                       padding="6px 10px")
                + "</tr>"
            )
        st.markdown(
            '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
            '<table style="border-collapse:collapse;width:100%;font-family:'
            '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
            f'{"".join(rows)}'
            '</table></div>',
            unsafe_allow_html=True,
        )

    # Impacto en margen
    sg_total = df_sa[df_sa["sobregasto"] > 0]["sobregasto"].sum()
    if sg_total > 0 and venta_acum > 0:
        impacto_pp = sg_total / venta_acum * 100
        st.markdown(
            f"<p style='font-size:13px;margin:12px 0 0 0;'><b>Impacto en margen:</b><br>"
            f"El sobregasto acumulado de estas {len(top_3)} sub-áreas es ~${sg_total:,.0f}. "
            f"Sobre la venta real {periodo_label} de ${venta_acum:,.0f}, esto representa "
            f"<b>{impacto_pp:.2f} pp</b> de margen perdido. Por cada $1.000 adicionales "
            f"en estas sub-áreas, el margen cae ~{1000/venta_acum*100:.3f}%.</p>",
            unsafe_allow_html=True,
        )

    # Nota positiva (sub-área que ahorró)
    df_ahorro = df_sa[df_sa["sobregasto"] < -100]
    if not df_ahorro.empty:
        ah = df_ahorro.nsmallest(1, "sobregasto").iloc[0]
        total_real_abs = sum(abs(r["real"]) for _, r in df_sa.iterrows())
        peso = (abs(ah["real"]) / total_real_abs * 100) if total_real_abs else 0
        st.markdown(
            f'<div style="background:#E8F5E9;border-left:4px solid #16A34A;'
            f'padding:10px 14px;margin:12px 0;border-radius:4px;font-size:13px;">'
            f'<b style="color:#1B5E20;">✅ Nota positiva: {SUB_AREA_LABEL[ah["sa"]]}</b> — la sub-área '
            f'más relevante ({peso:.0f}% del gasto total de Ops) — cerró '
            f'<b>${abs(ah["sobregasto"]):,.0f} bajo presupuesto</b> ({ah["pct"]:.1f}%), '
            f'compensando con creces los sobrecostos menores.'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ─── 2. COMPARATIVO vs FORECAST ───────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:24px 0 12px 0;font-weight:700;font-size:13px;'
        'letter-spacing:0.5px;">2. COMPARATIVO vs FORECAST</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='font-size:13px;margin:0 0 8px 0;font-style:italic;color:#64748B;'>"
        f"Dado que Fcst = Real en este modelo, la comparación Ppto vs Real refleja "
        f"la eficiencia de la proyección inicial.</p>",
        unsafe_allow_html=True,
    )

    total_ppto = df_sa["ppto"].sum()
    total_real = df_sa["real"].sum()
    ahorro = abs(total_ppto) - abs(total_real)
    pct_ahorro = (ahorro / abs(total_ppto) * 100) if total_ppto else None

    rows = []
    rows.append(
        "<tr>"
        + _th(f"Resumen Gasto Ops {periodo_label}", bg="#1F4E79", align="left")
        + _th("Ppto", bg="#1F4E79")
        + _th("Real", bg="#1F4E79")
        + _th("Ahorro / (Sobrecosto)", bg="#1F4E79")
        + _th("% Var", bg="#1F4E79")
        + "</tr>"
    )
    color_ah = "#16A34A" if ahorro >= 0 else "#DC2626"
    rows.append(
        "<tr>"
        + _td("Total Gastos Operacionales", bg="#FFFFFF", weight="600",
               color="#1E293B", align="left")
        + _td(_fmt_num(total_ppto), bg="#FFFFFF", color="#475569")
        + _td(_fmt_num(total_real), bg="#FFFFFF", color="#1E293B", weight="600")
        + _td(_fmt_num(ahorro if ahorro >= 0 else -ahorro),
               bg="#FFFFFF", color=color_ah, weight="700")
        + _td(_fmt_pct(-pct_ahorro) if pct_ahorro is not None else "—",
               bg="#FFFFFF", color=color_ah, weight="700")
        + "</tr>"
    )
    st.markdown(
        '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
        f'{"".join(rows)}</table></div>',
        unsafe_allow_html=True,
    )

    # Ineficiencias
    st.markdown(
        f"<p style='font-size:13px;margin:14px 0 8px 0;'>"
        f"<b>⚠️ Ineficiencias no previstas detectadas:</b></p>",
        unsafe_allow_html=True,
    )

    df_mes = df_costo[
        (df_costo["year"] == year) & (df_costo["month"].isin(meses))
        & (df_costo["escenario"] == "FCST") & (df_costo["kpi"] == "GASTO")
    ]
    inef = []
    for (sa, ct), g in df_mes.groupby(["sub_area", "cuenta_analitica"]):
        if len(g) < 2:
            continue
        montos = g["valor"].abs()
        avg = montos.mean()
        max_m = montos.max()
        if max_m > avg * 2 and max_m > 500:
            mes_max = g.loc[g["valor"].abs().idxmax(), "mes_text"]
            inef.append({
                "sa": sa, "cta": ct,
                "mes": mes_max, "max": max_m, "avg": avg,
            })
    inef.sort(key=lambda x: x["max"], reverse=True)

    if inef:
        items_html = []
        for i in inef[:5]:
            items_html.append(
                f'<li style="margin:4px 0;font-size:13px;">'
                f'<b>{i["sa"] or "?"} / {i["cta"] or "?"}:</b> '
                f'{i["mes"][:3].title()} concentra un pago atípico '
                f'(${i["max"]:,.0f} vs ${i["avg"]:,.0f} promedio mensual). '
                f'Posible facturación anual o cambio de plan no presupuestado.'
                f'</li>'
            )
        st.markdown(
            f'<div style="background:#FFF8E1;border-left:4px solid #F59E0B;'
            f'padding:10px 14px;margin:8px 0;border-radius:4px;">'
            f'<ul style="margin:0;padding-left:20px;">{"".join(items_html)}</ul>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background:#E8F5E9;border-left:4px solid #16A34A;'
            'padding:10px 14px;margin:8px 0;border-radius:4px;font-size:13px;">'
            'Sin outliers significativos detectados en el período.</div>',
            unsafe_allow_html=True,
        )

    # ─── 3. IMPACTO EN VENTAS ────────────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:24px 0 12px 0;font-weight:700;font-size:13px;'
        'letter-spacing:0.5px;">3. IMPACTO EN VENTAS — PICOS DE VENTA vs EFICIENCIA OPERATIVA</div>',
        unsafe_allow_html=True,
    )

    rows = []
    rows.append(
        "<tr>"
        + _th("Mes", bg="#1F4E79", align="left")
        + _th("Venta Real", bg="#1F4E79")
        + _th("Gasto Ops", bg="#1F4E79")
        + _th("Costo / Venta %", bg="#1F4E79")
        + _th("Status", bg="#1F4E79")
        + "</tr>"
    )
    for m in meses:
        v = _venta_periodo(df_venta, year, [m])
        g = abs(sum(_gasto_subarea(df_costo, year, [m], "FCST").get(sa, 0)
                      for sa in SUB_AREAS_PNL))
        ratio = (g / v * 100) if v else None
        if ratio is None:
            status, color = "—", "#94A3B8"
        elif ratio <= 12:
            status, color = "🟢 OK", "#16A34A"
        elif ratio <= 14:
            status, color = "🟡 Atención", "#EA580C"
        else:
            status, color = "🔴 Alerta", "#DC2626"
        rows.append(
            "<tr>"
            + _td(MESES_SHORT[m], bg="#FFFFFF", weight="600", color="#1E293B", align="left")
            + _td(_fmt_num(v), bg="#FFFFFF", color="#1E293B")
            + _td(_fmt_num(g), bg="#FFFFFF", color="#1E293B")
            + _td(f"{ratio:.1f}%".replace(".", ",") if ratio else "—",
                   bg="#FFFFFF", color=color, weight="700")
            + _td(status, bg="#FFFFFF", color=color, weight="600")
            + "</tr>"
        )
    # Acumulado
    g_t = abs(sum(_gasto_subarea(df_costo, year, meses, "FCST").get(sa, 0)
                    for sa in SUB_AREAS_PNL))
    ratio_t = (g_t / venta_acum * 100) if venta_acum else None
    if ratio_t is None:
        status_t, color_t = "—", "#94A3B8"
    elif ratio_t <= 12:
        status_t, color_t = "🟢 OK", "#16A34A"
    elif ratio_t <= 14:
        status_t, color_t = "🟡 Atención", "#EA580C"
    else:
        status_t, color_t = "🔴 Alerta", "#DC2626"
    rows.append(
        "<tr>"
        + _td(periodo_label, bg="#1F4E79", color="#FFFFFF", weight="700", align="left")
        + _td(_fmt_num(venta_acum), bg="#1F4E79", color="#FFFFFF", weight="700")
        + _td(_fmt_num(g_t), bg="#1F4E79", color="#FFFFFF", weight="700")
        + _td(f"{ratio_t:.1f}%".replace(".", ",") if ratio_t else "—",
               bg="#1F4E79", color="#FFFFFF", weight="700")
        + _td(status_t, bg="#1F4E79", color="#FFFFFF", weight="700")
        + "</tr>"
    )
    st.markdown(
        '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
        f'{"".join(rows)}</table></div>',
        unsafe_allow_html=True,
    )

    if ratio_t is not None:
        msg = ("<b>dentro</b>" if ratio_t <= 12 else "<b>sobre</b>")
        st.markdown(
            f"<p style='font-size:13px;margin:14px 0 0 0;'>"
            f"<b>Resumen período {periodo_label}:</b> Ratio Costo Ops / Venta = "
            f"<b style='color:{color_t};'>{ratio_t:.1f}%</b> "
            f"({msg} benchmark Plan UnionX 8-12%).</p>",
            unsafe_allow_html=True,
        )

    # ─── 4. BENCHMARK ────────────────────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:24px 0 12px 0;font-weight:700;font-size:13px;'
        'letter-spacing:0.5px;">4. BENCHMARK vs PLAN ESTRATÉGICO UNIONX 2026-2028</div>',
        unsafe_allow_html=True,
    )

    # Calcular métricas vs benchmarks Plan UnionX
    fijo_t = sum(_gasto_subarea_tipo(df_costo, year, meses, "FCST", "FIJO").get(sa, 0)
                  for sa in SUB_AREAS_PNL)
    var_t = sum(_gasto_subarea_tipo(df_costo, year, meses, "FCST", "VARIABLE").get(sa, 0)
                 for sa in SUB_AREAS_PNL)
    total_clasif = abs(fijo_t) + abs(var_t)
    pct_var = (abs(var_t) / total_clasif * 100) if total_clasif > 0 else 0

    bench_rows = []
    bench_rows.append(
        "<tr>"
        + _th("Indicador", bg="#1F4E79", align="left")
        + _th("Real Período", bg="#1F4E79")
        + _th("Meta UnionX", bg="#1F4E79")
        + _th("Benchmark Industria", bg="#1F4E79")
        + _th("Status", bg="#1F4E79")
        + "</tr>"
    )
    benchmarks = [
        {
            "ind": "Costo Operativo / Venta",
            "real": ratio_t if ratio_t else 0,
            "meta": "8-12%", "industria": "10-15%",
            "ok": (ratio_t and ratio_t <= 12),
            "atencion": (ratio_t and ratio_t <= 14),
            "fmt": "pct",
        },
        {
            "ind": "% Costos Variables (flexibilidad)",
            "real": pct_var,
            "meta": "≥50%", "industria": "40-60%",
            "ok": pct_var >= 50, "atencion": pct_var >= 35,
            "fmt": "pct",
        },
        {
            "ind": "Costo / Pedido",
            "real": (abs(g_t) * 1_000_000 / df_venta[
                (df_venta["year"] == year) & (df_venta["month"].isin(meses))
            ]["n_pedidos"].sum()) if (not df_venta.empty
                                       and df_venta[(df_venta["year"] == year)
                                                      & (df_venta["month"].isin(meses))]
                                                      ["n_pedidos"].sum() > 0) else 0,
            "meta": "↓ 10-15% YoY", "industria": "$800K-1.5MM",
            "ok": True, "atencion": True,
            "fmt": "clp",
        },
    ]

    for b in benchmarks:
        if b["fmt"] == "pct":
            real_fmt = f"{b['real']:.1f}%".replace(".", ",")
        else:
            real_fmt = f"${b['real']:,.0f}".replace(",", ".")

        if b["ok"]:
            status, color = "🟢 Cumple", "#16A34A"
        elif b["atencion"]:
            status, color = "🟡 Atención", "#EA580C"
        else:
            status, color = "🔴 Bajo meta", "#DC2626"

        bench_rows.append(
            "<tr>"
            + _td(b["ind"], bg="#FFFFFF", color="#1E293B", weight="600", align="left")
            + _td(real_fmt, bg="#FFFFFF", color=color, weight="700")
            + _td(b["meta"], bg="#FFFFFF", color="#475569")
            + _td(b["industria"], bg="#FFFFFF", color="#64748B")
            + _td(status, bg="#FFFFFF", color=color, weight="700")
            + "</tr>"
        )

    st.markdown(
        '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
        f'{"".join(bench_rows)}</table></div>',
        unsafe_allow_html=True,
    )

    # Sumario benchmark
    st.markdown(
        f'<p style="font-size:12px;color:#64748B;margin:10px 0 0 0;font-style:italic;">'
        f'Benchmarks Plan UnionX 2026-2028: costo/pedido ↓ 10-15% YoY · '
        f'costo logístico/venta 8-12% óptimo · margen contribución ≥35% · '
        f'EBITDA ≥12%. Benchmark industria: retail multi-canal CL.'
        f'</p>',
        unsafe_allow_html=True,
    )


# ============================================================
# TAB 4: COMPARATIVO YoY
# ============================================================
def _tab_yoy(df_costo: pd.DataFrame, df_venta: pd.DataFrame,
              year: int, meses: list[int], periodo_label: str):
    year_ant = year - 1
    st.markdown(
        f"<h3 style='color:#1F4E79;margin:0 0 4px 0;'>"
        f"COMPARATIVO YoY — {periodo_label} {year} vs {year_ant}</h3>"
        f"<p style='color:#64748B;font-size:12px;margin:0 0 16px 0;'>"
        f"Análisis evolución año contra año por sub-área y CC</p>",
        unsafe_allow_html=True,
    )

    if not meses:
        st.info("Selecciona al menos un mes")
        return

    # Datos por sub-área ambos años
    rows_html = []
    headers = (
        "<tr>"
        + _th("SUB-ÁREA", bg="#1F4E79", align="left")
        + _th(f"Real {year_ant}", bg="#475569")
        + _th(f"Real {year}", bg="#1F4E79")
        + _th("Var $", bg="#1F4E79")
        + _th("Var %", bg="#1F4E79")
        + _th(f"% s/Vta {year_ant}", bg="#475569")
        + _th(f"% s/Vta {year}", bg="#1F4E79")
        + _th("Δ pp", bg="#1F4E79")
        + "</tr>"
    )

    venta_actual = _venta_periodo(df_venta, year, meses)
    venta_ant = _venta_periodo(df_venta, year_ant, meses)

    yoy_data = []
    for sa in SUB_AREAS_PNL:
        real_act = _gasto_subarea(df_costo, year, meses, "FCST").get(sa, 0)
        real_ant = _gasto_subarea(df_costo, year_ant, meses, "FCST").get(sa, 0)
        var_abs = abs(real_act) - abs(real_ant)
        var_pct = (var_abs / abs(real_ant) * 100) if real_ant else None
        pct_v_act = (abs(real_act) / venta_actual * 100) if venta_actual else 0
        pct_v_ant = (abs(real_ant) / venta_ant * 100) if venta_ant else 0
        delta_pp = pct_v_act - pct_v_ant
        yoy_data.append({
            "sa": sa, "real_act": real_act, "real_ant": real_ant,
            "var_abs": var_abs, "var_pct": var_pct,
            "pct_v_act": pct_v_act, "pct_v_ant": pct_v_ant, "delta_pp": delta_pp,
        })
        color_var = _color_var(var_pct, es_costo=True)
        color_pp = _color_var(delta_pp, es_costo=True)
        rows_html.append(
            "<tr>"
            + _td(SUB_AREA_LABEL[sa], bg="#FFFFFF", weight="600",
                   color="#1E293B", align="left")
            + _td(_fmt_num(real_ant), bg="#FFFFFF", color="#475569")
            + _td(_fmt_num(real_act), bg="#FFFFFF", color="#1E293B", weight="700")
            + _td(_fmt_num(-var_abs), bg="#FFFFFF", color=color_var, weight="600")
            + _td(_fmt_pct(var_pct) if var_pct is not None else "—",
                   bg="#FFFFFF", color=color_var, weight="700")
            + _td(f"{pct_v_ant:.2f}%".replace(".", ","),
                   bg="#FFFFFF", color="#475569")
            + _td(f"{pct_v_act:.2f}%".replace(".", ","),
                   bg="#FFFFFF", color="#1E293B", weight="600")
            + _td(f"{delta_pp:+.2f} pp".replace(".", ","),
                   bg="#FFFFFF", color=color_pp, weight="700")
            + "</tr>"
        )

    # Total
    df_yoy = pd.DataFrame(yoy_data)
    real_act_t = df_yoy["real_act"].sum()
    real_ant_t = df_yoy["real_ant"].sum()
    var_t = abs(real_act_t) - abs(real_ant_t)
    var_pct_t = (var_t / abs(real_ant_t) * 100) if real_ant_t else None
    pct_v_act_t = (abs(real_act_t) / venta_actual * 100) if venta_actual else 0
    pct_v_ant_t = (abs(real_ant_t) / venta_ant * 100) if venta_ant else 0
    delta_t = pct_v_act_t - pct_v_ant_t
    rows_html.append(
        "<tr>"
        + _td("TOTAL", bg="#FFE082", color="#7F4F00", weight="700", align="left")
        + _td(_fmt_num(real_ant_t), bg="#FFE082", color="#7F4F00", weight="700")
        + _td(_fmt_num(real_act_t), bg="#FFE082", color="#7F4F00", weight="700")
        + _td(_fmt_num(-var_t), bg="#FFE082",
               color=_color_var(var_pct_t, es_costo=True), weight="700")
        + _td(_fmt_pct(var_pct_t) if var_pct_t is not None else "—",
               bg="#FFE082", color=_color_var(var_pct_t, es_costo=True), weight="700")
        + _td(f"{pct_v_ant_t:.2f}%".replace(".", ","),
               bg="#FFE082", color="#7F4F00", weight="700")
        + _td(f"{pct_v_act_t:.2f}%".replace(".", ","),
               bg="#FFE082", color="#7F4F00", weight="700")
        + _td(f"{delta_t:+.2f} pp".replace(".", ","),
               bg="#FFE082", color=_color_var(delta_t, es_costo=True), weight="700")
        + "</tr>"
    )

    st.markdown(
        '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
        f'<thead>{headers}</thead><tbody>{"".join(rows_html)}</tbody></table></div>',
        unsafe_allow_html=True,
    )

    # KPIs YoY
    st.markdown("<br>", unsafe_allow_html=True)
    cols = st.columns(4)
    cols[0].metric(f"Venta neta {year}", _fmt_num(venta_actual),
                    f"{((venta_actual/venta_ant-1)*100):+.1f}% YoY"
                    if venta_ant else None)
    cols[1].metric(f"Gasto Op {year}", _fmt_num(abs(real_act_t)),
                    f"{var_pct_t:+.1f}% YoY" if var_pct_t is not None else None,
                    delta_color="inverse")
    cols[2].metric(f"% Costo/Vta {year}", f"{pct_v_act_t:.1f}%",
                    f"{delta_t:+.1f} pp YoY", delta_color="inverse")
    cols[3].metric("Eficiencia",
                    "Mejorando" if delta_t < -0.5 else
                    "Empeorando" if delta_t > 0.5 else "Estable")

    st.divider()

    # Detalle por CC YoY
    st.markdown("<h4 style='color:#1F4E79;'>📊 Detalle YoY por Centro de Costo</h4>",
                  unsafe_allow_html=True)

    cc_yoy = []
    for cc in df_costo[df_costo["kpi"] == "GASTO"]["centro_costo"].dropna().unique():
        if not cc:
            continue
        f_act = df_costo[
            (df_costo["year"] == year) & (df_costo["month"].isin(meses))
            & (df_costo["centro_costo"] == cc) & (df_costo["escenario"] == "FCST")
            & (df_costo["kpi"] == "GASTO")
        ]["valor"].sum()
        f_ant = df_costo[
            (df_costo["year"] == year_ant) & (df_costo["month"].isin(meses))
            & (df_costo["centro_costo"] == cc) & (df_costo["escenario"] == "FCST")
            & (df_costo["kpi"] == "GASTO")
        ]["valor"].sum()
        cc_yoy.append({"cc": cc, "act": f_act, "ant": f_ant,
                         "var_abs": abs(f_act) - abs(f_ant),
                         "var_pct": ((abs(f_act) - abs(f_ant)) / abs(f_ant) * 100)
                                     if f_ant else None})
    cc_yoy = sorted(cc_yoy, key=lambda x: x["var_abs"], reverse=True)

    cc_rows = ["<tr>" + _th("Centro Costo", bg="#1F4E79", align="left")
                + _th(f"Real {year_ant}", bg="#475569")
                + _th(f"Real {year}", bg="#1F4E79")
                + _th("Var $", bg="#1F4E79")
                + _th("Var %", bg="#1F4E79") + "</tr>"]
    for x in cc_yoy[:15]:
        c = _color_var(x["var_pct"], es_costo=True)
        cc_rows.append(
            "<tr>"
            + _td(x["cc"], bg="#FFFFFF", color="#1E293B", weight="500", align="left")
            + _td(_fmt_num(x["ant"]), bg="#FFFFFF", color="#475569")
            + _td(_fmt_num(x["act"]), bg="#FFFFFF", color="#1E293B", weight="600")
            + _td(_fmt_num(-x["var_abs"]), bg="#FFFFFF", color=c, weight="600")
            + _td(_fmt_pct(x["var_pct"]) if x["var_pct"] is not None else "—",
                   bg="#FFFFFF", color=c, weight="700")
            + "</tr>"
        )
    st.markdown(
        '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
        f'{"".join(cc_rows)}</table></div>',
        unsafe_allow_html=True,
    )


# ============================================================
# TAB 5: PROYECCIÓN & PUNTO DE EQUILIBRIO
# ============================================================
def _tab_proyeccion(df_costo: pd.DataFrame, df_venta: pd.DataFrame,
                     year: int, periodo_label: str):
    import numpy as np
    import plotly.graph_objects as go

    st.markdown(
        f"<h3 style='color:#1F4E79;margin:0 0 4px 0;'>"
        f"INTELIGENCIA DE NEGOCIO — Proyección & Equilibrio Operacional</h3>"
        f"<p style='color:#64748B;font-size:12px;margin:0 0 16px 0;'>"
        f"Modelo multivariable (venta + pedidos) · benchmark 3PL fulfillment · "
        f"break-even sobre Margen Contribución</p>",
        unsafe_allow_html=True,
    )

    # ─── DATA PREP ────────────────────────────────────────────────────
    df_hist_costo = (df_costo[(df_costo["escenario"] == "FCST") & (df_costo["kpi"] == "GASTO")]
                       .groupby(["year", "month", "tipo_costo"])["valor"]
                       .sum().reset_index())
    if df_hist_costo.empty or df_venta.empty:
        st.info("Sin data suficiente para proyección")
        return

    df_costo_pivot = df_hist_costo.pivot_table(
        index=["year", "month"], columns="tipo_costo",
        values="valor", aggfunc="sum", fill_value=0,
    ).reset_index()
    if "FIJO" not in df_costo_pivot.columns:
        df_costo_pivot["FIJO"] = 0
    if "VARIABLE" not in df_costo_pivot.columns:
        df_costo_pivot["VARIABLE"] = 0
    df_costo_pivot["TOTAL"] = df_costo_pivot["FIJO"] + df_costo_pivot["VARIABLE"]

    df_merge = df_costo_pivot.merge(
        df_venta[["year", "month", "venta_neta_m", "margen_final_m", "n_pedidos"]],
        on=["year", "month"], how="inner",
    )
    df_merge["fijo_abs"] = df_merge["FIJO"].abs()
    df_merge["var_abs"] = df_merge["VARIABLE"].abs()
    df_merge["total_abs"] = df_merge["TOTAL"].abs()

    mask = (df_merge["venta_neta_m"] > 0) & (df_merge["total_abs"] > 0) & (df_merge["n_pedidos"] > 0)
    df_reg = df_merge[mask].copy()

    if len(df_reg) < 3:
        st.info("Necesito al menos 3 meses con venta + costo + pedidos para construir el modelo.")
        return

    # ─── 1. MODELO REGRESIÓN MULTIVARIABLE ───────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:16px 0 12px 0;font-weight:700;font-size:13px;">'
        '1. MODELO REGRESIÓN — costo en función de venta + pedidos</div>',
        unsafe_allow_html=True,
    )

    venta = df_reg["venta_neta_m"].values
    pedidos = df_reg["n_pedidos"].values
    costo_total = df_reg["total_abs"].values
    costo_var = df_reg["var_abs"].values
    costo_fij = df_reg["fijo_abs"].values

    # Modelo univariable: costo = a*venta + b
    a_uv, b_uv = np.polyfit(venta, costo_total, 1)
    r2_uv = np.corrcoef(venta, costo_total)[0, 1] ** 2

    # Modelo multivariable: costo = a*venta + b*pedidos + c
    # Resolver con least squares (pseudo-inversa numpy)
    X = np.column_stack([venta, pedidos, np.ones(len(venta))])
    try:
        coefs, residuals, rank, sv = np.linalg.lstsq(X, costo_total, rcond=None)
        a_mv, b_mv, c_mv = coefs
        # R² del modelo multivariable
        pred_mv = X @ coefs
        ss_res = np.sum((costo_total - pred_mv) ** 2)
        ss_tot = np.sum((costo_total - costo_total.mean()) ** 2)
        r2_mv = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    except Exception:
        a_mv, b_mv, c_mv, r2_mv = 0, 0, 0, 0

    # Coeficientes para variable y fijo separados
    a_var_uv, b_var_uv = np.polyfit(venta, costo_var, 1)
    a_fij_uv, b_fij_uv = np.polyfit(venta, costo_fij, 1)

    # Promedio histórico de pedidos para conversion costo/pedido
    pedidos_avg = float(pedidos.mean())
    costo_por_pedido = (costo_total.mean() * 1000 / pedidos_avg) if pedidos_avg else 0  # M$ × 1000 = $

    # Métricas del modelo
    col1, col2, col3, col4 = st.columns(4)
    color_r2 = "#16A34A" if r2_mv > 0.7 else "#EA580C" if r2_mv > 0.4 else "#DC2626"
    label_r2 = "Excelente" if r2_mv > 0.8 else "Aceptable" if r2_mv > 0.5 else "Débil"
    col1.metric("R² univariable (solo venta)", f"{r2_uv:.3f}")
    col2.metric("R² MULTIVARIABLE (venta+pedidos)",
                  f"{r2_mv:.3f}", label_r2)
    col3.metric("Costo / Pedido histórico",
                  f"${costo_por_pedido:,.0f}".replace(",", "."),
                  f"{pedidos_avg:,.0f} ped/mes prom".replace(",", "."))
    col4.metric("Costos Variables (% s/Venta)",
                  f"{a_var_uv*100:.2f}%",
                  f"Fijos: ${df_reg['fijo_abs'].mean():,.0f}/mes".replace(",", "."))

    st.caption(
        f"📊 **Modelo multivariable**: Costo ≈ {a_mv*100:.2f}% × Venta + "
        f"${b_mv:,.0f} × Pedidos + ${c_mv:,.0f} fijo".replace(",", ".")
    )

    # Mensaje sobre confiabilidad — coherente
    if r2_mv > 0.7:
        st.success(
            f"✅ **Modelo confiable** (R²={r2_mv:.2f}). Las proyecciones tienen "
            "buena correlación con los datos históricos."
        )
    elif r2_mv > 0.4:
        st.warning(
            f"⚠️ **Modelo aceptable** (R²={r2_mv:.2f}). Sirve para órdenes de "
            "magnitud, pero no para presupuestar al peso. Más data = mejor predicción."
        )
    else:
        st.error(
            f"⚠️ **Modelo débil** (R²={r2_mv:.2f}). Hay drivers ocultos que no "
            "estamos capturando (eventos puntuales, pagos anuales, decisiones "
            "discrecionales). Tomar las proyecciones como referencia, no como verdad. "
            "Recomiendo: cargar más historia mensual + limpiar outliers (ej: "
            "Meikify, honorarios extraordinarios)."
        )

    st.divider()

    # ─── 2. SIMULADOR EVENTOS ───────────────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:16px 0 12px 0;font-weight:700;font-size:13px;">'
        '2. SIMULADOR DE EVENTOS — proyección costo según escenario</div>',
        unsafe_allow_html=True,
    )

    venta_avg = float(venta.mean())
    eventos = {
        "Mes promedio": 0,
        "Cyber Day (May/Oct)": 80,
        "Black Friday (Nov)": 100,
        "Navidad (Dic)": 150,
        "Año Nuevo (Ene)": -30,
        "Marzo (vuelta clases)": 25,
    }

    col_a, col_b = st.columns([1, 2])
    with col_a:
        evento = st.selectbox("Escenario", list(eventos.keys()), key="ev_costo_op")
        delta_v = st.slider("Ajuste fino venta (%)", -50, 200,
                              eventos[evento], step=5, key="ev_costo_op_slider")
        # Asumimos pedidos escalan con venta (ratio promedio mantenido)
        ratio_ped_venta = pedidos_avg / venta_avg if venta_avg else 0
        v_sim = venta_avg * (1 + delta_v / 100)
        ped_sim = ratio_ped_venta * v_sim
        # Predicción multivariable
        c_tot_sim = max(0, a_mv * v_sim + b_mv * ped_sim + c_mv)
        ratio_sim = (c_tot_sim / v_sim * 100) if v_sim > 0 else 0
        cpp_sim = (c_tot_sim * 1000 / ped_sim) if ped_sim else 0

        st.markdown("---")
        st.metric("Venta proyectada", _fmt_num(v_sim),
                   f"{delta_v:+d}% vs promedio")
        st.metric("Pedidos esperados", f"{ped_sim:,.0f}".replace(",", "."))
        st.metric("Costo proyectado total", _fmt_num(c_tot_sim))
        st.metric("Costo / Pedido proyectado",
                   f"${cpp_sim:,.0f}".replace(",", "."),
                   f"{cpp_sim/costo_por_pedido*100-100:+.0f}% vs histórico"
                   if costo_por_pedido else None,
                   delta_color="inverse")
        # Status semáforo vs benchmarks 3PL
        if cpp_sim <= BENCH_COSTO_POR_PEDIDO_BAJO:
            status = f"🟢 Más barato que 3PL (${BENCH_COSTO_POR_PEDIDO_BAJO}+)"
        elif cpp_sim <= BENCH_COSTO_POR_PEDIDO_ALTO:
            status = f"🟡 En rango 3PL (${BENCH_COSTO_POR_PEDIDO_BAJO}-{BENCH_COSTO_POR_PEDIDO_ALTO})"
        else:
            status = f"🔴 Más caro que 3PL premium (>${BENCH_COSTO_POR_PEDIDO_ALTO})"
        st.metric("Ratio Costo/Venta", f"{ratio_sim:.1f}%", status)

    with col_b:
        # Gráfico
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=venta, y=costo_total, mode="markers", name="Meses históricos",
            marker=dict(size=14, color="#1F4E79", opacity=0.7),
            hovertemplate="Venta: %{x:,.0f}<br>Costo: %{y:,.0f}<extra></extra>",
        ))
        # Línea regresión univariable de referencia
        xx = np.linspace(venta.min() * 0.5, venta.max() * 2.5, 50)
        # Para la línea, asumo pedidos escalan
        yy_mv = a_mv * xx + b_mv * (ratio_ped_venta * xx) + c_mv
        yy_mv = np.maximum(0, yy_mv)
        fig.add_trace(go.Scatter(
            x=xx, y=yy_mv, mode="lines",
            name=f"Modelo (R²={r2_mv:.2f})",
            line=dict(color="#DC2626", width=2.5, dash="dash"),
        ))
        fig.add_trace(go.Scatter(
            x=[v_sim], y=[c_tot_sim], mode="markers+text",
            name=f"{evento}",
            marker=dict(size=22, color="#EA580C", symbol="star"),
            text=[f" {ratio_sim:.1f}%"], textposition="top center",
            textfont=dict(size=14, color="#EA580C"),
        ))
        fig.update_layout(
            height=400,
            xaxis=dict(title="Venta neta mensual (M CLP)", tickformat=",.0f"),
            yaxis=dict(title="Costo operativo (M CLP)", tickformat=",.0f"),
            margin=dict(t=20, b=40, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.05, x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ─── 3. BENCHMARK vs OPERADOR 3PL FULFILLMENT ───────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:16px 0 12px 0;font-weight:700;font-size:13px;">'
        '3. BENCHMARK vs OPERADOR 3PL FULFILLMENT (LATAM/CL)</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Comparación contra costo de tercerizar el fulfillment con un operador "
        "3PL profesional (ej: Bsale Fulfillment, Yunigo, Recíbelo Logística, "
        "Adexus 3PL). Incluye storage + pick&pack + handling. EXCLUYE flete a "
        "cliente final (es passthrough en ambos modelos)."
    )

    # Real actual UnionX
    costo_promedio = float(costo_total.mean())
    cpp_real = (costo_promedio * 1000 / pedidos_avg) if pedidos_avg else 0
    ratio_real = (costo_promedio / venta_avg * 100) if venta_avg else 0

    # Tabla comparativa
    bench_rows = [
        "<tr>"
        + _th("Modelo operación", bg="#1F4E79", align="left")
        + _th("Costo / Pedido", bg="#1F4E79")
        + _th("Costo / Venta %", bg="#1F4E79")
        + _th("Ventajas", bg="#1F4E79", align="left")
        + _th("Desventajas", bg="#1F4E79", align="left")
        + "</tr>"
    ]

    def _row(modelo, cpp, pct, vent, desv, color, highlight=False):
        bg = "#FEF3C7" if highlight else "#FFFFFF"
        return ("<tr>"
                + _td(modelo, bg=bg, color=color, weight="700", align="left")
                + _td(f"${cpp:,.0f}".replace(",", "."), bg=bg, color=color, weight="600")
                + _td(f"{pct:.1f}%", bg=bg, color=color, weight="600")
                + _td(vent, bg=bg, color="#475569", align="left", padding="6px 10px")
                + _td(desv, bg=bg, color="#475569", align="left", padding="6px 10px")
                + "</tr>")

    bench_rows.append(_row(
        "🏠 In-house OPTIMIZADO",
        950, 7.5,
        "Control total · margen alto · datos en vivo",
        "Inversión inicial · know-how requerido",
        "#16A34A",
    ))
    bench_rows.append(_row(
        f"📍 UnionX HOY",
        cpp_real, ratio_real,
        "Es lo que tenés ahora",
        "Comparar con benchmarks ↑↓",
        "#1F4E79", highlight=True,
    ))
    bench_rows.append(_row(
        "🚚 3PL Standard (Bsale, Yunigo)",
        2200, 13.0,
        "Sin CAPEX · escalable · SLA básico",
        "Margen menor · dependencia 3PL · API limitada",
        "#EA580C",
    ))
    bench_rows.append(_row(
        "🌟 3PL Premium (Recíbelo, Adexus)",
        3000, 16.5,
        "SLA fuerte · integraciones · soporte 24/7",
        "Más caro · contratos largos · menos flexibilidad",
        "#DC2626",
    ))

    st.markdown(
        '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
        f'{"".join(bench_rows)}</table></div>',
        unsafe_allow_html=True,
    )

    # Diagnóstico vs benchmark
    st.markdown("<br>", unsafe_allow_html=True)
    if cpp_real <= BENCH_COSTO_POR_PEDIDO_BAJO:
        st.success(
            f"✅ **UnionX ${cpp_real:,.0f}/pedido está MÁS BARATO que el "
            f"3PL standard (${BENCH_COSTO_POR_PEDIDO_BAJO}+)**. Tu operación in-house "
            f"es competitiva y eficiente. Ahorro estimado vs 3PL: "
            f"${(BENCH_COSTO_POR_PEDIDO_BAJO - cpp_real) * pedidos_avg / 1000:,.0f} M/mes.".replace(",", ".")
        )
    elif cpp_real <= BENCH_COSTO_POR_PEDIDO_ALTO:
        st.warning(
            f"🟡 **UnionX ${cpp_real:,.0f}/pedido está EN RANGO 3PL** "
            f"(${BENCH_COSTO_POR_PEDIDO_BAJO}-${BENCH_COSTO_POR_PEDIDO_ALTO}). "
            "Tu operación es comparable a outsourcear, pero retenés control. "
            "Hay espacio para optimizar y bajar al rango in-house (<$1.500)."
        )
    else:
        st.error(
            f"🔴 **UnionX ${cpp_real:,.0f}/pedido está MÁS CARO que un 3PL premium** "
            f"(>${BENCH_COSTO_POR_PEDIDO_ALTO}). Vale evaluar tercerizar al menos "
            "parcialmente (ej: long-tail SKUs B2C). Sobrecosto vs 3PL standard: "
            f"~${(cpp_real - BENCH_COSTO_POR_PEDIDO_BAJO) * pedidos_avg / 1000:,.0f} M/mes.".replace(",", ".")
        )

    st.divider()

    # ─── 4. PUNTO DE EQUILIBRIO (sobre Margen Contribución) ─────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:16px 0 12px 0;font-weight:700;font-size:13px;">'
        '4. PUNTO DE EQUILIBRIO OPERACIONAL — sobre Margen Contribución</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "**Fórmula correcta:** Venta break-even = Costos Fijos Operativos ÷ "
        "Margen Contribución %. El Margen Contribución viene del módulo Ventas "
        "(venta − COGS − comisiones canal − logística − marketing) y representa "
        "lo que queda de cada peso vendido para pagar la operación."
    )

    # Costos fijos operativos = promedio mensual de costos FIJOS del Sheet
    cf_mensual = float(df_reg["fijo_abs"].mean())
    # Margen Contribución desde módulo Ventas
    margen_avg = float(df_reg["margen_final_m"].mean())
    venta_avg_real = float(df_reg["venta_neta_m"].mean())
    mc_pct = (margen_avg / venta_avg_real) if venta_avg_real else 0
    # Break-even venta (sobre MC)
    breakeven_venta = (cf_mensual / mc_pct) if mc_pct > 0 else None
    # Holgura
    holgura_venta = (venta_avg_real - breakeven_venta) if breakeven_venta else None
    holgura_pct = (holgura_venta / breakeven_venta * 100) if breakeven_venta else None

    be_cols = st.columns(4)
    be_cols[0].metric("Costo Fijo Operativo mensual",
                        _fmt_num(cf_mensual),
                        "promedio histórico (Sheet)")
    be_cols[1].metric("Margen Contribución %",
                        f"{mc_pct*100:.1f}%",
                        f"${margen_avg:,.0f} / ${venta_avg_real:,.0f}".replace(",", "."))
    be_cols[2].metric("VENTA BREAK-EVEN",
                        _fmt_num(breakeven_venta) if breakeven_venta else "—",
                        f"= Fijos ${cf_mensual:,.0f} / MC {mc_pct*100:.1f}%".replace(",", "."))
    be_cols[3].metric("Holgura vs venta promedio",
                        f"{holgura_pct:+.1f}%" if holgura_pct is not None else "—",
                        f"${holgura_venta:,.0f} M sobre BE".replace(",", "")
                        if holgura_venta is not None else None)

    if breakeven_venta and venta_avg_real:
        if venta_avg_real >= breakeven_venta:
            st.success(
                f"✅ **Operación rentable**: vendés ${venta_avg_real:,.0f} M/mes "
                f"vs break-even de ${breakeven_venta:,.0f} M ({holgura_pct:+.0f}% de holgura). "
                f"Cada $1 vendido por encima del break-even contribuye "
                f"${mc_pct:.2f} a utilidad operativa.".replace(",", ".")
            )
        else:
            st.error(
                f"🔴 **Operación bajo break-even**: vendés ${venta_avg_real:,.0f} M/mes "
                f"vs los ${breakeven_venta:,.0f} M necesarios. "
                f"Te faltan ${breakeven_venta - venta_avg_real:,.0f} M/mes "
                f"para cubrir tus costos fijos.".replace(",", ".")
            )

    # Ejemplo numérico explicativo
    st.markdown(
        f'<div style="background:#F1F5F9;border-radius:6px;padding:12px 16px;'
        f'margin-top:12px;font-size:12px;color:#475569;">'
        f'<b>📐 Ejemplo:</b> Si vendés $300 M con margen contribución {mc_pct*100:.1f}%, '
        f'te quedan ${300*mc_pct:.0f} M para pagar la operación. '
        f'Tus fijos son ${cf_mensual:,.0f} M, así que {"sí cubrís" if 300*mc_pct >= cf_mensual else "NO cubrís"} '
        f'los fijos con esa venta.'
        f'</div>'.replace(",", "."),
        unsafe_allow_html=True,
    )

    st.divider()

    # ─── 5. ACCIONES SUGERIDAS ──────────────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:16px 0 12px 0;font-weight:700;font-size:13px;">'
        '5. ACCIONES SUGERIDAS — coherentes con el escenario</div>',
        unsafe_allow_html=True,
    )

    # Calcular % fijo de la operación (qué tan rígida es)
    pct_fijo_operacion = (cf_mensual / costo_promedio * 100) if costo_promedio else 0

    acciones = []

    # 1. Diagnóstico estructura
    if pct_fijo_operacion > 60:
        acciones.append({
            "color": "#7C3AED", "tipo": "🔵 ESTRUCTURA",
            "txt": f"Tu operación tiene **{pct_fijo_operacion:.0f}% fijo** — "
                    "estructura muy rígida. Bueno cuando vendés mucho (los fijos se "
                    "diluyen), peligroso cuando cae la venta. **Apalancamiento operativo alto.**",
        })
    elif pct_fijo_operacion < 40:
        acciones.append({
            "color": "#16A34A", "tipo": "🟢 ESTRUCTURA",
            "txt": f"Estructura {pct_fijo_operacion:.0f}% fijo — flexible, "
                    "tu costo se ajusta al volumen. Buena resiliencia ante caídas de venta.",
        })

    # 2. Diagnóstico vs benchmark 3PL
    if cpp_real > BENCH_COSTO_POR_PEDIDO_ALTO:
        acciones.append({
            "color": "#DC2626", "tipo": "🔴 EFICIENCIA",
            "txt": f"Tu costo por pedido (${cpp_real:,.0f}) supera al de un 3PL premium. "
                    "Evaluar tercerizar el fulfillment de SKUs long-tail B2C, "
                    "renegociar arriendos, automatizar picking.".replace(",", "."),
        })

    # 3. Escenario simulado
    if delta_v > 100 and pct_fijo_operacion > 50:
        acciones.append({
            "color": "#EA580C", "tipo": "🟠 PREPARAR EVENTO",
            "txt": f"Venta proyectada +{delta_v}%: tus fijos se DILUYEN "
                    f"({cf_mensual/v_sim*100:.1f}% del nuevo total). Aprovechar el evento "
                    "para correr a máxima utilización de la infraestructura ya pagada.",
        })
    if delta_v < -25:
        acciones.append({
            "color": "#7C3AED", "tipo": "🔵 ESCENARIO BAJA",
            "txt": f"Caída venta {delta_v}% deja la operación con "
                    f"{cf_mensual/v_sim*100:.1f}% fijos sobre venta. "
                    "Activar plan: reducir turnos extras, sub-arrendar zonas ociosas, "
                    "renegociar contratos largos con cláusula variable.",
        })

    # 4. Modelo confiabilidad
    if r2_mv < 0.5:
        acciones.append({
            "color": "#94A3B8", "tipo": "📊 MODELO",
            "txt": f"R² del modelo ({r2_mv:.2f}) es bajo — los costos no se explican "
                    "bien solo por venta+pedidos. Revisar outliers (ej: pagos anuales "
                    "Meikify, honorarios extraordinarios) y cargar más historia para "
                    "robustecer la predicción.",
        })

    if not acciones:
        acciones.append({
            "color": "#16A34A", "tipo": "🟢 OK",
            "txt": "Sin alertas. Mantener monitoreo mensual.",
        })

    for a in acciones:
        st.markdown(
            f'<div style="background:#FFFFFF;border-left:4px solid {a["color"]};'
            f'padding:10px 14px;margin:6px 0;border-radius:4px;font-size:13px;">'
            f'<b style="color:{a["color"]};">{a["tipo"]}</b><br>{a["txt"]}'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Nota final sobre próximo paso
    st.markdown(
        '<div style="background:#E3F2FD;border-left:4px solid #1F4E79;'
        'padding:12px 16px;margin-top:20px;border-radius:4px;font-size:12px;color:#1E293B;">'
        '<b>🎯 Próximo paso (app Finanzas):</b> con el costo operativo bien medido, '
        'crear P&L por línea de negocio asignando los costos según una política '
        '(ej: % pedidos por LN, % unidades, driver manual). Esto cierra el loop '
        'de rentabilidad real por canal/línea.'
        '</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# RENDER
# ============================================================
def render():
    with st.sidebar:
        st.markdown("### 💰 **Costo Operativo**")
        st.caption("P&L · Detalle CC · Informe Gestión")
        st.divider()

    st.title("💰 Costo Operativo Total — Operaciones")

    df_costo, res = _cargar()
    df_venta = _cargar_ventas_mensual()

    if df_costo.empty:
        st.warning("⏳ Sin datos. Correr `python extract_ops_costo_operativo.py`")
        return

    st.caption(
        f"🕒 Costos: {res.get('generado_en','')[:19]} · "
        f"Costos: Sheet OPERACIONES (Drive) · Venta: módulo Ventas (parquet)"
    )
    st.divider()

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        years = sorted(df_costo["year"].dropna().unique().astype(int).tolist())
        year_sel = st.selectbox("Año", years, index=len(years) - 1 if years else 0)
    with col2:
        modo = st.selectbox("Período", ["Q1", "Q2", "Q3", "Q4", "YTD", "Mes específico"])
    meses_disp = sorted(df_costo[df_costo["year"] == year_sel]["month"]
                          .dropna().unique().astype(int).tolist())
    if modo == "Q1":
        meses_sel, periodo_label = [1, 2, 3], "Q1"
    elif modo == "Q2":
        meses_sel, periodo_label = [4, 5, 6], "Q2"
    elif modo == "Q3":
        meses_sel, periodo_label = [7, 8, 9], "Q3"
    elif modo == "Q4":
        meses_sel, periodo_label = [10, 11, 12], "Q4"
    elif modo == "YTD":
        meses_sel = sorted(meses_disp)
        periodo_label = "YTD"
    else:
        with col3:
            mes_unico = st.selectbox("Mes", meses_disp,
                                       format_func=lambda m: MESES_ES.get(m, str(m)))
        meses_sel = [mes_unico]
        periodo_label = MESES_ES.get(mes_unico, str(mes_unico))[:3].title()
    meses_sel = [m for m in meses_sel if m in meses_disp]

    with col3:
        if modo != "Mes específico":
            st.caption(f"📅 **{periodo_label} {year_sel}** · Meses: "
                        f"{', '.join(MESES_SHORT.get(m, str(m)) for m in meses_sel)}")

    st.divider()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 P&L Operaciones",
        "🔎 Detalle por Centro de Costo",
        "📋 Informe de Gestión",
        "📈 Comparativo YoY",
        "🔮 Proyección & Equilibrio",
    ])
    with tab1:
        _tab_pnl(df_costo, df_venta, year_sel, meses_sel, periodo_label)
    with tab2:
        _tab_detalle_cc(df_costo, df_venta, year_sel, meses_sel, periodo_label)
    with tab3:
        _tab_informe(df_costo, df_venta, year_sel, meses_sel, periodo_label)
    with tab4:
        _tab_yoy(df_costo, df_venta, year_sel, meses_sel, periodo_label)
    with tab5:
        _tab_proyeccion(df_costo, df_venta, year_sel, periodo_label)
