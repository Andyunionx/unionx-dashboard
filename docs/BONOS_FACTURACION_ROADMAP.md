# Bonos Facturación — Roadmap

**Scope:** sólo pedidos **B2C** (Marketplace, Páginas Propias, Tiendas Propias, Fidelización).
**Tipo de bono:** **pozo grupal** — N personas × bono por persona = pozo target del mes.
**Distribución:** **manual** por el jefe de facturación entre el equipo.
**Dueño:** Gerencia Finanzas + Jefe Facturación.
**Dónde se ve:** App Operaciones → **💰 Bonos → Facturación**.
**Alimentación:** Andrés carga **N personas + bono por persona + pagado real** en la tab `💵 Carga Bonos`.
**Estado actual:** 25-may-2026.

---

## Decisiones cerradas

| # | Decisión | Valor |
|---|----------|-------|
| 1 | Scope | Solo B2C |
| 2 | Tipo de bono | Pozo grupal |
| 3 | Distribución | Manual (jefe) |
| 4 | Carga del pozo | N personas × bono por persona, ingresado manual |
| 5 | Umbral NC | 1% (sobre esto cae factor calidad) |
| 6 | Pesos | Configurables — preset recomendado 60/25/15 (Vol/Cal/SLA) |

---

## Fórmula

```
Pozo target mes  = N personas × bono por persona  (lo que cargas)
Pozo devengado   = Pozo target × factor combinado
factor combinado = f_vol × peso_vol + f_cal × peso_cal + f_sla × peso_sla
```

| Factor | Default peso | Cómo se calcula | Meta |
|--------|-------------:|-----------------|------|
| **Volumen** | 60% | `pedidos_b2c / meta_mes`. Tramos: <80%=0, 80-100% lineal, 100-120% bonus a 1.2× | ≥ 100% PPTO |
| **Calidad (NC)** | 25% | 1.0 si tasa NC ≤ 1%, cae lineal hasta 0 al doble del umbral | NC ≤ 1% |
| **SLA** | 15% | % pedidos facturados <24h tras venta (placeholder 95% hasta H1) | ≥ 95% |

> Pesos: si los 3 suman ≠ 100%, se normalizan. El usuario puede usar presets o personalizado.

---

## Flujo mensual

1. **Inicio de mes** → Andrés va a **💵 Carga Bonos** y carga `N personas` + `bono por persona`. La app calcula el pozo target = N × monto.
2. **Durante el mes** → consulta **📊 Resumen** y **👥 Pozo grupal** para ver avance.
3. **Cierre de mes** → el sistema muestra el **pozo devengado** según factores cumplidos.
4. **El jefe reparte** ese pozo entre las personas con criterio propio (la app no impone).
5. **Andrés registra** el bono total pagado real en **💵 Carga Bonos**.
6. **📈 Histórico** queda con devengado vs pagado y YTD acumulado.

---

## Fases

### 🟢 H0 — Operativo HOY (mayo 2026)

| Pieza | Dónde se ve | Meta | Resultado actual |
|-------|-------------|-----:|-----------------:|
| Pozo target (N × bono/persona) | Tab Carga Bonos / Tab Pozo grupal | Lo que tú definas | Pendiente carga inicial |
| Pedidos B2C facturados (mes) | Tab Resumen, métrica top | PPTO (~14.300 abr-may, ~24.500 jun) | abr-26: 13.951 (98%) · may-26 parcial: 6.867 |
| Meta automática desde PPTO | Tab Resumen | PPTO 2026 × mix 76.6% ÷ ticket $25.791 | Configurable |
| Tasa NC | Tab Resumen | ≤ 1% | abr-26: 0,29% ✅ · may: 0,16% ✅ |
| Pozo devengado mes | Tab Pozo grupal + Resumen | — | Calculado al cargar pozo |
| Bono pagado real | Tab Carga Bonos (input manual) | — | Se carga al cierre |
| Histórico YTD | Tab Histórico | — | Devengado + Pagado real + Δ |
| Alarmas cuello botella WMS | Alertas → Negocio | <100% carga equipo | 🔴 jun-26: PPTO +221% sobre capacidad |

**Limitación H0:** SLA usa placeholder 95% (todos los meses) porque aún no medimos timestamp emisión factura vs creación SO.

---

### 🟡 H1 — Próximas 2-4 semanas

| Pieza | Qué se entrega | Meta | Dónde |
|-------|----------------|------|-------|
| **SLA real** | Query Odoo: `account.move.invoice_date − sale.order.date_order`. Sumar % pedidos B2C con delta ≤ 24h. | ≥ 95% | Tab Resumen, métrica SLA |
| **Alarma 'mes va bajo bono'** | Si al día 20 del mes el avance proyectado < 80% → warning al jefe facturación | Cero meses bajo umbral | Alertas → Negocio |
| **Plantilla bulk** | Excel/CSV con `mes, n_personas, bono_persona, pagado_real` para cargar varios meses de una | Carga rápida histórico | Tab Carga Bonos (botón nuevo) |

---

### 🟠 H2 — 1-3 meses

| Pieza | Qué se entrega | Meta | Dónde |
|-------|----------------|------|-------|
| **Matching NC ↔ pedido B2C** | Hoy contamos NC totales del mes. Linkear NC.origen_so → pedido para saber cuáles son B2C. | NC% más preciso | Tab Resumen |
| **NC por causa raíz** | Tipificar NC por motivo (error facturación, devolución, anulación cliente, etc.) — solo las del área entran al cálculo | Calidad justa | Tab Detalle NC (nuevo) |
| **Aprobación mensual + PDF** | Botón "Aprobar mes" con firma del aprobador + timestamp. Export PDF planilla de pago. | Cero discusión post-cierre | Tab Cierre Mensual (nuevo) |
| **Bloqueo edición tras cierre** | Una vez aprobado un mes, los parámetros del pozo se bloquean (solo admin puede revertir) | Trazabilidad | Tab Carga Bonos |

---

### 🔵 H3 — 3-6 meses

| Pieza | Qué se entrega | Meta | Dónde |
|-------|----------------|------|-------|
| **Pozo ponderado por mix canal** | Marketplaces son más rápidos de facturar que B2C custom. Ponderar pedidos por complejidad. | Equidad inter-mes | Tab Resumen |
| **Forecast pedidos B2C (Prophet)** | Reemplazar Método C (estimación CLP→pedidos) por un Prophet directo a nivel pedidos | Meta más precisa | Tab Resumen, métrica Meta |
| **Dashboard externo para el equipo** | Tablero en pantalla del área Facturación con sus métricas live (sin login) | Awareness diario | Pantalla operativa |

---

## Estructura tabla Turso

```sql
CREATE TABLE bonos_facturacion_config (
    mes TEXT PRIMARY KEY,           -- YYYY-MM
    n_personas INTEGER,             -- cuántas personas en el equipo
    bono_persona_clp REAL,          -- target por persona si cumple 100%
    base_clp REAL,                  -- pozo total = n_personas × bono_persona
    bono_pagado_real_clp REAL,      -- lo efectivamente pagado al cierre
    observacion TEXT,
    actualizado_en TEXT
)
```

---

## Próxima acción de Andrés

1. **Cargar el pozo de mayo y meses anteriores** (N personas + bono por persona) en la tab `💵 Carga Bonos`.
2. **Revisar el pozo devengado** en la tab `👥 Pozo grupal` y el histórico en `📈 Histórico`.
3. **Cuando se cierre el mes**, registrar el bono total pagado real.

Cuando esté el primer mes cargado, podemos iterar: ¿los pesos cuadran con lo que pasó? ¿el umbral NC 1% es realista?
