# -*- coding: utf-8 -*-
"""
PULSO DIARIO DE INDICADORES FINANCIEROS — L-V 08:00 · solo Andrés.

Indicadores de mercado (mindicador.cl): dólar, euro, UF, UTM, TPM, IPC, cobre.
Incluye proyección del USD a 10 días hábiles como CONO ESTADÍSTICO (volatilidad
realizada de ~90 observaciones): P10/P50/P90. No es predicción puntual.

Sin cruces con balance ni obligaciones (pedido de Andrés: puntualmente indicadores).
Envío: Gmail API (token local o GMAIL_TOKEN_JSON en CI). Uso: --dry-run para preview.
"""
import base64
import datetime
import json
import math
import os
import sys
import urllib.request
from email.message import EmailMessage
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent
DRY = "--dry-run" in sys.argv
hoy = datetime.date.today()


def es(v, dec=2):
    s = f"{abs(v):,.{dec}f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return ("−" if v < 0 else "") + s


def api(path):
    """GET mindicador con User-Agent de navegador (Cloudflare bloquea urllib pelado
    desde IPs de datacenter, ej. GitHub Actions) + 3 reintentos con backoff."""
    import time
    req = urllib.request.Request(
        f"https://mindicador.cl/api/{path}",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
                 "Accept": "application/json"})
    ultimo = None
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            ultimo = e
            time.sleep(5 * (intento + 1))
    raise ultimo


def serie_anual(ind):
    """Serie diaria del indicador (este año + anterior), ascendente por fecha."""
    filas = []
    for y in (hoy.year - 1, hoy.year):
        try:
            filas += api(f"{ind}/{y}").get("serie", [])
        except Exception:
            pass
    vistos = {}
    for s in filas:
        vistos[s["fecha"][:10]] = float(s["valor"])
    return sorted(vistos.items())  # [(fecha, valor)] ascendente


def var_pct(serie, dias_atras):
    """Variación % del último valor vs el valor 'dias_atras' observaciones antes."""
    if len(serie) <= dias_atras:
        return None
    a, b = serie[-1 - dias_atras][1], serie[-1][1]
    return (b / a - 1) * 100 if a else None


# ============ series ============
usd = serie_anual("dolar")
eur = serie_anual("euro")
cobre = serie_anual("libra_cobre")
uf = serie_anual("uf")
utm = serie_anual("utm")
try:
    tpm_v = float(api("tpm")["serie"][0]["valor"])
except Exception:
    tpm_v = None
try:
    ipc = api("ipc")["serie"][:2]  # variación mensual %
    ipc_v, ipc_f = float(ipc[0]["valor"]), ipc[0]["fecha"][:7]
except Exception:
    ipc_v, ipc_f = None, ""

if not usd:
    raise SystemExit("mindicador.cl no entregó la serie del dólar (¿bloqueo/caída de la API?). "
                     "Sin datos no se envía pulso — revisar conectividad de la fuente.")
spot = usd[-1][1]
usd_d1, usd_d7, usd_d30 = var_pct(usd, 1), var_pct(usd, 5), var_pct(usd, 21)

# ============ cono USD 10 días hábiles ============
vals = [v for _, v in usd[-91:]]
rets = [math.log(vals[i + 1] / vals[i]) for i in range(len(vals) - 1)]
mu = sum(rets) / len(rets)
sd = (sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
H = 10
p50 = spot * math.exp(mu * H)
z90 = 1.2816
p10 = p50 * math.exp(-z90 * sd * math.sqrt(H))
p90 = p50 * math.exp(z90 * sd * math.sqrt(H))
fecha_h = hoy
habiles = 0
while habiles < H:
    fecha_h += datetime.timedelta(days=1)
    if fecha_h.weekday() < 5:
        habiles += 1
vol_anual = sd * math.sqrt(252) * 100

# ============ alertas ============
alertas = []
if usd_d1 is not None and abs(usd_d1) >= 1.0:
    alertas.append(f"🔴 El dólar se movió {es(usd_d1, 1)}% en un día (cierre ${es(spot)}).")
if usd_d7 is not None and abs(usd_d7) >= 2.5:
    alertas.append(f"🟡 Semana movida: USD {es(usd_d7, 1)}% en 5 días hábiles.")
alert_html = "".join(
    f"<div style='background:#FBF3F1;border-left:4px solid #9B3A2F;padding:8px 12px;"
    f"margin:6px 0;border-radius:0 6px 6px 0'>{a}</div>" for a in alertas)

# ============ HTML ============
def var_cell(v):
    if v is None:
        return "<td style='padding:5px 10px;text-align:right'>—</td>"
    c = "#9B3A2F" if v > 0.001 else ("#0E7A54" if v < -0.001 else "#5B6B78")
    return (f"<td style='padding:5px 10px;text-align:right;font-family:Consolas,monospace;"
            f"color:{c}'>{es(v, 2)}%</td>")


def fila_ind(nombre, valor, unidad, d1=None, d7=None, d30=None, dec=2):
    return (f"<tr><td style='padding:5px 10px;border-bottom:1px solid #E8EDF2'>{nombre}</td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #E8EDF2;text-align:right;"
            f"font-family:Consolas,monospace;font-weight:600'>{es(valor, dec)} {unidad}</td>"
            + "".join(x.replace("<td ", "<td style_border ").replace(
                "style='", "style='border-bottom:1px solid #E8EDF2;").replace("style_border ", "")
                for x in (var_cell(d1), var_cell(d7), var_cell(d30))) + "</tr>")


TH = ("<th style='text-align:left;padding:5px 10px;border-bottom:2px solid #1F3864;"
      "font-size:11px;text-transform:uppercase;color:#5B6B78'>")
THr = TH.replace("text-align:left", "text-align:right")

tendencia = ("al alza" if p50 > spot * 1.002 else ("a la baja" if p50 < spot * 0.998 else "lateral"))
resumen = [
    f"Dólar <b>${es(spot)}</b> ({es(usd_d1 or 0, 2)}% día · {es(usd_d7 or 0, 2)}% semana · "
    f"{es(usd_d30 or 0, 2)}% mes).",
    f"Cono a 10 días hábiles (al {fecha_h.strftime('%d-%m')}): <b>${es(p10)} – ${es(p90)}</b>, "
    f"centro ${es(p50)} — tendencia estadística {tendencia}, volatilidad anualizada {es(vol_anual, 1)}%.",
    f"UF ${es(uf[-1][1])} · UTM ${es(utm[-1][1], 0)}"
    + (f" · TPM {es(tpm_v, 2)}%" if tpm_v is not None else "")
    + (f" · IPC {ipc_f}: {es(ipc_v, 1)}%" if ipc_v is not None else "") + ".",
]
resumen_html = "".join(f"<li style='margin:3px 0'>{r}</li>" for r in resumen)

html = f"""<div style="font-family:'Segoe UI',system-ui,sans-serif;max-width:720px;margin:auto;color:#1E293B">
<div style="border-bottom:3px solid #1F3864;padding-bottom:8px">
  <div style="font-size:11px;letter-spacing:.12em;color:#2E75B6;font-weight:600">UNIONX · PULSO DE INDICADORES FINANCIEROS</div>
  <h2 style="margin:4px 0;color:#1F3864">💱 Dólar ${es(spot)} <span style="font-size:14px;color:{'#9B3A2F' if (usd_d1 or 0) > 0 else '#0E7A54'}">({es(usd_d1 or 0, 2)}% hoy)</span></h2>
  <div style="color:#5B6B78;font-size:12.5px">{['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'][hoy.weekday()]} {hoy.strftime('%d-%m-%Y')} · fuente mindicador.cl (Banco Central)</div>
</div>

<div style="background:#F2F6FA;border-left:4px solid #2E75B6;border-radius:0 8px 8px 0;padding:10px 16px;margin:14px 0">
  <div style="font-size:11px;letter-spacing:.08em;font-weight:700;color:#1F3864;text-transform:uppercase">En una mirada</div>
  <ul style="margin:6px 0 2px;padding-left:18px;font-size:13.5px">{resumen_html}</ul>
</div>
{alert_html}

<h3 style="color:#1F3864;margin:18px 0 4px">Indicadores</h3>
<table style="border-collapse:collapse;width:100%;font-size:13.5px">
<tr>{TH}Indicador</th>{THr}Valor</th>{THr}Δ 1d</th>{THr}Δ 5d</th>{THr}Δ 21d</th></tr>
{fila_ind('Dólar observado', spot, 'CLP', usd_d1, usd_d7, usd_d30)}
{fila_ind('Euro', eur[-1][1], 'CLP', var_pct(eur, 1), var_pct(eur, 5), var_pct(eur, 21))}
{fila_ind('Cobre (libra)', cobre[-1][1], 'USD', var_pct(cobre, 1), var_pct(cobre, 5), var_pct(cobre, 21))}
{fila_ind('UF', uf[-1][1], 'CLP', var_pct(uf, 1), var_pct(uf, 5), var_pct(uf, 21))}
{fila_ind('UTM', utm[-1][1], 'CLP', None, None, var_pct(utm, 21), 0)}
</table>
<div style="font-size:12.5px;color:#5B6B78;margin-top:4px">
{('TPM ' + es(tpm_v, 2) + '% anual') if tpm_v is not None else ''}{(' · IPC ' + ipc_f + ': ' + es(ipc_v, 1) + '% mensual') if ipc_v is not None else ''}</div>

<h3 style="color:#1F3864;margin:20px 0 4px">Proyección USD a 10 días hábiles (al {fecha_h.strftime('%d-%m-%Y')})</h3>
<table style="border-collapse:collapse;width:100%;font-size:13.5px">
<tr>{TH}Escenario</th>{THr}TC proyectado</th>{THr}Δ vs hoy</th></tr>
<tr><td style='padding:5px 10px;border-bottom:1px solid #E8EDF2'>P10 — piso probable</td>
    <td style='padding:5px 10px;border-bottom:1px solid #E8EDF2;text-align:right;font-family:Consolas,monospace;color:#0E7A54'>${es(p10)}</td>
    <td style='padding:5px 10px;border-bottom:1px solid #E8EDF2;text-align:right;font-family:Consolas,monospace'>{es((p10/spot-1)*100, 1)}%</td></tr>
<tr><td style='padding:5px 10px;border-bottom:1px solid #E8EDF2'><b>P50 — centro</b></td>
    <td style='padding:5px 10px;border-bottom:1px solid #E8EDF2;text-align:right;font-family:Consolas,monospace;font-weight:700'>${es(p50)}</td>
    <td style='padding:5px 10px;border-bottom:1px solid #E8EDF2;text-align:right;font-family:Consolas,monospace'>{es((p50/spot-1)*100, 1)}%</td></tr>
<tr><td style='padding:5px 10px'>P90 — techo probable</td>
    <td style='padding:5px 10px;text-align:right;font-family:Consolas,monospace;color:#9B3A2F'>${es(p90)}</td>
    <td style='padding:5px 10px;text-align:right;font-family:Consolas,monospace'>{es((p90/spot-1)*100, 1)}%</td></tr>
</table>
<div style="font-size:11.5px;color:#5B6B78;margin-top:6px">
Cono estadístico: deriva y volatilidad realizadas de las últimas ~90 observaciones
(σ diaria {es(sd*100, 2)}%), banda del 80% de confianza. <b>No es una predicción puntual</b> —
es el rango donde el TC cae 8 de cada 10 veces si el mercado se comporta como los últimos meses.
Eventos (Fed, TPM, cobre, política) pueden salirse del cono.</div>

<div style="margin-top:22px;border-top:1px solid #DCE3E8;padding-top:8px;color:#5B6B78;font-size:11.5px">
Fuente: mindicador.cl (Banco Central de Chile) · Generado {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')}.</div>
</div>"""

# ============ envío ============
if DRY:
    prev = ROOT / "data" / "outputs" / "pulso_indicadores_preview.html"
    prev.write_text(html, encoding="utf-8")
    print(f"[DRY] Preview -> {prev}")
    print(f"USD {es(spot)} ({es(usd_d1 or 0, 2)}% d) · cono10d {es(p10)}–{es(p90)} · "
          f"UF {es(uf[-1][1])} · alertas {len(alertas)}")
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
    msg["To"] = os.environ.get("PULSO_IND_TO", "andres@unionx.cl")
    msg["From"] = "andres@unionx.cl"
    icon = "🔴" if any(a.startswith("🔴") for a in alertas) else "💱"
    msg["Subject"] = (f"{icon} Pulso Indicadores · USD ${es(spot)} ({es(usd_d1 or 0, 1)}%) · "
                      f"cono 10d ${es(p10, 0)}–${es(p90, 0)} · {hoy.strftime('%d-%b')}")
    msg.set_content("Pulso de indicadores financieros (ver versión HTML).")
    msg.add_alternative(html, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"Enviado: USD {es(spot)} · cono {es(p10)}–{es(p90)}")
