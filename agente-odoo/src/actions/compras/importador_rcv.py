"""
Opcion B — Obtiene el detalle del RCV SII via la API interna del portal.

Descubierto 11-jun-2026 (sii_discovery_xhr.py): al hacer click en un tipo de
documento de la tabla resumen, la app Angular llama a
  POST /consdcvinternetui/services/data/facadeService/getDetalleCompra
y recibe JSON con el detalle documento por documento (RUT, folio, fecha,
neto, IVA, total). No se necesita Descargas Diferidas (que nunca funciono).

Estrategia: UI-driven — click en cada tipo doc, capturar el XHR response.
No se forja el request (evita lidiar con conversationId/token).
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

SII_LOGIN_URL = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html"
SII_RCV_URL   = "https://www4.sii.cl/consdcvinternetui/"
DTE_INTERNET_URL = "https://www4.sii.cl/consdteinternetui/#/verificar-dte"

MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

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


def _login_sii(page, rut: str, password: str):
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


def _fecha_iso(fecha_cl: str) -> str:
    """'31/05/2026' → '2026-05-31'."""
    try:
        return datetime.strptime(fecha_cl.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return str(fecha_cl or "")[:10]


def _obtener_detalle_rcv(page, year: int, month: int) -> tuple[list[dict], list[str]]:
    """
    En el RCV (ya logueado): selecciona periodo, Consultar, click en cada
    tipo de documento y captura los JSON de getDetalleCompra.

    Returns: (docs, errores) donde docs = [{tipo_doc, rut_emisor, ...}]
    """
    capturas: list[tuple[str, dict]] = []   # (codTipoDoc, json_response)
    errores: list[str] = []

    def on_response(resp):
        if "getDetalleCompra" not in resp.url or resp.status != 200:
            return
        try:
            body = resp.json()
            req_data = json.loads(resp.request.post_data or "{}")
            cod = str(req_data.get("data", {}).get("codTipoDoc", ""))
            capturas.append((cod, body))
        except Exception as e:
            errores.append(f"parse XHR: {e}")

    page.on("response", on_response)

    try:
        # Seleccionar periodo
        page.wait_for_timeout(2_000)
        selects = page.locator("select").all()
        if len(selects) >= 2:
            selects[1].select_option(MESES_ES[month])
        if len(selects) >= 3:
            selects[2].select_option(str(year))
        page.click("button:has-text('Consultar'), input[value='Consultar']")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4_000)

        n_links = page.locator("table a").count()
        if n_links == 0:
            errores.append("Tabla resumen sin links de tipo doc (¿periodo sin docs?)")
            return [], errores

        for i in range(n_links):
            nombre = "?"
            try:
                links = page.locator("table a").all()   # re-localizar tras Volver
                if i >= len(links):
                    break
                nombre = links[i].inner_text().strip()
                links[i].click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(3_500)
                volver = page.locator("button:has-text('Volver'), a:has-text('Volver')")
                if volver.count():
                    volver.first.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2_500)
            except Exception as e:
                errores.append(f"click tipo {i} ({nombre}): {str(e)[:120]}")
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    # ── Parsear capturas ─────────────────────────────────────────────────
    docs = []
    vistos = set()
    for cod_tipo, body in capturas:
        data = body.get("data")
        if not isinstance(data, list):
            continue
        for d in data:
            folio = str(d.get("detNroDoc", "")).strip()
            rut = f"{d.get('detRutDoc','')}-{d.get('detDvDoc','')}"
            key = (cod_tipo, rut, folio)
            if key in vistos:
                continue
            vistos.add(key)
            neto = float(d.get("detMntNeto") or 0)
            exento = float(d.get("detMntExe") or 0)
            docs.append({
                "tipo_doc":     cod_tipo,
                "rut_emisor":   rut.replace(".", "").upper(),
                "razon_social": str(d.get("detRznSoc") or "").strip(),
                "folio":        folio,
                "fecha":        _fecha_iso(str(d.get("detFchDoc") or "")),
                "monto_neto":   neto if neto else exento,
                "monto_iva":    float(d.get("detMntIVA") or 0),
                "monto_total":  float(d.get("detMntTotal") or 0),
            })
    return docs, errores


# ──────────────────────────────────────────────────────────────────────────────
# Descarga XML por folio desde consdteinternetui (best-effort)
# ──────────────────────────────────────────────────────────────────────────────

def _descargar_xml_consdteinternetui(page, rut_emisor: str, tipo_doc: str,
                                      folio: str, debug_dir: Optional[Path] = None) -> Optional[bytes]:
    xml_capturado = []

    def _on_response(response):
        if response.status != 200:
            return
        if not any(kw in response.url for kw in
                   ("getDte", "descargarXml", "/dte/", "consdteinternetui/services")):
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
        rut_body, dv = (rut_clean[:-1], rut_clean[-1]) if len(rut_clean) >= 2 else (rut_clean, "")

        page.goto(DTE_INTERNET_URL, timeout=25_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2_000)

        for sel, val in [("input[name='rutEmisor'], #rutEmisor, input[id*='rut']", rut_body),
                          ("input[name='dvEmisor'], #dvEmisor, input[maxlength='1']", dv),
                          ("input[name='folio'], #folio, input[placeholder*='olio']", folio)]:
            try:
                loc = page.locator(sel)
                if loc.count():
                    loc.first.fill(val, timeout=3_000)
            except Exception:
                continue
        try:
            sel_tipo = page.locator("select")
            if sel_tipo.count():
                sel_tipo.first.select_option(value=tipo_doc, timeout=3_000)
        except Exception:
            pass
        for sel in ["button:has-text('Consultar')", "button[type='submit']",
                    "input[value='Consultar']"]:
            try:
                if page.locator(sel).count():
                    page.locator(sel).first.click(timeout=4_000)
                    break
            except Exception:
                continue
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3_000)

        if debug_dir:
            page.screenshot(path=str(debug_dir / f"dte_{folio}.png"))

        if xml_capturado:
            return xml_capturado[0]

        for sel in ["a:has-text('XML')", "button:has-text('XML')", "*[title*='XML']"]:
            try:
                if page.locator(sel).count():
                    with page.expect_download(timeout=12_000) as dl_info:
                        page.locator(sel).first.click()
                    dl = dl_info.value
                    tmp = Path("/tmp") / f"dte_{rut_body}_{tipo_doc}_{folio}.xml"
                    dl.save_as(str(tmp))
                    return tmp.read_bytes()
            except Exception:
                continue
        return None
    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Punto de entrada principal
# ──────────────────────────────────────────────────────────────────────────────

def _clave_dedup(rut_emisor: str, folio: str) -> tuple[str, str]:
    """Clave (rut_sin_dv, folio_sin_ceros) — igual que _folios_en_odoo."""
    rut = str(rut_emisor or "").replace(".", "").replace("-", "").strip().upper()
    rut = rut[:-1] if len(rut) > 1 else rut
    digits = "".join(ch for ch in str(folio or "") if ch.isdigit())
    return (rut, str(int(digits)) if digits else "")


def listar_y_descargar_rcv(year: int, month: int, rut: str, password: str,
                            folios_ya_en_odoo=None, headless: bool = False,
                            intentar_xml: bool = True) -> ResultadoRCV:
    """
    1. Login SII + detalle RCV via API interna (getDetalleCompra) — inmediato
    2. Filtra docs ya en Odoo (folios_ya_en_odoo: set de (rut_sin_dv, folio))
    3. Para los nuevos, intenta bajar el XML (glosas) — best effort
    """
    from playwright.sync_api import sync_playwright

    folios_ya_en_odoo = folios_ya_en_odoo or set()
    resultado = ResultadoRCV(periodo=f"{year:04d}-{month:02d}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(45_000)

        try:
            _login_sii(page, rut, password)
        except Exception as e:
            resultado.errores.append(f"Login SII: {e}")
            browser.close()
            return resultado

        docs, errs = _obtener_detalle_rcv(page, year, month)
        resultado.errores.extend(errs)
        resultado.total_sii = len(docs)

        # Snapshot del detalle (auditoria + lo usa la comparacion SII vs Odoo)
        try:
            out_dir = Path(__file__).resolve().parents[4] / "data" / "contabilidad" / "sii"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"detalle_rcv_{year:04d}-{month:02d}.json").write_text(
                json.dumps(docs, indent=1, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        nuevos = []
        for d in docs:
            folio = d["folio"]
            tipo  = d["tipo_doc"]
            dte = DTERecibido(
                rut_emisor=d["rut_emisor"], razon_social=d["razon_social"],
                tipo_doc=tipo, folio=folio, fecha_emision=d["fecha"],
                monto_neto=d["monto_neto"], monto_iva=d["monto_iva"],
                monto_total=d["monto_total"],
            )
            if _clave_dedup(d["rut_emisor"], folio) in folios_ya_en_odoo:
                resultado.ya_en_odoo += 1
                continue
            if tipo not in TIPOS_AUTO_IMPORTAR:
                dte.error = f"Tipo {tipo} ({NOMBRE_TIPO_DOC.get(tipo, '?')}) no auto-importable"
                resultado.dtes.append(dte)
                continue
            nuevos.append(dte)

        # ── XML por folio (glosas) — best effort ────────────────────────────
        if nuevos and intentar_xml:
            debug_dir = Path(__file__).resolve().parents[4] / "data" / "contabilidad" / "sii" / "debug_xml"
            debug_dir.mkdir(parents=True, exist_ok=True)
            print(f"  → {len(nuevos)} docs nuevos — intentando XMLs...")
            for dte in nuevos:
                try:
                    xml = _descargar_xml_consdteinternetui(
                        page, dte.rut_emisor, dte.tipo_doc, dte.folio, debug_dir=debug_dir)
                    if xml:
                        dte.xml_bytes = xml
                        dte.xml_disponible = True
                        print(f"    ✓ XML {dte.tipo_doc}/{dte.folio} — {dte.razon_social[:40]}")
                    else:
                        print(f"    ⚠ sin XML {dte.tipo_doc}/{dte.folio} — se importa con totales")
                except Exception as e:
                    print(f"    ✗ XML {dte.tipo_doc}/{dte.folio}: {str(e)[:100]}")
                time.sleep(1)

        resultado.dtes.extend(nuevos)
        browser.close()

    return resultado
