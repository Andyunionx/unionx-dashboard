"""
SISTEMA DE ALERTAS EN TIEMPO REAL
10 alertas automticas cuando se detectan desvos

Thresholds validados con Andrs:
- A1: Margen Contribucin < 27% (CRTICA)
- A2: Stock bajo mnimo (CRTICA)
- A3: Desvo Presupuesto > 10% (CRTICA)
- A4: Retraso Importacin > Lead time promedio (CRTICA)
- A5: Rotacin Inventario baja (MODERADA)
- A6: Ocupacin Almacn > 90% (MODERADA)
- A7: Fulfillment < 95% / < 98% (CRTICA/MODERADA)
- A8: Concentracin Cliente > 30% (INFORMATIVA)
- A9: Variacin Costo > 5% (INFORMATIVA)
- A10: Flujo de Caja Negativo en < 30 das (INFORMATIVA)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class UrgenciaAlerta(Enum):
    """Niveles de urgencia"""
    CRITICA = ""
    MODERADA = ""
    INFORMATIVA = ""


@dataclass
class Alerta:
    """Estructura de una alerta"""
    id: str  # A1, A2, etc.
    nombre: str
    urgencia: UrgenciaAlerta
    condicion: str
    threshold: str
    valor_actual: float
    estado: str  # triggered, no_triggered
    accion_recomendada: str
    destinatarios: List[str]  # correos a quin enviar
    canal: str  # email, slack, sms
    timestamp: str


class SistemaAlertas:
    """Gestor central de 10 alertas en tiempo real"""

    # THRESHOLDS VALIDADOS
    THRESHOLDS = {
        'A1': {'margen_contrib_minimo': 0.27, 'urgencia': UrgenciaAlerta.CRITICA},
        'A2': {'frecuencia': 'tiempo_real', 'urgencia': UrgenciaAlerta.CRITICA},
        'A3': {'desvio_presupuesto_maximo': 0.10, 'urgencia': UrgenciaAlerta.CRITICA},
        'A4': {'urgencia': UrgenciaAlerta.CRITICA},
        'A5': {'rotacion_baja': 0.80, 'urgencia': UrgenciaAlerta.MODERADA, 'frecuencia': 'semanal'},
        'A6': {'ocupacion_maxima': 0.90, 'urgencia': UrgenciaAlerta.MODERADA, 'frecuencia': 'semanal'},
        'A7': {'fulfillment_critico': 0.95, 'fulfillment_meta': 0.98, 'urgencia_critica': UrgenciaAlerta.CRITICA, 'urgencia_moderada': UrgenciaAlerta.MODERADA},
        'A8': {'concentracion_cliente': 0.30, 'urgencia': UrgenciaAlerta.INFORMATIVA, 'frecuencia': 'semanal'},
        'A9': {'variacion_costo': 0.05, 'urgencia': UrgenciaAlerta.INFORMATIVA, 'frecuencia': 'semanal'},
        'A10': {'flujo_negativo_dias': 30, 'urgencia': UrgenciaAlerta.INFORMATIVA, 'frecuencia': 'semanal'},
    }

    HISTORIAL_PATH = Path(__file__).resolve().parent.parent / "data" / "alertas_historial.json"
    DEDUP_HOURS = 6  # no re-disparar misma alerta antes de N horas

    def __init__(self):
        """Inicializa el sistema de alertas"""
        self.alertas_activas = []
        self.historial = self._cargar_historial()

    def _cargar_historial(self) -> list:
        """Carga historial JSON (alertas previamente disparadas)."""
        if not self.HISTORIAL_PATH.exists():
            return []
        try:
            with open(self.HISTORIAL_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _guardar_historial(self):
        """Persiste el historial en JSON."""
        self.HISTORIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.HISTORIAL_PATH, "w", encoding="utf-8") as f:
            json.dump(self.historial[-1000:], f, indent=2, ensure_ascii=False, default=str)

    def _ya_disparada_recientemente(self, alerta_id: str, valor_key: str) -> bool:
        """Devuelve True si la alerta (id + valor_key) se disparo en las ultimas DEDUP_HOURS."""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=self.DEDUP_HOURS)
        for h in reversed(self.historial):
            try:
                ts = datetime.fromisoformat(h.get("timestamp", ""))
            except Exception:
                continue
            if ts < cutoff:
                return False
            if h.get("id") == alerta_id and h.get("valor_key") == valor_key:
                return True
        return False

    def _registrar_en_historial(self, alerta: 'Alerta', valor_key: str):
        """Agrega entrada al historial."""
        urgencia_str = alerta.urgencia.value if hasattr(alerta.urgencia, 'value') else str(alerta.urgencia)
        self.historial.append({
            "timestamp": alerta.timestamp,
            "id": alerta.id,
            "nombre": alerta.nombre,
            "urgencia": urgencia_str,
            "valor_actual": alerta.valor_actual,
            "valor_key": valor_key,
        })

    def evaluar(
        self,
        datos_rentabilidad: Dict,
        datos_operaciones: Dict,
        datos_comex: Dict,
        datos_flujo: Dict
    ) -> List[Alerta]:
        """
        Evala los 10 criterios de alerta

        Args:
            datos_rentabilidad: Datos del Reporte 1
            datos_operaciones: Datos del Reporte 2
            datos_comex: Datos COMEX
            datos_flujo: Datos de flujo de caja

        Returns:
            Lista de alertas disparadas
        """

        self.alertas_activas = []

        # A1: Margen Contribucin < 27%
        self._evaluar_a1_margen_critico(datos_rentabilidad)

        # A2: Stock bajo mnimo
        self._evaluar_a2_stock_bajo(datos_operaciones)

        # A3: Desvo Presupuesto > 10%
        self._evaluar_a3_desvio_presupuesto(datos_rentabilidad)

        # A4: Retraso Importacin
        self._evaluar_a4_retraso_importacion(datos_comex)

        # A5: Rotacin baja
        self._evaluar_a5_rotacion_baja(datos_operaciones)

        # A6: Ocupacin almacn > 90%
        self._evaluar_a6_ocupacion_almacen(datos_operaciones)

        # A7: Fulfillment bajo
        self._evaluar_a7_fulfillment_bajo(datos_operaciones)

        # A8: Concentracin cliente > 30%
        self._evaluar_a8_concentracion_cliente(datos_rentabilidad)

        # A9: Variacin costo > 5%
        self._evaluar_a9_variacion_costo(datos_rentabilidad)

        # A10: Flujo de caja negativo
        self._evaluar_a10_flujo_negativo(datos_flujo)

        return self.alertas_activas

    # ========================================================================
    # EVALUADORES DE CADA ALERTA
    # ========================================================================

    def _evaluar_a1_margen_critico(self, datos: Dict):
        """A1: Margen Contribucin < 27%"""

        # Buscar canal con margen < 27%
        canales_criticos = [
            c for c in datos.get('canales', [])
            if c.get('margen_contrib', 0.3) < self.THRESHOLDS['A1']['margen_contrib_minimo']
        ]

        for canal in canales_criticos:
            alerta = Alerta(
                id='A1',
                nombre='Margen de Contribucin Crtico',
                urgencia=self.THRESHOLDS['A1']['urgencia'],
                condicion='Margen contribucin < 27%',
                threshold='27%',
                valor_actual=canal.get('margen_contrib', 0) * 100,
                estado='triggered',
                accion_recomendada=f"ACCIN URGENTE: {canal.get('nombre', 'Canal')} tiene margen {canal.get('margen_contrib', 0)*100:.1f}%. Renegociar con cliente o revisar costos.",
                destinatarios=['ceo@unionx.cl', 'andres@unionx.cl'],
                canal='email',
                timestamp=datetime.now().isoformat()
            )
            self.alertas_activas.append(alerta)

    def _evaluar_a2_stock_bajo(self, datos: Dict):
        """A2: Stock bajo mnimo"""

        items_bajo = datos.get('items_bajo_minimo', [])

        for item in items_bajo:
            alerta = Alerta(
                id='A2',
                nombre='Stock Bajo Mnimo',
                urgencia=self.THRESHOLDS['A2']['urgencia'],
                condicion=f"Stock < mnimo para {item.get('sku', 'SKU')}",
                threshold=f"{item.get('minimo', 0)} unidades",
                valor_actual=item.get('stock_actual', 0),
                estado='triggered',
                accion_recomendada=f"Contactar a Steven (proveedor) para orden urgente de {item.get('sku')}. Stock actual: {item.get('stock_actual')} vs mnimo: {item.get('minimo')}",
                destinatarios=['andres@unionx.cl', 'operaciones@unionx.cl'],
                canal='email',
                timestamp=datetime.now().isoformat()
            )
            self.alertas_activas.append(alerta)

    def _evaluar_a3_desvio_presupuesto(self, datos: Dict):
        """A3: Desvo Presupuesto > 10%"""

        desvios = datos.get('desvios_presupuesto', {})

        for concepto, desvio_data in desvios.items():
            desvio_pct = abs(desvio_data.get('desvio_pct', 0))

            if desvio_pct > self.THRESHOLDS['A3']['desvio_presupuesto_maximo']:
                alerta = Alerta(
                    id='A3',
                    nombre='Desvo Presupuesto Mayor 10%',
                    urgencia=self.THRESHOLDS['A3']['urgencia'],
                    condicion=f"Desvo {concepto} > 10%",
                    threshold='10%',
                    valor_actual=desvio_pct * 100,
                    estado='triggered',
                    accion_recomendada=f"{concepto} desva {desvio_pct*100:.1f}%. Presupuesto: ${desvio_data.get('presupuesto', 0):,.0f} vs Real: ${desvio_data.get('real', 0):,.0f}. Revisar causa e informar.",
                    destinatarios=['ceo@unionx.cl', 'andres@unionx.cl'],
                    canal='email',
                    timestamp=datetime.now().isoformat()
                )
                self.alertas_activas.append(alerta)

    def _evaluar_a4_retraso_importacion(self, datos: Dict):
        """A4: Retraso Importacin > Lead time promedio"""

        importaciones = datos.get('importaciones_activas', [])

        for imp in importaciones:
            dias_retraso = imp.get('dias_retraso', 0)
            lead_time_promedio = imp.get('lead_time_promedio', 25)

            if dias_retraso > lead_time_promedio:
                alerta = Alerta(
                    id='A4',
                    nombre='Retraso Importacin',
                    urgencia=self.THRESHOLDS['A4']['urgencia'],
                    condicion=f"Importacin {imp.get('id')} con retraso",
                    threshold=f"{lead_time_promedio} das",
                    valor_actual=dias_retraso,
                    estado='triggered',
                    accion_recomendada=f"Contactar a Steven y Vicente (forwarder). Importacin {imp.get('id')} tiene {dias_retraso} das de retraso. ETA original: {imp.get('eta_original')} vs actual: {imp.get('eta_actual')}",
                    destinatarios=['andres@unionx.cl', 'comex@unionx.cl'],
                    canal='email',
                    timestamp=datetime.now().isoformat()
                )
                self.alertas_activas.append(alerta)

    def _evaluar_a5_rotacion_baja(self, datos: Dict):
        """A5: Rotacin Inventario Baja"""

        rotacion_actual = datos.get('rotacion_promedio', 0)
        rotacion_historica = datos.get('rotacion_historica', 2.0)
        umbral = rotacion_historica * (1 - (1 - self.THRESHOLDS['A5']['rotacion_baja']))

        if rotacion_actual < umbral:
            alerta = Alerta(
                id='A5',
                nombre='Rotacin Inventario Baja',
                urgencia=self.THRESHOLDS['A5']['urgencia'],
                condicion='Rotacin actual < promedio histrico -20%',
                threshold=f"{umbral:.2f} veces/mes",
                valor_actual=rotacion_actual,
                estado='triggered',
                accion_recomendada=f"Rotacin baja: {rotacion_actual:.2f} vs histrica {rotacion_historica:.2f}. Revisar productos lentos, considerar promocin o descontinuacin.",
                destinatarios=['andres@unionx.cl', 'operaciones@unionx.cl'],
                canal='email',
                timestamp=datetime.now().isoformat()
            )
            self.alertas_activas.append(alerta)

    def _evaluar_a6_ocupacion_almacen(self, datos: Dict):
        """A6: Ocupacin Almacn > 90%"""

        ocupacion = datos.get('ocupacion_pct', 0)

        if ocupacion > self.THRESHOLDS['A6']['ocupacion_maxima']:
            alerta = Alerta(
                id='A6',
                nombre='Ocupacin Almacn Crtica',
                urgencia=self.THRESHOLDS['A6']['urgencia'],
                condicion='Ocupacin almacn > 90%',
                threshold='90%',
                valor_actual=ocupacion * 100,
                estado='triggered',
                accion_recomendada=f"Almacn al {ocupacion*100:.1f}% de capacidad. Planificar: expansin?, tercerizacin?, reduccin de compras?",
                destinatarios=['andres@unionx.cl', 'operaciones@unionx.cl'],
                canal='email',
                timestamp=datetime.now().isoformat()
            )
            self.alertas_activas.append(alerta)

    def _evaluar_a7_fulfillment_bajo(self, datos: Dict):
        """A7: Fulfillment < 95% / < 98%"""

        tasa_ontime = datos.get('tasa_ontime_pct', 100)

        # Crtica si < 95%
        if tasa_ontime < self.THRESHOLDS['A7']['fulfillment_critico']:
            alerta = Alerta(
                id='A7',
                nombre='Fulfillment Crtico',
                urgencia=self.THRESHOLDS['A7']['urgencia_critica'],
                condicion='On-time < 95% (CRTICA)',
                threshold='95%',
                valor_actual=tasa_ontime,
                estado='triggered',
                accion_recomendada=f"CRTICO: Fulfillment {tasa_ontime:.1f}%. Revisar cuello de botella (compra, picking, despacho). Necesita intervencin urgente.",
                destinatarios=['andres@unionx.cl', 'operaciones@unionx.cl', 'ceo@unionx.cl'],
                canal='email',
                timestamp=datetime.now().isoformat()
            )
            self.alertas_activas.append(alerta)

        # Moderada si < 98%
        elif tasa_ontime < self.THRESHOLDS['A7']['fulfillment_meta']:
            alerta = Alerta(
                id='A7',
                nombre='Fulfillment Moderado',
                urgencia=self.THRESHOLDS['A7']['urgencia_moderada'],
                condicion='On-time < 98% (MODERADO)',
                threshold='98%',
                valor_actual=tasa_ontime,
                estado='triggered',
                accion_recomendada=f"Fulfillment {tasa_ontime:.1f}% vs meta 98%. Pequeas mejoras en procesos pueden ayudar.",
                destinatarios=['andres@unionx.cl', 'operaciones@unionx.cl'],
                canal='email',
                timestamp=datetime.now().isoformat()
            )
            self.alertas_activas.append(alerta)

    def _evaluar_a8_concentracion_cliente(self, datos: Dict):
        """A8: Concentracin Cliente > 30%"""

        clientes = datos.get('clientes', [])

        for cliente in clientes:
            concentracion = cliente.get('pct_ventas', 0)

            if concentracion > self.THRESHOLDS['A8']['concentracion_cliente']:
                alerta = Alerta(
                    id='A8',
                    nombre='Concentracin Cliente Alta',
                    urgencia=self.THRESHOLDS['A8']['urgencia'],
                    condicion=f"Cliente {cliente.get('nombre')} > 30% de ventas",
                    threshold='30%',
                    valor_actual=concentracion * 100,
                    estado='triggered',
                    accion_recomendada=f"{cliente.get('nombre')} representa {concentracion*100:.1f}% de ventas. Dependencia alta. Considerar: contrato largo plazo, diversificacin.",
                    destinatarios=['ceo@unionx.cl', 'comercial@unionx.cl'],
                    canal='email',
                    timestamp=datetime.now().isoformat()
                )
                self.alertas_activas.append(alerta)

    def _evaluar_a9_variacion_costo(self, datos: Dict):
        """A9: Variacin Costo > 5% vs semana anterior"""

        costo_actual = datos.get('costo_promedio', 0)
        costo_semana_anterior = datos.get('costo_semana_anterior', costo_actual)

        if costo_semana_anterior > 0:
            variacion = abs(costo_actual - costo_semana_anterior) / costo_semana_anterior

            if variacion > self.THRESHOLDS['A9']['variacion_costo']:
                alerta = Alerta(
                    id='A9',
                    nombre='Variacin Costo Significativa',
                    urgencia=self.THRESHOLDS['A9']['urgencia'],
                    condicion='Variacin costo > 5% vs semana anterior',
                    threshold='5%',
                    valor_actual=variacion * 100,
                    estado='triggered',
                    accion_recomendada=f"Costo vari {variacion*100:.1f}% vs semana anterior (${costo_semana_anterior:,.0f}  ${costo_actual:,.0f}). Investigar: precio?, mix de productos?, eficiencia?",
                    destinatarios=['andres@unionx.cl', 'procure@unionx.cl'],
                    canal='email',
                    timestamp=datetime.now().isoformat()
                )
                self.alertas_activas.append(alerta)

    def _evaluar_a10_flujo_negativo(self, datos: Dict):
        """A10: Flujo de Caja Negativo en < 30 das"""

        saldos_proyectados = datos.get('saldos_proyectados', {})

        for periodo, saldo in saldos_proyectados.items():
            if saldo < 0:
                alerta = Alerta(
                    id='A10',
                    nombre='Flujo de Caja Negativo Proyectado',
                    urgencia=self.THRESHOLDS['A10']['urgencia'],
                    condicion='Saldo proyectado < 0 en prximos 30 das',
                    threshold='> 0',
                    valor_actual=saldo,
                    estado='triggered',
                    accion_recomendada=f"Flujo caja proyectado NEGATIVO en {periodo} (${saldo:,.0f}). Acciones: acelerar cobranzas, diferir pagos, gestionar deuda.",
                    destinatarios=['ceo@unionx.cl', 'andres@unionx.cl', 'finanzas@unionx.cl'],
                    canal='email',
                    timestamp=datetime.now().isoformat()
                )
                self.alertas_activas.append(alerta)

    def enviar_alertas(self):
        """Envia las alertas disparadas por canal (con dedup por historial)."""

        for alerta in self.alertas_activas:
            valor_key = f"{alerta.threshold}|{alerta.condicion}"
            if self._ya_disparada_recientemente(alerta.id, valor_key):
                print(f"   ⓘ skip {alerta.id} (ya enviada en ultimas {self.DEDUP_HOURS}h)")
                continue

            if alerta.canal == 'email':
                self._enviar_email(alerta)
            elif alerta.canal == 'slack':
                self._enviar_slack(alerta)
            elif alerta.canal == 'sms':
                self._enviar_sms(alerta)

            self._registrar_en_historial(alerta, valor_key)

        self._guardar_historial()

    def _enviar_email(self, alerta: Alerta):
        """Envia alerta por email via Gmail API (shared_email)."""
        try:
            import sys as _sys
            from pathlib import Path as _Path
            project_root = _Path(__file__).resolve().parent.parent
            if str(project_root) not in _sys.path:
                _sys.path.insert(0, str(project_root))
            from shared_email import enviar_alerta

            cuerpo = f"""
            <h2>{alerta.nombre}</h2>
            <p><b>ID:</b> {alerta.id}</p>
            <p><b>Urgencia:</b> {alerta.urgencia}</p>
            <p><b>Threshold:</b> {alerta.threshold}</p>
            <p><b>Valor actual:</b> {alerta.valor_actual}</p>
            <p><b>Mensaje:</b> {getattr(alerta, 'mensaje', '')}</p>
            """
            urgencia_str = alerta.urgencia.value if hasattr(alerta.urgencia, 'value') else str(alerta.urgencia)
            msg_id = enviar_alerta(alerta.nombre, urgencia_str, cuerpo)
            print(f"   ✓ Email alerta enviado/draft: {msg_id} ({alerta.id})")
        except Exception as e:
            print(f"   ⚠️ No se pudo enviar email de alerta {alerta.id}: {e}")

    def _enviar_slack(self, alerta: Alerta):
        """Envia alerta por Slack via webhook (env var SLACK_WEBHOOK_URL)."""
        import os
        webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if not webhook:
            print(f"   ℹ️ SLACK_WEBHOOK_URL no configurada - skipping {alerta.id}")
            return
        try:
            import json as _json
            import urllib.request as _ur
            urgencia_str = alerta.urgencia.value if hasattr(alerta.urgencia, 'value') else str(alerta.urgencia)
            payload = {
                "text": f"*[ALERTA {urgencia_str.upper()}]* {alerta.nombre}\n"
                        f"Threshold: {alerta.threshold} | Actual: {alerta.valor_actual}\n"
                        f"ID: {alerta.id}"
            }
            req = _ur.Request(
                webhook,
                data=_json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            _ur.urlopen(req, timeout=10).read()
            print(f"   ✓ Slack notificado: {alerta.id}")
        except Exception as e:
            print(f"   ⚠️ Slack fallo para {alerta.id}: {e}")

    def _enviar_sms(self, alerta: Alerta):
        """SMS NO implementado (requiere Twilio). Fallback: log."""
        print(f"   ℹ️ SMS pendiente (Twilio no configurado): {alerta.id} - {alerta.nombre}")

    def exportar_json(self, path: str):
        """Exporta alertas a JSON"""
        datos = {
            'timestamp': datetime.now().isoformat(),
            'alertas_totales': len(self.alertas_activas),
            'alertas': [asdict(a) for a in self.alertas_activas]
        }

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)

        print(f" Alertas exportadas a {path}")


# ============================================================================
# SCRIPT EJECUTABLE
# ============================================================================

if __name__ == "__main__":
    # Crear sistema
    sistema = SistemaAlertas()

    # Datos ejemplo (en produccin vendran de los reportes)
    datos_rentabilidad_ejemplo = {
        'canales': [
            {'nombre': 'Recbelo', 'margen_contrib': 0.20},  # 20% < 27%  ALERTA
            {'nombre': 'Blue Express', 'margen_contrib': 0.30},  # OK
        ],
        'desvios_presupuesto': {
            'Ventas': {'presupuesto': 100000, 'real': 85000, 'desvio_pct': -0.15},  # -15% > 10%  ALERTA
        },
        'clientes': [
            {'nombre': 'Cliente A', 'pct_ventas': 0.35},  # 35% > 30%  ALERTA
        ],
        'costo_promedio': 50000,
        'costo_semana_anterior': 47000,
    }

    datos_operaciones_ejemplo = {
        'items_bajo_minimo': [{'sku': 'SKU-001', 'stock_actual': 2, 'minimo': 10}],  #  ALERTA A2
        'ocupacion_pct': 0.92,  # 92% > 90%  ALERTA A6
        'rotacion_promedio': 1.5,  # bajo  ALERTA A5
        'tasa_ontime_pct': 0.93,  # < 95%  ALERTA A7
        'rotacion_historica': 2.0,
    }

    datos_comex_ejemplo = {
        'importaciones_activas': [
            {'id': 'IMP-001', 'dias_retraso': 30, 'lead_time_promedio': 25, 'eta_original': '2026-04-15', 'eta_actual': '2026-04-20'},  #  ALERTA A4
        ],
    }

    datos_flujo_ejemplo = {
        'saldos_proyectados': {'proximo_mes': -10000},  # negativo  ALERTA A10
    }

    # Evaluar
    alertas = sistema.evaluar(
        datos_rentabilidad_ejemplo,
        datos_operaciones_ejemplo,
        datos_comex_ejemplo,
        datos_flujo_ejemplo
    )

    # Mostrar
    print(f"\n{'='*70}")
    print(f"SISTEMA DE ALERTAS: {len(alertas)} alertas disparadas")
    print(f"{'='*70}\n")

    for alerta in alertas:
        print(f"{alerta.urgencia.value} {alerta.id}: {alerta.nombre}")
        print(f"   Condicin: {alerta.condicion}")
        print(f"   Valor actual: {alerta.valor_actual:.2f} vs Threshold: {alerta.threshold}")
        print(f"   Accin: {alerta.accion_recomendada}")
        print()

    # Enviar
    sistema.enviar_alertas()

    # Exportar JSON
    sistema.exportar_json('data/outputs/alertas_tiempo_real.json')

    print(f"\n Sistema de alertas ejecutado correctamente")
