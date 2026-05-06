# Deploy Cloud Gratuito — Dashboard Ventas UnionX

**Stack:** Streamlit Community Cloud + Turso (libSQL) + GitHub Actions
**Costo:** USD $0/mes
**Multi-usuario:** ✅ con login email + password
**Sincronización:** automática 3 veces al día (09:00, 14:00, 18:00 Chile)

---

## ✅ Pasos del Setup (orden exacto)

### 1. Crear cuenta Turso (DB cloud) — 3 min

1. Ir a **https://turso.tech** y registrarse (con GitHub o email).
2. **New Database** → nombre: `unionx-ventas` → región: `gru` (São Paulo, más cerca).
3. En la página de la DB:
   - Copiar la **Database URL** (ej. `libsql://unionx-ventas-andyunionx.turso.io`)
   - Crear un **token**: botón **Tokens → Create token** → expiración: `Never` → copiar el JWT (`eyJ...`).
4. Guardar ambos valores temporalmente, los usaremos en pasos 3, 5 y 6.

### 2. Migrar la DB local a Turso — 15 min

Desde tu PC, en PowerShell:
```powershell
$env:LIBSQL_URL = "libsql://unionx-ventas-andyunionx.turso.io"
$env:LIBSQL_AUTH_TOKEN = "eyJ..."
cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
& "C:\Users\andre\AppData\Local\Programs\Python\Python312\python.exe" migrar_a_turso.py
```

Toma 10-20 min (377K filas). Al final imprime verificación local vs remote — los conteos deben coincidir.

### 3. Crear cuenta GitHub y subir código — 10 min

Si no tienes GitHub:
1. https://github.com/signup
2. Verificar email.

Crear repo:
1. https://github.com/new → nombre: `unionx-dashboard` → **Private** → Create.
2. Desde tu PC:
   ```powershell
   cd "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
   git init
   git add .
   git commit -m "Initial deploy"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/unionx-dashboard.git
   git push -u origin main
   ```

(Si pide credenciales: usar tu usuario GitHub + un Personal Access Token desde Settings → Developer settings → Personal access tokens → Generate new token classic, scope `repo`).

### 4. Configurar GitHub Secrets — 3 min

1. En tu repo → **Settings → Secrets and variables → Actions → New repository secret**.
2. Agregar 3 secrets:

| Nombre | Valor |
|---|---|
| `LIBSQL_URL` | `libsql://unionx-ventas-andyunionx.turso.io` |
| `LIBSQL_AUTH_TOKEN` | `eyJ...` (el token Turso) |
| `ANDRES_ODOO_PASSWORD` | tu password Odoo |

3. **Actions → Run workflow → "Sync Ventas Diario"** para probar la primera ejecución manual.

### 5. Crear cuenta Streamlit Community Cloud — 2 min

1. https://share.streamlit.io → **Sign up with GitHub** (autoriza).
2. **New app** → seleccionar tu repo `unionx-dashboard` → branch `main` → archivo `dashboard_ventas.py`.
3. **Advanced settings** → en **Secrets**, pegar el contenido de `.streamlit/secrets.toml.template` con valores reales (Turso URL, Token, password Odoo, hashes de auth).

Para generar el hash del password de auth:
```powershell
& "C:\Users\andre\AppData\Local\Programs\Python\Python312\python.exe" -c "import bcrypt; print(bcrypt.hashpw(b'TU_PASSWORD', bcrypt.gensalt()).decode())"
```

Pegar el hash resultante en `[auth.credentials.usernames.andres] password = "$2b$12$..."`.

4. **Deploy**. Espera 2-3 min hasta que muestre la URL final (ej. `unionx-dashboard.streamlit.app`).

### 6. Compartir con el equipo — 1 min

- URL: `https://unionx-dashboard.streamlit.app` (la que te dé Streamlit Cloud).
- Para agregar más usuarios al login: editar Secrets en Streamlit Cloud, agregar bloques `[auth.credentials.usernames.NOMBRE]` con su email/nombre/hash.
- Cualquier usuario con sus credenciales accede vía navegador, ve KPIs YoY, filtra y descarga el RAW Excel.

---

## 🛠️ Operación día a día

### Sincronización automática
GitHub Actions ejecuta `actualizar_diario.py` 3 veces al día (Chile):
- **09:00** — refresca día anterior
- **14:00** — refresca el día actual hasta ahora
- **18:00** — refresca el día actual al cierre

Cada corrida:
- Conecta a Odoo
- Extrae el último día (con todos los fixes: IVA, multi-fact, neteo NC, Tipo Negocio, etc.)
- Inserta a Turso (DEDUP automático)
- Sube logs como artefacto en la corrida (revisar si hay falla)

### Trigger manual
GitHub → Actions → **Sync Ventas Diario** → **Run workflow** → opcionalmente especificar `fecha` o `dias`.

### Agregar usuarios al dashboard
Streamlit Cloud → tu app → Settings → Secrets → editar:
```toml
[auth.credentials.usernames.NUEVO_USUARIO]
email = "persona@unionx.cl"
name = "Nombre Apellido"
password = "$2b$12$..."   # hash bcrypt
```

Save → Streamlit redeploya automáticamente (~30s).

### Ver logs
- **Sync logs:** GitHub → Actions → corrida específica → Artifacts → descargar `sync-log-XXXX`.
- **Dashboard logs:** Streamlit Cloud → tu app → Manage app (esquina inf-derecha) → tab Logs.

---

## 🐛 Troubleshooting

| Problema | Solución |
|---|---|
| Sync falla por 502 Odoo | Re-correr workflow manual; el script ya tiene retry 10 veces |
| Dashboard "Authentication failed" | Verificar hash del password en Streamlit secrets (regenerar con bcrypt) |
| Datos no aparecen en dashboard | Verificar que LIBSQL_URL y LIBSQL_AUTH_TOKEN estén en secrets de Streamlit Cloud |
| GitHub Actions exhausto | Plan free: 2000 min/mes. Cada corrida toma ~3-5 min × 3/día = ~450 min/mes. Sobra. |

---

## 💰 Costos verificados (todos $0)

| Servicio | Plan | Límite | Uso real estimado |
|---|---|---|---|
| Turso | Starter | 9 GB storage, 1B reads/mo | ~200 MB, ~10M reads/mo |
| GitHub Actions | Free | 2000 min/mo (privados) | ~450 min/mo |
| Streamlit Cloud | Community | 1 app pública o privada/cuenta, 1GB recursos | 1 app activa |
| Cloudflare (opcional) | Free | Unlimited | No requerido en este setup |

---

**Una vez deployed:** la skill local en tu PC ya no es necesaria. Puedes apagar el Task Scheduler:
```powershell
Disable-ScheduledTask -TaskName "UnionX - Actualizar Ventas Diario"
Disable-ScheduledTask -TaskName "UnionX - Dashboard Ventas (Streamlit)"
```

Pero **mantén la DB local como backup** en `data/db/maestra_ventas.db`.
