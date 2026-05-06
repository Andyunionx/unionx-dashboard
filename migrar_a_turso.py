"""
Migra el SQLite local (data/db/maestra_ventas.db) a Turso libSQL.
Setup previo: crear DB en turso.tech y obtener URL + AUTH_TOKEN.

Uso:
    set LIBSQL_URL=libsql://tu-db.turso.io
    set LIBSQL_AUTH_TOKEN=eyJ...
    python migrar_a_turso.py

Tiempo aprox: 10-20 min para ~377K filas (depende de la red).
"""
import os
import sqlite3
import sys
import time
from pathlib import Path

import libsql_client

LOCAL_DB = Path(__file__).parent / 'data' / 'db' / 'maestra_ventas.db'
URL = os.environ.get('LIBSQL_URL')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')

if not URL:
    print("[ERROR] LIBSQL_URL no está seteado. Setear con:")
    print('  set LIBSQL_URL=libsql://...')
    print('  set LIBSQL_AUTH_TOKEN=eyJ...')
    sys.exit(1)

print(f"=== Migración SQLite → Turso ===")
print(f"  Local: {LOCAL_DB}")
print(f"  Remote: {URL}")
print()

if not LOCAL_DB.exists():
    print(f"[ERROR] No existe {LOCAL_DB}")
    sys.exit(1)

local = sqlite3.connect(str(LOCAL_DB))
local.row_factory = sqlite3.Row
remote = libsql_client.create_client_sync(url=URL, auth_token=TOKEN)

# 1. Crear schema en remoto (basado en cargar_db_desde_excel.py)
print("[1/3] Creando schema en Turso...")
schema_sqls = [
    "DROP TABLE IF EXISTS ventas",
    "DROP TABLE IF EXISTS dim_productos",
    "DROP TABLE IF EXISTS dim_canales",
    "DROP TABLE IF EXISTS dim_bodegas",
    "DROP TABLE IF EXISTS dim_proveedores",
    "DROP TABLE IF EXISTS dim_marcas",
    "DROP TABLE IF EXISTS metadata_cargas",
    """CREATE TABLE ventas (
        tipo_movimiento TEXT, bodega TEXT, documento TEXT, fecha_documento TEXT,
        pedido TEXT, estado_pedido TEXT, tipo_despacho TEXT, sku TEXT, canal TEXT,
        fecha_venta TEXT, hora_venta TEXT, producto TEXT,
        categoria_macro TEXT, categoria_padre TEXT, categoria_hijo TEXT, categoria_comercial TEXT,
        estado_sku TEXT, pack TEXT, marca TEXT, proveedor TEXT,
        tipo_marca TEXT, tipo_compra TEXT, tipo_negocio TEXT, kam TEXT,
        estado_canal TEXT, anio_venta INT, mes_venta INT, semana_venta INT,
        dia_semana TEXT, hora_venta_num INT,
        cantidad REAL, venta_bruta REAL, venta_neta REAL, costo_unitario REAL, costo_total REAL,
        margen_front REAL, comision_pct REAL, comision REAL,
        logistica REAL, marketing REAL, margen_final REAL
    )""",
    """CREATE TABLE dim_productos (
        sku TEXT PRIMARY KEY, producto TEXT, categoria_macro TEXT, categoria_padre TEXT,
        categoria_hijo TEXT, categoria_comercial TEXT, estado_sku TEXT, pack TEXT,
        marca TEXT, proveedor TEXT, tipo_marca TEXT, tipo_compra TEXT
    )""",
    """CREATE TABLE dim_canales (
        canal TEXT PRIMARY KEY, tipo_negocio TEXT, estado_canal TEXT, kam TEXT
    )""",
    "CREATE TABLE dim_bodegas (bodega TEXT PRIMARY KEY)",
    "CREATE TABLE dim_proveedores (proveedor TEXT PRIMARY KEY)",
    "CREATE TABLE dim_marcas (marca TEXT PRIMARY KEY)",
    """CREATE TABLE metadata_cargas (
        fecha_carga TEXT, fuente TEXT, filas_cargadas INT,
        fecha_min_datos TEXT, fecha_max_datos TEXT, tipo TEXT
    )""",
    "CREATE INDEX idx_ventas_fecha ON ventas(fecha_venta)",
    "CREATE INDEX idx_ventas_sku ON ventas(sku)",
    "CREATE INDEX idx_ventas_canal ON ventas(canal)",
    "CREATE INDEX idx_ventas_marca ON ventas(marca)",
    "CREATE INDEX idx_ventas_documento ON ventas(documento)",
]
for sql in schema_sqls:
    remote.execute(sql)
print("      [OK] Schema creado\n")

# 2. Migrar tablas
def migrar_tabla(nombre, batch_size=200):
    print(f"  Migrando {nombre}...")
    rows = local.execute(f"SELECT * FROM {nombre}").fetchall()
    if not rows:
        print(f"    (vacía)")
        return
    cols = rows[0].keys()
    placeholders = ','.join(['?'] * len(cols))
    sql = f"INSERT OR IGNORE INTO {nombre} ({','.join(cols)}) VALUES ({placeholders})"

    total = len(rows)
    inserted = 0
    t0 = time.time()
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        stmts = [(sql, list(r)) for r in batch]
        try:
            remote.batch(stmts)
            inserted += len(batch)
        except Exception as e:
            # Re-intentar uno por uno (algún row malo)
            for r in batch:
                try:
                    remote.execute(sql, list(r))
                    inserted += 1
                except Exception as e2:
                    pass  # silencio, continuamos
        if inserted % 5000 == 0 or inserted == total:
            elapsed = time.time() - t0
            print(f"    {inserted:,}/{total:,} ({elapsed:.0f}s)")

print("[2/3] Migrando datos...")
migrar_tabla('ventas', batch_size=200)
migrar_tabla('dim_productos')
migrar_tabla('dim_canales')
migrar_tabla('dim_bodegas')
migrar_tabla('dim_proveedores')
migrar_tabla('dim_marcas')
migrar_tabla('metadata_cargas')

# 3. Verificar
print("\n[3/3] Verificación:")
for table in ['ventas', 'dim_productos', 'dim_canales', 'dim_bodegas', 'dim_proveedores', 'dim_marcas']:
    local_count = local.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    remote_count = remote.execute(f"SELECT COUNT(*) FROM {table}").rows[0][0]
    flag = "✓" if local_count == remote_count else "⚠"
    print(f"  {flag} {table:20}  local={local_count:>10,}  remote={remote_count:>10,}")

local.close()
remote.close()
print("\n[OK] Migración completada")
