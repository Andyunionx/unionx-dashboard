#!/usr/bin/env python3
"""
Extractor COMEX dimensiones: cruza SKUs en tránsito con peso/volumen/packaging
desde Odoo (`product.product` + `product.template` + `product.packaging`).

Permite estimar m3 y pallets por embarque (PI) sin esperar la maestra de cajas
del proveedor. Cuando llegue la maestra de "unidades por caja master" se podrá
afinar el cálculo (override del packaging Odoo).

Input:
- data/comex/transito.parquet (debe existir, viene de extract_comex_transito.py)

Output:
- data/comex/dimensiones_skus.parquet  -> detalle por SKU con peso/vol unitario
                                          y total por línea de PI.
- data/comex/dimensiones_resumen.json  -> resumen por PI: peso, m3, pallets, cobertura.

Asunción pallet estándar: 1 pallet ≈ 1,2 m3 (1.0m × 1.2m × 1.0m apilable).
Container 20': ~28 m3 útiles. Container 40' HC: ~67 m3 útiles.
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

from app.core.odoo_client import OdooClient  # noqa: E402

COMEX_PARQUET = PROJECT_ROOT / 'data' / 'comex' / 'transito.parquet'
OUT_DIR = PROJECT_ROOT / 'data' / 'comex'
OUT_PARQUET = OUT_DIR / 'dimensiones_skus.parquet'
OUT_RESUMEN = OUT_DIR / 'dimensiones_resumen.json'

# === MAESTRA MANUAL DE CAJAS MASTER (override) ============================
# Cuando Andrés tenga el archivo maestro de unidades por caja master, se
# subscribe en una de estas dos rutas y este extractor lo usa como OVERRIDE
# por encima de Odoo `product.packaging`. Si no existe, se usa solo Odoo.
#
# Formato JSON:  data/comex/maestra_cajas_master.json
#   { "SKU-001": {"qty_caja_master": 24, "m3_caja_master": 0.045, "kg_caja_master": 12.5},
#     "SKU-002": {"qty_caja_master": 12, "m3_caja_master": 0.030, "kg_caja_master": 8.0} }
#
# Formato Excel: data/comex/maestra_cajas_master.xlsx
#   Hoja con columnas: SKU | qty_caja_master | m3_caja_master | kg_caja_master
#   (los campos m3 y kg son opcionales; si vienen, OVERRIDE peso/volumen Odoo)
MAESTRA_JSON = OUT_DIR / 'maestra_cajas_master.json'
MAESTRA_XLSX = OUT_DIR / 'maestra_cajas_master.xlsx'


def _cargar_maestra_manual() -> dict:
    """Lee la maestra manual de cajas master si existe. JSON tiene prioridad."""
    if MAESTRA_JSON.exists():
        try:
            with open(MAESTRA_JSON, encoding='utf-8') as f:
                data = json.load(f)
            # normalizar claves a string upper
            return {str(k).strip().upper(): v for k, v in data.items()}
        except Exception as e:
            print(f"  WARN: no se pudo leer {MAESTRA_JSON}: {e}", flush=True)
    if MAESTRA_XLSX.exists():
        try:
            df = pd.read_excel(MAESTRA_XLSX)
            df.columns = [c.strip() for c in df.columns]
            data = {}
            for _, r in df.iterrows():
                sku = str(r.get('SKU') or '').strip().upper()
                if not sku:
                    continue
                data[sku] = {
                    'qty_caja_master': float(r.get('qty_caja_master') or 0) or None,
                    'm3_caja_master': float(r.get('m3_caja_master') or 0) or None,
                    'kg_caja_master': float(r.get('kg_caja_master') or 0) or None,
                }
            return data
        except Exception as e:
            print(f"  WARN: no se pudo leer {MAESTRA_XLSX}: {e}", flush=True)
    return {}

ODOO_URL = os.environ.get('ODOO_URL', 'https://unionxb2b.odoo.com')
ODOO_DB = os.environ.get('ODOO_DB', 'bmya-innovatek-sh-prd-6981800')
ODOO_USER = (os.environ.get('OPS_ODOO_USER', '').strip()
             or os.environ.get('ANDRES_ODOO_USER', '').strip()
             or 'andres@grupoeter.cl')
ODOO_PWD = (os.environ.get('OPS_ODOO_PASSWORD', '').strip()
            or os.environ.get('ANDRES_ODOO_PASSWORD', '').strip())

# Equivalencias de pallet/container (logística estándar)
M3_POR_PALLET = 1.2          # 1 pallet ≈ 1,2 m3 apilable promedio
M3_CONTAINER_20 = 28         # útiles
M3_CONTAINER_40HC = 67       # útiles

# Umbral para detectar volumen unitario anómalo en Odoo. >1 m3 / unidad es
# enorme (≈ mesa de comedor empacada) -> casi seguro que el campo `volume`
# está cargado en cm3 u otra unidad por error de captura.
VOL_UNIT_ANOMALO_M3 = 1.0


def main():
    print(f"=== Extract COMEX dimensiones — {datetime.now().isoformat()} ===", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not COMEX_PARQUET.exists():
        print(f"[ERROR] {COMEX_PARQUET} no existe. Correr extract_comex_transito.py primero", flush=True)
        return 1

    if not ODOO_PWD:
        print("[ERROR] ANDRES_ODOO_PASSWORD/OPS_ODOO_PASSWORD no seteado", flush=True)
        return 1

    df_t = pd.read_parquet(COMEX_PARQUET)
    skus_unicos = sorted(df_t['sku'].dropna().astype(str).unique())
    print(f"[1] SKUs únicos en tránsito: {len(skus_unicos)}", flush=True)

    odoo = OdooClient(url=ODOO_URL, db=ODOO_DB, username=ODOO_USER, password=ODOO_PWD, max_retries=3)
    print(f"[2] Conectando Odoo {ODOO_URL} como {ODOO_USER}...", flush=True)
    odoo.authenticate()

    # Buscar productos por default_code (SKU). Algunos SKUs del sheet pueden ser
    # barcodes (ver casos 1615383407099) -> fallback por barcode.
    print(f"[3] Buscando product.product (default_code in SKUs)...", flush=True)
    productos = odoo.search_read(
        'product.product',
        [('default_code', 'in', skus_unicos)],
        ['id', 'default_code', 'barcode', 'name', 'product_tmpl_id', 'active'],
        limit=10000,
    )
    sku_to_prod = {p['default_code']: p for p in productos if p.get('default_code')}

    # Fallback por barcode para los SKUs que no matchearon
    no_match = [s for s in skus_unicos if s not in sku_to_prod]
    if no_match:
        print(f"    fallback barcode para {len(no_match)} SKUs sin default_code...", flush=True)
        productos_bc = odoo.search_read(
            'product.product',
            [('barcode', 'in', no_match)],
            ['id', 'default_code', 'barcode', 'name', 'product_tmpl_id', 'active'],
            limit=10000,
        )
        for p in productos_bc:
            if p.get('barcode'):
                sku_to_prod[p['barcode']] = p

    print(f"    OK matched {len(sku_to_prod)}/{len(skus_unicos)}", flush=True)

    # Templates con peso/volumen/packaging
    template_ids = sorted({p['product_tmpl_id'][0] for p in sku_to_prod.values()
                           if p.get('product_tmpl_id')})
    print(f"[4] Cargando product.template ({len(template_ids)} plantillas) -> weight, volume, packaging...", flush=True)
    templates = odoo.execute_in_batches(
        'product.template', template_ids,
        ['id', 'weight', 'volume', 'uom_id', 'packaging_ids'],
        batch_size=200,
    )
    tmpl_by_id = {t['id']: t for t in templates}

    # Packagings (master box)
    packaging_ids = sorted({pid for t in templates for pid in (t.get('packaging_ids') or [])})
    pack_by_tmpl = defaultdict(list)
    if packaging_ids:
        print(f"[5] Cargando product.packaging ({len(packaging_ids)})...", flush=True)
        packagings = odoo.execute_in_batches(
            'product.packaging', packaging_ids,
            ['id', 'name', 'product_tmpl_id', 'qty'],
            batch_size=200,
        )
        for pk in packagings:
            tmpl = pk.get('product_tmpl_id')
            if tmpl:
                pack_by_tmpl[tmpl[0]].append(pk)
    else:
        print(f"[5] Sin packagings cargados en Odoo (esperar maestra Andrés)", flush=True)

    # Cargar maestra manual de cajas master (override de Odoo si existe)
    maestra = _cargar_maestra_manual()
    if maestra:
        print(f"    Maestra manual cargada: {len(maestra)} SKUs override", flush=True)
    else:
        print(f"    Sin maestra manual (data/comex/maestra_cajas_master.json|xlsx) — usando solo Odoo", flush=True)

    # Construir dataset SKU-level
    print(f"[6] Construyendo dataset por línea de PI...", flush=True)
    rows = []
    for _, r in df_t.iterrows():
        sku = str(r.get('sku') or '').strip()
        cantidad = float(r.get('cantidad') or 0)
        prod = sku_to_prod.get(sku)
        if prod and prod.get('product_tmpl_id'):
            tmpl = tmpl_by_id.get(prod['product_tmpl_id'][0], {})
            peso_unit = float(tmpl.get('weight') or 0)
            vol_unit = float(tmpl.get('volume') or 0)
            packs = pack_by_tmpl.get(prod['product_tmpl_id'][0], [])
            qty_master = packs[0]['qty'] if packs else None
            nombre_pack = packs[0]['name'] if packs else ''
            tiene_match = True
        else:
            peso_unit = 0
            vol_unit = 0
            qty_master = None
            nombre_pack = ''
            tiene_match = False

        # Override con maestra manual si existe (prioridad sobre Odoo)
        override = maestra.get(sku.upper())
        usa_maestra = False
        if override:
            usa_maestra = True
            qty_m = override.get('qty_caja_master')
            m3_m = override.get('m3_caja_master')
            kg_m = override.get('kg_caja_master')
            if qty_m and qty_m > 0:
                qty_master = qty_m
                nombre_pack = nombre_pack or 'maestra manual'
            if m3_m and m3_m > 0 and qty_m and qty_m > 0:
                # Volumen unitario = m3 caja / unidades por caja
                vol_unit = m3_m / qty_m
            if kg_m and kg_m > 0 and qty_m and qty_m > 0:
                # Peso unitario = kg caja / unidades por caja
                peso_unit = kg_m / qty_m

        # Detectar volumen unitario anómalo (data quality Odoo)
        vol_anomalo = vol_unit > VOL_UNIT_ANOMALO_M3
        # Volumen "confiable" para sumar: 0 si es anómalo o no tiene
        vol_unit_clean = 0 if vol_anomalo else vol_unit

        rows.append({
            'pi': r.get('pi'),
            'sku': sku,
            'producto': r.get('producto'),
            'cantidad': cantidad,
            'transporte': r.get('transporte'),
            'fecha_embarque': r.get('fecha_embarque'),
            'fecha_eta_bodega': r.get('fecha_eta_bodega'),
            'peso_unit_kg': peso_unit,
            'volumen_unit_m3': vol_unit,
            'volumen_unit_m3_clean': vol_unit_clean,
            'peso_total_kg': peso_unit * cantidad,
            'volumen_total_m3': vol_unit * cantidad,
            'volumen_total_m3_clean': vol_unit_clean * cantidad,
            'qty_caja_master': qty_master,
            'packaging_nombre': nombre_pack,
            'cajas_master_estim': (cantidad / qty_master) if (qty_master and qty_master > 0) else None,
            'match_odoo': tiene_match,
            'usa_maestra_manual': usa_maestra,
            'tiene_peso': peso_unit > 0,
            'tiene_volumen': vol_unit > 0,
            'volumen_anomalo': vol_anomalo,
        })

    df_dim = pd.DataFrame(rows)
    df_dim.to_parquet(OUT_PARQUET, index=False)
    print(f"    parquet: {OUT_PARQUET} ({len(df_dim)} filas)", flush=True)

    # Resumen por PI
    print(f"[7] Calculando resumen por PI...", flush=True)
    pi_rows = []
    for pi, grp in df_dim.groupby('pi'):
        unidades = float(grp['cantidad'].sum())
        peso_kg = float(grp['peso_total_kg'].sum())
        vol_m3 = float(grp['volumen_total_m3'].sum())
        # Volumen confiable: descarta SKUs con volumen unitario anómalo
        vol_m3_clean = float(grp['volumen_total_m3_clean'].sum())
        pallets = (vol_m3_clean / M3_POR_PALLET) if vol_m3_clean > 0 else 0
        skus = int(grp['sku'].nunique())
        with_peso = int(grp['tiene_peso'].sum())
        with_vol = int(grp['tiene_volumen'].sum())
        skus_anomalos = int(grp['volumen_anomalo'].sum())
        with_match = int(grp['match_odoo'].sum())
        # transporte mayoritario
        transp = grp['transporte'].mode().iloc[0] if not grp['transporte'].mode().empty else ''
        eta_bod = grp['fecha_eta_bodega'].dropna().min()
        embarque = grp['fecha_embarque'].dropna().min()
        # Cantidad estimada de containers (con volumen confiable)
        cont_20 = vol_m3_clean / M3_CONTAINER_20 if vol_m3_clean > 0 else 0
        cont_40 = vol_m3_clean / M3_CONTAINER_40HC if vol_m3_clean > 0 else 0

        pi_rows.append({
            'pi': pi,
            'transporte': transp,
            'fecha_embarque': str(embarque)[:10] if pd.notna(embarque) else '',
            'fecha_eta_bodega': str(eta_bod)[:10] if pd.notna(eta_bod) else '',
            'skus_distintos': skus,
            'unidades_totales': unidades,
            'peso_total_kg': round(peso_kg, 1),
            'volumen_total_m3': round(vol_m3_clean, 2),
            'volumen_total_m3_raw': round(vol_m3, 2),  # incluye anómalos
            'pallets_estim': round(pallets, 1),
            'containers_20_estim': round(cont_20, 2),
            'containers_40hc_estim': round(cont_40, 2),
            'skus_con_match_odoo': with_match,
            'skus_con_peso': with_peso,
            'skus_con_volumen': with_vol,
            'skus_volumen_anomalo': skus_anomalos,
            'cobertura_peso_pct': round(with_peso / skus * 100, 1) if skus else 0,
            'cobertura_volumen_pct': round(with_vol / skus * 100, 1) if skus else 0,
        })

    pi_rows.sort(key=lambda x: x['fecha_eta_bodega'] or '9999-99-99')

    # Resumen global
    total_unidades = float(df_dim['cantidad'].sum())
    total_peso = float(df_dim['peso_total_kg'].sum())
    total_vol = float(df_dim['volumen_total_m3'].sum())
    total_vol_clean = float(df_dim['volumen_total_m3_clean'].sum())
    skus_total = int(df_dim['sku'].nunique())
    skus_match = int(df_dim[df_dim['match_odoo']]['sku'].nunique())
    skus_peso = int(df_dim[df_dim['tiene_peso']]['sku'].nunique())
    skus_vol = int(df_dim[df_dim['tiene_volumen']]['sku'].nunique())
    skus_vol_anomalo = int(df_dim[df_dim['volumen_anomalo']]['sku'].nunique())
    skus_maestra = int(df_dim[df_dim['usa_maestra_manual']]['sku'].nunique()) if 'usa_maestra_manual' in df_dim.columns else 0

    # Top SKUs anómalos (muestreables al user para que arregle Odoo)
    df_anom = df_dim[df_dim['volumen_anomalo']].drop_duplicates('sku')
    df_anom = df_anom.sort_values('volumen_unit_m3', ascending=False).head(20)
    skus_anomalos_top = df_anom[['sku', 'producto', 'volumen_unit_m3']].to_dict('records')

    resumen = {
        'generado_en': datetime.now().isoformat(),
        'fuente': f'{ODOO_URL} ({ODOO_DB})',
        'sku_input': len(skus_unicos),
        'sku_match_odoo': skus_match,
        'sku_con_peso': skus_peso,
        'sku_con_volumen': skus_vol,
        'sku_volumen_anomalo': skus_vol_anomalo,
        'sku_con_maestra_manual': skus_maestra,
        'cobertura_peso_pct': round(skus_peso / skus_total * 100, 1) if skus_total else 0,
        'cobertura_volumen_pct': round(skus_vol / skus_total * 100, 1) if skus_total else 0,
        'cobertura_volumen_confiable_pct': round((skus_vol - skus_vol_anomalo) / skus_total * 100, 1) if skus_total else 0,
        'unidades_totales': total_unidades,
        'peso_total_kg': round(total_peso, 1),
        'volumen_total_m3': round(total_vol_clean, 2),
        'volumen_total_m3_raw': round(total_vol, 2),
        'pallets_totales_estim': round(total_vol_clean / M3_POR_PALLET, 1) if total_vol_clean else 0,
        'asunciones': {
            'm3_por_pallet': M3_POR_PALLET,
            'm3_container_20': M3_CONTAINER_20,
            'm3_container_40hc': M3_CONTAINER_40HC,
            'umbral_volumen_anomalo_m3': VOL_UNIT_ANOMALO_M3,
        },
        'por_pi': pi_rows,
        'skus_sin_match': sorted([s for s in skus_unicos if s not in sku_to_prod]),
        'skus_volumen_anomalo_top': skus_anomalos_top,
    }

    with open(OUT_RESUMEN, 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=str)
    print(f"    resumen: {OUT_RESUMEN}", flush=True)

    # Print resumen
    print("\n=== RESUMEN COMEX DIMENSIONES ===")
    print(f"  PIs analizadas: {len(pi_rows)}")
    if skus_total:
        print(f"  SKUs únicos: {skus_total} (match Odoo: {skus_match} = {skus_match/skus_total*100:.0f}%)")
    print(f"  Cobertura peso: {resumen['cobertura_peso_pct']}%")
    print(f"  Cobertura volumen (cargado): {resumen['cobertura_volumen_pct']}%")
    print(f"  Cobertura volumen (confiable, sin anómalos): {resumen['cobertura_volumen_confiable_pct']}%")
    print(f"  SKUs con volumen anómalo (>1 m3/unid -> mal cargado en Odoo): {skus_vol_anomalo}")
    print(f"  Total: {total_unidades:,.0f} uds · {total_peso/1000:.1f} ton")
    print(f"  Volumen total CONFIABLE: {total_vol_clean:.1f} m3 (raw incluyendo anómalos: {total_vol:,.0f})")
    print(f"  Pallets totales estimados: {resumen['pallets_totales_estim']:.1f}")
    print(f"\nOK")
    return 0


if __name__ == '__main__':
    sys.exit(main())
