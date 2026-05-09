#!/usr/bin/env python3
"""
Extractor de stock historico desde Odoo.

Reconstruye saldo diario por (SKU, bodega_logica) usando:
1. Snapshot stock.quant actual = saldo de HOY por SKU x location
2. Movimientos stock.move (state=done) historicos = deltas dia a dia
3. Saldo[d] = saldo[d+1] - delta[d+1]   (backward iteration)

Bodegas logicas mapeadas (relevantes para forecast):
- CA1: Bodega Carrascal (warehouse_id=1) y todas sus locations internas
- BFML: Bodega Fulfillment Mercado Libre (warehouse_id=20)
- BFFa: Bodega Fulfillment Falabella (warehouse_id=18)
- BFP: Bodega Fulfillment Paris (warehouse_id=17)
- BFR: Bodega Fulfillment Ripley (warehouse_id=19)
- BFW: Bodega Fulfillment Walmart (warehouse_id=56)

Output:
- data/stock_historico/stock_diario.parquet (fecha, sku, bodega, cantidad)
- data/stock_historico/metadata.json
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient

ODOO_URL = 'https://unionxb2b.odoo.com'
ODOO_DB = 'bmya-innovatek-sh-prd-6981800'
ODOO_USER = 'andres@grupoeter.cl'
ODOO_PASSWORD = os.environ.get('ANDRES_ODOO_PASSWORD')

if not ODOO_PASSWORD:
    print("[ERROR] ANDRES_ODOO_PASSWORD no seteado", flush=True)
    sys.exit(1)

OUTPUT_DIR = PROJECT_ROOT / 'data' / 'stock_historico'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Bodegas relevantes: warehouse_id -> codigo logico
BODEGAS = {
    1: 'CA1',     # Carrascal (con todas sublocations)
    20: 'BFML',
    18: 'BFFa',
    17: 'BFP',
    19: 'BFR',
    56: 'BFW',
}

# Fecha desde la que extraer (24 meses por defecto)
FECHA_DESDE = os.environ.get('STOCK_HIST_DESDE', '2024-01-01')
FECHA_HASTA = datetime.now().strftime('%Y-%m-%d')


def _conectar_odoo() -> OdooClient:
    odoo = OdooClient(url=ODOO_URL, db=ODOO_DB, username=ODOO_USER, password=ODOO_PASSWORD, max_retries=5)
    odoo.authenticate()
    return odoo


def _obtener_locations_relevantes(odoo: OdooClient) -> tuple[dict, set]:
    """Devuelve (location_id -> bodega_logica, set_de_ids).

    Mapea cada location_id (incluyendo sublocations de CA1) a su codigo de bodega.
    """
    print("[1] Obteniendo locations relevantes...", flush=True)
    locs = odoo.search_read('stock.location',
                             [('warehouse_id', 'in', list(BODEGAS.keys())),
                              ('usage', '=', 'internal')],
                             ['id', 'warehouse_id', 'complete_name'],
                             limit=5000)
    loc_to_bodega = {}
    for loc in locs:
        wh = loc.get('warehouse_id')
        wh_id = wh[0] if isinstance(wh, list) else wh
        if wh_id in BODEGAS:
            loc_to_bodega[loc['id']] = BODEGAS[wh_id]
    print(f"   Total locations: {len(loc_to_bodega)} (CA1 contribuye la mayoria por sublocations)", flush=True)
    return loc_to_bodega, set(loc_to_bodega.keys())


def _snapshot_quant_actual(odoo: OdooClient, location_ids: set) -> pd.DataFrame:
    """Snapshot HOY: stock.quant para esas locations -> saldo actual por (sku, bodega)."""
    print("[2] Snapshot stock.quant LIVE...", flush=True)
    rows = odoo.search_read_paginated('stock.quant',
                                       [('location_id', 'in', list(location_ids))],
                                       ['product_id', 'location_id', 'quantity'],
                                       page_size=2000)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=['sku', 'bodega', 'cantidad'])
    df['product_id_id'] = df['product_id'].apply(lambda x: x[0] if isinstance(x, list) else x)
    df['product_name'] = df['product_id'].apply(lambda x: x[1] if isinstance(x, list) else '')
    df['location_id_id'] = df['location_id'].apply(lambda x: x[0] if isinstance(x, list) else x)
    print(f"   Total quants: {len(df):,}", flush=True)
    return df[['product_id_id', 'product_name', 'location_id_id', 'quantity']]


def _extraer_movimientos_mes(odoo: OdooClient, location_ids: set, mes_str: str) -> pd.DataFrame:
    """Movimientos stock.move state=done de un mes especifico, filtrados por locations."""
    desde = f'{mes_str}-01 00:00:00'
    # Calcular ultimo dia del mes
    año, mes = map(int, mes_str.split('-'))
    if mes == 12:
        hasta_dt = datetime(año + 1, 1, 1) - timedelta(seconds=1)
    else:
        hasta_dt = datetime(año, mes + 1, 1) - timedelta(seconds=1)
    hasta = hasta_dt.strftime('%Y-%m-%d %H:%M:%S')

    loc_list = list(location_ids)
    domain = [
        ('state', '=', 'done'),
        ('date', '>=', desde),
        ('date', '<=', hasta),
        '|',
        ('location_id', 'in', loc_list),
        ('location_dest_id', 'in', loc_list),
    ]
    rows = odoo.search_read_paginated('stock.move', domain,
                                       ['date', 'product_id', 'product_uom_qty',
                                        'location_id', 'location_dest_id'],
                                       page_size=2000)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df['fecha'] = pd.to_datetime(df['date']).dt.date
    df['product_id_id'] = df['product_id'].apply(lambda x: x[0] if isinstance(x, list) else None)
    df['loc_id'] = df['location_id'].apply(lambda x: x[0] if isinstance(x, list) else None)
    df['loc_dest_id'] = df['location_dest_id'].apply(lambda x: x[0] if isinstance(x, list) else None)
    df = df[['fecha', 'product_id_id', 'product_uom_qty', 'loc_id', 'loc_dest_id']]
    return df


def _expandir_movimientos_a_deltas(df_moves: pd.DataFrame, loc_to_bodega: dict) -> pd.DataFrame:
    """Para cada move, genera filas de delta:
    - Si loc_dest_id es relevante: +qty para esa bodega
    - Si loc_id es relevante: -qty para esa bodega
    Movimientos internos entre 2 sublocaciones de la MISMA bodega logica se cancelan.
    """
    if df_moves.empty:
        return pd.DataFrame(columns=['fecha', 'sku', 'bodega', 'delta'])

    deltas = []
    for _, r in df_moves.iterrows():
        sku = r['product_id_id']
        qty = r['product_uom_qty'] or 0
        if qty == 0 or sku is None:
            continue
        b_origen = loc_to_bodega.get(r['loc_id'])
        b_destino = loc_to_bodega.get(r['loc_dest_id'])
        # Mismo bodega logica: net 0
        if b_origen == b_destino:
            continue
        if b_destino:
            deltas.append({'fecha': r['fecha'], 'sku': sku, 'bodega': b_destino, 'delta': qty})
        if b_origen:
            deltas.append({'fecha': r['fecha'], 'sku': sku, 'bodega': b_origen, 'delta': -qty})

    df = pd.DataFrame(deltas)
    if df.empty:
        return pd.DataFrame(columns=['fecha', 'sku', 'bodega', 'delta'])
    return df.groupby(['fecha', 'sku', 'bodega'], as_index=False)['delta'].sum()


def _reconstruir_saldo_diario(quant_hoy: pd.DataFrame, deltas_diarios: pd.DataFrame,
                                loc_to_bodega: dict, fecha_hoy: datetime,
                                fecha_desde_str: str) -> pd.DataFrame:
    """Reconstruye saldo diario backward y cubre TODO el rango fecha_desde -> fecha_hoy.

    Approach vectorizado:
    1. saldo[hoy] = quant_actual por (sku, bodega)
    2. Pivot deltas a (fecha, sku, bodega) y rellenar fechas faltantes con 0
    3. saldo[d] = saldo[hoy] - sum(delta[d+1..hoy])
       (porque deltas posteriores a d se aplicaron sobre el saldo[d] para llegar a saldo[hoy])
    """
    print("[5] Reconstruyendo saldo diario backward (vectorizado)...", flush=True)

    quant_hoy = quant_hoy.copy()
    quant_hoy['bodega'] = quant_hoy['location_id_id'].map(loc_to_bodega)
    quant_hoy = quant_hoy.dropna(subset=['bodega'])
    saldo_hoy = quant_hoy.groupby(['product_id_id', 'bodega'], as_index=False)['quantity'].sum()
    saldo_hoy.columns = ['sku', 'bodega', 'cantidad_hoy']

    # Universo de combinaciones (sku, bodega) que existen hoy O alguna vez tuvieron movimiento
    combo_hoy = set(zip(saldo_hoy['sku'], saldo_hoy['bodega']))
    combo_mov = set(zip(deltas_diarios['sku'], deltas_diarios['bodega'])) if not deltas_diarios.empty else set()
    todas_combos = combo_hoy | combo_mov
    print(f"   Combinaciones (sku, bodega) totales: {len(todas_combos):,}", flush=True)

    # Construir saldo hoy completo (incluyendo combos que aparecen solo en deltas)
    saldo_hoy_dict = dict(zip(zip(saldo_hoy['sku'], saldo_hoy['bodega']), saldo_hoy['cantidad_hoy']))

    # Rango fechas
    fecha_desde = pd.Timestamp(fecha_desde_str)
    fecha_hasta = pd.Timestamp(fecha_hoy.date())
    fechas_rango = pd.date_range(fecha_desde, fecha_hasta, freq='D')

    # Pivot deltas (fecha x combo)
    if not deltas_diarios.empty:
        deltas_diarios = deltas_diarios.copy()
        deltas_diarios['fecha'] = pd.to_datetime(deltas_diarios['fecha'])

    # Construir DF de salida iterando por combo (mas eficiente para volumen alto)
    print(f"   {len(todas_combos):,} combinaciones x {len(fechas_rango)} dias (vectorizado matricial)...", flush=True)

    # Construir matriz pivot: index=fecha, columns=(sku,bodega), values=delta
    if deltas_diarios.empty:
        # Caso sin deltas: saldo constante = cant_hoy para todos los dias
        out = []
        for (sku, bodega), c in saldo_hoy_dict.items():
            out.append(pd.DataFrame({'fecha': fechas_rango, 'sku': sku, 'bodega': bodega, 'cantidad': c}))
        return pd.concat(out, ignore_index=True)

    deltas_diarios['combo'] = deltas_diarios['sku'].astype(str) + '|' + deltas_diarios['bodega'].astype(str)
    pivot = deltas_diarios.pivot_table(
        index='fecha', columns='combo', values='delta', aggfunc='sum', fill_value=0.0,
    )
    # Asegurar que todas las fechas del rango esten presentes
    pivot = pivot.reindex(fechas_rango, fill_value=0.0)

    # Vector de saldo hoy para cada combo presente en pivot
    cant_hoy_vec = pd.Series({
        f'{sku}|{bodega}': saldo_hoy_dict.get((sku, bodega), 0.0)
        for sku, bodega in todas_combos
    })
    # Sincronizar columnas: todos los combos
    cols_all = sorted(set(pivot.columns) | set(cant_hoy_vec.index))
    pivot = pivot.reindex(columns=cols_all, fill_value=0.0)
    cant_hoy_vec = cant_hoy_vec.reindex(cols_all, fill_value=0.0)

    # delta_post[d] = sum(delta[d+1..fin]) por columna
    # cumsum reversa por columna, luego shift(-1)
    cumsum_rev = pivot[::-1].cumsum()[::-1]
    delta_post = cumsum_rev.shift(-1, fill_value=0.0)

    # saldo[d] = cant_hoy - delta_post[d]
    saldo_matriz = cant_hoy_vec.values[None, :] - delta_post.values

    # Convertir matriz de vuelta a long-form (fecha, sku, bodega, cantidad)
    print("   Convirtiendo matriz a long-form...", flush=True)
    df_long = pd.DataFrame(saldo_matriz, index=fechas_rango, columns=cols_all)
    df_long = df_long.stack().reset_index()
    df_long.columns = ['fecha', 'combo', 'cantidad']
    df_long[['sku', 'bodega']] = df_long['combo'].str.split('|', n=1, expand=True)
    df_long['sku'] = df_long['sku'].astype(int)
    df_long = df_long[['fecha', 'sku', 'bodega', 'cantidad']]
    df_long['cantidad'] = df_long['cantidad'].round(2)

    return df_long


def main():
    print(f"=== Extraccion stock historico — {datetime.now()} ===", flush=True)
    print(f"Periodo: {FECHA_DESDE} a {FECHA_HASTA}\n", flush=True)

    odoo = _conectar_odoo()
    loc_to_bodega, location_ids = _obtener_locations_relevantes(odoo)

    quant_hoy = _snapshot_quant_actual(odoo, location_ids)

    # Iterar mes a mes desde FECHA_DESDE hasta hoy
    desde_dt = datetime.strptime(FECHA_DESDE, '%Y-%m-%d')
    hasta_dt = datetime.now()
    año_mes_actual = desde_dt.replace(day=1)
    todos_deltas = []

    print(f"\n[3] Extrayendo movimientos mes a mes...", flush=True)
    while año_mes_actual <= hasta_dt:
        mes_str = año_mes_actual.strftime('%Y-%m')
        print(f"   [{mes_str}]", flush=True)
        df_mes = _extraer_movimientos_mes(odoo, location_ids, mes_str)
        if not df_mes.empty:
            df_deltas = _expandir_movimientos_a_deltas(df_mes, loc_to_bodega)
            todos_deltas.append(df_deltas)
            print(f"      {len(df_mes):,} moves -> {len(df_deltas):,} deltas (sku-bodega-dia)", flush=True)
        # Avanzar al siguiente mes
        if año_mes_actual.month == 12:
            año_mes_actual = año_mes_actual.replace(year=año_mes_actual.year + 1, month=1)
        else:
            año_mes_actual = año_mes_actual.replace(month=año_mes_actual.month + 1)

    if not todos_deltas:
        print("[ERROR] Sin deltas extraidos")
        sys.exit(1)

    print("\n[4] Consolidando deltas...", flush=True)
    df_deltas_total = pd.concat(todos_deltas, ignore_index=True)
    df_deltas_total = df_deltas_total.groupby(['fecha', 'sku', 'bodega'], as_index=False)['delta'].sum()
    print(f"   Total deltas: {len(df_deltas_total):,}", flush=True)

    df_diario = _reconstruir_saldo_diario(quant_hoy, df_deltas_total, loc_to_bodega, hasta_dt, FECHA_DESDE)

    print(f"\n[6] Guardando parquet...", flush=True)
    df_diario['fecha'] = pd.to_datetime(df_diario['fecha'])
    df_diario['cantidad'] = df_diario['cantidad'].astype('float32')
    df_diario['sku'] = df_diario['sku'].astype('int32')
    df_diario['bodega'] = df_diario['bodega'].astype('category')

    out_path = OUTPUT_DIR / 'stock_diario.parquet'
    df_diario.to_parquet(out_path, compression='zstd', compression_level=9, index=False)
    print(f"   {out_path}: {len(df_diario):,} filas, {out_path.stat().st_size/1024/1024:.1f} MB", flush=True)

    meta = {
        'generado_en': datetime.now().isoformat(),
        'fecha_desde': FECHA_DESDE,
        'fecha_hasta': FECHA_HASTA,
        'bodegas': list(BODEGAS.values()),
        'total_filas': len(df_diario),
        'total_skus': df_diario['sku'].nunique(),
        'total_bodegas': df_diario['bodega'].nunique(),
        'rango_fechas': [str(df_diario['fecha'].min().date()), str(df_diario['fecha'].max().date())],
    }
    with open(OUTPUT_DIR / 'metadata.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, default=str)

    print(f"\n[OK] Stock historico generado")
    print(f"  SKUs unicos: {meta['total_skus']:,}")
    print(f"  Bodegas: {meta['total_bodegas']}")
    print(f"  Rango: {meta['rango_fechas'][0]} a {meta['rango_fechas'][1]}")


if __name__ == '__main__':
    main()
