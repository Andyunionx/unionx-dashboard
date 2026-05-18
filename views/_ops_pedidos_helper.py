"""
Helper para KPI "Total Pedidos por período (B2B vs B2C)" en la app de
Operaciones (tab Resumen de KPIs WMS).

Lee `data/historico/ventas_historico.parquet` y agrega pedidos únicos
por (mes / semana / día) separando B2B y B2C.

REGLA B2B / B2C (definida por Andrés, no hay flag directo en el parquet):

  B2B si:
    1. bodega ∈ {Bodega Fulfillment ML / Falabella / Paris / Ripley / Walmart}
       → movimientos internos a bodegas fulfillment externas
    2. canal ∈ {UnionX B2B, El Volcan, Dimarsa, Falabella tienda,
                Paris tienda, Walmart tienda, Ripley tienda}
       → venta directa a retailers (Falabella Retail, Cencosud Retail,
         Walmart Retail) + B2B explícito
    3. canal contiene 'B2B' (catch-all para variantes futuras)
    4. tipo_negocio ∈ {Distribución, Corporativo}

  B2C = todo lo demás
"""
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENTAS_PARQUET = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"


# ============================================================
# REGLAS B2B (case-insensitive — se normalizan a UPPER al comparar)
# ============================================================
BODEGAS_FULFILLMENT_B2B = {
    "BODEGA FULFILLMENT MERCADO LIBRE",
    "BODEGA FULFILLMENT FALABELLA",
    "BODEGA FULFILLMENT PARIS",
    "BODEGA FULFILLMENT RIPLEY",
    "BODEGA FULFILLMENT WALMART",
}

CANALES_B2B_EXPLICITOS = {
    "UNIONX B2B",
    "EL VOLCAN",
    "EL VOLCÁN",
    "DIMARSA",
    "FALABELLA TIENDA",   # Falabella Retail
    "PARIS TIENDA",       # Paris/Cencosud Retail
    "WALMART TIENDA",     # Walmart Retail
    "RIPLEY TIENDA",
}

B2B_TIPOS_NEGOCIO = {"distribución", "distribucion", "corporativo"}


def clasificar_segmento(canal, tipo_negocio, bodega=None) -> str:
    """Devuelve 'B2B' o 'B2C' según la regla operativa de Andrés."""
    bodega_u = str(bodega or "").upper().strip()
    canal_u = str(canal or "").upper().strip()
    tipo_l = str(tipo_negocio or "").lower().strip()

    # Regla 1: bodega de fulfillment externo → B2B
    if bodega_u in BODEGAS_FULFILLMENT_B2B:
        return "B2B"
    # Regla 2: canal B2B explícito
    if canal_u in CANALES_B2B_EXPLICITOS:
        return "B2B"
    # Regla 3: canal contiene 'B2B'
    if "B2B" in canal_u:
        return "B2B"
    # Regla 4: tipo_negocio mayorista
    if tipo_l in B2B_TIPOS_NEGOCIO:
        return "B2B"
    return "B2C"


@st.cache_data(ttl=600, show_spinner=False)
def cargar_ventas_para_pedidos() -> pd.DataFrame:
    """Carga ventas históricas con cols mínimas + clasificación B2B/B2C."""
    if not VENTAS_PARQUET.exists():
        return pd.DataFrame()

    cols = ["fecha_venta", "pedido", "canal", "tipo_negocio", "bodega"]
    df = pd.read_parquet(VENTAS_PARQUET, columns=cols)
    df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce")
    df = df.dropna(subset=["fecha_venta", "pedido"]).copy()

    # Vectorizado (más rápido que apply para 400K filas)
    bodega_u = df["bodega"].fillna("").astype(str).str.upper().str.strip()
    canal_u = df["canal"].fillna("").astype(str).str.upper().str.strip()
    tipo_l = df["tipo_negocio"].fillna("").astype(str).str.lower().str.strip()

    es_b2b = (
        bodega_u.isin(BODEGAS_FULFILLMENT_B2B)
        | canal_u.isin(CANALES_B2B_EXPLICITOS)
        | canal_u.str.contains("B2B", na=False)
        | tipo_l.isin(B2B_TIPOS_NEGOCIO)
    )
    df["segmento"] = es_b2b.map({True: "B2B", False: "B2C"})
    return df


def pedidos_por_periodo(df: pd.DataFrame, granularidad: str = "mes",
                         n_periodos: int = 12) -> pd.DataFrame:
    """Devuelve DataFrame pivot: periodo × {B2B, B2C, Total, % B2B}.

    granularidad: 'mes' | 'semana' | 'dia'
    n_periodos: cuántos períodos mostrar (los últimos N)
    """
    if df.empty:
        return pd.DataFrame()

    d = df.copy()
    if granularidad == "mes":
        d["periodo"] = d["fecha_venta"].dt.to_period("M").astype(str)
    elif granularidad == "semana":
        d["periodo"] = d["fecha_venta"].dt.to_period("W-SUN").astype(str)
    elif granularidad == "dia":
        d["periodo"] = d["fecha_venta"].dt.date.astype(str)
    else:
        raise ValueError(f"granularidad inválida: {granularidad}")

    agg = d.groupby(["periodo", "segmento"])["pedido"].nunique().reset_index(name="n_pedidos")
    pivot = agg.pivot(index="periodo", columns="segmento", values="n_pedidos").fillna(0)
    if "B2B" not in pivot.columns:
        pivot["B2B"] = 0
    if "B2C" not in pivot.columns:
        pivot["B2C"] = 0
    pivot["Total"] = pivot["B2B"] + pivot["B2C"]
    pivot["% B2B"] = (pivot["B2B"] / pivot["Total"] * 100).fillna(0).round(1)
    pivot = pivot[["B2B", "B2C", "Total", "% B2B"]]
    pivot = pivot.sort_index()
    return pivot.tail(n_periodos)


def detalle_canales_por_segmento(df: pd.DataFrame, year: int = None,
                                   month: int = None) -> pd.DataFrame:
    """Devuelve detalle de pedidos por (canal, bodega, segmento) para
    auditar la clasificación. Útil para validar la regla en la UI."""
    if df.empty:
        return pd.DataFrame()
    d = df.copy()
    if year is not None:
        d = d[d["fecha_venta"].dt.year == year]
    if month is not None:
        d = d[d["fecha_venta"].dt.month == month]
    if d.empty:
        return pd.DataFrame()

    agg = d.groupby(["segmento", "canal", "bodega"], dropna=False)["pedido"].nunique().reset_index(
        name="n_pedidos",
    )
    agg = agg[agg["n_pedidos"] > 0].sort_values(
        ["segmento", "n_pedidos"], ascending=[True, False],
    )
    return agg
