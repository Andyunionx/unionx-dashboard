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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true")
    a = ap.parse_args()
    hoy = datetime.date.today()
    semana = hoy.isocalendar()[1]

    # --- sección 1: devoluciones (archivo del agente, hoja EMITIBLES)
    F = OUT / "NC_2026_DISPONIBLES_emitir.xlsx"
    xl = pd.ExcelFile(F)
    em = xl.parse([s for s in xl.sheet_names if "EMITIBLES" in s][0])
    full_exc = xl.parse([s for s in xl.sheet_names if "revisadas" in s][0])
    ff = full_exc[full_exc["estado_vivo"].str.startswith("FULFILLMENT")]
    piv_dev = em.pivot_table(index="mes", columns="canal", values="monto_NC", aggfunc="sum").fillna(0)
    piv_dev["TOTAL"] = piv_dev.sum(axis=1)

    # --- sección 2: cancelaciones. CRITERIO VÍCTOR (05-08): NC directa = cancelado
    # + boleta + SIN despacho. Con despacho = validar estado seller. Barridas fuera.
    C = pd.read_excel(OUT / "NC_cancelados_AUDITADO_v4_20260805.xlsx")
    barridas = C[C["origen"] != "Cancelación orgánica"]
    C = C[C["origen"] == "Cancelación orgánica"]
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
