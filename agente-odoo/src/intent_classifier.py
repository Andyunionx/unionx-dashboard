"""
Intent classifier - Usa Claude API para entender que pide el mail
y mapearlo a un intent estructurado que el executor pueda accionar.

Output: dict con
    intent_name: nombre canonical (ej. "sii_status_fix") o "unknown"
    odoo_module: modulo Odoo afectado (ej. "Contabilidad")
    entities: dict con datos extraidos (ej. cantidad de docs, folios mencionados)
    confidence: alta/media/baja
    summary: resumen humano de lo que pide
    requested_by: nombre del solicitante
"""
import json
import os
from typing import Optional

import anthropic

from .config_loader import load_allowed_actions, load_config


SYSTEM_PROMPT = """Eres un clasificador de solicitudes Odoo para UnionX (operacion logistica chilena).

Tu unica tarea: leer un email y clasificarlo en un intent estructurado JSON.

Intents disponibles (whitelist del executor):
{intents_block}

Si la solicitud NO corresponde a ningun intent de la whitelist, usa "unknown".

Modulos Odoo posibles: Contabilidad, Ventas, Compras, Inventario, Manufactura, CRM, Empleados, Sitio web, Otro.

Responde SOLO con un JSON valido, sin texto adicional, sin markdown fences. Schema:
{{
  "intent_name": "string",
  "odoo_module": "string",
  "entities": {{}},
  "confidence": "alta|media|baja",
  "summary": "string en espanol chileno, 1-2 lineas",
  "requested_by": "string (nombre o email del solicitante)",
  "reasoning": "string corto en espanol explicando por que este intent"
}}
"""


class IntentClassifier:
    def __init__(self):
        self.config = load_config()
        self.allowed_actions = load_allowed_actions()
        self.model = self.config["claude"]["model"]
        self.max_tokens = self.config["claude"]["max_tokens"]

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Falta ANTHROPIC_API_KEY en el entorno. "
                "Configurar en .env o variable de entorno."
            )
        self.client = anthropic.Anthropic(api_key=api_key)

    def _build_intents_block(self) -> str:
        """Genera la lista de intents para inyectar al system prompt."""
        lines = []
        for name, spec in self.allowed_actions.get("actions", {}).items():
            lines.append(f"- {name}: {spec.get('description', '')}")
        lines.append('- unknown: la solicitud no coincide con ninguna accion de la whitelist')
        return "\n".join(lines)

    def classify(self, email: dict) -> dict:
        """
        Clasifica el email y retorna intent estructurado.

        Args:
            email: dict con keys 'subject', 'body', 'from'
        """
        system = SYSTEM_PROMPT.format(intents_block=self._build_intents_block())

        user_msg = (
            f"De: {email.get('from', '')}\n"
            f"Asunto: {email.get('subject', '')}\n\n"
            f"Cuerpo:\n{email.get('body', '')[:4000]}"
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )

        text = response.content[0].text.strip()
        # Limpiar fences en caso que Claude los agregue igual
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            return {
                "intent_name": "unknown",
                "odoo_module": "Otro",
                "entities": {},
                "confidence": "baja",
                "summary": "No se pudo parsear la clasificacion",
                "requested_by": email.get("from", ""),
                "reasoning": f"JSON invalido: {e}. Raw: {text[:200]}",
            }
