# -*- coding: utf-8 -*-
"""Seguimiento del plan de acción de rentabilidad por canal.

Cada acción del informe mensual tiene UN indicador medible que sale de la propia
macro (RAW de ventas + carga de Gabriela). Este script lo recalcula y lo deja en
la pestaña "8. Plan de acción" del Sheet compartido:

  · Columnas automáticas (A–L): id, canal, acción, indicador, base ago-26, meta
    propuesta, último mes con carga, valor, mes en curso (solo RAW), Δ, semáforo.
    Se reescriben en cada corrida.
  · Columnas de gestión (M–P): responsable, fecha compromiso, estado, última
    gestión. Son de las personas: se preservan por id entre corridas.

Semáforo: verde si el indicador se movió en la dirección buscada (≥ 0,5 p.p. o
≥ 5% del valor base), rojo si se movió en contra, amarillo si está plano. Cuando
hay meta y ya se alcanzó, verde aunque el movimiento sea chico.

Uso:
    python macro_plan_accion.py            # lee el Sheet y escribe la pestaña
    python macro_plan_accion.py --dry-run  # solo imprime la tabla
Lo llama el workflow del lunes después de refrescar la macro.
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

H_PLAN = '8. Plan de acción'
M_BASE = '2026-08'                    # mes del informe que originó el plan
MOD_MAP = {'colecta': 'Colecta', 'fulfillment': 'Fulfillment', 'flex': 'Envío directo',
           'flex (flota propia)': 'Envío directo', 'envío directo': 'Envío directo', 'envio directo': 'Envío directo'}
COLS_AUTO = ['ID', 'Canal', 'Acción', 'Indicador', 'Unidad', f'Base {M_BASE}', 'Meta propuesta',
             'Último mes con carga', 'Valor último mes', 'Mes en curso (solo RAW)', 'Δ vs base', 'Semáforo']
COLS_GESTION = ['Responsable', 'Fecha compromiso', 'Estado', 'Última gestión (quién / qué / cuándo)']
COLS = COLS_AUTO + COLS_GESTION


def mes_str(x):
    s = str(x).strip()
    if len(s) >= 7 and s[4] == '-':
        return s[:7]
    try:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(s)))).strftime('%Y-%m')
    except ValueError:
        return s


class Ctx:
    """Indicadores sobre la base (Monto con signo) y la carga de Gabriela (Valor)."""

    def __init__(self, base, gab):
        self.base = base.copy()
        self.base['Mes'] = self.base['Mes'].map(mes_str)
        g = gab.copy()
        g = g[g['Valor'].astype(str).str.strip().ne('')].copy()
        g['Valor'] = pd.to_numeric(g['Valor'], errors='coerce').fillna(0)
        g = g[g['Valor'] != 0]
        g['Mes'] = g['Mes'].map(mes_str)
        g['Canal'] = g['Canal'].astype(str).str.strip().replace({'Mercado Libre 2': 'Mercado Libre'})
        g['glosa_k'] = g['Glosa'].astype(str).str.strip().str.lower()
        g['mod'] = g['Modalidad'].astype(str).str.strip().str.lower().map(MOD_MAP).fillna('')
        g['Valor'] = -g['Valor']          # costo negativo, abono positivo
        self.gab = g
        raw = self.base[self.base['Fuente'] == 'RAW ventas']
        ing = raw[raw['Centro de costo'] == 'Ingreso venta']
        self.ING = ing.groupby(['Canal', 'Mes'])['Monto'].sum()
        self.ING_MOD = ing.groupby(['Canal', 'Modalidad', 'Mes'])['Monto'].sum()
        self.meses_gab = sorted(g['Mes'].unique())
        self.meses_raw = sorted(ing['Mes'].unique())

    # --- helpers ---
    def ing(self, c, m):
        return float(self.ING.get((c, m), 0))

    def pct_glosa(self, c, sub, m):
        i = self.ing(c, m)
        if not i:
            return None
        x = self.gab[(self.gab['Canal'] == c) & (self.gab['Mes'] == m) & self.gab['glosa_k'].str.contains(sub.lower(), regex=False)]
        return float(x['Valor'].sum()) / i * 100

    def clp_glosa(self, c, sub, m):
        x = self.gab[(self.gab['Canal'] == c) & (self.gab['Mes'] == m) & self.gab['glosa_k'].str.contains(sub.lower(), regex=False)]
        return float(x['Valor'].sum()) if len(x) else 0.0

    def share_mod(self, c, mod, m):
        i = self.ing(c, m)
        return float(self.ING_MOD.get((c, mod, m), 0)) / i * 100 if i else None

    def mg_mod(self, c, mod, m):
        i = float(self.ING_MOD.get((c, mod, m), 0))
        if not i:
            return None
        b = self.base
        return float(b[(b['Canal'] == c) & (b['Modalidad'] == mod) & (b['Mes'] == m)]['Monto'].sum()) / i * 100

    def brecha_mod(self, c, a, b, m):
        x, y = self.mg_mod(c, a, m), self.mg_mod(c, b, m)
        return None if x is None or y is None else x - y

    def pct_sin_mod(self, c, m):
        x = self.gab[(self.gab['Canal'] == c) & (self.gab['Mes'] == m)]
        tot = x['Valor'].abs().sum()
        return float(x[x['mod'] == '']['Valor'].abs().sum()) / tot * 100 if tot else None

    def glosas_partidas(self, m):
        x = self.gab[self.gab['Mes'] == m]
        n = x.groupby(['Canal', 'glosa_k'])['Glosa'].agg(lambda s: s.str.strip().nunique())
        return int((n > 1).sum())


# (id, canal, acción, indicador, unidad, fuente raw|gab, mejor sube|baja|mantiene, fn(ctx, mes), meta fn(ctx) | None, responsable)
PLAN = [
    ('FAL-1', 'Falabella', 'Negociar / verificar la tarifa de comisión', 'Glosa "Comisiones" como % del ingreso', '%', 'gab', 'sube',
     lambda x, m: x.pct_glosa('Falabella', 'comisiones', m), lambda x: x.pct_glosa('Falabella', 'comisiones', '2026-07'), 'Comercial (KAM Falabella)'),
    ('FAL-2', 'Falabella', 'Revisar el cofinanciamiento logístico', 'Glosa "Cofinanciamiento" como % del ingreso', '%', 'gab', 'sube',
     lambda x, m: x.pct_glosa('Falabella', 'cofinanciamiento', m), lambda x: x.pct_glosa('Falabella', 'cofinanciamiento', '2026-07'), 'Comercial (KAM Falabella)'),
    ('ML-1', 'Mercado Libre', 'Mover mix de Colecta a Flex', 'Share de Envío directo (Flex) en el ingreso del canal', '%', 'raw', 'sube',
     lambda x, m: x.share_mod('Mercado Libre', 'Envío directo', m),
     lambda x: (x.share_mod('Mercado Libre', 'Envío directo', M_BASE) or 0) + 0.25 * (x.share_mod('Mercado Libre', 'Colecta', M_BASE) or 0), 'Comercial + Operaciones'),
    ('ML-2', 'Mercado Libre', 'Entender por qué Flex paga más comisión de venta', 'Brecha de margen Flex − Colecta (p.p.)', 'p.p.', 'gab', 'mantiene',
     lambda x, m: x.brecha_mod('Mercado Libre', 'Envío directo', 'Colecta', m), None, 'Comercial'),
    ('ML-3', 'Mercado Libre', 'Revisar el retiro de stock Full', 'Glosa "Cargo por retiro de stock Full" ($)', '$', 'gab', 'sube',
     lambda x, m: x.clp_glosa('Mercado Libre', 'retiro de stock full', m), lambda x: 0.0, 'Operaciones'),
    ('RIP-1', 'Ripley', 'Sostener la tarifa de primera milla', 'Glosa "primera milla" como % del ingreso', '%', 'gab', 'mantiene',
     lambda x, m: x.pct_glosa('Ripley', 'primera milla', m), lambda x: x.pct_glosa('Ripley', 'primera milla', M_BASE), 'Comercial (KAM Ripley)'),
    ('RIP-2', 'Ripley', 'Validar el retorno de la campaña Simplit', 'Glosas "CAMPAÑA COMERCIAL" ($)', '$', 'gab', 'sube',
     lambda x, m: x.clp_glosa('Ripley', 'campaña comercial', m), None, 'Comercial (KAM Ripley) + Marketing'),
    ('PAR-1', 'Paris', 'Confirmar si el cargo de marketing es puntual', 'Glosa "SERV. MARKETING DIGITAL" ($)', '$', 'gab', 'sube',
     lambda x, m: x.clp_glosa('Paris', 'marketing digital', m), lambda x: 0.0, 'Comercial (KAM Paris) + Marketing'),
    ('PAR-2', 'Paris', 'Seguir moviendo el mix a Fulfillment', 'Share de Fulfillment en el ingreso del canal', '%', 'raw', 'sube',
     lambda x, m: x.share_mod('Paris', 'Fulfillment', m), None, 'Comercial (KAM Paris)'),
    ('WAL-1', 'Walmart', 'Empujar WFS', 'Share de Fulfillment (WFS) en el ingreso del canal', '%', 'raw', 'sube',
     lambda x, m: x.share_mod('Walmart', 'Fulfillment', m), None, 'Comercial + Operaciones'),
    ('TOD-1', 'Todos', 'Cargar la modalidad siempre que la liquidación la informe', '% de la carga de Mercado Libre sin modalidad', '%', 'gab', 'baja',
     lambda x, m: x.pct_sin_mod('Mercado Libre', m), lambda x: 10.0, 'Gabriela'),
    ('TOD-2', 'Todos', 'Cargar la modalidad siempre que la liquidación la informe', '% de la carga de Falabella sin modalidad', '%', 'gab', 'baja',
     lambda x, m: x.pct_sin_mod('Falabella', m), lambda x: 10.0, 'Gabriela'),
    ('TOD-3', 'Todos', 'Higiene de glosas (mayúsculas, nombres)', 'Glosas partidas en dos por escritura distinta (n)', 'n', 'gab', 'baja',
     lambda x, m: float(x.glosas_partidas(m)), lambda x: 0.0, 'Gabriela'),
]


def _sem(base, ult, meta, mejor, unidad):
    if base is None or ult is None:
        return '⚪ sin dato'
    d = ult - base
    umbral = 0.5 if unidad in ('%', 'p.p.') else (1 if unidad == 'n' else max(abs(base) * 0.05, 1))
    if meta is not None:
        ok = (ult >= meta - 1e-9) if mejor == 'sube' else (ult <= meta + 1e-9) if mejor == 'baja' else abs(ult - meta) <= umbral
        if ok:
            return '🟢 en meta'
    if abs(d) < umbral:
        return '🟡 plano' if mejor != 'mantiene' else '🟢 se sostiene'
    if mejor == 'mantiene':
        return '🔴 se movió' if d < 0 else '🟢 mejoró'
    bien = d > 0 if mejor == 'sube' else d < 0
    return '🟢 mejora' if bien else '🔴 empeora'


def calcular(base, gab):
    x = Ctx(base, gab)
    m_gab = x.meses_gab[-1] if x.meses_gab else None
    m_raw = x.meses_raw[-1] if x.meses_raw else None
    filas = []
    for pid, canal, accion, ind, uni, fuente, mejor, fn, meta_fn, resp in PLAN:
        b = fn(x, M_BASE)
        meta = meta_fn(x) if meta_fn else None
        ult = fn(x, m_gab) if m_gab else None
        cur = fn(x, m_raw) if (fuente == 'raw' and m_raw and m_raw != m_gab) else None
        ref = cur if cur is not None else ult
        filas.append({'ID': pid, 'Canal': canal, 'Acción': accion, 'Indicador': ind, 'Unidad': uni,
                      f'Base {M_BASE}': b, 'Meta propuesta': meta, 'Último mes con carga': m_gab, 'Valor último mes': ult,
                      'Mes en curso (solo RAW)': (f'{m_raw}: ' + _fmt(cur, uni)) if cur is not None else '',
                      'Δ vs base': (ref - b) if (ref is not None and b is not None) else None,
                      'Semáforo': _sem(b, ref, meta, mejor, uni), 'Responsable': resp,
                      'Fecha compromiso': '', 'Estado': 'Abierta', 'Última gestión (quién / qué / cuándo)': ''})
    return pd.DataFrame(filas, columns=COLS), x


def _fmt(v, uni):
    if v is None or pd.isna(v):
        return ''
    if uni == '$':
        return ('-' if v < 0 else '') + '$' + f'{abs(v):,.0f}'.replace(',', '.')
    if uni == 'n':
        return f'{int(round(v))}'
    return f'{v:,.1f}'.replace(',', 'X').replace('.', ',').replace('X', '.') + (' p.p.' if uni == 'p.p.' else '%')


def leer_sheet():
    import macro_rentabilidad_drive as D
    gc = D._cli()
    sh, _ = D._abrir(gc, crear_si_falta=False)
    vb = sh.worksheet(D.H_BASE).get_all_values(value_render_option='UNFORMATTED_VALUE')
    base = pd.DataFrame(vb[1:], columns=vb[0])
    base['Monto'] = pd.to_numeric(base['Monto'], errors='coerce').fillna(0)
    vg = sh.worksheet(D.H_GAB).get_all_values(value_render_option='UNFORMATTED_VALUE')
    gab = pd.DataFrame(vg[1:], columns=vg[0])
    return sh, base, gab


def escribir(sh, df):
    import gspread
    try:
        ws = sh.worksheet(H_PLAN)
        prev = ws.get_all_values()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=H_PLAN, rows=80, cols=len(COLS) + 2)
        prev = []
    # preservar la gestión por ID
    if prev and len(prev) > 1 and 'ID' in prev[0]:
        p = pd.DataFrame(prev[1:], columns=prev[0])
        if 'ID' in p.columns:
            p = p.set_index('ID')
            for c in COLS_GESTION:
                if c in p.columns:
                    keep = p[c].reindex(df['ID']).fillna('').astype(str).str.strip().values
                    df[c] = [k if k else d for k, d in zip(keep, df[c])]
    out = df.copy()
    for c in [f'Base {M_BASE}', 'Meta propuesta', 'Valor último mes', 'Δ vs base']:
        out[c] = [(_fmt(v, u) if v is not None and not pd.isna(v) else '') for v, u in zip(out[c], out['Unidad'])]
    ws.clear()
    ws.update([COLS] + out.astype(object).where(pd.notna(out), '').values.tolist(), value_input_option='RAW')
    n = len(out) + 3
    ws.update(f'A{n}', [[f'Base = {M_BASE} (mes del informe). Columnas A–L las recalcula el proceso cada lunes; M–P son de gestión y se conservan. '
                         'Semáforo: verde = se mueve hacia la meta (o ya está), rojo = en contra, amarillo = plano. Revisión mensual con el informe de rentabilidad.']],
              value_input_option='RAW')
    ws.freeze(rows=1)
    ws.format(f'A1:{chr(64 + len(COLS))}1', {'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                                           'backgroundColor': {'red': .118, 'green': .227, 'blue': .373}, 'wrapStrategy': 'WRAP'})
    ws.format(f'M2:P{len(out) + 1}', {'backgroundColor': {'red': 1, 'green': .973, 'blue': .863}})   # amarillo = editable
    for col, w in zip('ABCDEFGHIJKLMNOP', [7, 14, 34, 36, 6, 12, 12, 12, 12, 16, 11, 13, 22, 12, 10, 40]):
        sh.batch_update({'requests': [{'updateDimensionProperties': {
            'range': {'sheetId': ws.id, 'dimension': 'COLUMNS', 'startIndex': ord(col) - 65, 'endIndex': ord(col) - 64},
            'properties': {'pixelSize': w * 8}, 'fields': 'pixelSize'}}]})
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    sh, base, gab = leer_sheet()
    df, x = calcular(base, gab)
    pd.set_option('display.width', 250)
    show = df[['ID', 'Canal', 'Indicador', 'Unidad', f'Base {M_BASE}', 'Meta propuesta', 'Valor último mes', 'Mes en curso (solo RAW)', 'Δ vs base', 'Semáforo']].copy()
    for c in [f'Base {M_BASE}', 'Meta propuesta', 'Valor último mes', 'Δ vs base']:
        show[c] = [_fmt(v, u) for v, u in zip(show[c], show['Unidad'])]
    print(show.to_string(index=False))
    print(f'\nÚltimo mes con carga de Gabriela: {x.meses_gab[-1] if x.meses_gab else "—"} · RAW hasta {x.meses_raw[-1] if x.meses_raw else "—"}')
    if a.dry_run:
        return
    escribir(sh, df)
    print(f'[{H_PLAN}] {len(df)} indicadores escritos · {sh.url}')


if __name__ == '__main__':
    main()
