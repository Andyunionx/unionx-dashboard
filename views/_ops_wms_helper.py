"""
Queries Odoo para KPIs WMS (Warehouse Management System).

Expone funciones para:
  - OTIF B2C / B2B (Order Time In Full): pickings entregados a tiempo y completos
  - Pick Accuracy: move_lines con discrepancias / total
  - Tiempo de recepción: pickings incoming, scheduled vs done
  - Volumen movimientos: stock.move por tipo último 30d

Datos vienen de Odoo via OPS_ODOO_USER (cuenta servicio).
Cache 5 min en cada función.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from views._ops_odoo_helper import get_ops_odoo_client


# ============================================================
# Clasificación de trabajo del equipo de bodega (fix WMS 13-jul-2026)
# Espeja extract_volumen_inventario._clasificar_wms. El informe/KPI WMS
# cuenta ENTREGAS DEL EQUIPO (entrega_ca1 + reposiciones a fulfillment +
# salidas BRSt) y EXCLUYE los despachos que ejecuta el marketplace desde
# sus bodegas de fulfillment. VOLUMEN acá; el COSTO (COP) sale del P&L
# (control_gestion), NO de este parquet.
# ============================================================
_PROOT = Path(__file__).resolve().parent.parent
_VOLUMEN_HIST = _PROOT / "data" / "operaciones" / "volumen_inventario_hist.parquet"
_BF_LOCS = ("BFML", "BFFa", "BFP", "BFR", "BFW", "BFE")
_ENT_EQUIPO_CATS = ("entrega_ca1", "reposicion_fulfillment", "entrega_reserva")


def _clasificar_wms(ptn, code, lo, ld):
    """Mirror de extract_volumen_inventario._clasificar_wms (ver taxonomía)."""
    ptn = ptn or ""; lo = lo or ""; ld = ld or ""
    car = "Carrascal" in ptn
    res = "Reserva Stock" in ptn
    ff = "Fulfillment" in ptn
    dest_bf = any(b in ld for b in _BF_LOCS)
    orig_bf = any(b in lo for b in _BF_LOCS)
    if code == "outgoing":
        if ff or orig_bf:
            return "fulfillment_marketplace"
        if car:
            return "entrega_ca1"
        if res:
            return "entrega_reserva"
        return "otra_bodega"
    if code == "internal":
        if dest_bf:
            return "reposicion_fulfillment"
        if res:
            return "pick_reserva"
        if car:
            if "Output" in ld:
                return "pick_ca1"
            if "Input" in lo:
                return "recepcion_putaway"
            if "Stock" in lo and "Stock" in ld:
                return "reslotting"
            return "interno_ca1_otro"
        return "otra_bodega"
    return "otra_bodega"


def _gap_entregas_equipo(odoo, desde: str, hasta: str) -> dict:
    """Entregas del equipo (clasificadas) para un rango que el snapshot aún no
    cubre — consulta Odoo en vivo (tramo A). Rango chico (≤ buffer del extract).
    """
    out = {"n_pedidos": 0, "n_unidades": 0.0, "n_lineas": 0}
    picks = odoo.search_read(
        "stock.picking",
        [("state", "=", "done"), ("date_done", ">=", desde), ("date_done", "<", hasta),
         ("picking_type_code", "in", ["outgoing", "internal"])],
        ["id", "picking_type_id", "picking_type_code"], limit=50000,
    )
    if not picks:
        return out
    ptn = {p["id"]: (p["picking_type_id"][1] if isinstance(p.get("picking_type_id"), list) else "")
           for p in picks}
    code = {p["id"]: p.get("picking_type_code", "") for p in picks}
    pids = list(ptn.keys())
    tot = defaultdict(lambda: [0.0, 0])         # pid -> [uds_total, lineas_total]
    best = {}                                   # pid -> (uds_par, lo, ld) del par dominante
    for i in range(0, len(pids), 500):
        chunk = pids[i:i + 500]
        rg = odoo._execute_with_retry(
            "read_group", "stock.move",
            [("picking_id", "in", chunk), ("state", "=", "done")],
            {"fields": ["picking_id", "product_uom_qty:sum"],
             "groupby": ["picking_id", "location_id", "location_dest_id"], "lazy": False},
        )
        for r in rg:
            praw = r.get("picking_id"); pid = praw[0] if isinstance(praw, list) else praw
            q = r.get("product_uom_qty", 0) or 0
            lo = r.get("location_id"); ld = r.get("location_dest_id")
            lo = lo[1] if isinstance(lo, list) and len(lo) > 1 else ""
            ld = ld[1] if isinstance(ld, list) and len(ld) > 1 else ""
            tot[pid][0] += q
            tot[pid][1] += r.get("__count", 0)
            if pid not in best or q > best[pid][0]:
                best[pid] = (q, lo, ld)
    for pid, (uds, lineas) in tot.items():
        _, lo, ld = best.get(pid, (0, "", ""))
        cat = _clasificar_wms(ptn.get(pid, ""), code.get(pid, ""), lo, ld)
        if cat in _ENT_EQUIPO_CATS:
            out["n_pedidos"] += 1
            out["n_unidades"] += uds
            out["n_lineas"] += lineas
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _load_vol_equipo():
    """Snapshot parquet filtrado a ENTREGAS DEL EQUIPO (categoria_wms).
    Devuelve (df, fecha_max). Fallback a outgoing si el parquet es viejo."""
    if not _VOLUMEN_HIST.exists():
        return None, None
    try:
        df = pd.read_parquet(_VOLUMEN_HIST)
        df["fecha_done"] = pd.to_datetime(df["fecha_done"], errors="coerce")
        if "categoria_wms" in df.columns:
            df = df[df["categoria_wms"].isin(_ENT_EQUIPO_CATS)].dropna(subset=["fecha_done"])
        else:
            df = df[df["picking_type_code"] == "outgoing"].dropna(subset=["fecha_done"])
        return df, df["fecha_done"].max()
    except Exception:
        return None, None


def _entregas_equipo_rango(odoo, desde_d, hasta_d, label) -> Dict:
    """Motor compartido (fix WMS 13-jul): entregas del equipo en [desde,hasta).
    Snapshot parquet (B) + complemento Odoo en vivo para el tramo posterior (A).
    Devuelve claves duplicadas (n_unidades / n_unidades_despachadas, etc.) para
    servir a productividad_calendario y productividad_periodo por igual."""
    from datetime import date as _date, timedelta as _td
    df, pmax = _load_vol_equipo()
    n_ped = n_lin = 0
    n_uds = 0.0
    if df is not None:
        d = df[(df["fecha_done"] >= pd.Timestamp(desde_d))
               & (df["fecha_done"] < pd.Timestamp(hasta_d))]
        n_ped += int(d["picking_id"].nunique())
        n_uds += float(d["n_unidades"].sum())
        n_lin += int(d["n_lineas"].sum())
    if odoo is not None and pmax is not None and hasta_d > pmax.date():
        gap_desde = max(desde_d, (pmax + pd.Timedelta(days=1)).date())
        gap_hasta = min(hasta_d, _date.today() + _td(days=1))
        if gap_desde < gap_hasta:
            try:
                g = _gap_entregas_equipo(odoo, gap_desde.strftime("%Y-%m-%d"),
                                         gap_hasta.strftime("%Y-%m-%d"))
                n_ped += g["n_pedidos"]; n_uds += g["n_unidades"]; n_lin += g["n_lineas"]
            except Exception:
                pass
    return {
        "periodo": label,
        "fecha_desde": desde_d.strftime("%Y-%m-%d"),
        "n_pedidos": n_ped,
        "n_lineas": n_lin,
        "n_lineas_pickeadas": n_lin,
        "n_unidades": int(n_uds),
        "n_unidades_despachadas": int(n_uds),
        "uds_por_pedido": (n_uds / n_ped) if n_ped else 0,
        "lineas_por_pedido": (n_lin / n_ped) if n_ped else 0,
    }


# ============================================================
# OTIF B2C / B2B
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_otif(dias: int = 30, canal_b2b: bool = False) -> Dict:
    """OTIF = on-time + in-full sobre pickings done en últimos N días.

    Args:
        dias: ventana temporal
        canal_b2b: True para filtrar solo partners is_company=True (B2B)

    Returns:
        {valor, total_pickings, on_time, in_full, both, error}
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        domain = [
            ("state", "=", "done"),
            ("date_done", ">=", desde),
            ("picking_type_code", "=", "outgoing"),
        ]
        if canal_b2b:
            domain.append(("partner_id.is_company", "=", True))
        else:
            domain.append(("partner_id.is_company", "=", False))

        pickings = odoo.search_read(
            "stock.picking", domain,
            ["id", "name", "scheduled_date", "date_done", "partner_id", "state"],
            limit=20000,
        )
        if not pickings:
            return {"valor": None, "error": "Sin pickings en ventana"}

        on_time = 0
        for p in pickings:
            sched = p.get("scheduled_date")
            done = p.get("date_done")
            if not sched or not done:
                continue
            # On-time: date_done <= scheduled_date (con tolerancia 0)
            if done[:10] <= sched[:10]:
                on_time += 1

        # In-full: qty_done >= product_uom_qty para TODAS las move_lines del picking
        # Paginar moves en chunks de 100 picking_ids para evitar 502 Odoo SaaS
        picking_ids = [p["id"] for p in pickings]
        moves = []
        chunk_size = 100
        for i in range(0, len(picking_ids), chunk_size):
            chunk = picking_ids[i:i + chunk_size]
            try:
                chunk_moves = odoo.search_read(
                    "stock.move",
                    [("picking_id", "in", chunk)],
                    ["picking_id", "product_uom_qty", "quantity", "state"],
                    limit=20000,
                )
                moves.extend(chunk_moves)
            except Exception:
                continue  # Skip chunk problemático, mejor parcial que nada
        # Agrupar por picking
        moves_by_pid = defaultdict(list)
        for m in moves:
            pid = m["picking_id"][0] if m.get("picking_id") else None
            if pid:
                moves_by_pid[pid].append(m)

        in_full = 0
        for pid in picking_ids:
            mvs = moves_by_pid.get(pid, [])
            if not mvs:
                continue
            # in_full = todos los moves cumplieron qty_done >= product_uom_qty
            ok = all(
                (m.get("quantity") or 0) >= (m.get("product_uom_qty") or 0)
                for m in mvs
            )
            if ok:
                in_full += 1

        # OTIF = pickings on-time AND in-full
        both = 0
        for p in pickings:
            pid = p["id"]
            sched = p.get("scheduled_date")
            done = p.get("date_done")
            if not sched or not done:
                continue
            if done[:10] > sched[:10]:
                continue
            mvs = moves_by_pid.get(pid, [])
            if not mvs:
                continue
            if all((m.get("quantity") or 0) >= (m.get("product_uom_qty") or 0) for m in mvs):
                both += 1

        total = len(pickings)
        return {
            "valor": both / total if total else None,
            "total_pickings": total,
            "on_time": on_time,
            "on_time_pct": on_time / total if total else 0,
            "in_full": in_full,
            "in_full_pct": in_full / total if total else 0,
            "both": both,
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# PICK ACCURACY
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_pick_accuracy(dias: int = 30) -> Dict:
    """Pick Accuracy = moves sin discrepancia / total moves done en ventana.

    Discrepancia = qty_done != product_uom_qty (en valor absoluto, tolerancia 0).
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        # Paginar para evitar 502 Odoo SaaS en respuestas grandes
        try:
            moves = odoo.search_read_paginated(
                "stock.move",
                [("state", "=", "done"),
                 ("date", ">=", desde),
                 ("picking_type_id.code", "=", "outgoing")],
                ["product_uom_qty", "quantity"],
                page_size=2000,
            )
        except AttributeError:
            # Fallback si search_read_paginated no existe
            moves = odoo.search_read(
                "stock.move",
                [("state", "=", "done"),
                 ("date", ">=", desde),
                 ("picking_type_id.code", "=", "outgoing")],
                ["product_uom_qty", "quantity"],
                limit=20000,
            )
        if not moves:
            return {"valor": None, "error": "Sin moves en ventana"}

        ok = sum(1 for m in moves
                 if (m.get("quantity") or 0) == (m.get("product_uom_qty") or 0))
        total = len(moves)
        return {
            "valor": ok / total if total else None,
            "ok": ok,
            "total": total,
            "errores": total - ok,
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# TIEMPO DE RECEPCIÓN
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_tiempo_recepcion(dias: int = 90) -> Dict:
    """Tiempo recepción = horas entre scheduled_date y date_done para pickings incoming.

    Args:
        dias: ventana temporal (default 90d para tener varios embarques)
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        pickings = odoo.search_read(
            "stock.picking",
            [("state", "=", "done"),
             ("date_done", ">=", desde),
             ("picking_type_code", "=", "incoming")],
            ["id", "name", "scheduled_date", "date_done", "partner_id"],
            limit=5000,
        )
        if not pickings:
            return {"valor": None, "error": "Sin recepciones en ventana"}

        horas_list = []
        detalle = []
        for p in pickings:
            sched = p.get("scheduled_date")
            done = p.get("date_done")
            if not sched or not done:
                continue
            try:
                t_sched = datetime.fromisoformat(sched.replace(" ", "T"))
                t_done = datetime.fromisoformat(done.replace(" ", "T"))
                horas = (t_done - t_sched).total_seconds() / 3600
                if horas < -240 or horas > 720:  # filtro outliers (-10d / +30d)
                    continue
                horas_list.append(horas)
                proveedor = p["partner_id"][1] if p.get("partner_id") else ""
                detalle.append({
                    "picking": p.get("name", ""),
                    "proveedor": proveedor,
                    "horas": round(horas, 1),
                    "scheduled": sched[:16],
                    "done": done[:16],
                })
            except Exception:
                pass

        if not horas_list:
            return {"valor": None, "error": "Sin datos válidos de tiempo"}

        promedio = sum(horas_list) / len(horas_list)
        return {
            "valor": promedio,
            "n_recepciones": len(horas_list),
            "min": min(horas_list),
            "max": max(horas_list),
            "detalle": sorted(detalle, key=lambda d: d["done"], reverse=True)[:20],
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# VOLUMEN DE MOVIMIENTOS
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_volumen_movimientos(dias: int = 30) -> Dict:
    """Volumen de movimientos por tipo (incoming, outgoing, internal) último N días."""
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        pickings = odoo.search_read(
            "stock.picking",
            [("state", "=", "done"), ("date_done", ">=", desde)],
            ["picking_type_code"],
            limit=50000,
        )
        counts = defaultdict(int)
        for p in pickings:
            counts[p.get("picking_type_code", "?")] += 1
        return {
            "incoming": counts.get("incoming", 0),
            "outgoing": counts.get("outgoing", 0),
            "internal": counts.get("internal", 0),
            "total": sum(counts.values()),
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# OFR — Order Fulfillment Rate
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_ofr(dias: int = 30) -> Dict:
    """OFR = sale.orders cumplidos completos / total sale.orders del período.

    Cumplido completo: TODOS los pickings outgoing del SO están en state='done'.
    Diferente de OTIF (que mide on-time + in-full sobre pickings individuales).

    OFR responde: ¿el pedido del cliente terminó al 100%?
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        # Sale orders confirmados en ventana
        sos = odoo.search_read(
            "sale.order",
            [("state", "in", ["sale", "done"]),
             ("date_order", ">=", desde)],
            ["id", "name", "state", "picking_ids"],
            limit=20000,
        )
        if not sos:
            return {"valor": None, "error": "Sin sale orders en ventana"}

        # Recolectar todos los picking_ids de los SO
        all_pickings = []
        for so in sos:
            all_pickings.extend(so.get("picking_ids", []) or [])
        if not all_pickings:
            return {"valor": None, "error": "Sin pickings asociados"}

        # Estado de los pickings outgoing (los relevantes para fulfillment)
        pickings = odoo.search_read(
            "stock.picking",
            [("id", "in", all_pickings),
             ("picking_type_code", "=", "outgoing")],
            ["id", "state", "sale_id"],
            limit=50000,
        )

        # Agrupar por SO
        so_picks = defaultdict(list)
        for p in pickings:
            sid = p["sale_id"][0] if p.get("sale_id") else None
            if sid:
                so_picks[sid].append(p["state"])

        cumplidos = 0
        parciales = 0
        sin_iniciar = 0
        total_con_picks = 0
        for so in sos:
            sid = so["id"]
            states = so_picks.get(sid, [])
            if not states:
                continue
            total_con_picks += 1
            if all(s == "done" for s in states):
                cumplidos += 1
            elif any(s == "done" for s in states):
                parciales += 1
            else:
                sin_iniciar += 1

        return {
            "valor": cumplidos / total_con_picks if total_con_picks else None,
            "total_so": len(sos),
            "total_con_pickings": total_con_picks,
            "cumplidos": cumplidos,
            "parciales": parciales,
            "sin_iniciar": sin_iniciar,
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# OCT — Order Cycle Time
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_oct(dias: int = 30) -> Dict:
    """OCT = horas promedio entre confirmación venta (sale.order.date_order)
    y primer despacho (stock.picking outgoing date_done).

    Mide rapidez del proceso fulfillment end-to-end.
    Benchmark e-com Chile: < 24h B2C, < 72h B2B.
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        # Pickings outgoing done en ventana
        pickings = odoo.search_read(
            "stock.picking",
            [("state", "=", "done"),
             ("date_done", ">=", desde),
             ("picking_type_code", "=", "outgoing"),
             ("sale_id", "!=", False)],
            ["sale_id", "date_done", "partner_id"],
            limit=20000,
        )
        if not pickings:
            return {"valor": None, "error": "Sin despachos en ventana"}

        # Tomamos el primer despacho por SO
        so_first_done = {}
        for p in pickings:
            sid = p["sale_id"][0] if p.get("sale_id") else None
            done = p.get("date_done")
            if not sid or not done:
                continue
            if sid not in so_first_done or done < so_first_done[sid]["done"]:
                so_first_done[sid] = {"done": done, "partner": p.get("partner_id")}

        if not so_first_done:
            return {"valor": None, "error": "Sin SO mapeados"}

        # Cargar fechas de orden de los SO
        so_ids = list(so_first_done.keys())
        sos = odoo.search_read(
            "sale.order",
            [("id", "in", so_ids)],
            ["id", "name", "date_order", "partner_id"],
            limit=20000,
        )
        sos_by_id = {s["id"]: s for s in sos}

        horas_b2c = []
        horas_b2b = []
        detalle = []
        for sid, info in so_first_done.items():
            so = sos_by_id.get(sid)
            if not so or not so.get("date_order"):
                continue
            try:
                t_order = datetime.fromisoformat(so["date_order"].replace(" ", "T"))
                t_done = datetime.fromisoformat(info["done"].replace(" ", "T"))
                horas = (t_done - t_order).total_seconds() / 3600
                if horas < 0 or horas > 720:  # filtro outliers (>30d)
                    continue
                # Determinar canal por partner
                partner_name = (info.get("partner") or so.get("partner_id") or [None, ""])[1]
                # Heurística simple — más fiable seria cargar is_company del partner
                detalle.append({
                    "so": so.get("name"),
                    "cliente": partner_name,
                    "horas": round(horas, 1),
                    "fecha_orden": so["date_order"][:16],
                    "fecha_despacho": info["done"][:16],
                })
                # Sin distinción canal (necesitaría is_company), guardamos en B2C por defecto
                horas_b2c.append(horas)
            except Exception:
                continue

        if not horas_b2c:
            return {"valor": None, "error": "Sin tiempos válidos"}

        return {
            "valor": sum(horas_b2c) / len(horas_b2c),
            "n_orders": len(horas_b2c),
            "min_h": min(horas_b2c),
            "max_h": max(horas_b2c),
            "mediana_h": sorted(horas_b2c)[len(horas_b2c)//2],
            "detalle": sorted(detalle, key=lambda d: d["horas"], reverse=True)[:20],
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# PRODUCTIVIDAD PICKING — por mes específico
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_lineas_pickeadas_mes(mes: str) -> Dict:
    """Líneas (moves) pickeadas en el mes YYYY-MM.

    Para sincronizar con horas equipo del mismo mes.
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"lineas": 0, "error": "Odoo no disponible"}

    try:
        anio, mes_n = mes.split("-")
        anio, mes_n = int(anio), int(mes_n)
        from datetime import date
        desde = date(anio, mes_n, 1).strftime("%Y-%m-%d")
        # Último día del mes
        if mes_n == 12:
            hasta = date(anio + 1, 1, 1).strftime("%Y-%m-%d")
        else:
            hasta = date(anio, mes_n + 1, 1).strftime("%Y-%m-%d")

        moves = odoo.search_read(
            "stock.move",
            [("state", "=", "done"),
             ("date", ">=", desde),
             ("date", "<", hasta),
             ("picking_type_id.code", "=", "outgoing")],
            ["id"],
            limit=300000,
        )
        return {"lineas": len(moves), "mes": mes, "error": None}
    except Exception as e:
        return {"lineas": 0, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# TENDENCIA MES A MES (OTIF + Pick Accuracy + OCT)
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def tendencia_mensual(meses: int = 6) -> List[Dict]:
    """Histórico mes a mes de KPIs principales.

    Returns: [{mes: "YYYY-MM", otif_b2c, otif_b2b, pick_acc, oct_h, n_pickings}, ...]
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return []

    out = []
    hoy = datetime.now()
    for i in range(meses, 0, -1):
        # Calcular mes (i meses atrás)
        anio = hoy.year
        mes_n = hoy.month - i + 1
        while mes_n <= 0:
            mes_n += 12
            anio -= 1
        mes_str = f"{anio}-{mes_n:02d}"

        from datetime import date
        desde = date(anio, mes_n, 1).strftime("%Y-%m-%d")
        if mes_n == 12:
            hasta = date(anio + 1, 1, 1).strftime("%Y-%m-%d")
        else:
            hasta = date(anio, mes_n + 1, 1).strftime("%Y-%m-%d")

        try:
            # Pickings outgoing done en el mes
            pickings = odoo.search_read(
                "stock.picking",
                [("state", "=", "done"),
                 ("date_done", ">=", desde),
                 ("date_done", "<", hasta),
                 ("picking_type_code", "=", "outgoing")],
                ["id", "scheduled_date", "date_done", "partner_id"],
                limit=20000,
            )
            n_pickings = len(pickings)
            if n_pickings == 0:
                out.append({"mes": mes_str, "otif_b2c": None, "otif_b2b": None,
                            "pick_acc": None, "n_pickings": 0})
                continue

            # OTIF: on-time AND in-full
            picking_ids = [p["id"] for p in pickings]
            moves = odoo.search_read(
                "stock.move",
                [("picking_id", "in", picking_ids)],
                ["picking_id", "product_uom_qty", "quantity"],
                limit=200000,
            )
            moves_by_pid = defaultdict(list)
            for m in moves:
                pid = m["picking_id"][0] if m.get("picking_id") else None
                if pid:
                    moves_by_pid[pid].append(m)

            # Necesitamos saber B2C vs B2B → cargar partners
            partner_ids = list({p["partner_id"][0] for p in pickings if p.get("partner_id")})
            partners = odoo.search_read(
                "res.partner", [("id", "in", partner_ids)],
                ["id", "is_company"], limit=20000,
            ) if partner_ids else []
            is_b2b = {p["id"]: p.get("is_company", False) for p in partners}

            otif_b2c_count, otif_b2b_count = 0, 0
            tot_b2c, tot_b2b = 0, 0
            for p in pickings:
                pid = p["id"]
                partner_id = p["partner_id"][0] if p.get("partner_id") else None
                b2b = is_b2b.get(partner_id, False)
                if b2b:
                    tot_b2b += 1
                else:
                    tot_b2c += 1
                sched = p.get("scheduled_date"); done = p.get("date_done")
                if not sched or not done:
                    continue
                if done[:10] > sched[:10]:
                    continue
                mvs = moves_by_pid.get(pid, [])
                if not mvs:
                    continue
                if all((m.get("quantity") or 0) >= (m.get("product_uom_qty") or 0) for m in mvs):
                    if b2b:
                        otif_b2b_count += 1
                    else:
                        otif_b2c_count += 1

            # Pick Accuracy = moves OK / total moves
            ok = sum(1 for m in moves
                     if (m.get("quantity") or 0) == (m.get("product_uom_qty") or 0))
            pick_acc = ok / len(moves) if moves else None

            out.append({
                "mes": mes_str,
                "otif_b2c": otif_b2c_count / tot_b2c if tot_b2c else None,
                "otif_b2b": otif_b2b_count / tot_b2b if tot_b2b else None,
                "pick_acc": pick_acc,
                "n_pickings": n_pickings,
                "n_b2c": tot_b2c,
                "n_b2b": tot_b2b,
            })
        except Exception:
            out.append({"mes": mes_str, "otif_b2c": None, "otif_b2b": None,
                        "pick_acc": None, "n_pickings": 0, "error": True})
    return out


# ============================================================
# MERMA OPERATIVA — desde Odoo stock.scrap
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_merma_odoo(dias: int = 90) -> Dict:
    """Merma ejecutada en Odoo via stock.scrap state=done.

    Args:
        dias: ventana temporal (default 90d)

    Returns:
        valor_pct: merma / valor_inventario_promedio (necesita stock data)
        valor_mermado: $ total
        qty_mermada: unidades total
        n_scraps: cantidad de scraps
        top_skus: top 20 SKUs mermados por valor
        detalle: lista últimos 50 scraps
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        scraps = odoo.search_read(
            "stock.scrap",
            [("state", "=", "done"), ("date_done", ">=", desde)],
            ["id", "name", "product_id", "scrap_qty", "date_done",
             "location_id", "scrap_location_id", "move_id", "origin"],
            limit=20000,
        )
        if not scraps:
            return {"valor": None, "qty_mermada": 0, "valor_mermado": 0,
                    "n_scraps": 0, "top_skus": [], "detalle": [],
                    "error": "Sin scraps en ventana"}

        # Cargar values desde los stock.moves asociados
        move_ids = [s["move_id"][0] for s in scraps if s.get("move_id")]
        moves_value = {}
        if move_ids:
            moves = odoo.search_read(
                "stock.move",
                [("id", "in", move_ids)],
                ["id", "value"], limit=20000,
            )
            moves_value = {m["id"]: m.get("value", 0) or 0 for m in moves}

        # Agregar valor a cada scrap
        for s in scraps:
            mid = s["move_id"][0] if s.get("move_id") else None
            s["valor"] = abs(moves_value.get(mid, 0))  # value puede ser negativo (egreso)

        total_qty = sum(s.get("scrap_qty", 0) for s in scraps)
        total_valor = sum(s.get("valor", 0) for s in scraps)

        # Top SKUs mermados
        from collections import defaultdict
        agg = defaultdict(lambda: {"qty": 0, "valor": 0, "n_scraps": 0})
        for s in scraps:
            if not s.get("product_id"):
                continue
            pid = s["product_id"][0]
            agg[pid]["nombre"] = s["product_id"][1]
            agg[pid]["qty"] += s.get("scrap_qty", 0)
            agg[pid]["valor"] += s.get("valor", 0)
            agg[pid]["n_scraps"] += 1

        top_skus = [
            {"sku": v["nombre"][:80], "qty_mermada": v["qty"],
             "valor_mermado": v["valor"], "n_scraps": v["n_scraps"]}
            for v in agg.values()
        ]
        top_skus.sort(key=lambda x: -x["valor_mermado"])

        # Detalle últimos N
        detalle = sorted(
            [{"fecha": s.get("date_done", "")[:10],
              "ref": s.get("name", ""),
              "sku": s["product_id"][1][:60] if s.get("product_id") else "",
              "qty": s.get("scrap_qty", 0),
              "valor": s.get("valor", 0),
              "ubicacion": s["location_id"][1] if s.get("location_id") else "",
              "destino": s["scrap_location_id"][1] if s.get("scrap_location_id") else "",
              "origen": s.get("origin", "")} for s in scraps],
            key=lambda d: d["fecha"], reverse=True,
        )[:50]

        # Calcular % merma vs inventario promedio
        # Necesitamos valor_inventario_promedio del cached_stock
        try:
            from views.shared import cached_stock
            stock_data = cached_stock()
            valor_inv = stock_data.get("kpis", {}).get("valor_total", 0) if stock_data else 0
            pct = total_valor / valor_inv if valor_inv > 0 else None
        except Exception:
            pct = None
            valor_inv = 0

        return {
            "valor": pct,  # % sobre valor inventario
            "valor_mermado": total_valor,
            "qty_mermada": total_qty,
            "n_scraps": len(scraps),
            "valor_inventario_referencia": valor_inv,
            "top_skus": top_skus[:20],
            "detalle": detalle,
            "ventana_dias": dias,
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# AJUSTES DE INVENTARIO — desde Odoo stock.move (cycle counts)
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_ajustes_inventario(desde_fecha: str = "2026-04-01") -> Dict:
    """Ajustes de inventario hechos en Odoo desde fecha (default abril 2026).

    Filtra SOLO por la ubicación virtual `Inventory adjustment`
    (excluye Scrap y Production que también tienen usage='inventory').

    En UnionX las ubicaciones virtuales son:
      - Virtual Locations/Inventory adjustment  ← USAMOS ESTA (cycle counts)
      - Virtual Locations/Production            ← NO usamos (es producción)
      - Virtual Locations/Scrap                 ← NO usamos (cubierto por kpi_merma_odoo)

    Equivalente a "cycle counts CON discrepancia" (los exactos no generan move).
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"n_ajustes": 0, "error": "Odoo no disponible"}

    try:
        # Domain: state=done desde fecha + ubicación = Inventory adjustment
        # Filtramos por NOMBRE (no por usage genérico) para excluir Scrap+Production
        moves = odoo.search_read(
            "stock.move",
            [("state", "=", "done"),
             ("date", ">=", desde_fecha),
             "|",
             ("location_id.name", "=", "Inventory adjustment"),
             ("location_dest_id.name", "=", "Inventory adjustment")],
            ["id", "name", "date", "product_id", "product_uom_qty",
             "location_id", "location_dest_id", "value", "reference"],
            limit=50000,
        )
        if not moves:
            return {"n_ajustes": 0, "n_skus_unicos": 0, "valor_neto": 0,
                    "valor_perdidas": 0, "valor_surplus": 0,
                    "top_skus_ajustados": [], "detalle": [],
                    "error": "Sin ajustes en ventana"}

        # Para cada move:
        #   Si location_id (origen) es inventory virtual => INGRESO (surplus, valor>0)
        #   Si location_dest_id (destino) es inventory virtual => EGRESO (pérdida, valor<0)
        from collections import defaultdict
        agg = defaultdict(lambda: {"qty_neta": 0, "valor_neto": 0, "n_movs": 0,
                                    "qty_surplus": 0, "qty_perdida": 0})

        valor_neto = 0
        valor_surplus = 0
        valor_perdidas = 0
        for m in moves:
            if not m.get("product_id"):
                continue
            pid = m["product_id"][0]
            qty = m.get("product_uom_qty", 0) or 0
            val = m.get("value", 0) or 0
            loc_origen = m.get("location_id")
            loc_dest = m.get("location_dest_id")

            # Detectar dirección del ajuste
            origen_es_virt = "inventory" in (loc_origen[1].lower() if loc_origen else "")
            # Más confiable: usar valor (positivo = ingreso a stock real)
            if val > 0:
                # Ajuste positivo (encontraron más): surplus
                agg[pid]["qty_surplus"] += qty
                agg[pid]["valor_neto"] += val
                valor_surplus += val
            elif val < 0:
                # Ajuste negativo: pérdida
                agg[pid]["qty_perdida"] += qty
                agg[pid]["valor_neto"] += val
                valor_perdidas += abs(val)
            agg[pid]["nombre"] = m["product_id"][1]
            agg[pid]["qty_neta"] += qty if val >= 0 else -qty
            agg[pid]["n_movs"] += 1
            valor_neto += val

        # Top SKUs con más ajustes
        top = [
            {"sku": v["nombre"][:80], "n_ajustes": v["n_movs"],
             "qty_surplus": v["qty_surplus"], "qty_perdida": v["qty_perdida"],
             "valor_neto": v["valor_neto"]}
            for v in agg.values()
        ]
        top.sort(key=lambda x: -x["n_ajustes"])

        # Detalle últimos N
        detalle = sorted(
            [{"fecha": m.get("date", "")[:10],
              "ref": m.get("reference", "") or m.get("name", "")[:40],
              "sku": m["product_id"][1][:60] if m.get("product_id") else "",
              "qty": m.get("product_uom_qty", 0),
              "valor": m.get("value", 0),
              "tipo": "Surplus" if (m.get("value") or 0) > 0 else "Pérdida",
              "origen": m["location_id"][1] if m.get("location_id") else "",
              "destino": m["location_dest_id"][1] if m.get("location_dest_id") else ""}
             for m in moves],
            key=lambda d: d["fecha"], reverse=True,
        )[:100]

        # Cobertura: SKUs únicos / total activos
        n_skus_ajustados = len(agg)
        try:
            total_activos = odoo.search_count(
                "product.product",
                [("active", "=", True), ("type", "=", "product")],
            )
        except Exception:
            total_activos = 0
        cobertura_pct = n_skus_ajustados / total_activos if total_activos else None

        return {
            "n_ajustes": len(moves),
            "n_skus_unicos": n_skus_ajustados,
            "total_skus_activos": total_activos,
            "cobertura_pct": cobertura_pct,
            "valor_neto": valor_neto,
            "valor_perdidas": valor_perdidas,
            "valor_surplus": valor_surplus,
            "top_skus_ajustados": top[:20],
            "detalle": detalle,
            "desde": desde_fecha,
            "error": None,
        }
    except Exception as e:
        return {"n_ajustes": 0, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# PLAN AUDITORÍA SEMANAL (priorización por alta rotación)
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def plan_auditoria_semanal(
    top_n_priorizar: int = 50,
    dias_sin_ajuste: int = 30,
    dias_rotacion: int = 90,
) -> Dict:
    """Plan recomendado de cycle counts para la semana.

    Lógica de priorización (combinada):
      1. SKUs Top A por rotación (movimientos en últimos N días)
      2. Que NO tengan ajuste en últimos N días (sin auditar recientemente)
      3. Que NO sean inactivos (qty > 0 actualmente)

    Args:
        top_n_priorizar: cuántos SKUs sugerir
        dias_sin_ajuste: SKU "sin auditar" si ajuste hace > N días
        dias_rotacion: ventana para calcular top movers

    Returns:
        plan_semana: lista de SKUs priorizados con score
        skus_alta_rotacion_sin_ajuste: count
        capacidad_semanal: estimación con horas equipo
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"plan": [], "error": "Odoo no disponible"}

    try:
        # 1. Movimientos outgoing últimos N días → ranking de rotación
        desde_rot = (datetime.now() - timedelta(days=dias_rotacion)).strftime("%Y-%m-%d")
        moves_rot = odoo.search_read(
            "stock.move",
            [("state", "=", "done"),
             ("date", ">=", desde_rot),
             ("picking_type_id.code", "=", "outgoing")],
            ["product_id", "product_uom_qty"],
            limit=200000,
        )
        from collections import defaultdict
        rot = defaultdict(lambda: {"qty": 0, "n_movs": 0, "nombre": ""})
        for m in moves_rot:
            if not m.get("product_id"):
                continue
            pid = m["product_id"][0]
            rot[pid]["nombre"] = m["product_id"][1]
            rot[pid]["qty"] += m.get("product_uom_qty", 0) or 0
            rot[pid]["n_movs"] += 1

        # Top movers
        top_movers = sorted(rot.items(), key=lambda x: -x[1]["qty"])

        # 2. SKUs con ajuste reciente (excluirlos del plan)
        desde_aj = (datetime.now() - timedelta(days=dias_sin_ajuste)).strftime("%Y-%m-%d")
        ajustes_recientes = odoo.search_read(
            "stock.move",
            [("state", "=", "done"),
             ("date", ">=", desde_aj),
             "|",
             ("location_id.name", "=", "Inventory adjustment"),
             ("location_dest_id.name", "=", "Inventory adjustment")],
            ["product_id"],
            limit=20000,
        )
        skus_auditados_recientes = {a["product_id"][0]
                                    for a in ajustes_recientes
                                    if a.get("product_id")}

        # 3. SKUs con stock actual (de cached stock data)
        from views.shared import cached_stock
        try:
            stock = cached_stock()
            # Stock data devuelve dict con 'skus' como list of dicts
            skus_data = stock.get("skus", []) if stock else []
            stock_actual = {}  # {product_id: {qty, valor, sku, semaforo}}
            # Necesitamos cargar product.product para mapear SKU code a id
            # Más fácil: quants
            quants = odoo.search_read(
                "stock.quant",
                [("location_id.usage", "=", "internal"), ("quantity", ">", 0)],
                ["product_id", "quantity", "value"],
                limit=80000,
            )
            for q in quants:
                if not q.get("product_id"):
                    continue
                pid = q["product_id"][0]
                if pid not in stock_actual:
                    stock_actual[pid] = {"qty": 0, "valor": 0,
                                         "nombre": q["product_id"][1]}
                stock_actual[pid]["qty"] += q.get("quantity", 0)
                stock_actual[pid]["valor"] += q.get("value", 0)
        except Exception:
            stock_actual = {}

        # 4. Construir plan: top movers SIN ajuste reciente, CON stock
        plan = []
        for pid, info in top_movers:
            if len(plan) >= top_n_priorizar:
                break
            if pid in skus_auditados_recientes:
                continue
            stock_info = stock_actual.get(pid, {"qty": 0, "valor": 0})
            if stock_info.get("qty", 0) <= 0:
                continue  # Sin stock no tiene sentido auditar
            # Score: combinación de rotación + valor en stock
            score = info["qty"] * (1 + (stock_info["valor"] / 100000))
            plan.append({
                "product_id": pid,
                "sku": info["nombre"][:80],
                "qty_movida_period": int(info["qty"]),
                "n_movs_period": info["n_movs"],
                "qty_stock_actual": int(stock_info["qty"]),
                "valor_stock_actual": stock_info["valor"],
                "prioridad_score": round(score, 1),
                "razon": "Top rotación + sin auditar >{}d".format(dias_sin_ajuste),
            })

        # 5. Capacidad semanal estimada (asumiendo ~3 SKUs auditables / hora / persona)
        from views._ops_data_helper import get_equipo_mes
        mes_actual = datetime.now().strftime("%Y-%m")
        eq = get_equipo_mes(mes_actual) or {}
        n_personas = eq.get("personas", 0)
        horas_mes = eq.get("horas_total", 0)
        # Asumir 5% del tiempo dedicado a cycle counts → 0.05 * horas/mes
        # Y 3 SKUs/h/persona auditables
        horas_cc_mes = horas_mes * 0.05
        capacidad_skus_mes = horas_cc_mes * 3
        capacidad_skus_semana = capacidad_skus_mes / 4.33

        return {
            "plan": plan,
            "skus_alta_rotacion_sin_ajuste": len(plan),
            "skus_auditados_recientes": len(skus_auditados_recientes),
            "capacidad": {
                "n_personas": n_personas,
                "horas_mes": horas_mes,
                "horas_cc_mes_5pct": round(horas_cc_mes, 0),
                "skus_audit_mes": int(capacidad_skus_mes),
                "skus_audit_semana": int(capacidad_skus_semana),
            },
            "ventana_rotacion_dias": dias_rotacion,
            "ventana_sin_ajuste_dias": dias_sin_ajuste,
            "error": None,
        }
    except Exception as e:
        return {"plan": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# PRODUCTIVIDAD POR PERÍODO (día / semana / mes)
# ============================================================
# ============================================================
# DEVOLUCIONES POR ERROR (Pick Accuracy real)
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_devoluciones_picking_error(dias: int = 90) -> Dict:
    """Tasa REAL de errores de picking medida desde devoluciones.

    Cuenta pickings tipo return (incoming desde cliente) cuyo origen es
    una venta. Esto refleja el error que el CLIENTE detectó, no la
    consistencia interna del sistema.

    Returns:
        valor: # devoluciones / # despachos en ventana
        n_devoluciones, n_despachos
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        # Devoluciones: pickings incoming con origin que sea una venta (return)
        devoluciones = odoo.search_read(
            "stock.picking",
            [("state", "=", "done"),
             ("date_done", ">=", desde),
             ("picking_type_code", "=", "incoming"),
             ("origin", "ilike", "S")],  # SO/Sxxx típico
            ["id", "name", "origin", "partner_id", "date_done"],
            limit=10000,
        )
        # search_count no esta disponible en nuestro OdooClient → usar search_read con id
        despachos_list = odoo.search_read(
            "stock.picking",
            [("state", "=", "done"),
             ("date_done", ">=", desde),
             ("picking_type_code", "=", "outgoing")],
            ["id"], limit=50000,
        )
        despachos = len(despachos_list)
        n_dev = len(devoluciones)
        n_des = despachos
        return {
            "valor": n_dev / n_des if n_des else None,
            "n_devoluciones": n_dev,
            "n_despachos": n_des,
            "ventana_dias": dias,
            "ejemplos": [{"ref": d.get("name"), "origen": d.get("origin"),
                          "cliente": d.get("partner_id", [None, ""])[1] if d.get("partner_id") else "",
                          "fecha": d.get("date_done", "")[:10]}
                         for d in devoluciones[:20]],
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# PRODUCTIVIDAD POR PERÍODO (calendar + rolling)
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def productividad_calendario(tipo: str = "mes", anio: int = None, mes: int = None) -> Dict:
    """Productividad para un período CALENDARIO específico.

    Args:
        tipo: 'mes' (mes calendario), 'semana_de_mes' (semanas dentro de un mes),
              'dia_especifico' (1 día concreto)
        anio: año (default: actual)
        mes: mes 1-12 (default: actual)

    Returns:
        items: [{periodo, n_pedidos, n_lineas, n_unidades, ...}]
    """
    from datetime import date as _date, timedelta as _td
    import calendar
    # El motor usa el snapshot parquet (categoria_wms); Odoo solo complementa el
    # tramo posterior al snapshot. Si Odoo no está, igual servimos desde parquet.
    odoo = get_ops_odoo_client()
    _df_chk, _ = _load_vol_equipo()
    if odoo is None and _df_chk is None:
        return {"items": [], "error": "Sin snapshot ni Odoo"}

    hoy = _date.today()
    anio = anio or hoy.year
    mes = mes or hoy.month

    items = []

    try:
        if tipo == "mes":
            # Listado de últimos 12 meses
            for i in range(11, -1, -1):
                a, m = anio, mes - i
                while m <= 0:
                    m += 12
                    a -= 1
                desde = _date(a, m, 1)
                if m == 12:
                    hasta = _date(a + 1, 1, 1)
                else:
                    hasta = _date(a, m + 1, 1)
                items.append(_calc_productividad(odoo, desde, hasta,
                                                  f"{a}-{m:02d}"))
        elif tipo == "semana_de_mes":
            # Semanas dentro del mes (lunes a domingo)
            n_dias = calendar.monthrange(anio, mes)[1]
            d = _date(anio, mes, 1)
            sem_n = 1
            while d.month == mes and d.year == anio:
                # Encontrar fin de semana (domingo)
                fin_sem = d + _td(days=(6 - d.weekday()))
                if fin_sem.month != mes or fin_sem.year != anio:
                    fin_sem = _date(anio, mes, n_dias)
                hasta = fin_sem + _td(days=1)
                items.append(_calc_productividad(odoo, d, hasta,
                                                  f"S{sem_n} ({d.strftime('%d/%m')}-{fin_sem.strftime('%d/%m')})"))
                d = hasta
                sem_n += 1
        elif tipo == "dia_especifico":
            # Días: hoy, ayer, ant., etc. (últimos 14 días)
            for i in range(13, -1, -1):
                d = hoy - _td(days=i)
                hasta = d + _td(days=1)
                items.append(_calc_productividad(odoo, d, hasta, d.strftime("%Y-%m-%d (%a)")))
        return {"items": items, "tipo": tipo, "anio": anio, "mes": mes, "error": None}
    except Exception as e:
        return {"items": items, "error": f"{type(e).__name__}: {str(e)[:120]}"}


def _calc_productividad(odoo, desde, hasta, label) -> Dict:
    """Productividad de un rango = ENTREGAS DEL EQUIPO (fix WMS 13-jul).
    Delega al motor compartido (parquet categoria_wms + complemento vivo)."""
    try:
        return _entregas_equipo_rango(odoo, desde, hasta, label)
    except Exception as e:
        return {"periodo": label, "error": str(e)[:100],
                "n_pedidos": 0, "n_lineas": 0, "n_unidades": 0,
                "uds_por_pedido": 0, "lineas_por_pedido": 0}


@st.cache_data(ttl=43200, show_spinner=False)
def productividad_periodo(periodo: str = "mes", n_periodos: int = 6) -> Dict:
    """Productividad operativa: ENTREGAS DEL EQUIPO (unidades/pedidos/líneas).

    Fix WMS 13-jul-2026: cuenta entregas del equipo (entrega_ca1 + reposiciones
    a fulfillment + salidas BRSt) desde el snapshot parquet con categoria_wms
    (B), corregido en toda la historia — excluye los despachos que ejecuta el
    marketplace. El tramo posterior al snapshot se completa con Odoo en vivo
    clasificado (A). Solo VOLUMEN; el COSTO (COP) sale del P&L, no de acá.

    Args:
        periodo: 'dia', 'semana', 'mes'
        n_periodos: cuántos períodos hacia atrás traer
    """
    from datetime import date as _date, timedelta as _td

    odoo = get_ops_odoo_client()
    df, _ = _load_vol_equipo()
    if df is None and odoo is None:
        return {"items": [], "error": "Sin snapshot ni Odoo"}

    try:
        items = []
        hoy = _date.today()
        for i in range(n_periodos, 0, -1):
            if periodo == "dia":
                desde_d = hoy - _td(days=i)
                hasta_d = desde_d + _td(days=1)
                label = desde_d.strftime("%Y-%m-%d")
            elif periodo == "semana":
                desde_d = hoy - _td(days=hoy.weekday() + 7 * (i - 1) + 7)
                hasta_d = desde_d + _td(days=7)
                label = f"Sem {desde_d.isocalendar()[1]} ({desde_d.strftime('%d/%m')})"
            else:  # mes
                anio = hoy.year
                mes_n = hoy.month - i + 1
                while mes_n <= 0:
                    mes_n += 12
                    anio -= 1
                desde_d = _date(anio, mes_n, 1)
                hasta_d = _date(anio + 1, 1, 1) if mes_n == 12 else _date(anio, mes_n + 1, 1)
                label = f"{anio}-{mes_n:02d}"

            items.append(_entregas_equipo_rango(odoo, desde_d, hasta_d, label))

        return {"items": items, "periodo": periodo, "n_periodos": n_periodos, "error": None}
    except Exception as e:
        return {"items": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# FORECAST VOLUMEN PICKING — V2: basado en forecast Prophet de ventas
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def forecast_volumen_picking(meses_adelante: int = 3) -> Dict:
    """Proyecta carga de picking basada en el forecast de VENTAS (Prophet).

    Mejor que el approach anterior porque el forecast Prophet del dashboard
    ventas YA incluye:
      - Trend
      - Estacionalidad semanal
      - Estacionalidad anual (Cyber Day, Black Friday, Día Madre/Padre, etc)
      - Holidays Chile

    Lógica:
      1. Lee proyección mensual $ desde data/forecast/forecast_resumen.json
      2. Calcula ratio histórico líneas_pickeadas / venta_$ últimos 3 meses
      3. Aplica ratio a proyección $ → líneas proyectadas
      4. Calcula horas equipo necesarias y % capacidad cubierta

    Returns: historico + forecast + tasas + recomendaciones
    """
    try:
        from views._ops_forecast_loader import proyeccion_mensual_ventas, cargar_forecast_resumen
        from views._ops_data_helper import get_equipo_mes, calcular_horas_estandar_mes

        # 1. Cargar proyección de ventas Prophet
        proy = proyeccion_mensual_ventas(meses_adelante=meses_adelante + 1)
        if not proy:
            return {"forecast": [], "error": "Sin forecast de ventas (data/forecast vacío)"}

        # 2. Histórico interno de picking + ventas para calcular ratio líneas/$
        hist = productividad_periodo("mes", n_periodos=6)
        if hist.get("error") or not hist.get("items"):
            return {"forecast": [], "error": hist.get("error", "Sin histórico picking")}

        # Cargar venta histórica de Odoo para los mismos meses
        odoo = get_ops_odoo_client()
        ventas_hist = {}
        if odoo:
            from datetime import datetime as _dt2, date as _date2
            for it in hist["items"]:
                # it["periodo"] = "YYYY-MM"
                try:
                    anio_h, mes_h = it["periodo"].split("-")
                    anio_h, mes_h = int(anio_h), int(mes_h)
                    desde = _date2(anio_h, mes_h, 1).strftime("%Y-%m-%d")
                    hasta = (_date2(anio_h + (1 if mes_h == 12 else 0),
                                    1 if mes_h == 12 else mes_h + 1, 1)).strftime("%Y-%m-%d")
                    sos = odoo.search_read(
                        "sale.order",
                        [("state", "in", ["sale", "done"]),
                         ("date_order", ">=", desde),
                         ("date_order", "<", hasta)],
                        ["amount_total"], limit=20000,
                    )
                    venta_mes = sum(s.get("amount_total", 0) or 0 for s in sos)
                    ventas_hist[it["periodo"]] = venta_mes
                except Exception:
                    pass

        # 3. Calcular ratios históricos por mes (líneas/$ y uds/$)
        ratios_lineas = []
        ratios_uds = []
        ratios_pedidos = []
        for it in hist["items"]:
            venta_mes = ventas_hist.get(it["periodo"], 0)
            if venta_mes <= 0:
                continue
            ratios_lineas.append(it["n_lineas_pickeadas"] / venta_mes)
            ratios_uds.append(it["n_unidades_despachadas"] / venta_mes)
            ratios_pedidos.append(it["n_pedidos"] / venta_mes)

        if not ratios_lineas:
            return {"forecast": [], "error": "Sin venta histórica para calcular ratios"}

        # Promedio últimos 3 meses con datos
        ratios_lineas = ratios_lineas[-3:]
        ratios_uds = ratios_uds[-3:]
        ratios_pedidos = ratios_pedidos[-3:]
        ratio_lineas_clp = sum(ratios_lineas) / len(ratios_lineas)
        ratio_uds_clp = sum(ratios_uds) / len(ratios_uds)
        ratio_pedidos_clp = sum(ratios_pedidos) / len(ratios_pedidos)

        # 4. Productividad actual (líneas/h)
        from datetime import datetime as _dt
        mes_actual_str = _dt.now().strftime("%Y-%m")
        eq = get_equipo_mes(mes_actual_str) or {}
        n_personas = eq.get("personas", 0)
        horas_actuales = eq.get("horas_total", 0)

        ultimos_3 = hist["items"][-3:]
        total_lineas_3m = sum(it["n_lineas_pickeadas"] for it in ultimos_3)
        horas_3m = horas_actuales * 3 if horas_actuales else 0
        prod_lineas_h = total_lineas_3m / horas_3m if horas_3m else 0

        # 5. Construir forecast aplicando ratios a proyección $ Prophet
        forecast = []
        # Skip mes actual (mixto), tomar futuros
        proy_futuros = [p for p in proy if p["mes_str"] > mes_actual_str][:meses_adelante]
        for p in proy_futuros:
            venta_proj_clp = p.get("proyeccion_clp", 0)
            lineas_proj = int(venta_proj_clp * ratio_lineas_clp)
            uds_proj = int(venta_proj_clp * ratio_uds_clp)
            pedidos_proj = int(venta_proj_clp * ratio_pedidos_clp)

            horas_necesarias = lineas_proj / prod_lineas_h if prod_lineas_h > 0 else 0
            calc_h = calcular_horas_estandar_mes(p["mes_str"], n_personas) if n_personas > 0 else {}
            horas_disp = calc_h.get("horas_total", 0)
            cobertura_pct = (horas_disp / horas_necesarias * 100) if horas_necesarias > 0 else None

            # Banda baja/alta usando bandas Prophet
            venta_low = p.get("banda_inferior", 0)
            venta_high = p.get("banda_superior", 0)

            forecast.append({
                "mes": p["mes_str"],
                "tipo_proyeccion": p.get("tipo", "forecast"),
                "venta_proj_clp": int(venta_proj_clp),
                "venta_proj_clp_low": int(venta_low),
                "venta_proj_clp_high": int(venta_high),
                "vs_ly_pct": p.get("pct_vs_ly", 0),
                "pedidos_proj": pedidos_proj,
                "lineas_proj": lineas_proj,
                "unidades_proj": uds_proj,
                "horas_necesarias_estim": int(horas_necesarias),
                "horas_disponibles_estandar": horas_disp,
                "cobertura_pct": cobertura_pct,
                "alerta": ("🔴 Falta capacidad" if cobertura_pct and cobertura_pct < 90
                          else "🟡 Límite" if cobertura_pct and cobertura_pct < 110
                          else "🟢 OK"),
            })

        return {
            "fuente": "Forecast ventas Prophet (dashboard ventas)",
            "historico": hist["items"],
            "ventas_hist_clp": ventas_hist,
            "forecast": forecast,
            "ratios_aplicados": {
                "lineas_por_clp": round(ratio_lineas_clp * 1_000_000, 2),  # líneas por MM CLP
                "uds_por_clp": round(ratio_uds_clp * 1_000_000, 2),
                "pedidos_por_clp": round(ratio_pedidos_clp * 1_000_000, 2),
                "n_meses_promedio": len(ratios_lineas),
                "leyenda": "Por cada $1MM CLP de venta",
            },
            "productividad_actual_lineas_h": round(prod_lineas_h, 1),
            "n_personas_actual": n_personas,
            "error": None,
        }
    except Exception as e:
        return {"forecast": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# COBERTURA CYCLE COUNTS
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def kpi_cobertura_cycle_counts(meses: int = 12) -> Dict:
    """% SKUs únicos auditados en últimos N meses sobre total SKUs activos."""
    from views._ops_data_helper import get_cycle_counts
    desde = (datetime.now() - timedelta(days=30 * meses)).strftime("%Y-%m-%d")
    counts = get_cycle_counts(desde_fecha=desde)
    skus_auditados = {c.get("sku") for c in counts if c.get("sku")}

    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        productos = odoo.search_read(
            "product.product",
            [("active", "=", True), ("type", "=", "product")],
            ["id"], limit=20000,
        )
        total_skus = len(productos)
        n_audit = len(skus_auditados)
        return {
            "valor": n_audit / total_skus if total_skus else None,
            "n_auditados": n_audit,
            "total_skus": total_skus,
            "n_cycle_counts": len(counts),
            "meses": meses,
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# TOP CLIENTES B2B CON PROBLEMAS DE OTIF
# ============================================================
@st.cache_data(ttl=43200, show_spinner=False)
def top_clientes_otif_problemas(dias: int = 30, top_n: int = 10) -> Dict:
    """Identifica clientes B2B con peor OTIF para foco de mejora."""
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": [], "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        pickings = odoo.search_read(
            "stock.picking",
            [("state", "=", "done"),
             ("date_done", ">=", desde),
             ("picking_type_code", "=", "outgoing"),
             ("partner_id.is_company", "=", True)],
            ["partner_id", "scheduled_date", "date_done"],
            limit=10000,
        )
        # Agrupar por cliente
        agg = defaultdict(lambda: {"total": 0, "tarde": 0})
        for p in pickings:
            if not p.get("partner_id"):
                continue
            pname = p["partner_id"][1]
            agg[pname]["total"] += 1
            sched = p.get("scheduled_date")
            done = p.get("date_done")
            if sched and done and done[:10] > sched[:10]:
                agg[pname]["tarde"] += 1

        result = []
        for cliente, d in agg.items():
            if d["total"] < 3:  # ignorar clientes con muy pocos pickings
                continue
            pct_tarde = d["tarde"] / d["total"]
            result.append({
                "cliente": cliente,
                "total": d["total"],
                "tarde": d["tarde"],
                "on_time_pct": (d["total"] - d["tarde"]) / d["total"],
            })
        # Ordenar por peor OTIF
        result.sort(key=lambda x: x["on_time_pct"])
        return {"valor": result[:top_n], "error": None}
    except Exception as e:
        return {"valor": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}
