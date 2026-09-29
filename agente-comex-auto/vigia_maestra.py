"""Vigía de la Maestra de Importaciones — corre en la nube, con el agente (GitHub Actions, diario).

La Maestra la actualiza el PC de Andrés (local/maestra_sync.py, Programador de tareas 09:30). Un proceso local
puede morir en silencio (PC apagado, tarea deshabilitada, Excel abierto días seguidos, un error), así que aquí
se vigila el RESULTADO y no el proceso: todo embarque con OC (fase 9 del estado) debe aparecer en la Maestra a
más tardar PLAZO_DIAS días después de quedar COMPLETADO. Si no:
  - alerta inmediata a Andrés, UNA vez por embarque (no bombardea);
  - recordatorio a Andrés los lunes mientras siga atrasado;
  - y una línea de estado (al día / atrasada) en el resumen de los lunes que recibe el equipo.
La Maestra se lee desde Drive (solo lectura) con el token OAuth del usuario (secret DRIVE_OAUTH_TOKEN_JSON).

Uso local:  python vigia_maestra.py          # muestra el chequeo, no envía nada
"""
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).parent
sys.path.insert(0, str(BASE.parent))            # drive_user_helpers.py vive en la raíz del repo

MAESTRA_ID = "1Q9gtihNJkmExH328lXaw1kv_pP7yB0VK"   # Drive · COMEX/Planificaciones/Maestra Importaciones.xlsx
PLAZO_DIAS = 3
VIGIA_FILE = BASE / "data" / "vigia_maestra.json"
ALERTA_A = "andres@unionx.cl"
RX_COMPLETADO = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T].*→ 9 \(COMPLETADO\)")


def _cargar() -> dict:
    return json.loads(VIGIA_FILE.read_text(encoding="utf-8")) if VIGIA_FILE.exists() else {}


def _guardar(d: dict):
    VIGIA_FILE.parent.mkdir(parents=True, exist_ok=True)
    VIGIA_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def fecha_oc(reg: dict):
    """Día en que el embarque quedó COMPLETADO (con OC), según el log del estado."""
    for linea in reversed(reg.get("log") or []):
        m = RX_COMPLETADO.match(linea)
        if m:
            return date.fromisoformat(m.group(1))
    ts = (reg.get("ts_actualizado") or "")[:10]
    return date.fromisoformat(ts) if ts else None


def maestra_drive() -> tuple[set, str]:
    """(N° de embarque presentes en la hoja 'Maestra', fecha de última modificación en Drive)."""
    import openpyxl
    import drive_user_helpers as D
    meta = D._service().files().get(fileId=MAESTRA_ID, fields="modifiedTime").execute()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "maestra.xlsx"
        D.descargar_archivo(MAESTRA_ID, p)
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        embs = {str(r[0]).strip() for r in wb["Maestra"].iter_rows(min_row=2, max_col=1, values_only=True) if r[0]}
        wb.close()
    return embs, meta["modifiedTime"]


def revisar(estado: dict, dry_run: bool = True) -> dict:
    hoy = datetime.now(timezone.utc).date()
    vig = _cargar()
    try:
        embs, modif = maestra_drive()
    except Exception as e:
        seguidos = vig.get("errores_seguidos", 0) + (vig.get("ultimo_chequeo") != hoy.isoformat())
        vig.update({"ultimo_chequeo": hoy.isoformat(), "error": f"no pude leer la Maestra en Drive: {e}",
                    "errores_seguidos": seguidos})
        print(f"  Vigía Maestra: ERROR {e} ({seguidos} día(s) seguidos)")
        # el vigía no puede quedar ciego en silencio: 2 días seguidos sin poder verificar → aviso (máx. 1 por semana)
        ult = vig.get("alerta_error")
        if seguidos >= 2 and (not ult or (hoy - date.fromisoformat(ult)).days >= 7):
            if not dry_run:
                from gmail_client import GmailClient
                GmailClient().send_email_with_attachments(
                    to=ALERTA_A, subject="⚠️ Vigía de la Maestra COMEX: no puedo verificarla",
                    body_html=(f"<p>Hace {seguidos} días que el agente no logra leer la Maestra de Importaciones en Drive "
                               f"para verificar que esté al día.</p><p>Error: <code>{e}</code></p><p>Lo más probable: el "
                               "token de Drive (secret DRIVE_OAUTH_TOKEN_JSON) venció o se revocó, o la Maestra cambió "
                               "de lugar. La actualización en el PC sigue funcionando; lo que falla es el control.</p>"))
                vig["alerta_error"] = hoy.isoformat()
            else:
                print("  (dry-run) avisaría que el vigía no puede verificar la Maestra")
        _guardar(vig)
        return vig
    vig["errores_seguidos"] = 0
    faltan = []
    for emb, r in estado.items():
        if not (r.get("fase") == 9 or r.get("po_name")) or emb in embs:
            continue
        f = fecha_oc(r)
        faltan.append({"embarque": emb, "po": r.get("po_name"), "desde": f.isoformat() if f else None,
                       "dias": (hoy - f).days if f else None})
    atrasados = [x for x in faltan if x["dias"] is not None and x["dias"] >= PLAZO_DIAS]
    alertados = vig.get("alertados", {})
    nuevos = [x for x in atrasados if x["embarque"] not in alertados]
    vig.update({"ultimo_chequeo": hoy.isoformat(), "maestra_modificada": modif, "embarques_en_maestra": len(embs),
                "faltan": faltan, "atrasados": atrasados, "error": None})
    # un embarque que ya entró sale de 'alertados' (si vuelve a faltar, se vuelve a avisar)
    vig["alertados"] = {k: v for k, v in alertados.items() if k in {x["embarque"] for x in faltan}}
    print(f"  Vigía Maestra: {len(embs)} embarques en la Maestra (modificada {modif[:16]}) · con OC y faltantes: "
          f"{[x['embarque'] for x in faltan] or 'ninguno'} · atrasados (≥{PLAZO_DIAS} días): {[x['embarque'] for x in atrasados] or 'ninguno'}")
    from zoneinfo import ZoneInfo
    hoy_cl = datetime.now(ZoneInfo("America/Santiago")).date()
    recordar = bool(atrasados) and not nuevos and hoy_cl.weekday() == 0 and vig.get("ultimo_recordatorio") != hoy_cl.isoformat()
    if (nuevos or recordar) and not dry_run:
        _alertar(nuevos or atrasados, modif, recordatorio=not nuevos)
        for x in nuevos:
            vig["alertados"][x["embarque"]] = hoy.isoformat()
        if recordar:
            vig["ultimo_recordatorio"] = hoy_cl.isoformat()
    elif nuevos or recordar:
        print(f"  (dry-run) {'alertaría' if nuevos else 'recordaría'} por {[x['embarque'] for x in (nuevos or atrasados)]}")
    _guardar(vig)
    return vig


def _filas_html(lst) -> str:
    td = "padding:6px;border:1px solid #ddd"
    return "".join(f"<tr><td style='{td}'><b>{x['embarque']}</b></td><td style='{td}'>{x.get('po') or '—'}</td>"
                   f"<td style='{td}'>{x.get('desde') or '—'}</td><td style='{td}'>{x.get('dias')}</td></tr>" for x in lst)


def _alertar(nuevos: list, modif: str, recordatorio: bool = False):
    from gmail_client import GmailClient
    html = ("<div style='font-family:Arial,sans-serif;font-size:14px;color:#333'>"
            + ("<p><i>Recordatorio de los lunes: siguen pendientes.</i></p>" if recordatorio else "") +
            f"<p>⚠️ Hay <b>{len(nuevos)} embarque(s) con OC</b> que llevan {PLAZO_DIAS} días o más sin aparecer en la "
            f"Maestra de Importaciones (última modificación en Drive: {modif[:10]}).</p>"
            "<table style='border-collapse:collapse'><tr style='background:#1F3864;color:#fff'>"
            "<th style='padding:6px'>Embarque</th><th style='padding:6px'>OC</th><th style='padding:6px'>Completado</th>"
            f"<th style='padding:6px'>Días</th></tr>{_filas_html(nuevos)}</table>"
            "<p><b>Qué revisar, en orden:</b> 1) que el PC esté prendido y con sesión iniciada; 2) la tarea "
            "<i>UnionX - Maestra COMEX (sync)</i> en el Programador de tareas; 3) el log "
            "<code>C:\\Users\\andre\\comex_maestra\\logs\\maestra_sync.log</code> (p.ej. Maestra abierta en Excel "
            "varios días); 4) si la OC se cargó a mano sin precosteo del agente, ese embarque hay que costearlo.</p>"
            "<p>Este aviso sale una vez por embarque y se recuerda los lunes mientras no entre.</p></div>")
    asunto = ("Recordatorio · " if recordatorio else "") + "⚠️ Maestra COMEX sin actualizar · " + ", ".join(x["embarque"] for x in nuevos)
    GmailClient().send_email_with_attachments(to=ALERTA_A, subject=asunto, body_html=html)


def linea_resumen() -> str:
    """Una línea de estado para el resumen de los lunes que recibe el equipo (el detalle va solo a Andrés)."""
    v = _cargar()
    if not v:
        return ""
    if v.get("error"):
        return "<p>⚠️ <b>Maestra de Importaciones:</b> no se pudo verificar esta semana (aviso a Andrés).</p>"
    if v.get("atrasados"):
        return (f"<p>⚠️ <b>Maestra de Importaciones:</b> {len(v['atrasados'])} embarque(s) con OC aún sin entrar "
                f"({', '.join(x['embarque'] for x in v['atrasados'])}); Andrés está avisado.</p>")
    pend = [x["embarque"] for x in v.get("faltan", [])]
    return (f"<p>✅ <b>Maestra de Importaciones al día</b> ({v.get('embarques_en_maestra')} embarques; última modificación "
            f"{str(v.get('maestra_modificada'))[:10]})" + (f"; entrando: {', '.join(pend)}" if pend else "") + ".</p>")


if __name__ == "__main__":
    import estado as st
    revisar(st.cargar(), dry_run=True)
