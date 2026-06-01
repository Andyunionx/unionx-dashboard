"""Envío y lectura de mails para el módulo Distribución."""
from __future__ import annotations
import base64
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.send",
          "https://www.googleapis.com/auth/gmail.readonly"]
ASUNTO_PREFIJO = "[Distribución]"


def _get_service(token_path):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    return build("gmail", "v1", credentials=creds)


def _cuerpo_html(facturas_resumen: list[dict]) -> str:
    filas = "".join(
        f"<tr><td style='padding:6px 12px;border-bottom:1px solid #eee'>{f['proveedor']}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{f['folio']}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{f['fecha']}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:right'>${f['monto_total']:,.0f}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:center'>{f['n_lineas']}</td></tr>"
        for f in facturas_resumen
    )
    return f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<h2 style="color:#1B5E20">📊 Distribución Contable — Propuesta de redistribución</h2>
<p>Hola,</p>
<p>El agente detectó <strong>{len(facturas_resumen)} factura(s)</strong> de proveedores de servicios
que requieren redistribución desde la cuenta <code>42410104</code>.</p>
<table style="border-collapse:collapse;width:100%;margin:16px 0">
  <thead><tr style="background:#37474F;color:white">
    <th style="padding:8px 12px;text-align:left">Proveedor</th>
    <th style="padding:8px 12px;text-align:left">Folio</th>
    <th style="padding:8px 12px;text-align:left">Fecha</th>
    <th style="padding:8px 12px;text-align:right">Total</th>
    <th style="padding:8px 12px;text-align:center">Líneas</th>
  </tr></thead>
  <tbody>{filas}</tbody>
</table>
<h3 style="color:#1B5E20">¿Qué hacer?</h3>
<ol>
  <li>Abrir el Excel adjunto.</li>
  <li>Revisar columna <strong>APROBADO (L)</strong>: escribir <code>SI</code> o <code>NO</code>.</li>
  <li>Si es <code>NO</code>, indicar código de cuenta correcto en columna <strong>M</strong>.</li>
  <li><strong>Responder este correo con el Excel adjunto.</strong></li>
</ol>
<p style="background:#E8F5E9;padding:12px;border-radius:6px;border-left:4px solid #1B5E20">
  El agente leerá la respuesta y aplicará los cambios en Odoo automáticamente.
  Tras 3 aprobaciones iguales del mismo proveedor, el sistema opera automáticamente.
</p>
<p style="color:#666;font-size:12px">— Agente UnionX · {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
</body></html>"""


def send_propuesta(excels: list[Path], facturas_resumen: list[dict],
                   token_path, destinatarios: list[str] = None,
                   cc: list[str] = None) -> dict:
    destinatarios = destinatarios or ["camila@unionx.cl", "victor@unionx.cl"]
    cc = cc or ["andres@unionx.cl"]
    fecha_str = datetime.now().strftime("%d-%b-%Y")
    asunto = f"{ASUNTO_PREFIJO} Propuesta redistribución — {len(excels)} factura(s) — {fecha_str}"

    msg = MIMEMultipart("mixed")
    msg["To"] = ", ".join(destinatarios)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = asunto
    msg.attach(MIMEText(_cuerpo_html(facturas_resumen), "html", "utf-8"))

    for excel_path in excels:
        with open(excel_path, "rb") as f:
            part = MIMEApplication(f.read(),
                _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            part["Content-Disposition"] = f'attachment; filename="{Path(excel_path).name}"'
            msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        service = _get_service(token_path)
        r = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "message_id": r.get("id"), "error": None}
    except Exception as e:
        return {"ok": False, "message_id": None, "error": str(e)}


def leer_respuestas(token_path, desde_horas: int = 48) -> list[dict]:
    service = _get_service(token_path)
    despues = (datetime.now() - timedelta(hours=desde_horas)).strftime("%Y/%m/%d")
    query = f'subject:"{ASUNTO_PREFIJO}" has:attachment after:{despues}'
    resultados = service.users().messages().list(userId="me", q=query, maxResults=20).execute()
    mensajes = resultados.get("messages", [])
    encontrados = []

    for msg_ref in mensajes:
        msg = service.users().messages().get(userId="me", id=msg_ref["id"], format="full").execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender = headers.get("From", "")
        if not any(x in sender for x in ["camila@", "victor@"]):
            continue
        adjuntos = _extraer_adjuntos(service, msg)
        xlsx_adjuntos = [a for a in adjuntos if a["nombre"].endswith(".xlsx")]
        if xlsx_adjuntos:
            encontrados.append({
                "message_id": msg_ref["id"],
                "sender": sender,
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "adjuntos": xlsx_adjuntos,
            })
    return encontrados


def _extraer_adjuntos(service, msg: dict) -> list[dict]:
    adjuntos = []
    def _procesar(partes):
        for parte in partes:
            if parte.get("filename") and parte.get("body"):
                body = parte["body"]
                if body.get("attachmentId"):
                    att = service.users().messages().attachments().get(
                        userId="me", messageId=msg["id"], id=body["attachmentId"]).execute()
                    datos = base64.urlsafe_b64decode(att["data"])
                else:
                    datos = base64.urlsafe_b64decode(body.get("data", ""))
                adjuntos.append({"nombre": parte["filename"], "contenido_bytes": datos})
            if parte.get("parts"):
                _procesar(parte["parts"])
    payload = msg.get("payload", {})
    if payload.get("parts"):
        _procesar(payload["parts"])
    return adjuntos
