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
OUT_TRANSITO = ROOT / "data/stock/fala_transito_live.parquet"
BASE = "https://sellercenter.falabella.com"
API = "https://sellercenter.falabella-marketplace.services/fby/v2/inbound-shipments/products"
API_INTENTS = "https://sellercenter.falabella-marketplace.services/fby/v2/shipment-intents"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# Envíos a Full "en curso" = tránsito (aún no disponibles en el stock del canal).
# received/received_with_differences/cancelled quedan fuera. Los draft/prepared
# aún no viajan pero ya están comprometidos por bodega → cuentan para no volver
# a sugerir esos SKU (pedido Claudia sem 36: "no está tomando el tránsito").
TRANSITO_ESTADOS = {"draft", "prepared", "shipped", "in_warehouse"}
MAX_DIAS_TRANSITO = 21  # intents en curso más viejos que esto = fantasma → se excluyen y avisa


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
    Devuelve (df, intents, expiro) — expiro=True si la sesión ya no sirve."""
    cap = {"h": None}

    def on_req(req):
        if "inbound-shipments/products" in req.url and req.method == "GET" and cap["h"] is None:
            cap["h"] = dict(req.headers)

    pg = ctx.new_page()
    pg.on("request", on_req)
    pg.goto(BASE + "/fulfillment/product", wait_until="networkidle", timeout=90000)
    pg.wait_for_timeout(9000)
    if "/auth" in pg.url or "/login" in pg.url:
        pg.close(); return None, None, True
    h = cap["h"]
    if not h:
        pg.close(); return None, None, True   # no disparó la request -> tratar como expirada
    h.pop("content-length", None)

    rows, page, total_pages = [], 1, None
    while True:
        r = None
        for _intento in range(3):   # la API tira 503 transitorios → reintentar
            r = pg.request.get(f"{API}?page={page}&pageSize=50&status=all", headers=h, timeout=30000)
            if r.status == 200:
                break
            pg.wait_for_timeout(4000)
        if r.status != 200:
            if page == 1 and r.status in (401, 403):
                pg.close(); return None, None, True
            print(f"[fbf][WARN] status {r.status} en page {page} tras 3 intentos", flush=True)
            break
        d = r.json()["data"]
        total_pages = d["totalPages"]
        rows.extend(d["results"])
        if page >= total_pages:
            break
        page += 1
    stock_completo = total_pages is not None and page >= total_pages

    # Tránsito: envíos a Full (shipment-intents), mismos headers de auth. Orden
    # createdAt DESC → los en curso son recientes; 3 páginas (150) sobran.
    # intents=None si la consulta falló del todo (para NO pisar el parquet bueno).
    intents, ipage = [], 1
    try:
        while True:
            r = None
            for _intento in range(3):
                r = pg.request.get(f"{API_INTENTS}?page={ipage}&pageSize=50"
                                   f"&orderBy=createdAt:DESC&isNextPage=true",
                                   headers=h, timeout=30000)
                if r.status == 200:
                    break
                pg.wait_for_timeout(4000)
            if r.status != 200:
                print(f"[fbf][WARN] intents status {r.status} p{ipage}", flush=True)
                if ipage == 1:
                    intents = None
                break
            di = r.json()["data"]
            intents.extend(di["results"])
            if ipage >= di.get("totalPages", 1) or ipage >= 3:
                break
            ipage += 1
    except Exception as e:
        print(f"[fbf][WARN] intents: {type(e).__name__}: {e}", flush=True)
        if not intents:
            intents = None

    pg.close()
    df = pd.DataFrame(rows)
    df.attrs["completo"] = stock_completo
    if not stock_completo:
        print(f"[fbf][WARN] stock INCOMPLETO ({len(rows)} filas, cortó en p{page}"
              f"/{total_pages}) — no se pisará el parquet bueno", flush=True)
    return df, intents, False


def _qty_item(q):
    """Cantidad declarada de un item de shipment-intent. `quantity` viene como dict
    (accepted/rejected/...); se toma la llave de cantidad esperada o, si no calza
    ninguna conocida, el mayor valor numérico positivo del dict."""
    if isinstance(q, (int, float)):
        return float(q)
    if isinstance(q, dict):
        for k in ("expected", "declared", "requested", "sent", "total", "quantity", "created"):
            v = q.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
        vals = [v for v in q.values() if isinstance(v, (int, float)) and v > 0]
        return float(max(vals)) if vals else 0.0
    return 0.0


def procesar_transito(intents) -> pd.DataFrame:
    """Tránsito a Full por SKU desde los shipment-intents en curso.

    pendiente_intent = totalQuantity - received; se prorratea a los items (la
    recepción parcial no viene por SKU). Intents en curso más viejos que
    MAX_DIAS_TRANSITO se excluyen (fantasmas; regla 'nada pendiente >1 semana',
    con holgura) y se avisa para revisarlos con bodega."""
    import datetime as _dt
    ahora = _dt.datetime.now(_dt.timezone.utc)
    filas, viejos = [], []
    for it in intents or []:
        st = str(it.get("status", "")).lower()
        if st not in TRANSITO_ESTADOS:
            continue
        created = str((it.get("audit") or {}).get("createdAt") or "")[:19]
        try:
            edad = (ahora - _dt.datetime.fromisoformat(created).replace(tzinfo=_dt.timezone.utc)).days
        except ValueError:
            edad = 0
        if edad > MAX_DIAS_TRANSITO:
            viejos.append(f"{it.get('number')}({st},{edad}d)")
            continue
        tq = float(it.get("totalQuantity") or 0)
        rec = float(it.get("received") or 0)
        pend = max(0.0, tq - rec)
        if pend <= 0 or tq <= 0:
            continue
        ratio = pend / tq
        suma_items = 0.0
        for x in (it.get("items") or []):
            sku = str(x.get("sellerSku") or "").strip()
            q = _qty_item(x.get("quantity"))
            suma_items += q
            if sku and q > 0:
                filas.append({"canal": "Falabella", "sku": sku, "qty": q * ratio})
        if suma_items and abs(suma_items - tq) > max(2, tq * 0.1):
            print(f"[fbf][WARN] intent {it.get('number')}: items suman {suma_items:.0f} "
                  f"vs totalQuantity {tq:.0f} — revisar llave de cantidad", flush=True)
    if viejos:
        print(f"[fbf][WARN] intents en curso >{MAX_DIAS_TRANSITO}d EXCLUIDOS "
              f"(revisar con bodega): {viejos[:6]}", flush=True)
    df = pd.DataFrame(filas)
    if df.empty:
        return pd.DataFrame(columns=["canal", "sku", "qty"])
    return df.groupby(["canal", "sku"], as_index=False)["qty"].sum()


def obtener_stock_fbf():
    """Devuelve (stock, transito): stock FBF por SKU y tránsito a Full por SKU."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            # 1) intentar con sesión guardada
            df, intents = None, None
            if SESSION.exists():
                ctx = b.new_context(storage_state=str(SESSION), user_agent=UA)
                df, intents, expiro = _extraer(ctx)
                ctx.close()
                if expiro:
                    df = None
            # 2) sin sesión válida -> login y reintento
            if df is None:
                ctx = b.new_context(user_agent=UA)
                _login(ctx)
                df, intents, expiro = _extraer(ctx)
                ctx.close()
                if expiro or df is None:
                    raise RuntimeError("No se pudo extraer FBF tras login")
        finally:
            b.close()

    transito = procesar_transito(intents) if intents is not None else None
    completo = bool(df.attrs.get("completo", False)) if df is not None else False
    if df is None or df.empty:
        return (pd.DataFrame(columns=["canal", "sku", "qty", "producto", "offering_id", "ventas_4sem"]),
                transito, False)
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
    return out, transito, completo


def main():
    df, transito, completo = obtener_stock_fbf()
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if completo and len(df):
        df["ts"] = ts
        df.to_parquet(OUT, index=False)
        con = int((df["qty"] > 0).sum())
        print(f"[fbf] {len(df)} SKU | {con} con stock | {int(df['qty'].sum()):,} uds -> {OUT.name}", flush=True)
    else:
        print(f"[fbf][WARN] stock incompleto/vacío — se conserva el último {OUT.name} bueno", flush=True)
    if transito is not None:
        transito = transito.copy()
        transito["ts"] = ts
        transito.to_parquet(OUT_TRANSITO, index=False)
        print(f"[fbf] tránsito a Full: {len(transito)} SKU | {transito['qty'].sum():,.0f} uds "
              f"-> {OUT_TRANSITO.name}", flush=True)
    else:
        print(f"[fbf][WARN] intents no disponibles — se conserva el último {OUT_TRANSITO.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
