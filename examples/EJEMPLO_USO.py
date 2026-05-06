#!/usr/bin/env python3
"""
EJEMPLO: Procesar EERR con clasificación automática + distribución por canal
Ejecutar: python EJEMPLO_USO.py
"""

import sys
from pathlib import Path

# Importar módulos
from eerr_classifier import EERRClassifier, EERRExporter
from integracion_distribucion_comisiones import (
    DistribuidorComisiones,
    procesar_eerr_completo
)


def ejemplo_1_clasificacion_simple():
    """Ejemplo básico: Clasificar algunos movimientos"""
    print("\n" + "="*70)
    print("EJEMPLO 1: CLASIFICACIÓN SIMPLE")
    print("="*70)

    classifier = EERRClassifier()

    # Datos de prueba
    movimientos = [
        {
            "codigo": "41410101",
            "glosa": "Venta Recíbelo abril",
            "contraparte": "RECIBELO",
            "cuenta": "Ingresos",
            "saldo": 1500.50
        },
        {
            "codigo": "43420101",
            "glosa": "Sueldo GRUPO ETER CONTABILIDAD",
            "contraparte": "",
            "cuenta": "Remuneraciones",
            "saldo": -250.00
        },
        {
            "codigo": "42410401",
            "glosa": "Publicidad GOOGLE ADS",
            "contraparte": "GOOGLE IRELAND",
            "cuenta": "Marketing",
            "saldo": -300.00
        },
        {
            "codigo": "43420116",
            "glosa": "Suscripción software CLAUDE",
            "contraparte": "ANTHROPIC",
            "cuenta": "Servicios",
            "saldo": -15.00
        },
    ]

    print("\n📋 MOVIMIENTOS A CLASIFICAR:")
    for i, mov in enumerate(movimientos, 1):
        print(f"\n{i}. {mov['codigo']} - {mov['glosa'][:50]}")
        print(f"   Contraparte: {mov['contraparte']}")
        print(f"   Saldo: M$ {mov['saldo']:.2f}")

    # Clasificar
    filas_procesadas, stats = classifier.procesar_eerr(movimientos)

    print("\n" + "-"*70)
    print("RESULTADO DE CLASIFICACIÓN:")
    print("-"*70)

    for fila in filas_procesadas:
        cls = fila.clasificacion
        print(f"\n✓ {fila.codigo}")
        print(f"  Glosa: {fila.glosa}")
        print(f"  Saldo: M$ {fila.saldo}")
        print(f"  → {cls.ln} | {cls.cc} | {cls.ca}")

    print("\n" + "-"*70)
    print("ESTADÍSTICAS:")
    print("-"*70)
    for key, val in stats.items():
        print(f"  {key.replace('_', ' ').title():.<30} {val}")


def ejemplo_2_distribucion_por_canal():
    """Ejemplo 2: Distribuir por canal de venta"""
    print("\n" + "="*70)
    print("EJEMPLO 2: DISTRIBUCIÓN POR CANAL")
    print("="*70)

    # Reutilizar datos del ejemplo 1
    classifier = EERRClassifier()
    movimientos = [
        {
            "codigo": "41410101",
            "glosa": "Venta Recíbelo",
            "contraparte": "RECIBELO",
            "cuenta": "Ingresos",
            "saldo": 1500.50
        },
        {
            "codigo": "41410109",
            "glosa": "Venta Blue Express",
            "contraparte": "BLUE EXPRESS",
            "cuenta": "Ingresos",
            "saldo": 800.00
        },
        {
            "codigo": "43420101",
            "glosa": "Sueldo GRUPO ETER",
            "contraparte": "",
            "cuenta": "Remuneraciones",
            "saldo": -250.00
        },
    ]

    filas_procesadas, _ = classifier.procesar_eerr(movimientos)

    # Distribuir
    distribuidor = DistribuidorComisiones()
    distribucion = distribuidor.procesar_eerr(
        filas_procesadas,
        mes="Abril",
        ano=2026
    )

    print("\n📊 DISTRIBUCIÓN POR CANAL:")
    print("-"*70)

    for canal, resumen in distribucion["resumen"].items():
        if resumen["cantidad"] > 0:
            print(f"\n🔹 {canal.replace('_', ' ').upper()}")
            print(f"   Movimientos: {resumen['cantidad']}")
            print(f"   Monto total: M$ {resumen['monto_total']:.2f}")

    # Detallar
    print("\n" + "-"*70)
    print("DETALLE POR CANAL:")
    print("-"*70)

    for canal, movimientos in distribucion["canales"].items():
        if not movimientos:
            continue
        print(f"\n📌 {canal.replace('_', ' ').upper()}")
        for mov in movimientos:
            print(f"  - {mov['glosa'][:40]:<40} M$ {mov['saldo_miles']:>10.2f}")


def ejemplo_3_exportar_json():
    """Ejemplo 3: Exportar en formato JSON para la skill"""
    print("\n" + "="*70)
    print("EJEMPLO 3: EXPORTAR PARA SKILL (JSON)")
    print("="*70)

    classifier = EERRClassifier()
    movimientos = [
        {"codigo": "41410101", "glosa": "Venta Recíbelo", "contraparte": "RECIBELO",
         "cuenta": "Ingresos", "saldo": 1500.50},
        {"codigo": "43420101", "glosa": "Sueldo GRUPO ETER", "contraparte": "",
         "cuenta": "Remuneraciones", "saldo": -250.00},
    ]

    filas_procesadas, _ = classifier.procesar_eerr(movimientos)
    distribuidor = DistribuidorComisiones()
    distribucion = distribuidor.procesar_eerr(filas_procesadas, "Abril")

    # Exportar JSON
    output_file = "ejemplo_distribucion.json"
    DistribuidorComisiones.a_json_skill(distribucion, output_file)

    print(f"\n✓ Archivo '{output_file}' generado")
    print("\nEstructura JSON:")
    print("-"*70)

    import json
    with open(output_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"Canales: {list(data['canales'].keys())}")
    print(f"Total movimientos: {sum(v['cantidad'] for v in data['resumen'].values())}")
    print(f"Total monto: M$ {sum(v['monto_total'] for v in data['resumen'].values()):.2f}")

    print("\nEste JSON se usa en la skill 'distribucion-comisiones-canal'")


def ejemplo_4_pipeline_completo():
    """Ejemplo 4: Pipeline completo (si tienes un EERR en Excel)"""
    print("\n" + "="*70)
    print("EJEMPLO 4: PIPELINE COMPLETO (CON ARCHIVO EXCEL)")
    print("="*70)

    ruta_eerr = "mi_eerr_abril.xlsx"

    if not Path(ruta_eerr).exists():
        print(f"\n❌ Archivo no encontrado: {ruta_eerr}")
        print("\nPara usar este ejemplo:")
        print("  1. Coloca tu EERR en Excel en la misma carpeta")
        print("  2. Nómbralo 'mi_eerr_abril.xlsx'")
        print("  3. Asegúrate de que tenga columnas: Código, Glosa, Contraparte, Cuenta, Saldo")
        print("\nEjemplo de uso:")
        print("  filas, dist = procesar_eerr_completo('mi_eerr_abril.xlsx', 'Abril')")
        return

    print(f"\nProcesando {ruta_eerr}...")
    filas_procesadas, distribucion = procesar_eerr_completo(ruta_eerr, "Abril")

    if filas_procesadas:
        print("\n✅ PIPELINE COMPLETADO")
        print(f"\nArchivos generados:")
        print(f"  - mi_eerr_CLASIFICADO.xlsx")
        print(f"  - mi_eerr_CLASIFICADO.json")
        print(f"  - mi_eerr_DISTRIBUCION_CANALES.json  ← Para la skill")
        print(f"  - mi_eerr_REPORTE_CANALES.html")


def menu_principal():
    """Menú interactivo"""
    print("\n" + "="*70)
    print("🎯 EERR CLASSIFIER - EJEMPLOS DE USO")
    print("="*70)
    print("\nElige un ejemplo para ejecutar:\n")
    print("1️⃣  Clasificación Simple (4 movimientos)")
    print("2️⃣  Distribución por Canal")
    print("3️⃣  Exportar JSON para Skill")
    print("4️⃣  Pipeline Completo (con archivo Excel)")
    print("0️⃣  Salir")

    opcion = input("\nOpción (0-4): ").strip()

    if opcion == "1":
        ejemplo_1_clasificacion_simple()
    elif opcion == "2":
        ejemplo_2_distribucion_por_canal()
    elif opcion == "3":
        ejemplo_3_exportar_json()
    elif opcion == "4":
        ejemplo_4_pipeline_completo()
    elif opcion == "0":
        print("\n👋 ¡Hasta luego!")
        return False
    else:
        print("\n❌ Opción no válida")

    return True


if __name__ == "__main__":
    print("\n📚 Sistema de Clasificación EERR - Ejemplos\n")

    # Si se pasa argumento, ejecutar ese ejemplo
    if len(sys.argv) > 1:
        opt = sys.argv[1]
        if opt == "1":
            ejemplo_1_clasificacion_simple()
        elif opt == "2":
            ejemplo_2_distribucion_por_canal()
        elif opt == "3":
            ejemplo_3_exportar_json()
        elif opt == "4":
            ejemplo_4_pipeline_completo()
        else:
            print("Uso: python EJEMPLO_USO.py [1|2|3|4]")
    else:
        # Menú interactivo
        while menu_principal():
            input("\n\nPresiona Enter para continuar...")
