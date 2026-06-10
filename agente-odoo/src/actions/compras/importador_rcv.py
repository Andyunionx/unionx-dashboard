"""
Opcion B — Obtiene DTEs del SII con XMLs individuales.

Flujo:
  1. descargar_detalle_compras() → Excel Descargas Diferidas (todos los docs del mes)
  2. Parsear Excel → identificar docs no en Odoo
  3. Para cada doc nuevo → descargar XML desde consdteinternetui
     (el XML tiene las lineas con glosas que el clasificador necesita para predistribuir)
  4. Retornar DTERecibido con xml_bytes lleno → importador_odoo crea draft con lineas reales
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DTE_INTERNET_URL = "https://www4.sii.cl/consdteinternetui/#/verificar-dte"

TIPOS_AUTO_IMPORTAR = {"33", "34", "61"}

NOMBRE_TIPO_DOC = {
    "33": "Factura electrónica",
    "34": "Factura no afecta",
    "43": "Liquidación-Factura",
    "56": "Nota de débito",
    "61": "Nota de crédito",
}


@dataclass
class DTERecibido:
    rut_emisor: str
    razon_social: str
    tipo_doc: str
    folio: str
    fecha_emision: str
    monto_neto: float
    monto_iva: float
    monto_total: float
    xml_disponible: bool = False
    xml_bytes: Optional[bytes] = None
    error: Optional[str] = None


@dataclass
class ResultadoRCV:
    periodo: str
    total_sii: int = 0
    ya_en_odoo: int = 0
    importados: int = 0
    errores: list = field(default_factory=list)
    dtes: list = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Login SII (reutiliza logica de descarga_sii.py)
# ──────────────────────────────────────────────────────────────────────────────

def _login_sii(page, rut: str, password: str):
    """Login en SII. Aterriza en consdcvinternetui; la sesion sirve para todos los portales www4."""
    from src.actions.compras.descarga_sii import SII_LOGIN_URL, SII_RCV_URL
    rut_limpio = rut.replace(".", "").replace("-", "").upper()
    page.goto(f"{SII_LOGIN_URL}?{SII_RCV_URL}", timeout=30_000)
    page.wait_for_load_state("networkidle")
    page.fill("input[name='rutcntr']", rut_limpio)
    page.fill("input[name='clave']", password)
    page.locator("input[name='clave']").press("Enter")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(8_000)
    if "IngresoRutClave" in page.url or "zeusr.sii.cl" in page.url:
        raise RuntimeError(f"Login SII fallido. URL: {page.url}")


# ──────────────────────────────────────────────────────────────────────────────
# Descarga XML por folio desde consdteinternetui
# ──────────────────────────────────────────────────────────────────────────────

def _descargar_xml_consdteinternetui(
    page, rut_emisor: str, tipo_doc: str, folio: str,
    debug_dir: Optional[Path] = None,
) -> Optional[bytes]:
    """
    Descarga el XML DTE de un folio especifico desde consdteinternetui.

    Estrategia 1 (principal): interceptar respuesta HTTP del API Angular interno.
    Estrategia 2 (fallback): click en boton "Descargar XML" si hay download.
    Estrategia 3: leer contenido HTML si la pagina devuelve XML inline.
    """
    xml_capturado = []

    def _on_response(response):
        if response.status != 200:
            return
        url = response.url
        if not any(kw in url for kw in
                   ("facDteDteInternet", "getDte", "descargarXml",
                    "/dte/", "consdteinternetui/services")):
            return
        try:
            body = response.body()
            if body and any(sig in body for sig in
                            (b"<DTE", b"<?xml", b"<Documento", b"<SetDTE")):
                xml_capturado.append(body)
        except Exception:
            pass

    page.on("response", _on_response)

    try:
        rut_clean = rut_emisor.replace(".", "").replace("-", "").strip().upper()
        rut_body  = rut_clean[:-1] if len(rut_clean) >= 2 else rut_clean
        dv        = rut_clean[-1]  if len(rut_clean) >= 2 else ""

        page.goto(DTE_INTERNET_URL, timeout=25_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2_000)

        if debug_dir:
            page.screenshot(path=str(debug_dir / f"dte_{folio}_1_inicial.png"))

        # ── RUT emisor ──────────────────────────────────────────────────────
        for sel in ["input[name='rutEmisor']", "#rutEmisor",
                    "input[placeholder*='RUT Emisor']", "input[ng-model*='rutEmisor']",
                    "input[id*='rut']"]:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.fill(rut_body, timeout=3_000)
                    break
            except Exception:
                continue

        # ── DV emisor ───────────────────────────────────────────────────────
        for sel in ["input[name='dvEmisor']", "#dvEmisor", "input[name='dv']",
                    "input[placeholder*='DV']", "input[maxlength='1']"]:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.fill(dv, timeout=2_000)
                    break
            except Exception:
                continue

        # ── Tipo DTE ────────────────────────────────────────────────────────
        for sel in ["select[name='tipoDte']", "#tipoDte",
                    "select[name='tipo']", "select[ng-model*='tipo']", "select"]:
            try:
                el = page.locator(sel)
                if el.count() > 0:
                    try:
                        el.first.select_option(value=tipo_doc, timeout=2_000)
                    except Exception:
                        el.first.select_option(index=int(tipo_doc) if tipo_doc.isdigit() else 0,
                                               timeout=2_000)
                    break
            except Exception:
                continue

        # ── Folio ───────────────────────────────────────────────────────────
        for sel in ["input[name='folio']", "#folio", "input[name='nroFolio']",
                    "input[placeholder*='olio']", "input[ng-model*='folio']"]:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.fill(folio, timeout=2_000)
                    break
            except Exception:
                continue

        # ── Consultar ───────────────────────────────────────────────────────
        for sel in ["button:has-text('Consultar')", "button:has-text('Buscar')",
                    "button[type='submit']", "input[value='Consultar']",
                    "input[type='submit']"]:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click(timeout=4_000)
                    break
            except Exception:
                continue

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3_000)

        if debug_dir:
            page.screenshot(path=str(debug_dir / f"dte_{folio}_2_resultado.png"))

        # ── Estrategia 1: XML capturado de la red ───────────────────────────
        if xml_capturado:
            return xml_capturado[0]

        # ── Estrategia 2: boton descarga ────────────────────────────────────
        for sel in ["a:has-text('XML')", "button:has-text('XML')",
                    "a:has-text('Descargar XML')", "button:has-text('Descargar XML')",
                    "a:has-text('Ver XML')", "*[title*='XML']"]:
            try:
                if page.locator(sel).count() > 0:
                    with page.expect_download(timeout=12_000) as dl_info:
                        page.locator(sel).first.click()
                    dl = dl_info.value
                    tmp = Path("/tmp") / f"dte_{rut_body}_{tipo_doc}_{folio}.xml"
                    dl.save_as(str(tmp))
                    return tmp.read_bytes()
            except Exception:
                continue

        # ── Estrategia 3: contenido inline ──────────────────────────────────
        try:
            content = page.content()
            if any(tag in content for tag in ("<DTE", "<Documento", "<SetDTE")):
                start = min(
                    (content.find(tag) for tag in ("<DTE", "<Documento", "<SetDTE")
                     if content.find(tag) >= 0),
                    default=-1,
                )
                if start >= 0:
                    return content[start:].encode("utf-8")
        except Exception:
            pass

        return None

    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Parser Excel Descargas Diferidas
# ──────────────────────────────────────────────────────────────────────────────

def _parsear_excel_detalle(archivo: Path) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        return []

    wb = openpyxl.load_workbook(str(archivo), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        wb.close()
        return []

    header_idx = 0
    for i, row in enumerate(rows):
        if any(isinstance(c, str) and len(str(c)) > 2 for c in row if c is not None):
            header_idx = i
            break

    headers = [str(c).strip().lower() if c else "" for c in rows[header_idx]]

    def _idx(*names):
        for n in names:
            for i, h in enumerate(headers):
                if n in h:
                    return i
        return None

    i_rut   = _idx("rut prov", "rut emi", "rut")
    i_razon = _idx("razón", "razon", "nombre")
    i_tipo  = _idx("tipo doc", "codigo doc", "tipo")
    i_folio = _idx("folio")
    i_fecha = _idx("fecha doc", "fecha emi", "fecha")
    i_neto  = _idx("monto neto", "neto")
    i_iva   = _idx("iva", "impuesto")
    i_total = _idx("monto total", "total")

    docs = []
    for row in rows[header_idx + 1:]:
        if not any(row):
            continue

        def val(idx):
            return row[idx] if idx is not None and idx < len(row) else None

        rut = str(val(i_rut) or "").strip()
        if not rut or rut.lower() in ("rut", "none", ""):
            continue

        def to_float(v):
            try:
                return float(str(v or "0").replace(".", "").replace(",", ".")
                             .replace("$", "").strip() or "0")
            except (ValueError, AttributeError):
                return 0.0

        fecha = val(i_fecha)
        if hasattr(fecha, "strftime"):
            fecha = fecha.strftime("%Y-%m-%d")
        else:
            fecha = str(fecha or "").strip()[:10]

        tipo_raw = str(val(i_tipo) or "").strip()
        tipo = tipo_raw if tipo_raw.isdigit() else ""
        folio = str(val(i_folio) or "").strip().split(".")[0]

        docs.append({
            "rut_emisor":   rut.replace(".", "").replace("-", "").upper(),
            "razon_social": str(val(i_razon) or "").strip(),
            "tipo_doc":     tipo,
            "folio":        folio,
            "fecha":        fecha,
            "monto_neto":   to_float(val(i_neto)),
            "monto_iva":    to_float(val(i_iva)),
            "monto_total":  to_float(val(i_total)),
        })

    wb.close()
    return docs


# ──────────────────────────────────────────────────────────────────────────────
# Punto de entrada principal
# ──────────────────────────────────────────────────────────────────────────────

def listar_y_descargar_rcv(
    year: int, month: int,
    rut: str, password: str,
    folios_ya_en_odoo=None,
    headless: bool = False,
) -> ResultadoRCV:
    """
    1. Descarga Excel de Descargas Diferidas del SII (totales por doc)
    2. Identifica docs no en Odoo
    3. Abre browser → login → descarga XML por folio para cada doc nuevo
    4. Retorna ResultadoRCV con dtes llenos (xml_bytes disponible para clasificador)
    """
    from src.actions.compras.descarga_sii import descargar_detalle_compras, DOWNLOADS_DIR
    from playwright.sync_api import sync_playwright

    folios_ya_en_odoo = folios_ya_en_odoo or set()
    resultado = ResultadoRCV(periodo=f"{year:04d}-{month:02d}")

    # ── Paso 1: obtener Excel con lista de docs ─────────────────────────────
    res = descargar_detalle_compras(
        year, month, rut=rut, password=password,
        headless=headless, esperar_generacion_seg=300,
    )

    if res.get("estado") == "solicitado":
        resultado.errores.append("Detalle SII solicitado — listo en próxima corrida")
        return resultado

    if res.get("estado") == "error" or not res.get("archivo"):
        # Intentar archivo ya existente en disco
        archivo_disco = DOWNLOADS_DIR / f"detalle_compras_{year:04d}-{month:02d}.xlsx"
        if not archivo_disco.exists():
            resultado.errores.append(res.get("error", "No hay detalle SII disponible"))
            return resultado
        archivo = archivo_disco
    else:
        archivo = res["archivo"]

    # ── Paso 2: parsear Excel, separar nuevos vs ya en Odoo ────────────────
    filas = _parsear_excel_detalle(Path(archivo))
    resultado.total_sii = len(filas)

    nuevos = []
    for fila in filas:
        folio = fila.get("folio", "")
        tipo  = fila.get("tipo_doc", "")
        dte = DTERecibido(
            rut_emisor=fila["rut_emisor"],
            razon_social=fila.get("razon_social", ""),
            tipo_doc=tipo,
            folio=folio,
            fecha_emision=fila.get("fecha", ""),
            monto_neto=fila.get("monto_neto", 0),
            monto_iva=fila.get("monto_iva", 0),
            monto_total=fila.get("monto_total", 0),
        )
        if folio in folios_ya_en_odoo:
            resultado.ya_en_odoo += 1
            continue
        if tipo and tipo not in TIPOS_AUTO_IMPORTAR:
            dte.error = f"Tipo {tipo} ({NOMBRE_TIPO_DOC.get(tipo, '?')}) no auto-importable"
            resultado.dtes.append(dte)
            continue
        nuevos.append(dte)

    if not nuevos:
        return resultado

    # ── Paso 3: descargar XML por folio (browser reutilizado) ───────────────
    debug_dir = DOWNLOADS_DIR / "debug_xml"
    debug_dir.mkdir(parents=True, exist_ok=True)

    print(f"  → {len(nuevos)} docs nuevos — descargando XMLs desde consdteinternetui...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx     = browser.new_context(accept_downloads=True)
        page    = ctx.new_page()
        page.set_default_timeout(30_000)

        try:
            _login_sii(page, rut, password)
        except Exception as e:
            resultado.errores.append(f"Login SII (XML): {e}")
            browser.close()
            resultado.dtes.extend(nuevos)
            return resultado

        for dte in nuevos:
            try:
                xml = _descargar_xml_consdteinternetui(
                    page, dte.rut_emisor, dte.tipo_doc, dte.folio,
                    debug_dir=debug_dir,
                )
                if xml:
                    dte.xml_bytes    = xml
                    dte.xml_disponible = True
                    print(f"    ✓ XML {dte.tipo_doc}/{dte.folio} — {dte.razon_social[:40]}")
                else:
                    dte.error = "XML no disponible en consdteinternetui"
                    print(f"    ⚠ sin XML {dte.tipo_doc}/{dte.folio} — se importa con totales")
            except Exception as e:
                dte.error = f"Error XML: {e}"
                print(f"    ✗ {dte.tipo_doc}/{dte.folio}: {e}")

            resultado.dtes.append(dte)
            time.sleep(1)   # pausa entre folios

        browser.close()

    return resultado
