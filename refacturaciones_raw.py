# -*- coding: utf-8 -*-
"""Refacturaciones de meses cerrados fuera del RAW (Andrés 8-oct-2026).

Cuando una FACTURA de un mes ya cerrado se revierte completa con una NC y se emite una factura nueva al mismo
cliente (ej. Walmart OC 5550650057: la N/C 042532 revierte la FAC 102752 del 30-sep y la FAC 103364 la reemplaza
el 8-oct), en Odoo las dos se compensan. Pero la factura nueva no queda ligada al pedido y el RAW, que se arma
desde los pedidos, solo trae la NC: quedaba una devolución de −$116,5M que no existe. La venta ya está en el mes
del pedido original (histórico), así que la NC sale del mes en curso.

Solo actúa con FACTURAS (no boletas) revertidas completas, de antes del inicio del extract, y con factura nueva ya
emitida: misma referencia, o sin referencia y mismo monto (±$100; la 103364 difiere $17 por redondeo de líneas).
Las boletas revertidas y las NC sin reemplazo siguen siendo devoluciones. Si la factura original es del mismo mes
no se toca nada (la venta del pedido puede venir con el documento de la factura nueva).
Kill switch: DISABLE_REFACTURACION_FIX=1.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent


def _cliente():
    sys.path.insert(0, str(ROOT / 'finanzas-unionx' / 'backend'))
    from app.core.odoo_client import OdooClient
    from app.config import Config
    cfg = Config()
    return OdooClient(cfg.ODOO_URL, cfg.ODOO_DB, cfg.ODOO_USER, cfg.ODOO_PASSWORD)


def refacturadas(ncs: list[str], desde: str, client=None) -> dict:
    """{nombre NC: detalle} de las NC que revierten completa una factura anterior a `desde` ya refacturada."""
    if not ncs:
        return {}
    client = client or _cliente()
    nc = client.search_read('account.move', [['name', 'in', ncs], ['move_type', '=', 'out_refund'], ['state', '=', 'posted'],
                                             ['reversed_entry_id', '!=', False]],
                            ['name', 'amount_total', 'reversed_entry_id'])
    ids = list({n['reversed_entry_id'][0] for n in nc})
    orig = {o['id']: o for o in client.search_read('account.move', [['id', 'in', ids]],
                                                   ['name', 'invoice_date', 'amount_total', 'ref', 'partner_id'])} if ids else {}
    out, usadas = {}, set()
    for n in nc:
        o = orig.get(n['reversed_entry_id'][0])
        if (not o or not str(o['name']).startswith('FAC') or str(o['invoice_date']) >= desde
                or abs(n['amount_total'] - o['amount_total']) >= 1):
            continue
        cand = client.search_read('account.move', [['move_type', '=', 'out_invoice'], ['state', '=', 'posted'],
                                                   ['partner_id', '=', o['partner_id'][0]],
                                                   ['invoice_date', '>=', str(o['invoice_date'])], ['id', '!=', o['id']]],
                                  ['name', 'invoice_date', 'amount_total', 'ref'])
        cand = [f for f in cand if f['id'] not in usadas and (
            (o.get('ref') and f.get('ref') == o['ref'])
            or (not f.get('ref') and abs(f['amount_total'] - o['amount_total']) <= 100))]
        if cand:
            f = sorted(cand, key=lambda f: str(f['invoice_date']))[-1]
            usadas.add(f['id'])
            out[n['name']] = (f"{n['name']} revierte {o['name']} del {o['invoice_date']} y la refactura "
                              f"{f['name']} (${o['amount_total']:,.0f})")
    return out


def excluir(df: pd.DataFrame, desde: str, verbose=True) -> pd.DataFrame:
    if os.environ.get('DISABLE_REFACTURACION_FIX') == '1' or 'documento' not in df.columns:
        return df
    doc = df['documento'].astype(str).str.strip()
    es_nc = df['tipo_movimiento'].astype(str).eq('Devolución') & doc.str.startswith('N/C')
    fuera = refacturadas(sorted(set(doc[es_nc])), desde)
    if not fuera:
        return df
    m = es_nc & doc.isin(fuera)
    if verbose:
        vb = pd.to_numeric(df.loc[m, 'venta_bruta'], errors='coerce').fillna(0).sum()
        print(f"   [refacturación] {int(m.sum())} filas de NC fuera del RAW (${vb:,.0f}): " + ' · '.join(fuera.values()))
    return df[~m].copy()
