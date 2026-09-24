# -*- coding: utf-8 -*-
"""Reglas por canal del margen final del RAW (ago-2026 en adelante).

margen_final = margen_front − comisión − logística − marketing

El extract (ventas_service) ya calcula comisión y logística por pedido para los
marketplaces (campos de Odoo del agente de Martín) y para los canales de la matriz
(% flat + envío tarifario BlueX). Este paso aplica ENCIMA las reglas por canal que
definió Andrés el 24-09-2026 (Excel "Canales sin regla de comisión"), que viven en
data/planillas/reglas_margen_final.csv:

  canal, com_pct, log_pct, mkt_pct, modo_com, fuente, nota

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
CUTOFF = '2026-08-01'


def cargar_reglas(path: Path = REGLAS) -> pd.DataFrame:
    r = pd.read_csv(path, dtype={'canal': str})
    r['canal'] = r['canal'].str.strip()
    for c in ('com_pct', 'log_pct', 'mkt_pct'):
        r[c] = pd.to_numeric(r[c], errors='coerce')
    r['modo_com'] = r['modo_com'].fillna('forzar').str.strip()
    return r.set_index('canal')


def aplicar(df: pd.DataFrame, reglas: pd.DataFrame | None = None, verbose: bool = False) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    reglas = cargar_reglas() if reglas is None else reglas
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
        if pd.notna(r['com_pct']):
            nueva = vn * r['com_pct'] / 100.0
            if r['modo_com'] == 'si_vacio':
                sel = df.loc[m, 'comision'] == 0
                df.loc[m & sel.reindex(df.index, fill_value=False), 'comision'] = nueva[sel]
            else:
                df.loc[m, 'comision'] = nueva
        if pd.notna(r['log_pct']):
            df.loc[m, 'logistica'] = vn * r['log_pct'] / 100.0
        if pd.notna(r['mkt_pct']):
            df.loc[m, 'marketing'] = vn * r['mkt_pct'] / 100.0
        df.loc[m, 'margen_final'] = (df.loc[m, 'margen_front'] - df.loc[m, 'comision']
                                     - df.loc[m, 'logistica'] - df.loc[m, 'marketing'])
        df.loc[m, 'comision_pct'] = (df.loc[m, 'comision'] / vn.where(vn != 0) * 100).fillna(0)
        f = df.loc[m, 'fuente_comision']
        df.loc[m, 'fuente_comision'] = f.where(f.str.contains('regla'), (f + '+regla').str.lstrip('+'))
        tocadas += int(m.sum())
    if verbose:
        print(f"   [margen_final_reglas] {tocadas:,} filas con regla de canal ({len(reglas)} canales en la tabla)")
    return df


if __name__ == '__main__':
    import sys
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'data/historico/ventas_mes_actual.parquet'
    d = pd.read_parquet(p)
    a = aplicar(d, verbose=True)
    b = aplicar(a)
    assert (a['margen_final'] - b['margen_final']).abs().max() < 1e-6, 'no idempotente'
    s = a[a['fecha_venta'].astype(str) >= CUTOFF].groupby('canal')[['venta_neta', 'comision', 'logistica', 'marketing', 'margen_final']].sum()
    print((s / 1e6).round(2).sort_values('venta_neta', ascending=False).head(25).to_string())
