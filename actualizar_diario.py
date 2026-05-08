#!/usr/bin/env python3
"""
Actualización diaria: extrae las ventas del día anterior y actualiza
DB SQLite + Excel. Idempotente (re-correr no duplica).

Diseñado para ejecutarse automáticamente vía Windows Task Scheduler
cada día a las 06:00 AM.

Uso manual:
    python actualizar_diario.py            # ayer
    python actualizar_diario.py --dias 3   # últimos 3 días (catch-up)
    python actualizar_diario.py --fecha 2026-05-05   # día específico
"""
import argparse
import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
LOG_DIR = PROJECT_ROOT / 'data' / 'db'
LOG_FILE = LOG_DIR / 'sincronizacion_diaria.log'
DB_PATH = PROJECT_ROOT / 'data' / 'db' / 'maestra_ventas.db'
PYTHON_EXE = sys.executable
SCRIPT_RAW = PROJECT_ROOT / 'actualizar_raw_historico.py'

LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logger():
    logger = logging.getLogger('actualizar_diario')
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S')
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=10, encoding='utf-8')
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def cargar_password():
    """Carga la password de Odoo desde la variable de entorno User."""
    if os.environ.get('ANDRES_ODOO_PASSWORD'):
        return
    try:
        import subprocess
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "[Environment]::GetEnvironmentVariable('ANDRES_ODOO_PASSWORD', 'User')"],
            capture_output=True, text=True, timeout=10
        )
        pwd = (r.stdout or '').strip()
        if pwd:
            os.environ['ANDRES_ODOO_PASSWORD'] = pwd
    except Exception:
        pass


def registrar_metadata(estado, mensaje, periodo_ini, periodo_fin, n_filas):
    """Registra resultado en metadata_cargas."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute("""
            INSERT INTO metadata_cargas
            (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(),
              f'actualizar_diario.py [{estado}] {mensaje}',
              n_filas, periodo_ini, periodo_fin,
              'daily_ok' if estado == 'OK' else 'daily_error'))
        conn.commit()
        conn.close()
    except Exception as e:
        # Si la DB no existe aún o hay otro error, solo loggear
        pass


def ejecutar_extraccion(logger, fecha_inicio: str, fecha_fin: str) -> tuple[bool, str, int]:
    """Ejecuta actualizar_raw_historico.py y captura resultado."""
    cargar_password()
    cmd = [
        PYTHON_EXE, '-u', str(SCRIPT_RAW),
        '--periodo', f'{fecha_inicio} 00:00:00', f'{fecha_fin} 23:59:59'
    ]
    logger.info(f"Ejecutando: {' '.join(cmd)}")
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        )
        elapsed = time.time() - t0
        # Loguear cada línea de stdout
        for line in (proc.stdout or '').splitlines():
            if line.strip():
                logger.info(f"  | {line}")
        if proc.returncode != 0:
            logger.error(f"Falló con código {proc.returncode}")
            for line in (proc.stderr or '').splitlines():
                if line.strip():
                    logger.error(f"  err| {line}")
            return False, f"exit code {proc.returncode}", 0

        # Buscar n_filas en el output
        n_filas = 0
        for line in (proc.stdout or '').splitlines():
            if 'filas extraidas' in line:
                try:
                    n_filas = int(line.split('[OK]')[1].split('filas')[0].strip().replace(',', ''))
                except Exception:
                    pass
        logger.info(f"OK extracción {fecha_inicio} → {fecha_fin}: {n_filas:,} filas en {elapsed:.0f}s")
        return True, 'OK', n_filas
    except subprocess.TimeoutExpired:
        logger.error("Timeout (>1h) — extracción cancelada")
        return False, 'timeout', 0
    except Exception as e:
        logger.exception(f"Error ejecutando: {e}")
        return False, str(e)[:200], 0


def main():
    parser = argparse.ArgumentParser(description='Actualización diaria automática')
    parser.add_argument('--dias', type=int, default=1,
                        help='Cuántos días hacia atrás extraer (default: 1 = ayer)')
    parser.add_argument('--fecha', type=str, default=None,
                        help='Fecha específica YYYY-MM-DD (anula --dias)')
    parser.add_argument('--hoy', action='store_true',
                        help='Extraer hoy (live mode, para Task Scheduler cada 5 min)')
    args = parser.parse_args()

    logger = setup_logger()
    logger.info("="*80)
    logger.info("ACTUALIZACIÓN DIARIA AUTOMÁTICA")
    logger.info("="*80)

    if args.hoy:
        hoy = datetime.now().strftime('%Y-%m-%d')
        fecha_inicio = hoy
        fecha_fin = hoy
    elif args.fecha:
        fecha_inicio = args.fecha
        fecha_fin = args.fecha
    else:
        ayer = datetime.now() - timedelta(days=args.dias)
        hoy_menos_1 = datetime.now() - timedelta(days=1)
        fecha_inicio = ayer.strftime('%Y-%m-%d')
        fecha_fin = hoy_menos_1.strftime('%Y-%m-%d')

    logger.info(f"Período objetivo: {fecha_inicio} a {fecha_fin}")

    ok, msg, n = ejecutar_extraccion(logger, fecha_inicio, fecha_fin)
    estado = 'OK' if ok else 'ERROR'
    registrar_metadata(estado, msg, fecha_inicio, fecha_fin, n)

    if ok:
        logger.info(f"[OK] Sincronización completada: {n:,} filas")
        # Después del sync, evaluar alertas
        try:
            logger.info("Evaluando alertas de negocio...")
            import subprocess
            r = subprocess.run(
                [PYTHON_EXE, '-u', str(PROJECT_ROOT / 'evaluar_alertas.py')],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            )
            for line in (r.stdout or '').splitlines():
                if line.strip():
                    logger.info(f"  | {line}")
        except Exception as e:
            logger.warning(f"Eval alertas falló (no bloquea): {e}")
        return 0
    else:
        logger.error(f"[FAIL] Sincronización fallida: {msg}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
