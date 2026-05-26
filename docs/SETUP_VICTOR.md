# Setup Víctor — Onboarding al agente de cobranza

> Esta guía es para vos, Víctor. Te lleva desde cero hasta hacer tu primer
> cambio al agente de cobranza usando Claude Code.

---

## TL;DR (5 pasos)

1. Aceptá la invitación al repo en GitHub (te llegó por mail)
2. Instalá Claude Code
3. Cloná el repo
4. Abrí Claude Code apuntando al repo
5. Decile a Claude: *"leí docs/SETUP_VICTOR.md, ¿qué hago primero?"*

---

## 1. Aceptar invitación al repo

Andrés te invitó como colaborador a `Andyunionx/unionx-dashboard` con
permiso **Write** (podés crear branches y abrir PRs; no podés mergear a
`main` ni borrar nada crítico).

- Revisá el mail asociado a tu cuenta GitHub `victorunionx`
- Buscá el mail de GitHub con asunto *"Andyunionx invited you to collaborate"*
- Click **View invitation** → **Accept invitation**

**Verificación:** abrí https://github.com/Andyunionx/unionx-dashboard
— tiene que cargar sin 404.

---

## 2. Instalar Claude Code

Requiere Node.js 18+. Si no lo tenés: https://nodejs.org/ (instalá la versión LTS).

Después, en PowerShell:

```powershell
npm install -g @anthropic-ai/claude-code
```

Verificá:

```powershell
claude --version
```

Primer login (abre el browser, te pide loguear con tu cuenta Anthropic):

```powershell
claude
```

Si no tenés cuenta Anthropic todavía, avisale a Andrés para que te active
el acceso del workspace UnionX.

---

## 3. Clonar el repo

Elegí dónde lo querés (sugerencia: `C:\Users\<tu-user>\dev\`):

```powershell
cd C:\Users\<tu-user>
mkdir dev -Force
cd dev
gh repo clone Andyunionx/unionx-dashboard
```

Si no tenés `gh` (GitHub CLI): https://cli.github.com/ — o usá:

```powershell
git clone https://github.com/Andyunionx/unionx-dashboard.git
```

---

## 4. Abrir Claude Code apuntando al repo

```powershell
cd unionx-dashboard
claude
```

Eso abre Claude Code dentro del repo. Lo primero que hace Claude al
arrancar es **leer automáticamente**:

- `CLAUDE.md` (la raíz del repo) → contexto general del proyecto UnionX
- Tus archivos de memoria personal (si después agregás `~/.claude/...`)

Eso significa que **antes de tu primer prompt, Claude ya sabe**:
- Quién sos en el equipo
- Qué hace el agente de cobranza
- Qué clientes están configurados
- Qué pasó con el incidente de Paris (25-may)

---

## 5. Tu primer prompt sugerido

Una vez abierto Claude Code, escribí literalmente:

```
Soy Víctor. Es mi primer día con Claude Code en este repo.
Leé docs/SETUP_VICTOR.md, docs/COMO_AGREGAR_CLIENTE.md y
docs/CONTABILIDAD_ESTADO_2026-05.md.
Después contame en 3 frases:
  1) qué hace el agente de cobranza
  2) dónde está el código que YO voy a tocar
  3) qué está pendiente esta semana
```

Claude debería responderte que vas a tocar:
- `agente-cobranza/clientes/*.yaml` — config de cada cliente
- `docs/memoria/*.md` — wiki donde guardás lo que vas aprendiendo

Y que **NO** vas a tocar (al menos por ahora):
- `agente-cobranza/lib/*.py` — código Python del motor
- Cualquier carpeta fuera de `agente-cobranza/` y `docs/`

---

## Cómo trabajar "la memoria" del equipo

Esto es lo más importante de entender. **La memoria de tu trabajo NO está
en tu cabeza ni en mails sueltos.** Está en archivos `.md` versionados
en el repo.

### El loop

Cuando descubrís algo nuevo (un `partner_id` nuevo, un cliente cambió
su Excel, una boleta tiene un comportamiento raro), le decís a Claude:

> "Agregá a `docs/memoria/clientes.md` que Paris ahora tiene un
> partner_id=999 para la cuenta corporativa, y que las facturas de ese
> partner van a la hoja `FAC CORPORATIVO` del Excel de Paris."

Claude edita el archivo. Vos hacés:

```powershell
git add docs/memoria/clientes.md
git commit -m "memoria: nuevo partner corporativo Paris 999"
git push
```

A partir de ese momento:
- **Mañana** cuando vos abras Claude Code → ya sabe del partner 999
- Cuando **Andrés** abra Claude Code → ya sabe del partner 999
- Cuando el **cron de GitHub Actions** corra → usa el dato (si lo pusiste también en el YAML del cliente)

Esa es la magia. No hay "subir al cloud", no hay base de datos, no hay
panel mágico. Es **Git + Markdown + Claude leyéndolos al arrancar**.

### ¿Dónde NO guardar memoria?

- ❌ Mail
- ❌ WhatsApp
- ❌ Tu cabeza
- ❌ Un .txt en tu escritorio
- ❌ Comentarios sueltos en el código

Si no está en un `.md` versionado, **no existe para el equipo**.

---

## Reglas de oro

### 1. Antes de cambiar algo, abrí una branch

```powershell
git checkout -b vcr/loquesea
```

Hacé los cambios, commiteá, abrí PR. Andrés revisa y mergea.
**Nunca empujes a `main` directamente.**

### 2. Si Claude te propone tocar `agente-cobranza/lib/*.py` → frená

Esos archivos son código Python que afecta a TODOS los clientes.
Cambios ahí requieren testing y aprobación de Andrés antes de merge.

Si Claude te lo sugiere, decile:
> "Frená, eso es código del motor. Avisale a Andrés primero."

### 3. Si dudás → preguntá a Claude antes de ejecutar

Claude no se ofende si le pedís:
> "Primero explicame qué vas a hacer, no lo hagas todavía."

Después de que entendés, le decís *"OK, hacelo"*.

### 4. El cron del agente está DESACTIVADO

Por el incidente del 23-may con Paris, el cron diario NO está corriendo.
Si querés probar un cliente, lo disparás **manual** desde GitHub:

1. https://github.com/Andyunionx/unionx-dashboard/actions
2. Workflow **Agente Cobranza Diario**
3. Click **Run workflow** → marcá `no_upload=true`
   (descarga de Odoo y genera Excel local, pero NO toca Drive)

Solo cuando vos + Andrés confirmen que el resultado es correcto,
se vuelve a activar el cron.

### 5. Tu mes 1: leer y entender

No empujés cambios al agente hasta haber leído:
- `docs/FLUJO_COBRANZA_BOLETA.md`
- `docs/COMO_AGREGAR_CLIENTE.md`
- `docs/CONTABILIDAD_ESTADO_2026-05.md` (estado actual + incidente)
- `docs/memoria/*.md` (lo que vayamos armando)

---

## Si algo se rompe

| Problema | Qué hacer |
|---|---|
| El comando no anda | Pegá el error completo a Claude y pedile ayuda |
| Claude propone algo que no entendés | *"Explicámelo como si tuviera 5 años, sin hacer nada todavía"* |
| No sabés si tenés permiso para hacer X | Pregúntale a Andrés por mail antes |
| Excel en Drive se ve mal después de una corrida | **NO toques nada.** Avisale a Andrés. Drive guarda historial 30 días, se puede restaurar |

---

## Glosario rápido

- **Cron**: trabajo que GitHub Actions corre solo, a una hora fija. El nuestro está pausado.
- **PR (Pull Request)**: pedirle a Andrés *"miráme este cambio y mergealo si te gusta"*
- **Branch**: tu copia personal del código donde podés cambiar cosas sin afectar a nadie
- **Service account**: la "cuenta robot" que el agente usa para abrir Excel en Drive (`union-x-revenue-bot@...`)
- **Partner** (en Odoo): cliente / contacto. Cada cliente tiene un `partner_id` (número entero)
- **YAML**: archivo de configuración fácil de leer. Los clientes del agente viven en `agente-cobranza/clientes/<cliente>.yaml`

---

## Contacto

- **Andrés** — andres@unionx.cl — para cualquier cosa que no responda Claude
- **Repo** — https://github.com/Andyunionx/unionx-dashboard
- **Estado del agente** — `docs/CONTABILIDAD_ESTADO_2026-05.md`

---

_Última actualización: 2026-05-26_
