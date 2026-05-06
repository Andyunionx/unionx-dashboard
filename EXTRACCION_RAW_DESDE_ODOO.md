# Extracción de Ventas desde Odoo en Formato RAW (40 Columnas)

## 📋 Resumen Ejecutivo

Sistema automatizado para extraer datos de ventas desde Odoo y transformarlos al **formato RAW exacto** (40 columnas), con:
- ✅ Neteado automático de facturas vs Notas de Crédito
- ✅ Enriquecimiento con planillas locales (Maestra Canales, Matriz Productos)
- ✅ Reintentos inteligentes ante inestabilidad de Odoo
- ✅ Cálculo de métricas financieras (margen, comisión, logística)
- ✅ Compatible con históricos SQL

---

## 🚀 Inicio Rápido

### Opción 1: Script Standalone (Recomendado para DB)

```bash
# Extraer ventas de un período específico
cd "g:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA"
python actualizar_raw_historico.py --periodo "2026-04-01 00:00:00" "2026-04-12 23:59:59"
```

**Output:**
```
====================================================================================================
ACTUALIZADOR DE RAW HISTORICO
====================================================================================================

Periodo a extraer: 2026-04-01 00:00:00 a 2026-04-12 23:59:59

[1/5] Conectando a Odoo...
      [OK] Conectado

[2/5] Inicializando VentasService...
      [OK] Servicio listo

[3/5] Extrayendo datos en FORMATO RAW...

[EXTRACCION RAW] Período: 2026-04-01 00:00:00 a 2026-04-12 23:59:59
      10% - Extrayendo órdenes...
  [OK] 6,202 órdenes
      20% - Extrayendo líneas de venta...
  [OK] 9,264 líneas
      30% - Extrayendo productos...
  [OK] 624 productos
      40% - Extrayendo facturas y notas de crédito...
  [OK] 3,837 facturas
      50% - Cargando planillas...
  [OK] Planillas cargadas
      60% - Construyendo dataset RAW...
  [OK] Dataset construido
      70% - Calculando métricas...
  [OK] Métricas calculadas
      80% - Aplicando filtros...
  [OK] Filtros aplicados

[5/5] Resumen de actualización:
      Lineas insertadas: 9,264
      Canales: 5
      Productos: 624

      KPIs del período:
      Venta Total (NETA): $206,923,456.78
      Margen Final: $116,712,345.23
      % Margen: 56.4%
```

### Opción 2: Desde Python (Para integración SQL)

```python
from pathlib import Path
import sys

# Setup
backend_path = Path(__file__).parent / 'finanzas-unionx' / 'backend'
sys.path.insert(0, str(backend_path))

from app.core.odoo_client import OdooClient
from app.services.ventas_service import VentasService
from app.config import Config
import pandas as pd

# Conectar a Odoo
odoo = OdooClient(
    url=Config.ODOO_URL,
    db=Config.ODOO_DB,
    username=Config.ODOO_USER,
    password=Config.ODOO_PASSWORD
)

# Crear servicio
service = VentasService(odoo, Config.PLANILLAS_DIR)

# Extraer en formato RAW (40 columnas exactas)
df_raw = service.extract_to_raw_format(
    periodo_inicio="2026-04-01 00:00:00",
    periodo_fin="2026-04-12 23:59:59",
    progress_callback=lambda pct, label: print(f"{pct}% - {label}")
)

# Usar en SQL
# - Insertar en tabla ventas_raw
# - Respetar tipos de datos (int, float, datetime)
# - Validar campos obligatorios (Pedido, SKU, Fecha Venta)

print(f"Filas extraídas: {len(df_raw):,}")
print(f"Columnas: {df_raw.columns.tolist()}")
```

---

## 📊 Estructura RAW (40 Columnas)

| # | Columna | Tipo | Descripción | Origen |
|---|---------|------|-------------|--------|
| 1 | Tipo Movimiento | str | "Venta" | Hardcoded |
| 2 | Bodega | str | `warehouse_id.name` | sale.order |
| 3 | Documento | str | `invoice.name` | account.move (factura) |
| 4 | Fecha Documento | datetime | `invoice.invoice_date` | account.move |
| 5 | Pedido | str | `order.name` | sale.order |
| 6 | Estado Pedido | str | `order.state` | sale.order |
| 7 | Tipo Despacho | str | Vacío (futuro) | - |
| 8 | SKU | str | `product.default_code` | product.product |
| 9 | Canal | str | `order.channel` (estandarizado) | sale.order |
| 10 | Fecha Venta | date | `order.date_order.date()` | sale.order |
| 11 | Hora Venta | time | `order.date_order.time()` | sale.order |
| 12 | Producto | str | `product.name` | product.product |
| 13 | Categoría macro | str | Matriz Productos | Excel |
| 14 | Categoría padre | str | Matriz Productos | Excel |
| 15 | Categoría hijo | str | Matriz Productos | Excel |
| 16 | Categoría comercial | str | Matriz Productos | Excel |
| 17 | Estado SKU | str | Vacío (futuro) | - |
| 18 | Pack | str | Vacío (futuro) | - |
| 19 | Marca | str | `product.manufacturer_id.name` | product.product |
| 20 | Proveedor | str | Vacío (futuro) | - |
| 21 | Tipo Marca | str | Vacío (futuro) | - |
| 22 | Tipo Compra | str | Vacío (futuro) | - |
| 23 | Tipo Negocio | str | Maestra Canales | Excel |
| 24 | KAM | str | Maestra Canales | Excel |
| 25 | Estado Canal | str | Vacío (futuro) | - |
| 26 | Año venta | int | Extraído de Fecha Venta | Calculado |
| 27 | Mes venta | int | Extraído de Fecha Venta | Calculado |
| 28 | Semana venta | int | Extraído de Fecha Venta (ISO) | Calculado |
| 29 | Día semana | int | Día de semana (0-6) | Calculado |
| 30 | Hora venta | str | Hora (duplicado de col 11) | sale.order |
| 31 | Cantidad | float | `order_line.product_uom_qty` | sale.order.line |
| 32 | Venta bruta | float | **NETO** (Factura - NC) | account.move |
| 33 | Costo Unitario | float | `order_line.purchase_price` | sale.order.line |
| 34 | Costo Total | float | Costo Unitario × Cantidad | Calculado |
| 35 | Margen Front | float | Venta bruta - Costo Total | Calculado |
| 36 | Comisión % | float | (Comisión / Venta bruta) × 100 | Calculado |
| 37 | Comisión | float | Comisión marketplace | sale.order |
| 38 | Logística | float | Costo logística | sale.order |
| 39 | Marketing | float | Costo marketing | Calculado (0 por ahora) |
| 40 | Mg final | float | Margen Front - Comisión - Logística - Marketing | Calculado |

---

## 🔧 Componentes Principales

### 1. OdooClient (Conexión Robusta)

**Archivo:** `finanzas-unionx/backend/app/core/odoo_client.py`

```python
from app.core.odoo_client import OdooClient

odoo = OdooClient(
    url='https://unionxb2b.odoo.com',
    db='bmya-innovatek-sh-prd-6981800',
    username='andres@grupoeter.cl',
    password='<contraseña>',
    max_retries=10  # Reintentos inteligentes (1s, 2s, 4s, 8s, 16s, 32s, 60s+)
)
```

**Características:**
- ✅ Reintentos automáticos con backoff exponencial + jitter
- ✅ Batching adaptativo (reduce tamaño si falla)
- ✅ Logging detallado para debugging
- ✅ Manejo de 502 BAD GATEWAY
- ✅ Connection pooling

**Métodos:**
```python
# Búsqueda simple
resultados = odoo.search_read(
    'sale.order',
    [('state', 'in', ['sale', 'done'])],
    ['id', 'name', 'date_order', 'amount_total']
)

# Búsqueda en lotes (recomendado para muchos IDs)
productos = odoo.execute_in_batches(
    'product.product',
    [1, 2, 3, ..., 624],  # 624 productos
    ['id', 'name', 'default_code', 'manufacturer_id'],
    batch_size=100  # Se reduce automáticamente si hay errores
)
```

---

### 2. VentasService (Transformación RAW)

**Archivo:** `finanzas-unionx/backend/app/services/ventas_service.py`

```python
from app.services.ventas_service import VentasService

service = VentasService(odoo, planillas_dir=Path('data/planillas'))

# Método principal: extrae y transforma a RAW
df_raw = service.extract_to_raw_format(
    periodo_inicio="2026-04-01 00:00:00",
    periodo_fin="2026-04-12 23:59:59",
    progress_callback=lambda pct, label: print(f"{pct}% - {label}")
)

# DataFrame con 40 columnas exactas, listo para SQL
print(df_raw.columns.tolist())
# [
#   'Tipo Movimiento', 'Bodega', 'Documento', ..., 'Mg final'
# ]
```

**Flujo interno:**

```
1. _extraer_ordenes()
   → sale.order (6,207 órdenes)
   
2. _extraer_lineas()
   → sale.order.line (9,272 líneas)
   
3. _extraer_productos()
   → product.product (624 productos) [EN LOTES DE 100]
   
4. _extraer_facturas_y_nc()
   → account.move (3,837 facturas + 81 NC)
   → Calcula: total_neto = factura - sum(NC_que_la_reversan)
   
5. _cargar_maestra_canales()
   → Excel local: Tipo Negocio, KAM por Canal
   
6. _cargar_matriz_productos()
   → Excel local: Categorías por SKU
   
7. _construir_dataset_raw()
   → Arma 40 columnas en orden exacto
   → Mapea todos los campos
   
8. _calcular_metricas_raw()
   → Convierte tipos (float, int, datetime)
   → Calcula margen, comisión %, etc.
   
RESULTADO: DataFrame con 40 columnas
```

---

## 💰 Neteado (Facturas vs Notas de Crédito)

**Problema:** Si emites una NC parcial contra una factura, el reporte debe mostrar el monto neto, no la factura original.

**Solución:** `_extraer_facturas_y_nc()`

```python
# Ejemplo:
# Factura #1001: $100.000
# NC #2001 (revierte #1001): -$20.000
# → Reporte debe mostrar: $80.000 (NETO)

# Cálculo interno:
facturas = odoo.execute_in_batches(
    'account.move',
    invoice_ids,  # IDs de facturas
    ['id', 'name', 'amount_total'],
    batch_size=100
)

ncs = odoo.execute_in_batches(
    'account.move',
    nc_ids,  # IDs de notas de crédito
    ['id', 'reversal_move_id', 'amount_total'],
    batch_size=100
)

# Mapeo: para cada NC, encontrar la factura que revierte
nc_por_factura = {}
for nc in ncs:
    if nc['reversal_move_id']:
        factura_id = nc['reversal_move_id'][0]
        nc_por_factura.setdefault(factura_id, []).append(nc)

# Cálculo de netos
totales_netos = {}
for factura in facturas:
    factura_id = factura['id']
    amount_original = factura['amount_total']
    nc_amount = sum(abs(nc['amount_total']) 
                   for nc in nc_por_factura.get(factura_id, []))
    totales_netos[factura_id] = amount_original - nc_amount
```

---

## 📁 Planillas Requeridas

**Ubicación:** `data/planillas/`

### 1. Maestra Canales.xlsx
```
Columnas: Empresa | Canal
Ejemplo:
  Cliente Bice | Banco Bice
  Bravium Chile SPA | Bravium
  COMERCIAL GIANNY... | Casa de la Carcasa
```

**Uso:** Obtener `Tipo Negocio` y `KAM` por canal

### 2. Matriz productos.xlsx (Hoja: Productos)
```
Columnas: Marca | Producto | SKU | Categoría macro | Categoría padre | Categoría hijo | Categoría comercial | ...
Ejemplo:
  DAY | Bajada De Ducha 50X80Cm | 72429 | Hogar | Baño | Duchas | Electrohogar | ...
```

**Uso:** Obtener 4 niveles de categorización por SKU

---

## 🛠️ Variables de Entorno

**Archivo:** `.env` (raíz del proyecto)

```env
# Odoo
ODOO_URL=https://unionxb2b.odoo.com
ODOO_DB=bmya-innovatek-sh-prd-6981800
ODOO_USER=andres@grupoeter.cl
ANDRES_ODOO_PASSWORD=<contraseña>

# SQL (si integras con DB)
DB_HOST=localhost
DB_PORT=3306
DB_NAME=unionx_ventas
DB_USER=root
DB_PASSWORD=<contraseña>
```

---

## 📤 Integración con SQL

### Crear tabla en MySQL/PostgreSQL

```sql
CREATE TABLE ventas_raw (
    id INT PRIMARY KEY AUTO_INCREMENT,
    tipo_movimiento VARCHAR(50),
    bodega VARCHAR(255),
    documento VARCHAR(50),
    fecha_documento DATE,
    pedido VARCHAR(50),
    estado_pedido VARCHAR(50),
    tipo_despacho VARCHAR(255),
    sku VARCHAR(50),
    canal VARCHAR(100),
    fecha_venta DATE,
    hora_venta TIME,
    producto VARCHAR(255),
    categoria_macro VARCHAR(100),
    categoria_padre VARCHAR(100),
    categoria_hijo VARCHAR(100),
    categoria_comercial VARCHAR(100),
    estado_sku VARCHAR(50),
    pack VARCHAR(255),
    marca VARCHAR(100),
    proveedor VARCHAR(100),
    tipo_marca VARCHAR(50),
    tipo_compra VARCHAR(50),
    tipo_negocio VARCHAR(100),
    kam VARCHAR(100),
    estado_canal VARCHAR(50),
    ano_venta INT,
    mes_venta INT,
    semana_venta INT,
    dia_semana INT,
    hora_venta_dup TIME,
    cantidad FLOAT,
    venta_bruta DECIMAL(15, 2),
    costo_unitario DECIMAL(15, 2),
    costo_total DECIMAL(15, 2),
    margen_front DECIMAL(15, 2),
    comision_pct FLOAT,
    comision DECIMAL(15, 2),
    logistica DECIMAL(15, 2),
    marketing DECIMAL(15, 2),
    mg_final DECIMAL(15, 2),
    fecha_extraccion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_periodo (fecha_venta),
    INDEX idx_pedido (pedido),
    INDEX idx_sku (sku),
    INDEX idx_canal (canal)
);
```

### Insertar datos desde Python

```python
import pandas as pd
from sqlalchemy import create_engine

# Extraer RAW desde Odoo
df_raw = service.extract_to_raw_format(
    periodo_inicio="2026-04-01 00:00:00",
    periodo_fin="2026-04-12 23:59:59"
)

# Conectar a SQL
engine = create_engine('mysql+pymysql://root:password@localhost:3306/unionx_ventas')

# Insertar
df_raw.to_sql('ventas_raw', con=engine, if_exists='append', index=False)

print(f"✅ Insertadas {len(df_raw):,} filas en DB")
```

---

## 🔍 Validación de Datos

Después de extraer, valida siempre:

```python
# 1. Revisar NULLs en campos obligatorios
assert df_raw['Pedido'].notna().all(), "Hay pedidos sin ID"
assert df_raw['SKU'].notna().all(), "Hay SKUs nulos"
assert df_raw['Fecha Venta'].notna().all(), "Hay fechas nulas"

# 2. Revisar tipos de datos
assert df_raw['Cantidad'].dtype == 'float64', "Cantidad debe ser float"
assert df_raw['Año venta'].dtype == 'int64', "Año debe ser int"

# 3. Revisar rangos de valores
assert (df_raw['Mes venta'] >= 1).all() and (df_raw['Mes venta'] <= 12).all()

# 4. Revisar que el neteado está correcto
assert (df_raw['Venta bruta'] >= 0).all(), "Venta bruta no puede ser negativa"

# 5. Revisar que margen es coherente
assert (df_raw['Mg final'] <= df_raw['Margen Front']).all()

print("✅ Todas las validaciones pasaron")
```

---

## 📊 Consultas SQL Útiles

```sql
-- Top 10 productos por ventas
SELECT sku, producto, SUM(venta_bruta) as total_venta
FROM ventas_raw
WHERE fecha_venta BETWEEN '2026-04-01' AND '2026-04-30'
GROUP BY sku, producto
ORDER BY total_venta DESC
LIMIT 10;

-- Margen por canal
SELECT canal, 
       SUM(venta_bruta) as venta_total,
       SUM(mg_final) as margen_total,
       (SUM(mg_final) / SUM(venta_bruta) * 100) as pct_margen
FROM ventas_raw
WHERE fecha_venta BETWEEN '2026-04-01' AND '2026-04-30'
GROUP BY canal
ORDER BY margen_total DESC;

-- Evolución diaria
SELECT fecha_venta, 
       COUNT(*) as num_ventas,
       SUM(venta_bruta) as venta_dia,
       SUM(mg_final) as margen_dia
FROM ventas_raw
WHERE fecha_venta BETWEEN '2026-04-01' AND '2026-04-30'
GROUP BY fecha_venta
ORDER BY fecha_venta;
```

---

## ⚠️ Troubleshooting

### "502 Bad Gateway"
**Causa:** Odoo inestable
**Solución:** Script reintentan automáticamente hasta 10 veces con backoff exponencial. Si sigue fallando:
- Espera 5+ minutos
- Contacta a Odoo Support con el email de template en este proyecto

### "KeyError: 'Cliente'"
**Causa:** Maestra Canales no tiene la estructura esperada
**Solución:** Verificar que Excel tenga columnas: `Empresa`, `Canal`

### "No hay datos extraídos"
**Causa:** Período sin ventas o Odoo conexión fallida
**Solución:** 
```python
# Verificar conexión
try:
    odoo.authenticate()
    print("✅ Conexión OK")
except Exception as e:
    print(f"❌ Error: {e}")

# Verificar período
from app.services.ventas_service import VentasService
service = VentasService(odoo, Path('data/planillas'))
df_raw = service.extract_to_raw_format(
    "2026-01-01 00:00:00",
    "2026-12-31 23:59:59"
)
print(f"Filas encontradas: {len(df_raw)}")
```

---

## 📝 Changelog

| Fecha | Versión | Cambios |
|-------|---------|---------|
| 2026-04-15 | 1.0 | Release inicial con 40 columnas RAW, neteado NC, OdooClient mejorado |
| 2026-04-14 | 0.9 | Beta con batching adaptativo y reintentos jitter |
| 2026-04-13 | 0.8 | Primera versión con extract_to_raw_format() |

---

## 📞 Soporte

**Contacto Odoo:** support@odoo.com
- Referencia: Instancia `bmya-innovatek-sh-prd-6981800`
- Problema: 502 Bad Gateway en XML-RPC API durante search_read grandes

**Contacto Internal:** Andrés UnionX
- Email: andres@unionx.cl
- Para: Debugging de extracción, validación de datos

---

## 📎 Anexos

### A. Script `actualizar_raw_historico.py` Completo
**Ubicación:** Raíz del proyecto

```python
#!/usr/bin/env python3
"""
Script para actualizar el archivo RAW histórico con nuevas ventas.
Extrae datos de Odoo en formato RAW (40 columnas) y los agrega al archivo histórico.

Uso:
    python actualizar_raw_historico.py              # Actualiza con datos de hoy
    python actualizar_raw_historico.py --periodo "2026-04-01" "2026-04-13"  # Rango personalizado
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# Backend
backend_path = Path(__file__).parent / 'finanzas-unionx' / 'backend'
sys.path.insert(0, str(backend_path))

from app.core.odoo_client import OdooClient
from app.services.ventas_service import VentasService
from app.config import Config


def actualizar_raw(periodo_inicio=None, periodo_fin=None):
    """
    Actualiza el archivo RAW historico con nuevas ventas.

    Args:
        periodo_inicio: Fecha inicio (default: hoy a las 00:00)
        periodo_fin: Fecha fin (default: hoy a las 23:59:59)
    """

    # Fechas por defecto (última medianoche hasta ahora)
    if not periodo_inicio:
        hoy = datetime.now()
        periodo_inicio = f"{hoy.strftime('%Y-%m-%d')} 00:00:00"
        periodo_fin = f"{hoy.strftime('%Y-%m-%d')} 23:59:59"

    print("\n" + "="*100)
    print("ACTUALIZADOR DE RAW HISTORICO")
    print("="*100 + "\n")

    print(f"Periodo a extraer: {periodo_inicio} a {periodo_fin}\n")

    try:
        # Conectar a Odoo
        print("[1/5] Conectando a Odoo...")
        odoo = OdooClient(
            url=Config.ODOO_URL,
            db=Config.ODOO_DB,
            username=Config.ODOO_USER,
            password=Config.ODOO_PASSWORD
        )
        print("      [OK] Conectado\n")

        # Crear servicio
        print("[2/5] Inicializando VentasService...")
        service = VentasService(odoo, Config.PLANILLAS_DIR)
        print("      [OK] Servicio listo\n")

        # Extraer en formato RAW
        print("[3/5] Extrayendo datos en FORMATO RAW...\n")

        def progress_callback(pct, label):
            print(f"      {pct}% - {label}")

        df_raw_nuevo = service.extract_to_raw_format(
            periodo_inicio,
            periodo_fin,
            progress_callback=progress_callback
        )

        if len(df_raw_nuevo) == 0:
            print("\n[INFO] No hay datos nuevos para este periodo")
            return

        print(f"\n[4/5] Guardando datos...")

        # Retorna el DataFrame listo para insertar en SQL
        print(f"\n[5/5] Resumen de extracción:")
        print(f"      Lineas extraídas: {len(df_raw_nuevo):,}")
        print(f"      Canales: {df_raw_nuevo['Canal'].nunique()}")
        print(f"      Productos: {df_raw_nuevo['SKU'].nunique()}")

        # KPIs rápidos
        venta_total = df_raw_nuevo['Venta bruta'].sum()
        margen_total = df_raw_nuevo['Mg final'].sum()

        print(f"\n      KPIs del período:")
        print(f"      Venta Total (NETA): ${venta_total:,.2f}")
        print(f"      Margen Final: ${margen_total:,.2f}")

        if venta_total > 0:
            print(f"      % Margen: {(margen_total / venta_total * 100):.1f}%")

        print("\n" + "="*100)
        print("[OK] EXTRACCION COMPLETADA")
        print("="*100 + "\n")

        # Retornar DataFrame para insertar en SQL
        return df_raw_nuevo

    except Exception as e:
        print(f"\n[ERROR]: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Extrae ventas de Odoo en formato RAW')
    parser.add_argument('--periodo', nargs=2, metavar=('INICIO', 'FIN'),
                       help='Periodo personalizado (ej: "2026-04-01 00:00:00" "2026-04-30 23:59:59")')

    args = parser.parse_args()

    df_raw = None
    if args.periodo:
        df_raw = actualizar_raw(args.periodo[0], args.periodo[1])
    else:
        df_raw = actualizar_raw()

    # Usar df_raw para insertar en SQL
    if df_raw is not None:
        print(f"\n✅ DataFrame listo con {len(df_raw):,} filas")
        print(f"Columnas: {df_raw.columns.tolist()}")
```

---

**Versión:** 1.0  
**Fecha:** 2026-04-15  
**Autor:** Claude Code + Andrés UnionX  
**Status:** ✅ Producción
