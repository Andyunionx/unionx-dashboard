"""
PASO 2: Extraer datos de FEBRERO 2026 por CANAL
Lee "Análisis Resultados" y suma por canal de venta
"""

import pandas as pd
from pathlib import Path

def extraer_febrero_2026():
    """Extrae datos de Febrero 2026 por canal"""
    print("\n" + "="*80)
    print(" PASO 2: EXTRACCION DATOS FEBRERO 2026 POR CANAL")
    print("="*80)

    ruta = Path("../data/planillas/Análisis Contribución 2026 V02.02.xlsx")

    try:
        # Leer el sheet "Análisis Resultados"
        print(f"\n[Leyendo] {ruta.name}")
        print(f"[Sheet] 'Análisis Resultados'")

        df = pd.read_excel(ruta, sheet_name='Análisis Resultados', header=0)

        print(f"\n[OK] Datos leídos: {df.shape[0]} filas × {df.shape[1]} columnas")

        # Ver columnas
        print(f"\n[Columnas disponibles]:")
        for i, col in enumerate(df.columns[:15], 1):
            print(f"  {i:2}. {col}")

        # Filtrar por Febrero 2026
        # Buscar columna que contenga mes/período
        mes_col = None
        for col in df.columns:
            if 'mes' in str(col).lower() or 'periodo' in str(col).lower():
                mes_col = col
                break

        print(f"\n[Columna Mes] {mes_col}")

        # Ver valores únicos de mes
        if mes_col:
            periodos = df[mes_col].unique()
            print(f"\n[Períodos encontrados] {len(periodos)} únicos")
            for p in sorted(periodos)[:20]:
                print(f"  - {p}")

        # Buscar Febrero específicamente
        # En el archivo parece que es "2 Q1" para trimestre Q1
        # Vamos a buscar todas las variantes

        print(f"\n[Buscando FEBRERO 2026...]")

        # Estrategia: buscar filas donde:
        # - AÑO = 2026
        # - Mes contenga "febrero" O "2" (segunda del mes)

        año_col = None
        for col in df.columns:
            if 'año' in str(col).lower():
                año_col = col
                break

        if año_col:
            df_2026 = df[df[año_col] == 2026].copy()
            print(f"\n[Filas año 2026] {len(df_2026)}")
        else:
            df_2026 = df.copy()

        # Buscar febrero
        # Probar diferentes formas
        df_febrero = None

        # Opción 1: Buscar en columna mes
        if mes_col:
            febrero_masks = (
                (df_2026[mes_col].astype(str).str.contains('febrero', case=False, na=False)) |
                (df_2026[mes_col].astype(str).str.contains('2', case=False, na=False))
            )
            df_febrero = df_2026[febrero_masks].copy()

        if df_febrero is None or len(df_febrero) == 0:
            print("\n[AVISO] No se encontró columna clara de mes")
            print("[Mostrando todas las filas 2026]")
            df_febrero = df_2026.copy()

        print(f"\n[Filas Febrero 2026] {len(df_febrero)}")

        # Agrupar por CANAL
        canal_col = None
        for col in df.columns:
            if 'canal' in str(col).lower():
                canal_col = col
                break

        if not canal_col:
            print("[AVISO] No se encontró columna 'Canal'")
            print("[Mostrando primeras 10 filas sin agrupar]")
            print(df_febrero.head(10).to_string())
            return

        print(f"\n[Columna Canal] {canal_col}")
        print(f"\n[Canales encontrados] {df_febrero[canal_col].nunique()} únicos")

        # Columnas de datos a sumar
        columnas_datos = {
            'Costo Venta': 'costo',
            'Margen Directo': 'margen_directo',
            'Comisión Venta': 'comision_venta',
            'Comisión Envío': 'comision_envio',
            'Marketing': 'marketing',
            'Total Comisiones': 'total_comisiones',
            'Contribución': 'contribucion'
        }

        # Encontrar las columnas en el dataframe
        columnas_encontradas = {}
        for col_buscada, alias in columnas_datos.items():
            for col_real in df.columns:
                if col_buscada.lower() in str(col_real).lower():
                    columnas_encontradas[alias] = col_real
                    break

        print(f"\n[Columnas de datos encontradas]")
        for alias, col_real in columnas_encontradas.items():
            print(f"  {alias:20} -> {col_real}")

        # Agrupar por canal
        if canal_col and columnas_encontradas:
            print(f"\n[RESUMEN POR CANAL - FEBRERO 2026]")
            print("="*80)

            # Crear resumen
            resumen_por_canal = []

            for canal in sorted(df_febrero[canal_col].unique()):
                if pd.isna(canal):
                    continue

                datos_canal = df_febrero[df_febrero[canal_col] == canal]

                fila_resumen = {
                    'Canal': canal,
                    'Filas': len(datos_canal)
                }

                # Sumar datos
                for alias, col_real in columnas_encontradas.items():
                    if col_real in df.columns:
                        valor = pd.to_numeric(datos_canal[col_real], errors='coerce').sum()
                        fila_resumen[alias] = valor

                resumen_por_canal.append(fila_resumen)

            df_resumen = pd.DataFrame(resumen_por_canal)

            # Mostrar resultado
            print(f"\n{df_resumen.to_string()}")

            # Totales
            print(f"\n[TOTALES FEBRERO 2026]")
            totales = df_resumen.select_dtypes(include=['number']).sum()
            print(f"{totales.to_string()}")

            # Guardar en CSV para validar
            csv_path = Path("data/outputs/febrero_2026_resumen_canales.csv")
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            df_resumen.to_csv(csv_path, index=False)
            print(f"\n[OK] Guardado en: {csv_path.name}")

        else:
            print("[ERROR] No se pudieron encontrar columnas necesarias")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()

# ============================================================================
# EJECUTAR
# ============================================================================

if __name__ == "__main__":
    extraer_febrero_2026()

    print("\n" + "="*80)
    print(" PROXIMO PASO:")
    print("="*80)
    print("""
1. Valida que los números coincidan con lo que ves en el archivo Excel
2. Si coinciden, podemos proceder a automatizar
3. Si no coinciden, ajustamos la lógica de extracción

Para validar:
- Abre el archivo "Análisis Contribución 2026"
- Ve a sheet "Análisis Resultados"
- Filtra por Febrero 2026
- Compara los números que viste aquí con los del resumen por canal
    """)
