"""
Helpers de consultas a Odoo para el agente de cobranza.

Define las 6 hojas estándar que el agente actualiza por cliente (mismo
contrato que los scripts originales de Martín en C:\\Users\\marti\\odoo-mcp\\).

Hojas estándar:
  - BOL PENDIENTE DE PAGO
  - REVERTIDOS
  - NC
  - FACTURAS PENDIENTES DE PAGO  (todos los clientes, solo tipo 33)
  - PAGADAS                       (últimos 300 días por default)
  - yuju                          (sale.order, últimos 200 días por default)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Importar OdooClient existente del backend de finanzas-unionx
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))
from app.core.odoo_client import OdooClient  # noqa: E402

# Campos del exportador "estado de cuenta vcr1" (definidos en MD de Víctor/Martín)
INV_FIELDS = [
    "l10n_latam_document_number", "partner_id", "date", "invoice_date_due",
    "ref", "payment_reference", "amount_residual", "invoice_origin",
    # Extras útiles
    "name", "move_type", "amount_total", "payment_state",
    "l10n_latam_document_type_id", "journal_id",
]
NC_FIELDS = INV_FIELDS + ["reversed_entry_id"]
SO_FIELDS = [
    "name", "partner_id", "create_date", "yuju_pack_id",
    "channel_order_reference", "fulfillment", "invoice_ids", "amount_total",
    "state",
]

# Tipo de documento Odoo Chile (l10n_latam_document_type_id)
DOC_TYPE_FACTURA = 1   # "(33) Factura Electrónica"
DOC_TYPE_BOLETA = 5    # "(39) Boleta Electrónica"


# ─────────────────────────────────────────────────────────────────────────────
# CONEXIÓN
# ─────────────────────────────────────────────────────────────────────────────
def conectar_odoo(url: str, db: str, username: str, password: str) -> OdooClient:
    """Crea cliente Odoo + autentica. Hace falla rápido si las creds son malas."""
    client = OdooClient(url=url, db=db, username=username, password=password,
                         max_retries=5)
    client.authenticate()
    return client


# ─────────────────────────────────────────────────────────────────────────────
# CONSULTAS ESTÁNDAR (las 6 hojas)
# ─────────────────────────────────────────────────────────────────────────────
def descargar_bol_pendiente(odoo: OdooClient, partner_ids: list[int]) -> list[dict]:
    """Hoja BOL PENDIENTE DE PAGO: boletas emitidas no pagadas."""
    return odoo.search_read_paginated(
        "account.move",
        [
            ("partner_id", "in", partner_ids),
            ("move_type", "=", "out_invoice"),
            ("payment_state", "=", "not_paid"),
            ("state", "=", "posted"),
        ],
        INV_FIELDS,
        page_size=500,
    )


def descargar_revertidos(odoo: OdooClient, partner_ids: list[int]) -> list[dict]:
    """Hoja REVERTIDOS: facturas/boletas con payment_state=reversed."""
    return odoo.search_read_paginated(
        "account.move",
        [
            ("partner_id", "in", partner_ids),
            ("move_type", "=", "out_invoice"),
            ("payment_state", "=", "reversed"),
            ("state", "=", "posted"),
        ],
        INV_FIELDS,
        page_size=500,
    )


def descargar_nc(odoo: OdooClient, partner_ids: list[int]) -> list[dict]:
    """Hoja NC: notas crédito emitidas (move_type=out_refund)."""
    return odoo.search_read_paginated(
        "account.move",
        [
            ("partner_id", "in", partner_ids),
            ("move_type", "=", "out_refund"),
            ("state", "=", "posted"),
        ],
        NC_FIELDS,
        page_size=500,
    )


def descargar_facturas_pendientes(odoo: OdooClient) -> list[dict]:
    """Hoja FACTURAS PENDIENTES DE PAGO:
    TODAS las facturas tipo 33 pendientes (no filtra por cliente, según MD).
    """
    return odoo.search_read_paginated(
        "account.move",
        [
            ("move_type", "=", "out_invoice"),
            ("payment_state", "in", ["not_paid", "partial"]),
            ("l10n_latam_document_type_id", "=", DOC_TYPE_FACTURA),
            ("state", "=", "posted"),
        ],
        INV_FIELDS,
        page_size=500,
    )


def descargar_pagadas(odoo: OdooClient, partner_ids: list[int],
                       dias_atras: int = 300) -> list[dict]:
    """Hoja PAGADAS: facturas/boletas pagadas en últimos N días."""
    fecha_desde = (datetime.now() - timedelta(days=abs(dias_atras))).strftime("%Y-%m-%d")
    return odoo.search_read_paginated(
        "account.move",
        [
            ("partner_id", "in", partner_ids),
            ("move_type", "=", "out_invoice"),
            ("payment_state", "=", "paid"),
            ("state", "=", "posted"),
            ("date", ">=", fecha_desde),
        ],
        INV_FIELDS,
        page_size=500,
    )


def descargar_yuju(odoo: OdooClient, partner_ids: list[int],
                    dias_atras: int = 200) -> list[dict]:
    """Hoja yuju: sale.orders del/los partner(s) en últimos N días.
    Sirve para cruzar boletas via XLOOKUP en el Excel del cliente.
    """
    fecha_desde = (datetime.now() - timedelta(days=abs(dias_atras))).strftime("%Y-%m-%d")
    return odoo.search_read_paginated(
        "sale.order",
        [
            ("partner_id", "in", partner_ids),
            ("create_date", ">=", fecha_desde),
        ],
        SO_FIELDS,
        page_size=500,
    )


def obtener_rut_por_partner(odoo: OdooClient,
                              partner_ids: list[int]) -> dict[int, str]:
    """Lookup RUT (campo vat) por partner_id en res.partner.
    Devuelve {partner_id: rut_str}. RUT vacío → "" (no None).
    """
    if not partner_ids:
        return {}
    partners = odoo.search_read(
        "res.partner",
        [("id", "in", list(set(partner_ids)))],
        ["id", "vat"],
        limit=len(partner_ids),
    )
    return {p["id"]: (p.get("vat") or "") for p in partners}


def obtener_doc_name_por_id(odoo: OdooClient,
                              move_ids: list[int]) -> dict[int, str]:
    """Lookup name por id en account.move (para resolver invoice_ids de yuju).
    Devuelve {move_id: name_str}.
    """
    if not move_ids:
        return {}
    docs = odoo.search_read(
        "account.move",
        [("id", "in", list(set(move_ids)))],
        ["id", "name"],
        limit=len(move_ids),
    )
    return {d["id"]: (d.get("name") or "") for d in docs}


# ─────────────────────────────────────────────────────────────────────────────
# TRANSFORMACIÓN A FORMATO EXCEL
# ─────────────────────────────────────────────────────────────────────────────
def doc_num(v: Any) -> int | str:
    """Convierte l10n_latam_document_number a entero limpio.
    "BEL 461400" → "461400" → 461400.  False/None → "" (no romper Excel).
    """
    if v is None or v is False or v == "":
        return ""
    s = str(v).strip()
    # Quitar prefijos típicos: "BEL ", "FAC ", "NC "
    for prefix in ("BEL ", "FAC ", "NC ", "BES ", "FAS "):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    try:
        return int(s)
    except ValueError:
        return s  # fallback: dejar el string si no es número


def _flatten_many2one(v: Any) -> Any:
    """Odoo devuelve relaciones como [id, "label"]. Para Excel queremos id o label."""
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return v[1]  # label es lo que el usuario lee
    return v if v is not False else ""


# Mapa de codigos de fulfillment de Odoo a labels humanos que usa Martin
FULFILLMENT_LABELS = {
    "fbm": "Seller",
    "fbf": "Flex",
    "fbc": "Full",
    "mix": "Mix",
}


def filas_para_hoja_documentos(docs: list[dict],
                                  rut_por_partner: dict[int, str]) -> list[list]:
    """Formato byte-compatible con el output de Martín (rebuild_*.py).

    Columnas (9):
      A: RUT Nº                  (lookup res.partner.vat)
      B: Empresa                 (partner display name)
      C: Fecha                   (account.move.date)
      D: Fecha de vencimiento    (account.move.invoice_date_due)
      E: Número de Documento     (l10n_latam_document_number como entero)
      F: Referencia de pago      (account.move.payment_reference, típico "BEL 466217")
      G: Referencia              (account.move.ref)
      H: Importe adeudado        (account.move.amount_residual)
      I: Pedido de venta         (account.move.invoice_origin)
    """
    headers = [
        "RUT Nº", "Empresa", "Fecha", "Fecha de vencimiento",
        "Número de Documento", "Referencia de pago", "Referencia",
        "Importe adeudado", "Pedido de venta",
    ]
    rows = [headers]
    for d in docs:
        partner_id = d["partner_id"][0] if d.get("partner_id") else None
        rows.append([
            rut_por_partner.get(partner_id, "") if partner_id else "",
            _flatten_many2one(d.get("partner_id")),
            d.get("date") or "",
            d.get("invoice_date_due") or "",
            doc_num(d.get("l10n_latam_document_number")),
            d.get("payment_reference") or "",
            d.get("ref") or "",
            float(d.get("amount_residual") or 0),
            d.get("invoice_origin") or "",
        ])
    return rows


def filas_para_hoja_nc(docs: list[dict],
                         rut_por_partner: dict[int, str]) -> list[list]:
    """Formato byte-compatible con NC de Martín.

    Columnas (10): Las 9 estándar + J: BEL Original (del reversed_entry_id).
    """
    headers = [
        "RUT Nº", "Empresa", "Fecha", "Fecha de vencimiento",
        "Número de Documento", "Referencia de pago", "Referencia",
        "Importe adeudado", "Pedido de venta", "BEL Original",
    ]
    rows = [headers]
    for d in docs:
        partner_id = d["partner_id"][0] if d.get("partner_id") else None
        # BEL Original = name del documento revertido
        bel_original = _flatten_many2one(d.get("reversed_entry_id"))
        rows.append([
            rut_por_partner.get(partner_id, "") if partner_id else "",
            _flatten_many2one(d.get("partner_id")),
            d.get("date") or "",
            d.get("invoice_date_due") or "",
            doc_num(d.get("l10n_latam_document_number")),
            d.get("payment_reference") or "",
            d.get("ref") or "",
            float(d.get("amount_residual") or 0),
            d.get("invoice_origin") or "",
            bel_original,
        ])
    return rows


def filas_para_hoja_yuju(sos: list[dict],
                           move_name_por_id: dict[int, str]) -> list[list]:
    """Formato byte-compatible con hoja yuju de Martín.

    Columnas (7):
      A: Cliente                   (partner display name)
      B: Fecha creación            (create_date con hora, "YYYY-MM-DD HH:MM:SS")
      C: Referencia de pedido      (sale.order.name, ej "S148816")
      D: Facturas                  (lookup de invoice_ids[0].name, ej "BEL 503133")
      E: Yuju Pack Id              (sale.order.yuju_pack_id)
      F: Marketplace Reference     (sale.order.channel_order_reference)
      G: Fulfillment               (sale.order.fulfillment → label humano)
    """
    headers = [
        "Cliente", "Fecha creación", "Referencia de pedido", "Facturas",
        "Yuju Pack Id", "Marketplace Reference", "Fulfillment",
    ]
    rows = [headers]
    for so in sos:
        # invoice_ids es una lista. Si tiene >1, concatenar separado por coma.
        inv_ids = so.get("invoice_ids") or []
        facturas_names = [move_name_por_id.get(i, "") for i in inv_ids if i]
        facturas_names = [n for n in facturas_names if n]
        facturas_str = ", ".join(facturas_names)

        fulfillment_code = so.get("fulfillment") or ""
        fulfillment_label = FULFILLMENT_LABELS.get(fulfillment_code, fulfillment_code)

        rows.append([
            _flatten_many2one(so.get("partner_id")),
            so.get("create_date") or "",
            so.get("name") or "",
            facturas_str,
            so.get("yuju_pack_id") or "",
            so.get("channel_order_reference") or "",
            fulfillment_label,
        ])
    return rows
