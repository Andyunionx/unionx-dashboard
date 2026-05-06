"""
Servicio de extracción de datos de stock desde Odoo
"""
import pandas as pd
from typing import Dict, Callable, Optional
from datetime import datetime

from app.core.odoo_client import OdooClient
from app.services.base_service import BaseOdooService


class StockService(BaseOdooService):
    """
    Extrae datos de stock de Odoo (inventario, movimientos, ubicaciones)
    """

    def extract(self, progress_callback: Optional[Callable] = None) -> Dict:
        """
        Extrae todos los datos de stock.

        Returns:
            Dict con df completo y resúmenes
        """
        def progress(pct, label):
            if progress_callback:
                progress_callback(pct, label)

        print("\n[EXTRACCION STOCK] Iniciando...")

        # PASO 1: Productos
        progress(20, "Extrayendo productos...")
        productos = self._extraer_productos()
        print(f"  [OK] {len(productos):,} productos")

        # PASO 2: Stock por ubicación
        progress(40, "Extrayendo stock por ubicación...")
        stock_ubicacion = self._extraer_stock_ubicacion()
        print(f"  [OK] {len(stock_ubicacion):,} registros de stock")

        # PASO 3: Movimientos recientes
        progress(60, "Extrayendo movimientos...")
        movimientos = self._extraer_movimientos()
        print(f"  [OK] {len(movimientos):,} movimientos")

        # PASO 4: Construir dataset
        progress(80, "Construyendo dataset...")
        df = self._construir_dataset(productos, stock_ubicacion, movimientos)
        print(f"  [OK] {len(df):,} filas")

        # PASO 5: Crear resúmenes
        progress(95, "Creando resúmenes...")
        resumenes = self._crear_resumenes(df)

        progress(100, "Completado")

        return {
            'data': df,
            'resumenes': resumenes,
            'metadata': {
                'total_productos': len(productos),
                'total_stock_registros': len(stock_ubicacion),
                'generado_en': datetime.now().isoformat()
            }
        }

    def apply_filters(self, data: Dict, bodega: str = None, categoria: str = None) -> Dict:
        """Aplica filtros en memoria"""
        df = data['data'].copy()

        if bodega:
            df = df[df['Bodega'] == bodega]
        if categoria:
            df = df[df['Categoría'] == categoria]

        resumenes = self._crear_resumenes(df)

        return {
            'data': df,
            'resumenes': resumenes,
            'metadata': {**data['metadata'], 'filtros_aplicados': {
                'bodega': bodega,
                'categoria': categoria
            }}
        }

    # ========== PASO 1: Productos ==========
    def _extraer_productos(self):
        """Extrae productos con datos básicos"""
        return self.odoo.search_read(
            'product.product',
            [('active', '=', True)],
            {
                'fields': [
                    'id', 'name', 'default_code', 'categ_id',
                    'list_price', 'standard_price', 'qty_available',
                    'incoming_qty', 'outgoing_qty'
                ],
                'limit': 10000
            }
        )

    # ========== PASO 2: Stock por ubicación ==========
    def _extraer_stock_ubicacion(self):
        """Extrae stock por ubicación (bodega)"""
        return self.odoo.search_read(
            'stock.quant',
            [('quantity', '>', 0)],
            {
                'fields': [
                    'id', 'product_id', 'location_id', 'quantity',
                    'reserved_quantity', 'create_date'
                ],
                'limit': 50000
            }
        )

    # ========== PASO 3: Movimientos ==========
    def _extraer_movimientos(self):
        """Extrae últimos 500 movimientos de stock"""
        return self.odoo.search_read(
            'stock.move',
            [('state', '=', 'done')],
            {
                'fields': [
                    'id', 'name', 'product_id', 'location_id',
                    'location_dest_id', 'quantity_done', 'date',
                    'picking_id', 'move_type'
                ],
                'limit': 500
            }
        )

    # ========== PASO 4: Construir dataset ==========
    def _construir_dataset(self, productos: list, stock_ubicacion: list,
                          movimientos: list) -> pd.DataFrame:
        """Construye DataFrame de stock"""
        productos_dict = {p['id']: p for p in productos}

        data = []
        for sq in stock_ubicacion:
            producto_id = sq['product_id'][0] if sq['product_id'] else None
            producto = productos_dict.get(producto_id, {})

            bodega = sq['location_id'][1] if sq['location_id'] else 'Sin ubicación'
            categoria = producto.get('categ_id', [None, ''])[1] if producto.get('categ_id') else 'Sin categoría'

            data.append({
                'SKU': producto.get('default_code', ''),
                'Producto': producto.get('name', ''),
                'Categoría': categoria,
                'Bodega': bodega,
                'Stock Disponible': sq.get('quantity', 0),
                'Stock Reservado': sq.get('reserved_quantity', 0),
                'Precio Venta': producto.get('list_price', 0),
                'Costo': producto.get('standard_price', 0),
                'Valor Total': sq.get('quantity', 0) * producto.get('standard_price', 0),
                'Entrada Pendiente': producto.get('incoming_qty', 0),
                'Salida Pendiente': producto.get('outgoing_qty', 0),
            })

        df = pd.DataFrame(data)
        return df

    # ========== PASO 5: Resúmenes ==========
    def _crear_resumenes(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Crea resúmenes por dimensión"""
        def crear_resumen(df_data, grupo_col, nombre_grupo):
            resumen = df_data.groupby(grupo_col).agg({
                'Stock Disponible': 'sum',
                'Stock Reservado': 'sum',
                'Valor Total': 'sum',
            }).reset_index()

            resumen.columns = [nombre_grupo, 'Stock Total', 'Stock Reservado', 'Valor Total']
            resumen['Stock Libre'] = resumen['Stock Total'] - resumen['Stock Reservado']
            resumen = resumen.sort_values('Valor Total', ascending=False)

            return resumen

        return {
            'bodega': crear_resumen(df, 'Bodega', 'Bodega'),
            'categoria': crear_resumen(df, 'Categoría', 'Categoría'),
        }
