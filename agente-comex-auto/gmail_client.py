"""
Cliente Gmail API - Lectura de emails, descarga de adjuntos, envío de emails.
"""

import base64
import mimetypes
import os
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from typing import Optional, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).parent  # agente-comex-auto (copia vendorizada, self-contained para el cron cloud)
# Token: primero el de este paquete (lo escribe el workflow desde el secret GMAIL_TOKEN),
# con fallback al del agente viejo para correr en local.
_TOKEN_CANDIDATES = [
    BASE_DIR / "config" / "token.json",
    BASE_DIR.parent / "agente-comex" / "config" / "token.json",
]
TOKEN_FILE = next((p for p in _TOKEN_CANDIDATES if p.exists()), _TOKEN_CANDIDATES[0])
CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailClient:
    """Wrapper para la API de Gmail."""

    def __init__(self):
        self.service = self._authenticate()

    def _authenticate(self):
        """Autentica con OAuth2 y retorna el servicio de Gmail."""
        creds = None

        if TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_FILE), SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def search_emails(
        self,
        sender: str,
        subject: Optional[str] = None,
        after_date: Optional[str] = None,
        has_attachment: bool = True,
        is_unread: bool = True,
        max_results: int = 10,
    ) -> list[dict]:
        """
        Busca emails que coincidan con los criterios.

        Args:
            sender: Email del remitente
            subject: Texto a buscar en el subject
            after_date: Fecha mínima (formato YYYY/MM/DD)
            has_attachment: Solo emails con adjuntos
            is_unread: Solo emails no leídos
            max_results: Máximo de resultados

        Returns:
            Lista de mensajes con id, subject, date, attachments
        """
        query_parts = [f"from:{sender}"]

        if subject:
            query_parts.append(f"subject:({subject})")
        if after_date:
            query_parts.append(f"after:{after_date}")
        if has_attachment:
            query_parts.append("has:attachment")
        if is_unread:
            query_parts.append("is:unread")

        query = " ".join(query_parts)

        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        messages = results.get("messages", [])
        detailed = []

        for msg in messages:
            detail = self.get_email_detail(msg["id"])
            if detail:
                detailed.append(detail)

        return detailed

    def get_email_detail(self, msg_id: str) -> dict:
        """Obtiene detalles completos de un email."""
        msg = (
            self.service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

        # Extraer adjuntos
        attachments = []
        parts = msg["payload"].get("parts", [])
        for part in parts:
            filename = part.get("filename", "")
            if filename:
                attachments.append(
                    {
                        "filename": filename,
                        "attachment_id": part["body"].get("attachmentId"),
                        "mime_type": part.get("mimeType"),
                        "size": part["body"].get("size", 0),
                    }
                )
            # Revisar subpartes (emails multipart)
            for subpart in part.get("parts", []):
                subfn = subpart.get("filename", "")
                if subfn:
                    attachments.append(
                        {
                            "filename": subfn,
                            "attachment_id": subpart["body"].get("attachmentId"),
                            "mime_type": subpart.get("mimeType"),
                            "size": subpart["body"].get("size", 0),
                        }
                    )

        return {
            "id": msg_id,
            "thread_id": msg.get("threadId"),
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
            "attachments": attachments,
            "label_ids": msg.get("labelIds", []),
        }

    def download_attachment(
        self, msg_id: str, attachment_id: str, filename: str, save_dir: str
    ) -> Path:
        """Descarga un adjunto y lo guarda en disco."""
        attachment = (
            self.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=msg_id, id=attachment_id)
            .execute()
        )

        data = base64.urlsafe_b64decode(attachment["data"])
        save_path = Path(save_dir) / filename
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, "wb") as f:
            f.write(data)

        return save_path

    def mark_as_read(self, msg_id: str):
        """Marca un email como leído."""
        self.service.users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    def add_label(self, msg_id: str, label: str):
        """Agrega un label a un email (para tracking)."""
        # Primero verificar/crear label
        label_id = self._get_or_create_label(label)
        self.service.users().messages().modify(
            userId="me", id=msg_id, body={"addLabelIds": [label_id]}
        ).execute()

    def _get_or_create_label(self, label_name: str) -> str:
        """Obtiene o crea un label en Gmail."""
        results = self.service.users().labels().list(userId="me").execute()
        for label in results.get("labels", []):
            if label["name"] == label_name:
                return label["id"]

        # Crear label
        body = {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created = self.service.users().labels().create(userId="me", body=body).execute()
        return created["id"]

    def send_email(self, to: str, subject: str, body_html: str, reply_to_id: Optional[str] = None) -> str:
        """
        Envía un email o crea un borrador.

        Si la env var GMAIL_DRY_RUN=1, en lugar de enviar crea un borrador
        en Gmail (no llega al destinatario). Útil para validar fixes sin
        molestar al forwarder/clientes.

        Args:
            to: Destinatario
            subject: Asunto
            body_html: Cuerpo en HTML
            reply_to_id: Si se proporciona, responde a ese thread

        Returns:
            ID del mensaje enviado o del borrador creado
        """
        message = MIMEText(body_html, "html")
        message["to"] = to
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Modo borrador (test sin enviar)
        if os.environ.get("GMAIL_DRY_RUN") == "1":
            draft = (
                self.service.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw}})
                .execute()
            )
            return f"[DRAFT] {draft['id']}"

        body = {"raw": raw}
        if reply_to_id:
            body["threadId"] = reply_to_id

        sent = (
            self.service.users()
            .messages()
            .send(userId="me", body=body)
            .execute()
        )
        return sent["id"]

    def create_draft(self, to: str, subject: str, body_html: str) -> str:
        """Crea un borrador de email."""
        message = MIMEText(body_html, "html")
        message["to"] = to
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        draft = (
            self.service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )
        return draft["id"]

    def send_email_with_attachments(
        self,
        to: str,
        subject: str,
        body_html: str,
        attachments: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
    ) -> str:
        """Envia email (o draft si GMAIL_DRY_RUN=1) con uno o mas archivos adjuntos.

        Args:
            to: destinatario principal
            subject: asunto
            body_html: cuerpo HTML
            attachments: lista de paths a archivos adjuntos
            cc: lista de copias

        Returns:
            ID del mensaje enviado o "[DRAFT] {id}" si esta en dry-run.
        """
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = ", ".join(cc)

        message.attach(MIMEText(body_html, "html"))

        for path_str in (attachments or []):
            path = Path(path_str)
            if not path.exists():
                continue
            ctype, encoding = mimetypes.guess_type(str(path))
            if ctype is None or encoding is not None:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)
            with open(path, "rb") as f:
                part = MIMEBase(maintype, subtype)
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=path.name)
            message.attach(part)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        if os.environ.get("GMAIL_DRY_RUN") == "1":
            draft = (
                self.service.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw}})
                .execute()
            )
            return f"[DRAFT] {draft['id']}"

        sent = (
            self.service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return sent["id"]
