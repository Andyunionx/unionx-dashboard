#!/usr/bin/env python3
"""
Resumen de Circulares y Resoluciones del SII (pedido de Víctor, 25-jun-2026).

- Lee los índices oficiales del SII (circulares + resoluciones del año).
- Cada ítem trae la descripción oficial de la materia (ese es el resumen base).
- Clasifica relevancia para UnionX (operación e-commerce/importadora) por reglas.
- Mantiene estado en data/contabilidad/sii/normativa_vistas.json.
- Modo semanal (default): envía mail SOLO si hay normas nuevas desde la última corrida.
- Modo --inicial: envía el resumen completo del año (primera vez).

USO:
  python resumen_normativo_sii.py --inicial --send-mail   # primer resumen completo
  python resumen_normativo_sii.py --send-mail             # corrida semanal (lunes)
  python resumen_normativo_sii.py                         # dry: imprime, no envía
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
ESTADO_PATH = PROJECT_ROOT / "data" / "contabilidad" / "sii" / "normativa_vistas.json"
TOKEN_GMAIL = PROJECT_ROOT / "agente-comex" / "config" / "token.json"

ANIO = 2026
FUENTES = {
    "Circular": {
        "indice": f"https://www.sii.cl/normativa_legislacion/circulares/{ANIO}/indcir{ANIO}.htm",
        "base": f"https://www.sii.cl/normativa_legislacion/circulares/{ANIO}/",
    },
    "Resolución": {
        "indice": f"https://www.sii.cl/normativa_legislacion/resoluciones/{ANIO}/res_ind{ANIO}.htm",
        "base": f"https://www.sii.cl/normativa_legislacion/resoluciones/{ANIO}/",
    },
}

# Materias rutinarias (valores/tablas mensuales) — se listan aparte, sin destacar
RE_RUTINARIA = re.compile(
    r"valor de.*unidad de fomento|tablas? de.*impuesto|c[aá]lculo.*reajuste|"
    r"segunda categor[ií]a|reajustes?, intereses y multas|ppmo",
    re.IGNORECASE,
)

# Materias de interés directo para UnionX (e-commerce, importadora, IVA/DTE)
KEYWORDS_UNIONX = [
    "iva", "boleta", "factura", "documento tributario", "dte",
    "registro de compras", "rcv", "nota de cr", "condonaci",
    "renta", "cr[eé]dito fiscal", "comercio digital", "plataforma",
    "marketplace", "importaci", "aduana", "retenci", "e-commerce",
    "electr[oó]nic",
]
RE_UNIONX = re.compile("|".join(KEYWORDS_UNIONX), re.IGNORECASE)

RE_ITEM = re.compile(
    r"<h5[^>]*><a href='(?P<pdf>[^']+)'[^>]*>(?P<titulo>[^<]+)</a></h5>\s*"
    r"<p[^>]*>(?P<materia>.*?)</p>\s*"
    r"(?:<span[^>]*><i>Fuente:\s*(?P<fuente>[^<]*)</i></span>)?",
    re.DOTALL,
)


def _limpiar(texto: str) -> str:
    return html_lib.unescape(re.sub(r"\s+", " ", texto or "")).strip()


def obtener_normas() -> list[dict]:
    """Scrapea ambos índices y devuelve lista de normas normalizadas."""
    normas = []
    for tipo, cfg in FUENTES.items():
        r = requests.get(cfg["indice"], timeout=45)
        r.raise_for_status()
        html = r.content.decode("utf-8-sig", errors="replace")
        for m in RE_ITEM.finditer(html):
            titulo = _limpiar(m.group("titulo"))
            num_m = re.search(r"N[°º&deg;]*\s*(\d+)", titulo)
            fecha_m = re.search(r"del?\s+(\d{1,2}\s+de\s+\w+)", titulo)
            materia = _limpiar(m.group("materia"))
            normas.append({
                "tipo": tipo,
                "numero": int(num_m.group(1)) if num_m else 0,
                "titulo": titulo,
                "fecha": _limpiar(fecha_m.group(1)) if fecha_m else "",
                "materia": materia,
                "fuente": _limpiar(m.group("fuente") or ""),
                "url": cfg["base"] + m.group("pdf"),
                "rutinaria": bool(RE_RUTINARIA.search(materia)),
                "interes_unionx": bool(RE_UNIONX.search(materia)) and not RE_RUTINARIA.search(materia),
                "clave": f"{tipo[:4].lower()}-{ANIO}-{int(num_m.group(1)) if num_m else 0}",
            })
    return normas


def cargar_estado() -> set:
    if ESTADO_PATH.exists():
        try:
            return set(json.loads(ESTADO_PATH.read_text(encoding="utf-8")).get("vistas", []))
        except Exception:
            return set()
    return set()


def guardar_estado(claves: set):
    ESTADO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ESTADO_PATH.write_text(json.dumps(
        {"anio": ANIO, "actualizado": datetime.now().isoformat(timespec="minutes"),
         "vistas": sorted(claves)},
        indent=1, ensure_ascii=False), encoding="utf-8")


def _fila(n: dict, destacar: bool) -> str:
    borde = "border-left:4px solid #E65100;" if destacar else ""
    tag = ("<span style='background:#FFF3E0;color:#E65100;font-size:11px;font-weight:bold;"
           "padding:1px 7px;border-radius:8px;margin-left:6px'>RELEVANTE UNIONX</span>"
           if destacar else "")
    return f"""
<div style="margin:10px 0;padding:8px 12px;background:#FAFAFA;border-radius:6px;{borde}">
  <a href="{n['url']}" style="font-weight:bold;color:#0D47A1;text-decoration:none">{n['titulo']}</a>{tag}
  <div style="font-size:13px;color:#333;margin-top:3px">{n['materia']}</div>
  <div style="font-size:11px;color:#888;margin-top:2px">{n['fuente']}</div>
</div>"""


def construir_mail(normas: list[dict], inicial: bool) -> tuple[str, str]:
    relevantes = [n for n in normas if n["interes_unionx"]]
    otras = [n for n in normas if not n["interes_unionx"] and not n["rutinaria"]]
    rutinarias = [n for n in normas if n["rutinaria"]]

    fecha_str = datetime.now().strftime("%d-%m-%Y")
    if inicial:
        titulo = f"Resumen normativo SII {ANIO} — línea base completa"
        intro = (f"Resumen inicial de <strong>todas</strong> las circulares y resoluciones "
                 f"publicadas por el SII durante {ANIO}. Desde ahora, cada lunes llegará "
                 f"un correo <strong>solo si hay normas nuevas</strong>.")
    else:
        titulo = f"Nuevas normas SII — semana del {fecha_str}"
        intro = ("El SII publicó las siguientes circulares/resoluciones nuevas "
                 "desde la última revisión.")

    cuerpo_secciones = ""
    if relevantes:
        cuerpo_secciones += (f"<h3 style='color:#E65100;margin-bottom:4px'>⭐ Relevantes para UnionX "
                             f"({len(relevantes)})</h3>"
                             "<p style='font-size:12px;color:#666;margin-top:0'>IVA, documentos tributarios, "
                             "renta, condonaciones, comercio digital.</p>")
        cuerpo_secciones += "".join(_fila(n, True) for n in relevantes)
    if otras:
        cuerpo_secciones += f"<h3 style='color:#37474F;margin-bottom:4px'>📄 Otras materias ({len(otras)})</h3>"
        cuerpo_secciones += "".join(_fila(n, False) for n in otras)
    if rutinarias:
        filas_rut = "".join(
            f"<li style='margin:2px 0'><a href='{n['url']}' style='color:#0D47A1'>{n['titulo']}</a> — "
            f"<span style='color:#555'>{n['materia'][:110]}</span></li>"
            for n in rutinarias)
        cuerpo_secciones += (f"<h3 style='color:#78909C;margin-bottom:4px'>🗓 Rutinarias — UF, tablas, "
                             f"reajustes ({len(rutinarias)})</h3><ul style='font-size:12px'>{filas_rut}</ul>")

    cuerpo = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#333;max-width:820px">
<h2 style="color:#1B5E20">📋 {titulo}</h2>
<p>{intro}</p>
<p style="font-size:13px">Total: <strong>{len(normas)}</strong> norma(s) —
{sum(1 for n in normas if n['tipo']=='Circular')} circular(es) ·
{sum(1 for n in normas if n['tipo']=='Resolución')} resolución(es).
Cada título enlaza al PDF oficial del SII.</p>
{cuerpo_secciones}
<p style="color:#666;font-size:12px;margin-top:24px">— Agente UnionX · revisión automática de
<a href="{FUENTES['Circular']['indice']}">circulares</a> y
<a href="{FUENTES['Resolución']['indice']}">resoluciones</a> · {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
</body></html>"""

    asunto = (f"[Normativa SII] {titulo}" if inicial else
              f"[Normativa SII] {len(normas)} norma(s) nueva(s) — {fecha_str}")
    return asunto, cuerpo


def enviar_mail(asunto: str, cuerpo_html: str, destinatarios: list[str], cc: list[str]) -> dict:
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(
        str(TOKEN_GMAIL), ["https://www.googleapis.com/auth/gmail.send"])
    service = build("gmail", "v1", credentials=creds)
    msg = MIMEMultipart("alternative")
    msg["To"] = ", ".join(destinatarios)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"ok": True, "message_id": r.get("id")}


def main():
    parser = argparse.ArgumentParser(description="Resumen normativo SII")
    parser.add_argument("--inicial", action="store_true",
                        help="Resumen completo del año (línea base)")
    parser.add_argument("--send-mail", action="store_true",
                        help="Enviar por Gmail (sin flag: solo imprime)")
    args = parser.parse_args()

    print(f"=== RESUMEN NORMATIVO SII — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    normas = obtener_normas()
    n_circ = sum(1 for n in normas if n["tipo"] == "Circular")
    n_reso = len(normas) - n_circ
    print(f"► Índices SII leídos: {n_circ} circulares + {n_reso} resoluciones {ANIO}")
    if not normas:
        print("⚠️  0 normas parseadas — revisar estructura HTML del SII")
        sys.exit(1)

    vistas = cargar_estado()
    nuevas = [n for n in normas if n["clave"] not in vistas]
    print(f"► Ya vistas: {len(vistas)} | Nuevas: {len(nuevas)}\n")

    a_reportar = normas if args.inicial else nuevas
    if not a_reportar:
        print("✓ Sin normas nuevas esta semana — no se envía correo.")
        guardar_estado({n["clave"] for n in normas})
        return

    for n in a_reportar:
        marca = "⭐" if n["interes_unionx"] else ("🗓" if n["rutinaria"] else "·")
        print(f"  {marca} {n['titulo'][:70]}")

    asunto, cuerpo = construir_mail(a_reportar, inicial=args.inicial)

    if args.send_mail:
        destinatarios = ["victor@unionx.cl"]
        cc = ["andres@unionx.cl"]
        res = enviar_mail(asunto, cuerpo, destinatarios, cc)
        print(f"\n✓ Mail enviado (message_id={res['message_id']}) → {', '.join(destinatarios)}")
    else:
        print(f"\n[DRY] Asunto: {asunto}")
        print("[DRY] Agregar --send-mail para enviar")

    guardar_estado({n["clave"] for n in normas})
    print(f"✓ Estado guardado: {ESTADO_PATH.name} ({len(normas)} claves)")


if __name__ == "__main__":
    main()
