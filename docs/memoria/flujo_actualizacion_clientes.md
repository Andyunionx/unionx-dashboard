# Flujo de actualización de Excel por cliente

> Versión limpia (sin credenciales) del MD original que vivía en Drive
> (`data/contabilidad/cobranza/actualizacion_clientes.md`).
> Las credenciales viven en GitHub Secrets — ver `docs/FLUJO_COBRANZA_BOLETA.md`.

Última actualización: 2026-05-22

---

## Resumen

Cada día a las 07:00 Chile (10:00 UTC), GitHub Actions corre el agente que:

1. Lee Odoo con el usuario `victor@grupoeter.cl`
2. Descarga, por cliente, las 6 hojas estándar (BOL, REVERTIDOS, NC, FACTURAS,
   PAGADAS, yuju)
3. Actualiza el Excel del cliente en Drive preservando las hojas con
   fórmulas / tablas dinámicas

Reemplaza los scripts originales que corrían en el PC de Martín:
- `rebuild_meli_final.py` (MELI 1 y 2)
- `rebuild_falabella.py`
- `rebuild_shopify.py` (Mercado Pago)
- `rebuild_paris.py`

## Clientes activos

| Cliente | Slug en repo | Excel en Drive (rel. a "Trabajado clientes/") | Partners Odoo |
|---|---|---|---|
| MELI 1 | `meli_1` | `MELI/MELI 1 05_2026 (PRUEBA VCR2).xlsx` | BOL: `[16]`, FAC: `[1586,90747]`, todos: `[16,1586,90747,19583]` |
| MELI 2 | `meli_2` | `MELI/MELI 2 2026.xlsx` | (mismos partners que MELI 1) |
| Falabella Fcom | `falabella` | `FALABELLA/Falabella desde abril 2026 B.xlsx` | `[14]` para todo |
| Shopify / MP | `shopify` | `MERCADO PAGO/MERCADO PAGO 2026.xlsx` | `[21]` para todo |
| Paris | `paris` | `PARIS/PARIS 2026.xlsx` | `[18]` para todo |

## Las 6 hojas estándar

| Hoja | Modelo Odoo | Dominio |
|---|---|---|
| `BOL PENDIENTE DE PAGO` | `account.move` | `move_type=out_invoice, payment_state=not_paid, state=posted` |
| `REVERTIDOS` | `account.move` | `move_type=out_invoice, payment_state=reversed` |
| `NC` | `account.move` | `move_type=out_refund` |
| `FACTURAS PENDIENTES DE PAGO` | `account.move` | `payment_state in [not_paid,partial], doc_type_id=1` (sin filtro cliente — TODAS) |
| `PAGADAS` | `account.move` | `payment_state=paid`, últimos 300 días |
| `yuju` | `sale.order` | últimos 200 días |

## Formato de columnas (byte-compatible con scripts originales)

### BOL PENDIENTE / REVERTIDOS / FACTURAS / PAGADAS (9 cols)

| Col | Header | Campo Odoo |
|---|---|---|
| A | RUT Nº | lookup `res.partner.vat` |
| B | Empresa | `account.move.partner_id` (display name) |
| C | Fecha | `account.move.date` |
| D | Fecha de vencimiento | `account.move.invoice_date_due` |
| E | Número de Documento | `l10n_latam_document_number` (entero) |
| F | Referencia de pago | `account.move.payment_reference` (ej. "BEL 466217") |
| G | Referencia | `account.move.ref` |
| H | Importe adeudado | `account.move.amount_residual` |
| I | Pedido de venta | `account.move.invoice_origin` (ej. "S101842") |

### NC (10 cols)

Las 9 estándar + col J:
- J: **BEL Original** — `account.move.reversed_entry_id` display name

### yuju (7 cols)

| Col | Header | Campo Odoo |
|---|---|---|
| A | Cliente | `sale.order.partner_id` (display name) |
| B | Fecha creación | `sale.order.create_date` (con hora) |
| C | Referencia de pedido | `sale.order.name` (ej "S148816") |
| D | Facturas | `sale.order.invoice_ids` → lookup → name del primer move (ej "BEL 503133") |
| E | Yuju Pack Id | `sale.order.yuju_pack_id` |
| F | Marketplace Reference | `sale.order.channel_order_reference` |
| G | Fulfillment | `sale.order.fulfillment` → label humano (Seller/Flex/Full/Mix) |

## Tipos de documento Odoo Chile

`l10n_latam_document_type_id`:
- `1` → (33) Factura Electrónica
- `5` → (39) Boleta Electrónica

## Mapping fulfillment

`sale.order.fulfillment`:
- `fbm` → "Seller"
- `fbf` → "Flex"
- `fbc` → "Full"
- `mix` → "Mix"

## Hojas que NO toca el agente (preservadas)

Definidas en cada YAML del cliente bajo `excel.hojas_preservar`:

| Cliente | Hojas preservadas |
|---|---|
| Paris | PAGOS, DINAMICAS, POR PAGAR, PAGO CENCO, Hoja2 |
| Shopify | pedidos, TRABAJADO, detalle |
| Falabella | _(a verificar con Víctor)_ |
| MELI 1 | _(a verificar con Víctor)_ |
| MELI 2 | _(a verificar con Víctor)_ |

## Fórmulas XLOOKUP que el agente aplica después del update

### Falabella

```
Col J de "BOL PENDIENTE DE PAGO" = XLOOKUP(I{fila}, yuju!D:D, yuju!G:G, 0, 0)
```

Cruza el `Pedido de venta` (col I) del BOL contra la col D `Facturas` de yuju,
y trae la col G `Fulfillment`.

### Shopify

```
Col J de "BOL PENDIENTE DE PAGO" = XLOOKUP(F{fila}, detalle!N:N, detalle!U:U, 0, 0)
```

Cruza `Referencia de pago` (col F) contra hoja `detalle` (definida por Víctor).

## Recálculo de fórmulas

Los scripts originales usaban `win32com.client.DispatchEx` (Excel COM, Windows-only)
para forzar `CalculateFull()` y recalcular fórmulas escritas.

En GitHub Actions corremos sobre Linux — sin COM. Confiamos en que Excel/Drive
**recalcula automáticamente al abrir** el archivo modificado. Si surge algún
caso donde una fórmula no se recalcula al abrir:
- Agregar LibreOffice headless al step del workflow
- O usar runner `windows-latest` solo para clientes específicos

## Agregar nuevo cliente

Ver `docs/COMO_AGREGAR_CLIENTE.md` — paso a paso para Víctor sin tocar Python.

## Próximos pasos (Fase B — conciliación externa)

Pendiente cuando estén los accesos:

1. **Portales de venta** — bajar pagos diarios y cruzar boleta↔pago:
   - Mercado Pago
   - Webpay
   - Yuju
   - Khipu
   - _(otros — completar)_
2. **Cartolas bancarias** — bajar y cruzar factura↔transferencia (1 a 1)
3. **Aplicar pagos a Odoo** automático con confirmación humana
4. **Reporte semanal** automático por mail
