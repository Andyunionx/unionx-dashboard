# 🚨 Incidente Paris — Mayo 2026

> **Documento vivo.** Víctor completa las secciones marcadas con
> 🟡 **PARA VÍCTOR**. Lo demás lo arma Andrés/Claude.

**Estado:** ⏳ esperando feedback de Víctor para diagnosticar root cause.
**Cron:** OFF (desactivado 25-may, commit `7029688`).

---

## 📅 Línea de tiempo

| Fecha | Evento |
|---|---|
| 22-may | PR #54 mergeado a `main`. Cron diario activado. |
| 23-may 07:00 | 1ra corrida automática del agente — sobreescribió 5 Excel en Drive. |
| 24-may 07:00 | 2da corrida. |
| 25-may 07:00 | 3ra corrida. |
| 25-may mediodía | Andrés detecta: *"Tuvimos problemas. Borró información de los Drive. En Paris se perdió todo lo de mayo que estaba en estado pagado."* |
| 25-may tarde | Cron desactivado (`7029688`). |
| 26-may | Setup de Víctor en el repo. Este doc creado para que Víctor complete qué se perdió. |

---

## 🟡 PARA VÍCTOR — Completá esta sección directamente con Claude

> Víctor: abrí Claude Code en este repo y decile algo como:
> *"Editá `docs/memoria/incidente_paris_2026-05.md` sección 'Qué se perdió'
> con lo siguiente: ..."* y le contás textual lo que te pasó.
> Claude lo formatea y lo deja prolijo. Vos commiteás y pusheás.

### 1. ¿En qué hoja exactamente se perdió data?

<!-- Marcá con X. Si fue en más de una, marcá todas. -->

- [ ] `BOL PENDIENTE DE PAGO`
- [ ] `REVERTIDOS`
- [ ] `NC`
- [ ] `FACTURAS PENDIENTES DE PAGO`
- [ ] `PAGADAS` ← sospecha principal
- [ ] `yuju`
- [ ] `PAGOS` (debería estar preservada — si se perdió acá es bug grave)
- [ ] `DINAMICAS` (debería estar preservada)
- [ ] `POR PAGAR` (debería estar preservada)
- [ ] `PAGO CENCO` (debería estar preservada)
- [ ] `Hoja2` (debería estar preservada)
- [ ] Otra: _______________

### 2. ¿Qué tipo de data se perdió?

<!-- Esto es lo más importante para identificar el root cause. -->

- [ ] **Filas con documentos que NO venían de Odoo** (data manual que cargabas vos)
- [ ] **Columnas extras** que vos agregabas a una hoja regenerada (ej: una col "ya cobrado por Paris")
- [ ] **Documentos de Odoo que sí están en Odoo** pero el agente no los trajo
- [ ] **Fórmulas que dejaron de funcionar** (no es "data perdida" estrictamente)
- [ ] **Formato/colores/anchos** de la hoja
- [ ] Otra cosa: _______________

### 3. ¿De qué mes era la data perdida?

- [ ] Mayo 2026 (el mes en curso)
- [ ] Mayo 2025 (1 año atrás)
- [ ] Mes anterior reciente: _______________
- [ ] Varios meses

> **Por qué pregunto:** la hoja `PAGADAS` solo trae **últimos 300 días**
> desde la fecha contable. Si hoy es 25-may-2026, eso cubre desde julio
> 2025 hasta hoy. **No cubre mayo 2025 ni antes**. Si la data perdida es
> anterior a julio 2025, esa es la causa.

### 4. ¿Esa data específica también está cargada en Odoo?

- [ ] Sí, está en Odoo (entonces el agente debería haberla traído)
- [ ] No, era data 100% manual que vos cargabas en el Excel
- [ ] Mitad y mitad
- [ ] No estoy seguro

### 5. Si tenés un ejemplo concreto, pegalo acá

<!-- Ej: "el doc BEL 461400 del 15-may-2026 estaba en Paris 2026.xlsx hoja PAGADAS
     con un comentario 'ya cobrado vía depósito'. Después del agente desapareció el comentario." -->

```
(Víctor: pegá ejemplo acá)
```

### 6. ¿Cuál es tu workflow habitual con la hoja `PAGADAS`?

<!-- Para entender qué hacías vos en esa hoja que el agente rompió. -->

- [ ] Solo la consultaba, no la editaba
- [ ] Le agregaba columnas extras (ej: estado de cobranza, comentarios)
- [ ] Le agregaba filas manuales (docs que no venían de Odoo)
- [ ] Aplicaba formato/colores para mi seguimiento
- [ ] Otra cosa: _______________

---

## 🔍 Hipótesis del root cause (Andrés/Claude)

Con la info que tenemos hoy (sin feedback de Víctor todavía), las 3
hipótesis más fuertes son:

### Hipótesis A — Data manual sobrescrita en `PAGADAS` ⭐ (más probable)

El agente regenera la hoja `PAGADAS` entera cada corrida con
`del wb[hoja]` + `create_sheet`. Si Víctor agregaba columnas o filas
manuales a esa hoja, se borran al día siguiente.

**Cómo confirmar:** preguntas 1, 2 y 6 del bloque "PARA VÍCTOR".

**Fix si se confirma:**
- Opción 1: mover `PAGADAS` a `hojas_preservar` (el agente deja de tocarla)
- Opción 2: el agente escribe en una hoja nueva `PAGADAS_BOT`, Víctor cruza manualmente
- Opción 3: el agente mergea (preserva columnas extras de Víctor) — más trabajo

### Hipótesis B — Ventana de 300 días deja docs viejos afuera

Si Víctor tenía data en `PAGADAS` de antes de **2025-07-29**
(300 días antes del 25-may-2026), el agente nunca la trajo y al regenerar
la hoja, esos docs viejos desaparecieron.

**Cómo confirmar:** pregunta 3 del bloque "PARA VÍCTOR" (mes 2025 vs 2026).

**Fix si se confirma:**
- Ampliar ventana a 730 días (`ventanas_dias.pagadas: -730` en `paris.yaml`)
- O quitar el filtro de fecha completamente para `PAGADAS`

### Hipótesis C — Hojas preservadas no se preservaron bien

Si la data perdida estaba en `PAGOS` / `DINAMICAS` / `POR PAGAR` /
`PAGO CENCO` / `Hoja2` → es bug del `excel_updater.py`.

**Cómo confirmar:** pregunta 1 del bloque "PARA VÍCTOR" (hoja exacta).

**Fix si se confirma:** auditar `lib/excel_updater.py` línea por línea.

---

## ✅ Plan para reactivar el cron (cuando se arregle)

1. Víctor restaura los 5 Excel desde historial de Drive (versión del 22-may)
2. Andrés/Claude implementa el fix según root cause
3. Validación 1: workflow_dispatch con `cliente=paris` + `no_upload=true`
4. Víctor compara artifact contra Excel restaurado
5. Víctor confirma: "OK, idéntico" o "Falta esto"
6. Si OK → repetir para los 4 clientes restantes
7. Cuando los 5 OK → revertir commit `7029688` (descomentar `schedule:`)
8. Martín desactiva su Task Scheduler local

---

## 🛡️ Salvaguardas a agregar (independientes del root cause)

Para que esto **no pueda volver a pasar**:

1. **Diff pre-upload obligatorio:** el workflow baja el Excel actual de Drive,
   genera el nuevo, compara. Si el diff de filas/hojas excede X% sin flag
   `--allow-large-diff`, aborta y sube solo como artifact para revisión manual.

2. **Backup automático antes de cada corrida:** copiar el Excel actual con
   sufijo `_BACKUP_YYYY-MM-DD.xlsx` antes de sobreescribir. Limpiar backups
   >30 días.

3. **Notificación Slack/mail:** cada corrida del cron manda resumen con
   "filas escritas por hoja por cliente". Si los números cambian mucho
   día a día, alguien lo nota antes de que se acumule el daño.

---

## 🔗 Referencias

- Estado general: `docs/CONTABILIDAD_ESTADO_2026-05.md`
- Wiki técnica del flujo: `docs/memoria/flujo_actualizacion_clientes.md`
- Decisión de desactivar cron: `docs/memoria/decisiones.md` (entrada 25-may)
- Workflow YAML: `.github/workflows/agente_cobranza_diario.yml`
- Updater de Excel: `agente-cobranza/lib/excel_updater.py`
- Helpers Odoo: `agente-cobranza/lib/odoo_helpers.py`

---

_Última edición: 2026-05-26 — Claude (esqueleto inicial)._
_Próxima edición esperada: Víctor completando bloque "PARA VÍCTOR"._
