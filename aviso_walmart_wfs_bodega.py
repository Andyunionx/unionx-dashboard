# -*- coding: utf-8 -*-
"""Aviso a operaciones: pedidos WFS de Walmart quedaron con bodega Carrascal.

Dos modos:
  (sin flags)   envía el aviso inicial y deja el threadId en un JSON
  --recordatorio  responde en ese mismo hilo (lo dispara GitHub Actions el lunes)

El recordatorio corre en GitHub Actions y no en el notebook de Andrés a propósito:
Gerardo y Yohana están de vacaciones y el aviso no se puede perder.
"""
import argparse, base64, json, os, sys
from email.message import EmailMessage
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent
ESTADO = ROOT / "data/outputs/_aviso_walmart_wfs.json"
ADJ = ROOT / "data/outputs/walmart_wfs_bodega_incorrecta.csv"
TO = ["gerardo@unionx.cl", "facturacion@melollevo.cl"]
CC = ["andres@unionx.cl"]
AZ = "#1E3A5F"
ASUNTO = "Pedidos fulfillment de Walmart quedaron con bodega Carrascal (13-19 ago)"
# Hilo del aviso original (07-09-2026). Va acá y no solo en el JSON porque
# data/outputs está en .gitignore y el recordatorio corre en GitHub Actions,
# donde ese archivo no existe.
HILO = {"thread_id": "1a07cfc0cde07345",
        "message_id_header": "<CABHtFmcLKcD0QLMYr2AMBBRBdnvuWk31sJ4=LyhOErMvUj5jUg@mail.gmail.com>"}


def _svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    cj = os.environ.get("GMAIL_TOKEN_JSON", "")
    info = json.loads(cj) if cj else json.load(open(ROOT / "agente-comex/config/token.json"))
    creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


CUERPO = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.55;max-width:720px">
<p>Hola Gerardo, hola Yohana,</p>

<p>Detectamos algo revisando el cierre de agosto y quiero dejarlo planteado para cuando vuelvan.</p>

<p style="background:#EBF0F8;border-left:4px solid {AZ};padding:10px 14px;margin:14px 0">
<b>El problema:</b> entre el <b>13 y el 19 de agosto</b>, <b>156 de 200 pedidos de Walmart WFS (78%)</b> por
<b>$5.662.160</b> quedaron registrados en Odoo con bodega <b>Carrascal</b> en vez de <b>Bodega Fulfillment
Walmart</b>, pese a que Walmart los declara como despachados por ellos.</p>

<p><b>Cómo lo identificamos.</b> El pedido trae el campo <code>fulfillment</code>, que Walmart marca como
<code>fbc</code> (fulfilled by channel, o sea despacha Walmart) o <code>fbm</code> (despachamos nosotros).
Los 156 vienen marcados <code>fbc</code> pero Odoo les asignó igual la bodega Carrascal.</p>

<p><b>Qué SÍ está bien, para tranquilidad:</b></p>
<ul style="margin:6px 0 14px 18px;padding:0">
<li><b>El stock no se descuadró.</b> De los 312 pickings generados, los 122 que salían de CA1/Stock quedaron
<b>cancelados</b>, y los 27 que sí se despacharon salieron de BFW/Stock, que es lo correcto. Solo 29 unidades
pasaron por CA1 y venían de Walmart.</li>
<li><b>La falta de boleta es correcta:</b> en WFS factura Walmart al cliente final, no nosotros.</li>
<li><b>Mercado Libre y Falabella están impecables:</b> revisamos los 4.720 pedidos de fulfillment de agosto y
los 4.720 tienen su bodega correcta. Es un tema puntual de Walmart.</li>
</ul>

<p><b>Por qué importa igual.</b> La bodega del pedido es lo que alimenta los reportes por canal. Con esto, el
fulfillment de Walmart de agosto aparece en <b>$928 mil</b> cuando en realidad fue cerca de
<b>$6,6 millones</b>. Al mirar el cierre parecía que el canal se había caído, y no es así.</p>

<p><b>Lo que proponemos:</b></p>
<ol style="margin:6px 0 14px 18px;padding:0">
<li><b>Corregir los 156 pedidos</b> reasignando la bodega a Bodega Fulfillment Walmart. Va el detalle adjunto,
pedido por pedido.</li>
<li><b>Prevenir el rebote:</b> que el conector de Walmart mapee automáticamente
<code>fulfillment = fbc</code> &rarr; Bodega Fulfillment Walmart al crear el pedido, igual que ya funciona en
Mercado Libre y Falabella.</li>
<li><b>Entender qué pasó esa semana:</b> el 1 al 12 de agosto no hubo ninguna venta por WFS y el 13 aparecen
estos pedidos mal ruteados. Puede haber sido un quiebre de stock en la bodega de Walmart, una recarga o un
cambio en el conector. Saberlo evita que se repita.</li>
</ol>

<p>Gerardo, el punto 3 es el que más me interesa que revisemos juntos: el pulso de reposición de esta semana
tiene a Walmart pidiendo 534 unidades, el canal que más pide de los cuatro, lo que apunta a que se quedó sin
stock allá.</p>

<p>Cuando vuelvan lo vemos con calma. Cualquier duda me dicen.</p>
<p>Saludos,<br>Andrés</p>
</div>"""

RECORDATORIO = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.55;max-width:720px">
<p>Hola Gerardo, hola Yohana,</p>
<p>Les reitero este tema ahora que vuelven de vacaciones, para que no se pierda.</p>
<p style="background:#FFF3CD;border-left:4px solid #B8860B;padding:10px 14px;margin:14px 0">
Son los <b>156 pedidos de Walmart WFS</b> del 13 al 19 de agosto (<b>$5.662.160</b>) que quedaron con bodega
Carrascal en vez de Bodega Fulfillment Walmart. El detalle pedido por pedido va en el adjunto del correo
original, más abajo en este hilo.</p>
<p>Los tres puntos siguen pendientes:</p>
<ol style="margin:6px 0 14px 18px;padding:0">
<li>Corregir la bodega de los 156 pedidos.</li>
<li>Que el conector mapee <code>fulfillment = fbc</code> &rarr; Bodega Fulfillment Walmart, para que no se repita.</li>
<li>Entender qué pasó esa semana (posible quiebre de stock en la bodega de Walmart).</li>
</ol>
<p>¿Lo vemos esta semana?</p>
<p>Saludos,<br>Andrés</p>
</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recordatorio", action="store_true")
    a = ap.parse_args()
    svc = _svc()
    msg = EmailMessage()
    msg["To"] = ", ".join(TO)
    msg["Cc"] = ", ".join(CC)
    msg["From"] = "andres@unionx.cl"
    body = {"raw": None}

    if a.recordatorio:
        st = json.load(open(ESTADO)) if ESTADO.exists() else HILO
        if not st.get("thread_id"):
            print("[ERROR] no hay hilo previo registrado — no se envía el recordatorio")
            return 1
        msg["Subject"] = "Re: " + ASUNTO
        msg["In-Reply-To"] = st["message_id_header"]
        msg["References"] = st["message_id_header"]
        msg.add_alternative(RECORDATORIO, subtype="html")
        body["threadId"] = st["thread_id"]
    else:
        msg["Subject"] = ASUNTO
        msg.add_alternative(CUERPO, subtype="html")
        if ADJ.exists():
            msg.add_attachment(ADJ.read_bytes(), maintype="text", subtype="csv", filename=ADJ.name)

    body["raw"] = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = svc.users().messages().send(userId="me", body=body).execute()
    print(f"Enviado. msg_id={r['id']} threadId={r['threadId']}")

    if not a.recordatorio:
        d = svc.users().messages().get(userId="me", id=r["id"], format="metadata",
                                       metadataHeaders=["Message-ID"]).execute()
        mid = next((h["value"] for h in d["payload"]["headers"] if h["name"] == "Message-ID"), "")
        ESTADO.write_text(json.dumps({"thread_id": r["threadId"], "msg_id": r["id"],
                                      "message_id_header": mid}, indent=1), encoding="utf-8")
        print(f"Hilo registrado en {ESTADO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
