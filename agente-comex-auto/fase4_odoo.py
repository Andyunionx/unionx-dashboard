"""FASE 4 — Carga de la PO en Odoo (borrador).

Con todos los SKU creados (fase 3), esta fase:
1. Re-costea el embarque para obtener el costo INTERNADO por unidad (CLP).
2. Arma la PO en Odoo: Topwill (1664), moneda CLP (45), picking type 1 (Carrascal),
   una línea por producto con price_unit = costo_internado_unit (CLP), qty del PI.
3. date_planned (recepción) = ETA bodega del estado (Seimex + 5).
4. La deja en BORRADOR (state=draft) para el OK de Andrés.

⚠️ Escribe en Odoo PRODUCCIÓN. dry_run=True (default) solo muestra la PO que crearía.
"""
import os
import sys
import xmlrpc.client
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE.parent / "_REACTIVAR_NUEVO_PC"))
import costear_embarque as ce      # noqa: E402
import estado as st                 # noqa: E402
import fase3_costeo as f3           # noqa: E402  (reusa resolver_archivos + construir_tarifas)

URL = "https://unionxb2b.odoo.com"; DB = "bmya-innovatek-sh-prd-6981800"
PARTNER_TOPWILL = 1664
PICKING_CARRASCAL = 1
CURRENCY_CLP = 45
COMPANY = 1


def _odoo():
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD")
    uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, "andres@grupoeter.cl", pwd, {})
    return xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object"), uid, pwd


def _costear(reg, emb_num) -> ce.Embarque:
    pi_path, pl_path = f3.resolver_archivos(reg)
    productos, inland, numero, puerto = ce.leer_pi(pi_path)
    ce.leer_pl(pl_path, productos)
    tar = f3.construir_tarifas(reg, puerto)
    embq = ce.Embarque(numero=numero or emb_num, puerto=puerto,
                       puerto_nombre=f3.PUERTOS.get(puerto, puerto),
                       productos=productos, inland_china=inland, tarifas=tar)
    ce.calcular_costeo(embq)
    return embq


def procesar_embarque(emb_num: str, reg: dict, dry_run: bool = True):
    embq = _costear(reg, emb_num)
    models, uid, pwd = _odoo()

    # resolver product_id por SKU y armar líneas
    lineas, sin_producto = [], []
    for p in embq.productos:
        sku = (p.sku or "").strip()
        pid = None
        if sku:
            r = models.execute_kw(DB, uid, pwd, "product.product", "search_read",
                                  [[["default_code", "=", sku]]], {"fields": ["id"], "limit": 1})
            pid = r[0]["id"] if r else None
        if not pid:
            sin_producto.append(f"{p.model}/{sku or 'SIN-SKU'}")
            continue
        lineas.append((0, 0, {
            "product_id": pid, "name": p.descripcion or p.model,
            "product_qty": p.qty, "price_unit": round(p.costo_internado_unit, 2),
        }))

    fecha = (reg.get("eta_bodega") or reg.get("eta_puerto") or "")[:10]
    date_planned = f"{fecha} 12:00:00" if fecha else False
    total_clp = sum(l[2]["product_qty"] * l[2]["price_unit"] for l in lineas)

    print(f"\n=== PO {emb_num} (borrador) ===")
    print(f"  Proveedor: Topwill (1664) · Moneda: CLP · Recepción: Bodega Carrascal (pt 1)")
    print(f"  date_planned (ETA bodega): {date_planned}")
    print(f"  Líneas: {len(lineas)} · Total internado: {total_clp:,.0f} CLP")
    if sin_producto:
        print(f"  ⚠️ {len(sin_producto)} productos SIN product_id (no van a la PO): {sin_producto}")
    for l in lineas[:5]:
        print(f"    · prod {l[2]['product_id']:<6} qty {l[2]['product_qty']:>5.0f} × {l[2]['price_unit']:>10,.0f} CLP  {l[2]['name'][:32]}")
    if len(lineas) > 5:
        print(f"    · ... (+{len(lineas)-5} líneas)")

    if dry_run:
        st.log(reg, f"PO dry-run: {len(lineas)} líneas · {total_clp:,.0f} CLP · ETA {date_planned} (NO escrita)")
        return

    if not lineas:
        st.log(reg, "PO NO creada: sin líneas resolubles")
        return
    po_id = models.execute_kw(DB, uid, pwd, "purchase.order", "create", [{
        "partner_id": PARTNER_TOPWILL, "picking_type_id": PICKING_CARRASCAL,
        "currency_id": CURRENCY_CLP, "company_id": COMPANY,
        "partner_ref": f"{embq.numero}PI", "date_planned": date_planned,
        "order_line": lineas,
    }])
    po = models.execute_kw(DB, uid, pwd, "purchase.order", "read", [[po_id]], {"fields": ["name"]})[0]
    reg["po_id"] = po_id; reg["po_name"] = po["name"]
    st.log(reg, f"PO {po['name']} creada en BORRADOR ({len(lineas)} líneas, {total_clp:,.0f} CLP)")
    st.set_fase(reg, 9, f"PO {po['name']} cargada en borrador → COMPLETADO")


def procesar(dry_run: bool = True) -> dict:
    estado = st.cargar()
    pend = [e for e, r in estado.items() if r.get("fase") == 4]
    if not pend:
        print("No hay embarques en fase 4.")
        return estado
    print(f"Embarques en fase 4 (carga PO): {pend}")
    for emb in pend:
        try:
            procesar_embarque(emb, estado[emb], dry_run=dry_run)
        except Exception as e:
            st.log(estado[emb], f"ERROR carga PO: {type(e).__name__}: {e}")
    st.guardar(estado)
    return estado


if __name__ == "__main__":
    dry = "--commit" not in sys.argv
    print(f"=== FASE 4 · carga PO Odoo {'(DRY-RUN, no escribe)' if dry else '(COMMIT — escribe en Odoo)'} ===")
    procesar(dry_run=dry)
