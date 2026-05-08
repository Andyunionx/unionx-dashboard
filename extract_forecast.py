#!/usr/bin/env python3
"""
Forecast diario y mensual con Prophet (Meta).

Genera:
- data/forecast/forecast_diario.parquet  (próximos 60 días: ds, yhat, yhat_lower, yhat_upper)
- data/forecast/forecast_canal.parquet   (top 10 canales próximos 30 días)
- data/forecast/forecast_resumen.json    (KPIs de proyección fin de mes)

Diseñado para correr en GH Actions cada día.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')

if not URL or not TOKEN:
    print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no seteados", flush=True)
    sys.exit(1)

HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}

PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / 'data' / 'forecast'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Cargar parquet histórico para no quemar Turso
HIST_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'


def _q(sql: str):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    r = requests.post(f"{URL}/v2/pipeline", json=body, headers=HEADERS, timeout=300)
    r.raise_for_status()
    return r.json()['results'][0]['response']['result']['rows']


def _val(row, idx):
    cell = row[idx]
    if cell.get('type') == 'null':
        return None
    return cell.get('value')


def cargar_serie_diaria_total() -> pd.DataFrame:
    """Carga venta diaria TOTAL combinando parquet histórico + Turso live."""
    print("[1/4] Cargando serie histórica completa...", flush=True)

    # Parte 1: parquet histórico (pre 2026-04-01)
    df_hist = pd.DataFrame()
    if HIST_PARQUET.exists():
        df_h = pd.read_parquet(HIST_PARQUET, columns=['fecha_venta', 'venta_bruta', 'tipo_movimiento'])
        df_h = df_h[df_h['tipo_movimiento'] == 'Venta']
        df_h['fecha_venta'] = pd.to_datetime(df_h['fecha_venta'], errors='coerce')
        df_h = df_h.dropna(subset=['fecha_venta'])
        df_hist = df_h.groupby(df_h['fecha_venta'].dt.date)['venta_bruta'].sum().reset_index()
        df_hist.columns = ['ds', 'y']
        print(f"  Parquet histórico: {len(df_hist)} días (pre-abril)")

    # Parte 2: Turso (April+)
    rows = _q("""
        SELECT fecha_venta, ROUND(SUM(venta_bruta), 0)
        FROM ventas
        WHERE fecha_venta >= '2026-04-01' AND tipo_movimiento = 'Venta'
        GROUP BY fecha_venta
        ORDER BY fecha_venta
    """)
    df_live = pd.DataFrame([{
        'ds': pd.to_datetime(_val(r, 0)),
        'y': float(_val(r, 1) or 0),
    } for r in rows])
    print(f"  Turso live: {len(df_live)} días (abril+)")

    # Combinar
    if not df_hist.empty:
        df_hist['ds'] = pd.to_datetime(df_hist['ds'])
        df = pd.concat([df_hist, df_live], ignore_index=True).drop_duplicates(subset='ds').sort_values('ds')
    else:
        df = df_live

    df = df[df['y'] > 0]  # quitar días con venta=0 (puede ser cierre)
    print(f"  Total combinado: {len(df)} días desde {df['ds'].min().date()} a {df['ds'].max().date()}\n")
    return df


def forecast_diario_total(df: pd.DataFrame, dias_adelante: int = 60) -> pd.DataFrame:
    """Entrena Prophet sobre venta diaria total y proyecta dias_adelante."""
    print(f"[2/4] Entrenando Prophet (venta diaria total, {len(df)} días)...", flush=True)
    from prophet import Prophet

    t0 = time.time()
    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,
        changepoint_prior_scale=0.05,  # menos overfitting
    )
    # Logger silencioso
    import logging
    logging.getLogger('prophet').setLevel(logging.WARNING)
    logging.getLogger('cmdstanpy').setLevel(logging.WARNING)

    m.fit(df)
    future = m.make_future_dataframe(periods=dias_adelante, freq='D')
    fc = m.predict(future)
    elapsed = time.time() - t0
    print(f"  [OK] Entrenado en {elapsed:.0f}s\n", flush=True)

    out = fc[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].copy()
    out['yhat'] = out['yhat'].round(0)
    out['yhat_lower'] = out['yhat_lower'].round(0)
    out['yhat_upper'] = out['yhat_upper'].round(0)
    return out


def forecast_por_canal(top_n: int = 10, dias_adelante: int = 30) -> pd.DataFrame:
    """Forecast Prophet por top N canales (más rápido que todos)."""
    from prophet import Prophet
    import logging
    logging.getLogger('prophet').setLevel(logging.WARNING)
    logging.getLogger('cmdstanpy').setLevel(logging.WARNING)

    print(f"[3/4] Forecasts por canal (top {top_n})...", flush=True)

    # Top canales
    rows = _q(f"""
        SELECT canal, ROUND(SUM(venta_bruta), 0)
        FROM ventas
        WHERE fecha_venta >= '2026-01-01' AND tipo_movimiento = 'Venta'
        GROUP BY canal
        ORDER BY 2 DESC LIMIT {top_n}
    """)
    canales = [_val(r, 0) for r in rows]
    print(f"  Top {len(canales)} canales: {canales}", flush=True)

    all_fcs = []
    for i, canal in enumerate(canales, 1):
        canal_safe = canal.replace("'", "''")
        # Cargar serie del canal (parquet + Turso)
        df_canal = pd.DataFrame()

        if HIST_PARQUET.exists():
            df_h = pd.read_parquet(HIST_PARQUET, columns=['fecha_venta', 'canal', 'venta_bruta', 'tipo_movimiento'])
            df_h = df_h[(df_h['canal'] == canal) & (df_h['tipo_movimiento'] == 'Venta')]
            df_h['fecha_venta'] = pd.to_datetime(df_h['fecha_venta'], errors='coerce')
            df_h = df_h.dropna(subset=['fecha_venta'])
            df_h = df_h.groupby(df_h['fecha_venta'].dt.date)['venta_bruta'].sum().reset_index()
            df_h.columns = ['ds', 'y']
            df_canal = df_h

        rows_live = _q(f"""
            SELECT fecha_venta, ROUND(SUM(venta_bruta), 0) FROM ventas
            WHERE canal = '{canal_safe}' AND fecha_venta >= '2026-04-01' AND tipo_movimiento = 'Venta'
            GROUP BY fecha_venta
        """)
        df_l = pd.DataFrame([{'ds': pd.to_datetime(_val(r, 0)), 'y': float(_val(r, 1) or 0)} for r in rows_live])

        if not df_canal.empty:
            df_canal['ds'] = pd.to_datetime(df_canal['ds'])
            df_full = pd.concat([df_canal, df_l]).drop_duplicates(subset='ds').sort_values('ds')
        else:
            df_full = df_l

        df_full = df_full[df_full['y'] > 0]

        if len(df_full) < 30:
            print(f"  [{i}/{len(canales)}] {canal}: solo {len(df_full)} días, skip")
            continue

        try:
            m = Prophet(yearly_seasonality=True, weekly_seasonality=True, daily_seasonality=False, changepoint_prior_scale=0.05)
            m.fit(df_full)
            future = m.make_future_dataframe(periods=dias_adelante, freq='D')
            fc = m.predict(future)
            fc_only_future = fc[fc['ds'] > df_full['ds'].max()][['ds', 'yhat', 'yhat_lower', 'yhat_upper']].copy()
            fc_only_future['canal'] = canal
            all_fcs.append(fc_only_future)
            print(f"  [{i}/{len(canales)}] {canal}: OK ({len(fc_only_future)} días pronosticados)")
        except Exception as e:
            print(f"  [{i}/{len(canales)}] {canal}: error {e}")

    if not all_fcs:
        return pd.DataFrame()

    df_out = pd.concat(all_fcs, ignore_index=True)
    df_out['yhat'] = df_out['yhat'].round(0)
    df_out['yhat_lower'] = df_out['yhat_lower'].round(0)
    df_out['yhat_upper'] = df_out['yhat_upper'].round(0)
    return df_out


def main():
    fecha_actual = datetime.now().date()
    print(f"=== Forecast UnionX — {fecha_actual} ===\n", flush=True)

    # 1. Cargar serie completa
    df_total = cargar_serie_diaria_total()
    if len(df_total) < 60:
        print("[ERROR] Menos de 60 días de historia, no se puede entrenar Prophet")
        sys.exit(1)

    # 2. Forecast diario total (próximos 60 días)
    fc_total = forecast_diario_total(df_total, dias_adelante=60)
    fc_total.to_parquet(OUTPUT_DIR / 'forecast_diario.parquet', compression='zstd', index=False)

    # 3. Forecast por canal (top 10, próximos 30 días)
    fc_canal = forecast_por_canal(top_n=10, dias_adelante=30)
    if not fc_canal.empty:
        fc_canal.to_parquet(OUTPUT_DIR / 'forecast_canal.parquet', compression='zstd', index=False)

    # 4. Resumen: proyección fin de mes
    print("[4/4] Calculando proyección fin de mes...", flush=True)
    primer_dia_mes = fecha_actual.replace(day=1)
    if fecha_actual.month == 12:
        ultimo_dia_mes = fecha_actual.replace(year=fecha_actual.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        ultimo_dia_mes = fecha_actual.replace(month=fecha_actual.month + 1, day=1) - timedelta(days=1)

    # Venta acumulada del mes actual
    rows = _q(f"""
        SELECT ROUND(SUM(venta_bruta), 0) FROM ventas
        WHERE fecha_venta >= '{primer_dia_mes}' AND fecha_venta <= '{fecha_actual}'
        AND tipo_movimiento = 'Venta'
    """)
    venta_actual_mes = float(_val(rows[0], 0) or 0) if rows else 0

    # Forecast de los días que faltan del mes
    fc_total['ds'] = pd.to_datetime(fc_total['ds']).dt.date
    fc_pendiente = fc_total[(fc_total['ds'] > fecha_actual) & (fc_total['ds'] <= ultimo_dia_mes)]
    venta_pendiente = float(fc_pendiente['yhat'].sum())

    proyeccion_mes = venta_actual_mes + venta_pendiente

    # Comparar contra LY
    primer_dia_ly = primer_dia_mes.replace(year=primer_dia_mes.year - 1)
    ultimo_dia_ly = ultimo_dia_mes.replace(year=ultimo_dia_mes.year - 1)
    rows_ly = _q(f"""
        SELECT ROUND(SUM(venta_bruta), 0) FROM ventas
        WHERE fecha_venta >= '{primer_dia_ly}' AND fecha_venta <= '{ultimo_dia_ly}'
        AND tipo_movimiento = 'Venta'
    """)
    venta_ly_mes_completo = float(_val(rows_ly[0], 0) or 0) if rows_ly else 0

    pct_vs_ly = ((proyeccion_mes - venta_ly_mes_completo) / venta_ly_mes_completo * 100) if venta_ly_mes_completo else None

    resumen = {
        'generado_en': datetime.now().isoformat(),
        'fecha_actual': str(fecha_actual),
        'mes': fecha_actual.strftime('%Y-%m'),
        'venta_actual_mes': venta_actual_mes,
        'venta_pendiente_estimada': venta_pendiente,
        'proyeccion_mes': proyeccion_mes,
        'venta_ly_mes_completo': venta_ly_mes_completo,
        'pct_vs_ly': pct_vs_ly,
        'dias_actuales': (fecha_actual - primer_dia_mes).days + 1,
        'dias_pendientes': (ultimo_dia_mes - fecha_actual).days,
    }
    with open(OUTPUT_DIR / 'forecast_resumen.json', 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2, default=str)

    print(f"\n  Mes actual: {fecha_actual.strftime('%B %Y')}")
    print(f"  Venta acumulada: ${venta_actual_mes/1e6:.1f}M ({resumen['dias_actuales']} días)")
    print(f"  Forecast pendiente: ${venta_pendiente/1e6:.1f}M ({resumen['dias_pendientes']} días)")
    print(f"  Proyección fin de mes: ${proyeccion_mes/1e6:.1f}M")
    if pct_vs_ly is not None:
        print(f"  vs LY mismo mes ({venta_ly_mes_completo/1e6:.1f}M): {pct_vs_ly:+.1f}%")

    print(f"\n[OK] Forecasts generados en {OUTPUT_DIR}/")


if __name__ == '__main__':
    main()
