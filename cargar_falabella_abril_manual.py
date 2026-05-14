#!/usr/bin/env python3
"""
Reemplazo manual de Falabella abril 2026: del Drive → Turso + parquet.

Razón: el extractor de Odoo está perdiendo líneas de venta cuando un pedido
tiene varias `sale.order.line` del mismo producto (multi-unit). Caso típico
Falabella mayorista: pide 6 unidades → Odoo genera 7 líneas (6 producto qty=1
+ 1 delivery), el extractor guarda solo 2.

Verificación directa Odoo XML-RPC confirmó:
- Pedido S212955 → 7 líneas, total $619.930 (Drive correcto, local solo $120K)
- Pedido S216955 → 7 líneas, total $442.930 (Drive correcto)
- Pedido S221337 → 5 líneas, total $399.950 (Drive correcto)

Mientras investigamos el fix del extractor, este script:
  1. DELETE de TODAS las filas Falabella abril 2026 en Turso (incompletas)
  2. INSERT desde Drive (que tiene las líneas correctas)
  3. Mismo reemplazo en el parquet histórico local

Idempotente — se puede re-ejecutar sin duplicar.
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

CANALES_A_REEMPLAZAR = ['Falabella']
DESDE = '2026-04-01'
HASTA = '2026-05-01'  # exclusivo

# Misma 40 cols + venta_neta calculada al final
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

COLS_DB = list(DRIVE_TO_DB.values())
COLS_PARQUET = COLS_DB + ['venta_neta']


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


def turso_pipeline(stmts: list, timeout_s: int = 120, retries: int = 4) -> dict:
    import time as _t
    url = os.environ['LIBSQL_URL'].rstrip('/')
    tok = os.environ['LIBSQL_AUTH_TOKEN']
    hdr = {'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}
    body = {'requests': [{'type': 'execute', 'stmt': s} for s in stmts] + [{'type': 'close'}]}
    last = None
    for i in range(retries):
        try:
            r = requests.post(f'{url}/v2/pipeline', json=body, headers=hdr, timeout=timeout_s)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.RequestException, KeyError) as e:
            last = e
            wait = 3 + i * 5
            print(f"   [retry {i+1}/{retries}] {type(e).__name__}, esperando {wait}s...", flush=True)
            _t.sleep(wait)
    raise last


def _coercer(df_drv: pd.DataFrame) -> pd.DataFrame:
    df = df_drv.copy()
    df.columns = [DRIVE_TO_DB.get(c, c) for c in df.columns]
    df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce')
    for c in ('cantidad', 'venta_bruta', 'costo_unitario', 'costo_total',
              'margen_front', 'comision_pct', 'comision', 'logistica',
              'marketing', 'margen_final'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
    for c in ('anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype('int64')
    df['venta_neta'] = (df['venta_bruta'] / 1.19).round(2)
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
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 'NULL'
    if isinstance(val, str):
        return "'" + val.replace("'", "''") + "'"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, pd.Timestamp):
        return f"'{val.strftime('%Y-%m-%d')}'"
    return "'" + str(val).replace("'", "''") + "'"


def main():
    _load_env()
    if not os.environ.get('LIBSQL_URL') or not os.environ.get('LIBSQL_AUTH_TOKEN'):
        print('[ERROR] LIBSQL_URL/TOKEN no seteados')
        sys.exit(1)

    raw = _descargar_drive()
    print("[2] Leyendo pestaña RAW...")
    df = pd.read_excel(io.BytesIO(raw), sheet_name='RAW')
    df = _coercer(df)
    print(f"   Drive total filas: {len(df):,}")

    df['canal_norm'] = df['canal'].astype(str).str.strip()
    desde_ts = pd.Timestamp(DESDE)
    hasta_ts = pd.Timestamp(HASTA)
    mask = (df['canal_norm'].isin(CANALES_A_REEMPLAZAR)
            & (df['fecha_venta'] >= desde_ts) & (df['fecha_venta'] < hasta_ts))
    sel = df[mask].drop(columns='canal_norm').copy()
    print(f"\n[3] Filtro Falabella abril 2026 en Drive: {len(sel):,} filas")

    if sel.empty:
        print("   Sin filas. Saliendo.")
        sys.exit(0)

    # Stats por tipo_movimiento
    g = sel.groupby('tipo_movimiento').agg(
        filas=('cantidad', 'count'),
        uds=('cantidad', 'sum'),
        venta_bruta=('venta_bruta', 'sum'),
        margen_front=('margen_front', 'sum'),
    ).reset_index()
    print(g.to_string(index=False))
    print(f"   TOTAL Drive: {len(sel):,} filas | {sel['venta_bruta'].sum():,.0f} venta | {sel['margen_front'].sum():,.0f} margen")

    # 4. DELETE Falabella abril en Turso (día por día para evitar timeout)
    print("\n[4] DELETE Falabella abril 2026 en Turso día por día (evitar timeout)...")
    canales_in = ','.join(f"'{c}'" for c in CANALES_A_REEMPLAZAR)
    affected_delete = 0
    fechas = pd.date_range(DESDE, HASTA, inclusive='left')
    for fecha in fechas:
        f_str = fecha.strftime('%Y-%m-%d')
        delete_sql = (f"DELETE FROM ventas WHERE canal IN ({canales_in}) AND fecha_venta = '{f_str}'")
        res = turso_pipeline([{'sql': delete_sql}], timeout_s=60)
        affected = res['results'][0]['response']['result'].get('affected_row_count', 0)
        affected_delete += affected
        if affected > 0:
            print(f"   {f_str}: -{affected} filas")
    print(f"   TOTAL eliminadas: {affected_delete:,}")

    # 5. INSERT chunks
    print(f"\n[5] INSERT desde Drive en Turso por chunks de 100...")
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
        res = turso_pipeline(stmts, timeout_s=180)
        for r in res['results']:
            if r.get('type') == 'ok':
                inserted += r.get('response', {}).get('result', {}).get('affected_row_count', 0)
        print(f"   chunk {i // chunk_size + 1}: +{len(chunk)} filas (total {inserted:,})")

    # 6. REPLACE en parquet
    print(f"\n[6] REPLACE Falabella abril en parquet histórico local...")
    df_hist = pd.read_parquet(PARQUET)
    df_hist['fecha_venta'] = pd.to_datetime(df_hist['fecha_venta'], errors='coerce')
    n_pre = len(df_hist)
    n_falabella_old = ((df_hist['canal'].isin(CANALES_A_REEMPLAZAR))
                       & (df_hist['fecha_venta'] >= desde_ts)
                       & (df_hist['fecha_venta'] < hasta_ts)).sum()
    venta_falabella_old = df_hist[(df_hist['canal'].isin(CANALES_A_REEMPLAZAR))
                                    & (df_hist['fecha_venta'] >= desde_ts)
                                    & (df_hist['fecha_venta'] < hasta_ts)]['venta_bruta'].sum()
    df_hist = df_hist[~((df_hist['canal'].isin(CANALES_A_REEMPLAZAR))
                        & (df_hist['fecha_venta'] >= desde_ts)
                        & (df_hist['fecha_venta'] < hasta_ts))]
    print(f"   Parquet pre: {n_pre:,} filas, Falabella abril removidas: {n_falabella_old:,} (${venta_falabella_old:,.0f})")

    sel_parquet = sel[COLS_PARQUET].copy()
    sel_parquet['fecha_venta'] = sel_parquet['fecha_venta'].dt.strftime('%Y-%m-%d')
    df_hist['fecha_venta'] = df_hist['fecha_venta'].dt.strftime('%Y-%m-%d')

    df_final = pd.concat([df_hist[COLS_PARQUET], sel_parquet], ignore_index=True)
    df_final['_fv'] = pd.to_datetime(df_final['fecha_venta'])
    df_final = df_final.sort_values('_fv', kind='stable').drop(columns='_fv')

    df_final.to_parquet(PARQUET, index=False)
    print(f"   Parquet final: {len(df_final):,} filas ({PARQUET.stat().st_size / 1e6:.1f} MB)")

    # Diff
    delta_filas = len(df_final) - n_pre
    delta_venta = sel['venta_bruta'].sum() - venta_falabella_old
    print(f"\n   Delta filas: {delta_filas:+,} | Delta venta: {delta_venta:+,.0f}")

    # Log
    log_path = PROJECT_ROOT / 'data' / 'cmr' / f"falabella_abril_drive_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    log = {
        'fecha_ejecucion': datetime.now().isoformat(timespec='seconds'),
        'canal': 'Falabella',
        'rango': {'desde': DESDE, 'hasta_excl': HASTA},
        'razon': 'Bug extractor pierde lineas en multi-unidad. Reemplazo con Drive.',
        'turso': {
            'filas_eliminadas': int(affected_delete),
            'filas_insertadas': int(inserted),
        },
        'parquet': {
            'filas_pre': int(n_pre),
            'filas_post': int(len(df_final)),
            'filas_falabella_removidas': int(n_falabella_old),
            'venta_falabella_anterior': float(venta_falabella_old),
            'venta_falabella_nueva': float(sel['venta_bruta'].sum()),
            'delta_venta': float(delta_venta),
        },
        'resumen_drive': g.to_dict(orient='records'),
    }
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] Log: {log_path}")
    print(f"\n=== RESUMEN FINAL ===")
    print(f"Turso Falabella abril: {affected_delete:,} filas eliminadas → {inserted:,} insertadas")
    print(f"Parquet: {n_pre:,} → {len(df_final):,} ({delta_filas:+,} filas)")
    print(f"Venta Falabella abril: ${venta_falabella_old:,.0f} → ${sel['venta_bruta'].sum():,.0f} ({delta_venta:+,.0f})")


if __name__ == '__main__':
    main()
