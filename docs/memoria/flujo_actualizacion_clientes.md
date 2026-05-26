# 📋 Wiki técnica — Actualización de clientes

> **Editable por Víctor y Andrés directamente** (vía Claude Code).
> Es la "verdad" sobre cada cliente que el agente de cobranza procesa.
> Cuando algo cambia en Odoo, en un Excel o en un cliente, **se actualiza acá primero**.

Última edición: 2026-05-26 — por: Claude (inicial)

---

## 🎯 Qué hace el agente (resumen 1 párrafo)

Todos los días a las 07:00 Chile (cuando el cron esté activo), el agente:
1. Se conecta a Odoo con el usuario `victor@grupoeter.cl`
2. Para cada cliente configurado (`agente-cobranza/clientes/*.yaml`):
   - Descarga 6 hojas de documentos contables
   - Baja el Excel del cliente desde Drive
   - Reemplaza esas 6 hojas con la data fresca de Odoo
   - Preserva las hojas marcadas como "manuales" (PAGOS, DINAMICAS, etc.)
   - Sube el Excel actualizado a Drive con sufijo `_ACTUALIZADO.xlsx`

---

## 📊 Las 6 hojas estándar

| Hoja | Qué trae | Filtro Odoo |
|---|---|---|
| `BOL PENDIENTE DE PAGO` | Boletas emitidas no pagadas | `move_type=out_invoice, payment_state=not_paid, state=posted` |
| `REVERTIDOS` | Boletas/facturas revertidas | `move_type=out_invoice, payment_state=reversed, state=posted` |
| `NC` | Notas de crédito emitidas | `move_type=out_refund, state=posted` |
| `FACTURAS PENDIENTES DE PAGO` | TODAS las facturas tipo 33 pendientes (no filtra por cliente) | `move_type=out_invoice, payment_state in [not_paid,partial], type_id=1, state=posted` |
| `PAGADAS` | Facturas/boletas pagadas últimos 300 días | `move_type=out_invoice, payment_state=paid, state=posted, date >= hoy-300d` |
| `yuju` | Pedidos de venta últimos 200 días | `sale.order, create_date >= hoy-200d` |

> ⚠️ **Atención Víctor:** la hoja `PAGADAS` se REGENERA entera cada corrida.
> Si en tu workflow agregás columnas extra o filas manuales a esa hoja, se
> pierden al día siguiente. Anotalo en `incidente_paris_2026-05.md` si te
> pasó algo de esto.

---

## 👥 Clientes configurados

### Paris

- **Partner ID Odoo:** `18`
- **RUT:** `66666666-6`
- **Excel:** `Trabajado clientes/PARIS/PARIS 2026.xlsx`
- **Hojas que NO se tocan (preservadas):** `PAGOS`, `DINAMICAS`, `POR PAGAR`, `PAGO CENCO`, `Hoja2`
- **XLOOKUP custom:** ninguno
- **YAML:** `agente-cobranza/clientes/paris.yaml`
- **Status:** ⚠️ INCIDENTE 23-25 may 2026 — ver `incidente_paris_2026-05.md`

**Particularidades:**
<!-- Víctor: completá acá si Paris tiene cosas raras (ej: "tiene 2 cuentas en Odoo", "los lunes carga manual la hoja X", etc.) -->
- _(Pendiente: Víctor completa con detalles del workflow real)_

---

### MELI 1

- **Partner ID Odoo:** `16` (boletas)
- **Partners para `yuju`/pagadas:** `[16, 1586, 90747, 19583]`
- **RUT:** `66666666-6`
- **Excel:** `Trabajado clientes/MELI/MELI 1 05_2026 (PRUEBA VCR2).xlsx`
- **Hojas preservadas:** _(ver YAML)_
- **YAML:** `agente-cobranza/clientes/meli_1.yaml`

**Particularidades:**
- Tiene **4 partner_ids distintos** en Odoo (uno para boletas, otros para facturas)
<!-- Víctor: completá si hay más -->

---

### MELI 2

- **Partner ID Odoo:** `1586` y `90747` (facturas)
- **RUT facturas:** `77398220-1`
- **Excel:** `Trabajado clientes/MELI/MELI 2 2026.xlsx`
- **YAML:** `agente-cobranza/clientes/meli_2.yaml`

**Particularidades:**
<!-- Víctor: completá -->

---

### Falabella Fcom

- **Partner ID Odoo:** `14`
- **RUT:** `66666666-6`
- **Excel:** `Trabajado clientes/FALABELLA/Falabella desde abril 2026 B.xlsx`
- **YAML:** `agente-cobranza/clientes/falabella.yaml`

**Particularidades:**
- La hoja `yuju` **no tiene** columna "Yuju Pack Id"
- Col G de `yuju` = Marketplace Reference
- Col J de `BOL PENDIENTE DE PAGO` tiene fórmula:
  ```
  =XLOOKUP(I{fila}, yuju!D:D, yuju!G:G, 0, 0)
  ```
<!-- Víctor: completá si hay más -->

---

### Shopify / Mercado Pago

- **Partner ID Odoo:** `21`
- **RUT:** `66666666-6`
- **Excel:** `Trabajado clientes/MERCADO PAGO/MERCADO PAGO 2026.xlsx`
- **Hojas preservadas:** `pedidos`, `TRABAJADO`, `detalle`
- **YAML:** `agente-cobranza/clientes/shopify.yaml`

**Particularidades:**
- Col J de `BOL PENDIENTE DE PAGO` tiene fórmula:
  ```
  =XLOOKUP(F{fila}, detalle!N:N, detalle!U:U, 0, 0)
  ```
<!-- Víctor: completá -->

---

## 🔧 Cosas que es bueno saber

### Tipos de documento Odoo Chile

| `l10n_latam_document_type_id` | Tipo |
|---|---|
| 1 | (33) Factura Electrónica |
| 5 | (39) Boleta Electrónica |

### Campos Odoo importantes

- `date` = fecha contable (NO es la fecha de emisión, aunque suele coincidir)
- `invoice_date` = fecha de emisión real
- `payment_state` = `not_paid`, `partial`, `paid`, `reversed`, `in_payment`
- `state` = `draft`, `posted`, `cancel`. **El agente solo trae `posted`.**

### Recálculo de fórmulas Excel

- **Scripts viejos de Martín (Windows):** recalculaban con Excel COM (`win32com`)
- **Agente nuevo (Linux/GitHub Actions):** NO recalcula. Confía en que Drive/Excel
  recalcula al abrir el archivo.
- Si una fórmula aparece sin recalcular al abrir el Excel, anotalo en `decisiones.md`
  y avisale a Andrés.

---

## 📝 Sección "Cosas que aprendí" (Víctor)

<!--
Víctor: cada vez que descubras algo nuevo, agregá un bullet acá con fecha.
Le decís a Claude:
  "Agregá un bullet a la sección 'Cosas que aprendí' de
   docs/memoria/flujo_actualizacion_clientes.md: hoy 26-may descubrí que..."
-->

- _(vacío por ahora — Víctor empieza a llenarlo)_

---

## 🔗 Referencias

- Doc técnica del flujo (no editable): `docs/FLUJO_COBRANZA_BOLETA.md`
- Guía agregar cliente nuevo: `docs/COMO_AGREGAR_CLIENTE.md`
- Estado actual: `docs/CONTABILIDAD_ESTADO_2026-05.md`
- Incidente Paris: `docs/memoria/incidente_paris_2026-05.md`
- Decisiones: `docs/memoria/decisiones.md`
