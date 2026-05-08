# 💼 Contribución Comercial — Implementación completa

Documento de referencia para entender, mantener y replicar la sección "💼 Contribución" del dashboard de Streamlit Cloud.

**Fuente de datos:** Google Sheets (lectura en vivo via Service Account `union-x-revenue-bot`)
**Sheet:** [Análisis de Contribución](https://docs.google.com/spreadsheets/d/1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4/edit)
**App desplegada:** https://unionx-dashboard-7ppjm2cem2zkfxwzkv3pzc.streamlit.app/

---

## 🎯 Objetivo

Mostrar el análisis de Contribución Comercial dentro del dashboard de ventas, leyendo en vivo desde el Google Sheet "Análisis de Contribución" con cache de **1 hora** (refresh manual disponible en cada vista). Sin uploaders ni copias locales — la data fluye desde la fuente que el equipo ya mantiene en Drive.

---

## 🏗️ Arquitectura — los 6 archivos que importan

```
unionx-dashboard/
│
├── dashboard_ventas.py                          ← Entry point Streamlit Cloud
│   └── pages = {... "💼 Contribución": [...] }  ← se agregan 4 sub-páginas
│
└── views/
    ├── _contribucion_loader.py    ⭐ NUEVO       ← Helper común: gspread, parse, formatos
    ├── contribucion_general.py    ⭐ NUEVO       ← Vista General (Resumen Resultados)
    ├── contribucion_meta.py       ⭐ NUEVO       ← Meta vs Resultado (con semáforos)
    ├── contribucion_kam.py        ⭐ NUEVO       ← Ranking + drill-down por KAM/Canal
    └── contribucion_detalle.py    ⭐ NUEVO       ← Drill-down filtrable Año/Q/Mes/...
```

**Patrón:** una vista por sub-página, cada una llama al loader común. Cache 1 hora vía `@st.cache_data(ttl=3600)`.

---

## 1️⃣ `_contribucion_loader.py` — Helper común

Ubicación: `views/_contribucion_loader.py`

### Responsabilidades

- **`_gspread_client()`** — singleton del cliente gspread
  - En **Streamlit Cloud:** lee de `st.secrets["gcp_service_account"]`
  - En **local:** lee de `credentials.json` en raíz
- **`cargar_hoja(nombre)`** — lee hoja del Sheet → DataFrame, cacheado 1 hora
- **`parse_numero(val)`** — convierte formato chileno (`'22.043.655'` → `22043655.0`, `'63%'` → `0.63`)
- **`parsear_columnas_numericas(df, cols)`** — helper masivo
- **`fmt_pesos_M`, `fmt_pesos_K`, `fmt_pct`** — formateo display
- **`color_cumplimiento(pct)`** — semáforo según % vs meta (🟢≥100% / 🟡≥85% / 🔴<85%)

### Constante clave

```python
SHEET_ID = "1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4"
```

### Patrón de uso desde una vista

```python
from views._contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas,
    fmt_pesos_M, fmt_pct, color_cumplimiento,
)

df = cargar_hoja("Resumen Resultados")  # cacheado
df = parsear_columnas_numericas(df, ["Venta KAM", "% Margen"])
```

---

## 2️⃣ Hojas del Sheet usadas

El Sheet "Análisis de Contribución" tiene 8 hojas. Usamos 4:

| Hoja | Vista | Filas | Columnas clave |
|---|---|---|---|
| **Resumen Resultados** | Vista General | 1982 | AÑO, Mes, Negocio, Canal, Venta KAM, Venta REAL, % Margen Directo, % Comisión Venta/Envío/Marketing, % Resultado Contribución |
| **Resumen General Meta - Resultad** | Meta vs Resultado | 994 | Trimestre, Mes, Negocio, Meta Venta, Resultado Venta, % Cumplimiento Venta, Meta Contribución, Resultado Contribución, % Cumplimiento Contribución |
| **Comparación Resultados Kam** | Por KAM | 994 | KAM, Canal, Venta KAM, Margen Directo, Comisión Venta/Envío, Marketing, Resultado Contribución (+columnas contables) |
| **Analisis Meta vs Resultados** | Análisis detallado | 1453 | AÑO, Negocio, Canal, KAM, Mes, Trimestre, Meta Venta, Resultado Venta, %, Meta Contribución, Resultado Contribución, % |

> Las otras 4 hojas (`Detalle Glosas 2026`, `Detalle fact provisión 2026`, `Detalle fuera de mes`, `Analisis de Resultados`) están disponibles para futuras vistas.

---

## 3️⃣ Vistas implementadas

### 📊 Vista General (`contribucion_general.py`)
- Filtros: Año, Mes, Negocio
- KPIs: Venta REAL, Venta KAM, % Margen Directo, % Contribución
- Tabla: detalle del Resumen Resultados con formatos display

### 🎯 Meta vs Resultado (`contribucion_meta.py`)
- Filtros: Trimestre, Negocio
- Tabla: cumplimiento Meta/Real con 🚦 (Venta + Contribución por línea)
- Gráfico: % Cumplimiento promedio por Negocio (Venta vs Contrib) con línea referencia 100%

### 👤 Por KAM (`contribucion_kam.py`)
- Forward-fill del campo KAM (en el Sheet aparece solo en 1ra fila del grupo)
- Filtros: KAM, Canal
- Ranking top KAMs por venta total, con Margen % y Contrib %
- Detalle KAM × Canal con Venta, Comisiones desglosadas, Contribución

### 🔬 Análisis detallado (`contribucion_detalle.py`)
- 5 filtros multiselect: Año, Negocio, Canal, KAM, Trimestre
- KPIs agregados según filtros: Venta Real, Contrib Real, % Cumplimiento Venta y Contrib, Margen Contribución
- Tabla filtrable con Meta/Real/Cumplimiento por cada combinación

---

## 4️⃣ Integración con `dashboard_ventas.py`

### Imports (al final de la sección de imports de views)

```python
from views.contribucion_general import render as render_contrib_general
from views.contribucion_meta import render as render_contrib_meta
from views.contribucion_kam import render as render_contrib_kam
from views.contribucion_detalle import render as render_contrib_detalle
```

### Sección agregada al `pages` dict

```python
pages = {
    "📊 Ventas": [...],
    "📦 Stock": [...],
    "💼 Contribución": [
        st.Page(render_contrib_general, title="Vista General", icon="📊", url_path="contrib-general"),
        st.Page(render_contrib_meta, title="Meta vs Resultado", icon="🎯", url_path="contrib-meta"),
        st.Page(render_contrib_kam, title="Por KAM", icon="👤", url_path="contrib-kam"),
        st.Page(render_contrib_detalle, title="Análisis detallado", icon="🔬", url_path="contrib-detalle"),
    ],
    "🔄 Análisis cruzado": [...],
}
```

---

## 5️⃣ Configuración Streamlit Cloud — Secrets

Para que funcione en cloud necesitás un secret `gcp_service_account` con el contenido completo del `credentials.json`.

### Pasos

1. Abrí `credentials.json` local
2. Convertilo a TOML (estructura plana de `[gcp_service_account]`)
3. https://share.streamlit.io/ → tu app → Settings → Secrets
4. Pegá el bloque (debajo de los secrets que ya tenés):

```toml
# Secrets que ya tenés
LIBSQL_URL = "..."
LIBSQL_AUTH_TOKEN = "..."
ANDRES_ODOO_PASSWORD = "..."

[auth]
# auth_config existente...

# NUEVO: Service Account para leer Google Sheets
[gcp_service_account]
type = "service_account"
project_id = "union-x-revenue"
private_key_id = "<copiar de credentials.json>"
private_key = """-----BEGIN PRIVATE KEY-----
<copiar la private key, manteniendo los \n como saltos de linea reales>
-----END PRIVATE KEY-----
"""
client_email = "union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com"
client_id = "<copiar>"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "<copiar>"
universe_domain = "googleapis.com"
```

5. Save → Streamlit reinicia solo

### Compartir el Sheet con el SA

Si querés que el SA acceda a OTRO Sheet en el futuro, compartilo con:
```
union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com
```
Permisos: **Viewer** (solo lectura) o **Editor** si necesitás escribir.

---

## 6️⃣ Performance esperada

| Acción | Tiempo |
|---|---|
| 1ra carga de una hoja | 2-5s (request HTTP a Sheets API) |
| 2da-Nva carga (cache válido) | <100ms (instantáneo) |
| Cache invalida automáticamente | a los **60 minutos** |
| Botón "🔄 Refrescar" | invalida cache global de la sesión (instantáneo) |

**Comparación vs Stock LIVE:** las hojas de Contribución son chicas (1000-2000 filas) y la API de Sheets es rápida → mucho más liviano que la consulta Odoo del Stock LIVE.

---

## 7️⃣ Patrón replicable — otra fuente Drive

Si querés agregar otro Sheet (otra carpeta, otro flujo):

### Paso 1: Compartir el Sheet con el SA
Email: `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com`

### Paso 2: Crear nuevo loader (si es otro Sheet)
Copiar `views/_contribucion_loader.py`, cambiar `SHEET_ID` constante.

O, si es la misma estructura: usar el loader existente y solo agregar funciones helper específicas.

### Paso 3: Crear views nuevas
Patrón:
```python
from views._mi_loader import cargar_hoja, fmt_pesos_M

def render():
    st.title("Mi nueva vista")
    if st.button("🔄 Refrescar"):
        st.cache_data.clear()
        st.rerun()
    df = cargar_hoja("MiHoja")
    # ... render
```

### Paso 4: Registrar en `dashboard_ventas.py`
```python
from views.mi_vista import render as render_mi_vista
# Agregar a pages dict en la sección que corresponda
```

---

## 8️⃣ Troubleshooting

| Síntoma | Causa probable | Solución |
|---|---|---|
| `PermissionError: caller does not have permission` | Sheet no compartido con el SA | Compartir el Sheet con `union-x-revenue-bot@...` |
| `FileNotFoundError: credentials` (local) | Falta `credentials.json` en raíz | Descargar nueva key del SA en Google Cloud Console |
| `KeyError: 'gcp_service_account'` (cloud) | Secret no configurado | Agregar bloque `[gcp_service_account]` en Streamlit Cloud Secrets |
| Datos viejos pese a actualización del Sheet | Cache 1 hora vigente | Botón "🔄 Refrescar" o esperar hasta 1 hora |
| Columnas con valores raros (texto en vez de números) | Format chileno no parseado | Agregar la columna al `cols_num` y llamar `parsear_columnas_numericas` |
| KAM aparece vacío en algunas filas | El Sheet usa "merge cells" visualmente | Aplicar `df["KAM"] = df["KAM"].replace("", pd.NA).ffill()` |

---

## 9️⃣ Checklist antes de hacer push

- [ ] El SA tiene acceso al Sheet (`gspread` puede abrirlo localmente)
- [ ] Las vistas levantan localmente: `streamlit run dashboard_ventas.py`
- [ ] No hay secretos hardcoded (sin `private_key` ni emails de SA en código fuente)
- [ ] `python scripts/policia_seguridad.py` pasa verde
- [ ] Si agregaste hojas/columnas nuevas, documentadas acá
- [ ] Pre-commit hook activo

---

## 🔗 Referencias

- **gspread docs:** https://docs.gspread.org/en/latest/
- **Streamlit secrets:** https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- **st.cache_data:** https://docs.streamlit.io/develop/concepts/architecture/caching
- **Google Sheets API:** https://developers.google.com/sheets/api/guides/concepts
- **Sheet Análisis Contribución:** https://docs.google.com/spreadsheets/d/1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4/

---

Última actualización: implementación inicial Contribución Comercial — 4 vistas + helper común + integración `dashboard_ventas.py`.
