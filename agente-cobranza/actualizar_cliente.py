#!/usr/bin/env python3
"""
Agente Cobranza — actualiza el Excel de cobranza de UN cliente leyendo Odoo.

Reemplaza los scripts originales de Martín (rebuild_meli_final.py,
rebuild_falabella.py, rebuild_shopify.py, rebuild_paris.py) por un solo
script parametrizado que lee la config desde YAML.

USO:
  # Procesar un cliente
  python actualizar_cliente.py --config clientes/paris.yaml

  # Modo dry-run: descarga de Odoo y genera el Excel local, SIN tocar Drive
  python actualizar_cliente.py --config clientes/paris.yaml --dry-run

  # Procesar TODOS los clientes (uno por archivo en clientes/)
  python actualizar_cliente.py --todos

VARS DE ENTORNO REQUERIDAS:
  ODOO_URL          (default https://unionxb2b.odoo.com)
  ODOO_DB           (default bmya-innovatek-sh-prd-6981800)
  ODOO_USER         email
  ODOO_PASSWORD     password
  GOOGLE_CREDENTIALS_JSON  (JSON del service account, para Drive)

  En GitHub Actions estos vienen de Secrets. Localmente:
  - ANDRES_ODOO_PASSWORD / OPS_ODOO_PASSWORD se autodetectan si están
  - credentials.json en repo root como fallback si falta GOOGLE_CREDENTIALS_JSON
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import yaml  # PyYAML

AGENT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_ROOT))

from lib.odoo_helpers import (  # noqa: E402
    conectar_odoo,
    descargar_bol_pendiente, descargar_revertidos, descargar_nc,
    descargar_facturas_pendientes, descargar_pagadas, descargar_yuju,
    filas_para_hoja_documentos, filas_para_hoja_nc, filas_para_hoja_yuju,
    obtener_rut_por_partner, obtener_doc_name_por_id,
)
from lib.excel_updater import actualizar_excel  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG LOAD
# ─────────────────────────────────────────────────────────────────────────────
def cargar_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Validaciones mínimas
    requeridos = ["nombre", "slug", "partners", "excel"]
    for r in requeridos:
        if r not in cfg:
            raise ValueError(f"Config inválida: falta '{r}' en {path}")
    if not cfg["partners"].get("todos"):
        raise ValueError(f"Config inválida: partners.todos vacío en {path}")
    if not cfg["excel"].get("drive_path"):
        raise ValueError(f"Config inválida: excel.drive_path vacío en {path}")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# PROCESO DE UN CLIENTE
# ─────────────────────────────────────────────────────────────────────────────
def procesar_cliente(config_path: Path, dry_run: bool = False,
                       output_suffix_override: str | None = None,
                       no_upload: bool = False) -> dict:
    """Procesa un cliente. Retorna dict con stats para el log."""
    cfg = cargar_config(config_path)
    nombre = cfg["nombre"]
    slug = cfg["slug"]

    print(f"\n{'='*78}", flush=True)
    print(f"  Procesando: {nombre}  (slug: {slug})", flush=True)
    print(f"  Config:     {config_path.name}", flush=True)
    print(f"  Dry-run:    {dry_run}", flush=True)
    print(f"{'='*78}", flush=True)

    # ─── 1. CONECTAR ODOO ─────────────────────────────────────────────────
    # El agente usa el usuario de Víctor (dueño funcional del proceso).
    # En producción (GitHub Actions) los valores vienen del workflow.
    # Localmente se aceptan fallbacks para que cualquiera con creds pueda testear.
    odoo_url = os.environ.get("ODOO_URL", "https://unionxb2b.odoo.com")
    odoo_db = os.environ.get("ODOO_DB", "bmya-innovatek-sh-prd-6981800")
    odoo_user = (
        os.environ.get("ODOO_USER")            # Workflow lo setea
        or os.environ.get("VICTOR_ODOO_USER")  # Local con Víctor
        or os.environ.get("ANDRES_ODOO_USER")  # Local con Andrés
        or os.environ.get("OPS_ODOO_USER")
        or "victor@grupoeter.cl"               # default: dueño funcional
    )
    odoo_pwd = (
        os.environ.get("ODOO_PASSWORD")
        or os.environ.get("VICTOR_ODOO_PASSWORD")
        or os.environ.get("ANDRES_ODOO_PASSWORD")
        or os.environ.get("OPS_ODOO_PASSWORD")
    )
    if not odoo_pwd:
        raise EnvironmentError(
            "Falta password de Odoo. En producción se setea VICTOR_ODOO_PASSWORD "
            "como GitHub Secret. Localmente: export ODOO_PASSWORD=... antes de correr."
        )

    print(f"\n[1/4] Conectando a Odoo {odoo_url} como {odoo_user}...", flush=True)
    odoo = conectar_odoo(odoo_url, odoo_db, odoo_user, odoo_pwd)

    # ─── 2. DESCARGAR LAS 6 HOJAS ─────────────────────────────────────────
    partners = cfg["partners"]
    p_todos = partners["todos"]
    p_boletas = partners.get("boletas") or p_todos
    p_facturas = partners.get("facturas") or p_todos

    ventanas = cfg.get("ventanas_dias") or {}
    dias_pagadas = abs(int(ventanas.get("pagadas") or -300))
    dias_yuju = abs(int(ventanas.get("yuju") or -200))

    print(f"\n[2/4] Descargando hojas desde Odoo...", flush=True)
    print(f"  partners todos:    {p_todos}", flush=True)
    print(f"  partners boletas:  {p_boletas}", flush=True)
    print(f"  partners facturas: {p_facturas}", flush=True)

    docs_bol = descargar_bol_pendiente(odoo, p_boletas)
    print(f"  BOL PENDIENTE DE PAGO:        {len(docs_bol):>6,}", flush=True)

    docs_rev = descargar_revertidos(odoo, p_boletas)
    print(f"  REVERTIDOS:                   {len(docs_rev):>6,}", flush=True)

    docs_nc = descargar_nc(odoo, p_boletas)
    print(f"  NC:                           {len(docs_nc):>6,}", flush=True)

    docs_fac = descargar_facturas_pendientes(odoo)
    print(f"  FACTURAS PENDIENTES (global): {len(docs_fac):>6,}", flush=True)

    docs_pag = descargar_pagadas(odoo, p_todos, dias_pagadas)
    print(f"  PAGADAS (últimos {dias_pagadas}d):     {len(docs_pag):>6,}", flush=True)

    sos = descargar_yuju(odoo, p_todos, dias_yuju)
    print(f"  yuju (últimos {dias_yuju}d):        {len(sos):>6,}", flush=True)

    # ─── 2.5. LOOKUPS EXTRA (RUT + names de facturas referenciadas) ──────
    # Para producir el formato byte-compatible con Martin necesitamos:
    #   - RUT del partner (no viene en account.move)
    #   - Name de cada move_id referenciado en sale_order.invoice_ids (hoja yuju)
    print(f"\n[2.5/4] Resolviendo RUTs de partners + names de facturas referenciadas...",
          flush=True)
    todos_partner_ids = set()
    for docs in (docs_bol, docs_rev, docs_nc, docs_fac, docs_pag):
        for d in docs:
            if d.get("partner_id"):
                todos_partner_ids.add(d["partner_id"][0])
    rut_por_partner = obtener_rut_por_partner(odoo, list(todos_partner_ids))
    print(f"  RUTs resueltos: {len(rut_por_partner)}", flush=True)

    move_ids_referenciados = set()
    for so in sos:
        for mid in (so.get("invoice_ids") or []):
            move_ids_referenciados.add(mid)
    move_name_por_id = obtener_doc_name_por_id(odoo, list(move_ids_referenciados))
    print(f"  Move names resueltos: {len(move_name_por_id)}", flush=True)

    # ─── 3. CONSTRUIR HOJAS PARA EXCEL ────────────────────────────────────
    hojas_data = {
        "BOL PENDIENTE DE PAGO":      filas_para_hoja_documentos(docs_bol, rut_por_partner),
        "REVERTIDOS":                  filas_para_hoja_documentos(docs_rev, rut_por_partner),
        "NC":                          filas_para_hoja_nc(docs_nc, rut_por_partner),
        "FACTURAS PENDIENTES DE PAGO": filas_para_hoja_documentos(docs_fac, rut_por_partner),
        "PAGADAS":                     filas_para_hoja_documentos(docs_pag, rut_por_partner),
        "yuju":                        filas_para_hoja_yuju(sos, move_name_por_id),
    }

    # ─── 4. BAJAR / ACTUALIZAR / SUBIR EXCEL ──────────────────────────────
    drive_path = cfg["excel"]["drive_path"]
    output_suffix = (output_suffix_override
                      or cfg["excel"].get("output_suffix")
                      or "_ACTUALIZADO")
    hojas_preservar = cfg["excel"].get("hojas_preservar") or []
    xlookup_setup = cfg.get("xlookup_setup") or []

    workdir = AGENT_ROOT / "tmp" / slug
    workdir.mkdir(parents=True, exist_ok=True)

    print(f"\n[3/4] Bajando Excel original de Drive...", flush=True)
    print(f"  drive_path: {drive_path}", flush=True)

    if dry_run:
        # Dry-run: usar copia local si existe, sino fallar amable
        local_original = workdir / f"{slug}_dryrun_input.xlsx"
        if not local_original.exists():
            # Generar uno vacío para dry-run
            from openpyxl import Workbook
            wb = Workbook()
            wb.active.title = "Placeholder"
            wb.save(local_original)
            print(f"  [DRY-RUN] Sin original real, usando workbook vacío en {local_original}",
                  flush=True)
        file_id_original = None
        file_id_actualizado = None
    else:
        from lib.drive_helpers import descargar_o_crear_actualizado
        local_original, file_id_original, file_id_actualizado = (
            descargar_o_crear_actualizado(drive_path, output_suffix, workdir=workdir)
        )
        print(f"  Original local:   {local_original}", flush=True)
        print(f"  file_id orig:     {file_id_original}", flush=True)
        print(f"  file_id ACT:      {file_id_actualizado or '(será creado)'}", flush=True)

    # Actualizar Excel
    base, ext = os.path.splitext(local_original.name)
    nombre_actualizado = f"{base}{output_suffix}{ext}"
    local_actualizado = workdir / nombre_actualizado

    print(f"\n[4/4] Actualizando hojas + escribiendo Excel...", flush=True)
    actualizar_excel(
        path_original=local_original,
        path_destino=local_actualizado,
        hojas_data=hojas_data,
        hojas_preservar=hojas_preservar,
        xlookup_setup=xlookup_setup,
    )
    print(f"  Excel actualizado: {local_actualizado}", flush=True)

    # Subir a Drive (si no es dry-run y no es --no-upload)
    if dry_run or no_upload:
        if no_upload:
            print(f"  --no-upload: el Excel queda solo local en {local_actualizado}",
                  flush=True)
    else:
        from lib.drive_helpers import (
            actualizar_archivo, buscar_carpeta_por_path, subir_archivo,
        )
        if file_id_actualizado:
            actualizar_archivo(file_id_actualizado, local_actualizado)
            print(f"  Drive: actualizado existing file_id {file_id_actualizado}",
                  flush=True)
        else:
            # Crear nuevo en la misma carpeta del original.
            # NOTA: las service accounts NO pueden crear archivos nuevos en
            # "Mi unidad" — falla con storageQuotaExceeded. Soluciones:
            #   - Andrés crea manualmente el archivo destino vacío y lo
            #     comparte con el bot (después del 1er run, el bot ya hace
            #     update y todo OK)
            #   - O mover los archivos a un Shared Drive (Team Drive)
            carpeta_path = "/".join(drive_path.split("/")[:-1])
            carpeta_id = buscar_carpeta_por_path(carpeta_path)
            if not carpeta_id:
                raise RuntimeError(f"No se encontró carpeta destino: {carpeta_path}")
            try:
                new_id = subir_archivo(local_actualizado, carpeta_id, nombre_actualizado)
                print(f"  Drive: creado nuevo file_id={new_id}", flush=True)
            except Exception as e:
                if "storageQuotaExceeded" in str(e):
                    raise RuntimeError(
                        f"\n\nNO SE PUEDE CREAR archivo nuevo en Drive con service account.\n"
                        f"Solucion: pedir a Andres que cree manualmente el archivo destino:\n"
                        f"  {drive_path.rsplit('/', 1)[0]}/{nombre_actualizado}\n"
                        f"  (puede ser un Excel vacio) y compartirlo con el bot.\n"
                        f"Despues del primer run, las actualizaciones siguientes funcionan OK.\n"
                    ) from e
                raise

    return {
        "cliente": nombre,
        "slug": slug,
        "stats": {
            "bol_pendiente":     len(docs_bol),
            "revertidos":        len(docs_rev),
            "nc":                len(docs_nc),
            "facturas_global":   len(docs_fac),
            "pagadas":           len(docs_pag),
            "yuju":              len(sos),
        },
        "local_actualizado": str(local_actualizado),
        "dry_run": dry_run,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="Agente Cobranza: actualiza Excel de cliente leyendo Odoo",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--config", type=Path,
                    help="Path al YAML del cliente (ej: clientes/paris.yaml)")
    g.add_argument("--todos", action="store_true",
                    help="Procesar todos los YAML en clientes/ (excepto _template)")
    ap.add_argument("--dry-run", action="store_true",
                     help="No toca Drive (ni descarga ni sube). Genera Excel desde un workbook vacío.")
    ap.add_argument("--no-upload", action="store_true",
                     help="Descarga el original real de Drive y procesa, pero NO sube el resultado. "
                          "El Excel queda solo local. Útil para validar paridad sin tocar producción.")
    ap.add_argument("--output-suffix", default=None,
                     help="Override del sufijo del archivo de salida (default: _ACTUALIZADO del YAML). "
                          "Útil para tests: --output-suffix _AGENTE_TEST evita pisar el archivo de Martín.")
    args = ap.parse_args()

    if args.todos:
        configs = sorted(p for p in (AGENT_ROOT / "clientes").glob("*.yaml")
                          if not p.name.startswith("_"))
        if not configs:
            print("[ERROR] No hay configs en clientes/", flush=True)
            return 1
        print(f"Procesando {len(configs)} cliente(s): "
              f"{[c.stem for c in configs]}", flush=True)
    else:
        configs = [args.config]

    resultados = []
    errores = []
    inicio = datetime.now()

    for cfg_path in configs:
        try:
            res = procesar_cliente(cfg_path, dry_run=args.dry_run,
                                     output_suffix_override=args.output_suffix,
                                     no_upload=args.no_upload)
            resultados.append(res)
        except Exception as e:
            print(f"\n[ERROR] {cfg_path.name}: {e}", flush=True)
            traceback.print_exc()
            errores.append({"config": str(cfg_path), "error": str(e)})

    # ─── Resumen final ────────────────────────────────────────────────────
    duracion = (datetime.now() - inicio).total_seconds()
    print(f"\n{'='*78}")
    print(f"  RESUMEN — Duración: {duracion:.0f}s")
    print(f"{'='*78}")
    print(f"  Procesados OK:  {len(resultados)}")
    print(f"  Errores:        {len(errores)}")
    if resultados:
        print(f"\n  Por cliente:")
        for r in resultados:
            s = r["stats"]
            print(f"   ✓ {r['cliente']:30s}  "
                  f"BOL:{s['bol_pendiente']:>5}  "
                  f"NC:{s['nc']:>4}  "
                  f"PAG:{s['pagadas']:>5}  "
                  f"yuju:{s['yuju']:>5}")
    if errores:
        print(f"\n  Errores detallados:")
        for e in errores:
            print(f"   ✗ {e['config']}: {e['error']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
