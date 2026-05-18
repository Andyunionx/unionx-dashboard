"""
Helper para KPI "Total Pedidos por período (B2B vs B2C)" en la app de
Operaciones (tab Resumen de KPIs WMS).

FUENTE PRINCIPAL: módulo de inventario de Odoo (stock.picking + stock.move).
FUENTE FALLBACK: data/historico/ventas_historico.parquet (snapshot ventas).

DIFERENCIA TIEMPOS:
  - Ventas (parquet): momento en que se registra/factura la venta
  - Inventario (Odoo): momento real del picking/despacho (date_done)
  Para KPIs operativos de productividad, lo correcto es Odoo.

REGLA CORREGIDA tras feedback de Andrés (18/may):

  "Pedidos" = solo picking_type_code='outgoing' (despachos al cliente).
  Los 'internal' (olas internas entre bodegas) NO son pedidos, son
  movimientos operativos.

  Para CADA outgoing, B2B/B2C se decide POR PARTNER (no por picking_type):
    B2B si partner_name contiene retailers conocidos:
      - Falabella Retail / Tienda
      - Walmart Retail / Tienda
      - Paris (Cencosud) Retail / Tienda
      - Ripley Retail / Tienda
      - Dimarsa
      - El Volcán
      - UnionX B2B
      - SP Digital, Hites, La Polar (otros retailers chilenos)
    B2C = todo lo demás (persona natural, marketplace consumer, web).

  IMPORTANTE: outgoing desde "Bodega Fulfillment Mercado Libre" al
  cliente final = B2C (es el despacho al consumidor del marketplace,
  no a ML como empresa). Antes los marcaba B2B incorrectamente.

  Las "olas internas" a fulfillment (picking_type_code='internal' con
  destino bodega Fulfillment ML/Falabella/etc.) se cuentan como
  MOVIMIENTOS OPERATIVOS B2B aparte, no como pedidos.
"""
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENTAS_PARQUET = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"
VOLUMEN_HIST_PARQUET = PROJECT_ROOT / "data" / "operaciones" / "volumen_inventario_hist.parquet"
VOLUMEN_HIST_RESUMEN = PROJECT_ROOT / "data" / "operaciones" / "volumen_inventario_hist_resumen.json"

# Cuántos días recientes consultamos en vivo a Odoo (los anteriores vienen
# del parquet histórico — se actualiza por cron diario/semanal)
DIAS_VIVO_ODOO = 7


# ============================================================
# REGLAS B2B
# ============================================================
# Para fuente PARQUET (campos: canal, tipo_negocio, bodega)
BODEGAS_FULFILLMENT_B2B = {
    "BODEGA FULFILLMENT MERCADO LIBRE",
    "BODEGA FULFILLMENT FALABELLA",
    "BODEGA FULFILLMENT PARIS",
    "BODEGA FULFILLMENT RIPLEY",
    "BODEGA FULFILLMENT WALMART",
}
CANALES_B2B_EXPLICITOS = {
    "UNIONX B2B", "EL VOLCAN", "EL VOLCÁN", "DIMARSA",
    "FALABELLA TIENDA", "PARIS TIENDA", "WALMART TIENDA", "RIPLEY TIENDA",
}
B2B_TIPOS_NEGOCIO = {"distribución", "distribucion", "corporativo"}

# Para fuente ODOO — solo se usa partner_name para clasificar outgoing.
# Las olas internas (picking_type_code='internal' con destino bodega
# Fulfillment XXX) se cuentan como B2B aparte (ver bodegas_internas_b2b).
KEYWORDS_PARTNER_B2B = [
    # Retailers chilenos (envío B2B directo)
    "FALABELLA RETAIL", "FALABELLA TIENDA",
    "WALMART RETAIL", "WALMART TIENDA",
    "CENCOSUD", "PARIS RETAIL", "PARIS TIENDA",
    "RIPLEY RETAIL", "RIPLEY TIENDA",
    "DIMARSA", "EL VOLCAN", "EL VOLCÁN",
    "UNIONX B2B", "UNION X B2B",
    "HITES", "LA POLAR", "SP DIGITAL", "ABC DIN",
    "SODIMAC CORP",
]

# Bodegas de destino que indican "ola interna B2B" (picking_type='internal')
BODEGAS_DESTINO_FULFILLMENT_B2B = [
    "FULFILLMENT MERCADO LIBRE",
    "FULFILLMENT FALABELLA",
    "FULFILLMENT PARIS",
    "FULFILLMENT RIPLEY",
    "FULFILLMENT WALMART",
]


# ============================================================
# CLASIFICADORES
# ============================================================
def clasificar_segmento(canal, tipo_negocio, bodega=None) -> str:
    """Clasificación B2B/B2C para fuente PARQUET (legacy fallback)."""
    bodega_u = str(bodega or "").upper().strip()
    canal_u = str(canal or "").upper().strip()
    tipo_l = str(tipo_negocio or "").lower().strip()

    if bodega_u in BODEGAS_FULFILLMENT_B2B:
        return "B2B"
    if canal_u in CANALES_B2B_EXPLICITOS:
        return "B2B"
    if "B2B" in canal_u:
        return "B2B"
    if tipo_l in B2B_TIPOS_NEGOCIO:
        return "B2B"
    return "B2C"


def clasificar_segmento_picking(picking_type_name, partner_name,
                                  picking_type_code=None) -> str:
    """Clasificación B2B/B2C para fuente ODOO.

    Regla CORREGIDA (18/may):
      - Solo aplica a OUTGOING (despachos al cliente).
      - B2B = partner es retailer (Falabella Retail, Walmart, etc.).
      - B2C = todos los demás outgoing (consumer final).
      - INTERNAL → segmento 'INTERNAL_B2B' (movimientos operativos, no
        son pedidos del cliente; se cuentan aparte como volumen B2B).
    """
    code = str(picking_type_code or "").lower().strip()
    pt_u = str(picking_type_name or "").upper().strip()
    pn_u = str(partner_name or "").upper().strip()

    # Internal = movimiento operativo, no es pedido
    if code == "internal":
        # Si el destino es fulfillment de retailer → es ola B2B operativa
        for kw in BODEGAS_DESTINO_FULFILLMENT_B2B:
            if kw in pt_u:
                return "INTERNAL_B2B"
        return "INTERNAL_OTRO"

    # Outgoing: clasificar por partner
    for kw in KEYWORDS_PARTNER_B2B:
        if kw in pn_u:
            return "B2B"
    return "B2C"


# ============================================================
# FUENTE 1A: PARQUET HISTÓRICO (rápido, se actualiza por cron)
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
def cargar_volumen_historico_parquet() -> tuple[pd.DataFrame, dict]:
    """Carga el snapshot histórico de pickings (generado por
    extract_volumen_inventario.py). Cache 1h en memoria.

    Devuelve `df` con TODOS los pickings (outgoing + internal) más:
      - segmento: B2B | B2C | INTERNAL_B2B | INTERNAL_OTRO
      - es_pedido: True si es outgoing (= pedido del cliente)

    Retorna (df, resumen) donde resumen tiene fecha_hasta, etc.
    """
    import json as _json
    if not VOLUMEN_HIST_PARQUET.exists():
        return pd.DataFrame(), {}
    df = pd.read_parquet(VOLUMEN_HIST_PARQUET)
    df["fecha_done"] = pd.to_datetime(df["fecha_done"], errors="coerce")
    if "picking_type_code" not in df.columns:
        df["picking_type_code"] = ""
    # Clasificación se aplica acá (el parquet no la trae para mantenerlo "raw")
    df["segmento"] = df.apply(
        lambda r: clasificar_segmento_picking(
            r["picking_type_name"], r["partner_name"],
            picking_type_code=r.get("picking_type_code", "")),
        axis=1,
    )
    df["es_pedido"] = df["picking_type_code"].astype(str).str.lower() == "outgoing"
    resumen = {}
    if VOLUMEN_HIST_RESUMEN.exists():
        try:
            resumen = _json.load(open(VOLUMEN_HIST_RESUMEN, encoding="utf-8"))
        except Exception:
            pass
    return df, resumen


# ============================================================
# FUENTE 1B: ODOO ÚLTIMOS N DÍAS (rápido, en vivo)
# ============================================================
@st.cache_data(ttl=1800, show_spinner="📦 Consultando Odoo (últimos días)...")
def cargar_volumen_ultimos_dias_odoo(dias: int = 7,
                                       desde_iso: str = None) -> pd.DataFrame:
    """Consulta Odoo pickings DONE de los últimos N días (ventana chica
    para mantener bajo el tiempo de respuesta). Cache 30 min.

    Si `desde_iso` se pasa explícito (ej: día siguiente al fin del parquet
    histórico), se usa en lugar de hoy-dias.
    """
    from views._ops_odoo_helper import get_ops_odoo_client

    odoo = get_ops_odoo_client()
    if odoo is None:
        return pd.DataFrame()

    try:
        if desde_iso:
            desde = desde_iso
        else:
            desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        hasta = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        pickings = odoo.search_read(
            "stock.picking",
            [("state", "=", "done"),
             ("date_done", ">=", desde),
             ("date_done", "<", hasta),
             ("picking_type_code", "in", ["outgoing", "internal"])],
            ["id", "name", "date_done", "picking_type_id", "partner_id",
             "picking_type_code"],
            limit=50000,
        )
        if not pickings:
            return pd.DataFrame()

        df_p = pd.DataFrame(pickings)
        df_p["picking_id"] = df_p["id"]
        df_p["fecha_done"] = pd.to_datetime(df_p["date_done"], errors="coerce")
        df_p["picking_type_name"] = df_p["picking_type_id"].apply(
            lambda x: x[1] if isinstance(x, list) and len(x) > 1 else "")
        df_p["partner_name"] = df_p["partner_id"].apply(
            lambda x: x[1] if isinstance(x, list) and len(x) > 1 else "")
        df_p["segmento"] = df_p.apply(
            lambda r: clasificar_segmento_picking(
                r["picking_type_name"], r["partner_name"],
                picking_type_code=r.get("picking_type_code", "")),
            axis=1,
        )
        df_p["es_pedido"] = df_p["picking_type_code"].astype(str).str.lower() == "outgoing"

        # Moves agregados (chunked)
        pids = df_p["picking_id"].tolist()
        chunk_size = 1000
        moves_agg = []
        for i in range(0, len(pids), chunk_size):
            chunk = pids[i:i + chunk_size]
            try:
                rg = odoo._execute_with_retry(
                    "read_group",
                    "stock.move",
                    [("picking_id", "in", chunk), ("state", "=", "done")],
                    {"fields": ["picking_id", "product_uom_qty:sum"],
                     "groupby": ["picking_id"], "lazy": False},
                )
                for r in rg:
                    pid_raw = r.get("picking_id")
                    pid_val = pid_raw[0] if isinstance(pid_raw, list) else pid_raw
                    moves_agg.append({
                        "picking_id": pid_val,
                        "n_lineas": r.get("__count", r.get("picking_id_count", 0)),
                        "n_unidades": r.get("product_uom_qty", 0) or 0,
                    })
            except Exception:
                continue

        df_m = pd.DataFrame(moves_agg) if moves_agg else pd.DataFrame(
            columns=["picking_id", "n_lineas", "n_unidades"])

        df = df_p.merge(df_m, on="picking_id", how="left")
        df["n_lineas"] = df["n_lineas"].fillna(0).astype(int)
        df["n_unidades"] = df["n_unidades"].fillna(0)

        return df[["picking_id", "fecha_done", "picking_type_name",
                   "partner_name", "picking_type_code", "segmento",
                   "es_pedido", "n_unidades", "n_lineas"]]

    except Exception as e:
        st.warning(f"⚠️ Error consultando Odoo en vivo: {type(e).__name__}: "
                   f"{str(e)[:120]}")
        return pd.DataFrame()


# ============================================================
# FUENTE 1: HÍBRIDA (parquet histórico + Odoo últimos días)
# ============================================================
def cargar_volumen_hibrido() -> tuple[pd.DataFrame, dict]:
    """Combina parquet histórico (rápido) + Odoo últimos días (en vivo).

    Retorna (df, info) donde info contiene:
      - fuente: 'hibrido' | 'solo_parquet' | 'solo_odoo'
      - corte_hist: fecha_hasta del parquet
      - filas_hist: # pickings del parquet
      - filas_vivo: # pickings consultados en vivo
      - generado_hist: timestamp del parquet
    """
    df_hist, resumen_hist = cargar_volumen_historico_parquet()
    info = {
        "fuente": "ninguna",
        "corte_hist": resumen_hist.get("rango_hasta"),
        "filas_hist": int(len(df_hist)),
        "filas_vivo": 0,
        "generado_hist": resumen_hist.get("generado_en"),
    }

    # Determinar desde cuándo consultar en vivo
    if not df_hist.empty and resumen_hist.get("rango_hasta"):
        # Desde el día siguiente al corte del parquet
        try:
            corte = datetime.strptime(
                resumen_hist["rango_hasta"], "%Y-%m-%d",
            ).date()
            desde_vivo = corte.strftime("%Y-%m-%d")
        except Exception:
            desde_vivo = None
    else:
        desde_vivo = None

    df_vivo = cargar_volumen_ultimos_dias_odoo(
        dias=DIAS_VIVO_ODOO, desde_iso=desde_vivo,
    )
    info["filas_vivo"] = int(len(df_vivo))

    # Combinar
    if not df_hist.empty and not df_vivo.empty:
        df_out = pd.concat([df_hist, df_vivo], ignore_index=True)
        df_out = df_out.drop_duplicates(subset=["picking_id"], keep="last")
        info["fuente"] = "hibrido"
    elif not df_hist.empty:
        df_out = df_hist
        info["fuente"] = "solo_parquet"
    elif not df_vivo.empty:
        df_out = df_vivo
        info["fuente"] = "solo_odoo"
    else:
        df_out = pd.DataFrame()
    return df_out, info


# Compat: alias retro para evitar romper imports si alguien lo usa
def cargar_volumen_inventario_odoo(meses_atras: int = 12) -> pd.DataFrame:
    """[deprecado] Antes consultaba 12 meses en vivo. Ahora usa híbrido."""
    df, _info = cargar_volumen_hibrido()
    return df


# ============================================================
# FUENTE 2: PARQUET (FALLBACK / legacy ventas)
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def cargar_ventas_para_pedidos() -> pd.DataFrame:
    """Carga ventas históricas con cols mínimas + clasificación B2B/B2C.

    [DEPRECADO — usar cargar_volumen_inventario_odoo()]
    Mantengo como fallback si Odoo no responde.
    """
    if not VENTAS_PARQUET.exists():
        return pd.DataFrame()

    cols = ["fecha_venta", "pedido", "canal", "tipo_negocio", "bodega",
            "sku", "cantidad", "tipo_movimiento"]
    df = pd.read_parquet(VENTAS_PARQUET, columns=cols)
    df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce")
    df = df.dropna(subset=["fecha_venta", "pedido"]).copy()

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


# ============================================================
# AGREGADORES POR PERÍODO (unificados para ambas fuentes)
# ============================================================
def _periodo_col(serie_fecha: pd.Series, granularidad: str) -> pd.Series:
    """Convierte una serie de fechas en un string de período."""
    if granularidad == "mes":
        return serie_fecha.dt.to_period("M").astype(str)
    if granularidad == "semana":
        return serie_fecha.dt.to_period("W-SUN").astype(str)
    if granularidad == "dia":
        return serie_fecha.dt.date.astype(str)
    raise ValueError(f"granularidad inválida: {granularidad}")


def pedidos_por_periodo(df: pd.DataFrame, granularidad: str = "mes",
                         n_periodos: int = 12,
                         metrica: str = "pedidos") -> pd.DataFrame:
    """Devuelve DataFrame pivot: periodo × {B2B, B2C, Total, % B2B}.

    Soporta ambas fuentes — detecta automáticamente:
      - Odoo: cols [picking_id, fecha_done, n_unidades, n_lineas, segmento]
      - Parquet: cols [pedido, fecha_venta, sku, cantidad, segmento]

    metrica: 'pedidos' | 'unidades' | 'lineas'
    """
    if df.empty:
        return pd.DataFrame()

    es_odoo = "picking_id" in df.columns

    d = df.copy()
    if es_odoo:
        d["periodo"] = _periodo_col(d["fecha_done"], granularidad)
        # CRÍTICO: solo outgoing cuenta como "pedido". Los internal son
        # movimientos operativos (se ven en otra métrica/tab).
        if "es_pedido" in d.columns:
            d = d[d["es_pedido"]].copy()
        elif "picking_type_code" in d.columns:
            d = d[d["picking_type_code"].astype(str).str.lower() == "outgoing"].copy()
    else:
        d["periodo"] = _periodo_col(d["fecha_venta"], granularidad)

    if metrica == "pedidos":
        if es_odoo:
            agg = d.groupby(["periodo", "segmento"])["picking_id"].nunique()
        else:
            agg = d.groupby(["periodo", "segmento"])["pedido"].nunique()
    elif metrica == "unidades":
        if es_odoo:
            agg = d.groupby(["periodo", "segmento"])["n_unidades"].sum()
        else:
            d_ven = d[d["tipo_movimiento"].fillna("").str.lower() == "venta"].copy()
            if d_ven.empty:
                d_ven = d.copy()
            d_ven["cantidad_abs"] = d_ven["cantidad"].abs()
            agg = d_ven.groupby(["periodo", "segmento"])["cantidad_abs"].sum()
    elif metrica == "lineas":
        if es_odoo:
            agg = d.groupby(["periodo", "segmento"])["n_lineas"].sum()
        else:
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
    """Tabla combinada con las 3 métricas: Pedidos, Unidades, Líneas."""
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


# ============================================================
# AUDITORÍA (detalle para validar regla)
# ============================================================
def detalle_canales_por_segmento(df: pd.DataFrame, year: int = None,
                                   month: int = None) -> pd.DataFrame:
    """Detalle por (canal/picking_type × bodega/partner × segmento)."""
    if df.empty:
        return pd.DataFrame()
    es_odoo = "picking_id" in df.columns
    d = df.copy()
    fecha_col = "fecha_done" if es_odoo else "fecha_venta"

    if year is not None:
        d = d[d[fecha_col].dt.year == year]
    if month is not None:
        d = d[d[fecha_col].dt.month == month]
    if d.empty:
        return pd.DataFrame()

    if es_odoo:
        # Para auditoría mostramos TODOS los pickings (outgoing + internal)
        # para que se vea cómo se clasifican incluso los internal.
        agg = d.groupby(
            ["segmento", "picking_type_name", "partner_name"], dropna=False,
        )["picking_id"].nunique().reset_index(name="n_pedidos")
        agg = agg.rename(columns={
            "picking_type_name": "Picking Type",
            "partner_name": "Partner",
        })
    else:
        agg = d.groupby(
            ["segmento", "canal", "bodega"], dropna=False,
        )["pedido"].nunique().reset_index(name="n_pedidos")
        agg = agg.rename(columns={"canal": "Canal", "bodega": "Bodega"})

    agg = agg[agg["n_pedidos"] > 0].sort_values(
        ["segmento", "n_pedidos"], ascending=[True, False],
    )
    return agg


# ============================================================
# LOADER UNIFICADO (Odoo > parquet)
# ============================================================
def cargar_volumen_unificado(meses_atras: int = 12) -> tuple[pd.DataFrame, str]:
    """Intenta Odoo primero. Si falla, cae al parquet.

    Retorna (df, fuente) donde fuente es 'odoo_inventario' o 'parquet_ventas'.
    """
    df = cargar_volumen_inventario_odoo(meses_atras=meses_atras)
    if not df.empty:
        return df, "odoo_inventario"
    df = cargar_ventas_para_pedidos()
    if not df.empty:
        return df, "parquet_ventas"
    return pd.DataFrame(), "ninguna"
