#!/usr/bin/env python3
"""
Backup semanal de Turso → SQLite comprimido.

Genera: data/backups/turso_backup_YYYY-MM-DD.db.zst
Pensado para correr en GitHub Actions semanal y subir como Release asset.
"""
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import zstandard as zstd

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')

if not URL or not TOKEN:
    print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no seteados", flush=True)
    sys.exit(1)

HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}

OUTPUT_DIR = Path(__file__).parent / 'data' / 'backups'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def turso_query(sql, timeout=300):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    r = requests.post(f"{URL}/v2/pipeline", json=body, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()['results'][0]['response']['result']


def list_tables():
    rows = turso_query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")['rows']
    return [r[0]['value'] for r in rows]


def get_create_sql(table):
    rows = turso_query(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")['rows']
    return rows[0][0]['value'] if rows else None


def backup_table_to_sqlite(table, conn_local, chunk=50000):
    """Copia una tabla de Turso a SQLite local en chunks."""
    print(f"  Tabla: {table}", flush=True)

    # Crear schema
    create_sql = get_create_sql(table)
    if create_sql:
        conn_local.execute(create_sql)
        conn_local.commit()

    # Contar
    n_total = int(turso_query(f"SELECT COUNT(*) FROM {table}")['rows'][0][0]['value'] or 0)
    if n_total == 0:
        print(f"    (vacía)", flush=True)
        return 0

    # Obtener cols
    cols_rows = turso_query(f"SELECT * FROM {table} LIMIT 1")
    cols = cols_rows.get('cols') or []
    cols_names = [c['name'] for c in cols] if cols else []

    if not cols_names:
        # Fallback: PRAGMA
        rows = turso_query(f"PRAGMA table_info({table})")['rows']
        cols_names = [r[1]['value'] for r in rows]

    # Dump en chunks por rowid
    last_rowid = 0
    n_done = 0
    placeholders = ','.join(['?'] * len(cols_names))
    insert_sql = f"INSERT INTO {table} ({','.join(cols_names)}) VALUES ({placeholders})"

    while True:
        rows = turso_query(
            f"SELECT rowid, {','.join(cols_names)} FROM {table} "
            f"WHERE rowid > {last_rowid} ORDER BY rowid LIMIT {chunk}"
        )['rows']
        if not rows:
            break
        flat = []
        for r in rows:
            vals = [c.get('value') if isinstance(c, dict) else c for c in r]
            last_rowid = int(vals[0])
            flat.append(tuple(vals[1:]))
        conn_local.executemany(insert_sql, flat)
        conn_local.commit()
        n_done += len(rows)
        print(f"    ... {n_done:,}/{n_total:,}", flush=True)
        if len(rows) < chunk:
            break

    return n_done


def main():
    fecha = datetime.now().strftime('%Y-%m-%d')
    backup_path = OUTPUT_DIR / f'turso_backup_{fecha}.db'
    backup_path_zst = OUTPUT_DIR / f'turso_backup_{fecha}.db.zst'

    if backup_path.exists():
        backup_path.unlink()

    print(f"=== Backup Turso → {backup_path} ===", flush=True)
    print(f"Fecha: {fecha}\n", flush=True)

    t0 = time.time()
    conn = sqlite3.connect(str(backup_path))

    tables = list_tables()
    print(f"Tablas: {tables}\n", flush=True)

    total_filas = 0
    for table in tables:
        try:
            n = backup_table_to_sqlite(table, conn)
            total_filas += n
        except Exception as e:
            print(f"  [ERROR backup {table}]: {e}", flush=True)

    conn.close()
    size_mb = backup_path.stat().st_size / 1024 / 1024
    elapsed = time.time() - t0
    print(f"\nBackup raw: {size_mb:.1f} MB · {total_filas:,} filas · {elapsed:.0f}s", flush=True)

    # Comprimir con zstandard
    print("Comprimiendo con zstd...", flush=True)
    cctx = zstd.ZstdCompressor(level=22)
    with open(backup_path, 'rb') as fin, open(backup_path_zst, 'wb') as fout:
        cctx.copy_stream(fin, fout, read_size=8192, write_size=8192)
    size_zst_mb = backup_path_zst.stat().st_size / 1024 / 1024
    print(f"Comprimido: {size_zst_mb:.1f} MB ({size_zst_mb/size_mb*100:.1f}% del original)", flush=True)

    # Borrar el .db sin comprimir (solo dejar el .zst)
    backup_path.unlink()

    print(f"\n[OK] Backup terminado: {backup_path_zst}", flush=True)
    print(f"BACKUP_FILE={backup_path_zst}", flush=True)  # Para GH Actions output


if __name__ == '__main__':
    main()
