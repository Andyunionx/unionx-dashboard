"""
Servicio avanzado de Stock — port del stock_dashboard.py Streamlit.

Calcula:
- Días de stock por SKU (basado en venta diaria 30d)
- Rotación 30d/90d en unidades y en costo
- Semáforo (5 categorías: QUIEBRE, CRITICO, BAJO, OPTIMO, SOBRESTOCK, SIN VENTA)
- Ocupación CA1/Stock (% posiciones físicas usadas)
- Tipo de ubicación: Fulfillment / Marketing / PV-Outlet / Planner

Reusa OdooClient del backend.
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Callable, Optional, List

import pandas as pd

from app.core.odoo_client import OdooClient


FULFILLMENT_KEYWORDS = ["BFML", "BFP", "BFR", "BFW", "Fulfillment", "fulfillment"]
MARKETING_KEYWORDS = ["Mk", "Marketing", "BMPE", "BMPN", "BMPVS"]
PV_OUTLET_KEYWORDS = ["BPV", "Post Venta", "Outlet", "Bo"]


class StockAdvancedService:
    """Servicio avanzado: stock + ventas 30d/90d + semáforo + ocupación."""

    def __init__(self, odoo: OdooClient):
        self.odoo = odoo

    # ============================================================
    # PASO 1: Extracción cruda desde Odoo
    # ============================================================
    def _fetch_locations(self) -> Dict:
        locs = self.odoo.search_read(
            'stock.location',
            [('usage', '=', 'internal')],
            ['id', 'complete_name', 'name', 'child_ids', 'quant_ids'],
            limit=10000,
        )
        return {l["id"]: l for l in locs}

    def _fetch_quants(self) -> List[Dict]:
        return self.odoo.search_read(
            'stock.quant',
            [('location_id.usage', '=', 'internal'), ('quantity', '>', 0)],
            ['location_id', 'product_id', 'product_categ_id', 'quantity',
             'reserved_quantity', 'available_quantity', 'value'],
            limit=50000,
        )

    def _fetch_products(self) -> Dict:
        prods = self.odoo.search_read(
            'product.product',
            [('is_storable', '=', True), ('active', '=', True)],
            ['id', 'name', 'default_code', 'barcode', 'categ_id', 'brand_id', 'avg_cost',
             'standard_price', 'list_price', 'qty_available', 'free_qty', 'uom_id'],
            limit=20000,
        )
        return {p["id"]: p for p in prods}

    def _fetch_sales_30_90(self) -> Dict:
        f90 = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        f30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        sales = self.odoo.search_read(
            'sale.order.line',
            [('order_id.date_order', '>=', f90),
             ('order_id.state', 'in', ['sale', 'done'])],
            ['product_id', 'product_uom_qty', 'price_subtotal', 'order_id'],
            limit=200000,
        )

        # Cargar fechas de orden para clasificar 30d vs 90d
        order_ids = list({s["order_id"][0] for s in sales if s.get("order_id")})
        order_dates = {}
        if order_ids:
            orders = self.odoo.execute_in_batches(
                'sale.order', order_ids, ['id', 'date_order'], batch_size=500
            )
            order_dates = {o["id"]: (o["date_order"][:10] if o.get("date_order") else "")
                           for o in orders}

        v30_qty, v30_cost = defaultdict(float), defaultdict(float)
        v90_qty, v90_cost = defaultdict(float), defaultdict(float)

        for s in sales:
            pid = s["product_id"][0] if s.get("product_id") else None
            if not pid:
                continue
            oid = s["order_id"][0] if s.get("order_id") else 0
            fecha = order_dates.get(oid, "")
            qty = s.get("product_uom_qty", 0) or 0
            subtotal = s.get("price_subtotal", 0) or 0

            v90_qty[pid] += qty
            v90_cost[pid] += subtotal
            if fecha >= f30:
                v30_qty[pid] += qty
                v30_cost[pid] += subtotal

        return {
            "v30_qty": dict(v30_qty), "v30_cost": dict(v30_cost),
            "v90_qty": dict(v90_qty), "v90_cost": dict(v90_cost),
        }

    # ============================================================
    # PASO 2: Cálculo de ocupación CA1/Stock
    # ============================================================
    @staticmethod
    def compute_occupancy(locations: Dict) -> Dict:
        """Calcula tasa de ocupación: posiciones físicas = hijas directas de CA1/Stock."""
        positions = []
        for lid, loc in locations.items():
            cn = loc.get("complete_name", "")
            if not cn.startswith("CA1/Stock/"):
                continue
            is_leaf = len(loc.get("child_ids", [])) == 0
            if not is_leaf:
                continue
            has_stock = len(loc.get("quant_ids", [])) > 0
            n_quants = len(loc.get("quant_ids", []))
            pos_name = cn.replace("CA1/Stock/", "")
            positions.append({
                "Posicion": pos_name,
                "Ubicacion": cn,
                "Estado": "Ocupada" if has_stock else "Vacia",
                "SKUs": n_quants,
            })

        total = len(positions)
        occupied = sum(1 for p in positions if p["Estado"] == "Ocupada")
        return {
            "positions": positions,
            "total": total,
            "occupied": occupied,
            "empty": total - occupied,
            "pct": round(occupied / total * 100, 1) if total > 0 else 0,
        }

    # ============================================================
    # PASO 3: Procesamiento + Semáforo
    # ============================================================
    @staticmethod
    def _classify_location(complete_name: str) -> str:
        cn_up = complete_name.upper()
        if any(k.upper() in cn_up for k in FULFILLMENT_KEYWORDS):
            return "Fulfillment"
        if any(k.upper() in cn_up for k in MARKETING_KEYWORDS):
            return "Marketing"
        if any(k.upper() in cn_up for k in PV_OUTLET_KEYWORDS):
            return "PV/Outlet"
        return "Planner"

    @staticmethod
    def _semaforo(qty: float, dias_stock: float, vta_30d: float) -> str:
        if qty == 0 and vta_30d > 0:
            return "QUIEBRE"
        if dias_stock < 30:
            return "CRITICO"
        if dias_stock < 90:
            return "BAJO"
        if dias_stock <= 180:
            return "OPTIMO"
        if dias_stock > 180 and vta_30d > 0:
            return "SOBRESTOCK"
        return "SIN VENTA"

    def process(self, locations: Dict, quants: List, products: Dict, ventas: Dict):
        """Construye DataFrame completo + agregado por SKU con semáforo."""
        v30_qty = ventas["v30_qty"]
        v30_cost = ventas["v30_cost"]
        v90_qty = ventas["v90_qty"]
        v90_cost = ventas["v90_cost"]

        rows = []
        for q in quants:
            pid = q["product_id"][0] if q.get("product_id") else None
            prod = products.get(pid, {})
            loc_id = q["location_id"][0] if q.get("location_id") else None
            loc = locations.get(loc_id, {})
            cn = loc.get("complete_name", "?")
            parts = cn.split("/")
            parent = "/".join(parts[:2]).strip() if len(parts) >= 2 else cn

            qty = q.get("quantity", 0) or 0
            res = q.get("reserved_quantity", 0) or 0
            avail = q.get("available_quantity", 0) or 0
            val = q.get("value", 0) or 0
            cu = prod.get("avg_cost", 0) or prod.get("standard_price", 0) or 0
            if qty > 0 and val == 0:
                val = qty * cu

            # SKU con fallback SOLO para productos activos (los que están en el
            # maestro; los inactivos quedan con SKU vacío = fuera del detalle por SKU).
            # default_code -> código [entre corchetes] en el nombre -> barcode -> nombre.
            sku = (prod.get("default_code") or "").strip()
            if prod and not sku:
                _m = re.search(r"\[([^\]]+)\]", prod.get("name", "") or "")
                sku = (_m.group(1).strip() if _m
                       else (prod.get("barcode") or "").strip()
                       or (prod.get("name") or "").strip())

            rows.append({
                "product_id": pid,
                "SKU": sku,
                "Producto": prod.get("name", q["product_id"][1] if q.get("product_id") else "?"),
                "Categoria": (prod.get("categ_id") or [0, ""])[1],
                "Marca": (prod.get("brand_id") or [0, ""])[1] if isinstance(prod.get("brand_id"), (list, tuple)) else "",
                "UdM": (prod.get("uom_id") or [0, ""])[1],
                "Bodega": parent,
                "Ubicacion": cn,
                "Tipo": self._classify_location(cn),
                "Qty": qty, "Reservada": res, "Disponible": avail,
                "Costo Unit": cu, "Valor": val,
                "Vta 30d Qty": v30_qty.get(pid, 0),
                "Vta 30d $": v30_cost.get(pid, 0),
                "Vta 90d Qty": v90_qty.get(pid, 0),
                "Vta 90d $": v90_cost.get(pid, 0),
            })

        df = pd.DataFrame(rows)
        if df.empty:
            return df, pd.DataFrame()

        # Agregar por SKU
        agg = df.groupby("product_id").agg({
            "SKU": "first", "Producto": "first", "Categoria": "first", "Marca": "first", "UdM": "first",
            "Qty": "sum", "Reservada": "sum", "Disponible": "sum",
            "Costo Unit": "first", "Valor": "sum",
            "Vta 30d Qty": "first", "Vta 30d $": "first",
            "Vta 90d Qty": "first", "Vta 90d $": "first",
            "Bodega": lambda x: ", ".join(sorted(set(x))),
        }).reset_index()

        # Días de stock
        agg["Vta Diaria"] = agg["Vta 30d Qty"] / 30
        agg["Dias Stock"] = agg.apply(
            lambda r: round(r["Qty"] / r["Vta Diaria"]) if r["Vta Diaria"] > 0 else 999,
            axis=1
        )

        # Rotación en unidades
        agg["Rot 30d Uds"] = agg.apply(
            lambda r: round(r["Vta 30d Qty"] / r["Qty"], 2) if r["Qty"] > 0 else 0, axis=1
        )
        agg["Rot 90d Uds"] = agg.apply(
            lambda r: round(r["Vta 90d Qty"] / r["Qty"], 2) if r["Qty"] > 0 else 0, axis=1
        )

        # Rotación en costo
        agg["Costo Vta 30d"] = agg["Vta 30d Qty"] * agg["Costo Unit"]
        agg["Costo Vta 90d"] = agg["Vta 90d Qty"] * agg["Costo Unit"]
        agg["Rot 30d $"] = agg.apply(
            lambda r: round(r["Costo Vta 30d"] / r["Valor"], 2) if r["Valor"] > 0 else 0, axis=1
        )
        agg["Rot 90d $"] = agg.apply(
            lambda r: round(r["Costo Vta 90d"] / r["Valor"], 2) if r["Valor"] > 0 else 0, axis=1
        )

        # Semáforo
        agg["Semaforo"] = agg.apply(
            lambda r: self._semaforo(r["Qty"], r["Dias Stock"], r["Vta 30d Qty"]), axis=1
        )

        return df, agg

    # ============================================================
    # PASO 4: Punto de entrada principal
    # ============================================================
    def extract_full(self, progress_callback: Optional[Callable] = None) -> Dict:
        """Extrae todo + procesa + devuelve estructura para el frontend."""
        def progress(pct, label):
            if progress_callback:
                progress_callback(pct, label)

        progress(10, "Cargando ubicaciones...")
        locations = self._fetch_locations()

        progress(25, "Cargando quants...")
        quants = self._fetch_quants()

        progress(45, "Cargando productos...")
        products = self._fetch_products()

        progress(65, "Cargando ventas 90 días...")
        ventas = self._fetch_sales_30_90()

        progress(80, "Calculando ocupación CA1/Stock...")
        ocupacion = self.compute_occupancy(locations)

        progress(90, "Procesando semáforo y rotación...")
        df_full, df_agg = self.process(locations, quants, products, ventas)

        progress(100, "Completado")

        # Resúmenes para frontend
        resumen_kpis = self._kpis_resumen(df_agg)
        resumen_semaforo = self._semaforo_distribution(df_agg)
        resumen_bodega = self._valor_por_bodega(df_full)

        return {
            "metadata": {
                "generado_en": datetime.now().isoformat(),
                "total_skus": int(len(df_agg)),
                "total_quants": int(len(quants)),
                "total_locations": int(len(locations)),
            },
            "kpis": resumen_kpis,
            "ocupacion": ocupacion,
            "semaforo": resumen_semaforo,
            "valor_bodega": resumen_bodega,
            "skus": df_agg.to_dict(orient="records"),
            "detalle": df_full.to_dict(orient="records"),
        }

    @staticmethod
    def _kpis_resumen(df_agg: pd.DataFrame) -> Dict:
        if df_agg.empty:
            return {}
        n_skus = len(df_agg)
        total_val = float(df_agg["Valor"].sum())
        total_qty = float(df_agg["Qty"].sum())

        n_quiebre = int(len(df_agg[df_agg["Semaforo"].str.contains("QUIEBRE|CRITICO", regex=True)]))
        n_bajo = int(len(df_agg[df_agg["Semaforo"] == "BAJO"]))
        n_optimo = int(len(df_agg[df_agg["Semaforo"] == "OPTIMO"]))
        n_sobre = int(len(df_agg[df_agg["Semaforo"] == "SOBRESTOCK"]))
        n_sinventa = int(len(df_agg[df_agg["Semaforo"] == "SIN VENTA"]))

        rot_30d = df_agg[df_agg["Rot 30d Uds"] > 0]["Rot 30d Uds"]
        rot_90d = df_agg[df_agg["Rot 90d Uds"] > 0]["Rot 90d Uds"]

        return {
            "n_skus": n_skus,
            "valor_total": round(total_val, 2),
            "unidades_total": round(total_qty, 2),
            "costo_promedio_sku": round(total_val / n_skus, 2) if n_skus else 0,
            "n_quiebre_critico": n_quiebre,
            "n_bajo": n_bajo,
            "n_optimo": n_optimo,
            "n_sobrestock": n_sobre,
            "n_sin_venta": n_sinventa,
            "rot_30d_promedio": round(float(rot_30d.mean()), 2) if len(rot_30d) > 0 else 0,
            "rot_90d_promedio": round(float(rot_90d.mean()), 2) if len(rot_90d) > 0 else 0,
        }

    @staticmethod
    def _semaforo_distribution(df_agg: pd.DataFrame) -> List[Dict]:
        if df_agg.empty:
            return []
        dist = df_agg["Semaforo"].value_counts().reset_index()
        dist.columns = ["Categoria", "SKUs"]
        return dist.to_dict(orient="records")

    @staticmethod
    def _valor_por_bodega(df_full: pd.DataFrame) -> List[Dict]:
        if df_full.empty:
            return []
        agg = df_full.groupby("Bodega").agg({
            "Valor": "sum",
            "Qty": "sum",
            "product_id": "nunique",
        }).reset_index()
        agg.columns = ["Bodega", "Valor", "Unidades", "SKUs"]
        agg = agg.sort_values("Valor", ascending=False)
        agg["Valor"] = agg["Valor"].round(2)
        agg["Unidades"] = agg["Unidades"].round(2)
        return agg.to_dict(orient="records")
