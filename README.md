# UNION X - IA: Sistema de Automatización Financiera

**Última actualización:** 2026-04-01

## 🎯 Qué es esto

Sistema completo de automatización para UnionX que integra:
1. **Agente COMEX Gmail** — Monitorea importaciones desde China
2. **Clasificador EERR** — Automatiza clasificación contable de estados de resultados
3. **Revenue Automation** — Extrae datos y genera reportes ejecutivos

---

## 📁 Estructura de Carpetas

```
UNION X - IA/
├── CLAUDE.md                    ← INICIO: Contexto completo del proyecto (lee esto primero)
├── README.md                    ← Este archivo
├── requirements.txt             ← Dependencias Python globales
│
├── agente-comex/               ← 🤖 Agente Gmail COMEX (monitorea Steven, Felipe, Vicente)
│   ├── main.py                 ← Punto de entrada
│   ├── setup_gmail.py          ← Setup autenticación Gmail
│   ├── src/
│   │   ├── gmail_client.py
│   │   ├── email_monitor.py
│   │   ├── trigger_detector.py
│   │   └── orchestrator.py
│   ├── config/
│   │   ├── config.yaml         ← Remitentes, polling interval
│   │   ├── credentials.json    ← OAuth2 credenciales
│   │   └── token.json          ← Token Gmail (refresh_token)
│   └── data/
│       ├── inbox/             ← Adjuntos descargados
│       └── output/            ← Prompts generados
│
├── eerr-finanzas/              ← 📊 Clasificador EERR + Revenue Automation
│   ├── eerr_classifier.py      ← Motor de 88 reglas de clasificación
│   ├── generar_reporte_eerr_completo.py
│   ├── integracion_distribucion_comisiones.py
│   ├── revenue_automation.py
│   ├── data_ingestion.py
│   ├── analizar_sin_clasificar.py
│   ├── REGLAS_CLASIFICACION.json
│   └── REGLAS_NUEVAS_FEBRERO.json
│
├── odoo/                        ← 🔌 Consultas y conexión Odoo
│   ├── odoo_connection.py       ← Cliente XML-RPC
│   ├── odoo_config.json
│   └── detect_odoo_databases.py
│
├── data/                        ← 💾 Datos compartidos
│   ├── eerr/                   ← EERR mensuales originales
│   │   ├── 01_EERR_Enero_2026.xlsx
│   │   └── 02_EERR_Febrero_2026.xlsx
│   ├── planillas/              ← Análisis Contribución
│   │   └── Análisis_Contribución_Marzo_2026.xlsx
│   └── outputs/                ← Reportes generados
│       ├── EERR_CLASIFICADO.xlsx
│       ├── EERR_DISTRIBUCION_CANALES.json
│       ├── EERR_REPORTE_CANALES.html
│       └── drive_download_20260331.xlsx
│
├── test/                        ← 🧪 Scripts de prueba y diagnóstico
│   ├── EERR_PRUEBA_Febrero2026.py
│   ├── diagnosticar_eerr.py
│   ├── install_credentials.py
│   ├── quick_test.py
│   └── test_*.py
│
├── examples/                    ← 📖 Ejemplos de uso
│   └── EJEMPLO_USO.py
│
├── archive/                     ← 📦 Versiones anteriores (no usar)
│   └── junior-revenue-original/
│
└── .claude/                     ← Configuración Claude Code
    └── settings.json
```

---

## 🚀 Cómo Usar

### 1. Agente COMEX Gmail (Monitoreo automático)

**Qué hace:**
- Monitorea emails de Steven (proveedor chino), Felipe (comercial), Vicente (forwarder)
- Detecta automáticamente PI, PL, OHNSO, demandas
- Ejecuta skills `comex-workflow` y `shipping-plan` automáticamente

**Cómo ejecutar:**
```bash
# Primer uso: autenticar Gmail
cd agente-comex
python setup_gmail.py

# Modo monitor (polling cada 2 minutos)
python main.py

# Escaneo único
python main.py --scan

# Ver historial de ejecuciones
python main.py --status
```

**Estado:** 
- ✅ Listo para ejecutar
- ✅ Token Gmail configurado
- ⚠️ Registrado en Task Scheduler Windows (background)

---

### 2. Clasificador EERR (Procesamiento automático)

**Qué hace:**
- Lee EERR mensual (Excel) de Odoo
- Aplica 88 reglas de clasificación contable
- Genera 3 formatos: JSON, Excel con colores, HTML interactivo

**Cómo ejecutar:**
```bash
cd eerr-finanzas

# Procesar un EERR
python eerr_classifier.py

# Ver movimientos sin clasificar
python analizar_sin_clasificar.py mi_eerr.xlsx
```

**Output automático:**
- `mi_eerr_CLASIFICADO.xlsx` — Excel ejecutivo
- `mi_eerr_DISTRIBUCION_CANALES.json` — Input para skill
- `mi_eerr_REPORTE_CANALES.html` — Reporte visual

---

### 3. Revenue Automation (Reportes ejecutivos)

**Qué hace:**
- Extrae datos Google Drive/Sheets/email automáticamente
- Integra con EERR clasificado
- Distribuye comisiones por canal
- Genera informe ejecutivo mensual

**Automatización:**
- Lunes 9 AM → Descarga Drive + Sheets
- Día 7 → Detalle completo Sheets
- Día 10 → EERR + procesamiento completo

---

## 🔧 Configuración

### Credenciales Odoo
Archivo: `odoo/odoo_config.json`
```json
{
  "url": "https://unionxb2b.odoo.com",
  "db": "bmya-innovatek-sh-prd-6981800",
  "user": "andres@grupoeter.cl",
  "password": "<usar env var ANDRES_ODOO_PASSWORD>"
}
```

### Agente COMEX
Archivo: `agente-comex/config/config.yaml`
- Remitentes: topwillsteven@163.com, felipe@unionx.cl, vicente@seimex.cl
- Polling: 120 segundos (2 minutos)
- Gastos Chile: Se ingresan manualmente por consola

---

## 🎓 Personas Clave

- **Steven** (topwillsteven@163.com) — Proveedor chino, envía PI/PL/OHNSO
- **Felipe** (felipe@unionx.cl) — Comercial UnionX, demandas
- **Vicente** (vicente@seimex.cl) — Forwarder, cotizaciones flete
- **Andrés** — Tu usuario (andres@grupoeter.cl, GitHub: AndyunionX)

---

## 📚 Documentación Completa

Revisa estos archivos para más detalle:

| Archivo | Para qué |
|---------|----------|
| `CLAUDE.md` | Contexto general del proyecto |
| `ARQUITECTURA_FINAL.md` | Diagrama de flujos y componentes |
| `QUICK_START.md` | Inicio rápido en 5 minutos |
| `AUTOMATION_SETUP.md` | Setup de automación Windows |
| `SKILL_*.md` | Templates de skills disponibles |

---

## ⚠️ Reglas Importantes

- **Nunca editar archivos sin preguntar a Claude primero** — Andrés quiere control total
- **Confirmar acciones destructivas** — Delete, overwrite, reset
- **Validar cambios en EERR** — Las reglas de clasificación afectan análisis financiero

---

## ✨ Próximos Pasos

1. ✅ Ejecutar `python agente-comex/main.py --scan` para verificar Gmail
2. ⏳ Esperar primer email del proveedor chino (Steven) para ver flujo en acción
3. ⏳ Probar clasificación EERR con archivo de Abril 2026
4. ⏳ Ajustar gastos internos Chile en tarifa_builder.py con valores reales

---

**¿Preguntas?** Revisa `CLAUDE.md` o memoria del proyecto para contexto adicional.
