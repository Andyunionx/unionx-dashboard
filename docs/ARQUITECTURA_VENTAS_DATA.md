# Arquitectura de datos de Ventas — construcción y enriquecimiento

> Cómo se construye el dato de ventas que alimenta el dashboard: órdenes, notas de
> crédito (NC), CMR, costos, canales. Referencia para mantenimiento y onboarding.
>
> Última verificación contra código: 2026-06-03.

## Flujo general

```
Odoo (sale.order, account.move) ─┐
Google Sheet "Base CMR" ─────────┤  → extract_mes_actual_a_parquet.py
CSVs (manual_externa, costo) ────┘        │
                                          ▼
        ventas_mes_actual.parquet  (mes vigente, regenerado por el pulso cada hora)
        ventas_historico.parquet   (≤ 1-jun, foto fija "congelada", ya con NC/CMR adentro)
                                          │  (commit a GitHub por el Cloudflare Worker → pulso)
                                          ▼
        App Streamlit: DuckDB lee los 2 parquet (Opción C: desde GitHub Raw, refresca c/15 min)
                       → MaestraService → KPIs
```

La **lectura** (DuckDB/MaestraService) NO transforma el dato — solo consulta. Todo el
enriquecimiento ocurre **arriba**, al generar el parquet.

## El motor de extracción: `ventas_service.py::extract_to_raw_format`

Produce el "formato RAW" de 40 columnas. **Es el método de producción** (lo llama
`extract_mes_actual_a_parquet.py`). Pasos:

| Paso | Qué hace | Método |
|---|---|---|
| 1 | Órdenes de venta (`sale.order`, estado sale/done/cancel) | `_extraer_ordenes` |
| 2 | Líneas (`sale.order.line`) → 1 fila de **Venta** por línea | `_extraer_lineas` |
| 3 | Productos (`product.product`) | `_extraer_productos` |
| 4 | Facturas (`out_invoice`) y **Notas de Crédito** (`out_refund`) | `_extraer_facturas_y_nc` |
| 4b | NC cross-month: carga productos/líneas de meses anteriores que una NC revierte | (en `extract_to_raw_format`) |
| 5 | Planillas: **Maestra Canales** + **Matriz Productos** | `_cargar_maestra_canales`, `_cargar_matriz_productos` |
| 6 | Arma las 40 columnas RAW | `_construir_dataset_raw` |
| 7 | Métricas derivadas (comisión, logística, margen, fechas) | `_calcular_metricas_raw` |

> ⚠️ Existe también `extract` / `_construir_dataset` (legacy) que **netea** las NC en el
> total de la orden. **NO es el de producción.** El parquet usa `extract_to_raw_format`
> / `_construir_dataset_raw`.

## Notas de Crédito (NC) — filas negativas, NO neteo

En `_construir_dataset_raw`, cada NC entra como **fila separada y negativa** (no se netea
en la orden):
- **`Tipo Movimiento` = 'Nota de Crédito'** (vs 'Venta').
- **Venta bruta, Costo Total, Comisión, Logística, Margen Front, Mg final → NEGATIVOS.**
- Se vincula a la **factura original → orden → SKU** vía `reversed_entry_id` / `reversal_move_id`.
- El **costo se toma de la `sale.order.line` original** (`purchase_price`) → margen de la
  devolución exacto.
- **Cross-month:** si la NC revierte una venta de un mes previo, se cargan ese producto y
  su línea original aunque no estén en el período (paso 4b).

**Consecuencia:** `SUM(venta_bruta)` **netea solo** (las NC son negativas). Las devoluciones
se ven aparte filtrando `tipo_movimiento`.

## Enriquecimiento (paso 5)
- **Maestra Canales** (`data/planillas`): Canal → **Tipo Negocio / Línea de Negocio**;
  resuelve canal por Empresa/cliente. Para NC, resuelve el canal por el partner de la
  venta original (con fallbacks heurísticos FAC*/BEL* → "Ajustes contables").
- **Matriz Productos**: SKU → **categorías (macro/padre/hijo), marca, proveedor, pack**.

## Overlays (post-extract, en `extract_mes_actual_a_parquet.py`)
Se aplican **sobre** el RAW ya construido, antes de escribir el parquet:
1. **`costo_override`** (`data/costo_override.csv`) → corrige filas con costo 0.
2. **`manual_externa`** (`data/manual_externa_facturas.csv`) → inyecta facturas que NO están
   en Odoo (Sodimac y similares), enriquecidas con la Matriz Productos.
3. **Casa Mila → UnionX B2B** → reclasificación de canal (Casa Mila SpA es la razón social
   de UnionX B2B, no entidad externa).
4. **CMR** (`extract_cmr_ventas.py::enriquecer_cmr_df`) → lee el Google Sheet "Base CMR 2026",
   matchea por (fecha, sku) las filas placeholder web con `venta_bruta=0`, y las marca como
   canal `CMR` / `tipo_negocio = Fidelización CMR` con su venta y margen. Se re-aplica en
   CADA regeneración del parquet (el extract baja de Odoo sin CMR).

## Histórico congelado
`ventas_historico.parquet` es una foto fija hasta el 1-jun (`CUTOFF_HISTORICO`), generada
desde la fuente con todo el enriquecimiento ya adentro (incluido CMR histórico ~$1.095M).
El `ventas_mes_actual.parquet` cubre el mes vigente y se regenera cada hora; un paso de
filtro (`>= cutoff`) evita doble conteo del día de corte.

## Capa de lectura (no transforma)
- `views/shared.py::_get_duck_conn` materializa los 2 parquet en DuckDB (con
  `PARQUET_ONLY=1`). Con `PARQUET_BASE_URL` lee desde GitHub Raw (Opción C, refresca c/15 min).
- `MaestraService` (`finanzas-unionx/backend/app/services/maestra_service.py`) corre las
  queries de KPIs sobre esa tabla `ventas`. SQL dialecto-neutral (corre en SQLite y DuckDB).

## Índice de archivos clave
| Tema | Archivo |
|---|---|
| Extracción RAW (órdenes, NC, enriquecimiento) | `finanzas-unionx/backend/app/services/ventas_service.py` |
| Orquestación + overlays (costo, manual, CMR) + Gate 1 | `extract_mes_actual_a_parquet.py` |
| Enriquecimiento CMR | `extract_cmr_ventas.py` |
| Lectura (motor DuckDB) | `views/shared.py` |
| Queries KPIs | `finanzas-unionx/backend/app/services/maestra_service.py` |
| Validación (Gate 1/2) | `validacion_ventas.py` |
| Scheduler del pulso | `scheduler/` (Cloudflare Worker) |
