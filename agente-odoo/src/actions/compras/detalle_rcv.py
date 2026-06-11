"""
Detalle del RCV SII via la API interna del portal — SOLO LECTURA.

Descubierto 11-jun-2026: al hacer click en un tipo de documento de la tabla
resumen del RCV, la app Angular llama a
  POST /consdcvinternetui/services/data/facadeService/getDetalleCompra
y recibe JSON con el detalle documento por documento (RUT, folio, fecha,
neto, IVA, total) al instante.

NOTA: la facultad de crear borradores en Odoo fue ELIMINADA por decisión
de Andrés (11-jun-2026): "Cargar manualmente una factura sin detalle de
la glosa no es útil". Este módulo solo alimenta la comparación SII vs Odoo
del mail diario con el detalle exacto de faltantes.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

SII_LOGIN_URL = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html"
SII_RCV_URL   = "https://www4.sii.cl/consdcvinternetui/"

MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

NOMBRE_TIPO_DOC = {
    "33": "Factura electrónica",
    "34": "Factura no afecta",
    "43": "Liquidación-Factura",
    "56": "Nota de débito",
    "61": "Nota de crédito",
}


def norm_folio(s) -> str:
    """'002256' / 'FAC 002256' / 2256.0 → '2256' (solo dígitos, sin ceros izq)."""
    digits = "".join(ch for ch in str(s or "") if ch.isdigit())
    return str(int(digits)) if digits else ""


def norm_rut_sin_dv(v) -> str:
    """'76.243.813-5' → '76243813' (sin puntos, guión ni DV)."""
    v = str(v or "").replace(".", "").replace("-", "").strip().upper()
    return v[:-1] if len(v) > 1 else v


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


def obtener_detalle_compras_api(year: int, month: int, rut: str, password: str,
                                 headless: bool = False) -> tuple[list[dict], list[str]]:
    """
    Login + RCV → detalle completo del periodo via getDetalleCompra.

    Returns: (docs, errores)
      docs = [{tipo_doc, rut_emisor, razon_social, folio, fecha,
               monto_neto, monto_iva, monto_total}]

    Guarda snapshot en data/contabilidad/sii/detalle_rcv_YYYY-MM.json.
    """
    from playwright.sync_api import sync_playwright

    capturas: list[tuple[str, dict]] = []
    errores: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.set_default_timeout(45_000)

        try:
            _login_sii(page, rut, password)
        except Exception as e:
            browser.close()
            return [], [f"Login SII: {e}"]

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
                errores.append("Tabla resumen sin links (¿periodo sin docs?)")

            for i in range(n_links):
                nombre = "?"
                try:
                    links = page.locator("table a").all()
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
            browser.close()

    # ── Parsear capturas ─────────────────────────────────────────────────
    docs = []
    vistos = set()
    for cod_tipo, body in capturas:
        data = body.get("data")
        if not isinstance(data, list):
            continue
        for d in data:
            folio = str(d.get("detNroDoc", "")).strip()
            rut_e = f"{d.get('detRutDoc','')}-{d.get('detDvDoc','')}"
            key = (cod_tipo, rut_e, folio)
            if key in vistos:
                continue
            vistos.add(key)
            neto = float(d.get("detMntNeto") or 0)
            exento = float(d.get("detMntExe") or 0)
            docs.append({
                "tipo_doc":     cod_tipo,
                "rut_emisor":   rut_e.replace(".", "").upper(),
                "razon_social": str(d.get("detRznSoc") or "").strip(),
                "folio":        folio,
                "fecha":        _fecha_iso(str(d.get("detFchDoc") or "")),
                "monto_neto":   neto if neto else exento,
                "monto_iva":    float(d.get("detMntIVA") or 0),
                "monto_total":  float(d.get("detMntTotal") or 0),
            })

    # Snapshot (auditoria + apps)
    try:
        out_dir = Path(__file__).resolve().parents[4] / "data" / "contabilidad" / "sii"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"detalle_rcv_{year:04d}-{month:02d}.json").write_text(
            json.dumps(docs, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    return docs, errores


def claves_compras_odoo(client, year: int, month: int) -> set:
    """
    Set de claves (rut_sin_dv, folio_normalizado) de facturas de compra en Odoo.
    Ventana: mes anterior + mes actual (el RCV incluye docs fechados el mes previo).
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
        rut = norm_rut_sin_dv(vat_por_pid.get(r["partner_id"][0], "")) if r.get("partner_id") else ""
        candidatos = [r.get("l10n_latam_document_number")]
        ref = str(r.get("ref") or "")
        if ref.split():
            candidatos.append(ref.split()[-1])
        for cand in candidatos:
            folio = norm_folio(cand)
            if folio:
                claves.add((rut, folio))
    return claves
