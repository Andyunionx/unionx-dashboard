"""
Helper para KPI "Total Pedidos por período (B2B vs B2C)" en la app de
Operaciones (tab Resumen de KPIs WMS).

Lee `data/historico/ventas_historico.parquet` y agrega pedidos únicos
por (mes / semana / día) separando B2B y B2C.

REGLA B2B / B2C (no hay flag directo en el parquet; se infiere):
  B2B = canal contiene 'B2B' OR tipo_negocio ∈ {Distribución, Corporativo}
  B2C = todo lo demás (Marketplace, Páginas propias, Fidelización, Marketing)

Rationale:
  - 'Distribución' = venta mayorista a distribuidores → B2B
  - 'Corporativo' = ventas a empresas (regalos corporativos, ofertas) → B2B
  - 'UnionX B2B' = literal en el nombre del canal
  - Marketplace (ML, Falabella, Walmart, Paris) = retail consumer → B2C
  - Páginas propias (web) = mayoría consumer final → B2C
  - Fidelización = programas con clientes finales → B2C
"""
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENTAS_PARQUET = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"


# Tipos de negocio considerados B2B
B2B_TIPOS_NEGOCIO = {"distribución", "distribucion", "corporativo"}


def clasificar_segmento(canal, tipo_negocio) -> str:
    """Devuelve 'B2B' o 'B2C' según regla."""
    c = str(canal or "").lower()
    t = str(tipo_negocio or "").lower().strip()
    if "b2b" in c or t in B2B_TIPOS_NEGOCIO:
        return "B2B"
    return "B2C"


@st.cache_data(ttl=600, show_spinner=False)
def cargar_ventas_para_pedidos() -> pd.DataFrame:
    """Carga ventas históricas con cols mínimas + clasificación B2B/B2C."""
    if not VENTAS_PARQUET.exists():
        return pd.DataFrame()

    df = pd.read_parquet(
        VENTAS_PARQUET,
        columns=["fecha_venta", "pedido", "canal", "tipo_negocio"],
    )
    df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce")
    df = df.dropna(subset=["fecha_venta", "pedido"]).copy()
    df["segmento"] = df.apply(
        lambda r: clasificar_segmento(r.get("canal"), r.get("tipo_negocio")),
        axis=1,
    )
    return df


def pedidos_por_periodo(df: pd.DataFrame, granularidad: str = "mes",
                         n_periodos: int = 12) -> pd.DataFrame:
    """Devuelve DataFrame pivot: periodo × {B2B, B2C, Total}.

    granularidad: 'mes' | 'semana' | 'dia'
    n_periodos: cuántos períodos mostrar (los últimos N)
    """
    if df.empty:
        return pd.DataFrame()

    d = df.copy()
    if granularidad == "mes":
        d["periodo"] = d["fecha_venta"].dt.to_period("M").astype(str)
    elif granularidad == "semana":
        # Lunes de la semana (formato YYYY-Www)
        d["periodo"] = d["fecha_venta"].dt.to_period("W-SUN").astype(str)
    elif granularidad == "dia":
        d["periodo"] = d["fecha_venta"].dt.date.astype(str)
    else:
        raise ValueError(f"granularidad inválida: {granularidad}")

    # Pedidos únicos por (periodo, segmento)
    agg = d.groupby(["periodo", "segmento"])["pedido"].nunique().reset_index(name="n_pedidos")

    # Pivot ancho
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
