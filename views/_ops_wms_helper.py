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
from typing import Dict, List, Optional

import streamlit as st

from views._ops_odoo_helper import get_ops_odoo_client


# ============================================================
# OTIF B2C / B2B
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
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
        # Esto requiere consultar move_lines (más caro, hacer en lote)
        picking_ids = [p["id"] for p in pickings]
        moves = odoo.search_read(
            "stock.move",
            [("picking_id", "in", picking_ids)],
            ["picking_id", "product_uom_qty", "quantity_done", "state"],
            limit=200000,
        )
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
                (m.get("quantity_done") or 0) >= (m.get("product_uom_qty") or 0)
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
            if all((m.get("quantity_done") or 0) >= (m.get("product_uom_qty") or 0) for m in mvs):
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
@st.cache_data(ttl=300, show_spinner=False)
def kpi_pick_accuracy(dias: int = 30) -> Dict:
    """Pick Accuracy = moves sin discrepancia / total moves done en ventana.

    Discrepancia = qty_done != product_uom_qty (en valor absoluto, tolerancia 0).
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        moves = odoo.search_read(
            "stock.move",
            [("state", "=", "done"),
             ("date", ">=", desde),
             ("picking_type_id.code", "=", "outgoing")],
            ["product_uom_qty", "quantity_done"],
            limit=200000,
        )
        if not moves:
            return {"valor": None, "error": "Sin moves en ventana"}

        ok = sum(1 for m in moves
                 if (m.get("quantity_done") or 0) == (m.get("product_uom_qty") or 0))
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
@st.cache_data(ttl=300, show_spinner=False)
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
@st.cache_data(ttl=300, show_spinner=False)
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
# TOP CLIENTES B2B CON PROBLEMAS DE OTIF
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
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
