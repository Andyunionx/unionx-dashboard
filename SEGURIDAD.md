# 🚓 Política de Seguridad — UnionX Dashboard

Este documento define las reglas para no exponer secretos en el repositorio Git.

## Reglas básicas (no negociables)

1. **Ningún password, API key o credencial JSON va en código fuente**.
2. **Nunca subir `.env`, `credentials.json`, `token.json`, `auth_config.yaml`** o similares.
3. **Antes de cada commit**, el `pre-commit hook` ejecuta automáticamente `scripts/policia_seguridad.py`.
4. **Si se detecta un secreto**, el commit se BLOQUEA. Hay que limpiarlo antes.
5. **Si un secreto YA fue commiteado**, hay que **rotar la credencial** Y limpiar el historial Git.

## Cómo funciona el policía de seguridad

### Modo automático (pre-commit)
Cada `git commit` ejecuta `scripts/policia_seguridad.py` sobre los archivos staged. Si encuentra:
- 🔴 **CRITICA** (Service Account, Private Key, OAuth tokens, Password Odoo) → **BLOQUEA**
- 🟡 **ALTA** (passwords hardcoded, API keys) → **BLOQUEA**
- 🔵 **MEDIA** (Bearer tokens) → reporta pero no bloquea

### Modo manual
```bash
# Escanear solo archivos staged (igual que pre-commit)
python scripts/policia_seguridad.py

# Escanear TODO el repo (auditoria completa)
python scripts/policia_seguridad.py --all

# Buscar archivos sensibles en el HISTORIAL Git
python scripts/policia_seguridad.py --history
```

### Bypass de emergencia (NO recomendado)
```bash
git commit --no-verify -m "..."
```
Solo usar en casos justificados y con conocimiento absoluto de qué se está commiteando.

## Cómo manejar credenciales

### ✅ Bien — env vars de Windows
```powershell
[Environment]::SetEnvironmentVariable("ANDRES_ODOO_PASSWORD", "tu-password", "User")
```

Y en el código Python:
```python
import os
password = os.environ.get("ANDRES_ODOO_PASSWORD")
```

### ✅ Bien — archivo .env (gitignored)
```bash
# .env (NUNCA SE COMMITEA — está en .gitignore)
ANDRES_ODOO_PASSWORD=tu-password
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
```

Cargado con `python-dotenv`:
```python
from dotenv import load_dotenv
load_dotenv()
```

### ✅ Bien — Streamlit Cloud Secrets
En Streamlit Cloud → Settings → Secrets:
```toml
ANDRES_ODOO_PASSWORD = "tu-password"
```

Acceder con `st.secrets["ANDRES_ODOO_PASSWORD"]`.

### ❌ Mal — NUNCA hacer esto
```python
# ❌ Hardcoded
PASSWORD = "ROTATED-2026-05-07"

# ❌ En config.json/yaml trackeado
{"password": "ROTATED-2026-05-07"}

# ❌ Service account en repo
# credentials.json con private_key real
```

## Si se detecta un secreto YA en el historial Git

### Paso 1: Rotar la credencial INMEDIATAMENTE
- **Password Odoo:** cambiarla en https://unionxb2b.odoo.com → User Settings → Change Password
- **Service Account Google:** Google Cloud Console → IAM → Service Accounts → revocar la key + crear nueva
- **OAuth tokens:** invalidar el refresh_token en https://myaccount.google.com/permissions

### Paso 2: Limpiar el historial Git con `git-filter-repo`
```bash
# Instalar la herramienta
pip install git-filter-repo

# Hacer backup del repo primero
cp -r .git ../backup-git-$(date +%s)

# Eliminar el archivo de TODO el historial
git filter-repo --path credentials.json --invert-paths
git filter-repo --path archive/Junior\ Revenue/credentials.json --invert-paths

# Force push (CUIDADO: reescribe el historial publico)
git push --force-with-lease --all
git push --force-with-lease --tags
```

### Paso 3: Avisar a colaboradores
Cualquier persona con clone debe re-clonar después del filter-repo.

## Archivos protegidos por nombre (`.gitignore`)

El archivo `.gitignore` bloquea por nombre:
- `.env`, `.env.*` (excepto `.env.template`)
- `credentials.json`, `**/credentials.json`
- `client_secret*.json`
- `token.json`, `**/token.json`
- `auth_config.yaml`
- `*.pem`, `*.key`, `id_rsa`
- `secrets.toml`, `service-account*.json`
- Frontend `node_modules/` y `dist/`

## Auditoría inicial pendiente

🔴 **Conocido:** los siguientes archivos están en el HISTORIAL Git aunque hoy se vean gitignored:
- `credentials.json` (commit `c7e89c7` — Service Account real `union-x-revenue`)
- `archive/Junior Revenue/credentials.json` (mismo commit)

**Acción:** rotar el Service Account + ejecutar `git filter-repo` para limpiar historial. Ver Paso 2 arriba.

## Convenciones del repo

- **Cada nueva integración** = nueva entrada en `.gitignore` para sus secretos correspondientes
- **Cada nueva env var** = entrada en `.env.template` con valor placeholder + documentación en este archivo
- **Cada nuevo collaborador** debe leer este documento ANTES de su primer commit

---

Última actualización: política inicializada con script `policia_seguridad.py` + pre-commit hook + .gitignore reforzado.
