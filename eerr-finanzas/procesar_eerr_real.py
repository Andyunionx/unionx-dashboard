"""
Procesa el EERR real de Febrero 2026
Ejecutar: python procesar_eerr_real.py
"""

import sys
import os
from pathlib import Path

# Configurar encoding UTF-8 para Windows
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Agregar ruta al módulo
sys.path.insert(0, str(Path(__file__).parent))

from integracion_distribucion_comisiones import procesar_eerr_completo

def main():
    # Ruta al EERR real
    ruta_eerr = "Junior Revenue/EERR/02 EE.RR Febrero 2026.xlsx"

    print("\n" + "="*70)
    print("🔄 PROCESANDO EERR REAL - FEBRERO 2026")
    print("="*70)

    if not Path(ruta_eerr).exists():
        print(f"\n❌ Error: No se encontró {ruta_eerr}")
        print("\n💡 Verifica que el archivo esté en:")
        print(f"   {Path(ruta_eerr).absolute()}")
        return

    print(f"\n📁 Archivo: {ruta_eerr}")
    print(f"   Tamaño: {Path(ruta_eerr).stat().st_size / 1024:.1f} KB")

    try:
        # Procesar
        filas_procesadas, distribucion = procesar_eerr_completo(ruta_eerr, "Febrero", 2026)

        if filas_procesadas:
            print("\n" + "="*70)
            print("✅ PROCESAMIENTO EXITOSO")
            print("="*70)

            # Resumen
            total = len(filas_procesadas)
            clasificadas = sum(1 for f in filas_procesadas if f.clasificacion and f.clasificacion.ln)
            sin_clasificar = total - clasificadas

            print(f"\n📊 RESUMEN:")
            print(f"   Total filas procesadas: {total}")
            print(f"   Clasificadas: {clasificadas} ({100*clasificadas/total:.1f}%)")
            print(f"   Sin clasificar: {sin_clasificar}")

            print(f"\n💰 DISTRIBUCIÓN POR LÍNEA DE NEGOCIO:")
            for key, val in distribucion["resumen"].items():
                if val["cantidad"] > 0:
                    print(f"   {key:.<30} {val['cantidad']:>3} movimientos | M$ {val['monto_total']:>10.2f}")

            print(f"\n📁 ARCHIVOS GENERADOS:")
            print(f"   ✓ 02 EE.RR Febrero 2026_CLASIFICADO.xlsx")
            print(f"   ✓ 02 EE.RR Febrero 2026_CLASIFICADO.json")
            print(f"   ✓ 02 EE.RR Febrero 2026_DISTRIBUCION_CANALES.json  ← Para skill")
            print(f"   ✓ 02 EE.RR Febrero 2026_REPORTE_CANALES.html")

            # Detalles de clasificación
            print(f"\n🎯 DETALLE DE CLASIFICACIONES (primeras 10):")
            print("-" * 70)
            for i, fila in enumerate(filas_procesadas[:10], 1):
                cls = fila.clasificacion
                if cls.ln:
                    print(f"\n{i}. {fila.codigo} | {fila.glosa[:40]}")
                    print(f"   → {cls.ln:15} | {cls.cc:20} | {cls.ca}")
                    print(f"   Saldo: M$ {fila.saldo:.2f}")

            if len(filas_procesadas) > 10:
                print(f"\n... y {len(filas_procesadas) - 10} movimientos más")

            # Alertas si hay sin clasificar
            if sin_clasificar > 0:
                print(f"\n⚠️  ATENCIÓN: {sin_clasificar} fila(s) sin clasificar automática")
                print("   Revisa el Excel para asignarlas manualmente")

    except Exception as e:
        print(f"\n❌ Error al procesar: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
