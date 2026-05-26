# 📜 Log de decisiones — Agente cobranza

> **Append-only.** Nunca se borra una entrada. Si una decisión se revierte,
> se agrega una entrada nueva diciendo "se revierte X por Y".
> Orden: **más reciente arriba**.

Formato de entrada:

```
## YYYY-MM-DD — Título corto
- **Quién decidió:** Andrés / Víctor / equipo
- **Contexto:** por qué se decidió esto
- **Decisión:** qué se hizo
- **Consecuencias:** qué cambia / a qué hay que estar atento
```

---

## 2026-05-26 — Crear wiki versionada `docs/memoria/`

- **Quién decidió:** Andrés
- **Contexto:** el doc `CONTABILIDAD_ESTADO_2026-05.md` mencionaba
  `docs/memoria/` y `docs/SETUP_VICTOR.md` como si existieran, pero no estaban.
  Víctor no entendía cómo "trabajar la memoria" desde Claude Code.
- **Decisión:** crear los 4 archivos prometidos:
  - `docs/SETUP_VICTOR.md` (onboarding)
  - `docs/memoria/README.md` (índice)
  - `docs/memoria/flujo_actualizacion_clientes.md` (wiki técnica)
  - `docs/memoria/decisiones.md` (este)
  - `docs/memoria/incidente_paris_2026-05.md` (para que Víctor complete)
- **Consecuencias:** Víctor puede actualizar la memoria del equipo
  directamente sin triangular por Andrés. Próxima sesión cualquier
  Claude lee esta wiki al arrancar.

---

## 2026-05-25 — Invitar a Víctor (`victorunionx`) al repo `unionx-dashboard`

- **Quién decidió:** Andrés
- **Contexto:** Víctor necesita acceso al código del agente para
  configurar clientes nuevos y actualizar la wiki de cobranza.
- **Decisión:** invitarlo como colaborador con permiso **Write** al repo
  `Andyunionx/unionx-dashboard`. Modelo de trabajo: Víctor crea branches
  y abre PRs; Andrés revisa y mergea.
- **Decisión secundaria:** **no** crear un repo separado `unionx-cl/cobranza`
  por ahora. Se evalúa migración a repo dedicado cuando se reactive el cron
  (post-fix del incidente).
- **Consecuencias:** Víctor ve TODO el repo (ventas, finanzas, COMEX), pero
  con regla en `SETUP_VICTOR.md` de tocar SOLO `agente-cobranza/` y `docs/`.

---

## 2026-05-25 — DESACTIVAR cron diario del agente cobranza

- **Quién decidió:** Andrés
- **Contexto:** las corridas del 23, 24 y 25 de mayo sobrescribieron
  los 5 Excel en Drive y Víctor reportó pérdida de data en Paris
  ("se perdió todo lo de mayo que estaba en estado pagado").
- **Decisión:** commit `7029688` comenta el `schedule:` del workflow
  `.github/workflows/agente_cobranza_diario.yml`. Queda solo
  `workflow_dispatch` (disparo manual) para poder debuggear sin riesgo.
- **Mitigación temporal:** Martín reactiva su Task Scheduler local hasta
  que se arregle el agente.
- **Consecuencias:** el cron NO corre hasta que:
  1. Víctor confirme qué data exacta se perdió
  2. Andrés/Claude identifiquen el root cause
  3. Se aplique fix
  4. Se valide en 1 cliente (Paris) con `no_upload=true`
  5. Se valide en los 5 clientes
- **Tracking del fix:** `docs/memoria/incidente_paris_2026-05.md`

---

## 2026-05-22 — Mergear PR #54 (agente cobranza) a `main` sin esperar OK de Víctor

- **Quién decidió:** Andrés
- **Contexto:** el agente cobranza fue desarrollado en branch `feat/agente-cobranza`.
  El plan era esperar validación humana de Víctor (compararía artifact contra
  Drive) antes del merge a main.
- **Decisión:** mergear igual para activar el cron y "ganar tiempo".
- **Consecuencias:** ⚠️ **decisión equivocada** — derivó en el incidente
  del 23-25 may. Lección aprendida: features que escriben a producción
  (Drive / Odoo / DB) requieren OK explícito del usuario antes de merge.
  **Regla nueva:** no mergear features productivas sin validación end-to-end.

---

## 2026-05-22 — Crear service account `union-x-revenue-bot` para Drive

- **Quién decidió:** Andrés
- **Contexto:** el agente necesita escribir Excel en Drive desde GitHub Actions
  sin usar credenciales personales.
- **Decisión:** usar el service account ya existente
  `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com`. Víctor lo
  compartió como Editor con la carpeta `Trabajado clientes` (id
  `19EsjfScn5YhJjNVMvT8Qkt3xZBGpGG16`).
- **Consecuencias:** el bot puede leer/escribir cualquier Excel en esa carpeta.
  Para nuevos clientes, hay que compartir el Excel específico también.

---

_Para agregar una entrada nueva, copiá el formato de arriba y pegala
encima de la última. NO borres entradas viejas, aunque la decisión se
haya revertido — eso forma parte de la historia._
