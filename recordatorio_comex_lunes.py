"""Recordatorio semanal COMEX — cada lunes 9 AM (Task Scheduler / GH Actions).

REFACTOR JUN-2026: la fuente de verdad del estado de embarques pasó del mail
con Vicente a la **API de Seimex**. Eliminado el touchpoint mail-Vicente.

Lógica por embarque (data viva de Seimex + estado local):
  - Stage Seimex:     Por Embarcar / En tránsito / Por Cerrar / Entregadas
  - Booking Seimex:   ya tiene contenedor asignado
  - Flete cotizado:   Seimex.quoted_freight_value (reemplaza ¿cotizó Vicente?)
  - ETA Seimex:       fecha llegada estimada
  - Local:            PI, PL, tarifa, precosteo, PO Odoo

Reglas de clasificación:
  - WAITING_STEVEN_PI/PL    : sin PI o PL en disco local
  - NO_FLETE_SEIMEX         : PI/PL ok pero Seimex sin quoted_freight (Vicente
                              aún no lo cotizó en el portal)
  - PROCESS_PENDING         : todo listo, falta correr procesar_embarque.py
  - NO_PO_ODOO              : precosteo OK, falta crear/confirmar PO
  - INCIDENT_SEIMEX         : Seimex marca has_incident=true (alerta crítica)
  - DONE                    : PO Odoo activa

Output: mail consolidado a Andrés (no se contacta a Vicente automáticamente).
Si Andrés ve un embarque sin flete cotizado en Seimex, pide a Vicente manual.

Uso:
    python recordatorio_comex_lunes.py            # full
    python recordatorio_comex_lunes.py --dry-run  # imprime, no envía
"""
import argparse
import base64
import os
import re
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent
EMB_DIR = PROJECT_ROOT / 'data' / 'comex' / 'embarques'
PRECOSTEO_DIR = PROJECT_ROOT / 'agente-comex' / 'data' / 'output'

DESTINATARIO_ANDRES = 'andres@unionx.cl'

# Stages Seimex que cuentan como "activos" (no Cerrada ni Entregadas)
STAGES_ACTIVOS = {'Por Embarcar', 'En tránsito', 'Por Cerrar'}


def _cargar_env():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _codigo_4dig(s: str) -> str | None:
    """Extrae '0604' de 'PI0604' / '26TP0604' / ref Seimex."""
    if not s: return None
    m = re.search(r'PI(\d{4})', str(s).upper())
    if m: return m.group(1)
    m = re.search(r'26TP(\d{4})', str(s).upper())
    if m: return m.group(1)
    m = re.search(r'\b(\d{4})\b', str(s))
    return m.group(1) if m else None


def estado_archivos(emb: str) -> dict:
    """Detecta PI, PL, Tarifa, Precosteo locales."""
    base = EMB_DIR / emb
    pi = pl = None
    if base.exists():
        for f in base.iterdir():
            name = f.name.upper()
            if 'PL.XLSX' in name or 'PL ' in name:
                pl = f
            elif '40HQ' in name or 'DHL' in name or 'AIR' in name or 'PI' in name:
                if 'PL' not in name.split('.')[0].split():
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
    """PO Odoo del embarque (state activo)."""
    import xmlrpc.client
    url = os.environ.get('ODOO_URL', 'https://unionxb2b.odoo.com')
    db = os.environ.get('ODOO_DB', 'bmya-innovatek-sh-prd-6981800')
    user = os.environ.get('ODOO_USER') or 'andres@grupoeter.cl'
    pwd = os.environ.get('ODOO_API_KEY') or os.environ.get('ANDRES_ODOO_PASSWORD')
    if not pwd: return None
    try:
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True)
        uid = common.authenticate(db, user, pwd, {})
        models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
        pos = models.execute_kw(db, uid, pwd, 'purchase.order', 'search_read',
            [[('partner_id', '=', 1664),
              ('partner_ref', 'like', f'%{emb}%'),
              ('state', 'in', ['draft', 'sent', 'purchase'])]],
            {'fields': ['name', 'state', 'amount_total']})
        return pos[0] if pos else None
    except Exception:
        return None


def clasificar(emb: str, archivos: dict, seimex: dict, po: dict | None) -> tuple[str, str]:
    """Devuelve (categoria, accion_recomendada).

    Prioridad:
      1. INCIDENT (Seimex has_incident=true)
      2. DONE (PO Odoo activa + Seimex stage Por Cerrar/Entregadas)
      3. WAITING_STEVEN (sin PI/PL local)
      4. NO_FLETE_SEIMEX (sin quoted_freight)
      5. PROCESS_PENDING (todo OK, falta correr procesar_embarque)
      6. NO_PO_ODOO (precosteo OK, falta PO)
    """
    if seimex.get('has_incident'):
        return ('INCIDENT_SEIMEX', f'⚠️ Seimex marca incidente. Revisar portal.')

    if po and po.get('state') in ('draft', 'sent', 'purchase'):
        return ('DONE', f'PO activa ({po["name"]}, {po["state"]})')

    if not archivos['pi'] and not archivos['pl']:
        return ('WAITING_STEVEN_BOTH', 'Esperar Steven (PI + PL)')
    if not archivos['pi']:
        return ('WAITING_STEVEN_PI', 'Esperar PI de Steven')
    if not archivos['pl']:
        return ('WAITING_STEVEN_PL', 'Esperar PL de Steven')

    # PI + PL OK → ver flete Seimex
    flete = seimex.get('quoted_freight_value')
    if not flete:
        return ('NO_FLETE_SEIMEX',
                'Sin flete cotizado en Seimex. Andrés decide: usar tarifa estimada o pedir a Vicente manual.')

    if not archivos['tarifa']:
        return ('GENERATE_TARIFA',
                f'Vicente cotizó USD {flete}. Correr generar_tarifas_embarque.py --embarque {emb} --flete {flete}')

    if not archivos['precosteo']:
        return ('PROCESS_PENDING', f'Todo listo. Correr: python procesar_embarque.py {emb}')

    return ('NO_PO_ODOO', 'Precosteo listo, falta PO Odoo. Correr cargar_po_comex_odoo.py')


COLOR = {
    'DONE': '#16A34A',
    'WAITING_STEVEN_BOTH': '#94A3B8',
    'WAITING_STEVEN_PI': '#94A3B8',
    'WAITING_STEVEN_PL': '#94A3B8',
    'NO_FLETE_SEIMEX': '#EA580C',
    'GENERATE_TARIFA': '#F59E0B',
    'PROCESS_PENDING': '#1E40AF',
    'NO_PO_ODOO': '#1E40AF',
    'INCIDENT_SEIMEX': '#DC2626',
}


def _enviar_mail_andres(resumen: list[dict], gmail_svc):
    """Mail consolidado a Andrés con estado vivo de los embarques."""
    filas = ''
    for r in resumen:
        c = COLOR.get(r['categoria'], '#64748B')
        stage = r.get('stage', '?') or '?'
        eta = r.get('eta', '-') or '-'
        flete = r.get('flete')
        flete_str = f"${flete:,.0f}" if flete else '—'
        filas += (
            f'<tr>'
            f'<td style="border:1px solid #ddd;padding:6px 10px"><b>26TP{r["emb"]}</b></td>'
            f'<td style="border:1px solid #ddd;padding:6px 10px;font-size:11px">{stage}</td>'
            f'<td style="border:1px solid #ddd;padding:6px 10px">{eta}</td>'
            f'<td style="border:1px solid #ddd;padding:6px 10px;text-align:right">{flete_str}</td>'
            f'<td style="border:1px solid #ddd;padding:6px 10px">{"✅" if r["pi"] else "❌"}</td>'
            f'<td style="border:1px solid #ddd;padding:6px 10px">{"✅" if r["tarifa"] else "❌"}</td>'
            f'<td style="border:1px solid #ddd;padding:6px 10px">{"✅" if r["precosteo"] else "❌"}</td>'
            f'<td style="border:1px solid #ddd;padding:6px 10px">{"✅" if r["po"] else "❌"}</td>'
            f'<td style="border:1px solid #ddd;padding:6px 10px;color:{c}"><b>{r["categoria"]}</b></td>'
            f'<td style="border:1px solid #ddd;padding:6px 10px">{r["accion"]}</td>'
            f'</tr>'
        )

    html = f"""<div style="font-family:Arial,sans-serif;font-size:13px;color:#111;line-height:1.4">
<p>Hola Andrés,</p>
<p>Resumen semanal del pipeline COMEX al {datetime.now().strftime('%A %d-%b %H:%M')} — <b>fuente: Seimex API + Odoo + disco local</b>.</p>
<table style="border-collapse:collapse;font-size:12px;width:100%">
<thead><tr style="background:#1F4E78;color:#fff">
<th style="border:1px solid #ddd;padding:6px 10px">Embarque</th>
<th style="border:1px solid #ddd;padding:6px 10px">Stage Seimex</th>
<th style="border:1px solid #ddd;padding:6px 10px">ETA</th>
<th style="border:1px solid #ddd;padding:6px 10px">Flete USD</th>
<th style="border:1px solid #ddd;padding:6px 10px">PI/PL</th>
<th style="border:1px solid #ddd;padding:6px 10px">Tarifa</th>
<th style="border:1px solid #ddd;padding:6px 10px">Precost</th>
<th style="border:1px solid #ddd;padding:6px 10px">PO Odoo</th>
<th style="border:1px solid #ddd;padding:6px 10px">Categoría</th>
<th style="border:1px solid #ddd;padding:6px 10px">Acción</th>
</tr></thead>
<tbody>{filas}</tbody>
</table>
<p style="font-size:11px;color:#888;margin-top:15px">
Recordatorio automático lunes 9:00 AM · agente COMEX UnionX<br>
Refactor jun-2026: el agente ya NO manda mails a Vicente. La cotización
de flete se lee del portal Seimex. Si un embarque queda en
<code>NO_FLETE_SEIMEX</code>, contactar a Vicente manualmente.
</p>
</div>"""
    msg = MIMEMultipart('alternative')
    msg['to'] = DESTINATARIO_ANDRES
    msg['subject'] = f'[COMEX semanal] {len(resumen)} embarques · {datetime.now().strftime("%d-%b")}'
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

    print(f"=== Recordatorio COMEX Semanal — {datetime.now()} ===\n", flush=True)

    # 1. Leer estado vivo desde Seimex API
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from seimex_api import SeimexAPI, SeimexAPIError
        api = SeimexAPI()
        ops = api.get_operations()
    except Exception as e:
        print(f"[ERROR] Seimex API falló: {type(e).__name__}: {e}")
        return 1

    # Filtrar solo Topwill activos
    seimex_activos = []
    for op in ops:
        if 'TOPWILL' not in str(op.get('supplier', '')).upper(): continue
        if op.get('stage', {}).get('name') not in STAGES_ACTIVOS: continue
        cod = _codigo_4dig(op.get('reference_number')) or _codigo_4dig(op.get('product'))
        if not cod: continue
        seimex_activos.append({
            'cod': cod,
            'ref': op.get('reference_number'),
            'stage': op.get('stage', {}).get('name'),
            'eta': str(op.get('eta') or '')[:10],
            'flete': op.get('quoted_freight_value'),
            'has_incident': op.get('has_incident'),
            'booking': op.get('booking'),
        })

    if not seimex_activos:
        print("Sin embarques activos en Seimex.")
        return 0

    # Deduplicar por código (Seimex a veces tiene refs duplicadas)
    seen_codes = set()
    deduped = []
    for s in seimex_activos:
        if s['cod'] in seen_codes: continue
        seen_codes.add(s['cod'])
        deduped.append(s)
    seimex_activos = deduped
    seimex_activos.sort(key=lambda x: x.get('eta') or '9999')
    print(f"Embarques activos Seimex (Topwill): {len(seimex_activos)}\n", flush=True)

    # 2. Para cada uno: cruzar con local + Odoo
    sys.path.insert(0, str(PROJECT_ROOT / 'agente-comex' / 'src'))
    from gmail_client import GmailClient
    g = GmailClient()

    resumen = []
    for s in seimex_activos:
        emb = s['cod']
        try:
            archivos = estado_archivos(emb)
            po = po_odoo_activa(emb)
            categoria, accion = clasificar(emb, archivos, s, po)
            r = {
                'emb': emb,
                'ref_seimex': s['ref'],
                'stage': s['stage'],
                'eta': s['eta'],
                'flete': s['flete'],
                'pi': bool(archivos['pi']),
                'pl': bool(archivos['pl']),
                'tarifa': bool(archivos['tarifa']),
                'precosteo': bool(archivos['precosteo']),
                'po': bool(po),
                'po_name': po['name'] if po else None,
                'categoria': categoria,
                'accion': accion,
            }
            resumen.append(r)
            print(f"  26TP{emb}  {s['stage']:<14}  {categoria:<22}  → {accion[:55]}", flush=True)
        except Exception as e:
            print(f"  26TP{emb}  ERROR: {type(e).__name__}: {e}", flush=True)

    if args.dry_run:
        print(f"\n[DRY-RUN] {len(resumen)} embarques analizados. Sin enviar mail.")
        return 0

    # 3. Mail a Andrés (único destinatario; NO se contacta a Vicente)
    try:
        msg_id = _enviar_mail_andres(resumen, g.service)
        print(f"\n[OK] Resumen a Andrés enviado (id={msg_id})")
    except Exception as e:
        print(f"\n[ERROR] mail Andrés falló: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
