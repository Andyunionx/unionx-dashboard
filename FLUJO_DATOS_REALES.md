# 🚀 FLUJO: De Tus Datos a Reportes Automáticos

**Para:** Andrés  
**Objetivo:** Ejecutar reportes automáticos CON TUS DATOS REALES  
**Tiempo:** 30 minutos  

---

## 📋 PASO 1: Preparar Carpeta de Entrada

### 1.1 Crea la carpeta dentro del proyecto
```
g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\datos_entrada\
```

El script la crea automáticamente si no existe.

### 1.2 Coloca aquí los 6 archivos

Andrés va a cargar estos archivos en esa carpeta:

```
UNION X - IA/
└── datos_entrada/
    ├── Presupuesto_Febrero_2026.xlsx              ← Presupuesto actual vs real
    ├── Sueldos_Febrero_2026.xlsx                  ← Nómina (BUK o contador)
    ├── Balance_Febrero_2026.xlsx                  ← Balance/Deuda
    ├── Comex_Maestra.xlsx  (o .json)              ← Importaciones por CC
    ├── Planificación_Financiera.xlsx              ← Flujo caja + proyecciones
    └── (OPCIONAL) GoogleSheet_Ventas_Export.xlsx  ← Datos ventas de GSheet
```

**NO IMPORTAN LOS NOMBRES EXACTOS** - El script busca por palabras clave:
- "Presupuesto" o "Budget"
- "Sueldos" o "Nomina"  
- "Balance" o "Deuda"
- "Comex"
- "Planificación" o "Plan"

---

## 📂 PASO 2: Estructura Exacta de Cada Archivo

### Archivo 1: PRESUPUESTO

```xlsx
Sheet: "Presupuesto" (o como lo tengas, solo necesita estar visible)

COLUMNA A               COLUMNA B              COLUMNA C
─────────────────────────────────────────────────────────
Concepto                Presupuesto            Real
Ventas                  500,000                475,000
Costo de Venta          350,000                342,000
Comisiones              25,000                 28,000
Gastos Operacionales    50,000                 52,000
Remuneraciones          80,000                 80,000
Otros                   10,000                 12,000
```

✅ **LO QUE IMPORTA:**
- Primera columna: Nombres conceptos (texto)
- Segunda columna: Números presupuesto (números)
- Tercera columna: Números reales (números)

---

### Archivo 2: SUELDOS

```xlsx
Sheet: "Nómina" o "Sueldos" (como lo tengas)

COLUMNA A               COLUMNA B              COLUMNA C
─────────────────────────────────────────────────────────
Empleado                Monto                  Centro Costos
Andrés García           4,000                  FINANZAS
Gerente Comercial       3,500                  COMERCIAL
Asistente Ops           2,000                  LOGISTICA
...resto...
TOTAL SUELDOS           95,000                 
```

✅ **LO QUE IMPORTA:**
- Nombres empleados
- Montos (números)
- Centro de Costos (FINANZAS, COMERCIAL, LOGISTICA, etc)
- UNA FILA CON TOTAL (opcional pero recomendado)

---

### Archivo 3: BALANCE / DEUDA

```xlsx
Sheet: "Deuda"

COLUMNA A               COLUMNA B              COLUMNA C         COLUMNA D
─────────────────────────────────────────────────────────────────────────────
Préstamo                Monto                  Tasa Anual        Plazo Meses
Banco A (LC)            300,000                8.0%              48
Leasing Máquinas        200,000                6.0%              36
TOTAL DEUDA             500,000

─────────────────────────────────────────────────────────────────────────────
Sheet: "Balance"

Cuentas por Cobrar      120,000
Inventario              80,000
Caja/Bancos             50,000
TOTAL ACTIVOS           250,000

Cuentas por Pagar       95,000
Deuda CP                100,000
TOTAL PASIVOS           195,000

PATRIMONIO              55,000
```

✅ **LO QUE IMPORTA:**
- Monto de cada préstamo (números)
- Tasa anual (% o decimal)
- Plazo en meses (número)
- Balance: Activos, Pasivos, Patrimonio

---

### Archivo 4: COMEX MAESTRA

**Opción A: Excel**
```xlsx
Sheet: "Importaciones" (o como lo tengas)

ID      Proveedor  Centro Costo   Status        ETA         Dias Late  Costo
IMP-001 Steven     DISTRIBUCION   en_transito   2026-04-15  0          8,000
IMP-002 Steven     LOGISTICA      en_transito   2026-04-25  5          5,000
IMP-003 Steven     E-COMMERCE     en_puerto     2026-04-10  0          6,500
```

**Opción B: JSON** (mejor para actualizar)
```json
{
  "importaciones_activas": [
    {
      "id": "IMP-001",
      "proveedor": "Steven",
      "cc": "DISTRIBUCION",
      "status": "en_transito",
      "eta_actual": "2026-04-15",
      "dias_retraso": 0,
      "costo": 8000,
      "margen_importacion_pct": 18
    }
  ]
}
```

✅ **LO QUE IMPORTA:**
- ID único por importación
- Centro de Costo (DISTRIBUCION, LOGISTICA, etc)
- Status (en_transito, en_puerto, etc)
- Costo total
- Días de retraso

---

### Archivo 5: PLANIFICACIÓN FINANCIERA

```xlsx
Sheet: "Planificación"

CONCEPTO                              MONTO
─────────────────────────────────────────────
INGRESOS OPERACIONALES
Ventas Recíbelo                       250,000
Ventas Blue Express                   150,000
Ventas Grupo Eter                     75,000
Otros Ingresos                        25,000
TOTAL INGRESOS                        500,000

COSTO DE VENTA                        342,000
MARGEN BRUTO                          158,000

REMUNERACIONES
  Sueldos                             80,000
  Honorarios                          10,000
  Rendiciones                         5,000
TOTAL REMUNERACIONES                  95,000

GASTOS OPERACIONALES                  70,000

EBIT                                  -7,000
```

✅ **LO QUE IMPORTA:**
- Estructura clara (grupo → items → subtotal)
- Números por línea
- Totales parciales (ayuda a validar)

---

## ⚙️ PASO 3: Ejecutar Ingesta de Datos

### 3.1 Abre terminal/PowerShell en la carpeta
```
C:\Users\LENOVO\Desktop\
```

O abre directamente PowerShell:
```powershell
cd "C:\Users\LENOVO\Desktop\UNION_X_Datos"
```

### 3.2 Ejecuta el script de ingesta
```bash
cd "g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\eerr-finanzas"

python ingestar_datos_desde_desktop.py
```

**Resultado esperado:**
```
[OK] Presupuesto copiado: Presupuesto_Febrero_2026.xlsx
[OK] Sueldos copiado: Sueldos_Febrero_2026.xlsx
[OK] Balance copiado: Balance_Febrero_2026.xlsx
[OK] COMEX copiado: comex_maestra_cc.json
[OK] Planificación copiado: Planificación Financiera.xlsx

Archivos procesados: 6/6
```

---

## 📊 PASO 4: Ejecutar Reportes

### 4.1 Ejecuta orquestador
```bash
python orquestador_reportes.py
```

### 4.2 Verifica resultados
Los reportes aparecen en:
```
data/outputs/
├── Reporte_Rentabilidad_20260401.xlsx
├── Reporte_KPIs_20260401.xlsx
├── Reporte_Planificacion_20260401.xlsx
├── alertas_tiempo_real.json
├── Resumen_Semanal_20260401.html
└── reporte_semanal.log
```

### 4.3 Abre en Excel y valida
```powershell
# Desde PowerShell en data/outputs/
start Reporte_Rentabilidad_*.xlsx
start Reporte_KPIs_*.xlsx
start Reporte_Planificacion_*.xlsx
```

---

## ✅ CHECKLIST: Antes de Ejecutar

- [ ] Carpeta existe: `UNION X - IA/datos_entrada/`
- [ ] 6 archivos están en esa carpeta (o al menos 5)
- [ ] Cada archivo tiene la estructura descrita arriba
- [ ] Presupuesto: Columnas Concepto, Presupuesto, Real
- [ ] Sueldos: Columnas Empleado, Monto, Centro Costos
- [ ] Balance: Sheets "Deuda" y "Balance"
- [ ] COMEX: Columnas ID, CC, Status, ETA, Costo
- [ ] Planificación: Estructura clara de ingresos/egresos

---

## 🔄 HISTÓRICOS (Opcional pero Recomendado)

Andrés menciona crear una carpeta con históricos. **Muy buena idea.**

### Estructura propuesta:

```
UNION X - IA/
├── datos_entrada/                ← ACTUAL (mes en curso)
│   ├── Presupuesto_Febrero_2026.xlsx
│   ├── Sueldos_Febrero_2026.xlsx
│   └── ...
│
└── datos_historicos/             ← HISTÓRICOS (para análisis)
    ├── 2026/
    │   ├── Enero/
    │   │   ├── Presupuesto_Enero_2026.xlsx
    │   │   ├── Sueldos_Enero_2026.xlsx
    │   │   ├── Balance_Enero_2026.xlsx
    │   │   └── ...
    │   └── Febrero/
    │       ├── Presupuesto_Febrero_2026.xlsx
    │       ├── Sueldos_Febrero_2026.xlsx
    │       ├── Balance_Febrero_2026.xlsx
    │       └── ...
    └── README.txt
        "Copia los archivos del mes anterior a datos_historicos/YYYY/Mes/"
```

**Por qué:** Así tienes versión de cada mes para análisis histórico.

---

## 🚀 DESPUÉS: Automatizar

Una vez que los reportes funcionan manualmente:

```bash
# Crear Task Scheduler para ejecutar CADA LUNES 9 AM
schtasks /create /tn "UNION_X_Reportes_Lunes_9am" ^
  /tr "python C:\path\to\orquestador_reportes.py" ^
  /sc weekly /d MON /st 09:00:00 /f
```

Ver: `README_REPORTES_AUTOMATICOS.md` para detalles.

---

## 🆘 TROUBLESHOOTING

### Error: "Carpeta no existe"
```
Solución: Crea manualmente C:\Users\LENOVO\Desktop\UNION_X_Datos\
```

### Error: "No se encontraron archivos"
```
Solución: Verifica que los 6 archivos están en la carpeta correcta
          (Desktop/UNION_X_Datos)
```

### Error: "Archivo corrupto"
```
Solución: Abre el Excel, verifica que tenga datos, guarda, intenta de nuevo
```

### Números no cuadran en reportes
```
Solución: Revisa que cada columna tenga la estructura descrita
          (nombres en columna A, números en B y C)
```

---

## 📞 RESUMEN FINAL

| Paso | Acción | Tiempo |
|------|--------|--------|
| 1 | Crear carpeta UNION X - IA/datos_entrada/ | 1 min |
| 2 | Cargar 6 archivos en esa carpeta | 10 min |
| 3 | Ejecutar `ingestar_datos_desde_desktop.py` | 2 min |
| 4 | Ejecutar `orquestador_reportes.py` | 5 min |
| 5 | Validar reportes en data/outputs/ | 5 min |
| **TOTAL** | | **23 min** |

---

**¿Listo? Empieza con PASO 1: Crea la carpeta en el proyecto 👇**

```
g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\datos_entrada\
```

**El script la crea automáticamente**, pero es bueno crear esta estructura:

```
UNION X - IA/
├── datos_entrada/          ← Coloca archivos aquí
├── datos_historicos/       ← (Opcional) Copia del mes anterior
├── data/
├── eerr-finanzas/
└── ...
```

Avísame cuando tengas los archivos listos y ejecuto contigo el script 🚀
