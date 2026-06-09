#!/usr/bin/env python3
"""Opcion B — Orquestador: SII RCV -> Odoo borradores."""
from __future__ import annotations
import argparse, json, os, sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
AGENTE_ROOT  = SCRIPT_DIR.parent
PROJECT_ROOT = AGENTE_ROOT.parent
sys.path.insert(0, str(AGENTE_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

from src.actions.compras.importador_rcv import listar_y_descargar_rcv
from src.actions.compras.importador_odoo import importar_dte_a_odoo


def conectar_odoo():
    from app.core.odoo_client import OdooClient
    creds = json.load(open(PROJECT_ROOT / "odoo" / "odoo_config.json"))["produccion"]
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD")
    if not pwd:
        raise RuntimeError("Falta env var ANDRES_ODOO_PASSWORD")
    client = OdooClient(url=creds["url"], db=creds["db_name"],
                        username=creds["username"], password=pwd)
    client.authenticate()
    return client


def _folios_en_odoo(client, year: int, month: int) -> set:
    import xmlrpc.client as xc
    uid = client.authenticate()
    models = xc.ServerProxy(f"{client.url}/xmlrpc/2/object", allow_none=True)
    res = models.execute_kw(client.db, uid, client.password, "account.move", "search_read",
        [[["move_type", "in", ["in_invoice", "in_refund"]],
          ["invoice_date", ">=", f"{year:04d}-{month:02d}-01"],
          ["invoice_date", "<=", f"{year:04d}-{month:02d}-28"]]],
        {"fields": ["l10n_latam_document_number", "ref"], "limit": 500})
    folios = set()
    for r in res:
        if r.get("l10n_latam_document_number"):
            folios.add(r["l10n_latam_document_number"])
        ref = str(r.get("ref") or "")
        partes = ref.split()
        if len(partes) >= 2:
            folios.add(partes[-1])
    return folios


def main():
    parser = argparse.ArgumentParser(description="Importador SII RCV -> Odoo")
    parser.add_argument("--mes", type=str, default=None, help="Periodo YYYY-MM")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    hoy = date.today()
    year, month = (int(args.mes[:4]), int(args.mes[5:7])) if args.mes else (hoy.year, hoy.month)

    sii_rut = os.environ.get("SII_RUT", "")
    sii_pwd = os.environ.get("SII_PASSWORD", "")
    if not sii_rut or not sii_pwd:
        print("ERROR: Faltan SII_RUT / SII_PASSWORD")
        sys.exit(1)

    print(f"=== IMPORTADOR SII -> ODOO — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    print(f"    Periodo: {year}-{month:02d}{' (DRY RUN)' if args.dry_run else ''}\n")

    client = conectar_odoo()
    print("✓ Conectado a Odoo\n")

    folios_odoo = _folios_en_odoo(client, year, month)
    print(f"► {len(folios_odoo)} documentos ya en Odoo para {year}-{month:02d}\n")

    print("► Descargando RCV del SII (Playwright)...")
    rcv = listar_y_descargar_rcv(year=year, month=month, rut=sii_rut,
                                  password=sii_pwd, folios_ya_en_odoo=folios_odoo,
                                  headless=False)
    if rcv.errores:
        print(f"  ⚠️  Errores: {rcv.errores}")

    nuevos = [d for d in rcv.dtes if d.xml_bytes]
    print(f"  SII: {rcv.total_sii} | Ya en Odoo: {rcv.ya_en_odoo} | Nuevos: {len(nuevos)}\n")

    if not nuevos:
        print("✓ Sin documentos nuevos.")
        return

    print("► Importando a Odoo...")
    importados = 0
    for dte in nuevos:
        res = importar_dte_a_odoo(client, dte, dry_run=args.dry_run)
        estado = "DRY RUN" if args.dry_run else f"move_id={res.move_id}"
        if res.ok:
            importados += 1
            print(f"  ✓ {res.ref} — {res.partner_nombre} [{estado}]")
        else:
            print(f"  ✗ {dte.tipo_doc}/{dte.folio} — {res.error}")

    print(f"\n✓ Importados: {importados}")
    if args.dry_run:
        print("⚠️  DRY RUN — no se creo nada en Odoo.")


if __name__ == "__main__":
    main()
