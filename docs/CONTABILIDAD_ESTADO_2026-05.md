# 📚 App Contabilidad / Agente Cobranza — Estado al 25-may-2026

> **Para retomar en otra sesión.** Este documento es self-contained:
> alguien que lo lea entiende dónde estamos parados sin contexto previo.

---

## 🎯 Sumario ejecutivo

El **agente de cobranza** (que reemplaza los scripts de Martín en su PC)
está implementado, mergeado a `main` (PR #54), pero **causó un incidente de
producción**: durante 3 días sobrescribió Excel en Drive con data faltante.

**Estado actual:**
- ✅ Cron desactivado en main (commit `7029688` del 25-may)
- ⏳ Esperando que Víctor reporte exactamente qué data se perdió
- ⏳ Esperando que Andrés/Víctor restauren versiones desde historial de Drive
- ❌ Diagnóstico de root cause pendiente
- ❌ Fix pendiente

**Próxima sesión:** retomar con feedback concreto de Víctor.

---

## 🚨 El incidente (23-25 may 2026)

### Línea de tiempo

| Fecha | Evento |
|---|---|
| **22-may** | Pushé última versión del agente a `feat/agente-cobranza`. Validé paridad técnica de Paris (headers + filas ±2) con `--no-upload`. Andrés mandó email a Víctor para validación humana. |
| **22-23 may** | Andrés mergeó PR #54 a `main` **sin esperar feedback de Víctor**. Esto activó el cron diario automático. |
| **23-may 07:00 Chile** | Primera corrida automática del cron — sobreescribió los 5 Excel en Drive |
| **24-may 07:00** | Segunda corrida |
| **25-may 07:00** | Tercera corrida |
| **25-may mediodía** | Andrés reporta: "Tuvimos problemas con la automatización. Borro información de los drive. En Paris se perdió todo lo de mayo que estaba en estado pagado." |
| **25-may tarde** | Cron desactivado en commit `7029688` (comentado el `schedule:` del workflow YAML, dejado solo `workflow_dispatch`). |

### Hipótesis del root cause (pendiente confirmar)

Las 3 más probables, ordenadas por likelihood:

1. **Filtros de Odoo distintos a los de Martín** — mi código usa
   `("date", ">=", fecha_desde_300d)` y `("state", "=", "posted")`.
   Capaz Martín usa `invoice_date` (no `date`), o no filtra por `state`,
   o usa otra ventana de tiempo. Si docs de mayo no entran a mi filtro,
   la hoja `PAGADAS` regenerada queda con menos filas que la original.

2. **Hojas no preservadas con data manual** — el YAML de Paris tiene
   `hojas_preservar: [PAGOS, DINAMICAS, POR PAGAR, PAGO CENCO, Hoja2]`.
   Si Víctor cargaba data manual encima de hojas que el agente regenera
   (`PAGADAS`, `BOL PENDIENTE DE PAGO`, etc.), esa data se perdió.

3. **Bug en `excel_updater.py`** al regenerar hojas — quizás el
   `del wb[nombre_hoja]` + `create_sheet` rompe referencias / fórmulas
   en otras hojas que las usaban.

### Lo que YA hice como mitigación

- ✅ Commit `7029688` en main: comentar el `schedule:` del workflow para que
  no vuelva a correr automáticamente.
- ✅ Mantengo `workflow_dispatch` para poder disparar manual si necesitamos
  debug (con `dry_run=true` o `no_upload=true`).

---

## 📦 Lo que está implementado y mergeado en `main`

### Estructura del repo

```
agente-cobranza/                       (mergeado en PR #54)
├── actualizar_cliente.py              # script genérico, lee YAML
├── lib/
│   ├── odoo_helpers.py                # las 6 hojas estándar
│   ├── drive_helpers.py               # bajar/subir Drive API
│   └── excel_updater.py               # update preservando hojas
├── clientes/
│   ├── _template.yaml
│   ├── paris.yaml                     # 5 clientes migrados de Martín
│   ├── falabella.yaml
│   ├── shopify.yaml
│   ├── meli_1.yaml
│   └── meli_2.yaml
├── requirements.txt
└── README.md

.github/workflows/agente_cobranza_diario.yml
                                       # cron DESACTIVADO (25-may commit 7029688)

docs/
├── COMO_AGREGAR_CLIENTE.md            # guía Víctor sin código Python
├── FLUJO_COBRANZA_BOLETA.md           # doc técnica limpia
├── SETUP_VICTOR.md                    # cómo trabaja Víctor en su sesión
└── memoria/                           # wiki versionada del equipo
    ├── README.md
    └── flujo_actualizacion_clientes.md
```

### Las 6 hojas estándar que actualiza el agente

| Hoja | Modelo Odoo | Filtro |
|---|---|---|
| `BOL PENDIENTE DE PAGO` | `account.move` | `move_type=out_invoice, payment_state=not_paid, state=posted` |
| `REVERTIDOS` | `account.move` | `move_type=out_invoice, payment_state=reversed` |
| `NC` | `account.move` | `move_type=out_refund` |
| `FACTURAS PENDIENTES DE PAGO` | `account.move` | `payment_state in [not_paid,partial], doc_type_id=1` (sin filtro cliente) |
| `PAGADAS` | `account.move` | `payment_state=paid`, **últimos 300 días** ← sospechoso del incidente |
| `yuju` | `sale.order` | últimos 200 días |

### Clientes configurados

| Cliente | Slug | Excel destino en Drive (rel. a `Trabajado clientes/`) |
|---|---|---|
| MELI 1 | `meli_1` | `MELI/MELI 1 05_2026 (PRUEBA VCR2).xlsx` |
| MELI 2 | `meli_2` | `MELI/MELI 2 2026.xlsx` |
| Falabella Fcom | `falabella` | `FALABELLA/Falabella desde abril 2026 B.xlsx` |
| Shopify / Mercado Pago | `shopify` | `MERCADO PAGO/MERCADO PAGO 2026.xlsx` |
| Paris | `paris` | `PARIS/PARIS 2026.xlsx` |

### Secretos y accesos

| Cosa | Estado |
|---|---|
| Secret `VICTOR_ODOO_PASSWORD` en GitHub | ✅ Andrés lo creó el 22-may |
| Service account `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com` | ✅ activo |
| Drive `Trabajado clientes` (id `19EsjfScn5YhJjNVMvT8Qkt3xZBGpGG16`) compartido con el bot | ✅ Víctor lo compartió el 22-may |

---

## 📋 Plan para retomar

### Paso 1 — Recuperación de data (Andrés + Víctor)

1. Víctor reporta a Andrés qué data específica se perdió:
   - ¿En qué hoja? (probablemente `PAGADAS`)
   - ¿Mayo 2025 o mayo 2026?
   - ¿Era data de Odoo o manual?
2. Andrés/Víctor restauran desde **historial de versiones de Drive** los 5
   Excel a la versión del 22-may (antes del primer cron del agente):
   - `PARIS / PARIS 2026_ACTUALIZADO.xlsx`
   - `MELI / MELI 1 05_2026 (PRUEBA VCR2)_ACTUALIZADO.xlsx`
   - `MELI / MELI 2 2026_ACTUALIZADO.xlsx`
   - `FALABELLA / Falabella desde abril 2026 B_ACTUALIZADO.xlsx`
   - `MERCADO PAGO / MERCADO PAGO 2026_ACTUALIZADO.xlsx`
3. Martín reactiva su Task Scheduler local **temporalmente** para que el
   flujo manual siga funcionando hasta que arreglemos el agente.

### Paso 2 — Diagnóstico (yo)

Con el feedback puntual de Víctor:

1. Comparar el script original de Martín (`C:\Users\marti\odoo-mcp\rebuild_paris.py`)
   con `agente-cobranza/lib/odoo_helpers.py`, fila por fila, para
   identificar diferencias en filtros Odoo.
2. Bajar el último Excel del agente que quedó subido (del 25-may) y
   compararlo con la versión restaurada de Martín para ver exactamente
   qué docs faltan.
3. Identificar el bug. Hipótesis principal: campo `date` vs `invoice_date`
   o `state=posted` filtrando demasiado.

### Paso 3 — Fix

Según root cause:
- Si es el filtro `date` → cambiar a `invoice_date` en los `descargar_*`
- Si es `state=posted` → relajar el filtro o agregar otros estados
- Si es preservar hojas → agregar las que faltaban a `hojas_preservar`
- Si es bug del updater → reescribir la lógica de regeneración

### Paso 4 — Re-validar antes de reactivar

1. Disparar workflow con `cliente=paris` + `no_upload=true`
2. Víctor compara el artifact contra el archivo restaurado de Drive
3. Cuando Víctor confirme "OK, idéntico", repetir para los otros 4
4. Cuando los 5 estén OK, reactivar el cron descomentando el `schedule:`
   en el workflow (revertir commit `7029688`)
5. Martín desactiva su Task Scheduler local

---

## 🧠 Lecciones aprendidas

1. **No mergear a main sin validación humana del end-to-end.** El plan
   original era: merge solo después de que Víctor validara el artifact.
   Se saltó ese paso. **Regla nueva:** features que tocan producción
   (escriben a Drive / Odoo / DB) requieren OK explícito de usuario antes
   del merge a main.

2. **Validación de paridad ≠ validación de correctitud.** Que cantidad de
   filas matcheen (con ±2 de timing) no garantiza que los docs son los
   mismos. **Regla nueva:** comparar también checksums o ids de docs
   específicos.

3. **El `_ACTUALIZADO.xlsx` de Martín NO era inmutable** — yo asumí que
   el bot solo iba a hacer `update` del file_id existente. Pero el
   `update` REEMPLAZA todo el contenido, no fusiona. Si Víctor cargaba
   data manual encima del archivo de Martín, mi update la borraba.
   **Regla nueva:** documentar explícitamente qué hojas NO tienen data
   manual y cuáles sí.

4. **Drive guarda 30 días de versiones** — confiamos en eso para
   recuperación. Documentado en `docs/SETUP_VICTOR.md` que el usuario
   sepa cómo restaurar.

---

## 🔗 Referencias rápidas

- **PR del agente** (mergeado): https://github.com/Andyunionx/unionx-dashboard/pull/54
- **Workflow desactivado**: `.github/workflows/agente_cobranza_diario.yml`
- **Commit de desactivación**: `7029688`
- **Branch del agente**: `feat/agente-cobranza` (sigue ahí, ya mergeada)
- **Drive `Trabajado clientes`**: https://drive.google.com/drive/folders/19EsjfScn5YhJjNVMvT8Qkt3xZBGpGG16
- **MD original con creds de Víctor** (queda en Drive, no en repo):
  `data/contabilidad/cobranza/actualizacion_clientes.md` en Mi unidad
- **Email a Víctor** del 22-may: enviado, asunto "[Cobranza] Migración a GitHub Actions"

---

_Documento generado: 25-may-2026 · Última sesión cerrada con cron desactivado._
