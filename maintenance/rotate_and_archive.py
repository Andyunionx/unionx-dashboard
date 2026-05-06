"""
Mantenimiento mensual: rota logs y archiva carpetas viejas del inbox.

- Comprime logs/*.log mayores a 5 MB y mueve a logs/archive/YYYY-MM/
- Mueve carpetas de agente-comex/data/inbox/ con mas de 60 dias a archive/inbox/

Ejecucion: 1 de cada mes a las 03:00 (Task Scheduler).
"""
import gzip
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_ARCHIVE = LOGS_DIR / "archive"
INBOX_DIR = PROJECT_ROOT / "agente-comex" / "data" / "inbox"
INBOX_ARCHIVE = PROJECT_ROOT / "archive" / "inbox"

ROTATE_THRESHOLD_BYTES = 5 * 1024 * 1024  # 5 MB
INBOX_AGE_DAYS = 60
INBOX_FOLDER_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})_")  # ej: 20260428_1530_xxx


def rotate_logs():
    """Comprime logs grandes y los mueve a archive/YYYY-MM/."""
    if not LOGS_DIR.exists():
        return 0

    rotated = 0
    yyyy_mm = datetime.now().strftime("%Y-%m")
    target_dir = LOGS_ARCHIVE / yyyy_mm
    target_dir.mkdir(parents=True, exist_ok=True)

    for log_path in LOGS_DIR.glob("*.log"):
        try:
            size = log_path.stat().st_size
        except OSError:
            continue

        if size < ROTATE_THRESHOLD_BYTES:
            continue

        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        gz_target = target_dir / f"{log_path.stem}_{ts}.log.gz"

        with open(log_path, "rb") as src, gzip.open(gz_target, "wb") as dst:
            shutil.copyfileobj(src, dst)

        # Truncar el original (no borrar para no romper handles abiertos)
        with open(log_path, "w") as f:
            f.write(f"# log rotado el {datetime.now().isoformat()} a {gz_target}\n")

        rotated += 1
        print(f"[OK] log rotado: {log_path.name} ({size//1024} KB) -> {gz_target.name}")

    return rotated


def archive_old_inbox():
    """Mueve carpetas de inbox con mas de N dias a archive/inbox/."""
    if not INBOX_DIR.exists():
        return 0

    INBOX_ARCHIVE.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now() - timedelta(days=INBOX_AGE_DAYS)
    moved = 0

    for folder in INBOX_DIR.iterdir():
        if not folder.is_dir():
            continue

        m = INBOX_FOLDER_RE.match(folder.name)
        if not m:
            continue

        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            folder_date = datetime(year, month, day)
        except ValueError:
            continue

        if folder_date >= cutoff:
            continue

        target = INBOX_ARCHIVE / folder.name
        if target.exists():
            print(f"[SKIP] ya existe en archive: {folder.name}")
            continue

        shutil.move(str(folder), str(target))
        moved += 1
        print(f"[OK] archivado: {folder.name}")

    return moved


def main():
    print(f"=== rotate_and_archive @ {datetime.now().isoformat()} ===")
    rotated = rotate_logs()
    moved = archive_old_inbox()
    print(f"Resumen: {rotated} log(s) rotado(s), {moved} carpeta(s) inbox archivada(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
