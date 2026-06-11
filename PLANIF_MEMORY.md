# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-06-12

### ✅ Tab "🌳 Jerárquico" — Completamente funcional
- Columnas mes actual: **Stock Hoy | Llegadas | Stk+Ped | Vta PPTO | Cobert.**
- Columnas meses futuros: **Stock Ini | Llegadas | Stk+Ped | Vta PPTO | Cobert.**
- Fórmula: `(Stock Ini + Llegadas) / avg(PPTO_M, M+1, M+2)`
- Colores: 🔴<1m | 🟡1-2m | 🟢2-4m | 🟣>4m
- Aggregación en filas de grupo ✅ (Bandú=1.270, Lhotse=61.406, etc.)
- TOTAL GENERAL pinneado: 121.165 stock | 40.531 vta | 127.944 stk+ped

### 🔶 Tab "💰 A Costo ($M)" — EN PROGRESO
- **Estructura**: columnas correctas ($M CLP) ✅
- **TOTAL GENERAL**: $925,3M Stock | $306,5M Vta/Mes ✅ 
- **Filas de marca (agrupadas)**: NO muestran valores — bug de aggregación AG-Grid
- **Filas expandidas (SKU)**: muestran valores correctamente ✅
- **Último commit**: `cafa706` (fix NameError + DataFrame mínimo)

#### Historia del bug de aggregación A Costo:
El problema es que las **filas grupales** (marca/categoría) no muestran valores agregados para `stock_cst_m` y `venta_prom_cst_m`, aunque el TOTAL GENERAL pinneado SÍ muestra los valores (calculados en Python).

**Lo que se investigó:**
- Los valores $M están en `_df_grid_cst` (DataFrame mínimo, solo columnas necesarias) ✓
- `aggFunc="sum"` y `enableValue=True` están configurados ✓
- AG-Grid CommunityEdition SÍ soporta aggregation en group rows ✓
- La razón exacta: desconocida — las celdas `[col-id="stock_cst_m"]` NO aparecen en las filas grupales (solo en el pinned row y header)

**Pendiente diagnosticar/solucionar:**
- Intentar con `groupDisplayType="singleColumn"` (sin "multipleColumns")
- Intentar pre-computar aggregados en Python y pasarlos como extra rows
- Intentar con `rowModelType="clientSide"` explícito
- Verificar si el issue es específico de streamlit-aggrid 1.0.5

---

## 🔲 Pendientes Felipe

- [ ] **Fix aggregación filas grupo en tab A Costo** ← bloqueante
- [ ] **Sobrestock por Categoria Padre** (stand by)
- [ ] PR #90 merge → app oficial (Andrés)
- [ ] Actualizar `ventas_historico.parquet` con Mayo+Junio 2026
- [ ] FCST desde Google Drive (cuando Andrés suba el link)

---

## 🔔 Para Andrés — mergear a main

**Branch**: `feat/fc-planif-onboarding`
**Último commit**: `cafa706`

**Incluye:**
1. Tab Jerárquico completo (Stock Hoy/Ini, Llegadas, Stk+Ped, Vta PPTO, Cobert.)
2. Tab A Costo ($M) — estructura lista, aggregación de grupos pendiente
3. `planif_forecast_transito.parquet` — tránsito FCST Jul-Nov 2026
4. Stock desde `data/stock/skus.parquet` (Stock LIVE cada 3h)
5. Fix pantuflas Lhotse (23 SKUs formato nuevo)

---

## 🧠 Contexto técnico

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| Último commit | `cafa706` |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| Stock LIVE | `data/stock/skus.parquet` — col: SKU, Qty, Costo Unit, Valor |
| PPTO file | `data/planificacion/snapshots/planif_forecast_manual.parquet` |
| Tránsito FCST | `data/planificacion/snapshots/planif_forecast_transito.parquet` |
| Master SKU | `data/planificacion/snapshots/planif_master_sku.parquet` |
| FCST Excel local | `C:\Users\felip\Desktop\UNIONX\FORECAST FINAL SKU\FORECAST FINAL SKU 26-27 V2.xlsx` |

### 🔁 Forzar full redeploy Streamlit Cloud
1. Cambiar versión real en `requirements.txt` (rich 13.9.3 ↔ 13.9.4)
2. Push
3. Manage app → ⋮ → Reboot app → Reboot

### 📌 Estructura A Costo (_df_grid_cst)
DataFrame mínimo con solo:
- Columnas id: `marca, categoria_padre, categoria_hijo, sku, produto, _is_total`
- Columnas fijas: `stock_cst_m, venta_prom_cst_m`
- Columnas mensuales (costo): `csi_YYYY-MM, ctr_, csp_, cvt_, cb_` × 6 meses
- Fórmula: `col_cst = col_unidades × Costo_Unit / 1_000_000`

---

*Actualizado: 2026-06-12*
