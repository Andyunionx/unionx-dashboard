# 🚢 Dashboard Operaciones — Implementación

Documento técnico para entender, mantener y replicar la 2da app de Streamlit Cloud (foco Operaciones), que comparte repo con la app de Ventas.

**Repo:** https://github.com/Andyunionx/unionx-dashboard
**App #1 (Ventas):** `dashboard_ventas.py` → https://unionx-dashboard-7ppjm2cem2zkfxwzkv3pzc.streamlit.app/
**App #2 (Operaciones):** `dashboard_operaciones.py` → URL nueva (a crear en Streamlit Cloud)

---

## 🎯 Objetivo

Tener una segunda app de Streamlit Cloud apuntando al **mismo repo** pero con:
- Entry point distinto (`dashboard_operaciones.py`)
- **Secrets independientes** (incluyendo usuario Odoo distinto)
- **Auth independiente** (lista de usuarios del equipo Ops)
- **Foco operativo** según el Plan Estratégico Unificado 2026-2028

Esto permite separar visibilidad y permisos sin duplicar código (auth, helpers, services se reusan vía imports).

---

## 🏗️ Arquitectura — qué se agrega y qué se reusa

```
unionx-dashboard/  (mismo repo)
│
├── dashboard_ventas.py                ← App #1 (existente, sin cambios)
├── dashboard_operaciones.py  ⭐NUEVO  ← App #2 entry point
│
├── views/
│   ├── (existentes — se reusan)
│   │   ├── stock_live.py              ← Reutilizado en ambas apps
│   │   ├── sistema_alertas.py         ← Reutilizado en ambas apps
│   │   └── sistema_seguridad.py       ← Reutilizado en ambas apps
│   │
│   ├── _ops_odoo_helper.py    ⭐NUEVO ← Helper OdooClient con creds OPS_*
│   ├── ops_comex.py           ⭐NUEVO
│   ├── ops_fulfillment_ops.py ⭐NUEVO
│   ├── ops_postventa.py       ⭐NUEVO
│   ├── ops_sac.py             ⭐NUEVO
│   ├── ops_logistica.py       ⭐NUEVO
│   ├── ops_costo_operativo.py ⭐NUEVO
│   └── ops_plan_estrategico.py⭐NUEVO
│
└── finanzas-unionx/backend/app/
    └── config.py     MODIFICADO       ← Soporta dual Odoo (OPS_* > ANDRES_*)
```

---

## 1️⃣ Config dual de Odoo

**`finanzas-unionx/backend/app/config.py`** — la clase `Config` ahora resuelve credenciales con esta prioridad:

```python
ODOO_USER = (
    os.getenv("OPS_ODOO_USER")          # 1. App Operaciones
    or os.getenv("ANDRES_ODOO_USER")    # 2. App Ventas (compat backwards)
    or "andres@grupoeter.cl"            # 3. fallback default
)
ODOO_PASSWORD = (
    os.getenv("OPS_ODOO_PASSWORD")
    or os.getenv("ANDRES_ODOO_PASSWORD")
    or ""
)
```

**Comportamiento por app:**

| App | Secret que setea | Credenciales que usa |
|---|---|---|
| `dashboard_ventas.py` | `ANDRES_ODOO_PASSWORD` | `andres@grupoeter.cl` |
| `dashboard_operaciones.py` | `OPS_ODOO_USER` + `OPS_ODOO_PASSWORD` | El usuario que el user defina |

> El usuario para Ops debería ser uno con permisos de lectura sobre stock, picking, helpdesk (no necesita acceso a finanzas).

---

## 2️⃣ Helper `views/_ops_odoo_helper.py`

Provee 2 funciones para uso en cualquier vista Ops:

```python
from views._ops_odoo_helper import get_ops_odoo_client, odoo_status_indicator

# Al inicio del render() de cada vista que usa Odoo:
if not odoo_status_indicator():
    return  # muestra error en sidebar y aborta

# Donde necesites consultas:
odoo = get_ops_odoo_client()
data = odoo.search_read('stock.quant', [...], [...], limit=1000)
```

**Características:**
- Cache `@st.cache_resource` — singleton durante la sesión
- Si faltan credenciales: `None` + mensaje en sidebar
- Si auth falla: `None` + mensaje en sidebar (no rompe la página)

---

## 3️⃣ `dashboard_operaciones.py` — entry point

Mismo patrón que `dashboard_ventas.py` con 4 diferencias:

| Aspecto | Ventas | Operaciones |
|---|---|---|
| `page_title` | "Dashboard UnionX" | "UnionX Operaciones" |
| `page_icon` | 📊 | 🚢 |
| Secrets exportados a env | `ANDRES_ODOO_PASSWORD` | `OPS_ODOO_USER`, `OPS_ODOO_PASSWORD` |
| Secciones del navigation | Ventas / Stock / Contribución / Análisis cruzado / Sistema | COMEX / Fulfillment / Post-venta / SAC / Logística / Plan Estratégico / Sistema |

---

## 4️⃣ Estructura de páginas (Plan Estratégico)

```python
pages = {
    "🚢 COMEX": [
        st.Page(render_ops_comex, title="Embarques activos", default=True),
    ],
    "📦 Fulfillment": [
        st.Page(render_stock_live, title="Stock LIVE"),         # reusa el de Ventas
        st.Page(render_ops_fulfillment, title="Operación bodega"),
        st.Page(render_ops_costo, title="Costo Operativo Total"),
    ],
    "↩️ Post-venta": [
        st.Page(render_ops_postventa, title="Devoluciones & SERNAC"),
    ],
    "💬 SAC": [
        st.Page(render_ops_sac, title="Servicio al Cliente"),
    ],
    "🚚 Logística": [
        st.Page(render_ops_logistica, title="Despacho & Couriers"),
    ],
    "📋 Plan Estratégico": [
        st.Page(render_ops_plan, title="Roadmap H1/H2/H3"),
    ],
    "⚙️ Sistema": [
        st.Page(render_sistema_alertas, title="Alertas"),       # reusa
        st.Page(render_sistema_seguridad, title="Seguridad"),   # reusa
    ],
}
```

---

## 5️⃣ Estado de cada vista (al cierre de implementación inicial)

| Vista | Estado | Próximo hito |
|---|---|---|
| 🚢 COMEX (embarques activos) | 🔧 Stub con tabla de KPIs planificados | Conectar output del agente Gmail |
| 📦 Stock LIVE | ✅ Reutilizado de App Ventas | Funcional con creds OPS_* |
| 📦 Fulfillment ops (OFR/OCT/Accuracy) | 🔧 Stub | Uploader manual mensual H1 |
| ↩️ Post-venta | 🔧 Stub | Tasa devolución desde Odoo (out_refund) H1 |
| 💬 SAC | 🟠 Bloqueado por Helpdesk | H2 — implementar Zendesk/Freshdesk |
| 🚚 Logística | 🔧 Stub parcial | Costo logístico/venta calculable H1 · APIs courier H2 |
| 💰 Costo Operativo Total | 🔧 Stub (port pendiente) | Portar el módulo de eerr-finanzas |
| 📋 Plan Estratégico | ✅ Funcional | — |
| ⚙️ Sistema | ✅ Reutilizado de App Ventas | — |

---

## 6️⃣ Configuración Streamlit Cloud — App #2

### Pasos para crear la 2da app

1. https://share.streamlit.io/ → **New app**
2. Repository: `Andyunionx/unionx-dashboard`
3. Branch: `main`
4. **Main file path:** `dashboard_operaciones.py` ⚠️ **(importante: distinto al app #1)**
5. App URL: `unionx-operaciones` (o lo que quieras)
6. **Advanced settings → Secrets:**

```toml
# Auth (puede ser distinto al de Ventas — ej solo equipo Ops)
[auth]
[auth.credentials.usernames.<user1>]
email = "ops@unionx.cl"
name = "Operaciones"
password = "$2b$12$..."  # hash bcrypt
# ... más usuarios

[auth.cookie]
name = "unionx-ops-auth"  # distinto al de Ventas
key = "<distinto al de Ventas>"
expiry_days = 30

# Odoo — usuario del equipo Ops (NO Andrés)
OPS_ODOO_USER = "operaciones@unionx.cl"
OPS_ODOO_PASSWORD = "<password del usuario Odoo Ops>"

# Si querés Stock LIVE compartido y mostrando el mismo dato que la app Ventas,
# se necesita que OPS_ODOO_USER tenga permisos de lectura sobre stock.quant.

# Resto: solo lo que use esta app específicamente
LIBSQL_URL = "<si querés acceso a la maestra de ventas via Turso>"
LIBSQL_AUTH_TOKEN = "<idem>"

# Service Account Google (si va a leer Sheets)
[gcp_service_account]
# ... mismo bloque que la app Ventas si querés acceso a los mismos Sheets
```

7. Deploy → ~1-2 min

### Crear el usuario Odoo "ops" (paso previo)

Antes de poner `OPS_ODOO_USER` en los secrets, hay que crearlo en Odoo:

1. Login Odoo como Andrés
2. Settings → Users & Companies → Users → Create
3. Datos:
   - Name: "Operaciones UnionX"
   - Email/Login: `operaciones@unionx.cl` (o el que quieras)
   - Generar password segura (gestor de passwords)
4. **Permisos:** lectura sobre Inventory, Manufacturing, Sales (lectura), Helpdesk. **Sin** acceso a Accounting/Finanzas.
5. Save

Después de crear el usuario, su password es lo que va en `OPS_ODOO_PASSWORD`.

---

## 7️⃣ Diferencias prácticas vs App Ventas

| Aspecto | App Ventas | App Operaciones |
|---|---|---|
| URL | `unionx-dashboard-7ppjm2c...` | `unionx-operaciones-...` |
| Usuario Odoo | `andres@grupoeter.cl` (acceso completo) | `operaciones@unionx.cl` (lectura ops) |
| Audiencia | Andrés + comercial + finanzas | Andrés + líderes Ops + bodega + COMEX |
| Cookie auth | `unionx-auth` | `unionx-ops-auth` |
| Sheets (Drive) | Análisis Contribución | Solo lo que se asigne (ej: maestra embarques cuando exista) |

---

## 8️⃣ Patrón replicable — agregar 3ra app

Si en el futuro querés una app más (ej: "UnionX Directorio", solo lectura para CEO), el patrón es:

1. Crear `dashboard_directorio.py` (entry point)
2. Crear `views/dir_*.py` (vistas específicas)
3. (Opcional) Crear helper `views/_dir_helper.py` con prefijo de env vars
4. En Streamlit Cloud: New app → main file path = `dashboard_directorio.py`
5. Secrets propios

El repo se vuelve un mono-repo de N apps de Streamlit, todas compartiendo `views/`, `app/services/`, `app/core/`, etc.

---

## 9️⃣ Troubleshooting

| Síntoma | Causa | Solución |
|---|---|---|
| `🔴 Odoo OPS · sin credenciales` en sidebar | Falta `OPS_ODOO_USER` o `OPS_ODOO_PASSWORD` en Secrets | Setear ambos en Streamlit Cloud Settings |
| `⚠️ OdooClient OPS error: AuthenticationError` | Usuario o password incorrectos | Verificar en Odoo que el user ops existe y la password es correcta |
| Tab Stock LIVE muestra 0 SKUs | Usuario Ops sin permisos de lectura sobre stock | En Odoo: dar permiso "Inventory: User" al usuario ops |
| App #1 deja de funcionar después de cambios | Conflicto en `views/stock_live.py` | Los views compartidos no deben tener side effects globales |
| Login app #2 acepta usuarios de app #1 | Mismo `auth_config.cookie.name` | Cambiar `cookie.name` en secrets de cada app |

---

## 🔟 Checklist antes de hacer push

- [ ] El nuevo entry point levanta sin errores: `streamlit run dashboard_operaciones.py`
- [ ] El sidebar muestra "🟢 Odoo OPS" con creds locales (env var Windows)
- [ ] Las 7 nuevas vistas no rompen al navegarse
- [ ] `python scripts/policia_seguridad.py` pasa verde
- [ ] `dashboard_ventas.py` sigue funcionando (no se rompió la app #1)
- [ ] Pre-commit hook activo

---

## 🔗 Referencias

- **Streamlit multi-app desde 1 repo:** https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
- **st.navigation:** https://docs.streamlit.io/develop/api-reference/navigation/st.navigation
- **st.secrets:** https://docs.streamlit.io/develop/concepts/connections/secrets-management

---

Última actualización: implementación inicial — entry point + 7 stubs + helper Odoo dual + doc.
