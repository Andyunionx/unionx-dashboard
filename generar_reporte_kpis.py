#!/usr/bin/env python3
"""
Genera reportes ejecutivos de KPIs desde la Maestra de Ventas SQLite.
Muestra venta y margen directo por canal y línea de negocio.

Uso:
    python generar_reporte_kpis.py                          # Últimos 15 días
    python generar_reporte_kpis.py 2026-04-01 2026-04-15    # Rango custom
    python generar_reporte_kpis.py --excel                  # Exportar a Excel
"""
import sys
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, date
import argparse

DB_PATH = Path(__file__).parent / 'data' / 'db' / 'maestra_ventas.db'


def ejecutar_query(db_path, query):
    """Ejecuta una query SQL y retorna un DataFrame."""
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def resumen_general(db_path, fecha_inicio, fecha_fin):
    """Resumen general de ventas y margen."""
    query = f"""
    SELECT
        COUNT(*) as lineas,
        ROUND(SUM(cantidad), 0) as unidades,
        ROUND(SUM(venta_bruta), 2) as venta_neta,
        ROUND(SUM(costo_total), 2) as costo,
        ROUND(SUM(margen_front), 2) as margen_directo,
        ROUND(SUM(margen_final), 2) as margen_final
    FROM ventas
    WHERE fecha_venta BETWEEN '{fecha_inicio}' AND '{fecha_fin}'
    """
    return ejecutar_query(db_path, query).iloc[0]


def por_canal(db_path, fecha_inicio, fecha_fin):
    """Resumen por canal."""
    query = f"""
    SELECT
        canal,
        COUNT(*) as lineas,
        ROUND(SUM(cantidad), 0) as unidades,
        ROUND(SUM(venta_bruta), 2) as venta_neta,
        ROUND(SUM(margen_front), 2) as margen_directo,
        ROUND(SUM(margen_final), 2) as margen_final,
        ROUND(100.0 * SUM(margen_final) / NULLIF(SUM(venta_bruta), 0), 1) as pct_margen
    FROM ventas
    WHERE fecha_venta BETWEEN '{fecha_inicio}' AND '{fecha_fin}'
    GROUP BY canal
    ORDER BY venta_neta DESC
    """
    return ejecutar_query(db_path, query)


def por_linea_negocio(db_path, fecha_inicio, fecha_fin):
    """Resumen por línea de negocio."""
    query = f"""
    SELECT
        tipo_negocio,
        COUNT(*) as lineas,
        ROUND(SUM(cantidad), 0) as unidades,
        ROUND(SUM(venta_bruta), 2) as venta_neta,
        ROUND(SUM(margen_front), 2) as margen_directo,
        ROUND(SUM(margen_final), 2) as margen_final,
        ROUND(100.0 * SUM(margen_final) / NULLIF(SUM(venta_bruta), 0), 1) as pct_margen
    FROM ventas
    WHERE fecha_venta BETWEEN '{fecha_inicio}' AND '{fecha_fin}'
    GROUP BY tipo_negocio
    ORDER BY venta_neta DESC
    """
    return ejecutar_query(db_path, query)


def matriz_canal_negocio(db_path, fecha_inicio, fecha_fin):
    """Matriz: Canal x Línea de Negocio."""
    query = f"""
    SELECT
        canal,
        tipo_negocio,
        ROUND(SUM(venta_bruta), 2) as venta_neta,
        ROUND(SUM(margen_final), 2) as margen_final
    FROM ventas
    WHERE fecha_venta BETWEEN '{fecha_inicio}' AND '{fecha_fin}'
    GROUP BY canal, tipo_negocio
    ORDER BY venta_neta DESC
    """
    return ejecutar_query(db_path, query)


def top_skus(db_path, fecha_inicio, fecha_fin, limit=15):
    """Top SKUs por venta neta."""
    query = f"""
    SELECT
        sku,
        producto,
        ROUND(SUM(cantidad), 0) as unidades,
        ROUND(SUM(venta_bruta), 2) as venta_neta,
        ROUND(SUM(margen_final), 2) as margen_final,
        ROUND(100.0 * SUM(margen_final) / NULLIF(SUM(venta_bruta), 0), 1) as pct_margen
    FROM ventas
    WHERE fecha_venta BETWEEN '{fecha_inicio}' AND '{fecha_fin}'
    GROUP BY sku
    ORDER BY venta_neta DESC
    LIMIT {limit}
    """
    return ejecutar_query(db_path, query)


def imprimir_reporte(db_path, fecha_inicio, fecha_fin):
    """Imprime un reporte formateado en consola."""
    print("\n" + "="*120)
    print(f"REPORTE EJECUTIVO — MAESTRA DE VENTAS")
    print(f"Período: {fecha_inicio} a {fecha_fin}")
    print(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*120 + "\n")

    # Resumen general
    print("[1] RESUMEN GENERAL")
    print("-" * 120)
    rg = resumen_general(db_path, fecha_inicio, fecha_fin)
    print(f"  Líneas de venta: {rg['lineas']:,}")
    print(f"  Unidades vendidas: {rg['unidades']:,.0f}")
    print(f"  Venta NETA: ${rg['venta_neta']:,.2f}")
    print(f"  Costo Total: ${rg['costo']:,.2f}")
    print(f"  Margen Directo: ${rg['margen_directo']:,.2f}")
    print(f"  Margen Final: ${rg['margen_final']:,.2f}")
    margen_pct = 100.0 * rg['margen_final'] / rg['venta_neta'] if rg['venta_neta'] > 0 else 0
    print(f"  % Margen Final: {margen_pct:.1f}%")

    # Por canal
    print("\n[2] VENTA POR CANAL")
    print("-" * 120)
    df_canal = por_canal(db_path, fecha_inicio, fecha_fin)
    for _, row in df_canal.iterrows():
        print(f"  {row['canal']:30s} -> ${row['venta_neta']:>12,.0f}  | Margen: ${row['margen_final']:>12,.0f}  ({row['pct_margen']:>5.1f}%)")

    # Por línea de negocio
    print("\n[3] VENTA POR LÍNEA DE NEGOCIO")
    print("-" * 120)
    df_negocio = por_linea_negocio(db_path, fecha_inicio, fecha_fin)
    for _, row in df_negocio.iterrows():
        print(f"  {row['tipo_negocio']:30s} -> ${row['venta_neta']:>12,.0f}  | Margen: ${row['margen_final']:>12,.0f}  ({row['pct_margen']:>5.1f}%)")

    # Matriz canal x negocio (top 15)
    print("\n[4] MATRIZ: CANAL x LÍNEA DE NEGOCIO (Top 15)")
    print("-" * 120)
    df_matriz = matriz_canal_negocio(db_path, fecha_inicio, fecha_fin).head(15)
    for _, row in df_matriz.iterrows():
        print(f"  {row['canal']:20s} + {row['tipo_negocio']:20s} -> ${row['venta_neta']:>12,.0f}  | Margen: ${row['margen_final']:>12,.0f}")

    # Top SKUs
    print("\n[5] TOP 15 PRODUCTOS")
    print("-" * 120)
    df_skus = top_skus(db_path, fecha_inicio, fecha_fin, limit=15)
    for idx, (_, row) in enumerate(df_skus.iterrows(), 1):
        prod_name = row['producto'][:40] if len(row['producto']) > 40 else row['producto']
        print(f"  {idx:2d}. {row['sku']:15s} | {prod_name:40s} → ${row['venta_neta']:>12,.0f}  ({row['pct_margen']:>5.1f}%)")

    print("\n" + "="*120 + "\n")


def exportar_a_excel(db_path, fecha_inicio, fecha_fin, output_file="Reporte_KPIs.xlsx"):
    """Exporta todos los KPIs a un Excel con múltiples hojas."""
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Hoja 1: Resumen General
        rg = resumen_general(db_path, fecha_inicio, fecha_fin)
        df_rg = pd.DataFrame([rg])
        df_rg.to_excel(writer, sheet_name='Resumen General', index=False)

        # Hoja 2: Por Canal
        df_canal = por_canal(db_path, fecha_inicio, fecha_fin)
        df_canal.to_excel(writer, sheet_name='Por Canal', index=False)

        # Hoja 3: Por Línea de Negocio
        df_negocio = por_linea_negocio(db_path, fecha_inicio, fecha_fin)
        df_negocio.to_excel(writer, sheet_name='Por Línea Negocio', index=False)

        # Hoja 4: Matriz Canal x Negocio
        df_matriz = matriz_canal_negocio(db_path, fecha_inicio, fecha_fin)
        df_matriz.to_excel(writer, sheet_name='Matriz', index=False)

        # Hoja 5: Top SKUs
        df_skus = top_skus(db_path, fecha_inicio, fecha_fin, limit=100)
        df_skus.to_excel(writer, sheet_name='Top SKUs', index=False)

    print(f"[OK] Reporte exportado a {output_file}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Genera reportes KPIs desde Maestra de Ventas')
    parser.add_argument('--inicio', default=None, help='Fecha inicio YYYY-MM-DD (default: hace 15 días)')
    parser.add_argument('--fin', default=None, help='Fecha fin YYYY-MM-DD (default: hoy)')
    parser.add_argument('--excel', action='store_true', help='Exportar a Excel en lugar de imprimir')
    parser.add_argument('--output', default='Reporte_KPIs.xlsx', help='Nombre del archivo Excel')

    args = parser.parse_args()

    # Determinar fechas
    if not args.fin:
        fecha_fin = date.today().strftime('%Y-%m-%d')
    else:
        fecha_fin = args.fin

    if not args.inicio:
        fecha_inicio = (date.today() - timedelta(days=14)).strftime('%Y-%m-%d')
    else:
        fecha_inicio = args.inicio

    # Verificar DB
    if not DB_PATH.exists():
        print(f"ERROR: Base de datos no encontrada: {DB_PATH}")
        sys.exit(1)

    if args.excel:
        exportar_a_excel(str(DB_PATH), fecha_inicio, fecha_fin, args.output)
    else:
        imprimir_reporte(str(DB_PATH), fecha_inicio, fecha_fin)
