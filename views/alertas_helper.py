"""
Bus de alertas compartidas entre Ventas y Operaciones (Turso).

USO desde Ventas/Ops/Cron:
    from views.alertas_helper import crear_alerta, listar_alertas, marcar_resuelta

    crear_alerta(
        tipo='venta_bajo_forecast',
        severity='warning',
        titulo='Mercado Libre cayó 32% vs forecast',
        mensaje='Mayo proyectaba $250M, va $170M (-32%)',
        contexto={'canal': 'Mercado Libre', 'actual': 170e6, 'forecast': 250e6},
        target_apps=['ventas', 'operaciones'],
    )

    abiertas = listar_alertas(target_app='ventas', status='open')
    marcar_resuelta(id=42, usuario='andres')

ESTRUCTURA DE LA TABLA (autocreada):
    id INTEGER PRIMARY KEY
    fecha_creada TEXT NOT NULL
    fecha_objetivo TEXT
    tipo TEXT NOT NULL
    severity TEXT NOT NULL  -- 'info' | 'warning' | 'critical'
    titulo TEXT NOT NULL
    mensaje TEXT
    contexto TEXT  -- JSON serializado
    target_apps TEXT  -- 'ventas,operaciones' CSV
    status TEXT  -- 'open' | 'reconocida' | 'resuelta'
    resuelta_por TEXT
    fecha_resuelta TEXT
"""
import json
import os
from datetime import datetime
from typing import List, Optional

import requests


def _get_url_token():
    url = os.environ.get('LIBSQL_URL', '').rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    return url, token


def _query(sql: str, args: list = None, timeout: int = 60):
    """Ejecuta query Turso. Si Turso falla (cuota, network, etc) devuelve None
    en lugar de tirar excepción. Callers deben manejar None como "no data"."""
    url, token = _get_url_token()
    if not url:
        return None

    request_args = []
    if args:
        for v in args:
            if v is None:
                request_args.append({"type": "null"})
            elif isinstance(v, bool):
                request_args.append({"type": "integer", "value": "1" if v else "0"})
            elif isinstance(v, int):
                request_args.append({"type": "integer", "value": str(v)})
            elif isinstance(v, float):
                request_args.append({"type": "float", "value": v})
            else:
                request_args.append({"type": "text", "value": str(v)})

    body = {"requests": [{"type": "execute", "stmt": {"sql": sql, "args": request_args}}, {"type": "close"}]}
    try:
        r = requests.post(
            f"{url}/v2/pipeline", json=body,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            timeout=timeout,
        )
        r.raise_for_status()
        result = r.json().get('results', [{}])[0]
        # Si Turso devuelve {type: error, error: {...}}, no hay 'response'
        if result.get('type') == 'error' or 'response' not in result:
            err_msg = result.get('error', {}).get('message', 'unknown')[:80]
            print(f"[alertas_helper._query] Turso bloqueado/error: {err_msg}", flush=True)
            return None
        return result['response']['result']
    except (requests.exceptions.RequestException, KeyError, ValueError) as e:
        print(f"[alertas_helper._query] {type(e).__name__}: {str(e)[:80]}", flush=True)
        return None


def crear_tabla_alertas():
    """Crea tabla alertas en Turso si no existe (idempotente)."""
    sql = """CREATE TABLE IF NOT EXISTS alertas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_creada TEXT NOT NULL,
        fecha_objetivo TEXT,
        tipo TEXT NOT NULL,
        severity TEXT NOT NULL,
        titulo TEXT NOT NULL,
        mensaje TEXT,
        contexto TEXT,
        target_apps TEXT,
        status TEXT DEFAULT 'open',
        resuelta_por TEXT,
        fecha_resuelta TEXT
    )"""
    try:
        _query(sql)
        # Índices para queries comunes
        _query("CREATE INDEX IF NOT EXISTS idx_alertas_status ON alertas(status)")
        _query("CREATE INDEX IF NOT EXISTS idx_alertas_severity ON alertas(severity)")
        _query("CREATE INDEX IF NOT EXISTS idx_alertas_fecha ON alertas(fecha_creada)")
    except Exception as e:
        print(f"[WARN] crear_tabla_alertas: {e}")


def crear_alerta(tipo: str, severity: str, titulo: str,
                 mensaje: str = "",
                 contexto: dict = None,
                 target_apps: List[str] = None,
                 fecha_objetivo: str = None,
                 deduplicate: bool = True) -> Optional[int]:
    """Inserta una alerta. Devuelve el ID generado.

    Si deduplicate=True (default), busca alertas open del mismo tipo+titulo
    de hoy y las actualiza en lugar de duplicar.
    """
    if severity not in ('info', 'warning', 'critical'):
        severity = 'info'
    target_apps_str = ','.join(target_apps) if target_apps else 'ventas,operaciones'
    contexto_str = json.dumps(contexto, default=str) if contexto else None

    # Deduplicación: si ya existe alerta open del mismo tipo+título HOY, no duplicar
    if deduplicate:
        try:
            hoy = datetime.now().strftime('%Y-%m-%d')
            existing = _query(
                "SELECT id FROM alertas WHERE tipo=? AND titulo=? AND status='open' AND fecha_creada >= ? LIMIT 1",
                [tipo, titulo, hoy],
            )
            if existing and existing.get('rows'):
                # Actualizar mensaje/contexto en la alerta existente
                row_id = int(existing['rows'][0][0]['value'])
                _query(
                    "UPDATE alertas SET mensaje=?, contexto=?, fecha_creada=? WHERE id=?",
                    [mensaje, contexto_str, datetime.now().isoformat(), row_id],
                )
                return row_id
        except Exception:
            pass

    # Crear nueva
    res = _query("""
        INSERT INTO alertas (fecha_creada, fecha_objetivo, tipo, severity, titulo, mensaje, contexto, target_apps, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
    """, [
        datetime.now().isoformat(),
        fecha_objetivo,
        tipo, severity, titulo, mensaje, contexto_str, target_apps_str,
    ])
    if res and 'last_insert_rowid' in res:
        return int(res['last_insert_rowid'])
    return None


def listar_alertas(target_app: str = None,
                   status: str = 'open',
                   severity: str = None,
                   limit: int = 100) -> List[dict]:
    """Lista alertas con filtros opcionales."""
    clauses = []
    args = []
    if target_app:
        clauses.append("target_apps LIKE ?")
        args.append(f"%{target_app}%")
    if status:
        clauses.append("status = ?")
        args.append(status)
    if severity:
        clauses.append("severity = ?")
        args.append(severity)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"SELECT id, fecha_creada, fecha_objetivo, tipo, severity, titulo, mensaje, contexto, target_apps, status FROM alertas{where} ORDER BY severity DESC, fecha_creada DESC LIMIT {int(limit)}"

    try:
        res = _query(sql, args)
    except Exception as e:
        print(f"[WARN] listar_alertas: {e}")
        return []

    if not res or not res.get('rows'):
        return []

    out = []
    for row in res['rows']:
        def _val(idx):
            cell = row[idx]
            return cell.get('value') if cell.get('type') != 'null' else None
        ctx_raw = _val(7)
        try:
            ctx = json.loads(ctx_raw) if ctx_raw else {}
        except Exception:
            ctx = {}
        out.append({
            'id': int(_val(0)),
            'fecha_creada': _val(1),
            'fecha_objetivo': _val(2),
            'tipo': _val(3),
            'severity': _val(4),
            'titulo': _val(5),
            'mensaje': _val(6),
            'contexto': ctx,
            'target_apps': _val(8),
            'status': _val(9),
        })
    return out


def marcar_resuelta(id_alerta: int, usuario: str, status: str = 'resuelta'):
    """Cambia status de una alerta. status: 'reconocida' | 'resuelta'."""
    if status not in ('reconocida', 'resuelta'):
        status = 'resuelta'
    try:
        _query("""
            UPDATE alertas
            SET status=?, resuelta_por=?, fecha_resuelta=?
            WHERE id=?
        """, [status, usuario, datetime.now().isoformat(), id_alerta])
        return True
    except Exception as e:
        print(f"[WARN] marcar_resuelta: {e}")
        return False


def contar_abiertas(target_app: str = None) -> dict:
    """Devuelve dict con conteo por severity."""
    clauses = ["status='open'"]
    args = []
    if target_app:
        clauses.append("target_apps LIKE ?")
        args.append(f"%{target_app}%")
    where = " WHERE " + " AND ".join(clauses)
    try:
        res = _query(f"SELECT severity, COUNT(*) FROM alertas{where} GROUP BY severity", args)
        if not res or not res.get('rows'):
            return {'critical': 0, 'warning': 0, 'info': 0, 'total': 0}
        d = {'critical': 0, 'warning': 0, 'info': 0}
        for row in res['rows']:
            sev = row[0].get('value', 'info')
            n = int(row[1].get('value', 0))
            d[sev] = n
        d['total'] = sum(d.values())
        return d
    except Exception:
        return {'critical': 0, 'warning': 0, 'info': 0, 'total': 0}
