"""Diagnóstico: qué combinación de fields + page_size aguanta Odoo."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.config import Config

odoo = OdooClient(
    url=Config.ODOO_URL, db=Config.ODOO_DB,
    username=Config.ODOO_USER, password=Config.ODOO_PASSWORD,
    max_retries=2,
)

DOMAIN = [
    ('date_order', '>=', '2026-04-01 00:00:00'),
    ('date_order', '<=', '2026-04-28 23:59:59'),
    ('state', 'in', ['sale', 'done']),
]

ALL_FIELDS = [
    'id', 'name', 'date_order', 'partner_id', 'user_id', 'amount_total',
    'margin', 'state', 'fulfillment', 'channel', 'channel_order_reference',
    'client_order_ref', 'invoice_ids', 'warehouse_id', 'yuju_pack_id'
]

NO_INVOICE_IDS = [f for f in ALL_FIELDS if f != 'invoice_ids']
LIGHT = ['id', 'name', 'date_order', 'state', 'amount_total']

def test(label, fields, limit):
    t0 = time.time()
    try:
        r = odoo.search_read('sale.order', DOMAIN, fields, limit=limit)
        print(f"  [OK] {label:35s} -> {len(r):4d} rec en {time.time()-t0:.1f}s")
        return True
    except Exception as e:
        msg = str(e)[:80]
        print(f"  [FAIL] {label:35s} -> {msg} ({time.time()-t0:.1f}s)")
        return False

print("=== Diagnóstico Odoo (sale.order, Abr 1-28) ===\n")
print("UID:", odoo.authenticate())
print()

for limit, fields, label in [
    (10, LIGHT,           'limit=10  light(5 fields)'),
    (100, LIGHT,          'limit=100 light(5 fields)'),
    (500, LIGHT,          'limit=500 light(5 fields)'),
    (50, NO_INVOICE_IDS,  'limit=50  full-no-invoice_ids(14)'),
    (100, NO_INVOICE_IDS, 'limit=100 full-no-invoice_ids(14)'),
    (50, ALL_FIELDS,      'limit=50  all(15 with invoice_ids)'),
    (100, ALL_FIELDS,     'limit=100 all(15 with invoice_ids)'),
]:
    test(label, fields, limit)
