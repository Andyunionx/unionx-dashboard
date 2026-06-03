# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-05-28 (sesión 2)

### ✅ Lo que se hizo esta sesión

1. **Fix IndexError en panel semáforo** (`triada_cobertura.py` línea 510)
   - Bug: `for i, row in estado_counts.iterrows()` usaba el índice del DataFrame como `i`
   - Después del filtro `SKUs > 0`, los índices eran no secuenciales (ej: 0 y 4)
   - `cols_bar[4]` fallaba si `cols_bar` sólo tenía 2 elementos
   - Fix: `for i, (_, row) in enumerate(estado_counts.iterrows()):`
   - Commit: `0415408`

2. **Fix KeyError `categoria_hijo`** (`triada_cobertura.py` línea 193-196)
   - Bug: `ventas_historico` cargaba OK pero sin columna `categoria_hijo`
   - El bloque `except` sólo ejecutaba si había excepción (no cuando faltaba la columna)
   - Resultado: `dff` no tenía `categoria_hijo` y el `groupby` fallaba con KeyError
   - Fix: Fallback post-try/except garantiza que las columnas siempre existan
   - Commit: `92987a9`

3. **Deploy forzado × 2 vía "Reboot app"** desde el panel Manage app de Streamlit Cloud
   - Streamlit Cloud NO estaba auto-deployando los pushes del branch `feat/fc-planif-onboarding`
   - Causa probable: webhook de GitHub no activo / app registrada como readonly
   - Workaround: usar ⋮ → "Reboot app" después de cada push importante

4. **Vista verificada en producción** — sin errores, todas las secciones cargando:
   - 3 filas de KPIs (forecast, ventas reales 4sem, forecast 3m)
   - Panel semáforo: 🔴 CRÍTICO 74 (68%) | ⬜ SIN DEMANDA 35 (32%)
   - Tabla SKU: 109 SKUs con Cat. Hijo = "Sin clasificar"
   - Sin error al fondo

---

## 🔲 Pendientes Felipe (próxima sesión)

- [ ] Validar tabs "Por Marca", "Por Categoría" y "Marca × Categoría" navegando a ellos manualmente
- [ ] Investigar por qué `ventas_historico` no tiene columna `categoria_hijo` — ¿falta en el parquet?
- [ ] Agregar gráfico de barras apiladas (Plotly) para distribución visual de cobertura
- [ ] Vincular con **Política de stock objetivo** (`views/planning/politicas.py`) para comparar cobertura actual vs objetivo
- [ ] Agregar alerta automática cuando SKUs CRÍTICO > umbral configurable
- [ ] Investigar y activar auto-deploy desde push (actualmente requiere Reboot manual)

---

## 🔔 Pendientes para Andrés

- [ ] **PR #65** — "planif: nueva vista Cobertura por Producto (sin Turso)" → revisar y mergear
  - URL: `https://github.com/Andyunionx/unionx-dashboard/pull/65`
  - Qué hace: agrega vista de cobertura + panel semáforo visual
  - Impacto: nueva página en sección Planificación, 0 riesgo en vistas existentes
  - ⚠️ El PR puede estar desactualizado — branch `feat/fc-planif-onboarding` tiene 3 commits nuevos desde que se abrió

---

## 🧠 Contexto técnico importante

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| Último commit | `92987a9` — fix KeyError categoria_hijo |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| App oficial | `https://unionx-planificacion.streamlit.app/` |
| Datos disponibles (locales) | stock_diario.parquet, transito.parquet, forecast_skus_anchored.parquet |
| Turso | Lecturas bloqueadas (billing) — app usa parquets como fallback |
| Credenciales Felipe | usuario: `felipe` — contraseña en `.streamlit/secrets.toml` local |
| Deploy Streamlit Cloud | NO auto-deploya desde push — requiere "Reboot app" manual desde Manage app |

---

## 📋 Convención de branches Felipe

```
feat/fc-planif-<descripcion-corta>
```
Ej: `feat/fc-planif-compras-priorizacion`, `feat/fc-planif-cobertura-alertas`

---

## 🐛 Bugs corregidos esta sesión

| Bug | Archivo | Línea | Fix |
|-----|---------|-------|-----|
| `IndexError: list index out of range` en panel semáforo | `triada_cobertura.py` | 510 | `enumerate(iterrows())` en vez de `iterrows()` directo |
| `KeyError: 'categoria_hijo'` en tab Categoría → Hijo | `triada_cobertura.py` | 193-196 | Fallback post-try/except para garantizar columna |

---

*Actualizado automáticamente por Claude al cierre de sesión.*
