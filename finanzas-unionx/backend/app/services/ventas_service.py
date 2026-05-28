"""
Servicio de extracción y enriquecimiento de datos de ventas.
Refactor del script descargar_reporte_ventas_completo.py.
"""
import pandas as pd
from typing import Dict, Callable, Optional
from datetime import datetime
from pathlib import Path

from app.core.odoo_client import OdooClient
from app.services.base_service import BaseOdooService


class VentasService(BaseOdooService):
    """
    Extrae datos de ventas de Odoo y los enriquece con planillas locales.
    8 pasos secuenciales: órdenes → líneas → productos → facturas → enriquecimiento → métricas → resúmenes
    """

    def __init__(self, odoo_client: OdooClient, planillas_dir: Path):
        super().__init__(odoo_client)
        self.planillas_dir = planillas_dir

    def extract_to_raw_format(self, periodo_inicio: str, periodo_fin: str,
                              progress_callback: Optional[Callable] = None) -> pd.DataFrame:
        """
        Extrae datos de Odoo y los transforma al FORMATO RAW de 40 columnas.

        Este es el nuevo método principal que debe usarse para alimentar el archivo RAW histórico.

        Columnas RAW (40):
        Tipo Movimiento, Bodega, Documento, Fecha Documento, Pedido, Estado Pedido,
        Tipo Despacho, SKU, Canal, Fecha Venta, Hora Venta, Producto,
        Categoría macro, Categoría padre, Categoría hijo, Categoría comercial,
        Estado SKU, Pack, Marca, Proveedor, Tipo Marca, Tipo Compra,
        Tipo Negocio, KAM, Estado Canal, Año venta, Mes venta, Semana venta,
        Día semana, Hora venta, Cantidad, Venta bruta, Costo Unitario, Costo Total,
        Margen Front, Comisión %, Comisión, Logística, Marketing, Mg final

        Returns:
            DataFrame con exactamente 40 columnas en formato RAW
        """
        def progress(pct, label):
            if progress_callback:
                progress_callback(pct, label)

        print(f"\n[EXTRACCION RAW] Período: {periodo_inicio} a {periodo_fin}")

        # PASO 1: Órdenes
        progress(10, "Extrayendo órdenes...")
        ordenes = self._extraer_ordenes(periodo_inicio, periodo_fin)
        orden_ids = [o['id'] for o in ordenes]
        ordenes_dict = {o['id']: o for o in ordenes}
        invoice_ids_all = list({inv_id for o in ordenes for inv_id in (o.get('invoice_ids') or [])})
        print(f"  [OK] {len(ordenes):,} órdenes")

        # PASO 2: Líneas
        progress(20, "Extrayendo líneas de venta...")
        lineas = self._extraer_lineas(orden_ids)
        print(f"  [OK] {len(lineas):,} líneas")

        # PASO 3: Productos
        progress(30, "Extrayendo productos...")
        productos = self._extraer_productos(lineas)
        print(f"  [OK] {len(productos)} productos")

        # PASO 4: Facturas y Notas de Crédito
        progress(40, "Extrayendo facturas y notas de crédito...")
        facturas, totales_netos, ncs, nc_lineas = self._extraer_facturas_y_nc(invoice_ids_all, periodo_inicio, periodo_fin, ordenes=ordenes)
        facturas_dict = {f['id']: f for f in facturas}
        print(f"  [OK] {len(facturas):,} facturas")

        # PASO 4b: Enriquecer productos y sale.order.line con refs de NC (cross-month)
        # Productos referenciados por NC que no estén en productos_dict (NC revierte pedidos
        # de meses anteriores → sus productos pueden no estar cargados).
        prod_ids_nc = {ln['product_id'][0] for ln in nc_lineas if ln.get('product_id')}
        prod_ids_faltantes = list(prod_ids_nc - set(productos.keys()))
        if prod_ids_faltantes:
            print(f"  [INFO] Cargando {len(prod_ids_faltantes)} productos extra de NC cross-month...")
            extras = self.odoo.execute_in_batches(
                'product.product',
                prod_ids_faltantes,
                ['id', 'name', 'default_code', 'qty_available'],
                batch_size=100,
            )
            for p in extras:
                productos[p['id']] = p

        # sale.order.line referenciadas por NC (para purchase_price exacto)
        sale_lines_dict = {ln['id']: ln for ln in lineas}
        sol_ids_nc = set()
        for ln in nc_lineas:
            for sid in (ln.get('sale_line_ids') or []):
                sol_ids_nc.add(sid)
        sol_faltantes = list(sol_ids_nc - set(sale_lines_dict.keys()))
        if sol_faltantes:
            print(f"  [INFO] Cargando {len(sol_faltantes)} sale.order.line extra (NC cross-month)...")
            try:
                extras_sol = self.odoo.execute_in_batches(
                    'sale.order.line',
                    sol_faltantes,
                    ['id', 'name', 'order_id', 'product_id', 'product_uom_qty',
                     'qty_delivered', 'purchase_price', 'price_subtotal', 'price_total'],
                    batch_size=100,
                )
                for sl in extras_sol:
                    sale_lines_dict[sl['id']] = sl
            except Exception as e:
                print(f"  [WARN] Error cargando sale.order.line extra: {str(e)[:100]}")

        # PASO 5: Cargar planillas de enriquecimiento
        progress(50, "Cargando planillas...")
        maestra_canales = self._cargar_maestra_canales()
        matriz_productos = self._cargar_matriz_productos()
        print(f"  [OK] Planillas cargadas")

        # PASO 6: Construir dataset en formato RAW
        progress(60, "Construyendo dataset RAW...")
        df_raw = self._construir_dataset_raw(
            lineas, ordenes_dict, productos, facturas_dict,
            totales_netos, ncs, maestra_canales, matriz_productos,
            nc_lineas=nc_lineas, sale_lines_dict=sale_lines_dict,
        )
        print(f"  [OK] {len(df_raw):,} filas")

        # PASO 7: Enriquecer con datos derivados y cálculos
        progress(80, "Calculando métricas...")
        df_raw = self._calcular_metricas_raw(df_raw)
        print(f"  [OK] Métricas calculadas")

        progress(100, "Completado")
        print(f"\n[SUCCESS] Dataset RAW completado con {len(df_raw):,} líneas\n")

        return df_raw

    def extract(self, periodo_inicio: str, periodo_fin: str,
                progress_callback: Optional[Callable] = None) -> Dict:
        """
        Extrae todos los datos de ventas en un período.

        Args:
            periodo_inicio: Fecha ISO (ej: '2026-04-01 00:00:00')
            periodo_fin: Fecha ISO (ej: '2026-04-30 23:59:59')
            progress_callback: Función para actualizar progreso (progress%, label)

        Returns:
            Dict con df completo y 4 resúmenes
        """
        def progress(pct, label):
            if progress_callback:
                progress_callback(pct, label)

        print(f"\n[EXTRACCION] Período: {periodo_inicio} a {periodo_fin}")

        # PASO 1: Órdenes
        progress(10, "Extrayendo órdenes...")
        ordenes = self._extraer_ordenes(periodo_inicio, periodo_fin)
        orden_ids = [o['id'] for o in ordenes]
        ordenes_dict = {o['id']: o for o in ordenes}
        invoice_ids_all = list({inv_id for o in ordenes for inv_id in (o.get('invoice_ids') or [])})
        print(f"  [OK] {len(ordenes):,} órdenes")

        # PASO 2: Líneas
        progress(25, "Extrayendo líneas de venta...")
        lineas = self._extraer_lineas(orden_ids)
        print(f"  [OK] {len(lineas):,} líneas")

        # PASO 3: Productos
        progress(40, "Extrayendo productos...")
        productos = self._extraer_productos(lineas)
        print(f"  [OK] {len(productos)} productos cargados")

        # PASO 4: Facturas y Notas de Crédito
        progress(55, "Extrayendo facturas y notas de crédito...")
        facturas, totales_netos_por_orden, _ncs, _nc_lineas = self._extraer_facturas_y_nc(invoice_ids_all, periodo_inicio, periodo_fin, ordenes=ordenes)
        facturas_dict = {f['id']: f for f in facturas}
        print(f"  [OK] {len(facturas):,} facturas y NC cargadas")

        # PASO 5: Construir dataset base
        progress(70, "Construyendo dataset...")
        df = self._construir_dataset(lineas, ordenes_dict, productos, facturas_dict, totales_netos_por_orden)
        print(f"  [OK] {len(df):,} filas")

        # PASO 6: Enriquecer
        progress(80, "Enriqueciendo con planillas...")
        df = self._enriquecer_dataset(df)
        print(f"  [OK] Dataset enriquecido")

        # PASO 7: Calcular métricas
        progress(90, "Calculando métricas...")
        df = self._calcular_metricas(df)
        print(f"  [OK] Métricas calculadas")

        # PASO 8: Crear resúmenes
        progress(95, "Creando resúmenes...")
        resumenes = self._crear_resumenes(df)
        print(f"  [OK] Resúmenes creados")

        progress(100, "Completado")

        return {
            'data': df,
            'resumenes': resumenes,
            'metadata': {
                'total_ordenes': len(ordenes),
                'total_lineas': len(df),
                'periodo_inicio': periodo_inicio,
                'periodo_fin': periodo_fin,
                'periodo_nombre': self._nombre_periodo(periodo_inicio, periodo_fin),
                'generado_en': datetime.now().isoformat()
            }
        }

    def apply_filters(self, data: Dict, canal: str = None, categoria: str = None,
                     bodega: str = None) -> Dict:
        """
        Aplica filtros en memoria sin re-query a Odoo.
        Rápido (< 200ms).

        Args:
            data: Data dict del extract()
            canal: Filtro por Canal
            categoria: Filtro por Categoría macro
            bodega: Filtro por Bodega Origen

        Returns:
            Data dict filtrado con KPIs recalculados
        """
        df = data['data'].copy()

        # Aplicar filtros
        if canal:
            df = df[df['Canal'] == canal]
        if categoria:
            df = df[df['Categoría macro'] == categoria]
        if bodega:
            df = df[df['Bodega Origen'] == bodega]

        # Recalcular resúmenes
        resumenes = self._crear_resumenes(df)

        # Calcular KPIs
        kpis = self._calcular_kpis(df)

        return {
            'data': df,
            'resumenes': resumenes,
            'kpis': kpis,
            'metadata': {**data['metadata'], 'filtros_aplicados': {
                'canal': canal,
                'categoria': categoria,
                'bodega': bodega
            }}
        }

    # ========== PASO 1: Órdenes ==========
    def _extraer_ordenes(self, periodo_inicio: str, periodo_fin: str):
        """
        Extrae órdenes confirmadas del período.
        Estrategia: chunkear el rango por días — Odoo SaaS hace timeout
        en el WHERE de date_order incluso con LIMIT bajo si el rango es amplio.
        """
        from datetime import datetime, timedelta

        fmt = '%Y-%m-%d %H:%M:%S'
        d0 = datetime.strptime(periodo_inicio, fmt)
        d1 = datetime.strptime(periodo_fin, fmt)

        fields = [
            'id', 'name', 'date_order', 'partner_id', 'user_id', 'amount_total',
            'margin', 'state', 'fulfillment', 'channel', 'channel_order_reference',
            'client_order_ref', 'invoice_ids', 'warehouse_id', 'yuju_pack_id',
            'website_id'
        ]

        all_orders = []
        cur = d0.replace(hour=0, minute=0, second=0)
        end = d1
        while cur <= end:
            day_end = min(cur.replace(hour=23, minute=59, second=59), end)
            chunk_ini = cur.strftime(fmt)
            chunk_fin = day_end.strftime(fmt)
            page = self.odoo.search_read_paginated(
                'sale.order',
                [
                    ('date_order', '>=', chunk_ini),
                    ('date_order', '<=', chunk_fin),
                    # Incluye 'cancel': pedidos cancelados pueden tener facturas
                    # posted que siguen en libros y el reporte oficial las cuenta.
                    # Las que no tengan factura no generarán filas.
                    ('state', 'in', ['sale', 'done', 'cancel']),
                ],
                fields=fields,
                page_size=200,
            )
            all_orders.extend(page)
            print(f"  [DIA] {cur.strftime('%Y-%m-%d')}: +{len(page)} ordenes (total={len(all_orders)})")
            cur = cur + timedelta(days=1)
            cur = cur.replace(hour=0, minute=0, second=0)

        return all_orders

    # ========== PASO 2: Líneas ==========
    def _extraer_lineas(self, orden_ids: list):
        """Extrae líneas de venta (paginado por chunks de IDs)"""
        # Chunkear los IDs para evitar dominios gigantes
        all_lines = []
        chunk_size = 500
        for i in range(0, len(orden_ids), chunk_size):
            chunk = orden_ids[i:i + chunk_size]
            chunk_lines = self.odoo.search_read_paginated(
                'sale.order.line',
                [('order_id', 'in', chunk)],
                fields=[
                    'id', 'name', 'order_id', 'product_id', 'product_uom_qty',
                    'qty_delivered', 'purchase_price', 'price_subtotal', 'price_total'
                ],
                page_size=1000,
            )
            all_lines.extend(chunk_lines)
        return all_lines

    def _legacy_extraer_lineas_INACTIVO(self, orden_ids: list):
        """[INACTIVO] mantenido para no romper firmas si algo lo importa"""
        return self.odoo.search_read(
            'sale.order.line',
            [('order_id', 'in', orden_ids)],
            {
                'fields': [
                    'id', 'name', 'order_id', 'product_id', 'product_uom_qty',
                    'qty_delivered', 'purchase_price', 'price_subtotal'
                ],
                'limit': 500000
            }
        )

    # ========== PASO 3: Productos ==========
    def _extraer_productos(self, lineas: list):
        """Extrae productos en lotes de 100 (reducido de 500 para evitar timeouts de Odoo)"""
        product_ids = list(set(l['product_id'][0] if l['product_id'] else None for l in lineas if l['product_id']))
        productos_list = self.odoo.execute_in_batches(
            'product.product',
            product_ids,
            ['id', 'name', 'default_code', 'qty_available'],
            batch_size=100
        )
        return {p['id']: p for p in productos_list}

    # ========== PASO 4: Facturas y Notas de Crédito ==========
    def _extraer_facturas_y_nc(self, invoice_ids: list, periodo_inicio: str, periodo_fin: str, ordenes=None):
        """
        Extrae facturas Y notas de crédito.
        Calcula el total NETO por orden: Sum(facturas) - Sum(NC).

        Args:
            ordenes: lista de ordenes (con invoice_ids) para mapeo en memoria

        Returns:
            (facturas_list, totales_netos_por_orden)
            donde totales_netos_por_orden es un dict {orden_id: total_neto}
        """
        if not invoice_ids:
            return [], {}

        # Extraer facturas originales
        print(f"    [INFO] Extrayendo {len(invoice_ids):,} facturas originales...")
        facturas = self.odoo.execute_in_batches(
            'account.move',
            invoice_ids,
            [
                'id', 'name', 'state', 'invoice_date', 'create_date',
                'company_id', 'l10n_latam_document_number', 'move_type',
                'amount_total', 'amount_untaxed', 'partner_id'
            ],
            batch_size=50
        )

        # Extraer todas las NC del período - con manejo de errores
        ncs = []
        try:
            print(f"    [INFO] Buscando notas de crédito del período...")
            nc_domain = [
                ('move_type', '=', 'out_refund'),
                ('invoice_date', '>=', periodo_inicio),
                ('invoice_date', '<=', periodo_fin),
                ('state', '=', 'posted'),
            ]

            # Primero buscar solo IDs (rápido)
            nc_ids = self.odoo.search_read(
                'account.move',
                nc_domain,
                ['id'],
                limit=10000,
            )
            nc_ids = [nc['id'] for nc in nc_ids]

            # Luego leer en lotes de 100
            if nc_ids:
                ncs = self.odoo.execute_in_batches(
                    'account.move',
                    nc_ids,
                    [
                        'id', 'name', 'state', 'invoice_date', 'create_date',
                        'company_id', 'l10n_latam_document_number', 'move_type',
                        'amount_total', 'amount_untaxed',
                        'reversed_entry_id', 'ref', 'partner_id',
                        'invoice_line_ids',
                    ],
                    batch_size=50
                )
        except Exception as e:
            print(f"    [WARN] No se pudieron extraer NC: {str(e)[:100]}")
            print(f"    [WARN] Continuando sin neteado de NC...")
            ncs = []


        # Mapeo de NC por factura original + Extraer facturas originales referenciadas por NC
        nc_por_factura = {}
        factura_orig_ids = []
        for nc in ncs:
            # Intentar obtener la factura original usando reversed_entry_id
            factura_id = None
            if nc.get('reversed_entry_id'):
                factura_id = nc['reversed_entry_id'][0] if isinstance(nc['reversed_entry_id'], (list, tuple)) else nc['reversed_entry_id']
            elif nc.get('reversal_move_id'):
                factura_id = nc['reversal_move_id'][0] if isinstance(nc['reversal_move_id'], (list, tuple)) else nc['reversal_move_id']

            if factura_id:
                if factura_id not in nc_por_factura:
                    nc_por_factura[factura_id] = []
                nc_por_factura[factura_id].append(nc)
                if factura_id not in factura_orig_ids:
                    factura_orig_ids.append(factura_id)

        # Extraer las facturas originales referenciadas por NC (que pueden no estar en invoice_ids)
        facturas_orig_adicionales = []
        if factura_orig_ids:
            # Solo traer IDs que NO están ya en facturas
            facturas_existentes_ids = {f['id'] for f in facturas}
            factura_orig_ids_faltantes = [fid for fid in factura_orig_ids if fid not in facturas_existentes_ids]

            if factura_orig_ids_faltantes:
                print(f"    [INFO] Extrayendo {len(factura_orig_ids_faltantes):,} facturas originales referenciadas por NC...")
                try:
                    facturas_orig_adicionales = self.odoo.execute_in_batches(
                        'account.move',
                        factura_orig_ids_faltantes,
                        [
                            'id', 'name', 'state', 'invoice_date', 'create_date',
                            'company_id', 'l10n_latam_document_number', 'move_type', 'amount_total'
                        ],
                        batch_size=50
                    )
                except Exception as e:
                    print(f"    [WARN] Error extrayendo facturas originales de NC: {str(e)[:100]}")
                    facturas_orig_adicionales = []

        # Agregar facturas adicionales a la lista principal
        facturas.extend(facturas_orig_adicionales)

        # Calcular totales netos por factura
        totales_netos_por_factura = {}
        for factura in facturas:
            factura_id = factura['id']
            # Usar amount_untaxed (sin IVA) para coincidir con price_subtotal de líneas
            amount_factura = factura.get('amount_untaxed', factura.get('amount_total', 0))

            nc_amount = sum(abs(nc.get('amount_untaxed', nc.get('amount_total', 0))) for nc in nc_por_factura.get(factura_id, []))
            totales_netos_por_factura[factura_id] = amount_factura - nc_amount

        # Crear mapeo factura_id → orden_id desde las ordenes en memoria
        factura_a_orden = {}
        if ordenes:
            for orden in ordenes:
                for inv_id in (orden.get('invoice_ids') or []):
                    factura_a_orden[inv_id] = orden['id']

        # Crear mapeo: orden_id → total_neto (sin llamadas extra a Odoo)
        totales_netos_por_orden = {}
        for factura_id, total_neto in totales_netos_por_factura.items():
            orden_id = factura_a_orden.get(factura_id)
            if orden_id:
                totales_netos_por_orden[orden_id] = total_neto

        # Extraer account.move.line de las NCs (para crear filas por SKU en vez de NC agregada)
        nc_line_ids_all = []
        for nc in ncs:
            nc_line_ids_all.extend(nc.get('invoice_line_ids') or [])

        nc_lineas = []
        if nc_line_ids_all:
            print(f"    [INFO] Extrayendo {len(nc_line_ids_all):,} líneas de NC (account.move.line)...")
            try:
                nc_lineas_raw = self.odoo.execute_in_batches(
                    'account.move.line',
                    nc_line_ids_all,
                    [
                        'id', 'move_id', 'product_id', 'quantity',
                        'price_subtotal', 'price_total', 'sale_line_ids',
                        'display_type',
                    ],
                    batch_size=100,
                )
                # Solo líneas de producto (descartar secciones/notas)
                nc_lineas = [
                    ln for ln in nc_lineas_raw
                    if ln.get('display_type') in (False, None, '', 'product')
                ]
            except Exception as e:
                print(f"    [WARN] Error extrayendo líneas NC: {str(e)[:100]}")
                nc_lineas = []

        print(f"    [INFO] Facturas cargadas: {len(facturas)}")
        print(f"    [INFO] Notas de crédito encontradas: {len(ncs)} ({len(nc_lineas)} líneas)")
        print(f"    [INFO] Órdenes con totales netos calculados: {len(totales_netos_por_orden)}")

        # Retornar facturas, totales netos, NCs Y líneas de NC (para detalle por SKU)
        return facturas, totales_netos_por_orden, ncs, nc_lineas

    # ========== PASO 5: Construir dataset ==========
    def _construir_dataset(self, lineas: list, ordenes_dict: dict, productos_dict: dict,
                          facturas_dict: dict, totales_netos: dict) -> pd.DataFrame:
        """
        Construye el DataFrame con 26 campos base.

        IMPORTANTE: Usa el total NETO (facturas - NC) en lugar del amount_total de la orden original.
        Esto asegura que las devoluciones parciales se reflejen correctamente.
        """
        data = []

        for linea in lineas:
            orden_id = linea['order_id'][0] if linea['order_id'] else None
            orden = ordenes_dict.get(orden_id, {})

            producto_id = linea['product_id'][0] if linea['product_id'] else None
            producto = productos_dict.get(producto_id, {})

            # Obtener factura (primera factura de la orden)
            factura = None
            if orden.get('invoice_ids'):
                for inv_id in orden['invoice_ids']:
                    if inv_id in facturas_dict:
                        factura = facturas_dict[inv_id]
                        break

            # Campos de orden
            partner_id = orden.get('partner_id', [None, ''])[1] if orden.get('partner_id') else ''
            user_id = orden.get('user_id', [None, ''])[1] if orden.get('user_id') else ''

            # IMPORTANTE: Usar total NETO (facturas - NC) en lugar del amount_total original
            total_neto = totales_netos.get(orden_id, orden.get('amount_total', 0))

            data.append({
                'Referencia de pedido': orden.get('name', ''),
                'Referencia cliente': orden.get('client_order_ref', ''),
                'Marketplace Reference': orden.get('channel_order_reference', ''),
                'Yuju Pack Id': orden.get('yuju_pack_id', ''),

                'Lineas - Referencia de pedido': linea.get('name', ''),
                'Fecha creacion': orden.get('date_order', ''),
                'Estado': orden.get('state', ''),

                'Cliente': partner_id,
                'Canal': orden.get('channel', ''),
                'Vendedor': user_id,
                'Fulfillment': orden.get('fulfillment', ''),

                'Inventario': orden.get('warehouse_id', [None, ''])[1] if orden.get('warehouse_id') else '',

                'Lineas - Producto': producto.get('name', ''),
                'Lineas - Referencia interna': producto.get('default_code', ''),

                'Lineas - Cantidad': linea.get('product_uom_qty', 0),
                'Lineas - Cantidad real': linea.get('qty_delivered', 0),
                'Lineas - Coste': linea.get('purchase_price', 0),
                'Lineas - Subtotal': linea.get('price_subtotal', 0),

                'Total': total_neto,  # ← NETO (facturas - NC), no amount_total original
                'Margen': orden.get('margin', 0),

                'Facturas - Numero': factura.get('name', '') if factura else '',
                'Facturas - Documento': factura.get('l10n_latam_document_number', '') if factura else '',
                'Facturas - Fecha': factura.get('invoice_date', '') if factura else '',
                'Facturas - Estado': factura.get('state', '') if factura else '',
                'Facturas - Empresa': factura.get('company_id', [None, ''])[1] if factura and factura.get('company_id') else '',
                'Facturas - Creado en': factura.get('create_date', '') if factura else '',
            })

        df = pd.DataFrame(data)
        return df

    # ========== PASO 6: Enriquecer ==========
    def _enriquecer_dataset(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Enriquece con planillas locales:
        - Maestra Canales → Tipo Negocio, Línea de Negocio
        - Matriz Productos → Categorías
        - Mockup raw Y → Comisiones y Logística
        """
        # Maestra Canales
        try:
            maestra = pd.read_excel(self.planillas_dir / 'Maestra Canales.xlsx')
            maestra_cols = maestra.columns.tolist()

            if 'Cliente' in maestra_cols and 'Tipo Negocio' in maestra_cols:
                df = df.merge(
                    maestra[['Cliente', 'Tipo Negocio', 'Linea de Negocio']],
                    on='Cliente',
                    how='left'
                )
        except Exception as e:
            print(f"[WARN] No se pudo cargar Maestra Canales: {e}")
            df['Tipo Negocio'] = ''
            df['Linea de Negocio'] = ''

        # Matriz Productos (categorías)
        try:
            matriz = pd.read_excel(self.planillas_dir / 'Matriz productos.xlsx', sheet_name='Productos')
            if 'Referencia interna' in matriz.columns:
                cols_cat = [c for c in matriz.columns if 'Categoría' in c]
                df = df.merge(
                    matriz[['Referencia interna'] + cols_cat],
                    left_on='Lineas - Referencia interna',
                    right_on='Referencia interna',
                    how='left'
                )
        except Exception as e:
            print(f"[WARN] No se pudo cargar Matriz productos: {e}")
            df['Categoría macro'] = ''
            df['Categoría padre'] = ''
            df['Categoría hijo'] = ''
            df['Categoría comercial'] = ''

        # Mockup raw Y (comisiones y logística)
        try:
            mockup = pd.read_excel(self.planillas_dir / 'Mockup raw Y.xlsx')
            # Comisión y Logística se mapean por Canal + Producto
            # Para simplificar, agregamos columnas vacías que se llenarán después
            df['Comisión %'] = 0
            df['Comisión $ (Mkpl)'] = 0
            df['Logística $ (Mkpl)'] = 0
        except Exception as e:
            print(f"[WARN] No se pudo cargar Mockup raw Y: {e}")
            df['Comisión %'] = 0
            df['Comisión $ (Mkpl)'] = 0
            df['Logística $ (Mkpl)'] = 0

        # Bodega Origen (from Inventario)
        df['Bodega Origen'] = df['Inventario'].apply(
            lambda x: 'Fulfillment' if 'fulfillment' in str(x).lower() else
                      'Warehouse Unionx' if 'unionx' in str(x).lower() or 'warehouse' in str(x).lower() else
                      (x if x else 'Sin bodega')
        )

        # Estandarizar canal "Web" con prefijos
        df['Canal'] = df.apply(self._estandarizar_canal, axis=1)

        return df

    @staticmethod
    def _estandarizar_canal(row):
        """Estandariza canal: Web → Lhotse/Simplit/UnionX según prefijo"""
        canal = row.get('Canal', '')
        if canal == 'Web':
            ref = str(row.get('Marketplace Reference', '')).upper()
            if ref.startswith('LH'):
                return 'Lhotse web'
            elif ref.startswith('SH'):
                return 'Simplit web'
            else:
                return 'UnionX web'
        return canal if canal else 'Sin canal'

    # ========== PASO 7: Calcular métricas ==========
    def _calcular_metricas(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula Costo Total, Margen Directo, Margen Final"""
        df['Lineas - Coste'] = pd.to_numeric(df['Lineas - Coste'], errors='coerce').fillna(0)
        df['Lineas - Cantidad'] = pd.to_numeric(df['Lineas - Cantidad'], errors='coerce').fillna(0)
        df['Total'] = pd.to_numeric(df['Total'], errors='coerce').fillna(0)
        df['Comisión $ (Mkpl)'] = pd.to_numeric(df['Comisión $ (Mkpl)'], errors='coerce').fillna(0)
        df['Logística $ (Mkpl)'] = pd.to_numeric(df['Logística $ (Mkpl)'], errors='coerce').fillna(0)

        df['Costo Total'] = df['Lineas - Coste'] * df['Lineas - Cantidad']
        df['Margen Directo'] = df['Total'] - df['Costo Total']
        df['Margen Final'] = df['Margen Directo'] - df['Comisión $ (Mkpl)'] - df['Logística $ (Mkpl)']

        return df

    # ========== PASO 8: Crear resúmenes ==========
    def _crear_resumenes(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Crea 4 resúmenes por Línea, Canal, Categoría, Bodega"""
        def crear_resumen(df_data, grupo_col, nombre_grupo):
            resumen = df_data.groupby(grupo_col).agg({
                'Total': 'sum',
                'Costo Total': 'sum',
                'Margen Directo': 'sum',
                'Comisión $ (Mkpl)': 'sum',
                'Logística $ (Mkpl)': 'sum',
                'Margen Final': 'sum'
            }).reset_index()

            resumen.columns = [nombre_grupo, 'Venta Neta', 'Costo', 'Margen Directo', 'Comisión', 'Logística', 'Margen Final']
            resumen['% Margen Final'] = (resumen['Margen Final'] / resumen['Venta Neta'] * 100).round(1)

            return resumen.sort_values('Venta Neta', ascending=False)

        return {
            'linea': crear_resumen(df, 'Linea de Negocio', 'Línea de Negocio'),
            'canal': crear_resumen(df, 'Canal', 'Canal'),
            'categoria': crear_resumen(df, 'Categoría macro', 'Categoría'),
            'bodega': crear_resumen(df, 'Bodega Origen', 'Bodega'),
        }

    # ========== Helper: KPIs ==========
    @staticmethod
    def _calcular_kpis(df: pd.DataFrame) -> Dict:
        """Calcula KPIs agregados"""
        return {
            'venta_neta': float(df['Total'].sum()),
            'costo_total': float(df['Costo Total'].sum()),
            'margen_directo': float(df['Margen Directo'].sum()),
            'margen_final': float(df['Margen Final'].sum()),
            'pct_margen_final': float((df['Margen Final'].sum() / df['Total'].sum() * 100).round(1)) if df['Total'].sum() > 0 else 0,
            'total_ordenes': int(df['Referencia de pedido'].nunique()),
            'total_lineas': len(df),
        }

    def _cargar_maestra_canales(self) -> pd.DataFrame:
        """Carga la Maestra Canales para enriquecimiento"""
        try:
            return pd.read_excel(self.planillas_dir / 'Maestra Canales.xlsx')
        except Exception as e:
            print(f"[WARN] No se pudo cargar Maestra Canales: {e}")
            return pd.DataFrame()

    def _cargar_canal_tipo_negocio(self) -> dict:
        """Carga mapping Canal → {tipo_negocio, kam} extraído del histórico."""
        import json
        try:
            f = self.planillas_dir / 'canal_tipo_negocio.json'
            if f.exists():
                return json.loads(f.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"[WARN] No se pudo cargar canal_tipo_negocio.json: {e}")
        return {}

    def _cargar_matriz_productos(self) -> pd.DataFrame:
        """Carga la Matriz de Productos para categorías y atributos"""
        try:
            return pd.read_excel(self.planillas_dir / 'Matriz productos.xlsx', sheet_name='Productos')
        except Exception as e:
            print(f"[WARN] No se pudo cargar Matriz productos: {e}")
            return pd.DataFrame()

    def _construir_dataset_raw(self, lineas: list, ordenes_dict: dict, productos_dict: dict,
                              facturas_dict: dict, totales_netos: dict, ncs: list,
                              maestra_canales: pd.DataFrame, matriz_productos: pd.DataFrame,
                              nc_lineas: list = None, sale_lines_dict: dict = None) -> pd.DataFrame:
        """
        Construye el DataFrame en FORMATO RAW exacto (40 columnas).

        Mapeo de Odoo a RAW:
        - Tipo Movimiento: 'Venta' (líneas de venta) o 'Nota de Crédito' (NC)
        - Bodega: warehouse_id.name
        - Documento: Factura number (o NC number para NC)
        - Fecha Documento: invoice_date
        - Pedido: order name
        - Estado Pedido: order state
        - Tipo Despacho: picking_type (si existe)
        - SKU: product default_code
        - Canal: order channel
        - Fecha Venta: order date_order (date part)
        - Hora Venta: order date_order (time part)
        - Producto: product name
        - Categorías: from Matriz Productos
        - Estado SKU: product status
        - Pack: product is_pack (si existe)
        - Marca: product manufacturer (si existe)
        - Proveedor: supplier info (si existe)
        - Tipo Marca: brand type (si existe)
        - Tipo Compra: purchase type (si existe)
        - Tipo Negocio: from Maestra Canales
        - KAM: key account manager (si existe)
        - Estado Canal: channel status (si existe)
        - Año/Mes/Semana/Día venta: calculated from date_order
        - Cantidad: product_uom_qty
        - Venta bruta: monto total (positivo para ventas, NEGATIVO para NC)
        - Costo Unitario: purchase_price
        - Costo Total: purchase_price * qty (negativo para NC)
        - Margen Front: venta bruta - costo total
        - Comisión %: from Mockup raw Y
        - Comisión: commission amount (negativo para NC)
        - Logística: logistics cost (negativo para NC)
        - Marketing: marketing cost (negativo para NC)
        - Mg final: Margen Front - Comisión - Logística - Marketing (negativo para NC)

        IMPORTANTE: Las notas de crédito aparecen como líneas SEPARADAS con signos NEGATIVOS
        para auditoría y trazabilidad, NO neteadas en la venta original.
        """
        data = []

        # Mapeo Canal → {tipo_negocio, kam} extraído del histórico
        canal_a_tn = self._cargar_canal_tipo_negocio()

        # Diccionario de lookup Empresa(cliente) -> Canal estandarizado
        empresa_a_canal = {}
        if not maestra_canales.empty and {'Empresa', 'Canal'}.issubset(maestra_canales.columns):
            for _, row in maestra_canales.iterrows():
                emp = str(row['Empresa']).strip().lower()
                can = str(row['Canal']).strip()
                if emp and can and emp != 'nan' and can != 'nan':
                    empresa_a_canal[emp] = can

        def _normalizar_canal_chile(c: str) -> str:
            """Quita sufijo ' Chile', prefijo 'Mercado ' y normaliza casos especiales."""
            if not c:
                return c
            cn = str(c).strip()
            cnl = cn.lower()
            if cnl.endswith(' chile'):
                cn = cn[:-6].strip()
                cnl = cn.lower()
            if cnl.startswith('mercado ') and 'libre' not in cnl:
                cn = cn[len('Mercado '):].strip()
            # Normalizaciones de capitalización para match con reporte oficial
            normaliza = {
                'sp digital': 'SP Digital',
            }
            return normaliza.get(cn.lower(), cn)

        def _resolver_canal(partner_name: str, channel_raw: str, channel_ref: str,
                            website_name: str = '') -> str:
            """
            Resuelve el canal estandarizado:
              0. website_id == 'UnionX B2b' (o similar) → 'UnionX B2B' (override)
              1. Lookup cliente (partner_id.name) en Maestra Canales
              2. Si el resultado (o el channel_raw) es 'Web', subdividir por channel_ref
                 (LH→Lhotse web, SH→Simplit web, otro→UnionX web)
              3. Fallback: channel_raw normalizado (quita 'Chile' y 'Mercado ')
            """
            # 0. Override B2B
            if website_name and 'b2b' in str(website_name).lower():
                return 'UnionX B2B'

            canal = ''
            if partner_name:
                key = str(partner_name).strip().lower()
                if key in empresa_a_canal:
                    canal = empresa_a_canal[key]
            if not canal:
                canal = (channel_raw or '').strip()
            # Si quedó 'Web' (de Maestra o de Odoo), subdividir por channel_ref
            if canal == 'Web':
                ref = str(channel_ref or '').upper()
                if ref.startswith('LH'):
                    return 'Lhotse web'
                if ref.startswith('SH'):
                    return 'Simplit web'
                return 'UnionX web'
            return _normalizar_canal_chile(canal)

        for linea in lineas:
            orden_id = linea['order_id'][0] if linea['order_id'] else None
            orden = ordenes_dict.get(orden_id, {})

            producto_id = linea['product_id'][0] if linea['product_id'] else None
            producto = productos_dict.get(producto_id, {})

            # FIX: filtrar bodega 'El Volcán' (defensa en profundidad — históricamente
            # se llamaba así, hoy la bodega ya no tiene "volcán" en el nombre pero
            # el filtro real efectivo está más abajo por canal_raw)
            bodega_nombre = orden.get('warehouse_id', [None, ''])[1] if orden.get('warehouse_id') else ''
            if 'volcán' in (bodega_nombre or '').lower() or 'volcan' in (bodega_nombre or '').lower():
                continue

            # Obtener TODAS las facturas POSTED asociadas (FAC + BEL si aplica).
            # No invoice posted ⇒ no fila (descarta pedidos 'cancel' sin facturas reales).
            facturas_orden = []
            if orden.get('invoice_ids'):
                for inv_id in orden['invoice_ids']:
                    f = facturas_dict.get(inv_id)
                    if f and f.get('state') == 'posted' and f.get('move_type') == 'out_invoice':
                        facturas_orden.append(f)
            if not facturas_orden:
                # Para pedidos en sale/done sin factura aún (ej. pendientes de facturar),
                # generar UNA fila placeholder. Para pedidos 'cancel' sin factura, skip.
                if orden.get('state') == 'cancel':
                    continue
                facturas_orden = [None]

            # Parsear fechas
            fecha_venta = orden.get('date_order', '')
            fecha_dt = pd.to_datetime(fecha_venta) if fecha_venta else pd.NaT
            hora_venta = fecha_dt.strftime('%H:%M:%S') if pd.notna(fecha_dt) else ''
            hora_venta_num = int(fecha_dt.hour) if pd.notna(fecha_dt) else 0

            # Línea: separar bruto (con IVA) y neto (sin IVA)
            # price_subtotal = sin IVA (neto), price_total = con IVA (bruto)
            venta_neta_pre_nc = linea.get('price_subtotal', 0)
            venta_bruta_pre_nc = linea.get('price_total', venta_neta_pre_nc * 1.19)
            venta_bruta = venta_neta_pre_nc  # mantenemos nombre interno = neto para cálculos margen

            # Cantidades
            cantidad = linea.get('product_uom_qty', 0)
            costo_unitario = linea.get('purchase_price', 0)
            costo_total = costo_unitario * cantidad

            # Márgenes (basados en venta bruta, sin NC)
            margen_front = venta_bruta - costo_total
            comision = linea.get('comision', 0)  # si existe en el modelo
            logistica = linea.get('logistica', 0)  # si existe en el modelo
            marketing = linea.get('marketing', 0)  # si existe en el modelo
            mg_final = margen_front - comision - logistica - marketing

            # Comisión %
            comision_pct = (comision / venta_bruta * 100) if venta_bruta > 0 else 0

            # Tipo Negocio + KAM se resuelven después por canal estandarizado
            tipo_negocio = ''
            kam = ''

            # Enriquecimiento con Matriz Productos
            sku = producto.get('default_code', '')
            categoria_macro = ''
            categoria_padre = ''
            categoria_hijo = ''
            categoria_comercial = ''
            marca_matriz = ''
            proveedor_matriz = ''
            pack_matriz = ''
            estado_sku_matriz = ''
            tipo_marca_matriz = ''

            if not matriz_productos.empty and sku:
                sku_col = 'SKU' if 'SKU' in matriz_productos.columns else 'Referencia interna'
                # Normalizar SKU para que match int/str
                matriz_sku_str = matriz_productos[sku_col].astype(str).str.strip()
                match = matriz_productos[matriz_sku_str == str(sku).strip()]
                if not match.empty:
                    row = match.iloc[0]
                    for col in matriz_productos.columns:
                        c_lower = col.lower()
                        v = row.get(col, '')
                        if pd.isna(v): v = ''
                        if 'macro' in c_lower:
                            categoria_macro = v
                        elif 'padre' in c_lower and 'macro' not in c_lower:
                            categoria_padre = v
                        elif 'hijo' in c_lower:
                            categoria_hijo = v
                        elif 'comercial' in c_lower:
                            categoria_comercial = v
                        elif col == 'Marca':
                            marca_matriz = v
                        elif col == 'Proveedor':
                            proveedor_matriz = v
                        elif col == 'Pack':
                            pack_matriz = v
                        elif col == 'In/out':
                            estado_sku_matriz = v
                        elif col == 'Estado marca':
                            # Tipo Marca = Estado marca (In/Out)
                            tipo_marca_matriz = v

            # Resolver canal (B2B website -> cliente Maestra -> fallback channel_raw)
            partner_name = orden.get('partner_id', [None, ''])[1] if orden.get('partner_id') else ''
            channel_raw_odoo = orden.get('channel', '') or ''
            channel_ref_odoo = orden.get('channel_order_reference', '') or ''
            website_name = ''
            if orden.get('website_id'):
                w = orden['website_id']
                website_name = w[1] if isinstance(w, (list, tuple)) and len(w) > 1 else str(w)
            canal_raw = _resolver_canal(partner_name, channel_raw_odoo, channel_ref_odoo, website_name)

            # Fusión de canales con variantes de capitalización (Drive y Odoo difieren)
            CANAL_CANONICO = {
                'sp digital': 'SP Digital',
                'exporunning': 'ExpoRunning',
            }
            if canal_raw:
                key = canal_raw.strip().lower()
                if key in CANAL_CANONICO:
                    canal_raw = CANAL_CANONICO[key]

            # FIX: filtrar canales que se cargan manualmente (offline) — no traer de Odoo
            # El Volcán: SIEMPRE excluir. Es bodega de consignación; las ventas se cargan
            # a mano (canal aparece como "El Volcan"/"El Volcán" en Odoo). Stock sí se
            # contabiliza en otros módulos (es consignación nuestra).
            canal_norm = (canal_raw or '').strip().lower().replace('á', 'a')
            if canal_norm == 'el volcan':
                continue
            # SAWA: solo excluir abril 2026 (cargado manual). Mayo en adelante sí auto-sync.
            if canal_raw in ('Sawa', 'sawa', 'SAWA'):
                fecha_venta_str = str(orden.get('date_order', ''))[:10]  # YYYY-MM-DD
                if '2026-04-01' <= fecha_venta_str <= '2026-04-30':
                    continue  # abril 2026: no traer

            # Resolver Tipo Negocio + KAM por canal (lookup en mapping del histórico)
            tn_info = canal_a_tn.get(canal_raw, {})
            tipo_negocio = tn_info.get('tipo_negocio', '') or tipo_negocio
            kam = tn_info.get('kam', '') or kam

            # Generar UNA fila por cada factura asociada al pedido (FAC + BEL si aplica)
            for factura in facturas_orden:
                # Aplicar neteo si esta factura tiene NC
                venta_neta_post_nc = venta_neta_pre_nc       # sin IVA, post-NC
                venta_bruta_post_nc = venta_bruta_pre_nc     # con IVA, post-NC
                if factura and factura.get('id') in totales_netos:
                    factura_id = factura['id']
                    total_neto_factura = totales_netos[factura_id]
                    if venta_neta_pre_nc > 0:
                        fact_total_neto = factura.get('amount_untaxed', factura.get('amount_total', venta_neta_pre_nc))
                        if fact_total_neto > 0:
                            ratio = total_neto_factura / fact_total_neto
                            venta_neta_post_nc = venta_neta_pre_nc * ratio
                            venta_bruta_post_nc = venta_bruta_pre_nc * ratio
                # Variables para cálculos margen (basados en NETO, no IVA)
                venta_neta = venta_neta_post_nc

                data.append({
                    'Tipo Movimiento': 'Venta',
                    'Bodega': bodega_nombre,
                    'Documento': factura.get('name', '') if factura else '',
                    'Fecha Documento': factura.get('invoice_date', '') if factura else '',
                    'Pedido': orden.get('name', ''),
                    'Pedido Marketplace': orden.get('channel_order_reference', '') or '',
                    'Ref Cliente': orden.get('client_order_ref', '') or '',
                    'Estado Pedido': orden.get('state', ''),
                    'Tipo Despacho': '',
                    'SKU': sku,
                    'Canal': canal_raw,
                    'Fecha Venta': fecha_venta.split(' ')[0] if fecha_venta else '',
                    'Hora Venta': hora_venta,
                    'Producto': producto.get('name', ''),
                    'Categoría macro': categoria_macro,
                    'Categoría padre': categoria_padre,
                    'Categoría hijo': categoria_hijo,
                    'Categoría comercial': categoria_comercial,
                    'Estado SKU': estado_sku_matriz,
                    'Pack': pack_matriz,
                    'Marca': marca_matriz or (producto.get('manufacturer_id', [None, ''])[1] if producto.get('manufacturer_id') else ''),
                    'Proveedor': proveedor_matriz,
                    'Tipo Marca': tipo_marca_matriz,
                    'Tipo Compra': '',
                    'Tipo Negocio': tipo_negocio,
                    'KAM': kam,
                    'Estado Canal': '',
                    'Año venta': fecha_dt.year if pd.notna(fecha_dt) else '',
                    'Mes venta': fecha_dt.month if pd.notna(fecha_dt) else '',
                    'Semana venta': fecha_dt.isocalendar()[1] if pd.notna(fecha_dt) else '',
                    'Día semana': fecha_dt.dayofweek if pd.notna(fecha_dt) else '',
                    'Hora venta': hora_venta_num,  # int hora del día (0-23)
                    'Cantidad': cantidad,
                    'Venta bruta': venta_bruta_post_nc,   # CON IVA (compatible histórico)
                    'Venta Neta': venta_neta_post_nc,     # SIN IVA
                    'Costo Unitario': costo_unitario,
                    'Costo Total': costo_total,
                    'Margen Front': venta_neta - costo_total,   # vs neta
                    'Comision %': comision_pct,
                    'Comisión': comision,
                    'Logística': logistica,
                    'Marketing': marketing,
                    'Mg final': mg_final
                })

        df = pd.DataFrame(data)

        # Helper: lookup de matriz productos por SKU (mismo formato que el bloque de ventas)
        def _matriz_lookup(sku_val):
            out = {
                'categoria_macro': '', 'categoria_padre': '', 'categoria_hijo': '',
                'categoria_comercial': '', 'marca': '', 'proveedor': '',
                'pack': '', 'estado_sku': '', 'tipo_marca': '',
            }
            if matriz_productos.empty or not sku_val:
                return out
            sku_col = 'SKU' if 'SKU' in matriz_productos.columns else 'Referencia interna'
            matriz_sku_str = matriz_productos[sku_col].astype(str).str.strip()
            match = matriz_productos[matriz_sku_str == str(sku_val).strip()]
            if match.empty:
                return out
            row = match.iloc[0]
            for col in matriz_productos.columns:
                c_lower = col.lower()
                v = row.get(col, '')
                if pd.isna(v): v = ''
                if 'macro' in c_lower:
                    out['categoria_macro'] = v
                elif 'padre' in c_lower and 'macro' not in c_lower:
                    out['categoria_padre'] = v
                elif 'hijo' in c_lower:
                    out['categoria_hijo'] = v
                elif 'comercial' in c_lower:
                    out['categoria_comercial'] = v
                elif col == 'Marca':
                    out['marca'] = v
                elif col == 'Proveedor':
                    out['proveedor'] = v
                elif col == 'Pack':
                    out['pack'] = v
                elif col == 'In/out':
                    out['estado_sku'] = v
                elif col == 'Estado marca':
                    out['tipo_marca'] = v
            return out

        # Indexar líneas NC por move_id (NC id) para lookup rápido
        nc_lineas_by_move = {}
        if nc_lineas:
            for nl in nc_lineas:
                mid = nl['move_id'][0] if nl.get('move_id') else None
                if mid is None:
                    continue
                nc_lineas_by_move.setdefault(mid, []).append(nl)
        if sale_lines_dict is None:
            sale_lines_dict = {ln['id']: ln for ln in lineas}

        # AGREGAR LÍNEAS SEPARADAS PARA NOTAS DE CRÉDITO (una fila por SKU devuelto)
        # Si la NC tiene invoice_line_ids → una fila por línea con SKU/marca/costo exactos.
        # Si no tiene líneas (fallback) → una fila agregada con costo proporcional (legacy).
        if ncs:
            nc_data = []

            for nc in ncs:
                    nc_id = nc.get('id')
                    # Usar monto sin IVA para que matchee con price_subtotal de las líneas
                    nc_amount = nc.get('amount_untaxed', nc.get('amount_total', 0))

                    # Obtener la factura original que revierte esta NC
                    factura_orig_id = None
                    if nc.get('reversed_entry_id'):
                        factura_orig_id = nc['reversed_entry_id'][0] if isinstance(nc['reversed_entry_id'], (list, tuple)) else nc['reversed_entry_id']
                    elif nc.get('reversal_move_id'):
                        factura_orig_id = nc['reversal_move_id'][0] if isinstance(nc['reversal_move_id'], (list, tuple)) else nc['reversal_move_id']

                    factura_orig = facturas_dict.get(factura_orig_id) if factura_orig_id else None

                    # Obtener la orden asociada a la factura original
                    orden_orig = None
                    if factura_orig:
                        for orden in ordenes_dict.values():
                            if factura_orig_id in (orden.get('invoice_ids') or []):
                                orden_orig = orden
                                break

                    if factura_orig:  # Crear línea NC incluso sin orden asociada
                        # Si no tenemos la orden, usar datos de la factura original
                        if not orden_orig:
                            # Crear un objeto "orden" ficticio basado en la factura.
                            # channel vacío para que el fallback FAC/BEL/Ajustes (más abajo)
                            # pueda decidir el canal correcto.
                            orden_orig = {
                                'name': f"Factura {factura_orig.get('name', '')}",
                                'channel': '',
                                'state': 'sale',
                                'warehouse_id': [None, 'Bodega Central'],
                            }

                        # Parsear fechas de la NC
                        fecha_nc = nc.get('invoice_date', '')
                        fecha_dt = pd.to_datetime(fecha_nc) if fecha_nc else pd.NaT
                        hora_nc = fecha_dt.strftime('%H:%M:%S') if pd.notna(fecha_dt) else ''
                        hora_nc_num = int(fecha_dt.hour) if pd.notna(fecha_dt) else 0

                        # ════════════════════════════════════════════════════════════
                        # RESOLUCIÓN DE CANAL PARA NCs (skill embebida 26-may-2026)
                        # ════════════════════════════════════════════════════════════
                        # Orden de intentos (de más específico a más genérico):
                        #
                        # 1. Partner del SO original → Maestra Canales (caso normal)
                        # 2. Partner de la NC misma → Maestra Canales
                        # 3. Partner de la factura original → Maestra Canales
                        # 4. Heurística por tipo de documento contable:
                        #    - FAC*  → "UnionX B2B"  (facturas = B2B típico)
                        #    - BEL*  → "UnionX web"  (boletas = B2C web)
                        # 5. Fallback final → "Ajustes contables" (NO "NC sin orden")
                        #
                        # Esto resuelve el caso de NCs huérfanas (sin partner mapeado).
                        # Antes esas filas quedaban con canal="NC sin orden" sin TN/KAM
                        # → distorsionaba reportes por canal.
                        # ════════════════════════════════════════════════════════════
                        partner_nc = ''
                        if orden_orig and orden_orig.get('partner_id'):
                            partner_nc = orden_orig['partner_id'][1] if isinstance(orden_orig['partner_id'], (list, tuple)) else ''
                        if not partner_nc and nc.get('partner_id'):
                            partner_nc = nc['partner_id'][1] if isinstance(nc['partner_id'], (list, tuple)) else ''
                        if not partner_nc and factura_orig and factura_orig.get('partner_id'):
                            partner_nc = factura_orig['partner_id'][1] if isinstance(factura_orig['partner_id'], (list, tuple)) else ''
                        canal_nc = _resolver_canal(
                            partner_nc,
                            (orden_orig.get('channel') if orden_orig else '') or '',
                            (orden_orig.get('channel_order_reference') if orden_orig else '') or ''
                        )

                        # Fallback por tipo de documento contable (FAC vs BEL).
                        # También cubrir el string legacy "NC sin orden" por si quedó
                        # cacheado en alguna ruta.
                        if not canal_nc or canal_nc == 'NC sin orden':
                            doc_name = (factura_orig.get('name', '') if factura_orig else '').upper()
                            if doc_name.startswith('FAC'):
                                canal_nc = 'UnionX B2B'
                            elif doc_name.startswith('BEL'):
                                canal_nc = 'UnionX web'
                            else:
                                canal_nc = 'Ajustes contables'

                        # Tipo Negocio + KAM para NC
                        tn_info_nc = canal_a_tn.get(canal_nc, {})
                        tipo_negocio_nc = tn_info_nc.get('tipo_negocio', '')
                        kam_nc = tn_info_nc.get('kam', '')

                        # Si el canal es fallback "Ajustes contables", asignar TN explícito
                        if canal_nc == 'Ajustes contables' and not tipo_negocio_nc:
                            tipo_negocio_nc = 'Ajustes contables'

                        # FIX MARGEN NC: aplicar costo proporcional de la factura original.
                        # Mg de devolución = -venta_neta + costo_proporcional
                        # Estimamos costo proporcional usando el % margen de la orden original:
                        # - factura_total = monto factura
                        # - costo_total_orden = SUM(costo_total) de líneas de la orden
                        # - ratio_costo = costo_total_orden / factura_total
                        # - costo_nc_proporcional = abs(nc_amount) * ratio_costo
                        nc_amount_abs = abs(nc_amount)  # sin IVA (amount_untaxed)
                        nc_amount_bruto_abs = abs(nc.get('amount_total', nc_amount * 1.19))  # con IVA
                        costo_nc = 0
                        if orden_orig and orden_orig.get('id') and factura_orig:
                            orden_id_orig = orden_orig['id']
                            factura_total = factura_orig.get('amount_untaxed', factura_orig.get('amount_total', 0)) or 0
                            # Sumar costos de líneas de la orden original
                            costo_orden = 0
                            for ln in lineas:
                                ord_id_ln = ln['order_id'][0] if ln.get('order_id') else None
                                if ord_id_ln == orden_id_orig:
                                    qty = ln.get('product_uom_qty', 0) or 0
                                    pp = ln.get('purchase_price', 0) or 0
                                    costo_orden += qty * pp
                            if factura_total > 0:
                                ratio = costo_orden / factura_total
                                costo_nc = nc_amount_abs * ratio

                        # margen NC = venta_neta - costo_total = (-nc_amount) - (-costo_nc) = -nc_amount + costo_nc
                        margen_nc = -nc_amount_abs + costo_nc

                        bodega_nc = orden_orig.get('warehouse_id', [None, ''])[1] if orden_orig.get('warehouse_id') else ''
                        pedido_nc = orden_orig.get('name', '')
                        estado_ped_nc = orden_orig.get('state', '')
                        anio_nc = fecha_dt.year if pd.notna(fecha_dt) else ''
                        mes_nc = fecha_dt.month if pd.notna(fecha_dt) else ''
                        sem_nc = fecha_dt.isocalendar()[1] if pd.notna(fecha_dt) else ''
                        dia_nc = fecha_dt.dayofweek if pd.notna(fecha_dt) else ''
                        fecha_v_nc = fecha_nc.split(' ')[0] if fecha_nc else ''

                        lineas_nc = nc_lineas_by_move.get(nc_id, []) if nc_id else []

                        if lineas_nc:
                            # B1: una fila por línea de la NC, con SKU/marca/categoría reales
                            # y costo exacto del sale.order.line original.
                            for nl in lineas_nc:
                                prod_id_nc = nl['product_id'][0] if nl.get('product_id') else None
                                producto_nc = productos_dict.get(prod_id_nc, {}) if prod_id_nc else {}
                                sku_nc = producto_nc.get('default_code', '') or ''
                                prod_nombre_nc = producto_nc.get('name', '') or ''

                                m = _matriz_lookup(sku_nc)

                                # purchase_price del sale.order.line original (costo congelado al momento de venta)
                                costo_unit_nc = 0
                                for sid in (nl.get('sale_line_ids') or []):
                                    sl = sale_lines_dict.get(sid)
                                    if sl and sl.get('purchase_price'):
                                        costo_unit_nc = sl['purchase_price']
                                        break

                                qty_nc = nl.get('quantity', 0) or 0
                                venta_neta_ln = -(nl.get('price_subtotal', 0) or 0)
                                venta_bruta_ln = -(nl.get('price_total', 0) or (nl.get('price_subtotal', 0) or 0) * 1.19)
                                costo_total_ln = -(costo_unit_nc * qty_nc)
                                margen_ln = venta_neta_ln - costo_total_ln  # = -venta + costo recuperado

                                nc_data.append({
                                    'Tipo Movimiento': 'Devolución',
                                    'Bodega': bodega_nc,
                                    'Documento': nc.get('name', ''),
                                    'Fecha Documento': fecha_nc,
                                    'Pedido': pedido_nc,
                                    'Pedido Marketplace': orden_orig.get('channel_order_reference', '') or '',
                                    'Ref Cliente': orden_orig.get('client_order_ref', '') or '',
                                    'Estado Pedido': estado_ped_nc,
                                    'Tipo Despacho': '',
                                    'SKU': sku_nc,
                                    'Canal': canal_nc,
                                    'Fecha Venta': fecha_v_nc,
                                    'Hora Venta': hora_nc,
                                    'Producto': prod_nombre_nc or f"Nota de Crédito de {factura_orig.get('name', 'Factura')}",
                                    'Categoría macro': m['categoria_macro'],
                                    'Categoría padre': m['categoria_padre'],
                                    'Categoría hijo': m['categoria_hijo'],
                                    'Categoría comercial': m['categoria_comercial'],
                                    'Estado SKU': m['estado_sku'],
                                    'Pack': m['pack'],
                                    'Marca': m['marca'],
                                    'Proveedor': m['proveedor'],
                                    'Tipo Marca': m['tipo_marca'],
                                    'Tipo Compra': '',
                                    'Tipo Negocio': tipo_negocio_nc,
                                    'KAM': kam_nc,
                                    'Estado Canal': '',
                                    'Año venta': anio_nc,
                                    'Mes venta': mes_nc,
                                    'Semana venta': sem_nc,
                                    'Día semana': dia_nc,
                                    'Hora venta': hora_nc_num,
                                    'Cantidad': -qty_nc,  # NEGATIVO: cantidad devuelta
                                    'Venta bruta': venta_bruta_ln,
                                    'Venta Neta': venta_neta_ln,
                                    'Costo Unitario': costo_unit_nc,
                                    'Costo Total': costo_total_ln,
                                    'Margen Front': margen_ln,
                                    'Comision %': 0,
                                    'Comisión': 0,
                                    'Logística': 0,
                                    'Marketing': 0,
                                    'Mg final': margen_ln,
                                })
                        else:
                            # Fallback legacy: NC sin invoice_line_ids → fila agregada con costo proporcional
                            nc_data.append({
                                'Tipo Movimiento': 'Devolución',
                                'Bodega': bodega_nc,
                                'Documento': nc.get('name', ''),
                                'Fecha Documento': fecha_nc,
                                'Pedido': pedido_nc,
                                'Pedido Marketplace': orden_orig.get('channel_order_reference', '') or '',
                                'Ref Cliente': orden_orig.get('client_order_ref', '') or '',
                                'Estado Pedido': estado_ped_nc,
                                'Tipo Despacho': '',
                                'SKU': '',
                                'Canal': canal_nc,
                                'Fecha Venta': fecha_v_nc,
                                'Hora Venta': hora_nc,
                                'Producto': f"Nota de Crédito de {factura_orig.get('name', 'Factura')}",
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
                                'Tipo Negocio': tipo_negocio_nc,
                                'KAM': kam_nc,
                                'Estado Canal': '',
                                'Año venta': anio_nc,
                                'Mes venta': mes_nc,
                                'Semana venta': sem_nc,
                                'Día semana': dia_nc,
                                'Hora venta': hora_nc_num,
                                'Cantidad': 1,
                                'Venta bruta': -nc_amount_bruto_abs,
                                'Venta Neta': -nc_amount_abs,
                                'Costo Unitario': 0,
                                'Costo Total': -costo_nc,
                                'Margen Front': margen_nc,
                                'Comision %': 0,
                                'Comisión': 0,
                                'Logística': 0,
                                'Marketing': 0,
                                'Mg final': margen_nc,
                            })

            # Agregar las filas de NC al DataFrame
            if nc_data:
                df_nc = pd.DataFrame(nc_data)
                df = pd.concat([df, df_nc], ignore_index=True)

        # Asegurar orden exacto de columnas (41 columnas: 40 RAW originales + Venta Neta)
        columnas_raw = [
            'Tipo Movimiento', 'Bodega', 'Documento', 'Fecha Documento', 'Pedido',
            'Estado Pedido', 'Tipo Despacho', 'SKU', 'Canal', 'Fecha Venta',
            'Hora Venta', 'Producto', 'Categoría macro', 'Categoría padre', 'Categoría hijo',
            'Categoría comercial', 'Estado SKU', 'Pack', 'Marca', 'Proveedor',
            'Tipo Marca', 'Tipo Compra', 'Tipo Negocio', 'KAM', 'Estado Canal',
            'Año venta', 'Mes venta', 'Semana venta', 'Día semana', 'Hora venta',
            'Cantidad', 'Venta bruta', 'Venta Neta', 'Costo Unitario', 'Costo Total', 'Margen Front',
            'Comision %', 'Comisión', 'Logística', 'Marketing', 'Mg final',
            'Pedido Marketplace', 'Ref Cliente'
        ]

        # Asegurar que todas las columnas existan
        for col in columnas_raw:
            if col not in df.columns:
                df[col] = 0 if col in ('Venta Neta',) else ''

        return df[columnas_raw]

    def _calcular_metricas_raw(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula y valida métricas en el formato RAW.
        Asegura que los tipos de datos sean correctos.
        """
        # Convertir columnas numéricas
        columnas_numericas = [
            'Cantidad', 'Venta bruta', 'Venta Neta', 'Costo Unitario', 'Costo Total',
            'Margen Front', 'Comision %', 'Comisión', 'Logística', 'Marketing', 'Mg final'
        ]

        for col in columnas_numericas:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # Convertir columnas de fecha
        df['Fecha Documento'] = pd.to_datetime(df['Fecha Documento'], errors='coerce')
        df['Fecha Venta'] = pd.to_datetime(df['Fecha Venta'], errors='coerce')

        # Convertir columnas de año/mes/semana/día a int
        columnas_temporales = ['Año venta', 'Mes venta', 'Semana venta', 'Día semana']
        for col in columnas_temporales:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

        return df

    @staticmethod
    def _nombre_periodo(periodo_inicio: str, periodo_fin: str) -> str:
        """Genera nombre del período (ej: 'abril_2026')"""
        try:
            fecha = pd.to_datetime(periodo_inicio)
            meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
                    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
            return f"{meses[fecha.month - 1]}_{fecha.year}"
        except:
            return 'periodo_custom'
