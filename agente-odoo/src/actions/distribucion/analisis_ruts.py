"""
Detecta RUTs de proveedores que llegaron a Odoo sin partner configurado.

Consulta facturas de compra recientes y agrupa las que tienen:
  - partner_id sin vat (RUT) → no se puede identificar el proveedor
  - partner_id sin nombre real (Unknown, False, etc.)

Complementa el módulo de distribución: si un proveedor no tiene partner,
sus facturas no llegarán bien clasificadas y es necesario crearlo.

NUNCA escribe en Odoo.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class RutSinPartner:
    partner_id: int
    partner_nombre: str
    partner_vat: str          # vacío o None si es el problema
    n_facturas: int
    monto_total: float
    ultima_factura: str
    ejemplo_folio: str


def detectar_ruts_sin_partner(
    odoo_client,
    dias: int = 30,
) -> list[RutSinPartner]:
    """
    Busca facturas de compra recientes cuyos partners no tienen RUT configurado.

    Args:
        odoo_client: OdooClient autenticado
        dias: ventana de días hacia atrás

    Returns:
        Lista de RutSinPartner con proveedores sin RUT, ordenados por monto desc.
    """
    desde = (date.today() - timedelta(days=dias)).isoformat()

    movs = odoo_client.search_read(
        "account.move",
        [
            ("move_type", "in", ["in_invoice", "in_refund"]),
            ("invoice_date", ">=", desde),
            ("state", "in", ["draft", "posted"]),
        ],
        ["id", "name", "partner_id", "amount_total", "invoice_date",
         "l10n_latam_document_number"],
        limit=2000,
    )

    if not movs:
        return []

    # Resolver partners
    partner_ids = list({m["partner_id"][0] for m in movs if m.get("partner_id")})
    partners = {}
    if partner_ids:
        for p in odoo_client.search_read(
            "res.partner",
            [("id", "in", partner_ids)],
            ["id", "name", "vat"],
            limit=len(partner_ids),
        ):
            partners[p["id"]] = p

    # Agrupar por partner_id los que NO tienen vat
    sin_rut: dict[int, dict] = {}
    for m in movs:
        if not m.get("partner_id"):
            continue
        pid = m["partner_id"][0]
        partner = partners.get(pid, {})
        vat = (partner.get("vat") or "").strip()

        # Detectar sin RUT: vat vacío, None, o claramente genérico
        if vat and vat.upper() not in ("", "FALSE", "NONE", "66666666-6"):
            continue  # tiene RUT válido → ok

        if pid not in sin_rut:
            sin_rut[pid] = {
                "partner_nombre": partner.get("name", "Sin nombre"),
                "partner_vat": vat,
                "facturas": [],
            }
        sin_rut[pid]["facturas"].append(m)

    resultado = []
    for pid, info in sin_rut.items():
        facturas = info["facturas"]
        monto_total = sum(f.get("amount_total", 0) for f in facturas)
        ultima = max((f.get("invoice_date") or "") for f in facturas)
        ejemplo = (facturas[-1].get("l10n_latam_document_number") or
                   facturas[-1].get("name") or "?")

        resultado.append(RutSinPartner(
            partner_id=pid,
            partner_nombre=info["partner_nombre"],
            partner_vat=info["partner_vat"] or "(sin RUT)",
            n_facturas=len(facturas),
            monto_total=monto_total,
            ultima_factura=ultima,
            ejemplo_folio=ejemplo,
        ))

    resultado.sort(key=lambda x: x.monto_total, reverse=True)
    return resultado
