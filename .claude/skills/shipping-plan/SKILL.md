---
name: shipping-plan
description: "Asistente de comercio exterior para crear shipping plans de importación desde China. TRIGGERS: (1) 'Shipping plan [MES AÑO]' + 'Flete USD XXXX' cuando hay archivo OHNSO y archivo de Demanda/Payment Plan subidos - ejecuta cruce Demanda × Disponibilidad con 4 categorías (Embarcar, Pend.Confirmación, Faltante, Sobrante). (2) Solo OHNSO subido sin demanda - ejecuta plan basado solo en disponibilidad. (3) Cruce contra plan de carga de Steven (Plan B / OHNSO con secciones de embarque). El mes/año indica la columna de demanda a usar (ej: 'Transito JUL 26'). Procesa archivos OHNSO con hojas SHENZHEN y NINGBO."
---

# Shipping Plan v3 - Demanda × Disponibilidad × Plan de carga

Skill para crear planes de embarque basados en el **cruce entre demanda real y disponibilidad** (OHNSO), y para validar contra el **plan de carga de Steven** (secciones de embarque).

## Trigger de Activación

### Formato requerido
```
Shipping plan [MES AÑO]
Flete USD [MONTO]
```

**Ejemplos válidos:**
- "Shipping plan JUL 26, flete USD 3500"
- "Shipping plan Agosto 2026. Valor flete: USD 3200"
- "Flete USD 4000. Shipping plan Sep 26"

### Archivos requeridos (2)
1. `OHNSO_*.xls/xlsx` — Disponibilidad del proveedor (hojas SHENZHEN y NINGBO)
2. `Shipping*Plan*.xlsx` o `*Payment*Plan*.xlsx` o `Demanda*.xlsx` — Archivo con columna de demanda

### Comportamiento por modo
- **Con Demanda**: Ejecuta cruce Demanda × Disponibilidad (v2)
- **Solo OHNSO**: Ejecuta plan basado en disponibilidad total (v1 legacy)
- **Con plan de Steven** (OHNSO/Plan B con secciones "1.SZ-04,40HQ" etc.): cruce contra plan de carga

## ⚠️ REGLAS DE NEGOCIO CRÍTICAS (aprendidas jul-2026, NO omitir)

### 1. "Rest items" NO es plan de carga
En los planes de Steven (Plan B, OHNSO), la sección **"Rest items" es stock disponible SIN
embarque asignado**. NUNCA contarla como plan de carga ni computarla en "sobras".
Sí puede usarse como fuente para asignar demanda pendiente a embarques nuevos.

### 2. Consolidar demanda por SKU antes de cruzar
La demanda UnionX puede traer el **mismo SKU en varias filas por distintas OT (Order No)**.
Antes de cruzar contra Steven: agrupar por SKU y sumar unidades. Si no, se generan
falsas "sobras" (ej: SIMJULZOPO-30 con OTs de 300 y 400 aparecía sobrando 1.000).

### 3. Match por descripción cuando el SKU no calza
Steven a veces usa Model/descr. distinta al SKU UnionX (ej: `TCMULTSTY5N1-BG` = "HD4 Khaki").
Si un SKU no matchea, intentar por Model + descripción y **confirmar con el usuario** antes
de asumir equivalencia.

### 4. Embarques fijos vs modificables
Cuando un embarque ya está cerrado con Steven (ej: SZ-04, SZ-03-08, IMP OP ya confirmados),
**NO agregarle ítems**. Solo se puede sumar carga a embarques abiertos (623 en armado) o
crear embarques nuevos. Preguntar al usuario cuáles están fijos antes de asignar.

### 5. Capacidad y bin-packing
Máximo **68 CBM por contenedor 40HQ** (asumir 623 = 40HQ salvo indicación).
Al asignar demanda pendiente: best-fit decreciente (ítems grandes primero, al embarque
compatible con menor espacio libre suficiente). Respetar origen: ítems de sheet SHENZHEN
solo a embarques SZ-*, de NINGBO a NB-*/IMP OP.

### 6. El usuario edita el Excel a mano
El archivo de salida es un documento vivo que el usuario modifica en Excel. Antes de
re-procesar: releer el archivo real (no asumir el estado anterior), y usar formato
condicional (no fills duros) para que los colores sobrevivan a sus ediciones.

## Clasificación de Productos (4 Categorías)

| Categoría | Definición | Acción |
|-----------|------------|--------|
| ✅ **EMBARCAR** | Necesito + Disponible Ready | **Incluir en Shipping Plan** |
| ⏳ **PEND. CONFIRMACIÓN** | Necesito + En OHNSO pero con status checking/artwork/wait | **Alertar** (esperando confirmación) |
| ⚠️ **FALTANTE** | Necesito + NO está en OHNSO | **Alertar** (crítico) |
| ○ **SOBRANTE** | NO necesito + Disponible | **Excluir** del plan |

### Fórmula de Verificación
```
Demanda Total = Embarcar SZ + Embarcar NB + Pend. Confirmación + Faltante
```
**El total SIEMPRE debe cuadrar exactamente con la demanda.**

## Extracción de Parámetros

```python
import re

def extract_params(mensaje):
    """Extraer mes/año y flete del mensaje del usuario"""

    mes_map = {
        'ene': 'ENE', 'jan': 'ENE', 'enero': 'ENE',
        'feb': 'FEB', 'febrero': 'FEB',
        'mar': 'MAR', 'marzo': 'MAR',
        'abr': 'ABR', 'apr': 'ABR', 'abril': 'ABR',
        'may': 'MAY', 'mayo': 'MAY',
        'jun': 'JUN', 'junio': 'JUN',
        'jul': 'JUL', 'julio': 'JUL',
        'ago': 'AGO', 'aug': 'AGO', 'agosto': 'AGO',
        'sep': 'SEP', 'sept': 'SEP', 'septiembre': 'SEP',
        'oct': 'OCT', 'octubre': 'OCT',
        'nov': 'NOV', 'noviembre': 'NOV',
        'dic': 'DIC', 'dec': 'DIC', 'diciembre': 'DIC'
    }

    match = re.search(r'(\w+)\s*[/-]?\s*(20)?(\d{2})\b', mensaje, re.IGNORECASE)
    if match:
        mes_raw = match.group(1).lower()
        año = match.group(3)
        mes = mes_map.get(mes_raw, mes_raw.upper()[:3])
        columna_demanda = f"Transito {mes} {año}"
    else:
        columna_demanda = None

    # Extraer flete (default: 3700 USD por 40HQ)
    match_flete = re.search(r'USD\s*[\$]?\s*([\d,\.]+)', mensaje, re.IGNORECASE)
    tarifa_flete = float(match_flete.group(1).replace(',', '')) if match_flete else 3700

    return columna_demanda, tarifa_flete
```

## Parser del plan de Steven (secciones de embarque)

Los planes de Steven (Plan B, OHNSO) traen los ítems agrupados bajo separadores
numerados: `1.SZ-04,40HQ`, `2.SZ-03-08,40HQ`, `3.Rest items`, etc.
**Usar el módulo compartido** `parser_plan_steven.py` (raíz del proyecto) — no
reimplementar el parseo. Expone `parsear_plan(path, sheet)` y el catálogo
`EMBARQUES` con tránsitos.

## Lógica de Clasificación

```python
def clasificar_demanda(df_demanda, df_ohnso_sz, df_ohnso_nb, demanda_col):
    """
    Clasificar cada SKU en 4 categorías.
    Prioridad: Ready SZ → Ready NB → Pendiente → Faltante
    IMPORTANTE: df_demanda debe venir YA CONSOLIDADO por SKU (regla 2).
    """

    exclude_patterns = ['checking', 'cancel', '等确认', 'artwork', 'wait']

    def is_excluded(ft):
        return any(p in str(ft).lower() for p in exclude_patterns)

    df_sz_ready = df_ohnso_sz[~df_ohnso_sz['Finish Time'].apply(is_excluded)]
    df_nb_ready = df_ohnso_nb[~df_ohnso_nb['Finish Time'].apply(is_excluded)]
    df_sz_pend = df_ohnso_sz[df_ohnso_sz['Finish Time'].apply(is_excluded)]
    df_nb_pend = df_ohnso_nb[df_ohnso_nb['Finish Time'].apply(is_excluded)]

    disp_sz_ready = df_sz_ready.groupby('SKU')['Qty'].sum()
    disp_nb_ready = df_nb_ready.groupby('SKU')['Qty'].sum()
    disp_sz_pend = df_sz_pend.groupby('SKU')['Qty'].sum()
    disp_nb_pend = df_nb_pend.groupby('SKU')['Qty'].sum()

    clasificacion = []
    for _, row in df_demanda[df_demanda[demanda_col] > 0].iterrows():
        sku = row['Sku']
        demanda = row[demanda_col]

        ready_sz = disp_sz_ready.get(sku, 0)
        ready_nb = disp_nb_ready.get(sku, 0)
        pend_total = disp_sz_pend.get(sku, 0) + disp_nb_pend.get(sku, 0)

        restante = demanda
        tomar_sz = min(restante, ready_sz); restante -= tomar_sz
        tomar_nb = min(restante, ready_nb); restante -= tomar_nb
        tomar_pend = min(restante, pend_total); restante -= tomar_pend
        faltante = restante

        clasificacion.append({
            'SKU': sku, 'Demanda': demanda,
            'Embarcar_SZ': tomar_sz, 'Embarcar_NB': tomar_nb,
            'Pend_Conf': tomar_pend, 'Faltante': faltante
        })

    return pd.DataFrame(clasificacion)
```

## Parámetros de Negocio

### Costos de Flete
| Parámetro | Valor |
|-----------|-------|
| Tarifa 40HQ | Del trigger (default USD 3,700) |
| Capacidad 40HQ | 68 CBM |
| Ocupación objetivo | ≥95% |

### Umbrales de Rentabilidad
| Puerto | Umbral Flete % |
|--------|---------------|
| Shenzhen (SZ) | ≤5% |
| Ningbo (NB) | ≤7% |

### Tiempos de Tránsito (vigentes jul-2026 — cadena completa)
| Tramo | Días |
|-------|------|
| CRD → ETD (carga en puerto China) | +7 |
| ETD → ETA Puerto Chile — **Shenzhen** | +52 |
| ETD → ETA Puerto Chile — **Ningbo** | +45 |
| ETA Puerto → ETA Bodega (desaduanaje + traslado) | +7 |

> Total referencial CRD→Bodega: **SZ ~66 días · NB ~59 días**.
> ⚠️ Estos parámetros se recalibran con datos reales de Seimex; si el usuario da
> otros valores (ej: NB 42 / bodega +5), usar los del usuario y avisar la diferencia.
> CRD de un embarque = **MAX(Finish Time)** de sus ítems.

### Fórmula de Sobrecosto
```
Costo Total = Valor FOB × 1.05 (inland China aprox.) + Flete
Sobrecosto % = Flete / Costo Total × 100
```
(Para costeo fino de inland China usar la skill `comex-workflow`, que lo desglosa.)

## Valores de Finish Time

| Valor | Interpretación | Categoría |
|-------|----------------|-----------|
| `Ready` / `Reday` | Listo | ✅ EMBARCAR |
| Fecha válida | CRD específico | ✅ EMBARCAR |
| `checking artwork` | Pendiente diseño | ⏳ PEND. CONF |
| `等确认...` | Pendiente confirmación | ⏳ PEND. CONF |
| `wait` | Esperando | ⏳ PEND. CONF |
| `cancel` | Cancelado | ⏳ PEND. CONF |
| No aparece en OHNSO | No disponible | ⚠️ FALTANTE |

## Output

### 1. Resumen en Chat

```
📦 SHIPPING PLAN v3 - [MES AÑO]
Flete 40HQ: USD [MONTO]
================================

📊 CLASIFICACIÓN:
   ✅ Shipping Plan SZ: XX,XXX (XX.X%)
   ✅ Shipping Plan NB: X,XXX (XX.X%)
   ⏳ Pend. Confirmación: X,XXX (X.X%)
   ⚠️ Faltante: X,XXX (XX.X%)
   ─────────────────────────
   📦 DEMANDA TOTAL: XX,XXX (100%)
   ✓ CHECK: 0 (cuadra)

📦 CONTENEDORES:

SHENZHEN (N contenedores)
| Cont# | CRD        | ETD        | ETA Puerto | ETA Bodega | CBM  | Ocup% | Valor USD | Flete% | SKUs | Unidades |
|-------|------------|------------|------------|------------|------|-------|-----------|--------|------|----------|
| SZ-01 | 2026-04-05 | 2026-04-12 | 2026-06-03 | 2026-06-10 | 67.9 | 99.8% | $63,520   | 5.0%   | 50   | 8,234    |
```

### 2. Excel Detallado

| Hoja | Contenido |
|------|-----------|
| **Resumen** | Clasificación completa + verificación matemática + bloque por embarque con fórmulas SUMIFS/COUNTIFS |
| **Plan_SZ / Plan_NB** | Contenedores con CRD, ETD, ETA Puerto, ETA Bodega, métricas |
| **Detalle_SZ / Detalle_NB** | Productos por contenedor (Demanda vs Embarcado) |
| **Pend_Confirmacion** | SKUs con status checking/artwork/wait |
| **Faltantes** | SKUs NO disponibles en OHNSO |

**Convenciones del Excel de salida:**
- Columnas de cruce: `Cantidad cargada`, `Embarque (Steven)`, `CRD`, `ETD`, `ETA Puerto`, `ETA Bodega`
- **Formato condicional** (no fill duro) sobre `Cantidad cargada`: verde =demanda / azul >demanda (sobra) / rojo <demanda (falta) / gris vacío — sobrevive a ediciones manuales
- Resumen con fórmulas `SUMIFS`/`COUNTIFS` referenciando las hojas Detail (se recalcula solo). El match por prefijo `LEFT(nombre;5)&"*"` absorbe variantes de escritura ("SZ-01(623)" vs "SZ-01 (623)")
- Ítems movidos desde Faltantes/Missing: marcar `Order No = "MISSING→OHNSO"` + fondo naranja (trazabilidad)
- Sin autofiltros fijos ni filas ocultas al guardar (verificar antes de entregar)

## Manejo de errores
- Columna `Transito [MES] [AÑO]` no existe en la demanda → listar columnas disponibles y preguntar
- SKU duplicado por OT → consolidar (regla 2), nunca fallar
- Archivo abierto en Excel (PermissionError al guardar) → pedir al usuario cerrarlo y reintentar
- Hoja SHENZHEN/NINGBO ausente en OHNSO → alertar y continuar con la disponible

## Ejemplo de Uso

**Usuario:**
```
Shipping plan JUL 26
Flete USD 3500
```
(Con OHNSO_Mar__28th.xls y Shipping_Payment_Plan_July.xlsx subidos)

**Claude:**
1. Detecta "JUL 26" → columna = "Transito JUL 26"
2. Extrae flete = $3,500 USD
3. Lee OHNSO (SHENZHEN + NINGBO)
4. Lee Demanda, valida columna existe, **consolida por SKU**
5. Clasifica cada SKU en 4 categorías (excluyendo Rest items como plan)
6. Genera plan solo con productos Ready
7. Alerta Pend. Confirmación y Faltantes
8. Verifica: Total = Demanda (diferencia = 0)
9. Genera Excel con todas las hojas y fórmulas dinámicas
