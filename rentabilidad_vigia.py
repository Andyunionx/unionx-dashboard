# -*- coding: utf-8 -*-
"""Vigía de la carpeta de liquidaciones de Gabriela (frente Rentabilidad).

Una vez al día revisa la carpeta de Drive. Si hay archivos nuevos o modificados desde la
última revisión, lee los meses afectados con la lectura automática, los compara con la
carga de Gabriela (pestaña "2. Carga Gabriela" de la macro) y les manda a Gabriela y a
Andrés un aviso corto: qué llegó, si cuadra por canal y centro de costo, y qué glosas
vienen sin regla en la receta. Si no hay cambios, no manda nada.

Estado: data/rentabilidad/vigia_estado.json (id de archivo → fecha de modificación).
La primera corrida solo registra lo que hay, sin avisar.

Uso: python rentabilidad_vigia.py [--no-mail] [--sembrar]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import tempfile
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

import rentabilidad_liquidaciones as RL
import rentabilidad_reporte_semanal as R

ROOT = Path(__file__).parent
ESTADO = ROOT / 'data' / 'rentabilidad' / 'vigia_estado.json'
TO = [x.strip() for x in os.environ.get('RENTABILIDAD_TO', 'gabriela@unionx.cl').split(',') if x.strip()]
CC = [x.strip() for x in os.environ.get('RENTABILIDAD_CC', 'andres@unionx.cl').split(',') if x.strip()]
MESES = R.MESES_ES
ANIO = int(os.environ.get('RENTABILIDAD_ANIO', '2026'))
CARPETA_CANAL = {'FALABELLA': 'Falabella', 'MELI': 'Mercado Libre', 'PARIS': 'Paris', 'RIPLEY': 'Ripley', 'WALMART': 'Walmart'}


def listado():
    """[(canal, mes, subcarpeta, file)] de toda la carpeta."""
    drv, arbol = R.drive_carpeta()
    out = []
    for canal, meses in arbol.items():
        for mes, fs in meses.items():
            for f, sub in fs:
                out.append((canal, mes, sub, f))
    return drv, arbol, out


def cambios(items, estado):
    nuevos, modif = [], []
    for canal, mes, sub, f in items:
        prev = estado.get(f['id'])
        if prev is None:
            nuevos.append((canal, mes, sub, f))
        elif prev != f['modifiedTime']:
            modif.append((canal, mes, sub, f))
    vivos = {f['id'] for *_, f in items}
    borrados = [k for k in estado if k not in vivos]
    return nuevos, modif, borrados


def leer_mes(drv, arbol, mes):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        R.bajar_mes(drv, arbol, mes, Path(td))
        return RL.leer_carpeta(Path(td))


def cuadre(liq, gab, mes_str, canales):
    a = liq[liq['canal'].isin(canales)].groupby(['canal', 'centro_costo'])['monto_neto'].sum()
    g = gab[(gab['Mes'] == mes_str) & gab['Canal'].isin(canales)].groupby(['Canal', 'cc'])['Valor'].sum()
    g.index.names = a.index.names
    q = pd.DataFrame({'lectura': a, 'carga': g}).fillna(0)
    q = q[(q['lectura'].abs() > 1) | (q['carga'].abs() > 1)]
    q['dif'] = q['lectura'] - q['carga']
    return q


def fm(v):
    return ('−' if v < 0 else '') + '$' + f"{abs(v) / 1e6:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') + ' M'


def correo(nuevos, modif, borrados, por_mes):
    td = 'padding:5px 9px;border:1px solid #d5dbe5;font-size:12.5px'
    th = lambda x, a='left': f'<th style="{td};background:#1E3A5F;color:#fff;text-align:{a}">{x}</th>'  # noqa: E731
    parts = ['<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.5;max-width:820px">',
             '<p>Hola Gabriela,</p><p>Llegaron cambios a la carpeta de liquidaciones. Esto es lo que leyó el proceso automático:</p>']
    filas = ''.join(f'<tr><td style="{td}">{"nuevo" if k == "n" else "modificado"}</td><td style="{td}">{c}</td>'
                    f'<td style="{td}">{MESES[m]}</td><td style="{td}">{f["name"]}</td></tr>'
                    for k, lst in (('n', nuevos), ('m', modif)) for c, m, s, f in lst)
    parts.append(f'<table style="border-collapse:collapse;margin:4px 0 12px"><tr>{th("Cambio")}{th("Carpeta")}{th("Mes")}{th("Archivo")}</tr>{filas}</table>')
    if borrados:
        parts.append(f'<p style="font-size:12.5px;color:#475569">Además se sacaron {len(borrados)} archivo(s) de la carpeta.</p>')
    for mes, (q, sin_regla, cour) in sorted(por_mes.items()):
        parts.append(f'<p><b>{MESES[mes]}: lectura automática vs tu carga</b></p>')
        if len(q):
            fq = ''.join(f'<tr><td style="{td}">{c}</td><td style="{td}">{cc or "(sin centro)"}</td><td style="{td};text-align:right">{fm(r.lectura)}</td>'
                         f'<td style="{td};text-align:right">{fm(r.carga)}</td><td style="{td};text-align:right;color:{"#15803D" if abs(r.dif) <= max(abs(r.carga) * 0.02, 1000) else "#B91C1C"}">'
                         f'{"cuadra" if abs(r.dif) <= max(abs(r.carga) * 0.02, 1000) else fm(r.dif)}</td></tr>'
                         for (c, cc), r in q.iterrows())
            parts.append(f'<table style="border-collapse:collapse;margin:4px 0 8px"><tr>{th("Canal")}{th("Centro de costo")}{th("Lectura", "right")}{th("Tu carga", "right")}{th("Diferencia", "right")}</tr>{fq}</table>')
        if len(cour):
            fc = ''.join(f'<tr><td style="{td}">{cu}</td><td style="{td}">{c}</td><td style="{td};text-align:right">{fm(v)}</td></tr>' for (cu, c), v in cour.items())
            parts.append('<p style="margin:6px 0 2px">Couriers por canal (lectura automática):</p>'
                         f'<table style="border-collapse:collapse;margin:4px 0 8px"><tr>{th("Courier")}{th("Canal")}{th("Monto neto", "right")}</tr>{fc}</table>')
        if len(sin_regla):
            fs = ''.join(f'<tr><td style="{td}">{c}</td><td style="{td}">{g}</td><td style="{td};text-align:right">{fm(v)}</td></tr>'
                         for (c, g), v in sin_regla.items())
            parts.append('<p style="margin:6px 0 2px">Glosas que no están en la receta (hay que definir su centro de costo):</p>'
                         f'<table style="border-collapse:collapse;margin:4px 0 8px"><tr>{th("Canal")}{th("Glosa")}{th("Monto neto", "right")}</tr>{fs}</table>')
    parts.append('<p style="font-size:12.5px;color:#475569">Montos netos. "Cuadra" = diferencia menor a 2%. Este aviso sale solo cuando hay cambios en la carpeta; '
                 'el informe completo sigue llegando los lunes.</p><p>Saludos,<br>Andrés</p></div>')
    return ''.join(parts)


def enviar(asunto, html):
    t = os.environ.get('GMAIL_TOKEN_JSON', '').strip()
    if not t:
        p = ROOT / 'agente-comex' / 'config' / 'token.json'
        t = p.read_text() if p.exists() else ''
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    d = json.loads(t)
    c = Credentials.from_authorized_user_info(d, d.get('scopes'))
    if c.expired and c.refresh_token:
        c.refresh(Request())
    m = EmailMessage()
    m['From'] = 'andres@unionx.cl'
    m['To'] = ', '.join(TO)
    if CC:
        m['Cc'] = ', '.join(CC)
    m['Subject'] = asunto
    m.set_content('Ver versión HTML.')
    m.add_alternative(html, subtype='html')
    r = build('gmail', 'v1', credentials=c).users().messages().send(userId='me', body={'raw': base64.urlsafe_b64encode(m.as_bytes()).decode()}).execute()
    return r.get('id')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-mail', action='store_true')
    ap.add_argument('--sembrar', action='store_true', help='solo registra lo que hay hoy, sin avisar')
    a = ap.parse_args()
    estado = json.loads(ESTADO.read_text(encoding='utf-8')) if ESTADO.exists() else {}
    drv, arbol, items = listado()
    nuevo_estado = {f['id']: f['modifiedTime'] for *_, f in items}
    if a.sembrar or not estado:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(nuevo_estado, indent=1), encoding='utf-8')
        print(f'[vigía] estado sembrado con {len(nuevo_estado)} archivos (sin aviso)')
        return
    nuevos, modif, borrados = cambios(items, estado)
    print(f'[vigía] {len(items)} archivos · nuevos {len(nuevos)} · modificados {len(modif)} · sacados {len(borrados)}')
    if not (nuevos or modif or borrados):
        print('[vigía] sin cambios: no se avisa')
        return
    _, _, gab, _ = R.cargar()
    por_mes = {}
    for mes in sorted({m for _, m, _, _ in nuevos + modif}):
        carpetas = {c for c, m, _, _ in nuevos + modif if m == mes}
        liq = leer_mes(drv, arbol, mes)
        mks = [CARPETA_CANAL[c] for c in carpetas if c in CARPETA_CANAL]
        q = cuadre(liq, gab, f'{ANIO}-{mes:02d}', mks) if mks else pd.DataFrame(columns=['lectura', 'carga', 'dif'])
        cour = (liq[liq['cuenta'].isin(['Recíbelo', 'BlueX'])].groupby(['cuenta', 'canal'])['monto_neto'].sum()
                if any(c not in CARPETA_CANAL for c in carpetas) else pd.Series(dtype=float))
        sr = liq[liq['estado_regla'].astype(str) != 'ok'].groupby(['canal', 'glosa'])['monto_neto'].sum()
        sr = sr[sr.abs() >= 1]
        por_mes[mes] = (q, sr, cour)
        print(f'[vigía] {MESES[mes]}: {len(q)} filas de cuadre · {len(sr)} glosas sin regla')
    html = correo(nuevos, modif, borrados, por_mes)
    resumen = ', '.join(sorted({f'{c} {MESES[m].lower()}' for c, m, _, _ in nuevos + modif}))
    asunto = f'Liquidaciones: llegó {resumen}'
    if a.no_mail:
        (ROOT / 'vigia_preview.html').write_text(html, encoding='utf-8')
        print(f'[vigía] --no-mail: {asunto} → vigia_preview.html')
    else:
        print(f'[vigía] enviado {enviar(asunto, html)} · {asunto}')
    ESTADO.write_text(json.dumps(nuevo_estado, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
