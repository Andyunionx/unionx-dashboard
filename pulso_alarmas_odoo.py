# -*- coding: utf-8 -*-
"""Pulso Alarmas Odoo — salud de crons + cola DTE, diario a primera hora.

Origen: incidente 20-ago-2026 (cron 26 'Send document to SII' apagado desde el
11-ago por trabajos de performance → 2.822 boletas sin enviar, lo detectó Yohana
9 días después). Este pulso lo habría acusado al día siguiente.

Chequeos:
  1. CRÍTICO — crons de la watchlist apagados.
  2. CRÍTICO — cron activo pero "muerto": lastcall más viejo que 3× su intervalo (mín 2 h).
  3. CRÍTICO — cola DTE: documentos posteados 'not_sent' > umbral.
  4. ADVERTENCIA — DTEs rechazados/objetados de las últimas 48 h sobre umbral.
  5. ADVERTENCIA — failure_count > 0 en cualquier cron activo.
  6. Tabla informativa: watchlist con estado, última y próxima ejecución.
  7. YUJU (stock → marketplaces). Origen: incidente 17→22 sep 2026 (rebuild Odoo.sh
     dejó código que respeta un flag que nació en False el 4-jun; 5 días sin webhooks
     de stock, nadie lo vio). CRÍTICO si el flag está apagado, si Multi Stock Src está
     vacío, o si hubo movimientos de stock en 24 h y NINGÚN webhook salió.
     ADVERTENCIA si la config o el módulo cambiaron en 24 h (quién y qué), o si hay
     endpoints raros (≠1 activo de stock, o id_shop=0).

  8. STOCK NEGATIVO (rediseño aprobado por Andrés el 15-nov-2026). Del 10 al 15-nov la crítica salió igual todos
     los días (14 a 16 casos en CA1/Output que vienen desde septiembre) y dejó de leerse. Ahora:
     CRÍTICO solo si hay negativos NUEVOS o que EMPEORARON en Entrada/Salida desde la corrida anterior, con el
     picking y el usuario que los generó. El acumulado pasa a ADVERTENCIA con su tendencia.
     El módulo madkting avisa solo si CAMBIA de versión (antes avisaba por cualquier reinstalación).

Estado entre corridas: VIGIA_ESTADO (por defecto .estado_vigia/estado.json; en CI lo conserva actions/cache).
Guarda las cantidades negativas y la versión de madkting de la corrida anterior. Sin estado previo, "nuevo" =
quant negativo modificado en las últimas VENTANA_NEG_H horas, y madkting no avisa.

Envío: Gmail API (token agente-comex local o GMAIL_TOKEN_JSON en CI).
Destinatarios: el pulso completo va a ALARMAS_EMAIL_TO (por defecto solo andres@unionx.cl). Si hay negativos
nuevos en Entrada/Salida sale además un correo corto, solo con esos casos, a NEGATIVOS_EMAIL_TO, con copia a
Andrés (aprobado el 15-nov para gerardo@unionx.cl). Revisión del 24-nov: el script NO trae destinatario por
defecto; el interruptor es una sola línea del workflow (NEGATIVOS_EMAIL_TO). Sin esa variable, o vacía, no sale.
Tampoco sale cuando no hay estado de la corrida anterior: ahí "nuevo" es una aproximación por write_date.

En GitHub Actions el log es público (el repo es público): los nombres de usuarios de Odoo no se imprimen ahí.
"""
import sys, json, os, time, base64, datetime
from html import escape
from pathlib import Path
import xmlrpc.client

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
HOY = datetime.datetime.utcnow()

# Hora de Chile real (antes se restaban 4 h fijas; con horario de verano son 3).
try:
    from zoneinfo import ZoneInfo
    _TZ_CL = ZoneInfo("America/Santiago")
except Exception:  # sin base de zonas horarias (Windows sin tzdata): horario de verano
    _TZ_CL = datetime.timezone(datetime.timedelta(hours=-3))


def hora_chile(dt_utc=None):
    """Datetime naive en UTC → hora de Chile."""
    return (dt_utc or HOY).replace(tzinfo=datetime.timezone.utc).astimezone(_TZ_CL)


# Estado entre corridas (negativos y versión de madkting de la corrida anterior).
ESTADO_PATH = Path(os.environ.get("VIGIA_ESTADO") or (ROOT / ".estado_vigia" / "estado.json"))
try:
    estado_prev = json.loads(ESTADO_PATH.read_text(encoding="utf-8"))
    if not isinstance(estado_prev, dict):
        estado_prev = {}
except Exception:
    estado_prev = {}
estado_nuevo = {"corrida_utc": HOY.strftime("%Y-%m-%d %H:%M:%S")}
VENTANA_NEG_H = 30          # sin estado previo: 24 h + margen por el atraso del gatillo
MAX_ORIGEN_NEG = 15         # a cuántos negativos nuevos se les busca picking y usuario

# ---- Odoo ----
cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
pw = os.environ.get("ANDRES_ODOO_PASSWORD", "")
if not pw and (ROOT / "odoo/.odoo_pass").exists():
    pw = (ROOT / "odoo/.odoo_pass").read_text().strip()
uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(cfg["db_name"], cfg["username"], pw, {})

def rpc(model, method, args, kw=None):
    for i in range(4):
        try:
            return xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object").execute_kw(
                cfg["db_name"], uid, pw, model, method, args, kw or {})
        except Exception:
            if i == 3:
                raise
            time.sleep(10)

# Crons que DEBEN estar activos (id: descripción corta)
WATCHLIST = {
    26: "Envío DTE al SII (boletas/facturas)",
    27: "SII: consulta estados / jobs generales",
    156: "Monitor DTEs rechazados (UnionX)",
    157: "Corrector 801 Duty/Dimarsa (UnionX)",
    132: "Costo packs desde LdM (UnionX)",
    159: "Peso packs desde LdM (UnionX)",
    149: "Shopify Directo: reconciliar pedidos",
    152: "Shopify Directo: sentinel sin-pedidos",
    115: "Yuju: envío de webhooks de stock a marketplaces",
}
# Yuju: mínimo de movimientos de stock en 24 h para exigir que haya salido algún webhook
# (día hábil normal ≈ 900; fin de semana puede ser ~0 y no debe alarmar)
YUJU_MIN_MOVES = 20
YUJU_ID_SHOP = 1090300
UMBRAL_NOT_SENT = 150
UMBRAL_RECHAZADOS = 10
UMBRAL_OBJETADOS = 40

DUR = {"minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800, "months": 2592000}

criticas, advertencias, tabla = [], [], []
EN_CI = os.environ.get("GITHUB_ACTIONS") == "true"
nombres_personas = set()    # usuarios de Odoo citados en las alarmas: van en el correo, no en el log público


def para_log(txt):
    """En GitHub Actions el log lo puede leer cualquiera: se quitan los nombres de personas."""
    if EN_CI:
        for nom in sorted(nombres_personas, key=len, reverse=True):
            if nom and nom != "?":
                txt = txt.replace(nom, "(usuario: ver correo)")
    return txt

crons = rpc("ir.cron", "search_read", [[]],
            {"fields": ["id", "name", "active", "lastcall", "nextcall",
                        "interval_number", "interval_type", "failure_count"],
             "context": {"active_test": False}})
by_id = {c["id"]: c for c in crons}

def edad(ts):
    if not ts:
        return None
    return (HOY - datetime.datetime.fromisoformat(ts)).total_seconds()

def fmt_edad(seg):
    if seg is None:
        return "nunca"
    if seg < 3600:
        return f"hace {seg/60:.0f} min"
    if seg < 86400:
        return f"hace {seg/3600:.1f} h"
    return f"hace {seg/86400:.1f} días"

# 1-2) watchlist apagada o muerta
for cid, desc in WATCHLIST.items():
    c = by_id.get(cid)
    if c is None:
        criticas.append(f"Cron {cid} ({desc}) NO EXISTE — ¿fue eliminado?")
        continue
    e = edad(c["lastcall"])
    periodo = (c["interval_number"] or 1) * DUR.get(c["interval_type"], 86400)
    estado = "ACTIVO"
    if not c["active"]:
        estado = "APAGADO"
        criticas.append(f"Cron {cid} «{c['name']}» está APAGADO ({desc}). Última corrida {fmt_edad(e)}.")
    elif e is not None and e > max(3 * periodo, 7200):
        estado = "SIN CORRER"
        criticas.append(f"Cron {cid} «{c['name']}» activo pero SIN CORRER {fmt_edad(e)} (intervalo {c['interval_number']} {c['interval_type']}).")
    tabla.append((cid, c["name"][:48], desc, estado, fmt_edad(e)))

# crons activos fuera de watchlist muertos hace >24h con intervalo <= diario
for c in crons:
    if not c["active"] or c["id"] in WATCHLIST:
        continue
    periodo = (c["interval_number"] or 1) * DUR.get(c["interval_type"], 86400)
    e = edad(c["lastcall"])
    if periodo <= 86400 and e is not None and e > max(3 * periodo, 86400):
        advertencias.append(f"Cron {c['id']} «{c['name'][:50]}» activo pero sin correr {fmt_edad(e)}.")

# 5) failure_count
for c in crons:
    if c["active"] and (c.get("failure_count") or 0) > 0:
        advertencias.append(f"Cron {c['id']} «{c['name'][:50]}» con failure_count={c['failure_count']}.")

# 3) cola DTE not_sent
n_pend = rpc("account.move", "search_count",
             [[("l10n_cl_dte_status", "=", "not_sent"), ("state", "=", "posted")]])
if n_pend > UMBRAL_NOT_SENT:
    criticas.append(f"COLA SII: {n_pend:,} documentos posteados sin enviar al SII (umbral {UMBRAL_NOT_SENT}).")

# 4) rechazados / objetados últimas 48h
d2 = (HOY - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
n_rej = rpc("account.move", "search_count",
            [[("l10n_cl_dte_status", "=", "rejected"), ("state", "=", "posted"), ("date", ">=", d2)]])
n_obj = rpc("account.move", "search_count",
            [[("l10n_cl_dte_status", "=", "objected"), ("state", "=", "posted"), ("date", ">=", d2)]])
if n_rej > UMBRAL_RECHAZADOS:
    advertencias.append(f"DTEs RECHAZADOS últimas 48 h: {n_rej} (umbral {UMBRAL_RECHAZADOS}).")
if n_obj > UMBRAL_OBJETADOS:
    advertencias.append(f"DTEs aceptados con reparos últimas 48 h: {n_obj} (umbral {UMBRAL_OBJETADOS}).")

# 6) stock NEGATIVO en ubicaciones internas (firma de recepciones/correcciones a medias:
#    casos cajas Vinoteca, decantador -599, Celiv 07-sep).
#    Rediseño 15-nov-2026: CRÍTICO solo lo NUEVO o lo que EMPEORÓ en Entrada/Salida desde la corrida anterior,
#    con el picking y el usuario que lo generó. El acumulado es ADVERTENCIA con tendencia.
neg_nuevos = []                                   # también alimenta el correo a bodega
ref_prev = estado_prev.get("corrida_utc") if isinstance(estado_prev.get("negativos"), dict) else None


def _es_io(loc):
    return any(x in loc for x in ("/Input", "/Output", "/Entrada", "/Salida"))


def _tendencia(ahora, antes):
    if antes is None:
        return "sin corrida anterior para comparar"
    d = ahora - antes
    return "igual que la corrida anterior" if d == 0 else f"{d:+d} vs la corrida anterior ({antes})"


def _origen_negativo(pid, loc_id, desde):
    """Último movimiento hecho que sacó ese producto de esa ubicación: (picking, usuario, fecha Chile)."""
    campos = ["date", "reference", "picking_id", "location_id", "write_uid", "create_uid"]
    # 1.º dentro de la ventana; si no hay, la última salida que exista (se ve por la fecha que es anterior).
    # Nunca una ENTRADA a la ubicación: no deja negativo y le cargaría el caso a quien no fue.
    for dom_fecha in ([("date", ">=", desde)], []):
        ml = rpc("stock.move.line", "search_read",
                 [[("product_id", "=", pid), ("state", "=", "done"), ("location_id", "=", loc_id)] + dom_fecha],
                 {"fields": campos, "order": "date desc", "limit": 1})
        if ml:
            m = ml[0]
            pick = (m["picking_id"][1] if m.get("picking_id") else None) or m.get("reference") or "sin picking"
            quien = (m.get("write_uid") or m.get("create_uid") or [0, "?"])[1]
            nombres_personas.add(quien)
            cuando = hora_chile(datetime.datetime.fromisoformat(m["date"])).strftime("%d-%m %H:%M")
            return pick, quien, cuando
    return "sin movimiento de salida", "?", ""


try:
    negs = rpc("stock.quant", "search_read",
               [[("location_id.usage", "=", "internal"), ("quantity", "<", 0)]],
               {"fields": ["product_id", "location_id", "quantity", "write_date"], "limit": 1000})
    prev_q = estado_prev.get("negativos") if ref_prev else {}
    estado_nuevo["negativos"] = {}
    std = {}
    prods = list({q["product_id"][0] for q in negs if q["product_id"]})
    for i in range(0, len(prods), 300):
        for p in rpc("product.product", "read", [prods[i:i+300]],
                     {"fields": ["standard_price"], "context": {"active_test": False}}):
            std[p["id"]] = p["standard_price"] or 0
    io_n, io_val, otros_n, otros_val = 0, 0.0, 0, 0.0
    io_claves = {}                                     # producto|ubicación → suma de sus quants negativos
    for q in negs:
        pid = q["product_id"][0] if q["product_id"] else 0
        loc_id, loc = q["location_id"][0], q["location_id"][1]
        clave = f"{pid}|{loc_id}"
        # Un producto puede tener varios quants en la misma ubicación (lote, paquete o dueño de consignación):
        # se SUMAN. Guardar solo el último pisaba a los otros y daba "empeoró" o lo escondía según el orden.
        estado_nuevo["negativos"][clave] = estado_nuevo["negativos"].get(clave, 0) + q["quantity"]
        val = abs(q["quantity"]) * std.get(pid, 0)
        if not _es_io(loc):
            otros_n += 1
            otros_val += val
            continue
        io_n += 1
        io_val += val
        c = io_claves.setdefault(clave, {"pid": pid, "loc_id": loc_id, "ubicacion": loc, "cantidad": 0.0, "valor": 0.0,
                                         "producto": q["product_id"][1] if q["product_id"] else "?", "write": None})
        c["cantidad"] += q["quantity"]
        c["valor"] += val
        c["write"] = max(filter(None, (c["write"], q["write_date"])), default=None)
    for clave, c in io_claves.items():
        antes = prev_q.get(clave)
        if ref_prev:                                   # con estado: nuevo o más negativo que la corrida anterior
            es_nuevo = antes is None or c["cantidad"] < antes - 1e-9
        else:                                          # sin estado: modificado dentro de la ventana (aproximación)
            e_q = edad(c["write"])
            es_nuevo = e_q is not None and e_q <= VENTANA_NEG_H * 3600
        if es_nuevo:
            neg_nuevos.append({"pid": c["pid"], "loc_id": c["loc_id"], "producto": c["producto"],
                               "ubicacion": c["ubicacion"], "cantidad": c["cantidad"], "antes": antes, "valor": c["valor"]})
    estado_nuevo["resumen_neg"] = {"io_n": io_n, "io_val": round(io_val), "otros_n": otros_n, "otros_val": round(otros_val)}
    rprev = estado_prev.get("resumen_neg") if ref_prev else None
    if neg_nuevos:
        desde_dt = (datetime.datetime.fromisoformat(ref_prev) - datetime.timedelta(hours=1)) if ref_prev \
            else HOY - datetime.timedelta(hours=VENTANA_NEG_H)
        desde = desde_dt.strftime("%Y-%m-%d %H:%M:%S")
        neg_nuevos.sort(key=lambda x: -x["valor"])
        for x in neg_nuevos[:MAX_ORIGEN_NEG]:
            try:
                x["picking"], x["usuario"], x["cuando"] = _origen_negativo(x["pid"], x["loc_id"], desde)
            except Exception as e:  # noqa: BLE001
                x["picking"], x["usuario"], x["cuando"] = f"no se pudo leer ({str(e)[:40]})", "?", ""
        ref_txt = (f"desde la corrida anterior ({hora_chile(datetime.datetime.fromisoformat(ref_prev)):%d-%m %H:%M})"
                   if ref_prev else f"en las últimas {VENTANA_NEG_H} h")
        det = "; ".join(
            f"{x['producto'][:40]} en {x['ubicacion']}: {x['cantidad']:g} u"
            + (f" (antes {x['antes']:g})" if x["antes"] is not None else " (nuevo)")
            + (f" · {x['picking']} · {x['usuario']}" + (f" · {x['cuando']}" if x.get("cuando") else "")
               if x.get("picking") else "")
            for x in neg_nuevos[:8])
        criticas.append(f"STOCK NEGATIVO NUEVO EN ENTRADA/SALIDA: {len(neg_nuevos)} caso(s) {ref_txt} "
                        f"(recepción o corrección a medias) → {det}" + (" …" if len(neg_nuevos) > 8 else ""))
    if io_n:
        resto = (f"Incluye los {len(neg_nuevos)} nuevo(s) de arriba; el resto no es de hoy y se resuelve"
                 if neg_nuevos else "No son de hoy: se resuelven")
        advertencias.append(f"Negativos acumulados en Entrada/Salida: {io_n} casos por ~${io_val:,.0f} a costo "
                            f"({_tendencia(io_n, rprev.get('io_n') if rprev else None)}). {resto} "
                            f"con la limpieza previa al inventario.")
    if otros_val > 500000:
        advertencias.append(f"Stock negativo en bodegas internas: {otros_n} quants por ~${otros_val:,.0f} a costo "
                            f"({_tendencia(otros_n, rprev.get('otros_n') if rprev else None)}; revisar ajustes pendientes).")
except Exception as e:
    advertencias.append(f"Chequeo de negativos falló: {str(e)[:80]}")

# 7) YUJU — el stock que ven los marketplaces sale de Odoo por webhook (módulo madkting).
#    Se vigila la config, los endpoints, el flujo real de las últimas 24 h y cambios del módulo.
yuju_resumen = "Yuju: sin datos"
try:
    d1 = (HOY - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    ycfg = rpc("madkting.config", "search_read", [[]],
               {"fields": ["webhook_stock_enabled", "stock_source_multi", "simple_stock_locations",
                           "webhook_auto_send_enabled", "webhook_stock_cron_enabled",
                           "webhook_product_batchsize", "write_date", "write_uid"]})
    if not ycfg:
        criticas.append("YUJU: no existe registro de configuración (madkting.config) — el módulo no puede enviar nada.")
    else:
        yc = ycfg[0]
        if not yc["webhook_stock_enabled"]:
            criticas.append("YUJU: «Stock webhooks enabled» está APAGADO en madkting.config → ningún webhook de stock sale a los marketplaces "
                            "(fue exactamente la causa del congelamiento 17→22 sep 2026).")
        if not yc["stock_source_multi"]:
            criticas.append("YUJU: «Multi Stock Src» (stock_source_multi) está VACÍO → desde la versión 2.8.x el envío lo exige aunque "
                            "simple_stock_locations esté activo. Valor histórico que funcionaba: 8 (CA1/Stock).")
        if edad(yc["write_date"]) is not None and edad(yc["write_date"]) < 86400:
            quien = yc["write_uid"][1] if yc["write_uid"] else "?"
            nombres_personas.add(quien)
            advertencias.append(
                f"YUJU: la configuración madkting.config fue MODIFICADA {fmt_edad(edad(yc['write_date']))} por {quien}. "
                f"Estado ahora → stock_enabled={yc['webhook_stock_enabled']} · src={yc['stock_source_multi']} · "
                f"auto_send={yc['webhook_auto_send_enabled']} · cron_enabled={yc['webhook_stock_cron_enabled']} · "
                f"batch={yc['webhook_product_batchsize']}. Verificar que fue intencional.")
        # endpoints
        hooks = rpc("madkting.webhook", "search_read", [[("hook_type", "=", "stock")]],
                    {"fields": ["id", "active", "id_shop", "url"], "context": {"active_test": False}})
        activos = [h for h in hooks if h["active"]]
        # id_shop es char en el módulo → comparar como texto
        if len(activos) != 1 or any(str(h["id_shop"] or "").strip() != str(YUJU_ID_SHOP) for h in activos):
            det = "; ".join(f"id {h['id']} shop={h['id_shop']} {'ON' if h['active'] else 'off'}" for h in hooks) or "ninguno"
            advertencias.append(f"YUJU: endpoints de stock anómalos (se espera 1 activo con id_shop={YUJU_ID_SHOP}): {det}. "
                                f"Un upgrade del módulo puede crear uno fantasma con id_shop=0.")
        # flujo real 24 h
        n_wh = rpc("yuju.webhook.record", "search_count", [[("date_webhook", ">=", d1), ("event", "=", "stock_update")]])
        n_wh_done = rpc("yuju.webhook.record", "search_count",
                        [[("date_webhook", ">=", d1), ("event", "=", "stock_update"), ("state", "=", "done")]])
        prods_wh = rpc("yuju.webhook.record", "read_group",
                       [[("date_webhook", ">=", d1), ("event", "=", "stock_update")], ["total_products:sum"], []],
                       {"lazy": False})
        n_prod_wh = int((prods_wh[0].get("total_products") or 0) if prods_wh else 0)
        n_moves = rpc("stock.move", "search_count",
                      [[("state", "=", "done"), ("date", ">=", d1),
                        ("product_id.id_product_madkting", "!=", False), ("product_id.active", "=", True)]])
        ult = rpc("yuju.webhook.record", "search_read", [[("event", "=", "stock_update"), ("state", "=", "done")]],
                  {"fields": ["date_webhook"], "order": "date_webhook desc", "limit": 1})
        ult_txt = fmt_edad(edad(ult[0]["date_webhook"])) if ult else "nunca"
        if n_moves >= YUJU_MIN_MOVES and n_wh_done == 0:
            criticas.append(f"YUJU: {n_moves:,} movimientos de stock en productos publicados en las últimas 24 h y CERO webhooks "
                            f"de stock enviados → el stock en los marketplaces está congelado (último envío exitoso {ult_txt}). "
                            f"Riesgo de sobreventa y cancelaciones.")
        elif n_wh and n_wh_done < n_wh:
            # Un webhook recién creado pasa unos minutos en borrador (el envío va por lotes). Solo cuentan los que
            # llevan más de 60 min sin terminar: el 24-nov había 75 "no done", todos de los últimos 2 minutos, y
            # esta advertencia salía casi todos los días por los que iban en tránsito.
            h1 = (HOY - datetime.timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
            n_atras = rpc("yuju.webhook.record", "search_count",
                          [[("date_webhook", ">=", d1), ("date_webhook", "<=", h1), ("event", "=", "stock_update"),
                            ("state", "!=", "done")]])
            if n_atras:
                advertencias.append(f"YUJU: {n_atras} de {n_wh} webhooks de stock de las últimas 24 h llevan más de "
                                    f"60 min sin quedar en estado done.")
        yuju_resumen = (f"Yuju 24h: {n_wh_done} webhooks / {n_prod_wh:,} productos · {n_moves:,} movs · "
                        f"flag {'ON' if yc['webhook_stock_enabled'] else 'OFF'} · último envío {ult_txt}")
    # versión / reinstalación del módulo
    mod = rpc("ir.module.module", "search_read", [[("name", "=", "madkting")]],
              {"fields": ["installed_version", "state", "write_date"]})
    # Solo si CAMBIA la versión instalada (antes avisaba por write_date: cada rebuild de Odoo.sh lo "reinstalaba"
    # con la misma versión 2.8.6 y la advertencia salía sin que hubiera cambiado nada).
    if mod:
        ver, ver_prev = mod[0]["installed_version"], estado_prev.get("madkting_version")
        estado_nuevo["madkting_version"] = ver
        if ver_prev and ver and ver != ver_prev:
            advertencias.append(f"YUJU: el módulo madkting CAMBIÓ DE VERSIÓN: {ver_prev} → {ver} (estado {mod[0]['state']}, "
                                f"modificado {fmt_edad(edad(mod[0]['write_date']))}). Un upgrade puede recrear la config con "
                                f"valores por defecto (flag de stock en False) o crear endpoints fantasma: revisar hoy.")
except Exception as e:
    advertencias.append(f"Chequeo Yuju falló: {str(e)[:100]}")

# ---- armar correo ----
estado_gral = "🔴" if criticas else ("🟡" if advertencias else "✅")
fecha = hora_chile().strftime("%d-%m-%Y %H:%M")  # hora de Chile (zona America/Santiago)
filas = "".join(
    f"<tr><td style='padding:4px 8px'>{cid}</td><td style='padding:4px 8px'>{nom}</td>"
    f"<td style='padding:4px 8px'>{desc}</td>"
    f"<td style='padding:4px 8px;font-weight:600;color:{'#16a34a' if est=='ACTIVO' else '#dc2626'}'>{est}</td>"
    f"<td style='padding:4px 8px'>{ult}</td></tr>"
    for cid, nom, desc, est, ult in tabla)

def bloque(titulo, items, color):
    if not items:
        return ""
    lis = "".join(f"<li style='margin:4px 0'>{escape(x, quote=False)}</li>" for x in items)
    return (f"<div style='background:{color};border-radius:8px;padding:10px 14px;margin:0 0 14px'>"
            f"<b>{titulo}</b><ul style='margin:6px 0 0;padding-left:18px'>{lis}</ul></div>")

html = f"""<div style='font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1e293b;max-width:860px'>
<h2 style='margin:0 0 4px'>{estado_gral} Pulso Alarmas Odoo · {fecha} (hora de Chile)</h2>
<p style='margin:0 0 14px;color:#64748b'>Salud de crons, cola DTE y Yuju · {len(crons)} crons ({sum(1 for c in crons if c['active'])} activos) · cola SII: {n_pend:,} sin enviar · rechazados 48h: {n_rej} · reparos 48h: {n_obj}<br>{yuju_resumen}</p>
{bloque('🔴 CRÍTICAS — requieren acción hoy', criticas, '#fee2e2')}
{bloque('🟡 Advertencias', advertencias, '#fef9c3')}
{"<p style='margin:0 0 14px'>✅ Sin alarmas: todos los crons vigilados corriendo y cola SII normal.</p>" if not criticas and not advertencias else ""}
<table cellspacing='0' style='border-collapse:collapse;font-size:13px'>
<tr style='background:#f1f5f9;font-weight:600'><td style='padding:4px 8px'>ID</td><td style='padding:4px 8px'>Cron</td><td style='padding:4px 8px'>Función</td><td style='padding:4px 8px'>Estado</td><td style='padding:4px 8px'>Última corrida</td></tr>
{filas}</table>
<p style='margin:14px 0 0;color:#94a3b8;font-size:12px'>Generado automáticamente (pulso_alarmas_odoo.py). Origen: incidente boletas sin enviar 11→20 ago 2026.</p>
</div>"""

print(f"[{estado_gral}] críticas: {len(criticas)} | advertencias: {len(advertencias)} | cola SII: {n_pend} | {yuju_resumen}")
for x in criticas: print("  CRIT:", para_log(x))
for x in advertencias: print("  ADV :", para_log(x))

for x in neg_nuevos:
    print(para_log(f"  NEG NUEVO: {x['producto'][:40]} | {x['ubicacion']} | {x['cantidad']:g} (antes {x['antes']}) | "
                   f"{x.get('picking', '-')} | {x.get('usuario', '-')} | {x.get('cuando', '')}"))

# El estado se guarda siempre que la corrida llegó hasta aquí (también con --no-enviar): es la referencia de mañana.
if "--sin-estado" not in sys.argv:
    try:
        if "negativos" not in estado_nuevo and isinstance(estado_prev.get("negativos"), dict):
            for k in ("negativos", "resumen_neg"):          # el chequeo falló hoy: se conserva la referencia anterior
                if k in estado_prev:
                    estado_nuevo[k] = estado_prev[k]
        if "madkting_version" not in estado_nuevo and estado_prev.get("madkting_version"):
            estado_nuevo["madkting_version"] = estado_prev["madkting_version"]
        ESTADO_PATH.parent.mkdir(parents=True, exist_ok=True)
        ESTADO_PATH.write_text(json.dumps(estado_nuevo, ensure_ascii=False), encoding="utf-8")
        print(f"(estado guardado: {len(estado_nuevo.get('negativos', {}))} negativos, madkting "
              f"{estado_nuevo.get('madkting_version', 's/d')}; referencia anterior: {ref_prev or 'ninguna'})")
    except Exception as e:  # noqa: BLE001
        print(f"(no se pudo guardar el estado: {str(e)[:80]})")

if "--no-enviar" in sys.argv:
    print("(--no-enviar: no se manda correo)")
    sys.exit(0)

# ---- Gmail ----
from email.message import EmailMessage
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

tok_env = os.environ.get("GMAIL_TOKEN_JSON")
if tok_env:
    creds = Credentials.from_authorized_user_info(json.loads(tok_env))
else:
    creds = Credentials.from_authorized_user_file(str(ROOT / "agente-comex/config/token.json"))
if not creds.valid:
    creds.refresh(Request())
svc = build("gmail", "v1", credentials=creds)
msg = EmailMessage()
msg["To"] = os.environ.get("ALARMAS_EMAIL_TO") or "andres@unionx.cl"
msg["From"] = "andres@unionx.cl"
msg["Subject"] = f"{estado_gral} Pulso Alarmas Odoo · {hora_chile().strftime('%d-%b')} · {len(criticas)} críticas"
msg.set_content("Pulso Alarmas Odoo (ver versión HTML).")
msg.add_alternative(html, subtype="html")
raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
r = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
print(f"Enviado: {r['id']}")

# Correo corto a bodega: SOLO los negativos nuevos en Entrada/Salida (aprobado por Andrés el 15-nov-2026).
# Interruptor: la variable NEGATIVOS_EMAIL_TO del workflow (una línea). Sin ella, o vacía, NO sale: el script no
# trae destinatario por defecto, así una corrida local o un workflow sin esa línea nunca le escribe a un tercero.
# Tampoco sale sin estado previo: ahí "nuevo" es una aproximación por write_date y a bodega solo van casos ciertos.
neg_to = os.environ.get("NEGATIVOS_EMAIL_TO", "").strip()
if neg_nuevos and neg_to and not ref_prev:
    print("(correo a bodega omitido: sin estado de la corrida anterior, los casos nuevos son una aproximación)")
elif neg_nuevos and not neg_to:
    print("(correo a bodega apagado: NEGATIVOS_EMAIL_TO vacío)")
if neg_nuevos and neg_to and ref_prev:
    td = "padding:4px 8px;border-bottom:1px solid #e2e8f0"
    filas_n = "".join(
        f"<tr><td style='{td}'>{escape(x['producto'][:60])}</td><td style='{td}'>{escape(x['ubicacion'])}</td>"
        f"<td style='{td};text-align:right'>{x['cantidad']:g}</td>"
        f"<td style='{td};text-align:right'>{'nuevo' if x['antes'] is None else format(x['antes'], 'g')}</td>"
        f"<td style='{td}'>{escape(str(x.get('picking', '')))}</td><td style='{td}'>{escape(str(x.get('usuario', '')))}</td>"
        f"<td style='{td}'>{escape(str(x.get('cuando', '')))}</td></tr>" for x in neg_nuevos[:40])
    html_n = f"""<div style='font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1e293b;max-width:860px'>
<p style='margin:0 0 10px'><b>{len(neg_nuevos)} caso(s) de stock negativo nuevo en zona de Entrada/Salida</b> detectados el
{fecha} (hora de Chile). Un negativo ahí significa que salió o se corrigió algo que el sistema no tenía: recepción
sin validar, picking validado antes de la entrada o corrección a medias. Revisar el picking indicado.</p>
<table cellspacing='0' style='border-collapse:collapse;font-size:13px'>
<tr style='background:#f1f5f9;font-weight:600'><td style='padding:4px 8px'>Producto</td><td style='padding:4px 8px'>Ubicación</td>
<td style='padding:4px 8px'>Cantidad</td><td style='padding:4px 8px'>Antes</td><td style='padding:4px 8px'>Picking</td>
<td style='padding:4px 8px'>Usuario</td><td style='padding:4px 8px'>Movimiento</td></tr>{filas_n}</table>
<p style='margin:12px 0 0;color:#94a3b8;font-size:12px'>Aviso automático del Pulso Alarmas Odoo. Solo incluye casos nuevos o que
empeoraron desde la corrida anterior; el acumulado histórico se trata aparte.</p></div>"""
    m2 = EmailMessage()
    m2["To"] = neg_to
    m2["Cc"] = "andres@unionx.cl"
    m2["From"] = "andres@unionx.cl"
    m2["Subject"] = f"🔴 Stock negativo nuevo en Entrada/Salida · {hora_chile().strftime('%d-%m')} · {len(neg_nuevos)} caso(s)"
    m2.set_content("Stock negativo nuevo en Entrada/Salida (ver versión HTML).")
    m2.add_alternative(html_n, subtype="html")
    r2 = svc.users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(m2.as_bytes()).decode()}).execute()
    print(f"Enviado a bodega: {r2['id']}")
