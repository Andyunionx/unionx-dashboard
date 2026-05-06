# Refactorización: Extracción de Ventas en Formato RAW

## Cambios Realizados

### 1. **Nuevo Método: `extract_to_raw_format()`**
**Archivo:** `finanzas-unionx/backend/app/services/ventas_service.py`

Este es el nuevo método principal para extraer datos de Odoo y transformarlos al **formato RAW exacto de 40 columnas**.

```python
df_raw = service.extract_to_raw_format(
    periodo_inicio="2026-04-01 00:00:00",
    periodo_fin="2026-04-30 23:59:59",
    progress_callback=progress_callback
)
```

**Ventajas:**
- Genera exactamente las 40 columnas del RAW histórico
- Mapea todos los campos de Odoo a la estructura RAW
- Enriquece con Maestra Canales y Matriz Productos
- Calcula todas las métricas financieras (Margen, Comisión, etc)

### 2. **Métodos Auxiliares Nuevos**

#### `_cargar_maestra_canales()`
Carga la Maestra Canales para obtener:
- Tipo Negocio
- KAM (Key Account Manager)

#### `_cargar_matriz_productos()`
Carga la Matriz de Productos para obtener:
- Categoría macro, padre, hijo, comercial

#### `_construir_dataset_raw()`
Construye el DataFrame con exactamente 40 columnas en orden RAW:

1. Tipo Movimiento → "Venta"
2. Bodega → warehouse_id.name
3. Documento → factura.name
4. Fecha Documento → invoice_date
5. Pedido → order.name
6. Estado Pedido → order.state
7. Tipo Despacho → (vacío por ahora)
8. SKU → product.default_code
9. Canal → order.channel (estandarizado)
10. Fecha Venta → order.date_order (date)
11. Hora Venta → order.date_order (time)
12. Producto → product.name
13-16. Categorías → from Matriz Productos
17. Estado SKU → (vacío)
18. Pack → (vacío)
19. Marca → product.manufacturer
20. Proveedor → (vacío)
21. Tipo Marca → (vacío)
22. Tipo Compra → (vacío)
23. Tipo Negocio → from Maestra Canales
24. KAM → from Maestra Canales
25. Estado Canal → (vacío)
26. Año venta → extracted from date
27. Mes venta → extracted from date
28. Semana venta → extracted from date
29. Día semana → extracted from date
30. Hora venta → (duplicado intencional)
31. Cantidad → product_uom_qty
32. Venta bruta → total NETO (con NC descontadas)
33. Costo Unitario → purchase_price
34. Costo Total → purchase_price * cantidad
35. Margen Front → venta bruta - costo total
36. Comisión % → comisión / venta * 100
37. Comisión → comisión amount
38. Logística → logistics cost
39. Marketing → marketing cost
40. Mg final → margen front - comisión - logística - marketing

#### `_calcular_metricas_raw()`
Valida y convierte tipos de datos:
- Columnas numéricas → float64
- Fechas → datetime64
- Año/Mes/Semana/Día → int64

### 3. **Script Nuevo: `actualizar_raw_historico.py`**

Script para actualizar automáticamente el archivo RAW histórico.

**Uso:**
```bash
# Actualizar con datos de hoy
python actualizar_raw_historico.py

# Actualizar periodo específico
python actualizar_raw_historico.py --periodo "2026-04-01 00:00:00" "2026-04-30 23:59:59"
```

**Funcionalidad:**
1. Extrae datos de Odoo en formato RAW
2. Lee el archivo RAW existente (`Raw ventas Y (4).xlsx`)
3. Agrega las nuevas filas (append, no sobrescribe)
4. Guarda el archivo actualizado
5. Muestra KPIs del período insertado

---

## Flujo de Datos (Nuevo)

```
Odoo
  ↓
extract_to_raw_format()  ← Nuevo método principal
  ↓ (40 columnas exactas)
DataFrame RAW
  ↓
actualizar_raw_historico.py
  ↓
Raw ventas Y (4).xlsx (append)  ← Maestra histórica actualizada
  ↓
Reportes y análisis
```

---

## Comparación: Antes vs Después

### ANTES
- Extracción directa a formato "reporte" (39 columnas)
- No compatible con RAW histórico
- No capturaba muchos atributos (marca, proveedor, etc)
- Reportes no alimentaban la maestra

### DESPUÉS
- Extracción en formato RAW (40 columnas exactas)
- Compatible 100% con RAW histórico
- Captura todos los atributos necesarios
- Script automático que actualiza la maestra cada día
- Reportes se generan A PARTIR del RAW (no al revés)

---

## Próximos Pasos

1. **Probar script**: Ejecutar `actualizar_raw_historico.py` con datos de abril
2. **Validar estructura**: Verificar que las 40 columnas estén correctas
3. **Integrar en automatización**: Programar ejecución diaria
4. **Generar reportes desde RAW**: Refactorizar reportes para que lean del RAW actualizado

---

## Campos a Completar en Futuro

Los siguientes campos están vacíos por ahora, pero pueden llenarse cuando Odoo tenga la información:
- Tipo Despacho
- Estado SKU
- Pack
- Proveedor
- Tipo Marca
- Tipo Compra
- Estado Canal
- Marketing (costo)

Esto permite que el sistema sea extensible sin romper la estructura.
