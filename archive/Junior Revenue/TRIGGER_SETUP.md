# REMOTE TRIGGERS - AGENTE AUTOMATIZADO
## Union X - Revenue Automation

Para ejecutar el análisis automáticamente **sin intervención manual**, usa el skill `/schedule` de Claude Code.

---

## 🎯 OPCIÓN 1: Schedule Semanal (Recomendado)

Copia y ejecuta este comando en Claude Code:

```
/schedule
```

Completa los campos:
- **Nombre:** "Revenue Analysis Weekly - Union X"
- **Cron:** `0 9 * * 1` (Lunes 9:00 AM, hora local)
- **Descripción:** "Ejecuta análisis semanal de rentabilidad y distribuye comisiones"

Luego pega este prompt:

```
Ejecuta el sistema de automatización de Revenue Management para Union X.

INSTRUCCIONES:
1. Lee la planilla maestra: Análisis Contribución 2026 V02.02.xlsx
2. Verifica si hay un archivo EERR en la carpeta (si no existe, avisa)
3. Ejecuta: python revenue_automation.py
4. Si hay EERR, ejecuta la skill: distribucion-comisiones-canal
5. Analiza desviaciones:
   - Si algún margen cae > 5% respecto a período anterior: ALERTA
   - Si incumplimiento presupuesto > 10%: ALERTA
   - Si KAM tiene gap real vs teórico > 20%: ALERTA
6. Genera informe en Markdown con:
   - Resumen ejecutivo (3 hallazgos clave)
   - Tablas de performance por canal
   - Alertas de desviaciones
   - Recomendaciones accionables
7. Guarda informe en: outputs/informe_revenue_YYYYMMDD.md
8. Notifica si hay cambios críticos

Trabaja en la carpeta: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/
```

---

## 🎯 OPCIÓN 2: Schedule Mensual (Cierre de Mes)

Para un análisis más profundo el primer día del mes:

```
Cron: 0 8 1 * * (1er día del mes, 8:00 AM)
```

Prompt:

```
Ejecuta análisis profundo de Revenue Management - Cierre Mensual

1. Lee: Análisis Contribución 2026 V02.02.xlsx
2. Ejecuta: python revenue_automation.py --profundo

3. ANÁLISIS ESPECIAL (Cierre Mensual):
   - YoY comparación (mes actual vs mes anterior año pasado)
   - QoQ si aplica (trimestral)
   - Top 5 canales por rentabilidad
   - Bottom 3 canales con recomendaciones
   - Análisis de KAMs: quién sobreperforma, quién requiere coaching
   - Budget vs Actual: desviación por sublínea con root cause

4. Genera tablas en Markdown:
   - Rentabilidad por canal (Mg. Directo, Comisiones, Mg. Contribución)
   - KAM Performance (Real vs Esperado + Gap)
   - Budget Variance (Meta vs Resultado + % Cumplimiento)
   - Alertas críticas (márgenes cayendo, comisiones subiendo anómalo)

5. RECOMENDACIONES:
   - 3 acciones inmediatas (rentabilidad)
   - 3 acciones 30-90 días (estrategia)
   - Reasignaciones de recursos recomendadas

6. Guarda en: outputs/cierre_mensual_[mes]_[año].md
```

---

## 🎯 OPCIÓN 3: Schedule Trimestral (Reportaje Ejecutivo)

Para dirección/gerencia (máximo detalle):

```
Cron: 0 10 1 1,4,7,10 * (1er día de cada trimestre, 10:00 AM)
```

Prompt:

```
REPORTE EJECUTIVO TRIMESTRAL - Revenue Management

Ejecuta análisis completo para presentación a dirección.

CONTENIDO:
1. PORTADA
   - Período trimestral
   - Empresa: Union X
   - Generado automáticamente

2. RESUMEN EJECUTIVO (1 página)
   - 3 hallazgos clave con impacto
   - Métricas clave (venta, contribución, márgenes)
   - Desviaciones vs presupuesto

3. ANÁLISIS TEMPORAL
   - YoY (trimestre actual vs trimestre anterior año pasado)
   - Tendencias (venta, margen, contribución)
   - Gráficos en texto (ASCII)

4. ANÁLISIS POR NEGOCIO
   - Marketplace: volumen, margen, comisiones
   - Fidelización: ROI por canal
   - Corporativo: pipeline y desviaciones
   - Distribución: retail 1P performance
   - Páginas Propias: web analytics

5. ANÁLISIS CROSS-CHANNEL
   - Rentabilidad comparativa
   - Canales a escalar
   - Canales a revisar/discontinuar
   - Erosión de márgenes por canal

6. PERFORMANCE KAMs
   - Tabla: Contribución Real vs Esperada
   - Gaps > 20%: coaching recomendado
   - Bonificaciones sugeridas
   - Análisis de movilidad/rotación

7. ACTUAL VS PRESUPUESTO
   - % Cumplimiento por sublínea
   - Gap análisis (qué explica desviaciones)
   - Proyecciones para cierre de año

8. RECOMENDACIONES
   - Top 5 acciones para maximizar rentabilidad
   - Inversiones recomendadas
   - Cambios organizacionales sugeridos
   - Timeline de implementación

9. APÉNDICE (Tablas detalladas)
   - Ranking de canales por margen
   - Detalles por KAM
   - Histórico de cumplimiento

Genera como: outputs/REPORTE_TRIMESTRAL_Q[n]_[año].docx
   O como: outputs/REPORTE_TRIMESTRAL_Q[n]_[año].md + .pdf
```

---

## 📊 TABLA DE SCHEDULES RECOMENDADOS

| Frecuencia | Día/Hora | Cron | Propósito | Audiencia |
|---|---|---|---|---|
| **Semanal** | Lun 9:00 | `0 9 * * 1` | Monitoreo operacional | Revenue Team |
| **Mensual** | 1er día 8:00 | `0 8 1 * *` | Cierre y análisis | Managers |
| **Trimestral** | 1er día trim 10:00 | `0 10 1 1,4,7,10 *` | Reporte ejecutivo | Dirección |

---

## 🔗 CÓMO CONFIGURAR EN CLAUDE CODE

### Método 1: Comando `/schedule`

1. Abre Claude Code
2. En la terminal inferior, escribe:
   ```
   /schedule
   ```
3. Se abrirá un formulario. Completa:
   - **Schedule name:** `Revenue Weekly - Union X`
   - **Cron expression:** `0 9 * * 1`
   - **Prompt:** Copia el prompt correspondiente de arriba
4. Click en "Create Schedule"
5. ✓ Listo. Corre automáticamente cada lunes a las 9 AM

### Método 2: API (Avanzado)

```bash
curl -X POST https://api.claude.ai/v1/code/triggers \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Revenue Weekly - Union X",
    "cron": "0 9 * * 1",
    "prompt": "Ejecuta el sistema de automatización..."
  }'
```

---

## 📧 NOTIFICACIONES

Una vez configurados los schedules, Claude Code:
- ✅ Ejecuta automáticamente en horario
- ✅ Genera informe
- ✅ Guarda en `outputs/`
- ⚠️ Notifica si hay alertas críticas
- 📊 Resume resultados en el dashboard de triggers

---

## 🛠️ TROUBLESHOOTING

**P: El trigger no ejecutó a la hora programada**
- Verifica que Claude Code esté corriendo
- Revisa que la cron expression sea válida (usa `crontab.guru`)
- Consulta logs en `outputs/pipeline_[timestamp].log`

**P: El archivo de salida no se generó**
- Revisa permisos de escritura en la carpeta `outputs/`
- Confirma que la ruta es correcta
- Revisa si el script tiene errores (Lee el log)

**P: Quiero ver el output antes de guardarlo**
- Ejecuta manualmente: `bash run_revenue_pipeline.sh`
- Revisa el stdout primero, luego configura el trigger

---

## 📋 CHECKLIST DE IMPLEMENTACIÓN

- [ ] Crear carpeta `outputs/` en `Junior Revenue/`
- [ ] Validar que `revenue_automation.py` existe y tiene permisos
- [ ] Crear Google Drive folder para archivos EERR si aplica
- [ ] Configurar primer schedule semanal
- [ ] Probar ejecución manual: `bash run_revenue_pipeline.sh`
- [ ] Esperar primer lunes para confirmar ejecución automática
- [ ] Revisar primer informe generado
- [ ] Iterar y ajustar thresholds de alerta según necesidad

---

*Automatización de Revenue Management - Union X. Sistema autonomous que genera insights sin intervención humana.*
