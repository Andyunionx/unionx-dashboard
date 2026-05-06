# 🔧 INSTALACIÓN FINAL - SISTEMA AUTOMATIZADO
## Union X Revenue Management

**Fecha:** 31-03-2026  
**Estado:** En instalación / Pruebas en curso

---

## ✅ PASOS COMPLETADOS

- [x] Dependencias Python instaladas (gspread, google-auth, pandas, openpyxl)
- [x] Scripts de ingestión creados (`data_ingestion.py`, `test_ingestion.py`)
- [x] Configuración template creada (`.env.template`, `config.json`)
- [x] Tests de validación creados
- [ ] Credenciales Google configuradas
- [ ] Triggers remotos configurados
- [ ] Prueba completa del sistema

---

## 🚀 PASO 1: CREAR CREDENCIALES DE GOOGLE (5 minutos)

### 1.1 Accede a Google Cloud Console

```
https://console.cloud.google.com/
```

### 1.2 Crea un nuevo proyecto

1. Click en el selector de proyectos (arriba)
2. Click "New Project"
3. Nombre: `Union X Revenue`
4. Click "Create"
5. Espera a que se cree

### 1.3 Habilita Google Drive API

1. En la barra de búsqueda, busca: "Google Drive API"
2. Click en el resultado
3. Click "Enable"

### 1.4 Habilita Google Sheets API

1. En la barra de búsqueda, busca: "Google Sheets API"
2. Click en el resultado
3. Click "Enable"

### 1.5 Crea Service Account

1. Ve a: IAM & Admin → Service Accounts
2. Click "Create Service Account"
3. Nombre: `union-x-revenue-bot`
4. Click "Create and Continue"
5. Click "Continue" en los pasos siguientes
6. Click "Done"

### 1.6 Descarga JSON de credenciales

1. En la tabla de Service Accounts, haz click en `union-x-revenue-bot`
2. Ve a "Keys" tab
3. Click "Add Key" → "Create new key"
4. Selecciona "JSON"
5. Click "Create"
6. Se descargará un JSON automáticamente
7. Guarda como: `credentials.json` en tu carpeta `Junior Revenue`

### 1.7 Comparte Google Drive file con Service Account

1. Abre: https://drive.google.com/file/d/1K11y6icDm9M3X3glGUVCOe4HsbpWpEBm/view
2. Click derecha "Share"
3. En tu JSON descargado, busca el campo: `"client_email": "...@...iam.gserviceaccount.com"`
4. Copia ese email
5. Pega en el campo "Share" de Google Drive
6. Dale acceso "Editor"
7. Click "Share"

### 1.8 Comparte Google Sheet con Service Account

1. Abre: https://docs.google.com/spreadsheets/d/1z-HLHEuj__HjNjf7hS4sIhU5QvoNiUJJ1BH965y4JEI
2. Repite los pasos 1.7 (comparte con el email de la Service Account)

---

## 📝 PASO 2: CREAR ARCHIVO `.env`

En la carpeta `Junior Revenue/`:

1. Copia `.env.template` → `.env`
2. Abre `.env` y configura:

```bash
# Google Credentials (copiar desde JSON descargado)
GOOGLE_APPLICATION_CREDENTIALS=credentials.json

# Email de Victor
VICTOR_EMAIL=victor@unionx.cl

# Password de Victor (usar App Password si tiene 2FA habilitado)
VICTOR_PASSWORD=tu_app_password_aqui

# Rutas (normalmente no necesitan cambio)
DESKTOP_PATH=C:\Users\LENOVO\Desktop\Junior Revenue
CONTRIBUCION_FILE=Análisis Contribución 2026 V02.02.xlsx
```

### ⚠️ App Password para Victor

Si Victor tiene 2FA habilitado en su Gmail:

1. Ve a: https://myaccount.google.com/apppasswords
2. Selecciona: Mail → Windows Computer
3. Google genera una contraseña de 16 caracteres
4. Pega esa contraseña en `VICTOR_PASSWORD`

---

## 🧪 PASO 3: EJECUTAR TESTS

Una vez configurados `.env` y `credentials.json`:

```bash
cd "g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue"
python test_ingestion.py
```

**Resultado esperado:**
```
✓ Validación Excel
✓ Simulación descarga
✓ Simulación inyección
✓ Validación credenciales
✓ Workflow Lunes 9AM

Total: 5/5 tests pasados
🎉 TODOS LOS TESTS PASARON
```

Si hay errores, revisa:
- ¿ `credentials.json` está en la carpeta?
- ¿Shared Google Drive y Sheet con Service Account?
- ¿ `.env` está correctamente configurado?

---

## 📅 PASO 4: CONFIGURAR TRIGGERS EN CLAUDE CODE

Una vez que los tests pasen, configura los 3 triggers automáticos.

### TRIGGER 1: Lunes 9:00 AM

En Claude Code ejecuta:
```
/schedule
```

Completa:
- **Name:** `Revenue - Lunes 9 AM`
- **Cron:** `0 9 * * 1`
- **Prompt:**

```
Ejecuta trigger: Lunes 9 AM - Union X Revenue

1. Carga .env desde carpeta
2. Ejecuta: python data_ingestion.py --trigger lunes9am --config config.json
3. Verifica logs en outputs/
4. Si falla, reporta error específico

Ubicación: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/
```

### TRIGGER 2: Día 7 del Mes 9:00 AM

```
/schedule
```

- **Name:** `Revenue - Día 7`
- **Cron:** `0 9 7 * *`
- **Prompt:**

```
Ejecuta trigger: Día 7 - Union X Revenue

1. Carga .env
2. Ejecuta: python data_ingestion.py --trigger dia7 --config config.json
3. Verifica que Google Sheet se descargó
4. Valida inyección en Excel

Ubicación: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/
```

### TRIGGER 3: Día 10 del Mes 9:00 AM (EERR + SKILL)

```
/schedule
```

- **Name:** `Revenue - Día 10 - EERR + Skill`
- **Cron:** `0 9 10 * *`
- **Prompt:**

```
Ejecuta trigger: Día 10 - EERR + Skill - Union X Revenue

1. Carga .env
2. Ejecuta: python data_ingestion.py --trigger dia10 --config config.json
   (Script descarga EERR automáticamente)
3. Una vez descargado EERR, ejecuta skill:
   /distribucion-comisiones-canal
   - EERR: C:\Users\LENOVO\Desktop\Junior Revenue\EERR_[fecha].xlsx
   - Destino: Análisis Contribución 2026 V02.02.xlsx
4. Verifica inyección en Excel

Ubicación: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/
```

---

## ✨ PASO 5: PRUEBA MANUAL INICIAL

Antes de confiar en los triggers automáticos, hazlos manualmente una vez:

```bash
# Test Trigger 1
python data_ingestion.py --trigger lunes9am --config config.json

# Test Trigger 2
python data_ingestion.py --trigger dia7 --config config.json

# Test Trigger 3 (requiere EERR)
python data_ingestion.py --trigger dia10 --config config.json
```

Si todos funcionan → Configura triggers en Claude Code

---

## 📊 VALIDACIÓN POST-INSTALACIÓN

Después de cada trigger, valida:

1. **Excel actualizado:**
   - Abre: `Análisis Contribución 2026 V02.02.xlsx`
   - Ve a: Pestaña "Análisis Resultados"
   - Verifica que hay datos nuevos
   - Fecha coincide con fecha de ejecución

2. **Logs generados:**
   - Carpeta: `outputs/`
   - Archivo: `trigger_[tipo]_YYYYMMDD.log`
   - Revisa que no hay errores

3. **Archivos descargados:**
   - Google Drive: Archivo local creado
   - Google Sheets: Datos leídos
   - EERR: Descargado del email

---

## 🎯 TIMELINE DE IMPLEMENTACIÓN

```
HOY
├─ [x] Dependencias instaladas
├─ [ ] Paso 1: Credenciales Google (5 min)
├─ [ ] Paso 2: Configurar .env (2 min)
└─ [ ] Paso 3: Ejecutar tests (2 min)

MAÑANA
├─ [ ] Paso 4: Configurar Trigger 1
├─ [ ] Paso 4: Configurar Trigger 2
├─ [ ] Paso 4: Configurar Trigger 3
└─ [ ] Paso 5: Prueba manual (30 min)

PRÓXIMA SEMANA
├─ Lunes 9 AM → Trigger 1 ejecuta automáticamente
├─ Verifica que Excel se actualiza
└─ Listo para producción

PRÓXIMAS 2 SEMANAS
├─ Día 7 → Trigger 2 ejecuta
├─ Día 10 → Trigger 3 + Skill ejecutan
└─ Sistema completamente operativo
```

---

## 📞 TROUBLESHOOTING

| Problema | Solución |
|----------|----------|
| "PermissionError al leer Excel" | Cierra Excel antes de ejecutar triggers |
| "Google Drive: 404 Not Found" | Service Account no tiene acceso al archivo. Comparte nuevamente |
| "Google Sheets: 403 Forbidden" | Service Account no tiene acceso. Comparte nuevamente |
| "IMAP: Login failed" | Verifica VICTOR_PASSWORD (usa App Password si 2FA) |
| "UnicodeEncodeError" | Cambio de encoding aplicado, debería estar resuelto |

---

## ✅ CHECKLIST FINAL

- [ ] Python 3.12+ instalado
- [ ] Dependencias instaladas (gspread, google-auth, etc.)
- [ ] Google Service Account creado
- [ ] `credentials.json` descargado y guardado
- [ ] Google Drive file compartido con Service Account
- [ ] Google Sheet compartido con Service Account
- [ ] `.env` configurado con credenciales
- [ ] `test_ingestion.py` pasó todos los tests
- [ ] Trigger 1 (Lunes 9 AM) configurado
- [ ] Trigger 2 (Día 7) configurado
- [ ] Trigger 3 (Día 10) configurado
- [ ] Pruebas manuales ejecutadas con éxito

---

## 🎉 SIGUIENTE PASO

1. **Configura Google Credentials** (Pasos 1.1 a 1.8 arriba)
2. **Crea `.env`** (Paso 2)
3. **Ejecuta test:** `python test_ingestion.py`
4. Si todos los tests pasan → **Configura 3 triggers en Claude Code**

¿Necesitas ayuda con algún paso? Avísame cuál.

---

*Sistema de automatización Revenue Management - Union X*  
*Instalación Final - 31-03-2026*
