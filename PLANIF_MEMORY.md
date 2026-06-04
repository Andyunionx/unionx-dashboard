# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-06-04 (sesión final)

### ✅ Estado actual — Vista Cobertura por Producto COMPLETA

#### Tab "🌳 Jerárquico" — funcionalidad completa
- **Tabla dinámica AG-Grid** con desplegables Marca → Cat Padre → Cat Hijo → SKU
- **Proyección 6 meses integrada** (Jun–Nov 2026):
  - Columnas agrupadas por mes: Stock Ini | Venta | Tránsito | Cob. Meses
  - Venta = PPTO del FCST (planif_forecast_manual) — si no hay PPTO, muestra 0
  - Tránsito = planif_transito_baseline con regla día 5 (6+ = mes siguiente)
  - Cobertura con colores: 🔴<1m | 🟡1-2m | 🟢2-4m | 🟣>4m
- **TOTAL GENERAL** pinneado al fondo: sin ícono expandir, sin contadores
- **Números**: separador de miles, sin decimales (excepto Cob. = 1 decimal)
- **Totales aggregados** por nivel (sum stock/venta/tránsito, avg cob)
- **Filtro "Solo SKUs marca propia"** (default ON) → excluye "Sin clasificar"

#### Fuentes de datos (alineadas a Triada Proyectada)
- Base SKUs: `planif_master_sku` (3,006 SKUs)
- Stock: `planif_stock_baseline` (IDs correctos, 3,797 SKUs)
- Venta proyectada: `planif_forecast_manual` (PPTO FCST, 622 SKUs con Jun-Ago)
- Tránsito: `planif_transito_baseline` (confirmados, sin RFQ)
- Ventas 6sem: ventas_historico rolling 42d → tasa mensual

#### Números validados vs FCST
- Lhotse junio: **14,587** ✅ | Simplit junio: **17,453** ✅
- TOTAL GENERAL: **128,674** stock | **40,531** venta jun | **3.2** cob jun

---

## 🔲 Pendientes Felipe (próxima sesión)

- [ ] Verificar visualmente la tabla después del merge de Andrés
- [ ] Cuando Turso tenga datos → verificar que `cargar_forecast_manual_mensual()` lo tome
- [ ] Agregar tránsito proyectado FCST para Ago-Nov:
  → Correr `python extract_forecast_transito.py` con el Excel FCST
- [ ] Actualizar `ventas_historico.parquet` con datos de Mayo+Junio 2026

---

## 🔔 Para Andrés — mergear a main

**Branch**: `feat/fc-planif-onboarding`
**Último commit**: `24336cc` — formato miles sin decimales

**Qué incluye este branch:**
1. Vista completa "Cobertura por Producto" (`views/planning/triada_cobertura.py`)
2. Nuevo script `extract_forecast_transito.py` — para tránsito FCST Aug-Nov
3. Snapshots desde main: `planif_forecast_manual`, `planif_stock_live`, `planif_ventas_diarias_sku`
4. `requirements.txt` con `streamlit-aggrid==1.0.5`

**Impacto**: CERO impacto en vistas existentes. Solo agrega/mejora la vista Cobertura.

---

## 🧠 Contexto técnico importante

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| Último commit | `24336cc` — números con separador de miles |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| App oficial | `https://unionx-planificacion.streamlit.app/` |
| Reboot | JS: Manage app → expand terminal → ⋮ → Reboot app |
| PPTO file | `data/planificacion/snapshots/planif_forecast_manual.parquet` |
| Stock file | `data/planificacion/snapshots/planif_stock_baseline.parquet` |
| Tránsito | `data/planificacion/snapshots/planif_transito_baseline.parquet` |

---

*Actualizado automáticamente por Claude al cierre de sesión.*
