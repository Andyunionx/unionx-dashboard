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
  1. DEVOLUCIÓN (agente `agente_tickets_nc.py`)
       EN COLA        -> nadie: sale sola en la próxima corrida horaria
       FUERA DE PLAZO -> Víctor: decidir si se regulariza por otra vía
       BLOQUEADA      -> Max / Facturación / Bodega según la causa
       MANUAL         -> Kitchen Center (excluido del agente por regla de Max)
       EXCLUIDA       -> Fulfillment (se descuenta en la liquidación, no lleva NC)
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
# Canales que el agente NO toca por regla de Max (mail 26-08): gestión manual.
CANALES_MANUALES = {"Kitchen Center"}
# Marca que el agente deja en `ref` de las NC que emite.
TAG_AGENTE = "AGENTE-PV"


def fmt(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,.0f}".format(n).replace(",", ".")


def tabla_html(df, index_name="mes"):
    cols = df.columns.tolist()
    head = "".join(f'<th style="padding:5px 10px;">{c}</th>' for c in [index_name] + cols)
    rows = ""
    for i, (idx, r) in enumerate(df.iterrows()):
        tds = "".join(f'<td style="padding:5px 10px;text-align:right;">{fmt(v) if v else "—"}</td>' for v in r)
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


def overlay_estado_vivo(df: pd.DataFrame) -> pd.DataFrame:
    """Clasifica cada OC disponible según Odoo HOY: EMITIBLE (boleta posteada sin
    NC) / FULFILLMENT (no emitir: liquidación) / SIN BOLETA / YA TIENE NC / SIN
    PEDIDO MAPEADO. Regla Víctor 04-08."""
    rpc = _rpc_conn()
    peds = sorted(set(df["pedido"].dropna().astype(str)))
    so = rpc("sale.order", "search_read", [[("name", "in", peds)]], {"fields": ["id", "name", "invoice_ids"]})
    smap = {s["name"]: s for s in so}
    inv_ids = sorted({i for s in so for i in s["invoice_ids"]})
    invs = {}
    for i in range(0, len(inv_ids), 300):
        for v in rpc("account.move", "read", [inv_ids[i:i+300]],
                     {"fields": ["move_type", "state", "invoice_date"]}):
            invs[v["id"]] = v
    bol_ids = [v["id"] for v in invs.values() if v["move_type"] == "out_invoice" and v["state"] == "posted"]
    rev = set()
    for i in range(0, len(bol_ids), 300):
        for r in rpc("account.move", "search_read",
                     [[("move_type", "=", "out_refund"), ("state", "=", "posted"),
                       ("reversed_entry_id", "in", bol_ids[i:i+300])]], {"fields": ["reversed_entry_id"]}):
            rev.add(r["reversed_entry_id"][0])
    oids = [s["id"] for s in so]
    ffset = set()
    for i in range(0, len(oids), 200):
        for p in rpc("stock.picking", "search_read", [[("sale_id", "in", oids[i:i+200])]],
                     {"fields": ["sale_id", "location_id"]}):
            if str(p["location_id"][1] if p["location_id"] else "").split("/")[0].startswith("BF"):
                ffset.add(p["sale_id"][0])
    def clasificar(r):
        s = smap.get(str(r["pedido"]))
        if not s:
            return "SIN PEDIDO MAPEADO"
        ivs = [invs[i] for i in s["invoice_ids"] if i in invs]
        boletas = [v for v in ivs if v["move_type"] == "out_invoice" and v["state"] == "posted"]
        ncs = [v for v in ivs if v["move_type"] == "out_refund" and v["state"] == "posted"]
        if s["id"] in ffset:
            return "FULFILLMENT — no emitir (liquidación)"
        if ncs or any(b["id"] in rev for b in boletas):
            return "YA TIENE NC"
        if not boletas:
            return "SIN BOLETA — no emitir"
        return "EMITIBLE"
    def fecha_bol(r):
        """Fecha de la boleta: es el reloj del plazo legal de 3 meses."""
        s = smap.get(str(r["pedido"]))
        if not s:
            return None
        f = [invs[i].get("invoice_date") for i in s["invoice_ids"]
             if i in invs and invs[i]["move_type"] == "out_invoice"
             and invs[i]["state"] == "posted" and invs[i].get("invoice_date")]
        return min(f) if f else None

    df = df.copy()
    df["estado_vivo"] = df.apply(clasificar, axis=1)
    df["fecha_boleta"] = pd.to_datetime(df.apply(fecha_bol, axis=1), errors="coerce")
    print(f"[devoluciones-vivo] {df['estado_vivo'].value_counts().to_dict()}")
    return df


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


def clasificar_pipeline(df, hoy):
    """Separa las devoluciones según QUIÉN tiene que actuar. Replica las reglas
    del agente para que ambos midan lo mismo."""
    lim = pd.Timestamp(hoy) - pd.DateOffset(months=PLAZO_NC_MESES)
    df = df.copy()
    ref = df["fecha_boleta"].fillna(pd.to_datetime(df.get("fecha_compra"), errors="coerce"))
    df["fecha_ref"] = ref
    df["dias_para_vencer"] = (ref + pd.DateOffset(months=PLAZO_NC_MESES) - pd.Timestamp(hoy)).dt.days

    def bucket(r):
        if str(r["estado_vivo"]).startswith("FULFILLMENT"):
            return "EXCLUIDA — Fulfillment"
        if r["estado_vivo"] != "EMITIBLE":
            return "BLOQUEADA — " + str(r["estado_vivo"]).title()
        if str(r.get("canal")) in CANALES_MANUALES:
            return "MANUAL — Kitchen Center"
        if pd.notna(r["fecha_ref"]) and r["fecha_ref"] < lim:
            return "FUERA DE PLAZO"
        return "EN COLA"

    df["bucket"] = df.apply(bucket, axis=1)
    return df


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

    # --- sección 1: devoluciones. El agente escribe la hoja "N NC a emitir";
    # el overlay de estado vivo (boleta posteada / fulfillment / ya-NC) se
    # calcula AQUÍ en cada corrida (el agente pisa el archivo al regenerar).
    F = OUT / "NC_2026_DISPONIBLES_emitir.xlsx"
    xl = pd.ExcelFile(F)
    hoja_emitir = [s for s in xl.sheet_names if "emitir" in s.lower()][0]
    disp = xl.parse(hoja_emitir)
    disp = overlay_estado_vivo(disp)
    disp = clasificar_pipeline(disp, hoy)
    em = disp[disp["bucket"] == "EN COLA"]
    plazo = disp[disp["bucket"] == "FUERA DE PLAZO"]
    manual = disp[disp["bucket"] == "MANUAL — Kitchen Center"]
    bloq = disp[disp["bucket"].str.startswith("BLOQUEADA")]
    ff = disp[disp["bucket"] == "EXCLUIDA — Fulfillment"]
    piv_dev = None   # el desglose por canal va solo en el Excel (Andrés 07-09)

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
    # dedupe contra la sección devoluciones (un pedido no puede estar en ambas)
    C = C[~C["pedido"].astype(str).isin(set(disp["pedido"].astype(str)))]
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
                   labels=["ya vencido", "vence en <15 días", "15-30 días", "más de 30 días"])
        r = df.groupby(b, observed=False).agg(pedidos=("pedido", "size"), monto=("monto", "sum"))
        return r[r["pedidos"] > 0]

    # --- excel adjunto
    fn = OUT / f"Pulso_NC_semana_{semana}_{hoy:%Y%m%d}.xlsx"
    with pd.ExcelWriter(fn) as w:
        if len(emitidas):
            emitidas.to_excel(w, sheet_name=f"0 EMITIDAS agente ({len(emitidas)})", index=False)
        em.to_excel(w, sheet_name=f"1 En cola ({len(em)})", index=False)
        plazo.to_excel(w, sheet_name=f"2 Fuera de plazo ({len(plazo)})", index=False)
        bloq.to_excel(w, sheet_name=f"3 Bloqueadas ({len(bloq)})", index=False)
        manual.to_excel(w, sheet_name=f"4 Kitchen Center manual ({len(manual)})", index=False)
        ff.to_excel(w, sheet_name=f"5 Fulfillment excluidas ({len(ff)})", index=False)
        nucleo.to_excel(w, sheet_name=f"6 Cancel emitibles ({len(nucleo)})", index=False)
        pagados.to_excel(w, sheet_name=f"7 Cancel valida seller ({len(pagados)})", index=False)
        vencidas.to_excel(w, sheet_name=f"8 Cancel vencidas ({len(vencidas)})", index=False)
        if len(cff):
            cff.to_excel(w, sheet_name=f"9 Cancel fulfillment ({len(cff)})", index=False)

    aviso_borrador = ("" if not a.draft else
        f'<div style="padding:8px 12px;background:{AMB};border-left:4px solid #B8860B;font-size:13px;margin:8px 0;">'
        f'<b>BORRADOR para aprobación de formato.</b></div>')

    m_emit = emitidas["amount_total"].sum() if len(emitidas) else 0
    bloq_txt = ""
    if len(bloq):
        det = bloq.groupby("bucket").agg(n=("oc", "size"), m=("monto_NC", "sum"))
        bloq_txt = " · ".join(f'{k.replace("BLOQUEADA — ","")}: {miles(r.n)} ({fmt(r.m)})'
                              for k, r in det.iterrows())

    sec0 = "" if not len(emitidas) else f"""
<h3 style="color:{AZ};margin:16px 0 2px;">0. YA EMITIDAS por el agente — {miles(len(emitidas))} NC · {fmt(m_emit)}</h3>
<div style="font-size:12px;color:#475569;">Últimos 7 días. Emisión y posteo automáticos desde los tickets de postventa;
nadie tiene que hacer nada con esto. Abierto por <b>mes de la venta que se reversa</b> — la NC se emite hoy pero corrige una
venta anterior, y eso es lo que explica el volumen. Detalle NC por NC en la hoja <b>"0 EMITIDAS agente"</b> del adjunto.</div>
{tabla_html(piv_emit, index_name="Mes de la venta")}"""

    html = f"""<div style="font-family:Arial,sans-serif;color:#222;max-width:780px;line-height:1.5;">
<h2 style="color:{AZ};margin-bottom:2px;">🧾 Pulso NC</h2>
<div style="color:#64748b;font-size:12px;">Semana {semana} · {hoy.strftime('%d/%m/%Y')} · fuente: planillas SAC + Odoo en vivo · este pulso informa, nunca crea NC</div>
{aviso_borrador}
{sec0}

<h3 style="color:{AZ};margin:16px 0 2px;">1. DEVOLUCIÓN — estado del pipeline</h3>
<div style="font-size:12px;color:#475569;">El agente <b>emite solo</b> lo que está EN COLA, en su corrida horaria. El resto necesita
que alguien decida. Mismo criterio que usa el agente, para que ambos midan lo mismo. Desglose por canal en el Excel.</div>
<ul style="font-size:13px;margin:6px 0 12px 18px;padding:0;">
<li><b>EN COLA — {miles(len(em))} OC · {fmt(em['monto_NC'].sum())}</b>: sale sola. <i>Nadie tiene que actuar.</i></li>
<li><b>FUERA DE PLAZO — {miles(len(plazo))} OC · {fmt(plazo['monto_NC'].sum())}</b>: boleta con más de {PLAZO_NC_MESES} meses,
ya no admite NC. <b>→ Víctor</b>: definir si se regulariza por otra vía.</li>
<li><b>MANUAL — {miles(len(manual))} OC · {fmt(manual['monto_NC'].sum())}</b>: Kitchen Center, excluido del agente por regla.
<b>→ Facturación</b>: emitir a mano.</li>
{'<li><b>BLOQUEADAS</b>: ' + bloq_txt + ' <b>→ Max / Facturación</b>: revisar caso a caso.</li>' if bloq_txt else ''}
<li><b>EXCLUIDA — {miles(len(ff))} OC · {fmt(ff['monto_NC'].sum())}</b>: Fulfillment, se descuenta en la liquidación del
marketplace y no lleva NC.</li>
</ul>

<h3 style="color:{AZ};margin:16px 0 2px;">2. CANCELACIÓN — {miles(len(nucleo) + len(pagados))} pedidos · {fmt(nucleo['monto'].sum() + pagados['monto'].sum())}</h3>
<div style="font-size:12px;color:#475569;"><b>Acá no hay agente y no va a haberlo</b>: ninguna NC de cancelación se emite en
automático. Este bloque solo informa y hace seguimiento. Igual que en devolución, el <b>Fulfillment queda excluido</b>
({miles(len(cff))} pedidos · {fmt(cff['monto'].sum() if len(cff) else 0)}): el marketplace lo descuenta en la liquidación y no
lleva NC. Desglose por canal y mes en el Excel.</div>
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
{tabla_html(semaforo(C), index_name="plazo restante")}</div>

<div style="font-size:12px;color:#475569;margin:8px 0;">Nota: quedaron FUERA de este pulso {miles(len(barridas))} pedidos
cancelados en barridas del conector (16-jun y fines de julio) por {fmt(barridas['monto'].sum())} — resoluciones de marketplace
en aclaración con facturación (ruteo enviado a Yohana 05-08). No corresponden a NC automática.</div>

<div style="font-size:13px;margin:12px 0;">📎 <b>Excel adjunto:</b> una hoja por bloque, con el detalle caso a caso.</div>
</div>"""

    asunto = (f"{'[BORRADOR] ' if a.draft else ''}🧾 Pulso NC · Semana {semana} · "
              f"emitidas {fmt(m_emit)} · en cola {fmt(em['monto_NC'].sum())} · "
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
        for nom, d_, col in [("1 EN COLA", em, "monto_NC"),
                             ("2 FUERA DE PLAZO", plazo, "monto_NC"),
                             ("3 BLOQUEADAS", bloq, "monto_NC"),
                             ("4 KITCHEN CENTER", manual, "monto_NC"),
                             ("5 FULFILLMENT", ff, "monto_NC"),
                             ("6 CANCEL por emitir", nucleo, "monto"),
                             ("7 CANCEL valida seller", pagados, "monto"),
                             ("8 CANCEL vencidas", vencidas, "monto")]:
            print(f"  {nom:22}: {len(d_):>4} · {fmt(d_[col].sum())}")
        return 0
    to = DRAFT_TO if a.draft else TO_PROD
    cc = DRAFT_CC if a.draft else CC_PROD
    print(f"Enviando a {to} cc {cc}...")
    mid = enviar(asunto, html, fn, to, cc)
    print("Enviado. msg_id:", mid)
    return 0 if mid else 1


if __name__ == "__main__":
    sys.exit(main())
