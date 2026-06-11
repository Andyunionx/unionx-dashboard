#!/usr/bin/env python3
"""
Opcion B — Orquestador: SII RCV → Odoo borradores → (opcional) predistribucion.

Modos:
  --dry-run      Muestra que haría sin escribir en Odoo
  --mes YYYY-MM  Procesar mes especifico (default: mes actual)
  --full-chain   Tras importar, ejecuta distribucion completa y envia mail
  --test         Con --full-chain, envia mail solo a andres@unionx.cl
"""
from __future__ import annotations
import argparse
import json
import os
import sys
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


def _norm_folio(s) -> str:
    """'002256' / 'FAC 002256' / 2256.0 → '2256' (solo dígitos, sin ceros izq)."""
    digits = "".join(ch for ch in str(s or "") if ch.isdigit())
    return str(int(digits)) if digits else ""


def _norm_rut(v) -> str:
    """'76.243.813-5' → '76243813' (sin puntos, guión ni DV)."""
    v = str(v or "").replace(".", "").replace("-", "").strip().upper()
    return v[:-1] if len(v) > 1 else v


def _folios_en_odoo(client, year: int, month: int) -> set:
    """
    Set de claves (rut_sin_dv, folio_normalizado) de las facturas ya en Odoo.

    Ventana: desde el 1 del mes ANTERIOR hasta fin del mes consultado — el RCV
    incluye docs fechados el mes previo pero recibidos este periodo.
    """
    import xmlrpc.client as xc
    import calendar
    uid = client.authenticate()
    models = xc.ServerProxy(f"{client.url}/xmlrpc/2/object", allow_none=True)

    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    ultimo_dia = calendar.monthrange(year, month)[1]

    res = models.execute_kw(client.db, uid, client.password, "account.move", "search_read",
        [[["move_type", "in", ["in_invoice", "in_refund"]],
          ["invoice_date", ">=", f"{prev_y:04d}-{prev_m:02d}-01"],
          ["invoice_date", "<=", f"{year:04d}-{month:02d}-{ultimo_dia}"]]],
        {"fields": ["l10n_latam_document_number", "ref", "partner_id"], "limit": 1000})

    pids = {r["partner_id"][0] for r in res if r.get("partner_id")}
    vat_por_pid = {}
    if pids:
        partners = models.execute_kw(client.db, uid, client.password, "res.partner", "read",
            [list(pids)], {"fields": ["vat"]})
        vat_por_pid = {p["id"]: p.get("vat") or "" for p in partners}

    claves = set()
    for r in res:
        rut = _norm_rut(vat_por_pid.get(r["partner_id"][0], "")) if r.get("partner_id") else ""
        candidatos = [r.get("l10n_latam_document_number")]
        ref = str(r.get("ref") or "")
        if ref.split():
            candidatos.append(ref.split()[-1])
        for cand in candidatos:
            folio = _norm_folio(cand)
            if folio:
                claves.add((rut, folio))
    return claves


def run_importador(args, year: int, month: int, client) -> int:
    """Importa DTEs faltantes desde SII → Odoo. Retorna cantidad de drafts creados."""
    sii_rut = os.environ.get("SII_RUT", "")
    sii_pwd = os.environ.get("SII_PASSWORD", "")
    if not sii_rut or not sii_pwd:
        print("ERROR: Faltan SII_RUT / SII_PASSWORD")
        return 0

    folios_odoo = _folios_en_odoo(client, year, month)
    print(f"► {len(folios_odoo)} documentos ya en Odoo para {year}-{month:02d}\n")

    print("► Descargando RCV + XMLs del SII (Playwright)...")
    rcv = listar_y_descargar_rcv(
        year=year, month=month,
        rut=sii_rut, password=sii_pwd,
        folios_ya_en_odoo=folios_odoo,
        headless=False,
    )

    if rcv.errores:
        for e in rcv.errores:
            print(f"  ⚠️  {e}")

    con_xml = sum(1 for d in rcv.dtes if d.xml_bytes)
    sin_xml = sum(1 for d in rcv.dtes if not d.xml_bytes and not d.error)
    print(f"  SII total: {rcv.total_sii} | Ya en Odoo: {rcv.ya_en_odoo} | "
          f"Nuevos: {len(rcv.dtes)} (con XML: {con_xml}, sin XML: {sin_xml})\n")

    importables = [d for d in rcv.dtes if not d.error]
    if not importables:
        print("✓ Sin documentos nuevos para importar.")
        return 0

    print("► Importando a Odoo...")
    importados = 0
    for dte in importables:
        res = importar_dte_a_odoo(client, dte, dry_run=args.dry_run)
        if res.ok:
            importados += 1
            xml_tag = "📄 XML" if dte.xml_bytes else "📋 totales"
            dry_tag = " [DRY]" if args.dry_run else f" move={res.move_id}"
            print(f"  ✓ {res.ref} — {res.partner_nombre[:40]} [{xml_tag}{dry_tag}]")
        else:
            print(f"  ✗ {dte.tipo_doc}/{dte.folio} — {res.error}")

    print(f"\n✓ Importados: {importados}")
    if args.dry_run:
        print("⚠️  DRY RUN — no se creó nada en Odoo.")
    return importados


def run_full_chain(args):
    """Importar + distribucion en un solo pipeline. Envia el borrador completo."""
    import importlib
    run_dist = importlib.import_module("run_distribucion")

    dist_args = argparse.Namespace(
        folio=None,
        aplicar=None,
        leer_respuestas=False,
        apply_direct=False,
        excluir_rut=None,
        send_mail=not args.test,
        test=args.test,
        dry_run=args.dry_run,
        aprobado_por="victor@unionx.cl",
    )
    run_dist.cmd_detectar_y_clasificar(dist_args)


def main():
    parser = argparse.ArgumentParser(description="Importador SII RCV → Odoo")
    parser.add_argument("--mes", type=str, default=None, help="Periodo YYYY-MM")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--full-chain", action="store_true",
                        help="Tras importar, ejecuta distribucion completa y envia mail")
    parser.add_argument("--test", action="store_true",
                        help="Con --full-chain, envia mail solo a andres@unionx.cl")
    args = parser.parse_args()

    hoy = date.today()
    year, month = (int(args.mes[:4]), int(args.mes[5:7])) if args.mes else (hoy.year, hoy.month)

    print(f"=== IMPORTADOR SII -> ODOO — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    print(f"    Periodo: {year}-{month:02d}{' (DRY RUN)' if args.dry_run else ''}\n")

    client = conectar_odoo()
    print("✓ Conectado a Odoo\n")

    importados = run_importador(args, year, month, client)

    if args.full_chain:
        print("\n" + "=" * 60)
        print("► Full-chain: ejecutando distribución diaria...\n")
        run_full_chain(args)
    elif importados > 0:
        print(f"\n💡 {importados} draft(s) creados en Odoo.")
        print("   Ejecuta distribucion_diaria o usa --full-chain para predistribuir.")


if __name__ == "__main__":
    main()
