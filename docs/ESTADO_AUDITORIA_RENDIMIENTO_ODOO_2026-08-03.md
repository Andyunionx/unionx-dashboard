# Auditoría de Rendimiento Odoo PROD — 03/08/2026

**Autor:** sesión Claude (workspace UNION X - IA, credencial andres@grupoeter.cl uid Odoo).
**Alcance real de esta sesión:** RPC a PROD + HTTP externo. SIN acceso a: MCP odoo-sh (logs/métricas/shell), repo `unionx-cl/innovatek-sh` (gh de AndyunionX no lo resuelve), VPS Hostinger (sin llave SSH). Los frentes que dependen de esos accesos quedan marcados **[BLOQUEADO-ACCESO]**.

## TL;DR (5 líneas)

1. **Workers saturados**: mismas rutas responden 0,5 s o 30 s según si pillan worker libre — es cola de espera, no una query puntual. Un simple `search_count` sobre mail.message **bota un worker (502)**.
2. **La mensajería interna está obesa**: mail.message crece ~431.000 filas/mes (jul), mail.followers 3,99 M, mail.tracking.value 2,89 M, ir.attachment 1,0 M — cada pedido de marketplace genera ~12 mensajes + followers + adjuntos.
3. **La integración de marketplaces (usuario Trinidad, RPC desde el VPS) es el gran escritor**: 849 pedidos + 807 partners (una dirección de despacho NUEVA por pedido; 388.000 partners acumulados) + 7.034 mensajes + 764 adjuntos cada 24 h.
4. **13 crons custom corren cada ≤10 min** (suite Shopify Directo ×5, Yuju webhooks c/1 min con una cola de 45.945 filas, LATAM Pass ×2, Factura 33, sweep boletas, SII...) — el pool de cron está permanentemente ocupado; casi todos son de las últimas semanas, calza con la degradación gradual.
5. **La fuga confirmada sigue abierta**: unionx.push.queue = 3.789 pending (28/07 → hoy, ~630/día) porque el PR #15 no se ha mergeado; los consumidores (crons 137/138) están apagados.

## Línea base — 03/08/2026 ~09:00-10:00 CLT (guardar: es el "antes")

| Ruta | HTTP | TTFB (muestras) |
|---|---|---|
| b2b.unionx.cl/ (home) | 200 | **5,85 s · 6,81 s · 20,95 s** |
| /web/login | 000/200 | **timeout 30 s · 20,82 s · 0,53 s** |
| /tienda (shop) | 200 | **5,27 s** |
| /tienda/juego-loza-…-9909 (ficha) | 200 | **3,89 s · 9,61 s** |
| RPC authenticate | — | 1,14 s |
| RPC search_read sale.order limit 80 | — | 0,86 · 0,70 · 0,48 s |

Nota: la línea base de las 08:45 (torre de Martín) daba 1,16-1,22 s; una hora después medimos 5-30 s → la saturación es intermitente y empeora en horario hábil. La varianza 0,5 s ↔ 30 s en `/web/login` (ruta casi estática) prueba **cola de workers**, no queries de catálogo.

## Hallazgos con evidencia

| # | Causa | Evidencia | Impacto | Esfuerzo | Estado |
|---|---|---|---|---|---|
| 1 | Workers saturados / insuficientes para la carga actual | TTFB 0,5↔30 s misma ruta; 502 al contar mail.message; contar ir.attachment tardó 23 s | ALTO | — (medir plan real) | **[BLOQUEADO-ACCESO]** requiere odoo-sh (workers, limit_*, logs) |
| 2 | Bloat de mensajería: mail.message ~431 k/mes (jul; may 354 k), mail.followers 3.995.980, mail.tracking.value 2.890.114, mail.notification 299.811 | counts RPC 03/08 | ALTO | Medio | Propuesto (limpieza + reducir generación) |
| 3 | Integración marketplaces crea 1 partner delivery por pedido → res.partner 388.000 y sumando 807/día | read_group create_date 24 h; muestra: hijas de "Cliente Falabella/ML/Shopify/Walmart" | ALTO (escrituras + followers/chatter en cascada + autocomplete lento) | Medio (cambiar a reutilizar partner o shipping en el picking) | Propuesto — código del conector (repo innovatek-sh) |
| 4 | 13 crons custom cada ≤10 min (115 Yuju stock c/1 min sobre cola yuju.webhook.record de 45.945; 148/150/153 Shopify c/5 min; 116 c/6 min; 146/151/154/155/2/12/24 c/10 min) | ir.cron read 03/08 | MEDIO-ALTO | Bajo (espaciar/consolidar) | Propuesto (requiere OK: espaciar afecta latencia de stock/boletas) |
| 5 | unionx.push.queue re-creciendo: 3.789 pending desde purga 28/07 (~630/día), consumidores apagados, PR #15 sin merge | search_count + rango create_date | BAJO (hoy) / recurrente | Bajo | **[BLOQUEADO-ACCESO]** merge PR #15; purga con backup ejecutable ya |
| 6 | ir.attachment 1.001.601 filas (1,0 M) — filestore OK (solo 3 en DB) pero la tabla es enorme; 764 adjuntos/día por integración (etiquetas/PDF) | counts RPC | MEDIO | Medio (retención/limpieza adjuntos de mensajería viejos) | Propuesto |
| 7 | website.visitor 107.904 / website.track 250.347 | counts | BAJO | Bajo (cron core ya limpia) | Monitorear |
| 8 | Access Denied recurrente c/6 s (vars stale Sar… en VPS) | reportado en brief; no verificable sin logs/VPS | MEDIO (1 auth fallida cada 6 s = worker ocupado) | Bajo | **[BLOQUEADO-ACCESO]** VPS + logs |
| 9 | mail.message: search_count global → 502; por mes: abr y jun también fallan (rangos grandes) | RPC 03/08 | (síntoma del #1/#2) | — | Evidencia |

## Escrituras por origen (proxy de RPC/h — sin logs de servidor no hay tabla exacta por IP)

| Origen (usuario RPC) | sale.order/24h | stock.move | mail.message | res.partner | ir.attachment | push.queue |
|---|---:|---:|---:|---:|---:|---:|
| **Trinidad Alfaro** (= conector marketplaces/Shopify VPS) | 849 | 1.643 | 7.034 | 807 | 764 | 849 |
| OdooBot (crons) | 3 | — | 2.005 | — | 365 | — |
| Gerardo (WMS/bodega) | — | — | 595 | — | — | — |
| ventas@unionx.cl | — | — | 264 | 1 | 190 | — |
| Martín | 10 | 24 | — | 10 | 606 | 9 |

Lectura: **~85% de la carga de escritura entra por la cuenta de la integración**. La tabla RPC/hora exacta por proceso requiere los logs de odoo-sh **[BLOQUEADO-ACCESO]**.

## Los dos caminos (punto 7)

**(a) Gratis (orden por impacto estimado en TTFB):**
1. Frenar la cascada por pedido del conector: no crear partner delivery nuevo por pedido (reutilizar por RUT/email o dirección en picking), bajar chatter/subscripciones automáticas en sale.order/stock.picking del conector (`mail_create_nosubscribe`, `tracking_disable` en context) → ataca #2 y #3 en la fuente.
2. Espaciar/consolidar crons custom: Yuju stock 1→5 min, sweep/sentinel/reconciliar Shopify 5-20→15-30 min fuera de horario pico, y revisar por qué yuju.webhook.record acumula 45.945 filas.
3. Limpieza con retención de mail.message/tracking/followers históricos de documentos de marketplace (> 6-12 meses) + attachments de chatter viejos. Baja el peso de cada INSERT/SELECT en las tablas más tocadas.
4. Merge PR #15 (corta el encolado push) + purga final de la cola con backup.
5. Matar el Access Denied c/6 s (vars stale del VPS).
**(b) Pagado:** dimensionar workers reales vs plan Odoo.sh contratado. **No cuantificable desde esta sesión** (falta odoo-sh: nº workers, RAM/CPU, plan actual). Con la firma de saturación observada, es probable que 1 worker extra compre mejora inmediata — pero cotizar recién después de medir el plan actual, y después del camino (a): pagar workers para sostener chatter basura es comprar síntoma.

**Recomendación:** primero (a).1-2 (baratos, atacan la fuente), medir 48 h, y con los datos de odoo-sh decidir si el plan actual va corto de verdad.

## Intervenciones ejecutadas 03/08/2026 ~13:00 UTC (con OK de Andrés)

**A) Crons espaciados** (registro en `data/outputs/odoo_crons_espaciados_20260803.json`, verificados por lectura posterior):

| Cron | Antes | Después |
|---|---|---|
| 115 Yuju Send Stock Webhooks | 1 min | **5 min** |
| 116 Yuju Process Price Webhooks | 6 min | **15 min** |
| 150 Shopify push stock | 5 min | **10 min** |
| 153 Shopify emisión OS Blue Express | 5 min | **10 min** |
| 151 Shopify sweep boletas (backstop) | 10 min | **30 min** |
| 149 Shopify reconciliar (backstop) | 20 min | **30 min** |
| 146 Factura 33 Corrector | 10 min | **30 min** |
| 154 LATAM Pass boletas | 10 min | **30 min** |
| 155 LATAM Pass canal despachos | 10 min | **30 min** |

NO tocado: 148 (procesar cola eventos Shopify = pipeline principal de pedidos, sigue en 5 min) ni crons core de Odoo. Reversa trivial: volver a escribir interval_number original.

**B) Purga unionx.push.queue**: 3.794 registros respaldados en `data/outputs/pwa_push_queue_backup_20260803.json` (2,11 MB) y purgados. Post-purga: count = 3 — **ya entraron 3 nuevos en minutos**, prueba viva de que sale_order.py sigue encolando: el leak se cierra recién con el PR #15.

**Después (misma hora, 3 muestras + login):** home 1,88 / 1,61 / 0,84 s · /web/login 0,61 s (antes: 5,9-21 s y hasta timeout 30 s). Cautela: una sola ventana de medición; validar en horario pico y por 48 h antes de declarar victoria.

## Pendiente / próximos pasos exactos

1. Conseguir en el entorno de Martín (o que me pase acceso): logs odoo-sh (requests >1 s, WorkerSanityCheck, el Access Denied c/6 s), plan/workers/límites, pg_stat_statements, top tablas por bytes.
2. Merge PR #15 en `unionx-cl/innovatek-sh` + revisar en ese repo: hook de sale_order.py que encola push, el código que crea partners por pedido, website_sale_search_unionx (override de búsqueda de /tienda — sospechoso directo de los 5,3 s del shop).
3. OKs pendientes de Martín/Andrés para ejecutar desde aquí (RPC): espaciar crons custom, purga push.queue con backup, limpieza de mensajería con retención.
4. Actualizar `sistemas/odoo/ESTADO.md` (unionx-app) — **no existe en este workspace**; el informe se genera aquí y debe copiarse/PR-earse desde el entorno que tenga ese repo.
