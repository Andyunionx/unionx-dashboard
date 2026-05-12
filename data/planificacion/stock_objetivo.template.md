# Template — Política de Stock Objetivo

Schema esperado para `stock_objetivo.parquet`. Editable directo desde la app
en el módulo *Políticas* (auto-genera una sugerencia inicial detectando las
categorías comerciales presentes en ventas).

## Columnas

| Columna | Tipo | Ejemplo | Notas |
|---|---|---|---|
| `categoria_comercial` | str | `A` / `B` / `C` o `Alta` / `Media` / `Baja` | Valor exacto debe coincidir con `dim_productos.categoria_comercial` |
| `meses_cobertura_objetivo` | float | `1.5` (A) / `2.5` (B) / `4.0` (C) | El target — manda el requerimiento de compra |
| `meses_cobertura_minimo` | float | `0.75` / `1.0` / `2.0` | Si la cobertura cae bajo esto, ALERTA |
| `meses_cobertura_maximo` | float | `3.0` / `4.5` / `8.0` | Si supera esto, candidato a LIQUIDACIÓN |
| `lead_time_buffer_dias` | int | `15` | Días extra que se suman al lead time del proveedor para "safety stock" |
| `comentarios` | str | `Top sellers — no quebrar nunca` | Notas libres |

## Lógica

- **Stock objetivo (uds)** = `venta_diaria_promedio × meses_cobertura_objetivo × 30`
- **Trigger de compra**: cuando `cobertura_actual_dias < (lead_time_total + buffer)`
- **Sobre-stock**: cuando `cobertura_actual_dias > meses_cobertura_maximo × 30`

## Política inicial sugerida (ejemplo)

| Categoría | Objetivo | Mínimo | Máximo | Buffer | Racional |
|---|---|---|---|---|---|
| Alta rotación / A | 1.5m | 0.75m | 3m | 15d | Rota rápido, mantener flujo |
| Media / B | 2.5m | 1m | 4.5m | 15d | Equilibrio entre quiebre y capital inmovilizado |
| Baja / C | 4m | 2m | 8m | 15d | Compra menos frecuente, lotes más grandes |

Ajustar al conocimiento del negocio. La app permite editar in-line y guardar.
