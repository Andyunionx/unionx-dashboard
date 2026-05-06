# Automatización de Ventas en Vivo (100%)

**Estado:** ✅ LISTO PARA ACTIVAR  
**Última actualización:** 2026-04-17  
**Responsable:** Sistema automático

---

## Resumen

Sistema que mantiene la Maestra de Ventas **100% en vivo** sincronizando datos de Odoo cada **5 minutos** directamente a SQLite.

### Componentes

1. **sincronizador_ventas.py** — Script Python que:
   - Conecta a Odoo XML-RPC
   - Extrae transacciones nuevas
   - Deduplica e inserta en BD
   - Guarda logs detallados

2. **run_sync.bat** — Wrapper con timeout (4 min) para evitar cuelgues

3. **setup_task_scheduler.ps1** — Registra automáticamente en Windows Task Scheduler

4. **Dashboard React** — Muestra datos en vivo desde la BD (http://localhost:5173/maestra)

---

## Cómo Activar la Automatización

### Paso 1: Abrir PowerShell como Administrador

```powershell
# Click derecho en PowerShell → "Ejecutar como administrador"
```

### Paso 2: Registrar en Task Scheduler

```powershell
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
powershell -ExecutionPolicy Bypass -File setup_task_scheduler.ps1
```

**Resultado esperado:**
```
[OK] COMPLETADO - Sincronizador activo cada 5 minutos
     Logs: G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\logs\sincronizador.log
```

### Paso 3: Verificar en Task Scheduler

```
1. Abrir: Tareas Programadas (Búsqueda de Windows → "Tareas")
2. Buscar: "UnionX-Sincronizador-Ventas"
3. Debe estar activa y mostrando "Se ejecuta cada 5 minutos"
```

---

## Arquitectura de Flujo de Datos

```
Odoo (unionxb2b.odoo.com)
        ↓
   [XML-RPC Client]
        ↓
 sincronizador_ventas.py (cada 5 min)
        ↓
  [Deduplicación]
        ↓
 maestra_ventas.db (SQLite)
        ↓
  [Flask Backend]
        ↓
 Dashboard React (en vivo)
        ↓
    Usuario ve datos frescos
```

---

## Monitoreo

### Ver Logs en Tiempo Real

```bash
# Terminal 1: Monitorear sincronizaciones
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
Get-Content logs\sincronizador.log -Tail 50 -Wait

# Terminal 2: Monitorear errores
Get-Content logs\sync_errors.log -Tail 10 -Wait
```

### Verificar BD Directamente

```python
import sqlite3
db = sqlite3.connect("C:/Users/LENOVO/Desktop/finanzas-unionx-app/maestra_ventas.db")
cur = db.cursor()

# Últimas 10 transacciones
cur.execute("SELECT fecha_venta, canal, ROUND(venta_bruta, 0) FROM ventas ORDER BY fecha_venta DESC LIMIT 10")
for fecha, canal, venta in cur.fetchall():
    print(f"{fecha} | {canal:30} | ${venta:15,.0f}")

db.close()
```

### Dashboard en Vivo

**URL:** http://localhost:5173/maestra

- ✅ Filtros dinámicos (Canal, Marca, Categoría, Bodega, KAM)
- ✅ KPIs en vivo
- ✅ Gráficos de tendencias
- ✅ Descarga RAW (40 columnas)

---

## Qué Pasa Cada 5 Minutos

1. **Task Scheduler** ejecuta `run_sync.bat`
2. `run_sync.bat` llama a `sincronizador_ventas.py`
3. Script conecta a Odoo
4. Extrae transacciones nuevas (últimas 24h en primera ejecución, delta después)
5. Deduplica: elimina registros con mismo documento + fecha + venta_bruta
6. Inserta en BD local
7. Sincroniza a Google Drive (si existe)
8. Guarda estado en `logs/sync_state.json`
9. Registra en `logs/sincronizador.log`

---

## Tolerancia a Fallos

| Escenario | Acción |
|-----------|--------|
| Odoo offline | Script espera timeout (4 min), se reintenta en 5 min |
| Conexión lenta | Timeout protege contra cuelgues indefinidos |
| BD corrupta | Deduplicación evita duplicados |
| Servidor caído | Logs guardan estado para diagnóstico |

---

## Estadísticas Esperadas

Después de activar, verás en logs:

```
[2026-04-17 15:00:00] [OK] SINCRONIZACIÓN COMPLETADA
[2026-04-17 15:00:00]       Registros: 245
[2026-04-17 15:00:00]       Venta sincronizada: $1,234,567.00
[2026-04-17 15:00:00]       Timestamp: 2026-04-17T15:00:15.234567
```

---

## Próximos Pasos

1. **Hoy:** Ejecutar `setup_task_scheduler.ps1`
2. **Mañana:** Verificar que los logs muestren sincronizaciones exitosas
3. **En 1 semana:** Confirmar que el dashboard siempre muestra datos frescos

---

## Soporte Técnico

**Logs de diagnóstico:**
```
G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\logs\
  ├── sincronizador.log          (ejecuciones)
  ├── sync_errors.log             (errores)
  └── sync_state.json             (estado actual)
```

**Script principal:**
```
G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\sincronizador_ventas.py
```

**Contacto:** Sistema automático / Andrés (gerente de finanzas)

---

## Checklist de Activación

- [ ] PowerShell abierto como Administrador
- [ ] Ejecutado: `setup_task_scheduler.ps1`
- [ ] Tarea visible en Task Scheduler
- [ ] Primera sincronización registrada en logs/
- [ ] Dashboard mostrando datos actualizados
- [ ] Monitoreo de logs configurado

✅ **Sistema listo para mantener venta 100% en vivo**
