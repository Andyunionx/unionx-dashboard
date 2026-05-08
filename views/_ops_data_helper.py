"""
Persistencia de datos manuales para KPIs Ops que NO vienen de Odoo.

Datos que se cargan manualmente:
  - equipo_bodega: # personas + horas trabajadas por mes
  - capacidad_bodega: m3 totales disponibles
  - cycle_counts: lista de auditorías (SKU, qty_sistema, qty_fisica, fecha)
  - merma_operativa: valor mermado por mes

Storage:
  - LOCAL (desarrollo): JSON file en data/ops_kpis_manuales.json (gitignored)
  - STREAMLIT CLOUD (prod): mismo JSON pero NO persiste entre re-deploys
    → roadmap H2: migrar a Turso (libSQL)

Convención: claves en formato "YYYY-MM" (mes/año), valores arbitrarios.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "ops_manuales"
DATA_FILE = DATA_DIR / "kpis.json"


def _load() -> Dict:
    """Carga el JSON. Si no existe, devuelve estructura vacía."""
    if not DATA_FILE.exists():
        return {
            "equipo_bodega": {},   # {"YYYY-MM": {"personas": N, "horas_total": H}}
            "capacidad_bodega": {  # único, no por mes
                "m3_totales": None,
                "fecha_actualizacion": None,
            },
            "cycle_counts": [],    # [{"sku": ..., "qty_sistema": ..., "qty_fisica": ..., "fecha": "YYYY-MM-DD"}, ...]
            "merma": {},           # {"YYYY-MM": {"valor_mermado": ..., "valor_inv_promedio": ...}}
            "_meta": {"version": 1, "ultima_carga": None},
        }
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: Dict) -> bool:
    """Persiste JSON. Crea dir si no existe."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data["_meta"]["ultima_carga"] = datetime.now().isoformat()
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


# ============================================================
# Equipo bodega
# ============================================================
def get_equipo_mes(mes: str) -> Dict:
    """Obtiene datos del equipo para un mes (YYYY-MM)."""
    data = _load()
    return data.get("equipo_bodega", {}).get(mes, {})


def set_equipo_mes(mes: str, personas: int, horas_total: float) -> bool:
    data = _load()
    if "equipo_bodega" not in data:
        data["equipo_bodega"] = {}
    data["equipo_bodega"][mes] = {
        "personas": personas,
        "horas_total": horas_total,
        "ts": datetime.now().isoformat(),
    }
    return _save(data)


def get_horas_promedio_dia(mes: str) -> float:
    """Helper: horas trabajadas por día (asume 22 días hábiles)."""
    info = get_equipo_mes(mes)
    horas = info.get("horas_total", 0)
    return horas / 22 if horas else 0


# ============================================================
# Capacidad bodega
# ============================================================
def get_capacidad_bodega() -> Dict:
    return _load().get("capacidad_bodega", {})


def set_capacidad_bodega(m3_totales: float) -> bool:
    data = _load()
    data["capacidad_bodega"] = {
        "m3_totales": m3_totales,
        "fecha_actualizacion": datetime.now().isoformat(),
    }
    return _save(data)


# ============================================================
# Cycle counts (auditorías de inventario)
# ============================================================
def add_cycle_count(sku: str, qty_sistema: float, qty_fisica: float, fecha: str = None, nota: str = "") -> bool:
    data = _load()
    if "cycle_counts" not in data:
        data["cycle_counts"] = []
    data["cycle_counts"].append({
        "sku": sku,
        "qty_sistema": qty_sistema,
        "qty_fisica": qty_fisica,
        "discrepancia": qty_fisica - qty_sistema,
        "fecha": fecha or datetime.now().strftime("%Y-%m-%d"),
        "nota": nota,
        "ts": datetime.now().isoformat(),
    })
    return _save(data)


def get_cycle_counts(desde_fecha: str = None) -> List[Dict]:
    data = _load()
    counts = data.get("cycle_counts", [])
    if desde_fecha:
        counts = [c for c in counts if c.get("fecha", "") >= desde_fecha]
    return sorted(counts, key=lambda c: c.get("fecha", ""), reverse=True)


def kpi_exactitud_inventario(dias: int = 30) -> Dict:
    """Calcula % SKUs sin diferencia en cycle counts recientes."""
    desde = (datetime.now().date()).strftime("%Y-%m-%d")
    # restar dias
    from datetime import timedelta
    desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")

    counts = get_cycle_counts(desde_fecha=desde)
    if not counts:
        return {"valor": None, "total": 0, "exactos": 0, "error": "Sin cycle counts en ventana"}
    exactos = sum(1 for c in counts if c.get("discrepancia", 0) == 0)
    total = len(counts)
    return {
        "valor": exactos / total if total else None,
        "total": total,
        "exactos": exactos,
        "discrepancias": total - exactos,
        "error": None,
    }


# ============================================================
# Merma operativa
# ============================================================
def set_merma_mes(mes: str, valor_mermado: float, valor_inv_promedio: float) -> bool:
    data = _load()
    if "merma" not in data:
        data["merma"] = {}
    data["merma"][mes] = {
        "valor_mermado": valor_mermado,
        "valor_inv_promedio": valor_inv_promedio,
        "pct_merma": valor_mermado / valor_inv_promedio if valor_inv_promedio else 0,
        "ts": datetime.now().isoformat(),
    }
    return _save(data)


def get_merma_mes(mes: str) -> Dict:
    return _load().get("merma", {}).get(mes, {})


def kpi_merma_operativa() -> Dict:
    """Promedio de merma de los últimos 3 meses cargados."""
    data = _load().get("merma", {})
    if not data:
        return {"valor": None, "error": "Sin datos cargados"}
    meses = sorted(data.keys(), reverse=True)[:3]
    valores = [data[m].get("pct_merma", 0) for m in meses if data[m].get("pct_merma") is not None]
    if not valores:
        return {"valor": None, "error": "Sin datos válidos"}
    return {
        "valor": sum(valores) / len(valores),
        "n_meses": len(valores),
        "ultimo_mes": meses[0] if meses else None,
        "error": None,
    }


# ============================================================
# Próximos embarques (forecasting de capacidad de recepción)
# ============================================================
def add_proximo_embarque(eta: str, m3: float, descripcion: str = "", contenedores: int = 1) -> bool:
    """Registra un embarque entrante esperado.

    Args:
        eta: fecha estimada arribo (YYYY-MM-DD)
        m3: volumen total esperado en m³
        descripcion: ej. "Steven – plancha pelo + secadores OHNSO"
        contenedores: cantidad (1 contenedor 40HC ≈ 67 m³ útil)
    """
    data = _load()
    if "proximos_embarques" not in data:
        data["proximos_embarques"] = []
    data["proximos_embarques"].append({
        "eta": eta,
        "m3": m3,
        "descripcion": descripcion,
        "contenedores": contenedores,
        "ts": datetime.now().isoformat(),
    })
    # Ordenar por ETA ascendente
    data["proximos_embarques"].sort(key=lambda x: x.get("eta", "9999"))
    return _save(data)


def get_proximos_embarques(solo_pendientes: bool = True) -> List[Dict]:
    data = _load()
    embarques = data.get("proximos_embarques", [])
    if solo_pendientes:
        hoy = datetime.now().strftime("%Y-%m-%d")
        embarques = [e for e in embarques if e.get("eta", "") >= hoy]
    return embarques


def delete_proximo_embarque(idx: int) -> bool:
    data = _load()
    embarques = data.get("proximos_embarques", [])
    if 0 <= idx < len(embarques):
        embarques.pop(idx)
        data["proximos_embarques"] = embarques
        return _save(data)
    return False


def kpi_capacidad_recepcion(m3_disponible: float) -> Dict:
    """Compara disponibilidad actual vs próximos embarques.

    Args:
        m3_disponible: m³ libres en bodega ahora

    Returns:
        valor: ratio capacidad/embarques próximos 30d
        ok: bool, True si entra el próximo embarque con buffer 20%
    """
    embarques = get_proximos_embarques(solo_pendientes=True)
    if not embarques:
        return {
            "valor": None,
            "m3_disponible": m3_disponible,
            "m3_proximos_30d": 0,
            "proximo_embarque": None,
            "ok": True,
            "error": "Sin embarques cargados",
        }
    from datetime import timedelta
    en_30d = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    proximos = [e for e in embarques if e.get("eta", "") <= en_30d]
    m3_proximos_30d = sum(e.get("m3", 0) for e in proximos)
    proximo = embarques[0] if embarques else None
    proximo_m3 = proximo.get("m3", 0) if proximo else 0
    # OK si entra con buffer 20%
    ok = m3_disponible >= proximo_m3 * 1.2 if proximo else True
    return {
        "valor": m3_disponible / m3_proximos_30d if m3_proximos_30d > 0 else None,
        "m3_disponible": m3_disponible,
        "m3_proximos_30d": m3_proximos_30d,
        "proximo_embarque": proximo,
        "ok": ok,
        "error": None,
    }


# ============================================================
# Volumen unitario por categoría (fallback cuando Odoo no tiene product.volume)
# ============================================================
def set_m3_categoria(categoria: str, m3_unitario: float) -> bool:
    """Volumen promedio en m³ de una unidad de la categoría."""
    data = _load()
    if "m3_por_categoria" not in data:
        data["m3_por_categoria"] = {}
    data["m3_por_categoria"][categoria] = {
        "m3_unitario": m3_unitario,
        "ts": datetime.now().isoformat(),
    }
    return _save(data)


def get_m3_categoria(categoria: str) -> float:
    data = _load().get("m3_por_categoria", {})
    return data.get(categoria, {}).get("m3_unitario", 0)


def get_all_m3_categoria() -> Dict[str, float]:
    """Devuelve {categoria: m3_unitario} de todas las cargadas."""
    data = _load().get("m3_por_categoria", {})
    return {k: v.get("m3_unitario", 0) for k, v in data.items()}


# ============================================================
# Capacidad por slot (m³ por posición)
# ============================================================
def set_capacidad_slot_default(m3_por_slot: float) -> bool:
    """Capacidad m³ default de cada posición individual.

    Cuando no se conoce la capacidad slot por slot, se asume este default.
    Típico rack industrial UnionX: 1.5–2.5 m³ por posición.
    """
    data = _load()
    if "capacidad_bodega" not in data:
        data["capacidad_bodega"] = {}
    data["capacidad_bodega"]["m3_por_slot_default"] = m3_por_slot
    data["capacidad_bodega"]["fecha_actualizacion"] = datetime.now().isoformat()
    return _save(data)


def get_capacidad_slot_default() -> float:
    return _load().get("capacidad_bodega", {}).get("m3_por_slot_default", 0)
