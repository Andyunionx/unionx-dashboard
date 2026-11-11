# -*- coding: utf-8 -*-
"""Agente Factura ML: ventas de Mercado Libre en que el comprador pidió FACTURA.

El conector emite boleta siempre. Para esas ventas, este agente hace lo que Facturación hace a
mano (Yohana, 10-nov-2026, hilo «Pulso diario - Facturas por emitir en Mercado Libre»):
«Revertir y crear factura» sobre la boleta. Así quedan los 3 documentos relacionados:
  BEL (39) ─► N/C (61, código SII 1 = anula, conciliada con la boleta)
          └─► FAC (33) al RUT de la empresa, ligada al mismo pedido (copia de la boleta).
El costo de venta se reversa en la NC y se vuelve a cargar en la factura: el neto no cambia.
El envío al SII lo hace el cron 26 estándar. La subida de la factura a Mercado Libre NO es
de este agente (es del conector MELI Directo, flag «Subir boleta a MELI»).

Gatillo: el pulso diario de Maite (notificaciones@unionx.cl, 09:00 días hábiles), que lista
solo las ventas con todos los datos (razón social, RUT, giro, dirección). Cruce con la nota
que deja el conector en el pedido («El comprador pidió FACTURA en MELI — RUT …»).

Regla de cliente (Andrés, 10-nov): por RUT, la ficha con giro y categoría IVA 1 (primero
empresas sin padre); si no hay ninguna, se crea una nueva con los datos del comprador.
Correo DTE desconocido → dte@grupoeter.cl (convención de Facturación en Odoo).

Se salta (y se informa) si: pedido no encontrado/ambiguo/cancelado, RUT distinto al de la
nota del conector, monto distinto, boleta no aceptada por el SII, boleta con NC o con pago
conciliado, o el pedido ya tiene factura 33.

Respuesta a Maite (Andrés, 11-nov): al terminar, el agente responde en el hilo de cada pulso con lo
que emitió y con lo que no pudo emitir por un motivo que pide revisión (la boleta aún no aceptada
por el SII no se informa: se reintenta en la corrida siguiente). Cada factura se informa una sola
vez: antes de responder lee el hilo y omite lo que ya mencionó. Solo en PROD con --ejecutar; los
pulsos anteriores al 11-nov se respondieron a mano.

Uso: python agente_factura_ml.py --test|--prod [--ejecutar] [--solo VENTA,VENTA|S123,…] [--max N] [--dias N]
                                 [--sin-respuesta]
  sin --ejecutar = plan (solo lectura; muestra la respuesta a Maite sin enviarla).
"""
import sys, os, re, json, html, base64, datetime, unicodedata
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import getaddresses
from pathlib import Path
import requests
sys.stdout.reconfigure(encoding="utf-8")

TAG = "[AGENTE-FACTURA-ML]"
MAX_POR_CORRIDA = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 10
DIAS = int(sys.argv[sys.argv.index("--dias") + 1]) if "--dias" in sys.argv else 7
SOLO = set(sys.argv[sys.argv.index("--solo") + 1].split(",")) if "--solo" in sys.argv else None
LIVE = "--ejecutar" in sys.argv
RESPONDER = "--sin-respuesta" not in sys.argv
RESPONDER_DESDE = "2026-11-11"
TRANSITORIO = "aún no aceptada por el SII"
DTE_EMAIL_DEFAULT = "dte@grupoeter.cl"
RAZON_NC = "Reemision como factura: el cliente la pidio en Mercado Libre"
REMITENTE, ASUNTO = "notificaciones@unionx.cl", "Facturas por emitir en Mercado Libre"
ROOT = Path(os.environ.get("UNIONX_ROOT", Path(__file__).parent))

# ── Odoo ─────────────────────────────────────────────────────────────────────
if "--test" in sys.argv:
    URL, DB = "https://test3-melollevo.odoo.com", "unionxb2b-sta3-40414386"
    USER = "andres@grupoeter.cl"
    AMB = "TEST"
elif "--prod" in sys.argv:
    cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
    URL, DB, USER = cfg["url"], cfg["db_name"], cfg["username"]
    AMB = "PROD"
else:
    raise SystemExit("indicar --test o --prod")
PW = os.environ.get("ANDRES_ODOO_PASSWORD", "")
if not PW and (ROOT / "odoo/.odoo_pass").exists():
    PW = (ROOT / "odoo/.odoo_pass").read_text().strip()


def jrpc(service, method, args):
    j = requests.post(URL + "/jsonrpc", json={"jsonrpc": "2.0", "method": "call",
                      "params": {"service": service, "method": method, "args": args}, "id": 1}, timeout=300).json()
    if "error" in j:
        raise Exception(str(j["error"].get("data", {}).get("message") or j["error"])[:500])
    return j.get("result")


UID = jrpc("common", "login", [DB, USER, PW])


def ex(model, method, *a, **k):
    return jrpc("object", "execute_kw", [DB, UID, PW, model, method, list(a), k])


HOY = str(datetime.date.today())
DOC = {d["code"]: d["id"] for d in ex("l10n_latam.document.type", "search_read",
                                      [("code", "in", ["33", "39", "61"]), ("country_id.code", "=", "CL")], fields=["code"])}
RUT_TYPE = ex("l10n_latam.identification.type", "search", [("name", "=", "RUT"), ("country_id.code", "=", "CL")])[0]
CHILE = ex("res.country", "search", [("code", "=", "CL")])[0]


# ── Utilidades ───────────────────────────────────────────────────────────────
def sin_tilde(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn").lower().strip()


def rut_digitos(r):
    return re.sub(r"[^0-9K]", "", str(r or "").upper())


def rut_valido(r):
    d = rut_digitos(r)
    if len(d) < 2 or not d[:-1].isdigit():
        return False
    s, m = 0, 2
    for c in reversed(d[:-1]):
        s += int(c) * m
        m = 2 if m == 7 else m + 1
    dv = 11 - s % 11
    return d[-1] == {10: "K", 11: "0"}.get(dv, str(dv))


def rut_odoo(r):
    d = rut_digitos(r)
    return f"{int(d[:-1])}-{d[-1]}"


def rut_variantes(r):
    d = rut_digitos(r)
    cuerpo = f"{int(d[:-1]):,}".replace(",", ".")
    return [rut_odoo(r), f"{cuerpo}-{d[-1]}", d, "CL" + d]


def monto(s):
    return float(re.sub(r"[^0-9]", "", str(s or "")) or 0)


# ── 1. Pulso de Maite (Gmail) ────────────────────────────────────────────────
def gmail():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = os.environ.get("GMAIL_TOKEN_JSON")
    creds = (Credentials.from_authorized_user_info(json.loads(tok)) if tok
             else Credentials.from_authorized_user_file(str(ROOT / "agente-comex/config/token.json")))
    if not creds.valid:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _html_de(payload):
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        cs = "utf-8"
        for h in payload.get("headers", []):
            if h["name"].lower() == "content-type":
                m = re.search(r'charset="?([\w-]+)', h["value"], re.I)
                cs = m.group(1) if m else cs
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(cs, errors="replace")
    for p in payload.get("parts", []) or []:
        r = _html_de(p)
        if r:
            return r
    return None


def parsear_pulso(h):
    """Bloques «Venta <id>» con su tabla etiqueta → valor."""
    ventas = {}
    partes = re.split(r">\s*Venta\s+(\d{10,})\s*<", h)
    for i in range(1, len(partes) - 1, 2):
        vid, blk = partes[i], partes[i + 1]
        filas = re.findall(r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>", blk, re.S)
        d = {sin_tilde(html.unescape(re.sub("<[^>]+>", "", k))): html.unescape(re.sub("<[^>]+>", "", v)).strip()
             for k, v in filas}
        cuenta = re.search(r">\s*(Cuenta\s+\d)", blk)
        ventas[vid] = {"venta": vid, "cuenta": cuenta.group(1) if cuenta else "",
                       "razon": d.get("razon social", ""), "rut": d.get("rut", ""), "giro": d.get("giro", ""),
                       "direccion": d.get("direccion", ""), "productos": d.get("productos", ""),
                       "total": monto(d.get("total"))}
    return ventas


def leer_pulsos(g):
    q = f'from:{REMITENTE} subject:("{ASUNTO}") newer_than:{DIAS}d'
    msgs = g.users().messages().list(userId="me", q=q, maxResults=30).execute().get("messages", [])
    ventas, pulsos = {}, {}
    for m in reversed(msgs):   # del más antiguo al más reciente: el último pulso manda
        full = g.users().messages().get(userId="me", id=m["id"], format="full").execute()
        hd = {x["name"].lower(): x["value"] for x in full["payload"].get("headers", [])}
        pulsos[m["id"]] = {"thread": full["threadId"], "ms": int(full["internalDate"]), "message_id": hd.get("message-id", ""),
                           "subject": hd.get("subject", ""), "from": hd.get("from", ""), "to": hd.get("to", ""),
                           "cc": hd.get("cc", "")}
        h = _html_de(full["payload"]) or ""
        for vid, v in parsear_pulso(h).items():
            v["mail_id"] = m["id"]
            ventas[vid] = v
    print(f"pulsos leídos: {len(msgs)} (últimos {DIAS} días) · ventas: {len(ventas)}")
    return ventas, pulsos


def _texto_de(payload):
    """Texto de un mensaje: text/plain o, si no hay, el html sin etiquetas."""
    def buscar(p, tipo):
        if p.get("mimeType") == tipo and p.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", errors="replace")
        for q in p.get("parts", []) or []:
            r = buscar(q, tipo)
            if r:
                return r
        return ""
    return buscar(payload, "text/plain") or html.unescape(re.sub("<[^>]+>", " ", buscar(payload, "text/html")))


def pesos(n):
    return "$" + f"{n:,.0f}".replace(",", ".")


# ── 2. Odoo: pedido, boleta, cliente ─────────────────────────────────────────
def comuna_id(nombre):
    n = sin_tilde(nombre)
    if not n:
        return False
    for s in ex("res.country.state", "search_read", [("country_id", "=", CHILE), ("name", "ilike", nombre.split()[0])],
                fields=["name"]):
        if sin_tilde(s["name"].split(" (")[0]) == n:
            return s["id"]
    return False


def partir_direccion(dirc):
    p = [x.strip() for x in str(dirc or "").split(",") if x.strip()]
    if len(p) < 3:
        return None
    return {"street": ", ".join(p[:-2]), "comuna": p[-2], "region": p[-1]}


def nota_conector(so_id):
    ms = ex("mail.message", "search_read", [("model", "=", "sale.order"), ("res_id", "=", so_id),
                                            ("body", "ilike", "pidió FACTURA")], fields=["body"], limit=1)
    if not ms:
        return None
    m = re.search(r"RUT\s+([0-9Kk.\-]+)", re.sub("<[^>]+>", " ", ms[0]["body"]))
    return rut_digitos(m.group(1)) if m else ""


def elegir_partner(v):
    """Regla Andrés 10-nov: ficha con giro + categoría IVA 1; si no hay, crear."""
    F = ["name", "vat", "is_company", "parent_id", "customer_rank", "l10n_cl_sii_taxpayer_type",
         "l10n_cl_activity_description", "l10n_cl_dte_email", "street", "city", "state_id", "country_id"]
    cands = ex("res.partner", "search_read", [("vat", "in", rut_variantes(v["rut"]))], fields=F)
    ok = [p for p in cands if p["l10n_cl_sii_taxpayer_type"] == "1" and (p["l10n_cl_activity_description"] or "").strip()]
    ok.sort(key=lambda p: (not p["is_company"], bool(p["parent_id"]), -(p["customer_rank"] or 0), p["id"]))
    # Odoo no deja crear una 2ª empresa con el mismo RUT (regla «un RUT = una empresa»): si la
    # empresa existe pero no califica (p. ej. categoría IVA 3), se usa esa y se completa.
    emp = sorted([p for p in cands if p["is_company"] and not p["parent_id"]], key=lambda p: p["id"])
    d = partir_direccion(v["direccion"])
    if ok or emp:
        p = ok[0] if ok else emp[0]
        completar = {}
        if p["l10n_cl_sii_taxpayer_type"] != "1":
            completar["l10n_cl_sii_taxpayer_type"] = "1"
        if not (p["l10n_cl_activity_description"] or "").strip():
            completar["l10n_cl_activity_description"] = v["giro"].strip()
        if not p["l10n_cl_dte_email"]:
            completar["l10n_cl_dte_email"] = DTE_EMAIL_DEFAULT
        if not (p["street"] or "").strip() or not (p["city"] or "").strip():
            completar.update({"street": d["street"], "city": d["comuna"]})
            if not p["state_id"] and comuna_id(d["comuna"]):
                completar["state_id"] = comuna_id(d["comuna"])
        if not p["country_id"]:
            completar["country_id"] = CHILE
        return {"accion": "usar", "id": p["id"], "nombre": p["name"], "completar": completar,
                "descartadas": len(cands) - 1}
    vals = {"name": v["razon"].strip(), "vat": rut_odoo(v["rut"]), "is_company": True,
            "l10n_latam_identification_type_id": RUT_TYPE, "l10n_cl_sii_taxpayer_type": "1",
            "l10n_cl_activity_description": v["giro"].strip(), "l10n_cl_dte_email": DTE_EMAIL_DEFAULT,
            "street": d["street"], "city": d["comuna"], "state_id": comuna_id(d["comuna"]), "country_id": CHILE,
            "customer_rank": 1}
    return {"accion": "crear", "vals": vals, "nombre": vals["name"], "descartadas": len(cands)}


def evaluar(v):
    """Devuelve (estado, detalle, ctx). estado: EMITIR / YA_FACTURADA / SALTAR."""
    if not rut_valido(v["rut"]):
        return "SALTAR", f"RUT inválido {v['rut']}", None
    if not partir_direccion(v["direccion"]):
        return "SALTAR", f"dirección incompleta «{v['direccion']}»", None
    sos = ex("sale.order", "search_read", ["|", ("channel_order_reference", "=", v["venta"]), ("yuju_pack_id", "=", v["venta"])],
             fields=["name", "state", "invoice_ids", "amount_total"])
    if SOLO and not ({v["venta"]} | {s["name"] for s in sos}) & SOLO:
        return None, None, None
    if len(sos) != 1:
        return "SALTAR", f"{'pedido no encontrado' if not sos else f'{len(sos)} pedidos para la venta (pack)'}", None
    so = sos[0]
    ctx = {"so": so}
    if so["state"] == "cancel":
        return "SALTAR", f"{so['name']} cancelado", ctx
    rut_nota = nota_conector(so["id"])
    if rut_nota is not None and rut_nota != rut_digitos(v["rut"]):
        return "SALTAR", f"{so['name']}: RUT del pulso {v['rut']} ≠ nota del conector {rut_nota}", ctx
    movs = ex("account.move", "read", so["invoice_ids"], fields=[
        "name", "state", "move_type", "l10n_latam_document_type_id", "amount_total", "payment_state",
        "l10n_cl_dte_status", "journal_id", "reversal_move_ids", "partner_id", "ref", "create_date",
        "reversed_entry_id"]) if so["invoice_ids"] else []
    fac = [m for m in movs if m["move_type"] == "out_invoice" and m["state"] == "posted"
           and m["l10n_latam_document_type_id"] and m["l10n_latam_document_type_id"][0] == DOC["33"]]
    if fac:
        ctx.update(fac=fac[-1], movs=movs)
        return "YA_FACTURADA", f"{so['name']}: {', '.join(m['name'] for m in fac)}", ctx
    bols = [m for m in movs if m["move_type"] == "out_invoice" and m["state"] == "posted"
            and m["l10n_latam_document_type_id"] and m["l10n_latam_document_type_id"][0] == DOC["39"]]
    if len(bols) != 1:
        return "SALTAR", f"{so['name']}: {len(bols)} boletas posteadas", ctx
    b = bols[0]
    ctx["bol"] = b
    ncs = ex("account.move", "search_read", [("reversed_entry_id", "=", b["id"]), ("state", "!=", "cancel")],
             fields=["name", "state", "ref"])
    nc_propia = [n for n in ncs if n["state"] == "posted" and TAG in str(n["ref"] or "")]
    borrador = [m for m in movs if m["move_type"] == "out_invoice" and m["state"] == "draft"]
    if nc_propia and len(borrador) == 1:     # corrida anterior cortada entre la NC y la factura
        ctx.update(nc=nc_propia[0], borrador=borrador[0])
        return "EMITIR", f"{so['name']}: retomar factura (NC {nc_propia[0]['name']} ya emitida)", ctx
    if ncs or b["payment_state"] == "reversed":
        return "SALTAR", f"{b['name']} ya tiene NC ({', '.join(str(n['name']) for n in ncs)})", ctx
    if b["payment_state"] not in ("not_paid",):
        return "SALTAR", f"{b['name']} con pago conciliado ({b['payment_state']}): revisar a mano", ctx
    if b["l10n_cl_dte_status"] != "accepted" and AMB != "TEST":   # en test3 el envío al SII está apagado
        return "SALTAR", f"{b['name']} aún no aceptada por el SII ({b['l10n_cl_dte_status']})", ctx
    if abs(b["amount_total"] - v["total"]) > 1:
        return "SALTAR", f"{b['name']} ${b['amount_total']:,.0f} ≠ total del pulso ${v['total']:,.0f}", ctx
    return "EMITIR", f"{so['name']} {b['name']} ${b['amount_total']:,.0f}", ctx


def cogs(move_id):
    ls = ex("account.move.line", "search_read", [("move_id", "=", move_id), ("display_type", "=", "cogs"),
                                                 ("account_id.code", "=like", "4141%")], fields=["balance"])
    return round(sum(l["balance"] for l in ls))


def emitir(v, ctx, part):
    b, so = ctx["bol"], ctx["so"]
    if part["accion"] == "crear":
        pid = ex("res.partner", "create", part["vals"])
    else:
        pid = part["id"]
        if part["completar"]:
            ex("res.partner", "write", [pid], part["completar"])
    if "nc" in ctx:                     # retomar
        nc, fid = ctx["nc"], ctx["borrador"]["id"]
    else:
        c = {"active_model": "account.move", "active_ids": [b["id"]]}
        wid = ex("account.move.reversal", "create", {
            "move_ids": [(6, 0, [b["id"]])], "date": HOY, "reason": RAZON_NC,
            "journal_id": b["journal_id"][0], "l10n_cl_edi_reference_doc_code": "1"}, context=c)
        act = ex("account.move.reversal", "modify_moves", [wid], context=c)
        fid = act["res_id"]
        nc = ex("account.move", "search_read", [("reversed_entry_id", "=", b["id"]), ("state", "=", "posted")],
                fields=["name", "ref"])[0]
        ex("account.move", "write", [nc["id"]], {"ref": f"{nc['ref'] or ''} {TAG}".strip()})
    ex("account.move", "write", [fid], {"partner_id": pid, "l10n_latam_document_type_id": DOC["33"],
                                        "invoice_date": HOY, "ref": f"Venta ML {v['venta']} {TAG}"})
    ex("account.move", "action_post", [fid])
    f = ex("account.move", "read", [fid], fields=["name", "state", "amount_total", "l10n_cl_dte_status"])[0]
    nc = ex("account.move", "read", [nc["id"]], fields=["name", "state", "amount_total"])[0]
    b2 = ex("account.move", "read", [b["id"]], fields=["payment_state"])[0]
    c_b, c_nc, c_f = cogs(b["id"]), cogs(nc["id"]), cogs(fid)
    # El costo de la factura es el promedio (AVCO) de hoy y el de la boleta el de su fecha: pueden
    # diferir unos pesos (S312755: 23.720 vs 23.722). Lo que se vigila es que la factura traiga costo.
    ok = (f["state"] == "posted" and nc["state"] == "posted" and b2["payment_state"] == "reversed"
          and abs(f["amount_total"] - b["amount_total"]) <= 1 and c_nc == -c_b
          and abs(c_f - c_b) <= max(100, 0.05 * abs(c_b)))
    return {"pedido": so["name"], "boleta": b["name"], "nc": nc["name"], "factura": f["name"], "cliente": part["nombre"],
            "cliente_id": pid, "total": f["amount_total"], "costo": {"bol": c_b, "nc": c_nc, "fac": c_f},
            "boleta_estado": b2["payment_state"], "ok": ok}


# ── 3. Respuesta a Maite ─────────────────────────────────────────────────────
def informe(ventas, resultados, hechos):
    """Qué contar por pulso: facturas emitidas por el agente y ventas saltadas que piden revisión."""
    ahora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    por_venta = {h["venta"]: h for h in hechos}
    inf = []
    for vid, (est, det, ctx) in resultados.items():
        v, ctx = ventas[vid], ctx or {}
        if vid in por_venta:
            h = por_venta[vid]
            inf.append({"mail_id": v["mail_id"], "tipo": "emitida", "clave": h["factura"], "creada": ahora,
                        "linea": f"Venta {vid} · {h['pedido']} · {h['cliente']} · {h['boleta']} anulada con {h['nc']} · "
                                 f"{h['factura']} · {pesos(h['total'])}"})
        elif est == "YA_FACTURADA" and TAG in str(ctx["fac"]["ref"] or ""):
            f, movs = ctx["fac"], ctx["movs"]

            def nc_de(doc_id):
                return next((m for m in movs if m["move_type"] == "out_refund" and m["state"] == "posted"
                             and m["reversed_entry_id"] and m["reversed_entry_id"][0] == doc_id), None)
            b = next((m for m in movs if m["move_type"] == "out_invoice" and m["state"] == "posted"
                      and m["l10n_latam_document_type_id"] and m["l10n_latam_document_type_id"][0] == DOC["39"]), None)
            nc, anul = (nc_de(b["id"]) if b else None), nc_de(f["id"])
            linea = (f"Venta {vid} · {ctx['so']['name']} · {f['partner_id'][1]} · {b['name'] if b else 'boleta'} anulada con "
                     f"{nc['name'] if nc else 'N/C'} · {f['name']} · {pesos(f['amount_total'])}")
            if anul:   # p. ej. S314002: Facturación anuló la factura porque el cliente canceló
                motivo = str(anul["ref"] or "").split(",", 1)[-1].strip(" .")
                linea += f" · después anulada con {anul['name']}" + (f" ({motivo})" if motivo else "")
            inf.append({"mail_id": v["mail_id"], "tipo": "emitida", "clave": f["name"], "creada": f["create_date"], "linea": linea})
        elif est == "SALTAR" and TRANSITORIO not in det:
            inf.append({"mail_id": v["mail_id"], "tipo": "revisar", "clave": f"Venta {vid}", "creada": "9999",
                        "linea": f"Venta {vid} · {v['razon']} · {det}"})
    return inf


def responder(g, pulsos, inf):
    """Responde en el hilo de cada pulso (desde RESPONDER_DESDE) lo que aún no se informó en ese hilo."""
    yo = g.users().getProfile(userId="me").execute()["emailAddress"].lower()
    enviados = []
    for mid, p in pulsos.items():
        f_pulso = datetime.datetime.fromtimestamp(p["ms"] / 1000, datetime.timezone.utc)
        if f_pulso.date().isoformat() < RESPONDER_DESDE:
            continue
        # Solo lo emitido después de este pulso (una venta repetida en el pulso siguiente no se vuelve a informar).
        items = [x for x in inf if x["mail_id"] == mid and x["creada"] > f_pulso.strftime("%Y-%m-%d %H:%M:%S")]
        if not items:
            continue
        th = g.users().threads().get(userId="me", id=p["thread"], format="full").execute()
        previo = "\n".join(_texto_de(m["payload"]) for m in th.get("messages", [])
                           if yo in next((h["value"] for h in m["payload"].get("headers", []) if h["name"].lower() == "from"), "").lower())
        nuevos = [x for x in items if not re.search(rf"\b{re.escape(x['clave'])}\b", previo)]
        if not nuevos:
            continue
        emit = [x for x in nuevos if x["tipo"] == "emitida"]
        rev = [x for x in nuevos if x["tipo"] == "revisar"]
        par = ["Hola Maite,"]
        if emit:
            par += [f"El agente emitió la factura de {len(emit)} venta{'s' if len(emit) > 1 else ''} de este pulso "
                    "(N/C a la boleta + factura 33 al RUT del comprador):", "\n".join("- " + x["linea"] for x in emit)]
        if rev:
            par += [f"{'Estas no las emitió' if len(rev) > 1 else 'Esta no la emitió'}; quedan para revisión de Facturación:",
                    "\n".join("- " + x["linea"] for x in rev)]
        if emit:
            par.append("El envío al SII lo hace Odoo durante el día.")
        de = p["from"]
        cc = [a for _, a in getaddresses([p["to"], p["cc"]]) if a and a.lower() != yo and a.lower() not in de.lower()]
        asunto = p["subject"] if p["subject"].lower().startswith("re:") else "Re: " + p["subject"]
        txt = "\n\n".join(par) + "\n\nBest Regards / Saludos,\n"
        if not (LIVE and AMB == "PROD" and RESPONDER):
            print(f"  RESPUESTA (no enviada: {'plan' if not LIVE else AMB if AMB != 'PROD' else '--sin-respuesta'}) "
                  f"a {de} cc {', '.join(cc)} · {asunto}\n" + "\n".join("    " + l for l in txt.splitlines()))
            continue
        try:
            firma = g.users().settings().sendAs().get(userId="me", sendAsEmail=yo).execute().get("signature", "")
        except Exception:
            firma = ""

        def p2h(t):
            ls = t.split("\n")
            if all(l.startswith("- ") for l in ls):
                return "<ul>" + "".join(f"<li>{html.escape(l[2:])}</li>" for l in ls) + "</ul>"
            return "<p>" + "<br>".join(html.escape(l) for l in ls) + "</p>"
        msg = MIMEMultipart("alternative")
        msg["To"], msg["Subject"] = de, asunto
        if cc:
            msg["Cc"] = ", ".join(cc)
        if p["message_id"]:
            msg["In-Reply-To"] = msg["References"] = p["message_id"]
        msg.attach(MIMEText(txt, "plain", "utf-8"))
        msg.attach(MIMEText("".join(p2h(t) for t in par) + (f"<div>{firma}</div>" if firma else "<p>Best Regards / Saludos,</p>"),
                            "html", "utf-8"))
        r = g.users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode(),
                                                         "threadId": p["thread"]}).execute()
        enviados.append({"pulso": mid, "respuesta": r["id"], "emitidas": len(emit), "revisar": len(rev)})
        print(f"  ✉ respuesta a Maite en el hilo del pulso {mid}: {len(emit)} emitidas · {len(rev)} para revisar (msg {r['id']})")
    return enviados


# ── 4. Corrida ───────────────────────────────────────────────────────────────
def main():
    print(f"[{HOY}] ambiente={AMB} modo={'EJECUTAR' if LIVE else 'PLAN'} máx={MAX_POR_CORRIDA}")
    g = gmail()
    ventas, pulsos = leer_pulsos(g)
    plan, hechos, errores, resultados = [], [], [], {}
    for vid, v in ventas.items():
        est, det, ctx = evaluar(v)
        if est is None:
            continue
        resultados[vid] = (est, det, ctx)
        part = elegir_partner(v) if est == "EMITIR" else None
        plan.append({"venta": vid, "estado": est, "detalle": det, "rut": v["rut"], "razon": v["razon"],
                     "cliente": part and (f"{part['accion']} «{part['nombre']}»"
                                          + (f" completar {list(part['completar'])}" if part.get("completar") else ""))})
        print(f"  {est:12} venta {vid} · {v['razon'][:40]:40} · {det}"
              + (f" · cliente: {plan[-1]['cliente']}" if part else ""))
        if est == "EMITIR" and LIVE:
            if len(hechos) + len(errores) >= MAX_POR_CORRIDA:
                print("    tope de la corrida: queda para la siguiente")
                continue
            if AMB == "TEST" and ctx["bol"]["l10n_cl_dte_status"] != "accepted":
                ex("account.move", "write", [ctx["bol"]["id"]], {"l10n_cl_dte_status": "accepted"})
            try:
                r = emitir(v, ctx, part)
                hechos.append({"venta": vid, **r})
                print(f"    {'✓' if r['ok'] else '⚠ REVISAR'} {r['boleta']} → {r['nc']} + {r['factura']} "
                      f"({r['cliente']}) ${r['total']:,.0f} · costo {r['costo']}")
            except Exception as e:
                errores.append({"venta": vid, "error": str(e)[:400]})
                print(f"    ✗ ERROR: {str(e)[:300]}")
    out = {"fecha": HOY, "ambiente": AMB, "live": LIVE, "plan": plan, "hechos": hechos, "errores": errores}
    fallo_respuesta = None
    try:
        out["respuestas"] = responder(g, pulsos, informe(ventas, resultados, hechos))
    except Exception as e:   # lo emitido ya quedó; la próxima corrida vuelve a intentar la respuesta
        fallo_respuesta = str(e)[:400]
        out["error_respuesta"] = fallo_respuesta
        print(f"  ✗ ERROR al responder a Maite: {fallo_respuesta}")
    nombre = f"factura_ml_{AMB.lower()}_{datetime.datetime.now():%Y%m%d_%H%M}.json"
    Path(os.environ.get("FACTURA_ML_OUT", ".")).joinpath(nombre).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"emitir: {sum(p['estado'] == 'EMITIR' for p in plan)} · hechas: {len(hechos)} · errores: {len(errores)} → {nombre}")
    if fallo_respuesta:
        raise SystemExit(1)   # corrida en rojo en GitHub: que se vea
    return out


if __name__ == "__main__":
    main()
