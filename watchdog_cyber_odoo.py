# -*- coding: utf-8 -*-
"""Vigía Cyber — revisa Odoo, Yuju y Shopify cada 5 minutos durante el Cyber oct-2026.

Por qué existe:
  · Cyber jun-26, jue 4-jun 14:47 → 23:45 CLT: no entró NINGÚN pedido de Yuju a Odoo durante
    9 horas, con Odoo arriba. Los pedidos pagados en esa ventana entraron tarde: parte a las
    23:45 y el resto recién el 5-jun a las 15:32. Nadie lo vio a tiempo.
  · 17→22-sep-26: una reconstrucción de Odoo.sh dejó apagado el envío de stock a Yuju 5 días.
  Este vigía acusa ese tipo de falla en 10-15 minutos.

Niveles (según cuánto afecta a la operación):
  🔴 EMERGENCIA — no se puede operar: no entran las ventas o bodega no puede preparar.
  🟠 URGENTE    — se opera, pero el daño crece cada hora (sobreventa, despachos o boletas atrasados).
  🟡 ATENCIÓN   — señal temprana o degradación sin impacto inmediato.
Cada aviso trae su impacto y un plan de acción (PLANES).

Chequeos (solo lectura, ~20 consultas livianas por ciclo):
  1. Odoo responde: página de ingreso + una lectura mínima por RPC (latencia).
  2. Crons críticos apagados, atrasados (> 2× su intervalo, mín 10 min) o con fallas; crons en
     general atrasados > 15 min (los procesos de cron no dan abasto); corridas de > 15 min.
  3. Pedidos Yuju por marketplace: silencio más largo que lo tolerado (calibrado con jun-26).
  4. Shopify Directo: eventos sin procesar, con error, rescatados por reconciliación, silencio.
  5. Pedidos trabados: Yuju sin confirmar o confirmados sin despacho; despachos en borrador.
  6. Stock a marketplaces (Yuju): flag, bodega, endpoint, webhooks vs movimientos; módulos
     de Odoo actualizados (posible despliegue en Odoo.sh).
  7. DTE: documentos sin enviar al SII (antigüedad), rechazos y folios disponibles (CAF) de
     boletas, facturas y notas de crédito según el consumo de las últimas 24 h.
  8. Correo saliente: cola atrasada y fallas.

Avisos por correo (Gmail API), pensados para no hacer spam:
  · 🔴 y 🟠: aviso inmediato al aparecer o al subir de nivel; recordatorio (emergencia cada 15 min,
    urgente cada 60) y aviso cuando se resuelve.
  · 🟡: sin correo propio; solo aparece en el resumen de las 08:30 y 20:30 CLT (si el resumen no
    llega, el vigía está caído).
  · El estado se guarda entre relevos (archivo .vigia_estado.json, cache de Actions): lo ya avisado
    no se repite como nuevo en cada turno.
El repo es público: en GitHub Actions el log NO muestra cifras.

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
TURNO = timedelta(hours=5, minutes=30)
RESUMEN_HORAS = (8, 20)                      # resumen a las 08:30 y 20:30 CLT
EN_ACTIONS = bool(os.environ.get("GITHUB_ACTIONS"))
DESTINO = os.environ.get("WATCHDOG_EMAIL_TO") or "andres@unionx.cl"
DESTINO_N1 = os.environ.get("WATCHDOG_EMAIL_N1") or ""    # se suman solo en avisos de EMERGENCIA (abiertos o resueltos)

N1, N2, N3 = "EMERGENCIA", "URGENTE", "ATENCIÓN"
RANGO = {N1: 3, N2: 2, N3: 1}
ICONO = {N1: "🔴", N2: "🟠", N3: "🟡"}
COLOR = {N1: "#dc2626", N2: "#ea580c", N3: "#ca8a04"}
RECORDAR_MIN = {N1: 15, N2: 60}             # 🟡 no manda correo propio: va en el resumen
ESTADO_ARCHIVO = Path(os.environ.get("WATCHDOG_ESTADO") or ROOT / ".vigia_estado.json")
SIGNIFICADO = {
    N1: "no se puede operar: no entran las ventas o bodega no puede preparar. Actuar ya.",
    N2: "se opera, pero el daño crece cada hora (sobreventa, despachos o boletas atrasados). Actuar en menos de 1 hora.",
    N3: "señal temprana o degradación sin impacto inmediato. Revisar en el día.",
}
MIN = {"minutes": 1, "hours": 60, "days": 1440, "weeks": 10080, "months": 43200}

# ─── planes de acción: impacto + pasos, en orden ─────────────────────────────
_ESCALAR_YUJU = "Escalar a Yuju como urgente (Pablo / Juan José, hilo de soporte) con la hora del último pedido recibido."
_PAUSAR_SYNC = "Pausar las sincronizaciones de nuestras apps que leen Odoo (sync_stock, sync_comex, refresh_parquet…), con Claude."
PLANES = {
    "odoo_caido": ("No entran ventas de Yuju ni Shopify, bodega no puede preparar ni despachar y no salen boletas.", [
        "Confirmar entrando a Odoo desde el navegador.",
        "Avisar de inmediato a Martín: estado del servidor en Odoo.sh y reinicio si corresponde.",
        "Avisar a Gerardo: bodega pasa a modo manual.",
        "Cuando vuelva: confirmar que entran pedidos (llega el aviso «resuelto») y comparar los pedidos del lapso entre "
        "el panel de Yuju y Odoo.",
    ]),
    "odoo_lento": ("Bodega trabaja lento y los pedidos de Yuju y Shopify pueden fallar por tiempo de espera.", [
        "Avisar a Martín: revisar CPU, memoria y workers en el panel de Odoo.sh; subir workers si hace falta.",
        _PAUSAR_SYNC,
        "Si pasa de 30 s por consulta, tratarlo como Odoo caído.",
    ]),
    "silencio_total": ("Las ventas de los marketplaces no están entrando a Odoo: bodega no las ve y no se preparan.", [
        "Si también hay aviso de Odoo caído o lento, seguir primero ese plan.",
        "Revisar en el panel de Yuju si hay pedidos nuevos en los marketplaces y si muestra errores al enviarlos a Odoo.",
        "Verificar en Odoo que el usuario «Trinidad Alfaro» (credencial de Yuju) siga activo: si se archiva o cambia "
        "su clave, Yuju no puede crear pedidos.",
        _ESCALAR_YUJU,
        "Avisar a Gerardo (bodega) que hay ventas que todavía no aparecen en Odoo.",
        "Cuando se normalice: comparar los pedidos del lapso entre Yuju y Odoo (en junio parte llegó ~25 h tarde).",
    ]),
    "silencio_canal": ("Las ventas de ese marketplace no están entrando a Odoo.", [
        "Revisar en el panel de Yuju si el marketplace tiene pedidos nuevos y si su conexión está activa "
        "(credenciales, publicaciones pausadas).",
        "Si hay pedidos en Yuju que no llegan a Odoo: " + _ESCALAR_YUJU[0].lower() + _ESCALAR_YUJU[1:],
        "Si el marketplace no tiene ventas: avisar a Comercial (Nicole) por si hay un problema en el canal.",
    ]),
    "shopify_cola": ("Pedidos pagados de las tiendas web no están entrando a Odoo.", [
        "Revisar en Odoo la acción planificada «Shopify Directo: procesar cola de eventos»: activa y corriendo.",
        "Ver el error del evento más antiguo en Shopify Directo → eventos.",
        "Avisar a Martín.",
        "Avisar a Gerardo (bodega) si hay pedidos web que no se ven.",
    ]),
    "shopify_error": ("Esos pedidos web no entraron a Odoo, o entraron incompletos.", [
        "Revisar el error de los eventos listados en Shopify Directo → eventos.",
        "Avisar a Martín.",
    ]),
    "shopify_rescate": ("Los pedidos web entran igual, pero con hasta 30 min de atraso.", [
        "Avisar a Martín: revisar los webhooks de Shopify hacia Odoo.",
    ]),
    "shopify_silencio": ("Puede que las tiendas web no estén vendiendo o que sus pedidos no lleguen.", [
        "Revisar en Shopify si hay pedidos pagados recientes.",
        "Si hay pedidos en Shopify que no están en Odoo, avisar a Martín.",
    ]),
    "sin_despacho": ("Pedidos vendidos que bodega no ve: no se preparan.", [
        "Abrir los pedidos listados y revisar por qué no generaron orden de despacho.",
        "Si son varios, avisar a Martín.",
        "Pasar la lista a Gerardo (bodega) para que no se atrasen.",
    ]),
    "sin_confirmar": ("Sin confirmar no generan orden de despacho.", [
        "Revisar los pedidos: si están correctos, confirmarlos a mano.",
        "Si son muchos, avisar a Martín y a Yuju.",
    ]),
    "despachos_borrador": ("Bodega no ve esos despachos listos para preparar.", [
        "Revisar los despachos en borrador y confirmarlos si corresponde.",
    ]),
    "yuju_stock": ("El stock de los marketplaces deja de actualizarse: sobreventa, cancelaciones y penalizaciones.", [
        "Odoo → Yuju → Configuración: confirmar «Stock webhooks enabled» activo y Multi Stock Src = CA1/Stock "
        "(así se arregló el 22-sep).",
        "Revisar que la acción planificada «Yuju Send Stock Webhooks» esté activa.",
        "Cuando vuelva: reenviar el stock de los productos movidos durante la caída (yuju_webhook_stock_masivo.py, con Claude).",
        "Preguntar a Martín si hubo un despliegue.",
    ]),
    "yuju_endpoint": ("El stock puede salir duplicado o a una tienda equivocada.", [
        "Preguntar a Martín antes de tocar: puede ser un desarrollo suyo.",
    ]),
    "yuju_pendientes": ("Algunos productos no actualizaron su stock en los marketplaces.", [
        "Revisar el mensaje de error en Odoo → Yuju → registros de webhooks.",
        "Si se repite, avisar a Yuju.",
    ]),
    "despliegue": ("Un despliegue puede cambiar configuraciones (el del 17-sep apagó el envío de stock a Yuju 5 días).", [
        "Preguntar a Martín qué se desplegó.",
        "Confirmar en los próximos avisos que no aparezcan alertas de Yuju ni de Shopify.",
    ]),
    "cron": ("", [
        "En Odoo → Ajustes → Técnico → Acciones planificadas: abrir el cron y ver si está activo, cuándo corrió y si tiene errores.",
        "Si está apagado: preguntar a Martín si lo apagó él; si es emergencia o urgente y no responde en 15 min, reactivarlo.",
        "Si está activo pero atrasado: está trabado en una corrida o faltan procesos de cron → avisar a Martín.",
    ]),
    "crons_capacidad": ("Los procesos automáticos (stock, etiquetas, boletas) se atrasan.", [
        "Avisar a Martín: faltan procesos de cron o hay uno trabado.",
        _PAUSAR_SYNC,
    ]),
    "cron_largo": ("Puede bloquear registros y atrasar a los demás crons.", [
        "Si se repite, avisar a Martín.",
    ]),
    "dte_cola": ("Boletas y facturas sin enviar al SII. No detiene la venta, pero acumula riesgo con el SII.", [
        "Revisar que la acción planificada «Send document to SII» esté activa (el 11-ago quedó apagada 9 días).",
        "Revisar el documento más antiguo pendiente: uno solo sin XML bloquea todo el lote (pasó en agosto).",
        "Avisar a Yohana (facturación) y a Martín.",
    ]),
    "folios": ("Sin folios (CAF) no se pueden emitir más documentos de ese tipo: los pedidos quedan sin boleta o factura.", [
        "Pedir a Víctor que descargue un CAF nuevo en el SII y lo cargue en Odoo.",
        "Avisar a Yohana (facturación).",
    ]),
    "dte_rechazos": ("Documentos rechazados por el SII.", [
        "Revisar el motivo del rechazo en Odoo.",
        "Avisar a Yohana (facturación).",
    ]),
    "correo": ("No salen correos de Odoo (confirmaciones, avisos).", [
        "Revisar los errores en Odoo → Ajustes → Técnico → Correos.",
        "Si persiste, avisar a Martín.",
    ]),
    "vigia": ("Esa parte no se está vigilando.", [
        "Si dura más de 30 min, revisar el log del vigía en GitHub (con Claude).",
    ]),
    "vigia_clave": ("El vigía está ciego: no revisa nada.", [
        "Actualizar la clave de Odoo del vigía (secreto ANDRES_ODOO_PASSWORD en GitHub), con Claude.",
    ]),
}

# Crons que sostienen la venta y el despacho: id → (qué hace, nivel si se cae, qué se deja de poder hacer)
CRONS = {
    148: ("Shopify: cola de pedidos", N1, "Los pedidos de las tiendas web no entran a Odoo."),
    115: ("Yuju: stock a marketplaces", N2, "El stock de los marketplaces deja de actualizarse: riesgo de sobreventa."),
    150: ("Shopify: envío de stock", N2, "El stock de las tiendas web deja de actualizarse: riesgo de sobreventa."),
    153: ("Shopify: OS Blue Express", N2, "Pedidos web de Blue Express quedan sin orden de servicio automática."),
    158: ("Recíbelo: etiquetas LATAM Pass RM", N2, "Pedidos LATAM Pass de RM quedan sin etiqueta automática."),
    160: ("Blue Express: etiquetas LATAM Pass regiones", N2, "Pedidos LATAM Pass de regiones quedan sin etiqueta automática."),
    26: ("DTE: envío al SII", N2, "Boletas y facturas no se envían al SII."),
    116: ("Yuju: precios a marketplaces", N3, "Los cambios de precio no llegan a los marketplaces."),
    149: ("Shopify: reconciliar pedidos perdidos", N3, "Si se pierde un webhook de Shopify, ese pedido no se rescata."),
    151: ("Shopify: barrido de boletas", N3, "Pedidos web pueden quedar sin boleta."),
    152: ("Shopify: centinela sin pedidos", N3, "Se pierde la alerta propia de Shopify por falta de pedidos."),
    27: ("SII: consultas de estado", N3, "No se actualiza el estado SII de los documentos."),
    29: ("Reglas automáticas por tiempo", N3, "Las reglas automáticas de Odoo que corren por tiempo se detienen."),
    2: ("Cola de correos salientes", N3, "No salen correos de Odoo."),
    5: ("Correo entrante (fetchmail)", N3, "Odoo no lee los correos entrantes configurados."),
    157: ("Corrector 801", N3, "Facturas manuales quedan sin OC de cliente."),
    146: ("Corrector Factura 33", N3, "No se corrigen las facturas 33."),
}

# Yuju crea los pedidos con la credencial «Trinidad Alfaro»
YUJU_UID = 211
YUJU_ID_SHOP = "1090300"
# Silencio tolerado (min) sin pedidos Yuju, por marketplace, en horario activo → (minutos, nivel).
# Brecha máxima 08-24 h en el Cyber jun-26, días 1-3: total 14 min · ML 30 · Falabella 19 ·
# Paris 56 · Ripley 72 · Walmart 113. Días 4-7 (sin el incidente): total 22 · ML 28 · Falabella 95.
# Semana normal sep-26 (09-24 h): total 35 · ML 48.
SILENCIO = {
    "pico": {"(total)": (30, N1), "Mercado Libre Chile": (45, N1), "Falabella Chile": (45, N1),
             "Paris": (90, N2), "Mercado Ripley Chile": (150, N2), "Walmart Chile": (180, N2)},
    "cola": {"(total)": (45, N1), "Mercado Libre Chile": (60, N1), "Falabella Chile": (120, N2)},
    "normal": {"(total)": (75, N1), "Mercado Libre Chile": (90, N2)},
}
SILENCIO_NOCHE = {"pico": {"(total)": (90, N2)}}         # 00-08 h en días de evento
SHOPIFY_SILENCIO_PICO = 120                              # min sin pedidos pagados en las 3 tiendas
# Folios CAF vigilados: id de l10n_latam.document.type → nombre
FOLIOS = {5: "boletas (39)", 1: "facturas (33)", 3: "notas de crédito (61)"}


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
    """Hallazgo: clave estable (para seguirlo entre ciclos), nivel, título, detalle y plan de acción."""
    __slots__ = ("clave", "nivel", "titulo", "detalle", "plan", "impacto", "confirmar", "recordar", "origen")

    def __init__(self, clave, nivel, titulo, detalle, plan, impacto=None, confirmar=1, recordar=True):
        self.clave, self.nivel, self.titulo, self.detalle, self.plan = clave, nivel, titulo, detalle, plan
        self.impacto = impacto          # reemplaza el impacto genérico del plan (crons)
        self.confirmar = confirmar      # ciclos seguidos antes de avisar (evita falsas alarmas por un tropiezo)
        self.recordar = recordar        # False = avisar una vez (cambios de configuración, despliegues)
        self.origen = None


# ─── Odoo ────────────────────────────────────────────────────────────────────
class Odoo:
    def __init__(self):
        cfg = json.load(open(ROOT / "odoo/odoo_config.json", encoding="utf-8"))["produccion"]
        self.url, self.db, self.user = cfg["url"], cfg["db_name"], cfg["username"]
        # una API key de Odoo es más estable que la clave personal (si la clave cambia, el vigía queda ciego)
        self.pw = os.environ.get("WATCHDOG_ODOO_KEY") or os.environ.get("ANDRES_ODOO_PASSWORD", "")
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
            out.append(H("odoo_web", N1, f"Odoo responde error {r.status_code}",
                         "La página de ingreso de Odoo devuelve error de servidor.", "odoo_caido", confirmar=2))
    except Exception as e:
        out.append(H("odoo_web", N1, "La página de Odoo no responde",
                     f"{type(e).__name__}: {str(e)[:150]}", "odoo_caido", confirmar=2))
    t = time.time()
    if not od.uid:
        od.login()
    od.ex("res.users", "read", [od.uid], fields=["id"], timeout=45)
    met["rpc_s"] = lat = time.time() - t
    if lat > 30:
        out.append(H("odoo_lento", N1, f"Odoo muy lento: {lat:.0f} s para una lectura mínima",
                     "Lo normal es ~1 s.", "odoo_lento", confirmar=2))
    elif lat > 10:
        out.append(H("odoo_lento", N2, f"Odoo lento: {lat:.0f} s para una lectura mínima",
                     "Lo normal es ~1 s. Señal temprana de saturación de workers.", "odoo_lento", confirmar=2))
    return out


def chk_crons(od, ahora, met):
    out = []
    cs = od.ex("ir.cron", "read", list(CRONS),
               fields=["name", "active", "nextcall", "interval_number", "interval_type",
                       "failure_count", "first_failure_date"], context={"active_test": False})
    for cid in set(CRONS) - {c["id"] for c in cs}:
        desc, nivel, impacto = CRONS[cid]
        out.append(H(f"cron{cid}", nivel, f"No existe el cron «{desc}»", f"id {cid}: ¿fue eliminado?", "cron", impacto))
    for c in cs:
        desc, nivel, impacto = CRONS[c["id"]]
        if not c["active"]:
            out.append(H(f"cron{c['id']}", nivel, f"Cron apagado: {desc}",
                         f"«{c['name']}» (id {c['id']}) está inactivo.", "cron", impacto))
            continue
        cada = c["interval_number"] * MIN.get(c["interval_type"], 1)
        atraso = minutos(de_odoo(c["nextcall"]), ahora)
        if atraso > max(2 * cada, 10):
            out.append(H(f"cron{c['id']}", nivel, f"Cron atrasado: {desc}",
                         f"«{c['name']}» le tocaba a las {hora(de_odoo(c['nextcall']))} (hace {fmt_min(atraso)}) "
                         f"y corre cada {fmt_min(cada)}.", "cron", impacto))
        if c["failure_count"] >= 3:        # 1-2 fallas sueltas se recuperan solas (ej. tanda grande del Full)
            desde = de_odoo(c["first_failure_date"])
            out.append(H(f"cron{c['id']}_falla", nivel, f"Cron con errores: {desc}",
                         f"«{c['name']}»: {c['failure_count']} corridas seguidas con error"
                         + (f" desde el {fecha_hora(desde)}" if desde else "") + ". Odoo lo apaga solo si sigue fallando.",
                         "cron", impacto))
    # crons en general: si varios se atrasan a la vez, los procesos de cron no dan abasto
    tarde = od.ex("ir.cron", "search_read", [("active", "=", True), ("nextcall", "<", ts(ahora - timedelta(minutes=15)))],
                  fields=["name", "nextcall"], limit=50)
    met["crons_atrasados"] = len(tarde)
    muy = [c for c in tarde if de_odoo(c["nextcall"]) < ahora - timedelta(minutes=45)]
    lista = "; ".join(f"{c['name'][:45]} (desde {hora(de_odoo(c['nextcall']))})" for c in tarde[:6])
    if len(muy) >= 3:
        out.append(H("crons_capacidad", N2, f"{len(muy)} crons atrasados más de 45 min",
                     f"Los procesos de cron no dan abasto: {lista}.", "crons_capacidad"))
    elif len(tarde) >= 3:
        out.append(H("crons_capacidad", N3, f"{len(tarde)} crons atrasados más de 15 min",
                     f"Primera señal de saturación de los procesos de cron: {lista}.", "crons_capacidad"))
    # carga de la última hora y corridas largas
    prog = od.ex("ir.cron.progress", "search_read", [("create_date", ">=", ts(ahora - timedelta(minutes=60)))],
                 fields=["cron_id", "create_date", "write_date"], limit=5000)
    dur = [((de_odoo(p["write_date"]) - de_odoo(p["create_date"])).total_seconds(), p) for p in prog]
    met["cron_min_1h"] = sum(d for d, _ in dur) / 60
    largos = {}
    for d, p in dur:
        if d > 900 and p["cron_id"]:
            largos[p["cron_id"][0]] = max(largos.get(p["cron_id"][0], (0, ""))[0], d), p["cron_id"][1]
    for cid, (d, nombre) in largos.items():
        out.append(H(f"cron_largo{cid}", N3, f"Corrida de cron de {fmt_min(d / 60)}: {nombre[:60]}",
                     "Lo normal es menos de 6 min.", "cron_largo", recordar=False))
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
            total = canal == "(total)"
            nombre = "Yuju (ningún marketplace)" if total else canal
            ultimo = (f"Último pedido a las {hora(ult[canal])}" if ult.get(canal)
                      else "Ningún pedido en las últimas 4 h")
            out.append(H(f"silencio:{canal}", nivel, f"Sin pedidos de {nombre} hace {fmt_min(sil)}",
                         f"{ultimo}. Tolerancia {umbral} min (día {tipo}).",
                         "silencio_total" if total else "silencio_canal"))
    return out


def chk_shopify(od, ahora, met):
    out = []
    trab = od.ex("shopify.webhook.event", "search_read",
                 [("state", "=", "received"), ("create_date", "<", ts(ahora - timedelta(minutes=15)))],
                 fields=["shopify_order_name", "topic", "create_date", "store_id"], order="create_date asc", limit=20)
    if trab:
        x = trab[0]
        out.append(H("shopify_cola", N1, f"{len(trab)}{'+' if len(trab) == 20 else ''} eventos de Shopify sin procesar hace más de 15 min",
                     f"El más antiguo: {x['topic']} {x['shopify_order_name'] or ''} "
                     f"({x['store_id'][1] if x['store_id'] else '?'}), recibido a las {hora(de_odoo(x['create_date']))}. "
                     f"Lo normal es que se procesen en menos de 5 min.", "shopify_cola"))
    err = od.ex("shopify.webhook.event", "search_read",
                [("state", "=", "error"), ("create_date", ">=", ts(ahora - timedelta(hours=2)))],
                fields=["shopify_order_name", "store_id", "error"], limit=20)
    if err:
        nombres = ", ".join(sorted({x["shopify_order_name"] or "?" for x in err}))[:200]
        out.append(H("shopify_error", N2 if len(err) >= 5 else N3, f"{len(err)} eventos de Shopify con error (2 h)",
                     f"Pedidos: {nombres}. Primer error: {(err[0]['error'] or '')[:180]}", "shopify_error"))
    resc = od.ex("shopify.webhook.event", "search_count",
                 [("source", "=", "reconcile"), ("create_date", ">=", ts(ahora - timedelta(minutes=60)))])
    if resc >= 3:
        out.append(H("shopify_rescate", N3, f"{resc} pedidos de Shopify entraron por reconciliación (1 h)",
                     "Los webhooks de Shopify no están llegando a Odoo.", "shopify_rescate"))
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
            out.append(H("silencio:shopify", N2, f"Sin pedidos pagados de Shopify hace {fmt_min(sil)}",
                         "Ninguna de las 3 tiendas (UnionX, Lhotse, Simplit). En el Cyber de junio la brecha más larga "
                         "fue 51 min.", "shopify_silencio"))
    return out


def chk_flujo(od, ahora, met):
    out = []
    d3, m30 = ts(ahora - timedelta(days=3)), ts(ahora - timedelta(minutes=30))
    sinp = od.ex("sale.order", "search_read",
                 [("create_uid", "=", YUJU_UID), ("state", "=", "sale"), ("picking_ids", "=", False),
                  ("create_date", ">=", d3), ("create_date", "<", m30)], fields=["name"], limit=50)
    if sinp:
        out.append(H("yuju_sin_despacho", N1 if len(sinp) >= 5 else N2,
                     f"{len(sinp)} pedidos Yuju confirmados sin orden de despacho",
                     f"{', '.join(x['name'] for x in sinp[:10])}.", "sin_despacho"))
    borr = od.ex("sale.order", "search_read",
                 [("create_uid", "=", YUJU_UID), ("state", "in", ["draft", "sent"]),
                  ("create_date", ">=", d3), ("create_date", "<", m30)], fields=["name"], limit=50)
    if borr:
        out.append(H("yuju_sin_confirmar", N2 if len(borr) >= 10 else N3,
                     f"{len(borr)} pedidos Yuju sin confirmar hace más de 30 min",
                     f"{', '.join(x['name'] for x in borr[:10])}.", "sin_confirmar"))
    pick = od.ex("stock.picking", "search_count",
                 [("picking_type_code", "=", "outgoing"), ("state", "=", "draft"),
                  ("create_date", ">=", d3), ("create_date", "<", m30)])
    if pick >= 5:
        out.append(H("despachos_borrador", N3, f"{pick} despachos en borrador hace más de 30 min",
                     "Normalmente se confirman solos al confirmar el pedido.", "despachos_borrador"))
    return out


def chk_yuju_stock(od, ahora, met):
    out = []
    cfg = od.ex("madkting.config", "search_read", [],
                fields=["webhook_stock_enabled", "stock_source_multi", "write_date", "write_uid"])
    if not cfg:
        return [H("yuju_config", N2, "Yuju: no existe la configuración (madkting.config)",
                  "El módulo no puede enviar stock a los marketplaces.", "yuju_stock")]
    c = cfg[0]
    if not c["webhook_stock_enabled"]:
        out.append(H("yuju_flag", N2, "Yuju: el envío de stock a marketplaces está APAGADO",
                     "«Stock webhooks enabled» en False (misma causa del congelamiento 17→22-sep).", "yuju_stock"))
    if not c["stock_source_multi"]:
        out.append(H("yuju_bodega", N2, "Yuju: sin bodega de origen del stock (Multi Stock Src vacío)",
                     "Desde la versión 2.8.x el envío lo exige.", "yuju_stock"))
    if de_odoo(c["write_date"]) > ahora - timedelta(hours=24):
        out.append(H("yuju_config_cambio", N3, "Yuju: alguien cambió la configuración",
                     f"{fecha_hora(de_odoo(c['write_date']))} por {c['write_uid'][1] if c['write_uid'] else '?'}.",
                     "despliegue", recordar=False))
    hooks = od.ex("madkting.webhook", "search_read", [("hook_type", "=", "stock")],
                  fields=["id", "active", "id_shop"], context={"active_test": False})
    act = [h for h in hooks if h["active"]]
    if len(act) != 1 or any(str(h["id_shop"] or "").strip() != YUJU_ID_SHOP for h in act):
        det = "; ".join(f"id {h['id']} shop={h['id_shop']} {'activo' if h['active'] else 'inactivo'}" for h in hooks) or "ninguno"
        out.append(H("yuju_endpoint", N3, "Yuju: endpoints de stock anómalos",
                     f"Se espera 1 activo con id_shop {YUJU_ID_SHOP}: {det}.", "yuju_endpoint"))
    m30 = ts(ahora - timedelta(minutes=30))
    mov = od.ex("stock.move", "search_count",
                [("state", "=", "done"), ("date", ">=", m30), ("product_id.id_product_madkting", "!=", False)])
    wh = od.ex("yuju.webhook.record", "search_count", [("event", "=", "stock_update"), ("create_date", ">=", m30)])
    # de noche y en fin de semana bodega no valida: los pedidos nuevos también mueven el stock
    # disponible (4-oct: 14 de 15 ventanas de 30 min con pedidos tuvieron envío)
    ped = od.ex("sale.order", "search_count", [("create_uid", "=", YUJU_UID), ("create_date", ">=", m30)])
    met["yuju_mov_30"], met["yuju_wh_30"], met["yuju_ped_30"] = mov, wh, ped
    if (mov >= 10 or ped >= 3) and wh == 0:
        out.append(H("yuju_stock_congelado", N2, "Yuju: el stock de los marketplaces no se está actualizando",
                     f"En 30 min: {ped} pedidos Yuju nuevos y {mov} movimientos validados de productos publicados, "
                     f"y ningún envío de stock a Yuju.", "yuju_stock", confirmar=2))
    pend = od.ex("yuju.webhook.record", "search_count",
                 [("state", "!=", "done"), ("create_date", ">=", ts(ahora - timedelta(hours=2))),
                  ("create_date", "<", ts(ahora - timedelta(minutes=15)))])
    if pend:
        out.append(H("yuju_wh_pendientes", N3, f"Yuju: {pend} envíos de stock sin confirmar (2 h)",
                     "Quedaron en borrador o con error: Yuju no los recibió.", "yuju_pendientes"))
    mods = od.ex("ir.module.module", "search_read",
                 [("state", "=", "installed"), ("write_date", ">=", ts(ahora - timedelta(minutes=60)))],
                 fields=["name"], limit=30)
    if mods:
        out.append(H("odoo_modulos", N3, f"Se actualizaron {len(mods)} módulos de Odoo en la última hora",
                     f"Posible despliegue en Odoo.sh: {', '.join(m['name'] for m in mods[:12])}.", "despliegue",
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
            out.append(H("dte_cola", N2 if edad > 240 else N3, f"{n} documentos sin enviar al SII; el más antiguo hace {fmt_min(edad)}",
                         f"{viejo['name']}, creado a las {hora(de_odoo(viejo['create_date']))}. El envío corre cada 15 min: "
                         f"la cola no está bajando.", "dte_cola"))
    rech = od.ex("account.move", "search_count",
                 [("l10n_cl_dte_status", "=", "rejected"), ("create_date", ">=", ts(ahora - timedelta(hours=6)))])
    if rech >= 10:
        out.append(H("dte_rechazos", N3, f"{rech} documentos rechazados por el SII (6 h)", "", "dte_rechazos"))
    out += _folios(od, ahora, met)
    return out


def _folios(od, ahora, met):
    """Folios CAF que quedan por tipo de documento, comparados con el consumo de las últimas 24 h."""
    out = []
    tipos = list(FOLIOS)
    cafs = od.ex("l10n_cl.dte.caf", "search_read", [("l10n_latam_document_type_id", "in", tipos)],
                 fields=["l10n_latam_document_type_id", "start_nb", "final_nb"])
    # solo documentos emitidos por nosotros: las compras usan los mismos tipos con el folio del proveedor
    base = [("l10n_latam_document_type_id", "in", tipos), ("state", "=", "posted"),
            ("move_type", "in", ["out_invoice", "out_refund"]), ("create_date", ">=", ts(ahora - timedelta(days=30)))]
    ult = {x["l10n_latam_document_type_id"][0]: x["sequence_number"] for x in
           od.ex("account.move", "read_group", base, ["sequence_number:max"], ["l10n_latam_document_type_id"], lazy=False)}
    uso = {x["l10n_latam_document_type_id"][0]: x["__count"] for x in
           od.ex("account.move", "read_group", base[:3] + [("create_date", ">=", ts(ahora - timedelta(hours=24)))],
                 ["id:count"], ["l10n_latam_document_type_id"], lazy=False)}
    met["folios"] = {}
    for tid, nombre in FOLIOS.items():
        last = ult.get(tid)
        if not last:
            continue
        quedan = sum(c["final_nb"] - max(c["start_nb"] - 1, last) for c in cafs
                     if c["l10n_latam_document_type_id"][0] == tid and c["final_nb"] > last)
        dia = uso.get(tid, 0)
        met["folios"][nombre] = (quedan, dia)
        dias = quedan / dia if dia else None
        txt = (f"Quedan {quedan:,} folios de {nombre}; en las últimas 24 h se emitieron {dia:,}"
               + (f" (alcanzan para ~{fmt_min(dias * 1440)})." if dias is not None else ".")).replace(",", ".")
        if quedan < 500 or (dias is not None and dias < 0.2):
            out.append(H(f"folios{tid}", N1, f"Se están acabando los folios de {nombre}", txt, "folios"))
        elif quedan < 2000 or (dias is not None and dias < 1.5):
            out.append(H(f"folios{tid}", N2, f"Quedan pocos folios de {nombre}", txt, "folios"))
        elif dias is not None and dias < 4:
            out.append(H(f"folios{tid}", N3, f"Folios de {nombre} para menos de 4 días", txt, "folios"))
    return out


def chk_correo(od, ahora, met):
    out = []
    met["correo_cola"] = n = od.ex("mail.mail", "search_count", [("state", "=", "outgoing")])
    if n:
        viejo = od.ex("mail.mail", "search_read", [("state", "=", "outgoing")], fields=["create_date"],
                      order="create_date asc", limit=1)[0]
        edad = minutos(de_odoo(viejo["create_date"]), ahora)
        if edad > 30:
            out.append(H("correo_cola", N3, f"{n} correos en cola; el más antiguo hace {fmt_min(edad)}",
                         "La cola de correos salientes no está saliendo.", "correo"))
    exc = od.ex("mail.mail", "search_count",
                [("state", "=", "exception"), ("create_date", ">=", ts(ahora - timedelta(minutes=60))),
                 ("subject", "not ilike", "Acknowledgment")])
    if exc >= 20:
        out.append(H("correo_fallas", N3, f"{exc} correos fallidos en la última hora", "", "correo"))
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
        h = H("vigia_acceso", N2, "El vigía no puede entrar a Odoo", str(e), "vigia_clave")
        h.origen = "Vigía"
        return [h], {n for n, _ in CHEQUEOS}, met
    except Exception as e:
        h = H("odoo_rpc", N1, "Odoo no responde a consultas", f"{type(e).__name__}: {str(e)[:200]}",
              "odoo_caido", confirmar=2)
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
            h = H(f"chequeo:{nombre}", N3, f"El vigía no pudo revisar: {nombre}",
                  f"{type(e).__name__}: {str(e)[:200]}", "vigia", confirmar=3)
            h.origen = "Vigía"
            hall.append(h)
        met["t"][nombre] = time.time() - t
    met["ciclo_s"] = time.time() - t0
    return hall, fallidos, met


# ─── seguimiento entre ciclos ────────────────────────────────────────────────
class Estado:
    """Problemas abiertos entre ciclos. Se guarda en disco para sobrevivir al relevo de turno."""

    def __init__(self):
        self.abiertos = {}      # clave → {"h", "desde", "veces", "avisado", "nivel_avisado"}
        self.resumenes = set()  # "AAAA-MM-DD HH" (CLT) de los resúmenes ya enviados

    def actualizar(self, hallazgos, fallidos, ahora):
        nuevos, recordar, resueltos, vistos = [], [], [], set()
        for h in hallazgos:
            if h.clave in vistos:
                continue
            vistos.add(h.clave)
            a = self.abiertos.setdefault(h.clave, {"desde": ahora, "veces": 0, "avisado": None, "nivel_avisado": None})
            a["h"] = h
            a["veces"] += 1
            if a["veces"] < h.confirmar or h.nivel == N3:
                continue        # 🟡 no manda correo propio: queda para el resumen
            if a["avisado"] is None or RANGO[h.nivel] > RANGO[a["nivel_avisado"]]:
                nuevos.append(a)
            elif h.recordar and ahora - a["avisado"] >= timedelta(minutes=RECORDAR_MIN[h.nivel]):
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

    def vigentes(self):
        """Lo abierto y confirmado (incluye 🟡), del más grave al más leve: para el resumen."""
        return sorted((a for a in self.abiertos.values() if a["veces"] >= a["h"].confirmar),
                      key=lambda a: -RANGO[a["h"].nivel])

    def guardar(self, archivo=ESTADO_ARCHIVO):
        def iso(t):
            return t.isoformat() if t else None
        datos = {"resumenes": sorted(self.resumenes)[-6:], "abiertos": {
            k: {"nivel": a["h"].nivel, "titulo": a["h"].titulo, "detalle": a["h"].detalle, "plan": a["h"].plan,
                "impacto": a["h"].impacto, "origen": a["h"].origen, "confirmar": a["h"].confirmar,
                "recordar": a["h"].recordar, "desde": iso(a["desde"]), "veces": a["veces"],
                "avisado": iso(a["avisado"]), "nivel_avisado": a["nivel_avisado"]}
            for k, a in self.abiertos.items()}}
        archivo.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def cargar(cls, archivo=ESTADO_ARCHIVO):
        e = cls()
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
        except Exception:
            return e            # primer turno, o archivo ilegible: parte de cero
        e.resumenes = set(datos.get("resumenes", []))
        for k, d in datos.get("abiertos", {}).items():
            h = H(k, d["nivel"], d["titulo"], d["detalle"], d["plan"] if d["plan"] in PLANES else "vigia",
                  d.get("impacto"), d.get("confirmar", 1), d.get("recordar", True))
            h.origen = d.get("origen")
            e.abiertos[k] = {"h": h, "desde": datetime.fromisoformat(d["desde"]), "veces": d["veces"],
                             "avisado": datetime.fromisoformat(d["avisado"]) if d["avisado"] else None,
                             "nivel_avisado": d["nivel_avisado"]}
        return e


# ─── correo ──────────────────────────────────────────────────────────────────
_gmail = None


def enviar(asunto, html, extra=""):
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
    msg["To"], msg["From"], msg["Subject"] = ", ".join(x for x in (DESTINO, extra) if x), "andres@unionx.cl", asunto
    msg.set_content("Vigía Cyber Odoo (ver versión HTML).")
    msg.add_alternative(html, subtype="html")
    _gmail.users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}).execute()


def _item(a, ahora, resuelto=False, con_plan=True):
    h = a["h"]
    color = "#16a34a" if resuelto else COLOR[h.nivel]
    etiqueta = "RESUELTO" if resuelto else f"{ICONO[h.nivel]} {h.nivel}"
    dur = f"abierto desde las {hora(a['desde'])} ({fmt_min(minutos(a['desde'], ahora))})"
    html = (f"<div style='border-left:4px solid {color};padding:8px 12px;margin:0 0 12px;background:#f8fafc'>"
            f"<span style='color:{color};font-weight:700;font-size:12px'>{etiqueta}</span> · "
            f"<span style='color:#64748b;font-size:12px'>{escape(h.origen or '')} · {dur}</span><br>"
            f"<b>{escape(h.titulo)}</b>"
            + (f"<br><span style='color:#334155'>{escape(h.detalle)}</span>" if h.detalle else ""))
    if con_plan and not resuelto:
        impacto, pasos = PLANES[h.plan]
        impacto = h.impacto or impacto
        if impacto:
            html += f"<div style='margin-top:6px'><b>Impacto:</b> {escape(impacto)}</div>"
        html += ("<div style='margin-top:4px'><b>Qué hacer:</b><ol style='margin:2px 0 0;padding-left:20px'>"
                 + "".join(f"<li style='margin:2px 0'>{escape(p)}</li>" for p in pasos) + "</ol></div>")
    return html + "</div>"


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
        fila("Stock a Yuju (30 min)", f"{met.get('yuju_wh_30', '?')} envíos · {met.get('yuju_ped_30', '?')} pedidos nuevos · "
                                      f"{met.get('yuju_mov_30', '?')} movimientos validados"),
        fila("Crons", f"{met.get('crons_atrasados', '?')} atrasados > 15 min · {met.get('cron_min_1h', 0):.0f} min de cron en la última hora"),
        fila("DTE sin enviar al SII", f"{met.get('dte_pend', '?')}" + (f" · más antiguo {fmt_min(met['dte_edad_min'])}" if met.get("dte_edad_min") else "")),
        fila("Folios disponibles", " · ".join(f"{k}: {q:,} (24 h: {d:,})".replace(",", ".") for k, (q, d) in met.get("folios", {}).items()) or "?"),
        fila("Correos en cola", f"{met.get('correo_cola', '?')}"),
        fila("Fase", met.get("fase", "?")),
    ]
    if picos:
        filas.append(fila("Peor valor desde el último resumen",
                          f"lectura mínima {picos.get('rpc_s', 0):.1f} s · crons atrasados {picos.get('crons_atrasados', 0)} · "
                          f"DTE sin enviar {picos.get('dte_pend', 0)} · ciclo más largo {picos.get('ciclo_s', 0):.0f} s"))
    return f"<table style='font-size:13px;border-collapse:collapse;margin-top:6px'>{''.join(filas)}</table>"


def _leyenda():
    return ("<p style='color:#64748b;font-size:12px;margin-top:16px;line-height:1.5'><b>Niveles</b><br>"
            + "<br>".join(f"{ICONO[n]} <b>{n}</b>: {escape(SIGNIFICADO[n])}" for n in (N1, N2, N3)) + "</p>")


def _envoltorio(titulo, cuerpo, ahora):
    return (f"<div style='font-family:Segoe UI,Arial,sans-serif;max-width:720px;color:#0f172a'>"
            f"<h3 style='margin:0 0 4px'>{escape(titulo)}</h3>"
            f"<p style='margin:0 0 14px;color:#64748b;font-size:12px'>{ahora.astimezone(CLT):%d-%m-%Y %H:%M} CLT · "
            f"revisión cada 5 min de Odoo, Yuju y Shopify</p>{cuerpo}{_leyenda()}</div>")


def correo_alerta(nuevos, recordar, resueltos, met, ahora):
    abiertos = sorted(nuevos + recordar, key=lambda a: -RANGO[a["h"].nivel])
    if abiertos:
        principal = abiertos[0]["h"]
        extra = len(abiertos) - 1
        asunto = f"{ICONO[principal.nivel]} {principal.nivel} · {principal.titulo}" + (f" (+{extra})" if extra else "")
    else:
        asunto = f"✅ Resuelto · {resueltos[0]['h'].titulo}" + (f" (+{len(resueltos) - 1})" if len(resueltos) > 1 else "")
    asunto = f"Vigía Cyber · {asunto}"
    cuerpo = ""
    if nuevos:
        cuerpo += "<h4 style='margin:10px 0 6px'>Nuevo</h4>" + "".join(
            _item(a, ahora) for a in sorted(nuevos, key=lambda a: -RANGO[a["h"].nivel]))
    if recordar:
        cuerpo += "<h4 style='margin:10px 0 6px'>Sigue abierto</h4>" + "".join(
            _item(a, ahora) for a in sorted(recordar, key=lambda a: -RANGO[a["h"].nivel]))
    if resueltos:
        cuerpo += "<h4 style='margin:10px 0 6px'>Resuelto</h4>" + "".join(_item(a, ahora, True) for a in resueltos)
    cuerpo += "<h4 style='margin:14px 0 2px'>Estado ahora</h4>" + _metricas(met)
    return asunto, _envoltorio(asunto, cuerpo, ahora)


def correo_resumen(estado, met, picos, ahora, prueba=False):
    abiertos = estado.vigentes() if estado else []
    icono = ICONO[abiertos[0]["h"].nivel] if abiertos else "🟢"
    etiqueta = "PRUEBA" if prueba else f"resumen {ahora.astimezone(CLT):%H:%M}"
    asunto = f"Vigía Cyber · {icono} {etiqueta} · " + (f"{len(abiertos)} problemas abiertos" if abiertos else "todo en orden")
    cuerpo = ("".join(_item(a, ahora) for a in abiertos) if abiertos
              else "<p style='margin:0 0 6px'>Sin problemas abiertos.</p>")
    cuerpo += "<h4 style='margin:14px 0 2px'>Estado ahora</h4>" + _metricas(met, picos)
    cuerpo += ("<p style='color:#64748b;font-size:12px;margin-top:14px'>Este resumen llega a las 08:30 y 20:30. "
               "Si no llega, el vigía está caído. Los avisos 🟡 solo aparecen aquí; 🔴 y 🟠 llegan al momento.</p>")
    return asunto, _envoltorio(asunto, cuerpo, ahora)


# ─── ejecución ───────────────────────────────────────────────────────────────
def imprimir_detalle(hall, fallidos, met):
    print(f"\nFase: {met.get('fase', '?')} · ciclo {met.get('ciclo_s', 0):.1f} s")
    print("Tiempo por chequeo: " + " · ".join(f"{k} {v:.1f}s" for k, v in met["t"].items()))
    if fallidos:
        print(f"No revisados: {', '.join(sorted(fallidos))}")
    if not hall:
        print("\n✅ Sin hallazgos.")
    for h in sorted(hall, key=lambda h: -RANGO[h.nivel]):
        conf = f" (avisa al {h.confirmar}° ciclo seguido)" if h.confirmar > 1 else ""
        impacto, pasos = PLANES[h.plan]
        print(f"\n{ICONO[h.nivel]} [{h.nivel}] {h.origen}: {h.titulo}{conf}\n    {h.detalle}")
        print(f"    Impacto: {h.impacto or impacto}")
        for i, p in enumerate(pasos, 1):
            print(f"    {i}. {p}")
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
            print(f"[vigía] ciclo de prueba: " + " · ".join(f"{sum(h.nivel == n for h in hall)} {n.lower()}" for n in (N1, N2, N3))
                  + f" · {met.get('ciclo_s', 0):.0f} s")
        else:
            imprimir_detalle(hall, fallidos, met)
        if a.prueba or a.enviar:
            est = Estado()
            est.actualizar([h for h in hall if h.confirmar == 1], fallidos, ahora)
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
    estado, picos, n = Estado.cargar(), {}, 0      # el estado viene del turno anterior (cache de Actions)
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
            # el log de Actions es público: solo conteos de problemas por nivel, nunca cifras del negocio
            abiertos = list(estado.abiertos.values())
            print(f"[{hora(ahora)} CLT] ciclo {n}: "
                  + " · ".join(f"{sum(x['h'].nivel == nv for x in abiertos)} {nv.lower()}" for nv in (N1, N2, N3))
                  + f" · {len(nuevos)} nuevos · {len(resueltos)} resueltos · {met.get('ciclo_s', 0):.0f} s", flush=True)
            if nuevos or recordar or resueltos:
                n1 = any(x["h"].nivel == N1 for x in nuevos + recordar) or any(x["nivel_avisado"] == N1 for x in resueltos)
                try:
                    enviar(*correo_alerta(nuevos, recordar, resueltos, met, ahora), extra=DESTINO_N1 if n1 else "")
                    estado.marcar(nuevos + recordar, ahora)
                except Exception as e:      # se reintenta en el próximo ciclo
                    print(f"[vigía] no se pudo enviar el aviso: {type(e).__name__}", flush=True)
            local = ahora.astimezone(CLT)
            slot = f"{local:%Y-%m-%d %H}"
            if local.hour in RESUMEN_HORAS and local.minute >= 30 and slot not in estado.resumenes:
                try:
                    enviar(*correo_resumen(estado, met, picos, ahora))
                    estado.resumenes.add(slot)
                    picos = {}
                except Exception as e:
                    print(f"[vigía] no se pudo enviar el resumen: {type(e).__name__}", flush=True)
            try:
                estado.guardar()
            except Exception as e:
                print(f"[vigía] no se pudo guardar el estado: {type(e).__name__}", flush=True)
        prox = ahora_utc()
        prox = prox.replace(second=0, microsecond=0) + timedelta(minutes=5 - prox.minute % 5)
        time.sleep(max((prox - ahora_utc()).total_seconds(), 1))
    print("[vigía] fin del turno: relevo", flush=True)
    subprocess.run(["gh", "workflow", "run", "watchdog_cyber.yml"], check=False)


if __name__ == "__main__":
    main()
