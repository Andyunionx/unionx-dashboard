# 🏢 Roadmap GAV directo por canal/categoría — May 2026

> **Para Andrés y futuros lectores.** Este documento describe cómo evolucionar
> la distribución del GAV (Gastos de Administración y Ventas) desde el método
> heurístico actual (`% venta`) a un método mixto basado en literatura de
> **Cost Accounting** (Horngren, Datar & Rajan, 15ª ed.).

---

## 🎯 Por qué cambiar lo que tenemos

**Hoy** el GAV se reparte por defecto al `% venta` de cada canal, con una
excepción `equitativo` para Grupo Eter y Legales. Eso tiene 3 problemas:

1. **Penaliza al canal de alto volumen-bajo margen** (ej: Mercado Libre con
   descuentos altos recibe demasiado overhead administrativo que no causa).
   El IMA Statement 4B advierte explícitamente contra esto: "no asignar costos
   por *ability to bear* (capacidad de pagar)".
2. **Ignora la causalidad directa**: el sueldo de un KAM que atiende solo
   Marketplace se reparte hoy a todos los canales por venta, cuando debería
   ir 100% a Marketplace.
3. **No distingue gastos por línea de producto**: el comprador de la categoría
   Pets se reparte a Tecno, Beauty, etc., cuando solo debería ir a Pets.

## 📚 Marco teórico aplicable

Horngren/Datar/Rajan distingue 4 métodos de asignación a un cost object:

| Método | Cuándo aplica | Precisión |
|---|---|---|
| **Direct Tracing** | Causalidad directa y visible | Máxima |
| **Cause-and-Effect (ABC)** | Hay cost driver identificable | Alta |
| **Benefits-Received** | Sin driver claro, usar MC absoluto (no venta) | Media |
| **Fairness / Equity** | Holding corporativo, último recurso | Baja |

**Referencias citables**:
- Horngren, Datar & Rajan (2015). *Cost Accounting: A Managerial Emphasis*,
  15th ed., Pearson — Cap. 14 *Cost Allocation*.
- IMA Statement on Management Accounting 4B — *Allocation of Service and
  Administrative Costs*.
- Kaplan & Anderson (2007). *Time-Driven Activity-Based Costing*. HBP.

## 🧭 Decisiones tomadas (cerradas con Andrés)

1. **Cost object para distribuir el GAV** = `tipo_negocio` (6 valores oficiales
   del Sheet KAM): `Marketplace`, `Fidelización`, `Páginas Propias`,
   `Tiendas Propias`, `Corporativo`, `Distribución`. **NO** a las 90 cuentas
   individuales (eso es cliente, no canal estratégico).
2. **Eje de producto** = `categoria_macro` (17 valores limpios de Odoo: Pets,
   Home, Tecno, Sport, Beauty, Fashion, etc.). `categoria_padre` (61) queda
   para v2 si necesitamos más detalle.
3. **Marca** = omitida en esta iteración. No existe catálogo de marcas en
   ningún parquet. Si más adelante se carga un catálogo SKU→marca, agregamos
   un modo `directo_marca`.
4. **Cargos mixtos** (ej: Gerente comercial que cubre 6 tipo_negocio) =
   split manual con porcentajes que sumen 100% (cuando el responsable puede
   estimar dedicación). Fallback: `mc_absoluto`.
5. **Driver `mc_absoluto`** se calcula del Sheet KAM (tiene MC por tipo_negocio
   ya calculado, con gap del 12% asumido como ruido aceptable para ranking
   relativo).

## 🧱 Modos de asignación soportados

| Modo (col `metodo_asignacion`) | Descripción | Categoría doctrinal |
|---|---|---|
| `directo_canal` | 100% a uno o más `tipo_negocio` (col `destino_tipo_negocio` con porcentajes opcionales en `pct_asignacion`) | Direct Tracing (cat 1: KAMs, Ger. Comercial) |
| `directo_categoria` | 100% a una `categoria_macro` (col `destino_categoria_macro`). Dentro de la categoría se subdistribuye a `tipo_negocio` por venta de la categoría en cada uno | Direct Tracing por LN/categoría (cat 3: Planner, Comprador, Marketing producto) |
| `mc_absoluto` | Reparto por MC absoluto del `tipo_negocio` (Benefits-Received correcto según IMA) | Cause-and-Effect proxy (cat 2 transversales) |
| `equitativo` | Reparto igual entre los 6 `tipo_negocio` | Fairness (cat 2 paraguas puro: CEO, Chairman, Grupo Eter, Legales) |
| `venta` | LEGACY: reparto por % venta. Se mantiene como fallback para que la app no se rompa cuando una fila del Sheet aún no tiene `metodo_asignacion` | — |

### Cascada para `directo_categoria`

```
$100 MM de "Comprador Pets"
  → 100% a categoría_macro = Pets
    → split entre tipo_negocio según venta de Pets x tipo_negocio:
       Marketplace: 60% → $60 MM
       Tiendas Propias: 25% → $25 MM
       Fidelización: 15% → $15 MM
```

## 📋 Fases del proyecto

### Fase 0 — Modificar Sheet P&L Drive (DATA, Andrés + contabilidad)

**Output**: Sheet `1NfIL-k00pUbF5ogsVnadP2wMAVc7oUKkOA7UMLOT-j0` con
columnas nuevas.

**Columnas a agregar** (todas opcionales — si vacías, fallback a `venta`):

| Columna | Tipo | Valores | Ejemplo |
|---|---|---|---|
| `METODO ASIGNACION` | enum | `directo_canal`, `directo_categoria`, `mc_absoluto`, `equitativo`, `venta` | `directo_canal` |
| `DESTINO TIPO NEGOCIO` | string | Uno o más `tipo_negocio` separados por `;`. Si vacío y método=`directo_canal`, error. | `Marketplace;Fidelización` |
| `DESTINO CATEGORIA` | string | Una `categoria_macro`. Si vacío y método=`directo_categoria`, error. | `Pets` |
| `PCT ASIGNACION` | string JSON | Para split: `{"Marketplace": 60, "Fidelización": 40}`. Si vacío, distribución uniforme entre los destinos. | `{"Marketplace": 80, "Fidelización": 20}` |
| `DESCRIPCION CARGO` | texto libre | Para que cualquiera entienda qué es este cargo | "KAM Felipe — Recíbelo" |

**Plan de llenado sugerido** (alto impacto primero):

1. **COMERCIAL** (197.8 MM YTD, 55% del GAV): cada KAM con su(s) tipo_negocio + Ger. Comercial con split estimado.
2. **GRUPO ETER** (86 MM, 24%): `equitativo`. CEO, Chairman, Directorio, etc.
3. **FINANZAS Y ADMINISTRACIÓN** (71.8 MM, 20%): `mc_absoluto`.
4. **UNIONX** (2.6 MM, 1%): probable `directo_categoria` o `mc_absoluto` según naturaleza.
5. **LEGALES** (0.8 MM): `equitativo`.
6. **MARKETING** (0.2 MM): revisar — está muy chico, probable mal cargado.

### Fase 1 — Extractor lee cols nuevas (CÓDIGO, ~1-2h)

**Archivo**: `extract_finanzas_control_gestion.py`

- Agregar las 5 columnas nuevas al rename map (tolerancia a Ñ, espacios,
  encoding).
- Pasar valores raw al parquet (sin transformar) en cols nuevas.
- Validaciones soft (logs warning, no crashes):
  - `metodo_asignacion=directo_canal` sin `destino_tipo_negocio` → warn
  - `metodo_asignacion=directo_categoria` sin `destino_categoria_macro` → warn
  - `pct_asignacion` mal formado JSON → warn
  - `tipo_negocio` destino que no esté en lista oficial → warn
- Backward compatible: si ninguna col nueva existe, el parquet sale igual
  que antes.

### Fase 2 — Lógica multi-modo (CÓDIGO, ~3-4h)

**Archivo**: `views/_fin_distribucion.py`

Agregar:

1. **`cargar_mc_absoluto_por_tipo_negocio(year, meses)`**: lee `contribucion_kam.parquet`
   y devuelve `{tipo_negocio: mc_absoluto}` para usar como peso.

2. **`cargar_venta_por_categoria_tipo_negocio(year, meses)`**: lee
   `ventas_historico.parquet` + `ventas_mes_actual.parquet` y devuelve
   `{(categoria_macro, tipo_negocio): venta}` para la cascada.

3. **`distribuir_gav_multi_modo(df_gav, df_kam, df_ventas_cat)`**: para cada
   fila del GAV con `metodo_asignacion` definido, aplica el modo
   correspondiente. Si está vacío → fallback `venta`.

   Output: DataFrame largo `[fila_gav_idx, area, sub_area, descripcion_cargo,
   metodo, destino, tipo_negocio, monto_asignado]`.

4. **Función helper `_split_pct(json_str, destinos_default)`**: parsea el
   JSON de porcentajes, valida que sumen 100, retorna dict.

### Fase 3 — UI Drivers extendida (CÓDIGO, ~2h)

**Archivo**: `views/fin_pyl_linea_negocio.py` (tab Drivers)

- Sección nueva debajo del editor de drivers de Costo OP:
  **"🏢 GAV — Asignación por área/sub-área"**
- Tabla **read-only** (no editable en app, la fuente de verdad es el Sheet):
  - Cols: `area`, `sub_area`, `descripcion_cargo`, `monto MM`, `método`, `destino`
  - Coloreado por método: 🎯 directo_canal, 🏷️ directo_categoria,
    📊 mc_absoluto, ⚖️ equitativo, 💰 venta
- Indicador de completitud: "X% del GAV tiene método definido, Y% en fallback venta"
- Botón para descargar el mapping como CSV (auditoría)
- Banner explicativo + link al doc del roadmap

### Fase 4 — Validación + deploy + doc (~1h)

- Smoke test: comparar EBIT por canal (`tipo_negocio`) antes vs después.
  Documentar deltas en un comentario del PR.
- Banner top del tab P&L: "GAV distribuido con método mixto. Ver tab Drivers."
- Actualizar `docs/FINANZAS_ESTADO_2026-05.md` con la nueva lógica.

## 🚦 Estado de implementación

| Fase | Estado | Notas |
|---|---|---|
| 0 — Sheet Drive | ⏳ Pendiente Andrés | Bloqueante para deploy real, pero el código de fases 1-4 funciona sin esto (fallback a `venta`) |
| 1 — Extractor | ✅ Implementado | Backward compatible |
| 2 — Lógica | ✅ Implementado | Driver `mc_absoluto` + función `distribuir_gav_multi_modo` |
| 3 — UI Drivers | ✅ Implementado | Sección read-only en tab Drivers |
| 4 — Validación | ⏳ Pendiente Andrés | Se valida cuando se llene el Sheet |

## 🧪 Cómo probar antes de llenar el Sheet

```bash
# 1. Smoke test desde repo root
python -c "
from views._fin_distribucion import (
    cargar_gav_corporativo,
    cargar_mc_absoluto_por_tipo_negocio,
)
gav = cargar_gav_corporativo(2026, list(range(1,5)))
mc  = cargar_mc_absoluto_por_tipo_negocio(2026, list(range(1,5)))
print('GAV total:', gav['monto'].sum() / 1e6, 'MM')
print('MC por tipo_negocio:', mc)
"
```

## ❓ Preguntas abiertas (no críticas para deploy)

1. **¿Cuándo el Sheet tenga `directo_categoria` pero esa categoría no se
   vendió en ningún tipo_negocio?** Hoy: fallback a `equitativo`. ¿Está OK?
2. **¿Qué pasa con cargos compartidos?** Ej: Ger. Comercial supervisa 6
   tipo_negocio. Hoy: split manual con `pct_asignacion`. ¿Si Andrés no
   estima %, fallback a `mc_absoluto`?
3. **`mc_absoluto` con MC negativo**: si un tipo_negocio tiene MC<0 ¿lo
   excluimos del reparto o le asignamos 0%? Hoy: lo excluimos del peso.

## 🔗 Referencias

- Doc estado app Finanzas: `docs/FINANZAS_ESTADO_2026-05.md`
- Sheet P&L Drive: https://docs.google.com/spreadsheets/d/1NfIL-k00pUbF5ogsVnadP2wMAVc7oUKkOA7UMLOT-j0
- Sheet KAM (MC absoluto por tipo_negocio): https://docs.google.com/spreadsheets/d/1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4

---

_Documento generado: 2026-05-22 · Roadmap consensuado con Andrés._
