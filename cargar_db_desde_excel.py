#!/usr/bin/env python3
"""
Crea la Maestra SQLite y carga TODO el contenido de Raw ventas Y (4).xlsx
(histórico + abril ya extraído) en una sola pasada. Idempotente: si la DB
existe, la borra y reconstruye limpia.

Uso:
    python cargar_db_desde_excel.py
"""
import sys
import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd

PROJECT_ROOT = Path(__file__).parent
RAW_FILE = PROJECT_ROOT / 'data' / 'planillas' / 'Raw ventas Y (4).xlsx'
DB_PATH = PROJECT_ROOT / 'data' / 'db' / 'maestra_ventas.db'

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
    'Cantidad': 'cantidad', 'Venta bruta': 'venta_bruta',
    'Costo Unitario': 'costo_unitario', 'Costo Total': 'costo_total',
    'Margen Front': 'margen_front', 'Comision %': 'comision_pct',
    'Comisión': 'comision', 'Logística': 'logistica',
    'Marketing': 'marketing', 'Mg final': 'margen_final',
}


def crear_schema(conn: sqlite3.Connection):
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS ventas")
    c.execute("DROP TABLE IF EXISTS dim_productos")
    c.execute("DROP TABLE IF EXISTS dim_canales")
    c.execute("DROP TABLE IF EXISTS dim_bodegas")
    c.execute("DROP TABLE IF EXISTS dim_proveedores")
    c.execute("DROP TABLE IF EXISTS dim_marcas")
    c.execute("DROP TABLE IF EXISTS metadata_cargas")

    c.execute("""
        CREATE TABLE ventas (
            tipo_movimiento TEXT, bodega TEXT, documento TEXT, fecha_documento TEXT,
            pedido TEXT, estado_pedido TEXT, tipo_despacho TEXT, sku TEXT, canal TEXT,
            fecha_venta TEXT, hora_venta TEXT, producto TEXT,
            categoria_macro TEXT, categoria_padre TEXT, categoria_hijo TEXT, categoria_comercial TEXT,
            estado_sku TEXT, pack TEXT, marca TEXT, proveedor TEXT,
            tipo_marca TEXT, tipo_compra TEXT, tipo_negocio TEXT, kam TEXT,
            estado_canal TEXT, anio_venta INT, mes_venta INT, semana_venta INT,
            dia_semana TEXT, hora_venta_num INT,
            cantidad REAL, venta_bruta REAL, costo_unitario REAL, costo_total REAL,
            margen_front REAL, comision_pct REAL, comision REAL,
            logistica REAL, marketing REAL, margen_final REAL
        )
    """)
    c.execute("""
        CREATE TABLE dim_productos (
            sku TEXT PRIMARY KEY, producto TEXT, categoria_macro TEXT, categoria_padre TEXT,
            categoria_hijo TEXT, categoria_comercial TEXT, estado_sku TEXT, pack TEXT,
            marca TEXT, proveedor TEXT, tipo_marca TEXT, tipo_compra TEXT
        )
    """)
    c.execute("""
        CREATE TABLE dim_canales (
            canal TEXT PRIMARY KEY, tipo_negocio TEXT, estado_canal TEXT, kam TEXT
        )
    """)
    c.execute("CREATE TABLE dim_bodegas (bodega TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE dim_proveedores (proveedor TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE dim_marcas (marca TEXT PRIMARY KEY)")
    c.execute("""
        CREATE TABLE metadata_cargas (
            fecha_carga TEXT, fuente TEXT, filas_cargadas INT,
            fecha_min_datos TEXT, fecha_max_datos TEXT, tipo TEXT
        )
    """)
    # Índices
    c.execute("CREATE INDEX idx_ventas_fecha ON ventas(fecha_venta)")
    c.execute("CREATE INDEX idx_ventas_sku ON ventas(sku)")
    c.execute("CREATE INDEX idx_ventas_canal ON ventas(canal)")
    c.execute("CREATE INDEX idx_ventas_marca ON ventas(marca)")
    c.execute("CREATE INDEX idx_ventas_documento ON ventas(documento)")
    c.execute("CREATE INDEX idx_ventas_pedido ON ventas(pedido)")
    conn.commit()


def main():
    print("\n" + "="*100)
    print("CARGAR MAESTRA SQLite desde Excel RAW")
    print("="*100 + "\n")

    if not RAW_FILE.exists():
        print(f"[ERROR] No existe el Excel RAW: {RAW_FILE}")
        return 1

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"DB path: {DB_PATH}")
    print(f"Excel:   {RAW_FILE} ({RAW_FILE.stat().st_size/1024/1024:.1f} MB)\n")

    print("[1/4] Leyendo Excel RAW (puede tomar 1-2 min)...")
    df = pd.read_excel(RAW_FILE, sheet_name='RAW')
    print(f"      [OK] {len(df):,} filas, {len(df.columns)} columnas")

    print("\n[2/4] Creando schema SQLite...")
    conn = sqlite3.connect(str(DB_PATH))
    crear_schema(conn)
    print("      [OK] Schema creado")

    print("\n[3/4] Insertando datos...")
    df_db = df.rename(columns=RAW_TO_DB).copy()
    for col in ['fecha_documento', 'fecha_venta']:
        if col in df_db.columns:
            df_db[col] = pd.to_datetime(df_db[col], errors='coerce').dt.strftime('%Y-%m-%d')
    df_db = df_db.where(pd.notna(df_db), None)

    cols = [v for v in RAW_TO_DB.values() if v in df_db.columns]
    df_db[cols].to_sql('ventas', conn, if_exists='append', index=False, chunksize=5000)
    print(f"      [OK] {len(df_db):,} filas insertadas en `ventas`")

    # Dimensiones (INSERT OR IGNORE: si hay sku con atributos divergentes,
    # gana la primera versión y se ignoran las siguientes)
    print("\n      Poblando dimensiones...")
    cur = conn.cursor()

    def insert_ignore(table, cols, df_dim):
        if df_dim.empty:
            return 0
        rows = df_dim.where(pd.notna(df_dim), None).itertuples(index=False, name=None)
        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
        cur.executemany(sql, list(rows))
        return cur.rowcount

    dim_prod_cols = ['sku', 'producto', 'categoria_macro', 'categoria_padre',
                     'categoria_hijo', 'categoria_comercial', 'estado_sku',
                     'pack', 'marca', 'proveedor', 'tipo_marca', 'tipo_compra']
    dim_prod = df_db[dim_prod_cols].drop_duplicates(subset=['sku']).dropna(subset=['sku'])
    n = insert_ignore('dim_productos', dim_prod_cols, dim_prod)
    print(f"        +{n:,} productos")

    dim_can = df_db[['canal', 'tipo_negocio', 'estado_canal', 'kam']].drop_duplicates(subset=['canal']).dropna(subset=['canal'])
    n = insert_ignore('dim_canales', ['canal', 'tipo_negocio', 'estado_canal', 'kam'], dim_can)
    print(f"        +{n:,} canales")

    dim_bod = df_db[['bodega']].drop_duplicates().dropna()
    n = insert_ignore('dim_bodegas', ['bodega'], dim_bod)
    print(f"        +{n:,} bodegas")

    dim_prov = df_db[['proveedor']].drop_duplicates().dropna()
    n = insert_ignore('dim_proveedores', ['proveedor'], dim_prov)
    print(f"        +{n:,} proveedores")

    dim_mar = df_db[['marca']].drop_duplicates().dropna()
    n = insert_ignore('dim_marcas', ['marca'], dim_mar)
    print(f"        +{n:,} marcas")

    # Metadata
    fecha_min = df_db['fecha_venta'].min()
    fecha_max = df_db['fecha_venta'].max()
    conn.execute("""
        INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), f'Excel completo ({RAW_FILE.name})', len(df_db), fecha_min, fecha_max, 'rebuild_full'))
    conn.commit()

    print("\n[4/4] Resumen final:")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(fecha_venta), MAX(fecha_venta), SUM(venta_bruta), SUM(margen_final) FROM ventas")
    n, fmin, fmax, vt, mt = cur.fetchone()
    pct = (mt/vt*100) if vt else 0
    print(f"      Filas:           {n:,}")
    print(f"      Rango:           {fmin} -> {fmax}")
    print(f"      Venta NETA:      ${vt:,.0f}")
    print(f"      Margen Final:    ${mt:,.0f}")
    print(f"      % Margen:        {pct:.1f}%")
    print(f"      DB size:         {DB_PATH.stat().st_size/1024/1024:.1f} MB")
    conn.close()

    print("\n" + "="*100)
    print("[OK] MAESTRA SQLite RECONSTRUIDA")
    print("="*100 + "\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
