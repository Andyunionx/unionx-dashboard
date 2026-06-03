# UnionX — Scheduler confiable del pulso (Cloudflare Worker)

**Problema que resuelve:** el cron de GitHub Actions es "best-effort" y dropea runs
(el pulso de las 22:00 no salió la noche del 2-jun). Este Worker de Cloudflare
dispara el workflow de forma **confiable**.

**Arquitectura:** el Worker solo hace `workflow_dispatch` del pulso en GitHub. Toda
la lógica (fechas, ventana de email 08:00–24:00 horas pares, Gate 1/Gate 2) vive
en `cyber_pulso.yml`. El Worker es intencionalmente trivial → fácil de mantener.

```
Cloudflare Cron (confiable, cada hora)
   └─ POST workflow_dispatch → GitHub Actions: cyber_pulso.yml
        └─ refresca parquet (app) + manda email si toca (ventana + Gate 2)
```

## Setup (una vez)

### 1. Crear el token de GitHub (PAT fine-grained)
1. GitHub → **Settings → Developer settings → Fine-grained tokens → Generate new token**.
2. **Resource owner:** Andyunionx · **Repository access:** Only select → `unionx-dashboard`.
3. **Permissions → Actions: Read and write**. (Nada más.)
4. **Expiration:** 1 año (anótalo para rotarlo; ver "Mantención" abajo).
5. Genera y **copia el token** (`github_pat_...`).

### 2. Desplegar el Worker en Cloudflare
Con Wrangler (CLI):
```bash
npm install -g wrangler
cd scheduler
wrangler login                 # abre el navegador, autoriza tu cuenta Cloudflare
wrangler deploy                # despliega el worker + el cron de wrangler.toml
wrangler secret put GH_TOKEN   # pega el PAT del paso 1
```
(Alternativa sin CLI: crear el Worker en el dashboard de Cloudflare, pegar `worker.js`,
agregar el Trigger Cron `0 * * * *`, y el secret `GH_TOKEN` en Settings → Variables.)

### 3. Verificar
```bash
curl https://unionx-pulso-scheduler.<tu-subdominio>.workers.dev/trigger
```
→ debe responder "pulso disparado" y aparecer un run nuevo en GitHub Actions
(Actions → Cyber Pulso). Revisa que el email salga si estás en hora par 08–24 CLT.

### 4. Apagar el cron flojo de GitHub (¡solo después de verificar el paso 3!)
En `.github/workflows/cyber_pulso.yml`, comentar el bloque `schedule:` para que NO
haya doble disparo (GitHub + Cloudflare). Dejar `workflow_dispatch:` para manuales.

## Mantención
- **Rotar el PAT** antes de su expiración (1 año): regenerarlo y `wrangler secret put GH_TOKEN`.
  Para cero rotación, migrar a una GitHub App (cambiar solo la obtención del token en `worker.js`).
- **Post-Cyber:** ajustar `crons` en `wrangler.toml` a la cadencia normal (ver comentarios ahí).

## Costo
Cloudflare Workers free tier: 100.000 requests/día. Esto usa ~24/día → **gratis**.
GitHub Actions: repo público → minutos ilimitados → **gratis**.
