#!/usr/bin/env python3
"""
Convierte el reporte anterior al formato RAW de 40 columnas.
Útil para visualizar cómo se ve el RAW sin depender de Odoo.
"""
import pandas as pd
from pathlib import Path
from datetime import datetime

print("\n" + "="*100)
print("CONVERTIDOR: REPORTE ANTERIOR A FORMATO RAW (40 COLUMNAS)")
print("="*100 + "\n")

# Cargar reporte anterior
reporte_file = Path('data/outputs/reporte_ventas_abril_2026.xlsx')

if not reporte_file.exists():
    print(f"[ERROR] No encontrado: {reporte_file}")
    exit(1)

print(f"Leyendo reporte: {reporte_file.name}")
df_reporte = pd.read_excel(reporte_file, sheet_name='Ventas')
print(f"Filas cargadas: {len(df_reporte):,}\n")

# Mapeo de columnas: REPORTE → RAW
print("Mapeando columnas al formato RAW...\n")

# Las 40 columnas del RAW
df_raw = pd.DataFrame({
    'Tipo Movimiento': 'Venta',  # Por defecto
    'Bodega': df_reporte['Inventario'],
    'Documento': df_reporte['Facturas - Documento'],
    'Fecha Documento': df_reporte['Facturas - Fecha'],
    'Pedido': df_reporte['Referencia de pedido'],
    'Estado Pedido': df_reporte['Estado'],
    'Tipo Despacho': '',  # No disponible
    'SKU': df_reporte['Lineas - Referencia interna'],
    'Canal': df_reporte['Canal'],
    'Fecha Venta': df_reporte['Fecha creacion'].astype(str).str.split(' ').str[0],
    'Hora Venta': df_reporte['Fecha creacion'].astype(str).str.split(' ').str[1],
    'Producto': df_reporte['Lineas - Producto'],
    'Categoría macro': df_reporte['Categoría macro'],
    'Categoría padre': df_reporte['Categoría padre'],
    'Categoría hijo': df_reporte['Categoría hijo'],
    'Categoría comercial': df_reporte['Categoría comercial'],
    'Estado SKU': '',  # No disponible
    'Pack': '',  # No disponible
    'Marca': '',  # No disponible en reporte
    'Proveedor': '',  # No disponible
    'Tipo Marca': '',  # No disponible
    'Tipo Compra': '',  # No disponible
    'Tipo Negocio': df_reporte['Tipo Negocio'],
    'KAM': '',  # No disponible
    'Estado Canal': '',  # No disponible
    'Año venta': pd.to_datetime(df_reporte['Fecha creacion']).dt.year,
    'Mes venta': pd.to_datetime(df_reporte['Fecha creacion']).dt.month,
    'Semana venta': pd.to_datetime(df_reporte['Fecha creacion']).dt.isocalendar().week,
    'Día semana': pd.to_datetime(df_reporte['Fecha creacion']).dt.dayofweek,
    'Hora venta': df_reporte['Fecha creacion'].astype(str).str.split(' ').str[1],  # Duplicado
    'Cantidad': df_reporte['Lineas - Cantidad'],
    'Venta bruta': df_reporte['Total'],  # Ya es NETA (con NC descontadas)
    'Costo Unitario': df_reporte['Lineas - Coste'],
    'Costo Total': df_reporte['Costo Total'],
    'Margen Front': df_reporte['Margen Directo'],
    'Comision %': (df_reporte['Comisión $ (Mkpl)'] / df_reporte['Total'] * 100).fillna(0),
    'Comisión': df_reporte['Comisión $ (Mkpl)'],
    'Logística': df_reporte['Logística $ (Mkpl)'],
    'Marketing': 0,  # No disponible
    'Mg final': df_reporte['Margen Final']
})

print(f"Filas convertidas: {len(df_raw):,}")
print(f"Columnas RAW: {len(df_raw.columns)}\n")

# Resumen
print("="*100)
print("RESUMEN DE DATOS")
print("="*100 + "\n")

print(f"KPIs del período (Abril 1-12):\n")
print(f"  Venta Total (NETA):    ${df_raw['Venta bruta'].sum():>20,.2f}")
print(f"  Costo Total:           ${df_raw['Costo Total'].sum():>20,.2f}")
print(f"  Margen Front:          ${df_raw['Margen Front'].sum():>20,.2f}")
print(f"  Margen Final:          ${df_raw['Mg final'].sum():>20,.2f}")

venta_total = df_raw['Venta bruta'].sum()
if venta_total > 0:
    print(f"  % Margen Final:        {(df_raw['Mg final'].sum() / venta_total * 100):>20.1f}%")

print(f"\nCanales: {df_raw['Canal'].nunique()}")
print(f"SKUs: {df_raw['SKU'].nunique()}\n")

# Mostrar primeras filas
print("="*100)
print("PRIMERAS FILAS DEL RAW")
print("="*100 + "\n")

display_df = df_raw.head(5).copy()
display_df['Venta bruta'] = display_df['Venta bruta'].apply(lambda x: f"${x:,.0f}")
display_df['Costo Total'] = display_df['Costo Total'].apply(lambda x: f"${x:,.0f}")
display_df['Margen Front'] = display_df['Margen Front'].apply(lambda x: f"${x:,.0f}")
display_df['Mg final'] = display_df['Mg final'].apply(lambda x: f"${x:,.0f}")

print(display_df.to_string(index=False))

# Guardar como Excel
output_file = Path('data/outputs/Raw_ventas_abril_2026_demo.xlsx')
print(f"\n\nGuardando archivo de demostración...")
df_raw.to_excel(output_file, sheet_name='RAW', index=False)
print(f"[OK] Guardado: {output_file}")
print(f"     Tamaño: {output_file.stat().st_size / 1024:.1f} KB")
print(f"     Filas: {len(df_raw):,}")
print(f"     Columnas: {len(df_raw.columns)}")

print("\n" + "="*100)
print("CONVERSION COMPLETADA")
print("="*100 + "\n")

# Resumen por canal
print("\nRESUMEN POR CANAL:\n")
canal_summary = df_raw.groupby('Canal').agg({
    'Venta bruta': 'sum',
    'Costo Total': 'sum',
    'Mg final': 'sum',
    'Pedido': 'nunique'
}).reset_index()

canal_summary.columns = ['Canal', 'Venta', 'Costo', 'Margen', 'Ordenes']
canal_summary = canal_summary.sort_values('Venta', ascending=False)

for idx, row in canal_summary.iterrows():
    print(f"  {row['Canal']:20} | Venta: ${row['Venta']:>12,.0f} | "
          f"Margen: ${row['Margen']:>10,.0f} | Ordenes: {int(row['Ordenes']):>5}")

print("\n")
