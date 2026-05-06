"""
Generador de Excel con 5 hojas (Ventas + 4 resúmenes).
Replica exactamente la lógica del script original.
"""
from io import BytesIO
import pandas as pd


class ExcelBuilder:
    """
    Construye un Excel con múltiples hojas a partir de DataFrames.
    Retorna BytesIO para enviar directamente sin escribir en disco.
    """

    @staticmethod
    def build(df_ventas, resumen_linea, resumen_canal, resumen_categoria, resumen_bodega,
              periodo_nombre: str) -> BytesIO:
        """
        Construye un Excel con 5 hojas.

        Args:
            df_ventas: DataFrame con detalle de ventas (10,110 líneas × 39 columnas)
            resumen_linea: DataFrame con resumen por Línea de Negocio
            resumen_canal: DataFrame con resumen por Canal
            resumen_categoria: DataFrame con resumen por Categoría
            resumen_bodega: DataFrame con resumen por Bodega
            periodo_nombre: Nombre del período (ej: 'abril_2026')

        Returns:
            BytesIO con el Excel generado
        """
        output = BytesIO()

        try:
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Hoja 1: Detalle completo
                df_ventas.to_excel(writer, sheet_name='Ventas', index=False)

                # Hojas 2-5: Resúmenes
                resumen_linea.to_excel(writer, sheet_name='Resumen Linea Negocio', index=False)
                resumen_canal.to_excel(writer, sheet_name='Resumen Canal', index=False)
                resumen_categoria.to_excel(writer, sheet_name='Resumen Categoria', index=False)
                resumen_bodega.to_excel(writer, sheet_name='Resumen Bodega', index=False)

            output.seek(0)
            return output

        except Exception as e:
            raise RuntimeError(f"Error generando Excel: {e}")

    @staticmethod
    def build_to_file(df_ventas, resumen_linea, resumen_canal, resumen_categoria, resumen_bodega,
                     filepath: str, periodo_nombre: str):
        """
        Alternativa: guarda el Excel en disco (para debugging o análisis local).
        """
        try:
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                df_ventas.to_excel(writer, sheet_name='Ventas', index=False)
                resumen_linea.to_excel(writer, sheet_name='Resumen Linea Negocio', index=False)
                resumen_canal.to_excel(writer, sheet_name='Resumen Canal', index=False)
                resumen_categoria.to_excel(writer, sheet_name='Resumen Categoria', index=False)
                resumen_bodega.to_excel(writer, sheet_name='Resumen Bodega', index=False)

            print(f"[OK] Excel guardado en {filepath}")
            return filepath

        except Exception as e:
            raise RuntimeError(f"Error guardando Excel: {e}")
