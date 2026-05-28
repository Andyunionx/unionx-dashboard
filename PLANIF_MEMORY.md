# 📦 Memoria de Planificación — Felipe Caballero

> Archivo mantenido por Claude. Se actualiza al cierre de cada sesión.
> **NO editar manualmente** — Claude lo sobreescribe en cada cierre.

---

## 🗓️ Última sesión: 2026-05-28

### ✅ Lo que se hizo esta sesión

1. **Setup completo del ambiente de trabajo online**
   - Fork `UnionXFelipe/unionx-planif` creado (no se usa, pero existe)
   - App personal desplegada por Andrés: `https://unionx-planificacion-planner.streamlit.app/`
   - Acceso write a `Andyunionx/unionx-dashboard` confirmado
   - Workflow `auto_pr_planif.yml` activo: cada push a `feat/fc-planif-*` → PR automático a main

2. **Vista "Cobertura por Producto" construida** (`views/planning/triada_cobertura.py`)
   - Funciona 100% con datos locales (sin Turso)
   - Cruza stock actual + tránsito COMEX + forecast Prophet
   - Clasifica por estado: CRÍTICO / URGENTE / AJUSTADO / NORMAL / HOLGADO / SIN DEMANDA
   - Tabs: Por SKU | Por Marca | Por Categoría | Marca × Categoría
   - Registrada en `dashboard_planificacion.py` como página `pln-cobertura`

3. **Mejora visual agregada**
   - Panel semáforo con tarjetas coloreadas por estado (cantidad + % del total)
   - Commit: `7c03be9` — pusheado y PR #65 abierto

---

## 🔲 Pendientes Felipe (próxima sesión)

- [ ] Validar que la vista Cobertura carga bien datos reales en la app online
- [ ] Agregar gráfico de barras apiladas (Plotly) para distribución visual de cobertura
- [ ] Vincular con **Política de stock objetivo** (`views/planning/politicas.py`) para comparar cobertura actual vs objetivo
- [ ] Agregar alerta automática cuando SKUs CRÍTICO > umbral configurable
- [ ] Revisar si el horizonte de tránsito funciona bien con los parquets locales

---

## 🔔 Pendientes para Andrés

- [ ] **PR #65** — "planif: nueva vista Cobertura por Producto (sin Turso)" → revisar y mergear
  - URL: `https://github.com/Andyunionx/unionx-dashboard/pull/65`
  - Qué hace: agrega vista de cobertura + panel semáforo visual
  - Impacto: nueva página en sección Planificación, 0 riesgo en vistas existentes

---

## 🧠 Contexto técnico importante

| Item | Detalle |
|------|---------|
| Branch activo | `feat/fc-planif-onboarding` |
| App personal Felipe | `https://unionx-planificacion-planner.streamlit.app/` |
| App oficial | `https://unionx-planificacion.streamlit.app/` |
| Datos disponibles (locales) | stock_diario.parquet, transito.parquet, forecast_skus_anchored.parquet |
| Turso | Lecturas bloqueadas (billing) — app usa parquets como fallback |
| Credenciales Felipe | usuario: `felipe` — contraseña en `.streamlit/secrets.toml` local |

---

## 📋 Convención de branches Felipe

```
feat/fc-planif-<descripcion-corta>
```
Ej: `feat/fc-planif-compras-priorizacion`, `feat/fc-planif-cobertura-alertas`

---

*Actualizado automáticamente por Claude al cierre de sesión.*
