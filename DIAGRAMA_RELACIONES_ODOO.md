# DIAGRAMA: Relaciones entre Modelos Odoo para Extraer RAW

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXTRACCION RAW DESDE ODOO                           │
│                                                                              │
│  PIVOT: sale.order.line                                                     │
│  ═══════════════════════════════════════════════════════════════════════════│
│                                                                              │
│  [sale.order.line]                                                          │
│  ├── id                                 → Fila única                        │
│  ├── qty_invoiced                       → Cantidad                         │
│  ├── price_subtotal                     → Venta bruta                      │
│  ├── create_date                        → Hora (extraer HOUR)              │
│  │                                                                          │
│  ├─→ order_id [sale.order]             ┌─────────────────────────────    │
│  │   ├── name                            │ Documento/Pedido               │
│  │   ├── date_order                      │ Fecha Venta                    │
│  │   ├── state                           │ Estado Pedido                  │
│  │   ├── warehouse_id [stock.warehouse]  │ Bodega → name                 │
│  │   │   └── name                        │                               │
│  │   │                                   │                               │
│  │   ├── salesman_id [res.users]        │ KAM (¿?)                      │
│  │   │   └── name                        │                               │
│  │   │                                   │                               │
│  │   └── x_studio_canal (CUSTOM)        │ CANAL ← CRÍTICO              │
│  │   └── x_studio_tipo_negocio (CUSTOM) │ TIPO NEGOCIO ← CRÍTICO       │
│  │   └── x_studio_tipo_despacho (CUSTOM)│ Tipo Despacho                │
│  │   └── x_studio_comision_pct (CUSTOM) │ Comisión %                   │
│  │   └── x_studio_logistica (CUSTOM)    │ Logística                    │
│  │   └── x_studio_marketing (CUSTOM)    │ Marketing                    │
│  │   └── x_studio_kam (CUSTOM)          │ KAM alternativa (¿?)         │
│  │                                       │                               │
│  ├─→ product_id [product.product]      └─────────────────────────────    │
│  │   ├── default_code                    → SKU                           │
│  │   ├── name                            → Producto                      │
│  │   ├── standard_price                  → Costo Unitario                │
│  │   ├── state                           → Estado SKU                    │
│  │   │                                                                    │
│  │   ├── categ_id [product.category]                                     │
│  │   │   ├── name                        → Categoría hijo                │
│  │   │   └── parent_id [product.category]                                │
│  │   │       ├── name                    → Categoría padre               │
│  │   │       └── parent_id [product.category]                            │
│  │   │           └── name                → Categoría macro               │
│  │   │                                                                    │
│  │   ├── manufacturer_id [res.partner]   → Marca / name                  │
│  │   ├── seller_ids [product.supplierinfo] → Proveedor[0]                │
│  │   │   └── name [res.partner]                                          │
│  │   │                                                                    │
│  │   └── x_studio_categoria_comercial (CUSTOM) → Categoría comercial     │
│  │   └── x_studio_tipo_marca (CUSTOM)          → Tipo Marca             │
│  │   └── x_studio_tipo_compra (CUSTOM)         → Tipo Compra            │
│  │   └── x_studio_pack (CUSTOM)                → Pack                    │
│  │                                                                        │
│  └─→ account.move (¿?)                  → Factura / Documento (¿?)      │
│      └── name                           → FAC xxxxx (¿?)                │
│      └── invoice_date                   → Fecha Documento (¿?)          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘

LEYENDA:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[modelo]              = Tabla en Odoo
├──                   = Campo normal
└── x_studio_*        = Custom field (NECESITA CONFIRMACION)
→                     = Mapea a columna RAW
(¿)                   = Dudoso/Requiere confirmación
←CRÍTICO              = Esencial para agrupar datos
```

---

## FLUJO DE EXTRACCION

```
1. BUSCAR sale.order.line
   ├── Filtro: date_order >= 2026-02-01 AND date_order < 2026-03-01
   ├── Filtro: order_id.state IN ['sale', 'done']
   └── Retornar: 16,648 líneas para febrero 2026

2. POR CADA sale.order.line:
   
   a) EXTRAER campos directos
      ├── qty_invoiced → Cantidad
      ├── price_subtotal → Venta bruta
      ├── create_date → Hora venta
      └── create_date → Derivar: Año, Mes, Semana, Día, Hora
   
   b) EXPANDIR order_id (sale.order)
      ├── name → Pedido
      ├── date_order → Fecha Venta, Derivar: Año, Mes, Semana, Día
      ├── state → Estado Pedido
      ├── warehouse_id.name → Bodega
      ├── salesman_id.name → KAM (¿si no hay custom field?)
      └── [CUSTOM FIELDS]
          ├── x_studio_canal → Canal ⭐
          ├── x_studio_tipo_negocio → Tipo Negocio ⭐
          ├── x_studio_tipo_despacho → Tipo Despacho
          ├── x_studio_comision_pct → Comisión %
          ├── x_studio_logistica → Logística
          ├── x_studio_marketing → Marketing
          └── x_studio_kam → KAM alternativa
   
   c) EXPANDIR product_id (product.product)
      ├── default_code → SKU
      ├── name → Producto
      ├── standard_price → Costo Unitario
      ├── state → Estado SKU
      ├── manufacturer_id.name → Marca
      ├── seller_ids[0].name → Proveedor
      └── [CUSTOM FIELDS]
          ├── x_studio_categoria_comercial → Categoría comercial
          ├── x_studio_tipo_marca → Tipo Marca
          ├── x_studio_tipo_compra → Tipo Compra
          └── x_studio_pack → Pack
   
   d) EXPANDIR categ_id (product.category - recursiva)
      └── Recorrer jerarquía:
          ├── categ_id.name → Categoría hijo
          ├── categ_id.parent_id.name → Categoría padre
          └── categ_id.parent_id.parent_id.name → Categoría macro

3. DERIVAR campos calculados
   ├── Costo Total = Cantidad × Costo Unitario
   ├── Margen Front = Venta bruta - Costo Total
   ├── Comisión = Venta bruta × (Comisión % / 100) [si existe]
   ├── Margen final = Margen Front - Comisión - Logística - Marketing
   └── Año/Mes/Semana/Día = Extraer de fecha_venta

4. SALIDA: DataFrame con 40 columnas
   └── Guardar como CSV con 16,648 filas (línea × línea, sin agrupar)

5. VALIDAR
   └── Comparar totales contra Raw ventas Y.xlsx
       ├── Venta total debe coincidir (99.8%+)
       └── Margen debe coincidir (99.9%+)
```

---

## CAMPOS CRÍTICOS PARA CONFIRMAR CON ANDRÉS

### 🔴 BLOQUEADORES (Sin estos no se puede)

1. **¿Dónde está CANAL?**
   - En `sale.order` como custom field?
   - ¿Qué nombre exacto tiene? (`x_studio_canal`, `x_canal`, `channel_id`?)
   
2. **¿Dónde está TIPO NEGOCIO?**
   - En `sale.order` como custom field?
   - ¿Qué valores posibles? (Marketplace, Distribución, etc.)

3. **¿Dónde está KAM?**
   - ¿Es `sale.order.salesman_id.name`?
   - ¿O hay un custom field separado?

### 🟡 IMPORTANTES (Afectan exactitud)

4. **¿Existe COMISIÓN % en Odoo?**
   - ¿En dónde? ¿sale.order.line o sale.order?
   - ¿O se calcula afuera?

5. **¿Existe LOGÍSTICA en Odoo?**
   - ¿Cómo se asigna? (por orden, por línea, por canal?)

6. **¿Existe MARKETING en Odoo?**
   - ¿Es un custom field?

### 🟢 INFORMACIÓN (Nice to have)

7. **¿Categoría comercial existe?**
   - ¿Es diferente de product.category?
   - ¿O es un custom field?

8. **¿Tipo Marca, Tipo Compra, Pack existen?**
   - ¿Dónde?

---

## PROXIMOS PASOS

1. **ANDRÉS CONFIRMA:**
   - Nombres exactos de custom fields
   - Dónde están ubicados
   - Valores esperados

2. **CREAMOS:**
   - Script de extracción XML-RPC con los nombres correctos
   - Test con febrero 2026
   - Validación contra Raw ventas Y.xlsx

3. **RESULTADO:**
   - RAW completo desde Odoo (16,648 líneas)
   - Estructura idéntica a Raw ventas Y.xlsx
   - Listo para agrupar por canal

---

**Generado:** 2026-04-02
