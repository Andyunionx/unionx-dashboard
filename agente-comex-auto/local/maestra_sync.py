"""Sincroniza la Maestra de Importaciones VIVA con los precosteos del agente COMEX. Corre en el PC de Andrés.

Por qué en el PC: la Maestra vive en Google Drive (COMEX/Planificaciones) y la usan personas; el agente de la
nube no la toca. Este proceso (Programador de tareas de Windows, diario) hace:
  1. Precosteos: baja del correo ENVIADO los que el agente mandó al equipo (adjunto Pre-costeo_x_CBM_<EMB>.xlsx)
     y suma los del agente antiguo (agente-comex/data/output). Por embarque gana el MÁS RECIENTE.
  2. Qué entra: embarques que no están en la Maestra y que ya tienen OC (estado del agente en origin/main:
     fase 9 o po_name), o que vienen del agente antiguo (ya cerrados). Los que esperan SKU entran solos después.
  3. SKU: alias del estado del agente (sku_alias, por SKU o por modelo) + alias_sku.json (manual, con fuente).
     Un "SKU" con espacios, ':' o decimal ('0.4') es una nota del PI → la fila queda sin SKU (no se inventa).
  4. Cirugía XML (maestra_xml.py), validación, respaldo y reemplazo EN EL MISMO ARCHIVO (Drive conserva el id
     y el historial de versiones).
Seguridad: no escribe si la Maestra cambió en los últimos 30 min, si hay un ~$ (Excel abierto) de menos de 12 h,
o si el archivo cambió entre la lectura y la escritura. Nunca usa COM/Excel.

Uso:  python maestra_sync.py              # vista previa en C:/Users/andre/comex_maestra/preview (no toca la Maestra)
      python maestra_sync.py --aplicar    # respalda y reemplaza la Maestra viva
      python maestra_sync.py --solo 26TP0811,26TP0826 --sin-correo
"""
import argparse
import base64
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.stdout:                       # con pythonw (Programador de tareas) no hay consola
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
import maestra_xml as MX  # noqa: E402

MAESTRA = Path("G:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/COMEX/Planificaciones/Maestra Importaciones.xlsx")
REPO_DRIVE = Path("G:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA")
LEGADO = [REPO_DRIVE / "agente-comex" / "data" / "output", REPO_DRIVE / "agente-comex-auto" / "data" / "output"]
TOKEN = REPO_DRIVE / "agente-comex" / "config" / "token.json"          # mismo token del agente (solo lectura)
WORK = Path("C:/Users/andre/comex_maestra")
CACHE, BACKUPS, LOGS, PREVIEW = WORK / "cache", WORK / "backups", WORK / "logs", WORK / "preview"
REPO_GIT = Path(__file__).resolve().parents[2]                          # worktree de este código
ALIAS = Path(__file__).parent / "alias_sku.json"
RX_ADJ = re.compile(r"^Pre-costeo_x_CBM_(\d{2}TP\d{4}[A-Z]*)\.xlsx$")
MAX_BACKUPS = 20
GIT = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"


def log(msg):
    print(msg, flush=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "maestra_sync.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 1. precosteos
def gmail():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(TOKEN))
    if not creds.valid:
        creds.refresh(Request())          # en memoria: NO reescribe token.json (lo usa el agente antiguo)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _partes(p):
    yield p
    for h in p.get("parts", []) or []:
        yield from _partes(h)


def bajar_de_correo() -> list:
    """[(emb, fecha_epoch, path)] de los adjuntos enviados por el agente (se cachean por id de mensaje)."""
    svc, out, token = gmail(), [], None
    q = 'in:sent has:attachment subject:"Costeo importación" newer_than:400d'
    ids = []
    while True:
        r = svc.users().messages().list(userId="me", q=q, maxResults=100, pageToken=token).execute()
        ids += [m["id"] for m in r.get("messages", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    for mid in ids:
        m = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        fecha = int(m["internalDate"]) / 1000
        for p in _partes(m["payload"]):
            mm = RX_ADJ.match(p.get("filename") or "")
            if not mm or not p.get("body", {}).get("attachmentId"):
                continue
            dest = CACHE / mm.group(1) / f"{mid}_{p['filename']}"
            if not dest.exists():
                a = svc.users().messages().attachments().get(userId="me", messageId=mid, id=p["body"]["attachmentId"]).execute()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(base64.urlsafe_b64decode(a["data"]))
            out.append((mm.group(1), fecha, dest))
    return out


def del_legado() -> list:
    out = []
    for d in LEGADO:
        for f in glob.glob(str(d / "*" / "Pre-costeo_x_CBM_*.xlsx")):
            mm = RX_ADJ.match(Path(f).name)
            if mm:
                out.append((mm.group(1), Path(f).stat().st_mtime, Path(f)))
    return out


# ---------------------------------------------------------------- 2. estado del agente (origin/main)
def estado_agente() -> dict:
    cache = CACHE / "estado_embarques.json"
    # con pythonw (Programador de tareas) git necesita consola oculta y sin prompts, o muere con 0xC000013A
    kw = dict(capture_output=True, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    try:
        f = subprocess.run([GIT, "-C", str(REPO_GIT), "fetch", "-q", "origin", "main"], timeout=120, **kw)
        if f.returncode:
            log(f"  (aviso: git fetch devolvió {f.returncode}; uso el último origin/main descargado)")
        txt = subprocess.run([GIT, "-C", str(REPO_GIT), "show", "origin/main:agente-comex-auto/data/estado_embarques.json"],
                             check=True, timeout=60, **kw).stdout.decode("utf-8")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(txt, encoding="utf-8")
    except Exception as e:  # sin red: se usa la última copia buena
        log(f"  (aviso: no pude leer el estado desde origin/main: {e}; uso la copia en caché)")
        txt = cache.read_text(encoding="utf-8") if cache.exists() else "{}"
    d = json.loads(txt)
    return d.get("embarques", d)


def con_oc(reg: dict) -> bool:
    return bool(reg) and (reg.get("fase") == 9 or bool(reg.get("po_name")))


# ---------------------------------------------------------------- 3. SKU
def sku_valido(s: str) -> bool:
    s = s.strip()
    return len(s) >= 3 and not re.search(r"[\s:;,]", s) and not re.fullmatch(r"\d+\.\d+", s)


def corregir_skus(emb: dict, reg: dict, manual: dict) -> list:
    """Aplica alias y limpia notas; devuelve la lista de cambios (para el log)."""
    alias = dict(manual.get("global", {}))
    alias.update(manual.get("por_embarque", {}).get(emb["embarque"], {}))
    alias.update({k: {"sku": v, "fuente": "estado del agente (sku_alias)"} for k, v in (reg or {}).get("sku_alias", {}).items()})
    cambios = []
    for p in emb["productos"]:
        sku, modelo = str(p.get("SKU") or "").strip(), str(p.get("Model") or "").strip()
        nuevo = alias.get(sku) or alias.get(modelo)
        if nuevo and nuevo["sku"] != sku:
            cambios.append(f"{modelo}: {sku or '(sin SKU)'} → {nuevo['sku']} ({nuevo.get('fuente', '')})")
            p["SKU"] = nuevo["sku"]
        elif sku and not sku_valido(sku):
            cambios.append(f"{modelo}: '{sku}' no es un SKU (nota del PI) → sin SKU")
            p["SKU"] = None
    return cambios


def odoo_codigos(codigos: set) -> set:
    """Cuáles de estos códigos existen como default_code en Odoo (activos o archivados). Solo lectura."""
    import os
    import xmlrpc.client
    url, db, user = "https://unionxb2b.odoo.com", "bmya-innovatek-sh-prd-6981800", "andres@grupoeter.cl"
    env = {}
    if (REPO_DRIVE / ".env").exists():
        for linea in (REPO_DRIVE / ".env").read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                k, v = linea.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD") or env.get("ANDRES_ODOO_PASSWORD")
    uid = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common").authenticate(db, user, pwd, {})
    obj, out, lst = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object"), set(), sorted(codigos)
    for i in range(0, len(lst), 200):
        r = obj.execute_kw(db, uid, pwd, "product.product", "search_read",
                           [[["default_code", "in", lst[i:i + 200]], ["active", "in", [True, False]]]], {"fields": ["default_code"]})
        out |= {x["default_code"] for x in r if x.get("default_code")}
    return out


def completar_con_odoo(embs: list):
    """Fila sin SKU cuyo MODELO es un código de Odoo → ese es el SKU (el PI lo trajo en la columna equivocada).
    Los SKU que no existen en Odoo se informan, no se tocan."""
    cand = {str(p.get("Model") or "").strip() for e in embs for p in e["productos"] if not str(p.get("SKU") or "").strip()}
    skus = {str(p.get("SKU") or "").strip() for e in embs for p in e["productos"] if str(p.get("SKU") or "").strip()}
    try:
        existen = odoo_codigos({c for c in cand | skus if c})
    except Exception as ex:
        log(f"  (aviso: no pude consultar Odoo: {ex}; sigo sin completar SKU por modelo)")
        return
    for e in embs:
        for p in e["productos"]:
            sku, modelo = str(p.get("SKU") or "").strip(), str(p.get("Model") or "").strip()
            if not sku and modelo in existen:
                p["SKU"] = modelo
                log(f"  {e['embarque']} · {modelo}: sin SKU → {modelo} (el modelo es un código de Odoo)")
        faltan = sorted({str(p.get("SKU")).strip() for p in e["productos"] if str(p.get("SKU") or "").strip()
                         and str(p.get("SKU")).strip() not in existen})
        if faltan:
            log(f"  {e['embarque']} · SKU que no existen en Odoo (se dejan igual): {', '.join(faltan)}")


# ---------------------------------------------------------------- 4. escritura segura
def puede_escribir() -> str | None:
    lock = MAESTRA.with_name("~$" + MAESTRA.name)
    if lock.exists() and time.time() - lock.stat().st_mtime < 12 * 3600:
        return f"hay un ~$ de hace {(time.time() - lock.stat().st_mtime) / 60:.0f} min (Excel abierto)"
    if time.time() - MAESTRA.stat().st_mtime < 30 * 60:
        return "la Maestra cambió hace menos de 30 min (alguien la está editando o Drive sincroniza)"
    return None


def respaldar() -> Path:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS / f"Maestra Importaciones {datetime.now():%Y%m%d-%H%M%S}.xlsx"
    shutil.copy2(MAESTRA, dest)
    for viejo in sorted(BACKUPS.glob("Maestra Importaciones *.xlsx"))[:-MAX_BACKUPS]:
        viejo.unlink()
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="respalda y reemplaza la Maestra viva")
    ap.add_argument("--solo", default="", help="embarques separados por coma")
    ap.add_argument("--sin-correo", action="store_true")
    a = ap.parse_args()
    log(f"=== maestra_sync {'APLICAR' if a.aplicar else 'vista previa'}")
    hash_ini = sha(MAESTRA)

    fuentes = del_legado()
    if not a.sin_correo:
        try:
            fuentes += bajar_de_correo()
        except Exception as e:
            log(f"  (aviso: no pude leer el correo: {e}; sigo solo con los precosteos locales)")
    mejor = {}
    for emb, fecha, path in fuentes:
        if emb not in mejor or fecha > mejor[emb][0]:
            mejor[emb] = (fecha, path)

    estado = estado_agente()
    en_maestra = MX.embarques_en_maestra(MAESTRA)
    manual = json.loads(ALIAS.read_text(encoding="utf-8")) if ALIAS.exists() else {}
    solo = {s.strip() for s in a.solo.split(",") if s.strip()}
    embs, esperan = [], []
    for emb, (fecha, path) in sorted(mejor.items()):
        if emb in en_maestra or (solo and emb not in solo):
            continue
        origen = ("correo" if str(path).startswith(str(CACHE)) else
                  "agente antiguo" if str(path).startswith(str(LEGADO[0])) else "agente nuevo (local)")
        reg = estado.get(emb)
        # el agente antiguo solo costeó embarques que se cerraron con OC a mano; el nuevo, se mira su estado
        if not (origen == "agente antiguo" or con_oc(reg)):
            esperan.append(f"{emb} (fase {reg.get('fase') if reg else '?'})")
            continue
        e = MX.leer_precosteo(str(path))
        if e["embarque"] != emb:
            log(f"  (aviso: {path.name} dice embarque {e['embarque']}; se usa {emb})")
            e["embarque"] = emb
        for c in corregir_skus(e, reg, manual):
            log(f"  {emb} · {c}")
        e["fuente"] = f"{origen} {datetime.fromtimestamp(fecha):%d-%m-%Y}"
        embs.append(e)
    if esperan:
        log(f"  Esperan OC (entran solos cuando la tengan): {', '.join(esperan)}")
    if not embs:
        log("  Nada que agregar: la Maestra ya tiene todos los embarques con OC.")
        return
    completar_con_odoo(embs)
    embs.sort(key=lambda e: (e["eta"], e["embarque"]))
    log(f"  A agregar ({len(embs)}): " + ", ".join(f"{e['embarque']} [{e['fuente']}]" for e in embs))

    PREVIEW.mkdir(parents=True, exist_ok=True)
    destino = PREVIEW / f"Maestra Importaciones (vista previa {datetime.now():%Y%m%d-%H%M}).xlsx"
    st = MX.construir(MAESTRA, embs, destino)
    log(f"  ✓ Válida: Maestra +{st['filas_maestra']} filas ({st['fila_ini']}–{st['fila_fin']}) · +{st['embarques']} embarques en "
        f"Variacion Exog./Eficiencia/Centros/listados · Matriz +{st['matriz_columnas']} col y +{st['matriz_skus']} SKU · "
        f"{st['formulas_ampliadas']} fórmulas ampliadas · {st['hojas']} hojas → {destino}")
    if not a.aplicar:
        log("  Vista previa lista (la Maestra NO se tocó). Para aplicar: --aplicar")
        return

    motivo = puede_escribir()
    if motivo:
        log(f"  ✋ No escribo: {motivo}. Reintento en la próxima corrida.")
        sys.exit(2)
    if sha(MAESTRA) != hash_ini:
        log("  ✋ No escribo: la Maestra cambió mientras armaba la actualización. Reintento en la próxima corrida.")
        sys.exit(2)
    bk = respaldar()
    shutil.copyfile(destino, MAESTRA)                 # mismo archivo: Drive conserva id e historial
    if sha(MAESTRA) != sha(destino):
        shutil.copyfile(bk, MAESTRA)
        log("  ✗ La copia no quedó idéntica: restauré el respaldo.")
        sys.exit(1)
    log(f"  ✓ Maestra actualizada. Respaldo: {bk}")
    with open(LOGS / "maestra_sync.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "embarques": [e["embarque"] for e in embs],
                            "fuentes": {e["embarque"]: e["fuente"] for e in embs}, "respaldo": str(bk),
                            **{k: v for k, v in st.items() if not k.startswith("listado")}}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
