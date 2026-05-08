"""
Helpers de Stock Operacional (Vista Stock LIVE de la app Operaciones).

Foco operacional (a diferencia de la mirada comercial de la app Ventas):
  - SKUs duplicados (en múltiples ubicaciones físicas)
  - Tasa de uso de posiciones (movimientos recientes vs dormidas)
  - Alertas operacionales heurísticas

Datos vienen de Odoo via OPS_ODOO_USER (cuenta servicio).
Cache 5 min para evitar consultas repetidas.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

import streamlit as st

from views._ops_odoo_helper import get_ops_odoo_client


# ============================================================
# SKUs DUPLICADOS (en múltiples ubicaciones)
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def skus_duplicados(min_ubicaciones: int = 2) -> Dict:
    """SKUs que están en N o más ubicaciones físicas distintas.

    Útil para detectar:
      - Capital atado innecesario (mismo SKU disperso)
      - Riesgo de errores de picking
      - Candidatos a consolidación

    Args:
        min_ubicaciones: umbral mínimo (default: 2 = duplicado)
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": [], "error": "Odoo no disponible"}

    try:
        quants = odoo.search_read(
            "stock.quant",
            [("location_id.usage", "=", "internal"), ("quantity", ">", 0)],
            ["product_id", "location_id", "quantity", "value"],
            limit=50000,
        )
        if not quants:
            return {"valor": [], "error": "Sin quants"}

        # Agrupar por producto
        by_product = defaultdict(lambda: {"locations": [], "qty_total": 0, "valor": 0})
        for q in quants:
            if not q.get("product_id"):
                continue
            pid = q["product_id"][0]
            pname = q["product_id"][1]
            loc_name = q["location_id"][1] if q.get("location_id") else "?"
            qty = q.get("quantity", 0)
            val = q.get("value", 0)

            entry = by_product[pid]
            entry["nombre"] = pname
            entry["locations"].append({"loc": loc_name, "qty": qty, "valor": val})
            entry["qty_total"] += qty
            entry["valor"] += val

        # Filtrar SKUs con >= min_ubicaciones
        duplicados = []
        for pid, info in by_product.items():
            n_locs = len(info["locations"])
            if n_locs >= min_ubicaciones:
                # Top ubicación con mayor qty (sugerencia de consolidación)
                loc_principal = max(info["locations"], key=lambda x: x["qty"])
                duplicados.append({
                    "product_id": pid,
                    "sku": info["nombre"][:80],
                    "n_ubicaciones": n_locs,
                    "qty_total": info["qty_total"],
                    "valor": info["valor"],
                    "ubicaciones": [l["loc"] for l in info["locations"]],
                    "principal": loc_principal["loc"],
                    "qty_principal": loc_principal["qty"],
                })

        # Ordenar por valor (los más caros primero — más impacto)
        duplicados.sort(key=lambda x: x["valor"], reverse=True)

        return {
            "valor": duplicados,
            "total": len(duplicados),
            "valor_total": sum(d["valor"] for d in duplicados),
            "error": None,
        }
    except Exception as e:
        return {"valor": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# TASA DE USO DE POSICIONES
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def uso_posiciones(dias: int = 7) -> Dict:
    """Clasifica posiciones físicas según uso reciente.

    - Activas: con movimientos en últimos N días
    - Dormidas: con stock pero SIN movimientos en >30 días
    - Vacías: sin stock, disponibles para asignación

    Foco en CA1/Stock (bodega principal).
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    try:
        # 1. Todas las ubicaciones de CA1/Stock que sean leaves (sin hijos)
        locations = odoo.search_read(
            "stock.location",
            [("usage", "=", "internal"), ("complete_name", "ilike", "CA1/Stock/")],
            ["id", "complete_name", "child_ids", "quant_ids"],
            limit=10000,
        )
        leaf_locs = [l for l in locations if not l.get("child_ids")]
        loc_id_to_name = {l["id"]: l["complete_name"] for l in leaf_locs}

        if not leaf_locs:
            return {"valor": None, "error": "Sin posiciones CA1/Stock"}

        # 2. Movimientos recientes (últimos N días) por location
        desde_reciente = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
        moves_recientes = odoo.search_read(
            "stock.move",
            [("state", "=", "done"),
             ("date", ">=", desde_reciente),
             "|",
             ("location_id", "in", list(loc_id_to_name.keys())),
             ("location_dest_id", "in", list(loc_id_to_name.keys()))],
            ["location_id", "location_dest_id", "date"],
            limit=50000,
        )
        locs_activas = set()
        for m in moves_recientes:
            for k in ("location_id", "location_dest_id"):
                if m.get(k):
                    lid = m[k][0]
                    if lid in loc_id_to_name:
                        locs_activas.add(lid)

        # 3. Movimientos antiguos (>30d) — para detectar "dormidas"
        desde_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        moves_30d = odoo.search_read(
            "stock.move",
            [("state", "=", "done"),
             ("date", ">=", desde_30d),
             "|",
             ("location_id", "in", list(loc_id_to_name.keys())),
             ("location_dest_id", "in", list(loc_id_to_name.keys()))],
            ["location_id", "location_dest_id"],
            limit=50000,
        )
        locs_30d = set()
        for m in moves_30d:
            for k in ("location_id", "location_dest_id"):
                if m.get(k):
                    lid = m[k][0]
                    if lid in loc_id_to_name:
                        locs_30d.add(lid)

        # 4. Clasificar
        activas = []
        dormidas = []
        vacias = []
        for loc in leaf_locs:
            lid = loc["id"]
            tiene_stock = bool(loc.get("quant_ids"))
            es_activa = lid in locs_activas
            tuvo_mov_30d = lid in locs_30d

            entry = {
                "location_id": lid,
                "nombre": loc["complete_name"].replace("CA1/Stock/", ""),
                "n_skus": len(loc.get("quant_ids", [])),
            }

            if es_activa:
                activas.append(entry)
            elif tiene_stock and not tuvo_mov_30d:
                dormidas.append(entry)
            elif not tiene_stock:
                vacias.append(entry)
            # else: tiene stock + movimiento entre 7d y 30d — neutral, no clasificada

        total = len(leaf_locs)
        return {
            "valor": {
                "total_posiciones": total,
                "activas": len(activas),
                "dormidas": len(dormidas),
                "vacias": len(vacias),
                "neutral": total - len(activas) - len(dormidas) - len(vacias),
                "pct_activas": len(activas) / total if total else 0,
                "pct_dormidas": len(dormidas) / total if total else 0,
                "pct_vacias": len(vacias) / total if total else 0,
            },
            "detalle": {
                "activas": activas[:50],
                "dormidas": sorted(dormidas, key=lambda x: -x["n_skus"])[:50],
                "vacias": vacias[:50],
            },
            "ventana_dias": dias,
            "error": None,
        }
    except Exception as e:
        return {"valor": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ============================================================
# ALERTAS OPERACIONALES
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def alertas_operacionales() -> List[Dict]:
    """Heurísticas operacionales sobre el stock actual.

    Devuelve lista de alertas con severidad (CRITICA / ALTA / MEDIA).

    NOTA importante (feedback Andrés):
      - Odoo agrega bien CA1/Stock (las integraciones leen el padre)
      - Odoo dirige picking automáticamente al slot más cercano
      - Inventarios se hacen por producto o ubicación → ambos cuadran
    Por eso las alertas se enfocan en FRAGMENTACIÓN y CAPACIDAD m³,
    no en "duplicados" cuyo problema operacional ya está resuelto.
    """
    alertas = []

    # 1. Fragmentación: SKUs con qty pequeñas en múltiples slots
    try:
        from views._ops_capacidad_helper import slots_liberables, disponibilidad_posiciones
        from views._ops_data_helper import kpi_capacidad_recepcion

        sl = slots_liberables(umbral_qty_chico=5, min_ubicaciones=2)
        n_lib = sl.get("slots_liberables_total", 0)
        if n_lib >= 30:
            alertas.append({
                "severidad": "ALTA",
                "tipo": "Fragmentación de slotting",
                "mensaje": f"{n_lib} posiciones liberables consolidando {sl.get('skus_a_consolidar', 0)} SKUs con fragmentos (qty ≤5)",
                "accion": "Revisar tab Eficiencia de slotting → exportar plan de consolidación",
            })
        elif n_lib >= 10:
            alertas.append({
                "severidad": "MEDIA",
                "tipo": "Fragmentación de slotting",
                "mensaje": f"{n_lib} posiciones liberables consolidando fragmentos",
                "accion": "Plan de consolidación semanal recomendado",
            })

        # 2. Capacidad m³ vs próximos embarques
        disp = disponibilidad_posiciones()
        m3_libre = disp.get("totales", {}).get("m3_libre", 0) if disp.get("totales") else 0
        cap = kpi_capacidad_recepcion(m3_libre)
        if cap.get("proximo_embarque") and not cap.get("ok"):
            pe = cap["proximo_embarque"]
            alertas.append({
                "severidad": "CRITICA",
                "tipo": "Capacidad insuficiente embarque",
                "mensaje": f"Próx embarque {pe.get('eta', '?')} requiere {pe.get('m3', 0):.0f} m³ "
                           f"(disp actual: {m3_libre:.0f} m³)",
                "accion": "Liquidar slow movers + consolidar fragmentos YA, o renegociar ETA",
            })

        # 3. Ocupación general bodega
        pct_ocup = disp.get("totales", {}).get("pct_ocupacion", 0) if disp.get("totales") else 0
        if pct_ocup >= 90:
            alertas.append({
                "severidad": "CRITICA",
                "tipo": "Bodega saturada",
                "mensaje": f"Ocupación {pct_ocup:.0f}% — riesgo bloqueo recepción",
                "accion": "Plan urgente: liquidar slow movers + consolidación + revisar embarques entrantes",
            })
        elif pct_ocup >= 80:
            alertas.append({
                "severidad": "ALTA",
                "tipo": "Bodega cercana al límite",
                "mensaje": f"Ocupación {pct_ocup:.0f}% — espacio limitado para nuevos embarques",
                "accion": "Plan de consolidación + revisar liquidación slow movers",
            })
    except Exception:
        pass

    # 4. Posiciones dormidas (SKUs sin rotación ocupando capacidad)
    uso = uso_posiciones(dias=7)
    if uso.get("valor"):
        pct_dormidas = uso["valor"].get("pct_dormidas", 0)
        n_dormidas = uso["valor"].get("dormidas", 0)
        if pct_dormidas > 0.20:
            alertas.append({
                "severidad": "ALTA",
                "tipo": "Posiciones dormidas",
                "mensaje": f"{n_dormidas} posiciones ({pct_dormidas*100:.0f}%) con stock sin movs >30d",
                "accion": "Revisar SKUs — candidatos a liquidación / promociones",
            })

        n_vacias = uso["valor"].get("vacias", 0)
        pct_vacias = uso["valor"].get("pct_vacias", 0)
        if pct_vacias < 0.10 and n_vacias < 20:
            alertas.append({
                "severidad": "CRITICA",
                "tipo": "Pocas posiciones vacías",
                "mensaje": f"Solo {n_vacias} posiciones vacías ({pct_vacias*100:.0f}%) — riesgo recepción",
                "accion": "Liberar capacidad antes del próximo embarque",
            })

    return alertas


# ============================================================
# RANKING POSICIONES POR ACTIVIDAD
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def ranking_posiciones_actividad(dias: int = 30, top_n: int = 30) -> List[Dict]:
    """Top N posiciones con mayor cantidad de movimientos (in/out) en últimos N días.

    Útil para entender qué posiciones son las más "calientes" y deberían tener
    los SKUs A (rotación alta) cerca del área de packing.
    """
    odoo = get_ops_odoo_client()
    if odoo is None:
        return []

    try:
        # Locations CA1/Stock leaves
        locations = odoo.search_read(
            "stock.location",
            [("usage", "=", "internal"), ("complete_name", "ilike", "CA1/Stock/")],
            ["id", "complete_name", "child_ids"],
            limit=10000,
        )
        leaf_loc_ids = [l["id"] for l in locations if not l.get("child_ids")]
        loc_id_to_name = {l["id"]: l["complete_name"].replace("CA1/Stock/", "")
                          for l in locations if not l.get("child_ids")}

        if not leaf_loc_ids:
            return []

        # Moves desde/hacia esas locs
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
        moves = odoo.search_read(
            "stock.move",
            [("state", "=", "done"),
             ("date", ">=", desde),
             "|",
             ("location_id", "in", leaf_loc_ids),
             ("location_dest_id", "in", leaf_loc_ids)],
            ["location_id", "location_dest_id", "product_uom_qty"],
            limit=100000,
        )

        # Contar movimientos por loc
        counts = defaultdict(lambda: {"out": 0, "in": 0, "qty_out": 0, "qty_in": 0})
        for m in moves:
            qty = m.get("product_uom_qty", 0)
            if m.get("location_id"):
                lid = m["location_id"][0]
                if lid in loc_id_to_name:
                    counts[lid]["out"] += 1
                    counts[lid]["qty_out"] += qty
            if m.get("location_dest_id"):
                lid = m["location_dest_id"][0]
                if lid in loc_id_to_name:
                    counts[lid]["in"] += 1
                    counts[lid]["qty_in"] += qty

        # Build ranking
        result = []
        for lid, c in counts.items():
            total_mov = c["out"] + c["in"]
            if total_mov == 0:
                continue
            result.append({
                "posicion": loc_id_to_name.get(lid, "?"),
                "salidas": c["out"],
                "entradas": c["in"],
                "total_movs": total_mov,
                "qty_movida": c["qty_out"] + c["qty_in"],
            })

        result.sort(key=lambda x: -x["total_movs"])
        return result[:top_n]
    except Exception:
        return []
