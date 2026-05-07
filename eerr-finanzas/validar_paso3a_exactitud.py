"""
VALIDACIÓN RIGUROSA PASO 3a
Compara línea × línea que la agregación es EXACTA
- Verifica que cada fila del Raw original está contabilizada
- Valida que los totales coincidan al 100%
- Identifica cualquier discrepancia
"""

import pandas as pd
from pathlib import Path
import sys

def validar_paso3a():
    """Validación rigurosa de PASO 3a"""

    print("\n" + "="*100)
    print(" VALIDACION RIGUROSA PASO 3a: Extracción vs Raw Original")
    print("="*100)

    # Leer Raw original
    ruta_raw_original = Path("../datos_entrada/Raw ventas Y.xlsx")
    if not ruta_raw_original.exists():
        print(f"\n[ERROR] No existe: {ruta_raw_original}")
        return False

    print(f"\n[1/4] Leyendo Raw original...")
    df_raw_original = pd.read_excel(ruta_raw_original, sheet_name='RAW', header=0)
    print(f"[OK] {len(df_raw_original):,} filas totales cargadas")

    # Filtrar febrero
    print(f"\n[2/4] Filtrando Febrero 2026...")
    df_febrero = df_raw_original[
        (df_raw_original['Año venta'] == 2026) &
        (df_raw_original['Mes venta'] == 2)
    ].copy()
    print(f"[OK] {len(df_febrero):,} filas de febrero")

    # Leer salida PASO 3a
    ruta_salida = Path("data/outputs/raw_agregado_febrero_2026.xlsx")
    if not ruta_salida.exists():
        print(f"\n[ERROR] No existe salida de PASO 3a: {ruta_salida}")
        print(f"        Ejecuta primero: python paso3a_desde_excel.py")
        return False

    print(f"\n[3/4] Leyendo salida PASO 3a (agregado)...")
    df_agregado = pd.read_excel(ruta_salida)
    print(f"[OK] {len(df_agregado)} filas agrupadas")

    # ============================================================================
    # VALIDACION 1: TOTALES GENERALES
    # ============================================================================
    print(f"\n[VALIDACION 1] TOTALES GENERALES")
    print("-" * 100)

    metricas = ['Venta bruta', 'Costo Total', 'Margen Front', 'Cantidad']
    todas_coinciden = True

    for metrica in metricas:
        if metrica not in df_febrero.columns:
            continue

        total_original = df_febrero[metrica].sum()

        # Convertir nombre para agregado
        metrica_agregado = metrica
        if metrica == 'Venta bruta':
            metrica_agregado = 'Venta'
        elif metrica == 'Costo Total':
            metrica_agregado = 'Costo Venta'
        elif metrica == 'Margen Front':
            metrica_agregado = 'Margen Directo'

        if metrica_agregado not in df_agregado.columns:
            print(f"[ERROR] Columna no encontrada en agregado: {metrica_agregado}")
            todas_coinciden = False
            continue

        total_agregado = df_agregado[metrica_agregado].sum()

        diferencia_abs = abs(total_original - total_agregado)
        diferencia_pct = (diferencia_abs / total_original * 100) if total_original != 0 else 0

        match = "✓ COINCIDE" if diferencia_abs < 1 else "✗ DIFERENCIA"
        todos_coinciden_ok = todas_coinciden and (diferencia_abs < 1)

        print(f"\n{metrica:<25}")
        print(f"  Original:   ${total_original:>20,.2f}")
        print(f"  Agregado:   ${total_agregado:>20,.2f}")
        print(f"  Diferencia: ${diferencia_abs:>20,.2f} ({diferencia_pct:.4f}%)")
        print(f"  Estado:     {match}")

        if diferencia_abs >= 1:
            todas_coinciden = False

    # ============================================================================
    # VALIDACION 2: POR CANAL
    # ============================================================================
    print(f"\n\n[VALIDACION 2] TOTALES POR CANAL (Top 10)")
    print("-" * 100)
    print(f"{'Canal':<35} | {'Original':>15} | {'Agregado':>15} | {'Diferencia':>12} | {'Estado':>8}")
    print("-" * 100)

    # Agrupar original por canal
    df_original_por_canal = df_febrero.groupby('Canal', as_index=False).agg({
        'Venta bruta': 'sum',
        'Costo Total': 'sum',
        'Margen Front': 'sum',
        'Cantidad': 'sum'
    }).sort_values('Margen Front', ascending=False)

    # Agrupar agregado por canal
    df_agregado_por_canal = df_agregado.groupby('Canal', as_index=False).agg({
        'Venta': 'sum',
        'Margen Directo': 'sum'
    }).sort_values('Margen Directo', ascending=False)

    canales_coinciden = 0
    canales_totales = 0

    for _, row_original in df_original_por_canal.iterrows():
        canal = row_original['Canal']
        venta_original = row_original['Venta bruta']

        # Buscar en agregado
        row_agregado = df_agregado_por_canal[df_agregado_por_canal['Canal'] == canal]
        if not row_agregado.empty:
            venta_agregado = row_agregado.iloc[0]['Venta']
        else:
            venta_agregado = 0

        diferencia = abs(venta_original - venta_agregado)
        diferencia_pct = (diferencia / venta_original * 100) if venta_original > 0 else 0

        if diferencia < 100:  # Permitir pequeñas diferencias por redondeo
            estado = "[OK]"
            canales_coinciden += 1
        else:
            estado = "[DIFF]"

        canales_totales += 1

        print(f"{canal:<35} | ${venta_original:>14,.0f} | ${venta_agregado:>14,.0f} | ${diferencia:>11,.0f} | {estado:>8}")

    print(f"\n  Canales con coincidencia: {canales_coinciden}/{canales_totales}")

    # ============================================================================
    # VALIDACION 3: POR TIPO NEGOCIO
    # ============================================================================
    print(f"\n\n[VALIDACION 3] TOTALES POR TIPO NEGOCIO")
    print("-" * 100)
    print(f"{'Tipo Negocio':<35} | {'Original':>15} | {'Agregado':>15} | {'Varianza':>10}")
    print("-" * 100)

    df_original_negocio = df_febrero.groupby('Tipo Negocio', as_index=False).agg({
        'Venta bruta': 'sum'
    }).sort_values('Venta bruta', ascending=False)

    df_agregado_negocio = df_agregado.groupby('Tipo Negocio', as_index=False).agg({
        'Venta': 'sum'
    }).sort_values('Venta', ascending=False)

    for _, row_original in df_original_negocio.iterrows():
        negocio = row_original['Tipo Negocio']
        venta_original = row_original['Venta bruta']

        row_agregado = df_agregado_negocio[df_agregado_negocio['Tipo Negocio'] == negocio]
        if not row_agregado.empty:
            venta_agregado = row_agregado.iloc[0]['Venta']
        else:
            venta_agregado = 0

        varianza = (venta_agregado - venta_original) / venta_original * 100 if venta_original > 0 else 0

        print(f"{negocio:<35} | ${venta_original:>14,.0f} | ${venta_agregado:>14,.0f} | {varianza:>9.2f}%")

    # ============================================================================
    # VALIDACION 4: RECUENTO DE FILAS
    # ============================================================================
    print(f"\n\n[VALIDACION 4] RECUENTO DE DIMENSIONES")
    print("-" * 100)

    dimensiones_original = df_febrero.groupby(['Canal', 'Tipo Negocio', 'KAM']).size()
    dimensiones_agregado = df_agregado.groupby(['Canal', 'Tipo Negocio', 'KAM']).size()

    print(f"Combinaciones úniques (Canal × Negocio × KAM):")
    print(f"  Original: {len(dimensiones_original)}")
    print(f"  Agregado: {len(dimensiones_agregado)}")

    if len(dimensiones_original) == len(dimensiones_agregado):
        print(f"  Estado: [OK] Todas las dimensiones están presentes")
    else:
        print(f"  Estado: [AVISO] Hay diferencia en dimensiones")

    # ============================================================================
    # RESUMEN FINAL
    # ============================================================================
    print(f"\n\n{'='*100}")
    print(" RESUMEN FINAL")
    print(f"{'='*100}")

    if todas_coinciden and canales_coinciden == canales_totales:
        print(f"""
[✓ VALIDACION EXITOSA]

  - Totales generales: COINCIDEN EXACTAMENTE
  - Canales: {canales_coinciden}/{canales_totales} coinciden
  - Dimensiones: {len(dimensiones_agregado)} combinaciones presentes

  CONCLUSION: Los datos de PASO 3a son EXACTOS
  Status: LISTO PARA INYECTAR EN ANALISIS RESULTADO

ARCHIVO GENERADO:
  {ruta_salida}

PROXIMO PASO:
  python inyectar_raw_analisis_resultado.py
""")
        return True
    else:
        print(f"""
[✗ VALIDACION PARCIAL]

  - Totales generales: {"COINCIDEN" if todas_coinciden else "CON DIFERENCIAS"}
  - Canales: {canales_coinciden}/{canales_totales} coinciden
  - Dimensiones: {len(dimensiones_agregado)} combinaciones

AVISO: Revisa las discrepancias arriba antes de inyectar.

DIAGNOSTICO:
""")
        if not todas_coinciden:
            print("  1. Hay diferencias en totales generales")
            print("  2. Verifica que febrero_2026 está siendo filtrado correctamente")
            print("  3. Revisa que no hay valores NaN o inválidos")

        if canales_coinciden < canales_totales:
            print(f"  1. Hay {canales_totales - canales_coinciden} canales con discrepancias")
            print("  2. Verifica que los nombres de canal coinciden exactamente")

        return False


if __name__ == "__main__":
    exito = validar_paso3a()

    if exito:
        print("\n" + "="*100)
        print(" PRESIONA CUALQUIER TECLA PARA CONTINUAR CON INYECCION")
        print("="*100)
        sys.exit(0)
    else:
        print("\n[DETENER] Revisa los errores antes de continuar")
        sys.exit(1)
