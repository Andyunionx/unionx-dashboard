# 🛒 App Ventas UnionX — Estado al 19-may-2026

> **Para retomar en otra sesión de Claude.** Este documento es self-contained:
> alguien que lo lea entiende dónde estamos parados sin contexto previo.

---

## 🎯 Sumario ejecutivo

La app **Ventas** (`dashboard_ventas.py` → URL `https://unionx-dashboard-7ppjm2cem2zkfxwzkv3pzc.streamlit.app/`) es el dashboard principal de la operación comercial. Lee de Turso (libSQL cloud), se sincroniza con Odoo 3 veces al día y expone:

1. **KPIs YoY** (ventas, unidades, margen, top SKUs, canales, etc.)
2. **Vistas COMEX, Ops, Forecast** compartidas con apps Operaciones y Planificación
3. **Descarga RAW Excel** (41 columnas) usado por finanzas/contabilidad
4. **Login multi-usuario** con bcrypt (Andrés, Felipe, Nicolas, Gabriela, Martín)

El último cuadre mensual (mayo 2026) cierra en **$384,44 MM bruta / $323,06 MM neta / 56,0% margen** después de los fixes de auditoría aplicados hoy.

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
- **El Volcán**: SIEMPRE excluir (ventas consignación, carga manual)
- **Sawa abril 2026**: excluir (cargada manual). Mayo+ sí auto-sync.

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

### Snapshot mayo 2026 POST-fix
| Métrica | Valor |
|---|---|
| Filas totales | 11,509 (10,726 ventas + 783 NCs) |
| Bruta | $384.442.535 |
| Neta | $323.061.071 |
| Costo Total | $142.163.289 |
| Margen Directo | $180.999.202 |
| Margen % | **56,0%** |

Top 5 canales:
| Canal | Bruta | Neta | Margen | MG% |
|---|---|---|---|---|
| Mercado Libre | $113,4 MM | $95,3 MM | $58,1 MM | 61,0% |
| Falabella | $56,9 MM | $47,8 MM | $29,4 MM | 61,5% |
| Paris tienda | $46,2 MM | $38,8 MM | $18,5 MM | 47,6% |
| UnionX B2B | $27,1 MM | $22,8 MM | $16,3 MM | 71,5% |
| Simplit web | $18,5 MM | $15,5 MM | $9,0 MM | 57,8% |

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

## 🚧 Próximos pasos sugeridos

### Crítico (cuando se aborde Mg final completo)
1. **Cargar comisiones por canal** en una tabla `comisiones_canal (canal, comision_pct, vigente_desde, vigente_hasta)`
2. Modificar `_construir_dataset_raw()` para aplicar comisión durante extract
3. Idem logística y marketing (puede venir de Drive/Sheet)

### Mantenimiento (cuando haya tiempo)
4. Revisar 16 clientes B2B con canal vacío → agregar a `Maestra canales`
5. Fix BEL anuladas: detectar y poner `costo_total=0` para no perder $101K
6. Cargar costo manual en Odoo para los 4 SKUs sin `standard_price`
7. Decidir si crear columna formal `linea_negocio` o quedarse con `tipo_negocio`

### Mejoras UX
8. Vista nueva: comparativo P&L Drive vs ventas Turso (cuadrar diferencias)
9. Alerta proactiva cuando un SKU nuevo aparezca sin estar en Matriz Productos

---

## 🔁 Cómo retomar este trabajo

1. Lee este archivo de cabo a rabo (5 min)
2. Verifica estado actual de la app:
   ```powershell
   $env:PYTHONIOENCODING="utf-8"
   python -c "from db_client import get_connection; c=get_connection(None); print(c.execute(\"SELECT COUNT(*) FROM ventas WHERE fecha_venta BETWEEN '2026-05-01' AND '2026-05-31'\").fetchall()[0])"
   ```
3. Si vas a tocar el RAW o auditar: empieza por `data/auditoria/audit_raw_findings_2026-05.xlsx`
4. Si vas a agregar usuario: sigue sección "Onboarding nuevo usuario"
5. Si la sync diaria falla: revisa logs en `data/db/sincronizacion_diaria.log` o GitHub Actions

---

**Última actualización:** 2026-05-19 14:35 CL
**Autor:** Andrés + Claude Code (sesión auditoría RAW)
