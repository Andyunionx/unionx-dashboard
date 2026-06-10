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

    # NORMALIZAR fecha_venta y fecha_documento del extract Odoo a string YYYY-MM-DD
    # antes de cualquier concat. Odoo a veces devuelve timestamp completo,
    # otras solo fecha; mezclas causan ArrowTypeError al guardar parquet.
    for fcol in ('fecha_venta', 'fecha_documento'):
        if fcol in df.columns:
            df[fcol] = pd.to_datetime(df[fcol], errors='coerce').dt.strftime('%Y-%m-%d')

    # Reclasificar canales: Casa Mila SpA es la razón social de UnionX B2B (no entidad externa)
    if 'canal' in df.columns:
        df['canal'] = df['canal'].replace({'Casa Mila': 'UnionX B2B'})

    # Inyectar facturas manual_externa (Sodimac y similares cargadas a Turso manualmente).
    # Estas NO están en Odoo, entonces el extract las pierde. Se conservan en CSV local.
    manual_csv = PROJECT_ROOT / 'data' / 'manual_externa_facturas.csv'
    if manual_csv.exists():
        manual = pd.read_csv(manual_csv)
        # Filtrar al rango pedido (fechas como string YYYY-MM-DD, mismo dtype que df)
        manual['fecha_venta'] = pd.to_datetime(manual['fecha_venta']).dt.strftime('%Y-%m-%d')
        if 'fecha_documento' in manual.columns:
            manual['fecha_documento'] = pd.to_datetime(manual['fecha_documento'], errors='coerce').dt.strftime('%Y-%m-%d')
        manual = manual[(manual['fecha_venta'] >= desde) & (manual['fecha_venta'] < hasta)]
        if not manual.empty:
            print(f"   [manual_externa] Inyectando {len(manual)} filas (Sodimac etc)...")
            # Quitar columnas extras del CSV que no estén en COLS_DB
            manual = manual[[c for c in COLS_DB if c in manual.columns]]
            # Agregar columnas faltantes vacías
            for c in COLS_DB:
                if c not in manual.columns:
                    manual[c] = ''

            # Enriquecer manual_externa con Matriz Productos (lookup por SKU).
            # Las filas que vienen del CSV tienen categoría vacía; la matriz les da contexto.
            try:
                matriz_path = PROJECT_ROOT / 'data' / 'planillas' / 'Matriz productos.xlsx'
                if matriz_path.exists():
                    matriz = pd.read_excel(matriz_path, sheet_name='Productos')
                    matriz['SKU_norm'] = matriz['SKU'].astype(str).str.strip()
                    mp = matriz.set_index('SKU_norm')
                    enriched = 0
                    for idx, row in manual.iterrows():
                        sku = str(row.get('sku','')).strip()
                        if not sku or sku not in mp.index:
                            continue
                        m = mp.loc[sku]
                        if isinstance(m, pd.DataFrame):
                            m = m.iloc[0]
                        # Solo completar campos vacíos en la fila manual
                        mapping = {
                            'categoria_macro': 'Categoría macro',
                            'categoria_padre': 'Categoría padre',
                            'categoria_hijo': 'Categoría hijo',
                            'categoria_comercial': 'Categoría comercial',
                            'marca': 'Marca',
                            'proveedor': 'Proveedor',
                            'pack': 'Pack',
                            'estado_sku': 'In/out',
                            'tipo_marca': 'Estado marca',
                        }
                        for db_col, mat_col in mapping.items():
                            if mat_col in m.index and pd.notna(m[mat_col]):
                                if not str(row.get(db_col,'')).strip():
                                    manual.at[idx, db_col] = str(m[mat_col])
                        enriched += 1
                    if enriched:
                        print(f"   [manual_externa] Categorías heredadas de Matriz para {enriched}/{len(manual)} filas")
            except Exception as e:
                print(f"   [WARN] No se pudo enriquecer manual_externa con Matriz: {type(e).__name__}: {str(e)[:80]}")

            df = pd.concat([df, manual[COLS_DB]], ignore_index=True)

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

    # Enriquecimiento CMR (Fidelización CMR) desde Google Sheet.
    # Antes era un UPDATE directo a Turso (extract_cmr_ventas.py); ahora se aplica
    # al parquet para que DuckDB lo vea. Se re-aplica en cada generación.
    try:
        from extract_cmr_ventas import enriquecer_cmr_df
        df = enriquecer_cmr_df(df)
    except Exception as e:
        print(f"   [WARN] CMR enrichment saltado: {type(e).__name__}: {str(e)[:100]}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # GATE 1 (mecanismo de seguridad): validar contra el último parquet bueno.
    # Si falla, NO sobreescribir — la app sigue mostrando el último dato válido.
    import json as _json
    from datetime import datetime as _dt
    from validacion_ventas import validar_ventas_df, resumen_validacion
    df_previo = None
    if OUT_PATH.exists():
        try:
            df_previo = pd.read_parquet(OUT_PATH)
        except Exception:
            df_previo = None
    ok, problemas, stats = validar_ventas_df(df, df_previo)
    print("\n" + resumen_validacion(ok, problemas, stats))
    marker = OUT_PATH.parent / 'validacion_ventas.json'
    marker.write_text(_json.dumps({
        'ts': _dt.now().isoformat(timespec='seconds'), 'ok': ok, 'problemas': problemas, 'stats': stats,
    }, default=str, ensure_ascii=False), encoding='utf-8')
    if not ok:
        print("\n[GATE 1] NO se publica el parquet — se conserva el último bueno.", flush=True)
        sys.exit(0)  # salida limpia: el commit posterior no verá cambios

    # Overlay correcciones fecha_venta (cuando Yuju/integrador cargó tarde a Odoo)
    overlay_path = PROJECT_ROOT / 'data' / 'correcciones' / 'fix_fechas_yuju.json'
    if overlay_path.exists():
        try:
            ovl = _json.loads(overlay_path.read_text(encoding='utf-8')).get('correcciones', {})
            if ovl:
                ped_str = df['pedido'].astype(str)
                mask = ped_str.isin(ovl.keys())
                n_fix = int(mask.sum())
                if n_fix > 0:
                    pre = df.loc[mask, 'fecha_venta'].value_counts().to_dict()
                    df.loc[mask, 'fecha_venta'] = ped_str[mask].map(ovl)
                    # Recalcular campos derivados de fecha
                    fv_dt = pd.to_datetime(df.loc[mask, 'fecha_venta'], errors='coerce')
                    if 'anio_venta' in df.columns: df.loc[mask, 'anio_venta'] = fv_dt.dt.year
                    if 'mes_venta' in df.columns: df.loc[mask, 'mes_venta'] = fv_dt.dt.month
                    if 'semana_venta' in df.columns: df.loc[mask, 'semana_venta'] = fv_dt.dt.isocalendar().week
                    if 'dia_semana' in df.columns:
                        dia_nom = ['Lunes','Martes','Miercoles','Jueves','Viernes','Sabado','Domingo']
                        df.loc[mask, 'dia_semana'] = fv_dt.dt.dayofweek.map(lambda i: dia_nom[i] if pd.notna(i) else None)
                    print(f"   [overlay fecha] {n_fix} filas corregidas con fix_fechas_yuju.json | pre={pre}")
        except Exception as e:
            print(f"   [WARN] overlay fecha_venta no aplicado: {type(e).__name__}: {str(e)[:80]}")

    # Overlay canal B2B (pedidos B2B que en Odoo quedan con canal vacio/Website)
    overlay_canal = PROJECT_ROOT / 'data' / 'correcciones' / 'fix_canal_b2b.json'
    if overlay_canal.exists():
        try:
            ovl_b2b = _json.loads(overlay_canal.read_text(encoding='utf-8')).get('correcciones', {})
            if ovl_b2b:
                ped_str = df['pedido'].astype(str)
                n_fix = 0
                for pedido, fix in ovl_b2b.items():
                    mask = ped_str == pedido
                    if mask.sum() > 0:
                        for col, val in fix.items():
                            if col in df.columns:
                                df.loc[mask, col] = val
                        n_fix += int(mask.sum())
                if n_fix > 0:
                    print(f"   [overlay canal B2B] {n_fix} filas reclasificadas con fix_canal_b2b.json")
        except Exception as e:
            print(f"   [WARN] overlay canal B2B no aplicado: {type(e).__name__}: {str(e)[:80]}")

    # Append manuales (ventas externas no en Odoo: El Volcan, Sodimac manual, etc.)
    # Cada archivo en data/manuales/*.parquet se concatena al final del extract.
    manuales_dir = PROJECT_ROOT / 'data' / 'manuales'
    if manuales_dir.exists():
        manual_files = sorted(manuales_dir.glob('*.parquet'))
        if manual_files:
            for mf in manual_files:
                try:
                    df_m = pd.read_parquet(mf)
                    if 'fecha_venta' in df_m.columns:
                        df_m['fecha_venta'] = pd.to_datetime(df_m['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
                    # Solo agregar filas del mes/rango del df principal
                    desde_str = str(df['fecha_venta'].min())[:10]
                    hasta_str = str(df['fecha_venta'].max())[:10]
                    df_m = df_m[(df_m['fecha_venta'] >= desde_str) & (df_m['fecha_venta'] <= hasta_str)]
                    if not df_m.empty:
                        # Alinear cols
                        cols_align = [c for c in df.columns if c in df_m.columns]
                        df_m = df_m[cols_align]
                        for c in df.columns:
                            if c not in df_m.columns:
                                df_m[c] = '' if df[c].dtype == 'object' else 0
                        df_m = df_m[df.columns]
                        df = pd.concat([df, df_m], ignore_index=True)
                        print(f"   [manual] +{len(df_m)} filas desde {mf.name}")
                except Exception as e:
                    print(f"   [WARN] manual {mf.name} no aplicado: {type(e).__name__}: {str(e)[:80]}")

    # DEDUP literal: el extract de Odoo trae duplicados de origen (algun JOIN
    # multiplica filas). Limpia filas 100% identicas en columnas clave.
    n_pre = len(df)
    df_dedup = df.copy()
    for c in df_dedup.columns:
        if str(df_dedup[c].dtype) == 'category':
            df_dedup[c] = df_dedup[c].astype('object')
    df_dedup['_fv_str'] = pd.to_datetime(df_dedup['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    df_dedup['_vb_r'] = pd.to_numeric(df_dedup['venta_bruta'], errors='coerce').fillna(0).round(2)
    df_dedup['_qty'] = pd.to_numeric(df_dedup['cantidad'], errors='coerce').fillna(0)
    df_dedup = df_dedup.drop_duplicates(
        subset=['pedido', 'sku', '_fv_str', 'documento', 'tipo_movimiento', '_vb_r', '_qty'],
        keep='first',
    ).drop(columns=['_fv_str', '_vb_r', '_qty'])
    n_post = len(df_dedup)
    if n_post < n_pre:
        print(f"   [dedup] {n_pre:,} -> {n_post:,} filas (-{n_pre-n_post} duplicados literales)")
    df = df_dedup

    # Forzar columnas object/texto a string. Los archivos manuales pueden traer
    # datetime.time / int / etc, y al concat con extract Odoo se mezclan tipos.
    # PyArrow rompe en to_parquet si una columna object tiene tipos heterogeneos.
    cols_texto_final = [c for c in COLS_DB if c not in (
        'cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario', 'costo_total',
        'margen_front', 'comision_pct', 'comision', 'logistica', 'marketing',
        'margen_final', 'anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num',
        'fecha_venta',
    )]
    for c in cols_texto_final:
        if c in df.columns:
            df[c] = df[c].apply(
                lambda v: '' if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            )

    df.to_parquet(OUT_PATH, index=False)
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"\n[OK] Guardado {OUT_PATH} ({len(df):,} filas, {size_kb:.0f} KB)")
    print(f"     Rango fechas: {df['fecha_venta'].min()} a {df['fecha_venta'].max()}")
    print(f"     Venta bruta total: ${pd.to_numeric(df['venta_bruta']).sum():,.0f}")
    print(f"     Venta neta total:  ${pd.to_numeric(df['venta_neta']).sum():,.0f}")


if __name__ == '__main__':
    main()
