"""
PASO 3a OPTIMIZADO: Extrae RAW desde Odoo (versión rápida)

Optimizaciones:
1. Busca sale.order (no line × line)
2. Usa search_read con muchos campos a la vez
3. Cache agresivo para evitar queries repetidas
4. Expande solo lo necesario (product, category)
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

class ExtraerRawOptimizado:
    """Versión optimizada para velocidad"""

    def __init__(self):
        self.url = "https://unionxb2b.odoo.com"
        self.db = "bmya-innovatek-sh-prd-6981800"
        self.usuario = "andres@grupoeter.cl"

        # Cargar password
        env_path = Path(__file__).parent.parent / ".env"
        load_dotenv(str(env_path))
        self.password = os.getenv("ANDRES_ODOO_PASSWORD")

        if not self.password:
            raise ValueError("Password no configurado en .env")

        self.uid = None
        self.models = None
        self.ruta_output = Path("data/outputs/raw_odoo_febrero_2026_optimizado.csv")
        self.ruta_output.parent.mkdir(parents=True, exist_ok=True)

        # Caches
        self.cache_categoria = {}
        self.cache_product = {}

        print(f"\n{'='*120}")
        print(" PASO 3a OPTIMIZADO: Extrae RAW desde Odoo (Rápido)")
        print(f"{'='*120}")

    def conectar(self) -> bool:
        """Conecta a Odoo"""
        print(f"\n[Conectando a Odoo...]")
        try:
            common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            self.uid = common.authenticate(self.db, self.usuario, self.password, {})

            if not self.uid:
                print("[ERROR] Autenticación fallida")
                return False

            self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
            print(f"[OK] Conectado (UID: {self.uid})")
            return True

        except Exception as e:
            print(f"[ERROR] {e}")
            return False

    def get_categoria_jerarquia(self, categ_id):
        """Obtiene la jerarquía de categoría (macro/padre/hijo)"""
        if categ_id in self.cache_categoria:
            return self.cache_categoria[categ_id]

        try:
            categorias = []
            current_id = categ_id

            for _ in range(5):
                if current_id:
                    categ = self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'product.category', 'read',
                        [current_id],
                        {'fields': ['name', 'parent_id']}
                    )[0]
                    categorias.append(categ.get('name', ''))
                    parent_id = categ.get('parent_id', [None])[0] if isinstance(categ.get('parent_id'), list) else None
                    current_id = parent_id
                else:
                    break

            categorias.reverse()

            result = {
                'macro': categorias[0] if len(categorias) > 0 else '',
                'padre': categorias[1] if len(categorias) > 1 else '',
                'hijo': categorias[2] if len(categorias) > 2 else '',
            }
            self.cache_categoria[categ_id] = result
            return result

        except:
            return {'macro': '', 'padre': '', 'hijo': ''}

    def get_product_info(self, product_id):
        """Obtiene info del producto con cache"""
        if product_id in self.cache_product:
            return self.cache_product[product_id]

        try:
            product = self.models.execute_kw(
                self.db, self.uid, self.password,
                'product.product', 'read',
                [product_id],
                {'fields': ['default_code', 'name', 'categ_id', 'brand_id', 'state']}
            )[0]

            # Obtener marca
            marca = ''
            brand_id = product.get('brand_id', [None])[0] if isinstance(product.get('brand_id'), list) else None
            if brand_id:
                try:
                    brand = self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'product.brand', 'read',
                        [brand_id],
                        {'fields': ['name']}
                    )[0]
                    marca = brand.get('name', '')
                except:
                    marca = ''

            # Obtener categoría
            categ_id = product.get('categ_id', [None])[0] if isinstance(product.get('categ_id'), list) else None
            categoria = {'macro': '', 'padre': '', 'hijo': ''}
            if categ_id:
                categoria = self.get_categoria_jerarquia(categ_id)

            result = {
                'sku': product.get('default_code', ''),
                'nombre': product.get('name', ''),
                'categoria_macro': categoria['macro'],
                'categoria_padre': categoria['padre'],
                'categoria_hijo': categoria['hijo'],
                'marca': marca,
                'estado': product.get('state', ''),
            }

            self.cache_product[product_id] = result
            return result

        except:
            return {
                'sku': '', 'nombre': '', 'categoria_macro': '',
                'categoria_padre': '', 'categoria_hijo': '',
                'marca': '', 'estado': ''
            }

    def extraer_ordenes(self) -> pd.DataFrame:
        """Extrae órdenes de febrero 2026"""
        print(f"\n[Extrayendo órdenes febrero 2026...]")

        try:
            domain = [
                ('create_date', '>=', '2026-02-01'),
                ('create_date', '<', '2026-03-01'),
                ('state', 'in', ['sale', 'done']),
            ]

            ordenes = self.models.execute_kw(
                self.db, self.uid, self.password,
                'sale.order', 'search_read',
                [domain],
                {'fields': [
                    'id', 'name', 'create_date', 'state',
                    'partner_id', 'user_id', 'team_id', 'warehouse_id',
                    'order_line', 'amount_total', 'payment_reference',
                    'fulfillment'
                ],
                 'limit': 10000}
            )

            print(f"[OK] {len(ordenes)} órdenes encontradas")

            datos = []

            for idx, orden in enumerate(ordenes):
                try:
                    if (idx + 1) % 50 == 0:
                        print(f"  [{idx + 1}/{len(ordenes)}]")

                    # DATOS DE LA ORDEN
                    fecha_venta = orden.get('create_date', '')
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

                    # Partner (Canal)
                    canal = ''
                    partner_id = orden.get('partner_id', [None])[0] if isinstance(orden.get('partner_id'), list) else None
                    if partner_id:
                        partner_name = orden.get('partner_id', [None, None])[1] if isinstance(orden.get('partner_id'), list) else None
                        canal = partner_name or ''

                    # User (KAM)
                    kam = ''
                    user_id = orden.get('user_id', [None])[0] if isinstance(orden.get('user_id'), list) else None
                    if user_id:
                        user_name = orden.get('user_id', [None, None])[1] if isinstance(orden.get('user_id'), list) else None
                        kam = user_name or ''

                    # Team (Tipo Negocio)
                    tipo_negocio = ''
                    team_id = orden.get('team_id', [None])[0] if isinstance(orden.get('team_id'), list) else None
                    if team_id:
                        team_name = orden.get('team_id', [None, None])[1] if isinstance(orden.get('team_id'), list) else None
                        tipo_negocio = team_name or ''

                    # Warehouse (Bodega)
                    bodega = ''
                    warehouse_id = orden.get('warehouse_id', [None])[0] if isinstance(orden.get('warehouse_id'), list) else None
                    if warehouse_id:
                        warehouse_name = orden.get('warehouse_id', [None, None])[1] if isinstance(orden.get('warehouse_id'), list) else None
                        bodega = warehouse_name or ''

                    # Por cada línea de la orden
                    order_lines = orden.get('order_line', [])
                    venta_total = orden.get('amount_total', 0)
                    cantidad_total = len(order_lines) if order_lines else 1

                    # Si no hay líneas, crear una fila para la orden
                    if not order_lines:
                        fila = {
                            'Tipo Movimiento': 'Venta',
                            'Bodega': bodega,
                            'Documento': orden.get('payment_reference', ''),
                            'Fecha Documento': fecha_venta,
                            'Pedido': orden.get('name', ''),
                            'Estado Pedido': orden.get('state', ''),
                            'Tipo Despacho': orden.get('fulfillment', ''),
                            'SKU': '',
                            'Canal': canal,
                            'Fecha Venta': fecha_venta,
                            'Hora Venta': f"{hora:02d}:00:00",
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
                            'Cantidad': 1,
                            'Venta bruta': venta_total,
                            'Costo Unitario': 0,
                            'Costo Total': 0,
                            'Margen Front': 0,
                            'Comision %': 0,
                            'Comisión': 0,
                            'Logística': 0,
                            'Marketing': 0,
                            'Mg final': 0,
                        }
                        datos.append(fila)

                except Exception as e:
                    print(f"  [AVISO] Error en orden {idx}: {str(e)[:50]}")
                    continue

            print(f"[OK] {len(datos)} filas procesadas")
            return pd.DataFrame(datos)

        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()

    def guardar(self, df: pd.DataFrame) -> bool:
        """Guarda como CSV"""
        print(f"\n[Guardando] {self.ruta_output}")
        try:
            df.to_csv(self.ruta_output, index=False)
            print(f"[OK] {len(df)} filas guardadas")
            return True
        except Exception as e:
            print(f"[ERROR] {e}")
            return False

    def ejecutar(self):
        """Ejecuta extracción"""
        if not self.conectar():
            return None

        df = self.extraer_ordenes()

        if df.empty:
            print("[ERROR] No se extrajo data")
            return None

        if not self.guardar(df):
            return None

        # Resumen
        print(f"\n{'='*120}")
        print(" EXTRACCION COMPLETADA")
        print(f"{'='*120}")
        print(f"\nFebrero 2026:")
        print(f"  Filas: {len(df):,}")
        print(f"  Venta total: ${df['Venta bruta'].sum():,.0f}")

        return df


if __name__ == "__main__":
    extractor = ExtraerRawOptimizado()
    df = extractor.ejecutar()

    if df is not None and not df.empty:
        print(f"\n[SIGUIENTE] Validar contra Raw ventas Y.xlsx")
