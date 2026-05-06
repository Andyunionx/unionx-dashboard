"""
Wrapper compartido para envio de emails desde cualquier parte del proyecto.

Reutiliza GmailClient de agente-comex (no duplica integracion). Provee
helpers de alto nivel para los casos de uso comunes:
- enviar_reporte_ceo(reportes, resumen_html)
- enviar_alerta(alerta)

Respeta la env var GMAIL_DRY_RUN=1 para crear borradores en lugar de enviar.

Configuracion via variables de entorno (recomendado: env vars de Windows User):
- CEO_EMAIL: destinatario principal de reportes ejecutivos (default: andres@unionx.cl)
- CEO_CC: copias adicionales separadas por coma
- ALERT_EMAIL_TO: destinatario de alertas (default: andres@unionx.cl)
"""
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "agente-comex"))

from src.gmail_client import GmailClient  # noqa: E402

_client: Optional[GmailClient] = None


def _get_client() -> GmailClient:
    global _client
    if _client is None:
        _client = GmailClient()
    return _client


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def enviar_reporte_ceo(
    asunto: str,
    cuerpo_html: str,
    adjuntos: Optional[Iterable[str]] = None,
) -> str:
    """Envia (o crea draft) reporte ejecutivo al CEO.

    Args:
        asunto: subject del email
        cuerpo_html: HTML body
        adjuntos: paths a archivos a adjuntar

    Returns:
        ID del mensaje enviado o "[DRAFT] {id}" si DRY_RUN.
    """
    to = os.environ.get("CEO_EMAIL", "andres@unionx.cl")
    cc = _split_csv(os.environ.get("CEO_CC"))

    client = _get_client()
    return client.send_email_with_attachments(
        to=to,
        subject=asunto,
        body_html=cuerpo_html,
        attachments=list(adjuntos) if adjuntos else None,
        cc=cc or None,
    )


def enviar_alerta(
    nombre: str,
    urgencia: str,
    cuerpo_html: str,
    adjuntos: Optional[Iterable[str]] = None,
) -> str:
    """Envia (o crea draft) email de alerta.

    Args:
        nombre: nombre corto de la alerta
        urgencia: CRITICA / MODERADA / INFO
        cuerpo_html: HTML body con detalle
        adjuntos: paths opcionales a archivos
    """
    to = os.environ.get("ALERT_EMAIL_TO", "andres@unionx.cl")
    asunto = f"[ALERTA {urgencia.upper()}] {nombre} — UnionX"

    client = _get_client()
    return client.send_email_with_attachments(
        to=to,
        subject=asunto,
        body_html=cuerpo_html,
        attachments=list(adjuntos) if adjuntos else None,
    )
