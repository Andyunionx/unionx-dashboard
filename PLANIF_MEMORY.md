# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-06-04 (sesión 3 — larga)

### ✅ Lo que se hizo esta sesión

#### 1. Vista Cobertura — rediseño completo con AG-Grid jerárquico
- **Tab "🌳 Jerárquico"**: tabla dinámica tipo Excel con desplegables
  - Jerarquía: Marca → Categoría Padre → Categoría Hijo → SKU
  - **Proyección 6 meses integrada** (Jun–Nov 2026):
    - Stock Inicio | Venta PPTO | Tránsito ETA | Cob.Meses (colores)
  - **Fila TOTAL GENERAL** al fondo (negrita, fondo gris), sin ícono expandir
  - Totales aggregados en cada nivel (sum stock/venta/tránsito, avg cob.)

#### 2. Correcciones de datos
- **Filtro "Solo SKUs marca propia"**: cambiado de `tipo_marca` a `marca` del master
  - Fix: productos nuevos sin historial de ventas (Lhotse/Simplit) ahora incluidos
  - Lhotse: +49 SKUs, +925u PPTO jun | Simplit: +17 SKUs, +520u PPTO jun
- **Tránsito confirmado**: cambiado a `planif_transito_baseline` (excluye TRANSITO_RFQ)
  - Jun: 15,424u → Jul: 30,566u (con regla día 1-5)
- **Regla día 5**: ETA 1-5 → mismo mes | ETA 6+ → mes siguiente

#### 3. Fuentes de datos alineadas a Triada Proyectada
- Base SKUs: `planif_master_sku` (3,006 SKUs, igual que Triada)
- Stock: `planif_stock_baseline` (IDs correctos, 3,797 SKUs)
- Venta proyectada: `planif_forecast_manual` (PPTO Jun-Ago, 622 SKUs) > histórico
- Tránsito: `planif_transito_baseline` (confirmados ETA hasta jun)
- Ventas 6sem: rolling 42 días → tasa mensual (/42×30)

#### 4. Filtro y visualización
- "Solo SKUs marca propia" (default: ON) → excluye "Sin clasificar"
- KPI único: forecast promedio 3m (PPTO Jun+Jul+Ago)
- 658 SKUs marca propia visibles
- Números validados vs FCST: Lhotse 14,587 ✅ Simplit 17,453 ✅

---

## 🔲 Pendientes Felipe (próxima sesión)

- [ ] **Verificar visualmente** que TOTAL GENERAL no muestre ícono `>` ni `(1)`
  → commit `a8f5121` debería haberlo arreglado con `getRowClass + custom_css`
- [ ] Agregar tránsito proyectado del FCST para Ago-Nov:
  → Correr `python extract_forecast_transito.py` cuando Andrés tenga el Excel FCST
- [ ] Cuando Turso tenga los datos del PPTO actualizado, verificar que `cargar_forecast_manual_mensual()` lo tome automático
- [ ] Revisar si hay que agregar `Bandú` como marca propia al filtro

---

## 🔔 Pendientes para Andrés

- [ ] **PR a main** — toda la funcionalidad de Cobertura está en `feat/fc-planif-onboarding`
- [ ] Actualizar `ventas_historico.parquet` con datos de Mayo+Junio 2026
- [ ] Poner `FORECAST FINAL SKU 26-27 V2.xlsx` en `data/planificacion/` para extraer tránsito Ago-Nov
- [ ] Arreglar billing Turso para que el pipeline automático funcione

---

## 🧠 Contexto técnico importante

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| Último commit | `a8f5121` — ocultar botón expand en TOTAL GENERAL |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| App oficial | `https://unionx-planificacion.streamlit.app/` |
| Reboot method | JS sequence: Manage app → expand terminal → click ⋮ → Reboot app |
| PPTO file | `data/planificacion/snapshots/planif_forecast_manual.parquet` — 677 SKUs |
| Stock file | `data/planificacion/snapshots/planif_stock_baseline.parquet` — 3,797 SKUs |
| Tránsito file | `data/planificacion/snapshots/planif_transito_baseline.parquet` — confirmado hasta jun |

---

## 📋 Arquitectura de datos (alineada a Triada Proyectada)

```
Base SKUs    → cargar_planif_master()         (planif_master_sku, 3006 SKUs)
Stock        → cargar_planif_stock_live()      → cargar_planif_stock_baseline()
Ventas       → ventas_historico.parquet        (últimos 5 meses, rolling 42d → tasa mensual)
Vta/Mes      → planif_forecast_manual (PPTO) > histórico (SIN Prophet)
Tránsito     → planif_transito_baseline        (filtra TRANSITO_RFQ)
```

## 📋 Lógica de proyección mensual

```
Para cada mes M (6 meses forward, Jun-Nov 2026):
  Stock Inicio M = stock_actual (mes actual) | Stock Fin M-1 (meses futuros)
  Venta M = planif_forecast_manual[sku][mes] | 0 si no tiene PPTO
  Tránsito M = planif_transito_baseline con regla día 5
  Cob M = Stock Ini M / Venta M
  Stock Fin M = max(0, Stock Ini - Venta + Tránsito)
```

---

*Actualizado automáticamente por Claude al cierre de sesión.*
