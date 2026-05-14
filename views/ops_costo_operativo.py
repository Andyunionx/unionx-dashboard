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
# BENCHMARKS — Operadores fulfillment 3PL en Chile (2024-2025)
# ============================================================
# IMPORTANTE: estos son operadores que ofrecen FULFILLMENT (storage +
# pick&pack + handling + shipping label), NO couriers de última milla
# (Blue Express, Recíbelo, Starken, Chilexpress hacen solo flete final).
#
# Operadores fulfillment 3PL en CL:
#   - Bsale Fulfillment: storage + p&p; ~$1.500-2.500/pedido
#   - Mercado Libre Full (FBM): tarifa MELI; ~$1.800-3.000/pedido B2C
#   - Storage Online / boutique 3PL: $1.200-2.500/pedido
#   - Adexus Supply Chain: B2B premium con SLA; $2.500-4.000/pedido
#   - DHL Supply Chain CL: premium internacional; $3.500-5.500/pedido
#
# Estos rangos NO incluyen flete a cliente final (passthrough vía courier).
# Sí incluyen: storage, pick, pack, label, handling, IT.
#
# OBJETIVO REAL DEPENDE DEL AOV (Ticket Promedio):
#   AOV < $20K   → costo/pedido objetivo $800-1500 (>10% se vuelve caro)
#   AOV $20-50K  → costo/pedido objetivo $1500-2500 (5-10% es óptimo)
#   AOV $50-100K → costo/pedido objetivo $2000-3500 (3-5% es óptimo)
#   AOV >$100K   → costo/pedido objetivo $3000-5000 (1-3% es óptimo)
BENCHMARKS_3PL_CL = [
    {
        "modelo": "🏠 In-house OPTIMIZADO (target)",
        "cpp_low": 800, "cpp_high": 1500,
        "tipo": "Operación propia bien automatizada",
        "ventajas": "Control total · margen alto · datos en vivo · sin contrato",
        "desventajas": "CAPEX inicial · know-how · escala mínima",
    },
    {
        "modelo": "🏪 Bsale Fulfillment / Storage Online",
        "cpp_low": 1500, "cpp_high": 2500,
        "tipo": "3PL standard volumen B2C",
        "ventajas": "Sin CAPEX · escalable · API básica · contrato flexible",
        "desventajas": "Margen menor · dependencia 3PL · SLA limitado",
    },
    {
        "modelo": "🛒 Mercado Libre Full (FBM)",
        "cpp_low": 1800, "cpp_high": 3000,
        "tipo": "Fulfillment integrado al canal MELI",
        "ventajas": "Boost MELI · entrega rápida · stockeo MELI",
        "desventajas": "Solo MELI · stock comprometido · tarifa por SKU",
    },
    {
        "modelo": "🏢 Adexus Supply Chain",
        "cpp_low": 2500, "cpp_high": 4000,
        "tipo": "3PL premium B2B con SLA",
        "ventajas": "SLA fuerte · ERP · soporte 24/7 · trazabilidad",
        "desventajas": "Más caro · contratos largos · menos flexibilidad",
    },
    {
        "modelo": "🌐 DHL Supply Chain Chile",
        "cpp_low": 3500, "cpp_high": 5500,
        "tipo": "Premium internacional",
        "ventajas": "Best-in-class · global · valor agregado",
        "desventajas": "Caro · setup lento · solo gran volumen",
    },
]
BENCH_CPP_OPTIMO = 1500       # ≤ → in-house optimizado
BENCH_CPP_RANGO_3PL = 3000    # entre BENCH_CPP_OPTIMO y este = 3PL standard
BENCH_CPP_PREMIUM = 4500      # > este = caro vs 3PL premium


def _objetivo_por_aov(aov_clp: float) -> dict:
    """Devuelve banda objetivo de costo/pedido según AOV de la operación."""
    if aov_clp < 20_000:
        return {"cpp_min": 800, "cpp_max": 1500, "pct_min": 5, "pct_max": 10,
                 "categoria": "AOV bajo (B2C marketplace)"}
    if aov_clp < 50_000:
        return {"cpp_min": 1500, "cpp_max": 2500, "pct_min": 5, "pct_max": 10,
                 "categoria": "AOV medio-bajo (B2C masivo)"}
    if aov_clp < 100_000:
        return {"cpp_min": 2000, "cpp_max": 3500, "pct_min": 3, "pct_max": 5,
                 "categoria": "AOV medio (B2C premium / B2B chico)"}
    return {"cpp_min": 3000, "cpp_max": 5000, "pct_min": 1, "pct_max": 3,
             "categoria": "AOV alto (B2B / cuentas grandes)"}


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
            n_lineas=("sku", "count"),
            n_unidades=("cantidad", "sum"),
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


def _kpi_html(label: str, valor: str, meta: str = "", color: str = "#1F4E79") -> str:
    """Card HTML estilo KPI con borde de color."""
    return (
        f'<div style="background:white;border-radius:12px;padding:16px 18px;'
        f'border:1px solid #E2E8F0;border-left:4px solid {color};'
        f'box-shadow:0 1px 3px rgba(0,0,0,0.05);height:100%;">'
        f'<div style="font-size:0.72rem;color:#64748B;text-transform:uppercase;'
        f'letter-spacing:0.5px;font-weight:600;margin-bottom:6px;">{label}</div>'
        f'<div style="font-size:1.5rem;font-weight:700;color:#1E293B;'
        f'line-height:1.1;">{valor}</div>'
        f'<div style="font-size:0.72rem;color:#64748B;margin-top:8px;'
        f'padding-top:8px;border-top:1px solid #F1F5F9;">{meta}</div></div>'
    )


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
        f"Multivariable (venta + pedidos + unidades) · benchmark fulfillment 3PL · "
        f"break-even sobre Margen Contribución · cuándo escalar fijos</p>",
        unsafe_allow_html=True,
    )

    # ─── DATA PREP ────────────────────────────────────────────────
    df_hist = (df_costo[(df_costo["escenario"] == "FCST") & (df_costo["kpi"] == "GASTO")]
                 .groupby(["year", "month", "tipo_costo"])["valor"]
                 .sum().reset_index())
    if df_hist.empty or df_venta.empty:
        st.info("Sin data suficiente")
        return

    pivot = df_hist.pivot_table(index=["year", "month"], columns="tipo_costo",
                                  values="valor", aggfunc="sum", fill_value=0).reset_index()
    if "FIJO" not in pivot.columns:
        pivot["FIJO"] = 0
    if "VARIABLE" not in pivot.columns:
        pivot["VARIABLE"] = 0
    pivot["TOTAL"] = pivot["FIJO"] + pivot["VARIABLE"]

    df_merge = pivot.merge(
        df_venta[["year", "month", "venta_neta_m", "margen_final_m",
                    "n_pedidos", "n_lineas", "n_unidades", "venta_neta"]],
        on=["year", "month"], how="inner",
    )
    df_merge["fijo_abs"] = df_merge["FIJO"].abs()
    df_merge["var_abs"] = df_merge["VARIABLE"].abs()
    df_merge["total_abs"] = df_merge["TOTAL"].abs()

    mask = ((df_merge["venta_neta_m"] > 0) & (df_merge["total_abs"] > 0)
             & (df_merge["n_pedidos"] > 0))
    df_reg = df_merge[mask].copy()
    if len(df_reg) < 3:
        st.info("Necesito al menos 3 meses con venta + pedidos + costo.")
        return

    venta = df_reg["venta_neta_m"].values
    pedidos = df_reg["n_pedidos"].values
    unidades = df_reg["n_unidades"].values
    costo_t = df_reg["total_abs"].values
    costo_v = df_reg["var_abs"].values
    costo_f = df_reg["fijo_abs"].values

    # AOV de la operación (ticket promedio)
    venta_neta_total_clp = float(df_reg["venta_neta"].sum())
    pedidos_total = float(pedidos.sum())
    aov = venta_neta_total_clp / pedidos_total if pedidos_total else 0
    objetivo = _objetivo_por_aov(aov)

    # ─── 0. CONTEXTO + AOV ────────────────────────────────────────
    st.markdown(
        '<div style="background:#0D3A5F;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:12px 0;font-weight:700;font-size:13px;">'
        '0. CONTEXTO DE TU OPERACIÓN — qué objetivo apuntar</div>',
        unsafe_allow_html=True,
    )
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("AOV (Ticket Promedio)", f"${aov:,.0f}".replace(",", "."),
                 objetivo["categoria"])
    cc2.metric("Costo / Pedido OBJETIVO",
                 f"${objetivo['cpp_min']:,.0f} - ${objetivo['cpp_max']:,.0f}".replace(",", "."),
                 "según AOV de tu operación")
    cc3.metric("Costo / Venta OBJETIVO",
                 f"{objetivo['pct_min']}% - {objetivo['pct_max']}%",
                 "ratio óptimo vs tu AOV")
    st.caption(
        "💡 **Importante:** los benchmarks NO son absolutos. Lo correcto depende de "
        "tu AOV (ticket promedio). Una operación con AOV $5K NO puede tener mismo "
        "costo/pedido que una con AOV $500K. Acá el objetivo está calculado para tu AOV."
    )

    st.divider()

    # ─── 1. MODELO MULTIVARIABLE ─────────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:12px 0;font-weight:700;font-size:13px;">'
        '1. MODELO MULTIVARIABLE — costo en función de venta + pedidos + unidades</div>',
        unsafe_allow_html=True,
    )

    def _r2_lstsq(X_arr, y_arr):
        try:
            coefs, _, _, _ = np.linalg.lstsq(X_arr, y_arr, rcond=None)
            pred = X_arr @ coefs
            ss_res = np.sum((y_arr - pred) ** 2)
            ss_tot = np.sum((y_arr - y_arr.mean()) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            return coefs, max(0, min(1, r2))
        except Exception:
            return None, 0

    # Modelos: cada combinación
    ones = np.ones(len(venta))
    modelos = {
        "Solo Venta": (np.column_stack([venta, ones]), costo_t,
                         ["venta", "fijo"]),
        "Solo Pedidos": (np.column_stack([pedidos, ones]), costo_t,
                            ["pedidos", "fijo"]),
        "Solo Unidades": (np.column_stack([unidades, ones]), costo_t,
                            ["unidades", "fijo"]),
        "Venta + Pedidos": (np.column_stack([venta, pedidos, ones]), costo_t,
                              ["venta", "pedidos", "fijo"]),
        "Multivariable (V+P+U)": (np.column_stack([venta, pedidos, unidades, ones]),
                                     costo_t, ["venta", "pedidos", "unidades", "fijo"]),
    }
    resultados = {}
    for nombre, (X_, y_, names) in modelos.items():
        coefs, r2 = _r2_lstsq(X_, y_)
        resultados[nombre] = {"coefs": coefs, "r2": r2, "names": names}

    # Tabla de R² comparativo
    r2_rows = ["<tr>" + _th("Modelo", bg="#1F4E79", align="left")
                + _th("R²", bg="#1F4E79")
                + _th("Calidad", bg="#1F4E79", align="left") + "</tr>"]
    for nombre, info in resultados.items():
        r2 = info["r2"]
        if r2 > 0.7:
            cal, color = "✅ Confiable", "#16A34A"
        elif r2 > 0.4:
            cal, color = "🟡 Aceptable", "#EA580C"
        else:
            cal, color = "🔴 Débil", "#DC2626"
        r2_rows.append("<tr>"
                        + _td(nombre, bg="#FFFFFF", color="#1E293B",
                               weight="600", align="left")
                        + _td(f"{r2:.3f}", bg="#FFFFFF", color=color, weight="700")
                        + _td(cal, bg="#FFFFFF", color=color, align="left",
                               padding="6px 10px")
                        + "</tr>")
    cM, cR = st.columns([2, 1])
    with cM:
        st.markdown(
            '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
            '<table style="border-collapse:collapse;width:100%;font-family:'
            '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
            f'{"".join(r2_rows)}</table></div>',
            unsafe_allow_html=True,
        )
    with cR:
        st.markdown(
            '<div style="background:#FFF8E1;border-left:4px solid #F59E0B;'
            'padding:10px 14px;border-radius:4px;font-size:12px;color:#1E293B;">'
            "<b>📚 ¿Qué es R²?</b><br>"
            "Mide qué % del movimiento del costo se explica por las variables "
            "del modelo. R²=1 significa predicción perfecta. R²=0 significa "
            "que la variable no explica nada.<br><br>"
            "Un R² alto en el modelo Multivariable te dice que sí podemos "
            "proyectar el costo a partir de venta+pedidos+unidades. "
            "Un R² bajo indica drivers ocultos (eventos puntuales, decisiones "
            "discrecionales)."
            "</div>",
            unsafe_allow_html=True,
        )

    # Mejor modelo
    mejor = max(resultados.items(), key=lambda kv: kv[1]["r2"])
    nombre_mejor, info_mejor = mejor
    st.caption(f"🏆 Mejor modelo: **{nombre_mejor}** (R²={info_mejor['r2']:.3f})")

    # ─── ANÁLISIS FIJO vs VARIABLE por driver ────────────────────
    st.markdown(
        "<h4 style='color:#1F4E79;margin:18px 0 8px 0;'>📊 Correlación: ¿qué driver explica mejor cada tipo de costo?</h4>",
        unsafe_allow_html=True,
    )

    drivers = {"Venta": venta, "Pedidos": pedidos, "Unidades": unidades}
    fv_rows = ["<tr>" + _th("Tipo Costo", bg="#1F4E79", align="left")]
    for d in drivers:
        fv_rows[0] += _th(f"R² vs {d}", bg="#1F4E79")
    fv_rows[0] += _th("Mejor driver", bg="#1F4E79") + "</tr>"

    for tipo, costos in [("VARIABLE", costo_v), ("FIJO", costo_f), ("TOTAL", costo_t)]:
        row_cells = [_td(tipo, bg="#FFFFFF", color="#1E293B",
                          weight="700", align="left")]
        r2_d = {}
        for d_name, d_vals in drivers.items():
            try:
                r2 = np.corrcoef(d_vals, costos)[0, 1] ** 2
            except Exception:
                r2 = 0
            r2_d[d_name] = r2
            color = ("#16A34A" if r2 > 0.7 else "#EA580C" if r2 > 0.4 else "#DC2626")
            row_cells.append(_td(f"{r2:.3f}", bg="#FFFFFF",
                                   color=color, weight="700"))
        mejor_driver = max(r2_d, key=r2_d.get)
        row_cells.append(_td(mejor_driver, bg="#FEF3C7", color="#1E293B",
                              weight="700"))
        fv_rows.append("<tr>" + "".join(row_cells) + "</tr>")

    st.markdown(
        '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
        f'{"".join(fv_rows)}</table></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "💡 **Lo esperado:** Costos VARIABLES deben correlacionar fuerte con Pedidos o Unidades "
        "(comisiones, insumos, transporte por bulto). Costos FIJOS deberían NO correlacionar "
        "con nada (arriendo, sueldos planta). Si los fijos correlacionan, no son tan fijos."
    )

    st.divider()

    # ─── 2. KPIs UNITARIOS ────────────────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:12px 0;font-weight:700;font-size:13px;">'
        '2. KPIs UNITARIOS DE COSTO — promedios históricos</div>',
        unsafe_allow_html=True,
    )

    costo_total_clp = costo_t.mean() * 1000  # M$ → $
    pedidos_avg = pedidos.mean()
    unidades_avg = unidades.mean()
    lineas_avg = df_reg["n_lineas"].mean()

    cpp = costo_total_clp / pedidos_avg if pedidos_avg else 0
    cpu = costo_total_clp / unidades_avg if unidades_avg else 0
    cpl = costo_total_clp / lineas_avg if lineas_avg else 0

    # vs objetivo según AOV
    cpp_color = ("#16A34A" if cpp <= objetivo["cpp_max"]
                  else "#EA580C" if cpp <= objetivo["cpp_max"] * 1.3 else "#DC2626")
    cpp_status = ("🟢 Dentro objetivo" if cpp <= objetivo["cpp_max"]
                    else "🟡 Sobre objetivo" if cpp <= objetivo["cpp_max"] * 1.3
                    else "🔴 Muy sobre objetivo")

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_kpi_html(
        "Costo / PEDIDO",
        f"${cpp:,.0f}".replace(",", "."),
        f"Objetivo: ${objetivo['cpp_min']:,}-{objetivo['cpp_max']:,}<br>".replace(",", ".")
        + f"<b style='color:{cpp_color};'>{cpp_status}</b>",
        cpp_color,
    ), unsafe_allow_html=True)
    k2.markdown(_kpi_html(
        "Costo / UNIDAD movida",
        f"${cpu:,.0f}".replace(",", "."),
        f"Promedio: {unidades_avg:,.0f} unid/mes<br>".replace(",", ".")
        + f"Implica {unidades_avg/pedidos_avg:.1f} unid/pedido prom",
        "#7C3AED",
    ), unsafe_allow_html=True)
    k3.markdown(_kpi_html(
        "Costo / LÍNEA pickeada",
        f"${cpl:,.0f}".replace(",", "."),
        f"Promedio: {lineas_avg:,.0f} líneas/mes<br>".replace(",", ".")
        + f"Productividad picking",
        "#0EA5E9",
    ), unsafe_allow_html=True)
    k4.markdown(_kpi_html(
        "AOV (Ticket Promedio)",
        f"${aov:,.0f}".replace(",", "."),
        f"Para evaluar si CPP es alto/bajo<br>vs valor del pedido",
        "#1F4E79",
    ), unsafe_allow_html=True)

    st.caption(
        f"📐 **Cálculos:** Costo/Pedido = costo total mensual / # pedidos · "
        f"Costo/Unidad = costo total / # unidades despachadas · "
        f"Costo/Línea = costo total / # líneas pickeadas. "
        f"Todos calculados sobre el promedio de {len(df_reg)} meses con data."
    )

    st.divider()

    # ─── 3. SIMULADOR EVENTOS ────────────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:12px 0;font-weight:700;font-size:13px;">'
        '3. SIMULADOR DE EVENTOS</div>',
        unsafe_allow_html=True,
    )

    venta_avg = float(venta.mean())
    eventos = {
        "Mes promedio": 0, "Cyber Day": 80, "Black Friday": 100,
        "Navidad": 150, "Año Nuevo (caída)": -30, "Marzo": 25,
    }
    cA, cB = st.columns([1, 2])
    with cA:
        evento = st.selectbox("Escenario", list(eventos.keys()), key="ev_op")
        delta_v = st.slider("Ajuste fino venta (%)", -50, 200,
                              eventos[evento], step=5, key="ev_op_slider")
        # Asumimos pedidos y unidades escalan proporcionalmente con venta
        ratio_ped = pedidos_avg / venta_avg if venta_avg else 0
        ratio_uni = unidades_avg / venta_avg if venta_avg else 0
        v_sim = venta_avg * (1 + delta_v / 100)
        ped_sim = ratio_ped * v_sim
        uni_sim = ratio_uni * v_sim

        # Aplicar mejor modelo
        coefs_best = info_mejor["coefs"]
        names_best = info_mejor["names"]
        # Construir vector con las variables del mejor modelo
        var_map = {"venta": v_sim, "pedidos": ped_sim, "unidades": uni_sim, "fijo": 1}
        c_tot_sim = max(0, sum(coefs_best[i] * var_map[n] for i, n in enumerate(names_best)))
        ratio_sim = (c_tot_sim / v_sim * 100) if v_sim > 0 else 0
        cpp_sim = (c_tot_sim * 1000 / ped_sim) if ped_sim else 0

        st.markdown("---")
        st.metric("Venta proyectada", _fmt_num(v_sim), f"{delta_v:+d}% vs prom")
        st.metric("Pedidos esperados", f"{ped_sim:,.0f}".replace(",", "."))
        st.metric("Costo proyectado total", _fmt_num(c_tot_sim))
        st.metric("Costo / Pedido proyectado",
                   f"${cpp_sim:,.0f}".replace(",", "."),
                   f"{cpp_sim/cpp*100-100:+.0f}% vs histórico" if cpp else None,
                   delta_color="inverse")
        st.metric("Ratio Costo / Venta", f"{ratio_sim:.1f}%")

    with cB:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=venta, y=costo_t, mode="markers",
                                    name="Histórico", marker=dict(size=14, color="#1F4E79")))
        # Línea: aplicar modelo a rango de venta
        xx = np.linspace(venta.min() * 0.5, venta.max() * 2.5, 50)
        yy = np.array([
            max(0, sum(coefs_best[i] * (
                {"venta": x, "pedidos": ratio_ped * x,
                 "unidades": ratio_uni * x, "fijo": 1}[n]
            ) for i, n in enumerate(names_best)))
            for x in xx
        ])
        fig.add_trace(go.Scatter(x=xx, y=yy, mode="lines",
                                    name=f"{nombre_mejor} (R²={info_mejor['r2']:.2f})",
                                    line=dict(color="#DC2626", width=2.5, dash="dash")))
        fig.add_trace(go.Scatter(x=[v_sim], y=[c_tot_sim], mode="markers+text",
                                    name=evento,
                                    marker=dict(size=22, color="#EA580C", symbol="star"),
                                    text=[f" {ratio_sim:.1f}%"], textposition="top center"))
        fig.update_layout(
            height=400,
            xaxis=dict(title="Venta neta (M CLP)", tickformat=",.0f"),
            yaxis=dict(title="Costo operativo (M CLP)", tickformat=",.0f"),
            margin=dict(t=20, b=40, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.05, x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ─── 4. BENCHMARK 3PL FULFILLMENT ────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:12px 0;font-weight:700;font-size:13px;">'
        '4. BENCHMARK vs OPERADORES FULFILLMENT 3PL CL (no couriers)</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Comparación contra operadores que ofrecen **fulfillment** completo "
        "(storage + pick&pack + handling), NO couriers de última milla "
        "(Blue Express, Recíbelo, Starken, Chilexpress hacen solo flete final). "
        "Excluye flete a cliente final (passthrough en ambos modelos)."
    )

    bench_rows = ["<tr>"
                   + _th("Modelo", bg="#1F4E79", align="left")
                   + _th("Costo / Pedido", bg="#1F4E79")
                   + _th("Tipo", bg="#1F4E79", align="left")
                   + _th("Ventajas", bg="#1F4E79", align="left")
                   + _th("Desventajas", bg="#1F4E79", align="left")
                   + "</tr>"]
    # Insertar UnionX en posición correcta
    inserted = False
    for b in BENCHMARKS_3PL_CL:
        # Ver si hay que insertar UnionX antes
        if not inserted and cpp <= b["cpp_high"]:
            bench_rows.append("<tr>"
                + _td("📍 UnionX HOY", bg="#FEF3C7", color="#1F4E79", weight="700", align="left")
                + _td(f"${cpp:,.0f}".replace(",", "."), bg="#FEF3C7",
                       color="#1F4E79", weight="700")
                + _td("Tu operación actual", bg="#FEF3C7", color="#475569", align="left", padding="6px 10px")
                + _td(f"AOV ${aov:,.0f} → objetivo ${objetivo['cpp_min']}-{objetivo['cpp_max']}".replace(",", "."), bg="#FEF3C7", color="#475569", align="left", padding="6px 10px")
                + _td("(highlighted)", bg="#FEF3C7", color="#475569", align="left", padding="6px 10px")
                + "</tr>")
            inserted = True
        bench_rows.append("<tr>"
            + _td(b["modelo"], bg="#FFFFFF", color="#1E293B", weight="600", align="left")
            + _td(f"${b['cpp_low']:,}-{b['cpp_high']:,}".replace(",", "."),
                   bg="#FFFFFF", color="#1E293B", weight="600")
            + _td(b["tipo"], bg="#FFFFFF", color="#475569", align="left", padding="6px 10px")
            + _td(b["ventajas"], bg="#FFFFFF", color="#475569", align="left", padding="6px 10px")
            + _td(b["desventajas"], bg="#FFFFFF", color="#475569", align="left", padding="6px 10px")
            + "</tr>")
    if not inserted:
        bench_rows.append("<tr>"
            + _td("📍 UnionX HOY", bg="#FFEBE6", color="#DC2626", weight="700", align="left")
            + _td(f"${cpp:,.0f}".replace(",", "."), bg="#FFEBE6",
                   color="#DC2626", weight="700")
            + _td("Sobre rangos benchmarks 3PL", bg="#FFEBE6", color="#DC2626", align="left", padding="6px 10px")
            + _td("—", bg="#FFEBE6", color="#475569", align="left", padding="6px 10px")
            + _td("—", bg="#FFEBE6", color="#475569", align="left", padding="6px 10px")
            + "</tr>")

    st.markdown(
        '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
        f'{"".join(bench_rows)}</table></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div style="background:#F1F5F9;border-radius:6px;padding:10px 14px;'
        f'margin-top:10px;font-size:12px;color:#475569;">'
        f'<b>🎯 ¿Cuál es el OBJETIVO real?</b><br>'
        f'Tu AOV es <b>${aov:,.0f}</b> (categoría: {objetivo["categoria"]}).<br>'
        f'Para esa AOV, el objetivo es <b>costo/pedido entre ${objetivo["cpp_min"]:,}-${objetivo["cpp_max"]:,}</b> '
        f'que equivale a <b>{objetivo["pct_min"]}-{objetivo["pct_max"]}% costo/venta</b>. '
        f'Apuntar a <b>ambos al mismo tiempo</b> — no son intercambiables. '
        f'Si tenés AOV bajo, no podés meter $5K de costo aunque sea solo 5%; si tenés AOV alto, no podés ser feliz con $5K de costo si es 30% del pedido.'
        f'</div>'.replace(",", "."),
        unsafe_allow_html=True,
    )

    st.divider()

    # ─── 5. BREAK-EVEN sobre Margen Contribución ─────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:12px 0;font-weight:700;font-size:13px;">'
        '5. PUNTO DE EQUILIBRIO — sobre Margen Contribución (REAL del módulo Ventas)</div>',
        unsafe_allow_html=True,
    )

    cf_mensual = float(df_reg["fijo_abs"].mean())
    margen_avg = float(df_reg["margen_final_m"].mean())
    venta_avg_real = float(df_reg["venta_neta_m"].mean())
    mc_pct = (margen_avg / venta_avg_real) if venta_avg_real else 0
    breakeven = (cf_mensual / mc_pct) if mc_pct > 0 else None
    holgura_pct = ((venta_avg_real / breakeven - 1) * 100) if breakeven else None

    cM, cF = st.columns([2, 1])
    with cM:
        be1, be2, be3, be4 = st.columns(4)
        be1.metric("Costo Fijo Op mensual", _fmt_num(cf_mensual))
        be2.metric("Margen Contrib %", f"{mc_pct*100:.1f}%",
                     f"${margen_avg:,.0f} / ${venta_avg_real:,.0f}".replace(",", "."))
        be3.metric("Venta BREAK-EVEN", _fmt_num(breakeven) if breakeven else "—")
        be4.metric("Holgura vs venta",
                     f"{holgura_pct:+.1f}%" if holgura_pct is not None else "—")

        if breakeven and venta_avg_real >= breakeven:
            st.success(
                f"✅ Operación rentable: vendés ${venta_avg_real:,.0f} M vs BE de "
                f"${breakeven:,.0f} M. Cada $1 sobre BE aporta ${mc_pct:.2f} a "
                f"utilidad operativa.".replace(",", ".")
            )
        elif breakeven:
            st.error(
                f"🔴 Bajo break-even: faltan ${breakeven - venta_avg_real:,.0f} M/mes "
                f"para cubrir fijos.".replace(",", ".")
            )
    with cF:
        st.markdown(
            '<div style="background:#FFF8E1;border-left:4px solid #F59E0B;'
            'padding:10px 14px;border-radius:4px;font-size:12px;color:#1E293B;">'
            '<b>📚 ¿Qué es el Margen de Contribución?</b><br>'
            'Es lo que queda de cada peso vendido DESPUÉS de pagar los costos '
            'directos del producto (COGS, comisiones canal, logística, marketing).<br><br>'
            '<b>Fórmula:</b> MC = Margen Final / Venta Neta<br>'
            '<b>Origen:</b> módulo Ventas (parquet), columna <code>margen_final</code>.<br><br>'
            'Sirve para saber cuánto te queda para pagar la operación. El break-even '
            'es cuando MC × Venta = Costos Fijos.'
            '</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ─── 6. CUÁNDO ESCALAR FIJOS ─────────────────────────────────
    st.markdown(
        '<div style="background:#1F4E79;color:#FFFFFF;padding:10px 16px;'
        'border-radius:4px;margin:12px 0;font-weight:700;font-size:13px;">'
        '6. CUÁNDO HAY QUE ESCALAR (o achicar) COSTOS FIJOS</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Modelo: si el variable es ~lineal con pedidos pero el fijo NO escala, "
        "hay un punto donde el equipo/bodega se satura y hay que sumar otra persona "
        "o m³ de bodega. Estos son los umbrales recomendados."
    )

    # Heurística simple: capacidad por unidad de fijo
    # Asumimos que 1 persona FTE bodega = $1.5MM/mes y maneja ~1500 pedidos/mes
    PEDIDOS_POR_FTE = 1500
    COSTO_FTE_MENSUAL = 1500
    M3_BODEGA_BASE = 500  # m³ por bodega base
    COSTO_BODEGA_MENSUAL = 5000  # $5MM/mes por bodega base

    # Capacidad actual asumida desde fijos
    n_ftes_actual = max(1, cf_mensual / COSTO_FTE_MENSUAL)
    capacidad_pedidos = n_ftes_actual * PEDIDOS_POR_FTE
    utilizacion_pct = (pedidos_avg / capacidad_pedidos * 100) if capacidad_pedidos else 0

    e1, e2, e3 = st.columns(3)
    e1.metric("FTEs implícitos en fijos",
                f"{n_ftes_actual:.1f}",
                f"asumiendo ${COSTO_FTE_MENSUAL/1000:.1f}M/FTE")
    e2.metric("Capacidad teórica pedidos/mes",
                f"{capacidad_pedidos:,.0f}".replace(",", "."),
                f"a {PEDIDOS_POR_FTE}/FTE")
    e3.metric("Utilización actual",
                f"{utilizacion_pct:.0f}%",
                f"{pedidos_avg:,.0f} / {capacidad_pedidos:,.0f}".replace(",", "."))

    if utilizacion_pct < 60:
        st.info(
            f"🟦 **Sub-utilizado** ({utilizacion_pct:.0f}%): tenés capacidad ociosa. "
            f"Antes de sumar fijos, asegurarte de saturar lo que tenés. "
            f"Podrías procesar hasta {capacidad_pedidos - pedidos_avg:.0f} pedidos extra/mes "
            f"sin sumar costos fijos."
        )
    elif utilizacion_pct < 85:
        st.success(
            f"🟢 **Utilización óptima** ({utilizacion_pct:.0f}%): zona dulce. "
            f"Tenés margen para crecer sin sumar fijos hasta ~{capacidad_pedidos:,.0f} pedidos/mes."
            .replace(",", ".")
        )
    elif utilizacion_pct < 100:
        st.warning(
            f"🟠 **Cerca del límite** ({utilizacion_pct:.0f}%): empezar a planear "
            f"el siguiente FTE (+${COSTO_FTE_MENSUAL/1000:.1f}M fijo/mes). "
            f"Cuando llegues a {capacidad_pedidos:.0f} pedidos/mes consistentes, sumar."
        )
    else:
        st.error(
            f"🔴 **SATURADO** ({utilizacion_pct:.0f}%): ya superás capacidad teórica. "
            f"Necesitás sumar al menos {(pedidos_avg/capacidad_pedidos - 1) * n_ftes_actual:.1f} FTEs "
            f"o evaluar tercerizar overflow con un 3PL puntual."
        )

    # Tabla de umbrales
    st.markdown("<h5 style='color:#1F4E79;margin:14px 0 6px 0;'>📏 Umbrales de escalamiento sugeridos</h5>",
                  unsafe_allow_html=True)
    umbrales = [
        ("Sumar 1 FTE bodega",
          f"Cuando pedidos/mes > {int(capacidad_pedidos * 0.85):,}".replace(",", "."),
          f"+${COSTO_FTE_MENSUAL/1000:.1f}M fijo/mes"),
        ("Reducir 1 FTE bodega",
          f"Si pedidos/mes < {int((n_ftes_actual - 1) * PEDIDOS_POR_FTE * 0.7):,} sostenido 2+ meses".replace(",", "."),
          f"−${COSTO_FTE_MENSUAL/1000:.1f}M/mes"),
        ("Sumar bodega o m³ adicional",
          f"Cuando ocupación >85% por 60 días seguidos",
          f"+${COSTO_BODEGA_MENSUAL/1000:.1f}M/mes (~{M3_BODEGA_BASE} m³)"),
        ("Tercerizar overflow con 3PL puntual",
          f"En picos +50% sobre capacidad sin sumar fijo permanente",
          f"~${BENCH_CPP_RANGO_3PL}/pedido extra (variable)"),
    ]
    u_rows = ["<tr>"
                + _th("Decisión", bg="#1F4E79", align="left")
                + _th("Cuándo", bg="#1F4E79", align="left")
                + _th("Impacto $", bg="#1F4E79")
                + "</tr>"]
    for d, c, imp in umbrales:
        u_rows.append("<tr>"
            + _td(d, bg="#FFFFFF", color="#1E293B", weight="600", align="left")
            + _td(c, bg="#FFFFFF", color="#475569", align="left", padding="6px 10px")
            + _td(imp, bg="#FFFFFF", color="#1E293B", weight="600")
            + "</tr>")
    st.markdown(
        '<div style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden;">'
        '<table style="border-collapse:collapse;width:100%;font-family:'
        '-apple-system,Segoe UI,sans-serif;font-size:12px;">'
        f'{"".join(u_rows)}</table></div>',
        unsafe_allow_html=True,
    )

    # Nota próximo paso
    st.markdown(
        '<div style="background:#E3F2FD;border-left:4px solid #1F4E79;'
        'padding:12px 16px;margin-top:20px;border-radius:4px;font-size:12px;'
        'color:#1E293B;">'
        '<b>🎯 Próximo paso (app Finanzas):</b> con costo operativo bien medido y '
        'modelo de driver claro (¿pedidos? ¿unidades? ¿venta?), crear P&L por '
        'línea de negocio asignando costos según el driver más correlacionado de '
        'cada CC. Esto cierra el loop de rentabilidad real por canal.'
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
