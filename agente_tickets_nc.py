# -*- coding: utf-8 -*-
"""Agente Tickets Helpdesk → NC (decisión Andrés 26-08-2026: opción B, emisión y
posteo automático, activo desde el LUNES 31-08-2026).

Reglas: ver nc_reglas.py (Max, correo 17-sep-2026; complemento Andrés 05-oct). Resumen:
  - Gatillo: Motivo == "Devolución" + Resolución no vacía + producto recepcionado
    (Estado Nuevo / Outlet / Merma). Motivo "Cambio" = canal manual sin confirmar.
  - Se emiten a mano (el agente no los toca): Fidelización, Distribución, páginas
    propias y Kitchen Center. Fuera también los tickets con "PV" + OC en el título.
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
  --excel RUTA       con --dry-run: deja el resultado ticket a ticket en un Excel (para validar)
Seguridad: máx MAX_NC_POR_CORRIDA NC por corrida (el resto queda para la siguiente hora).
"""
import sys, os, json, re, datetime, collections
from pathlib import Path
import requests

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import nc_reglas as R  # noqa: E402

FECHA_INICIO = datetime.date(2026, 8, 31)
VENTANA_H = 8
MAX_NC_POR_CORRIDA = 40
TAG = "[AGENTE-PV"
EXCEL = sys.argv[sys.argv.index("--excel") + 1] if "--excel" in sys.argv else None

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
           fields=["id", "name", "ticket_ref", "properties", "x_estado_nc", "team_id", "create_date"],
           limit=1000, offset=off, order="id")
    tickets += b
    off += len(b)
    if len(b) < 1000:
        break
print(f"tickets leídos: {len(tickets)}")

def ficha(t, bucket, detalle):
    oc = norm_oc(prop(t, "Nº Orden de compra"))
    if not oc and "-" in t["name"]:
        oc = norm_oc(t["name"].split("-", 1)[1])
    return {"t": t, "canal": R.texto(t, "Canal"), "estado": R.texto(t, "Estado"), "oc": oc,
            "prod": prop(t, "Producto Comprado"), "qty": prop(t, "Cantidad") or 0,
            "frecep": prop(t, "F. recepción PV"), "bucket": bucket, "detalle": detalle}

# Clasificación con las reglas de Max (nc_reglas.py). Solo CANDIDATO entra al agente;
# MANUAL se revisa contra Odoo únicamente para informar (nunca se emite desde acá).
cand, manuales, otros = [], [], []
conteo = collections.Counter()
for t in tickets:
    # Solo se saltan los resueltos de verdad. «con_nc» y «nc_previa» se vuelven a verificar
    # contra Odoo en cada corrida: 69 tickets (05-oct) tenían esa marca sin que existiera
    # ninguna NC (borradores borrados después) y el agente los saltaba para siempre.
    if t.get("x_estado_nc") in ("nc_creada", "no_aplica"):
        conteo["YA RESUELTO"] += 1
        continue
    bucket, detalle = R.clasificar(t)
    conteo[bucket] += 1
    if bucket == R.CANDIDATO:
        cand.append(ficha(t, bucket, detalle))
    elif bucket == R.MANUAL:
        manuales.append(ficha(t, bucket, detalle))
    elif bucket != R.OTRO_MOTIVO:
        otros.append(ficha(t, bucket, detalle))
print(f"clasificación: {dict(conteo)}")
print(f"candidatos (reglas Max): {len(cand)} · manuales: {len(manuales)}")

marcas = collections.defaultdict(list)   # estado_nc -> ticket ids
por_oc = collections.defaultdict(list)
for c in cand:
    tid = c["t"]["id"]
    if not c["oc"]:
        marcas["revisar"].append((tid, "sin Nº de orden"))
    elif not c["prod"] or not c["qty"]:
        marcas["revisar"].append((tid, "sin producto/cantidad"))
    else:
        por_oc[c["oc"]].append(c)
print(f"OC con tickets emitibles: {len(por_oc)}")

# ---- 2) resolver cada OC (consultas POR LOTE) ----
man_por_oc = collections.defaultdict(list)   # manuales: solo para informar
for c in manuales:
    if c["oc"]:
        man_por_oc[c["oc"]].append(c)
ocs = sorted(set(por_oc) | set(man_por_oc))
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
        if key in por_oc or key in man_por_oc:
            ord_por_oc[key].append(o)
        elif o["name"] in por_oc or o["name"] in man_por_oc:
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
    # Un BORRADOR propio (de una corrida que falló al postear) NO debe contar como
    # "NC ya existe": si no, el ticket queda marcado con_nc y se salta para siempre
    # sin que la NC llegue a emitirse (41 borradores huérfanos, 01-03 sep 2026).
    # Se elimina —no tiene efecto fiscal, nunca se posteó— y se reemite abajo.
    propios_draft = [n for n in ncs if n["state"] == "draft" and TAG in str(n.get("ref") or "")]
    if propios_draft and not [n for n in ncs if n["state"] == "posted"]:
        if LIVE:
            try:
                ex("account.move", "unlink", [n["id"] for n in propios_draft])
                print(f"  ♻ boleta {bol['name']}: {len(propios_draft)} borrador(es) huérfano(s) eliminados → se reemite")
            except Exception as e:
                print(f"  ⚠ boleta {bol['name']}: no se pudo limpiar borrador huérfano: {str(e)[:120]}")
        ncs = [n for n in ncs if n not in propios_draft]
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

# Lista de boletas autorizadas (Andrés 05-oct, opción 2): mientras la variable tenga
# boletas, se emiten SOLO esas; el resto queda retenido (sin marcar) hasta validarlo.
# Vacía = sin restricción.
AUTORIZADAS = {b.strip() for b in os.environ.get("AGENTE_NC_BOLETAS_AUTORIZADAS", "").split(",") if b.strip()}
if AUTORIZADAS:
    retenidas = [a for a in acciones if a["bol"]["name"] not in AUTORIZADAS]
    acciones = [a for a in acciones if a["bol"]["name"] in AUTORIZADAS]
    print(f"lista de boletas autorizadas activa: {len(acciones)} autorizadas · {len(retenidas)} retenidas hasta validarlas")

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


def estado_manual(oc, cs):
    """Estado NC de una OC de canal manual, con las mismas consultas del agente. Solo informa."""
    ords = ord_por_oc.get(oc, [])
    if len(ords) != 1:
        return f"pedido {'no encontrado' if not ords else 'ambiguo'}", None, 0
    boletas = [bol_por_id[i] for i in ords[0]["invoice_ids"] if i in bol_por_id]
    if not boletas:
        return "sin boleta", None, 0
    if len(boletas) > 1:
        return f"{len(boletas)} boletas", None, 0
    bol = boletas[0]
    if nc_por_bol.get(bol["id"]) or str(bol.get("l10n_latam_document_number") or "") in nc_ref_folios:
        return "ya tiene NC", bol, 0
    if fecha_bol.get(bol["id"], "9999") < LIM_PLAZO:
        return "fuera de plazo (3 meses)", bol, 0
    por_prod = {l["product_id"][0]: l for l in lin_por_bol.get(bol["id"], []) if l["product_id"]}
    monto = 0
    for c in cs:
        pid = c["prod"][0] if isinstance(c["prod"], (list, tuple)) else c["prod"]
        if pid in por_prod:
            monto += por_prod[pid]["price_unit"] * min(c["qty"] or 0, por_prod[pid]["quantity"])
    return "PENDIENTE NC", bol, monto


filas_man = []
for oc, cs in man_por_oc.items():
    est, bol, monto = estado_manual(oc, cs)
    for c in cs:
        filas_man.append({"grupo": c["detalle"], "canal": c["canal"], "ticket": c["t"]["ticket_ref"],
                          "titulo": c["t"]["name"], "oc": oc, "estado NC": est,
                          "boleta": bol["name"] if bol else "", "fecha boleta": fecha_bol.get(bol["id"]) if bol else "",
                          "monto estimado OC": round(monto)})
for c in manuales:
    if not c["oc"]:
        filas_man.append({"grupo": c["detalle"], "canal": c["canal"], "ticket": c["t"]["ticket_ref"],
                          "titulo": c["t"]["name"], "oc": "", "estado NC": "sin Nº de orden",
                          "boleta": "", "fecha boleta": "", "monto estimado OC": 0})
cm = collections.Counter((f["grupo"], f["estado NC"]) for f in filas_man)
print("\nmanuales por grupo y estado NC:", dict(cm))

if EXCEL and not LIVE:
    import pandas as pd
    nombre_t = {t["id"]: t for t in tickets}

    def fila_ticket(c):
        t = c["t"]
        return {"ticket": t["ticket_ref"], "titulo": t["name"], "canal": c["canal"],
                "equipo": (t.get("team_id") or [0, ""])[1], "motivo": R.texto(t, "Motivo"),
                "resolución": R.texto(t, "Resolución"), "estado producto": c["estado"],
                "oc": c["oc"], "creado": str(t.get("create_date") or "")[:10], "detalle": c["detalle"]}

    hojas = {}
    hojas["1 Emitiría el agente"] = pd.DataFrame([{
        "boleta": a["bol"]["name"], "oc": a["oc"], "tickets": ", ".join("#" + str(r) for r in a["trefs"]),
        "canal": ", ".join(sorted({R.texto(nombre_t[i], "Canal") for i in a["tids"]})),
        "tipo": "total" if a["total"] else "parcial", "fecha NC": a["fecha"],
        "monto estimado": round(a["monto_est"])} for a in acciones])
    hojas["2 Agente - revisar"] = pd.DataFrame([{
        "estado": est, "ticket": nombre_t[tid]["ticket_ref"], "titulo": nombre_t[tid]["name"],
        "canal": R.texto(nombre_t[tid], "Canal"), "motivo": m} for est, lst in marcas.items() for tid, m in lst])
    hojas["3 Manuales"] = pd.DataFrame(filas_man)
    hace7 = str(datetime.date.today() - datetime.timedelta(days=7))
    camb = [fila_ticket(c) for c in otros if c["bucket"] == R.CAMBIO]
    hojas["4 Cambio"] = pd.DataFrame(camb)
    hojas["5 Cambio ultima semana"] = pd.DataFrame([f for f in camb if f["creado"] >= hace7])
    hojas["6 Sin revisar"] = pd.DataFrame([fila_ticket(c) for c in otros if c["bucket"] == R.SIN_REVISAR])
    hojas["7 PV en titulo"] = pd.DataFrame([fila_ticket(c) for c in otros if c["bucket"] == R.PV_TITULO])
    hojas["8 No recepcionado"] = pd.DataFrame([fila_ticket(c) for c in otros if c["bucket"] == R.NO_RECEPCIONADO])
    resumen = [("Clasificación", k, v, None) for k, v in conteo.most_common()]
    resumen += [("Agente", "emitiría NC", len(acciones), round(sum(a["monto_est"] for a in acciones)))]
    resumen += [("Agente", f"marca {k}", len(v), None) for k, v in marcas.items()]
    resumen += [("Manual", f"{g} · {e}", n, None) for (g, e), n in sorted(cm.items())]
    with pd.ExcelWriter(EXCEL) as w:
        pd.DataFrame(resumen, columns=["bloque", "concepto", "tickets / NC", "monto"]).to_excel(w, sheet_name="Resumen", index=False)
        for n, d in hojas.items():
            d.to_excel(w, sheet_name=n, index=False)
    print(f"Excel de validación: {EXCEL}")

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

actual = {t["id"]: t.get("x_estado_nc") for t in tickets}
for est, lst in marcas.items():
    ids = [i for i, _ in lst if actual.get(i) != est]   # solo las que cambian
    if ids:
        ex("helpdesk.ticket", "write", ids, {"x_estado_nc": est})
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
            # La cantidad devuelta se REPARTE entre las líneas del mismo producto: una
            # boleta puede traer el producto repetido en varias líneas (qty 1 + qty 1).
            # Antes se escribía el total en CADA línea → se acreditaba el doble (4 NC
            # con $190.930 de exceso, 01-02 sep 2026). Además nunca se asigna más de lo
            # que trae la línea original, así la NC no puede superar a la boleta.
            pendiente = dict(a["lineas"])
            for l in ls:
                pid = l["product_id"][0] if l["product_id"] else 0
                resta = pendiente.get(pid, 0)
                if resta <= 0:
                    ex("account.move.line", "unlink", [l["id"]])
                    continue
                asignar = min(l["quantity"], resta)
                pendiente[pid] = resta - asignar
                if abs(l["quantity"] - asignar) > 0.001:
                    ex("account.move.line", "write", [l["id"]], {"quantity": asignar})
            sobra = {p: q for p, q in pendiente.items() if q > 0.001}
            if sobra:
                # El ticket pide devolver más unidades de las que tiene la boleta.
                print(f"  ⚠ boleta {bol['name']}: el ticket pide {sobra} unidades de más "
                      f"que la boleta — se acredita solo lo facturado")
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

# ---- 4) reporte semanal a Max (lunes, SOLO la primera corrida del día) ----
# Fix 15-sep: (a) antes salía en CADA corrida horaria del lunes (3+ mails/día);
# ahora solo en la ventana de la primera corrida (07:19 CLT = 11:00-12:30 UTC).
# (b) antes listaba TODOS los nc_previa históricos; ahora solo los NUEVOS de la semana.
hora_utc = datetime.datetime.utcnow().hour
if HOY.weekday() == 0 and LIVE and 11 <= hora_utc < 13:
    try:
        d7 = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        casos = ex("helpdesk.ticket", "search_read",
                   [("x_estado_nc", "=", "nc_previa"), ("write_date", ">=", d7)],
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
            cuerpo = "Hola Max,\n\nCasos NUEVOS de la última semana con NC PREVIA detectados por el agente (devolución llegó con NC ya emitida) — para investigar:\n\n"
            cuerpo += "\n".join(f"- #{c['ticket_ref']} {c['name']}" for c in casos)
            cuerpo += "\n\n(Solo se listan los detectados en los últimos 7 días; el histórico completo queda filtrable en el Helpdesk por Estado NC = 'NC previa'.)\n\nSaludos,\nAgente NC Postventa"
            msg = EmailMessage()
            msg["To"] = "maximiliano@unionx.cl"
            msg["Cc"] = "andres@unionx.cl"
            msg["From"] = "andres@unionx.cl"
            msg["Subject"] = f"[Agente NC] Reporte semanal: {len(casos)} tickets NUEVOS con NC previa"
            msg.set_content(cuerpo)
            svc.users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}).execute()
            print(f"reporte semanal a Max enviado ({len(casos)} casos)")
    except Exception as e:
        print(f"reporte semanal falló: {str(e)[:150]}")
