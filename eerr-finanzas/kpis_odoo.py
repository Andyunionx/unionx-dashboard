"""
Wrappers de OdooClient para los KPIs operacionales y financieros.

Cada funcion devuelve un dict con valor + metadata para mostrar en dashboards.
Manejo robusto de errores: si Odoo falla, devuelve None + mensaje (no crashea).

Funciones expuestas:
- get_odoo_client(): factory cacheada del cliente
- kpi_dio(): Days Inventory Outstanding
- kpi_dso(): Days Sales Outstanding (B2B)
- kpi_dpo(): Days Payable Outstanding
- kpi_ccc(): Cash Conversion Cycle
- kpi_aov(): Average Order Value
- kpi_yoy_ingresos(): crecimiento ingresos YoY YTD
- kpi_repeat_customer(): tasa de recompra
- kpi_clientes_b2b_activos(): conteo
- kpi_top_clientes_b2b(): top N por venta
- kpi_morosidad_b2b(): % cartera vencida >30d
- kpi_abc_inventario(): clasificacion ABC con datos
- kpi_slow_movers(): SKUs sin venta >180d
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Importar OdooClient del backend
_BACKEND = PROJECT_ROOT / "finanzas-unionx" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from app.core.odoo_client import OdooClient
    from app.config import Config
    _ODOO_DISPONIBLE = True
except Exception as _e:
    _ODOO_DISPONIBLE = False
    _IMPORT_ERROR = str(_e)


_client_cache = None


def get_odoo_client() -> Optional["OdooClient"]:
    """Devuelve cliente Odoo singleton. None si no se puede conectar."""
    global _client_cache
    if not _ODOO_DISPONIBLE:
        return None
    if _client_cache is not None:
        return _client_cache
    try:
        # La password viene de env var ANDRES_ODOO_PASSWORD via Config
        if not Config.ODOO_PASSWORD:
            return None
        _client_cache = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
        # Test rápido
        _client_cache.authenticate()
        return _client_cache
    except Exception:
        return None


def _safe_query(fn, default=None, error_msg=""):
    """Wrapper que captura excepciones y devuelve default + mensaje."""
    try:
        return {"valor": fn(), "error": None}
    except Exception as e:
        return {"valor": default, "error": f"{error_msg}: {str(e)[:120]}"}


# ============================================================================
# KPIs FINANCIEROS — Capital de trabajo
# ============================================================================

def kpi_dio(odoo: "OdooClient" = None) -> dict:
    """Days Inventory Outstanding = Inventario / (CMV anual / 365).

    Inventario actual = sum(qty * standard_price) en stock.quant.
    CMV = sum(price_subtotal) de líneas de account.move tipo out_invoice
          con producto cuyo type='product' (heuristico para CMV).
    """
    if odoo is None:
        odoo = get_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    def _calc():
        # 1. Inventario valorizado actual
        quants = odoo.search_read(
            'stock.quant',
            [('location_id.usage', '=', 'internal'), ('quantity', '>', 0)],
            ['product_id', 'quantity'],
            limit=20000,
        )
        if not quants:
            return None
        product_ids = list({q['product_id'][0] for q in quants if q.get('product_id')})

        # 2. Costo unitario (standard_price) de esos productos
        productos = odoo.execute_in_batches(
            'product.product', product_ids,
            ['id', 'standard_price'], batch_size=100,
        )
        cost_map = {p['id']: p.get('standard_price', 0) for p in productos}

        # 3. Inventario valorizado total
        inv_valorizado = sum(q['quantity'] * cost_map.get(q['product_id'][0], 0) for q in quants)

        # 4. CMV últimos 365 días (suma de cost de productos vendidos)
        un_anio_atras = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        lineas_venta = odoo.search_read(
            'sale.order.line',
            [('order_id.date_order', '>=', un_anio_atras),
             ('order_id.state', 'in', ['sale', 'done'])],
            ['product_id', 'product_uom_qty', 'purchase_price'],
            limit=200000,
        )
        cmv_anual = sum(l.get('product_uom_qty', 0) * l.get('purchase_price', 0) for l in lineas_venta)
        if cmv_anual <= 0:
            return None
        return inv_valorizado / (cmv_anual / 365)

    return _safe_query(_calc, error_msg="DIO")


def kpi_dso(odoo: "OdooClient" = None) -> dict:
    """Days Sales Outstanding = CxC / (Venta diaria).

    CxC = sum amount_residual de account.move tipo out_invoice posted no pagados.
    Venta diaria = venta últimos 365 / 365.
    """
    if odoo is None:
        odoo = get_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    def _calc():
        cxc_movs = odoo.search_read(
            'account.move',
            [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
             ('payment_state', 'in', ['not_paid', 'partial', 'in_payment'])],
            ['amount_residual'],
            limit=20000,
        )
        cxc_total = sum(m.get('amount_residual', 0) for m in cxc_movs)

        un_anio_atras = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        ventas = odoo.search_read(
            'account.move',
            [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
             ('invoice_date', '>=', un_anio_atras)],
            ['amount_total'],
            limit=20000,
        )
        venta_anual = sum(v.get('amount_total', 0) for v in ventas)
        if venta_anual <= 0:
            return None
        return cxc_total / (venta_anual / 365)

    return _safe_query(_calc, error_msg="DSO")


def kpi_dpo(odoo: "OdooClient" = None) -> dict:
    """Days Payable Outstanding = CxP / (Compras diarias)."""
    if odoo is None:
        odoo = get_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    def _calc():
        cxp_movs = odoo.search_read(
            'account.move',
            [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
             ('payment_state', 'in', ['not_paid', 'partial', 'in_payment'])],
            ['amount_residual'],
            limit=20000,
        )
        cxp_total = sum(m.get('amount_residual', 0) for m in cxp_movs)

        un_anio_atras = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        compras = odoo.search_read(
            'account.move',
            [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
             ('invoice_date', '>=', un_anio_atras)],
            ['amount_total'],
            limit=20000,
        )
        compras_anual = sum(c.get('amount_total', 0) for c in compras)
        if compras_anual <= 0:
            return None
        return cxp_total / (compras_anual / 365)

    return _safe_query(_calc, error_msg="DPO")


def kpi_ccc(odoo: "OdooClient" = None) -> dict:
    """Cash Conversion Cycle = DIO + DSO - DPO."""
    odoo = odoo or get_odoo_client()
    dio = kpi_dio(odoo)
    dso = kpi_dso(odoo)
    dpo = kpi_dpo(odoo)
    if dio["valor"] is None or dso["valor"] is None or dpo["valor"] is None:
        return {"valor": None, "error": "Falta DIO/DSO/DPO", "componentes": {"DIO": dio, "DSO": dso, "DPO": dpo}}
    return {
        "valor": dio["valor"] + dso["valor"] - dpo["valor"],
        "error": None,
        "componentes": {"DIO": dio["valor"], "DSO": dso["valor"], "DPO": dpo["valor"]},
    }


def kpi_morosidad_b2b(odoo: "OdooClient" = None, dias_corte: int = 30) -> dict:
    """% morosidad B2B = cartera vencida >N días / cartera total B2B."""
    odoo = odoo or get_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    def _calc():
        # Heuristic: B2B = partner.is_company == True
        cxc = odoo.search_read(
            'account.move',
            [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
             ('payment_state', 'in', ['not_paid', 'partial']),
             ('partner_id.is_company', '=', True)],
            ['amount_residual', 'invoice_date_due'],
            limit=20000,
        )
        if not cxc:
            return 0.0
        hoy = datetime.now().date()
        total = sum(m.get('amount_residual', 0) for m in cxc)
        vencido = 0
        for m in cxc:
            due = m.get('invoice_date_due')
            if not due:
                continue
            try:
                due_date = datetime.strptime(due, '%Y-%m-%d').date()
                if (hoy - due_date).days > dias_corte:
                    vencido += m.get('amount_residual', 0)
            except Exception:
                pass
        if total <= 0:
            return 0.0
        return vencido / total

    return _safe_query(_calc, error_msg="Morosidad B2B")


# ============================================================================
# KPIs COMERCIALES
# ============================================================================

def kpi_aov(odoo: "OdooClient" = None, dias: int = 90) -> dict:
    """Average Order Value en últimos N días."""
    odoo = odoo or get_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    def _calc():
        desde = (datetime.now() - timedelta(days=dias)).strftime('%Y-%m-%d')
        ordenes = odoo.search_read(
            'sale.order',
            [('date_order', '>=', desde), ('state', 'in', ['sale', 'done'])],
            ['amount_total'],
            limit=50000,
        )
        if not ordenes:
            return None
        return sum(o.get('amount_total', 0) for o in ordenes) / len(ordenes)

    return _safe_query(_calc, error_msg="AOV")


def kpi_yoy_ingresos(odoo: "OdooClient" = None) -> dict:
    """% Var YoY ingresos YTD: venta YTD año actual vs mismo período año anterior."""
    odoo = odoo or get_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    def _calc():
        hoy = datetime.now()
        ini_actual = f"{hoy.year}-01-01"
        fin_actual = hoy.strftime('%Y-%m-%d')
        ini_anterior = f"{hoy.year - 1}-01-01"
        fin_anterior = (hoy.replace(year=hoy.year - 1)).strftime('%Y-%m-%d')

        actual = odoo.search_read(
            'sale.order',
            [('date_order', '>=', ini_actual), ('date_order', '<=', fin_actual),
             ('state', 'in', ['sale', 'done'])],
            ['amount_total'], limit=100000,
        )
        anterior = odoo.search_read(
            'sale.order',
            [('date_order', '>=', ini_anterior), ('date_order', '<=', fin_anterior),
             ('state', 'in', ['sale', 'done'])],
            ['amount_total'], limit=100000,
        )
        v_actual = sum(o.get('amount_total', 0) for o in actual)
        v_anterior = sum(o.get('amount_total', 0) for o in anterior)
        if v_anterior <= 0:
            return None
        return (v_actual - v_anterior) / v_anterior

    return _safe_query(_calc, error_msg="YoY")


def kpi_repeat_customer(odoo: "OdooClient" = None, dias: int = 180) -> dict:
    """Tasa de recompra = % partners con >=2 órdenes en últimos N días."""
    odoo = odoo or get_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    def _calc():
        desde = (datetime.now() - timedelta(days=dias)).strftime('%Y-%m-%d')
        ordenes = odoo.search_read(
            'sale.order',
            [('date_order', '>=', desde), ('state', 'in', ['sale', 'done'])],
            ['partner_id'],
            limit=200000,
        )
        if not ordenes:
            return None
        from collections import Counter
        counter = Counter(o['partner_id'][0] for o in ordenes if o.get('partner_id'))
        total_partners = len(counter)
        repetidos = sum(1 for c in counter.values() if c >= 2)
        if total_partners == 0:
            return 0.0
        return repetidos / total_partners

    return _safe_query(_calc, error_msg="Repeat customer")


def kpi_clientes_b2b_activos(odoo: "OdooClient" = None, dias: int = 90) -> dict:
    """N° clientes B2B (is_company) con orden en últimos N días."""
    odoo = odoo or get_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    def _calc():
        desde = (datetime.now() - timedelta(days=dias)).strftime('%Y-%m-%d')
        ordenes = odoo.search_read(
            'sale.order',
            [('date_order', '>=', desde), ('state', 'in', ['sale', 'done']),
             ('partner_id.is_company', '=', True)],
            ['partner_id'],
            limit=100000,
        )
        if not ordenes:
            return 0
        return len({o['partner_id'][0] for o in ordenes if o.get('partner_id')})

    return _safe_query(_calc, error_msg="Clientes B2B")


def kpi_top_clientes_b2b(odoo: "OdooClient" = None, dias: int = 365, top_n: int = 10) -> dict:
    """Top N clientes B2B por venta YTD."""
    odoo = odoo or get_odoo_client()
    if odoo is None:
        return {"valor": [], "error": "Odoo no disponible"}

    def _calc():
        desde = (datetime.now() - timedelta(days=dias)).strftime('%Y-%m-%d')
        ordenes = odoo.search_read(
            'sale.order',
            [('date_order', '>=', desde), ('state', 'in', ['sale', 'done']),
             ('partner_id.is_company', '=', True)],
            ['partner_id', 'amount_total'],
            limit=200000,
        )
        from collections import defaultdict
        agg = defaultdict(lambda: {"venta": 0, "ordenes": 0, "nombre": ""})
        for o in ordenes:
            if not o.get('partner_id'):
                continue
            pid, pname = o['partner_id'][0], o['partner_id'][1]
            agg[pid]["venta"] += o.get('amount_total', 0)
            agg[pid]["ordenes"] += 1
            agg[pid]["nombre"] = pname
        top = sorted(agg.items(), key=lambda x: x[1]["venta"], reverse=True)[:top_n]
        return [{"partner_id": pid, "nombre": d["nombre"], "venta": d["venta"], "ordenes": d["ordenes"]} for pid, d in top]

    return _safe_query(_calc, default=[], error_msg="Top clientes")


# ============================================================================
# KPIs FULFILLMENT — Inventario
# ============================================================================

def kpi_abc_inventario(odoo: "OdooClient" = None) -> dict:
    """Clasifica SKUs en A/B/C por valor de venta últimos 365 días.

    A: top 80% del valor acumulado
    B: siguiente 15%
    C: bottom 5%
    """
    odoo = odoo or get_odoo_client()
    if odoo is None:
        return {"valor": [], "error": "Odoo no disponible"}

    def _calc():
        un_anio = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        lineas = odoo.search_read(
            'sale.order.line',
            [('order_id.date_order', '>=', un_anio),
             ('order_id.state', 'in', ['sale', 'done'])],
            ['product_id', 'product_uom_qty', 'price_subtotal'],
            limit=300000,
        )
        if not lineas:
            return []
        from collections import defaultdict
        agg = defaultdict(lambda: {"qty": 0, "venta": 0, "nombre": ""})
        for l in lineas:
            if not l.get('product_id'):
                continue
            pid, pname = l['product_id'][0], l['product_id'][1]
            agg[pid]["qty"] += l.get('product_uom_qty', 0)
            agg[pid]["venta"] += l.get('price_subtotal', 0)
            agg[pid]["nombre"] = pname

        # Ordenar por venta descendente
        sorted_skus = sorted(agg.items(), key=lambda x: x[1]["venta"], reverse=True)
        venta_total = sum(d["venta"] for _, d in sorted_skus)
        if venta_total <= 0:
            return []

        result = []
        acumulado = 0
        for pid, d in sorted_skus:
            acumulado += d["venta"]
            pct = acumulado / venta_total
            if pct <= 0.80:
                clase = "A"
            elif pct <= 0.95:
                clase = "B"
            else:
                clase = "C"
            result.append({
                "product_id": pid,
                "nombre": d["nombre"],
                "qty_vendida": d["qty"],
                "venta": d["venta"],
                "pct_acumulado": pct,
                "clase": clase,
            })
        return result

    return _safe_query(_calc, default=[], error_msg="ABC inventario")


def kpi_slow_movers(odoo: "OdooClient" = None, dias: int = 180) -> dict:
    """SKUs sin venta en últimos N días pero con stock > 0."""
    odoo = odoo or get_odoo_client()
    if odoo is None:
        return {"valor": [], "error": "Odoo no disponible"}

    def _calc():
        # 1. Productos vendidos en los últimos N días
        desde = (datetime.now() - timedelta(days=dias)).strftime('%Y-%m-%d')
        lineas = odoo.search_read(
            'sale.order.line',
            [('order_id.date_order', '>=', desde),
             ('order_id.state', 'in', ['sale', 'done'])],
            ['product_id'], limit=200000,
        )
        productos_vendidos = {l['product_id'][0] for l in lineas if l.get('product_id')}

        # 2. Productos en stock con qty > 0
        quants = odoo.search_read(
            'stock.quant',
            [('location_id.usage', '=', 'internal'), ('quantity', '>', 0)],
            ['product_id', 'quantity'],
            limit=20000,
        )
        from collections import defaultdict
        stock_map = defaultdict(lambda: {"qty": 0, "nombre": ""})
        for q in quants:
            if not q.get('product_id'):
                continue
            pid, pname = q['product_id'][0], q['product_id'][1]
            stock_map[pid]["qty"] += q['quantity']
            stock_map[pid]["nombre"] = pname

        # 3. Slow movers = en stock pero NO vendido
        result = []
        for pid, d in stock_map.items():
            if pid not in productos_vendidos:
                result.append({
                    "product_id": pid,
                    "nombre": d["nombre"],
                    "stock": d["qty"],
                })
        return sorted(result, key=lambda x: x["stock"], reverse=True)

    return _safe_query(_calc, default=[], error_msg="Slow movers")


def kpi_stockouts_skus_a(odoo: "OdooClient" = None) -> dict:
    """% SKUs A con stock <= mínimo (orderpoint)."""
    odoo = odoo or get_odoo_client()
    if odoo is None:
        return {"valor": None, "error": "Odoo no disponible"}

    def _calc():
        # 1. Obtener SKUs A
        abc = kpi_abc_inventario(odoo)
        skus_a = [item["product_id"] for item in (abc.get("valor") or []) if item.get("clase") == "A"]
        if not skus_a:
            return None

        # 2. Buscar orderpoints de esos SKUs
        ops = odoo.search_read(
            'stock.warehouse.orderpoint',
            [('product_id', 'in', skus_a)],
            ['product_id', 'product_min_qty'],
            limit=20000,
        )
        if not ops:
            return None

        # 3. Stock actual
        quants = odoo.search_read(
            'stock.quant',
            [('product_id', 'in', skus_a), ('location_id.usage', '=', 'internal')],
            ['product_id', 'quantity'], limit=20000,
        )
        from collections import defaultdict
        stock_map = defaultdict(float)
        for q in quants:
            if q.get('product_id'):
                stock_map[q['product_id'][0]] += q['quantity']

        # 4. Contar stockouts
        with_stockout = 0
        for op in ops:
            pid = op['product_id'][0]
            actual = stock_map.get(pid, 0)
            min_qty = op.get('product_min_qty', 0)
            if min_qty > 0 and actual <= min_qty:
                with_stockout += 1
        if not ops:
            return None
        return with_stockout / len(ops)

    return _safe_query(_calc, error_msg="Stockouts A")
