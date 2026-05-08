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


def _build_holidays_chile() -> pd.DataFrame:
    """Holidays Chile + eventos e-commerce custom (CyberDay, CyberMonday, etc).

    Estos picos son fundamentales para no subestimar oct/nov y junio.
    """
    eventos = []
    # Cyber Day Chile (CCS) — primera semana junio típicamente
    for anio in [2024, 2025, 2026, 2027]:
        eventos += [{'holiday': 'cyber_day', 'ds': f'{anio}-06-01', 'lower_window': 0, 'upper_window': 3}]
    # CyberMonday Chile (CCS) — primera semana de octubre
    for anio in [2024, 2025, 2026, 2027]:
        eventos += [{'holiday': 'cyber_monday', 'ds': f'{anio}-10-06', 'lower_window': -1, 'upper_window': 3}]
    # Black Friday — último viernes noviembre
    eventos += [
        {'holiday': 'black_friday', 'ds': '2024-11-29', 'lower_window': -1, 'upper_window': 3},
        {'holiday': 'black_friday', 'ds': '2025-11-28', 'lower_window': -1, 'upper_window': 3},
        {'holiday': 'black_friday', 'ds': '2026-11-27', 'lower_window': -1, 'upper_window': 3},
    ]
    # Día de la Madre Chile (segundo domingo mayo)
    eventos += [
        {'holiday': 'dia_madre', 'ds': '2025-05-11', 'lower_window': -7, 'upper_window': 0},
        {'holiday': 'dia_madre', 'ds': '2026-05-10', 'lower_window': -7, 'upper_window': 0},
        {'holiday': 'dia_madre', 'ds': '2027-05-09', 'lower_window': -7, 'upper_window': 0},
    ]
    # Día del Padre Chile (tercer domingo junio)
    eventos += [
        {'holiday': 'dia_padre', 'ds': '2025-06-15', 'lower_window': -7, 'upper_window': 0},
        {'holiday': 'dia_padre', 'ds': '2026-06-21', 'lower_window': -7, 'upper_window': 0},
    ]
    # Fiestas Patrias (18 sept — semana previa con compras)
    eventos += [
        {'holiday': 'ffpp', 'ds': '2024-09-18', 'lower_window': -10, 'upper_window': 1},
        {'holiday': 'ffpp', 'ds': '2025-09-18', 'lower_window': -10, 'upper_window': 1},
        {'holiday': 'ffpp', 'ds': '2026-09-18', 'lower_window': -10, 'upper_window': 1},
    ]
    # Navidad (compras intensas 1-24 dic)
    eventos += [
        {'holiday': 'navidad', 'ds': '2024-12-25', 'lower_window': -20, 'upper_window': 0},
        {'holiday': 'navidad', 'ds': '2025-12-25', 'lower_window': -20, 'upper_window': 0},
        {'holiday': 'navidad', 'ds': '2026-12-25', 'lower_window': -20, 'upper_window': 0},
    ]
    df = pd.DataFrame(eventos)
    df['ds'] = pd.to_datetime(df['ds'])
    return df


def _entrenar_prophet(df: pd.DataFrame, dias_adelante: int, with_holidays: bool = True):
    """Entrena Prophet, devuelve (modelo, forecast df). Reutilizable para anual."""
    from prophet import Prophet
    import logging
    logging.getLogger('prophet').setLevel(logging.WARNING)
    logging.getLogger('cmdstanpy').setLevel(logging.WARNING)

    holidays_df = _build_holidays_chile() if with_holidays else None
    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,
        changepoint_prior_scale=0.05,
        holidays=holidays_df,
        holidays_prior_scale=10.0,  # peso fuerte a eventos e-commerce
    )
    # Holidays oficiales Chile (feriados)
    try:
        m.add_country_holidays(country_name='CL')
    except Exception:
        pass  # holidays library puede fallar offline

    m.fit(df)
    future = m.make_future_dataframe(periods=dias_adelante, freq='D')
    fc = m.predict(future)
    return m, fc


def forecast_diario_total(df: pd.DataFrame, dias_adelante: int = 90) -> pd.DataFrame:
    """Entrena Prophet sobre venta diaria total y proyecta dias_adelante (default 90)."""
    print(f"[2/5] Entrenando Prophet 90d (venta diaria total, {len(df)} días, +holidays)...", flush=True)
    t0 = time.time()
    m, fc = _entrenar_prophet(df, dias_adelante, with_holidays=True)
    print(f"  [OK] Entrenado en {time.time()-t0:.0f}s\n", flush=True)

    out = fc[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].copy()
    for c in ['yhat', 'yhat_lower', 'yhat_upper']:
        out[c] = out[c].round(0)
    # Guardar también modelo+componentes para vista "Año" y "Componentes"
    return out, m, fc


def forecast_anual(df: pd.DataFrame, m=None, fc=None) -> tuple:
    """Forecast 365 días. Reutiliza modelo si ya está entrenado, sino reentrena."""
    print("[3/5] Forecast anual (365 días)...", flush=True)
    t0 = time.time()
    if m is None:
        m, fc = _entrenar_prophet(df, dias_adelante=365, with_holidays=True)
    else:
        # Extender el horizonte sobre el modelo existente
        future = m.make_future_dataframe(periods=365, freq='D')
        fc = m.predict(future)
    print(f"  [OK] {time.time()-t0:.0f}s\n", flush=True)

    out = fc[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].copy()
    for c in ['yhat', 'yhat_lower', 'yhat_upper']:
        out[c] = out[c].round(0)
    return out, m, fc


def extraer_componentes(m, fc) -> dict:
    """Extrae componentes de Prophet (trend, weekly, yearly, holidays) para vista de diagnóstico."""
    print("[4/5] Extrayendo componentes Prophet...", flush=True)
    cols = ['ds', 'trend', 'weekly', 'yearly']
    if 'holidays' in fc.columns:
        cols.append('holidays')
    df_comp = fc[cols].copy()
    return df_comp


def forecast_por_canal(top_n: int = 10, dias_adelante: int = 30) -> pd.DataFrame:
    """Forecast Prophet por top N canales. Una sola query agrupada para no quemar Turso."""
    from prophet import Prophet
    import logging
    logging.getLogger('prophet').setLevel(logging.WARNING)
    logging.getLogger('cmdstanpy').setLevel(logging.WARNING)

    print(f"[3/4] Forecasts por canal (top {top_n})...", flush=True)

    # Top canales: desde parquet histórico (últimos 12 meses) para no quemar Turso
    canales = []
    if HIST_PARQUET.exists():
        df_h = pd.read_parquet(HIST_PARQUET, columns=['fecha_venta', 'canal', 'venta_bruta', 'tipo_movimiento'])
        df_h = df_h[df_h['tipo_movimiento'] == 'Venta']
        df_h['fecha_venta'] = pd.to_datetime(df_h['fecha_venta'], errors='coerce')
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=365)
        df_h = df_h[df_h['fecha_venta'] >= cutoff]
        top = df_h.groupby('canal')['venta_bruta'].sum().sort_values(ascending=False).head(top_n)
        canales = top.index.tolist()
        print(f"  Top {len(canales)} canales (desde parquet últimos 12m): {canales}", flush=True)
    else:
        # Fallback: query Turso con rango chico
        rows = _q(f"""
            SELECT canal, ROUND(SUM(venta_bruta), 0)
            FROM ventas
            WHERE fecha_venta >= date('now', '-90 days') AND tipo_movimiento = 'Venta'
            GROUP BY canal
            ORDER BY 2 DESC LIMIT {top_n}
        """)
        canales = [_val(r, 0) for r in rows]
        print(f"  Top {len(canales)} canales (desde Turso 90d): {canales}", flush=True)

    # UNA sola query Turso para todos los canales (april+)
    canales_sql = ",".join("'" + c.replace("'", "''") + "'" for c in canales)
    print("  Query agrupada Turso (1 sola request)...", flush=True)
    rows_live = _q(f"""
        SELECT canal, fecha_venta, ROUND(SUM(venta_bruta), 0)
        FROM ventas
        WHERE canal IN ({canales_sql})
          AND fecha_venta >= '2026-04-01'
          AND tipo_movimiento = 'Venta'
        GROUP BY canal, fecha_venta
    """)
    df_live = pd.DataFrame([{
        'canal': _val(r, 0),
        'ds': pd.to_datetime(_val(r, 1)),
        'y': float(_val(r, 2) or 0),
    } for r in rows_live])
    print(f"  Turso live: {len(df_live)} filas (canal-fecha)")

    # Histórico parquet (1 sola lectura, filtrado en pandas)
    df_hist = pd.DataFrame()
    if HIST_PARQUET.exists():
        df_h = pd.read_parquet(HIST_PARQUET, columns=['fecha_venta', 'canal', 'venta_bruta', 'tipo_movimiento'])
        df_h = df_h[(df_h['canal'].isin(canales)) & (df_h['tipo_movimiento'] == 'Venta')]
        df_h['fecha_venta'] = pd.to_datetime(df_h['fecha_venta'], errors='coerce')
        df_h = df_h.dropna(subset=['fecha_venta'])
        df_hist = df_h.groupby([df_h['canal'], df_h['fecha_venta'].dt.date])['venta_bruta'].sum().reset_index()
        df_hist.columns = ['canal', 'ds', 'y']
        df_hist['ds'] = pd.to_datetime(df_hist['ds'])
        print(f"  Histórico parquet: {len(df_hist)} filas (canal-fecha)")

    all_fcs = []
    for i, canal in enumerate(canales, 1):
        df_h_c = df_hist[df_hist['canal'] == canal][['ds', 'y']] if not df_hist.empty else pd.DataFrame()
        df_l_c = df_live[df_live['canal'] == canal][['ds', 'y']]

        if not df_h_c.empty:
            df_full = pd.concat([df_h_c, df_l_c]).drop_duplicates(subset='ds').sort_values('ds')
        else:
            df_full = df_l_c.sort_values('ds')

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


def _suma_periodo_ly(df_hist: pd.DataFrame, fecha_desde: pd.Timestamp, fecha_hasta: pd.Timestamp) -> float:
    """Suma venta del parquet histórico para un rango (para comparativas LY)."""
    if df_hist.empty:
        return 0.0
    mask = (df_hist['fecha_venta'] >= fecha_desde) & (df_hist['fecha_venta'] <= fecha_hasta)
    return float(df_hist.loc[mask, 'venta_bruta'].sum())


def main():
    fecha_actual = datetime.now().date()
    print(f"=== Forecast UnionX — {fecha_actual} ===\n", flush=True)

    # 1. Cargar serie completa
    df_total = cargar_serie_diaria_total()
    if len(df_total) < 60:
        print("[ERROR] Menos de 60 días de historia, no se puede entrenar Prophet")
        sys.exit(1)

    # 2. Entrenar Prophet con horizonte anual (cubre 90d y 365d en un solo modelo)
    fc_anual_df, m, fc_full = forecast_diario_total(df_total, dias_adelante=365)

    # Slice 90 días para vista corta + 365 para vista anual
    fc_90 = fc_anual_df[fc_anual_df['ds'] <= pd.Timestamp(fecha_actual) + pd.Timedelta(days=90)].copy()
    fc_90.to_parquet(OUTPUT_DIR / 'forecast_diario.parquet', compression='zstd', index=False)
    fc_anual_df.to_parquet(OUTPUT_DIR / 'forecast_anual.parquet', compression='zstd', index=False)

    # Componentes (trend, weekly, yearly, holidays) — para vista de diagnóstico
    df_componentes = extraer_componentes(m, fc_full)
    df_componentes.to_parquet(OUTPUT_DIR / 'forecast_componentes.parquet', compression='zstd', index=False)

    # 3. Forecast por canal (top 10, próximos 30 días)
    fc_canal = forecast_por_canal(top_n=10, dias_adelante=30)
    if not fc_canal.empty:
        fc_canal.to_parquet(OUTPUT_DIR / 'forecast_canal.parquet', compression='zstd', index=False)

    # 4. Resumen multi-horizonte
    print("[5/5] Calculando proyecciones multi-horizonte...", flush=True)

    fc_anual_df['ds'] = pd.to_datetime(fc_anual_df['ds']).dt.date

    # Cargar parquet histórico para comparativas LY (1 sola lectura)
    df_hist = pd.DataFrame()
    if HIST_PARQUET.exists():
        df_hist = pd.read_parquet(HIST_PARQUET, columns=['fecha_venta', 'venta_bruta', 'tipo_movimiento'])
        df_hist = df_hist[df_hist['tipo_movimiento'] == 'Venta'].copy()
        df_hist['fecha_venta'] = pd.to_datetime(df_hist['fecha_venta'], errors='coerce')

    # ===== Cierre del mes =====
    primer_dia_mes = fecha_actual.replace(day=1)
    if fecha_actual.month == 12:
        ultimo_dia_mes = fecha_actual.replace(year=fecha_actual.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        ultimo_dia_mes = fecha_actual.replace(month=fecha_actual.month + 1, day=1) - timedelta(days=1)

    rows = _q(f"""
        SELECT ROUND(SUM(venta_bruta), 0) FROM ventas
        WHERE fecha_venta >= '{primer_dia_mes}' AND fecha_venta <= '{fecha_actual}'
        AND tipo_movimiento = 'Venta'
    """)
    venta_actual_mes = float(_val(rows[0], 0) or 0) if rows else 0

    fc_pendiente = fc_anual_df[(fc_anual_df['ds'] > fecha_actual) & (fc_anual_df['ds'] <= ultimo_dia_mes)]
    venta_pendiente = float(fc_pendiente['yhat'].sum())
    proyeccion_mes = venta_actual_mes + venta_pendiente

    primer_dia_ly = primer_dia_mes.replace(year=primer_dia_mes.year - 1)
    ultimo_dia_ly = ultimo_dia_mes.replace(year=ultimo_dia_mes.year - 1)
    venta_ly_mes_completo = _suma_periodo_ly(df_hist, pd.Timestamp(primer_dia_ly), pd.Timestamp(ultimo_dia_ly))
    pct_vs_ly = ((proyeccion_mes - venta_ly_mes_completo) / venta_ly_mes_completo * 100) if venta_ly_mes_completo else None

    # ===== Horizontes 30/60/90 días =====
    horizontes = {}
    for n_dias in [30, 60, 90]:
        fc_h = fc_anual_df[(fc_anual_df['ds'] > fecha_actual) & (fc_anual_df['ds'] <= fecha_actual + timedelta(days=n_dias))]
        proy = float(fc_h['yhat'].sum())
        # Comparativa LY (mismo rango año atrás)
        desde_ly = pd.Timestamp(fecha_actual.replace(year=fecha_actual.year - 1)) + pd.Timedelta(days=1)
        hasta_ly = pd.Timestamp(fecha_actual.replace(year=fecha_actual.year - 1)) + pd.Timedelta(days=n_dias)
        ly = _suma_periodo_ly(df_hist, desde_ly, hasta_ly)
        horizontes[f'{n_dias}d'] = {
            'proyeccion': proy,
            'venta_ly_mismo_rango': ly,
            'pct_vs_ly': ((proy - ly) / ly * 100) if ly > 0 else None,
        }

    # ===== Año calendario actual =====
    primer_dia_anio = fecha_actual.replace(month=1, day=1)
    ultimo_dia_anio = fecha_actual.replace(month=12, day=31)

    # Venta acumulada YTD desde Turso (cubre todo el año hasta hoy)
    rows_ytd = _q(f"""
        SELECT ROUND(SUM(venta_bruta), 0) FROM ventas
        WHERE fecha_venta >= '{primer_dia_anio}' AND fecha_venta <= '{fecha_actual}'
        AND tipo_movimiento = 'Venta'
    """)
    venta_ytd = float(_val(rows_ytd[0], 0) or 0) if rows_ytd else 0
    # Si Turso no tiene todo el año, completar con parquet
    if not df_hist.empty:
        ytd_parquet = _suma_periodo_ly(
            df_hist,
            pd.Timestamp(primer_dia_anio),
            pd.Timestamp(min(fecha_actual, df_hist['fecha_venta'].max().date())),
        )
        # Tomar el mayor (Turso puede no tener pre-abril)
        venta_ytd = max(venta_ytd, ytd_parquet)

    # Forecast resto del año
    fc_resto_anio = fc_anual_df[(fc_anual_df['ds'] > fecha_actual) & (fc_anual_df['ds'] <= ultimo_dia_anio)]
    proyeccion_resto_anio = float(fc_resto_anio['yhat'].sum())
    proyeccion_anio = venta_ytd + proyeccion_resto_anio

    # Año LY completo
    venta_anio_ly = _suma_periodo_ly(
        df_hist,
        pd.Timestamp(primer_dia_anio.replace(year=fecha_actual.year - 1)),
        pd.Timestamp(ultimo_dia_anio.replace(year=fecha_actual.year - 1)),
    )
    pct_anio_vs_ly = ((proyeccion_anio - venta_anio_ly) / venta_anio_ly * 100) if venta_anio_ly else None

    # Tabla mes a mes (proyección + LY)
    fc_anual_df['ds_dt'] = pd.to_datetime(fc_anual_df['ds'])
    fc_anual_df['anio'] = fc_anual_df['ds_dt'].dt.year
    fc_anual_df['mes'] = fc_anual_df['ds_dt'].dt.month
    tabla_mensual = []
    for mes in range(1, 13):
        primer_d = fecha_actual.replace(month=mes, day=1)
        if mes == 12:
            ultimo_d = fecha_actual.replace(year=fecha_actual.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            ultimo_d = fecha_actual.replace(month=mes + 1, day=1) - timedelta(days=1)

        # Real (Turso/parquet) si ya pasó parcial o completo
        if ultimo_d <= fecha_actual:
            # Mes pasado completo
            rows_m = _q(f"""
                SELECT ROUND(SUM(venta_bruta), 0) FROM ventas
                WHERE fecha_venta >= '{primer_d}' AND fecha_venta <= '{ultimo_d}'
                AND tipo_movimiento = 'Venta'
            """)
            real = float(_val(rows_m[0], 0) or 0) if rows_m else 0
            if real == 0 and not df_hist.empty:
                real = _suma_periodo_ly(df_hist, pd.Timestamp(primer_d), pd.Timestamp(ultimo_d))
            proy_mes = real
            tipo = 'real'
        elif primer_d <= fecha_actual <= ultimo_d:
            # Mes en curso = proyección (real YTD del mes + forecast pendiente)
            proy_mes = proyeccion_mes
            tipo = 'mixto'
        else:
            # Mes futuro = forecast
            fc_m = fc_anual_df[(fc_anual_df['ds'] >= primer_d) & (fc_anual_df['ds'] <= ultimo_d)]
            proy_mes = float(fc_m['yhat'].sum())
            tipo = 'forecast'

        # LY del mismo mes
        ly = _suma_periodo_ly(
            df_hist,
            pd.Timestamp(primer_d.replace(year=fecha_actual.year - 1)),
            pd.Timestamp(ultimo_d.replace(year=fecha_actual.year - 1)),
        )
        tabla_mensual.append({
            'mes': mes,
            'mes_nombre': primer_d.strftime('%b'),
            'proyeccion': round(proy_mes, 0),
            'venta_ly': round(ly, 0),
            'pct_vs_ly': ((proy_mes - ly) / ly * 100) if ly > 0 else None,
            'tipo': tipo,
        })

    resumen = {
        'generado_en': datetime.now().isoformat(),
        'fecha_actual': str(fecha_actual),
        'mes': fecha_actual.strftime('%Y-%m'),
        'anio': fecha_actual.year,
        # Mes en curso
        'venta_actual_mes': venta_actual_mes,
        'venta_pendiente_estimada': venta_pendiente,
        'proyeccion_mes': proyeccion_mes,
        'venta_ly_mes_completo': venta_ly_mes_completo,
        'pct_vs_ly': pct_vs_ly,
        'dias_actuales': (fecha_actual - primer_dia_mes).days + 1,
        'dias_pendientes': (ultimo_dia_mes - fecha_actual).days,
        # Horizontes 30/60/90
        'horizontes': horizontes,
        # Año calendario
        'anio_proyeccion': {
            'venta_ytd': venta_ytd,
            'proyeccion_resto_anio': proyeccion_resto_anio,
            'proyeccion_anio_completo': proyeccion_anio,
            'venta_anio_ly': venta_anio_ly,
            'pct_anio_vs_ly': pct_anio_vs_ly,
            'tabla_mensual': tabla_mensual,
        },
    }
    with open(OUTPUT_DIR / 'forecast_resumen.json', 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2, default=str)

    print(f"\n  Mes actual ({fecha_actual.strftime('%B %Y')}): proy ${proyeccion_mes/1e6:.1f}M ({pct_vs_ly:+.1f}% vs LY)" if pct_vs_ly else f"\n  Mes actual: ${proyeccion_mes/1e6:.1f}M")
    print(f"  Próximos 30d: ${horizontes['30d']['proyeccion']/1e6:.1f}M ({horizontes['30d']['pct_vs_ly']:+.1f}% vs LY)" if horizontes['30d']['pct_vs_ly'] else f"  Próximos 30d: ${horizontes['30d']['proyeccion']/1e6:.1f}M")
    print(f"  Próximos 60d: ${horizontes['60d']['proyeccion']/1e6:.1f}M ({horizontes['60d']['pct_vs_ly']:+.1f}% vs LY)" if horizontes['60d']['pct_vs_ly'] else f"  Próximos 60d: ${horizontes['60d']['proyeccion']/1e6:.1f}M")
    print(f"  Próximos 90d: ${horizontes['90d']['proyeccion']/1e6:.1f}M ({horizontes['90d']['pct_vs_ly']:+.1f}% vs LY)" if horizontes['90d']['pct_vs_ly'] else f"  Próximos 90d: ${horizontes['90d']['proyeccion']/1e6:.1f}M")
    print(f"  Año {fecha_actual.year}: ${proyeccion_anio/1e6:.0f}M ({pct_anio_vs_ly:+.1f}% vs {venta_anio_ly/1e6:.0f}M LY)" if pct_anio_vs_ly else f"  Año {fecha_actual.year}: ${proyeccion_anio/1e6:.0f}M")

    print(f"\n[OK] Forecasts generados en {OUTPUT_DIR}/")


if __name__ == '__main__':
    main()
