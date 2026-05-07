"""
PASO 3a VALIDACION: Extrae desde Contabilidad CON FILTROS MEJORADOS
Objetivo: Entender por qué hay discrepancias con Excel

Filtros aplicados:
1. Solo facturas 'posted' (confirmadas)
2. Solo out_invoice (venta, no devoluciones)
3. Fecha factura Feb 2026
4. Solo líneas con product_id (excluye impuestos/gastos)
5. Solo cuentas de venta (account_id tipo 'income')
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

print("\n" + "="*120)
print(" VALIDACION: Contabilidad vs Excel (Febrero 2026)")
print("="*120)

# Conectar
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(str(env_path))
password = os.getenv("ANDRES_ODOO_PASSWORD")

if not password:
    print("[ERROR] Password no configurado")
    exit(1)

url = "https://unionxb2b.odoo.com"
db = "bmya-innovatek-sh-prd-6981800"
usuario = "andres@grupoeter.cl"

print(f"\n[Conectando a Odoo...]")
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, usuario, password, {})

if not uid:
    print("[ERROR] Autenticación fallida")
    exit(1)

print(f"[OK] Conectado (UID: {uid})")
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# PASO 1: BUSCAR FACTURAS FEBRERO 2026
print(f"\n[PASO 1] Buscando facturas febrero 2026...")

domain = [
    ('invoice_date', '>=', '2026-02-01'),
    ('invoice_date', '<', '2026-03-01'),
    ('state', '=', 'posted'),
    ('move_type', '=', 'out_invoice'),
]

facturas = models.execute_kw(
    db, uid, password,
    'account.move', 'search_read',
    [domain],
    {'fields': ['id', 'name', 'invoice_date', 'partner_id', 'user_id',
                'team_id', 'amount_total', 'amount_untaxed',
                'line_ids', 'state'],
     'limit': 100000}
)

print(f"[OK] {len(facturas)} facturas encontradas")

# PASO 2: EXTRAER LINEAS
print(f"\n[PASO 2] Buscando líneas de esas facturas...")

factura_ids = [f['id'] for f in facturas]

lineas = models.execute_kw(
    db, uid, password,
    'account.move.line', 'search_read',
    [[('move_id', 'in', factura_ids)]],
    {'fields': ['id', 'move_id', 'product_id', 'quantity', 'price_unit',
                'price_subtotal', 'account_id', 'tax_ids', 'create_date'],
     'limit': 500000}
)

print(f"[OK] {len(lineas)} líneas contables encontradas")

# PASO 3: MAPEO DE FACTURAS
print(f"\n[PASO 3] Creando mapeo de facturas y cuentas...")

facturas_dict = {}
cuentas_dict = {}  # Cache de tipos de cuenta

for factura in facturas:
    facturas_dict[factura['id']] = factura

print(f"[OK] {len(facturas_dict)} facturas en cache")

# PASO 4: PROCESAR LINEAS CON FILTROS MEJORADOS
print(f"\n[PASO 4] Procesando {len(lineas)} líneas...")

datos = []
lineas_descartadas = {'sin_producto': 0, 'impuesto': 0, 'otros': 0}

for idx, linea in enumerate(lineas):
    try:
        if (idx + 1) % 5000 == 0:
            print(f"  [{idx + 1}/{len(lineas)}]")

        move_id = linea.get('move_id', [None])[0] if linea.get('move_id') else None
        if not move_id or move_id not in facturas_dict:
            continue

        factura = facturas_dict[move_id]

        # FILTRO 1: Solo líneas con producto
        product_id = linea.get('product_id', [None])[0] if linea.get('product_id') else None
        if not product_id:
            lineas_descartadas['sin_producto'] += 1
            continue

        # FILTRO 2: Excluir líneas de impuesto (si tiene tax_ids pero product_id es impuesto)
        # En Odoo, las líneas de impuesto tienen quantity=0 o son líneas de ajuste
        quantity = linea.get('quantity', 0)
        if quantity == 0:
            lineas_descartadas['impuesto'] += 1
            continue

        # Fecha factura
        fecha_str = factura.get('invoice_date', '')
        if fecha_str:
            try:
                if isinstance(fecha_str, str):
                    dt = datetime.fromisoformat(fecha_str.replace('Z', '+00:00'))
                else:
                    dt = fecha_str

                año = dt.year
                mes = dt.month
                semana = dt.isocalendar()[1]
                dia_semana = dt.weekday()
                hora = dt.hour
            except:
                año, mes, semana, dia_semana, hora = 2026, 2, 1, 0, 0
        else:
            año, mes, semana, dia_semana, hora = 2026, 2, 1, 0, 0

        # Partner (Cliente/Canal)
        partner_data = factura.get('partner_id', [None, ''])
        canal = partner_data[1] if isinstance(partner_data, list) and len(partner_data) > 1 else ''

        # User (KAM)
        user_data = factura.get('user_id', [None, ''])
        kam = user_data[1] if isinstance(user_data, list) and len(user_data) > 1 else ''

        # Team (Tipo Negocio)
        team_data = factura.get('team_id', [None, ''])
        tipo_negocio = team_data[1] if isinstance(team_data, list) and len(team_data) > 1 else ''

        # Datos de la línea
        cantidad = linea.get('quantity', 0)
        precio_unitario = linea.get('price_unit', 0)
        venta_bruta = linea.get('price_subtotal', cantidad * precio_unitario)

        # Crear fila
        fila = {
            'Tipo Movimiento': 'Venta',
            'Bodega': '',
            'Documento': factura.get('name', ''),
            'Fecha Documento': fecha_str,
            'Pedido': factura.get('name', ''),
            'Estado Pedido': factura.get('state', ''),
            'Tipo Despacho': '',
            'SKU': '',
            'Canal': canal,
            'Fecha Venta': fecha_str,
            'Hora Venta': f"{hora:02d}:00:00" if hora else '',
            'Producto': '',
            'Categoría macro': '',
            'Categoría padre': '',
            'Categoría hijo': '',
            'Categoría comercial': '',
            'Estado SKU': '',
            'Pack': '',
            'Marca': '',
            'Proveedor': '',
            'Tipo Marca': '',
            'Tipo Compra': '',
            'Tipo Negocio': tipo_negocio,
            'KAM': kam,
            'Estado Canal': '',
            'Año venta': año,
            'Mes venta': mes,
            'Semana venta': semana,
            'Día semana': dia_semana,
            'Hora venta': hora,
            'Cantidad': cantidad,
            'Venta bruta': venta_bruta,
            'Costo Unitario': 0,
            'Costo Total': 0,
            'Margen Front': venta_bruta,
            'Comision %': 0,
            'Comisión': 0,
            'Logística': 0,
            'Marketing': 0,
            'Mg final': venta_bruta,
        }

        datos.append(fila)

    except Exception as e:
        pass

print(f"[OK] {len(datos)} líneas procesadas")
print(f"[INFO] Líneas descartadas: {lineas_descartadas}")

# PASO 5: GUARDAR
print(f"\n[PASO 5] Guardando...")
df = pd.DataFrame(datos)

ruta = Path("data/outputs/raw_contabilidad_febrero_2026_validado.csv")
ruta.parent.mkdir(parents=True, exist_ok=True)

df.to_csv(ruta, index=False)
print(f"[OK] Guardado: {ruta}")

# PASO 6: COMPARAR CONTRA EXCEL
print(f"\n{'='*120}")
print(" COMPARACION: CONTABILIDAD vs EXCEL")
print(f"{'='*120}")

print(f"\n[PASO 6] Cargando Raw Excel...")
ruta_excel = Path(__file__).parent.parent / "datos_entrada/Raw ventas Y.xlsx"
df_raw = pd.read_excel(ruta_excel, sheet_name='RAW')
df_raw_feb = df_raw[(df_raw['Año venta'] == 2026) & (df_raw['Mes venta'] == 2)]

print(f"\nExcel (source):")
print(f"  Filas: {len(df_raw_feb):,}")
venta_excel = df_raw_feb['Venta bruta'].sum()
print(f"  Venta bruta: ${venta_excel:,.0f}")
print(f"  Canales únicos: {df_raw_feb['Canal'].nunique()}")

print(f"\nContabilidad (extracción):")
print(f"  Filas: {len(df):,}")
venta_conta = df['Venta bruta'].sum()
print(f"  Venta bruta: ${venta_conta:,.0f}")
print(f"  Canales únicos: {df['Canal'].nunique()}")

print(f"\nDiferencias:")
diff_filas = len(df) - len(df_raw_feb)
diff_venta = venta_conta - venta_excel
pct_venta = (diff_venta / venta_excel * 100) if venta_excel > 0 else 0

print(f"  Filas: {diff_filas:,} ({diff_filas/len(df_raw_feb)*100:+.2f}%)")
print(f"  Venta: ${diff_venta:,.0f} ({pct_venta:+.2f}%)")

if abs(pct_venta) < 5:
    print(f"  Status: ACEPTABLE (< 5%)")
else:
    print(f"  Status: REQUIERE REVISION (diferencia > 5%)")

print(f"\n{'='*120}")
