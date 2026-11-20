# -*- coding: utf-8 -*-
"""Marca verificada por SKU para el RAW de ventas.

Regla de Andrés (20-nov-2026): «la marca siempre se verifica en Odoo o en la maestra de pricing». Orden:
  1) Odoo: product.template.brand_id («Marca (MultiVende)»). Si el SKU tiene fichas con marcas distintas, no cuenta.
  2) Maestra Pricing (Drive, hoja Pricing, columna Marca; la mantiene Felipe).
  3) Herencia: un pack toma la marca de los componentes de su BoM si es una sola (BoM de Odoo; si no tiene, hoja Packs
     de la Pricing). Un Open Box «OB-<sku>» toma la marca verificada del SKU original.
  4) Dinasty y corporativos (SKU DN, DIN, VIN, ER, DT, WB o categoría padre «Corporativo» en la Matriz) sin marca en
     Odoo ni en la Pricing: ITEK, que es lo que Odoo usa para ellos (Andrés 20-nov-2026).
  5) Matriz productos: solo respaldo histórico (SKU antiguos que ya no están en Odoo ni en la Pricing con marca).
  6) «SIN MARCA», visible en el RAW y en el log del extract.
La grafía se unifica con data/planillas/marcas_alias.csv (clave → nombre): ITEK = Itek = Innovate-K = Dinasty (Andrés
20-nov-2026: misma marca, propia). Una marca que no esté en el alias usa la grafía de la Pricing y, si no, la de Odoo.

Salida: data/planillas/marcas_sku.csv (sku_norm, marca, fuente). La aplica mejoras_raw_overlay.py (paso P1f).

Solo LEE Odoo y Drive. Uso:
  python marcas_sku.py                          Odoo con ANDRES_ODOO_PASSWORD; Pricing de Drive (DRIVE_OAUTH_TOKEN_JSON
                                                o drive_oauth_token.json)
  python marcas_sku.py --pricing-file X.xlsx    prueba local con una copia de la Pricing
  python marcas_sku.py --backfill               aplica la marca verificada al histórico (cambia solo marca y tipo_marca)
"""
from __future__ import annotations

import argparse
import io
import os
import re
import time
import unicodedata
import xmlrpc.client
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
PLANILLAS = ROOT / 'data' / 'planillas'
OUT_SKU = PLANILLAS / 'marcas_sku.csv'
ALIAS = PLANILLAS / 'marcas_alias.csv'
MATRIZ = PLANILLAS / 'Matriz productos.xlsx'
HIST = ROOT / 'data' / 'historico' / 'ventas_historico.parquet'

ODOO_URL = os.getenv('ODOO_URL', 'https://unionxb2b.odoo.com')
ODOO_DB = os.getenv('ODOO_DB', 'bmya-innovatek-sh-prd-6981800')
ODOO_USER = os.getenv('ANDRES_ODOO_USER', 'andres@grupoeter.cl')

SIN = 'SIN MARCA'
VACIOS = {'', 'nan', 'none', 'false', '0', '-', 'sin marca', 'null'}
# SKU que no son productos (despachos, retiros, descuentos, aportes, cupones): no llevan marca y el RAW los deja como
# vienen. Los servicios de Odoo también quedan fuera.
NO_PRODUCTO = re.compile(r'^(delivery|retiro|despacho|envio|flete|descuento|discount|apcom|aporte|cupon)|^disc$')
# Dinasty y corporativos (Vinoteca, ER, DT, DN, WB): van como ITEK si no tienen marca en Odoo ni en la Pricing.
CORPORATIVO = re.compile(r'^(dn|din|vin|er|dt|wb)')
MARCA_CORPORATIVO = 'ITEK'
MIN_PLANTILLAS = 5000   # una lectura de Odoo a medias no pisa el CSV bueno
MIN_PRICING = 500


# ─────────────────────────── normalización ───────────────────────────
def norm_sku(s) -> str:
    """Igual que mejoras_raw_overlay._norm (minúsculas, sin acentos) y además sin el «.0» de un número de Excel."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ''
    if isinstance(s, float) and s.is_integer():
        s = int(s)
    s = str(s).strip()
    if re.fullmatch(r'\d+\.0', s):
        s = s[:-2]
    s = s.lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def limpia(m) -> str:
    s = '' if m is None or (isinstance(m, float) and pd.isna(m)) else str(m).strip()
    return '' if s.lower() in VACIOS else s


def clave(m) -> str:
    s = ''.join(c for c in unicodedata.normalize('NFD', str(m or '').strip().lower()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[\s\-\._]', '', s)


class Grafia:
    """Nombre canónico de una marca: marcas_alias.csv > grafía de la Pricing > la que venga."""

    def __init__(self, pricing_marcas):
        self.alias = {}
        if ALIAS.exists():
            a = pd.read_csv(ALIAS, dtype=str, keep_default_na=False)
            self.alias = {clave(k): v.strip() for k, v in zip(a['clave'], a['marca']) if k and v}
        self.pricing = {}
        for m in pricing_marcas:
            if m:
                self.pricing.setdefault(clave(m), m)

    def __call__(self, m):
        m = limpia(m)
        if not m:
            return ''
        k = clave(m)
        return self.alias.get(k) or self.pricing.get(k) or m


# ─────────────────────────── fuentes ───────────────────────────
class OdooRO:
    """Cliente XML-RPC mínimo y de SOLO LECTURA (search_read paginado con reintentos)."""

    def __init__(self):
        pw = os.environ.get('ANDRES_ODOO_PASSWORD', '')
        if not pw:
            raise SystemExit('[ABORTA] falta ANDRES_ODOO_PASSWORD')
        self.pw = pw
        self.uid = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common').authenticate(ODOO_DB, ODOO_USER, pw, {})
        if not self.uid:
            raise SystemExit('[ABORTA] Odoo no autenticó')
        self.m = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object', allow_none=True)

    def leer(self, modelo, dominio, campos, pagina=2000):
        out, off = [], 0
        while True:
            for i in range(5):
                try:
                    p = self.m.execute_kw(ODOO_DB, self.uid, self.pw, modelo, 'search_read', [dominio],
                                          {'fields': campos, 'limit': pagina, 'offset': off, 'order': 'id asc'})
                    break
                except Exception:
                    if i == 4:
                        raise
                    time.sleep(5 * (i + 1))
            out += p
            if len(p) < pagina:
                return out
            off += pagina


def leer_odoo():
    o = OdooRO()
    act = [('active', 'in', [True, False])]
    t = o.leer('product.template', act, ['id', 'brand_id', 'type', 'active'])
    p = o.leer('product.product', act, ['id', 'default_code', 'product_tmpl_id', 'active'])
    b = o.leer('mrp.bom', act, ['id', 'product_tmpl_id', 'active'])
    bl = o.leer('mrp.bom.line', [], ['bom_id', 'product_id'])
    return t, p, b, bl


def bajar_pricing() -> bytes:
    from sync_categorias_pricing import bajar   # mismo acceso a Drive que las categorías
    return bajar()


def leer_pricing(xlsx: bytes):
    pr = pd.read_excel(io.BytesIO(xlsx), sheet_name='Pricing', header=1, dtype=object)
    pr['sk'] = pr['SKU'].map(norm_sku)
    pr['marca'] = pr['Marca'].map(limpia)
    pr = pr[pr.sk.ne('')].sort_values('marca', key=lambda s: s.eq('')).drop_duplicates('sk', keep='first')
    pk = pd.read_excel(io.BytesIO(xlsx), sheet_name='Packs', dtype=object)
    pk['p'] = pk['Pack'].map(norm_sku)
    pk['c'] = pk['SKU'].map(norm_sku)
    pk = pk[pk.p.ne('') & pk.c.ne('')]
    es_pack = pr['Pack'].astype(str).str.strip().str.lower().str.startswith('s')
    return dict(zip(pr.sk, pr.marca)), set(pr.sk[es_pack]), pk.groupby('p')['c'].apply(list).to_dict()


def leer_matriz():
    mx = pd.read_excel(MATRIZ, sheet_name='Productos', dtype=object)
    mx['sk'] = mx['SKU'].map(norm_sku)
    mx = mx[mx.sk.ne('')].drop_duplicates('sk', keep='first')
    es_pack = mx['Pack'].astype(str).str.strip().str.lower().str.startswith('s')
    padre = next((c for c in mx.columns if 'padre' in c.lower() and 'macro' not in c.lower()), None)
    corp = set(mx.sk[mx[padre].astype(str).str.strip().str.lower().eq('corporativo')]) if padre else set()
    return dict(zip(mx.sk, mx['Marca'].map(limpia))), set(mx.sk[es_pack]), corp


# ─────────────────────────── regla ───────────────────────────
def construir(odoo, pricing_xlsx: bytes) -> pd.DataFrame:
    t, p, b, bl = odoo
    if len(t) < MIN_PLANTILLAS:
        raise SystemExit(f'[ABORTA] Odoo devolvió solo {len(t)} plantillas')
    pr_marca, pr_pack, pk_comp = leer_pricing(pricing_xlsx)
    if sum(1 for v in pr_marca.values() if v) < MIN_PRICING:
        raise SystemExit(f'[ABORTA] la Pricing trajo solo {len(pr_marca)} SKU con marca')
    mx_marca, mx_pack, mx_corp = leer_matriz()
    graf = Grafia(pr_marca.values())

    tm = {r['id']: limpia(r['brand_id'][1] if r['brand_id'] else '') for r in t}
    ttype = {r['id']: r['type'] for r in t}
    tact = {r['id']: r['active'] for r in t}
    bom_tmpl = {}
    for r in sorted(b, key=lambda r: (not r['active'], -r['id'])):   # activa > archivada; la más nueva
        if r['product_tmpl_id']:
            bom_tmpl.setdefault(r['product_tmpl_id'][0], r['id'])
    comp = {}
    for r in bl:
        if r['bom_id'] and r['product_id']:
            comp.setdefault(r['bom_id'][0], []).append(r['product_id'][0])
    var_code = {r['id']: norm_sku(r['default_code'] or '') for r in p}

    fichas = {}   # SKU → plantillas (activas primero)
    for r in p:
        sk = norm_sku(r['default_code'] or '')
        if sk and r['product_tmpl_id']:
            tid = r['product_tmpl_id'][0]
            fichas.setdefault(sk, []).append((bool(r['active'] and tact.get(tid)), tid))

    def odoo_de(sk):
        f = fichas.get(sk)
        if not f:
            return None
        act = [tid for a, tid in f if a]
        base = list(dict.fromkeys(act or [tid for _, tid in f]))
        marcas = {graf(tm.get(x, '')) for x in base} - {''}
        unica = len({clave(m) for m in marcas}) == 1
        return {'tmpls': base, 'tipo': ttype.get(base[0]), 'marca': next(iter(marcas)) if unica else '',
                'bom': any(x in bom_tmpl for x in base)}

    def verificada(sk):
        """Pasos 1-2 para un SKU cualquiera (componente o SKU original de un Open Box)."""
        o = odoo_de(sk)
        if o and o['marca']:
            return o['marca']
        return graf(pr_marca.get(sk, ''))

    def de_componentes(sk, o):
        comps = []
        if o:
            for tid in o['tmpls']:
                if tid in bom_tmpl:
                    comps = [var_code.get(c, '') for c in comp.get(bom_tmpl[tid], [])]
                    break
        if not comps:
            comps = pk_comp.get(sk, [])
        ms = {verificada(c) for c in comps if c} - {''}
        return next(iter(ms)) if comps and len({clave(m) for m in ms}) == 1 else ''

    universo = set(fichas) | {k for k, v in pr_marca.items() if v} | set(mx_marca)
    filas = []
    for sk in sorted(universo):
        o = odoo_de(sk)
        if NO_PRODUCTO.match(sk) or (o and o['tipo'] == 'service'):
            continue
        es_pack = bool((o and o['bom']) or sk in pr_pack or sk in mx_pack or sk in pk_comp or sk.startswith(('pack', 'kit')))
        m_odoo = o['marca'] if o else ''
        m_pr = graf(pr_marca.get(sk, ''))
        if m_odoo:
            marca, fuente = m_odoo, 'odoo'
        elif m_pr:
            marca, fuente = m_pr, 'pricing'
        elif es_pack and (m_comp := de_componentes(sk, o)):
            marca, fuente = m_comp, 'componentes'
        elif sk.startswith('ob-') and (m_base := verificada(sk[3:])):
            marca, fuente = m_base, 'open box'
        elif CORPORATIVO.match(sk) or sk in mx_corp:
            marca, fuente = graf(MARCA_CORPORATIVO), 'corporativo'
        elif graf(mx_marca.get(sk, '')):
            marca, fuente = graf(mx_marca[sk]), 'matriz'
        else:
            marca, fuente = SIN, 'sin marca'
        filas.append({'sku_norm': sk, 'marca': marca, 'fuente': fuente})
    return pd.DataFrame(filas)


def backfill():
    """Aplica la marca verificada al histórico: cambia SOLO marca y tipo_marca (este último solo donde cambió la marca).
    Respaldo antes de escribir."""
    import shutil
    from mejoras_raw_overlay import marca_verificada
    from clasificar_marca import clasificar_tipo_marca
    h = pd.read_parquet(HIST)
    antes = h['marca'].astype(str).copy()
    h = marca_verificada(h, verbose=True)
    cambia = antes.ne(h['marca'].astype(str))
    h.loc[cambia, 'tipo_marca'] = h.loc[cambia, 'marca'].apply(clasificar_tipo_marca)
    if 'es_despacho' in h.columns:
        h.loc[cambia & h['es_despacho'].fillna(False).astype(bool), 'tipo_marca'] = 'Envío'
    print(f'[backfill] filas con marca distinta: {int(cambia.sum()):,} de {len(h):,}')
    shutil.copy2(HIST, HIST.with_suffix(f'.parquet.bak_marca_{date.today():%Y%m%d}'))
    h.to_parquet(HIST, index=False, compression='zstd')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pricing-file', help='copia local de la Maestra Pricing (prueba)')
    ap.add_argument('--backfill', action='store_true', help='aplica la marca verificada al histórico')
    a = ap.parse_args()
    if a.backfill:
        return backfill()
    xlsx = Path(a.pricing_file).read_bytes() if a.pricing_file else bajar_pricing()
    ms = construir(leer_odoo(), xlsx)
    PLANILLAS.mkdir(parents=True, exist_ok=True)
    ms.to_csv(OUT_SKU, index=False, encoding='utf-8', lineterminator='\n')
    print(f'[OK] {OUT_SKU.name}: {len(ms):,} SKU · ' + ' · '.join(f'{k} {v:,}' for k, v in ms.fuente.value_counts().items()))


if __name__ == '__main__':
    main()
