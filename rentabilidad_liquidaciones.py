# -*- coding: utf-8 -*-
"""Lectura unificada de liquidaciones de marketplace (frente Rentabilidad).

Toma los archivos que Gabriela deja en la carpeta de Drive (un subdirectorio por
canal y mes) y los lleva a UNA tabla, una fila por línea de liquidación:

    canal · cuenta · archivo · pedido · glosa · monto_archivo · base_iva · monto_neto
    · modalidad_liq · centro_costo · estado_regla

Convención de signo = la de la carga de Gabriela: COSTO POSITIVO, abono negativo.
monto_neto está sin IVA (los archivos de ML, Paris, Ripley y Walmart traen el monto
con IVA — confirmado por Martín 25-09 contra las facturas; Falabella trae columna sin IVA).

La glosa se deja con el nombre que usa Gabriela en su carga, y el centro de costo sale
de data/rentabilidad/receta_glosas.csv (su receta, confirmada el 28-09). Glosa sin regla
→ estado_regla='sin regla' (cola de excepciones para ella).

Uso:
    python rentabilidad_liquidaciones.py <carpeta_mes> [--mes 2026-08] [--out archivo.parquet]
La carpeta tiene la estructura de Drive: FALABELLA/, MELI/(AGOSTO MELI 1|2)/, PARIS/(FF|SELLER)/,
RIPLEY/, WALMART/, Recibelo-Blue/.  Para la prueba de agosto se usan copias locales.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
RECETA = ROOT / 'data' / 'rentabilidad' / 'receta_glosas.csv'
IVA = 1.19
COLS = ['canal', 'cuenta', 'archivo', 'pedido', 'glosa', 'monto_archivo', 'base_iva', 'monto_neto', 'modalidad_liq']


def _norm(s):
    s = str(s or '').strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s)


def _df(rows):
    d = pd.DataFrame(rows, columns=COLS) if rows else pd.DataFrame(columns=COLS)
    return d


# ─────────────────────────── Falabella ───────────────────────────
def falabella(path: Path, cuenta='Falabella') -> pd.DataFrame:
    f = pd.read_excel(path)
    mod = f['Modalidad logistica'].map({'FBF': 'Fulfillment', 'FBS': ''}).fillna('')
    # FBS se separa entre Colecta y Envío directo (Flex) por el tipo de envío cuando viene
    flex = f.get('Tipo de envio', pd.Series('', index=f.index)).astype(str).str.lower().str.contains('direct|flex')
    mod = mod.where(~((f['Modalidad logistica'] == 'FBS') & flex), 'Envío directo')
    d = pd.DataFrame({
        'canal': 'Falabella', 'cuenta': cuenta, 'archivo': path.name,
        'pedido': f['N de orden'].astype('Int64').astype(str).replace('<NA>', ''),
        'glosa': f['Descripcion Factura'].astype(str).str.strip(),
        'monto_archivo': pd.to_numeric(f['Monto (Sin IVA)'], errors='coerce').fillna(0),
        'base_iva': 'neto', 'modalidad_liq': mod,
    })
    d['monto_neto'] = -d['monto_archivo']
    return d[COLS]


# ─────────────────────────── Mercado Libre ───────────────────────────
def _ml_tabla(path: Path, fila_header=7):
    raw = pd.read_excel(path, header=None)
    hdr = [str(x).strip() for x in raw.iloc[fila_header].tolist()]
    d = raw.iloc[fila_header + 1:].copy()
    d.columns = hdr
    return d.loc[:, ~pd.Index(hdr).duplicated()]


def mercadolibre(path: Path, cuenta: str) -> pd.DataFrame:
    n = path.name.lower()
    if 'envios' in n or 'enviosflex' in n:          # NC / ND de Envíos Flex (bonificación)
        d = pd.read_excel(path, header=7)
        vcol = [c for c in d.columns if str(c).startswith('Valor de la')][0]
        out = pd.DataFrame({'canal': 'Mercado Libre', 'cuenta': cuenta, 'archivo': path.name,
                            'pedido': d['Número de venta'].astype(str).str.replace(r'\.0$', '', regex=True),
                            'glosa': d['Detalle'].astype(str).str.strip(),
                            'monto_archivo': pd.to_numeric(d[vcol], errors='coerce').fillna(0),
                            'base_iva': 'con_iva', 'modalidad_liq': 'Envío directo'})
    else:                                           # facturación y NC de ML
        d = _ml_tabla(path)
        d = d[d['Detalle'].notna()]
        out = pd.DataFrame({'canal': 'Mercado Libre', 'cuenta': cuenta, 'archivo': path.name,
                            'pedido': d['Número de venta'].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', ''),
                            'glosa': d['Detalle'].astype(str).str.strip(),
                            'monto_archivo': pd.to_numeric(d['Valor del cargo'], errors='coerce').fillna(0),
                            'base_iva': 'con_iva', 'modalidad_liq': ''})
    out['monto_neto'] = out['monto_archivo'] / IVA      # cargos positivos, anulaciones negativas
    return out[COLS]


# ─────────────────────────── Paris ───────────────────────────
PARIS_GLOSA = {'Venta': 'Venta', 'Devolución': 'Devolución', 'Cobro por despacho': 'Cobro por despacho',
               'Logística inversa': 'Logística inversa', 'Compensación logística': 'Compensación logística',
               'Despacho': 'Despacho', 'Cargo': 'Cargo'}


def paris(path: Path, cuenta: str) -> pd.DataFrame:
    p = pd.read_excel(path)
    ff = 'FF' in cuenta
    tipo = p['tipo'].astype(str).str.strip()
    if 'Monto comisión' in p.columns:                     # Seller: comisión explícita
        com = pd.to_numeric(p['Monto comisión'], errors='coerce').fillna(0)
    else:                                                 # FF: comisión = monto − monto a pagar
        com = pd.to_numeric(p['monto'], errors='coerce').fillna(0) - pd.to_numeric(p['monto a pagar'], errors='coerce').fillna(0)
    monto = pd.to_numeric(p['monto'], errors='coerce').fillna(0)
    es_venta = tipo.isin(['Venta', 'Devolución'])
    # Venta/Devolución → el costo es la comisión. El resto de los tipos → el monto es el cargo
    # (negativo = nos cobran; Despacho viene positivo porque Paris lo abona y lo vuelve a cobrar).
    val = com.where(es_venta, -monto.where(tipo != 'Despacho', -monto))
    glosa = tipo.map(PARIS_GLOSA).fillna(tipo)
    if ff:
        glosa = glosa.replace({'Venta': 'Cargo venta'}) + ' (FF)'
    d = pd.DataFrame({'canal': 'Paris', 'cuenta': cuenta, 'archivo': path.name,
                      'pedido': p['número orden'].astype(str).str.replace(r'\.0$', '', regex=True),
                      'glosa': glosa, 'monto_archivo': val, 'base_iva': 'con_iva',
                      'modalidad_liq': 'Fulfillment' if ff else ''})
    d['monto_neto'] = d['monto_archivo'] / IVA
    return d[COLS]


# ─────────────────────────── Ripley (Mirakl, formato ancho) ───────────────────────────
RIPLEY_GLOSA = {
    'Comisiones sobre pedidos': 'Comision Ventas MKP',
    'Comisiones sobre pedidos reembolsados': 'Comision Ventas MKP',
    'Descuento por costo logístico': 'MKP Cobro logístico parcial del despacho primera milla',
    'Descuento por logistica inversa': 'MKP Cobro despacho logistica inversa',
    'Descuento por cancelación': 'MKP Penalidad - Cancelacion',
    'Descuento por PDM': 'MKP Acuerdo comercial - Espacios Always OnProduct',
    'Abono postventa': 'MKP Otros abonos',
    'Otros descuentos': 'MKP Otros descuentos',
    'Descuento por cupones de despacho': 'MKP Cupones de despacho',
    'Cobro despacho primera milla': 'MKP Cobro logístico parcial del despacho primera milla',
}
RIPLEY_NO_COSTO = {'Fecha OC', 'Número documento liquidación', 'Orden de compra', 'Shop ID', 'Tienda',
                   'Importe del pedido', 'Envío', 'Gastos de envío pagados por el operador', 'Pedidos reembolsados',
                   'Envío reembolsado', 'Gastos de envío reembolsados pagados por el operador', 'A pagar'}


def ripley(path: Path, cuenta='Ripley') -> pd.DataFrame:
    r = pd.read_excel(path)
    val_cols = [c for c in r.columns if c not in RIPLEY_NO_COSTO and pd.api.types.is_numeric_dtype(r[c])]
    m = r.melt(id_vars=['Orden de compra'], value_vars=val_cols, var_name='concepto', value_name='v')
    m = m[pd.to_numeric(m['v'], errors='coerce').fillna(0) != 0]
    d = pd.DataFrame({'canal': 'Ripley', 'cuenta': cuenta, 'archivo': path.name,
                      'pedido': m['Orden de compra'].astype(str),
                      'glosa': m['concepto'].map(RIPLEY_GLOSA).fillna(m['concepto']),
                      'monto_archivo': -pd.to_numeric(m['v'], errors='coerce'),   # descuento negativo = costo
                      'base_iva': 'con_iva', 'modalidad_liq': ''})
    d['monto_neto'] = d['monto_archivo'] / IVA
    return d[COLS]


# ─────────────────────────── Walmart ───────────────────────────
def walmart(path: Path, cuenta='Walmart') -> pd.DataFrame:
    with pd.ExcelFile(path) as x:
        w = pd.read_excel(x, sheet_name=x.sheet_names[0])
    col = {c.split(' /')[0].strip(): c for c in w.columns}
    concepto = w[col['Concept']].astype(str).str.strip()
    glosa = w[col['GLOSA']].astype(str).str.strip() if 'GLOSA' in col else concepto
    com = pd.to_numeric(w[col['Cargo por comision']], errors='coerce').fillna(0)
    afecto = pd.to_numeric(w[col['Afecto a Pago']], errors='coerce').fillna(0)
    noaf = pd.to_numeric(w[col['No Afecto a Pago']], errors='coerce').fillna(0)
    es_sku = concepto.eq('SKU')
    # 'Despacho cliente' (Servicio logístico / WFS) viene con signo mixto en "No afecto a
    # pago" y Gabriela lo carga siempre como costo → valor absoluto. El resto: negativo = cobro.
    desp_cli = concepto.eq('Despacho cliente')
    val = (-com).where(es_sku, (-(afecto + noaf)).where(~desp_cli, (afecto + noaf).abs()))
    fb = w[col['Fulfilled By']].astype(str).str.upper() if 'Fulfilled By' in col else pd.Series('', index=w.index)
    d = pd.DataFrame({'canal': 'Walmart', 'cuenta': cuenta, 'archivo': path.name,
                      'pedido': w[col['Orden']].astype(str).str.replace(r'\.0$', '', regex=True),
                      'glosa': glosa, 'monto_archivo': val, 'base_iva': 'con_iva',
                      'modalidad_liq': fb.map(lambda s: 'Fulfillment' if 'WFS' in s or 'WALMART' in s else '')})
    d['monto_neto'] = d['monto_archivo'] / IVA
    return d[COLS]


# ─────────────────────────── couriers (Recíbelo / BlueX) ───────────────────────────
def recibelo(path: Path) -> pd.DataFrame:
    x = pd.read_excel(path, sheet_name='Detalle')
    canal = x['Cliente/Canal'].astype(str).str.strip()
    d = pd.DataFrame({'canal': canal, 'cuenta': 'Recíbelo', 'archivo': path.name,
                      'pedido': x['ID interna'].astype(str), 'glosa': 'Recibelo',
                      'monto_archivo': pd.to_numeric(x['Costo Total'], errors='coerce').fillna(0),
                      'base_iva': 'neto', 'modalidad_liq': 'Envío directo'})
    d['monto_neto'] = d['monto_archivo']
    return d[COLS]


def bluex(path: Path) -> pd.DataFrame:
    x = pd.read_excel(path, sheet_name='Detalle')
    neto = [c for c in x.columns if str(c).startswith('NETO')][0]
    d = pd.DataFrame({'canal': x['CANAL'].astype(str).str.strip(), 'cuenta': 'BlueX', 'archivo': path.name,
                      'pedido': x['REFERENCIA'].astype(str), 'glosa': 'Bluexpress',
                      'monto_archivo': pd.to_numeric(x[neto], errors='coerce').fillna(0),
                      'base_iva': 'neto', 'modalidad_liq': ''})
    d['monto_neto'] = d['monto_archivo']
    return d[COLS]


CANAL_COURIER = {'mercado libre': 'Mercado Libre', 'meli': 'Mercado Libre', 'falabella': 'Falabella', 'ripley': 'Ripley',
                 'paris': 'Paris', 'walmart': 'Walmart'}


def leer_carpeta(base: Path) -> pd.DataFrame:
    partes = []
    for f in sorted(base.rglob('*.xlsx')):
        p = str(f.relative_to(base)).upper().replace('\\', '/')
        try:
            if p.startswith('FALABELLA'):
                partes.append(falabella(f))
            elif p.startswith('MELI'):
                partes.append(mercadolibre(f, 'ML 2' if 'MELI 2' in p else 'ML 1'))
            elif p.startswith('PARIS'):
                partes.append(paris(f, 'Paris FF' if '/FF/' in p else 'Paris Seller'))
            elif p.startswith('RIPLEY'):
                partes.append(ripley(f))
            elif p.startswith('WALMART'):
                partes.append(walmart(f))
            elif 'RECIBELO' in p and 'COSTEO' in f.name.upper():
                partes.append(recibelo(f))
            elif 'BLUE' in f.name.upper() and 'RESUMEN_' in f.name.upper():
                partes.append(bluex(f))
        except Exception as e:
            print(f'   [WARN] {p}: {type(e).__name__}: {e}')
    d = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLS)
    return clasificar(d)


def clasificar(d: pd.DataFrame) -> pd.DataFrame:
    r = pd.read_csv(RECETA)
    r['k'] = r['glosa_normalizada'].map(_norm)
    regla = {(c, k): (cc, o) for c, k, cc, o in zip(r['canal'], r['k'], r['centro_costo'], r['origen'])}
    por_glosa = {}
    for (c, k), v in regla.items():
        por_glosa.setdefault(k, v)
    d = d.copy()
    d['k'] = d['glosa'].map(_norm)
    cc, est = [], []
    for c, k in zip(d['canal'], d['k']):
        v = regla.get((c, k))
        if v is None:
            # glosas combinadas en la carga ("A / B") o con otra escritura: se busca por partes
            cand = [x for (cx, kx), x in regla.items() if cx == c and (k in kx or kx in k) and len(k) > 6]
            v = cand[0] if cand else None
        if v is None and k in ('recibelo', 'bluexpress', 'enviame'):
            v = ('Comisión envío', 'factura courier')
        cc.append(v[0] if v else '')
        est.append('ok' if v else 'sin regla')
    d['centro_costo'] = cc
    d['estado_regla'] = est
    return d.drop(columns=['k'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('carpeta')
    ap.add_argument('--out')
    a = ap.parse_args()
    d = leer_carpeta(Path(a.carpeta))
    print(d.groupby(['canal', 'cuenta'])['monto_neto'].agg(['count', 'sum']).round(0).to_string())
    print('sin regla:', int((d.estado_regla == 'sin regla').sum()), 'líneas ·',
          round(d.loc[d.estado_regla == 'sin regla', 'monto_neto'].abs().sum()))
    if a.out:
        d.to_parquet(a.out, index=False)
