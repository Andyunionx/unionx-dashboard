"""
Opcion B — Crea borradores en Odoo desde datos DTE del SII.
"""
from __future__ import annotations
import xmlrpc.client as xc
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

NS = {"dte": "http://www.sii.cl/SiiDte"}
TIPO_DOC_MOVE_TYPE = {"33": "in_invoice", "34": "in_invoice", "61": "in_refund"}
_CACHE_DOC_TYPE: dict[str, int] = {}


@dataclass
class ResultadoImportOdoo:
    ok: bool
    move_id: Optional[int] = None
    ref: Optional[str] = None
    partner_nombre: Optional[str] = None
    error: Optional[str] = None


def _get_models(client):
    uid = client.authenticate()
    models = xc.ServerProxy(f"{client.url}/xmlrpc/2/object", allow_none=True)
    return models, uid, client.db, client.password


def _get_doc_type_id(models, uid, db, pwd, tipo_doc: str) -> Optional[int]:
    if tipo_doc in _CACHE_DOC_TYPE:
        return _CACHE_DOC_TYPE[tipo_doc]
    res = models.execute_kw(db, uid, pwd, "l10n_latam.document.type", "search_read",
        [[["code", "=", tipo_doc], ["country_id.code", "=", "CL"]]],
        {"fields": ["id"], "limit": 1})
    if res:
        _CACHE_DOC_TYPE[tipo_doc] = res[0]["id"]
        return res[0]["id"]
    return None


def _get_partner_id(models, uid, db, pwd, rut: str, nombre: str) -> Optional[int]:
    rut_norm = rut.replace(".", "").upper()
    if "-" not in rut_norm and len(rut_norm) > 1:
        rut_norm = rut_norm[:-1] + "-" + rut_norm[-1]
    res = models.execute_kw(db, uid, pwd, "res.partner", "search_read",
        [[["vat", "=", rut_norm], ["active", "in", [True, False]]]],
        {"fields": ["id"], "limit": 1})
    if res:
        return res[0]["id"]
    return models.execute_kw(db, uid, pwd, "res.partner", "create",
        [{"name": nombre, "vat": rut_norm, "country_id": 46,
          "l10n_cl_taxpayer_type": "1", "company_type": "company"}], {})


def _get_default_account(models, uid, db, pwd) -> Optional[int]:
    res = models.execute_kw(db, uid, pwd, "account.account", "search_read",
        [[["code", "=", "42410104"]]], {"fields": ["id"], "limit": 1})
    return res[0]["id"] if res else None


def _get_tax_iva(models, uid, db, pwd) -> Optional[int]:
    res = models.execute_kw(db, uid, pwd, "account.tax", "search_read",
        [[["type_tax_use", "=", "purchase"], ["amount", "=", 19.0],
          ["active", "in", [True, False]]]],
        {"fields": ["id"], "limit": 1})
    return res[0]["id"] if res else None


def _parsear_xml_dte(xml_bytes: bytes) -> dict:
    try:
        root = ET.fromstring(xml_bytes)
        def find(tag):
            for pfx in ["", "dte:"]:
                el = root.find(f".//{pfx}{tag}", NS if pfx else {})
                if el is not None and el.text:
                    return el.text.strip()
            return ""
        lineas = []
        for det in root.iter("Detalle"):
            nombre = ""
            for t in ["NmbItem", "DscItem"]:
                el = det.find(t) or det.find(f"dte:{t}", NS)
                if el is not None and el.text:
                    nombre = el.text.strip(); break
            qty_el = det.find("QtyItem") or det.find("dte:QtyItem", NS)
            price_el = det.find("PrcItem") or det.find("dte:PrcItem", NS)
            qty = float(qty_el.text or "1") if qty_el is not None else 1.0
            price = float(price_el.text or "0") if price_el is not None else 0.0
            if nombre or price:
                lineas.append({"nombre": nombre, "cantidad": qty, "precio": price})
        return {
            "tipo_doc": find("TipoDTE"), "folio": find("Folio"),
            "fecha": find("FchEmis"), "rut_emisor": find("RUTEmisor"),
            "razon_emisor": find("RznSoc"),
            "monto_neto": float(find("MntNeto") or "0"),
            "monto_iva":  float(find("IVA") or "0"),
            "monto_total": float(find("MntTotal") or "0"),
            "lineas": lineas,
        }
    except Exception as e:
        return {"error": str(e)}


def importar_dte_a_odoo(client, dte, dry_run: bool = False) -> ResultadoImportOdoo:
    if dte.xml_bytes:
        datos = _parsear_xml_dte(dte.xml_bytes)
        if "error" in datos:
            return ResultadoImportOdoo(ok=False, error=f"XML: {datos['error']}")
        tipo_doc = datos.get("tipo_doc") or dte.tipo_doc
        folio    = datos.get("folio") or dte.folio
        fecha    = datos.get("fecha") or dte.fecha_emision
        rut_e    = datos.get("rut_emisor") or dte.rut_emisor
        razon    = datos.get("razon_emisor") or dte.razon_social
        monto_neto = datos.get("monto_neto") or dte.monto_neto
        lineas_dte = datos.get("lineas", [])
    else:
        tipo_doc = dte.tipo_doc; folio = dte.folio; fecha = dte.fecha_emision
        rut_e = dte.rut_emisor; razon = dte.razon_social
        monto_neto = dte.monto_neto; lineas_dte = []

    move_type = TIPO_DOC_MOVE_TYPE.get(tipo_doc, "in_invoice")

    if dry_run:
        return ResultadoImportOdoo(ok=True, ref=f"DRY RUN {tipo_doc}/{folio}",
                                   partner_nombre=razon)

    models, uid, db, pwd = _get_models(client)

    # Anti-duplicado: comparar folios del partner normalizados (sin ceros izq)
    def _nf(s):
        digits = "".join(ch for ch in str(s or "") if ch.isdigit())
        return str(int(digits)) if digits else ""

    rut_body = rut_e.replace(".", "").replace("-", "").strip().upper()
    rut_body = rut_body[:-1] if len(rut_body) > 1 else rut_body
    del_partner = models.execute_kw(db, uid, pwd, "account.move", "search_read",
        [[["move_type", "in", ["in_invoice", "in_refund"]],
          ["partner_id.vat", "ilike", rut_body]]],
        {"fields": ["name", "ref", "l10n_latam_document_number"], "limit": 300})
    folio_n = _nf(folio)
    for ex in del_partner:
        candidatos = [ex.get("l10n_latam_document_number")]
        ref = str(ex.get("ref") or "")
        if ref.split():
            candidatos.append(ref.split()[-1])
        if folio_n and folio_n in {_nf(c) for c in candidatos}:
            return ResultadoImportOdoo(ok=False, error=f"Ya existe: {ex['name']}")

    partner_id  = _get_partner_id(models, uid, db, pwd, rut_e, razon)
    doc_type_id = _get_doc_type_id(models, uid, db, pwd, tipo_doc)
    account_id  = _get_default_account(models, uid, db, pwd)
    tax_id      = _get_tax_iva(models, uid, db, pwd)

    if not partner_id:
        return ResultadoImportOdoo(ok=False, error=f"No partner RUT {rut_e}")

    if lineas_dte:
        lines = [(0, 0, {"name": l["nombre"] or f"Linea {i+1}",
                          "quantity": l["cantidad"], "price_unit": l["precio"],
                          "account_id": account_id,
                          **({"tax_ids": [(6, 0, [tax_id])]} if tax_id else {})})
                 for i, l in enumerate(lineas_dte)]
    else:
        lines = [(0, 0, {"name": f"Factura {tipo_doc}/{folio} — {razon}",
                          "quantity": 1, "price_unit": monto_neto,
                          "account_id": account_id,
                          **({"tax_ids": [(6, 0, [tax_id])]} if tax_id else {})})]

    vals = {
        "move_type": move_type, "partner_id": partner_id,
        "invoice_date": fecha, "invoice_line_ids": lines,
        **({"l10n_latam_document_type_id": doc_type_id} if doc_type_id else {}),
        "l10n_latam_document_number": folio,
        "ref": f"{'FAC' if tipo_doc in ('33','34') else 'NC'} {folio}",
    }
    try:
        move_id = models.execute_kw(db, uid, pwd, "account.move", "create", [vals], {})
        return ResultadoImportOdoo(ok=True, move_id=move_id,
                                   ref=f"{tipo_doc}/{folio}", partner_nombre=razon)
    except Exception as e:
        return ResultadoImportOdoo(ok=False, error=str(e))
