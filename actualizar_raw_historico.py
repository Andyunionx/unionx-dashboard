#!/usr/bin/env python3
"""
Script para extraer ventas de Odoo en formato RAW (40 columnas) e insertar
directamente en la Maestra de Ventas (SQLite).

Uso:
    python actualizar_raw_historico.py                                        # Datos de hoy
    python actualizar_raw_historico.py --periodo "2026-04-01" "2026-04-15"    # Rango custom
    python actualizar_raw_historico.py --no-db                                # Solo Excel, sin DB
"""
import sys
import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd

# Backend
backend_path = Path(__file__).parent / 'finanzas-unionx' / 'backend'
sys.path.insert(0, str(backend_path))
sys.path.insert(0, str(Path(__file__).parent))

from app.core.odoo_client import OdooClient
from app.services.ventas_service import VentasService
from app.config import Config
from db_client import get_connection

# Paths
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / 'data' / 'db' / 'maestra_ventas.db'
DB_LOCAL = Path.home() / 'Desktop' / 'finanzas-unionx-app' / 'maestra_ventas.db'
RAW_FILE = PROJECT_ROOT / 'data' / 'planillas' / 'Raw ventas Y (4).xlsx'

# Mapeo: nombre RAW (Odoo) -> nombre DB (SQLite)
RAW_TO_DB = {
    'Tipo Movimiento': 'tipo_movimiento',
    'Bodega': 'bodega',
    'Documento': 'documento',
    'Fecha Documento': 'fecha_documento',
    'Pedido': 'pedido',
    'Estado Pedido': 'estado_pedido',
    'Tipo Despacho': 'tipo_despacho',
    'SKU': 'sku',
    'Canal': 'canal',
    'Fecha Venta': 'fecha_venta',
    'Hora Venta': 'hora_venta',
    'Producto': 'producto',
    'Categoría macro': 'categoria_macro',
    'Categoría padre': 'categoria_padre',
    'Categoría hijo': 'categoria_hijo',
    'Categoría comercial': 'categoria_comercial',
    'Estado SKU': 'estado_sku',
    'Pack': 'pack',
    'Marca': 'marca',
    'Proveedor': 'proveedor',
    'Tipo Marca': 'tipo_marca',
    'Tipo Compra': 'tipo_compra',
    'Tipo Negocio': 'tipo_negocio',
    'KAM': 'kam',
    'Estado Canal': 'estado_canal',
    'Año venta': 'anio_venta',
    'Mes venta': 'mes_venta',
    'Semana venta': 'semana_venta',
    'Día semana': 'dia_semana',
    'Hora venta': 'hora_venta_num',
    'Cantidad': 'cantidad',
    'Venta bruta': 'venta_bruta',
    'Venta Neta': 'venta_neta',
    'Costo Unitario': 'costo_unitario',
    'Costo Total': 'costo_total',
    'Margen Front': 'margen_front',
    'Comision %': 'comision_pct',
    'Comisión': 'comision',
    'Logística': 'logistica',
    'Marketing': 'marketing',
    'Mg final': 'margen_final',
    'Pedido Marketplace': 'pedido_marketplace',
    'Ref Cliente': 'client_order_ref',
}


def _data_quality_checks(df: pd.DataFrame) -> list[str]:
    """Valida data quality. Devuelve lista de warnings (no bloquea)."""
    warnings = []
    n = len(df)
    if n == 0:
        warnings.append("DataFrame vacío")
        return warnings

    # 1. Fechas no futuras
    if 'fecha_venta' in df.columns:
        hoy = pd.Timestamp.now().normalize()
        futuras = pd.to_datetime(df['fecha_venta'], errors='coerce') > hoy
        n_futuras = int(futuras.sum())
        if n_futuras > 0:
            warnings.append(f"{n_futuras} filas con fecha_venta futura")

    # 2. SKU obligatorio
    if 'sku' in df.columns:
        n_sin_sku = df['sku'].isna().sum() + (df['sku'] == '').sum()
        if n_sin_sku > 0:
            warnings.append(f"{n_sin_sku} filas sin SKU")

    # 3. Venta bruta debería ser > 0 (excepto NCs que son negativas)
    if 'venta_bruta' in df.columns:
        n_cero = (df['venta_bruta'].fillna(0) == 0).sum()
        pct_cero = n_cero / n * 100
        if pct_cero > 5:
            warnings.append(f"{pct_cero:.1f}% filas con venta_bruta=0 ({n_cero}/{n})")

    # 4. Canal vacío (no debería haber)
    if 'canal' in df.columns:
        n_sin_canal = df['canal'].isna().sum() + (df['canal'] == '').sum()
        if n_sin_canal > 0:
            warnings.append(f"{n_sin_canal} filas sin canal")

    # 5. Cantidad lógica
    if 'cantidad' in df.columns:
        n_cant_cero = (df['cantidad'].fillna(0) == 0).sum()
        if n_cant_cero > n * 0.1:
            warnings.append(f"{n_cant_cero} filas con cantidad=0 (>10%)")

    return warnings


def insertar_en_maestra(df_raw, db_path):
    """Inserta DataFrame RAW en la Maestra (SQLite local o Turso cloud, vía db_client)."""
    df = df_raw.rename(columns=RAW_TO_DB).copy()

    # Convertir fechas a string ISO
    for col in ['fecha_documento', 'fecha_venta']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')

    df = df.where(pd.notna(df), None)

    # ===== DATA QUALITY CHECKS =====
    warnings = _data_quality_checks(df)
    if warnings:
        print("\n⚠️  Data Quality warnings:")
        for w in warnings:
            print(f"   - {w}")
        print()

    conn = get_connection(db_path)

    # IDEMPOTENTE: borrar filas previas del mismo período antes de insertar
    fmin_in = df['fecha_venta'].min()
    fmax_in = df['fecha_venta'].max()
    if fmin_in and fmax_in:
        cur_del = conn.cursor()
        cur_del.execute(
            "DELETE FROM ventas WHERE fecha_venta BETWEEN ? AND ?",
            (fmin_in, fmax_in)
        )
        n_del = cur_del.rowcount or 0
        if n_del > 0:
            print(f"      [DEDUP] Borradas {n_del:,} filas previas del período")
        conn.commit()

    # Columnas de la tabla ventas (manual multi-row INSERT, compatible con libsql)
    ventas_cols = [v for v in RAW_TO_DB.values()]
    cols_disponibles = [c for c in ventas_cols if c in df.columns]
    df_v = df[cols_disponibles]
    rows_v = list(df_v.itertuples(index=False, name=None))
    n_total = len(rows_v)
    chunk_size = 200  # multi-row INSERT en chunks

    if rows_v:
        n_cols = len(cols_disponibles)
        cols_csv = ",".join(cols_disponibles)
        for i in range(0, n_total, chunk_size):
            batch = rows_v[i:i + chunk_size]
            row_ph = "(" + ",".join(["?"] * n_cols) + ")"
            all_ph = ",".join([row_ph] * len(batch))
            sql = f"INSERT INTO ventas ({cols_csv}) VALUES {all_ph}"
            flat = [v for r in batch for v in r]
            conn.execute(sql, flat)
        conn.commit()

    # Dimensiones nuevas (INSERT OR IGNORE para evitar duplicados)
    cursor = conn.cursor()

    def _insert_ignore(table, cols, df_dim):
        if df_dim.empty:
            return 0
        rows = list(df_dim.where(pd.notna(df_dim), None).itertuples(index=False, name=None))
        if not rows:
            return 0
        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
        # Insertar fila por fila (volúmenes pequeños en dim tables)
        n_inserted = 0
        for r in rows:
            try:
                conn.execute(sql, list(r))
                n_inserted += 1
            except Exception:
                pass
        conn.commit()
        return n_inserted

    prod_cols = ['sku', 'producto', 'categoria_macro', 'categoria_padre',
                 'categoria_hijo', 'categoria_comercial', 'estado_sku',
                 'pack', 'marca', 'proveedor', 'tipo_marca', 'tipo_compra']
    nuevos = df[prod_cols].drop_duplicates(subset=['sku']).dropna(subset=['sku'])
    n_p = _insert_ignore('dim_productos', prod_cols, nuevos)
    if n_p > 0:
        print(f"      +{n_p} SKUs nuevos")

    can_cols = ['canal', 'tipo_negocio', 'estado_canal', 'kam']
    nuevos_c = df[can_cols].drop_duplicates(subset=['canal']).dropna(subset=['canal'])
    n_c = _insert_ignore('dim_canales', can_cols, nuevos_c)
    if n_c > 0:
        print(f"      +{n_c} canales nuevos")

    # Registrar carga
    fecha_min = df['fecha_venta'].min()
    fecha_max = df['fecha_venta'].max()
    conn.execute("""
        INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [datetime.now().isoformat(), 'Odoo (extract_to_raw_format)', len(df), fecha_min, fecha_max, 'incremental_odoo'])
    conn.commit()

    total_row = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()
    total = total_row[0] if total_row else 0
    conn.close()
    return total


def actualizar_raw(periodo_inicio=None, periodo_fin=None, skip_db=False):
    """Extrae desde Odoo e inserta en Maestra SQLite + Excel."""

    if not periodo_inicio:
        hoy = datetime.now()
        periodo_inicio = f"{hoy.strftime('%Y-%m-%d')} 00:00:00"
        periodo_fin = f"{hoy.strftime('%Y-%m-%d')} 23:59:59"

    print("\n" + "="*100)
    print("ACTUALIZADOR RAW — Odoo -> Maestra SQLite")
    print("="*100 + "\n")
    print(f"Periodo: {periodo_inicio} a {periodo_fin}\n")

    try:
        # [1] Conectar Odoo
        print("[1/6] Conectando a Odoo...")
        odoo = OdooClient(
            url=Config.ODOO_URL,
            db=Config.ODOO_DB,
            username=Config.ODOO_USER,
            password=Config.ODOO_PASSWORD
        )
        print("      [OK] Conectado\n")

        # [2] Servicio
        print("[2/6] Inicializando VentasService...")
        service = VentasService(odoo, Config.PLANILLAS_DIR)
        print("      [OK] Servicio listo\n")

        # [3] Extraer RAW
        print("[3/6] Extrayendo datos en FORMATO RAW...\n")
        df_raw = service.extract_to_raw_format(
            periodo_inicio, periodo_fin,
            progress_callback=lambda pct, label: print(f"      {pct}% - {label}")
        )

        if len(df_raw) == 0:
            print("\n[INFO] No hay datos nuevos para este periodo")
            return None

        print(f"\n      [OK] {len(df_raw):,} filas extraidas")

        # [4] Insertar en Maestra SQLite
        if not skip_db:
            print(f"\n[4/6] Insertando en Maestra SQLite...")
            # Elegir DB (local si existe, sino Google Drive)
            db = DB_LOCAL if DB_LOCAL.exists() else DB_PATH
            print(f"      DB: {db}")

            if db.exists():
                total = insertar_en_maestra(df_raw, db)
                print(f"      [OK] +{len(df_raw):,} filas -> Total DB: {total:,}")

                # Si usamos local, también actualizar la de Google Drive
                if db == DB_LOCAL and DB_PATH.exists():
                    print(f"      Sincronizando a Google Drive...")
                    total_gd = insertar_en_maestra(df_raw, DB_PATH)
                    print(f"      [OK] Google Drive sincronizado: {total_gd:,} filas")
            else:
                print(f"      [WARN] DB no existe. Ejecuta primero crear_maestra_ventas.py")
        else:
            print("\n[4/6] Saltando DB (--no-db)")

        # [5] Actualizar Excel RAW (idempotente: filtra el período antes de concatenar)
        print(f"\n[5/6] Actualizando Excel RAW...")
        if RAW_FILE.exists():
            df_existente = pd.read_excel(RAW_FILE, sheet_name='RAW')
            df_existente['Fecha Venta'] = pd.to_datetime(df_existente['Fecha Venta'], errors='coerce')
            ini_dt = pd.to_datetime(periodo_inicio).date()
            fin_dt = pd.to_datetime(periodo_fin).date()
            mask_period = (df_existente['Fecha Venta'].dt.date >= ini_dt) & (df_existente['Fecha Venta'].dt.date <= fin_dt)
            n_excluidas = int(mask_period.sum())
            df_existente = df_existente[~mask_period]
            if n_excluidas > 0:
                print(f"      [DEDUP] Excluidas {n_excluidas:,} filas previas del período en Excel")
            df_completo = pd.concat([df_existente, df_raw], ignore_index=True)
            print(f"      Existentes (post-dedup): {len(df_existente):,} + Nuevas: {len(df_raw):,} = {len(df_completo):,}")
        else:
            df_completo = df_raw
            print(f"      Creando nuevo archivo RAW")

        with pd.ExcelWriter(RAW_FILE, engine='openpyxl') as writer:
            df_completo.to_excel(writer, sheet_name='RAW', index=False)
        print(f"      [OK] {RAW_FILE.name} ({RAW_FILE.stat().st_size / 1024 / 1024:.1f} MB)")

        # [6] Resumen
        venta_total = df_raw['Venta bruta'].sum()
        margen_total = df_raw['Mg final'].sum()

        print(f"\n[6/6] Resumen:")
        print(f"      Filas: {len(df_raw):,}")
        print(f"      Canales: {df_raw['Canal'].nunique()}")
        print(f"      SKUs: {df_raw['SKU'].nunique()}")
        print(f"      Venta (NETA): ${venta_total:,.0f}")
        print(f"      Margen Final: ${margen_total:,.0f}")
        if venta_total > 0:
            print(f"      % Margen: {(margen_total / venta_total * 100):.1f}%")

        print("\n" + "="*100)
        print("[OK] ACTUALIZACION COMPLETADA — Odoo -> SQLite + Excel")
        print("="*100 + "\n")

        return df_raw

    except Exception as e:
        print(f"\n[ERROR]: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Extrae ventas de Odoo -> Maestra SQLite + Excel')
    parser.add_argument('--periodo', nargs=2, metavar=('INICIO', 'FIN'),
                       help='Periodo (ej: "2026-04-01 00:00:00" "2026-04-30 23:59:59")')
    parser.add_argument('--no-db', action='store_true',
                       help='Solo actualizar Excel, no insertar en DB')

    args = parser.parse_args()

    if args.periodo:
        actualizar_raw(args.periodo[0], args.periodo[1], skip_db=args.no_db)
    else:
        actualizar_raw(skip_db=args.no_db)
