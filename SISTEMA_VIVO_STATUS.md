# Sistema de Ventas 100% En Vivo - Status Final

**Fecha:** 2026-04-17 15:00  
**Estado:** ✅ **COMPLETADO Y ACTIVO**

---

## Resumen Ejecutivo

**Sistema de sincronización automática de ventas Odoo → SQLite en vivo cada 5 minutos.**

Mantiene la Maestra de Ventas actualizada en tiempo real con:
- ✅ BD limpia y sin duplicados
- ✅ Dashboard React en vivo (http://localhost:5173/maestra)
- ✅ Excel RAW 40 columnas exportable
- ✅ Sincronizador automático cada 5 minutos (Windows Task Scheduler)

---

## Arquitectura de Flujo

```
ODOO (unionxb2b.odoo.com)
        ↓
  [XML-RPC Extract]
        ↓
sincronizador_ventas.py
  (cada 5 minutos)
        ↓
  [Deduplicación]
  [Validación]
        ↓
maestra_ventas.db (SQLite)
        ↓
  [Flask Backend]
        ↓
Dashboard React ← Usuario ve datos FRESCOS
```

---

## Componentes Activos

### 1. **Base de Datos SQLite**
**Ubicación:** `C:\Users\LENOVO\Desktop\finanzas-unionx-app\maestra_ventas.db`

**Contenido actual:**
```
Total filas: 386,001
Rango histórico: 2024-12-02 a 2026-04-17

Desglose:
├─ Histórico (pre-abril): 376,275 filas
└─ April 1-17: 9,726 filas | $235.1 MM
```

**Características:**
- ✅ Sin duplicados (deduplicación por documento+fecha+venta)
- ✅ 40 columnas RAW (todas presentes)
- ✅ Transacciones, notas de crédito, devoluciones
- ✅ Metadata de cargas registrada

### 2. **Sincronizador (sincronizador_ventas.py)**

Extrae datos desde Odoo cada 5 minutos:

**Lógica:**
1. Conecta a Odoo XML-RPC
2. Identifica nuevo período (última sync vs ahora)
3. Extrae órdenes confirmadas (state: 'sale', 'done')
4. Deduplica contra BD actual
5. Inserta nuevos registros
6. Registra carga en metadata_cargas
7. Guarda estado en `logs/sync_state.json`

**Logs en:** `logs/sincronizador.log`

### 3. **Task Scheduler (Windows)**

**Nombre:** `UnionX-Sincronizador-Ventas`  
**Intervalo:** Cada 5 minutos  
**Acción:** Ejecuta `run_sync.bat`  
**Estado:** ✅ ACTIVO

**Para verificar:**
```
Windows → Tareas Programadas → UnionX-Sincronizador-Ventas
```

### 4. **Dashboard React (En vivo)**

**URL:** http://localhost:5173/maestra

**Funcionalidades:**
- ✅ 5 filtros dinámicos (Canal, Marca, Categoría, Bodega, KAM)
- ✅ KPIs en tiempo real
- ✅ Gráficos de tendencias
- ✅ Export RAW (40 columnas)
- ✅ Tabla detalle paginada

**Backend:** Flask en http://localhost:5001/api

---

## Monitoreo

### Ver logs en vivo (PowerShell)

```powershell
# Sincronizaciones exitosas
Get-Content "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\logs\sincronizador.log" -Tail 50 -Wait

# Errores
Get-Content "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\logs\sync_errors.log" -Tail 10
```

### Verificar BD actual

```python
import sqlite3
db = sqlite3.connect("C:/Users/LENOVO/Desktop/finanzas-unionx-app/maestra_ventas.db")
cur = db.cursor()
cur.execute("SELECT COUNT(*), MAX(fecha_venta) FROM ventas")
total, fecha_max = cur.fetchone()
print(f"Total filas: {total:,} | Última actualización: {fecha_max}")
db.close()
```

### Ver estado de sincronización

```bash
cat "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\logs\sync_state.json"
```

---

## Qué Sucede Cada 5 Minutos

1. **14:00:00** → Task Scheduler ejecuta `run_sync.bat`
2. **14:00:02** → Script conecta a Odoo
3. **14:00:10** → Extrae órdenes nuevas
4. **14:00:15** → Deduplica y verifica integridad
5. **14:00:20** → Inserta en BD SQLite
6. **14:00:21** → Registra en metadata_cargas
7. **14:00:22** → Dashboard se refresca automáticamente
8. **14:05:00** → Próxima ejecución

---

## Flujo de Datos en Tiempo Real

**Ejemplo: Nueva orden en Odoo a las 14:30:00**

```
14:30:00 → Orden confirmada en Odoo
14:35:00 → Task Scheduler dispara sincronizador
14:35:15 → Orden extraida desde Odoo
14:35:20 → Cargada en BD SQLite
14:35:21 → Dashboard actualiza (sin refresh manual)
14:35:30 → Usuario ve orden en dashboard
```

---

## Detalles de Configuración

### Task Scheduler

| Propiedad | Valor |
|-----------|-------|
| Nombre | UnionX-Sincronizador-Ventas |
| Acción | Ejecutar: `G:\...\run_sync.bat` |
| Trigger | Repetir cada 5 minutos |
| Usuario | LENOVO\[tu usuario] |
| Permisos | Elevado (Admin) |
| Estado | Activo |

### Sincronizador

| Propiedad | Valor |
|-----------|-------|
| Script | `sincronizador_ventas.py` |
| Timeout | 4 minutos (240s) |
| Deduplicación | Por documento+fecha+venta_bruta |
| Reintentos | Automático en siguiente ciclo |
| Logs | `logs/sincronizador.log` |

### Base de Datos

| Propiedad | Valor |
|-----------|-------|
| Tipo | SQLite |
| Ubicación | Desktop: `maestra_ventas.db` |
| Ubicación Backup | Project: `data/db/maestra_ventas.db` |
| Columnas | 40 (RAW format) |
| Tamaño actual | ~162 MB |

---

## Mantenimiento

### Si necesitas pausar sincronización:
```powershell
Disable-ScheduledTask -TaskName "UnionX-Sincronizador-Ventas"
```

### Para reactivar:
```powershell
Enable-ScheduledTask -TaskName "UnionX-Sincronizador-Ventas"
```

### Borrar historial de logs:
```bash
Remove-Item "G:\...\logs\sincronizador.log"
```

---

## Alertas y Troubleshooting

### ⚠️ Si el sincronizador falla:

1. **Revisar logs:**
   ```
   logs/sincronizador.log
   logs/sync_errors.log
   ```

2. **Verificar conectividad Odoo:**
   - ¿Está online? https://unionxb2b.odoo.com
   - ¿Credenciales vigentes?

3. **Verificar BD:**
   - ¿Existe el archivo?
   - ¿Tiene permisos escritura?

4. **Reintentar manualmente:**
   ```bash
   cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
   python3 sincronizador_ventas.py
   ```

---

## Próximos Pasos

✅ **Sistema en vivo y automático**

**Tareas opcionales (para el futuro):**
- [ ] Alertas por email si sync falla
- [ ] Dashboard adicional de sincronización (uptimes)
- [ ] Auditoría de cambios (quién modificó qué)
- [ ] Backup automático de BD cada semana
- [ ] Compresión de logs cada mes

---

## Resumen de Archivos Clave

```
G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\
├── sincronizador_ventas.py          ← Script principal (robusto)
├── run_sync.bat                      ← Wrapper con timeout
├── setup_automation.vbs              ← Auto-configuración (ejecutado)
├── logs/                             ← Directorio de logs
│   ├── sincronizador.log            ← Ejecuciones
│   ├── sync_errors.log              ← Errores
│   └── sync_state.json              ← Último estado
├── finanzas-unionx/                 ← Backend Flask
│   └── backend/app/config.py        ← Configuración BD
├── data/
│   ├── db/maestra_ventas.db         ← BD principal (backup)
│   └── planillas/                   ← Datos de entrada
└── SISTEMA_VIVO_STATUS.md           ← Este archivo
```

---

## Contacto/Soporte

**Sistema:** Automatización UnionX Ventas  
**Responsable:** Claude Code (Backend) + Windows Task Scheduler (Orchestración)  
**Última actualización:** 2026-04-17 15:00  

**Para cambios:** Editar `sincronizador_ventas.py` y reiniciar tarea

---

**✅ LISTO PARA PRODUCCIÓN**
