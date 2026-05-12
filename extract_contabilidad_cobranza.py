#!/usr/bin/env python3
"""
Extractor Cobranza: descarga de Odoo todos los documentos de venta NO
conciliados (facturas y boletas pendientes) + pedidos de venta relacionados.

Pasos del flujo COBRANZA según Andrés:
  1. Documentos contables NO conciliados → ESTE EXTRACTOR
  2. Pedidos de venta + relación documento ↔ pedido → ESTE EXTRACTOR
  3. Boleta → cruzar con pagos portales (Mercado Pago, Webpay, Yuju...) [upload manual]
  4. Factura → cruzar con cartolas bancarias [upload manual]
  5. Validar contra drives de devolución y NC [futuro]
  6. Conciliar en Odoo [vista con botón aprobación]
  7. Reporte CxC

Output:
  - data/contabilidad/cobranza/documentos_no_conciliados.parquet
  - data/contabilidad/cobranza/pedidos_venta.parquet
  - data/contabilidad/cobranza/notas_credito.parquet
  - data/contabilidad/cobranza/resumen.json

Cron: corre cada 6h (sync_contabilidad.yml).
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

from app.core.odoo_client import OdooClient  # noqa

OUT_DIR = PROJECT_ROOT / "data" / "contabilidad" / "cobranza"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ODOO_URL = os.environ.get("ODOO_URL", "https://unionxb2b.odoo.com")
ODOO_DB = os.environ.get("ODOO_DB", "bmya-innovatek-sh-prd-6981800")
ODOO_USER = (
    os.environ.get("OPS_ODOO_USER", "").strip()
    or os.environ.get("ANDRES_ODOO_USER", "").strip()
    or "andres@grupoeter.cl"
)
ODOO_PWD = (
    os.environ.get("OPS_ODOO_PASSWORD", "").strip()
    or os.environ.get("ANDRES_ODOO_PASSWORD", "").strip()
)

# Ventana: documentos pendientes desde hace N días (cubre vencidos y vigentes)
DIAS_HACIA_ATRAS = 365


def main():
    print(f"=== Extract Contabilidad Cobranza — {datetime.now().isoformat()} ===\n", flush=True)

    if not ODOO_PWD:
        print("[ERROR] ANDRES_ODOO_PASSWORD/OPS_ODOO_PASSWORD no seteado", flush=True)
        return 1

    odoo = OdooClient(url=ODOO_URL, db=ODOO_DB, username=ODOO_USER,
                       password=ODOO_PWD, max_retries=3)
    print(f"[1] Conectando Odoo {ODOO_URL} como {ODOO_USER}...", flush=True)
    odoo.authenticate()

    fecha_desde = (datetime.now() - timedelta(days=DIAS_HACIA_ATRAS)).strftime("%Y-%m-%d")

    # ─── 1. DOCUMENTOS NO CONCILIADOS (account.move) ────────────────────
    print(f"\n[2] Cargando facturas/boletas NO conciliadas desde {fecha_desde}...", flush=True)
    docs = odoo.search_read_paginated(
        "account.move",
        [
            ("move_type", "in", ["out_invoice", "out_refund"]),  # facturas y NC de venta
            ("state", "=", "posted"),
            ("payment_state", "in", ["not_paid", "partial", "in_payment"]),
            ("invoice_date", ">=", fecha_desde),
        ],
        [
            "id", "name", "move_type", "invoice_date", "invoice_date_due",
            "partner_id", "amount_total", "amount_residual",
            "amount_total_signed", "amount_residual_signed",
            "currency_id", "payment_state", "state",
            "ref", "invoice_origin",  # invoice_origin trae el SO si fue creado desde uno
            "journal_id", "l10n_latam_document_type_id",
        ],
        page_size=500,
    )
    print(f"    {len(docs):,} documentos pendientes", flush=True)

    # Determinar tipo de documento (boleta vs factura) por journal/document_type
    # En Odoo Chile: l10n_latam_document_type_id define el tipo (33 factura, 39 boleta, etc.)
    rows_docs = []
    hoy = datetime.now().date()
    for d in docs:
        partner_name = d["partner_id"][1] if d.get("partner_id") else ""
        partner_id = d["partner_id"][0] if d.get("partner_id") else None
        journal_name = d["journal_id"][1] if d.get("journal_id") else ""
        doc_type_name = (d["l10n_latam_document_type_id"][1]
                          if d.get("l10n_latam_document_type_id") else "")
        # Heurística tipo: por document_type primero, luego por journal
        tipo = "FACTURA"
        if "boleta" in doc_type_name.lower() or "boleta" in journal_name.lower():
            tipo = "BOLETA"
        elif "ticket" in doc_type_name.lower() or "ticket" in journal_name.lower():
            tipo = "BOLETA"

        # Días vencido
        fecha_due = d.get("invoice_date_due") or d.get("invoice_date")
        try:
            fecha_due_d = datetime.strptime(fecha_due, "%Y-%m-%d").date() if fecha_due else None
        except Exception:
            fecha_due_d = None
        dias_vencido = (hoy - fecha_due_d).days if fecha_due_d else None

        # Aging bucket
        if dias_vencido is None:
            bucket = "Sin fecha"
        elif dias_vencido < 0:
            bucket = "Vigente"
        elif dias_vencido <= 30:
            bucket = "1-30 días"
        elif dias_vencido <= 60:
            bucket = "31-60 días"
        elif dias_vencido <= 90:
            bucket = "61-90 días"
        else:
            bucket = "+90 días"

        rows_docs.append({
            "id_odoo": d["id"],
            "documento": d.get("name", ""),
            "tipo": tipo,
            "doc_type": doc_type_name,
            "fecha_emision": d.get("invoice_date"),
            "fecha_vencimiento": fecha_due,
            "dias_vencido": dias_vencido,
            "bucket_aging": bucket,
            "partner_id": partner_id,
            "partner_nombre": partner_name,
            "monto_total": float(d.get("amount_total", 0) or 0),
            "monto_pendiente": float(d.get("amount_residual", 0) or 0),
            "monto_pagado": float((d.get("amount_total", 0) or 0) - (d.get("amount_residual", 0) or 0)),
            "estado_pago": d.get("payment_state", ""),
            "moneda": d["currency_id"][1] if d.get("currency_id") else "CLP",
            "referencia": d.get("ref", "") or "",
            "origen_so": d.get("invoice_origin", "") or "",
            "journal": journal_name,
            "es_nc": d.get("move_type") == "out_refund",
        })

    df_docs = pd.DataFrame(rows_docs)
    df_docs.to_parquet(OUT_DIR / "documentos_no_conciliados.parquet", index=False)
    print(f"    parquet: documentos_no_conciliados.parquet", flush=True)

    # ─── 2. NOTAS DE CRÉDITO (separadas para fácil cruce) ────────────────
    df_nc = df_docs[df_docs["es_nc"]].copy()
    df_nc.to_parquet(OUT_DIR / "notas_credito.parquet", index=False)
    print(f"    {len(df_nc):,} notas de crédito → notas_credito.parquet", flush=True)

    # ─── 3. PEDIDOS DE VENTA (relacionar con documentos por origen_so) ───
    print(f"\n[3] Cargando pedidos de venta relacionados...", flush=True)
    so_origins = sorted({d["origen_so"] for d in rows_docs if d.get("origen_so")})
    if so_origins:
        sale_orders = odoo.search_read(
            "sale.order",
            [("name", "in", so_origins)],
            ["id", "name", "date_order", "partner_id", "amount_total",
             "state", "user_id", "team_id", "client_order_ref"],
            limit=10000,
        )
    else:
        sale_orders = []

    rows_so = []
    for so in sale_orders:
        rows_so.append({
            "id_odoo": so["id"],
            "pedido": so.get("name", ""),
            "fecha_pedido": so.get("date_order", "")[:10] if so.get("date_order") else "",
            "partner_id": so["partner_id"][0] if so.get("partner_id") else None,
            "partner_nombre": so["partner_id"][1] if so.get("partner_id") else "",
            "monto_total": float(so.get("amount_total", 0) or 0),
            "estado": so.get("state", ""),
            "vendedor": so["user_id"][1] if so.get("user_id") else "",
            "canal": so["team_id"][1] if so.get("team_id") else "",
            "referencia_cliente": so.get("client_order_ref", "") or "",
        })
    df_so = pd.DataFrame(rows_so)
    df_so.to_parquet(OUT_DIR / "pedidos_venta.parquet", index=False)
    print(f"    {len(df_so):,} pedidos → pedidos_venta.parquet", flush=True)

    # ─── 4. RESUMEN ──────────────────────────────────────────────────────
    total_pendiente = df_docs["monto_pendiente"].sum() if not df_docs.empty else 0
    by_bucket = df_docs.groupby("bucket_aging")["monto_pendiente"].sum().to_dict()
    by_tipo = df_docs.groupby("tipo")["monto_pendiente"].sum().to_dict()
    top_deudores = (df_docs.groupby("partner_nombre")["monto_pendiente"].sum()
                            .sort_values(ascending=False).head(20).to_dict())

    resumen = {
        "generado_en": datetime.now().isoformat(),
        "ventana_dias": DIAS_HACIA_ATRAS,
        "fuente": f"{ODOO_URL} ({ODOO_DB})",
        "total_documentos_pendientes": len(df_docs),
        "total_monto_pendiente_clp": round(total_pendiente, 0),
        "monto_por_aging": {k: round(v, 0) for k, v in by_bucket.items()},
        "monto_por_tipo": {k: round(v, 0) for k, v in by_tipo.items()},
        "top_20_deudores": [
            {"partner": k, "monto": round(v, 0)} for k, v in top_deudores.items()
        ],
        "notas_credito_count": len(df_nc),
        "pedidos_venta_count": len(df_so),
    }

    with open(OUT_DIR / "resumen.json", "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=str)
    print(f"    resumen.json", flush=True)

    print(f"\n=== RESUMEN ===")
    print(f"  Documentos pendientes: {len(df_docs):,}")
    print(f"  Monto total pendiente: ${total_pendiente:,.0f} CLP")
    print(f"  Por tipo: {by_tipo}")
    print(f"  Por aging: {by_bucket}")
    print(f"  Notas de crédito: {len(df_nc):,}")
    print(f"  Pedidos venta vinculados: {len(df_so):,}")
    print(f"\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
