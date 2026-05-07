# 📂 PREPARACIÓN DE DATOS DE ENTRADA

## Estado Actual vs Requerido

### ✅ ARCHIVOS QUE YA EXISTEN

```
data/
├── eerr/
│   ├── 01 EE.RR Enero 2026 (2).xlsx                    ✅ EXISTE
│   └── 02 EE.RR Febrero 2026.xlsx                      ✅ EXISTE
├── outputs/
│   ├── 02 EE.RR Febrero 2026_CLASIFICADO.json          ✅ EXISTE
│   ├── 02 EE.RR Febrero 2026_DISTRIBUCION_CANALES.json ✅ EXISTE
│   └── drive_download_20260331.xlsx                    ✅ EXISTE
└── planillas/
    └── Análisis Contribución 2026 V02.02.xlsx          ✅ EXISTE (15 MB)
```

---

### ❌ ARCHIVOS QUE FALTAN

Para que los scripts ejecuten SIN ERRORES, necesitas:

#### **REPORTE 1: Rentabilidad**
```
data/planillas/
├── Presupuesto_Febrero_2026.xlsx            ❌ FALTA
│   └── Debe tener sheet "Presupuesto"
│       Columnas: Concepto, Monto (estimado vs real)
│
└── Presupuesto_Marzo_2026.xlsx              ❌ FALTA (para próximos lunes)
```

#### **REPORTE 2: KPIs Operacionales**
```
data/outputs/
├── odoo_export_20260401.json                ❌ FALTA
│   Estructura esperada:
│   {
│     "inventory": {
│       "total_unidades": 5000,
│       "valor_stock": 120000,
│       "ocupacion_pct": 0.75,
│       "items_bajo_minimo": [],
│       "rotacion_promedio": 2.1
│     },
│     "fulfillment": {
│       "pedidos_pendientes": 10,
│       "pedidos_despachados_hoy": 25,
│       "pedidos_ontime_pct": 97.5,
│       "tiempo_promedio_fulfillment_dias": 2.0
│     }
│   }
│
└── comex_maestra_cc.json                    ❌ FALTA
    Estructura esperada:
    {
      "importaciones_activas": [
        {
          "id": "IMP-001",
          "cc": "DISTRIBUCION",
          "status": "en_transito",
          "dias_retraso": 0,
          "costo": 5000,
          "margen_importacion_pct": 18
        }
      ]
    }
```

#### **REPORTE 3: Planificación Financiera**
```
data/planillas/
├── Planificación Financiera.xlsx            ❌ FALTA
│   Sheets requeridos:
│   - "Planificación" (con EERR, sueldos, honorarios, rendiciones, deuda)
│
├── Sueldos_Febrero_2026.xlsx                ❌ FALTA
│   Columnas: Empleado, Monto, Centro Costos
│
├── Balance_Febrero_2026.xlsx                ❌ FALTA
│   Sheets:
│   - "Deuda" (Préstamo, Monto, Tasa, Plazo)
│   - "Balance" (Activos, Pasivos)
│
└── P&L Comparativo.xlsx                     ❌ FALTA (secundario, para analista)
```

---

## 🔧 CÓMO GENERAR LOS ARCHIVOS QUE FALTAN

### Opción A: Extraer desde Odoo (RECOMENDADO - Futuro)

```python
# Script para extraer datos automáticamente de Odoo
# (A implementar en próxima sesión con API)

from odoo_rpc_client import OdooRPC

client = OdooRPC(
    url='https://unionxb2b.odoo.com',
    db='bmya-innovatek-sh-prd-6981800',
    username='andres@grupoeter.cl',
    password='***'
)

# Extraer inventario
stock_levels = client.execute('stock.quant', 'search_read', [...])

# Extraer pedidos
sale_orders = client.execute('sale.order', 'search_read', [...])

# Extraer deuda
account_move_lines = client.execute('account.move.line', 'search_read', [...])
```

### Opción B: Crear Excel Manualmente (AHORA - Para Testing)

#### 1️⃣ **Presupuesto_Febrero_2026.xlsx**

Crear sheet "Presupuesto":

| Concepto | Presupuesto | Real |
|----------|------------|------|
| Ventas | 500000 | 450000 |
| Margen Bruto | 30% | 28% |
| Costo Venta | 350000 | 324000 |
| Comisiones | 25000 | 28000 |
| Otros Gastos | 50000 | 55000 |

#### 2️⃣ **odoo_export_20260401.json**

Guardar como `data/outputs/odoo_export_20260401.json`:

```json
{
  "inventory": {
    "total_unidades": 5000,
    "valor_stock": 120000,
    "ocupacion_pct": 0.75,
    "items_bajo_minimo": [
      {"sku": "SKU-001", "stock_actual": 2, "minimo": 10}
    ],
    "rotacion_promedio": 2.1,
    "sku_total": 150,
    "sku_activos": 120
  },
  "fulfillment": {
    "pedidos_pendientes": 10,
    "pedidos_despachados_hoy": 25,
    "pedidos_ontime_pct": 97.5,
    "tiempo_promedio_fulfillment_dias": 2.0,
    "ordenes_atrasadas": 0
  }
}
```

#### 3️⃣ **comex_maestra_cc.json**

Guardar como `data/outputs/comex_maestra_cc.json`:

```json
{
  "importaciones_activas": [
    {
      "id": "IMP-001",
      "proveedor": "Steven",
      "cc": "DISTRIBUCION",
      "status": "en_transito",
      "eta_original": "2026-04-15",
      "eta_actual": "2026-04-15",
      "dias_retraso": 0,
      "costo": 5000,
      "costeo_cn": 3000,
      "flete": 2000,
      "margen_importacion_pct": 18,
      "lead_time_promedio": 25
    },
    {
      "id": "IMP-002",
      "proveedor": "Steven",
      "cc": "LOGISTICA",
      "status": "en_transito",
      "eta_original": "2026-04-20",
      "eta_actual": "2026-04-25",
      "dias_retraso": 5,
      "costo": 3000,
      "costeo_cn": 1800,
      "flete": 1200,
      "margen_importacion_pct": 15,
      "lead_time_promedio": 25
    }
  ]
}
```

#### 4️⃣ **Planificación Financiera.xlsx**

Crear sheet "Planificación" con estas secciones:

```
INGRESOS OPERACIONALES
├─ Ventas Canal 1: 400,000
├─ Ventas Canal 2: 100,000
└─ Total: 500,000

COSTO DE VENTA
├─ COGS: 350,000

REMUNERACIONES
├─ Sueldos: 80,000
├─ Honorarios: 10,000
├─ Rendiciones: 5,000
└─ Total: 95,000

OTROS GASTOS
├─ Marketing: 20,000
├─ Operacionales: 35,000
└─ Total: 55,000

EERR (descargado de Odoo)
└─ [Ver EERR Febrero 2026.xlsx]

BALANCE
├─ Cuentas por Cobrar: 120,000
├─ Inventario: 80,000
├─ Cuentas por Pagar: 95,000
└─ Deuda: 500,000
```

#### 5️⃣ **Sueldos_Febrero_2026.xlsx**

| Empleado | Monto | CC |
|----------|-------|-----|
| Gerente Comercial | 3000 | COMERCIAL |
| Asistente Logística | 2000 | LOGISTICA |
| Contador | 2500 | FINANZAS |
| ... | ... | ... |
| **TOTAL** | **80,000** | |

#### 6️⃣ **Balance_Febrero_2026.xlsx**

Sheet "Deuda":

| Préstamo | Monto | Tasa | Plazo |
|----------|-------|------|-------|
| Banco A | 300,000 | 8% | 48 meses |
| Leasing | 200,000 | 6% | 36 meses |
| **TOTAL** | **500,000** | | |

---

## 📋 CHECKLIST: Preparar Datos

### Paso 1: Verificar EERR Clasificado ✅
```bash
# Ya existe, pero verificar estructura
cat data/outputs/02\ EE.RR\ Febrero\ 2026_CLASIFICADO.json | head -50
```

### Paso 2: Crear Presupuesto ❌
- [ ] Crear `data/planillas/Presupuesto_Febrero_2026.xlsx`
- [ ] Agregar sheet "Presupuesto" con columnas: Concepto, Presupuesto, Real

### Paso 3: Crear JSON Odoo ❌
- [ ] Crear `data/outputs/odoo_export_20260401.json`
- [ ] Incluir: inventory + fulfillment

### Paso 4: Crear JSON COMEX ❌
- [ ] Crear `data/outputs/comex_maestra_cc.json`
- [ ] Incluir: importaciones_activas con datos por CC

### Paso 5: Crear Planificación Financiera ❌
- [ ] Crear `data/planillas/Planificación Financiera.xlsx`
- [ ] Sheet "Planificación" con todas las secciones

### Paso 6: Crear Sueldos ❌
- [ ] Crear `data/planillas/Sueldos_Febrero_2026.xlsx`
- [ ] Incluir: Empleado, Monto, CC

### Paso 7: Crear Balance ❌
- [ ] Crear `data/planillas/Balance_Febrero_2026.xlsx`
- [ ] Sheets: "Deuda", "Balance"

### Paso 8: Prueba Manual ❓
```bash
python orquestador_reportes.py
```

---

## 🚀 ALTERNATIVA RÁPIDA: Usar Mock Data

Si no tienes los Excel reales aún, puedo crear un script que genere **datos de ejemplo** para testing:

```python
# Generar presupuesto de ejemplo
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws['A1'] = 'Concepto'
ws['B1'] = 'Presupuesto'
# ... llenar con datos ejemplo
wb.save('data/planillas/Presupuesto_Febrero_2026.xlsx')
```

---

## ❓ MI RECOMENDACIÓN

**Nivel 1 (Mínimo para testing - 2 horas):**
- Crear 2-3 JSON simples (Odoo, COMEX)
- Crear 1 Excel presupuesto
- Ejecutar scripts y ver qué sale

**Nivel 2 (Para Andrés usar - 4 horas):**
- Exportar TODOS los datos reales desde Excel/Odoo
- Validar que los números cierren
- Ejecutar en producción

**Nivel 3 (Automatizado - 1 semana):**
- Conectar API Odoo directa
- Eliminar Excel intermedio
- Lunes 9 AM completamente automático

---

## 📞 PRÓXIMO PASO

¿Quieres que:
1. **Cree un script que genere datos de ejemplo** (para testing ya)
2. **Te dé instrucciones paso-a-paso para exportar datos reales** (de Excel/Odoo)
3. **Ambas opciones** (ejemplo + real)

Avisa y lo hago ahora mismo 👀
