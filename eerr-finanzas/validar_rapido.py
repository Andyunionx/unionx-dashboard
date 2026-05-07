"""
Validación rápida de PASO 3a - Versión simplificada
"""

import pandas as pd
from pathlib import Path

print("\n" + "="*100)
print(" VALIDACION RAPIDA PASO 3a")
print("="*100)

# Leer Raw original
print("\n[Leyendo Raw original...]")
df_raw = pd.read_excel("../datos_entrada/Raw ventas Y.xlsx", sheet_name='RAW')
df_feb = df_raw[(df_raw['Año venta'] == 2026) & (df_raw['Mes venta'] == 2)]

print(f"  Raw original febrero: {len(df_feb):,} filas")
print(f"  Venta total: ${df_feb['Venta bruta'].sum():,.0f}")
print(f"  Costo total: ${df_feb['Costo Total'].sum():,.0f}")
print(f"  Margen directo: ${df_feb['Margen Front'].sum():,.0f}")

# Leer agregado
print("\n[Leyendo agregado...]")
df_agg = pd.read_excel("data/outputs/raw_agregado_febrero_2026.xlsx")

print(f"  Agregado: {len(df_agg)} filas (después de agrupar)")
print(f"  Venta total: ${df_agg['Venta'].sum():,.0f}")
print(f"  Costo total: ${df_agg['Costo Venta'].sum():,.0f}")
print(f"  Margen directo: ${df_agg['Margen Directo'].sum():,.0f}")

# Comparar
print("\n" + "="*100)
print(" COMPARACION")
print("="*100)

print("\n[TOTALES]")
venta_raw = df_feb['Venta bruta'].sum()
venta_agg = df_agg['Venta'].sum()
costo_raw = df_feb['Costo Total'].sum()
costo_agg = df_agg['Costo Venta'].sum()
margen_raw = df_feb['Margen Front'].sum()
margen_agg = df_agg['Margen Directo'].sum()

print(f"\n  Venta:")
print(f"    Raw:     ${venta_raw:,.2f}")
print(f"    Agregado: ${venta_agg:,.2f}")
print(f"    Diferencia: ${abs(venta_raw - venta_agg):,.2f} ({abs(venta_raw - venta_agg)/venta_raw*100:.4f}%)")
print(f"    Match: {'✓ OK' if abs(venta_raw - venta_agg) < 1 else '✗ DIFERENCIA'}")

print(f"\n  Costo:")
print(f"    Raw:     ${costo_raw:,.2f}")
print(f"    Agregado: ${costo_agg:,.2f}")
print(f"    Diferencia: ${abs(costo_raw - costo_agg):,.2f}")
print(f"    Match: {'✓ OK' if abs(costo_raw - costo_agg) < 1 else '✗ DIFERENCIA'}")

print(f"\n  Margen Directo:")
print(f"    Raw:     ${margen_raw:,.2f}")
print(f"    Agregado: ${margen_agg:,.2f}")
print(f"    Diferencia: ${abs(margen_raw - margen_agg):,.2f}")
print(f"    Match: {'✓ OK' if abs(margen_raw - margen_agg) < 1 else '✗ DIFERENCIA'}")

# Resumen
print("\n" + "="*100)
if (abs(venta_raw - venta_agg) < 1 and
    abs(costo_raw - costo_agg) < 1 and
    abs(margen_raw - margen_agg) < 1):
    print("[✓ VALIDACION EXITOSA]")
    print("\nLos datos coinciden EXACTAMENTE. LISTO PARA INYECTAR.")
else:
    print("[✗ VALIDACION FALLIDA]")
    print("\nHay discrepancias. Revisa arriba.")

print("="*100 + "\n")
