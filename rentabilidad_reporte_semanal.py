# -*- coding: utf-8 -*-
"""Reporte semanal de Rentabilidad por canal (lunes).

Mismo formato que el primer informe ("Rentabilidad por canal — Agosto vs Julio 2026 ·
informe, seguimiento del plan y automatización", 22-09-2026), generado solo cada lunes
desde la planilla macro y la carpeta de liquidaciones:

  1. Resultado: margen por canal, último mes con carga de Gabriela vs el anterior.
  2. Dónde dar ojo: canales que más se movieron y las glosas que lo explican (automático).
  3. Seguimiento del plan: pestaña '8. Plan de acción' + alertas de gestión (acciones sin
     responsable, sin fecha, sin gestión o vencidas) → la presión semanal.
  4. Estado de la automatización: qué liquidaciones hay en la carpeta de Drive para el
     mes, y si la lectura automática cuadra con la carga manual de Gabriela.
  Adjunto: HTML con gráficos (puente del margen y glosas que más se movieron por canal).

Uso:
    python rentabilidad_reporte_semanal.py                 # vista previa solo a Andrés
    python rentabilidad_reporte_semanal.py --enviar        # a Gabriela, cc Andrés
    python rentabilidad_reporte_semanal.py --no-mail       # solo genera archivos
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html as H
import io
import json
import os
import re
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import macro_plan_accion as PA            # noqa: E402
import macro_rentabilidad_drive as D     # noqa: E402

CARPETA_LIQ = '1JfVgnTg0F2OkMHvX1EW4CsFvYQspHeYV'
URL_SHEET = 'https://docs.google.com/spreadsheets/d/1re-VnNWZiRmfbifJoOPS_oyyzVHVEnuvQ7645Baq4Ck'
URL_CARPETA = f'https://drive.google.com/drive/folders/{CARPETA_LIQ}'
MK = ['Mercado Libre', 'Falabella', 'Walmart', 'Paris', 'Ripley']
ORD_CC = ['Comisión venta', 'Comisión envío', 'Marketing']
MESES_ES = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
            9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}
# Qué debe haber en la carpeta cada mes (subcarpeta del canal → archivos esperados)
ESPERADO = {'FALABELLA': 'Liquidación (InvoiceReport)', 'MELI': 'ML 1 y ML 2: facturación, NC, NC Flex, ND Flex',
            'PARIS': 'FF y Seller (transactions_report)', 'RIPLEY': 'Liquidaciones semanales Mirakl',
            'WALMART': 'Liquidaciones quincenales', 'Recibelo-Blue': 'Costeo Recíbelo + detalle BlueX'}
MES_CARPETA = {v.upper(): k for k, v in MESES_ES.items()}
MES_ABREV = {'ENE': 1, 'FEB': 2, 'MAR': 3, 'ABR': 4, 'MAY': 5, 'JUN': 6, 'JUL': 7, 'AGO': 8, 'SEP': 9, 'SEPT': 9,
             'SET': 9, 'OCT': 10, 'NOV': 11, 'DIC': 12}


def mes_carpeta(nombre):
    """Mes de una carpeta de la liquidación: con el nombre completo ("AGOSTO MELI 1") o abreviado como palabra
    ("SEPT MELI 1", 7-oct: la liquidación de ML de septiembre no se leía). La abreviatura se compara por palabra
    entera para no confundir MAR con MARKETING."""
    u = str(nombre).upper()
    mes = next((v for k, v in MES_CARPETA.items() if k in u), None)
    if mes:
        return mes
    return next((MES_ABREV[w] for w in re.findall(r'[A-ZÁÉÍÓÚÑ]+', u) if w in MES_ABREV), None)


def n(x, d=1):
    return f'{x:,.{d}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def pp(x, d=1):
    return ('+' if x > 0 else '') + n(x, d)


def mm(x):
    return ('-' if x < 0 else '') + '$' + n(abs(x) / 1e6, 1) + ' M'


def nom(m):
    return MESES_ES[int(m[5:7])]


# ───────────────────────── datos ─────────────────────────
def cargar():
    gc = D._cli()
    sh, _ = D._abrir(gc, crear_si_falta=False)
    vb = sh.worksheet(D.H_BASE).get_all_values(value_render_option='UNFORMATTED_VALUE')
    base = pd.DataFrame(vb[1:], columns=vb[0])
    base['Monto'] = pd.to_numeric(base['Monto'], errors='coerce').fillna(0)
    base['Mes'] = base['Mes'].map(PA.mes_str)
    vg = sh.worksheet(D.H_GAB).get_all_values(value_render_option='UNFORMATTED_VALUE')
    gab = pd.DataFrame(vg[1:], columns=vg[0])
    gab = gab[gab['Valor'].astype(str).str.strip().ne('')].copy()
    gab['Valor'] = pd.to_numeric(gab['Valor'], errors='coerce').fillna(0)
    gab = gab[gab['Valor'] != 0]
    gab['Mes'] = gab['Mes'].map(PA.mes_str)
    gab['Canal'] = gab['Canal'].astype(str).str.strip().replace({'Mercado Libre 2': 'Mercado Libre'})
    gab['cc'] = gab['Centro de costo'].astype(str).str.strip().str.capitalize().replace({'Comisión envio': 'Comisión envío'})
    gab = gab[gab['cc'].isin(D.CC_GABRIELA)]             # mismo filtro que la base (D.gab_df)
    gab['Glosa'] = gab['Glosa'].astype(str).str.strip()
    try:
        vp = sh.worksheet(PA.H_PLAN).get_all_values()
        plan = pd.DataFrame(vp[1:], columns=vp[0])
        plan = plan[plan['ID'].astype(str).str.strip().str.fullmatch(r'[A-Z]{2,4}-\d+')]
    except Exception:
        plan = pd.DataFrame()
    return sh, base, gab, plan


def comerciales(sh, base, gab) -> pd.DataFrame:
    """Costos comerciales con la misma regla de la planilla (D.combinar): carga de Gabriela o lectura de sus
    liquidaciones (pestaña 2b), la más completa por canal × mes × centro. Columnas como gab (cc, Valor costo +)."""
    canales = base.loc[base['Fuente'] == 'RAW ventas', 'Canal'].unique()
    g = gab.copy()
    g['Canal'] = D.canonizar(g['Canal'], canales)
    g['Centro de costo'] = g['cc']
    g['Fuente'] = 'Gabriela'
    try:
        vl = sh.worksheet(D.H_LIQ).get_all_values(value_render_option='UNFORMATTED_VALUE')
        liq = pd.DataFrame(vl[1:], columns=vl[0])
        liq['Valor'] = pd.to_numeric(liq['Valor'], errors='coerce').fillna(0)
        liq['Mes'] = liq['Mes'].map(PA.mes_str)
        liq['Canal'] = D.canonizar(liq['Canal'], canales)
        liq['Glosa'] = liq['Glosa'].astype(str).str.strip()
    except Exception:
        liq = None
    c = D.combinar(g, liq)
    c['cc'] = c['Centro de costo']
    return c


ESTADO_HOJA = '_estado reporte'


def estado_leer(sh) -> str:
    """Último mes cuyo reporte de CIERRE ya se envió (pestaña oculta de la planilla)."""
    try:
        v = sh.worksheet(ESTADO_HOJA).acell('B1').value
        return PA.mes_str(v) if v else ''
    except Exception:
        return ''


def estado_guardar(sh, mes: str):
    try:
        ws = sh.worksheet(ESTADO_HOJA)
    except Exception:
        ws = sh.add_worksheet(title=ESTADO_HOJA, rows=5, cols=3)
        sh.batch_update({'requests': [{'updateSheetProperties': {'properties': {'sheetId': ws.id, 'hidden': True}, 'fields': 'hidden'}}]})
    ws.update([['Último cierre reportado', mes, dt.date.today().isoformat()]], range_name='A1', value_input_option='RAW')


def drive_carpeta():
    """Árbol de la carpeta de liquidaciones: {canal: {mes_num: [archivos]}}."""
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    env = os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '').strip()
    creds = (Credentials.from_authorized_user_info(json.loads(env)) if env
             else Credentials.from_authorized_user_file(str(ROOT / 'drive_oauth_token.json')))
    if not creds.valid:
        creds.refresh(Request())
    d = build('drive', 'v3', credentials=creds)

    def hijos(fid):
        out, tok = [], None
        while True:
            r = d.files().list(q=f"'{fid}' in parents and trashed=false", pageToken=tok, pageSize=200,
                               fields='nextPageToken,files(id,name,mimeType,modifiedTime)',
                               supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            out += r['files']
            tok = r.get('nextPageToken')
            if not tok:
                return out

    arbol = {}
    for c in hijos(CARPETA_LIQ):
        if not c['mimeType'].endswith('folder'):
            continue
        for m in hijos(c['id']):
            if not m['mimeType'].endswith('folder'):
                continue
            mes = mes_carpeta(m['name'])
            if mes:
                grupos = [(m, mes, '')]
            else:
                # carpeta por proveedor con los meses adentro (MELI/ENVIAME/AGOSTO, PAGINAS/SHOPIFY/JULIO; 7-oct)
                grupos = [(x, mes_carpeta(x['name']), m['name'] + '/') for x in hijos(m['id'])
                          if x['mimeType'].endswith('folder') and mes_carpeta(x['name'])]
            for carpeta, mes, pref in grupos:
                files = []
                pila = [carpeta]
                while pila:
                    x = pila.pop()
                    for f in hijos(x['id']):
                        (pila.append(f) if f['mimeType'].endswith('folder') else files.append((f, pref + x['name'])))
                arbol.setdefault(c['name'], {}).setdefault(mes, []).extend(files)
    return d, arbol


def bajar_mes(drv, arbol, mes_num, destino: Path):
    """Descarga los archivos del mes a una carpeta con la estructura que lee rentabilidad_liquidaciones."""
    from googleapiclient.http import MediaIoBaseDownload
    for canal, meses in arbol.items():
        for f, sub in meses.get(mes_num, []):
            p = destino / canal / sub / f['name']
            p.parent.mkdir(parents=True, exist_ok=True)
            if f['mimeType'] == 'application/vnd.google-apps.spreadsheet':
                req = drv.files().export_media(fileId=f['id'], mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                if not p.name.endswith('.xlsx'):
                    p = p.with_name(p.name + '.xlsx')
            else:
                req = drv.files().get_media(fileId=f['id'], supportsAllDrives=True)
            b = io.BytesIO()
            dl = MediaIoBaseDownload(b, req)
            done = False
            while not done:
                _, done = dl.next_chunk()
            p.write_bytes(b.getvalue())


# ───────────────────────── métricas ─────────────────────────
def metricas(base, gab):
    # Mes de cierre = último mes con los cinco marketplaces CARGADOS (costo comercial ≥ 10% del ingreso,
    # sea de la carga de Gabriela o de la lectura de sus liquidaciones). Uno a medio cargar no se compara:
    # se informa como "carga en curso".
    raw = base[base['Fuente'] == 'RAW ventas']
    ING = raw[raw['Centro de costo'] == 'Ingreso venta'].groupby(['Canal', 'Mes'])['Monto'].sum()
    costo = gab.groupby(['Canal', 'Mes'])['Valor'].sum()
    cargado = lambda c, m: ING.get((c, m), 0) > 0 and costo.get((c, m), 0) / ING.get((c, m), 0) >= 0.10  # noqa: E731
    meses = sorted(gab['Mes'].unique())
    por_mes = {m: {c for c in MK if cargado(c, m)} for m in meses}
    completos = [m for m in meses if set(MK) <= por_mes[m]]
    M1 = completos[-1] if completos else meses[-1]
    M0 = completos[-2] if len(completos) > 1 else None
    en_curso = {m: sorted(cs) for m, cs in por_mes.items() if m > M1}
    ING_MOD = raw[raw['Centro de costo'] == 'Ingreso venta'].groupby(['Canal', 'Modalidad', 'Mes'])['Monto'].sum()
    CC = base.groupby(['Canal', 'Mes', 'Centro de costo'])['Monto'].sum()
    # el cierre es de TODOS los canales (Andrés 6-oct), los con venta ≥ $1M en el mes, de mayor a menor venta
    canales = sorted([c for (c, m), v in ING.items() if m == M1 and v >= 1e6], key=lambda c: -ING.get((c, M1), 0))

    def mg(c, m):
        i = ING.get((c, m), 0)
        return float(base[(base['Canal'] == c) & (base['Mes'] == m)]['Monto'].sum()) / i * 100 if i else None

    def mgmod(c, mod, m):
        i = ING_MOD.get((c, mod, m), 0)
        return float(base[(base['Canal'] == c) & (base['Modalidad'] == mod) & (base['Mes'] == m)]['Monto'].sum()) / i * 100 if i else None

    def ccp(c, cc, m):
        i = ING.get((c, m), 0)
        return CC.get((c, m, cc), 0) / i * 100 if i else 0

    g = gab.copy()
    g['Valor'] = -g['Valor']           # costo negativo, abono positivo (para % del ingreso)
    g['k'] = g['Glosa'].str.lower()

    def movers(c):
        if not M0:
            return []
        i0, i1 = ING.get((c, M0), 0), ING.get((c, M1), 0)
        x = g[g['Canal'] == c]
        a = x[x['Mes'] == M1].groupby('k').agg(v=('Valor', 'sum'), glosa=('Glosa', 'first'))
        b = x[x['Mes'] == M0].groupby('k').agg(v=('Valor', 'sum'), glosa=('Glosa', 'first'))
        z = a.join(b, how='outer', lsuffix='1', rsuffix='0').fillna({'v1': 0, 'v0': 0})
        z['glosa'] = z['glosa1'].fillna(z['glosa0'])
        z['d'] = (z['v1'] / i1 * 100 if i1 else 0) - (z['v0'] / i0 * 100 if i0 else 0)
        z = z[z['d'].abs() >= 0.3].sort_values('d', key=lambda s: -s.abs())
        return [(r.glosa, float(r.d)) for r in z.head(7).itertuples()]

    return dict(M0=M0, M1=M1, ING=ING, ING_MOD=ING_MOD, canales=canales, mg=mg, mgmod=mgmod, ccp=ccp, movers=movers, en_curso=en_curso)


def alertas_plan(plan: pd.DataFrame, hoy: dt.date):
    """Presión semanal: qué acciones no tienen dueño, fecha, gestión, o están vencidas/rojas."""
    out = []
    gcol = PA.columnas(plan.columns)['gestion_cur'] or ''
    gmes = PA.mes_de_col(gcol) if gcol else None
    for _, r in plan.iterrows():
        est = str(r.get('Estado', '')).strip().lower()
        if est in ('cerrada', 'cerrado', 'descartada', 'hecha'):
            continue
        falta = []
        if not str(r.get('Fecha compromiso', '')).strip():
            falta.append('sin fecha compromiso')
        else:
            try:
                f = pd.to_datetime(str(r['Fecha compromiso']), dayfirst=True).date()
                if f < hoy:
                    falta.append(f'vencida ({f.strftime("%d-%m")})')
            except Exception:
                pass
        if not str(r.get(gcol, '')).strip():
            falta.append(f'sin gestión de {nom(gmes).lower()}' if gmes else 'sin gestión registrada')
        if str(r.get('Semáforo', '')).startswith('🔴'):
            falta.append('semáforo rojo')
        if falta:
            out.append((r['ID'], r.get('Canal', ''), r.get('Acción', ''), r.get('Responsable', ''), ', '.join(falta)))
    return out


# ───────────────────────── diseño (estándar App Finanzas + guía "MD Gráficos") ─────────────────────────
# Un color de énfasis + grises, títulos que afirman la conclusión, cifras es-CL tabulares,
# grilla punteada tenue, etiquetas directas. El dashboard (adjunto) es HTML con ECharts; el
# correo es HTML "email-safe" (tablas con estilos en línea) con los gráficos como PNG
# incrustados, porque Gmail no ejecuta JS ni muestra SVG.
NAVY, BLUE, INK, MUTE, RULE, GRAY, GRAY2 = '#1F3864', '#2E75B6', '#1E293B', '#64748B', '#E2E8F0', '#B9C6CF', '#8FA3B0'
GOOD, BAD, AMBER, BG = '#0E7A54', '#B42318', '#B45309', '#EEF1F4'
NEG_BAR, POS_BAR = '#9B3A2F', '#0E7A54'
SERIF = "Georgia,'Times New Roman',serif"
SANS = "system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif"
MONO = "ui-monospace,'Cascadia Mono',Consolas,'DejaVu Sans Mono',monospace"


def _ax_cat(cats, rotate=0):
    return {'type': 'category', 'data': cats, 'axisTick': {'show': False}, 'axisLine': {'lineStyle': {'color': RULE}},
            'axisLabel': {'color': MUTE, 'fontFamily': SANS, 'fontSize': 11, 'interval': 0, 'rotate': rotate, 'lineHeight': 14}}


def _ax_val(nombre=None, fmt='@@NUM@@'):
    return {'type': 'value', 'name': nombre, 'nameTextStyle': {'color': MUTE, 'fontSize': 10, 'fontFamily': MONO, 'align': 'left', 'padding': [0, 0, 0, -8]},
            'axisLine': {'show': False}, 'axisTick': {'show': False},
            'axisLabel': {'color': MUTE, 'fontFamily': MONO, 'fontSize': 10, 'formatter': fmt},
            'splitLine': {'lineStyle': {'color': RULE, 'type': 'dashed'}}}


def _lab(t, pos='top', color=INK, bold=False, size=10.5):
    return {'show': True, 'position': pos, 'formatter': t, 'color': color, 'fontWeight': 'bold' if bold else 'normal', 'fontSize': size, 'fontFamily': MONO}


TIP = {'trigger': 'item', 'formatter': '@@TIP@@', 'backgroundColor': '#fff', 'borderColor': RULE, 'textStyle': {'color': INK, 'fontSize': 12, 'fontFamily': SANS}}


def opt_mancuerna(filas, l0, l1):
    """filas: [(canal, m0, m1)] ordenadas. Punto gris hueco = mes anterior, punto sólido = mes actual
    (verde si sube, rojo si baja). La distancia es la variación: se lee sin restar."""
    filas = list(reversed(filas))
    cats = [f[0] for f in filas]
    series = []
    for i, (c, a, b) in enumerate(filas):
        if a is None:
            continue
        series.append({'type': 'line', 'data': [[a, i], [b, i]], 'symbol': 'none', 'lineStyle': {'color': GRAY, 'width': 3},
                       'silent': True, 'z': 1, 'tooltip': {'show': False}})
    def lab(pos, color, bold, size):
        return {'show': True, 'position': pos, 'distance': 9, 'formatter': '@@X@@', 'color': color,
                'fontFamily': MONO, 'fontSize': size, 'fontWeight': 'bold' if bold else 'normal'}
    # cada etiqueta va del lado opuesto al otro punto: no se tapan aunque estén cerca
    series.append({'name': l0, 'type': 'scatter', 'symbolSize': 11, 'z': 3,
                   'itemStyle': {'color': '#fff', 'borderColor': GRAY2, 'borderWidth': 2},
                   'data': [{'value': [a, i], 'tip': f'{c} · {l0}: {n(a)}%', 'label': lab('left' if a <= b else 'right', MUTE, False, 10)}
                            for i, (c, a, b) in enumerate(filas) if a is not None]})
    series.append({'name': l1, 'type': 'scatter', 'symbolSize': 13, 'z': 4,
                   'data': [{'value': [b, i], 'tip': f'{c} · {l1}: {n(b)}%' + (f' ({pp(b - a)} p.p.)' if a is not None else ''),
                             'itemStyle': {'color': (GOOD if b >= a else BAD) if a is not None else BLUE},
                             'label': lab('right' if (a is None or b >= a) else 'left', INK, True, 11)}
                            for i, (c, a, b) in enumerate(filas)]})
    vals = [v for f in filas for v in f[1:] if v is not None]
    lo, hi = min(vals + [0]), max(vals)
    return {'tooltip': TIP, 'animation': False,
            'grid': {'left': 8, 'right': 40, 'top': 12, 'bottom': 8, 'containLabel': True},
            'xAxis': {**_ax_val(None, '@@PCT@@'), 'min': (int(lo // 5) - 1) * 5, 'max': (int(hi // 5) + 1) * 5, 'interval': 5},
            'yAxis': {'type': 'category', 'data': cats, 'axisTick': {'show': False}, 'axisLine': {'show': False},
                      'axisLabel': {'color': INK, 'fontFamily': SANS, 'fontSize': 12}},
            'series': series}


def opt_cascada(steps):
    cats, bases, alts, tops, cum = [], [], [], [], 0.0
    for lab, v, kind in steps:
        cats.append(lab.replace(' ', '\n', 1) if kind == 'dec' else lab)
        if kind == 'start':
            b, h, disp, color, cum = min(0, v), abs(v), v, NAVY, v
        elif kind == 'total':
            b, h, disp, color = min(0, cum), abs(cum), cum, BLUE
        else:
            nx = cum + v
            b, h, disp, color, cum = min(cum, nx), abs(v), v, (POS_BAR if v > 0 else NEG_BAR), nx
        bases.append(round(b, 3))
        alts.append({'value': round(h, 3), 'tip': f'{lab}: {pp(disp) if kind == "dec" else n(disp) + "%"}', 'itemStyle': {'color': color}, 'label': {'show': False}})
        tops.append({'value': round(b + h, 3), 'tip': None, 'label': _lab(pp(disp) if kind == 'dec' else n(disp) + '%', 'top', INK if kind != 'dec' else MUTE, kind != 'dec')})
    techo = max([t['value'] for t in tops] + [0])
    piso = min(bases + [0])
    return {'tooltip': TIP, 'animation': False, 'grid': {'left': 12, 'right': 8, 'top': 30, 'bottom': 4, 'containLabel': True},
            'xAxis': _ax_cat(cats), 'yAxis': {**_ax_val('p.p. del ingreso'), 'boundaryGap': ['6%', '16%'], 'splitNumber': 5},
            # stackStrategy 'all': sin esto ECharts apila los negativos aparte y la cascada que
            # cruza el cero se dibuja mal (base −6 + alto 9,5 debe ir de −6 a 3,5)
            'series': [{'type': 'bar', 'stack': 'w', 'stackStrategy': 'all', 'data': bases, 'itemStyle': {'color': 'transparent'}, 'emphasis': {'disabled': True}, 'tooltip': {'show': False}, 'barWidth': '58%'},
                       {'type': 'bar', 'stack': 'w', 'stackStrategy': 'all', 'data': alts, 'barWidth': '58%'},
                       {'type': 'bar', 'data': tops, 'barGap': '-100%', 'barWidth': '58%', 'itemStyle': {'color': 'transparent'}, 'emphasis': {'disabled': True}, 'tooltip': {'show': False}}]}


def opt_glosas(items):
    items = sorted(items, key=lambda t: abs(t[1]))
    data = [{'value': round(v, 2), 'tip': f'{g}: {pp(v)} p.p.', 'itemStyle': {'color': POS_BAR if v > 0 else NEG_BAR},
             'label': _lab(pp(v), 'right' if v > 0 else 'left', INK, False, 10.5)} for g, v in items]
    m = max(abs(v) for _, v in items) if items else 1
    return {'tooltip': TIP, 'animation': False, 'grid': {'left': 8, 'right': 44, 'top': 8, 'bottom': 4, 'containLabel': True},
            'xAxis': {**_ax_val(None), 'min': -m * 1.7, 'max': m * 1.7, 'splitNumber': 4,
                      'axisLabel': {**_ax_val()['axisLabel'], 'showMinLabel': False, 'showMaxLabel': False}},
            'yAxis': {'type': 'category', 'data': [(g[:34] + '…') if len(g) > 35 else g for g, _ in items], 'axisTick': {'show': False}, 'axisLine': {'show': False},
                      'axisLabel': {'color': INK, 'fontFamily': SANS, 'fontSize': 11, 'margin': 14}},
            'series': [{'type': 'bar', 'data': data, 'barMaxWidth': 16}]}


JS_FUN = {
    '"@@NUM@@"': "function(v){return fmtNum(v);}",
    '"@@X@@"': "function(p){return fmtNum(p.value[0])+'%';}",
    '"@@PCT@@"': "function(v){return fmtNum(v)+'%';}",
    '"@@TIP@@"': "function(p){return (p.data&&p.data.tip)?p.data.tip:(p.name||'');}",
}


def _js(opts):
    s = json.dumps(opts, ensure_ascii=False)
    for k, v in JS_FUN.items():
        s = s.replace(k, v)
    return s


def opt_modalidad(mods, v0, v1, l0, l1):
    def serie(nm, vals, color, enf):
        return {'name': nm, 'type': 'bar', 'barMaxWidth': 34, 'itemStyle': {'color': color},
                'data': [{'value': (round(v, 2) if v is not None else None), 'tip': f'{nm}: {n(v)}%' if v is not None else 'sin venta',
                          'label': _lab(n(v) + '%' if v is not None else '', 'top', INK if enf else MUTE, enf, 10.5)} for v in vals]}
    return {'tooltip': TIP, 'animation': False,
            'legend': {'top': 0, 'right': 0, 'itemWidth': 10, 'itemHeight': 10, 'icon': 'rect', 'textStyle': {'color': MUTE, 'fontSize': 11, 'fontFamily': MONO}},
            'grid': {'left': 12, 'right': 8, 'top': 32, 'bottom': 4, 'containLabel': True}, 'xAxis': _ax_cat(mods),
            'yAxis': {**_ax_val('% margen', '@@PCT@@'), 'boundaryGap': ['6%', '16%']},
            'series': ([serie(l0, v0, GRAY, False)] if v0 else []) + [serie(l1, v1, BLUE, True)]}


# ───────────────────────── detalle explicativo por canal ─────────────────────────
CENTROS = [('Costo venta', 'Costo de venta'), ('Devolución', 'Devolución'), ('Comisión venta', 'Comisión de venta'),
           ('Comisión envío', 'Comisión de envío'), ('Marketing', 'Marketing')]


def detalle_canal(c, X, base, gab, M0, M1):
    ING = X['ING']
    i0, i1 = ING.get((c, M0), 0) if M0 else 0, ING.get((c, M1), 0)
    CC = base[base['Canal'] == c].groupby(['Mes', 'Centro de costo'])['Monto'].sum()
    centros = []
    for cc, lab in CENTROS:
        a0, a1 = (CC.get((M0, cc), 0) if M0 else 0), CC.get((M1, cc), 0)
        p0, p1 = (a0 / i0 * 100 if i0 else None), (a1 / i1 * 100 if i1 else None)
        # efecto en el margen de agosto = Δ p.p. × ingreso de agosto (el "cuánto vale" del cambio)
        efecto = ((p1 - p0) / 100 * i1) if (p0 is not None and p1 is not None) else None
        centros.append(dict(centro=lab, cc=cc, a0=a0, a1=a1, p0=p0, p1=p1, d=(p1 - p0) if p0 is not None else None, efecto=efecto))
    g = gab[gab['Canal'] == c].copy()
    g['k'] = g['Glosa'].str.lower()
    A = g[g['Mes'] == M1].groupby('k').agg(v1=('Valor', 'sum'), glosa=('Glosa', 'first'), cc=('cc', 'first'))
    Bq = g[g['Mes'] == M0].groupby('k').agg(v0=('Valor', 'sum'), glosa0=('Glosa', 'first'), cc0=('cc', 'first')) if M0 else pd.DataFrame(columns=['v0', 'glosa0', 'cc0'])
    z = A.join(Bq, how='outer').fillna({'v1': 0, 'v0': 0})
    z['glosa'] = z['glosa'].fillna(z['glosa0'])
    z['cc'] = z['cc'].fillna(z['cc0'])
    # Valor de Gabriela: costo positivo. En % del ingreso con signo del margen (costo = negativo)
    z['p0'] = -z['v0'] / i0 * 100 if i0 else 0
    z['p1'] = -z['v1'] / i1 * 100 if i1 else 0
    z['d'] = z['p1'] - z['p0']
    z['estado'] = ['nueva' if a == 0 and b != 0 else ('desaparece' if b == 0 and a != 0 else '') for a, b in zip(z['v0'], z['v1'])]
    z = z.sort_values('d', key=lambda s: -s.abs())
    glosas = [dict(glosa=r.glosa, cc=r.cc, v0=r.v0, v1=r.v1, p0=r.p0, p1=r.p1, d=r.d, estado=r.estado) for r in z.itertuples() if abs(r.d) >= 0.1][:10]
    mods = []
    for mod in ['Colecta', 'Envío directo', 'Fulfillment']:
        s1 = X['ING_MOD'].get((c, mod, M1), 0)
        if i1 and s1 / i1 >= 0.05:
            mods.append(dict(mod=mod, share=s1 / i1 * 100, m0=X['mgmod'](c, mod, M0) if M0 else None, m1=X['mgmod'](c, mod, M1)))
    mg0, mg1 = X['mg'](c, M0) if M0 else None, X['mg'](c, M1)
    d = (mg1 - mg0) if mg0 is not None else 0
    # narrativa: los centros que más mueven, cada uno con su glosa principal
    partes = []
    for ce in sorted([x for x in centros if x['d'] is not None], key=lambda x: -abs(x['d']))[:3]:
        if abs(ce['d']) < 0.5:
            continue
        gl = [x for x in glosas if x['cc'] == ce['cc']]
        txt = f"{ce['centro'].lower()} {pp(ce['d'])} p.p. ({'+' if ce['efecto'] > 0 else '−'}{mm(abs(ce['efecto']))} de margen)"
        if gl:
            x = gl[0]
            txt += (f", sobre todo por \"{x['glosa']}\"" + (' (glosa nueva este mes' if x['estado'] == 'nueva' else ' (desaparece este mes' if x['estado'] == 'desaparece' else ' (')
                    + f"{'' if x['estado'] == '' else ', '}{mm(x['v1'])} en {nom(M1).lower()} vs {mm(x['v0'])} en {nom(M0).lower()})")
        elif ce['cc'] == 'Devolución':
            txt += (': la devolución se registra en el mes de la nota de crédito, así que parte de la mejora puede ser solo que aún no se emiten las notas del mes'
                    if ce['d'] > 0 else ': la devolución se registra en el mes de la nota de crédito y puede incluir ventas de meses anteriores')
        partes.append(txt)
    efecto_total = d / 100 * i1
    if mg0 is None:
        narrativa = f'{c} deja {n(mg1)}% en {nom(M1).lower()}.'
    elif abs(d) < 0.5:
        narrativa = f'{c} se mantiene: {n(mg0)}% → {n(mg1)}%.'
    else:
        narrativa = (f"El margen de {c} pasó de {n(mg0)}% a {n(mg1)}% ({pp(d)} p.p.). A la venta de {nom(M1).lower()} ({mm(i1)}) "
                     f"eso equivale a {'+' if efecto_total > 0 else '−'}{mm(abs(efecto_total))} de margen. Lo explican: " + '; '.join(partes) + '.')
    if len(mods) >= 2:
        best = max(mods, key=lambda m: m['m1'] if m['m1'] is not None else -1e9)
        worst = min(mods, key=lambda m: m['m1'] if m['m1'] is not None else 1e9)
        narr_mod = (f"Por modalidad, {best['mod']} es la que más deja ({n(best['m1'])}%, {n(best['share'], 0)}% de la venta) y "
                    f"{worst['mod']} la que menos ({n(worst['m1'])}%, {n(worst['share'], 0)}% de la venta).")
    else:
        narr_mod = ''
    return dict(canal=c, i0=i0, i1=i1, mg0=mg0, mg1=mg1, d=d, efecto=efecto_total, centros=centros, glosas=glosas, mods=mods,
                narrativa=narrativa, narr_mod=narr_mod)


def _tabla(heads, rows, aligns, cls='t'):
    th = ''.join(f'<th style="text-align:{a}">{h}</th>' for h, a in zip(heads, aligns))
    tr = ''.join('<tr>' + ''.join(f'<td style="text-align:{a}">{v}</td>' for v, a in zip(r, aligns)) + '</tr>' for r in rows)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def _chip(t, tono):
    return f'<span class="chip {tono}">{H.escape(t)}</span>'


def _signo(v, d=1, suf=''):
    if v is None:
        return '—'
    c = 'pos' if v > 0.05 else 'neg' if v < -0.05 else 'neu'
    return f'<span class="{c}" style="white-space:nowrap">{pp(v, d)}{suf}</span>'


def dashboard_html(ctx):
    """Dashboard explicativo (adjunto del correo)."""
    opts = {}
    kp = ''.join(f"""<div class="kpi"><div class="eyebrow">{H.escape(t['label'])}</div><div class="kv">{t['valor']}<span class="ku">{t.get('unidad', '')}</span></div>
<div class="kd" style="color:{t.get('color', MUTE)}">{t['meta']}</div><div class="kx">{t.get('expl', '')}</div></div>""" for t in ctx['kpis'])
    opts['c_mancuerna'] = opt_mancuerna(ctx['mancuerna'], ctx['l0'], ctx['l1'])
    l0, l1 = ctx['l0'], ctx['l1']
    res_rows = [[f'<b>{H.escape(r["canal"])}</b>', mm(r['i1']), (n(r['mg0']) + '%') if r['mg0'] is not None else '—', f'<b>{n(r["mg1"])}%</b>',
                 _signo(r['d'], suf=' p.p.'), ('+' if r['efecto'] > 0 else '−') + mm(abs(r['efecto']))] for r in ctx['detalle']]
    resumen_tab = _tabla(['Canal', f'Ingreso {l1[:3].lower()}', f'Margen {l0[:3].lower()}', f'Margen {l1[:3].lower()}', 'Δ', f'Efecto en margen {l1[:3].lower()}'],
                         res_rows, ['left', 'right', 'right', 'right', 'right', 'right'])
    canales = ''
    for i, dc in enumerate(ctx['detalle']):
        steps = [(f'Margen {l0[:3].lower()}', dc['mg0'] or 0, 'start')] + [(ce['centro'].replace('Comisión de ', 'Comisión '), ce['d'] or 0, 'dec') for ce in dc['centros']]
        otros = (dc['d'] or 0) - sum((ce['d'] or 0) for ce in dc['centros'])
        if abs(otros) >= 0.05:
            steps.append(('Otros', otros, 'dec'))
        steps.append((f'Margen {l1[:3].lower()}', 0, 'total'))
        opts[f'c_casc{i}'] = opt_cascada(steps)
        gl = [(x['glosa'], x['d']) for x in dc['glosas'][:7]]
        if gl:
            opts[f'c_glo{i}'] = opt_glosas(gl)
        if len(dc['mods']) >= 2:
            opts[f'c_mod{i}'] = opt_modalidad([m['mod'] for m in dc['mods']], [m['m0'] for m in dc['mods']] if dc['mg0'] is not None else None,
                                              [m['m1'] for m in dc['mods']], l0, l1)
        cen_rows = [[ce['centro'], (n(ce['p0']) + '%') if ce['p0'] is not None else '—', (n(ce['p1']) + '%') if ce['p1'] is not None else '—',
                     _signo(ce['d'], suf=' p.p.'), (('+' if ce['efecto'] > 0 else '−') + mm(abs(ce['efecto']))) if ce['efecto'] is not None else '—']
                    for ce in dc['centros']]
        gl_rows = [[H.escape(x['glosa']) + (' ' + _chip(x['estado'], 'bad' if x['estado'] == 'nueva' else 'neu') if x['estado'] else ''), H.escape(str(x['cc'])),
                    mm(x['v0']), mm(x['v1']), f"{n(x['p0'])}%", f"{n(x['p1'])}%", _signo(x['d'], suf=' p.p.')] for x in dc['glosas']]
        mod_rows = [[m['mod'], f"{n(m['share'], 0)}%", (n(m['m0']) + '%') if m['m0'] is not None else '—', f"<b>{n(m['m1'])}%</b>",
                     _signo((m['m1'] - m['m0']) if m['m0'] is not None else None, suf=' p.p.')] for m in dc['mods']]
        canales += f"""<section class="panel" id="canal{i}"><div class="eyebrow">{H.escape(dc['canal'])} · {l0} → {l1}</div>
<h3>{H.escape(ctx['titulos'][i])}</h3>
<div class="qp"><div class="qp-t">Qué pasó</div><p>{H.escape(dc['narrativa'])}</p>{f'<p>{H.escape(dc["narr_mod"])}</p>' if dc['narr_mod'] else ''}</div>
<div class="two"><div><div class="mini">De dónde sale la variación del margen</div>
<div class="how">Parte del margen de {l0.lower()} (azul oscuro). Cada barra es cuánto sumó (verde) o restó (rojo) cada centro de costo, en puntos del ingreso. Termina en el margen de {l1.lower()} (azul).</div>
<div class="chart" id="c_casc{i}" style="height:270px"></div></div>
<div><div class="mini">Las glosas que más se movieron</div>
<div class="how">Cambio de cada glosa como % del ingreso entre los dos meses. Rojo = ese cargo pesa más (resta margen); verde = pesa menos o es un abono.</div>
{f'<div class="chart" id="c_glo{i}" style="height:270px"></div>' if gl else '<p class="lead">Ninguna glosa se movió más de 0,1 p.p.</p>'}</div></div>
<div class="two"><div><div class="mini">Por centro de costo · % del ingreso</div>{_tabla(['Centro', l0[:3], l1[:3], 'Δ', f'Efecto $ {l1[:3].lower()}'], cen_rows, ['left', 'right', 'right', 'right', 'right'])}</div>
<div>{f'<div class="mini">Por modalidad · margen</div><div class="how">Cada modalidad con su propia venta; los cargos sin modalidad se reparten por venta.</div><div class="chart" id="c_mod{i}" style="height:200px"></div>' + _tabla(['Modalidad', 'Share venta', f'Mg {l0[:3].lower()}', f'Mg {l1[:3].lower()}', 'Δ'], mod_rows, ['left', 'right', 'right', 'right', 'right']) if len(dc['mods']) >= 2 else '<div class="mini">Por modalidad</div><p class="lead">Una sola modalidad con más de 5% de la venta.</p>'}</div></div>
<details><summary>Detalle de glosas ({len(dc['glosas'])})</summary>{_tabla(['Glosa', 'Centro', f'$ {l0[:3].lower()}', f'$ {l1[:3].lower()}', f'% {l0[:3].lower()}', f'% {l1[:3].lower()}', 'Δ'], gl_rows, ['left', 'left', 'right', 'right', 'right', 'right', 'right'])}
<p class="nota">$ = monto de la glosa (costo positivo, abono negativo). % = sobre el ingreso del canal, con el signo del margen.</p></details></section>"""
    plan_rows = [[f'<b>{H.escape(r["ID"])}</b>', H.escape(r['Indicador']), H.escape(r['Base']), H.escape(r['Ultimo']), _chip(r['sem_t'], r['sem_c']),
                  H.escape(r['Responsable']), _chip(r['Fecha'], 'neu') if r['Fecha'] else _chip('sin fecha', 'bad'),
                  H.escape(r['Gestion']) if r['Gestion'] else _chip('sin gestión', 'bad')] for r in ctx['plan']]
    comp_rows = [[f'<b>{H.escape(r["ID"])}</b>', H.escape(r['Accion']), H.escape(r['Comprometido']), H.escape(r['Base']), H.escape(r['Ultimo']),
                  _chip(r['sem_t'], r['sem_c'])] for r in ctx['plan'] if r['Comprometido']]
    comp_html = (f"""<div class="mini">Compromisos de {ctx['g_prev']} → resultado en {ctx['lp1'].lower()}</div>
{_tabla(['ID', 'Acción', 'Lo comprometido', ctx['lp0'], ctx['lp1'], 'Resultado'], comp_rows, ['left'] * 3 + ['right'] * 2 + ['left'])}""" if comp_rows else '')
    auto_rows = [[m, f'<b>{c}</b>', d, _chip(f'{k} archivo' + ('s' if k != 1 else ''), 'good') if k else _chip('falta', 'warn'), u or '—'] for m, c, d, k, u in ctx['auto']]
    cuad = ''
    for mstr, filas in ctx['cuadre'].items():
        cuad += f'<div class="mini" style="margin-top:14px">Cuadre {nom(mstr).lower()} · lectura automática vs carga manual (neto)</div>' + _tabla(
            ['Canal', 'Automática', 'Carga manual', 'Estado'], filas, ['left', 'right', 'right', 'left'])
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rentabilidad por canal</title><style>
:root{{--navy:{NAVY};--blue:{BLUE};--ink:{INK};--mute:{MUTE};--rule:{RULE};--bg:{BG};--good:{GOOD};--bad:{BAD};--warn:{AMBER}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:{SANS};font-size:14px}}
.wrap{{max-width:1160px;margin:0 auto;padding:32px 24px 56px;display:flex;flex-direction:column;gap:18px}}
.eyebrow{{font-family:{MONO};font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--mute)}}
h1{{font-family:{SERIF};font-weight:400;font-size:38px;line-height:1.15;margin:6px 0 6px;text-wrap:balance;max-width:900px}} h1 em{{color:var(--blue);font-style:normal}}
.intro{{max-width:720px;color:#334155;font-size:15px;line-height:1.55;margin:0}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);background:#fff;border:1px solid var(--rule)}}
.kpi{{padding:16px 18px;border-right:1px solid var(--rule)}} .kpi:last-child{{border-right:0}}
.kv{{font-family:{MONO};font-size:30px;font-weight:600;margin:8px 0 4px;font-variant-numeric:tabular-nums}} .ku{{font-size:13px;color:var(--mute);margin-left:4px;font-weight:400}}
.kd{{font-family:{MONO};font-size:12px}} .kx{{font-size:12px;color:var(--mute);margin-top:6px;line-height:1.4}}
.panel{{background:#fff;border:1px solid var(--rule);padding:20px 22px}}
.panel h3{{font-family:{SERIF};font-weight:400;font-size:22px;margin:6px 0 10px;text-wrap:balance}} .lead{{color:var(--mute);font-size:13.5px;margin:0 0 8px;max-width:780px;line-height:1.5}}
.qp{{background:#F5F8FC;border-left:3px solid var(--blue);padding:10px 14px;margin:0 0 14px}} .qp-t{{font-family:{MONO};font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--blue);margin-bottom:2px}}
.qp p{{margin:4px 0;line-height:1.55;max-width:900px}}
.mini{{font-family:{MONO};font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink);margin:10px 0 2px;font-weight:600}}
.how{{font-size:12px;color:var(--mute);line-height:1.45;margin:0 0 4px;max-width:520px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:26px}} .chart{{width:100%}}
.scroll{{overflow-x:auto}} table.t{{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}}
table.t th{{font-family:{MONO};font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);border-bottom:2px solid var(--navy);padding:6px 8px;font-weight:600;white-space:nowrap}}
table.t td{{border-bottom:1px solid var(--rule);padding:6px 8px;vertical-align:top}}
.pos{{color:var(--good);font-weight:600}} .neg{{color:var(--bad);font-weight:600}} .neu{{color:var(--mute)}}
.chip{{display:inline-block;padding:1px 8px;border-radius:10px;border:1px solid currentColor;font-family:{MONO};font-size:10.5px;white-space:nowrap}}
.chip.good{{color:var(--good)}} .chip.bad{{color:var(--bad)}} .chip.warn{{color:var(--warn)}} .chip.neu{{color:var(--mute)}}
details{{margin-top:12px}} summary{{cursor:pointer;font-family:{MONO};font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--blue)}}
.nota{{font-size:11.5px;color:var(--mute);margin:6px 0 0}}
.metodo{{font-size:12.5px;color:#334155;line-height:1.55;columns:2;column-gap:28px}} .metodo p{{margin:0 0 8px;break-inside:avoid}}
@media (max-width:860px){{.kpis{{grid-template-columns:1fr 1fr}} .two{{grid-template-columns:1fr}} h1{{font-size:28px}} .metodo{{columns:1}}}}
</style></head><body><div class="wrap">
<div><div class="eyebrow">Rentabilidad por canal · reporte semanal · {H.escape(ctx['fecha'])}</div>
<h1>{ctx['titular']}</h1><p class="intro">{H.escape(ctx['intro'])}</p></div>
<div class="kpis">{kp}</div>
<section class="panel"><div class="eyebrow">Resultado · margen por canal</div><h3>{H.escape(ctx['titulo_mancuerna'])}</h3>
<div class="how">Cada línea es un canal. Punto hueco = margen de {l0.lower()}; punto sólido = {l1.lower()} (verde si sube, rojo si baja). El largo de la línea es cuánto se movió. "Efecto en margen" traduce ese cambio a pesos sobre la venta de {l1.lower()}.</div>
<div class="two"><div class="chart" id="c_mancuerna" style="height:{70 + 46 * len(ctx['mancuerna'])}px"></div><div>{resumen_tab}</div></div></section>
{canales}
<section class="panel"><div class="eyebrow">Seguimiento del plan de acción</div><h3>{H.escape(ctx['titulo_plan'])}</h3>
<div class="how">El indicador de cada mes y el semáforo ({ctx['lp1'].lower()} contra {ctx['lp0'].lower()}) se recalculan todos los días. Responsable, fecha compromiso y la gestión de {ctx['g_cur']} se llenan en la pestaña 8 de la planilla; la de meses anteriores queda en la pestaña 8b.</div>
{comp_html}
{_tabla(['ID', 'Indicador', ctx['lp0'], ctx['lp1'], 'Semáforo', 'Responsable', 'Fecha', 'Gestión de ' + ctx['g_cur']], plan_rows, ['left'] * 2 + ['right'] * 2 + ['left'] * 4)}</section>
<section class="panel"><div class="eyebrow">Estado de la automatización</div><h3>{H.escape(ctx['titulo_auto'])}</h3>
<div class="how">Qué liquidaciones hay en la carpeta de Drive por canal y mes, y si la lectura automática reproduce la carga manual de Gabriela (±2%).</div>
{_tabla(['Mes', 'Carpeta', 'Qué debe estar', 'Estado', 'Última subida'], auto_rows, ['left'] * 5)}{cuad}</section>
<section class="panel"><div class="eyebrow">Cómo se calcula</div><div class="metodo">
<p><b>Margen</b> = ingreso − costo de venta − devolución − comisión de venta − comisión de envío − marketing, como % del ingreso del canal.</p>
<p><b>Ingreso, costo y devolución</b> salen del RAW de ventas (por fecha de venta). La devolución del último mes sigue creciendo hasta cerrar su ventana de 3 meses.</p>
<p><b>Comisiones y marketing</b> salen de las liquidaciones cargadas por Gabriela, clasificadas por glosa según su receta.</p>
<p><b>p.p.</b> = puntos porcentuales del ingreso. <b>Efecto en margen</b> = Δ p.p. × ingreso del último mes: cuánto margen dio o quitó el cambio.</p>
<p><b>Modalidad</b>: los cargos que la liquidación informa por modalidad van a esa modalidad; los que vienen a nivel cuenta se reparten por venta.</p>
<p>Se compara el último mes con carga de los cinco marketplaces; un mes a medio cargar se informa como "en curso".</p></div></section>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/6.1.0/echarts.min.js"></script><script>
function fmtNum(v){{if(v==null||v==='')return '';var a=Math.abs(v);var d=(a<100&&a!==Math.round(a))?1:0;return v.toLocaleString('es-CL',{{minimumFractionDigits:d,maximumFractionDigits:d}});}}
var O={_js(opts)};
Object.keys(O).forEach(function(i){{var e=document.getElementById(i);if(!e)return;var c=echarts.init(e);c.setOption(O[i]);new ResizeObserver(function(){{c.resize();}}).observe(e);}});
window.__listo=true;
</script></body></html>"""


# ───────────────────────── reporte ─────────────────────────
def _mes_tag(m):
    return f' <span style="color:#64748b;font-size:11px">({m})</span>' if m else ''


def construir(hoy=None, cuadrar=True, modo='auto'):
    hoy = hoy or dt.date.today()
    sh, base, gab, plan = cargar()
    com = comerciales(sh, base, gab)       # carga de Gabriela + lectura de liquidaciones (lo que usa la planilla)
    X = metricas(base, com)
    M0, M1, ING = X['M0'], X['M1'], X['ING']
    if modo == 'auto':
        modo = 'cierre' if M1 > estado_leer(sh) else 'seguimiento'
    canales = X['canales']
    l0, l1 = (nom(M0) if M0 else ''), nom(M1)
    det = [detalle_canal(c, X, base, com, M0, M1) for c in canales]
    det.sort(key=lambda d: -abs(d['d']))
    MG = {d['canal']: (d['mg0'], d['mg1']) for d in det}

    def tot(m):
        if not m:
            return None, 0
        i = sum(ING.get((c, m), 0) for c in canales)
        mg_ = float(base[base['Canal'].isin(canales) & (base['Mes'] == m)]['Monto'].sum())
        return (mg_ / i * 100 if i else None), mg_
    t0, c0 = tot(M0)
    t1, c1 = tot(M1)
    caen = [d['canal'] for d in sorted(det, key=lambda d: d['d']) if d['mg0'] is not None and d['d'] <= -1]
    suben = [d['canal'] for d in sorted(det, key=lambda d: -d['d']) if d['mg0'] is not None and d['d'] >= 1]
    titular = ((f'<em>{H.escape(" y ".join(caen))}</em> pierde{"n" if len(caen) > 1 else ""} margen en {l1.lower()}'
                + (f'; {H.escape(" y ".join(suben))} mejora{"n" if len(suben) > 1 else ""}.' if suben else '.')) if caen
               else f'Ningún canal pierde más de 1 punto de margen en {l1.lower()}.')
    intro = (f'{l1} contra {l0.lower()} en todos los canales con venta de $1M o más. Para cada canal: qué pasó con el margen, '
             f'qué centro de costo y qué glosa lo explican, y cómo le fue a cada modalidad. Al final, el plan de acción y el estado de la automatización.')
    alert = alertas_plan(plan, hoy) if len(plan) else []
    rol = PA.columnas(plan.columns) if len(plan) else dict(meses=[], gestion_prev=None, gestion_cur=None)
    (hm1, pm1) = rol['meses'][-1] if rol['meses'] else ('', None)
    (hm0, pm0) = rol['meses'][-2] if len(rol['meses']) > 1 else ('', None)
    lp1 = nom(pm1)[:3] if pm1 else 'Último'
    lp0 = nom(pm0)[:3] if pm0 else 'Anterior'
    con_gestion = sum(1 for _, r in plan.iterrows() if str(r.get(rol['gestion_cur'] or '', '')).strip())
    g_cur = nom(PA.mes_de_col(rol['gestion_cur'])).lower() if rol['gestion_cur'] and PA.mes_de_col(rol['gestion_cur']) else 'del mes'
    g_prev = nom(PA.mes_de_col(rol['gestion_prev'])).lower() if rol['gestion_prev'] else ''
    comprom = [r for _, r in plan.iterrows() if rol['gestion_prev'] and str(r.get(rol['gestion_prev'], '')).strip()]
    auto_rows, cuadre = [], {}
    try:
        drv, arbol = drive_carpeta()
        meses_rev = sorted({int(M1[5:7])} | {int(m[5:7]) for m in X['en_curso']} | {(hoy.replace(day=1) - dt.timedelta(days=1)).month})
        for mes in meses_rev:
            for canal, desc in ESPERADO.items():
                fs = arbol.get(canal, {}).get(mes, [])
                auto_rows.append((MESES_ES[mes], canal, desc, len(fs), max((f['modifiedTime'][:10] for f, _ in fs), default='')))
        if cuadrar:
            import rentabilidad_liquidaciones as RL
            for mstr in [M1] + sorted(X['en_curso']):
                mes = int(mstr[5:7])
                if not any(arbol.get(c, {}).get(mes) for c in ESPERADO):
                    continue
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
                    bajar_mes(drv, arbol, mes, Path(td))
                    liq = RL.leer_carpeta(Path(td))
                a = liq[liq['canal'].isin(MK)].groupby('canal')['monto_neto'].sum()
                b = gab[(gab['Mes'] == mstr) & gab['Canal'].isin(MK)].groupby('Canal')['Valor'].sum()
                q = pd.DataFrame({'agente': a, 'carga': b}).fillna(0)
                q['dif'] = q['agente'] - q['carga']
                cuadre[mstr] = q.reindex(MK).fillna(0)
    except Exception as e:
        print(f'   [WARN] automatización: {type(e).__name__}: {e}')
    qm = cuadre.get(M1)
    cuadran = int(((qm['dif'].abs() <= qm['carga'].abs() * 0.02) & (qm['carga'] != 0)).sum()) if qm is not None else 0
    faltan = sum(1 for r in auto_rows if not r[3])

    def estado_cuadre(r):
        if r.carga and r.agente and abs(r.dif) <= abs(r.carga) * 0.02:
            return 'cuadra', 'good'
        if not r.agente:
            return 'sin archivo', 'warn'
        if not r.carga:
            return 'sin carga', 'warn'
        return f'dif. {mm(r.dif)}', 'bad'

    kpis = [
        {'label': f'Margen total · {l1}', 'valor': n(t1) if t1 is not None else '—', 'unidad': '%',
         'meta': f'{"▲" if t1 >= t0 else "▼"} {pp(t1 - t0)} p.p. vs {l0.lower()}' if t0 is not None else '', 'color': GOOD if t0 is not None and t1 >= t0 else BAD,
         'expl': 'Margen de todos los canales con venta de $1M o más en el mes, sobre su ingreso total.'},
        {'label': f'Margen en pesos · {l1}', 'valor': n(c1 / 1e6, 1), 'unidad': 'M CLP',
         'meta': f'{"▲" if c1 >= c0 else "▼"} {pp((c1 - c0) / 1e6)} M vs {l0.lower()}' if M0 else '', 'color': GOOD if c1 >= c0 else BAD,
         'expl': 'Parte del cambio es venta: el ingreso de los canales también cambió.'},
        {'label': 'Plan de acción con gestión', 'valor': f'{con_gestion}/{len(plan)}', 'unidad': 'acciones',
         'meta': f'{len(alert)} requieren gestión', 'color': BAD if con_gestion == 0 else AMBER if alert else GOOD,
         'expl': 'Acciones con responsable trabajando y gestión registrada en la planilla.'},
        {'label': f'Lectura automática · {l1}', 'valor': f'{cuadran}/5', 'unidad': 'canales',
         'meta': 'cuadran con la carga manual (±2%)', 'color': GOOD if cuadran == 5 else AMBER,
         'expl': 'Las diferencias son documentos que aún no están en la carpeta (Envíame, marketing, factura Ripley).'},
    ]
    titulos = []
    for dc in det:
        ce = max([x for x in dc['centros'] if x['d'] is not None] or [dict(centro='', d=0)], key=lambda x: abs(x['d']))
        titulos.append(f"{dc['canal']} {'sube' if dc['d'] > 0.5 else 'baja' if dc['d'] < -0.5 else 'se mantiene'} {n(abs(dc['d']))} p.p.; "
                       f"lo que más pesa es {ce['centro'].lower()} ({pp(ce['d'])} p.p.)" if abs(dc['d']) > 0.5 else f"{dc['canal']} se mantiene en {n(dc['mg1'])}%")
    peor, mejor = min(det, key=lambda d: d['d']), max(det, key=lambda d: d['d'])
    titulo_m = f"{peor['canal']} cae {n(abs(peor['d']))} p.p. y {mejor['canal']} sube {n(mejor['d'])} p.p." if M0 else f'Margen por canal en {l1.lower()}'
    plan_ctx = []
    for _, r in plan.iterrows():
        sem = str(r.get('Semáforo', ''))
        plan_ctx.append({'ID': str(r['ID']), 'Indicador': str(r.get('Indicador', '')), 'Accion': str(r.get('Acción', '')),
                         'Base': str(r.get(hm0, '')), 'Ultimo': str(r.get(hm1, '')), 'Mes': '',
                         'Resultado': str(r.get('Resultado del mes', '')),
                         'Comprometido': str(r.get(rol['gestion_prev'] or '', '')).strip(),
                         'Prio': str(r.get('Prioridad (share de venta)', '')).strip(),
                         'sem_t': sem[2:].strip() or '—',
                         'sem_c': 'good' if sem.startswith('🟢') else 'bad' if sem.startswith('🔴') else 'warn' if sem.startswith('🟡') else 'neu',
                         'Responsable': str(r.get('Responsable', '')), 'Fecha': str(r.get('Fecha compromiso', '')).strip(),
                         'Gestion': str(r.get(rol['gestion_cur'] or '', '')).strip()})
    cuadre_ctx = {m: [[f'<b>{c}</b>', mm(r.agente) if r.agente else '—', mm(r.carga) if r.carga else '—', _chip(*estado_cuadre(r))] for c, r in q.iterrows()]
                  for m, q in cuadre.items()}
    ctx = dict(fecha=hoy.strftime('%d-%m-%Y'), titular=titular, intro=intro, kpis=kpis, l0=l0, l1=l1,
               mancuerna=[(d['canal'], d['mg0'], d['mg1']) for d in sorted(det, key=lambda d: -d['mg1'])],
               titulo_mancuerna=titulo_m, detalle=det, titulos=titulos, plan=plan_ctx,
               titulo_plan=f'{con_gestion} de {len(plan)} acciones tienen gestión de {g_cur}', auto=auto_rows, cuadre=cuadre_ctx,
               lp0=lp0, lp1=lp1, g_cur=g_cur, g_prev=g_prev,
               titulo_auto=(f'{faltan} carpeta{"s" if faltan != 1 else ""} pendiente{"s" if faltan != 1 else ""} · {cuadran} de 5 canales cuadran en {l1.lower()}'))
    dash = dashboard_html(ctx)

    # ── correo: formato del primer informe (secciones, tablas y listas; sin imágenes) ──
    tdl = 'padding:5px 9px;border:1px solid #d5dbe5;font-size:12.5px;vertical-align:top'
    th = lambda x, a='left': f'<th style="padding:6px 9px;border:1px solid #d5dbe5;background:#1E3A5F;color:#fff;text-align:{a};font-size:12.5px">{x}</th>'  # noqa: E731
    cold = lambda d: ('#1E7A45' if d > 0.5 else '#C0392B' if d < -0.5 else '#64748b') if d is not None else '#64748b'  # noqa: E731
    res = ''.join(f'<tr><td style="{tdl};font-weight:600">{d["canal"]}</td><td style="{tdl};text-align:right">{mm(d["i1"])}</td>'
                  f'<td style="{tdl};text-align:right">{n(d["mg0"]) + "%" if d["mg0"] is not None else "—"}</td><td style="{tdl};text-align:right;font-weight:600">{n(d["mg1"])}%</td>'
                  f'<td style="{tdl};text-align:right;font-weight:600;color:{cold(d["d"])}">{pp(d["d"]) if d["mg0"] is not None else "—"}</td>'
                  f'<td style="{tdl};text-align:right">{(("+" if d["efecto"] > 0 else "−") + mm(abs(d["efecto"]))) if d["mg0"] is not None else "—"}</td></tr>' for d in sorted(det, key=lambda d: d['d']))
    ojo = ''.join(f'<li style="margin-bottom:8px"><b>{d["canal"]}</b> — {H.escape(d["narrativa"])}</li>' for d in det if abs(d['d']) >= 1) or '<li>Ningún canal se movió más de 1 p.p.</li>'
    por_resp = {}
    for a in alert:
        por_resp.setdefault(str(a[3]) or 'Sin responsable', []).append(a[0])
    alert_html = ''.join(f'<li><b>{H.escape(r)}</b>: {", ".join(xs)}</li>' for r, xs in por_resp.items())
    comp_mail = ''.join(f'<tr><td style="{tdl};font-weight:600;white-space:nowrap">{H.escape(r["ID"])}</td><td style="{tdl}">{H.escape(r["Accion"])}</td>'
                        f'<td style="{tdl}">{H.escape(r["Comprometido"])}</td><td style="{tdl};text-align:right">{H.escape(r["Base"])}</td>'
                        f'<td style="{tdl};text-align:right">{H.escape(r["Ultimo"])}</td><td style="{tdl};white-space:nowrap">{H.escape(r["sem_t"])}</td></tr>'
                        for r in plan_ctx if r['Comprometido'])
    comp_mail = (f'<p style="margin:10px 0 6px"><b>Compromisos de {g_prev} → resultado en {nom(pm1).lower() if pm1 else ""}</b>: lo que se anotó al cerrar '
                 f'{g_prev} y cómo se movió el indicador.</p><table style="border-collapse:collapse"><tr>{th("ID")}{th("Acción")}{th("Lo comprometido")}'
                 f'{th(lp0, "right")}{th(lp1, "right")}{th("Resultado")}</tr>{comp_mail}</table>') if comp_mail else ''
    plan_rows = ''.join(f'<tr><td style="{tdl};font-weight:600;white-space:nowrap">{H.escape(r["ID"])}</td><td style="{tdl};white-space:nowrap">{H.escape(r["Prio"])}</td><td style="{tdl}">{H.escape(r["Indicador"])}</td>'
                        f'<td style="{tdl};text-align:right">{H.escape(r["Base"])}</td><td style="{tdl};text-align:right">{H.escape(r["Ultimo"])}'
                        f'{_mes_tag(r["Mes"])}</td>'
                        f'<td style="{tdl};white-space:nowrap">{H.escape(r["sem_t"])}</td><td style="{tdl}">{H.escape(r["Responsable"])}</td>'
                        f'<td style="{tdl}">{H.escape(r["Fecha"]) or "—"}</td><td style="{tdl}">{H.escape(r["Gestion"]) or "—"}</td></tr>' for r in plan_ctx)
    auto_html = ''.join(f'<tr><td style="{tdl}">{m}</td><td style="{tdl};font-weight:600">{c}</td><td style="{tdl}">{d}</td>'
                        f'<td style="{tdl};text-align:center">{"✅ " + str(k) if k else "⏳ falta"}</td><td style="{tdl}">{u}</td></tr>' for m, c, d, k, u in auto_rows)
    cuad_mail = ''
    for mstr, q in cuadre.items():
        cuad_mail += (f'<p style="margin:12px 0 4px">Lectura automática de <b>{nom(mstr).lower()}</b> contra la carga manual (neto):</p><table style="border-collapse:collapse">'
                      f'<tr>{th("Canal")}{th("Automática", "right")}{th("Carga manual", "right")}{th("Estado")}</tr>'
                      + ''.join(f'<tr><td style="{tdl};font-weight:600">{c}</td><td style="{tdl};text-align:right">{mm(r.agente) if r.agente else "—"}</td>'
                                f'<td style="{tdl};text-align:right">{mm(r.carga) if r.carga else "—"}</td><td style="{tdl}">{estado_cuadre(r)[0]}</td></tr>' for c, r in q.iterrows()) + '</table>')
    encurso = ''.join(f'<p style="margin:10px 0 0">Carga manual de <b>{nom(m).lower()}</b> en curso: faltan {", ".join(c for c in MK if c not in cs) or "ninguno"}.</p>' for m, cs in X['en_curso'].items())
    h3 = 'style="color:#1E3A5F;margin:18px 0 6px"'
    body = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.5;max-width:960px">
<h2 style="color:#1E3A5F;margin:0 0 2px;font-size:19px">Rentabilidad por canal — cierre de {l1.lower()} · {hoy.strftime('%d-%m-%Y')}</h2>
<div style="color:#64748b;font-size:12px;margin-bottom:10px">Último mes con carga de los cinco marketplaces: <b>{l1}</b>{' · comparado con ' + l0 if M0 else ''} · <a href="{URL_SHEET}">planilla macro</a> · <a href="{URL_CARPETA}">carpeta de liquidaciones</a> · adjunto: dashboard con gráficos y detalle por canal</div>
<p style="margin:0 0 10px;padding:8px 10px;background:#EEF3FA;border-left:3px solid #1E3A5F;font-size:13px"><b>Reporte de cierre de {l1.lower()}.</b> Es el análisis del mes: {l1.lower()} contra {l0.lower() if M0 else 'el mes anterior'}, qué lo explica y el plan de acción. Las semanas siguientes llega el seguimiento del plan de acción.</p>
<h3 {h3}>1. Resultado</h3>
<table style="border-collapse:collapse"><tr>{th('Canal')}{th('Ingreso ' + l1[:3], 'right')}{th('% Mg ' + l0[:3], 'right')}{th('% Mg ' + l1[:3], 'right')}{th('Δ p.p.', 'right')}{th('Efecto $', 'right')}</tr>{res}</table>
<p style="font-size:12px;color:#475569;margin:4px 0 0">Efecto $ = variación del margen (p.p.) × ingreso de {l1.lower()}: cuánto margen dio o quitó el cambio.</p>
<h3 {h3}>2. Dónde dar ojo</h3><ul style="margin:0 0 10px 18px;padding:0">{ojo}</ul>
<h3 {h3}>3. Seguimiento del plan de acción</h3>
{comp_mail}
<p style="margin:12px 0 6px">{con_gestion} de {len(plan)} acciones tienen gestión de {g_cur}. Responsable, fecha compromiso y la gestión de {g_cur} se llenan en la pestaña <a href="{URL_SHEET}">8. Plan de acción</a>. Pendientes por responsable:</p>
{'<ul style="margin:0 0 10px 18px;padding:0;font-size:13px">' + alert_html + '</ul>' if alert_html else ''}
<table style="border-collapse:collapse"><tr>{th('ID')}{th('Prioridad')}{th('Indicador')}{th(lp0, 'right')}{th(lp1, 'right')}{th('Semáforo')}{th('Responsable')}{th('Fecha')}{th('Gestión de ' + g_cur)}</tr>{plan_rows}</table>
<h3 {h3}>4. Estado de la automatización</h3>
<table style="border-collapse:collapse"><tr>{th('Mes')}{th('Carpeta')}{th('Qué debe estar')}{th('Archivos')}{th('Última subida')}</tr>{auto_html}</table>
{cuad_mail}{encurso}
<p style="font-size:12px;color:#475569;margin-top:14px">Reporte automático de los lunes. La planilla y el plan de acción se refrescan todos los días con lo que llega a la carpeta de liquidaciones.</p>
</div>"""
    if modo == 'seguimiento':
        sig = ''
        for m, cs in sorted(X['en_curso'].items()):
            falt = [c for c in MK if c not in cs]
            sig += (f'<li><b>{nom(m)}</b>: {len(cs)} de 5 marketplaces cargados' + (f' · falta {", ".join(falt)}' if falt else '')
                    + f'. Con los cinco llega el reporte de cierre de {nom(m).lower()}.</li>')
        sig = sig or f'<li>Todavía no hay carga del mes siguiente a {l1.lower()}.</li>'
        pend = ('<ul style="margin:0 0 10px 18px;padding:0;font-size:13px">' + alert_html + '</ul>') if alert_html else ''
        body = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.5;max-width:960px">
<h2 style="color:#1E3A5F;margin:0 0 2px;font-size:19px">Rentabilidad por canal — seguimiento del plan de acción · {hoy.strftime('%d-%m-%Y')}</h2>
<div style="color:#64748b;font-size:12px;margin-bottom:10px"><a href="{URL_SHEET}">planilla macro</a> · <a href="{URL_CARPETA}">carpeta de liquidaciones</a> · adjunto: dashboard del cierre de {l1.lower()}</div>
<p style="margin:0 0 10px;padding:8px 10px;background:#EEF3FA;border-left:3px solid #1E3A5F;font-size:13px"><b>Semana de seguimiento.</b> El análisis del mes es el reporte de cierre de {l1.lower()}, que llegó al cerrar su carga. Esta semana: cómo avanza el plan de acción y la carga del mes siguiente.</p>
<h3 {h3}>1. Plan de acción</h3>
{comp_mail}
<p style="margin:12px 0 6px">{con_gestion} de {len(plan)} acciones tienen gestión de {g_cur}. Responsable, fecha compromiso y la gestión de {g_cur} se llenan en la pestaña <a href="{URL_SHEET}">8. Plan de acción</a>. Pendientes por responsable:</p>
{pend}
<table style="border-collapse:collapse"><tr>{th('ID')}{th('Prioridad')}{th('Indicador')}{th(lp0, 'right')}{th(lp1, 'right')}{th('Semáforo')}{th('Responsable')}{th('Fecha')}{th('Gestión de ' + g_cur)}</tr>{plan_rows}</table>
<h3 {h3}>2. Avance de la carga</h3><ul style="margin:0 0 10px 18px;padding:0">{sig}</ul>
<h3 {h3}>3. Estado de la automatización</h3>
<table style="border-collapse:collapse"><tr>{th('Mes')}{th('Carpeta')}{th('Qué debe estar')}{th('Archivos')}{th('Última subida')}</tr>{auto_html}</table>
{cuad_mail}
<p style="font-size:12px;color:#475569;margin-top:14px">Reporte automático de los lunes. Al cerrar la carga de cada mes llega el análisis del mes contra el anterior con su plan de acción; las semanas siguientes, este seguimiento.</p>
</div>"""
    return body, dash, dict(M0=M0, M1=M1, alertas=len(alert), plan=len(plan), cuadre=cuadre, en_curso=X['en_curso'], modo=modo)


def enviar(asunto, body, html_adj, to, cc=None):
    tok = os.environ.get('GMAIL_TOKEN_JSON', '').strip() or (ROOT / 'agente-comex/config/token.json').read_text()
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    t = json.loads(tok)
    creds = Credentials.from_authorized_user_info(t, t.get('scopes'))
    if not creds.valid:
        creds.refresh(Request())
    m = EmailMessage()
    m['From'] = 'andres@unionx.cl'
    m['To'] = ', '.join(to)
    if cc:
        m['Cc'] = ', '.join(cc)
    m['Subject'] = asunto
    m.add_alternative(body, subtype='html')
    m.add_attachment(html_adj.encode('utf-8'), maintype='text', subtype='html', filename='Rentabilidad por canal - dashboard.html')
    r = build('gmail', 'v1', credentials=creds).users().messages().send(userId='me', body={'raw': base64.urlsafe_b64encode(m.as_bytes()).decode()}).execute()
    return r['id']


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--enviar', action='store_true', help='a Gabriela con copia a Andrés')
    ap.add_argument('--no-mail', action='store_true')
    ap.add_argument('--sin-cuadre', action='store_true', help='no descarga liquidaciones para cuadrar')
    ap.add_argument('--out', default=str(Path(tempfile.gettempdir())))
    ap.add_argument('--modo', choices=['auto', 'cierre', 'seguimiento'], default='auto',
                    help='cierre = análisis del mes (una vez por mes cerrado); seguimiento = plan de acción')
    a = ap.parse_args()
    from zoneinfo import ZoneInfo
    hoy = dt.datetime.now(ZoneInfo('America/Santiago')).date()   # fecha de Chile (el runner está en UTC)
    body, dash, info = construir(hoy, cuadrar=not a.sin_cuadre, modo=a.modo)
    Path(a.out, 'rentabilidad_semanal.html').write_text(body, encoding='utf-8')
    Path(a.out, 'rentabilidad_semanal_dashboard.html').write_text(dash, encoding='utf-8')
    print(f"[reporte] modo {info['modo']} · {info['M1']} vs {info['M0']} · plan {info['plan']} acciones, {info['alertas']} con alerta")
    if a.no_mail:
        sys.exit(0)
    if info['modo'] == 'cierre':
        asunto = f"Rentabilidad por canal — cierre de {nom(info['M1']).lower()}: análisis del mes y plan de acción"
    else:
        asunto = f"Rentabilidad por canal — seguimiento del plan de acción · semana {hoy.strftime('%d-%m')}"
    if a.enviar:
        to = [x.strip() for x in os.environ.get('RENTABILIDAD_TO', 'gabriela@unionx.cl').split(',') if x.strip()]
        cc = [x.strip() for x in os.environ.get('RENTABILIDAD_CC', 'andres@unionx.cl').split(',') if x.strip()]
    else:
        to, cc, asunto = ['andres@unionx.cl'], None, '[VISTA PREVIA] ' + asunto
    print('ENVIADO', to, cc, enviar(asunto, body, dash, to, cc))
    if a.enviar and info['modo'] == 'cierre':       # el cierre del mes ya salió: las próximas semanas son seguimiento
        estado_guardar(D._abrir(D._cli(), crear_si_falta=False)[0], info['M1'])
