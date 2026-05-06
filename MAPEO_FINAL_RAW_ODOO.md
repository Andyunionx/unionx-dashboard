# MAPEO FINAL: RAW Ventas Y ← Odoo (Confirmado por Andrés)

## Resumen Ejecutivo
- **Modelo base:** `sale.order` (con expansiones a product, partner, user, team)
- **Período test:** Febrero 2026
- **Filas esperadas:** 16,648 líneas
- **Campos confirmados:** 20 (resto derivados o vacíos)

---

## MAPEO 1:1 - RAW ← Odoo

| # | Columna RAW | Odoo Model | Odoo Field | Ejemplo | Notas |
|----|------------|-----------|-----------|---------|-------|
| 1 | Tipo Movimiento | sale.order | state → "Venta" | "Venta" | Derivado de state |
| 2 | Bodega | sale.order | warehouse_id.name | "Carrascal" | ✓ Confirmado |
| 3 | Documento | sale.order | payment_reference | "FAC 80523" | ✓ N° Document |
| 4 | Fecha Documento | sale.order | create_date | 2025-01-02 | ✓ create_date |
| 5 | Pedido | sale.order | name | "SO12345" | ✓ N° pedido Odoo |
| 6 | Estado Pedido | sale.order | state | "done" | ✓ State |
| 7 | Tipo Despacho | sale.order | fulfillment | "Normal" | ✓ Campo fulfillment |
| 8 | SKU | product.product | default_code | "1659991379695" | ✓ Confirmado |
| 9 | Canal | sale.order → partner | partner_id.name | "You Market" | ✓ Partner_Id = Cliente/Canal |
| 10 | Fecha Venta | sale.order | create_date | 2025-01-02 | ✓ create_date |
| 11 | Hora Venta | sale.order | create_date (HOUR) | "08:25:58" | ✓ Extraer hora de create_date |
| 12 | Producto | product.product | name | "Secaplatos Negro..." | ✓ Variante del producto |
| 13 | Categoría macro | product.category | Jerarquía nivel 0 | "Home" | ✓ categ_id (recursiva) |
| 14 | Categoría padre | product.category | Jerarquía nivel 1 | "Organización" | ✓ parent_id recursiva |
| 15 | Categoría hijo | product.category | Jerarquía nivel 2 | "Secadores de platos" | ✓ categ_id directo |
| 16 | Categoría comercial | ? | ? | "Diamante" | ❌ NO encontrado |
| 17 | Estado SKU | product.product | state | "active" | ✓ Derivado |
| 18 | Pack | ? | ? | "No" | ❌ NO encontrado |
| 19 | Marca | product.product | brand_id.name | "Simplit" | ✓ Confirmado |
| 20 | Proveedor | product.product | supplier | "Melollevo" | ✓ seller_ids |
| 21 | Tipo Marca | ? | ? | "Propia" | ❌ NO encontrado |
| 22 | Tipo Compra | ? | ? | "Importación" | ❌ NO encontrado |
| 23 | Tipo Negocio | sale.order | team_id.name | "Fidelización" | ✓ Team_Id (sales team) |
| 24 | KAM | sale.order → user | user_id.name | "Trini" | ✓ User_Id (vendedor) |
| 25 | Estado Canal | ? | ? | "In" | ❌ NO encontrado |
| 26 | Año venta | Derivada | YEAR(create_date) | 2025 | ✓ Calculado |
| 27 | Mes venta | Derivada | MONTH(create_date) | 1 | ✓ Calculado |
| 28 | Semana venta | Derivada | WEEK(create_date) | 1 | ✓ Calculado |
| 29 | Día semana | Derivada | WEEKDAY(create_date) | 4 | ✓ Calculado |
| 30 | Hora venta | Derivada | HOUR(create_date) | 8 | ✓ Calculado |
| 31 | Cantidad | sale.order.line | product_uom_qty | 1.0 | ✓ Confirmado |
| 32 | Venta bruta | sale.order | amount_total | 29690.50 | ✓ Venta total bruta |
| 33 | Costo Unitario | sale.order.line | purchase_price | 5023.78 | ✓ Confirmado |
| 34 | Costo Total | Derivada | qty × purchase_price | 5023.78 | ✓ Calculado |
| 35 | Margen Front | sale.order.line | margin | 19926.22 | ✓ margin (Odoo lo calcula) |
| 36 | Comision % | ? | ? | NaN | ❌ NO está en Odoo |
| 37 | Comisión | ? | ? | 0.0 | ❌ NO está en Odoo |
| 38 | Logística | ? | ? | 0.0 | ❌ NO está en Odoo |
| 39 | Marketing | ? | ? | NaN | ❌ NO está en Odoo |
| 40 | Mg final | Derivada | margin - comisión - logística - marketing | 19926.22 | ✓ Por ahora = margin |

---

## CAMPOS CONFIRMADOS (20 de 40)

✅ **Disponibles directamente en Odoo:**
1. Bodega: `warehouse_id`
2. Documento: `payment_reference` 
3. Fecha Documento: `create_date`
4. Pedido: `name`
5. Estado Pedido: `state`
6. Tipo Despacho: `fulfillment`
7. SKU: `default_code`
8. Canal: `partner_id.name` (cliente/partner)
9. Fecha Venta: `create_date`
10. Hora Venta: HOUR(`create_date`)
11. Producto: `product_id.name`
12. Marca: `brand_id.name`
13. Tipo Negocio: `team_id.name` (sales team)
14. KAM: `user_id.name` (vendedor)
15. Cantidad: `product_uom_qty`
16. Venta bruta: `amount_total`
17. Costo Unitario: `purchase_price`
18. Margen Front: `margin` (Odoo calcula)
19. Categoría (jerarquía): `product_id.categ_id` (recursiva)
20. Proveedor: `product_id.seller_ids[0].name`

---

## CAMPOS NO DISPONIBLES EN ODOO (6 campos)

❌ **Comisión %, Comisión, Logística, Marketing** — Andrés confirma que NO están en Odoo por ahora
- Se pueden dejar en blanco (0 o NaN)
- Se rellenarán después desde otra fuente (Skill distribución-comisiones-canal)

❓ **Campos sin fuente identificada (5):**
- Categoría comercial (¿dónde viene?)
- Pack (¿dónde viene?)
- Tipo Marca (¿dónde viene?)
- Tipo Compra (¿dónde viene?)
- Estado Canal (¿dónde viene?)

---

## QUERY ODOO - Estructura Final

```python
# BUSCAR sale.order en febrero 2026
domain = [
    ('create_date', '>=', '2026-02-01'),
    ('create_date', '<', '2026-03-01'),
    ('state', 'in', ['sale', 'done']),
]

fields = [
    'id', 'name', 'create_date', 'state',
    'partner_id',           # Canal
    'user_id',              # KAM
    'team_id',              # Tipo Negocio
    'warehouse_id',         # Bodega
    'payment_reference',    # Documento
    'fulfillment',          # Tipo Despacho
    'amount_total',         # Venta bruta
    'amount_untaxed',       # Venta neta (alternativa)
    # Expansiones:
    'order_line',           # → sale.order.line (para detalle)
]

# POR CADA sale.order.line:
line_fields = [
    'id', 'product_id', 'product_uom_qty',
    'price_unit', 'purchase_price', 'margin'
]
```

---

## ALTERNATIVA: ¿Usar `sale.order` o `sale.order.line`?

### Opción A: `sale.order.line` (RECOMENDADO)
- Una fila = una línea de producto
- Datos a nivel de producto (SKU, categoría, marca)
- Cantidad y precios por línea
- **16,648 líneas esperadas**

### Opción B: `sale.order`
- Una fila = una orden completa
- Datos agregados por orden
- Cantidad y precios sumados
- Menos filas pero menos detalle

**Voy con Opción A** → `sale.order.line` (más detalle, igual a Raw original)

---

## PROCEDIMIENTO DE EXTRACCIÓN

### Paso 1: Buscar todas las órdenes de febrero 2026
```sql
SELECT * FROM sale.order
WHERE create_date >= '2026-02-01'
  AND create_date < '2026-03-01'
  AND state IN ('sale', 'done')
```
Resultado esperado: ~X órdenes

### Paso 2: Por cada orden, extraer líneas
```sql
SELECT * FROM sale.order.line
WHERE order_id IN (resultado del paso 1)
```
Resultado esperado: 16,648 líneas

### Paso 3: Enriquecer cada línea
Para cada línea agregar:
- Datos de la orden (partner_id, user_id, team_id, etc.)
- Datos del producto (SKU, categoría, marca, etc.)
- Datos derivados (año, mes, hora, costo total, etc.)

### Paso 4: Salida
DataFrame con 40 columnas (o 35 sin Comisión/Logística/Marketing)

---

## VALIDACIÓN ESPERADA

Una vez extraído desde Odoo:
- **Filas:** ~16,648 (igual a Raw)
- **Venta total:** ~$410M (igual a Raw)
- **Margen total:** ~$192.5M (igual a Raw)
- **Coincidencia:** 99.9%+ (pequeñas diferencias por redondeo)

---

## SIGUIENTES PASOS

1. ✅ **Crear `extraer_raw_odoo_v2.py`** con este mapeo exacto
2. ✅ **Conectar a Odoo** con credenciales Andrés
3. ✅ **Extraer February 2026** (sale.order.line)
4. ✅ **Enriquecer** con partner, user, team, product
5. ✅ **Generar CSV** con 40 columnas
6. ✅ **Validar** contra Raw ventas Y.xlsx
7. ✅ **Inyectar** en Análisis Resultado

---

**Generado:** 2026-04-02
**Confirmado por:** Andrés
**Estado:** Listo para codificar
