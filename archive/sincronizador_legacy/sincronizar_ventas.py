#!/usr/bin/env python3
"""
Sincronizador automático de ventas desde Odoo a Maestra SQLite.
Ejecutado cada 5 minutos vía Task Scheduler.

Características:
- Detección automática de rango de fechas (nunca más de 7 días)
- Deduplicación idempotente (DELETE + INSERT)
- Logging detallado en data/db/sincronizacion.log
- Alarm de prevención si atraso > 30 días

Uso:
    python sincronizar_ventas.py
"""
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, date
import pandas as pd
import logging

# Setup paths
PROJECT_ROOT = Path(__file__).parent
backend_path = PROJECT_ROOT / 'finanzas-unionx' / 'backend'
sys.path.insert(0, str(backend_path))

from app.core.odoo_client import OdooClient
from app.services.ventas_service import VentasService
from app.config import Config

# DB and paths
DB_PATH = PROJECT_ROOT / 'data' / 'db' / 'maestra_ventas.db'
DB_LOCAL = Path.home() / 'Desktop' / 'finanzas-unionx-app' / 'maestra_ventas.db'
LOG_PATH = PROJECT_ROOT / 'data' / 'db' / 'sincronizacion.log'

# 40-column mapping (from actualizar_raw_historico.py)
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

# Setup logging
log_format = '[%(asctime)s] %(levelname)-8s %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.FileHandler(str(LOG_PATH), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def obtener_fecha_max_db(db_path):
    """Returns MAX(fecha_venta) from the DB, or None if table is empty."""
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(fecha_venta) FROM ventas")
        result = cursor.fetchone()[0]
        conn.close()
        return result
    except Exception as e:
        logger.warning(f"Error obteniendo MAX(fecha_venta): {e}")
        return None


def obtener_periodo_siguiente(db_path, inicio_historico="2026-04-01"):
    """
    Determines the date range to extract in the next Odoo fetch.

    Strategy:
    - Never extract more than 7 days at once (weekly batching)
    - If DB is empty or behind: catch up incrementally
    - If up to date: refresh the current week (in case of corrections/late NC)

    Returns: (fecha_inicio, fecha_fin) as "YYYY-MM-DD HH:MM:SS" strings
    """
    max_fecha_str = obtener_fecha_max_db(db_path)
    hoy = date.today()
    inicio = date.fromisoformat(inicio_historico)

    # Determine 'desde' (start of period to fetch)
    if max_fecha_str is None:
        # DB is empty: start from the beginning
        desde = inicio
    else:
        max_fecha = date.fromisoformat(max_fecha_str)
        if max_fecha < inicio:
            # Before our start: begin from day 1
            desde = inicio
        else:
            desde = max_fecha + timedelta(days=1)

    # Determine 'hasta' (end of period to fetch)
    if desde >= hoy:
        # Already up to date: refresh current week (7-day rolling window)
        # Determine which week we're in, relative to inicio_historico
        dias_desde_inicio = (hoy - inicio).days
        semana_actual = dias_desde_inicio // 7
        desde = inicio + timedelta(weeks=semana_actual)
        hasta = min(desde + timedelta(days=6), hoy)
    else:
        # Behind: catch up, max 7 days at a time
        hasta = min(desde + timedelta(days=6), hoy)

    # Convert to "YYYY-MM-DD HH:MM:SS" strings
    inicio_str = f"{desde.strftime('%Y-%m-%d')} 00:00:00"
    fin_str = f"{hasta.strftime('%Y-%m-%d')} 23:59:59"

    return inicio_str, fin_str, desde, hasta


def insertar_deduplicado(df_raw, db_path, fecha_desde, fecha_hasta):
    """
    Inserts df_raw into DB with deduplication.

    1. DELETE rows where fecha_venta BETWEEN fecha_desde AND fecha_hasta
    2. INSERT new rows
    3. Update dimensions (new SKUs, canales, etc)
    4. Log the load in metadata_cargas

    Returns: total row count in ventas table
    """
    df = df_raw.rename(columns=RAW_TO_DB).copy()

    # Convert date columns to ISO string
    for col in ['fecha_documento', 'fecha_venta']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')

    # Replace NaN with None
    df = df.where(pd.notna(df), None)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # DELETE existing rows for this date range
    cursor.execute(
        "DELETE FROM ventas WHERE fecha_venta BETWEEN ? AND ?",
        (str(fecha_desde), str(fecha_hasta))
    )
    deleted_count = cursor.rowcount

    # INSERT new rows
    ventas_cols = [v for v in RAW_TO_DB.values()]
    cols_disponibles = [c for c in ventas_cols if c in df.columns]
    df[cols_disponibles].to_sql('ventas', conn, if_exists='append', index=False, chunksize=1000)

    # Update dimensions
    # Nuevos SKUs
    skus_db = set(r[0] for r in cursor.execute("SELECT sku FROM dim_productos").fetchall())
    nuevos = df[~df['sku'].isin(skus_db)][
        ['sku', 'producto', 'categoria_macro', 'categoria_padre',
         'categoria_hijo', 'categoria_comercial', 'estado_sku',
         'pack', 'marca', 'proveedor', 'tipo_marca', 'tipo_compra']
    ].drop_duplicates(subset=['sku'])
    if len(nuevos) > 0:
        nuevos.where(pd.notna(nuevos), None).to_sql('dim_productos', conn, if_exists='append', index=False)
        logger.info(f"      +{len(nuevos)} SKUs nuevos")

    # Nuevos canales
    canales_db = set(r[0] for r in cursor.execute("SELECT canal FROM dim_canales").fetchall())
    nuevos_c = df[~df['canal'].isin(canales_db)][
        ['canal', 'tipo_negocio', 'estado_canal', 'kam']
    ].drop_duplicates(subset=['canal'])
    if len(nuevos_c) > 0:
        nuevos_c.where(pd.notna(nuevos_c), None).to_sql('dim_canales', conn, if_exists='append', index=False)
        logger.info(f"      +{len(nuevos_c)} canales nuevos")

    # Record load metadata
    fecha_min = df['fecha_venta'].min()
    fecha_max = df['fecha_venta'].max()
    cursor.execute("""
        INSERT INTO metadata_cargas (fecha_carga, fuente, filas_cargadas, fecha_min_datos, fecha_max_datos, tipo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), 'Odoo (sincronizar_ventas)', len(df), fecha_min, fecha_max, 'incremental_odoo'))
    conn.commit()

    total = cursor.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
    conn.close()

    logger.info(f"      Deduplicado: {deleted_count} eliminadas, +{len(df_raw):,} nuevas -> Total: {total:,}")

    return total


def sincronizar():
    """Main sync orchestrator."""
    logger.info("="*100)
    logger.info("SINCRONIZADOR RAW — Odoo -> Maestra SQLite (every 5 min)")
    logger.info("="*100)

    try:
        # Choose DB (prefer local if exists)
        db = DB_LOCAL if DB_LOCAL.exists() else DB_PATH
        if not db.exists():
            logger.error(f"ERROR: DB no existe en {db}")
            logger.error("Ejecuta primero: python data/db/crear_maestra_ventas.py")
            return False

        # Determine period to fetch
        logger.info("\n[1/5] Detectando período a extraer...")
        periodo_inicio, periodo_fin, fecha_desde, fecha_hasta = obtener_periodo_siguiente(db)
        logger.info(f"      Período: {periodo_inicio} a {periodo_fin}")

        # Check if we're significantly behind
        max_fecha = obtener_fecha_max_db(db)
        if max_fecha:
            atraso_dias = (date.today() - date.fromisoformat(max_fecha)).days
            if atraso_dias > 30:
                logger.warning(f"\n[ALERTA] Base de datos atrasada {atraso_dias} días!")
                logger.warning(f"         Última fecha en DB: {max_fecha}")
                logger.warning(f"         Hoy: {date.today()}")

        # [2] Conectar a Odoo
        logger.info("\n[2/5] Conectando a Odoo...")
        odoo = OdooClient(
            url=Config.ODOO_URL,
            db=Config.ODOO_DB,
            username=Config.ODOO_USER,
            password=Config.ODOO_PASSWORD
        )
        logger.info("      [OK] Conectado")

        # [3] Inicializar servicio
        logger.info("\n[3/5] Inicializando VentasService...")
        service = VentasService(odoo, Config.PLANILLAS_DIR)
        logger.info("      [OK] Servicio listo")

        # [4] Extraer RAW
        logger.info(f"\n[4/5] Extrayendo datos {fecha_desde.strftime('%Y-%m-%d')} a {fecha_hasta.strftime('%Y-%m-%d')}...")
        df_raw = service.extract_to_raw_format(
            periodo_inicio, periodo_fin,
            progress_callback=lambda pct, label: logger.info(f"      {pct}% - {label}")
        )

        if len(df_raw) == 0:
            logger.info("      [INFO] No hay datos nuevos")
            logger.info("="*100 + "\n")
            return True

        logger.info(f"      [OK] {len(df_raw):,} filas extraidas")

        # [5] Insertar con deduplicación
        logger.info(f"\n[5/5] Insertando en Maestra SQLite (con deduplicación)...")
        logger.info(f"      DB: {db}")
        total = insertar_deduplicado(df_raw, db, fecha_desde, fecha_hasta)

        # Resumen
        venta_total = df_raw['Venta bruta'].sum()
        margen_total = df_raw['Mg final'].sum()
        logger.info(f"\n      Resumen:")
        logger.info(f"        Filas: {len(df_raw):,}")
        logger.info(f"        Canales: {df_raw['Canal'].nunique()}")
        logger.info(f"        SKUs: {df_raw['SKU'].nunique()}")
        logger.info(f"        Venta bruta: ${venta_total:,.0f}")
        logger.info(f"        Margen final: ${margen_total:,.0f}")
        if venta_total > 0:
            logger.info(f"        % Margen: {(margen_total / venta_total * 100):.1f}%")

        logger.info("\n" + "="*100)
        logger.info("[OK] SINCRONIZACION COMPLETADA")
        logger.info("="*100 + "\n")

        return True

    except Exception as e:
        logger.error(f"\n[ERROR] {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        logger.error("="*100 + "\n")
        return False


if __name__ == '__main__':
    success = sincronizar()
    sys.exit(0 if success else 1)
