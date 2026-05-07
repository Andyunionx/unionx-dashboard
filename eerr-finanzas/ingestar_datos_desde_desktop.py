"""
INGESTADOR DE DATOS REALES
Lee archivos que Andres carga en datos_entrada/ y los adapta para reportes

Estructura esperada:
  ../datos_entrada/
  ├── Presupuesto_Febrero_2026.xlsx
  ├── Sueldos_Febrero_2026.xlsx
  ├── Balance_Febrero_2026.xlsx
  ├── Comex_Maestra.xlsx o .json
  ├── Planificacion_Financiera.xlsx
  └── (OPCIONAL) GoogleSheet_Ventas_Export.xlsx

Ejecutar:
  python ingestar_datos_desde_desktop.py

Resultado:
  Copia archivos a data/planillas/ y data/outputs/ con nombres correctos
"""

import shutil
from pathlib import Path
import openpyxl
import json
from datetime import datetime


class IngestadorDatos:
    """Lee archivos desde Desktop y los adapta para reportes"""

    def __init__(self):
        # Leer desde carpeta datos_entrada/ dentro de UNION X - IA
        self.datos_entrada = Path("../datos_entrada")
        self.datos_planillas = Path("../data/planillas")
        self.datos_outputs = Path("../data/outputs")
        self.mes_actual = datetime.now().strftime("%B_%Y").replace(" ", "_")

        # Crear carpetas si no existen
        self.datos_planillas.mkdir(parents=True, exist_ok=True)
        self.datos_outputs.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*70}")
        print(f"INGESTADOR DE DATOS DESDE DESKTOP")
        print(f"{'='*70}")
        print(f"\nBuscando datos en: {self.datos_entrada}")
        print(f"Destino: {self.datos_planillas} y {self.datos_outputs}")

    def verificar_carpeta_entrada(self) -> bool:
        """Verifica que existe carpeta con datos"""
        if not self.datos_entrada.exists():
            self.datos_entrada.mkdir(parents=True, exist_ok=True)
            print(f"\n[OK] Carpeta creada: {self.datos_entrada}")
            print(f"\nColoca tus archivos en:")
            print(f"  {self.datos_entrada}/")
            print(f"    ├── Presupuesto_Febrero_2026.xlsx")
            print(f"    ├── Sueldos_Febrero_2026.xlsx")
            print(f"    ├── Balance_Febrero_2026.xlsx")
            print(f"    ├── Comex_Maestra.xlsx")
            print(f"    └── Planificación_Financiera.xlsx")
            return True
        return True

    def listar_archivos_encontrados(self):
        """Lista archivos disponibles"""
        archivos = list(self.datos_entrada.glob("*.xlsx")) + list(self.datos_entrada.glob("*.json"))

        if not archivos:
            print(f"\n[AVISO] No hay archivos en {self.datos_entrada}")
            return False

        print(f"\n[OK] Archivos encontrados ({len(archivos)}):")
        for archivo in archivos:
            tamaño = archivo.stat().st_size / 1024  # KB
            print(f"  • {archivo.name} ({tamaño:.0f} KB)")

        return True

    def copiar_presupuesto(self):
        """Copia Presupuesto a destino"""
        fuentes = list(self.datos_entrada.glob("*resupuesto*.xlsx"))

        if not fuentes:
            print(f"\n[AVISO] No encontrado: archivo de Presupuesto")
            return False

        origen = fuentes[0]
        destino = self.datos_planillas / "Presupuesto_Febrero_2026.xlsx"

        try:
            shutil.copy2(origen, destino)
            print(f"[OK] Presupuesto copiado: {destino.name}")
            return True
        except Exception as e:
            print(f"[ERROR] No se pudo copiar Presupuesto: {e}")
            return False

    def copiar_sueldos(self):
        """Copia Sueldos a destino"""
        fuentes = list(self.datos_entrada.glob("*ueldos*.xlsx")) + list(self.datos_entrada.glob("*nómina*.xlsx"))

        if not fuentes:
            print(f"[AVISO] No encontrado: archivo de Sueldos")
            return False

        origen = fuentes[0]
        destino = self.datos_planillas / "Sueldos_Febrero_2026.xlsx"

        try:
            shutil.copy2(origen, destino)
            print(f"[OK] Sueldos copiado: {destino.name}")
            return True
        except Exception as e:
            print(f"[ERROR] No se pudo copiar Sueldos: {e}")
            return False

    def copiar_balance(self):
        """Copia Balance a destino"""
        fuentes = list(self.datos_entrada.glob("*alance*.xlsx")) + list(self.datos_entrada.glob("*euda*.xlsx"))

        if not fuentes:
            print(f"[AVISO] No encontrado: archivo de Balance")
            return False

        origen = fuentes[0]
        destino = self.datos_planillas / "Balance_Febrero_2026.xlsx"

        try:
            shutil.copy2(origen, destino)
            print(f"[OK] Balance copiado: {destino.name}")
            return True
        except Exception as e:
            print(f"[ERROR] No se pudo copiar Balance: {e}")
            return False

    def copiar_comex(self):
        """Copia COMEX (Excel o JSON)"""
        fuentes_xlsx = list(self.datos_entrada.glob("*omex*.xlsx")) + list(self.datos_entrada.glob("*omex*.xls"))
        fuentes_json = list(self.datos_entrada.glob("*omex*.json"))

        fuentes = fuentes_xlsx + fuentes_json

        if not fuentes:
            print(f"[AVISO] No encontrado: archivo de COMEX")
            return False

        origen = fuentes[0]

        if origen.suffix.lower() == ".json":
            destino = self.datos_outputs / "comex_maestra_cc.json"
        else:
            destino = self.datos_outputs / "Comex_Maestra.xlsx"

        try:
            shutil.copy2(origen, destino)
            print(f"[OK] COMEX copiado: {destino.name}")
            return True
        except Exception as e:
            print(f"[ERROR] No se pudo copiar COMEX: {e}")
            return False

    def copiar_planificacion(self):
        """Copia Planificación Financiera a destino"""
        fuentes = list(self.datos_entrada.glob("*lanificación*.xlsx")) + list(self.datos_entrada.glob("*lan*.xlsx"))

        if not fuentes:
            print(f"[AVISO] No encontrado: archivo de Planificación")
            return False

        origen = fuentes[0]
        destino = self.datos_planillas / "Planificación Financiera.xlsx"

        try:
            shutil.copy2(origen, destino)
            print(f"[OK] Planificación copiado: {destino.name}")
            return True
        except Exception as e:
            print(f"[ERROR] No se pudo copiar Planificación: {e}")
            return False

    def copiar_google_sheets(self):
        """Copia export de Google Sheets (ventas)"""
        fuentes = list(self.datos_entrada.glob("*GoogleSheet*.xlsx")) + list(self.datos_entrada.glob("*google*.xlsx"))

        if not fuentes:
            print(f"[AVISO] No encontrado: export de Google Sheets (opcional)")
            return False

        origen = fuentes[0]
        destino = self.datos_outputs / "GoogleSheet_Ventas_Export.xlsx"

        try:
            shutil.copy2(origen, destino)
            print(f"[OK] Google Sheets copiado: {destino.name}")
            return True
        except Exception as e:
            print(f"[ERROR] No se pudo copiar Google Sheets: {e}")
            return False

    def crear_odoo_export_dummy(self):
        """Crea JSON de Odoo con datos dummy si no existe"""
        destino = self.datos_outputs / "odoo_export_20260401.json"

        if destino.exists():
            print(f"[OK] Odoo export ya existe: {destino.name}")
            return True

        datos_dummy = {
            "inventory": {
                "total_unidades": 5000,
                "valor_stock": 120000,
                "ocupacion_pct": 0.78,
                "items_bajo_minimo": [],
                "rotacion_promedio": 2.15,
                "sku_total": 150,
                "sku_activos": 125
            },
            "fulfillment": {
                "pedidos_pendientes": 12,
                "pedidos_despachados_hoy": 28,
                "pedidos_ontime_pct": 96.5,
                "tiempo_promedio_fulfillment_dias": 2.1,
                "ordenes_atrasadas": 1
            }
        }

        try:
            with open(destino, 'w', encoding='utf-8') as f:
                json.dump(datos_dummy, f, indent=2, ensure_ascii=False)
            print(f"[OK] Odoo export creado (datos dummy): {destino.name}")
            return True
        except Exception as e:
            print(f"[ERROR] No se pudo crear Odoo export: {e}")
            return False

    def ejecutar(self):
        """Ejecuta el proceso de ingesta completo"""

        if not self.verificar_carpeta_entrada():
            return False

        if not self.listar_archivos_encontrados():
            return False

        print(f"\n{'='*70}")
        print(f"COPIANDO ARCHIVOS...")
        print(f"{'='*70}\n")

        resultados = {
            "Presupuesto": self.copiar_presupuesto(),
            "Sueldos": self.copiar_sueldos(),
            "Balance": self.copiar_balance(),
            "COMEX": self.copiar_comex(),
            "Planificación": self.copiar_planificacion(),
            "Google Sheets": self.copiar_google_sheets(),
            "Odoo Export": self.crear_odoo_export_dummy(),
        }

        print(f"\n{'='*70}")
        print(f"RESUMEN")
        print(f"{'='*70}\n")

        OK = sum(1 for v in resultados.values() if v)
        TOTAL = len(resultados)

        print(f"Archivos procesados: {OK}/{TOTAL}")
        print(f"\nAhora puedes ejecutar:")
        print(f"  python orquestador_reportes.py")


# ============================================================================
# EJECUTAR
# ============================================================================

if __name__ == "__main__":
    ingestador = IngestadorDatos()
    exito = ingestador.ejecutar()

    if not exito:
        print(f"\n[INSTRUCCIONES]")
        print(f"1. Crea carpeta: UNION X - IA/datos_entrada/")
        print(f"2. Coloca tus archivos en esa carpeta")
        print(f"3. Ejecuta este script nuevamente")
    else:
        print(f"\n[LISTO] Todos los datos han sido copiados")
