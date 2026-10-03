# -*- coding: utf-8 -*-
"""Vigía Cyber — revisa Odoo, Yuju y Shopify cada 5 minutos durante el Cyber oct-2026.

Por qué existe:
  · Cyber jun-26, jue 4-jun 14:47 → 23:45 CLT: no entró NINGÚN pedido de Yuju a Odoo durante
    9 horas, con Odoo arriba. Los pedidos pagados en esa ventana entraron tarde: parte a las
    23:45 y el resto recién el 5-jun a las 15:32. Nadie lo vio a tiempo.
  · 17→22-sep-26: una reconstrucción de Odoo.sh dejó apagado el envío de stock a Yuju 5 días.
  Este vigía acusa ese tipo de falla en 10-15 minutos.

Chequeos (solo lectura, ~20 consultas livianas por ciclo):
  1. Odoo responde: página de ingreso + una lectura mínima por RPC (latencia).
  2. Crons críticos apagados, atrasados (> 2× su intervalo, mín 10 min) o con fallas; crons en
     general atrasados > 15 min (los procesos de cron no dan abasto); corridas de > 15 min.
  3. Pedidos Yuju por marketplace: silencio más largo que lo tolerado (calibrado con jun-26).
  4. Shopify Directo: eventos sin procesar, con error, rescatados por reconciliación, silencio.
  5. Pedidos trabados: Yuju sin confirmar o confirmados sin despacho; despachos en borrador.
  6. Stock a marketplaces (Yuju): flag, bodega, endpoint, webhooks vs movimientos; módulos
     de Odoo actualizados (posible despliegue en Odoo.sh).
  7. DTE: documentos sin enviar al SII (antigüedad) y rechazos.
  8. Correo saliente: cola atrasada y fallas.

Avisos por correo (Gmail API): problema nuevo → aviso inmediato; sigue abierto → recordatorio
(crítico cada 30 min, advertencia cada 2 h); se resolvió → aviso; resumen 08:30 y 20:30 CLT (si
no llega, el vigía está caído). El repo es público: en GitHub Actions el log NO muestra cifras.

Uso:
  python watchdog_cyber_odoo.py --una-vez             # un ciclo, muestra todo en pantalla, no envía
  python watchdog_cyber_odoo.py --una-vez --enviar    # idem y manda el resumen por correo
  python watchdog_cyber_odoo.py --prueba              # un ciclo + correo de prueba (verifica secretos)
  python watchdog_cyber_odoo.py                       # turno de ~5 h 30 (GitHub Actions); se releva solo
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent
UTC = timezone.utc
CLT = timezone(timedelta(hours=-3))          # Chile, horario de verano (desde el 6-sep-2026)

VIGIA_DESDE = datetime(2026, 10, 3, 23, 0, tzinfo=UTC)   # sáb 3-oct 20:00 CLT (pre-Cyber: línea base)
VIGIA_HASTA = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # mar 13-oct 12:00 CLT (cola de despachos)
DIAS_PICO = {"2026-10-05", "2026-10-06", "2026-10-07"}   # días 1-3 del evento
DIAS_COLA = {"2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11"}
CICLO = timedelta(minutes=5)
TURNO = timedelta(hours=5, minutes=30)
RESUMEN_HORAS = (8, 20)                      # resumen a las 08:30 y 20:30 CLT
EN_ACTIONS = bool(os.environ.get("GITHUB_ACTIONS"))
DESTINO = os.environ.get("WATCHDOG_EMAIL_TO") or "andres@unionx.cl"

CRIT, ADV = "CRÍTICO", "ADVERTENCIA"
MIN = {"minutes": 1, "hours": 60, "days": 1440, "weeks": 10080, "months": 43200}

# Crons que sostienen la venta y el despacho: id → (qué hace, nivel si se cae)
CRONS = {
    115: ("Yuju: stock a marketplaces", CRIT),
    116: ("Yuju: precios a marketplaces", ADV),
    148: ("Shopify: cola de pedidos", CRIT),
    149: ("Shopify: reconciliar pedidos perdidos", ADV),
    150: ("Shopify: envío de stock", CRIT),
    151: ("Shopify: barrido de boletas", ADV),
    152: ("Shopify: centinela sin pedidos", ADV),
    153: ("Shopify: OS Blue Express", CRIT),
    158: ("Recíbelo: etiquetas RM", CRIT),
    160: ("Blue Express: etiquetas regiones", CRIT),
    26: ("DTE: envío al SII", CRIT),
    27: ("SII: consultas de estado", ADV),
    29: ("Reglas automáticas de Odoo", CRIT),
    2: ("Cola de correos salientes", ADV),
    5: ("Correo entrante (fetchmail)", ADV),
    157: ("Corrector 801", ADV),
    146: ("Corrector Factura 33", ADV),
}

# Yuju crea los pedidos con la credencial «Trinidad Alfaro» (ventas@melollevo.cl)
YUJU_UID = 211
YUJU_ID_SHOP = "1090300"
# Silencio tolerado (min) sin pedidos Yuju, por marketplace, en horario activo.
# Brecha máxima 08-24 h en el Cyber jun-26, días 1-3: total 14 min · ML 30 · Falabella 19 ·
# Paris 56 · Ripley 72 · Walmart 113. Días 4-7 (sin el incidente): total 22 · ML 28 · Falabella 95.
# Semana normal sep-26 (09-24 h): total 35 · ML 48.
SILENCIO = {
    "pico": {"(total)": (30, CRIT), "Mercado Libre Chile": (45, CRIT), "Falabella Chile": (45, CRIT),
             "Paris": (90, ADV), "Mercado Ripley Chile": (150, ADV), "Walmart Chile": (180, ADV)},
    "cola": {"(total)": (45, CRIT), "Mercado Libre Chile": (60, CRIT), "Falabella Chile": (120, ADV)},
    "normal": {"(total)": (75, ADV), "Mercado Libre Chile": (90, ADV)},
}
SILENCIO_NOCHE = {"pico": {"(total)": (90, ADV)}}        # 00-08 h en días de evento
SHOPIFY_SILENCIO_PICO = 120                              # min sin pedidos pagados en las 3 tiendas


# ─── utilidades ──────────────────────────────────────────────────────────────
def ahora_utc():
    return datetime.now(UTC)


def ts(t):
    return t.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def de_odoo(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC) if s else None


def minutos(desde, hasta):
    return (hasta - desde).total_seconds() / 60


def fmt_min(m):
    if m < 60:
        return f"{m:.0f} min"
    if m < 1440:
        return f"{int(m // 60)} h {int(m % 60):02d}"
    return f"{m / 1440:.1f} días".replace(".", ",")


def hora(t):
    return t.astimezone(CLT).strftime("%H:%M")


def fecha_hora(t):
    return t.astimezone(CLT).strftime("%d-%m %H:%M")


def fase(t):
    """(tipo de día, ¿horario activo?, inicio de la ventana de hoy) en hora de Chile."""
    d = t.astimezone(CLT)
    dia = d.strftime("%Y-%m-%d")
    tipo = "pico" if dia in DIAS_PICO else "cola" if dia in DIAS_COLA else "normal"
    if tipo == "normal":
        activo = 9 <= d.hour < 23
        inicio = d.replace(hour=9 if activo else 0, minute=0, second=0, microsecond=0)
    else:
        activo = d.hour >= 8
        inicio = d.replace(hour=8 if activo else 0, minute=0, second=0, microsecond=0)
    return tipo, activo, inicio


class H:
    """Hallazgo: clave estable (para seguirlo entre ciclos), nivel, título y detalle."""
    __slots__ = ("clave", "nivel", "titulo", "detalle", "confirmar", "recordar", "origen")

    def __init__(self, clave, nivel, titulo, detalle="", confirmar=1, recordar=True):
        self.clave, self.nivel, self.titulo, self.detalle = clave, nivel, titulo, detalle
        self.confirmar = confirmar      # ciclos seguidos antes de avisar (evita falsas alarmas por un tropiezo)
        self.recordar = recordar        # False = avisar una vez (cambios de configuración, despliegues)
        self.origen = None


# ─── Odoo ────────────────────────────────────────────────────────────────────
class Odoo:
    def __init__(self):
        cfg = json.load(open(ROOT / "odoo/odoo_config.json", encoding="utf-8"))["produccion"]
        self.url, self.db, self.user = cfg["url"], cfg["db_name"], cfg["username"]
        self.pw = os.environ.get("ANDRES_ODOO_PASSWORD", "")
        if not self.pw and (ROOT / "odoo/.odoo_pass").exists():
            self.pw = (ROOT / "odoo/.odoo_pass").read_text().strip()
        self.s = requests.Session()
        self.uid = None

    def _call(self, service, method, args, timeout=60):
        r = self.s.post(f"{self.url}/jsonrpc", timeout=timeout, json={
            "jsonrpc": "2.0", "method": "call", "id": 1,
            "params": {"service": service, "method": method, "args": args}})
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            raise RuntimeError((j["error"].get("data") or {}).get("message") or j["error"].get("message"))
        return j["result"]

    def login(self):
        self.uid = self._call("common", "login", [self.db, self.user, self.pw], timeout=45)
        if not self.uid:
            raise PermissionError("Odoo rechazó la clave del vigía")

    def ex(self, model, method, *args, timeout=60, **kw):
        if not self.uid:
            self.login()
        return self._call("object", "execute_kw",
                          [self.db, self.uid, self.pw, model, method, list(args), kw], timeout=timeout)


# ─── chequeos ────────────────────────────────────────────────────────────────
def chk_disponibilidad(od, ahora, met):
    out = []
    try:
        t = time.time()
        r = od.s.get(f"{od.url}/web/login", timeout=30)
        met["web_s"] = time.time() - t
        if r.status_code >= 500:
            out.append(H("odoo_web", CRIT, f"Odoo responde error {r.status_code}",
                         "La página de ingreso de Odoo devuelve error de servidor.", confirmar=2))
    except Exception as e:
        out.append(H("odoo_web", CRIT, "La página de Odoo no responde",
                     f"{type(e).__name__}: {str(e)[:150]}", confirmar=2))
    t = time.time()
    if not od.uid:
        od.login()
    od.ex("res.users", "read", [od.uid], fields=["id"], timeout=45)
    met["rpc_s"] = lat = time.time() - t
    if lat > 30:
        out.append(H("odoo_lento", CRIT, f"Odoo muy lento: {lat:.0f} s para una lectura mínima",
                     "Lo normal es ~1 s. Con esta lentitud los pedidos de Yuju y Shopify empiezan a fallar por "
                     "tiempo de espera. Avisar a Martín para revisar workers en Odoo.sh.", confirmar=2))
    elif lat > 10:
        out.append(H("odoo_lento", ADV, f"Odoo lento: {lat:.0f} s para una lectura mínima",
                     "Lo normal es ~1 s. Señal temprana de saturación de workers.", confirmar=2))
    return out


def chk_crons(od, ahora, met):
    out = []
    cs = od.ex("ir.cron", "read", list(CRONS),
               fields=["name", "active", "nextcall", "interval_number", "interval_type",
                       "failure_count", "first_failure_date"], context={"active_test": False})
    for cid in set(CRONS) - {c["id"] for c in cs}:
        out.append(H(f"cron{cid}", CRONS[cid][1], f"No existe el cron «{CRONS[cid][0]}»", f"id {cid}: ¿fue eliminado?"))
    for c in cs:
        desc, nivel = CRONS[c["id"]]
        if not c["active"]:
            out.append(H(f"cron{c['id']}", nivel, f"Cron apagado: {desc}", f"«{c['name']}» (id {c['id']}) está inactivo."))
            continue
        cada = c["interval_number"] * MIN.get(c["interval_type"], 1)
        atraso = minutos(de_odoo(c["nextcall"]), ahora)
        if atraso > max(2 * cada, 10):
            out.append(H(f"cron{c['id']}", nivel, f"Cron atrasado: {desc}",
                         f"Le tocaba a las {hora(de_odoo(c['nextcall']))} (hace {fmt_min(atraso)}) y corre cada "
                         f"{fmt_min(cada)}. Está trabado en una corrida larga o los procesos de cron no dan abasto."))
        if c["failure_count"]:
            desde = de_odoo(c["first_failure_date"])
            out.append(H(f"cron{c['id']}_falla", nivel if c["failure_count"] >= 3 else ADV, f"Cron con errores: {desc}",
                         f"{c['failure_count']} corridas seguidas con error"
                         + (f" desde el {fecha_hora(desde)}" if desde else "") + ". Odoo lo apaga solo si sigue fallando."))
    # crons en general: si varios se atrasan a la vez, los procesos de cron no dan abasto
    tarde = od.ex("ir.cron", "search_read", [("active", "=", True), ("nextcall", "<", ts(ahora - timedelta(minutes=15)))],
                  fields=["name", "nextcall"], limit=50)
    met["crons_atrasados"] = len(tarde)
    muy = [c for c in tarde if de_odoo(c["nextcall"]) < ahora - timedelta(minutes=45)]
    lista = "; ".join(f"{c['name'][:45]} (desde {hora(de_odoo(c['nextcall']))})" for c in tarde[:6])
    if len(muy) >= 3:
        out.append(H("crons_capacidad", CRIT, f"{len(muy)} crons atrasados más de 45 min",
                     f"Los procesos de cron no dan abasto: {lista}. Avisar a Martín."))
    elif len(tarde) >= 3:
        out.append(H("crons_capacidad", ADV, f"{len(tarde)} crons atrasados más de 15 min",
                     f"Primera señal de saturación de los procesos de cron: {lista}."))
    # carga de la última hora y corridas largas (bloquean registros y atrasan a los demás)
    prog = od.ex("ir.cron.progress", "search_read", [("create_date", ">=", ts(ahora - timedelta(minutes=60)))],
                 fields=["cron_id", "create_date", "write_date"], limit=5000)
    dur = [((de_odoo(p["write_date"]) - de_odoo(p["create_date"])).total_seconds(), p) for p in prog]
    met["cron_min_1h"] = sum(d for d, _ in dur) / 60
    largos = {}
    for d, p in dur:
        if d > 900 and p["cron_id"]:
            largos[p["cron_id"][0]] = max(largos.get(p["cron_id"][0], (0, ""))[0], d), p["cron_id"][1]
    for cid, (d, nombre) in largos.items():
        out.append(H(f"cron_largo{cid}", ADV, f"Corrida de cron de {fmt_min(d / 60)}: {nombre[:60]}",
                     "Lo normal es menos de 6 min. Una corrida así bloquea registros y atrasa al resto de los crons.",
                     recordar=False))
    return out


def chk_pedidos_yuju(od, ahora, met):
    tipo, activo, inicio = fase(ahora)
    reglas = SILENCIO[tipo] if activo else SILENCIO_NOCHE.get(tipo, {})
    g = od.ex("sale.order", "read_group",
              [("create_uid", "=", YUJU_UID), ("create_date", ">=", ts(ahora - timedelta(hours=4)))],
              ["create_date:max"], ["channel"], lazy=False)
    ult = {(x["channel"] or "?"): de_odoo(x["create_date"]) for x in g}
    if ult:
        ult["(total)"] = max(ult.values())
    h1 = od.ex("sale.order", "read_group",
               [("create_uid", "=", YUJU_UID), ("create_date", ">=", ts(ahora - timedelta(hours=1)))],
               ["id:count"], ["channel"], lazy=False)
    met["yuju_1h"] = {(x["channel"] or "?"): x["__count"] for x in h1}
    met["fase"] = f"{tipo} · {'horario activo' if activo else 'noche'}"
    out = []
    for canal, (umbral, nivel) in reglas.items():
        ref = max(t for t in (ult.get(canal), inicio) if t)     # no alarmar por la noche quieta
        sil = minutos(ref, ahora)
        if sil > umbral:
            nombre = "Yuju (ningún marketplace)" if canal == "(total)" else canal
            ultimo = (f"Último pedido a las {hora(ult[canal])}" if ult.get(canal)
                      else "Ningún pedido en las últimas 4 h")
            out.append(H(f"silencio:{canal}", nivel, f"Sin pedidos de {nombre} hace {fmt_min(sil)}",
                         f"{ultimo}. Tolerancia {umbral} min (día {tipo}). Si Odoo está arriba, el problema está "
                         f"en la sincronización de pedidos de Yuju o en el marketplace: revisar el panel de Yuju. "
                         f"En el Cyber de junio pasó esto 9 horas sin que nadie lo viera."))
    return out


def chk_shopify(od, ahora, met):
    out = []
    trab = od.ex("shopify.webhook.event", "search_read",
                 [("state", "=", "received"), ("create_date", "<", ts(ahora - timedelta(minutes=15)))],
                 fields=["shopify_order_name", "topic", "create_date", "store_id"], order="create_date asc", limit=20)
    if trab:
        x = trab[0]
        out.append(H("shopify_cola", CRIT, f"{len(trab)}{'+' if len(trab) == 20 else ''} eventos de Shopify sin procesar hace más de 15 min",
                     f"El más antiguo: {x['topic']} {x['shopify_order_name'] or ''} "
                     f"({x['store_id'][1] if x['store_id'] else '?'}) recibido a las {hora(de_odoo(x['create_date']))}. "
                     f"El cron «Shopify: cola de pedidos» los toma en ≤5 min: esos pedidos todavía no están en Odoo."))
    err = od.ex("shopify.webhook.event", "search_read",
                [("state", "=", "error"), ("create_date", ">=", ts(ahora - timedelta(hours=2)))],
                fields=["shopify_order_name", "store_id", "error"], limit=20)
    if err:
        nombres = ", ".join(sorted({x["shopify_order_name"] or "?" for x in err}))[:200]
        out.append(H("shopify_error", CRIT if len(err) >= 5 else ADV, f"{len(err)} eventos de Shopify con error (2 h)",
                     f"Pedidos: {nombres}. Primer error: {(err[0]['error'] or '')[:180]}"))
    resc = od.ex("shopify.webhook.event", "search_count",
                 [("source", "=", "reconcile"), ("create_date", ">=", ts(ahora - timedelta(minutes=60)))])
    if resc >= 3:
        out.append(H("shopify_rescate", ADV, f"{resc} pedidos de Shopify entraron por reconciliación (1 h)",
                     "Los webhooks de Shopify no están llegando a Odoo: los pedidos entran igual, pero por la "
                     "reconciliación, con hasta 30 min de atraso."))
    g = od.ex("shopify.webhook.event", "read_group",
              [("topic", "=", "orders/paid"), ("create_date", ">=", ts(ahora - timedelta(hours=1)))],
              ["id:count"], ["store_id"], lazy=False)
    met["shopify_1h"] = {(x["store_id"][1].split(" (")[0] if x["store_id"] else "?"): x["__count"] for x in g}
    tipo, activo, inicio = fase(ahora)
    if tipo == "pico" and activo:
        ult = od.ex("shopify.webhook.event", "search_read", [("topic", "=", "orders/paid")],
                    fields=["create_date"], order="id desc", limit=1)
        ref = max(t for t in ((de_odoo(ult[0]["create_date"]) if ult else None), inicio) if t)
        sil = minutos(ref, ahora)
        if sil > SHOPIFY_SILENCIO_PICO:
            out.append(H("silencio:shopify", ADV, f"Sin pedidos pagados de Shopify hace {fmt_min(sil)}",
                         "Ninguna de las 3 tiendas (UnionX, Lhotse, Simplit). En el Cyber de junio la brecha más larga "
                         "fue 51 min. Revisar que las tiendas estén vendiendo y que lleguen los webhooks."))
    return out


def chk_flujo(od, ahora, met):
    out = []
    d3, m30 = ts(ahora - timedelta(days=3)), ts(ahora - timedelta(minutes=30))
    borr = od.ex("sale.order", "search_read",
                 [("create_uid", "=", YUJU_UID), ("state", "in", ["draft", "sent"]),
                  ("create_date", ">=", d3), ("create_date", "<", m30)], fields=["name"], limit=50)
    if borr:
        out.append(H("yuju_sin_confirmar", CRIT if len(borr) >= 10 else ADV,
                     f"{len(borr)} pedidos Yuju sin confirmar hace más de 30 min",
                     f"{', '.join(x['name'] for x in borr[:10])}. Sin confirmar no generan despacho."))
    sinp = od.ex("sale.order", "search_read",
                 [("create_uid", "=", YUJU_UID), ("state", "=", "sale"), ("picking_ids", "=", False),
                  ("create_date", ">=", d3), ("create_date", "<", m30)], fields=["name"], limit=50)
    if sinp:
        out.append(H("yuju_sin_despacho", CRIT if len(sinp) >= 5 else ADV,
                     f"{len(sinp)} pedidos Yuju confirmados sin orden de despacho",
                     f"{', '.join(x['name'] for x in sinp[:10])}. Bodega no los ve."))
    pick = od.ex("stock.picking", "search_count",
                 [("picking_type_code", "=", "outgoing"), ("state", "=", "draft"),
                  ("create_date", ">=", d3), ("create_date", "<", m30)])
    if pick >= 5:
        out.append(H("despachos_borrador", ADV, f"{pick} despachos en borrador hace más de 30 min",
                     "Normalmente se confirman solos al confirmar el pedido."))
    return out


def chk_yuju_stock(od, ahora, met):
    out = []
    cfg = od.ex("madkting.config", "search_read", [],
                fields=["webhook_stock_enabled", "stock_source_multi", "write_date", "write_uid"])
    if not cfg:
        return [H("yuju_config", CRIT, "Yuju: no existe la configuración (madkting.config)",
                  "El módulo no puede enviar stock a los marketplaces.")]
    c = cfg[0]
    if not c["webhook_stock_enabled"]:
        out.append(H("yuju_flag", CRIT, "Yuju: el envío de stock a marketplaces está APAGADO",
                     "«Stock webhooks enabled» en False (misma causa del congelamiento 17→22-sep). Riesgo de sobreventa."))
    if not c["stock_source_multi"]:
        out.append(H("yuju_bodega", CRIT, "Yuju: sin bodega de origen del stock (Multi Stock Src vacío)",
                     "Desde la versión 2.8.x el envío lo exige. Valor que funciona: CA1/Stock."))
    if de_odoo(c["write_date"]) > ahora - timedelta(hours=24):
        out.append(H("yuju_config_cambio", ADV, "Yuju: alguien cambió la configuración",
                     f"{fecha_hora(de_odoo(c['write_date']))} por {c['write_uid'][1] if c['write_uid'] else '?'}. "
                     f"Verificar que fue intencional.", recordar=False))
    hooks = od.ex("madkting.webhook", "search_read", [("hook_type", "=", "stock")],
                  fields=["id", "active", "id_shop"], context={"active_test": False})
    act = [h for h in hooks if h["active"]]
    if len(act) != 1 or any(str(h["id_shop"] or "").strip() != YUJU_ID_SHOP for h in act):
        det = "; ".join(f"id {h['id']} shop={h['id_shop']} {'activo' if h['active'] else 'inactivo'}" for h in hooks) or "ninguno"
        out.append(H("yuju_endpoint", ADV, "Yuju: endpoints de stock anómalos",
                     f"Se espera 1 activo con id_shop {YUJU_ID_SHOP}: {det}."))
    m30 = ts(ahora - timedelta(minutes=30))
    mov = od.ex("stock.move", "search_count",
                [("state", "=", "done"), ("date", ">=", m30), ("product_id.id_product_madkting", "!=", False)])
    wh = od.ex("yuju.webhook.record", "search_count", [("event", "=", "stock_update"), ("create_date", ">=", m30)])
    met["yuju_mov_30"], met["yuju_wh_30"] = mov, wh
    if mov >= 10 and wh == 0:
        out.append(H("yuju_stock_congelado", CRIT, "Yuju: el stock de los marketplaces no se está actualizando",
                     f"{mov} movimientos de stock de productos publicados en 30 min y ningún envío de stock a Yuju. "
                     f"Riesgo de sobreventa y cancelaciones.", confirmar=2))
    pend = od.ex("yuju.webhook.record", "search_count",
                 [("state", "!=", "done"), ("create_date", ">=", ts(ahora - timedelta(hours=2))),
                  ("create_date", "<", ts(ahora - timedelta(minutes=15)))])
    if pend:
        out.append(H("yuju_wh_pendientes", ADV, f"Yuju: {pend} envíos de stock sin confirmar (2 h)",
                     "Quedaron en borrador o con error: Yuju no los recibió."))
    mods = od.ex("ir.module.module", "search_read",
                 [("state", "=", "installed"), ("write_date", ">=", ts(ahora - timedelta(minutes=60)))],
                 fields=["name"], limit=30)
    if mods:
        out.append(H("odoo_modulos", ADV, f"Se actualizaron {len(mods)} módulos de Odoo en la última hora",
                     f"Posible despliegue en Odoo.sh: {', '.join(m['name'] for m in mods[:12])}. En septiembre una "
                     f"reconstrucción apagó el envío de stock a Yuju: verificar que Yuju y Shopify sigan operando.",
                     recordar=False))
    return out


def chk_dte(od, ahora, met):
    out = []
    dom = [("l10n_cl_dte_status", "=", "not_sent"), ("state", "=", "posted")]
    met["dte_pend"] = n = od.ex("account.move", "search_count", dom)
    if n:
        viejo = od.ex("account.move", "search_read", dom, fields=["name", "create_date"], order="create_date asc", limit=1)[0]
        edad = minutos(de_odoo(viejo["create_date"]), ahora)
        met["dte_edad_min"] = edad
        if edad > 90:
            out.append(H("dte_cola", CRIT if edad > 240 else ADV, f"{n} documentos sin enviar al SII; el más antiguo hace {fmt_min(edad)}",
                         f"{viejo['name']} creado a las {hora(de_odoo(viejo['create_date']))}. El cron de envío corre cada "
                         f"15 min: la cola no está bajando."))
    rech = od.ex("account.move", "search_count",
                 [("l10n_cl_dte_status", "=", "rejected"), ("create_date", ">=", ts(ahora - timedelta(hours=6)))])
    if rech >= 10:
        out.append(H("dte_rechazos", ADV, f"{rech} documentos rechazados por el SII (6 h)", "Revisar el motivo en Odoo."))
    return out


def chk_correo(od, ahora, met):
    out = []
    met["correo_cola"] = n = od.ex("mail.mail", "search_count", [("state", "=", "outgoing")])
    if n:
        viejo = od.ex("mail.mail", "search_read", [("state", "=", "outgoing")], fields=["create_date"],
                      order="create_date asc", limit=1)[0]
        edad = minutos(de_odoo(viejo["create_date"]), ahora)
        if edad > 30:
            out.append(H("correo_cola", ADV, f"{n} correos en cola; el más antiguo hace {fmt_min(edad)}",
                         "La cola de correos salientes no está saliendo (confirmaciones, etiquetas, avisos)."))
    exc = od.ex("mail.mail", "search_count",
                [("state", "=", "exception"), ("create_date", ">=", ts(ahora - timedelta(minutes=60))),
                 ("subject", "not ilike", "Acknowledgment")])
    if exc >= 20:
        out.append(H("correo_fallas", ADV, f"{exc} correos fallidos en la última hora", "Revisar el servidor de correo saliente."))
    return out


CHEQUEOS = [  # los 3 primeros se mantienen aunque Odoo esté lento; el resto se salta para no cargarlo más
    ("Crons", chk_crons), ("Pedidos Yuju", chk_pedidos_yuju), ("Shopify", chk_shopify),
    ("Pedidos trabados", chk_flujo), ("Stock a marketplaces", chk_yuju_stock), ("DTE", chk_dte), ("Correo", chk_correo),
]


def ciclo(od, ahora):
    """Devuelve (hallazgos, chequeos que no se pudieron hacer, métricas)."""
    met, hall, fallidos = {"t": {}}, [], set()
    t0 = time.time()
    try:
        for h in chk_disponibilidad(od, ahora, met):
            h.origen = "Disponibilidad"
            hall.append(h)
    except PermissionError as e:
        h = H("vigia_acceso", CRIT, "El vigía no puede entrar a Odoo", str(e))
        h.origen = "Disponibilidad"
        return [h], {n for n, _ in CHEQUEOS}, met
    except Exception as e:
        h = H("odoo_rpc", CRIT, "Odoo no responde a consultas", f"{type(e).__name__}: {str(e)[:200]}", confirmar=2)
        h.origen = "Disponibilidad"
        od.uid = None
        met["t"]["Disponibilidad"] = time.time() - t0
        return hall + [h], {n for n, _ in CHEQUEOS}, met
    met["t"]["Disponibilidad"] = time.time() - t0
    lento = met.get("rpc_s", 0) > 10
    for i, (nombre, fn) in enumerate(CHEQUEOS):
        if lento and i >= 3:
            fallidos.add(nombre)
            continue
        t = time.time()
        try:
            for h in fn(od, ahora, met):
                h.origen = nombre
                hall.append(h)
        except Exception as e:
            fallidos.add(nombre)
            h = H(f"chequeo:{nombre}", ADV, f"El vigía no pudo revisar: {nombre}",
                  f"{type(e).__name__}: {str(e)[:200]}", confirmar=3)
            h.origen = "Vigía"
            hall.append(h)
        met["t"][nombre] = time.time() - t
    met["ciclo_s"] = time.time() - t0
    return hall, fallidos, met


# ─── seguimiento entre ciclos ────────────────────────────────────────────────
class Estado:
    def __init__(self):
        self.abiertos = {}   # clave → {"h", "desde", "veces", "avisado", "nivel_avisado"}

    def actualizar(self, hallazgos, fallidos, ahora):
        nuevos, recordar, resueltos, vistos = [], [], [], set()
        for h in hallazgos:
            if h.clave in vistos:
                continue
            vistos.add(h.clave)
            a = self.abiertos.setdefault(h.clave, {"desde": ahora, "veces": 0, "avisado": None, "nivel_avisado": None})
            a["h"] = h
            a["veces"] += 1
            if a["veces"] < h.confirmar:
                continue
            if a["avisado"] is None or (h.nivel == CRIT and a["nivel_avisado"] == ADV):
                nuevos.append(a)
            elif h.recordar and ahora - a["avisado"] >= timedelta(minutes=30 if h.nivel == CRIT else 120):
                recordar.append(a)
        for clave in list(self.abiertos):
            if clave in vistos or self.abiertos[clave]["h"].origen in fallidos:
                continue        # si el chequeo no se pudo hacer, no se da por resuelto
            a = self.abiertos.pop(clave)
            if a["avisado"]:
                resueltos.append(a)
        return nuevos, recordar, resueltos

    def marcar(self, items, ahora):
        for a in items:
            a["avisado"], a["nivel_avisado"] = ahora, a["h"].nivel

    def avisados(self):
        return [a for a in self.abiertos.values() if a["avisado"]]


# ─── correo ──────────────────────────────────────────────────────────────────
COLOR = {CRIT: "#dc2626", ADV: "#d97706"}
_gmail = None


def enviar(asunto, html):
    global _gmail
    if _gmail is None:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        tok = os.environ.get("GMAIL_TOKEN_JSON")
        creds = (Credentials.from_authorized_user_info(json.loads(tok)) if tok
                 else Credentials.from_authorized_user_file(str(ROOT / "agente-comex/config/token.json")))
        if not creds.valid:
            creds.refresh(Request())
        _gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    msg = EmailMessage()
    msg["To"], msg["From"], msg["Subject"] = DESTINO, "andres@unionx.cl", asunto
    msg.set_content("Vigía Cyber Odoo (ver versión HTML).")
    msg.add_alternative(html, subtype="html")
    _gmail.users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}).execute()


def _item(a, ahora, resuelto=False):
    h = a["h"]
    color = "#16a34a" if resuelto else COLOR[h.nivel]
    etiqueta = "RESUELTO" if resuelto else h.nivel
    dur = f"abierto desde las {hora(a['desde'])} ({fmt_min(minutos(a['desde'], ahora))})"
    return (f"<div style='border-left:4px solid {color};padding:6px 10px;margin:0 0 10px;background:#f8fafc'>"
            f"<span style='color:{color};font-weight:700;font-size:12px'>{etiqueta}</span> · "
            f"<span style='color:#64748b;font-size:12px'>{escape(h.origen or '')} · {dur}</span><br>"
            f"<b>{escape(h.titulo)}</b><br><span style='color:#334155'>{escape(h.detalle)}</span></div>")


def _metricas(met, picos=None):
    def fila(k, v):
        return f"<tr><td style='padding:3px 10px 3px 0;color:#64748b'>{k}</td><td style='padding:3px 0'>{v}</td></tr>"
    y = met.get("yuju_1h", {})
    s = met.get("shopify_1h", {})
    filas = [
        fila("Odoo", f"lectura mínima {met['rpc_s']:.1f} s · página de ingreso {met['web_s']:.1f} s"
             if met.get("rpc_s") is not None and met.get("web_s") is not None else "sin respuesta"),
        fila("Pedidos Yuju (última hora)", f"{sum(y.values())} · " + " · ".join(f"{k.replace(' Chile', '')} {v}" for k, v in sorted(y.items(), key=lambda kv: -kv[1])) if y else "0"),
        fila("Pedidos Shopify (última hora)", f"{sum(s.values())} · " + " · ".join(f"{k} {v}" for k, v in s.items()) if s else "0"),
        fila("Stock a Yuju (30 min)", f"{met.get('yuju_wh_30', '?')} envíos · {met.get('yuju_mov_30', '?')} movimientos"),
        fila("Crons", f"{met.get('crons_atrasados', '?')} atrasados > 15 min · {met.get('cron_min_1h', 0):.0f} min de cron en la última hora"),
        fila("DTE sin enviar al SII", f"{met.get('dte_pend', '?')}" + (f" · más antiguo {fmt_min(met['dte_edad_min'])}" if met.get("dte_edad_min") else "")),
        fila("Correos en cola", f"{met.get('correo_cola', '?')}"),
        fila("Fase", met.get("fase", "?")),
    ]
    if picos:
        filas.append(fila("Peor valor desde el último resumen",
                          f"lectura mínima {picos.get('rpc_s', 0):.1f} s · crons atrasados {picos.get('crons_atrasados', 0)} · "
                          f"DTE sin enviar {picos.get('dte_pend', 0)} · ciclo más largo {picos.get('ciclo_s', 0):.0f} s"))
    return f"<table style='font-size:13px;border-collapse:collapse;margin-top:6px'>{''.join(filas)}</table>"


def _envoltorio(titulo, cuerpo, ahora):
    return (f"<div style='font-family:Segoe UI,Arial,sans-serif;max-width:720px;color:#0f172a'>"
            f"<h3 style='margin:0 0 4px'>{escape(titulo)}</h3>"
            f"<p style='margin:0 0 14px;color:#64748b;font-size:12px'>{ahora.astimezone(CLT):%d-%m-%Y %H:%M} CLT · "
            f"revisión cada 5 min de Odoo, Yuju y Shopify</p>{cuerpo}</div>")


def correo_alerta(nuevos, recordar, resueltos, met, ahora):
    abiertos = nuevos + recordar
    if abiertos:
        crit = [a for a in abiertos if a["h"].nivel == CRIT]
        icono = "🔴" if crit else "🟡"
        principal = (crit or abiertos)[0]["h"].titulo
        extra = len(abiertos) - 1
        asunto = f"{icono} Vigía Cyber Odoo · {principal}" + (f" (+{extra})" if extra else "")
    else:
        asunto = f"✅ Vigía Cyber Odoo · resuelto: {resueltos[0]['h'].titulo}" + (f" (+{len(resueltos) - 1})" if len(resueltos) > 1 else "")
    cuerpo = ""
    if nuevos:
        cuerpo += "<h4 style='margin:10px 0 6px'>Nuevo</h4>" + "".join(_item(a, ahora) for a in nuevos)
    if recordar:
        cuerpo += "<h4 style='margin:10px 0 6px'>Sigue abierto</h4>" + "".join(_item(a, ahora) for a in recordar)
    if resueltos:
        cuerpo += "<h4 style='margin:10px 0 6px'>Resuelto</h4>" + "".join(_item(a, ahora, True) for a in resueltos)
    cuerpo += "<h4 style='margin:14px 0 2px'>Estado ahora</h4>" + _metricas(met)
    return asunto, _envoltorio(asunto[2:].strip(), cuerpo, ahora)


def correo_resumen(estado, met, picos, ahora, prueba=False):
    abiertos = estado.avisados() if estado else []
    icono = "🔴" if any(a["h"].nivel == CRIT for a in abiertos) else "🟡" if abiertos else "🟢"
    etiqueta = "PRUEBA" if prueba else f"resumen {ahora.astimezone(CLT):%H:%M}"
    asunto = f"{icono} Vigía Cyber Odoo · {etiqueta} · " + (f"{len(abiertos)} problemas abiertos" if abiertos else "todo en orden")
    cuerpo = ("".join(_item(a, ahora) for a in abiertos) if abiertos
              else "<p style='margin:0 0 6px'>Sin problemas abiertos.</p>")
    cuerpo += "<h4 style='margin:14px 0 2px'>Estado ahora</h4>" + _metricas(met, picos)
    cuerpo += ("<p style='color:#64748b;font-size:12px;margin-top:14px'>Este resumen llega a las 08:30 y 20:30. "
               "Si no llega, el vigía está caído.</p>")
    return asunto, _envoltorio(asunto[2:].strip(), cuerpo, ahora)


# ─── ejecución ───────────────────────────────────────────────────────────────
def imprimir_detalle(hall, fallidos, met):
    print(f"\nFase: {met.get('fase', '?')} · ciclo {met.get('ciclo_s', 0):.1f} s")
    print("Tiempo por chequeo: " + " · ".join(f"{k} {v:.1f}s" for k, v in met["t"].items()))
    if fallidos:
        print(f"No revisados: {', '.join(sorted(fallidos))}")
    if not hall:
        print("\n✅ Sin hallazgos.")
    for h in sorted(hall, key=lambda h: h.nivel != CRIT):
        conf = f" (avisa al {h.confirmar}° ciclo seguido)" if h.confirmar > 1 else ""
        print(f"\n[{h.nivel}] {h.origen}: {h.titulo}{conf}\n    {h.detalle}")
    print("\nMétricas: " + json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in met.items() if k != "t"},
                                      ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--una-vez", action="store_true", help="un ciclo, muestra todo en pantalla")
    ap.add_argument("--enviar", action="store_true", help="con --una-vez: manda el resumen por correo")
    ap.add_argument("--prueba", action="store_true", help="un ciclo + correo de prueba")
    a = ap.parse_args()
    od = Odoo()

    if a.una_vez or a.prueba:
        ahora = ahora_utc()
        hall, fallidos, met = ciclo(od, ahora)
        if EN_ACTIONS:
            print(f"[vigía] ciclo de prueba: {sum(h.nivel == CRIT for h in hall)} críticas · "
                  f"{sum(h.nivel == ADV for h in hall)} advertencias · {met.get('ciclo_s', 0):.0f} s")
        else:
            imprimir_detalle(hall, fallidos, met)
        if a.prueba or a.enviar:
            est = Estado()
            est.marcar(est.actualizar([h for h in hall if h.confirmar == 1], fallidos, ahora)[0], ahora)
            enviar(*correo_resumen(est, met, None, ahora, prueba=a.prueba))
            print(f"[vigía] correo enviado a {DESTINO}")
        return

    t0 = ahora_utc()
    if t0 >= VIGIA_HASTA:
        print("[vigía] el período del Cyber terminó: no hace nada")
        return
    if VIGIA_DESDE - t0 > TURNO:
        print(f"[vigía] faltan {VIGIA_DESDE - t0} para empezar: sale (el cron lo vuelve a arrancar)")
        return
    fin_turno = t0 + TURNO
    estado, picos, n, resumen_hecho = Estado(), {}, 0, set()
    print(f"[vigía] turno {t0.astimezone(CLT):%d-%m %H:%M} → {fin_turno.astimezone(CLT):%H:%M} CLT · avisa a {DESTINO}", flush=True)
    while True:
        ahora = ahora_utc()
        if ahora >= VIGIA_HASTA:
            print("[vigía] fin del período del Cyber")
            return
        if ahora >= fin_turno:
            break
        if ahora >= VIGIA_DESDE:
            n += 1
            hall, fallidos, met = ciclo(od, ahora)
            for k in ("rpc_s", "crons_atrasados", "dte_pend", "ciclo_s"):
                if isinstance(met.get(k), (int, float)):
                    picos[k] = max(picos.get(k, 0), met[k])
            nuevos, recordar, resueltos = estado.actualizar(hall, fallidos, ahora)
            # el log de Actions es público: solo conteos de problemas, nunca cifras del negocio
            print(f"[{hora(ahora)} CLT] ciclo {n}: {sum(a['h'].nivel == CRIT for a in estado.abiertos.values())} críticos · "
                  f"{sum(a['h'].nivel == ADV for a in estado.abiertos.values())} advertencias · {len(nuevos)} nuevos · "
                  f"{len(resueltos)} resueltos · {met.get('ciclo_s', 0):.0f} s", flush=True)
            if nuevos or recordar or resueltos:
                try:
                    enviar(*correo_alerta(nuevos, recordar, resueltos, met, ahora))
                    estado.marcar(nuevos + recordar, ahora)
                except Exception as e:      # se reintenta en el próximo ciclo
                    print(f"[vigía] no se pudo enviar el aviso: {type(e).__name__}", flush=True)
            local = ahora.astimezone(CLT)
            slot = (local.date(), local.hour)
            if local.hour in RESUMEN_HORAS and 30 <= local.minute < 40 and slot not in resumen_hecho:
                try:
                    enviar(*correo_resumen(estado, met, picos, ahora))
                    resumen_hecho.add(slot)
                    picos = {}
                except Exception as e:
                    print(f"[vigía] no se pudo enviar el resumen: {type(e).__name__}", flush=True)
        prox = ahora_utc()
        prox = prox.replace(second=0, microsecond=0) + timedelta(minutes=5 - prox.minute % 5)
        time.sleep(max((prox - ahora_utc()).total_seconds(), 1))
    print("[vigía] fin del turno: relevo", flush=True)
    subprocess.run(["gh", "workflow", "run", "watchdog_cyber.yml"], check=False)


if __name__ == "__main__":
    main()
