"""
Discovery: captura las llamadas XHR del RCV SII para mapear la API interna.
Corre local con browser visible. Guarda todo en data/contabilidad/sii/_discovery/.

Uso:
  SII_RUT=xxxxxxxx-x SII_PASSWORD=... python sii_discovery_xhr.py
"""
import json
import os
import time
from pathlib import Path

SII_LOGIN_URL = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html"
SII_RCV_URL   = "https://www4.sii.cl/consdcvinternetui/"

RUT = os.environ.get("SII_RUT", "")
PWD = os.environ.get("SII_PASSWORD", "")
PERIODO_MES = "Junio"
PERIODO_ANO = "2026"

if not RUT or not PWD:
    raise SystemExit("Faltan env vars SII_RUT / SII_PASSWORD")

OUT = Path(__file__).resolve().parents[2] / "data" / "contabilidad" / "sii" / "_discovery"
OUT.mkdir(parents=True, exist_ok=True)

capturas = []


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(60_000)

        # ── Capturar todas las respuestas de servicios ──────────────────────
        def on_response(resp):
            url = resp.url
            if "consdcvinternetui/services" not in url:
                return
            try:
                body = resp.text()
            except Exception:
                body = "<binario>"
            req = resp.request
            post_data = req.post_data or ""
            capturas.append({
                "n": len(capturas),
                "method": req.method,
                "url": url,
                "status": resp.status,
                "request_body": post_data[:3000],
                "response_body": body[:50000],
            })
            print(f"  [{len(capturas)-1}] {req.method} {url.split('/services/')[-1][:80]} -> {resp.status} ({len(body)} bytes)")

        page.on("response", on_response)

        # ── Login ────────────────────────────────────────────────────────────
        print("► Login SII...")
        rut_limpio = RUT.replace(".", "").replace("-", "").upper()
        page.goto(f"{SII_LOGIN_URL}?{SII_RCV_URL}")
        page.wait_for_load_state("networkidle")
        page.fill("input[name='rutcntr']", rut_limpio)
        page.fill("input[name='clave']", PWD)
        page.locator("input[name='clave']").press("Enter")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(8000)
        print(f"  URL post-login: {page.url}")

        # ── Seleccionar periodo y consultar ──────────────────────────────────
        print("► Periodo + Consultar...")
        page.wait_for_timeout(2000)
        selects = page.locator("select").all()
        print(f"  {len(selects)} selects encontrados")
        if len(selects) >= 2:
            selects[1].select_option(PERIODO_MES)
        if len(selects) >= 3:
            selects[2].select_option(PERIODO_ANO)
        page.click("button:has-text('Consultar'), input[value='Consultar']")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000)
        page.screenshot(path=str(OUT / "d1_post_consultar.png"), full_page=True)

        # ── Mapear tabla resumen COMPRA ───────────────────────────────────────
        print("► Filas de la tabla resumen:")
        rows = page.locator("table tbody tr").all()
        for i, row in enumerate(rows[:15]):
            try:
                print(f"  fila {i}: {row.inner_text()[:120]}")
            except Exception:
                pass

        # ── Click en cada link de tipo de documento ───────────────────────────
        print("► Buscando links dentro de la tabla...")
        links = page.locator("table a").all()
        print(f"  {len(links)} links en tablas")
        textos = []
        for l in links[:10]:
            try:
                textos.append(l.inner_text().strip())
            except Exception:
                textos.append("?")
        print(f"  textos: {textos}")

        if links:
            print("► Click en primer link (detalle tipo doc)...")
            links[0].click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(5000)
            page.screenshot(path=str(OUT / "d2_detalle_tipo.png"), full_page=True)

            # Botones disponibles en el detalle
            botones = page.locator("button, input[type='button'], input[type='submit']").all()
            print("► Botones visibles en detalle:")
            for b in botones[:20]:
                try:
                    txt = b.inner_text().strip() or b.get_attribute("value") or ""
                    if txt:
                        print(f"  - '{txt}'")
                except Exception:
                    pass

            # Intentar descargar el detalle
            for sel in ["button:has-text('Descargar')", "a:has-text('Descargar')",
                        "input[value*='Descargar']"]:
                try:
                    cnt = page.locator(sel).count()
                    if cnt:
                        print(f"► Encontrado '{sel}' ({cnt}) — click con expect_download...")
                        try:
                            with page.expect_download(timeout=20000) as dl:
                                page.locator(sel).first.click()
                            d = dl.value
                            dest = OUT / f"d3_descarga_{d.suggested_filename}"
                            d.save_as(str(dest))
                            print(f"  ✓ Descargado: {dest.name}")
                        except Exception as e:
                            print(f"  (sin download directo: {str(e)[:100]})")
                            page.screenshot(path=str(OUT / "d3_post_descargar.png"), full_page=True)
                        break
                except Exception:
                    continue

        # ── Guardar capturas ──────────────────────────────────────────────────
        (OUT / "xhr_capturas.json").write_text(
            json.dumps(capturas, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\n✓ {len(capturas)} XHR capturadas -> {OUT / 'xhr_capturas.json'}")

        time.sleep(2)
        browser.close()


if __name__ == "__main__":
    main()
