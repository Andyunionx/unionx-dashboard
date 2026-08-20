# -*- coding: utf-8 -*-
"""Pulso Alarmas Odoo — salud de crons + cola DTE, diario a primera hora.

Origen: incidente 20-ago-2026 (cron 26 'Send document to SII' apagado desde el
11-ago por trabajos de performance → 2.822 boletas sin enviar, lo detectó Yohana
9 días después). Este pulso lo habría acusado al día siguiente.

Chequeos:
  1. CRÍTICO — crons de la watchlist apagados.
  2. CRÍTICO — cron activo pero "muerto": lastcall más viejo que 3× su intervalo (mín 2 h).
  3. CRÍTICO — cola DTE: documentos posteados 'not_sent' > umbral.
  4. ADVERTENCIA — DTEs rechazados/objetados de las últimas 48 h sobre umbral.
  5. ADVERTENCIA — failure_count > 0 en cualquier cron activo.
  6. Tabla informativa: watchlist con estado, última y próxima ejecución.

Envío: Gmail API (token agente-comex local o GMAIL_TOKEN_JSON en CI).
Destinatario: andres@unionx.cl (edición inicial; ampliar destinatarios con OK).
"""
import sys, json, os, time, base64, datetime
from pathlib import Path
import xmlrpc.client

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
HOY = datetime.datetime.utcnow()

# ---- Odoo ----
cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
pw = os.environ.get("ANDRES_ODOO_PASSWORD", "")
if not pw and (ROOT / "odoo/.odoo_pass").exists():
    pw = (ROOT / "odoo/.odoo_pass").read_text().strip()
uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(cfg["db_name"], cfg["username"], pw, {})

def rpc(model, method, args, kw=None):
    for i in range(4):
        try:
            return xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object").execute_kw(
                cfg["db_name"], uid, pw, model, method, args, kw or {})
        except Exception:
            if i == 3:
                raise
            time.sleep(10)

# Crons que DEBEN estar activos (id: descripción corta)
WATCHLIST = {
    26: "Envío DTE al SII (boletas/facturas)",
    27: "SII: consulta estados / jobs generales",
    156: "Monitor DTEs rechazados (UnionX)",
    157: "Corrector 801 Duty/Dimarsa (UnionX)",
    132: "Costo packs desde LdM (UnionX)",
    159: "Peso packs desde LdM (UnionX)",
    149: "Shopify Directo: reconciliar pedidos",
    152: "Shopify Directo: sentinel sin-pedidos",
}
UMBRAL_NOT_SENT = 150
UMBRAL_RECHAZADOS = 10
UMBRAL_OBJETADOS = 40

DUR = {"minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800, "months": 2592000}

criticas, advertencias, tabla = [], [], []

crons = rpc("ir.cron", "search_read", [[]],
            {"fields": ["id", "name", "active", "lastcall", "nextcall",
                        "interval_number", "interval_type", "failure_count"],
             "context": {"active_test": False}})
by_id = {c["id"]: c for c in crons}

def edad(ts):
    if not ts:
        return None
    return (HOY - datetime.datetime.fromisoformat(ts)).total_seconds()

def fmt_edad(seg):
    if seg is None:
        return "nunca"
    if seg < 3600:
        return f"hace {seg/60:.0f} min"
    if seg < 86400:
        return f"hace {seg/3600:.1f} h"
    return f"hace {seg/86400:.1f} días"

# 1-2) watchlist apagada o muerta
for cid, desc in WATCHLIST.items():
    c = by_id.get(cid)
    if c is None:
        criticas.append(f"Cron {cid} ({desc}) NO EXISTE — ¿fue eliminado?")
        continue
    e = edad(c["lastcall"])
    periodo = (c["interval_number"] or 1) * DUR.get(c["interval_type"], 86400)
    estado = "ACTIVO"
    if not c["active"]:
        estado = "APAGADO"
        criticas.append(f"Cron {cid} «{c['name']}» está APAGADO ({desc}). Última corrida {fmt_edad(e)}.")
    elif e is not None and e > max(3 * periodo, 7200):
        estado = "SIN CORRER"
        criticas.append(f"Cron {cid} «{c['name']}» activo pero SIN CORRER {fmt_edad(e)} (intervalo {c['interval_number']} {c['interval_type']}).")
    tabla.append((cid, c["name"][:48], desc, estado, fmt_edad(e)))

# crons activos fuera de watchlist muertos hace >24h con intervalo <= diario
for c in crons:
    if not c["active"] or c["id"] in WATCHLIST:
        continue
    periodo = (c["interval_number"] or 1) * DUR.get(c["interval_type"], 86400)
    e = edad(c["lastcall"])
    if periodo <= 86400 and e is not None and e > max(3 * periodo, 86400):
        advertencias.append(f"Cron {c['id']} «{c['name'][:50]}» activo pero sin correr {fmt_edad(e)}.")

# 5) failure_count
for c in crons:
    if c["active"] and (c.get("failure_count") or 0) > 0:
        advertencias.append(f"Cron {c['id']} «{c['name'][:50]}» con failure_count={c['failure_count']}.")

# 3) cola DTE not_sent
n_pend = rpc("account.move", "search_count",
             [[("l10n_cl_dte_status", "=", "not_sent"), ("state", "=", "posted")]])
if n_pend > UMBRAL_NOT_SENT:
    criticas.append(f"COLA SII: {n_pend:,} documentos posteados sin enviar al SII (umbral {UMBRAL_NOT_SENT}).")

# 4) rechazados / objetados últimas 48h
d2 = (HOY - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
n_rej = rpc("account.move", "search_count",
            [[("l10n_cl_dte_status", "=", "rejected"), ("state", "=", "posted"), ("date", ">=", d2)]])
n_obj = rpc("account.move", "search_count",
            [[("l10n_cl_dte_status", "=", "objected"), ("state", "=", "posted"), ("date", ">=", d2)]])
if n_rej > UMBRAL_RECHAZADOS:
    advertencias.append(f"DTEs RECHAZADOS últimas 48 h: {n_rej} (umbral {UMBRAL_RECHAZADOS}).")
if n_obj > UMBRAL_OBJETADOS:
    advertencias.append(f"DTEs aceptados con reparos últimas 48 h: {n_obj} (umbral {UMBRAL_OBJETADOS}).")

# ---- armar correo ----
estado_gral = "🔴" if criticas else ("🟡" if advertencias else "✅")
fecha = (HOY - datetime.timedelta(hours=4)).strftime("%d-%m-%Y %H:%M")  # CLT
filas = "".join(
    f"<tr><td style='padding:4px 8px'>{cid}</td><td style='padding:4px 8px'>{nom}</td>"
    f"<td style='padding:4px 8px'>{desc}</td>"
    f"<td style='padding:4px 8px;font-weight:600;color:{'#16a34a' if est=='ACTIVO' else '#dc2626'}'>{est}</td>"
    f"<td style='padding:4px 8px'>{ult}</td></tr>"
    for cid, nom, desc, est, ult in tabla)

def bloque(titulo, items, color):
    if not items:
        return ""
    lis = "".join(f"<li style='margin:4px 0'>{x}</li>" for x in items)
    return (f"<div style='background:{color};border-radius:8px;padding:10px 14px;margin:0 0 14px'>"
            f"<b>{titulo}</b><ul style='margin:6px 0 0;padding-left:18px'>{lis}</ul></div>")

html = f"""<div style='font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1e293b;max-width:860px'>
<h2 style='margin:0 0 4px'>{estado_gral} Pulso Alarmas Odoo · {fecha} CLT</h2>
<p style='margin:0 0 14px;color:#64748b'>Salud de crons y cola DTE · {len(crons)} crons ({sum(1 for c in crons if c['active'])} activos) · cola SII: {n_pend:,} sin enviar · rechazados 48h: {n_rej} · reparos 48h: {n_obj}</p>
{bloque('🔴 CRÍTICAS — requieren acción hoy', criticas, '#fee2e2')}
{bloque('🟡 Advertencias', advertencias, '#fef9c3')}
{"<p style='margin:0 0 14px'>✅ Sin alarmas: todos los crons vigilados corriendo y cola SII normal.</p>" if not criticas and not advertencias else ""}
<table cellspacing='0' style='border-collapse:collapse;font-size:13px'>
<tr style='background:#f1f5f9;font-weight:600'><td style='padding:4px 8px'>ID</td><td style='padding:4px 8px'>Cron</td><td style='padding:4px 8px'>Función</td><td style='padding:4px 8px'>Estado</td><td style='padding:4px 8px'>Última corrida</td></tr>
{filas}</table>
<p style='margin:14px 0 0;color:#94a3b8;font-size:12px'>Generado automáticamente (pulso_alarmas_odoo.py). Origen: incidente boletas sin enviar 11→20 ago 2026.</p>
</div>"""

print(f"[{estado_gral}] críticas: {len(criticas)} | advertencias: {len(advertencias)} | cola SII: {n_pend}")
for x in criticas: print("  CRIT:", x)
for x in advertencias: print("  ADV :", x)

if "--no-enviar" in sys.argv:
    print("(--no-enviar: no se manda correo)")
    sys.exit(0)

# ---- Gmail ----
from email.message import EmailMessage
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

tok_env = os.environ.get("GMAIL_TOKEN_JSON")
if tok_env:
    creds = Credentials.from_authorized_user_info(json.loads(tok_env))
else:
    creds = Credentials.from_authorized_user_file(str(ROOT / "agente-comex/config/token.json"))
if not creds.valid:
    creds.refresh(Request())
svc = build("gmail", "v1", credentials=creds)
msg = EmailMessage()
msg["To"] = "andres@unionx.cl"
msg["From"] = "andres@unionx.cl"
msg["Subject"] = f"{estado_gral} Pulso Alarmas Odoo · {(HOY - datetime.timedelta(hours=4)).strftime('%d-%b')} · {len(criticas)} críticas"
msg.set_content("Pulso Alarmas Odoo (ver versión HTML).")
msg.add_alternative(html, subtype="html")
raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
r = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
print(f"Enviado: {r['id']}")
