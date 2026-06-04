# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-06-03 (sesión larga)

### ✅ Lo que se hizo esta sesión

#### 1. Fixes críticos desplegados
- **Fix IndexError panel semáforo** — `enumerate(iterrows())` en loop cols_bar (`0415408`)
- **Fix KeyError `categoria_hijo`** — fallback post-try/except en `_preparar_datos` (`92987a9`)
- **Fix `ventas_4sem` → `ventas_6sem`** — ventana rolling de 28 → 42 días (`2408e8b`)

#### 2. Vista Cobertura — rediseño completo
- **KPI único**: eliminadas 2 de las 3 filas de KPI, queda solo "forecast promedio 3m"
- **Semáforo**: basado en `estado_fc3m`
- **Base de SKUs**: migrada de `forecast_skus_anchored` (110 SKUs) → `planif_master_sku` (3,006 SKUs)
- **Stock**: migrado a `planif_stock_baseline` (IDs correctos) + `planif_stock_live`
- **Arquitectura alineada a Triada Proyectada** — mismas fuentes de datos, misma jerarquía de fallback

#### 3. Vta/Mes = PPTO del FCST Excel
- **Fuente**: `planif_forecast_manual.parquet` (677 SKUs, meses 2026-01 a 2027-01)
- **Lógica**: Jun+Jul+Ago promedio por SKU → 622 SKUs con PPTO activo
- **Fallback**: promedio histórico Feb+Mar+Abr para SKUs sin PPTO
- **Bug corregido**: lectura directa del parquet (bypass `_is_turso_blocked` que no detectaba error de credenciales)
- **Impacto comprobado**: Levo histórico 2,614 → con PPTO 4,146 u/mes (+58%)

#### 4. Filtro "Solo SKUs marca propia"
- Reemplazó el filtro "Solo demanda o PPTO"
- Usa `tipo_marca = "Propia"` del `ventas_historico.parquet`
- 757 SKUs marca propia visibles (Levo, Lhotse, Simplit, Xroad, Bandú, etc.)
- Sin clasificar y marcas externas quedan ocultas con checkbox activo

#### 5. Vista Jerárquica AG-Grid con proyección mensual integrada
- **Tab "🌳 Jerárquico"**: tabla dinámica tipo Excel con desplegables
- **Jerarquía**: Marca → Categoría Padre → Categoría Hijo → SKU
- **Columnas de proyección 6 meses** integradas (Jun–Nov 2026):
  - Stock Inicio | Venta PPTO | Tránsito ETA | Cob.Meses (con colores)
- **Fórmula**: Stock Inicio(N) = Stock Fin(N-1) = Stock Ini(N-1) − Venta + Tránsito
- **Excepción mes actual**: Stock Inicio = Stock HOY del planif_stock_baseline
- **Colores cobertura**: 🔴 <1m | 🟡 1-2m | 🟢 2-4m | 🟣 >4m
- **Totales aggregados** en cada nivel (sum stock/venta/tránsito, avg cobertura)

#### 6. Datos traídos desde main branch de Andrés
- `data/planificacion/snapshots/planif_forecast_manual.parquet` — PPTO Jun-Ago 2026
- `data/planificacion/snapshots/planif_stock_live.parquet` — Stock live diario
- `data/planificacion/snapshots/planif_ventas_diarias_sku.parquet`
- `data/planificacion/snapshots/planif_stock_baseline.parquet` — ya estaba
- `data/planificacion/snapshots/planif_master_sku.parquet` — ya estaba

---

## 🔲 Pendientes Felipe (próxima sesión)

- [ ] **Verificar que el Reboot del último commit llegó** — commit `2ac7256` (proyección integrada en Jerárquico) puede necesitar otro reboot
- [ ] Confirmar que la proyección mensual se ve correctamente en el AG-Grid con los grupos de columnas por mes
- [ ] Revisar si los números de proyección hacen sentido (comparar con Triada Proyectada)
- [ ] Posibles mejoras al Jerárquico: poder mostrar/ocultar meses
- [ ] Corregir `extract_stock_historico.py` — guarda IDs Odoo en vez de códigos de referencia (bug pendiente largo plazo)
- [ ] Actualizar `ventas_historico.parquet` con datos de Mayo 2026 (cortado el 30/04)

---

## 🔔 Pendientes para Andrés

- [ ] **PR #65 o nuevo PR** — revisar y mergear a main cuando esté validado
- [ ] Arreglar billing Turso para que el pipeline automático funcione
- [ ] Subir Excel FCST actualizado cuando haya nueva versión (correr `extract_forecast_ppto_a_turso.py`)

---

## 🧠 Contexto técnico importante

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| Último commit | `2ac7256` — proyección mensual integrada en Jerárquico |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| App oficial | `https://unionx-planificacion.streamlit.app/` |
| Reboot method | JS sequence: Manage app → expand terminal → click ⋮ → Reboot app |
| Turso | Bloqueado por billing — app usa parquets como fallback |
| PPTO file | `data/planificacion/snapshots/planif_forecast_manual.parquet` — 677 SKUs |
| Stock file | `data/planificacion/snapshots/planif_stock_baseline.parquet` — 3,797 SKUs |

---

## 📋 Arquitectura de datos `_preparar_datos()`

```
Base SKUs    → cargar_planif_master()         (planif_master_sku, 3006 SKUs)
Stock        → cargar_planif_stock_live()      → cargar_planif_stock_baseline()
Ventas raw   → ventas_historico.parquet        (últimos 5 meses)
ventas_6sem  → rolling 42d → tasa mensual (/42*30)
venta_prom_3m → planif_forecast_manual (PPTO Jun+Jul+Ago) > histórico
tipo_marca   → ventas_historico.parquet       (para filtro marca propia)
Tránsito     → cargar_planif_transito_live()  → cargar_transito()
```

---

## 📋 Lógica de proyección mensual (tab Jerárquico)

```
Para cada SKU, por mes M (6 meses forward):
  Stock Ini M = stock_actual (mes actual) ó Stock Fin M-1 (meses futuros)
  Venta M     = planif_forecast_manual[sku][mes] ó venta_prom_3m (fallback)
  Tránsito M  = comex/transito con fecha_eta_bodega en mes M
  Cob M       = Stock Ini M / Venta M
  Stock Fin M = max(0, Stock Ini M − Venta M + Tránsito M)
```

---

## 🐛 Bugs corregidos esta sesión

| Bug | Fix |
|-----|-----|
| IndexError semáforo | `enumerate(iterrows())` |
| KeyError `categoria_hijo` | fallback post-try/except |
| SKUs incorrectos (110 vs 700+) | cambió base de forecast a planif_master_sku |
| Stock = 0 en todos | migró a planif_stock_baseline (IDs correctos) |
| PPTO no se aplicaba | bypass `_is_turso_blocked` — lectura directa parquet |
| SKUs faltantes FCST | filtro cambiado: demanda OR PPTO → marca propia |

---

*Actualizado automáticamente por Claude al cierre de sesión.*
