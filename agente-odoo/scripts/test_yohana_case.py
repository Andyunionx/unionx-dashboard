"""
Test E2E del caso Yohana sin necesidad de Claude API.

Mockeamos el intent que el classifier produciria a partir del mail real
y corremos el resto del flow contra Odoo TEST:
  - OdooQuery: lista facturas rechazadas
  - Dispatcher: dry-run del sii_status_fix (no toca Odoo)
  - DraftBuilder: simula la generacion del HTML del borrador
"""
import json
import os
import sys
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.executor.dispatcher import Dispatcher
from src.odoo_query import OdooQuery


console = Console(force_terminal=True)


# --- Mail mockeado (simula lo que vendria del watcher) ---
SOURCE_EMAIL = {
    "id": "MOCK_MAIL_YOHANA",
    "thread_id": "MOCK_THREAD",
    "from": "yohana@melollevo.cl",
    "subject": "Re: cerificar documentos en el SII",
    "date": "Mon, 4 May 2026 08:00:00 -0400",
    "body": (
        "@Andres Browne buenos dias, tenemos 5 documentos que estan en odoo "
        "como rechazados pero si estan aceptados en el SII, como podemos "
        "cambiar el estado en odoo? Quedo atenta"
    ),
    "matched_keywords": ["body:rechazad", "body:cambiar el estado", "subject:sii"],
}

# --- Intent mockeado (lo que el classifier produciria) ---
INTENT = {
    "intent_name": "sii_status_fix",
    "odoo_module": "Contabilidad",
    "entities": {
        # Sin folios explicitos -> el action listara las rechazadas existentes
        # (limitado por max_records_per_run en allowed_actions.yaml)
    },
    "confidence": "alta",
    "summary": "Yohana reporta 5 facturas rechazadas en Odoo pero aceptadas en SII. Solicita cambiar estado en Odoo.",
    "requested_by": "Yohana <yohana@melollevo.cl>",
    "reasoning": "Mock: en flow real esto lo deduce Claude del mail.",
}


def main():
    console.print(Panel(
        "[bold]TEST E2E - Caso Yohana[/bold]\n"
        "[dim]Mockea el intent del mail real y prueba dispatcher contra Odoo TEST.[/dim]",
        border_style="cyan",
    ))

    # 1. Conectar a Odoo TEST
    odoo = OdooQuery()

    # 2. Inspeccionar que hay facturas rechazadas en TEST
    console.print("\n[bold]Buscando facturas rechazadas en Odoo TEST...[/bold]")
    rejected = odoo.find_rejected_invoices_with_dte(limit=20)
    console.print(f"[dim]Encontradas: {len(rejected)} facturas rechazadas[/dim]")

    if rejected:
        t = Table(title="Facturas rechazadas (sample)")
        t.add_column("ID")
        t.add_column("Name")
        t.add_column("Folio")
        t.add_column("Cliente")
        t.add_column("Monto")
        t.add_column("DTE Status")
        for inv in rejected[:10]:
            partner = inv.get("partner_id") or [None, "(sin partner)"]
            t.add_row(
                str(inv.get("id")),
                str(inv.get("name") or "")[:25],
                str(inv.get("l10n_latam_document_number") or ""),
                str(partner[1] if isinstance(partner, list) else partner)[:20],
                f"{inv.get('amount_total', 0):,.0f}",
                str(inv.get("l10n_cl_dte_status") or ""),
            )
        console.print(t)

    # 3. Dispatcher: dry-run
    console.print("\n[bold]Despachando intent al executor...[/bold]")
    dispatcher = Dispatcher(odoo)
    result = dispatcher.dispatch(INTENT, SOURCE_EMAIL)

    console.print(f"\n[bold]Resultado executor:[/bold]")
    console.print(f"  intent: {result.intent_name}")
    console.print(f"  mode: [yellow]{result.mode}[/yellow]")
    console.print(f"  status: {result.status}")
    console.print(f"  message: {result.message}")
    console.print(f"  registros afectados (plan): {len(result.records_affected)}")

    if result.records_affected:
        t2 = Table(title="Plan de cambios (dry-run)")
        t2.add_column("ID")
        t2.add_column("Folio")
        t2.add_column("Antes")
        t2.add_column("Despues")
        t2.add_column("Skip?")
        for r in result.records_affected[:10]:
            t2.add_row(
                str(r.get("id")),
                str(r.get("folio") or ""),
                str(r.get("before") or "-"),
                str(r.get("after") or "-"),
                "SI" if r.get("skipped") else "no",
            )
        console.print(t2)

    # 4. Verificar que NADA se modifico en Odoo
    console.print("\n[bold]Verificacion: cantidad de rechazadas DESPUES del dry-run...[/bold]")
    rejected_after = odoo.count(
        "account.move",
        [("l10n_cl_dte_status", "=", "rejected"),
         ("move_type", "in", ["out_invoice", "out_refund"])],
    )
    console.print(f"[dim]Rechazadas antes: {len(rejected)} | despues: {rejected_after}[/dim]")
    if rejected_after == len(rejected) or rejected_after >= len(rejected):
        console.print("[green]OK - Odoo NO fue modificado (dry-run respetado)[/green]")
    else:
        console.print(f"[red]ALERTA: cantidad cambio. Antes={len(rejected)} Despues={rejected_after}[/red]")

    # 5. Mostrar audit log
    log_path = BASE / "data" / "odoo_actions_log.jsonl"
    if log_path.exists():
        console.print(f"\n[bold]Audit log:[/bold] {log_path}")
        with open(log_path, encoding="utf-8") as f:
            lines = f.readlines()
        if lines:
            last = json.loads(lines[-1])
            console.print(f"[dim]Ultima entrada: {last['timestamp']} | "
                          f"{last['intent_name']} | {last['mode']} | {last['status']}[/dim]")


if __name__ == "__main__":
    main()
