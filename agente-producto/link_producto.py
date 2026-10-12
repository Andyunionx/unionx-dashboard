"""Lee un link de producto (competencia en Chile, marketplace o proveedor de cualquier parte) y devuelve lo que sirve para
evaluarlo: nombre, marca, precio, moneda, código, imagen y si el precio es PVP de mercado o costo de proveedor.

Orden de lectura (lo primero que funcione):
  1. Tiendas Shopify: <url>.json (título, marca, tipo, precio, SKU y código de barras exactos).
  2. JSON-LD schema.org Product / ProductGroup (la mayoría de las tiendas y marketplaces).
  3. Open Graph (og:title, og:price:amount, og:price:currency).
  4. Solo el título de la página.
Si el sitio bloquea la lectura (Alibaba, Amazon a veces), se completa a mano: el resto del flujo es igual.
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
from urllib.parse import urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "es-CL,es;q=0.9,en;q=0.8"}
PROVEEDORES = ("alibaba.", "1688.", "made-in-china.", "globalsources.", "dhgate.", "tradekey.", "ec21.", "yiwugo.")
STOP = set("""de del la las el los y o en con sin para por a un una al su sus mas muy tipo modelo nuevo nueva original oficial set kit
pack x cm mm kg gr g ml lt l un unidades unidad color colores talla tamano incluye envio gratis oferta the and with for of in to new
free shipping pcs pc piece pieces size inch porciones porcion servicios sabor sabores natural unisex adulto nino nina""".split())
CANTIDAD = re.compile(r"^\d+([.,]\d+)?(KG|KGS|G|GR|GRS|ML|L|LT|LTS|CM|MM|M|MAH|W|V|PCS|U|UN|X\d+)?$")


def _sin_tilde(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def _num(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = re.sub(r"[^\d.,]", "", str(x))
    if not s:
        return None
    if "," in s and "." in s:                                   # 1.234,56 o 1,234.56
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        partes = s.split(",")
        s = s.replace(",", "") if len(partes[-1]) == 3 else s.replace(",", ".")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.split(".")[-1]) == 3):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _get(url: str, timeout: int = 20) -> requests.Response:
    """GET con reintento ante límite de consultas (429/503): las tiendas Shopify limitan lecturas seguidas."""
    import time
    r = requests.get(url, headers=UA, timeout=timeout)
    for intento in range(2):
        if r.status_code not in (429, 503):
            break
        espera = min(float(r.headers.get("Retry-After") or 0) or 2.0 * (intento + 1), 6.0)
        time.sleep(espera)
        r = requests.get(url, headers=UA, timeout=timeout)
    return r


def _shopify(url: str) -> dict | None:
    m = re.match(r"(https?://[^/]+/(?:[^/]+/)?products/[^/?#]+)", url)
    if not m:
        return None
    r = _get(m.group(1) + ".json")
    if not r.ok or "product" not in r.text[:200]:
        return None
    p = r.json()["product"]
    v = (p.get("variants") or [{}])[0]
    return {"nombre": p.get("title"), "marca": p.get("vendor"), "categoria_tienda": p.get("product_type"),
            "precio": _num(v.get("price")), "moneda": None, "sku": v.get("sku"), "gtin": v.get("barcode"),
            "imagen": ((p.get("image") or {}).get("src")), "descripcion": re.sub(r"<[^>]+>", " ", p.get("body_html") or "")[:600],
            "fuente_dato": "Shopify (.json)"}


def _jsonld(txt: str) -> dict | None:
    for bloque in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', txt, re.S):
        try:
            d = json.loads(bloque.strip())
        except Exception:  # noqa: BLE001
            continue
        cand = d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []
        for x in cand:
            if not isinstance(x, dict) or x.get("@type") not in ("Product", "ProductGroup"):
                continue
            ofs = x.get("offers") or (x.get("hasVariant") or [{}])[0].get("offers") or {}
            ofs = ofs[0] if isinstance(ofs, list) and ofs else ofs
            precio = ofs.get("price") or ofs.get("lowPrice") if isinstance(ofs, dict) else None
            marca = x.get("brand")
            marca = marca.get("name") if isinstance(marca, dict) else marca
            img = x.get("image")
            img = img[0] if isinstance(img, list) and img else img
            img = img.get("url") if isinstance(img, dict) else img
            return {"nombre": x.get("name"), "marca": marca, "precio": _num(precio),
                    "moneda": ofs.get("priceCurrency") if isinstance(ofs, dict) else None,
                    "sku": x.get("sku") or x.get("mpn"), "gtin": x.get("gtin13") or x.get("gtin") or x.get("gtin12"),
                    "imagen": img, "descripcion": (x.get("description") or "")[:600], "fuente_dato": "JSON-LD"}
    return None


def _og(txt: str) -> dict:
    meta = {k.lower(): html.unescape(v) for k, v in re.findall(
        r'<meta[^>]+(?:property|name)="((?:og|product|twitter):[^"]+)"[^>]+content="([^"]*)"', txt)}
    titulo = re.search(r"<title[^>]*>(.*?)</title>", txt, re.S)
    return {"nombre": meta.get("og:title") or (html.unescape(titulo.group(1)).strip() if titulo else None),
            "precio": _num(meta.get("og:price:amount") or meta.get("product:price:amount")),
            "moneda": meta.get("og:price:currency") or meta.get("product:price:currency"),
            "imagen": meta.get("og:image:secure_url") or meta.get("og:image"), "descripcion": (meta.get("og:description") or "")[:600],
            "fuente_dato": "Open Graph"}


def leer(url: str) -> dict:
    url = url.strip()
    dom = urlparse(url).netloc.lower().removeprefix("www.")
    out = {"url": url, "tienda": dom, "nombre": None, "marca": None, "precio": None, "moneda": None, "sku": None, "gtin": None,
           "imagen": None, "descripcion": "", "fuente_dato": None, "error": None}
    try:
        s = _shopify(url)
        if s:
            out.update({k: v for k, v in s.items() if v not in (None, "")})
        r = _get(url, timeout=25)
        if r.ok:
            for parte in (_jsonld(r.text), _og(r.text)):
                if parte:
                    for k, v in parte.items():
                        if out.get(k) in (None, "") and v not in (None, ""):
                            out[k] = v
        elif not s:
            out["error"] = (f"la página respondió {r.status_code}" + (" (demasiadas consultas seguidas: espera un minuto y vuelve a leer)"
                            if r.status_code == 429 else " (el sitio puede bloquear lecturas automáticas)"))
    except Exception as e:  # noqa: BLE001
        out["error"] = f"no pude leer la página ({type(e).__name__})"
    if out["moneda"] is None and (dom.endswith(".cl") or "mercadolibre.cl" in dom):
        out["moneda"] = "CLP"
    # ¿el precio del link es PVP de mercado o costo de proveedor?
    if any(p in dom for p in PROVEEDORES):
        out["rol_precio"] = "costo"
    elif out["moneda"] == "CLP":
        out["rol_precio"] = "pvp"
    else:
        out["rol_precio"] = "referencia"                     # tienda extranjera: precio de venta afuera, ni costo ni PVP local
    out["terminos"] = terminos(out)
    return out


def terminos(d: dict) -> list[str]:
    """Palabras para buscar en la DIN: marca, códigos de modelo y palabras del nombre (sin tildes, sin relleno)."""
    vistos, out = set(), []
    marca = _sin_tilde(str(d.get("marca") or "")).upper().replace("-", " ").strip()
    nombre = _sin_tilde(str(d.get("nombre") or "")).upper()
    nombre = re.sub(r"\|.*$", "", nombre)                    # "Producto | Tienda"
    for t in ([marca] if marca else []) + re.findall(r"[A-Z0-9][A-Z0-9\-\.]*", nombre):
        t = t.strip(".-")
        if (len(t) < 3 or t.lower() in STOP or t in vistos or t == marca.replace(" ", "") or CANTIDAD.match(t)
                or (t != marca and t in marca.split())):
            continue
        vistos.add(t)
        out.append(t)
    return out[:8]


# ── v3: texto completo, PDF enlazados (manual, ficha) y ficha técnica por patrones (respaldo sin IA) ──
def texto_visible(html_txt: str, max_chars: int = 20000) -> str:
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html_txt)
    t = re.sub(r"(?s)<br\s*/?>|</(p|li|div|tr|h\d)>", "\n", t)
    t = html.unescape(re.sub(r"(?s)<[^>]+>", " ", t))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()[:max_chars]


def pdfs_enlazados(html_txt: str, base_url: str, max_n: int = 3) -> list[str]:
    """Links a PDF (manuales, fichas, declaraciones CE) o a descargas de adjuntos."""
    from urllib.parse import urljoin
    out = []
    for h in re.findall(r'href="([^"]+)"', html_txt):
        h_ = html.unescape(h)
        if re.search(r"\.pdf(\?|$)", h_, re.I) or re.search(r"attachment.*download|download.*attachment", h_, re.I):
            u = urljoin(base_url, h_)
            if u not in out:
                out.append(u)
    return out[:max_n]


def leer_pdf(url: str, max_chars: int = 25000) -> str:
    import io
    try:
        r = _get(url, timeout=40)
        if not r.ok or r.content[:4] != b"%PDF" or len(r.content) > 25e6:
            return ""
        import pypdf
        pdf = pypdf.PdfReader(io.BytesIO(r.content))
        partes = []
        for pg in pdf.pages[:40]:
            partes.append(pg.extract_text() or "")
            if sum(map(len, partes)) > max_chars:
                break
        return "\n".join(partes)[:max_chars]
    except Exception:  # noqa: BLE001
        return ""


def ficha_por_patrones(texto: str) -> dict:
    """Ficha técnica mínima sin IA: potencia, capacidad, voltaje, medidas, peso y origen leídos con patrones."""
    t = _sin_tilde(texto).upper()
    num = lambda s: float(s.replace(",", "."))
    f = {}
    m = re.search(r"(\d{2,5})\s*(W|WATTS?|VATIOS?)\b", t)
    if m:
        f["potencia_w"] = num(m.group(1))
    caps = [num(x) for x in re.findall(r"(\d{2,4}(?:[.,]\d+)?)\s*ML\b", t)]
    lts = [num(x) * 1000 for x in re.findall(r"(\d(?:[.,]\d+)?)\s*(?:L|LT|LITROS?)\b", t)]
    if caps or lts:
        f["capacidad_ml"] = max(caps + lts)
    m = re.search(r"(\d{2,3})\s*-?\s*(\d{2,3})?\s*V\b", t)
    if m:
        f["voltaje"] = m.group(0).replace(" ", "")
    m = re.search(r"(\d{2,4}(?:[.,]\d+)?)\s*[X×]\s*(\d{2,4}(?:[.,]\d+)?)\s*[X×]\s*(\d{2,4}(?:[.,]\d+)?)\s*(MM|CM)", t)
    if m:
        k = 1 if m.group(4) == "MM" else 10
        f["medidas_mm"] = [num(m.group(i)) * k for i in (1, 2, 3)]
    m = re.search(r"(?:PESO|WEIGHT)[^0-9]{0,20}(\d+(?:[.,]\d+)?)\s*(KG|G)\b", t)
    if m:
        f["peso_kg"] = num(m.group(1)) / (1000 if m.group(2) == "G" else 1)
    m = re.search(r"(?:MADE IN|FABRICADO EN|HECHO EN)\s+([A-Z ]{3,20})", t)
    if m:
        f["origen"] = m.group(1).strip().title()
    m = re.search(r"(?:FABRICANTE|MANUFACTURER|IMPORTADO POR|DISTRIBUIDO POR)\s*[:.]?\s*([A-Z0-9&.,' \-]{4,80})", t)
    if m:
        f["fabricante_texto"] = m.group(1).strip()
    return f


def leer_completo(url: str) -> dict:
    """leer() + texto de la página + texto de hasta 2 PDF enlazados (manual/ficha) + ficha por patrones."""
    d = leer(url)
    texto, pdf_txt, pdfs = "", "", []
    try:
        r = _get(url, timeout=25)
        if r.ok:
            texto = texto_visible(r.text)
            pdfs = pdfs_enlazados(r.text, url)
            pdf_txt = "\n\n".join(t for t in (leer_pdf(u) for u in pdfs[:2]) if t)
    except Exception:  # noqa: BLE001
        pass
    d.update({"texto_pagina": texto, "pdfs": pdfs, "texto_pdfs": pdf_txt,
              "ficha_patrones": ficha_por_patrones(" ".join([d.get("nombre") or "", d.get("descripcion") or "", texto, pdf_txt[:8000]]))})
    return d
