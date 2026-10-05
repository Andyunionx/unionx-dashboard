# -*- coding: utf-8 -*-
"""Reglas de emisión de NC por devolución — fuente única para el agente y el pulso.

Las usan `agente_tickets_nc.py` (emite) y `pulso_nc_semanal.py` (informa), para que
los dos midan exactamente lo mismo.

Reglas (Max, correo 17-sep-2026, confirmadas 22-sep; complemento de Andrés 05-oct):
  1. Solo tickets con Motivo «Devolución». Los de canales manuales quedan con motivo
     «Cambio» mientras Max no los confirma; al confirmarse pasan a «Devolución» y
     quedan disponibles para emitir la NC.
  2. Resolución vacía → ticket creado automáticamente que nadie revisó → fuera.
  3. Se emiten a mano (no los toca el agente): Fidelización, Distribución, páginas
     propias (UnionX, Lhotse, Simplit y UnionX B2B) y Kitchen Center.
  4. «PV» + número de orden de compra en el título → proceso manual de Postventa
     (transitorio: va a desaparecer a medida que Retorna y los canales se automaticen).
  5. Se mantiene del flujo anterior: el producto tiene que estar recepcionado
     (Estado Nuevo / Outlet / Merma).
  Max, 05-oct: en automático quedan SOLO los marketplaces de CANALES_AUTOMATICOS; cualquier
  otro canal (Ventas Emilio, Hites, El Volcán, Abcdin, etc.) es manual por ahora. Se emiten
  todas las resoluciones no vacías, incluidas las «Ver …».
  Con la OC del ticket se verifica si ya tiene NC; varios tickets de una misma OC
  dan una sola NC, por los productos de cada ticket.
"""
import re

CANALES_AUTOMATICOS = {"Falabella", "Mercado Libre", "Paris", "Ripley", "Walmart"}
EQUIPOS_PAGINA_PROPIA = {"Página propia", "Página propia Simplit"}
CANALES_PAGINAS_PROPIAS = {"UnionX web", "Lhotse web", "Simplit web", "UnionX b2b"}
# clientes del equipo Fidelización (algunos tickets entran por Customer Care)
CANALES_FIDELIZACION = {"Travel Duty", "Celmedia", "Global Reward", "Sawa", "Banco Bice",
                        "You Market", "LATAM - GO POINT", "Friends"}
CANALES_DISTRIBUCION = {"Falabella tienda", "Paris tienda", "Lokal"}
CANAL_KITCHEN = "Kitchen Center"
ESTADOS_RECEPCIONADO = {"Nuevo", "Outlet", "Merma"}
RE_PV_TITULO = re.compile(r"\bPV\s*[#\-_]?\s*\d{3,}", re.I)

# Buckets de clasificación de un ticket
CANDIDATO = "CANDIDATO"            # entra al agente
CAMBIO = "CAMBIO"                  # motivo Cambio: pendiente de confirmar por Max
OTRO_MOTIVO = "OTRO_MOTIVO"
SIN_REVISAR = "SIN_REVISAR"        # resolución vacía
MANUAL = "MANUAL"                  # canal que se emite a mano
PV_TITULO = "PV_TITULO"            # «PV» + OC en el título
NO_RECEPCIONADO = "NO_RECEPCIONADO"


def prop(t, nombre):
    """Valor legible de una propiedad del ticket (selección → etiqueta, many2one → nombre)."""
    for p in (t.get("properties") or []):
        if str(p.get("string", "")).strip().lower() == nombre.lower():
            v = p.get("value")
            if p.get("type") == "selection" and p.get("selection"):
                return dict((s[0], s[1]) for s in p["selection"]).get(v, v)
            if p.get("type") == "many2one" and isinstance(v, (list, tuple)):
                return v[1]
            return v
    return None


def texto(t, nombre):
    v = prop(t, nombre)
    return "" if v in (None, False) else str(v).strip()


def grupo_manual(t):
    """Grupo de gestión manual del ticket, o None si es de un canal automático."""
    canal = texto(t, "Canal")
    equipo = str((t.get("team_id") or [0, ""])[1] or "").strip()
    if canal == CANAL_KITCHEN:
        return "Kitchen Center"
    if canal in CANALES_PAGINAS_PROPIAS or equipo in EQUIPOS_PAGINA_PROPIA:
        return "Página propia"
    if equipo == "Fidelización" or canal in CANALES_FIDELIZACION:
        return "Fidelización"
    if equipo == "Distribución" or canal in CANALES_DISTRIBUCION:
        return "Distribución"
    if canal not in CANALES_AUTOMATICOS:
        return "Otro canal (manual por ahora)"
    return None


def clasificar(t):
    """→ (bucket, detalle) según las reglas de Max, en el orden de su correo."""
    motivo = texto(t, "Motivo")
    if motivo == "Cambio":
        return CAMBIO, grupo_manual(t) or "canal automático"
    if motivo != "Devolución":
        return OTRO_MOTIVO, motivo or "(sin motivo)"
    if not texto(t, "Resolución"):
        return SIN_REVISAR, "resolución vacía"
    g = grupo_manual(t)
    if g:
        return MANUAL, g
    if RE_PV_TITULO.search(t.get("name") or ""):
        return PV_TITULO, "PV + OC en el título: proceso manual de Postventa"
    estado = texto(t, "Estado")
    if estado not in ESTADOS_RECEPCIONADO:
        return NO_RECEPCIONADO, estado or "(vacío)"
    return CANDIDATO, estado
