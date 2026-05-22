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


def filas_para_hoja_documentos(docs: list[dict]) -> list[list]:
    """Convierte docs de account.move a filas para Excel.
    Devuelve lista de filas (cada fila es una lista). Primera fila = headers.

    Columnas (orden basado en exportador "estado de cuenta vcr1" según MD):
      A: doc_number       (l10n_latam_document_number como entero)
      B: partner          (nombre cliente)
      C: date             (fecha contable)
      D: invoice_date_due (vencimiento)
      E: ref              (referencia)
      F: payment_reference
      G: amount_residual  (saldo pendiente)
      H: amount_total
      I: invoice_origin   (SO de origen)
      J: payment_state
      K: doc_type         (33/39)
      L: journal
      M: name             (BEL XXXXX completo)
      N: id               (id Odoo para debug)
    """
    headers = [
        "doc_number", "partner", "date", "invoice_date_due", "ref",
        "payment_reference", "amount_residual", "amount_total",
        "invoice_origin", "payment_state", "doc_type", "journal",
        "name", "id_odoo",
    ]
    rows = [headers]
    for d in docs:
        rows.append([
            doc_num(d.get("l10n_latam_document_number")),
            _flatten_many2one(d.get("partner_id")),
            d.get("date") or "",
            d.get("invoice_date_due") or "",
            d.get("ref") or "",
            d.get("payment_reference") or "",
            float(d.get("amount_residual") or 0),
            float(d.get("amount_total") or 0),
            d.get("invoice_origin") or "",
            d.get("payment_state") or "",
            _flatten_many2one(d.get("l10n_latam_document_type_id")),
            _flatten_many2one(d.get("journal_id")),
            d.get("name") or "",
            d.get("id"),
        ])
    return rows


def filas_para_hoja_nc(docs: list[dict]) -> list[list]:
    """Similar a documentos pero agrega col `reversed_entry` (referencia al doc revertido)."""
    headers = [
        "doc_number", "partner", "date", "invoice_date_due", "ref",
        "payment_reference", "amount_residual", "amount_total",
        "invoice_origin", "payment_state", "doc_type", "journal",
        "reversed_entry", "name", "id_odoo",
    ]
    rows = [headers]
    for d in docs:
        rows.append([
            doc_num(d.get("l10n_latam_document_number")),
            _flatten_many2one(d.get("partner_id")),
            d.get("date") or "",
            d.get("invoice_date_due") or "",
            d.get("ref") or "",
            d.get("payment_reference") or "",
            float(d.get("amount_residual") or 0),
            float(d.get("amount_total") or 0),
            d.get("invoice_origin") or "",
            d.get("payment_state") or "",
            _flatten_many2one(d.get("l10n_latam_document_type_id")),
            _flatten_many2one(d.get("journal_id")),
            _flatten_many2one(d.get("reversed_entry_id")),
            d.get("name") or "",
            d.get("id"),
        ])
    return rows


def filas_para_hoja_yuju(sos: list[dict]) -> list[list]:
    """Convierte sale.orders a filas para hoja yuju.
    Columnas estándar usadas en los Excel de clientes (en el MD aparece que
    Falabella usa col G = Marketplace Reference y col D para el XLOOKUP).
    """
    headers = [
        "name", "partner", "create_date", "yuju_pack_id",
        "channel_order_reference", "fulfillment", "amount_total", "state",
        "invoice_ids", "id_odoo",
    ]
    rows = [headers]
    for so in sos:
        rows.append([
            so.get("name") or "",
            _flatten_many2one(so.get("partner_id")),
            (so.get("create_date") or "")[:10],
            so.get("yuju_pack_id") or "",
            so.get("channel_order_reference") or "",
            so.get("fulfillment") or "",
            float(so.get("amount_total") or 0),
            so.get("state") or "",
            ",".join(str(i) for i in (so.get("invoice_ids") or [])),
            so.get("id"),
        ])
    return rows
