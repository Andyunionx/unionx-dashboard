# Dashboard Ventas Diario — Manual de Operaciones

**Última actualización:** 2026-05-06
**Estado:** ✅ EN PRODUCCIÓN

---

## 🎯 Qué es

Dashboard web (Streamlit) que muestra ventas con comparativa **YoY (Year over Year)**:
- KPIs principales: Venta Neta, Margen, % Margen, Unidades — con variación vs año anterior.
- Gráfico evolución mensual TY vs LY.
- Tendencia diaria del mes actual vs mismo mes año anterior.
- Tabla por canal con var YoY.
- Top 20 SKUs con var YoY.
- **Descarga RAW** en formato 40 columnas para cualquier período.

**URL:** http://localhost:8503

**Acceso directo:** doble click en `Dashboard Ventas UnionX.url` en el escritorio.

---

## 🔄 Actualización diaria automática

### Cómo funciona

1. Cada día a las **06:00 AM**, Windows Task Scheduler ejecuta `actualizar_diario.py`.
2. El script extrae las ventas del **día anterior** desde Odoo:
   - Chunkeo por día (evita timeouts)
   - 9 fixes consolidados: multi-facturación, website_id, El Volcán filter, neteo NC con costo proporcional, cancel+posted, etc.
   - **Idempotente:** re-correr no genera duplicados (DELETE WHERE BETWEEN antes de insertar).
3. Inserta en `data/db/maestra_ventas.db` (SQLite, 374K+ filas) y actualiza `data/planillas/Raw ventas Y (4).xlsx`.
4. El dashboard cachea 5 minutos cada agregado; se refresca automáticamente.

### Logs

```
data\db\sincronizacion_diaria.log
```

Rotación automática (5 MB × 10 archivos = 50 MB max).

### Estado en el dashboard

Badge en la esquina superior derecha:
- 🟢 **OK** — última sincronización < 30 horas
- 🟡 **ATRASADO** — entre 30-48h
- 🔴 **FALLA** — > 48h o error

---

## 📋 Comandos útiles

### Ver estado de la tarea diaria
```powershell
Get-ScheduledTaskInfo -TaskName "UnionX - Actualizar Ventas Diario"
```

### Ejecutar la sincronización manual ahora
```powershell
Start-ScheduledTask -TaskName "UnionX - Actualizar Ventas Diario"
```

O desde la línea de comandos:
```powershell
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
& "C:\Users\andre\AppData\Local\Programs\Python\Python312\python.exe" actualizar_diario.py
```

### Catch-up (extraer N días hacia atrás)
```powershell
& "C:\Users\andre\AppData\Local\Programs\Python\Python312\python.exe" actualizar_diario.py --dias 5
```

### Extraer un día específico
```powershell
& "C:\Users\andre\AppData\Local\Programs\Python\Python312\python.exe" actualizar_diario.py --fecha 2026-05-04
```

### Ver últimos logs
```powershell
Get-Content "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\data\db\sincronizacion_diaria.log" -Tail 50
```

### Reiniciar el dashboard
```powershell
# Matar streamlit
Get-Process python | Where-Object { $_.MainWindowTitle -like "*streamlit*" } | Stop-Process

# O por puerto
Get-NetTCPConnection -LocalPort 8503 | Stop-Process -Id { $_.OwningProcess } -Force

# Relanzar (watchdog lo restaura solo)
Start-ScheduledTask -TaskName "UnionX - Dashboard Ventas (Streamlit)"
```

---

## 🛠️ Instalación inicial (solo una vez)

### 1. Registrar la tarea diaria de actualización
```powershell
powershell -ExecutionPolicy Bypass -File "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\registrar_tarea_diaria.ps1"
```

### 2. Registrar el watchdog del dashboard
```powershell
powershell -ExecutionPolicy Bypass -File "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\registrar_dashboard_servicio.ps1"
```

### 3. Probar
```powershell
# Forzar primera carga manual
Start-ScheduledTask -TaskName "UnionX - Actualizar Ventas Diario"

# Arrancar dashboard
Start-ScheduledTask -TaskName "UnionX - Dashboard Ventas (Streamlit)"

# Esperar 30s y abrir navegador
Start-Process "http://localhost:8503"
```

---

## 📊 Componentes del dashboard

### Header
- Título y badge de estado de sincronización
- Selector de rango de fechas (TY)
- Botón Refrescar
- Indicador de período LY comparado

### KPIs (4 cards)
- **Venta Neta:** monto del período + var % vs LY
- **Margen Final:** $ + var % vs LY
- **% Margen:** % + variación absoluta en pts vs LY
- **Unidades:** totales + var % vs LY

### Gráficos
- **Evolución mensual:** AreaChart con TY (azul) y LY (gris) lado a lado
- **Tendencia diaria mes actual:** LineChart con TY (línea sólida) y LY (línea punteada)

### Tablas
- **Por Canal:** Canal, Venta TY, Venta LY, Var %, % Margen
- **Top 20 SKUs:** SKU, Producto, Venta TY, Var %, % Margen

### Descarga
- Selector de período independiente
- Botón "Generar y descargar" → Excel con 40 columnas RAW

---

## 🐛 Troubleshooting

### Dashboard no abre
1. Verificar que el puerto 8503 esté escuchando:
   ```powershell
   Get-NetTCPConnection -LocalPort 8503 -ErrorAction SilentlyContinue
   ```
2. Si no, ejecutar el watchdog manual:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\start_dashboard_ventas.ps1"
   ```

### Datos desactualizados (badge 🟡 o 🔴)
1. Ver el log de la última corrida:
   ```powershell
   Get-Content "data\db\sincronizacion_diaria.log" -Tail 100
   ```
2. Ejecutar sincronización manual:
   ```powershell
   & "C:\Users\andre\AppData\Local\Programs\Python\Python312\python.exe" actualizar_diario.py --dias 1
   ```

### Error "ANDRES_ODOO_PASSWORD no definida"
La password está en variable de entorno User. El script intenta cargarla via PowerShell. Si falla:
```powershell
[Environment]::SetEnvironmentVariable('ANDRES_ODOO_PASSWORD', 'TU_PASSWORD', 'User')
```

### Odoo cae con 502 Bad Gateway
La skill tiene retry automático con backoff (10 intentos, 1-60s). Si después de eso sigue fallando, esperar y relanzar:
```powershell
& "C:\Users\andre\AppData\Local\Programs\Python\Python312\python.exe" actualizar_diario.py --fecha 2026-05-04
```

---

## 📁 Archivos clave

| Archivo | Propósito |
|---|---|
| `dashboard_ventas.py` | Dashboard Streamlit principal |
| `actualizar_diario.py` | Wrapper de sincronización diaria |
| `actualizar_raw_historico.py` | Skill principal (extracción + transformación) |
| `finanzas-unionx/backend/app/services/maestra_service.py` | Lógica YoY + descarga RAW |
| `finanzas-unionx/backend/app/services/ventas_service.py` | Skill `extract_to_raw_format` |
| `start_dashboard_ventas.ps1` | Watchdog del dashboard (auto-restart) |
| `registrar_tarea_diaria.ps1` | Registro Task Scheduler para sync diaria |
| `registrar_dashboard_servicio.ps1` | Registro Task Scheduler para dashboard |
| `data/db/maestra_ventas.db` | DB SQLite (datos históricos + diarios) |
| `data/planillas/Raw ventas Y (4).xlsx` | Excel RAW espejo de la DB |
| `data/planillas/Maestra Canales.xlsx` | Mapeo Empresa → Canal (165 entradas) |
| `data/db/sincronizacion_diaria.log` | Log con rotación (50 MB max) |

---

## 🔮 Roadmap sugerido (si surge necesidad)

- Notificación email/Slack si la sincronización falla
- Filtros adicionales en el dashboard (por bodega, marca, KAM)
- Export a Power BI / Looker Studio
- Comparativa por canal × año detallada
- Forecast simple del cierre de mes
