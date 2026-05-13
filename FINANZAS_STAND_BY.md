# 💰 App Finanzas — Stand By (paso a paso para retomar)

> **Cuando Andrés diga "retomemos finanzas", leer este archivo y mandar
> exactamente el contenido de la sección "MENSAJE COMPLETO PARA RETOMAR"
> al final.**

**Último commit con todo el código:** `7e7b81d`

---

## Estado actual (snapshot)

✅ **Lo que está hecho y pusheado:**

```
dashboard_finanzas.py                      ← entry point, sidebar verde
extract_finanzas_planificacion.py          ← lee Excel local (9 hojas)
extract_finanzas_control_gestion.py        ← lee Sheet Drive PPTO+FCST
views/_fin_auth.py                         ← SSO Odoo cookie 8h
views/_fin_data.py                         ← helpers cacheados
views/fin_foto_mes.py                      ← Vista 1: cierre + V/H
views/fin_control_gestion.py               ← Vista 2a: PPTO vs FCST Sheet (PRINCIPAL)
views/fin_pyl_cc.py                        ← Vista 2b: P&L por CC del Excel local
views/fin_pyl_linea_negocio.py             ← Vista 3: parcial, espera distribución
views/fin_caja_deuda_kt.py                 ← Vista 4: caja + KT + deuda + ratios
views/fin_forecast_cierre.py               ← Vista 5: cierre proyectado año
.github/workflows/sync_finanzas.yml        ← cron cada 6h (Excel + Sheet Drive)
data/finanzas/                             ← parquets generados
```

✅ **Datos reales corriendo:**
- Excel `Planificación Financiera 2026.xlsx` → 9 parquets:
  - `pyl_mensual` (6,126 filas 2019-2026)
  - `ppto_2026` (3,030 filas)
  - `resumen_ytd`, `kt`, `deuda`, `metas_2026`, `fcst_eerr`, `dashboard_data`, `analisis_financiero`
- Sheet Drive "P&L 2025-2026":
  - 4,891 filas | 2 LN | 20 canales | 12 áreas | 33 CCs
  - PPTO/FCST × VENTA/COSTO/GASTO/CONTRIB

⏳ **Pendientes cuando retome:**
1. Deploy en Streamlit Cloud → `unionx-finanzas.streamlit.app`
2. Validar números de las 5 vistas en producción
3. Cruzar REAL del Excel con PPTO+FCST del Sheet → vista 3 columnas
4. Conectar archivo de distribución por canal → completar Vista 3 P&L Línea Negocio
5. Sumar al snapshot el campo "cobertura volumen" del Sheet
6. (Si necesario) ajustar layout/filtros tras feedback de Andrés

🔑 **Secret generado para deploy:**
`FIN_COOKIE_SECRET = "fCRxsWIND8bHF58SpOA7cU95jIlMyQjujIx1YLasB67AmtVw-d2ZXmYadi5qUAiS"`

🔑 **Sheet Drive integrado:** `1NfIL-k00pUbF5ogsVnadP2wMAVc7oUKkOA7UMLOT-j0`
Compartido con `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com`

---

## MENSAJE COMPLETO PARA RETOMAR

> Cuando Andrés diga "retomemos finanzas", responder con todo lo que sigue:

---

### 💰 Lo que armé

```
dashboard_finanzas.py              ← entry point sidebar verde
extract_finanzas_planificacion.py  ← lee Excel local (9 hojas → 9 parquets)
extract_finanzas_control_gestion.py← lee Sheet Drive (PPTO+FCST 4,891 filas)
views/_fin_auth.py                 ← SSO Odoo cookie 8h
views/_fin_data.py                 ← helpers cacheados
views/fin_foto_mes.py              ← Vista 1: cierre + V/H
views/fin_control_gestion.py       ← Vista 2: PPTO vs FCST Sheet (PRINCIPAL)
views/fin_pyl_cc.py                ← Vista P&L CC del Excel local
views/fin_pyl_linea_negocio.py     ← Vista 3 parcial
views/fin_caja_deuda_kt.py         ← Caja + KT + deuda + ratios
views/fin_forecast_cierre.py       ← Cierre proyectado año
.github/workflows/sync_finanzas.yml← cron cada 6h
```

### 🎛️ Navegación (sidebar verde)

```
🎯 Resumen
  └ 📸 Foto del mes (V/H)

💵 Control de Gestión
  ├ PPTO vs FCST (Sheet Drive)     ← PRINCIPAL
  ├ P&L por CC (archivo local)
  └ P&L por Línea de Negocio       ← parcial

💧 Caja & Balance
  └ Caja, Deuda & KT

🎯 Forecast
  └ Cierre proyectado año
```

### 📋 Datos reales

**Excel `Planificación Financiera 2026.xlsx`** → 9 parquets en `data/finanzas/`:
- `pyl_mensual` (6,126 filas 2019-2026 mensual)
- `ppto_2026`, `resumen_ytd`, `kt`, `deuda`, `metas_2026`, `fcst_eerr`, `dashboard_data`, `analisis_financiero`

**Sheet Drive "P&L 2025-2026"** (`1NfIL-k00pUbF5ogsVnadP2wMAVc7oUKkOA7UMLOT-j0`):
- 4,891 filas · 2 LN (UNIONX, GRUPO ETER) · 20 canales · 12 áreas · 33 CCs
- 9 dimensiones × 8 escenarios×KPI (PPTO/FCST × VENTA/COSTO/GASTO/CONTRIB)

### 🚀 Para deployar en Streamlit Cloud

**Create app**:
- Repo: `Andyunionx/unionx-dashboard` · branch `main` · file `dashboard_finanzas.py`
- URL sugerida: `unionx-finanzas`
- Secrets:
```toml
FIN_ALLOWED_EMAILS = "andres@grupoeter.cl,andres@unionx.cl,facturacion@melollevo.cl,contabilidad@grupoeter.cl"
FIN_COOKIE_SECRET = "fCRxsWIND8bHF58SpOA7cU95jIlMyQjujIx1YLasB67AmtVw-d2ZXmYadi5qUAiS"
ODOO_URL = "https://unionxb2b.odoo.com"
ODOO_DB = "bmya-innovatek-sh-prd-6981800"
OPS_ODOO_USER = "<el mismo de Ops>"
OPS_ODOO_PASSWORD = "<el mismo de Ops>"

# Para que la vista Control de Gestión sincronice el Sheet:
[gcp_service_account]
# pegar el JSON completo de credentials.json
```

### 🟡 Pendientes

1. Deploy en Streamlit Cloud → `unionx-finanzas.streamlit.app`
2. Validar números de las 5 vistas
3. **Cruzar REAL Excel × PPTO+FCST Sheet** → vista 3 columnas Real vs PPTO vs FCST
4. **Conectar distribución por canal** → completar Vista P&L Línea Negocio
5. Ajustes de layout/filtros si surgen tras validación
