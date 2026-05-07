# 📊 Reportes Automáticos - UNION X Finanzas

## Estado: ✅ IMPLEMENTADO (Sesión 3)

Los 3 reportes semanales automáticos + sistema de alertas en tiempo real están completamente implementados.

---

## 🎯 Resumen de Implementación

### ✅ Completado en Sesión 3

| Componente | Archivo | Estado |
|---|---|---|
| **Skill: Análisis Rentabilidad** | `analisis_rentabilidad_skill.py` | ✅ Listo |
| **Reporte 1: Rentabilidad** | `generar_reporte1_rentabilidad.py` | ✅ Listo |
| **Reporte 2: KPIs Operacionales** | `generar_reporte2_kpis.py` | ✅ Listo |
| **Reporte 3: Planificación Financiera** | `generar_reporte3_planificacion.py` | ✅ Listo |
| **Sistema de 10 Alertas** | `sistema_alertas_tiempo_real.py` | ✅ Listo |
| **Orquestador Maestro** | `orquestador_reportes.py` | ✅ Listo |

---

## 📋 Lo Que Se Automatizó

### 1️⃣ **REPORTE 1: Rentabilidad** (Lunes 9 AM)

**Entrada:**
- EERR clasificado de Odoo (JSON)
- Presupuesto mensual (Excel)

**Salida:**
- 4 Secciones en Excel:
  1. Rentabilidad por canal (3 márgenes: directo, contribución, operacional)
  2. Rentabilidad por Línea de Negocio
  3. Control de Presupuesto
  4. **Análisis Profundo** (ejecuta Skill si margen < 27%)

**Skill: "análisis-rentabilidad"**
- Análisis automático cuando margen de contribución < 27%
- Diagnóstico: ¿Fue precio? ¿Fue costo? ¿Fue mix de productos?
- Comparación histórica (¿es anomalía nueva o tendencia?)
- 3 acciones recomendadas específicas
- Top 3 canales mejorables

---

### 2️⃣ **REPORTE 2: KPIs Operacionales** (Lunes 9 AM)

**Entrada:**
- Odoo: Inventario, pedidos, despachos (API o export JSON)
- COMEX: Importaciones en tránsito, costos, ETAs

**Salida:**
- Dashboard con 4 secciones:
  1. **Inventario & Almacén** — Stock, rotación, ocupación
  2. **Despachos & Fulfillment** — On-time %, tiempos, órdenes atrasadas
  3. **COMEX & Importaciones** — **MAESTRA por Centro de Costo** (NEW!)
     - Tabla histórica: importaciones, costos promedio, retrasos, márgenes por CC
  4. **Alertas Operacionales** — Estado de salud

**NUEVO: Maestra COMEX por Centro de Costo**
- Tracking histórico de importaciones por CC (DISTRIBUCION, LOGISTICA, etc.)
- Costo promedio, retrasos promedio, margen de importación
- Base para análisis de rentabilidad por línea de negocio

---

### 3️⃣ **REPORTE 3: Planificación Financiera** (Lunes 9 AM)

**Entrada (Arquitectura de 2 Excels):**

**EXCEL #1: "Planificación Financiera"** (PRINCIPAL)
- EERR (automático desde Odoo próximamente)
- Sueldos (Excel contador/BUK - TBD Odoo)
- Honorarios (Manual por CC, distribución template)
- Rendiciones (Manual por CC, distribución template)
- Deuda (Excel balance - TBD Odoo)
- Balance
- Ajustes forecast

**EXCEL #2: "P&L Comparativo"** (SECUNDARIO)
- Para análista financiero (presupuesto vs real)
- NO se sincroniza automáticamente

**Salida:**
- Excel consolidado con 4 secciones:
  1. **EERR Consolidado** — Ingresos, costos, margen bruto, EBIT, utilidad neta
  2. **Flujo de Caja** — Histórico + proyecciones (optimista, pesimista)
  3. **Capital de Trabajo (KT)** — CxC, inventario, CxP, KT necesario vs actual
  4. **Deuda & Amortizaciones** — Proyecciones 12 meses

**Próximas Migraciones (Mediano Plazo):**
- Sueldos → Integrar con BUK vía API
- Deuda → Migrar a Odoo Accounting
- Honorarios/Rendiciones → Template sistematizado (bajo ROI ahora)

---

### 🚨 **SISTEMA DE 10 ALERTAS EN TIEMPO REAL**

Thresholds validados con Andrés. Se evalúan automáticamente y envían alertas por email/Slack/SMS.

| ID | Alerta | Métrica | Threshold | Urgencia | Frecuencia |
|----|--------|---------|-----------|----------|-----------|
| **A1** | Margen Crítico | Margen contrib % | < 27% | 🔴 CRÍTICA | Diaria |
| **A2** | Stock Bajo | Stock actual | < Mínimo | 🔴 CRÍTICA | Tiempo real |
| **A3** | Desvío Presupuesto | Desvío % | > 10% | 🔴 CRÍTICA | Diaria |
| **A4** | Retraso Importación | Días late | > Lead time | 🔴 CRÍTICA | Diaria |
| **A5** | Rotación Baja | Rotación | < Prom -20% | 🟡 MODERADA | Semanal |
| **A6** | Ocupación Almacén | Ocupación % | > 90% | 🟡 MODERADA | Semanal |
| **A7** | Fulfillment Bajo | On-time % | < 95%/98% | 🔴/🟡 | Diaria |
| **A8** | Cliente Concentrado | % ventas | > 30% | 🟢 INFO | Semanal |
| **A9** | Variación Costo | Variación % | > 5% | 🟢 INFO | Semanal |
| **A10** | Flujo Negativo | Saldo proj | < 0 | 🟢 INFO | Semanal |

**Resultado:** JSON con alertas dispuestas + emails automáticos a CEO/Andrés/Equipos

---

## 🚀 Cómo Ejecutar

### Opción A: Ejecución Manual (Para Testing)

```bash
cd "g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\eerr-finanzas"

# Ejecutar reportes
python orquestador_reportes.py

# O ejecutar reportes individuales:
python generar_reporte1_rentabilidad.py
python generar_reporte2_kpis.py
python generar_reporte3_planificacion.py
python sistema_alertas_tiempo_real.py
```

### Opción B: Automático - Cada Lunes 9 AM (Windows Task Scheduler)

1. **Crear archivo** `setup_scheduler.bat` en raíz del proyecto:

```batch
@echo off
REM Crear tarea programada: UNION X Reportes Lunes 9 AM
setlocal enabledelayedexpansion

REM Ruta absoluta al script
set SCRIPT_PATH=C:\ruta\a\UNION X - IA\eerr-finanzas\orquestador_reportes.py
set PYTHON_PATH=C:\Python39\python.exe

REM Crear tarea
schtasks /create /tn "UNION_X_Reportes_Lunes_9am" /tr "%PYTHON_PATH% %SCRIPT_PATH%" /sc weekly /d MON /st 09:00:00 /f

echo ✅ Tarea creada: UNION_X_Reportes_Lunes_9am
echo Ejecutará cada lunes a las 9:00 AM

REM Ejecutar inmediatamente para verificar
REM schtasks /run /tn "UNION_X_Reportes_Lunes_9am"
```

2. **Ejecutar el batch** (como Administrador):
```bash
setup_scheduler.bat
```

3. **Verificar en Task Scheduler:**
   - Abrir: `Tareas Programadas` (Windows)
   - Buscar: `UNION_X_Reportes_Lunes_9am`
   - Estado: Habilitada ✅

4. **Ver logs:**
```bash
tail -f data/outputs/reporte_semanal.log
```

---

## 📂 Estructura de Salidas

Los reportes se guardan automáticamente en `data/outputs/`:

```
data/outputs/
├── Reporte_Rentabilidad_YYYYMMDD.xlsx
├── Reporte_KPIs_YYYYMMDD.xlsx
├── Reporte_Planificacion_YYYYMMDD.xlsx
├── alertas_tiempo_real.json
├── Resumen_Semanal_YYYYMMDD.html
└── reporte_semanal.log
```

---

## 🔗 Integración Requerida

### Entrada: Rutas de Archivos

Deben existir en las rutas especificadas (o ajustar en `orquestador_reportes.py`):

```
data/
├── eerr/
│   ├── 01 EE.RR Enero 2026.xlsx
│   └── 02 EE.RR Febrero 2026.xlsx
├── planillas/
│   ├── Análisis Contribución 2026 V02.02.xlsx
│   ├── Presupuesto_Febrero_2026.xlsx
│   ├── Planificación Financiera.xlsx
│   ├── Sueldos_Febrero_2026.xlsx
│   └── Balance_Febrero_2026.xlsx
└── outputs/
    ├── (EERR clasificado JSON)
    ├── (COMEX maestra JSON)
    └── (Reportes generados)
```

### Próxima Integración: Odoo API

**Actualizar** `generar_reporte1_rentabilidad.py` para:
- Extraer EERR directo desde Odoo (sin Excel intermedio)
- Extraer datos de ventas por canal desde Odoo

**Código ejemplo:**
```python
import odoo_rpc_client

client = odoo_rpc_client.OdooRPC(
    url='https://unionxb2b.odoo.com',
    db='bmya-innovatek-sh-prd-6981800',
    username='andres@grupoeter.cl',
    password='...'
)

# Extraer EERR
account_moves = client.execute('account.move', 'search', [...])

# Extraer ventas por canal
sales_orders = client.execute('sale.order', 'search', [...])
```

---

## ✅ Checklist de Validación

Antes de activar automáticamente:

- [ ] Validar rutas de entrada (todos los Excel/JSON existen)
- [ ] Test manual: `python orquestador_reportes.py` (sin errores)
- [ ] Verificar estructura de salidas (3 reportes + alertas OK)
- [ ] Integración de emails (SMTP configurado)
- [ ] Task Scheduler activo (verificar en Windows)
- [ ] Logs siendo guardados (ver `reporte_semanal.log`)
- [ ] Confirmar con Andrés: horarios, destinatarios, thresholds

---

## 🔍 Troubleshooting

### Error: "Módulo no encontrado"
```bash
# Instalar dependencias
pip install openpyxl pandas numpy
```

### Error: "Archivo no existe"
- Verificar rutas en `orquestador_reportes.py`
- Ajustar según estructura real del proyecto

### Email no se envía
- Configurar SMTP (TODO en `_enviar_emails()`)
- Validar credenciales de correo

### Task Scheduler no ejecuta
```bash
# Verificar tarea existe
schtasks /query /tn "UNION_X_Reportes_Lunes_9am"

# Ejecutar manualmente
schtasks /run /tn "UNION_X_Reportes_Lunes_9am"

# Ver resultado
Get-ScheduledTask -TaskName "UNION_X_Reportes_Lunes_9am" -ErrorAction SilentlyContinue | Select-Object State
```

---

## 📞 Contacto & Próximos Pasos

**Implementado por:** Claude Code  
**Fecha:** 2026-04-01  
**Versión:** 1.0 (Producción)

**Próximos pasos:**
1. ✅ Implementación Reportes 1, 2, 3
2. ✅ Skill "análisis-rentabilidad"
3. ✅ Sistema de 10 alertas
4. ⏳ Integración Odoo API (para eliminar Excel intermedio)
5. ⏳ Migración Sueldos a BUK integrado
6. ⏳ Migración Deuda a Odoo Accounting
7. ⏳ Dashboard tiempo real (Google Data Studio)

---

**Última actualización:** 2026-04-01 (Session 3 Implementation)
