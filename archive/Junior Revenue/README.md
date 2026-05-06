# 🎯 SISTEMA DE AUTOMATIZACIÓN REVENUE MANAGEMENT
## Union X - Análisis de Rentabilidad Automatizado

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   MOTOR AUTOMATIZADO REVENUE MANAGEMENT v1.0           │
│   Ejecuta 4 análisis sin intervención manual           │
│   Genera reportes ejecutivos semanalmente              │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 📦 QUÉ RECIBISTE

### ✅ Sistema Completo (5 archivos nuevos)

```
├─ revenue_automation.py        → Motor (analiza datos, 4 estudios)
├─ run_revenue_pipeline.sh      → Orquestador (flujo completo)
├─ AUTOMATION_SETUP.md          → Documentación técnica
├─ TRIGGER_SETUP.md             → Guía de schedules automáticos
├─ QUICK_START.md               → Inicio en 5 minutos
├─ EJEMPLO_INFORME.md           → Muestra de salida
└─ README.md                    → Este archivo
```

### 🎁 Bonus: Análisis Manual Previo

Los análisis YoY/Cross-Channel/KAM/Budget del principio fueron **mi análisis manual** basado en datos reales de tu planilla. Ahora tienes un **sistema que lo automatiza**.

---

## 🚀 COMIENZA EN 3 PASOS

### Paso 1: Prueba Local (2 minutos)

```bash
cd "g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue"
bash run_revenue_pipeline.sh
# Ver: outputs/informe_revenue_[timestamp].md
```

### Paso 2: Configura Schedule (1 minuto)

En Claude Code:
```
/schedule
```
- Nombre: `Revenue Weekly - Union X`
- Cron: `0 9 * * 1` (Lunes 9 AM)
- Prompt: (Ver `TRIGGER_SETUP.md`)

### Paso 3: Cada Lunes (Automático)

- ✅ Se ejecuta automáticamente
- ✅ Genera informe
- ✅ Detecta alertas
- ✅ Guarda en `outputs/`

---

## 🔄 FLUJO AUTOMATIZADO

```
DATOS ENTRADA
    ↓
    ├─ Análisis Contribución 2026.xlsx (existente)
    ├─ EERR.xlsx (descargado manual, por ahora)
    └─ Google Sheets (futuro API)
    ↓
MOTOR ANÁLISIS (Python)
    ├─ Análisis 1️⃣ Temporal (YoY/QoQ/MoM)
    ├─ Análisis 2️⃣ Cross-Channel (rentabilidad)
    ├─ Análisis 3️⃣ KAM Performance (Real vs Teórico)
    └─ Análisis 4️⃣ Budget vs Actual
    ↓
INFORME EJECUTIVO
    ├─ Resumen (3 hallazgos clave)
    ├─ Tablas Markdown (rentabilidad, KAM, presupuesto)
    ├─ Alertas críticas (margen, presupuesto, KAM)
    └─ Recomendaciones accionables
    ↓
SALIDA
    ├─ outputs/informe_revenue_[timestamp].md
    ├─ outputs/pipeline_[timestamp].log
    └─ Notificaciones de alertas (futuro)
```

---

## 📊 ANÁLISIS GENERADOS

| # | Análisis | Incluye | Frecuencia |
|---|---|---|---|
| 1️⃣ | **Temporal** | YoY, QoQ, MoM | Semanal |
| 2️⃣ | **Cross-Channel** | Rentabilidad por canal, erosión márgenes | Semanal |
| 3️⃣ | **KAM Performance** | Real vs Teórico, gaps, recomendaciones | Mensual |
| 4️⃣ | **Budget vs Actual** | Cumplimiento %, desviaciones, alertas | Semanal |

---

## 🎯 EJEMPLO DE SALIDA

Ver archivo: **`EJEMPLO_INFORME.md`**

Incluye:
- ✅ Resumen ejecutivo con 3 hallazgos clave
- ✅ Tabla YoY (Feb 2025 vs Feb 2026)
- ✅ Análisis cross-channel (9 canales)
- ✅ Performance KAM (3 KAMs principales)
- ✅ Budget vs Actual (5 sublíneas)
- ✅ Alertas críticas (Ripley, Corporativo, etc.)
- ✅ Recomendaciones accionables (9 acciones)

---

## ⚡ CARACTERÍSTICAS

### ✅ Ya Implementado

- [x] Motor de análisis en Python
- [x] Orquestador de flujo
- [x] 4 análisis estructurados
- [x] Generación de reportes Markdown
- [x] Detección de alertas críticas
- [x] Documentación completa

### 🔜 Próximo (Roadmap Q2)

- [ ] API Google Sheets (sincronización automática)
- [ ] Descarga automática EERR de email
- [ ] Alertas por Slack/Teams
- [ ] Dashboard PowerBI/Sheets
- [ ] Histórico de ejecuciones (JSON)

### 🚀 Futuro (Q3-Q4)

- [ ] Predicción de contribución (ML)
- [ ] Benchmarking vs industria FMCG
- [ ] Recomendaciones automáticas de pricing
- [ ] Integración con Odoo/ERP

---

## 📖 DOCUMENTACIÓN

| Archivo | Para Quién | Contenido |
|---|---|---|
| `QUICK_START.md` | Ejecutivos | Cómo usar en 5 minutos |
| `AUTOMATION_SETUP.md` | Técnicos | Configuración detallada |
| `TRIGGER_SETUP.md` | DevOps | Guía de schedules/triggers |
| `revenue_automation.py` | Desarrolladores | Código fuente comentado |
| `EJEMPLO_INFORME.md` | Managers | Muestra de salida típica |

---

## 🆘 TROUBLESHOOTING

| Problema | Solución |
|----------|----------|
| "El trigger no ejecutó" | Verifica que Claude Code esté abierto |
| "Archivo no se generó" | Verifica que `outputs/` existe |
| "Error de permisos" | Verifica permisos en carpeta |
| "Python no encontrado" | Verifica instalación Python 3.12+ |

Ver `AUTOMATION_SETUP.md` para más detalles.

---

## 🎬 CASOS DE USO

### Caso 1: Monitoreo Semanal
- Ejecuta: Lunes 9 AM automáticamente
- Resultado: Informe + alertas
- Acción: Revisar 5 minutos, escalar si es crítico

### Caso 2: Cierre Mensual
- Ejecuta: 1er día del mes, 8 AM
- Resultado: Análisis profundo + recomendaciones
- Acción: Input para reporte gerencial

### Caso 3: Reporte Trimestral
- Ejecuta: 1er día de trimestre, 10 AM
- Resultado: Informe ejecutivo (Word/PDF)
- Acción: Presentación a dirección

### Caso 4: Ad-hoc (Demanda)
- Ejecuta: `bash run_revenue_pipeline.sh` manualmente
- Resultado: Análisis inmediato
- Acción: Investigación especial

---

## 💡 KEY INSIGHTS DEL ANÁLISIS INICIAL

De mi análisis manual de tus datos (que ahora se automatiza):

### 🟢 Fortalezas
- Crecimiento YoY fuerte: +33.7% venta, +44.4% contribución
- Marketplace cumple 100% presupuesto de contribución
- Canales como Paris (40.7%), Kitchen Center (35.7%), Sawa (45.3%) tienen márgenes excelentes

### 🔴 Debilidades
- **Ripley:** Solo 9.8% contribución (erosión 49.6pp) → Renegociar o discontinuar
- **Corporativo:** 3.2% presupuesto cumplido → Investigar colapso
- **Distribución:** 20.7% cumplido → Caída de Retail 1P
- **Dependencia:** 72% volumen es Marketplace → Riesgo concentrado

### 🎯 Oportunidades
- Escalar Celmedia, Sawa, Paris (márgenes altos)
- Replicar prácticas de KAM Claudia (sobreperformance)
- Optimizar costos logísticos (+58.6% YoY anómalo)

---

## 📈 MÉTRICAS CRÍTICAS A MONITOREAR

```
✓ Venta YoY Growth       → Target: >20%  (Actual: +33.7% ✅)
✓ Mg. Contribución       → Target: 28%+  (Actual: 28.0% ⚠️)
✓ Comisión Envío/Venta   → Target: <9%   (Actual: 10.3% 🔴)
✓ Budget Cumplimiento    → Target: >90%  (Actual: 73.7% 🔴)
✓ Erosión Margen Digital → Target: <30pp (Ripley: 49.6pp 🔴)
```

---

## 🔐 Privacidad & Seguridad

- ✅ Todo corre localmente (Python + Bash)
- ✅ No se suben datos a internet
- ✅ Archivos generados guardados en `outputs/` local
- ✅ No requiere API keys (por ahora)

---

## 📞 SOPORTE

**Preguntas técnicas:**
- Revisa `AUTOMATION_SETUP.md`

**Cómo usar schedules:**
- Ve a `TRIGGER_SETUP.md`

**Quiero personalizar análisis:**
- Edita `revenue_automation.py` (comentado)

**Reporta bugs:**
- Revisa logs en `outputs/pipeline_[timestamp].log`

---

## 🎯 PRÓXIMOS PASOS

### Hoy
1. Lee `QUICK_START.md` (5 min)
2. Ejecuta manual: `bash run_revenue_pipeline.sh` (2 min)
3. Revisa informe en `outputs/` (5 min)

### Esta Semana
1. Configura schedule semanal (`/schedule`)
2. Espera a que se ejecute el lunes

### Próximas 2 Semanas
1. Configura schedule mensual (cierre)
2. Integra con tu flujo de reporte

### Mes 2
1. Investiga oportunidades de mejora (Ripley, Corporativo, etc.)
2. Implementa recomendaciones
3. Monitorea impacto con nuevos informes

---

## 🎓 EJEMPLO REAL

**Escenario:** Lunes 9:00 AM

```
1. Timer dispara → Ejecuta revenue_automation.py
2. Lee: Análisis Contribución 2026 V02.02.xlsx
3. Analiza: 4 estudios en paralelo
4. Genera: Informe Markdown + alertas
5. Guarda: outputs/informe_revenue_20260331_090000.md

TÚ RECIBES NOTIFICACIÓN:
═══════════════════════════════════════════
⚠️ ALERTA REVENUE: Margen Ripley cayó a 9.8%
   Recomendación: Renegociar o discontinuar

✅ Informe disponible:
   outputs/informe_revenue_20260331_090000.md

Acción recomendada: Revisar (5 min) → Escalar
═══════════════════════════════════════════
```

---

## 🏆 BENEFICIOS

| Beneficio | Impacto |
|-----------|---------|
| **Automatización** | 0 intervención manual semanal |
| **Consistencia** | Mismo análisis cada período |
| **Velocidad** | Informe en minutos vs horas |
| **Alertas** | Detecta problemas automáticamente |
| **Escalabilidad** | Agrega canales/KAMs sin cambio |
| **Trazabilidad** | Histórico de análisis |

---

## 📊 Versión

- **Sistema:** Revenue Automation Engine v1.0
- **Fecha creación:** 31-03-2026
- **Python:** 3.12+
- **Dependencias:** openpyxl, pandas (instaladas)
- **Última actualización:** 31-03-2026

---

```
╔═══════════════════════════════════════════════════════╗
║                                                       ║
║  🎉 SISTEMA LISTO PARA USAR                         ║
║                                                       ║
║  Próximo paso: QUICK_START.md                        ║
║                                                       ║
╚═══════════════════════════════════════════════════════╝
```

*Revenue Automation Engine - Union X*  
*Análisis de rentabilidad sin fricción*
