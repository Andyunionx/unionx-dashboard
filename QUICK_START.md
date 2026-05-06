# 🚀 QUICK START - Sistema Automatizado Revenue Management
## Union X - En 5 minutos

---

## ¿Qué acabas de recibir?

Un **sistema de automatización completo** que:
- ✅ Analiza rentabilidad automáticamente
- ✅ Ejecuta 4 análisis en paralelo (YoY, Cross-Channel, KAM, Budget)
- ✅ Genera reportes ejecutivos sin intervención
- ✅ Detecta alertas críticas (márgenes cayendo, presupuesto desviado)
- ✅ Se ejecuta semanal, mensual o trimestral

---

## 📁 Archivos Nuevos Creados

```
Junior Revenue/
├── 🟢 revenue_automation.py      ← MOTOR (análisis)
├── 🟢 run_revenue_pipeline.sh    ← ORQUESTADOR (flujo)
├── 🟢 AUTOMATION_SETUP.md        ← DOCUMENTACIÓN COMPLETA
├── 🟢 TRIGGER_SETUP.md           ← GUÍA DE SCHEDULERS
├── 🟢 QUICK_START.md             ← ESTE ARCHIVO
│
└── outputs/                       ← CARPETA DE SALIDA (se crea automáticamente)
```

---

## ⚡ 3 FORMAS DE USAR

### **OPCIÓN A: Manual (Ahora mismo)**

```bash
# Abre PowerShell/Git Bash en la carpeta del proyecto
cd "g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue"

# Ejecuta
bash run_revenue_pipeline.sh

# El informe se guarda en outputs/informe_revenue_[timestamp].md
```

✓ **Tiempo:** 2-3 minutos  
✓ **Cuándo usarla:** Cuando necesitas análisis bajo demanda

---

### **OPCIÓN B: Automático Semanal (Recomendado)**

En Claude Code, ejecuta:

```
/schedule
```

Luego configura:
- **Nombre:** `Revenue Weekly - Union X`
- **Cron:** `0 9 * * 1` (Lunes 9:00 AM)
- **Prompt:** (Ver en `TRIGGER_SETUP.md`)

✓ **Tiempo:** 1 minuto para configurar  
✓ **Frecuencia:** Automático cada lunes  
✓ **Cuándo usarla:** Para monitoreo operacional continuo

---

### **OPCIÓN C: Mensual + Trimestral (Ejecutivos)**

Configura dos schedules adicionales:

```
1. Mensual (1er día, 8:00 AM)    → Cierre profundo
2. Trimestral (1er día Q, 10:00 AM) → Reporte ejecutivo
```

Ver instrucciones en `TRIGGER_SETUP.md`

✓ **Tiempo:** 2 minutos para configurar ambos  
✓ **Cuándo usarla:** Para dirección/gerencia

---

## 📊 ¿Qué Genera el Sistema?

### Informe Incluye:

1. **Resumen Ejecutivo** (3 hallazgos clave)
   - Crecimientos YoY
   - Desviaciones presupuesto
   - Alertas críticas

2. **4 Análisis Estructurados**
   - Temporal: YoY, QoQ, MoM
   - Cross-Channel: canales por rentabilidad
   - KAM Performance: Real vs Teórico
   - Budget vs Actual: cumplimiento %

3. **Tablas Markdown**
   - Rentabilidad por canal
   - Performance de KAMs
   - Presupuesto vs realidad

4. **Recomendaciones Accionables**
   - Acciones inmediatas (días)
   - Iniciativas (30-90 días)
   - Cambios estratégicos

5. **Alertas Automáticas**
   - Márgenes cayendo > 5%
   - Presupuesto desviado > 10%
   - KAM con gap > 20%

---

## 🔄 Flujo de Datos

```
Tu Planilla (Análisis Contribución)
    ↓
Motor Python (análisis en paralelo)
    ↓
Informe Markdown + CSV
    ↓
Guardan en outputs/ automáticamente
```

---

## 🎯 Roadmap: Próximos Pasos

**HOY (ya está hecho):**
- ✅ Motor de análisis
- ✅ Orquestador
- ✅ Documentación

**SEMANA 1:**
- [ ] Ejecuta manualmente: `bash run_revenue_pipeline.sh`
- [ ] Revisa primer informe en `outputs/`
- [ ] Ajusta thresholds si necesario

**SEMANA 2:**
- [ ] Configura schedule semanal (`/schedule`)
- [ ] Verifica ejecución automática el lunes

**SEMANA 3-4:**
- [ ] Configura schedule mensual (cierre)
- [ ] Integra con tu flujo de reporte

**MES 2:**
- [ ] (Futuro) Descarga automática de EERR
- [ ] (Futuro) API Google Sheets
- [ ] (Futuro) Alertas por Slack/email

---

## 🆘 Troubleshooting Rápido

| Problema | Solución |
|----------|----------|
| "No se ejecutó en horario" | Verifica que Claude Code esté abierto |
| "Archivo no se guardó" | Verifica carpeta `outputs/` existe |
| "Error al leer planilla" | Cierra `Análisis Contribución...xlsx` |
| "Script no corre" | Verifica Python instalado: `python --version` |

---

## 📖 Documentación Completa

- **`AUTOMATION_SETUP.md`** → Configuración detallada
- **`TRIGGER_SETUP.md`** → Guía de schedules
- **`revenue_automation.py`** → Código fuente comentado

---

## 💡 Ejemplo de Uso

**Caso:** Es lunes 9:00 AM

1. Schedule se ejecuta automáticamente
2. Lee: `Análisis Contribución 2026 V02.02.xlsx`
3. Analiza últimas 7 días de datos
4. Genera informe
5. **Tú recibes:** Notificación + Informe en `outputs/informe_revenue_20260331_090000.md`
6. Tú revisas: 2 minutos
7. Acción: Si hay alerta crítica, escala

---

## 🎬 Empieza Ahora

### Opción más rápida (2 minutos):

```bash
cd "g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue"
bash run_revenue_pipeline.sh
# Ver informe en: outputs/informe_revenue_[timestamp].md
```

### Opción más cómoda (1 minuto setup, luego automático):

```
En Claude Code → /schedule → Copia prompt de TRIGGER_SETUP.md
```

---

## ¿Preguntas?

Revisa el archivo correspondiente:
- **¿Cómo funciona?** → `AUTOMATION_SETUP.md`
- **¿Cómo programar?** → `TRIGGER_SETUP.md`
- **¿Código fuente?** → `revenue_automation.py`

---

*Sistema de automatización Revenue Management - Union X*  
*Generado: 31-03-2026*
