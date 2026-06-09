"""
Opcion B — Auto-importacion SII → Odoo.
Usa Playwright para: login SII, navegar RCV, listar DTEs, descargar XMLs.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SII_LOGIN_URL = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html"
SII_RCV_URL   = "https://www4.sii.cl/consdcvinternetui/"
TIPOS_AUTO_IMPORTAR = {"33", "34", "61"}
TIPO_DOC_MOVE_TYPE = {"33": "in_invoice", "34": "in_invoice",
                      "43": "in_invoice", "61": "in_refund", "56": "in_refund"}


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
    xml_disponible: bool = True
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


def _login_rcv(page, rut: str, password: str):
    rut_limpio = rut.replace(".", "").replace("-", "").upper()
    page.goto(f"{SII_LOGIN_URL}?{SII_RCV_URL}", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    for sel in ["#rutcontribuyente", "#rut", "input[name='rut ']"]:
        try:
            page.fill(sel, rut_limpio, timeout=3_000); break
        except Exception:
            continue
    for sel in ["#clave", "input[name='clave ']", "input[type='password ']"]:
        try:
            page.fill(sel, password, timeout=3_000); break
        except Exception:
            continue
    page.keyboard.press("Enter")
    time.sleep(8)
    page.wait_for_load_state("networkidle", timeout=20_000)


def _extraer_tabla_dte(page) -> list:
    docs = []
    try:
        rows = page.query_selector_all("table tbody tr")
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 6:
                continue
            texts = [c.inner_text().strip() for c in cells]
            try:
                docs.append({
                    "rut_emisor":  texts[0].replace(".","").replace("-","").upper(),
                    "razon_social": texts[1] if len(texts) > 1 else "",
                    "tipo_doc":    texts[2].strip() if len(texts) > 2 else "",
                    "folio":       texts[3].strip() if len(texts) > 3 else "",
                    "fecha":       texts[4].strip() if len(texts) > 4 else "",
                    "monto_neto":  float(texts[5].replace(".","").replace(",",".")
                                         .replace("$","") or "0") if len(texts) > 5 else 0,
                    "monto_total": float(texts[6].replace(".","").replace(",",".")
                                         .replace("$","") or "0") if len(texts) > 6 else 0,
                })
            except Exception:
                continue
    except Exception:
        pass
    return docs


def _descargar_xml_dte(page, tipo_doc: str, folio: str, rut_e: str) -> Optional[bytes]:
    try:
        with page.expect_download(timeout=15_000) as dl_info:
            page.click(f"text={folio}", timeout=5_000)
        download = dl_info.value
        tmp = Path("/tmp") / f"dte_{rut_e}_{tipo_doc}_{folio}.xml"
        download.save_as(str(tmp))
        return tmp.read_bytes()
    except Exception:
        return None


def listar_y_descargar_rcv(year: int, month: int, rut: str, password: str,
                            folios_ya_en_odoo=None, headless: bool = False) -> ResultadoRCV:
    from playwright.sync_api import sync_playwright
    folios_ya_en_odoo = folios_ya_en_odoo or set()
    resultado = ResultadoRCV(periodo=f"{year:04d}-{month:02d}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        try:
            _login_rcv(page, rut, password)
            if SII_RCV_URL not in page.url and "consdcv" not in page.url:
                resultado.errores.append(f"Login fallo — URL: {page.url[:80]}")
                return resultado

            # Navegar a detalle del periodo
            page.goto(f"{SII_RCV_URL}#/index", timeout=20_000)
            time.sleep(3)
            try:
                page.click("text=Compras", timeout=5_000)
                time.sleep(1)
            except Exception:
                pass
            mes_str = f"{month:02d}/{year}"
            for sel in ["input[placeholder*='Período ']", "input[placeholder*='periodo ']",
                        "input[placeholder*='mes ']", "#periodo"]:
                try:
                    page.fill(sel, mes_str, timeout=3_000); break
                except Exception:
                    continue
            for btn in ["Consultar", "Buscar"]:
                try:
                    page.click(f"button:has-text('{btn} ')", timeout=3_000)
                    time.sleep(3)
                    break
                except Exception:
                    continue
            page.wait_for_load_state("networkidle", timeout=15_000)

            filas = _extraer_tabla_dte(page)
            resultado.total_sii = len(filas)

            for fila in filas:
                tipo = fila.get("tipo_doc", "")
                folio = fila.get("folio", "")
                rut_e = fila.get("rut_emisor", "")
                dte = DTERecibido(
                    rut_emisor=rut_e, razon_social=fila.get("razon_social", ""),
                    tipo_doc=tipo, folio=folio, fecha_emision=fila.get("fecha", ""),
                    monto_neto=fila.get("monto_neto", 0), monto_iva=0,
                    monto_total=fila.get("monto_total", 0))

                if folio in folios_ya_en_odoo:
                    resultado.ya_en_odoo += 1
                    dte.xml_disponible = False
                    resultado.dtes.append(dte); continue

                if tipo not in TIPOS_AUTO_IMPORTAR:
                    dte.xml_disponible = False
                    dte.error = f"Tipo {tipo} no auto-importable"
                    resultado.dtes.append(dte); continue

                xml = _descargar_xml_dte(page, tipo, folio, rut_e)
                if xml:
                    dte.xml_bytes = xml
                    resultado.importados += 1
                else:
                    dte.error = "No se pudo descargar XML"
                resultado.dtes.append(dte)
        except Exception as e:
            resultado.errores.append(str(e))
        finally:
            browser.close()
    return resultado
