# Cómo agregar un cliente nuevo al agente de cobranza

> Guía para Víctor / Martín. **No requiere tocar código Python.**

## TL;DR

1. Copiar `agente-cobranza/clientes/_template.yaml` a `agente-cobranza/clientes/<slug>.yaml`
2. Completar 4 campos: `nombre`, `slug`, `partners`, `excel.drive_path`
3. Compartir el Excel en Drive con el service account
4. Abrir PR a `feat/agente-cobranza` (durante la migración) o a `main` (después del merge inicial)
5. Andrés revisa y mergea
6. El cron del día siguiente ya procesa el cliente

---

## Paso a paso

### 1. Conseguir los `partner_id` en Odoo

Entrar a Odoo → módulo **Contactos** → buscar el cliente → abrir su ficha.
El número de URL al final es el `partner_id`. Ej:

```
https://unionxb2b.odoo.com/web#id=25&model=res.partner
                                ^^
                                partner_id = 25
```

Si el cliente tiene **varios partners** en Odoo (uno para boletas, otro
para facturas — típico de marketplaces), anotá todos.

### 2. Conseguir la ruta del Excel en Drive

Entrar a Drive → navegar hasta el archivo Excel del cliente. La ruta
desde "Mi unidad/" la armás juntando los nombres de carpeta:

```
Mi unidad/
  POST_CONTABILIDAD 2024/
    2026/
      Trabajado clientes/
        WALMART/
          Walmart 2026.xlsx        ← tu archivo
```

Path final: `POST_CONTABILIDAD 2024/2026/Trabajado clientes/WALMART/Walmart 2026.xlsx`

### 3. Identificar qué hojas no se pueden tocar

Abrir el Excel y listar las hojas que tienen:
- Tablas dinámicas
- Fórmulas complejas (más allá de XLOOKUP simple)
- Data manual escrita a mano

Esas hojas van en `excel.hojas_preservar`. El agente las dejará intactas.

### 4. Compartir el Excel con el service account

> ⚠️ **Sin este paso el agente no puede leer ni escribir el archivo.**

1. En Drive, click derecho sobre el Excel → **Compartir**
2. Pegar el email: `union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com`
3. Cambiar permiso a **Editor**
4. Desmarcar "Notificar" (es un bot, no hace falta)
5. Click **Enviar**

### 5. Crear el YAML del cliente

Copiar el template:

```bash
cp agente-cobranza/clientes/_template.yaml agente-cobranza/clientes/walmart.yaml
```

Editar:

```yaml
nombre: "Walmart"
slug: walmart

partners:
  todos:    [25]
  boletas:  [25]
  facturas: [25]
  rut: "12345678-9"

excel:
  drive_path: "POST_CONTABILIDAD 2024/2026/Trabajado clientes/WALMART/Walmart 2026.xlsx"
  output_suffix: "_ACTUALIZADO"
  hojas_preservar:
    - "PAGOS"
    - "POR PAGAR"

xlookup_setup: []   # vacío si no necesita cruces especiales
```

### 6. (Opcional) Probar localmente en dry-run

Si tenés Python instalado y las creds:

```bash
cd unionx-dashboard/
pip install -r agente-cobranza/requirements.txt
export ODOO_PASSWORD="..."
python agente-cobranza/actualizar_cliente.py --config agente-cobranza/clientes/walmart.yaml --dry-run
```

El `--dry-run` descarga de Odoo y genera el Excel local en `tmp/walmart/`
sin tocar Drive.

### 7. Abrir PR

```bash
git checkout -b feat/cliente-walmart
git add agente-cobranza/clientes/walmart.yaml
git commit -m "agente-cobranza: agregar cliente Walmart"
git push -u origin feat/cliente-walmart
```

Después en GitHub: **Open pull request**. Asignáselo a Andrés.

---

## Casos especiales

### Cliente con multiple partner_id (ej: MELI)

MELI tiene partners separados para boletas vs facturas:

```yaml
partners:
  todos:    [16, 1586, 90747, 19583]   # los 4
  boletas:  [16]                        # solo el que emite boletas
  facturas: [1586, 90747]               # los que reciben facturas
```

### Cliente que necesita XLOOKUP custom (ej: Falabella, Shopify)

Falabella cruza la col `I` de BOL contra la col `D` de yuju, y trae la col `G`:

```yaml
xlookup_setup:
  - hoja: "BOL PENDIENTE DE PAGO"
    columna: J
    formula: '=XLOOKUP(I{fila},yuju!D:D,yuju!G:G,0,0)'
```

El `{fila}` se reemplaza automáticamente por el número de fila al aplicar
la fórmula.

### Cliente con ventanas distintas (ej: traer 1 año de pagadas)

```yaml
ventanas_dias:
  pagadas: -365        # 1 año en vez de 300 días
  yuju:    -200        # default
```

---

## Qué pasa después del PR

1. **Yo (Andrés)** o **Claude** revisamos el YAML.
2. Validamos:
   - `partner_id` correctos (no apuntar al partner equivocado)
   - `drive_path` existe y está compartido con el service account
   - `hojas_preservar` matchean las hojas reales del Excel
3. Si todo OK → merge a `main`
4. Cron diario 07:00 Chile lo procesa
5. El archivo `<nombre>_ACTUALIZADO.xlsx` aparece en la misma carpeta del Excel original

## Cómo verificar que un cliente está corriendo bien

GitHub → repo `unionx-dashboard` → tab **Actions** → workflow
**Agente Cobranza Diario** → último run → expandir el step del cliente.

Verás algo así:

```
✓ Cliente Walmart                BOL:   42  NC:   3  PAG:  186  yuju:   75
```

Si el cliente falla, el step aparece con ✗ y el error sale en el log.

---

## Dudas

Cualquier duda al canal #cobranza-automation o pingueá a Andrés.
