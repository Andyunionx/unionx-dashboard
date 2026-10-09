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
import io
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
RECETA = ROOT / 'data' / 'rentabilidad' / 'receta_glosas.csv'
IVA = 1.19
COLS = ['canal', 'cuenta', 'archivo', 'pedido', 'sku', 'glosa', 'monto_archivo', 'base_iva', 'monto_neto', 'modalidad_liq']


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
        'sku': f['SKU vendedor'].astype(str).str.strip().replace({'nan': ''}),
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
                            'sku': '', 'envio': d['Número de envío'].astype(str).str.replace(r'\.0$', '', regex=True),
                            'glosa': d['Detalle'].astype(str).str.strip(),
                            'monto_archivo': pd.to_numeric(d[vcol], errors='coerce').fillna(0),
                            'base_iva': 'con_iva', 'modalidad_liq': 'Envío directo'})
    else:                                           # facturación y NC de ML
        d = _ml_tabla(path)
        d = d[d['Detalle'].notna()]
        out = pd.DataFrame({'canal': 'Mercado Libre', 'cuenta': cuenta, 'archivo': path.name,
                            'pedido': d['Número de venta'].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', ''),
                            'sku': '', 'envio': d['Número de envío'].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', ''),
                            'glosa': d['Detalle'].astype(str).str.strip(),
                            'monto_archivo': pd.to_numeric(d['Valor del cargo'], errors='coerce').fillna(0),
                            'base_iva': 'con_iva', 'modalidad_liq': ''})
    out['monto_neto'] = out['monto_archivo'] / IVA      # cargos positivos, anulaciones negativas
    return out[COLS + ['envio']]


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
    pedido = p['nro suborden'].astype(str).str.replace(r'\.0$', '', regex=True)   # el RAW guarda la suborden
    d = pd.DataFrame({'canal': 'Paris', 'cuenta': cuenta, 'archivo': path.name, 'pedido': pedido,
                      'sku': '', 'glosa': glosa, 'monto_archivo': val, 'base_iva': 'con_iva',
                      'modalidad_liq': 'Fulfillment' if ff else ''})
    # Descuento Comercial (Gabriela 8-oct): columna de la liquidación de Colecta, al lado de cada Venta y Devolución;
    # rebaja la comisión, por eso entra con signo negativo. En FF no entra.
    if not ff and 'Descuento Comercial' in p.columns:
        dc = pd.to_numeric(p['Descuento Comercial'], errors='coerce').fillna(0)
        m = dc != 0
        d = pd.concat([d, pd.DataFrame({'canal': 'Paris', 'cuenta': cuenta, 'archivo': path.name, 'pedido': pedido[m],
                                        'sku': '', 'glosa': 'Descuento Comercial', 'monto_archivo': -dc[m],
                                        'base_iva': 'con_iva', 'modalidad_liq': ''})], ignore_index=True)
    # Gabriela divide por 1,19 y redondea FILA A FILA (así cuadra al peso con su carga de agosto y septiembre)
    d['monto_neto'] = (d['monto_archivo'] / IVA).round()
    return d[COLS]


# ─────────────────────────── Ripley (Mirakl, formato ancho) ───────────────────────────
RIPLEY_GLOSA = {
    'Comisiones sobre pedidos': 'Comision Ventas MKP',
    'Comisiones sobre pedidos reembolsados': 'Comision Ventas MKP',
    'Descuento por costo logístico': 'MKP Cobro logístico parcial del despacho primera milla',
    'Descuento por logistica inversa': 'MKP Cobro despacho logistica inversa',
    'Descuento por cancelación': 'MKP Penalidad - Cancelacion',
    'Descuento por PDM': 'MKP Acuerdo comercial - Espacios Always OnProduct',
    # Gabriela 8-oct: columna Z = costo fijo, AJ = última milla, H + L = despacho que cobra Ripley por pedido
    'Otros descuentos': 'MKP COMISIÓN COSTO FIJO MKP',
    'Descuento por cupones de despacho': 'MKP Logística última milla',
    'Gastos de envío pagados por el operador': 'Despacho de productos MKP Ventas',
    'Gastos de envío reembolsados pagados por el operador': 'Despacho de productos MKP Ventas',
    'Cobro despacho primera milla': 'MKP Cobro logístico parcial del despacho primera milla',
}
# Envío (G) y Envío reembolsado (K) son lo que paga el cliente: Ripley lo abona y lo descuenta en H, por eso no
# entran. El Abono postventa no entra porque no tiene facturación asociada (Gabriela 8-oct).
RIPLEY_NO_COSTO = {'Fecha OC', 'Número documento liquidación', 'Orden de compra', 'Shop ID', 'Tienda',
                   'Importe del pedido', 'Envío', 'Pedidos reembolsados', 'Envío reembolsado', 'A pagar',
                   'Abono postventa', 'Abonos por cupón promocional'}   # sin facturación asociada (Gabriela 8-oct)


def ripley(path: Path, cuenta='Ripley') -> pd.DataFrame:
    r = pd.read_excel(path)
    val_cols = [c for c in r.columns if c not in RIPLEY_NO_COSTO and pd.api.types.is_numeric_dtype(r[c])]
    m = r.melt(id_vars=['Orden de compra'], value_vars=val_cols, var_name='concepto', value_name='v')
    m = m[pd.to_numeric(m['v'], errors='coerce').fillna(0) != 0]
    d = pd.DataFrame({'canal': 'Ripley', 'cuenta': cuenta, 'archivo': path.name,
                      'pedido': m['Orden de compra'].astype(str),
                      'sku': '', 'glosa': m['concepto'].map(RIPLEY_GLOSA).fillna(m['concepto']),
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
                      'sku': (w[col['SKU']].astype(str).str.strip().replace({'nan': ''}) if 'SKU' in col else ''),
                      'glosa': glosa, 'monto_archivo': val, 'base_iva': 'con_iva',
                      'modalidad_liq': fb.map(lambda s: 'Fulfillment' if 'WFS' in s or 'WALMART' in s else '')})
    d['monto_neto'] = d['monto_archivo'] / IVA
    return d[COLS]


# ─────────────────────────── Kitchen Center / Banco Bice ───────────────────────────
def kitchen_center(path: Path) -> pd.DataFrame:
    """Reporte Melollevo de Kitchen Center: una fila por pedido (Venta / Devolución / Reenvío / Cancelación).
    "Monto Facturado" es lo que KC nos cobra (comisión 20% del bruto, con IVA)."""
    x = pd.read_excel(path)
    x = x[pd.to_numeric(x['Monto Facturado'], errors='coerce').fillna(0) != 0]
    d = pd.DataFrame({'canal': 'Kitchen Center', 'cuenta': 'Kitchen Center', 'archivo': path.name,
                      'pedido': x['ID Pedido Shopify'].astype(str).str.replace('#', '', regex=False).str.strip(),
                      'sku': '', 'glosa': 'Comisión KC',
                      'monto_archivo': pd.to_numeric(x['Monto Facturado'], errors='coerce').fillna(0),
                      'base_iva': 'con IVA', 'modalidad_liq': ''})
    d['monto_neto'] = d['monto_archivo'] / IVA
    return d[COLS]


def bice(path: Path) -> pd.DataFrame:
    """Liquidación de Banco Bice: pestaña "Analisis Facturación Pedidos", comisión por pedido con IVA
    (la suma cuadra con "Comisión con iva" del Resumen)."""
    x = pd.read_excel(path, sheet_name='Analisis Facturación Pedidos')
    x = x[x['ID Pedido'].notna()]
    d = pd.DataFrame({'canal': 'Banco Bice', 'cuenta': 'Banco Bice', 'archivo': path.name,
                      'pedido': x['ID Pedido'].astype(str).str.strip(), 'sku': '', 'glosa': 'Comisión Bice',
                      'monto_archivo': pd.to_numeric(x['Comision Del Pedido'], errors='coerce').fillna(0),
                      'base_iva': 'con IVA', 'modalidad_liq': ''})
    d['monto_neto'] = d['monto_archivo'] / IVA
    return d[COLS]


# ─────────────────────────── couriers (Recíbelo / BlueX) ───────────────────────────
_MAPA_RAW = {}


def _mapa_raw():
    """Pedido de Odoo → canal y Marketplace Reference de CMR, desde el RAW (para las referencias S y #)."""
    if not _MAPA_RAW:
        cols = ['pedido', 'pedido_marketplace', 'canal']
        partes = [pd.read_parquet(p, columns=cols) for p in (ROOT / 'data/historico/ventas_historico.parquet',
                                                               ROOT / 'data/historico/ventas_mes_actual.parquet') if p.exists()]
        r = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=cols)
        _MAPA_RAW['canal'] = dict(zip(r['pedido'].astype(str).str.strip().str.upper(), r['canal']))
        _MAPA_RAW['cmr'] = set(r.loc[r['canal'] == 'CMR', 'pedido_marketplace'].astype(str).str.strip())
    return _MAPA_RAW


CANAL_WEB_RECIBELO = {'Simplit web': 'Simplit Home', 'Lhotse web': 'Lhotse', 'UnionX web': 'UnionX Web',
                      'LATAM Pass': 'LATAM PASS', 'CMR': 'CMR'}


def canal_recibelo(id_interna, tags, id_imported) -> str:
    """Receta de Gabriela (29-09, con el cruce al RAW de las referencias S del 5-10). Validada contra su
    costeo de agosto: 98,7% de los envíos (las diferencias son S de pedidos web que ella dejaba en B2B)."""
    m = _mapa_raw()
    i = re.sub(r'^MEL', '', str(id_interna or '').strip().upper()).replace(' ', '')
    i = re.sub(r'-M?\d+$', '', i)                     # reenvío "-1" y bulto de multi-bulto "-M1"
    t = str(tags or '').replace('\xa0', ' ').lower()
    imp = str(id_imported or '').strip().upper()
    if 'falabella' in t:
        return 'Falabella'
    if 'ripley' in t or imp.endswith('-A'):
        return 'Ripley'
    for pre, canal in (('SH', 'Simplit Home'), ('LH', 'Lhotse'), ('MKT', 'Marketing'), ('PV', 'Postventa'), ('ITAU', 'Celmedia')):
        if i.startswith(pre):
            return canal
    if i.startswith('#'):
        return 'CMR' if i in m['cmr'] else 'UnionX Web'
    if re.fullmatch(r'S\d+', i):
        return CANAL_WEB_RECIBELO.get(m['canal'].get(i, ''), 'UnionX B2B')
    if 'PKG' in imp or 'PKG' in i or re.fullmatch(r'\d{9}', i):
        return 'Falabella'
    if re.fullmatch(r'\d{11}', i) or re.fullmatch(r'2000\d{12,15}', i):
        return 'Mercado Libre'
    return 'Desconocido'


def recibelo_crudo(path: Path) -> pd.DataFrame:
    """Archivo crudo de Recíbelo ("UnionX {MES}.xlsx", pestaña Detalle): costo = TARIFA + TARIFA BIG TICKET
    (neto; cuadra con el NETO de la pestaña Resumen) y canal con canal_recibelo()."""
    x = pd.read_excel(path, sheet_name='Detalle')
    costo = pd.to_numeric(x['TARIFA'], errors='coerce').fillna(0) + pd.to_numeric(x.get('TARIFA BIG TICKET', 0), errors='coerce').fillna(0)
    d = pd.DataFrame({'canal': [canal_recibelo(a, b, c) for a, b, c in zip(x['ID interna'], x['Tags'], x['ID imported'])],
                      'cuenta': 'Recíbelo', 'archivo': path.name,
                      'pedido': x['ID interna'].astype(str).str.strip(), 'sku': '', 'glosa': 'Recibelo',
                      'monto_archivo': costo, 'base_iva': 'neto', 'modalidad_liq': 'Envío directo'})
    d['monto_neto'] = d['monto_archivo']
    return d[COLS]


def recibelo(path: Path) -> pd.DataFrame:
    x = pd.read_excel(path, sheet_name='Detalle')
    canal = x['Cliente/Canal'].astype(str).str.strip()
    d = pd.DataFrame({'canal': canal, 'cuenta': 'Recíbelo', 'archivo': path.name,
                      'pedido': [str(b).split('-PKG')[0] if str(b) not in ('0', 'nan', '') else str(a).split('-M')[0]
                                 for a, b in zip(x['ID interna'], x['ID imported'])],
                      'sku': '', 'glosa': 'Recibelo',
                      'monto_archivo': pd.to_numeric(x['Costo Total'], errors='coerce').fillna(0),
                      'base_iva': 'neto', 'modalidad_liq': 'Envío directo'})
    d['monto_neto'] = d['monto_archivo']
    return d[COLS]


def bluex(path: Path) -> pd.DataFrame:
    """Resumen Blue Express de Gabriela. Desde sep-26 (correo 5-oct): la columna NETO es el monto por OS y
    SUMA_EN_RESUMEN marca las filas que suman (las piezas de envíos multi-OS repiten el monto de su cabecera);
    la pestaña "NC <n°>" trae la rebaja por OS aceptada, con el canal del mes original, y se aplica en el mes
    en que llega."""
    xl = pd.ExcelFile(path)
    x = pd.read_excel(xl, sheet_name='Detalle')
    if 'SUMA_EN_RESUMEN' in x.columns:
        x = x[x['SUMA_EN_RESUMEN'].astype(str).str.strip().str.lower().str.startswith('s')]
    neto = 'NETO' if 'NETO' in x.columns else [c for c in x.columns if str(c).startswith('NETO')][0]

    def filas(canal, ref, monto):
        d = pd.DataFrame({'canal': canal.astype(str).str.strip(), 'cuenta': 'BlueX', 'archivo': path.name,
                          'pedido': ref.astype(str).str.split(r'[,;]').str[0].str.strip()
                                     .str.replace(r'^(MEL|GRS)', '', regex=True).str.replace(r'^[A-Za-z]+-(\d+)$', r'\1', regex=True),
                          'sku': '', 'glosa': 'Bluexpress',
                          'monto_archivo': pd.to_numeric(monto, errors='coerce').fillna(0),
                          'base_iva': 'neto', 'modalidad_liq': ''})
        d['monto_neto'] = d['monto_archivo']
        return d[COLS]

    partes = [filas(x['CANAL'], x['REFERENCIA'], x[neto])]
    for hoja in [h for h in xl.sheet_names if h.strip().upper().startswith('NC')]:
        n = pd.read_excel(xl, sheet_name=hoja)
        c_canal = next((c for c in n.columns if str(c).strip().upper().startswith('CANAL')), None)
        c_nc = next((c for c in n.columns if str(c).strip().upper().startswith('NC')), None)
        if c_canal is None or c_nc is None:
            continue
        n = n[n[c_canal].notna() & n[c_canal].astype(str).str.strip().ne('')]   # sin la fila de total
        ref = n['REFERENCIA'] if 'REFERENCIA' in n.columns else n[c_canal]
        partes.append(filas(n[c_canal], ref, n[c_nc]))
    return pd.concat(partes, ignore_index=True)


def enviame(path: Path) -> pd.DataFrame:
    """Factura de Envíame, courier de Mercado Libre (carpeta MELI/ENVIAME/<MES>, Gabriela 7-oct). Pestaña Detalle,
    una fila por envío; 'total' = precio + seguro, neto (suma el Subtotal de la pestaña Resumen). La última fila es
    el total y no trae id."""
    x = pd.read_excel(path, sheet_name='Detalle')
    x = x[x['id'].notna()]
    monto = pd.to_numeric(x['total'] if 'total' in x.columns else x['precio'], errors='coerce').fillna(0)
    d = pd.DataFrame({'canal': 'Mercado Libre', 'cuenta': 'Envíame', 'archivo': path.name,
                      'pedido': x['imported_id'].map(lambda v: str(int(v)) if pd.notna(v) else ''),
                      'sku': '', 'glosa': 'Enviame', 'monto_archivo': monto, 'base_iva': 'neto', 'modalidad_liq': ''})
    d['monto_neto'] = d['monto_archivo']
    return d[COLS]


RIPLEY_FF = {'almacenamiento diario': 'FBR COBRO ALMACENAMIENTO DIARIO',
             'cofinanciamiento logistico': 'FBR COFINANCIAMIENTO LOGISTICO',
             'commission_fee': 'Comisión Ventas FF'}


def ripley_ff(path: Path) -> pd.DataFrame:
    """CSV de Fulfillment de Ripley (abonos_descuentos_<folio>_ff_2143.csv, Gabriela 8-oct): columna S "Descuento por
    almacenamiento diario (FF)" y V "Descuento por cofinanciamiento logístico (FF)" → Comisión envío; K commission_fee
    → Comisión venta. Vienen en positivo (= lo que se descuenta) y con IVA; se suman TODAS las filas, también las sin
    pedido (los cobros de bodega vienen sueltos)."""
    raw = path.read_bytes()
    x = None
    for enc in ('utf-8-sig', 'latin-1'):
        for sep in (';', ','):
            try:
                c = pd.read_csv(io.BytesIO(raw), sep=sep, encoding=enc)
            except Exception:
                continue
            if c.shape[1] > 5:
                x = c
                break
        if x is not None:
            break
    if x is None:
        raise ValueError('CSV de Fulfillment de Ripley sin columnas reconocibles')
    col_ped = next((c for c in x.columns if _norm(c) in ('order_id', 'orden de compra', 'pedido')), None)
    pedido = x[col_ped].astype(str) if col_ped else pd.Series('', index=x.index)
    partes = []
    for clave, glosa in RIPLEY_FF.items():
        col = next((c for c in x.columns if clave in _norm(c)), None)
        if col is None:
            continue
        v = pd.to_numeric(x[col].astype(str).str.replace(',', '.', regex=False), errors='coerce').fillna(0)
        m = v != 0
        partes.append(pd.DataFrame({'canal': 'Ripley', 'cuenta': 'Ripley FF', 'archivo': path.name, 'pedido': pedido[m],
                                    'sku': '', 'glosa': glosa, 'monto_archivo': v[m], 'base_iva': 'con_iva',
                                    'modalidad_liq': 'Fulfillment'}))
    d = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLS)
    d['monto_neto'] = d['monto_archivo'] / IVA
    return d[COLS]


def hites(path: Path) -> pd.DataFrame:
    """Liquidación de Hites (carpeta HITES/<MES>, tres archivos por mes con corte el 20; Gabriela 8-oct): columna
    COMISIÓN → comisión de venta y SHIPPING → comisión de envío, con IVA. TOTAL, PAGO y ESTADO no entran."""
    x = pd.read_excel(path)
    x = x[x['ORDEN DE COMPRA'].notna()]
    partes = [pd.DataFrame({'canal': 'Hites', 'cuenta': 'Hites', 'archivo': path.name,
                            'pedido': x['ORDEN DE COMPRA'].astype(str).str.replace(r'\.0$', '', regex=True), 'sku': '',
                            'glosa': glosa, 'monto_archivo': pd.to_numeric(x[col], errors='coerce').fillna(0),
                            'base_iva': 'con_iva', 'modalidad_liq': 'Colecta'})
              for col, glosa in (('COMISIÓN', 'Comisión Marketplace seller Comercial Innovatek Spa'),
                                 ('SHIPPING', 'Despacho Marketplace seller Comercial Innovatek Spa'))]
    d = pd.concat(partes, ignore_index=True)
    d['monto_neto'] = d['monto_archivo'] / IVA
    return d[COLS]


CANAL_COURIER = {'mercado libre': 'Mercado Libre', 'meli': 'Mercado Libre', 'falabella': 'Falabella', 'ripley': 'Ripley',
                 'paris': 'Paris', 'walmart': 'Walmart'}


def leer_carpeta(base: Path) -> pd.DataFrame:
    partes = []
    # Recíbelo: si en la carpeta del mes está el costeo de Gabriela se usa ese; el crudo solo cuando no hay costeo.
    con_costeo = {f.parent for f in base.rglob('*.xlsx') if 'RECIBELO' in str(f).upper() and 'COSTEO' in f.name.upper()}
    for f in sorted(base.rglob('*.csv')):            # CSV de Fulfillment de Ripley (abonos y descuentos)
        p = str(f.relative_to(base)).upper().replace('\\', '/')
        if p.startswith('RIPLEY') and 'ABONOS' in f.name.upper():
            try:
                partes.append(ripley_ff(f))
            except Exception as e:
                print(f'   [WARN] {p}: {type(e).__name__}: {e}')
    for f in sorted(base.rglob('*.xlsx')):
        p = str(f.relative_to(base)).upper().replace('\\', '/')
        try:
            if p.startswith('MELI') and '/ENVIAME/' in p:
                partes.append(enviame(f))
                continue
            if p.startswith('HITES'):
                partes.append(hites(f))
                continue
            if p.startswith('KITCHEN CENTER'):
                partes.append(kitchen_center(f))
                continue
            if p.startswith('BICE'):
                partes.append(bice(f))
                continue
            if ('RECIBELO' in p and f.name.upper().startswith('UNIONX') and 'COSTEO' not in f.name.upper()
                    and f.parent not in con_costeo and 'Detalle' in pd.ExcelFile(f).sheet_names):
                partes.append(recibelo_crudo(f))
                continue
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
