"""
PASO 3a COMPLETO: Extrae RAW desde Odoo, valida y lo inyecta en Análisis Resultado

Flujo:
1. Conecta a Odoo y extrae sale.order.line de febrero 2026
2. Enriquece con datos del producto y la orden (40 columnas)
3. Agrupa por período/canal/negocio/KAM
4. Valida contra Raw ventas Y.xlsx
5. Inyecta en "Análisis Resultado" sin borrar histórico

Uso:
    python paso3a_ejecutar_completo.py
"""

import sys
from pathlib import Path

# Agregar ruta de módulos
sys.path.insert(0, str(Path(__file__).parent))

def ejecutar_paso3a():
    """Ejecuta PASO 3a completo"""

    print("\n" + "="*100)
    print(" PASO 3a: EXTRAE RAW DESDE ODOO Y LO INYECTA EN ANÁLISIS RESULTADO")
    print("="*100)

    # PASO 1: Extraer desde Odoo
    print("\n[PASO 3a.1/4] Extrayendo desde Odoo...")
    print("-" * 100)

    try:
        from extraer_raw_desde_odoo import ExtraerRawOdoo

        extractor = ExtraerRawOdoo()
        df_odoo = extractor.ejecutar()

        if df_odoo is None or df_odoo.empty:
            print("\n[ERROR] No se pudo extraer desde Odoo.")
            print("[ALTERNATIVA] Asegúrate de que:")
            print("  1. Raw ventas Y.xlsx está en datos_entrada/")
            print("  2. Ejecuta paso3a_desde_excel.py como alternativa")
            return False

    except ImportError as e:
        print(f"[ERROR] Módulo no encontrado: {e}")
        print("[ALTERNATIVA] Ejecuta paso3a_desde_excel.py")
        return False

    # PASO 2: Validar
    print("\n[PASO 3a.2/4] Validando extracción...")
    print("-" * 100)

    try:
        from validar_extraccion_odoo import comparar_extracciones
        comparar_extracciones()

    except Exception as e:
        print(f"[AVISO] No se pudo ejecutar validación: {e}")

    # PASO 3: Inyectar
    print("\n[PASO 3a.3/4] Inyectando en Análisis Resultado...")
    print("-" * 100)

    try:
        from inyectar_raw_analisis_resultado import InyectarRawAnalisis

        inyector = InyectarRawAnalisis()
        exito = inyector.ejecutar()

        if not exito:
            print("\n[AVISO] Revisa los detalles del error arriba.")
            return False

    except Exception as e:
        print(f"[ERROR] No se pudo inyectar: {e}")
        import traceback
        traceback.print_exc()
        return False

    # PASO 4: Resumen
    print("\n[PASO 3a.4/4] Resumen")
    print("-" * 100)

    print(f"""
[EXITO] PASO 3a completado

    Datos extraídos de Odoo: Febrero 2026
    Canales procesados: {len(df_odoo) if df_odoo is not None else 0}
    Destino: Análisis Contribución 2026 > Análisis Resultados

[SIGUIENTE]
    Las tablas dinámicas en 'Análisis Contribución' se actualizarán automáticamente
    Los reportes semanales ya tienen datos frescos

    Próximo paso: PASO 3b - Mapear EERR + Skill distribución
""")

    return True


def main():
    """Punto de entrada"""

    import argparse

    parser = argparse.ArgumentParser(description="Ejecuta PASO 3a: Extrae RAW desde Odoo")
    parser.add_argument('--help-odoo', action='store_true', help="Muestra instrucciones de conexión Odoo")
    parser.add_argument('--desde-excel', action='store_true', help="Usa Raw ventas Y.xlsx en lugar de Odoo")

    args = parser.parse_args()

    if args.help_odoo:
        print("""
[CONEXION ODOO]

Requisitos:
  1. Usuario activo en Odoo: andres@grupoeter.cl
  2. Password guardado en .env como ANDRES_ODOO_PASSWORD
  3. Acceso a módulos: Ventas (sale), Productos (product), Contabilidad (account)

Si no tienes acceso:
  1. Abre: https://unionxb2b.odoo.com
  2. Genera un "Application Token" en tu perfil
  3. Usa el token como password en lugar de tu contraseña

Alternativa:
  python paso3a_desde_excel.py
  (Usa Raw ventas Y.xlsx en lugar de Odoo directo)
""")
        return

    if args.desde_excel:
        print("\n[OPCION ALTERNATIVA] Ejecutando desde Excel...")
        import subprocess
        resultado = subprocess.run(
            ["python", "paso3a_desde_excel.py"],
            cwd=Path(__file__).parent
        )
        sys.exit(resultado.returncode)

    # Ejecutar PASO 3a
    exito = ejecutar_paso3a()

    if exito:
        print("\n[OK] PASO 3a completado exitosamente")
        sys.exit(0)
    else:
        print("\n[ERROR] PASO 3a falló. Revisa los logs arriba.")
        sys.exit(1)


if __name__ == "__main__":
    main()
