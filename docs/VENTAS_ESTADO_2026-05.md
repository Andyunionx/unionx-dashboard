# 🛒 App Ventas UnionX — Estado al 25-may-2026

> **Para retomar en otra sesión de Claude.** Este documento es self-contained:
> alguien que lo lea entiende dónde estamos parados sin contexto previo.

---

## 🎯 Sumario ejecutivo

La app **Ventas** (`dashboard_ventas.py` → URL `https://unionx-dashboard-7ppjm2cem2zkfxwzkv3pzc.streamlit.app/`) es el dashboard principal de la operación comercial. Hoy lee de Turso (libSQL cloud) con **fallback a parquet local** (Turso plan free agotado hasta 1-jun). Se sincroniza con Odoo cada 4h vía Task Scheduler local + bypass directo Odoo → parquet. Expone:

1. **KPIs YoY** (ventas, unidades, margen, top SKUs, canales, etc.)
2. **Vistas COMEX, Ops, Forecast** compartidas con apps Operaciones y Planificación
3. **Descarga RAW Excel** (40 columnas, formato histórico)
4. **Login multi-usuario** con bcrypt (Andrés, Felipe, Nicolas, Gabriela, Martín)

**Cuadre mayo 2026 al 25-may:** $432,28 MM bruta / $363,26 MM neta / 14.722 filas (incluye Sodimac manual_externa $17,29 MM).

### 🗺️ Plan estratégico de arquitectura (acordado 25-may)

| Fase | Cuándo | Qué |
|---|---|---|
| ✅ Fase 1: Fallbacks | **25-may (hoy)** | 2 queries Turso críticas con fallback parquet. Tercero entra y todo funciona. |
| 🕐 Fase 2: Reset Turso | **1-jun** (automático) | Cuota se reinicia. Funcionalidades vuelven sin tocar nada. |
| 🎯 Fase 3: Migración a DuckDB | **post-Cyber ≥7-jun** | Migrar progresivamente con POC validada (branch `feature/duckdb-poc`). Side-by-side a cada paso. |

POC DuckDB ya validada: **5/5 casos idénticos** vs SQLite/Turso actual, **14x más rápido**. Ver branch `feature/duckdb-poc` y script `_compare_a_vs_b.py`.

---

## 📦 Sesiones recientes (19-may-2026)

### Sesión 1 — Cierre cabo Sodimac + NCs (mañana)
- Inyectada factura Sodimac **FAC 097825** como `manual_externa` ($17,29 MM bruta / $14,53 MM neta, canal UnionX B2B)
- 775 filas NCs mayo procesadas, $-24,93 MM bruta aplicadas como neteo + filas Devolución negativas
- Total cuadrado: $383,55 MM bruta / $322,31 MM neta

### Sesión 2 — Onboarding usuario Martín
- Agregado bloque `[auth.credentials.usernames.martin]` en [auth_config.yaml](../auth_config.yaml) y replicado en Streamlit Cloud Secrets
- Email: `martin@unionx.cl` · Password: `Martin2026!` (cambiar al primer login)
- **Pendiente**: invitación como viewer en Streamlit Cloud (Settings → Sharing) para apps privadas

### Sesión 3 — Auditoría RAW 40 columnas (esta sesión)
Findings + fixes aplicados (detalle más abajo).

### Sesión 4 — Bypass Turso + bugs reportados (22-may-2026)

**Bugs reportados por Andrés y resoluciones:**

| # | Bug | Estado | Resolución |
|---|---|---|---|
| 1 | Paris tienda duplicado ($23 MM extra) | ⚠️ Confirmado | S231708 (Cencosud, 14-may, sin factura) duplica a 458440 (Cencosud, 18-may, FAC 098229). **Andrés cancela en Odoo manual** |
| 2 | 6 pedidos sin canal/LN/KAM ($5,87 MM) | 🟡 Identificado | Partners no están en Maestra canales: IMPORTADORA ESTADO, MineGroup, Teknorpro, Shopify Lhotse, Melollevo. Pendiente cargar mapeo |
| 3 | Excel descarga columnas costo/margen | ⏸️ Esperando captura nueva | NO reproduce con RAW actual (post-fix #4). Pendiente: Andrés descarga uno fresco y manda captura si sigue |

**Bypass Turso permanente** (decidido como solución default):
- [extract_mes_actual_a_parquet.py](../extract_mes_actual_a_parquet.py) refactorizado: ahora soporta `--source odoo` (default) o `--source turso` (legacy)
- [.github/workflows/sync_mes_actual.yml](../.github/workflows/sync_mes_actual.yml) usa `--source odoo` por defecto cada hora
- Tiempo: ~4 min vs ~5 seg desde Turso (aceptable, sigue dentro del límite de 2000 min/mes de GitHub Actions)
- Aplica overlay costo desde `data/costo_override.csv` automáticamente
- Resultado primera corrida: 13,397 filas mayo, $405,28 MM bruta, mayo completo hasta 22-may ✅

### 🚨 Incidente 22-may-2026: Turso plan Starter agotado
**Síntoma:** Sidebar muestra `⚠️ Turso no cargó · KeyError: 'response'`. El dashboard funciona con histórico parquet (413K filas) pero **el mes actual no se actualiza**.

**Causa:** Turso plan Starter (gratuito) bloqueó TODAS las lecturas:
```
'Operation was blocked: SQL read operations are forbidden
 (reads are blocked, do you need to upgrade your plan?)'
```
Probable: alcanzaron los **1 mil millones de row reads/mes** del plan Starter (combinación de reloads del dashboard cada 15 min × 5 usuarios × N vistas/sesión).

**Estado:** Esperando reset mensual (1 de junio 2026). Mayo queda congelado al snapshot del **19-may-2026 14:35** (post-fixes auditoría).

**Mitigaciones disponibles si se vuelve urgente:**
1. **Upgrade plan Turso "Scaler"** (~USD $29/mes): 25 mil millones de reads + 500M writes + 24 GB storage.
2. **Crear extract Odoo→parquet directo** que no dependa de Turso (el cron `sync_mes_actual.yml` actualmente lee desde Turso, así que también está bloqueado). Modificar [extract_mes_actual_a_parquet.py](../extract_mes_actual_a_parquet.py) para extraer directo de Odoo.
3. **Migrar a otro proveedor** (Supabase / Neon / Cloudflare D1).

**Impacto en los fixes aplicados hoy:** Ninguno. Los UPDATEs de fix #3 (categorías) y fix #4 (costo_override) están persistidos en Turso. Cuando se desbloquee el reset, los datos están correctos.

### Sesión 5 — Maratón de fixes (25-may-2026)

#### Cambios funcionales
| # | Tema | Resultado |
|---|---|---|
| 1 | RAW Excel: quitar columna `Venta Neta` | Vuelve al formato 40 columnas histórico. Quien la necesite: `Venta bruta / 1.19` |
| 2 | Linkear Maestra Canales al Drive | `Maestra B2B.xlsx` (1QqIaF__kAMnE6bmrp6PfYC9p2HES9I8Y, owner Nicolas) sincronizada cada 4h. Pestañas: `Empresa` (148) + `CanalxKam` (124). Drive prioridad + local fallback (case-insensitive) |
| 3 | S231708 Cencosud cancelado en Odoo | Eliminado el pedido duplicado de $23,1 MM vía wizard `sale.order.cancel`. Parquet limpio. |
| 4 | Task Scheduler local cada 4h | `UnionX - Sync Mes Actual (bypass Turso)` registrada vía `schtasks.exe`. Corridas: 07:00, 11:00, 15:00, 19:00, 23:00. Wrapper [sync_mes_actual_local.ps1](../sync_mes_actual_local.ps1) hace extract Odoo → parquet → commit → push. |

#### Bugs encontrados y resueltos
| # | Bug | Causa raíz | Fix |
|---|---|---|---|
| A | Cron GH Actions `sync_mes_actual.yml` fallaba silencioso desde 21-may | `pip install pandas pyarrow libsql-client openpyxl` faltaba deps del backend para `--source odoo` | `pip install -r requirements.txt` + timeout 30 min |
| B | Sodimac perdido en bypass Odoo | Factura inyectada manual vive solo en Turso, extract Odoo no la trae | Catálogo `data/manual_externa_facturas.csv` + auto-inject post-extract |
| C | App mostraba $421 MM en vez de $432 MM | Fechas guardadas como `'2026-05-25 00:00:00'` (timestamp). Query `BETWEEN '2026-05-01' AND '2026-05-25'` excluía día 25 (string compare) | `_normalize_fecha_venta()` convierte a `'YYYY-MM-DD'` antes de cargar al SQLite local |
| D | "Forzar recarga DB" no limpiaba KPIs | `force_refresh_db_local()` solo limpiaba 3 caches | Ahora limpia las 9: `_cached_kpis_inner`, `cached_mensual`, `cached_diaria`, `_cached_semanal_inner`, `_cached_canales_inner`, `_cached_top_skus_inner` + las 3 originales |
| E | Streamlit Cloud conservaba SQLite local viejo | `@st.cache_resource` quedaba pegado | Bump del archivo temp `unionx_dashboard_local.db` → `v2` → `v3` para forzar rebuild |
| F | `cached_ventas_canal_30d` rompía con `KeyError: 'response'` | Query Turso sin try/except. Tira excepción cuando cuota agotada | Try/except + fallback que reconstruye desde parquet hist + mes_actual |
| G | `alertas_helper._query` rompía con `KeyError: 'response'` | Mismo patrón que F | Try/except + retorna `None`; los 3 callers ya manejan `None` correctamente |

#### Validación de causa raíz (commit `29e2c7f`)
Bug C era el más sutil. Probado localmente:
```
SIN fix (timestamp en SQLite): SUM bruta mayo = $421,008,906
CON fix (YYYY-MM-DD):          SUM bruta mayo = $432,277,673
```
Diferencia: $11,27 MM = 465 filas del 25-may que quedaban fuera del `BETWEEN`.

#### Patrón recurrente: "Oh no Error running app" tras push de parquet (26-may)
**Síntoma:** Después de pushear un parquet con muchos cambios (filas nuevas, cambio de schema), Streamlit Cloud carga el código nuevo pero el cache_resource de `get_local_db_path` queda pegado a la BD vieja en estado inconsistente → app tira "Oh no Error running app".

**Workaround actual:** Reboot manual desde share.streamlit.io → Manage app → Reboot. ~1 min y vuelve.

**Fix permanente:** post-Cyber Monday, migrar a DuckDB sobre parquet (Fase 3 del plan). DuckDB lee parquet directo sin SQLite intermedio → cache_resource no se pega.

**Veces que pasó:** mínimo 3 (24-may, 25-may, 26-may). Cada vez resuelto con reboot.

#### Stock LIVE + 7 workflows con bug sistémico (commit `4e4bc58` + `b8c3298`)
**Hallazgo:** El cron `sync_stock.yml` que actualiza Stock LIVE cada 3h **nunca funcionó** — carpeta `data/stock/` siempre vacía en repo. Causa: mismo patrón que `sync_mes_actual.yml` (instalaba `pip install pandas pyarrow requests` pero los scripts importan del backend `finanzas-unionx/backend/app/`).

Auditoría de los 13 workflows revelan **6 con riesgo + 1 a verificar**:
| Workflow | Era 🔴 → ahora ✅ |
|---|---|
| `sync_cmr.yml` | Ventas CMR semanal |
| `sync_comex.yml` | 3 scripts: validación Odoo, dimensiones SKU, capacidad forecast |
| `sync_contabilidad.yml` | Cobranza Odoo + libro compras |
| `sync_forecast.yml` | Stock histórico + Prophet (Prophet sigue instalándose aparte) |
| `sync_kpis_wms.yml` | precalcular_kpis_wms.py + volumen inventario |
| `sync_otif_drive.yml` | OTIF Drive |
| `sync_stock.yml` | Stock LIVE (Odoo → parquet) |
| `sync_kam_drive.yml` | KAM Drive (preventivo) |

**Fix sweeping:** todos pasaron a `pip install -r requirements.txt`. Solo `sync_forecast.yml` mantiene un `pip install prophet` extra (no está en requirements.txt por peso).

**Consecuencia esperada:** próximas 24h muchos parquets que estaban congelados van a volver a actualizarse automáticamente (stock, KPIs WMS, contabilidad, etc.). Algunos datos visuales en otras apps van a "saltar" al ponerse al día.

#### POC arquitectura B (branch `feature/duckdb-poc`)
Validación side-by-side con `_compare_a_vs_b.py`:
- **5/5 casos idénticos** (16 métricas × 5 escenarios = 80 comparaciones, todas match)
- DuckDB sobre parquet **14x más rápido** que Turso/SQLite (~0,5s vs ~7s)
- Bug encontrado en proceso: parquets hist y mes tienen orden de columnas distinto. Fix: `UNION ALL BY NAME`

---

## 🗂️ Arquitectura

```
                            ┌──────────────────────┐
                            │   Odoo (XML-RPC)     │
                            │   unionxb2b.odoo.com │
                            └──────────┬───────────┘
                                       │
                       ┌───────────────┼────────────────┐
                       │               │                │
                       ▼               ▼                ▼
              actualizar_diario   sync_mes_actual  actualizar_raw_historico
              (06:00 AM)          (cada hora)      (manual / catch-up)
                       │               │                │
                       └───────────────┴────────────────┘
                                       │
                                       ▼
                          ┌────────────────────────┐
                          │  Turso (libSQL cloud)  │
                          │  ventas (41 cols)      │
                          │  costo_override (NEW)  │
                          │  dim_productos         │
                          │  dim_canales           │
                          │  metadata_cargas       │
                          │  alertas               │
                          │  audit                 │
                          └────────────┬───────────┘
                                       │
                                       ▼
                       ┌──────────────────────────────────┐
                       │  Streamlit Cloud                 │
                       │  dashboard_ventas.py             │
                       │  → 17 vistas (Resumen, KPIs,     │
                       │     COMEX, Ops, Forecast, ...)   │
                       │  → Descarga RAW Excel            │
                       │  Auth bcrypt (5 usuarios)        │
                       └──────────────────────────────────┘
```

### Stack confirmado
| Capa | Tecnología | Plan/Costo |
|---|---|---|
| DB cloud | Turso libSQL | Starter (gratis) |
| App | Streamlit Community Cloud | Free |
| Sync | GitHub Actions workflows | 450/2000 min/mes |
| Auth | `streamlit_authenticator` + bcrypt | Local YAML / Secrets toml |

---

## 🔄 Pipeline de sincronización

### Workflows automáticos
| Cron | Workflow | Qué hace |
|---|---|---|
| `09:00 CL` diario | `actualizar_diario.py` (GA + Task Scheduler local) | Re-extrae día anterior, DEDUP automático |
| `14:00 CL` diario | mismo | Refresca día actual hasta ahora |
| `18:00 CL` diario | mismo | Cierre del día actual |
| Cada hora | `sync_mes_actual.yml` | Refresca mes corriente completo |
| Manual | `actualizar_raw_historico.py --periodo D1 D2` | Catch-up rangos custom |

### Comportamiento DEDUP (importante)
[actualizar_raw_historico.py:146-162](../actualizar_raw_historico.py#L146)
```sql
DELETE FROM ventas WHERE fecha_venta BETWEEN ? AND ?
AND (fuente IS NULL OR fuente != 'manual_externa')
```
Cada sync **borra y re-inserta** todo el período (excepto filas con `fuente='manual_externa'` como Sodimac FAC 097825).

### Overlay automático costo_override (agregado 19-may-2026)
[actualizar_raw_historico.py:183-209](../actualizar_raw_historico.py#L183)

Después del INSERT, se aplica overlay sobre filas con `costo_total=0`:
```sql
UPDATE ventas SET costo_unitario=?, costo_total=?*cantidad,
                  margen_front=venta_neta-(?*cantidad),
                  margen_final=venta_neta-(?*cantidad)
WHERE sku=? AND (costo_total IS NULL OR costo_total=0)
AND (fuente IS NULL OR fuente <> 'manual_externa')
```
Esto **persiste el fix de los 102 SKUs con `purchase_price` congelado a 0** en Odoo aún después de cada DELETE+INSERT.

---

## 📊 Modelo de datos

### Tabla `ventas` (41 columnas)
Columnas en orden de descarga RAW Excel:

| # | Columna RAW | Campo DB | Origen | Notas |
|---|---|---|---|---|
| 1 | Tipo Movimiento | `tipo_movimiento` | Generado | `Venta` o `Devolución` |
| 2 | Bodega | `bodega` | Odoo `warehouse_id.name` | |
| 3 | Documento | `documento` | Odoo `account.move.name` | FAC/BEL/NC |
| 4 | Fecha Documento | `fecha_documento` | Odoo `invoice_date` | |
| 5 | Pedido | `pedido` | Odoo `sale.order.name` | |
| 6 | Estado Pedido | `estado_pedido` | Odoo `sale.order.state` | |
| 7 | Tipo Despacho | `tipo_despacho` | (vacío) | No usado actualmente |
| 8 | SKU | `sku` | Odoo `product.default_code` | |
| 9 | Canal | `canal` | Resuelto via `_resolver_canal()` | B2B website → partner → channel_ref → channel |
| 10 | Fecha Venta | `fecha_venta` | Odoo `date_order` (date) | Clave de período |
| 11 | Hora Venta | `hora_venta` | Odoo `date_order` (time) | |
| 12 | Producto | `producto` | Odoo `product.name` | |
| 13-16 | Categorías macro/padre/hijo/comercial | `categoria_*` | **Matriz Productos** (lookup por SKU) | |
| 17 | Estado SKU | `estado_sku` | Matriz `In/out` | |
| 18 | Pack | `pack` | Matriz `Pack` | Si/No |
| 19 | Marca | `marca` | Matriz `Marca` | |
| 20 | Proveedor | `proveedor` | Matriz `Proveedor` | 16% vacío en mayo |
| 21 | Tipo Marca | `tipo_marca` | Matriz `Estado marca` | |
| 22 | Tipo Compra | `tipo_compra` | (vacío) | No usado |
| 23 | Tipo Negocio | `tipo_negocio` | **Maestra Canales** (lookup por canal) | Marketplace, Distribución, Páginas propias, Fidelización, Corporativo, Marketing |
| 24 | KAM | `kam` | Maestra Canales | |
| 25 | Estado Canal | `estado_canal` | (vacío) | No usado |
| 26-29 | Año/Mes/Semana/Día | `anio_venta`/`mes_venta`/`semana_venta`/`dia_semana` | Derivado de `date_order` | |
| 30 | Hora venta | `hora_venta_num` | Derivado | |
| 31 | Cantidad | `cantidad` | Odoo `product_uom_qty` | NEGATIVA en NCs |
| 32 | Venta bruta | `venta_bruta` | `price_total` (CON IVA) | NEGATIVA en NCs |
| 33 | Venta Neta | `venta_neta` | `price_subtotal` (SIN IVA) | NEGATIVA en NCs |
| 34 | Costo Unitario | `costo_unitario` | Odoo `sale.order.line.purchase_price` (congelado) | Si =0, overlay desde `costo_override` |
| 35 | Costo Total | `costo_total` | `costo_unitario × cantidad` | |
| 36 | Margen Front | `margen_front` | `venta_neta − costo_total` | Margen Directo |
| 37 | Comisión % | `comision_pct` | (=0, no hay datos) | ⚠️ Pendiente |
| 38 | Comisión | `comision` | (=0) | ⚠️ Pendiente |
| 39 | Logística | `logistica` | (=0) | ⚠️ Pendiente |
| 40 | Marketing | `marketing` | (=0) | ⚠️ Pendiente |
| 41 | Mg final | `margen_final` | `margen_front − comisión − logística − marketing` | = `margen_front` en 100% de filas (los 3 restos son 0) |

Columnas extra (no en RAW): `fuente`, `pedido_marketplace`, `client_order_ref`.

### Tabla `costo_override` (NUEVA, 19-may-2026)
```sql
CREATE TABLE costo_override (
    sku TEXT PRIMARY KEY,
    costo_unitario REAL NOT NULL,
    fuente TEXT,         -- 'odoo_standard_price'
    fecha_set TEXT,      -- ISO timestamp
    nota TEXT
)
```
Carga inicial: **102 SKUs** corregidos desde `product.product.standard_price` de Odoo.

---

## 🧮 Cálculos clave

### Margen Directo (lo que el RAW llama "Margen Front")
```
margen_front = venta_neta_post_NC − costo_total
```
Donde `venta_neta_post_NC` aplica el ratio de neteo si la factura tiene NCs parciales asociadas. El costo NO se ajusta por ese ratio (decisión consciente para mantener costo histórico).

### Margen Final
```
margen_final = margen_front − comisión − logística − marketing
```
**En la realidad actual:** `margen_final == margen_front` porque comisión/logística/marketing están en 0 (Odoo no tiene esos campos en `sale.order.line`). Ver pendiente #1.

### Notas de Crédito (NCs)
Implementación en [ventas_service.py:1222-1291](../finanzas-unionx/backend/app/services/ventas_service.py#L1222):
- Una fila `tipo_movimiento='Devolución'` por cada línea de NC con SKU real
- Costo congelado del `sale.order.line.purchase_price` original (cross-month resolvable)
- Todos los montos en **negativo**: cantidad, venta_bruta, venta_neta, costo_total
- Margen NC = `venta_neta_negativa − costo_negativo` = recupera margen contable

**Validado mayo 2026**: 783/783 NCs (100%) con SKU asignado + signo negativo correcto en TODOS los campos.

### IVA (ratio bruta/neta)
Validado **1,19 exacto** en todos los canales → IVA Chile 19% aplica bien.

### Canal — orden de resolución
Función `_resolver_canal()`:
1. Si `website_id` está seteado → es B2B web → usa nombre del website
2. Si `partner_name` está en `Maestra Canales` → usa ese canal
3. Si `channel_order_reference` no vacío → infiere por reference
4. Si `channel` (campo Odoo) no vacío → usa ese
5. Normalización via `CANAL_CANONICO` (ej. "sp digital" → "SP Digital")

### Exclusiones de canal
- **El Volcán**: SIEMPRE excluir ventas (consignación, carga manual). NCs sí entran (ej. mayo: N/C 039654 "CIERRE MES ABRIL 2026" -$2,28 MM).
- **Sawa abril 2026**: excluir (cargada manual). Mayo+ sí auto-sync.

### Inyección manual de facturas externas (Sodimac, etc.)
Catálogo en [data/manual_externa_facturas.csv](../data/manual_externa_facturas.csv). Cada vez que el bypass corre (`extract_mes_actual_a_parquet.py --source odoo`) lee este CSV y agrega las filas al parquet automáticamente. Hoy contiene FAC 097825 Sodimac. Cuando llegue reporte de consignación El Volcán mayo, agregarlo acá.

---

## 🔍 Auditoría RAW mayo 2026 (esta sesión)

### ✅ Lo que está BIEN
| Check | Resultado |
|---|---|
| NCs con SKU asignado | **783/783 (100%)** |
| NCs con signo NEGATIVO | **783/783 (100%)** |
| IVA bruta/neta = 1,19 | TODOS los canales |
| `costo_total = costo_unit × cantidad` | 11,497/11,499 (99,98%) |
| `margen_front = neta − costo` | 11,493/11,499 (99,95%) |
| Tipo Negocio + KAM completos | 99,7% |

### 🔧 Fixes aplicados HOY

**Fix #3: 14 SKUs nuevos a [Matriz productos.xlsx](../data/planillas/Matriz%20productos.xlsx)**
| SKU | Macro | Padre | Hijo |
|---|---|---|---|
| `SIMCUPAR-BK`, `SIMCUCER-24` | Home | Menaje de Cocina | Cuchillería |
| `SMBATLCGR`, `SMBATPMGR` | Home | Menaje de Cocina | Baterías de cocina |
| `Pack483`, `Pack484`, `Pack486` | Home | Menaje de Cocina | Pack Batería+Utensilios |
| `DNTASAINSCORP` | Home | Termos y Hidratación | Tazas Térmicas |
| `SIMJULZOPO-30` | Home | Vajilla | Juego de Loza |
| `LVMPADBML-BK`, `LVMPADOFS-BK` | Tecno | Periféricos | Gaming/Office |
| `Pack480-M`, `Pack482-L` | Sport | Vestuario Deportivo | Calcetines |
| `1659132834108` | Automotive | Seguridad Vehicular | Antifatiga GPS |

Backups: `data/planillas/Matriz productos.backup_20260519_*.xlsx` (×2)

**Fix #4: 102 SKUs corregidos en `costo_override`**
- Origen: `product.product.standard_price` de Odoo
- 329 filas mayo afectadas
- $4,14 MM margen real recuperado (antes contaba como 100% margen falso)
- Persistencia: tabla + overlay en extract

### ⚠️ Pendientes detectados (NO fixeados)

| # | Hallazgo | Impacto | Estado |
|---|---|---|---|
| 1 | `Mg final = Margen Front` (faltan comisiones/logística/marketing canal) | 🟠 ALTO — sobreestima margen ~15-18% en marketplaces | Pendiente "otro minuto" |
| 2 | 16 filas con canal vacío ($5,87 MM neta) | 🟢 BAJO — clientes B2B sin match en Maestra Canales | Pendiente |
| 3 | 6 boletas BEL anuladas con margen=0 pero costo>0 | 🟢 BAJO — pierde -$101K total | Pendiente |
| 4 | 4 SKUs sin costo en Odoo + 1 no existente | 🟢 BAJO — requiere acción manual en Odoo | Lista en `data/auditoria/fix4_costos_resultado.xlsx` |
| 5 | No existe columna "Línea de Negocio" explícita | 🟢 BAJO — lo más cercano es `Tipo Negocio` | Decidir si crear |

### Snapshot mayo 2026 — al 25-may (después de Sesión 5)
| Métrica | Valor |
|---|---|
| Filas totales | **14.722** (13.825 ventas + 897 NCs) |
| Bruta | **$432.277.673** (incluye Sodimac $17,29 MM manual_externa) |
| Neta | **$363.258.720** |
| Costo Total | ~$153.86 MM |
| Margen Directo | ~$209 MM |
| Margen % | **~57,5%** |
| Datos hasta | **2026-05-25** ✅ |
| Filas sin canal | **0** ✅ |

Top canales mayo (post-cancelación S231708):
| Canal | Bruta | Notas |
|---|---|---|
| Mercado Libre | $148,9 MM | — |
| Falabella | $75,3 MM | — |
| UnionX B2B | $28,8 MM | incluye Sodimac FAC 097825 |
| Paris tienda | $23,1 MM | sin S231708 duplicado cancelado |
| Simplit web | $22,9 MM | — |
| Dimarsa | $17,1 MM | — |
| Kitchen Center | $17,0 MM | — |

---

## 🗺️ Mapa de vistas

Entry point: [dashboard_ventas.py](../dashboard_ventas.py)

```
🎯 Resumen
  📸 Foto del mes (V/H)             → views/foto_mes.py
  📈 KPIs YoY                       → views/kpis_yoy.py
  🏆 Top SKUs                       → views/top_skus.py
  📊 Análisis Canal                 → views/analisis_canal.py
  🔔 Alertas                        → views/alertas_negocio.py

📦 Operaciones (compartidas con app Ops)
  🚢 COMEX                          → views/ops_comex.py
  📊 Stock LIVE                     → views/ops_stock_live.py
  📋 Pedidos B2B vs B2C             → views/ops_b2b_b2c.py
  💰 Costo Operativo                → views/ops_costo_operativo.py
  🔮 Forecast                       → views/ops_forecast.py

📊 Forecast
  📈 Forecast Ventas                → views/forecast_ventas.py

⬇️ Descarga
  ⬇️ Descargar RAW                  → views/ventas_descarga.py (41 cols Excel)

⚙️ Admin
  📋 Audit Log                      → views/audit.py
  🔧 Maintenance                    → views/maintenance.py
```

---

## 👥 Usuarios y acceso

### Streamlit Cloud Secrets (auth)
| Usuario | Email | Rol |
|---|---|---|
| `andres` | andres@unionx.cl | Andrés Browne (admin) |
| `felipe` | felipe@unionx.cl | Felipe |
| `nicolas` | nicolas@unionx.cl | Nicolas |
| `gabriela` | gabriela@grupoeter.cl | Gabriela Pastran |
| `martin` | martin@unionx.cl | Martín — agregado 19-may-2026 |

Configurados en:
- Local: [auth_config.yaml](../auth_config.yaml) (gitignored)
- Cloud: Streamlit Cloud → Settings → Secrets (sección `[auth.credentials.usernames.*]`)

### URL de la app
- Producción: `https://unionx-dashboard-7ppjm2cem2zkfxwzkv3pzc.streamlit.app/`
- Alias corto (configurado): `unionx-dashboard.streamlit.app`

### Onboarding nuevo usuario (3 pasos)
1. Generar hash bcrypt:
   ```powershell
   & "C:\Users\andre\AppData\Local\Programs\Python\Python312\python.exe" -c "import bcrypt; print(bcrypt.hashpw(b'PASSWORD', bcrypt.gensalt()).decode())"
   ```
2. Agregar bloque en [auth_config.yaml](../auth_config.yaml) Y en Streamlit Cloud Secrets
3. Invitar como viewer en Streamlit Cloud → Settings → Sharing (si la app es privada)

---

## 📂 Archivos clave

| Path | Descripción |
|---|---|
| [dashboard_ventas.py](../dashboard_ventas.py) | Entry point Streamlit |
| [actualizar_raw_historico.py](../actualizar_raw_historico.py) | Extract Odoo → Turso (con overlay) |
| [actualizar_diario.py](../actualizar_diario.py) | Wrapper diario (Task Scheduler / GA) |
| [inyectar_factura_manual.py](../inyectar_factura_manual.py) | Inyecta facturas externas (Sodimac, etc.) con `fuente='manual_externa'` |
| [db_client.py](../db_client.py) | Capa unificada SQLite local / Turso libSQL |
| [finanzas-unionx/backend/app/services/ventas_service.py](../finanzas-unionx/backend/app/services/ventas_service.py) | Lógica de extracción y armado del RAW |
| [finanzas-unionx/backend/app/services/maestra_service.py](../finanzas-unionx/backend/app/services/maestra_service.py) | `descargar_raw()` (41 cols Excel) |
| [data/planillas/Matriz productos.xlsx](../data/planillas/Matriz%20productos.xlsx) | Categorías por SKU (7.338 filas) |
| [data/planillas/Maestra canales.xlsx](../data/planillas/Maestra%20canales.xlsx) | Mapeo canal → Tipo Negocio + KAM |
| [auth_config.yaml](../auth_config.yaml) | Auth bcrypt local (gitignored) |
| `data/db/maestra_ventas.db` | SQLite local (backup + dev) |
| `data/auditoria/` | Exports de auditorías (xlsx) |

---

## 🚧 Próximos pasos

### 🎯 Plan estratégico (acordado 25-may)
**P1: Fallbacks** ✅ HECHO (commit `d13720d`/`659c6c2`)
- `cached_ventas_canal_30d` y `_query` de alertas_helper con try/except + fallback parquet
- App robusta para terceros aunque Turso esté bloqueado

**P2: Reset Turso** — 1-jun (automático, sin tocar nada)

**P3: Migración a DuckDB** — post-Cyber ≥7-jun
- Branch lista: `feature/duckdb-poc`
- Validación side-by-side con [_compare_a_vs_b.py](../_compare_a_vs_b.py)
- Migrar vistas una a una: KPIs YoY → Resúmenes canal → Tendencias → Top SKUs
- Una vez todo OK, eliminar capa Turso/SQLite del código
- Para writes (audit log, alertas): Cloudflare D1 gratis o JSON commiteado al repo

### Pendientes funcionales (cuando haya tiempo)
1. **Cargar comisiones por canal** para que `Mg final` sí reste comisiones marketplace
2. Cargar reporte mensual El Volcán a `manual_externa_facturas.csv` (cuando llegue)
3. Cargar costo manual en Odoo para los 4 SKUs sin `standard_price`
4. Fix BEL anuladas: detectar y poner `costo_total=0` para no perder $101K
5. Decidir si crear columna formal `linea_negocio` o quedarse con `tipo_negocio`

### Mejoras UX
6. Vista nueva: comparativo P&L Drive vs ventas Turso (cuadrar diferencias)
7. Alerta proactiva cuando un SKU nuevo aparezca sin estar en Matriz Productos

---

## 🔁 Cómo retomar este trabajo

1. Lee este archivo de cabo a rabo (5 min)
2. Verifica estado actual de la app:
   ```powershell
   python -c "import pandas as pd; df=pd.read_parquet('data/historico/ventas_mes_actual.parquet'); print(f'{len(df):,} filas, max fecha {df[chr(39)+chr(102)+chr(101)+chr(99)+chr(104)+chr(97)+chr(95)+chr(118)+chr(101)+chr(110)+chr(116)+chr(97)+chr(39)].max()}, bruta ${df[chr(39)+chr(118)+chr(101)+chr(110)+chr(116)+chr(97)+chr(95)+chr(98)+chr(114)+chr(117)+chr(116)+chr(97)+chr(39)].sum():,.0f}')"
   ```
3. Verifica que Task Scheduler local esté activo:
   ```powershell
   schtasks /Query /TN "UnionX - Sync Mes Actual (bypass Turso)" /FO LIST
   ```
4. Si vas a tocar el RAW o auditar: empieza por `data/auditoria/audit_raw_findings_2026-05.xlsx`
5. Si vas a migrar a DuckDB (post 7-jun): `git checkout feature/duckdb-poc` + corré `_compare_a_vs_b.py` antes de cada merge
6. Si la sync diaria falla: revisa logs en `data/db/sync_mes_actual_local.log`

---

**Última actualización:** 2026-05-25 ~17:00 CL
**Autores:** Andrés + Claude Code (sesiones 1-5)
