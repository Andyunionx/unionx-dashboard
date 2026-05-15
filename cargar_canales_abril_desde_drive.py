#!/usr/bin/env python3
"""
Reemplaza canales abril 2026 con datos del Drive RAW maestro.

Razón: el extractor de Odoo (o el sync de cada canal) deja data residual
distinta a la del Drive operacional. Mientras se debuggea cada caso, este
script trae las filas del Drive y reemplaza el período abril en
Turso + parquet histórico local.

Canales soportados (lista CANALES_A_REEMPLAZAR abajo):
- Falabella, Sawa, El Volcan: ya cargados con scripts previos
- CMR, Paris, Mercado Libre, Kitchen Center, UnionX B2B: nuevos
- Cualquiera con bug multi-unidad o sync incompleto

Idempotente: DELETE Local + INSERT Drive por canal/mes.

Uso:
    python cargar_canales_abril_desde_drive.py
    python cargar_canales_abril_desde_drive.py --canales "CMR,Paris,Mercado Libre"
"""
import argparse
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent
CREDENTIALS = PROJECT_ROOT / 'credentials.json'
DRIVE_FILE_ID = '1K11y6icDm9M3X3glGUVCOe4HsbpWpEBm'
PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'

CANALES_DEFAULT = ['CMR', 'Paris', 'Mercado Libre', 'Kitchen Center',
                    'UnionX B2B', 'Walmart', 'Celmedia', 'UnionX web',
                    'Ripley', 'Travel Duty', 'Lhotse web', 'Simplit web',
                    'Global Reward', 'ExpoRunning', 'Speedreams', 'Eattouch',
                    'SP Digital', 'Hites', 'Abc', 'Banco Bice', 'Marketing',
                    'Corporativo', 'Lokal', 'Friends', 'BazarED',
                    'Ferretería Higuerillas', 'Relacional', 'Gluky',
                    'Ripley tienda', 'Concesionarios autos']

DESDE = '2026-04-01'
HASTA = '2026-05-01'

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
    'Pedido Marketplace': 'pedido_marketplace', 'Ref Cliente': 'client_order_ref',
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


def _descargar() -> bytes:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    creds = Credentials.from_service_account_file(
        str(CREDENTIALS),
        scopes=['https://www.googleapis.com/auth/drive.readonly'],
    )
    drive = build('drive', 'v3', credentials=creds)
    request = drive.files().get_media(fileId=DRIVE_FILE_ID)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf.read()


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
    parser = argparse.ArgumentParser()
    parser.add_argument('--canales', default=','.join(CANALES_DEFAULT),
                        help='Lista de canales separados por coma')
    parser.add_argument('--skip-turso', action='store_true',
                        help='Solo parquet, omite Turso (útil cuando red lenta)')
    args = parser.parse_args()

    canales = [c.strip() for c in args.canales.split(',') if c.strip()]
    print(f"Canales a procesar: {canales}")

    _load_env()

    # 1. Cargar Drive completo
    print("\n[1] Descargando Drive...")
    raw = _descargar()
    df = pd.read_excel(io.BytesIO(raw), sheet_name='RAW')
    df = _coercer(df)
    print(f"   Drive RAW: {len(df):,} filas")

    # Normalización canónica del canal (Sp→SP Digital, Mercado Libre Chile, etc.)
    from _canal_normalize import normalizar_columna_canal, normalizar_canal
    df = normalizar_columna_canal(df, col='canal')
    canales = [normalizar_canal(c) for c in canales]
    print(f"   Canales (normalizados): {canales}")

    desde_ts = pd.Timestamp(DESDE)
    hasta_ts = pd.Timestamp(HASTA)
    sel = df[(df['canal'].astype(str).str.strip().isin(canales))
             & (df['fecha_venta'] >= desde_ts)
             & (df['fecha_venta'] < hasta_ts)].copy()
    print(f"   Filtrado por canales y abril 2026: {len(sel):,} filas")

    if sel.empty:
        print("   Sin filas. Saliendo.")
        sys.exit(0)

    # Resumen por canal
    g = sel.groupby('canal').agg(
        filas=('venta_bruta', 'count'),
        venta=('venta_bruta', 'sum'),
        margen=('margen_front', 'sum'),
    ).reset_index().sort_values('venta', ascending=False)
    print("\n   Resumen Drive por canal:")
    print(g.to_string(index=False))
    print(f"\n   TOTAL: {len(sel):,} filas, venta ${sel['venta_bruta'].sum():,.0f}, margen ${sel['margen_front'].sum():,.0f}")

    # 2. Actualizar PARQUET local (PRIMERO porque es lo que ve el dashboard)
    print(f"\n[2] REPLACE en parquet histórico local...")
    df_hist = pd.read_parquet(PARQUET)
    df_hist['fecha_venta'] = pd.to_datetime(df_hist['fecha_venta'], errors='coerce')
    n_pre = len(df_hist)
    mask = ((df_hist['canal'].astype(str).str.strip().isin(canales))
            & (df_hist['fecha_venta'] >= desde_ts)
            & (df_hist['fecha_venta'] < hasta_ts))
    n_removed = int(mask.sum())
    venta_removed = float(df_hist.loc[mask, 'venta_bruta'].astype(float).sum())
    df_hist = df_hist[~mask]

    sel_p = sel[COLS_PARQUET].copy()
    sel_p['fecha_venta'] = sel_p['fecha_venta'].dt.strftime('%Y-%m-%d')
    df_hist['fecha_venta'] = df_hist['fecha_venta'].dt.strftime('%Y-%m-%d')
    df_final = pd.concat([df_hist[COLS_PARQUET], sel_p], ignore_index=True)
    df_final['_fv'] = pd.to_datetime(df_final['fecha_venta'])
    df_final = df_final.sort_values('_fv', kind='stable').drop(columns='_fv')
    df_final.to_parquet(PARQUET, index=False)
    n_post = len(df_final)
    venta_new = float(sel['venta_bruta'].sum())
    print(f"   Parquet pre: {n_pre:,} | quitadas {n_removed:,} ({venta_removed:,.0f}) | agregadas {len(sel):,} ({venta_new:,.0f})")
    print(f"   Parquet post: {n_post:,} filas (delta {n_post - n_pre:+,})")

    # 3. Actualizar Turso
    if args.skip_turso:
        print("\n[3] SKIP Turso (--skip-turso)")
    else:
        print(f"\n[3] REPLACE en Turso con libsql_client...")
        try:
            import libsql_client
            client = libsql_client.create_client_sync(
                url=os.environ['LIBSQL_URL'],
                auth_token=os.environ['LIBSQL_AUTH_TOKEN'],
            )
            # DELETE por canal en chunks (para no atragantar Turso)
            for canal in canales:
                try:
                    canal_esc = canal.replace("'", "''")
                    rs = client.execute(
                        f"DELETE FROM ventas WHERE canal = '{canal_esc}' "
                        f"AND fecha_venta >= '{DESDE}' AND fecha_venta < '{HASTA}'"
                    )
                    if rs.rows_affected > 0:
                        print(f"   {canal:24s}: -{rs.rows_affected:>5} filas")
                except Exception as e:
                    print(f"   {canal:24s}: error DELETE - {type(e).__name__}: {str(e)[:80]}")

            # INSERT en batches de 100
            print(f"\n   INSERT por batches de 100...")
            sel['fecha_venta_str'] = sel['fecha_venta'].dt.strftime('%Y-%m-%d')
            cols_csv = ','.join(COLS_DB)
            placeholders = '(' + ','.join('?' * len(COLS_DB)) + ')'

            inserted = 0
            batch_size = 100
            for i in range(0, len(sel), batch_size):
                chunk = sel.iloc[i:i + batch_size]
                all_ph = ','.join([placeholders] * len(chunk))
                sql = f"INSERT INTO ventas ({cols_csv}) VALUES {all_ph}"
                flat = []
                for _, row in chunk.iterrows():
                    for c in COLS_DB:
                        v = row['fecha_venta_str'] if c == 'fecha_venta' else row[c]
                        if pd.isna(v):
                            flat.append(None)
                        elif isinstance(v, (int, float)):
                            flat.append(float(v) if isinstance(v, float) else int(v))
                        else:
                            flat.append(str(v))
                rs = client.execute(sql, flat)
                inserted += rs.rows_affected
                if (i // batch_size + 1) % 10 == 0 or i + batch_size >= len(sel):
                    print(f"   batch {i // batch_size + 1}: total insertado {inserted:,}")
            print(f"   TOTAL insertado: {inserted:,} filas")
            client.close()
        except Exception as e:
            print(f"   [ERROR] Turso: {type(e).__name__}: {str(e)[:200]}")
            print(f"   Parquet ya actualizado — el dashboard mostrará data correcta.")

    # Log
    log_path = PROJECT_ROOT / 'data' / 'cmr' / f"canales_abril_drive_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    log = {
        'fecha_ejecucion': datetime.now().isoformat(timespec='seconds'),
        'canales': canales,
        'rango': {'desde': DESDE, 'hasta_excl': HASTA},
        'parquet': {
            'filas_pre': n_pre, 'filas_post': n_post,
            'filas_removidas': n_removed, 'filas_agregadas': len(sel),
            'venta_anterior': venta_removed, 'venta_nueva': venta_new,
            'delta_venta': venta_new - venta_removed,
        },
        'resumen_por_canal': g.to_dict(orient='records'),
    }
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] Log: {log_path}")
    print(f"\n=== RESUMEN FINAL ===")
    print(f"Parquet: {n_pre:,} → {n_post:,} ({n_post - n_pre:+,})")
    print(f"Venta abril (en estos canales): ${venta_removed:,.0f} → ${venta_new:,.0f} ({venta_new - venta_removed:+,.0f})")


if __name__ == '__main__':
    main()
