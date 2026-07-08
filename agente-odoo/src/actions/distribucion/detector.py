"""
Detecta facturas de compra en borrador con líneas en 42410104.
Excluye Liquidaciones-Factura (documentos FAL).
NUNCA escribe en Odoo.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

CUENTA_CATCHALL_ID = 1377  # 42410104 COMISIÓN GRANDES CUENTAS


@dataclass
class LineaFactura:
    line_id: int
    move_id: int
    glosa: str
    cantidad: float
    precio_unitario: float
    monto_neto: float
    cuenta_actual_id: int
    cuenta_actual_codigo: str
    cuenta_actual_nombre: str
    analytic_distribution: dict


@dataclass
class FacturaParaDistribuir:
    move_id: int
    name: str
    folio: str
    partner_id: int
    partner_nombre: str
    partner_rut: str
    fecha: Optional[str]
    monto_total: float
    state: str
    lineas: list[LineaFactura] = field(default_factory=list)

    @property
    def tiene_lineas_catchall(self) -> bool:
        return any(l.cuenta_actual_id == CUENTA_CATCHALL_ID for l in self.lineas)


def detectar_facturas_pendientes(
    odoo_client,
    estados: list[str] = None,
    limite: int = 100,
    folio_especifico: str = None,
) -> list[FacturaParaDistribuir]:
    estados = estados or ["draft"]

    # Buscar PRIMERO las líneas en la cuenta catchall y de ahí subir a los moves.
    # (Antes se traían las primeras N facturas draft de TODAS y se filtraba
    # después → con >N borradores, facturas con 42410104 se perdían en silencio.)
    lineas_catchall = odoo_client.search_read(
        "account.move.line",
        [("account_id", "=", CUENTA_CATCHALL_ID),
         ("parent_state", "in", estados),
         ("display_type", "in", [False, "product"]),
         ("move_id.move_type", "in", ["in_invoice", "in_refund"])],
        ["id", "move_id"], limit=10000,
    )
    if not lineas_catchall:
        return []
    move_ids_catchall = sorted({l["move_id"][0] for l in lineas_catchall})
    if len(move_ids_catchall) > limite:
        print(f"  ⚠️  {len(move_ids_catchall)} facturas con 42410104 — procesando {limite} "
              f"(las demás en la próxima corrida)")
        move_ids_catchall = move_ids_catchall[:limite]

    domain = [("id", "in", move_ids_catchall)]
    if folio_especifico:
        domain.append(("l10n_latam_document_number", "=", folio_especifico))

    movs = odoo_client.search_read(
        "account.move", domain,
        ["id", "name", "partner_id", "invoice_date", "amount_total", "state",
         "l10n_latam_document_number", "invoice_line_ids"],
        limit=limite,
    )
    if not movs:
        return []

    partner_ids = list({m["partner_id"][0] for m in movs if m.get("partner_id")})
    partners = {}
    if partner_ids:
        for p in odoo_client.search_read("res.partner", [("id", "in", partner_ids)],
                                          ["id", "name", "vat"], limit=len(partner_ids)):
            partners[p["id"]] = p

    all_move_ids = [m["id"] for m in movs]
    todas_lineas = odoo_client.search_read(
        "account.move.line",
        [("move_id", "in", all_move_ids), ("display_type", "in", [False, "product"])],
        ["id", "move_id", "name", "quantity", "price_unit", "price_subtotal",
         "account_id", "analytic_distribution"],
        limit=10000,
    )
    account_ids = list({l["account_id"][0] for l in todas_lineas if l.get("account_id")})
    accounts = {}
    if account_ids:
        for a in odoo_client.search_read("account.account", [("id", "in", account_ids)],
                                          ["id", "code", "name"], limit=len(account_ids)):
            accounts[a["id"]] = a

    lineas_por_move: dict[int, list[dict]] = {}
    for l in todas_lineas:
        mid = l["move_id"][0] if l.get("move_id") else None
        if mid:
            lineas_por_move.setdefault(mid, []).append(l)

    resultado: list[FacturaParaDistribuir] = []
    for m in movs:
        # Filtro client-side por folio
        folio_factura = m.get("l10n_latam_document_number") or ""  # xmlrpc devuelve False
        if folio_especifico and folio_factura != folio_especifico:
            continue

        partner = partners.get(m["partner_id"][0]) if m.get("partner_id") else None
        rut = ""
        if partner:
            vat = (partner.get("vat") or "").upper().strip()
            rut = vat[2:] if vat.startswith("CL") else vat

        lineas_obj = []
        for l in lineas_por_move.get(m["id"], []):
            acc = accounts.get(l["account_id"][0]) if l.get("account_id") else None
            lineas_obj.append(LineaFactura(
                line_id=l["id"], move_id=m["id"],
                glosa=(l.get("name") or "").strip(),
                cantidad=float(l.get("quantity") or 1),
                precio_unitario=float(l.get("price_unit") or 0),
                monto_neto=float(l.get("price_subtotal") or 0),
                cuenta_actual_id=acc["id"] if acc else 0,
                cuenta_actual_codigo=acc["code"] if acc else "",
                cuenta_actual_nombre=acc["name"] if acc else "",
                analytic_distribution=l.get("analytic_distribution") or {},
            ))

        lineas_catchall_obj = [l for l in lineas_obj if l.cuenta_actual_id == CUENTA_CATCHALL_ID]
        if not lineas_catchall_obj:
            continue

        resultado.append(FacturaParaDistribuir(
            move_id=m["id"], name=(m.get("name") or ""), folio=folio_factura,
            partner_id=m["partner_id"][0] if m.get("partner_id") else 0,
            partner_nombre=partner["name"] if partner else "",
            partner_rut=rut, fecha=m.get("invoice_date"),
            monto_total=float(m.get("amount_total") or 0),
            state=m.get("state", ""), lineas=lineas_obj,
        ))

    return resultado
