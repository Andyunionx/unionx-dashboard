"""Queries Odoo específicas del módulo de compras. Read-only."""
from __future__ import annotations
from calendar import monthrange
from typing import Optional


class OdooCompras:
    def __init__(self, odoo_query):
        self.q = odoo_query

    def listar_compras_mes(self, anio: int, mes: int) -> list[dict]:
        ultimo_dia = monthrange(anio, mes)[1]
        date_from = f"{anio:04d}-{mes:02d}-01"
        date_to   = f"{anio:04d}-{mes:02d}-{ultimo_dia:02d}"

        domain = [
            ("move_type", "in", ["in_invoice", "in_refund"]),
            ("invoice_date", ">=", date_from),
            ("invoice_date", "<=", date_to),
        ]
        fields = ["id", "name", "partner_id", "invoice_date",
                  "amount_untaxed", "amount_tax", "amount_total",
                  "state", "move_type", "l10n_latam_document_number",
                  "l10n_latam_document_type_id", "ref"]
        movs = self.q.search_read("account.move", domain, fields, limit=5000)

        partner_ids = sorted({m["partner_id"][0] for m in movs if m.get("partner_id")})
        partners = {}
        if partner_ids:
            for p in self.q.search_read("res.partner", [("id", "in", partner_ids)],
                                         ["id", "vat", "name"], limit=len(partner_ids)):
                partners[p["id"]] = p

        doc_type_ids = sorted({m["l10n_latam_document_type_id"][0]
                                for m in movs if m.get("l10n_latam_document_type_id")})
        doc_types = {}
        if doc_type_ids:
            for d in self.q.search_read("l10n_latam.document.type",
                                         [("id", "in", doc_type_ids)],
                                         ["id", "code", "name"], limit=len(doc_type_ids)):
                doc_types[d["id"]] = d

        out = []
        for m in movs:
            partner = partners.get(m["partner_id"][0]) if m.get("partner_id") else None
            dt = doc_types.get(m["l10n_latam_document_type_id"][0]) if m.get("l10n_latam_document_type_id") else None
            out.append({
                "id": m["id"], "name": m["name"],
                "partner_id": m["partner_id"][0] if m.get("partner_id") else None,
                "partner_name": partner["name"] if partner else "",
                "partner_vat": (partner.get("vat") or "").upper() if partner else "",
                "folio": m.get("l10n_latam_document_number") or "",
                "tipo_doc_code": dt["code"] if dt else "",
                "tipo_doc_name": dt["name"] if dt else "",
                "invoice_date": m.get("invoice_date"),
                "amount_untaxed": m.get("amount_untaxed", 0.0),
                "amount_tax": m.get("amount_tax", 0.0),
                "amount_total": m.get("amount_total", 0.0),
                "state": m.get("state"),
                "move_type": m.get("move_type"),
            })
        return out

    def partner_por_rut(self, rut: str) -> Optional[dict]:
        if not rut:
            return None
        for v in [rut, f"CL{rut}", rut.replace("-", "")]:
            res = self.q.search_read("res.partner", [("vat", "=", v)],
                                      ["id", "name", "vat",
                                       "property_account_payable_id", "supplier_rank"],
                                      limit=1)
            if res:
                return res[0]
        return None
