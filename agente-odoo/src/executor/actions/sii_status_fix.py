"""
Accion: sii_status_fix

Caso del mail de Yohana (4-may-2026):
> "tenemos 5 documentos que estan en odoo como rechazados pero si estan
>  aceptados en el SII, como podemos cambiar el estado en odoo?"

Esta accion cambia l10n_cl_dte_status de 'rejected' a 'accepted' en
las facturas que el intent classifier identifique (por folio o por busqueda).

IMPORTANTE: Esta accion NO consulta el SII directamente para validar.
Confia en lo que dice el solicitante (Yohana) o en folios explicitos
del mail. Por eso require_human_confirmation=true en el yaml.
"""
from typing import Optional


def _get_target_invoices(odoo_query, intent: dict, spec: dict) -> list[dict]:
    """
    Identifica las facturas objetivo. Prioridad:
      1. Si el intent trae 'folios' explicitos, busca por folio.
      2. Si trae 'invoice_ids', usa esos.
      3. Si no, lista todas las rechazadas (limitadas por max_records_per_run).
    """
    entities = intent.get("entities", {})
    max_records = spec.get("max_records_per_run", 20)

    # Caso 1: folios explicitos
    folios = entities.get("folios") or entities.get("folio_numbers")
    if folios:
        results = []
        for folio in folios[:max_records]:
            inv = odoo_query.get_invoice_by_folio(str(folio))
            if inv:
                results.append(inv)
        return results

    # Caso 2: ids explicitos
    ids = entities.get("invoice_ids")
    if ids:
        domain = [("id", "in", ids[:max_records])]
        return odoo_query.search_read(
            "account.move", domain,
            ["id", "name", "partner_id", "amount_total", "l10n_cl_dte_status",
             "l10n_latam_document_number"],
            limit=max_records,
        )

    # Caso 3: lista todas las rechazadas
    return odoo_query.find_rejected_invoices_with_dte(limit=max_records)


def dry_run(odoo_query, intent: dict, spec: dict) -> list[dict]:
    """
    Simula la accion. Retorna lista de registros que SERIAN modificados,
    cada uno con before_state, after_state.

    NO toca Odoo.
    """
    targets = _get_target_invoices(odoo_query, intent, spec)
    plan = []
    for inv in targets:
        # Solo procesa los que estan rechazados (filtra defensivamente)
        current_status = inv.get("l10n_cl_dte_status")
        if current_status != "rejected":
            plan.append({
                "id": inv["id"],
                "name": inv.get("name"),
                "folio": inv.get("l10n_latam_document_number"),
                "skipped": True,
                "reason": f"Estado actual='{current_status}', no es 'rejected'",
            })
            continue

        plan.append({
            "id": inv["id"],
            "name": inv.get("name"),
            "folio": inv.get("l10n_latam_document_number"),
            "partner_id": inv.get("partner_id"),
            "amount_total": inv.get("amount_total"),
            "before": {"l10n_cl_dte_status": "rejected"},
            "after": {"l10n_cl_dte_status": "accepted"},
            "skipped": False,
        })
    return plan


def execute(odoo_query, intent: dict, spec: dict, dry_run_plan: list[dict]) -> list[dict]:
    """
    Ejecuta el plan dry_run en Odoo de verdad.
    Solo procesa entradas con skipped=False.
    """
    executed = []
    for entry in dry_run_plan:
        if entry.get("skipped"):
            executed.append(entry)
            continue

        inv_id = entry["id"]
        try:
            odoo_query.write(
                "account.move",
                [inv_id],
                {"l10n_cl_dte_status": "accepted"},
            )
            executed.append({**entry, "executed": True})
        except Exception as e:
            executed.append({**entry, "executed": False, "error": str(e)})
    return executed
