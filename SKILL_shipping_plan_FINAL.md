---
name: shipping-plan
description: "Asistente de comercio exterior para crear shipping plans de importación desde China. TRIGGERS: (1) 'Shipping plan [MES AÑO]' + 'Flete USD XXXX' cuando hay archivo OHNSO y archivo de Demanda/Payment Plan subidos - ejecuta cruce Demanda × Disponibilidad con 4 categorías (Embarcar, Pend.Confirmación, Faltante, Sobrante). (2) Solo OHNSO subido sin demanda - ejecuta plan basado solo en disponibilidad. El mes/año indica la columna de demanda a usar (ej: 'Transito JUL 26'). Procesa archivos OHNSO con hojas SHENZHEN y NINGBO."
---

# Shipping Plan v2 - Demanda × Disponibilidad

Skill para crear planes de embarque basados en el **cruce entre demanda real y disponibilidad** (OHNSO).

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
    
    # Mapeo de meses
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
    
    # Buscar mes + año → genera columna "Transito JUL 26"
    match = re.search(r'(\w+)\s*[/-]?\s*(20)?(\d{2})\b', mensaje, re.IGNORECASE)
    if match:
        mes_raw = match.group(1).lower()
        año = match.group(3)
        mes = mes_map.get(mes_raw, mes_raw.upper()[:3])
        columna_demanda = f"Transito {mes} {año}"
    else:
        columna_demanda = None
    
    # Extraer flete (default: 3700)
    match_flete = re.search(r'USD\s*[\$]?\s*([\d,\.]+)', mensaje, re.IGNORECASE)
    tarifa_flete = float(match_flete.group(1).replace(',', '')) if match_flete else 3700
    
    return columna_demanda, tarifa_flete
```

## Lógica de Clasificación

```python
def clasificar_demanda(df_demanda, df_ohnso_sz, df_ohnso_nb, demanda_col):
    """
    Clasificar cada SKU en 4 categorías.
    Prioridad: Ready SZ → Ready NB → Pendiente → Faltante
    """
    
    exclude_patterns = ['checking', 'cancel', '等确认', 'artwork', 'wait']
    
    def is_excluded(ft):
        return any(p in str(ft).lower() for p in exclude_patterns)
    
    # Separar Ready vs Pendiente
    df_sz_ready = df_ohnso_sz[~df_ohnso_sz['Finish Time'].apply(is_excluded)]
    df_nb_ready = df_ohnso_nb[~df_ohnso_nb['Finish Time'].apply(is_excluded)]
    df_sz_pend = df_ohnso_sz[df_ohnso_sz['Finish Time'].apply(is_excluded)]
    df_nb_pend = df_ohnso_nb[df_ohnso_nb['Finish Time'].apply(is_excluded)]
    
    # Disponibilidad por SKU
    disp_sz_ready = df_sz_ready.groupby('SKU')['Qty'].sum()
    disp_nb_ready = df_nb_ready.groupby('SKU')['Qty'].sum()
    disp_sz_pend = df_sz_pend.groupby('SKU')['Qty'].sum()
    disp_nb_pend = df_nb_pend.groupby('SKU')['Qty'].sum()
    
    clasificacion = []
    for _, row in df_demanda[df_demanda[demanda_col] > 0].iterrows():
        sku = row['Sku']
        demanda = row[demanda_col]
        
        # Disponibilidad
        ready_sz = disp_sz_ready.get(sku, 0)
        ready_nb = disp_nb_ready.get(sku, 0)
        pend_total = disp_sz_pend.get(sku, 0) + disp_nb_pend.get(sku, 0)
        
        restante = demanda
        
        # 1. Tomar de Ready SZ
        tomar_sz = min(restante, ready_sz)
        restante -= tomar_sz
        
        # 2. Tomar de Ready NB
        tomar_nb = min(restante, ready_nb)
        restante -= tomar_nb
        
        # 3. Pendiente confirmación
        tomar_pend = min(restante, pend_total)
        restante -= tomar_pend
        
        # 4. Faltante
        faltante = restante
        
        clasificacion.append({
            'SKU': sku,
            'Demanda': demanda,
            'Embarcar_SZ': tomar_sz,
            'Embarcar_NB': tomar_nb,
            'Pend_Conf': tomar_pend,
            'Faltante': faltante
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

### Tiempos de Tránsito
| Puerto | Días desde CRD |
|--------|----------------|
| Shenzhen | CRD + 62 días |
| Ningbo | CRD + 52 días |

### Fórmula de Sobrecosto
```
Costo Total = Valor FOB × 1.05 (inland China) + Flete
Sobrecosto % = Flete / Costo Total × 100
```

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
📦 SHIPPING PLAN v2 - [MES AÑO]
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
| Cont# | CRD        | ETA        | CBM  | Ocup% | Valor USD | Flete% | SKUs | Unidades |
|-------|------------|------------|------|-------|-----------|--------|------|----------|
| SZ-01 | 2026-04-05 | 2026-06-06 | 67.9 | 99.8% | $63,520   | 5.0%   | 50   | 8,234    |

NINGBO (M contenedores)
| Cont# | CRD        | ETA        | CBM  | Ocup% | Valor USD | Flete% | SKUs | Unidades |
|-------|------------|------------|------|-------|-----------|--------|------|----------|
| NB-01 | 2026-04-20 | 2026-06-11 | 67.1 | 98.6% | $16,727   | 16.6%  | 9    | 1,523    |
```

### 2. Excel Detallado

| Hoja | Contenido |
|------|-----------|
| **Resumen** | Clasificación completa + verificación matemática |
| **Plan_SZ** | Contenedores SZ con CRD, ETA, métricas |
| **Plan_NB** | Contenedores NB con CRD, ETA, métricas |
| **Detalle_SZ** | Productos por contenedor (Demanda vs Embarcado) |
| **Detalle_NB** | Productos por contenedor (Demanda vs Embarcado) |
| **Pend_Confirmacion** | SKUs con status checking/artwork/wait |
| **Faltantes** | SKUs NO disponibles en OHNSO |

## Estructura de Archivos Input

### OHNSO (Disponibilidad)
Columnas clave:
- `SKU` — Código del producto
- `Model` — Modelo
- `DESCRIPTON` — Descripción
- `Qty` — Cantidad disponible
- `AMOUNT (USD)` — Valor total
- `TOTAL CBM` — Volumen
- `Finish Time` — Fecha CRD o status

### Demanda (Shipping/Payment Plan)
Columnas clave:
- `Sku` — Código del producto
- `Descripcion` — Nombre
- `Transito [MES] [AÑO]` — Cantidad requerida
- `COSTO USD` — Precio unitario (opcional)
- `Marca` — Marca (opcional)

## Limitación a Demanda

**Regla crítica**: Nunca embarcar más de lo que se necesita.

```python
def limitar_a_demanda(df_ohnso, clasificacion, col_embarcar):
    """
    Tomar del OHNSO solo la cantidad clasificada para embarcar.
    Priorizar por CRD más temprano.
    """
    embarcar_dict = clasificacion.set_index('SKU')[col_embarcar].to_dict()
    
    resultado = []
    for sku, qty_embarcar in embarcar_dict.items():
        if qty_embarcar <= 0:
            continue
        
        sku_rows = df_ohnso[df_ohnso['SKU'] == sku].sort_values('CRD')
        qty_acum = 0
        
        for _, row in sku_rows.iterrows():
            if qty_acum >= qty_embarcar:
                break
            
            qty_tomar = min(row['Qty'], qty_embarcar - qty_acum)
            proporcion = qty_tomar / row['Qty']
            
            resultado.append({
                'SKU': sku,
                'Qty_Tomada': qty_tomar,
                'CBM': row['CBM'] * proporcion,
                'Amount': row['Amount'] * proporcion,
                'CRD': row['CRD']
            })
            qty_acum += qty_tomar
    
    return pd.DataFrame(resultado)
```

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
4. Lee Demanda, valida columna existe
5. Clasifica cada SKU en 4 categorías
6. Genera plan solo con productos Ready
7. Alerta Pend. Confirmación y Faltantes
8. Verifica: Total = Demanda (diferencia = 0)
9. Genera Excel con todas las hojas

**Resultado esperado:**
```
📊 CLASIFICACIÓN:
   ✅ Shipping Plan SZ: 30,477 (64.0%)
   ✅ Shipping Plan NB: 4,995 (10.5%)
   ⏳ Pend. Confirmación: 3,730 (7.8%)
   ⚠️ Faltante: 8,385 (17.6%)
   ─────────────────────────
   📦 DEMANDA TOTAL: 47,587 (100%)
   ✓ CHECK: 0 ✅
```
