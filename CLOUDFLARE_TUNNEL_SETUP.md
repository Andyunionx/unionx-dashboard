# Publicar UnionX Dashboards con Cloudflare Tunnel + Access

Este doc te guía para exponer `http://localhost:8501` a internet de forma segura,
con URL HTTPS permanente y login de Cloudflare Access antes del propio login de Streamlit.

**Resultado final:** `https://dashboards.unionx.cl` (o el dominio que elijas)
→ Cloudflare Access pide tu email → si está en la whitelist, entra
→ Streamlit pide usuario/contraseña → acceso al dashboard.

---

## Pre-requisitos

1. **Cuenta Cloudflare gratis** — https://dash.cloudflare.com/sign-up
2. **Un dominio apuntado a Cloudflare** (DNS gestionado por Cloudflare).
   - Si ya tenés `unionx.cl` podés usar un subdominio (ej. `dashboards.unionx.cl`).
   - Si no, podés comprar uno en Cloudflare Registrar (~$10/año) o apuntar uno existente.

---

## Paso 1 — Instalar cloudflared

Descargá el instalador oficial para Windows:
- https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.msi

Instalá con doble clic. Verificá en PowerShell:
```powershell
cloudflared --version
```

---

## Paso 2 — Autenticar y crear el tunnel

En PowerShell:
```powershell
# 1. Login (abre browser, pedí que autorice tu cuenta Cloudflare)
cloudflared tunnel login

# 2. Crear tunnel llamado "unionx-dashboards"
cloudflared tunnel create unionx-dashboards
# Esto genera un archivo credentials (JSON) en C:\Users\LENOVO\.cloudflared\
# Anotá el Tunnel UUID que imprime.

# 3. Ruta DNS: asocia subdominio al tunnel
cloudflared tunnel route dns unionx-dashboards dashboards.unionx.cl
```

---

## Paso 3 — Archivo de configuración

Creá `C:\Users\LENOVO\.cloudflared\config.yml`:

```yaml
tunnel: unionx-dashboards
credentials-file: C:\Users\LENOVO\.cloudflared\<TUNNEL-UUID>.json

ingress:
  - hostname: dashboards.unionx.cl
    service: http://localhost:8501
    originRequest:
      noTLSVerify: true
      # Streamlit necesita WebSocket:
      httpHostHeader: localhost:8501
  - service: http_status:404
```

---

## Paso 4 — Probar

```powershell
cloudflared tunnel run unionx-dashboards
```

Abrí en el browser: `https://dashboards.unionx.cl`
Deberías ver la pantalla de login de Streamlit.

---

## Paso 5 — Correr como servicio Windows (persistente)

```powershell
# Como Administrador
cloudflared service install
# Servicio queda registrado como "cloudflared". Arranca con Windows.
```

Verificá: `Get-Service cloudflared` → debería decir `Running`.

---

## Paso 6 — Activar Cloudflare Access (opcional pero recomendado)

En https://one.dash.cloudflare.com:
1. Access → Applications → Add an application → Self-hosted
2. **Application name:** UnionX Dashboards
3. **Application domain:** dashboards.unionx.cl
4. **Session duration:** 24h
5. **Policies:**
   - Nombre: "Equipo UnionX"
   - Action: Allow
   - Include: Emails → `andres@unionx.cl`, `ceo@unionx.cl`, etc. (whitelist)
6. Identity providers: activar "One-time PIN" (manda código por email al tercero)
   o Google Workspace si tu empresa lo usa.

Con esto, **antes de llegar a Streamlit ya pasaron el filtro de Cloudflare**.
Doble capa de seguridad.

---

## Troubleshooting

**WebSocket falla / app queda "Connecting..."**
→ Streamlit usa WebSocket. Cloudflare lo soporta automático. Verificá que
en `config.yml` tengas `noTLSVerify: true`. Si sigue, probá agregar en
el `.streamlit/config.toml`:

```toml
[server]
enableCORS = false
enableXsrfProtection = true
baseUrlPath = ""
```

**Cookie de auth de Streamlit no persiste**
→ En `auth_config.yaml` la key `cookie.key` debe ser secreta (YA está seteada
como `unionx_2026_secret_change_me_k8j3nd92kf` — cambiala por algo random real).

**Ver logs del tunnel:**
```powershell
Get-Content C:\Windows\System32\config\systemprofile\.cloudflared\*.log -Tail 50 -Wait
```

---

## Costo

- **Cloudflare Tunnel:** gratis
- **Cloudflare Access:** gratis hasta 50 usuarios
- **Dominio:** ~$10 USD/año si lo comprás nuevo

Total: prácticamente gratis para el uso de UnionX.
