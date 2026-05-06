"""
Orchestrator - Pega los componentes en un flujo end-to-end:

  email candidato -> intent_classifier -> odoo_query -> executor -> draft_builder

Es el handler que recibe cada candidato del watcher.
"""
from rich.console import Console
from rich.panel import Panel

from .draft_builder import DraftBuilder
from .executor.dispatcher import Dispatcher
from .intent_classifier import IntentClassifier
from .odoo_query import OdooQuery


console = Console(force_terminal=True)


class Orchestrator:
    def __init__(self, gmail):
        self.gmail = gmail
        self.classifier = IntentClassifier()
        self.odoo = OdooQuery()
        self.dispatcher = Dispatcher(self.odoo)
        self.draft_builder = DraftBuilder(gmail)

    def handle_candidate(self, email: dict):
        """Procesa un mail candidato detectado por el watcher."""
        console.print(Panel(
            f"[bold]Mail candidato[/bold]\n"
            f"De: {email.get('from')}\n"
            f"Asunto: {email.get('subject')}\n"
            f"Keywords: {', '.join(email.get('matched_keywords', []))}",
            border_style="cyan",
        ))

        # 1. Clasificar intent
        try:
            intent = self.classifier.classify(email)
        except Exception as e:
            console.print(f"[red]Error clasificando: {e}[/red]")
            return

        console.print(f"[dim]Intent: {intent.get('intent_name')} "
                      f"({intent.get('confidence')}) - {intent.get('summary')}[/dim]")

        # 2. Despachar al executor (whitelist + dry-run + audit log)
        result = self.dispatcher.dispatch(intent, email)
        console.print(f"[dim]Executor: mode={result.mode} status={result.status} "
                      f"records={len(result.records_affected)}[/dim]")
        if result.message:
            console.print(f"[dim]  -> {result.message}[/dim]")

        # 3. Crear borrador de respuesta en Gmail
        try:
            draft_id = self.draft_builder.create_reply_draft(email, intent, result)
            console.print(f"[green]Borrador creado en Gmail: {draft_id}[/green]")
        except Exception as e:
            console.print(f"[red]Error creando borrador: {e}[/red]")
            return

        # 4. Marcar mail como procesado para no reprocesarlo
        try:
            self.draft_builder.mark_email_processed(email["id"])
        except Exception as e:
            console.print(f"[yellow]No se pudo marcar como procesado: {e}[/yellow]")
