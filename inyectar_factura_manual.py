"""Inyecta facturas manuales (cargadas por contabilidad sin SO en Odoo) a Turso ventas.

Estas facturas tienen state='posted' pero `invoice_origin=False` (sin SO), por
lo que el extract regular NO las trae. Las marcamos con `fuente='manual_externa'`
para que el DEDUP del extract NO las borre.

Uso:
    python inyectar_factura_manual.py
    (los registros se definen en FACTURAS_MANUALES abajo)

Para agregar una nueva factura manual:
1. Verificar en Odoo: factura existe con state='posted' pero sin SO
2. Agregar entrada a FACTURAS_MANUALES con todos los datos
3. Correr el script
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent

env = PROJECT_ROOT / '.env'
for line in env.read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import libsql_client

# ============================================================
# FACTURAS MANUALES — agregar acá las que cargó contabilidad sin SO
# ============================================================
FACTURAS_MANUALES = [
    # FAC 097825 — SODIMAC S.A., Premios educativos
    # Costo aún no asociado → margen 100%
    {
        'documento':       'FAC 097825',
        'fecha_documento': '2026-05-05',
        'fecha_venta':     '2026-05-05',
        'pedido':          '',
        'canal':           'UnionX B2B',
        'tipo_negocio':    'Distribución',
        'kam':             'Martin',
        'producto':        'Premios educativos Sodimac',
        'sku':             '',                 # sin SKU específico
        'marca':           '',
        'categoria_macro': '',
        'categoria_padre': '',
        'categoria_hijo':  '',
        'estado_pedido':   'sale',
        'tipo_movimiento': 'Venta',
        'bodega':          '',
        'cantidad':        1,
        'venta_bruta':     17291199.0,         # con IVA si aplica
        'venta_neta':      17291199.0 / 1.19,  # sin IVA
        'costo_unitario':  0.0,                # SIN COSTO ASOCIADO TODAVÍA
        'costo_total':     0.0,
        'margen_front':    17291199.0 / 1.19,  # = venta_neta → margen 100%
        'comision_pct':    0.0,
        'comision':        0.0,
        'logistica':       0.0,
        'marketing':       0.0,
        'margen_final':    17291199.0 / 1.19,
        'anio_venta':      2026,
        'mes_venta':       5,
        'semana_venta':    19,
        'dia_semana':      1,  # martes
        'hora_venta_num':  0,
        'hora_venta':      '00:00:00',
        'pedido_marketplace': '',
        'client_order_ref':   '',
    },
]


def _new_client():
    return libsql_client.create_client_sync(
        url=os.environ['LIBSQL_URL'],
        auth_token=os.environ['LIBSQL_AUTH_TOKEN'],
    )


def exec_retry(sql, args=None, max_retries=4, base_wait=5, label=''):
    last = None
    for a in range(1, max_retries + 1):
        c = None
        try:
            c = _new_client()
            rs = c.execute(sql, args) if args is not None else c.execute(sql)
            c.close()
            return rs
        except Exception as e:
            last = e
            if c:
                try: c.close()
                except: pass
            if a < max_retries:
                w = base_wait * (2 ** (a - 1))
                print(f"  {label} retry {a} ({type(e).__name__}) en {w}s...", flush=True)
                time.sleep(w)
    raise last


COLS_DB = [
    'tipo_movimiento', 'bodega', 'documento', 'fecha_documento', 'pedido',
    'estado_pedido', 'sku', 'canal', 'fecha_venta', 'hora_venta',
    'producto', 'categoria_macro', 'categoria_padre', 'categoria_hijo',
    'marca', 'tipo_negocio', 'kam', 'anio_venta', 'mes_venta',
    'semana_venta', 'dia_semana', 'hora_venta_num',
    'cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario', 'costo_total',
    'margen_front', 'comision_pct', 'comision', 'logistica', 'marketing',
    'margen_final', 'pedido_marketplace', 'client_order_ref', 'fuente',
]


def main():
    print("=== INYECCIÓN FACTURAS MANUALES (fuente=manual_externa) ===\n")
    docs = [f['documento'] for f in FACTURAS_MANUALES]
    placeholders = ','.join(['?'] * len(docs))

    # 1) Verificar existencia previa
    rs = exec_retry(
        f"SELECT documento, COUNT(*), SUM(venta_bruta) FROM ventas "
        f"WHERE documento IN ({placeholders}) GROUP BY documento",
        docs, label='[check]'
    )
    if rs.rows:
        print("⚠️ Documentos YA existentes, borrando para reinsertar:")
        for r in rs.rows:
            print(f"   {r[0]}: {r[1]} filas, ${r[2] or 0:,.0f}")
        exec_retry(
            f"DELETE FROM ventas WHERE documento IN ({placeholders})",
            docs, label='[del]'
        )
        print("   Eliminados.\n")
    else:
        print("OK: no hay documentos previos.\n")

    # 2) Preparar filas con fuente='manual_externa'
    print(f"[INSERT] {len(FACTURAS_MANUALES)} factura(s) manual(es)...")
    rows = []
    for f in FACTURAS_MANUALES:
        row = []
        for col in COLS_DB:
            if col == 'fuente':
                row.append('manual_externa')
            else:
                row.append(f.get(col, None))
        rows.append(row)

    cols_csv = ','.join(COLS_DB)
    ph = '(' + ','.join('?' * len(COLS_DB)) + ')'
    all_ph = ','.join([ph] * len(rows))
    sql = f"INSERT INTO ventas ({cols_csv}) VALUES {all_ph}"
    flat = [v for r in rows for v in r]
    rs = exec_retry(sql, flat, label='[insert]')
    print(f"   Insertados: {rs.rows_affected} filas\n")

    # 3) Verificación
    rs = exec_retry(
        f"SELECT documento, canal, tipo_negocio, cantidad, venta_bruta, "
        f"costo_total, margen_front, fuente "
        f"FROM ventas WHERE documento IN ({placeholders})",
        docs, label='[verify]'
    )
    print("=== VERIFICACIÓN ===")
    for r in rs.rows:
        doc, canal, tn, qty, vta, cto, marg, fuente = r
        pct = 100.0 * (marg or 0) / (vta or 1)
        print(f"  {doc}")
        print(f"    canal={canal} | tipo_negocio={tn} | qty={qty} | venta=${vta:,.0f}")
        print(f"    costo=${cto:,.0f} | margen=${marg:,.0f} ({pct:.0f}%) | fuente={fuente}")


if __name__ == '__main__':
    main()
