# -*- coding: utf-8 -*-
"""Webhook de stock masivo hacia Yuju (módulo madkting).

Reenvía el stock de Odoo a Yuju para un conjunto de productos, llamando el mismo
método que el botón "Webhook Stock" de la ficha (product.product.send_webhook_action).

REGLA DE ORO: antes de tocar el lote completo, dispara UN canario y exige que aparezca
un yuju.webhook.record nuevo en estado 'done'. Si el envío unitario no funciona
(como el 22-09-2026 tras el rebuild), aborta: un masivo sobre un botón muerto es ruido.

Universos (elegir uno):
  --movidos       productos Yuju con stock.move done desde el corte (default; ids en
                  data/outputs/yuju_resync_ids.json, o recalcula con --desde)
  --pendientes    productos con webhook_pending=True (los que el cron no drenó)
  --todos         todos los activos con id_product_madkting
  --ids 1,2,3     lista explícita

Modo:
  (sin flag)      DRY-RUN: muestra universo, canario y plan, no envía nada
  --ejecutar      envía de verdad
  --lote N        ids por llamada RPC (default 1 = uno por uno, el más seguro)
  --pausa S       segundos entre llamadas (default 0.3)
  --desde 'YYYY-MM-DD HH:MM:SS'  corte UTC para --movidos (default 2026-09-17 18:22:00)

Salida: data/outputs/yuju_resync_<fecha>.json con el resultado por producto.
"""
import sys, json, os, time, argparse, datetime
from pathlib import Path
import requests

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent
cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
pw = os.environ.get("ANDRES_ODOO_PASSWORD", "") or (ROOT / "odoo/.odoo_pass").read_text().strip()
URL = cfg["url"] + "/jsonrpc"


def jrpc_raw(service, method, args):
    for i in range(3):
        try:
            r = requests.post(URL, json={"jsonrpc": "2.0", "method": "call",
                                         "params": {"service": service, "method": method, "args": args}, "id": 1},
                              timeout=300)
            return r.json()
        except Exception:
            time.sleep(3)
    return {"error": {"message": "sin respuesta del servidor"}}


def jrpc(service, method, args):
    j = jrpc_raw(service, method, args)
    if "error" in j:
        raise RuntimeError(json.dumps(j["error"], ensure_ascii=False)[:400])
    return j["result"]


uid = jrpc("common", "login", [cfg["db_name"], cfg["username"], pw])


def ex(model, method, *args, **kw):
    return jrpc("object", "execute_kw", [cfg["db_name"], uid, pw, model, method, list(args), kw])


def ex_raw(model, method, *args, **kw):
    return jrpc_raw("object", "execute_kw", [cfg["db_name"], uid, pw, model, method, list(args), kw])


def n_records():
    return ex("yuju.webhook.record", "search_count", [])


def ultimo_record():
    r = ex("yuju.webhook.record", "search_read", [], fields=["create_date", "state", "message", "total_products", "data"],
           order="create_date desc", limit=1)
    return r[0] if r else None


def config_yuju():
    return ex("madkting.config", "search_read", [],
              fields=["webhook_stock_enabled", "stock_source_multi", "simple_stock_locations",
                      "webhook_stock_cron_enabled", "webhook_auto_send_enabled", "webhook_product_batchsize",
                      "webhook_product_limit", "write_date", "write_uid"])[0]


def universo(args):
    base = [("active", "=", True), ("id_product_madkting", "!=", False)]
    if args.ids:
        return [int(x) for x in args.ids.split(",") if x.strip()]
    if args.todos:
        return ex("product.product", "search", base)
    if args.pendientes:
        return ex("product.product", "search", base + [("webhook_pending", "=", True)])
    # --movidos (default)
    cache = ROOT / "data/outputs/yuju_resync_ids.json"
    if cache.exists() and not args.desde_explicito:
        return json.load(open(cache))
    g = ex("stock.move", "read_group",
           [("state", "=", "done"), ("date", ">=", args.desde),
            ("product_id.id_product_madkting", "!=", False), ("product_id.active", "=", True)],
           ["product_id"], ["product_id"], lazy=False)
    ids = sorted({r["product_id"][0] for r in g if r["product_id"]})
    json.dump(ids, open(cache, "w"))
    return ids


def disparar(ids):
    """Llama send_webhook_action para una lista de ids. Devuelve (ok, detalle)."""
    j = ex_raw("product.product", "send_webhook_action", ids)
    if "error" in j:
        d = j["error"].get("data", {})
        return False, f"{d.get('name', '')}: {str(d.get('message', j['error'].get('message', '')))[:160]}"
    r = j.get("result")
    if isinstance(r, dict):
        if r.get("has_errors") or r.get("errors"):
            return False, f"errors={r.get('errors')}"
        return True, "success" if r.get("success") else str(r)[:120]
    return True, str(r)[:120]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ejecutar", action="store_true")
    ap.add_argument("--movidos", action="store_true")
    ap.add_argument("--pendientes", action="store_true")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--ids", default="")
    ap.add_argument("--lote", type=int, default=1)
    ap.add_argument("--pausa", type=float, default=0.3)
    ap.add_argument("--desde", default="2026-09-17 18:22:00")
    ap.add_argument("--canario", type=int, default=21887, help="id de producto para la prueba previa")
    ap.add_argument("--sin-canario", action="store_true", help="saltar la prueba previa (NO recomendado)")
    args = ap.parse_args()
    args.desde_explicito = "--desde" in sys.argv

    print("=" * 78)
    print("WEBHOOK STOCK MASIVO → YUJU   " + ("*** EJECUTAR ***" if args.ejecutar else "(dry-run)"))
    print("=" * 78)

    c = config_yuju()
    print("Config madkting:")
    for k, v in c.items():
        if k != "id":
            print(f"   {k:<38} = {v}")
    if not c["webhook_stock_enabled"]:
        print("\n>>> webhook_stock_enabled=False: el módulo no va a enviar nada. ABORTO.")
        sys.exit(2)

    ids = universo(args)
    modo = "ids" if args.ids else "todos" if args.todos else "pendientes" if args.pendientes else "movidos"
    print(f"\nUniverso ({modo}): {len(ids)} productos")
    if not ids:
        print("Nada que enviar."); sys.exit(0)

    lotes = [ids[i:i + args.lote] for i in range(0, len(ids), args.lote)]
    est = len(lotes) * (0.7 + args.pausa)
    print(f"Plan: {len(lotes)} llamadas de {args.lote} id(s) · pausa {args.pausa}s · ~{est / 60:.1f} min")
    print(f"Verificación: cada llamada debe crear ≥1 yuju.webhook.record en estado 'done'")

    if not args.ejecutar:
        print("\nDRY-RUN. Nada enviado. Para ejecutar: --ejecutar (siempre pasa por el canario primero).")
        sys.exit(0)

    # ---------- CANARIO ----------
    if not args.sin_canario:
        print(f"\n--- CANARIO: producto {args.canario} ---")
        n0 = n_records()
        ok, det = disparar([args.canario])
        time.sleep(3)
        n1 = n_records()
        print(f"   retorno: {det}   ·   yuju.webhook.record {n0} → {n1}")
        if not ok or n1 <= n0:
            print("\n>>> EL ENVÍO UNITARIO NO FUNCIONA: el método responde pero no crea registro de webhook.")
            print(">>> Un masivo ahora sería inútil. ABORTO. Resolver primero con Yuju / revisar el código del módulo.")
            sys.exit(3)
        u = ultimo_record()
        print(f"   registro: {u['create_date']} state={u['state']} total={u['total_products']} msg={str(u['message'])[:60]}")
        print(f"   payload : {str(u['data'])[:200]}")
        if u["state"] != "done":
            print(f"\n>>> El canario quedó en estado '{u['state']}', no 'done'. ABORTO.")
            sys.exit(3)
        print("   CANARIO OK.")

    # ---------- LOTE ----------
    print(f"\n--- ENVÍO: {len(lotes)} llamadas ---")
    res = []
    n_ini = n_records()
    t0 = time.time()
    fallos = 0
    for i, lote in enumerate(lotes, 1):
        ok, det = disparar(lote)
        res.append({"ids": lote, "ok": ok, "detalle": det})
        if not ok:
            fallos += 1
        if i % 25 == 0 or i == len(lotes):
            n_now = n_records()
            print(f"   {i}/{len(lotes)}  registros creados hasta ahora: {n_now - n_ini}  fallos RPC: {fallos}  ({time.time() - t0:.0f}s)")
        if fallos >= 10 and fallos / i > 0.5:
            print("\n>>> Más de la mitad de las llamadas fallan. ABORTO para no seguir a ciegas.")
            break
        time.sleep(args.pausa)

    n_fin = n_records()
    creados = n_fin - n_ini
    print(f"\nRESULTADO: {len(res)} llamadas · {creados} yuju.webhook.record creados · {fallos} fallos RPC")
    # cuántos productos quedaron efectivamente cubiertos por registros 'done' posteriores al inicio
    hechos = ex("yuju.webhook.record", "search_read",
                [("create_date", ">=", (datetime.datetime.utcnow() - datetime.timedelta(seconds=time.time() - t0 + 30)).strftime("%Y-%m-%d %H:%M:%S"))],
                fields=["state", "total_products", "data"])
    cubiertos = set()
    for h in hechos:
        if h["state"] != "done":
            continue
        try:
            for item in json.loads(h["data"] or "[]"):
                cubiertos.add(item.get("product_id"))
        except Exception:
            pass
    faltan = [i for i in ids if i not in cubiertos]
    print(f"Productos con webhook 'done' verificado: {len(cubiertos & set(ids))}/{len(ids)}   ·   sin registro: {len(faltan)}")
    out = ROOT / f"data/outputs/yuju_resync_{datetime.date.today():%Y%m%d}.json"
    json.dump({"config": c, "universo": modo, "ids": ids, "llamadas": res, "registros_creados": creados,
               "cubiertos": sorted(cubiertos & set(ids)), "sin_registro": faltan},
              open(out, "w"), indent=1, default=str)
    print(f"Detalle: {out.relative_to(ROOT)}")
    if faltan:
        print(f"Primeros sin registro: {faltan[:15]}")


if __name__ == "__main__":
    main()
