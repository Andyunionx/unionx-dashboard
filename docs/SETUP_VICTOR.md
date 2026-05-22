# Setup para Víctor — trabajar en el repo desde Claude Code

> Guía para que Víctor pueda:
> 1. **Validar** archivos generados por el agente vs los originales de Martín
> 2. **Agregar clientes nuevos** vía PR sin tocar código Python
> 3. **Mantener su memoria operativa** (el MD del flujo) versionada en el repo

## TL;DR

| Cosa | Dónde vive | Quién la edita |
|---|---|---|
| **Código del agente** | `agente-cobranza/` en el repo | Andrés / Claude (vía PR) |
| **Configs de clientes** (YAMLs) | `agente-cobranza/clientes/` | Víctor (vía PR) |
| **Memoria operativa de Víctor** | `docs/memoria/` en el repo | Víctor (push directo o PR) |
| **MD original con credenciales** | Drive `actualizacion_clientes.md` | Víctor (queda como histórico) |
| **Credenciales** | GitHub Secrets | Solo Andrés |
| **Excel de clientes** | Drive `Trabajado clientes/` | El agente (automático) |

---

## 1. Setup inicial (una sola vez)

### 1.1 Andrés te invita al repo

Andrés tiene que ir a:
`https://github.com/Andyunionx/unionx-dashboard/settings/access`

Y agregarte como **Collaborator** con rol `Write`. Vas a recibir un email de invitación.

### 1.2 Instalá Claude Code en tu máquina

Si todavía no lo tenés:

```bash
# Mac/Linux
curl -fsSL https://claude.ai/install.sh | sh

# Windows: descargar instalador desde claude.com/code
```

Después logueá con tu cuenta:

```bash
claude /login
```

### 1.3 Cloná el repo

```bash
# Donde quieras tener el código (ej: en tu carpeta personal)
cd ~/proyectos
git clone https://github.com/Andyunionx/unionx-dashboard.git
cd unionx-dashboard
```

### 1.4 Configurá tus credenciales locales (solo para testear localmente)

> ⚠️ **NUNCA commitees estas credenciales al repo.** El `.gitignore` ya excluye
> los archivos típicos, pero tené cuidado.

Creá un archivo `.env.local` en la raíz del repo (gitignored):

```bash
# Tu user de Odoo
ODOO_USER=victor@grupoeter.cl
ODOO_PASSWORD=<tu password>

# Credentials del bot Drive (pedirle a Andrés que te lo pase por canal seguro)
# Lo guardás como archivo credentials.json en la raíz del repo
```

Para activar tu entorno antes de correr cualquier script:

```bash
# Mac/Linux
source .env.local
# o más explícito
export $(cat .env.local | xargs)

# Windows PowerShell
# (creá un .env.local.ps1 con $env:ODOO_USER="..." etc.)
. .\.env.local.ps1
```

### 1.5 Instalá dependencias Python

Necesitás Python 3.12+:

```bash
pip install -r agente-cobranza/requirements.txt
```

---

## 2. Workflow diario — agregar un cliente nuevo

Desde la raíz del repo, abrí Claude Code:

```bash
cd ~/proyectos/unionx-dashboard
claude
```

Y le decís:

```
Hola Claude, necesito agregar un cliente nuevo al agente de cobranza.

Leéte docs/COMO_AGREGAR_CLIENTE.md y guiame paso a paso:

1. Conseguir el partner_id en Odoo
2. Crear el YAML siguiendo agente-cobranza/clientes/_template.yaml
3. Compartir el Excel con el service account
4. Abrir un PR

Datos del cliente:
  Nombre:  <NOMBRE>
  Excel:   <PATH/EN/Trabajado clientes/...>
  XLOOKUP? <SÍ/NO/no sé>
```

Claude Code va a:
1. Leer la guía
2. Hacerte preguntas para juntar los datos
3. Crear el archivo `agente-cobranza/clientes/<slug>.yaml`
4. Crear branch + PR

Después en GitHub: PR aprobado por Andrés → merge → al día siguiente el cron procesa el cliente.

---

## 3. Workflow — validar un Excel generado por el agente

Cuando Andrés disparé el agente con `no_upload=true`, GitHub Actions deja el
Excel resultante como **artifact descargable**. Para validar:

### 3.1 Bajar el artifact

1. Andá a: https://github.com/Andyunionx/unionx-dashboard/actions
2. Buscá la corrida más reciente de **"Agente Cobranza Diario"**
3. Scroll al fondo → sección **"Artifacts"** → descargar `agente-cobranza-tmp-<run_id>`
4. Descomprimir el ZIP

Adentro vas a ver:
```
agente-cobranza/tmp/
  paris/
    PARIS 2026.xlsx                 ← original que bajó de Drive
    PARIS 2026_ACTUALIZADO.xlsx     ← el que generó el agente
  falabella/ ...
```

### 3.2 Comparar

Abrí el archivo `*_ACTUALIZADO.xlsx` que generó el agente y compará contra
el que tenés vos hoy en Drive (`*_ACTUALIZADO.xlsx` que genera el cron de Martín).

**Qué tiene que matchear:**
- Headers de cada hoja (mismas columnas, mismos nombres)
- Cantidad de filas en cada hoja (puede haber ±5 por timing — está OK)
- Hojas custom (PAGOS, DINAMICAS, etc.) tienen que estar **idénticas** (no las toca el agente)
- Fórmulas XLOOKUP (si el cliente las usa) tienen que estar intactas

**Si algo no matchea:** abrí un issue en GitHub con un screenshot y un Claude
Code en el repo te ayuda a investigar.

---

## 4. Tu memoria operativa — `docs/memoria/`

Tu archivo `actualizacion_clientes.md` actual vive en Drive con credenciales
en plano. Para que esté **versionada** (con historial de cambios) y accesible
desde el repo, te creamos `docs/memoria/` donde podés:

- Documentar cualquier proceso operativo
- Anotar decisiones, casos raros, troubleshooting
- Mantener una "wiki" de cobranza

**Reglas:**

✅ Lo que **SÍ va** en `docs/memoria/`:
- Cómo se hace tal proceso
- Mapping de campos Odoo
- Casos especiales por cliente
- Troubleshooting
- Cambios de proveedores/portales

❌ Lo que **NO va** en `docs/memoria/`:
- Passwords, tokens, API keys
- Datos personales de clientes (RUTs específicos, montos absolutos)
- Información sensible que no debería estar en el repo

Las credenciales van en GitHub Secrets (las maneja Andrés).

### Ejemplo: crear/editar tu memoria

Desde Claude Code en tu máquina:

```
Quiero agregar un proceso a mi memoria. Es sobre cómo conciliar pagos
manuales que llegan por transferencia sin orden. Hacéme preguntas hasta
sacar el flujo completo y después generá un archivo en docs/memoria/
con título descriptivo. Cuando esté, abrí PR.
```

---

## 5. Reglas de oro para trabajar en el repo

### 5.1 Nunca pushear directo a `main`

Siempre creá una branch:

```bash
git checkout -b feat/cliente-walmart        # nueva feature
git checkout -b fix/yuju-falabella           # un bug
git checkout -b docs/memoria-conciliacion    # cambios en docs
```

Después PR a main, Andrés revisa y mergea.

### 5.2 Antes de empezar a editar, traer cambios recientes

```bash
git checkout main
git pull
git checkout -b feat/lo-tuyo
```

### 5.3 Si Claude Code te sugiere editar archivos que no entendés

Decile **no, solo hacé lo que te pedí**. Si toca código del agente
(`agente-cobranza/lib/*.py` o `agente-cobranza/actualizar_cliente.py`)
eso lo hace Andrés/Claude principal, no vos.

Lo que **vos sí podés** editar libremente:
- `agente-cobranza/clientes/*.yaml`
- `docs/memoria/*.md`
- Tu propio README si querés

### 5.4 Si tenés dudas, preguntá en el PR

Cuando abrís el PR podés mencionar a Andrés con `@AndyunionX` y dejar
un comentario explicando qué dudás.

---

## 6. Comandos útiles

```bash
# Ver el status del repo
git status

# Ver los últimos cambios
git log --oneline -10

# Correr el agente en tu máquina con tu cliente
source .env.local
python agente-cobranza/actualizar_cliente.py --config agente-cobranza/clientes/<slug>.yaml --dry-run

# Validar un YAML que escribiste
python -c "import yaml; yaml.safe_load(open('agente-cobranza/clientes/<slug>.yaml'))"

# Volver a la rama main si te perdiste
git checkout main
```

---

## 7. Cosas que NO podés hacer (porque solo Andrés tiene acceso)

| Cosa | Por qué |
|---|---|
| Editar `.github/workflows/*.yml` | Cambios al cron de producción los maneja Andrés |
| Cambiar `agente-cobranza/lib/*.py` | Código core del agente, requiere review técnica |
| Crear / borrar GitHub Secrets | Solo el owner del repo |
| Cambiar permisos de Drive | Lo maneja Andrés |
| Mergear PRs a `main` | Requiere review de Andrés |

Si necesitás algo de esta lista, abrí un issue o pingueá a Andrés directo.

---

## 8. Soporte

| Problema | A quién pingueás |
|---|---|
| "Me da error al correr el agente local" | Andrés / Claude (en el repo) |
| "Mi PR no se mergea" | Andrés |
| "Una fórmula XLOOKUP de un cliente se rompió" | Andrés (es bug del agente) |
| "No sé cómo armar un YAML" | Claude Code (con `docs/COMO_AGREGAR_CLIENTE.md`) |
| "Cambió un proceso operativo y quiero documentarlo" | Editás `docs/memoria/` |
