"""Auditoría comparativa del Prophet actual vs alternativas tuneadas.

Backtest sobre la serie diaria TOTAL (venta_bruta CLP) usando parquet histórico
local — sin Turso (evita el bloqueo).

Compara:
  1. Prophet ADITIVO   + cp=0.05  (config actual)
  2. Prophet MULTIPL.  + cp=0.05  (cambio mínimo)
  3. Prophet MULTIPL.  + cp=0.5   (mayor flexibilidad changepoints)
  4. Prophet MULTIPL.  + cp=0.5 + holidays_prior_scale=20
  5. Naive estacional  (DOY hace 1 año × factor de crecimiento YTD)
  6. MA(30)            (media móvil últimas 4 semanas)

Backtest: 3 cortes rolling (cada uno predice 60 días hacia adelante).
Métricas: MAPE, sesgo %, MAE.

Output:
  data/forecast/audit_v2_results.json
  data/forecast/audit_v2_predicciones.parquet  (cada config × ds × yhat)
"""
import json
import logging
import os
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')
logging.getLogger('prophet').setLevel(logging.WARNING)
logging.getLogger('cmdstanpy').setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).parent
HIST_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
LIVE_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
OUT_DIR = PROJECT_ROOT / 'data' / 'forecast'
OUT_DIR.mkdir(parents=True, exist_ok=True)

HORIZONTE = 60          # días por backtest
CORTES = 3              # cortes rolling


def cargar_serie() -> pd.DataFrame:
    """Carga venta diaria TOTAL desde parquet (hist + live, sin Turso)."""
    print(f"[1] Cargando serie diaria total...", flush=True)
    df_hist = pd.DataFrame()
    if HIST_PARQUET.exists():
        df_h = pd.read_parquet(HIST_PARQUET, columns=['fecha_venta', 'venta_bruta', 'tipo_movimiento'])
        df_h = df_h[df_h['tipo_movimiento'] == 'Venta']
        df_h['fecha_venta'] = pd.to_datetime(df_h['fecha_venta'], errors='coerce')
        df_h = df_h.dropna(subset=['fecha_venta'])
        df_hist = df_h.groupby(df_h['fecha_venta'].dt.date)['venta_bruta'].sum().reset_index()
        df_hist.columns = ['ds', 'y']

    df_live = pd.DataFrame()
    if LIVE_PARQUET.exists():
        df_l = pd.read_parquet(LIVE_PARQUET, columns=['fecha_venta', 'venta_bruta', 'tipo_movimiento'])
        df_l = df_l[df_l['tipo_movimiento'] == 'Venta']
        df_l['fecha_venta'] = pd.to_datetime(df_l['fecha_venta'], errors='coerce')
        df_l = df_l.dropna(subset=['fecha_venta'])
        df_live = df_l.groupby(df_l['fecha_venta'].dt.date)['venta_bruta'].sum().reset_index()
        df_live.columns = ['ds', 'y']

    df = pd.concat([df_hist, df_live]).drop_duplicates(subset='ds', keep='last').sort_values('ds')
    df['ds'] = pd.to_datetime(df['ds'])
    df = df[df['y'] > 0].reset_index(drop=True)
    print(f"  Serie: {len(df)} días, desde {df['ds'].min().date()} a {df['ds'].max().date()}", flush=True)
    return df


def _holidays_chile() -> pd.DataFrame:
    """Holidays custom (cyberday, ffpp, navidad)."""
    eventos = []
    for anio in (2024, 2025, 2026):
        eventos.extend([
            {'holiday': 'cyberday', 'ds': f'{anio}-05-29', 'lower_window': -2, 'upper_window': 3},
            {'holiday': 'ffpp', 'ds': f'{anio}-09-18', 'lower_window': -10, 'upper_window': 1},
            {'holiday': 'navidad', 'ds': f'{anio}-12-25', 'lower_window': -20, 'upper_window': 0},
            {'holiday': 'black_friday', 'ds': f'{anio}-11-29', 'lower_window': -3, 'upper_window': 1},
        ])
    df = pd.DataFrame(eventos)
    df['ds'] = pd.to_datetime(df['ds'])
    return df


def fit_prophet(train: pd.DataFrame, horizonte: int, seasonality_mode: str,
                cp_prior: float, holidays_prior: float = 10.0):
    from prophet import Prophet
    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,
        seasonality_mode=seasonality_mode,
        changepoint_prior_scale=cp_prior,
        holidays=_holidays_chile(),
        holidays_prior_scale=holidays_prior,
    )
    try:
        m.add_country_holidays(country_name='CL')
    except Exception:
        pass
    m.fit(train)
    future = m.make_future_dataframe(periods=horizonte, freq='D')
    return m.predict(future)


def fit_naive_estacional(train: pd.DataFrame, horizonte: int) -> pd.DataFrame:
    """Predicción = venta mismo DOY hace 365 días × factor de crecimiento YTD."""
    train = train.copy()
    train['ds'] = pd.to_datetime(train['ds'])
    # Factor de crecimiento: ventas últimos 90d vs mismo período año anterior
    fin = train['ds'].max()
    ini_90 = fin - pd.Timedelta(days=90)
    ini_90_ly = ini_90 - pd.DateOffset(years=1)
    fin_ly = fin - pd.DateOffset(years=1)
    vta_90 = train[train['ds'] >= ini_90]['y'].sum()
    vta_90_ly = train[(train['ds'] >= ini_90_ly) & (train['ds'] <= fin_ly)]['y'].sum()
    factor = (vta_90 / vta_90_ly) if vta_90_ly > 0 else 1.0

    # Construir predicción para días futuros
    future_ds = pd.date_range(fin + pd.Timedelta(days=1), periods=horizonte, freq='D')
    # Buscar el mismo día calendar del año anterior en train
    ds_ly = future_ds - pd.DateOffset(years=1)
    map_ly = dict(zip(train['ds'].dt.date, train['y']))
    yhat = [(map_ly.get(d.date(), 0) * factor) for d in ds_ly]
    return pd.DataFrame({'ds': future_ds, 'yhat': yhat})


def fit_ma30(train: pd.DataFrame, horizonte: int) -> pd.DataFrame:
    """MA(30) extrapolado constante."""
    media = train['y'].tail(30).mean()
    future_ds = pd.date_range(train['ds'].max() + pd.Timedelta(days=1), periods=horizonte, freq='D')
    return pd.DataFrame({'ds': future_ds, 'yhat': [media] * horizonte})


def metricas(real: pd.Series, pred: pd.Series) -> dict:
    """MAPE, sesgo %, MAE."""
    r = real.values.astype(float)
    p = np.maximum(pred.values.astype(float), 0)
    if len(r) == 0:
        return {'n': 0}
    mask = r > 0
    mape = float(np.mean(np.abs(r[mask] - p[mask]) / r[mask]) * 100) if mask.any() else None
    sesgo = float((p.sum() - r.sum()) / max(r.sum(), 1) * 100)
    mae = float(np.mean(np.abs(r - p)))
    return {
        'n': len(r),
        'real_total': float(r.sum()),
        'pred_total': float(p.sum()),
        'mape_pct': mape,
        'sesgo_pct': sesgo,
        'mae': mae,
    }


def run_backtest(df: pd.DataFrame) -> dict:
    """3 cortes rolling, 6 modelos cada uno."""
    df = df.copy()
    df['ds'] = pd.to_datetime(df['ds'])
    fin = df['ds'].max()
    # 3 cortes: fin-60, fin-120, fin-180 (cada uno predice 60d hacia adelante)
    cortes = [fin - pd.Timedelta(days=60 + i * 60) for i in range(CORTES)]

    configs = [
        ('prophet_aditivo_cp005',  lambda t, h: fit_prophet(t, h, 'additive',       0.05)),
        ('prophet_multipl_cp005',  lambda t, h: fit_prophet(t, h, 'multiplicative', 0.05)),
        ('prophet_multipl_cp05',   lambda t, h: fit_prophet(t, h, 'multiplicative', 0.5)),
        ('prophet_multipl_cp05_hp20', lambda t, h: fit_prophet(t, h, 'multiplicative', 0.5, 20.0)),
        ('naive_estacional',       lambda t, h: fit_naive_estacional(t, h)),
        ('ma30',                   lambda t, h: fit_ma30(t, h)),
    ]

    resultados = {}
    todas_preds = []

    for corte in cortes:
        train = df[df['ds'] <= corte].copy()
        test = df[(df['ds'] > corte) & (df['ds'] <= corte + pd.Timedelta(days=HORIZONTE))].copy()
        if len(train) < 90 or test.empty:
            print(f"  [skip corte {corte.date()}]: train={len(train)} test={len(test)}", flush=True)
            continue

        print(f"\n[Corte {corte.date()}] train={len(train)}d, test={len(test)}d", flush=True)
        for nombre, fn in configs:
            try:
                t0 = datetime.now()
                fc = fn(train, HORIZONTE)
                dur = (datetime.now() - t0).total_seconds()
                fc_future = fc[fc['ds'] > corte][['ds', 'yhat']].copy()
                merged = pd.merge(test[['ds', 'y']], fc_future, on='ds', how='inner')
                if merged.empty:
                    print(f"  {nombre:<30} sin overlap test/fc", flush=True)
                    continue
                m = metricas(merged['y'], merged['yhat'])
                m['fit_seconds'] = dur
                key = f'{nombre}__{corte.date()}'
                resultados[key] = m
                print(f"  {nombre:<30} MAPE={m['mape_pct']:>6.1f}%  sesgo={m['sesgo_pct']:>+7.1f}%  "
                      f"real={m['real_total']/1e6:>5.0f}M  pred={m['pred_total']/1e6:>5.0f}M  ({dur:.0f}s)", flush=True)
                # Guardar predicciones para inspección
                merged['config'] = nombre
                merged['corte'] = corte.date().isoformat()
                todas_preds.append(merged)
            except Exception as e:
                print(f"  {nombre:<30} ERROR: {type(e).__name__}: {str(e)[:80]}", flush=True)

    # Agregado: MAPE/sesgo promedio por config (cross cortes)
    print(f"\n=== RESUMEN (promedio sobre {CORTES} cortes) ===", flush=True)
    agg = {}
    for nombre, _ in configs:
        keys = [k for k in resultados if k.startswith(nombre + '__')]
        if not keys:
            continue
        mapes = [resultados[k]['mape_pct'] for k in keys if resultados[k].get('mape_pct') is not None]
        sesgos = [resultados[k]['sesgo_pct'] for k in keys]
        reales = sum(resultados[k]['real_total'] for k in keys)
        preds = sum(resultados[k]['pred_total'] for k in keys)
        agg[nombre] = {
            'mape_promedio': float(np.mean(mapes)) if mapes else None,
            'sesgo_promedio': float(np.mean(sesgos)),
            'sesgo_consolidado_pct': float((preds - reales) / max(reales, 1) * 100),
            'real_total_M': reales / 1e6,
            'pred_total_M': preds / 1e6,
            'n_cortes': len(keys),
        }
        print(f"  {nombre:<30} MAPE_avg={agg[nombre]['mape_promedio'] or 0:>6.1f}%  "
              f"sesgo_avg={agg[nombre]['sesgo_promedio']:>+7.1f}%  "
              f"sesgo_consol={agg[nombre]['sesgo_consolidado_pct']:>+7.1f}%", flush=True)

    if todas_preds:
        df_preds = pd.concat(todas_preds, ignore_index=True)
        df_preds.to_parquet(OUT_DIR / 'audit_v2_predicciones.parquet', index=False)

    return {'agregado': agg, 'por_corte': resultados}


def main():
    df = cargar_serie()
    result = run_backtest(df)
    out = OUT_DIR / 'audit_v2_results.json'
    out.write_text(json.dumps(result, indent=2, default=str, ensure_ascii=False), encoding='utf-8')
    print(f"\n[OK] Resultados: {out}", flush=True)

    # Veredicto: el mejor por sesgo consolidado y MAPE
    if result.get('agregado'):
        best_sesgo = min(result['agregado'].items(),
                          key=lambda x: abs(x[1]['sesgo_consolidado_pct']))
        best_mape = min(((k, v) for k, v in result['agregado'].items() if v.get('mape_promedio')),
                         key=lambda x: x[1]['mape_promedio'])
        print(f"\n🏆 Mejor SESGO consolidado: {best_sesgo[0]} ({best_sesgo[1]['sesgo_consolidado_pct']:+.1f}%)", flush=True)
        print(f"🏆 Mejor MAPE promedio:     {best_mape[0]} ({best_mape[1]['mape_promedio']:.1f}%)", flush=True)


if __name__ == '__main__':
    main()
