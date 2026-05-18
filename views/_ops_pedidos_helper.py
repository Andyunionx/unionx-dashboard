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
    """Carga ventas históricas con cols mínimas + clasificación B2B/B2C.

    Incluye `sku`, `cantidad` y `tipo_movimiento` para poder calcular:
      - pedidos (nunique de `pedido`)
      - unidades (suma de `cantidad`, solo movimientos de venta)
      - líneas (nunique de `pedido + sku` = SKU-líneas pickeadas)
    """
    if not VENTAS_PARQUET.exists():
        return pd.DataFrame()

    cols = ["fecha_venta", "pedido", "canal", "tipo_negocio", "bodega",
            "sku", "cantidad", "tipo_movimiento"]
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


def _periodo_col(df: pd.DataFrame, granularidad: str) -> pd.Series:
    """Devuelve columna `periodo` según granularidad."""
    if granularidad == "mes":
        return df["fecha_venta"].dt.to_period("M").astype(str)
    if granularidad == "semana":
        return df["fecha_venta"].dt.to_period("W-SUN").astype(str)
    if granularidad == "dia":
        return df["fecha_venta"].dt.date.astype(str)
    raise ValueError(f"granularidad inválida: {granularidad}")


def pedidos_por_periodo(df: pd.DataFrame, granularidad: str = "mes",
                         n_periodos: int = 12,
                         metrica: str = "pedidos") -> pd.DataFrame:
    """Devuelve DataFrame pivot: periodo × {B2B, B2C, Total, % B2B}.

    granularidad: 'mes' | 'semana' | 'dia'
    n_periodos: cuántos períodos mostrar (los últimos N)
    metrica: 'pedidos' | 'unidades' | 'lineas'
      - 'pedidos': # pedidos únicos (nunique de `pedido`)
      - 'unidades': suma de `cantidad` (solo `tipo_movimiento == Venta`,
        en valor absoluto — devoluciones se cuentan pero no descuentan)
      - 'lineas': # de combinaciones únicas (pedido, sku) = líneas pickeadas
    """
    if df.empty:
        return pd.DataFrame()

    d = df.copy()
    d["periodo"] = _periodo_col(d, granularidad)

    if metrica == "pedidos":
        agg = d.groupby(["periodo", "segmento"])["pedido"].nunique()
    elif metrica == "unidades":
        # Solo movimientos de Venta, valor absoluto (devoluciones cuentan
        # como movimiento operativo aunque inviertan signo)
        d_ven = d[d["tipo_movimiento"].fillna("").str.lower() == "venta"].copy()
        if d_ven.empty:
            d_ven = d.copy()  # fallback si no hay tipo_movimiento
        d_ven["cantidad_abs"] = d_ven["cantidad"].abs()
        agg = d_ven.groupby(["periodo", "segmento"])["cantidad_abs"].sum()
    elif metrica == "lineas":
        d["lin_key"] = d["pedido"].astype(str) + "||" + d["sku"].astype(str)
        agg = d.groupby(["periodo", "segmento"])["lin_key"].nunique()
    else:
        raise ValueError(f"metrica inválida: {metrica}")

    agg = agg.reset_index(name="valor")
    pivot = agg.pivot(index="periodo", columns="segmento", values="valor").fillna(0)
    if "B2B" not in pivot.columns:
        pivot["B2B"] = 0
    if "B2C" not in pivot.columns:
        pivot["B2C"] = 0
    pivot["Total"] = pivot["B2B"] + pivot["B2C"]
    pivot["% B2B"] = (pivot["B2B"] / pivot["Total"] * 100).fillna(0).round(1)
    pivot = pivot[["B2B", "B2C", "Total", "% B2B"]]
    pivot = pivot.sort_index()
    return pivot.tail(n_periodos)


def kpis_volumen_por_periodo(df: pd.DataFrame, granularidad: str = "mes",
                                n_periodos: int = 12) -> pd.DataFrame:
    """Devuelve DataFrame combinado con TODAS las métricas por período.

    Columnas: B2B_Ped, B2C_Ped, Total_Ped, B2B_Un, B2C_Un, Total_Un,
              B2B_Lin, B2C_Lin, Total_Lin, % B2B (sobre pedidos)
    """
    if df.empty:
        return pd.DataFrame()

    p_ped = pedidos_por_periodo(df, granularidad, n_periodos, "pedidos")
    p_un = pedidos_por_periodo(df, granularidad, n_periodos, "unidades")
    p_lin = pedidos_por_periodo(df, granularidad, n_periodos, "lineas")

    out = pd.DataFrame(index=p_ped.index)
    out["Pedidos B2B"] = p_ped["B2B"]
    out["Pedidos B2C"] = p_ped["B2C"]
    out["Pedidos Total"] = p_ped["Total"]
    out["Unidades B2B"] = p_un["B2B"]
    out["Unidades B2C"] = p_un["B2C"]
    out["Unidades Total"] = p_un["Total"]
    out["Líneas B2B"] = p_lin["B2B"]
    out["Líneas B2C"] = p_lin["B2C"]
    out["Líneas Total"] = p_lin["Total"]
    out["% B2B (pedidos)"] = p_ped["% B2B"]
    return out


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
