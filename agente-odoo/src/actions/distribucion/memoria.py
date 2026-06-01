"""Memoria por proveedor — YAML por RUT, auto tras 3 aprobaciones."""
from __future__ import annotations
import re
from datetime import date
from pathlib import Path
import yaml

UMBRAL_AUTO = 3
DIRECTORIO_DEFAULT = Path(__file__).parent.parent.parent.parent / "data" / "memoria_distribucion"


def _ruta_yaml(rut: str, directorio: Path = DIRECTORIO_DEFAULT) -> Path:
    directorio.mkdir(parents=True, exist_ok=True)
    return directorio / (rut.replace("-", "").replace("/", "") + ".yaml")


def cargar_memoria(rut: str, directorio: Path = DIRECTORIO_DEFAULT) -> dict:
    ruta = _ruta_yaml(rut, directorio)
    if not ruta.exists():
        return {}
    try:
        with open(ruta, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def guardar_memoria(rut: str, memoria: dict, directorio: Path = DIRECTORIO_DEFAULT):
    ruta = _ruta_yaml(rut, directorio)
    with open(ruta, "w", encoding="utf-8") as f:
        yaml.dump(memoria, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _patron_desde_glosa(glosa: str) -> str:
    g = glosa.lower().strip()
    g = re.sub(r"\s+", " ", g)
    g = re.sub(r"\|\s*\$[\d.,]+\s*\w*", "", g).strip()
    palabras = [p for p in g.split() if len(p) > 2
                and p not in ("del", "los", "las", "con", "por", "para", "una", "uno")]
    return " ".join(palabras[:4]) if palabras else g[:30]


def registrar_aprobacion(rut: str, nombre_proveedor: str, glosa: str,
                          cuenta_destino: str, aprobado_por: str,
                          directorio: Path = DIRECTORIO_DEFAULT) -> dict:
    memoria = cargar_memoria(rut, directorio) or {"rut": rut, "nombre": nombre_proveedor, "reglas": []}
    patron = _patron_desde_glosa(glosa)
    reglas = memoria.get("reglas", [])
    existente = next((r for r in reglas if r.get("patron") == patron
                      and r.get("cuenta_destino") == cuenta_destino), None)
    if existente:
        existente["aprobaciones"] = existente.get("aprobaciones", 0) + 1
        existente["ultima_aprobacion"] = str(date.today())
        existente["aprobado_por"] = aprobado_por
        existente["auto"] = existente["aprobaciones"] >= UMBRAL_AUTO
    else:
        reglas.append({"patron": patron, "tipo_match": "contains_lower",
                        "cuenta_destino": cuenta_destino, "aprobaciones": 1,
                        "ultima_aprobacion": str(date.today()),
                        "aprobado_por": aprobado_por, "auto": False})
    memoria["reglas"] = reglas
    guardar_memoria(rut, memoria, directorio)
    return memoria


def registrar_correccion(rut: str, nombre_proveedor: str, glosa: str,
                          cuenta_destino_correcta: str, corregido_por: str,
                          directorio: Path = DIRECTORIO_DEFAULT) -> dict:
    memoria = cargar_memoria(rut, directorio) or {"rut": rut, "nombre": nombre_proveedor, "reglas": []}
    patron = _patron_desde_glosa(glosa)
    reglas = [r for r in memoria.get("reglas", []) if r.get("patron") != patron]
    reglas.append({"patron": patron, "tipo_match": "contains_lower",
                    "cuenta_destino": cuenta_destino_correcta, "aprobaciones": 1,
                    "ultima_aprobacion": str(date.today()),
                    "aprobado_por": corregido_por, "corregida": True, "auto": False})
    memoria["reglas"] = reglas
    guardar_memoria(rut, memoria, directorio)
    return memoria


def resumen_memoria(rut: str, directorio: Path = DIRECTORIO_DEFAULT) -> str:
    m = cargar_memoria(rut, directorio)
    if not m:
        return f"Sin memoria para RUT {rut}"
    reglas = m.get("reglas", [])
    auto = [r for r in reglas if r.get("aprobaciones", 0) >= UMBRAL_AUTO]
    pendientes = [r for r in reglas if r.get("aprobaciones", 0) < UMBRAL_AUTO]
    pendientes_txt = ", ".join(f"{r['patron']} ({r['aprobaciones']}/3)" for r in pendientes) or "ninguna"
    return (f"Proveedor: {m.get('nombre', rut)} | RUT: {rut}\n"
            f"  Auto ({len(auto)}): {', '.join(r['patron'] for r in auto) or 'ninguna'}\n"
            f"  Aprendiendo ({len(pendientes)}): {pendientes_txt}")
