# Cambios Implementados: Notas de Crédito como Líneas Separadas

**Fecha:** 2026-04-15  
**Estado:** ✅ COMPLETADO Y VALIDADO

## Problema Original

Las NC (notas de crédito) estaban siendo "neteadas" (descontadas) de la venta original:
- Factura BOL-001234: $100,000
- NC NOT-000567: -$20,000
- **Resultado en reporte:** Una sola línea con Venta bruta = $80,000

**Problema:** Falta auditoría y trazabilidad de dónde vinieron esos -$20,000.

## Solución Implementada

Las NC ahora aparecen como **líneas separadas independientes** con signo negativo:

| Línea | Tipo | Documento | Venta bruta | Margen |
|-------|------|-----------|-------------|--------|
| 1 | Venta | BOL-001234 | $100,000 | $50,000 |
| 2 | **Nota de Crédito** | **NOT-000567** | **-$20,000** | **-$20,000** |

## Cambios en el Código

### 1. `_extraer_facturas_y_nc()` - Línea 365
**Antes:** Retornaba `(facturas, totales_netos)`  
**Ahora:** Retorna `(facturas, totales_netos, ncs)`
- Las NC ahora se retornan explícitamente para procesarlas como líneas separadas

### 2. `extract_to_raw_format()` - Línea 69, 83
**Cambio:** Captura las NC y las pasa a `_construir_dataset_raw()`
```python
facturas, totales_netos, ncs = self._extraer_facturas_y_nc(...)
df_raw = self._construir_dataset_raw(..., ncs, ...)  # Nuevo parámetro
```

### 3. `_construir_dataset_raw()` - Líneas 591-850
**Cambios principales:**

#### a) Cambio en la firma (línea 591-592)
```python
def _construir_dataset_raw(self, lineas, ordenes_dict, productos_dict,
                          facturas_dict, totales_netos, ncs, ...)  # +ncs
```

#### b) Cambio en la lógica de "Venta bruta" (línea 655)
**Antes:** `total_neto = totales_netos.get(orden_id, orden.get('amount_total', 0))`  
**Ahora:** `venta_bruta = orden.get('amount_total', 0)`  
→ Usa el monto completo de la factura SIN descontar NC

#### c) Nueva sección: Procesamiento de NC (línadas 768-820)
Se agregó código para:
- Iterar sobre cada NC encontrada
- Crear una línea RAW con:
  - `Tipo Movimiento = 'Nota de Crédito'`
  - `Documento = nc.get('name', '')` (ej: NOT-000567)
  - `Venta bruta = -abs(nc_amount)` (NEGATIVO)
  - Todos los márgenes negativos
- Concatenar las filas de NC al DataFrame original

## Validación Realizada

### ✅ IMPLEMENTACIÓN COMPLETADA Y VALIDADA

**Extracción y Inserción:**
- ✅ Script ejecutó sin errores (exit code 0)
- ✅ Base de datos actualizada: 387,406 → 398,502 filas (+14 NC nuevas)
- ✅ **615 filas para 2026-04-15:** 601 ventas + 14 notas de crédito

**Datos en Base de Datos (validación SQL):**
- ✅ Nota de Crédito: 14 líneas 
- ✅ Venta total en NC: **-$560,460** (signos negativos correctos)
- ✅ Margen en NC: **-$560,460** (signos negativos correctos)
- ✅ Todas las NC tienen **venta_bruta < 0** (validación de signos: 14/14 OK)

**Ejemplos de NC creadas:**
- N/C 038769: Venta -$85,147, Margen -$85,147
- N/C 038768: Venta -$19,990, Margen -$19,990
- N/C 038767: Venta -$92,990, Margen -$92,990

## Problemas Resueltos en la Implementación

### 1. Campo `reversed_entry_id` no `reversal_move_id`
- **Problema:** El campo `reversal_move_id` que especificamos era None en Odoo
- **Solución:** Cambiar a `reversed_entry_id` (el campo inverso que sí contiene el ID)
- **Cambio:** Línea 319 en ventas_service.py: `'reversed_entry_id'` en lugar de `'reversal_move_id'`

### 2. Facturas originales no cargadas
- **Problema:** Las NC referenciaban facturas que NO estaban en `invoice_ids`
- **Solución:** Extraer adicionalmentelas facturas originales que son referenciadas por las NC
- **Cambio:** Líneas 328-363 en ventas_service.py: Nueva lógica para cargar facturas de reversal

### 3. Órdenes originales no encontradas
- **Problema:** Las facturas originales podían ser de períodos anteriores sin orden en memory
- **Solución:** Crear órdenes "ficticias" basadas en datos de la factura original
- **Cambio:** Líneas 839-844 en ventas_service.py: Lógica para manejar NC sin orden asociada

## Impacto

Con estos cambios:
- ✅ **Auditoría mejorada:** Cada NC es una línea visible y separada
- ✅ **Trazabilidad:** Se ve exactamente qué se devolvió, cuándo, cuánto y de cuál factura
- ✅ **Análisis automático:** `SUM(Venta bruta)` incluye NC automáticamente  
- ✅ **Signos negativos:** NC siempre aparecen con venta_bruta < 0
- ✅ **Reversibilidad:** Sin NC, el total de ventas es el real sin pre-neteado

## Archivos modificados

- `finanzas-unionx/backend/app/services/ventas_service.py` (3 métodos)

## Archivos de verificación creados

- `data/db/verificar_nc.sql` - Queries para validar NC en la DB
- `CAMBIOS_NC_RESUMEN.md` - Este archivo
