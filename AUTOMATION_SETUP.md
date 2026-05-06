# SISTEMA DE AUTOMATIZACIÓN REVENUE MANAGEMENT
## Union X - Junior Revenue

**Versión:** 1.0  
**Última actualización:** 31-03-2026  
**Responsable:** Revenue Analytics

---

## 📋 DESCRIPCIÓN GENERAL

Este sistema automatiza el análisis de rentabilidad y distribución de comisiones de Union X. Consta de tres componentes:

1. **Motor de Análisis** (`revenue_automation.py`) — Procesa datos y ejecuta 4 análisis
2. **Orquestador Pipeline** (`run_revenue_pipeline.sh`) — Coordina flujo completo
3. **Scheduler (Trigger Remoto)** — Ejecuta automáticamente en horarios definidos

---

## 🔄 FLUJO DE DATOS

```
FUENTES DE DATOS
    ↓
    ├─ Análisis Contribución 2026 V02.02.xlsx (existente)
    ├─ EERR (descargado manualmente de email o Drive)
    └─ Google Sheets (eventual API)
    ↓
MOTOR DE ANÁLISIS (Python)
    ├─ Análisis 1: YoY / QoQ / MoM
    ├─ Análisis 2: Cross-Channel
    ├─ Análisis 3: KAM Real vs Teórico
    └─ Análisis 4: Budget vs Actual
    ↓
INYECCIÓN DE RESULTADOS
    ├─ Actualizar planilla de Contribución
    ├─ Ejecutar skill distribucion-comisiones-canal
    └─ Generar informe en Markdown
    ↓
ENTREGA
    ├─ Informe ejecutivo (📄 outputs/)
    ├─ Alertas de desviaciones (📧 email)
    └─ Dashboard (opcional: PowerBI/Sheets)
```

---

## 🚀 CÓMO USAR

### **Opción A: Ejecución Manual (Demanda)**

```bash
# Desde la carpeta del proyecto
cd "g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue"

# Ejecutar análisis básico
bash run_revenue_pipeline.sh

# Ejecutar con EERR
bash run_revenue_pipeline.sh --eerr "path/to/EERR.xlsx"
```

### **Opción B: Ejecución Automática Semanal (Recomendado)**

Usa el comando `/schedule` en Claude Code para configurar un trigger:

```
/schedule "Análisis Revenue Union X" --cron "0 9 * * 1" --prompt "
Ejecuta el análisis de revenue de Union X:

1. Lee: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/Análisis Contribución 2026 V02.02.xlsx
2. Corre: python revenue_automation.py
3. Genera informe
4. Guarda en: outputs/informe_revenue_[timestamp].md
5. Notifica si hay desviaciones > 5%
"
```

**Programación sugerida:**
- **Semanal:** Lunes 9:00 AM (para revisar semana anterior)
- **Mensual:** Primer día del mes 8:00 AM (cierre mensual)
- **Trimestral:** Día 1 de mes siguiente (cierre Q)

---

## 📥 ALIMENTACIÓN DE DATOS

### **1. Análisis de Contribución (Automático)**
La planilla `Análisis Contribución 2026 V02.02.xlsx` es la fuente maestra. El motor la lee automáticamente. Asegurate de actualizar en tiempo real o ejecutar el script después de cambios.

### **2. EERR (Manual, Temporal)**
Hasta que se implemente API de Google Drive:
1. Victor descarga EERR de `victor@unionx.cl`
2. Guarda en: `Junior Revenue/EERR_[MES_AÑO].xlsx`
3. Ejecuta: `bash run_revenue_pipeline.sh --eerr "EERR_Marzo2026.xlsx"`
4. El script ejecutará la skill `distribucion-comisiones-canal` internamente

### **3. Google Sheets (Futuro)**
Para habilitar sincronización automática con Google Sheets:
- [ ] Crear Google Service Account
- [ ] Configurar credenciales en `.env`
- [ ] Extender `revenue_automation.py` con `gspread`

---

## 📊 ANÁLISIS GENERADOS

### **Análisis 1: Temporal (YoY/QoQ/MoM)**
- Comparación año contra año
- Variaciones de contribución por período
- Identificación de trends

### **Análisis 2: Cross-Channel**
- Rentabilidad comparativa por canal
- Erosión de márgenes (Directo → Contribución)
- Canales para escalar vs. descontinuar

### **Análisis 3: Performance KAM**
- Contribución real vs. teórica
- Gaps por KAM y canal
- Bonificación sugerida

### **Análisis 4: Budget vs Actual**
- % de cumplimiento por sublínea
- Desviaciones positivas/negativas
- Alertas si gap > 5%

---

## ⚠️ ALERTAS CRÍTICAS AUTOMÁTICAS

El sistema notifica automáticamente si detecta:

1. **Caída de margen de contribución > 5%**
   - Acción: Revisar comisiones y costos logísticos

2. **Incumplimiento presupuesto > 10%**
   - Acción: Reasignar metas o escalar a management

3. **Erosión de margen directo anómala**
   - Acción: Auditar pricing y COGS

4. **KAM con gap real vs teórico > 20%**
   - Acción: Coaching o revisión de contrato

---

## 📁 ESTRUCTURA DE ARCHIVOS

```
Junior Revenue/
├── Análisis Contribución 2026 V02.02.xlsx    [MAESTRA]
├── EERR_Marzo2026.xlsx                        [ENTRADA MANUAL]
├── revenue_automation.py                       [MOTOR]
├── run_revenue_pipeline.sh                     [ORQUESTADOR]
├── AUTOMATION_SETUP.md                         [ESTE ARCHIVO]
│
├── outputs/                                    [SALIDAS]
│   ├── informe_revenue_20260331_090000.md
│   ├── informe_revenue_20260407_090000.md
│   └── pipeline_20260407_090000.log
│
└── logs/                                       [HISTÓRICO]
    └── executions.json
```

---

## 🔧 CONFIGURACIÓN AVANZADA

### **Personalizar Umbrales de Alerta**

Editar `revenue_automation.py`, sección `analyze_budget_vs_actual()`:

```python
ALERT_THRESHOLDS = {
    'margin_erosion': 0.05,      # 5%
    'budget_variance': 0.10,     # 10%
    'kam_performance_gap': 0.20, # 20%
}
```

### **Agregar Análisis Personalizados**

```python
def analyze_custom_metric(self):
    """Tu análisis aquí"""
    pass
```

---

## 📧 INTEGRACIÓN CON EMAIL/SLACK (Futuro)

```python
# Pseudo-código
if critical_alert:
    send_email(
        to='revenue-team@unionx.cl',
        subject=f'⚠️ Alerta Revenue: {alert_type}',
        body=formatted_report
    )
    send_slack('#revenue-alerts', f':warning: {alert_type}')
```

---

## ❓ FAQ

**P: ¿Puedo editar la planilla mientras corre el análisis?**  
R: No recomendado. Cierra la planilla o usa la copia (`V02.02_backup.xlsx`).

**P: ¿Qué pasa si el EERR tiene un formato diferente?**  
R: El motor es robusto a cambios de estructura. Si falla, revisa logs en `pipeline_[timestamp].log`.

**P: ¿Cómo agrego datos de Google Sheets directamente?**  
R: Descarga manualmente como `.xlsx` o proporciona credenciales de API (requiere setup adicional).

**P: ¿Puedo ejecutar dos análisis en paralelo?**  
R: Sí, el sistema soporta múltiples instancias si los archivos de salida tienen timestamps únicos.

**P: ¿Dónde veo el histórico de ejecuciones?**  
R: En `logs/executions.json` (generado después de cada ejecución).

---

## 🎯 ROADMAP

**Q2 2026:**
- [ ] Integración Google Sheets API
- [ ] Sincronización automática EERR desde email
- [ ] Dashboard PowerBI conectado a outputs
- [ ] Alertas por Slack/Teams

**Q3 2026:**
- [ ] ML para forecast de contribución
- [ ] Benchmark vs. industria FMCG
- [ ] Recomendaciones automáticas de pricing

**Q4 2026:**
- [ ] Integración con Odoo/ERP
- [ ] Mobile app para reportes

---

## 📞 SOPORTE

- **Problemas técnicos:** Revisa `pipeline_[timestamp].log`
- **Preguntas funcionales:** Contacta a [Revenue Manager]
- **Mejoras sugeridas:** Create issue en repositorio

---

*Sistema automatizado de Union X. Diseñado para eficiencia y toma de decisiones basada en datos.*
