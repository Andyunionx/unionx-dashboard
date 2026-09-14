"""Reconciliación PI ↔ PO en Odoo — detecta líneas faltantes.

Para cada PI de embarque (data/comex/embarques/**/*PI*.xlsx), busca su PO en Odoo
(partner_ref con el número de embarque) y compara los productos del PI vs las líneas
de la PO. Reporta los productos del PI que NO tienen línea en la PO = faltantes.

Matching robusto a renombres/variantes:
  1) por SKU exacto (PI sku == default_code de la línea)
  2) si no, por CANTIDAD + solape de descripción (greedy: cada producto del PI
     reclama una línea de la PO con la misma qty y mejor solape de palabras)
Así los SKU que se renombraron al crear la variante (ej. LHSMARTWAPE→LHSWSHAR,
SMCAFIT4→SMCFIT4) igual calzan por qty+desc y no dan falso positivo.

Uso:
  python reconciliar_pi_po.py                 # reporte a consola + data/comex/reconciliacion_pi_po.json
  python reconciliar_pi_po.py --email         # además envía correo si hay faltantes
  python reconciliar_pi_po.py --emb 26TP0608  # solo un embarque
"""
import json
import os
import re
import sys
import glob
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "_REACTIVAR_NUEVO_PC"))
import costear_embarque as ce  # noqa: E402

import xmlrpc.client  # noqa: E402

URL = "https://unionxb2b.odoo.com"; DB = "bmya-innovatek-sh-prd-6981800"
DEST = ["andres@unionx.cl", "sguzman@grupoeter.cl"]
STOP = {"de", "la", "el", "los", "las", "con", "para", "simplit", "simp", "levo",
        "xroad", "real", "cup", "y", "ml", "cm", "un", "una", "the", "a", "of"}
_RE_EMB = re.compile(r"(2[56]TP\d{4})", re.IGNORECASE)


def _toks(s):
    return set(re.findall(r"[a-z0-9]{2,}", str(s).lower())) - STOP


def _odoo():
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD")
    uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, "andres@grupoeter.cl", pwd, {})
    return xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object"), uid, pwd


def _pi_files():
    fs = {}
    for f in glob.glob(str(ROOT / "data" / "comex" / "embarques" / "**" / "*PI*.xlsx"), recursive=True):
        if "PL" in os.path.basename(f) or "~$" in f:
            continue
        mm = _RE_EMB.search(os.path.basename(f))
        if mm:
            fs.setdefault(mm.group(1).upper(), f)  # un PI por embarque (el primero)
    return fs


def _po_lines(models, uid, pwd, emb):
    dom = ["|", ["partner_ref", "ilike", emb], ["origin", "ilike", emb]]
    pos = models.execute_kw(DB, uid, pwd, "purchase.order", "search_read",
                            [dom + [["state", "!=", "cancel"]]], {"fields": ["name", "state", "order_line"]})
    out = []
    for p in pos:
        if not p["order_line"]:
            continue
        lns = models.execute_kw(DB, uid, pwd, "purchase.order.line", "read",
                               [p["order_line"]], {"fields": ["product_id", "product_qty"]})
        for l in lns:
            code = str(l["product_id"][1]).split("]")[0].strip("[") if l.get("product_id") else ""
            out.append({"po": p["name"], "state": p["state"], "code": code.upper(),
                        "name": str(l["product_id"][1]) if l.get("product_id") else "", "qty": l["product_qty"]})
    return out, [p["name"] for p in pos]


def _reconciliar(pi_prods, po_lines):
    unmatched = list(po_lines)
    faltan = []
    for p in pi_prods:
        sku = (p.sku or "").strip().upper()
        hit = next((l for l in unmatched if sku and l["code"] == sku), None)
        if hit:
            unmatched.remove(hit); continue
        cands = [l for l in unmatched if abs(l["qty"] - float(p.qty)) < 0.5]
        if cands:
            ptk = _toks(p.descripcion)
            best = max(cands, key=lambda l: len(ptk & _toks(l["name"])))
            unmatched.remove(best); continue
        faltan.append({"model": p.model, "sku": p.sku or "(sin código)",
                       "qty": int(p.qty), "desc": str(p.descripcion).split("\n")[0][:50]})
    return faltan


def main():
    solo = None
    if "--emb" in sys.argv:
        solo = sys.argv[sys.argv.index("--emb") + 1].upper()
    enviar = "--email" in sys.argv

    models, uid, pwd = _odoo()
    pis = _pi_files()
    if solo:
        pis = {k: v for k, v in pis.items() if k == solo}
    print(f"Embarques con PI: {len(pis)}\n")

    reporte = {}
    for emb, pi in sorted(pis.items()):
        try:
            prods, _, _, _ = ce.leer_pi(Path(pi))
        except Exception as e:
            print(f"  {emb}: error leyendo PI ({e})"); continue
        po_lines, po_names = _po_lines(models, uid, pwd, emb)
        if not po_names:
            continue  # sin PO en Odoo aún → no aplica
        faltan = _reconciliar(prods, po_lines)
        estado = "✅ OK" if not faltan else f"⚠️ {len(faltan)} FALTANTES"
        print(f"  {emb:<12} PO={','.join(po_names):<20} PI={len(prods):>3} · PO={len(po_lines):>3} líneas · {estado}")
        for f in faltan:
            print(f"       ✗ {f['model']:<10} {f['sku']:<16} qty={f['qty']:<5} {f['desc']}")
        if faltan:
            reporte[emb] = {"pos": po_names, "faltantes": faltan}

    out = ROOT / "data" / "comex" / "reconciliacion_pi_po.json"
    out.write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")
    total = sum(len(v["faltantes"]) for v in reporte.values())
    print(f"\n{'='*50}\nPO con faltantes: {len(reporte)} · líneas faltantes: {total}")
    print(f"Reporte: {out}")

    if enviar and reporte:
        _enviar(reporte, total)


def _enviar(reporte, total):
    sys.path.insert(0, str(ROOT / "agente-comex" / "src"))
    from gmail_client import GmailClient
    filas = ""
    for emb, v in sorted(reporte.items()):
        for f in v["faltantes"]:
            filas += (f"<tr><td style='padding:6px;border:1px solid #ddd'>{emb} ({','.join(v['pos'])})</td>"
                      f"<td style='padding:6px;border:1px solid #ddd'>{f['sku']}</td>"
                      f"<td style='padding:6px;border:1px solid #ddd'>{f['qty']}</td>"
                      f"<td style='padding:6px;border:1px solid #ddd'>{f['desc']}</td></tr>")
    html = (f"<div style='font-family:Arial,sans-serif;font-size:14px;color:#333'>"
            f"<p>Detecté <b>{total} líneas del PI que faltan en su PO</b> (reconciliación automática):</p>"
            f"<table style='border-collapse:collapse'><tr style='background:#1F3864;color:#fff'>"
            f"<th style='padding:6px;border:1px solid #ddd'>Embarque (PO)</th><th style='padding:6px;border:1px solid #ddd'>SKU</th>"
            f"<th style='padding:6px;border:1px solid #ddd'>Qty</th><th style='padding:6px;border:1px solid #ddd'>Producto</th></tr>"
            f"{filas}</table><p>Favor revisar y completar las PO. Saludos.</p></div>")
    mid = GmailClient().send_email(to=", ".join(DEST),
                                   subject=f"⚠️ Reconciliación PI↔PO — {total} líneas faltantes en {len(reporte)} embarque(s)",
                                   body_html=html)
    print(f"Correo de faltantes enviado a {', '.join(DEST)} · id {mid}")


if __name__ == "__main__":
    main()
