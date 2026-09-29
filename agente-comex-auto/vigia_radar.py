"""Vigía del Radar de Importaciones — corre en la nube, con el agente COMEX (GitHub Actions, diario).

El radar se actualiza en el PC de Andrés (radar-aduana/pipeline/actualizar.py, Programador de tareas 10:00) y deja
su estado en Drive (data/comex/radar/estado_radar.json). Un proceso local puede morir en silencio, así que aquí se
vigila desde afuera, con dos reglas:
  R1  el radar no corre hace más de DIAS_SIN_CORRER días (PC apagado, tarea deshabilitada, error antes de escribir);
  R2  Aduana publicó un mes (datos.gob.cl) hace más de DIAS_PUBLICADO días y el radar no lo tiene cargado.
Cada problema se avisa a Andrés UNA vez y se recuerda cada 7 días mientras siga. Los errores y controles de calidad
de cada corrida los avisa el propio PC (actualizar.py); aquí solo lo que el PC no puede avisar.

Uso local:  python vigia_radar.py          # muestra el chequeo, no envía nada
"""
import json
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import requests

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).parent
sys.path.insert(0, str(BASE.parent))            # drive_user_helpers.py vive en la raíz del repo

CKAN = "https://datos.gob.cl/api/3/action"
RX_DATASET = re.compile(r"^registros?-de-importaci[oó]n(es)?-(\d{4})$")
RX_RECURSO = re.compile(r"importaciones[-_ ]+([a-z]+)[-_ ]+(\d{4})\.(rar|zip|txt)$", re.I)
MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
DIAS_SIN_CORRER = 3
DIAS_PUBLICADO = 3
VIGIA_FILE = BASE / "data" / "vigia_radar.json"
ALERTA_A = "andres@unionx.cl"


def estado_drive() -> dict:
    """Último estado que dejó el PC (estado_radar.json en Drive; se busca por nombre)."""
    import drive_user_helpers as D
    svc = D._service()
    fs = svc.files().list(q="name = 'estado_radar.json' and trashed = false", orderBy="modifiedTime desc",
                          fields="files(id,modifiedTime)", pageSize=5).execute().get("files", [])
    if not fs:
        raise RuntimeError("no encontré estado_radar.json en Drive")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "estado_radar.json"
        D.descargar_archivo(fs[0]["id"], p)
        return json.loads(p.read_text(encoding="utf-8"))


def ultimo_publicado() -> tuple:
    """(mes 'AAAA-MM', fecha de publicación) del último mes de DIN en datos.gob.cl."""
    anio = date.today().year
    res = requests.get(f"{CKAN}/package_search", params={"q": "registro importacion", "rows": 200}, timeout=60).json()["result"]["results"]
    nombres = [d["name"] for d in res if RX_DATASET.match(d["name"]) and int(RX_DATASET.match(d["name"]).group(2)) >= anio - 1]
    mejor = (None, None)
    for n in nombres:
        pkg = requests.get(f"{CKAN}/package_show", params={"id": n}, timeout=60).json()["result"]
        for r in pkg["resources"]:
            m = RX_RECURSO.search((r.get("url") or "").rsplit("/", 1)[-1])
            if m and MESES.get(m.group(1).lower()):
                mes = f"{m.group(2)}-{MESES[m.group(1).lower()]:02d}"
                if mejor[0] is None or mes > mejor[0]:
                    mejor = (mes, (r.get("created") or "")[:10])
    return mejor


def revisar(dry_run: bool = True) -> dict:
    hoy = datetime.now(timezone.utc).date()
    vig = json.loads(VIGIA_FILE.read_text(encoding="utf-8")) if VIGIA_FILE.exists() else {}
    problemas = {}
    try:
        est = estado_drive()
        corrida = date.fromisoformat(est["ultima_corrida"][:10])
        if (hoy - corrida).days > DIAS_SIN_CORRER:
            problemas["sin_correr"] = (f"El radar no se actualiza desde el {corrida:%d-%m-%Y} ({(hoy - corrida).days} días): "
                                       "PC apagado o sin sesión, o la tarea 'UnionX - Radar Importaciones' está detenida.")
    except Exception as e:
        est = {}
        problemas["sin_estado"] = f"No pude leer el estado del radar en Drive: {e}"
    try:
        mes, publicado = ultimo_publicado()
        if mes and est.get("ultimo_mes") and mes > est["ultimo_mes"] and publicado and \
                (hoy - date.fromisoformat(publicado)).days > DIAS_PUBLICADO:
            problemas[f"atrasado_{mes}"] = (f"Aduana publicó las DIN de {mes} el {publicado} y el radar sigue en "
                                             f"{est['ultimo_mes']}. Revisar el log del PC: C:\\Users\\andre\\radar_aduana\\logs\\actualizar.log")
    except Exception as e:
        mes, publicado = None, None
        print(f"  (vigía radar: no pude consultar datos.gob.cl: {e})")
    avisados = vig.get("avisados", {})
    nuevos = {k: v for k, v in problemas.items()
              if k not in avisados or (hoy - date.fromisoformat(avisados[k])).days >= 7}
    vig.update({"ultimo_chequeo": hoy.isoformat(), "radar_ultimo_mes": est.get("ultimo_mes"),
                "radar_ultima_corrida": est.get("ultima_corrida"), "radar_resultado": est.get("resultado"),
                "aduana_ultimo_mes": mes, "aduana_publicado_el": publicado, "problemas": problemas,
                "avisados": {k: v for k, v in avisados.items() if k in problemas}})
    print(f"  Vigía radar: último mes {est.get('ultimo_mes')} (corrida {str(est.get('ultima_corrida'))[:10]}, "
          f"{est.get('resultado')}) · Aduana publicó hasta {mes} ({publicado}) · problemas: {list(problemas) or 'ninguno'}")
    if nuevos and not dry_run:
        from gmail_client import GmailClient
        html = ("<div style='font-family:Arial,sans-serif;font-size:14px'><p>⚠️ El vigía del <b>Radar de Importaciones</b> "
                "detectó:</p><ul>" + "".join(f"<li>{v}</li>" for v in nuevos.values()) +
                "</ul><p>Se vuelve a avisar cada 7 días mientras siga.</p></div>")
        GmailClient().send_email_with_attachments(to=ALERTA_A, subject="⚠️ Radar de Importaciones sin actualizar", body_html=html)
        for k in nuevos:
            vig["avisados"][k] = hoy.isoformat()
    elif nuevos:
        print(f"  (dry-run) avisaría: {list(nuevos)}")
    VIGIA_FILE.parent.mkdir(parents=True, exist_ok=True)
    VIGIA_FILE.write_text(json.dumps(vig, indent=2, ensure_ascii=False), encoding="utf-8")
    return vig


if __name__ == "__main__":
    revisar(dry_run=True)
