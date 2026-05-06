"""Extrae abril 14-17 usando el método probado"""
import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

PERIODO_INICIO  = '2026-04-14 00:00:00'
PERIODO_FIN     = '2026-04-17 23:59:59'

env_path = Path(__file__).parent / ".env"
load_dotenv(str(env_path))
password = os.getenv("ANDRES_ODOO_PASSWORD")

url     = "https://unionxb2b.odoo.com"
db      = "bmya-innovatek-sh-prd-6981800"
usuario = "andres@grupoeter.cl"

print("\n[Conectando a Odoo...]")
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid    = common.authenticate(db, usuario, password, {})
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

print(f"[OK] Conectado\n")

# Extraer órdenes
print(f"[1] Extrayendo órdenes {PERIODO_INICIO} a {PERIODO_FIN}...")
ordenes = models.execute_kw(db, uid, password,
    'sale.order', 'search_read',
    [[
        ('date_order', '>=', PERIODO_INICIO),
        ('date_order', '<=', PERIODO_FIN),
        ('state', 'in', ['sale', 'done']),
    ]],
    {'fields': ['id', 'name', 'date_order', 'amount_total'], 'limit': 200000}
)

print(f"[OK] {len(ordenes):,} órdenes encontradas")
total = sum([o['amount_total'] for o in ordenes])
print(f"     Venta total: ${total:,.0f}\n")

if len(ordenes) > 0:
    print("Primeras 5 órdenes:")
    for o in ordenes[:5]:
        print(f"  {o['date_order']} | {o['name']:20} | ${o['amount_total']:>12,.0f}")

