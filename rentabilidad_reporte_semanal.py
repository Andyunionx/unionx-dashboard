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


# ───────────────────────── gráficos (ECharts, guía "MD Gráficos") ─────────────────────────
EMF, NAVY, GRAY, RULE, MUTE, INK, NEG, POS, POS_SOFT = '#2E75B6', '#1F3864', '#B9C6CF', '#DCE3E8', '#7C8B98', '#1E293B', '#9B3A2F', '#0E7A54', '#5FA98A'
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif"


def _lbl(t, pos='top', color=INK, bold=False, size=10):
    return {'show': True, 'position': pos, 'formatter': t, 'color': color, 'fontWeight': 'bold' if bold else 'normal', 'fontSize': size, 'fontFamily': FONT}


def _cat(cats):
    return {'type': 'category', 'data': cats, 'axisTick': {'show': False}, 'axisLine': {'lineStyle': {'color': RULE}},
            'axisLabel': {'color': MUTE, 'fontFamily': FONT, 'fontSize': 11, 'interval': 0}}


def _val(u=None):
    return {'type': 'value', 'name': u, 'nameTextStyle': {'color': MUTE, 'fontSize': 10, 'align': 'left', 'padding': [0, 0, 0, -10]},
            'axisLine': {'show': False}, 'axisTick': {'show': False},
            'axisLabel': {'color': MUTE, 'fontFamily': FONT, 'fontSize': 10, 'formatter': '@@AXIS@@'},
            'splitLine': {'lineStyle': {'color': RULE, 'type': 'dashed'}}}


TIP = {'trigger': 'item', 'formatter': '@@TIP@@', 'backgroundColor': '#fff', 'borderColor': RULE, 'textStyle': {'color': INK, 'fontSize': 12}}


class Charts:
    def __init__(self):
        self.items = []

    def div(self, opt, h=280):
        cid = f'ch{len(self.items)}'
        self.items.append((cid, opt))
        return f'<div class="chart" id="{cid}" style="height:{h}px"></div>'

    def js(self):
        o = json.dumps({c: x for c, x in self.items}, ensure_ascii=False)
        return o.replace('"@@AXIS@@"', 'function(v){return fmtNum(v);}').replace(
            '"@@TIP@@"', "function(p){var q=Array.isArray(p)?p:[p];var s='';q.forEach(function(x){if(x.data&&x.data.tip){s+=(s?'<br>':'')+x.data.tip;}});return s||(q[0].name||'');}")


def cascada(steps):
    cats, bases, alts, tops, cum = [], [], [], [], 0.0
    for lab, v, kind in steps:
        cats.append(lab.replace(' ', '\n', 1) if kind == 'dec' else lab)
        if kind == 'start':
            b, h, disp, color, cum = min(0, v), abs(v), v, EMF, v
        elif kind == 'total':
            b, h, disp, color = min(0, cum), abs(cum), cum, NAVY
        else:
            nx = cum + v
            b, h, disp, color, cum = min(cum, nx), abs(v), v, (POS_SOFT if v > 0 else NEG), nx
        bases.append(round(b, 3))
        alts.append({'value': round(h, 3), 'tip': f'{lab}: {n(disp)} p.p.', 'itemStyle': {'color': color, 'borderRadius': [3, 3, 0, 0]}, 'label': {'show': False}})
        tops.append({'value': round(b + h, 3), 'tip': None, 'label': _lbl(pp(disp) if kind == 'dec' else n(disp) + '%', 'top', INK if kind != 'dec' else MUTE, kind != 'dec')})
    return {'tooltip': TIP, 'grid': {'left': 14, 'right': 12, 'top': 34, 'bottom': 4, 'containLabel': True}, 'xAxis': _cat(cats), 'yAxis': _val('p.p.'),
            'series': [{'name': '_b', 'type': 'bar', 'stack': 'w', 'data': bases, 'itemStyle': {'color': 'transparent'}, 'emphasis': {'disabled': True}, 'tooltip': {'show': False}, 'barWidth': '56%'},
                       {'name': 'v', 'type': 'bar', 'stack': 'w', 'data': alts, 'barWidth': '56%'},
                       {'name': '_t', 'type': 'bar', 'data': tops, 'barGap': '-100%', 'barWidth': '56%', 'itemStyle': {'color': 'transparent'}, 'emphasis': {'disabled': True}, 'tooltip': {'show': False}}]}


def barras2(cats, s0, s1, l0, l1, u='% margen'):
    def serie(nm, vals, color, enf):
        return {'name': nm, 'type': 'bar', 'barMaxWidth': 38, 'itemStyle': {'color': color, 'borderRadius': [3, 3, 0, 0]},
                'data': [{'value': (round(v, 2) if v is not None else None), 'tip': f'{nm}: {n(v)}%' if v is not None else '',
                          'label': _lbl(n(v) + '%' if v is not None else '', 'top', INK if enf else MUTE, enf, 10)} for v in vals]}
    return {'tooltip': TIP, 'legend': {'top': 0, 'right': 4, 'itemWidth': 10, 'itemHeight': 10, 'icon': 'roundRect', 'textStyle': {'color': MUTE, 'fontSize': 11}},
            'grid': {'left': 14, 'right': 12, 'top': 34, 'bottom': 4, 'containLabel': True}, 'xAxis': _cat(cats), 'yAxis': _val(u),
            'series': ([serie(l0, s0, GRAY, False)] if s0 is not None else []) + [serie(l1, s1, EMF, True)]}


def barras_h(items):
    items = sorted(items, key=lambda t: abs(t[1]))
    data = [{'value': round(v, 2), 'tip': f'{g}: {pp(v)} p.p.', 'itemStyle': {'color': POS if v > 0 else NEG, 'borderRadius': [0, 3, 3, 0] if v > 0 else [3, 0, 0, 3]},
             'label': _lbl(pp(v), 'right' if v > 0 else 'left', INK, False, 10)} for g, v in items]
    return {'tooltip': TIP, 'grid': {'left': 8, 'right': 64, 'top': 6, 'bottom': 4, 'containLabel': True},
            'xAxis': _val('Δ p.p.'), 'yAxis': {'type': 'category', 'data': [g[:40] for g, _ in items], 'axisTick': {'show': False}, 'axisLine': {'show': False},
                                               'axisLabel': {'color': INK, 'fontFamily': FONT, 'fontSize': 11}},
            'series': [{'type': 'bar', 'data': data, 'barMaxWidth': 20}]}


# ───────────────────────── reporte ─────────────────────────
def construir(hoy=None, cuadrar=True):
    hoy = hoy or dt.date.today()
    sh, base, gab, plan = cargar()
    X = metricas(base, gab)
    M0, M1, ING = X['M0'], X['M1'], X['ING']
    canales = X['canales']
    MG = {c: (X['mg'](c, M0) if M0 else None, X['mg'](c, M1)) for c in canales}

    # 2. dónde dar ojo (automático)
    ojo = []
    for c in sorted(canales, key=lambda c: -abs((MG[c][1] or 0) - (MG[c][0] or 0))):
        d = (MG[c][1] - MG[c][0]) if MG[c][0] is not None else None
        mv = X['movers'](c)
        txt = f'Margen {n(MG[c][0]) + "% → " if MG[c][0] is not None else ""}{n(MG[c][1])}%' + (f' ({pp(d)} p.p.).' if d is not None else '.')
        if mv:
            txt += ' Lo explican: ' + '; '.join(f'"{gl}" {pp(v)} p.p.' for gl, v in mv[:3]) + '.'
        prio = 'ALTA' if d is not None and d <= -3 else ('MEDIA' if d is not None and abs(d) >= 1 else 'BAJA')
        ojo.append((c, prio, txt, d))

    # 3. plan
    alert = alertas_plan(plan, hoy) if len(plan) else []
    sin_gestion = sum(1 for a in alert if 'sin gestión' in a[4])

    # 4. automatización
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
            cuadre = {}
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
                liq.to_parquet(Path(tempfile.gettempdir()) / f'liquidaciones_{mstr}.parquet', index=False)
    except Exception as e:
        print(f'   [WARN] automatización: {type(e).__name__}: {e}')

    # ── HTML adjunto con gráficos ──
    ch = Charts()
    orden = sorted(canales, key=lambda c: (MG[c][1] - (MG[c][0] or MG[c][1])))
    sec = f'<h2>Resumen</h2>' + ch.div(barras2(orden, [MG[c][0] for c in orden] if M0 else None, [MG[c][1] for c in orden],
                                                  nom(M0) if M0 else '', nom(M1)), 260)
    for c in canales:
        mg0, mg1 = MG[c]
        sec += f'<h2>{H.escape(c)}</h2><p class="sub">Ingreso {nom(M1)} {mm(ING.get((c, M1), 0))} · margen {n(mg0) + "% → " if mg0 is not None else ""}<b>{n(mg1)}%</b></p><div class="two">'
        if M0:
            deltas = [(lab, X['ccp'](c, cc, M1) - X['ccp'](c, cc, M0)) for lab, cc in
                      [('Costo venta', 'Costo venta'), ('Comisión venta', 'Comisión venta'), ('Comisión envío', 'Comisión envío'), ('Marketing', 'Marketing'), ('Devolución', 'Devolución')]]
            otros = (mg1 - mg0) - sum(v for _, v in deltas)
            if abs(otros) >= 0.05:
                deltas.append(('Otros', otros))
            sec += '<div>' + ch.div(cascada([(f'Margen {nom(M0)[:3]}', mg0, 'start')] + [(l, v, 'dec') for l, v in deltas] + [(f'Margen {nom(M1)[:3]}', 0, 'total')])) + '</div>'
        mv = X['movers'](c)
        if mv:
            sec += '<div>' + ch.div(barras_h(mv)) + '</div>'
        sec += '</div>'
    html_adj = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rentabilidad por canal — semana {hoy.strftime('%d-%m')}</title><style>
body{{font-family:Arial,sans-serif;color:#1f2937;margin:0}} .wrap{{max-width:1120px;margin:0 auto;padding:24px 20px 50px}}
h1{{color:#1E3A5F;font-size:22px;margin:0 0 4px}} h2{{color:#1E3A5F;font-size:17px;margin:28px 0 6px;border-bottom:2px solid #1E3A5F;padding-bottom:3px}}
.sub{{margin:0 0 4px;font-size:13px}} .two{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} @media(max-width:820px){{.two{{grid-template-columns:1fr}}}} .chart{{width:100%}}
</style></head><body><div class="wrap"><h1>Rentabilidad por canal — {nom(M1)}{' vs ' + nom(M0) if M0 else ''}</h1>
<div class="sub">Reporte semanal · {hoy.strftime('%d-%m-%Y')} · fuente: <a href="{URL_SHEET}">planilla macro</a>. Puente del margen en p.p. del ingreso: verde suma, rojo resta.</div>{sec}</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/6.1.0/echarts.min.js"></script><script>
function fmtNum(v){{if(v==null||v==='')return '';var a=Math.abs(v);var d=(a<10&&a!==Math.round(a))?1:0;return v.toLocaleString('es-CL',{{minimumFractionDigits:d,maximumFractionDigits:d}});}}
var O={ch.js()};var R=matchMedia('(prefers-reduced-motion: reduce)').matches;
Object.keys(O).forEach(function(i){{var e=document.getElementById(i);if(!e)return;var c=echarts.init(e);var o=O[i];o.animation=!R;c.setOption(o);new ResizeObserver(function(){{c.resize();}}).observe(e);}});
</script></body></html>"""

    # ── cuerpo del mail ──
    tdl = 'padding:5px 9px;border:1px solid #d5dbe5;font-size:12.5px;vertical-align:top'
    th = lambda x, a='left': f'<th style="padding:6px 9px;border:1px solid #d5dbe5;background:#1E3A5F;color:#fff;text-align:{a};font-size:12.5px">{x}</th>'  # noqa: E731
    col_d = lambda d: ('#1E7A45' if d > 0.5 else '#C0392B' if d < -0.5 else '#64748b') if d is not None else '#64748b'  # noqa: E731
    res = ''.join(f'<tr><td style="{tdl};font-weight:600">{c}</td><td style="{tdl};text-align:right">{mm(ING.get((c, M1), 0))}</td>'
                  f'<td style="{tdl};text-align:right">{n(MG[c][0]) + "%" if MG[c][0] is not None else "—"}</td><td style="{tdl};text-align:right;font-weight:600">{n(MG[c][1])}%</td>'
                  f'<td style="{tdl};text-align:right;font-weight:600;color:{col_d(d)}">{pp(d) if d is not None else "—"}</td></tr>'
                  for c, _, _, d in sorted(ojo, key=lambda t: (t[3] if t[3] is not None else 0)))
    ojo_html = ''.join(f'<li style="margin-bottom:6px"><b>{c}</b> <span style="font-size:11px;color:#64748b">({p})</span> — {H.escape(t)}</li>' for c, p, t, _ in ojo if p != 'BAJA') or '<li>Ningún canal se movió más de 1 p.p.</li>'
    plan_rows = ''
    for _, r in plan.iterrows():
        plan_rows += (f'<tr><td style="{tdl};font-weight:600">{H.escape(str(r["ID"]))}</td><td style="{tdl}">{H.escape(str(r.get("Indicador", "")))}</td>'
                      f'<td style="{tdl};text-align:right">{H.escape(str(r.get(f"Base {PA.M_BASE}", "")))}</td><td style="{tdl};text-align:right">{H.escape(str(r.get("Valor último mes", "")))}</td>'
                      f'<td style="{tdl};white-space:nowrap">{H.escape(str(r.get("Semáforo", "")))}</td><td style="{tdl}">{H.escape(str(r.get("Responsable", "")))}</td>'
                      f'<td style="{tdl}">{H.escape(str(r.get("Fecha compromiso", "")) or "—")}</td><td style="{tdl}">{H.escape(str(r.get("Última gestión (quién / qué / cuándo)", "")) or "—")}</td></tr>')
    por_resp = {}
    for a in alert:
        por_resp.setdefault(str(a[3]) or 'Sin responsable', []).append(a)
    alert_html = ''.join(f'<li><b>{H.escape(r)}</b>: {", ".join(x[0] for x in xs)} — {H.escape("; ".join(sorted({x[4] for x in xs})))}</li>' for r, xs in por_resp.items())
    auto_html = ''.join(f'<tr><td style="{tdl}">{m}</td><td style="{tdl};font-weight:600">{c}</td><td style="{tdl}">{d}</td>'
                        f'<td style="{tdl};text-align:center">{"✅ " + str(k) if k else "⏳ falta"}</td><td style="{tdl}">{u}</td></tr>' for m, c, d, k, u in auto_rows)
    cuadre_html = ''
    for mstr, q in (cuadre or {}).items():
        cuadre_html += (f'<p style="margin:12px 0 4px">Lectura automática de <b>{nom(mstr).lower()}</b> contra la carga manual (neto, con lo que hay en la carpeta):</p><table style="border-collapse:collapse">'
                        f'<tr>{th("Canal")}{th("Automática", "right")}{th("Carga manual", "right")}{th("Dif.", "right")}{th("Sin regla", "right")}</tr>'
                        + ''.join(f'<tr><td style="{tdl};font-weight:600">{c}</td><td style="{tdl};text-align:right">{mm(r.agente) if r.agente else "sin archivo"}</td><td style="{tdl};text-align:right">{mm(r.carga) if r.carga else "sin carga"}</td>'
                                  f'<td style="{tdl};text-align:right">{mm(r.dif) if (r.agente and r.carga) else "—"}</td><td style="{tdl};text-align:right">{mm(r.sin_regla)}</td></tr>' for c, r in q.reindex(MK).fillna(0).iterrows()) + '</table>')
    h3 = 'style="color:#1E3A5F;margin:18px 0 6px"'
    body = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.5;max-width:960px">
<h2 style="color:#1E3A5F;margin:0 0 2px;font-size:19px">Rentabilidad por canal — reporte semanal {hoy.strftime('%d-%m-%Y')}</h2>
<div style="color:#64748b;font-size:12px;margin-bottom:10px">Último mes con carga de liquidaciones: <b>{nom(M1)}</b>{' · comparado con ' + nom(M0) if M0 else ''} · <a href="{URL_SHEET}">planilla macro</a> · <a href="{URL_CARPETA}">carpeta de liquidaciones</a> · adjunto: gráficos por canal</div>
<h3 {h3}>1. Resultado</h3>
<table style="border-collapse:collapse"><tr>{th('Canal')}{th('Ingreso ' + nom(M1)[:3], 'right')}{th('% Mg ' + (nom(M0)[:3] if M0 else ''), 'right')}{th('% Mg ' + nom(M1)[:3], 'right')}{th('Δ p.p.', 'right')}</tr>{res}</table>
<h3 {h3}>2. Dónde dar ojo</h3><ul style="margin:0 0 10px 18px;padding:0">{ojo_html}</ul>
<h3 {h3}>3. Seguimiento del plan de acción</h3>
<p style="margin:0 0 6px">{len(alert)} de {len(plan)} acciones necesitan gestión esta semana{f"; {sin_gestion} no tienen ninguna gestión registrada" if sin_gestion else ""}. Responsable, fecha compromiso, estado y última gestión se llenan en la pestaña <a href="{URL_SHEET}">8. Plan de acción</a>.</p>
{'<ul style="margin:0 0 10px 18px;padding:0;font-size:13px">' + alert_html + '</ul>' if alert_html else ''}
<table style="border-collapse:collapse"><tr>{th('ID')}{th('Indicador')}{th('Base', 'right')}{th('Último mes', 'right')}{th('Semáforo')}{th('Responsable')}{th('Fecha')}{th('Última gestión')}</tr>{plan_rows}</table>
<h3 {h3}>4. Estado de la automatización</h3>
<table style="border-collapse:collapse"><tr>{th('Mes')}{th('Carpeta')}{th('Qué debe estar')}{th('Archivos')}{th('Última subida')}</tr>{auto_html}</table>
{cuadre_html}
{''.join(f'<p style="margin:10px 0 0">Carga manual en curso de <b>{nom(m).lower()}</b>: {", ".join(cs)} cargados; faltan {", ".join(c for c in MK if c not in cs) or "ninguno"}.</p>' for m, cs in X['en_curso'].items())}
<p style="font-size:12px;color:#475569;margin-top:14px">Reporte automático de los lunes. La planilla se refresca los lunes 09:00 y 12:00; la pestaña de plan de acción se recalcula en la misma corrida.</p>
</div>"""
    return body, html_adj, dict(M0=M0, M1=M1, alertas=len(alert), plan=len(plan), cuadre=cuadre, en_curso=X['en_curso'])


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
    m.add_attachment(html_adj.encode('utf-8'), maintype='text', subtype='html', filename='Rentabilidad por canal - graficos.html')
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
    body, adj, info = construir(hoy, cuadrar=not a.sin_cuadre)
    Path(a.out, 'rentabilidad_semanal.html').write_text(body, encoding='utf-8')
    Path(a.out, 'rentabilidad_semanal_graficos.html').write_text(adj, encoding='utf-8')
    print(f"[reporte] {info['M1']} vs {info['M0']} · plan {info['plan']} acciones, {info['alertas']} con alerta")
    if a.no_mail:
        sys.exit(0)
    asunto = f"Rentabilidad por canal — semana {hoy.strftime('%d-%m')} · {nom(info['M1'])}: resultado, plan de acción y automatización"
    if a.enviar:
        to = [x.strip() for x in os.environ.get('RENTABILIDAD_TO', 'gabriela@unionx.cl').split(',') if x.strip()]
        cc = [x.strip() for x in os.environ.get('RENTABILIDAD_CC', 'andres@unionx.cl').split(',') if x.strip()]
    else:
        to, cc, asunto = ['andres@unionx.cl'], None, '[VISTA PREVIA] ' + asunto
    print('ENVIADO', to, cc, enviar(asunto, body, adj, to, cc))
