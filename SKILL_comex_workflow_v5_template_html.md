---
name: comex-workflow
description: "Flujo completo de costeo de importaciones desde China. TRIGGERS: 'Costear embarque', 'Nuevo embarque', 'Procesar PI', 'Costeo COMEX'. Usuario sube 3 archivos: PI (Proforma Invoice), PL (Packing List), y Tarifas (flete + gastos Chile). Claude genera Pre-costeo x CBM, actualiza Maestra Importaciones CON TODAS LAS PESTAÑAS, y crea borrador de email en Gmail."
---

# COMEX Workflow - Costeo de Importaciones

Skill para automatizar el flujo completo de costeo de importaciones desde China.

## Trigger de Activación

**Frases que activan esta skill:**
- "Costear embarque"
- "Nuevo embarque"
- "Procesar PI"
- "Costeo COMEX"
- "Actualizar maestra con PI"

**Archivos que el usuario debe subir (3):**
1. **PI** (Proforma Invoice) - Excel del proveedor con precios y gastos Inland China
2. **PL** (Packing List) - Excel del proveedor con CBM
3. **Tarifas_COMEX.xlsx** - Solo flete marítimo y gastos Inland Chile

---

## FLUJO DE EJECUCIÓN

```
┌──────────────────────────────────────────────────────────────────────┐
│  PASO 1: LEER ARCHIVOS + VALIDAR CONCEPTOS                           │
│  • Extraer número de embarque del PI                                 │
│  • Extraer productos: Model, SKU, Qty, Price, Gift box, Delivery     │
│  • Extraer gastos Inland China del PI                                │
│  • Extraer CBM del PL                                                │
│  • ⚠️ ALERTAR si hay conceptos no reconocidos en PI/PL              │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PASO 2: CALCULAR PRE-COSTEO x CBM                                   │
│  • Aplicar fórmulas de costeo (ver sección FÓRMULAS)                 │
│  • Calcular sobrecosto sobre P×Q                                     │
│  • Generar Pre-costeo_x_CBM_[EMBARQUE].xlsx                          │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PASO 3: ACTUALIZAR MAESTRA IMPORTACIONES                            │
│  • Agregar filas a pestaña "Maestra"                                 │
│  • Actualizar "1. Apertura CC" con resumen del embarque              │
│  • Actualizar "4. Matriz SKU" con costos por SKU                     │
│  • Actualizar "5. Resumen Variaciones"                               │
│  • Calcular variación vs ÚLTIMO costo internado por SKU              │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PASO 4: CREAR BORRADOR EMAIL                                        │
│  • Eficiencia vs benchmark (últimos 6 meses)                         │
│  • Productos con variación >10% vs ÚLTIMO costo                      │
│  • Análisis de causas                                                │
└──────────────────────────────────────────────────────────────────────┘
```

---

## ⚠️ VALIDACIÓN DE CONCEPTOS (PASO 1)

Antes de procesar, Claude debe verificar que todos los conceptos en PI y PL son reconocidos.

### Conceptos RECONOCIDOS en PI:
- Productos con: No, Model, DESCRIPTON, QTY, Price, AMOUNT, Gift box, SKU
- Filas de "delivery cost" después de cada producto
- Gastos Inland China al final:
  - "FF" o "Form F"
  - "local charge" o "storage"
  - "long vehicle" o "cleaning custom"
  - "Steven" o "3%" o "comisión"

### Conceptos RECONOCIDOS en PL:
- No, Model, DESCRIPTON, Total Packages, Q'ty/ctn, Total q'ty
- G.w., N.W., Total(kg)
- CTN Size, CBM/CTN, TOTAL CBM

### Si hay conceptos NO RECONOCIDOS:
```
⚠️ ALERTA: Se encontraron conceptos no reconocidos en el PI/PL:

PI línea 45: "Inspection fee" - $150 USD
PI línea 47: "Special packaging" - $200 USD
PL línea 12: "Palletizing" - $80 USD

Estos conceptos no están documentados en la skill. Por favor revisar:
1. ¿Deben incluirse en el costo? ¿En qué centro de costo?
2. ¿Se prorratea por valor, por CBM, o es fijo por producto?

Esperando confirmación antes de continuar...
```

---

## FÓRMULAS DE CÁLCULO (CORREGIDAS)

### 1. Delivery Cost (PRORRATEADO por grupo de Model)

**CRÍTICO:** El delivery cost en el PI aparece DESPUÉS de un grupo de productos con el mismo Model. Debe prorratearse entre todos los productos de ese grupo por cantidad.

```python
def procesar_pi_con_delivery_prorrateado(df):
    """
    El delivery cost aplica al GRUPO de productos anteriores con el mismo Model.
    Se prorrata por cantidad (Qty) entre todas las variantes.
    
    Ejemplo en PI:
        Fila 37: TPB02 - Botella Negra    - Qty: 154
        Fila 38: TPB02 - Botella Pink     - Qty: 100
        Fila 39: TPB02 - Botella Blanca   - Qty: 150
        Fila 40: delivery cost            - $43
        
    El $43 se prorrata entre las 3 filas:
        Total Qty grupo = 154 + 100 + 150 = 404
        Delivery unitario = $43 / 404 = $0.1064
        
        Botella Negra:  $0.1064 × 154 = $16.39
        Botella Pink:   $0.1064 × 100 = $10.64
        Botella Blanca: $0.1064 × 150 = $15.97
        Total: $43.00 ✓
    """
    
    productos = []
    grupo_actual = []
    model_actual = None
    
    for i, row in df.iterrows():
        model = str(row.get('Model', '')).strip()
        desc = str(row.get('DESCRIPTON', '')).strip().lower()
        qty = pd.to_numeric(row.get('QTY(PCS)', 0), errors='coerce') or 0
        
        # Detectar si es delivery cost
        if 'delivery' in desc:
            delivery_amount = row.get('AMOUNT', row.get('Price', 0))
            
            # Asignar delivery al grupo anterior
            if grupo_actual:
                total_qty_grupo = sum(p['qty'] for p in grupo_actual)
                for p in grupo_actual:
                    # Prorratear por cantidad
                    p['delivery'] = delivery_amount * (p['qty'] / total_qty_grupo)
                    p['delivery_unitario'] = delivery_amount / total_qty_grupo
                
                productos.extend(grupo_actual)
                grupo_actual = []
            continue
        
        # Si es un producto válido
        if model and model != 'nan' and qty > 0:
            # Si cambió el modelo, cerrar grupo anterior
            if model_actual and model != model_actual and grupo_actual:
                productos.extend(grupo_actual)
                grupo_actual = []
            
            model_actual = model
            grupo_actual.append({
                'model': model,
                'qty': qty,
                'price': row.get('Price', 0),
                'gift_box': row.get('Gift box', 0),
                'sku': row.get('SKU', ''),
                'delivery': 0,  # Se llenará cuando aparezca delivery cost
                'delivery_unitario': 0
            })
    
    # Agregar último grupo si quedó algo
    if grupo_actual:
        productos.extend(grupo_actual)
    
    return pd.DataFrame(productos)
```

**⚠️ ERROR COMÚN:** Asignar el delivery cost completo a cada producto individual en lugar de prorratearlo entre el grupo.

### 2. Gift Box (con 3% adicional)

```python
# La gift box lleva un 3% adicional sobre el valor especificado en PI
gift_box_pi = valor_en_PI  # Lo que dice el PI
gift_box_real = gift_box_pi * 1.03  # Agregar 3%
```

### 2. Comisión Steven (3%)

```python
# La comisión de Steven es 3% sobre:
# (Total compra + Costo traslado + Local charge + Long vehicle)

base_comision = (
    total_amount_PxQ +      # Suma de todos los P×Q
    sum(delivery_cost) +     # Todos los delivery costs
    local_charge +           # Local charge storage
    long_vehicle             # Long vehicle + customs cleaning
)

comision_steven = base_comision * 0.03
```

**IMPORTANTE:** La comisión Steven NO incluye Form F en su base de cálculo.

### 3. Centros de Costo

```python
# CC1: EXW (Gift Box + Delivery)
cc_exw = sum(gift_box_real) + sum(delivery_cost)
# Donde gift_box_real = gift_box_PI × 1.03

# CC2: Inland China
# Extraer del PI (ya vienen calculados, excepto comisión Steven que se recalcula)
local_charge = buscar_en_PI("local charge")
long_vehicle = buscar_en_PI("long vehicle")
form_f = buscar_en_PI("FF")

# Recalcular comisión Steven con la base correcta
base_steven = total_amount + sum(delivery_cost) + local_charge + long_vehicle
comision_steven = base_steven * 0.03

cc_inland_china = comision_steven + local_charge + long_vehicle + form_f

# CC3: Flete (prorrateado por CBM)
cc_flete = tarifas['flete_total']

# CC4: Inland Chile
total_cif = total_amount + cc_exw + cc_inland_china + cc_flete
agente_aduana = total_cif * 0.0016
gastos_chile_clp = sum(todos_los_gastos_chile)
cc_inland_chile = agente_aduana + (gastos_chile_clp / dolar)
```

### 4. Sobrecosto

```python
# Sobrecosto = todos los CC sobre P×Q (sin extras)
total_amount = sum(qty * price)  # Base: P×Q puro

sobrecosto_total = cc_exw + cc_inland_china + cc_flete + cc_inland_chile
sobrecosto_pct = (sobrecosto_total / total_amount) * 100
```

### 5. Costo Internado por Producto

```python
# Por producto, prorrateado por CBM
pct_cbm = producto_cbm / total_cbm

# Costos por producto
exw_producto = (qty * price) + gift_box_real + delivery_cost
inland_china_producto = cc_inland_china * (exw_producto / total_exw)
flete_producto = cc_flete * pct_cbm
cif_producto = exw_producto + inland_china_producto + flete_producto

# Gastos Chile por producto (prorrateados por CBM)
agente_producto = (total_cif * 0.0016) * pct_cbm * dolar
gastos_chile_producto = gastos_chile_clp * pct_cbm

costo_internado_total = (cif_producto * dolar) + agente_producto + gastos_chile_producto
costo_internado_unit = costo_internado_total / qty
```

---

## COMPARACIÓN DE PRODUCTOS (vs ÚLTIMO COSTO)

```python
# Comparar contra el ÚLTIMO costo internado, NO el promedio

for producto in embarque_actual:
    sku = producto['SKU']
    
    # Buscar el ÚLTIMO registro de este SKU en la Maestra
    historico = maestra[maestra['SKU'] == sku].sort_values('ETA', ascending=False)
    
    if len(historico) > 0:
        ultimo_costo = historico.iloc[0]['Costo Neto Unitario']
        ultimo_embarque = historico.iloc[0]['N° Embarque']
        
        variacion_pct = ((producto['Costo_Internado'] - ultimo_costo) / ultimo_costo) * 100
        
        if abs(variacion_pct) > 10:
            productos_variacion.append({
                'model': producto['Model'],
                'sku': sku,
                'costo_actual': producto['Costo_Internado'],
                'ultimo_costo': ultimo_costo,
                'ultimo_embarque': ultimo_embarque,
                'variacion': variacion_pct
            })
    else:
        # Producto nuevo, sin histórico
        productos_nuevos.append(producto)
```

---

## ACTUALIZACIÓN DE PESTAÑAS DE LA MAESTRA

### Pestaña "Maestra" (principal)
Agregar filas con el formato estándar, resaltadas en color.

### Pestaña "1. Apertura CC"
Agregar fila con resumen del embarque:
| N° Embarque | Puerto | Año | ETA | # SKUs | Costo Unit | Inland China | Costo FOB | Flete | Costo CIF | Inland Chile | Costo Internado | Overcost % |

```python
nueva_fila_apertura = {
    'N° Embarque': embarque,
    'Puerto': puerto,
    'Año': 2026,
    'ETA': fecha_eta,
    '# SKUs': len(productos),
    'Costo Unit': total_amount,
    'Inland China': cc_inland_china,
    'Costo FOB': total_amount + cc_exw + cc_inland_china,
    'Flete': cc_flete,
    'Costo CIF': total_cif,
    'Inland Chile': cc_inland_chile,
    'Costo Internado': total_internado_clp,
    'Overcost %': sobrecosto_pct
}
```

### Pestaña "4. Matriz SKU"
Agregar columna con el nuevo embarque mostrando Costo Neto Unitario por SKU:

```
| SKU | ... | 25TP1024 | 26TP0126 | 26TP0129 | 26TP0202 |  <- NUEVA COLUMNA
|-----|-----|----------|----------|----------|----------|
| ABC | ... | $5,200   | $5,350   | -        | $5,180   |
| DEF | ... | $12,100  | -        | $12,500  | $12,300  |
```

### Pestaña "5. Resumen Variaciones"
Actualizar el análisis de SKUs con mayor variación en los últimos 4 meses:

```python
# Recalcular top SKUs con mayor variación
fecha_4m = fecha_actual - timedelta(days=120)
df_reciente = maestra[maestra['ETA'] >= fecha_4m]

# Agrupar por SKU y calcular variación máxima
variaciones = []
for sku in df_reciente['SKU'].unique():
    datos_sku = df_reciente[df_reciente['SKU'] == sku].sort_values('ETA')
    if len(datos_sku) > 1:
        primer_costo = datos_sku.iloc[0]['Costo Neto Unitario']
        ultimo_costo = datos_sku.iloc[-1]['Costo Neto Unitario']
        variacion = ((ultimo_costo - primer_costo) / primer_costo) * 100
        variaciones.append({
            'SKU': sku,
            'Variación': variacion,
            'Primer Costo': primer_costo,
            'Último Costo': ultimo_costo
        })

# Ordenar por variación absoluta y tomar top 20
top_variaciones = sorted(variaciones, key=lambda x: abs(x['Variación']), reverse=True)[:20]
```

---

## CONTENIDO DEL EMAIL (HTML)

### Subject del Email:
```
[EMBARQUE] Análisis de Costeo - [PUERTO] - X.XX% (N productos con variación significativa)
```

### Template HTML Completo:

```html
<div dir="ltr">
<div style="font-family:Arial,sans-serif;line-height:1.6;color:#333;max-width:800px;margin:0 auto">

<!-- HEADER: Título con emoji y puerto -->
<h2 style="color:#1a5276;border-bottom:2px solid #1a5276;padding-bottom:10px">📦 Análisis Embarque {EMBARQUE} | {PUERTO_CODIGO} ({PUERTO_NOMBRE})</h2>

<!-- INDICADOR DE SOBRECOSTO: Verde si bajo benchmark, Rojo si sobre benchmark -->
<!-- Si BAJO benchmark (bueno): background:#d5f5e3, color:#1e8449, símbolo ✓ -->
<!-- Si SOBRE benchmark (malo): background:#fadbd8, color:#c0392b, símbolo ⚠️ -->
<table style="width:100%;background:{COLOR_FONDO_INDICADOR};border-radius:8px;margin:20px 0">
<tbody><tr>
<td style="padding:20px;text-align:center">
<span style="font-size:28px;font-weight:bold;color:{COLOR_TEXTO_INDICADOR}">{SIMBOLO} Sobrecosto: {SOBRECOSTO_PCT}%</span>
</td>
</tr>
</tbody></table>

<!-- TEXTO BENCHMARK -->
<p style="font-size:16px">Embarque <b>{DIFERENCIA_PP} pp por {DIRECCION}</b> del benchmark de {PUERTO_CODIGO} ({BENCHMARK_PCT}% promedio últimos 6 meses).</p>

<!-- SECCIÓN 1: DESGLOSE DE CENTROS DE COSTO -->
<h3 style="color:#1a5276;margin-top:30px">1. Desglose de Centros de Costo</h3>

<table style="width:100%;border-collapse:collapse;margin:15px 0">
<tbody><tr style="background:#1a5276;color:white">
<th style="padding:12px;text-align:left;border:1px solid #ddd">Centro de Costo</th>
<th style="padding:12px;text-align:right;border:1px solid #ddd">USD</th>
<th style="padding:12px;text-align:right;border:1px solid #ddd">% sobre P×Q</th>
</tr>
<tr style="background:#f8f9fa">
<td style="padding:10px;border:1px solid #ddd">Total Amount (P×Q)</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">${TOTAL_PXQ}</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">Base</td>
</tr>
<tr>
<td style="padding:10px;border:1px solid #ddd">EXW (Gift Box + Delivery)</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">${CC_EXW}</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">{CC_EXW_PCT}%</td>
</tr>
<tr style="background:#f8f9fa">
<td style="padding:10px;border:1px solid #ddd">Inland China</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">${CC_INLAND_CHINA}</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">{CC_INLAND_CHINA_PCT}%</td>
</tr>
<tr>
<td style="padding:10px;border:1px solid #ddd">Flete Marítimo</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">${CC_FLETE}</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">{CC_FLETE_PCT}%</td>
</tr>
<tr style="background:#f8f9fa">
<td style="padding:10px;border:1px solid #ddd">Inland Chile</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">${CC_INLAND_CHILE}</td>
<td style="padding:10px;text-align:right;border:1px solid #ddd">{CC_INLAND_CHILE_PCT}%</td>
</tr>
<tr style="background:#1a5276;color:white;font-weight:bold">
<td style="padding:12px;border:1px solid #ddd">TOTAL SOBRECOSTO</td>
<td style="padding:12px;text-align:right;border:1px solid #ddd">${SOBRECOSTO_USD}</td>
<td style="padding:12px;text-align:right;border:1px solid #ddd">{SOBRECOSTO_PCT}%</td>
</tr>
</tbody></table>

<!-- TABLA BENCHMARK -->
<table style="width:100%;border-collapse:collapse;margin:15px 0">
<tbody><tr style="background:#2c3e50;color:white">
<th style="padding:10px;border:1px solid #ddd">Puerto</th>
<th style="padding:10px;border:1px solid #ddd">Benchmark 6m</th>
<th style="padding:10px;border:1px solid #ddd">Este Embarque</th>
<th style="padding:10px;border:1px solid #ddd">Diferencia</th>
</tr>
<tr>
<td style="padding:10px;text-align:center;border:1px solid #ddd"><b>{PUERTO_CODIGO} ({PUERTO_NOMBRE})</b></td>
<td style="padding:10px;text-align:center;border:1px solid #ddd">{BENCHMARK_PCT}%</td>
<td style="padding:10px;text-align:center;border:1px solid #ddd">{SOBRECOSTO_PCT}%</td>
<!-- Color verde (#27ae60) si negativo (bueno), rojo (#c0392b) si positivo (malo) -->
<td style="padding:10px;text-align:center;border:1px solid #ddd;color:{COLOR_DIFERENCIA};font-weight:bold">{SIGNO_DIFERENCIA}{DIFERENCIA_PP} pp {SIMBOLO_DIFERENCIA}</td>
</tr>
</tbody></table>

<!-- SECCIÓN 2: VARIACIÓN DE PRODUCTOS -->
<h3 style="color:#1a5276;margin-top:30px">2. Variación de Productos vs Último Costo</h3>

<p>Se detectan <b>{N_VARIACION} productos con variación significativa (&gt;10%)</b> y <b>{N_NUEVOS} productos nuevos</b>:</p>

<table style="width:100%;border-collapse:collapse;margin:15px 0;font-size:14px">
<tbody><tr style="background:#1a5276;color:white">
<th style="padding:10px;text-align:left;border:1px solid #ddd">Producto</th>
<th style="padding:10px;text-align:left;border:1px solid #ddd">SKU</th>
<th style="padding:10px;text-align:right;border:1px solid #ddd">Costo Actual</th>
<th style="padding:10px;text-align:right;border:1px solid #ddd">Último Costo</th>
<th style="padding:10px;text-align:center;border:1px solid #ddd">Embarque Ant.</th>
<th style="padding:10px;text-align:center;border:1px solid #ddd">Variación</th>
</tr>

<!-- FILA CON AUMENTO (variación positiva): background:#fadbd8, color:#c0392b -->
<tr style="background:#fadbd8">
<td style="padding:8px;border:1px solid #ddd">{PRODUCTO}</td>
<td style="padding:8px;border:1px solid #ddd">{SKU}</td>
<td style="padding:8px;text-align:right;border:1px solid #ddd">${COSTO_ACTUAL}</td>
<td style="padding:8px;text-align:right;border:1px solid #ddd">${ULTIMO_COSTO}</td>
<td style="padding:8px;text-align:center;border:1px solid #ddd">{EMBARQUE_ANT}</td>
<td style="padding:8px;text-align:center;border:1px solid #ddd;color:#c0392b"><b>+{VARIACION}%</b></td>
</tr>

<!-- FILA CON MEJORA (variación negativa): background:#d5f5e3, color:#27ae60 -->
<tr style="background:#d5f5e3">
<td style="padding:8px;border:1px solid #ddd">{PRODUCTO}</td>
<td style="padding:8px;border:1px solid #ddd">{SKU}</td>
<td style="padding:8px;text-align:right;border:1px solid #ddd">${COSTO_ACTUAL}</td>
<td style="padding:8px;text-align:right;border:1px solid #ddd">${ULTIMO_COSTO}</td>
<td style="padding:8px;text-align:center;border:1px solid #ddd">{EMBARQUE_ANT}</td>
<td style="padding:8px;text-align:center;border:1px solid #ddd;color:#27ae60"><b>-{VARIACION}% ✓</b></td>
</tr>

<!-- FILA PRODUCTO NUEVO: background:#f8f9fa, badge verde claro -->
<tr style="background:#f8f9fa">
<td style="padding:8px;border:1px solid #ddd">{PRODUCTO}</td>
<td style="padding:8px;border:1px solid #ddd">{SKU}</td>
<td style="padding:8px;text-align:right;border:1px solid #ddd">${COSTO_ACTUAL}</td>
<td style="padding:8px;text-align:right;border:1px solid #ddd">-</td>
<td style="padding:8px;text-align:center;border:1px solid #ddd">-</td>
<td style="padding:8px;text-align:center;border:1px solid #ddd"><span style="background:#e8f6f3;padding:2px 8px;border-radius:4px">NUEVO</span></td>
</tr>

</tbody></table>

<!-- CAJA DE ANÁLISIS: Fondo amarillo con borde izquierdo amarillo -->
<div style="background:#fef9e7;border-left:4px solid #f1c40f;padding:15px;margin:20px 0">
<strong>💡 Análisis de variaciones:</strong>
<ul style="margin:10px 0">
<li><b>{PRODUCTO_1}:</b> {EXPLICACION_1}</li>
<li><b>{PRODUCTO_2}:</b> {EXPLICACION_2}</li>
<!-- Agregar más items según productos con variación -->
</ul>
</div>

<!-- CAJA DE CONCLUSIÓN -->
<!-- Si BAJO benchmark (bueno): background:#eafaf1, border:#27ae60, color:#1e8449, símbolo ✓ -->
<!-- Si SOBRE benchmark (malo): background:#fadbd8, border:#c0392b, color:#c0392b, símbolo ⚠️ -->
<div style="background:{BG_CONCLUSION};border:1px solid {BORDER_CONCLUSION};border-radius:8px;padding:15px;margin:20px 0">
<strong style="color:{COLOR_CONCLUSION}">{SIMBOLO_CONCLUSION} Conclusión:</strong>
<p style="margin:10px 0">{TEXTO_CONCLUSION}</p>
</div>

<!-- SECCIÓN 3: MÉTRICAS DEL EMBARQUE -->
<h3 style="color:#1a5276;margin-top:30px">3. Métricas del Embarque</h3>

<table style="width:100%;border-collapse:collapse;margin:15px 0">
<tbody><tr>
<td style="padding:10px;border:1px solid #ddd;width:25%"><b>Productos</b></td>
<td style="padding:10px;border:1px solid #ddd;width:25%">{N_PRODUCTOS}</td>
<td style="padding:10px;border:1px solid #ddd;width:25%"><b>CBM</b></td>
<td style="padding:10px;border:1px solid #ddd;width:25%">{TOTAL_CBM}</td>
</tr>
<tr style="background:#f8f9fa">
<td style="padding:10px;border:1px solid #ddd"><b>Unidades</b></td>
<td style="padding:10px;border:1px solid #ddd">{TOTAL_UNIDADES}</td>
<td style="padding:10px;border:1px solid #ddd"><b>Dólar</b></td>
<td style="padding:10px;border:1px solid #ddd">${DOLAR}</td>
</tr>
<tr>
<td style="padding:10px;border:1px solid #ddd"><b>Amount (P×Q)</b></td>
<td style="padding:10px;border:1px solid #ddd">${TOTAL_PXQ} USD</td>
<td style="padding:10px;border:1px solid #ddd"><b>Flete 40HQ</b></td>
<td style="padding:10px;border:1px solid #ddd">${FLETE} USD</td>
</tr>
<tr style="background:#f8f9fa">
<td style="padding:10px;border:1px solid #ddd"><b>Internado Total</b></td>
<td style="padding:10px;border:1px solid #ddd" colspan="3">${INTERNADO_CLP} CLP</td>
</tr>
</tbody></table>

<br>

</div>
<div style="font-family:Arial,sans-serif;line-height:1.6;color:#333;max-width:800px;margin:0 auto">Favor revisar precosteo y documentos para ingresar.</div>
<div style="font-family:Arial,sans-serif;line-height:1.6;color:#333;max-width:800px;margin:0 auto"><br></div>
<div style="font-family:Arial,sans-serif;line-height:1.6;color:#333;max-width:800px;margin:0 auto">Gracias.</div>
</div>
```

### Variables del Template:

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `{EMBARQUE}` | Número de embarque | 26TP0130 |
| `{PUERTO_CODIGO}` | Código puerto | SZ, NB |
| `{PUERTO_NOMBRE}` | Nombre puerto | Shenzhen, Ningbo |
| `{SOBRECOSTO_PCT}` | % sobrecosto total | 23.55 |
| `{BENCHMARK_PCT}` | Benchmark del puerto | 16.00 |
| `{DIFERENCIA_PP}` | Diferencia en pp | 7.5 |
| `{DIRECCION}` | "encima" o "debajo" | encima |
| `{COLOR_FONDO_INDICADOR}` | Color según resultado | #d5f5e3 (verde) o #fadbd8 (rojo) |
| `{COLOR_TEXTO_INDICADOR}` | Color texto | #1e8449 (verde) o #c0392b (rojo) |
| `{SIMBOLO}` | Símbolo según resultado | ✓ (bueno) o ⚠️ (malo) |

### Colores del Template:

| Situación | Background | Color Texto | Símbolo |
|-----------|------------|-------------|---------|
| **BAJO benchmark** (bueno) | #d5f5e3 | #1e8449 / #27ae60 | ✓ |
| **SOBRE benchmark** (malo) | #fadbd8 | #c0392b | ⚠️ |
| **Variación positiva** (aumento) | #fadbd8 | #c0392b | (ninguno) |
| **Variación negativa** (mejora) | #d5f5e3 | #27ae60 | ✓ |
| **Producto nuevo** | #f8f9fa | - | Badge NUEVO |

### Benchmarks por Puerto:

| Puerto | Código | Benchmark 6m |
|--------|--------|--------------|
| Shenzhen | SZ | 16% |
| Ningbo | NB | 18% |
| Xiamen | XI | 17% |
| Aéreo | AIR | 25% |

---

## ARCHIVO DE TARIFAS SIMPLIFICADO

El usuario solo debe completar:

```
DATOS DEL EMBARQUE
- Puerto Origen: SZ, NB, XI, AIR
- Dólar Aduana: CLP por USD
- Fecha ETA

FLETE MARÍTIMO  
- Flete Total 40HQ: USD
- Capacidad 40HQ: 68 CBM

INLAND CHILE
- Agente Aduana (%): 0.0016
- Gastos Puerto STI: CLP
- Flete Terrestre: CLP
- Seimex: CLP
- Desconsolidación Craft: CLP
- Seguro Carga: CLP
- Gastos Despacho: CLP
- Gate In Maersk: CLP
```

**Los gastos Inland China se extraen automáticamente del PI.**

---

## RESUMEN DE CORRECCIONES IMPLEMENTADAS

| Punto | Descripción | Estado |
|-------|-------------|--------|
| A.1 | Comisión Steven 3% sobre (P×Q + delivery + local charge + long vehicle) | ✅ |
| A.2 | Gift box = valor PI × 1.03 (agregar 3%) | ✅ |
| A.3 | Comparar productos vs ÚLTIMO costo internado (no promedio) | ✅ |
| A.4 | **Delivery cost PRORRATEADO por grupo de Model** (no asignado individualmente) | ✅ |
| B | Actualizar pestañas: Maestra, 1. Apertura CC, 4. Matriz SKU, 5. Resumen Variaciones | ✅ |
| C | Alertar si hay conceptos no reconocidos en PI/PL | ✅ |

---

## EJEMPLO DE ALERTA DE CONCEPTOS NO RECONOCIDOS

```
⚠️ ALERTA: Conceptos no reconocidos encontrados

En el PI (líneas 52-54):
- "Insurance fee": $120 USD
- "Quality inspection": $85 USD

En el PL (línea 18):
- "Wooden crate surcharge": $200 USD

Estos conceptos no están documentados. Por favor indicar:
1. ¿Deben incluirse en el costo?
2. ¿A qué centro de costo pertenecen? (EXW, Inland China, Flete, Inland Chile)
3. ¿Cómo se prorratean? (por valor, por CBM, fijo)

Responda para continuar con el procesamiento.
```
