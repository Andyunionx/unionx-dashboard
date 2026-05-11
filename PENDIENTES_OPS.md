# 📋 Pendientes — App Operaciones

Lista viva de cosas a hacer en el dashboard de Operaciones.
Se revisa cada vez que el user pregunta "qué pendientes hay" o "status del proyecto".

Última actualización: 2026-05-11

---

## 🔥 PRIORIDAD ALTA (próxima sesión)

### 1. 💰 Análisis de costo operativo por canal de venta
**Pedido por:** Andrés (2026-05-11)
**Bloqueado por:** carga de costos operacionales (esta semana)

**Concepto:** Cruzar la productividad ya medida (pedidos/líneas/uds) con el
costo operativo real para entender qué canal es más eficiente.

**Cuando lleguen los costos:**
1. Cargar costos operacionales mensuales (sueldos bodega + arriendo + insumos
   + servicios) por categoría → JSON manual en data/ops_manuales o Sheet
2. Distribuir el costo por canal usando como driver:
   - Pedidos por canal × peso operativo (B2B suele ser más caro/pedido por
     volumen y consolidación; B2C tiene picking más simple pero más despachos)
   - O simplemente: costo / pedidos totales del canal
3. Crear vista nueva en Tab Picking → "Costo por canal":
   - Costo total operativo / canal
   - Costo / pedido / canal
   - Costo / línea / canal
   - Costo / unidad / canal
   - Margen contribución bruta / canal vs costo operativo
   - **Output:** ranking de canales por eficiencia operativa real
4. Cruzar con margen bruto del Análisis de Contribución (ya existe en eerr-finanzas)
   → margen NETO por canal después de operativo

**Helper a crear:** `views/_ops_costo_canal.py`
**Datos requeridos:**
- Costos operacionales mensuales (bloqueado, los carga Andrés)
- Pedidos/líneas/uds por canal (ya extraído en `kpi_ventas_por_canal` y stock.picking + sale.order)

---

### 2. 📊 OTIF desde Google Drive (no Odoo)
**Pedido por:** Andrés (2026-05-11)
**Bloqueado por:** Service Account access al Sheet
**URL:** https://docs.google.com/spreadsheets/d/1OSvJ0sO4H4VgU9Ac0GW5mpCjdCJL2N61dcYZpkxFbCo

**Acción:**
1. Andrés comparte el Sheet con `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com`
2. Crear `views/_ops_otif_drive.py` que lee el Sheet con gspread
3. Reemplazar lógica del Tab OTIF actual (que usa stock.picking) por la del Sheet
4. Mantener la del Sheet como verdad oficial para OTIF (data manual con
   fechas reales prometidas vs entregadas)

---

## 🟡 MEDIO

### 3. 🔧 Pick Accuracy real desde devoluciones
**Estado:** ✅ Implementado parcial. Andrés debe verificar si las devoluciones
están bien capturadas en Odoo (filtro "origin like S%").

**Verificación:** mirar en Tab Picking sección "Tasa de devoluciones" — si
muestra 0.017% (1 cada 5826 despachos), validar:
- ¿Realmente hay tan pocas devoluciones?
- ¿O las devoluciones se procesan fuera de Odoo (en Yuju, manual, etc.)?

Si no se capturan bien, agregar campo "razón devolución" desde helpdesk.

### 4. 📐 m³ por slot bodega (capacidad real)
**Estado:** Pausado — depende de carga de dimensiones de caja master en Odoo
o desde PI/PL del agente COMEX.

**Cuando esté disponible:** reactivar la sub-tab "Disponibilidad m³" del Stock LIVE
y "Capacidad para próximos embarques" (forecasting de recepción).

**Avance 2026-05-11:** ✅ Implementado `extract_comex_dimensiones.py` que cruza
los SKUs en tránsito con `weight` y `volume` desde `product.template` Odoo y
calcula m³/pallets/containers por PI. Resultado actual: 168/206 SKUs match Odoo
(82%), cobertura volumen confiable 67%, 8 SKUs con volumen anómalo (>1m³/unid
— probablemente cargados en cm³). Nueva tab "📐 Volumen / Pallets" en COMEX.

**Pendiente para mejorar precisión:**
1. Andrés cargar la maestra de unidades por caja master en Odoo (`product.packaging`)
   o subir como JSON manual → permite calcular cajas master por PI
2. Corregir los 8 SKUs con volumen anómalo en Odoo (lista visible en la tab)
3. Pedir a operaciones que carguen `weight` y `volume` para los 33% de SKUs
   sin dimensiones (incidencia visible en la tab nueva)

### 5. 🔄 Refactor v2: extract_wms_raw → parquets + cálculos en memoria
**Estado:** Código ya creado (`extract_wms_raw.py` + `views/_ops_wms_raw_loader.py`)
pero NO activo. La app sigue usando snapshot.json precalculado.

**Cuando hacerlo:** después de validar que el approach actual funciona estable.
Beneficio: 1 sola corrida diaria que extrae raw, los KPIs se calculan en runtime
desde parquet (super rápido, sin cuelgues).

---

## ➡️ MIGRACIONES PENDIENTES

### Mover "Análisis pedidos" a app Ventas
**Eliminado del Ops** (commit 724f8fe) por ser información comercial, no operacional.
El código está en commits anteriores si se quiere recuperar:
- Mix por canal (B2C/B2B)
- Mix por categoría / marca
- Top SKUs vendidos
- Detalle pedidos con filtros + Excel export
**Acción futura:** crear Tab "Análisis pedidos" en `dashboard_ventas.py` con misma lógica.

---

## 🟢 BAJA / NICE TO HAVE

### 6. Costo operativo total view (vista placeholder existente)
Tab `🚢 Fulfillment > Costo Operativo Total` está creada pero vacía. Llenar
cuando lleguen costos operacionales (mismo trigger que pendiente #1).

### 7. Migrar app Ventas a Turso
Si la app Ventas tiene datos manuales que se pierden en redeploys, aplicar el
mismo patrón Turso que ya funciona en Operaciones.

### 8. OCT estricto (último picking vs primer picking)
Actualmente OCT mide hasta el PRIMER picking despachado. Si querés métrica
estricta "todo el pedido entregado", cambiar a `max(date_done)` por SO.

---

## ✅ COMPLETADOS RECIENTES (2026-05-09 a 2026-05-11)

- COMEX: nueva tab "📐 Volumen / Pallets" → cruza SKUs en tránsito con
  peso/volumen Odoo, estima m³/pallets/containers por PI, detecta SKUs con
  volumen mal cargado en Odoo (`extract_comex_dimensiones.py`)
- Tab Datos manuales → Equipo bodega: config base singleton + auto-cálculo horas
- Cycle counts y Merma desde Odoo automático (no manual)
- Plan auditoría semanal con priorización por rotación
- Forecast operacional desde Prophet ventas (no histórico interno ingenuo)
- Snapshot pre-calculado 1x/día (GH Action `sync_kpis_wms.yml`)
- Bug fix crítico: campo `quantity_done` → `quantity` (Odoo 17+)
- Sesión persistente 8h con cookie HMAC
- Productividad por mes calendario / semana / día con períodos naturales
- 3 dimensiones combinadas (pedidos/líneas/uds) × por persona/día/hora
- Pick Accuracy real desde devoluciones (complementa la métrica de sistema)
- Eliminados todos los botones "Cargar" — datos siempre visibles del snapshot
