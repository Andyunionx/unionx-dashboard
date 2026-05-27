"""Genera los snapshots planif_* que NO se pueden dumpear de Turso (reads
bloqueadas) usando fuentes alternativas que NO dependen de Turso:

  - planif_ventas_diarias_sku ← parquets de ventas (historico + mes_actual)
  - planif_forecast_manual    ← FORECAST FINAL SKU 26-27 V2.xlsx
  - planif_stock_live         ← Odoo directo (StockAdvancedService)

Escribe a data/planificacion/snapshots/<tabla>.parquet — el mismo fallback
que consume views/planning/_data_helpers.py cuando Turso bloquea.

Uso:
    python generar_snapshots_offline.py                  # los 3
    python generar_snapshots_offline.py --tabla ventas   # uno solo
    python generar_snapshots_offline.py --tabla forecast
    python generar_snapshots_offline.py --tabla stock     # ~3-5 min (Odoo)
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))
SNAPSHOTS_DIR = PROJECT_ROOT / 'data' / 'planificacion' / 'snapshots'
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
BASELINE_DATE = '2026-05-11'


def _cargar_env():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ============================================================
# 1. ventas_diarias_sku ← parquets de ventas
# ============================================================
def snapshot_ventas_diarias():
    print("[ventas_diarias] Derivando de parquets...", flush=True)
    hist = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
    mes = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
    cols = ['fecha_venta', 'sku', 'cantidad', 'venta_bruta', 'margen_front', 'tipo_movimiento']
    dfs = []
    for p in (hist, mes):
        if p.exists():
            d = pd.read_parquet(p, columns=[c for c in cols if c])
            dfs.append(d)
    if not dfs:
        print("  Sin parquets de ventas. Skip.")
        return None
    df = pd.concat(dfs, ignore_index=True)
    df = df[df['tipo_movimiento'] == 'Venta']
    df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce')
    df = df[df['fecha_venta'] >= pd.Timestamp(BASELINE_DATE)]
    df = df[df['sku'].notna() & (df['sku'].astype(str) != '')]
    df['fecha'] = df['fecha_venta'].dt.strftime('%Y-%m-%d')
    out = (df.groupby(['sku', 'fecha'], as_index=False)
             .agg(unidades=('cantidad', 'sum'),
                   venta_neta=('venta_bruta', 'sum'),
                   margen_front=('margen_front', 'sum')))
    out['sku'] = out['sku'].astype(str)
    path = SNAPSHOTS_DIR / 'planif_ventas_diarias_sku.parquet'
    out.to_parquet(path, compression='zstd', index=False)
    print(f"  OK {len(out):,} filas (sku×fecha desde {BASELINE_DATE}) → {path.name}", flush=True)
    return len(out)


# ============================================================
# 2. forecast_manual ← FORECAST FINAL XLSX
# ============================================================
def snapshot_forecast_manual():
    print("[forecast_manual] Leyendo FORECAST FINAL XLSX...", flush=True)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'efppto', str(PROJECT_ROOT / 'extract_forecast_ppto_a_turso.py'))
    mod = importlib.util.module_from_spec(spec)
    # Evitar que el módulo intente conectarse a Turso al importar
    os.environ.setdefault('LIBSQL_URL', os.environ.get('LIBSQL_URL', ''))
    spec.loader.exec_module(mod)
    df = mod.extract_xlsx_to_long()  # [sku, mes, unidades]
    if df is None or df.empty:
        print("  XLSX sin datos. Skip.")
        return None
    df['sku'] = df['sku'].astype(str)
    df['unidades'] = pd.to_numeric(df['unidades'], errors='coerce').fillna(0)
    df['fuente'] = 'xlsx_fcst_final'
    df['ts_actualizado'] = datetime.now().isoformat(timespec='seconds')
    path = SNAPSHOTS_DIR / 'planif_forecast_manual.parquet'
    df.to_parquet(path, compression='zstd', index=False)
    print(f"  OK {len(df):,} filas (sku×mes) → {path.name}", flush=True)
    return len(df)


# ============================================================
# 3. stock_live ← Odoo directo
# ============================================================
def _clasificar_bodega(bodega: str) -> str:
    """Réplica de la lógica de sync_planificacion._clasificar_bodega."""
    b = (bodega or '').lower()
    if 'meli' in b or 'mercado' in b: return 'full_meli'
    if 'fala' in b: return 'full_fala'
    if 'paris' in b: return 'full_paris'
    if 'ripley' in b: return 'full_ripley'
    if 'volcan' in b or 'volcán' in b: return 'volcan'
    if 'duty' in b or 'travel' in b: return 'duty_travel'
    if 'reserv' in b: return 'reserva'
    if 'tienda' in b: return 'tiendas'
    if 'marketing' in b or 'mkt' in b: return 'marketing'
    if 'ca1' in b or 'carrascal' in b: return 'ca1_hijas'
    return 'otros'


def snapshot_stock_live():
    print("[stock_live] Conectando a Odoo (StockAdvancedService, ~3-5 min)...", flush=True)
    _cargar_env()
    from app.core.odoo_client import OdooClient
    from app.services.stock_advanced_service import StockAdvancedService
    odoo = OdooClient(
        url='https://unionxb2b.odoo.com',
        db='bmya-innovatek-sh-prd-6981800',
        username='andres@grupoeter.cl',
        password=os.environ['ANDRES_ODOO_PASSWORD'],
    )
    svc = StockAdvancedService(odoo)
    import time as _t
    t0 = _t.time()
    data = svc.extract_full(progress_callback=None)
    print(f"  Odoo extract en {_t.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(data['detalle'])
    if df.empty:
        print("  Sin detalle stock. Skip.")
        return None
    df['categoria_bodega'] = df['Bodega'].apply(_clasificar_bodega)
    pivot = df.pivot_table(index='SKU', columns='categoria_bodega', values='Qty',
                            aggfunc='sum', fill_value=0).reset_index()
    for col in ['ca1_hijas', 'full_meli', 'full_fala', 'full_paris', 'full_ripley',
                'volcan', 'duty_travel', 'reserva', 'tiendas', 'marketing', 'otros']:
        if col not in pivot.columns:
            pivot[col] = 0
    df_agg = df.groupby('SKU').agg(
        producto=('Producto', 'first'), marca=('Marca', 'first'),
        categoria=('Categoria', 'first'), stock_total=('Qty', 'sum'),
        stock_disponible=('Disponible', 'sum'), stock_reservado=('Reservada', 'sum'),
        valor_total_clp=('Valor', 'sum'),
    ).reset_index()
    final = df_agg.merge(pivot, on='SKU', how='left').fillna(0)
    final = final.rename(columns={'SKU': 'sku'})
    final['ts_snapshot'] = datetime.now().isoformat(timespec='seconds')
    final = final[final['sku'].astype(str).str.strip() != '']
    path = SNAPSHOTS_DIR / 'planif_stock_live.parquet'
    final.to_parquet(path, compression='zstd', index=False)
    print(f"  OK {len(final):,} SKUs → {path.name}", flush=True)
    return len(final)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tabla', choices=['ventas', 'forecast', 'stock'],
                        help='Solo generar este snapshot')
    args = parser.parse_args()
    _cargar_env()

    print(f"=== Generar snapshots offline — {datetime.now()} ===\n", flush=True)
    jobs = {
        'ventas': snapshot_ventas_diarias,
        'forecast': snapshot_forecast_manual,
        'stock': snapshot_stock_live,
    }
    target = [args.tabla] if args.tabla else list(jobs.keys())
    resultados = {}
    for t in target:
        try:
            resultados[t] = jobs[t]()
        except Exception as e:
            print(f"  ✗ {t} FALLÓ: {type(e).__name__}: {str(e)[:120]}", flush=True)
            resultados[t] = None
    print(f"\n=== Resumen ===")
    for t, n in resultados.items():
        print(f"  {t:<10} {'OK ' + format(n, ',') + ' filas' if n else 'FALLÓ/vacío'}")


if __name__ == '__main__':
    main()
