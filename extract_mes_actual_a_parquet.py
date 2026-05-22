#!/usr/bin/env python3
"""
Descarga el mes actual y lo guarda en parquet local.

Fuente: por defecto **Odoo directo** (bypass Turso) para que el dashboard siga
funcionando incluso si Turso está bloqueado por cuota o caído. Si se pasa
`--source=turso` se mantiene el comportamiento legacy.

El dashboard de Ventas usa este parquet para mostrar el mes en curso.

Output: data/historico/ventas_mes_actual.parquet

Uso:
    python extract_mes_actual_a_parquet.py                 # mes actual desde Odoo
    python extract_mes_actual_a_parquet.py --mes 2026-05   # mes específico
    python extract_mes_actual_a_parquet.py --source turso  # legacy: desde Turso
"""
import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
OUT_PATH = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'

COLS_DB = [
    'tipo_movimiento', 'bodega', 'documento', 'fecha_documento', 'pedido',
    'estado_pedido', 'tipo_despacho', 'sku', 'canal', 'fecha_venta',
    'hora_venta', 'producto', 'categoria_macro', 'categoria_padre',
    'categoria_hijo', 'categoria_comercial', 'estado_sku', 'pack', 'marca',
    'proveedor', 'tipo_marca', 'tipo_compra', 'tipo_negocio', 'kam',
    'estado_canal', 'anio_venta', 'mes_venta', 'semana_venta', 'dia_semana',
    'hora_venta_num', 'cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario',
    'costo_total', 'margen_front', 'comision_pct', 'comision', 'logistica',
    'marketing', 'margen_final',
]

# Mapeo RAW Odoo → DB (igual que actualizar_raw_historico.py)
RAW_TO_DB = {
    'Tipo Movimiento': 'tipo_movimiento', 'Bodega': 'bodega', 'Documento': 'documento',
    'Fecha Documento': 'fecha_documento', 'Pedido': 'pedido', 'Estado Pedido': 'estado_pedido',
    'Tipo Despacho': 'tipo_despacho', 'SKU': 'sku', 'Canal': 'canal',
    'Fecha Venta': 'fecha_venta', 'Hora Venta': 'hora_venta', 'Producto': 'producto',
    'Categoría macro': 'categoria_macro', 'Categoría padre': 'categoria_padre',
    'Categoría hijo': 'categoria_hijo', 'Categoría comercial': 'categoria_comercial',
    'Estado SKU': 'estado_sku', 'Pack': 'pack', 'Marca': 'marca',
    'Proveedor': 'proveedor', 'Tipo Marca': 'tipo_marca', 'Tipo Compra': 'tipo_compra',
    'Tipo Negocio': 'tipo_negocio', 'KAM': 'kam', 'Estado Canal': 'estado_canal',
    'Año venta': 'anio_venta', 'Mes venta': 'mes_venta', 'Semana venta': 'semana_venta',
    'Día semana': 'dia_semana', 'Hora venta': 'hora_venta_num',
    'Cantidad': 'cantidad', 'Venta bruta': 'venta_bruta', 'Venta Neta': 'venta_neta',
    'Costo Unitario': 'costo_unitario', 'Costo Total': 'costo_total',
    'Margen Front': 'margen_front', 'Comision %': 'comision_pct',
    'Comisión': 'comision', 'Logística': 'logistica',
    'Marketing': 'marketing', 'Mg final': 'margen_final',
}


def _load_env():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _mes_actual_yyyymm() -> str:
    return datetime.now().strftime('%Y-%m')


def _rango_mes(yyyymm: str) -> tuple[str, str]:
    año, mes = map(int, yyyymm.split('-'))
    desde = f"{año:04d}-{mes:02d}-01"
    if mes == 12:
        hasta = f"{año + 1:04d}-01-01"
    else:
        hasta = f"{año:04d}-{mes + 1:02d}-01"
    return desde, hasta


def _coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Forzar dtypes consistentes con el resto del pipeline."""
    for c in ('cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario',
              'costo_total', 'margen_front', 'comision_pct', 'comision',
              'logistica', 'marketing', 'margen_final'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
    for c in ('anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype('int64')
    cols_texto = [c for c in COLS_DB if c not in (
        'cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario', 'costo_total',
        'margen_front', 'comision_pct', 'comision', 'logistica', 'marketing',
        'margen_final', 'anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num',
        'fecha_venta',
    )]
    for c in cols_texto:
        if c in df.columns:
            df[c] = df[c].astype('object').where(df[c].notna(), '').astype(str).replace('nan', '')
    return df


def extract_from_turso(desde: str, hasta: str) -> pd.DataFrame:
    """Legacy: lee desde Turso libSQL."""
    if not os.environ.get('LIBSQL_URL') or not os.environ.get('LIBSQL_AUTH_TOKEN'):
        raise RuntimeError('LIBSQL_URL/LIBSQL_AUTH_TOKEN no seteados')
    import libsql_client
    client = libsql_client.create_client_sync(
        url=os.environ['LIBSQL_URL'],
        auth_token=os.environ['LIBSQL_AUTH_TOKEN'],
    )
    t0 = time.time()
    cols_csv = ','.join(COLS_DB)
    rs = client.execute(
        f"SELECT {cols_csv} FROM ventas "
        f"WHERE fecha_venta >= '{desde}' AND fecha_venta < '{hasta}' "
        f"ORDER BY fecha_venta"
    )
    elapsed = time.time() - t0
    print(f"   [Turso] {len(rs.rows):,} filas en {elapsed:.1f}s")
    df = pd.DataFrame(rs.rows, columns=COLS_DB)
    client.close()
    return df


def extract_from_odoo(desde: str, hasta: str) -> pd.DataFrame:
    """Bypass: extrae directo desde Odoo (sin Turso). Más lento (3-5 min) pero
    no depende de Turso. Aplica las mismas reglas que actualizar_raw_historico.py:
    Matriz productos, Maestra canales, costo_override, NCs como filas negativas, etc.
    """
    sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

    from app.core.odoo_client import OdooClient
    from app.services.ventas_service import VentasService
    from app.config import Config

    cfg = Config()
    client = OdooClient(cfg.ODOO_URL, cfg.ODOO_DB, cfg.ODOO_USER, cfg.ODOO_PASSWORD)
    planillas_dir = PROJECT_ROOT / 'data' / 'planillas'
    svc = VentasService(client, planillas_dir)

    # Odoo espera 'YYYY-MM-DD HH:MM:SS'. hasta es '<próximo mes>-01'; lo
    # convertimos a '<último día actual> 23:59:59'.
    desde_full = f"{desde} 00:00:00"
    # restar 1 día a 'hasta' para tener último día del mes actual
    from datetime import datetime, timedelta
    hasta_dt = datetime.strptime(hasta, '%Y-%m-%d') - timedelta(seconds=1)
    hasta_full = hasta_dt.strftime('%Y-%m-%d %H:%M:%S')

    print(f"   [Odoo] Extrayendo {desde_full} a {hasta_full} (puede tardar 3-5 min)...")
    t0 = time.time()
    df_raw = svc.extract_to_raw_format(desde_full, hasta_full)
    elapsed = time.time() - t0
    print(f"   [Odoo] {len(df_raw):,} filas RAW en {elapsed:.1f}s")

    # Renombrar columnas RAW (Odoo) → DB
    df = df_raw.rename(columns=RAW_TO_DB).copy()
    # Quedarse solo con COLS_DB (descarta pedido_marketplace, client_order_ref)
    df = df[[c for c in COLS_DB if c in df.columns]]

    # Aplicar costo_override si tabla existe localmente (refleja fixes manuales)
    override_csv = PROJECT_ROOT / 'data' / 'costo_override.csv'
    if override_csv.exists():
        ov = pd.read_csv(override_csv)
        ov_map = dict(zip(ov['sku'].astype(str), ov['costo_unitario'].astype(float)))
        mask = (df['costo_total'].fillna(0) == 0) & df['sku'].astype(str).isin(ov_map)
        if mask.any():
            print(f"   [overlay] Aplicando costo_override a {mask.sum()} filas...")
            df.loc[mask, 'costo_unitario'] = df.loc[mask, 'sku'].astype(str).map(ov_map)
            df.loc[mask, 'costo_total'] = df.loc[mask, 'costo_unitario'] * df.loc[mask, 'cantidad']
            df.loc[mask, 'margen_front'] = df.loc[mask, 'venta_neta'] - df.loc[mask, 'costo_total']
            df.loc[mask, 'margen_final'] = df.loc[mask, 'margen_front']

    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mes', default=None, help='YYYY-MM (default: mes actual)')
    parser.add_argument('--source', choices=['odoo', 'turso'], default='odoo',
                       help='Fuente: "odoo" (default, bypass Turso) o "turso" (legacy)')
    args = parser.parse_args()

    _load_env()

    mes = args.mes or _mes_actual_yyyymm()
    desde, hasta = _rango_mes(mes)
    print(f"[1] Descargando ventas {mes} ({desde} a {hasta}) — fuente: {args.source.upper()}")

    if args.source == 'turso':
        df = extract_from_turso(desde, hasta)
    else:
        df = extract_from_odoo(desde, hasta)

    if df.empty:
        print(f"   [WARN] Sin filas. Saliendo sin escribir parquet.")
        sys.exit(0)

    df = _coerce_dtypes(df)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"\n[OK] Guardado {OUT_PATH} ({len(df):,} filas, {size_kb:.0f} KB)")
    print(f"     Rango fechas: {df['fecha_venta'].min()} a {df['fecha_venta'].max()}")
    print(f"     Venta bruta total: ${pd.to_numeric(df['venta_bruta']).sum():,.0f}")
    print(f"     Venta neta total:  ${pd.to_numeric(df['venta_neta']).sum():,.0f}")


if __name__ == '__main__':
    main()
