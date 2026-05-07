"""
Test rápido de conexión a Odoo
"""

import xmlrpc.client
import os
from pathlib import Path
from dotenv import load_dotenv

print("\n" + "="*80)
print(" TEST: Conexión a Odoo")
print("="*80)

# Cargar password
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(str(env_path))
password = os.getenv("ANDRES_ODOO_PASSWORD")

if not password:
    print("[ERROR] ANDRES_ODOO_PASSWORD no encontrado")
    exit(1)

print(f"\n[1/3] Conectando a Odoo...")
url = "https://unionxb2b.odoo.com"
db = "bmya-innovatek-sh-prd-6981800"
usuario = "andres@grupoeter.cl"

try:
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    print(f"[OK] Servidor alcanzable")

    print(f"\n[2/3] Autenticando...")
    uid = common.authenticate(db, usuario, password, {})

    if not uid:
        print(f"[ERROR] Autenticación fallida")
        exit(1)

    print(f"[OK] Autenticado (UID: {uid})")

    print(f"\n[3/3] Probando búsqueda...")
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

    # Test simple: contar sale.order
    domain = [
        ('create_date', '>=', '2026-02-01'),
        ('create_date', '<', '2026-03-01'),
        ('state', 'in', ['sale', 'done']),
    ]

    count = models.execute_kw(db, uid, password, 'sale.order', 'search_read', [domain], {'limit': 1})

    print(f"[OK] Query funciona. Encontrado: {len(count)} resultados")

    if count:
        order = count[0]
        print(f"\n[MUESTRA] Primer pedido febrero 2026:")
        print(f"  Pedido: {order.get('name')}")
        print(f"  Fecha: {order.get('create_date')}")
        print(f"  Estado: {order.get('state')}")
        print(f"  Partner: {order.get('partner_id')}")
        print(f"  Amount: {order.get('amount_total')}")

    print(f"\n{'='*80}")
    print("[OK] CONEXION EXITOSA - Listo para extracción completa")
    print(f"{'='*80}")

except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
    exit(1)
