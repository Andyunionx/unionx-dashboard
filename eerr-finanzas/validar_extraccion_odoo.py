"""
Valida la extracción desde Odoo comparándola contra Raw ventas Y.xlsx
- Compara totales por canal
- Identifica custom fields faltantes o incorrectos
- Proporciona recomendaciones de ajuste
"""

import pandas as pd
from pathlib import Path

def comparar_extracciones():
    """Compara extracción Odoo vs archivo Excel original"""

    print("\n" + "="*100)
    print(" VALIDACION: Extracción Odoo vs Raw ventas Y.xlsx (Febrero 2026)")
    print("="*100)

    # Leer extracción desde Odoo
    ruta_odoo = Path("data/outputs/raw_desde_odoo_febrero_2026.csv")
    if not ruta_odoo.exists():
        print(f"[ERROR] No existe: {ruta_odoo}")
        print(f"        Ejecuta primero: python extraer_raw_desde_odoo.py")
        return

    df_odoo = pd.read_csv(ruta_odoo)
    print(f"\n[ODOO] {len(df_odoo)} filas agrupadas")

    # Leer archivo original
    ruta_excel = Path("../datos_entrada/Raw ventas Y.xlsx")
    if not ruta_excel.exists():
        print(f"[ERROR] No existe: {ruta_excel}")
        print(f"        Verifica que Raw ventas Y.xlsx esté en datos_entrada/")
        return

    df_raw = pd.read_excel(ruta_excel, sheet_name='RAW', header=0)

    # Filtrar febrero 2026
    df_excel = df_raw[(df_raw['Año venta'] == 2026) & (df_raw['Mes venta'] == 2)].copy()

    # Agrupar igual a Odoo
    df_excel_agrupado = df_excel.groupby(
        ['Año venta', 'Mes venta', 'Canal', 'Tipo Negocio', 'KAM'],
        as_index=False
    ).agg({
        'Venta bruta': 'sum',
        'Costo Total': 'sum',
        'Margen Front': 'sum',
        'Cantidad': 'sum',
    })

    df_excel_agrupado = df_excel_agrupado.rename(columns={
        'Año venta': 'AÑO',
        'Mes venta': 'Mes',
        'Venta bruta': 'Venta',
        'Costo Total': 'Costo Venta',
        'Margen Front': 'Margen Directo',
    })

    print(f"[EXCEL] {len(df_excel_agrupado)} filas agrupadas")

    # COMPARACION 1: TOTALES GENERALES
    print(f"\n[COMPARACION 1] TOTALES GENERALES\n")
    print(f"{'Métrica':<25} | {'Odoo':>18} | {'Excel':>18} | {'Varianza':>12} | {'Match':>6}")
    print("-" * 90)

    metricas = ['Venta', 'Costo Venta', 'Margen Directo', 'Cantidad']

    for metrica in metricas:
        if metrica in df_odoo.columns and metrica in df_excel_agrupado.columns:
            total_odoo = df_odoo[metrica].sum()
            total_excel = df_excel_agrupado[metrica].sum()
            varianza = ((total_odoo - total_excel) / total_excel * 100) if total_excel != 0 else 0
            match = "OK" if abs(varianza) < 1 else "FALTA"

            print(f"{metrica:<25} | ${total_odoo:>17,.0f} | ${total_excel:>17,.0f} | {varianza:>11.2f}% | {match:>6}")

    # COMPARACION 2: POR CANAL
    print(f"\n[COMPARACION 2] TOTALES POR CANAL\n")
    print(f"{'Canal':<30} | {'Odoo Venta':>15} | {'Excel Venta':>15} | {'Coincide':>10}")
    print("-" * 75)

    coincidencias = 0
    total_canales = 0

    for canal in sorted(df_odoo['Canal'].unique()):
        venta_odoo = df_odoo[df_odoo['Canal'] == canal]['Venta'].sum()
        venta_excel = df_excel_agrupado[df_excel_agrupado['Canal'] == canal]['Venta'].sum()

        diferencia = abs(venta_odoo - venta_excel)
        coincide = diferencia < 100  # Permitir diferencia menor a 100 por redondeo

        if coincide:
            coincidencias += 1
        total_canales += 1

        marca = "[OK]" if coincide else "[DIFF]"
        print(f"{canal:<30} | ${venta_odoo:>14,.0f} | ${venta_excel:>14,.0f} | {marca}")

    print(f"\n[RESULTADO] {coincidencias}/{total_canales} canales coinciden")

    # COMPARACION 3: POR TIPO NEGOCIO
    print(f"\n[COMPARACION 3] POR TIPO NEGOCIO\n")
    print(f"{'Tipo Negocio':<30} | {'Odoo':>15} | {'Excel':>15} | {'Varianza':>10}")
    print("-" * 75)

    for tipo in sorted(df_odoo['Tipo Negocio'].unique()):
        venta_odoo = df_odoo[df_odoo['Tipo Negocio'] == tipo]['Venta'].sum()
        venta_excel = df_excel_agrupado[df_excel_agrupado['Tipo Negocio'] == tipo]['Venta'].sum()

        varianza = ((venta_odoo - venta_excel) / venta_excel * 100) if venta_excel != 0 else 0
        print(f"{tipo:<30} | ${venta_odoo:>14,.0f} | ${venta_excel:>14,.0f} | {varianza:>9.2f}%")

    # DIAGNÓSTICO
    print(f"\n[DIAGNÓSTICO]")
    print("-" * 100)

    if coincidencias == total_canales:
        print("[OK] Extracción Odoo coincide EXACTAMENTE con Raw ventas Y.xlsx")
        print("     LISTO para inyectar en 'Análisis Resultado'")
    else:
        print(f"[AVISO] {total_canales - coincidencias} canales NO coinciden")
        print("\n[PASOS A TOMAR]")
        print("  1. Revisar custom fields en Odoo:")
        print("     - ¿Canal está correctamente asignado en cada orden?")
        print("     - ¿Tipo Negocio está correctamente asignado?")
        print("     - ¿KAM está correctamente asignado?")
        print("     - ¿Hay campos de comisión/logística/marketing?")
        print("\n  2. Actualizar extraer_raw_desde_odoo.py con los nombres correctos")
        print("  3. Ejecutar nuevamente")

    print(f"\n[CUSTOM FIELDS ENCONTRADOS EN ODOO]")
    print("-" * 100)

    # Listar custom fields encontrados
    custom_fields = ['Canal', 'Tipo Negocio', 'KAM']
    for field in custom_fields:
        if field in df_odoo.columns:
            valores = df_odoo[field].unique()[:5]
            print(f"  - {field}: {', '.join(map(str, valores))} ...")
        else:
            print(f"  - {field}: NO ENCONTRADO (falta enriquecer)")

    print(f"\n{'='*100}")


if __name__ == "__main__":
    comparar_extracciones()
