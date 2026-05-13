# 📚 App Contabilidad — Stand By (paso a paso para retomar)

> **Cuando Andrés diga "retomemos contabilidad", leer este archivo y mandar
> exactamente el contenido de la sección "MENSAJE COMPLETO PARA RETOMAR"
> al final.**

**Fecha de pausa:** 2026-05-12
**Commit en main con todo el código:** `895427d`

---

## Estado actual (snapshot)

✅ **Lo que está hecho y pusheado:**

```
extract_contabilidad_cobranza.py   → lee Odoo, ya corrió OK con datos reales
extract_contabilidad_cc.py         → procesa libro+memoria+cartolas (espera uploads)
dashboard_contabilidad.py          → Streamlit, sidebar marrón
views/_cont_auth.py                → SSO Odoo independiente
views/_cont_data.py                → helpers cacheados
views/cont_cobranza.py             → Vista Flujo 1
views/cont_centro_costos.py        → Vista Flujo 2
.github/workflows/sync_contabilidad.yml  → cron cada 6h
data/contabilidad/                 → outputs + carpetas para uploads
```

✅ **Datos reales primera corrida (Cobranza):**
- 9,853 documentos pendientes
- $711.8 MM CLP totales
- Boletas $510 MM, Facturas $202 MM
- +90 días vencidos: $45.8 MM
- 31-60 días: $104 MM
- 182 notas crédito, 9,500 SOs vinculados

⏳ **Pendiente cuando retome:**
1. Andrés comparte URLs de Drives de devolución y NC
2. Andrés sube primer libro compras del SII + `memoria_cuentas.xlsx`
3. Confirmar nombres reales de portales de pago (MP, Webpay, Yuju, Khipu, otros)
4. Implementar cruce automático boleta↔portal y factura↔cartola con score
5. Implementar botón "Aplicar a Odoo" con preview + confirmación
6. Configurar deploy: `unionx-contabilidad.streamlit.app`

🔑 **Secret generado para deploy:**
`CONT_COOKIE_SECRET = "X0tMywwjYtPVNaF07Yr0Wry9gVZGdP1pIDav8rG_AwyKesU35l4pkB8cx3RSWXT3"`

---

## MENSAJE COMPLETO PARA RETOMAR

> Cuando Andrés diga "retomemos contabilidad", responder con todo lo que
> sigue debajo (es exactamente el mensaje que le mandé al pausar):

---

### 📚 Lo que armé

```
extract_contabilidad_cobranza.py    ← lee Odoo, ya corrió: 9,853 docs / $711.8MM
extract_contabilidad_cc.py          ← procesa libro+memoria+cartolas (espera uploads)
dashboard_contabilidad.py           ← Streamlit, sidebar marrón
views/_cont_auth.py                 ← SSO Odoo independiente
views/_cont_data.py                 ← helpers cacheados
views/cont_cobranza.py              ← Vista Flujo 1
views/cont_centro_costos.py        ← Vista Flujo 2
.github/workflows/sync_contabilidad.yml  ← cron cada 6h
data/contabilidad/                  ← outputs + uploads
```

### 📊 Flujo 1 — Cobranza (datos reales primera corrida)

| | |
|---|---|
| **Documentos pendientes** | 9,853 |
| **Monto total CxC** | $711.8 MM CLP |
| Boletas (cruzar portales) | $510 MM |
| Facturas (cruzar cartolas) | $202 MM |
| 🔴 +90 días vencidos | $45.8 MM |
| 🟠 31-60 días | $104 MM |
| Notas crédito | 182 |
| Pedidos venta vinculados | 9,500 |

**En la vista vas a ver:** KPIs · gráfico aging · top 20 deudores · tabs Boleta/Factura/NC/SO con descarga Excel · uploaders (pagos portales para boletas, cartolas para facturas).

### 📊 Flujo 2 — Centro de Costos

Espera tus uploads:
1. **Libro de compras del SII** → `data/contabilidad/centro_costos/libros_compras/*.xlsx`
2. **`memoria_cuentas.xlsx`** → mapping RUT proveedor → cuenta contable + CC + tipo
3. **Cartolas bancarias** → `data/contabilidad/centro_costos/cartolas_bancarias/*.xlsx`

**Cuando subas:** el extractor cruza por RUT normalizado y devuelve dos listas: ✅ Listos para Odoo (con cuenta + CC) y ⏳ Pendientes (sin mapping, descargás template para completar y agregar al Excel).

### 🚀 Para deployar en Streamlit Cloud

Igual que Finanzas, **Create app**:
- Repo: `Andyunionx/unionx-dashboard` · branch `main` · file `dashboard_contabilidad.py`
- URL sugerida: `unionx-contabilidad`
- Secrets:
```toml
CONT_ALLOWED_EMAILS = "andres@grupoeter.cl,andres@unionx.cl,contabilidad@grupoeter.cl,facturacion@melollevo.cl"
CONT_COOKIE_SECRET = "X0tMywwjYtPVNaF07Yr0Wry9gVZGdP1pIDav8rG_AwyKesU35l4pkB8cx3RSWXT3"
ODOO_URL = "https://unionxb2b.odoo.com"
ODOO_DB = "bmya-innovatek-sh-prd-6981800"
OPS_ODOO_USER = "<el mismo de Ops>"
OPS_ODOO_PASSWORD = "<el mismo de Ops>"
```

### 🟡 Lo que necesito de vos para completar

| Item | Para qué |
|---|---|
| URLs de Drives de **devolución** y **NC** | Sumar al cruce automático de cobranza |
| Primer **libro compras del SII** (Excel) | Validar parser y formato real |
| Primer **`memoria_cuentas.xlsx`** | Mapping inicial RUT → cuenta contable |
| Confirmar nombres reales de **portales de pago** | Mercado Pago, Webpay, Yuju, Khipu, otros... |

Cuando tengas eso, agrego:
1. **Cruce automático** boleta↔portal y factura↔cartola con score de confianza
2. **Botón "Aplicar a Odoo"** que crea los `account.move.line` de pago con preview/confirmación
3. **Validación contra Drives NC** antes de marcar como "no cobrable"

Hard refresh en la app cuando termines el deploy 👍
