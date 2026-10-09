# -*- coding: utf-8 -*-
"""Rentabilidad por canal — informe de control de gestión (Andrés 9-oct-2026).

Segundo informe del cierre de rentabilidad (el primero, rentabilidad_reporte_semanal.py, es venta, margen y razones,
para comercial). Este es para control de gestión (Gabriela): dónde podemos ser más rentables. Baja a glosa, modalidad
de envío y relación con la venta (% de la venta y $/pedido), mes contra mes en los tres últimos meses cerrados, y
cruza cada canal con la historia de su plan de acción (lo comprometido el mes anterior y el resultado). Resumen =
oportunidades en $/mes: la glosa vuelve a su mejor mes de la ventana, o a $0 si es un cargo evitable.

Sale con el reporte de cierre (rentabilidad_reporte_semanal.py --enviar, modo cierre): correo que se sostiene solo
+ HTML adjunto con el detalle por canal.

Uso suelto: python rentabilidad_control_gestion.py [--mes 2026-09] [--out carpeta]   (solo genera los archivos)
"""
from __future__ import annotations

import argparse
import html as H
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import macro_plan_accion as PA  # noqa: E402
import macro_rentabilidad_drive as D  # noqa: E402

CENTROS = ['Comisión venta', 'Comisión envío', 'Marketing']
EVITABLE = re.compile(r'penalid|multa|cancelaci|retiro de stock|stock antiguo|sobrepasar|diferencias en las medidas|retiro stock')
UMBRAL_OP = 50_000
LARGO = {1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto', 9: 'septiembre',
         10: 'octubre', 11: 'noviembre', 12: 'diciembre'}

CSS = """
:root{--ink:#1f2937;--mut:#64748b;--line:#dde3ea;--head:#1e3a5f;--soft:#f4f7fb;--good:#1e7a45;--bad:#b42318;--warn:#a15c07}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font:14px/1.5 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:22px;margin:0 0 4px;color:var(--head);text-wrap:balance}h2{font-size:18px;color:var(--head);margin:34px 0 8px;border-bottom:2px solid var(--head);padding-bottom:4px}
h3{font-size:16px;margin:26px 0 6px;color:var(--head)}.sub{color:var(--mut);font-size:13px}
.pre{background:#fef3c7;border-left:4px solid #d97706;padding:8px 12px;margin:12px 0;font-size:13px}
.how{color:var(--mut);font-size:12.5px;margin:2px 0 8px;max-width:900px}
.tw{overflow-x:auto;margin:6px 0 12px}table{border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:12.5px;min-width:600px}
th{background:var(--head);color:#fff;font-weight:600;padding:6px 8px;text-align:left;white-space:nowrap}
td{padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}td.r,th.r{text-align:right}
tr.cc td{background:var(--soft);font-weight:600;color:var(--head)}
.up{color:var(--bad);font-weight:600}.dn{color:var(--good);font-weight:600}.op{font-weight:700}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin:6px 0 10px}.k{border:1px solid var(--line);border-radius:6px;padding:6px 10px;min-width:150px}
.k b{display:block;font-size:15px}.k span{color:var(--mut);font-size:11.5px}
.gest{border-left:3px solid var(--head);background:var(--soft);padding:6px 10px;margin:6px 0;font-size:12.5px}
.chip{display:inline-block;border-radius:10px;padding:0 7px;font-size:11.5px;font-weight:600}
.g{background:#e7f5ec;color:var(--good)}.b{background:#fdecea;color:var(--bad)}.w{background:#fff4e0;color:var(--warn)}.n{background:#eef1f5;color:var(--mut)}
details{margin:4px 0}summary{cursor:pointer;color:var(--head);font-weight:600}
@media (prefers-color-scheme:dark){:root{--ink:#e5e7eb;--mut:#9aa6b2;--line:#334155;--head:#8fb3e0;--soft:#1b2533}body{background:#0f1720}th{background:#1e3a5f}}
"""


def n(x, d=1):
    return f'{x:,.{d}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def clp(x):
    return ('−' if x < 0 else '') + '$' + n(abs(x), 0)


def mm(x):
    return ('−' if x < 0 else '') + '$' + n(abs(x) / 1e6, 1) + ' M'


def pct(x):
    return '—' if x is None else n(x) + '%'


def norm(s):
    s = re.sub(r'^\(sin glosa en tabla\)\s*', '', str(s).strip(), flags=re.I)
    s = ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s).strip()


def chip(sem):
    s = str(sem)
    cls = 'g' if s.startswith('🟢') else 'b' if s.startswith('🔴') else 'w' if s.startswith('🟡') else 'n'
    return f'<span class="chip {cls}">{H.escape(s[2:].strip() or "—")}</span>'


def pedidos(meses):
    """Pedidos por canal × modalidad × mes (modalidad declarada en Odoo, igual que la macro). Si Odoo no
    responde, vacío: el informe sale sin $/pedido."""
    try:
        import macro_rentabilidad_canal as MC
        _, v = MC.construir(meses[0], meses[-1])
        v = v[v['tipo_movimiento'].astype(str) == 'Venta']
        return v.groupby(['mes', 'canal', 'Modalidad'])['pedido'].nunique().reset_index(name='pedidos').rename(
            columns={'mes': 'Mes', 'canal': 'Canal'})
    except Exception as e:
        print(f'   [WARN] pedidos por modalidad: {type(e).__name__}: {e}')
        return pd.DataFrame(columns=['Mes', 'Canal', 'Modalidad', 'pedidos'])


def construir(m1=None, sh=None, pendientes=None):
    """Arma el informe del mes cerrado m1 (por defecto, el mes cerrado del plan de acción). Devuelve
    dict(asunto, body, doc, resumen). pendientes = lista de textos de carga faltante (se avisa arriba)."""
    sh = sh or D._abrir(D._cli(), crear_si_falta=False)[0]
    vb = sh.worksheet(D.H_BASE).get_all_values(value_render_option='UNFORMATTED_VALUE')
    b = pd.DataFrame(vb[1:], columns=vb[0])
    b['Monto'] = pd.to_numeric(b['Monto'], errors='coerce').fillna(0)
    b['Mes'] = b['Mes'].map(PA.mes_str)
    vp = sh.worksheet(PA.H_PLAN).get_all_values()
    plan = pd.DataFrame(vp[1:], columns=vp[0])
    plan = plan[plan['ID'].astype(str).str.fullmatch(r'[A-Z]{2,4}-\d+')]
    rol = PA.columnas(plan.columns)
    M1 = m1 or (rol['meses'][-1][1] if rol['meses'] else sorted(b['Mes'].unique())[-2])
    M0 = PA.mes_anterior(M1)
    Mi = PA.mes_anterior(M0)
    MESES = [Mi, M0, M1]
    NOM = {m: PA.lab(m)[:3] for m in MESES}
    LG = {m: LARGO[int(m[5:7])] for m in MESES}
    b = b[b['Mes'].isin(MESES)].copy()
    b['gk'] = b['Glosa'].map(norm)
    ped = pedidos(MESES)
    ING = b[b['Centro de costo'] == 'Ingreso venta'].groupby(['Canal', 'Mes'])['Monto'].sum()
    ING_MOD = b[b['Centro de costo'] == 'Ingreso venta'].groupby(['Canal', 'Modalidad', 'Mes'])['Monto'].sum()
    PED = ped.groupby(['Canal', 'Mes'])['pedidos'].sum()
    PED_MOD = ped.set_index(['Canal', 'Modalidad', 'Mes'])['pedidos']
    MG = b.groupby(['Canal', 'Mes'])['Monto'].sum()
    g_prev_mes = PA.mes_de_col(rol['gestion_prev']) if rol['gestion_prev'] else M0
    g_prev = LARGO[int(g_prev_mes[5:7])] if g_prev_mes else ''

    # ───────────── glosas, oportunidades, modalidades, plan ─────────────
    def glosas_canal(c):
        x = b[(b['Canal'] == c) & b['Centro de costo'].isin(CENTROS + ['Devolución', 'Costo venta'])].copy()
        x['costo'] = -x['Monto']
        etiqueta = x.groupby('gk')['Glosa'].agg(lambda s: s.mode().iat[0]).replace({'': '(sin glosa)'})
        t = x.groupby(['Centro de costo', 'gk', 'Mes'])['costo'].sum().unstack('Mes').reindex(columns=MESES).fillna(0)
        filas = []
        for (cc, gk), r in t.iterrows():
            f = {'centro': cc, 'gk': gk, 'glosa': (etiqueta.get(gk, gk) or '(sin glosa)') if cc not in ('Devolución', 'Costo venta') else
                 ('Devoluciones' if cc == 'Devolución' else 'Costo de venta (producto)')}
            for m in MESES:
                i = float(ING.get((c, m), 0))
                f[m] = float(r[m])
                f['p' + m] = float(r[m]) / i * 100 if i else None
            filas.append(f)
        return filas

    def oportunidad(c, f):
        i1 = float(ING.get((c, M1), 0))
        if f['centro'] == 'Costo venta' or not i1 or f[M1] <= 0:
            return None, ''
        if EVITABLE.search(f['gk']):
            return f[M1], 'cargo evitable → $0'
        meses_con = [m for m in MESES if f[m] > 0 and f['p' + m] is not None]
        if len(meses_con) < 2:
            return None, ''
        m_best = min(meses_con, key=lambda m: f['p' + m])
        if m_best == M1:
            return None, ''
        op = (f['p' + M1] - f['p' + m_best]) / 100 * i1
        return (op, f'mejor mes ({NOM[m_best]}: {pct(f["p" + m_best])})') if op > 0 else (None, '')

    def modalidades(c):
        x = b[b['Canal'] == c]
        out = []
        for mod in sorted(x['Modalidad'].unique()):
            y = x[x['Modalidad'] == mod]
            f = {'mod': mod}
            for m in MESES:
                i = float(ING_MOD.get((c, mod, m), 0))
                z = y[y['Mes'] == m]
                f['v' + m] = i
                f['mg' + m] = float(z['Monto'].sum()) / i * 100 if i else None
                f['com' + m] = -float(z[z['Centro de costo'] == 'Comisión venta']['Monto'].sum()) / i * 100 if i else None
                env = -float(z[z['Centro de costo'] == 'Comisión envío']['Monto'].sum())
                f['env' + m] = env / i * 100 if i else None
                p_ = float(PED_MOD.get((c, mod, m), 0))
                f['ped' + m] = p_
                f['envped' + m] = env / p_ if p_ else None
            if max(f['v' + m] for m in MESES) >= 100_000:          # sin modalidades con venta mínima
                out.append(f)
        return sorted(out, key=lambda f: -f['v' + M1])

    def plan_canal(c):
        cs = {c} | ({'Páginas web'} if c in ('UnionX web', 'Lhotse web', 'Simplit web') else set())
        out = []
        for _, r in plan[plan['Canal'].isin(cs)].iterrows():
            vals = [(PA.lab(m)[:3], str(r.get(h, '')).strip()) for h, m in rol['meses']]
            out.append(dict(id=r['ID'], ind=r['Indicador'], acc=r['Acción'], vals=vals, sem=str(r.get('Semáforo', '')),
                            comp=str(r.get(rol['gestion_prev'] or '', '')).strip()))
        return out

    canales = [c for c in (ING.xs(M1, level='Mes').sort_values(ascending=False).index if len(ING) else [])
               if ING.get((c, M1), 0) >= 1e6 and len(b[(b['Canal'] == c) & b['Centro de costo'].isin(CENTROS)])]
    detalle, ops = [], []
    for c in canales:
        gl = glosas_canal(c)
        for f in gl:
            f['op'], f['ref'] = oportunidad(c, f)
            if f['op'] and f['op'] >= UMBRAL_OP:
                ops.append(dict(canal=c, **f))
        detalle.append(dict(canal=c, glosas=gl, mods=modalidades(c), plan=plan_canal(c)))
    ops.sort(key=lambda o: -o['op'])
    ops_cost = [o for o in ops if o['centro'] != 'Devolución']
    ops_dev = [o for o in ops if o['centro'] == 'Devolución']
    tot_cost = sum(o['op'] for o in ops_cost)
    tot_dev = sum(o['op'] for o in ops_dev)

    # ───────────── HTML (detalle) ─────────────
    def dpp(a, b_):
        if a is None or b_ is None:
            return '<td class="r">—</td>'
        d = b_ - a
        cls = 'up' if d > 0.05 else 'dn' if d < -0.05 else ''
        return f'<td class="r {cls}">{"+" if d > 0 else ""}{n(d)}</td>'

    def tabla_glosas(c, gl):
        filas = []
        nombre = {'Comisión venta': 'Comisión de venta', 'Comisión envío': 'Comisión de envío', 'Marketing': 'Marketing',
                  'Devolución': 'Devoluciones', 'Costo venta': 'Producto'}
        for cc in ['Comisión venta', 'Comisión envío', 'Marketing', 'Devolución', 'Costo venta']:
            g = [f for f in gl if f['centro'] == cc and any(abs(f[m]) > 0.5 for m in MESES)]
            if not g:
                continue
            if cc in CENTROS:
                tot = {m: sum(f[m] for f in g) for m in MESES}
                tp = {m: (tot[m] / ING.get((c, m), 0) * 100 if ING.get((c, m), 0) else None) for m in MESES}
                filas.append(f'<tr class="cc"><td>{nombre[cc]}</td>' + ''.join(f'<td class="r">{clp(tot[m])}</td>' for m in MESES)
                             + ''.join(f'<td class="r">{pct(tp[m])}</td>' for m in MESES) + dpp(tp[M0], tp[M1]) + '<td></td><td></td></tr>')
            for f in sorted(g, key=lambda f: -f[M1]):
                envped = clp(f[M1] / PED.get((c, M1))) if (cc == 'Comisión envío' and PED.get((c, M1), 0)) else ''
                opc = f'<td class="r op">{clp(f["op"])}' if f.get('op') else '<td class="r">—'
                ref = f'<br><span class="sub">{H.escape(f["ref"])}</span>' if f.get('ref') else ''
                filas.append(f'<tr><td>{"&nbsp;&nbsp;" if cc in CENTROS else ""}{H.escape(f["glosa"])}</td>'
                             + ''.join(f'<td class="r">{clp(f[m])}</td>' for m in MESES)
                             + ''.join(f'<td class="r">{pct(f["p" + m])}</td>' for m in MESES) + dpp(f['p' + M0], f['p' + M1])
                             + f'<td class="r">{envped}</td>{opc}{ref}</td></tr>')
        hdr = ('<tr><th>Glosa</th>' + ''.join(f'<th class="r">$ {NOM[m]}</th>' for m in MESES)
               + ''.join(f'<th class="r">% venta {NOM[m]}</th>' for m in MESES)
               + f'<th class="r">Δ p.p. {NOM[M1]} vs {NOM[M0]}</th><th class="r">$/pedido del canal {NOM[M1]}</th><th class="r">Oportunidad $/mes</th></tr>')
        return f'<div class="tw"><table>{hdr}{"".join(filas)}</table></div>'

    def tabla_mods(mods):
        if len(mods) < 2:
            return '<p class="how">Una sola modalidad.</p>'
        hdr = ('<tr><th>Modalidad</th>' + ''.join(f'<th class="r">Venta {NOM[m]}</th>' for m in MESES)
               + f'<th class="r">Pedidos {NOM[M1]}</th>' + ''.join(f'<th class="r">Margen {NOM[m]}</th>' for m in MESES)
               + f'<th class="r">Com. venta {NOM[M1]}</th><th class="r">Envío {NOM[M1]}</th><th class="r">Envío $/pedido {NOM[M0]}</th>'
               f'<th class="r">Envío $/pedido {NOM[M1]}</th></tr>')
        rows = ''.join(f'<tr><td>{H.escape(f["mod"])}</td>' + ''.join(f'<td class="r">{mm(f["v" + m])}</td>' for m in MESES)
                       + f'<td class="r">{n(f["ped" + M1], 0)}</td>' + ''.join(f'<td class="r">{pct(f["mg" + m])}</td>' for m in MESES)
                       + f'<td class="r">{pct(f["com" + M1])}</td><td class="r">{pct(f["env" + M1])}</td>'
                       + f'<td class="r">{clp(f["envped" + M0]) if f["envped" + M0] else "—"}</td>'
                       + f'<td class="r">{clp(f["envped" + M1]) if f["envped" + M1] else "—"}</td></tr>' for f in mods)
        return f'<div class="tw"><table>{hdr}{rows}</table></div>'

    def bloque_plan(pl):
        if not pl:
            return ''
        out = []
        for p in pl:
            tray = ' → '.join(f'{m} {H.escape(v) or "—"}' for m, v in p['vals'])
            comp = (f' · <b>Gestión {g_prev}:</b> «{H.escape(p["comp"])}»' if p['comp']
                    else f' · <b>Gestión {g_prev}:</b> <span class="sub">sin registro</span>')
            out.append(f'<div class="gest"><b>{p["id"]}</b> {H.escape(p["acc"])} — {H.escape(p["ind"])}<br>{tray}{comp} · '
                       f'resultado {NOM[M1].lower()} vs {NOM[M0].lower()}: {chip(p["sem"])}</div>')
        return '<div class="sub" style="margin-top:8px">Plan de acción de este canal</div>' + ''.join(out)

    secciones = []
    for d in detalle:
        c = d['canal']
        i = {m: float(ING.get((c, m), 0)) for m in MESES}
        mg = {m: (float(MG.get((c, m), 0)) / i[m] * 100 if i[m] else None) for m in MESES}
        pe = {m: float(PED.get((c, m), 0)) for m in MESES}
        op_c = sum(f['op'] or 0 for f in d['glosas'] if (f.get('op') or 0) >= UMBRAL_OP)
        meses_t = ' · '.join(NOM[m] for m in MESES)
        kp = (f'<div class="kpis"><div class="k"><span>Venta neta {meses_t}</span><b>{" · ".join(mm(i[m]) for m in MESES)}</b></div>'
              f'<div class="k"><span>Pedidos {meses_t}</span><b>{" · ".join(n(pe[m], 0) for m in MESES)}</b></div>'
              f'<div class="k"><span>Ticket promedio {NOM[M1]}</span><b>{clp(i[M1] / pe[M1]) if pe[M1] else "—"}</b></div>'
              f'<div class="k"><span>Margen {meses_t}</span><b>{" · ".join(pct(mg[m]) for m in MESES)}</b></div>'
              f'<div class="k"><span>Oportunidad identificada</span><b>{clp(op_c) if op_c else "—"} /mes</b></div></div>')
        secciones.append(f'<h3 id="c{len(secciones)}">{H.escape(c)}</h3>{kp}{bloque_plan(d["plan"])}'
                         f'<div class="sub" style="margin-top:10px">Glosa por glosa (costo positivo, abono negativo)</div>{tabla_glosas(c, d["glosas"])}'
                         f'<details><summary>Por modalidad de envío</summary>{tabla_mods(d["mods"])}</details>')

    def filas_top(lista):
        return ''.join(f'<tr><td class="r">{k + 1}</td><td>{H.escape(o["canal"])}</td><td>{H.escape(o["glosa"])}</td><td>{H.escape(o["centro"])}</td>'
                       + ''.join(f'<td class="r">{pct(o["p" + m])}</td>' for m in MESES)
                       + f'<td>{H.escape(o["ref"])}</td><td class="r op">{clp(o["op"])}</td></tr>' for k, o in enumerate(lista))

    th_top = ('<tr><th class="r">#</th><th>Canal</th><th>Glosa</th><th>Centro</th>' + ''.join(f'<th class="r">% venta {NOM[m]}</th>' for m in MESES)
              + '<th>Referencia</th><th class="r">Oportunidad $/mes</th></tr>')
    aviso = (f'<div class="pre"><b>Carga pendiente:</b> {H.escape("; ".join(pendientes))}.</div>') if pendientes else ''
    periodo = f'{LG[Mi].capitalize()} a {LG[M1]} {M1[:4]}'
    indice = ' · '.join(f'<a href="#c{k}">{H.escape(d["canal"])}</a>' for k, d in enumerate(detalle))
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rentabilidad: control de gestión</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Rentabilidad por canal — control de gestión · cierre de {LG[M1]}</h1>
<div class="sub">{periodo} · fuente: macro de rentabilidad (RAW de ventas + carga de Gabriela + lectura de liquidaciones)</div>
{aviso}
<p class="how">Para qué sirve: encontrar dónde podemos ser más rentables. Cada canal se abre glosa por glosa, con su peso sobre la venta y, en logística, por pedido; se compara mes contra mes y por modalidad de envío, y se cruza con lo que se gestionó en el plan de acción. De aquí salen las acciones nuevas.</p>
<h2>1. Resumen: dónde está la plata</h2>
<p class="how">Oportunidad = cuánto margen al mes se recupera si la glosa vuelve a su mejor mes de {LG[Mi]} a {LG[M1]} (como % de la venta de {LG[M1]}), o a $0 si es un cargo evitable (penalidades, multas, retiro o stock antiguo en bodega del marketplace). Solo glosas de costo y devoluciones; desde {clp(UMBRAL_OP)}.</p>
<div class="kpis"><div class="k"><span>Tarifas y cargos</span><b>{clp(tot_cost)} /mes</b></div><div class="k"><span>Devoluciones</span><b>{clp(tot_dev)} /mes</b></div><div class="k"><span>Glosas con oportunidad</span><b>{len(ops)}</b></div></div>
<h3>Tarifas, cargos y servicios (top 15)</h3><p class="how">Lo que se negocia con el canal o se deja de pagar operando distinto.</p>
<div class="tw"><table>{th_top}{filas_top(ops_cost[:15])}</table></div>
<h3>Devoluciones</h3><p class="how">Se registran en el mes de la nota de crédito, así que un salto puede incluir ventas de meses anteriores. Igual muestran dónde mirar primero (entregas fallidas, producto, cliente).</p>
<div class="tw"><table>{th_top}{filas_top(ops_dev)}</table></div>
<h2>2. Detalle por canal</h2><p class="how">{indice}</p>
{''.join(secciones)}
<h2>3. Cómo leerlo</h2>
<ul class="how"><li>% venta = la glosa sobre la venta neta del canal en el mes. Δ p.p. en rojo = esa glosa pesa más que el mes anterior (resta margen); en verde = pesa menos.</li>
<li>$/pedido = costo de la glosa dividido por los pedidos del canal en el mes (solo comisión de envío), para separar tarifa de volumen. En la tabla por modalidad, el envío por pedido es el de cada modalidad.</li>
<li>Las devoluciones se registran en el mes de la nota de crédito y pueden ser de ventas de meses anteriores.</li>
<li>Los cargos que el marketplace informa sin modalidad se reparten entre modalidades según su venta.</li>
<li>Plan de acción: trayectoria del indicador mes a mes, lo que se anotó al cerrar {g_prev} y el resultado de {LG[M1]} contra {LG[M0]}.</li></ul>
</div></body></html>"""

    # ───────────── correo (se sostiene solo) ─────────────
    th = 'style="background:#1e3a5f;color:#fff;padding:5px 8px;text-align:left;font-size:12.5px;white-space:nowrap"'
    thr = 'style="background:#1e3a5f;color:#fff;padding:5px 8px;text-align:right;font-size:12.5px;white-space:nowrap"'
    td = 'style="padding:4px 8px;border-bottom:1px solid #dde3ea;font-size:12.5px;vertical-align:top"'
    tdr = 'style="padding:4px 8px;border-bottom:1px solid #dde3ea;font-size:12.5px;text-align:right;white-space:nowrap"'
    h3 = 'style="color:#1e3a5f;margin:20px 0 6px;font-size:16px"'
    nota = 'style="font-size:12px;color:#64748b;margin:4px 0 0"'

    def cc_pct(c, cc, m):
        i = float(ING.get((c, m), 0))
        x = -float(b[(b['Canal'] == c) & (b['Mes'] == m) & (b['Centro de costo'] == cc)]['Monto'].sum())
        return x / i * 100 if i else None

    def celda_d(c, cc):
        a, z = cc_pct(c, cc, M0), cc_pct(c, cc, M1)
        if z is None or (abs(z) < 0.05 and (a is None or abs(a) < 0.05)):
            return f'<td {tdr}>—</td>'
        if a is None:
            return f'<td {tdr}>{n(z)}%</td>'
        color = '#b42318' if z - a > 0.5 else '#1e7a45' if z - a < -0.5 else '#64748b'
        return f'<td {tdr}>{n(z)}% <span style="color:{color}">({"+" if z - a > 0 else ""}{n(z - a)})</span></td>'

    def mg_pct(c, m):
        i = float(ING.get((c, m), 0))
        return float(MG.get((c, m), 0)) / i * 100 if i else None

    res_rows = ''
    for d in detalle:
        c = d['canal']
        op_c = sum(f['op'] or 0 for f in d['glosas'] if (f.get('op') or 0) >= UMBRAL_OP)
        res_rows += (f'<tr><td {td}><b>{H.escape(c)}</b></td><td {tdr}>{mm(float(ING.get((c, M1), 0)))}</td>'
                     + ''.join(f'<td {tdr}>{pct(mg_pct(c, m))}</td>' for m in MESES)
                     + celda_d(c, 'Comisión venta') + celda_d(c, 'Comisión envío') + celda_d(c, 'Marketing') + celda_d(c, 'Devolución')
                     + f'<td {tdr}><b>{clp(op_c) if op_c else "—"}</b></td></tr>')

    def pedido_de(o):
        pe = float(PED.get((o['canal'], M1), 0))
        return clp(o[M1] / pe) if (o['centro'] == 'Comisión envío' and pe) else '—'

    top_rows = ''.join(f'<tr><td {td}>{H.escape(o["canal"])}</td><td {td}>{H.escape(o["glosa"])}<br>'
                       f'<span style="color:#64748b;font-size:11.5px">{H.escape(o["centro"])}</span></td>'
                       + ''.join(f'<td {tdr}>{pct(o["p" + m])}</td>' for m in MESES)
                       + f'<td {tdr}>{clp(o[M1])}</td><td {tdr}>{pedido_de(o)}</td><td {td}>{H.escape(o["ref"])}</td>'
                       f'<td {tdr}><b>{clp(o["op"])}</b></td></tr>' for o in ops_cost[:10])
    dev_rows = ''.join(f'<tr><td {td}>{H.escape(o["canal"])}</td>' + ''.join(f'<td {tdr}>{pct(o["p" + m])}</td>' for m in MESES)
                       + f'<td {tdr}>{clp(o[M1])}</td><td {tdr}><b>{clp(o["op"])}</b></td></tr>' for o in ops_dev)
    comp_rows, n_bien, n_mal = '', 0, 0
    for _, r in plan.iterrows():
        cm = str(r.get(rol['gestion_prev'] or '', '')).strip()
        if not cm:
            continue
        sem = str(r.get('Semáforo', ''))
        n_bien += sem.startswith('🟢')
        n_mal += sem.startswith('🔴')
        vals = {m: str(r.get(h, '')).strip() for h, m in rol['meses']}
        col_s = '#1e7a45' if sem.startswith('🟢') else '#b42318' if sem.startswith('🔴') else '#a15c07'
        comp_rows += (f'<tr><td {td}><b>{H.escape(r["ID"])}</b></td><td {td}>{H.escape(r["Canal"])}</td><td {td}>{H.escape(r["Acción"])}</td>'
                      f'<td {td}>«{H.escape(cm)}»</td><td {tdr}>{H.escape(vals.get(M0, ""))}</td><td {tdr}>{H.escape(vals.get(M1, ""))}</td>'
                      f'<td {td}><b style="color:{col_s}">{H.escape(sem[2:].strip())}</b></td></tr>')
    sin_comp = [r['ID'] for _, r in plan.iterrows() if not str(r.get(rol['gestion_prev'] or '', '')).strip()]
    nuevos = sorted([(d['canal'], f) for d in detalle for f in d['glosas'] if f['centro'] in CENTROS
                     and f[Mi] <= 0 and f[M0] <= 0 and f[M1] >= UMBRAL_OP], key=lambda t: -t[1][M1])

    bul = []
    if ops_cost:
        o = ops_cost[0]
        sig = (' Le siguen ' + ' y '.join(f'{H.escape(x["glosa"])} ({H.escape(x["canal"])}, {clp(x["op"])})' for x in ops_cost[1:3]) + '.'
               if len(ops_cost) > 2 else '')
        bul.append(f'<b>Tarifas y cargos: {clp(tot_cost)}/mes recuperables.</b> La más grande es {H.escape(o["glosa"])} ({H.escape(o["canal"])}): '
                   f'{pct(o["p" + Mi])} de la venta en {LG[Mi]}, {pct(o["p" + M0])} en {LG[M0]} y {pct(o["p" + M1])} en {LG[M1]}; '
                   f'volver a su mejor mes son {clp(o["op"])}/mes.{sig}')
    if ops_dev:
        bul.append(f'<b>Devoluciones: {clp(tot_dev)}/mes.</b> Las más altas en {LG[M1]}: '
                   + ', '.join(f'{H.escape(o["canal"])} ({pct(o["p" + M1])} de la venta, contra {pct(o["p" + M0])} en {LG[M0]})' for o in ops_dev[:3])
                   + '. Se registran en el mes de la nota de crédito, así que parte puede ser de ventas anteriores.')
    if comp_rows:
        bul.append(f'<b>Plan de acción:</b> de las acciones con gestión anotada en {g_prev}, {n_bien} mejoraron y {n_mal} empeoraron en {LG[M1]}; '
                   f'{len(sin_comp)} acciones no tienen gestión registrada.')
    if nuevos:
        bul.append(f'<b>Costos que aparecen en {LG[M1]}</b> (no estaban en {LG[Mi]} ni {LG[M0]}): '
                   + '; '.join(f'{H.escape(f["glosa"])} en {H.escape(c)} ({clp(f[M1])})' for c, f in nuevos[:4]) + '.')
    tabla_comp = (f'<table style="border-collapse:collapse"><tr><th {th}>ID</th><th {th}>Canal</th><th {th}>Acción</th><th {th}>Lo comprometido</th>'
                  f'<th {thr}>{NOM[M0]}</th><th {thr}>{NOM[M1]}</th><th {th}>Resultado</th></tr>{comp_rows}</table>') if comp_rows \
        else f'<p>No hay gestión registrada de {g_prev}.</p>'
    aviso_mail = (f'<p style="margin:0 0 10px;padding:8px 10px;background:#fef3c7;border-left:3px solid #d97706;font-size:13px">'
                  f'<b>Carga pendiente:</b> {H.escape("; ".join(pendientes))}.</p>') if pendientes else ''
    body = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.5;max-width:980px">
<h2 style="color:#1e3a5f;margin:0 0 2px;font-size:19px">Rentabilidad por canal — control de gestión · cierre de {LG[M1]}</h2>
<div style="color:#64748b;font-size:12px;margin-bottom:10px">{periodo} · <a href="{D_URL()}">planilla macro</a> · adjunto: detalle por canal</div>
{aviso_mail}<p style="margin:0 0 8px">Dónde podemos ser más rentables, canal por canal: qué glosas pesan más sobre la venta que antes, cuánto vale volverlas a su mejor mes y qué pasó con lo que se gestionó en {g_prev}. El HTML adjunto trae cada canal glosa por glosa, por modalidad de envío y por pedido.</p>
<h3 {h3}>Lo principal</h3><ul style="margin:0 0 6px 18px;padding:0">{''.join(f'<li style="margin-bottom:6px">{x}</li>' for x in bul)}</ul>
<h3 {h3}>1. Resumen por canal</h3>
<table style="border-collapse:collapse"><tr><th {th}>Canal</th><th {thr}>Venta {NOM[M1]}</th>{''.join(f'<th {thr}>Margen {NOM[m]}</th>' for m in MESES)}<th {thr}>Com. venta</th><th {thr}>Com. envío</th><th {thr}>Marketing</th><th {thr}>Devoluciones</th><th {thr}>Oportunidad $/mes</th></tr>{res_rows}</table>
<p {nota}>Centros de costo como % de la venta de {LG[M1]}; entre paréntesis, la variación en puntos contra {LG[M0]} (rojo = pesa más, verde = pesa menos).</p>
<h3 {h3}>2. Tarifas, cargos y servicios: dónde está la plata (top 10)</h3>
<table style="border-collapse:collapse"><tr><th {th}>Canal</th><th {th}>Glosa</th>{''.join(f'<th {thr}>% venta {NOM[m]}</th>' for m in MESES)}<th {thr}>$ {NOM[M1]}</th><th {thr}>$/pedido</th><th {th}>Referencia</th><th {thr}>Oportunidad $/mes</th></tr>{top_rows}</table>
<p {nota}>Oportunidad = volver al mejor mes de {LG[Mi]} a {LG[M1]} (o a $0 si es un cargo evitable: penalidades, multas, retiro o stock antiguo). $/pedido solo en comisión de envío.</p>
<h3 {h3}>3. Devoluciones</h3>
<table style="border-collapse:collapse"><tr><th {th}>Canal</th>{''.join(f'<th {thr}>% venta {NOM[m]}</th>' for m in MESES)}<th {thr}>$ {NOM[M1]}</th><th {thr}>Oportunidad $/mes</th></tr>{dev_rows}</table>
<h3 {h3}>4. Compromisos de {g_prev} → resultado en {LG[M1]}</h3>
{tabla_comp}
<p {nota}>Sin gestión registrada: {", ".join(sin_comp) if sin_comp else "ninguna"}. La gestión de {LG[M1]} se anota en la pestaña 8 de la planilla.</p>
<p style="font-size:12px;color:#64748b;margin-top:14px">Detalle glosa por glosa, por modalidad y por pedido: HTML adjunto. Informe automático del cierre de cada mes, junto al de venta, margen y razones.</p></div>"""
    asunto = f'Rentabilidad por canal — control de gestión del cierre de {LG[M1]}: dónde ser más rentables'
    return dict(asunto=asunto, body=body, doc=doc, M1=M1,
                resumen=dict(canales=len(detalle), oportunidades=len(ops), tarifas=tot_cost, devoluciones=tot_dev))


def D_URL():
    import rentabilidad_reporte_semanal as R
    return R.URL_SHEET


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--mes', default=None)
    ap.add_argument('--out', default=tempfile.gettempdir())
    a = ap.parse_args()
    r = construir(a.mes)
    Path(a.out, 'rentabilidad_control_gestion.html').write_text(r['doc'], encoding='utf-8')
    Path(a.out, 'rentabilidad_control_gestion_correo.html').write_text(r['body'], encoding='utf-8')
    print(f"[control] {r['M1']} · {r['resumen']}")
