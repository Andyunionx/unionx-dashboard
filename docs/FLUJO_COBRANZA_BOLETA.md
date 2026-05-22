# Flujo Cobranza Boleta — Doc técnica

> Versión limpia del MD original de Víctor/Martín (`data/contabilidad/cobranza/actualizacion_clientes.md`).
> **Sin credenciales en plano** — usar GitHub Secrets para producción.

Última actualización: 2026-05-22.

## Resumen del flujo

1. **Descargar de Odoo** los documentos contables (boletas, facturas, NC)
   del cliente — pagados y pendientes.
2. **Descargar de Odoo** los pedidos de venta (`sale.order`) para cruzar
   cada doc con su pedido.
3. **Actualizar el Excel del cliente en Drive** con 6 hojas estándar
   (BOL PENDIENTE, REVERTIDOS, NC, FACTURAS PENDIENTES, PAGADAS, yuju)
   preservando las demás hojas que tienen fórmulas / tablas dinámicas.
4. **(Próxima fase B)** conciliar con pagos de portales (Mercado Pago,
   Webpay, Yuju, Khipu, etc.) y aplicar pagos a Odoo.

## Quién lo ejecuta

- **Hoy:** scripts Python en el PC de Martín (`C:\Users\marti\odoo-mcp\`)
  vía Windows Task Scheduler, todos los días 07:00 AM.
- **Próximo (en migración):** GitHub Actions con cron 07:00 Chile, ver
  `.github/workflows/agente_cobranza_diario.yml`.

## Credenciales y accesos

> ⚠️ Las credenciales **NO** se commitean al repo. Viven en:
> - GitHub Secrets (para Actions)
> - Variables de entorno locales (para corridas manuales)

| Servicio | Cómo se accede | Secret name |
|---|---|---|
| Odoo | XML-RPC con user/pass de Víctor | `VICTOR_ODOO_PASSWORD` (a crear) |
| Google Drive | Service account | `GOOGLE_CREDENTIALS_JSON` (existente) |

Usuario Odoo: `victor@grupoeter.cl` (dueño funcional del proceso de cobranza).

Service account email (debe estar compartido con cada Excel cliente):
`union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com`

## Las 6 hojas estándar

Mismo contrato que tenía Martín en sus scripts originales.

| Hoja | Modelo Odoo | Dominio |
|---|---|---|
| `BOL PENDIENTE DE PAGO` | `account.move` | `move_type=out_invoice, payment_state=not_paid, state=posted` |
| `REVERTIDOS` | `account.move` | `move_type=out_invoice, payment_state=reversed` |
| `NC` | `account.move` | `move_type=out_refund` (notas crédito emitidas) |
| `FACTURAS PENDIENTES DE PAGO` | `account.move` | `payment_state in [not_paid,partial], doc_type_id=1` (sin filtro cliente — TODAS las facturas tipo 33 globales) |
| `PAGADAS` | `account.move` | `payment_state=paid` últimos 300 días |
| `yuju` | `sale.order` | `partner_id in partners.todos`, últimos 200 días |

## Campos Odoo que se traen

Definido en `agente-cobranza/lib/odoo_helpers.py`:

```python
INV_FIELDS = [
    "l10n_latam_document_number", "partner_id", "date", "invoice_date_due",
    "ref", "payment_reference", "amount_residual", "invoice_origin",
    "name", "move_type", "amount_total", "payment_state",
    "l10n_latam_document_type_id", "journal_id",
]
NC_FIELDS = INV_FIELDS + ["reversed_entry_id"]
SO_FIELDS = [
    "name", "partner_id", "create_date", "yuju_pack_id",
    "channel_order_reference", "fulfillment", "invoice_ids",
    "amount_total", "state",
]
```

### Tipos de documento Odoo Chile

| `l10n_latam_document_type_id` | Tipo |
|---|---|
| 1 | (33) Factura Electrónica |
| 5 | (39) Boleta Electrónica |

## Clientes configurados al 2026-05-22

| Cliente | Slug | Excel destino |
|---|---|---|
| MELI 1 | `meli_1` | `…/MELI/MELI 1 05_2026 (PRUEBA VCR2).xlsx` |
| MELI 2 | `meli_2` | `…/MELI/MELI 2 2026.xlsx` |
| Falabella Fcom | `falabella` | `…/FALABELLA/Falabella desde abril 2026 B.xlsx` |
| Shopify / Mercado Pago | `shopify` | `…/MERCADO PAGO/MERCADO PAGO 2026.xlsx` |
| Paris | `paris` | `…/PARIS/PARIS 2026.xlsx` |

Cada uno tiene su YAML en `agente-cobranza/clientes/<slug>.yaml`.

## Fórmulas XLOOKUP (cruce BOL ↔ yuju)

Algunos clientes cruzan boletas con pedidos vía fórmula en la hoja BOL.
Se setea automáticamente después del rewrite, definido en el YAML del cliente.

**Falabella:**
```
Col J de BOL = XLOOKUP(I{fila}, yuju!D:D, yuju!G:G, 0, 0)
```

**Shopify:**
```
Col J de BOL = XLOOKUP(F{fila}, detalle!N:N, detalle!U:U, 0, 0)
```

## Limitación conocida: recálculo de fórmulas

Los scripts originales de Martín usan Excel COM (`win32com.client`) para
forzar `CalculateFull()` después de escribir el archivo, porque openpyxl
no recalcula. Eso solo corre en Windows.

En GitHub Actions corremos sobre Ubuntu — sin COM. Confiamos en que
Excel/Drive **recalcula automáticamente al abrir** el archivo modificado
(es el comportamiento por default). Si surge algún caso donde una fórmula
no se recalcula bien al abrir, evaluamos:

- LibreOffice headless en el step del workflow
- Runner `windows-latest` para clientes específicos
- Pre-calcular en Python con `pycel`

## Próximos pasos (Fase B — conciliación externa)

Pendiente cuando estén los accesos:

1. **Portales de venta** (Mercado Pago, Webpay, Yuju, Khipu) — bajar
   pagos diarios y cruzar boleta↔pago por monto+fecha+orden.
2. **Cartolas bancarias** — bajar (manual al inicio) y cruzar
   factura↔transferencia 1 a 1.
3. **Aplicar pagos a Odoo** (`account.move.js_assign_outstanding_line`)
   con preview + confirmación humana.
4. **Reporte semanal automático** por mail con cobrado vs por cobrar.

## Cómo testear localmente

```bash
# Setear creds
export ODOO_PASSWORD="..."
export GOOGLE_CREDENTIALS_JSON='{...}'

# Dry-run de Paris (sin tocar Drive)
python agente-cobranza/actualizar_cliente.py \
  --config agente-cobranza/clientes/paris.yaml \
  --dry-run

# Real con 1 cliente
python agente-cobranza/actualizar_cliente.py --config agente-cobranza/clientes/paris.yaml

# Todos los clientes
python agente-cobranza/actualizar_cliente.py --todos
```
