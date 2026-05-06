"""
Dispatcher del executor. Aplica las 3 reglas duras:

  1. Whitelist: solo ejecuta intents pre-aprobados en allowed_actions.yaml
  2. Dry-run obligatorio antes de ejecutar
  3. Audit trail JSONL en data/odoo_actions_log.jsonl

Nunca llamar directamente al cliente Odoo desde otra parte del agente
para escribir - siempre pasar por aca.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config_loader import load_allowed_actions, load_config
from .actions import sii_status_fix


# Registro central de implementaciones de acciones
ACTION_REGISTRY = {
    "sii_status_fix": sii_status_fix,
}


class ExecutionResult:
    """Resultado de una ejecucion (dry-run o real)."""

    def __init__(
        self,
        intent_name: str,
        mode: str,  # "dry-run" | "executed" | "skipped"
        status: str,  # "ok" | "error" | "skipped"
        records_affected: list[dict],
        message: str,
        error: Optional[str] = None,
    ):
        self.intent_name = intent_name
        self.mode = mode
        self.status = status
        self.records_affected = records_affected
        self.message = message
        self.error = error
        self.timestamp = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "intent_name": self.intent_name,
            "mode": self.mode,
            "status": self.status,
            "records_affected": self.records_affected,
            "message": self.message,
            "error": self.error,
        }


class Dispatcher:
    """Punto unico de entrada para ejecutar acciones en Odoo."""

    def __init__(self, odoo_query):
        self.config = load_config()
        self.allowed = load_allowed_actions()["actions"]
        self.execute_mode = self.config["executor"]["execute_mode"]
        self.log_path = Path(__file__).parent.parent.parent / self.config["executor"]["log_path"]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.odoo_query = odoo_query

    def dispatch(self, intent: dict, source_email: dict) -> ExecutionResult:
        """
        Ejecuta (o simula) la accion correspondiente al intent.

        Args:
            intent: output del IntentClassifier
            source_email: el mail original (para audit trail)
        """
        intent_name = intent.get("intent_name", "unknown")

        # Regla 1: Whitelist
        if intent_name == "unknown" or intent_name not in self.allowed:
            result = ExecutionResult(
                intent_name=intent_name,
                mode="skipped",
                status="skipped",
                records_affected=[],
                message=f"Intent '{intent_name}' no esta en whitelist. "
                        "Generando solo borrador en modo consulta.",
            )
            self._write_log(result, source_email, intent)
            return result

        # Regla 2: Dry-run primero
        action_module = ACTION_REGISTRY.get(intent_name)
        if action_module is None:
            return ExecutionResult(
                intent_name=intent_name,
                mode="skipped",
                status="error",
                records_affected=[],
                message="Intent en whitelist pero falta implementacion en ACTION_REGISTRY",
                error="not_implemented",
            )

        spec = self.allowed[intent_name]

        # Dry-run: simular y registrar
        try:
            dry = action_module.dry_run(self.odoo_query, intent, spec)
        except Exception as e:
            return ExecutionResult(
                intent_name=intent_name,
                mode="dry-run",
                status="error",
                records_affected=[],
                message="Error durante dry-run",
                error=str(e),
            )

        # Si execute_mode=false o requiere confirmacion humana, parar aca
        if not self.execute_mode:
            result = ExecutionResult(
                intent_name=intent_name,
                mode="dry-run",
                status="ok",
                records_affected=dry,
                message=f"DRY-RUN OK. {len(dry)} registro(s) a modificar. "
                        "EXECUTE_MODE=false: no se ejecuta.",
            )
            self._write_log(result, source_email, intent)
            return result

        if spec.get("require_human_confirmation", True):
            result = ExecutionResult(
                intent_name=intent_name,
                mode="dry-run",
                status="ok",
                records_affected=dry,
                message=f"DRY-RUN OK. {len(dry)} registro(s) a modificar. "
                        "Accion requiere confirmacion humana antes de ejecutar.",
            )
            self._write_log(result, source_email, intent)
            return result

        # Ejecucion real
        try:
            executed = action_module.execute(self.odoo_query, intent, spec, dry)
            result = ExecutionResult(
                intent_name=intent_name,
                mode="executed",
                status="ok",
                records_affected=executed,
                message=f"EJECUTADO. {len(executed)} registro(s) modificados en Odoo.",
            )
        except Exception as e:
            result = ExecutionResult(
                intent_name=intent_name,
                mode="executed",
                status="error",
                records_affected=dry,
                message="Error durante ejecucion. El log dry-run tiene el plan que fallo.",
                error=str(e),
            )

        self._write_log(result, source_email, intent)
        return result

    def _write_log(self, result: ExecutionResult, source_email: dict, intent: dict):
        """Append-only JSONL audit trail."""
        entry = {
            **result.to_dict(),
            "source_email": {
                "id": source_email.get("id"),
                "from": source_email.get("from"),
                "subject": source_email.get("subject"),
                "date": source_email.get("date"),
            },
            "intent_full": intent,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
