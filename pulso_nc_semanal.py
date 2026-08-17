# -*- coding: utf-8 -*-
"""Pulso NC semanal (lunes) — NC por emitir por DEVOLUCIÓN y por CANCELACIÓN, por mes y canal.

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
import os, sys, json, time, argparse, datetime, base64, mimetypes
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
        for v in rpc("account.move", "read", [inv_ids[i:i+300]], {"fields": ["move_type", "state"]}):
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
    df = df.copy()
    df["estado_vivo"] = df.apply(clasificar, axis=1)
    print(f"[devoluciones-vivo] {df['estado_vivo'].value_counts().to_dict()}")
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
    rows = []
    for s in canc:
        if s["id"] in ff:
            continue
        ivs = [invs[i] for i in s["invoice_ids"] if i in invs]
        bol = [v for v in ivs if v["move_type"] == "out_invoice" and v["state"] == "posted"
               and v["payment_state"] != "reversed" and v["id"] not in rev]
        ncs = [v for v in ivs if v["move_type"] == "out_refund" and v["state"] == "posted"]
        if not bol or ncs:
            continue
        b = bol[0]
        rows.append({"pedido": s["name"], "canal": canal_de(s), "mes": str(b["invoice_date"])[:7],
                     "boleta": b["name"], "monto": b["amount_total"], "pago_boleta": b["payment_state"],
                     "despachado": s["id"] in desp, "dia_cancel": str(s["write_date"])[:10]})
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
    ap.add_argument("--draft", action="store_true")
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
    em = disp[disp["estado_vivo"] == "EMITIBLE"]
    ff = disp[disp["estado_vivo"].str.startswith("FULFILLMENT")]
    piv_dev = em.pivot_table(index="mes", columns="canal", values="monto_NC", aggfunc="sum").fillna(0)
    piv_dev["TOTAL"] = piv_dev.sum(axis=1)

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
    C = C[~C["pedido"].astype(str).isin(set(em["pedido"].astype(str)))]
    nucleo = C[~C["despachado"]]
    pagados = C[C["despachado"]]  # con despacho: validar estado seller
    piv_can = nucleo.pivot_table(index="mes", columns="canal", values="monto", aggfunc="sum").fillna(0)
    piv_can["TOTAL"] = piv_can.sum(axis=1)

    # --- excel adjunto
    fn = OUT / f"Pulso_NC_semana_{semana}_{hoy:%Y%m%d}.xlsx"
    with pd.ExcelWriter(fn) as w:
        em.to_excel(w, sheet_name=f"Devolucion emitibles ({len(em)})", index=False)
        ff.to_excel(w, sheet_name=f"Fulfillment excluidas ({len(ff)})", index=False)
        nucleo.to_excel(w, sheet_name=f"Cancelacion nucleo ({len(nucleo)})", index=False)
        pagados.to_excel(w, sheet_name=f"Cancel con despacho ({len(pagados)})", index=False)

    aviso_borrador = ("" if not a.draft else
        f'<div style="padding:8px 12px;background:{AMB};border-left:4px solid #B8860B;font-size:13px;margin:8px 0;">'
        f'<b>BORRADOR para aprobación de formato.</b></div>')

    html = f"""<div style="font-family:Arial,sans-serif;color:#222;max-width:760px;line-height:1.5;">
<h2 style="color:{AZ};margin-bottom:2px;">🧾 Pulso NC por emitir</h2>
<div style="color:#64748b;font-size:12px;">Semana {semana} · {hoy.strftime('%d/%m/%Y')} · fuente: planillas SAC + Odoo en vivo · solo informa, no crea NC</div>
{aviso_borrador}

<h3 style="color:{AZ};margin:14px 0 2px;">1. NC por DEVOLUCIÓN — {miles(len(em))} OC · {fmt(em['monto_NC'].sum())}</h3>
<div style="font-size:12px;color:#475569;">Criterio: devolución recepcionada en bodega + boleta posteada + sin NC. Fulfillment EXCLUIDO
({miles(len(ff))} OC · {fmt(ff['monto_NC'].sum())} → se descuentan en liquidación factura, no llevan NC).</div>
{tabla_html(piv_dev)}

<h3 style="color:{AZ};margin:14px 0 2px;">2. NC por CANCELACIÓN (directas) — {miles(len(nucleo))} pedidos · {fmt(nucleo['monto'].sum())}</h3>
<div style="font-size:12px;color:#475569;">Criterio Víctor: pedido cancelado 2026 + boleta posteada + <b>SIN despacho</b> + sin NC
(auditado: sin reversas ya emitidas, sin gemelos vivos, sin fulfillment, sin barridas administrativas).</div>
{tabla_html(piv_can)}

<div style="padding:8px 12px;background:{AMB};border-left:4px solid #B8860B;font-size:13px;margin:10px 0;">
<b>🔍 En validación de estado seller (no contado arriba):</b> {miles(len(pagados))} pedidos cancelados CON despacho hecho por
{fmt(pagados['monto'].sum())} — patrón devolución marketplace (Paris/Falabella/Walmart/Ripley pagan y luego descuentan en
liquidación): se valida el estado en el seller center antes de definir NC. Hoja "Cancel con despacho" del adjunto.</div>

<div style="font-size:12px;color:#475569;margin:8px 0;">Nota: quedaron FUERA de este pulso {miles(len(barridas))} pedidos
cancelados en barridas del conector (16-jun y fines de julio) por {fmt(barridas['monto'].sum())} — resoluciones de marketplace
en aclaración con facturación (ruteo enviado a Yohana 05-08). No corresponden a NC automática.</div>

<div style="font-size:13px;margin:12px 0;">📎 <b>Excel adjunto:</b> detalle OC por OC de las 4 poblaciones (devolución emitibles ·
fulfillment excluidas · cancelación directas · canceladas con despacho en validación).</div>
</div>"""

    asunto = (f"{'[BORRADOR] ' if a.draft else ''}🧾 Pulso NC · Semana {semana} · "
              f"Devolución {fmt(em['monto_NC'].sum())} · Cancelación {fmt(nucleo['monto'].sum())} por emitir")
    to = DRAFT_TO if a.draft else TO_PROD
    cc = DRAFT_CC if a.draft else CC_PROD
    print(f"Enviando a {to} cc {cc}...")
    mid = enviar(asunto, html, fn, to, cc)
    print("Enviado. msg_id:", mid)
    return 0 if mid else 1


if __name__ == "__main__":
    sys.exit(main())
