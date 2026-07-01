#!/usr/bin/env python3
"""
Actualiza ventas_historico.parquet con datos descargados del Ventas Streamlit.

Uso:
    python merge_ventas_descarga.py <ruta_parquet_descargado>

Ejemplo:
    python merge_ventas_descarga.py ventas_2026-01-01_2026-06-30.parquet

Qué hace:
  1. Lee el parquet descargado (mismo schema de 41 cols que ventas_historico)
  2. Detecta el rango de fechas que cubre
  3. Remueve esas fechas del historico actual (para evitar duplicados)
  4. Agrega los datos nuevos
  5. Guarda ventas_historico.parquet actualizado
"""
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
PARQUET_PATH = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'

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


def main():
    if len(sys.argv) < 2:
        print("Uso: python merge_ventas_descarga.py <ruta_parquet_descargado>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path

    if not input_path.exists():
        print(f"[ERROR] No encuentro el archivo: {input_path}")
        sys.exit(1)

    # 1. Cargar el parquet descargado
    print(f"[1] Leyendo parquet descargado: {input_path.name}")
    df_new = pd.read_parquet(input_path)
    df_new['fecha_venta'] = pd.to_datetime(df_new['fecha_venta'], errors='coerce')
    df_new = df_new.dropna(subset=['fecha_venta'])
    print(f"    {len(df_new):,} filas | rango: {df_new['fecha_venta'].min().date()} → {df_new['fecha_venta'].max().date()}")

    if len(df_new) == 0:
        print("[ERROR] El parquet descargado está vacío.")
        sys.exit(1)

    fecha_min = df_new['fecha_venta'].min()
    fecha_max = df_new['fecha_venta'].max()

    # Validar columnas esenciales
    cols_falta = [c for c in ('sku', 'fecha_venta', 'venta_neta', 'tipo_negocio', 'marca') if c not in df_new.columns]
    if cols_falta:
        print(f"[WARN] Columnas faltantes en descarga: {cols_falta}")

    # 2. Cargar historico actual
    print(f"\n[2] Leyendo ventas_historico.parquet...")
    df_hist = pd.read_parquet(PARQUET_PATH)
    df_hist['fecha_venta'] = pd.to_datetime(df_hist['fecha_venta'], errors='coerce')
    print(f"    {len(df_hist):,} filas | rango: {df_hist['fecha_venta'].min().date()} → {df_hist['fecha_venta'].max().date()}")

    # Stats por mes antes del merge
    df_hist['_mes'] = df_hist['fecha_venta'].dt.to_period('M').astype(str)
    venta_antes = df_hist.groupby('_mes')['venta_neta'].sum().tail(8)
    print("\n   Venta neta por mes (últimos 8, ANTES):")
    for mes, v in venta_antes.items():
        print(f"     {mes}: ${v/1e6:.1f}M")
    df_hist = df_hist.drop(columns='_mes')

    # 3. Remover el rango del historico (para reemplazar con datos frescos)
    mascara_fuera = (df_hist['fecha_venta'] < fecha_min) | (df_hist['fecha_venta'] > fecha_max)
    df_hist_reducido = df_hist[mascara_fuera].copy()
    removidas = len(df_hist) - len(df_hist_reducido)
    print(f"\n[3] Removidas {removidas:,} filas del rango {fecha_min.date()} → {fecha_max.date()}")

    # 4. Alinear columnas
    cols_comunes = [c for c in PARQUET_COLS if c in df_new.columns and c in df_hist_reducido.columns]
    cols_extra_hist = [c for c in df_hist_reducido.columns if c not in PARQUET_COLS]

    # Normalizar texto para evitar errores Arrow
    cols_texto = [c for c in cols_comunes if c not in (
        'anio_venta', 'mes_venta', 'semana_venta', 'hora_venta_num',
        'cantidad', 'venta_bruta', 'costo_unitario', 'costo_total',
        'margen_front', 'comision_pct', 'comision', 'logistica',
        'marketing', 'margen_final', 'venta_neta', 'fecha_venta',
    )]
    for df_x in (df_hist_reducido, df_new):
        for c in cols_texto:
            if c in df_x.columns:
                df_x[c] = df_x[c].astype(object).where(df_x[c].notna(), '').astype(str).replace('nan', '')

    # 5. Concat y ordenar
    df_final = pd.concat([df_hist_reducido[cols_comunes], df_new[cols_comunes]], ignore_index=True)
    df_final = df_final.sort_values('fecha_venta', kind='stable').reset_index(drop=True)

    # Stats por mes después
    df_final['_mes'] = df_final['fecha_venta'].dt.to_period('M').astype(str)
    venta_despues = df_final.groupby('_mes')['venta_neta'].sum().tail(8)
    print("\n   Venta neta por mes (últimos 8, DESPUÉS):")
    for mes, v in venta_despues.items():
        print(f"     {mes}: ${v/1e6:.1f}M")
    df_final = df_final.drop(columns='_mes')

    print(f"\n[4] Total final: {len(df_final):,} filas")

    # 6. Guardar (fecha como string, igual que el parquet original)
    df_final['fecha_venta'] = df_final['fecha_venta'].dt.strftime('%Y-%m-%d')
    df_final[cols_comunes].to_parquet(PARQUET_PATH, index=False)

    size_mb = PARQUET_PATH.stat().st_size / 1e6
    print(f"\n[OK] Guardado {PARQUET_PATH} ({size_mb:.1f} MB)")
    print("\nPróximo paso: git add data/historico/ventas_historico.parquet && git commit -m 'data: actualizar ventas_historico con datos completos'")


if __name__ == '__main__':
    main()
