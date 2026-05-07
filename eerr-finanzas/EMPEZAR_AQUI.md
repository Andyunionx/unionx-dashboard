# 🚀 EMPEZAR AQUI - Guía Rápida

## OPCIÓN A: Test Inmediato (Datos de Ejemplo) - 5 minutos ⚡

Si quieres **ver funcionando todo ahora mismo**, sin esperar a preparar datos reales:

### Paso 1: Generar datos de ejemplo
```bash
cd "g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\eerr-finanzas"

python generar_datos_ejemplo.py
```

**Resultado:** Crea automáticamente:
- ✅ `data/planillas/Presupuesto_Febrero_2026.xlsx`
- ✅ `data/outputs/odoo_export_20260401.json`
- ✅ `data/outputs/comex_maestra_cc.json`
- ✅ `data/planillas/Planificación Financiera.xlsx`
- ✅ `data/planillas/Sueldos_Febrero_2026.xlsx`
- ✅ `data/planillas/Balance_Febrero_2026.xlsx`

### Paso 2: Ejecutar los reportes
```bash
python orquestador_reportes.py
```

**Resultado:** Se generan en `data/outputs/`:
- ✅ `Reporte_Rentabilidad_YYYYMMDD.xlsx`
- ✅ `Reporte_KPIs_YYYYMMDD.xlsx`
- ✅ `Reporte_Planificacion_YYYYMMDD.xlsx`
- ✅ `alertas_tiempo_real.json`
- ✅ `Resumen_Semanal_YYYYMMDD.html`
- ✅ `reporte_semanal.log`

### Paso 3: Revisar resultados
```bash
# Ver log de ejecución
cat data/outputs/reporte_semanal.log

# Abrir reportes en Excel
start data/outputs/Reporte_Rentabilidad_*.xlsx
start data/outputs/Reporte_KPIs_*.xlsx
start data/outputs/Reporte_Planificacion_*.xlsx
```

---

## OPCIÓN B: Datos Reales (Tus archivos actuales) - 30 minutos

Si tienes Excel/datos en Odoo y quieres usar **números REALES**:

### Paso 1: Revisar qué archivos necesitas
```bash
# Leer esta guía
cat PREPARAR_DATOS_ENTRADA.md
```

### Paso 2: Preparar cada archivo
Sigue el checklist en `PREPARAR_DATOS_ENTRADA.md`:

- [ ] Crear `Presupuesto_Febrero_2026.xlsx`
- [ ] Crear JSON de Odoo (inventario, fulfillment)
- [ ] Crear JSON de COMEX (importaciones por CC)
- [ ] Crear `Planificación Financiera.xlsx`
- [ ] Crear `Sueldos_Febrero_2026.xlsx`
- [ ] Crear `Balance_Febrero_2026.xlsx`

### Paso 3: Ajustar rutas en los scripts
Si tus archivos están en otras ubicaciones, editar:
- `orquestador_reportes.py` → líneas donde define `ruta_*`

### Paso 4: Ejecutar
```bash
python orquestador_reportes.py
```

---

## 🔍 VERIFICAR QUÉ EXISTE YA

Ejecuta esto para ver qué archivos ya tienes:

```bash
cd "g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"

# Ver estructura actual
tree data/ -L 2

# Ver archivos Excel/JSON
find data -type f \( -name "*.xlsx" -o -name "*.json" \)
```

---

## ⚠️ SI HAY ERRORES

### Error: "ModuleNotFoundError: No module named 'openpyxl'"
```bash
# Instalar dependencias
pip install openpyxl pandas numpy
```

### Error: "FileNotFoundError: Archivo no existe"
Ejecutar primero:
```bash
python generar_datos_ejemplo.py
```

### Error: "Permission denied"
Asegúrate de que NO tienes los archivos Excel abiertos en Excel

---

## 📋 PRÓXIMOS PASOS (Después de Testear)

1. **Validar números:** ¿Coinciden con lo esperado?
2. **Ajustar thresholds:** Si alguna alerta no aplica, revisar `sistema-alertas-tiempo-real.py`
3. **Conectar emails:** Configurar SMTP en `orquestador_reportes.py`
4. **Activar automático:** Crear Task Scheduler (ver `README_REPORTES_AUTOMATICOS.md`)

---

## 📞 DOCUMENTACIÓN COMPLETA

- **README_REPORTES_AUTOMATICOS.md** — Guía técnica completa
- **PREPARAR_DATOS_ENTRADA.md** — Mapeo archivo entrada vs scripts
- **Carpeta `eerr-finanzas/`** — Todos los scripts Python

---

## 🎯 RESUMEN

| Opción | Tiempo | Resultado | Para |
|--------|--------|-----------|------|
| **A: Ejemplo** | 5 min | Reportes con datos ficticios | Ver cómo funciona YA |
| **B: Real** | 30 min | Reportes con tus números | Usar en producción |

---

**¿Cuál prefieres? Avísame y te guío paso a paso 👀**
