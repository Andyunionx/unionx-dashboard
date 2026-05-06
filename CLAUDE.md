# UNION X - IA: Contexto del Proyecto

## Sobre Andrés
- **Rol:** Gerente de Finanzas + Supply Chain de UnionX
  - Finanzas: Reportes, rentabilidad, análisis decisiones
  - Supply Chain: COMEX (importaciones), fulfillment, operaciones
- **Mayor dolor:** Procesos manuales, lentos, con 75% errores
- **Preferencia:** Español chileno, confirmación antes de cambios, control total
- **Disponibilidad:** Validación diaria

---

## El Objetivo Estratégico (2026)

**De:** Procesos manuales, lentos, 75% errores, integraciones rotas  
**A:** 3 reportes automáticos semanales + alertas tiempo real

### Lo que CEO espera (cada lunes 9 AM):
1. **Reporte Rentabilidad** — Contribución + Control Presupuesto
2. **Reporte KPIs Operacionales** — Inventario, despachos, COMEX, productividad  
3. **Reporte Planificación Financiera** — Flujo caja, KT, deuda, proyecciones

### Alertas en tiempo real:
- 4 alertas críticas (margen, stock, desvío presupuesto, retrasos)
- 3 alertas moderadas (rotación, ocupación, fulfillment)
- 3 alertas informativas (concentración, variación costo, flujo negativo)

**Éxito:** Lunes 9 AM sin errores, cero intervención manual, CEO toma decisiones con datos frescos

---

## Los 3 Flujos Principales (Estado Actual)

### 1. **Agente COMEX Gmail** 
Automatiza importaciones desde China monitoreando correos.

**Ubicación:** `agente-comex/`

**Personas clave:**
- **Steven** (proveedor chino) — topwillsteven@163.com — Envía PI (Proforma Invoice), PL (Packing List), OHNSO
- **Felipe** (comercial UnionX) — felipe@unionx.cl — Envía demandas y shipping plans
- **Vicente** (forwarder) — vicente@seimex.cl — Envía costos de flete

**Cómo funciona:**
1. Monitorea 3 buzones vía Gmail API
2. Detecta triggers:
   - `COMEX_WORKFLOW`: Cuando llega PI + PL de Steven → Ejecuta skill `comex-workflow`
   - `SHIPPING_PLAN_OHNSO`: Cuando llega OHNSO de Steven → Ejecuta skill `shipping-plan`
   - `SHIPPING_PLAN_DEMANDA`: Cuando llega demanda de Felipe → Ejecuta skill `shipping-plan`

**Estado:** Listo para ejecutar. Token Gmail configurado. Polling cada 2 minutos.

**Automatización:** Registrado en Task Scheduler Windows (corre en background al iniciar sesión)

---

### 2. **EERR Finanzas** 
Clasifica el Estado de Resultados mensual de Odoo y distribuye por canal.

**Ubicación:** `eerr-finanzas/`

**Flujo:**
1. Extrae EERR mensual de Odoo (o archivo Excel)
2. **Clasificador:** Aplica 88 reglas contables → asigna Línea Negocio, Centro Costos, Área
3. **Distribuidor:** Mapea a canales de venta (Recíbelo, Blue Express, Grupo Eter, Control Aportes)
4. **Salida:** JSON clasificado, Excel con colores, reporte HTML interactivo

**Skills conectadas:**
- `distribucion-comisiones-canal` — cuando subes el JSON, actualiza Análisis de Contribución automáticamente
- `reporte-financiero-gerencial` — genera reportes ejecutivos Word + Excel

**Automatización:** Triggers cada lunes 9 AM, día 7 y día 10 del mes (Task Scheduler)

---

### 3. **Revenue Automation**
Ingesta datos de Google Drive/Sheets/email y genera reportes ejecutivos mensuales.

**Ubicación:** `eerr-finanzas/` (mismo módulo)

**Cómo funciona:**
1. Descarga archivos de Google Drive automáticamente
2. Lee planillas de Google Sheets (detalles de ventas)
3. Lee EERR por email en fecha específica
4. Ejecuta análisis de contribución y distribuye comisiones
5. Genera informe ejecutivo → Análisis de Contribución.xlsx

**Automatización:** Calendarios programados (lunes 9 AM, día 7, día 10)

---

## Skills Disponibles

| Skill | Cuándo se activa | Input | Output |
|-------|------------------|-------|--------|
| `comex-workflow` | Manual o trigger automático del agente COMEX | 3 archivos (PI, PL, Tarifas) | Costeo importación + Matriz de costos |
| `shipping-plan` | Manual o trigger automático del agente COMEX | OHNSO + Demanda + flete | Plan de embarque optimizado |
| `distribucion-comisiones-canal` | Manual al subir JSON + EERR | JSON distribución canales | Actualiza Análisis de Contribución |
| `reporte-financiero-gerencial` | Manual al actualizar EERR | Archivo EERR.xlsx | Reportes Word + Excel con branding |

---

## Estructura de Carpetas

```
UNION X - IA/
├── CLAUDE.md                    ← Este archivo
├── agente-comex/                ← Agente Gmail COMEX Gmail (Steven, Felipe, Vicente)
│   ├── main.py
│   ├── src/
│   ├── config/
│   └── data/
├── eerr-finanzas/               ← Clasificador EERR + Revenue
│   ├── eerr_classifier.py
│   ├── revenue_automation.py
│   └── ...
├── odoo/                        ← Consultas Odoo (ventas, pedidos, etc.)
│   ├── odoo_connection.py
│   └── ...
├── data/                        ← Datos compartidos
│   ├── eerr/                    ← EERR mensuales
│   ├── planillas/               ← Análisis Contribución
│   └── outputs/                 ← Reportes generados (JSON, Excel, HTML)
└── .claude/                     ← Configuración Claude Code
    └── settings.json
```

---

## Próximos Pasos Típicos

1. **Email del proveedor chino llega** → Agente detecta PI/PL → Lanza skill `comex-workflow` automáticamente
2. **Fin de mes: EERR de Odoo** → Skill `reporte-financiero-gerencial` genera reportes → Actualiza Análisis Contribución
3. **Demanda de Felipe** → Agente detecta → Lanza skill `shipping-plan` automáticamente

---

## Reglas de Trabajo

✋ **NUNCA editar/eliminar/sobreescribir archivos sin preguntar primero** — Andrés quiere control total

💬 **Antes de acciones importantes, aviso + confirmación** — Explicar qué voy a hacer y esperar OK

🇨🇱 **Hablar en español chileno** — Es la preferencia de Andrés

---

## Datos de Referencia

**Odoo UnionX:**
- URL: https://unionxb2b.odoo.com
- Base: bmya-innovatek-sh-prd-6981800
- Usuario: andres@grupoeter.cl

**GitHub:**
- Username de Andrés: AndyunionX

**Última actualización:** 2026-04-01
