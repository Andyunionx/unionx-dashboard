# 📥 OBTENER DATOS FALTANTES

**Estado:** Ya tienes 5 archivos en `datos_entrada/` ✅  
**Falta:** Sueldos Febrero + Ventas (opcional)

---

## 🎯 RESUMEN RÁPIDO

| Archivo | Estado | Cómo obtener |
|---------|--------|--------------|
| Presupuesto_Febrero_2026.xlsx | ✅ TIENES | Ya cargado |
| Sueldos_Febrero_2026.xlsx | ❌ FALTA | Gmail o descarga manual |
| Balance_Febrero_2026.xlsx | ✅ TIENES | Ya cargado |
| Comex_Maestra.xlsx/.json | ✅ TIENES | Ya cargado |
| Planificación Financiera.xlsx | ✅ TIENES | Ya cargado |
| GoogleSheet_Ventas_Export.xlsx | ⏸️ OPCIONAL | Odoo (automático o manual) |

---

## 📋 OPCIÓN 1: Automático (Script que busca por ti)

```bash
cd "g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\eerr-finanzas"

# Intenta descargar Sueldos desde Gmail + Ventas de Odoo automáticamente
python preparar_datos_faltantes.py
```

**Qué hace:**
1. Busca en tu Gmail: "liquidaciones de sueldo febrero" → descarga `.xlsx`
2. Conecta a Odoo → extrae órdenes venta febrero → genera Excel
3. Valida que todos los archivos estén en `datos_entrada/`

**Requisitos:**
- Credenciales Gmail configuradas (`credentials.json`) ✅
- Credenciales Odoo en `.env` (usuario + password) ✅

---

## 📧 OPCIÓN 2: Descarga Manual desde Gmail (2 minutos)

Si el script falla, hazlo manual:

1. **Abre Gmail:** https://gmail.com
2. **Busca:** "liquidaciones de sueldo febrero"
3. **Descarga:** archivo `02.2026 CALCULO DE SUELDOS proceso.xlsx`
4. **Coloca en:** `UNION X - IA/datos_entrada/`
5. **Renombra a:** `Sueldos_Febrero_2026.xlsx`

**Email:** De Victor Cabrera (victor@unionx.cl)  
**Fecha:** 26 Feb 2026  
**Subject:** "liquidaciones de sueldo febrero 2026"

---

## 🏢 OPCIÓN 3: Extraer Ventas de Odoo (Automático o Manual)

### 3A: Automático (Script)
```bash
python extraer_ventas_odoo.py
```

Conecta a Odoo, extrae órdenes de venta febrero 2026, genera Excel automáticamente.

### 3B: Manual desde Odoo
1. **Ingresa a:** https://unionxb2b.odoo.com
2. **Usuario:** andres@grupoeter.cl
3. **Ve a:** Ventas > Órdenes de Venta
4. **Filtra:** Fecha entre 2026-02-01 y 2026-02-28
5. **Descarga:** como Excel
6. **Coloca en:** `UNION X - IA/datos_entrada/GoogleSheet_Ventas_Export.xlsx`

---

## ✅ CHECKLIST FINAL

Antes de ejecutar reportes:

```bash
# Opción recomendada: automático
python preparar_datos_faltantes.py

# O si prefieres manual:
# 1. Descarga Sueldos manualmente desde Gmail
# 2. Descarga Ventas manualmente desde Odoo
# 3. Coloca ambos en datos_entrada/

# Luego verifica
ls -la ../datos_entrada/

# Deberías ver:
# ✅ Presupuesto_Febrero_2026.xlsx
# ✅ Sueldos_Febrero_2026.xlsx
# ✅ Balance_Febrero_2026.xlsx
# ✅ Comex_Maestra.xlsx (o .json)
# ✅ Planificación Financiera.xlsx
# ✅ GoogleSheet_Ventas_Export.xlsx (opcional)
```

---

## 🚀 PRÓXIMO PASO (Una vez que tengas los 6 archivos)

```bash
# Ingestar todos los archivos
python ingestar_datos_desde_desktop.py

# Generar reportes
python orquestador_reportes.py

# Ver resultados
start ../data/outputs/Reporte_Rentabilidad_*.xlsx
```

---

## 🆘 Si algo falla

### Error: "No se pudo conectar a Odoo"
- Usuario: andres@grupoeter.cl ✅
- URL: https://unionxb2b.odoo.com ✅
- Base: bmya-innovatek-sh-prd-6981800 ✅
- ¿Password en `.env`? Verificar ANDRES_PASSWORD

### Error: "Gmail API no configurada"
- Verificar: `credentials.json` existe en raíz
- Si no: Configurar OAuth https://developers.google.com

### Mejor opción si hay errores: Descargar manual

---

## 📝 RESUMEN DE CAMBIOS

**Scripts nuevos creados:**
- `descargar_sueldos_gmail.py` — Descarga desde Gmail automáticamente
- `extraer_ventas_odoo.py` — Extrae de Odoo automáticamente  
- `preparar_datos_faltantes.py` — Orquestador de ambos

**Ejecución recomendada:**
```bash
python preparar_datos_faltantes.py  # Todo automático
python ingestar_datos_desde_desktop.py
python orquestador_reportes.py
```

---

**¿Listo? Empieza con:**
```bash
cd eerr-finanzas
python preparar_datos_faltantes.py
```
