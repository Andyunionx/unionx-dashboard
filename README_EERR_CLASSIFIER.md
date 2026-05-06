# EERR Classifier & P&L Distribution System

## 📋 Descripción General

Plataforma **completamente automatizada** que:

1. ✅ **Extrae reglas** del HTML de PL_Manager (88 reglas de clasificación contable)
2. ✅ **Clasifica automáticamente** cada fila del EERR (Estado de Resultados)
3. ✅ **Distribuye por canal** de venta (Recíbelo, Blue Express, etc.)
4. ✅ **Integra con skill** `distribucion-comisiones-canal` para actualizar análisis de contribución
5. ✅ **Exporta** en Excel, JSON y HTML con reportes ejecutivos

---

## 🏗️ Arquitectura

```
PL_Manager.html (88 reglas)
           ↓
eerr_classifier.py (motorClassifier)
           ↓
EERR.xlsx → Clasificado automáticamente
           ↓
integracion_distribucion_comisiones.py
           ↓
    Distribuido por canal
           ↓
Skill: distribucion-comisiones-canal
           ↓
Análisis de Contribución actualizado
```

---

## 🚀 Uso Rápido

### Opción 1: Desde Python (Recomendado)

```python
from integracion_distribucion_comisiones import procesar_eerr_completo

# Procesa EERR completo en un comando
filas, distribucion = procesar_eerr_completo(
    ruta_eerr_xlsx="mi_eerr_abril.xlsx",
    mes="Abril",
    ano=2026
)
```

**Output:**
- `mi_eerr_CLASIFICADO.xlsx` - EERR con clasificaciones
- `mi_eerr_CLASIFICADO.json` - Datos estructurados
- `mi_eerr_DISTRIBUCION_CANALES.json` - Para la skill
- `mi_eerr_REPORTE_CANALES.html` - Reporte visual

### Opción 2: Desde Claude Code (Workflow completo)

```
/distribucion-comisiones-canal
→ Sube EERR sin procesar
→ Sistema automático:
  1. Clasifica 88 reglas
  2. Distribuye por canal
  3. Actualiza planilla de Análisis de Contribución
```

---

## 📚 Reglas de Clasificación

### Estructura de Regla

```json
{
  "codigo": "43420101",      // Código contable (match exacto)
  "campo": "GLOSA",          // Campo a validar: NINGUNO, GLOSA, CONTRAPARTE
  "keyword": "GRUPO ETER",   // Palabra clave a buscar
  "ln": "GRUPO ETER",        // Línea de negocio (resultado)
  "cc": "REMUNERACIONES",    // Centro de costos
  "area2": "FINANZAS...",    // Área empresa
  "sa": "CONTABILIDAD",      // Sub-área
  "ca": "CONTABILIDAD"       // Cuenta analítica
}
```

### Lógica de Aplicación

1. **Busca por código contable** (match exacto)
2. **Valida según campo:**
   - `NINGUNO` → Aplica regla directamente
   - `GLOSA` → Busca keyword en descripción del movimiento
   - `CONTRAPARTE` → Busca keyword en nombre del proveedor/cliente
3. **Normaliza texto** (mayúsculas, sin acentos) para búsqueda confiable

### Ejemplo de Aplicación

```
Fila: Código=43420101, Glosa="Sueldo GRUPO ETER CONTABILIDAD"

Buscar en REGLAS[codigo=43420101]:
  └─ Si campo="GLOSA" y keyword="GRUPO ETER CONTABILIDAD"
     └─ ✓ Match en glosa normalizada
     └─ Aplica: ln=GRUPO ETER, cc=REMUNERACIONES...
```

---

## 🛠️ Modificar Reglas

### Agregar Nueva Regla

```python
# En eerr_classifier.py, agregar a REGLAS:
{
    "codigo": "41999999",
    "campo": "GLOSA",
    "keyword": "TU_PALABRA_CLAVE",
    "ln": "UNION X",
    "cc": "NUEVO_CC",
    "area2": "NUEVA_AREA",
    "sa": "SUB_AREA",
    "ca": "CUENTA_ANALITICA"
}
```

### O actualizar REGLAS_CLASIFICACION.json

```bash
python eerr_classifier.py  # Lee desde REGLAS_CLASIFICACION.json
```

---

## 📊 Flujo de Datos

### 1. Entrada (EERR.xlsx)

| Código | Glosa | Contraparte | Saldo |
|--------|-------|-------------|-------|
| 41410101 | Venta Recíbelo | RECIBELO | 1500.5 |
| 43420101 | Sueldo GRUPO ETER... | | -250.0 |

### 2. Clasificación

```
Código 41410101 → Regla match → UNION X | COSTO VENTA | ...
Código 43420101 + Glosa → Match keyword → GRUPO ETER | REMUNERACIONES | ...
```

### 3. Distribución por Canal

```
Canal: RECIBELO
  └─ Movimiento 1: M$ 1500.5 (Venta)
  
Canal: GRUPO_ETER
  └─ Movimiento 2: M$ -250.0 (Remuneración)
```

### 4. Skill distribucion-comisiones-canal

```
Input: distribucion JSON con estructura por canal
Output: Comisiones distribuidas en Análisis de Contribución
```

---

## 📁 Archivos del Sistema

| Archivo | Propósito |
|---------|-----------|
| `eerr_classifier.py` | Motor de clasificación (88 reglas) |
| `integracion_distribucion_comisiones.py` | Distribuidor por canal + integración skill |
| `REGLAS_CLASIFICACION.json` | Reglas en JSON (fácil mantener) |
| `README_EERR_CLASSIFIER.md` | Este archivo |

---

## ✨ Características Destacadas

### ✅ Clasificación Automática
- 88 reglas precargadas del HTML original
- Búsqueda por código + validación de contexto
- Normalización automática de texto (tildes, mayúsculas)

### ✅ Distribución por Canal
- **4 canales identificados:**
  - `RECIBELO` (patrón: código 41410101 o glosa contiene "RECIBELO")
  - `BLUE_EXPRESS` (código 41410109)
  - `CONTROL_APORTES` (contexto de aportes)
  - `GRUPO_ETER` / `UNIONX` (por línea de negocio)

### ✅ Múltiples Formatos de Salida
- **Excel** - Formato ejecutivo con colores
- **JSON** - Para integración programática
- **HTML** - Reporte visual interactivo

### ✅ Trazabilidad Completa
- Registro de qué regla se aplicó
- Confianza de clasificación
- Alertas de filas sin clasificar

---

## 🔗 Integración con Skill

### Paso 1: Procesar EERR

```python
from integracion_distribucion_comisiones import procesar_eerr_completo

filas, distribucion = procesar_eerr_completo("EERR_Abril.xlsx", "Abril")
```

### Paso 2: Activar Skill

```
Usuario en Claude Code:
"Distribuye comisiones canal" + adjunta "EERR_Abril_DISTRIBUCION_CANALES.json"

Skill recibe: {
  "canales": {
    "RECIBELO": [...],
    "BLUE_EXPRESS": [...],
    "CONTROL_APORTES": [...]
  },
  "resumen": { "cantidad": N, "monto_total": XXX }
}
```

### Paso 3: Resultado

✓ Análisis de Contribución actualizado automáticamente
✓ Comisiones distribuidas por canal
✓ Reportes generados

---

## 🧪 Testing

```python
# Test simple (en eerr_classifier.py)
python eerr_classifier.py

# Output:
# 📊 ESTADÍSTICAS:
# Grupo Eter...........2
# Union X.............2
# Sin clasificar.....1
# Splits...............0
```

---

## 📝 Notas de Mantenimiento

### Actualizar Reglas Anualmente

1. Solicitar actualización de HTML a usuario PL_Manager
2. Reemplazar `REGLAS` en `eerr_classifier.py`
3. Ejecutar tests para validar

### Agregar Nueva Línea de Negocio

```python
# 1. Agregar en SPLIT_ACCOUNTS
{
    "id": "mi_linea",
    "titulo": "Mi Línea de Negocio",
    "modo": "rows",  # o "amount"
    "cuenta": "XXXX",
    "codigo": "XXXX"
}

# 2. Agregar reglas correspondientes en REGLAS
# 3. Actualizar MAPEO_CANAL si aplica
```

---

## 🐛 Troubleshooting

| Problema | Solución |
|----------|----------|
| Filas "sin clasificar" | Agregar regla para ese código contable |
| Canal incorrecto | Actualizar patrones en `PATRONES_*` |
| Excel con error | Verificar formato de columnas en EERR |

---

## 📞 Contacto & Soporte

Para cambios o actualizaciones:
1. Editar `REGLAS_CLASIFICACION.json`
2. O reportar en memory del proyecto
3. Skill automáticamente usará nuevas reglas

---

**Última actualización:** 2026-04-01  
**Versión:** 1.0  
**Estado:** Producción ✅
