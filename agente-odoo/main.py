"""
Agente Odoo - Punto de entrada.

Monitorea Gmail buscando dudas/solicitudes Odoo, las clasifica,
ejecuta la solucion (con safety layer) y genera borrador de respuesta.

Uso:
    python main.py              # Modo monitor (polling continuo)
    python main.py --scan       # Escaneo unico
    python main.py --status     # Ver ultimas acciones del audit log
"""
import argparse
import json
import os
import sys
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Reusa GmailClient de agente-comex (mismo token)
AGENTE_COMEX = Path(__file__).parent.parent / "agente-comex"
sys.path.insert(0, str(AGENTE_COMEX))
from src.gmail_client import GmailClient  # type: ignore  # noqa: E402

from src.email_watcher import EmailWatcher
from src.orchestrator import Orchestrator
from src.config_loader import load_config

BASE_DIR = Path(__file__).parent
console = Console(force_terminal=True)


def print_banner():
    config = load_config()
    env = config["odoo"]["environment"]
    exec_mode = "EJECUTA" if config["executor"]["execute_mode"] else "DRY-RUN"
    env_color = "red" if env == "produccion" else "yellow"

    console.print(Panel(
        "[bold blue]AGENTE ODOO[/bold blue]\n"
        "[dim]UnionX - Asistente de soporte Odoo via Gmail[/dim]\n\n"
        "[dim]Flujo:[/dim]\n"
        "  Mail Odoo -> Clasifica -> Consulta Odoo -> Ejecuta -> Borrador Gmail\n\n"
        f"[dim]Entorno Odoo:[/dim] [{env_color}]{env.upper()}[/{env_color}]\n"
        f"[dim]Modo Executor:[/dim] [{'red' if exec_mode == 'EJECUTA' else 'green'}]{exec_mode}[/{'red' if exec_mode == 'EJECUTA' else 'green'}]",
        border_style="blue",
    ))


def show_status():
    """Muestra las ultimas N entradas del audit log."""
    config = load_config()
    log_path = BASE_DIR / config["executor"]["log_path"]

    if not log_path.exists():
        console.print("[dim]Sin acciones registradas todavia.[/dim]")
        return

    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))

    table = Table(title="Ultimas acciones del agente Odoo")
    table.add_column("Fecha", style="dim")
    table.add_column("Intent")
    table.add_column("Modo")
    table.add_column("Status")
    table.add_column("Registros")
    table.add_column("De")

    for e in entries[-15:]:
        status_color = {"ok": "green", "error": "red", "skipped": "yellow"}.get(e["status"], "white")
        table.add_row(
            e["timestamp"][:16],
            e["intent_name"],
            e["mode"],
            f"[{status_color}]{e['status']}[/{status_color}]",
            str(len(e.get("records_affected", []))),
            e.get("source_email", {}).get("from", "")[:30],
        )

    console.print(table)


def check_setup() -> bool:
    """Verifica configuracion."""
    config = load_config()
    token_path = (BASE_DIR / config["gmail"]["token_path"]).resolve()
    if not token_path.exists():
        console.print(f"[red]FALTA token Gmail: {token_path}[/red]")
        console.print("  Ejecuta primero: python ../agente-comex/setup_gmail.py")
        return False

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]FALTA ANTHROPIC_API_KEY en el entorno[/red]")
        return False

    odoo_config = (BASE_DIR / config["odoo"]["config_path"]).resolve()
    if not odoo_config.exists():
        console.print(f"[red]FALTA odoo config: {odoo_config}[/red]")
        return False

    console.print("[green]OK - Configuracion completa[/green]")
    return True


def main():
    parser = argparse.ArgumentParser(description="Agente Odoo")
    parser.add_argument("--scan", action="store_true", help="Escaneo unico")
    parser.add_argument("--status", action="store_true", help="Ver audit log")
    args = parser.parse_args()

    print_banner()

    if args.status:
        show_status()
        return

    if not check_setup():
        sys.exit(1)

    gmail = GmailClient()
    watcher = EmailWatcher(gmail)
    orchestrator = Orchestrator(gmail)

    if args.scan:
        console.print("\n[bold]Escaneo unico...[/bold]\n")
        candidates = watcher.scan_once()
        if not candidates:
            console.print("[dim]Sin candidatos nuevos.[/dim]")
            return
        for c in candidates:
            orchestrator.handle_candidate(c)
    else:
        console.print("\n[bold]Modo monitor (Ctrl+C para detener)[/bold]\n")
        try:
            watcher.run(on_candidate=orchestrator.handle_candidate)
        except KeyboardInterrupt:
            console.print("\n[yellow]Monitor detenido.[/yellow]")


if __name__ == "__main__":
    main()
