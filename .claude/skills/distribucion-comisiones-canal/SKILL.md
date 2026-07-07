---
name: distribucion-comisiones-canal
description: "Distribuye las comisiones del EERR por canal de venta e inserta el resultado en la planilla de Análisis de Contribución. Usa esta skill SIEMPRE que el usuario suba o mencione el EERR junto con archivos de Recíbelo, Blue Express o Control de Aportes para el análisis de comisiones. Triggers incluyen: distribuir comisiones, comisiones por canal, análisis de contribución, costeo por canal, EERR + Recíbelo, EERR + Blue Express, cargar comisiones, distribuir costos directos, margen de contribución por canal, rentabilidad por canal."
version: 1.0.0
---

# Distribución de Comisiones por Canal de Venta

Distribuye los costos directos de operación (comisiones) del EERR a cada canal de venta y genera el resultado en formato compatible con la planilla de Análisis de Contribución.

## Archivos Requeridos

El usuario debe subir 4 archivos:

| # | Archivo | Contenido clave |
|---|---------|-----------------|
| 1 | **EERR mensual** (.xlsx) | Pestañas: DETALLE (libro mayor), MAPEO CANALES, provisión mes (ej: "Febrero en Marzo 26"), devengado mes anterior (ej: "Enero en Febrero 26.") |
| 2 | **Recíbelo** (.xlsx) | Pestaña DB con columnas CLIENTE INTERNO, TARIFA, TARIFA BIGTICKET |
| 3 | **Blue Express** (.xlsx) | Detalle de factura con columnas CENTRO COSTO, NETO |
| 4 | **Control de Aportes** (.xlsx) | Pestaña "Aportes" con Año, Mes, Retail, Provisión Neta, Fecha Emisión |

Opcionalmente recibe:
| 5 | **Análisis de Contribución** (.xlsx) | Para inyectar la pestaña con resultados directamente |

## Paso 1: Leer MAPEO CANALES del EERR

Leer la pestaña `MAPEO CANALES` del EERR. Contiene 4 secciones:

### 1a. Mapeo por Contraparte
Columnas: Tipo | Nombre Exacto (Contraparte o Glosa) | Canal de Venta.
Construir diccionario `contraparte → canal`.

### 1b. Mapeo por Glosa
Columnas: Tipo | Texto inicial de Glosa | Canal de Venta.
Construir diccionario `prefijo_glosa → canal`.

### 1c. Proveedores Excluidos
Proveedores que se distribuyen aparte (ej: REVERSSO SPA → se distribuye 1/3 a cada página web).

### 1d. Cuentas Incluidas
Las cuentas del DETALLE a considerar. Por defecto:
- COMISIÓN GRANDES CUENTAS
- ENVIO GRANDES CUENTAS
- FLETES Y GASTOS DE ENVIO
- MARKETING DIGITAL
- COMISION BANCARIA pago electrónico

### 1e. Glosas Excluidas
Glosas que son asientos contables globales, no transacciones directas:
- `prov factura` → se distribuye usando pestaña de provisión
- `rev prov factura` → ignorar (está en líneas con flag PROVISION que netan a 0)
- `revierte aporte` → se distribuye usando Control de Aportes
- `google workspace`, `chatwoot` → excluir del análisis (no son comisiones de canal)

## Paso 2: Clasificar líneas del DETALLE

Leer pestaña `DETALLE` del EERR (header en fila 2). Filtrar solo las cuentas incluidas (Paso 1d).

### 2a. Excluir líneas con PROVISION flag
Las líneas donde la columna `PROVISION` = "PROVISION" suman neto $0 (son contrapartidas contables). **Excluirlas completamente.**

### 2b. Clasificar las líneas restantes
Para cada línea sin PROVISION flag:
1. Si la glosa comienza con un prefijo excluido (1e) → clasificar como `__PROV__`, `__REVIERTE__` o `__EXCL__`
2. Si la contraparte está en el mapeo (1a) → asignar canal directo
3. Si la glosa comienza con un prefijo del mapeo (1b) → asignar canal directo
4. Si no coincide con nada → marcar como `__NOMAP__` y alertar al usuario

### 2c. Verificar que no haya líneas sin mapear
Si hay `__NOMAP__`, mostrar al usuario las líneas no mapeadas para que indique el canal.

## Paso 3: Distribuir asiento PROV FACTURA

El asiento global `prov factura` (provisión del mes) se distribuye usando la pestaña de provisión del EERR (ej: "Febrero en Marzo 26").

1. Leer la pestaña de provisión, filtrar filas con Razón Social válida y DESGLOSE $ numérico
2. Mapear cada Razón Social al canal usando el mismo diccionario del Paso 1a
3. Determinar la cuenta contable según campo DESGLOCE:
   - `ENVIO GRANDES CTAS` → ENVIO GRANDES CUENTAS
   - `MARKETING` → MARKETING DIGITAL
   - `COMISION X VENTA` → COMISIÓN GRANDES CUENTAS
   - `servicio de envios` (TIPO GASTO) → FLETES Y GASTOS DE ENVIO
   - default GRANDES CUENTAS → COMISIÓN GRANDES CUENTAS
4. Calcular peso de cada (canal, cuenta) sobre el total por cuenta
5. Distribuir el monto del asiento global proporcionalmente

## Paso 4: Distribuir REVIERTE APORTE

El asiento `revierte aporte` se distribuye según el Control de Aportes:

1. Leer pestaña "Aportes" del Control de Aportes
2. **Criterio de distribución**: Identificar los aportes cuya provisión fue emitida en el período actual. La base de distribución se compone de:
   - Aportes del mes anterior con fecha emisión en el mes actual
   - Aportes del mes actual (PROV APORTE) que aparecen en el DETALLE
3. Calcular peso proporcional por canal (Retail)
4. Distribuir el monto del asiento `revierte aporte` según esos pesos
5. Los canales destino son:
   - Falabella → `Falabella tienda`
   - Paris → `Paris tienda`
   - Duty Travel → `Travel Duty`

## Paso 5: Redistribuciones especiales

### 5a. Página Web → dividir en 3
Los costos asignados a "Página Web" (pasarelas de pago, marketing digital, Shopify, Klaviyo, etc.) se dividen en **partes iguales** entre:
- `Simplit web`
- `Lhotse web`
- `UnionX web` (incluye MeLollevo)

### 5b. Recibelo → distribuir por canal
Leer pestaña DB del archivo Recibelo. Calcular total por CLIENTE INTERNO = TARIFA + TARIFA BIGTICKET.
Distribuir el monto total de Recibelo en el EERR proporcionalmente.

Mapeo CLIENTE INTERNO → Canal:
| CLIENTE INTERNO | Canal |
|----------------|-------|
| FALABELLA | Falabella |
| LHOTSE | Lhotse web |
| MELOLLEVO | UnionX web |
| MERCADO LIBRE | Mercado Libre |
| BICE | Banco Bice |
| MKT | MKT |
| PV | PV |
| SIMPLIT | Simplit web |
| UNIONX | UnionX web |

### 5c. Blue Express → distribuir por canal
Leer pestaña de factura detallada del archivo Blue Express. Calcular total NETO por CENTRO COSTO.
Distribuir el monto total de Blue Express proporcionalmente.

Mapeo CENTRO COSTO → Canal:
| CENTRO COSTO | Canal |
|--------------|-------|
| APPRECIO | Apprecio |
| BICE | Banco Bice |
| CELMEDIA | Celmedia |
| GRS | Global Reward |
| GVG | Gran Venta Garage |
| LHOTSE STORE | Lhotse web |
| MELOLLEVO | UnionX web |
| MERCADO LIBRE | Mercado Libre |
| MKT | MKT |
| PV | PV |
| SIMPLIT | Simplit web |
| UNIONX | UnionX web |

### 5d. Reversso → distribuir 1/3 a cada web
Las comisiones provisionadas de Reversso se dividen 1/3 entre Simplit web, Lhotse web y UnionX web.

## Paso 6: Consolidar y generar equivalencias

Consolidar todos los registros por (Canal, Cuenta). Calcular las equivalencias para Análisis de Contribución:

| Cuenta EERR | → Columna Análisis Contribución |
|-------------|-------------------------------|
| COMISIÓN GRANDES CUENTAS + COMISION BANCARIA pago electrónico | **Comisión Venta** |
| ENVIO GRANDES CUENTAS + FLETES Y GASTOS DE ENVIO | **Comisión Envío** |
| MARKETING DIGITAL | **Marketing** |
| Suma de los 3 anteriores | **Total Comisiones** |

## Paso 7: Verificar cuadratura

Comparar el total distribuido contra el EERR:
- Total EERR (5 cuentas) - Exclusiones (Google Workspace, Chatwoot) = Total distribuible
- Total distribuido debe ser = Total distribuible
- **Si la diferencia no es $0, revisar y corregir antes de continuar.**

## Paso 8: Generar salida en formato Análisis Resultados

Crear una tabla con las **22 columnas** exactas de la pestaña "Análisis Resultados":

```
AÑO | Negocio | Canal | KAM | Mes | Trimestre | Venta | NC Aportes | Venta Real | Costo Venta | Margen Directo | Comisión Venta | Comisión Envío | Marketing | Total Comisiones | Contribución | Resultado Venta KAM | Resulrado Margen Front KAM | Resultado Comisión Venta KAM | Resultado Comisión Logística KAM | Resultado Marketing KAM | Resultado Contribución KAM
```

- **AÑO, Mes, Trimestre**: Según el período del EERR
- **Negocio, KAM**: Obtener del archivo de Análisis de Contribución (pestaña "Análisis Resultados", mismo canal y último mes disponible)
- **Comisión Venta, Comisión Envío, Marketing, Total Comisiones**: Resultado del análisis
- **Venta, Costo, Margen, Resultado KAM**: Dejar vacío (provienen del RAW y seguimiento comercial)

## Paso 9: Inyectar en Análisis de Contribución

Si el usuario proporcionó el archivo de Análisis de Contribución:

**IMPORTANTE**: Este archivo suele tener la pestaña "Análisis Resultados" con max_row=1,048,576 (inflada por Excel), lo que supera el límite de memoria de openpyxl.

**Solución**: Manipular el .xlsx como archivo ZIP:
1. Generar el XML de la nueva pestaña con lxml
2. Copiar el archivo original
3. Inyectar el XML como nueva hoja (sheet) en el ZIP
4. Actualizar `workbook.xml`, `workbook.xml.rels` y `[Content_Types].xml` para registrar la nueva pestaña
5. El nombre de la pestaña debe ser: `EERR {Mes} {Año}` (ej: "EERR Feb 2026")

## Paso 10: Generar archivo de soporte

Adicionalmente, generar un Excel separado con las pestañas de detalle:
1. **Comisiones x Canal** — Resumen pivot por canal y cuenta
2. **Detalle Glosas x Canal** — Cada glosa asignada a su canal, agrupada por cuenta
3. **Detalle Recibelo** — Distribución por cliente interno
4. **Detalle Blue Express** — Distribución por centro de costo
5. **Desprovisión Aportes** — Base y distribución del revierte
6. **Mapeo Canales** — Tabla de mapeo completa
7. **Notas Metodológicas** — Documentación de criterios

## Nombres de Canales (referencia)

Usar siempre la nomenclatura del archivo Análisis de Contribución:
- `Simplit web` (no "Simplit Web")
- `Lhotse web` (no "Lhotse Web")
- `UnionX web` (no "UnionX Web") — incluye MeLollevo
- `Abc` (no "ABC")
- `Gran Venta Garage` (no "GVG")
- `Walmart tienda` (no "Walmart Tienda")
- `Falabella tienda` (no "Falabella Tienda")
- `Paris tienda` (no "Paris Tienda")
- `Banco Bice` (no "Bice")
- `Global Reward` (no "GRS")

## Reglas de Negocio Críticas

1. **WALMART CHILE S.A y WALMART CHILE COM. LTDA** → Canal `Walmart tienda` (separado de Walmart)
2. **PROV APORTE PARIS** → Canal `Paris tienda` (no Paris)
3. **PROV APORTES FALABELLA** → Canal `Falabella tienda`
4. **MeLollevo web = UnionX web** → Consolidar todo en `UnionX web`
5. **Líneas PROVISION flag** → Excluir (neto = $0, se cancelan entre sí)
6. **Google Workspace + Chatwoot** → Excluir del análisis
