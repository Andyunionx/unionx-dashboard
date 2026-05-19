"""Helper Gmail API con OAuth user flow.

Permite:
  - Descargar adjuntos de mensajes (resuelve limitación MCP)
  - Enviar mails directamente (sin pasar por draft)

SETUP INICIAL (una sola vez):
  1. Ve a https://console.cloud.google.com/apis/credentials → +CREATE CREDENTIALS → OAuth client ID
  2. Application type: Desktop app, nombre "UnionX Gmail Helper"
  3. Descarga el JSON → guárdalo como `gmail_oauth_client.json` en la raíz del proyecto
  4. Habilita Gmail API en el proyecto Google Cloud
  5. Corre: python gmail_helper.py auth
  6. Se abre navegador → da consent con tu cuenta andres@unionx.cl
  7. Token queda guardado en `gmail_token.json` (gitignored)

USO PROGRAMÁTICO:
  from gmail_helper import download_attachment, send_mail, get_service
  download_attachment(msg_id, att_id, '/path/to/save.pdf')
  send_mail(to=['x@y.cl'], cc=['z@w.cl'], subject='Hola', body='...')
"""
import base64
import json
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent
CLIENT_PATH = PROJECT_ROOT / 'gmail_oauth_client.json'
TOKEN_PATH = PROJECT_ROOT / 'gmail_token.json'

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
]


def get_service():
    """Devuelve service Gmail API autenticado. OAuth user flow."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_PATH.exists():
                raise FileNotFoundError(
                    f"Falta {CLIENT_PATH}. Descarga OAuth client ID Desktop "
                    f"desde Google Cloud Console y guárdalo allí."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding='utf-8')

    return build('gmail', 'v1', credentials=creds)


def download_attachment(message_id: str, attachment_id: str, save_path: str | Path) -> Path:
    """Descarga un adjunto de Gmail por su ID. Devuelve el path guardado."""
    svc = get_service()
    att = svc.users().messages().attachments().get(
        userId='me', messageId=message_id, id=attachment_id
    ).execute()
    data = base64.urlsafe_b64decode(att['data'].encode('UTF-8'))
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(data)
    return save_path


def download_all_attachments(message_id: str, save_dir: str | Path) -> list:
    """Descarga todos los adjuntos de un mensaje a la carpeta indicada. Devuelve lista de paths."""
    svc = get_service()
    msg = svc.users().messages().get(userId='me', id=message_id).execute()
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    def _walk(parts):
        for p in parts:
            if p.get('filename') and p.get('body', {}).get('attachmentId'):
                fname = p['filename']
                att_id = p['body']['attachmentId']
                path = download_attachment(message_id, att_id, save_dir / fname)
                paths.append(path)
                print(f"  ↓ {fname} ({path.stat().st_size:,} bytes)", flush=True)
            if p.get('parts'):
                _walk(p['parts'])

    payload = msg.get('payload', {})
    _walk([payload] + payload.get('parts', []))
    return paths


def send_mail(to: list[str], subject: str, body: str,
              cc: list[str] | None = None, bcc: list[str] | None = None,
              attachments: list[str | Path] | None = None,
              html_body: str | None = None) -> str:
    """Envía mail directamente (no draft). Devuelve message ID."""
    svc = get_service()

    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        for att_path in attachments:
            att_path = Path(att_path)
            with open(att_path, 'rb') as f:
                from email.mime.base import MIMEBase
                from email import encoders
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{att_path.name}"')
            msg.attach(part)
    else:
        msg = MIMEText(body, 'plain', 'utf-8')

    msg['to'] = ', '.join(to)
    if cc:
        msg['cc'] = ', '.join(cc)
    if bcc:
        msg['bcc'] = ', '.join(bcc)
    msg['subject'] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = svc.users().messages().send(userId='me', body={'raw': raw}).execute()
    return sent['id']


def main():
    """CLI: python gmail_helper.py auth — fuerza el flow OAuth para guardar token."""
    if len(sys.argv) > 1 and sys.argv[1] == 'auth':
        # Borrar token viejo para forzar re-auth
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink()
        svc = get_service()
        # Test: get profile
        profile = svc.users().getProfile(userId='me').execute()
        print(f"\n[OK] Autenticado como: {profile['emailAddress']}")
        print(f"     Token guardado en: {TOKEN_PATH}")
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
