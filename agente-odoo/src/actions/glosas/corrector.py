"""
Corrector de glosas de facturas de proveedor (XML vs Odoo).

PROBLEMA
  Cuando el XML del DTE no trae código de producto, la importación de Odoo
  (l10n_cl_edi, casilla dte@) busca un producto cuyo nombre CONTENGA el NmbItem.
  Si el proveedor manda un nombre corto o genérico ("Co", "Se", ".", "*",
  "Producto"), Odoo pega cualquier producto, escribe su nombre como glosa y deja
  la línea en la cuenta del producto (210217 Facturas por recibir).
  Caso de origen: FAC 601152 Walmart Serv. Generales (23-oct-2026).

QUÉ CORRIGE (solo si se cumple TODO)
  - Factura de proveedor (in_invoice / in_refund) en BORRADOR, compañía 1,
    que entró por correo (invoice_source_email) y tiene su XML DTE_*.xml.
  - Línea con producto que NO calza por código (CdgItem/VlrCodigo), sin OC,
    sin ficha de proveedor del producto, y cuyo NmbItem está contenido en el
    nombre del producto (la firma del match por nombre parcial).
  - Proveedor sin órdenes de compra confirmadas (servicios).
  - Línea que nadie ha editado (write_uid = OdooBot).
  - La línea calza en monto con su ítem del XML (mismo orden, ±$1).

ACCIÓN
  glosa  <- NmbItem del XML; DscItem si el nombre no dice nada
  producto <- vacío
  cuenta <- según el historial del proveedor en el último año (líneas contabilizadas
            sin producto), en este orden:
            1. la que usó para esa misma glosa (sin números): Walmart separa
               comisión 42410104 de envío 42410201;
            2. si el proveedor usa una sola cuenta, esa (bancos -> 44410190);
            3. si no, NO se cambia: queda en la que puso Odoo (210217 Facturas por
               recibir) y la asigna Camila al contabilizar. Regla de Víctor
               (3-nov-2026): no mezclar proveedores en 42410104.
  Se reescriben cantidad, precio, descuento e impuestos con su valor actual
  para que Odoo no los recalcule al quitar el producto. Se verifica que los
  totales de la factura no cambien y se deja una nota en el chatter.

NUNCA: contabiliza, toca facturas contabilizadas ni líneas editadas por personas.
Validado por Víctor el 3-nov-2026 (hilo 1a169c1e7c088f0d).
"""
from __future__ import annotations

import html
import re
import unicodedata
import xml.etree.ElementTree as ET
import xmlrpc.client
from base64 import b64decode
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Optional

COMPANY_ID = 1
ODOOBOT_UID = 1
NOMBRES_GENERICOS = {"producto", "productos", "servicio", "servicios", "item", "items", "articulo", "articulos"}
DIAS_HISTORIAL = 365
CTX = {"context": {"allowed_company_ids": [COMPANY_ID], "lang": "es_CL"}}


# ── estructuras ──────────────────────────────────────────────────────────────

@dataclass
class ItemXML:
    nro: int
    nombre: str
    descripcion: str
    codigos: list[str]
    monto: float


@dataclass
class LineaPropuesta:
    line_id: int
    nro_xml: int
    glosa_actual: str
    glosa_nueva: str
    producto_id: int
    producto: str
    cuenta_actual_id: int
    cuenta_actual: str
    cuenta_nueva_id: int
    cuenta_nueva: str
    origen_cuenta: str              # "misma glosa" | "única del proveedor" | "sin cambio"
    neto: float
    # valores que se reescriben tal cual para que Odoo no los recalcule
    quantity: float = 0.0
    price_unit: float = 0.0
    discount: float = 0.0
    tax_ids: list[int] = field(default_factory=list)


@dataclass
class FacturaPropuesta:
    move_id: int
    documento: str
    proveedor_id: int
    proveedor: str
    fecha: str
    total_neto: float
    total: float
    lineas: list[LineaPropuesta] = field(default_factory=list)


@dataclass
class Omitida:
    move_id: int
    documento: str
    proveedor: str
    motivo: str


# ── utilidades ───────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", html.unescape(s or "")).encode("ascii", "ignore").decode()
    return s.lower().strip()


def _nombre_pobre(nombre: str) -> bool:
    """True si el NmbItem no sirve como glosa ("Co", ".", "*", "Producto")."""
    util = re.sub(r"[^A-Za-z0-9]", "", _norm(nombre))
    return len(util) <= 3 or _norm(nombre) in NOMBRES_GENERICOS


def glosa_desde_xml(item: ItemXML) -> str:
    nombre = html.unescape(item.nombre or "").strip()
    desc = html.unescape(item.descripcion or "").strip()
    if _nombre_pobre(nombre) and desc:
        return desc
    return nombre or desc


def leer_items_xml(contenido: bytes, folio: str) -> list[ItemXML]:
    """Ítems <Detalle> del documento con ese folio (o del único documento del XML)."""
    raiz = ET.fromstring(contenido)
    docs = [e for e in raiz.iter() if e.tag.rsplit("}", 1)[-1] == "Documento"]
    if not docs:
        raise ValueError("XML sin <Documento>")

    def hijo(e, nombre):
        for h in e:
            if h.tag.rsplit("}", 1)[-1] == nombre:
                return h
        return None

    def texto(e, nombre):
        h = hijo(e, nombre)
        return (h.text or "").strip() if h is not None else ""

    doc = docs[0]
    if len(docs) > 1:
        for d in docs:
            folios = [x.text for x in d.iter() if x.tag.rsplit("}", 1)[-1] == "Folio"]
            if folios and folios[0].strip() == str(folio).strip():
                doc = d
                break
        else:
            raise ValueError(f"XML con {len(docs)} documentos y ninguno con folio {folio}")

    items = []
    for det in (e for e in doc.iter() if e.tag.rsplit("}", 1)[-1] == "Detalle"):
        codigos = [texto(c, "VlrCodigo") for c in det if c.tag.rsplit("}", 1)[-1] == "CdgItem"]
        items.append(ItemXML(
            nro=int(texto(det, "NroLinDet") or 0),
            nombre=texto(det, "NmbItem"),
            descripcion=texto(det, "DscItem"),
            codigos=[c for c in codigos if c],
            monto=float(texto(det, "MontoItem") or 0),
        ))
    return sorted(items, key=lambda i: i.nro)


class _Odoo:
    """Envoltura mínima sobre OdooClient: lectura con reintentos, escritura directa (sin reintento)."""

    def __init__(self, client):
        self.c = client

    def sr(self, model, domain, fields, **kw):
        return self.c.search_read(model, domain, fields, **kw)

    def kw(self, model, method, args, opts=None):
        uid = self.c.authenticate()
        proxy = xmlrpc.client.ServerProxy(f"{self.c.url}/xmlrpc/2/object", allow_none=True)
        return proxy.execute_kw(self.c.db, uid, self.c.password, model, method, args, opts or {})


# ── detección ────────────────────────────────────────────────────────────────

def detectar(client, move_id: Optional[int] = None) -> tuple[list[FacturaPropuesta], list[Omitida]]:
    """Solo lectura. Devuelve las facturas con líneas a corregir y las que se omitieron (con motivo)."""
    o = _Odoo(client)
    dom = [("move_type", "in", ["in_invoice", "in_refund"]), ("state", "=", "draft"),
           ("company_id", "=", COMPANY_ID), ("invoice_source_email", "!=", False)]
    if move_id:
        dom.append(("id", "=", move_id))
    moves = o.sr("account.move", dom, ["name", "partner_id", "commercial_partner_id", "invoice_date",
                                       "l10n_latam_document_number", "amount_untaxed", "amount_total"])
    if not moves:
        return [], []
    ids = [m["id"] for m in moves]
    lineas = o.sr("account.move.line", [("move_id", "in", ids), ("display_type", "=", "product")],
                  ["move_id", "sequence", "name", "product_id", "account_id", "quantity", "price_unit",
                   "discount", "tax_ids", "price_subtotal", "write_uid", "purchase_line_id"])
    por_move: dict[int, list[dict]] = {}
    for l in lineas:
        por_move.setdefault(l["move_id"][0], []).append(l)

    propuestas, omitidas = [], []
    cache_oc, cache_cuenta = {}, {}
    for m in moves:
        ls = sorted(por_move.get(m["id"], []), key=lambda l: (l["sequence"], l["id"]))
        sospechosas = [l for l in ls if l["product_id"]]
        if not sospechosas:
            continue
        prov_id = m["commercial_partner_id"][0]
        prov = m["commercial_partner_id"][1]

        def omitir(motivo):
            omitidas.append(Omitida(m["id"], m["name"], prov, motivo))

        # proveedor de mercadería -> no se toca
        if prov_id not in cache_oc:
            cache_oc[prov_id] = o.kw("purchase.order", "search_count",
                                     [[("partner_id", "child_of", [prov_id]), ("state", "in", ["purchase", "done"])]])
        if cache_oc[prov_id]:
            omitir(f"proveedor con {cache_oc[prov_id]} órdenes de compra (mercadería)")
            continue

        # XML
        att = o.sr("ir.attachment", [("res_model", "=", "account.move"), ("res_id", "=", m["id"]),
                                     ("name", "=like", "DTE_%.xml")], ["name", "datas"])
        if not att:
            omitir("sin XML DTE adjunto")
            continue
        try:
            items = leer_items_xml(b64decode(att[0]["datas"]), m["l10n_latam_document_number"] or "")
        except Exception as e:  # XML ilegible -> no se adivina
            omitir(f"XML ilegible: {e}")
            continue
        if len(items) != len(ls):
            omitir(f"el XML tiene {len(items)} ítems y Odoo {len(ls)} líneas")
            continue
        if any(abs(it.monto - abs(l["price_subtotal"])) > 1 for it, l in zip(items, ls)):
            omitir("los montos de las líneas no calzan con los ítems del XML")
            continue

        prods = {p["id"]: p for p in o.kw("product.product", "read",
                                           [[l["product_id"][0] for l in sospechosas], ["name", "default_code", "product_tmpl_id"]],
                                           {"context": {"active_test": False, "lang": "es_CL"}})}
        fp = None
        for it, l in zip(items, ls):
            if not l["product_id"]:
                continue
            p = prods[l["product_id"][0]]
            if p["default_code"] and p["default_code"] in it.codigos:
                continue                                    # match por código: está bien
            if l["purchase_line_id"]:
                continue                                    # viene de una OC
            if _norm(it.nombre) not in _norm(p["name"]) or not _norm(it.nombre):
                continue                                    # no es la firma del nombre parcial
            if o.kw("product.supplierinfo", "search_count",
                    [[("partner_id", "=", prov_id), ("product_tmpl_id", "=", p["product_tmpl_id"][0])]]):
                continue                                    # el proveedor tiene ficha de ese producto
            if l["write_uid"] and l["write_uid"][0] != ODOOBOT_UID:
                omitir(f"línea {l['id']} editada por {l['write_uid'][1]}: no se toca")
                continue
            if prov_id not in cache_cuenta:
                cache_cuenta[prov_id] = _historial_cuentas(o, prov_id)
            glosa = glosa_desde_xml(it)
            cta, origen = _cuenta_para(cache_cuenta[prov_id], glosa)
            cta_id, cta = cta or tuple(l["account_id"])
            if fp is None:
                fp = FacturaPropuesta(m["id"], m["name"], prov_id, prov, m["invoice_date"] or "",
                                      m["amount_untaxed"], m["amount_total"])
            fp.lineas.append(LineaPropuesta(
                line_id=l["id"], nro_xml=it.nro, glosa_actual=l["name"] or "", glosa_nueva=glosa,
                producto_id=p["id"], producto=p["name"],
                cuenta_actual_id=l["account_id"][0], cuenta_actual=l["account_id"][1],
                cuenta_nueva_id=cta_id, cuenta_nueva=cta, origen_cuenta=origen,
                neto=l["price_subtotal"], quantity=l["quantity"], price_unit=l["price_unit"],
                discount=l["discount"], tax_ids=l["tax_ids"]))
        if fp:
            propuestas.append(fp)
    return propuestas, omitidas


def _clave_glosa(glosa: str) -> str:
    """Glosa sin números ni signos: "Comision del servicio 1000128380720262" -> "comision del servicio"."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", _norm(glosa))).strip()


def _historial_cuentas(o: _Odoo, prov_id: int) -> dict:
    """Cuentas del proveedor en líneas contabilizadas sin producto del último año: por glosa y en total."""
    desde = (date.today() - timedelta(days=DIAS_HISTORIAL)).isoformat()
    ls = o.sr("account.move.line", [("partner_id", "child_of", [prov_id]),
                                    ("move_id.move_type", "in", ["in_invoice", "in_refund"]),
                                    ("parent_state", "=", "posted"), ("display_type", "=", "product"),
                                    ("product_id", "=", False), ("date", ">=", desde)], ["name", "account_id"])
    por_glosa: dict[str, Counter] = {}
    total = Counter()
    for l in ls:
        if not l["account_id"]:
            continue
        cta = tuple(l["account_id"])
        total[cta] += 1
        por_glosa.setdefault(_clave_glosa(l["name"] or ""), Counter())[cta] += 1
    return {"por_glosa": por_glosa, "total": total}


def _cuenta_para(hist: dict, glosa: str) -> tuple[Optional[tuple[int, str]], str]:
    """(cuenta, origen). Sin precedente claro -> (None, "sin cambio"): queda la cuenta actual."""
    c = hist["por_glosa"].get(_clave_glosa(glosa))
    if c:
        return c.most_common(1)[0][0], "misma glosa"
    if len(hist["total"]) == 1:
        return next(iter(hist["total"])), "única del proveedor"
    return None, "sin cambio"


# ── aplicación ───────────────────────────────────────────────────────────────

def aplicar(client, propuestas: list[FacturaPropuesta]) -> list[dict]:
    """ESCRIBE en Odoo. Re-verifica cada factura antes de tocarla. Devuelve el resultado por factura."""
    o = _Odoo(client)
    hoy = date.today().strftime("%d-%m-%Y")
    resultados = []
    for f in propuestas:
        mv = o.kw("account.move", "read", [[f.move_id], ["state", "amount_untaxed", "amount_tax", "amount_total"]])[0]
        if mv["state"] != "draft":
            resultados.append({"move_id": f.move_id, "documento": f.documento, "estado": "omitida: ya no está en borrador"})
            continue
        ids = [l.line_id for l in f.lineas]
        ahora = {l["id"]: l for l in o.kw("account.move.line", "read", [ids, ["product_id", "write_uid", "price_subtotal"]])}
        cambio = [l for l in f.lineas if not ahora.get(l.line_id) or not ahora[l.line_id]["product_id"]
                  or ahora[l.line_id]["product_id"][0] != l.producto_id
                  or (ahora[l.line_id]["write_uid"] and ahora[l.line_id]["write_uid"][0] != ODOOBOT_UID)]
        if cambio:
            resultados.append({"move_id": f.move_id, "documento": f.documento, "estado": "omitida: alguien editó las líneas desde la detección"})
            continue
        for l in f.lineas:
            o.kw("account.move.line", "write", [[l.line_id], {
                "product_id": False, "name": l.glosa_nueva, "account_id": l.cuenta_nueva_id,
                "quantity": l.quantity, "price_unit": l.price_unit, "discount": l.discount,
                "tax_ids": [(6, 0, l.tax_ids)]}], CTX)
        des = o.kw("account.move", "read", [[f.move_id], ["amount_untaxed", "amount_tax", "amount_total"]])[0]
        cuadra = all(abs(des[k] - mv[k]) < 0.5 for k in ("amount_untaxed", "amount_tax", "amount_total"))
        if not cuadra:
            # deshacer: se restituye la línea tal como estaba
            for l in f.lineas:
                o.kw("account.move.line", "write", [[l.line_id], {
                    "product_id": l.producto_id, "name": l.glosa_actual, "account_id": l.cuenta_actual_id,
                    "quantity": l.quantity, "price_unit": l.price_unit, "discount": l.discount,
                    "tax_ids": [(6, 0, l.tax_ids)]}], CTX)
            resultados.append({"move_id": f.move_id, "documento": f.documento,
                               "estado": f"REVERTIDA: los totales cambiaban ({mv['amount_total']} -> {des['amount_total']})"})
            continue
        filas = "".join(
            f"<li>Línea {l.nro_xml}: «{html.escape(l.glosa_actual)}» → «{html.escape(l.glosa_nueva)}». "
            f"Se quitó el producto [{html.escape(l.producto)}]. "
            + (f"Cuenta sin cambio ({html.escape(l.cuenta_actual)}): sin precedente en el historial del proveedor, la asigna contabilidad."
               if l.origen_cuenta == "sin cambio" else
               f"Cuenta {html.escape(l.cuenta_actual)} → {html.escape(l.cuenta_nueva)} ({l.origen_cuenta} en el historial del proveedor).")
            + "</li>"
            for l in f.lineas)
        total = f"{des['amount_total']:,.0f}".replace(",", ".")
        o.kw("account.move", "message_post", [[f.move_id]], {
            "body": (f"<p>Glosa repuesta desde el XML por el agente corrector de glosas el {hoy}. "
                     f"Odoo había pegado un producto por nombre parcial al importar la factura.</p><ul>{filas}</ul>"
                     f"<p>Totales sin cambio: ${total}.</p>"),
            "body_is_html": True,  # por RPC el body str se escapa salvo que se marque como HTML
            "message_type": "comment", "subtype_xmlid": "mail.mt_note"})
        resultados.append({"move_id": f.move_id, "documento": f.documento, "estado": "corregida", "lineas": len(f.lineas)})
    return resultados


def a_dict(propuestas, omitidas) -> dict:
    return {"propuestas": [asdict(p) for p in propuestas], "omitidas": [asdict(x) for x in omitidas]}
