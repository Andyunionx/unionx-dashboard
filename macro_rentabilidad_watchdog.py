# -*- coding: utf-8 -*-
"""Watchdog de la macro de rentabilidad.

Revisa dos cosas distintas, porque hay dos formas de que esto se muera sin que
nadie se entere:

  1. QUE EL PROCESO CORRA — lo revisa el workflow con la API de Actions.
  2. QUE LA PLANILLA ESTÉ VIVA — lo revisa este script. El proceso puede correr
     perfecto todos los lunes y la macro igual quedar inútil si Gabriela dejó de
     cargar su parte. Eso no lo detecta ningún check de workflow.

Avisa por correo SOLO a Andrés, y solo cuando hay algo que hacer.

Uso:
    python macro_rentabilidad_watchdog.py            # revisa y avisa si falta
    python macro_rentabilidad_watchdog.py --no-enviar  # solo imprime
"""
import argparse, base64, datetime, json, os, re, sys
from email.message import EmailMessage
from pathlib import Path

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from macro_rentabilidad_drive import SHEET_ID_FIJO, H_RAW, H_GAB, H_BASE, _cli, _num  # noqa: E402

AZ = '#1E3A5F'
PARA = os.environ.get('MACRO_WATCHDOG_TO', 'andres@unionx.cl')


def _gmail():
    tok = os.environ.get('GMAIL_TOKEN_JSON', '')
    tok = json.loads(tok) if tok else json.load(open(ROOT / 'agente-comex/config/token.json'))
    creds = Credentials.from_authorized_user_info(tok, tok.get('scopes'))
    if not creds.valid:
        creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)


def mes_anterior(hoy=None):
    hoy = hoy or datetime.date.today()
    primero = hoy.replace(day=1)
    ant = primero - datetime.timedelta(days=1)
    return ant.strftime('%Y-%m')


def revisar():
    sh = _cli().open_by_key(SHEET_ID_FIJO)
    out = {'alertas': [], 'sheet': f'https://docs.google.com/spreadsheets/d/{SHEET_ID_FIJO}'}

    # --- la pestaña del script ---
    raw = sh.worksheet(H_RAW).get_all_values()
    meses_raw = sorted({r[1] for r in raw[1:] if len(r) > 1 and r[1].strip()})
    out['raw_filas'] = len(raw) - 1
    out['raw_meses'] = meses_raw
    if not meses_raw:
        out['alertas'].append(('La pestaña del RAW está vacía',
                               'El proceso automático no dejó ninguna fila. Revisar la corrida.'))

    # --- la pestaña de Gabriela ---
    gab = sh.worksheet(H_GAB).get_all_values()
    cab = gab[0]
    iMes, iVal = cab.index('Mes'), cab.index('Valor')
    con_valor = [r for r in gab[1:] if len(r) > iVal and r[iVal].strip()]
    meses_gab = sorted({r[iMes] for r in con_valor if r[iMes].strip()})
    total = sum(_num(r[iVal]) for r in con_valor)
    out['gab_filas'] = len(con_valor)
    out['gab_meses'] = meses_gab
    out['gab_total'] = total

    objetivo = mes_anterior()
    if objetivo not in meses_gab:
        out['alertas'].append((
            f'Gabriela no ha cargado {objetivo}',
            f'La macro tiene la venta de {objetivo} desde el RAW, pero no sus comisiones ni '
            f'marketing. Sin eso el margen de ese mes queda sobreestimado. '
            f'Último mes que cargó: {meses_gab[-1] if meses_gab else "ninguno"}.'))

    # --- meses donde hay venta pero no hay costo de Gabriela ---
    huecos = [m for m in meses_raw if m not in meses_gab]
    if huecos:
        out['alertas'].append((
            f'{len(huecos)} mes(es) con venta y sin costos comerciales',
            'Meses en el RAW sin ninguna fila cargada por Gabriela: ' + ', '.join(huecos) + '. '
            'El margen de esos meses sale inflado.'))

    # --- la base de la dinámica ---
    try:
        base = sh.worksheet(H_BASE).get_all_values()
        out['base_filas'] = len(base) - 1
        if len(base) <= 1:
            out['alertas'].append(('La base de la dinámica está vacía',
                                   'La pestaña 6. Rentabilidad no va a mostrar nada.'))
    except gspread.WorksheetNotFound:
        out['base_filas'] = 0
        out['alertas'].append(('No existe la base de la dinámica',
                               'El proceso nunca llegó a crearla.'))
    return out


def enviar(o):
    filas = ''.join(
        f'<tr><td style="padding:7px 11px;border:1px solid #d5dbe5;font-weight:600">{t}</td>'
        f'<td style="padding:7px 11px;border:1px solid #d5dbe5">{d}</td></tr>'
        for t, d in o['alertas'])
    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.55;max-width:760px">
<p>La macro de rentabilidad por canal tiene {len(o['alertas'])} tema(s) pendiente(s).</p>
<table style="border-collapse:collapse;margin:10px 0 18px 0">
<tr><th style="padding:7px 11px;border:1px solid #d5dbe5;background:{AZ};color:#fff;text-align:left">Qué pasa</th>
<th style="padding:7px 11px;border:1px solid #d5dbe5;background:{AZ};color:#fff;text-align:left">Detalle</th></tr>
{filas}</table>
<p style="background:#EBF0F8;border-left:4px solid {AZ};padding:11px 15px">
<b>Estado de la planilla</b><br>
Pesta&ntilde;a del RAW: {o['raw_filas']} filas · meses {', '.join(o['raw_meses']) or '&mdash;'}<br>
Carga de Gabriela: {o['gab_filas']} filas · ${o['gab_total']:,.0f} · meses {', '.join(o['gab_meses']) or '&mdash;'}<br>
Base de la din&aacute;mica: {o['base_filas']} filas</p>
<p>🔗 <a href="{o['sheet']}">Abrir la planilla</a></p>
</div>""".replace(',', '.')
    m = EmailMessage()
    m['To'] = PARA
    m['From'] = 'andres@unionx.cl'
    m['Subject'] = f'⚠️ Macro rentabilidad — {len(o["alertas"])} tema(s) pendiente(s)'
    m.add_alternative(html, subtype='html')
    r = _gmail().users().messages().send(
        userId='me', body={'raw': base64.urlsafe_b64encode(m.as_bytes()).decode()}).execute()
    print(f'[aviso] enviado a {PARA} · msg_id {r["id"]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-enviar', action='store_true')
    a = ap.parse_args()
    o = revisar()
    print(f'RAW        : {o["raw_filas"]} filas · {o["raw_meses"]}')
    print(f'Gabriela   : {o["gab_filas"]} filas · ${o["gab_total"]:,.0f} · {o["gab_meses"]}')
    print(f'Base dinám.: {o["base_filas"]} filas')
    if not o['alertas']:
        print('\n[OK] la macro está al día — no se envía nada.')
        return
    print(f'\n{len(o["alertas"])} alerta(s):')
    for t, d in o['alertas']:
        print(f'  · {t}: {d}')
    if a.no_enviar:
        print('\n→ --no-enviar: no se manda el correo.')
        return
    enviar(o)


if __name__ == '__main__':
    main()
