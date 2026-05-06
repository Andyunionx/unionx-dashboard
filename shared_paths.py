"""
Punto unico de resolucion de paths a planillas master.
Lee config/sources_of_truth.yaml y expone constantes + helpers.

Uso:
    from shared_paths import PLANIFICACION_FINANCIERA, CONTRIBUCION, make_backup
    print(PLANIFICACION_FINANCIERA)  # Path absoluto al Excel maestro

    # Antes de modificar:
    make_backup(PLANIFICACION_FINANCIERA)
"""
from datetime import datetime
from pathlib import Path
from typing import Optional
import shutil

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config" / "sources_of_truth.yaml"


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config no encontrado: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_config = _load_config()


def _resolve(value) -> Path:
    """Convierte el value del config a Path absoluto.

    Soporta:
      - string: path relativo a PROJECT_ROOT (o absoluto si comienza con drive/slash)
      - dict {'glob': '...'}: resuelve al archivo MAS RECIENTE (por mtime) que
        matchea el patron glob. Util para versionado tipo "V51 - 04, V52, V53...".
    """
    if isinstance(value, dict) and "glob" in value:
        pattern = value["glob"]
        # Resolver glob relativo a PROJECT_ROOT
        # Path.glob no soporta paths absolutos en el patron, asi que separamos
        from pathlib import PurePath
        if PurePath(pattern).is_absolute():
            base = Path(pattern).parent
            pat = Path(pattern).name
        else:
            base = (PROJECT_ROOT / pattern).parent
            pat = Path(pattern).name
        try:
            matches = sorted(base.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
            if matches:
                return matches[0]  # mas reciente
        except Exception:
            pass
        # Si no hay match, devolver path "esperado" (no existira pero permite log claro)
        return base / pat
    # string normal
    return PROJECT_ROOT / str(value)


# ============================================================================
# Constantes de path (las mas usadas)
# ============================================================================
PLANIFICACION_FINANCIERA: Path = _resolve(_config["planillas"]["planificacion_financiera"])
CONTRIBUCION: Path = _resolve(_config["planillas"]["contribucion"])
PRESUPUESTO_LEGACY: Path = _resolve(_config["planillas"].get("presupuesto_legacy", ""))
MAESTRA_CANALES: Path = _resolve(_config["planillas"].get("maestra_canales", ""))

BACKUPS_DIR: Path = _resolve(_config.get("backups_dir", "data/planillas/backups"))
EERR_DIR: Path = _resolve(_config.get("eerr_dir", "data/eerr"))
OUTPUTS_DIR: Path = _resolve(_config.get("outputs_dir", "data/outputs"))


def get_path(key: str) -> Path:
    """Acceso dinamico por key del yaml. Ej: get_path('contribucion').

    Acepta tanto las top-level keys (backups_dir, eerr_dir, outputs_dir)
    como las anidadas en 'planillas'.
    """
    if key in _config.get("planillas", {}):
        return _resolve(_config["planillas"][key])
    if key in _config:
        return _resolve(_config[key])
    raise KeyError(f"Key '{key}' no esta en {CONFIG_PATH}")


def make_backup(file_path) -> Optional[Path]:
    """Crea un backup timestampeado en BACKUPS_DIR antes de modificar el archivo.

    Devuelve el Path del backup creado, o None si el original no existia.
    """
    src = Path(file_path)
    if not src.exists():
        return None

    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUPS_DIR / f"{src.stem}_{ts}{src.suffix}"
    shutil.copy2(src, dst)
    return dst


def reload_config() -> None:
    """Re-lee el yaml (util si se modifica en runtime)."""
    global _config, PLANIFICACION_FINANCIERA, CONTRIBUCION, PRESUPUESTO_LEGACY
    global MAESTRA_CANALES, BACKUPS_DIR, EERR_DIR, OUTPUTS_DIR
    _config = _load_config()
    PLANIFICACION_FINANCIERA = _resolve(_config["planillas"]["planificacion_financiera"])
    CONTRIBUCION = _resolve(_config["planillas"]["contribucion"])
    PRESUPUESTO_LEGACY = _resolve(_config["planillas"].get("presupuesto_legacy", ""))
    MAESTRA_CANALES = _resolve(_config["planillas"].get("maestra_canales", ""))
    BACKUPS_DIR = _resolve(_config.get("backups_dir", "data/planillas/backups"))
    EERR_DIR = _resolve(_config.get("eerr_dir", "data/eerr"))
    OUTPUTS_DIR = _resolve(_config.get("outputs_dir", "data/outputs"))
