"""
SKILL: análisis-rentabilidad
Análisis profundo automático cuando margen de contribución < 27%

Entrada:
  - Datos de rentabilidad por canal (ventas, costo, margen)
  - Histórico de márgenes (últimas 4 semanas)
  - Detalles de clientes/productos por canal

Salida:
  - Diagnóstico: ¿Qué causó la caída?
  - Comparativa histórica (es anomalía o tendencia?)
  - 3 acciones recomendadas específicas
  - Top 3 canales para mejorar margen
"""

import json
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
from pathlib import Path


@dataclass
class CanalRentabilidad:
    """Datos de un canal de venta"""
    nombre: str
    ventas_semana: float
    costo_semana: float
    margen_directo_pct: float  # (ventas - costo) / ventas
    margen_contribucion_pct: float  # incluye comisiones y gastos
    margen_operacional_pct: float
    tendencia_semana_anterior: str  # "↑", "↓", "→"
    clientes_top_3: List[Dict]  # [{"nombre": "Cliente X", "ventas": Y, "margen_pct": Z}]
    productos_top_3: List[Dict]  # [{"sku": "ABC123", "ventas": Y, "margen_pct": Z}]


@dataclass
class DiagnosticoRentabilidad:
    """Resultado del análisis"""
    canal_critico: str
    margen_actual: float
    margen_semana_anterior: float
    es_anomalia: bool  # True si es nueva caída (vs tendencia)

    # Diagnóstico de causa raíz
    diagnostico_causa: str  # "Precio bajo", "Costo alto", "Mix de productos"
    cliente_principal_problema: Optional[str]
    producto_principal_problema: Optional[str]

    # Acciones recomendadas (máx 3)
    acciones_recomendadas: List[str]

    # Oportunidades
    canales_mejorables: List[Dict]  # [{"canal": "X", "margen_actual": Y%, "potencial": Z%}]


class AnalisadorRentabilidad:
    """Motor de análisis profundo de rentabilidad"""

    def __init__(self, data_historica_path: Optional[str] = None):
        """
        Args:
            data_historica_path: Ruta a archivo JSON con histórico de márgenes
        """
        self.historico = self._cargar_historico(data_historica_path)

    def _cargar_historico(self, path: Optional[str]) -> Dict:
        """Carga histórico de márgenes (últimas 4 semanas)"""
        if not path or not Path(path).exists():
            # Retorna estructura vacía si no existe
            return {
                "semana_1": {},
                "semana_2": {},
                "semana_3": {},
                "semana_4": {},
            }

        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def analizar(self, canales_actuales: List[CanalRentabilidad]) -> List[DiagnosticoRentabilidad]:
        """
        Analiza rentabilidad y detecta canales con margen < 27%

        Args:
            canales_actuales: Lista de canales con datos de esta semana

        Returns:
            Lista de diagnósticos para canales críticos
        """
        diagnosticos = []

        for canal in canales_actuales:
            # SOLO alertar si margen < 27%
            if canal.margen_contribucion_pct < 27:
                diagnostico = self._diagnosticar_canal(canal)
                diagnosticos.append(diagnostico)

        return diagnosticos

    def _diagnosticar_canal(self, canal: CanalRentabilidad) -> DiagnosticoRentabilidad:
        """Diagnóstico detallado de un canal con margen bajo"""

        # 1. Verificar si es anomalía (caída nueva) vs tendencia
        margen_semana_anterior = self.historico.get("semana_1", {}).get(canal.nombre, {}).get("margen_contrib", 0)
        es_anomalia = (margen_semana_anterior > 27) and (canal.margen_contribucion_pct < 27)

        # 2. Diagnosticar causa raíz
        diagnostico_causa, cliente_problema, producto_problema = self._diagnosticar_causa_raiz(canal)

        # 3. Generar acciones recomendadas
        acciones = self._generar_acciones(
            diagnostico_causa,
            cliente_problema,
            producto_problema,
            canal
        )

        # 4. Identificar canales mejorables
        canales_mejorables = self._identificar_mejorables(canal)

        return DiagnosticoRentabilidad(
            canal_critico=canal.nombre,
            margen_actual=canal.margen_contribucion_pct,
            margen_semana_anterior=margen_semana_anterior,
            es_anomalia=es_anomalia,
            diagnostico_causa=diagnostico_causa,
            cliente_principal_problema=cliente_problema,
            producto_principal_problema=producto_problema,
            acciones_recomendadas=acciones,
            canales_mejorables=canales_mejorables,
        )

    def _diagnosticar_causa_raiz(self, canal: CanalRentabilidad) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Determina qué causó la caída de margen
        Retorna: (causa_general, cliente_problema, producto_problema)
        """

        # Verificar si fue problema de cliente (cliente específico con margen muy bajo)
        if canal.clientes_top_3:
            cliente_bajo_margen = next(
                (c for c in canal.clientes_top_3 if c.get("margen_pct", 0) < 15),
                None
            )
            if cliente_bajo_margen:
                return ("Precio bajo con cliente específico", cliente_bajo_margen.get("nombre"), None)

        # Verificar si fue problema de producto (mix de productos bajo margen)
        if canal.productos_top_3:
            producto_bajo_margen = next(
                (p for p in canal.productos_top_3 if p.get("margen_pct", 0) < 15),
                None
            )
            if producto_bajo_margen:
                return ("Mix de productos: venta de items bajo margen", None, producto_bajo_margen.get("sku"))

        # Comparar costo vs semana anterior
        margen_semana_anterior = self.historico.get("semana_1", {}).get(canal.nombre, {}).get("margen_contrib", 27)
        if margen_semana_anterior >= 27:
            # Es anomalía nueva → probablemente precio
            return ("Precio bajo (caída nueva)", None, None)

        # Tendencia de caída → probablemente costo subió
        return ("Costo alto o ineficiencia operacional", None, None)

    def _generar_acciones(
        self,
        diagnostico: str,
        cliente: Optional[str],
        producto: Optional[str],
        canal: CanalRentabilidad
    ) -> List[str]:
        """Genera 3 acciones recomendadas específicas"""

        acciones = []

        if "Precio bajo" in diagnostico and cliente:
            acciones.append(
                f"ACCIÓN URGENTE: Renegociar términos con {cliente}. "
                f"Margen actual: {canal.margen_contribucion_pct:.1f}% (crítico < 27%). "
                f"Sugerir incremento de precio o revisar volumen mínimo."
            )
        elif "Precio bajo" in diagnostico:
            acciones.append(
                f"Revisar precios de venta en {canal.nombre}. "
                f"Comparar contra competencia y reposicionar si es necesario."
            )

        if "Mix de productos" in diagnostico and producto:
            acciones.append(
                f"Reducir venta de {producto} o incrementar precio. "
                f"Este SKU está bajando margen promedio del canal. "
                f"Considerar descontinuar o reclasificar."
            )
        elif "Mix de productos" in diagnostico:
            acciones.append(
                f"Ajustar mix de productos en {canal.nombre}. "
                f"Priorizar venta de items con margen > 40% y limitar items < 20%."
            )

        if "Costo alto" in diagnostico:
            acciones.append(
                f"Revisar costos operacionales en {canal.nombre}. "
                f"Analizar: comisiones, fletes, empaque, COGS. "
                f"Buscar reducción de 5-10% para recuperar margen."
            )

        # Si no hay acciones específicas, generar genérica
        if not acciones:
            acciones.append(
                f"Análisis urgente: {canal.nombre} tiene margen {canal.margen_contribucion_pct:.1f}%. "
                f"Revisar histórico y causa de caída vs semana anterior."
            )

        # Completar hasta 3 acciones
        while len(acciones) < 3:
            acciones.append(f"Monitorear {canal.nombre} próximas 2 semanas para confirmar tendencia.")

        return acciones[:3]

    def _identificar_mejorables(self, canal_critico: CanalRentabilidad) -> List[Dict]:
        """Identifica top 3 canales que podrían mejorar margen"""

        # Para este ejemplo, retornar estructura. En producción:
        # - Comparar todos los canales vs benchmark
        # - Identificar cuáles pueden crecer más que otros

        return [
            {
                "canal": f"{canal_critico.nombre} (si se reducen costos operacionales)",
                "margen_actual": f"{canal_critico.margen_contribucion_pct:.1f}%",
                "potencial": f"{min(35, canal_critico.margen_contribucion_pct + 8):.1f}%",
                "acciones": "Reducir COGS y comisiones"
            },
            {
                "canal": "Canal con volumen medio (sin presión de precio)",
                "margen_actual": "28%",
                "potencial": "35%",
                "acciones": "Incremento de precio moderado"
            },
            {
                "canal": "Canal de nicho (margen natural alto)",
                "margen_actual": "32%",
                "potencial": "38%",
                "acciones": "Enfoque en productos premium"
            }
        ]

    def generar_reporte_html(self, diagnosticos: List[DiagnosticoRentabilidad]) -> str:
        """Genera reporte HTML para emitir por email"""

        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #d32f2f; }}
                .diagnostico {{
                    background: #fff3e0;
                    padding: 15px;
                    margin: 10px 0;
                    border-left: 4px solid #f57c00;
                    border-radius: 4px;
                }}
                .accion {{ background: #e3f2fd; padding: 10px; margin: 5px 0; }}
                .mejorable {{ background: #f3e5f5; padding: 10px; margin: 5px 0; }}
                table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #f5f5f5; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h1>🔴 ANÁLISIS PROFUNDO: Rentabilidad Crítica</h1>
            <p><strong>Fecha:</strong> {fecha}</p>
            <p><strong>Canales en alerta:</strong> {num_alertas}</p>

            {diagnosticos_html}

            <h3>Oportunidades de Mejora (Top 3)</h3>
            {mejorables_html}

            <p style="color: #666; font-size: 12px; margin-top: 30px;">
                Reporte generado automáticamente por Skill "análisis-rentabilidad"
            </p>
        </body>
        </html>
        """

        # Construir HTML de diagnósticos
        diagnosticos_html = ""
        for d in diagnosticos:
            anomalia_badge = "⚠️ ANOMALÍA NUEVA" if d.es_anomalia else "📉 TENDENCIA"
            diagnosticos_html += f"""
            <div class="diagnostico">
                <h3>{d.canal_critico} - {anomalia_badge}</h3>
                <table>
                    <tr>
                        <th>Métrica</th>
                        <th>Valor</th>
                    </tr>
                    <tr>
                        <td>Margen Actual</td>
                        <td><strong>{d.margen_actual:.1f}%</strong> (CRÍTICO: < 27%)</td>
                    </tr>
                    <tr>
                        <td>Margen Semana Anterior</td>
                        <td>{d.margen_semana_anterior:.1f}%</td>
                    </tr>
                    <tr>
                        <td>Causa Raíz Diagnosticada</td>
                        <td><strong>{d.diagnostico_causa}</strong></td>
                    </tr>
                </table>

                <h4>Acciones Recomendadas:</h4>
                {"".join(f'<div class="accion">✓ {a}</div>' for a in d.acciones_recomendadas)}
            </div>
            """

        # Construir HTML de mejorables
        mejorables_html = ""
        for m in diagnosticos[0].canales_mejorables if diagnosticos else []:
            mejorables_html += f"""
            <div class="mejorable">
                <strong>{m['canal']}</strong><br>
                Margen Actual: {m['margen_actual']} → Potencial: {m['potencial']}<br>
                Acciones: {m['acciones']}
            </div>
            """

        return html_template.format(
            fecha=datetime.now().strftime("%d/%m/%Y %H:%M"),
            num_alertas=len(diagnosticos),
            diagnosticos_html=diagnosticos_html,
            mejorables_html=mejorables_html or "<p>No hay diagnósticos disponibles</p>"
        )


# ============================================================================
# EJEMPLO DE USO
# ============================================================================

if __name__ == "__main__":
    # Crear analizador
    analizador = AnalisadorRentabilidad()

    # Ejemplo: canales de esta semana
    canales_ejemplo = [
        CanalRentabilidad(
            nombre="Recíbelo",
            ventas_semana=50000,
            costo_semana=38000,
            margen_directo_pct=24.0,
            margen_contribucion_pct=20.5,  # < 27% → CRÍTICO
            margen_operacional_pct=15.0,
            tendencia_semana_anterior="↓",
            clientes_top_3=[
                {"nombre": "Cliente A", "ventas": 20000, "margen_pct": 18},
                {"nombre": "Cliente B", "ventas": 15000, "margen_pct": 22},
                {"nombre": "Cliente C", "ventas": 15000, "margen_pct": 25},
            ],
            productos_top_3=[
                {"sku": "SKU-001", "ventas": 25000, "margen_pct": 22},
                {"sku": "SKU-002", "ventas": 15000, "margen_pct": 18},
                {"sku": "SKU-003", "ventas": 10000, "margen_pct": 20},
            ]
        ),
        CanalRentabilidad(
            nombre="Blue Express",
            ventas_semana=35000,
            costo_semana=24500,
            margen_directo_pct=30.0,
            margen_contribucion_pct=28.0,  # OK: > 27%
            margen_operacional_pct=22.0,
            tendencia_semana_anterior="↑",
            clientes_top_3=[],
            productos_top_3=[],
        )
    ]

    # Analizar
    diagnosticos = analizador.analizar(canales_ejemplo)

    # Mostrar resultado
    print(f"✓ Diagnósticos generados: {len(diagnosticos)}")
    for d in diagnosticos:
        print(f"\n📊 {d.canal_critico}")
        print(f"   Margen: {d.margen_actual:.1f}% (prev: {d.margen_semana_anterior:.1f}%)")
        print(f"   Causa: {d.diagnostico_causa}")
        print(f"   Acciones:")
        for a in d.acciones_recomendadas:
            print(f"      - {a}")

    # Generar HTML
    if diagnosticos:
        html = analizador.generar_reporte_html(diagnosticos)
        print("\n✓ Reporte HTML generado (listo para enviar por email)")
