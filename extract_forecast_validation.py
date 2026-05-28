#!/usr/bin/env python3
"""
Cross-validation del forecast SKU x canal: MAPE retrospectivo.

Para cada (sku, canal) en el forecast:
1. Re-entrena Prophet con TODOS los datos hasta hace 60 dias
2. Predice los proximos 60 dias
3. Compara contra el real -> calcula MAPE, RMSE, sesgo

Output:
- data/forecast/forecast_validation.parquet (sku, canal, mape, rmse, sesgo, n_dias)
- data/forecast/validation_summary.json (agregados por nivel)
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / 'data' / 'forecast'
OUT_DIR.mkdir(parents=True, exist_ok=True)

URL = os.environ.get('LIBSQL_URL', '').strip().rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '').strip()
HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}

HIST_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
STOCK_HIST = PROJECT_ROOT / 'data' / 'stock_historico' / 'stock_diario.parquet'
PRICING_HIST = PROJECT_ROOT / 'data' / 'pricing_historico' / 'pricing_diario.parquet'
FC_SKUS = PROJECT_ROOT / 'data' / 'forecast' / 'forecast_skus.parquet'

# Reusar mismo mapeo que extract_forecast_skus
sys.path.insert(0, str(PROJECT_ROOT))
from extract_forecast_skus import (
    CANAL_BODEGAS, DEFAULT_BODEGAS, construir_holidays_chile,
    construir_regresor_stock, _q, _val,
)


def cargar_ventas_diarias() -> pd.DataFrame:
    """Carga ventas diarias por (sku, canal) — solo lo necesario para validation."""
    cols = ['fecha_venta', 'sku', 'canal', 'venta_bruta', 'cantidad', 'tipo_movimiento']
    df_hist = pd.DataFrame()
    if HIST_PARQUET.exists():
        df_h = pd.read_parquet(HIST_PARQUET, columns=cols)
        df_h = df_h[df_h['tipo_movimiento'] == 'Venta'].copy()
        df_h['fecha_venta'] = pd.to_datetime(df_h['fecha_venta'], errors='coerce')
        df_h = df_h.dropna(subset=['fecha_venta'])
        df_h['fecha'] = df_h['fecha_venta'].dt.date
        df_hist = df_h.groupby(['fecha', 'sku', 'canal'], as_index=False).agg(
            cantidad=('cantidad', 'sum'),
        )
    # Turso por chunks
    rows = []
    desde = datetime(2026, 4, 1).date()
    hoy = datetime.now().date()
    while desde <= hoy:
        hasta = min(desde + timedelta(days=14), hoy)
        try:
            chunk = _q(f"""
                SELECT fecha_venta, sku, canal, SUM(cantidad)
                FROM ventas
                WHERE fecha_venta >= '{desde}' AND fecha_venta <= '{hasta}'
                  AND tipo_movimiento = 'Venta'
                GROUP BY fecha_venta, sku, canal
            """)
            rows.extend(chunk)
        except Exception:
            pass
        desde = hasta + timedelta(days=1)
    df_live = pd.DataFrame([{
        'fecha': pd.to_datetime(_val(r, 0)).date(),
        'sku': _val(r, 1),
        'canal': _val(r, 2),
        'cantidad': float(_val(r, 3) or 0),
    } for r in rows])
    df = pd.concat([df_hist, df_live], ignore_index=True) if not df_hist.empty else df_live
    df['fecha'] = pd.to_datetime(df['fecha'])
    df['sku'] = df['sku'].astype(str)
    return df[df['cantidad'] > 0]


def validar_sku_canal(sku: str, canal: str, ventas: pd.DataFrame,
                       stock_indexed: dict, pricing_indexed: dict,
                       holidays: pd.DataFrame, fecha_corte: pd.Timestamp,
                       horizonte: int = 60) -> dict | None:
    """
    Re-entrena con datos hasta fecha_corte, predice horizonte dias,
    compara contra real. Devuelve metrica.
    """
    from prophet import Prophet

    sub = ventas[(ventas['sku'] == sku) & (ventas['canal'] == canal)].copy()
    if len(sub) < 30:
        return None

    # Train: hasta fecha_corte
    train = sub[sub['fecha'] <= fecha_corte].copy()
    test = sub[(sub['fecha'] > fecha_corte) & (sub['fecha'] <= fecha_corte + pd.Timedelta(days=horizonte))].copy()

    if len(train) < 30 or test.empty:
        return None

    train['ds'] = train['fecha']
    train['y'] = train['cantidad']
    df_serie = train[['ds', 'y']].sort_values('ds').reset_index(drop=True)

    # Regresores
    fechas_full = pd.date_range(df_serie['ds'].min(),
                                 fecha_corte + pd.Timedelta(days=horizonte), freq='D')
    stock_serie = construir_regresor_stock(stock_indexed, sku, canal, fechas_full)
    pri_df = pricing_indexed.get((sku, canal))
    if pri_df is not None and not pri_df.empty:
        pri = pri_df.reindex(fechas_full).ffill().fillna({'descuento_efectivo': 0, 'promo_activa': 0})
    else:
        pri = pd.DataFrame({'descuento_efectivo': 0, 'promo_activa': 0}, index=fechas_full)

    regs = pd.DataFrame({
        'ds': fechas_full,
        'tuvo_stock': stock_serie.values,
        'descuento_efectivo': pri['descuento_efectivo'].values,
        'promo_activa': pri['promo_activa'].values,
    })

    try:
        m = Prophet(yearly_seasonality=False, weekly_seasonality=True,
                     daily_seasonality=False, changepoint_prior_scale=0.05,
                     holidays=holidays, holidays_prior_scale=10.0)
        for col in ['tuvo_stock', 'descuento_efectivo', 'promo_activa']:
            m.add_regressor(col)
        df_train = pd.merge(df_serie, regs, on='ds', how='left')
        for col in ['tuvo_stock', 'descuento_efectivo', 'promo_activa']:
            df_train[col] = df_train[col].fillna(1 if col == 'tuvo_stock' else 0)
        m.fit(df_train)

        future = pd.DataFrame({'ds': fechas_full})
        future = pd.merge(future, regs, on='ds', how='left')
        for col in ['tuvo_stock', 'descuento_efectivo', 'promo_activa']:
            future[col] = future[col].ffill().fillna(1 if col == 'tuvo_stock' else 0)
        fc = m.predict(future)
    except Exception as e:
        return {'sku': sku, 'canal': canal, 'error': str(e)[:80]}

    fc_test = fc[fc['ds'] > fecha_corte][['ds', 'yhat']].copy()
    test['ds'] = test['fecha']
    merged = pd.merge(test[['ds', 'cantidad']], fc_test, on='ds', how='inner')
    if merged.empty:
        return None

    real = merged['cantidad'].values
    pred = np.maximum(merged['yhat'].values, 0)
    n = len(merged)
    # MAPE: solo cuando real > 0
    mask = real > 0
    mape = float(np.mean(np.abs(real[mask] - pred[mask]) / real[mask]) * 100) if mask.any() else None
    rmse = float(np.sqrt(np.mean((real - pred) ** 2)))
    bias = float(np.mean(pred - real))
    sma = float(np.mean(np.abs(real - pred)) / max(np.mean(real), 1) * 100)  # MAE relativa
    return {
        'sku': sku, 'canal': canal,
        'n_dias_train': len(df_serie),
        'n_dias_test': n,
        'venta_real_test': float(real.sum()),
        'venta_pred_test': float(pred.sum()),
        'mape_pct': mape,
        'rmse': rmse,
        'sesgo': bias,
        'mae_rel_pct': sma,
    }


def backtest_prophet_total(ventas: pd.DataFrame, holidays: pd.DataFrame,
                            fecha_corte: pd.Timestamp, horizonte: int = 60) -> dict:
    """Backtest del Prophet TOTAL (serie agregada). Mide sesgo a nivel total."""
    from prophet import Prophet
    print(f"\n[X] Backtest Prophet TOTAL: train hasta {fecha_corte.date()}, predict {horizonte}d", flush=True)

    # Serie diaria total
    df_diario = ventas.groupby('fecha', as_index=False)['cantidad'].sum()
    df_diario['ds'] = df_diario['fecha']
    df_diario['y'] = df_diario['cantidad']
    train = df_diario[df_diario['ds'] <= fecha_corte][['ds', 'y']]
    test = df_diario[(df_diario['ds'] > fecha_corte) &
                      (df_diario['ds'] <= fecha_corte + pd.Timedelta(days=horizonte))]
    if len(train) < 90 or test.empty:
        return {}

    m = Prophet(yearly_seasonality=True, weekly_seasonality=True, daily_seasonality=False,
                 changepoint_prior_scale=0.05, holidays=holidays, holidays_prior_scale=10.0)
    m.fit(train)
    future = m.make_future_dataframe(periods=horizonte, freq='D')
    fc = m.predict(future)
    fc_test = fc[fc['ds'] > fecha_corte][['ds', 'yhat']]
    merged = pd.merge(test[['ds', 'cantidad']], fc_test, on='ds', how='inner')
    if merged.empty:
        return {}
    real = merged['cantidad'].values
    pred = np.maximum(merged['yhat'].values, 0)
    mape = float(np.mean(np.abs(real - pred) / np.maximum(real, 1)) * 100)
    sesgo_pct = float((pred.sum() - real.sum()) / max(real.sum(), 1) * 100)
    print(f"   TOTAL real {real.sum():.0f} unid, predicho {pred.sum():.0f} unid, sesgo {sesgo_pct:+.1f}%, MAPE {mape:.1f}%", flush=True)
    return {
        'venta_real_total': float(real.sum()),
        'venta_pred_total': float(pred.sum()),
        'sesgo_total_pct': sesgo_pct,
        'mape_total_pct': mape,
        'n_dias': len(merged),
    }


def main():
    if not URL or not TOKEN:
        print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no seteados", flush=True)
        sys.exit(1)

    logging.getLogger('prophet').setLevel(logging.WARNING)
    logging.getLogger('cmdstanpy').setLevel(logging.WARNING)

    print(f"=== Validation Prophet (MAPE backtest 60d) — {datetime.now()} ===\n", flush=True)

    if not FC_SKUS.exists():
        print("[ERROR] forecast_skus.parquet no existe. Correr extract_forecast_skus primero.")
        sys.exit(1)

    df_fc = pd.read_parquet(FC_SKUS)
    pares_a_validar = df_fc[['sku', 'canal']].drop_duplicates().values.tolist()
    print(f"[1] Pares (sku, canal) a validar: {len(pares_a_validar)}", flush=True)

    ventas = cargar_ventas_diarias()
    print(f"[2] Ventas cargadas: {len(ventas):,} filas", flush=True)

    # Pre-indexar stock + pricing
    stock_indexed = {}
    if STOCK_HIST.exists():
        sh = pd.read_parquet(STOCK_HIST)
        sh['fecha'] = pd.to_datetime(sh['fecha'])
        sh['sku'] = sh['sku'].astype(str)
        stock_indexed = {sku: g[['fecha', 'bodega', 'cantidad']].copy()
                          for sku, g in sh.groupby('sku', observed=True)}
    pricing_indexed = {}
    if PRICING_HIST.exists():
        ph = pd.read_parquet(PRICING_HIST)
        ph['fecha'] = pd.to_datetime(ph['fecha'])
        ph['sku'] = ph['sku'].astype(str)
        pricing_indexed = {key: g.set_index('fecha')[['descuento_efectivo', 'promo_activa']].copy()
                            for key, g in ph.groupby(['sku', 'canal'], observed=True)}
    print(f"[3] Stock indexado: {len(stock_indexed):,}, Pricing: {len(pricing_indexed):,}", flush=True)

    holidays = construir_holidays_chile()
    fecha_corte = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=60)
    print(f"[4] Backtest: train hasta {fecha_corte.date()}, predict 60d hacia adelante", flush=True)

    resultados = []
    t0 = time.time()
    for i, (sku, canal) in enumerate(pares_a_validar, 1):
        try:
            r = validar_sku_canal(str(sku), canal, ventas, stock_indexed, pricing_indexed,
                                    holidays, fecha_corte, horizonte=60)
            if r:
                resultados.append(r)
            if i % 10 == 0:
                elapsed = time.time() - t0
                print(f"   [{i}/{len(pares_a_validar)}] {elapsed:.0f}s ({elapsed/i:.1f}s/par)", flush=True)
        except Exception as e:
            print(f"   [{i}] FAIL ({sku}, {canal}): {str(e)[:80]}", flush=True)

    if not resultados:
        print("[ERROR] Sin resultados de validation")
        sys.exit(1)

    df_val = pd.DataFrame(resultados)
    out = OUT_DIR / 'forecast_validation.parquet'
    df_val.to_parquet(out, compression='zstd', compression_level=9, index=False)
    print(f"\n[5] {out}: {len(df_val):,} filas", flush=True)

    # Metricas agregadas
    sku_meta = pd.DataFrame()
    if HIST_PARQUET.exists():
        h = pd.read_parquet(HIST_PARQUET, columns=['sku', 'marca', 'categoria_padre'])
        sku_meta = h.drop_duplicates('sku').set_index('sku')

    df_val_clean = df_val.dropna(subset=['mape_pct'])
    # Backtest del Prophet TOTAL (serie agregada) para medir sesgo a nivel total
    bt_total = backtest_prophet_total(ventas, holidays, fecha_corte, horizonte=60)

    summary = {
        'generado_en': datetime.now().isoformat(),
        'pares_validados': len(df_val),
        'pares_con_mape': len(df_val_clean),
        'mape_pct_p50': float(df_val_clean['mape_pct'].median()) if not df_val_clean.empty else None,
        'mape_pct_p75': float(df_val_clean['mape_pct'].quantile(0.75)) if not df_val_clean.empty else None,
        'mape_pct_promedio': float(df_val_clean['mape_pct'].mean()) if not df_val_clean.empty else None,
        'mae_rel_pct_p50': float(df_val['mae_rel_pct'].median()),
        'sesgo_promedio': float(df_val['sesgo'].mean()),
        'venta_real_total_test': float(df_val['venta_real_test'].sum()),
        'venta_pred_total_test': float(df_val['venta_pred_test'].sum()),
        'sesgo_global_pct': float(
            (df_val['venta_pred_test'].sum() - df_val['venta_real_test'].sum())
            / max(df_val['venta_real_test'].sum(), 1) * 100
        ),
        'prophet_total_backtest': bt_total,
    }
    with open(OUT_DIR / 'validation_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n[OK] Validation completa")
    print(f"  Pares con MAPE: {summary['pares_con_mape']}/{summary['pares_validados']}")
    print(f"  MAPE p50: {summary['mape_pct_p50']:.1f}%, p75: {summary['mape_pct_p75']:.1f}%, prom: {summary['mape_pct_promedio']:.1f}%")
    print(f"  Sesgo global (over/under-forecast): {summary['sesgo_global_pct']:+.1f}%")
    print(f"  Venta real test: {summary['venta_real_total_test']:.0f} unid, predicha: {summary['venta_pred_total_test']:.0f} unid")


if __name__ == '__main__':
    main()
