# -*- coding: utf-8 -*-
"""Macro de rentabilidad por canal — tabla larga para dinámica.

Estructura (definida con Andrés 08-09-2026):
    Año | Mes | Línea de negocio | Canal | Modalidad | Centro de costo | Glosa | Valor | Fuente

Una fila por combinación. Formato largo a propósito: aguanta canales y glosas
nuevas sin rehacer nada, y es lo que come una tabla dinámica.

QUÉ PRODUCE ESTE SCRIPT: solo lo que sale del RAW de ventas —Ingreso venta y
Costo venta—. Comisión venta, comisión envío y marketing los carga Gabriela en
la planilla espejo (`--plantilla`), con exactamente las mismas columnas, y el
consolidador apila las dos.

EL MARGEN NO SE CARGA COMO FILA. Es una resta de las otras; si se guarda como
dato, al filtrar la dinámica deja de cuadrar con lo filtrado. Va como campo
calculado en la dinámica.

MODALIDAD LOGÍSTICA — se resuelve por dos vías:
  1. Odoo, por pedido, donde el marketplace la declara (may-2026 en adelante,
     que es cuando el RAW empezó a guardar el nombre del pedido de Odoo en vez
     del id del marketplace).
  2. Regla por canal donde no aplica: El Volcán es consignación, Kitchen Center
     y el B2B son venta directa, etc.

Uso:
    python macro_rentabilidad_canal.py --desde 2026-05 --hasta 2026-08
    python macro_rentabilidad_canal.py --plantilla     # planilla vacía p/ Gabriela
"""
import argparse, json, os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import xmlrpc.client

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
OUT = Path(r'C:/Users/andre/AppData/Local/Temp/repo_adjuntos')
OUT.mkdir(parents=True, exist_ok=True)

COLS = ['Año', 'Mes', 'Línea de negocio', 'Canal', 'Modalidad',
        'Centro de costo', 'Glosa', 'Valor', 'Fuente']

# Centros de costo que carga Gabriela (el RAW no los tiene completos).
CC_GABRIELA = ['Comisión venta', 'Comisión envío', 'Marketing']

# Signo con que cada centro de costo entra al margen. Con esto el total de una
# dinámica ES el margen: no hace falta campo calculado, y al filtrar sigue
# cuadrando con lo filtrado.
SIGNO = {'Ingreso venta': 1, 'Otros ingresos': 1,
         'Devolución': 1,          # ya viene negativo desde el RAW
         'Costo venta': -1, 'Otros costos': -1,
         'Comisión venta': -1, 'Comisión envío': -1, 'Marketing': -1}

# Gabriela carga con el vocabulario nativo del marketplace, que es el que le
# llega en la liquidación. Se traduce acá para que ella no tenga que traducir
# nada. Lo que no tiene equivalente queda vacío = costo de canal, y se prorratea
# por venta entre las modalidades de ese canal.
MOD_GABRIELA = {'colecta': 'Colecta', 'fulfillment': 'Fulfillment',
                'flex': 'Envío directo', 'flex (flota propia)': 'Envío directo',
                'envío directo': 'Envío directo', 'envio directo': 'Envío directo',
                'venta directa': 'Venta directa', 'consignación': 'Consignación'}

# --- taxonomía de modalidad, unificada entre canales -----------------------
# El objetivo es comparar rentabilidad ENTRE canales, así que la modalidad tiene
# que significar lo mismo en todos. El nombre nativo de cada marketplace se
# traduce a este vocabulario común.
# CAMPO CANÓNICO: `fulfillment` existe en TODOS los canales y está poblado al
# 100%. Calza con los campos propios de cada marketplace (en Meli, fbc son los
# 13.442 de x_meli_logistic_type=fulfillment, y fbf los 7.456 de self_service:
# 2 pedidos de diferencia en 25.250). Los campos por canal solo afinan fbm.
MOD_BASE = {'fbc': 'Fulfillment',      # el marketplace almacena y despacha
            'fbf': 'Envío directo',    # Flex y equivalentes: despachamos nosotros
            'fbm': 'Colecta'}          # el marketplace retira de nuestra bodega
# Los puntos de entrega (xd_drop_off de Meli, "Retiro Tienda" de Ripley) se
# COLAPSAN en Colecta — decisión Andrés 08-09. Quedan 5 modalidades y la
# taxonomía es simétrica entre canales, que es lo que permite compararlos.
# Canales sin modalidad de marketplace: se asigna por naturaleza del canal.
MOD_FIJA = {'El Volcan': 'Consignación', 'El Volcán': 'Consignación',
            'Kitchen Center': 'Venta directa', 'Abc': 'Venta directa',
            'UnionX B2B': 'Venta directa', 'Casa Mila': 'Venta directa'}
# "By seller" = despachamos nosotros (decisión Andrés 08-09): las tiendas
# propias y los programas de fidelización no tienen modalidad de marketplace.
MOD_LN = {'Distribución': 'Venta directa', 'Corporativo': 'Venta directa',
          'Marketing': 'Venta directa',
          'Páginas Propias': 'Envío directo', 'Fidelización': 'Envío directo'}


def _odoo():
    cfg = json.load(open(ROOT / 'odoo/odoo_config.json'))['produccion']
    pw = os.environ.get('ANDRES_ODOO_PASSWORD', '') or (ROOT / 'odoo/.odoo_pass').read_text().strip()
    uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(
        cfg['db_name'], cfg['username'], pw, {})
    M = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object")

    def rpc(model, method, *a, **k):
        for i in range(4):
            try:
                return M.execute_kw(cfg['db_name'], uid, pw, model, method, list(a), k)
            except Exception:
                if i == 3:
                    raise
    return rpc


def modalidad_odoo(pedidos):
    """{pedido: modalidad} desde los campos que declara cada marketplace."""
    rpc = _odoo()
    out = {}
    campos = ['name', 'channel', 'fulfillment', 'x_meli_logistic_type',
              'x_fala_ship_type', 'x_fala_shipping_cost']
    for i in range(0, len(pedidos), 300):
        for s in rpc('sale.order', 'search_read', [['name', 'in', pedidos[i:i+300]]],
                     fields=campos):
            ch = str(s.get('channel') or '')
            m = MOD_BASE.get(str(s.get('fulfillment') or ''))
            if not m and 'Falabella' in ch:
                # respaldo por si Falabella no trae `fulfillment`: x_fala_ship_type
                # separa FBF del resto, y dentro del resto manda el signo del cobro
                # (abono = lo despachamos nosotros). Calibrado 04-09.
                st = str(s.get('x_fala_ship_type') or '')
                c = s.get('x_fala_shipping_cost') or 0
                m = ('Fulfillment' if st == 'Own Warehouse' else
                     ('Envío directo' if c > 0 else 'Colecta') if st == 'Dropshipping' else None)
            if m:
                out[s['name']] = m
    return out


def cargar_raw(desde, hasta):
    h = pd.read_parquet(ROOT / 'data/historico/ventas_historico.parquet')
    m = ROOT / 'data/historico/ventas_mes_actual.parquet'
    if m.exists():
        h = pd.concat([h, pd.read_parquet(m)], ignore_index=True)
    h['mes'] = h['fecha_venta'].astype(str).str[:7]
    v = h[(h['mes'] >= desde) & (h['mes'] <= hasta)].copy()
    # el RAW trae 'Páginas propias' y 'Páginas Propias': se normaliza
    v['ln'] = v['tipo_negocio'].astype(str).str.strip().str.title().replace({'': 'Sin clasificar'})
    v['canal'] = v['canal'].astype(str).str.strip()
    for c in ['venta_neta', 'costo_total', 'cantidad']:
        v[c] = pd.to_numeric(v[c], errors='coerce').fillna(0)
    return v


def construir(desde, hasta):
    v = cargar_raw(desde, hasta)
    print(f'[raw] {len(v):,} filas · {desde} a {hasta}', flush=True)

    peds = sorted({p for p in v['pedido'].astype(str) if p.startswith('S')})
    print(f'[odoo] resolviendo modalidad de {len(peds):,} pedidos...', flush=True)
    mod = modalidad_odoo(peds) if peds else {}
    print(f'[odoo] {len(mod):,} pedidos con modalidad declarada', flush=True)

    def resolver(r):
        m = mod.get(str(r['pedido']))
        if m:
            return m
        if r['canal'] in MOD_FIJA:
            return MOD_FIJA[r['canal']]
        if r['ln'] in MOD_LN:
            return MOD_LN[r['ln']]
        return 'Sin modalidad'

    v['Modalidad'] = v.apply(resolver, axis=1)
    v['Año'] = v['mes'].str[:4].astype(int)
    v['Mes'] = v['mes']

    dims = ['Año', 'Mes', 'ln', 'canal', 'Modalidad']
    filas = []
    # Cada centro de costo sale de un tipo_movimiento del RAW. La devolución va
    # aparte del ingreso a propósito: sumada al ingreso se esconde, y es justo
    # lo que queremos poder mirar mes a mes.
    for cc, col, mov in [('Ingreso venta', 'venta_neta', 'Venta'),
                         ('Costo venta', 'costo_total', 'Venta'),
                         ('Devolución', 'venta_neta', 'Devolución'),
                         ('Otros ingresos', 'venta_neta', 'Otros ingresos'),
                         ('Otros costos', 'costo_total', 'Otros costos')]:
        s = v[v['tipo_movimiento'].astype(str) == mov]
        if not len(s):
            continue
        g = s.groupby(dims, as_index=False)[col].sum()
        g = g[g[col] != 0]
        g['Centro de costo'] = cc
        g['Glosa'] = cc          # el RAW no tiene glosa: se usa el propio centro
        g['Valor'] = g[col]
        g['Fuente'] = 'RAW ventas'
        filas.append(g[dims + ['Centro de costo', 'Glosa', 'Valor', 'Fuente']])
    t = pd.concat(filas, ignore_index=True).rename(
        columns={'ln': 'Línea de negocio', 'canal': 'Canal'})[COLS]
    return t.sort_values(['Mes', 'Línea de negocio', 'Canal', 'Modalidad', 'Centro de costo']), v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--desde', default='2026-05')
    ap.add_argument('--hasta', default='2026-08')
    ap.add_argument('--plantilla', action='store_true',
                    help='genera además la planilla vacía para Gabriela')
    a = ap.parse_args()

    t, v = construir(a.desde, a.hasta)
    f = OUT / f'Macro rentabilidad canal - RAW {a.desde} a {a.hasta}.xlsx'
    with pd.ExcelWriter(f, engine='openpyxl') as w:
        t.to_excel(w, sheet_name='Datos RAW', index=False)
    print(f'\n[OK] {f} · {len(t):,} filas')

    print('\n=== COBERTURA DE MODALIDAD (venta neta) ===')
    q = v[v['tipo_movimiento'].astype(str).str.startswith('Venta')]
    p = q.pivot_table(index='Modalidad', columns='Mes', values='venta_neta', aggfunc='sum', fill_value=0)
    p['TOTAL'] = p.sum(axis=1)
    print(p.sort_values('TOTAL', ascending=False).to_string(float_format=lambda x: f'{x/1e6:,.1f}M'))

    if a.plantilla:
        base = t[['Año', 'Mes', 'Línea de negocio', 'Canal']].drop_duplicates()
        pl = base.merge(pd.DataFrame({'Centro de costo': CC_GABRIELA}), how='cross')
        pl['Modalidad'] = ''      # Gabriela puede dejarlo vacío = todo el canal
        pl['Glosa'] = ''
        pl['Valor'] = ''
        pl['Fuente'] = 'Gabriela'
        pl = pl[COLS]
        fp = OUT / f'Macro rentabilidad canal - PLANTILLA Gabriela {a.desde} a {a.hasta}.xlsx'
        with pd.ExcelWriter(fp, engine='openpyxl') as w:
            pl.to_excel(w, sheet_name='Cargar aquí', index=False)
        print(f'\n[OK] plantilla {fp} · {len(pl):,} filas a completar')


if __name__ == '__main__':
    main()
