# -*- coding: utf-8 -*-
"""
Reconstruye El Volcán H1 2026 (ene-jun) al histórico desde la fuente canónica
'Base Trini 2026' del libro Seguimiento contribución (que YA tiene la Venta neta
cuadrada con Trinidad). Reemplaza el load previo (overlay manuales) que quedó
DOBLADO en enero ($8,02M vs $4,02M canónico) y con desvíos en feb/abr.

Modelo El Volcán (consignación, retiene 30%): igual que reintegrar_ev_junio_2026.py
    venta_neta   = 'Venta neta' de Base Trini (ya = (Costo Total−NC)/0,70)
    venta_bruta  = venta_neta × 1,19
    comision     = venta_neta × 0,30
    costo_unit   = standard_price de Odoo (por SKU); costo_total = ×unidades
    margen_front = venta_neta − costo_total ; margen_final = margen_front − comision

Reemplaza SOLO canal='El Volcan' de 2026 (deja 2025 intacto). Uso: [--apply]
"""
import argparse, os, shutil, sys, xmlrpc.client
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
HIST = ROOT / "data" / "historico" / "ventas_historico.parquet"
SHEET_SEG = "1d7iN4M-AoNZvBEXxvGWYK5pJoXAI6VxzJIdjh12QNjM"
COMISION_PCT, IVA = 30.0, 1.19
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
ODOO = dict(url="https://unionxb2b.odoo.com", db="bmya-innovatek-sh-prd-6981800", user="andres@grupoeter.cl")


def _load_env():
    for p in (".env", "eerr-finanzas/.env"):
        f = ROOT / p
        if f.exists():
            for ln in f.read_text(encoding="utf-8").splitlines():
                if "=" in ln and not ln.strip().startswith("#"):
                    k, v = ln.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _num(x):
    s = str(x).replace(".", "").replace(",", ".").replace("$", "").strip()
    try:
        return float(s) if s not in ("", "-", "nan", "None") else 0.0
    except ValueError:
        return 0.0


def costos_odoo(skus):
    _load_env()
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD")
    if not pwd:
        sys.exit("[ERROR] falta ANDRES_ODOO_PASSWORD")
    uid = xmlrpc.client.ServerProxy(f"{ODOO['url']}/xmlrpc/2/common").authenticate(ODOO["db"], ODOO["user"], pwd, {})
    models = xmlrpc.client.ServerProxy(f"{ODOO['url']}/xmlrpc/2/object")
    recs = models.execute_kw(ODOO["db"], uid, pwd, "product.product", "search_read",
        [["|", ["default_code", "in", skus], ["barcode", "in", skus]]],
        {"fields": ["default_code", "barcode", "standard_price"]})
    out = {}
    for r in recs:
        for key in (r.get("default_code"), r.get("barcode")):
            if key and str(key) in skus and str(key) not in out:
                out[str(key)] = r["standard_price"]
    return out


def leer_base_trini():
    """Líneas El Volcán H1 desde 'Base Trini 2026'. Cols: Canal0, Comisión2, Mes4,
    Fecha5, Venta neta6, SKU8, Producto9, Costo productos11, Unidades12."""
    import gspread
    gc = gspread.service_account(filename=str(ROOT / "credentials.json"))
    vals = gc.open_by_key(SHEET_SEG).worksheet("Base Trini 2026").get_all_values()
    filas = []
    for r in vals[1:]:
        if len(r) < 13:
            continue
        canal = str(r[0]).strip().lower()
        if "volcan" not in canal.replace("á", "a"):
            continue
        mes = str(r[4]).strip()
        if not mes.isdigit() or not (1 <= int(mes) <= 6):
            continue
        fecha = pd.to_datetime(str(r[5]).replace("_", "-"), dayfirst=True, errors="coerce")
        if pd.isna(fecha):
            fecha = pd.to_datetime(str(r[5]), errors="coerce")
        sku = str(r[8]).strip()
        if not sku or pd.isna(fecha):
            continue
        filas.append(dict(sku=sku, fecha=fecha, mes=int(mes),
                          producto=r[9], neta=_num(r[6]), unidades=_num(r[12])))
    return filas


def main(apply=False):
    df = pd.read_parquet(HIST)
    fv = pd.to_datetime(df["fecha_venta"], errors="coerce")
    es_ev = df["canal"].astype(str).str.strip().str.lower().str.replace("á", "a").eq("el volcan")
    mask = es_ev & (fv.dt.year == 2026) & (fv.dt.month.between(1, 6))
    ev = df[mask]
    print("ANTES El Volcán H1 2026 por mes:")
    for m in range(1, 7):
        e = ev[fv[mask.index].loc[ev.index].dt.month == m] if len(ev) else ev
        e = ev[pd.to_datetime(ev["fecha_venta"]).dt.month == m]
        print(f"  mes {m}: {len(e)}f · neta ${e['venta_neta'].sum():,.0f}")

    detalle = leer_base_trini()
    print(f"\nBase Trini El Volcán H1: {len(detalle)} líneas")

    attr_cols = ["producto", "categoria_macro", "categoria_padre", "categoria_hijo",
                 "categoria_comercial", "estado_sku", "pack", "marca", "proveedor",
                 "tipo_marca", "hora_venta", "hora_venta_num"]
    attrs = {}
    for _, r in ev.iterrows():
        attrs.setdefault(str(r["sku"]), {c: r[c] for c in attr_cols if c in ev.columns})

    plantilla = {c: "" for c in df.columns}
    plantilla.update(dict(
        tipo_movimiento="Venta", bodega="Bodega El Volcán", documento="",
        fecha_documento="", pedido="", estado_pedido="Ok", tipo_despacho="Seller",
        canal="El Volcan", proveedor="UnionX", tipo_compra="Importación",
        tipo_negocio="Marketplace", kam="Trini", estado_canal="In",
        tipo_marca="Propia", es_despacho=False, pedido_marketplace="", yuju_pack_id=""))

    skus = list({d["sku"] for d in detalle})
    costos = costos_odoo(skus)
    faltan = [s for s in skus if s not in costos]
    if faltan:
        print(f"[WARN] {len(faltan)} SKUs sin costo Odoo: {faltan[:5]}")

    filas = []
    for d in detalle:
        neta = d["neta"]; bruta = neta * IVA; com = neta * COMISION_PCT / 100.0
        cu = float(costos.get(d["sku"], 0.0)); ct = cu * d["unidades"]
        f = dict(plantilla); f.update(attrs.get(d["sku"], {}))
        if not f.get("producto"):
            f["producto"] = d["producto"]
        f.update(dict(sku=d["sku"], fecha_venta=d["fecha"].strftime("%Y-%m-%d"),
            anio_venta=2026, mes_venta=d["mes"], semana_venta=int(d["fecha"].isocalendar().week),
            dia_semana=DIAS[d["fecha"].weekday()], cantidad=d["unidades"],
            venta_bruta=bruta, venta_neta=neta, costo_unitario=cu, costo_total=ct,
            comision_pct=COMISION_PCT, comision=com, logistica=0.0, marketing=0.0,
            margen_front=neta - ct, margen_final=(neta - ct) - com))
        filas.append(f)
    nuevas = pd.DataFrame(filas)[df.columns]

    print("\nDESPUÉS (nuevo El Volcán H1) por mes:")
    for m in range(1, 7):
        e = nuevas[nuevas["mes_venta"] == m]
        print(f"  mes {m}: {len(e)}f · neta ${e['venta_neta'].sum():,.0f}")
    print(f"\nTOTAL nuevo: {len(nuevas)}f · neta ${nuevas['venta_neta'].sum():,.0f} · "
          f"comisión ${nuevas['comision'].sum():,.0f} · costo ${nuevas['costo_total'].sum():,.0f}")

    df_out = pd.concat([df[~mask], nuevas], ignore_index=True)
    print(f"Histórico: {len(df)} → {len(df_out)} filas (−{int(mask.sum())} +{len(nuevas)})")

    if apply:
        bak = HIST.with_suffix(".parquet.bak_evh1")
        if not bak.exists():
            shutil.copy2(HIST, bak); print(f"backup: {bak.name}")
        df_out.to_parquet(HIST, index=False)
        print("✓ APLICADO")
    else:
        print("→ dry-run (usa --apply)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    main(apply=ap.parse_args().apply)
