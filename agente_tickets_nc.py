# -*- coding: utf-8 -*-
"""Agente Tickets Helpdesk → NC (decisión Andrés 26-08-2026: opción B, emisión y
posteo automático, activo desde el LUNES 31-08-2026).

Reglas (Max, mail 26-08):
  - Gatillo: propiedad Motivo == "Devolución" Y Estado in {Nuevo, Outlet, Merma}.
    Estado vacío = aún no se recepciona → no emitir todavía.
  - Exclusión: canal Kitchen Center (gestión manual).
  - OC del canal en propiedad "Nº Orden de compra" (normalizar prefijo PV/espacios).
  - NC POR LÍNEA: "Producto Comprado" × "Cantidad". Varios tickets de una OC → una
    NC agrupada. Fecha NC = "F. recepción PV" (si su mes está cerrado → hoy).
  - Si la boleta YA tiene NC (no creada por este agente) → NO emitir; marcar
    'NC previa (investigar)' → reporte semanal a Max (lunes).
Formato NC = wizard account.move.reversal (igual que facturación): tipo 61,
código referencia SII 1 (devolución total) / 3 (parcial). El envío al SII lo
hace el cron 26 estándar.

Campo helpdesk.ticket.x_estado_nc: con_nc / nc_creada / sin_nc / sin_boleta /
nc_previa / revisar / no_aplica.

Modos:
  --dry-run          simula todo, NO escribe nada (default antes del 31-08)
  --auto             modo workflow: dry-run antes del 31-08, live desde esa fecha
  --ejecutar         fuerza live
  --full             barre todo el histórico (default: tickets modificados últimas VENTANA_H horas)
Seguridad: máx MAX_NC_POR_CORRIDA NC por corrida (el resto queda para la siguiente hora).
"""
import sys, os, json, re, datetime, collections
from pathlib import Path
import requests

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
FECHA_INICIO = datetime.date(2026, 8, 31)
VENTANA_H = 8
MAX_NC_POR_CORRIDA = 40
TAG = "[AGENTE-PV"
ESTADOS_OK = {"Nuevo", "Outlet", "Merma"}

cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
PW = os.environ.get("ANDRES_ODOO_PASSWORD", "")
if not PW and (ROOT / "odoo/.odoo_pass").exists():
    PW = (ROOT / "odoo/.odoo_pass").read_text().strip()
URL = cfg["url"] + "/jsonrpc"

def jrpc(service, method, args):
    r = requests.post(URL, json={"jsonrpc": "2.0", "method": "call",
                                 "params": {"service": service, "method": method, "args": args}, "id": 1}, timeout=300)
    j = r.json()
    if "error" in j:
        raise Exception(json.dumps(j["error"], ensure_ascii=False)[:600])
    return j["result"]

UID = jrpc("common", "login", [cfg["db_name"], cfg["username"], PW])

def ex(model, method, *args, **kw):
    return jrpc("object", "execute_kw", [cfg["db_name"], UID, PW, model, method, list(args), kw])

HOY = datetime.date.today()
LIVE = ("--ejecutar" in sys.argv) or ("--auto" in sys.argv and HOY >= FECHA_INICIO)
if "--dry-run" in sys.argv:
    LIVE = False
FULL = "--incremental" not in sys.argv  # default: barrido completo (batch, ~5 min); los resueltos se saltan por campo
print(f"[{HOY}] modo={'LIVE' if LIVE else 'DRY-RUN'} barrido={'FULL' if FULL else f'incremental {VENTANA_H}h'}")

def prop(t, nombre):
    for p in (t.get("properties") or []):
        if str(p.get("string", "")).strip().lower() == nombre.lower():
            v = p.get("value")
            if p.get("type") == "selection" and p.get("selection"):
                return dict((s[0], s[1]) for s in p["selection"]).get(v, v)
            return v
    return None

def norm_oc(s):
    s = str(s or "").strip().replace(" ", "")
    s = re.sub(r"^PV[-_]?", "", s, flags=re.I)
    return s.lstrip("#")

# ---- 1) universo de tickets ----
dominio = []
if not FULL:
    desde = (datetime.datetime.utcnow() - datetime.timedelta(hours=VENTANA_H)).strftime("%Y-%m-%d %H:%M:%S")
    dominio = [("write_date", ">=", desde)]
tickets, off = [], 0
while True:
    b = ex("helpdesk.ticket", "search_read", dominio,
           fields=["id", "name", "ticket_ref", "properties", "x_estado_nc", "team_id"],
           limit=1000, offset=off, order="id")
    tickets += b
    off += len(b)
    if len(b) < 1000:
        break
print(f"tickets leídos: {len(tickets)}")

cand = []
for t in tickets:
    if t.get("x_estado_nc") in ("con_nc", "nc_creada", "no_aplica", "nc_previa"):
        continue  # ya resuelto
    if str(prop(t, "Motivo") or "").strip() != "Devolución":
        continue
    canal = str(prop(t, "Canal") or "")
    estado = str(prop(t, "Estado") or "").strip()
    oc = norm_oc(prop(t, "Nº Orden de compra"))
    if not oc and "-" in t["name"]:
        oc = norm_oc(t["name"].split("-", 1)[1])
    cand.append({"t": t, "canal": canal, "estado": estado, "oc": oc,
                 "prod": prop(t, "Producto Comprado"), "qty": prop(t, "Cantidad") or 0,
                 "frecep": prop(t, "F. recepción PV")})
print(f"candidatos (Motivo=Devolución, sin resolver): {len(cand)}")

marcas = collections.defaultdict(list)   # estado_nc -> ticket ids
por_oc = collections.defaultdict(list)
for c in cand:
    tid = c["t"]["id"]
    if "kitchen" in c["canal"].lower():
        marcas["no_aplica"].append((tid, "canal Kitchen Center (manual)"))
    elif c["estado"] not in ESTADOS_OK:
        pass  # sin disposición final aún: se re-evalúa la próxima corrida
    elif not c["oc"]:
        marcas["revisar"].append((tid, "sin Nº de orden"))
    elif not c["prod"] or not c["qty"]:
        marcas["revisar"].append((tid, "sin producto/cantidad"))
    else:
        por_oc[c["oc"]].append(c)
print(f"OC con tickets emitibles: {len(por_oc)}")

# ---- 2) resolver cada OC (consultas POR LOTE) ----
ocs = list(por_oc.keys())
print("resolviendo pedidos por lote...")
B = 400
ord_por_oc = collections.defaultdict(list)
for i in range(0, len(ocs), B):
    ch = ocs[i:i+B]
    variantes = ch + ["#" + o for o in ch]
    for o in ex("sale.order", "search_read",
                ["|", ("channel_order_reference", "in", variantes), ("name", "in", ch)],
                fields=["id", "name", "channel_order_reference", "invoice_ids"], limit=2000):
        key = norm_oc(o.get("channel_order_reference") or "") or o["name"]
        if key in por_oc:
            ord_por_oc[key].append(o)
        elif o["name"] in por_oc:
            ord_por_oc[o["name"]].append(o)
inv_all = sorted({i for os_ in ord_por_oc.values() for o in os_ for i in o["invoice_ids"]})
bol_por_id = {}
for i in range(0, len(inv_all), 800):
    for b in ex("account.move", "search_read",
                [("id", "in", inv_all[i:i+800]), ("move_type", "=", "out_invoice"), ("state", "=", "posted")],
                fields=["id", "name", "journal_id", "l10n_latam_document_number", "ref"], limit=1000):
        bol_por_id[b["id"]] = b
bol_ids = list(bol_por_id.keys())
nc_por_bol = collections.defaultdict(list)
for i in range(0, len(bol_ids), 800):
    for n in ex("account.move", "search_read",
                [("move_type", "=", "out_refund"), ("reversed_entry_id", "in", bol_ids[i:i+800]),
                 ("state", "in", ["draft", "posted"])],
                fields=["id", "name", "ref", "state", "reversed_entry_id"], limit=2000):
        nc_por_bol[n["reversed_entry_id"][0]].append(n)
lin_por_bol = collections.defaultdict(list)
for i in range(0, len(bol_ids), 400):
    for l in ex("account.move.line", "search_read",
                [("move_id", "in", bol_ids[i:i+400]), ("display_type", "=", "product")],
                fields=["id", "move_id", "product_id", "quantity", "price_unit"], limit=8000):
        lin_por_bol[l["move_id"][0]].append(l)
# NC standalone (sin reversed_entry) detectadas por referencia SII al folio
folios = sorted({str(b.get("l10n_latam_document_number") or "") for b in bol_por_id.values() if b.get("l10n_latam_document_number")})
nc_ref_folios = set()
for i in range(0, len(folios), 800):
    for r in ex("l10n_cl.account.invoice.reference", "search_read",
                [("origin_doc_number", "in", folios[i:i+800]), ("move_id.move_type", "=", "out_refund"),
                 ("move_id.state", "in", ["draft", "posted"])],
                fields=["origin_doc_number"], limit=4000):
        nc_ref_folios.add(str(r["origin_doc_number"]))
print(f"folios con NC por referencia SII (standalone): {len(nc_ref_folios)}")
# fechas de boleta para el plazo tributario (NC con rebaja IVA: 3 meses)
fecha_bol = {}
for i in range(0, len(bol_ids), 800):
    for b in ex("account.move", "search_read", [("id", "in", bol_ids[i:i+800])], fields=["id", "date"], limit=1000):
        fecha_bol[b["id"]] = str(b["date"])
LIM_PLAZO = str(HOY - datetime.timedelta(days=90))
print(f"pedidos: {sum(len(v) for v in ord_por_oc.values())} | boletas: {len(bol_por_id)} | con NC previa: {len(nc_por_bol)}")

acciones = []   # (boleta, [tickets], lineas {product_id: qty}, total_flag, fecha)
for oc, cs in por_oc.items():
    tids = [c["t"]["id"] for c in cs]
    ords = ord_por_oc.get(oc, [])
    if len(ords) != 1:
        marcas["revisar"] += [(i, f"pedido {'no encontrado' if not ords else 'ambiguo'} para OC {oc}") for i in tids]
        continue
    boletas = [bol_por_id[i] for i in ords[0]["invoice_ids"] if i in bol_por_id]
    if not boletas:
        marcas["sin_boleta"] += [(i, f"OC {oc} sin boleta posteada") for i in tids]
        continue
    if len(boletas) > 1:
        marcas["revisar"] += [(i, f"OC {oc} con {len(boletas)} boletas") for i in tids]
        continue
    bol = boletas[0]
    ncs = nc_por_bol.get(bol["id"], [])
    if ncs:
        if any(TAG in str(n.get("ref") or "") for n in ncs):
            marcas["con_nc"] += [(i, f"NC del agente ya existe: {ncs[0]['name']}") for i in tids]
        else:
            marcas["nc_previa"] += [(i, f"boleta {bol['name']} ya tiene NC {ncs[0]['name']} ({ncs[0]['state']})") for i in tids]
        continue
    if str(bol.get("l10n_latam_document_number") or "") in nc_ref_folios:
        marcas["nc_previa"] += [(i, f"boleta {bol['name']} tiene NC standalone (referencia SII al folio)") for i in tids]
        continue
    if fecha_bol.get(bol["id"], "9999") < LIM_PLAZO:
        marcas["revisar"] += [(i, f"boleta {bol['name']} de {fecha_bol.get(bol['id'])} — fuera de plazo NC 3 meses, decisión manual") for i in tids]
        continue
    por_prod = {l["product_id"][0]: l for l in lin_por_bol.get(bol["id"], []) if l["product_id"]}
    lineas, problema = {}, None
    for c in cs:
        pid = c["prod"][0] if isinstance(c["prod"], (list, tuple)) else c["prod"]
        if pid not in por_prod:
            problema = f"producto {c['prod'][1] if isinstance(c['prod'],(list,tuple)) else pid} no está en boleta {bol['name']}"
            break
        if c["qty"] > por_prod[pid]["quantity"]:
            problema = f"cantidad ticket ({c['qty']}) > facturada ({por_prod[pid]['quantity']:g})"
            break
        lineas[pid] = lineas.get(pid, 0) + c["qty"]
    if problema:
        marcas["revisar"] += [(i, problema) for i in tids]
        continue
    total_flag = (set(lineas) == set(por_prod)) and all(lineas[p] == por_prod[p]["quantity"] for p in lineas)
    frecep = min((c["frecep"] for c in cs if c["frecep"]), default=None)
    if frecep and str(frecep)[:7] == f"{HOY:%Y-%m}":
        fecha_nc = str(frecep)[:10]
    else:
        fecha_nc = str(HOY)
    acciones.append({"bol": bol, "tids": tids, "trefs": [c["t"]["ticket_ref"] for c in cs],
                     "lineas": lineas, "total": total_flag, "fecha": fecha_nc, "oc": oc,
                     "monto_est": sum(por_prod[p]["price_unit"] * q for p, q in lineas.items())})

print(f"\nNC a emitir: {len(acciones)} (tope por corrida: {MAX_NC_POR_CORRIDA})")
tot_m = sum(a["monto_est"] for a in acciones)
print(f"Monto estimado (neto líneas): ${tot_m:,.0f}")
for a in acciones[:15]:
    print(f"  {'TOTAL ' if a['total'] else 'PARCIAL'} boleta {a['bol']['name']} OC {a['oc']} fecha {a['fecha']} ~${a['monto_est']:,.0f} tickets {a['trefs']}")
if len(acciones) > 15:
    print(f"  ... y {len(acciones)-15} más")
for est, lst in marcas.items():
    print(f"\n{est}: {len(lst)}")
    for tid, m in lst[:6]:
        print(f"   ticket {tid}: {m}")

if not LIVE:
    print("\nDRY-RUN — no se escribió nada (ni campo ni NC).")
    sys.exit(0)

# ---- 3) EJECUCIÓN ----
def marcar(tids, estado, nota):
    ex("helpdesk.ticket", "write", tids, {"x_estado_nc": estado})
    for tid in tids:
        try:
            ex("helpdesk.ticket", "message_post", [tid], body=f"[Agente NC] {nota}")
        except Exception:
            pass

for est, lst in marcas.items():
    if lst:
        ex("helpdesk.ticket", "write", [i for i, _ in lst], {"x_estado_nc": est})
print("campos marcados (no emisores)")

emitidas, errores = 0, []
for a in acciones[:MAX_NC_POR_CORRIDA]:
    try:
        bol = a["bol"]
        wiz = ex("account.move.reversal", "create", {
            "move_ids": [(6, 0, [bol["id"]])], "date": a["fecha"],
            "reason": f"Devolución postventa tickets {','.join('#'+str(r) for r in a['trefs'])}",
            "journal_id": bol["journal_id"][0],
            "l10n_cl_edi_reference_doc_code": "1" if a["total"] else "3",
        })
        ex("account.move.reversal", "reverse_moves", [wiz])
        nc = ex("account.move", "search_read",
                [("move_type", "=", "out_refund"), ("reversed_entry_id", "=", bol["id"]), ("state", "=", "draft")],
                fields=["id", "ref"], order="id desc", limit=1)[0]
        if not a["total"]:
            ls = ex("account.move.line", "search_read",
                    [("move_id", "=", nc["id"]), ("display_type", "=", "product")],
                    fields=["id", "product_id", "quantity"])
            for l in ls:
                pid = l["product_id"][0] if l["product_id"] else 0
                if pid not in a["lineas"]:
                    ex("account.move.line", "unlink", [l["id"]])
                elif abs(l["quantity"] - a["lineas"][pid]) > 0.001:
                    ex("account.move.line", "write", [l["id"]], {"quantity": a["lineas"][pid]})
        ex("account.move", "write", [nc["id"]],
           {"ref": f"{nc.get('ref') or ''} {TAG} {','.join('#'+str(r) for r in a['trefs'])}]".strip()})
        chk = ex("account.move", "read", [nc["id"]], fields=["amount_total"])[0]
        if chk["amount_total"] <= 0:
            raise Exception("NC quedó en $0 tras la poda — no se postea")
        ex("account.move", "action_post", [nc["id"]])
        marcar(a["tids"], "nc_creada", f"NC emitida por boleta {bol['name']} (${chk['amount_total']:,.0f})")
        emitidas += 1
        print(f"  ✔ NC posteada boleta {bol['name']} ${chk['amount_total']:,.0f} tickets {a['trefs']}")
    except Exception as e:
        errores.append((a["oc"], str(e)[:200]))
        try:
            ex("helpdesk.ticket", "write", a["tids"], {"x_estado_nc": "revisar"})
        except Exception:
            pass
        print(f"  ✘ ERROR OC {a['oc']}: {str(e)[:160]}")

print(f"\nEMITIDAS: {emitidas} | errores: {len(errores)} | pendientes próxima corrida: {max(0, len(acciones)-MAX_NC_POR_CORRIDA)}")

# ---- 4) reporte semanal a Max (lunes) ----
if HOY.weekday() == 0 and LIVE:
    try:
        casos = ex("helpdesk.ticket", "search_read", [("x_estado_nc", "=", "nc_previa")],
                   fields=["ticket_ref", "name"], limit=200)
        if casos:
            import base64
            from email.message import EmailMessage
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            tok = os.environ.get("GMAIL_TOKEN_JSON")
            creds = (Credentials.from_authorized_user_info(json.loads(tok)) if tok
                     else Credentials.from_authorized_user_file(str(ROOT / "agente-comex/config/token.json")))
            if not creds.valid:
                creds.refresh(Request())
            svc = build("gmail", "v1", credentials=creds)
            cuerpo = "Hola Max,\n\nCasos con NC PREVIA detectados por el agente (devolución llegó con NC ya emitida) — para investigar:\n\n"
            cuerpo += "\n".join(f"- #{c['ticket_ref']} {c['name']}" for c in casos)
            cuerpo += "\n\nSaludos,\nAgente NC Postventa"
            msg = EmailMessage()
            msg["To"] = "maximiliano@unionx.cl"
            msg["Cc"] = "andres@unionx.cl"
            msg["From"] = "andres@unionx.cl"
            msg["Subject"] = f"[Agente NC] Reporte semanal: {len(casos)} tickets con NC previa a investigar"
            msg.set_content(cuerpo)
            svc.users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}).execute()
            print(f"reporte semanal a Max enviado ({len(casos)} casos)")
    except Exception as e:
        print(f"reporte semanal falló: {str(e)[:150]}")
