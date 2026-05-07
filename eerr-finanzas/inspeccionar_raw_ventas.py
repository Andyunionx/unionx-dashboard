"""
Inspecciona la estructura exacta del archivo "Raw ventas Y"
Para entender qué datos extraer de Odoo
"""

import pandas as pd
import openpyxl
from pathlib import Path

def inspeccionar_raw():
    """Inspecciona Raw ventas Y"""
    print("\n" + "="*80)
    print(" INSPECCION: RAW VENTAS Y")
    print("="*80)

    ruta = Path("../datos_entrada/Raw ventas Y.xlsx")

    if not ruta.exists():
        print(f"[ERROR] No encontrado: {ruta}")
        return

    try:
        # Ver sheets
        excel_file = pd.ExcelFile(ruta)
        print(f"\n[Archivo] {ruta.name}")
        print(f"[Sheets] {len(excel_file.sheet_names)} encontrados")
        for i, sheet in enumerate(excel_file.sheet_names[:10], 1):
            print(f"  {i}. {sheet}")

        # Leer primer sheet
        primer_sheet = excel_file.sheet_names[0]
        df = pd.read_excel(ruta, sheet_name=primer_sheet, header=0)

        print(f"\n[Sheet activo] {primer_sheet}")
        print(f"[Dimensiones] {df.shape[0]} filas × {df.shape[1]} columnas")

        print(f"\n[COLUMNAS] ({len(df.columns)} totales):")
        for i, col in enumerate(df.columns, 1):
            print(f"  {i:2}. {col}")

        print(f"\n[PRIMERAS 10 FILAS]:")
        print(df.head(10).to_string())

        print(f"\n[TIPOS DE DATOS]:")
        print(df.dtypes)

        print(f"\n[VALORES UNICOS] Muestras:")
        for col in df.columns[:10]:
            unicos = df[col].nunique()
            print(f"  {col}: {unicos} únicos")
            if unicos <= 20:
                print(f"    Valores: {df[col].unique()[:10]}")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()

# ============================================================================
# EJECUTAR
# ============================================================================

if __name__ == "__main__":
    inspeccionar_raw()

    print("\n" + "="*80)
    print(" ANALISIS COMPLETADO")
    print("="*80)
    print("""
Con esta información podemos:
1. Entender exactamente qué columnas tiene el Raw
2. Ver cómo se estructura la información
3. Diseñar un script que obtenga lo mismo desde Odoo
4. Hacer el match de canales entre Odoo y el Raw
    """)
