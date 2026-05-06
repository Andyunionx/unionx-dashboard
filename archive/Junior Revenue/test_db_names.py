"""
Prueba variaciones de nombres de base de datos
"""

import xmlrpc.client


def test_db(url, db_name, username, password):
    """Intenta autenticarse con un nombre de BD específico"""
    try:
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        uid = common.authenticate(db_name, username, password, {})

        if uid:
            return f"[OK] ENCONTRADA: {db_name} -> UID: {uid}"
        else:
            return f"[FAIL] {db_name} (autenticación rechazada)"

    except Exception as e:
        error_msg = str(e)
        if "does not exist" in error_msg:
            return f"[X] {db_name} (no existe)"
        else:
            return f"[?] {db_name} (error: {error_msg[:50]}...)"


def test_all(url, candidates, username, password):
    """Prueba todos los candidatos"""
    print(f"\nProbando contra: {url}")
    print("-" * 70)

    for db_name in candidates:
        result = test_db(url, db_name, username, password)
        print(result)


if __name__ == "__main__":
    username = "andres@grupoeter.cl"
    password = "ROTATED-2026-05-07"

    # Candidatos para PRODUCCIÓN
    prod_url = "https://unionxb2b.odoo.com"
    prod_candidates = [
        "unionxb2b",
        "union_xb2b",
        "union-xb2b",
        "unionx",
        "union-x",
        "unionxb2b_prod",
        "prod",
        "produccion",
    ]

    # Candidatos para TEST
    test_url = "https://test3-melollevo.odoo.com"
    test_candidates = [
        "test3",
        "test3_melollevo",
        "test3-melollevo",
        "melollevo",
        "test",
        "test_melollevo",
        "test-melollevo",
        "testdb",
    ]

    print("=" * 70)
    print("PROBANDO VARIACIONES DE NOMBRES DE BASE DE DATOS")
    print("=" * 70)

    test_all(prod_url, prod_candidates, username, password)
    test_all(test_url, test_candidates, username, password)

    print("\n" + "=" * 70)
    print("Si encuentras un [OK], copia ese nombre a odoo_config.json")
    print("=" * 70)
