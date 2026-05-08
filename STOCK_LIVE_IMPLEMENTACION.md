# 📦 Stock LIVE — Implementación completa

Documento de referencia para entender, mantener y replicar el patrón "Stock en vivo" (cache 5 min desde Odoo) integrado al dashboard de Streamlit Cloud.

**Repo:** https://github.com/Andyunionx/unionx-dashboard
**App desplegada:** https://unionx-dashboard-7ppjm2cem2zkfxwzkv3pzc.streamlit.app/
**Commits:** `2c5c5e5` (sistema completo) + `89b3158` (tab en dashboard_ventas.py)

---

## 🎯 Objetivo

Mostrar inventario en vivo desde Odoo, con clasificación por **semáforo a 3 meses** (target stock), **ocupación de bodega CA1/Stock** y **rotación 30d/90d**, dentro del dashboard de ventas existente.

---

## 🏗️ Arquitectura — los 4 archivos que importan

```
unionx-dashboard/
│
├── dashboard_ventas.py                                    ← Tab "📦 Stock LIVE" (entrada Streamlit Cloud)
│
└── finanzas-unionx/backend/app/
    ├── core/odoo_client.py                                ← XML-RPC client con retry/batching
    ├── services/stock_advanced_service.py  ⭐ NUEVO       ← Lógica de cálculo (port del Streamlit standalone)
    ├── api/stock.py                                       ← 4 endpoints REST nuevos (modo Flask local)
    └── ...
└── finanzas-unionx/backend/run.py                         ← APScheduler refresh cada 5 min (modo Flask local)
```

**Importante:** En **Streamlit Cloud** se usa SOLO `dashboard_ventas.py` + `stock_advanced_service.py` + `odoo_client.py`. La API Flask (`api/stock.py`) y el APScheduler (`run.py`) son para uso local con frontend React. Streamlit Cloud usa `@st.cache_data(ttl=300)` que es funcionalmente equivalente al APScheduler.

---

## 1️⃣ `stock_advanced_service.py` — Lógica core (360 líneas)

Ubicación: `finanzas-unionx/backend/app/services/stock_advanced_service.py`

### Constantes de clasificación de ubicaciones

```python
FULFILLMENT_KEYWORDS = ["BFML", "BFP", "BFR", "BFW", "Fulfillment", "fulfillment"]
MARKETING_KEYWORDS   = ["Mk", "Marketing", "BMPE", "BMPN", "BMPVS"]
PV_OUTLET_KEYWORDS   = ["BPV", "Post Venta", "Outlet", "Bo"]
```

### Estructura de la clase

```python
class StockAdvancedService:
    def __init__(self, odoo: OdooClient): ...

    # Extracción cruda desde Odoo
    def _fetch_locations(self) -> Dict           # stock.location internos + jerarquía
    def _fetch_quants(self) -> List              # stock.quant con quantity > 0
    def _fetch_products(self) -> Dict            # product.product storable+active
    def _fetch_sales_30_90(self) -> Dict         # sale.order.line últimos 90d, separa 30d

    # Cálculos
    @staticmethod
    def compute_occupancy(locations) -> Dict      # CA1/Stock: posiciones físicas usadas
    @staticmethod
    def _classify_location(complete_name) -> str  # Fulfillment/Marketing/PV-Outlet/Planner
    @staticmethod
    def _semaforo(qty, dias_stock, vta_30d) -> str

    # Procesamiento
    def process(self, locations, quants, products, ventas) -> (df, df_agg)

    # Punto de entrada principal (lo que llama Streamlit)
    def extract_full(self, progress_callback=None) -> Dict
```

### Lógica del semáforo (5 categorías + 1)

```python
@staticmethod
def _semaforo(qty: float, dias_stock: float, vta_30d: float) -> str:
    if qty == 0 and vta_30d > 0:
        return "QUIEBRE"          # 🔴 Sin stock pero hay demanda
    if dias_stock < 30:
        return "CRITICO"          # 🔴 < 30 días de stock
    if dias_stock < 90:
        return "BAJO"             # 🟡 30-89 días
    if dias_stock <= 180:
        return "OPTIMO"           # 🟢 90-180 días (target 3 meses)
    if dias_stock > 180 and vta_30d > 0:
        return "SOBRESTOCK"       # 🔵 > 180 días con venta
    return "SIN VENTA"            # ⚪ Sin movimiento 30d
```

### Cálculo de días de stock + rotación

```python
# Días de stock = inventario / venta diaria de últimos 30 días
agg["Vta Diaria"] = agg["Vta 30d Qty"] / 30
agg["Dias Stock"] = agg.apply(
    lambda r: round(r["Qty"] / r["Vta Diaria"]) if r["Vta Diaria"] > 0 else 999,
    axis=1
)

# Rotación en unidades = veces que rota el stock en el período
agg["Rot 30d Uds"] = round(agg["Vta 30d Qty"] / agg["Qty"], 2)
agg["Rot 90d Uds"] = round(agg["Vta 90d Qty"] / agg["Qty"], 2)

# Rotación en costo = costo de ventas del período / valor inventario
agg["Costo Vta 30d"] = agg["Vta 30d Qty"] * agg["Costo Unit"]
agg["Rot 30d $"] = round(agg["Costo Vta 30d"] / agg["Valor"], 2)
```

### Cálculo de ocupación CA1/Stock

```python
@staticmethod
def compute_occupancy(locations: Dict) -> Dict:
    """Posiciones físicas = hijas directas (leaf) de CA1/Stock."""
    positions = []
    for lid, loc in locations.items():
        cn = loc.get("complete_name", "")
        if not cn.startswith("CA1/Stock/"):
            continue
        is_leaf = len(loc.get("child_ids", [])) == 0
        if not is_leaf:
            continue
        has_stock = len(loc.get("quant_ids", [])) > 0
        positions.append({
            "Posicion": cn.replace("CA1/Stock/", ""),
            "Estado": "Ocupada" if has_stock else "Vacia",
            "SKUs": len(loc.get("quant_ids", [])),
        })
    total = len(positions)
    occupied = sum(1 for p in positions if p["Estado"] == "Ocupada")
    return {
        "positions": positions,
        "total": total,
        "occupied": occupied,
        "empty": total - occupied,
        "pct": round(occupied / total * 100, 1) if total > 0 else 0,
    }
```

### Output de `extract_full()`

```python
{
    "metadata": {
        "generado_en": "2026-05-08T14:30:00",
        "total_skus": 612,
        "total_quants": 4521,
        "total_locations": 287,
    },
    "kpis": {
        "n_skus": 612,
        "valor_total": 1234567890.0,
        "unidades_total": 45678.0,
        "n_quiebre_critico": 12,
        "n_bajo": 45,
        "n_optimo": 380,
        "n_sobrestock": 87,
        "n_sin_venta": 88,
        "rot_30d_promedio": 0.42,
        "rot_90d_promedio": 1.18,
    },
    "ocupacion": {
        "total": 250, "occupied": 198, "empty": 52, "pct": 79.2,
        "positions": [...],
    },
    "semaforo": [
        {"Categoria": "OPTIMO", "SKUs": 380},
        {"Categoria": "SIN VENTA", "SKUs": 88},
        ...
    ],
    "valor_bodega": [
        {"Bodega": "CA1", "Valor": 980000000, "Unidades": 32000, "SKUs": 450},
        ...
    ],
    "skus": [...],     # df_agg.to_dict(orient="records")
    "detalle": [...],  # df_full.to_dict(orient="records")
}
```

---

## 2️⃣ Tab en `dashboard_ventas.py` — Integración Streamlit Cloud

### Imports necesarios (al inicio del archivo)

```python
# Streamlit Cloud: exponer secretos como env vars
for _key in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN', 'ANDRES_ODOO_PASSWORD'):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

from app.services.maestra_service import MaestraService
from app.services.stock_advanced_service import StockAdvancedService  # ⭐ NUEVO
from app.core.odoo_client import OdooClient                            # ⭐ NUEVO
from app.config import Config                                          # ⭐ NUEVO
```

### Declaración de tabs (línea ~445)

```python
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Vista General",
    "📅 Vista Semanal",
    "📤 Cargar offline",
    "📦 Stock LIVE",   # ⭐ NUEVO
])
```

### Contenido del Tab 4 (línea ~685 hasta el final, 140 líneas)

**Estructura general:**

```python
with tab4:
    # 1. Validar credenciales
    if not Config.ODOO_PASSWORD:
        st.error("⚠️ Falta ANDRES_ODOO_PASSWORD en Streamlit Cloud Secrets...")
        st.stop()

    # 2. Cache de 5 min — equivalente al APScheduler en modo Flask
    @st.cache_data(ttl=300, show_spinner="Consultando Odoo (puede tomar 30-60s la primera vez)…")
    def _stock_live_data():
        odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
        service = StockAdvancedService(odoo)
        return service.extract_full(progress_callback=None)

    # 3. Llamar (cacheado) y manejar errores
    try:
        stock_data = _stock_live_data()
    except Exception as e:
        st.error(f"❌ Error consultando Odoo: {type(e).__name__}: {e}")
        st.stop()

    # 4. Render: 6 KPIs semáforo + Ocupación + Distribución + Valor por bodega + Tabla SKUs
    # ... (ver dashboard_ventas.py líneas 685-820 para detalle completo)
```

### Botón refresh manual (forzar invalidar cache)

```python
if st.button("🔄 Refrescar Odoo", key="stock_live_refresh"):
    _stock_live_data.clear()  # invalida el cache
    st.rerun()                # vuelve a renderizar
```

---

## 3️⃣ Configuración de Streamlit Cloud — Secrets

**Sin esto el tab muestra error.** Pasos:

1. https://share.streamlit.io/ → tu app `unionx-dashboard`
2. Click `⋮` (3 puntos) → **Settings** → tab **Secrets**
3. Pegar (en formato TOML):

```toml
ANDRES_ODOO_PASSWORD = "tu-password-nueva"

# Otros secrets que ya existen y NO hay que tocar:
# LIBSQL_URL = "..."
# LIBSQL_AUTH_TOKEN = "..."
```

4. **Save** → Streamlit reinicia la app automáticamente (~30s)
5. Refrescar el navegador en la URL pública

---

## 4️⃣ `app/config.py` — Cómo se lee la password

```python
# finanzas-unionx/backend/app/config.py
class Config:
    ODOO_URL = 'https://unionxb2b.odoo.com'
    ODOO_DB = 'bmya-innovatek-sh-prd-6981800'
    ODOO_USER = 'andres@grupoeter.cl'
    ODOO_PASSWORD = os.getenv('ANDRES_ODOO_PASSWORD')  # ← lee de env var
```

> 🔒 **Seguridad:** la password NUNCA se hardcodea. Siempre vía env var. En Streamlit Cloud es vía `st.secrets`. En local es vía `.env` o env var de Windows.

---

## 5️⃣ `odoo_client.py` — Cliente XML-RPC

Ubicación: `finanzas-unionx/backend/app/core/odoo_client.py`

**Métodos clave que usa el StockAdvancedService:**

```python
client.search_read(model, domain, fields, limit=N)              # query simple
client.search_read_paginated(model, domain, fields, page_size)  # paginado para queries grandes
client.execute_in_batches(model, ids, fields, batch_size=N)     # batching adaptativo si falla
```

**Características:**
- Reintentos exponenciales (10 intentos con jitter)
- Backoff inteligente
- Reducción dinámica de batch size si falla
- Logging detallado

---

## 6️⃣ Performance esperada

| Acción | Tiempo |
|---|---|
| 1ra carga del tab (consulta Odoo) | 30-60s |
| 2da-Nva carga (cache válido) | <1s (instantáneo) |
| Cache invalida automáticamente | a los 5 min |
| Botón "🔄 Refrescar" | invalida y consulta de nuevo |

**Streamlit Cloud timeout:** 60s por callback. La consulta cabe justo. Si crece la cantidad de SKUs y se va a 80s+, se puede:
- Reducir `limit` en queries de quants/lineas
- Aumentar TTL del cache a 600s (10 min)
- Migrar el extract a un job pre-ejecutado (cron Streamlit)

---

## 7️⃣ Patrón replicable — para crear próximos tabs

Para agregar **Comercial / Margen / Ocupación / lo que sea**, seguir este patrón:

### Paso 1: Crear el servicio
```
finanzas-unionx/backend/app/services/<area>_service.py
```
- Clase con `__init__(odoo)` y un método `extract_full(progress_callback=None)`
- Devuelve dict con `metadata`, `kpis`, `<otros bloques>`

### Paso 2: Importar en dashboard_ventas.py
```python
from app.services.<area>_service import <Area>Service
```

### Paso 3: Agregar el tab
```python
tabN = st.tabs([..., "<emoji> <Nombre>"])[N]

with tabN:
    @st.cache_data(ttl=300)
    def _<area>_data():
        odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
        return <Area>Service(odoo).extract_full()

    data = _<area>_data()
    # ... render
```

### Paso 4: Si requiere nueva env var
- Agregar al loop de secrets en dashboard_ventas.py:
  ```python
  for _key in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN', 'ANDRES_ODOO_PASSWORD', '<NUEVO>'):
  ```
- Setear en Streamlit Cloud Secrets

---

## 8️⃣ Troubleshooting

| Síntoma | Causa probable | Solución |
|---|---|---|
| `⚠️ Falta ANDRES_ODOO_PASSWORD` | Secret no configurado en Streamlit Cloud | Settings → Secrets → agregar |
| `Error consultando Odoo: AuthenticationError` | Password incorrecta | Re-rotar en Odoo, actualizar Secret |
| Tab tarda >60s y timeout | Demasiados SKUs / queries lentas | Reducir limits o aumentar TTL |
| `ImportError: stock_advanced_service` | Path no incluye finanzas-unionx/backend | Verificar `sys.path.insert(0, ...)` al inicio del dashboard |
| Cache no se actualiza | TTL no expiró | Botón "🔄 Refrescar" o `st.cache_data.clear()` |

---

## 9️⃣ Checklist antes de hacer push de cambios al Stock

- [ ] El servicio sigue devolviendo el contrato esperado (las claves del dict)
- [ ] El tab en `dashboard_ventas.py` no tiene secretos hardcoded
- [ ] Si hay nuevas env vars: están en `.env.template` + documentadas en `SEGURIDAD.md`
- [ ] `python scripts/policia_seguridad.py` pasa verde
- [ ] Pre-commit hook activo (`.git/hooks/pre-commit`)
- [ ] Probar localmente antes: `streamlit run dashboard_ventas.py`

---

## 🔗 Referencias

- **Streamlit secrets:** https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- **st.cache_data:** https://docs.streamlit.io/develop/concepts/architecture/caching
- **Odoo XML-RPC API:** https://www.odoo.com/documentation/18.0/developer/reference/external_api.html
- **APScheduler:** https://apscheduler.readthedocs.io/

---

Última actualización: implementación completa Stock LIVE — commits `2c5c5e5` + `89b3158`.
