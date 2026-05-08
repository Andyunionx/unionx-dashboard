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
# OFR — Order Fulfillment Rate
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
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
@st.cache_data(ttl=300, show_spinner=False)
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
@st.cache_data(ttl=300, show_spinner=False)
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
@st.cache_data(ttl=600, show_spinner=False)
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
                ["picking_id", "product_uom_qty", "quantity_done"],
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
                if all((m.get("quantity_done") or 0) >= (m.get("product_uom_qty") or 0) for m in mvs):
                    if b2b:
                        otif_b2b_count += 1
                    else:
                        otif_b2c_count += 1

            # Pick Accuracy = moves OK / total moves
            ok = sum(1 for m in moves
                     if (m.get("quantity_done") or 0) == (m.get("product_uom_qty") or 0))
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
# COBERTURA CYCLE COUNTS
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
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
