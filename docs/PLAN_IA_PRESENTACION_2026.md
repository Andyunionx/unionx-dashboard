# 🧠 Plan IA — Operaciones y Finanzas

> **PPT objetivo:** Plan IA - Operaciones y Finanzas
> **Audiencia:** Gerencias UnionX · **Duración:** 30 minutos · **Fecha:** 26-may-2026
> **Autor:** Andrés Browne · **Apoyo:** Claude

---

## 📑 Estado del plan de trabajo

| Etapa | Slide(s) | Estado |
|---|---|---|
| E1 — Portada + Resumen ejecutivo | 1-2 | ✅ Cerrado |
| E2 — Status actual / Foto 360 | 3 | ✅ Cerrado |
| E3 — El Cerebro UnionX (5 fases + ejemplo RAW) | 4-5 | ✅ Cerrado |
| E4 — Mirada Empresa | 6 | ✅ Cerrado |
| E5 — Mirada Área (7 áreas, paso a paso F1→F5) | 7-13 | ✅ Cerrado |
| E5b — Eficiencias overview + plantilla + paso a paso reducción | 14-16 | ✅ Cerrado |
| E5c — Otras eficiencias + Qué necesitamos | 17-18 | ✅ Cerrado |
| E6 — Carta Gantt (macro + hitos + calendario) | 19-21 | ✅ Cerrado |
| E7 — KPIs / Resultados esperados | 22 | ✅ Cerrado |
| E8 — Riesgos y mitigaciones | 23 | ✅ Cerrado |
| E9 — Cierre / próximos pasos | 24 | ✅ Cerrado |
| E10 — Anexo técnico | 25 | ✅ Cerrado |
| **E11 — Generar PPT con skill `pptx`** | — | ⏳ Final |

---

## Slide 1 — Portada

```
┌──────────────────────────────────────────────┐
│  [LOGO UNIONX]                               │
│                                              │
│  Plan IA                                     │
│  Operaciones y Finanzas                      │
│                                              │
│  Hoja de ruta 2026                           │
│                                              │
│  Andrés Browne · Gerencia Finanzas + SC      │
│  26 de mayo de 2026                          │
└──────────────────────────────────────────────┘
```

**Paleta UnionX (extraída del logo oficial):**
- **Primario** `#4A90E2` (azul UnionX — del logo)
- **Texto oscuro** `#0F172A` · **Texto claro** `#475569`
- **Acento positivo** `#10B981` (verde KPI)
- **Alerta** `#DC2626` · **Warning** `#EA580C`
- **Fondo** `#F8FAFC`

**Logo:** `data/branding/unionx_logo.png` (descargado de unionx.cl)

---

## Slide 2 — Resumen ejecutivo

**Mensaje único:** UnionX ya tiene los cimientos del Cerebro IA construidos. Cerramos 5 piezas y liberamos eficiencias por **~$33 MM en 2026** y **~$100 MM/año en régimen**.

| Hoy | Diciembre 2026 |
|---|---|
| Procesos manuales, 75% errores reportados | < 5% errores, validación automática |
| Andrés consolida reportes a mano cada lunes | 3 reportes auto-generados lunes 9:00 |
| Decisiones con dato de hace 30 días | Decisiones con dato fresco (< 1 día) |
| Excel paralelos en cada PC | 1 cerebro centralizado consultable |
| Equipo captura datos | Equipo valida y analiza |

**Los 2 objetivos del plan:**
1. **Centralización (Cerebro Union X)** — Una sola fuente de verdad operativa para Ventas + Finanzas + Operaciones + Contabilidad + SAC + Facturación.
2. **Reducción de costos** — ~$33 MM ahorro identificado en 2026 · ~$100 MM run-rate anual.

---

## Slide 3 — Foto 360 / Status actual

### Lo que ya está vivo HOY

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       CEREBRO UNION X (en construcción)                 │
│                                                                         │
│  📊 3 APPS WEB                              🤖 3 AGENTES IA              │
│  ├─ App Ventas (17 vistas, 5 usuarios)      ├─ Agente COMEX Gmail ✅    │
│  ├─ App Finanzas (P&L por LN, EBIT, FCST)   ├─ Agente Compras (SII×Odoo)│
│  └─ App Operaciones (COMEX/Stock/B2B/Bonos) └─ Agente Cobranza ⏸️ pausa │
│                                                                         │
│  🧩 6 SKILLS                                🔌 INTEGRACIONES            │
│  ├─ comex-workflow                          ├─ Odoo (XML-RPC)           │
│  ├─ shipping-plan                           ├─ Gmail API                │
│  ├─ distribucion-comisiones                 ├─ Drive / Sheets API       │
│  ├─ reporte-financiero-gerencial            ├─ SII (Playwright)         │
│  ├─ segmentacion-pedido                     └─ Turso libSQL             │
│  └─ EERR clasificador (88 reglas)                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

| Pieza | Estado | Quién usa |
|---|---|---|
| App Ventas | 🟢 Producción · sync 3×/día Odoo | Andrés, Felipe, Nicolas, Gabriela, Martín |
| App Finanzas | 🟢 Producción · P&L LN + EBIT + FCST | Andrés + Gerencia |
| App Operaciones | 🟢 Producción | Operaciones |
| Agente COMEX Gmail | 🟢 Polling 2 min · Steven/Felipe/Vicente | Automático |
| Agente Compras Odoo | 🟢 Daily · email a Camila + Víctor | Contabilidad |
| Agente Cobranza | 🔴 Pausado por incidente 23-25 may | Víctor (manual) |
| EERR Clasificador | 🟢 88 reglas · mensual | Andrés |
| 6 Skills Claude | 🟢 On-demand | Andrés |

---

## Slide 4 — El Cerebro Union X

### El problema (HOY)

```
                  ┌─────────────────────────┐
                  │       Odoo (ERP)        │
                  │   potente, pero solo    │
                  │   1 de las fuentes      │
                  └────────────┬────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌──────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│ Drives x persona │  │ Integraciones   │  │ Marketplaces     │
│ formatos propios │  │ a medias        │  │ (ML, Fala, etc)  │
│ archivos locales │  │                 │  │                  │
└──────────────────┘  └─────────────────┘  └──────────────────┘
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               ▼
            Cada área arma SU versión → valor a medias
            Datos atrasados · ineficiencias invisibles · imposible escalar
```

### El Cerebro (la respuesta)

> Centralizar para tener **data en vivo**, capturar **eficiencias**, dejar el **valor agregado dentro de la empresa**, **entender las ineficiencias** y tener toda la **base de datos internalizada**.

### Las 5 fases

| Fase | Nombre | Qué pasa |
|---|---|---|
| **F1** | **Auditar** | Mapear cómo trabaja cada área. Fuentes, archivos, pasos a mano, pérdida de info |
| **F2** | **Integrar (semiautomático)** | Unificar fuentes en un modelo único, aún con intervención humana |
| **F3** | **Automatizar y eliminar lo descentralizado** | Apagar Drives/Excel paralelos. Fuente única vive sin intervención |
| **F4** | **Eficientar** | Sobre lo centralizado: optimizar integraciones, eliminar redundancia |
| **F5** | **Agentes** | IA replica los flujos manteniendo la esencia del Cerebro |

---

## Slide 5 — Caso paradigmático: RAW de Ventas

**El recorrido completo F1 → F3 ya está logrado. Lo replicamos en cada área.**

| Fase | Antes | Hoy |
|---|---|---|
| F1 Auditar | Construido por un tercero, sin documentar | 41 columnas mapeadas, fuente por fuente, documentado en `docs/VENTAS_ESTADO_2026-05.md` |
| F2 Integrar | Info de Odoo + Excel + Drive + marketplaces, manual | Modelo unificado en Turso, semi-auto |
| F3 Automatizar | Cada área hacía SU versión del RAW | RAW único en vivo, integrado con Planificación + Operaciones + Forecasting Finanzas |
| F4 Eficientar | — | **Pendiente:** comisiones/logística/marketing por canal → margen real |
| F5 Agentes | — | **Pendiente:** agente que auto-cure la matriz productos y maestra canales |

**Mensaje a Gerencias:** lo que logramos con Ventas, lo replicamos en cada área de la empresa.

---

## Slide 6 — Mirada EMPRESA

| Área | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|
| **Ventas** | ✅ 100% | ✅ 100% | ✅ 100% | 🟡 30% · *Cargar comisión/logística/mkt por canal* | 🔴 0% · *Diseñar agente RAW auto-curado* |
| **Finanzas** | ✅ 100% | ✅ 100% | 🟡 70% · *Cerrar Sheet KAM live* | 🔴 10% · *Reporte unificado L9AM* | 🔴 0% · *Definir scope* |
| **Operaciones** | ✅ 100% | ✅ 100% | 🟡 60% · *Forecast a Odoo auto* | 🔴 0% | 🟡 30% · *COMEX v2 sin validación intermedia* |
| **Contabilidad** (Compras + Cobranza) | ✅ 100% | 🟡 50% · *Integrar Cobranza al pipeline* | 🟡 30% · *Fix incidente Cobranza y reactivar cron* | 🔴 0% | 🟡 40% · *Compras en prod, Cobranza pausado* |
| **SAC / Log. Inversa** | 🟡 30% · *Completar auditoría flujos NC y devoluciones* | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% |
| **Facturación** | ✅ 100% | 🔴 0% · *Centralizar criterio facturación por canal* | 🔴 10% · *POC etiqueta+deadline activo* | 🔴 0% | 🔴 0% |
| **EERR / Reportes** | 🟡 50% · *Completar mapeo cuentas* | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% |

**Cada celda 🟡/🔴 en la PPT incluye un mini-callout con el "próximo paso" abajo.**

---

## Slides 7-13 — Mirada ÁREA: paso a paso por cada área del Cerebro

> **Formato común:** cada slide muestra el recorrido F1→F5 con detalle de los pasos siguientes.
> Visualmente: una banda horizontal con 5 cajas (F1 a F5), cada caja con su estado (✅/🟡/🔴) y debajo el detalle del próximo paso concreto.

---

### Slide 7 — VENTAS (Caso paradigmático)

| Fase | Estado | Qué pasó / qué pasa |
|---|---|---|
| F1 Auditar | ✅ 100% | 41 columnas mapeadas, fuente por fuente. Documentado en `VENTAS_ESTADO_2026-05.md` |
| F2 Integrar | ✅ 100% | Modelo unificado en Turso. Sync Odoo 3×/día + cada hora mes corriente |
| F3 Automatizar | ✅ 100% | App Ventas única, 17 vistas, 5 usuarios. Eliminados los Excel paralelos. RAW Excel 41 cols on-demand |
| F4 Eficientar | 🟡 30% | **Próximo paso:** Cargar tabla `comisiones_canal` (% por canal × mes). Cargar logística y marketing por canal. Overlay en extract para que `margen_final` deje de ser igual a `margen_front` |
| F5 Agentes | 🔴 0% | **Próximo paso:** Agente que auto-cure Matriz Productos y Maestra Canales cuando aparezcan SKUs/canales nuevos. Alerta proactiva |

**Impacto al cerrar F4:** Margen real por canal → permite decisiones comerciales informadas (cortar canales tóxicos, renegociar tarifas).

---

### Slide 8 — FINANZAS (P&L LN, EBIT, FCST)

| Fase | Estado | Qué pasa |
|---|---|---|
| F1 Auditar | ✅ 100% | EERR clasificado con 88 reglas. Mapeo cuentas analíticas completo |
| F2 Integrar | ✅ 100% | App Finanzas: P&L 7 líneas, EBIT consolidado, FCST Ene-Dic, drill-down canal/KAM/LN |
| F3 Automatizar | 🟡 70% | **Próximo paso:** Cerrar gap Sheet KAM ($216 MM YTD-Abr menos vs Drive). Sheet en vivo, cron cada 6h ya activo |
| F4 Eficientar | 🔴 10% | **Próximo paso:** Reporte unificado Lunes 9 AM (los 3 reportes en uno). Eliminar planillas paralelas de gerencia |
| F5 Agentes | 🔴 0% | **Próximo paso:** Agente que arme reportes ejecutivos sin trigger manual + alertas proactivas EBIT por canal |

**Impacto al cerrar F4-F5:** Andrés deja de armar reportes a mano cada lunes (~10 hrs/sem liberadas).

---

### Slide 9 — OPERACIONES (COMEX + Stock + B2B/B2C + Forecast + Bonos)

| Fase | Estado | Qué pasa |
|---|---|---|
| F1 Auditar | ✅ 100% | Flujos COMEX (PI→PL→OHNSO→Costeo), stock LIVE, capacidad WMS auditados |
| F2 Integrar | ✅ 100% | App Operaciones con 5 vistas integradas. Stock LIVE desde Odoo. Bonos Facturación con pozo grupal |
| F3 Automatizar | 🟡 60% | **Próximo paso:** Forecast B2C a Odoo automático (hoy se vuelca manual). Costo operativo por canal real (no allocated lineal) |
| F4 Eficientar | 🔴 0% | **Próximo paso:** Análisis costo variable evitable / pedido (para decisiones fulfillment). Reducción capacidad bodega si stock baja |
| F5 Agentes | 🟡 30% | **Activo:** Agente COMEX Gmail polling cada 2 min. **Próximo paso:** COMEX v2 — sin validación humana intermedia (auto-ejecuta skill al detectar PI/PL completo) |

**Impacto al cerrar F4-F5:** Permite la eficiencia "Fulfillment +10%" y "Renegociación logística" con datos sólidos.

---

### Slide 10 — CONTABILIDAD (Compras + Cobranza)

| Fase | Estado | Qué pasa |
|---|---|---|
| F1 Auditar | ✅ 100% | Mapeo SII×Odoo×Drive completo |
| F2 Integrar | 🟡 50% | Compras: 3 fuentes cruzadas a diario. **Próximo paso:** Integrar Cobranza al mismo pipeline |
| F3 Automatizar | 🟡 30% | Compras: cuadre 3-vías automático + reporte 7 AM a Camila/Víctor. **Próximo paso:** Fix incidente Agente Cobranza (root cause análisis Filtros Odoo `date` vs `invoice_date`) y reactivar cron |
| F4 Eficientar | 🔴 0% | **Próximo paso:** Validación cruzada con auditoría externa automatizada. Reducir horas de auditor externo |
| F5 Agentes | 🟡 40% | **Activo:** Agente Compras Odoo en prod. **Pausado:** Cobranza (incidente 23-25 may). **Próximo paso:** Fix + 2 ciclos validados antes de reactivar |

**Impacto al cerrar F3-F5:** Habilita salida de 2 Analistas Contables (jul + oct 2026).

---

### Slide 11 — SAC / LOGÍSTICA INVERSA

| Fase | Estado | Qué pasa |
|---|---|---|
| F1 Auditar | 🟡 30% | **Próximo paso URGENTE:** Completar auditoría flujos NC + devoluciones. Mapear inputs/outputs del informe semanal que arma Jorgelis |
| F2 Integrar | 🔴 0% | **Próximo paso:** Modelo unificado de NC en Turso (extender tabla `ventas`) + integración con WMS para devoluciones |
| F3 Automatizar | 🔴 0% | **Próximo paso:** Informe 100% auto. Email semanal sin intervención |
| F4 Eficientar | 🔴 0% | Pendiente F1-F3 |
| F5 Agentes | 🔴 0% | Pendiente F1-F3 |

**Plan acelerado:** Cerrar F1→F3 antes del **31-jul-2026** para habilitar salida Analista Log. Inv. (Jorgelis).

---

### Slide 12 — FACTURACIÓN

| Fase | Estado | Qué pasa |
|---|---|---|
| F1 Auditar | ✅ 100% | Flujos por canal mapeados, criterios facturación documentados |
| F2 Integrar | 🔴 0% | **Próximo paso:** Centralizar criterio facturación por canal en tabla única (hoy cada facturadora tiene su Excel) |
| F3 Automatizar | 🔴 10% | **Activo:** POC etiqueta + deadline. **Próximo paso:** Llevarlo a producción + 2 ciclos validados sin error |
| F4 Eficientar | 🔴 0% | Pendiente F2-F3 |
| F5 Agentes | 🔴 0% | Pendiente F2-F3 |

**Plan acelerado:** F2-F3 antes del **15-ago-2026** (salida Facturadora #1) y **15-sep-2026** (salida #2).

---

### Slide 13 — EERR / REPORTES GERENCIALES

| Fase | Estado | Qué pasa |
|---|---|---|
| F1 Auditar | 🟡 50% | **Próximo paso:** Completar mapeo de las cuentas que faltan del P&L Drive (gap GAV) |
| F2 Integrar | 🔴 0% | **Próximo paso:** Skill `reporte-financiero-gerencial` ya existe pero requiere trigger manual. Integrar al pipeline |
| F3 Automatizar | 🔴 0% | **Próximo paso:** Reporte mensual automático día 5 del mes siguiente |
| F4 Eficientar | 🔴 0% | Pendiente F2-F3 |
| F5 Agentes | 🔴 0% | Pendiente F2-F3 |

**Plan:** Cerrar F1→F3 antes del **30-sep-2026** para habilitar salida Control de Gestión (Gabriela).

---

## Slide 14 — Bloque 2: Eficiencias identificadas — Overview

**Mensaje:** Hemos identificado **~$33 MM en 2026** y **~$100 MM/año run-rate** en eficiencias que la IA habilita directamente.

| Categoría | Ahorro 2026 | Run-rate anual |
|---|---:|---:|
| 🧑‍💼 Personal (6 cargos, incl. cargas patronales) | **~$28,4 MM** | **~$91,0 MM** |
| 📦 Fulfillment Falabella +10% share | ~$0,6 MM | ~$1,28 MM |
| 🔧 Reducción usuarios Odoo (35 → 15) | ~$2,7 MM | **$5,47 MM** |
| 🔌 Reducción Yuju 50% | ~$1,8 MM | **$3,68 MM** |
| **TOTAL** | **~$33 MM** | **~$101 MM/año** |

---

## Slide 15 — Reducción de plantilla por automatización

| Cargo (centro costo) | Sale | Bruto/mes | Meses 2026 | Ahorro 2026 | Anualizado |
|---|---|---:|---:|---:|---:|
| Analista Logística Inversa | 31/07/2026 | $1.004.852 | 5 | $5,02 MM | $12,06 MM |
| Analista Contable (#1) | 31/07/2026 | $1.015.754 | 5 | $5,08 MM | $12,19 MM |
| Analista Contable (#2) | Oct 2026 | $770.000 | 2 | $1,54 MM | $9,24 MM |
| Facturadora (#1) | 15/08/2026 | $895.815 | 4,5 | $4,03 MM | $10,75 MM |
| Facturadora (#2) | 15/09/2026 | $822.212 | 3,5 | $2,88 MM | $9,87 MM |
| Control de Gestión | 30/09/2026 ⏳ | $2.258.096 | 3 | $6,77 MM | $27,10 MM |
| **Subtotal bruto** | | $6,77 MM/mes | | **$25,32 MM** | **$81,21 MM** |
| **+ Cargas patronales 12%** | | | | **~$28,4 MM** | **~$91,0 MM** |

**Visual sugerido para PPT:** línea de tiempo Jul → Ago → Sep → Oct con un avatar/icono por cargo cuando sale.

**Línea de tiempo de salidas:**
```
Jul 26          Ago 26          Sep 26          Oct 26
  │               │               │               │
  31 ─ Analista   15 ─ Factur.1   15 ─ Factur.2   X ─ Anal. Cont.2
  31 ─ Anal.Cont.1                30 ─ Ctrl Gest.
       Log.Inv.
```

---

## Slide 16 — ⭐ Paso a paso para la reducción de personal

> Para cada cargo: qué hace hoy → qué IA lo reemplaza → en qué fase está el reemplazo → qué necesita para activarse.

| Cargo | Tareas hoy | IA reemplaza | Estado IA | Prerrequisito | Fecha |
|---|---|---|---|---|---|
| **Analista Log. Inv.** (Jorgelis) | Informe semanal NC + devoluciones manual | Agente SAC/Log. Inversa | 🔴 F1 30% | Auditar flujos NC/devoluciones · automatizar informe semanal · 2 ciclos validados | 31-jul-2026 |
| **Analista Contable #1** (Joselyn) | Cuadrar SII×Odoo · revisar partners · distribuir cuentas grandes | Agente Compras (ya activo) | 🟢 F5 50% | Onboarding Camila/Víctor en flujo nuevo · agente estable 2 meses | 31-jul-2026 |
| **Analista Contable #2** (F. Avila) | Apoyo cobranza · revisión partners | Agente Cobranza | 🔴 F3 0% (incidente) | Fix root cause Cobranza · 2 ciclos validados sin error · Camila absorbe carga residual | Oct-2026 |
| **Facturadora #1** (Iris) | Facturación manual por canal | POC etiqueta + deadline | 🟡 F3 10% | POC en producción · 2 ciclos sin error · validación Yohana | 15-ago-2026 |
| **Facturadora #2** (F. Stipp) | Facturación manual por canal | POC etiqueta + deadline (#1 ya validado) | 🔴 (sigue #1) | Validación final flujo · Yohana redistribuye carga | 15-sep-2026 |
| **Control de Gestión** (Gabriela) | Reportes a gerencias · planificación financiera · análisis ad-hoc | App Finanzas + reporte unificado L9AM + chat ejecutivo | 🟡 F4 10% | Apps cubren 100% de los reportes que arma · chat ejecutivo POC · validación 2 meses | 30-sep-2026 |

**Mensaje clave:** la salida de cada persona requiere que la IA que la reemplaza esté en producción **2 meses antes**, con validación humana cruzada durante ese período. No es eliminación brusca: es transición planificada.

---

## Slide 17 — Otras eficiencias habilitadas por IA

### A. Fulfillment Falabella +10% share
- **Tarifa fulfillment Fala:** $2.490/pedido (sin última milla)
- **Tarifa fulfillment ML:** $3.150/pedido (sin última milla)
- **Costo bodega allocated:** ~$2.887/pedido
- **Diferencial Fala vs bodega:** +$397/pedido a favor de fulfillment
- **+10% share Fala (~269 pedidos/mes):** **~$1,28 MM/año**
- **ML NO conviene migrar** ($3.150 > $2.887 bodega = pierde $263/ped)
- **Habilitador IA:** Análisis volumen por canal + costo variable evitable real

### B. Reducción usuarios Odoo (35 → 15)
- Costo Odoo total: $9,57 MM/año
- Costo/usuario: $273.428/año (tarifa lineal confirmada)
- 20 usuarios menos: **$5,47 MM/año**
- **Habilitador IA:** Apps centralizan lo que hoy se hace en Odoo (5 dashboards reemplazan acceso directo de 20 personas)

### C. Reducción Yuju 50%
- Costo Yuju actual: $7,36 MM/año
- A la mitad: **$3,68 MM/año**
- **Habilitador IA:** Sustituir Yuju por integraciones directas Odoo ↔ marketplaces vía Agente COMEX

---

## Slide 18 — Qué necesitamos para lograr las otras eficiencias

| Eficiencia | Prerrequisito técnico | Prerrequisito organizacional | Owner | Deadline |
|---|---|---|---|---|
| **Fulfillment +10% Fala** | Cálculo costo variable evitable real (no allocated) · plan migración SKUs · análisis stock fulfillment requerido | Decisión Comité Comercial · ajustar política inventario | Andrés + Comité | Q4 2026 |
| **Odoo 35 → 15** | Apps cubren los flujos de los 20 usuarios a quitar · capacitación 2 sesiones · audit usos reales últimos 90 días | Comunicación al equipo · acuerdos por área | Andrés + IT | Q3 2026 |
| **Yuju ÷2** | Decidir qué marketplaces salen · integración directa alternativa lista · validación 1 ciclo completo | Validación Felipe (comercial) · plan rollback si falla | Andrés + Felipe | Q3 2026 |

⚠️ **Slide visualmente importante** — esta es la base de la Gantt del slide siguiente.

---

## Slide 19 — Carta Gantt (vista macro)

**3 capas en un solo timeline:** Cerebro (recorrido F2→F5 por área) · Salidas de personal (hitos) · Otras eficiencias.

```
                        Jun     Jul     Ago     Sep     Oct     Nov     Dic
──────────────────────────────────────────────────────────────────────────────
🎯 HITOS PERSONAL                ▼ 31    ▼ 15    ▼ 15    ▼ X    
                              Anal.LI  Fact.   Fact.   AC#2
                              + AC#1   #1      #2 +
                                              CG 30

📋 CAPA CEREBRO POR ÁREA

SAC/Log.Inv  F1→F3      ████████
Contabilidad F2→F3      ████████
Facturación  F2→F3              ████████
EERR/Reportes F1→F3                     ████████████
Finanzas     F3→F4      ████████████
Ventas       F4 Mg Real ████████
Ventas       F5 Agente                          ████████
Operaciones  F3 FCST→Odoo       ████████
Operaciones  F5 COMEX v2                ████████
Cerebro VOZ  POC + prod                                 ████████████

💸 OTRAS EFICIENCIAS

Odoo 35→15                      ████████
Yuju ÷2                         ████████
Fulfillment Fala +10%                           ████████████
```

**Lectura del slide:**
- **Capa morada** (hitos) — fechas donde sale gente
- **Capa azul** (Cerebro) — qué fase F2-F5 se cierra en cada área
- **Capa verde** (eficiencias) — Odoo + Yuju + Fulfillment

**Visual sugerido en PPT:** barras Gantt clásicas con colores diferenciados, hitos con triángulo invertido ▼ y nombre del cargo que sale.

---

## Slide 20 — Hitos críticos: qué entregamos antes de cada salida

> Para cada salida de persona, listamos los entregables IA que tienen que estar EN PRODUCCIÓN y VALIDADOS antes. **No es eliminación brusca: es transición planificada.**

### 🔴 Hito 1 — 31-jul-2026 (salen Analista Log. Inv. + Analista Contable #1)

| Entregable | Owner | Deadline interno |
|---|---|---|
| Agente SAC/Log. Inv. F1 completo (auditoría flujos NC + devoluciones) | Andrés + Claude | 15-jun |
| Agente SAC/Log. Inv. F2-F3 (informe semanal 100% auto) | Andrés + Claude | 30-jun |
| Validación 2 ciclos sin error (semanas 1 y 2 de julio) | Andrés | 15-jul |
| Agente Compras 60 días en producción sin incidente | Andrés + Víctor | 15-jul |
| Onboarding Camila/Víctor en flujo nuevo | Víctor | 20-jul |
| Comunicación interna salidas | RR.HH. | 25-jul |

### 🟡 Hito 2 — 15-ago-2026 (sale Facturadora #1)

| Entregable | Owner | Deadline interno |
|---|---|---|
| POC etiqueta+deadline en producción | Andrés + Yohana | 30-jun |
| 2 ciclos completos sin error (julio) | Yohana | 31-jul |
| Tabla criterio facturación por canal centralizada | Yohana | 15-jul |
| Validación final flujo nuevo | Yohana | 10-ago |

### 🟡 Hito 3 — 15-sep-2026 (sale Facturadora #2)

| Entregable | Owner | Deadline interno |
|---|---|---|
| Flujo facturación #1 ya estable (post-15-ago) | Yohana | 31-ago |
| Redistribución carga residual | Yohana | 31-ago |
| Validación 30 días con flujo #1 sola | Yohana | 14-sep |

### 🔴 Hito 4 — 30-sep-2026 (sale Control de Gestión - Gabriela)

| Entregable | Owner | Deadline interno |
|---|---|---|
| EERR / Reportes F1 completo (mapeo cuentas faltantes) | Andrés | 31-jul |
| Skill `reporte-financiero-gerencial` integrada al pipeline (F2) | Andrés + Claude | 15-ago |
| Reporte mensual automático día 5 (F3) en producción | Andrés | 15-sep |
| Reporte unificado Lunes 9 AM (Finanzas F4) 2 ciclos OK | Andrés | 22-sep |
| Chat ejecutivo POC (Cerebro Voz) operativo | Andrés + Claude | 22-sep |
| Validación 2 meses con apps cubriendo 100% reportes ad-hoc | Andrés | 25-sep |

### 🟡 Hito 5 — Octubre 2026 (sale Analista Contable #2)

| Entregable | Owner | Deadline interno |
|---|---|---|
| Fix root cause incidente Agente Cobranza | Andrés + Claude | 15-jun (urgente) |
| Agente Cobranza reactivado + 60 días sin error | Andrés + Víctor | 15-sep |
| Camila absorbe carga residual cobranza | Víctor | Sept |

### 🟢 Otras eficiencias (Q3-Q4 2026)

| Eficiencia | Deadline | Prerrequisitos |
|---|---|---|
| Odoo 35→15 usuarios | 30-sep-2026 | Audit usos 90d · capacitación · apps cubren 100% flujos |
| Yuju ÷2 | 30-sep-2026 | Definir marketplaces que salen · integración alternativa · 1 ciclo validado |
| Fulfillment Falabella +10% | 31-dic-2026 | Análisis costo variable evitable · plan migración SKUs · decisión Comité Comercial |

---

## Slide 21 — Vista calendario (visual de respaldo)

```
        JUN-26              JUL-26              AGO-26              SEP-26              OCT-26
  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
  │ • SAC F1-F3    │  │ • SAC F3 valid │  │ • Fact #1 prod │  │ • Fact #2 valid│  │ • Cobranza OK  │
  │ • Cobranza fix │  │ • POC factur   │  │ • Odoo audit   │  │ • EERR F3 prod │  │ • Cerebro Voz  │
  │ • Comisión cnl │  │ • Compras 60d  │  │ • Yuju decisión│  │ • Rep L9AM 2cic│  │ • Fulfill plan │
  │ • Sheet KAM    │  │ • Onboard CV   │  │ • Costo variab │  │ • Chat ejec POC│  │                │
  │                │  │                │  │                │  │                │  │                │
  │                │  │  ▼ 31 ━━━━━━━━━│  │  ▼ 15 ━━━━━━━━━│  │  ▼ 15 ━━━━━━━━━│  │  ▼ X ━━━━━━━━━ │
  │                │  │  Anal.LI       │  │  Fact #1       │  │  Fact #2       │  │  AC #2         │
  │                │  │  Anal.Cont #1  │  │                │  │  ▼ 30          │  │                │
  │                │  │                │  │                │  │  Ctrl. Gestión │  │                │
  └────────────────┘  └────────────────┘  └────────────────┘  └────────────────┘  └────────────────┘
```

---

## Slide 22 — KPIs / Resultados esperados

**Mensaje único:** El plan se mide con 4 dimensiones — Eficiencia, Costos, Calidad, Madurez del Cerebro.

### Cuadro de mando dic-2026

| Dimensión | KPI | Hoy | Meta dic-2026 | Cómo se mide |
|---|---|---|---|---|
| 💸 **Costos** | Headcount estructura administrativa | 47 personas | **41 personas (-6)** | Conteo nómina mensual |
| 💸 **Costos** | Costo personal anual administrativo | ~$1.247 MM | **~$1.156 MM (-$91 MM)** | Run-rate Total Haberes × 12 |
| 💸 **Costos** | Costo SaaS (Odoo + Yuju + Turso + Claude) | ~$16,9 MM/año | **~$8,1 MM/año (-$8,8 MM)** | Suma facturas SaaS |
| 💸 **Costos** | **Inversión IA mensual** | $0 | **~USD $250** | Factura Claude API + Turso Scaler |
| ⚡ **Eficiencia** | Reportes manuales semana (Andrés) | ~5 | **0** | Self-report quincenal |
| ⚡ **Eficiencia** | Tiempo Andrés en consolidación / sem | ~10 hrs | **↓ 80% (≤ 2 hrs)** | Time tracking |
| ⚡ **Eficiencia** | Lead time COMEX (PI → costeo) | ~3 días | **↓ 70% (≤ 1 día)** | Timestamp PI vs matriz costeo |
| ⚡ **Eficiencia** | Visibilidad EBIT (días atraso) | ~30 días | **< 1 día** | Fecha dato / fecha cierre |
| ✅ **Calidad** | Tasa error reportes | 75% | **< 5%** | Errores reportados / total |
| ✅ **Calidad** | Cuadre SII × Odoo × Drive (días) | 5-7 días | **< 1 día** | Tiempo cuadre diario |
| 🧠 **Madurez Cerebro** | Áreas con F3+ cerrado (de 7) | 3 | **6** | Slide 6 |
| 🧠 **Madurez Cerebro** | Agentes en producción (de 5 planificados) | 2 (COMEX, Compras) | **5** | Conteo agentes activos |
| 🎯 **ROI** | **ROI Cerebro Union X** | — | **>30x** | $101 MM ahorro ÷ $3 MM costo IA anual |

### Visual sugerido en PPT

Cuadro 4 columnas con un KPI grande por dimensión (Costos | Eficiencia | Calidad | Madurez) — formato "scorecard" con flechas ↑↓.

---

## Slide 23 — Riesgos y mitigaciones

| # | Riesgo | Prob. | Impacto | Mitigación | Owner |
|---|---|---|---|---|---|
| 🔴 1 | **Agente Cobranza no se arregla en junio** → caen 2 hitos (jul, oct) | Media | **Alto** | Fix con prioridad máxima en S1-S2 (1-30 jun). Si no se cierra al 30-jun, postergar salida Anal. Contable #2 a nov-2026. **Plan B:** Martín reactiva su Task Scheduler local temporalmente | Andrés + Víctor |
| 🟠 2 | **Adopción baja del equipo** (siguen con Excel local) → no se materializan eficiencias | Media | Alto | Onboarding formal Camila/Víctor/Martín · cerrar acceso a planillas paralelas · sponsor Gerencia | Andrés + Gerencia |
| 🟠 3 | **Comunicación interna mal manejada** (salidas filtradas o sin contexto) → conflicto laboral | Media | Alto | Plan comunicación con RR.HH. 30 días antes de cada salida · narrativa "automatización" no "despido" · finiquitos en regla | Gerencia + RR.HH. |
| 🟡 4 | **POC etiqueta+deadline no llega a prod a tiempo** → no se libera Facturadora #1 al 15-ago | Media | Medio | Sprint dedicado en junio · Yohana valida semana a semana · si no llega, postergar a 30-ago | Andrés + Yohana |
| 🟡 5 | **Costo Claude API se descontrola** | Baja | Medio | Prompt caching agresivo · límites de tokens por skill · auditoría mensual de uso. Hoy < USD $150/mes · alerta a USD $400 | Andrés |
| 🟡 6 | **Incidente tipo Cobranza se repite** (agente escribe en prod y borra data) | Baja | Alto | Regla nueva ya vigente: features que escriben en Drive/Odoo/DB requieren OK humano antes de mergear · ambientes test obligatorios | Andrés |
| 🟡 7 | **Andrés es single point of failure** (sabe cómo funciona todo) | Alta | Alto | Documentación viva (`docs/*_ESTADO_*.md` actualizado cada sesión) · onboarding técnico a un segundo · Claude como copiloto persistente | Andrés |
| 🟢 8 | **Dependencia Odoo** (si cae, todo cae) | Baja | Alto | Histórico parquet + snapshots semanales · apps siguen funcionando con histórico aunque Odoo caiga | — |

**Slide en PPT:** matriz 2×2 Probabilidad/Impacto con los 8 riesgos numerados ubicados en cada cuadrante.

---

## Slide 24 — Cierre / próximos pasos

### El pedido a Gerencia

| # | Decisión que necesitamos | Quién decide | Cuándo |
|---|---|---|---|
| 1 | **Aprobación del plan global** (Cerebro + 6 salidas + 3 eficiencias) | Gerencia General | Hoy |
| 2 | **Aprobación presupuesto IA** ~USD 250/mes (Claude + Turso) | Finanzas | Esta semana |
| 3 | **Validación calendario de salidas** con RR.HH. + Legal | Gerencia + RR.HH. | Esta semana |
| 4 | **Sponsor para adopción** (cerrar Excel paralelos) | Gerencia | Inmediato |
| 5 | **Fix Agente Cobranza es prioridad #1** — destrabar recursos | Andrés | 30-jun (deadline duro) |

### Próximos 30 días (junio 2026)

```
Semana 1   (1-7 jun)    Kick-off Sprint S1 + comunicación interna inicial
Semana 2   (8-14 jun)   Fix Agente Cobranza + auditoría SAC F1
Semana 3   (15-21 jun)  POC etiqueta+deadline en pre-prod + comisiones canal
Semana 4   (22-30 jun)  Validación de cierre S2 + go/no-go salidas julio
```

### Mensaje final del PPT

> **"El Cerebro UnionX ya existe a medias. Cerrar las piezas que faltan libera ~$33 MM este año, ~$100 MM run-rate, y nos pone en condiciones de escalar sin escalar planilla."**

---

## Slide 25 — Anexo técnico / arquitectura

> Slide opcional al final — solo si alguna gerencia pregunta "¿cómo está construido?".

### Arquitectura actual del Cerebro

```
                ┌──────────────────────────────────────────────────┐
                │                  CEREBRO UNION X                 │
                │                                                  │
                │   ┌──────────┐  ┌──────────┐  ┌──────────┐       │
                │   │   APP    │  │   APP    │  │   APP    │       │
                │   │  VENTAS  │  │ FINANZAS │  │   OPS    │       │
                │   └────┬─────┘  └────┬─────┘  └────┬─────┘       │
                │        └─────────────┼─────────────┘             │
                │                      │                           │
                │              ┌───────▼────────┐                  │
                │              │   TURSO DB +   │                  │
                │              │  PARQUET LOCAL │                  │
                │              └───────┬────────┘                  │
                │                      │                           │
                │       ┌──────────────┼──────────────┐            │
                │       │              │              │            │
                │  ┌────▼─────┐  ┌────▼─────┐  ┌─────▼────┐        │
                │  │  AGENTE  │  │  AGENTE  │  │  AGENTE  │        │
                │  │  COMEX   │  │  COMPRAS │  │ COBRANZA │        │
                │  │  Gmail   │  │  SII+Odoo│  │ (paused) │        │
                │  └────┬─────┘  └────┬─────┘  └─────┬────┘        │
                │       │             │              │             │
                │  ┌────▼─────────────▼──────────────▼────┐        │
                │  │       SKILLS CLAUDE (on-demand)      │        │
                │  │  comex · shipping · comisiones ·     │        │
                │  │  reporte gerencial · segmentación ·  │        │
                │  │  EERR clasificador                   │        │
                │  └──────────────────┬───────────────────┘        │
                └─────────────────────┼────────────────────────────┘
                                      │
                          ┌───────────▼──────────┐
                          │  FUENTES EXTERNAS    │
                          │  Odoo · SII · Gmail  │
                          │  Drive · Forwarder   │
                          └──────────────────────┘
```

### Stack técnico

| Capa | Tecnología | Plan / costo mensual |
|---|---|---|
| Inteligencia | Claude API (Opus 4.7) | ~USD $150-200 (variable) |
| Apps Web | Streamlit Community Cloud | $0 (Free) |
| DB cloud | Turso libSQL | $29 USD (Scaler, recomendado) |
| Orquestación | GitHub Actions | $0 (450/2000 min) |
| ERP fuente | Odoo (unionxb2b.odoo.com) | (costo existente, a reducir 35→15) |
| Email/Drive | Google Workspace API | (incluido en Workspace) |
| Automatización local | Windows Task Scheduler | $0 |

### Inversión IA total estimada

| Concepto | Mensual | Anual |
|---|---:|---:|
| Claude API | ~USD $200 | USD $2.400 |
| Turso Scaler | USD $29 | USD $348 |
| **Total inversión IA** | **~USD $229** | **~USD $2.748** = ~$2,7 MM CLP/año |

**ROI:** $101 MM ahorro anual / $2,7 MM costo = **>37x**

---

## 🎨 Guía para generar el PPT (E11)

> Esta sección está pensada para que **otra sesión de Claude (o vos mismo)** pueda armar el PPT sin contexto previo. Self-contained.

### Skill a usar
- `anthropic-skills:pptx` (ya disponible en el entorno)

### Parámetros del archivo
- **Aspect ratio:** 16:9
- **Total slides:** 25 (más portada y opcional cierre = 25-26 finales)
- **Idioma:** Español chileno
- **Tono:** Ejecutivo gerencial. No técnico. Frases cortas.
- **Output path sugerido:** `data/outputs/Plan_IA_Operaciones_Finanzas_2026-05-26.pptx`

### Identidad visual

| Elemento | Valor |
|---|---|
| Logo | `data/branding/unionx_logo.png` (azul UnionX) |
| Color primario | `#4A90E2` (azul UnionX, del logo) |
| Color texto oscuro | `#0F172A` |
| Color texto secundario | `#475569` |
| Color éxito / positivo | `#10B981` (verde) |
| Color alerta | `#DC2626` (rojo) |
| Color warning | `#EA580C` (naranja) |
| Color fondo | `#F8FAFC` (gris muy claro) |
| Tipografía sugerida | Inter / Calibri / Arial (sans-serif) |

### Estructura de los 25 slides

| # | Título | Tipo de slide |
|---|---|---|
| 1 | Portada | Título + autor + fecha + logo |
| 2 | Resumen ejecutivo | 2 columnas (Hoy vs Dic-2026) + KPIs cierre |
| 3 | Foto 360 / Status actual | Diagrama + tabla pieza-estado |
| 4 | El Cerebro Union X — definición | Diagrama del problema + las 5 fases |
| 5 | Caso paradigmático: RAW de Ventas | Tabla recorrido F1→F5 |
| 6 | Mirada Empresa | Matriz 7 áreas × 5 fases con % avance |
| 7 | Mirada Área: Ventas | Banda horizontal F1-F5 con próximos pasos |
| 8 | Mirada Área: Finanzas | Idem |
| 9 | Mirada Área: Operaciones | Idem |
| 10 | Mirada Área: Contabilidad (Compras + Cobranza) | Idem |
| 11 | Mirada Área: SAC / Logística Inversa | Idem |
| 12 | Mirada Área: Facturación | Idem |
| 13 | Mirada Área: EERR / Reportes | Idem |
| 14 | Bloque 2: Eficiencias overview | Cifras grandes $33 MM / $101 MM + tabla 4 categorías |
| 15 | Reducción de plantilla | Tabla 6 cargos + línea de tiempo Jul-Oct |
| 16 | Paso a paso reducción de personal | Tabla cargo / IA / prerrequisito / fecha |
| 17 | Otras eficiencias (Fulfillment + Odoo + Yuju) | 3 cards |
| 18 | Qué necesitamos para las otras eficiencias | Tabla con prerrequisitos |
| 19 | Carta Gantt — vista macro | Diagrama Gantt con tracks |
| 20 | Hitos críticos: entregables previos a cada salida | 5 sub-tablas (1 por hito) |
| 21 | Vista calendario | 5 cajas mes a mes |
| 22 | KPIs / Resultados esperados | Scorecard 4 dimensiones |
| 23 | Riesgos y mitigaciones | Matriz 2×2 + tabla 8 riesgos |
| 24 | Cierre / próximos pasos | 5 decisiones + sprint plan 30 días |
| 25 | Anexo técnico / arquitectura | Diagrama + stack + ROI |

### Reglas para el PPT

1. **Cada slide = 1 idea principal.** No saturar.
2. **Mensaje único en la parte superior** del slide (frase de 1-2 líneas).
3. **Visual + datos** abajo. Evitar slides solo de texto.
4. **Logo UnionX en footer** de cada slide (excepto portada que va grande).
5. **Numeración de slide en footer derecho.**
6. **Fecha "Plan IA · Mayo 2026"** en footer izquierdo.
7. **Notas del presentador** (speaker notes) opcionales con el detalle de cada slide.

### Comando para ejecutar (en sesión nueva de Claude)

```
Crea el PPT del Plan IA siguiendo el documento docs/PLAN_IA_PRESENTACION_2026.md.
- Usa la skill anthropic-skills:pptx
- Logo: data/branding/unionx_logo.png
- 25 slides según la estructura del MD
- Output: data/outputs/Plan_IA_Operaciones_Finanzas_2026-05-26.pptx
- Idioma: español chileno, tono ejecutivo gerencial
- Aspect ratio 16:9
- Paleta UnionX: primario #4A90E2
```

---

## 📋 Pendientes que quedan abiertos (no bloquean el PPT)

Estos son temas que se mencionaron pero no afectan la presentación de mañana. Para retomar en próximas sesiones:

1. **Eficiencia logística** — quedó FUERA del cálculo. Si más adelante hay datos firmes de renegociación, retomar como bonus.
2. **Costo variable evitable por pedido en bodega** — se usó allocated $2.887. Refinar cuando esté.
3. **Validar deadlines internos** del slide 20 con cada owner (Yohana, Víctor, Felipe).
4. **Camino crítico: Fix Agente Cobranza** — bloqueante para hito jul + oct. Empezar 1-jun.

### Resueltos en este ciclo
- ✅ Fecha Gabriela Pastran: 30/09/2026
- ✅ % Flex ML y Falabella: 50%
- ✅ Tarifa Odoo: lineal → $5,47 MM/año
- ✅ Logo en `data/branding/unionx_logo.png` + paleta extraída
- ✅ Anexo Técnico: incluido (slide 25)
- ✅ Logística sacada del cálculo (decisión Andrés)

---

_Última actualización: 25-may-2026 · Documento cerrado y listo para generar PPT._
_Para retomar en próxima sesión: leer este archivo de cabo a rabo + ejecutar el comando de E11._
