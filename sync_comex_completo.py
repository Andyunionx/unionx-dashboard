"""Orquesta el pipeline COMEX completo en secuencia:

  1. extract_comex_desde_odoo.py     → data/comex/transito.parquet (principal)
  2. extract_comex_transito.py       → data/comex/transito_sheet.parquet (contraste)
  3. comparar_transito_sheet_vs_odoo → data/comex/transito_alertas.json
  4. sync_planificacion.py            → tablas Turso planif_* (best-effort)

Diseñado para ejecutarse vía Task Scheduler. Idempotente. Si un paso falla,
los siguientes igualmente corren (best-effort). Logs en data/comex/logs/.
"""
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent
LOG_DIR = PROJECT_ROOT / 'data' / 'comex' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'sync_comex.log'
PYTHON = sys.executable

PASOS = [
    ('Odoo (principal)',          'extract_comex_desde_odoo.py',           True),
    ('Sheet (contraste)',         'extract_comex_transito.py',             False),
    ('Comparador',                'comparar_transito_sheet_vs_odoo.py',    False),
    ('Sync Turso planif_*',       'sync_planificacion.py',                 False),
    ('Snapshots planif a parquet', 'extract_planif_snapshots.py',          False),
]


def setup_logger():
    log = logging.getLogger('sync_comex')
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S')
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=5, encoding='utf-8')
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def main():
    log = setup_logger()
    log.info('=' * 60)
    log.info(f'Inicio sync COMEX completo')
    log.info('=' * 60)

    fallos_criticos = 0
    for nombre, script, critico in PASOS:
        path = PROJECT_ROOT / script
        if not path.exists():
            log.warning(f'[SKIP] {nombre}: {script} no existe')
            continue
        log.info(f'[RUN] {nombre} → {script}')
        t0 = time.time()
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        try:
            r = subprocess.run([PYTHON, '-u', str(path)],
                                env=env, capture_output=True, text=True, timeout=600)
            dur = time.time() - t0
            if r.returncode == 0:
                log.info(f'[OK]  {nombre} en {dur:.1f}s')
            else:
                msg = (r.stderr or r.stdout or '').strip()[-400:]
                log.error(f'[FAIL] {nombre} rc={r.returncode} en {dur:.1f}s: {msg}')
                if critico:
                    fallos_criticos += 1
        except subprocess.TimeoutExpired:
            log.error(f'[TIMEOUT] {nombre} > 600s. Aborto este paso, sigo con los demás.')
            if critico:
                fallos_criticos += 1
        except Exception as e:
            log.error(f'[ERROR] {nombre}: {type(e).__name__}: {e}')
            if critico:
                fallos_criticos += 1

    log.info('=' * 60)
    if fallos_criticos == 0:
        log.info('SUCCESS (pasos críticos OK)')
        return 0
    log.error(f'FAIL: {fallos_criticos} paso(s) crítico(s) fallaron')
    return 1


if __name__ == '__main__':
    sys.exit(main())
