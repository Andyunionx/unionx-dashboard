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
    gab['Glosa'] = gab['Glosa'].astype(str).str.strip()
    try:
        vp = sh.worksheet(PA.H_PLAN).get_all_values()
        plan = pd.DataFrame(vp[1:], columns=vp[0])
        plan = plan[plan['ID'].astype(str).str.strip().str.fullmatch(r'[A-Z]{2,4}-\d+')]
    except Exception:
        plan = pd.DataFrame()
    return sh, base, gab, plan


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
            mes = next((v for k, v in MES_CARPETA.items() if k in m['name'].upper()), None)
            if not mes:
                continue
            files = []
            pila = [m]
            while pila:
                x = pila.pop()
                for f in hijos(x['id']):
                    (pila.append(f) if f['mimeType'].endswith('folder') else files.append((f, x['name'])))
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
    # Mes de cierre = último mes con carga de los cinco marketplaces (uno a medio cargar no
    # se compara: se informa como "carga en curso" en la sección de automatización).
    por_mes = gab[gab['Canal'].isin(MK)].groupby('Mes')['Canal'].apply(set)
    completos = sorted(m for m, cs in por_mes.items() if set(MK) <= cs)
    M1 = completos[-1] if completos else sorted(por_mes.index)[-1]
    M0 = completos[-2] if len(completos) > 1 else None
    en_curso = {m: sorted(cs) for m, cs in por_mes.items() if m > M1}
    raw = base[base['Fuente'] == 'RAW ventas']
    ING = raw[raw['Centro de costo'] == 'Ingreso venta'].groupby(['Canal', 'Mes'])['Monto'].sum()
    ING_MOD = raw[raw['Centro de costo'] == 'Ingreso venta'].groupby(['Canal', 'Modalidad', 'Mes'])['Monto'].sum()
    CC = base.groupby(['Canal', 'Mes', 'Centro de costo'])['Monto'].sum()
    canales = [c for c in MK if ING.get((c, M1), 0) > 0]

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
        if not str(r.get('Última gestión (quién / qué / cuándo)', '')).strip():
            falta.append('sin gestión registrada')
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


def dashboard_html(ctx):
    """Dashboard completo (adjunto). También es la fuente de los PNG del correo: cada panel
    con id se captura con Playwright."""
    k, opts = ctx['kpis'], {}
    kp = ''.join(f"""<div class="kpi"><div class="eyebrow">{H.escape(t['label'])}</div><div class="kv">{t['valor']}<span class="ku">{t.get('unidad', '')}</span></div>
<div class="kd" style="color:{t.get('color', MUTE)}">{t['meta']}</div></div>""" for t in k)
    opts['c_mancuerna'] = opt_mancuerna(ctx['mancuerna'], ctx['l0'], ctx['l1'])
    canales = ''
    for i, c in enumerate(ctx['canales']):
        opts[f'c_casc{i}'] = opt_cascada(c['cascada'])
        if c['glosas']:
            opts[f'c_glo{i}'] = opt_glosas(c['glosas'])
        canales += f"""<section class="panel" id="p_canal{i}"><div class="eyebrow">{H.escape(c['canal'])} · {H.escape(c['sub'])}</div>
<h3>{H.escape(c['titulo'])}</h3><p class="lead">{H.escape(c['lead'])}</p>
<div class="two" id="g_canal{i}" style="background:#fff;padding:4px 2px"><div><div class="mini">De dónde sale la variación del margen (p.p. del ingreso)</div><div class="chart" id="c_casc{i}" style="height:250px"></div></div>
<div><div class="mini">Glosas que más se movieron</div>{f'<div class="chart" id="c_glo{i}" style="height:250px"></div>' if c['glosas'] else '<p class="lead">Sin glosas con más de 0,3 p.p. de variación.</p>'}</div></div></section>"""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rentabilidad por canal</title><style>
:root{{--navy:{NAVY};--blue:{BLUE};--ink:{INK};--mute:{MUTE};--rule:{RULE};--bg:{BG}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:{SANS}}}
.wrap{{max-width:1120px;margin:0 auto;padding:32px 24px 56px;display:flex;flex-direction:column;gap:18px}}
.eyebrow{{font-family:{MONO};font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--mute)}}
h1{{font-family:{SERIF};font-weight:400;font-size:38px;line-height:1.15;margin:6px 0 4px;text-wrap:balance;max-width:880px}} h1 em{{color:var(--blue);font-style:normal}}
.intro{{max-width:640px;color:#334155;font-size:15px;line-height:1.55;margin:0}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);background:#fff;border:1px solid var(--rule)}}
.kpi{{padding:16px 18px;border-right:1px solid var(--rule)}} .kpi:last-child{{border-right:0}}
.kv{{font-family:{MONO};font-size:30px;font-weight:600;margin:8px 0 4px;font-variant-numeric:tabular-nums}} .ku{{font-size:13px;color:var(--mute);margin-left:4px;font-weight:400}}
.kd{{font-family:{MONO};font-size:12px}}
.panel{{background:#fff;border:1px solid var(--rule);padding:18px 20px}}
.panel h3{{font-family:{SERIF};font-weight:400;font-size:21px;margin:6px 0 4px;text-wrap:balance}} .lead{{color:var(--mute);font-size:13.5px;margin:0 0 8px;max-width:760px;line-height:1.5}}
.mini{{font-family:{MONO};font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);margin:6px 0 2px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:22px}} .chart{{width:100%}}
@media (max-width:820px){{.kpis{{grid-template-columns:1fr 1fr}} .two{{grid-template-columns:1fr}} h1{{font-size:28px}}}}
</style></head><body><div class="wrap">
<div><div class="eyebrow">Rentabilidad por canal · reporte semanal · {H.escape(ctx['fecha'])}</div>
<h1>{ctx['titular']}</h1><p class="intro">{H.escape(ctx['intro'])}</p></div>
<div class="kpis" id="p_kpis">{kp}</div>
<section class="panel" id="p_mancuerna"><div class="eyebrow">Comparación · margen por canal</div><h3>{H.escape(ctx['titulo_mancuerna'])}</h3>
<p class="lead">Punto hueco = {H.escape(ctx['l0'].lower())}, punto sólido = {H.escape(ctx['l1'].lower())} (verde si sube, rojo si baja). La distancia es la variación.</p>
<div id="g_mancuerna" style="background:#fff;padding:4px 2px"><div class="chart" id="c_mancuerna" style="height:{60 + 46 * len(ctx['mancuerna'])}px"></div></div></section>
{canales}
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/6.1.0/echarts.min.js"></script><script>
function fmtNum(v){{if(v==null||v==='')return '';var a=Math.abs(v);var d=(a<100&&a!==Math.round(a))?1:0;return v.toLocaleString('es-CL',{{minimumFractionDigits:d,maximumFractionDigits:d}});}}
var O={_js(opts)};
Object.keys(O).forEach(function(i){{var e=document.getElementById(i);if(!e)return;var c=echarts.init(e,null,{{renderer:'canvas'}});c.setOption(O[i]);new ResizeObserver(function(){{c.resize();}}).observe(e);}});
window.__listo=true;
</script></body></html>"""


def capturar_png(html: str, ids):
    """PNG 2x de cada panel (para incrustar en el correo). Requiere playwright + chromium."""
    from playwright.sync_api import sync_playwright
    out = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        f = Path(td) / 'dash.html'
        f.write_text(html, encoding='utf-8')
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={'width': 1000, 'height': 1000}, device_scale_factor=2)
            pg.goto(f.as_uri())
            pg.wait_for_function('window.__listo === true', timeout=30000)
            pg.wait_for_timeout(700)
            for i in ids:
                el = pg.query_selector(f'#{i}')
                if el:
                    out[i] = el.screenshot(type='png')
            b.close()
    return out


# ───────────────────────── reporte ─────────────────────────
def construir(hoy=None, cuadrar=True, con_png=True):
    hoy = hoy or dt.date.today()
    sh, base, gab, plan = cargar()
    X = metricas(base, gab)
    M0, M1, ING = X['M0'], X['M1'], X['ING']
    canales = X['canales']
    MG = {c: (X['mg'](c, M0) if M0 else None, X['mg'](c, M1)) for c in canales}
    l0, l1 = (nom(M0) if M0 else ''), nom(M1)

    # consolidado de los cinco marketplaces
    def tot(m):
        if not m:
            return None, 0
        i = sum(ING.get((c, m), 0) for c in canales)
        mg_ = float(base[base['Canal'].isin(canales) & (base['Mes'] == m)]['Monto'].sum())
        return (mg_ / i * 100 if i else None), mg_
    t0, c0 = tot(M0)
    t1, c1 = tot(M1)

    # canales ordenados por variación
    orden = sorted(canales, key=lambda c: ((MG[c][1] - MG[c][0]) if MG[c][0] is not None else 0))
    caen = [c for c in orden if MG[c][0] is not None and MG[c][1] - MG[c][0] <= -1]
    suben = [c for c in orden if MG[c][0] is not None and MG[c][1] - MG[c][0] >= 1]
    if caen:
        c_peor = caen[0]
        titular = (f'<em>{H.escape(" y ".join(caen))}</em> pierde{"n" if len(caen) > 1 else ""} margen en {l1.lower()}'
                   + (f'; {H.escape(" y ".join(suben))} mejora{"n" if len(suben) > 1 else ""}.' if suben else '.'))
    else:
        titular = f'Ningún marketplace pierde más de 1 punto de margen en {l1.lower()}.'
    intro = (f'{l1} contra {l0.lower()} en los cinco marketplaces con liquidación cargada. Margen = ingreso − costo de venta − devolución − comisión de venta − '
             f'comisión de envío − marketing, como % del ingreso del canal.') if M0 else f'Resultado de {l1.lower()}.'

    # plan + automatización
    alert = alertas_plan(plan, hoy) if len(plan) else []
    con_gestion = sum(1 for _, r in plan.iterrows() if str(r.get('Última gestión (quién / qué / cuándo)', '')).strip())
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
                q['sin_regla'] = liq[liq['canal'].isin(MK) & (liq['estado_regla'] == 'sin regla')].groupby('canal')['monto_neto'].apply(lambda s: s.abs().sum())
                cuadre[mstr] = q.fillna(0)
    except Exception as e:
        print(f'   [WARN] automatización: {type(e).__name__}: {e}')
    qm = cuadre.get(M1)
    cuadran = int(((qm['dif'].abs() <= qm['carga'].abs() * 0.02) & (qm['carga'] != 0)).sum()) if qm is not None else 0

    kpis = [
        {'label': f'Margen marketplaces · {l1}', 'valor': n(t1) if t1 is not None else '—', 'unidad': '%',
         'meta': (f'{"▲" if t1 >= t0 else "▼"} {pp(t1 - t0)} p.p. vs {l0.lower()}' if t0 is not None else ''), 'color': (GOOD if t0 is not None and t1 >= t0 else BAD)},
        {'label': f'Contribución · {l1}', 'valor': n(c1 / 1e6, 1), 'unidad': 'M CLP',
         'meta': (f'{"▲" if c1 >= c0 else "▼"} {pp((c1 - c0) / 1e6)} M vs {l0.lower()}' if M0 else ''), 'color': (GOOD if c1 >= c0 else BAD)},
        {'label': 'Plan de acción con gestión', 'valor': f'{con_gestion}/{len(plan)}', 'unidad': 'acciones',
         'meta': f'{len(alert)} requieren gestión esta semana', 'color': (BAD if con_gestion == 0 else AMBER if alert else GOOD)},
        {'label': f'Lectura automática · {l1}', 'valor': f'{cuadran}/5', 'unidad': 'canales',
         'meta': 'cuadran con la carga manual (±2%)', 'color': (GOOD if cuadran == 5 else AMBER)},
    ]

    ch_canales = []
    for c in sorted(canales, key=lambda c: -abs((MG[c][1] - MG[c][0]) if MG[c][0] is not None else 0)):
        mg0, mg1 = MG[c]
        d = (mg1 - mg0) if mg0 is not None else 0
        deltas = [(lab, X['ccp'](c, cc, M1) - X['ccp'](c, cc, M0)) for lab, cc in
                  [('Costo venta', 'Costo venta'), ('Comisión venta', 'Comisión venta'), ('Comisión envío', 'Comisión envío'),
                   ('Marketing', 'Marketing'), ('Devolución', 'Devolución')]] if M0 else []
        otros = d - sum(v for _, v in deltas)
        if abs(otros) >= 0.05:
            deltas.append(('Otros', otros))
        mayor = max(deltas, key=lambda t: abs(t[1])) if deltas else ('', 0)
        mv = X['movers'](c)
        verbo = 'sube' if d > 0.5 else 'baja' if d < -0.5 else 'se mantiene'
        titulo = (f'{c} {verbo} {n(abs(d))} p.p.; lo que más pesa es {mayor[0].lower()} ({pp(mayor[1])} p.p.)' if abs(d) > 0.5
                  else f'{c} se mantiene en {n(mg1)}%')
        lead = (f'Ingreso {l1.lower()} {mm(ING.get((c, M1), 0))}, margen {n(mg0) + "% → " if mg0 is not None else ""}{n(mg1)}%.'
                + (f' La glosa que más se movió es "{mv[0][0]}" ({pp(mv[0][1])} p.p. del ingreso).' if mv else ''))
        ch_canales.append({'canal': c, 'sub': f'{l0} → {l1}', 'titulo': titulo, 'lead': lead,
                           'cascada': [(f'Margen {l0[:3].lower()}', mg0 or 0, 'start')] + [(lab, v, 'dec') for lab, v in deltas] + [(f'Margen {l1[:3].lower()}', 0, 'total')],
                           'glosas': mv, 'd': d, 'mg0': mg0, 'mg1': mg1})
    mancuerna = [(c, MG[c][0], MG[c][1]) for c in sorted(canales, key=lambda c: -MG[c][1])]
    peor = min(canales, key=lambda c: (MG[c][1] - MG[c][0]) if MG[c][0] is not None else 0)
    mejor = max(canales, key=lambda c: (MG[c][1] - MG[c][0]) if MG[c][0] is not None else 0)
    titulo_m = (f'{peor} cae {n(abs(MG[peor][1] - MG[peor][0]))} p.p. y {mejor} sube {n(MG[mejor][1] - MG[mejor][0])} p.p.' if M0 else f'Margen por canal en {l1.lower()}')
    ctx = dict(fecha=hoy.strftime('%d %b %Y').lower(), titular=titular, intro=intro, kpis=kpis, mancuerna=mancuerna, l0=l0, l1=l1,
               titulo_mancuerna=titulo_m, canales=ch_canales)
    dash = dashboard_html(ctx)
    ids = ['g_mancuerna'] + [f'g_canal{i}' for i in range(len(ch_canales))]
    pngs = capturar_png(dash, ids) if con_png else {}

    # ── correo email-safe ──
    tdb = f'padding:9px 12px;border-bottom:1px solid {RULE};font-size:13px;vertical-align:top;font-family:{SANS};color:{INK}'
    thb = f'padding:8px 12px;border-bottom:2px solid {NAVY};font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:{MUTE};font-family:{MONO};text-align:left;font-weight:600'

    def chip(t, color):
        return f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;border:1px solid {color};color:{color};font-size:11px;font-family:{MONO};white-space:nowrap">{t}</span>'

    kpi_cells = ''.join(f'<td width="25%" style="padding:14px 16px;border-right:1px solid {RULE};vertical-align:top;background:#fff">'
                        f'<div style="font-family:{MONO};font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:{MUTE}">{H.escape(t["label"])}</div>'
                        f'<div style="font-family:{MONO};font-size:26px;font-weight:600;color:{INK};margin:6px 0 2px">{t["valor"]}<span style="font-size:12px;color:{MUTE};font-weight:400;margin-left:4px">{t["unidad"]}</span></div>'
                        f'<div style="font-family:{MONO};font-size:11.5px;color:{t["color"]}">{t["meta"]}</div></td>' for t in kpis)
    img = lambda cid, w=920: f'<img src="cid:{cid}" width="{w}" style="display:block;width:100%;max-width:{w}px;height:auto;border:0" alt="">'  # noqa: E731

    def panel(eyebrow, titulo, contenido, sub=''):
        return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid {RULE};margin:0 0 16px"><tr><td style="padding:18px 20px">'
                f'<div style="font-family:{MONO};font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:{MUTE}">{eyebrow}</div>'
                f'<div style="font-family:{SERIF};font-size:20px;color:{INK};margin:6px 0 4px">{titulo}</div>'
                + (f'<div style="font-family:{SANS};font-size:13px;color:{MUTE};margin:0 0 10px;line-height:1.5">{sub}</div>' if sub else '')
                + contenido + '</td></tr></table>')

    # 1. resultado (mancuerna)
    sec1 = panel('1 · Resultado · margen por canal', H.escape(titulo_m), img('g_mancuerna') if 'g_mancuerna' in pngs else '',
                 f'Punto hueco = {l0.lower()}, punto sólido = {l1.lower()} (verde sube, rojo baja).')
    # 2. dónde dar ojo: canales con |Δ| >= 1
    sec2 = ''
    for i, cc in enumerate(ch_canales):
        if abs(cc['d']) < 1:
            continue
        sec2 += panel(f'2 · Dónde dar ojo · {H.escape(cc["canal"])}', H.escape(cc['titulo']), img(f'g_canal{i}') if f'g_canal{i}' in pngs else '', H.escape(cc['lead']))
    # 3. plan
    por_resp = {}
    for a in alert:
        por_resp.setdefault(str(a[3]) or 'Sin responsable', []).append(a)
    filas_plan = ''
    for _, r in plan.iterrows():
        sem = str(r.get('Semáforo', ''))
        col = GOOD if sem.startswith('🟢') else BAD if sem.startswith('🔴') else AMBER if sem.startswith('🟡') else MUTE
        ges = str(r.get('Última gestión (quién / qué / cuándo)', '')).strip()
        fec = str(r.get('Fecha compromiso', '')).strip()
        filas_plan += (f'<tr><td style="{tdb};font-family:{MONO};font-weight:600;white-space:nowrap">{H.escape(str(r["ID"]))}</td><td style="{tdb}">{H.escape(str(r.get("Indicador", "")))}</td>'
                       f'<td style="{tdb};text-align:right;font-family:{MONO}">{H.escape(str(r.get(f"Base {PA.M_BASE}", "")))}</td>'
                       f'<td style="{tdb};text-align:right;font-family:{MONO}">{H.escape(str(r.get("Valor último mes", "")))}</td>'
                       f'<td style="{tdb}">{chip(sem[2:].strip() or "—", col)}</td><td style="{tdb}">{H.escape(str(r.get("Responsable", "")))}</td>'
                       f'<td style="{tdb}">{chip(fec, INK) if fec else chip("sin fecha", BAD)}</td><td style="{tdb}">{H.escape(ges) if ges else chip("sin gestión", BAD)}</td></tr>')
    resp_html = ''.join(f'<li style="margin:0 0 4px"><b>{H.escape(r)}</b>: {", ".join(x[0] for x in xs)}</li>' for r, xs in por_resp.items())
    sec3 = panel('3 · Seguimiento del plan de acción',
                 f'{con_gestion} de {len(plan)} acciones tienen gestión registrada',
                 (f'<ul style="margin:0 0 12px 18px;padding:0;font-family:{SANS};font-size:13px;color:{INK}">{resp_html}</ul>' if resp_html else '')
                 + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><th style="{thb}">ID</th><th style="{thb}">Indicador</th><th style="{thb};text-align:right">Base</th>'
                 f'<th style="{thb};text-align:right">Último</th><th style="{thb}">Semáforo</th><th style="{thb}">Responsable</th><th style="{thb}">Fecha</th><th style="{thb}">Última gestión</th></tr>{filas_plan}</table>',
                 f'Responsable, fecha compromiso, estado y última gestión se llenan en la pestaña <a href="{URL_SHEET}" style="color:{BLUE}">8. Plan de acción</a>. '
                 'Pendientes por responsable:' if resp_html else '')
    # 4. automatización
    filas_auto = ''.join(f'<tr><td style="{tdb}">{m}</td><td style="{tdb};font-family:{MONO};font-weight:600">{c}</td><td style="{tdb};color:{MUTE}">{d}</td>'
                         f'<td style="{tdb}">{chip(f"{k} archivo" + ("s" if k != 1 else ""), GOOD) if k else chip("falta", AMBER)}</td><td style="{tdb};font-family:{MONO};color:{MUTE}">{u}</td></tr>'
                         for m, c, d, k, u in auto_rows)
    cuad_html = ''
    for mstr, q in cuadre.items():
        filas = ''
        for c, r in q.reindex(MK).fillna(0).iterrows():
            ok = r.carga and r.agente and abs(r.dif) <= abs(r.carga) * 0.02
            est = chip('cuadra', GOOD) if ok else (chip('sin archivo', AMBER) if not r.agente else chip('sin carga', AMBER) if not r.carga else chip(f'dif. {mm(r.dif)}', BAD))
            filas += (f'<tr><td style="{tdb};font-weight:600">{c}</td><td style="{tdb};text-align:right;font-family:{MONO}">{mm(r.agente) if r.agente else "—"}</td>'
                      f'<td style="{tdb};text-align:right;font-family:{MONO}">{mm(r.carga) if r.carga else "—"}</td><td style="{tdb}">{est}</td></tr>')
        cuad_html += (f'<div style="font-family:{MONO};font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:{MUTE};margin:16px 0 4px">Cuadre {nom(mstr).lower()} · lectura automática vs carga manual (neto)</div>'
                      f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><th style="{thb}">Canal</th><th style="{thb};text-align:right">Automática</th><th style="{thb};text-align:right">Carga manual</th><th style="{thb}">Estado</th></tr>{filas}</table>')
    encurso = ''.join(f'<p style="font-family:{SANS};font-size:13px;color:{INK};margin:12px 0 0">Carga manual de <b>{nom(m).lower()}</b> en curso: faltan {", ".join(c for c in MK if c not in cs) or "ninguno"}.</p>' for m, cs in X['en_curso'].items())
    faltan = sum(1 for r in auto_rows if not r[3])
    sec4 = panel('4 · Estado de la automatización', f'{faltan} carpeta{"s" if faltan != 1 else ""} de liquidaciones pendiente{"s" if faltan != 1 else ""}' if faltan else 'Carpeta de liquidaciones al día',
                 f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><th style="{thb}">Mes</th><th style="{thb}">Carpeta</th><th style="{thb}">Qué debe estar</th><th style="{thb}">Estado</th><th style="{thb}">Última subida</th></tr>{filas_auto}</table>'
                 + cuad_html + encurso, f'Carpeta: <a href="{URL_CARPETA}" style="color:{BLUE}">liquidaciones en Drive</a>.')
    body = f"""<div style="background:{BG};padding:24px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="960" cellpadding="0" cellspacing="0" style="max-width:960px;width:100%"><tr><td style="padding:0 16px">
<div style="font-family:{MONO};font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:{MUTE}">Rentabilidad por canal · reporte semanal · {H.escape(ctx['fecha'])}</div>
<div style="font-family:{SERIF};font-size:30px;line-height:1.2;color:{INK};margin:8px 0 6px">{titular.replace('<em>', f'<span style="color:{BLUE}">').replace('</em>', '</span>')}</div>
<div style="font-family:{SANS};font-size:14px;color:#334155;line-height:1.55;margin:0 0 16px;max-width:680px">{H.escape(intro)} <a href="{URL_SHEET}" style="color:{BLUE}">Planilla macro</a> · adjunto: dashboard interactivo.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {RULE};margin:0 0 16px"><tr>{kpi_cells}</tr></table>
{sec1}{sec2}{sec3}{sec4}
<div style="font-family:{SANS};font-size:11.5px;color:{MUTE};margin:8px 0 0">Reporte automático de los lunes. La planilla se refresca los lunes 09:00 y 12:00 y la pestaña de plan de acción se recalcula en la misma corrida.</div>
</td></tr></table></td></tr></table></div>"""
    return body, dash, dict(M0=M0, M1=M1, alertas=len(alert), plan=len(plan), cuadre=cuadre, en_curso=X['en_curso'], pngs=pngs)


def enviar(asunto, body, html_adj, to, cc=None, pngs=None):
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
    m.set_content('Reporte semanal de rentabilidad por canal. Ábrelo en un cliente que muestre HTML.')
    m.add_alternative(body, subtype='html')
    htmlpart = m.get_payload()[1]
    for cid, png in (pngs or {}).items():
        htmlpart.add_related(png, maintype='image', subtype='png', cid=f'<{cid}>')
    m.add_attachment(html_adj.encode('utf-8'), maintype='text', subtype='html', filename='Rentabilidad por canal - dashboard.html')
    r = build('gmail', 'v1', credentials=creds).users().messages().send(userId='me', body={'raw': base64.urlsafe_b64encode(m.as_bytes()).decode()}).execute()
    return r['id']


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--enviar', action='store_true', help='a Gabriela con copia a Andrés')
    ap.add_argument('--no-mail', action='store_true')
    ap.add_argument('--sin-cuadre', action='store_true', help='no descarga liquidaciones para cuadrar')
    ap.add_argument('--out', default=str(Path(tempfile.gettempdir())))
    a = ap.parse_args()
    hoy = dt.date.today()
    body, dash, info = construir(hoy, cuadrar=not a.sin_cuadre)
    Path(a.out, 'rentabilidad_semanal.html').write_text(body, encoding='utf-8')
    Path(a.out, 'rentabilidad_semanal_dashboard.html').write_text(dash, encoding='utf-8')
    for cid, png in info['pngs'].items():
        Path(a.out, f'{cid}.png').write_bytes(png)
    print(f"[reporte] {info['M1']} vs {info['M0']} · plan {info['plan']} acciones, {info['alertas']} con alerta · {len(info['pngs'])} gráficos")
    if a.no_mail:
        sys.exit(0)
    asunto = f"Rentabilidad por canal — semana {hoy.strftime('%d-%m')} · {nom(info['M1'])}: resultado, plan de acción y automatización"
    if a.enviar:
        to = [x.strip() for x in os.environ.get('RENTABILIDAD_TO', 'gabriela@unionx.cl').split(',') if x.strip()]
        cc = [x.strip() for x in os.environ.get('RENTABILIDAD_CC', 'andres@unionx.cl').split(',') if x.strip()]
    else:
        to, cc, asunto = ['andres@unionx.cl'], None, '[VISTA PREVIA] ' + asunto
    print('ENVIADO', to, cc, enviar(asunto, body, dash, to, cc, info['pngs']))
