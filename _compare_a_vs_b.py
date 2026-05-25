"""Side-by-side: opción A (SQLite/Turso actual) vs B (DuckDB sobre parquet).

Replica la query de A construyendo el SQLite local desde parquets como hace la
app actual, y la query de B con DuckDB directo. Compara los KPIs.

Si las salidas son IDÉNTICAS → B es safe para promover a producción.
"""
import sys, tempfile, sqlite3, time
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

# ============================================================
# OPCIÓN A: replicar el flujo actual (parquet → SQLite temp)
# ============================================================

def build_sqlite_like_app() -> str:
    """Construye SQLite local replicando exactamente lo que hace views/shared.py."""
    tmp = tempfile.mktemp(suffix='.db')
    conn = sqlite3.connect(tmp)

    cols = ['tipo_movimiento', 'bodega', 'documento', 'fecha_documento', 'pedido',
            'estado_pedido', 'tipo_despacho', 'sku', 'canal', 'fecha_venta',
            'hora_venta', 'producto', 'categoria_macro', 'categoria_padre',
            'categoria_hijo', 'categoria_comercial', 'estado_sku', 'pack', 'marca',
            'proveedor', 'tipo_marca', 'tipo_compra', 'tipo_negocio', 'kam',
            'estado_canal', 'anio_venta', 'mes_venta', 'semana_venta', 'dia_semana',
            'hora_venta_num', 'cantidad', 'venta_bruta', 'venta_neta', 'costo_unitario',
            'costo_total', 'margen_front', 'comision_pct', 'comision', 'logistica',
            'marketing', 'margen_final']

    schema = f"CREATE TABLE ventas ({', '.join(f'{c} TEXT' for c in cols)})"
    # Usar tipos correctos
    schema = """CREATE TABLE ventas (
        tipo_movimiento TEXT, bodega TEXT, documento TEXT, fecha_documento TEXT,
        pedido TEXT, estado_pedido TEXT, tipo_despacho TEXT, sku TEXT, canal TEXT,
        fecha_venta TEXT, hora_venta TEXT, producto TEXT,
        categoria_macro TEXT, categoria_padre TEXT, categoria_hijo TEXT, categoria_comercial TEXT,
        estado_sku TEXT, pack TEXT, marca TEXT, proveedor TEXT,
        tipo_marca TEXT, tipo_compra TEXT, tipo_negocio TEXT, kam TEXT,
        estado_canal TEXT, anio_venta INT, mes_venta INT, semana_venta INT,
        dia_semana TEXT, hora_venta_num INT,
        cantidad REAL, venta_bruta REAL, venta_neta REAL, costo_unitario REAL, costo_total REAL,
        margen_front REAL, comision_pct REAL, comision REAL,
        logistica REAL, marketing REAL, margen_final REAL
    )"""
    conn.execute(schema)
    conn.commit()

    # Carga hist + mes con normalización de fecha (como tras mi fix de hoy)
    def _normalize_fecha(df):
        df = df.copy()
        df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
        return df

    df_hist = pd.read_parquet(PROJECT_ROOT / 'data/historico/ventas_historico.parquet')
    df_hist = _normalize_fecha(df_hist)
    df_hist[cols].to_sql('ventas', conn, if_exists='append', index=False, chunksize=500, method='multi')

    df_mes = pd.read_parquet(PROJECT_ROOT / 'data/historico/ventas_mes_actual.parquet')
    df_mes = _normalize_fecha(df_mes)
    df_mes[cols].to_sql('ventas', conn, if_exists='append', index=False, chunksize=500, method='multi')

    conn.close()
    return tmp


def kpis_opcion_a(db_path: str, params: dict) -> dict:
    from app.services.maestra_service import MaestraService
    svc = MaestraService(db_path)
    def _conn(self=svc):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c
    svc._conn = _conn
    return svc.get_kpis_yoy(params)


# ============================================================
# OPCIÓN B: DuckDB directo sobre parquet
# ============================================================
def kpis_opcion_b(params: dict) -> dict:
    from views._duckdb_poc import DuckDBVentasService
    return DuckDBVentasService().get_kpis_yoy(params)


# ============================================================
# Comparación
# ============================================================
def compare(params: dict, label: str):
    print(f"\n{'='*80}\nCASO: {label}\nFiltros: {params}\n{'='*80}")

    t0 = time.time()
    db_a = build_sqlite_like_app()
    print(f"  [A] SQLite build: {time.time()-t0:.2f}s")
    t1 = time.time()
    res_a = kpis_opcion_a(db_a, params)
    print(f"  [A] Query KPIs: {time.time()-t1:.3f}s")

    t2 = time.time()
    res_b = kpis_opcion_b(params)
    print(f"  [B] DuckDB total: {time.time()-t2:.3f}s")

    # Comparar
    print(f"\n  {'Métrica':<20} | {'A (SQLite)':>15} | {'B (DuckDB)':>15} | {'Match':<5}")
    print(f"  {'-'*65}")
    all_match = True
    for metric in ['venta', 'venta_neta', 'margen', 'margen_front', 'margen_final',
                   'unidades', 'ordenes', 'pct_margen']:
        for period in ['ty', 'ly']:
            a = res_a[period].get(metric)
            b = res_b[period].get(metric)
            match = (a == b) or (abs(float(a or 0) - float(b or 0)) < 0.01)
            mark = '✓' if match else '✗'
            if not match:
                all_match = False
            print(f"  {period.upper()}.{metric:<16} | {a!s:>15} | {b!s:>15} | {mark}")

    print(f"\n  Veredicto: {'✅ IDÉNTICO' if all_match else '❌ DIFERENCIAS DETECTADAS'}")
    import os
    os.unlink(db_a)
    return all_match


# ============================================================
# Run cases
# ============================================================
if __name__ == '__main__':
    cases = [
        ({'fecha_desde': '2026-05-01', 'fecha_hasta': '2026-05-25'},
         "Mayo 2026 (sin filtros)"),
        ({'fecha_desde': '2026-05-01', 'fecha_hasta': '2026-05-25', 'canal': 'Mercado Libre'},
         "Mayo 2026 + canal MeLi"),
        ({'fecha_desde': '2026-05-01', 'fecha_hasta': '2026-05-25', 'tipo_negocio': 'Distribución'},
         "Mayo 2026 + TN Distribución"),
        ({'fecha_desde': '2026-04-01', 'fecha_hasta': '2026-04-30'},
         "Abril 2026 (mes cerrado)"),
        ({'fecha_desde': '2026-05-01', 'fecha_hasta': '2026-05-31', 'kam': 'Martin'},
         "Mayo + KAM Martin"),
    ]

    results = []
    for p, label in cases:
        ok = compare(p, label)
        results.append((label, ok))

    print(f"\n\n{'='*80}\nRESUMEN FINAL\n{'='*80}")
    for label, ok in results:
        print(f"  {'✅' if ok else '❌'} {label}")
    total_ok = sum(1 for _, ok in results if ok)
    print(f"\n  {total_ok}/{len(results)} casos idénticos")
