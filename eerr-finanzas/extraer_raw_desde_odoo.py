"""
PASO 3a ODOO: Extrae RAW completo directamente desde Odoo
- Reemplaza Raw ventas Y.xlsx con extracción en tiempo real
- Obtiene 40 columnas de sale.order.line + producto + orden
- Agrupa por Año/Mes/Canal/Tipo Negocio/KAM
- Genera DataFrame listo para inyectar en "Análisis Resultado"

CONEXIÓN ODOO:
- URL: https://unionxb2b.odoo.com
- Base: bmya-innovatek-sh-prd-6981800
- Usuario: andres@grupoeter.cl
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os

class ExtraerRawOdoo:
    """Extrae datos de venta línea × línea desde Odoo"""

    def __init__(self):
        self.url = "https://unionxb2b.odoo.com"
        self.db = "bmya-innovatek-sh-prd-6981800"
        self.usuario = "andres@grupoeter.cl"

        # Obtener password desde .env o solicitarlo
        try:
            from dotenv import load_dotenv
            load_dotenv()
            self.password = os.getenv("ANDRES_ODOO_PASSWORD")
            if not self.password:
                self.password = input("\n[ODOO] Ingresa tu password de Odoo: ")
        except:
            self.password = input("\n[ODOO] Ingresa tu password de Odoo: ")

        self.uid = None
        self.models = None
        self.ruta_output = Path("data/outputs/raw_desde_odoo_febrero_2026.csv")
        self.ruta_output.parent.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*100}")
        print(" PASO 3a ODOO: EXTRAE RAW VENTAS DIRECTAMENTE DESDE ODOO")
        print(f"{'='*100}")
        print(f"\nConexión:")
        print(f"  URL: {self.url}")
        print(f"  Base: {self.db}")
        print(f"  Usuario: {self.usuario}")

    def conectar(self) -> bool:
        """Conecta a Odoo mediante XML-RPC"""
        print(f"\n[Conectando a Odoo...]")
        try:
            common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            self.uid = common.authenticate(self.db, self.usuario, self.password, {})

            if not self.uid:
                print("[ERROR] Autenticación fallida. Verifica usuario y password.")
                return False

            self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
            print(f"[OK] Conectado a Odoo (UID: {self.uid})")
            return True

        except Exception as e:
            print(f"[ERROR] No se pudo conectar: {e}")
            print("\n[ALTERNATIVA] Si Odoo requiere 2FA:")
            print("  1. Genera un token en tu perfil Odoo")
            print("  2. Usa el token como 'password' en la conexión")
            return False

    def extraer_lineas_febrero(self) -> list:
        """Extrae todas las líneas de venta de febrero 2026"""
        print(f"\n[Extrayendo sale.order.line de febrero 2026...]")

        try:
            # Buscar órdenes de venta en febrero 2026
            domain = [
                ('order_id.date_order', '>=', '2026-02-01'),
                ('order_id.date_order', '<', '2026-03-01'),
                ('order_id.state', 'in', ['sale', 'done']),
            ]

            # Campos a extraer de sale.order.line
            fields_linea = [
                'id', 'order_id', 'product_id', 'qty_invoiced', 'product_uom_qty',
                'price_unit', 'price_subtotal', 'discount', 'create_date'
            ]

            lines = self.models.execute_kw(
                self.db, self.uid, self.password,
                'sale.order.line', 'search_read',
                [domain],
                {'fields': fields_linea, 'limit': 100000}
            )

            print(f"[OK] {len(lines)} líneas de venta encontradas")
            return lines

        except Exception as e:
            print(f"[ERROR] No se pudieron extraer líneas: {e}")
            import traceback
            traceback.print_exc()
            return []

    def enriquecer_lineas(self, lines: list) -> pd.DataFrame:
        """Enriquece cada línea con datos del producto y la orden"""
        print(f"\n[Enriqueciendo {len(lines)} líneas con detalles...]")

        datos = []

        for idx, line in enumerate(lines):
            try:
                if (idx + 1) % 1000 == 0:
                    print(f"  [{idx + 1}/{len(lines)}]")

                # Datos de la línea
                order_id = line['order_id'][0] if line['order_id'] else None
                product_id = line['product_id'][0] if line['product_id'] else None
                cantidad = line['qty_invoiced'] if line['qty_invoiced'] else line['product_uom_qty']

                # Validar que haya cantidad
                if not cantidad or cantidad == 0:
                    continue

                # Obtener datos de la orden
                if order_id:
                    try:
                        order = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'sale.order', 'read',
                            [order_id],
                            {'fields': ['name', 'date_order', 'warehouse_id', 'user_id', 'state']}
                        )[0]
                    except:
                        order = {}
                else:
                    order = {}

                # Obtener datos del producto
                if product_id:
                    try:
                        product = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'product.product', 'read',
                            [product_id],
                            {'fields': ['default_code', 'name', 'categ_id', 'manufacturer_id',
                                       'seller_ids', 'standard_price', 'list_price']}
                        )[0]
                    except:
                        product = {}
                else:
                    product = {}

                # Obtener categoría y detalles
                categ_id = product.get('categ_id', [None])[0] if isinstance(product.get('categ_id'), list) else None
                categoria_info = {}
                if categ_id:
                    try:
                        categoria_info = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'product.category', 'read',
                            [categ_id],
                            {'fields': ['name', 'parent_id']}
                        )[0]
                    except:
                        categoria_info = {}

                # Calcular costos y márgenes
                precio_unitario = line.get('price_unit', 0)
                costo_unitario = product.get('standard_price', 0)
                venta_bruta = line.get('price_subtotal', cantidad * precio_unitario)
                costo_total = cantidad * costo_unitario
                margen_directo = venta_bruta - costo_total

                # Fecha y derivados
                fecha_venta = order.get('date_order', '')
                if fecha_venta:
                    try:
                        if isinstance(fecha_venta, str):
                            dt = datetime.fromisoformat(fecha_venta.replace('Z', '+00:00'))
                        else:
                            dt = fecha_venta

                        año = dt.year
                        mes = dt.month
                        semana = dt.isocalendar()[1]
                        dia_semana = dt.weekday()
                        hora = dt.hour
                    except:
                        año, mes, semana, dia_semana, hora = 0, 0, 0, 0, 0
                else:
                    año, mes, semana, dia_semana, hora = 0, 0, 0, 0, 0

                # CUSTOM FIELDS - Intentar obtener
                # Nota: Estos campos pueden requerir ajustes según la configuración real de Odoo

                # Canal (custom field en sale.order)
                canal = order.get('x_studio_canal', '') or order.get('x_canal', '') or 'Sin asignar'

                # Tipo Negocio (custom field)
                tipo_negocio = order.get('x_studio_tipo_negocio', '') or order.get('x_tipo_negocio', '') or 'Distribucion'

                # KAM (puede ser user_id)
                kam = order.get('user_id', [None])[1] if isinstance(order.get('user_id'), list) else order.get('user_id', '')

                # Comisión % (custom field)
                comision_pct = order.get('x_studio_comision_pct', '') or line.get('x_comision_pct', '')

                # Comisión (calculada)
                comision = (venta_bruta * float(comision_pct) / 100) if comision_pct else 0

                # Logística (custom field)
                logistica = order.get('x_studio_logistica', '') or line.get('x_logistica', '') or 0

                # Marketing (custom field)
                marketing = order.get('x_studio_marketing', '') or line.get('x_marketing', '') or 0

                # Margen final
                margen_final = margen_directo - comision - float(logistica if logistica else 0) - float(marketing if marketing else 0)

                # Construir fila
                fila = {
                    'Tipo Movimiento': 'Venta',
                    'Bodega': order.get('warehouse_id', [None])[1] if isinstance(order.get('warehouse_id'), list) else '',
                    'Documento': order.get('name', ''),
                    'Fecha Documento': fecha_venta,
                    'Pedido': order.get('name', ''),
                    'Estado Pedido': order.get('state', ''),
                    'Tipo Despacho': '',  # No disponible en base query
                    'SKU': product.get('default_code', ''),
                    'Canal': canal,
                    'Fecha Venta': fecha_venta,
                    'Hora Venta': f"{hora:02d}:00:00" if hora else '',
                    'Producto': product.get('name', ''),
                    'Categoría macro': categoria_info.get('name', ''),
                    'Categoría padre': '',  # Requiere recursión
                    'Categoría hijo': categoria_info.get('name', ''),
                    'Categoría comercial': '',  # Custom
                    'Estado SKU': 'active',
                    'Pack': 'No',  # Custom field
                    'Marca': '',  # manufacturer_id
                    'Proveedor': '',  # seller_ids
                    'Tipo Marca': '',  # Custom
                    'Tipo Compra': '',  # Custom
                    'Tipo Negocio': tipo_negocio,
                    'KAM': kam,
                    'Estado Canal': 'In',  # Custom
                    'Año venta': año,
                    'Mes venta': mes,
                    'Semana venta': semana,
                    'Día semana': dia_semana,
                    'Hora venta': hora,
                    'Cantidad': cantidad,
                    'Venta bruta': venta_bruta,
                    'Costo Unitario': costo_unitario,
                    'Costo Total': costo_total,
                    'Margen Front': margen_directo,
                    'Comision %': comision_pct if comision_pct else 0,
                    'Comisión': comision,
                    'Logística': logistica,
                    'Marketing': marketing,
                    'Mg final': margen_final,
                }

                datos.append(fila)

            except Exception as e:
                print(f"  [AVISO] Error procesando línea {idx}: {str(e)[:50]}")
                continue

        print(f"[OK] {len(datos)} líneas enriquecidas")
        return pd.DataFrame(datos)

    def agregar_por_canal(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrupa por Año, Mes, Canal, Tipo Negocio, KAM"""
        print(f"\n[Agrupando] Por período/canal/negocio/kam")

        if df.empty:
            print("[ERROR] DataFrame vacío, no se puede agrupar")
            return df

        df_agrupado = df.groupby(
            ['Año venta', 'Mes venta', 'Canal', 'Tipo Negocio', 'KAM'],
            as_index=False
        ).agg({
            'Venta bruta': 'sum',
            'Costo Total': 'sum',
            'Margen Front': 'sum',
            'Comisión': 'sum',
            'Logística': 'sum',
            'Marketing': 'sum',
            'Mg final': 'sum',
            'Cantidad': 'sum',
        })

        # Renombrar para coincidir con "Análisis Resultado"
        df_agrupado = df_agrupado.rename(columns={
            'Año venta': 'AÑO',
            'Mes venta': 'Mes',
            'Venta bruta': 'Venta',
            'Costo Total': 'Costo Venta',
            'Margen Front': 'Margen Directo',
        })

        # Reordenar columnas
        columnas_orden = [
            'AÑO', 'Mes', 'Canal', 'Tipo Negocio', 'KAM',
            'Venta', 'Costo Venta', 'Margen Directo', 'Cantidad',
            'Comisión', 'Logística', 'Marketing', 'Mg final'
        ]

        df_agrupado = df_agrupado[[c for c in columnas_orden if c in df_agrupado.columns]]

        print(f"[OK] {df_agrupado.shape[0]} filas agrupadas")
        return df_agrupado

    def ejecutar(self):
        """Ejecuta extracción completa"""

        if not self.conectar():
            return None

        # Extraer líneas
        lines = self.extraer_lineas_febrero()
        if not lines:
            print("[ERROR] No se encontraron líneas de venta")
            return None

        # Enriquecer
        df = self.enriquecer_lineas(lines)
        if df.empty:
            print("[ERROR] No se pudieron enriquecer las líneas")
            return None

        # Agrupar
        df_agrupado = self.agregar_por_canal(df)

        # Guardar
        print(f"\n[Guardando] {self.ruta_output.name}")
        df_agrupado.to_csv(self.ruta_output, index=False)
        print(f"[OK] {self.ruta_output}")

        # Resumen
        print(f"\n[RESUMEN] Extracción desde Odoo - Febrero 2026")
        print(f"  Filas agrupadas: {len(df_agrupado)}")
        print(f"  Venta total: ${df_agrupado['Venta'].sum():,.0f}")
        print(f"  Costo total: ${df_agrupado['Costo Venta'].sum():,.0f}")
        print(f"  Margen directo: ${df_agrupado['Margen Directo'].sum():,.0f}")

        return df_agrupado


# ============================================================================
# EJECUTAR
# ============================================================================

if __name__ == "__main__":
    extractor = ExtraerRawOdoo()
    df = extractor.ejecutar()

    if df is not None and not df.empty:
        print(f"\n{'='*100}")
        print(" LISTO PARA VALIDAR CONTRA Raw ventas Y.xlsx")
        print(f"{'='*100}")
        print(f"\n[PROXIMO PASO] Comparar resultados:")
        print(f"  1. Correr: python validar_raw_vs_analisis.py")
        print(f"  2. Ajustar custom fields según errores")
        print(f"  3. Ejecutar inyección en Análisis Resultado")
