#!/usr/bin/env python3
"""
Valida PIs del sheet COMEX contra ingresos reales en Odoo.

Para cada PI en data/comex/transito.parquet:
  - Busca movimientos stock.move (state=done) de los SKUs de esa PI
  - Con destino en bodegas relevantes (CA1, BFML, BFFa, BFP, BFR, BFW)
  - Posteriores a fecha_embarque del PI
  - Excluye transfers internos (location_id en mismas bodegas)
  - Suma cantidad recibida por SKU
  - Compara contra cantidad esperada del PI

Estados resultantes:
  - 🟢 INGRESADO: >=95% de unidades del PI ya registradas en Odoo
  - 🟡 PARCIAL: 30-95% recibido
  - 🔴 PENDIENTE: <30% recibido (PI realmente en tránsito)
  - ⚪ SIN_INFO: no se encontraron movimientos (SKUs no matchean o sin recepcion aun)

Output:
- data/comex/validacion_odoo.parquet (sku, pi, esperado, recibido, ratio, status)
- data/comex/validacion_odoo_resumen.json (estado por PI)
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.config import Config

COMEX_PARQUET = PROJECT_ROOT / 'data' / 'comex' / 'transito.parquet'
OUT_DIR = PROJECT_ROOT / 'data' / 'comex'

# Warehouse IDs (del diag previo: project_bodegas_unionx)
WAREHOUSES_RECEPCION = [1, 17, 18, 19, 20, 56]  # CA1, BFP, BFFa, BFR, BFML, BFW


def main():
    pwd = os.environ.get('ANDRES_ODOO_PASSWORD')
    if not pwd:
        print("[ERROR] ANDRES_ODOO_PASSWORD no seteado")
        sys.exit(1)

    if not COMEX_PARQUET.exists():
        print(f"[ERROR] {COMEX_PARQUET} no existe. Correr extract_comex_transito.py primero")
        sys.exit(1)

    print(f"=== Validacion COMEX vs Odoo — {datetime.now()} ===\n", flush=True)

    odoo = OdooClient(url=Config.ODOO_URL, db=Config.ODOO_DB,
                       username=Config.ODOO_USER, password=pwd, max_retries=3)
    print(f"[1] UID: {odoo.authenticate()}", flush=True)

    df_t = pd.read_parquet(COMEX_PARQUET)
    df_t['fecha_embarque'] = pd.to_datetime(df_t['fecha_embarque'], errors='coerce')
    print(f"[2] PIs a validar: {df_t['pi'].nunique()} ({len(df_t)} filas)", flush=True)

    # Obtener locations internal de las bodegas relevantes
    print(f"[3] Cargando locations internal de bodegas relevantes...", flush=True)
    locs = odoo.search_read('stock.location',
                              [('warehouse_id', 'in', WAREHOUSES_RECEPCION),
                               ('usage', '=', 'internal')],
                              ['id', 'warehouse_id'], limit=5000)
    dest_ids = [loc['id'] for loc in locs]
    print(f"    Locations destino: {len(dest_ids)}", flush=True)

    # Map sku -> product_id (default_code o barcode)
    print(f"[4] Mapeando SKUs a product_id en Odoo...", flush=True)
    skus_unicos = df_t['sku'].dropna().astype(str).unique().tolist()
    productos = odoo.search_read('product.product',
                                   [('default_code', 'in', skus_unicos)],
                                   ['id', 'default_code', 'barcode'], limit=5000)
    sku_to_id = {p['default_code']: p['id'] for p in productos if p.get('default_code')}

    # Reintentar para SKUs no matched con barcode
    no_match = [s for s in skus_unicos if s not in sku_to_id]
    if no_match:
        bcodes = odoo.search_read('product.product',
                                    [('barcode', 'in', no_match)],
                                    ['id', 'default_code', 'barcode'], limit=5000)
        for p in bcodes:
            bc = p.get('barcode')
            if bc and bc in no_match:
                sku_to_id[bc] = p['id']

    print(f"    SKUs mapeados: {len(sku_to_id)}/{len(skus_unicos)} "
          f"(no encontrados: {len(skus_unicos) - len(sku_to_id)})", flush=True)

    # Procesar PI por PI
    print(f"\n[5] Cruzando con stock.move por PI...", flush=True)
    resultados = []
    resumen_pi = []

    for pi, df_pi in df_t.groupby('pi', dropna=False):
        fecha_embarque = pd.Timestamp(df_pi['fecha_embarque'].min())
        fecha_eta_bodega_val = df_pi['fecha_eta_bodega'].min() if 'fecha_eta_bodega' in df_pi.columns else None
        fecha_eta_bodega = pd.Timestamp(fecha_eta_bodega_val) if pd.notna(fecha_eta_bodega_val) else pd.NaT
        if pd.isna(fecha_embarque):
            fecha_embarque = pd.Timestamp('2026-01-01')

        # Ventana de fechas centrada en ETA bodega (evita capturar movimientos de OTROS PIs).
        # Si no hay ETA bodega, usar fecha_embarque + 50d como estimacion.
        if pd.notna(fecha_eta_bodega):
            ventana_desde = fecha_eta_bodega - pd.Timedelta(days=14)
            ventana_hasta = fecha_eta_bodega + pd.Timedelta(days=60)
        else:
            ventana_desde = fecha_embarque + pd.Timedelta(days=35)
            ventana_hasta = fecha_embarque + pd.Timedelta(days=110)

        # Limite superior: no buscar movimientos en el futuro
        hoy_ts = pd.Timestamp(datetime.now())
        ventana_hasta_real = ventana_hasta if ventana_hasta < hoy_ts else hoy_ts

        skus_pi = df_pi['sku'].dropna().astype(str).unique().tolist()
        product_ids_pi = [sku_to_id[s] for s in skus_pi if s in sku_to_id]

        recibido_por_prod = defaultdict(float)
        # Solo buscar movimientos si la ventana ya comenzo (sino la PI todavia no puede haber llegado)
        if product_ids_pi and ventana_desde <= hoy_ts:
            domain = [
                ('product_id', 'in', product_ids_pi),
                ('state', '=', 'done'),
                ('date', '>=', ventana_desde.strftime('%Y-%m-%d 00:00:00')),
                ('date', '<=', ventana_hasta_real.strftime('%Y-%m-%d 23:59:59')),
                ('location_dest_id', 'in', dest_ids),
                ('product_uom_qty', '>', 0),
            ]
            try:
                moves = odoo.search_read('stock.move', domain,
                                           ['product_id', 'product_uom_qty', 'date',
                                            'location_id', 'location_dest_id'], limit=5000)
            except Exception as e:
                print(f"    [warn] {pi}: error stock.move: {str(e)[:80]}", flush=True)
                moves = []

            # Excluir transfers internos (origen ya en dest_ids = movimiento interno entre bodegas)
            for m in moves:
                loc_origen = m.get('location_id')
                loc_origen_id = loc_origen[0] if isinstance(loc_origen, list) else loc_origen
                if loc_origen_id in dest_ids:
                    continue  # transfer interno, no ingreso
                prod = m.get('product_id')
                prod_id = prod[0] if isinstance(prod, list) else prod
                qty = float(m.get('product_uom_qty', 0))
                recibido_por_prod[prod_id] += qty

        # Comparar SKU por SKU
        for _, row in df_pi.iterrows():
            sku = str(row['sku']) if pd.notna(row['sku']) else None
            esperado = float(row['cantidad']) if pd.notna(row['cantidad']) else 0
            prod_id = sku_to_id.get(sku) if sku else None
            recibido = recibido_por_prod.get(prod_id, 0) if prod_id else 0
            ratio = (recibido / esperado) if esperado > 0 else 0

            if not prod_id:
                status = '⚪ SIN_INFO'
            elif ratio >= 0.95:
                status = '🟢 INGRESADO'
            elif ratio >= 0.30:
                status = '🟡 PARCIAL'
            else:
                status = '🔴 PENDIENTE'

            resultados.append({
                'pi': pi,
                'sku': sku,
                'producto': row.get('producto', ''),
                'cantidad_esperada': esperado,
                'cantidad_recibida_odoo': recibido,
                'ratio_recibido': round(ratio, 3),
                'status_validacion': status,
                'odoo_product_id': prod_id,
                'fecha_embarque': fecha_embarque.date() if pd.notna(fecha_embarque) else None,
                'fecha_eta_bodega': row.get('fecha_eta_bodega'),
            })

        # Resumen por PI
        df_res_pi = pd.DataFrame([r for r in resultados if r['pi'] == pi])
        if df_res_pi.empty:
            continue
        total_esperado = float(df_res_pi['cantidad_esperada'].sum())
        total_recibido = float(df_res_pi['cantidad_recibida_odoo'].sum())
        ratio_pi = (total_recibido / total_esperado) if total_esperado > 0 else 0

        if ratio_pi >= 0.95:
            status_pi = '🟢 INGRESADO'
        elif ratio_pi >= 0.30:
            status_pi = '🟡 PARCIAL'
        elif ratio_pi >= 0.05:
            status_pi = '🟡 INICIANDO'
        else:
            status_pi = '🔴 PENDIENTE'

        resumen_pi.append({
            'pi': pi,
            'fecha_embarque': str(fecha_embarque.date()) if pd.notna(fecha_embarque) else None,
            'skus_total': len(df_res_pi),
            'skus_ingresados': int((df_res_pi['status_validacion'] == '🟢 INGRESADO').sum()),
            'skus_parciales': int((df_res_pi['status_validacion'] == '🟡 PARCIAL').sum()),
            'skus_pendientes': int((df_res_pi['status_validacion'] == '🔴 PENDIENTE').sum()),
            'skus_sin_info': int((df_res_pi['status_validacion'] == '⚪ SIN_INFO').sum()),
            'unidades_esperadas': total_esperado,
            'unidades_recibidas': total_recibido,
            'ratio_pi': round(ratio_pi, 3),
            'status_pi': status_pi,
        })

        print(f"    {pi} | esperado {total_esperado:>7,.0f} unid | recibido {total_recibido:>7,.0f} | "
              f"{ratio_pi*100:>5.1f}% | {status_pi}", flush=True)

    # Persistir
    df_res = pd.DataFrame(resultados)
    out_path = OUT_DIR / 'validacion_odoo.parquet'
    df_res.to_parquet(out_path, compression='zstd', compression_level=9, index=False)
    print(f"\n[6] {out_path.name}: {len(df_res):,} filas", flush=True)

    resumen_json = {
        'generado_en': datetime.now().isoformat(),
        'total_pis': len(resumen_pi),
        'pis_ingresados': sum(1 for r in resumen_pi if r['status_pi'] == '🟢 INGRESADO'),
        'pis_parciales': sum(1 for r in resumen_pi if r['status_pi'] in ('🟡 PARCIAL', '🟡 INICIANDO')),
        'pis_pendientes': sum(1 for r in resumen_pi if r['status_pi'] == '🔴 PENDIENTE'),
        'sku_no_match_odoo': len(skus_unicos) - len(sku_to_id),
        'por_pi': resumen_pi,
    }
    with open(OUT_DIR / 'validacion_odoo_resumen.json', 'w', encoding='utf-8') as f:
        json.dump(resumen_json, f, indent=2, default=str)

    print(f"\n[OK] Validacion completa")
    print(f"  PIs ingresados (drive desactualizado): {resumen_json['pis_ingresados']}")
    print(f"  PIs parciales: {resumen_json['pis_parciales']}")
    print(f"  PIs realmente pendientes: {resumen_json['pis_pendientes']}")


if __name__ == '__main__':
    main()
