# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-07-01

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

### ✅ Tab "📉 Sobrestock" — NUEVO (commit afa26a5)
- Jerarquía: Marca → Cat. Padre → Cat. Hijo → SKU (misma estructura AG-Grid)
- Filtro: `cobertura_fc3m (stock/venta_prom_3m) > 4 meses`
- Ordenado por Capital Inmovilizado DESC (mayor problema primero)
- Columnas:
  - **Cob. ACT (m)** — cobertura actual en meses
  - **Meses Exceso** — cobertura - 4
  - **Stock CST ($)** — stock × Costo Unit (CLP full, no $M)
  - **Vta CST Prom/Mes ($)** — venta_prom_3m × Costo Unit
  - **Stk Óptimo ($)** — 4 × Vta CST Prom/Mes
  - **Capital Inmov. ($)** — Stock CST - Stk Óptimo
  - **Llegadas (u)** — transit meses 1-5 (excluye mes actual)
- Caption: Total capital inmovilizado + conteo SKUs
- Referencia Excel: hoja "Sobrestock x SKU Padre" en analisis_planificacion_JUN26.xlsx

---

## 🔲 Pendientes Felipe

- [x] **Sobrestock por Categoria Padre** ← COMPLETADO 2026-07-01
- [x] **Página Análisis Planificación (7 tabs)** ← COMPLETADO 2026-07-01
- [ ] PR merge → app oficial (Andrés) — branch: `feat/fc-planif-onboarding`
- [ ] Actualizar `ventas_historico.parquet` con Mayo+Junio 2026 (tabs comerciales necesitan datos completos)
- [ ] FCST desde Google Drive (cuando Andrés suba el link)

---

## ✅ Página Análisis Planificación (commit pendiente de push)

**Archivo**: `views/planning/analisis_planificacion.py`  
**Registrado en**: `dashboard_planificacion.py` → "🎯 Planificación" → url_path=`pln-analisis`

**7 tabs implementados**:
1. 📊 Cómo Vamos — Real vs Meta del mes actual (Marca + Canal)
2. 📈 Comp. Marcas — YTD META|REAL|VAR% (Venta Neta + Contribución Frontal)
3. 📈 Comp. Canales — YTD META|REAL|VAR%
4. 💰 CST x Marca — Proyección mensual a costo ($M) por Marca (6 meses)
5. 🔴 Detalle Crítico — SKUs con cobertura fc3m < 1m + llegadas próximas
6. 🚢 Tránsitos — Embarques agrupados por PI con USD/ETA
7. 🆕 Nuevos en Tránsito — SKUs con stock=0 con llegadas próximas

**Fuentes de datos**:
- PPTO: `data/planificacion/snapshots/planif_ppto_canal.parquet` + `planif_ppto_marca.parquet`
- Script extracción: `extract_ppto_snapshot.py` (leer desde desktop PPTO 2026 Excel)
- Ventas real: `data/historico/ventas_historico.parquet` (canal via `tipo_negocio`)
- Supply chain: `_preparar_datos()` de triada_cobertura + transit pivot

**Nota importante**: ventas_historico.parquet tiene datos INCOMPLETOS para 2026 (solo ~15% del total real). Los tabs Cómo Vamos/Comp.Marcas/Canales mostrarán cifras reales bajas hasta actualizar el parquet.

---

## 🔔 Para Andrés — mergear a main

**Branch**: `feat/fc-planif-onboarding`
**Último commit**: pendiente push (ver abajo)

**Incluye:**
1. Tab Jerárquico completo ✅
2. Tab A Costo ($M) completo ✅ (aggregación + orden correcto)
3. Tab Sobrestock ✅ (capital inmovilizado por SKU > 4m cobertura)
4. **Página Análisis Planificación (7 tabs)** ✅ — NUEVO
5. `planif_forecast_transito.parquet` — tránsito FCST Jul-Nov 2026
6. Stock desde `data/stock/skus.parquet` (Stock LIVE cada 3h)
6. Fix pantuflas Lhotse (23 SKUs)

---

## 🧠 Contexto técnico

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| Último commit | `afa26a5` |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| Stock LIVE | `data/stock/skus.parquet` — cols: SKU, Qty, Costo Unit, Valor |
| PPTO file | `data/planificacion/snapshots/planif_forecast_manual.parquet` |
| Tránsito FCST | `data/planificacion/snapshots/planif_forecast_transito.parquet` |
| Master SKU | `data/planificacion/snapshots/planif_master_sku.parquet` |
| FCST Excel local | `C:\Users\felip\Desktop\UNIONX\FORECAST FINAL SKU\FORECAST FINAL SKU 26-27 V2.xlsx` |
| Ref. Excel Sobrestock | `C:\Users\felip\Desktop\UNIONX\FORECAST FINAL SKU\Analisis Planificacion\analisis_planificacion_JUN26.xlsx` → hoja "Sobrestock x SKU Padre" |

### 🔁 Forzar full redeploy Streamlit Cloud
1. Cambiar versión en `requirements.txt` (rich 13.9.3 ↔ 13.9.4)
2. Push
3. Manage app → ⋮ → Reboot app → Reboot

### 📌 Estructura A Costo (_df_grid_cst)
DataFrame mínimo con solo columnas necesarias (igual que df_jer en Jerárquico):
- `marca, categoria_padre, categoria_hijo, sku, produto, _is_total`
- `stock_cst_m, venta_prom_cst_m`
- `csi_{ms}, ctr_{ms}, csp_{ms}, cvt_{ms}, cb_{ms}` × 6 meses
- Fórmula: `col_cst = col_unidades × Costo_Unit / 1_000_000`
- Grid: `_go2["autoGroupColumnDef"] = {"pinned": "left", ...}` — CRÍTICO para aggregación
- **OJO**: columna producto en df_jer se llama `"produto"` (no `"producto"`)

### 📌 Estructura Sobrestock (_df_grid_sob)
- Fuente: `df_jer` (copia post-proyección)
- Filtro: `stock_actual / venta_prom_3m > 4`
- Costo Unit: `cargar_costo_unit_sku()` (igual que A Costo)
- Llegadas = sum(`tr_{ms}` para meses 1-5, excluye mes actual)
- CLP full (no $M): `'$'+Math.round(x).toLocaleString('es-CL')`
- Grid: mismo patrón `autoGroupColumnDef: {pinned: "left"}` + `groupDisplayType: "multipleColumns"`

### 📊 Valores A Costo confirmados (Jun 26)
| Marca | Stock Hoy ($M) | Vta/Mes ($M) |
|-------|---------------|-------------|
| Bandú | $15,0M | $11,1M |
| Dynamo | $10,3M | $5,9M |
| Lhotse | $322,6M | $83,1M |
| Simplit | $279,8M | $117,0M |
| **TOTAL** | **$925,3M** | **$306,5M** |

---

*Actualizado: 2026-07-01*
