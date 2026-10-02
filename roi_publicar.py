"""
Publicación del ROI por producto (Andrés 1-oct-2026).

  - Excel con fórmulas → Drive "ROI UnionX" (siempre el mismo archivo y link).
  - Inyección en "Planificacion Forecast 2027.xlsx" (de Felipe): se reescribe SOLO la pestaña DATAA, con VALORES,
    en el mismo orden de columnas de 'ROI por SKU'. Las columnas ROI / EVA / Categoría 2 de "MIX de Productos"
    ya la buscan con BUSCARV (col 12, 13 y 6). Cirugía de zip: el resto del archivo queda byte a byte igual.
    Si Felipe guarda mientras tanto (cambia la fecha de modificación), no se pisa: se reintenta.
  - Histórico de cada corrida (Drive) + controles de calidad + resumen semanal por correo.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import zipfile
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
CARPETA_ROI = "1S05wnO8UFkKptPed4P5wZ0VuGYUIIRr0"
NOMBRE_EXCEL = "ROI_Producto_UnionX.xlsx"
NOMBRE_HIST = "historico_roi.parquet"
PLANIF_ID = "1hYU05PXkFm2VaL1D_LbtFGYGRj0i8umR"          # Planificacion Forecast 2027.xlsx (Felipe)
PLANIF_HOJA = "DATAA"
FUENTES = {"pricing": "1gVJmFCR19KbYkZfds7fH-62rJ0Zpt32P", "comex": "1Q9gtihNJkmExH328lXaw1kv_pP7yB0VK",
           "productos": "1LskgqxkQXRza4gpRtOWWeeMh0uzkUTcg9JuN9xSMOh0"}
RESUMEN_TO = os.environ.get("ROI_RESUMEN_TO",
                            "nicolas@unionx.cl,nicole@unionx.cl,felipe@unionx.cl,sguzman@unionx.cl,martin@unionx.cl")
ALERTA_TO = os.environ.get("ROI_ALERTA_TO", "andres@unionx.cl")
HIST_COLS = ["segmento", "clasificacion", "palanca_top", "venta", "contribucion", "capital", "roi_capital", "eva", "gmroi",
             "k_bodega", "stock_cierre_val", "alarma"]


def _svc():
    from drive_user_helpers import _service
    return _service()


# ── estado de las fuentes (vigía) ───────────────────────────────────────────
def fechas_fuentes() -> dict:
    s = _svc()
    return {k: s.files().get(fileId=v, fields="modifiedTime", supportsAllDrives=True).execute()["modifiedTime"]
            for k, v in FUENTES.items()}


def _archivo(nombre: str):
    q = f"name='{nombre}' and '{CARPETA_ROI}' in parents and trashed=false"
    fs = _svc().files().list(q=q, fields="files(id,appProperties,modifiedTime)", supportsAllDrives=True,
                             includeItemsFromAllDrives=True).execute()["files"]
    return fs[0] if fs else None


def estado_guardado() -> dict:
    f = _archivo(NOMBRE_EXCEL)
    return (f or {}).get("appProperties", {}) or {}


# ── Excel a Drive ───────────────────────────────────────────────────────────
def publicar_excel(path: Path, fechas: dict, meta_extra: dict) -> str:
    from drive_user_helpers import subir_o_actualizar
    fid, _ = subir_o_actualizar(path, CARPETA_ROI, nombre_destino=NOMBRE_EXCEL, hacer_publico=False)
    props = {**fechas, **{k: str(v)[:100] for k, v in meta_extra.items()}}
    _svc().files().update(fileId=fid, body={"appProperties": props}, supportsAllDrives=True).execute()
    return fid


# ── inyección en la planificación (cirugía de zip sobre la hoja DATAA) ─────
def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _hoja_xml(encabezados: list[str], filas: list[list]) -> bytes:
    def celda(ref, v):
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            return ""
        if isinstance(v, (bool, np.bool_)):
            v = int(v)
        if isinstance(v, (int, float, np.integer, np.floating)):
            return f'<c r="{ref}"><v>{float(v)!r}</v></c>'
        t = escape(str(v))
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{t}</t></is></c>'
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
              '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
              '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
              'state="frozen"/></sheetView></sheetViews><sheetData>')
    for i, fila in enumerate([encabezados] + filas, 1):
        out.write(f'<row r="{i}">')
        for j, v in enumerate(fila, 1):
            out.write(celda(f"{_col(j)}{i}", v))
        out.write("</row>")
    out.write("</sheetData></worksheet>")
    return out.getvalue().encode("utf-8")


MIX_HOJA = "MIX de Productos"
GMROI_ENC = "GMROI"
GMROI_DESC = "Margen directo ÷ inventario promedio a costo (veces al año)"
_RE_LOOKUP = re.compile(r"VLOOKUP\(([A-Z]+)(\d+),DATAA!\$?A\$?(\d*):\$?([A-Z]+)\$?(\d*),(\d+),0\)")
_RE_CELDA = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)


def _idx(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _unesc(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
            .replace("&amp;", "&"))


def tabla_dataa(s: pd.DataFrame, skus_num: frozenset = frozenset()) -> tuple[list[str], list[list]]:
    """Mismo orden y encabezados que 'ROI por SKU' (BUSCARV de Felipe: col 6 clasificación, 12 ROI, 13 EVA, 14 GMROI).
    El SKU va como NÚMERO si en MIX de Productos está guardado como número (BUSCARV no cruza número con texto).
    En las columnas que en el libro son fórmula, un vacío va como "" (igual que la fórmula), no como celda en blanco."""
    import roi_producto as rp
    s = s.copy()
    s["costo_d"] = s["costo"].clip(lower=0) / 365
    enc = [h for _k, h, *_ in rp.COLUMNAS]
    keys = [k for k, *_ in rp.COLUMNAS]
    formula = [tipo == "f" for _k, _h, tipo, *_ in rp.COLUMNAS]
    orden_seg = {c: i for i, c in enumerate(rp.SEGMENTOS)}
    s = s.assign(_o=s["segmento"].map(orden_seg).fillna(9)).sort_values(["_o", "venta"], ascending=[True, False])
    filas = []
    for sku, r in s.iterrows():
        fila = []
        for k, es_f in zip(keys, formula):
            src = rp.ENTRADA_DE.get(k, k)
            if src is None:
                v = int(sku) if sku in skus_num else sku
            else:
                v = r.get(src)
                if es_f and (v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v)))):
                    v = ""
            fila.append(v)
        filas.append(fila)
    return enc, filas


def _partes_hojas(zin: zipfile.ZipFile) -> dict:
    wbx = zin.read("xl/workbook.xml").decode("utf-8")
    rels = zin.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    out = {}
    for m in re.finditer(r"<sheet\b[^>]*/>", wbx):
        nombre = _unesc(re.search(r'name="([^"]+)"', m.group(0)).group(1))
        rid = re.search(r'r:id="([^"]+)"', m.group(0)).group(1)
        tgt = re.search(r'<Relationship\b[^>]*Id="' + re.escape(rid) + r'"[^>]*/>', rels).group(0)
        target = re.search(r'Target="([^"]+)"', tgt).group(1).lstrip("/")
        out[nombre] = target if target.startswith("xl/") else "xl/" + target
    return out


def _compartidos(zin: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zin.namelist():
        return []
    x = zin.read("xl/sharedStrings.xml").decode("utf-8")
    return [_unesc("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))) for si in re.findall(r"<si>(.*?)</si>", x, re.S)]


def _valor(attrs: str, cuerpo, ss: list):
    """Valor de una celda del XML: número, texto o None."""
    if not cuerpo:
        return None
    t = re.search(r'\bt="(\w+)"', attrs)
    t = t.group(1) if t else "n"
    if t == "inlineStr":
        return _unesc("".join(re.findall(r"<t[^>]*>(.*?)</t>", cuerpo, re.S)))
    v = re.search(r"<v>(.*?)</v>", cuerpo, re.S)
    if not v:
        return None
    v = v.group(1)
    if t == "s":
        return ss[int(v)]
    if t in ("str", "e"):
        return _unesc(v)
    if t == "b":
        return bool(int(v))
    try:
        return float(v)
    except ValueError:
        return _unesc(v)


def _celda_cache(ref: str, attrs: str, f_xml: str, valor) -> str:
    attrs = re.sub(r'\s*\bt="[^"]*"', "", attrs)
    if isinstance(valor, (int, float, np.integer, np.floating)) and not isinstance(valor, bool):
        return f'<c r="{ref}"{attrs}>{f_xml}<v>{float(valor)!r}</v></c>'
    return f'<c r="{ref}"{attrs} t="str">{f_xml}<v>{escape(str(valor))}</v></c>'


def _procesar_mix(xml: str, ss: list, dataa: list, gmroi_idx: int) -> tuple:
    """Recalcula el valor guardado de toda fórmula BUSCARV(...;DATAA!...) de la hoja (como Excel: número con número,
    texto sin distinguir mayúsculas, "-" si no está, 0 si la celda de DATAA está vacía) y agrega la columna GMROI
    si no existe (encabezado en la fila 2, a la derecha de las búsquedas)."""
    num, txt = {}, {}
    for i, fila in enumerate(dataa):
        k = fila[0]
        if isinstance(k, (int, float, np.integer, np.floating)):
            num.setdefault(float(k), (i + 2, fila))
        else:
            txt.setdefault(str(k).upper(), (i + 2, fila))

    def buscar(clave, col_idx, fila_max):
        if clave is None:
            return "-"
        hit = num.get(float(clave)) if isinstance(clave, float) else txt.get(str(clave).upper())
        if not hit or (fila_max and hit[0] > fila_max):
            return "-"
        v = hit[1][col_idx - 1] if col_idx - 1 < len(hit[1]) else None
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            return 0.0
        return v

    filas_xml = list(re.finditer(r"(<row\b[^>]*>)(.*?)(</row>)", xml, re.S))
    col_gm, estilo_enc, estilo_desc, estilo_dato, max_lookup, key_col = None, "", "", "", 0, None
    for m in filas_xml:
        r = int(re.search(r'\br="(\d+)"', m.group(1)).group(1))
        if r > 3:
            break
        for c in _RE_CELDA.finditer(m.group(2)):
            col, attrs, cuerpo = c.group(1), c.group(3), c.group(4)
            if r == 2 and str(_valor(attrs, cuerpo, ss)).strip() == GMROI_ENC:
                col_gm = col
            if r == 3 and cuerpo and "DATAA!" in cuerpo:
                lk = _RE_LOOKUP.search(cuerpo)
                if lk:
                    max_lookup = max(max_lookup, _idx(col))
                    key_col = key_col or lk.group(1)
                    if int(lk.group(6)) == 12:              # ROI: su estilo se copia a GMROI
                        st_ = re.search(r'\bs="\d+"', attrs)
                        estilo_dato = (" " + st_.group(0)) if st_ else ""
    if not max_lookup:
        raise RuntimeError("MIX de Productos ya no tiene fórmulas BUSCARV sobre DATAA: no se toca")
    agregar = col_gm is None
    if agregar:
        ocupadas = set()
        for m in filas_xml[:3]:
            ocupadas |= {c.group(1) for c in _RE_CELDA.finditer(m.group(2)) if c.group(4)}
        j = max_lookup + 1
        while _col(j) in ocupadas:
            j += 1
        col_gm = _col(j)
        for m in filas_xml[:3]:
            r = int(re.search(r'\br="(\d+)"', m.group(1)).group(1))
            for c in _RE_CELDA.finditer(m.group(2)):
                st_ = re.search(r'\bs="\d+"', c.group(3))
                if not st_:
                    continue
                if r == 2 and c.group(1) == _col(max_lookup - 2):       # encabezado de ROI (naranjo)
                    estilo_enc = " " + st_.group(0)
                if r == 1 and _idx(c.group(1)) < j:                     # texto descriptivo de la fila 1
                    estilo_desc = " " + st_.group(0)
    gi = _idx(col_gm)
    stats = {"celdas_actualizadas": 0, "con_valor": 0, "columna_gmroi": col_gm, "gmroi_agregada": agregar}

    def rehacer_fila(m):
        r = int(re.search(r'\br="(\d+)"', m.group(1)).group(1))
        celdas = [(c.group(1), c.group(0), c.group(3), c.group(4)) for c in _RE_CELDA.finditer(m.group(2))]
        valores = {col: _valor(attrs, cu, ss) for col, _x, attrs, cu in celdas}
        nuevas = []
        for col, xml_c, attrs, cu in celdas:
            if col == col_gm and agregar:
                continue
            lk = _RE_LOOKUP.search(cu or "")
            fx = re.search(r"<f\b[^>]*>.*?</f>", cu or "", re.S)
            if lk and fx and "DATAA!" in fx.group(0):
                v = buscar(valores.get(lk.group(1)), int(lk.group(6)), int(lk.group(5)) if lk.group(5) else 0)
                nuevas.append((col, _celda_cache(f"{col}{r}", attrs, fx.group(0), v)))
                stats["celdas_actualizadas"] += 1
                stats["con_valor"] += v != "-"
            else:
                nuevas.append((col, xml_c))
        if agregar:
            nueva = None
            if r == 1:
                nueva = f'<c r="{col_gm}1"{estilo_desc} t="inlineStr"><is><t>{escape(GMROI_DESC)}</t></is></c>'
            elif r == 2:
                nueva = f'<c r="{col_gm}2"{estilo_enc} t="inlineStr"><is><t>{GMROI_ENC}</t></is></c>'
            elif r >= 3 and key_col and any(_RE_LOOKUP.search(cu or "") for _c, _x, _a, cu in celdas):
                fx = f'<f>IFERROR(VLOOKUP({key_col}{r},DATAA!$A:${_col(gmroi_idx)},{gmroi_idx},0),"-")</f>'
                v = buscar(valores.get(key_col), gmroi_idx, 0)
                nueva = _celda_cache(f"{col_gm}{r}", estilo_dato, fx, v)
                stats["celdas_actualizadas"] += 1
                stats["con_valor"] += v != "-"
            if nueva:
                nuevas.append((col_gm, nueva))
                nuevas.sort(key=lambda x: _idx(x[0]))
        return m.group(1) + "".join(x for _c, x in nuevas) + m.group(3)

    xml = re.sub(r"(<row\b[^>]*>)(.*?)(</row>)", rehacer_fila, xml, flags=re.S)
    if agregar:
        def ext(mt):
            return f"{mt.group(1)}:{_col(max(_idx(mt.group(2)), gi))}{mt.group(3)}"
        xml = re.sub(r'(?<=<autoFilter ref=")([A-Z]+\d+):([A-Z]+)(\d+)', ext, xml, count=1)
        xml = re.sub(r'(?<=<dimension ref=")([A-Z]+\d+):([A-Z]+)(\d+)', ext, xml, count=1)
        cubre = any(int(a) <= gi <= int(b) for a, b in re.findall(r'<col min="(\d+)" max="(\d+)"', xml))
        if not cubre and "</cols>" in xml:
            xml = xml.replace("</cols>", f'<col min="{gi}" max="{gi}" width="13.3" customWidth="1"/></cols>', 1)
    return xml, stats


def _inyectar_bytes(original: bytes, s: pd.DataFrame) -> tuple:
    import roi_producto as rp
    zin = zipfile.ZipFile(io.BytesIO(original))
    partes = _partes_hojas(zin)
    if PLANIF_HOJA not in partes or MIX_HOJA not in partes:
        raise RuntimeError(f"la planilla no tiene las hojas {PLANIF_HOJA} y {MIX_HOJA}")
    ss = _compartidos(zin)
    mix = zin.read(partes[MIX_HOJA]).decode("utf-8")
    lk = _RE_LOOKUP.search(mix)
    key_col = lk.group(1) if lk else "E"
    skus_num = set()                      # SKU que MIX guarda como número (celda sin atributo t)
    for c in _RE_CELDA.finditer(mix):
        if c.group(1) == key_col and int(c.group(2)) >= 3 and c.group(4) and not re.search(r'\bt="', c.group(3)):
            v = _valor(c.group(3), c.group(4), ss)
            if isinstance(v, float):
                skus_num.add(str(int(v)))
    enc, filas = tabla_dataa(s, frozenset(skus_num))
    dataa_xml = _hoja_xml(enc, filas)
    gmroi_idx = [k for k, *_ in rp.COLUMNAS].index("gmroi") + 1
    mix_xml, stats = _procesar_mix(mix, ss, filas, gmroi_idx)
    stats.update(filas_dataa=len(filas), skus_numericos=len(skus_num))
    wbx = zin.read("xl/workbook.xml").decode("utf-8")
    if stats["gmroi_agregada"]:
        gi = _idx(stats["columna_gmroi"])
        wbx = re.sub(r"('MIX de Productos'!\$A\$\d+:\$)([A-Z]+)(\$\d+)",
                     lambda mt: mt.group(1) + _col(max(_idx(mt.group(2)), gi)) + mt.group(3), wbx)
    if "fullCalcOnLoad" not in wbx:                     # Excel recalcula todo al abrir
        wbx = re.sub(r"<calcPr\b", '<calcPr fullCalcOnLoad="1"', wbx, count=1)
    parte_dataa = partes[PLANIF_HOJA]
    parte_rels = parte_dataa.replace("worksheets/", "worksheets/_rels/") + ".rels"
    rels = zin.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            n = it.filename
            if n == parte_dataa:
                zout.writestr(it, dataa_xml)
            elif n == partes[MIX_HOJA]:
                zout.writestr(it, mix_xml.encode("utf-8"))
            elif n == "xl/workbook.xml":
                zout.writestr(it, wbx.encode("utf-8"))
            elif n in ("xl/calcChain.xml", parte_rels):
                continue
            elif n == "[Content_Types].xml":
                ct = zin.read(n).decode("utf-8")
                zout.writestr(it, re.sub(r'<Override[^>]*PartName="/xl/calcChain.xml"[^>]*/>', "", ct))
            elif n == "xl/_rels/workbook.xml.rels":
                zout.writestr(it, re.sub(r'<Relationship[^>]*Target="[^"]*calcChain.xml"[^>]*/>', "", rels))
            else:
                zout.writestr(it, zin.read(n))
    return out.getvalue(), stats


def inyectar_planificacion(s: pd.DataFrame, intentos: int = 3, subir: bool = True, local_out: Path | None = None,
                           original: bytes | None = None) -> dict:
    import googleapiclient.http
    svc = _svc()
    for i in range(intentos):
        meta = svc.files().get(fileId=PLANIF_ID, fields="name,modifiedTime", supportsAllDrives=True).execute()
        if original is None:
            buf = io.BytesIO()
            dl = googleapiclient.http.MediaIoBaseDownload(buf, svc.files().get_media(fileId=PLANIF_ID, supportsAllDrives=True))
            done = False
            while not done:
                _, done = dl.next_chunk()
            datos = buf.getvalue()
        else:
            datos = original
        nuevo, stats = _inyectar_bytes(datos, s)
        import openpyxl                    # control: el archivo resultante abre y conserva sus hojas
        wb = openpyxl.load_workbook(io.BytesIO(nuevo), read_only=True)
        if PLANIF_HOJA not in wb.sheetnames or MIX_HOJA not in wb.sheetnames:
            raise RuntimeError("la planilla resultante no conserva sus hojas: no se sube")
        if local_out:
            local_out.write_bytes(nuevo)
        if not subir:
            return {**stats, "subido": False}
        ahora = svc.files().get(fileId=PLANIF_ID, fields="modifiedTime", supportsAllDrives=True).execute()["modifiedTime"]
        if ahora != meta["modifiedTime"]:
            print(f"[planificación] Felipe la modificó durante la inyección: reintento {i + 1}")
            original = None
            continue
        media = googleapiclient.http.MediaIoBaseUpload(io.BytesIO(nuevo), mimetype=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), resumable=True)
        svc.files().update(fileId=PLANIF_ID, media_body=media, supportsAllDrives=True).execute()
        return {**stats, "subido": True, "archivo": meta["name"]}
    raise RuntimeError("la planilla se modificó en todos los intentos: no se pisó")


# ── histórico, controles y resumen ──────────────────────────────────────────
def leer_historico() -> pd.DataFrame:
    import googleapiclient.http
    f = _archivo(NOMBRE_HIST)
    if not f:
        return pd.DataFrame()
    buf = io.BytesIO()
    dl = googleapiclient.http.MediaIoBaseDownload(buf, _svc().files().get_media(fileId=f["id"], supportsAllDrives=True))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return pd.read_parquet(io.BytesIO(buf.getvalue()))


def guardar_historico(hist: pd.DataFrame, s: pd.DataFrame, meta: dict) -> pd.DataFrame:
    import googleapiclient.http
    snap = s[[c for c in HIST_COLS if c in s.columns]].copy()
    snap.insert(0, "sku", snap.index)
    snap.insert(0, "corrida", pd.Timestamp.now(tz="America/Santiago").tz_localize(None).floor("min"))
    snap["alcance"] = meta.get("alcance", "")
    snap["ventana_hasta"] = meta.get("ventana", ("", ""))[1]
    h = pd.concat([hist, snap.reset_index(drop=True)], ignore_index=True)
    data = io.BytesIO()
    h.to_parquet(data, index=False)
    media = googleapiclient.http.MediaIoBaseUpload(io.BytesIO(data.getvalue()), mimetype="application/octet-stream")
    f = _archivo(NOMBRE_HIST)
    if f:
        _svc().files().update(fileId=f["id"], media_body=media, supportsAllDrives=True).execute()
    else:
        _svc().files().create(body={"name": NOMBRE_HIST, "parents": [CARPETA_ROI]}, media_body=media,
                              supportsAllDrives=True).execute()
    return h


def ultima_corrida(hist: pd.DataFrame, alcance: str) -> pd.DataFrame:
    if hist.empty:
        return pd.DataFrame()
    h = hist[hist["alcance"] == alcance]
    if h.empty:
        return pd.DataFrame()
    return h[h["corrida"] == h["corrida"].max()].set_index("sku")


def controles(s: pd.DataFrame, prev: pd.DataFrame, n_pricing: int, n_pi: int) -> list[str]:
    """Problemas que impiden publicar (lista vacía = OK)."""
    p = []
    act = s[s["segmento"] == "Activo"]
    if n_pricing < 500:
        p.append(f"La Maestra Pricing trae solo {n_pricing} SKU (esperado > 500).")
    if n_pi < 50:
        p.append(f"El historial de PI trae solo {n_pi} PI (esperado > 50): revisar la Maestra COMEX.")
    if len(act) < 300:
        p.append(f"Solo {len(act)} SKU activos (esperado > 300).")
    if not prev.empty:
        pa = prev[prev["segmento"] == "Activo"]
        if len(pa) and len(act) < 0.7 * len(pa):
            p.append(f"Los SKU activos cayeron de {len(pa)} a {len(act)} (−{1 - len(act) / len(pa):.0%}).")
        va, vp = act["venta"].sum(), pa["venta"].sum()
        if vp and not 0.6 <= va / vp <= 1.4:
            p.append(f"La venta de 12 meses cambió {va / vp - 1:+.0%} contra la corrida anterior.")
    if s["roi_capital"].replace([np.inf, -np.inf], np.nan).dropna().empty:
        p.append("El ROI salió vacío.")
    return p


def _gmail():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    tok = os.environ.get("GMAIL_TOKEN_JSON")
    creds = (Credentials.from_authorized_user_info(json.loads(tok)) if tok
             else Credentials.from_authorized_user_file(str(ROOT / "agente-comex/config/token.json")))
    if not creds.valid:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def enviar(to: str, asunto: str, html: str, cc: str = "", adjuntos: list[tuple[str, bytes]] = ()):
    msg = EmailMessage()
    msg["To"], msg["From"], msg["Subject"] = to, "andres@unionx.cl", asunto
    if cc:
        msg["Cc"] = cc
    msg.set_content("Ver versión HTML.")
    msg.add_alternative(html, subtype="html")
    for nombre, data in adjuntos:
        msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=nombre)
    _gmail().users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}).execute()


def mm(v):
    return f"${v / 1e6:,.1f}M".replace(",", "@").replace(".", ",").replace("@", ".")


def resumen_html(s: pd.DataFrame, prev: pd.DataFrame, meta: dict, link_excel: str) -> str:
    th = "padding:4px 9px;background:#1F3864;color:#fff;text-align:left;font-size:12.5px"
    td = "padding:3px 9px;border-bottom:1px solid #E2E8F0;font-size:12.5px"

    def tabla(cab, filas, vacio="—"):
        if not filas:
            return f"<p style='font-size:13px;color:#64748B'>{vacio}</p>"
        h = "".join(f"<th style='{th}'>{c}</th>" for c in cab)
        b = "".join("<tr>" + "".join(f"<td style='{td}'>{c}</td>" for c in f) + "</tr>" for f in filas)
        return f"<table style='border-collapse:collapse;margin:4px 0 10px'><tr>{h}</tr>{b}</table>"
    act = s[s["segmento"] == "Activo"]
    roi = act["contribucion"].sum() / act["capital"].sum() if act["capital"].sum() else 0
    kpi = tabla(["Cartera activa", ""], [["SKU activos", f"{len(act):,}".replace(",", ".")], ["Venta 12m", mm(act['venta'].sum())],
                                          ["Contribución", mm(act['contribucion'].sum())], ["Capital", mm(act['capital'].sum())],
                                          ["ROI s/ capital", f"{roi:.2f}x".replace(".", ",")], ["EVA", mm(act['eva'].sum())]])
    cambios, nuevos_dv, nuevas_al = [], [], []
    if not prev.empty:
        j = s[["producto", "clasificacion", "segmento", "eva", "alarma", "stock_cierre_val"]].join(
            prev[["clasificacion", "segmento", "alarma"]], rsuffix="_ant", how="left")
        ch = j[(j["segmento"] == "Activo") & j["clasificacion_ant"].notna() & (j["clasificacion"] != j["clasificacion_ant"])]
        cambios = [[k, str(r.producto)[:45], r.clasificacion_ant, r.clasificacion, mm(r.eva)]
                   for k, r in ch.sort_values("eva", key=abs, ascending=False).head(15).iterrows()]
        dv = j[(j["clasificacion"] == "Destruye valor") & (j["clasificacion_ant"] != "Destruye valor") & (j["segmento"] == "Activo")]
        nuevos_dv = [[k, str(r.producto)[:45], mm(r.eva)] for k, r in dv.sort_values("eva").head(15).iterrows()]
        al = j[(j["segmento"] == "Solo stock") & (j["segmento_ant"] != "Solo stock")]
        nuevas_al = [[k, str(r.producto)[:45], r.alarma, mm(r.stock_cierre_val)]
                     for k, r in al.sort_values("stock_cierre_val", ascending=False).head(15).iterrows()]
    out_ = s[s["segmento"] == "Out"]
    solo = s[s["segmento"] == "Solo stock"]
    base = "Primera corrida: desde la próxima se comparan los cambios." if prev.empty else ""
    return f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.5;max-width:760px">
<p>Hola,</p><p>Resumen semanal del <b>ROI por producto</b> (12 meses {meta['ventana'][0]} a {meta['ventana'][1]}, alcance:
<b>{meta['alcance']}</b>). {base}</p>{kpi}
<h3 style="color:#1F3864;font-size:14px;margin:12px 0 2px">SKU que cambiaron de clasificación</h3>
{tabla(["SKU", "Producto", "Antes", "Ahora", "EVA"], cambios)}
<h3 style="color:#1F3864;font-size:14px;margin:12px 0 2px">Nuevos en "Destruye valor"</h3>
{tabla(["SKU", "Producto", "EVA"], nuevos_dv)}
<h3 style="color:#1F3864;font-size:14px;margin:12px 0 2px">Nuevas alarmas de solo stock</h3>
{tabla(["SKU", "Producto", "Alarma", "Stock"], nuevas_al)}
<p style="font-size:13px">En total: <b>{len(solo):,}</b> SKU con stock y sin venta ({mm(solo['stock_cierre_val'].sum())}) y
<b>{len(out_):,}</b> SKU Out con {mm(out_['k_bodega'].sum())} de inventario por liberar.</p>
<p style="font-size:13px">Excel completo (fórmulas vivas): <a href="{link_excel}">ROI UnionX en Drive</a>. El ROI, EVA y la clasificación
por SKU también están en la Planificación Forecast 2027 (MIX de Productos).</p>
<p>Saludos,<br>Andrés</p></div>""".replace(",", ",")
