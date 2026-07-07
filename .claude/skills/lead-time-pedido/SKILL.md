---
name: lead-time-pedido
description: "Calcula hacia atrás las fechas de un pedido COMEX (fecha de orden, CRD, ETD, ETA Puerto) partiendo de una ETA Bodega objetivo, considerando lead time de producción por SKU. TRIGGERS: 'lead time pedido', 'cuándo debo ordenar', 'fecha límite pedido para llegar [FECHA]', o cuando el usuario da una ETA bodega objetivo y pregunta cuándo colocar la orden a Steven."
---

# Lead Time Pedido — Cálculo inverso desde ETA Bodega objetivo

Dado un **objetivo de llegada a bodega** (ETA WH), calcula hacia atrás toda la cadena
para determinar **cuándo hay que colocar el pedido** a Steven (Topwill).

## Cadena de fechas (inversa)

```
Fecha pedido = CRD − LT producción
CRD          = ETD − 7 días         (carga en puerto China)
ETD          = ETA Puerto − tránsito (SZ 52 / NB 45 días)
ETA Puerto   = ETA Bodega − 7 días  (desaduanaje + traslado)
```

### Parámetros vigentes (jul-2026)
| Tramo | Días |
|-------|------|
| Producción (LT por SKU; default si no hay dato) | **35** |
| CRD → ETD | 7 |
| ETD → ETA Puerto — Shenzhen | 52 |
| ETD → ETA Puerto — Ningbo | 45 |
| ETA Puerto → ETA Bodega | 7 |

**Totales referenciales pedido→bodega:** SZ ~101 días · NB ~94 días (con producción 35d).

> ⚠️ Si el usuario entrega otros tránsitos (ej: NB 42, bodega +5), usar los suyos y avisar.

## Regla clave: Compra vs Traer

El archivo de pedido trae dos situaciones distintas por SKU:

| Caso | Significado | ¿Aplica LT producción? |
|------|-------------|------------------------|
| **`Compra > 0`** | Hay que MANDAR A PRODUCIR | **SÍ** — fecha pedido = CRD − LT producción |
| **`Compra = 0` y `Traer > 0`** | Ya está fabricado, en bodega China (Rest items / stock Topwill) | **NO** — puede embarcar al siguiente CRD disponible; fecha pedido = solo confirmar carga |

Nunca aplicar lead time de producción a unidades que ya están listas en China — infla
la fecha de pedido ~5 semanas y adelanta compras innecesariamente.

## Lead time de producción por SKU

Prioridad de fuentes:
1. Columna `LT` / `Lead Time` en el archivo del pedido (días)
2. Historial del SKU (diferencia Order date → Finish Time en OHNSO/PIs anteriores)
3. Default **35 días** (avisar cuándo se usó el default)

Categorías con LT típicamente mayor (verificar con Steven): electrónica con PCB
(smartwatch, parlantes) ~45d; cerámica/loza ~40d; textil/bolsos ~30d.

## Cálculo

```python
from datetime import timedelta

TRANSITO = {'SZ': 52, 'NB': 45}
CRD_ETD = 7
PTO_BODEGA = 7
LT_DEFAULT = 35

def fechas_pedido(eta_bodega, puerto, lt_produccion=None, ya_producido=False):
    """Cadena inversa desde ETA bodega objetivo."""
    eta_puerto = eta_bodega - timedelta(days=PTO_BODEGA)
    etd = eta_puerto - timedelta(days=TRANSITO[puerto])
    crd = etd - timedelta(days=CRD_ETD)
    if ya_producido:          # Compra = 0, Traer > 0 → sin producción
        fecha_pedido = crd    # solo confirmar carga antes del CRD
    else:
        fecha_pedido = crd - timedelta(days=lt_produccion or LT_DEFAULT)
    return {'fecha_pedido': fecha_pedido, 'crd': crd, 'etd': etd,
            'eta_puerto': eta_puerto, 'eta_bodega': eta_bodega}
```

## Output

### Resumen en chat
```
🎯 ETA Bodega objetivo: [FECHA]

| Puerto | Fecha límite pedido | CRD | ETD | ETA Puerto | ETA Bodega |
|--------|--------------------:|-----|-----|-----------|-----------|
| SZ (producir, LT 35d) | 26-may | 30-jun | 07-jul | 28-ago | 04-sep |
| SZ (ya producido)     | 30-jun | 30-jun | 07-jul | 28-ago | 04-sep |
| NB (producir, LT 35d) | 02-jun | 07-jul | 14-jul | 28-ago | 04-sep |

⚠️ SKUs que ya NO llegan a la fecha objetivo: [lista con mejor ETA posible]
```

### Excel (si hay archivo de pedido)
Una fila por SKU con: SKU, Descripción, Compra, Traer, LT usado (y fuente), fecha
límite de pedido, CRD, ETD, ETA Puerto, ETA Bodega, y columna `¿Llega?` con semáforo
(verde llega / rojo no llega + mejor fecha alternativa).

## Validaciones
- Si la fecha límite de pedido ya pasó → alertar en rojo con la mejor ETA bodega alcanzable
  (hoy + LT + cadena) en vez de una fecha imposible
- Si el SKU no tiene puerto definido → asumir el del proveedor histórico y avisar
- Fechas límite que caen en fin de semana → adelantar al viernes anterior
