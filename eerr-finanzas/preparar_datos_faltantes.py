"""
Prepara datos faltantes:
1. Descarga Sueldos Febrero desde Gmail
2. Extrae Ventas de Odoo
3. Valida que todos los archivos estén en datos_entrada/
"""

from pathlib import Path
import subprocess
import sys

def main():
    print("\n" + "="*70)
    print("PREPARAR DATOS FALTANTES")
    print("="*70)

    # Carpeta de destino
    datos_entrada = Path("../datos_entrada")
    datos_entrada.mkdir(parents=True, exist_ok=True)

    # 1. Intentar descargar sueldos desde Gmail
    print("\n[PASO 1/2] Descargando Sueldos Febrero desde Gmail...")
    try:
        result = subprocess.run(
            [sys.executable, "descargar_sueldos_gmail.py"],
            capture_output=False,
            text=True
        )
        if result.returncode == 0:
            print("[OK] Sueldos descargados")
        else:
            print("[AVISO] No se pudo descargar desde Gmail (ver instrucciones arriba)")
    except Exception as e:
        print(f"[ERROR] {e}")

    # 2. Intentar extraer ventas de Odoo
    print("\n[PASO 2/2] Extrayendo Ventas de Odoo...")
    try:
        result = subprocess.run(
            [sys.executable, "extraer_ventas_odoo.py"],
            capture_output=False,
            text=True
        )
        if result.returncode == 0:
            print("[OK] Ventas extraídas")
        else:
            print("[AVISO] No se pudo extraer desde Odoo (ver instrucciones arriba)")
    except Exception as e:
        print(f"[ERROR] {e}")

    # 3. Validar archivos
    print("\n" + "="*70)
    print("VALIDACIÓN DE ARCHIVOS")
    print("="*70)

    archivos_esperados = {
        "Presupuesto_Febrero_2026.xlsx": "Presupuesto",
        "Sueldos_Febrero_2026.xlsx": "Sueldos",
        "Balance_Febrero_2026.xlsx": "Balance",
        "Comex_Maestra.xlsx": "COMEX (Excel)",
        "comex_maestra_cc.json": "COMEX (JSON)",
        "Planificación Financiera.xlsx": "Planificación Financiera",
        "GoogleSheet_Ventas_Export.xlsx": "Ventas (opcional)"
    }

    print(f"\nArchivos en: {datos_entrada}\n")

    archivos_encontrados = list(datos_entrada.glob("*"))
    encontrados = {f.name: True for f in archivos_encontrados}

    for archivo, desc in archivos_esperados.items():
        if archivo in encontrados:
            print(f"✅ {archivo:40} [{desc}]")
        else:
            print(f"❌ {archivo:40} [{desc}]")

    # Resumen
    ok_count = sum(1 for f in archivos_esperados if f in encontrados)
    total_count = len(archivos_esperados)

    print(f"\n{'='*70}")
    print(f"Archivos: {ok_count - 1}/{total_count - 1} (Ventas es opcional)")
    print(f"{'='*70}")

    if ok_count >= 5:  # Al menos 5 sin contar ventas
        print("\n✅ LISTO PARA EJECUTAR REPORTES")
        print("\nSiguiente paso:")
        print("  python ingestar_datos_desde_desktop.py")
        print("  python orquestador_reportes.py")
        return True
    else:
        print("\n⚠️  Faltan archivos. Ver instrucciones de descarga manual arriba.")
        return False


if __name__ == "__main__":
    exito = main()
    sys.exit(0 if exito else 1)
