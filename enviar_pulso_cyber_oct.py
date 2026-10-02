#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pulso Cyber UnionX — Cyber Octubre 2026 (lun 5 → dom 11 de octubre).

Correo cada 2 horas (horas pares, 08:00 a 24:00 CLT) con el formato del Pulso de
ventas diario, más un dashboard HTML adjunto (gráficos de venta y margen por hora y
por día, filtrables por día, canal y línea de negocio).

Comparación por día del evento (Día 1 = lunes de cada Cyber), no por fecha: contra el Cyber
de octubre 2025 (lun 6 → dom 12) y el de junio 2026 (lun 1 → dom 7). Siempre "mismo tramo": el día en curso
se compara hasta la misma hora.

Meta: data/planificacion/plan_cyber_oct2026.json (venta bruta por canal, planificación
comercial). Apertura por día: la de Nicole si está cargada en "meta_dia"; si no, la curva
de cada canal en el Cyber de octubre 2025. Meta por hora: curva horaria del mismo día
del Cyber 2025.

Pre-Cyber: viernes 2, sábado 3 y domingo 4 de octubre, solo páginas web y Kitchen
Center, sin meta: van como filas "Pre" al inicio de la tabla por día (no suman al acumulado).

Fuente: RAW de ventas en parquet (histórico + mes en curso), igual que el pulso diario.

Vars de entorno:
  EMAIL_TO, EMAIL_FROM, RESEND_API_KEY, GMAIL_TOKEN_JSON, ANDRES_ODOO_PASSWORD
  CYBER_PREBORRADOR=1   asunto [PRE-BORRADOR] (el workflow además restringe EMAIL_TO a Andrés)
  CYBER_FORCE_EMAIL=1   ignora la ventana horaria
  CYBER_AHORA="YYYY-MM-DD HH:MM"  simula la hora de corte (pruebas)
  CYBER_ENSAYO=1        ensayo: usa el Cyber de junio como si fuera octubre (solo pruebas)
  CYBER_FORZAR_RANGO=1  arma y envía aunque esté fuera de las fechas (borradores)
Uso local sin enviar: python enviar_pulso_cyber_oct.py --solo-archivos <carpeta>

Nota: enviar_pulso_cyber.py (Cyber de junio) se mantiene porque otros pulsos importan de ahí
_enviar_via_gmail y fmt_m; este archivo no los toca.
"""
import base64
import io
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo('America/Santiago')
except Exception:  # Windows sin tzdata
    import pytz
    TZ = pytz.timezone('America/Santiago')
CHILE_TZ = TZ

PROJECT_ROOT = Path(os.environ.get('CYBER_ROOT') or Path(__file__).parent)
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
EMAIL_TO = [e.strip() for e in os.environ.get('EMAIL_TO', 'andres@unionx.cl').split(',') if e.strip()]
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'onboarding@resend.dev')
PREBORRADOR = os.environ.get('CYBER_PREBORRADOR', '0') == '1'
ENSAYO = os.environ.get('CYBER_ENSAYO', '0') == '1'

# ───────────────────────── configuración del evento ─────────────────────────
EVENTO = 'Cyber Octubre 2026'
DIAS = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10', '2026-10-11']
LBL = ['Día 1 · lun', 'Día 2 · mar', 'Día 3 · mié', 'Día 4 · jue', 'Día 5 · vie', 'Día 6 · sáb', 'Día 7 · dom']
LY = ['2025-10-06', '2025-10-07', '2025-10-08', '2025-10-09', '2025-10-10', '2025-10-11', '2025-10-12']
JUN = ['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04', '2026-06-05', '2026-06-06', '2026-06-07']
PRE = ['2026-10-02', '2026-10-03', '2026-10-04']
PRE_LBL = ['Pre · vie', 'Pre · sáb', 'Pre · dom']
PRE_LY = ['2025-10-03', '2025-10-04', '2025-10-05']
PRE_JUN = ['2026-05-29', '2026-05-30', '2026-05-31']
PRE_CANALES = ['UnionX web', 'Lhotse web', 'Simplit web', 'Kitchen Center']
RANGO_INICIO = datetime(2026, 10, 5, 6, 0, tzinfo=TZ)
RANGO_FIN = datetime(2026, 10, 12, 5, 59, tzinfo=TZ)     # incluye el pulso de las 00:00 del lun 12 (cierre del dom 11)
META_JSON = PROJECT_ROOT / 'data' / 'planificacion' / 'plan_cyber_oct2026.json'
SERIES = ('ty', 'ly', 'jun')
IVA = 1.19
NOM_SERIE = {'ty': 'Oct 2026', 'ly': 'Oct 2025', 'jun': 'Jun 2026'}
LINEA_DEF = {'CMR': 'Fidelización', 'El Volcan': 'Distribución', 'LATAM Pass': 'Fidelización'}


def ahora():
    v = os.environ.get('CYBER_AHORA', '').strip()
    if v:
        return datetime.strptime(v, '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
    return datetime.now(TZ)


_TOD_DATOS = {}   # día → hora de la última venta en el parquet (la fija construir())


def corte():
    """(día comercial, índice del día, hora de corte HH:MM:SS, hora int, fracción de la hora).
    Antes de las 06:00 cuenta como cierre del día anterior. Índices: pre-Cyber −3..−1,
    Cyber 0..6, 7 = Cyber terminado, −4 = antes del pre-Cyber."""
    a = ahora()
    dia = a if a.hour >= 6 else a - timedelta(days=1)
    dia_s = dia.strftime('%Y-%m-%d')
    cierre = dia_s != a.strftime('%Y-%m-%d')
    if dia_s in DIAS:
        idx = DIAS.index(dia_s)
    elif dia_s in PRE:
        idx = PRE.index(dia_s) - 3
    elif dia_s > DIAS[-1]:
        idx = 7
    else:
        idx = -4
    tod = '23:59:59' if cierre else a.strftime('%H:%M:%S')
    # Si el dato llega hasta antes del corte (parquet atrasado), se compara hasta la última
    # venta registrada: si no, los otros Cyber sumarían horas que hoy todavía no están.
    ult = _TOD_DATOS.get(dia_s)
    if ult and ult < tod:
        tod = ult
    h = int(tod[:2])
    frac = 1.0 if tod >= '23:59' else int(tod[3:5]) / 60
    return dia_s, idx, tod, h, frac, a


def hoy_comercial():
    return corte()[0]


def _check_rango():
    a = ahora()
    if a < RANGO_INICIO or a > RANGO_FIN:
        print(f"[SKIP] {a:%Y-%m-%d %H:%M} fuera del Cyber ({RANGO_INICIO:%d-%m %H:%M} → {RANGO_FIN:%d-%m %H:%M})", flush=True)
        return False
    return True


# ───────────────────────── datos ─────────────────────────
COLS = ['fecha_venta', 'hora_venta', 'tipo_movimiento', 'canal', 'tipo_negocio', 'marca', 'categoria_hijo', 'pedido',
        'sku', 'producto', 'bodega', 'cantidad', 'venta_bruta', 'venta_neta', 'margen_front',
        'comision', 'logistica', 'marketing', 'margen_final']
NUM = ['cantidad', 'venta_bruta', 'venta_neta', 'margen_front', 'comision', 'logistica', 'marketing', 'margen_final']


def cargar_ventas():
    """Histórico + mes en curso (solo los días posteriores al último del histórico: evita doble conteo)."""
    import pyarrow.parquet as pq
    hp = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
    mp = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
    partes = []
    for p in (hp, mp):
        if p.exists():
            cols = [c for c in COLS if c in pq.read_schema(p).names]
            partes.append(pd.read_parquet(p, columns=cols))
    h = partes[0]
    h['fv'] = pd.to_datetime(h['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    df = h
    if len(partes) > 1:
        m = partes[1]
        m['fv'] = pd.to_datetime(m['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
        m = m[m['fv'] > h['fv'].max()]
        df = pd.concat([h, m], ignore_index=True)
    fechas = set(DIAS + LY + JUN + PRE + PRE_LY + PRE_JUN)
    df = df[df['fv'].isin(fechas)].copy()
    for c in NUM:
        df[c] = pd.to_numeric(df.get(c, 0), errors='coerce').fillna(0.0)
    t = df['hora_venta'].astype(str).str.strip()
    t = t.where(t.str.match(r'^\d{1,2}:\d{2}'), '00:00:00')
    df['tod'] = t.str.zfill(8).str[:8]
    df['h'] = df['tod'].str[:2].astype(int)
    for c in ('canal', 'tipo_negocio', 'marca', 'categoria_hijo'):
        df[c] = df[c].fillna('').astype(str).str.strip()
    return df


def series(df):
    """{serie: df con columna d (−3..6)}. Pre-Cyber solo webs + Kitchen Center."""
    mapas = {'ty': dict(zip(DIAS, range(7))) | dict(zip(PRE, range(-3, 0))),
             'ly': dict(zip(LY, range(7))) | dict(zip(PRE_LY, range(-3, 0))),
             'jun': dict(zip(JUN, range(7))) | dict(zip(PRE_JUN, range(-3, 0)))}
    if ENSAYO:
        mapas['ty'] = mapas['jun']
    out = {}
    for s, mp in mapas.items():
        x = df[df['fv'].isin(mp)].copy()
        x['d'] = x['fv'].map(mp)
        x = x[(x['d'] >= 0) | x['canal'].isin(PRE_CANALES)]
        out[s] = x
    return out


def en_tramo(x, idx, tod):
    """Mismo tramo: días anteriores completos + el día en curso hasta la hora de corte."""
    return (x['d'] < idx) | ((x['d'] == idx) & (x['tod'] <= tod))


# ───────────────────────── metas ─────────────────────────
def cargar_metas(S, lineas_canal):
    """Meta bruta por canal × día × hora. Devuelve (DataFrame d,h,canal,linea,meta, info)."""
    plan = json.loads(META_JSON.read_text(encoding='utf-8'))
    mc = {k: float(v) for k, v in plan['metas_canal'].items()}
    ly = S['ly'][(S['ly']['d'] >= 0) & (S['ly']['tipo_movimiento'] == 'Venta')]
    tot_d = ly.groupby('d')['venta_bruta'].sum().reindex(range(7), fill_value=0)
    share_tot = tot_d / tot_d.sum()
    filas = []
    for canal, meta in mc.items():
        x = ly[ly['canal'] == canal].groupby('d')['venta_bruta'].sum().reindex(range(7), fill_value=0)
        sh = (x / x.sum()) if x.sum() >= 1e6 else share_tot
        for d in range(7):
            filas.append((canal, d, meta * float(sh[d])))
    cd = pd.DataFrame(filas, columns=['canal', 'd', 'meta'])
    fuente_dia = 'curva de cada canal en el Cyber oct-2025'
    md = plan.get('meta_dia') or []
    if len(md) == 7:
        f = pd.Series(md, index=range(7), dtype=float) / cd.groupby('d')['meta'].sum()
        cd['meta'] = cd['meta'] * cd['d'].map(f)
        fuente_dia = 'apertura por día cargada'
    # Grupos con meta propia por día en venta NETA (ej. Nicole, Marketplace + Fidelización):
    # cada día del grupo se reescala a esa meta × 1,19 (bruto, como el RAW); dentro del día se
    # reparte entre los canales del grupo según su peso (planilla + curva del canal).
    notas = []
    for nombre, g in (plan.get('grupos') or {}).items():
        mdn = g.get('meta_dia_neta') or []
        sel = cd['canal'].isin(g.get('canales', []))
        if len(mdn) == 7 and sel.any():
            obj = pd.Series(mdn, index=range(7), dtype=float) * IVA
            base = cd[sel].groupby('d')['meta'].sum()
            cd.loc[sel, 'meta'] = cd.loc[sel, 'meta'] * cd.loc[sel, 'd'].map(obj / base)
            notas.append(f"{nombre}: {fmt_m(sum(mdn))} neta → {fmt_m(sum(mdn) * IVA)} bruta, apertura por día del área")
        elif sel.any():
            notas.append(f"{nombre}: {fmt_m(cd.loc[sel, 'meta'].sum())} bruta de la planilla, por día con la curva de cada canal en oct-2025")
    if notas:
        fuente_dia = ' · '.join(notas)
    mc = cd.groupby('canal')['meta'].sum().to_dict()
    # curva horaria del mismo día del Cyber 2025 (toda la empresa)
    hh = ly.groupby(['d', 'h'])['venta_bruta'].sum().clip(lower=0)
    hh = (hh / hh.groupby(level=0).transform('sum')).rename('sh').reset_index()
    m = cd.merge(hh, on='d', how='left')
    m['meta'] = m['meta'] * m['sh'].fillna(0)
    m['linea'] = m['canal'].map(lineas_canal).fillna(m['canal'].map(LINEA_DEF)).fillna('Otros')
    info = {'total': sum(mc.values()), 'total_planilla': None if plan.get('grupos') else plan.get('total_general_planilla'),
            'fuente': plan.get('fuente', ''), 'fuente_dia': fuente_dia, 'canales': mc}
    return m[['d', 'h', 'canal', 'linea', 'meta']], info


def meta_tramo(M, idx, h, frac):
    """Meta hasta el corte (días anteriores completos + horas del día en curso, la última prorrateada)."""
    w = pd.Series(0.0, index=M.index)
    w[M['d'] < idx] = 1.0
    hoy = M['d'] == idx
    w[hoy & (M['h'] < h)] = 1.0
    w[hoy & (M['h'] == h)] = frac
    return M['meta'] * w


def curva_acumulada(S, idx, tod):
    """% de la venta del día equivalente del Cyber 2025 hecho al corte (para proyectar el cierre)."""
    if not 0 <= idx <= 6:
        return None
    x = S['ly'][(S['ly']['d'] == idx) & (S['ly']['tipo_movimiento'] == 'Venta')]
    t = x['venta_bruta'].sum()
    return float(x.loc[x['tod'] <= tod, 'venta_bruta'].sum() / t) if t > 0 else None


# ───────────────────────── formato ─────────────────────────
def fmt_m(v):
    if v is None or v == 0:
        return '$0'
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:,.1f} M".replace(',', 'X').replace('.', ',').replace('X', '.')
    if abs(v) >= 1_000:
        return f"${v / 1_000:,.0f} K".replace(',', '.')
    return f"${v:,.0f}".replace(',', '.')


def ent(v):
    return f"{int(round(v)):,}".replace(',', '.')


def pct(v, d=1):
    return f"{v:,.{d}f}%".replace(',', 'X').replace('.', ',').replace('X', '.')


def var_cell(ty, ref):
    if not ref or ref <= 0:
        return '<td align="right" style="color:#94A3B8">—</td>'
    v = (ty / ref - 1) * 100
    c = '#16A34A' if v >= 0 else '#DC2626'
    return f'<td align="right" style="color:{c};font-weight:600">{"+" if v >= 0 else ""}{pct(v)}</td>'


def meta_cell(ty, meta):
    if not meta:
        return '<td align="right">—</td><td align="right" style="color:#94A3B8">—</td>'
    p = ty / meta * 100
    c = '#16A34A' if p >= 100 else ('#EA580C' if p >= 80 else '#DC2626')
    return f'<td align="right">{fmt_m(meta)}</td><td align="right" style="color:{c};font-weight:600">{pct(p)}</td>'


def agg(x, by=None):
    cols = dict(sos=('pedido', 'nunique'), uds=('cantidad', 'sum'), bruta=('venta_bruta', 'sum'),
                neta=('venta_neta', 'sum'), margen=('margen_front', 'sum'))
    if by is None:
        return pd.Series({k: (x[c].nunique() if f == 'nunique' else x[c].sum()) for k, (c, f) in cols.items()})
    return x.groupby(by).agg(**cols)


def pm(r):
    return r['margen'] / r['neta'] * 100 if r['neta'] else 0


TH = 'style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"'


def tabla(cab, filas):
    th = ''.join(f'<th align="{"left" if i == 0 else "right"}">{c}</th>' for i, c in enumerate(cab))
    return (f'<table style="width:100%;border-collapse:collapse;font-size:0.83rem"><thead><tr {TH}>{th}</tr></thead>'
            f'<tbody>{"".join(filas)}</tbody></table>')


# ───────────────────────── correo ─────────────────────────
def render_html(S, M, info, lineas_canal, alarma_stock):
    dia_s, idx, tod, h, frac, a = corte()
    T = {s: S[s][en_tramo(S[s], idx, tod)] for s in SERIES}
    cy = {s: T[s][T[s]['d'] >= 0] for s in SERIES}
    pre = {s: T[s][T[s]['d'] < 0] for s in SERIES}
    M = M.assign(mt=meta_tramo(M, idx, h, frac))
    en_cyber = idx >= 0
    n_dias = min(max(idx + 1, 0), 7)

    # ── cabecera
    tot = {s: agg(cy[s]) for s in SERIES}
    b, n, mg = tot['ty']['bruta'], tot['ty']['neta'], tot['ty']['margen']
    meta_tot, meta_corte = info['total'], M['mt'].sum()
    dev = cy['ty'].loc[cy['ty']['tipo_movimiento'] == 'Devolución', 'venta_bruta'].sum()
    hoy_b = cy['ty'].loc[cy['ty']['d'] == idx, 'venta_bruta'].sum() if 0 <= idx <= 6 else 0
    meta_hoy = M.loc[M['d'] == idx, 'meta'].sum() if 0 <= idx <= 6 else 0
    meta_hoy_corte = M.loc[M['d'] == idx, 'mt'].sum() if 0 <= idx <= 6 else 0
    share_ly = curva_acumulada(S, idx, tod)
    proy_hoy = hoy_b / share_ly if share_ly and share_ly >= 0.05 else None
    col = lambda v: '#16A34A' if v >= 100 else ('#EA580C' if v >= 80 else '#DC2626')  # noqa: E731
    p_corte = b / meta_corte * 100 if meta_corte else 0
    if en_cyber:
        estado = (f'Día {n_dias} de 7 · corte {a:%d-%b %H:%M} · datos hasta las {tod[:5]}' if idx <= 6 else 'Cyber terminado')
    else:
        estado = f'Pre-Cyber · corte {a:%d-%b %H:%M} · datos hasta las {tod[:5]} · el Cyber parte el lun 5-oct'
    hoy_txt = ''
    if 0 <= idx <= 6:
        p_hoy = hoy_b / meta_hoy_corte * 100 if meta_hoy_corte else 0
        hoy_txt = (f'<br><b>{LBL[idx]}:</b> {fmt_m(hoy_b)} · meta del día {fmt_m(meta_hoy)} · meta al corte {fmt_m(meta_hoy_corte)} '
                   f'(<b style="color:{col(p_hoy)}">{pct(p_hoy)}</b>)'
                   + (f' · proyección de cierre del día {fmt_m(proy_hoy)} ({pct(proy_hoy / meta_hoy * 100 if meta_hoy else 0)} de la meta), '
                      f'con la curva del día {idx + 1} del Cyber oct-2025' if proy_hoy else ''))
    box_acum = f"""
<div style="background:#F1F5F9;border-left:4px solid #2563EB;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Acumulado {EVENTO} (venta bruta)</div>
  <div style="font-size:1.7rem;font-weight:700;color:#1E40AF;margin:2px 0">{fmt_m(b)} <span style="font-size:0.95rem;font-weight:600;color:#64748B">bruta · {fmt_m(n)} neta</span></div>
  <div style="font-size:0.88rem;color:#64748B">
    Meta Cyber {fmt_m(meta_tot)} · avance <b>{pct(b / meta_tot * 100 if meta_tot else 0)}</b> · meta al corte {fmt_m(meta_corte)} (<b style="color:{col(p_corte)}">{pct(p_corte)}</b>) · gap al corte {fmt_m(b - meta_corte)}<br>
    Margen directo {fmt_m(mg)} ({pct(pm(tot['ty']))}) · {ent(tot['ty']['uds'])} uds · {ent(tot['ty']['sos'])} pedidos · devoluciones {fmt_m(dev)}{hoy_txt}
  </div>
</div>"""

    # ── comparación mismo tramo
    rng = (f'día 1 → día {min(idx, 6) + 1}, hasta las {tod[:5]} del día en curso' if en_cyber else 'aún no parte')
    vs_ly = (tot['ty']['bruta'] / tot['ly']['bruta'] - 1) * 100 if tot['ly']['bruta'] else 0
    vs_jun = (tot['ty']['bruta'] / tot['jun']['bruta'] - 1) * 100 if tot['jun']['bruta'] else 0
    vs_ly_m = (tot['ty']['margen'] / tot['ly']['margen'] - 1) * 100 if tot['ly']['margen'] else 0
    vs_jun_m = (tot['ty']['margen'] / tot['jun']['margen'] - 1) * 100 if tot['jun']['margen'] else 0
    cl = lambda v: '#16A34A' if v >= 0 else '#DC2626'  # noqa: E731
    sg = lambda v: '+' if v >= 0 else ''  # noqa: E731
    box_cmp = f"""
<div style="background:#FEF3C7;border-left:4px solid #EA580C;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">📊 Comparación mismo tramo ({rng})</div>
  <table style="width:100%;margin-top:6px;font-size:0.88rem">
    <tr><td>Cyber oct 2026:</td><td align="right"><b>{fmt_m(tot['ty']['bruta'])}</b> bruta · {fmt_m(tot['ty']['margen'])} margen ({pct(pm(tot['ty']))})</td></tr>
    <tr><td>Cyber oct 2025 (mismos días del evento):</td><td align="right">{fmt_m(tot['ly']['bruta'])} bruta · {fmt_m(tot['ly']['margen'])} margen ({pct(pm(tot['ly']))})</td></tr>
    <tr><td>Cyber jun 2026 (mismos días del evento):</td><td align="right">{fmt_m(tot['jun']['bruta'])} bruta · {fmt_m(tot['jun']['margen'])} margen ({pct(pm(tot['jun']))})</td></tr>
    <tr style="border-top:1px solid #E2E8F0"><td>vs oct 2025:</td><td align="right">Venta <span style="color:{cl(vs_ly)};font-weight:600">{sg(vs_ly)}{pct(vs_ly)}</span> · Margen <span style="color:{cl(vs_ly_m)};font-weight:600">{sg(vs_ly_m)}{pct(vs_ly_m)}</span></td></tr>
    <tr><td>vs jun 2026:</td><td align="right">Venta <span style="color:{cl(vs_jun)};font-weight:600">{sg(vs_jun)}{pct(vs_jun)}</span> · Margen <span style="color:{cl(vs_jun_m)};font-weight:600">{sg(vs_jun_m)}{pct(vs_jun_m)}</span></td></tr>
  </table>
</div>"""

    # ── margen final (devengo)
    x = cy['ty']
    com, log, mkt, mfin = x['comision'].sum(), x['logistica'].sum(), x['marketing'].sum(), x['margen_final'].sum()
    box_mfin = (f"""
<div style="background:#F0FDF4;border-left:4px solid #16A34A;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#166534;text-transform:uppercase;letter-spacing:0.05em">💰 Margen Final (contribución directa)</div>
  <div style="font-size:1.5rem;font-weight:700;color:#15803D;margin:2px 0">{fmt_m(mfin)} <span style="font-size:0.9rem;font-weight:600;color:#64748B">({pct(mfin / n * 100 if n else 0)} s/neta)</span></div>
  <div style="font-size:0.85rem;color:#64748B">Margen directo {fmt_m(mg)} − Comisión {fmt_m(com)} − Logística {fmt_m(log)} − Marketing {fmt_m(mkt)} = <b>Margen Final {fmt_m(mfin)}</b></div>
</div>""" if n else '')

    # ── por día (alineado por día del evento: Día 1 = lunes de cada Cyber)
    dia_rows = []
    vd = {s: agg(T[s][T[s]['d'] >= 0], 'd') for s in SERIES}          # mismo tramo (el día en curso, al corte)
    full = {s: S[s][S[s]['d'] >= 0].groupby('d')['venta_bruta'].sum() for s in ('ly', 'jun')}
    md = M.groupby('d')['meta'].sum()
    # pre-Cyber (vie, sáb, dom previos): solo páginas web + Kitchen Center, sin meta
    vp = {s: agg(pre[s], 'd') for s in SERIES}
    for d, lbl in zip(range(-3, 0), PRE_LBL):
        if d not in vp['ty'].index:
            continue
        r = vp['ty'].loc[d]
        ref = {s: (vp[s].loc[d]['bruta'] if d in vp[s].index else 0) for s in ('ly', 'jun')}
        dia_rows.append(f'<tr style="background:#FAFAF9"><td>{lbl} <span style="color:#94A3B8;font-size:0.75rem">webs + KC</span></td><td align="right">{ent(r["sos"])}</td>'
                        + f'<td align="right">{ent(r["uds"])}</td>'
                        + f'<td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pct(pm(r))}</td>'
                        + '<td align="right" style="color:#94A3B8">sin meta</td><td align="right">—</td>'
                        + f'<td align="right">{fmt_m(ref["ly"])}</td>' + var_cell(r['bruta'], ref['ly'])
                        + f'<td align="right">{fmt_m(ref["jun"])}</td>' + var_cell(r['bruta'], ref['jun']) + '</tr>')
    for d in range(7):
        r = vd['ty'].loc[d] if d in vd['ty'].index else None
        ref = {s: (vd[s].loc[d]['bruta'] if d in vd[s].index else 0) for s in ('ly', 'jun')}
        if r is None or d > idx:
            dia_rows.append(f'<tr style="color:#94A3B8"><td>{LBL[d]}</td>' + '<td align="right">—</td>' * 5
                            + f'<td align="right">{fmt_m(md.get(d, 0))}</td><td align="right">—</td>'
                            + f'<td align="right">{fmt_m(full["ly"].get(d, 0))}</td><td align="right">—</td>'
                            + f'<td align="right">{fmt_m(full["jun"].get(d, 0))}</td><td align="right">—</td></tr>')
            continue
        al_corte = d == idx and tod < '23:59'
        dia_rows.append(f'<tr><td>{LBL[d]}{" (al corte)" if al_corte else ""}</td><td align="right">{ent(r["sos"])}</td>'
                        + f'<td align="right">{ent(r["uds"])}</td>'
                        + f'<td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pct(pm(r))}</td>'
                        + meta_cell(r['bruta'], md.get(d, 0) if d < idx else M.loc[M['d'] == d, 'mt'].sum())
                        + f'<td align="right">{fmt_m(ref["ly"])}</td>' + var_cell(r['bruta'], ref['ly'])
                        + f'<td align="right">{fmt_m(ref["jun"])}</td>' + var_cell(r['bruta'], ref['jun']) + '</tr>')
    sec_dia = (f'<h3 style="margin:24px 0 8px 0;font-size:1rem">📅 Por día del Cyber — oct 2026 vs oct 2025 vs jun 2026</h3>'
               + tabla(['Día', 'SOs', 'Uds', 'Bruta', 'Margen', '%M', 'Meta', '%Meta', 'Oct-25', 'vs', 'Jun-26', 'vs'], dia_rows)
               + '<p style="font-size:0.78rem;color:#64748B;margin:4px 0 0">Se compara por día del evento, no por fecha: Día 1 es el lunes de cada Cyber '
               '(oct-26 lun 5 · oct-25 lun 6 · jun-26 lun 1). Las filas "Pre" son el viernes, sábado y domingo previos a cada Cyber, solo páginas web '
               'y Kitchen Center, sin meta (no suman al acumulado del Cyber). El día en curso se compara hasta la misma hora; los días por venir '
               'muestran, en gris, la meta y el día completo de los otros Cyber.</p>') if en_cyber else ''

    # ── por hora (día en curso)
    sec_hora = ''
    if 0 <= idx <= 6:
        def por_h(s):
            z = S[s][(S[s]['d'] == idx)]
            return z.groupby('h')['venta_bruta'].sum()
        hty, hly, hjun = por_h('ty'), por_h('ly'), por_h('jun')
        hm = M[M['d'] == idx].groupby('h')['meta'].sum()
        filas, acum, acum_m = [], 0, 0
        for hh in range(0, h + 1):
            v = float(hty.get(hh, 0))
            mt = float(hm.get(hh, 0)) * (frac if hh == h else 1)
            acum += v
            acum_m += mt
            filas.append(f'<tr><td>{hh:02d}:00{" (en curso)" if hh == h and frac < 1 else ""}</td><td align="right">{fmt_m(v)}</td>'
                         f'<td align="right">{fmt_m(mt)}</td><td align="right">{fmt_m(acum)}</td>'
                         + f'<td align="right">{fmt_m(acum_m)}</td>'
                         f'<td align="right" style="color:{col(acum / acum_m * 100 if acum_m else 0)};font-weight:600">{pct(acum / acum_m * 100 if acum_m else 0)}</td>'
                         f'<td align="right">{fmt_m(hly.get(hh, 0))}</td><td align="right">{fmt_m(hjun.get(hh, 0))}</td></tr>')
        sec_hora = (f'<h3 style="margin:24px 0 8px 0;font-size:1rem">⏱️ Por hora — {LBL[idx]}</h3>'
                    + tabla(['Hora', 'Venta', 'Meta hora', 'Acumulado', 'Meta acum.', '%Meta acum.', f'Oct-25 día {idx + 1}', f'Jun-26 día {idx + 1}'], filas)
                    + '<p style="font-size:0.78rem;color:#64748B;margin:4px 0 0">Meta por hora = meta del día repartida con la curva horaria del mismo día del Cyber 2025.</p>')

    # ── por línea de negocio y por canal (acumulado Cyber, mismo tramo)
    M_lin = M.groupby('linea')['mt'].sum()
    M_can = M.groupby('canal')['mt'].sum()

    def bloque(col_, titulo, metas, top=None, con_meta=True):
        g = {s: agg(cy[s], col_) for s in SERIES}
        ty = g['ty'].sort_values('bruta', ascending=False)
        if top:
            ty = ty.head(top)
        filas = []
        for k, r in ty.iterrows():
            ly_r = g['ly'].loc[k] if k in g['ly'].index else None
            jn_r = g['jun'].loc[k] if k in g['jun'].index else None
            celdas = (f'<tr><td>{str(k or "—")[:26]}</td><td align="right">{ent(r["sos"])}</td>'
                      + f'<td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pct(pm(r))}</td>')
            if con_meta:
                celdas += meta_cell(r['bruta'], metas.get(k, 0))
            celdas += (var_cell(r['bruta'], ly_r['bruta'] if ly_r is not None else 0) + var_cell(r['margen'], ly_r['margen'] if ly_r is not None else 0)
                       + var_cell(r['bruta'], jn_r['bruta'] if jn_r is not None else 0) + var_cell(r['margen'], jn_r['margen'] if jn_r is not None else 0) + '</tr>')
            filas.append(celdas)
        if col_ == 'tipo_negocio':
            t_ = tot['ty']
            filas.append(f'<tr style="font-weight:700;background:#F8FAFC"><td>TOTAL</td><td align="right">{ent(t_["sos"])}</td>'
                         + f'<td align="right">{fmt_m(t_["bruta"])}</td><td align="right">{fmt_m(t_["margen"])}</td><td align="right">{pct(pm(t_))}</td>'
                         + meta_cell(t_['bruta'], meta_corte) + var_cell(t_['bruta'], tot['ly']['bruta']) + var_cell(t_['margen'], tot['ly']['margen'])
                         + var_cell(t_['bruta'], tot['jun']['bruta']) + var_cell(t_['margen'], tot['jun']['margen']) + '</tr>')
        cab = ['', 'SOs', 'Bruta', 'Margen', '%M'] + (['Meta al corte', '%Meta'] if con_meta else []) + ['vs oct-25 Vta', 'vs oct-25 Mg', 'vs jun-26 Vta', 'vs jun-26 Mg']
        cab[0] = titulo
        return tabla(cab, filas)

    sec_lin = sec_can = sec_mar = sec_cat = ''
    if en_cyber and len(cy['ty']):
        sec_lin = '<h3 style="margin:24px 0 8px 0;font-size:1rem">🏢 Por línea de negocio (acumulado Cyber, mismo tramo)</h3>' + bloque('tipo_negocio', 'Línea de negocio', M_lin.to_dict())
        sec_can = '<h3 style="margin:24px 0 8px 0;font-size:1rem">🏆 Top 15 canales (acumulado Cyber, mismo tramo)</h3>' + bloque('canal', 'Canal', M_can.to_dict(), top=15)
        sec_mar = '<h3 style="margin:24px 0 8px 0;font-size:1rem">🏷️ Top 10 marcas</h3>' + bloque('marca', 'Marca', {}, top=10, con_meta=False)
        sec_cat = '<h3 style="margin:24px 0 8px 0;font-size:1rem">📂 Top 10 categorías</h3>' + bloque('categoria_hijo', 'Categoría', {}, top=10, con_meta=False)

    # ── alarma de stock
    sec_stock = ''
    if alarma_stock:
        filas = [f'<tr><td>{x["sku"]}</td><td>{x["producto"]}</td><td align="right">{ent(x["disp"])}</td>'
                 + f'<td align="right">{x["vta_diaria"]:.1f}</td><td align="right">{x["dias_cob"]:.1f}</td></tr>' for x in alarma_stock]
        sec_stock = ('<h3 style="margin:24px 0 8px 0;font-size:1rem">🚨 Alarma de stock (cobertura &lt; 7 días)</h3>'
                     + tabla(['SKU', 'Producto', 'Disponible', 'Vta diaria', 'Días cob.'], filas))

    banner = ('<div style="background:#FEE2E2;border-left:4px solid #DC2626;padding:10px 12px;border-radius:6px;margin:12px 0;font-size:0.88rem;color:#991B1B">'
              '<b>ENSAYO:</b> la serie "oct 2026" usa la venta del Cyber de junio para probar el formato. No son datos reales de octubre.</div>') if ENSAYO else ''
    nota_meta = (f'Meta (venta bruta): {info["fuente_dia"]}. '
                 + (f'La suma por canal ({fmt_m(info["total"])}) no coincide con el "Total general" de la planilla ({fmt_m(info["total_planilla"])}).'
                    if info.get('total_planilla') and abs(info['total'] - info['total_planilla']) > 10 else ''))
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body style="font-family:-apple-system,Segoe UI,sans-serif;max-width:900px;margin:auto;color:#1E293B">
<h2 style="margin:0 0 4px 0">🛍️ Pulso {EVENTO}</h2>
<p style="color:#64748B;margin:0 0 16px 0;font-size:0.9rem">{estado}</p>
{banner}
{box_acum if en_cyber else ''}
{box_cmp if en_cyber else ''}
{box_mfin if en_cyber else ''}
{sec_dia}
{sec_hora}
{sec_lin}
{sec_can}
{sec_mar}
{sec_cat}
{sec_stock}
<hr style="border:none;border-top:1px solid #E2E8F0;margin:24px 0">
<p style="font-size:0.85rem;color:#64748B">
📈 Adjunto: <b>dashboard</b> con venta y margen por hora y por día, filtrable por día, canal y línea de negocio.<br>
📎 Adjunto: Excel RAW del día.<br>
🔗 Dashboard live: <a href="https://unionx-ventas.streamlit.app">unionx-ventas.streamlit.app</a><br>
{nota_meta}<br>
Venta bruta con IVA, como el RAW de ventas. Margen = margen directo (venta neta − costo). Comparación siempre en el mismo tramo.
</p>
<style>td,th{{padding:6px 8px;border-bottom:1px solid #E2E8F0}}</style>
</body></html>"""
    return html, b, hoy_b, (b / meta_tot if meta_tot else 0)


# ───────────────────────── dashboard HTML (adjunto) ─────────────────────────
def render_dashboard(S, M, info):
    dia_s, idx, tod, h, frac, a = corte()
    canales = sorted({c for s in SERIES for c in S[s]['canal'].unique()} | set(M['canal']))
    lineas = sorted({l for s in SERIES for l in S[s]['tipo_negocio'].unique()} | set(M['linea']))
    ci = {c: i for i, c in enumerate(canales)}
    li = {l: i for i, l in enumerate(lineas)}
    rows = []
    for si, s in enumerate(SERIES):
        x = S[s].copy()
        if s == 'ty':
            x = x[en_tramo(x, idx, tod)]
        x['t'] = en_tramo(x, idx, tod).astype(int)
        g = x.groupby(['d', 'h', 'canal', 'tipo_negocio', 't'])[['venta_bruta', 'margen_front', 'venta_neta']].sum().reset_index()
        for r in g.itertuples(index=False):
            rows.append([si, int(r.d), int(r.h), ci[r.canal], li[r.tipo_negocio], int(r.t),
                         round(r.venta_bruta), round(r.margen_front), round(r.venta_neta)])
    metas = [[int(r.d), int(r.h), ci[r.canal], li[r.linea], round(r.meta)] for r in M.itertuples(index=False) if r.meta > 0]
    dias_lbl = PRE_LBL + LBL
    D = {'rows': rows, 'metas': metas, 'canales': canales, 'lineas': lineas, 'dias': dias_lbl,
         'corte': {'d': idx, 'h': h, 'frac': round(frac, 3), 'txt': a.strftime('%d-%m %H:%M')},
         'series': [NOM_SERIE[s] for s in SERIES], 'ensayo': ENSAYO}
    sel_dia = ('<option value="cyber">Cyber completo (día 1 → día 7)</option><option value="pre">Pre-Cyber (vie, sáb, dom previos)</option>'
               + ''.join(f'<option value="{d}">{l}</option>' for d, l in zip(range(-3, 7), dias_lbl)))
    default_dia = str(idx) if -3 <= idx <= 6 else 'cyber'
    return TPL_DASH.replace('@@DATA@@', json.dumps(D, ensure_ascii=False, separators=(',', ':'))) \
        .replace('@@SEL_DIA@@', sel_dia).replace('@@DEF_DIA@@', default_dia) \
        .replace('@@EVENTO@@', EVENTO).replace('@@CORTE@@', a.strftime('%d-%m-%Y %H:%M')) \
        .replace('@@META@@', fmt_m(info['total'])) \
        .replace('@@ENSAYO@@', '<div class="ensayo">ENSAYO: la serie "Oct 2026" usa la venta del Cyber de junio para probar el formato.</div>' if ENSAYO else '')


TPL_DASH = r"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard Cyber UnionX</title>
<style>
:root{--bg:#0A1424;--panel:#101D33;--line:#1E2E4A;--ink:#E6EDF7;--mut:#8397B5;--ty:#3987e5;--ly:#d95926;--jun:#199e70;--meta:#8397B5;--pos:#22C55E;--neg:#EF4444}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;font-size:13px}
.wrap{max-width:1500px;margin:0 auto;padding:18px 22px 30px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:12px;flex-wrap:wrap}
h1{margin:0;font-size:24px} h1 span{color:var(--ty)} .sub{color:var(--mut);font-size:12.5px;margin-top:3px}
.filters{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 12px}
.filters label{display:flex;flex-direction:column;gap:4px;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
select{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font-size:13px;min-width:220px}
select:focus-visible{outline:2px solid var(--ty);outline-offset:1px}
.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px 15px}
.kt{color:var(--mut);font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.kv{font-size:24px;font-weight:700;margin-top:6px} .kx{color:var(--mut);font-size:11.5px;margin-top:5px;line-height:1.45}
.pos{color:var(--pos)} .neg{color:var(--neg)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;min-width:0}
.pt{font-size:13.5px;font-weight:700;margin-bottom:2px} .ps{color:var(--mut);font-size:11px;margin-bottom:6px}
.ch{width:100%;height:290px}
.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--mut);font-size:11.5px;margin:0 0 10px}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
.legend i.dash{background:repeating-linear-gradient(90deg,var(--meta) 0 4px,transparent 4px 7px);height:2px}
.tw{overflow-x:auto} table{width:100%;border-collapse:collapse;font-size:12.5px}
th{color:var(--mut);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;text-align:right;padding:6px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left} td{padding:6px;border-bottom:1px solid var(--line)}
.n{text-align:right;font-variant-numeric:tabular-nums;font-family:Consolas,'Cascadia Mono',monospace;font-size:12px}
.mut{color:var(--mut)} .ensayo{background:#3B1219;border:1px solid #7F1D1D;color:#FCA5A5;border-radius:8px;padding:8px 12px;margin-bottom:10px}
footer{color:var(--mut);font-size:11px;line-height:1.5;margin-top:6px}
@media(max-width:1100px){.cards{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
@media(max-width:560px){.wrap{padding:14px 16px}.cards{grid-template-columns:1fr}select{min-width:0;width:100%}.filters label{flex:1 1 100%}}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
</style></head><body><div class="wrap">
<header><div><h1>Dashboard <span>@@EVENTO@@</span></h1>
<div class="sub">Venta bruta (con IVA) y margen directo · corte @@CORTE@@ · meta Cyber @@META@@ · comparación por día del evento (Día 1 = lunes de cada Cyber) contra el Cyber oct 2025 y el Cyber jun 2026</div></div></header>
@@ENSAYO@@
<div class="filters" role="group" aria-label="Filtros">
 <label>Día<select id="f_dia">@@SEL_DIA@@</select></label>
 <label>Canal<select id="f_canal"></select></label>
 <label>Línea de negocio<select id="f_linea"></select></label>
</div>
<div class="legend"><span><i style="background:var(--ty)"></i>Oct 2026</span><span><i style="background:var(--ly)"></i>Oct 2025</span><span><i style="background:var(--jun)"></i>Jun 2026</span><span><i class="dash"></i>Meta Oct 2026</span></div>
<div class="cards" id="cards"></div>
<div class="grid">
 <div class="panel"><div class="pt">Venta por hora</div><div class="ps" id="ps_hv"></div><div id="c_hv" class="ch"></div></div>
 <div class="panel"><div class="pt">Margen directo por hora</div><div class="ps" id="ps_hm"></div><div id="c_hm" class="ch"></div></div>
</div>
<div class="grid">
 <div class="panel"><div class="pt">Venta por día</div><div class="ps">Por día del evento · pre-Cyber (vie, sáb, dom) y días 1 a 7 · la marca gris es la meta del día · el día en curso va al corte</div><div id="c_dv" class="ch"></div></div>
 <div class="panel"><div class="pt">Margen directo por día</div><div class="ps">Mismos días y filtros</div><div id="c_dm" class="ch"></div></div>
</div>
<div class="panel"><div class="pt">Tabla por día</div><div class="ps">Mismos filtros · Oct 2025 y Jun 2026 muestran el día completo; la variación del día en curso se calcula al mismo tramo</div><div class="tw"><table id="tabla"></table></div></div>
<footer>Las tres series se alinean por día del evento, no por fecha: Día 1 es el lunes de cada Cyber (oct-26 lun 5 · oct-25 lun 6 · jun-26 lun 1); pre-Cyber = viernes, sábado y domingo previos. Las curvas de oct 2025 y jun 2026 son el día completo; las tarjetas comparan el mismo tramo (hasta la hora de corte en el día en curso). Meta por hora = meta del día repartida con la curva horaria del mismo día del Cyber 2025. Pre-Cyber: solo páginas web y Kitchen Center, sin meta.</footer>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/6.1.0/echarts.min.js"></script>
<script>
const D=@@DATA@@;
const C={ty:'#3987e5',ly:'#d95926',jun:'#199e70',meta:'#8397B5',mut:'#8397B5',line:'#1E2E4A',ink:'#E6EDF7'};
const SK=['ty','ly','jun'];
const fM=v=>v==null?'—':'$'+(v/1e6).toLocaleString('es-CL',{minimumFractionDigits:1,maximumFractionDigits:1})+' M';
const fP=v=>v==null||!isFinite(v)?'—':(v>=0?'+':'')+v.toLocaleString('es-CL',{minimumFractionDigits:1,maximumFractionDigits:1})+'%';
const fPm=v=>v==null||!isFinite(v)?'—':v.toLocaleString('es-CL',{minimumFractionDigits:1,maximumFractionDigits:1})+'%';
const fD=document.getElementById('f_dia'),fC=document.getElementById('f_canal'),fL=document.getElementById('f_linea');
fC.innerHTML='<option value="all">Todos los canales</option>'+D.canales.map((c,i)=>`<option value="${i}">${c}</option>`).join('');
fL.innerHTML='<option value="all">Todas las líneas</option>'+D.lineas.map((c,i)=>`<option value="${i}">${c}</option>`).join('');
fD.value='@@DEF_DIA@@';
const base={textStyle:{fontFamily:'Segoe UI,system-ui,sans-serif',color:C.ink},animation:false,
 tooltip:{trigger:'axis',backgroundColor:'#0F1B30',borderColor:C.line,textStyle:{color:C.ink,fontSize:12},valueFormatter:v=>fM(v)},
 grid:{left:8,right:64,top:16,bottom:4,containLabel:true}};
const ax=o=>Object.assign({axisLine:{lineStyle:{color:'#2A3B5C'}},axisTick:{show:false},axisLabel:{color:C.mut,fontSize:10.5},splitLine:{lineStyle:{color:C.line,type:'dashed'}}},o||{});
const charts={};
function mk(id){const el=document.getElementById(id);const c=echarts.init(el);new ResizeObserver(()=>c.resize()).observe(el);charts[id]=c;return c;}
['c_hv','c_hm','c_dv','c_dm'].forEach(mk);
function diasSel(v){if(v==='cyber')return[0,1,2,3,4,5,6];if(v==='pre')return[-3,-2,-1];return[+v];}
function pasa(r,canal,linea){return (canal==='all'||r[3]==+canal)&&(linea==='all'||r[4]==+linea);}
function metaW(m){const k=D.corte;if(m[0]<k.d)return 1;if(m[0]>k.d)return 0;return m[1]<k.h?1:(m[1]===k.h?k.frac:0);}
function render(){
 const ds=diasSel(fD.value),canal=fC.value,linea=fL.value;
 const H={ty:{v:Array(24).fill(0),m:Array(24).fill(0)},ly:{v:Array(24).fill(0),m:Array(24).fill(0)},jun:{v:Array(24).fill(0),m:Array(24).fill(0)}};
 const Dd={},Dt={};SK.forEach(s=>{Dd[s]={v:Array(10).fill(0),m:Array(10).fill(0),n:Array(10).fill(0)};Dt[s]={v:Array(10).fill(0),m:Array(10).fill(0)};});
 const T={};SK.forEach(s=>T[s]={v:0,m:0,n:0});
 for(const r of D.rows){ if(!pasa(r,canal,linea))continue; const s=SK[r[0]];
  Dd[s].v[r[1]+3]+=r[6];Dd[s].m[r[1]+3]+=r[7];Dd[s].n[r[1]+3]+=r[8]; if(r[5]===1){Dt[s].v[r[1]+3]+=r[6];Dt[s].m[r[1]+3]+=r[7];}
  if(ds.includes(r[1])){H[s].v[r[2]]+=r[6];H[s].m[r[2]]+=r[7]; if(r[5]===1){T[s].v+=r[6];T[s].m+=r[7];T[s].n+=r[8];}}}
 const MH=Array(24).fill(0),MD=Array(10).fill(null);let mTot=0,mCorte=0;
 for(const m of D.metas){ if(!((canal==='all'||m[2]==+canal)&&(linea==='all'||m[3]==+linea)))continue;
  MD[m[0]+3]=(MD[m[0]+3]||0)+m[4]; if(ds.includes(m[0])){MH[m[1]]+=m[4];mTot+=m[4];mCorte+=m[4]*metaW(m);} }
 // ty: no dibujar horas futuras del día en curso
 const enCurso=ds.length===1&&ds[0]===D.corte.d;
 const tyV=H.ty.v.map((v,i)=>enCurso&&i>D.corte.h?null:v),tyM=H.ty.m.map((v,i)=>enCurso&&i>D.corte.h?null:v);
 const hrs=[...Array(24).keys()].map(h=>String(h).padStart(2,'0'));
 const lin=(n,d,c,extra)=>Object.assign({name:n,type:'line',data:d,symbol:'none',lineStyle:{width:2,color:c},itemStyle:{color:c},
   endLabel:{show:true,formatter:p=>p.seriesName.replace('Meta Oct 2026','Meta'),color:C.mut,fontSize:10}},extra||{});
 const metaOn=mTot>0;
 charts.c_hv.setOption(Object.assign({},base,{xAxis:ax({type:'category',data:hrs,splitLine:{show:false}}),yAxis:ax({type:'value',axisLabel:{color:C.mut,formatter:v=>(v/1e6).toLocaleString('es-CL')}}),
  series:[lin('Oct 2026',tyV,C.ty,{lineStyle:{width:2.5,color:C.ty}}),lin('Oct 2025',H.ly.v,C.ly),lin('Jun 2026',H.jun.v,C.jun)].concat(metaOn?[lin('Meta Oct 2026',MH,C.meta,{lineStyle:{width:1.6,color:C.meta,type:'dashed'}})]:[])}),true);
 charts.c_hm.setOption(Object.assign({},base,{xAxis:ax({type:'category',data:hrs,splitLine:{show:false}}),yAxis:ax({type:'value',axisLabel:{color:C.mut,formatter:v=>(v/1e6).toLocaleString('es-CL')}}),
  series:[lin('Oct 2026',tyM,C.ty,{lineStyle:{width:2.5,color:C.ty}}),lin('Oct 2025',H.ly.m,C.ly),lin('Jun 2026',H.jun.m,C.jun)]}),true);
 const sel=new Set(ds.map(d=>d+3));
 const bars=(k)=>SK.map(s=>({name:D.series[SK.indexOf(s)],type:'bar',barGap:'12%',barMaxWidth:16,
   data:Dd[s][k].map((v,i)=>({value:(s==='ty'&&i-3>D.corte.d)?null:v,itemStyle:{color:C[s],opacity:sel.has(i)?1:.45,borderRadius:[4,4,0,0]}}))}));
 charts.c_dv.setOption(Object.assign({},base,{tooltip:Object.assign({},base.tooltip,{axisPointer:{type:'shadow'}}),xAxis:ax({type:'category',data:D.dias.map(l=>l.replace(' · ','\n')),splitLine:{show:false},axisLabel:{color:C.mut,fontSize:10.5,interval:0,lineHeight:14}}),
  yAxis:ax({type:'value',axisLabel:{color:C.mut,formatter:v=>(v/1e6).toLocaleString('es-CL')}}),
  series:bars('v').concat([{name:'Meta Oct 2026',type:'scatter',data:MD,symbol:'rect',symbolSize:[22,3],itemStyle:{color:C.meta},z:5}])}),true);
 charts.c_dm.setOption(Object.assign({},base,{tooltip:Object.assign({},base.tooltip,{axisPointer:{type:'shadow'}}),xAxis:ax({type:'category',data:D.dias.map(l=>l.replace(' · ','\n')),splitLine:{show:false},axisLabel:{color:C.mut,fontSize:10.5,interval:0,lineHeight:14}}),
  yAxis:ax({type:'value',axisLabel:{color:C.mut,formatter:v=>(v/1e6).toLocaleString('es-CL')}}),series:bars('m')}),true);
 const lblSel=fD.options[fD.selectedIndex].text;
 document.getElementById('ps_hv').textContent=lblSel+' · millones de pesos · línea punteada = meta';
 document.getElementById('ps_hm').textContent=lblSel+' · millones de pesos';
 // tarjetas (mismo tramo)
 const v=(a,b)=>b?(a/b-1)*100:null, pmf=t=>t.n?t.m/t.n*100:null, cls=x=>x==null?'':(x>=0?'pos':'neg');
 const card=(t,val,lines)=>`<div class="card"><div class="kt">${t}</div><div class="kv">${val}</div><div class="kx">${lines}</div></div>`;
 const pcm=mCorte?T.ty.v/mCorte*100:null;
 document.getElementById('cards').innerHTML=
  card('Venta Oct 2026',fM(T.ty.v),`al corte ${D.corte.txt}`)+
  card('Meta',metaOn?fM(mCorte):'sin meta',metaOn?`al corte · ${pcm==null?'':`<b class="${pcm>=100?'pos':'neg'}">${fPm(pcm)}</b> de avance`} · total ${fM(mTot)}`:'pre-Cyber sin meta')+
  card('vs Oct 2025',`<span class="${cls(v(T.ty.v,T.ly.v))}">${fP(v(T.ty.v,T.ly.v))}</span>`,`${fM(T.ly.v)} mismo tramo · margen <span class="${cls(v(T.ty.m,T.ly.m))}">${fP(v(T.ty.m,T.ly.m))}</span>`)+
  card('vs Jun 2026',`<span class="${cls(v(T.ty.v,T.jun.v))}">${fP(v(T.ty.v,T.jun.v))}</span>`,`${fM(T.jun.v)} mismo tramo · margen <span class="${cls(v(T.ty.m,T.jun.m))}">${fP(v(T.ty.m,T.jun.m))}</span>`)+
  card('Margen directo',fPm(pmf(T.ty)),`Oct 2025 ${fPm(pmf(T.ly))} · Jun 2026 ${fPm(pmf(T.jun))}`);
 // tabla por día
 let tb='<tr><th>Día</th><th>Oct 2026</th><th>Meta</th><th>%Meta</th><th>Oct 2025</th><th>vs</th><th>Jun 2026</th><th>vs</th><th>Mg Oct 26</th><th>%M</th></tr>';
 D.dias.forEach((l,i)=>{const fut=i-3>D.corte.d,cur=i-3===D.corte.d;const t=Dd.ty.v[i],me=MD[i],rl=cur?Dt.ly.v[i]:Dd.ly.v[i],rj=cur?Dt.jun.v[i]:Dd.jun.v[i];
  tb+=`<tr><td>${l}${i-3===D.corte.d?' (al corte)':''}</td><td class="n">${fut?'—':fM(t)}</td><td class="n mut">${me?fM(me):'—'}</td><td class="n">${!fut&&me?fPm(t/me*100):'—'}</td>`+
  `<td class="n mut">${fM(Dd.ly.v[i])}</td><td class="n ${fut?'':cls(v(t,rl))}">${fut?'—':fP(v(t,rl))}</td><td class="n mut">${fM(Dd.jun.v[i])}</td><td class="n ${fut?'':cls(v(t,rj))}">${fut?'—':fP(v(t,rj))}</td>`+
  `<td class="n">${fut?'—':fM(Dd.ty.m[i])}</td><td class="n">${fut?'—':fPm(Dd.ty.n[i]?Dd.ty.m[i]/Dd.ty.n[i]*100:null)}</td></tr>`;});
 document.getElementById('tabla').innerHTML=tb;
}
[fD,fC,fL].forEach(e=>e.addEventListener('change',render));render();window.__listo=true;
</script></body></html>"""


# ───────────────────────── stock, Excel, envío, validación ─────────────────────────
def cargar_alarma_stock():
    """SKUs con cobertura < 7 días (Vta 30d Qty del parquet de stock)."""
    try:
        p = PROJECT_ROOT / 'data' / 'stock' / 'skus.parquet'
        if not p.exists():
            return []
        st = pd.read_parquet(p)
        out = []
        for _, row in st.iterrows():
            sku = str(row.get('SKU', '')).strip()
            disp = float(row.get('Disponible', 0) or 0)
            u30 = float(row.get('Vta 30d Qty', 0) or 0)
            if not sku or u30 <= 0:
                continue
            vd = u30 / 30
            dc = disp / vd if vd else 999
            if dc < 7:
                out.append({'sku': sku, 'producto': str(row.get('Producto', ''))[:50], 'disp': int(disp), 'vta_diaria': vd,
                            'dias_cob': dc, 'perdido': max(0, vd * 7 - disp) * float(row.get('Costo Unit', 0) or 0)})
        return sorted(out, key=lambda x: -x['perdido'])[:10]
    except Exception as e:
        print(f"      [WARN] alarma stock: {type(e).__name__}: {e}", flush=True)
        return []


def excel_raw_dia(df_dia, dia_s):
    x = df_dia.drop(columns=[c for c in ('venta_neta', 'fv', 'tod', 'h', 'd') if c in df_dia.columns])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        x.to_excel(w, index=False, sheet_name=f'Cyber {dia_s}')
    return buf.getvalue()


def _gmail_con_adjuntos(asunto, html, adjuntos, to_list):
    """adjuntos: [(bytes, nombre)] — el tipo sale de la extensión (.xlsx / .html)."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    cj = os.environ.get('GMAIL_TOKEN_JSON', '')
    if not cj:
        tp = PROJECT_ROOT / 'agente-comex' / 'config' / 'token.json'
        cj = tp.read_text() if tp.exists() else ''
    if not cj:
        return None
    cd = json.loads(cj)
    creds = Credentials.from_authorized_user_info(cd, cd.get('scopes'))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    msg = MIMEMultipart()
    msg['to'] = ','.join(to_list)
    msg['subject'] = asunto
    msg.attach(MIMEText(html, 'html'))
    for b, nombre in adjuntos:
        if not b:
            continue
        if nombre.lower().endswith('.html'):
            part = MIMEBase('text', 'html')
        else:
            part = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        part.set_payload(b)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=nombre)
        msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return build('gmail', 'v1', credentials=creds).users().messages().send(userId='me', body={'raw': raw}).execute().get('id', '?')


def enviar(html, adjuntos, bruta_total, bruta_hoy, avance):
    pre = '[PRE-BORRADOR] ' if PREBORRADOR else ''
    a = ahora()
    asunto = f"{pre}🛍️ Cyber UnionX Oct · {a:%H:%M} · {fmt_m(bruta_hoy)} hoy · {fmt_m(bruta_total)} acum ({pct(avance * 100, 0)} meta)"
    print(f"[envío] {asunto} → {EMAIL_TO}", flush=True)
    try:
        mid = _gmail_con_adjuntos(asunto, html, adjuntos, EMAIL_TO)
        if mid:
            print(f"      [OK] Gmail {mid}", flush=True)
            return True
    except Exception as e:
        print(f"      [WARN] Gmail falló: {type(e).__name__}: {e}", flush=True)
    if not RESEND_API_KEY:
        print('[ERROR] sin Gmail ni Resend', flush=True)
        return False
    att = [{'filename': n, 'content': base64.b64encode(b).decode()} for b, n in adjuntos if b]
    r = requests.post('https://api.resend.com/emails', json={'from': EMAIL_FROM, 'to': EMAIL_TO, 'subject': asunto, 'html': html, 'attachments': att},
                      headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'}, timeout=60)
    print(f"      Resend {r.status_code}", flush=True)
    return r.status_code < 300


def validar_contra_odoo(dia_s, bruta_parquet):
    """Venta bruta del día en el parquet vs Odoo state=sale (mismo día CLT). FAIL-CLOSED: > 10% → no envía."""
    import xmlrpc.client
    pw = os.environ.get('ANDRES_ODOO_PASSWORD', '')
    if not pw:
        return False, 'sin ANDRES_ODOO_PASSWORD, no puedo validar — NO envío'
    try:
        url, db, user = 'https://unionxb2b.odoo.com', 'bmya-innovatek-sh-prd-6981800', 'andres@grupoeter.cl'
        uid = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True).authenticate(db, user, pw, {})
        d0 = datetime.strptime(dia_s, '%Y-%m-%d').replace(tzinfo=TZ)
        desde = d0.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        hasta = (d0 + timedelta(days=1)).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        sos = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True).execute_kw(
            db, uid, pw, 'sale.order', 'search_read', [[('date_order', '>=', desde), ('date_order', '<', hasta), ('state', '=', 'sale')]],
            {'fields': ['amount_total'], 'limit': 20000})
        odoo = sum(s['amount_total'] for s in sos)
    except Exception as e:
        return False, f'Odoo no disponible ({type(e).__name__}) — NO envío'
    print(f"[VALIDA] {dia_s}: parquet ${bruta_parquet:,.0f} | Odoo state=sale ${odoo:,.0f} ({len(sos)} SOs)", flush=True)
    if odoo < 1_000_000:
        return True, f'Odoo bajo (${odoo:,.0f}), inicio del día'
    dif = abs(bruta_parquet - odoo) / odoo
    if dif > 0.10:
        return False, f'parquet ${bruta_parquet:,.0f} vs Odoo ${odoo:,.0f} (dif {dif * 100:.1f}%) — re-extraer'
    return True, f'OK (dif {dif * 100:.2f}%)'


def alertar_andres(asunto, detalle):
    to = [e.strip() for e in os.environ.get('ANDRES_ALERT_EMAIL', 'andres@unionx.cl').split(',') if e.strip()]
    html = (f"<h3>⚠️ Pulso Cyber bloqueado por el mecanismo de seguridad</h3><p>{ahora():%Y-%m-%d %H:%M} CLT</p>"
            f"<pre style='background:#f6f8fa;padding:12px;border-radius:6px'>{detalle}</pre><p>El pulso NO se envió a la lista. Revisa el extract/parquet.</p>")
    try:
        if _gmail_con_adjuntos(f"[ALERTA pulso Cyber] {asunto}", html, [], to):
            return True
    except Exception as e:
        print(f"   [alerta] Gmail falló: {e}", flush=True)
    if RESEND_API_KEY:
        r = requests.post('https://api.resend.com/emails', json={'from': EMAIL_FROM, 'to': to, 'subject': f"[ALERTA pulso Cyber] {asunto}", 'html': html},
                          headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'}, timeout=30)
        return r.status_code < 300
    return False


def construir():
    print('[1/4] Cargando RAW (parquet)...', flush=True)
    t0 = time.time()
    df = cargar_ventas()
    S = series(df)
    dia_s = corte()[0]
    hoy = df[df['fv'] == dia_s] if not ENSAYO else pd.DataFrame()   # todos los canales: frescura del dato
    if len(hoy) and ahora().strftime('%Y-%m-%d') == dia_s:
        _TOD_DATOS[dia_s] = hoy['tod'].max()
    lin = (df[df['fv'] >= '2026-06-01'].groupby('canal')['tipo_negocio'].agg(lambda s: s.mode().iat[0] if len(s.mode()) else '')).to_dict()
    M, info = cargar_metas(S, lin)
    print(f"      {len(df):,} filas en {time.time() - t0:.1f}s · meta ${info['total']:,.0f} ({info['fuente_dia']})", flush=True)
    print('[2/4] Armando correo y dashboard...', flush=True)
    html, bruta_total, bruta_hoy, avance = render_html(S, M, info, lin, cargar_alarma_stock())
    dash = render_dashboard(S, M, info)
    dia_s = corte()[0]
    dia_df = df[df['fv'] == dia_s]          # todos los canales del día: Excel RAW y validación contra Odoo
    return html, dash, dia_df, bruta_total, bruta_hoy, avance, dia_s


def main():
    args = sys.argv[1:]
    solo = '--solo-archivos' in args
    forzar_rango = os.environ.get('CYBER_FORZAR_RANGO') == '1'   # solo para borradores
    if not solo and not ENSAYO and not forzar_rango and not _check_rango():
        return 0
    hora = ahora().hour
    cfg = os.environ.get('CYBER_EMAIL_HOURS', '').strip()
    ok_hora = (hora in {int(x) for x in cfg.split(',') if x.strip().isdigit()}) if cfg else (hora % 2 == 0 and (hora == 0 or hora >= 8))
    if os.environ.get('CYBER_FORCE_EMAIL') == '1':
        ok_hora = True
    if not solo and not ok_hora:
        print(f"[SKIP email] {hora} h CLT — el correo sale cada 2 h (pares, 08:00–24:00). El parquet ya se refrescó.", flush=True)
        return 0
    if not solo:
        try:   # GATE 2: parquet sano antes de armar/enviar
            from validacion_ventas import validar_ventas_df, resumen_validacion
            mp = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
            okv, probs, st = validar_ventas_df(pd.read_parquet(mp) if mp.exists() else None, None)
            if not okv:
                det = resumen_validacion(okv, probs, st)
                print(f"[GATE 2] BLOQUEA:\n{det}", flush=True)
                alertar_andres('datos no pasaron la validación — pulso NO enviado', det)
                return 0
        except Exception as e:
            print(f"[GATE 2][WARN] validación saltada: {type(e).__name__}: {e}", flush=True)
    html, dash, dia_df, bruta_total, bruta_hoy, avance, dia_s = construir()
    a = ahora()
    nombre_dash = f"Dashboard Cyber Oct {a:%d-%m %H%M}.html"
    xlsx = excel_raw_dia(dia_df, dia_s) if len(dia_df) else None
    adj = [(dash.encode('utf-8'), nombre_dash)] + ([(xlsx, f'Raw Cyber {dia_s}.xlsx')] if xlsx else [])
    if solo:
        out = Path(args[args.index('--solo-archivos') + 1]) if len(args) > args.index('--solo-archivos') + 1 else Path('.')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'pulso_cyber.html').write_text(html, encoding='utf-8')
        (out / nombre_dash).write_text(dash, encoding='utf-8')
        print(f"[OK] archivos en {out}", flush=True)
        return 0
    if not ENSAYO and os.environ.get('CYBER_SIN_VALIDAR') != '1':   # CYBER_SIN_VALIDAR solo para borradores locales
        okv, msg = validar_contra_odoo(dia_s, float(dia_df['venta_bruta'].sum()) if len(dia_df) else 0.0)
        if not okv:
            print(f"[VALIDA] ABORTA: {msg}", flush=True)
            alertar_andres('validación contra Odoo falló — pulso NO enviado', msg)
            return 0
        print(f"[VALIDA] {msg}", flush=True)
    print('[3/4] Enviando...', flush=True)
    ok = enviar(html, adj, bruta_total, bruta_hoy, avance)
    print('[4/4] Listo.' if ok else '[4/4] FALLÓ', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
