# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-06-11

### ✅ Estado actual — Vista Cobertura por Producto

#### Tab "🌳 Jerárquico" — OK
- Columnas por mes: **Stock Ini | Llegadas | Stk+Ped | Vta PPTO | Cobert.**
- Fórmula: `(Stock Ini + Llegadas) / avg(PPTO_M, M+1, M+2)`
- Colores: 🔴<1m | 🟡1-2m | 🟢2-4m | 🟣>4m
- Datos Jun 26: Lhotse 61.406u, Stk+Ped 62.206u, Cobert. 4.9m

#### Tab "💰 A Costo ($M)" — NUEVO ✅
- Misma jerarquía que Jerárquico (Marca → Cat. Padre → Cat. Hijo → SKU)
- Columna fija: **Stock Hoy ($M)** = stock_actual × Costo Unit / 1M
- Columnas por mes: **Stk Ini ($M) | Llegadas ($M) | Stk+Ped ($M) | Vta PPTO ($M) | Cobert.**
- **TOTAL GENERAL: $925,3M** (valor CIF internado de todo el inventario)
- Formato: `$1,2M` (CLP millones, 1 decimal)
- Costo Unit: columna `Costo Unit` de `data/stock/skus.parquet` (CIF internado)
- Cobertura = mismos colores que Jerárquico (ratio unidades, no cambia con costo)

#### Fuentes de datos
- Base SKUs: `planif_master_sku` (3,006 SKUs)
- Stock: `data/stock/skus.parquet` (Stock LIVE, actualizado cada 3h)
- Costo: columna `Costo Unit` del mismo `skus.parquet` (CIF internado por SKU)
- Venta proyectada: `planif_forecast_manual` (PPTO FCST, 677 SKUs Jun-Ene)
- Tránsito confirmado: `planif_transito_baseline` (hasta jun-25)
- Tránsito FCST: `planif_forecast_transito` (Jul-Nov 2026, 952 registros)

#### Fix pantuflas
- 23 SKUs Lhotse con formato nuevo (`LHPANIM{color}{XX}-{YY}`)

---

## 🔲 Pendientes Felipe (próxima sesión)

- [ ] **Sobrestock por Categoria Padre** (stand by — retomar después del dashboard a costo)
  - Tab nuevo "Sobrestock" dentro de Cobertura por Producto
  - Productos con cobertura > 4m, agrupados por Categoria Padre
  - Formato similar a hoja "Detalle Critico" del Excel analisis_planificacion_JUN26.xlsx
- [ ] PR #90 merge → para que Andrés tenga los cambios en app oficial
- [ ] Actualizar `ventas_historico.parquet` con datos de Mayo+Junio 2026
- [ ] Actualizar FCST desde Google Drive cuando Andrés suba el link

---

## 🔔 Para Andrés — mergear a main

**Branch**: `feat/fc-planif-onboarding`
**Último commit**: `7083b4d`

**Qué incluye:**
1. Tab "🌳 Jerárquico" — Stock Ini | Llegadas | Stk+Ped | Vta PPTO | Cobert. (fórmula avg 3m)
2. Tab "💰 A Costo ($M)" — misma vista pero en $M CLP a costo CIF
3. `planif_forecast_transito.parquet` — tránsito FCST Jul-Nov 2026
4. `cargar_costo_unit_sku()` en `_data_helpers.py`
5. Stock desde `data/stock/skus.parquet` (Stock LIVE cada 3h)
6. Fix pantuflas Lhotse (23 SKUs)

**Impacto**: CERO impacto en vistas existentes.

---

## 🧠 Contexto técnico importante

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| Último commit | `7083b4d` |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| App oficial | `https://unionx-planificacion.streamlit.app/` |
| Stock LIVE | `data/stock/skus.parquet` — columnas: SKU, Qty, Costo Unit, Valor, etc. |
| PPTO file | `data/planificacion/snapshots/planif_forecast_manual.parquet` |
| Tránsito file | `data/planificacion/snapshots/planif_transito_baseline.parquet` |
| Tránsito FCST | `data/planificacion/snapshots/planif_forecast_transito.parquet` |
| Master SKU | `data/planificacion/snapshots/planif_master_sku.parquet` |
| Excel análisis | `C:\Users\felip\Desktop\UNIONX\FORECAST FINAL SKU\Analisis Planificacion\analisis_planificacion_JUN26.xlsx` |

### 🔁 Cómo forzar redeploy en Streamlit Cloud

Streamlit Cloud NO re-clona para cambios Python (soft restart). Para full redeploy:
1. Cambiar versión real en `requirements.txt` (ej: `rich==13.9.3` ↔ `rich==13.9.4`)
2. Push
3. Abrir Manage app → `⋮` → "Reboot app" → confirmar

### 🐛 Bug AG-Grid resuelto: columnDefs duplicados
- **Síntoma**: columnas de meses no aparecían en tab A Costo
- **Causa**: AG-Grid no soporta el mismo `field` en dos lugares de `columnDefs` (como columna individual hidden + como hijo de un grupo)
- **Fix**: después de `gb.build()`, filtrar `columnDefs` para eliminar las definiciones individuales de columnas mensuales antes de agregar los grupos

```python
_pref_mensuales = ('csi_','ctr_','csp_','cvt_','si_','tr_','sp_','vt_','cb_')
_go2["columnDefs"] = [
    c for c in _go2.get("columnDefs", [])
    if not any(str(c.get("field","")).startswith(p) for p in _pref_mensuales)
]
```

### 📊 Excel de referencia: analisis_planificacion_JUN26.xlsx
Hojas: Cómo Vamos Junio | Comp. Marcas | Comp. Canales | VTA x Marca JUN 26 | CST x Marca | Crítico x Marca | Detalle Crítico | Tránsitos por Embarque | Nuevos en Tránsito | TD REPORTES UNID

- **TD REPORTES UNID** = fuente de datos base (Marca, Cat. Padre, Cat. Hijo, SKU, Stock HOY, Embarcado, Cobert. por mes)
- **CST x Marca** = valores en $M CLP con misma estructura que tab A Costo
- **Crítico x Marca** = referencia para tab Sobrestock futuro

---

*Actualizado automáticamente por Claude al cierre de sesión 2026-06-11.*
