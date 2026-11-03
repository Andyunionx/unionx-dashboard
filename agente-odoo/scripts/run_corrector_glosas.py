#!/usr/bin/env python3
"""
Corrector de glosas de facturas de proveedor (XML vs Odoo). Ver src/actions/glosas/corrector.py.

USO:
  python agente-odoo/scripts/run_corrector_glosas.py                      # PRUEBA: solo muestra qué haría (default)
  python agente-odoo/scripts/run_corrector_glosas.py --move-id 1175585    # PRUEBA sobre una factura
  python agente-odoo/scripts/run_corrector_glosas.py --aplicar --move-id 1175585   # ESCRIBE una factura
  python agente-odoo/scripts/run_corrector_glosas.py --aplicar            # ESCRIBE todas

Cada corrida deja un JSON en agente-odoo/data/glosas/ con la propuesta (valores antes del cambio)
y, si se aplicó, el resultado por factura.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
AGENTE_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = AGENTE_ROOT.parent
sys.path.insert(0, str(AGENTE_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

from src.actions.glosas.corrector import detectar, aplicar, a_dict

DIR_GLOSAS = AGENTE_ROOT / "data" / "glosas"


def conectar_odoo():
    from app.core.odoo_client import OdooClient
    creds = json.load(open(PROJECT_ROOT / "odoo" / "odoo_config.json"))["produccion"]
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD")
    if not pwd:
        raise RuntimeError("Falta env var ANDRES_ODOO_PASSWORD")
    client = OdooClient(url=creds["url"], db=creds["db_name"], username=creds["username"], password=pwd)
    client.authenticate()
    return client


def main():
    ap = argparse.ArgumentParser(description="Corrector de glosas XML vs Odoo (facturas de proveedor en borrador)")
    ap.add_argument("--aplicar", action="store_true", help="ESCRIBE en Odoo. Sin este flag solo muestra la propuesta.")
    ap.add_argument("--move-id", type=int, help="Solo esta factura (account.move id)")
    args = ap.parse_args()

    modo = "APLICAR" if args.aplicar else "PRUEBA (no escribe)"
    print(f"=== CORRECTOR DE GLOSAS — {datetime.now():%Y-%m-%d %H:%M} — {modo} ===\n")
    client = conectar_odoo()
    propuestas, omitidas = detectar(client, move_id=args.move_id)

    n_lin = sum(len(f.lineas) for f in propuestas)
    print(f"Facturas a corregir: {len(propuestas)} ({n_lin} líneas)\n")
    # El repo es público y sus logs de Actions también: ahí solo conteos, el detalle queda en el chatter de Odoo.
    detalle = not os.environ.get("GITHUB_ACTIONS")
    for f in (propuestas if detalle else []):
        print(f"► {f.documento} · {f.proveedor} · {f.fecha} · neto ${f.total_neto:,.0f}".replace(",", "."))
        for l in f.lineas:
            print(f"   L{l.nro_xml}: «{l.glosa_actual}» → «{l.glosa_nueva}»")
            print(f"       producto quitado: {l.producto} · cuenta {l.cuenta_actual} → {l.cuenta_nueva} ({l.origen_cuenta})")
    if omitidas:
        print(f"\nOmitidas ({len(omitidas)}):")
        for x in (omitidas if detalle else []):
            print(f"   {x.documento} · {x.proveedor}: {x.motivo}")

    DIR_GLOSAS.mkdir(parents=True, exist_ok=True)
    salida = DIR_GLOSAS / f"{'aplicado' if args.aplicar else 'propuesta'}_{datetime.now():%Y%m%d_%H%M%S}.json"
    registro = a_dict(propuestas, omitidas)
    # el respaldo (valores antes del cambio) se escribe ANTES de tocar Odoo
    salida.write_text(json.dumps(registro, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.aplicar and propuestas:
        resultados = aplicar(client, propuestas)
        registro["resultados"] = resultados
        salida.write_text(json.dumps(registro, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\nResultado:")
        for r in resultados:
            print(f"   {r['documento'] if detalle else 'factura id ' + str(r['move_id'])}: {r['estado']}")
    print(f"\nRegistro: {salida}")


if __name__ == "__main__":
    main()
