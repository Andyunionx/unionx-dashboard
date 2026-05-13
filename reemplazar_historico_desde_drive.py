#!/usr/bin/env python3
"""
Reemplaza el parquet histórico pre-CUTOFF con la pestaña RAW del Drive maestro.

Decisión de negocio: el Drive es la fuente de verdad operacional (Odoo + cargas
manuales del equipo administrativo). El parquet local debe coincidir con el
Drive en todo el período cerrado (pre-CUTOFF_HISTORICO).

Behaviour:
- Lee `data/historico/ventas_historico.parquet` existente
- Descarga el xlsx del Drive (pestaña 'RAW', 40 cols + Venta Neta calculada)
- Filtra Drive a `fecha_venta < CUTOFF_HISTORICO`
- Filtra parquet local a `fecha_venta >= CUTOFF_HISTORICO` (preserva abril+ congelado)
- Concatena ambos y guarda

Uso: python reemplazar_historico_desde_drive.py [--cutoff YYYY-MM-DD]
"""
import argparse
import io
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
PARQUET_PATH = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
SHARED_PATH = PROJECT_ROOT / 'views' / 'shared.py'
CREDENTIALS = PROJECT_ROOT / 'credentials.json'

# El xlsx maestro. File ID dado por el user (mismo que usamos en la auditoría).
DRIVE_FILE_ID = '1K11y6icDm9M3X3glGUVCOe4HsbpWpEBm'

# Mapping nombres Excel → snake_case del parquet
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

# Orden esperado del parquet (incluye venta_neta al final)
PARQUET_COLS = [
    'tipo_movimiento', 'bodega', 'documento', 'fecha_documento', 'pedido', 'estado_pedido',
    'tipo_despacho', 'sku', 'canal', 'fecha_venta', 'hora_venta', 'producto',
    'categoria_macro', 'categoria_padre', 'categoria_hijo', 'categoria_comercial',
    'estado_sku', 'pack', 'marca', 'proveedor', 'tipo_marca', 'tipo_compra', 'tipo_negocio',
    'kam', 'estado_canal', 'anio_venta', 'mes_venta', 'semana_venta', 'dia_semana',
    'hora_venta_num', 'cantidad', 'venta_bruta', 'costo_unitario', 'costo_total',
    'margen_front', 'comision_pct', 'comision', 'logistica', 'marketing', 'margen_final',
    'venta_neta',
]


def descargar_xlsx_de_drive(file_id: str) -> bytes:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    scopes = ['https://www.googleapis.com/auth/drive.readonly']
    creds = Credentials.from_service_account_file(str(CREDENTIALS), scopes=scopes)
    drive = build('drive', 'v3', credentials=creds)

    meta = drive.files().get(fileId=file_id, fields='name,size,mimeType').execute()
    size_mb = int(meta.get('size', 0)) / 1e6
    print(f"[1] Descargando {meta.get('name')} ({size_mb:.1f} MB)...")

    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f"   {int(status.progress() * 100)}%")
    buf.seek(0)
    return buf.read()


def normalizar_canal(canal):
    """Aplica reglas de fusión y casing oficial."""
    if pd.isna(canal):
        return canal
    s = str(canal).strip()
    # Fusión Sp Digital → SP Digital
    if s.lower() == 'sp digital':
        return 'SP Digital'
    return s


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cutoff', default=None,
                        help='Fecha de corte YYYY-MM-DD (default: lee CUTOFF_HISTORICO de views/shared.py)')
    args = parser.parse_args()

    # 1. Resolver cutoff
    if args.cutoff:
        cutoff = args.cutoff
    else:
        m = re.search(r"CUTOFF_HISTORICO\s*=\s*['\"](\d{4}-\d{2}-\d{2})['\"]", SHARED_PATH.read_text(encoding='utf-8'))
        if not m:
            print("[ERROR] No pude leer CUTOFF_HISTORICO de views/shared.py")
            sys.exit(1)
        cutoff = m.group(1)
    print(f"Cutoff aplicado: {cutoff} (fechas < cutoff vienen de Drive; >= cutoff se preserva del parquet local)")

    # 2. Descargar Drive
    xlsx_bytes = descargar_xlsx_de_drive(DRIVE_FILE_ID)

    print("[2] Leyendo pestaña RAW...")
    df_drv = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name='RAW')
    df_drv.columns = [DRIVE_TO_DB.get(c, c) for c in df_drv.columns]
    print(f"   Filas Drive (todas): {len(df_drv):,}")

    # 3. Verificar columnas esperadas
    cols_falta = [c for c in PARQUET_COLS if c not in df_drv.columns and c != 'venta_neta']
    if cols_falta:
        print(f"[WARN] Cols faltantes en Drive: {cols_falta}")
        for c in cols_falta:
            df_drv[c] = '' if c in ('tipo_movimiento', 'bodega', 'sku', 'canal', 'producto') else 0

    # 4. Casteos numéricos + fecha
    df_drv['fecha_venta'] = pd.to_datetime(df_drv['fecha_venta'], errors='coerce')
    for c in ('anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num'):
        if c in df_drv.columns:
            df_drv[c] = pd.to_numeric(df_drv[c], errors='coerce').fillna(0).astype('int64')
    for c in ('cantidad', 'venta_bruta', 'costo_unitario', 'costo_total',
              'margen_front', 'comision_pct', 'comision', 'logistica', 'marketing', 'margen_final'):
        if c in df_drv.columns:
            df_drv[c] = pd.to_numeric(df_drv[c], errors='coerce').fillna(0.0)

    # 5. Calcular venta_neta (= venta_bruta / 1.19 para mantener compatibilidad histórica)
    if 'venta_neta' not in df_drv.columns:
        df_drv['venta_neta'] = (df_drv['venta_bruta'] / 1.19).round(2)

    # 6. Normalizar canal (Sp Digital → SP Digital, etc.)
    df_drv['canal'] = df_drv['canal'].apply(normalizar_canal)

    # 7. Filtrar Drive a fecha_venta < cutoff
    cutoff_ts = pd.Timestamp(cutoff)
    df_drv_pre = df_drv[df_drv['fecha_venta'] < cutoff_ts].copy()
    print(f"[3] Filas Drive pre-cutoff (< {cutoff}): {len(df_drv_pre):,}")

    # 8. Cargar parquet local y filtrar a >= cutoff (preservar)
    df_loc = pd.read_parquet(PARQUET_PATH)
    df_loc['fecha_venta'] = pd.to_datetime(df_loc['fecha_venta'], errors='coerce')
    df_loc_post = df_loc[df_loc['fecha_venta'] >= cutoff_ts].copy()
    print(f"[4] Filas locales post-cutoff (>= {cutoff}, preservadas): {len(df_loc_post):,}")

    # 9. Coerce todas las cols TEXT a string para evitar errores Arrow por tipos mixtos
    cols_texto = [c for c in PARQUET_COLS if c not in (
        'anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num',
        'cantidad', 'venta_bruta', 'costo_unitario', 'costo_total',
        'margen_front', 'comision_pct', 'comision', 'logistica',
        'marketing', 'margen_final', 'venta_neta', 'fecha_venta',
    )]
    for df_x in (df_drv_pre, df_loc_post):
        for c in cols_texto:
            if c in df_x.columns:
                df_x[c] = df_x[c].astype('object').where(df_x[c].notna(), '').astype(str).replace('nan', '')

    # 10. Concat + sort
    df_final = pd.concat([df_drv_pre[PARQUET_COLS], df_loc_post[PARQUET_COLS]], ignore_index=True)
    df_final = df_final.sort_values('fecha_venta', kind='stable')

    print(f"[5] Total final: {len(df_final):,} filas")

    # 10. Stats por mes (validación)
    df_final['_mes'] = df_final['fecha_venta'].dt.to_period('M').astype(str)
    print("\n   Filas por mes (top 5 últimos):")
    print(df_final.groupby('_mes').size().tail(8).to_string())
    df_final = df_final.drop(columns='_mes')

    # 11. Formato fecha a string para parquet (compatible con el resto del código)
    df_final['fecha_venta'] = df_final['fecha_venta'].dt.strftime('%Y-%m-%d')

    # 12. Guardar
    df_final[PARQUET_COLS].to_parquet(PARQUET_PATH, index=False)
    size_mb = PARQUET_PATH.stat().st_size / 1e6
    print(f"\n[OK] Guardado {PARQUET_PATH} ({size_mb:.1f} MB)")


if __name__ == '__main__':
    main()
