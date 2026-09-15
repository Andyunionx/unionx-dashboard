# -*- coding: utf-8 -*-
"""GO-LIVE GRNI 210217 — reasignación masiva de la cuenta de entrada de stock.

Plan (memo Víctor 20-08 + condiciones acordadas): el día del corte (propuesto
1-oct-2026, tras la barrida final de 210215 del cierre de septiembre):
  1. Reasignar property_stock_account_input_categ_id de TODAS las categorías de
     producto: 210215 → 210217 "Facturas por recibir" (creada por Víctor 02-09).
  2. Desde ese momento: recepciones acreditan 210217; facturas de proveedor
     ENLAZADAS a la OC la debitan. 210215 queda congelada con su saldo histórico
     a depurar (fichas de depuración).
  3. Verificación: primera recepción del día debe acreditar 210217.

Uso: python golive_grni_210217.py [--ejecutar]   (default: dry-run)
Reversible: mismo script con --revertir vuelve todo a 210215.
"""
import sys, json, os, time
from pathlib import Path
import requests

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
EJECUTAR = "--ejecutar" in sys.argv
REVERTIR = "--revertir" in sys.argv
cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
pw = os.environ.get("ANDRES_ODOO_PASSWORD", "") or (ROOT / "odoo/.odoo_pass").read_text().strip()
URL = cfg["url"] + "/jsonrpc"

def jrpc(s, m, a):
    for i in range(3):
        r = requests.post(URL, json={"jsonrpc": "2.0", "method": "call",
                                     "params": {"service": s, "method": m, "args": a}, "id": 1}, timeout=180)
        try:
            j = r.json()
        except Exception:
            time.sleep(5)
            continue
        if "error" in j:
            raise Exception(json.dumps(j["error"], ensure_ascii=False)[:400])
        return j.get("result")

uid = jrpc("common", "login", [cfg["db_name"], cfg["username"], pw])

def ex(model, method, *args, **kw):
    return jrpc("object", "execute_kw", [cfg["db_name"], uid, pw, model, method, list(args), kw])

a215 = ex("account.account", "search", [("code", "=", "210215")])[0]
a217 = ex("account.account", "search", [("code", "=", "210217")])[0]
origen, destino = (a217, a215) if REVERTIR else (a215, a217)

cats = ex("product.category", "search", [("property_stock_account_input_categ_id", "=", origen)])
print(f"Categorías con cuenta de entrada = {'210217' if REVERTIR else '210215'}: {len(cats)}")
n_dest = ex("product.category", "search_count", [("property_stock_account_input_categ_id", "=", destino)])
print(f"Ya apuntando al destino: {n_dest}")

if not EJECUTAR:
    print(f"\nDRY-RUN — ejecutaría: write property_stock_account_input_categ_id = "
          f"{'210215' if REVERTIR else '210217'} sobre {len(cats)} categorías. Correr con --ejecutar el día del corte.")
    sys.exit(0)

B = 200
for i in range(0, len(cats), B):
    ex("product.category", "write", [cats[i:i+B]], {"property_stock_account_input_categ_id": destino})
    print(f"  {min(i+B, len(cats))}/{len(cats)}")
print("Reasignación completa.")
chk = ex("product.category", "search_count", [("property_stock_account_input_categ_id", "=", destino)])
print(f"VERIFICACIÓN: categorías apuntando al destino: {chk}")
print("Siguiente: validar que la PRIMERA recepción del día acredite la cuenta nueva (monitor la vigila).")
