"""
Capa de conexión DB unificada: SQLite local + Turso (libSQL) cloud.

Modos:
- LOCAL: si LIBSQL_URL no está seteado → usa sqlite3 contra archivo local
- CLOUD: si LIBSQL_URL='libsql://...' → usa libsql-client contra Turso (vía HTTPS)

API uniforme tipo sqlite3.Connection:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT ...", params).fetchall()
    row[0], row['canal']  # ambos accesos funcionan
    conn.commit() / conn.close()
"""
import os
import sqlite3
from pathlib import Path


def get_connection(db_path, libsql_url: str = None, auth_token: str = None):
    """
    Devuelve conexión al DB.
    Si LIBSQL_URL está en env (o param), usa Turso. Si no, sqlite3 local.
    """
    libsql_url = libsql_url or os.environ.get('LIBSQL_URL')
    auth_token = auth_token or os.environ.get('LIBSQL_AUTH_TOKEN')

    if libsql_url and libsql_url.strip() and libsql_url.startswith(('libsql://', 'https://', 'wss://')):
        try:
            import libsql_client
            client = libsql_client.create_client_sync(
                url=libsql_url,
                auth_token=auth_token or '',
            )
            return _LibsqlAdapter(client)
        except ImportError:
            print("[WARN] libsql-client no instalado, fallback a sqlite3 local")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


class _LibsqlAdapter:
    """Adaptador que hace que libsql_client se comporte como sqlite3.Connection."""
    def __init__(self, client):
        self._client = client
        self._tx = None

    def execute(self, sql, params=()):
        result = self._client.execute(sql, list(params) if params else [])
        return _LibsqlResult(result)

    def cursor(self):
        return _LibsqlCursor(self._client)

    def commit(self):
        pass  # libsql-client autocommit por default

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass


class _LibsqlCursor:
    def __init__(self, client):
        self._client = client
        self._result = None

    def execute(self, sql, params=()):
        self._result = self._client.execute(sql, list(params) if params else [])
        return self

    def executemany(self, sql, params_list):
        self._client.batch([(sql, list(p)) for p in params_list])
        return self

    def fetchall(self):
        if self._result is None:
            return []
        return [_Row(self._result.columns, list(row)) for row in self._result.rows]

    def fetchone(self):
        if self._result is None or not self._result.rows:
            return None
        return _Row(self._result.columns, list(self._result.rows[0]))

    @property
    def rowcount(self):
        if self._result is None:
            return -1
        return self._result.rows_affected if hasattr(self._result, 'rows_affected') else len(self._result.rows)

    @property
    def description(self):
        if self._result is None:
            return []
        return [(c, None, None, None, None, None, None) for c in self._result.columns]


class _LibsqlResult:
    """Wraps libsql ResultSet para que tenga fetchone/fetchall."""
    def __init__(self, result):
        self._result = result
        self._index = 0

    def fetchall(self):
        return [_Row(self._result.columns, list(row)) for row in self._result.rows]

    def fetchone(self):
        rows = self._result.rows
        if self._index >= len(rows):
            return None
        row = rows[self._index]
        self._index += 1
        return _Row(self._result.columns, list(row))


class _Row:
    """Imita sqlite3.Row: acceso por índice y por nombre de columna."""
    def __init__(self, cols, values):
        self._cols = list(cols)
        self._values = list(values)
        self._map = {c: i for i, c in enumerate(self._cols)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._map[key]]

    def keys(self):
        return list(self._cols)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


def get_db_path():
    """Path canonical del SQLite local. Override con DB_PATH env si existe."""
    p = os.environ.get('DB_PATH')
    if p:
        return Path(p)
    return Path(__file__).parent / 'data' / 'db' / 'maestra_ventas.db'
