"""
🤖 Asistente IA — App Operaciones.

Chatbot con Claude (Anthropic) que tiene acceso en tiempo real a los
datos de la app:
  - costo_operativo.parquet (Sheet OPERACIONES Drive)
  - control_gestion.parquet (Sheet P&L Finanzas)
  - ventas_historico.parquet (módulo Ventas)
  - kpis_wms snapshot (productividad, OTIF, etc.)
  - capacidad forecast (bodega + tránsito)
  - dimensiones COMEX

Usa tool calling para que Claude pueda:
  - Consultar costos por CC, período, sub-área, tipo costo
  - Comparar años (YoY)
  - Cruzar costos vs venta vs pedidos
  - Detectar outliers e ineficiencias
  - Proyectar costo según escenario de venta

Requiere ANTHROPIC_API_KEY en Streamlit Secrets.
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
# TOOL DEFINITIONS para Claude API
# ============================================================
TOOLS_DEF = [
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
# UI
# ============================================================
def render():
    with st.sidebar:
        st.markdown("### 🤖 **Asistente IA**")
        st.caption("Pregúntame sobre los números")
        st.divider()
        if st.button("🗑️ Limpiar conversación", use_container_width=True):
            st.session_state.pop("ops_chat_msgs", None)
            st.rerun()

    st.title("🤖 Asistente IA — Operaciones")
    st.caption(
        "Hago preguntas sobre los datos: costos, ventas, eficiencias, "
        "tendencias. Uso tools en vivo sobre los parquets del repo."
    )

    # Check API key
    api_key = (st.secrets.get("ANTHROPIC_API_KEY")
                if hasattr(st, "secrets") else None) or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error(
            "⚠️ Falta `ANTHROPIC_API_KEY` en Streamlit Secrets. "
            "Pedir a Andrés agregarla en Settings → Secrets de la app."
        )
        with st.expander("📋 ¿Cómo obtener una API key?"):
            st.markdown(
                "1. Ir a https://console.anthropic.com/\n"
                "2. Login con cuenta de UnionX\n"
                "3. Settings → API Keys → Create Key\n"
                "4. Copiar y pegar en Streamlit Cloud → app `unionx-operaciones` "
                "→ Settings → Secrets como:\n"
                "```toml\nANTHROPIC_API_KEY = \"sk-ant-...\"\n```"
            )

        # Modo fallback: queries manuales
        st.divider()
        st.markdown("### 📊 Mientras tanto: consultas directas")
        with st.expander("🔍 Costo Operativo por filtro"):
            colA, colB = st.columns(2)
            y = colA.selectbox("Año", [2025, 2026], key="man_y")
            mes_opts = ["Todos", "Q1", "Q2", "Q3", "Q4"]
            mes_sel = colB.selectbox("Período", mes_opts, key="man_m")
            sa = st.selectbox("Sub-área (opcional)",
                                ["Todas"] + ["LOGISTICA", "OPERACIONES",
                                              "POSTVENTA", "GRUPO ETER", "UNIONX"],
                                key="man_sa")
            if st.button("Consultar", type="primary"):
                m = None
                if mes_sel == "Q1":
                    m = [1, 2, 3]
                elif mes_sel == "Q2":
                    m = [4, 5, 6]
                elif mes_sel == "Q3":
                    m = [7, 8, 9]
                elif mes_sel == "Q4":
                    m = [10, 11, 12]
                result = tool_costo_operativo(
                    year=y, meses=m,
                    sub_area=sa if sa != "Todas" else None,
                )
                st.json(result)
        return

    # Importar SDK Anthropic
    try:
        import anthropic
    except ImportError:
        st.error(
            "⚠️ Falta paquete `anthropic`. Agregalo a `requirements.txt`:\n"
            "```\nanthropic>=0.39.0\n```"
        )
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Inicializar conversación
    if "ops_chat_msgs" not in st.session_state:
        st.session_state["ops_chat_msgs"] = []

    # Mostrar historial
    for msg in st.session_state["ops_chat_msgs"]:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        elif msg["role"] == "assistant":
            # content puede ser str (respuesta final) o list (con tool_use)
            with st.chat_message("assistant"):
                if isinstance(msg["content"], str):
                    st.markdown(msg["content"])
                else:
                    for block in msg["content"]:
                        if block.get("type") == "text":
                            st.markdown(block["text"])
                        elif block.get("type") == "tool_use":
                            with st.expander(f"🔧 Consultando: `{block['name']}`"):
                                st.code(json.dumps(block.get("input", {}),
                                                     indent=2, ensure_ascii=False))

    # Sugerencias rápidas
    if not st.session_state["ops_chat_msgs"]:
        st.markdown("##### 💡 Ejemplos de preguntas")
        col1, col2 = st.columns(2)
        sugerencias = [
            "¿Por qué subió tanto Logística en Q1 2026?",
            "¿Cuál es el ratio Costo/Venta YTD?",
            "Comparame REMUNERACIONES 2026 vs 2025",
            "¿Qué CC tuvo la mayor desviación Ppto vs Real?",
            "¿Cuánto gastamos en arriendos este año?",
            "¿Qué tan llena va a estar la bodega en 60 días?",
        ]
        for i, s in enumerate(sugerencias):
            col = col1 if i % 2 == 0 else col2
            if col.button(s, key=f"sug_{i}", use_container_width=True):
                st.session_state["_ops_chat_input"] = s
                st.rerun()

    # Input
    user_input = st.chat_input("Pregúntame algo sobre los números...")
    if "_ops_chat_input" in st.session_state:
        user_input = st.session_state.pop("_ops_chat_input")

    if user_input:
        # Agregar mensaje user
        st.session_state["ops_chat_msgs"].append({
            "role": "user", "content": user_input,
        })
        with st.chat_message("user"):
            st.markdown(user_input)

        # Loop tool calling
        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("⏳ Pensando...")

            messages_api = []
            for m in st.session_state["ops_chat_msgs"]:
                messages_api.append({"role": m["role"], "content": m["content"]})

            try:
                # Loop: llamar API, si tool_use ejecutar y volver, repetir
                max_iters = 6
                for _ in range(max_iters):
                    response = client.messages.create(
                        model="claude-sonnet-4-5",
                        max_tokens=2048,
                        system=SYSTEM_PROMPT,
                        tools=TOOLS_DEF,
                        messages=messages_api,
                    )

                    # ¿Hay tool_use?
                    tool_uses = [b for b in response.content if b.type == "tool_use"]
                    if not tool_uses:
                        # Respuesta final
                        text_blocks = [b.text for b in response.content if b.type == "text"]
                        final_text = "\n\n".join(text_blocks)
                        placeholder.markdown(final_text)
                        st.session_state["ops_chat_msgs"].append({
                            "role": "assistant", "content": final_text,
                        })
                        break

                    # Ejecutar cada tool_use
                    # Agregar el mensaje del assistant con tool_use al historial API
                    assistant_content = []
                    for b in response.content:
                        if b.type == "text":
                            assistant_content.append({"type": "text", "text": b.text})
                        elif b.type == "tool_use":
                            assistant_content.append({
                                "type": "tool_use", "id": b.id,
                                "name": b.name, "input": b.input,
                            })
                    messages_api.append({"role": "assistant", "content": assistant_content})

                    # Ejecutar tools
                    tool_results = []
                    for tu in tool_uses:
                        fn = TOOL_FUNCS.get(tu.name)
                        if fn is None:
                            result = {"error": f"Tool {tu.name} no existe"}
                        else:
                            try:
                                result = fn(**(tu.input or {}))
                            except Exception as e:
                                result = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
                        with st.expander(f"🔧 `{tu.name}`", expanded=False):
                            st.code(json.dumps(tu.input or {}, indent=2,
                                                  ensure_ascii=False))
                            st.code(json.dumps(result, indent=2,
                                                  ensure_ascii=False, default=str))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })

                    messages_api.append({"role": "user", "content": tool_results})
                    placeholder.markdown("⏳ Analizando data...")
                else:
                    placeholder.markdown("⚠️ Se alcanzó el límite de iteraciones de tools.")

            except Exception as e:
                placeholder.error(f"❌ Error: {type(e).__name__}: {str(e)[:300]}")
                st.session_state["ops_chat_msgs"].pop()  # quitar último user msg para retry
