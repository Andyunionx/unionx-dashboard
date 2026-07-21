# -*- coding: utf-8 -*-
"""Overlay: mete a JUNIO las boletas de venta cuyo invoice_date es junio pero cuya
orden (date_order) es julio → cayeron en el hueco del cruce de meses del extract
(ver [[extract_cruce_meses_facturas]]). Reconciliación por documento.

Uso:  python overlay_crossover_junio.py           # dry-run
      python overlay_crossover_junio.py --apply   # aplica (backup .bak_crossover)
"""
import argparse, os, re, shutil
from pathlib import Path
from collections import Counter
import pandas as pd
import xmlrpc.client

ROOT = Path(__file__).resolve().parent
HIST = ROOT / "data" / "historico" / "ventas_historico.parquet"
norm = lambda s: str(s or "").strip().upper()

# canal Odoo (sale.order.channel) -> canal del RAW
CANAL_MAP = {
    "Mercado Libre Chile": "Mercado Libre", "Falabella Chile": "Falabella",
    "Mercado Ripley Chile": "Mercado Ripley", "Walmart Chile": "Walmart",
    "Paris": "Paris", "Shopify": "UnionX",
}
# partner (B2B/corporativo sin channel) -> canal del RAW. Substring, minúsculas.
# Resto de B2B se dejan con el nombre del partner (convención del RAW).
PARTNER_CANAL = {"casa mila": "UnionX B2B", "celmedia": "Celmedia"}


def _pw():
    pw = os.environ.get("ANDRES_ODOO_PASSWORD")
    if not pw:
        for envp in [".env", "eerr-finanzas/.env"]:
            p = ROOT / envp
            if p.exists():
                for ln in p.read_text().splitlines():
                    if ln.startswith("ANDRES_ODOO_PASSWORD"):
                        pw = ln.split("=", 1)[1].strip().strip('"').strip("'")
    return pw


def _odoo():
    url = "https://unionxb2b.odoo.com"; db = "bmya-innovatek-sh-prd-6981800"
    pw = _pw()
    uid = xmlrpc.client.ServerProxy(url + "/xmlrpc/2/common").authenticate(db, "andres@grupoeter.cl", pw, {})
    return xmlrpc.client.ServerProxy(url + "/xmlrpc/2/object"), db, uid, pw


def cargar_crossover(h):
    M, db, uid, pw = _odoo()
    dom = [["state", "=", "posted"], ["move_type", "=", "out_invoice"],
           ["invoice_date", ">=", "2026-06-01"], ["invoice_date", "<=", "2026-06-30"]]
    ids = M.execute_kw(db, uid, pw, "account.move", "search", [dom])
    inv = {}
    for i in range(0, len(ids), 2000):
        for d in M.execute_kw(db, uid, pw, "account.move", "read", [ids[i:i+2000]],
                              {"fields": ["name", "invoice_origin", "invoice_date", "amount_untaxed"]}):
            inv[d["id"]] = d
    raw_docs = set(h["documento"].dropna().astype(str).map(norm).unique())
    # crossover: doc ausente del RAW + SO Sxxxx con date_order>=julio
    cand = {mid: d for mid, d in inv.items()
            if norm(d["name"]) not in raw_docs and re.fullmatch(r"S\d{5,}", str(d.get("invoice_origin") or "").strip())}
    sos = list({d["invoice_origin"].strip() for d in cand.values()})
    so = {}
    for i in range(0, len(sos), 300):
        for r in M.execute_kw(db, uid, pw, "sale.order", "search_read", [[["name", "in", sos[i:i+300]]]],
                              {"fields": ["name", "date_order", "channel", "partner_id", "state"]}):
            so[r["name"]] = r
    cross = {mid: d for mid, d in cand.items()
             if str(so.get(d["invoice_origin"].strip(), {}).get("date_order", ""))[:7] >= "2026-07"}
    # líneas de esas facturas
    move_ids = list(cross.keys())
    lines = []
    for i in range(0, len(move_ids), 200):
        lines += M.execute_kw(db, uid, pw, "account.move.line", "search_read",
                              [[["move_id", "in", move_ids[i:i+200]], ["display_type", "in", [False, "product"]],
                                ["product_id", "!=", False]]],
                              {"fields": ["move_id", "product_id", "quantity", "price_subtotal", "price_total"]})
    # costo por SKU = standard_price live
    pids = list({l["product_id"][0] for l in lines if l.get("product_id")})
    std = {}
    for i in range(0, len(pids), 300):
        for r in M.execute_kw(db, uid, pw, "product.product", "read", [pids[i:i+300]],
                              {"fields": ["default_code", "standard_price"]}):
            std[r["id"]] = (str(r.get("default_code") or "").strip(), float(r.get("standard_price") or 0))
    rows = []
    for l in lines:
        mid = l["move_id"][0]; d = cross[mid]
        soc = so.get(d["invoice_origin"].strip(), {})
        ch = soc.get("channel"); ch = ch[1] if isinstance(ch, (list, tuple)) else ch
        # canal: marketplace desde channel; si viene vacío (B2B/corporativo directo),
        # usar el nombre del partner (así aparece como en el RAW: Casa Mila, Celmedia, etc.)
        part = soc.get("partner_id"); part = part[1] if isinstance(part, (list, tuple)) else ""
        if ch:
            canal = CANAL_MAP.get(ch, ch)
        else:
            pl = str(part).lower()
            canal = next((v for k, v in PARTNER_CANAL.items() if k in pl), part or "")
        sku, cu = std.get(l["product_id"][0], ("", 0.0))
        qty = float(l.get("quantity") or 0)
        rows.append({
            "documento": d["name"], "pedido": d["invoice_origin"].strip(),
            "canal": canal, "fecha_venta": d["invoice_date"], "fecha_documento": d["invoice_date"],
            "sku": sku, "producto": (l["product_id"][1] if l.get("product_id") else ""),
            "cantidad": qty, "venta_neta": float(l.get("price_subtotal") or 0), "venta_bruta": float(l.get("price_total") or 0),
            "costo_unitario": cu, "costo_total": cu * qty,
            "tipo_movimiento": "Venta", "estado_pedido": "", "bodega": "", "tipo_despacho": "",
            "hora_venta": "", "hora_venta_num": 0,
        })
    return pd.DataFrame(rows), {norm(d["name"]) for d in cross.values()}


def main(apply=False):
    h = pd.read_parquet(HIST)
    cat_cols = [c for c in h.columns if str(h[c].dtype) == "category"]
    for c in cat_cols:
        h[c] = h[c].astype(object)
    ov, docs = cargar_crossover(h)
    print(f"[crossover] {len(ov)} líneas de {ov['documento'].nunique()} boletas | "
          f"neto ${ov['venta_neta'].sum():,.0f}".replace(",", "."))
    # guard anti doble conteo: ninguno de esos documentos debe estar ya en el RAW
    ya = set(h["documento"].dropna().astype(str).map(norm)) & docs
    assert not ya, f"documentos ya en RAW: {ya}"

    # margen + enriquecimiento por Matriz (marca/categoria/proveedor/pack/estado_sku/es_despacho/tipo_compra)
    ov["margen_front"] = ov["venta_neta"] - ov["costo_total"]
    ov["margen_final"] = ov["margen_front"]
    for c in ["marca", "producto", "categoria_macro", "categoria_padre", "categoria_hijo",
              "categoria_comercial", "estado_sku", "pack", "proveedor"]:
        ov[c] = ov.get(c, "")
    try:
        from mejoras_raw_overlay import aplicar_mejoras
        ov = aplicar_mejoras(ov, con_nc_backfill=False, verbose=False)
    except Exception as e:
        print(f"[WARN] mejoras no aplicadas: {e}")
    try:
        from clasificar_marca import clasificar_tipo_marca
        ov["tipo_marca"] = ov["marca"].apply(clasificar_tipo_marca)
    except Exception:
        pass

    # atributos de canal (tipo_negocio/kam/estado_canal) heredados del histórico por canal (moda)
    def moda_por_canal(col):
        m = {}
        for canal, g in h.groupby(h["canal"].astype(str)):
            s = g[col].astype(str)
            s = s[s.str.strip() != ""]
            if len(s):
                m[canal] = s.mode().iat[0]
        return m
    for col in ["tipo_negocio", "kam", "estado_canal"]:
        mp = moda_por_canal(col)
        ov[col] = ov["canal"].astype(str).map(mp).fillna("")

    # alinear al esquema del histórico + recomputar fechas
    for c in h.columns:
        if c not in ov.columns:
            ov[c] = False if c == "es_despacho" else (0 if pd.api.types.is_numeric_dtype(h[c].dtype) else "")
    ov = ov[h.columns.tolist()]
    fv = pd.to_datetime(ov["fecha_venta"], errors="coerce")
    ov["fecha_venta"] = fv.dt.strftime("%Y-%m-%d")
    ov["anio_venta"] = fv.dt.year.fillna(0).astype("int64")
    ov["mes_venta"] = fv.dt.month.fillna(0).astype("int64")
    ov["semana_venta"] = fv.dt.isocalendar().week.fillna(0).astype("int64")
    DIAS = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
    ov["dia_semana"] = fv.dt.weekday.map(DIAS).fillna("")
    for c in h.columns:
        if pd.api.types.is_numeric_dtype(h[c].dtype):
            ov[c] = pd.to_numeric(ov[c], errors="coerce").fillna(0).astype(h[c].dtype)
        elif h[c].dtype == bool:
            ov[c] = ov[c].astype(bool)
        else:
            ov[c] = ov[c].astype(str).replace("nan", "")

    print("\n[dry-run] por canal (neto):")
    for canal, g in ov.groupby("canal"):
        print(f"   {canal:16} {g['documento'].nunique():3} boletas | neto ${g['venta_neta'].sum():,.0f} | margen ${g['margen_front'].sum():,.0f}".replace(",", "."))
    print(f"   TOTAL: {ov['documento'].nunique()} boletas | neto ${ov['venta_neta'].sum():,.0f}".replace(",", "."))
    print(f"[hist] {len(h):,} -> {len(h)+len(ov):,} filas")

    if not apply:
        print("\n[DRY-RUN] no se escribió nada.")
        return
    shutil.copy2(str(HIST), str(HIST) + ".bak_crossover")
    h_new = pd.concat([h, ov], ignore_index=True)
    for c in cat_cols:
        h_new[c] = h_new[c].astype("category")
    h_new.to_parquet(HIST, index=False, compression="zstd")
    print(f"\n[OK] aplicado. Backup .bak_crossover ({len(h_new):,} filas)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    main(**vars(ap.parse_args()))
