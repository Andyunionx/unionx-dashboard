# MAPEO: Extracción RAW Directamente desde Odoo

## Objetivo
Reemplazar Excel intermediario con extracción directa desde Odoo usando XML-RPC API.

---

## Estructura de Datos Requerida

### Dimensiones Clave (Obligatorias para Agrupar)
- **Período:** Año venta, Mes venta, Semana venta, Día semana
- **Ubicación:** Bodega
- **Comercial:** Canal, Tipo Negocio, KAM
- **Producto:** SKU, Producto, Categoría macro/padre/hijo/comercial, Marca, Proveedor
- **Documento:** Tipo Movimiento, Documento, Pedido, Estado Pedido

### Métricas Clave (Lo que sumamos por dimensión)
- Cantidad
- Venta bruta
- Costo Total
- Margen Front
- Comisión %, Comisión
- Logística
- Marketing
- Margen final

---

## Mapeo: 40 Columnas → Odoo Models

| # | Columna RAW | Tipo | Modelo Odoo | Campo Odoo | Notas |
|----|---|---|---|---|---|
| 1 | Tipo Movimiento | Dim | sale.order / stock.move | ¿Custom? | Odoo almacena en tipo de documento (factura, entrada stock, etc.) |
| 2 | Bodega | Dim | stock.warehouse | name | Almacén del movimiento |
| 3 | Documento | Dim | account.move OR sale.order | name | Número de factura o número de SO |
| 4 | Fecha Documento | Dim | account.move | invoice_date OR sale.order | date_order |
| 5 | Pedido | Dim | sale.order | name | Número de orden de venta |
| 6 | Estado Pedido | Dim | sale.order | state | draft, sent, sale, done, cancel |
| 7 | Tipo Despacho | Dim | sale.order | ¿Custom? | Tipo de entrega (normal, express, pickup) |
| 8 | SKU | Dim | product.product | default_code | Código interno del producto |
| 9 | Canal | Dim | sale.order | ¿Custom field? | Mercado Libre, Falabella, etc. (asignado manualmente o por cliente) |
| 10 | Fecha Venta | Dim | sale.order | date_order | Fecha de la orden |
| 11 | Hora Venta | Dim | sale.order.line | create_date (hour part) | Se puede extraer de create_date |
| 12 | Producto | Dim | product.product | name | Nombre del producto |
| 13 | Categoría macro | Dim | product.category | custom_level (¿) | Categorización jerarquizada |
| 14 | Categoría padre | Dim | product.category | parent_id | Categoría padre |
| 15 | Categoría hijo | Dim | product.category | name | Categoría específica |
| 16 | Categoría comercial | Dim | product.category | ¿Custom? | Categorización comercial diferente |
| 17 | Estado SKU | Dim | product.product | state | active, draft, obsolete |
| 18 | Pack | Dim | product.product | ¿Custom? | Si el producto es un pack (Si/No) |
| 19 | Marca | Dim | product.product | manufacturer_id | Fabricante |
| 20 | Proveedor | Dim | product.product | seller_ids | Proveedor principal |
| 21 | Tipo Marca | Dim | product.product | ¿Custom? | Propia, Compra, Otras marcas |
| 22 | Tipo Compra | Dim | product.product | ¿Custom? | Importación, Compra local |
| 23 | Tipo Negocio | Dim | sale.order | ¿Custom? | Marketplace, Distribución, Páginas propias, Fidelización |
| 24 | KAM | Dim | sale.order OR res.partner | ¿Custom? | Key Account Manager responsable |
| 25 | Estado Canal | Dim | sale.order | ¿Custom? | In, Out (estatus del canal) |
| 26 | Año venta | Dim | DERIVED | year(date_order) | Extraído de fecha |
| 27 | Mes venta | Dim | DERIVED | month(date_order) | Extraído de fecha |
| 28 | Semana venta | Dim | DERIVED | week(date_order) | Extraído de fecha |
| 29 | Día semana | Dim | DERIVED | weekday(date_order) | Extraído de fecha (0-6 o 1-7) |
| 30 | Hora venta | Dim | DERIVED | hour(create_date) | Extraído de hora |
| 31 | Cantidad | Métrica | sale.order.line | qty_invoiced OR product_uom_qty | Cantidad total vendida |
| 32 | Venta bruta | Métrica | sale.order.line | price_subtotal OR price_total | Valor sin descuentos |
| 33 | Costo Unitario | Métrica | product.product | standard_price OR cost | Costo por unidad |
| 34 | Costo Total | DERIVED | = Cantidad × Costo Unitario | Calculado | |
| 35 | Margen Front | DERIVED | = Venta bruta - Costo Total | Calculado | |
| 36 | Comisión % | Métrica | sale.order.line OR account.invoice.line | ¿Custom field? | % de comisión por línea |
| 37 | Comisión | DERIVED | = Venta bruta × (Comisión % / 100) | Calculado | Validar si es por línea o por canal |
| 38 | Logística | Métrica | sale.order | ¿Custom field? | Costo logístico asignado |
| 39 | Marketing | Métrica | sale.order | ¿Custom field? | Costo marketing asociado |
| 40 | Mg final | DERIVED | = Margen Front - Comisión - Logística - Marketing | Calculado | |

---

## Preguntas para Andrés (CRÍTICAS)

❓ **Campo "Canal"** 
- ¿Es un campo personalizado en sale.order? 
- ¿Cómo se asigna? (manual, por cliente, por fuente)

❓ **Campo "Tipo Negocio"** 
- ¿Custom field en sale.order?
- ¿Se asigna por cliente o por línea?

❓ **Campo "KAM"** 
- ¿Es el `salesman_id` de sale.order?
- ¿O un custom field en res.partner?

❓ **Campo "Comisión %"** 
- ¿Dónde se almacena? (por línea, por orden, por canal)
- ¿Es un custom field?

❓ **Campos "Logística" y "Marketing"** 
- ¿Son custom fields en sale.order?
- ¿Cómo se calculan?

❓ **Categorías Jerárquicas** 
- ¿Se usan product.category estándar?
- ¿Hay diferencia entre "Categoría comercial" y "Categoría padre"?

❓ **"Tipo Marca", "Tipo Compra"** 
- ¿Dónde se almacenan?

---

## Propuesta de Extracción

### Paso 1: Query Base (sale.order.line + producto + orden)
```python
domain = [
    ('order_id.date_order', '>=', '2026-02-01'),
    ('order_id.date_order', '<', '2026-03-01'),
    ('order_id.state', 'in', ['sale', 'done']),
]

fields = [
    'id', 'order_id', 'product_id', 'qty_invoiced', 
    'price_subtotal', 'create_date',  # de sale.order.line
    'order_id.name', 'order_id.date_order', 'order_id.partner_id', 
    'order_id.warehouse_id', 'order_id.state',  # de sale.order
    # ... campos custom del pedido (Canal, Tipo Negocio, KAM, etc.)
]

lines = models.execute_kw(db, uid, pw, 'sale.order.line', 'search_read', [domain], {'fields': fields})
```

### Paso 2: Enriquecimiento
Para cada línea:
1. Obtener detalles del producto (SKU, categoría, marca, proveedor, costo)
2. Obtener custom fields de la orden (Canal, Tipo Negocio, KAM, Comisión, Logística, Marketing)
3. Derivar métricas calculadas (Costo Total, Margen, etc.)
4. Derivar dimensiones de fecha (Año, Mes, Semana, Día)

### Paso 3: Agregación
Agrupar por: [Año, Mes, Canal, Tipo Negocio, KAM]
Sumar: Cantidad, Venta, Costo, Margen, Comisiones, Logística, Marketing

---

## Siguiente Paso

**Una vez Andrés confirma las preguntas críticas**, construiremos:
1. `extraer_raw_desde_odoo.py` — Extrae línea × línea con todos los campos
2. `paso3a2_agregar_raw_odoo.py` — Reemplaza paso3a1 (Excel) con versión Odoo directa
3. Test con febrero 2026
4. Comparación con valores actuales para validar que es exacto

---

