"""
Descarga automática del libro de compras del SII via Playwright.
Credenciales: env vars SII_RUT y SII_PASSWORD.

Flujo de auth SII:
  1. Login en zeusr.sii.cl con destino=www4.sii.cl/consdcvinternetui/
  2. Tras auth, el portal redirige directamente al RCV autenticado
  3. Seleccionar periodo → Consultar
  4. Ir a Descargas Diferidas → Solicitar detalle → esperar → descargar

El CSV del botón "Descargar" en COMPRA solo trae el RESUMEN (totales por tipo).
El DETALLE con RUT/folio/monto individual se obtiene via Descargas Diferidas.
"""
from __future__ import annotations
import os
import time
from datetime import date
from pathlib import Path
from typing import Optional

SII_LOGIN_URL = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html"
SII_RCV_URL   = "https://www4.sii.cl/consdcvinternetui/"

MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

DOWNLOADS_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "contabilidad" / "sii"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
HISTORICO_DIR = DOWNLOADS_DIR / "historico"
HISTORICO_DIR.mkdir(parents=True, exist_ok=True)


def _login_rcv(page, rut: str, password: str, log_steps: list):
    """Hace login en el SII y aterriza en el RCV autenticado."""
    rut_limpio = rut.replace(".", "").replace("-", "").upper()
    login_url  = f"{SII_LOGIN_URL}?{SII_RCV_URL}"

    log_steps.append("Login con destino RCV...")
    page.goto(login_url)
    page.wait_for_load_state("networkidle")

    page.fill("input[name='rutcntr']", rut_limpio)
    page.fill("input[name='clave']", password)
    page.locator("input[name='clave']").press("Enter")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)

    # Esperar que CAutInicio.cgi complete la redirección JS al RCV
    # El networkidle captura la carga de CAutInicio, luego 8s para que el JS redirija
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(8000)

    log_steps.append(f"URL post-login: {page.url}")
    if "InicioAutenticacion" in page.url or "IngresoRutClave" in page.url:
        raise RuntimeError("Login SII fallido. Verificar RUT y clave tributaria.")
    if "zeusr.sii.cl" in page.url:
        raise RuntimeError(f"Auth incompleta — quedó en {page.url}")

    log_steps.append("Login OK — autenticado en RCV")


def _seleccionar_periodo_y_consultar(page, anio: int, mes: int, log_steps: list):
    """Selecciona el periodo y hace click en Consultar."""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    try:
        selects = page.locator("select").all()
        if len(selects) >= 2:
            selects[1].select_option(MESES_ES[mes])
            log_steps.append(f"Mes: {MESES_ES[mes]}")
        if len(selects) >= 3:
            selects[2].select_option(str(anio))
            log_steps.append(f"Año: {anio}")
    except Exception as e:
        log_steps.append(f"Advertencia periodo: {e}")

    page.click("button:has-text('Consultar'), input[value='Consultar']")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(5000)
    log_steps.append("Consultar clickeado")


def descargar_libro_compras(
    anio: int, mes: int,
    rut: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = False,
    timeout_ms: int = 90_000,
) -> dict:
    """
    Descarga el resumen del libro de compras (CSV por tipo de documento).
    Para el DETALLE con RUT/folio, usar descargar_detalle_compras().
    """
    rut = rut or os.environ.get("SII_RUT", "")
    password = password or os.environ.get("SII_PASSWORD", "")

    if not rut or not password:
        return {"ok": False, "archivo": None,
                "error": "Faltan SII_RUT y SII_PASSWORD", "detalles": ""}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "archivo": None,
                "error": "pip install playwright && playwright install chromium",
                "detalles": ""}

    log_steps = []
    archivo_dest    = DOWNLOADS_DIR / f"libro_compras_{anio:04d}-{mes:02d}.xlsx"
    snapshot_diario = HISTORICO_DIR / f"libro_{anio:04d}-{mes:02d}_snapshot_{date.today().isoformat()}.xlsx"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(accept_downloads=True)
            page    = context.new_page()
            page.set_default_timeout(timeout_ms)

            _login_rcv(page, rut, password, log_steps)
            _seleccionar_periodo_y_consultar(page, anio, mes, log_steps)

            # Scroll y descargar resumen
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)

            with page.expect_download(timeout=30000) as dl_info:
                page.click("button:has-text('Descargar'), a:has-text('Descargar')")
            download = dl_info.value

            import shutil
            shutil.copy(download.path(), archivo_dest)
            shutil.copy(download.path(), snapshot_diario)
            log_steps.append(f"Resumen guardado: {archivo_dest}")
            browser.close()

        return {"ok": True, "archivo": archivo_dest, "error": None,
                "detalles": "\n".join(log_steps)}

    except Exception as e:
        return {"ok": False, "archivo": None,
                "error": f"Error: {e}", "detalles": "\n".join(log_steps)}


def descargar_detalle_compras(
    anio: int, mes: int,
    rut: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = False,
    timeout_ms: int = 120_000,
    esperar_generacion_seg: int = 300,
) -> dict:
    """
    Descarga el DETALLE del libro de compras via Descargas Diferidas.

    El proceso es asíncrono: el SII genera el archivo (minutos) y luego lo descarga.
    - Si hay un archivo ya generado y listo: lo descarga inmediatamente.
    - Si no: solicita la generación y espera hasta esperar_generacion_seg segundos.

    Returns:
        dict con 'ok', 'archivo', 'error', 'estado' ('descargado'|'solicitado'|'error')
    """
    rut = rut or os.environ.get("SII_RUT", "")
    password = password or os.environ.get("SII_PASSWORD", "")

    if not rut or not password:
        return {"ok": False, "archivo": None, "estado": "error",
                "error": "Faltan SII_RUT y SII_PASSWORD", "detalles": ""}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "archivo": None, "estado": "error",
                "error": "pip install playwright && playwright install chromium",
                "detalles": ""}

    log_steps = []
    archivo_dest = DOWNLOADS_DIR / f"detalle_compras_{anio:04d}-{mes:02d}.xlsx"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(accept_downloads=True)
            page    = context.new_page()
            page.set_default_timeout(timeout_ms)

            _login_rcv(page, rut, password, log_steps)
            _seleccionar_periodo_y_consultar(page, anio, mes, log_steps)

            # Ir a pestaña Descargas Diferidas
            page.click("a:has-text('Descargas Diferidas')")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)
            log_steps.append("En Descargas Diferidas")

            screenshot = DOWNLOADS_DIR / f"sii_diferidas_{date.today().isoformat()}.png"
            page.screenshot(path=str(screenshot))

            # ── Intentar descargar si ya hay archivo listo ────────────────────
            descargado = _intentar_descargar_diferida(page, "Compra", log_steps)
            if descargado:
                import shutil
                shutil.copy(descargado.path(), archivo_dest)
                log_steps.append(f"Detalle guardado: {archivo_dest}")
                browser.close()
                return {"ok": True, "archivo": archivo_dest, "estado": "descargado",
                        "error": None, "detalles": "\n".join(log_steps)}

            # ── Solicitar generación nueva ────────────────────────────────────
            log_steps.append("Solicitando generación del detalle de Compras...")
            _solicitar_diferida(page, "Compra", log_steps)

            # ── Esperar y reintentar ──────────────────────────────────────────
            inicio = time.time()
            while time.time() - inicio < esperar_generacion_seg:
                page.wait_for_timeout(30000)  # esperar 30 seg
                page.reload()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(3000)

                descargado = _intentar_descargar_diferida(page, "Compra", log_steps)
                if descargado:
                    import shutil
                    shutil.copy(descargado.path(), archivo_dest)
                    log_steps.append(f"Detalle guardado tras espera: {archivo_dest}")
                    browser.close()
                    return {"ok": True, "archivo": archivo_dest, "estado": "descargado",
                            "error": None, "detalles": "\n".join(log_steps)}

                elapsed = int(time.time() - inicio)
                log_steps.append(f"Esperando... {elapsed}s/{esperar_generacion_seg}s")

            # No estuvo listo en el tiempo máximo — fue solicitado, se descargará mañana
            browser.close()
            return {"ok": True, "archivo": None, "estado": "solicitado",
                    "error": None,
                    "detalles": "\n".join(log_steps + [
                        "Archivo solicitado. Próxima corrida lo descargará cuando esté listo."])}

    except Exception as e:
        return {"ok": False, "archivo": None, "estado": "error",
                "error": f"Error: {e}", "detalles": "\n".join(log_steps)}


def _intentar_descargar_diferida(page, tipo: str, log_steps: list):
    """
    Busca un archivo listo para descargar en Descargas Diferidas.
    Retorna el objeto download si lo encontró, None si no.
    """
    # Buscar botón de descarga dentro de la sección del tipo (Compra/Venta)
    # La UI del SII muestra: Compra → [tabla con filas] → botón Descargar por fila
    selectores = [
        f"section:has-text('{tipo}') button:has-text('Descargar')",
        f"div:has-text('{tipo}') a:has-text('Descargar')",
        f"table button:has-text('Descargar')",
        f"button:has-text('Descargar')",
    ]
    for sel in selectores:
        try:
            count = page.locator(sel).count()
            if count > 0:
                log_steps.append(f"Archivo listo para descargar ({sel})")
                with page.expect_download(timeout=30000) as dl_info:
                    page.locator(sel).first.click()
                return dl_info.value
        except Exception:
            continue
    return None


def _solicitar_diferida(page, tipo: str, log_steps: list):
    """Hace click en 'Solicitar' para el tipo dado (Compra/Venta)."""
    selectores = [
        f"section:has-text('{tipo}') button:has-text('Solicitar')",
        f"div:has-text('{tipo}') button:has-text('Solicitar')",
        f"button:has-text('Solicitar')",
        f"a:has-text('Solicitar')",
    ]
    for sel in selectores:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)
                log_steps.append(f"Solicitar clickeado ({sel})")
                return
        except Exception:
            continue
    log_steps.append("No se encontró botón Solicitar")


def descargar_mes_actual_y_anterior(
    rut: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = False,
) -> list[dict]:
    """Descarga resumen del mes actual y anterior."""
    hoy = date.today()
    mes_anterior = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
    return [
        descargar_libro_compras(*mes_anterior, rut=rut, password=password, headless=headless),
        descargar_libro_compras(hoy.year, hoy.month, rut=rut, password=password, headless=headless),
    ]
