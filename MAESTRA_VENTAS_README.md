# Maestra de Ventas — Sistema Automático de Sincronización

**Última actualización:** 15-04-2026  
**Estado:** ✅ OPERATIVO

## Resumen Ejecutivo

Se ha implementado un sistema completo y automático para:

1. **Cargar histórico** (2024-2026) en base de datos SQLite
2. **Extraer datos automáticamente** desde Odoo cada 5 minutos
3. **Generar KPIs** por canal y línea de negocio
4. **Deduplicar** automáticamente (sin registros duplicados)
5. **Respetar límites de Odoo** (máx 7 días por extracción)

---

## Base de Datos SQLite

### Ubicación
- **Ruta principal:** `data/db/maestra_ventas.db` (204 MB)
- **Ruta local (sync):** `~/Desktop/finanzas-unionx-app/maestra_ventas.db`

### Estado actual
- **Total de filas:** 387,406 registros
- **Rango de datos:** 2024-12-02 hasta 2026-04-15
- **Columnas:** 40 (RAW Ventas Y formato exacto)
- **Tablas:** 
  - `ventas` (principal, 40 cols + fecha_carga)
  - `dim_productos` (SKU, producto, categorías, marca, proveedor, etc.)
  - `dim_canales` (canal, tipo_negocio, KAM, estado)
  - `dim_bodegas`, `dim_proveedores`, `dim_marcas`
  - `metadata_cargas` (log de cargas, fuente, fechas, tipo)

### Índices (optimizados para queries)
- `fecha_venta`, `sku`, `canal`, `marca`, `tipo_movimiento`, `bodega`, `documento`, `pedido`, etc.

---

## Automatización Programada

### Script principal: `sincronizar_ventas.py`

**Lógica de extracción (semanal inteligente):**
```
Si DB está vacía:
  Extraer Apr 01-07 (primera semana)
  
Si estamos atrasados (max_fecha < hoy - 1 día):
  Extraer siguientes 7 días (máx)
  
Si estamos al día (max_fecha >= ayer):
  Refrescar semana actual (por correcciones/NC nuevas)
```

**Deduplicación idempotente:**
- DELETE rows WHERE `fecha_venta BETWEEN [desde] AND [hasta]`
- INSERT new rows
- Resultado: cero duplicados aunque se ejecute múltiples veces

**Alarm de prevención:**
- Si atraso > 30 días → log con nivel ALERTA

**Logging:**
- Archivo: `data/db/sincronizacion.log`
- Contiene: fecha, período, filas, status, errores

### Ejecución automática

**Archivo batch:** `sincronizar_ventas.bat`
- Ejecuta el script Python cada 5 minutos via Task Scheduler
- Output: append a `data/db/sincronizacion.log`

**Configuración Task Scheduler:** `registrar_tarea_ventas.ps1`

```powershell
# Ejecutar como Administrador:
powershell -ExecutionPolicy Bypass -File registrar_tarea_ventas.ps1
```

Crea la tarea: `UnionX-IA\Sincronizar Ventas Odoo`
- Trigger: cada 5 minutos, indefinidamente
- Ejecuta: `sincronizar_ventas.bat`
- Condición: solo si hay red disponible

### Verificar Task Scheduler

```powershell
Get-ScheduledTask -TaskPath "\UnionX-IA" -TaskName "Sincronizar Ventas Odoo"
```

---

## Generadores de KPIs

### SQL Queries: `data/db/consultas_kpis.sql`

9 consultas SQL pre-escritas para análisis:
1. Resumen general
2. Por canal
3. Por línea de negocio
4. Matriz canal x negocio
5. Por categoría macro
6. Top 20 SKUs
7. Por bodega
8. Tendencia diaria
9. Últimos 7 días vs semana previa

### Reportes Python: `generar_reporte_kpis.py`

**Uso:**
```bash
# Imprimir reporte en consola (últimos 15 días)
python generar_reporte_kpis.py

# Rango custom
python generar_reporte_kpis.py --inicio 2026-04-01 --fin 2026-04-15

# Exportar a Excel
python generar_reporte_kpis.py --excel --output Mi_Reporte.xlsx
```

**Salida:**
- Resumen general (líneas, unidades, venta neta, margen directo, margen final, %)
- Venta por canal
- Venta por línea de negocio
- Matriz canal x negocio (top 15)
- Top 15 productos

---

## Flujo de datos

```
Odoo (XML-RPC)
  ├─ sale.order (pedidos)
  ├─ sale.order.line (líneas de venta)
  ├─ product.product (productos)
  ├─ account.move type=out_invoice (facturas)
  └─ account.move type=out_refund (notas de crédito)
  ↓
OdooClient (conexión robusta, 10 reintentos, batching adaptivo)
  ↓
VentasService.extract_to_raw_format()
  ├─ Extrae 40 columnas RAW por línea de venta
  ├─ Busca facturas asociadas a cada orden
  ├─ Detecta notas de crédito (NC) que revierten facturas
  └─ Crea LÍNEAS SEPARADAS para NC (no neteadas, signo negativo)
  ↓
sincronizar_ventas.py
  ├─ Detecta período siguiente (7 días máx)
  ├─ DELETE + INSERT (deduplicación)
  ├─ Actualiza dimensiones (SKUs, canales nuevos)
  └─ Registra en metadata_cargas
  ↓
Base de datos SQLite (maestra_ventas.db)
  ├─ Líneas de venta (Tipo Movimiento = 'Venta')
  ├─ Líneas de NC (Tipo Movimiento = 'Nota de Crédito') con Venta bruta negativa
  ├─ 40 columnas RAW
  ├─ Índices optimizados
  └─ Sincronizado a Google Drive cada 5 min
```

## Tratamiento de Notas de Crédito (NC)

Las NC se registran como **líneas separadas independientes** para auditoría y trazabilidad:

| Concepto | Venta Original | Nota de Crédito |
|----------|---|---|
| Tipo Movimiento | "Venta" | "Nota de Crédito" |
| Documento | BOL-001234 | NOT-000567 |
| Venta bruta | $100,000 | **-$20,000** (NEGATIVO) |
| Costo Total | $50,000 | **0** (sin costo) |
| Margen Front | $50,000 | **-$20,000** (NEGATIVO) |
| Mg final | $45,000 | **-$20,000** (NEGATIVO) |

**Ventajas:**
- ✅ Auditoría clara: cada NC es visible como línea separada
- ✅ Trazabilidad: se ve exactamente qué se devolvió y cuándo
- ✅ Análisis: si necesitas restar NC, `SUM(Venta bruta)` lo hace automáticamente
- ✅ Reversibilidad: sin NC, el total de ventas es el real sin neteado previo

---

## Próximos pasos (Roadmap futuro)

### Punto 6: Comisiones
- Usuario cargará planilla de condiciones (categoría × canal → % comisión)
- Aplicar UPDATE masivo a tabla `ventas` con nuevos cálculos
- Script: `aplicar_comisiones.py` (no implementado aún)

### Punto 7: Dashboard interactivo
- Flask backend ya existe en `finanzas-unionx/backend/`
- Agregar blueprint `api/raw_ventas.py` con endpoints:
  - `GET /api/ventas/raw` — Query raw data con filtros
  - `GET /api/ventas/export-raw` — Descargar Excel 40 cols
  - `GET /api/ventas/kpis` — KPIs resumen
  - `GET /api/ventas/por-canal` — Agregado por canal
  - `GET /api/ventas/por-linea-negocio` — Agregado por línea

---

## Troubleshooting

### "DB no existe"
```bash
python data/db/crear_maestra_ventas.py
```

### "Script no avanza, se queda stuck"
1. Revisar `data/db/sincronizacion.log` para ver dónde se queda
2. Si es en "Extrayendo facturas": Odoo puede estar lento. Esperar 5 min.
3. Si es un error repeté: revisar mensaje de error en el log

### "Duplicados en la DB"
- No debe pasar. La lógica DELETE + INSERT debería prevenir duplicados.
- Si ocurre, ejecutar:
  ```sql
  DELETE FROM ventas WHERE rowid NOT IN (
    SELECT MIN(rowid) FROM ventas GROUP BY documento, sku, fecha_venta
  );
  ```

### "Task Scheduler no ejecuta"
1. Verificar permisos: ejecutar `registrar_tarea_ventas.ps1` como Admin
2. Ver que `sincronizar_ventas.bat` existe y es ejecutable
3. Revisar Event Viewer → Windows Logs → Application para errores

---

## KPIs Actuales (01-15 Abr 2026)

```
Venta NETA:      $272,717,830
Margen Directo:  $127,764,441
Margen Final:    $121,600,717
% Margen Final:  44.6%
Líneas:          11,090
Unidades:        12,791
```

---

## Archivos clave

| Archivo | Propósito |
|---------|-----------|
| `sincronizar_ventas.py` | Orquestador principal (inteligencia de fechas + deduplicación) |
| `sincronizar_ventas.bat` | Batch para Task Scheduler |
| `registrar_tarea_ventas.ps1` | Registra tarea automática |
| `generar_reporte_kpis.py` | Genera reportes ejecutivos |
| `data/db/consultas_kpis.sql` | Queries SQL pre-escritas |
| `data/db/actualizar_maestra_ventas.py` | Carga histórico desde Excel |
| `data/db/maestra_ventas.db` | Base de datos SQLite |
| `data/db/sincronizacion.log` | Log de ejecuciones automáticas |

---

## Contacto y soporte

- **Gerente Finanzas:** Andrés (andres@unionx.cl)
- **Sistema:** Maestra de Ventas RAW (40 cols)
- **Periodo histórico:** 2024-12-02 hasta 2026-04-15
- **Actualización:** Cada 5 minutos automáticamente
