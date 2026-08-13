---
name: cotizacion-aereo
description: "Cotización de importaciones por AVIÓN (carga aérea). TRIGGERS: 'Cotizar aéreo', 'Cotización aérea', 'Costear por aire', 'Cuánto sale traer por avión'. A partir de una lista de productos (costo unitario, uds/caja, CBM/caja, GW/caja) y las cantidades a traer, calcula el peso cobrable (MAX de peso real vs volumétrico), el flete aéreo y el costo internado por producto. Entrega una herramienta Excel de 5 pestañas con costeo, optimización single-product, optimización de mix y comparativo vs costo Odoo."
---

# Cotización Aérea — Costeo de importaciones por avión

Skill para cotizar cuánto cuesta traer productos por **avión** (no marítimo).
Motor + herramienta: `cotizar_aereo.py` (raíz del repo).

## Trigger de Activación
- "Cotizar aéreo" / "Cotización aérea"
- "Costear por aire" / "Cuánto sale traer por avión"
- "PV vs GW" / "Peso cobrable aéreo"

## Qué necesita el usuario aportar
1. **Productos** con estos 4 datos por producto (de PI/PL en el correo):
   costo unitario USD (FOB), unidades por caja master (Q'ty/CTN), CBM/CTN, GW kg/CTN.
2. **Cantidades** a traer de cada producto.
3. **Tarifa aérea USD/kg** — la entrega el usuario (varía por ruta/temporada).
4. **Internación Chile** — default **USD 1.500** (ver abajo). Editable / modo desglose.
5. **Costo actual Odoo** (`product.product.standard_price` por `default_code`) para el comparativo.

> Fuente de los 4 datos: `Cash state <fecha>.xls` (OHNSO SZ/NB, trae todo junto) o los
> pares PI+PL (`agente-comex/data/inbox/`, `data/comex/embarques/`). PI = precio; PL = uds/ctn, CBM/ctn, GW/ctn.

---

## FÓRMULAS

### 1. Peso cobrable (la clave del aéreo)
```
Factor aéreo IATA = 167 kg/m³   (6.000 cm³/kg)
PV (peso volumétrico) = CBM_total × 167
Peso cobrable         = MAX( GW_total , PV )
```
- **PV > GW** → manda el **volumen** (liviano/voluminoso: secadores, audífonos).
- **GW > PV** → manda el **peso** (denso: proyectores, monitores, teclados).

### 2. Flete aéreo
```
flete_total = peso_cobrable_envio × tarifa_usd_kg      (peso_cobrable_envio = MAX(ΣPV, ΣGW))
# prorrateo entre productos por su peso cobrable individual max(pv_i, gw_i)
```

### 3. Internación Chile
Default: **USD 1.500 fijo**. En envío aéreo chico domina lo FIJO:

| Componente | Comportamiento |
|---|---|
| Desconsolidación (~$135.000 + IVA) | Fijo por guía (AWB). IVA recuperable → costo real ≈ $135.000 |
| Honorarios agente aduana | 0,45–1% del CIF con **mínimo** (~$80–120k); en envíos chicos manda el mínimo |
| Terrestre aeropuerto→bodega | Fijo (~$100k) |
| Derecho ad valorem (6%) | **≈ 0%** por el **TLC Chile-China** (electrónica/secadores/aspiradoras liberados) |
| IVA 19% | **Recuperable → NO es costo real**, no entra al costo |
| Almacenaje aeroportuario | Por kg/día; bajo si se retira rápido |

Modo desglose: `internacion = FIJO_base + ad_valorem%×CIF + almacenaje$/kg×peso`.
Prorrateo de internación entre productos: **por CIF** (los derechos/honorarios son ad-valorem).

### 4. Costo internado por producto
```
internado_unit = (fob + flete + intern) / cantidad    (USD; ×TC para CLP)
```

---

## HERRAMIENTA (5 pestañas — `escribir_herramienta`, todo fórmulas vivas)
```
python cotizar_aereo.py     # genera C:\Users\andre\Downloads\Cotizacion_Aereo.xlsx
```
1. **Resumen** — variables editables (amarillas: tarifa, TC, modo/partidas internación) + resultados globales.
2. **Costeo** — por producto: PV vs GW, flete, internación prorrateada, internado unit + **costo Odoo** + gap %.
3. **Optimizacion** — selector de producto + curva `internado_unit(N)` con gráfico + **break-even N\* vs Odoo** (single-product).
4. **Comparativo** — aéreo vs Odoo por producto: gap, break-even, veredicto.
5. **Mix** — qué productos consolidar (premium estructural) + curva de consolidación.

`productos` necesita: nombre, model, sku, costo_unit_usd, uds_ctn, cbm_ctn, gw_ctn, cantidad, odoo_cost_clp.

---

## MODELO DE OPTIMIZACIÓN

### Single-product (pestaña Optimizacion)
Costo internado unitario es **hipérbola decreciente SIN óptimo interior**:
```
internado_unit(N) = costo_unit + flete_unit + internación_fija / N
```
- **Flete aéreo = lineal por unidad** (no hay economía de escala en el flete).
- Lo único que baja con volumen es la **internación fija amortizada** (÷N).
- Piso = **asíntota = costo_unit + flete_unit** (no se baja por volumen).
- **Break-even vs Odoo:** `N* = internación / (costo_Odoo − costo_unit − flete_unit)`
  (si `costo_Odoo ≤ asíntota` → "no alcanza": aire siempre > Odoo).

### MIX de productos (pestaña Mix)
La internación fija es **un ticket único por envío**. Una vez justificado el avión con el
producto **ancla** (mayor costo de oportunidad de quiebre), **sumar cualquier producto cuesta
solo FOB + flete** — el fijo ya está pagado. Por eso el criterio de mix NO es el internado con
los 1.500 completos, sino el **premium estructural** = `asíntota (costo_unit+flete_unit) vs Odoo`,
independiente del volumen y del fijo:
- premium ≤ 0 o < 15% → **fly** (proyectores de alto valor y densos).
- 15–40% → **evaluar**.
- ≥ 40% → **marítimo** (baratos/voluminosos: mousepad, secador, audífono).

La consolidación (llenar el envío) baja la internación/u (curva en pestaña Mix), pero **NO baja el
premium de flete** — ese es estructural. Regla: **justifica el avión con el ancla, llena con los de premium bajo.**

---

## DECISIÓN AÉREO vs MARÍTIMO vs QUIEBRE
El aéreo se justifica cuando el **costo de oportunidad del quiebre** supera el sobrecosto del flete.
Si el usuario entrega `costo_oportunidad_clp`, comparar contra el premium aéreo por producto.

## NOTAS / SUPUESTOS
- Factor **167 kg/m³** (IATA). Si el forwarder usa otro (166/200 express), pasarlo en `cotizar(..., factor=...)`.
- Los 4 datos salen de **PI (precio) + PL (uds/ctn, CBM/ctn, GW/ctn)**. Si un producto no está en ningún PI/PL, pedir a Steven.
- IVA **no** entra al costo (recuperable). Ad valorem **0%** por defecto (TLC China).
- Odoo std_price vía xmlrpc (env `ANDRES_ODOO_PASSWORD`).
- ⚠️ El repo vive dentro de Google Drive → archivos nuevos sin commit se pueden perder por clobber de sync.
  Tras crear/editar, **commitear pronto** (ver memoria `sync_local_clobber`).
- Español chileno. Confirmar con Andrés antes de cargar en Odoo o enviar correos.
