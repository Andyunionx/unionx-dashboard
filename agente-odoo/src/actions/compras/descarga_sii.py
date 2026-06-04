"""
Descarga automática del libro de compras del SII via Playwright.
Credenciales: env vars SII_RUT y SII_PASSWORD.
"""
from __future__ import annotations
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

SII_LOGIN_URL = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html"
SII_RCV_URL   = "https://www4.sii.cl/consdcvinternetui/"

DOWNLOADS_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "contabilidad" / "sii"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
HISTORICO_DIR = DOWNLOADS_DIR / "historico"
HISTORICO_DIR.mkdir(parents=True, exist_ok=True)


def descargar_libro_compras(
    anio: int, mes: int,
    rut: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = True,
    timeout_ms: int = 60_000,
) -> dict:
    rut = rut or os.environ.get("SII_RUT", "")
    password = password or os.environ.get("SII_PASSWORD", "")

    if not rut or not password:
        return {"ok": False, "archivo": None,
                "error": "Faltan SII_RUT y SII_PASSWORD en env vars", "detalles": ""}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "archivo": None,
                "error": "Playwright no instalado: pip install playwright && playwright install chromium",
                "detalles": ""}

    log_steps = []
    nombre_archivo = f"libro_compras_{anio:04d}-{mes:02d}.xlsx"
    archivo_dest   = DOWNLOADS_DIR / nombre_archivo
    snapshot_diario = HISTORICO_DIR / f"libro_{anio:04d}-{mes:02d}_snapshot_{date.today().isoformat()}.xlsx"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(accept_downloads=True)
            page    = context.new_page()
            page.set_default_timeout(timeout_ms)

            log_steps.append("Navegando a login SII...")
            page.goto(SII_LOGIN_URL)
            page.wait_for_load_state("networkidle")

            page.fill("input[name='rutcntr']", rut)
            page.fill("input[name='clave']", password)
            log_steps.append("Credenciales ingresadas")
            page.click("button#bt_ingresar, input[type='submit']")
            page.wait_for_load_state("networkidle")

            if "InicioAutenticacion" in page.url or "Error" in page.content()[:5000]:
                browser.close()
                return {"ok": False, "archivo": None,
                        "error": "Login SII fallido. Verificar credenciales.",
                        "detalles": "\n".join(log_steps)}

            log_steps.append("Login OK")

            log_steps.append(f"Navegando al RCV {anio}-{mes:02d}...")
            page.goto(SII_RCV_URL)
            page.wait_for_load_state("networkidle")

            try:
                page.select_option("select#periodoAnno, select[name*='ano']", str(anio))
                page.select_option("select#periodoMes, select[name*='mes']", f"{mes:02d}")
            except Exception:
                log_steps.append("Selectores de periodo no encontrados")

            try:
                page.click("a:has-text('COMPRA'), button:has-text('Compra')")
            except Exception:
                pass

            page.wait_for_load_state("networkidle")

            with page.expect_download(timeout=timeout_ms) as download_info:
                page.click("a:has-text('Descargar'), button:has-text('Excel'), button:has-text('XLS')")
            download = download_info.value
            tmp_path = download.path()
            log_steps.append(f"Descarga completada")

            import shutil
            shutil.copy(tmp_path, archivo_dest)
            shutil.copy(tmp_path, snapshot_diario)
            log_steps.append(f"Guardado en {archivo_dest}")
            browser.close()

        return {"ok": True, "archivo": archivo_dest, "error": None,
                "detalles": "\n".join(log_steps)}

    except Exception as e:
        return {"ok": False, "archivo": None,
                "error": f"Error en descarga: {e}",
                "detalles": "\n".join(log_steps)}


def descargar_mes_actual_y_anterior(
    rut: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = True,
) -> list[dict]:
    hoy = date.today()
    mes_actual = (hoy.year, hoy.month)
    mes_anterior = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
    return [
        descargar_libro_compras(*mes_anterior, rut=rut, password=password, headless=headless),
        descargar_libro_compras(*mes_actual, rut=rut, password=password, headless=headless),
    ]
