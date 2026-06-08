"""Recordatorio semanal COMEX — cada lunes 9 AM (Task Scheduler).

Para cada embarque "abierto" en el pipeline detecta qué falta y avisa.

Lógica por embarque:
  - Tiene PI?       (data/comex/embarques/XXXX/*PI*.xlsx que NO sea PL)
  - Tiene PL?       (data/comex/embarques/XXXX/*PL.xlsx)
  - Tiene Tarifa?   (data/comex/embarques/Tarifas_Base_COMEX-XXXX.xlsx)
  - Tiene Precosteo? (agente-comex/data/output/26TPXXXX/Pre-costeo_*.xlsx)
  - Tiene PO Odoo?  (purchase.order partner_id=Topwill ref like %XXXX%)

  - Si falta PI o PL → ESPERAR STEVEN (informativo, no se contacta)
  - Si falta Tarifa:
       * Si NO hay mail enviado a Vicente sobre el embarque → AVISA ANDRÉS
       * Si último mail a Vicente >3 días sin respuesta → MANDA recordatorio
       * Si <3 días → esperar
  - Si todo está pero no hay precosteo → comando exacto en el mail
  - Si precosteo OK pero no hay PO Odoo → comando exacto

Output: mail consolidado a andres@unionx.cl con tabla resumen + acción por
embarque. Recordatorios automáticos a Vicente solo cuando aplica el caso.

Uso:
    python recordatorio_comex_lunes.py            # full
    python recordatorio_comex_lunes.py --dry-run  # genera HTML, no envía
"""
import argparse
import base64
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent
EMB_DIR = PROJECT_ROOT / 'data' / 'comex' / 'embarques'
PRECOSTEO_DIR = PROJECT_ROOT / 'agente-comex' / 'data' / 'output'

DESTINATARIO_ANDRES = 'andres@unionx.cl'
VICENTE_EMAIL = 'vicente@seimex.cl'
DIAS_MAX_SIN_RESPUESTA_VICENTE = 3
# COOLDOWN: si en los últimos N días YA se mandó CUALQUIER mail a Vicente
# sobre el embarque (este recordatorio o cualquier otro proceso externo),
# NO mandamos otro. Evita spam por procesos paralelos no identificados
# (caso 26TP0528 del 28-may: 3 mails idénticos en un día desde fuera del repo).
COOLDOWN_DIAS_VICENTE = 7


def _cargar_env():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def detectar_embarques_activos() -> list[str]:
    """Devuelve códigos de 4 dígitos (ej '0528') con al menos un archivo en disco."""
    if not EMB_DIR.exists():
        return []
    codigos = set()
    for sub in EMB_DIR.iterdir():
        if sub.is_dir() and re.fullmatch(r'\d{4}', sub.name):
            codigos.add(sub.name)
    return sorted(codigos)


def estado_archivos(emb: str) -> dict:
    """Detecta PI, PL, Tarifa, Precosteo locales del embarque."""
    base = EMB_DIR / emb
    pi = pl = None
    if base.exists():
        for f in base.iterdir():
            name = f.name.upper()
            if 'PL.XLSX' in name or 'PL ' in name:
                pl = f
            elif '40HQ' in name or 'DHL' in name or 'AIR' in name or 'PI' in name:
                if 'PL' not in name.split('.')[0].split():  # evitar match cruzado
                    pi = f
    tarifa = EMB_DIR / f'Tarifas_Base_COMEX-{emb}.xlsx'
    precosteo_dir = PRECOSTEO_DIR / f'26TP{emb}'
    precosteo = next(precosteo_dir.glob(f'Pre-costeo_x_CBM_26TP{emb}.xlsx'), None) if precosteo_dir.exists() else None
    return {
        'pi': pi, 'pl': pl,
        'tarifa': tarifa if tarifa.exists() else None,
        'precosteo': precosteo,
    }


def po_odoo_activa(emb: str) -> dict | None:
    """Devuelve dict de la PO activa del embarque (state != cancel) o None."""
    import xmlrpc.client
    url = os.environ.get('ODOO_URL', 'https://unionxb2b.odoo.com')
    db = os.environ.get('ODOO_DB', 'bmya-innovatek-sh-prd-6981800')
    user = os.environ.get('ODOO_USER') or 'andres@grupoeter.cl'
    pwd = os.environ.get('ODOO_API_KEY') or os.environ.get('ANDRES_ODOO_PASSWORD')
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True)
    uid = common.authenticate(db, user, pwd, {})
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
    pos = models.execute_kw(db, uid, pwd, 'purchase.order', 'search_read',
        [[('partner_id', '=', 1664),
          ('partner_ref', 'like', f'%{emb}%'),
          ('state', 'in', ['draft', 'sent', 'purchase'])]],
        {'fields': ['name', 'state', 'amount_total']})
    return pos[0] if pos else None


def historia_vicente(emb: str, gmail_svc) -> dict:
    """Busca mails enviados a Vicente y respuestas sobre el embarque."""
    info = {'enviado_ts': None, 'respondido_ts': None}
    res = gmail_svc.users().messages().list(userId='me',
        q=f'to:{VICENTE_EMAIL} ({emb} OR 26TP{emb}) newer_than:60d',
        maxResults=5).execute()
    for m in res.get('messages', [])[:1]:  # más reciente
        full = gmail_svc.users().messages().get(userId='me', id=m['id'],
            format='metadata', metadataHeaders=['Date']).execute()
        for h in full.get('payload', {}).get('headers', []):
            if h['name'] == 'Date':
                try:
                    from email.utils import parsedate_to_datetime
                    info['enviado_ts'] = parsedate_to_datetime(h['value'])
                except Exception:
                    pass
                break
    res2 = gmail_svc.users().messages().list(userId='me',
        q=f'from:{VICENTE_EMAIL} ({emb} OR 26TP{emb}) newer_than:60d',
        maxResults=5).execute()
    for m in res2.get('messages', [])[:1]:
        full = gmail_svc.users().messages().get(userId='me', id=m['id'],
            format='metadata', metadataHeaders=['Date']).execute()
        for h in full.get('payload', {}).get('headers', []):
            if h['name'] == 'Date':
                try:
                    from email.utils import parsedate_to_datetime
                    info['respondido_ts'] = parsedate_to_datetime(h['value'])
                except Exception:
                    pass
                break
    return info


def clasificar(emb: str, archivos: dict, po: dict | None, vicente: dict) -> tuple[str, str, str]:
    """Devuelve (categoria, accion_recomendada, destinatario_accion)."""
    if po and po.get('state') in ('draft', 'sent', 'purchase'):
        return ('DONE', f'PO activa en Odoo ({po["name"]}, {po["state"]})', '-')

    if not archivos['pi'] and not archivos['pl']:
        return ('WAITING_STEVEN_BOTH', 'Esperar Steven (mandará PL día 1, PI día 3)', 'Steven (esperar)')
    if not archivos['pi']:
        return ('WAITING_STEVEN_PI', 'Esperar PI de Steven (~2 días después del PL)', 'Steven (esperar)')
    if not archivos['pl']:
        return ('WAITING_STEVEN_PL', 'Esperar PL de Steven', 'Steven (esperar)')

    if not archivos['tarifa']:
        now = datetime.now(timezone.utc)
        env = vicente.get('enviado_ts')
        resp = vicente.get('respondido_ts')
        if not env:
            return ('NO_COTIZACION_PEDIDA',
                    'Pedir cotización flete a Vicente (solicitar_flete_vicente.py)',
                    'Vicente (pedir manual)')
        if resp and resp >= env:
            return ('VICENTE_COTIZO_FALTA_GENERAR_TARIFA',
                    f'Vicente ya cotizó. Correr generar_tarifas_embarque.py --embarque {emb} --flete <USD>',
                    'Tú (generar tarifa)')
        dias_desde_envio = (now - env).total_seconds() / 86400
        # COOLDOWN: si último mail a Vicente sobre el emb fue hace <COOLDOWN_DIAS,
        # NO mandamos otro, sin importar si está "late". Evita spam.
        if dias_desde_envio < COOLDOWN_DIAS_VICENTE:
            return ('WAITING_VICENTE_COOLDOWN',
                    f'Último mail a Vicente hace {dias_desde_envio:.1f}d (<{COOLDOWN_DIAS_VICENTE}d cooldown). NO recordar.',
                    'Vicente (cooldown activo)')
        if dias_desde_envio > DIAS_MAX_SIN_RESPUESTA_VICENTE:
            return ('VICENTE_LATE',
                    f'Vicente lleva {dias_desde_envio:.0f} días sin responder y cooldown OK — recordar',
                    'Vicente (recordatorio AUTO)')
        return ('WAITING_VICENTE', f'Vicente: pedido hace {dias_desde_envio:.1f} días, esperar', 'Vicente (esperar)')

    if not archivos['precosteo']:
        return ('PROCESS_PENDING',
                f'Tiene todo. Correr: python procesar_embarque.py {emb}',
                'Tú (procesar)')

    return ('NO_PO_ODOO',
            f'Precosteo listo, falta cargar PO. Correr cargar_po_comex_odoo.py',
            'Tú (cargar Odoo)')


COLOR = {
    'DONE': '#16A34A',
    'WAITING_STEVEN_BOTH': '#94A3B8',
    'WAITING_STEVEN_PI': '#94A3B8',
    'WAITING_STEVEN_PL': '#94A3B8',
    'NO_COTIZACION_PEDIDA': '#EA580C',
    'VICENTE_COTIZO_FALTA_GENERAR_TARIFA': '#EA580C',
    'WAITING_VICENTE': '#F59E0B',
    'WAITING_VICENTE_COOLDOWN': '#94A3B8',
    'VICENTE_LATE': '#DC2626',
    'PROCESS_PENDING': '#1E40AF',
    'NO_PO_ODOO': '#1E40AF',
}


def _enviar_recordatorio_vicente(embarques_late: list[dict], gmail_svc):
    """Mail consolidado a Vicente con CC Andrés."""
    if not embarques_late:
        return None
    filas = ''.join(
        f'<tr>'
        f'<td style="border:1px solid #888;padding:6px 10px"><b>26TP{e["emb"]}</b></td>'
        f'<td style="border:1px solid #888;padding:6px 10px">{e["dias"]:.0f} días</td>'
        f'<td style="border:1px solid #888;padding:6px 10px">{e["enviado"].strftime("%Y-%m-%d")}</td>'
        f'</tr>' for e in embarques_late
    )
    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#111;line-height:1.5">
<p>Hola Vicente,</p>
<p>Recordatorio: estamos pendientes de tu cotización de flete para {len(embarques_late)} embarque(s) que llevan más de {DIAS_MAX_SIN_RESPUESTA_VICENTE} días sin respuesta:</p>
<table style="border-collapse:collapse;font-size:13px">
<thead><tr style="background:#1F4E78;color:#fff">
<th style="border:1px solid #888;padding:6px 10px">Embarque</th>
<th style="border:1px solid #888;padding:6px 10px">Pendiente</th>
<th style="border:1px solid #888;padding:6px 10px">Solicitado el</th>
</tr></thead>
<tbody>{filas}</tbody>
</table>
<p>Cualquier consulta, quedo atento.</p>
<p>Saludos,<br>Andrés Browne<br><i>Gerente Finanzas + Supply Chain · UnionX</i></p>
<p style="font-size:11px;color:#888;margin-top:20px">Recordatorio automático generado por agente COMEX UnionX.</p>
</div>"""
    msg = MIMEMultipart('alternative')
    msg['to'] = VICENTE_EMAIL
    msg['cc'] = DESTINATARIO_ANDRES
    msg['subject'] = f'Recordatorio: cotización flete pendiente ({len(embarques_late)} embarques)'
    msg.attach(MIMEText('Ver HTML.', 'plain', 'utf-8'))
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = gmail_svc.users().messages().send(userId='me', body={'raw': raw}).execute()
    return sent['id']


def _enviar_mail_andres(resumen: list[dict], gmail_svc, vicente_msg_id: str | None):
    """Mail consolidado a Andrés con estado de cada embarque."""
    filas = ''
    for r in resumen:
        c = COLOR.get(r['categoria'], '#64748B')
        filas += (f'<tr>'
                  f'<td style="border:1px solid #ddd;padding:6px 10px"><b>26TP{r["emb"]}</b></td>'
                  f'<td style="border:1px solid #ddd;padding:6px 10px">{"✅" if r["pi"] else "❌"}</td>'
                  f'<td style="border:1px solid #ddd;padding:6px 10px">{"✅" if r["pl"] else "❌"}</td>'
                  f'<td style="border:1px solid #ddd;padding:6px 10px">{"✅" if r["tarifa"] else "❌"}</td>'
                  f'<td style="border:1px solid #ddd;padding:6px 10px">{"✅" if r["precosteo"] else "❌"}</td>'
                  f'<td style="border:1px solid #ddd;padding:6px 10px">{"✅" if r["po"] else "❌"}</td>'
                  f'<td style="border:1px solid #ddd;padding:6px 10px;color:{c}"><b>{r["categoria"]}</b></td>'
                  f'<td style="border:1px solid #ddd;padding:6px 10px">{r["accion"]}</td>'
                  f'</tr>')

    aviso_vicente = ''
    if vicente_msg_id:
        aviso_vicente = (f'<p>📧 Mail recordatorio enviado automáticamente a Vicente '
                         f'(id <code>{vicente_msg_id}</code>) por las cotizaciones con '
                         f'>{DIAS_MAX_SIN_RESPUESTA_VICENTE} días sin respuesta.</p>')

    html = f"""<div style="font-family:Arial,sans-serif;font-size:13px;color:#111;line-height:1.4">
<p>Hola Andrés,</p>
<p>Resumen semanal del pipeline COMEX al {datetime.now().strftime('%A %d-%b %H:%M')}:</p>
{aviso_vicente}
<table style="border-collapse:collapse;font-size:12px;width:100%">
<thead><tr style="background:#1F4E78;color:#fff">
<th style="border:1px solid #ddd;padding:6px 10px">Embarque</th>
<th style="border:1px solid #ddd;padding:6px 10px">PI</th>
<th style="border:1px solid #ddd;padding:6px 10px">PL</th>
<th style="border:1px solid #ddd;padding:6px 10px">Tarifa</th>
<th style="border:1px solid #ddd;padding:6px 10px">Pre-cost</th>
<th style="border:1px solid #ddd;padding:6px 10px">PO Odoo</th>
<th style="border:1px solid #ddd;padding:6px 10px">Categoría</th>
<th style="border:1px solid #ddd;padding:6px 10px">Acción</th>
</tr></thead>
<tbody>{filas}</tbody>
</table>
<p style="font-size:11px;color:#888;margin-top:15px">Recordatorio automático lunes 9:00 AM · agente COMEX UnionX</p>
</div>"""
    msg = MIMEMultipart('alternative')
    msg['to'] = DESTINATARIO_ANDRES
    msg['subject'] = f'[COMEX semanal] {len(resumen)} embarques con gaps · {datetime.now().strftime("%d-%b")}'
    msg.attach(MIMEText('Ver HTML.', 'plain', 'utf-8'))
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = gmail_svc.users().messages().send(userId='me', body={'raw': raw}).execute()
    return sent['id']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='No enviar mails, solo imprimir')
    args = parser.parse_args()
    _cargar_env()

    print(f"=== Recordatorio COMEX Lunes — {datetime.now()} ===\n", flush=True)
    embs = detectar_embarques_activos()
    if not embs:
        print("Sin embarques activos en carpeta data/comex/embarques/. Nada que reportar.")
        return 0

    # Gmail client
    sys.path.insert(0, str(PROJECT_ROOT / 'agente-comex' / 'src'))
    from gmail_client import GmailClient
    g = GmailClient()

    resumen = []
    vicente_late = []
    for emb in embs:
        try:
            archivos = estado_archivos(emb)
            po = po_odoo_activa(emb)
            vicente = historia_vicente(emb, g.service)
            categoria, accion, destinatario = clasificar(emb, archivos, po, vicente)
            r = {
                'emb': emb, 'pi': bool(archivos['pi']), 'pl': bool(archivos['pl']),
                'tarifa': bool(archivos['tarifa']), 'precosteo': bool(archivos['precosteo']),
                'po': bool(po), 'categoria': categoria, 'accion': accion,
                'destinatario': destinatario,
            }
            resumen.append(r)
            if categoria == 'VICENTE_LATE':
                dias = (datetime.now(timezone.utc) - vicente['enviado_ts']).total_seconds() / 86400
                vicente_late.append({'emb': emb, 'enviado': vicente['enviado_ts'], 'dias': dias})
            print(f"  26TP{emb}  {categoria:<40}  → {accion[:60]}", flush=True)
        except Exception as e:
            print(f"  26TP{emb}  ERROR: {type(e).__name__}: {e}", flush=True)

    if args.dry_run:
        print(f"\n[DRY-RUN] {len(resumen)} embarques analizados, {len(vicente_late)} late Vicente. Sin enviar.")
        return 0

    # Mail a Vicente si aplica
    vicente_msg_id = None
    if vicente_late:
        try:
            vicente_msg_id = _enviar_recordatorio_vicente(vicente_late, g.service)
            print(f"\n[OK] Recordatorio a Vicente enviado (id={vicente_msg_id})")
        except Exception as e:
            print(f"\n[WARN] mail Vicente falló: {type(e).__name__}: {e}")

    # Mail a Andrés siempre
    try:
        msg_id = _enviar_mail_andres(resumen, g.service, vicente_msg_id)
        print(f"[OK] Resumen a Andrés enviado (id={msg_id})")
    except Exception as e:
        print(f"[ERROR] mail Andrés falló: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
