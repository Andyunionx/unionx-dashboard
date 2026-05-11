"""
Extracción de OTIF desde Google Sheet → snapshot JSON.

Script standalone que precalcula los datos OTIF del Sheet
"RESUMEN MENSUAL OTIF" para inyectarlos en data/kpis_wms/snapshot.json.

Schedule (GH Action sync_otif_drive.yml):
  - Día 01 del mes a 03:00 UTC (00:00 Chile)
  - Día 10 del mes a 03:00 UTC (00:00 Chile)
  -> El Sheet OTIF se actualiza 1x/mes, con esto cubrimos el cambio + un
     refresh de seguridad 10 días después.

Modifica/crea data/kpis_wms/snapshot.json sin tocar el resto de KPIs Odoo
(merge inteligente: solo actualiza la sección "otif_drive").
"""
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

OUTPUT_DIR = PROJECT_ROOT / "data" / "kpis_wms"
OUTPUT_FILE = OUTPUT_DIR / "snapshot.json"


def main():
    print(f"=== Extract OTIF Drive — {datetime.now().isoformat()} ===", flush=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Cargar snapshot existente o crear vacío
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                snapshot = json.load(f)
            print(f"Snapshot existente: {len(snapshot.get('kpis', {}))} KPIs Odoo conservados", flush=True)
        except Exception as e:
            print(f"WARN: snapshot existente corrupto, reseteando ({e})", flush=True)
            snapshot = {}
    else:
        snapshot = {}

    # Importar funciones OTIF
    try:
        from views._ops_otif_drive import (
            kpi_otif_resumen, kpi_otif_por_mes, kpi_otif_por_cliente,
            kpi_otif_por_courier, top_pedidos_tarde, meses_disponibles,
            cortes_otif_disponibles, dashboard_otif_corte,
        )
    except Exception as e:
        print(f"ERROR import: {e}", flush=True)
        return 1

    print("\n[1/3] Listando cortes (26-25) y meses disponibles del Sheet…", flush=True)
    try:
        cortes = cortes_otif_disponibles()
        meses_dispon = meses_disponibles()
        print(f"  OK: {len(cortes)} cortes, {len(meses_dispon)} meses", flush=True)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        cortes = []
        meses_dispon = []

    if not cortes and not meses_dispon:
        snapshot["otif_drive"] = {"error": "Sin acceso al Sheet o sin meses con datos"}
    else:
        otif_data = {
            "cortes_disponibles": cortes,
            "meses_disponibles": meses_dispon,
            "por_mes": [],
            "resumen_por_mes": {},
            "clientes_por_mes": {},
            "couriers_por_mes": {},
            "tarde_por_mes": {},
            "dashboard_por_corte": {},  # NUEVO: formato Apps Script
            "generado_en": datetime.now().isoformat(),
        }

        # Tendencia mensual completa
        print(f"\n[2/3] Tendencia mensual…", flush=True)
        try:
            otif_data["por_mes"] = kpi_otif_por_mes()
            print(f"  OK: {len(otif_data['por_mes'])} meses", flush=True)
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)

        # Dashboard por corte (formato Apps Script) — TODOS los disponibles
        # para soportar comparativos año contra año
        print(f"\n[3/3] Dashboard por corte (formato Apps Script) — {len(cortes)} cortes…", flush=True)
        for c in cortes:
            try:
                otif_data["dashboard_por_corte"][c["key"]] = dashboard_otif_corte(c["key"])
                print(f"  {c['key']}: {c['label']} OK", flush=True)
            except Exception as e:
                print(f"  {c['key']}: ERROR {e}", flush=True)

        # Mantener también detalle por mes calendario (compat con view anterior)
        for m in meses_dispon[:6]:
            try:
                otif_data["resumen_por_mes"][m] = kpi_otif_resumen(m)
                otif_data["clientes_por_mes"][m] = kpi_otif_por_cliente(m, top_n=20)
                otif_data["couriers_por_mes"][m] = kpi_otif_por_courier(m)
                otif_data["tarde_por_mes"][m] = top_pedidos_tarde(m, top_n=50)
            except Exception:
                pass

        snapshot["otif_drive"] = otif_data

    # Guardar
    snapshot["otif_drive_actualizado"] = datetime.now().isoformat()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n=== OTIF Drive snapshot guardado en {OUTPUT_FILE} ===", flush=True)
    print(f"Tamaño: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
