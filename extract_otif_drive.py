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
        )
    except Exception as e:
        print(f"ERROR import: {e}", flush=True)
        return 1

    print("\n[1/2] Listando meses disponibles del Sheet…", flush=True)
    try:
        meses_dispon = meses_disponibles()
        print(f"  OK: {len(meses_dispon)} meses", flush=True)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        meses_dispon = []

    if not meses_dispon:
        snapshot["otif_drive"] = {"error": "Sin acceso al Sheet o sin meses con datos"}
    else:
        print(f"\n[2/2] Pre-cálculo OTIF para top 6 meses ({meses_dispon[:6]})…", flush=True)
        otif_data = {
            "meses_disponibles": meses_dispon,
            "por_mes": [],
            "resumen_por_mes": {},
            "clientes_por_mes": {},
            "couriers_por_mes": {},
            "tarde_por_mes": {},
            "generado_en": datetime.now().isoformat(),
        }

        # Tendencia mensual completa
        try:
            otif_data["por_mes"] = kpi_otif_por_mes()
            print(f"  Tendencia mensual: {len(otif_data['por_mes'])} meses", flush=True)
        except Exception as e:
            print(f"  ERROR tendencia: {e}", flush=True)

        # Top 6 meses con detalle
        for m in meses_dispon[:6]:
            try:
                otif_data["resumen_por_mes"][m] = kpi_otif_resumen(m)
                otif_data["clientes_por_mes"][m] = kpi_otif_por_cliente(m, top_n=20)
                otif_data["couriers_por_mes"][m] = kpi_otif_por_courier(m)
                otif_data["tarde_por_mes"][m] = top_pedidos_tarde(m, top_n=50)
                print(f"  {m}: OK", flush=True)
            except Exception as e:
                print(f"  {m}: ERROR {e}", flush=True)

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
