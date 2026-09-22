# -*- coding: utf-8 -*-
"""Normalización del RAW de ventas: un SKU limpio y UN nombre por SKU en toda la historia.

POR QUÉ EXISTE (22-09-2026)
  El extract escribe `producto` con el nombre vigente al momento de extraer. Cuando
  Nicole estandarizó nombres en la Matriz (agosto 2026) el mes actual empezó a salir
  con nombres largos y el histórico congelado quedó con los cortos: 243 SKUs con dos
  nombres, 32,5% de la venta. `mejoras_raw_overlay` (P1/P1d) ya unifica DENTRO del
  archivo que procesa; esto lo hace ENTRE archivos (histórico + mes actual) y arregla
  además tres bugs de SKU.

QUÉ HACE
  1. SKU: strip; formato numérico de Excel roto ("1.659.991.971.809,00" → "1659991971809",
     venía del import CMR); variantes de mayúscula que existen en la fuente canónica
     ("Lvmonpor-15" → "LVMONPOR-15", 42 casos).
  2. producto: un nombre canónico por SKU desde la FUENTE elegida (--fuente matriz|odoo),
     con respaldo en la otra y una tabla de overrides para lo que no es un producto
     (Delivery_007 → "Envíos", ApCom → "Aportes comerciales").
  3. Conserva el nombre original en `producto_origen` (única memoria del nombre viejo).
  4. Filas sin SKU: NO se tocan (no se pueden resolver por nombre); se reportan.

USO
  python normalizar_raw.py --fuente matriz                    # dry-run sobre histórico + mes actual
  python normalizar_raw.py --fuente matriz --aplicar          # reescribe ambos parquets (con .bak)
  python normalizar_raw.py --fuente matriz --solo-mapa        # solo refresca data/maestra/nombres_canonicos.parquet
  Desde código: from normalizar_raw import aplicar; df = aplicar(df)   (usa el mapa cacheado)
"""
import argparse, json, os, re, shutil, sys, datetime as dt
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent
HIST = ROOT / 'data/historico/ventas_historico.parquet'
MESA = ROOT / 'data/historico/ventas_mes_actual.parquet'
MATRIZ = ROOT / 'data/planillas/Matriz productos.xlsx'
MAPA = ROOT / 'data/maestra/nombres_canonicos.parquet'
FUENTE_DEFAULT = os.environ.get('RAW_FUENTE_NOMBRE', 'matriz')

# Lo que NO es un producto de catálogo, o cuya ficha trae un nombre inservible.
# OJO: una sola grafía por SKU acá. Las variantes van en SKU_ALIAS; si un override
# tuviera dos grafías del mismo SKU, la regla de mayúsculas los alternaría en cada
# corrida (pasó con tulogo/Tulogo el 22-09) y el proceso dejaría de ser idempotente.
OVERRIDES = {
    'Delivery_007': 'Envíos',            # Odoo: "Free delivery charges"; Matriz: "Envios"
    'ApCom': 'Aportes comerciales',
    'APORTE-RIPLEY': 'Aporte Promocional Tarjeta Ripley',
    'Tulogo': 'Personalización con Logo',
}
SKU_ALIAS = {'apcom': 'ApCom', 'tulogo': 'Tulogo', 'delivery_007': 'Delivery_007'}   # variantes → SKU canónico
SIN_SKU = {'', 'nan', 'none', '<na>'}


# ───────────────────────── fuentes ─────────────────────────
def _odoo_nombres(skus):
    """{sku: nombre} desde product.product (ficha activa primero)."""
    import xmlrpc.client
    cfg = json.load(open(ROOT / 'odoo/odoo_config.json'))['produccion']
    pw = os.environ.get('ANDRES_ODOO_PASSWORD', '') or (ROOT / 'odoo/.odoo_pass').read_text().strip()
    uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(cfg['db_name'], cfg['username'], pw, {})
    M = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object")
    out = {}
    skus = sorted(skus)
    for i in range(0, len(skus), 400):
        rs = M.execute_kw(cfg['db_name'], uid, pw, 'product.product', 'search_read',
                          [[['default_code', 'in', skus[i:i + 400]], ['active', 'in', [True, False]]]],
                          {'fields': ['default_code', 'name', 'active']})
        for p in sorted(rs, key=lambda x: (not x['active'], x['id'])):
            k = str(p['default_code']).strip()
            if k and k not in out and str(p['name']).strip():
                out[k] = str(p['name']).strip()
    return out


def _matriz_nombres():
    mx = pd.read_excel(MATRIZ)
    ks = next(c for c in mx.columns if str(c).strip().lower() == 'sku')
    kp = next(c for c in mx.columns if str(c).strip().lower() == 'producto')
    mx = mx[[ks, kp]].dropna()
    mx[ks] = mx[ks].astype(str).str.strip(); mx[kp] = mx[kp].astype(str).str.strip()
    mx = mx[mx[ks].ne('') & mx[kp].ne('') & ~mx[kp].isin(['0', 'nan'])].drop_duplicates(ks, keep='first')
    return dict(zip(mx[ks], mx[kp]))


def construir_mapa(skus_raw, fuente=FUENTE_DEFAULT, guardar=True):
    """Mapa canónico {sku: nombre} = fuente principal, respaldo en la otra, overrides encima.
    Se guarda con la fecha para que `aplicar()` no dependa de Odoo/Drive en cada corrida."""
    principal = _matriz_nombres() if fuente == 'matriz' else _odoo_nombres(skus_raw)
    respaldo = _odoo_nombres(set(skus_raw) - set(principal)) if fuente == 'matriz' else _matriz_nombres()
    mapa = dict(respaldo); mapa.update(principal); mapa.update(OVERRIDES)
    mapa = {k: v for k, v in mapa.items() if v and v.strip() not in ('0', 'nan') and k not in SKU_ALIAS}
    # una sola grafía por SKU en el mapa: si la fuente trae "Pack88" y "PACK88", gana la
    # primera y la otra se resuelve por la regla de mayúsculas (evita alternancias).
    vistos, limpio = set(), {}
    for k, v in mapa.items():
        if k.upper() in vistos:
            continue
        vistos.add(k.upper()); limpio[k] = v
    mapa = limpio
    if guardar:
        MAPA.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({'sku': list(mapa), 'producto': list(mapa.values())}).assign(
            fuente=fuente, ts=dt.datetime.now().isoformat(timespec='seconds')).to_parquet(MAPA, index=False)
    return mapa


def cargar_mapa():
    if not MAPA.exists():
        raise FileNotFoundError(f'No existe {MAPA}. Corre: python normalizar_raw.py --solo-mapa')
    m = pd.read_parquet(MAPA)
    return dict(zip(m['sku'], m['producto']))


# ───────────────────────── normalización ─────────────────────────
_NUM_ROTO = re.compile(r'^\d{1,3}(\.\d{3})+(,\d{1,2})?$')


def normalizar_sku(s, canon_upper):
    s = str(s).strip()
    if s.lower() in SIN_SKU:
        return ''
    if _NUM_ROTO.match(s):                      # "1.659.991.971.809,00" → "1659991971809"
        s = re.sub(r'\D', '', s.split(',')[0])
    if s in SKU_ALIAS:                          # alias explícito manda sobre la regla de mayúsculas
        return SKU_ALIAS[s]
    if s in canon_upper.values():               # ya está en su grafía canónica
        return s
    if s.upper() in canon_upper:
        return canon_upper[s.upper()]          # "Lvmonpor-15" → "LVMONPOR-15"
    return s


def aplicar(df, mapa=None, verbose=True):
    """Devuelve df con sku limpio, producto canónico y producto_origen. No toca otras columnas."""
    log = print if verbose else (lambda *a, **k: None)
    if 'sku' not in df.columns or 'producto' not in df.columns:
        return df
    mapa = mapa or cargar_mapa()
    canon_upper = {k.upper(): k for k in mapa}
    df = df.copy()
    sku0 = df['sku'].astype(str).str.strip()
    sku1 = sku0.map(lambda s: normalizar_sku(s, canon_upper))
    n_sku = int((sku0 != sku1).sum())
    df['sku'] = sku1
    prod0 = df['producto'].astype(str).str.strip().replace({'nan': '', 'None': ''})
    if 'producto_origen' not in df.columns:
        df['producto_origen'] = prod0
    else:
        df['producto_origen'] = df['producto_origen'].astype(str).replace({'nan': '', 'None': ''}).where(
            df['producto_origen'].astype(str).str.strip().ne(''), prod0)
    nuevo = sku1.map(mapa)
    mask = nuevo.notna() & sku1.ne('')
    n_prod = int((mask & (prod0 != nuevo)).sum())
    df.loc[mask, 'producto'] = nuevo[mask].values
    sin_sku = int(sku1.eq('').sum()); sin_mapa = int((~mask & sku1.ne('')).sum())
    log(f'  [normalizar] SKU corregidos: {n_sku:,} · nombres homologados: {n_prod:,} de {len(df):,} filas '
        f'· sin SKU (se dejan): {sin_sku:,} · con SKU sin nombre canónico: {sin_mapa:,}')
    return df


def _resumen(df, etiqueta):
    v = df[df['tipo_movimiento'].astype(str).str.startswith('Venta')] if 'tipo_movimiento' in df.columns else df
    g = v.groupby(v['sku'].astype(str))['producto'].nunique()
    print(f'  {etiqueta}: {len(df):,} filas · SKUs con >1 nombre: {int((g > 1).sum())} · venta neta ${pd.to_numeric(v["venta_neta"], errors="coerce").sum():,.0f}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fuente', choices=['matriz', 'odoo'], default=FUENTE_DEFAULT)
    ap.add_argument('--aplicar', action='store_true', help='reescribe los parquets (con respaldo .bak)')
    ap.add_argument('--solo-mapa', action='store_true')
    a = ap.parse_args()

    h = pd.read_parquet(HIST); m = pd.read_parquet(MESA) if MESA.exists() else None
    skus = set(h['sku'].astype(str).str.strip()) | (set(m['sku'].astype(str).str.strip()) if m is not None else set())
    skus = {s for s in skus if s.lower() not in SIN_SKU}
    print(f'[mapa] construyendo desde {a.fuente} para {len(skus):,} SKUs...', flush=True)
    mapa = construir_mapa(skus, a.fuente)
    print(f'[mapa] {len(mapa):,} nombres canónicos → {MAPA.relative_to(ROOT)}')
    if a.solo_mapa:
        return

    print('\nANTES'); _resumen(h, 'histórico');
    if m is not None: _resumen(m, 'mes actual')
    print('\nNORMALIZANDO')
    h2 = aplicar(h, mapa); m2 = aplicar(m, mapa) if m is not None else None
    print('\nDESPUÉS'); _resumen(h2, 'histórico')
    if m2 is not None: _resumen(m2, 'mes actual')
    if m2 is not None:
        both = pd.concat([h2[['sku', 'producto', 'tipo_movimiento']], m2[['sku', 'producto', 'tipo_movimiento']]])
        _resumen(both.assign(venta_neta=0), 'histórico + mes actual (unión)')

    # invariantes: mismas filas, misma venta, columnas preservadas (+ producto_origen)
    for old, new, nom in [(h, h2, 'histórico'), (m, m2, 'mes actual')]:
        if old is None: continue
        assert len(old) == len(new), f'{nom}: cambió el número de filas'
        assert abs(pd.to_numeric(old['venta_neta'], errors='coerce').sum() - pd.to_numeric(new['venta_neta'], errors='coerce').sum()) < 1, f'{nom}: cambió la venta'
        assert set(old.columns) <= set(new.columns) and set(new.columns) - set(old.columns) <= {'producto_origen'}, f'{nom}: columnas'
    print('\n[verif] filas, venta neta y columnas intactas (+ producto_origen) ✓')

    if not a.aplicar:
        print('\n→ dry-run. Usa --aplicar para reescribir.'); return
    for p, d in [(HIST, h2), (MESA, m2)]:
        if d is None: continue
        bak = p.with_suffix(f'.parquet.bak_normalizar_{dt.date.today():%Y%m%d}')
        shutil.copy2(p, bak)
        d.to_parquet(p, index=False, compression='zstd' if p == HIST else None)
        print(f'[OK] {p.relative_to(ROOT)} reescrito · respaldo {bak.name}')


if __name__ == '__main__':
    main()
