# Datos — App Planificación

Este directorio contiene los datasets que alimentan la app `dashboard_planificacion.py`.

## Archivos esperados

| Archivo | Origen | Cómo cargar |
|---|---|---|
| `proveedores_master.parquet` | Drive del tercero (consultor SC) | `python extract_proveedores_master.py` |
| `stock_objetivo.parquet` | Editable desde la app, módulo *Políticas* | UI directa, o sugerencia automática |

## Archivos reutilizados de otros módulos (no viven acá)

| Dato | Path |
|---|---|
| Forecast SKU (anchored) | `data/forecast/forecast_skus_anchored.parquet` |
| Forecast SKU (base) | `data/forecast/forecast_skus.parquet` |
| Tránsito COMEX | `data/comex/transito.parquet` |
| Ventas histórico | `data/historico/ventas_historico.parquet` |
| Stock vivo | Turso (vía `views.shared.cached_stock`) |
| Elasticidad-precio | `data/forecast/elasticidad_sku.parquet` |

## Templates de schema

Cada archivo `*.template.md` documenta las columnas esperadas y ejemplos de valores válidos:

- `proveedores_master.template.md`
- `stock_objetivo.template.md`

## Pendiente integración

- **App finanzas-unionx**: cuando exponga endpoint `/api/cashflow/proyeccion`, el módulo
  *Caja* lo consume directo (sin escribir nada en este directorio).
- **Maestra de importaciones del tercero**: el sheet definitivo aún no está. Cuando esté,
  completar `SHEET_ID` y `TAB_NAME` en `extract_proveedores_master.py` y compartir con
  `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com`.
