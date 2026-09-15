# -*- coding: utf-8 -*-
"""Monitor contable-vs-capas del inventario (auditoría gap 111001/111008).

Para cada fecha de corte:
  - Saldo contable por cuenta (111001, 111008, 111006, 210215, 210208, 1101016)
    desde account.move.line posteadas con date <= corte.
  - Valorización módulo = suma stock.valuation.layer con create_date <= corte.
  - GAP = (111001 + 111008) - capas.
Además: cargos NUEVOS a 111008 desde el 30-jun (fuentes vivas: ajuste al real + goteo NC).

Uso: python monitor_inventario_gap.py [YYYY-MM-DD ...]   (default: fin mes anterior y hoy)
"""
import sys, json, os, time, datetime
import xmlrpc.client
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
pw = os.environ.get("ANDRES_ODOO_PASSWORD", "") or (ROOT / "odoo/.odoo_pass").read_text().strip()
uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(cfg["db_name"], cfg["username"], pw, {})

def rpc(model, method, args, kw=None):
    for i in range(4):
        try:
            return xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object").execute_kw(
                cfg["db_name"], uid, pw, model, method, args, kw or {})
        except Exception:
            if i == 3:
                raise
            time.sleep(8)

CUENTAS = ["111001", "111008", "111006", "210215", "210217", "210208", "1101016"]
accs = rpc("account.account", "search_read", [[("code", "in", CUENTAS)]], {"fields": ["id", "code", "name"]})
acc_id = {a["code"]: a["id"] for a in accs}

hoy = datetime.date.today()
fin_mes_ant = hoy.replace(day=1) - datetime.timedelta(days=1)
cortes = [datetime.date.fromisoformat(a) for a in sys.argv[1:]] or [fin_mes_ant, hoy]

res = {}
for corte in cortes:
    fila = {}
    for code in CUENTAS:
        g = rpc("account.move.line", "read_group",
                [[("account_id", "=", acc_id[code]), ("parent_state", "=", "posted"),
                  ("date", "<=", str(corte))], ["balance"], []], {"lazy": False})
        fila[code] = g[0]["balance"] or 0.0
    g = rpc("stock.valuation.layer", "read_group",
            [[("create_date", "<=", f"{corte} 23:59:59")], ["value"], []], {"lazy": False})
    fila["capas"] = g[0]["value"] or 0.0
    fila["gap"] = fila["111001"] + fila["111008"] - fila["capas"]
    res[str(corte)] = fila

print(f"{'Cuenta':<28}" + "".join(f"{str(c):>16}" for c in cortes))
NOM = {"111001": "111001 Mercadería Nal.", "111008": "111008 Inv. Reservado", "210217": "210217 GRNI nueva",
       "111006": "111006 Import. Tránsito", "210215": "210215 Fact. x Recibir",
       "210208": "210208 Prov. Steven", "1101016": "1101016 Pago ML",
       "capas": "Capas AVCO (módulo)", "gap": "GAP (111001+111008-capas)"}
for k in ["111001", "111008", "111006", "210215", "210217", "210208", "1101016", "capas", "gap"]:
    print(f"{NOM[k]:<28}" + "".join(f"{res[str(c)][k]/1e6:>14,.1f}M" for c in cortes))

# fuentes vivas 111008 desde 30-jun
mv = rpc("account.move.line", "search_read",
         [[("account_id", "=", acc_id["111008"]), ("parent_state", "=", "posted"),
           ("date", ">", "2026-06-30")]],
         {"fields": ["date", "move_name", "name", "debit", "credit"], "order": "date"})
print(f"\nMovimientos 111008 desde 30-jun: {len(mv)}")
for m in mv:
    print(f"  {m['date']}  {m['move_name']:<22} D{m['debit']:>12,.0f} H{m['credit']:>12,.0f}  {str(m['name'])[:45]}")

out = ROOT / "data/outputs/monitor_inventario_gap.json"
hist = json.load(open(out)) if out.exists() else {}
hist.update({k: {kk: round(vv, 0) for kk, vv in v.items()} for k, v in res.items()})
json.dump(hist, open(out, "w"), indent=1)
print(f"\nGuardado: {out.name}")
