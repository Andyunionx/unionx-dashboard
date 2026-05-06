"""
Auditor on-demand - Inspecciona modulos Odoo y genera reporte por modulo.

Uso:
    python scripts/run_audit.py                    # Audita todos los modulos
    python scripts/run_audit.py Contabilidad       # Solo un modulo
    python scripts/run_audit.py Contabilidad Ventas

Output:
    data/audit_history/audit_<timestamp>.json
    data/audit_history/audit_<timestamp>.md   (reporte legible)
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from rich.console import Console
from rich.table import Table

from src.auditor.module_auditor import MODULE_MODELS, ModuleAuditor
from src.odoo_query import OdooQuery


console = Console(force_terminal=True)


def render_markdown(findings_by_module: dict) -> str:
    """Convierte findings a un reporte Markdown."""
    lines = [f"# Auditoria Odoo - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]

    # Resumen ejecutivo
    total_alto = sum(f["summary"]["by_severity"].get("alto", 0) for f in findings_by_module.values())
    total_medio = sum(f["summary"]["by_severity"].get("medio", 0) for f in findings_by_module.values())
    total_bajo = sum(f["summary"]["by_severity"].get("bajo", 0) for f in findings_by_module.values())

    lines.append("## Resumen ejecutivo\n")
    lines.append(f"- **Alto:** {total_alto}")
    lines.append(f"- **Medio:** {total_medio}")
    lines.append(f"- **Bajo:** {total_bajo}\n")

    # Por modulo
    for module, data in findings_by_module.items():
        lines.append(f"\n## {module}\n")
        for dim_name in ["data_quality", "configuration", "automations", "efficiency", "scalability"]:
            findings = data.get(dim_name, [])
            if not findings:
                continue
            dim_label = {
                "data_quality": "Calidad de datos",
                "configuration": "Configuracion",
                "automations": "Automatizaciones",
                "efficiency": "Eficiencia",
                "scalability": "Escalabilidad",
            }[dim_name]
            lines.append(f"### {dim_label}\n")
            for f in findings:
                sev = f.get("severity", "info").upper()
                lines.append(f"- **[{sev}]** {f.get('title', '')}")
                if f.get("detail"):
                    lines.append(f"  - Detalle: {f['detail']}")
                if f.get("action"):
                    lines.append(f"  - Propuesta: {f['action']}")
                if f.get("items"):
                    lines.append(f"  - Items: {f['items'][:5]}{'...' if len(f.get('items', [])) > 5 else ''}")
            lines.append("")

    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    modules = args if args else list(MODULE_MODELS.keys())

    invalid = [m for m in modules if m not in MODULE_MODELS]
    if invalid:
        console.print(f"[red]Modulos no validos: {invalid}[/red]")
        console.print(f"Disponibles: {list(MODULE_MODELS.keys())}")
        sys.exit(1)

    console.print(f"[bold]Auditando: {modules}[/bold]\n")

    odoo = OdooQuery()
    auditor = ModuleAuditor(odoo)
    results = {}

    for module in modules:
        console.print(f"[cyan]Auditando {module}...[/cyan]")
        results[module] = auditor.audit_module(module)
        s = results[module]["summary"]["by_severity"]
        console.print(f"  -> alto={s.get('alto', 0)} medio={s.get('medio', 0)} "
                      f"bajo={s.get('bajo', 0)} info={s.get('info', 0)}")

    # Persistir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = BASE / "data" / "audit_history"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"audit_{timestamp}.json"
    md_path = out_dir / f"audit_{timestamp}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(results))

    console.print(f"\n[green]Audit guardado:[/green]")
    console.print(f"  {json_path}")
    console.print(f"  {md_path}")

    # Tabla resumen
    table = Table(title="Resumen por modulo")
    table.add_column("Modulo")
    table.add_column("Alto", style="red")
    table.add_column("Medio", style="yellow")
    table.add_column("Bajo")
    for module, data in results.items():
        s = data["summary"]["by_severity"]
        table.add_row(module, str(s.get("alto", 0)), str(s.get("medio", 0)), str(s.get("bajo", 0)))
    console.print(table)


if __name__ == "__main__":
    main()
