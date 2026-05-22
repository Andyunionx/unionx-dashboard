# Agente Cobranza

Actualiza diariamente los Excel de cobranza de cada cliente de UnionX,
descargando datos frescos desde Odoo y preservando las fórmulas / tablas
dinámicas que cada Excel ya tiene en Drive.

## Por qué existe

Reemplaza los scripts originales de Martín (`rebuild_meli_final.py`,
`rebuild_falabella.py`, `rebuild_shopify.py`, `rebuild_paris.py`) que
corrían en el PC de Martín con Task Scheduler de Windows. Ahora corren
centralizados en GitHub Actions, no dependen de que el PC esté encendido,
y son mantenibles por cualquiera que toque un YAML.

## Arquitectura

```
agente-cobranza/
├── actualizar_cliente.py        # script genérico, lee YAML
├── lib/
│   ├── odoo_helpers.py          # consultas a las 6 hojas estándar
│   ├── drive_helpers.py         # bajar/subir archivos a Drive
│   └── excel_updater.py         # update preservando hojas
├── clientes/
│   ├── _template.yaml           # plantilla para agregar clientes
│   ├── paris.yaml
│   ├── falabella.yaml
│   ├── shopify.yaml
│   ├── meli_1.yaml
│   └── meli_2.yaml
└── requirements.txt
```

## Las 6 hojas estándar que actualiza por cliente

| Hoja | Modelo Odoo | Filtro |
|---|---|---|
| `BOL PENDIENTE DE PAGO` | account.move | `move_type=out_invoice, payment_state=not_paid` |
| `REVERTIDOS` | account.move | `move_type=out_invoice, payment_state=reversed` |
| `NC` | account.move | `move_type=out_refund` |
| `FACTURAS PENDIENTES DE PAGO` | account.move | `payment_state in [not_paid,partial], doc_type_id=1` (sin filtrar cliente) |
| `PAGADAS` | account.move | `payment_state=paid`, últimos 300 días |
| `yuju` | sale.order | últimos 200 días, para cruce XLOOKUP |

Cualquier otra hoja del Excel del cliente (PAGOS, DINAMICAS, POR PAGAR,
etc.) queda **intacta** — la define cada YAML en `excel.hojas_preservar`.

## Cómo se ejecuta

### Localmente (testing)

```bash
# Setear creds (1 vez)
export ODOO_PASSWORD="..."           # password de Odoo
export GOOGLE_CREDENTIALS_JSON='{...}'  # JSON del service account

# Modo dry-run (sin tocar Drive)
python actualizar_cliente.py --config clientes/paris.yaml --dry-run

# Procesar 1 cliente
python actualizar_cliente.py --config clientes/paris.yaml

# Procesar todos
python actualizar_cliente.py --todos
```

### En producción (GitHub Actions)

Cron: `.github/workflows/agente_cobranza_diario.yml` — 07:00 Chile (10:00 UTC).

Lee `ANDRES_ODOO_PASSWORD` y `GOOGLE_CREDENTIALS_JSON` desde Secrets del repo.

## Cómo agregar un cliente nuevo

Ver [`docs/COMO_AGREGAR_CLIENTE.md`](../docs/COMO_AGREGAR_CLIENTE.md).

Resumen: copiar `clientes/_template.yaml` → `clientes/<nombre>.yaml`,
completar campos, abrir PR.

## Requisitos previos al primer run en producción

1. Cada Excel de cliente en Drive debe estar **compartido con el service account**:
   `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com` con rol `Editor`.

2. `ANDRES_ODOO_PASSWORD` debe estar en Secrets del repo
   (Settings → Secrets and variables → Actions).

3. `GOOGLE_CREDENTIALS_JSON` debe estar en Secrets (el mismo que usan los
   syncs de Finanzas).

## Limitación conocida: recálculo de fórmulas

Los scripts originales de Martín usan `win32com.client` (Excel COM) para
recalcular fórmulas — Windows-only. Acá corremos en Linux (Actions), así
que **no recalculamos**: las fórmulas quedan en el archivo y Excel/Drive
las recalcula cuando un humano abre el Excel.

Si alguna fórmula no se recalcula bien al abrir, agregamos un step con
LibreOffice headless al workflow. Por ahora confiamos en el recalc-on-open
(que es lo que pasa siempre que abrís un archivo modificado).
