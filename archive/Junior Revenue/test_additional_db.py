"""
Prueba variaciones adicionales basadas en "Commercial Inn"
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


if __name__ == "__main__":
    username = "andres@grupoeter.cl"
    password = "ROTATED-2026-05-07"

    # Candidatos adicionales basados en "Commercial Inn"
    prod_url = "https://unionxb2b.odoo.com"
    prod_candidates = [
        "commercialinn",
        "commercial_inn",
        "commercial-inn",
        "commercial",
        "inn",
        "commercialinncl",
    ]

    test_url = "https://test3-melollevo.odoo.com"
    test_candidates = [
        "commercialinn",
        "commercial_inn",
        "commercial-inn",
        "commercial",
    ]

    print("=" * 70)
    print("PROBANDO VARIACIONES CON 'COMMERCIAL INN'")
    print("=" * 70)

    print(f"\nProbando contra: {prod_url}")
    print("-" * 70)
    for db_name in prod_candidates:
        result = test_db(prod_url, db_name, username, password)
        print(result)

    print(f"\nProbando contra: {test_url}")
    print("-" * 70)
    for db_name in test_candidates:
        result = test_db(test_url, db_name, username, password)
        print(result)
