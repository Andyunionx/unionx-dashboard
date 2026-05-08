"""Audit log de logins (escribe a Turso)."""
import os
from datetime import datetime
from typing import Optional

import requests


def log_login(usuario: str, exito: bool, ip: Optional[str] = None, user_agent: Optional[str] = None):
    """Registra un intento de login en Turso (tabla audit_logins).
    Falla silenciosamente si no se puede (no bloquea el login)."""
    url = os.environ.get('LIBSQL_URL', '').rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    if not url or not token:
        return

    sql = """INSERT INTO audit_logins (timestamp, usuario, exito, ip, user_agent)
             VALUES (?, ?, ?, ?, ?)"""
    body = {"requests": [{"type": "execute", "stmt": {
        "sql": sql,
        "args": [
            {"type": "text", "value": datetime.now().isoformat()},
            {"type": "text", "value": usuario or "?"},
            {"type": "integer", "value": "1" if exito else "0"},
            {"type": "text", "value": ip or "?"} if ip else {"type": "null"},
            {"type": "text", "value": user_agent[:500] if user_agent else "?"} if user_agent else {"type": "null"},
        ],
    }}, {"type": "close"}]}
    try:
        requests.post(f"{url}/v2/pipeline", json=body,
                     headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                     timeout=10)
    except Exception:
        pass  # No bloqueamos login si falla audit


def get_recent_logins(limit: int = 50):
    """Devuelve últimos N intentos de login."""
    url = os.environ.get('LIBSQL_URL', '').rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    if not url:
        return []
    sql = f"SELECT timestamp, usuario, exito, ip FROM audit_logins ORDER BY timestamp DESC LIMIT {int(limit)}"
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    try:
        r = requests.post(f"{url}/v2/pipeline", json=body,
                         headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                         timeout=15)
        rows = r.json()['results'][0]['response']['result']['rows']
        return [{
            'timestamp': row[0]['value'],
            'usuario': row[1]['value'],
            'exito': bool(int(row[2]['value'])),
            'ip': row[3].get('value') if row[3].get('type') != 'null' else None,
        } for row in rows]
    except Exception:
        return []


def crear_tabla_audit():
    """Crea tabla audit_logins en Turso si no existe (idempotente)."""
    url = os.environ.get('LIBSQL_URL', '').rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    if not url:
        return
    sql = """CREATE TABLE IF NOT EXISTS audit_logins (
        timestamp TEXT NOT NULL,
        usuario TEXT NOT NULL,
        exito INTEGER NOT NULL,
        ip TEXT,
        user_agent TEXT
    )"""
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    try:
        requests.post(f"{url}/v2/pipeline", json=body,
                     headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                     timeout=15)
    except Exception:
        pass
