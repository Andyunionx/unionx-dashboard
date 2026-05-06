# 🤖 SETUP: REMOTE TRIGGERS AUTOMÁTICOS
## Union X - Sistema 100% Autónomo

---

## 📋 TRIGGERS A CONFIGURAR (3 Total)

### **TRIGGER 1: Lunes 9:00 AM**
**Qué hace:** Descarga Google Drive + Google Sheets, inyecta en Excel

### **TRIGGER 2: Día 7 del Mes**  
**Qué hace:** Descarga Google Sheets detallado con comisiones por KAM

### **TRIGGER 3: Día 10 del Mes**
**Qué hace:** Descarga EERR del email de Victor → Ejecuta skill `distribucion-comisiones-canal`

---

## 🔧 SETUP (Paso a Paso)

### Paso 1: Instala Dependencias

```bash
pip install gspread google-auth-oauthlib google-auth-httplib2 google-api-python-client pandas openpyxl
```

### Paso 2: Configura Google Credentials

Para que Claude Code descargue automáticamente de Google Drive y Google Sheets:

1. Ve a: https://console.cloud.google.com/
2. Crea un proyecto (ej: "Union X Revenue")
3. Habilita estas APIs:
   - Google Drive API
   - Google Sheets API
4. Crea **Service Account**:
   - IAM & Admin → Service Accounts → Create
   - Descarga JSON con credenciales
   - Guarda como: `credentials.json` en `Junior Revenue/`

5. Comparte las URLs con la Service Account:
   - Google Drive file: Comparte con el email de la service account
   - Google Sheet: Comparte con el email de la service account

### Paso 3: Variables de Entorno

Crea archivo `.env` en `Junior Revenue/`:

```bash
# Google Credentials
GOOGLE_APPLICATION_CREDENTIALS=credentials.json

# Email Victor (para descargar EERR)
VICTOR_EMAIL=victor@unionx.cl
VICTOR_PASSWORD=tu_contraseña_aqui  # O usa "App Password" si 2FA está habilitado
```

### Paso 4: Configura config.json

Ya está creado, pero revisa:

```json
{
  "google_drive_file_id": "1K11y6icDm9M3X3glGUVCOe4HsbpWpEBm",
  "google_sheets_id": "1z-HLHEuj__HjNjf7hS4sIhU5QvoNiUJJ1BH965y4JEI",
  "google_sheets_gid": 1518723659,
  "service_account_json": "credentials.json"
}
```

### Paso 5: Crea los Triggers en Claude Code

En Claude Code, ejecuta `/schedule` **tres veces**:

---

## 📅 TRIGGER 1: LUNES 9:00 AM

```
/schedule
```

Configura:
- **Name:** `Revenue - Lunes 9 AM - Descarga Drive + Sheets`
- **Cron:** `0 9 * * 1` (Lunes 9:00 AM)
- **Prompt:**

```
Ejecuta trigger automático: Lunes 9 AM - Union X Revenue

INSTRUCCIONES:
1. Carga variables de entorno desde .env
2. Ejecuta: python data_ingestion.py --trigger lunes9am --config config.json
3. Descripción de qué hace:
   - Descarga archivo desde Google Drive (venta, COGS, margen directo por CANAL)
   - Lee Google Sheets (comisiones por KAM)
   - Inyecta en: C:\Users\LENOVO\Desktop\Junior Revenue\Análisis Contribución 2026 V02.02.xlsx
   - Pestaña: "Análisis Resultados"
   - Actualiza: mes actual en adelante

UBICACIÓN:
- Script: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/data_ingestion.py
- Config: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/config.json
- Excel: C:\Users\LENOVO\Desktop\Junior Revenue\Análisis Contribución 2026 V02.02.xlsx

ALERTAS:
- Si falla descarga: Reporta error específico
- Si falla inyección: Verifica que Excel no esté abierto
- Si falla autenticación: Verifica credenciales en .env y config.json

SALIDA:
- Log en: outputs/trigger_lunes9am_YYYYMMDD.log
```

---

## 📅 TRIGGER 2: DÍA 7 DEL MES

```
/schedule
```

Configura:
- **Name:** `Revenue - Día 7 - Descarga Google Sheets Detail`
- **Cron:** `0 9 7 * *` (Día 7, 9:00 AM)
- **Prompt:**

```
Ejecuta trigger automático: Día 7 del Mes - Union X Revenue

INSTRUCCIONES:
1. Carga variables de entorno desde .env
2. Ejecuta: python data_ingestion.py --trigger dia7 --config config.json
3. Descripción de qué hace:
   - Lee Google Sheets detallado (venta, COGS, margen directo, COMISIONES por CANAL/KAM)
   - URL: https://docs.google.com/spreadsheets/d/1z-HLHEuj__HjNjf7hS4sIhU5QvoNiUJJ1BH965y4JEI/edit
   - Inyecta en: C:\Users\LENOVO\Desktop\Junior Revenue\Análisis Contribución 2026 V02.02.xlsx
   - Pestaña: "Análisis Resultados"
   - Actualiza: mes actual en adelante

UBICACIÓN:
- Script: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/data_ingestion.py
- Config: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/config.json

SALIDA:
- Log en: outputs/trigger_dia7_YYYYMMDD.log
- Excel actualizado con comisiones detalladas
```

---

## 📅 TRIGGER 3: DÍA 10 DEL MES (EERR + SKILL)

```
/schedule
```

Configura:
- **Name:** `Revenue - Día 10 - EERR + Skill Distribución Comisiones`
- **Cron:** `0 9 10 * *` (Día 10, 9:00 AM)
- **Prompt:**

```
Ejecuta trigger automático: Día 10 del Mes - Union X Revenue

INSTRUCCIONES:

1. DESCARGAR EERR:
   - Carga variables de entorno (.env): VICTOR_EMAIL, VICTOR_PASSWORD
   - Ejecuta: python data_ingestion.py --trigger dia10 --victor-email $VICTOR_EMAIL --victor-password $VICTOR_PASSWORD
   - Script descarga EERR desde email de victor@unionx.cl automáticamente
   - Guarda en: C:\Users\LENOVO\Desktop\Junior Revenue\EERR_[fecha].xlsx

2. EJECUTAR SKILL DISTRIBUCION-COMISIONES-CANAL:
   - Una vez descargado el EERR, invoca la skill:
   - /distribucion-comisiones-canal
   - Proporciona:
     * EERR descargado: C:\Users\LENOVO\Desktop\Junior Revenue\EERR_[fecha].xlsx
     * Planilla destino: C:\Users\LENOVO\Desktop\Junior Revenue\Análisis Contribución 2026 V02.02.xlsx
     * Pestaña: "Análisis Resultados"
   
3. INYECTAR EN EXCEL:
   - Skill ejecuta automáticamente
   - Distribuye comisiones por canal
   - Inyecta en pestaña "Análisis Resultados"
   - Actualiza: mes actual en adelante

4. VALIDAR:
   - Verifica que Excel se actualizó correctamente
   - Si hay errores en skill, reporta

FLUJO ESPERADO:
   Script descarga EERR 
     ↓
   Invoca skill distribucion-comisiones-canal
     ↓
   Skill procesa y distribuye comisiones
     ↓
   Skill inyecta en Excel
     ↓
   Excel actualizado

UBICACIÓN:
- Script: g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/Junior Revenue/data_ingestion.py
- Planilla: C:\Users\LENOVO\Desktop\Junior Revenue\Análisis Contribución 2026 V02.02.xlsx

SALIDA:
- Log en: outputs/trigger_dia10_YYYYMMDD.log
- Excel con comisiones distribuidas
```

---

## ✅ CHECKLIST POST-SETUP

- [ ] Dependencias instaladas (gspread, google-auth, etc.)
- [ ] Credentials.json creado y guardado en carpeta
- [ ] .env configurado con VICTOR_EMAIL y VICTOR_PASSWORD
- [ ] config.json actualizado
- [ ] Google Drive file compartido con service account
- [ ] Google Sheet compartido con service account
- [ ] Trigger 1 (Lunes 9 AM) creado
- [ ] Trigger 2 (Día 7) creado
- [ ] Trigger 3 (Día 10) creado
- [ ] Carpeta `outputs/` creada en Junior Revenue

---

## 🧪 PRUEBA MANUAL (Antes de Automatizar)

Ejecuta cada trigger manualmente primero:

```bash
# Test Trigger 1
python data_ingestion.py --trigger lunes9am --config config.json

# Test Trigger 2
python data_ingestion.py --trigger dia7 --config config.json

# Test Trigger 3 (requiere VICTOR_EMAIL y VICTOR_PASSWORD)
python data_ingestion.py --trigger dia10 --victor-email "victor@unionx.cl" --victor-password "tu_password"
```

Si todos pasan, entonces configura los triggers automáticos.

---

## 📊 FLUJO AUTOMÁTICO FINAL

```
CADA SEMANA (Lunes 9 AM)
├─ Descarga Drive (venta, COGS, margen por canal)
├─ Descarga Google Sheets (comisiones por KAM)
└─ Inyecta en Excel → Análisis Resultados

DÍA 7 CADA MES
├─ Descarga Google Sheets detail
└─ Inyecta en Excel → Análisis Resultados

DÍA 10 CADA MES
├─ Descarga EERR del email Victor
├─ Ejecuta skill distribucion-comisiones-canal
└─ Inyecta en Excel → Análisis Resultados

DESPUÉS CADA INYECCIÓN
├─ Revenue automation genera reportería
└─ Notifica cambios críticos
```

---

## 🔐 Seguridad

**Credenciales:**
- Guarda `credentials.json` en `.gitignore` (no commits)
- Variables en `.env` (no commits)
- Considera usar Google Cloud Secret Manager para prod

**Permisos:**
- Service Account solo necesita acceso de lectura a Drive/Sheets
- IMAP necesita contraseña (usa App Password si tienes 2FA)

---

## ❓ FAQ

**P: ¿Qué pasa si el trigger falla?**  
R: Revisa logs en `outputs/trigger_[nombre]_YYYYMMDD.log`. Claude Code notificará del error.

**P: ¿Puedo editar Excel mientras corre un trigger?**  
R: NO. Los triggers fallarán si el archivo está abierto.

**P: ¿Cómo sé que funcionó?**  
R: Revisa Excel → Análisis Resultados → Datos actualizados. O revisa log.

**P: ¿Los triggers se ejecutan en mi zona horaria?**  
R: Sí, la cron usa tu timezone local.

---

*Sistema automatizado 100% autónomo - Union X Revenue Management*
