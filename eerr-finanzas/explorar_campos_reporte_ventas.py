"""
EXPLORAR: Todos los campos disponibles en sale.order y sale.order.line
Para replicar exactamente el Reporte Ventas de Odoo
"""

import xmlrpc.client
from pathlib import Path
import os
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(str(env_path))
password = os.getenv("ANDRES_ODOO_PASSWORD")

url = "https://unionxb2b.odoo.com"
db = "bmya-innovatek-sh-prd-6981800"
usuario = "andres@grupoeter.cl"

common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, usuario, password, {})
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

print("\n" + "="*120)
print(" CAMPOS DISPONIBLES: sale.order")
print("="*120)

# Obtener campos de sale.order
campos_orden = models.execute_kw(db, uid, password, 'sale.order', 'fields_get', [],
    {'attributes': ['string', 'type', 'relation']})

# Filtrar campos relevantes para el reporte
keywords = ['marketplace', 'fulfillment', 'margin', 'margen', 'channel',
            'yuju', 'pack', 'inventory', 'inventari', 'reference', 'invoice',
            'warehouse', 'carrier', 'delivery', 'shipping', 'team', 'commission']

print(f"\nTotal campos sale.order: {len(campos_orden)}")
print(f"\nCampos CUSTOM o RELEVANTES:")
print(f"{'Campo API':<45} {'Etiqueta':30} {'Tipo'}")
print("-"*100)

for campo, info in sorted(campos_orden.items()):
    label = info.get('string', '').lower()
    field = campo.lower()

    es_relevante = (
        campo.startswith('x_') or
        campo.startswith('marketplace') or
        any(kw in field or kw in label for kw in keywords)
    )

    if es_relevante:
        print(f"  {campo:<45} {info.get('string', ''):<30} {info.get('type', '')}")

print(f"\n{'='*120}")
print(f" CAMPOS DISPONIBLES: sale.order.line")
print(f"{'='*120}")

campos_linea = models.execute_kw(db, uid, password, 'sale.order.line', 'fields_get', [],
    {'attributes': ['string', 'type', 'relation']})

keywords_linea = ['margin', 'margen', 'cost', 'costo', 'discount', 'descuento',
                  'invoice', 'factura', 'qty_delivered', 'qty_invoiced',
                  'purchase_price', 'product', 'marketplace', 'commission']

print(f"\nTotal campos sale.order.line: {len(campos_linea)}")
print(f"\nCampos CUSTOM o RELEVANTES:")
print(f"{'Campo API':<45} {'Etiqueta':30} {'Tipo'}")
print("-"*100)

for campo, info in sorted(campos_linea.items()):
    label = info.get('string', '').lower()
    field = campo.lower()

    es_relevante = (
        campo.startswith('x_') or
        any(kw in field or kw in label for kw in keywords_linea)
    )

    if es_relevante:
        print(f"  {campo:<45} {info.get('string', ''):<30} {info.get('type', '')}")

print(f"\n{'='*120}")
print(f" CAMPOS DISPONIBLES: product.product (para SKU, costo, categoría)")
print(f"{'='*120}")

campos_prod = models.execute_kw(db, uid, password, 'product.product', 'fields_get', [],
    {'attributes': ['string', 'type']})

keywords_prod = ['default_code', 'standard_price', 'categ', 'barcode', 'list_price',
                 'cost', 'qty', 'virtual', 'inventory']

print(f"\nTotal campos product.product: {len(campos_prod)}")
print(f"\nCampos RELEVANTES para reporte:")
print(f"{'Campo API':<45} {'Etiqueta':30} {'Tipo'}")
print("-"*100)

for campo, info in sorted(campos_prod.items()):
    label = info.get('string', '').lower()
    field = campo.lower()

    es_relevante = any(kw in field or kw in label for kw in keywords_prod)

    if es_relevante:
        print(f"  {campo:<45} {info.get('string', ''):<30} {info.get('type', '')}")

print(f"\n{'='*120}")

# Verificar un pedido de muestra para ver qué valores reales tiene
print(f"\n MUESTRA: Primeros 3 pedidos de marzo 2026 con TODOS los campos")
print(f"{'='*120}")

ordenes_muestra = models.execute_kw(db, uid, password,
    'sale.order', 'search_read',
    [[('date_order', '>=', '2026-03-01'), ('date_order', '<', '2026-04-01'),
      ('state', 'in', ['sale', 'done'])]],
    {'limit': 3}
)

if ordenes_muestra:
    o = ordenes_muestra[0]
    print(f"\nCampos del primer pedido ({o.get('name', '')}):")
    for k, v in sorted(o.items()):
        if v and v != False and v != [] and v != {}:
            print(f"  {k:<45} = {str(v)[:80]}")

print(f"\n{'='*120}")
