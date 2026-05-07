"""
LIMPIEZA: Vaciar description_pickingout y description_pickingin
en productos que tienen HTML de marketing cargado.

Autorizado por Andrés Browne - 17/04/2026
"""
import json
import sys
import io
import xmlrpc.client
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CONFIG_PATH = Path(__file__).parent / "odoo_config.json"


def limpiar_campo(models, db, uid, password, campo):
    # Buscar IDs de productos con HTML en ese campo
    ids = models.execute_kw(
        db, uid, password,
        "product.template", "search",
        [[(campo, "ilike", "<br")]]
    )
    total = len(ids)
    print(f"\n  Campo: {campo}")
    print(f"  Productos encontrados con HTML: {total}")

    if total == 0:
        print("  Nada que limpiar.")
        return 0

    # Ejecutar write para vaciar el campo (llamada XML-RPC directa)
    resultado = models.execute_kw(
        db, uid, password,
        "product.template", "write",
        [ids, {campo: False}]
    )

    if resultado:
        print(f"  [OK] {total} productos limpiados exitosamente.")
    else:
        print(f"  [ERROR] No se pudo limpiar el campo.")

    return total


def main():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)["produccion"]

    import os
    url      = cfg["url"]
    db       = cfg["db_name"]
    username = cfg["username"]
    password = cfg.get("password") or os.getenv("ANDRES_ODOO_PASSWORD")
    if not password:
        raise RuntimeError("Password no encontrada. Setear env var ANDRES_ODOO_PASSWORD")

    # Autenticar
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, username, password, {})
    if not uid:
        print("[ERROR] Autenticacion fallida.")
        sys.exit(1)
    print(f"[OK] Conectado a Odoo produccion | UID={uid}")

    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    print("=" * 70)
    print("LIMPIEZA: description_pickingout y description_pickingin")
    print("=" * 70)

    total_out = limpiar_campo(models, db, uid, password, "description_pickingout")
    total_in  = limpiar_campo(models, db, uid, password, "description_pickingin")

    print("\n" + "=" * 70)
    print(f"[RESUMEN] Limpieza completada:")
    print(f"  description_pickingout: {total_out} productos")
    print(f"  description_pickingin:  {total_in} productos")
    print("=" * 70)


if __name__ == "__main__":
    main()
