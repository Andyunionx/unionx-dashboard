"""
Pre-cálculo de KPIs WMS (corre via GH Action 2x/día).

Genera snapshot JSON con TODOS los KPIs operacionales pre-calculados
para que el dashboard de Operaciones cargue instantáneo (lee parquet/JSON
en vez de hacer 13+ queries Odoo en runtime).

Schedule (GH Action):
  - 03:00 UTC = 00:00 Chile
  - 15:00 UTC = 12:00 Chile
(2 veces/día, suficiente para uso operacional según Andrés 2026-05-09)

Output: data/kpis_wms/snapshot.json
"""
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

OUTPUT_DIR = PROJECT_ROOT / "data" / "kpis_wms"
OUTPUT_FILE = OUTPUT_DIR / "snapshot.json"


def _safe_run(label, fn, *args, **kwargs):
    """Ejecuta una función helper capturando excepciones."""
    print(f"[{label}] computando...", flush=True)
    try:
        result = fn(*args, **kwargs)
        print(f"[{label}] OK", flush=True)
        return result
    except Exception as e:
        print(f"[{label}] ERROR: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


def _save_partial(snapshot: dict):
    """Guarda snapshot incremental para que esté disponible aunque crashee.
    Se llama después de cada KPI principal."""
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        print(f"[save_partial] ERROR: {e}", flush=True)


def main():
    print(f"=== Pre-cálculo KPIs WMS — {datetime.now().isoformat()} ===")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Imports tardíos para que el path esté seteado
    from views._ops_wms_helper import (
        kpi_otif, kpi_pick_accuracy, kpi_tiempo_recepcion,
        kpi_volumen_movimientos, top_clientes_otif_problemas,
        kpi_ofr, kpi_oct, kpi_lineas_pickeadas_mes,
        tendencia_mensual, kpi_cobertura_cycle_counts,
        kpi_merma_odoo, kpi_ajustes_inventario,
        plan_auditoria_semanal, productividad_periodo, forecast_volumen_picking,
        kpi_devoluciones_picking_error, productividad_calendario,
    )
    # Limpiar cache de st (no usamos streamlit aquí pero los decorators lo intentan)
    try:
        import streamlit as st
        st.cache_data.clear()
    except Exception:
        pass

    mes_actual = datetime.now().strftime("%Y-%m")

    snapshot = {
        "generado_en": datetime.now().isoformat(),
        "mes_actual": mes_actual,
        "kpis": {},
        "errores": [],
    }

    # === Resumen KPIs (lo que muestra el Tab Resumen) ===
    # Guarda parcial después de cada uno para que el snapshot esté disponible
    # aunque el script crashee a mitad de ejecución.
    snapshot["kpis"]["otif_b2c_30d"] = _safe_run("OTIF B2C 30d", kpi_otif, dias=30, canal_b2b=False); _save_partial(snapshot)
    snapshot["kpis"]["otif_b2b_30d"] = _safe_run("OTIF B2B 30d", kpi_otif, dias=30, canal_b2b=True); _save_partial(snapshot)
    snapshot["kpis"]["pick_accuracy_30d"] = _safe_run("Pick Acc 30d", kpi_pick_accuracy, dias=30); _save_partial(snapshot)
    snapshot["kpis"]["tiempo_recepcion_90d"] = _safe_run("Tiempo Rec 90d", kpi_tiempo_recepcion, dias=90); _save_partial(snapshot)
    snapshot["kpis"]["ofr_30d"] = _safe_run("OFR 30d", kpi_ofr, dias=30); _save_partial(snapshot)
    snapshot["kpis"]["oct_30d"] = _safe_run("OCT 30d", kpi_oct, dias=30); _save_partial(snapshot)
    snapshot["kpis"]["merma_odoo_90d"] = _safe_run("Merma Odoo 90d", kpi_merma_odoo, dias=90); _save_partial(snapshot)
    snapshot["kpis"]["ajustes_inventario"] = _safe_run("Ajustes inv", kpi_ajustes_inventario, desde_fecha="2026-04-01"); _save_partial(snapshot)
    snapshot["kpis"]["lineas_mes_actual"] = _safe_run("Líneas mes", kpi_lineas_pickeadas_mes, mes_actual); _save_partial(snapshot)
    snapshot["kpis"]["volumen_movs_90d"] = _safe_run("Vol movs", kpi_volumen_movimientos, dias=90); _save_partial(snapshot)
    snapshot["kpis"]["top_clientes_otif_30d"] = _safe_run("Top clientes OTIF", top_clientes_otif_problemas, dias=30, top_n=15); _save_partial(snapshot)

    # === Tendencia (6 meses) ===
    snapshot["tendencia_6m"] = _safe_run("Tendencia 6m", tendencia_mensual, meses=6); _save_partial(snapshot)

    # === Forecast operacional ===
    snapshot["forecast_3m"] = _safe_run("Forecast 3m", forecast_volumen_picking, meses_adelante=3); _save_partial(snapshot)

    # === Productividad por período ===
    snapshot["productividad_dia_30d"] = _safe_run("Prod día 30d", productividad_periodo, periodo="dia", n_periodos=30); _save_partial(snapshot)
    snapshot["productividad_semana_12s"] = _safe_run("Prod sem 12s", productividad_periodo, periodo="semana", n_periodos=12); _save_partial(snapshot)
    snapshot["productividad_mes_6m"] = _safe_run("Prod mes 6m", productividad_periodo, periodo="mes", n_periodos=6); _save_partial(snapshot)

    # === Plan auditoría semanal ===
    snapshot["plan_auditoria"] = _safe_run("Plan auditoría", plan_auditoria_semanal, top_n_priorizar=50, dias_sin_ajuste=30); _save_partial(snapshot)

    # === Pick Accuracy REAL (devoluciones por error) ===
    snapshot["kpis"]["devoluciones_picking_error_90d"] = _safe_run(
        "Devoluciones por error 90d", kpi_devoluciones_picking_error, dias=90); _save_partial(snapshot)
    snapshot["kpis"]["devoluciones_picking_error_30d"] = _safe_run(
        "Devoluciones por error 30d", kpi_devoluciones_picking_error, dias=30); _save_partial(snapshot)

    # === Productividad calendario (últimos 12 meses + semanas mes actual + días) ===
    snapshot["productividad_meses_12m"] = _safe_run(
        "Prod meses calendario", productividad_calendario, tipo="mes"); _save_partial(snapshot)
    snapshot["productividad_semanas_mes_actual"] = _safe_run(
        "Prod semanas mes actual", productividad_calendario, tipo="semana_de_mes"); _save_partial(snapshot)
    snapshot["productividad_dias_14d"] = _safe_run(
        "Prod últimos 14 días", productividad_calendario, tipo="dia_especifico"); _save_partial(snapshot)

    # === OTIF para distintas ventanas (para Tab OTIF) ===
    snapshot["otif_ventanas"] = {}
    for dias in [7, 14, 30, 60, 90]:
        snapshot["otif_ventanas"][f"b2c_{dias}d"] = _safe_run(f"OTIF B2C {dias}d", kpi_otif, dias=dias, canal_b2b=False)
        snapshot["otif_ventanas"][f"b2b_{dias}d"] = _safe_run(f"OTIF B2B {dias}d", kpi_otif, dias=dias, canal_b2b=True)

    # === Pick / Tiempo recepción para distintas ventanas ===
    snapshot["pick_ventanas"] = {}
    for dias in [7, 14, 30, 60, 90]:
        snapshot["pick_ventanas"][f"{dias}d"] = _safe_run(f"Pick Acc {dias}d", kpi_pick_accuracy, dias=dias)

    snapshot["recepcion_ventanas"] = {}
    for dias in [30, 60, 90, 180, 365]:
        snapshot["recepcion_ventanas"][f"{dias}d"] = _safe_run(f"Tiempo Rec {dias}d", kpi_tiempo_recepcion, dias=dias)

    # Recolectar errores
    for k, v in snapshot["kpis"].items():
        if isinstance(v, dict) and v.get("error"):
            snapshot["errores"].append(f"{k}: {v['error']}")

    # Guardar
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n=== Snapshot guardado en {OUTPUT_FILE} ===")
    print(f"Tamaño: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")
    print(f"KPIs computados: {len(snapshot['kpis'])}")
    print(f"Errores: {len(snapshot['errores'])}")
    if snapshot["errores"]:
        print("\nERRORES:")
        for e in snapshot["errores"]:
            print(f"  - {e}")

    return 0 if not snapshot["errores"] else 1


if __name__ == "__main__":
    sys.exit(main())
