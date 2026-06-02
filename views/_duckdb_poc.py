"""POC: reimplementa get_kpis_yoy usando DuckDB sobre parquet, sin SQLite intermedio.

Objetivo: validar que los KPIs dan EXACTAMENTE lo mismo que la opción A
(Turso/SQLite) antes de migrar.

NO se usa en producción. Solo para comparación side-by-side.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
HIST_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
MES_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'


class DuckDBVentasService:
    """Lee directo de parquets con DuckDB. Sin SQLite, sin cache pegado.

    Cada llamada abre una conexión DuckDB nueva, lee los parquets via UNION,
    y devuelve resultado. Latencia: 50-200ms para parquets de ~500K filas.
    """

    def __init__(self, hist_path: Path = HIST_PARQUET, mes_path: Path = MES_PARQUET):
        self.hist_path = hist_path
        self.mes_path = mes_path

    def _conn(self):
        """Conexión DuckDB en memoria con los parquets registrados como views."""
        con = duckdb.connect(':memory:')
        # CRÍTICO: convertir fecha_venta a DATE puro (sin timestamp) para
        # que BETWEEN '2026-05-01' AND '2026-05-25' incluya el día 25.
        # UNION ALL BY NAME: matchea por NOMBRE de columna, no por posición.
        # Crítico porque hist y mes tienen distinto orden de columnas
        # (venta_neta está en pos 40 en hist, pos 32 en mes).
        con.execute(f"""
            CREATE VIEW ventas AS
            SELECT * EXCLUDE (fecha_venta),
                   CAST(fecha_venta AS DATE) AS fecha_venta
            FROM (
                SELECT * FROM read_parquet('{self.hist_path.as_posix()}')
                UNION ALL BY NAME
                SELECT * FROM read_parquet('{self.mes_path.as_posix()}')
            )
        """)
        return con

    def _build_where(self, params: dict) -> tuple[str, list]:
        clauses = []
        values: list = []
        if params.get('fecha_desde'):
            clauses.append("fecha_venta >= ?")
            values.append(params['fecha_desde'])
        if params.get('fecha_hasta'):
            clauses.append("fecha_venta <= ?")
            values.append(params['fecha_hasta'])
        for col in ('canal', 'marca', 'categoria_macro', 'categoria_padre',
                    'categoria_hijo', 'tipo_negocio', 'kam', 'bodega', 'sku'):
            v = params.get(col) or params.get('categoria') if col == 'categoria_macro' else params.get(col)
            v = params.get(col)
            if not v:
                continue
            if isinstance(v, (list, tuple, set)):
                if not v:
                    continue
                placeholders = ','.join(['?'] * len(v))
                clauses.append(f"{col} IN ({placeholders})")
                values.extend(v)
            else:
                clauses.append(f"{col} = ?")
                values.append(v)
        where = " AND ".join(clauses) if clauses else "1=1"
        return where, values

    def _kpis_periodo(self, fecha_desde: str, fecha_hasta: str, params_extra: Optional[dict] = None) -> dict:
        params = dict(params_extra or {})
        params['fecha_desde'] = fecha_desde
        params['fecha_hasta'] = fecha_hasta
        where, values = self._build_where(params)

        sql = f"""
            SELECT
                COALESCE(ROUND(SUM(venta_bruta), 0), 0) as venta,
                COALESCE(ROUND(SUM(venta_neta), 0), 0) as venta_neta,
                COALESCE(ROUND(SUM(margen_front), 0), 0) as margen_front,
                COALESCE(ROUND(SUM(margen_final), 0), 0) as margen_final,
                COALESCE(ROUND(SUM(margen_front), 0), 0) as margen,
                COALESCE(ROUND(100.0 * SUM(margen_front) / NULLIF(SUM(venta_neta), 0), 1), 0) as pct_margen
            FROM ventas WHERE {where}
        """
        sql2 = f"""
            SELECT
                COALESCE(ROUND(SUM(cantidad), 0), 0) as unidades,
                COUNT(DISTINCT documento) as ordenes
            FROM ventas WHERE {where} AND tipo_movimiento = 'Venta'
        """
        con = self._conn()
        row = con.execute(sql, values).fetchone()
        cols = ['venta','venta_neta','margen_front','margen_final','margen','pct_margen']
        result = dict(zip(cols, row))
        row2 = con.execute(sql2, values).fetchone()
        result['unidades'] = row2[0]
        result['ordenes'] = row2[1]
        con.close()
        return result

    def _shift_year(self, fecha: str) -> str:
        d = pd.to_datetime(fecha)
        try:
            return d.replace(year=d.year - 1).strftime('%Y-%m-%d')
        except ValueError:
            # 29-feb → 28-feb del año anterior
            return d.replace(year=d.year - 1, day=28).strftime('%Y-%m-%d')

    def get_kpis_yoy(self, params: dict) -> dict:
        ty_desde = params.get('fecha_desde')
        ty_hasta = params.get('fecha_hasta')
        if not ty_desde or not ty_hasta:
            from datetime import datetime
            hoy = datetime.now()
            ty_desde = hoy.replace(day=1).strftime('%Y-%m-%d')
            ty_hasta = hoy.strftime('%Y-%m-%d')
        ly_desde = self._shift_year(ty_desde)
        ly_hasta = self._shift_year(ty_hasta)

        ty = self._kpis_periodo(ty_desde, ty_hasta, params)
        ly = self._kpis_periodo(ly_desde, ly_hasta, params)

        def var_pct(t, l):
            if not l:
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
