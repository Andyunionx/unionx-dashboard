# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-06-12 (tarde)

### ✅ Tab "🌳 Jerárquico" — Completamente funcional
- Mes actual: **Stock Hoy** | Llegadas | Stk+Ped | Vta PPTO | Cobert.
- Meses futuros: **Stock Ini** | Llegadas | Stk+Ped | Vta PPTO | Cobert.
- Aggregación en filas de marca ✅

### ✅ Tab "💰 A Costo ($M)" — FUNCIONANDO COMPLETO
- Orden columnas: **Marca/Categoría | Cat. Padre | Cat. Hijo | SKU | Producto | Stock Hoy ($M) | Vta/Mes ($M) | [grupos mes]**
- Aggregación en filas de marca ✅:
  - Bandú: $15,0M | Dynamo: $10,3M | Lhotse: $322,6M | Simplit: $279,8M
  - **TOTAL GENERAL: $925,3M** stock | $306,5M vta/mes
- Mes actual: **Stock Hoy ($M)** | Llegadas ($M) | Stk+Ped ($M) | Vta PPTO ($M) | Cobert.
- Meses futuros: **Stk Ini ($M)** | Llegadas ($M) | Stk+Ped ($M) | Vta PPTO ($M) | Cobert.
- Colores cobertura: 🔴🟡🟢🟣 (mismos que Jerárquico)

#### Clave del fix de aggregación:
`_go2["autoGroupColumnDef"] = {"pinned": "left", ...}` → fuerza las columnas jerárquicas a la izquierda Y activa la aggregación en filas de grupo. Commit: `c26fcf1`

---

## 🔲 Pendientes Felipe

- [ ] **Sobrestock por Categoria Padre** (estaba en stand by)
  - Tab nuevo dentro de Cobertura por Producto
  - Productos con cobertura > 4m, agrupados por Cat. Padre
  - Referencia: hoja "Detalle Critico" del Excel analisis_planificacion_JUN26.xlsx
- [ ] PR merge → app oficial (Andrés)
- [ ] Actualizar `ventas_historico.parquet` con Mayo+Junio 2026
- [ ] FCST desde Google Drive (cuando Andrés suba el link)

---

## 🔔 Para Andrés — mergear a main

**Branch**: `feat/fc-planif-onboarding`
**Último commit**: `f3aba16`

**Incluye:**
1. Tab Jerárquico completo ✅
2. Tab A Costo ($M) completo ✅ (aggregación + orden correcto)
3. `planif_forecast_transito.parquet` — tránsito FCST Jul-Nov 2026
4. Stock desde `data/stock/skus.parquet` (Stock LIVE cada 3h)
5. Fix pantuflas Lhotse (23 SKUs)

---

## 🧠 Contexto técnico

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| Último commit | `f3aba16` |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| Stock LIVE | `data/stock/skus.parquet` — cols: SKU, Qty, Costo Unit, Valor |
| PPTO file | `data/planificacion/snapshots/planif_forecast_manual.parquet` |
| Tránsito FCST | `data/planificacion/snapshots/planif_forecast_transito.parquet` |
| Master SKU | `data/planificacion/snapshots/planif_master_sku.parquet` |
| FCST Excel local | `C:\Users\felip\Desktop\UNIONX\FORECAST FINAL SKU\FORECAST FINAL SKU 26-27 V2.xlsx` |

### 🔁 Forzar full redeploy Streamlit Cloud
1. Cambiar versión en `requirements.txt` (rich 13.9.3 ↔ 13.9.4)
2. Push
3. Manage app → ⋮ → Reboot app → Reboot

### 📌 Estructura A Costo (_df_grid_cst)
DataFrame mínimo con solo columnas necesarias (igual que df_jer en Jerárquico):
- `marca, categoria_padre, categoria_hijo, sku, producto, _is_total`
- `stock_cst_m, venta_prom_cst_m`
- `csi_{ms}, ctr_{ms}, csp_{ms}, cvt_{ms}, cb_{ms}` × 6 meses
- Fórmula: `col_cst = col_unidades × Costo_Unit / 1_000_000`
- Grid: `_go2["autoGroupColumnDef"] = {"pinned": "left", ...}` — CRÍTICO para aggregación

### 📊 Valores A Costo confirmados (Jun 26)
| Marca | Stock Hoy ($M) | Vta/Mes ($M) |
|-------|---------------|-------------|
| Bandú | $15,0M | $11,1M |
| Dynamo | $10,3M | $5,9M |
| Lhotse | $322,6M | $83,1M |
| Simplit | $279,8M | $117,0M |
| **TOTAL** | **$925,3M** | **$306,5M** |

---

*Actualizado: 2026-06-12*
