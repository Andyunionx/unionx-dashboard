# -*- coding: utf-8 -*-
"""Agente Tickets Helpdesk → NC (decisión Andrés 26-08-2026: opción B, emisión y
posteo automático, activo desde el LUNES 31-08-2026).

Reglas: ver nc_reglas.py (Max, correo 17-sep-2026; complemento Andrés 05-oct). Resumen:
  - Gatillo: Motivo == "Devolución" + Resolución no vacía + producto recepcionado
    (Estado Nuevo / Outlet / Merma). Motivo "Cambio" = canal manual sin confirmar.
  - Se emiten a mano (el agente no los toca): Fidelización, Distribución, UnionX B2B
    y Kitchen Center (las 3 webs entran al automático desde el 19-oct). Fuera también
    los tickets con "PV" + OC en el título.
  - OC del canal en propiedad "Nº Orden de compra" (normalizar prefijo PV/espacios).
    Se busca como referencia del canal, nombre del pedido o pack de Yuju (las OC de
    Mercado Libre «2000013…» son el pack, no la orden: 19-oct).
  - Fulfillment (despacho desde bodega BF*) NO lleva NC: se descuenta en la
    liquidación del marketplace (Víctor 04-08).
  - NC POR LÍNEA: "Producto Comprado" × "Cantidad". Varios tickets de una OC → una
    NC agrupada. Fecha NC = "F. recepción PV" (si su mes está cerrado → hoy).
  - Si la boleta YA tiene NC (no creada por este agente) → NO emitir; marcar
    'NC previa (investigar)' → reporte semanal a Max (lunes).
Formato NC = wizard account.move.reversal (igual que facturación): tipo 61,
código referencia SII 1 (devolución total) / 3 (parcial). El envío al SII lo
hace el cron 26 estándar.

Inventario (Andrés 20-oct, probado en test3): cada NC por devolución va con su
devolución de stock, en este orden:
  1) devolución del despacho original (solo las unidades del ticket) a CA1/Output;
  2) NC: toma el costo de esa devolución y la 111009 queda en cero;
  3) traslado CA1/Output → BPV/Entrada «devuelto por recepcionar», que valida el
     agente. Odoo crea solo el BPV/STOR (Entrada → Stock), que valida bodega.
Solo para productos recibidos desde el 07-oct (CORTE_BPV): hasta el 06-oct Postventa
los ingresaba a BPV (recepción sin OC y conteo del 06-oct) y devolverlos duplicaría el stock.
Sin despacho único desde CA1/Output, o con una devolución que no hizo el agente, sale
solo la NC (como antes del 20-oct).
La devolución vuelve a la bodega de donde salió el despacho (CA1/Output, Full u OOB) y
de ahí se traslada a BPV. Ventas Fulfillment (Andrés 21-oct): no llevan NC, pero con
vars.AGENTE_NC_FULL_INVENTARIO=true el producto recibido vuelve igual a la bodega Full y
pasa a BPV; la regla 45 reversa el costo Full y el ticket queda «no_aplica».
Cambios (Andrés 21-oct): con vars.AGENTE_NC_CAMBIO_INVENTARIO=true, el producto recibido de
un cambio (canal automático, recepcionado, sin error de despacho) vuelve del despacho
original SIN reembolso y pasa a BPV; el reemplazo sale como hoy (salida «PV»+OC de bodega)
y la 111009 queda en cero con el par. El ticket no se marca: si el cambio termina en
devolución, la NC reutiliza esa misma devolución. vars.AGENTE_NC_CAMBIO_EXCLUIR deja en
espera los tickets que se listen ahí.
Reglas de Max del 22-oct (ver nc_reglas.py): «Aplica Reembolso» = No deja la devolución sin
NC; un Cambio con «Sí» lleva NC por la diferencia, que se emite a mano (va a la hoja de
manuales del pulso). Error de despacho (el ticket trae «SKU recibido»): la NC es por lo
comprado, pero a BPV entra lo que llegó. Con vars.AGENTE_NC_ERROR_DESPACHO_INVENTARIO=true
lo comprado vuelve del despacho a CA1/Stock (en realidad nunca salió) y lo que llegó pasa de
CA1/Stock a BPV/Entrada; sin la variable, esos casos salen solo con la NC (antes entraba a
BPV el SKU comprado).

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
# BPV/Stock quedó igual al conteo físico de Francisca del 06-oct (ajuste del 14-oct) y desde
# el 03-oct Postventa casi no registró recepciones sin OC (5 unidades entre el 5 y el 13-oct):
# lo recibido desde el 07-oct no está en Odoo (cruce con la lista de Max del 20-oct).
CORTE_BPV = "2026-10-07"
CA1_STOCK, CA1_OUTPUT, BPV_ENTRADA, T_BPV_INT = 8, 11, 3327, 165
FULL_INV = os.environ.get("AGENTE_NC_FULL_INVENTARIO", "").strip().lower() == "true"
CAMBIO_INV = os.environ.get("AGENTE_NC_CAMBIO_INVENTARIO", "").strip().lower() == "true"
ERROR_INV = os.environ.get("AGENTE_NC_ERROR_DESPACHO_INVENTARIO", "").strip().lower() == "true"
# Cambios en espera (tickets separados por comas): no se devuelven mientras estén en la variable.
CAMBIO_EXCLUIR = {t.strip().lstrip("#") for t in os.environ.get("AGENTE_NC_CAMBIO_EXCLUIR", "").split(",") if t.strip()}
EXCEL =sys.argv[sys.argv.index("--excel") + 1] if "--excel" in sys.argv else None

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
    return {"t": t, "canal": R.canal_canonico(R.texto(t, "Canal")), "estado": R.texto(t, "Estado"), "oc": oc,
            "prod": prop(t, "Producto Comprado"), "qty": prop(t, "Cantidad") or 0,
            "frecep": prop(t, "F. recepción PV"), "bucket": bucket, "detalle": detalle,
            "motivo": R.texto(t, "Motivo"), "reembolso": R.texto(t, "Aplica Reembolso"),
            "sku_rec": prop(t, "SKU recibido si fue error de despacho"),
            "qty_rec": prop(t, "Cantidad recibida si fue error de despacho") or 0}

def pid_de(v):
    return v[0] if isinstance(v, (list, tuple)) else v

def recibido(cs):
    """Error de despacho (Max, 22-oct): {SKU que llegó: unidades} de los tickets de una OC, y si la
    OC mezcla tickets con y sin error. Un «SKU recibido» igual a lo comprado no es error."""
    rec, con, sin = collections.Counter(), 0, 0
    for c in cs:
        r = pid_de(c["sku_rec"])
        if r and r != pid_de(c["prod"]):
            rec[r] += c["qty_rec"] or c["qty"]
            con += 1
        else:
            sin += 1
    return dict(rec), bool(con and sin)

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
# Cambios con producto recibido, de canales automáticos (en los manuales «Cambio» es un
# estado de espera hasta que Max confirma). Los de error de despacho entran con su propio
# tratamiento de inventario (planificar_inventario).
cam_por_oc = collections.defaultdict(list)
for c in otros:
    t = c["t"]
    if (c["bucket"] == R.CAMBIO and c["detalle"] == "canal automático" and c["oc"] and c["prod"] and c["qty"]
            and R.texto(t, "Resolución") and c["estado"] in R.ESTADOS_RECEPCIONADO
            and not R.RE_PV_TITULO.search(t.get("name") or "")):
        cam_por_oc[c["oc"]].append(c)
ocs = sorted(set(por_oc) | set(man_por_oc) | set(cam_por_oc))
ocs_set = set(ocs)
print("resolviendo pedidos por lote...")
B = 400
ord_por_oc = collections.defaultdict(list)
for i in range(0, len(ocs), B):
    ch = ocs[i:i+B]
    variantes = ch + ["#" + o for o in ch]
    for o in ex("sale.order", "search_read",
                ["|", "|", ("channel_order_reference", "in", variantes), ("name", "in", ch),
                 ("yuju_pack_id", "in", ch)],
                fields=["id", "name", "channel_order_reference", "yuju_pack_id", "invoice_ids"], limit=5000):
        key = norm_oc(o.get("channel_order_reference") or "") or o["name"]
        pack = norm_oc(o.get("yuju_pack_id") or "")
        if key in ocs_set:
            ord_por_oc[key].append(o)
        elif o["name"] in ocs_set:
            ord_por_oc[o["name"]].append(o)
        elif pack in ocs_set:
            ord_por_oc[pack].append(o)
# Pedidos despachados desde una bodega Full (BF*): no llevan NC. Casi nunca tienen
# boleta (13.384 de 13.386 entre ago y oct-2026), pero los que sí la tienen no deben
# salir por el agente.
oid_all = sorted({o["id"] for os_ in ord_por_oc.values() for o in os_})
ped_full = set()
for i in range(0, len(oid_all), 400):
    for p in ex("stock.picking", "search_read", [("sale_id", "in", oid_all[i:i+400])],
                fields=["sale_id", "location_id"], limit=10000):
        if str(p["location_id"][1] if p["location_id"] else "").split("/")[0].startswith("BF"):
            ped_full.add(p["sale_id"][0])
print(f"pedidos Fulfillment entre los cruzados: {len(ped_full)}")
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

def monto_oc(bol, cs):
    """Monto estimado de la NC de una OC: precio de la boleta × unidades del ticket."""
    por_prod = {l["product_id"][0]: l for l in lin_por_bol.get(bol["id"], []) if l["product_id"]}
    m = 0
    for c in cs:
        pid = c["prod"][0] if isinstance(c["prod"], (list, tuple)) else c["prod"]
        if pid in por_prod:
            m += por_prod[pid]["price_unit"] * min(c["qty"] or 0, por_prod[pid]["quantity"])
    return m


ctx_oc = {}     # oc -> (boleta, monto estimado, pedido), solo para el Excel de validación / pulso
acciones = []   # (boleta, [tickets], lineas {product_id: qty}, total_flag, fecha)
inv_full = []   # ventas Fulfillment recibidas: solo inventario, sin NC
for oc, cs in por_oc.items():
    tids = [c["t"]["id"] for c in cs]
    ords = ord_por_oc.get(oc, [])
    if len(ords) != 1:
        marcas["revisar"] += [(i, f"pedido {'no encontrado' if not ords else 'ambiguo'} para OC {oc}") for i in tids]
        continue
    boletas = [bol_por_id[i] for i in ords[0]["invoice_ids"] if i in bol_por_id]
    if ords[0]["id"] in ped_full:
        marcas["revisar" if boletas else "sin_boleta"] += [
            (i, f"OC {oc} Fulfillment: se descuenta en la liquidación, no lleva NC") for i in tids]
        lin_f = collections.Counter()
        for c in cs:
            lin_f[c["prod"][0] if isinstance(c["prod"], (list, tuple)) else c["prod"]] += c["qty"]
        rec, mixto = recibido(cs)
        inv_full.append({"bol": None, "pedido": ords[0]["name"], "so_id": ords[0]["id"], "tids": tids,
                         "trefs": [c["t"]["ticket_ref"] for c in cs], "lineas": dict(lin_f), "oc": oc,
                         "rec": rec, "mixto": mixto,
                         "frecep": min((c["frecep"] for c in cs if c["frecep"]), default=None), "con_boleta": bool(boletas),
                         "estados": ", ".join(sorted({str(c["estado"]) for c in cs if c["estado"]}))})
        continue
    if not boletas:
        marcas["sin_boleta"] += [(i, f"OC {oc} sin boleta posteada") for i in tids]
        continue
    if len(boletas) > 1:
        marcas["revisar"] += [(i, f"OC {oc} con {len(boletas)} boletas") for i in tids]
        continue
    bol = boletas[0]
    ctx_oc[oc] = (bol, monto_oc(bol, cs), ords[0]["name"])
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
    # Unidades facturadas por producto SUMANDO sus líneas: una boleta puede traer el mismo
    # producto en varias líneas (1 + 1). Comparando contra una sola línea, un ticket de 1
    # unidad parecía devolución total y la NC acreditaba la boleta completa (18 NC con
    # $410.523 neto de más, sep-oct 2026).
    cant_bol = collections.Counter()
    for l in lin_por_bol.get(bol["id"], []):
        if l["product_id"]:
            cant_bol[l["product_id"][0]] += l["quantity"]
    lineas, problema = {}, None
    for c in cs:
        pid = c["prod"][0] if isinstance(c["prod"], (list, tuple)) else c["prod"]
        if pid not in por_prod:
            problema = f"producto {c['prod'][1] if isinstance(c['prod'],(list,tuple)) else pid} no está en boleta {bol['name']}"
            break
        if lineas.get(pid, 0) + c["qty"] > cant_bol[pid]:
            problema = f"cantidad ticket ({lineas.get(pid, 0) + c['qty']}) > facturada ({cant_bol[pid]:g})"
            break
        lineas[pid] = lineas.get(pid, 0) + c["qty"]
    if problema:
        marcas["revisar"] += [(i, problema) for i in tids]
        continue
    total_flag = (set(lineas) == set(cant_bol)) and all(lineas[p] == cant_bol[p] for p in lineas)
    frecep = min((c["frecep"] for c in cs if c["frecep"]), default=None)
    if frecep and str(frecep)[:7] == f"{HOY:%Y-%m}":
        fecha_nc = str(frecep)[:10]
    else:
        fecha_nc = str(HOY)
    rec, mixto = recibido(cs)
    acciones.append({"bol": bol, "pedido": ords[0]["name"], "so_id": ords[0]["id"], "tids": tids,
                     "trefs": [c["t"]["ticket_ref"] for c in cs], "lineas": lineas, "total": total_flag,
                     "fecha": fecha_nc, "oc": oc, "frecep": frecep, "rec": rec, "mixto": mixto,
                     "estados": ", ".join(sorted({str(c["estado"]) for c in cs if c["estado"]})),
                     "monto_est": sum(por_prod[p]["price_unit"] * q for p, q in lineas.items())})


def planificar_inventario(lst):
    """Decide, para cada NC, si va con devolución de inventario (ver docstring). Solo lee.
    Deja en cada acción: inv (despacho, unidades por movimiento, devolución a retomar) o None,
    inv_motivo (texto para el Excel y el ticket) y costo_dev (costo de las unidades del ticket)."""
    so_ids = sorted({a["so_id"] for a in lst})
    outs = collections.defaultdict(list)
    for i in range(0, len(so_ids), 400):
        for p in ex("stock.picking", "search_read", [("sale_id", "in", so_ids[i:i+400]), ("state", "=", "done"),
                                                     ("location_dest_id.usage", "=", "customer")],
                    fields=["id", "name", "sale_id", "location_id"], limit=5000):
            outs[p["sale_id"][0]].append(p)
    out_ids = [p["id"] for ps in outs.values() for p in ps]
    devs, movs = collections.defaultdict(list), collections.defaultdict(list)
    for i in range(0, len(out_ids), 400):
        ch = out_ids[i:i+400]
        for r in ex("stock.picking", "search_read", [("return_id", "in", ch), ("state", "!=", "cancel")],
                    fields=["id", "name", "state", "origin", "return_id"], limit=5000):
            devs[r["return_id"][0]].append(r)
        for m in ex("stock.move", "search_read", [("picking_id", "in", ch), ("state", "=", "done")],
                    fields=["id", "picking_id", "product_id", "quantity", "bom_line_id", "sale_line_id"], limit=20000):
            movs[m["picking_id"][0]].append(m)
    mids = [m["id"] for ms in movs.values() for m in ms]
    val = collections.defaultdict(lambda: [0.0, 0.0])
    for i in range(0, len(mids), 800):
        for l in ex("stock.valuation.layer", "search_read", [("stock_move_id", "in", mids[i:i+800])],
                    fields=["stock_move_id", "value", "quantity"], limit=20000):
            val[l["stock_move_id"][0]][0] += l["value"]
            val[l["stock_move_id"][0]][1] += l["quantity"]
    costo_u = {k: abs(v / q) if q else 0 for k, (v, q) in val.items()}
    slids = sorted({m["sale_line_id"][0] for ms in movs.values() for m in ms if m["sale_line_id"]})
    sl = {}
    for i in range(0, len(slids), 800):
        for l in ex("sale.order.line", "read", slids[i:i+800], fields=["product_id", "product_uom_qty"]):
            sl[l["id"]] = l
    # Kits NO inventariables (47 al 20-oct): Odoo no les pone línea de costo ni en la boleta ni
    # en la NC, así que la devolución dejaría la 111009 descuadrada (test3). Solo NC hasta
    # marcarlos como inventariables, como los otros 464.
    pids = sorted({p for a in lst for p in a["lineas"]})
    kit_no_inv = set()
    for i in range(0, len(pids), 800):
        kit_no_inv |= {p["id"] for p in ex("product.product", "read", pids[i:i+800], fields=["is_kits", "is_storable"])
                       if p["is_kits"] and not p["is_storable"]}
    # Error de despacho: lo que llegó pasa de CA1/Stock a BPV, así que en Odoo tiene que estar en
    # CA1/Stock y no ser un kit (un kit no se traslada, solo sus componentes).
    rec_pids = sorted({p for a in lst for p in a.get("rec") or {}})
    disp_ca1, rec_kit = collections.Counter(), set()
    if rec_pids:
        for q in ex("stock.quant", "search_read", [("product_id", "in", rec_pids), ("location_id", "child_of", CA1_STOCK)],
                    fields=["product_id", "quantity"], limit=10000):
            disp_ca1[q["product_id"][0]] += q["quantity"]
        rec_kit = {p["id"] for p in ex("product.product", "read", rec_pids, fields=["is_kits"]) if p["is_kits"]}
    for a in lst:
        a["inv"], a["costo_dev"] = None, 0
        os_ = outs.get(a["so_id"], [])
        if len(os_) != 1:
            a["inv_motivo"] = f"solo NC: pedido {'sin despacho' if not os_ else f'con {len(os_)} despachos'}"
            continue
        out = os_[0]
        # Unidades a devolver por movimiento del despacho. Un kit se vende en una línea y se
        # despacha por componentes: se devuelve la proporción del kit que trae el ticket.
        pend, cant = dict(a["lineas"]), {}
        for m in movs.get(out["id"], []):
            l = sl.get(m["sale_line_id"][0]) if m["sale_line_id"] else None
            p = l["product_id"][0] if l else m["product_id"][0]
            if p not in pend:
                continue
            if m["bom_line_id"] and l and l["product_uom_qty"]:
                q = round(m["quantity"] * min(1, a["lineas"][p] / l["product_uom_qty"]), 4)
            else:
                q = min(m["quantity"], pend[p])
                pend[p] -= q
            if q > 0:
                cant[m["id"]] = q
        a["costo_dev"] = sum(q * costo_u.get(mid, 0) for mid, q in cant.items())
        prev = devs.get(out["id"], [])
        ajenas = [r for r in prev if TAG not in str(r.get("origin") or "")]
        if not a["frecep"] or str(a["frecep"])[:10] < CORTE_BPV:
            a["inv_motivo"] = ("solo NC: recibido antes del 07-oct (ya está en BPV)" if a["frecep"]
                               else "solo NC: ticket sin F. recepción PV")
        elif not origen_ok(out["location_id"][1]):
            a["inv_motivo"] = f"solo NC: despachado desde {out['location_id'][1]}"
        elif ajenas:
            a["inv_motivo"] = f"solo NC: el despacho ya tiene la devolución {ajenas[0]['name']}"
        elif not cant:
            a["inv_motivo"] = "solo NC: el producto del ticket no está en el despacho"
        elif kit_no_inv & set(a["lineas"]):
            a["inv_motivo"] = "solo NC: kit no inventariable en Odoo"
        elif a.get("rec"):
            # Si una corrida anterior ya hizo la devolución, el traslado puede estar hecho y el
            # stock de lo que llegó ya descontado: no se vuelve a exigir.
            falta = [] if prev else [p for p, q in a["rec"].items() if p in rec_kit or disp_ca1[p] < q]
            if not ERROR_INV:
                a["inv_motivo"] = "solo NC: error de despacho (inventario a mano; AGENTE_NC_ERROR_DESPACHO_INVENTARIO)"
            elif a["mixto"]:
                a["inv_motivo"] = "solo NC: error de despacho mezclado con otros tickets de la OC (inventario a mano)"
            elif out["location_id"][0] != CA1_OUTPUT:
                a["inv_motivo"] = f"solo NC: error de despacho desde {out['location_id'][1]} (inventario a mano)"
            elif falta:
                a["inv_motivo"] = "solo NC: error de despacho, lo que llegó es kit o no tiene stock en CA1/Stock (inventario a mano)"
            else:
                for p, q in a["rec"].items():
                    disp_ca1[p] -= q
                a["inv"] = {"out": out, "cant": cant, "ret": prev[0]["id"] if prev else None, "rec": a["rec"]}
                a["inv_motivo"] = ("error de despacho: lo comprado vuelve a CA1/Stock y lo que llegó pasa a BPV"
                                   + (f" (retoma {prev[0]['name']})" if prev else ""))
        else:
            a["inv"] = {"out": out, "cant": cant, "ret": prev[0]["id"] if prev else None}
            a["inv_motivo"] = (f"devolución a {out['location_id'][1]} y traslado a BPV"
                               + (f" (retoma {prev[0]['name']})" if prev else ""))


def origen_ok(nombre):
    """Bodegas a las que vuelve la devolución en Odoo antes de pasar a BPV: CA1/Output, Full
    (BF*, BKC1) y OOB. Otras (consignación, tiendas) siguen saliendo solo con NC."""
    raiz = str(nombre).split("/")[0]
    return nombre == "CA1/Output" or raiz.startswith("BF") or raiz in ("BKC1", "OOB")


# Lo que sale en un cambio es el pick con documento origen «PV» + OC; si no existe, el cambio no
# se ha despachado (Max, 22-oct).
pv_por_oc = collections.defaultdict(list)
oc_c = sorted(cam_por_oc)
for i in range(0, len(oc_c), 400):
    ch = oc_c[i:i+400]
    for p in ex("stock.picking", "search_read", [("origin", "in", [f"PV{o}" for o in ch] + [f"PV#{o}" for o in ch]),
                                                 ("state", "!=", "cancel")],
                fields=["name", "origin", "state", "location_id"], limit=5000):
        pv_por_oc[norm_oc(p["origin"])].append(p)

inv_cambio = []   # cambios: solo inventario, sin NC ni reembolso
for oc, cs in cam_por_oc.items():
    ords = ord_por_oc.get(oc, [])
    if len(ords) != 1:
        continue
    lin_c = collections.Counter()
    for c in cs:
        lin_c[c["prod"][0] if isinstance(c["prod"], (list, tuple)) else c["prod"]] += c["qty"]
    rec, mixto = recibido(cs)
    frecep = min((c["frecep"] for c in cs if c["frecep"]), default=None)
    pvs = pv_por_oc.get(oc, [])
    obs = []
    if any(c["reembolso"] == "Sí" for c in cs):
        obs.append("Aplica Reembolso = Sí: NC por la diferencia, a mano")
    if frecep and str(frecep)[:10] >= CORTE_BPV:
        if not pvs:
            obs.append("sin pick PV: el cambio no se ha despachado")
        elif any(c["motivo"] == "Reenvío" for c in cs) and any(p["location_id"][1].startswith("CA1/") for p in pvs):
            # La unidad que vuelve al cliente está en BPV: si el pick sale de CA1, BPV queda
            # con una unidad fantasma y CA1 con una de menos.
            obs.append("reenvío: el pick PV sale de CA1 y la unidad está en BPV (debería salir de BPV)")
    inv_cambio.append({"bol": None, "pedido": ords[0]["name"], "so_id": ords[0]["id"], "tids": [c["t"]["id"] for c in cs],
                       "trefs": [c["t"]["ticket_ref"] for c in cs], "lineas": dict(lin_c), "oc": oc, "cambio": True,
                       "frecep": frecep, "rec": rec, "mixto": mixto,
                       "motivo": ", ".join(sorted({c["motivo"] for c in cs})),
                       "reembolso": ", ".join(sorted({c["reembolso"] for c in cs if c["reembolso"]})),
                       "pv": ", ".join(f"{p['name']} ({p['state']}, {p['location_id'][1]})" for p in pvs),
                       "obs": "; ".join(obs),
                       "estados": ", ".join(sorted({str(c["estado"]) for c in cs if c["estado"]}))})
planificar_inventario(acciones + inv_full + inv_cambio)

# Lista de boletas autorizadas (Andrés 05-oct, opción 2): mientras la variable tenga
# boletas, se emiten SOLO esas; el resto queda retenido (sin marcar) hasta validarlo.
# Vacía = sin restricción.
AUTORIZADAS = {b.strip() for b in os.environ.get("AGENTE_NC_BOLETAS_AUTORIZADAS", "").split(",") if b.strip()}
retenidas = []
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
for nombre_l, lst_ in (("a emitir", acciones), ("retenidas", retenidas), ("Fulfillment (sin NC)", inv_full),
                       ("cambios (sin NC)", inv_cambio)):
    inv_c = collections.Counter(a["inv_motivo"].split(" (retoma")[0] for a in lst_)
    if inv_c:
        print(f"inventario de las NC {nombre_l}: {dict(inv_c)} · costo devuelto "
              f"${sum(a['costo_dev'] for a in lst_ if a['inv']):,.0f}")
obs_c = collections.Counter(o for a in inv_cambio for o in a["obs"].split("; ") if o)
if obs_c:
    print(f"cambios, observaciones: {dict(obs_c)}")
for est, lst in marcas.items():
    print(f"\n{est}: {len(lst)}")
    for tid, m in lst[:6]:
        print(f"   ticket {tid}: {m}")


def estado_manual(oc, cs):
    """Estado NC de una OC de canal manual, con las mismas consultas del agente. Solo informa."""
    ords = ord_por_oc.get(oc, [])
    if len(ords) != 1:
        return f"pedido {'no encontrado' if not ords else 'ambiguo'}", None, 0
    if ords[0]["id"] in ped_full:
        return "Fulfillment (no lleva NC)", None, 0
    boletas = [bol_por_id[i] for i in ords[0]["invoice_ids"] if i in bol_por_id]
    if not boletas:
        return "sin boleta", None, 0
    if len(boletas) > 1:
        return f"{len(boletas)} boletas", None, 0
    bol = boletas[0]
    if nc_por_bol.get(bol["id"]) or str(bol.get("l10n_latam_document_number") or "") in nc_ref_folios:
        return "ya tiene NC", bol, 0
    if fecha_bol.get(bol["id"], "9999") < LIM_PLAZO:
        return "fuera de plazo (3 meses)", bol, monto_oc(bol, cs)
    return "PENDIENTE NC", bol, monto_oc(bol, cs)


filas_man = []
for oc, cs in man_por_oc.items():
    est, bol, monto = estado_manual(oc, cs)
    ords = ord_por_oc.get(oc, [])
    for c in cs:
        filas_man.append({"grupo": c["detalle"], "canal": c["canal"], "ticket": c["t"]["ticket_ref"],
                          "titulo": c["t"]["name"], "oc": oc, "pedido": ords[0]["name"] if len(ords) == 1 else "",
                          "estado NC": est,
                          "boleta": bol["name"] if bol else "", "fecha boleta": fecha_bol.get(bol["id"]) if bol else "",
                          "monto estimado OC": round(monto)})
for c in manuales:
    if not c["oc"]:
        filas_man.append({"grupo": c["detalle"], "canal": c["canal"], "ticket": c["t"]["ticket_ref"],
                          "titulo": c["t"]["name"], "oc": "", "pedido": "", "estado NC": "sin Nº de orden",
                          "boleta": "", "fecha boleta": "", "monto estimado OC": 0})
# Cambio con «Aplica Reembolso» = Sí (Max, 22-oct): NC por la diferencia entre lo devuelto y lo que
# salió con el pick PV. El pick no tiene precio en Odoo, así que la emite Facturación; el monto
# de la hoja es el precio en boleta de lo devuelto (el tope de esa NC).
for oc, cs in cam_por_oc.items():
    if not any(c["reembolso"] == "Sí" for c in cs):
        continue
    est, bol, monto = estado_manual(oc, cs)
    ords = ord_por_oc.get(oc, [])
    for c in cs:
        filas_man.append({"grupo": "Cambio con reembolso (NC por la diferencia)", "canal": c["canal"],
                          "ticket": c["t"]["ticket_ref"], "titulo": c["t"]["name"], "oc": oc,
                          "pedido": ords[0]["name"] if len(ords) == 1 else "", "estado NC": est,
                          "boleta": bol["name"] if bol else "", "fecha boleta": fecha_bol.get(bol["id"]) if bol else "",
                          "monto estimado OC": round(monto)})
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

    oc_de_tid = {c["t"]["id"]: c["oc"] for c in cand}

    def filas_nc(lst):
        return pd.DataFrame([{
            "boleta": a["bol"]["name"], "pedido": a["pedido"], "oc": a["oc"], "tickets": ", ".join("#" + str(r) for r in a["trefs"]),
            "canal": ", ".join(sorted({R.canal_canonico(R.texto(nombre_t[i], "Canal")) for i in a["tids"]})),
            "tipo": "total" if a["total"] else "parcial", "fecha NC": a["fecha"],
            "monto estimado": round(a["monto_est"]), "recepción PV": str(a["frecep"] or "")[:10],
            "estado producto": a["estados"], "inventario": a["inv_motivo"],
            "costo unidades": round(a["costo_dev"])} for a in lst],
            columns=["boleta", "pedido", "oc", "tickets", "canal", "tipo", "fecha NC", "monto estimado",
                     "recepción PV", "estado producto", "inventario", "costo unidades"])

    def fila_marca(est, tid, m):
        oc = oc_de_tid.get(tid, "")
        bol, monto, pedido = ctx_oc.get(oc, (None, 0, ""))
        return {"estado": est, "ticket": nombre_t[tid]["ticket_ref"], "titulo": nombre_t[tid]["name"],
                "canal": R.canal_canonico(R.texto(nombre_t[tid], "Canal")), "motivo": m, "oc": oc, "pedido": pedido,
                "boleta": bol["name"] if bol else "", "fecha boleta": fecha_bol.get(bol["id"], "") if bol else "",
                "monto estimado OC": round(monto)}

    hojas = {}
    hojas["1 Emitiría el agente"] = filas_nc(acciones)
    # Cumplen las reglas pero no están en la lista autorizada: esperan validación de Max.
    hojas["1b Retenidas"] = filas_nc(retenidas)
    hojas["1c Fulfillment inventario"] = pd.DataFrame([{
        "pedido": a["pedido"], "oc": a["oc"], "tickets": ", ".join("#" + str(r) for r in a["trefs"]),
        "canal": ", ".join(sorted({R.canal_canonico(R.texto(nombre_t[i], "Canal")) for i in a["tids"]})),
        "recepción PV": str(a["frecep"] or "")[:10], "estado producto": a["estados"], "inventario": a["inv_motivo"].replace("solo NC: ", "sin devolución: "),
        "costo unidades": round(a["costo_dev"]), "activo": "sí" if FULL_INV else "no (AGENTE_NC_FULL_INVENTARIO)"} for a in inv_full])
    hojas["1d Cambios inventario"] = pd.DataFrame([{
        "pedido": a["pedido"], "oc": a["oc"], "tickets": ", ".join("#" + str(r) for r in a["trefs"]),
        "canal": ", ".join(sorted({R.canal_canonico(R.texto(nombre_t[i], "Canal")) for i in a["tids"]})),
        "recepción PV": str(a["frecep"] or "")[:10], "estado producto": a["estados"],
        "motivo": a["motivo"], "aplica reembolso": a["reembolso"],
        "inventario": ("ya devuelto por el agente" if a["inv"] and a["inv"]["ret"] else a["inv_motivo"].replace("solo NC: ", "sin devolución: ")),
        "costo unidades": round(a["costo_dev"]), "pick PV": a["pv"], "observación": a["obs"],
        "activo": ("en espera (AGENTE_NC_CAMBIO_EXCLUIR)" if CAMBIO_EXCLUIR & {str(r) for r in a["trefs"]} else "sí")
                  if CAMBIO_INV else "no (AGENTE_NC_CAMBIO_INVENTARIO)"} for a in inv_cambio])
    hojas["2 Agente - revisar"] = pd.DataFrame([fila_marca(est, tid, m) for est, lst in marcas.items() for tid, m in lst])
    hojas["3 Manuales"] = pd.DataFrame(filas_man)
    hace7 = str(datetime.date.today() - datetime.timedelta(days=7))
    camb = [fila_ticket(c) for c in otros if c["bucket"] == R.CAMBIO]
    hojas["4 Cambio"] = pd.DataFrame(camb)
    hojas["5 Cambio ultima semana"] = pd.DataFrame([f for f in camb if f["creado"] >= hace7])
    hojas["6 Sin revisar"] = pd.DataFrame([fila_ticket(c) for c in otros if c["bucket"] == R.SIN_REVISAR])
    hojas["7 PV en titulo"] = pd.DataFrame([fila_ticket(c) for c in otros if c["bucket"] == R.PV_TITULO])
    hojas["8 No recepcionado"] = pd.DataFrame([fila_ticket(c) for c in otros if c["bucket"] == R.NO_RECEPCIONADO])
    hojas["9 Sin reembolso"] = pd.DataFrame([fila_ticket(c) for c in otros if c["bucket"] == R.SIN_REEMBOLSO])
    resumen = [("Clasificación", k, v, None) for k, v in conteo.most_common()]
    resumen += [("Agente", "emitiría NC", len(acciones), round(sum(a["monto_est"] for a in acciones)))]
    resumen += [("Agente", "retenida (lista autorizada)", len(retenidas), round(sum(a["monto_est"] for a in retenidas)))]
    for nombre_l, lst_ in (("emitiría", acciones), ("retenida", retenidas)):
        for mot, n in collections.Counter(a["inv_motivo"].split(" (retoma")[0] for a in lst_).most_common():
            resumen += [(f"Inventario ({nombre_l})", mot, n, round(sum(a["costo_dev"] for a in lst_ if a["inv_motivo"].startswith(mot))))]
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

def validar_picking(pid, dest):
    """Reserva, completa las cantidades y valida (mismo procedimiento probado en test3). Se
    completa aunque no se pueda reservar: CA1/Output tiene productos en negativo y el producto
    ya está físicamente en Postventa."""
    ex("stock.picking", "action_assign", [pid])
    mv = ex("stock.move", "search_read", [("picking_id", "=", pid)], fields=["id", "product_uom_qty", "quantity"])
    for m in mv:
        if m["quantity"] < m["product_uom_qty"]:
            ex("stock.move", "write", [m["id"]], {"quantity": m["product_uom_qty"]})
    ex("stock.move.line", "write", ex("stock.move.line", "search", [("picking_id", "=", pid)]), {"location_dest_id": dest})
    ex("stock.move", "write", [m["id"] for m in mv], {"picked": True})
    ex("stock.picking", "button_validate", [pid], context={"skip_sms": True, "skip_backorder": True})
    p = ex("stock.picking", "read", [pid], fields=["name", "state"])[0]
    if p["state"] != "done":
        raise Exception(f"{p['name']} quedó en estado {p['state']}")
    return p["name"]


def devolver(a):
    """Paso 1: devolución del despacho original a la bodega de donde salió (CA1/Output, Full u
    OOB), solo con las unidades del ticket y «a reembolsar». En un error de despacho lo comprado
    vuelve a CA1/Stock: en realidad nunca salió. Si una corrida anterior la dejó hecha, se retoma."""
    inv, out = a["inv"], a["inv"]["out"]
    dest = CA1_STOCK if inv.get("rec") else out["location_id"][0]
    if inv["ret"]:
        r = ex("stock.picking", "read", [inv["ret"]], fields=["name", "state"])[0]
        return inv["ret"], (r["name"] if r["state"] == "done" else validar_picking(inv["ret"], dest))
    ctx = {"active_model": "stock.picking", "active_id": out["id"], "active_ids": [out["id"]]}
    w = ex("stock.return.picking", "create", {"picking_id": out["id"]}, context=ctx)
    for l in ex("stock.return.picking.line", "search_read", [("wizard_id", "=", w)], fields=["id", "move_id"]):
        ex("stock.return.picking.line", "write", [l["id"]],
           {"quantity": inv["cant"].get(l["move_id"][0], 0), "to_refund": not a.get("cambio")})
    ex("stock.return.picking", "action_create_returns", [w], context=ctx)
    ret_id = ex("stock.picking", "search", [("return_id", "=", out["id"]), ("state", "!=", "cancel")], order="id desc", limit=1)[0]
    ex("stock.picking", "write", [ret_id], {
        "location_dest_id": dest,
        "origin": f"{out['name']} {TAG} {','.join('#' + str(r) for r in a['trefs'])}]"})
    try:
        return ret_id, validar_picking(ret_id, dest)
    except Exception:
        ex("stock.picking", "action_cancel", [ret_id])
        raise


def trasladar(ret_id, ret_name, nota, recibido=None):
    """Paso 3: de la bodega donde quedó la devolución a BPV/Entrada «devuelto por recepcionar»,
    validado por el agente. Odoo crea solo el BPV/STOR (Entrada → Stock) que valida bodega.
    En un error de despacho (recibido = {producto: unidades}) pasa a BPV lo que llegó, desde
    CA1/Stock, donde Odoo todavía lo tiene. No duplica: si la devolución ya tiene traslado, no
    hace nada."""
    prev = ex("stock.picking", "search_read", [("picking_type_id", "=", T_BPV_INT), ("origin", "=like", f"{ret_name} ·%"),
                                               ("state", "!=", "cancel")], fields=["id", "state"], limit=1)
    if prev:
        # Ya existe: si una corrida cortada lo dejó sin validar, se valida ahora (test3 21-oct).
        if prev[0]["state"] == "done":
            return None
        if prev[0]["state"] == "draft":
            ex("stock.picking", "action_confirm", [prev[0]["id"]])
        return validar_picking(prev[0]["id"], BPV_ENTRADA)
    if recibido:
        origen = CA1_STOCK
        lineas = [(p["id"], p["display_name"], recibido[p["id"]], p["uom_id"][0])
                  for p in ex("product.product", "read", list(recibido), fields=["display_name", "uom_id"])]
    else:
        origen = ex("stock.picking", "read", [ret_id], fields=["location_dest_id"])[0]["location_dest_id"][0]
        lineas = [(m["product_id"][0], m["product_id"][1], m["quantity"], m["product_uom"][0])
                  for m in ex("stock.move", "search_read", [("picking_id", "=", ret_id), ("state", "=", "done")],
                              fields=["product_id", "quantity", "product_uom"]) if m["quantity"]]
    pid = ex("stock.picking", "create", {
        "picking_type_id": T_BPV_INT, "location_id": origen, "location_dest_id": BPV_ENTRADA,
        "origin": f"{ret_name} · {nota} · devuelto por recepcionar",
        "move_ids": [(0, 0, {"name": n[:60], "product_id": p, "product_uom_qty": q, "product_uom": u,
                             "location_id": origen, "location_dest_id": BPV_ENTRADA}) for p, n, q, u in lineas]})
    ex("stock.picking", "action_confirm", [pid])
    return validar_picking(pid, BPV_ENTRADA)


# Devoluciones del agente (últimos 30 días) que quedaron sin traslado a BPV (corrida cortada entre pasos).
# Fuera las de error de despacho (vuelven a CA1/Stock): ahí lo que pasa a BPV es otro producto,
# que solo conoce el ticket; si quedaron sin traslado, se avisa para completarlo a mano.
hace30 = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
for r in ex("stock.picking", "search_read", [("origin", "ilike", TAG), ("state", "=", "done"), ("return_id", "!=", False),
                                             ("create_date", ">=", hace30), ("location_dest_id.usage", "=", "internal"),
                                             ("location_dest_id", "!=", CA1_STOCK)],
            fields=["id", "name", "origin"], limit=500):
    try:
        tr = trasladar(r["id"], r["name"], r["origin"].split(TAG)[-1].strip(" ]"))
        if tr:
            print(f"  ↪ traslado pendiente completado: {r['name']} → {tr}")
    except Exception as e:
        print(f"  ⚠ traslado pendiente de {r['name']} falló: {str(e)[:150]}")
for r in ex("stock.picking", "search_read", [("origin", "ilike", TAG), ("state", "=", "done"), ("return_id", "!=", False),
                                             ("create_date", ">=", hace30), ("location_dest_id", "=", CA1_STOCK)],
            fields=["id", "name", "origin"], limit=500):
    if not ex("stock.picking", "search_count", [("picking_type_id", "=", T_BPV_INT), ("origin", "=like", f"{r['name']} ·%"),
                                                ("state", "=", "done")]):
        print(f"  ⚠ error de despacho {r['name']} ({r['origin']}): lo que llegó no pasó a BPV, completar a mano")

actual = {t["id"]: t.get("x_estado_nc") for t in tickets}
for est, lst in marcas.items():
    ids = [i for i, _ in lst if actual.get(i) != est]   # solo las que cambian
    if ids:
        ex("helpdesk.ticket", "write", ids, {"x_estado_nc": est})
print("campos marcados (no emisores)")

emitidas, errores, sin_inv = 0, [], []
for a in acciones[:MAX_NC_POR_CORRIDA]:
    try:
        bol = a["bol"]
        # 1) Primero la devolución: así la NC toma el costo del despacho original. Si emitiera
        # antes, tomaría el costo promedio de hoy y la 111009 quedaría con diferencia (test3).
        ret, nota_inv = None, f" Inventario: {a['inv_motivo']}."
        if a["inv"]:
            try:
                ret = devolver(a)
            except Exception as e:
                # No se frena la NC (es del cliente): sale como antes del 20-oct y queda avisado.
                nota_inv = f" Devolución de inventario NO hecha ({str(e)[:120]}): revisar con bodega."
                sin_inv.append((a["oc"], f"devolución: {str(e)[:150]}"))
                print(f"  ⚠ OC {a['oc']}: la devolución de inventario falló, sale solo la NC: {str(e)[:120]}")
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
        nc_name = ex("account.move", "read", [nc["id"]], fields=["name"])[0]["name"]
        if ret:
            # 3) Traslado a BPV/Entrada; si falla, la próxima corrida lo completa (barrido de arriba).
            rec = a["inv"].get("rec")
            try:
                tr = trasladar(ret[0], ret[1], f"{nc_name} ({a['estados'] or 'sin estado'})", rec)
                nota_inv = (f" Error de despacho: lo comprado volvió a CA1/Stock ({ret[1]}) y lo que llegó pasó a "
                            f"BPV/Entrada ({tr}); bodega valida el BPV/STOR." if rec else
                            f" Producto devuelto ({ret[1]}) y trasladado a BPV/Entrada ({tr}); bodega valida el BPV/STOR.")
            except Exception as e:
                nota_inv = (f" Error de despacho: lo comprado volvió a CA1/Stock ({ret[1]}); lo que llegó NO pasó a BPV, "
                            f"completar a mano ({str(e)[:100]})." if rec else
                            f" Producto devuelto ({ret[1]}); el traslado a BPV queda para la próxima corrida ({str(e)[:100]}).")
                sin_inv.append((a["oc"], f"traslado: {str(e)[:150]}"))
        marcar(a["tids"], "nc_creada", f"NC emitida por boleta {bol['name']} (${chk['amount_total']:,.0f}).{nota_inv}")
        emitidas += 1
        print(f"  ✔ NC posteada boleta {bol['name']} ${chk['amount_total']:,.0f} tickets {a['trefs']}"
              + (f" · {ret[1]} → BPV" if ret else f" · {a['inv_motivo']}"))
    except Exception as e:
        errores.append((a["oc"], str(e)[:200]))
        try:
            ex("helpdesk.ticket", "write", a["tids"], {"x_estado_nc": "revisar"})
        except Exception:
            pass
        print(f"  ✘ ERROR OC {a['oc']}: {str(e)[:160]}")

print(f"\nEMITIDAS: {emitidas} | errores: {len(errores)} | pendientes próxima corrida: {max(0, len(acciones)-MAX_NC_POR_CORRIDA)}")
if sin_inv:
    print(f"inventario con problema ({len(sin_inv)}): {sin_inv[:10]}")

# Ventas Fulfillment recibidas por Postventa: sin NC, solo devolución a la bodega Full + traslado a BPV.
if FULL_INV:
    hechas_f = 0
    for a in [x for x in inv_full if x["inv"]][:MAX_NC_POR_CORRIDA]:
        try:
            ret = devolver(a)
            tr = trasladar(ret[0], ret[1], f"Fulfillment sin NC ({a['estados'] or 'sin estado'})")
            nota = (f"[Agente NC] Venta Fulfillment (sin NC): producto devuelto a {a['inv']['out']['location_id'][1]} "
                    f"({ret[1]}) y trasladado a BPV/Entrada ({tr or 'ya trasladado'}); bodega valida el BPV/STOR.")
            for tid in a["tids"]:
                ex("helpdesk.ticket", "message_post", [tid], body=nota)
            if not a["con_boleta"]:
                ex("helpdesk.ticket", "write", a["tids"], {"x_estado_nc": "no_aplica"})
            hechas_f += 1
            print(f"  ✔ Fulfillment {a['pedido']} tickets {a['trefs']} · {ret[1]} → BPV")
        except Exception as e:
            print(f"  ✘ Fulfillment {a['pedido']}: {str(e)[:160]}")
    print(f"Fulfillment devueltos a BPV: {hechas_f} de {sum(1 for x in inv_full if x['inv'])}")

# Cambios: devolución SIN reembolso del despacho original + traslado a BPV. Solo los que aún no
# tienen devolución del agente (el ticket no se marca; así no se repite cada corrida).
if CAMBIO_INV:
    hechos_c, pend_c = 0, [x for x in inv_cambio if x["inv"] and not x["inv"]["ret"]
                           and not CAMBIO_EXCLUIR & {str(r) for r in x["trefs"]}]
    for a in pend_c[:MAX_NC_POR_CORRIDA]:
        try:
            ret = devolver(a)
            rec = a["inv"].get("rec")
            tr = trasladar(ret[0], ret[1], f"Cambio sin NC ({a['estados'] or 'sin estado'})", rec)
            nota = (f"[Agente NC] Cambio por error de despacho (sin NC): lo comprado volvió a CA1/Stock ({ret[1]}, sin "
                    f"reembolso) y lo que llegó pasó a BPV/Entrada ({tr or 'ya trasladado'}); el reemplazo sale con la salida PV de bodega."
                    if rec else
                    f"[Agente NC] Cambio (sin NC): producto devuelto a {a['inv']['out']['location_id'][1]} ({ret[1]}, "
                    f"sin reembolso) y trasladado a BPV/Entrada ({tr or 'ya trasladado'}); el reemplazo sale con la salida PV de bodega.")
            for tid in a["tids"]:
                ex("helpdesk.ticket", "message_post", [tid], body=nota)
            hechos_c += 1
            print(f"  ✔ Cambio {a['pedido']} tickets {a['trefs']} · {ret[1]} → BPV")
        except Exception as e:
            print(f"  ✘ Cambio {a['pedido']}: {str(e)[:160]}")
    print(f"Cambios devueltos a BPV: {hechos_c} de {len(pend_c)}")

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
