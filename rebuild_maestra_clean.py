#!/usr/bin/env python3
"""
Reconstruye la base de datos Maestra limpiamente:
1. Carga Raw ventas Y (4).xlsx filtrando SOLO datos pre-abril
2. Crea DB fresca
3. Carga April 1-17 desde Odoo (sin duplicar)
"""
import sys
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient
from app.services.ventas_service import VentasService
from app.config import Config

# Paths
DB_LOCAL = Path.home() / 'Desktop' / 'finanzas-unionx-app' / 'maestra_ventas.db'
DB_PROJECT = PROJECT_ROOT / 'data' / 'db' / 'maestra_ventas.db'
RAW_FILE = PROJECT_ROOT / 'data' / 'planillas' / 'Raw ventas Y (4).xlsx'

def create_db_schema(db_path):
    """Crea el schema de la base de datos."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Tabla principal ventas
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ventas (
        tipo_movimiento TEXT,
        bodega TEXT,
        documento TEXT,
        fecha_documento TEXT,
        pedido TEXT,
        estado_pedido TEXT,
        tipo_despacho TEXT,
        sku TEXT,
        canal TEXT,
        fecha_venta TEXT,
        hora_venta TEXT,
        producto TEXT,
        categoria_macro TEXT,
        categoria_padre TEXT,
        categoria_hijo TEXT,
        categoria_comercial TEXT,
        estado_sku TEXT,
        pack TEXT,
        marca TEXT,
        proveedor TEXT,
        tipo_marca TEXT,
        tipo_compra TEXT,
        tipo_negocio TEXT,
        kam TEXT,
        estado_canal TEXT,
        anio_venta INT,
        mes_venta INT,
        semana_venta INT,
        dia_semana TEXT,
        hora_venta_num INT,
        cantidad REAL,
        venta_bruta REAL,
        costo_unitario REAL,
        costo_total REAL,
        margen_front REAL,
        comision_pct REAL,
        comision REAL,
        logistica REAL,
        marketing REAL,
        margen_final REAL
    )
    """)

    # Tablas dimensión
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dim_productos (
        sku TEXT PRIMARY KEY,
        producto TEXT,
        categoria_macro TEXT,
        categoria_padre TEXT,
        categoria_hijo TEXT,
        categoria_comercial TEXT,
        estado_sku TEXT,
        pack TEXT,
        marca TEXT,
        proveedor TEXT,
        tipo_marca TEXT,
        tipo_compra TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dim_canales (
        canal TEXT PRIMARY KEY,
        tipo_negocio TEXT,
        estado_canal TEXT,
        kam TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dim_bodegas (
        bodega TEXT PRIMARY KEY
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dim_proveedores (
        proveedor TEXT PRIMARY KEY
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dim_marcas (
        marca TEXT PRIMARY KEY
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS metadata_cargas (
        fecha_carga TEXT,
        fuente TEXT,
        filas_cargadas INT,
        fecha_min_datos TEXT,
        fecha_max_datos TEXT,
        tipo TEXT
    )
    """)

    conn.commit()
    conn.close()

def load_historical_data(db_path):
    """Carga datos históricos pre-abril desde Raw ventas Y (4).xlsx"""
    print("\n[1] Cargando datos históricos (pre-abril)...")
    print(f"    Leyendo: {RAW_FILE.name}")

    df = pd.read_excel(RAW_FILE, sheet_name='RAW')
    print(f"    Total en archivo: {len(df):,} filas")

    # Filtrar solo datos antes de April 1
    df['Fecha Venta'] = pd.to_datetime(df['Fecha Venta'], errors='coerce')
    df_historical = df[df['Fecha Venta'] < '2026-04-01'].copy()

    print(f"    Rango original: {df['Fecha Venta'].min().date()} a {df['Fecha Venta'].max().date()}")
    print(f"    Filas pre-abril: {len(df_historical):,}")
    print(f"    Venta pre-abril: ${df_historical['Venta bruta'].sum():,.0f}")

    # Insertar en DB
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
        'Costo Unitario': 'costo_unitario',
        'Costo Total': 'costo_total',
        'Margen Front': 'margen_front',
        'Comision %': 'comision_pct',
        'Comisión': 'comision',
        'Logística': 'logistica',
        'Marketing': 'marketing',
        'Mg final': 'margen_final',
    }

    df_clean = df_historical.rename(columns=RAW_TO_DB).copy()
    for col in ['fecha_documento', 'fecha_venta']:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].dt.strftime('%Y-%m-%d')

    df_clean = df_clean.where(pd.notna(df_clean), None)

    conn = sqlite3.connect(str(db_path))
    ventas_cols = [v for v in RAW_TO_DB.values()]
    cols_disponibles = [c for c in ventas_cols if c in df_clean.columns]
    df_clean[cols_disponibles].to_sql('ventas', conn, if_exists='append', index=False, chunksize=1000)

    # Registrar carga
    cursor = conn.cursor()
    fecha_min = df_clean['fecha_venta'].min()
    fecha_max = df_clean['fecha_venta'].max()
    cursor.execute("""
        INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), 'Excel histórico (Raw ventas Y)', len(df_clean), fecha_min, fecha_max, 'historical'))

    conn.commit()
    conn.close()

    print(f"    [OK] Datos históricos cargados\n")

def load_april_data(db_path):
    """Carga datos de April 1-17 desde Odoo"""
    print("[2] Cargando datos de Odoo (April 1-17)...")

    try:
        odoo = OdooClient(
            url=Config.ODOO_URL,
            db=Config.ODOO_DB,
            username=Config.ODOO_USER,
            password=Config.ODOO_PASSWORD
        )
        service = VentasService(odoo, Config.PLANILLAS_DIR)

        df_april = service.extract_to_raw_format(
            "2026-04-01 00:00:00", "2026-04-17 23:59:59",
            progress_callback=lambda pct, label: print(f"    {pct}% - {label}")
        )

        if len(df_april) == 0:
            print("    [WARN] No hay datos de Odoo para este periodo")
            return

        print(f"\n    Filas de Odoo: {len(df_april):,}")
        print(f"    Venta: ${df_april['Venta bruta'].sum():,.0f}")

        # Insertar en DB
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
            'Costo Unitario': 'costo_unitario',
            'Costo Total': 'costo_total',
            'Margen Front': 'margen_front',
            'Comision %': 'comision_pct',
            'Comisión': 'comision',
            'Logística': 'logistica',
            'Marketing': 'marketing',
            'Mg final': 'margen_final',
        }

        df_clean = df_april.rename(columns=RAW_TO_DB).copy()
        for col in ['fecha_documento', 'fecha_venta']:
            if col in df_clean.columns:
                df_clean[col] = df_clean[col].dt.strftime('%Y-%m-%d')

        df_clean = df_clean.where(pd.notna(df_clean), None)

        conn = sqlite3.connect(str(db_path))
        ventas_cols = [v for v in RAW_TO_DB.values()]
        cols_disponibles = [c for c in ventas_cols if c in df_clean.columns]
        df_clean[cols_disponibles].to_sql('ventas', conn, if_exists='append', index=False, chunksize=1000)

        # Registrar carga
        cursor = conn.cursor()
        fecha_min = df_clean['fecha_venta'].min()
        fecha_max = df_clean['fecha_venta'].max()
        cursor.execute("""
            INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), 'Odoo (extract_to_raw_format)', len(df_clean), fecha_min, fecha_max, 'incremental_odoo'))

        conn.commit()
        conn.close()

        print(f"    [OK] Datos de Odoo cargados\n")

    except Exception as e:
        print(f"    [ERROR]: {str(e)}")
        import traceback
        traceback.print_exc()

def verify_data(db_path):
    """Verifica que los datos estén correctos"""
    print("[3] Verificando integridad...")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM ventas")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT ROUND(SUM(venta_bruta), 0) FROM ventas WHERE fecha_venta BETWEEN '2026-04-01' AND '2026-04-17'")
    april_venta = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ventas WHERE fecha_venta BETWEEN '2026-04-01' AND '2026-04-17'")
    april_rows = cursor.fetchone()[0]

    cursor.execute("SELECT MIN(fecha_venta), MAX(fecha_venta) FROM ventas")
    fecha_min, fecha_max = cursor.fetchone()

    conn.close()

    print(f"    Total filas: {total:,}")
    print(f"    Rango: {fecha_min} a {fecha_max}")
    print(f"    April 1-17: {april_rows:,} filas | ${april_venta:,} venta")
    print(f"    [{"OK" if april_venta and april_venta < 250_000_000 else "WARN"}]\n")

if __name__ == '__main__':
    print("="*100)
    print("REBUILD MAESTRA VENTAS — LIMPIO (Pre-abril + Odoo abril)")
    print("="*100)

    # Eliminar DBs antiguos
    print("\n[0] Eliminando databases antiguos...")
    for db in [DB_LOCAL, DB_PROJECT]:
        if db.exists():
            db.unlink()
            print(f"    Eliminado: {db.name}")

    # Crear DB fresca
    print("\n    Creando schema...")
    create_db_schema(DB_LOCAL)
    if DB_PROJECT.exists() or not DB_LOCAL.exists():
        create_db_schema(DB_PROJECT)

    # Cargar datos
    load_historical_data(DB_LOCAL)
    load_april_data(DB_LOCAL)

    # Sincronizar a Google Drive si existe
    if DB_PROJECT.exists():
        print("[3] Sincronizando a Google Drive...")
        import shutil
        shutil.copy(str(DB_LOCAL), str(DB_PROJECT))
        print(f"    [OK] DB sincronizada\n")

    # Verificar
    verify_data(DB_LOCAL)

    print("="*100)
    print("[OK] REBUILD COMPLETADO")
    print("="*100)
