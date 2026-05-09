"""
Lector del snapshot pre-calculado de KPIs WMS.

El snapshot se genera 2x/día (00:00 y 12:00 Chile) por GH Action
ejecutando precalcular_kpis_wms.py. Esto evita que el dashboard haga
13+ queries Odoo en runtime cada vez que el user entra al Tab Resumen.

Si el snapshot no existe o es muy viejo (>14h), se hace fallback a
queries Odoo en vivo (comportamiento anterior).
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_FILE = PROJECT_ROOT / "data" / "kpis_wms" / "snapshot.json"

# Snapshot considerado "fresco" si tiene menos de 14h (margen para 2x/día)
MAX_AGE_HOURS = 14


@st.cache_data(ttl=300, show_spinner=False)
def cargar_snapshot() -> Dict:
    """Carga el snapshot JSON. Devuelve {} si no existe."""
    if not SNAPSHOT_FILE.exists():
        return {}
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def snapshot_status() -> Dict:
    """Status del snapshot para mostrar en UI."""
    snap = cargar_snapshot()
    if not snap or "error" in snap:
        return {
            "existe": False,
            "fresco": False,
            "edad_horas": None,
            "generado_en": None,
            "n_errores": 0,
            "leyenda": "❌ Sin snapshot — fallback Odoo en vivo (lento)",
        }
    gen = snap.get("generado_en")
    try:
        gen_dt = datetime.fromisoformat(gen)
        edad_horas = (datetime.now() - gen_dt).total_seconds() / 3600
    except Exception:
        edad_horas = None

    fresco = edad_horas is not None and edad_horas <= MAX_AGE_HOURS
    return {
        "existe": True,
        "fresco": fresco,
        "edad_horas": round(edad_horas, 1) if edad_horas is not None else None,
        "generado_en": gen,
        "n_errores": len(snap.get("errores", [])),
        "n_kpis": len(snap.get("kpis", {})),
        "leyenda": (
            f"✅ Snapshot {snap.get('generado_en', '')[:16]} "
            f"({edad_horas:.1f}h atrás)" if fresco
            else f"⚠️ Snapshot viejo ({edad_horas:.0f}h) — usando datos de la última corrida"
        ),
    }


def get_kpi(nombre: str, fallback_fn=None, *args, **kwargs):
    """Lee un KPI del snapshot. Si no existe, ejecuta fallback_fn (Odoo).

    Args:
        nombre: clave del KPI en snapshot["kpis"]
        fallback_fn: función a ejecutar si no hay snapshot
        *args, **kwargs: pasados a fallback_fn

    Returns:
        dict con el KPI (mismo shape que devuelve la fn original)
    """
    snap = cargar_snapshot()
    kpis = snap.get("kpis", {})
    if nombre in kpis and not isinstance(kpis[nombre], dict) and "error" in kpis.get(nombre, {}):
        # Datos válidos del snapshot
        return kpis[nombre]
    if nombre in kpis and isinstance(kpis[nombre], dict) and not kpis[nombre].get("error"):
        return kpis[nombre]

    # Fallback a Odoo
    if fallback_fn is not None:
        try:
            return fallback_fn(*args, **kwargs)
        except Exception as e:
            return {"error": f"Snapshot vacío + fallback falló: {e}"}
    return {"error": "Snapshot no contiene este KPI y no hay fallback"}


def get_seccion(nombre: str, default=None):
    """Lee una sección del snapshot (ej: tendencia_6m, forecast_3m, plan_auditoria)."""
    snap = cargar_snapshot()
    if nombre in snap:
        return snap[nombre]
    if nombre in snap.get("kpis", {}):
        return snap["kpis"][nombre]
    return default if default is not None else {}


def get_otif_ventana(canal: str, dias: int):
    """Acceso directo a OTIF de ventana específica."""
    snap = cargar_snapshot()
    key = f"{canal}_{dias}d"
    return snap.get("otif_ventanas", {}).get(key, {})


def get_pick_ventana(dias: int):
    snap = cargar_snapshot()
    return snap.get("pick_ventanas", {}).get(f"{dias}d", {})


def get_recepcion_ventana(dias: int):
    snap = cargar_snapshot()
    return snap.get("recepcion_ventanas", {}).get(f"{dias}d", {})
