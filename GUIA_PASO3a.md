# GUÍA: PASO 3a - Extrae RAW desde Odoo

## Objetivo
Reemplazar la intermediación de Excel con extracción **directa desde Odoo**, manteniendo 100% de fidelidad con los datos de venta.

---

## Opciones de Uso

### Opción A: Desde Odoo (Recomendado)
Extrae datos en **tiempo real** directamente de la base de datos Odoo.

**Requisitos:**
- Usuario activo en Odoo: `andres@grupoeter.cl`
- Password o API Token de Odoo

**Pasos:**
```bash
# 1. Configura el password en .env (en raíz del proyecto)
echo "ANDRES_ODOO_PASSWORD=tu_password_aqui" > ../.env

# 2. Ejecuta la extracción
python paso3a_ejecutar_completo.py

# 3. Verifica resultados
# - Se generará: data/outputs/raw_desde_odoo_febrero_2026.csv
# - Se inyectará automáticamente en Análisis Resultado
```

**Obtener API Token (si usas 2FA):**
1. Ve a: https://unionxb2b.odoo.com
2. Abre tu perfil (arriba a la derecha)
3. En "Seguridad" → Genera "Application Token"
4. Usa ese token como `ANDRES_ODOO_PASSWORD`

---

### Opción B: Desde Excel
Usa el archivo `Raw ventas Y.xlsx` existente (más rápido, sin dependencias de Odoo).

**Requisitos:**
- `datos_entrada/Raw ventas Y.xlsx` debe existir

**Pasos:**
```bash
# Ejecuta directamente
python paso3a_desde_excel.py

# Genera: data/outputs/raw_agregado_febrero_2026.xlsx
# Inyecta automáticamente en Análisis Resultado
```

**Usar solo Excel si:**
- No tienes password/token de Odoo
- Necesitas procesar rápido
- Odoo está en mantenimiento

---

## Flujo de Scripts

```
Opción A (Odoo)          |  Opción B (Excel)
-----------              |  -----
CONEXION ODOO            |  LEER EXCEL
    ↓                    |      ↓
extraer_raw_desde_odoo   |  paso3a_desde_excel
    ↓                    |      ↓
validar_extraccion_odoo  |  VALIDACION MANUAL (opcional)
    ↓                    |      ↓
DATOS LISTOS             |  DATOS LISTOS
    ↓                    |      ↓
inyectar_raw_analisis_resultado
    ↓
ANALISIS RESULTADO ACTUALIZADO
    ↓
TABLAS DINAMICAS SE REGENERAN AUTOMATICAMENTE
```

---

## Archivos Generados

| Archivo | Descripción |
|---------|-------------|
| `data/outputs/raw_desde_odoo_febrero_2026.csv` | Extracción Odoo bruta (línea × línea) |
| `data/outputs/raw_desde_odoo_febrero_2026_agrupado.csv` | Agregado por canal/negocio/KAM |
| `data/outputs/raw_agregado_febrero_2026.xlsx` | Versión Excel lista para inyectar |
| `MAPEO_RAW_DESDE_ODOO.md` | Mapeo de 40 columnas a fuentes Odoo |

---

## Validación

Después de ejecutar, verifica:

### 1. ¿Totales coinciden?
```bash
python validar_extraccion_odoo.py
```

Espera ver:
- Venta total febrero: ~$410M (comparar con tus registros)
- 37-40 combinaciones canal/negocio/KAM
- Varianza < 1% respecto a Raw ventas Y.xlsx

### 2. ¿Inyección fue exitosa?
Abre `Análisis Contribución 2026 V02.02.xlsx`:
1. Ve a sheet "Análisis Resultados"
2. Desplázate al final
3. Deberías ver nuevas filas con AÑO=2026, Mes=2

### 3. ¿Tablas dinámicas se actualizaron?
En "Análisis Contribución":
1. Abre sheet "Tabla YoY"
2. Verifica que febrero 2026 aparece con datos nuevos
3. Haz clic en botón "Actualizar" en la tabla dinámica si no se ve

---

## Custom Fields Esperados en Odoo

El script intenta encontrar estos campos en Odoo. Si falta alguno, verás "FALTA" en validación:

| Campo | Ubicación esperada | Alternativa si no existe |
|-------|------|---|
| Canal | custom field en sale.order | Usar nombre del cliente |
| Tipo Negocio | custom field en sale.order | Usar tipo de cliente |
| KAM | salesman_id en sale.order | Usar nombre del usuario |
| Comisión % | custom field en sale.order.line | Calculada global |
| Logística | custom field en sale.order | Costo por defecto |
| Marketing | custom field en sale.order | $0 si no existe |

**Si faltan campos, contacta a Andrés para confirmar en qué custom fields están guardados en Odoo.**

---

## Solución de Problemas

### Error: "No se pudo conectar a Odoo"
```
[ERROR] No se pudo conectar a Odoo: Connection refused

Soluciones:
1. Verifica URL: https://unionxb2b.odoo.com (sin /web ni extras)
2. Valida usuario: andres@grupoeter.cl (exacto)
3. Confirma password en .env (sin espacios extras)
4. Si usas 2FA: genera API Token en tu perfil Odoo
5. Verifica que tengas internet conectado
```

### Error: "Autenticación fallida"
```
[ERROR] Autenticación fallida

Soluciones:
1. Verifica que el usuario existe en Odoo
2. Si es password de usuario: intenta API Token
3. Confirma que la base 'bmya-innovatek-sh-prd-6981800' es correcta
4. Pide a IT que verifique que tu usuario tenga acceso a API XML-RPC
```

### Error: "No existe Raw ventas Y.xlsx"
```
[ERROR] No existe: ../datos_entrada/Raw ventas Y.xlsx

Soluciones:
1. Verifica que Raw ventas Y.xlsx está en: UNION X - IA/datos_entrada/
2. Usa opción Odoo en lugar de Excel
3. Descarga el archivo desde Google Drive si no existe localmente
```

### Varianza > 1% en validación
```
[FALTA] 5 canales NO coinciden

Causas posibles:
1. Custom fields no están siendo leídos correctamente
2. Falta algún período de datos (entrada manual en Odoo)
3. Cálculo de costos diferente entre fuentes

Pasos:
1. Revisa MAPEO_RAW_DESDE_ODOO.md "Preguntas Críticas"
2. Confirma con Andrés qué custom fields faltan
3. Actualiza extraer_raw_desde_odoo.py con nombres correctos
```

---

## Operación Manual (Sin Scripts)

Si los scripts fallan, puedes hacer todo manualmente:

1. **Abre Raw ventas Y.xlsx**
2. **Filtra:** Columna "Año venta" = 2026, "Mes venta" = 2
3. **Agrupa** (Pivot Table):
   - Row Labels: Canal, Tipo Negocio, KAM
   - Values: Suma de Venta bruta, Costo Total, Margen Front
4. **Copia** el pivot result
5. **Abre:** Análisis Contribución 2026 V02.02.xlsx
6. **Pega** en sheet "Análisis Resultados" (al final, sin borrar histórico)
7. **Guarda**

Las tablas dinámicas se actualizarán automáticamente.

---

## Próximos Pasos

Después de completar PASO 3a:

1. **PASO 3b:** Mapear EERR + Skill "distribucion-comisiones-canal"
   - Ubicación: Ver PLAN_RENTABILIDAD_PASO3.md
   - Script: `paso3b_mapear_eerr.py` (por crear)

2. **PASO 3c:** Mapear Seguimiento Contribución (Google Sheet)
   - Ubicación: Formulario de seguimiento KAM-Canal
   - Script: `paso3c_extraer_seguimiento.py` (por crear)

3. **PASO 4:** Script maestro que inyecta RAW + EERR + Seguimiento
   - Combina todas las fuentes
   - Valida integridad de datos
   - Genera reportes ejecutivos

---

## Referencia Rápida

```bash
# Ejecutar TODO (Odoo + validación + inyección)
python paso3a_ejecutar_completo.py

# Ejecutar TODO desde Excel (sin Odoo)
python paso3a_desde_excel.py

# Solo validar (comparar contra Raw ventas Y.xlsx)
python validar_extraccion_odoo.py

# Solo inyectar (requiere CSV previo)
python inyectar_raw_analisis_resultado.py
```

---

## Contacto y Soporte

Si hay dudas sobre:
- **Custom fields en Odoo**: Contacta a IT o al admin de Odoo
- **Estructura de datos**: Revisar MAPEO_RAW_DESDE_ODOO.md
- **Errores de scripts**: Ver sección "Solución de Problemas"
- **Configuración de reportes**: Ver PLAN_RENTABILIDAD_PASO3.md

---

**Última actualización:** 2026-04-02
**Estado:** PASO 3a - Código generado, esperando test con Andrés
