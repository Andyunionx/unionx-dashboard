"""Costeo retroactivo de embarques ene–mar 2026 que nunca pasaron por el precosteo (solo tienen OC en Odoo a FOB×TC).

Mismo método que el agente COMEX (costear_embarque.py): PI + PL del correo de Steven (caché data/comex/pi_pl_gmail) +
flete FINAL de la API de Seimex + gastos Chile estándar. TC = el que usó la OC de Odoo (precio OC ÷ FOB del PI).
Salida en una carpeta de STAGING (no la lee el sincronizador hasta que se valide):
  C:/Users/andre/comex_maestra/retro/<EMB>/Pre-costeo_x_CBM_<EMB>.xlsx  + validacion.json (cuadre contra Odoo)
Uso:  python retro_costeo.py 26TP0115 [26TP0105 …]
"""
import json
import os
import re
import sys
import xmlrpc.client
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path("G:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA")
sys.path.insert(0, str(REPO / "_REACTIVAR_NUEVO_PC"))
sys.path.insert(0, str(REPO))
import costear_embarque as ce  # noqa: E402

CACHE = REPO / "data" / "comex" / "pi_pl_gmail"
STAGING = Path("C:/Users/andre/comex_maestra/retro")
CHILE_GASTOS = {"STI": 20000, "Transporte terrestre": 415000, "Seimex": 238529, "Desconsolidación": 50000,
                "Despacho": 43658, "Gate in": 145000}          # = fase3_costeo.CHILE_GASTOS
PUERTOS = {"SZ": "Shenzhen", "NB": "Ningbo", "XI": "Xiamen"}


def _env():
    env = {}
    for linea in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in linea and not linea.lstrip().startswith("#"):
            k, v = linea.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = _env()
os.environ.setdefault("SEIMEX_EMAIL", ENV.get("SEIMEX_EMAIL", ""))
os.environ.setdefault("SEIMEX_PASSWORD", ENV.get("SEIMEX_PASSWORD", ""))


ODOO_URL, ODOO_DB, ODOO_USER = "https://unionxb2b.odoo.com", "bmya-innovatek-sh-prd-6981800", "andres@grupoeter.cl"


def odoo():
    url, db, user = ODOO_URL, ODOO_DB, ODOO_USER
    pwd = ENV.get("ANDRES_ODOO_PASSWORD")          # desde .env (nunca en el código)
    uid = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common").authenticate(db, user, pwd, {})
    o = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return lambda m, meth, *a, **k: o.execute_kw(db, uid, pwd, m, meth, list(a), k)


def archivos(emb: str):
    """(PI, PL, PI de Dinasty si el contenedor es compartido) — la versión más reciente de cada uno.
    Si hay un PI 'Innovatek' (contenedor compartido), ese es el nuestro; el PI sin nombre es el combinado."""
    num = emb[-4:]
    fs = sorted((p for p in CACHE.iterdir() if f"26TP{num}PI" in p.name), key=lambda p: p.name[:8] + p.name)
    pis = [p for p in fs if re.search(r"PI\s*(SZ|NB|XI|Innovatek)", p.name, re.I) and "dinasty" not in p.name.lower()]
    innov = [p for p in pis if "innovatek" in p.name.lower()]
    pls = [p for p in fs if re.search(r"PI\s*PL\.xlsx?$", p.name, re.I)]
    din = [p for p in fs if "dinasty" in p.name.lower()]
    pi = innov[-1] if innov else (pis[-1] if pis else None)
    return pi, (pls[-1] if pls else None), (din[-1] if (din and innov) else None)


def dolar_observado(fecha: str) -> float | None:
    """Dólar observado (mindicador.cl) del día o del hábil anterior más cercano."""
    import requests
    d = datetime.strptime(fecha[:10], "%Y-%m-%d")
    for k in range(0, 8):
        dd = (d - timedelta(days=k)).strftime("%d-%m-%Y")
        try:
            s = requests.get(f"https://mindicador.cl/api/dolar/{dd}", timeout=10).json().get("serie", [])
            if s:
                return float(s[0]["valor"])
        except Exception:
            continue
    return None


def sku_desde_oc(productos, lineas, tc):
    """El SKU correcto es el de Odoo. Reglas, en orden (cada línea de la OC se usa una sola vez):
      1. el SKU del PI existe en la OC → se deja;
      2. misma cantidad exacta y UNA sola línea candidata en la OC → su SKU (el precio de las OC antiguas no sirve
         para comparar: a veces es FOB × 960 y a veces ya trae flete);
      3. varias candidatas con la misma cantidad → la de precio (CLP ÷ USD) más parecido a la mediana de las ya amarradas;
      4. cantidad casi igual (±2 u o ±2%) y una sola candidata → su SKU;
      5. variantes de color: el PI trae un solo SKU S con más unidades que la OC y la OC tiene S-XX por la
         diferencia (HD4: TCMULTSTY5N1 2.004 en el PI = 1.002 base + 1.002 -BG en la OC) → se parte la línea."""
    import copy
    usadas, cambios = set(), []
    por_sku = {}
    for i, l in enumerate(lineas):
        if l["sku"]:
            por_sku.setdefault(l["sku"], []).append(i)
    for p in productos:
        s = str(p.sku or "").strip()
        if s in por_sku:
            usadas.update(i for i in por_sku[s] if abs(lineas[i]["qty"] - p.qty) < 0.5 or len(por_sku[s]) == 1)

    def libres(cond):
        return [i for i, l in enumerate(lineas) if i not in usadas and l["sku"] and cond(l)]
    ratios = []
    nuevos = []
    for p in productos:
        s = str(p.sku or "").strip()
        if s in por_sku:
            oc_q = sum(lineas[i]["qty"] for i in por_sku[s])
            if p.qty - oc_q > 0.5:        # regla 5: variantes
                var = libres(lambda l: l["sku"].startswith(s + "-") and abs(l["qty"] - (p.qty - oc_q)) < 0.5)
                if len(var) == 1:
                    i = var[0]
                    usadas.add(i)
                    q = copy.copy(p)
                    fr = lineas[i]["qty"] / p.qty
                    for attr in ("cbm_total", "delivery_total"):     # totales de la línea: se reparten por unidades
                        v = getattr(p, attr, 0) or 0
                        setattr(q, attr, v * fr)
                        setattr(p, attr, v * (1 - fr))
                    q.qty, q.sku = lineas[i]["qty"], lineas[i]["sku"]
                    p.qty = oc_q
                    nuevos.append(q)
                    cambios.append((p.model, f"{s} {oc_q + q.qty:.0f} u", f"{s} {oc_q:.0f} + {q.sku} {q.qty:.0f} (OC)"))
            continue
        cands = libres(lambda l: abs(l["qty"] - p.qty) < 0.5)
        if len(cands) > 1 and ratios and p.price:
            med = sorted(ratios)[len(ratios) // 2]
            cands = [min(cands, key=lambda i: abs(lineas[i]["precio_clp"] / p.price - med))]
        if not cands:
            cands = libres(lambda l: abs(l["qty"] - p.qty) <= max(2, 0.02 * p.qty))
        if len(cands) == 1:
            i = cands[0]
            usadas.add(i)
            if p.price:
                ratios.append(lineas[i]["precio_clp"] / p.price)
            cambios.append((p.model, s or "(sin SKU)", lineas[i]["sku"]))
            p.sku = lineas[i]["sku"]
    productos.extend(nuevos)
    return cambios


def flete_seimex(emb: str):
    from seimex_api import SeimexAPI
    sys.path.insert(0, str(REPO / "agente-comex-auto"))
    import fase2_seimex as f2
    op = f2._match_operacion(SeimexAPI().get_operations(), emb)
    if not op:
        return None, None, None
    return op.get("quoted_freight_value"), op.get("eta"), op


def pos_odoo(x, emb: str):
    pos = x("purchase.order", "search_read", [["partner_ref", "ilike", emb]], fields=["name", "partner_ref", "state"])
    lineas = []
    for po in pos:
        for l in x("purchase.order.line", "search_read", [["order_id", "=", po["id"]]],
                   fields=["product_id", "product_qty", "price_unit"]):
            code = x("product.product", "read", [l["product_id"][0]], fields=["default_code"])[0]["default_code"] if l["product_id"] else None
            lineas.append({"po": po["name"], "sku": code, "qty": l["product_qty"], "precio_clp": l["price_unit"]})
    return pos, lineas


def costear(emb: str, x) -> dict:
    pi, pl, din = archivos(emb)
    if not pi or not pl:
        return {"embarque": emb, "error": f"falta PI ({pi}) o PL ({pl})"}
    productos, inland, numero, puerto = ce.leer_pi(pi)
    ce.leer_pl(pl, productos)
    flete, eta, op = flete_seimex(emb)
    pos, lineas = pos_odoo(x, emb)
    # TC = dólar observado al llegar el barco (cuando se paga el saldo y se acepta la DIN); el precio de las OC
    # antiguas NO siempre es FOB × TC (a veces trae otros cargos), así que no sirve para despejar el TC
    tc = (dolar_observado(eta) if eta else None) or 950.0
    cambios_sku = sku_desde_oc(productos, lineas, tc)
    nota_flete = ""
    if din and flete:   # contenedor compartido con Dinasty: el flete se reparte por CBM
        pd_, _, _, _ = ce.leer_pi(din)
        ce.leer_pl(pl, pd_)
        cbm_ux, cbm_din = sum(p.cbm_total for p in productos), sum(p.cbm_total for p in pd_)
        if cbm_ux + cbm_din > 0:
            share = cbm_ux / (cbm_ux + cbm_din)
            nota_flete = f"contenedor compartido con Dinasty: flete × {share:.2f} (CBM UnionX {cbm_ux:.1f} / total {cbm_ux + cbm_din:.1f})"
            flete = float(flete) * share
    eta_bodega = (datetime.strptime(eta[:10], "%Y-%m-%d") + timedelta(days=5)).strftime("%Y-%m-%d") if eta else ""
    tar = ce.Tarifas(puerto=puerto, puerto_nombre=PUERTOS.get(puerto, puerto), dolar=tc, fecha_eta=eta_bodega,
                     flete_total_usd=float(flete or 0.0), gastos_chile_clp=dict(CHILE_GASTOS))
    embq = ce.Embarque(numero=emb, puerto=puerto, puerto_nombre=PUERTOS.get(puerto, puerto),
                       productos=productos, inland_china=inland, tarifas=tar)
    ce.calcular_costeo(embq)
    out = STAGING / emb
    out.mkdir(parents=True, exist_ok=True)
    path = ce.generar_precosteo_xlsx(embq, out)
    # cuadre contra Odoo: unidades por SKU y FOB total
    u_pi = {}
    for p in productos:
        u_pi[str(p.sku or p.model).strip()] = u_pi.get(str(p.sku or p.model).strip(), 0) + p.qty
    u_po = {}
    for l in lineas:
        u_po[l["sku"]] = u_po.get(l["sku"], 0) + l["qty"]
    difs = sorted({(str(k), u_pi.get(k, 0), u_po.get(k, 0)) for k in set(u_pi) | set(u_po) if abs(u_pi.get(k, 0) - u_po.get(k, 0)) > 0.5})
    # líneas del PI que no son productos (notas, cargos de fábrica): quedan sin SKU y se informan
    notas = [(p.model, str(p.sku or ""), p.qty, p.price) for p in productos
             if re.search(r"\s|:|,", str(p.sku or "")) or re.search(r"rework|wechat|charge|deposit", str(p.model) + str(p.sku or ""), re.I)]
    val = {"embarque": emb, "pi": pi.name, "pl": pl.name, "dinasty": din.name if din else None, "puerto": puerto,
           "tc_oc": round(tc, 2), "flete_usd": round(float(flete or 0), 2), "nota_flete": nota_flete,
           "seimex_ref": op.get("reference_number") if op else None, "eta_puerto": eta, "eta_bodega": eta_bodega,
           "ocs": [p["name"] for p in pos], "unidades_pi": sum(u_pi.values()), "unidades_oc": sum(u_po.values()),
           "fob_pi_usd": round(embq.total_pxq, 2), "fob_oc_usd": round(sum(l["qty"] * l["precio_clp"] for l in lineas) / tc, 2) if tc else None,
           "internado_clp": round(embq.total_internado_clp), "sobrecosto_pct": round(embq.sobrecosto_pct, 2),
           "diferencias_sku": difs[:30], "no_reconocidos": [str(n) for n in (inland.no_reconocidos or [])],
           "sku_desde_oc": cambios_sku, "notas_como_producto": notas, "precosteo": str(path)}
    (out / "validacion.json").write_text(json.dumps(val, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return val


if __name__ == "__main__":
    x = odoo()
    for emb in sys.argv[1:]:
        try:
            v = costear(emb, x)
        except Exception as e:
            v = {"embarque": emb, "error": f"{type(e).__name__}: {e}"}
        print(json.dumps({k: v.get(k) for k in ("embarque", "error", "pi", "pl", "dinasty", "tc_oc", "flete_usd", "nota_flete", "seimex_ref",
                                                 "eta_bodega", "ocs", "unidades_pi", "unidades_oc", "fob_pi_usd", "fob_oc_usd",
                                                 "internado_clp", "sobrecosto_pct", "diferencias_sku", "sku_desde_oc",
                                                 "notas_como_producto", "no_reconocidos")},
                         ensure_ascii=False, default=str))
