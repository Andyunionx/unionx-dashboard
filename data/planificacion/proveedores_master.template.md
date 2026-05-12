# Template — Maestro de Proveedores

Schema esperado para `proveedores_master.parquet`. Si el tercero entrega un sheet con
otras columnas, ajustar el mapeo de aliases en `extract_proveedores_master.py`.

## Columnas

| Columna | Tipo | Ejemplo | Notas |
|---|---|---|---|
| `proveedor_id` | str | `PROV-001` | Idealmente coincide con el `proveedor` de `dim_productos` en Turso |
| `nombre` | str | `Foshan Trading Co.` | Razón social. Único, sirve de key de match |
| `pais_origen` | str | `China` | Para análisis de riesgo geográfico/arancelario |
| `puerto_origen` | str | `Shenzhen` / `Yiwu` / `Ningbo` | Determina rutas y lead times de tránsito |
| `contacto_nombre` | str | `Lily Chen` | Quién atiende el día a día |
| `contacto_email` | str | `lily@foshan.com` | Para correos automatizados futuros |
| `contacto_whatsapp` | str | `+86 138 1234 5678` | Canal preferido del proveedor |
| `moneda` | str | `USD` / `EUR` / `CNY` | Para escenario cambiario |
| `incoterm` | str | `EXW` / `FOB` / `CIF` | Define qué cubre el precio acordado |
| `tipo_credito` | str | `T/T 30% advance + 70% before shipment` | Condición de pago acordada |
| `dias_credito` | int | `0` (anticipo) / `30` / `60` | Si tiene crédito, días desde factura |
| `dias_produccion_min` | int | `25` | Lead time de producción mínimo |
| `dias_produccion_max` | int | `45` | Lead time de producción máximo |
| `dias_transito_min` | int | `20` | Tránsito marítimo mínimo a Chile |
| `dias_transito_max` | int | `45` | Tránsito marítimo máximo a Chile |
| `moq_unidades` | int | `500` | Mínimo de orden en unidades por SKU |
| `moq_usd` | float | `5000` | Mínimo de orden en USD por PI |
| `moq_cbm` | float | `15` | Mínimo en CBM (volumen) — relevante para LCL/FCL |
| `comentarios` | str | `Cierre fábrica fin de año, no recibir pedidos después de 1-nov` | Notas libres |

## Fuente

El maestro lo mantiene el tercero (consultor Supply Chain) en un Google Sheet.
Una vez disponible:

1. Compartir el sheet en lectura con `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com`
2. Completar `SHEET_ID` y `TAB_NAME` en `extract_proveedores_master.py`
3. Correr `python extract_proveedores_master.py`

Mientras tanto el archivo puede llenarse manualmente con un CSV → parquet.
