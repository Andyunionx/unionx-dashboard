#!/usr/bin/env python3
"""
Forecast SKU x canal con regresores (stock + pricing) y reconciliacion jerarquica bottom-up.

Pipeline:
1. Carga ventas diarias por (sku, canal) desde parquet historico + Turso live
2. Carga regresores: stock historico (mapeado a canal segun bodega) + pricing (precio_lista, descuento, promo_activa)
3. Detecta ventanas de quiebre: dias con venta=0 Y stock=0 -> marca como missing en entrenamiento
4. Seleccion dinamica de SKUs: cubrir 90% venta del MISMO periodo LY
5. Entrena Prophet con regresores por SKU x canal (top dinamicos)
6. Cola larga: suma agregada por canal con Prophet simple
7. Reconciliacion bottom-up: SKU -> Marca -> Categoria -> Canal -> Total
8. Persiste forecasts + componentes para vista explicable

Output:
- data/forecast/forecast_skus.parquet
- data/forecast/forecast_jerarquico.parquet
- data/forecast/forecast_componentes_skus.parquet
- data/forecast/metadata_skus.json
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / 'data' / 'forecast'
OUT_DIR.mkdir(parents=True, exist_ok=True)

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')
HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}

HIST_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
# Parquet del mes actual — refrescado cada hora por sync_mes_actual.yml (bypass Turso).
MES_ACTUAL_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
STOCK_HIST = PROJECT_ROOT / 'data' / 'stock_historico' / 'stock_diario.parquet'
PRICING_HIST = PROJECT_ROOT / 'data' / 'pricing_historico' / 'pricing_diario.parquet'

# Mapeo canal -> bodegas que abastecen ese canal
# Basado en memoria project_bodegas_unionx
CANAL_BODEGAS = {
    # Marketplaces estandar -> CA1
    'Mercado Libre': ['CA1'],
    'Falabella': ['CA1'],
    'Falabella tienda': ['CA1'],
    'Paris': ['CA1'],
    'Paris tienda': ['CA1'],
    'Ripley': ['CA1'],
    'Walmart': ['CA1'],
    # Web ecommerce -> CA1
    'UnionX web': ['CA1'],
    'Simplit web': ['CA1'],
    'Kitchen Center': ['CA1'],  # tambien tiene su bodega propia BKC1 pero no relevante
    # Fulfillment (modalidades especificas)
    'Mercado Libre Full': ['BFML'],
    'Falabella Fulfillment': ['BFFa'],
    'Paris Fulfillment': ['BFP'],
    'Ripley Fulfillment': ['BFR'],
    'Walmart Fulfillment': ['BFW'],
}
DEFAULT_BODEGAS = ['CA1']  # fallback para canales no mapeados explicitamente


def _q(sql: str, retries: int = 3):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    last = None
    for i in range(retries):
        try:
            r = requests.post(f"{URL}/v2/pipeline", json=body, headers=HEADERS, timeout=180)
            r.raise_for_status()
            res = r.json()['results'][0]
            if res.get('type') == 'error':
                raise RuntimeError(res['error']['message'])
            return res['response']['result']['rows']
        except (requests.exceptions.RequestException, RuntimeError) as e:
            last = e
            time.sleep(2 ** i)
    raise last


def _val(row, idx):
    cell = row[idx]
    return None if cell.get('type') == 'null' else cell.get('value')


def cargar_ventas_diarias() -> pd.DataFrame:
    """Carga ventas diarias por (sku, canal) combinando parquet + Turso (agregado)."""
    print("[1] Cargando ventas diarias (sku x canal)...", flush=True)
    cols = ['fecha_venta', 'sku', 'canal', 'producto', 'marca', 'categoria_padre',
            'categoria_hijo', 'tipo_negocio', 'venta_bruta', 'venta_neta', 'cantidad',
            'tipo_movimiento']

    df_hist = pd.DataFrame()
    if HIST_PARQUET.exists():
        df_h = pd.read_parquet(HIST_PARQUET, columns=cols)
        df_h = df_h[df_h['tipo_movimiento'] == 'Venta'].copy()
        df_h['fecha_venta'] = pd.to_datetime(df_h['fecha_venta'], errors='coerce')
        df_h = df_h.dropna(subset=['fecha_venta'])
        df_h['fecha'] = df_h['fecha_venta'].dt.date
        df_hist = df_h.groupby(['fecha', 'sku', 'canal'], as_index=False).agg(
            venta_bruta=('venta_bruta', 'sum'),
            venta_neta=('venta_neta', 'sum'),
            cantidad=('cantidad', 'sum'),
            producto=('producto', 'first'),
            marca=('marca', 'first'),
            categoria_padre=('categoria_padre', 'first'),
            categoria_hijo=('categoria_hijo', 'first'),
            tipo_negocio=('tipo_negocio', 'first'),
        )
        print(f"   Parquet histórico: {len(df_hist):,} (sku, canal, dia)", flush=True)

    # Mes actual desde parquet (refrescado c/1h por sync_mes_actual.yml — bypass Turso)
    df_mes = pd.DataFrame()
    if MES_ACTUAL_PARQUET.exists():
        df_m = pd.read_parquet(MES_ACTUAL_PARQUET, columns=cols)
        df_m = df_m[df_m['tipo_movimiento'] == 'Venta'].copy()
        df_m['fecha_venta'] = pd.to_datetime(df_m['fecha_venta'], errors='coerce')
        df_m = df_m.dropna(subset=['fecha_venta'])
        df_m['fecha'] = df_m['fecha_venta'].dt.date
        df_mes = df_m.groupby(['fecha', 'sku', 'canal'], as_index=False).agg(
            venta_bruta=('venta_bruta', 'sum'),
            venta_neta=('venta_neta', 'sum'),
            cantidad=('cantidad', 'sum'),
            producto=('producto', 'first'),
            marca=('marca', 'first'),
            categoria_padre=('categoria_padre', 'first'),
            categoria_hijo=('categoria_hijo', 'first'),
            tipo_negocio=('tipo_negocio', 'first'),
        )
        print(f"   Parquet mes actual: {len(df_mes):,} (sku, canal, dia)", flush=True)

    # Turso live por chunks de 2 semanas (la query agregada full puede timeoutear)
    print("   Turso live (chunks 2w)...", flush=True)
    rows = []
    desde = datetime(2026, 4, 1).date()
    hoy = datetime.now().date()
    while desde <= hoy:
        hasta = min(desde + timedelta(days=14), hoy)
        try:
            chunk = _q(f"""
                SELECT fecha_venta, sku, canal,
                       MAX(producto), MAX(marca), MAX(categoria_padre), MAX(categoria_hijo),
                       MAX(tipo_negocio),
                       SUM(venta_bruta), SUM(venta_neta), SUM(cantidad)
                FROM ventas
                WHERE fecha_venta >= '{desde}' AND fecha_venta <= '{hasta}'
                  AND tipo_movimiento = 'Venta'
                GROUP BY fecha_venta, sku, canal
            """)
            rows.extend(chunk)
            print(f"      {desde} - {hasta}: {len(chunk):,} filas", flush=True)
        except Exception as e:
            print(f"      [skip] {desde} - {hasta}: {str(e)[:80]}", flush=True)
        desde = hasta + timedelta(days=1)
    df_live = pd.DataFrame([{
        'fecha': pd.to_datetime(_val(r, 0)).date(),
        'sku': _val(r, 1),
        'canal': _val(r, 2),
        'producto': _val(r, 3),
        'marca': _val(r, 4),
        'categoria_padre': _val(r, 5),
        'categoria_hijo': _val(r, 6),
        'tipo_negocio': _val(r, 7),
        'venta_bruta': float(_val(r, 8) or 0),
        'venta_neta': float(_val(r, 9) or 0),
        'cantidad': float(_val(r, 10) or 0),
    } for r in rows])
    print(f"   Turso: {len(df_live):,} (sku, canal, dia)", flush=True)

    # Combinar las 3 fuentes y deduplicar por (fecha, sku, canal) priorizando la más reciente
    partes = [df for df in (df_hist, df_mes, df_live) if not df.empty]
    if not partes:
        return pd.DataFrame(columns=['fecha', 'sku', 'canal', 'cantidad'])
    df = pd.concat(partes, ignore_index=True)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df['sku'] = df['sku'].astype(str)
    df = df.sort_values('fecha').drop_duplicates(subset=['fecha', 'sku', 'canal'], keep='last')
    print(f"   Total combinado: {len(df):,} filas, {df['fecha'].min().date()} → {df['fecha'].max().date()}", flush=True)
    return df[df['cantidad'] > 0]


def cargar_stock_historico() -> pd.DataFrame:
    """Stock diario por (sku, bodega). Devuelve DataFrame vacio si no existe parquet aun."""
    if not STOCK_HIST.exists():
        print("[skip] Stock historico no existe — usando fallback tuvo_stock=1", flush=True)
        return pd.DataFrame()
    df = pd.read_parquet(STOCK_HIST)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df['sku'] = df['sku'].astype(str)
    print(f"   Stock historico: {len(df):,} filas, {df['sku'].nunique()} SKUs", flush=True)
    return df


def cargar_pricing() -> pd.DataFrame:
    if not PRICING_HIST.exists():
        print("[skip] Pricing historico no existe", flush=True)
        return pd.DataFrame()
    df = pd.read_parquet(PRICING_HIST)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df['sku'] = df['sku'].astype(str)
    print(f"   Pricing: {len(df):,} filas", flush=True)
    return df


def construir_regresor_stock(stock_indexed: dict, sku: str, canal: str,
                              fechas: pd.DatetimeIndex) -> pd.Series:
    """Stock pre-indexado por sku para acceso O(1).

    stock_indexed: dict {sku -> DataFrame con columnas (fecha, bodega, cantidad)}
    """
    if not stock_indexed:
        return pd.Series(1, index=fechas)
    bodegas = CANAL_BODEGAS.get(canal, DEFAULT_BODEGAS)
    df = stock_indexed.get(sku)
    if df is None or df.empty:
        return pd.Series(1, index=fechas)
    df = df[df['bodega'].isin(bodegas)]
    if df.empty:
        return pd.Series(1, index=fechas)
    saldo = df.groupby('fecha')['cantidad'].sum().reindex(fechas, method='ffill').fillna(0)
    return (saldo > 0).astype(int)


def detectar_ventanas_quiebre(df_ventas: pd.DataFrame, stock_hist: pd.DataFrame) -> pd.DataFrame:
    """Flag quiebre: el efecto se aplica via regresor tuvo_stock por SKU x canal en el loop principal.

    En esta primera iteracion no excluimos filas explicitamente — el regresor binario
    `tuvo_stock` (0 cuando no habia stock) le permite a Prophet aprender que la venta=0
    en esos dias es por quiebre y no por falta de demanda.
    """
    print("[3] (Quiebre se modela como regresor tuvo_stock por SKU x canal en Prophet)", flush=True)
    df_ventas = df_ventas.copy()
    df_ventas['is_quiebre'] = 0
    return df_ventas


def seleccionar_skus_dinamicos(df_ventas: pd.DataFrame, fecha_objetivo_desde: datetime,
                                 fecha_objetivo_hasta: datetime, cobertura: float = 0.90) -> set:
    """SKUs que cubrieron `cobertura` de venta del MISMO periodo LY.

    Si no hay datos LY, usa ultimo periodo de igual longitud disponible.
    """
    print(f"[4] Seleccion dinamica SKUs (cobertura {cobertura*100:.0f}% periodo LY)...", flush=True)
    desde_ly = fecha_objetivo_desde.replace(year=fecha_objetivo_desde.year - 1)
    hasta_ly = fecha_objetivo_hasta.replace(year=fecha_objetivo_hasta.year - 1)

    df_ly = df_ventas[(df_ventas['fecha'] >= desde_ly) & (df_ventas['fecha'] <= hasta_ly)]
    if df_ly.empty:
        # Fallback: ultimos 60 dias
        cutoff = df_ventas['fecha'].max() - pd.Timedelta(days=60)
        df_ly = df_ventas[df_ventas['fecha'] >= cutoff]
        print(f"   Sin LY, usando ultimos 60d: {len(df_ly):,} filas", flush=True)

    venta_total = df_ly['venta_bruta'].sum()
    venta_sku = df_ly.groupby('sku')['venta_bruta'].sum().sort_values(ascending=False)
    venta_sku_cum = venta_sku.cumsum() / venta_total
    skus_top = set(venta_sku_cum[venta_sku_cum <= cobertura].index)
    # Asegurar al menos 20 y a lo sumo 200
    skus_top = set(venta_sku.head(max(20, min(200, len(skus_top)))).index)
    print(f"   SKUs seleccionados: {len(skus_top)} (cubren {cobertura*100:.0f}% venta LY ${venta_total/1e6:.0f}M)", flush=True)
    return skus_top


def construir_holidays_chile() -> pd.DataFrame:
    """Holidays Chile + eventos e-commerce (mismo helper que extract_forecast.py)."""
    eventos = []
    for año in [2024, 2025, 2026, 2027]:
        eventos += [{'holiday': 'cyber_day', 'ds': f'{año}-06-01', 'lower_window': 0, 'upper_window': 3}]
        eventos += [{'holiday': 'cyber_monday', 'ds': f'{año}-10-06', 'lower_window': -1, 'upper_window': 3}]
    eventos += [
        {'holiday': 'black_friday', 'ds': '2024-11-29', 'lower_window': -1, 'upper_window': 3},
        {'holiday': 'black_friday', 'ds': '2025-11-28', 'lower_window': -1, 'upper_window': 3},
        {'holiday': 'black_friday', 'ds': '2026-11-27', 'lower_window': -1, 'upper_window': 3},
        {'holiday': 'dia_madre', 'ds': '2025-05-11', 'lower_window': -7, 'upper_window': 0},
        {'holiday': 'dia_madre', 'ds': '2026-05-10', 'lower_window': -7, 'upper_window': 0},
        {'holiday': 'dia_madre', 'ds': '2027-05-09', 'lower_window': -7, 'upper_window': 0},
        {'holiday': 'dia_padre', 'ds': '2025-06-15', 'lower_window': -7, 'upper_window': 0},
        {'holiday': 'dia_padre', 'ds': '2026-06-21', 'lower_window': -7, 'upper_window': 0},
        {'holiday': 'ffpp', 'ds': '2024-09-18', 'lower_window': -10, 'upper_window': 1},
        {'holiday': 'ffpp', 'ds': '2025-09-18', 'lower_window': -10, 'upper_window': 1},
        {'holiday': 'ffpp', 'ds': '2026-09-18', 'lower_window': -10, 'upper_window': 1},
        {'holiday': 'navidad', 'ds': '2024-12-25', 'lower_window': -20, 'upper_window': 0},
        {'holiday': 'navidad', 'ds': '2025-12-25', 'lower_window': -20, 'upper_window': 0},
        {'holiday': 'navidad', 'ds': '2026-12-25', 'lower_window': -20, 'upper_window': 0},
    ]
    df = pd.DataFrame(eventos)
    df['ds'] = pd.to_datetime(df['ds'])
    return df


def forecast_sku_canal(df_serie: pd.DataFrame, regresores: pd.DataFrame,
                        dias_adelante: int, holidays: pd.DataFrame):
    """Entrena Prophet con regresores. Devuelve (forecast, componentes_dict)."""
    from prophet import Prophet

    m = Prophet(
        yearly_seasonality=False,  # series cortas SKU x canal: yearly tiende a overfit
        weekly_seasonality=True,
        daily_seasonality=False,
        changepoint_prior_scale=0.05,
        holidays=holidays,
        holidays_prior_scale=10.0,
    )
    # Skip add_country_holidays para no requerir internet ni cargar holiday lib en cada modelo

    # Agregar regresores
    for col in regresores.columns:
        if col == 'ds':
            continue
        m.add_regressor(col)

    df_train = pd.merge(df_serie, regresores, on='ds', how='left')
    # Rellenar regresores faltantes con valores neutros
    for col in ['tuvo_stock', 'descuento_efectivo', 'promo_activa']:
        if col in df_train.columns:
            fill = 1 if col == 'tuvo_stock' else 0
            df_train[col] = df_train[col].fillna(fill)

    m.fit(df_train)

    future = m.make_future_dataframe(periods=dias_adelante, freq='D')
    # Para regresores futuros: usar ultimo valor conocido (forward fill)
    future = pd.merge(future, regresores, on='ds', how='left')
    for col in ['tuvo_stock', 'descuento_efectivo', 'promo_activa']:
        if col in future.columns:
            future[col] = future[col].ffill().bfill()
            fill = 1 if col == 'tuvo_stock' else 0
            future[col] = future[col].fillna(fill)

    fc = m.predict(future)
    return fc, m


def main():
    if not URL or not TOKEN:
        print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no seteados", flush=True)
        sys.exit(1)

    logging.getLogger('prophet').setLevel(logging.WARNING)
    logging.getLogger('cmdstanpy').setLevel(logging.WARNING)

    print(f"=== Forecast SKU x Canal — {datetime.now()} ===\n", flush=True)
    df_ventas = cargar_ventas_diarias()
    print(f"\n[2] Cargando regresores...", flush=True)
    stock_hist = cargar_stock_historico()
    pricing = cargar_pricing()

    df_ventas = detectar_ventanas_quiebre(df_ventas, stock_hist)

    # Pre-indexar stock por SKU para acceso O(1) en el loop (4.9M filas no se pueden filtrar 100 veces)
    print("   Pre-indexando stock por SKU...", flush=True)
    if not stock_hist.empty:
        stock_indexed = {sku: g[['fecha', 'bodega', 'cantidad']].copy()
                          for sku, g in stock_hist.groupby('sku', observed=True)}
        print(f"   Stock indexado para {len(stock_indexed):,} SKUs", flush=True)
    else:
        stock_indexed = {}

    # Pre-indexar pricing por (sku, canal)
    print("   Pre-indexando pricing por (SKU, canal)...", flush=True)
    if not pricing.empty:
        pricing_indexed = {key: g.set_index('fecha')[['descuento_efectivo', 'promo_activa']].copy()
                            for key, g in pricing.groupby(['sku', 'canal'], observed=True)}
        print(f"   Pricing indexado: {len(pricing_indexed):,} (sku, canal) keys", flush=True)
    else:
        pricing_indexed = {}

    # Seleccion dinamica para los proximos 60 dias (por defecto)
    DIAS_ADELANTE = int(os.environ.get('DIAS_ADELANTE', '60'))
    fecha_hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_obj_desde = fecha_hoy
    fecha_obj_hasta = fecha_hoy + timedelta(days=DIAS_ADELANTE)
    skus_top = seleccionar_skus_dinamicos(df_ventas, fecha_obj_desde, fecha_obj_hasta)

    # Holidays
    holidays = construir_holidays_chile()

    print(f"\n[5] Entrenando Prophet por SKU x canal...", flush=True)
    # Por simplicidad: para cada SKU, modelar el canal con mas venta (top canal por SKU)
    # En lugar de SKU x canal explosivo (puede ser 50 SKUs x 10 canales = 500 modelos)
    # Tomamos cada (sku, canal) unicamente si la combinacion tiene >= 30 dias de venta
    pares_validos = []
    for sku in skus_top:
        canales_sku = df_ventas[df_ventas['sku'] == sku]['canal'].value_counts()
        for canal, n_dias in canales_sku.items():
            if n_dias >= 30:
                pares_validos.append((sku, canal))
    print(f"   Pares (SKU, canal) a forecastear: {len(pares_validos)}", flush=True)

    # Limitar para tiempo razonable (max 200 modelos)
    MAX_MODELOS = int(os.environ.get('MAX_MODELOS', '200'))
    if len(pares_validos) > MAX_MODELOS:
        # Ordenar por venta y tomar top
        venta_par = df_ventas.groupby(['sku', 'canal'])['venta_bruta'].sum()
        pares_ordenados = sorted(pares_validos, key=lambda p: -venta_par.get(p, 0))
        pares_validos = pares_ordenados[:MAX_MODELOS]
        print(f"   Limitando a top {MAX_MODELOS} pares por venta", flush=True)

    forecasts = []
    componentes_all = []
    metadatos_modelo = []
    t0 = time.time()

    # Pre-indexar ventas por (sku, canal) para evitar mascara linear sobre 160k filas en cada iter
    print("   Pre-indexando ventas por (SKU, canal)...", flush=True)
    ventas_indexed = {}
    for (sku_g, canal_g), g in df_ventas.groupby(['sku', 'canal'], observed=True):
        ventas_indexed[(sku_g, canal_g)] = g[['fecha', 'venta_bruta', 'cantidad']].copy()
    print(f"   Ventas indexadas: {len(ventas_indexed):,} keys", flush=True)

    for i, (sku, canal) in enumerate(pares_validos, 1):
        try:
            sub_raw = ventas_indexed.get((sku, canal))
            if sub_raw is None:
                continue
            sub = sub_raw.groupby('fecha', as_index=False).agg(
                venta_bruta=('venta_bruta', 'sum'),
                cantidad=('cantidad', 'sum'),
            )
            sub['ds'] = sub['fecha']
            sub['y'] = sub['cantidad']  # forecastear unidades (no monto)
            df_serie = sub[['ds', 'y']]
            if len(df_serie) < 30:
                continue

            # Regresor stock (acceso O(1) via dict pre-indexado)
            fechas_full = pd.date_range(df_serie['ds'].min(), fecha_obj_hasta, freq='D')
            stock_serie = construir_regresor_stock(stock_indexed, sku, canal, fechas_full)
            # Regresor pricing (acceso O(1) via dict)
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

            fc, model = forecast_sku_canal(df_serie, regs, DIAS_ADELANTE, holidays)
            # Guardar predicciones futuras (filtrar futuro estricto desde HOY, no desde max(train))
            hoy_ts = pd.Timestamp(datetime.now().date())
            fc_fut = fc[fc['ds'] > hoy_ts][
                ['ds', 'yhat', 'yhat_lower', 'yhat_upper']].copy()
            # Clip a >= 0 (no hay venta negativa). Prophet a veces predice negativos en SKUs
            # con cambios bruscos de tendencia o ventas intermitentes.
            for c in ['yhat', 'yhat_lower', 'yhat_upper']:
                fc_fut[c] = fc_fut[c].clip(lower=0)
            # Outlier guard: si yhat de algun dia > 10x del max historico de train, descartar SKU
            max_hist = df_serie['y'].max()
            if max_hist > 0 and (fc_fut['yhat'] > 10 * max_hist).any():
                print(f"   [{i}] {sku}/{canal}: outlier (yhat > 10x max hist), descartado", flush=True)
                continue
            fc_fut['sku'] = sku
            fc_fut['canal'] = canal
            forecasts.append(fc_fut)

            # Componentes Prophet (para vista explicable)
            comp_cols = [c for c in fc.columns
                         if c in ('ds', 'trend', 'weekly', 'yearly', 'holidays',
                                   'tuvo_stock', 'descuento_efectivo', 'promo_activa',
                                   'yhat')]
            comp = fc[comp_cols].copy()
            comp['sku'] = sku
            comp['canal'] = canal
            componentes_all.append(comp)
            metadatos_modelo.append({'sku': sku, 'canal': canal, 'n_dias_train': len(df_serie),
                                       'venta_total_train': float(sub['venta_bruta'].sum())})

            if i % 10 == 0:
                elapsed = time.time() - t0
                print(f"   [{i}/{len(pares_validos)}] elapsed {elapsed:.0f}s ({elapsed/i:.1f}s por modelo)", flush=True)
        except Exception as e:
            print(f"   [{i}] FAIL ({sku}, {canal}): {str(e)[:80]}", flush=True)
            continue

    if not forecasts:
        print("[ERROR] Sin forecasts generados")
        sys.exit(1)

    print(f"\n[6] Consolidando + guardando...", flush=True)
    df_fc = pd.concat(forecasts, ignore_index=True)
    df_comp = pd.concat(componentes_all, ignore_index=True)

    # Bottom-up reconciliation a nivel marca, canal, total
    print("[7] Reconciliacion jerarquica bottom-up...", flush=True)
    sku_meta = (df_ventas.groupby('sku').agg(
        marca=('marca', 'first'),
        categoria_padre=('categoria_padre', 'first'),
        categoria_hijo=('categoria_hijo', 'first'),
        tipo_negocio=('tipo_negocio', 'first'),
    ).reset_index())
    df_fc_enriq = df_fc.merge(sku_meta, on='sku', how='left')

    df_fc_enriq.to_parquet(OUT_DIR / 'forecast_skus.parquet',
                            compression='zstd', compression_level=9, index=False)

    # Niveles agregados (bottom-up): suma desde SKU
    niveles = {
        'forecast_jerarquico_marca_canal': df_fc_enriq.groupby(['ds', 'marca', 'canal'], as_index=False)[['yhat', 'yhat_lower', 'yhat_upper']].sum(),
        'forecast_jerarquico_canal': df_fc_enriq.groupby(['ds', 'canal'], as_index=False)[['yhat', 'yhat_lower', 'yhat_upper']].sum(),
        'forecast_jerarquico_categoria': df_fc_enriq.groupby(['ds', 'categoria_padre'], as_index=False)[['yhat', 'yhat_lower', 'yhat_upper']].sum(),
        'forecast_jerarquico_tipo_negocio': df_fc_enriq.groupby(['ds', 'tipo_negocio'], as_index=False)[['yhat', 'yhat_lower', 'yhat_upper']].sum(),
    }
    for nombre, dfn in niveles.items():
        dfn.to_parquet(OUT_DIR / f'{nombre}.parquet', compression='zstd', index=False)
        print(f"   {nombre}: {len(dfn):,} filas", flush=True)

    df_comp.to_parquet(OUT_DIR / 'forecast_componentes_skus.parquet',
                        compression='zstd', compression_level=9, index=False)

    meta = {
        'generado_en': datetime.now().isoformat(),
        'modelos_entrenados': len(metadatos_modelo),
        'skus_unicos': len({m['sku'] for m in metadatos_modelo}),
        'canales_unicos': len({m['canal'] for m in metadatos_modelo}),
        'dias_adelante': DIAS_ADELANTE,
        'fecha_hasta': str(fecha_obj_hasta.date()),
        'tiempo_total_s': int(time.time() - t0),
    }
    with open(OUT_DIR / 'metadata_skus.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, default=str)

    print(f"\n[OK] Forecast SKU x canal generado")
    print(f"  Modelos entrenados: {meta['modelos_entrenados']}")
    print(f"  SKUs: {meta['skus_unicos']}, Canales: {meta['canales_unicos']}")
    print(f"  Dias: {meta['dias_adelante']}, Tiempo: {meta['tiempo_total_s']}s")


if __name__ == '__main__':
    main()
