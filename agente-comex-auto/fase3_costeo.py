"""FASE 3 — Costeo + chequeo de SKUs en Odoo + borrador de correo.

Con PI+PL (fase 1) y flete final (fase 2), esta fase:
1. Construye las Tarifas (flete del estado + gastos Chile ESTÁNDAR + TC + ETA).
2. Corre el motor de costeo (reusa _REACTIVAR_NUEVO_PC/costear_embarque.py, con fix CBM).
3. Genera el Pre-costeo + compara con la Maestra.
4. Ítems SIN código en el PI → SKU por el historial del modelo en la Maestra (si es inequívoco).
   Chequea en Odoo qué SKU existen (por default_code) → lista de FALTANTES.
5. Envía el correo de costeo a Felipe/Seba/bodega (una vez por cada cambio de pendientes).
6. Gate: sin pendientes → fase 4. Solo ítems SIN código → PO parcial (no bloquean).
   SKU por crear → se queda y re-chequea Odoo cada día.
7. Lunes: UN resumen consolidado de embarques detenidos (URGENTE si ETA <= 7 días).

dry_run=True: costea y reporta, NO crea el borrador en Gmail.
"""
import os
import re
import sys
import glob
import xmlrpc.client
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
REPO = BASE.parent
sys.path.insert(0, str(REPO / "_REACTIVAR_NUEVO_PC"))
sys.path.insert(0, str(BASE))  # GmailClient vendorizado en este paquete
import costear_embarque as ce           # noqa: E402
import estado as st                       # noqa: E402

# Gastos Chile ESTÁNDAR por contenedor (criterio fijado con Andrés) ≈ 912.187 CLP
CHILE_GASTOS = {
    "Gastos Puerto STI": 20000, "Flete Terrestre": 415000, "Seimex (local)": 238529,
    "Desconsolidación": 50000, "Gastos Despacho": 43658, "Gate In": 145000,
}
TC_ADUANA = 950.0
MAESTRA = REPO / "data" / "comex" / "Maestra Importaciones V2.xlsx"
OUT = BASE / "data" / "output"
DEST = ["felipe@unionx.cl", "sguzman@grupoeter.cl", "bodega@grupoeter.cl"]  # Gerardo por confirmar

PUERTOS = {"SZ": "Shenzhen", "NB": "Ningbo", "XI": "Xiamen"}

# Maestra viva (historial modelo → SKU): local en el PC de Andrés; en la nube se baja de Drive (como vigia_maestra)
MAESTRA_VIVA_LOCAL = Path("G:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/COMEX/Planificaciones/Maestra Importaciones.xlsx")
MIN_EMB_AUTO = 3           # embarques con el mismo SKU para cargarlo solo a la PO
TOL_AUTO = 0.10            # precio PI vs último precio histórico (automático)
TOL_SUGERIDO = 0.35        # ídem para solo sugerirlo en el correo
MIN_QTY = 10               # menos = muestra; no se asigna
RX_NO_PRODUCTO = re.compile(r"exhibidor|muestra|dummy|display", re.I)
_HISTORIAL = None          # cache por corrida


def resolver_archivos(reg) -> tuple[Path | None, Path | None]:
    """Devuelve (pi_path, pl_path): path del estado → repo → re-descarga de Gmail on-demand."""
    def buscar(doc):
        if not doc:
            return None
        if doc.get("path") and Path(doc["path"]).exists():
            return Path(doc["path"])
        fn = doc["filename"]
        # buscar por nombre en el repo (local)
        for base in [REPO / "data" / "comex" / "embarques", REPO / "agente-comex" / "data" / "inbox",
                     Path("C:/Users/andre/Downloads")]:
            hits = glob.glob(str(base / "**" / fn), recursive=True)
            if hits:
                return Path(hits[0])
        # re-descargar de Gmail (runner efímero en la nube)
        if doc.get("msg_id") and doc.get("attachment_id"):
            try:
                from gmail_client import GmailClient
                save_dir = BASE / "data" / "inbox" / (reg.get("embarque") or "tmp")
                return GmailClient().download_attachment(doc["msg_id"], doc["attachment_id"], fn, str(save_dir))
            except Exception as e:
                print(f"  (no pude re-descargar {fn} de Gmail: {e})")
        return None
    return buscar(reg.get("pi")), buscar(reg.get("pl"))


def aplicar_alias(productos, reg):
    """Corrige SKU del PI de Steven: reg['sku_alias'] = {sku_pi_o_modelo: sku_odoo}.
    Clave = SKU mal escrito, o MODELO si el ítem viene sin código (ej. {"HD4 Khaki": "..."}).
    Ej. 26TP0720: SIMOREXBAS-35 → SIMOREXOSL-WD (confirmado por Andrés 24-sep)."""
    alias = {k.strip().upper(): v for k, v in (reg.get("sku_alias") or {}).items()}
    hist = {k.strip().upper(): v["sku"] for k, v in (reg.get("sku_historial") or {}).items()}
    for p in productos:
        s = (p.sku or "").strip().upper()
        m = str(p.model or "").strip().upper()
        if s and s in alias:
            p.sku = alias[s]
        elif not s and m in alias:      # ítem SIN código en el PI → se mapea por MODELO
            p.sku = alias[m]
        elif not s and m in hist:       # sin alias confirmado → el SKU que dio el historial (sku_por_historial)
            p.sku = hist[m]
    return productos


def _norm_modelo(s) -> str:
    return re.sub(r"[\s\-_]", "", str(s or "")).upper()


def historial_maestra() -> dict:
    """{MODELO normalizado: [(embarque, sku, precio_usd), ...]} desde la hoja 'Maestra'
    (A = N° Embarque, C = Model, D = SKU, G = Cost Unit). Si no se puede leer → {} (el agente sigue como antes)."""
    global _HISTORIAL
    if _HISTORIAL is not None:
        return _HISTORIAL
    _HISTORIAL = {}
    try:
        import tempfile
        import openpyxl
        with tempfile.TemporaryDirectory() as tmp:
            path = MAESTRA_VIVA_LOCAL
            if not path.exists():
                import vigia_maestra
                import drive_user_helpers as D
                path = Path(tmp) / "maestra.xlsx"
                D.descargar_archivo(vigia_maestra.MAESTRA_ID, path)
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            for r in wb["Maestra"].iter_rows(min_row=2, max_col=7, values_only=True):
                emb, modelo, sku, precio = r[0], r[2], r[3], r[6]
                sku = str(int(sku) if isinstance(sku, float) else sku or "").strip()
                if emb and modelo and sku:
                    _HISTORIAL.setdefault(_norm_modelo(modelo), []).append((str(emb).strip(), sku, precio))
            wb.close()
        print(f"  Historial Maestra: {len(_HISTORIAL)} modelos")
    except Exception as e:
        print(f"  (historial Maestra no disponible: {type(e).__name__}: {e})")
    return _HISTORIAL


def sku_por_historial(productos, reg, emb_num) -> dict:
    """Ítems SIN código en el PI → SKU por el historial del MODELO en la Maestra.
    Caso 26TP0826: TP103 venía sin código, nadie respondió el correo y la PO salió sin las 504 hieleras,
    aunque el modelo siempre fue SIMHIECHAR (24TP1114, 24TP1216, 25TP0901).
    Steven REUSA modelos (0604: TP48 fue decantador en 2 embarques y esta vez era el filtro VINFILTOXIG; 0423:
    USB-C-1 negro y el historial solo tenía el blanco), así que hay dos niveles:
      - AUTOMÁTICO (va a la PO): mismo SKU en >= MIN_EMB_AUTO embarques y precio a ±TOL_AUTO del último;
      - SUGERIDO (solo en el correo y el resumen, para confirmar): SKU único en el historial y precio a ±TOL_SUGERIDO.
    Ambos descartan: < MIN_QTY u (muestras), precio 0 (cajas), modelo que ya trae SKU en otra línea del PI
    (0826: TP033E "Package box" ≠ telón LVTELELE-100), color del PI distinto al del SKU, exhibidores/muestras
    y SKU que no exista en Odoo. Backtest PIs 2024-2026: ver commit.
    reg['sku_historial'] = automáticos (aplicar_alias los reaplica en fase 4); reg['sku_sugerido'] = por confirmar."""
    sin = [p for p in productos if not (p.sku or "").strip()]
    hist = historial_maestra() if sin else {}
    if not hist:
        return {}
    con_sku = {_norm_modelo(p.model) for p in productos if (p.sku or "").strip()}
    candidatos = {}
    for p in sin:
        m = _norm_modelo(p.model)
        filas = sorted((f for f in hist.get(m, []) if f[0].upper() != emb_num.upper()), key=lambda f: f[0])
        skus = {f[1] for f in filas}
        if not m or m in con_sku or len(skus) != 1 or float(p.qty or 0) < MIN_QTY:
            continue
        precio = float(p.price or 0)
        ref = next((float(f[2]) for f in reversed(filas) if isinstance(f[2], (int, float)) and f[2] > 0), None)
        if precio <= 0 or not ref or abs(precio / ref - 1) > TOL_SUGERIDO:
            continue
        embs = sorted({f[0] for f in filas})
        auto = len(embs) >= MIN_EMB_AUTO and abs(precio / ref - 1) <= TOL_AUTO
        candidatos[str(p.model).strip()] = {"sku": next(iter(skus)), "embarques": embs, "precio_hist": ref,
                                           "auto": auto, "desc": str(p.descripcion or "")}
    nombres = _odoo_nombres([c["sku"] for c in candidatos.values()]) if candidatos else {}
    for k in list(candidatos):
        c = candidatos[k]
        nombre = nombres.get(c["sku"])
        if not nombre or RX_NO_PRODUCTO.search(nombre) or _choca_color(c["desc"], c["sku"], nombre):
            del candidatos[k]
            continue
        c["nombre"] = nombre[:60]
        del c["desc"]
    auto = {k: v for k, v in candidatos.items() if v.pop("auto")}
    sugeridos = {k: v for k, v in candidatos.items() if k not in auto}
    if auto:
        reg["sku_historial"] = {**(reg.get("sku_historial") or {}), **auto}
        aplicar_alias(productos, reg)
        for k, v in auto.items():
            st.log(reg, f"{k} sin código en el PI → {v['sku']} por historial Maestra ({', '.join(v['embarques'][-3:])})")
    if sugeridos:
        reg["sku_sugerido"] = sugeridos
    else:
        reg.pop("sku_sugerido", None)
    return auto


COLORES = {"negro": (r"negr[oa]|black", "BK"), "blanco": (r"blanc[oa]|white", "WH"), "rosado": (r"rosad[oa]|pink", "PK"),
           "rojo": (r"roj[oa]|red", "RD"), "azul": (r"azul|blue", None), "verde": (r"verde|green", None),
           "gris": (r"gris|grey|gray", None)}


def _colores(texto: str, sku: str = "") -> set:
    return {c for c, (rx, suf) in COLORES.items()
            if re.search(rf"\b(?:{rx})\b", texto, re.I) or (suf and sku.upper().endswith(f"-{suf}"))}


def _choca_color(desc_pi: str, sku: str, nombre_odoo: str) -> bool:
    """El PI dice un color y el SKU/producto de Odoo dice otro (0423: cable USB-C negro → LVCABTC-WH)."""
    pi, odoo = _colores(desc_pi), _colores(nombre_odoo, sku)
    return bool(pi and odoo and not pi & odoo)


def _odoo_nombres(skus) -> dict:
    """{default_code: nombre} de los SKU que existen (activos) en Odoo."""
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD")
    url = "https://unionxb2b.odoo.com"; db = "bmya-innovatek-sh-prd-6981800"
    uid = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common").authenticate(db, "andres@grupoeter.cl", pwd, {})
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return {r["default_code"]: r["name"] for r in models.execute_kw(
        db, uid, pwd, "product.product", "search_read", [[["default_code", "in", sorted(set(skus))]]],
        {"fields": ["default_code", "name"]})}


def construir_tarifas(reg, puerto: str) -> ce.Tarifas:
    return ce.Tarifas(
        puerto=puerto, puerto_nombre=PUERTOS.get(puerto, puerto),
        dolar=TC_ADUANA, fecha_eta=reg.get("eta_bodega") or reg.get("eta_puerto") or "",
        flete_total_usd=float(reg.get("flete_usd") or 0.0),
        gastos_chile_clp=dict(CHILE_GASTOS),
    )


def odoo_sku_check(productos) -> tuple[list, list]:
    """Devuelve (existentes, faltantes) por default_code en Odoo."""
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD")
    url = "https://unionxb2b.odoo.com"; db = "bmya-innovatek-sh-prd-6981800"
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, "andres@grupoeter.cl", pwd, {})
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    skus = sorted({(p.sku or "").strip() for p in productos if (p.sku or "").strip()})
    existentes, faltantes = [], []
    for sku in skus:
        n = models.execute_kw(db, uid, pwd, "product.product", "search_count", [[["default_code", "=", sku]]])
        (existentes if n else faltantes).append(sku)
    return existentes, faltantes


def po_manual_existente(emb_num: str):
    """PO ya cargada a mano en Odoo para este embarque (partner_ref contiene 26TP####)."""
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD")
    url = "https://unionxb2b.odoo.com"; db = "bmya-innovatek-sh-prd-6981800"
    uid = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common").authenticate(db, "andres@grupoeter.cl", pwd, {})
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return [p["name"] for p in models.execute_kw(db, uid, pwd, "purchase.order", "search_read",
            [[["partner_ref", "ilike", emb_num], ["state", "!=", "cancel"]]], {"fields": ["name"]})]


def procesar_embarque(emb_num: str, reg: dict, dry_run: bool = True):
    pos = po_manual_existente(emb_num)
    if pos and not reg.get("po_parcial"):
        # Cargado a mano en Odoo → no costear/escalar más (evita falsas alarmas y PO duplicada)
        reg["po_name"] = ",".join(pos)
        st.set_fase(reg, 9, f"PO ya existente en Odoo ({', '.join(pos)}) → COMPLETADO")
        return
    pi_path, pl_path = resolver_archivos(reg)
    if not pi_path or not pl_path:
        st.log(reg, f"FALTA archivo local (PI={bool(pi_path)} PL={bool(pl_path)}) → no puedo costear aún")
        return
    print(f"\n--- Costeando {emb_num} ---\n  PI: {pi_path.name}\n  PL: {pl_path.name}")

    productos, inland, numero, puerto = ce.leer_pi(pi_path)
    ce.leer_pl(pl_path, productos)
    aplicar_alias(productos, reg)
    sku_por_historial(productos, reg, emb_num)
    tar = construir_tarifas(reg, puerto)
    embq = ce.Embarque(numero=numero or emb_num, puerto=puerto,
                       puerto_nombre=PUERTOS.get(puerto, puerto),
                       productos=productos, inland_china=inland, tarifas=tar)
    ce.calcular_costeo(embq)
    if MAESTRA.exists():
        try: ce.comparar_con_maestra(embq, MAESTRA)
        except Exception as e: print(f"  (aviso: comparar_con_maestra falló: {e})")

    out_dir = OUT / emb_num; out_dir.mkdir(parents=True, exist_ok=True)
    precosteo = ce.generar_precosteo_xlsx(embq, out_dir)
    reg["costeo_path"] = str(precosteo)

    existentes, faltantes = odoo_sku_check(productos)
    sin_sku = sorted({p.model for p in productos if not (p.sku or "").strip()})  # productos sin código en el PI
    reg["skus"] = [p.sku for p in productos if p.sku]
    reg["skus_faltantes"] = faltantes
    reg["productos_sin_sku"] = sin_sku
    pendientes = len(faltantes) + len(sin_sku)
    st.log(reg, f"costeado · {len(productos)} prod · sobrecosto {embq.sobrecosto_pct:.1f}% · "
                f"internado {embq.total_internado_clp:,.0f} CLP · SKU por crear: {len(faltantes)} · sin SKU: {len(sin_sku)}")
    print(f"  SKU existentes: {len(existentes)} | POR CREAR: {faltantes or '—'} | SIN SKU en PI: {sin_sku or '—'}")

    sugeridos = reg.get("sku_sugerido") or {}
    reg["pendientes_detalle"] = [
        {"model": p.model, "sku": (p.sku or "").strip() or "(sin código)", "qty": int(p.qty),
         "desc": str(p.descripcion).splitlines()[0][:60] if p.descripcion else "",
         **({"sugerido": sugeridos[str(p.model).strip()]["sku"]} if str(p.model).strip() in sugeridos else {})}
        for p in productos
        if (p.sku or "").strip() in faltantes or not (p.sku or "").strip()]

    if not dry_run:
        _enviar_correo(embq, reg, out_dir, faltantes, sin_sku)

    # gate a fase 4: todos los SKU existen y ningún producto sin código
    if pendientes == 0:
        st.set_fase(reg, 4, "todos los productos con SKU en Odoo → cargar PO")
    elif not faltantes and not reg.get("po_parcial"):
        # Solo quedan ítems SIN código (muestras, etc.): NO bloquean → PO parcial con lo que tiene SKU
        if dry_run:
            st.log(reg, f"(dry-run) cargaría PO parcial sin {sin_sku}")
        else:
            import fase4_odoo as f4  # import local: fase4 importa este módulo
            f4.procesar_embarque(emb_num, reg, dry_run=False, parcial=True)
    else:
        st.log(reg, f"pendientes ({len(faltantes)} por crear + {len(sin_sku)} sin código) → re-chequea Odoo mañana")


def _enviar_correo(embq, reg, out_dir, faltantes, sin_sku=None):
    """Opción B (100% autónomo): ENVÍA el correo al equipo (no borrador).
    Idempotente: solo re-envía si cambió la lista de pendientes (no spamea cada día)."""
    from gmail_client import GmailClient
    sin_sku = sin_sku or []
    firma = f"{sorted(faltantes)}|{sorted(sin_sku)}"
    if reg.get("correo_firma") == firma:
        st.log(reg, "correo ya enviado con estos pendientes → no re-envío")
        return
    html_path = ce.generar_email_html(embq, out_dir)
    html = Path(html_path).read_text(encoding="utf-8")
    if faltantes:
        html += ("<div style='background:#fef9e7;border-left:4px solid #f1c40f;padding:12px;margin:16px 0'>"
                 f"<b>⚠️ SKU por crear en Odoo ({len(faltantes)}):</b> {', '.join(faltantes)}</div>")
    if sin_sku:
        html += ("<div style='background:#fdecea;border-left:4px solid #e74c3c;padding:12px;margin:16px 0'>"
                 f"<b>⚠️ Productos del PI SIN SKU ({len(sin_sku)}) — no van en la PO (se carga parcial con el resto):</b> "
                 f"{', '.join(sin_sku)}</div>")
    otros = embq.inland_china.no_reconocidos
    if otros:
        lista = "<br>".join(f"{str(o['descripcion']).splitlines()[0][:60]}: US${o['amount']:,.2f}" for o in otros)
        html += ("<div style='background:#f4f6f7;border-left:4px solid #7f8c8d;padding:12px;margin:16px 0'>"
                 f"<b>Cargos de la PI que no son productos ni gastos conocidos ({len(otros)}) — incluidos en el costo "
                 f"como gasto en China; revisar si alguno es un producto:</b><br>{lista}</div>")
    def _filas(d):
        return "<br>".join(f"{m} → <b>{v['sku']}</b> {v.get('nombre', '')} (mismo modelo en "
                           f"{', '.join(v['embarques'][-3:])}; último US${v['precio_hist']:g})" for m, v in d.items())
    hist = reg.get("sku_historial") or {}
    if hist:
        html += ("<div style='background:#eaf2fb;border-left:4px solid #2e86c1;padding:12px;margin:16px 0'>"
                 f"<b>🔎 Venían SIN código en el PI y se asignaron por el historial de la Maestra ({len(hist)}) — "
                 f"van en la PO; si alguno no corresponde, avisar:</b><br>{_filas(hist)}</div>")
    sug = reg.get("sku_sugerido") or {}
    if sug:
        html += ("<div style='background:#f4f6f7;border-left:4px solid #7f8c8d;padding:12px;margin:16px 0'>"
                 f"<b>❓ SKU probable según el historial ({len(sug)}) — NO van en la PO hasta que alguien lo "
                 f"confirme (el mismo modelo ya se usó para otros productos):</b><br>{_filas(sug)}</div>")
    subj = f"[{embq.numero}] Costeo importación — {embq.puerto_nombre} — {embq.sobrecosto_pct:.1f}%"
    pend = len(faltantes) + len(sin_sku)
    if pend:
        subj += f" · {pend} SKU pendientes"
    gmail = GmailClient()
    adjuntos = [reg["costeo_path"]] if reg.get("costeo_path") and Path(reg["costeo_path"]).exists() else []
    msg_id = gmail.send_email_with_attachments(
        to=", ".join(DEST), subject=subj, body_html=html, attachments=adjuntos)
    reg["correo_firma"] = firma
    accion = "borrador con planilla" if str(msg_id).startswith("[DRAFT]") else "correo ENVIADO con planilla"
    st.log(reg, f"{accion} ({msg_id}, {len(adjuntos)} adj) → {', '.join(DEST)}")


CC_RESUMEN = ["andres@unionx.cl"]
DIAS_URGENTE = 7                                  # ETA bodega a <= 7 días (o vencida) → URGENTE
DIGEST_FILE = BASE / "data" / "digest_semanal.json"


def resumen_lunes(estado: dict, dry_run: bool = True):
    """UN solo correo, los LUNES (hora Chile), con todos los embarques detenidos en fase 3,
    ordenados por ETA bodega. URGENTE solo si la ETA es en <= DIAS_URGENTE días o ya pasó.
    Una vez por lunes (DIGEST_FILE). FORZAR_RESUMEN=1 lo fuerza (pruebas)."""
    import json
    from zoneinfo import ZoneInfo
    hoy = datetime.now(ZoneInfo("America/Santiago")).date()
    forzar = os.environ.get("FORZAR_RESUMEN") == "1"
    if hoy.weekday() != 0 and not forzar:
        return
    meta = json.loads(DIGEST_FILE.read_text(encoding="utf-8")) if DIGEST_FILE.exists() else {}
    if meta.get("ultimo") == hoy.isoformat() and not forzar:
        return
    filas = []
    for emb, r in estado.items():
        if r.get("fase") != 3:
            continue
        eta = (r.get("eta_bodega") or "")[:10]
        try:
            dias = (datetime.strptime(eta, "%Y-%m-%d").date() - hoy).days
        except Exception:
            dias = None
        urg = dias is not None and dias <= DIAS_URGENTE
        filas.append((dias if dias is not None else 999, emb, eta, urg, r))
    if not filas:
        return
    filas.sort(key=lambda f: (f[0], f[1]))
    td = "padding:6px;border:1px solid #ddd;vertical-align:top"
    html_filas = ""
    for dias, emb, eta, urg, r in filas:
        det = r.get("pendientes_detalle")
        if det:
            items = "<br>".join(f"{d['sku']} · {d['model']} · {d['qty']} u · {d['desc']}"
                                + (f" → ¿<b>{d['sugerido']}</b>?" if d.get("sugerido") else "") for d in det)
        else:  # registro previo al detalle: solo códigos
            items = "<br>".join([*(r.get("skus_faltantes") or []),
                                 *[f"{m} (sin código)" for m in (r.get("productos_sin_sku") or [])]]) or "—"
        estado_txt = "🔴 URGENTE" if urg else "Informativo"
        cuando = "s/ETA" if dias == 999 else ("vencida" if dias < 0 else f"en {dias} días")
        po = f"PO parcial {r['po_name']}" if r.get("po_parcial") and r.get("po_name") else "sin PO"
        html_filas += (f"<tr><td style='{td}'><b>{emb}</b></td><td style='{td}'>{eta} ({cuando})</td>"
                       f"<td style='{td}'>{estado_txt}</td><td style='{td}'>{po}</td>"
                       f"<td style='{td};font-size:12px'>{items}</td></tr>")
    n_urg = sum(1 for f in filas if f[3])
    html = ("<div style='font-family:Arial,sans-serif;font-size:14px;color:#333'>"
            f"<p>Resumen semanal: <b>{len(filas)} embarque(s) detenidos</b> esperando SKU en Odoo"
            + (f", <b>{n_urg} urgente(s)</b> (ETA en {DIAS_URGENTE} días o menos, o vencida)" if n_urg else "")
            + ".</p><table style='border-collapse:collapse'><tr style='background:#1F3864;color:#fff'>"
            "<th style='padding:6px'>Embarque</th><th style='padding:6px'>ETA bodega</th>"
            "<th style='padding:6px'>Estado</th><th style='padding:6px'>PO</th>"
            f"<th style='padding:6px'>Pendiente (SKU · modelo · qty · producto)</th></tr>{html_filas}</table>"
            "<p>Los SKU por crear bloquean la PO: favor crearlos en Odoo con ese código exacto. "
            "Los ítems <i>sin código</i> no bloquean (la PO se carga parcial sin ellos).</p>"
            + _linea_maestra() + "<p>Saludos.</p></div>")
    subj = (f"Resumen semanal COMEX — {len(filas)} embarque(s) detenidos"
            + (f" · 🔴 {n_urg} urgente(s)" if n_urg else ""))
    if dry_run:
        print(f"(dry-run) resumen lunes: {subj}")
        return html
    from gmail_client import GmailClient
    mid = GmailClient().send_email_with_attachments(to=", ".join(DEST), subject=subj,
                                                    body_html=html, cc=CC_RESUMEN)
    DIGEST_FILE.write_text(json.dumps({"ultimo": hoy.isoformat(), "msg_id": mid,
                                       "embarques": [f[1] for f in filas]}, indent=2), encoding="utf-8")
    print(f"Resumen semanal enviado ({mid}) · {len(filas)} embarques · {n_urg} urgentes")


def _linea_maestra() -> str:
    """Estado de la Maestra de Importaciones (lo vigila vigia_maestra.py; el detalle le llega solo a Andrés)."""
    try:
        import vigia_maestra
        return vigia_maestra.linea_resumen()
    except Exception as e:
        print(f"  (línea Maestra del resumen falló: {e})")
        return ""


def procesar(dry_run: bool = True) -> dict:
    estado = st.cargar()
    pend = [e for e, r in estado.items() if r.get("fase") == 3]
    if not pend:
        print("No hay embarques en fase 3.")
        return estado
    print(f"Embarques en fase 3 (costeo): {pend}")
    for emb in pend:
        try:
            procesar_embarque(emb, estado[emb], dry_run=dry_run)
        except Exception as e:
            st.log(estado[emb], f"ERROR costeo: {type(e).__name__}: {e}")
    try:
        resumen_lunes(estado, dry_run=dry_run)
    except Exception as e:
        print(f"  (resumen semanal falló: {type(e).__name__}: {e})")
    st.guardar(estado)
    print("\nEstado actual:")
    print(st.resumen(estado))
    return estado


if __name__ == "__main__":
    dry = "--commit" not in sys.argv
    print(f"=== FASE 3 · costeo + SKUs + borrador {'(dry-run, sin borrador)' if dry else '(commit)'} ===")
    procesar(dry_run=dry)
