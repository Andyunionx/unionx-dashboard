"""
Lector de parquets WMS raw (extraídos por extract_wms_raw.py 1x/día).

Concepto: la app NO consulta Odoo en runtime. Lee parquets locales
con la base de datos completa de los últimos 180 días.

Calcula KPIs en memoria con pandas (instantáneo, ~10ms).
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "wms_raw"


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_metadata() -> Dict:
    """Lee metadata.json con info de la última extracción."""
    p = RAW_DIR / "metadata.json"
    if not p.exists():
        return {"error": "metadata.json no existe — corré extract_wms_raw.py"}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def status() -> Dict:
    """Status de la data raw para mostrar en UI."""
    meta = cargar_metadata()
    if "error" in meta:
        return {"existe": False, "fresco": False, "leyenda": f"❌ {meta['error']}"}
    gen = meta.get("generado_en")
    try:
        gen_dt = datetime.fromisoformat(gen)
        edad_h = (datetime.now() - gen_dt).total_seconds() / 3600
    except Exception:
        edad_h = None
    fresco = edad_h is not None and edad_h <= 26  # margen para job 1x/día
    return {
        "existe": True,
        "fresco": fresco,
        "edad_horas": round(edad_h, 1) if edad_h is not None else None,
        "generado_en": gen,
        "leyenda": (f"📦 Data {gen[:16]} ({edad_h:.0f}h atrás)" if fresco
                    else f"⚠️ Data desactualizada ({edad_h:.0f}h)"),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def df_pickings() -> pd.DataFrame:
    p = RAW_DIR / "pickings.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    # Convertir fechas
    for col in ["scheduled_date", "date_done"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def df_moves() -> pd.DataFrame:
    p = RAW_DIR / "moves.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def df_sale_orders() -> pd.DataFrame:
    p = RAW_DIR / "sale_orders.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if "date_order" in df.columns:
        df["date_order"] = pd.to_datetime(df["date_order"], errors="coerce")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def df_scraps() -> pd.DataFrame:
    p = RAW_DIR / "scraps.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if "date_done" in df.columns:
        df["date_done"] = pd.to_datetime(df["date_done"], errors="coerce")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def df_ajustes_inv() -> pd.DataFrame:
    p = RAW_DIR / "ajustes_inv.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


# ============================================================
# CÁLCULOS DE KPIs (en memoria, no toca Odoo)
# ============================================================
def kpi_otif(dias: int = 30, canal_b2b: bool = False,
             es_company_partner: Dict[int, bool] = None) -> Dict:
    """OTIF calculado desde parquets en memoria."""
    df_p = df_pickings()
    if df_p.empty:
        return {"error": "Sin pickings raw"}
    desde = pd.Timestamp.now() - pd.Timedelta(days=dias)
    f = df_p[(df_p["date_done"] >= desde) &
             (df_p["picking_type_code"] == "outgoing") &
             (df_p["state"] == "done")].copy()
    # Filtrar B2B/B2C: si no tenemos info de partner, asumimos todos B2C
    # (en el snapshot original se hacía con partner_id.is_company al hacer search)
    # Para v1, como aproximación usamos todos los pickings (sin filtro de canal)
    # TODO: en extract_wms_raw agregar res.partner.is_company para cada partner_id
    if f.empty:
        return {"valor": None, "error": "Sin pickings en ventana"}

    on_time_count = (f["date_done"].dt.date <= f["scheduled_date"].dt.date).sum()
    total = len(f)

    # In-full: ver moves de cada picking
    df_m = df_moves()
    if df_m.empty or "picking_id_id" not in df_m.columns:
        in_full_count = 0
        both = 0
    else:
        moves_in_window = df_m[df_m["picking_id_id"].isin(f["id"])]
        # Por picking: in_full si todos los moves cumplieron quantity >= product_uom_qty
        moves_in_window = moves_in_window.copy()
        moves_in_window["ok"] = (
            (moves_in_window["quantity"].fillna(0) >=
             moves_in_window["product_uom_qty"].fillna(0))
        )
        in_full_pids = (
            moves_in_window.groupby("picking_id_id")["ok"].all()
            .pipe(lambda s: s[s].index.tolist())
        )
        in_full_count = len(in_full_pids)
        # Both: on-time AND in-full
        f["on_time"] = f["date_done"].dt.date <= f["scheduled_date"].dt.date
        both = f[f["on_time"] & f["id"].isin(in_full_pids)].shape[0]

    return {
        "valor": both / total if total else None,
        "total_pickings": int(total),
        "on_time": int(on_time_count),
        "on_time_pct": on_time_count / total if total else 0,
        "in_full": int(in_full_count),
        "in_full_pct": in_full_count / total if total else 0,
        "both": int(both),
        "error": None,
    }


def kpi_pick_accuracy(dias: int = 30) -> Dict:
    """Pick Accuracy desde parquet moves."""
    df = df_moves()
    if df.empty:
        return {"error": "Sin moves raw"}
    desde = pd.Timestamp.now() - pd.Timedelta(days=dias)
    # Filtrar outgoing en ventana
    pt_outgoing = df[df.get("picking_type_id_name", "").astype(str).str.contains(
        "out|deliver|dispatch", case=False, na=False)] if "picking_type_id_name" in df.columns else df
    f = pt_outgoing[(pt_outgoing["date"] >= desde) &
                    (pt_outgoing["state"] == "done")].copy()
    if f.empty:
        return {"valor": None, "error": "Sin moves en ventana"}
    f["ok"] = f["quantity"].fillna(0) == f["product_uom_qty"].fillna(0)
    ok = int(f["ok"].sum())
    total = len(f)
    return {
        "valor": ok / total if total else None,
        "ok": ok,
        "total": int(total),
        "errores": int(total - ok),
        "error": None,
    }


def kpi_tiempo_recepcion(dias: int = 90) -> Dict:
    """Tiempo recepción promedio desde parquet pickings."""
    df = df_pickings()
    if df.empty:
        return {"error": "Sin pickings raw"}
    desde = pd.Timestamp.now() - pd.Timedelta(days=dias)
    f = df[(df["date_done"] >= desde) &
           (df["picking_type_code"] == "incoming") &
           (df["state"] == "done") &
           df["scheduled_date"].notna()].copy()
    if f.empty:
        return {"valor": None, "error": "Sin recepciones en ventana"}
    f["horas"] = (f["date_done"] - f["scheduled_date"]).dt.total_seconds() / 3600
    # Filtrar outliers
    f = f[(f["horas"] >= -240) & (f["horas"] <= 720)]
    if f.empty:
        return {"valor": None, "error": "Sin datos válidos"}
    return {
        "valor": float(f["horas"].mean()),
        "n_recepciones": int(len(f)),
        "min": float(f["horas"].min()),
        "max": float(f["horas"].max()),
        "error": None,
    }


def kpi_volumen_movimientos(dias: int = 30) -> Dict:
    """Volumen movs por tipo desde parquet pickings."""
    df = df_pickings()
    if df.empty:
        return {"error": "Sin pickings raw"}
    desde = pd.Timestamp.now() - pd.Timedelta(days=dias)
    f = df[(df["date_done"] >= desde) & (df["state"] == "done")]
    counts = f["picking_type_code"].value_counts().to_dict()
    return {
        "incoming": int(counts.get("incoming", 0)),
        "outgoing": int(counts.get("outgoing", 0)),
        "internal": int(counts.get("internal", 0)),
        "total": int(sum(counts.values())),
        "error": None,
    }


def kpi_ofr(dias: int = 30) -> Dict:
    """Order Fulfillment Rate: % SO con pickings 100% completados."""
    df_so = df_sale_orders()
    df_p = df_pickings()
    if df_so.empty:
        return {"error": "Sin sale.orders raw"}
    desde = pd.Timestamp.now() - pd.Timedelta(days=dias)
    f = df_so[(df_so["date_order"] >= desde)].copy()
    if f.empty:
        return {"valor": None, "error": "Sin SO en ventana"}
    # SO está cumplido si todos sus pickings asociados están done
    if df_p.empty or "sale_id_id" not in df_p.columns:
        return {"valor": None, "error": "Sin link picking-SO"}
    # Mapeo sale_id → set de estados de pickings
    pickings_por_so = df_p.groupby("sale_id_id")["state"].apply(set).to_dict()
    cumplidos = 0
    parciales = 0
    sin_iniciar = 0
    for so_id in f["id"]:
        states = pickings_por_so.get(so_id)
        if not states:
            sin_iniciar += 1
        elif states == {"done"}:
            cumplidos += 1
        else:
            parciales += 1
    total = len(f)
    return {
        "valor": cumplidos / total if total else None,
        "cumplidos": cumplidos,
        "parciales": parciales,
        "sin_iniciar": sin_iniciar,
        "total_con_pickings": cumplidos + parciales,
        "n_orders": total,
        "error": None,
    }


def kpi_oct(dias: int = 30) -> Dict:
    """Order Cycle Time: horas entre date_order y date_done del primer picking."""
    df_so = df_sale_orders()
    df_p = df_pickings()
    if df_so.empty or df_p.empty:
        return {"error": "Sin data"}
    desde = pd.Timestamp.now() - pd.Timedelta(days=dias)
    f_so = df_so[(df_so["date_order"] >= desde)].copy()
    if f_so.empty:
        return {"valor": None, "error": "Sin SO en ventana"}
    # Primer date_done por sale_id
    if "sale_id_id" not in df_p.columns:
        return {"valor": None, "error": "Sin link"}
    primer_done = (df_p[df_p["state"] == "done"]
                   .groupby("sale_id_id")["date_done"].min().to_dict())
    horas = []
    for _, row in f_so.iterrows():
        d_done = primer_done.get(row["id"])
        if d_done is None or pd.isna(d_done):
            continue
        h = (d_done - row["date_order"]).total_seconds() / 3600
        if -240 <= h <= 8760:  # filtro outliers
            horas.append(h)
    if not horas:
        return {"valor": None, "error": "Sin pares completos"}
    s = pd.Series(horas)
    return {
        "valor": float(s.mean()),
        "mediana_h": float(s.median()),
        "min_h": float(s.min()),
        "max_h": float(s.max()),
        "n_orders": len(horas),
        "error": None,
    }


def kpi_lineas_pickeadas_mes(mes: str = None) -> Dict:
    """Líneas pickeadas en el mes especificado (YYYY-MM)."""
    if mes is None:
        mes = datetime.now().strftime("%Y-%m")
    df = df_moves()
    if df.empty:
        return {"lineas": 0, "error": "Sin moves raw"}
    desde = pd.Timestamp(f"{mes}-01")
    # Fin de mes
    next_m = (desde + pd.offsets.MonthBegin(1))
    f = df[(df["date"] >= desde) & (df["date"] < next_m) & (df["state"] == "done")]
    # Filtrar outgoing por picking_type_name
    if "picking_type_id_name" in f.columns:
        f = f[f["picking_type_id_name"].astype(str).str.contains(
            "out|deliver|dispatch", case=False, na=False)]
    return {"lineas": int(len(f)), "mes": mes, "error": None}


def kpi_merma(dias: int = 90, valor_inv_referencia: float = 0) -> Dict:
    """% Merma desde parquet scraps."""
    df = df_scraps()
    if df.empty:
        return {"error": "Sin scraps raw"}
    desde = pd.Timestamp.now() - pd.Timedelta(days=dias)
    f = df[df["date_done"] >= desde].copy()
    if f.empty:
        return {"valor": None, "n_scraps": 0,
                "qty_mermada": 0, "valor_mermado": 0,
                "error": "Sin scraps en ventana"}
    # Cargar valores de moves asociados
    df_m = df_moves()
    valor_total = 0
    if not df_m.empty and "id" in df_m.columns:
        move_ids = f["move_id_id"].dropna().tolist()
        moves_v = df_m[df_m["id"].isin(move_ids)].set_index("id")["value"].to_dict() if "value" in df_m.columns else {}
        f["valor"] = f["move_id_id"].map(lambda mid: abs(moves_v.get(mid, 0) or 0) if mid else 0)
        valor_total = float(f["valor"].sum())
    qty_total = float(f["scrap_qty"].sum())
    pct = (valor_total / valor_inv_referencia) if valor_inv_referencia > 0 else None
    return {
        "valor": pct,
        "valor_mermado": valor_total,
        "qty_mermada": qty_total,
        "n_scraps": int(len(f)),
        "valor_inventario_referencia": valor_inv_referencia,
        "ventana_dias": dias,
        "error": None,
    }


def kpi_ajustes_inventario_v2() -> Dict:
    """Ajustes de inventario desde parquet."""
    df = df_ajustes_inv()
    if df.empty:
        return {"n_ajustes": 0, "error": "Sin ajustes raw"}
    valor_neto = float(df["value"].fillna(0).sum())
    valor_surplus = float(df[df["value"] > 0]["value"].sum())
    valor_perdidas = float(-df[df["value"] < 0]["value"].sum())
    n_skus = df["product_id_id"].nunique() if "product_id_id" in df.columns else 0
    return {
        "n_ajustes": int(len(df)),
        "n_skus_unicos": int(n_skus),
        "valor_neto": valor_neto,
        "valor_surplus": valor_surplus,
        "valor_perdidas": valor_perdidas,
        "error": None,
    }


def productividad_por_periodo(periodo: str = "mes", n_periodos: int = 6) -> Dict:
    """Productividad por día/semana/mes desde parquet."""
    df_p = df_pickings()
    df_m = df_moves()
    if df_p.empty:
        return {"items": [], "error": "Sin data"}

    # Pickings outgoing done por período
    out = df_p[(df_p["picking_type_code"] == "outgoing") &
               (df_p["state"] == "done")].copy()
    if out.empty:
        return {"items": [], "error": "Sin pickings outgoing"}

    if periodo == "dia":
        out["bucket"] = out["date_done"].dt.date.astype(str)
    elif periodo == "semana":
        out["bucket"] = out["date_done"].dt.to_period("W").astype(str)
    else:  # mes
        out["bucket"] = out["date_done"].dt.to_period("M").astype(str)

    # Líneas y unidades por picking
    if not df_m.empty and "picking_id_id" in df_m.columns:
        moves_agg = df_m.groupby("picking_id_id").agg(
            n_lineas=("id", "count"),
            n_uds=("quantity", "sum"),
        ).reset_index()
        out = out.merge(moves_agg, left_on="id", right_on="picking_id_id", how="left")
        out["n_lineas"] = out["n_lineas"].fillna(0)
        out["n_uds"] = out["n_uds"].fillna(0)
    else:
        out["n_lineas"] = 0
        out["n_uds"] = 0

    grouped = out.groupby("bucket").agg(
        n_pedidos=("id", "count"),
        n_lineas_pickeadas=("n_lineas", "sum"),
        n_unidades_despachadas=("n_uds", "sum"),
    ).reset_index().sort_values("bucket", ascending=False).head(n_periodos)
    grouped["uds_por_pedido"] = grouped["n_unidades_despachadas"] / grouped["n_pedidos"].clip(lower=1)
    grouped["lineas_por_pedido"] = grouped["n_lineas_pickeadas"] / grouped["n_pedidos"].clip(lower=1)
    items = grouped.rename(columns={"bucket": "periodo"}).to_dict("records")
    items.reverse()  # cronológico ascendente
    return {"items": items, "periodo": periodo, "error": None}
