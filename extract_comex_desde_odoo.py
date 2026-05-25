"""Extrae embarques en tránsito desde Odoo (purchase.order de Topwill).

Reemplaza el Sheet de Martín como fuente principal de transito.parquet.
Cruza con product.product para traer nombre canónico, categoría y marca.

Filtros:
  - partner_id = 1664 (Shenzhen Topwill Electronic Co. Ltd)
  - partner_ref LIKE '26TP%' (embarques del flujo agente COMEX)
  - state in (draft, sent, purchase)  ← excluye cancel y done

Output:
  - data/comex/transito.parquet
  - data/comex/transito_resumen.json
"""
import json
import os
import re
import sys
import time
import xmlrpc.client
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / 'data' / 'comex'
OUT_DIR.mkdir(parents=True, exist_ok=True)

PARTNER_TOPWILL = 1664


def _cargar_env():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _conectar(max_retries: int = 4):
    _cargar_env()
    url = os.environ.get('ODOO_URL', 'https://unionxb2b.odoo.com')
    db = os.environ.get('ODOO_DB', 'bmya-innovatek-sh-prd-6981800')
    user = os.environ.get('ODOO_USER') or 'andres@grupoeter.cl'
    pwd = os.environ.get('ODOO_API_KEY') or os.environ.get('ANDRES_ODOO_PASSWORD')
    last = None
    for a in range(1, max_retries + 1):
        try:
            common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True)
            uid = common.authenticate(db, user, pwd, {})
            models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
            return uid, models, db, pwd
        except xmlrpc.client.ProtocolError as e:
            last = e
            if a < max_retries:
                wait = 5 * (2 ** (a - 1))
                print(f"  [retry] Odoo {e.errcode} attempt {a}/{max_retries}, esperando {wait}s...")
                time.sleep(wait)
    raise last


def _split_categoria(cat_label: str) -> dict:
    """'Hogar / Basureros de cocina' → {macro: Hogar, padre: Basureros de cocina, hijo: ''}.
    Para 3 niveles: 'A / B / C' → macro=A, padre=B, hijo=C.
    """
    if not cat_label:
        return {'categoria_macro': '', 'categoria_padre': '', 'categoria_hijo': ''}
    partes = [p.strip() for p in cat_label.split(' / ')]
    if len(partes) == 1:
        return {'categoria_macro': partes[0], 'categoria_padre': '', 'categoria_hijo': ''}
    if len(partes) == 2:
        return {'categoria_macro': partes[0], 'categoria_padre': partes[1], 'categoria_hijo': ''}
    return {'categoria_macro': partes[0], 'categoria_padre': partes[1], 'categoria_hijo': ' / '.join(partes[2:])}


def _parse_pi(pi_full: str) -> dict:
    """26TP0330 → {pi_anio: 2026, pi_codigo: TP0330, pi_full: 26TP0330PI}."""
    m = re.match(r'(\d{2})(TP\d{4})', pi_full or '')
    if not m:
        return {'pi_anio': None, 'pi_codigo': '', 'pi_full': pi_full or ''}
    anio = 2000 + int(m.group(1))
    codigo = m.group(2)
    return {'pi_anio': anio, 'pi_codigo': codigo, 'pi_full': f'{anio % 100:02d}{codigo}PI'}


def extraer() -> pd.DataFrame:
    uid, models, db, pwd = _conectar()
    print(f"[1] Buscando PO Topwill EN TRÁNSITO (receipt_status != 'full')...")
    pos = models.execute_kw(db, uid, pwd, 'purchase.order', 'search_read',
        [[('partner_id', '=', PARTNER_TOPWILL),
          ('partner_ref', 'like', '26TP%'),
          ('state', 'in', ['draft', 'sent', 'purchase']),
          ('receipt_status', 'not in', ['full'])]],
        {'fields': ['id', 'name', 'partner_ref', 'state', 'date_planned',
                     'date_order', 'effective_date', 'receipt_status',
                     'amount_total', 'order_line']})
    print(f"   {len(pos)} PO Topwill en tránsito (excluidos recibidos full)")
    if not pos:
        return pd.DataFrame()

    # Bulk read de todas las order_lines
    all_line_ids = [lid for p in pos for lid in p['order_line']]
    print(f"[2] Leyendo {len(all_line_ids)} líneas de las PO...")
    lines = models.execute_kw(db, uid, pwd, 'purchase.order.line', 'read',
        [all_line_ids],
        {'fields': ['id', 'order_id', 'product_id', 'name', 'product_qty',
                     'price_unit', 'date_planned']})

    # Bulk read product.product
    product_ids = list({l['product_id'][0] for l in lines if l.get('product_id')})
    print(f"[3] Leyendo metadata de {len(product_ids)} productos...")
    productos = models.execute_kw(db, uid, pwd, 'product.product', 'read',
        [product_ids],
        {'fields': ['id', 'default_code', 'name', 'categ_id', 'brand_id', 'standard_price']})
    prod_map = {p['id']: p for p in productos}

    # Map order_id → PO
    po_map = {p['id']: p for p in pos}

    # Construir DataFrame
    print(f"[4] Construyendo DataFrame...")
    filas = []
    for line in lines:
        po = po_map.get(line['order_id'][0]) if line.get('order_id') else None
        if not po:
            continue
        prod = prod_map.get(line['product_id'][0]) if line.get('product_id') else None
        sku = (prod or {}).get('default_code') or ''
        nombre = (prod or {}).get('name') or line.get('name') or ''
        categ_label = prod['categ_id'][1] if prod and prod.get('categ_id') else ''
        marca = prod['brand_id'][1] if prod and prod.get('brand_id') else ''
        cat = _split_categoria(categ_label)

        pi_full_raw = po.get('partner_ref') or ''
        pi_info = _parse_pi(pi_full_raw)

        eta = line.get('date_planned') or po.get('date_planned')
        fecha_embarque = po.get('date_order')

        # Clasificar status según receipt_status y state
        rs = po.get('receipt_status') or ''
        if rs == 'partial':
            status = 'TRANSITO_PARCIAL'
        elif po['state'] in ('draft', 'sent'):
            status = 'TRANSITO_RFQ'  # PO sin confirmar (pre-Steven)
        else:
            status = 'TRANSITO'  # purchase confirmada, sin recibir

        filas.append({
            'flag': '',
            'sku': sku,
            'producto': nombre,
            'pi': pi_info['pi_full'],
            'status': status,
            'transporte': '',  # No disponible en Odoo
            'nro_pedido': po['name'],  # P00677
            'cantidad': float(line.get('product_qty') or 0),
            'costo_unitario_usd': None,
            'gift_box_envio': None,
            'costo_ingreso_clp': float(line.get('price_unit') or 0) * float(line.get('product_qty') or 0),
            'costo_ingreso_clp_unit': float(line.get('price_unit') or 0),
            'fecha_embarque': fecha_embarque,
            'fecha_eta_chile': eta,
            'fecha_eta_bodega': eta,
            'odoo': True,
            'costo_total_usd': None,
            'pi_anio': pi_info['pi_anio'],
            'pi_codigo': pi_info['pi_codigo'],
            'pi_full': pi_info['pi_full'],
            'categoria_macro': cat['categoria_macro'],
            'categoria_padre': cat['categoria_padre'],
            'categoria_hijo': cat['categoria_hijo'],
            'marca': marca,
            'po_id': po['id'],
            'po_name': po['name'],
            'po_state': po['state'],
            'fuente': 'odoo',
            'fuente_costo': 'odoo',
        })

    df = pd.DataFrame(filas)
    for c in ('fecha_embarque', 'fecha_eta_chile', 'fecha_eta_bodega'):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors='coerce')
    return df


def main():
    print(f"=== Extract COMEX desde Odoo — {datetime.now()} ===\n", flush=True)
    df = extraer()

    if df.empty:
        print("[ERROR] Sin PO Topwill activas")
        return 1

    print(f"\n[5] Stats:")
    print(f"   Filas: {len(df)}")
    print(f"   PIs únicos: {df['pi'].nunique()}")
    print(f"   SKUs únicos: {df['sku'].nunique()}")
    print(f"   Unidades total: {df['cantidad'].sum():,.0f}")
    print(f"   CLP total internado: ${df['costo_ingreso_clp'].sum()/1e6:.1f}MM")
    print()
    print(f"   PIs incluidos:")
    pi_agg = df.groupby('pi', dropna=False).agg(
        nro=('nro_pedido', 'first'),
        state=('po_state', 'first'),
        skus=('sku', 'nunique'),
        unid=('cantidad', 'sum'),
        clp=('costo_ingreso_clp', 'sum'),
        eta=('fecha_eta_bodega', 'first'),
    ).sort_values('eta')
    for pi, r in pi_agg.iterrows():
        eta_s = r['eta'].strftime('%Y-%m-%d') if pd.notna(r['eta']) else '-'
        print(f"     {pi:<14} {r['nro']:<8} {r['state']:<10} {r['skus']:>3} skus  {r['unid']:>7,.0f} unid  ${r['clp']/1e6:>6.1f}MM  ETA {eta_s}")

    # Guardar
    out_p = OUT_DIR / 'transito.parquet'
    df.to_parquet(out_p, compression='zstd', compression_level=9, index=False)
    print(f"\n[OK] Guardado: {out_p} ({len(df)} filas)")

    # Resumen JSON
    resumen = {
        'generado_en': datetime.now().isoformat(),
        'fuente': 'odoo',
        'filtros': {'partner_id': PARTNER_TOPWILL, 'partner_ref_like': '26TP%',
                     'state_in': ['draft', 'sent', 'purchase']},
        'total_filas': len(df),
        'total_pis': int(df['pi'].nunique()),
        'total_skus': int(df['sku'].nunique()),
        'total_unidades': float(df['cantidad'].sum()),
        'total_clp_internado': float(df['costo_ingreso_clp'].sum()),
        'eta_proxima': df['fecha_eta_bodega'].min().isoformat() if df['fecha_eta_bodega'].notna().any() else None,
        'eta_lejana': df['fecha_eta_bodega'].max().isoformat() if df['fecha_eta_bodega'].notna().any() else None,
    }
    with open(OUT_DIR / 'transito_resumen.json', 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2, default=str)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
