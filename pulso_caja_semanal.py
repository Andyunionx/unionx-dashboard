# -*- coding: utf-8 -*-
"""
PULSO DE CAJA SEMANAL — lunes 08:00 · solo Andrés (calibración).

Bloques:
  1. Caja hoy por banco (vs hace 7 días).
  2. Flujo de la semana por destino/origen (contrapartidas bancarias clasificadas).
  3. Lo que viene (30 días): CxC por vencer + vencidas (cobranza), CxP por vencer,
     cuotas de créditos (parquet), plan COMEX de la planilla, IVA/nómina por calendario.
  4. Semáforo de cobertura a 14 días (solo datos duros; estimados informativos aparte).
  5. Alertas: caja bajo umbral, costo financiero semanal alto, transitorias, pagos sin nominar.

Fuentes: Odoo (SOLO LECTURA, xmlrpc) + data/finanzas/{prestamos_comerciales,deuda}.parquet.
Envío: Gmail API (token agente-comex local o GMAIL_TOKEN_JSON en CI). Uso: --dry-run para previsualizar.
"""
import base64
import datetime
import json
import os
import sys
import xmlrpc.client
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent
DRY = "--dry-run" in sys.argv
UMBRAL_CAJA = 50.0            # MM CLP — alerta si caja total queda bajo esto
UMBRAL_FIN_SEM = 8.0          # MM CLP — intereses+gastos fin. por semana sobre esto = alerta
COMPANY_ID = 1                # Comercial Innovatek

hoy = datetime.date.today()
d7 = hoy - datetime.timedelta(days=7)
d14 = hoy + datetime.timedelta(days=14)
d30 = hoy + datetime.timedelta(days=30)


def mm(v, dec=1):
    s = f"{abs(v)/1e6:,.{dec}f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return ("−$" if v < 0 else "$") + s + " M"


# ============ Odoo (solo lectura) ============
cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
DB = cfg.get("db_name") or cfg.get("db")
pw = (os.environ.get("ANDRES_ODOO_PASSWORD", "") or cfg.get("password") or "")
if not pw and (ROOT / "odoo/.odoo_pass").exists():
    pw = (ROOT / "odoo/.odoo_pass").read_text().strip()
common = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common")
uid = common.authenticate(DB, cfg["username"], pw, {})
models = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object")


def sread(model, domain, fields, **kw):
    out, offset = [], 0
    while True:
        page = models.execute_kw(DB, uid, pw, model, "search_read",
                                 [domain], {"fields": fields, "limit": 1000, "offset": offset,
                                            "order": "id asc", **kw})
        out += page
        if len(page) < 1000:
            return out
        offset += 1000


# ---- cuentas de caja y diarios ----
cash_accs = sread("account.account", [("account_type", "=", "asset_cash")], ["id", "code", "name"])
cash_ids = [a["id"] for a in cash_accs]
journals = sread("account.journal",
                 [("type", "in", ["bank", "cash"]), ("company_id", "=", COMPANY_ID)],
                 ["id", "name"])
j_ids = [j["id"] for j in journals]

# ============ BLOQUE 1 — saldos por banco ============
def saldos(hasta=None):
    # saldo por cuenta = TODOS los diarios (filtrar por diario deja el mayor incompleto)
    dom = [("account_id", "in", cash_ids), ("parent_state", "=", "posted"),
           ("company_id", "=", COMPANY_ID)]
    if hasta:
        dom.append(("date", "<=", str(hasta)))
    grp = models.execute_kw(DB, uid, pw, "account.move.line", "read_group",
                            [dom, ["balance"], ["account_id"]], {})
    return {g["account_id"][1]: g["balance"] for g in grp if g.get("account_id")}

s_hoy = saldos()
s_ant = saldos(d7)
caja_total, caja_ant = sum(s_hoy.values()), sum(s_ant.values())
bancos_top = sorted(s_hoy.items(), key=lambda kv: -abs(kv[1]))[:8]

# ============ BLOQUE 2 — flujo de la semana ============
bank_week = sread("account.move.line",
                  [("journal_id", "in", j_ids), ("account_id", "in", cash_ids),
                   ("parent_state", "=", "posted"), ("date", ">", str(d7))],
                  ["move_id", "date", "debit", "credit"])
move_ids = sorted({l["move_id"][0] for l in bank_week if l.get("move_id")})
lines = []
for i in range(0, len(move_ids), 2000):
    lines += sread("account.move.line",
                   [("move_id", "in", move_ids[i:i + 2000]), ("parent_state", "=", "posted")],
                   ["move_id", "account_id", "partner_id", "name", "balance"])
lw = pd.DataFrame([{
    "account_id": l["account_id"][0] if l.get("account_id") else None,
    "account": l["account_id"][1] if l.get("account_id") else "",
    "partner": l["partner_id"][1] if l.get("partner_id") else "",
    "glosa": l.get("name") or "",
    "balance": l.get("balance") or 0.0,
} for l in lines])
lw["codigo"] = lw["account"].str.extract(r"^(\d+)")
lw = lw[~lw["account_id"].isin(set(cash_ids))]  # contrapartidas


def bucket(c, n, p, g):
    c, n, p, g = str(c or ""), str(n or "").lower(), str(p or "").lower(), str(g or "").lower()
    if c == "100101":
        return "Transitoria sin aplicar"
    if c == "110402" or "factoring" in n:
        return "Factoring (financiamiento)"
    if c == "110401" or "clientes" in n:
        return "Cobros de clientes (facturas)"
    if c == "110312" or "aduana" in n or "pedro serrano" in p:
        return "Aduana e internación COMEX"
    if c.startswith("210202") or c.startswith("4342") or "remuner" in n or "nomina" in g or "nómina" in g:
        return "Remuneraciones"
    if "previred" in (n + g + p) or c.startswith("210203") or c.startswith("210204"):
        return "Imposiciones"
    if c == "210504" or "impuesto" in n or "tesoreria" in p or "tesorería" in p:
        return "SII / IVA"
    if c.startswith("210215") or c.startswith("1110") or "topwill" in p:
        return "Proveedores importación"
    if "interes" in n or "interés" in n or "gasto bancario" in n or c.startswith("47") or c == "120101":
        return "Intereses y gastos financieros"
    if c.startswith("22") or "prestamo" in n or "préstamo" in n or "credito" in n or "crédito" in n:
        return "Deuda: amortización / giro"
    if c.startswith("2101") or c.startswith("2102"):
        return "Proveedores nacionales"
    if c.startswith("1105") or c.startswith("1101") or c.startswith("1001"):
        return "Cuentas puente / traspasos (neto)"
    return "Otros"


if len(lw):
    lw["bucket"] = [bucket(c, a, p, g) for c, a, p, g in
                    zip(lw["codigo"], lw["account"], lw["partner"], lw["glosa"])]
    flujo = lw.groupby("bucket")["balance"].sum().sort_values(ascending=False)
else:
    flujo = pd.Series(dtype=float)
salidas_sem = float(flujo[flujo > 0].sum()) if len(flujo) else 0.0
entradas_sem = -float(flujo[flujo < 0].sum()) if len(flujo) else 0.0
fin_sem = float(flujo.get("Intereses y gastos financieros", 0.0)) / 1e6
trans_sem = float(lw[lw["codigo"] == "100101"]["balance"].sum()) / 1e6 if len(lw) else 0.0
sin_partner = float(lw[(lw["bucket"] == "Proveedores nacionales") & (lw["partner"] == "")
                       & (lw["balance"] > 0)]["balance"].sum()) / 1e6 if len(lw) else 0.0

# ============ BLOQUE 3 — lo que viene ============
def facturas(tipo):
    return sread("account.move",
                 [("move_type", "in", tipo), ("state", "=", "posted"),
                  ("payment_state", "in", ["not_paid", "partial"]),
                  ("company_id", "=", COMPANY_ID)],
                 ["partner_id", "invoice_date_due", "amount_residual_signed", "name"])

cxc = pd.DataFrame([{
    "partner": f["partner_id"][1] if f.get("partner_id") else "—",
    "due": f.get("invoice_date_due") or "",
    "monto": f.get("amount_residual_signed") or 0.0,
} for f in facturas(["out_invoice", "out_refund"])])
cxp = pd.DataFrame([{
    "partner": f["partner_id"][1] if f.get("partner_id") else "—",
    "due": f.get("invoice_date_due") or "",
    "monto": -(f.get("amount_residual_signed") or 0.0),
} for f in facturas(["in_invoice", "in_refund"])])

def tramos(df):
    if df.empty:
        return dict(vencido=0, v7=0, v14=0, v30=0), df
    df = df.copy()
    df["due_d"] = pd.to_datetime(df["due"], errors="coerce").dt.date
    venc = df[df["due_d"] < hoy]
    return {
        "vencido": venc["monto"].sum(),
        "v7": df[(df["due_d"] >= hoy) & (df["due_d"] <= hoy + datetime.timedelta(days=7))]["monto"].sum(),
        "v14": df[(df["due_d"] >= hoy) & (df["due_d"] <= d14)]["monto"].sum(),
        "v30": df[(df["due_d"] >= hoy) & (df["due_d"] <= d30)]["monto"].sum(),
    }, venc

t_cxc, cxc_venc = tramos(cxc)
t_cxp, cxp_venc = tramos(cxp)
top_deudores = (cxc_venc.groupby("partner")["monto"].sum().sort_values(ascending=False).head(10)
                if len(cxc_venc) else pd.Series(dtype=float))

# cuotas de créditos comerciales (parquet)
try:
    pres = pd.read_parquet(ROOT / "data/finanzas/prestamos_comerciales.parquet").dropna(
        subset=["cuotas_pend", "cuota_mensual"])
    cuotas_30 = float(pres.loc[pres["cuotas_pend"] > 0, "cuota_mensual"].sum())
except Exception:
    cuotas_30 = 0.0

# plan COMEX de la planilla (amortización proyectada por mes, bloque COMEX)
try:
    deu = pd.read_parquet(ROOT / "data/finanzas/deuda.parquet")
    cx = deu[(deu["bloque"] == "COMEX") & (deu["seccion"] == "Balances deuda LP")
             & (deu["linea"] == "(-) Pago / Amortizaciones")]
    comex_plan = {(int(r["year"]), int(r["month"])): abs(float(r["valor"])) * 1000  # M$→CLP
                  for _, r in cx.iterrows()}
    m0 = (hoy.year, hoy.month)
    m1 = (hoy.year + (hoy.month // 12), hoy.month % 12 + 1)
    comex_mes, comex_next = comex_plan.get(m0, 0.0), comex_plan.get(m1, 0.0)
    prox4 = []
    y, mo = m0
    for _ in range(4):
        prox4.append((f"{mo:02d}-{y}", comex_plan.get((y, mo), 0.0)))
        y, mo = (y + mo // 12, mo % 12 + 1)
except Exception:
    comex_mes = comex_next = 0.0
    prox4 = []

# calendario fijo (estimados por patrón)
IVA_EST, NOMINA_EST, IMPO_EST = 28e6 * 1e0, 72e6, 28e6
IVA_EST = 28e6
eventos_14 = []
for delta in range(0, 15):
    f = hoy + datetime.timedelta(days=delta)
    if f.day == 20:
        eventos_14.append(("IVA F29 (est.)", IVA_EST, f))
    if f.day == 13:
        eventos_14.append(("Imposiciones (est.)", IMPO_EST, f))
    if (f + datetime.timedelta(days=1)).day == 1:
        eventos_14.append(("Nómina fin de mes (est.)", NOMINA_EST, f))

# semáforo cobertura 14d (solo duros; estimados se muestran aparte)
compromisos_14 = (t_cxp["v14"] + t_cxp["vencido"] * 0.5 + cuotas_30 * 14 / 30
                  + comex_mes * 14 / 30 + sum(e[1] for e in eventos_14))
recursos_14 = caja_total + t_cxc["v14"] * 0.85
cobertura = recursos_14 / compromisos_14 if compromisos_14 > 0 else 9.9
sem_color, sem_txt = (("#0E7A54", "VERDE") if cobertura >= 1.2 else
                      ("#B8860B", "AMARILLO") if cobertura >= 1.0 else ("#9B3A2F", "ROJO"))

# ============ alertas ============
alertas = []
if caja_total / 1e6 < UMBRAL_CAJA:
    alertas.append(f"🔴 Caja total {mm(caja_total)} bajo el umbral de ${UMBRAL_CAJA:.0f} M.")
if fin_sem > UMBRAL_FIN_SEM:
    alertas.append(f"🔴 Costo financiero de la semana {mm(fin_sem*1e6)} (umbral ${UMBRAL_FIN_SEM:.0f} M/sem).")
if trans_sem > 5:
    alertas.append(f"🟡 {mm(trans_sem*1e6)} salieron a la transitoria 100101 sin aplicar esta semana — pedir aplicación a Víctor.")
if sin_partner > 50:
    alertas.append(f"🟡 {mm(sin_partner*1e6)} pagados a proveedores SIN contraparte nominada esta semana.")
if cobertura < 1.0:
    alertas.append(f"🔴 Cobertura 14 días {cobertura:.2f}× — los compromisos superan caja + cobranza dura.")

# ============ resumen ejecutivo (en una mirada) ============
neto_sem = entradas_sem - salidas_sem
_fl_real = flujo[~flujo.index.str.contains("puente|Transitoria", case=False)] if len(flujo) else flujo
top_salida = _fl_real.idxmax() if len(_fl_real) and _fl_real.max() > 0 else "—"
top3_deud = top_deudores.head(3)
resumen = []
resumen.append(
    f"La semana {'quemó' if neto_sem < 0 else 'sumó'} <b>{mm(abs(neto_sem))}</b> de caja "
    f"(entró {mm(entradas_sem)}, salió {mm(salidas_sem)}; mayor salida: {top_salida.lower()}).")
resumen.append(
    f"Cobertura a 14 días <b style='color:{sem_color}'>{sem_txt} ({cobertura:.2f}×)</b>: "
    f"recursos duros {mm(recursos_14)} vs compromisos {mm(compromisos_14)}.")
if t_cxc["vencido"] > 50e6:
    resumen.append(
        f"La palanca inmediata es la <b>cobranza vencida: {mm(t_cxc['vencido'])}</b>"
        + (f" — los 3 mayores deudores ({', '.join(top3_deud.index[:3])}) concentran "
           f"{mm(top3_deud.sum())}." if len(top3_deud) else "."))
prox_ev = sorted(eventos_14, key=lambda e: e[2])
if prox_ev:
    resumen.append("Se viene: " + " · ".join(f"{n} {mm(v)} el {f.strftime('%d-%m')}"
                                             for n, v, f in prox_ev[:3])
                   + (f" · plan COMEX del mes {mm(comex_mes)}." if comex_mes else "."))
resumen_html = "".join(f"<li style='margin:3px 0'>{r}</li>" for r in resumen)

# ============ HTML ============
def fila(l, v, extra=""):
    color = "#9B3A2F" if v < 0 else "#1E293B"
    return (f"<tr><td style='padding:4px 10px;border-bottom:1px solid #E8EDF2'>{l}</td>"
            f"<td style='padding:4px 10px;border-bottom:1px solid #E8EDF2;text-align:right;"
            f"font-family:Consolas,monospace;color:{color}'>{mm(v)}</td>"
            f"<td style='padding:4px 10px;border-bottom:1px solid #E8EDF2;color:#5B6B78;font-size:12px'>{extra}</td></tr>")

TH = ("<th style='text-align:left;padding:5px 10px;border-bottom:2px solid #1F3864;font-size:11px;"
      "text-transform:uppercase;color:#5B6B78'>")
THr = TH.replace("text-align:left", "text-align:right")

# dos columnas claras: Entrada / Salida (montos siempre positivos)
flujo_rows = ""
for b, v in flujo.sort_values(ascending=False).items():
    if abs(v) < 1e6:
        continue
    ent = mm(-v, 1) if v < 0 else ""
    sal = mm(v, 1) if v > 0 else ""
    flujo_rows += (f"<tr><td style='padding:4px 10px;border-bottom:1px solid #E8EDF2'>{b}</td>"
                   f"<td style='padding:4px 10px;border-bottom:1px solid #E8EDF2;text-align:right;"
                   f"font-family:Consolas,monospace;color:#0E7A54'>{ent}</td>"
                   f"<td style='padding:4px 10px;border-bottom:1px solid #E8EDF2;text-align:right;"
                   f"font-family:Consolas,monospace;color:#9B3A2F'>{sal}</td></tr>")

deud_rows = "".join(fila(p, v) for p, v in top_deudores.items())
prox_rows = "".join(
    f"<tr><td style='padding:3px 10px'>{lbl}</td>"
    f"<td style='padding:3px 10px;text-align:right;font-family:Consolas,monospace'>{mm(v)}</td></tr>"
    for lbl, v in prox4)
ev_rows = "".join(fila(n, -v, f.strftime("%d-%m")) for n, v, f in eventos_14)
alert_html = "".join(f"<div style='background:#FBF3F1;border-left:4px solid #9B3A2F;padding:8px 12px;"
                     f"margin:6px 0;border-radius:0 6px 6px 0'>{a}</div>" for a in alertas) or \
             "<div style='color:#0E7A54'>✅ Sin alertas esta semana.</div>"

html = f"""<div style="font-family:'Segoe UI',system-ui,sans-serif;max-width:760px;margin:auto;color:#1E293B">
<div style="border-bottom:3px solid #1F3864;padding-bottom:8px">
  <div style="font-size:11px;letter-spacing:.12em;color:#2E75B6;font-weight:600">UNIONX · PULSO DE CAJA SEMANAL · CONFIDENCIAL</div>
  <h2 style="margin:4px 0;color:#1F3864">💧 Caja: {mm(caja_total)} <span style="font-size:14px;color:{'#9B3A2F' if caja_total < caja_ant else '#0E7A54'}">({mm(caja_total-caja_ant)} vs lunes pasado)</span></h2>
  <div style="color:#5B6B78;font-size:12.5px">Semana {d7.strftime('%d-%m')} → {hoy.strftime('%d-%m-%Y')} · Comercial Innovatek · datos bancarios Odoo</div>
</div>

<div style="background:#F2F6FA;border-left:4px solid #2E75B6;border-radius:0 8px 8px 0;padding:10px 16px;margin:14px 0">
  <div style="font-size:11px;letter-spacing:.08em;font-weight:700;color:#1F3864;text-transform:uppercase">En una mirada</div>
  <ul style="margin:6px 0 2px;padding-left:18px;font-size:13.5px">{resumen_html}</ul>
</div>

<h3 style="color:#1F3864;margin:18px 0 6px">Semáforo de cobertura a 14 días:
  <span style="color:{sem_color}">{sem_txt} ({cobertura:.2f}×)</span></h3>
<div style="font-size:13px;color:#5B6B78">Caja {mm(caja_total)} + CxC por vencer 14d {mm(t_cxc['v14'])}×85% &nbsp;vs&nbsp;
CxP 14d {mm(t_cxp['v14'])} + 50% CxP vencida {mm(t_cxp['vencido'])} + cuotas {mm(cuotas_30*14/30)} + plan COMEX {mm(comex_mes*14/30)} + calendario (IVA/nómina).</div>

{alert_html}

<h3 style="color:#1F3864;margin:20px 0 4px">1 · Caja por banco</h3>
<table style="border-collapse:collapse;width:100%">{"".join(fila(b.split(' ',1)[-1][:38], v) for b, v in bancos_top)}
{fila('<b>TOTAL</b>', caja_total)}</table>

<h3 style="color:#1F3864;margin:20px 0 4px">2 · La semana: entró {mm(entradas_sem)} · salió {mm(salidas_sem)}</h3>
<table style="border-collapse:collapse;width:100%"><tr>{TH}Destino / origen</th>{THr}Entrada</th>{THr}Salida</th></tr>{flujo_rows}</table>

<h3 style="color:#1F3864;margin:20px 0 4px">3 · Cobranza y compromisos (30 días)</h3>
<table style="border-collapse:collapse;width:100%">
{fila('CxC por vencer 0-7d', t_cxc['v7'])}{fila('CxC por vencer 8-30d', t_cxc['v30']-t_cxc['v7'])}
{fila('<b>CxC VENCIDA (cobrar ya)</b>', t_cxc['vencido'])}
{fila('CxP por pagar 0-30d', -t_cxp['v30'])}{fila('CxP vencida (colgada)', -t_cxp['vencido'])}
{fila('Cuotas créditos (30d)', -cuotas_30)}{fila('Plan COMEX mes (planilla)', -comex_mes)}</table>

<b style="color:#1F3864;font-size:13px">Top deudores vencidos:</b>
<table style="border-collapse:collapse;width:100%">{deud_rows}</table>

<b style="color:#1F3864;font-size:13px">Calendario próximos 14 días:</b>
<table style="border-collapse:collapse;width:100%">{ev_rows or fila('Sin eventos de calendario', 0)}</table>

<b style="color:#1F3864;font-size:13px">Plan de amortización COMEX (planilla, próximos 4 meses):</b>
<table style="border-collapse:collapse;width:50%">{prox_rows}</table>

<div style="margin-top:22px;border-top:1px solid #DCE3E8;padding-top:8px;color:#5B6B78;font-size:11.5px">
Fuentes: Odoo read-only (saldos y movimientos bancarios, facturas por cobrar/pagar) ·
Planificación Financiera (cuotas y plan COMEX, refresco lunes 11:00) ·
IVA/nómina/imposiciones = estimados por patrón. Umbral caja ${UMBRAL_CAJA:.0f} M.
Libros contables abiertos desde abril: saldos pueden moverse. Generado {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')}.</div>
</div>"""

# ============ Excel detalle ============
xlsx = ROOT / "data" / "outputs" / "pulso_caja_detalle.xlsx"
with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
    if len(lw):
        lw.sort_values("balance", ascending=False).to_excel(xw, sheet_name="Mov semana", index=False)
    if len(cxc):
        cxc.sort_values("due").to_excel(xw, sheet_name="CxC pendientes", index=False)
    if len(cxp):
        cxp.sort_values("due").to_excel(xw, sheet_name="CxP pendientes", index=False)

# ============ envío ============
if DRY:
    prev = ROOT / "data" / "outputs" / "pulso_caja_preview.html"
    prev.write_text(html, encoding="utf-8")
    print(f"[DRY] Preview -> {prev}")
    print(f"Caja {mm(caja_total)} ({mm(caja_total-caja_ant)}) · cobertura14d {cobertura:.2f}x {sem_txt} · "
          f"alertas: {len(alertas)}")
else:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = os.environ.get("GMAIL_TOKEN_JSON")
    creds = (Credentials.from_authorized_user_info(json.loads(tok)) if tok
             else Credentials.from_authorized_user_file(str(ROOT / "agente-comex/config/token.json")))
    if not creds.valid:
        creds.refresh(Request())
    svc = build("gmail", "v1", credentials=creds)
    msg = EmailMessage()
    msg["To"] = os.environ.get("PULSO_CAJA_TO", "andres@unionx.cl")
    msg["From"] = "andres@unionx.cl"
    icon = "🔴" if any(a.startswith("🔴") for a in alertas) else ("🟡" if alertas else "🟢")
    msg["Subject"] = (f"{icon} Pulso Caja · {mm(caja_total)} · cobertura 14d {cobertura:.1f}× · "
                      f"{hoy.strftime('%d-%b')}")
    msg.set_content("Pulso de Caja semanal (ver versión HTML).")
    msg.add_alternative(html, subtype="html")
    with open(xlsx, "rb") as f:
        msg.add_attachment(f.read(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename="pulso_caja_detalle.xlsx")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"Enviado: caja {mm(caja_total)} · cobertura {cobertura:.2f}x {sem_txt} · alertas {len(alertas)}")
