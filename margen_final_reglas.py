# -*- coding: utf-8 -*-
"""Reglas por canal del margen final del RAW (ago-2026 en adelante).

margen_final = margen_front − comisión − logística − marketing

El extract (ventas_service) ya calcula comisión y logística por pedido para los
marketplaces (campos de Odoo del agente de Martín) y para los canales de la matriz
(% flat + envío tarifario BlueX). Este paso aplica ENCIMA las reglas por canal que
definió Andrés el 24-09-2026 (Excel "Canales sin regla de comisión"), que viven en
data/planillas/reglas_margen_final.csv:

  canal, com_pct, log_pct, mkt_pct, modo_com, modo_log, com_pct_evento, meses_evento, fuente, nota
  · modo_log = 'si_vacio': la logística % solo se pone si la fila no trae (CMR tras el rebuild del Drive).

  · modo_com = 'sku': comisión por SKU desde data/planillas/comision_sku_canal.csv
    (ej. matriz de Hites); los SKU que no están usan com_pct como respaldo.
  · com_pct_evento + meses_evento (ej. '2026-10'): tasa distinta en meses de evento
    (Abc: 14% normal, 28% en el mes de Cyber — Nicole 24-09).
  · Las líneas de envío (SKU Delivery_*) no llevan costos: son lo que paga el
    comprador por el despacho. Los % manuales se calculan solo sobre la venta de
    productos, y lo que viene por pedido (Odoo, tarifario) y quedó en la línea de
    envío se reasigna a los productos del mismo pedido (Andrés 24-09). El total del
    pedido no cambia.

  · com_pct / log_pct / mkt_pct vacíos = no tocar lo que trae el extract.
  · modo_com = 'forzar' reemplaza la comisión; 'si_vacio' solo la pone si la fila
    viene sin comisión (CMR: la comisión real del Drive manda).
  · Las devoluciones llevan venta_neta negativa → comisión/logística/marketing
    negativos: revierten el costo de la venta devuelta.

Idempotente: se puede aplicar dos veces y da lo mismo. Solo toca filas Venta y
Devolución con fecha_venta >= CUTOFF, de los canales listados.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
REGLAS = ROOT / 'data' / 'planillas' / 'reglas_margen_final.csv'
COM_SKU = ROOT / 'data' / 'planillas' / 'comision_sku_canal.csv'
HIST = ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
# Devengo comercial desde jun-2026 (Andrés 30-09/01-10): jun–jul se recalcularon por pedido
# (reemplazan la carga manual "Otros costos"); ago en adelante viene así del extract.
CUTOFF = '2026-06-01'
MARKETPLACES = ('Mercado Libre', 'Falabella', 'Paris', 'Ripley', 'Walmart')
# Campo por pedido que puede venir vacío al vender (se llena con la liquidación) → promedio del canal
HUECOS = [(c, 'comision') for c in MARKETPLACES] + [('Ripley', 'logistica'), ('Walmart', 'logistica')]
COSTOS = ('comision', 'logistica', 'marketing')


def cargar_reglas(path: Path = REGLAS) -> pd.DataFrame:
    r = pd.read_csv(path, dtype={'canal': str})
    r['canal'] = r['canal'].str.strip()
    for c in ('com_pct', 'log_pct', 'mkt_pct', 'com_pct_evento'):
        if c not in r.columns:
            r[c] = None
        r[c] = pd.to_numeric(r[c], errors='coerce')
    if 'meses_evento' not in r.columns:
        r['meses_evento'] = ''
    r['meses_evento'] = r['meses_evento'].fillna('').astype(str)
    r['modo_com'] = r['modo_com'].fillna('forzar').str.strip()
    if 'modo_log' not in r.columns:
        r['modo_log'] = 'forzar'
    r['modo_log'] = r['modo_log'].fillna('forzar').astype(str).str.strip()
    return r.set_index('canal')


def aplicar(df: pd.DataFrame, reglas: pd.DataFrame | None = None, verbose: bool = False) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    reglas = cargar_reglas() if reglas is None else reglas
    com_sku = {}
    if COM_SKU.exists():
        _cs = pd.read_csv(COM_SKU, dtype={'sku': str, 'canal': str})
        for _, x in _cs.iterrows():
            com_sku.setdefault(str(x['canal']).strip(), {})[str(x['sku']).strip()] = float(x['com_pct'])
    df = df.copy()
    for c in ('venta_neta', 'costo_total', 'margen_front', 'comision', 'logistica', 'marketing', 'margen_final', 'comision_pct'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
        else:
            df[c] = 0.0
    if 'fuente_comision' not in df.columns:
        df['fuente_comision'] = ''
    df['fuente_comision'] = df['fuente_comision'].fillna('').astype(str)

    fv = df['fecha_venta'].astype(str).str[:10]
    base = (fv >= CUTOFF) & df['tipo_movimiento'].astype(str).isin(['Venta', 'Devolución'])
    tocadas = 0
    for canal, r in reglas.iterrows():
        m = base & (df['canal'].astype(str).str.strip() == canal)
        if not m.any():
            continue
        vn = df.loc[m, 'venta_neta']
        if pd.notna(r['com_pct']) or r['modo_com'] == 'sku':
            pct = pd.Series(r['com_pct'] if pd.notna(r['com_pct']) else 0.0, index=vn.index, dtype=float)
            if r['meses_evento'] and pd.notna(r['com_pct_evento']):
                ev = fv[m].str[:7].isin([x.strip() for x in r['meses_evento'].split(';') if x.strip()])
                pct[ev] = r['com_pct_evento']
            if r['modo_com'] == 'sku' and canal in com_sku:
                sk = df.loc[m, 'sku'].astype(str).str.strip().map(com_sku[canal])
                pct = sk.fillna(pct)
            pct[df.loc[m, 'sku'].astype(str).str.startswith('Delivery')] = 0.0
            nueva = vn * pct / 100.0
            if r['modo_com'] == 'si_vacio':
                sel = df.loc[m, 'comision'] == 0
                df.loc[m & sel.reindex(df.index, fill_value=False), 'comision'] = nueva[sel]
            else:
                df.loc[m, 'comision'] = nueva
        es_env = df.loc[m, 'sku'].astype(str).str.startswith('Delivery')
        if pd.notna(r['log_pct']):
            nueva_log = (vn * r['log_pct'] / 100.0).where(~es_env, 0.0)
            if r.get('modo_log', 'forzar') == 'si_vacio':
                sel_l = df.loc[m, 'logistica'] == 0
                df.loc[m & sel_l.reindex(df.index, fill_value=False), 'logistica'] = nueva_log[sel_l]
            else:
                df.loc[m, 'logistica'] = nueva_log
        if pd.notna(r['mkt_pct']):
            df.loc[m, 'marketing'] = (vn * r['mkt_pct'] / 100.0).where(~es_env, 0.0)
        df.loc[m, 'margen_final'] = (df.loc[m, 'margen_front'] - df.loc[m, 'comision']
                                     - df.loc[m, 'logistica'] - df.loc[m, 'marketing'])
        df.loc[m, 'comision_pct'] = (df.loc[m, 'comision'] / vn.where(vn != 0) * 100).fillna(0)
        f = df.loc[m, 'fuente_comision']
        df.loc[m, 'fuente_comision'] = f.where(f.str.contains('regla'), (f + '+regla').str.lstrip('+'))
        tocadas += int(m.sum())
    movido = _sacar_envio_del_reparto(df, base)
    n_prom = _promedio_canal(df, base, _ventas_referencia(df))
    # la referencia se rearma después del promedio: la devolución revierte lo que la venta lleva
    n_rev = _reversa_devoluciones(df, base, _ventas_referencia(df))
    # Identidad en TODAS las filas desde el corte (no solo las con regla): había filas
    # corregidas por pasos previos del RAW con margen_final = margen_front (24-09: 119
    # filas, $0,5M en septiembre).
    df.loc[base, 'margen_final'] = (df.loc[base, 'margen_front'] - df.loc[base, 'comision']
                                    - df.loc[base, 'logistica'] - df.loc[base, 'marketing'])
    if verbose:
        print(f"   [margen_final_reglas] {tocadas:,} filas con regla de canal ({len(reglas)} canales en la tabla)"
              f" · ${movido:,.0f} de costos movidos de líneas de envío a productos"
              f" · {n_prom:,} filas con promedio del canal · {n_rev:,} costos revertidos en devoluciones")
    return df


def _ventas_referencia(df: pd.DataFrame) -> pd.DataFrame:
    """Ventas del histórico + las del df (sin duplicar meses): base para tasas de respaldo y
    para revertir la devolución con el costo de su venta original."""
    cols = ['fecha_venta', 'tipo_movimiento', 'canal', 'pedido_marketplace', 'sku', 'cantidad', 'venta_neta', *COSTOS]
    partes = [df[[c for c in cols if c in df.columns]]]
    if HIST.exists():
        try:
            h = pd.read_parquet(HIST, columns=cols)
            meses_df = set(df['fecha_venta'].astype(str).str[:7])
            partes.insert(0, h[~h['fecha_venta'].astype(str).str[:7].isin(meses_df)])
        except Exception as e:  # el histórico es solo apoyo: sin él se usan las tasas del propio df
            print(f"   [margen_final_reglas][WARN] histórico no disponible: {type(e).__name__}")
    r = pd.concat(partes, ignore_index=True)
    for c in ('cantidad', 'venta_neta', *COSTOS):
        r[c] = pd.to_numeric(r[c], errors='coerce').fillna(0.0)
    return r[(r['tipo_movimiento'].astype(str) == 'Venta') & ~r['sku'].astype(str).str.startswith('Delivery')
             & (r['venta_neta'] > 0)]


def _tasa(ref: pd.DataFrame, canal: str, col: str, mes: str, minimo: int = 30, solo_con_dato: bool = True):
    """Tasa col/venta del canal en el mes; si el mes tiene menos de `minimo` ventas con dato,
    la del último mes anterior que sí tenga. Devuelve (tasa, mes_usado) o (None, None)."""
    x = ref[(ref['canal'] == canal) & ((ref[col] > 0) if solo_con_dato else True)]
    x = x.assign(_m=x['fecha_venta'].astype(str).str[:7])
    for m in sorted({m for m in x['_m'] if m <= mes}, reverse=True):
        y = x[x['_m'] == m]
        if len(y) >= minimo and y['venta_neta'].sum() > 0:
            return y[col].sum() / y['venta_neta'].sum(), m
    return None, None


def _promedio_canal(df: pd.DataFrame, base: pd.Series, ref: pd.DataFrame) -> int:
    """Pedido de marketplace sin el campo en Odoo (comisión; logística Ripley/Walmart) → promedio
    del canal, con comentario. Lo ideal es el % según contrato (Andrés 30-09)."""
    venta = base & (df['tipo_movimiento'] == 'Venta') & ~df['sku'].astype(str).str.startswith('Delivery') & (df['venta_neta'] > 0)
    mes = df['fecha_venta'].astype(str).str[:7]
    n = 0
    for canal, col in HUECOS:
        sin = venta & (df['canal'] == canal) & (df[col] == 0)
        for m in sorted(set(mes[sin])):
            sel = sin & (mes == m)
            tasa, m_ref = _tasa(ref, canal, col, m)
            if tasa is None:
                continue
            df.loc[sel, col] = df.loc[sel, 'venta_neta'] * tasa
            f = df.loc[sel, 'fuente_comision']
            df.loc[sel, 'fuente_comision'] = (f + f'·{col} promedio canal {m_ref} (lo ideal: contrato)').str.lstrip('·')
            n += int(sel.sum())
    return n


def _reversa_devoluciones(df: pd.DataFrame, base: pd.Series, ref: pd.DataFrame) -> int:
    """La venta conserva sus costos del momento de vender y la devolución los revierte (comisión,
    logística y marketing; Andrés 01-10). Si la N/C calza con su venta (pedido marketplace + SKU) se
    revierte lo de esa venta por unidad; si no, con la tasa del canal del mes. Solo costos en 0
    (los canales con % de contrato ya los revierten por la regla)."""
    dev = base & (df['tipo_movimiento'] == 'Devolución') & ~df['sku'].astype(str).str.startswith('Delivery') & (df['venta_neta'] < 0)
    if not dev.any():
        return 0
    r = ref[ref['pedido_marketplace'].astype(str).str.len() > 3]
    por_ud = r.groupby([r['pedido_marketplace'].astype(str), r['sku'].astype(str)])[['cantidad', *COSTOS]].sum()
    por_ud = por_ud[por_ud['cantidad'] > 0]
    llave = pd.Series(list(zip(df['pedido_marketplace'].astype(str), df['sku'].astype(str))), index=df.index)
    calza = dev & llave.isin(set(por_ud.index))
    mes = df['fecha_venta'].astype(str).str[:7]
    n = 0
    for col in COSTOS:
        sin = dev & (df[col] == 0)
        ex = sin & calza
        if ex.any():
            u = llave[ex].map(lambda k: por_ud.at[k, col] / por_ud.at[k, 'cantidad'])
            df.loc[ex, col] = df.loc[ex, 'cantidad'] * u          # cantidad < 0 → costo negativo
        for (canal, m), idx in df[sin & ~calza].groupby(['canal', mes[sin & ~calza]]).groups.items():
            tasa, _ = _tasa(ref, canal, col, m, minimo=1, solo_con_dato=False)
            if tasa is not None:
                df.loc[idx, col] = df.loc[idx, 'venta_neta'] * tasa
        hecho = sin & (df[col] != 0)
        etiqueta = pd.Series(f'·reversa {col} devolución (tasa canal)', index=df.index).where(~calza, f'·reversa {col} exacta')
        df.loc[hecho, 'fuente_comision'] = (df.loc[hecho, 'fuente_comision'] + etiqueta[hecho]).str.lstrip('·')
        n += int(hecho.sum())
    v = df.loc[dev, 'venta_neta']
    df.loc[dev, 'comision_pct'] = (df.loc[dev, 'comision'] / v.where(v != 0) * 100).fillna(0)
    return n


def _sacar_envio_del_reparto(df: pd.DataFrame, base: pd.Series) -> float:
    """Costos que quedaron en líneas Delivery_* → a los productos del mismo pedido,
    en proporción a su venta neta. Si el pedido no tiene productos, se quedan."""
    env = base & df['sku'].astype(str).str.startswith('Delivery')
    costo = df[['comision', 'logistica', 'marketing']].abs().sum(axis=1) > 0
    env_c = env & costo
    if not env_c.any():
        return 0.0
    key = df['pedido'].astype(str) + '|' + df['tipo_movimiento'].astype(str)
    prod = base & ~df['sku'].astype(str).str.startswith('Delivery') & (df['venta_neta'] != 0)
    peds = set(key[env_c])
    pm = prod & key.isin(peds)
    if not pm.any():
        return 0.0
    w = df.loc[pm, 'venta_neta'] / df.loc[pm].groupby(key[pm])['venta_neta'].transform('sum')
    movido = 0.0
    tiene_prod = key[env_c].isin(set(key[pm]))
    ec = env_c.copy(); ec[env_c] = tiene_prod.values
    for c in ('comision', 'logistica', 'marketing'):
        tot = df.loc[ec].groupby(key[ec])[c].sum()
        df.loc[pm, c] = df.loc[pm, c] + key[pm].map(tot).fillna(0) * w
        movido += float(df.loc[ec, c].abs().sum())
        df.loc[ec, c] = 0.0
    for idx in (pm, ec):
        df.loc[idx, 'margen_final'] = (df.loc[idx, 'margen_front'] - df.loc[idx, 'comision']
                                       - df.loc[idx, 'logistica'] - df.loc[idx, 'marketing'])
        v = df.loc[idx, 'venta_neta']
        df.loc[idx, 'comision_pct'] = (df.loc[idx, 'comision'] / v.where(v != 0) * 100).fillna(0)
    return movido


if __name__ == '__main__':
    import sys
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'data/historico/ventas_mes_actual.parquet'
    d = pd.read_parquet(p)
    a = aplicar(d, verbose=True)
    b = aplicar(a)
    assert (a['margen_final'] - b['margen_final']).abs().max() < 1e-6, 'no idempotente'
    s = a[a['fecha_venta'].astype(str) >= CUTOFF].groupby('canal')[['venta_neta', 'comision', 'logistica', 'marketing', 'margen_final']].sum()
    print((s / 1e6).round(2).sort_values('venta_neta', ascending=False).head(25).to_string())
