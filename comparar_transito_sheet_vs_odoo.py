"""Compara transito.parquet (Odoo, fuente principal) vs transito_sheet.parquet
(Sheet Martín, contraste). Detecta:

  1. PIs en Sheet pero NO en Odoo  → ALERTA (embarque sin trackear en Odoo)
  2. PIs en Odoo pero NO en Sheet  → INFO (agente generó PO sin reflejo en Sheet)
  3. Cantidad por SKU difiere      → WARN

Output: data/comex/transito_alertas.json
"""
import json
import os
import sys
import xmlrpc.client
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent
COMEX = PROJECT_ROOT / 'data' / 'comex'
P_ODOO = COMEX / 'transito.parquet'
P_SHEET = COMEX / 'transito_sheet.parquet'
OUT = COMEX / 'transito_alertas.json'
PARTNER_TOPWILL = 1664


def _conectar_odoo():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    url = os.environ.get('ODOO_URL', 'https://unionxb2b.odoo.com')
    db = os.environ.get('ODOO_DB', 'bmya-innovatek-sh-prd-6981800')
    user = os.environ.get('ODOO_USER') or 'andres@grupoeter.cl'
    pwd = os.environ.get('ODOO_API_KEY') or os.environ.get('ANDRES_ODOO_PASSWORD')
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True)
    uid = common.authenticate(db, user, pwd, {})
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
    return uid, models, db, pwd


def _clasificar_pi_huerfano(pi: str, uid, models, db, pwd) -> tuple[str, str]:
    """Para un PI que está en Sheet pero no en transito.parquet (Odoo activo),
    chequea si existe en Odoo con receipt_status='full' (ya recibido) o no existe.
    Devuelve (categoria, razon)."""
    refs_test = [pi, f'{pi}PI', pi.replace('PI', '')]
    pos = models.execute_kw(db, uid, pwd, 'purchase.order', 'search_read',
        [[('partner_id', '=', PARTNER_TOPWILL),
          ('partner_ref', 'in', refs_test)]],
        {'fields': ['name', 'state', 'receipt_status', 'effective_date']})
    if not pos:
        return ('SIN_PO_ODOO',
                'No existe PO en Odoo. Probable: pendiente flete Vicente / sin precosteo / requiere acción.')
    activos = [p for p in pos if p['state'] != 'cancel']
    if not activos:
        return ('TODAS_CANCELADAS',
                f'PO existieron pero todas canceladas: {[p["name"] for p in pos]}')
    full = [p for p in activos if (p.get('receipt_status') or '') == 'full']
    if full:
        nombres = ', '.join(p['name'] for p in full)
        eff = full[0].get('effective_date')
        return ('YA_RECIBIDO',
                f'Recibido en Odoo (PO {nombres}, arrival {eff}). Mover a "EN BODEGA" en Sheet de Martín.')
    return ('OTRO_ESTADO',
            f'PO existe pero no incluida en extract activo: {[(p["name"], p["state"], p.get("receipt_status")) for p in activos]}')


def _normalizar_pi(pi: str) -> str:
    """Normaliza '26TP0330PI' / '26TP0330' / '26tp0330' → '26TP0330'."""
    if not pi:
        return ''
    return str(pi).upper().replace('PI', '').strip()


def comparar() -> dict:
    if not P_ODOO.exists():
        return {'error': f'No existe {P_ODOO}'}
    if not P_SHEET.exists():
        return {'error': f'No existe {P_SHEET}', 'warning': 'Sin Sheet no hay comparación'}

    df_o = pd.read_parquet(P_ODOO)
    df_s = pd.read_parquet(P_SHEET)
    df_o['_pi'] = df_o['pi'].map(_normalizar_pi)
    df_s['_pi'] = df_s['pi'].map(_normalizar_pi)

    pis_odoo = set(df_o['_pi'].unique()) - {''}
    pis_sheet = set(df_s['_pi'].unique()) - {''}

    solo_sheet = sorted(pis_sheet - pis_odoo)
    solo_odoo = sorted(pis_odoo - pis_sheet)
    en_ambos = sorted(pis_sheet & pis_odoo)

    # Detalle PIs solo Sheet — clasificar consultando Odoo
    alertas_sheet_only = []
    if solo_sheet:
        try:
            uid, models, db, pwd = _conectar_odoo()
        except Exception as e:
            uid = None
            print(f"  [WARN] No pude conectar Odoo para clasificar huérfanos: {e}")
        for pi in solo_sheet:
            sub = df_s[df_s['_pi'] == pi]
            entrada = {
                'pi': pi,
                'skus': int(sub['sku'].nunique()),
                'unidades': float(sub['cantidad'].sum()) if 'cantidad' in sub.columns else 0,
                'eta': str(sub['fecha_eta_bodega'].min()) if 'fecha_eta_bodega' in sub.columns and sub['fecha_eta_bodega'].notna().any() else None,
            }
            if uid:
                categoria, razon = _clasificar_pi_huerfano(pi, uid, models, db, pwd)
                entrada['categoria'] = categoria
                entrada['razon'] = razon
            else:
                entrada['categoria'] = 'DESCONOCIDO'
                entrada['razon'] = 'No fue posible verificar en Odoo (sin conexión).'
            alertas_sheet_only.append(entrada)

    info_odoo_only = []
    for pi in solo_odoo:
        sub = df_o[df_o['_pi'] == pi]
        info_odoo_only.append({
            'pi': pi,
            'skus': int(sub['sku'].nunique()),
            'unidades': float(sub['cantidad'].sum()),
            'po_name': sub['po_name'].iloc[0] if 'po_name' in sub.columns else None,
            'eta': str(sub['fecha_eta_bodega'].min()) if sub['fecha_eta_bodega'].notna().any() else None,
            'razon': 'PO creada en Odoo por el agente pero aún no reflejada en Drive Sheet.',
        })

    # Comparar cantidades en PIs comunes
    warn_qty = []
    for pi in en_ambos:
        o = df_o[df_o['_pi'] == pi].groupby('sku')['cantidad'].sum()
        s = df_s[df_s['_pi'] == pi].groupby('sku')['cantidad'].sum()
        skus_comunes = set(o.index) & set(s.index)
        for sku in skus_comunes:
            q_o, q_s = float(o[sku]), float(s[sku])
            if abs(q_o - q_s) > 0.5:
                warn_qty.append({
                    'pi': pi, 'sku': sku,
                    'qty_odoo': q_o, 'qty_sheet': q_s, 'diff': q_o - q_s,
                })

    resumen = {
        'generado_en': datetime.now().isoformat(),
        'totales': {
            'pis_odoo': len(pis_odoo),
            'pis_sheet': len(pis_sheet),
            'pis_en_ambos': len(en_ambos),
            'pis_solo_sheet': len(solo_sheet),
            'pis_solo_odoo': len(solo_odoo),
            'skus_qty_difieren': len(warn_qty),
        },
        'alertas_sheet_pero_no_odoo': alertas_sheet_only,
        'info_odoo_pero_no_sheet': info_odoo_only,
        'warn_qty_difieren': warn_qty[:50],
    }
    return resumen


def main():
    res = comparar()
    print('=== Comparación Sheet vs Odoo ===')
    print(json.dumps(res, indent=2, default=str, ensure_ascii=False))
    OUT.write_text(json.dumps(res, indent=2, default=str, ensure_ascii=False), encoding='utf-8')
    print(f"\n[OK] Alertas guardadas: {OUT}")


if __name__ == '__main__':
    main()
