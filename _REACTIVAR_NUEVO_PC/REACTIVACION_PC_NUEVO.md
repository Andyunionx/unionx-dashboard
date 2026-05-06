# Reactivación UNION X - IA en PC nuevo

**Fecha del análisis:** 2026-04-28
**PC anterior (usuario):** LENOVO
**PC nuevo (usuario):** andre
**Estado del proyecto:** ✅ código intacto en Google Drive · ⚠️ requiere ajustes locales antes de operar

---

## Resumen ejecutivo

El código completo del proyecto está sano en `G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA`. Lo que se rompió al cambiar de PC son las rutas hardcodeadas que apuntaban a `C:\Users\LENOVO\...` y los componentes locales del PC (Task Scheduler de Windows, instalación de Python, dependencias pip, sincronización de Google Drive).

**Ya hice (sin tu intervención):** corregí todas las rutas hardcodeadas a `LENOVO` en los scripts de automatización.
**Falta que tú hagas (acciones manuales en Windows):** instalar Python + dependencias, registrar tareas en Task Scheduler, copiar 2 archivos de configuración protegidos, validar conexiones.

---

## 1. Cambios que ya quedaron aplicados

| Archivo | Cambio |
|---|---|
| `setup_windows_automation.ps1` | Auto-detecta Python (PATH → py launcher → rutas comunes en %LOCALAPPDATA%). Ya no hardcodea `LENOVO`. |
| `trigger_lunes_9am.bat` | Usa `python` del PATH con fallback a `py -3`. |
| `trigger_dia7_mes.bat` | Idem. |
| `trigger_dia10_mes.bat` | Idem. |
| `start_unionx_dashboard.ps1` | Ruta streamlit usa `$env:LOCALAPPDATA` con fallback Python313/311/310. |
| `start_contribucion_dashboard.ps1` | Idem. |
| `start_stock_dashboard.ps1` | Idem. |
| `start_cloudflare_tunnel.ps1` | Usa `$env:USERPROFILE\.cloudflared\` y `$env:LOCALAPPDATA\Temp\`. |

---

## 2. Cambios bloqueados — requieren tu acción manual

Cowork no me deja editar `.claude/settings.json` ni `.claude/settings.local.json` (Cowork los protege). Dejé las versiones corregidas en este mismo folder:

- **`settings.json.NUEVO`** → reemplaza `G:\...\UNION X - IA\.claude\settings.json`
- **`settings.local.json.NUEVO`** → reemplaza `G:\...\UNION X - IA\.claude\settings.local.json`

**Comando para reemplazar (en PowerShell, con la app Cowork cerrada):**

```powershell
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
Copy-Item ".claude\settings.json" ".claude\settings.json.bak" -Force
Copy-Item ".claude\settings.local.json" ".claude\settings.local.json.bak" -Force
Copy-Item "_REACTIVAR_NUEVO_PC\settings.json.NUEVO" ".claude\settings.json" -Force
Copy-Item "_REACTIVAR_NUEVO_PC\settings.local.json.NUEVO" ".claude\settings.local.json" -Force
```

---

## 3. Pasos manuales en orden

### Paso 1 — Instalar Python 3.12 (si no está)

```powershell
# Verificar si Python ya está
python --version
# Si NO existe: descarga desde https://www.python.org/downloads/release/python-3120/
# IMPORTANTE: marcar "Add python.exe to PATH" durante la instalación
```

### Paso 2 — Instalar dependencias del proyecto

```powershell
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# Dependencias adicionales no listadas en requirements.txt:
python -m pip install gspread python-dotenv streamlit dotenv
```

### Paso 3 — Reemplazar los 2 settings de Cowork (paso 2 de arriba)

Usar el bloque `Copy-Item` del punto 2.

### Paso 4 — Validar conexión Odoo

```powershell
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
python eerr-finanzas\test_odoo_conexion.py
```

Resultado esperado: 3 OKs y al final `[OK] CONEXION EXITOSA`. La password está en `.env` (`ANDRES_ODOO_PASSWORD=ROTATED-2026-05-07`).

### Paso 5 — Validar token Gmail (auto-refresh)

```powershell
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
python agente-comex\main.py --status
python agente-comex\main.py --scan
```

El token actual venció el `2026-03-31`, pero el `refresh_token` sigue válido y el cliente lo refresca solo en la primera llamada. Si pide reauth, ejecutá:

```powershell
python agente-comex\setup_gmail.py
```

### Paso 6 — Registrar tareas en Task Scheduler

Abrí PowerShell **como administrador**:

```powershell
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
powershell -ExecutionPolicy Bypass -File setup_windows_automation.ps1
```

Verificá en `tasksched.msc` → Biblioteca → UnionX-IA que aparezcan las 4 tareas:

1. UnionX-IA - Agente COMEX Gmail (al iniciar sesión)
2. UnionX-IA - Lunes 9 AM (Drive+Sheets)
3. UnionX-IA - Día 7 mes (Comisiones)
4. UnionX-IA - Día 10 mes (EERR+Skill)

### Paso 7 — Confirmar que Google Drive está sincronizando G:

En el ícono de Drive de la barra de tareas, confirmar que `Mi unidad` está sincronizada y la carpeta del proyecto se ve completa. (Esta sesión confirmó que sí está, pero conviene re-validar.)

### Paso 8 — Confirmar carpeta `Junior Revenue` en escritorio

`data_ingestion.py` espera el Excel maestro en:
```
C:\Users\andre\Desktop\Junior Revenue\Análisis Contribución 2026 V02.02.xlsx
```
Si no existe, hay que crear la carpeta y copiar el archivo desde respaldo.

---

## 4. Estado de cada componente

| Componente | Estado | Notas |
|---|---|---|
| Carpeta `UNION X - IA/` en Drive | ✅ Completa | Todos los .py, configs, datos accesibles |
| `CLAUDE.md` | ✅ OK | Sin cambios necesarios |
| `ARQUITECTURA_FINAL.md` | ⚠️ Revisar | Menciona `C:\Users\LENOVO\Desktop\Junior Revenue\` (línea 282). Solo doc, no afecta ejecución, pero conviene actualizarla cuando confirmes la ruta nueva. |
| `requirements.txt` | ⚠️ Incompleto | Falta `gspread`, `python-dotenv`, `streamlit`. Resuelto con el `pip install` extra del Paso 2. |
| `.env` | ✅ Tiene `ANDRES_ODOO_PASSWORD` | Otros vars (`GOOGLE_APPLICATION_CREDENTIALS`, `ANDRES_EMAIL`) están en `.env.template` pero `data_ingestion.py` los pide solo si usás el flujo IMAP. Validar Paso 4-5. |
| `.env.template` | ⚠️ Tiene path LENOVO en `DESKTOP_PATH` | Solo afecta si copiás el template; `data_ingestion.py` usa `Path.home()` dinámico, así que no rompe. |
| Token Gmail | ⚠️ Expirado pero recuperable | Refresh token vigente. Auto-renueva en primer `python main.py --scan`. |
| Conexión Odoo | ⏳ Sin testear | Validar con Paso 4. |
| Python en PC | ❓ Desconocido | Validar con Paso 1. |
| Task Scheduler | ❌ Sin registrar | Re-registrar con Paso 6. |
| Google Drive sync | ✅ Activo | Confirmado: archivos visibles en G:\\ |
| Skills (4 críticas) | ✅ Disponibles | comex-workflow, shipping-plan, distribucion-comisiones-canal, reporte-financiero-gerencial |

---

## 5. Referencias residuales a `LENOVO` (no críticas)

Logs históricos y docs que dejé sin tocar (no afectan operación, solo registros de cuándo era LENOVO):

```
logs/sync.log
logs/sincronizador.log
data/db/sincronizacion.log
SISTEMA_VIVO_STATUS.md
AUTOMATIZACION_VENTAS_EN_VIVO.md
CLOUDFLARE_TUNNEL_SETUP.md
FLUJO_DATOS_REALES.md
SETUP_TRIGGERS.md
INSTALACION_FINAL.md
ARQUITECTURA_FINAL.md
ACTIVAR_AUTOMATIZACION.txt
test/install_credentials.py
extract_full*.py / extract_final.py / sync_*.py / sincronizador_*.py
run_revenue_pipeline.sh
.env.template
```

Si querés que los limpie en una pasada, decime y lo hago. Para operación normal no son necesarios.

---

## 6. Test de smoke completo (cuando termines pasos 1-7)

```powershell
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"

# 1. Python OK
python --version

# 2. Odoo OK
python eerr-finanzas\test_odoo_conexion.py

# 3. Gmail OK
python agente-comex\main.py --status
python agente-comex\main.py --scan

# 4. Task Scheduler OK
Get-ScheduledTask -TaskPath "\UnionX-IA\" | Format-Table TaskName, State

# 5. Skills OK (en Cowork): pedir a Claude "lista las skills disponibles"
```

Si los 5 dan verde, el sistema queda **100% operativo**.

---

## 7. Atajo: ejecutar todo en una sola tirada

Pegá esto en PowerShell **como administrador**:

```powershell
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"

# Dependencias
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install gspread python-dotenv streamlit

# Settings de Cowork
Copy-Item ".claude\settings.json" ".claude\settings.json.bak" -Force
Copy-Item ".claude\settings.local.json" ".claude\settings.local.json.bak" -Force
Copy-Item "_REACTIVAR_NUEVO_PC\settings.json.NUEVO" ".claude\settings.json" -Force
Copy-Item "_REACTIVAR_NUEVO_PC\settings.local.json.NUEVO" ".claude\settings.local.json" -Force

# Tareas Windows
powershell -ExecutionPolicy Bypass -File setup_windows_automation.ps1

# Validaciones
python eerr-finanzas\test_odoo_conexion.py
python agente-comex\main.py --status
python agente-comex\main.py --scan

# Verificar tareas
Get-ScheduledTask -TaskPath "\UnionX-IA\" | Format-Table TaskName, State
```
