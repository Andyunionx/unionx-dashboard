# -*- coding: utf-8 -*-
"""Scraper de stock Fulfillment by Falabella (FBF) desde el Seller Center.

Reemplaza la 'vista no descarga' (skill de Claudia) por acceso directo a la API
interna del Seller Center: pagina `/fby/v2/inbound-shipments/products` con los
headers reales de la app (authorization + tenant). Login vía SSO corporativo
(2 pasos) con Playwright; reusa la sesión guardada si sigue válida.

Salida: data/stock/fala_fbf_live.parquet  (canal, sku, qty, producto, offering_id,
ventas_4sem, ts). El pulso de reposición lo usa como stock de Falabella.

Credenciales: env FALA_USER / FALA_PASS  (o archivo .env.fala local, gitignored).
Uso: python scrape_fala_fbf.py
"""
import os
import sys
import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
SESSION = ROOT / "data/stock/fala_session.json"
OUT = ROOT / "data/stock/fala_fbf_live.parquet"
BASE = "https://sellercenter.falabella.com"
API = "https://sellercenter.falabella-marketplace.services/fby/v2/inbound-shipments/products"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")


def _creds():
    u, p = os.environ.get("FALA_USER"), os.environ.get("FALA_PASS")
    if u and p:
        return u, p
    envf = ROOT / ".env.fala"
    if envf.exists():
        d = {}
        for ln in envf.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                d[k.strip()] = v.strip()
        return d.get("FALA_USER"), d.get("FALA_PASS")
    return None, None


def _login(ctx):
    """SSO corporativo (email -> Continuar -> password -> Login). Guarda la sesión."""
    u, p = _creds()
    if not u or not p:
        raise RuntimeError("Faltan credenciales FALA_USER/FALA_PASS (env o .env.fala)")
    pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    pg.locator("input[type=email]:visible, input[type=text]:visible").first.fill(u)
    pg.get_by_role("button", name="Continuar").first.click()
    pg.wait_for_timeout(4000)
    pwd = pg.locator("input[type=password]:visible").first
    pwd.wait_for(timeout=20000, state="visible")
    pwd.fill(p)
    clicked = False
    for lbl in ["Login", "Ingresar", "Iniciar sesión", "Continuar", "Iniciar", "Entrar", "Acceder"]:
        btn = pg.get_by_role("button", name=lbl)
        if btn.count():
            btn.first.click(); clicked = True; break
    if not clicked:
        pg.locator("button[type=submit]:visible").first.click()
    pg.wait_for_timeout(9000)
    if "/auth" in pg.url or "/login" in pg.url:
        raise RuntimeError(f"Login falló (¿2FA o credenciales?). URL: {pg.url}")
    SESSION.parent.mkdir(parents=True, exist_ok=True)
    ctx.storage_state(path=str(SESSION))
    pg.close()


def _extraer(ctx):
    """Navega a /fulfillment/product, captura headers reales y pagina la API.
    Devuelve (df, expiro) — expiro=True si la sesión ya no sirve (redirige a login)."""
    cap = {"h": None}

    def on_req(req):
        if "inbound-shipments/products" in req.url and req.method == "GET" and cap["h"] is None:
            cap["h"] = dict(req.headers)

    pg = ctx.new_page()
    pg.on("request", on_req)
    pg.goto(BASE + "/fulfillment/product", wait_until="networkidle", timeout=90000)
    pg.wait_for_timeout(9000)
    if "/auth" in pg.url or "/login" in pg.url:
        pg.close(); return None, True
    h = cap["h"]
    if not h:
        pg.close(); return None, True   # no disparó la request -> tratar como expirada
    h.pop("content-length", None)

    rows, page = [], 1
    while True:
        r = pg.request.get(f"{API}?page={page}&pageSize=50&status=all", headers=h, timeout=30000)
        if r.status != 200:
            if page == 1 and r.status in (401, 403):
                pg.close(); return None, True
            print(f"[fbf][WARN] status {r.status} en page {page}", flush=True)
            break
        d = r.json()["data"]
        rows.extend(d["results"])
        if page >= d["totalPages"]:
            break
        page += 1
    pg.close()
    df = pd.DataFrame(rows)
    return df, False


def obtener_stock_fbf() -> pd.DataFrame:
    """Devuelve el stock FBF (canal, sku, qty, producto, offering_id, ventas_4sem)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            # 1) intentar con sesión guardada
            df = None
            if SESSION.exists():
                ctx = b.new_context(storage_state=str(SESSION), user_agent=UA)
                df, expiro = _extraer(ctx)
                ctx.close()
                if expiro:
                    df = None
            # 2) sin sesión válida -> login y reintento
            if df is None:
                ctx = b.new_context(user_agent=UA)
                _login(ctx)
                df, expiro = _extraer(ctx)
                ctx.close()
                if expiro or df is None:
                    raise RuntimeError("No se pudo extraer FBF tras login")
        finally:
            b.close()

    if df is None or df.empty:
        return pd.DataFrame(columns=["canal", "sku", "qty", "producto", "offering_id", "ventas_4sem"])
    out = pd.DataFrame({
        "canal": "Falabella",
        "sku": df["sellerSku"].astype(str).str.strip(),
        "qty": pd.to_numeric(df["availableStock"], errors="coerce").fillna(0).astype(int),
        "producto": df["name"].astype(str),
        "offering_id": df["offeringId"].astype(str),
        "ventas_4sem": pd.to_numeric(df.get("salesLastFourWeeks"), errors="coerce").fillna(0).astype(int),
    })
    # dedup por SKU (sumar si hubiera repetidos)
    out = out.groupby(["canal", "sku"], as_index=False).agg(
        qty=("qty", "sum"), producto=("producto", "first"),
        offering_id=("offering_id", "first"), ventas_4sem=("ventas_4sem", "sum"))
    return out


def main():
    df = obtener_stock_fbf()
    df["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    con = int((df["qty"] > 0).sum())
    print(f"[fbf] {len(df)} SKU | {con} con stock | {int(df['qty'].sum()):,} uds -> {OUT.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
