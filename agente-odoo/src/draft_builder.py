"""
Draft builder - Genera el borrador de respuesta y lo guarda en Gmail Drafts.

Combina:
  - El intent clasificado
  - El resultado del executor (dry-run o ejecutado)
  - Los datos consultados de Odoo

Genera HTML legible para que Andres revise antes de enviar.
"""
import base64
import sys
from email.mime.text import MIMEText
from pathlib import Path

# Reusa GmailClient de agente-comex
AGENTE_COMEX = Path(__file__).parent.parent.parent / "agente-comex"
sys.path.insert(0, str(AGENTE_COMEX))
from src.gmail_client import GmailClient  # type: ignore  # noqa: E402


class DraftBuilder:
    """Construye y guarda borradores en Gmail."""

    def __init__(self, gmail: GmailClient):
        self.gmail = gmail

    # -------- Templates HTML --------

    def _table_records(self, records: list[dict]) -> str:
        """Tabla HTML para mostrar registros afectados."""
        if not records:
            return "<p><em>Sin registros afectados.</em></p>"

        rows = []
        for r in records:
            if r.get("skipped"):
                rows.append(
                    f"<tr style='color:#999'>"
                    f"<td>{r.get('folio', r.get('name', r.get('id')))}</td>"
                    f"<td colspan='3'><em>Omitido: {r.get('reason', '')}</em></td>"
                    f"</tr>"
                )
                continue

            before = r.get("before", {})
            after = r.get("after", {})
            executed_mark = "OK" if r.get("executed") else ""
            error_mark = f" ERROR: {r.get('error', '')}" if r.get("executed") is False and r.get("error") else ""

            rows.append(
                f"<tr>"
                f"<td>{r.get('folio', r.get('name', r.get('id')))}</td>"
                f"<td>{before}</td>"
                f"<td>{after}</td>"
                f"<td>{executed_mark}{error_mark}</td>"
                f"</tr>"
            )

        return f"""
<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px'>
  <thead style='background:#eee'>
    <tr><th>Folio/ID</th><th>Antes</th><th>Despues</th><th>Estado</th></tr>
  </thead>
  <tbody>{''.join(rows)}</tbody>
</table>"""

    def _build_body(self, intent: dict, exec_result, source_email: dict) -> str:
        """Compone el HTML del borrador."""
        intent_name = intent.get("intent_name", "unknown")
        summary = intent.get("summary", "")
        requested_by = intent.get("requested_by", "")
        confidence = intent.get("confidence", "")
        odoo_module = intent.get("odoo_module", "")

        # Cabecera segun el modo
        if exec_result.mode == "executed" and exec_result.status == "ok":
            header = (
                f"<p>Hola,</p>"
                f"<p>Realice el cambio solicitado. {exec_result.message}</p>"
            )
        elif exec_result.mode == "dry-run":
            header = (
                f"<p>Hola,</p>"
                f"<p>Identifique la solicitud. <strong>Pendiente confirmacion humana</strong> "
                f"antes de ejecutar el cambio en Odoo (el agente esta en modo seguro).</p>"
            )
        elif exec_result.status == "skipped":
            header = (
                f"<p>Hola,</p>"
                f"<p>Recibi la consulta pero el agente <strong>no esta autorizado</strong> "
                f"para ejecutar esta accion automaticamente. Aca van los datos relevantes "
                f"para que tomes la decision manual.</p>"
            )
        else:
            header = (
                f"<p>Hola,</p>"
                f"<p>Hubo un problema procesando la solicitud:</p>"
                f"<p><strong>Error:</strong> {exec_result.error or 'desconocido'}</p>"
            )

        body = f"""
{header}

<h4 style='margin-top:20px;color:#333'>Resumen de la solicitud</h4>
<ul>
  <li><strong>Solicitante:</strong> {requested_by}</li>
  <li><strong>Modulo Odoo:</strong> {odoo_module}</li>
  <li><strong>Intent detectado:</strong> {intent_name} (confianza: {confidence})</li>
  <li><strong>Resumen:</strong> {summary}</li>
</ul>

<h4 style='margin-top:20px;color:#333'>Detalle de registros</h4>
{self._table_records(exec_result.records_affected)}

<hr style='margin-top:30px;border:none;border-top:1px solid #ccc'>
<p style='font-size:11px;color:#888'>
  Este borrador fue generado automaticamente por el agente Odoo de UnionX.<br>
  Mail original: "{source_email.get('subject', '')}" de {source_email.get('from', '')}.<br>
  Modo executor: {exec_result.mode} | Estado: {exec_result.status} | Timestamp: {exec_result.timestamp}.
</p>
"""
        return body

    # -------- API publica --------

    def create_reply_draft(
        self,
        source_email: dict,
        intent: dict,
        exec_result,
    ) -> str:
        """
        Crea un borrador de respuesta en Gmail (responde al thread del mail original).
        """
        body_html = self._build_body(intent, exec_result, source_email)
        subject = source_email.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject

        # Para mantenerlo en el mismo thread, necesitamos el thread_id y los headers
        # In-Reply-To y References. Por simplicidad (y porque es un borrador para
        # revision humana), usamos el helper basico de create_draft.
        # Andres al enviar puede ajustar destinatario/CC.
        to = source_email.get("from", "")

        message = MIMEText(body_html, "html")
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        body = {"message": {"raw": raw}}
        # Asociar al thread original para que aparezca en la conversacion
        if source_email.get("thread_id"):
            body["message"]["threadId"] = source_email["thread_id"]

        draft = (
            self.gmail.service.users()
            .drafts()
            .create(userId="me", body=body)
            .execute()
        )
        return draft["id"]

    def mark_email_processed(self, msg_id: str):
        """Etiqueta el mail original para que el watcher no lo reprocese."""
        self.gmail.add_label(msg_id, "ODOO_AGENT_PROCESSED")
