"""
🤖 Asistente IA — App Operaciones (Google Gemini, GRATIS).

Chatbot con Gemini 2.0 Flash que tiene acceso en tiempo real a los
datos de la app via tool calling:
  - costo_operativo.parquet (Sheet OPERACIONES Drive)
  - control_gestion.parquet (Sheet P&L Finanzas)
  - ventas_historico.parquet (módulo Ventas)
  - kpis_wms snapshot (productividad, OTIF, etc.)
  - capacidad forecast (bodega + tránsito)
  - dimensiones COMEX

Tier gratuito Google AI Studio:
  - 15 requests/min
  - 1.500 requests/día
  - 1M tokens/día (input + output)
  → MÁS que suficiente para uso personal de Andrés.

Requiere GEMINI_API_KEY en Streamlit Secrets.
Obtener gratis en: https://aistudio.google.com/apikey
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).parent.parent
COSTO_OP_PARQUET = PROJECT_ROOT / "data" / "operaciones" / "costo_operativo.parquet"
CONTROL_GESTION_PARQUET = PROJECT_ROOT / "data" / "finanzas" / "control_gestion.parquet"
VENTAS_HIST_PARQUET = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"
WMS_SNAPSHOT_JSON = PROJECT_ROOT / "data" / "kpis_wms" / "snapshot.json"
CAPACIDAD_JSON = PROJECT_ROOT / "data" / "capacidad" / "forecast_resumen.json"
COMEX_RESUMEN_JSON = PROJECT_ROOT / "data" / "comex" / "transito_resumen.json"


# ============================================================
# DATA LOADERS (cacheados)
# ============================================================
@st.cache_data(ttl=300)
def _load_costo_op() -> pd.DataFrame:
    if COSTO_OP_PARQUET.exists():
        return pd.read_parquet(COSTO_OP_PARQUET)
    return pd.DataFrame()


@st.cache_data(ttl=300)
def _load_control_gestion() -> pd.DataFrame:
    if CONTROL_GESTION_PARQUET.exists():
        return pd.read_parquet(CONTROL_GESTION_PARQUET)
    return pd.DataFrame()


@st.cache_data(ttl=600)
def _load_ventas() -> pd.DataFrame:
    if not VENTAS_HIST_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(VENTAS_HIST_PARQUET)
    df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce")
    df = df.dropna(subset=["fecha_venta"])
    df["year"] = df["fecha_venta"].dt.year
    df["month"] = df["fecha_venta"].dt.month
    return df


@st.cache_data(ttl=300)
def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return {}


# ============================================================
# TOOLS — cada función ES una herramienta que Claude puede invocar
# ============================================================
def tool_costo_operativo(
    year: int,
    meses: list[int] | None = None,
    sub_area: str | None = None,
    centro_costo: str | None = None,
    tipo_costo: str | None = None,
    escenario: str = "FCST",
) -> dict:
    """Consulta gastos operativos por filtros.

    Devuelve: total, # filas, desglose por sub_area/CC, top 5 cuenta_analiticas.
    """
    df = _load_costo_op()
    if df.empty:
        return {"error": "Sin datos costo operativo"}

    f = df[(df["year"] == year) & (df["escenario"] == escenario)
            & (df["kpi"] == "GASTO")]
    if meses:
        f = f[f["month"].isin(meses)]
    if sub_area:
        f = f[f["sub_area"].str.upper() == sub_area.upper()]
    if centro_costo:
        f = f[f["centro_costo"].str.upper() == centro_costo.upper()]
    if tipo_costo:
        f = f[f["tipo_costo"].str.upper() == tipo_costo.upper()]

    total = float(f["valor"].sum())
    by_sa = f.groupby("sub_area")["valor"].sum().to_dict()
    by_cc = f.groupby("centro_costo")["valor"].sum().sort_values().head(10).to_dict()
    by_cta = (f.groupby("cuenta_analitica")["valor"].sum()
                  .abs().sort_values(ascending=False).head(5).to_dict())
    by_tipo = f.groupby("tipo_costo")["valor"].sum().to_dict()

    return {
        "total_clp_miles": round(total, 0),
        "filas": len(f),
        "filtros": {"year": year, "meses": meses, "sub_area": sub_area,
                     "centro_costo": centro_costo, "tipo_costo": tipo_costo,
                     "escenario": escenario},
        "por_sub_area": {k: round(v, 0) for k, v in by_sa.items() if v},
        "top_10_cc": {k: round(v, 0) for k, v in by_cc.items() if k},
        "top_5_cuenta_analitica": {k: round(v, 0) for k, v in by_cta.items() if k},
        "por_tipo_costo": {k: round(v, 0) for k, v in by_tipo.items() if k},
    }


def tool_comparar_yoy(
    year_actual: int,
    year_anterior: int,
    meses: list[int] | None = None,
    centro_costo: str | None = None,
    sub_area: str | None = None,
) -> dict:
    """Compara costos año contra año para detectar desviaciones grandes."""
    df = _load_costo_op()
    if df.empty:
        return {"error": "Sin datos"}

    def _filtra(year):
        f = df[(df["year"] == year) & (df["escenario"] == "FCST")
                & (df["kpi"] == "GASTO")]
        if meses:
            f = f[f["month"].isin(meses)]
        if centro_costo:
            f = f[f["centro_costo"].str.upper() == centro_costo.upper()]
        if sub_area:
            f = f[f["sub_area"].str.upper() == sub_area.upper()]
        return f

    f_act = _filtra(year_actual)
    f_ant = _filtra(year_anterior)
    total_act = float(f_act["valor"].sum())
    total_ant = float(f_ant["valor"].sum())
    var_pct = ((abs(total_act) - abs(total_ant)) / abs(total_ant) * 100) if total_ant else None

    # Top variaciones por CC
    cc_act = f_act.groupby("centro_costo")["valor"].sum().abs()
    cc_ant = f_ant.groupby("centro_costo")["valor"].sum().abs()
    cc_var = (cc_act - cc_ant).sort_values(ascending=False).head(10)

    return {
        f"total_{year_anterior}": round(total_ant, 0),
        f"total_{year_actual}": round(total_act, 0),
        "var_absoluta_miles_clp": round(abs(total_act) - abs(total_ant), 0),
        "var_pct": round(var_pct, 1) if var_pct is not None else None,
        "top_10_cc_var_yoy": {k: round(v, 0) for k, v in cc_var.items()},
    }


def tool_venta_periodo(
    year: int,
    meses: list[int] | None = None,
    canal: str | None = None,
    marca: str | None = None,
) -> dict:
    """Consulta venta neta y margen del módulo Ventas."""
    df = _load_ventas()
    if df.empty:
        return {"error": "Sin datos ventas"}

    f = df[df["year"] == year]
    if meses:
        f = f[f["month"].isin(meses)]
    if canal:
        f = f[f["canal"].str.contains(canal, case=False, na=False)]
    if marca:
        f = f[f["marca"].str.contains(marca, case=False, na=False)]

    return {
        "venta_bruta_clp": float(f["venta_bruta"].sum()),
        "venta_neta_clp": float(f["venta_neta"].sum()),
        "margen_front_clp": float(f["margen_front"].sum()),
        "margen_final_clp": float(f["margen_final"].sum()),
        "n_pedidos": int(f["pedido"].nunique()),
        "n_unidades": int(f["cantidad"].sum()),
        "filtros": {"year": year, "meses": meses, "canal": canal, "marca": marca},
    }


def tool_ratio_costo_venta(year: int, meses: list[int] | None = None) -> dict:
    """Calcula ratio Costo Operativo / Venta Neta para un período."""
    costo = tool_costo_operativo(year, meses, escenario="FCST")
    venta = tool_venta_periodo(year, meses)
    if "error" in costo or "error" in venta:
        return {"error": "Sin data suficiente"}
    venta_neta_m = venta["venta_neta_clp"] / 1000  # M CLP
    costo_m = abs(costo["total_clp_miles"])
    ratio = (costo_m / venta_neta_m * 100) if venta_neta_m else None
    benchmark = "🟢 Cumple Plan UnionX (8-12%)" if ratio and ratio <= 12 else (
        "🟡 Atención (12-14%)" if ratio and ratio <= 14 else "🔴 Sobre benchmark")
    return {
        "year": year,
        "meses": meses,
        "venta_neta_miles_clp": round(venta_neta_m, 0),
        "costo_op_miles_clp": round(costo_m, 0),
        "ratio_costo_venta_pct": round(ratio, 2) if ratio else None,
        "evaluacion": benchmark,
    }


def tool_centros_costo_disponibles() -> list[str]:
    """Lista todos los Centros de Costo y Sub-áreas disponibles."""
    df = _load_costo_op()
    if df.empty:
        return []
    return {
        "centros_costo": sorted(df["centro_costo"].dropna().unique().tolist()),
        "sub_areas": sorted(df["sub_area"].dropna().unique().tolist()),
        "areas": sorted(df["area"].dropna().unique().tolist()),
        "tipos_costo": sorted(df["tipo_costo"].dropna().unique().tolist()),
        "years_disponibles": sorted(df["year"].dropna().unique().astype(int).tolist()),
        "canales": sorted(df["canal"].dropna().unique().tolist()),
    }


def tool_drilldown_cc(centro_costo: str, year: int,
                       meses: list[int] | None = None) -> dict:
    """Drill-down de un CC: mes a mes + top cuentas analíticas + tipo costo."""
    df = _load_costo_op()
    if df.empty:
        return {"error": "Sin datos"}
    f = df[(df["year"] == year)
            & (df["centro_costo"].str.upper() == centro_costo.upper())
            & (df["escenario"] == "FCST") & (df["kpi"] == "GASTO")]
    if meses:
        f = f[f["month"].isin(meses)]
    if f.empty:
        return {"error": f"No se encontraron datos para CC '{centro_costo}'"}

    return {
        "centro_costo": centro_costo,
        "total_clp_miles": round(float(f["valor"].sum()), 0),
        "tipo_costo_predominante": (f.groupby("tipo_costo")["valor"].sum()
                                         .abs().idxmax()),
        "por_mes": {int(m): round(float(v), 0)
                       for m, v in f.groupby("month")["valor"].sum().items()},
        "por_cuenta_analitica": (f.groupby("cuenta_analitica")["valor"].sum()
                                    .abs().sort_values(ascending=False)
                                    .head(10).round(0).to_dict()),
        "por_sub_area": (f.groupby("sub_area")["valor"].sum()
                            .round(0).to_dict()),
    }


def tool_top_desviaciones(year: int, meses: list[int] | None = None,
                            top_n: int = 5) -> dict:
    """Top N CCs con mayor sobregasto FCST vs PPTO."""
    df = _load_costo_op()
    if df.empty:
        return {"error": "Sin datos"}
    f = df[(df["year"] == year) & (df["kpi"] == "GASTO")]
    if meses:
        f = f[f["month"].isin(meses)]
    piv = (f.groupby(["centro_costo", "escenario"])["valor"].sum()
              .unstack("escenario", fill_value=0))
    if "PPTO" not in piv.columns or "FCST" not in piv.columns:
        return {"error": "Falta PPTO o FCST en el periodo"}
    piv["sobregasto"] = piv["FCST"].abs() - piv["PPTO"].abs()
    piv["pct"] = piv.apply(
        lambda r: ((abs(r["FCST"]) - abs(r["PPTO"])) / abs(r["PPTO"]) * 100)
                   if r["PPTO"] else 0, axis=1)
    top = piv.nlargest(top_n, "sobregasto").round(1)
    return {
        "year": year, "meses": meses,
        "top_desviaciones": [
            {
                "centro_costo": cc,
                "ppto_miles_clp": round(row["PPTO"], 0),
                "real_miles_clp": round(row["FCST"], 0),
                "sobregasto_miles_clp": round(row["sobregasto"], 0),
                "var_pct": round(row["pct"], 1),
            }
            for cc, row in top.iterrows()
        ],
    }


def tool_kpis_wms() -> dict:
    """Snapshot de KPIs operacionales WMS (productividad, OTIF, etc.)."""
    snap = _load_json(WMS_SNAPSHOT_JSON)
    if not snap:
        return {"error": "Sin snapshot WMS"}
    return {
        "generado": snap.get("generado_en", ""),
        "kpis": snap.get("kpis", {}),
        "productividad_mes_6m_resumen":
            snap.get("productividad_mes_6m", {}).get("items", [])[-6:],
    }


def tool_capacidad_bodega() -> dict:
    """Forecast de capacidad bodega 90 días."""
    r = _load_json(CAPACIDAD_JSON)
    if not r:
        return {"error": "Sin forecast capacidad"}
    return {
        "estado_actual": r.get("estado_actual", {}),
        "pico_proyectado": r.get("pico_proyectado", {}),
        "primer_critico": r.get("primer_critico"),
        "primer_atencion": r.get("primer_atencion"),
        "capacidad_total_posiciones": r.get("capacidad_posiciones"),
    }


def tool_comex_transito() -> dict:
    """Resumen embarques en tránsito (PIs por llegar, m³, pallets)."""
    r = _load_json(COMEX_RESUMEN_JSON)
    if not r:
        return {"error": "Sin data tránsito"}
    return r


# ============================================================
# TOOL FUNCTIONS REGISTRY (Gemini usa Python functions directamente)
# ============================================================
TOOLS_DEF_LEGACY = [
    {
        "name": "costo_operativo",
        "description": "Consulta gastos operativos (FCST=real) del Sheet "
                         "OPERACIONES con filtros opcionales. Útil para preguntas "
                         "como '¿cuánto gastamos en logística Q1?' o "
                         "'¿cuál es el costo de REMUNERACIONES en 2026?'",
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Año (2025 o 2026)"},
                "meses": {"type": "array", "items": {"type": "integer"},
                            "description": "Lista meses 1-12, opcional"},
                "sub_area": {"type": "string",
                              "description": "LOGISTICA, OPERACIONES, POSTVENTA, GRUPO ETER, UNIONX"},
                "centro_costo": {"type": "string",
                                   "description": "REMUNERACIONES, ARRIENDOS, etc."},
                "tipo_costo": {"type": "string",
                                 "description": "FIJO o VARIABLE"},
                "escenario": {"type": "string",
                                "description": "FCST (default, real) o PPTO"},
            },
            "required": ["year"],
        },
    },
    {
        "name": "comparar_yoy",
        "description": "Compara gastos entre 2 años (típicamente 2026 vs 2025) "
                         "para detectar variaciones. Filtros opcionales por CC, "
                         "sub-área, meses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "year_actual": {"type": "integer"},
                "year_anterior": {"type": "integer"},
                "meses": {"type": "array", "items": {"type": "integer"}},
                "centro_costo": {"type": "string"},
                "sub_area": {"type": "string"},
            },
            "required": ["year_actual", "year_anterior"],
        },
    },
    {
        "name": "venta_periodo",
        "description": "Consulta venta neta + margen + pedidos del módulo Ventas. "
                         "Filtros opcionales por canal, marca.",
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "meses": {"type": "array", "items": {"type": "integer"}},
                "canal": {"type": "string",
                            "description": "Walmart, Falabella, etc. (substring match)"},
                "marca": {"type": "string", "description": "Lhotse, Levo, etc."},
            },
            "required": ["year"],
        },
    },
    {
        "name": "ratio_costo_venta",
        "description": "Calcula ratio Costo Operativo / Venta Neta y evalúa vs "
                         "benchmark Plan UnionX (8-12%).",
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "meses": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["year"],
        },
    },
    {
        "name": "centros_costo_disponibles",
        "description": "Lista todos los CCs, sub-áreas, áreas, tipos de costo "
                         "disponibles en los datos. Útil al inicio si no estás "
                         "seguro de qué filtrar.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "drilldown_cc",
        "description": "Drill-down profundo de un CC específico: mes a mes + "
                         "top cuentas analíticas + tipo costo predominante.",
        "input_schema": {
            "type": "object",
            "properties": {
                "centro_costo": {"type": "string"},
                "year": {"type": "integer"},
                "meses": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["centro_costo", "year"],
        },
    },
    {
        "name": "top_desviaciones",
        "description": "Top N centros de costo con mayor sobregasto FCST vs PPTO.",
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "meses": {"type": "array", "items": {"type": "integer"}},
                "top_n": {"type": "integer", "description": "Default 5"},
            },
            "required": ["year"],
        },
    },
    {
        "name": "kpis_wms",
        "description": "KPIs operacionales WMS: productividad mensual (pedidos, "
                         "líneas, unidades), OTIF, pick accuracy, etc.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "capacidad_bodega",
        "description": "Forecast capacidad bodega 90 días: posiciones ocupadas/libres, "
                         "pico proyectado, primer crítico.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "comex_transito",
        "description": "Resumen embarques COMEX en tránsito: PIs próximos a llegar, "
                         "ETAs, m³ y pallets estimados.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

TOOL_FUNCS = {
    "costo_operativo": tool_costo_operativo,
    "comparar_yoy": tool_comparar_yoy,
    "venta_periodo": tool_venta_periodo,
    "ratio_costo_venta": tool_ratio_costo_venta,
    "centros_costo_disponibles": tool_centros_costo_disponibles,
    "drilldown_cc": tool_drilldown_cc,
    "top_desviaciones": tool_top_desviaciones,
    "kpis_wms": tool_kpis_wms,
    "capacidad_bodega": tool_capacidad_bodega,
    "comex_transito": tool_comex_transito,
}


SYSTEM_PROMPT = """Sos un asistente experto en operaciones y finanzas de UnionX.

Tenés acceso a TOOLS para consultar datos reales en tiempo real:
- costo_operativo: Sheet OPERACIONES (Drive) con Ppto y Fcst por mes/CC/sub-área/tipo
- venta_periodo: módulo Ventas (parquet histórico) con venta bruta/neta/margen/pedidos
- comparar_yoy: comparación año contra año
- ratio_costo_venta: ratio Costo Op / Venta Neta vs benchmark Plan UnionX (8-12%)
- top_desviaciones: CCs con mayor sobregasto Ppto vs Real
- drilldown_cc: desglose profundo de un CC
- kpis_wms: productividad bodega, OTIF, pick accuracy
- capacidad_bodega: forecast posiciones 90 días
- comex_transito: embarques en tránsito

CONTEXTO IMPORTANTE:
- Modelo "Fcst = Real": el escenario FCST representa lo realmente gastado/proyectado
- Valores del Sheet OPERACIONES están en MILES CLP (M$)
- Valores del módulo Ventas están en CLP raw (dividir por 1000 para comparar)
- Año actual: 2026
- Sub-áreas operacionales: LOGISTICA, OPERACIONES, POSTVENTA, GRUPO ETER, UNIONX
- Benchmark Plan UnionX 2026-2028: costo logístico/venta 8-12% óptimo, 12-14% atención, >14% crítico

ESTILO DE RESPUESTA:
- Sé conciso y directo, español chileno
- Usa números con formato chileno (puntos miles, comas decimales)
- Cuando expliques un "por qué", siempre llamá a las tools primero para tener data real
- Si la pregunta es ambigua (ej: "¿por qué subió tanto?"), preguntá período/año o asumí Q actual
- Para análisis de variaciones, siempre dá: monto absoluto + % + qué CC/cuenta lo explica
- Sugerí acciones concretas cuando detectes ineficiencias
- NO inventes números — si una tool falla, decilo

Cuando el usuario te pregunte "¿por qué el número X?", tu flujo:
1. Identificar qué métrica refiere
2. Llamar tools para obtener data
3. Hacer drill-down si es necesario para encontrar el driver
4. Explicar la causa + sugerir acción si aplica"""


# ============================================================
# UI — Google Gemini (gratis)
# ============================================================
SUGERENCIAS = [
    "¿Por qué subió tanto Logística en Q1 2026?",
    "¿Cuál es el ratio Costo/Venta YTD?",
    "Comparame REMUNERACIONES 2026 vs 2025",
    "¿Qué CC tuvo la mayor desviación Ppto vs Real?",
    "¿Cuánto gastamos en arriendos este año?",
    "¿Qué tan llena va a estar la bodega en 60 días?",
]


def _modo_consultas_directas():
    """Modo fallback sin LLM: selectores + tools."""
    st.divider()
    st.markdown("### 📊 Modo consultas directas (sin LLM)")
    st.caption("Mientras configurás Gemini, podés consultar las tools directamente:")

    consulta = st.selectbox(
        "Tipo de consulta",
        [
            "Costo Operativo por filtro",
            "Comparar año vs año (YoY)",
            "Top desviaciones Ppto vs Real",
            "Ratio Costo/Venta",
            "Drill-down Centro de Costo",
            "Venta del período (módulo Ventas)",
        ],
    )

    if consulta == "Costo Operativo por filtro":
        cA, cB = st.columns(2)
        y = cA.selectbox("Año", [2025, 2026], key="cd_y1")
        mes_sel = cB.selectbox("Período", ["Todos", "Q1", "Q2", "Q3", "Q4"], key="cd_m1")
        sa = st.selectbox("Sub-área", ["Todas", "LOGISTICA", "OPERACIONES",
                                          "POSTVENTA", "GRUPO ETER", "UNIONX"],
                            key="cd_sa1")
        if st.button("Consultar", type="primary", key="cd_b1"):
            m = {"Q1": [1,2,3], "Q2": [4,5,6], "Q3": [7,8,9], "Q4": [10,11,12]}.get(mes_sel)
            r = tool_costo_operativo(year=y, meses=m,
                                       sub_area=sa if sa != "Todas" else None)
            st.json(r)

    elif consulta == "Comparar año vs año (YoY)":
        cA, cB = st.columns(2)
        ya = cA.selectbox("Año actual", [2026, 2025], key="cd_y2a")
        yb = cB.selectbox("Año anterior", [2025, 2024], key="cd_y2b")
        if st.button("Comparar", type="primary", key="cd_b2"):
            r = tool_comparar_yoy(year_actual=ya, year_anterior=yb)
            st.json(r)

    elif consulta == "Top desviaciones Ppto vs Real":
        cA, cB = st.columns(2)
        y = cA.selectbox("Año", [2026, 2025], key="cd_y3")
        n = cB.slider("Top N", 3, 20, 5, key="cd_n3")
        if st.button("Buscar", type="primary", key="cd_b3"):
            r = tool_top_desviaciones(year=y, top_n=n)
            st.json(r)

    elif consulta == "Ratio Costo/Venta":
        cA, cB = st.columns(2)
        y = cA.selectbox("Año", [2026, 2025], key="cd_y4")
        mes_sel = cB.selectbox("Período", ["YTD", "Q1", "Q2", "Q3", "Q4"], key="cd_m4")
        if st.button("Calcular", type="primary", key="cd_b4"):
            m = {"Q1": [1,2,3], "Q2": [4,5,6], "Q3": [7,8,9], "Q4": [10,11,12]}.get(mes_sel)
            r = tool_ratio_costo_venta(year=y, meses=m)
            st.json(r)

    elif consulta == "Drill-down Centro de Costo":
        ccs = tool_centros_costo_disponibles().get("centros_costo", [])
        cA, cB = st.columns(2)
        cc = cA.selectbox("Centro de Costo", ccs, key="cd_cc5")
        y = cB.selectbox("Año", [2026, 2025], key="cd_y5")
        if st.button("Drill-down", type="primary", key="cd_b5"):
            r = tool_drilldown_cc(centro_costo=cc, year=y)
            st.json(r)

    elif consulta == "Venta del período (módulo Ventas)":
        cA, cB = st.columns(2)
        y = cA.selectbox("Año", [2026, 2025], key="cd_y6")
        mes_sel = cB.selectbox("Período", ["YTD", "Q1", "Q2", "Q3", "Q4"], key="cd_m6")
        if st.button("Consultar", type="primary", key="cd_b6"):
            m = {"Q1": [1,2,3], "Q2": [4,5,6], "Q3": [7,8,9], "Q4": [10,11,12]}.get(mes_sel)
            r = tool_venta_periodo(year=y, meses=m)
            st.json(r)


def render():
    with st.sidebar:
        st.markdown("### 🤖 **Asistente IA**")
        st.caption("Gemini — gratis")
        st.divider()
        if st.button("🗑️ Limpiar conversación", use_container_width=True):
            st.session_state.pop("ops_chat_msgs", None)
            st.rerun()

    st.title("🤖 Asistente IA — Operaciones")
    st.caption(
        "Powered by Google Gemini (gratis · 1.500 reqs/día) · "
        "10 tools sobre los parquets del repo en vivo"
    )

    # Check API key
    api_key = None
    try:
        api_key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        pass
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        st.warning("⚠️ Falta `GEMINI_API_KEY` en Streamlit Secrets para activar el chat.")
        with st.expander("📋 ¿Cómo obtenerla? (es gratis, 2 minutos)", expanded=True):
            st.markdown(
                "1. Ir a **https://aistudio.google.com/apikey**\n"
                "2. Login con tu cuenta Google\n"
                "3. Click **Create API key** → seleccionar proyecto (o crear nuevo)\n"
                "4. Copiar la key (empieza con `AIza...`)\n"
                "5. En Streamlit Cloud → app `unionx-operaciones` → Settings → Secrets, agregar:\n"
                "   ```toml\n"
                "   GEMINI_API_KEY = \"AIza...\"\n"
                "   ```\n"
                "6. Reboot app\n\n"
                "**Tier gratuito Gemini 2.0 Flash:**\n"
                "- 15 requests por minuto\n"
                "- 1.500 requests por día\n"
                "- 1.000.000 tokens por día\n\n"
                "→ Más que suficiente para uso personal."
            )
        _modo_consultas_directas()
        return

    # Importar SDK Gemini
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        st.error(
            "⚠️ Falta paquete `google-genai`. Agregar a requirements.txt:\n"
            "```\ngoogle-genai>=0.7.0\n```"
        )
        _modo_consultas_directas()
        return

    client = genai.Client(api_key=api_key)

    # Sistema prompt
    system_prompt = """Sos un asistente experto en operaciones y finanzas de UnionX.

Tenés acceso a tools para consultar datos REALES en tiempo real:
- costo_operativo: gastos por año/mes/sub-area/CC/tipo/escenario (FCST=real, PPTO)
- venta_periodo: venta neta/bruta/margen/pedidos del módulo Ventas
- comparar_yoy: comparación año contra año
- ratio_costo_venta: ratio + evaluación vs benchmark Plan UnionX (8-12%)
- top_desviaciones: CCs con mayor sobregasto Ppto vs Real
- drilldown_cc: desglose profundo de un CC (mes a mes + cuenta analítica)
- centros_costo_disponibles: lista de CCs/sub-áreas/tipos
- kpis_wms: productividad bodega
- capacidad_bodega: forecast posiciones 90 días
- comex_transito: PIs en tránsito

CONTEXTO IMPORTANTE:
- Modelo "Fcst = Real": el escenario FCST representa lo realmente gastado
- Valores Sheet OPERACIONES están en MILES CLP (M$)
- Valores módulo Ventas están en CLP raw (dividir por 1000 para comparar con costos)
- Año actual: 2026
- Sub-áreas: LOGISTICA, OPERACIONES, POSTVENTA, GRUPO ETER, UNIONX
- Benchmark Plan UnionX: costo logístico/venta 8-12% óptimo

ESTILO:
- Conciso, español chileno
- Números formato chileno (1.234.567)
- Para "por qué" → llamar tools primero, no inventar
- Variaciones: dar monto absoluto + % + qué CC lo explica
- Sugerir acciones concretas si detectás ineficiencias
"""

    # Chat history
    if "ops_chat_msgs" not in st.session_state:
        st.session_state["ops_chat_msgs"] = []

    # Mostrar historial
    for msg in st.session_state["ops_chat_msgs"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Sugerencias
    if not st.session_state["ops_chat_msgs"]:
        st.markdown("##### 💡 Ejemplos de preguntas")
        col1, col2 = st.columns(2)
        for i, s in enumerate(SUGERENCIAS):
            col = col1 if i % 2 == 0 else col2
            if col.button(s, key=f"sug_{i}", use_container_width=True):
                st.session_state["_ops_chat_input"] = s
                st.rerun()

    # Input
    user_input = st.chat_input("Pregúntame algo sobre los números...")
    if "_ops_chat_input" in st.session_state:
        user_input = st.session_state.pop("_ops_chat_input")

    if user_input:
        st.session_state["ops_chat_msgs"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("⏳ Pensando...")

            try:
                # Tool functions list para Gemini (auto function calling)
                tool_funcs_list = [
                    tool_costo_operativo, tool_comparar_yoy, tool_venta_periodo,
                    tool_ratio_costo_venta, tool_centros_costo_disponibles,
                    tool_drilldown_cc, tool_top_desviaciones, tool_kpis_wms,
                    tool_capacidad_bodega, tool_comex_transito,
                ]

                # Construir historial para Gemini
                contents = []
                for m in st.session_state["ops_chat_msgs"]:
                    role = "user" if m["role"] == "user" else "model"
                    contents.append({"role": role, "parts": [{"text": m["content"]}]})

                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        tools=tool_funcs_list,
                        temperature=0.2,
                        # automatic_function_calling enabled por default cuando hay tools Python
                    ),
                )

                # Gemini ejecuta las funciones automáticamente y devuelve respuesta final
                final_text = response.text or "(sin respuesta)"

                # Mostrar tools llamadas si las hubo (en automatic_function_calling.history)
                try:
                    afc = response.automatic_function_calling_history
                    if afc:
                        with st.expander(f"🔧 {len(afc)} llamadas a tools", expanded=False):
                            for h in afc:
                                # h es un Content con function_call o function_response
                                if hasattr(h, "parts"):
                                    for p in h.parts:
                                        if hasattr(p, "function_call") and p.function_call:
                                            st.markdown(f"**→ `{p.function_call.name}`**")
                                            st.code(json.dumps(
                                                dict(p.function_call.args), indent=2,
                                                ensure_ascii=False, default=str,
                                            ))
                                        elif hasattr(p, "function_response") and p.function_response:
                                            st.code(json.dumps(
                                                dict(p.function_response.response or {}),
                                                indent=2, ensure_ascii=False, default=str,
                                            )[:1500])
                except Exception:
                    pass

                placeholder.markdown(final_text)
                st.session_state["ops_chat_msgs"].append({
                    "role": "assistant", "content": final_text,
                })

            except Exception as e:
                msg = str(e)[:400]
                placeholder.error(f"❌ Error Gemini: {type(e).__name__}: {msg}")
                # Quitar último user msg para retry limpio
                if st.session_state["ops_chat_msgs"]:
                    st.session_state["ops_chat_msgs"].pop()
