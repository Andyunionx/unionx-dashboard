# -*- coding: utf-8 -*-
"""Pulso NC semanal (lunes) — estado del ciclo de notas de crédito.

REDISEÑO 07-09-2026 (Andrés). El pulso mostraba "NC por emitir" con un criterio
más laxo que el del agente que las emite: pedía solo boleta posteada y sin NC,
sin validar el plazo legal de 3 meses ni el resto de las reglas. Resultado: 433
casos "emitibles" de los cuales solo 57 lo eran de verdad. El resto se acumulaba
sin salida y el número subía semana a semana en vez de mostrar linealidad.

Ahora el pulso mide EL MISMO universo sobre el que actúa el agente y separa por
QUIÉN TIENE QUE ACTUAR:

  0. EMITIDAS por el agente la semana pasada  -> nadie, es la foto de lo hecho
  1. DEVOLUCIÓN (agente `agente_tickets_nc.py`, corrido en DRY-RUN por este script)
       EN COLA          -> nadie: sale sola en la próxima corrida horaria
       RETENIDAS        -> Max: cumplen las reglas pero no están en la lista autorizada
       MANUAL           -> Facturación: canales que se emiten a mano (nc_reglas.py)
       OC POR CORREGIR  -> Max: la OC del ticket no calza con un pedido de Odoo
       POR REVISAR      -> Max: producto/cantidad del ticket no calza con la boleta
       FUERA DE PLAZO   -> solo en el Excel, no en el correo (Andrés 20-10: 708 de las
                           915 OC tenían la boleta pagada)
       EXCLUIDA         -> Fulfillment (se descuenta en la liquidación, no lleva NC)
     Hasta el 19-10 esta sección leía las planillas SAC (agente_nc.py), que ya no se
     actualizan: mostraba las mismas cifras semana tras semana (Max, 19-10).
  2. CANCELACIÓN — SIN AGENTE, y así se mantiene (decisión Andrés 07-09).
       El pulso solo informa y presiona; nadie emite NC de cancelación en
       automático. Quien valida con el marketplace es FACTURACIÓN.

El reloj del plazo de 3 meses corre desde la fecha de la BOLETA, no desde la
fecha en que se registró la cancelación en Odoo (que es lo que se usaba antes y
hacía ver todo como reciente).

REGLA PERMANENTE: este pulso INFORMA — nunca crea NC en Odoo.
"""
_DOC_ANTERIOR = """Pulso NC semanal (lunes) — NC por emitir por DEVOLUCIÓN y por CANCELACIÓN, por mes y canal.

Origen: inputs de Víctor 04/05-08-2026 (vía Andrés + su respuesta al borrador):
  1. Fulfillment NO lleva NC (se descuenta en la liquidación factura) → excluido.
  2. Cancelación — CRITERIO VÍCTOR (05-08): NC directa = pedido cancelado + boleta
     posteada + SIN DESPACHO. Los cancelados CON despacho son devoluciones
     marketplace (Paris/Fala/Walmart/Ripley pagan y luego descuentan) → validar
     estado seller antes de NC. Barridas masivas (16-jun/fines-jul, resoluciones
     de marketplace sincronizadas por el conector) fuera del pulso.
  3. REGLA PERMANENTE: este pulso INFORMA — nunca crea NC en Odoo.

Pipeline lunes: agente_nc.py (refresca universo SAC+Odoo) → este script.
NOTA: la sección cancelación hoy lee el archivo auditado estático
(NC_cancelados_AUDITADO_v4_20260805.xlsx); antes de encronar hay que hacer vivo
ese recálculo (cancelados 2026 + boleta + flag despachado + filtros de auditoría).

Uso: python pulso_nc_semanal.py [--draft]   (--draft: envía SOLO a DRAFT_TO)
Destinatarios producción (EMAIL_TO env o default): camila@melollevo.cl,
favila@melollevo.cl (Fernanda Ávila), victor@grupoeter.cl, maximiliano@unionx.cl,
facturacion@melollevo.cl + andres@unionx.cl en copia.

RECONSTRUIDO 13-08-2026: el original (05-08) fue borrado del disco por el sync
de Drive antes de llegar a git — mismo patrón que agente_nc.py.
"""
import os, sys, re, json, time, argparse, datetime, base64, mimetypes
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
OUT = ROOT / "data" / "outputs"
AZ = "#1E3A5F"; GR = "#EBF0F8"; AMB = "#FFF3CD"

TO_PROD = [e.strip() for e in os.environ.get(
    "EMAIL_TO",
    "camila@melollevo.cl,favila@melollevo.cl,victor@grupoeter.cl,"
    "maximiliano@unionx.cl,facturacion@melollevo.cl").split(",") if e.strip()]
CC_PROD = ["andres@unionx.cl"]
DRAFT_TO = ["victor@grupoeter.cl"]; DRAFT_CC = ["andres@unionx.cl"]

# Plazo legal para emitir una NC, contado desde la fecha de la boleta.
PLAZO_NC_MESES = 3
# Boletas anteriores a 2026 son legacy (BSALE, decisión 20-jul): no entran a "fuera de plazo".
DESDE_BOLETA = "2026-01-01"
# Marca que el agente deja en `ref` de las NC que emite.
TAG_AGENTE = "AGENTE-PV"


def fmt(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,.0f}".format(n).replace(",", ".")


def tabla_html(df, index_name="mes", conteos=()):
    """`conteos`: columnas que son cantidades (se muestran sin signo $)."""
    cols = df.columns.tolist()
    head = "".join(f'<th style="padding:5px 10px;">{c}</th>' for c in [index_name] + cols)
    rows = ""
    for i, (idx, r) in enumerate(df.iterrows()):
        tds = "".join(f'<td style="padding:5px 10px;text-align:right;">'
                      f'{(miles(v) if c in conteos else fmt(v)) if v else "—"}</td>' for c, v in r.items())
        rows += f'<tr style="background:{GR if i % 2 == 0 else "#fff"};"><td style="padding:5px 10px;">{idx}</td>{tds}</tr>'
    return (f'<table style="border-collapse:collapse;font-size:12px;margin:6px 0;">'
            f'<tr style="background:{AZ};color:#fff;text-align:left;">{head}</tr>{rows}</table>')


def enviar(asunto, html, adjunto_path, to, cc):
    from email.message import EmailMessage
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    cj = os.environ.get("GMAIL_TOKEN_JSON", "")
    info = json.loads(cj) if cj else json.load(open(ROOT / "agente-comex/config/token.json"))
    creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    svc = build("gmail", "v1", credentials=creds)
    msg = EmailMessage()
    msg["To"] = ", ".join(to); msg["Cc"] = ", ".join(cc)
    msg["From"] = "andres@unionx.cl"; msg["Subject"] = asunto
    msg.add_alternative(html, subtype="html")
    mt, st = (mimetypes.guess_type(str(adjunto_path))[0]).split("/")
    msg.add_attachment(Path(adjunto_path).read_bytes(), maintype=mt, subtype=st,
                       filename=Path(adjunto_path).name)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    for i in range(3):
        try:
            return svc.users().messages().send(userId="me", body={"raw": raw}).execute()["id"]
        except Exception as e:
            print(f"send intento {i+1}: {type(e).__name__}"); time.sleep(8)


def _rpc_conn():
    import xmlrpc.client, time as _t
    cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
    pw = os.environ.get("ANDRES_ODOO_PASSWORD", "") or (ROOT / "odoo/.odoo_pass").read_text().strip()
    uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(cfg["db_name"], cfg["username"], pw, {})
    def rpc(model, method, args, kw=None):
        for i in range(3):
            try:
                return xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object").execute_kw(
                    cfg["db_name"], uid, pw, model, method, args, kw or {})
            except Exception:
                if i == 2:
                    raise
                _t.sleep(5)
    return rpc


def devoluciones_agente(hoy):
    """Corre el agente de tickets en DRY-RUN (no escribe nada en Odoo: ni NC ni campos) y
    devuelve las hojas de su Excel de validación. Así el pulso mide exactamente el mismo
    universo y las mismas reglas que el agente que emite (nc_reglas.py)."""
    import subprocess
    xls = OUT / f"NC_agente_dryrun_{hoy:%Y%m%d}.xlsx"
    r = subprocess.run([sys.executable, str(ROOT / "agente_tickets_nc.py"), "--dry-run", "--excel", str(xls)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    print(r.stdout[-1200:])
    if r.returncode != 0 or not xls.exists():
        raise RuntimeError(f"el agente en dry-run falló (exit {r.returncode}): {r.stderr[-600:]}")
    return pd.read_excel(xls, sheet_name=None)


def oc_y_monto(d, col):
    """(OC distintas, monto) — el monto viene repetido en cada ticket de la misma OC."""
    if not len(d):
        return 0, 0
    u = d.drop_duplicates("oc")
    return len(u), u[col].sum()


def nc_emitidas_agente(desde, hasta):
    """NC que el agente emitió en la ventana, con la boleta que reversan y su
    fecha de venta. Es la sección 0 del pulso: la foto de lo ya ejecutado."""
    rpc = _rpc_conn()
    ncs = rpc("account.move", "search_read",
              [[("move_type", "=", "out_refund"), ("ref", "like", f"%{TAG_AGENTE}%"),
                ("invoice_date", ">=", str(desde)), ("invoice_date", "<=", str(hasta))]],
              {"fields": ["name", "invoice_date", "amount_total", "state", "ref",
                          "reversed_entry_id", "l10n_cl_dte_status"], "limit": 5000})
    if not ncs:
        return pd.DataFrame()
    d = pd.DataFrame(ncs)
    oid = [r[0] for r in d["reversed_entry_id"] if r]
    bol = {}
    for i in range(0, len(oid), 300):
        for b in rpc("account.move", "read", [oid[i:i+300]],
                     {"fields": ["id", "name", "invoice_date", "invoice_origin"]}):
            bol[b["id"]] = b
    gb = lambda r, c: bol.get(r[0], {}).get(c) if r else None
    d["boleta"] = d["reversed_entry_id"].map(lambda r: gb(r, "name"))
    d["fecha_venta"] = pd.to_datetime(d["reversed_entry_id"].map(lambda r: gb(r, "invoice_date")),
                                      errors="coerce")
    d["pedido"] = d["reversed_entry_id"].map(lambda r: str(gb(r, "invoice_origin") or ""))
    d["fecha_nc"] = pd.to_datetime(d["invoice_date"], errors="coerce")
    d["dias_venta_a_nc"] = (d["fecha_nc"] - d["fecha_venta"]).dt.days
    d["tickets"] = d["ref"].map(lambda r: ", ".join("#" + x for x in re.findall(r"#(\d+)", str(r))))

    # motivo y estado del producto, desde el ticket que originó la NC
    trefs = sorted({x for r in d["ref"] for x in re.findall(r"#(\d+)", str(r))})
    tk = {}
    for i in range(0, len(trefs), 200):
        try:
            for t in _jrpc("helpdesk.ticket", "search_read",
                           [["ticket_ref", "in", [int(x) for x in trefs[i:i+200]]]],
                           fields=["ticket_ref", "properties"], limit=1000):
                tk[str(t["ticket_ref"])] = t
        except Exception as e:
            print(f"[nc-agente][WARN] tickets: {type(e).__name__}")
            break

    def _prop(t, etiqueta):
        for p in (t.get("properties") or []):
            if str(p.get("string") or "").strip().lower() != etiqueta.lower():
                continue
            v = p.get("value")
            if v in (None, False, ""):
                return ""
            if p.get("type") == "selection":
                return dict(p.get("selection") or []).get(v, str(v))
            if p.get("type") == "many2one" and isinstance(v, list):
                return str(v[1])
            return str(v)
        return ""

    def _agg(ref, etiqueta):
        vals = {_prop(tk[x], etiqueta) for x in re.findall(r"#(\d+)", str(ref)) if x in tk}
        vals = sorted(v for v in vals if v)
        return " / ".join(vals)

    for col, et in [("motivo", "Motivo"), ("estado_producto", "Estado"),
                    ("canal", "Canal"), ("producto", "Producto Comprado"),
                    ("resolucion", "Resolución")]:
        d[col] = d["ref"].map(lambda r: _agg(r, et))
    d = d.drop(columns=["reversed_entry_id", "invoice_date"])
    return d.sort_values("amount_total", ascending=False)


def _jrpc(model, method, dominio, **kw):
    """JSON-RPC: el campo `properties` de helpdesk trae nulos que XML-RPC no
    sabe serializar."""
    import requests
    cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
    pw = os.environ.get("ANDRES_ODOO_PASSWORD", "") or (ROOT / "odoo/.odoo_pass").read_text().strip()
    import xmlrpc.client
    uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(
        cfg["db_name"], cfg["username"], pw, {})
    r = requests.post(cfg["url"] + "/jsonrpc", json={"jsonrpc": "2.0", "method": "call", "params": {
        "service": "object", "method": "execute_kw",
        "args": [cfg["db_name"], uid, pw, model, method, [dominio], kw]}, "id": 1}, timeout=300).json()
    if "error" in r:
        raise RuntimeError(str(r["error"])[:200])
    return r["result"]


def recompute_cancelados() -> pd.DataFrame:
    """Recalcula EN VIVO el universo de cancelados 2026 con boleta y sin NC.
    Filtros de auditoría (04/05-08): sin NC por reversa directa, sin fulfillment,
    flag despachado (criterio Víctor), y detección de BARRIDAS del conector
    (>50 cancelaciones con la misma fecha de modificación → resolución masiva de
    marketplace, se excluyen y se informan aparte)."""
    import xmlrpc.client, time as _t
    cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
    pw = os.environ.get("ANDRES_ODOO_PASSWORD", "") or (ROOT / "odoo/.odoo_pass").read_text().strip()
    uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(cfg["db_name"], cfg["username"], pw, {})
    def rpc(model, method, args, kw=None):
        for i in range(3):
            try:
                return xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object").execute_kw(
                    cfg["db_name"], uid, pw, model, method, args, kw or {})
            except Exception:
                if i == 2:
                    raise
                _t.sleep(5)
    canc = rpc("sale.order", "search_read",
               [[("state", "=", "cancel"), ("create_date", ">=", "2026-01-01"), ("invoice_ids", "!=", False)]],
               {"fields": ["id", "name", "team_id", "invoice_ids", "channel_order_reference", "write_date"]})
    inv_ids = sorted({i for s in canc for i in s["invoice_ids"]})
    invs = {}
    for i in range(0, len(inv_ids), 300):
        for v in rpc("account.move", "read", [inv_ids[i:i+300]],
                     {"fields": ["move_type", "state", "payment_state", "name", "amount_total", "invoice_date"]}):
            invs[v["id"]] = v
    # NC por reversa directa de las boletas
    bol_ids = [v["id"] for v in invs.values() if v["move_type"] == "out_invoice" and v["state"] == "posted"]
    rev = set()
    for i in range(0, len(bol_ids), 300):
        for r in rpc("account.move", "search_read",
                     [[("move_type", "=", "out_refund"), ("state", "=", "posted"),
                       ("reversed_entry_id", "in", bol_ids[i:i+300])]], {"fields": ["reversed_entry_id"]}):
            rev.add(r["reversed_entry_id"][0])
    # fulfillment + despachado por pedido
    oids = [s["id"] for s in canc]
    ff, desp = set(), set()
    for i in range(0, len(oids), 200):
        for p in rpc("stock.picking", "search_read", [[("sale_id", "in", oids[i:i+200])]],
                     {"fields": ["sale_id", "location_id", "state", "picking_type_id"]}):
            bod = str(p["location_id"][1] if p["location_id"] else "").split("/")[0]
            if bod.startswith("BF"):
                ff.add(p["sale_id"][0])
            if p["state"] == "done":
                desp.add(p["sale_id"][0])
    def canal_de(s):
        ref = str(s.get("channel_order_reference") or "")
        t = s["team_id"][1] if s["team_id"] else ""
        if ref.startswith("#"): return "Shopify"
        if ref.startswith("20000"): return "Mercado Libre"
        if ref.isdigit() and len(ref) == 10: return "Falabella"
        if t and t != "Melollevo": return t
        return "Otro marketplace"
    rows, ff_rows = [], []
    for s in canc:
        ivs = [invs[i] for i in s["invoice_ids"] if i in invs]
        bol = [v for v in ivs if v["move_type"] == "out_invoice" and v["state"] == "posted"
               and v["payment_state"] != "reversed" and v["id"] not in rev]
        ncs = [v for v in ivs if v["move_type"] == "out_refund" and v["state"] == "posted"]
        if not bol or ncs:
            continue
        b = bol[0]
        r = {"pedido": s["name"], "canal": canal_de(s), "mes": str(b["invoice_date"])[:7],
             # fecha EXACTA de la boleta: es el reloj del plazo legal de 3 meses
             "fecha_boleta": str(b["invoice_date"])[:10],
             "boleta": b["name"], "monto": b["amount_total"], "pago_boleta": b["payment_state"],
             "despachado": s["id"] in desp, "dia_cancel": str(s["write_date"])[:10]}
        # Fulfillment se excluye (el marketplace lo descuenta en la liquidación,
        # no lleva NC) pero se guarda aparte para poder informar cuánto es.
        (ff_rows if s["id"] in ff else rows).append(r)
    globals()["_CANCEL_FF"] = pd.DataFrame(ff_rows)
    C = pd.DataFrame(rows)
    if C.empty:
        C = pd.DataFrame(columns=["pedido", "canal", "mes", "boleta", "monto", "pago_boleta",
                                  "despachado", "dia_cancel", "origen"])
        return C
    # barridas: >50 cancelados con la misma fecha de modificación
    masivos = C["dia_cancel"].value_counts()
    dias_barrida = set(masivos[masivos > 50].index)
    C["origen"] = C["dia_cancel"].map(lambda d: "Barrida conector" if d in dias_barrida else "Cancelación orgánica")
    print(f"[cancelados-vivo] {len(C)} casos | barridas detectadas: {sorted(dias_barrida)}")
    return C


def main():
    ap = argparse.ArgumentParser()
    # OJO: --draft NO crea un borrador, ENVÍA el correo a DRAFT_TO (Víctor).
    # Para probar sin mandarle nada a nadie, usar --no-enviar.
    ap.add_argument("--draft", action="store_true",
                    help="envía SOLO a DRAFT_TO (Víctor) — sigue siendo un envío real")
    ap.add_argument("--no-enviar", action="store_true",
                    help="calcula, escribe el Excel y muestra el resumen, sin enviar nada")
    a = ap.parse_args()
    hoy = datetime.date.today()
    semana = hoy.isocalendar()[1]

    # --- sección 1: devoluciones, desde los tickets de postventa con las reglas del
    # agente (corrida en dry-run). Desglose por canal solo en el Excel (Andrés 07-09).
    H = devoluciones_agente(hoy)

    def hoja(nombre, cols):
        # una hoja vacía viene sin columnas: se completan para que los filtros no fallen
        d = H.get(nombre, pd.DataFrame())
        return d.reindex(columns=list(dict.fromkeys(list(d.columns) + cols)))
    em = hoja("1 Emitiría el agente", ["oc", "pedido", "monto estimado"])
    ret = hoja("1b Retenidas", ["oc", "pedido", "monto estimado"])
    rev = hoja("2 Agente - revisar", ["estado", "motivo", "oc", "pedido", "fecha boleta", "monto estimado OC"])
    man = hoja("3 Manuales", ["grupo", "estado NC", "oc", "pedido", "fecha boleta", "monto estimado OC"])
    mot = rev["motivo"].astype(str)
    es_rev = rev["estado"] == "revisar"
    ff = rev[mot.str.contains("Fulfillment")]
    oc_mal = rev[es_rev & mot.str.contains("pedido no encontrado|pedido ambiguo|sin Nº de orden")]
    plazo = pd.concat([rev[mot.str.contains("fuera de plazo")],
                       man[man["estado NC"] == "fuera de plazo (3 meses)"]], ignore_index=True)
    plazo = plazo[plazo["fecha boleta"].astype(str) >= DESDE_BOLETA]
    dif = rev[es_rev & ~mot.str.contains("Fulfillment|fuera de plazo|pedido no encontrado|pedido ambiguo|sin Nº de orden")]
    manual = man[man["estado NC"] == "PENDIENTE NC"]
    n_plazo, m_plazo = oc_y_monto(plazo, "monto estimado OC")
    n_man, m_man = oc_y_monto(manual, "monto estimado OC")
    n_ff = ff["oc"].nunique()
    ped_dev = {str(p) for d in (em, ret, rev, man) if "pedido" in d for p in d["pedido"].dropna() if str(p)}

    # --- sección 0: lo que el agente YA emitió en los últimos 7 días
    lunes_ant = hoy - datetime.timedelta(days=7)
    try:
        emitidas = nc_emitidas_agente(lunes_ant, hoy)
    except Exception as e:
        print(f"[nc-agente][WARN] {type(e).__name__}: {e}")
        emitidas = pd.DataFrame()
    # La dimensión que explica el volumen es la FECHA DE VENTA que se reversa,
    # no el canal (el canal se ve en el Excel). Decisión Andrés 07-09.
    piv_emit = pd.DataFrame()
    if len(emitidas):
        e = emitidas.copy()
        e["Mes de la venta"] = e["fecha_venta"].dt.strftime("%Y-%m").fillna("sin fecha")
        e["est"] = e["estado_producto"].replace("", "sin dato")
        piv_emit = e.pivot_table(index="Mes de la venta", columns="est",
                                 values="amount_total", aggfunc="sum").fillna(0)
        piv_emit["TOTAL"] = piv_emit.sum(axis=1)
        piv_emit = piv_emit.sort_index()

    # --- sección 2: cancelaciones EN VIVO. CRITERIO VÍCTOR (05-08): NC directa =
    # cancelado + boleta + SIN despacho. Con despacho = validar estado seller.
    # Barridas del conector fuera (detección automática >50/día).
    try:
        C = recompute_cancelados()
        C.to_excel(OUT / f"NC_cancelados_vivo_{hoy:%Y%m%d}.xlsx", index=False)
    except Exception as e:
        print(f"[cancelados-vivo][WARN] {type(e).__name__}: {e} -> archivo auditado estático")
        C = pd.read_excel(OUT / "NC_cancelados_AUDITADO_v4_20260805.xlsx")
    barridas = C[C["origen"] != "Cancelación orgánica"]
    C = C[C["origen"] == "Cancelación orgánica"]
    # dedupe contra la sección devoluciones (un pedido no puede estar en ambas): los
    # cancelados con ticket de devolución se informan arriba, donde el agente los emite.
    en_dev = C["pedido"].astype(str).isin(ped_dev)
    C_dev = C[en_dev]
    C = C[~en_dev]
    # El reloj de los 3 meses corre desde la BOLETA, no desde `dia_cancel` (que es
    # cuándo se registró la cancelación en Odoo y hacía ver todo como reciente).
    C = C.copy()
    ref_can = pd.to_datetime(C.get("fecha_boleta"), errors="coerce")
    if ref_can.isna().all():
        ref_can = pd.to_datetime(C["mes"].astype(str) + "-01", errors="coerce")
    C["dias_para_vencer"] = (ref_can + pd.DateOffset(months=PLAZO_NC_MESES)
                             - pd.Timestamp(hoy)).dt.days
    C["vencida"] = C["dias_para_vencer"] < 0
    nucleo = C[~C["despachado"] & ~C["vencida"]]      # Facturación: emitir
    pagados = C[C["despachado"] & ~C["vencida"]]      # Facturación: validar con el marketplace
    vencidas = C[C["vencida"]]                        # Víctor: cómo se regulariza
    piv_can = None   # idem: el detalle por canal y mes va en el Excel
    cff = globals().get("_CANCEL_FF", pd.DataFrame())

    def semaforo(df):
        b = pd.cut(df["dias_para_vencer"], [-10**6, 0, 15, 30, 10**6],
                   labels=["ya vencido", "vence en menos de 15 días", "vence en 15 a 30 días", "más de 30 días"])
        r = df.groupby(b, observed=False).agg(pedidos=("pedido", "size"), monto=("monto", "sum"))
        return r[r["pedidos"] > 0]

    # --- excel adjunto
    fn = OUT / f"Pulso_NC_semana_{semana}_{hoy:%Y%m%d}.xlsx"
    with pd.ExcelWriter(fn) as w:
        if len(emitidas):
            emitidas.to_excel(w, sheet_name=f"0 EMITIDAS agente ({len(emitidas)})", index=False)
        em.to_excel(w, sheet_name=f"1 En cola ({len(em)})", index=False)
        ret.to_excel(w, sheet_name=f"1b Retenidas ({len(ret)})", index=False)
        manual.to_excel(w, sheet_name=f"2 Manual por emitir ({n_man})", index=False)
        oc_mal.to_excel(w, sheet_name=f"3 OC por corregir ({len(oc_mal)})", index=False)
        dif.to_excel(w, sheet_name=f"3b Por revisar ({len(dif)})", index=False)
        plazo.to_excel(w, sheet_name=f"4 Fuera de plazo ({n_plazo})", index=False)
        ff.to_excel(w, sheet_name=f"5 Fulfillment excluidas ({n_ff})", index=False)
        nucleo.to_excel(w, sheet_name=f"6 Cancel emitibles ({len(nucleo)})", index=False)
        pagados.to_excel(w, sheet_name=f"7 Cancel valida seller ({len(pagados)})", index=False)
        vencidas.to_excel(w, sheet_name=f"8 Cancel vencidas ({len(vencidas)})", index=False)
        if len(cff):
            cff.to_excel(w, sheet_name=f"9 Cancel fulfillment ({len(cff)})", index=False)
        if len(C_dev):
            C_dev.to_excel(w, sheet_name=f"10 Cancel con devolucion ({len(C_dev)})", index=False)

    aviso_borrador = ("" if not a.draft else
        f'<div style="padding:8px 12px;background:{AMB};border-left:4px solid #B8860B;font-size:13px;margin:8px 0;">'
        f'<b>BORRADOR para aprobación de formato.</b></div>')

    m_emit = emitidas["amount_total"].sum() if len(emitidas) else 0
    m_em = em["monto estimado"].sum() if len(em) else 0
    m_ret = ret["monto estimado"].sum() if len(ret) else 0
    man_txt = ""
    if n_man:
        g = manual.drop_duplicates("oc")["grupo"].value_counts()
        man_txt = " (" + ", ".join(f"{k} {miles(v)}" for k, v in g.items()) + ")"
    li_ret = ("" if not len(ret) else
              f"<li><b>RETENIDAS — {miles(len(ret))} NC · {fmt(m_ret)}</b>: cumplen todas las reglas, pero hoy el "
              f"agente emite solo la lista autorizada del 05-10. <b>→ Max</b>: validarlas para liberarlas.</li>")
    nota_dev = ("" if not len(C_dev) else
                f"Los {miles(len(C_dev))} pedidos cancelados que tienen ticket de devolución "
                f"({fmt(C_dev['monto'].sum())}) se cuentan arriba, en devolución. ")
    txt_ret = f"retenidas {fmt(m_ret)} · " if len(ret) else ""

    sec0 = "" if not len(emitidas) else f"""
<h3 style="color:{AZ};margin:16px 0 2px;">0. YA EMITIDAS por el agente — {miles(len(emitidas))} NC · {fmt(m_emit)}</h3>
<div style="font-size:12px;color:#475569;">Últimos 7 días. Emisión y posteo automáticos desde los tickets de postventa;
nadie tiene que hacer nada con esto. Abierto por <b>mes de la venta que se reversa</b> — la NC se emite hoy pero corrige una
venta anterior, y eso es lo que explica el volumen. Detalle NC por NC en la hoja <b>"0 EMITIDAS agente"</b> del adjunto.</div>
{tabla_html(piv_emit, index_name="Mes de la venta")}"""

    html = f"""<div style="font-family:Arial,sans-serif;color:#222;max-width:780px;line-height:1.5;">
<h2 style="color:{AZ};margin-bottom:2px;">🧾 Pulso NC</h2>
<div style="color:#64748b;font-size:12px;">Semana {semana} · {hoy.strftime('%d/%m/%Y')} · fuente: tickets de postventa + Odoo en vivo · este pulso informa, nunca crea NC</div>
{aviso_borrador}
{sec0}

<h3 style="color:{AZ};margin:16px 0 2px;">1. DEVOLUCIÓN — tickets de postventa</h3>
<div style="font-size:12px;color:#475569;">Mismos tickets y mismas reglas que usa el agente (simulación de hoy, sin emitir nada).
El agente <b>emite solo</b> lo que está EN COLA, en su corrida horaria; el resto necesita que alguien decida. Montos netos
estimados: precio de la boleta por las unidades del ticket. Desglose caso a caso y por canal en el Excel.</div>
<ul style="font-size:13px;margin:6px 0 12px 18px;padding:0;">
<li><b>EN COLA — {miles(len(em))} NC · {fmt(m_em)}</b>: sale sola. <i>Nadie tiene que actuar.</i></li>
{li_ret}
<li><b>MANUAL — {miles(n_man)} OC · {fmt(m_man)}</b>{man_txt}: canales que se emiten a mano. <b>→ Facturación</b>: emitir.</li>
<li><b>OC POR CORREGIR — {miles(len(oc_mal))} tickets</b>: la OC del ticket no calza con ningún pedido de Odoo, calza con más
de uno o viene vacía. <b>→ Max</b>: corregir la OC en el ticket (número de pedido real).</li>
<li><b>POR REVISAR — {miles(len(dif))} tickets</b>: el producto o la cantidad del ticket no calza con la boleta, o la OC tiene
más de una boleta. <b>→ Max</b>: revisar el ticket.</li>
<li><b>EXCLUIDA — {miles(n_ff)} OC</b>: Fulfillment, se descuenta en la liquidación del marketplace y no lleva NC.</li>
</ul>

<h3 style="color:{AZ};margin:16px 0 2px;">2. CANCELACIÓN — {miles(len(nucleo) + len(pagados))} pedidos · {fmt(nucleo['monto'].sum() + pagados['monto'].sum())}</h3>
<div style="font-size:12px;color:#475569;"><b>Acá no hay agente y no va a haberlo</b>: ninguna NC de cancelación se emite en
automático. Este bloque solo informa y hace seguimiento. Igual que en devolución, el <b>Fulfillment queda excluido</b>
({miles(len(cff))} pedidos · {fmt(cff['monto'].sum() if len(cff) else 0)}): el marketplace lo descuenta en la liquidación y no
lleva NC. {nota_dev}Desglose por canal y mes en el Excel.</div>
<ul style="font-size:13px;margin:6px 0 12px 18px;padding:0;">
<li><b>Por emitir — {miles(len(nucleo))} pedidos · {fmt(nucleo['monto'].sum())}</b>: cancelado + boleta posteada + SIN despacho
(criterio Víctor). <b>→ Facturación</b>: emitir la NC.</li>
<li><b>Esperando al marketplace — {miles(len(pagados))} pedidos · {fmt(pagados['monto'].sum())}</b>: cancelados CON despacho
hecho. El marketplace paga y luego descuenta en liquidación. <b>→ Facturación</b>: validar el estado en el seller center antes
de definir si corresponde NC.</li>
<li><b>Vencidas — {miles(len(vencidas))} pedidos · {fmt(vencidas['monto'].sum())}</b>: boleta con más de {PLAZO_NC_MESES} meses.
<b>→ Víctor</b>: cómo se regulariza.</li>
</ul>

<div style="padding:8px 12px;background:{AMB};border-left:4px solid #B8860B;font-size:13px;margin:10px 0;">
<b>⏳ Reloj de vencimiento de la cancelación</b> — la NC tiene {PLAZO_NC_MESES} meses desde la boleta:
{tabla_html(semaforo(C), index_name="plazo restante", conteos=("pedidos",))}</div>

<div style="font-size:12px;color:#475569;margin:8px 0;">Nota: quedaron FUERA de este pulso {miles(len(barridas))} pedidos
cancelados en barridas del conector (16-jun y fines de julio) por {fmt(barridas['monto'].sum())} — resoluciones de marketplace
en aclaración con facturación (ruteo enviado a Yohana 05-08). No corresponden a NC automática.</div>

<div style="font-size:13px;margin:12px 0;">📎 <b>Excel adjunto:</b> una hoja por bloque, con el detalle caso a caso.</div>
</div>"""

    asunto = (f"{'[BORRADOR] ' if a.draft else ''}🧾 Pulso NC · Semana {semana} · "
              f"emitidas {fmt(m_emit)} · en cola {fmt(m_em)} · "
              f"{txt_ret}"
              f"cancelación {fmt(nucleo['monto'].sum())}")
    if a.no_enviar:
        prev = OUT / f"Pulso_NC_semana_{semana}_{hoy:%Y%m%d}_PREVIEW.html"
        prev.write_text(f"<html><head><meta charset='utf-8'><title>{asunto}</title></head>"
                        f"<body style='margin:24px'><div style='font-family:Arial;font-size:12px;"
                        f"color:#64748b;margin-bottom:14px'><b>Asunto:</b> {asunto}<br>"
                        f"<b>Para:</b> {', '.join(TO_PROD)}<br><b>CC:</b> {', '.join(CC_PROD)}<br>"
                        f"<b>Adjunto:</b> {fn.name}</div><hr>{html}</body></html>", encoding="utf-8")
        print(f"\n[--no-enviar] NO se envía nada.")
        print(f"  Excel   : {fn}")
        print(f"  Preview : {prev}")
        print(f"  asunto seria: {asunto}")
        print(f"\n  0 EMITIDAS agente : {len(emitidas):>4} · {fmt(m_emit)}")
        print(f"  1 EN COLA              : {len(em):>4} NC · {fmt(m_em)}")
        print(f"  1b RETENIDAS           : {len(ret):>4} NC · {fmt(m_ret)}")
        print(f"  2 MANUAL               : {n_man:>4} OC · {fmt(m_man)}")
        print(f"  3 OC POR CORREGIR      : {len(oc_mal):>4} tickets")
        print(f"  3b POR REVISAR         : {len(dif):>4} tickets")
        print(f"  4 FUERA DE PLAZO       : {n_plazo:>4} OC · {fmt(m_plazo)}")
        print(f"  5 FULFILLMENT          : {n_ff:>4} OC")
        for nom, d_ in [("6 CANCEL por emitir", nucleo), ("7 CANCEL valida seller", pagados),
                        ("8 CANCEL vencidas", vencidas), ("10 CANCEL con devolución", C_dev)]:
            print(f"  {nom:23}: {len(d_):>4} · {fmt(d_['monto'].sum())}")
        return 0
    to = DRAFT_TO if a.draft else TO_PROD
    cc = DRAFT_CC if a.draft else CC_PROD
    print(f"Enviando a {to} cc {cc}...")
    mid = enviar(asunto, html, fn, to, cc)
    print("Enviado. msg_id:", mid)
    return 0 if mid else 1


if __name__ == "__main__":
    sys.exit(main())
