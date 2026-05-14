#!/usr/bin/env python3
"""
Carga manual de ventas Sawa y El Volcán abril 2026 desde el Drive maestro a Turso.

Estos canales son cargas manuales que el extractor de Odoo filtra deliberadamente:
- El Volcán: SIEMPRE filtrado (consignación, ventas vienen vía Drive del equipo admin)
- Sawa: filtrado solo en abril 2026 (decisión user)

Este script las trae explícitamente del Drive y las inserta en Turso para que el
dashboard de ventas las refleje.

Idempotente: DELETE previo de filas (canal IN (Sawa, El Volcan) AND fecha abril 2026)
antes de INSERT, para no duplicar si se vuelve a correr.

Output:
  - Turso: rows insertadas en tabla ventas
  - Parquet local data/historico/ventas_historico.parquet actualizado
  - Log en data/cmr/sawa_volcan_manual_YYYYMMDD.json
"""
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent
CREDENTIALS = PROJECT_ROOT / 'credentials.json'
DRIVE_FILE_ID = '1K11y6icDm9M3X3glGUVCOe4HsbpWpEBm'
PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'

CANALES_A_CARGAR = ['Sawa', 'El Volcan']
DESDE = '2026-04-01'
HASTA = '2026-05-01'  # exclusivo

# Mismas 40 cols que el parquet histórico
DRIVE_TO_DB = {
    'Tipo Movimiento': 'tipo_movimiento', 'Bodega': 'bodega', 'Documento': 'documento',
    'Fecha Documento': 'fecha_documento', 'Pedido': 'pedido', 'Estado Pedido': 'estado_pedido',
    'Tipo Despacho': 'tipo_despacho', 'SKU': 'sku', 'Canal': 'canal',
    'Fecha Venta': 'fecha_venta', 'Hora Venta': 'hora_venta', 'Producto': 'producto',
    'Categoría macro': 'categoria_macro', 'Categoría padre': 'categoria_padre',
    'Categoría hijo': 'categoria_hijo', 'Categoría comercial': 'categoria_comercial',
    'Estado SKU': 'estado_sku', 'Pack': 'pack', 'Marca': 'marca', 'Proveedor': 'proveedor',
    'Tipo Marca': 'tipo_marca', 'Tipo Compra': 'tipo_compra', 'Tipo Negocio': 'tipo_negocio',
    'KAM': 'kam', 'Estado Canal': 'estado_canal', 'Año venta': 'anio_venta',
    'Mes venta': 'mes_venta', 'Semana venta': 'semana_venta', 'Día semana': 'dia_semana',
    'Hora venta': 'hora_venta_num', 'Cantidad': 'cantidad', 'Venta bruta': 'venta_bruta',
    'Costo Unitario': 'costo_unitario', 'Costo Total': 'costo_total',
    'Margen Front': 'margen_front', 'Comision %': 'comision_pct',
    'Comisión': 'comision', 'Logística': 'logistica', 'Marketing': 'marketing',
    'Mg final': 'margen_final',
}

COLS_DB = list(DRIVE_TO_DB.values())  # 40 cols
COLS_PARQUET = COLS_DB + ['venta_neta']  # parquet tiene venta_neta extra


def _load_env():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _descargar_drive() -> bytes:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    creds = Credentials.from_service_account_file(
        str(CREDENTIALS),
        scopes=['https://www.googleapis.com/auth/drive.readonly'],
    )
    drive = build('drive', 'v3', credentials=creds)
    print("[1] Descargando Drive maestro...")
    request = drive.files().get_media(fileId=DRIVE_FILE_ID)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf.read()


def turso_pipeline(stmts: list, timeout_s: int = 90) -> dict:
    """Ejecuta varios statements en un solo request (Turso v2 pipeline)."""
    url = os.environ['LIBSQL_URL'].rstrip('/')
    tok = os.environ['LIBSQL_AUTH_TOKEN']
    hdr = {'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}
    body = {'requests': [{'type': 'execute', 'stmt': s} for s in stmts] + [{'type': 'close'}]}
    r = requests.post(f'{url}/v2/pipeline', json=body, headers=hdr, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def _coercer(df_drv: pd.DataFrame) -> pd.DataFrame:
    """Normaliza dtypes para compatibilidad con parquet."""
    df = df_drv.copy()
    df.columns = [DRIVE_TO_DB.get(c, c) for c in df.columns]

    # Fecha_venta a datetime
    df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce')

    # Numéricos
    for c in ('cantidad', 'venta_bruta', 'costo_unitario', 'costo_total',
              'margen_front', 'comision_pct', 'comision', 'logistica',
              'marketing', 'margen_final'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
    for c in ('anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype('int64')

    # Calcular venta_neta para el parquet
    df['venta_neta'] = (df['venta_bruta'] / 1.19).round(2)

    # Strings (lo que no es número/fecha): forzar str
    cols_texto = [c for c in COLS_DB if c not in (
        'cantidad', 'venta_bruta', 'costo_unitario', 'costo_total', 'margen_front',
        'comision_pct', 'comision', 'logistica', 'marketing', 'margen_final',
        'anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num', 'fecha_venta',
    )]
    for c in cols_texto:
        if c in df.columns:
            df[c] = df[c].astype('object').where(df[c].notna(), '').astype(str).replace('nan', '')

    return df


def _sql_literal(val) -> str:
    """Convierte un valor python a literal SQL seguro."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 'NULL'
    if isinstance(val, str):
        escaped = val.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, pd.Timestamp):
        return f"'{val.strftime('%Y-%m-%d')}'"
    return f"'{str(val)}'"


def main():
    _load_env()
    if not os.environ.get('LIBSQL_URL') or not os.environ.get('LIBSQL_AUTH_TOKEN'):
        print('[ERROR] LIBSQL_URL/TOKEN no seteados')
        sys.exit(1)

    # 1. Descargar Drive
    raw = _descargar_drive()
    print("[2] Leyendo pestaña RAW...")
    df = pd.read_excel(io.BytesIO(raw), sheet_name='RAW')
    df = _coercer(df)
    print(f"   Drive total filas: {len(df):,}")

    # 2. Filtrar Sawa + El Volcán abril 2026
    df['canal_norm'] = df['canal'].astype(str).str.strip()
    desde_ts = pd.Timestamp(DESDE)
    hasta_ts = pd.Timestamp(HASTA)
    mask = (df['canal_norm'].isin(CANALES_A_CARGAR)
            & (df['fecha_venta'] >= desde_ts) & (df['fecha_venta'] < hasta_ts))
    sel = df[mask].drop(columns='canal_norm').copy()
    print(f"\n[3] Filtro {CANALES_A_CARGAR} abril 2026: {len(sel):,} filas")

    if sel.empty:
        print("   Sin filas para cargar. Saliendo.")
        sys.exit(0)

    # Stats preview
    g = sel.groupby('canal').agg(
        filas=('cantidad', 'count'),
        uds=('cantidad', 'sum'),
        venta_bruta=('venta_bruta', 'sum'),
        margen_front=('margen_front', 'sum'),
    ).reset_index()
    print(g.to_string(index=False))

    # 3. DELETE previo en Turso (idempotencia)
    print("\n[4] DELETE en Turso (limpia previos de Sawa/Volcan abril)...")
    canales_in = ','.join(f"'{c}'" for c in CANALES_A_CARGAR)
    delete_sql = (f"DELETE FROM ventas WHERE canal IN ({canales_in}) "
                   f"AND fecha_venta >= '{DESDE}' AND fecha_venta < '{HASTA}'")
    res = turso_pipeline([{'sql': delete_sql}])
    affected_delete = res['results'][0]['response']['result'].get('affected_row_count', 0)
    print(f"   Filas eliminadas previo: {affected_delete}")

    # 4. INSERT chunks (200 filas por request para no exceder body size)
    print(f"\n[5] INSERT en Turso por chunks...")
    cols_csv = ','.join(COLS_DB)
    sel['fecha_venta_str'] = sel['fecha_venta'].dt.strftime('%Y-%m-%d')

    inserted = 0
    chunk_size = 100
    for i in range(0, len(sel), chunk_size):
        chunk = sel.iloc[i:i + chunk_size]
        stmts = []
        for _, row in chunk.iterrows():
            vals = []
            for c in COLS_DB:
                v = row['fecha_venta_str'] if c == 'fecha_venta' else row[c]
                vals.append(_sql_literal(v))
            sql = f"INSERT INTO ventas ({cols_csv}) VALUES ({','.join(vals)})"
            stmts.append({'sql': sql})
        res = turso_pipeline(stmts, timeout_s=120)
        # Sumar affected_row_count de cada statement
        for r in res['results']:
            if r.get('type') == 'ok':
                inserted += r.get('response', {}).get('result', {}).get('affected_row_count', 0)
        print(f"   chunk {i // chunk_size + 1}: +{len(chunk)} filas (total {inserted})")

    # 5. APPEND al parquet local
    print(f"\n[6] APPEND al parquet histórico local...")
    df_hist = pd.read_parquet(PARQUET)
    df_hist['fecha_venta'] = pd.to_datetime(df_hist['fecha_venta'], errors='coerce')
    # Quitar pre-existentes (idempotencia)
    n_pre = len(df_hist)
    df_hist = df_hist[~((df_hist['canal'].isin(CANALES_A_CARGAR))
                        & (df_hist['fecha_venta'] >= desde_ts)
                        & (df_hist['fecha_venta'] < hasta_ts))]
    n_post_clean = len(df_hist)
    print(f"   Parquet pre: {n_pre:,} filas → tras limpiar Sawa/Volcan abril: {n_post_clean:,}")

    # Concat con los nuevos
    sel_parquet = sel[COLS_PARQUET].copy()
    sel_parquet['fecha_venta'] = sel_parquet['fecha_venta'].dt.strftime('%Y-%m-%d')

    df_hist['fecha_venta'] = df_hist['fecha_venta'].dt.strftime('%Y-%m-%d')
    df_final = pd.concat([df_hist[COLS_PARQUET], sel_parquet], ignore_index=True)

    # Sort por fecha_venta
    df_final['_fv'] = pd.to_datetime(df_final['fecha_venta'])
    df_final = df_final.sort_values('_fv', kind='stable').drop(columns='_fv')

    df_final.to_parquet(PARQUET, index=False)
    print(f"   Parquet final: {len(df_final):,} filas ({PARQUET.stat().st_size / 1e6:.1f} MB)")

    # 6. Log
    log_dir = PROJECT_ROOT / 'data' / 'cmr'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"sawa_volcan_manual_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    log = {
        'fecha_ejecucion': datetime.now().isoformat(timespec='seconds'),
        'canales': CANALES_A_CARGAR,
        'rango': {'desde': DESDE, 'hasta_excl': HASTA},
        'turso': {
            'filas_eliminadas_previo': int(affected_delete),
            'filas_insertadas': int(inserted),
        },
        'parquet': {
            'filas_pre': int(n_pre),
            'filas_post_clean': int(n_post_clean),
            'filas_final': int(len(df_final)),
            'filas_agregadas': int(len(sel_parquet)),
        },
        'resumen_por_canal': g.to_dict(orient='records'),
    }
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] Log guardado: {log_path}")
    print(f"\n=== RESUMEN ===")
    print(f"Turso: {inserted} filas insertadas (eliminadas previas: {affected_delete})")
    print(f"Parquet: {len(df_final):,} filas total ({len(sel_parquet)} agregadas)")


if __name__ == '__main__':
    main()
