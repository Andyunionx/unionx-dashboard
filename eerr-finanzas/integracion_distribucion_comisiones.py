"""
INTEGRACIÓN: EERR Classifier → Skill distribucion-comisiones-canal
Toma el EERR clasificado y lo convierte a formato de distribución por canal
"""

import json
from typing import List, Dict
from pathlib import Path
from eerr_classifier import EERRClassifier, EERRExporter, FilaEERR

# ============================================================================
# MAPEO: LÍNEA DE NEGOCIO → CANAL
# ============================================================================

MAPEO_CANAL = {
    "GRUPO ETER": "GRUPO_ETER",
    "UNION X": "UNIONX",
    "NO SE CONSIDERA": "OTRO",
}

CANALES_VALIDOS = ["RECIBELO", "BLUE_EXPRESS", "CONTROL_APORTES", "GRUPO_ETER", "UNIONX", "OTRO"]

# ============================================================================
# DISTRIBUIDOR DE COMISIONES POR CANAL
# ============================================================================

class DistribuidorComisiones:
    """
    Clasifica los movimientos de EERR por canal de venta para integración
    con la skill de distribución de comisiones del EERR
    """

    PATRONES_RECIBELO = {
        "keywords": ["RECIBELO", "RECÍBELO", "RECIBELO"],
        "codigos": ["41410101", "42410201"],
    }

    PATRONES_BLUE_EXPRESS = {
        "keywords": ["BLUE", "BLUE EXPRESS", "BLUEEXPRESS"],
        "codigos": ["41410109"],
    }

    PATRONES_CONTROL_APORTES = {
        "keywords": ["APORTE", "CONTROL", "VENDEDOR"],
        "codigos": [],
    }

    def __init__(self):
        self.asignaciones = []

    def _normalizar(self, texto: str) -> str:
        """Normaliza para búsqueda"""
        return str(texto or "").upper().replace("Á","A").replace("É","E").replace("Í","I").replace("Ó","O").strip()

    def detectar_canal(self, fila: FilaEERR) -> str:
        """
        Detecta el canal de venta basado en:
        - Código contable
        - Glosa
        - Contraparte
        """
        # Buscar en patrones
        glosa_norm = self._normalizar(fila.glosa)
        contra_norm = self._normalizar(fila.contraparte)

        if fila.codigo in self.PATRONES_RECIBELO["codigos"] or \
           any(k in glosa_norm or k in contra_norm for k in self.PATRONES_RECIBELO["keywords"]):
            return "RECIBELO"

        if fila.codigo in self.PATRONES_BLUE_EXPRESS["codigos"] or \
           any(k in glosa_norm or k in contra_norm for k in self.PATRONES_BLUE_EXPRESS["keywords"]):
            return "BLUE_EXPRESS"

        if any(k in glosa_norm or k in contra_norm for k in self.PATRONES_CONTROL_APORTES["keywords"]):
            return "CONTROL_APORTES"

        # Mapear por línea de negocio
        if fila.clasificacion and fila.clasificacion.ln:
            return MAPEO_CANAL.get(fila.clasificacion.ln, "OTRO")

        return "OTRO"

    def procesar_eerr(self, filas: List[FilaEERR], mes: str, ano: int = 2026) -> Dict:
        """
        Procesa EERR y genera distribución por canal
        Retorna estructura lista para skill distribucion-comisiones-canal
        """
        distribucion = {
            "meta": {
                "fecha_procesamiento": str(Path(Path.cwd())),
                "mes": mes,
                "ano": ano,
                "total_filas": len(filas),
            },
            "canales": {canal: [] for canal in CANALES_VALIDOS},
            "resumen": {canal: {"cantidad": 0, "monto_total": 0.0} for canal in CANALES_VALIDOS},
            "alertas": [],
        }

        for fila in filas:
            # Skip filas sin clasificar
            if not fila.clasificacion or not fila.clasificacion.ln:
                distribucion["alertas"].append({
                    "tipo": "SIN_CLASIFICAR",
                    "num_fila": fila.num_fila,
                    "codigo": fila.codigo,
                    "glosa": fila.glosa,
                    "saldo": fila.saldo,
                })
                continue

            canal = self.detectar_canal(fila)

            # Registro de movimiento
            movimiento = {
                "num_fila": fila.num_fila,
                "codigo": fila.codigo,
                "glosa": fila.glosa[:80],
                "contraparte": fila.contraparte[:50],
                "cuenta_contable": fila.cuenta,
                "saldo_miles": round(fila.saldo, 3),
                "saldo_pesos": round(fila.saldo * 1000, 0),
                "clasificacion": {
                    "linea_negocio": fila.clasificacion.ln,
                    "centro_costos": fila.clasificacion.cc,
                    "cuenta_analitica": fila.clasificacion.ca,
                },
                "canal_detectado": canal,
                "confianza": 1.0 if fila.clasificacion.metodo == "auto" else 0.8,
            }

            distribucion["canales"][canal].append(movimiento)
            distribucion["resumen"][canal]["cantidad"] += 1
            distribucion["resumen"][canal]["monto_total"] += fila.saldo

        return distribucion

    @staticmethod
    def a_json_skill(distribucion: Dict, output_path: str):
        """Exporta en formato que espera la skill"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(distribucion, f, ensure_ascii=False, indent=2)
        print(f"OK Exportado para skill en {output_path}")

    @staticmethod
    def generar_reporte_html(distribucion: Dict, output_path: str = "reporte_distribucion.html"):
        """Genera reporte HTML de distribución por canal"""
        html = """
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Reporte de Distribución por Canal</title>
            <style>
                body { font-family: 'Inter', sans-serif; margin: 20px; background: #f5f5f5; }
                .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }
                h1 { color: #0F2140; margin-bottom: 30px; }
                .resumen { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 30px; }
                .card { background: #f0f9ff; border-left: 4px solid #1B5EA6; padding: 20px; border-radius: 5px; }
                .card h3 { margin: 0; color: #1B5EA6; font-size: 14px; }
                .card .valor { font-size: 24px; font-weight: bold; color: #0F2140; margin-top: 10px; }
                table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
                th { background: #0F2140; color: white; padding: 12px; text-align: left; font-size: 12px; }
                td { padding: 10px 12px; border-bottom: 1px solid #e0e0e0; }
                tr:hover { background: #f9f9f9; }
                .alerta { background: #FEF2F2; border-left: 4px solid #B91C1C; padding: 10px; margin: 5px 0; }
                .canal-header { background: #EBF3FC; padding: 10px; margin-top: 20px; font-weight: bold; color: #1B5EA6; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📊 Reporte de Distribución EERR por Canal</h1>
        """

        # Resumen general
        html += '<div class="resumen">'
        for canal, resumen in distribucion["resumen"].items():
            if resumen["cantidad"] > 0:
                html += f"""
                <div class="card">
                    <h3>{canal.replace('_', ' ')}</h3>
                    <div class="valor">{resumen['cantidad']} movimientos</div>
                    <div style="font-size: 12px; color: #666; margin-top: 5px;">M$ {resumen['monto_total']:.2f}</div>
                </div>
                """
        html += '</div>'

        # Detalle por canal
        for canal, movimientos in distribucion["canales"].items():
            if not movimientos:
                continue
            html += f'<div class="canal-header">📌 CANAL: {canal.replace("_", " ")}</div>'
            html += '<table><thead><tr>'
            html += '<th>#</th><th>Código</th><th>Glosa</th><th>Monto M$</th><th>Línea Negocio</th>'
            html += '</tr></thead><tbody>'
            for mov in movimientos:
                html += f"""
                <tr>
                    <td>{mov['num_fila']}</td>
                    <td>{mov['codigo']}</td>
                    <td>{mov['glosa'][:50]}</td>
                    <td style="text-align: right">{mov['saldo_miles']:.2f}</td>
                    <td>{mov['clasificacion']['linea_negocio']}</td>
                </tr>
                """
            html += '</tbody></table>'

        # Alertas
        if distribucion["alertas"]:
            html += '<h2>⚠️ Alertas</h2>'
            for alerta in distribucion["alertas"]:
                html += f"""
                <div class="alerta">
                    <strong>{alerta['tipo']}</strong> - Fila {alerta['num_fila']}: {alerta['glosa'][:60]}
                </div>
                """

        html += """
            </div>
        </body>
        </html>
        """

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"OK Reporte HTML generado: {output_path}")


# ============================================================================
# PIPELINE COMPLETO
# ============================================================================

def procesar_eerr_completo(ruta_eerr_xlsx: str, mes: str, ano: int = 2026):
    """
    Pipeline completo:
    1. Lee EERR en Excel
    2. Clasifica automáticamente con reglas
    3. Distribuye por canal
    4. Exporta en múltiples formatos
    """
    try:
        import openpyxl

        print("="*70)
        print("PIPELINE: EERR → CLASIFICACIÓN → DISTRIBUCIÓN CANALES")
        print("="*70)

        # 1. Leer EERR
        print(f"\n1️⃣ Leyendo {Path(ruta_eerr_xlsx).name}...")
        wb = openpyxl.load_workbook(ruta_eerr_xlsx, data_only=True)
        ws = wb.active
        datos_eerr = []

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[0]:  # Skip empty
                continue
            datos_eerr.append({
                "codigo": row[0] or "",
                "glosa": row[1] or "",
                "contraparte": row[2] or "",
                "cuenta": row[3] or "",
                "saldo": float(row[4] or 0),
            })

        print(f"   ✓ {len(datos_eerr)} filas leídas")

        # 2. Clasificar
        print(f"\n2️⃣ Clasificando con {len(datos_eerr)} reglas...")
        classifier = EERRClassifier()
        filas_procesadas, stats = classifier.procesar_eerr(datos_eerr)
        print(f"   ✓ {stats['ge']} GRUPO ETER, {stats['ux']} UNIONX, {stats['sin_clasificar']} sin clasificar")

        # 3. Distribuir por canal
        print(f"\n3️⃣ Distribuyendo por canal...")
        distribuidor = DistribuidorComisiones()
        distribucion = distribuidor.procesar_eerr(filas_procesadas, mes, ano)
        print(f"   ✓ Distribuido en {sum(1 for v in distribucion['resumen'].values() if v['cantidad'] > 0)} canales")

        # 4. Exportar
        base_path = Path(ruta_eerr_xlsx).stem
        print(f"\n4️⃣ Exportando resultados...")

        EERRExporter.a_json(filas_procesadas, f"{base_path}_CLASIFICADO.json")
        EERRExporter.a_excel(filas_procesadas, f"{base_path}_CLASIFICADO.xlsx", stats)
        DistribuidorComisiones.a_json_skill(distribucion, f"{base_path}_DISTRIBUCION_CANALES.json")
        DistribuidorComisiones.generar_reporte_html(distribucion, f"{base_path}_REPORTE_CANALES.html")

        print(f"\n✅ PROCESO COMPLETADO")
        print(f"   Archivos generados:")
        print(f"   - {base_path}_CLASIFICADO.json")
        print(f"   - {base_path}_CLASIFICADO.xlsx")
        print(f"   - {base_path}_DISTRIBUCION_CANALES.json (para skill)")
        print(f"   - {base_path}_REPORTE_CANALES.html")

        return filas_procesadas, distribucion

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None, None


if __name__ == "__main__":
    # Ejemplo: procesar un EERR
    # procesar_eerr_completo("mi_eerr.xlsx", "Abril")
    print("📌 Use: procesar_eerr_completo('ruta/archivo.xlsx', 'Mes')")
