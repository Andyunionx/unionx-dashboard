"""
PASO 3a FINAL: Extrae RAW directamente desde Odoo (Campos reales confirmados)

Mapeo confirmado por Andrés:
- Canal: partner_id
- Tipo Negocio: team_id
- KAM: user_id
- Venta bruta: amount_total
- Costo: purchase_price
- Cantidad: product_uom_qty
- Margen: margin (Odoo lo calcula)
- Categoría: categ_id (recursiva)
- Marca: brand_id
- SKU: default_code

Comisiones, logística, marketing: NO existen en Odoo (se rellenan después)

Salida: RAW con 40 columnas, idéntico a Raw ventas Y.xlsx
"""

import xmlrpc.client
import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from collections import defaultdict

class ExtraerRawOdooV2:
    """Extrae RAW desde Odoo usando campos confirmados por Andrés"""

    def __init__(self):
        self.url = "https://unionxb2b.odoo.com"
        self.db = "bmya-innovatek-sh-prd-6981800"
        self.usuario = "andres@grupoeter.cl"

        # Obtener password desde .env en raíz del proyecto
        from dotenv import load_dotenv
        from pathlib import Path
        env_path = Path(__file__).parent.parent / ".env"  # UNION X - IA/.env
        load_dotenv(str(env_path))
        self.password = os.getenv("ANDRES_ODOO_PASSWORD")

        if not self.password:
            print("[ERROR] ANDRES_ODOO_PASSWORD no encontrado en .env")
            raise ValueError("Password no configurado")

        self.uid = None
        self.models = None
        self.ruta_output = Path("data/outputs/raw_odoo_febrero_2026.csv")
        self.ruta_output.parent.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*120}")
        print(" PASO 3a FINAL: Extrae RAW desde Odoo (Campos reales confirmados)")
        print(f"{'='*120}")
        print(f"\nConexión Odoo:")
        print(f"  URL: {self.url}")
        print(f"  Base: {self.db}")
        print(f"  Usuario: {self.usuario}")

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

    def extraer_lineas_febrero(self) -> list:
        """Extrae sale.order.line de febrero 2026"""
        print(f"\n[Extrayendo sale.order.line febrero 2026...]")

        try:
            # Buscar órdenes en febrero
            domain = [
                ('create_date', '>=', '2026-02-01'),
                ('create_date', '<', '2026-03-01'),
                ('state', 'in', ['sale', 'done']),
            ]

            # Obtener IDs de órdenes
            order_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'sale.order', 'search',
                [domain],
                {'limit': 100000}
            )

            print(f"[OK] {len(order_ids)} órdenes encontradas")

            # Extraer líneas de esas órdenes
            line_domain = [('order_id', 'in', order_ids)]

            lines = self.models.execute_kw(
                self.db, self.uid, self.password,
                'sale.order.line', 'search_read',
                [line_domain],
                {'fields': ['id', 'order_id', 'product_id', 'product_uom_qty',
                           'price_unit', 'purchase_price', 'margin'],
                 'limit': 100000}
            )

            print(f"[OK] {len(lines)} líneas extraídas")
            return lines, order_ids

        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            return [], []

    def enriquecer_lineas(self, lines: list, order_ids: list) -> pd.DataFrame:
        """Enriquece líneas con datos de orden, producto, partner, user, team"""
        print(f"\n[Enriqueciendo {len(lines)} líneas...]")

        # Cache para evitar queries repetidas
        cache_orden = {}
        cache_producto = {}
        cache_partner = {}
        cache_user = {}
        cache_team = {}
        cache_categoria = {}

        datos = []

        for idx, line in enumerate(lines):
            try:
                if (idx + 1) % 1000 == 0:
                    print(f"  [{idx + 1}/{len(lines)}]")

                order_id = line['order_id'][0] if line['order_id'] else None
                product_id = line['product_id'][0] if line['product_id'] else None
                cantidad = line['product_uom_qty']

                if not cantidad or cantidad == 0:
                    continue

                # DATOS DE LA ORDEN
                if order_id not in cache_orden:
                    try:
                        orden = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'sale.order', 'read',
                            [order_id],
                            {'fields': ['name', 'create_date', 'state', 'warehouse_id',
                                       'partner_id', 'user_id', 'team_id',
                                       'payment_reference', 'fulfillment',
                                       'amount_total', 'amount_untaxed']}
                        )[0]
                        cache_orden[order_id] = orden
                    except:
                        cache_orden[order_id] = {}

                orden = cache_orden[order_id]

                # DATOS DEL PRODUCTO
                if product_id not in cache_producto:
                    try:
                        producto = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'product.product', 'read',
                            [product_id],
                            {'fields': ['default_code', 'name', 'categ_id',
                                       'brand_id', 'seller_ids', 'state']}
                        )[0]
                        cache_producto[product_id] = producto
                    except:
                        cache_producto[product_id] = {}

                producto = cache_producto[product_id]

                # PARTNER (Canal)
                partner_id = orden.get('partner_id', [None])[0] if isinstance(orden.get('partner_id'), list) else None
                if partner_id and partner_id not in cache_partner:
                    try:
                        partner = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'res.partner', 'read',
                            [partner_id],
                            {'fields': ['name']}
                        )[0]
                        cache_partner[partner_id] = partner.get('name', '')
                    except:
                        cache_partner[partner_id] = ''

                canal = cache_partner.get(partner_id, '')

                # USER (KAM)
                user_id = orden.get('user_id', [None])[0] if isinstance(orden.get('user_id'), list) else None
                if user_id and user_id not in cache_user:
                    try:
                        user = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'res.users', 'read',
                            [user_id],
                            {'fields': ['name']}
                        )[0]
                        cache_user[user_id] = user.get('name', '')
                    except:
                        cache_user[user_id] = ''

                kam = cache_user.get(user_id, '')

                # TEAM (Tipo Negocio)
                team_id = orden.get('team_id', [None])[0] if isinstance(orden.get('team_id'), list) else None
                if team_id and team_id not in cache_team:
                    try:
                        team = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'crm.team', 'read',
                            [team_id],
                            {'fields': ['name']}
                        )[0]
                        cache_team[team_id] = team.get('name', '')
                    except:
                        cache_team[team_id] = ''

                tipo_negocio = cache_team.get(team_id, '')

                # CATEGORIA (recursiva)
                categ_id = producto.get('categ_id', [None])[0] if isinstance(producto.get('categ_id'), list) else None
                categoria_info = {'macro': '', 'padre': '', 'hijo': ''}

                if categ_id:
                    if categ_id not in cache_categoria:
                        try:
                            # Obtener jerarquía
                            categorias = []
                            current_id = categ_id

                            for _ in range(5):  # Max 5 niveles
                                if current_id:
                                    categ = self.models.execute_kw(
                                        self.db, self.uid, self.password,
                                        'product.category', 'read',
                                        [current_id],
                                        {'fields': ['name', 'parent_id']}
                                    )[0]
                                    categorias.append(categ.get('name', ''))
                                    current_id = categ.get('parent_id', [None])[0] if isinstance(categ.get('parent_id'), list) else None
                                else:
                                    break

                            # Invertir para tener macro -> padre -> hijo
                            categorias.reverse()

                            info = {
                                'macro': categorias[0] if len(categorias) > 0 else '',
                                'padre': categorias[1] if len(categorias) > 1 else '',
                                'hijo': categorias[2] if len(categorias) > 2 else '',
                            }
                            cache_categoria[categ_id] = info

                        except:
                            cache_categoria[categ_id] = {'macro': '', 'padre': '', 'hijo': ''}

                    categoria_info = cache_categoria[categ_id]

                # MARCA
                brand_id = producto.get('brand_id', [None])[0] if isinstance(producto.get('brand_id'), list) else None
                marca = ''
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

                # PROVEEDOR (seller_ids)
                proveedor = ''
                seller_ids = producto.get('seller_ids', [])
                if seller_ids:
                    try:
                        seller = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'product.supplierinfo', 'read',
                            [seller_ids[0]],
                            {'fields': ['partner_id']}
                        )[0]
                        partner_id_supplier = seller.get('partner_id', [None])[0] if isinstance(seller.get('partner_id'), list) else None
                        if partner_id_supplier:
                            partner_supplier = self.models.execute_kw(
                                self.db, self.uid, self.password,
                                'res.partner', 'read',
                                [partner_id_supplier],
                                {'fields': ['name']}
                            )[0]
                            proveedor = partner_supplier.get('name', '')
                    except:
                        proveedor = ''

                # FECHAS Y DERIVADAS
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
                        hora_str = f"{hora:02d}:00:00"

                    except:
                        año, mes, semana, dia_semana, hora, hora_str = 0, 0, 0, 0, 0, ''
                else:
                    año, mes, semana, dia_semana, hora, hora_str = 0, 0, 0, 0, 0, ''

                # COSTOS Y MÁRGENES
                precio_unitario = line.get('price_unit', 0)
                costo_unitario = line.get('purchase_price', 0)
                venta_bruta = precio_unitario * cantidad
                costo_total = costo_unitario * cantidad
                margen_front = line.get('margin', venta_bruta - costo_total)

                # BODEGA
                warehouse_id = orden.get('warehouse_id', [None])[0] if isinstance(orden.get('warehouse_id'), list) else None
                bodega = ''
                if warehouse_id:
                    try:
                        warehouse = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'stock.warehouse', 'read',
                            [warehouse_id],
                            {'fields': ['name']}
                        )[0]
                        bodega = warehouse.get('name', '')
                    except:
                        bodega = ''

                # CONSTRUIR FILA
                fila = {
                    'Tipo Movimiento': 'Venta',
                    'Bodega': bodega,
                    'Documento': orden.get('payment_reference', ''),
                    'Fecha Documento': fecha_venta,
                    'Pedido': orden.get('name', ''),
                    'Estado Pedido': orden.get('state', ''),
                    'Tipo Despacho': orden.get('fulfillment', ''),
                    'SKU': producto.get('default_code', ''),
                    'Canal': canal,
                    'Fecha Venta': fecha_venta,
                    'Hora Venta': hora_str,
                    'Producto': producto.get('name', ''),
                    'Categoría macro': categoria_info.get('macro', ''),
                    'Categoría padre': categoria_info.get('padre', ''),
                    'Categoría hijo': categoria_info.get('hijo', ''),
                    'Categoría comercial': '',  # No existe en Odoo
                    'Estado SKU': producto.get('state', ''),
                    'Pack': '',  # No existe en Odoo
                    'Marca': marca,
                    'Proveedor': proveedor,
                    'Tipo Marca': '',  # No existe en Odoo
                    'Tipo Compra': '',  # No existe en Odoo
                    'Tipo Negocio': tipo_negocio,
                    'KAM': kam,
                    'Estado Canal': '',  # No existe en Odoo
                    'Año venta': año,
                    'Mes venta': mes,
                    'Semana venta': semana,
                    'Día semana': dia_semana,
                    'Hora venta': hora,
                    'Cantidad': cantidad,
                    'Venta bruta': venta_bruta,
                    'Costo Unitario': costo_unitario,
                    'Costo Total': costo_total,
                    'Margen Front': margen_front,
                    'Comision %': 0,  # No existe en Odoo
                    'Comisión': 0,  # No existe en Odoo
                    'Logística': 0,  # No existe en Odoo
                    'Marketing': 0,  # No existe en Odoo
                    'Mg final': margen_front,  # Por ahora = margen_front
                }

                datos.append(fila)

            except Exception as e:
                print(f"  [AVISO] Error línea {idx}: {str(e)[:50]}")
                continue

        print(f"[OK] {len(datos)} líneas enriquecidas")
        return pd.DataFrame(datos)

    def guardar_csv(self, df: pd.DataFrame) -> bool:
        """Guarda DataFrame como CSV"""
        print(f"\n[Guardando] {self.ruta_output}")

        try:
            df.to_csv(self.ruta_output, index=False)
            print(f"[OK] {len(df)} filas guardadas")
            return True
        except Exception as e:
            print(f"[ERROR] {e}")
            return False

    def ejecutar(self) -> pd.DataFrame:
        """Ejecuta extracción completa"""

        if not self.conectar():
            return None

        lines, order_ids = self.extraer_lineas_febrero()
        if not lines:
            return None

        df = self.enriquecer_lineas(lines, order_ids)
        if df.empty:
            return None

        if not self.guardar_csv(df):
            return None

        # Resumen
        print(f"\n{'='*120}")
        print(" EXTRACCION COMPLETADA")
        print(f"{'='*120}")
        print(f"\nFebrero 2026:")
        print(f"  Líneas: {len(df):,}")
        print(f"  Venta total: ${df['Venta bruta'].sum():,.0f}")
        print(f"  Costo total: ${df['Costo Total'].sum():,.0f}")
        print(f"  Margen directo: ${df['Margen Front'].sum():,.0f}")

        return df


# ============================================================================
# EJECUTAR
# ============================================================================

if __name__ == "__main__":
    extractor = ExtraerRawOdooV2()
    df = extractor.ejecutar()

    if df is not None and not df.empty:
        print(f"\n[PROXIMO PASO]")
        print(f"  1. Validar contra Raw ventas Y.xlsx")
        print(f"  2. Inyectar en Análisis Resultado")
        print(f"\nComandos:")
        print(f"  python validar_paso3a_exactitud.py")
        print(f"  python inyectar_raw_analisis_resultado.py")
