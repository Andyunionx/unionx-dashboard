# Auditoría Dashboard Ventas — Drive Raw vs Local

Fecha: 2026-05-13
Fuente Drive: `Raw ventas Y.xlsx` (108 MB, 421.326 filas, pestaña RAW)
Fuente Local: `data/historico/ventas_historico.parquet` + Turso live (mayo 2026)

## Veredicto

El Drive es la **fuente de verdad operacional** (consolidación Odoo + cargas manuales del equipo). El parquet local solo reflejaba Odoo, por eso diferían 15-20K filas/mes en histórico cerrado y 1-20% en venta.

## Acciones aplicadas

### 1. Reemplazo del parquet histórico pre-2026-04 con Drive

Script `reemplazar_historico_desde_drive.py` (nuevo). Descarga el xlsx, lee la pestaña RAW, filtra a `fecha_venta < CUTOFF` y reemplaza las filas pre-cutoff del parquet local manteniendo las post-cutoff (abril 2026 ya congelado).

- Parquet pre-fix: 373.497 filas, 11 MB
- Parquet post-fix: **397.858 filas, 12.5 MB**
- Diferencia: **+24.361 filas** (datos pre-2026-04 que el extractor de Odoo nunca había traído)

Filas por mes post-fix:
| Mes | Filas |
|---|---:|
| 2025-09 | 15.770 |
| 2025-10 | 34.280 |
| 2025-11 | 25.774 |
| 2025-12 | 35.499 |
| 2026-01 | 28.259 |
| 2026-02 | 29.047 |
| 2026-03 | 43.993 |
| 2026-04 | 19.230 |

### 2. Fusión de canales con capitalización inconsistente

Variantes detectadas y fusionadas:

| Variante incorrecta | Canónico | Filas Turso | Filas Parquet |
|---|---|---:|---:|
| `Sp Digital` | `SP Digital` | 85 | (ya normalizado en step 1) |
| `Exporunning` | `ExpoRunning` | 18 | 18 |

**Cambios**:
- [ventas_service.py:907-913](finanzas-unionx/backend/app/services/ventas_service.py#L907) — diccionario `CANAL_CANONICO` aplicado al canal resuelto. Si en el futuro aparecen más variantes, agregar entradas ahí.
- Turso: 103 filas actualizadas (85 + 18).
- Parquet local: 18 filas actualizadas.

## Pendiente — bug del extractor de Odoo

Hay canales que aparecen en el Drive de fechas recientes (mayo 2026) pero **NO** llegan a Turso vía extractor:

| Canal | Drive abril/mayo | Turso post-CUTOFF | Hipótesis |
|---|---:|---:|---|
| Speedreams | 3 filas / $240K (abr), 4 filas / $1.4M (may) | 0 | El extractor no resuelve este canal o lo filtra |
| Eattouch | 1 fila / $3.7K (abr) | 0 | Idem |
| Exporunning | 145 filas / $1.3M (abr) | (ahora normalizado a ExpoRunning) | OK post-fusión |

Speedreams y Eattouch son canales de **pocas filas pero existentes**. El extractor de Odoo probablemente:
- No los reconoce en el resolver `_resolver_canal` (queda canal vacío o "Otro")
- O los pedidos no tienen `channel` ni `partner_id` en Odoo que coincida con esos nombres

**Acción siguiente** (no aplicada hoy, requiere debug): correr el extractor en modo verbose y revisar qué `channel_raw_odoo` viene de Odoo para esos pedidos, y agregar entradas al mapping `canal_a_tn` / `_resolver_canal`.

## Casa Mila / Apprecio — no son bug

Aparecen en local pero no en Drive abril 2026 porque:
- Casa Mila tiene venta histórica pero el Drive descargado no la trae (¿corte temporal del archivo? ¿el equipo dejó de cargarla?)
- Apprecio en abril solo tiene NC (-$10K), monto chico

Decisión user: dejarlos como están — no son drift, son canales que existen en local pero el Drive auditado no incluye este mes.

## Diferencias residuales esperadas

Después de los fixes anteriores, el local mantendrá diff vs Drive en:

1. **Abril 2026**: Drive 34.825 filas vs Local 19.230 (preservado de Turso congelado). El user pidió "hasta marzo 2026" para reemplazo, así que abril queda con Turso. La diff de 15K filas refleja el bug del extractor + cargas manuales que se hicieron post-extracción.
2. **Mayo 2026 en adelante**: dependerá de si el extractor resuelve bien los canales recientes (Speedreams, Eattouch, etc.).

## Resumen — qué hace ahora el dashboard

- **Hasta 2026-03-31**: lee del parquet, que coincide con el Drive maestro al ~100%
- **2026-04**: lee del parquet congelado de Turso (sin Drive merge)
- **2026-05+**: lee Turso live

## Próximas mejoras

1. **Workflow GH Actions para refrescar parquet mensual desde Drive** — semejante al `freeze_mes.yml`, pero descargando del Drive en vez de Turso. Garantiza sincronía con el Drive operacional.
2. **Resolver del canal en el extractor**: mejorar para que Speedreams/Eattouch lleguen a Turso.
3. **Workflow de alerta**: comparar Drive vs Local cada quincena y avisar si la diff supera 2% en algún mes ya cerrado.
