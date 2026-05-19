# 💰 App Finanzas UnionX — Estado al 19-may-2026

> **Para retomar en otra sesión de Claude.** Este documento es self-contained:
> alguien que lo lea entiende dónde estamos parados sin contexto previo.

---

## 🎯 Sumario ejecutivo

La app **Finanzas** (`dashboard_finanzas.py` → URL `unionx-finanzas.streamlit.app`) ya tiene:

1. **Hero global empresa** al tope de la vista P&L con los 5 KPIs consolidados (Venta, MC, Costo OP, GAV, EBIT) y mini-gráfico de tendencia EBIT mensual Real + Proyectado.
2. **Tab Proyección FCST** que muestra Ene→Dic en una sola tabla mezclando meses reales (FCST cerrado del Sheet Drive) y meses proyectados.
3. **Drill-down automático** al filtrar por canal/LN/KAM, mostrando matriz CC × dimensión con el detalle de cómo se asignó el Costo OP y GAV.
4. **Transparencia del GAV** con banner + lista de áreas incluidas/excluidas + disclaimer del gap.
5. **Pipeline en vivo** con crons que actualizan automáticamente todas las fuentes que alimentan el EBIT.

El último fix grande corrigió el EBIT del hero que estaba mostrando -$80 MM cuando el real era +$48,9 MM (causado por mezclar fuentes incorrectas y duplicar costos).

---

## 📦 Sesiones recientes (19-may-2026)

### Sesión actual — todo mergeado en `main`

| Branch | Estado | Qué hace |
|---|---|---|
| `feat/fin-pyl-mejoras` | ✅ mergeado (PR #50) | Hero global empresa + tab Proyección FCST + drill-down al filtrar + transparencia GAV |
| `fix/fin-pyl-fuentes-correctas` | ✅ mergeado (PR #51) | Cambia fuente del hero a P&L Drive oficial (no Sheet KAM) + fix duplicación Costo OP + driver ARRIENDOS de `unidades` a `venta` |

### PRs todavía pendientes de mergear

| Branch | Prioridad | Qué hace |
|---|---|---|
| **`chore/sync-kam-drive`** | media | Workflow GitHub Actions que extrae el Sheet KAM 1×/día como respaldo del live read |
| **`fix/ops-costo-cache-mtime`** | media (afecta vista Ops, no Finanzas) | Auto-refresh de los 5 tabs de Costo Operativo cuando el cron actualiza `control_gestion.parquet` |

Links:
- https://github.com/Andyunionx/unionx-dashboard/pull/new/chore/sync-kam-drive
- https://github.com/Andyunionx/unionx-dashboard/pulls?q=is%3Apr+is%3Aopen+head%3Afix%2Fops-costo-cache-mtime

---

## 🗂️ Mapa de vistas

Entry point: `dashboard_finanzas.py` (líneas 105-129)

```
🎯 Resumen
  📸 Foto del mes (V/H)            → views/fin_foto_mes.py

💵 Control de Gestión
  💵 PPTO vs FCST (Sheet Drive)    → views/fin_control_gestion.py
  📋 P&L por CC (archivo local)    → views/fin_pyl_cc.py
  📈 P&L por Línea de Negocio      → views/fin_pyl_linea_negocio.py  ⭐ vista principal
                                      Tabs: P&L 7 líneas | Proyección FCST | Drivers |
                                            Detalle | Cómo se calcula | Roadmap

💧 Caja & Balance
  💧 Caja, Deuda & KT              → views/fin_caja_deuda_kt.py

🎯 Forecast
  🎯 Cierre proyectado año         → views/fin_forecast_cierre.py
```

---

## 🏢 Vista principal: P&L por Línea de Negocio

**Archivo:** `views/fin_pyl_linea_negocio.py` (~1.770 líneas)

### Estructura visual (al abrir la vista)

```
┌─────────────────────────────────────────────────────────────────┐
│ 🏢 Vista consolidada UnionX · YTD 2026                           │
│  💰 Venta  📈 MC  ⚙️ Costo OP  🏢 GAV  🎯 EBIT                    │
│                                                                  │
│  📈 Tendencia EBIT mensual (Real sólido verde + Proy punteado)   │
└─────────────────────────────────────────────────────────────────┘
⚠️ Banner amarillo: explicación de las 2 fuentes de datos

🎛️ FILTROS · profundizá por dimensión
  Año | Período (YTD/Q/Mes) | Canal | KAM | LN | Desglose por
─────────────────────────────────────────────────────────────────
[💰 P&L 7 líneas] [🔮 Proyección FCST] [🎚️ Drivers] [📋 Detalle] [ℹ️ Help] [🚀 Roadmap]
```

### Helpers clave (importantes para entender el cálculo)

**Fuente OFICIAL del agregado consolidado** (lo del hero y tab Proyección):

```python
def _consolidado_pyl_drive(year, meses, escenario="FCST") -> dict:
    """Lee control_gestion.parquet y devuelve totales corporativos:
       venta (kpi=VENTA), contribucion (kpi=CONTRIB),
       gasto_operativo (kpi=GASTO + area=OPERACIONES),
       gasto_gav (kpi=GASTO + area NOT IN OPERACIONES),
       ebit = contribucion - gasto_total
    """
```

**Tendencia mensual del hero / tab Proyección:**

```python
def _calcular_tendencia_ebit_anual(year) -> pd.DataFrame:
    """Mezcla:
      - Real: meses con FCST cerrado en P&L Drive (mes < mes actual)
      - Proyectado: meses futuros usando FCST de venta + MC% YTD +
                    promedio Costo OP/GAV mensual.
    Devuelve cols [mes, mes_label, tipo, venta_mm, contrib_mm,
                    costo_op_mm, gav_mm, ebit_mm]
    """
```

**Cálculo P&L 7 líneas (desglose por canal/LN/KAM):** sigue usando Sheet KAM
(`contribucion_filtrada()`) — esta es la única parte que NO viene del Drive
porque el KAM tiene el desglose por canal que el Drive no tiene.

---

## 🚿 Pipeline de actualización en vivo

**Crítico para Andrés:** "Quiero que vaya quedando actualizando".

### Crons activos que alimentan el EBIT

| # | Fuente | Cron file | Frecuencia | Origen |
|---|---|---|---|---|
| 1 | `control_gestion.parquet` ⭐ corazón del EBIT | `sync_pyl_drive.yml` | **1×/día 06:00 Chile** | Sheet Drive `1NfIL-k00pUbF5ogsVnadP2wMAVc7oUKkOA7UMLOT-j0` |
| 2 | `contribucion_kam.parquet` (desgloses canal/KAM) | `sync_kam_drive.yml` ⏳ **PR pendiente** | 1×/día 07:00 Chile | Sheet `1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4` |
| 3 | `pyl_mensual.parquet` + `fcst_eerr.parquet` | `sync_finanzas.yml` | cada 6h | Excel `data/planillas/Planificación Financiera 2026.xlsx` (local) |
| 4 | `ventas_historico.parquet` (drivers meses cerrados) | `freeze_mes.yml` | día 2 de cada mes | Turso (snapshot mensual) |
| 5 | `ventas_mes_actual.parquet` | `sync_mes_actual.yml` | cada 1h (:30) | Turso (live) |
| 6 | `volumen_inventario_hist.parquet` | `sync_kpis_wms.yml` | 2×/día 00:00 y 12:00 Chile | Odoo |

### Live read (no necesita cron, ya está al día)

- **Sheet KAM** se lee EN VIVO en cada sesión usando `gcp_service_account` con cache TTL 30min en `views/_ops_contrib_helper.py:cargar_contribucion_kam()`. El cron del item 2 es solo respaldo por si las credenciales caen.

### Cómo el dato llega del cron a la app

```
[Sheet Drive / Odoo / Excel local]
              ↓
   GitHub Actions cron corre extractor
              ↓
   Commit + push del parquet a main
              ↓
   Streamlit Cloud detecta push → redeploy (~30s)
              ↓
   Cache invalidado por mtime del parquet
              ↓
   Próxima visita = dato fresco
```

### Cache invalidation por mtime

Las funciones cacheadas en `_fin_distribucion.py` y `fin_pyl_linea_negocio.py`
usan el mtime del parquet como cache key, así cuando el cron sobrescribe el
archivo, el cache se invalida automáticamente:

```python
@st.cache_data(ttl=600, show_spinner=False)
def _cargar_costos_operativos_cached(year, meses, escenario,
                                       incluir_cuenta_analitica,
                                       _mtime_key: float):
    ...

def cargar_costos_operativos(year, meses, escenario):
    return _cargar_costos_operativos_cached(
        ..., _mtime_pyl_drive()  # ← invalida cuando cambia el archivo
    )
```

---

## ⚠️ Issues conocidos / Limitaciones

### 1. Gap del Sheet KAM (~12% menos venta vs Drive)

El Sheet KAM "Análisis de Resultados" tiene ~$216 MM menos de venta que el
P&L Drive en YTD-Abr 2026 ($1.605 MM vs $1.821 MM). Causa: canales sin KAM
asignado, NC Aportes mal capturados, etc.

**Mitigación aplicada:**
- Hero usa P&L Drive (números oficiales corporativos)
- Desgloses por canal/KAM siguen usando KAM (es la única fuente con esa info)
- Banner amarillo visible explicando la inconsistencia

**Pendiente para resolver de fondo:** completar el Sheet KAM con los canales
faltantes (responsable: dueños del KAM).

### 2. GAV potencialmente subestimado

`cargar_gav_corporativo()` excluye áreas `{OPERACIONES, LOGISTICA, POSTVENTA}`
para no duplicar con Costo OP. Pero algunos servicios corporativos (legales
puntuales, asesorías estratégicas, seguros corporativos no asignados a área)
pueden no estar cargados en el Sheet Drive todavía.

**Efecto:** EBIT potencialmente sobreestimado.

**Mitigación:** disclaimer visible en el tab P&L explicándolo.

**Pendiente para resolver:** Andrés/contabilidad completar esas cuentas en el
Sheet P&L Drive.

### 3. Driver de ARRIENDOS

Default cambiado de `unidades` a `venta` (más conservador). ML pasó de recibir
27% del arriendo a ~15-18%. Aún no es exacto porque lo ideal sería **m³ × días
en bodega**, pero esa data no existe hoy.

**Pendiente roadmap:** capturar m³ ocupado por canal en Odoo o WMS.

### 4. Diferencia EBIT FCST vs EBIT contable real

El EBIT del hero (FCST oficial del Drive) puede diferir del EBIT contable
real porque el FCST es "lo real cerrado pisado mes a mes por el responsable".
Andrés ha mencionado que su Planificación Financiera muestra +$17 MM YTD-Abr
y el hero muestra +$48,9 MM. La diferencia es atribuible a esa convención
del FCST vs contable.

---

## 📋 Stand-by features (no se hicieron, esperando definición)

### 1. EBIT por canal — vista dedicada con waterfall y ranking

Se creó en una sesión, después se borró por scope creep
(Andrés clarificó que el desglose por canal ya existe en P&L por LN).
**Si se quisiera retomar:** branch `feat/fin-ebit-por-canal` ya no existe,
pero la lógica está disponible reutilizando `_consolidado_pyl_drive()` y
`contribucion_filtrada(desglose_por="canal")`.

### 2. GAV específico por canal (costos fijos directos)

Asignación directa (no por driver heurístico) de:
- Gerente comercial → sus canales
- KAM → su canal específico
- Planner → sus LNs
- Equipo producto → su categoría

Requeriría:
- Tabla manual de mapping editable en UI (uploader)
- Persistencia en Turso o JSON local

### 3. PPTO vs FCST vs Real comparativo

Hoy el hero muestra solo FCST. Sería útil tener comparativo:
- PPTO original
- FCST actual (pisado por responsable)
- Real contable (cuando esté cerrado el mes)

Roadmap menciona esto pero no está implementado.

### 4. Sensitivity analysis del EBIT

"¿Qué pasa si crece la venta 10%?" — calcular automáticamente el delta
de EBIT con elasticidad de costos variables.

### 5. Alertas EBIT por canal

- Canal con EBIT% < umbral (ej: < -10%)
- Canal con EBIT% deteriorándose mes a mes
- Break-even por canal (cuánta venta necesita para EBIT=0)

---

## 🔧 Notas técnicas importantes

### Fuentes de datos y dónde viven

```
data/finanzas/
  control_gestion.parquet         ⭐ P&L Drive oficial (Venta, MC, Costo OP, GAV)
  control_gestion_resumen.json    ↳ metadata del extract
  contribucion_kam.parquet         Sheet KAM (desgloses por canal/KAM/LN)
  pyl_mensual.parquet              Planif Financiera (P&L mensual)
  fcst_eerr.parquet                Planif Financiera (FCST venta)

data/historico/
  ventas_historico.parquet         Snapshot meses cerrados (drivers)
  ventas_mes_actual.parquet        Mes en curso (live de Turso)

data/operaciones/
  costo_operativo.parquet          ⚠️ DEPRECADO — ya NO se usa por la vista
                                      (tenía clasificación rota). Mantener
                                      hasta confirmar que nada lo lee.
  volumen_inventario_hist.parquet  Pedidos/unidades reales (Odoo)
```

### Drivers default por Centro de Costo

`views/_fin_distribucion.py:DRIVER_DEFAULT_POR_CC`:

| CC | Driver | Razón |
|---|---|---|
| REMUNERACIONES, BENEFICIOS, MOVILIZACIÓN, MANTENCIÓN | `pedidos` | Operadores procesan pedidos |
| INSUMOS | `unidades` | Cartón/etiquetas escalan con unidades físicas |
| **ARRIENDOS** | **`venta`** ⚠️ cambiado de `unidades` | ML mueve unidades chicas, no proporcional al espacio |
| HONORARIOS, SEGUROS, GASTOS OFICINA | `venta` | Servicios proporcionales al revenue |
| SUSCRIPCIÓN/SW | `equitativo` | SaaS independiente del volumen |

### Drivers default por Área GAV

`views/_fin_distribucion.py:DRIVER_DEFAULT_POR_AREA_GAV`:

| Área | Driver |
|---|---|
| COMERCIAL, MARKETING, FIN/ADMIN, UNIONX, TIENDA | `venta` |
| GRUPO ETER, LEGALES Y NOTARIALES | `equitativo` |

### Áreas operativas excluidas del GAV (para no duplicar con Costo OP)

`AREAS_OPERATIVAS_EXCLUIR = {"OPERACIONES", "LOGISTICA", "POSTVENTA"}`

En realidad solo `OPERACIONES` aparece como `area` en el Drive — `LOGISTICA`
y `POSTVENTA` están como `sub_area` dentro de `OPERACIONES`. La exclusión
sigue siendo correcta por defensiveness.

### Streamlit Secrets requeridos en la app Finanzas

```toml
[gcp_service_account]
# JSON completo del service account para leer Sheets
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "..."
client_email = "union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com"
...

# Turso (DB ventas live)
LIBSQL_URL = "..."
LIBSQL_AUTH_TOKEN = "..."

# Odoo (para queries en vivo de stock)
OPS_ODOO_USER = "..."
OPS_ODOO_PASSWORD = "..."
ANDRES_ODOO_PASSWORD = "..."

# Auth de la app
FIN_ALLOWED_EMAILS = "andres@unionx.cl,..."
FIN_COOKIE_SECRET = "..."
```

### Secret de GitHub Actions requerido

`GOOGLE_CREDENTIALS_JSON` — usado por los workflows que leen Sheets (P&L Drive,
KAM, costo operativo legacy).

---

## 📝 Para retomar la próxima sesión

1. **Mergear los 2 PRs pendientes** si todavía no se hicieron:
   - `chore/sync-kam-drive`
   - `fix/ops-costo-cache-mtime`

2. **Verificar deploy en Streamlit Cloud** después del merge: la app debería
   refrescar automáticamente (~30s). Probar:
   - Abrir `unionx-finanzas.streamlit.app` → ir a "P&L por Línea de Negocio"
   - Verificar que el hero muestra EBIT YTD positivo (~$48 MM al 19-may)
   - Verificar que el banner amarillo de las 2 fuentes aparece
   - Cambiar filtro a un canal específico (ej: Mercado Libre) → debería abrirse
     auto el expander "Cómo se calculó el Costo OP y GAV con tus filtros"
   - Ir al tab "Proyección FCST" → verificar tabla Ene-Dic + gráfico apilado

3. **Tareas pendientes en orden de valor**:
   - **A** completar Sheet KAM con canales faltantes (no es código, es data)
   - **B** completar Sheet P&L Drive con cuentas corporativas faltantes (GAV gap)
   - **C** GAV por canal directo (tabla manual de mapping)
   - **D** Comparativo PPTO vs FCST vs Real
   - **E** Sensitivity analysis del EBIT
   - **F** Alertas EBIT por canal

4. **Sesión actual está enfocada en Operaciones** — no tocar Finanzas hasta
   nueva indicación.

---

## 🔗 Referencias rápidas

- **App URL**: https://unionx-finanzas.streamlit.app
- **Repo**: https://github.com/Andyunionx/unionx-dashboard
- **Sheet P&L Drive**: https://docs.google.com/spreadsheets/d/1NfIL-k00pUbF5ogsVnadP2wMAVc7oUKkOA7UMLOT-j0
- **Sheet KAM**: https://docs.google.com/spreadsheets/d/1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4

### Comandos útiles

```bash
# Re-extraer P&L Drive a mano (si necesitas validar cambios del Sheet)
python extract_finanzas_control_gestion.py

# Re-extraer KAM a mano
python extract_kam_contribucion.py

# Disparar workflows desde GitHub UI
# Actions → "Sync P&L Drive..." → Run workflow
# Actions → "Sync KAM Drive..." → Run workflow

# Smoke test del cálculo del EBIT (script de auditoría)
python -c "
import sys, types
sys.path.insert(0, '.')
# Mock streamlit
st_mod = types.ModuleType('streamlit')
class _D:
    def __getattr__(self, n): return self
    def __call__(self, *a, **k): return self
st_mod.cache_data = lambda **k: (lambda f: f)
st_mod.session_state = {}
st_mod.secrets = {}
sys.modules['streamlit'] = st_mod
from views import fin_pyl_linea_negocio as v
res = v._consolidado_pyl_drive(year=2026, meses=[1,2,3,4], escenario='FCST')
for k, val in res.items():
    if 'pct' in k: print(f'{k}: {val:.1f}%')
    elif k == 'n_filas': print(f'{k}: {val}')
    else: print(f'{k}: \${val/1e6:,.1f} MM')
"
```

---

_Documento generado: 19-may-2026 · Última sesión enfocada en app Finanzas._
