"""
Queries Odoo para análisis comercial-operacional.

Visualización pedidos / unidades / venta agregada por:
  - Mes
  - SKU (top movers)
  - Canal venta (B2C vs B2B vía partner.is_company)
  - Categoría producto (product.categ_id)
  - Marca (extraer de display_name si no hay campo brand)

Datos vienen de Odoo via OPS_ODOO_USER (cuenta servicio).
Cache 10 min en cada función (queries pesadas).
"""
from collections import defaultdict
from datetime import datetime, timedelta, date
from typing import Dict, List

import streamlit as st

from views._ops_odoo_helper import get_ops_odoo_client


def _mes_str(d: datetime) -> str:
    return f"{d.year}-{d.month:02d}"


def _rango_mes(anio: int, mes: int):
    desde = date(anio, mes, 1).strftime("%Y-%m-%d")
    if mes == 12:
        hasta = date(anio + 1, 1, 1).strftime("%Y-%m-%d")
    else:
        hasta = date(anio, mes + 1, 1).strftime("%Y-%m-%d")
    return desde, hasta


# ============================================================
# VENTAS POR MES (pedidos + unidades + monto)
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def ventas_por_mes(meses: int = 12) -> List[Dict]:
    """[{mes, n_pedidos, n_unidades, monto, ticket_promedio}, ...]
    Sale.orders en estado sale o done.
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return []

    out = []
    hoy = datetime.now()
    for i in range(meses, 0, -1):
        anio = hoy.year
        mes_n = hoy.month - i + 1
        while mes_n <= 0:
            mes_n += 12
            anio -= 1
        mes_str = f"{anio}-{mes_n:02d}"
        desde, hasta = _rango_mes(anio, mes_n)

        try:
            sos = odoo.search_read(
                "sale.order",
                [("state", "in", ["sale", "done"]),
                 ("date_order", ">=", desde),
                 ("date_order", "<", hasta)],
                ["id", "amount_total"],
                limit=20000,
            )
            n_pedidos = len(sos)
            monto = sum(s.get("amount_total", 0) for s in sos)
            so_ids = [s["id"] for s in sos]
            n_unidades = 0
            if so_ids:
                lines = odoo.search_read(
                    "sale.order.line",
                    [("order_id", "in", so_ids)],
                    ["product_uom_qty"], limit=200000,
                )
                n_unidades = sum(l.get("product_uom_qty", 0) for l in lines)

            out.append({
                "mes": mes_str,
                "n_pedidos": n_pedidos,
                "n_unidades": int(n_unidades),
                "monto": monto,
                "ticket_promedio": monto / n_pedidos if n_pedidos else 0,
            })
        except Exception:
            out.append({"mes": mes_str, "n_pedidos": 0, "n_unidades": 0,
                        "monto": 0, "ticket_promedio": 0, "error": True})
    return out


# ============================================================
# TOP SKUs (unidades + monto)
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def top_skus(dias: int = 90, top_n: int = 30) -> Dict:
    """Top SKUs por unidades vendidas en últimos N días."""
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"items": [], "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        sos = odoo.search_read(
            "sale.order",
            [("state", "in", ["sale", "done"]),
             ("date_order", ">=", desde)],
            ["id"],
            limit=50000,
        )
        if not sos:
            return {"items": [], "error": "Sin SO en ventana"}
        so_ids = [s["id"] for s in sos]

        lines = odoo.search_read(
            "sale.order.line",
            [("order_id", "in", so_ids)],
            ["product_id", "product_uom_qty", "price_subtotal", "order_id"],
            limit=300000,
        )

        agg = defaultdict(lambda: {"n_pedidos": set(), "unidades": 0, "monto": 0, "nombre": ""})
        for l in lines:
            if not l.get("product_id"):
                continue
            pid = l["product_id"][0]
            agg[pid]["nombre"] = l["product_id"][1]
            agg[pid]["unidades"] += l.get("product_uom_qty", 0) or 0
            agg[pid]["monto"] += l.get("price_subtotal", 0) or 0
            if l.get("order_id"):
                agg[pid]["n_pedidos"].add(l["order_id"][0])

        items = []
        for pid, info in agg.items():
            items.append({
                "product_id": pid,
                "sku": info["nombre"][:80],
                "n_pedidos": len(info["n_pedidos"]),
                "unidades": int(info["unidades"]),
                "monto": info["monto"],
                "ticket_promedio_uds": info["unidades"] / len(info["n_pedidos"]) if info["n_pedidos"] else 0,
            })
        items.sort(key=lambda x: -x["unidades"])
        return {
            "items": items[:top_n],
            "total_skus_distintos": len(items),
            "ventana_dias": dias,
            "error": None,
        }
    except Exception as e:
        return {"items": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# MIX POR CANAL (B2C / B2B)
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def ventas_por_canal(dias: int = 90) -> Dict:
    """Mix B2C vs B2B basado en partner.is_company."""
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"items": [], "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        sos = odoo.search_read(
            "sale.order",
            [("state", "in", ["sale", "done"]),
             ("date_order", ">=", desde)],
            ["id", "partner_id", "amount_total"],
            limit=50000,
        )
        if not sos:
            return {"items": [], "error": "Sin SO"}

        partner_ids = list({s["partner_id"][0] for s in sos if s.get("partner_id")})
        partners = odoo.search_read(
            "res.partner", [("id", "in", partner_ids)],
            ["id", "is_company"], limit=20000,
        )
        is_b2b = {p["id"]: p.get("is_company", False) for p in partners}

        b2c_count, b2b_count = 0, 0
        b2c_monto, b2b_monto = 0, 0
        b2c_pids, b2b_pids = set(), set()

        for s in sos:
            pid = s["partner_id"][0] if s.get("partner_id") else None
            monto = s.get("amount_total", 0) or 0
            if is_b2b.get(pid, False):
                b2b_count += 1
                b2b_monto += monto
                if pid: b2b_pids.add(pid)
            else:
                b2c_count += 1
                b2c_monto += monto
                if pid: b2c_pids.add(pid)

        return {
            "items": [
                {"canal": "B2C", "n_pedidos": b2c_count, "monto": b2c_monto,
                 "n_clientes": len(b2c_pids), "ticket_prom": b2c_monto / b2c_count if b2c_count else 0},
                {"canal": "B2B", "n_pedidos": b2b_count, "monto": b2b_monto,
                 "n_clientes": len(b2b_pids), "ticket_prom": b2b_monto / b2b_count if b2b_count else 0},
            ],
            "ventana_dias": dias,
            "error": None,
        }
    except Exception as e:
        return {"items": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# MIX POR CATEGORÍA
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def ventas_por_categoria(dias: int = 90) -> Dict:
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"items": [], "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        sos = odoo.search_read(
            "sale.order",
            [("state", "in", ["sale", "done"]),
             ("date_order", ">=", desde)],
            ["id"], limit=50000,
        )
        if not sos:
            return {"items": [], "error": "Sin SO"}

        so_ids = [s["id"] for s in sos]
        lines = odoo.search_read(
            "sale.order.line",
            [("order_id", "in", so_ids)],
            ["product_id", "product_uom_qty", "price_subtotal"],
            limit=300000,
        )

        # Cargar categorías de los productos
        product_ids = list({l["product_id"][0] for l in lines if l.get("product_id")})
        productos = odoo.search_read(
            "product.product",
            [("id", "in", product_ids)],
            ["id", "categ_id"], limit=20000,
        )
        cat_map = {p["id"]: (p["categ_id"][1] if p.get("categ_id") else "Sin categoría")
                   for p in productos}

        agg = defaultdict(lambda: {"unidades": 0, "monto": 0, "n_skus": set()})
        for l in lines:
            pid = l["product_id"][0] if l.get("product_id") else None
            cat = cat_map.get(pid, "Sin categoría")
            agg[cat]["unidades"] += l.get("product_uom_qty", 0) or 0
            agg[cat]["monto"] += l.get("price_subtotal", 0) or 0
            if pid:
                agg[cat]["n_skus"].add(pid)

        items = [{"categoria": k, "unidades": int(v["unidades"]),
                  "monto": v["monto"], "n_skus": len(v["n_skus"])}
                 for k, v in agg.items()]
        items.sort(key=lambda x: -x["monto"])
        return {"items": items, "ventana_dias": dias, "error": None}
    except Exception as e:
        return {"items": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# MIX POR MARCA (heurística: primer token del display_name)
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def ventas_por_marca(dias: int = 90) -> Dict:
    """Marca = primer token del display_name del producto.

    Heurística porque Odoo no tiene campo 'brand' standard.
    Si UnionX tiene un campo custom (x_marca, brand_id), modificar acá.
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"items": [], "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        sos = odoo.search_read(
            "sale.order",
            [("state", "in", ["sale", "done"]),
             ("date_order", ">=", desde)],
            ["id"], limit=50000,
        )
        if not sos:
            return {"items": [], "error": "Sin SO"}

        so_ids = [s["id"] for s in sos]
        lines = odoo.search_read(
            "sale.order.line",
            [("order_id", "in", so_ids)],
            ["product_id", "product_uom_qty", "price_subtotal"],
            limit=300000,
        )

        agg = defaultdict(lambda: {"unidades": 0, "monto": 0, "n_skus": set()})
        for l in lines:
            if not l.get("product_id"):
                continue
            pid = l["product_id"][0]
            nombre = l["product_id"][1] or ""
            # Heurística: extraer primer token significativo
            # Ej: "[OHNSO-PP01] Plancha pelo OHNSO PRO 2000W" → "OHNSO"
            marca = "Otros"
            if nombre:
                # Si el nombre arranca con [SKU]
                if nombre.startswith("[") and "]" in nombre:
                    sku_part = nombre[1:nombre.index("]")]
                    if "-" in sku_part:
                        marca = sku_part.split("-")[0]
                    elif "_" in sku_part:
                        marca = sku_part.split("_")[0]
                    else:
                        marca = sku_part
                else:
                    # Tomar primer palabra
                    tokens = nombre.split()
                    if tokens:
                        marca = tokens[0]
            agg[marca]["unidades"] += l.get("product_uom_qty", 0) or 0
            agg[marca]["monto"] += l.get("price_subtotal", 0) or 0
            agg[marca]["n_skus"].add(pid)

        items = [{"marca": k, "unidades": int(v["unidades"]),
                  "monto": v["monto"], "n_skus": len(v["n_skus"])}
                 for k, v in agg.items()]
        items.sort(key=lambda x: -x["monto"])
        return {"items": items, "ventana_dias": dias, "error": None,
                "nota": "Marca extraída del display_name (heurística)"}
    except Exception as e:
        return {"items": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# DETALLE CRUZADO: SKU x mes x canal
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def detalle_pedidos(dias: int = 90, top_n: int = 200) -> Dict:
    """Tabla detallada de pedidos con SKU, canal, categoría, marca."""
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"items": [], "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        sos = odoo.search_read(
            "sale.order",
            [("state", "in", ["sale", "done"]),
             ("date_order", ">=", desde)],
            ["id", "name", "date_order", "partner_id", "amount_total"],
            limit=top_n,
        )
        if not sos:
            return {"items": [], "error": "Sin SO"}

        # Partners
        partner_ids = list({s["partner_id"][0] for s in sos if s.get("partner_id")})
        partners = odoo.search_read(
            "res.partner", [("id", "in", partner_ids)],
            ["id", "is_company"], limit=10000,
        )
        is_b2b = {p["id"]: p.get("is_company", False) for p in partners}

        # Lines
        so_ids = [s["id"] for s in sos]
        lines = odoo.search_read(
            "sale.order.line",
            [("order_id", "in", so_ids)],
            ["order_id", "product_id", "product_uom_qty", "price_subtotal"],
            limit=200000,
        )

        # Categorías
        product_ids = list({l["product_id"][0] for l in lines if l.get("product_id")})
        productos = odoo.search_read(
            "product.product",
            [("id", "in", product_ids)],
            ["id", "categ_id"], limit=20000,
        )
        cat_map = {p["id"]: (p["categ_id"][1] if p.get("categ_id") else "")
                   for p in productos}

        sos_by_id = {s["id"]: s for s in sos}
        items = []
        for l in lines:
            sid = l["order_id"][0] if l.get("order_id") else None
            so = sos_by_id.get(sid)
            if not so:
                continue
            pid_prod = l["product_id"][0] if l.get("product_id") else None
            pname = l["product_id"][1] if l.get("product_id") else ""
            partner_id = so["partner_id"][0] if so.get("partner_id") else None
            partner_name = so["partner_id"][1] if so.get("partner_id") else ""
            canal = "B2B" if is_b2b.get(partner_id, False) else "B2C"

            # Marca heurística
            marca = "Otros"
            if pname.startswith("[") and "]" in pname:
                sku_part = pname[1:pname.index("]")]
                marca = sku_part.split("-")[0] if "-" in sku_part else sku_part

            items.append({
                "fecha": so.get("date_order", "")[:10],
                "pedido": so.get("name", ""),
                "cliente": partner_name[:40],
                "canal": canal,
                "sku": pname[:60],
                "categoria": cat_map.get(pid_prod, ""),
                "marca": marca,
                "unidades": int(l.get("product_uom_qty", 0) or 0),
                "monto": l.get("price_subtotal", 0) or 0,
            })
        items.sort(key=lambda x: x["fecha"], reverse=True)
        return {"items": items, "ventana_dias": dias, "error": None}
    except Exception as e:
        return {"items": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}
