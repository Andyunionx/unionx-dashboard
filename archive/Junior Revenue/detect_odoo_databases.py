"""
Script para detectar nombres de base de datos disponibles en Odoo
"""

import xmlrpc.client
from urllib.parse import urljoin

def get_available_databases(url):
    """Obtiene lista de bases de datos disponibles en un servidor Odoo"""
    try:
        url = url.rstrip('/')
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        databases = common.list()
        return databases
    except Exception as e:
        print(f"[ERROR] No se pudo conectar a {url}: {e}")
        return []


if __name__ == "__main__":
    print("=" * 70)
    print("DETECTANDO BASES DE DATOS DISPONIBLES")
    print("=" * 70)

    # PRODUCCIÓN
    prod_url = "https://unionxb2b.odoo.com"
    print(f"\n1. Conectando a: {prod_url}")
    print("-" * 70)

    prod_dbs = get_available_databases(prod_url)
    if prod_dbs:
        print(f"[OK] Bases de datos encontradas ({len(prod_dbs)}):")
        for db in prod_dbs:
            print(f"  - {db}")
    else:
        print("[ERROR] No se encontraron bases de datos")

    # TEST
    test_url = "https://test3-melollevo.odoo.com"
    print(f"\n2. Conectando a: {test_url}")
    print("-" * 70)

    test_dbs = get_available_databases(test_url)
    if test_dbs:
        print(f"[OK] Bases de datos encontradas ({len(test_dbs)}):")
        for db in test_dbs:
            print(f"  - {db}")
    else:
        print("[ERROR] No se encontraron bases de datos")

    print("\n" + "=" * 70)
    print("SIGUIENTE PASO:")
    print("=" * 70)
    print("Actualiza odoo_config.json con los nombres correctos de las DBs")
    print("Ejemplo:")
    print("""
  "produccion": {
    "url": "https://unionxb2b.odoo.com",
    "username": "andres@unionx.cl",
    "password": "ROTATED-2026-05-07",
    "db_name": "<aqui el nombre correcto>"
  }
    """)
