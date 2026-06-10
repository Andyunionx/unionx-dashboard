#!/usr/bin/env python3
"""
Orquestador del módulo Distribución de Servicios.

Criterios de detección:
  1. Factura de proveedor (in_invoice / in_refund)
  2. Estado borrador (draft)
  3. Al menos una línea en cuenta 42410104 (COMISIÓN GRANDES CUENTAS)
  4. Excluye Liquidaciones-Factura (documentos FAL)

USO:
  python agente-odoo/scripts/run_distribucion.py              # detecta + clasifica + genera Excel
  python agente-odoo/scripts/run_distribucion.py --test       # envía solo a andres@unionx.cl
  python agente-odoo/scripts/run_distribucion.py --send-mail  # envía a Camila + Victor
  python agente-odoo/scripts/run_distribucion.py --leer-respuestas   # lee respuestas Gmail
  python agente-odoo/scripts/run_distribucion.py --apply-direct      # aplica sin aprobación
  python agente-odoo/scripts/run_distribucion.py --folio 11381602    # solo esa factura
  python agente-odoo/scripts/run_distribucion.py --excluir-rut 96999930-7  # excluir RUT
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

from src.actions.distribucion.detector import detectar_facturas_pendientes
from src.actions.distribucion.clasificador import clasificar_factura
from src.actions.distribucion.template_excel import generar_excel_aprobacion
from src.actions.distribucion.memoria import cargar_memoria, resumen_memoria
from src.actions.distribucion.aplicador import aplicar_distribucion, aplicar_directo
from src.actions.distribucion.gmail_distribucion import (
    send_propuesta_completa, leer_respuestas, ya_enviado_hoy)
from src.actions.distribucion.analisis_ruts import detectar_ruts_sin_partner
from datetime import date as _date

TOKEN_GMAIL  = PROJECT_ROOT / "agente-comex" / "config" / "token.json"

PROVEEDORES_INGRESO_MANUAL = {
    "77398220-1": {"nombre": "MercadoLibre Chile Ltda.", "portal": "Seller Center ML"},
    "76516950-K": {"nombre": "Mercado Pago Operadora S.A.", "portal": "Portal Mercado Pago"},
    "96874030-K": {"nombre": "ABC S.A.", "portal": "Portal ABC"},
}


def _detectar_faltantes_ingreso_manual(client, year: int, month: int) -> list[dict]:
    import xmlrpc.client as xc
    URL = client.url; DB = client.db; PWD = client.password
    uid = client.authenticate()
    models = xc.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)
    mes_inicio = f"{year:04d}-{month:02d}-01"
    mes_fin    = f"{year:04d}-{month:02d}-28"
    faltantes = []
    for rut, meta in PROVEEDORES_INGRESO_MANUAL.items():
        este_mes = models.execute_kw(DB, uid, PWD, "account.move", "search_read",
            [[["move_type", "in", ["in_invoice", "in_refund"]],
              ["partner_id.vat", "=", rut],
              ["invoice_date", ">=", mes_inicio], ["invoice_date", "<=", mes_fin]]],
            {"fields": ["id"], "limit": 1})
        if este_mes:
            continue
        ultimo = models.execute_kw(DB, uid, PWD, "account.move", "search_read",
            [[["move_type", "in", ["in_invoice", "in_refund"]], ["partner_id.vat", "=", rut]]],
            {"fields": ["invoice_date", "create_date", "create_uid", "ref", "name"],
             "limit": 1, "order": "invoice_date desc"})
        ultimo_doc = ultimo[0] if ultimo else None
        faltantes.append({
            "rut": rut, "nombre": meta["nombre"], "portal": meta["portal"],
            "ultimo_doc": (ultimo_doc.get("ref") or ultimo_doc.get("name")) if ultimo_doc else "—",
            "ultimo_fecha": ultimo_doc.get("invoice_date", "—") if ultimo_doc else "—",
            "ingresado_por": (ultimo_doc.get("create_uid") or [None, "—"])[1] if ultimo_doc else "—",
        })
    return faltantes
DIR_DISTRIBUCION = AGENTE_ROOT / "data" / "distribucion"
DIR_MEMORIA  = AGENTE_ROOT / "data" / "memoria_distribucion"


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


def _leer_resumen_sii_csv(sii_dir: Path, anio: int, mes: int) -> dict:
    """Lee el CSV de resumen del SII (totales por tipo de documento)."""
    archivo = sii_dir / f"libro_compras_{anio:04d}-{mes:02d}.xlsx"
    if not archivo.exists():
        return {}
    try:
        contenido = archivo.read_text(encoding="utf-8", errors="replace")
        if "Tipo Documento" not in contenido:
            return {}
        total_docs = 0
        monto_neto = 0.0
        for linea in contenido.splitlines()[1:]:  # skip header
            partes = linea.split(";")
            if len(partes) >= 4:
                try:
                    total_docs += int(partes[1])
                    monto_neto  += float(partes[3])
                except (ValueError, IndexError):
                    pass
        return {"total_docs": total_docs, "monto_total": monto_neto}
    except Exception:
        return {}


def cmd_detectar_y_clasificar(args):
    print(f"=== DISTRIBUCIÓN SERVICIOS — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    client = conectar_odoo()
    print("✓ Conectado a Odoo producción\n")

    print("► Detectando facturas con líneas en 42410104...")
    facturas = detectar_facturas_pendientes(
        odoo_client=client,
        estados=["draft"],
        limite=50,
        folio_especifico=args.folio,
    )

    # Filtrar por exclusión de RUTs
    if hasattr(args, "excluir_rut") and args.excluir_rut:
        excluidos = {r.strip() for r in args.excluir_rut.split(",")}
        facturas = [f for f in facturas if f.partner_rut not in excluidos]

    # Excluir Liquidaciones-Factura (FAL)
    facturas_fal = [f for f in facturas if f.name.upper().startswith("FAL")]
    facturas = [f for f in facturas if not f.name.upper().startswith("FAL")]
    if facturas_fal:
        print(f"  (Excluidas {len(facturas_fal)} liquidaciones FAL: "
              f"{', '.join(f.name for f in facturas_fal)})")

    # ── Análisis paralelo: RUTs sin partner ───────────────────────────────
    print("► Detectando proveedores sin RUT configurado en Odoo (últimos 30 días)...")
    ruts_sin_partner = detectar_ruts_sin_partner(client, dias=30)
    if ruts_sin_partner:
        print(f"  ⚠️  {len(ruts_sin_partner)} proveedor(es) sin RUT:")
        for r in ruts_sin_partner[:5]:
            print(f"    • {r.partner_nombre} | {r.n_facturas} facturas | ${r.monto_total:,.0f}")
    else:
        print("  ✓ Todos los proveedores tienen RUT configurado")
    print()

    # ── Proveedores de ingreso manual (ML, MP, ABC) ───────────────────────
    hoy_obj = _date.today()
    print(f"► Verificando ingreso de proveedores manuales ({hoy_obj.year}-{hoy_obj.month:02d})...")
    try:
        faltantes_manual = _detectar_faltantes_ingreso_manual(client, hoy_obj.year, hoy_obj.month)
        if faltantes_manual:
            print(f"  ⚠️  {len(faltantes_manual)} proveedor(es) sin ingresar este mes:")
            for f in faltantes_manual:
                print(f"    • {f['nombre']} | último doc: {f['ultimo_doc']} ({f['ultimo_fecha']})")
        else:
            print("  ✓ Todos los proveedores manuales ya tienen facturas este mes")
    except Exception as e:
        print(f"  (Error verificando proveedores manuales: {e})")
        faltantes_manual = []
    print()

    # ── Análisis SII vs Odoo ───────────────────────────────────────────────
    comparacion_sii = None
    print("► Comparando SII vs Odoo (faltantes en Odoo)...")
    try:
        from src.actions.compras.descarga_sii import descargar_mes_actual_y_anterior
        from src.actions.compras.sii_parser import parse_libro_sii, cargar_directorio
        from src.actions.compras.odoo_compras import OdooCompras
        from src.actions.compras.compara_sii_odoo import comparar
        from datetime import date

        sii_rut = os.environ.get("SII_RUT", "")
        sii_pwd = os.environ.get("SII_PASSWORD", "")

        if sii_rut and sii_pwd:
            from src.actions.compras.descarga_sii import descargar_detalle_compras

            # Intentar descargar el DETALLE (Descargas Diferidas) — comparación exacta
            hoy_d = date.today()
            resultado_detalle = descargar_detalle_compras(
                hoy_d.year, hoy_d.month,
                rut=sii_rut, password=sii_pwd,
                headless=True,
                esperar_generacion_seg=300,  # esperar hasta 5 min
            )
            if resultado_detalle["estado"] == "descargado":
                print(f"  ✓ Detalle SII descargado: {resultado_detalle['archivo'].name}")
            elif resultado_detalle["estado"] == "solicitado":
                print("  📋 Detalle SII solicitado — estará listo en la próxima corrida")
                # Mientras tanto, descargar el resumen para comparación de totales
                resultados_resumen = descargar_mes_actual_y_anterior(rut=sii_rut, password=sii_pwd)
                descargados = [r for r in resultados_resumen if r["ok"]]
                if descargados:
                    print(f"  ✓ Resumen SII descargado ({len(descargados)} mes/es)")
            else:
                print(f"  ⚠️  Error SII: {resultado_detalle['error']}")
                resultados_resumen = descargar_mes_actual_y_anterior(rut=sii_rut, password=sii_pwd)
                descargados = [r for r in resultados_resumen if r["ok"]]
                if descargados:
                    print(f"  ✓ Resumen SII (fallback): {len(descargados)} mes/es")
        else:
            print("  (SII_RUT/SII_PASSWORD no configurados — skip descarga automática)")

        # Intentar leer archivos ya existentes en disco
        sii_dir = PROJECT_ROOT / "data" / "contabilidad" / "sii"
        compras_sii = cargar_directorio(sii_dir) if sii_dir.exists() else []

        if compras_sii:
            hoy = date.today()
            oc = OdooCompras(client)
            compras_odoo = []
            for mes_offset in [0, 1]:
                m = hoy.month - mes_offset
                y = hoy.year
                if m <= 0:
                    m += 12; y -= 1
                compras_odoo.extend(oc.listar_compras_mes(y, m))

            periodo = f"{hoy.year}-{hoy.month:02d}"
            comparacion_sii = comparar(compras_sii, compras_odoo, periodo)
            print(f"  SII: {comparacion_sii.total_sii} docs | "
                  f"Odoo: {comparacion_sii.total_odoo} docs | "
                  f"Faltantes en Odoo: {len(comparacion_sii.faltantes_en_odoo)}")
        else:
            # Los archivos descargados son resumen CSV (no detalle).
            # Comparar totales Odoo vs totales SII usando el CSV de resumen.
            hoy = date.today()
            resumen_sii = _leer_resumen_sii_csv(sii_dir, hoy.year, hoy.month)
            if resumen_sii:
                oc = OdooCompras(client)
                compras_odoo = oc.listar_compras_mes(hoy.year, hoy.month)
                total_odoo = sum(c.get("amount_total", 0) for c in compras_odoo)
                print(f"  SII (resumen): {resumen_sii['total_docs']} docs, "
                      f"${resumen_sii['monto_total']:,.0f} neto")
                print(f"  Odoo: {len(compras_odoo)} docs, ${total_odoo:,.0f} total")
                comparacion_sii = type('SIIResumen', (), {
                    'faltantes_en_odoo': [],
                    'total_sii': resumen_sii['total_docs'],
                    'total_odoo': len(compras_odoo),
                    '_resumen': resumen_sii,
                    '_odoo_total': total_odoo,
                })()
            else:
                print("  (Sin libro SII en disco — subir a data/contabilidad/sii/ para comparar)")
    except Exception as e:
        print(f"  (Error en análisis SII: {e})")
    print()

    if not facturas:
        print("✓ No hay facturas pendientes de distribución.\n")
        # Igual enviamos el mail con las otras secciones (RUTs + SII)
        if args.test or args.send_mail:
            if args.send_mail and not args.test and ya_enviado_hoy(TOKEN_GMAIL):
                print("► Mail de análisis diario ya enviado hoy — skip (pulso 1x/día)")
                return []
            print("► Enviando mail de análisis diario (sin distribuciones hoy)...")
            if args.test:
                destinatarios = ["andres@unionx.cl"]; cc = []
                print("  [MODO PRUEBA] Solo a andres@unionx.cl")
            else:
                destinatarios = ["camila@unionx.cl", "victor@unionx.cl"]
                cc = ["andres@unionx.cl"]
            resultado_mail = send_propuesta_completa(
                excels=[],
                facturas_resumen=[],
                ruts_sin_partner=ruts_sin_partner,
                faltantes_manual=faltantes_manual,
                comparacion_sii=comparacion_sii,
                token_path=TOKEN_GMAIL,
                destinatarios=destinatarios,
                cc=cc,
            )
            if resultado_mail["ok"]:
                print(f"  ✓ Mail enviado (message_id={resultado_mail['message_id']})")
            else:
                print(f"  ✗ Error: {resultado_mail['error']}")
        return []

    print(f"  {len(facturas)} factura(s) encontradas:\n")
    for f in facturas:
        n = len([l for l in f.lineas if l.cuenta_actual_id == 1377])
        print(f"  • {f.name} | {f.partner_nombre} | ${f.monto_total:,.0f} | {n} líneas en 42410104")
    print()

    # Clasificar todas
    resultados_clasificados = []
    for factura in facturas:
        print(f"► Clasificando {factura.name} ({factura.partner_nombre})...")
        memoria = cargar_memoria(factura.partner_rut)
        resultado = clasificar_factura(factura, memoria)
        resultados_clasificados.append(resultado)
        for linea in resultado.lineas:
            estado = "🟢 AUTO" if linea.auto_aplicado else "🟡 REVISAR"
            print(f"    {estado} | '{linea.glosa[:55]}' → {linea.cuenta_codigo} ({linea.confianza:.0%})")
        print()

    # Modo apply-direct: aplica en Odoo sin aprobación
    if hasattr(args, "apply_direct") and args.apply_direct:
        print("► Aplicando directamente en Odoo (sin aprobación)...\n")
        total_ok = total_err = 0
        for resultado in resultados_clasificados:
            fa = aplicar_directo(client, resultado, dry_run=args.dry_run)
            if fa.confirmada:
                total_ok += 1
            if fa.errores:
                total_err += 1
        print()
        print(f"Resumen: {total_ok} factura(s) confirmadas, {total_err} con errores")
        if args.dry_run:
            print("(DRY RUN — no se escribió en Odoo)")
        return []

    # Generar UN SOLO Excel con todas las facturas
    dir_output = str(DIR_DISTRIBUCION)
    excel_path = generar_excel_aprobacion(resultados_clasificados, directorio_output=dir_output)
    excels_generados = [(r.factura, excel_path) for r in resultados_clasificados]
    print(f"✓ Excel unificado: {excel_path.name}\n")
    print("=" * 60)
    print(f"✓ Excel generado: {excel_path.name}\n")

    if args.test or args.send_mail:
        if args.send_mail and not args.test and ya_enviado_hoy(TOKEN_GMAIL):
            print("► Mail de análisis diario ya enviado hoy — skip (pulso 1x/día)")
            print(f"  Excel disponible en: agente-odoo/data/distribucion/{excel_path.name}")
            return excels_generados
        print("► Enviando correo...")
        resumen_facturas = [
            {
                "proveedor": f.partner_nombre,
                "folio": f.folio,
                "fecha": f.fecha or "",
                "monto_total": f.monto_total,
                "n_lineas": len([l for l in f.lineas if l.cuenta_actual_id == 1377]),
            }
            for f, _ in excels_generados
        ]

        if args.test:
            destinatarios = ["andres@unionx.cl"]
            cc = []
            print("  [MODO PRUEBA] Enviando solo a andres@unionx.cl")
        else:
            destinatarios = ["camila@unionx.cl", "victor@unionx.cl"]
            cc = ["andres@unionx.cl"]

        resultado_mail = send_propuesta_completa(
            excels=[excel_path] if excels_generados else [],
            facturas_resumen=resumen_facturas,
            ruts_sin_partner=ruts_sin_partner,
            faltantes_manual=faltantes_manual,
            comparacion_sii=comparacion_sii,
            token_path=TOKEN_GMAIL,
            destinatarios=destinatarios,
            cc=cc,
        )
        if resultado_mail["ok"]:
            print(f"  ✓ Mail enviado (message_id={resultado_mail['message_id']})")
            print(f"  TO: {', '.join(destinatarios)}" + (f" | CC: {', '.join(cc)}" if cc else ""))
        else:
            print(f"  ✗ Error enviando mail: {resultado_mail['error']}")
    else:
        print(f"  Excel listo en: agente-odoo/data/distribucion/{excel_path.name}")
        print("  Para enviar: agregar flag --send-mail (Camila+Victor) o --test (solo Andrés)")

    print()
    return excels_generados


def cmd_leer_respuestas(args):
    print(f"=== LEYENDO RESPUESTAS — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    print("► Buscando respuestas de Camila/Victor en Gmail (últimas 48h)...")
    respuestas = leer_respuestas(token_path=TOKEN_GMAIL, desde_horas=48)

    if not respuestas:
        print("  Sin respuestas nuevas por el momento.")
        return

    print(f"  {len(respuestas)} respuesta(s) encontrada(s)\n")
    client = conectar_odoo()

    for resp in respuestas:
        print(f"► De: {resp['sender']} | Asunto: {resp['subject']}")
        print(f"  {len(resp['adjuntos'])} Excel(s) adjunto(s)")

        for adjunto in resp["adjuntos"]:
            if not adjunto["nombre"].endswith(".xlsx"):
                continue

            tmp_path = DIR_DISTRIBUCION / f"aprobado_{adjunto['nombre']}"
            tmp_path.write_bytes(adjunto["contenido_bytes"])
            print(f"  Procesando: {adjunto['nombre']}...")

            resultado = aplicar_distribucion(
                odoo_client=client,
                ruta_excel=tmp_path,
                aprobado_por=resp["sender"],
                dry_run=args.dry_run,
                directorio_memoria=str(DIR_MEMORIA),
            )

            if resultado.ok:
                confirmadas = sum(1 for f in resultado.facturas if f.confirmada)
                print(f"    ✓ {resultado.total_lineas} línea(s) "
                      f"{'simuladas' if args.dry_run else 'aplicadas'} | "
                      f"{confirmadas} factura(s) confirmadas")
                if resultado.partner_rut:
                    print(f"    {resumen_memoria(resultado.partner_rut, DIR_MEMORIA)}")
            else:
                print(f"    ✗ Errores: {resultado.errores_globales}")
        print()


def cmd_aplicar(args):
    print(f"=== APLICANDO DISTRIBUCIÓN — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    if not Path(args.aplicar).exists():
        print(f"Error: no se encuentra el archivo '{args.aplicar}'")
        sys.exit(1)

    client = conectar_odoo()
    dry_run = args.dry_run
    if dry_run:
        print("⚠️  MODO DRY RUN — no se escribirá en Odoo\n")

    resultado = aplicar_distribucion(
        odoo_client=client,
        ruta_excel=args.aplicar,
        aprobado_por=args.aprobado_por or "victor@unionx.cl",
        dry_run=dry_run,
        directorio_memoria=str(DIR_MEMORIA),
    )

    print(f"\n{'=' * 60}")
    print(f"✓ Líneas procesadas: {resultado.total_lineas}")
    if resultado.errores_globales:
        print(f"⚠️  Errores: {resultado.errores_globales}")
    if dry_run:
        print("\n⚠️  DRY RUN completado.")
    else:
        print("\n✓ Cambios aplicados en Odoo.")

    if resultado.partner_rut:
        print()
        print(resumen_memoria(resultado.partner_rut, DIR_MEMORIA))


def main():
    parser = argparse.ArgumentParser(description="Distribución de servicios → cuentas contables")
    parser.add_argument("--folio", type=str, help="Procesar solo esta factura (folio)")
    parser.add_argument("--aplicar", type=str, metavar="EXCEL",
                        help="Ruta al Excel aprobado → aplica en Odoo")
    parser.add_argument("--leer-respuestas", action="store_true",
                        help="Lee respuestas de Gmail y aplica automáticamente")
    parser.add_argument("--apply-direct", action="store_true",
                        help="Aplica clasificación directo en Odoo sin aprobación")
    parser.add_argument("--excluir-rut", type=str, metavar="RUT",
                        help="RUT(s) a excluir separados por coma")
    parser.add_argument("--send-mail", action="store_true",
                        help="Envía el Excel a Camila/Victor por Gmail")
    parser.add_argument("--test", action="store_true",
                        help="Modo prueba: envía solo a andres@unionx.cl")
    parser.add_argument("--dry-run", action="store_true",
                        help="Modo simulación: no escribe en Odoo")
    parser.add_argument("--aprobado-por", type=str, default="victor@unionx.cl",
                        help="Email del analista que aprobó (para --aplicar manual)")
    args = parser.parse_args()

    if args.aplicar:
        cmd_aplicar(args)
    elif args.leer_respuestas:
        cmd_leer_respuestas(args)
    else:
        cmd_detectar_y_clasificar(args)


if __name__ == "__main__":
    main()
