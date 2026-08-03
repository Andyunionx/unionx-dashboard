# -*- coding: utf-8 -*-
"""Tránsito vivo — unidades en tránsito por SKU con ETA real.

Cruza:
  1. Seimex API (fuente única de embarques desde jul-2026): operaciones sin
     recepción confirmada, con ETA — el estado/fecha VIVO de cada PI.
  2. Odoo: líneas de OC de esos PIs (partner_ref, saneados en auditoría jul-26)
     con cantidad pendiente de recibir (product_qty - qty_received).

Reemplaza la fuente muerta del snapshot de planificación:
  - extract_forecast_transito.py leía "Transito AGO26..." del Excel
    FORECAST FINAL SKU 26-27 V2.xlsx (congelado 18-may-2026).
  - Los pickings de entrada de Odoo NO proyectan (solo basura 2024-25: las
    recepciones se crean al arribo, no al embarque).

Output:
  data/planificacion/snapshots/transito_vivo.parquet  (sku, unidades, eta, pi, oc)
  data/planificacion/snapshots/planif_forecast_transito.parquet  (sku, mes,
    unidades, ts_actualizado) — mismo esquema que consume la app de
    planificación (triada_cobertura / analisis_planificacion), ahora VIVO.

Uso: python transito_vivo.py [--dry-run]
"""
import sys, os, re, json, argparse, datetime
from pathlib import Path
import xmlrpc.client
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
SNAP = ROOT / "data/planificacion/snapshots"
HORIZONTE_ATRAS_DIAS = 10   # ETA vencida hace poco = probablemente descargando, se mantiene


def _cargar_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def operaciones_vivas() -> pd.DataFrame:
    """Seimex: operaciones sin recepción confirmada con ETA vigente."""
    sys.path.insert(0, str(ROOT))
    from seimex_api import SeimexAPI
    api = SeimexAPI()
    corte = (datetime.date.today() - datetime.timedelta(days=HORIZONTE_ATRAS_DIAS)).isoformat()
    filas = []
    for o in api.get_operations():
        r = SeimexAPI.resumen_operacion(o)
        eta = str(r.get("eta") or "")[:10]
        if not eta or r.get("reception_confirmed") or eta < corte:
            continue
        # codigo PI/DS + año de la referencia: "256-26 PI0528" -> ('PI','0528','26')
        txt = str(r.get("reference") or "") + " " + str(r.get("product") or "")
        m = re.search(r"(PI|DS)\s*-?\s*(\d{3,4})", txt, re.I)
        if not m:
            continue
        my = re.search(r"-\s*(\d{2})\b", str(r.get("reference") or ""))
        filas.append({"tipo": m.group(1).upper(), "code": m.group(2).zfill(4),
                      "anio": my.group(1) if my else "26", "eta": eta,
                      "stage": r.get("stage"), "ref_seimex": r.get("reference"),
                      "zarpe_conf": bool(r.get("departure_confirmed"))})
    df = pd.DataFrame(filas).drop_duplicates(subset=["tipo", "code"], keep="first")
    print(f"[seimex] {len(df)} embarques vivos con ETA:")
    for r in df.sort_values("eta").itertuples(index=False):
        print(f"   {r.tipo}{r.code}  ETA {r.eta}  {r.stage}")
    return df


def pendientes_odoo(ops: pd.DataFrame) -> pd.DataFrame:
    """Líneas de OC de esos PIs con cantidad pendiente de recibir."""
    cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
    pw = os.environ.get("ANDRES_ODOO_PASSWORD", "") or (ROOT / "odoo/.odoo_pass").read_text().strip()
    uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(
        cfg["db_name"], cfg["username"], pw, {})

    def rpc(model, method, args, kw=None):
        return xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object").execute_kw(
            cfg["db_name"], uid, pw, model, method, args, kw or {})

    # incluye BORRADORES: las OC de embarques nuevos suelen confirmarse tarde
    # (P00701/702/703 draft al 29-jul) — se marcan con flag para visibilidad.
    po = rpc("purchase.order", "search_read",
             [[("state", "in", ["draft", "sent", "purchase", "done"]), ("partner_ref", "!=", False)]],
             {"fields": ["id", "name", "partner_ref", "state"]})
    key = {}
    for p in po:
        s = str(p["partner_ref"]).upper()
        m2 = re.search(r"(\d{2})(TP|DS)0*(\d{3,4})", s)
        if m2:
            key.setdefault((m2.group(1), m2.group(3).zfill(4)), []).append(p)

    filas, sin_oc = [], []
    for op in ops.itertuples(index=False):
        matches = key.get((op.anio, op.code), [])
        if not matches:
            sin_oc.append(op)
            continue
        for p in matches:
            lines = rpc("purchase.order.line", "search_read", [[("order_id", "=", p["id"])]],
                        {"fields": ["product_id", "product_qty", "qty_received"]})
            pids = [l["product_id"][0] for l in lines if l["product_id"]]
            codes = {x["id"]: str(x["default_code"] or "").strip()
                     for x in rpc("product.product", "read", [pids], {"fields": ["default_code"]})} if pids else {}
            for l in lines:
                pend = l["product_qty"] - l["qty_received"]
                if pend <= 0.01 or not l["product_id"]:
                    continue
                sku = codes.get(l["product_id"][0], "")
                if not sku:
                    continue
                filas.append({"sku": sku, "unidades": pend, "eta": op.eta,
                              "pi": f"{op.tipo}{op.code}-{op.anio}", "oc": p["name"],
                              "oc_estado": p["state"], "stage": op.stage})
    if sin_oc:
        print(f"\n[GAP] {len(sin_oc)} embarques vivos SIN OC en Odoo (no proyectables por SKU):")
        for op in sin_oc:
            print(f"   {op.tipo}{op.code}-{op.anio}  ETA {op.eta}  {op.stage}  (Seimex {op.ref_seimex})")
    # persistir gaps para el mail del pulso
    gaps = [{"pi": f"{op.tipo}{op.code}-{op.anio}", "eta": op.eta, "stage": op.stage,
             "ref_seimex": op.ref_seimex} for op in sin_oc]
    SNAP.mkdir(parents=True, exist_ok=True)
    with open(SNAP / "transito_gaps.json", "w", encoding="utf-8") as f:
        json.dump(gaps, f, ensure_ascii=False)
    return pd.DataFrame(filas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    _cargar_env()
    ops = operaciones_vivas()
    det = pendientes_odoo(ops)
    if det.empty:
        print("[WARN] sin líneas pendientes para los embarques vivos")
        return 1
    det = det.groupby(["sku", "eta", "pi", "oc", "oc_estado", "stage"], as_index=False)["unidades"].sum()
    print(f"\n[transito] {len(det)} líneas | {det['unidades'].sum():,.0f} uds | {det['sku'].nunique()} SKUs")
    print(det.groupby("pi").agg(uds=("unidades", "sum"), eta=("eta", "first")).sort_values("eta").to_string())

    if a.dry_run:
        print("\n(dry-run: no se escribe nada)")
        return 0
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    det["ts_actualizado"] = ts
    SNAP.mkdir(parents=True, exist_ok=True)
    det.to_parquet(SNAP / "transito_vivo.parquet", index=False)
    # mismo esquema que consume la app de planificación
    mensual = det.assign(mes=det["eta"].str[:7]).groupby(["sku", "mes"], as_index=False)["unidades"].sum()
    mensual["ts_actualizado"] = ts
    mensual.to_parquet(SNAP / "planif_forecast_transito.parquet", index=False)
    print(f"\nOK guardados transito_vivo.parquet + planif_forecast_transito.parquet ({ts})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
