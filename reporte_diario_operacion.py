#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reporte Diario de Operación (Odoo -> HTML).

Da sensibilidad de lo que pasó AYER en la bodega. 4 componentes:
  1. Entregas del día por CANAL x MODALIDAD (B2C/FF/B2B) x LÍNEA DE NEGOCIO
     (+ preparación/picking del equipo por categoría WMS).
  2. Unidades RECEPCIONADAS por marca y producto.
  3. Unidades AJUSTADAS por marca y producto (ajustes de inventario + mermas).
  4. Cambios de stock por bodega (flujo neto del día: entra - sale).

Fuente: Odoo directo (stock.move done del día). Canal = stock.picking.x_canal.
Marca  = product.template.brand_id ("Marca (MultiVende)"). SKU = default_code.

Uso:
  python reporte_diario_operacion.py [--fecha YYYY-MM-DD]   # default: ayer
  (Prototipo: NO envía correo, solo genera + guarda HTML.)
"""
import argparse
import base64
import io
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))
OUT_DIR = PROJECT_ROOT / "data" / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Ubicaciones virtuales de ajuste / merma
LOC_ADJ = [14, 3298]      # Virtual Locations/Inventory adjustment
LOC_SCRAP = [16, 3300]    # Virtual Locations/Scrap
_BF_LOCS = ("BFML", "BFFa", "BFP", "BFR", "BFW", "BFE")

# Bodegas "reales" del equipo (para flujo de stock). El resto (Partners,
# Virtual Locations, Vendors, Production) son ubicaciones externas.
_EXTERNAS = ("Partners", "Virtual Locations", "Vendors", "Physical Locations",
             "Production", "Inter-warehouse")


# ---------------------------------------------------------------- Odoo
def get_odoo():
    env = PROJECT_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    from app.core.odoo_client import OdooClient
    cli = OdooClient(
        os.environ.get("ODOO_URL", "https://unionxb2b.odoo.com"),
        os.environ.get("ODOO_DB", "bmya-innovatek-sh-prd-6981800"),
        os.environ.get("OPS_ODOO_USER") or os.environ.get("ANDRES_ODOO_USER", "andres@grupoeter.cl"),
        os.environ.get("OPS_ODOO_PASSWORD") or os.environ.get("ANDRES_ODOO_PASSWORD", ""),
    )
    cli.authenticate()
    return cli


# ---------------------------------------------------------------- clasificación
def clasificar_wms(ptn, code, lo, ld):
    """Categoría WMS del movimiento según el trabajo real del equipo."""
    ptn, lo, ld = ptn or "", lo or "", ld or ""
    car = "Carrascal" in ptn
    res = "Reserva Stock" in ptn
    ff = "Fulfillment" in ptn
    dest_bf = any(b in ld for b in _BF_LOCS)
    orig_bf = any(b in lo for b in _BF_LOCS)
    if code == "outgoing":
        if ff or orig_bf:
            return "fulfillment_marketplace"
        if car:
            return "entrega_ca1"
        if res:
            return "entrega_reserva"
        return "otra_bodega"
    if code == "internal":
        if dest_bf:
            return "reposicion_fulfillment"
        if res:
            return "pick_reserva"
        if car:
            if "Output" in ld:
                return "pick_ca1"
            if "Input" in lo:
                return "recepcion_putaway"
            if "Stock" in lo and "Stock" in ld:
                return "reslotting"
            return "interno_ca1_otro"
        return "otra_bodega"
    if code == "incoming":
        return "recepcion"
    return "otra_bodega"


# canal (x_canal) -> (canal_display, tipo_negocio)
def cargar_canal_map():
    f = PROJECT_ROOT / "data" / "planillas" / "canal_tipo_negocio.json"
    base = {}
    if f.exists():
        raw = json.load(open(f, encoding="utf-8"))
        for k, v in raw.items():
            base[k.strip().lower()] = v.get("tipo_negocio", "")
    return base


def resolver_canal(x_canal, canal_map):
    """Devuelve (canal_display, tipo_negocio) desde x_canal de Odoo."""
    c = (x_canal or "").strip()
    if not c:
        return ("(sin canal)", "Sin clasificar")
    cl = c.lower()
    # marketplaces frecuentes
    reglas = [
        ("mercado libre", "Mercado Libre", "Marketplace"),
        ("mercado ripley", "Ripley", "Marketplace"),
        ("ripley", "Ripley", "Marketplace"),
        ("falabella", "Falabella", "Marketplace"),
        ("paris", "Paris", "Marketplace"),
        ("walmart", "Walmart", "Marketplace"),
        ("shopify", "Web propia (Shopify)", "Páginas Propias"),
        ("woocommerce", "Web propia", "Páginas Propias"),
    ]
    for key, disp, tn in reglas:
        if key in cl:
            return (disp, tn)
    # buscar en el mapa canónico
    tn = canal_map.get(cl) or canal_map.get(cl.replace(" chile", "").strip())
    return (c, tn or "Otro")


def modalidad(categoria, tipo_negocio):
    if categoria in ("fulfillment_marketplace", "reposicion_fulfillment"):
        return "Fulfillment"
    if tipo_negocio in ("Corporativo", "Distribución"):
        return "B2B"
    return "B2C"


def wh_code(locname):
    """Prefijo de bodega ('CA1/Stock' -> 'CA1'). Externa -> None."""
    if not locname:
        return None
    if any(locname.startswith(e) for e in _EXTERNAS):
        return None
    return locname.split("/")[0].strip()


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", help="YYYY-MM-DD (default: ayer)")
    args = ap.parse_args()

    if args.fecha:
        d = datetime.strptime(args.fecha, "%Y-%m-%d").date()
    else:
        d = date.today() - timedelta(days=1)
        if d.weekday() == 6:      # domingo (lunes reporta el viernes, último hábil)
            d = d - timedelta(days=2)
    d0 = f"{d} 00:00:00"
    d1 = f"{d + timedelta(days=1)} 00:00:00"
    print(f"=== Reporte Diario Operación — {d} ===", flush=True)

    cli = get_odoo()
    canal_map = cargar_canal_map()
    print("Odoo OK. Consultando movimientos del día...", flush=True)

    # 1) TODOS los stock.move done del día (para stock por bodega + ajustes)
    moves = cli.search_read(
        "stock.move",
        [("state", "=", "done"), ("date", ">=", d0), ("date", "<", d1)],
        ["id", "picking_id", "product_id", "product_uom_qty",
         "location_id", "location_dest_id"],
        limit=300000,
    )
    print(f"  {len(moves):,} movimientos done", flush=True)
    if not moves:
        print("[WARN] Sin movimientos ese día.", flush=True)
        return 1

    # 2) pickings involucrados -> canal + tipo + código
    pick_ids = list({m["picking_id"][0] for m in moves if m.get("picking_id")})
    picks = {}
    for i in range(0, len(pick_ids), 500):
        for p in cli.search_read(
            "stock.picking", [("id", "in", pick_ids[i:i + 500])],
            ["id", "name", "x_canal", "picking_type_id", "picking_type_code", "partner_id"],
            limit=500,
        ):
            picks[p["id"]] = p

    # 3) productos -> sku + marca (resolución cacheada, reutilizable)
    prod, brand = {}, {}

    def ensure_products(ids):
        falt = [i for i in set(ids) if i and i not in prod]
        tmpl_new = set()
        for i in range(0, len(falt), 500):
            for p in cli.search_read(
                "product.product", [("id", "in", falt[i:i + 500])],
                ["id", "default_code", "name", "product_tmpl_id"], limit=500,
            ):
                prod[p["id"]] = p
                tid = (p.get("product_tmpl_id") or [None])[0]
                if tid and tid not in brand:
                    tmpl_new.add(tid)
        tmpl_new = list(tmpl_new)
        for i in range(0, len(tmpl_new), 500):
            for t in cli.search_read(
                "product.template", [("id", "in", tmpl_new[i:i + 500])],
                ["id", "brand_id"], limit=500,
            ):
                brand[t["id"]] = (t.get("brand_id") or [None, "(sin marca)"])[1]

    ensure_products([m["product_id"][0] for m in moves if m.get("product_id")])

    def prod_info(pid):
        p = prod.get(pid, {})
        sku = p.get("default_code") or "s/sku"
        nm = p.get("name") or ""
        mid = (p.get("product_tmpl_id") or [None])[0]
        mk = brand.get(mid, "(sin marca)") if mid else "(sin marca)"
        return sku, nm, mk

    # ---- agregaciones ----
    # comp1: entregas (outgoing) por canal x modalidad x linea; + picking equipo
    entregas = defaultdict(lambda: {"ped": set(), "uds": 0.0})
    prep_cat = defaultdict(float)
    # comp2: recepciones por marca/producto
    recep = defaultdict(float)          # (marca, sku, nombre) -> uds
    recep_tipo = defaultdict(float)     # IN vs RET
    # comp3: ajustes por marca/producto (neto con signo)
    ajustes = defaultdict(float)
    # comp4: flujo de stock por bodega
    flujo = defaultdict(lambda: {"in": 0.0, "out": 0.0})

    for m in moves:
        q = m.get("product_uom_qty") or 0.0
        lo = (m.get("location_id") or [None, ""])[1]
        ld = (m.get("location_dest_id") or [None, ""])[1]
        lo_id = (m.get("location_id") or [None])[0]
        ld_id = (m.get("location_dest_id") or [None])[0]
        pk = picks.get((m.get("picking_id") or [None])[0], {})
        code = pk.get("picking_type_code", "")
        ptn = (pk.get("picking_type_id") or [None, ""])[1]
        cat = clasificar_wms(ptn, code, lo, ld)
        canal_disp, tn = resolver_canal(pk.get("x_canal"), canal_map)
        pid = (m.get("product_id") or [None])[0]

        # comp4 flujo bodega (neto): externa->wh = in ; wh->externa/otra wh = out
        wo, wd = wh_code(lo), wh_code(ld)
        if wo != wd:
            if wd:
                flujo[wd]["in"] += q
            if wo:
                flujo[wo]["out"] += q

        # comp3 ajustes / merma
        if lo_id in LOC_ADJ or ld_id in LOC_ADJ:
            sku, nm, mk = prod_info(pid)
            signo = q if ld_id not in LOC_ADJ else -q  # entra a stock (+) / sale (-)
            # si viene DESDE ajuste hacia bodega: +q ; si va a ajuste: -q
            if lo_id in LOC_ADJ:
                signo = q
            elif ld_id in LOC_ADJ:
                signo = -q
            ajustes[(mk, sku, nm)] += signo

        # comp2 recepciones
        if code == "incoming":
            sku, nm, mk = prod_info(pid)
            recep[(mk, sku, nm)] += q
            recep_tipo["Devolución (RET)" if "/RET/" in (pk.get("name") or "") else "Compra (IN)"] += q

        # comp1 entregas (outgoing a cliente) + preparación equipo
        if code == "outgoing":
            mod = modalidad(cat, tn)
            k = (canal_disp, mod, tn)
            entregas[k]["ped"].add((m.get("picking_id") or [None])[0])
            entregas[k]["uds"] += q
        if cat != "recepcion":   # recepción tiene su propia sección
            prep_cat[cat] += q

    # comp3b: mermas (stock.scrap done del día) con bodega + responsable
    scr = cli.search_read(
        "stock.scrap",
        [("state", "=", "done"), ("date_done", ">=", d0), ("date_done", "<", d1)],
        ["product_id", "scrap_qty", "location_id", "create_uid"], limit=5000)
    ensure_products([s["product_id"][0] for s in scr if s.get("product_id")])
    scrap_rows = []
    for s in scr:
        pid = (s.get("product_id") or [None])[0]
        sku, nm, mk = prod_info(pid)
        bod = (s.get("location_id") or [None, ""])[1].split("/")[0].strip() or "?"
        resp = (s.get("create_uid") or [None, "?"])[1]
        scrap_rows.append({"mk": mk, "sku": sku, "nm": nm, "bodega": bod,
                           "resp": resp, "uds": s.get("scrap_qty") or 0.0})

    # ---- salida HTML ----
    html = _render(d, entregas, prep_cat, recep, recep_tipo, ajustes, scrap_rows, flujo)
    out = OUT_DIR / f"reporte_diario_op_{d}.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nHTML guardado: {out.relative_to(PROJECT_ROOT)}", flush=True)

    # ---- envío (SEND=1) ----
    if os.environ.get("SEND") == "1":
        from email.mime.text import MIMEText
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        cj = os.environ.get("GMAIL_TOKEN_JSON", "")
        if not cj:
            tp = PROJECT_ROOT / "agente-comex" / "config" / "token.json"
            cj = tp.read_text() if tp.exists() else ""
        cd = json.loads(cj)
        creds = Credentials.from_authorized_user_info(cd, cd.get("scopes"))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        svc = build("gmail", "v1", credentials=creds)
        to = [e.strip() for e in os.environ.get(
            "EMAIL_TO", "andres@unionx.cl,gerardo@unionx.cl").split(",") if e.strip()]
        dias_s = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        m = MIMEText(html, "html", "utf-8")
        m["to"] = ",".join(to)
        m["from"] = "andres@unionx.cl"
        m["subject"] = f"\U0001f4e6 Reporte Diario Operación — {dias_s[d.weekday()]} {d.strftime('%d-%m')}"
        raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
        print("Enviado:", svc.users().messages().send(
            userId="me", body={"raw": raw}).execute().get("id"), flush=True)

    # ---- resumen consola ----
    tot_ent_uds = sum(v["uds"] for v in entregas.values())
    tot_ent_ped = len(set().union(*[v["ped"] for v in entregas.values()])) if entregas else 0
    print(f"\n--- RESUMEN {d} ---")
    print(f"  Entregas: {tot_ent_ped} pedidos · {tot_ent_uds:,.0f} uds")
    print(f"  Preparación equipo: " + " · ".join(f"{k} {v:,.0f}" for k, v in sorted(prep_cat.items())))
    print(f"  Recepciones: {sum(recep.values()):,.0f} uds ({len(recep)} productos)")
    print(f"  Ajustes: {sum(ajustes.values()):+,.0f} uds netos ({len(ajustes)} productos) · Merma {sum(r['uds'] for r in scrap_rows):,.0f} ({len(scrap_rows)} scraps)")
    print(f"  Bodegas con flujo: {len([w for w,v in flujo.items() if v['in'] or v['out']])}")
    return 0


def _tbl(rows, headers, aligns=None):
    aligns = aligns or ["left"] * len(headers)
    th = "".join(f'<th style="text-align:{a}">{h}</th>' for h, a in zip(headers, aligns))
    trs = ""
    for r in rows:
        tds = "".join(f'<td style="text-align:{a}">{c}</td>' for c, a in zip(r, aligns))
        trs += f"<tr>{tds}</tr>"
    return f'<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'


def _fmt(x):
    return f"{x:,.0f}".replace(",", ".")


def _render(d, entregas, prep_cat, recep, recep_tipo, ajustes, scrap, flujo):
    css = """
    body{font-family:'Segoe UI',Arial,sans-serif;color:#1a2332;margin:0;background:#f4f6f9;padding:24px}
    .wrap{max-width:960px;margin:0 auto}
    h1{font-size:20px;margin:0 0 2px}
    .sub{color:#64748b;font-size:13px;margin-bottom:20px}
    h2{font-size:15px;color:#1F3A5F;border-bottom:2px solid #2E75B6;padding-bottom:5px;margin:26px 0 10px}
    table{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.06);border-radius:6px;overflow:hidden}
    th{background:#1F3A5F;color:#fff;padding:7px 10px;font-weight:600}
    td{padding:6px 10px;border-top:1px solid #eef1f5}
    tbody tr:nth-child(even){background:#fafbfc}
    .tot td{font-weight:700;background:#eaf1f8;border-top:2px solid #2E75B6}
    .kpi{display:inline-block;background:#fff;border-radius:8px;padding:10px 16px;margin:0 8px 8px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)}
    .kpi b{font-size:20px;color:#1F3A5F;display:block}
    .kpi span{font-size:11px;color:#64748b}
    .neg{color:#c0392b}.pos{color:#1e8449}
    .note{font-size:11px;color:#94a3b8;margin-top:4px}
    """
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    # KPIs
    tot_uds = sum(v["uds"] for v in entregas.values())
    tot_ped = len(set().union(*[v["ped"] for v in entregas.values()])) if entregas else 0
    kpis = f"""
    <div class="kpi"><b>{_fmt(tot_ped)}</b><span>PEDIDOS ENTREGADOS</span></div>
    <div class="kpi"><b>{_fmt(tot_uds)}</b><span>UNIDADES ENTREGADAS</span></div>
    <div class="kpi"><b>{_fmt(sum(recep.values()))}</b><span>UDS RECEPCIONADAS</span></div>
    <div class="kpi"><b>{sum(ajustes.values()):+,.0f}</b><span>AJUSTE NETO (uds)</span></div>
    <div class="kpi"><b>{_fmt(sum(r['uds'] for r in scrap))}</b><span>MERMA (uds)</span></div>
    """.replace(",", ".")

    # comp1: entregas por canal x modalidad x linea
    rows1 = []
    for (canal, mod, tn), v in sorted(entregas.items(), key=lambda kv: -kv[1]["uds"]):
        rows1.append([canal, mod, tn, _fmt(len(v["ped"])), _fmt(v["uds"])])
    rows1.append(["TOTAL", "", "", _fmt(tot_ped), _fmt(tot_uds)])
    t1 = _tbl(rows1, ["Canal", "Modalidad", "Línea negocio", "Pedidos", "Unidades"],
              ["left", "left", "left", "right", "right"])

    # preparación equipo
    lbl = {"entrega_ca1": "Entrega CA1 (despacho a cliente)",
           "pick_ca1": "Picking CA1 (transferencia a zona salida)",
           "pick_reserva": "Picking Reserva", "entrega_reserva": "Entrega Reserva",
           "reposicion_fulfillment": "Reposición a Fulfillment",
           "fulfillment_marketplace": "Despacho Fulfillment (lo hace el mkp)",
           "recepcion_putaway": "Putaway de recepción", "reslotting": "Reslotting interno",
           "otra_bodega": "Movimientos otras bodegas", "interno_ca1_otro": "Interno CA1 otro"}
    rows_p = [[lbl.get(k, k), _fmt(v)] for k, v in sorted(prep_cat.items(), key=lambda kv: -kv[1]) if v]
    tprep = _tbl(rows_p, ["Actividad WMS del día", "Unidades"], ["left", "right"])

    # comp2: recepciones por marca/producto
    rr = sorted(recep.items(), key=lambda kv: -kv[1])
    rows2 = [[mk, sku, (nm[:48]), _fmt(u)] for (mk, sku, nm), u in rr[:40]]
    rows2.append(["TOTAL", "", f"{len(recep)} productos", _fmt(sum(recep.values()))])
    t2 = _tbl(rows2, ["Marca", "SKU", "Producto", "Uds"], ["left", "left", "left", "right"])
    rtipo = " · ".join(f"{k}: {_fmt(v)} uds" for k, v in recep_tipo.items()) or "sin recepciones"

    # comp3: ajustes por marca/producto
    aa = sorted(ajustes.items(), key=lambda kv: kv[1])  # más negativos primero
    rows3 = []
    for (mk, sku, nm), u in aa:
        cls = "neg" if u < 0 else "pos"
        rows3.append([mk, sku, nm[:48], f'<span class="{cls}">{u:+,.0f}</span>'.replace(",", ".")])
    if not rows3:
        rows3 = [["(sin ajustes de inventario ese día)", "", "", ""]]
    t3 = _tbl(rows3, ["Marca", "SKU", "Producto", "Ajuste uds"], ["left", "left", "left", "right"])
    smerma = ""
    if scrap:
        sm = sorted(scrap, key=lambda r: -r["uds"])
        rows_s = [[r["mk"], r["sku"], r["nm"][:40], r["bodega"], r["resp"], _fmt(r["uds"])]
                  for r in sm]
        tot_m = sum(r["uds"] for r in scrap)
        rows_s.append(["TOTAL", "", "", "", f"{len(scrap)} scraps", _fmt(tot_m)])
        smerma = "<h2>3b · Merma / Scrap del día (bodega y responsable)</h2>" + _tbl(
            rows_s, ["Marca", "SKU", "Producto", "Bodega", "Responsable", "Uds"],
            ["left", "left", "left", "left", "left", "right"])

    # comp4: flujo por bodega
    rows4 = []
    for w, v in sorted(flujo.items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"])):
        neto = v["in"] - v["out"]
        cls = "neg" if neto < 0 else "pos"
        rows4.append([w, _fmt(v["in"]), _fmt(v["out"]),
                      f'<span class="{cls}">{neto:+,.0f}</span>'.replace(",", ".")])
    t4 = _tbl(rows4, ["Bodega", "Entró", "Salió", "Neto"], ["left", "right", "right", "right"])

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body><div class="wrap">
    <h1>📦 Reporte Diario de Operación</h1>
    <div class="sub">{dias[d.weekday()]} {d.strftime('%d-%m-%Y')} · fuente Odoo (movimientos done del día)</div>
    {kpis}
    <h2>1 · Entregas por canal, modalidad y línea de negocio</h2>{t1}
    <div class="note">Modalidad: Fulfillment = despacho desde bodega del marketplace · B2B = Corporativo/Distribución · B2C = resto.</div>
    <h2>1b · Volumen operacional por categoría WMS</h2>{tprep}
    <div class="note">La entrega CA1 ≈ preparación real del equipo: la mayoría de pedidos se pican en un solo paso (no generan un "Picking CA1" separado, por eso ese número es menor).</div>
    <h2>2 · Unidades recepcionadas por marca y producto</h2>
    <div class="note">{rtipo}</div>{t2}
    <h2>3 · Unidades ajustadas por marca y producto</h2>
    <div class="note">Ajuste de inventario: (+) suma a stock, (−) resta. </div>{t3}{smerma}
    <h2>4 · Cambios de stock por bodega (flujo neto del día)</h2>{t4}
    <div class="note">Entró/Salió = unidades que entraron o salieron de cada bodega hacia otra bodega o ubicación externa (cliente, proveedor, ajuste). Neto = Entró − Salió.</div>
    </div></body></html>"""


if __name__ == "__main__":
    sys.exit(main())
