"""
PASO 3a.1: Leer RAW VENTAS Y
Agrupa por: Año, Mes, Canal, Tipo Negocio, KAM
Suma: Venta, Costo, Margen Directo
Crea DataFrame listo para inyectar en "Análisis Resultado"
"""

import pandas as pd
from pathlib import Path
from datetime import datetime

class AgregadorRawVentas:
    """Lee Raw ventas y agrupa por período/canal"""

    def __init__(self):
        self.ruta_raw = Path("../datos_entrada/Raw ventas Y.xlsx")
        self.ruta_salida = Path("data/outputs/raw_agregado_febrero_2026.csv")
        self.ruta_salida.parent.mkdir(parents=True, exist_ok=True)

    def leer_raw(self):
        """Lee el sheet RAW"""
        print(f"\n[Leyendo] {self.ruta_raw.name}")
        df = pd.read_excel(self.ruta_raw, sheet_name='RAW', header=0)
        print(f"[OK] {df.shape[0]:,} filas cargadas")
        return df

    def filtrar_febrero(self, df):
        """Filtra por Febrero 2026"""
        print(f"\n[Filtrando] Febrero 2026 (Año=2026, Mes=2)")

        df_febrero = df[(df['Año venta'] == 2026) & (df['Mes venta'] == 2)].copy()

        print(f"[OK] {df_febrero.shape[0]:,} filas de febrero 2026")
        print(f"[Canales encontrados] {df_febrero['Canal'].nunique()}")
        print(f"[Negocios encontrados] {df_febrero['Tipo Negocio'].nunique()}")
        print(f"[KAMs encontrados] {df_febrero['KAM'].nunique()}")

        return df_febrero

    def agregar_por_canal(self, df):
        """Agrupa por Año, Mes, Canal, Tipo Negocio, KAM"""
        print(f"\n[Agrupando] Por período/canal/negocio/kam")

        # Agrupar y sumar
        df_agrupado = df.groupby(
            ['Año venta', 'Mes venta', 'Canal', 'Tipo Negocio', 'KAM'],
            as_index=False
        ).agg({
            'Venta bruta': 'sum',
            'Costo Total': 'sum',
            'Margen Front': 'sum',
            'Cantidad': 'sum'
        })

        # Renombrar columnas para coincidir con "Análisis Resultado"
        df_agrupado = df_agrupado.rename(columns={
            'Año venta': 'AÑO',
            'Mes venta': 'Mes',
            'Canal': 'Canal',
            'Tipo Negocio': 'Negocio',
            'Venta bruta': 'Venta',
            'Costo Total': 'Costo Venta',
            'Margen Front': 'Margen Directo',
            'Cantidad': 'Cantidad'
        })

        # Reordenar columnas para coincidir con estructura de "Análisis Resultado"
        columnas_orden = [
            'AÑO', 'Negocio', 'Canal', 'KAM', 'Mes',
            'Venta', 'Costo Venta', 'Margen Directo', 'Cantidad'
        ]

        df_agrupado = df_agrupado[columnas_orden]

        print(f"[OK] {df_agrupado.shape[0]} filas agrupadas")

        return df_agrupado

    def validar_totales(self, df_raw_filtrado, df_agrupado):
        """Valida que los totales coincidan"""
        print(f"\n[VALIDACION] Comparar totales")

        venta_raw = df_raw_filtrado['Venta bruta'].sum()
        costo_raw = df_raw_filtrado['Costo Total'].sum()
        margen_raw = df_raw_filtrado['Margen Front'].sum()

        venta_agrupado = df_agrupado['Venta'].sum()
        costo_agrupado = df_agrupado['Costo Venta'].sum()
        margen_agrupado = df_agrupado['Margen Directo'].sum()

        print(f"\n  Venta bruta:")
        print(f"    Raw filtrado:  ${venta_raw:,.2f}")
        print(f"    Agrupado:      ${venta_agrupado:,.2f}")
        print(f"    Coinciden:     {abs(venta_raw - venta_agrupado) < 1}")

        print(f"\n  Costo total:")
        print(f"    Raw filtrado:  ${costo_raw:,.2f}")
        print(f"    Agrupado:      ${costo_agrupado:,.2f}")
        print(f"    Coinciden:     {abs(costo_raw - costo_agrupado) < 1}")

        print(f"\n  Margen directo:")
        print(f"    Raw filtrado:  ${margen_raw:,.2f}")
        print(f"    Agrupado:      ${margen_agrupado:,.2f}")
        print(f"    Coinciden:     {abs(margen_raw - margen_agrupado) < 1}")

    def mostrar_resumen(self, df):
        """Muestra resumen por canal"""
        print(f"\n[RESUMEN] Top 10 Canales por Margen Directo")
        print("="*100)

        df_top = df.nlargest(10, 'Margen Directo')[
            ['Canal', 'Negocio', 'Venta', 'Costo Venta', 'Margen Directo']
        ].copy()

        for idx, (i, row) in enumerate(df_top.iterrows(), 1):
            print(f"{idx:2}. {row['Canal']:30} | {row['Negocio']:20} | Venta: ${row['Venta']:>12,.0f} | Margen: ${row['Margen Directo']:>12,.0f}")

    def guardar_csv(self, df):
        """Guarda en CSV"""
        print(f"\n[Guardando] {self.ruta_salida.name}")
        df.to_csv(self.ruta_salida, index=False)
        print(f"[OK] {self.ruta_salida}")

    def ejecutar(self):
        """Ejecuta el proceso completo"""
        print("\n" + "="*100)
        print(" PASO 3a.1: AGREGAR RAW VENTAS POR CANAL")
        print("="*100)

        try:
            # Leer
            df_raw = self.leer_raw()

            # Filtrar febrero
            df_febrero = self.filtrar_febrero(df_raw)

            # Agrupar
            df_agrupado = self.agregar_por_canal(df_febrero)

            # Validar
            self.validar_totales(df_febrero, df_agrupado)

            # Mostrar
            self.mostrar_resumen(df_agrupado)

            # Guardar
            self.guardar_csv(df_agrupado)

            print(f"\n" + "="*100)
            print(" LISTO PARA INYECTAR EN 'ANÁLISIS RESULTADO'")
            print("="*100)

            return df_agrupado

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            return None

# ============================================================================
# EJECUTAR
# ============================================================================

if __name__ == "__main__":
    agregador = AgregadorRawVentas()
    df_resultado = agregador.ejecutar()

    if df_resultado is not None:
        print(f"\n[PROXIMO PASO] PASO 3b: Mapear EERR + Skill Distribución")
