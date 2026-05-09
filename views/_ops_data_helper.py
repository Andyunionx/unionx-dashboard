"""
Persistencia de datos manuales para KPIs Ops que NO vienen de Odoo.

Datos que se cargan manualmente:
  - equipo_bodega: # personas + horas trabajadas por mes
  - capacidad_bodega: m3 totales disponibles
  - cycle_counts: lista de auditorías (SKU, qty_sistema, qty_fisica, fecha)
  - merma_operativa: valor mermado por mes
  - proximos_embarques: lista de embarques entrantes
  - m3_por_categoria: fallback volumen unidad

Storage (en orden de preferencia):
  1. **TURSO (prod)**: tabla `ops_kpis_manuales` con esquema key-value JSON.
     Persiste entre re-deploys de Streamlit Cloud. Requiere LIBSQL_URL +
     LIBSQL_AUTH_TOKEN en env vars.
  2. **JSON local (dev fallback)**: `data/ops_manuales/kpis.json`. Solo si
     Turso no está disponible (ej: desarrollo local sin credenciales).

API pública (sin cambios):
  - get_equipo_mes(mes), set_equipo_mes(mes, personas, horas)
  - get_capacidad_bodega(), set_capacidad_bodega(m3)
  - add_cycle_count, get_cycle_counts, kpi_exactitud_inventario
  - set/get_merma_mes, kpi_merma_operativa
  - add/get/delete_proximo_embarque, kpi_capacidad_recepcion
  - set/get_m3_categoria, get_all_m3_categoria
  - calcular_horas_estandar_mes, get_horas_promedio_dia
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

# Asegurar que db_client esté importable
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_TURSO_KEY = "kpis_v1"  # singleton key en la tabla


def _empty_estructura() -> Dict:
    return {
        "equipo_bodega": {},
        "capacidad_bodega": {
            "m3_totales": None,
            "m3_por_slot_default": 0,
            "fecha_actualizacion": None,
        },
        "cycle_counts": [],
        "merma": {},
        "proximos_embarques": [],
        "m3_por_categoria": {},
        "_meta": {"version": 1, "ultima_carga": None, "storage": "init"},
    }


def _try_turso():
    """Devuelve (conn, esta_en_turso) o (None, False) si no hay credenciales."""
    if not os.environ.get('LIBSQL_URL'):
        return None, False
    try:
        from db_client import get_connection, get_db_path
        conn = get_connection(get_db_path())
        # Asegurar tabla existe
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ops_kpis_manuales (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL,
                ts TEXT NOT NULL
            )
        """)
        conn.commit()
        return conn, True
    except Exception as e:
        print(f"[ops_data_helper] Turso falló, fallback JSON: {e}")
        return None, False


def _load() -> Dict:
    """Carga la estructura desde Turso (prod) o JSON local (fallback dev)."""
    # 1. Intentar Turso
    conn, ok = _try_turso()
    if ok:
        try:
            row = conn.execute("SELECT v FROM ops_kpis_manuales WHERE k = ?",
                               (_TURSO_KEY,)).fetchone()
            if row:
                data = json.loads(row[0])
                data.setdefault("_meta", {})["storage"] = "turso"
                return data
            else:
                # Primera vez: estructura vacía
                return _empty_estructura()
        except Exception as e:
            print(f"[ops_data_helper] Error leyendo de Turso: {e}")
        finally:
            try: conn.close()
            except Exception: pass

    # 2. Fallback JSON local
    if not DATA_FILE.exists():
        return _empty_estructura()
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("_meta", {})["storage"] = "json_local"
            return data
    except Exception:
        return _empty_estructura()


def _save(data: Dict) -> bool:
    """Persiste a Turso (prod) o JSON local (fallback dev)."""
    data.setdefault("_meta", {})["ultima_carga"] = datetime.now().isoformat()

    # 1. Intentar Turso
    conn, ok = _try_turso()
    if ok:
        try:
            data["_meta"]["storage"] = "turso"
            conn.execute(
                "INSERT OR REPLACE INTO ops_kpis_manuales (k, v, ts) VALUES (?, ?, ?)",
                (_TURSO_KEY, json.dumps(data, ensure_ascii=False),
                 datetime.now().isoformat()),
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[ops_data_helper] Error escribiendo a Turso: {e}")
        finally:
            try: conn.close()
            except Exception: pass

    # 2. Fallback JSON local
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data["_meta"]["storage"] = "json_local"
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_storage_status() -> Dict:
    """Diagnóstico para mostrar en la UI: dónde se está persistiendo."""
    conn, ok = _try_turso()
    if conn:
        try: conn.close()
        except Exception: pass
    return {
        "turso_configurado": bool(os.environ.get('LIBSQL_URL')),
        "turso_alcanzable": ok,
        "storage_actual": "Turso (cloud)" if ok else "JSON local (efímero en Cloud)",
        "advertencia": None if ok else (
            "Sin LIBSQL_URL en env. Datos en JSON local — se pierden al re-deploy."
        ),
    }


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


# Horario estándar UnionX bodega (definido por Andrés 2026-05-09):
# L-J: 8 a 18 con 1h almuerzo = 9 hrs/día
# V:   8 a 15 con 1h almuerzo = 6 hrs/día
# Total/persona/sem: 4*9 + 6 = 42 hrs (coincide con contrato 42h sem)
HORARIO_BODEGA = {
    "lunes_jueves_hrs": 9,
    "viernes_hrs": 6,
    "sabado_hrs": 0,
    "domingo_hrs": 0,
}


def calcular_horas_estandar_mes(mes: str, n_personas: int) -> Dict:
    """Calcula horas totales estándar del mes según horario UnionX bodega.

    Args:
        mes: "YYYY-MM"
        n_personas: cantidad de operarios activos

    Returns:
        {horas_total, horas_persona, n_lj, n_v, n_dias_habiles}
    """
    import calendar
    from datetime import date as _date
    try:
        anio, mes_n = mes.split("-")
        anio, mes_n = int(anio), int(mes_n)
    except Exception:
        return {"horas_total": 0, "error": "Formato YYYY-MM inválido"}

    n_dias = calendar.monthrange(anio, mes_n)[1]
    n_lj = sum(1 for d in range(1, n_dias + 1)
               if _date(anio, mes_n, d).weekday() < 4)  # L=0, M=1, X=2, J=3
    n_v = sum(1 for d in range(1, n_dias + 1)
              if _date(anio, mes_n, d).weekday() == 4)  # V=4
    hrs_persona = (n_lj * HORARIO_BODEGA["lunes_jueves_hrs"]
                   + n_v * HORARIO_BODEGA["viernes_hrs"])
    hrs_total = hrs_persona * n_personas
    return {
        "horas_total": hrs_total,
        "horas_persona": hrs_persona,
        "n_lj": n_lj,
        "n_v": n_v,
        "n_dias_habiles": n_lj + n_v,
        "n_personas": n_personas,
        "error": None,
    }


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
