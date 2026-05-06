# AUDITORÍA CRÍTICA: extract_to_raw_format()

## REFERENCIA CORRECTA (Archivo RAW)
```
Raw ventas Y (5).xlsx - Abril 1-15:
  • 11,090 líneas
  • 4,627 documentos únicos
  • Venta Bruta: $272,717,830
  • Margen: $121,600,717 (44.6%)
  • Composición:
    - Ventas: $278,069,290
    - Devoluciones: -$5,351,460
    - Otros costos: $0
  • NETO: $272,717,830
```

---

## PROBLEMAS ENCONTRADOS EN extract_to_raw_format()

### PROBLEMA #1: Venta Bruta Incorrecta (Línea 694)

**Código actual:**
```python
# Total de factura (SIN descontar NC)
venta_bruta = orden.get('amount_total', 0)  # ❌ INCORRECTO
```

**El bug:**
Cuando una orden tiene MÚLTIPLES líneas, el código asigna `amount_total` de la ORDEN completa a CADA línea:

```
Orden SO-2026-0001: amount_total = $1,000
  ├─ Línea 1 (Producto A, qty 10): price_subtotal = $600
  │   → venta_bruta asignado = $1,000 ❌
  │
  └─ Línea 2 (Producto B, qty 20): price_subtotal = $400
      → venta_bruta asignado = $1,000 ❌

RESULTADO: $1,000 + $1,000 = $2,000 en lugar de $1,000
```

**Solución:**
```python
# Usar el monto de ESTA línea, no el total de la orden
venta_bruta = linea.get('price_subtotal', 0)  # ✓ CORRECTO
```

---

### PROBLEMA #2: NC No Se Restan de la Venta (Líneas 790, 878)

**Código actual:**
```python
# Para VENTAS (línea 790):
'Venta bruta': venta_bruta,  # Amount_total SIN restar NC

# Para NC (línea 878):
'Venta bruta': -abs(nc_amount),  # NC como línea SEPARADA
```

**El bug:**
Las NC aparecen como líneas separadas (correcto para auditoría), PERO:
- El monto de venta en la ORDEN original NO se reduce
- Resultado: Una venta de $1,000 facturada y luego devuelta $300 aparece como:
  - Línea 1 (Venta): $1,000
  - Línea 2 (NC): -$300
  - **NETO en el archivo RAW: $700** (correcto)
  - **PERO el "Documento Contable" (factura) tiene amount_total = $1,000**

Aquí está el problema del neteo **según documento contable**:
- El usuario menciona: "revisa los campos que se extraen y el neteo **según documento contable**"
- El código _extraer_facturas_y_nc() calcula `totales_netos_por_factura` (facturas - NC)
- PERO _construir_dataset_raw() **NO UTILIZA ESTOS TOTALES NETOS**
- En cambio, sigue usando `orden.get('amount_total', 0)` sin aplicar neteado

---

### PROBLEMA #3: Campos Faltantes para Contabilidad

El método debería incluir:
```
- Documento Contable (Factura): account.move.name
- Número Factura: l10n_latam_document_number  
- Tipo Factura: move_type (out_invoice / out_refund)
- Referencia de NC: reversed_entry_id (qué factura revierte)
- Fecha Contable: invoice_date (no date_order)
```

Actualmente solo toma:
```python
'Documento': factura.get('name', '') if factura else '',  # ✓ Tiene
'Fecha Documento': factura.get('invoice_date', '') if factura else '',  # ✓ Tiene
# Pero FALTA: l10n_latam_document_number, move_type, reversed_entry_id
```

---

## COMPARATIVA: Referencia vs Actual

| Métrica | Raw ventas Y (5).xlsx | extract_to_raw_format() |Diferencia|
|---------|---------------------|----------------------|----------|
| Líneas Abril | 11,090 | 2,679 | -8,411 (falta 75%) |
| Documentos | 4,627 | ~986 | -3,641 (falta 78%) |
| Venta Bruta | $272.7M | $523.2M | +$250.5M (+91.8%) |
| Tipo Movimiento | Venta, Devolución | Venta, Nota de Crédito | ⚠️ Diferentes nombres |

**Razones de la diferencia:**

1. **Venta Bruta 91.8% más alta** → Bug #1: amount_total de orden en cada línea
2. **75% menos líneas** → Bug #1: Mucho más agregado por error de sobreduplición
3. **Tipo movimiento diferente** → Bug #2: Usar "Devolución" vs "Nota de Crédito"

---

## SOLUCIÓN REQUERIDA

### Paso 1: Fijar price_subtotal
```python
# Línea 694 (actual)
venta_bruta = orden.get('amount_total', 0)

# Debe ser:
venta_bruta = linea.get('price_subtotal', 0)  # Monto de ESTA línea
```

### Paso 2: Aplicar neteo según documento contable
```python
# Para CADA LÍNEA, obtener su factura y aplicar neteado:
factura_id = [inv for inv in orden.get('invoice_ids', [])][0]  # Primera factura
venta_neta = totales_netos.get(factura_id, linea.get('price_subtotal', 0))

# Luego:
'Venta bruta': venta_neta,  # Ya neteada por factura
```

### Paso 3: Agregar campos de contabilidad
```python
'Documento Contable': factura.get('l10n_latam_document_number', '') if factura else '',
'Tipo Factura': factura.get('move_type', '') if factura else '',
'Ref NC Reversión': nc.get('reversed_entry_id')[0] if nc.get('reversed_entry_id') else '',
```

### Paso 4: Renombrar tipos de movimiento
```python
# Línea 847 (actual):
'Tipo Movimiento': 'Nota de Crédito',

# Debe ser:
'Tipo Movimiento': 'Devolución',  # Coincidir con archivo RAW
```

---

## IMPACTO EN SINCRONIZADOR

Si sincronizador_ventas.py está usando extract_to_raw_format(), los números serán SIEMPRE incorrectos.

**Recomendación inmediata:**
- NO usar extract_to_raw_format() hasta que sea corregido
- Usar método alternativo más simple (similar a extract_final.py) que:
  1. Lee sale.order.line (con price_subtotal correcto)
  2. Mapea a factura_id
  3. Aplica neteado a nivel de factura
  4. Inserta líneas individuales (sin duplicar amount_total)

