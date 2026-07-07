"""Parser canónico de planes de embarque de Steven (Topwill).

Los planes (Plan B, OHNSO) traen ítems agrupados bajo separadores numerados:
    1.SZ-04,40HQ
    2.SZ-03-08,40HQ
    3.Rest items
Este módulo es la ÚNICA implementación del parseo — no copiar en scripts nuevos.
(Consolidación post-auditoría 7-jul-2026: antes había 10 copias.)

Uso:
    from parser_plan_steven import parsear_plan, parsear_libro, EMBARQUES, fechas_embarque

    items = parsear_libro("OHNSO-Jul.01st.xls")          # SHENZHEN + NINGBO
    items = parsear_plan("plan.xls", "SHENZHEN")         # una hoja

Reglas de negocio (confirmadas por Andrés, jul-2026):
  - "Rest items" NO es plan de carga: es stock disponible sin embarque asignado.
  - La demanda UnionX se consolida por SKU (puede venir repetida por OT).
  - Capacidad contenedor 40HQ = 68 CBM (asumir 623 = 40HQ salvo indicación).
"""
import re
from datetime import datetime, timedelta

import pandas as pd

# --- Parámetros de tránsito vigentes (jul-2026) ---
TRANSITO = {'SZ': 52, 'NB': 45}   # ETD → ETA puerto Chile (días)
CRD_ETD = 7                       # CRD → ETD
PTO_BODEGA = 7                    # ETA puerto → ETA bodega
CAP_40HQ = 68                     # CBM

# Catálogo de embarques conocidos (plan septiembre 2026)
EMBARQUES = {
    'SZ-04,40HQ':        {'origen': 'SZ', 'fijo': True},
    'SZ-03-08,40HQ':     {'origen': 'SZ', 'fijo': True},
    'SZ-01(623)':        {'origen': 'SZ', 'fijo': False},
    'SZ-02(623)':        {'origen': 'SZ', 'fijo': False},
    'IMP OP 350-26 40HQ': {'origen': 'NB', 'fijo': True},
    'NB-01':             {'origen': 'NB', 'fijo': False},
}

SHEETS_DEFAULT = ('SHENZHEN', 'NINGBO')
REST_ITEMS = 'Rest items'

_RE_SECCION = re.compile(r'^\d+\.(.+)$')


def es_rest_items(seccion: str) -> bool:
    """True si la sección es stock sin asignar (no cuenta como plan de carga)."""
    s = str(seccion).upper()
    return 'REST' in s and 'ITEM' in s


def parsear_plan(path, sheet):
    """Parsea una hoja de un plan de Steven.

    Devuelve lista de dicts con las columnas del header original más:
      __seccion : nombre del embarque/sección ("SZ-04,40HQ", "Rest items", ...)
      __sheet   : nombre de la hoja ("SHENZHEN" / "NINGBO")
    """
    df = pd.read_excel(path, sheet_name=sheet, header=None)
    items, seccion, hdr = [], None, None
    for _, row in df.iterrows():
        vals = [v for v in row.values if pd.notna(v)]
        if not vals:
            continue
        first = str(vals[0]).strip()
        m = _RE_SECCION.match(first)
        if m and len(vals) <= 2:
            seccion = m.group(1).strip()
            continue
        if first == 'No' and len(vals) > 1 and 'Model' in str(vals[1]):
            hdr = [str(v).strip() for v in row.values]
            continue
        try:
            int(first)
        except (ValueError, TypeError):
            continue
        if hdr is None or seccion is None:
            continue
        it = {col: row.values[j] for j, col in enumerate(hdr) if j < len(row.values)}
        it['__seccion'] = seccion
        it['__sheet'] = sheet
        items.append(it)
    return items


def parsear_libro(path, sheets=SHEETS_DEFAULT):
    """Parsea todas las hojas indicadas y concatena los ítems."""
    items = []
    for s in sheets:
        items.extend(parsear_plan(path, s))
    return items


def indexar_por_sku(items):
    """Índice SKU → lista de matches normalizados (qty, cbm, embarque, finish...)."""
    idx = {}
    for it in items:
        sku = str(it.get('SKU', '') or '').strip()
        if not sku or sku.lower() == 'nan':
            continue
        qty = pd.to_numeric(it.get('Qty'), errors='coerce')
        if not pd.notna(qty):
            continue
        finish = it.get('Finish Time')
        idx.setdefault(sku, []).append({
            'embarque': it['__seccion'],
            'sheet': it.get('__sheet'),
            'es_plan': not es_rest_items(it['__seccion']),
            'qty': int(qty),
            'cbm_total': pd.to_numeric(it.get('TOTAL CBM'), errors='coerce'),
            'cbm_ctn': pd.to_numeric(it.get('(CBM)\n/CTN'), errors='coerce'),
            'qty_ctn': pd.to_numeric(it.get("Q'ty/ctn"), errors='coerce'),
            'price': pd.to_numeric(it.get('Price\n(USD)'), errors='coerce'),
            'model': str(it.get('Model', '') or '').strip(),
            'finish': finish if isinstance(finish, datetime) else None,
        })
    return idx


def crd_por_embarque(items):
    """CRD de cada embarque = MAX(Finish Time) de sus ítems (excluye Rest items)."""
    crds = {}
    for it in items:
        if es_rest_items(it['__seccion']):
            continue
        f = it.get('Finish Time')
        if isinstance(f, datetime):
            e = it['__seccion']
            if e not in crds or f > crds[e]:
                crds[e] = f
    return crds


def fechas_embarque(embarque, crd):
    """Cadena CRD → ETD → ETA puerto → ETA bodega para un embarque."""
    origen = 'NB' if ('NB' in embarque.upper() or 'IMP OP' in embarque.upper()) else 'SZ'
    etd = crd + timedelta(days=CRD_ETD)
    eta_pto = etd + timedelta(days=TRANSITO[origen])
    eta_bod = eta_pto + timedelta(days=PTO_BODEGA)
    return crd, etd, eta_pto, eta_bod
