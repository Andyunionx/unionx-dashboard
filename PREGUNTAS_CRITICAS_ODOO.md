# ❓ PREGUNTAS CRÍTICAS: Confirmar Estructura Odoo

## Context
Necesito extraer los datos de venta desde Odoo en el mismo formato que `Raw ventas Y.xlsx`. He mapeado las 40 columnas, pero hay campos que NO existen en Odoo estándar - son **custom fields** que alguien agregó.

---

## 🔴 BLOQUEADORES - SIN ESTOS NO PUEDO CONTINUAR

### Pregunta 1: **¿DÓNDE ESTÁ EL CAMPO "CANAL"?**

En Raw ventas Y.xlsx veo valores como:
- "You Market"
- "Mercado Libre" 
- "Falabella"
- "Kitchen Center"

**¿De dónde vienen en Odoo?**
- [ ] ¿Es un campo en `sale.order`?
- [ ] ¿Es un custom field `x_studio_canal`?
- [ ] ¿Viene del `res.partner` (cliente)?
- [ ] ¿De dónde exacto?

**Necesito el nombre exacto del campo en Odoo:**
```
Canal = sale.order._______ (llena el espacio)
```

---

### Pregunta 2: **¿DÓNDE ESTÁ EL CAMPO "TIPO NEGOCIO"?**

En Raw ventas Y.xlsx veo valores como:
- "Fidelización"
- "Marketplace"
- "Distribución"
- "Páginas propias"

**¿De dónde vienen en Odoo?**
- [ ] ¿Es un campo en `sale.order`?
- [ ] ¿Es un custom field?
- [ ] ¿Cómo se llama exactamente?

**Necesito:**
```
Tipo Negocio = sale.order._______ (llena el espacio)
```

---

### Pregunta 3: **¿DÓNDE ESTÁ EL CAMPO "KAM"?**

En Raw ventas Y.xlsx veo nombres como:
- "Trini"
- "Clau"
- "Felipe"
- "Vicente"

**¿De dónde vienen en Odoo?**
- [ ] ¿Es `sale.order.salesman_id.name` (el vendedor)?
- [ ] ¿Es un custom field separado?
- [ ] ¿Cómo se llama exactamente?

**Necesito:**
```
KAM = sale.order._______ (llena el espacio)
```

---

## 🟡 IMPORTANTES - AFECTAN EXACTITUD

### Pregunta 4: **¿EXISTEN "COMISIÓN %", "LOGÍSTICA" Y "MARKETING"?**

En Raw ventas Y.xlsx veo:
- Comisión %: En su mayoría vacío (NaN)
- Logística: Valores como 0.0, a veces vacío
- Marketing: Casi siempre vacío (NaN)

**¿Existen en Odoo o se calculan afuera?**
- [ ] ¿Dónde está cada uno?
- [ ] ¿Cómo se asignan?
- [ ] ¿Por orden, por línea, global?

**Necesito:**
```
Comisión % = ________________
Logística = ________________
Marketing = ________________
```

---

### Pregunta 5: **¿EXISTEN LOS CUSTOM FIELDS DE PRODUCTO?**

En Raw ventas Y.xlsx veo:
- Categoría comercial: "Diamante", "Oro", etc.
- Tipo Marca: "Propia", "Compra", etc.
- Tipo Compra: "Importación", "Local"
- Pack: "Si", "No"

**¿Existen en `product.product` como custom fields?**
- [ ] ¿Sí o no?
- [ ] ¿Cómo se llaman exactamente?

**Necesito:**
```
Categoría comercial = product.product._______
Tipo Marca = product.product._______
Tipo Compra = product.product._______
Pack = product.product._______
```

---

## 🟢 INFORMACIÓN - Nice to Have

### Pregunta 6: **¿EXISTE "TIPO DESPACHO"?**
En Raw tengo 16,648 filas de febrero, pero "Tipo Despacho" está vacío en todas.
- ¿Existe en Odoo?
- ¿O se puede omitir por ahora?

### Pregunta 7: **¿CÓMO ACCEDER A LOS CUSTOM FIELDS?**
Si existen custom fields (como `x_studio_canal`), ¿cómo se llaman exactamente en Odoo?
- ¿Con prefijo `x_studio_`? 
- ¿Con prefijo `x_`?
- ¿Con otro nombre?

---

## 📋 RESPUESTA IDEAL

Por favor, completa esto:

```
ESTRUCTURA ODOO PARA CANAL/NEGOCIO/KAM:
═══════════════════════════════════════

Canal:
  - Modelo: sale.order
  - Campo: x_studio_canal (o ¿cuál?)
  - Ejemplos de valores: You Market, Mercado Libre, Falabella, Kitchen Center

Tipo Negocio:
  - Modelo: sale.order
  - Campo: x_studio_tipo_negocio (o ¿cuál?)
  - Ejemplos: Fidelización, Marketplace, Distribución

KAM:
  - Modelo: sale.order
  - Campo: salesman_id.name (o ¿cuál?)
  - Ejemplos: Trini, Clau, Felipe


ESTRUCTURA ODOO PARA COMISIONES/LOGÍSTICA/MARKETING:
══════════════════════════════════════════════════════

Comisión %:
  - ¿Existe? Sí / No
  - Ubicación: ________________
  - Cómo se asigna: ________________

Logística:
  - ¿Existe? Sí / No
  - Ubicación: ________________
  - Cómo se asigna: ________________

Marketing:
  - ¿Existe? Sí / No
  - Ubicación: ________________
  - Cómo se asigna: ________________


CUSTOM FIELDS EN PRODUCTO:
═══════════════════════════

Categoría comercial: ¿x_studio_categoria_comercial u otro?
Tipo Marca: ¿x_studio_tipo_marca u otro?
Tipo Compra: ¿x_studio_tipo_compra u otro?
Pack: ¿x_studio_pack u otro?
```

---

## PLAN DE ACCIÓN

**UNA VEZ QUE CONFIRMES ARRIBA:**

1. ✅ Crearé script Python que conecta a Odoo
2. ✅ Extraeré `sale.order.line` de febrero 2026
3. ✅ Enriqueceré con todos los custom fields
4. ✅ Generaré RAW con 40 columnas exacto
5. ✅ Validaré contra Raw ventas Y.xlsx
6. ✅ Inyectaré en Análisis Resultado

**Tiempo estimado una vez que confirmes:** 30 minutos

---

**Generado:** 2026-04-02
**Estado:** Bloqueado esperando confirmación de custom fields
