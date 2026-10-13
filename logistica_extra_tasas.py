# -*- coding: utf-8 -*-
"""Tasas de logística que no viene por pedido, para el margen final del RAW (Andrés 13-oct).

Mercado Libre cobra, además de lo que trae cada pedido en Odoo:
  · Envíame: courier de los envíos a regiones (factura mensual, carpeta ENVIAME de las liquidaciones).
  · Cargos de Full: almacenamiento, retiro de stock, colecta, stock antiguo, variación del servicio.

Fuente: la carga de Gabriela en la macro de Rentabilidad (pestaña "2. Carga Gabriela", neto), que es la que
manda en la macro. Tasa del mes = cargo / venta neta de productos de ML del mes (Envíame sobre la venta que no es
Full; los cargos de Full sobre la venta Full). margen_final_reglas.py la aplica a cada venta de producto; los meses
que todavía no tienen carga usan la última tasa conocida.

Escribe data/planillas/logistica_extra_tasas.csv. Corre a diario en el vigía de liquidaciones (rentabilidad_vigia.yml).
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
SALIDA = ROOT / 'data' / 'planillas' / 'logistica_extra_tasas.csv'
DESDE = '2026-06'            # CUTOFF del devengo (margen_final_reglas)
# canal, concepto, patrón de la glosa en la carga de Gabriela (centro "Comisión envío"), venta base
CONCEPTOS = [('Mercado Libre', 'Envíame', r'envia', 'no_full'),
             ('Mercado Libre', 'Cargos Full', r'full', 'full')]


def ventas_base() -> pd.DataFrame:
    """Venta neta de productos por canal × mes, separada en Full y no Full (histórico + mes en curso)."""
    cols = ['fecha_venta', 'canal', 'sku', 'tipo_movimiento', 'venta_neta', 'bodega']
    h = pd.read_parquet(ROOT / 'data/historico/ventas_historico.parquet', columns=cols)
    partes = [h]
    mp = ROOT / 'data/historico/ventas_mes_actual.parquet'
    if mp.exists():
        m = pd.read_parquet(mp, columns=cols)
        meses_h = set(h['fecha_venta'].astype(str).str[:7])
        partes.append(m[~m['fecha_venta'].astype(str).str[:7].isin(meses_h)])
    r = pd.concat(partes, ignore_index=True)
    r['venta_neta'] = pd.to_numeric(r['venta_neta'], errors='coerce').fillna(0.0)
    r = r[(r['tipo_movimiento'].astype(str) == 'Venta') & ~r['sku'].astype(str).str.startswith('Delivery') & (r['venta_neta'] > 0)]
    r = r.assign(mes=r['fecha_venta'].astype(str).str[:7],
                 full=r['bodega'].astype(str).str.lower().str.contains('fulfillment'))
    return r


def main() -> int:
    import macro_rentabilidad_drive as MD
    sh, _ = MD._abrir(MD._cli(), crear_si_falta=False)
    g = MD.gab_df(sh.worksheet(MD.H_GAB).get_all_values())
    g['Canal'] = MD.canonizar(g['Canal'], sorted({c for c, *_ in CONCEPTOS}))     # "Mercado Libre 2" → "Mercado Libre"
    g = g[(g['Centro de costo'] == 'Comisión envío') & (g['Mes'] >= DESDE)]
    v = ventas_base()
    filas = []
    for canal, concepto, patron, base in CONCEPTOS:
        x = g[(g['Canal'] == canal) & g['Glosa'].astype(str).str.contains(patron, case=False, regex=True)]
        for mes, monto in x.groupby('Mes')['Valor'].sum().items():
            y = v[(v['canal'] == canal) & (v['mes'] == mes)]
            vb = float(y.loc[y['full'] if base == 'full' else ~y['full'], 'venta_neta'].sum())
            if monto > 0 and vb > 0:
                filas.append({'canal': canal, 'concepto': concepto, 'base': base, 'mes': mes, 'monto': round(float(monto)),
                              'venta_base': round(vb), 'tasa': round(float(monto) / vb, 6),
                              'fuente': 'Carga Gabriela (macro Rentabilidad)'})
    if not filas:
        print('[logistica_extra_tasas] sin cargos en la carga de Gabriela: no toco el archivo')
        return 0
    t = pd.DataFrame(filas).sort_values(['canal', 'concepto', 'mes'])
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(SALIDA, index=False)
    print(t.to_string(index=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
