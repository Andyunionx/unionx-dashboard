"""
Helpers de capacidad m³ y eficiencia de slotting (app Operaciones).

Foco operacional real (con feedback de Andrés):
  - Disponibilidad m³ por posición (cuánto cabe en cada slot)
  - Slots liberables (consolidando SKUs con qty pequeñas por posición)
  - Slotting subóptimo (SKUs A en zona fría)
  - Forecasting capacidad para próximos embarques

Datos de m³:
  1. product.volume de Odoo (si está cargado)
  2. Fallback: m³ por categoría manual (vista carga manual)
  3. Fallback final: estimación con avg general

Cache 5 min.
"""
from collections import defaultdict
from typing import Dict, List, Optional

import streamlit as st

from views._ops_odoo_helper import get_ops_odoo_client
from views._ops_data_helper import (
    get_capacidad_bodega,
    get_capacidad_slot_default,
    get_all_m3_categoria,
)


# ============================================================
# VOLUMEN POR PRODUCTO (Odoo + fallback manual)
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def get_volumen_productos() -> Dict[int, Dict]:
    """{product_id: {volume_m3, categ, source}}.

    source:
      - 'odoo' si product.volume > 0
      - 'categoria' si caemos al fallback manual por categoría
      - 'sin_dato' si no hay nada
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {}

    # 1. Productos activos con stock
    productos = odoo.search_read(
        "product.product",
        [("active", "=", True), ("type", "=", "product")],
        ["id", "display_name", "volume", "categ_id"],
        limit=20000,
    )

    m3_cat = get_all_m3_categoria()  # {nombre_categ: m3_unit}

    out = {}
    for p in productos:
        pid = p["id"]
        odoo_vol = p.get("volume", 0) or 0
        categ_name = p["categ_id"][1] if p.get("categ_id") else ""
        if odoo_vol > 0:
            out[pid] = {"volume_m3": odoo_vol, "categ": categ_name, "source": "odoo"}
        elif categ_name in m3_cat and m3_cat[categ_name] > 0:
            out[pid] = {"volume_m3": m3_cat[categ_name], "categ": categ_name, "source": "categoria"}
        else:
            out[pid] = {"volume_m3": 0, "categ": categ_name, "source": "sin_dato"}
    return out


# ============================================================
# DISPONIBILIDAD m³ POR POSICIÓN
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def disponibilidad_posiciones() -> Dict:
    """Por cada posición leaf de CA1/Stock devuelve:
      - m³ totales (capacidad slot)
      - m³ ocupados (sum quant.qty * product.volume)
      - m³ libres
      - % ocupación
      - n_skus
      - n_unidades
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"posiciones": [], "error": "Odoo no disponible"}

    try:
        # 1. Leaf locations CA1/Stock
        locations = odoo.search_read(
            "stock.location",
            [("usage", "=", "internal"), ("complete_name", "ilike", "CA1/Stock/")],
            ["id", "complete_name", "child_ids"],
            limit=10000,
        )
        leaf_locs = [l for l in locations if not l.get("child_ids")]
        if not leaf_locs:
            return {"posiciones": [], "error": "Sin posiciones leaf en CA1/Stock"}

        leaf_loc_ids = [l["id"] for l in leaf_locs]
        loc_id_to_name = {l["id"]: l["complete_name"].replace("CA1/Stock/", "")
                          for l in leaf_locs}

        # 2. Quants por location
        quants = odoo.search_read(
            "stock.quant",
            [("location_id", "in", leaf_loc_ids), ("quantity", ">", 0)],
            ["product_id", "location_id", "quantity", "value"],
            limit=100000,
        )

        # 3. Volúmenes por producto
        vols = get_volumen_productos()

        # 4. Capacidad por slot (default global, hasta tener data por slot)
        cap_slot_default = get_capacidad_slot_default()
        if cap_slot_default <= 0:
            # Fallback: si tenemos m3_totales bodega → dividir entre # slots
            cap_total = get_capacidad_bodega().get("m3_totales") or 0
            if cap_total > 0 and len(leaf_locs) > 0:
                cap_slot_default = cap_total / len(leaf_locs)

        # 5. Agregar por location
        loc_data = defaultdict(lambda: {
            "m3_ocupado": 0, "n_skus": 0, "n_unidades": 0, "valor": 0,
            "skus_sin_volumen": 0,
        })
        for q in quants:
            if not q.get("location_id"):
                continue
            lid = q["location_id"][0]
            pid = q["product_id"][0] if q.get("product_id") else None
            qty = q.get("quantity", 0) or 0
            valor = q.get("value", 0) or 0
            d = loc_data[lid]
            d["n_skus"] += 1
            d["n_unidades"] += qty
            d["valor"] += valor
            if pid and pid in vols:
                v = vols[pid].get("volume_m3", 0)
                if v > 0:
                    d["m3_ocupado"] += qty * v
                else:
                    d["skus_sin_volumen"] += 1
            else:
                d["skus_sin_volumen"] += 1

        # 6. Build resultado
        posiciones = []
        for lid, name in loc_id_to_name.items():
            d = loc_data.get(lid, {
                "m3_ocupado": 0, "n_skus": 0, "n_unidades": 0, "valor": 0,
                "skus_sin_volumen": 0,
            })
            cap = cap_slot_default
            ocupado = d["m3_ocupado"]
            libre = max(cap - ocupado, 0)
            pct = (ocupado / cap * 100) if cap > 0 else 0
            posiciones.append({
                "posicion": name,
                "m3_capacidad": round(cap, 3),
                "m3_ocupado": round(ocupado, 3),
                "m3_libre": round(libre, 3),
                "pct_ocupacion": round(pct, 1),
                "n_skus": d["n_skus"],
                "n_unidades": int(d["n_unidades"]),
                "valor": d["valor"],
                "estado": (
                    "VACIA" if d["n_skus"] == 0
                    else "LLENA" if pct >= 90
                    else "DISPONIBLE" if pct < 50
                    else "MEDIO"
                ),
                "calidad_dato": (
                    "completa" if d["skus_sin_volumen"] == 0 else f"{d['skus_sin_volumen']} SKUs sin volumen"
                ),
            })

        # Totales agregados
        total_cap = sum(p["m3_capacidad"] for p in posiciones)
        total_ocup = sum(p["m3_ocupado"] for p in posiciones)
        total_libre = sum(p["m3_libre"] for p in posiciones)

        return {
            "posiciones": posiciones,
            "totales": {
                "m3_capacidad": round(total_cap, 1),
                "m3_ocupado": round(total_ocup, 1),
                "m3_libre": round(total_libre, 1),
                "pct_ocupacion": round(total_ocup / total_cap * 100, 1) if total_cap > 0 else 0,
                "n_posiciones": len(posiciones),
                "n_vacias": sum(1 for p in posiciones if p["estado"] == "VACIA"),
                "n_disponibles": sum(1 for p in posiciones if p["estado"] in ("VACIA", "DISPONIBLE")),
                "n_llenas": sum(1 for p in posiciones if p["estado"] == "LLENA"),
            },
            "config": {
                "m3_slot_default": cap_slot_default,
                "fuente_volumen_odoo": sum(1 for v in get_volumen_productos().values() if v.get("source") == "odoo"),
                "fuente_volumen_categ": sum(1 for v in get_volumen_productos().values() if v.get("source") == "categoria"),
                "fuente_volumen_sin_dato": sum(1 for v in get_volumen_productos().values() if v.get("source") == "sin_dato"),
            },
            "error": None,
        }
    except Exception as e:
        return {"posiciones": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# SLOTS LIBERABLES (eficiencia de slotting)
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def slots_liberables(umbral_qty_chico: int = 5, min_ubicaciones: int = 2) -> Dict:
    """SKUs en N+ posiciones donde algunas tienen qty <= umbral_qty_chico.

    Lógica: si un SKU está en 3 slots con qty (50, 3, 2), los 2 slots con qty
    chica son candidatos a consolidar al slot con qty 50, liberando 2 posiciones
    sin afectar la operación.

    Args:
        umbral_qty_chico: qty por debajo de la cual el slot es 'fragmento'
        min_ubicaciones: mínimo de slots para considerar SKU
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"items": [], "error": "Odoo no disponible"}

    try:
        quants = odoo.search_read(
            "stock.quant",
            [("location_id.usage", "=", "internal"),
             ("location_id.complete_name", "ilike", "CA1/Stock/"),
             ("quantity", ">", 0)],
            ["product_id", "location_id", "quantity", "value"],
            limit=80000,
        )
        if not quants:
            return {"items": [], "error": "Sin quants"}

        by_product = defaultdict(lambda: {"slots": [], "qty_total": 0, "valor_total": 0})
        for q in quants:
            if not q.get("product_id"):
                continue
            pid = q["product_id"][0]
            pname = q["product_id"][1]
            loc_name = q["location_id"][1].replace("CA1/Stock/", "") if q.get("location_id") else "?"
            qty = q.get("quantity", 0)
            val = q.get("value", 0)
            entry = by_product[pid]
            entry["nombre"] = pname
            entry["slots"].append({"loc": loc_name, "qty": qty, "valor": val})
            entry["qty_total"] += qty
            entry["valor_total"] += val

        items = []
        slots_liberables_total = 0
        for pid, info in by_product.items():
            if len(info["slots"]) < min_ubicaciones:
                continue
            slot_principal = max(info["slots"], key=lambda x: x["qty"])
            fragmentos = [s for s in info["slots"]
                          if s["loc"] != slot_principal["loc"] and s["qty"] <= umbral_qty_chico]
            if not fragmentos:
                continue  # SKU bien repartido, no hay fragmentos
            slots_liberables_total += len(fragmentos)
            items.append({
                "product_id": pid,
                "sku": info["nombre"][:80],
                "n_ubicaciones": len(info["slots"]),
                "qty_total": info["qty_total"],
                "valor_total": info["valor_total"],
                "slot_principal": slot_principal["loc"],
                "qty_principal": slot_principal["qty"],
                "n_fragmentos": len(fragmentos),
                "slots_a_liberar": [f["loc"] for f in fragmentos],
                "qty_a_mover": sum(f["qty"] for f in fragmentos),
            })

        items.sort(key=lambda x: -x["n_fragmentos"])
        return {
            "items": items,
            "slots_liberables_total": slots_liberables_total,
            "skus_a_consolidar": len(items),
            "umbral_qty": umbral_qty_chico,
            "error": None,
        }
    except Exception as e:
        return {"items": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# SLOTTING SUBÓPTIMO (SKUs A en zona fría)
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def slotting_suboptimo(top_n_a: int = 50, dias_actividad: int = 30) -> Dict:
    """SKUs Top A (alta rotación) ubicados en posiciones de baja actividad.

    Cruza:
      - Top N SKUs por movimientos (salidas) en últimos N días
      - Posiciones donde están y su % de actividad

    Si un SKU A está en zona "fría" (posición con bajo tráfico relativo),
    es candidato a re-slotting hacia posiciones cercanas al packing.
    """
    from datetime import datetime, timedelta
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"items": [], "error": "Odoo no disponible"}

    try:
        desde = (datetime.now() - timedelta(days=dias_actividad)).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Locations CA1/Stock
        locations = odoo.search_read(
            "stock.location",
            [("usage", "=", "internal"), ("complete_name", "ilike", "CA1/Stock/")],
            ["id", "complete_name", "child_ids"],
            limit=10000,
        )
        leaf_locs = [l for l in locations if not l.get("child_ids")]
        leaf_loc_ids = [l["id"] for l in leaf_locs]
        loc_id_to_name = {l["id"]: l["complete_name"].replace("CA1/Stock/", "")
                          for l in leaf_locs}

        # 2. Movimientos (salidas) últimos N días
        moves = odoo.search_read(
            "stock.move",
            [("state", "=", "done"),
             ("date", ">=", desde),
             ("location_id", "in", leaf_loc_ids)],  # salida desde CA1
            ["product_id", "location_id", "product_uom_qty"],
            limit=100000,
        )

        # SKU → total movimientos
        sku_movs = defaultdict(lambda: {"qty_movida": 0, "n_movs": 0, "nombre": ""})
        loc_movs = defaultdict(int)
        for m in moves:
            if not m.get("product_id"):
                continue
            pid = m["product_id"][0]
            sku_movs[pid]["nombre"] = m["product_id"][1]
            sku_movs[pid]["qty_movida"] += m.get("product_uom_qty", 0)
            sku_movs[pid]["n_movs"] += 1
            if m.get("location_id"):
                loc_movs[m["location_id"][0]] += 1

        if not sku_movs:
            return {"items": [], "error": "Sin movimientos"}

        # 3. Top A SKUs por qty movida
        top_a = sorted(sku_movs.items(), key=lambda x: -x[1]["qty_movida"])[:top_n_a]
        top_a_pids = {pid for pid, _ in top_a}

        # 4. Quants actuales de los top A
        quants = odoo.search_read(
            "stock.quant",
            [("product_id", "in", list(top_a_pids)),
             ("location_id", "in", leaf_loc_ids),
             ("quantity", ">", 0)],
            ["product_id", "location_id", "quantity"],
            limit=10000,
        )

        # 5. Clasificar zonas: caliente (top 20% movs) vs fría (bottom 50%)
        loc_movs_sorted = sorted(loc_movs.items(), key=lambda x: -x[1])
        n_top20 = max(1, int(len(loc_movs_sorted) * 0.2))
        n_bot50 = max(1, int(len(loc_movs_sorted) * 0.5))
        zonas_calientes = {lid for lid, _ in loc_movs_sorted[:n_top20]}
        zonas_frias = {lid for lid, _ in loc_movs_sorted[-n_bot50:]}

        # 6. Items: SKUs A en zona fría
        items = []
        for q in quants:
            pid = q["product_id"][0]
            lid = q["location_id"][0]
            if lid in zonas_frias and lid not in zonas_calientes:
                items.append({
                    "sku": q["product_id"][1][:80],
                    "posicion_actual": loc_id_to_name.get(lid, "?"),
                    "qty_en_slot": q["quantity"],
                    "movimientos_30d": sku_movs[pid]["n_movs"],
                    "qty_movida_30d": sku_movs[pid]["qty_movida"],
                    "movs_posicion_actual": loc_movs.get(lid, 0),
                })

        items.sort(key=lambda x: -x["qty_movida_30d"])

        return {
            "items": items,
            "n_skus_a_relocar": len(items),
            "ventana_dias": dias_actividad,
            "n_zonas_calientes": len(zonas_calientes),
            "n_zonas_frias": len(zonas_frias),
            "error": None,
        }
    except Exception as e:
        return {"items": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}
