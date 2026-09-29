# -*- coding: utf-8 -*-
"""Cuadre mensual del margen final del RAW contra las liquidaciones (Andrés 29-09-2026).

Durante el mes, el RAW lleva un margen final ESTIMADO por pedido (campos de Odoo del agente
de Martín, tarifarios Recíbelo/BlueX, reglas por canal). Cuando llegan las liquidaciones del
mes a la carpeta de Drive de Gabriela, este paso lo lleva a lo REAL:

    residual(canal, centro) = liquidación del mes − lo que el RAW ya tiene

y lo reparte entre las filas de venta de ese canal y mes, sin tocar la venta:
    · logística → por peso (peso_sku × cantidad; sin peso, por venta)
    · comisión y marketing → por venta neta
    · las líneas de envío (Delivery_*) no reciben nada
Así el total del canal cuadra con lo cobrado y se mantiene el detalle por unidad vendida.
Incluye los cargos que el canal cobra a la cuenta (publicidad, cofinanciamiento, couriers,
cargos Full, aportes), que no existen por pedido en Odoo. Marketing de marketplaces entra al
margen final (Andrés 29-09).

Solo cuadra un canal si su carpeta del mes tiene archivos. Idempotente: si se corre dos
veces, el residual de la segunda es ~0. Deja traza: fuente_comision += '+cuadre' y un CSV
data/rentabilidad/cuadre_YYYY-MM.csv (canal, centro, RAW antes, liquidación, residual).

Uso:  python cuadre_liquidacion.py 2026-08 [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

P_HIST = ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
P_MES = ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
PESOS = ROOT / 'data' / 'planillas' / 'pesos_sku.parquet'
OUT = ROOT / 'data' / 'rentabilidad'
CENTRO_COL = {'Comisión venta': 'comision', 'Comisión envío': 'logistica', 'Marketing': 'marketing'}
# nombres de canal de los reportes de courier → canal del RAW
CANAL_MAP = {'simplit home': 'Simplit web', 'simplit web': 'Simplit web', 'lhotse': 'Lhotse web', 'lhotse web': 'Lhotse web',
             'unionx web': 'UnionX web', 'latam pass': 'LATAM Pass', 'grs': 'Global Reward', 'global reward': 'Global Reward',
             'bice': 'Banco Bice', 'banco bice': 'Banco Bice', 'unionxb2b': 'UnionX B2B', 'unionx b2b': 'UnionX B2B',
             'cmr': 'CMR', 'celmedia': 'Celmedia', 'mercado libre': 'Mercado Libre', 'falabella': 'Falabella',
             'ripley': 'Ripley', 'paris': 'Paris', 'walmart': 'Walmart', 'marketing': 'Marketing'}
CARPETA_DE = {'Mercado Libre': 'MELI', 'Falabella': 'FALABELLA', 'Paris': 'PARIS', 'Ripley': 'RIPLEY', 'Walmart': 'WALMART'}
# Canales que NO se cuadran con los reportes de courier porque esos reportes no cubren toda
# su logística: B2B también despacha por otros transportistas (ej. ICCM, en fletes) que no
# están en la carpeta. Mantiene el tarifario hasta tener todas sus facturas de flete.
NO_CUADRAR = {('UnionX B2B', 'Comisión envío'), ('Marketing', 'Comisión envío')}


def liquidacion_del_mes(mes: str):
    """Lee la carpeta de Drive del mes con la lectura automática. Devuelve (liq, carpetas_con_archivos)."""
    import rentabilidad_reporte_semanal as R
    import rentabilidad_liquidaciones as RL
    drv, arbol = R.drive_carpeta()
    m = int(mes[5:7])
    con = {c for c, meses in arbol.items() if meses.get(m)}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        R.bajar_mes(drv, arbol, m, Path(td))
        liq = RL.leer_carpeta(Path(td))
    liq['canal_raw'] = liq['canal'].astype(str).str.strip().str.lower().map(CANAL_MAP)
    return liq, con


def cuadrar(df: pd.DataFrame, mes: str, liq: pd.DataFrame, carpetas: set, verbose=True):
    df = df.copy()
    for c in ('venta_neta', 'cantidad', 'margen_front', 'comision', 'logistica', 'marketing', 'margen_final', 'comision_pct'):
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
    df['fuente_comision'] = df.get('fuente_comision', '').fillna('').astype(str) if 'fuente_comision' in df else ''
    en_mes = (df['fecha_venta'].astype(str).str[:7] == mes) & df['tipo_movimiento'].astype(str).isin(['Venta', 'Devolución'])
    es_env = df['sku'].astype(str).str.startswith('Delivery')
    base = en_mes & ~es_env & (df['tipo_movimiento'] == 'Venta') & (df['venta_neta'] > 0)
    pesos = {}
    if PESOS.exists():
        pp_ = pd.read_parquet(PESOS)
        pesos = dict(zip(pp_['sku'].astype(str), pd.to_numeric(pp_['peso_kg'], errors='coerce').fillna(0)))
    peso_def = float(np.median(list(pesos.values()))) if pesos else 0.5
    df['_peso'] = df['sku'].astype(str).map(pesos).fillna(peso_def) * df['cantidad'].clip(lower=0)

    # qué canales cuadran: marketplaces con su carpeta del mes; el resto (couriers) si el
    # canal aparece en el reporte de courier del mes
    liq = liq[liq['canal_raw'].notna() & liq['centro_costo'].isin(CENTRO_COL)]
    objetivo = liq.groupby(['canal_raw', 'centro_costo'])['monto_neto'].sum()
    filas = []
    for (canal, centro), T in objetivo.items():
        if canal in CARPETA_DE and CARPETA_DE[canal] not in carpetas:
            continue
        if (canal, centro) in NO_CUADRAR:
            filas.append(dict(canal=canal, centro=centro, raw_antes=float(df.loc[en_mes & (df['canal'] == canal), CENTRO_COL[centro]].sum()),
                              liquidacion=T, residual=0, aplicado=0, nota='no se cuadra: faltan fletes de otros transportistas'))
            continue
        col = CENTRO_COL[centro]
        mc = en_mes & (df['canal'] == canal)
        if not mc.any():
            filas.append(dict(canal=canal, centro=centro, raw_antes=0, liquidacion=T, residual=T, aplicado=0, nota='sin venta en el RAW'))
            continue
        # para couriers, el objetivo de logística es el courier: se suma a lo que el canal
        # ya trae del marketplace (ej. ML: envío MELI + Recíbelo Flex). Se compara contra
        # el total del centro en el RAW.
        R0 = float(df.loc[mc, col].sum())
        D = float(T) - R0
        tgt = base & (df['canal'] == canal)
        w = df.loc[tgt, '_peso'] if col == 'logistica' else df.loc[tgt, 'venta_neta']
        if w.sum() <= 0:
            w = df.loc[tgt, 'venta_neta']
        if w.sum() <= 0 or abs(D) < 1:
            filas.append(dict(canal=canal, centro=centro, raw_antes=R0, liquidacion=T, residual=D, aplicado=0, nota='' if abs(D) < 1 else 'sin filas para repartir'))
            continue
        df.loc[tgt, col] = df.loc[tgt, col] + D * w / w.sum()
        f = df.loc[tgt, 'fuente_comision']
        df.loc[tgt, 'fuente_comision'] = f.where(f.str.contains('cuadre'), (f + '+cuadre').str.lstrip('+'))
        filas.append(dict(canal=canal, centro=centro, raw_antes=R0, liquidacion=T, residual=D, aplicado=D, nota=''))
    df.loc[en_mes, 'margen_final'] = (df.loc[en_mes, 'margen_front'] - df.loc[en_mes, 'comision']
                                      - df.loc[en_mes, 'logistica'] - df.loc[en_mes, 'marketing'])
    v = df.loc[en_mes, 'venta_neta']
    df.loc[en_mes, 'comision_pct'] = (df.loc[en_mes, 'comision'] / v.where(v != 0) * 100).fillna(0)
    df = df.drop(columns=['_peso'])
    log = pd.DataFrame(filas)
    if verbose and len(log):
        print(log.assign(**{c: log[c] / 1e6 for c in ['raw_antes', 'liquidacion', 'residual', 'aplicado']}).round(2).to_string(index=False))
    return df, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mes')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--liq', help='parquet de la lectura automática (si no, se lee de Drive)')
    a = ap.parse_args()
    if a.liq:
        liq = pd.read_parquet(a.liq)
        liq['canal_raw'] = liq['canal'].astype(str).str.strip().str.lower().map(CANAL_MAP)
        carpetas = {CARPETA_DE[c] for c in liq['canal_raw'].dropna().unique() if c in CARPETA_DE}
    else:
        liq, carpetas = liquidacion_del_mes(a.mes)
    # el mes vive en el histórico si ya está congelado; si no, en el mes actual
    df = pd.read_parquet(P_HIST)
    path = P_HIST
    if not (df['fecha_venta'].astype(str).str[:7] == a.mes).any():
        df, path = pd.read_parquet(P_MES), P_MES
    antes = df.copy()
    out, log = cuadrar(df, a.mes, liq, carpetas)
    en_mes = out['fecha_venta'].astype(str).str[:7] == a.mes
    fuera = ~en_mes
    for c in ['venta_neta', 'comision', 'logistica', 'marketing', 'margen_final']:
        x = pd.to_numeric(antes.loc[fuera, c], errors='coerce').fillna(0).values
        assert np.abs(x - out.loc[fuera, c].values).max() < 1e-6, f'cambió {c} fuera del mes'
    assert abs(pd.to_numeric(antes['venta_neta'], errors='coerce').sum() - out['venta_neta'].sum()) < 1, 'cambió la venta'
    A, B = out[en_mes], antes[en_mes]
    cols = ['venta_neta', 'comision', 'logistica', 'marketing', 'margen_final']
    print(pd.DataFrame({'antes': [pd.to_numeric(B[c], errors='coerce').sum() / 1e6 for c in cols],
                        'con cuadre': [A[c].sum() / 1e6 for c in cols]}, index=cols).round(2).T.to_string())
    if a.dry_run:
        return
    for c in antes.columns:
        if antes[c].dtype != out[c].dtype:
            try:
                out[c] = out[c].astype(antes[c].dtype)
            except Exception:
                pass
    out.to_parquet(path, index=False, compression='zstd')
    OUT.mkdir(parents=True, exist_ok=True)
    log.to_csv(OUT / f'cuadre_{a.mes}.csv', index=False, encoding='utf-8-sig')
    print(f'[OK] {path.name} cuadrado para {a.mes} · log {OUT / f"cuadre_{a.mes}.csv"}')


if __name__ == '__main__':
    main()
