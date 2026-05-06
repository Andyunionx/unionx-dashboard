# ANÁLISIS PROFUNDO: Estructura RAW - Mapeo a Odoo

## Resumen Ejecutivo
- **Total columnas:** 40
- **Tipo:** Dimensiones (24), Métricas (12), Derivadas (4)
- **Origen primario:** `sale.order.line` (Odoo)
- **Enriquecimiento:** `product.product`, `sale.order`, `stock.warehouse`

---

## CATEGORÍA 1: DIMENSIONES DE DOCUMENTO (6 columnas)
Identifican el documento base de la transacción

| # | Columna | Tipo | Origen Odoo | Campo Odoo | Ejemplo |
|----|---------|------|------------|-----------|---------|
| 1 | **Tipo Movimiento** | Text | sale.order / account.move | Tipo (Venta/Devolución) | "Venta" |
| 2 | **Bodega** | Text | stock.warehouse | name | "Carrascal" |
| 3 | **Documento** | Text | account.move | name | "FAC 80523" |
| 4 | **Fecha Documento** | DateTime | account.move | invoice_date | 2025-01-02 |
| 5 | **Pedido** | Text | sale.order | name | "50189" |
| 6 | **Estado Pedido** | Text | sale.order | state | "sale", "done", "cancel" |

**Observación:** Se usan AMBOS sale.order y account.move. Puede ser que se toman datos del pedido pero se procesan cuando se factura.

---

## CATEGORÍA 2: DIMENSIONES DE PRODUCTO (8 columnas)
Identifican el artículo vendido y sus atributos

| # | Columna | Tipo | Origen Odoo | Campo Odoo | Ejemplo |
|----|---------|------|------------|-----------|---------|
| 8 | **SKU** | Text | product.product | default_code | "1659991379695" |
| 12 | **Producto** | Text | product.product | name | "Secaplatos Negro 2 Niveles armable" |
| 13 | **Categoría macro** | Text | product.category (nivel 1) | name | "Home" |
| 14 | **Categoría padre** | Text | product.category (nivel 2) | parent_id | "Organización" |
| 15 | **Categoría hijo** | Text | product.category (nivel 3) | name | "Secadores de platos" |
| 16 | **Categoría comercial** | Text | product.product | ¿Custom field? | "Diamante" |
| 18 | **Pack** | Boolean/Text | product.product | ¿Custom field? | "No" |
| 19 | **Marca** | Text | product.product | manufacturer_id.name | "Simplit" |
| 20 | **Proveedor** | Text | product.product | seller_ids[0].name | "Melollevo" |

**Observaciones:**
- La jerarquía de categorías (macro/padre/hijo) viene de `product.category` con relaciones parent_id
- "Categoría comercial" parece ser un campo adicional no estándar de Odoo
- "Pack" también parece ser custom field

---

## CATEGORÍA 3: DIMENSIONES DE VENTA/COMERCIAL (5 columnas)
Contexto comercial de la transacción

| # | Columna | Tipo | Origen Odoo | Campo Odoo | Ejemplo |
|----|---------|------|------------|-----------|---------|
| 7 | **Tipo Despacho** | Text | sale.order | ¿Custom field? | "Normal"/"Express" |
| 9 | **Canal** | Text | sale.order | ¿Custom field? | "You Market" |
| 21 | **Tipo Marca** | Text | product.product | ¿Custom field? | "Propia"/"Compra" |
| 22 | **Tipo Compra** | Text | product.product | ¿Custom field? | "Importación"/"Local" |
| 23 | **Tipo Negocio** | Text | sale.order | ¿Custom field? | "Fidelización" |
| 24 | **KAM** | Text | sale.order OR res.partner | salesman_id.name OR custom | "Trini" |
| 25 | **Estado Canal** | Text | sale.order | ¿Custom field? | "In"/"Out" |

**Observaciones críticas:**
- Canal, Tipo Negocio, KAM son los campos MÁS IMPORTANTES para agrupar
- Muchos parecen ser custom fields que NO vienen en Odoo estándar
- KAM podría ser el `salesman_id` de la orden o un campo personalizado

---

## CATEGORÍA 4: DIMENSIONES DE TIEMPO (5 columnas)
Derivan de fecha pero son dimensiones de análisis

| # | Columna | Tipo | Origen Odoo | Cálculo | Ejemplo |
|----|---------|------|------------|---------|---------|
| 10 | **Fecha Venta** | DateTime | sale.order | date_order | 2025-01-02 |
| 11 | **Hora Venta** | Time | sale.order.line | HOUR(create_date) | "08:25:58" |
| 26 | **Año venta** | Integer | Derivada | YEAR(date_order) | 2025 |
| 27 | **Mes venta** | Integer | Derivada | MONTH(date_order) | 1 |
| 28 | **Semana venta** | Integer | Derivada | WEEK(date_order) | 1 |
| 29 | **Día semana** | Integer | Derivada | WEEKDAY(date_order) | 4 (Jueves) |
| 30 | **Hora venta** | Time | Derivada | HOUR(date_order) | "08:00:00" |

**Observación:** Hay duplicado entre columna 11 (Hora Venta) y 30 (Hora venta). Probablemente columna 11 es más precisa (create_date).

---

## CATEGORÍA 5: DIMENSIONES DE ESTADO/CLASIFICACIÓN (3 columnas)

| # | Columna | Tipo | Origen Odoo | Campo Odoo | Ejemplo |
|----|---------|------|------------|-----------|---------|
| 17 | **Estado SKU** | Text | product.product | state | "out"/"in" |

**Observación:** "out" probablemente significa "en venta" o "activo en canal".

---

## CATEGORÍA 6: MÉTRICAS - CANTIDAD Y PRECIO (5 columnas)
Datos transaccionales base

| # | Columna | Tipo | Origen Odoo | Campo Odoo | Ejemplo |
|----|---------|------|------------|-----------|---------|
| 31 | **Cantidad** | Float | sale.order.line | qty_invoiced (o product_uom_qty) | 1.0 |
| 32 | **Venta bruta** | Float | sale.order.line | price_subtotal (sin descuentos) | 29690.5 |
| 33 | **Costo Unitario** | Float | product.product | standard_price | 5023.78 |
| 34 | **Costo Total** | Float | DERIVADA | qty × cost_unit | 5023.78 |
| 35 | **Margen Front** | Float | DERIVADA | venta_bruta - costo_total | 19926.22 |

**Crítico:** 
- Cantidad debe ser `qty_invoiced` (cantidad facturada) NO `product_uom_qty` (cantidad pedida)
- Venta bruta es DESPUÉS de descuentos aplicados en la línea
- Costo Unitario viene de `product.product.standard_price` o COGS

---

## CATEGORÍA 7: MÉTRICAS - COMISIONES Y DESCUENTOS (4 columnas)

| # | Columna | Tipo | Origen Odoo | Campo Odoo | Ejemplo |
|----|---------|------|------------|-----------|---------|
| 36 | **Comision %** | Float | sale.order.line | ¿Custom field? | NaN |
| 37 | **Comisión** | Float | Calculada | venta_bruta × (comision_% / 100) | 0.0 |
| 38 | **Logística** | Float | sale.order | ¿Custom field? | 0.0 |
| 39 | **Marketing** | Float | sale.order | ¿Custom field? | NaN (aparece vacío) |

**Crítico:**
- Comisión % NO está en los datos (columna 36 = NaN)
- Logística y Marketing también aparecen como 0 o vacías
- Probablemente estos campos NO existen en Odoo o están mal configurados

---

## CATEGORÍA 8: MÉTRICAS DERIVADAS (3 columnas)

| # | Columna | Tipo | Cálculo | Ejemplo |
|----|---------|------|---------|---------|
| 40 | **Mg final** | Float | margen_front - comisión - logística - marketing | 19926.22 |

---

## SÍNTESIS: ¿QUÉ EXTRAER DE ODOO?

### FUENTE PRIMARIA: `sale.order.line`
```
Fields necesarios:
- id
- order_id → expansión a sale.order
- product_id → expansión a product.product
- qty_invoiced (cantidad)
- price_subtotal (venta bruta)
- discount (si es separado)
- create_date (para hora)
```

### EXPANSIÓN 1: `sale.order` (por order_id)
```
Fields necesarios:
- name (Pedido)
- date_order (Fecha Venta)
- state (Estado Pedido)
- partner_id (Cliente)
- salesman_id (posible KAM)
- warehouse_id (Bodega)

Custom fields esperados:
- x_studio_canal (Canal) ← CRÍTICO
- x_studio_tipo_negocio (Tipo Negocio) ← CRÍTICO
- x_studio_tipo_despacho (Tipo Despacho)
- x_studio_comision_pct (Comisión %)
- x_studio_logistica (Logística)
- x_studio_marketing (Marketing)
```

### EXPANSIÓN 2: `product.product` (por product_id)
```
Fields necesarios:
- default_code (SKU)
- name (Producto)
- categ_id (Categoría - luego expandir)
- manufacturer_id (Marca)
- seller_ids (Proveedor)
- standard_price (Costo Unitario)
- state (Estado SKU)

Custom fields esperados:
- x_studio_categoria_comercial (Categoría comercial)
- x_studio_tipo_marca (Tipo Marca)
- x_studio_tipo_compra (Tipo Compra)
- x_studio_pack (Pack)
```

### EXPANSIÓN 3: `product.category` (por categ_id)
```
Fields necesarios (recursiva):
- name (Categoría nivel actual)
- parent_id (Para recorrer jerarquía)
```

---

## PREGUNTAS CRÍTICAS PARA ANDRÉS

### Sobre Custom Fields ❓
1. **¿Cómo se llaman los custom fields en Odoo?**
   - ¿Son `x_studio_canal` o `x_canal` o algo más?
   - ¿Dónde están guardados (sale.order, product.product)?

2. **Canal, Tipo Negocio, KAM:**
   - ¿Estos 3 campos existen REALMENTE en Odoo?
   - ¿O se rellenan de otras formas?

3. **Comisión, Logística, Marketing:**
   - ¿Existen en Odoo o se calculan después?
   - ¿Cómo se asignan (por canal, global, por cliente)?

### Sobre Estructura de Datos ❓
4. **Categorías jerárquicas:**
   - ¿La jerarquía (macro/padre/hijo) viene de product.category estándar?
   - ¿O hay custom fields adicionales?

5. **KAM:**
   - ¿Es simplemente `sale.order.salesman_id.name`?
   - ¿O hay una tabla separada de KAM?

6. **Tipo Despacho:**
   - ¿Existe en Odoo?
   - ¿O se rellena de otra forma?

---

## SIGUIENTE PASO

Una vez que Andrés confirme los nombres de los custom fields y dónde están, podré:

1. ✅ Crear query exacta a `sale.order.line` con todos los JOINs
2. ✅ Extraer las 40 columnas correctamente
3. ✅ Generar RAW en el mismo formato que Raw ventas Y.xlsx
4. ✅ Validar que coincide exactamente con datos febrero 2026

---

**Generado:** 2026-04-02  
**Estado:** Esperando respuestas de Andrés sobre custom fields en Odoo
