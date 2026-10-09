# -*- coding: utf-8 -*-
"""Seguimiento del plan de acción de rentabilidad por canal.

Cada acción del informe mensual tiene UN indicador medible que sale de la propia
macro (RAW de ventas + carga de Gabriela). Este script lo recalcula y lo deja en
la pestaña "8. Plan de acción" del Sheet compartido:

  · Columnas automáticas: id, canal, prioridad, acción, indicador, meta propuesta, UNA COLUMNA POR MES
    (los últimos cuatro meses cerrados; ago-26 es la base), mes en curso (solo RAW), resultado del mes
    (último mes cerrado contra el anterior) y semáforo. Se reescriben en cada corrida.
  · Columnas de gestión: responsable, fecha compromiso, estado, la gestión del mes anterior (lo que se
    comprometió, fija) y la gestión del mes en curso (editable). Al cerrar un mes, lo escrito se guarda en
    la pestaña "8b. Historial plan" y la columna editable parte vacía para el mes nuevo (Andrés 9-oct).

Semáforo del resultado del mes: verde si el indicador se movió en la dirección buscada (≥ 0,5 p.p. o ≥ 5%
del valor anterior), rojo si se movió en contra, amarillo si está plano. Cuando hay meta y ya se alcanzó,
verde aunque el movimiento sea chico.

Uso:
    python macro_plan_accion.py            # lee el Sheet y escribe la pestaña
    python macro_plan_accion.py --dry-run  # solo imprime la tabla
Lo llama el workflow del lunes después de refrescar la macro.
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

H_PLAN = '8. Plan de acción'
H_HIST = '8b. Historial plan'
M_BASE = '2026-08'                    # mes del informe que originó el plan
MES_INICIO = '2026-07'                # primer mes de la serie (el de la meta "tasa de julio")
N_MESES = 4                           # meses cerrados que se muestran
MES_CORTO = {1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun', 7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct',
             11: 'Nov', 12: 'Dic'}
MES_NUM = {v: k for k, v in MES_CORTO.items()}
MOD_MAP = {'colecta': 'Colecta', 'fulfillment': 'Fulfillment', 'flex': 'Envío directo',
           'flex (flota propia)': 'Envío directo', 'envío directo': 'Envío directo', 'envio directo': 'Envío directo'}
WEBS = ['Simplit web', 'Lhotse web', 'UnionX web']
COLS_IZQ = ['ID', 'Canal', 'Prioridad (share de venta)', 'Acción', 'Indicador', 'Unidad', 'Meta propuesta']
COLS_DER = ['Mes en curso (solo RAW)', 'Resultado del mes', 'Semáforo']
COLS_GESTION = ['Responsable', 'Fecha compromiso', 'Estado']
GESTION_LEGACY = 'Última gestión (quién / qué / cuándo)'      # columna única de gestión hasta el 9-oct (= agosto)
COLS_HIST = ['Mes de cierre', 'ID', 'Canal', 'Acción', 'Indicador', 'Valor del mes', 'Gestión', 'Responsable', 'Estado',
             'Guardado el']


def lab(m):
    """'2026-09' → 'Sep-26'."""
    return f'{MES_CORTO[int(m[5:7])]}-{m[2:4]}'


def col_mes(m):
    return lab(m) + (' (base)' if m == M_BASE else '')


def mes_de_col(h):
    """'Sep-26', 'Ago-26 (base)' o 'Gestión Sep-26 (…)' → '2026-09'."""
    mm = re.match(r'^(?:Gestión )?([A-Z][a-z]{2})-(\d\d)', str(h).strip())
    return f'20{mm.group(2)}-{MES_NUM[mm.group(1)]:02d}' if mm and mm.group(1) in MES_NUM else None


def col_gestion_prev(m):
    return f'Gestión {lab(m)} (comprometido)'


def col_gestion_cur(m):
    return f'Gestión {lab(m)} (escribir aquí)'


def mes_anterior(m):
    y, mo = int(m[:4]), int(m[5:7])
    return f'{y - 1}-12' if mo == 1 else f'{y}-{mo - 1:02d}'


def columnas(hdr):
    """Columnas de la pestaña por rol (para el reporte): meses [(encabezado, 'YYYY-MM')], gestión fija y editable."""
    hdr = [str(h) for h in hdr]
    return dict(meses=[(h, mes_de_col(h)) for h in hdr if mes_de_col(h) and not h.startswith('Gestión')],
                gestion_prev=next((h for h in hdr if h.endswith('(comprometido)')), None),
                gestion_cur=next((h for h in hdr if h.endswith('(escribir aquí)')), None) or (GESTION_LEGACY if GESTION_LEGACY in hdr else None))


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

    def __init__(self, base, gab, liq=None):
        import macro_rentabilidad_drive as D
        self.base = base.copy()
        self.base['Mes'] = self.base['Mes'].map(mes_str)
        raw = self.base[self.base['Fuente'] == 'RAW ventas']
        ing = raw[raw['Centro de costo'] == 'Ingreso venta']
        self.ING = ing.groupby(['Canal', 'Mes'])['Monto'].sum()
        self.ING_MOD = ing.groupby(['Canal', 'Modalidad', 'Mes'])['Monto'].sum()

        def limpio(x, fuente):
            x = x.copy()
            x = x[x['Valor'].astype(str).str.strip().ne('')].copy()
            x['Valor'] = pd.to_numeric(x['Valor'], errors='coerce').fillna(0)
            x = x[x['Valor'] != 0]
            x['Mes'] = x['Mes'].map(mes_str)
            x['Canal'] = D.canonizar(x['Canal'].astype(str), raw['Canal'].unique())
            x['Centro de costo'] = x['Centro de costo'].astype(str).str.strip().str.capitalize().replace(
                {'Comisión envio': 'Comisión envío', 'Comision envío': 'Comisión envío'})
            x = x[x['Centro de costo'].isin(D.CC_GABRIELA)]     # mismo filtro que la base (D.gab_df)
            x['Fuente'] = fuente
            return x
        # costos comerciales = carga de Gabriela o lectura de sus liquidaciones, la más completa por
        # canal × mes × centro (la misma regla de la base, D.combinar): el plan recoge lo que ya está en la carpeta
        g = limpio(gab, 'Gabriela')
        self.con_carga = set(zip(g['Canal'], g['Mes']))       # canal × mes que Gabriela ya cargó
        solo = g.copy()                                        # indicadores de higiene de SU carga (TOD-*)
        solo['glosa_k'] = solo['Glosa'].astype(str).str.strip().str.lower()
        solo['mod'] = solo['Modalidad'].astype(str).str.strip().str.lower().map(MOD_MAP).fillna('')
        self.solo_gab = solo
        l = limpio(liq, 'Liquidación') if liq is not None and len(liq) else None
        g = D.combinar(g, l)
        g['glosa_k'] = g['Glosa'].astype(str).str.strip().str.lower()
        g['mod'] = g['Modalidad'].astype(str).str.strip().str.lower().map(MOD_MAP).fillna('')
        # Mes de comparación = último mes con los cinco marketplaces CARGADOS: costo comercial de al menos
        # 10% de su ingreso (un canal a medio cargar, ej. Mercado Libre sep con $3,7M sobre $130M, daba
        # semáforos falsos).
        MK = ['Mercado Libre', 'Falabella', 'Walmart', 'Paris', 'Ripley']
        costo = g.groupby(['Canal', 'Mes'])['Valor'].sum()

        def cargado(c, m):
            i = float(self.ING.get((c, m), 0))
            return i > 0 and float(costo.get((c, m), 0)) / i >= 0.10
        meses = sorted(g['Mes'].unique())
        completos = [m for m in meses if all(cargado(c, m) for c in MK)]
        # Último mes cargado de CADA canal: cada indicador se mide en el último mes de su canal (Andrés 6-oct:
        # el plan no recogía lo nuevo porque esperaba a que los cinco marketplaces estuvieran completos).
        self.meses_canal = {c: [m for m in meses if cargado(c, m)] for c in MK}
        # canales fuera de los cinco marketplaces: último mes con costo comercial cargado (carga o lectura)
        self.meses_costo = g.groupby('Canal')['Mes'].apply(lambda s_: sorted(s_.unique())).to_dict()
        g['Valor'] = -g['Valor']          # costo negativo, abono positivo
        self.gab = g
        self.meses_gab = completos or meses
        self.meses_raw = sorted(ing['Mes'].unique())
        dev = self.base[self.base['Centro de costo'] == 'Devolución']
        self.DEV = dev.groupby(['Canal', 'Mes'])['Monto'].sum()
        # participación en la venta del último mes completo del RAW (el último del RAW es el mes en curso)
        self.m_share = self.meses_raw[-2] if len(self.meses_raw) > 1 else (self.meses_raw[-1] if self.meses_raw else None)
        tot = float(ing[ing['Mes'] == self.m_share]['Monto'].sum()) if self.m_share else 0
        self.SHARE = {c: float(v) / tot * 100 for c, v in ing[ing['Mes'] == self.m_share].groupby('Canal')['Monto'].sum().items()} if tot else {}

    # --- helpers ---
    def ing(self, c, m):
        if isinstance(c, (list, tuple)):
            return sum(float(self.ING.get((x, m), 0)) for x in c)
        return float(self.ING.get((c, m), 0))

    def pct_cc(self, c, cc, m):
        """Centro de costo (carga o lectura) como % del ingreso; c puede ser una lista de canales."""
        cs = c if isinstance(c, (list, tuple)) else [c]
        i = self.ing(cs, m)
        if not i:
            return None
        x = self.gab[self.gab['Canal'].isin(cs) & (self.gab['Mes'] == m) & (self.gab['Centro de costo'] == cc)]
        if not len(x):
            return None
        return float(x['Valor'].sum()) / i * 100

    def dev_pct(self, c, m):
        i = self.ing(c, m)
        return float(self.DEV.get((c, m), 0)) / i * 100 if i else None

    def share(self, c):
        cs = c if isinstance(c, (list, tuple)) else [c]
        return sum(self.SHARE.get(x, 0) for x in cs)

    def ultimo_mes(self, canal, m_gab):
        if canal in self.meses_canal:
            return (self.meses_canal.get(canal) or [m_gab])[-1]
        cs = WEBS if canal == 'Páginas web' else [canal]
        ms = sorted({m for c in cs for m in self.meses_costo.get(c, [])})
        return ms[-1] if ms else m_gab

    def pct_glosa(self, c, sub, m):
        i = self.ing(c, m)
        if not i:
            return None
        x = self.gab[(self.gab['Canal'] == c) & (self.gab['Mes'] == m) & self.gab['glosa_k'].str.contains(sub.lower(), regex=False)]
        if not len(x) and (c, m) not in self.con_carga:
            return None          # solo está la lectura automática y la glosa no viene en la liquidación
        return float(x['Valor'].sum()) / i * 100

    def clp_glosa(self, c, sub, m):
        x = self.gab[(self.gab['Canal'] == c) & (self.gab['Mes'] == m) & self.gab['glosa_k'].str.contains(sub.lower(), regex=False)]
        if not len(x) and (c, m) not in self.con_carga:
            return None          # ej. marketing de Paris: documento aparte que Gabriela aún no carga
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
        x = self.solo_gab[(self.solo_gab['Canal'] == c) & (self.solo_gab['Mes'] == m)]
        tot = x['Valor'].abs().sum()
        return float(x[x['mod'] == '']['Valor'].abs().sum()) / tot * 100 if tot else None

    def glosas_partidas(self, m):
        x = self.solo_gab[self.solo_gab['Mes'] == m]
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
    ('KC-1', 'Kitchen Center', 'Verificar la comisión de KC contra el contrato (20%)', 'Comisión de venta como % del ingreso', '%', 'gab', 'sube',
     lambda x, m: x.pct_cc('Kitchen Center', 'Comisión venta', m), lambda x: -20.0, 'Comercial (KAM Kitchen Center)'),
    ('PAR-3', 'Paris', 'Bajar las devoluciones (entregas fallidas del courier de Paris)', 'Devoluciones como % del ingreso', '%', 'gab', 'sube',
     lambda x, m: x.dev_pct('Paris', m), lambda x: x.dev_pct('Paris', '2026-07'), 'Comercial (KAM Paris) + Operaciones'),
    ('FAL-3', 'Falabella', 'Bajar las devoluciones', 'Devoluciones como % del ingreso', '%', 'gab', 'sube',
     lambda x, m: x.dev_pct('Falabella', m), lambda x: x.dev_pct('Falabella', '2026-07'), 'Comercial (KAM Falabella) + Operaciones'),
    ('WEB-1', 'Páginas web', 'Llevar el marketing de las webs al 10% de la venta', 'Marketing como % del ingreso (Simplit, Lhotse y UnionX web)', '%', 'gab', 'sube',
     lambda x, m: x.pct_cc(WEBS, 'Marketing', m), lambda x: -10.0, 'Martín + Marketing'),
    ('WEB-2', 'Páginas web', 'Revisar el costo de envío de las webs', 'Comisión de envío como % del ingreso (webs)', '%', 'gab', 'sube',
     lambda x, m: x.pct_cc(WEBS, 'Comisión envío', m), None, 'Martín + Operaciones'),
    ('LAT-1', 'LATAM Pass', 'Revisar el costo de couriers de LATAM', 'Comisión de envío como % del ingreso', '%', 'gab', 'sube',
     lambda x, m: x.pct_cc('LATAM Pass', 'Comisión envío', m), None, 'Martín'),
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


def calcular(base, gab, liq=None):
    """Una fila por acción con el indicador de cada mes cerrado (los últimos N_MESES desde MES_INICIO), el mes en
    curso (solo indicadores del RAW) y el resultado del último mes cerrado contra el anterior."""
    x = Ctx(base, gab, liq)
    m_cierre = x.m_share                                 # último mes completo del RAW (el último es el mes en curso)
    m_prev = mes_anterior(m_cierre) if m_cierre else None
    m_raw = x.meses_raw[-1] if x.meses_raw else None
    meses = [m for m in x.meses_raw if MES_INICIO <= m <= (m_cierre or '')][-N_MESES:]
    filas = []
    for pid, canal, accion, ind, uni, fuente, mejor, fn, meta_fn, resp in PLAN:
        vals = {m: fn(x, m) for m in sorted(set(meses) | ({m_prev} if m_prev else set()))}
        meta = meta_fn(x) if meta_fn else None
        ult, ant = vals.get(m_cierre), vals.get(m_prev)
        cur = fn(x, m_raw) if (fuente == 'raw' and m_raw and m_raw != m_cierre) else None
        sh_ = x.share(WEBS if canal == 'Páginas web' else canal) if canal != 'Todos' else None
        prio = ('⚪ Transversal' if sh_ is None else ('🔴 Alta' if sh_ >= 15 else '🟡 Media' if sh_ >= 5 else '🟢 Baja')
                + ('' if sh_ is None else f' · {sh_:.0f}%'.replace('.', ',')))
        fila = {'ID': pid, 'Canal': canal, 'Prioridad (share de venta)': prio, '_share': -1 if sh_ is None else sh_,
                'Acción': accion, 'Indicador': ind, 'Unidad': uni, 'Meta propuesta': meta, '_mejor': mejor}
        fila.update({col_mes(m): vals.get(m) for m in meses})
        fila.update({'Mes en curso (solo RAW)': (f'{lab(m_raw)}: ' + _fmt(cur, uni)) if cur is not None else '',
                     'Resultado del mes': (ult - ant) if (ult is not None and ant is not None) else None,
                     'Semáforo': _sem(ant, ult, meta, mejor, uni), 'Responsable': resp, 'Fecha compromiso': '',
                     'Estado': 'Abierta', '_vals': vals})
        filas.append(fila)
    df = pd.DataFrame(filas).sort_values('_share', ascending=False, kind='stable').reset_index(drop=True)
    info = dict(meses=meses, m_cierre=m_cierre, m_prev=m_prev, m_raw=m_raw)
    return df, x, info


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
    try:
        vl = sh.worksheet(D.H_LIQ).get_all_values(value_render_option='UNFORMATTED_VALUE')
        liq = pd.DataFrame(vl[1:], columns=vl[0])
    except Exception:
        liq = None
    return sh, base, gab, liq


def _r(f, *a, **k):
    """Reintenta ante cuota de escrituras de Sheets (429)."""
    import time
    from gspread.exceptions import APIError
    for i in range(6):
        try:
            return f(*a, **k)
        except APIError as e:
            if '429' in str(e) and i < 5:
                print(f'   [sheets] 429, espero {30 * (i + 1)} s', flush=True)
                time.sleep(30 * (i + 1))
                continue
            raise


def _col(i):
    """Índice 1-based → letra de columna (A..Z, AA..)."""
    out = ''
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def leer_historial(sh):
    import gspread
    try:
        v = _r(sh.worksheet(H_HIST).get_all_values)
        return pd.DataFrame(v[1:], columns=v[0]) if len(v) > 1 else pd.DataFrame(columns=COLS_HIST)
    except gspread.WorksheetNotFound:
        return pd.DataFrame(columns=COLS_HIST)


def guardar_historial(sh, filas):
    """Agrega al historial la gestión de un mes que se cerró (no reescribe lo anterior)."""
    import gspread
    try:
        ws = sh.worksheet(H_HIST)
        if not _r(ws.get_all_values):
            _r(ws.update, values=[COLS_HIST], range_name='A1')
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=H_HIST, rows=400, cols=len(COLS_HIST))
        _r(ws.update, values=[COLS_HIST], range_name='A1')
        _r(ws.format, f'A1:{_col(len(COLS_HIST))}1', {'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                                                     'backgroundColor': {'red': .118, 'green': .227, 'blue': .373}})
        _r(ws.freeze, rows=1)
    _r(ws.append_rows, filas, value_input_option='RAW')


def armar(df, info, prev, hist):
    """Arma la pestaña (sin escribir): columnas, gestión conservada por ID y, si cerró un mes nuevo, las filas que
    pasan al historial. prev = valores actuales de la pestaña; hist = historial (DataFrame)."""
    m_cierre, m_prev = info['m_cierre'], info['m_prev']
    cols_mes = [col_mes(m) for m in info['meses']]
    cp, cc = col_gestion_prev(m_prev), col_gestion_cur(m_cierre)
    cols = COLS_IZQ + cols_mes + COLS_DER + COLS_GESTION + [cp, cc]
    df = df.copy()
    p = pd.DataFrame(prev[1:], columns=prev[0]) if prev and len(prev) > 1 and 'ID' in prev[0] else pd.DataFrame(columns=['ID'])
    p = p[p['ID'].astype(str).str.strip().str.fullmatch(r'[A-Z]{2,4}-\d+')].set_index('ID')
    # responsable, fecha y estado: de las personas, se conservan por ID
    for c in COLS_GESTION:
        if c in p.columns:
            keep = p[c].reindex(df['ID']).fillna('').astype(str).str.strip().values
            df[c] = [k if k else d for k, d in zip(keep, df[c])]
    # gestión: la columna editable es del mes de su encabezado; cuando cierra un mes nuevo se guarda en el historial
    rol = columnas(p.columns)
    col_ed = rol['gestion_cur']
    per_ed = (M_BASE if col_ed == GESTION_LEGACY else mes_de_col(col_ed)) if col_ed else None
    textos = p[col_ed].reindex(df['ID']).fillna('').astype(str).str.strip() if col_ed else pd.Series('', index=df['ID'])
    nuevas = []
    if per_ed and m_cierre and per_ed < m_cierre:
        if not (hist['Mes de cierre'].astype(str) == per_ed).any():
            hoy = dt.date.today().isoformat()
            nuevas = [[per_ed, r['ID'], r['Canal'], r['Acción'], r['Indicador'], _fmt(r['_vals'].get(per_ed), r['Unidad']),
                       textos.get(r['ID'], ''), r['Responsable'], r['Estado'], hoy] for _, r in df.iterrows()]
            hist = pd.concat([hist, pd.DataFrame(nuevas, columns=COLS_HIST)], ignore_index=True)
        actual = {}                                       # mes nuevo: la columna editable parte vacía
    else:
        actual = textos.to_dict()
    h = hist[hist['Mes de cierre'].astype(str) == m_prev]
    comp = dict(zip(h['ID'], h['Gestión'])) if len(h) else {}
    df[cp] = [comp.get(i, '') for i in df['ID']]
    df[cc] = [actual.get(i, '') for i in df['ID']]
    out = df.copy()
    for c in ['Meta propuesta', 'Resultado del mes'] + cols_mes:
        out[c] = [(_fmt(v, u) if v is not None and not pd.isna(v) else '') for v, u in zip(out[c], out['Unidad'])]
    out['Resultado del mes'] = [(f'{t} ({lab(m_cierre)[:3].lower()} vs {lab(m_prev)[:3].lower()})' if t else '') for t in out['Resultado del mes']]
    out = out[cols]
    return cols, out, nuevas, cp, cc


def escribir(sh, df, info):
    import gspread
    try:
        ws = sh.worksheet(H_PLAN)
        prev = _r(ws.get_all_values)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=H_PLAN, rows=80, cols=len(COLS_IZQ) + N_MESES + 10)
        prev = []
    cols, out, nuevas, cp, cc = armar(df, info, prev, leer_historial(sh))
    if nuevas:
        guardar_historial(sh, nuevas)
        print(f'[{H_HIST}] gestión de {lab(nuevas[0][0])} guardada ({sum(1 for f in nuevas if f[6])} con texto)')
    m_cierre, m_prev = info['m_cierre'], info['m_prev']
    cols_mes = [col_mes(m) for m in info['meses']]
    nota = [f'Una columna por mes cerrado ({lab(M_BASE)} es la base del plan). "Resultado del mes" y "Semáforo" comparan {lab(m_cierre)} '
            f'contra {lab(m_prev)}: es el resultado de lo comprometido en "{cp}". Responsable, fecha, estado y "{cc}" son de '
            f'gestión (amarillo) y se conservan; al cerrar el próximo mes, lo escrito pasa al historial ({H_HIST}). Orden = prioridad '
            'por share de venta. Semáforo: verde = se mueve hacia la meta (o ya está), rojo = en contra, amarillo = plano.']
    datos = [cols] + out.astype(object).where(pd.notna(out), '').values.tolist()
    n = len(datos)
    ult = _col(len(cols))
    # Primero se escribe y recién después se limpia lo que sobra: si Sheets corta a mitad
    # (cuota de escrituras, 429), la pestaña nunca queda vacía (incidente 2-oct-2026).
    _r(ws.update, values=datos + [[''] * len(cols), nota + [''] * (len(cols) - 1)], range_name='A1', value_input_option='RAW')
    if ws.row_count > n + 2:
        _r(ws.batch_clear, [f'A{n + 3}:{_col(max(ws.col_count, len(cols)))}{ws.row_count}'])
    if ws.col_count > len(cols):
        _r(ws.batch_clear, [f'{_col(len(cols) + 1)}1:{_col(ws.col_count)}{n + 2}'])
    _r(ws.freeze, rows=1)
    i_ges = len(COLS_IZQ) + len(cols_mes) + len(COLS_DER) + 1          # primera columna de gestión (1-based)
    _r(ws.batch_format, [
        {'range': f'A1:{ult}1', 'format': {'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                                           'backgroundColor': {'red': .118, 'green': .227, 'blue': .373}, 'wrapStrategy': 'WRAP'}},
        {'range': f'A2:{ult}{n}', 'format': {'backgroundColor': {'red': 1, 'green': 1, 'blue': 1}, 'wrapStrategy': 'WRAP'}},
        {'range': f'{_col(i_ges)}2:{_col(i_ges + 2)}{n}', 'format': {'backgroundColor': {'red': 1, 'green': .973, 'blue': .863}}},   # editable
        {'range': f'{_col(i_ges + 3)}2:{_col(i_ges + 3)}{n}', 'format': {'backgroundColor': {'red': .933, 'green': .949, 'blue': .969}}},  # fija
        {'range': f'{_col(i_ges + 4)}2:{_col(i_ges + 4)}{n}', 'format': {'backgroundColor': {'red': 1, 'green': .973, 'blue': .863}}},   # editable
    ])
    ancho = {'ID': 7, 'Canal': 14, 'Prioridad (share de venta)': 14, 'Acción': 32, 'Indicador': 34, 'Unidad': 6,
             'Meta propuesta': 11, 'Mes en curso (solo RAW)': 14, 'Resultado del mes': 16, 'Semáforo': 13, 'Responsable': 20,
             'Fecha compromiso': 11, 'Estado': 10, cp: 36, cc: 36}
    anchos = [{'updateDimensionProperties': {'range': {'sheetId': ws.id, 'dimension': 'COLUMNS', 'startIndex': i, 'endIndex': i + 1},
                                             'properties': {'pixelSize': ancho.get(c, 11) * 8}, 'fields': 'pixelSize'}}
              for i, c in enumerate(cols)]
    _r(sh.batch_update, {'requests': anchos})     # una sola escritura
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    sh, base, gab, liq = leer_sheet()
    df, x, info = calcular(base, gab, liq)
    pd.set_option('display.width', 250)
    cols_mes = [col_mes(m) for m in info['meses']]
    show = df[['ID', 'Canal', 'Indicador', 'Unidad'] + cols_mes + ['Resultado del mes', 'Semáforo']].copy()
    for c in cols_mes + ['Resultado del mes']:
        show[c] = [_fmt(v, u) for v, u in zip(show[c], show['Unidad'])]
    print(show.drop(columns=['Unidad']).to_string(index=False))
    print(f"\nMeses: {', '.join(lab(m) for m in info['meses'])} · resultado {lab(info['m_cierre'])} vs {lab(info['m_prev'])} · "
          f"en curso {lab(info['m_raw']) if info['m_raw'] else '—'}")
    if a.dry_run:
        return
    escribir(sh, df, info)
    print(f'[{H_PLAN}] {len(df)} indicadores escritos · {sh.url}')


if __name__ == '__main__':
    main()
