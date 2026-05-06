---
name: reporte-financiero-gerencial
description: Genera reportes ejecutivos automatizados para gerencias (Word + Excel) basados en el archivo de planificación financiera. Incluye branding corporativo UnionX. Usa esta skill SIEMPRE que el usuario mencione que actualizó, cargó o subió el EERR (Estado de Resultados), el Balance, o el archivo de planificación financiera. Triggers incluyen: "cargué el EERR", "actualicé el balance", "balance febrero", "balance [mes]", "necesito el reporte mensual", "análisis de resultados", "comparación vs presupuesto", "indicadores financieros", "capital de trabajo", "reporte para gerencia", "situación financiera", "ratios de liquidez".
version: 1.3.0
---

# Skill de Reportería Financiera Gerencial

Esta skill genera reportes ejecutivos automatizados para las gerencias de UnionX, basados en las actualizaciones periódicas del archivo de planificación financiera.

## Branding Corporativo

- **Colores UnionX**: Azul principal (#5B9BD5), Azul oscuro headers (#2E75B6)
- **Logo**: "UNION" (negro) + "X" (azul) + "MORE THAN BRANDS"
- **Tipografía**: Arial

## Contexto de Uso

El usuario actualiza su archivo de planificación financiera 2 veces al mes:
1. **Carga de EERR (Estado de Resultados)** - Datos de resultados mensuales
2. **Carga de Balance** - Datos de situación financiera

## Flujo de Trabajo

### Paso 1: Identificar el Tipo de Carga
Si el usuario ya lo indicó en su mensaje, proceder directamente. Si no:
- "¿Qué carga realizaste: EERR o Balance?"
- "¿De qué mes y año son los datos?"

### Paso 2: Solicitar el Archivo
Pedir el archivo de planificación financiera (.xlsx).

### Paso 3: Generar el Reporte
Según el tipo de carga, ejecutar Escenario 1 (EERR) o Escenario 2 (Balance).

---

## Escenario 1: Carga de EERR (Estado de Resultados)

Genera **Reporte Ejecutivo** con formato numerado:

### 1. RESUMEN EJECUTIVO (máximo 6 bullets)
- Usar iconos: ↑ alza, ↓ baja, → estable
- Colores: rojo para alertas, verde para positivos
- Incluir: Ventas, Margen Directo, Margen Contribución, GAV, Utilidad Neta, EBITDA

### 2. ANÁLISIS DE MÉTRICAS CLAVE

| Métrica | Mes Actual | Mismo Mes AA | Presupuesto | Var vs AA | Var vs Ppto |
|---------|------------|--------------|-------------|-----------|-------------|

**Métricas obligatorias:**
1. Ventas
2. Margen Directo (valor y % sobre ventas)
3. Margen de Contribución (valor y % sobre ventas)
4. GAV (valor y % sobre ventas)
5. Resultado Operacional
6. Utilidad Neta
7. **EBITDA** (calcular: Resultado Operacional + Depreciación)

**IMPORTANTE - Fuentes de datos:**
- Datos reales: Hoja "P&L" 
- Datos presupuesto: Hoja "Ppto 2026" (filas 70=GAV, 72=Res.Op, 93=Utilidad, 95=EBITDA)
- EBITDA real: Fila 76 del P&L, o calcular con fila 37 (Depreciación)

### 3. ANÁLISIS DE CAPITAL DE TRABAJO

Extraer de hoja "KT":
- Inventario y Meses de Inventario
- Rotación de Inventario
- Meses de CxC y CxP
- Capital de Trabajo Neto
- Columna TENDENCIA con semáforo (Mejora/Alerta/Estable)

### 4. RECOMENDACIONES

Tabla con columnas: ÁREA | PRIORIDAD | RECOMENDACIÓN | JUSTIFICACIÓN
- Prioridad ALTA = fondo rojo
- Prioridad MEDIA = fondo amarillo

---

## Escenario 2: Carga de Balance

Genera **Reporte de Situación Financiera** con formato numerado:

### 1. RESUMEN EJECUTIVO (máximo 6 bullets)
- Usar iconos: ↑ alza, ↓ baja, → estable
- Colores: rojo para alertas, verde para positivos
- Incluir: Total Activos, Total Pasivos, Patrimonio, Deuda Financiera, Capital de Trabajo, Razón Corriente

### 2. ESTRUCTURA DEL BALANCE

| Cuenta | Mes Actual | Mes Anterior | Variación | % Var |
|--------|------------|--------------|-----------|-------|

**Secciones obligatorias:**

**ACTIVOS:**
- Caja y equivalentes
- Existencias (Inventario)
- CxC comerciales
- Anticipo proveedores
- Total Activos Corrientes
- Activos Fijos Netos
- **Total Activos**

**PASIVOS:**
- CxP comerciales
- Anticipo clientes / Provisiones
- Deuda financiera
- Préstamos socios
- Impuestos por pagar
- **Total Pasivos**

**PATRIMONIO:**
- Capital emitido
- Utilidad acumulada
- Utilidad del ejercicio
- **Total Patrimonio**

**Fuente de datos:** Hoja "Ref Balances" o "EEFF"

### 3. RATIOS DE LIQUIDEZ Y SOLVENCIA

| Ratio | Mes Actual | Mes Anterior | Benchmark | Estado |
|-------|------------|--------------|-----------|--------|

**Ratios obligatorios:**
1. **Razón Corriente** = Activos Corrientes / Pasivos Corrientes (Benchmark: >1.2)
2. **Prueba Ácida** = (Activos Corrientes - Inventario) / Pasivos Corrientes (Benchmark: >0.8)
3. **Razón de Endeudamiento** = Total Pasivos / Total Activos (Benchmark: <0.7)
4. **Deuda/Patrimonio** = Total Pasivos / Patrimonio (Benchmark: <2.0)
5. **Cobertura de Deuda** = EBITDA / Deuda Financiera (si disponible)

**Estado:** Usar semáforo
- 🟢 Cumple benchmark
- 🟡 Cerca del límite (±10%)
- 🔴 Fuera de benchmark

### 4. ANÁLISIS DE CAPITAL DE TRABAJO

Extraer de hoja "KT":
- **Inventario**: Valor y Meses de Inventario
- **CxC**: Valor y Días de CxC
- **CxP**: Valor y Días de CxP
- **Ciclo de Conversión de Efectivo** = Días Inv + Días CxC - Días CxP
- **Capital de Trabajo Neto** = Activos Corrientes - Pasivos Corrientes

Incluir columna TENDENCIA con semáforo (Mejora/Alerta/Estable)

### 5. ANÁLISIS DE DEUDA FINANCIERA

Extraer de hoja "Deuda financiera":
- Deuda total por tipo (Bancaria, Socios, Revolving)
- Deuda Corto Plazo vs Largo Plazo
- Variación vs mes anterior
- % de Deuda sobre Activos

### 6. RECOMENDACIONES

Tabla con columnas: ÁREA | PRIORIDAD | RECOMENDACIÓN | JUSTIFICACIÓN
- Prioridad ALTA = fondo rojo (ratios fuera de benchmark)
- Prioridad MEDIA = fondo amarillo (tendencias negativas)

---

## Formato de Salida

### 1. Documento Word (.docx)
- Títulos numerados (1. RESUMEN EJECUTIVO, 2. ESTRUCTURA DEL BALANCE...)
- Bullets simples con iconos ↑↓→
- Tablas con headers azul UnionX (#2E75B6)
- Semáforos: verde positivo, rojo negativo, amarillo alerta
- Footer con logo UnionX

### 2. Archivo Excel (.xlsx)

**Para EERR (4 hojas):**
1. Resumen Ejecutivo
2. Métricas Clave
3. Capital de Trabajo
4. Recomendaciones

**Para Balance (5 hojas):**
1. Resumen Ejecutivo
2. Estructura Balance
3. Ratios Financieros
4. Capital de Trabajo
5. Recomendaciones

### 3. Borrador de Email
Crear draft en Gmail con:
- **EERR:** Asunto: "Resultados [Mes Año] - Análisis Ejecutivo EERR | UnionX"
- **Balance:** Asunto: "Situación Financiera [Mes Año] - Análisis Balance | UnionX"
- Resumen de hallazgos clave
- Sección "📎 Documentos Adjuntos" listando ambos archivos
- Firma UnionX

---

## Estructura del Archivo de Planificación

| Hoja | Contenido | Columnas clave |
|------|-----------|----------------|
| P&L | EERR mensual real | Feb 2026 = col 91, Feb 2025 = col 79 |
| Ppto 2026 | Presupuesto | Feb 2026 = col 91 |
| KT | Capital de Trabajo | Mismas columnas |
| Ref Balances | Balance mensual | CM = Ene 2026, CN = Feb 2026 |
| EEFF | Estados Financieros | Mismas columnas que Ref Balances |
| Deuda financiera | Detalle de deuda | Mismas columnas |
| Otros | Otros activos/pasivos | Mismas columnas |

### Filas clave en P&L:
- Fila 3: Ingresos por Ventas
- Fila 37: Depreciación
- Fila 39: Total GAV
- Fila 41: Resultado Operacional
- Fila 56: Resultado Después de Impuestos
- Fila 76: EBITDA

### Filas clave en Ppto 2026:
- Fila 8: Ventas
- Fila 70: Total GAV
- Fila 72: Resultado Operacional
- Fila 93: Utilidad del Ejercicio
- Fila 95: EBITDA

### Filas clave en Ref Balances:
- Fila 6: Caja y equivalentes
- Fila 7: Existencias
- Fila 8: CxC comerciales
- Fila 9: Anticipo proveedores
- Fila 10: Otras CxC
- Fila 16: Total Activos Corrientes
- Fila 22: Total Activos Fijos
- Fila 24: Total Activos
- Fila 28: CxP comerciales
- Fila 30: Anticipo clientes
- Fila 31: Deuda financiera
- Fila 32: Préstamos socios
- Fila 35: Total Pasivos
- Fila 38: Capital emitido
- Fila 39: Utilidad acumulada
- Fila 40: Utilidad del ejercicio
- Fila 42: Total Patrimonio
- Fila 46: Check Balance (debe ser 0)

### Mapeo de columnas por mes (2026):
| Mes | Columna Ref Balances | Índice |
|-----|---------------------|--------|
| Ene 2026 | CM | 91 |
| Feb 2026 | CN | 92 |
| Mar 2026 | CO | 93 |
| Abr 2026 | CP | 94 |

**Nota**: Los valores del Ppto están en unidades, dividir por 1000 para obtener M CLP.
