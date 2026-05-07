# 📋 GUÍA: Preparar Datos Reales - Específico para Andrés

## ✅ Qué Ya Tienes

```
data/
├── eerr/
│   ├── 01 EE.RR Enero 2026.xlsx           (556 KB) ✅
│   └── 02 EE.RR Febrero 2026.xlsx         (1.9 MB) ✅ ← PRINCIPAL
│
├── outputs/
│   ├── 02 EE.RR Febrero 2026_CLASIFICADO.json      ✅ ← IMPORTANTE
│   ├── 02 EE.RR Febrero 2026_DISTRIBUCION_CANALES.json ✅
│   └── drive_download_20260331.xlsx                 (84 MB)
│
└── planillas/
    └── Análisis Contribución 2026 V02.02.xlsx      (15 MB) ✅
```

---

## ❌ Qué Falta (y Cómo Obtenerglo)

### 1️⃣ Presupuesto_Febrero_2026.xlsx

**Dónde conseguirlo:**
- ¿Tienes presupuesto del mes? Búscalo en Google Drive, Sheets, o Email del CEO
- Si está en Google Sheets: Descargalo como Excel
- Si está en Odoo: Exporta desde Accounting

**Estructura necesaria:**

```
Sheet: "Presupuesto"
┌───────────────────────┬────────────┬─────────────┐
│ Concepto              │ Presupuesto │ Real (Odoo) │
├───────────────────────┼────────────┼─────────────┤
│ Ventas                │   500,000  │   475,000   │
│ Costo de Venta        │   350,000  │   342,000   │
│ Margen Bruto          │   150,000  │   133,000   │
│ Comisiones            │    25,000  │    28,000   │
│ Gastos Operacionales  │    50,000  │    52,000   │
│ Remuneraciones        │    80,000  │    80,000   │
│ EBIT Estimado         │    45,000  │    -27,000  │
└───────────────────────┴────────────┴─────────────┘
```

**⚡ RÁPIDO: Copiar de tu "P&L Comparativo" si existe**

---

### 2️⃣ odoo_export_20260401.json

**Qué necesita:**

```json
{
  "inventory": {
    "total_unidades": 5000,
    "valor_stock": 120000,
    "ocupacion_pct": 0.78,
    "items_bajo_minimo": [...],
    "rotacion_promedio": 2.1,
    "sku_total": 150,
    "sku_activos": 125
  },
  "fulfillment": {
    "pedidos_pendientes": 12,
    "pedidos_despachados_hoy": 28,
    "pedidos_ontime_pct": 96.5,
    "tiempo_promedio_fulfillment_dias": 2.1,
    "ordenes_atrasadas": 1
  }
}
```

**¿De dónde sacarlo?**

Opción A (Odoo):
```python
# Exportar desde Odoo
# En Odoo: Inventario > Reportes > Seguimiento de Stock
# Exportar a JSON
```

Opción B (RÁPIDO - Estimar):
- `total_unidades`: ¿Cuántas unidades tienes en almacén HOY?
- `valor_stock`: ¿Cuál es el valor de inventario en el balance?
- `ocupacion_pct`: ¿Qué porcentaje del almacén está lleno?
- `rotacion_promedio`: Ventas/mes ÷ Inventario promedio
- `pedidos_ontime_pct`: ¿Qué % de pedidos se despachan a tiempo?

---

### 3️⃣ comex_maestra_cc.json

**Dónde conseguirlo:**

Este viene del **Agente COMEX** que ya existe en el proyecto. El agente monitorea emails de:
- **Steven** (topwillsteven@163.com) - Proveedorchino
- **Vicente** (vicente@seimex.cl) - Forwarder

**Si el agente ya corre:**
```bash
# Ver archivos COMEX generados
ls -la data/outputs/*comex* 2>/dev/null
```

**Si NO tienes datos COMEX aún:**

Crea manualmente `data/outputs/comex_maestra_cc.json`:

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
      "costo": 8000,
      "margen_importacion_pct": 18,
      "lead_time_promedio": 25
    }
  ]
}
```

---

### 4️⃣ Planificación Financiera.xlsx

**Dónde conseguirlo:**

¿Tienes un Excel de "Planificación Financiera" o "Plan Financiero"?
- Búscalo en Drive, Email, o pregunta a CEO/CFO
- Si está como Google Sheet: Descárgalo

**Estructura necesaria:**

```
Sheet: "Planificación"
┌──────────────────────────┬─────────┐
│ INGRESOS OPERACIONALES   │         │
│ Ventas Recíbelo          │ 250,000 │
│ Ventas Blue Express      │ 150,000 │
│ Ventas Grupo Eter        │  75,000 │
│ Otros Ingresos           │  25,000 │
│ TOTAL INGRESOS           │ 500,000 │
├──────────────────────────┼─────────┤
│ COSTO DE VENTA           │ 342,000 │
│ Margen Bruto             │ 158,000 │
├──────────────────────────┼─────────┤
│ REMUNERACIONES           │  95,000 │
│ (Sueldos)                │  80,000 │
│ (Honorarios)             │  10,000 │
│ (Rendiciones)            │   5,000 │
├──────────────────────────┼─────────┤
│ GASTOS OPERACIONALES     │  70,000 │
│ EBIT                     │  -7,000 │
└──────────────────────────┴─────────┘
```

**⚡ RÁPIDO:**
Puedo copiar datos del EERR Febrero que ya tienes + Sueldos/Honorarios/Rendiciones

---

### 5️⃣ Sueldos_Febrero_2026.xlsx

**Dónde conseguirlo:**

Tienes VARIAS opciones:

**Opción A: De BUK** (Mejor)
- Entrar en BUK: Tu login
- Ir a: Nómina > Reportes > Resumen Salarial Febrero
- Descargar como Excel

**Opción B: De Odoo**
- Odoo > Nómina > Salarios
- Exportar Febrero

**Opción C: De Contador**
- Si el contador mantiene un Excel de sueldos, pedirle copia

**Estructura necesaria:**

```
┌──────────────────┬─────────┬──────────────┐
│ Empleado         │ Monto   │ Centro Cost  │
├──────────────────┼─────────┼──────────────┤
│ Andrés (Finanza) │  4,000  │ FINANZAS     │
│ Gerente Comercia │  3,500  │ COMERCIAL    │
│ Jefe Ops         │  3,200  │ LOGISTICA    │
│ ... (resto)      │  ...    │ ...          │
│ TOTAL            │ 80,000  │              │
└──────────────────┴─────────┴──────────────┘
```

---

### 6️⃣ Balance_Febrero_2026.xlsx

**Dónde conseguirlo:**

Contacta al **Contador** - debe tener el Balance mensual

O en **Odoo**: Accounting > Reportes > Balance Sheet

**Estructura necesaria:**

```
Sheet "Deuda":
┌─────────────────────┬──────────┬────────┬────────┐
│ Préstamo            │ Monto    │ Tasa % │ Plazo  │
├─────────────────────┼──────────┼────────┼────────┤
│ Banco A (LC)        │ 300,000  │ 8.0%   │ 48     │
│ Leasing Máquinas    │ 200,000  │ 6.0%   │ 36     │
│ TOTAL DEUDA         │ 500,000  │        │        │
└─────────────────────┴──────────┴────────┴────────┘

Sheet "Balance":
┌──────────────────┬──────────┐
│ Cuentas Cobrar   │ 120,000  │
│ Inventario       │  80,000  │
│ Caja/Bancos      │  50,000  │
│ TOTAL ACTIVOS    │ 250,000  │
├──────────────────┼──────────┤
│ Cuentas Pagar    │  95,000  │
│ Deuda CP         │ 100,000  │
│ TOTAL PASIVOS    │ 195,000  │
├──────────────────┼──────────┤
│ PATRIMONIO       │  55,000  │
└──────────────────┴──────────┘
```

---

## 🚀 PLAN DE ACCIÓN (Elige uno)

### Plan A: 30 minutos - Usar Casi Todo Real

1. **Buscar:**
   - [ ] Presupuesto Febrero (Google Drive / Email)
   - [ ] Datos Odoo Inventario (o estimar)
   - [ ] Datos COMEX actuales (Steven/Vicente)
   - [ ] Sueldos Febrero (BUK o Excel)
   - [ ] Balance Febrero (Contador)

2. **Crear archivos:**
   - [ ] `data/planillas/Presupuesto_Febrero_2026.xlsx`
   - [ ] `data/outputs/odoo_export_20260401.json`
   - [ ] `data/outputs/comex_maestra_cc.json`
   - [ ] `data/planillas/Sueldos_Febrero_2026.xlsx`
   - [ ] `data/planillas/Balance_Febrero_2026.xlsx`

3. **Ejecutar:**
   ```bash
   python orquestador_reportes.py
   ```

---

### Plan B: 10 minutos - Datos Parciales + Estimados

**Combinar:**
- ✅ EERR Febrero que ya tienes
- ✅ JSON clasificado que ya existe
- ❌ Estimar Presupuesto (copia del Real)
- ❌ Estimar Odoo (datos típicos)
- ❌ Estimar COMEX (data dummy)
- ❌ Estimar Sueldos (data típica)
- ❌ Estimar Balance (típico)

```bash
python generar_datos_ejemplo_REAL_HIBRIDO.py
```

(Puedo crear este script)

---

### Plan C: Rápido Test - Solo EERR Real

Usar el EERR que ya tienes + generar resto con datos dummy

```bash
python generar_datos_ejemplo.py  # Genera dummy
# Luego reemplazar only JSON EERR con el real
cp data/outputs/02\ EE.RR\ Febrero\ 2026_CLASIFICADO.json data/outputs/eerr_real.json
```

---

## 📋 CHECKLIST FINAL

Antes de ejecutar `orquestador_reportes.py`:

```
ARCHIVO                                         TENGO   NECESITO
─────────────────────────────────────────────────────────────────
data/eerr/02 EE.RR Febrero 2026.xlsx            ✅      (ya existe)
data/outputs/*_CLASIFICADO.json                 ✅      (ya existe)
data/planillas/Presupuesto_Febrero_2026.xlsx    ❌      (CREAR)
data/outputs/odoo_export_20260401.json          ❌      (CREAR)
data/outputs/comex_maestra_cc.json              ❌      (CREAR)
data/planillas/Planificación Financiera.xlsx    ❌      (CREAR/BUSCAR)
data/planillas/Sueldos_Febrero_2026.xlsx        ❌      (CREAR/BUSCAR)
data/planillas/Balance_Febrero_2026.xlsx        ❌      (CREAR/BUSCAR)
```

---

## ❓ Preguntas Rápidas Para Andrés

Responde estas y podemos empezar HOY:

1. ¿Dónde tienes el archivo de Presupuesto Febrero? (Drive, Email, ¿otro?)
2. ¿Cuántas unidades tienes aprox en almacén? (o déjame estimar)
3. ¿Quién tiene los sueldos? (BUK, Contador, ¿tú?)
4. ¿Tienes datos COMEX recientes o empiezo con estimados?
5. ¿El Balance Febrero de dónde lo saco? (Odoo, Contador, ¿tienes?)

---

## 🔄 Mi Recomendación

**Hoy:**
1. Busca los 6 archivos (o al menos 3-4)
2. Sube lo que encuentres a `data/planillas/`
3. Yo genero el resto como "estimado"
4. Ejecutamos reportes para ver cómo funciona

**Después:**
- Reemplazas datos estimados por reales
- Ejecutas reportes con números reales
- Automáticas cada lunes 9 AM

---

**¿Cuál es tu próximo paso? Avísame y empezamos 👀**
