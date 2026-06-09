# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-06-09

### ✅ Estado actual — Vista Cobertura por Producto COMPLETA

#### Tab "🌳 Jerárquico" — funcionalidad completa (desplegado en prod)
- **Tabla dinámica AG-Grid** con desplegables Marca → Cat Padre → Cat Hijo → SKU
- **Proyección 6 meses integrada** (Jun–Nov 2026):
  - Columnas agrupadas por mes: **Stock Ini | Llegadas | Stk+Ped | Vta PPTO | Cobert.**
  - Stock Ini = stock actual al inicio de cada mes
  - Llegadas = tránsito COMEX confirmado (ETA con regla día 5)
  - Stk+Ped = Stock Ini + Llegadas
  - Vta PPTO = forecast del FCST (planif_forecast_manual)
  - Cobertura = (Stock Ini + Llegadas) / avg(PPTO_M, PPTO_M+1, PPTO_M+2)
  - Colores cobertura: 🔴<1m | 🟡1-2m | 🟢2-4m | 🟣>4m
- **TOTAL GENERAL** pinneado al fondo: sin ícono expandir
- **Filtro "Solo SKUs marca propia"** (default ON) → excluye "Sin clasificar"

#### Datos Jun 26 validados
| Marca | Stock Hoy | Llegadas | Stk+Ped | Vta PPTO |
|-------|-----------|----------|---------|----------|
| Lhotse | 61.406 | 800 | 62.206 | 14.587 |
| Simplit | 31.260 | 3.860 | 35.120 | 17.453 |
| **TOTAL** | **121.165** | **6.779** | **127.944** | **40.531** |

#### Fuentes de datos
- Base SKUs: `planif_master_sku` (3,006 SKUs)
- **Stock: `data/stock/skus.parquet`** (Stock LIVE, actualizado cada 3h via sync_stock.yml)
- Venta proyectada: `planif_forecast_manual` (PPTO FCST, 677 SKUs Jun-Ene)
- Tránsito: `planif_transito_baseline` (confirmados hasta jun-25)
- Tránsito futuro: `planif_forecast_transito` (FCST Aug-Nov, si existe)

#### Fix pantuflas aplicado
- 23 SKUs Lhotse pantuflas actualizados de `LHPANIM{color}-{XX}/{YY}` → `LHPANIM{color}{XX}-{YY}`
- Commit: `9263ec2`

---

## 🔲 Pendientes Felipe (próxima sesión)

- [ ] Verificar cobertura de Lhotse con los nuevos números (debería ser ~4.3-4.6m)
- [ ] Agregar columna **"Compra"** desde el FCST Excel → script `extract_forecast_transito.py` ya existe, hay que agregar extracción de columnas `Compra PPTO MES`
- [ ] Actualizar `ventas_historico.parquet` con datos de Mayo+Junio 2026
- [ ] PR #90 merge → para que Andrés tenga los cambios en la app oficial

---

## 🔔 Para Andrés — mergear a main

**Branch**: `feat/fc-planif-onboarding`
**Último commit**: `d270888` — Cobertura avg 3m + Stk+Ped + Stock LIVE

**Qué incluye este branch:**
1. Vista "Cobertura por Producto" completamente renovada
   - Fórmula correcta: `(Stk+Ped) / avg(PPTO_M, M+1, M+2)`
   - Columnas: Stock Ini | Llegadas | Stk+Ped | Vta PPTO | Cobert.
2. Stock desde `data/stock/skus.parquet` (Stock LIVE cada 3h)
3. Fix pantuflas Lhotse (23 SKUs formato nuevo)
4. `requirements.txt` actualizado

**Impacto**: CERO impacto en vistas existentes.

---

## 🧠 Contexto técnico importante

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| Último commit | `d270888` |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| App oficial | `https://unionx-planificacion.streamlit.app/` |
| Reboot full | Abrir panel ⋮ → "Reboot app" → Confirmar (funciona desde la login page con el panel expandido) |
| **IMPORTANTE** | Para forzar full redeploy (re-clonar repo): cambiar versión en requirements.txt + commit que toque triada_cobertura.py al mismo tiempo → luego Reboot manual desde el ⋮ |
| PPTO file | `data/planificacion/snapshots/planif_forecast_manual.parquet` |
| Stock file | `data/stock/skus.parquet` (Stock LIVE) |
| Tránsito | `data/planificacion/snapshots/planif_transito_baseline.parquet` |
| Master SKU | `data/planificacion/snapshots/planif_master_sku.parquet` |

### 🔁 Cómo forzar redeploy en Streamlit Cloud (lección aprendida)

Streamlit Cloud **NO** re-clona el repo automáticamente para cambios de Python (solo soft restart).
Para forzar un full redeploy que tome los últimos commits:
1. Hacer un commit que cambie `requirements.txt` (versión real, no solo comentario) **Y** también el archivo `.py` que necesita actualizarse
2. Push
3. En el app: abrir panel "Manage app" → click `⋮` → "Reboot app" → Confirmar
4. Streamlit hará un full redeploy con re-clone del repo

---

*Actualizado automáticamente por Claude al cierre de sesión 2026-06-09.*
