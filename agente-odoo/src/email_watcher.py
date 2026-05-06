"""
Email watcher - Monitorea Gmail buscando mails con dudas/solicitudes Odoo.

Reusa el GmailClient de agente-comex (mismo token Gmail).
"""
import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional

# Reusa GmailClient de agente-comex
AGENTE_COMEX = Path(__file__).parent.parent.parent / "agente-comex"
sys.path.insert(0, str(AGENTE_COMEX))
from src.gmail_client import GmailClient  # type: ignore  # noqa: E402

from .config_loader import load_config, load_triggers


class EmailWatcher:
    """Polling Gmail con filtros de keywords Odoo."""

    def __init__(self, gmail: GmailClient):
        self.gmail = gmail
        self.config = load_config()
        self.triggers = load_triggers()
        self.poll_interval = self.config["gmail"]["poll_interval_seconds"]
        self.scan_from = self.config["gmail"]["scan_from_date"]
        self.allowed_senders = self.config["allowed_senders"]
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compila regex para eficiencia."""
        self.exclude_re = [
            re.compile(p, re.IGNORECASE)
            for p in self.triggers.get("exclude_subject_patterns", [])
        ]

    def _sender_allowed(self, from_header: str) -> bool:
        """True si el remitente esta en allowed_senders."""
        from_header = from_header.lower()
        return any(domain.lower() in from_header for domain in self.allowed_senders)

    def _is_excluded(self, subject: str) -> bool:
        """True si el subject matchea un patron de exclusion."""
        return any(p.search(subject) for p in self.exclude_re)

    def _matches_keywords(self, subject: str, body: str) -> Optional[list[str]]:
        """Retorna lista de keywords que matchearon, o None si nada matcheo."""
        subject_l = subject.lower()
        body_l = body.lower()
        matched = []
        for kw in self.triggers.get("keywords_subject", []):
            if kw.lower() in subject_l:
                matched.append(f"subject:{kw}")
        for kw in self.triggers.get("keywords_body", []):
            if kw.lower() in body_l:
                matched.append(f"body:{kw}")
        return matched or None

    def _has_skip_label(self, label_ids: list[str]) -> bool:
        """True si el mail tiene un label de 'ya procesado'."""
        skip_names = set(self.triggers.get("skip_labels", []))
        # Necesitamos resolver label_ids -> names. Por simplicidad, uso label cache.
        return any(lid in self._skip_label_ids for lid in label_ids)

    def _resolve_skip_labels(self):
        """Resuelve nombres de skip_labels a sus IDs en Gmail."""
        results = self.gmail.service.users().labels().list(userId="me").execute()
        skip_names = set(self.triggers.get("skip_labels", []))
        self._skip_label_ids = {
            lab["id"] for lab in results.get("labels", []) if lab["name"] in skip_names
        }

    def _get_email_body(self, msg_id: str) -> str:
        """Extrae el cuerpo (texto plano) de un email."""
        msg = self.gmail.service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()

        def walk_parts(parts):
            for p in parts:
                if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
                    import base64
                    return base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", errors="replace")
                if p.get("parts"):
                    sub = walk_parts(p["parts"])
                    if sub:
                        return sub
            return ""

        payload = msg["payload"]
        if payload.get("body", {}).get("data"):
            import base64
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        if payload.get("parts"):
            return walk_parts(payload["parts"])
        return ""

    def scan_once(self) -> list[dict]:
        """
        Escanea Gmail una vez y retorna los mails candidatos.

        Cada candidato es un dict con:
            id, thread_id, from, subject, body, snippet, date, matched_keywords
        """
        self._resolve_skip_labels()

        # Query base: no-leidos despues de scan_from
        query = f"is:unread after:{self.scan_from}"
        results = self.gmail.service.users().messages().list(
            userId="me", q=query, maxResults=50
        ).execute()

        candidates = []
        for msg_ref in results.get("messages", []):
            detail = self.gmail.get_email_detail(msg_ref["id"])
            if not detail:
                continue

            # Filtro 1: skip si tiene label de procesado
            if self._has_skip_label(detail.get("label_ids", [])):
                continue

            # Filtro 2: sender en whitelist de dominios
            if not self._sender_allowed(detail.get("from", "")):
                continue

            # Filtro 3: subject no esta en exclude_patterns
            if self._is_excluded(detail.get("subject", "")):
                continue

            # Filtro 4: keywords matchean
            body = self._get_email_body(msg_ref["id"])
            matched = self._matches_keywords(detail.get("subject", ""), body)
            if not matched:
                continue

            detail["body"] = body
            detail["matched_keywords"] = matched
            candidates.append(detail)

        return candidates

    def run(self, on_candidate: Callable[[dict], None]):
        """Loop infinito de polling. Llama on_candidate(mail) por cada match."""
        print(f"[WATCHER] Polling cada {self.poll_interval}s. Ctrl+C para detener.")
        while True:
            try:
                candidates = self.scan_once()
                if candidates:
                    print(f"[WATCHER] {len(candidates)} candidato(s) detectado(s)")
                    for c in candidates:
                        on_candidate(c)
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[WATCHER ERROR] {e}. Reintentando en {self.poll_interval}s...")
                time.sleep(self.poll_interval)
