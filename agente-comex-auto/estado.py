"""Store de estado del agente COMEX autónomo (máquina de estados por embarque).

Persistencia: JSON en data/estado_embarques.json (commiteable al repo para el cron cloud).

Fases:
  1 = ESPERANDO_DOCS   (falta PI y/o PL de Steven)
  2 = ESPERANDO_FLETE  (PI+PL OK; esperando que Seimex publique el flete final)
  3 = COSTEO_Y_SKUS    (flete OK; costeado; esperando que existan todos los SKU en Odoo)
  4 = CARGA_PO         (SKU OK; PO cargada en Odoo en borrador)
  9 = COMPLETADO
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
ESTADO_FILE = BASE / "data" / "estado_embarques.json"

FASES = {1: "ESPERANDO_DOCS", 2: "ESPERANDO_FLETE", 3: "COSTEO_Y_SKUS",
         4: "CARGA_PO", 9: "COMPLETADO"}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def cargar() -> dict:
    if ESTADO_FILE.exists():
        return json.loads(ESTADO_FILE.read_text(encoding="utf-8"))
    return {}


def guardar(estado: dict):
    ESTADO_FILE.parent.mkdir(parents=True, exist_ok=True)
    ESTADO_FILE.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")


def get_embarque(estado: dict, emb: str) -> dict:
    """Devuelve (creando si no existe) el registro de un embarque."""
    if emb not in estado:
        estado[emb] = {
            "embarque": emb, "fase": 1,
            "pi": None, "pl": None,
            "pi_candidatos": [], "pl_candidatos": [],
            "flete_usd": None, "flete_moneda": None,
            "seimex_ref": None, "eta_puerto": None, "eta_bodega": None,
            "costeo_path": None, "skus": [], "skus_faltantes": None,
            "po_id": None, "po_name": None,
            "ts_creado": _now(), "ts_actualizado": _now(), "log": [],
        }
    return estado[emb]


def log(reg: dict, msg: str):
    reg["log"].append(f"{_now()} · {msg}")
    reg["ts_actualizado"] = _now()
    print(f"  [{reg['embarque']}] {msg}")


def set_fase(reg: dict, fase: int, motivo: str = ""):
    if reg["fase"] != fase:
        log(reg, f"fase {reg['fase']} ({FASES.get(reg['fase'])}) → {fase} ({FASES.get(fase)}) {motivo}".strip())
        reg["fase"] = fase


def resumen(estado: dict) -> str:
    if not estado:
        return "(sin embarques en seguimiento)"
    lines = []
    for emb, r in sorted(estado.items()):
        docs = ("PI✓" if r.get("pi") else "PI·") + " " + ("PL✓" if r.get("pl") else "PL·")
        lines.append(f"  {emb:<12} fase {r['fase']} {FASES.get(r['fase'],''):<16} {docs}  flete={r.get('flete_usd') or '—'}")
    return "\n".join(lines)
