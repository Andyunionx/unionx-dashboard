#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pulso Black UnionX 2026 — canales digitales (vie 27 → lun 30 de noviembre de 2026).

Correo a las 08:00, 12:00, 16:00 y 22:00 CLT (Andrés, 27-nov; parte el vie 27 a las 12:00) con:
  · la venta digital acumulada del Black contra el Black 2025 (mismo día de la semana, −364 días) y el plan A;
  · la venta por canal y por día del Black;
  · la venta por canal y por tramo de 2 horas del día en curso, contra el mismo día y tramo del Black 2025.

Canales digitales = líneas Marketplace, Fidelización y Páginas propias del RAW (columna tipo_negocio). Quedan fuera
Distribución (tiendas y UnionX B2B), Corporativo y Marketing.

Venta = venta bruta (con IVA) de las filas «Venta» del RAW: lo que se vendió (pedidos tomados). Las devoluciones no se
restan: el RAW las fecha con el día de la venta original a las 00:00 y las del Black 2025 ya están todas registradas,
así que restarlas compararía un año con devoluciones completas contra otro sin ellas.

Comparación: cada día contra el mismo día de la semana de 2025 (−364): vie 27-nov-26 ↔ vie 28-nov-25 … lun 30-nov-26 ↔
lun 1-dic-25. El día en curso se compara hasta la misma hora (mismo tramo).

Plan A = escenario A (plan de Nicole al 100%) del libro de operaciones Black/Navidad (Hugo, 23-nov), venta neta por canal
y día × 1,19 → data/planificacion/plan_black_2026.json. En el día en curso, el plan al corte usa la curva horaria del
mismo día del Black 2025 (canales digitales).

Fuente de venta: RAW en parquet (histórico + mes en curso; black_pulso.yml re-extrae el mes desde Odoo en cada corrida).

Vars de entorno:
  EMAIL_TO, EMAIL_FROM, RESEND_API_KEY, GMAIL_TOKEN_JSON, ANDRES_ODOO_PASSWORD
  BLACK_PREBORRADOR=1     asunto [PRE-BORRADOR] (el workflow además deja EMAIL_TO solo en Andrés)
  BLACK_FORCE_EMAIL=1     ignora la ventana horaria
  BLACK_AHORA="YYYY-MM-DD HH:MM"   simula la hora de corte (pruebas)
  BLACK_FORZAR_RANGO=1    arma y envía aunque esté fuera de las fechas (borradores)
  BLACK_SIN_VALIDAR=1     no valida contra Odoo (solo borradores locales)
  BLACK_EMAIL_HOURS="8,12"   horas CLT en que sale el correo (por defecto 8, 12, 16 y 22)
Uso local sin enviar: python enviar_pulso_black.py --solo-archivos <carpeta>

No toca enviar_pulso_cyber.py ni enviar_pulso_diario.py.
"""
import base64
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

PROJECT_ROOT = Path(os.environ.get('BLACK_ROOT') or Path(__file__).parent)
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
EMAIL_TO = [e.strip() for e in os.environ.get('EMAIL_TO', 'andres@unionx.cl').split(',') if e.strip()]
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'onboarding@resend.dev')
PREBORRADOR = os.environ.get('BLACK_PREBORRADOR', '0') == '1'

# ───────────────────────── configuración del evento ─────────────────────────
DIAS = ['2026-11-27', '2026-11-28', '2026-11-29', '2026-11-30']
LBL = ['vie 27', 'sáb 28', 'dom 29', 'lun 30']
LY = ['2025-11-28', '2025-11-29', '2025-11-30', '2025-12-01']          # −364: mismo día de la semana
LY_LBL = ['vie 28-nov-25', 'sáb 29-nov-25', 'dom 30-nov-25', 'lun 1-dic-25']
RANGO_INICIO = datetime(2026, 11, 27, 0, 0, tzinfo=TZ)
RANGO_FIN = datetime(2026, 11, 30, 23, 59, tzinfo=TZ)   # último pulso: lun 30 a las 22:00 (sin cierre de medianoche)
PLAN_JSON = PROJECT_ROOT / 'data' / 'planificacion' / 'plan_black_2026.json'
IVA = 1.19
LINEAS = ['Marketplace', 'Fidelización', 'Páginas propias']
NOM_LINEA = {'Marketplace': 'Marketplace', 'Fidelización': 'Fidelización', 'Páginas propias': 'Páginas web'}
# canales que se muestran siempre (aunque vayan en cero); el resto de cada línea va en «Otros» si es chico
FIJOS = {'Marketplace': ['Mercado Libre', 'Falabella', 'Paris', 'Walmart', 'Ripley', 'Kitchen Center'],
         'Fidelización': ['LATAM Pass', 'Travel Duty'],
         'Páginas propias': ['Simplit web', 'Lhotse web', 'UnionX web']}
UMBRAL_OTROS = 1_000_000      # bruta: bajo esto, en ambos años, el canal va agrupado en «Otros»
TRAMOS = [f'{2 * t:02d}–{2 * t + 2:02d}' for t in range(12)]
# Entran a Odoo en un lote al día con la hora de la carga, no la de la compra (verificado en el RAW 16→26-nov-26 y en el
# Black 2025: una sola hora por día). Kitchen Center llega cerca de las 09:00. Se comparan por día completo y solo
# cuando el lote de hoy ya llegó.
LOTE = ['Kitchen Center', 'Travel Duty', 'El Volcan', 'Abc', 'Sawa', 'Banco Bice', 'Global Reward', 'You Market']
FIJOS_LOTE = ['Kitchen Center', 'Travel Duty']     # se avisa en «Lo principal» si su lote de hoy aún no llega
HORA_LOTE = {'Kitchen Center': 'cerca de las 09:00', 'Travel Duty': 'entre las 09:00 y las 17:00'}   # RAW 16→26-nov-26


# paleta del pulso (estilos en línea; el correo no lleva CSS externo)
NAVY, CREMA, ACENTO, POS, NEG, GRIS, TXT, LINEA = '#13233A', '#F6F5F1', '#2E75B6', '#2E7D5B', '#B5473A', '#6B7280', '#1F2937', '#E5E7EB'


def ahora():
    v = os.environ.get('BLACK_AHORA', '').strip()
    if v:
        return datetime.strptime(v, '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
    return datetime.now(TZ)


_TOD_DATOS = {}   # día → hora de la última venta en el parquet (la fija construir())


def corte():
    """(día comercial, índice 0..3 del día del Black, hora de corte HH:MM:SS, momento).
    Antes de las 06:00 cuenta como cierre del día anterior. idx −1 = antes del Black; 4 = Black terminado."""
    a = ahora()
    dia = a if a.hour >= 6 else a - timedelta(days=1)
    dia_s = dia.strftime('%Y-%m-%d')
    cierre = dia_s != a.strftime('%Y-%m-%d')
    if dia_s in DIAS:
        idx = DIAS.index(dia_s)
    elif dia_s > DIAS[-1]:
        idx = 4
    else:
        idx = -1
    tod = '23:59:59' if cierre or idx == 4 else a.strftime('%H:%M:%S')
    # si el dato llega hasta antes del corte, se compara hasta la última venta registrada (si no, 2025 sumaría horas
    # que hoy todavía no están en el RAW)
    ult = _TOD_DATOS.get(dia_s)
    if ult and ult < tod and idx <= 3:
        tod = ult
    return dia_s, idx, tod, a


# ───────────────────────── datos ─────────────────────────
COLS = ['fecha_venta', 'hora_venta', 'tipo_movimiento', 'canal', 'tipo_negocio', 'pedido', 'documento', 'sku',
        'cantidad', 'venta_bruta', 'venta_neta', 'es_despacho', 'margen_front', 'comision', 'logistica', 'marketing',
        'margen_final']
MARGEN = ['margen_front', 'comision', 'logistica', 'marketing', 'margen_final']


def cargar_ventas():
    """Histórico + mes en curso (solo días posteriores al último del histórico: evita doble conteo)."""
    import pyarrow.parquet as pq
    hp = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
    mp = Path(os.environ.get('BLACK_MES_PARQUET') or (PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'))
    partes = []
    for p in (hp, mp):
        if p.exists():
            cols = [c for c in COLS if c in pq.read_schema(p).names]
            x = pd.read_parquet(p, columns=cols)
            x['fv'] = pd.to_datetime(x['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
            partes.append(x)
    df = partes[0]
    if len(partes) > 1:
        m = partes[1]
        df = pd.concat([df, m[m['fv'] > df['fv'].max()]], ignore_index=True)
    df = df[df['fv'].isin(set(DIAS + LY))].copy()
    for c in ('cantidad', 'venta_bruta', 'venta_neta', *MARGEN):
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0) if c in df.columns else 0.0
    t = df['hora_venta'].astype(str).str.strip()
    t = t.where(t.str.match(r'^\d{1,2}:\d{2}'), '00:00:00')
    df['tod'] = t.str.zfill(8).str[:8]
    df['t'] = df['tod'].str[:2].astype(int) // 2           # tramo de 2 horas (0..11)
    for c in ('canal', 'tipo_negocio', 'tipo_movimiento'):
        df[c] = df[c].fillna('').astype(str).str.strip()
    return df


def series(df):
    """{'ty': Black 2026, 'ly': Black 2025 (−364)} con columna d = día del Black (0..3); solo filas Venta digitales."""
    v = df[(df['tipo_movimiento'] == 'Venta') & df['tipo_negocio'].isin(LINEAS)]
    out = {}
    for s, fechas in (('ty', DIAS), ('ly', LY)):
        x = v[v['fv'].isin(fechas)].copy()
        x['d'] = x['fv'].map(dict(zip(fechas, range(4))))
        out[s] = x
    return out


def en_tramo(x, idx, tod):
    """Mismo tramo: días anteriores completos + el día en curso hasta la hora de corte."""
    return (x['d'] < idx) | ((x['d'] == idx) & (x['tod'] <= tod))


def cargar_plan():
    """Plan A bruto por canal y día: {canal: [vie, sáb, dom, lun]} (neta del libro × 1,19)."""
    if not PLAN_JSON.exists():
        return {}, ''
    p = json.loads(PLAN_JSON.read_text(encoding='utf-8'))
    out = {c: [float(v.get(d, 0) or 0) * IVA for d in DIAS] for c, v in p.get('venta_neta_por_canal_dia', {}).items()}
    return out, p.get('fuente', '')


# ───────────────────────── formato ─────────────────────────
def mm(v, d=1):
    """Millones con coma decimal: 12,3."""
    return f"{v / 1e6:,.{d}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def fmt_m(v):
    return f"${mm(v)} M"


def ent(v):
    return f"{int(round(v)):,}".replace(',', '.')


def pct_txt(v, d=0, signo=True):
    s = f"{v:+,.{d}f}%" if signo else f"{v:,.{d}f}%"
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


def var(ty, ly):
    return (ty / ly - 1) * 100 if ly and ly > 0 else None


TD = f'padding:5px 7px;border-bottom:1px solid {LINEA};white-space:nowrap'


def td(v, bold=False, color=None, align='right', bg=None, gris=False):
    st = TD + (';font-weight:700' if bold else '') + (f';color:{color}' if color else (f';color:{GRIS}' if gris else ''))
    st += f';background:{bg}' if bg else ''
    return f'<td align="{align}" style="{st}">{v}</td>'


def td_var(ty, ly, bold=False, bg=None):
    v = var(ty, ly)
    if v is None:
        return td('—', gris=True, bg=bg)
    return td(pct_txt(v), bold=bold, color=POS if v >= 0 else NEG, bg=bg)


def tabla(cab, filas, nota=''):
    th = ''.join(f'<th align="{"left" if i == 0 else "right"}" style="padding:6px 7px;border-bottom:2px solid {NAVY};'
                 f'font-size:11px;color:{GRIS};font-weight:600;white-space:nowrap">{c}</th>' for i, c in enumerate(cab))
    n = f'<p style="font-size:11.5px;color:{GRIS};margin:6px 0 0;line-height:1.45">{nota}</p>' if nota else ''
    return (f'<div style="overflow-x:auto"><table style="border-collapse:collapse;font-size:12.5px;'
            f'font-variant-numeric:tabular-nums;color:{TXT};min-width:100%">'
            f'<thead><tr>{th}</tr></thead><tbody>{"".join(filas)}</tbody></table></div>{n}')


def seccion(num, titulo, cuerpo):
    return (f'<h2 style="font-family:Georgia,serif;font-size:17px;color:{NAVY};margin:26px 0 8px;font-weight:600">'
            f'<span style="color:{ACENTO}">{num}</span>&nbsp; {titulo}</h2>{cuerpo}')


# ───────────────────────── agrupación de canales ─────────────────────────
def linea_de(S):
    return pd.concat([S['ty'], S['ly']]).groupby('canal')['tipo_negocio'].agg(lambda s: s.mode().iat[0])


def parejo(S, idx, tod):
    """Mismo tramo, parejo entre años.
    · Canales con hora real: días anteriores completos + el día en curso hasta la hora de corte, en ambos años.
    · Canales que entran en un lote al día (LOTE; la hora del RAW es la de la carga, no la de la compra): el día en curso
      cuenta en 2026 y en 2025 (día completo) solo si el lote de hoy ya llegó; si no, sale de los dos años."""
    ty, ly = S['ty'], S['ly']
    llegados = set(ty.loc[(ty['d'] == idx) & ty['canal'].isin(LOTE), 'canal'])
    lt, ll = ty['canal'].isin(LOTE), ly['canal'].isin(LOTE)
    Tty = ty[(ty['d'] < idx) | ((ty['d'] == idx) & (lt | (ty['tod'] <= tod)))]
    Tly = ly[(ly['d'] < idx) | ((ly['d'] == idx) & ((ll & ly['canal'].isin(llegados)) | (~ll & (ly['tod'] <= tod))))]
    return {'ty': Tty, 'ly': Tly}, llegados


def grupos_dia(S, lin):
    """[(línea, [canales a mostrar], [canales en «Otros»])] para las tablas."""
    tot = pd.concat([S['ty'].groupby('canal')['venta_bruta'].sum().rename('ty'),
                     S['ly'].groupby('canal')['venta_bruta'].sum().rename('ly')], axis=1).fillna(0)
    out = []
    for L in LINEAS:
        cs = [c for c in lin.index if lin[c] == L]
        resto = [c for c in cs if c not in FIJOS[L]]
        grandes = [c for c in resto if tot.loc[c].max() >= UMBRAL_OTROS]
        otros = sorted([c for c in resto if c not in grandes], key=lambda c: -tot.loc[c].max())
        mostrar = sorted(FIJOS[L] + grandes, key=lambda c: -(tot.loc[c, 'ty'] if c in tot.index else 0))
        out.append((L, mostrar, otros))
    return out


def full_ly_d_c(S, canal, d):
    """Venta 2025 del canal en el día d completo."""
    x = S['ly']
    return float(x.loc[(x['d'] == d) & (x['canal'] == canal), 'venta_bruta'].sum())


# ───────────────────────── correo ─────────────────────────
def render_html(S, plan, plan_fuente, fuente_txt, M=None):
    dia_s, idx, tod, a = corte()
    i_hoy = min(max(idx, 0), 3)
    cerrado = idx > 3 or tod >= '23:59'
    T, llegados = parejo(S, idx if idx <= 3 else 4, tod)
    lin = linea_de(S)
    grupos = grupos_dia(S, lin)
    todos = [c for _, m_, o_ in grupos for c in m_ + o_]
    nuevos = sorted(c for c in S['ty']['canal'].unique() if c not in set(S['ly']['canal']))
    lote_pend = [c for c in FIJOS_LOTE if c not in llegados] if idx <= 3 else []

    # ── cifras base
    b_ty, b_ly = T['ty']['venta_bruta'].sum(), T['ly']['venta_bruta'].sum()
    ped_ty = T['ty']['pedido'].nunique()
    hoy_ty = T['ty'].loc[T['ty']['d'] == i_hoy, 'venta_bruta'].sum()
    hoy_ly = T['ly'].loc[T['ly']['d'] == i_hoy, 'venta_bruta'].sum()
    full_ly_d = S['ly'].groupby('d')['venta_bruta'].sum().reindex(range(4), fill_value=0)
    # plan A: días cerrados completos; día en curso al corte = plan del día × parte del día que llevaba 2025 a esta hora
    plan_d = [sum(v[d] for v in plan.values()) for d in range(4)] if plan else [0] * 4
    curva = 1.0 if cerrado else (hoy_ly / full_ly_d[i_hoy] if full_ly_d[i_hoy] else 0)
    plan_corte = (sum(plan_d[:i_hoy]) + plan_d[i_hoy] * curva) if plan else 0
    if idx > 3:
        plan_corte = sum(plan_d)
    g_ty = T['ty'].groupby('canal')['venta_bruta'].sum()
    g_ly = T['ly'].groupby('canal')['venta_bruta'].sum()
    delta = g_ty.sub(g_ly, fill_value=0).sort_values()
    t_ult = 11 if cerrado else min(int(tod[:2]) // 2, 11)
    rt = {s: T[s][(T[s]['d'] == i_hoy) & ~T[s]['canal'].isin(LOTE)] for s in ('ty', 'ly')}   # hoy, canales con hora real
    ult_ty = rt['ty'].loc[rt['ty']['t'] == t_ult, 'venta_bruta'].sum()
    ult_ly = rt['ly'].loc[rt['ly']['t'] == t_ult, 'venta_bruta'].sum()
    v_tot = var(b_ty, b_ly)
    nuevos_ty = T['ty'].loc[T['ty']['canal'].isin(nuevos), 'venta_bruta'].sum()
    v_sin_nuevos = var(b_ty - nuevos_ty, b_ly)
    dia_lbl = LBL[i_hoy]
    hora_txt = 'cierre del día' if cerrado else tod[:5]
    col = lambda v: POS if (v or 0) >= 0 else NEG  # noqa: E731

    # ── titular (se calcula desde los datos)
    if v_tot is None:
        titular = f'El Black digital lleva {fmt_m(b_ty)}'
    else:
        titular = (f'El Black digital lleva {fmt_m(b_ty)}: {pct_txt(abs(v_tot), 0, False)} '
                   f'{"sobre" if v_tot >= 0 else "bajo"} el Black 2025 a la misma hora')
    mueve_pos = delta[delta > 0].sort_values(ascending=False).head(2)
    mueve_neg = delta[delta < 0].head(2)
    lista = lambda s: ' y '.join(f'{c} ({"+" if v >= 0 else "−"}{fmt_m(abs(v))})' for c, v in s.items())  # noqa: E731
    sub = ([f'Suben {lista(mueve_pos)}'] if len(mueve_pos) else []) + ([f'bajan {lista(mueve_neg)}'] if len(mueve_neg) else [])
    subtitulo = '; '.join(sub) + ' frente a 2025.' if sub else ''

    # ── lo principal
    bullets = []
    if v_tot is not None:
        txt_n = (f' Sin {", ".join(nuevos)}, que no existía{"n" if len(nuevos) > 1 else ""} en 2025: {pct_txt(v_sin_nuevos)}.'
                 if nuevos and nuevos_ty >= 100_000 and v_sin_nuevos is not None else '')
        bullets.append(f'<b>Acumulado del Black</b> (vie 27 00:00 → {dia_lbl} {hora_txt}): {fmt_m(b_ty)} contra {fmt_m(b_ly)} '
                       f'del Black 2025 a la misma altura (<b style="color:{col(v_tot)}">{pct_txt(v_tot)}</b>, '
                       f'{"+" if b_ty >= b_ly else "−"}{fmt_m(abs(b_ty - b_ly))}).{txt_n}')
    if idx <= 3 and i_hoy > 0:
        vh = var(hoy_ty, hoy_ly)
        bullets.append(f'<b>Hoy {dia_lbl}</b> hasta las {hora_txt}: {fmt_m(hoy_ty)} contra {fmt_m(hoy_ly)} el {LY_LBL[i_hoy]}'
                       + (f' (<b style="color:{col(vh)}">{pct_txt(vh)}</b>)' if vh is not None else '') + '.')
    if not cerrado:
        vu = var(ult_ty, ult_ly)
        bullets.append(f'<b>Tramo en curso</b> ({TRAMOS[t_ult]} h), canales con hora real: {fmt_m(ult_ty)} contra '
                       f'{fmt_m(ult_ly)} en 2025 a la misma hora' + (f' (<b style="color:{col(vu)}">{pct_txt(vu)}</b>)' if vu is not None else '') + '.')
    if lote_pend:
        ref = sum(full_ly_d_c(S, c, i_hoy) for c in lote_pend)
        cuando = '; '.join(f'{c} suele llegar {HORA_LOTE[c]}' for c in lote_pend if c in HORA_LOTE)
        bullets.append(f'<b>Falta el lote de hoy</b> de {" y ".join(lote_pend)}: entra{"n" if len(lote_pend) > 1 else ""} a Odoo una vez al día, '
                       f'sin hora de compra ({cuando}). Mientras no llega, sale de la comparación en los dos años '
                       f'(el {LY_LBL[i_hoy]} sumó {fmt_m(ref)}).')
    if plan:
        p_av = b_ty / plan_corte * 100 if plan_corte else 0
        bullets.append(f'<b>Plan A</b> (plan de Nicole al 100%): {fmt_m(sum(plan_d))} para los cuatro días; al corte tocaba '
                       f'{fmt_m(plan_corte)} y vamos en <b style="color:{col(p_av - 100)}">{pct_txt(p_av, 0, False)}</b>.')

    kpi = lambda et, v, s, c='#C9D3E0': (f'<td style="padding:10px 10px 6px;vertical-align:top;width:25%">'  # noqa: E731
                                          f'<div style="font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:#9FB3CC">{et}</div>'
                                          f'<div style="font-family:Georgia,serif;font-size:22px;color:#FFFFFF;margin:2px 0">{v}</div>'
                                          f'<div style="font-size:11.5px;color:{c}">{s}</div></td>')
    cv = lambda v: '#8FD3B0' if (v or 0) >= 0 else '#F2A7A0'  # noqa: E731
    vh = var(hoy_ty, hoy_ly)
    k1 = kpi('Acumulado Black', fmt_m(b_ty), f'{ent(ped_ty)} pedidos · bruta con IVA')
    k2 = kpi('vs Black 2025', pct_txt(v_tot) if v_tot is not None else '—', f'2025 a la misma hora: {fmt_m(b_ly)}', cv(v_tot))
    k3 = kpi(f'Hoy {dia_lbl}', fmt_m(hoy_ty), f'{pct_txt(vh)} vs {LY_LBL[i_hoy]}' if vh is not None else '—', cv(vh))
    k4 = kpi('vs plan A al corte', pct_txt(b_ty / plan_corte * 100, 0, False) if plan_corte else '—',
             f'tocaba {fmt_m(plan_corte)}' if plan_corte else 'sin plan')
    estado = ('Black terminado' if idx > 3 else (f'cierre {dia_lbl}' if cerrado else f'{dia_lbl} · datos hasta las {tod[:5]}'))
    head = (f'<div style="background:{NAVY};color:#fff;padding:18px 16px 8px;border-radius:6px 6px 0 0">'
            f'<div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#9FB3CC">Pulso Black UnionX · canales digitales · {estado}</div>'
            f'<div style="font-family:Georgia,serif;font-size:22px;line-height:1.25;margin:6px 0 4px">{titular}</div>'
            f'<div style="font-size:13px;color:#C9D3E0">{subtitulo}</div>'
            f'<table style="width:100%;border-collapse:collapse;margin-top:10px"><tr>{k1}{k2}{k3}{k4}</tr></table></div>')
    if M:
        bullets.append(M['bullet'])
    principal = seccion('01', 'Lo principal', '<ul style="margin:0;padding-left:18px;font-size:13.5px;line-height:1.5">'
                        + ''.join(f'<li style="margin:0 0 6px">{b}</li>' for b in bullets) + '</ul>')

    # ── 02 · hoy por canal y tramo de 2 horas (canales con hora real) + lotes
    tramos = list(range(t_ult + 1))
    ct = rt['ty'].groupby(['canal', 't'])['venta_bruta'].sum()
    ly_c = rt['ly'].groupby('canal')['venta_bruta'].sum()
    filas = []
    ncol = len(tramos) + 4

    def celda_m(v, bold=False, bg=None):
        return td(mm(v) if abs(v) >= 50_000 else ('—' if v == 0 else '0,0'), bold=bold, bg=bg, gris=(v == 0))

    def fila_t(nombre, canales, bold=False, bg=None):
        vals = [sum(ct.get((c, t), 0) for c in canales) for t in tramos]
        tl = sum(ly_c.get(c, 0) for c in canales)
        return (f'<tr>{td(nombre, bold=bold, align="left", bg=bg)}{"".join(celda_m(v, bold, bg) for v in vals)}'
                f'{td(mm(sum(vals)), bold=True, bg=bg)}{td(mm(tl), bg=bg, gris=True)}{td_var(sum(vals), tl, bold=bold, bg=bg)}</tr>')

    def rotulo(txt):
        return (f'<tr><td colspan="{ncol}" style="padding:9px 7px 3px;font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;'
                f'color:{ACENTO};font-weight:700">{txt}</td></tr>')

    rt_canales = []
    for L, mostrar, otros in grupos:
        cs = [c for c in mostrar if c not in LOTE]
        os_ = [c for c in otros if c not in LOTE]
        if not cs and not os_:
            continue
        filas.append(rotulo(NOM_LINEA[L]))
        filas += [fila_t('&nbsp;&nbsp;' + c, [c]) for c in cs]
        if os_:
            filas.append(fila_t('&nbsp;&nbsp;Otros', os_))
        rt_canales += cs + os_
    filas.append(fila_t('Con hora real', rt_canales, bold=True, bg='#E8EEF6'))
    ly_t = rt['ly'].groupby('t')['venta_bruta'].sum()
    ty_t = rt['ty'].groupby('t')['venta_bruta'].sum()
    filas.append(f'<tr>{td("&nbsp;&nbsp;2025 · " + LY_LBL[i_hoy], align="left", gris=True)}'
                 + ''.join(td(mm(ly_t.get(t, 0)), gris=True) for t in tramos) + td(mm(ly_t.sum()), gris=True) + td('') + td('') + '</tr>')
    filas.append(f'<tr>{td("&nbsp;&nbsp;Var. vs 2025", align="left", bold=True)}'
                 + ''.join(td_var(ty_t.get(t, 0), ly_t.get(t, 0)) for t in tramos) + td_var(ty_t.sum(), ly_t.sum(), bold=True)
                 + td('') + td('') + '</tr>')
    # lotes: sin tramo (la hora es la de la carga)
    lote_hoy = [c for c in todos if c in LOTE]
    filas_lote = []
    for c in lote_hoy:
        v26 = S['ty'].loc[(S['ty']['d'] == i_hoy) & (S['ty']['canal'] == c), 'venta_bruta'].sum()
        v25 = full_ly_d_c(S, c, i_hoy)
        if abs(v26) < 50_000 and abs(v25) < 50_000:      # lotes chicos: no aportan a la lectura
            continue
        llego = c in llegados or idx > 3
        filas_lote.append(f'<tr>{td("&nbsp;&nbsp;" + c, align="left")}'
                          + f'<td colspan="{len(tramos)}" align="left" style="{TD};color:{GRIS};font-size:11.5px">'
                          + ('lote cargado' if llego else 'el lote de hoy aún no llega') + '</td>'
                          + td(mm(v26) if v26 else '—', bold=True, gris=not v26) + td(mm(v25), gris=True)
                          + (td_var(v26, v25) if llego else td('·', gris=True)) + '</tr>')
    if filas_lote:
        filas.append(rotulo('Lote diario, sin hora de compra · 2025 = día completo'))
        filas += filas_lote
    filas.append(f'<tr>{td("Total digital hoy", bold=True, align="left", bg="#E8EEF6")}'
                 + f'<td colspan="{len(tramos)}" style="{TD};background:#E8EEF6"></td>'
                 + td(mm(hoy_ty), bold=True, bg='#E8EEF6') + td(mm(hoy_ly), gris=True, bg='#E8EEF6')
                 + td_var(hoy_ty, hoy_ly, bold=True, bg='#E8EEF6') + '</tr>')
    cab_t = [f'{dia_lbl} · $ millones'] + [TRAMOS[t] + ('*' if (t == t_ult and not cerrado) else '') for t in tramos] + ['Hoy', '2025', 'Var.']
    nota_t = (f'Venta bruta por tramo de 2 horas según la hora de la venta en Odoo. «2025» compara con el {LY_LBL[i_hoy]} '
              f'(mismo día de la semana) hasta la misma hora.' + (f' *Tramo en curso: datos hasta las {tod[:5]}.' if not cerrado else '')
              + ' Los canales que entran en un lote al día no tienen hora de compra: se comparan por día completo y solo cuando el '
              'lote de hoy ya llegó; el «Total digital hoy» sigue la misma regla.')
    sec_tramo = seccion('02', 'Hoy por canal y tramo de 2 horas', tabla(cab_t, filas, nota_t))

    # ── 03 · por canal y día del Black
    cd = T['ty'].groupby(['canal', 'd'])['venta_bruta'].sum()
    filas = []

    def fila_d(nombre, canales, bold=False, bg=None):
        vals = [sum(cd.get((c, d), 0) for c in canales) for d in range(4)]
        tl = T['ly'].loc[T['ly']['canal'].isin(canales), 'venta_bruta'].sum()
        p = sum(plan.get(c, [0] * 4)[d] for c in canales for d in range(4)) if plan else 0
        pend = len(canales) == 1 and canales[0] in LOTE and canales[0] not in llegados and idx <= 3
        cel = ''.join(td('·', gris=True, bg=bg) if (d > i_hoy and idx <= 3) else
                      (td('pend.', gris=True, bg=bg) if (pend and d == i_hoy and not vals[d]) else
                       td(mm(vals[d]) if vals[d] else '—', bold=bold, bg=bg, gris=(vals[d] == 0))) for d in range(4))
        return (f'<tr>{td(nombre, bold=bold, align="left", bg=bg)}{cel}{td(mm(sum(vals)), bold=True, bg=bg)}'
                f'{td(mm(tl), bg=bg, gris=True)}{td_var(sum(vals), tl, bold=bold, bg=bg)}{td(mm(p) if p else "—", bg=bg, gris=True)}</tr>')

    for L, mostrar, otros in grupos:
        filas += [fila_d('&nbsp;&nbsp;' + c + (' †' if c in LOTE else ''), [c]) for c in mostrar]
        if otros:
            filas.append(fila_d('&nbsp;&nbsp;Otros', otros))
        filas.append(fila_d(NOM_LINEA[L], mostrar + otros, bold=True, bg='#F3F4F6'))
    filas.append(fila_d('Total digital', todos, bold=True, bg='#E8EEF6'))
    ly_d = T['ly'].groupby('d')['venta_bruta'].sum()
    ty_d = T['ty'].groupby('d')['venta_bruta'].sum()
    r_ly, r_var, r_plan, r_pp = [], [], [], []
    for d in range(4):
        if d > i_hoy and idx <= 3:
            r_ly.append(td(mm(full_ly_d[d]), gris=True))
            r_var.append(td('·', gris=True))
            r_pp.append(td('·', gris=True))
        else:
            r_ly.append(td(mm(ly_d.get(d, 0)), gris=True))
            r_var.append(td_var(ty_d.get(d, 0), ly_d.get(d, 0)))
            pc = plan_d[d] * (curva if (d == i_hoy and idx <= 3) else 1) if plan else 0
            r_pp.append(td(pct_txt(ty_d.get(d, 0) / pc * 100, 0, False) if pc else '—'))
        r_plan.append(td(mm(plan_d[d]) if plan else '—', gris=True))
    vac = td('') + td('') + td('')
    filas.append(f'<tr>{td("2025 (mismo día de la semana)", align="left", gris=True)}{"".join(r_ly)}{td(mm(b_ly), gris=True)}{vac}</tr>')
    filas.append(f'<tr>{td("Var. vs 2025", align="left", bold=True)}{"".join(r_var)}{td_var(b_ty, b_ly, bold=True)}{vac}</tr>')
    if plan:
        filas.append(f'<tr>{td("Plan A del día", align="left", gris=True)}{"".join(r_plan)}{td(mm(sum(plan_d)), gris=True)}{vac}</tr>')
        filas.append(f'<tr>{td("Real / plan A", align="left", bold=True)}{"".join(r_pp)}'
                     f'{td(pct_txt(b_ty / plan_corte * 100, 0, False) if plan_corte else "—", bold=True)}{vac}</tr>')
    en_curso = idx <= 3 and not cerrado
    cab_d = (['Black · $ millones'] + [l + ('*' if (d == i_hoy and en_curso) else '') for d, l in enumerate(LBL)]
             + ['Black', '2025', 'Var.', 'Plan A'])
    nota_d = ('Cada día contra el mismo día de la semana del Black 2025: ' + ', '.join(f'{LBL[d]} ↔ {LY_LBL[d]}' for d in range(4)) + '. '
              + (f'*Día en curso hasta las {tod[:5]}, contra 2025 a la misma hora; los días que vienen muestran, en gris, el día completo '
                 f'de 2025. ' if en_curso else '')
              + 'El Black 2025 empezó el jueves 27-nov: ese día no entra en la comparación. † Entra en un lote al día. '
              + (f'Plan A = {plan_fuente}. La columna «Plan A» es el plan de los cuatro días por canal; «Real / plan A» del día en curso '
                 f'usa el plan del día × la parte del día que llevaba 2025 a esta hora ({pct_txt(curva * 100, 0, False)}).' if plan else ''))
    sec_dia = seccion('03', 'Por canal y día del Black', tabla(cab_d, filas, nota_d))

    # ── pie: definiciones y fuente
    otros_txt = '; '.join(f'{NOM_LINEA[L]}: {", ".join(o)}' for L, _, o in grupos if o)
    nota = ('<b>Canales digitales</b> = líneas Marketplace, Fidelización y Páginas propias del RAW de ventas (columna «tipo de negocio»). '
            'No entran Distribución (tiendas Paris, Ripley y Walmart, UnionX B2B), Corporativo ni Marketing. '
            + (f'«Otros» agrupa canales chicos: {otros_txt}. ' if otros_txt else '')
            + '<b>Venta</b> = venta bruta con IVA de lo vendido (filas «Venta» del RAW), como el Pulso Diario. Las devoluciones no se '
            'restan: las de 2025 ya están todas registradas y las de hoy todavía no. '
            f'<b>Fuente</b>: {fuente_txt}.')
    pie = (f'<div style="margin-top:22px;padding:12px 14px;background:{CREMA};border-radius:6px;font-size:11.5px;color:{GRIS};'
           f'line-height:1.5">{nota}</div>')
    html = (f'<html><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:#FFFFFF">'
            f'<div style="max-width:1000px;margin:0 auto;padding:12px;font-family:Arial,Helvetica,sans-serif;color:{TXT}">'
            f'{head}<div style="padding:4px 4px 0">{principal}{sec_tramo}{sec_dia}{M['seccion'] if M else ''}{pie}</div></div></body></html>')
    resumen = {'dia': dia_s, 'idx': idx, 'tod': tod, 'b_ty': b_ty, 'b_ly': b_ly, 'var': v_tot, 'hoy_ty': hoy_ty, 'hoy_ly': hoy_ly,
               'plan_corte': plan_corte, 'plan_total': sum(plan_d), 'curva': curva, 'ped_ty': ped_ty, 'nuevos': nuevos,
               'nuevos_ty': nuevos_ty, 'var_sin_nuevos': v_sin_nuevos, 'lote_llegados': sorted(llegados), 'lote_pendientes': lote_pend,
               'ult_tramo': TRAMOS[t_ult], 'ult_ty': ult_ty, 'ult_ly': ult_ly, 'titular': titular, 'subtitulo': subtitulo,
               'delta_canal': {k: float(v) for k, v in delta.items()}}
    return html, resumen


# ───────────────────────── margen (Andrés 27-nov: «Ok con tu propuesta») ─────────────────────────
def margen(df, S):
    """Margen directo y final del Black digital al corte, mismas definiciones del pulso Cyber de octubre: margen directo =
    margen_front (venta neta − costo); margen final = margen_final del RAW (directo − comisión − logística − marketing);
    % sobre la venta neta; todas las filas del RAW (venta y devoluciones). Mismo corte parejo que la venta (lotes por día
    completo cuando llegó el de hoy). El margen final de 2025 NO se compara: el RAW de 2025 trae comisión y logística solo en
    Mercado Libre (completa) y en parte en Falabella y Walmart; el resto tiene margen final = margen directo. Única comparación
    válida de margen final: Mercado Libre."""
    dia_s, idx, tod, _ = corte()
    i = idx if idx <= 3 else 4
    llegados = set(S['ty'].loc[(S['ty']['d'] == i) & S['ty']['canal'].isin(LOTE), 'canal'])
    d = df[df['tipo_negocio'].isin(LINEAS)]
    A = {}
    for s_, fechas in (('ty', DIAS), ('ly', LY)):
        x = d[d['fv'].isin(fechas)].copy()
        x['d'] = x['fv'].map(dict(zip(fechas, range(4))))
        lote = x['canal'].isin(LOTE)
        hoy_lote = lote & (x['canal'].isin(llegados) if s_ == 'ly' else True)
        A[s_] = x[(x['d'] < i) | ((x['d'] == i) & (hoy_lote | (~lote & (x['tod'] <= tod))))]
    cols = ['venta_neta', 'margen_front', 'margen_final']
    g = {s_: A[s_].groupby('canal')[cols].sum() for s_ in A}
    tot = {s_: A[s_][cols].sum() for s_ in A}
    pc = lambda n, m: (m / n * 100) if n else None  # noqa: E731
    md, md25 = pc(tot['ty'].venta_neta, tot['ty'].margen_front), pc(tot['ly'].venta_neta, tot['ly'].margen_front)
    mf = pc(tot['ty'].venta_neta, tot['ty'].margen_final)
    ppx = lambda a, b: (f"{a - b:+.1f} pp".replace('.', ',')) if (a is not None and b is not None) else '—'  # noqa: E731
    p0 = lambda v: pct_txt(v, 1, False) if v is not None else '—'  # noqa: E731
    ml = 'Mercado Libre'
    ml_ty = g['ty'].loc[ml] if ml in g['ty'].index else None
    ml_ly = g['ly'].loc[ml] if ml in g['ly'].index else None
    mf_ml = pc(ml_ty.venta_neta, ml_ty.margen_final) if ml_ty is not None else None
    mf_ml25 = pc(ml_ly.venta_neta, ml_ly.margen_final) if ml_ly is not None else None
    bullet = (f'<b>Margen</b>: directo {fmt_m(tot["ty"].margen_front)} ({p0(md)} de la venta neta) contra {p0(md25)} del Black 2025 a la '
              f'misma hora ({ppx(md, md25)}); final {fmt_m(tot["ty"].margen_final)} ({p0(mf)}). El margen final no se compara con 2025 '
              f'(el RAW de 2025 no trae comisión ni logística en la mayoría de los canales)'
              + (f', salvo Mercado Libre: {p0(mf_ml)} contra {p0(mf_ml25)} ({ppx(mf_ml, mf_ml25)}).' if mf_ml is not None and mf_ml25 is not None else '.'))
    # tabla por canal (orden por venta neta; los chicos en «Otros»)
    t = g['ty'].join(g['ly'], rsuffix='_25', how='left').fillna(0).sort_values('venta_neta', ascending=False)
    grandes = [c for c in t.index if t.loc[c, 'venta_neta'] >= 300_000]
    otros = [c for c in t.index if c not in grandes]
    filas = []

    def fila(nombre, cs, bold=False, bg=None):
        r = t.loc[cs].sum()
        a, b, c25 = pc(r.venta_neta, r.margen_front), pc(r.venta_neta_25, r.margen_front_25), pc(r.venta_neta, r.margen_final)
        dpp = (a - b) if (a is not None and b is not None) else None
        if cs == [ml]:
            f25 = pc(r.venta_neta_25, r.margen_final_25)
            mf25_txt = td(p0(f25), gris=True, bg=bg)
        else:
            mf25_txt = td('—', gris=True, bg=bg)
        return (f'<tr>{td(nombre, bold=bold, align="left", bg=bg)}{td(mm(r.venta_neta), bold=bold, bg=bg)}'
                f'{td(mm(r.margen_front), bold=bold, bg=bg)}{td(p0(a), bold=bold, bg=bg, color=(NEG if (a or 0) < 0 else None))}'
                f'{td(p0(b), gris=True, bg=bg)}'
                + (td(ppx(a, b), bg=bg, color=(POS if dpp >= 0 else NEG)) if dpp is not None else td('—', gris=True, bg=bg))
                + f'{td(mm(r.margen_final), bold=bold, bg=bg)}{td(p0(c25), bold=bold, bg=bg, color=(NEG if (c25 or 0) < 0 else None))}'
                f'{mf25_txt}</tr>')

    filas += [fila('&nbsp;&nbsp;' + c, [c]) for c in grandes]
    if otros:
        filas.append(fila('&nbsp;&nbsp;Otros', otros))
    filas.append(fila('Total digital', list(t.index), bold=True, bg='#E8EEF6'))
    cab = ['Margen · $ millones', 'Venta neta', 'M. directo', '%', '% 2025', 'Dif.', 'M. final', '%', '% 2025']
    nota = ('Margen directo = venta neta − costo. Margen final = margen directo − comisión − logística − marketing, como el pulso del Cyber. '
            '% sobre la venta neta, con todas las filas del RAW (incluye devoluciones). Mismo corte que la venta. «% 2025» del margen final '
            'solo en Mercado Libre: es el único canal cuyo RAW de 2025 trae comisión y logística completas; en los demás el margen final de '
            '2025 queda igual al directo y no sirve para comparar. Referencia, no meta: el Cyber de octubre usó 23,3% de margen final.'
            + (f' «Otros»: {", ".join(otros)}.' if otros else ''))
    sec = seccion('04', 'Margen directo y final por canal (acumulado Black)', tabla(cab, filas, nota))
    cifras = {'neta': float(tot['ty'].venta_neta), 'md': float(tot['ty'].margen_front), 'md_pct': md, 'md_pct_25': md25,
              'mf': float(tot['ty'].margen_final), 'mf_pct': mf, 'mf_ml': mf_ml, 'mf_ml_25': mf_ml25}
    return {'bullet': bullet, 'seccion': sec, 'cifras': cifras}


# ───────────────────────── envío y validación ─────────────────────────
# Base RAW del día adjunta (Andrés 28-nov «Agreguémoslo»: igual que el pulso Cyber de octubre). Mismas columnas que el
# adjunto del Cyber, todos los canales y movimientos del día, sin las columnas auxiliares.
RAW_COLS = ['fecha_venta', 'hora_venta', 'tipo_movimiento', 'canal', 'tipo_negocio', 'marca', 'categoria_hijo', 'pedido',
            'documento', 'sku', 'producto', 'bodega', 'cantidad', 'venta_bruta', 'venta_neta', 'margen_front',
            'comision', 'logistica', 'marketing', 'margen_final']


def excel_raw_dia(dia_s):
    """Excel con el RAW del día (mes en curso del parquet). Como el Cyber: sin venta_neta ni columnas auxiliares."""
    import io
    import pyarrow.parquet as pq
    mp = Path(os.environ.get('BLACK_MES_PARQUET') or (PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'))
    if not mp.exists():
        return None
    cols = [c for c in RAW_COLS if c in pq.read_schema(mp).names]
    x = pd.read_parquet(mp, columns=cols)
    x = x[pd.to_datetime(x['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d') == dia_s]
    if not len(x):
        return None
    x = x.drop(columns=[c for c in ('venta_neta',) if c in x.columns])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        x.to_excel(w, index=False, sheet_name=f'Black {dia_s}')
    return buf.getvalue()


def _gmail(asunto, html, to_list, adjuntos=()):
    """adjuntos: [(bytes, nombre.xlsx)]."""
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
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    for b, nombre in adjuntos:
        if not b:
            continue
        part = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        part.set_payload(b)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=nombre)
        msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return build('gmail', 'v1', credentials=creds).users().messages().send(userId='me', body={'raw': raw}).execute().get('id', '?')


def asunto_de(r):
    pre = '[PRE-BORRADOR] ' if PREBORRADOR else ''
    idx = r['idx']
    cuando = 'cierre' if (idx > 3 or r['tod'] >= '23:59') else r['tod'][:5]
    dia = LBL[min(max(idx, 0), 3)]
    v = r['var']
    vtxt = f" · {pct_txt(v)} vs Black 2025" if v is not None else ''
    return f"{pre}Black digital UnionX · {dia} {cuando} · {fmt_m(r['b_ty'])} acumulado{vtxt}"


def enviar(html, r, adjuntos=()):
    asunto = asunto_de(r)
    print(f"[envío] {asunto} → {EMAIL_TO}", flush=True)
    try:
        mid = _gmail(asunto, html, EMAIL_TO, adjuntos)
        if mid:
            print(f"      [OK] Gmail {mid}", flush=True)
            return True
    except Exception as e:
        print(f"      [WARN] Gmail falló: {type(e).__name__}: {e}", flush=True)
    if not RESEND_API_KEY:
        print('[ERROR] sin Gmail ni Resend', flush=True)
        return False
    rr = requests.post('https://api.resend.com/emails', json={'from': EMAIL_FROM, 'to': EMAIL_TO, 'subject': asunto, 'html': html,
                             'attachments': [{'filename': n, 'content': base64.b64encode(b).decode()} for b, n in adjuntos if b]},
                       headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'}, timeout=60)
    print(f"      Resend {rr.status_code}", flush=True)
    return rr.status_code < 300


def validar_contra_odoo(dia_s, bruta_parquet, tod='23:59:59'):
    """Venta bruta del día en el parquet (todas las líneas, filas Venta) vs Odoo sale.order state=sale del mismo día CLT,
    hasta la hora de la última venta del parquet (tod). Sin ese tope, un lote que entra a Odoo entre el extract y la
    validación (27-nov: el lote de Kitchen Center entró a las 09:21) bloquea el pulso sin que el dato esté malo.
    FAIL-CLOSED: diferencia > 10% → no envía."""
    import xmlrpc.client
    pw = os.environ.get('ANDRES_ODOO_PASSWORD', '')
    if not pw:
        return False, 'sin ANDRES_ODOO_PASSWORD, no puedo validar — NO envío', None
    try:
        url, db, user = 'https://unionxb2b.odoo.com', 'bmya-innovatek-sh-prd-6981800', 'andres@grupoeter.cl'
        uid = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True).authenticate(db, user, pw, {})
        d0 = datetime.strptime(dia_s, '%Y-%m-%d').replace(tzinfo=TZ)
        desde = d0.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        hh, mi, ss = (int(v) for v in tod.split(':'))
        tope = d0 + timedelta(hours=hh, minutes=mi, seconds=ss + 1)
        hasta = min(d0 + timedelta(days=1), tope).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        sos = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True).execute_kw(
            db, uid, pw, 'sale.order', 'search_read', [[('date_order', '>=', desde), ('date_order', '<', hasta), ('state', '=', 'sale')]],
            {'fields': ['amount_total'], 'limit': 20000})
        odoo = sum(s['amount_total'] for s in sos)
    except Exception as e:
        return False, f'Odoo no disponible ({type(e).__name__}) — NO envío', None
    print(f"[VALIDA] {dia_s} hasta las {tod[:5]}: parquet ${bruta_parquet:,.0f} | Odoo state=sale ${odoo:,.0f} ({len(sos)} pedidos)", flush=True)
    if odoo < 1_000_000:
        return True, f'Odoo bajo (${odoo:,.0f}), inicio del día', odoo
    dif = abs(bruta_parquet - odoo) / odoo
    if dif > 0.10:
        return False, f'parquet ${bruta_parquet:,.0f} vs Odoo ${odoo:,.0f} (dif {dif * 100:.1f}%) — re-extraer', odoo
    return True, f'OK (dif {dif * 100:.2f}%)', odoo


def alertar_andres(asunto, detalle):
    to = [e.strip() for e in os.environ.get('ANDRES_ALERT_EMAIL', 'andres@unionx.cl').split(',') if e.strip()]
    html = (f"<h3>Pulso Black bloqueado por el control de datos</h3><p>{ahora():%Y-%m-%d %H:%M} CLT</p>"
            f"<pre style='background:#f6f8fa;padding:12px;border-radius:6px'>{detalle}</pre><p>El pulso NO salió a la lista. Revisa el extract.</p>")
    try:
        if _gmail(f"[ALERTA pulso Black] {asunto}", html, to):
            return True
    except Exception as e:
        print(f"   [alerta] Gmail falló: {e}", flush=True)
    return False


def construir():
    print('[1/3] Cargando RAW (parquet)...', flush=True)
    t0 = time.time()
    df = cargar_ventas()
    dia_s = corte()[0]
    hoy = df[(df['fv'] == dia_s) & (df['tipo_movimiento'] == 'Venta')]
    if len(hoy) and ahora().strftime('%Y-%m-%d') == dia_s:
        _TOD_DATOS[dia_s] = hoy['tod'].max()
    S = series(df)
    plan, plan_fuente = cargar_plan()
    fuente_txt = os.environ.get('BLACK_FUENTE_TXT') or f'RAW de ventas extraído de Odoo, corte {ahora():%d-%m %H:%M}'
    print(f"      {len(df):,} filas en {time.time() - t0:.1f}s · plan A {'cargado' if plan else 'sin JSON'}", flush=True)
    print('[2/3] Armando correo...', flush=True)
    try:
        M = margen(df, S)
    except Exception as e:      # el margen nunca debe botar el pulso de venta
        print(f'      [MARGEN][WARN] {type(e).__name__}: {e} — el pulso sale sin margen', flush=True)
        M = None
    html, r = render_html(S, plan, plan_fuente, fuente_txt, M)
    if M:
        r['margen'] = M['cifras']
    dia_df = df[(df['fv'] == corte()[0]) & (df['tipo_movimiento'] == 'Venta')]     # todos los canales: validación contra Odoo
    return html, r, dia_df


def main():
    for st in (sys.stdout, sys.stderr):      # Windows: consola cp1252
        try:
            st.reconfigure(encoding='utf-8')
        except Exception:
            pass
    args = sys.argv[1:]
    solo = '--solo-archivos' in args
    a = ahora()
    if not solo and os.environ.get('BLACK_FORZAR_RANGO') != '1' and not (RANGO_INICIO <= a <= RANGO_FIN):
        print(f"[SKIP] {a:%Y-%m-%d %H:%M} fuera del Black ({RANGO_INICIO:%d-%m %H:%M} → {RANGO_FIN:%d-%m %H:%M})", flush=True)
        return 0
    cfg = os.environ.get('BLACK_EMAIL_HOURS', '').strip()
    horas = {int(x) for x in cfg.split(',') if x.strip().isdigit()} if cfg else {8, 12, 16, 22}
    ok_hora = a.hour in horas or os.environ.get('BLACK_FORCE_EMAIL') == '1'
    if not solo and not ok_hora:
        print(f"[SKIP email] {a.hour} h CLT — el correo sale a las {sorted(horas)} h.", flush=True)
        return 0
    html, r, dia_df = construir()
    xlsx = excel_raw_dia(r['dia'])
    adj = [(xlsx, f"Raw Black {r['dia']}.xlsx")] if xlsx else []
    print(f"      adjunto RAW: {len(xlsx) / 1024:,.0f} KB" if xlsx else '      sin adjunto RAW (día sin filas)', flush=True)
    if solo:
        out = Path(args[args.index('--solo-archivos') + 1]) if len(args) > args.index('--solo-archivos') + 1 else Path('.')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'pulso_black.html').write_text(html, encoding='utf-8')
        for b, n in adj:
            (out / n).write_bytes(b)
        (out / 'pulso_black_resumen.json').write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float), encoding='utf-8')
        (out / 'pulso_black_asunto.txt').write_text(asunto_de(r), encoding='utf-8')
        print(f"[OK] archivos en {out} · {asunto_de(r)}", flush=True)
        return 0
    if os.environ.get('BLACK_SIN_VALIDAR') != '1':
        okv, msg, _ = validar_contra_odoo(r['dia'], float(dia_df['venta_bruta'].sum()) if len(dia_df) else 0.0, r['tod'])
        if not okv:
            print(f"[VALIDA] ABORTA: {msg}", flush=True)
            alertar_andres('validación contra Odoo falló — pulso NO enviado', msg)
            return 0
        print(f"[VALIDA] {msg}", flush=True)
    print('[3/3] Enviando...', flush=True)
    ok = enviar(html, r, adj)
    if ok and not PREBORRADOR:   # marca para el workflow: tras un pulso enviado a la lista se regenera el Drive LIVE
        (PROJECT_ROOT / '.black_pulso_enviado').write_text(datetime.now(TZ).isoformat(), encoding='utf-8')
    print('Listo.' if ok else 'FALLÓ', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
