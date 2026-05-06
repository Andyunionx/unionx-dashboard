"""
Diagnostico SOLO LECTURA: investiga por que las Guias de Despacho
muestran descripciones largas con HTML en los productos.

Revisa 4 campos candidatos:
  - product.template.description_sale       (pedido de venta)
  - product.template.description_pickingout (guia de despacho salida)
  - product.template.description_pickingin  (recepcion)
  - product.template.description            (interna)
  - stock.move.description_picking          (texto efectivo en GD)

Este script NO modifica nada.
"""
import json
import sys
import io
from pathlib import Path

# Forzar UTF-8 en stdout para evitar UnicodeEncodeError en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "finanzas-unionx" / "backend"))
from app.core.odoo_client import OdooClient  # type: ignore

CONFIG_PATH = Path(__file__).parent / "odoo_config.json"


def short(txt, n=140):
    if not txt:
        return "(vacio)"
    t = str(txt).replace("\n", " ").replace("\r", " ")
    return t[:n] + ("..." if len(t) > n else "")


def main():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)["produccion"]

    client = OdooClient(cfg["url"], cfg["db_name"], cfg["username"], cfg["password"])
    uid = client.authenticate()
    print(f"[OK] Conectado a Odoo produccion | UID={uid}")
    print("=" * 90)

    # ---------- CHECK 1: cuantos productos tienen cada campo ----------
    print("\n[CHECK 1] Conteo de productos con descripciones cargadas")
    print("-" * 90)
    total = client._execute_with_retry("search_count", "product.template", [], {})
    print(f"Total productos (product.template): {total}")

    for field in ["description_sale", "description_pickingout",
                  "description_pickingin", "description"]:
        cnt = client._execute_with_retry(
            "search_count", "product.template", [(field, "!=", False)], {}
        )
        with_br = client._execute_with_retry(
            "search_count", "product.template", [(field, "ilike", "<br")], {}
        )
        print(f"  {field:25s} | no_vacio={cnt:5d} | con_'<br'={with_br:5d}")

    # ---------- CHECK 2: muestras con HTML ----------
    print("\n[CHECK 2] Productos con '<br' en description_sale")
    print("-" * 90)
    sample = client.search_read(
        "product.template",
        [("description_sale", "ilike", "<br")],
        ["id", "default_code", "name", "description_sale"],
        limit=20,
    )
    for p in sample:
        print(f"  [{p['id']}] SKU={p.get('default_code')} | {p['name']}")
        print(f"    description_sale: {short(p.get('description_sale'))}")

    print("\n[CHECK 2b] Productos con '<br' en description_pickingout")
    print("-" * 90)
    sample2 = client.search_read(
        "product.template",
        [("description_pickingout", "ilike", "<br")],
        ["id", "default_code", "name", "description_pickingout"],
        limit=20,
    )
    for p in sample2:
        print(f"  [{p['id']}] SKU={p.get('default_code')} | {p['name']}")
        print(f"    description_pickingout: {short(p.get('description_pickingout'))}")

    # ---------- CHECK 3: templates QWeb del delivery slip ----------
    print("\n[CHECK 3] Templates QWeb relacionados con Guia/Delivery")
    print("-" * 90)
    views = client.search_read(
        "ir.ui.view",
        [
            "|", "|", "|",
            ("key", "ilike", "deliveryslip"),
            ("key", "ilike", "delivery_slip"),
            ("key", "ilike", "stock.report_delivery"),
            ("key", "ilike", "l10n_cl"),
        ],
        ["id", "name", "key", "type", "write_date", "write_uid", "inherit_id"],
        limit=50,
    )
    for v in views:
        inh = v.get("inherit_id")
        inh_name = inh[1] if inh else "-"
        print(f"  [{v['id']:6d}] key={v.get('key')}")
        print(f"         name={v.get('name')} | hereda_de={inh_name}")
        print(f"         modificado={v.get('write_date')} | por_uid={v.get('write_uid')}")

    # ---------- CHECK 4: ultimas pickings y sus description_picking ----------
    print("\n[CHECK 4] Ultimas 5 Guias de Despacho (outgoing done) y sus lineas")
    print("-" * 90)
    pickings = client.search_read(
        "stock.picking",
        [("state", "=", "done"), ("picking_type_code", "=", "outgoing")],
        ["id", "name", "partner_id", "date_done"],
        limit=5,
    )
    for pk in pickings:
        partner = pk.get("partner_id")
        partner_name = partner[1] if partner else "-"
        print(f"\n  Picking [{pk['id']}] {pk['name']} | {pk.get('date_done')} | {partner_name}")
        moves = client.search_read(
            "stock.move",
            [("picking_id", "=", pk["id"])],
            ["id", "product_id", "description_picking"],
            limit=10,
        )
        for m in moves:
            prod = m.get("product_id")
            prod_name = prod[1] if prod else "-"
            dp = m.get("description_picking") or ""
            print(f"    - move[{m['id']}] | product: {prod_name}")
            print(f"      description_picking: {short(dp)}")

    print("\n" + "=" * 90)
    print("[FIN] Diagnostico completado - no se modifico nada en Odoo")


if __name__ == "__main__":
    main()
