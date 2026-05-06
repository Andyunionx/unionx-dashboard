"""
Migra el SQLite local a Turso libSQL usando multi-row INSERT (mucho más rápido).
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
    print("[ERROR] LIBSQL_URL no está seteado.")
    sys.exit(1)

print(f"=== Migración SQLite → Turso (multi-row INSERT) ===")
print(f"  Local: {LOCAL_DB}")
print(f"  Remote: {URL}\n")

local = sqlite3.connect(str(LOCAL_DB))
local.row_factory = sqlite3.Row
remote = libsql_client.create_client_sync(url=URL, auth_token=TOKEN)

# 1. Schema
print("[1/3] Creando schema...")
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
]  # Índices se crean al final (insertar es más rápido sin índices)
for sql in schema_sqls:
    remote.execute(sql)
print("      [OK] Schema creado (sin índices)\n")


def migrar_tabla_multi(nombre, rows_per_insert=500):
    """Multi-row INSERT: 1 statement con N filas."""
    print(f"  Migrando {nombre}...")
    rows = local.execute(f"SELECT * FROM {nombre}").fetchall()
    if not rows:
        print(f"    (vacía)")
        return

    cols = list(rows[0].keys())
    n_cols = len(cols)
    total = len(rows)

    t0 = time.time()
    inserted = 0

    for i in range(0, total, rows_per_insert):
        batch = rows[i:i + rows_per_insert]
        n_rows = len(batch)
        # SQL multi-row: INSERT INTO T (c1,c2) VALUES (?,?),(?,?),...
        placeholders_per_row = '(' + ','.join(['?'] * n_cols) + ')'
        all_placeholders = ','.join([placeholders_per_row] * n_rows)
        sql = f"INSERT OR IGNORE INTO {nombre} ({','.join(cols)}) VALUES {all_placeholders}"
        # Aplanar parámetros
        flat_params = []
        for r in batch:
            flat_params.extend(list(r))
        try:
            remote.execute(sql, flat_params)
            inserted += n_rows
        except Exception as e:
            # Si falla por tamaño, dividir
            print(f"    [WARN] Error batch {i}: {str(e)[:100]}")
            # Re-intentar con batch pequeño
            for r in batch:
                try:
                    remote.execute(
                        f"INSERT OR IGNORE INTO {nombre} ({','.join(cols)}) VALUES ({','.join(['?']*n_cols)})",
                        list(r)
                    )
                    inserted += 1
                except Exception:
                    pass

        if inserted % 10000 == 0 or inserted == total:
            elapsed = time.time() - t0
            rate = inserted / elapsed if elapsed else 0
            eta = (total - inserted) / rate if rate else 0
            print(f"    {inserted:,}/{total:,} ({elapsed:.0f}s, {rate:.0f}/s, ETA {eta:.0f}s)")


print("[2/3] Migrando datos (multi-row INSERT)...")
migrar_tabla_multi('ventas', rows_per_insert=500)
migrar_tabla_multi('dim_productos', rows_per_insert=500)
migrar_tabla_multi('dim_canales', rows_per_insert=500)
migrar_tabla_multi('dim_bodegas', rows_per_insert=500)
migrar_tabla_multi('dim_proveedores', rows_per_insert=500)
migrar_tabla_multi('dim_marcas', rows_per_insert=500)
migrar_tabla_multi('metadata_cargas', rows_per_insert=500)

# 3. Crear índices al final (mucho más rápido que insertar con índices vivos)
print("\n[2.5/3] Creando índices...")
for idx_sql in [
    "CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha_venta)",
    "CREATE INDEX IF NOT EXISTS idx_ventas_sku ON ventas(sku)",
    "CREATE INDEX IF NOT EXISTS idx_ventas_canal ON ventas(canal)",
    "CREATE INDEX IF NOT EXISTS idx_ventas_marca ON ventas(marca)",
]:
    remote.execute(idx_sql)
print("      [OK] Índices creados\n")

# 4. Verificar
print("\n[3/3] Verificación:")
for table in ['ventas', 'dim_productos', 'dim_canales', 'dim_bodegas', 'dim_proveedores', 'dim_marcas']:
    local_count = local.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    remote_count = remote.execute(f"SELECT COUNT(*) FROM {table}").rows[0][0]
    flag = "OK" if local_count == remote_count else "DIFF"
    print(f"  [{flag}] {table:22}  local={local_count:>10,}  remote={remote_count:>10,}")

local.close()
remote.close()
print("\n[OK] Migración completada")
