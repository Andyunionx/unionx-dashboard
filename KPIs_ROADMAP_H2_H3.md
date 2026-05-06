# Roadmap KPIs · UnionX 2026-2028

## Resumen

El plan estratégico define ~66 KPIs distribuidos en 9 áreas. Esta sesión cubrió **Vista Ejecutiva + 3 áreas (Finanzas avanzada, Fulfillment, Comercial)** con datos Odoo en vivo y stubs manuales para los KPIs que requieren integraciones externas.

**Estado actual de cobertura:**

| Estado | Cantidad | Significado |
|---|---|---|
| 🟢 Automático en vivo (Odoo) | ~22 | Datos en vivo con cache 15min |
| 🟡 Manual con uploader | ~14 | Input mensual, persistencia JSON |
| 🟠 Esperando H2 (integración pendiente) | ~20 | Stub mostrado, fuente identificada |
| 🔴 Sin medir todavía | ~10 | Sin fuente identificada |

---

## Mapa completo por área

### ✅ Áreas cubiertas en esta sesión

#### Finanzas/Admin (Tab 7 de Planificación)
| KPI | Estado | Fuente |
|---|---|---|
| EBITDA % YTD | 🟢 | Metas 2026 |
| Margen contribución | 🟢 | Metas 2026 |
| DIO | 🟢 | Odoo (stock.quant + sale.order.line) |
| DSO B2B | 🟢 | Odoo (account.move out_invoice) |
| DPO | 🟢 | Odoo (account.move in_invoice) |
| CCC | 🟢 | Calculado: DIO + DSO − DPO |
| Cobertura intereses | 🟢 | Análisis Financiero (planilla) |
| Forecast accuracy ingresos | 🟢 | Cruce Metas 2026 (Meta vs Resultado) |
| % morosidad B2B | 🟢 | Odoo (aged buckets) |
| D/EBITDA | 🟢 | Análisis Financiero |
| Días cierre contable | 🟡 | Manual (input pendiente uploader) |

#### Fulfillment (página nueva)
| KPI | Estado | Fuente |
|---|---|---|
| ABC SKUs por valor | 🟢 | Odoo (sale.order.line últimos 365d) |
| Slow movers >180d | 🟢 | Odoo (stock.quant ∖ sale.order.line) |
| Stockouts SKUs A | 🟢 | Odoo (orderpoint vs qty_available) |
| OFR (Order Fulfillment Rate) | 🟡 → 🟠 | Manual hoy · WMS H2 |
| Order Cycle Time | 🟡 → 🟠 | Manual hoy · WMS H2 |
| Pick & Pack Accuracy | 🟡 → 🟠 | Manual hoy · WMS H2 |
| Inventory Accuracy | 🟡 → 🟠 | Manual hoy · WMS H2 |
| Productividad picking | 🟡 → 🟠 | Manual hoy · WMS H2 |
| Costo / pedido | 🟡 → 🟢 | Manual hoy · automatizable cuando sync Odoo esté activo |
| Tiempo recepción contenedor | 🟡 → 🟠 | Manual hoy · WMS H2 |

#### Comercial (página nueva)
| KPI | Estado | Fuente |
|---|---|---|
| AOV (Average Order Value) | 🟢 | Odoo (sale.order.amount_total) |
| Crecimiento ingresos YoY YTD | 🟢 | Odoo (comparación años) |
| Repeat customer rate (90d/180d) | 🟢 | Odoo (partners con ≥2 órdenes) |
| N° clientes B2B activos | 🟢 | Odoo (partner.is_company + ordenes 90d) |
| Top 10 clientes B2B | 🟢 | Odoo (sale.order agg) |
| Margen contribución por canal (B2B vs B2C) | 🟢 | Odoo (price_subtotal − purchase_price·qty) |
| Mix de canal | 🟢 | Odoo (calc % B2B vs B2C) |
| ROAS | 🟡 → 🟠 | Manual hoy · Google Ads + Meta API H2 |
| CAC | 🟡 → 🟠 | Manual · Google Ads API H2 |
| CLV | 🟡 → 🟠 | Manual · cálculo combinado Odoo + GA H2 |
| CLV / CAC | 🟡 → 🟠 | Manual · derivado de los anteriores |
| % Tráfico orgánico | 🟡 → 🟠 | Manual · Google Analytics 4 H2 |

---

## 🟠 Pendientes H2 (6-18 meses) — fuentes externas

### COMEX
| KPI | Fuente requerida | Esfuerzo | Acción siguiente |
|---|---|---|---|
| Lead time puerta a puerta | Planilla manual de embarques o agente Gmail expandido | Bajo | Agregar tab COMEX con uploader; el agente Gmail ya captura PI/PL |
| Costo aterrizaje USD/CBM | Output del workflow `comex-workflow` (skill ya existe) | Bajo | Cosechar del JSON que genera la skill |
| Precisión costeo pre vs post | Cruce skill `comex-workflow` + factura final en Odoo | Medio | Agregar reconciliación al cierre del embarque |
| Fill rate proveedor | Manual o ERP del proveedor | Medio | Uploader manual con tracking por PO |
| Cumplimiento ETA ±7 días | Tracking del forwarder + ETA en planilla | Medio | Pedir API a Seimex/forwarder |
| Cobertura cambiaria | Manual / planilla tesorería | Bajo | Uploader simple |

### Fulfillment (todos requieren WMS o capa de medición)
- Implementar **WMS** (Odoo Inventory avanzado o Mecalux EasyWMS)
- Alternativa intermedia: módulo custom Odoo que registre pick/pack timestamps
- Esfuerzo: **Alto** · 6-12 meses según opción

### Post-venta (área no cubierta esta sesión)
| KPI | Fuente requerida | Esfuerzo |
|---|---|---|
| Tasa de devolución | Odoo (out_refund) | 🟢 Calculable | Bajo — falta implementar página |
| Tiempo resolución devolución | Helpdesk (Zendesk/Freshdesk) | Medio |
| Recovery rate | Tracking RMA en Odoo + producto reacondicionado | Medio |
| Reclamos SERNAC | Portal SERNAC + uploader | Bajo (manual) |
| Costo logística inversa | P&L cuenta específica | Bajo (calculable cuando sync activo) |

### SAC
- Implementar **Helpdesk omnicanal** (Zendesk, Freshdesk, Help Scout)
- Esfuerzo: **Medio** · 2-4 meses
- Una vez integrado: FRT, FCR, AHT, CSAT, NPS, tickets/pedido todo automático

### Logística
| KPI | Fuente | Esfuerzo |
|---|---|---|
| OTD (On-Time Delivery) | API Blue Express + Recíbelo | Medio |
| Tasa de incidentes | API couriers + reglas de negocio | Medio |
| Costo logístico/venta | P&L (cuenta courier) / venta Odoo | Bajo (calculable cuando sync activo) |
| Tarifa courier por zona | Conciliación factura courier | Medio |

### Marketing
- Integrar **Google Ads API**, **Meta Marketing API**, **Google Analytics 4 Data API**
- Esfuerzo: **Medio** · 1-3 meses por integración
- Una vez integrado: ROAS, CAC, CLV, % orgánico, recompra 90d todo automático

### Tecnología
| KPI | Fuente | Esfuerzo |
|---|---|---|
| Uptime sistemas críticos | Monitoring (UptimeRobot, Pingdom) | Bajo |
| Cobertura integración | Auditoría manual | Bajo |
| Calidad datos | Reglas custom sobre data warehouse | Medio (depende de DWH) |

---

## 🔴 Sin medir todavía — H3 (18-24m+)

| KPI | Por qué no se mide | Plan |
|---|---|---|
| Reingreso veloz al stock (post-devolución) | No hay timestamp de cuándo entra al stock disponible | Requiere ajustes en proceso de bodega + WMS |
| % devoluciones evitables (causa raíz) | Falta tipificación al ingreso | Workflow RMA con causa obligatoria |
| % consultas autoservicio | Sin chatbot/FAQ con tracking | Implementar chatbot + métricas |
| Voice of Customer estructurado | No hay flujo de tickets → mejora producto | Definir ciclo formal |
| Marketing Mix Modeling | Modelo predictivo no existe | H3 — proyecto largo |

---

## 📍 Próximos hitos por horizonte

### H1 — restantes (próximos 1-3 meses)
1. **COMEX** — crear página con datos del agente Gmail + planilla manual (similar patrón Fulfillment)
2. **Post-venta** — crear página con tasa devolución desde Odoo (out_refund)
3. **Logística** — crear página con costo logístico/venta calculable (cuando sync active)
4. **Sincronizador Odoo** — habilitar tarea Task Scheduler (depende de la BD que estás trabajando en Visual)
5. **Reportes ejecutivos automáticos al CEO** — Lunes 9 AM ya tiene infraestructura, falta `CEO_EMAIL` env var
6. **Avisar a Vicente** sobre las cotizaciones espurias del 28/04 (manual)

### H2 (3-12 meses)
1. **Helpdesk** (Zendesk/Freshdesk) — desbloquea SAC + parte de Post-venta
2. **APIs couriers** (Blue Express, Recíbelo) — desbloquea Logística
3. **Google Ads/Meta + GA4** — desbloquea Marketing
4. **WMS o capa de medición** — desbloquea Fulfillment operacional
5. **Data warehouse** (BigQuery/Postgres) — fuente única
6. **Forecast por SKU con ML** — alimenta shipping plan COMEX

### H3 (12-24m+)
1. **Predictivo de demanda + reposición automática**
2. **Multi-bodega o expansión regional (Perú/Colombia)**
3. **Marcas propias maduras ≥40% ventas**
4. **Marketing Mix Modeling**

---

## Cómo se actualiza este documento

- **Cuando un KPI cambia de estado** (ej: 🟡 → 🟢 porque se conectó Odoo), actualizar la columna "Estado".
- **Cuando se identifique fuente** para un 🔴, moverlo a 🟠 con la fuente.
- **Cuando se agregue un KPI** nuevo del plan estratégico, agregarlo en la sección correspondiente.

Última actualización: 2026-04-30 — sesión de implementación Vista Ejecutiva + Finanzas avanzada + Fulfillment + Comercial.

---

## Anexo: Roadmap específico **Costo Operativo Total**

### 🟢 H1 — Implementado (completado en esta sesión)
1. **Modo estimado desde P&L** con factores de atribución configurables (config/costo_operativo.yaml).
2. **Template Excel descargable** para que terceros (RRHH, Contabilidad) carguen detalle real con conceptos sugeridos: Sueldos Operaciones, Arriendo Megacentro, Servicios bodega, Flete despacho, Insumos packing, Combustible, Movilización, Comisión marketplaces, Logística inversa, etc.
3. **Uploader en Fulfillment Tab 5 → 'Carga por terceros'** que parsea el Excel y persiste en `data/kpis_manuales/costo_operativo_<año>.json`.
4. **Análisis automático con benchmarks de mercado** del Plan UnionX:
   - Costo logístico/venta (8-14% según ticket)
   - % Variable/Total (50-65% saludable)
   - Costo/pedido USD (3-7 ref USA-Chile)
5. **Recomendaciones automáticas** vía heurísticas:
   - Estructura demasiado fija → tercerización
   - Concentración Top 3 conceptos > 65% → negociación con esos proveedores
   - Costo/venta > benchmark max → revisar mix couriers, slotting, AOV
   - Tendencia mes a mes (alza > 10% vs promedio) → identificar concepto

### 🟡 H2 — Para los próximos 3-6 meses
- **Comparación período anterior** automática (mes vs mismo mes año previo).
- **Drill-down por proveedor** dentro de cada concepto variable (ej: cuál courier es más caro por zona).
- **Alertas push** cuando un concepto excede umbral configurable.
- **Integración con cash flow rolling 13 semanas** para prever tensión de caja.

### 🟠 H2-H3 — Migración a automatización vía Odoo (6-18 meses)
- Implementar **cuentas analíticas** en Odoo separando: Operaciones · Comercial · Administración · Finanzas.
- Una vez migrado, el módulo `kpis_odoo.py` puede consultar directamente `account.analytic.line` filtrado por la cuenta analítica de Operaciones.
- Esto elimina la necesidad del uploader manual (queda solo como override puntual).

### 🔵 H3 — Largo plazo (18-24m+)
- **Modelo predictivo**: forecast de costo operativo basado en venta proyectada (ML simple regresión por concepto).
- **Optimizador**: dado un objetivo de margen, sugerir qué cuentas atacar primero (mayor impacto).
