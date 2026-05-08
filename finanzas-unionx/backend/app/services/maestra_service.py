"""
Servicio para consultas a la Maestra de Ventas (SQLite local o Turso libSQL).
"""
import os
import sys
import sqlite3
import pandas as pd
from pathlib import Path

# Importar adaptador DB (soporta SQLite local y Turso)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
try:
    from db_client import get_connection as _get_db_connection
except ImportError:
    _get_db_connection = None


class MaestraService:
    def __init__(self, db_path):
        self.db_path = str(db_path)

    def _conn(self):
        if _get_db_connection:
            return _get_db_connection(self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _build_where(self, params):
        """Construye WHERE soportando valores escalares (=) y listas (IN)."""
        clauses = []
        values = []

        def _add(col, val):
            """Agrega clause con = (escalar), IN (lista) o LIKE (str con wildcard)."""
            if val is None or val == '' or val == []:
                return
            if isinstance(val, (list, tuple, set)):
                if not val:
                    return
                placeholders = ','.join(['?'] * len(val))
                clauses.append(f"{col} IN ({placeholders})")
                values.extend(val)
            else:
                clauses.append(f"{col} = ?")
                values.append(val)

        if params.get('fecha_desde'):
            clauses.append("fecha_venta >= ?")
            values.append(params['fecha_desde'])
        if params.get('fecha_hasta'):
            clauses.append("fecha_venta <= ?")
            values.append(params['fecha_hasta'])
        _add('canal', params.get('canal'))
        _add('marca', params.get('marca'))
        _add('categoria_macro', params.get('categoria') or params.get('categoria_macro'))
        _add('categoria_padre', params.get('categoria_padre'))
        _add('categoria_hijo', params.get('categoria_hijo'))
        _add('tipo_negocio', params.get('tipo_negocio'))
        _add('kam', params.get('kam'))
        _add('bodega', params.get('bodega'))
        _add('tipo_movimiento', params.get('tipo_movimiento'))
        _add('sku', params.get('sku'))

        # Producto: si lista → IN, si string → LIKE
        prod = params.get('producto')
        if prod:
            if isinstance(prod, (list, tuple, set)):
                placeholders = ','.join(['?'] * len(prod))
                clauses.append(f"producto IN ({placeholders})")
                values.extend(prod)
            else:
                clauses.append("LOWER(producto) LIKE ?")
                values.append(f"%{str(prod).lower()}%")

        where = " AND ".join(clauses) if clauses else "1=1"
        return where, values

    def get_kpis(self, params):
        where, values = self._build_where(params)
        conn = self._conn()
        row = conn.execute(f"""
            SELECT
                COALESCE(ROUND(SUM(venta_bruta), 0), 0) as venta_bruta,
                COALESCE(ROUND(SUM(margen_final), 0), 0) as margen_final,
                COALESCE(ROUND(SUM(cantidad), 0), 0) as unidades,
                COUNT(DISTINCT documento) as ordenes,
                COUNT(*) as lineas,
                CASE WHEN SUM(venta_bruta) != 0
                    THEN ROUND(SUM(margen_final) / SUM(venta_bruta) * 100, 1)
                    ELSE 0 END as pct_margen,
                CASE WHEN COUNT(DISTINCT documento) != 0
                    THEN ROUND(SUM(venta_bruta) / COUNT(DISTINCT documento), 0)
                    ELSE 0 END as ticket_promedio
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
        """, values).fetchone()
        conn.close()
        return dict(row)

    def get_filtros(self):
        conn = self._conn()
        filtros = {}
        filtros['canales'] = [r[0] for r in conn.execute(
            "SELECT DISTINCT canal FROM dim_canales WHERE canal IS NOT NULL ORDER BY canal"
        ).fetchall()]
        filtros['marcas'] = [r[0] for r in conn.execute(
            "SELECT DISTINCT marca FROM dim_marcas WHERE marca IS NOT NULL AND marca != '0' ORDER BY marca"
        ).fetchall()]
        filtros['categorias'] = [r[0] for r in conn.execute(
            "SELECT DISTINCT categoria_macro FROM dim_productos WHERE categoria_macro IS NOT NULL GROUP BY categoria_macro ORDER BY categoria_macro"
        ).fetchall()]
        filtros['tipos_negocio'] = [r[0] for r in conn.execute(
            "SELECT DISTINCT tipo_negocio FROM ventas WHERE tipo_negocio IS NOT NULL AND tipo_negocio != '' GROUP BY tipo_negocio ORDER BY tipo_negocio"
        ).fetchall()]
        filtros['kams'] = [r[0] for r in conn.execute(
            "SELECT DISTINCT kam FROM ventas WHERE kam IS NOT NULL GROUP BY kam ORDER BY kam"
        ).fetchall()]
        filtros['bodegas'] = [r[0] for r in conn.execute(
            "SELECT DISTINCT bodega FROM dim_bodegas WHERE bodega IS NOT NULL ORDER BY bodega"
        ).fetchall()]
        # Rango de fechas
        row = conn.execute("SELECT MIN(fecha_venta), MAX(fecha_venta) FROM ventas").fetchone()
        filtros['fecha_min'] = row[0]
        filtros['fecha_max'] = row[1]
        # Total registros y última carga
        total_registros = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        filtros['total_registros'] = total_registros
        ultima_carga_row = conn.execute("SELECT MAX(fecha_carga) FROM metadata_cargas").fetchone()
        filtros['ultima_carga'] = ultima_carga_row[0] if ultima_carga_row[0] else None
        conn.close()
        return filtros

    def get_resumen_canales(self, params, limit=10):
        where, values = self._build_where(params)
        conn = self._conn()
        rows = conn.execute(f"""
            SELECT canal,
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final,
                ROUND(SUM(cantidad), 0) as unidades,
                COUNT(DISTINCT documento) as ordenes
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
            GROUP BY canal ORDER BY venta_bruta DESC LIMIT ?
        """, values + [limit]).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_resumen_categorias(self, params, limit=10):
        where, values = self._build_where(params)
        conn = self._conn()
        rows = conn.execute(f"""
            SELECT categoria_macro as categoria,
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final,
                ROUND(SUM(cantidad), 0) as unidades
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
            GROUP BY categoria_macro ORDER BY venta_bruta DESC LIMIT ?
        """, values + [limit]).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_resumen_tipo_negocio(self, params):
        where, values = self._build_where(params)
        conn = self._conn()
        rows = conn.execute(f"""
            SELECT tipo_negocio,
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
            GROUP BY tipo_negocio ORDER BY venta_bruta DESC
        """, values).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_tendencia(self, params):
        where, values = self._build_where(params)
        conn = self._conn()
        rows = conn.execute(f"""
            SELECT anio_venta as anio, mes_venta as mes,
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final,
                ROUND(SUM(cantidad), 0) as unidades,
                COUNT(DISTINCT documento) as ordenes
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
            GROUP BY anio_venta, mes_venta
            ORDER BY anio_venta, mes_venta
        """, values).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d['periodo'] = f"{d['anio']}-{str(d['mes']).zfill(2)}"
            result.append(d)
        return result

    def get_detalle(self, params, page=1, page_size=50, sort_by='venta_bruta', sort_order='desc', search=None):
        where, values = self._build_where(params)
        if search:
            where += " AND (sku LIKE ? OR producto LIKE ?)"
            values.extend([f'%{search}%', f'%{search}%'])

        allowed_sorts = {
            'fecha_venta', 'sku', 'producto', 'canal', 'marca', 'cantidad',
            'venta_bruta', 'margen_final', 'costo_total', 'categoria_macro'
        }
        if sort_by not in allowed_sorts:
            sort_by = 'venta_bruta'
        if sort_order not in ('asc', 'desc'):
            sort_order = 'desc'

        offset = (page - 1) * page_size
        conn = self._conn()

        total = conn.execute(f"SELECT COUNT(*) FROM ventas WHERE {where}", values).fetchone()[0]

        rows = conn.execute(f"""
            SELECT fecha_venta, sku, producto, canal, marca, categoria_macro,
                   bodega, tipo_negocio, kam, cantidad, venta_bruta,
                   costo_total, margen_front, comision, logistica, marketing, margen_final
            FROM ventas WHERE {where}
            ORDER BY {sort_by} {sort_order}
            LIMIT ? OFFSET ?
        """, values + [page_size, offset]).fetchall()
        conn.close()

        return {
            'data': [dict(r) for r in rows],
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
        }

    # Mapeo DB -> nombres originales del Raw ventas Y.xlsx
    EXPORT_COLUMNS = [
        ('tipo_movimiento', 'Tipo Movimiento'),
        ('bodega', 'Bodega'),
        ('documento', 'Documento'),
        ('fecha_documento', 'Fecha Documento'),
        ('pedido', 'Pedido'),
        ('estado_pedido', 'Estado Pedido'),
        ('tipo_despacho', 'Tipo Despacho'),
        ('sku', 'SKU'),
        ('canal', 'Canal'),
        ('fecha_venta', 'Fecha Venta'),
        ('hora_venta', 'Hora Venta'),
        ('producto', 'Producto'),
        ('categoria_macro', 'Categoría macro'),
        ('categoria_padre', 'Categoría padre'),
        ('categoria_hijo', 'Categoría hijo'),
        ('categoria_comercial', 'Categoría comercial'),
        ('estado_sku', 'Estado SKU'),
        ('pack', 'Pack'),
        ('marca', 'Marca'),
        ('proveedor', 'Proveedor'),
        ('tipo_marca', 'Tipo Marca'),
        ('tipo_compra', 'Tipo Compra'),
        ('tipo_negocio', 'Tipo Negocio'),
        ('kam', 'KAM'),
        ('estado_canal', 'Estado Canal'),
        ('anio_venta', 'Año venta'),
        ('mes_venta', 'Mes venta'),
        ('semana_venta', 'Semana venta'),
        ('dia_semana', 'Día semana'),
        ('hora_venta_num', 'Hora venta'),
        ('cantidad', 'Cantidad'),
        ('venta_bruta', 'Venta bruta'),
        ('costo_unitario', 'Costo Unitario'),
        ('costo_total', 'Costo Total'),
        ('margen_front', 'Margen Front'),
        ('comision_pct', 'Comision %'),
        ('comision', 'Comisión'),
        ('logistica', 'Logística'),
        ('marketing', 'Marketing'),
        ('margen_final', 'Mg final'),
    ]

    def export_dataframe(self, params):
        where, values = self._build_where(params)
        db_cols = ', '.join(col[0] for col in self.EXPORT_COLUMNS)
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(f"""
            SELECT {db_cols}
            FROM ventas WHERE {where}
            ORDER BY fecha_venta DESC
        """, conn, params=values)
        conn.close()
        # Renombrar a nombres originales del Raw
        rename_map = {col[0]: col[1] for col in self.EXPORT_COLUMNS}
        df.rename(columns=rename_map, inplace=True)
        return df

    def get_top_skus(self, params, limit=20):
        """Top 20 SKUs por venta bruta"""
        where, values = self._build_where(params)
        conn = self._conn()
        rows = conn.execute(f"""
            SELECT sku, producto,
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final,
                ROUND(SUM(cantidad), 0) as unidades,
                ROUND(100.0 * SUM(margen_final) / NULLIF(SUM(venta_bruta), 0), 1) as pct_margen
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
            GROUP BY sku, producto
            ORDER BY venta_bruta DESC
            LIMIT ?
        """, values + [limit]).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_resumen_bodegas(self, params):
        """Resumen por bodega"""
        where, values = self._build_where(params)
        conn = self._conn()
        rows = conn.execute(f"""
            SELECT bodega,
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final,
                ROUND(SUM(cantidad), 0) as unidades,
                ROUND(100.0 * SUM(margen_final) / NULLIF(SUM(venta_bruta), 0), 1) as pct_margen
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
            GROUP BY bodega
            ORDER BY venta_bruta DESC
        """, values).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_tendencia_diaria(self, params):
        """Tendencia por día"""
        where, values = self._build_where(params)
        conn = self._conn()
        rows = conn.execute(f"""
            SELECT fecha_venta,
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final,
                ROUND(SUM(cantidad), 0) as unidades
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
            GROUP BY fecha_venta
            ORDER BY fecha_venta
        """, values).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_comparativa_semanal(self):
        """Comparativa últimos 7 días vs 7 días anteriores"""
        conn = self._conn()
        # Obtener máxima fecha de la DB
        max_date_row = conn.execute("SELECT MAX(fecha_venta) FROM ventas").fetchone()
        if not max_date_row[0]:
            conn.close()
            return {
                'actual': {'venta_bruta': 0, 'margen_final': 0, 'pct_margen': 0},
                'anterior': {'venta_bruta': 0, 'margen_final': 0, 'pct_margen': 0},
                'variacion_venta_pct': 0,
                'variacion_margen_pct': 0
            }

        max_date = max_date_row[0]

        # Semana actual: últimos 7 días desde max_date
        actual_row = conn.execute(f"""
            SELECT
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final
            FROM ventas
            WHERE fecha_venta >= date('{max_date}', '-6 days')
              AND fecha_venta <= '{max_date}'
              AND tipo_movimiento = 'Venta'
        """).fetchone()

        # Semana anterior: los 7 días previos
        anterior_row = conn.execute(f"""
            SELECT
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final
            FROM ventas
            WHERE fecha_venta >= date('{max_date}', '-13 days')
              AND fecha_venta < date('{max_date}', '-6 days')
              AND tipo_movimiento = 'Venta'
        """).fetchone()

        conn.close()

        actual_venta = actual_row[0] or 0
        actual_margen = actual_row[1] or 0
        anterior_venta = anterior_row[0] or 0
        anterior_margen = anterior_row[1] or 0

        variacion_venta_pct = 0 if anterior_venta == 0 else round((actual_venta - anterior_venta) / anterior_venta * 100, 1)
        variacion_margen_pct = 0 if anterior_margen == 0 else round((actual_margen - anterior_margen) / anterior_margen * 100, 1)

        actual_pct_margen = 0 if actual_venta == 0 else round(actual_margen / actual_venta * 100, 1)
        anterior_pct_margen = 0 if anterior_venta == 0 else round(anterior_margen / anterior_venta * 100, 1)

        return {
            'actual': {
                'venta_bruta': actual_venta,
                'margen_final': actual_margen,
                'pct_margen': actual_pct_margen
            },
            'anterior': {
                'venta_bruta': anterior_venta,
                'margen_final': anterior_margen,
                'pct_margen': anterior_pct_margen
            },
            'variacion_venta_pct': variacion_venta_pct,
            'variacion_margen_pct': variacion_margen_pct
        }

    def get_matriz_canal_negocio(self, params, limit=15):
        """Matriz canal × tipo de negocio"""
        where, values = self._build_where(params)
        conn = self._conn()
        rows = conn.execute(f"""
            SELECT canal, tipo_negocio,
                ROUND(SUM(venta_bruta), 0) as venta_bruta,
                ROUND(SUM(margen_final), 0) as margen_final,
                ROUND(100.0 * SUM(margen_final) / NULLIF(SUM(venta_bruta), 0), 1) as pct_margen
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
            GROUP BY canal, tipo_negocio
            ORDER BY venta_bruta DESC
            LIMIT ?
        """, values + [limit]).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ============================================================
    # YEAR-OVER-YEAR (YoY) — Comparativa contra el año anterior
    # ============================================================

    @staticmethod
    def _shift_year(fecha_str: str, anios: int = -1) -> str:
        """Resta N años a una fecha YYYY-MM-DD."""
        from datetime import datetime
        if not fecha_str:
            return None
        d = datetime.strptime(fecha_str[:10], '%Y-%m-%d')
        try:
            return d.replace(year=d.year + anios).strftime('%Y-%m-%d')
        except ValueError:
            # 29-feb año bisiesto -> 28-feb
            return d.replace(year=d.year + anios, day=28).strftime('%Y-%m-%d')

    def _kpis_periodo(self, fecha_desde: str, fecha_hasta: str, params_extra=None):
        """KPIs base para un período (soporta filtros escalares y multi-select)."""
        clauses = ["fecha_venta >= ?", "fecha_venta <= ?"]
        values = [fecha_desde, fecha_hasta]

        def _add(col, val):
            if val is None or val == '' or val == []:
                return
            if isinstance(val, (list, tuple, set)):
                if not val:
                    return
                placeholders = ','.join(['?'] * len(val))
                clauses.append(f"{col} IN ({placeholders})")
                values.extend(val)
            else:
                clauses.append(f"{col} = ?")
                values.append(val)

        if params_extra:
            _add('canal', params_extra.get('canal'))
            _add('marca', params_extra.get('marca'))
            _add('categoria_macro', params_extra.get('categoria') or params_extra.get('categoria_macro'))
            _add('categoria_padre', params_extra.get('categoria_padre'))
            _add('categoria_hijo', params_extra.get('categoria_hijo'))
            _add('tipo_negocio', params_extra.get('tipo_negocio'))
            _add('kam', params_extra.get('kam'))
            _add('bodega', params_extra.get('bodega'))
            _add('sku', params_extra.get('sku'))
            # Producto: si es lista (multiselect) usar IN, si es string usar LIKE
            prod = params_extra.get('producto')
            if prod:
                if isinstance(prod, (list, tuple, set)):
                    placeholders = ','.join(['?'] * len(prod))
                    clauses.append(f"producto IN ({placeholders})")
                    values.extend(prod)
                else:
                    clauses.append("LOWER(producto) LIKE ?")
                    values.append(f"%{str(prod).lower()}%")
        where = " AND ".join(clauses)
        conn = self._conn()
        row = conn.execute(f"""
            SELECT
                COALESCE(ROUND(SUM(venta_bruta), 0), 0) as venta,
                COALESCE(ROUND(SUM(venta_neta), 0), 0) as venta_neta,
                COALESCE(ROUND(SUM(margen_front), 0), 0) as margen_front,
                COALESCE(ROUND(SUM(margen_final), 0), 0) as margen_final,
                COALESCE(ROUND(SUM(margen_front), 0), 0) as margen,
                COALESCE(ROUND(100.0 * SUM(margen_front) / NULLIF(SUM(venta_neta), 0), 1), 0) as pct_margen
            FROM ventas WHERE {where}
        """, values).fetchone()
        row2 = conn.execute(f"""
            SELECT
                COALESCE(ROUND(SUM(cantidad), 0), 0) as unidades,
                COUNT(DISTINCT documento) as ordenes
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
        """, values).fetchone()
        conn.close()
        return {**dict(row), **dict(row2)}

    def get_kpis_yoy(self, params):
        """
        KPIs del periodo TY vs mismo periodo LY (-1 año).
        Returns: {'ty': {...}, 'ly': {...}, 'var': {...}}
        """
        ty_desde = params.get('fecha_desde')
        ty_hasta = params.get('fecha_hasta')
        if not ty_desde or not ty_hasta:
            # Default: mes actual hasta hoy
            from datetime import datetime
            hoy = datetime.now()
            ty_desde = hoy.replace(day=1).strftime('%Y-%m-%d')
            ty_hasta = hoy.strftime('%Y-%m-%d')
        ly_desde = self._shift_year(ty_desde)
        ly_hasta = self._shift_year(ty_hasta)

        ty = self._kpis_periodo(ty_desde, ty_hasta, params)
        ly = self._kpis_periodo(ly_desde, ly_hasta, params)

        def var_pct(t, l):
            if l == 0 or l is None:
                return None
            return round((t - l) / abs(l) * 100, 1)

        var = {
            'venta': var_pct(ty['venta'], ly['venta']),
            'margen': var_pct(ty['margen'], ly['margen']),
            'unidades': var_pct(ty['unidades'], ly['unidades']),
            'ordenes': var_pct(ty['ordenes'], ly['ordenes']),
            'pct_margen': round((ty['pct_margen'] or 0) - (ly['pct_margen'] or 0), 1),
        }

        return {
            'ty': ty, 'ly': ly, 'var_pct': var,
            'periodo_ty': {'desde': ty_desde, 'hasta': ty_hasta},
            'periodo_ly': {'desde': ly_desde, 'hasta': ly_hasta},
        }

    def get_tendencia_mensual_yoy(self, anios=2):
        """Mensual TY vs LY: 12 meses, NETO (incluye devoluciones)."""
        conn = self._conn()
        rows = conn.execute("""
            SELECT strftime('%Y', fecha_venta) as anio,
                   strftime('%m', fecha_venta) as mes,
                   ROUND(SUM(venta_bruta), 0) as venta,
                   ROUND(SUM(margen_final), 0) as margen,
                   ROUND(SUM(CASE WHEN tipo_movimiento = 'Venta' THEN cantidad ELSE 0 END), 0) as unidades
            FROM ventas
            GROUP BY anio, mes
            ORDER BY anio, mes
        """).fetchall()
        conn.close()
        # Pivot: por mes, año actual y año anterior
        from datetime import datetime
        anio_actual = datetime.now().year
        meses = []
        for m in range(1, 13):
            ms = f"{m:02d}"
            ty = next((r for r in rows if r['anio'] == str(anio_actual) and r['mes'] == ms), None)
            ly = next((r for r in rows if r['anio'] == str(anio_actual - 1) and r['mes'] == ms), None)
            meses.append({
                'mes': ms,
                'mes_nombre': ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'][m-1],
                'venta_ty': ty['venta'] if ty else 0,
                'venta_ly': ly['venta'] if ly else 0,
                'margen_ty': ty['margen'] if ty else 0,
                'margen_ly': ly['margen'] if ly else 0,
                'unidades_ty': ty['unidades'] if ty else 0,
                'unidades_ly': ly['unidades'] if ly else 0,
            })
        return meses

    def get_tendencia_diaria_yoy(self, anio=None, mes=None):
        """Día a día del mes en curso TY vs LY (NETO)."""
        from datetime import datetime
        if anio is None: anio = datetime.now().year
        if mes is None: mes = datetime.now().month
        conn = self._conn()
        rows = conn.execute("""
            SELECT fecha_venta as fecha,
                   ROUND(SUM(venta_bruta), 0) as venta,
                   ROUND(SUM(margen_final), 0) as margen,
                   ROUND(SUM(CASE WHEN tipo_movimiento = 'Venta' THEN cantidad ELSE 0 END), 0) as unidades
            FROM ventas
            WHERE ((strftime('%Y', fecha_venta) = ? AND strftime('%m', fecha_venta) = ?)
                OR (strftime('%Y', fecha_venta) = ? AND strftime('%m', fecha_venta) = ?))
            GROUP BY fecha
            ORDER BY fecha
        """, [str(anio), f"{mes:02d}", str(anio-1), f"{mes:02d}"]).fetchall()
        conn.close()
        # Pivot por día del mes
        dias = {}
        for r in rows:
            fecha = r['fecha']
            anio_r = int(fecha[:4]); dia_r = int(fecha[8:10])
            d = dias.setdefault(dia_r, {'dia': dia_r,
                'venta_ty': 0, 'venta_ly': 0, 'margen_ty': 0, 'margen_ly': 0,
                'unidades_ty': 0, 'unidades_ly': 0})
            sufijo = 'ty' if anio_r == anio else 'ly'
            d[f'venta_{sufijo}'] = r['venta']
            d[f'margen_{sufijo}'] = r['margen']
            d[f'unidades_{sufijo}'] = r['unidades']
        return [dias[k] for k in sorted(dias.keys())]

    def get_por_canal_yoy(self, params):
        """Por canal: TY, LY y var % (aplica filtros del dashboard)."""
        ty_desde = params.get('fecha_desde'); ty_hasta = params.get('fecha_hasta')
        if not ty_desde or not ty_hasta:
            from datetime import datetime
            hoy = datetime.now()
            ty_desde = hoy.replace(day=1).strftime('%Y-%m-%d')
            ty_hasta = hoy.strftime('%Y-%m-%d')
        ly_desde = self._shift_year(ty_desde); ly_hasta = self._shift_year(ty_hasta)

        # Construir extra WHERE para filtros (sin canal porque agrupamos por canal)
        params_extra = {k: v for k, v in params.items() if k not in ('fecha_desde', 'fecha_hasta', 'canal')}
        extra_where, extra_values = '', []
        if any(params_extra.get(k) for k in ('marca', 'categoria', 'tipo_negocio', 'kam', 'bodega', 'sku', 'producto')):
            _w, _v = self._build_where(params_extra)
            if _w and _w != '1=1':
                extra_where = ' AND ' + _w
                extra_values = _v

        conn = self._conn()
        rows_ty = conn.execute(f"""
            SELECT canal,
                   ROUND(SUM(venta_bruta), 0) as venta,
                   ROUND(SUM(margen_final), 0) as margen,
                   ROUND(SUM(CASE WHEN tipo_movimiento = 'Venta' THEN cantidad ELSE 0 END), 0) as unidades,
                   ROUND(100.0 * SUM(margen_final) / NULLIF(SUM(venta_bruta), 0), 1) as pct_margen
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ? {extra_where}
            GROUP BY canal
        """, [ty_desde, ty_hasta] + extra_values).fetchall()
        rows_ly = conn.execute(f"""
            SELECT canal,
                   ROUND(SUM(venta_bruta), 0) as venta,
                   ROUND(SUM(margen_final), 0) as margen,
                   ROUND(SUM(CASE WHEN tipo_movimiento = 'Venta' THEN cantidad ELSE 0 END), 0) as unidades
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ? {extra_where}
            GROUP BY canal
        """, [ly_desde, ly_hasta] + extra_values).fetchall()
        conn.close()
        ly_map = {r['canal']: r for r in rows_ly}
        result = []
        for r in rows_ty:
            ly = ly_map.get(r['canal'])
            ly_venta = ly['venta'] if ly else 0
            ly_margen = ly['margen'] if ly else 0
            var = round((r['venta'] - ly_venta) / abs(ly_venta) * 100, 1) if ly_venta else None
            var_mg = round((r['margen'] - ly_margen) / abs(ly_margen) * 100, 1) if ly_margen else None
            result.append({
                'canal': r['canal'],
                'venta_ty': r['venta'], 'venta_ly': ly_venta, 'var_venta_pct': var,
                'margen_ty': r['margen'], 'margen_ly': ly_margen, 'var_margen_pct': var_mg,
                'unidades_ty': r['unidades'], 'unidades_ly': ly['unidades'] if ly else 0,
                'pct_margen': r['pct_margen'],
            })
        result.sort(key=lambda x: -(x['venta_ty'] or 0))
        return result

    def get_top_skus_yoy(self, params, limit=20):
        """Top SKUs con var YoY (aplica filtros del dashboard)."""
        ty_desde = params.get('fecha_desde'); ty_hasta = params.get('fecha_hasta')
        if not ty_desde or not ty_hasta:
            from datetime import datetime
            hoy = datetime.now()
            ty_desde = hoy.replace(day=1).strftime('%Y-%m-%d')
            ty_hasta = hoy.strftime('%Y-%m-%d')
        ly_desde = self._shift_year(ty_desde); ly_hasta = self._shift_year(ty_hasta)

        # Filtros extra (canal, marca, categoria, etc.)
        params_extra = {k: v for k, v in params.items() if k not in ('fecha_desde', 'fecha_hasta')}
        extra_where, extra_values = '', []
        if any(params_extra.get(k) for k in ('canal', 'marca', 'categoria', 'tipo_negocio', 'kam', 'bodega', 'sku', 'producto')):
            _w, _v = self._build_where(params_extra)
            if _w and _w != '1=1':
                # Reemplazar columnas para alias 'v.'
                _w = _w.replace('canal ', 'v.canal ').replace('marca ', 'v.marca ').replace('kam ', 'v.kam ')
                _w = _w.replace('categoria_macro', 'v.categoria_macro').replace('tipo_negocio', 'v.tipo_negocio')
                _w = _w.replace('bodega', 'v.bodega').replace('sku ', 'v.sku ')
                _w = _w.replace('LOWER(producto)', 'LOWER(v.producto)')
                extra_where = ' AND ' + _w
                extra_values = _v

        conn = self._conn()
        ty = conn.execute(f"""
            SELECT v.sku, COALESCE(p.producto, v.producto) as producto,
                   ROUND(SUM(v.venta_bruta), 0) as venta,
                   ROUND(SUM(v.margen_final), 0) as margen,
                   ROUND(SUM(v.cantidad), 0) as unidades,
                   ROUND(100.0 * SUM(v.margen_final) / NULLIF(SUM(v.venta_bruta), 0), 1) as pct_margen
            FROM ventas v LEFT JOIN dim_productos p ON v.sku = p.sku
            WHERE v.tipo_movimiento = 'Venta' AND v.fecha_venta BETWEEN ? AND ? {extra_where}
            GROUP BY v.sku ORDER BY venta DESC LIMIT ?
        """, [ty_desde, ty_hasta] + extra_values + [limit]).fetchall()
        skus = [r['sku'] for r in ty]
        if not skus:
            conn.close(); return []
        placeholders = ','.join(['?'] * len(skus))
        ly = conn.execute(f"""
            SELECT sku, ROUND(SUM(venta_bruta), 0) as venta_ly,
                   ROUND(SUM(margen_final), 0) as margen_ly
            FROM ventas
            WHERE tipo_movimiento = 'Venta' AND fecha_venta BETWEEN ? AND ?
              AND sku IN ({placeholders})
            GROUP BY sku
        """, [ly_desde, ly_hasta] + skus).fetchall()
        conn.close()
        ly_map = {r['sku']: r for r in ly}
        out = []
        for r in ty:
            l = ly_map.get(r['sku'])
            ly_v = l['venta_ly'] if l else 0
            var = round((r['venta'] - ly_v) / abs(ly_v) * 100, 1) if ly_v else None
            out.append({**dict(r), 'venta_ly': ly_v, 'var_venta_pct': var})
        return out

    def get_tendencia_semanal_yoy(self, anio=None, mes=None, params_extra=None):
        """
        Tendencia semanal del mes solicitado vs mismo mes año anterior.
        Devuelve [{semana: 1, semana_label: 'Sem 1', desde, hasta, venta_ty, venta_ly, ...}]
        """
        from datetime import datetime, timedelta, date
        if anio is None: anio = datetime.now().year
        if mes is None: mes = datetime.now().month
        # Construir semanas del mes (lunes a domingo, recortadas al mes)
        primer_dia = date(anio, mes, 1)
        # Último día del mes
        if mes == 12:
            ultimo_dia = date(anio, 12, 31)
        else:
            ultimo_dia = date(anio, mes + 1, 1) - timedelta(days=1)

        semanas = []
        cur = primer_dia
        n_sem = 1
        while cur <= ultimo_dia:
            # Domingo de esta semana o fin de mes
            domingo = cur + timedelta(days=(6 - cur.weekday()))
            fin_sem = min(domingo, ultimo_dia)
            semanas.append({'n': n_sem, 'desde': cur, 'hasta': fin_sem})
            cur = fin_sem + timedelta(days=1)
            n_sem += 1

        # Filtros adicionales (soporta escalar e IN)
        extra_clauses = []
        extra_values = []
        if params_extra:
            for k, col in [('canal', 'canal'), ('marca', 'marca'),
                            ('categoria', 'categoria_macro'), ('tipo_negocio', 'tipo_negocio'),
                            ('kam', 'kam'), ('bodega', 'bodega'), ('sku', 'sku')]:
                v = params_extra.get(k)
                if not v:
                    continue
                if isinstance(v, (list, tuple, set)):
                    placeholders = ','.join(['?'] * len(v))
                    extra_clauses.append(f"AND {col} IN ({placeholders})")
                    extra_values.extend(v)
                else:
                    extra_clauses.append(f"AND {col} = ?")
                    extra_values.append(v)
            if params_extra.get('producto'):
                extra_clauses.append("AND LOWER(producto) LIKE ?")
                extra_values.append(f"%{str(params_extra['producto']).lower()}%")
        extra_where = ' '.join(extra_clauses)

        conn = self._conn()
        result = []
        for sem in semanas:
            d_ty = sem['desde'].strftime('%Y-%m-%d')
            h_ty = sem['hasta'].strftime('%Y-%m-%d')
            # Misma semana LY
            try:
                d_ly = sem['desde'].replace(year=anio - 1).strftime('%Y-%m-%d')
                h_ly = sem['hasta'].replace(year=anio - 1).strftime('%Y-%m-%d')
            except ValueError:
                d_ly = (sem['desde'].replace(year=anio - 1, day=28)).strftime('%Y-%m-%d')
                h_ly = (sem['hasta'].replace(year=anio - 1, day=28)).strftime('%Y-%m-%d')

            ty = conn.execute(f"""
                SELECT
                    COALESCE(ROUND(SUM(venta_bruta), 0), 0) as venta,
                    COALESCE(ROUND(SUM(venta_neta), 0), 0) as venta_neta,
                    COALESCE(ROUND(SUM(margen_final), 0), 0) as margen,
                    COALESCE(ROUND(SUM(CASE WHEN tipo_movimiento='Venta' THEN cantidad ELSE 0 END), 0), 0) as unidades
                FROM ventas
                WHERE fecha_venta BETWEEN ? AND ? {extra_where}
            """, [d_ty, h_ty] + extra_values).fetchone()
            ly = conn.execute(f"""
                SELECT
                    COALESCE(ROUND(SUM(venta_bruta), 0), 0) as venta,
                    COALESCE(ROUND(SUM(venta_neta), 0), 0) as venta_neta,
                    COALESCE(ROUND(SUM(margen_final), 0), 0) as margen,
                    COALESCE(ROUND(SUM(CASE WHEN tipo_movimiento='Venta' THEN cantidad ELSE 0 END), 0), 0) as unidades
                FROM ventas
                WHERE fecha_venta BETWEEN ? AND ? {extra_where}
            """, [d_ly, h_ly] + extra_values).fetchone()
            ty_d = dict(ty); ly_d = dict(ly)
            var = (ty_d['venta'] - ly_d['venta']) / abs(ly_d['venta']) * 100 if ly_d['venta'] else None
            result.append({
                'semana': sem['n'],
                'label': f"Sem {sem['n']}",
                'desde': d_ty, 'hasta': h_ty,
                'desde_ly': d_ly, 'hasta_ly': h_ly,
                'venta_ty': ty_d['venta'], 'venta_neta_ty': ty_d['venta_neta'],
                'margen_ty': ty_d['margen'], 'unidades_ty': ty_d['unidades'],
                'venta_ly': ly_d['venta'], 'venta_neta_ly': ly_d['venta_neta'],
                'margen_ly': ly_d['margen'], 'unidades_ly': ly_d['unidades'],
                'var_venta_pct': round(var, 1) if var is not None else None,
            })
        conn.close()
        return result

    def get_filtros_disponibles(self):
        """Devuelve listas distintas para todos los filtros del dashboard."""
        conn = self._conn()

        def _distinct(col):
            return [r[0] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM ventas "
                f"WHERE {col} IS NOT NULL AND {col} != '' AND {col} != '0' "
                f"ORDER BY {col}"
            ).fetchall()]

        canales = _distinct('canal')
        marcas = _distinct('marca')
        categorias_macro = _distinct('categoria_macro')
        categorias_padre = _distinct('categoria_padre')
        categorias_hijo = _distinct('categoria_hijo')
        tipos_negocio = _distinct('tipo_negocio')
        kams = _distinct('kam')

        # Productos y SKUs (limitar a top vendidos para no inflar UI)
        productos = [r[0] for r in conn.execute("""
            SELECT producto FROM ventas
            WHERE producto IS NOT NULL AND producto != ''
            GROUP BY producto
            ORDER BY producto
            LIMIT 5000
        """).fetchall()]
        skus = [r[0] for r in conn.execute("""
            SELECT sku FROM ventas
            WHERE sku IS NOT NULL AND sku != ''
            GROUP BY sku
            ORDER BY sku
            LIMIT 5000
        """).fetchall()]

        conn.close()
        return {
            'canales': canales,
            'marcas': marcas,
            'categorias': categorias_macro,  # backward compat
            'categorias_macro': categorias_macro,
            'categorias_padre': categorias_padre,
            'categorias_hijo': categorias_hijo,
            'tipos_negocio': tipos_negocio,
            'kams': kams,
            'productos': productos,
            'skus': skus,
        }

    def health(self):
        """Estado de la sincronización: última carga, registros, alarma si atrasado."""
        from datetime import datetime, timedelta
        conn = self._conn()
        row = conn.execute("""
            SELECT COUNT(*) as filas, MIN(fecha_venta) as fmin, MAX(fecha_venta) as fmax
            FROM ventas
        """).fetchone()
        meta = conn.execute("""
            SELECT fecha_carga, fuente, filas_cargadas, tipo
            FROM metadata_cargas
            ORDER BY fecha_carga DESC LIMIT 5
        """).fetchall()
        conn.close()
        ultima = meta[0]['fecha_carga'] if meta else None
        atraso_horas = None
        estado = 'desconocido'
        if ultima:
            try:
                d = datetime.fromisoformat(ultima)
                atraso_horas = round((datetime.now() - d).total_seconds() / 3600, 1)
                if atraso_horas <= 30: estado = 'ok'
                elif atraso_horas <= 48: estado = 'atrasado'
                else: estado = 'falla'
            except Exception:
                pass
        return {
            'estado': estado,
            'atraso_horas': atraso_horas,
            'filas_total': row['filas'],
            'fecha_min': row['fmin'],
            'fecha_max': row['fmax'],
            'ultima_carga': ultima,
            'historico_cargas': [dict(m) for m in meta],
        }

    def descargar_raw(self, fecha_desde, fecha_hasta):
        """Genera DataFrame con las 40 columnas RAW para descarga Excel."""
        import pandas as pd
        DB_TO_RAW = {
            'tipo_movimiento': 'Tipo Movimiento', 'bodega': 'Bodega', 'documento': 'Documento',
            'fecha_documento': 'Fecha Documento', 'pedido': 'Pedido', 'estado_pedido': 'Estado Pedido',
            'tipo_despacho': 'Tipo Despacho', 'sku': 'SKU', 'canal': 'Canal',
            'fecha_venta': 'Fecha Venta', 'hora_venta': 'Hora Venta', 'producto': 'Producto',
            'categoria_macro': 'Categoría macro', 'categoria_padre': 'Categoría padre',
            'categoria_hijo': 'Categoría hijo', 'categoria_comercial': 'Categoría comercial',
            'estado_sku': 'Estado SKU', 'pack': 'Pack', 'marca': 'Marca',
            'proveedor': 'Proveedor', 'tipo_marca': 'Tipo Marca', 'tipo_compra': 'Tipo Compra',
            'tipo_negocio': 'Tipo Negocio', 'kam': 'KAM', 'estado_canal': 'Estado Canal',
            'anio_venta': 'Año venta', 'mes_venta': 'Mes venta', 'semana_venta': 'Semana venta',
            'dia_semana': 'Día semana', 'hora_venta_num': 'Hora venta',
            'cantidad': 'Cantidad',
            'venta_bruta': 'Venta bruta', 'venta_neta': 'Venta Neta',
            'costo_unitario': 'Costo Unitario', 'costo_total': 'Costo Total',
            'margen_front': 'Margen Front', 'comision_pct': 'Comision %',
            'comision': 'Comisión', 'logistica': 'Logística',
            'marketing': 'Marketing', 'margen_final': 'Mg final',
        }
        conn = self._conn()
        df = pd.read_sql_query(
            f"SELECT {','.join(DB_TO_RAW.keys())} FROM ventas "
            "WHERE fecha_venta BETWEEN ? AND ? ORDER BY fecha_venta",
            conn, params=[fecha_desde, fecha_hasta])
        conn.close()
        df = df.rename(columns=DB_TO_RAW)
        return df
