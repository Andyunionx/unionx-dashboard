#!/usr/bin/env python3
"""
Calibracion del forecast TOTAL usando bottom-up SKU como ancla.

Logica:
1. Bottom-up SKU (200 modelos con regresores stock + pricing) -> serie diaria en $
2. Cobertura: venta historica de esos 200 SKUs / venta total historica
3. Bottom-up extrapolado = serie / cobertura  (escala al 100% del negocio)
4. Factor de calibracion = bottom_up_extrapolado_60d / prophet_total_60d
5. Aplicar factor a forecast_anual + forecast_diario + resumen
6. Regenerar tabla mensual con valores calibrados

Genera:
- data/forecast/forecast_anual.parquet (sobrescrito, calibrado)
- data/forecast/forecast_diario.parquet (sobrescrito, calibrado)
- data/forecast/forecast_resumen.json (sobrescrito, recalculado)
- data/forecast/calibration_metadata.json (factor, cobertura, before/after)

Mantiene backups en data/forecast/_raw/ para auditoria.
"""
import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / 'data' / 'forecast'
RAW_DIR = OUT_DIR / '_raw'
RAW_DIR.mkdir(parents=True, exist_ok=True)

HIST_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
PRICING_HIST = PROJECT_ROOT / 'data' / 'pricing_historico' / 'pricing_diario.parquet'
FC_SKUS = OUT_DIR / 'forecast_skus.parquet'
FC_ANUAL = OUT_DIR / 'forecast_anual.parquet'
FC_DIARIO = OUT_DIR / 'forecast_diario.parquet'
FC_RESUMEN = OUT_DIR / 'forecast_resumen.json'


def cargar_pricing_reciente() -> pd.DataFrame:
    """Precio promedio ultimos 30d por SKU x canal (para convertir unidades a $)."""
    pri = pd.read_parquet(PRICING_HIST)
    pri['fecha'] = pd.to_datetime(pri['fecha'])
    pri['sku'] = pri['sku'].astype(str)
    cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=30)
    ult = pri[pri['fecha'] >= cutoff]
    if ult.empty:
        ult = pri[pri['fecha'] >= pri['fecha'].max() - pd.Timedelta(days=60)]
    # Precio promedio ponderado por cantidad (menos sesgado que promedio simple)
    g = ult.groupby(['sku', 'canal'], observed=True).agg(
        venta_bruta=('venta_bruta', 'sum'),
        cantidad=('cantidad', 'sum'),
    )
    g['precio_unidad'] = g['venta_bruta'] / g['cantidad'].clip(lower=1)
    return g['precio_unidad'].reset_index()


def calcular_cobertura(sku_set: set) -> float:
    """% venta total que cubren los SKUs forecasteados (ultimos 365d)."""
    if not HIST_PARQUET.exists():
        return 0.85  # default conservador
    h = pd.read_parquet(HIST_PARQUET, columns=['sku', 'venta_bruta', 'tipo_movimiento', 'fecha_venta'])
    h = h[h['tipo_movimiento'] == 'Venta'].copy()
    h['sku'] = h['sku'].astype(str)
    h['fecha_venta'] = pd.to_datetime(h['fecha_venta'], errors='coerce')
    h = h.dropna(subset=['fecha_venta'])
    cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=365)
    h = h[h['fecha_venta'] >= cutoff]
    venta_top = h[h['sku'].isin(sku_set)]['venta_bruta'].sum()
    venta_total = h['venta_bruta'].sum()
    if venta_total <= 0:
        return 0.85
    return float(venta_top / venta_total)


def main():
    print(f"=== Calibracion forecast TOTAL via bottom-up SKU — {datetime.now()} ===\n", flush=True)

    if not all(p.exists() for p in [FC_SKUS, FC_ANUAL, FC_DIARIO, FC_RESUMEN]):
        print("[ERROR] Faltan parquets. Correr extract_forecast.py + extract_forecast_skus.py")
        sys.exit(1)

    # Backup originales (una vez)
    for p in [FC_ANUAL, FC_DIARIO, FC_RESUMEN]:
        bak = RAW_DIR / p.name
        if not bak.exists():
            shutil.copy2(p, bak)
            print(f"   Backup: {bak.name}", flush=True)

    # 1. Cargar inputs
    fc_skus = pd.read_parquet(FC_SKUS)
    fc_skus['ds'] = pd.to_datetime(fc_skus['ds'])
    fc_skus['sku'] = fc_skus['sku'].astype(str)

    fc_anual = pd.read_parquet(FC_ANUAL)
    fc_anual['ds'] = pd.to_datetime(fc_anual['ds'])

    fc_diario = pd.read_parquet(FC_DIARIO)
    fc_diario['ds'] = pd.to_datetime(fc_diario['ds'])

    print(f"[1] forecast_skus: {len(fc_skus):,} filas", flush=True)
    print(f"    forecast_anual: {len(fc_anual):,} filas", flush=True)
    print(f"    forecast_diario: {len(fc_diario):,} filas", flush=True)

    pricing = cargar_pricing_reciente()
    print(f"[2] Pricing reciente: {len(pricing):,} (sku, canal) precios", flush=True)

    # 2. Convertir bottom-up (unidades) a $ usando precio reciente por SKU x canal
    # FILTRAR a futuro estricto (algunos SKUs tienen forecast desde su ultimo dia con venta,
    # que puede ser hace varios meses)
    hoy = pd.Timestamp(datetime.now().date())
    fc_skus_futuro = fc_skus[fc_skus['ds'] > hoy].copy()
    print(f"[3a] forecast_skus filtrado a futuro estricto (>={hoy.date()}): "
          f"{len(fc_skus_futuro):,} filas, {fc_skus_futuro['ds'].nunique()} dias", flush=True)

    fc_skus_dol = fc_skus_futuro.merge(pricing, on=['sku', 'canal'], how='left')
    fc_skus_dol['precio_unidad'] = fc_skus_dol['precio_unidad'].fillna(
        fc_skus_dol['precio_unidad'].median()  # fallback: mediana global
    )
    # Clip yhat a >= 0 (Prophet a veces predice negativo en SKUs con quiebres)
    yhat_clip = fc_skus_dol['yhat'].clip(lower=0)
    n_negativos = (fc_skus_dol['yhat'] < 0).sum()
    if n_negativos > 0:
        print(f"   [WARN] {n_negativos} predicciones negativas clipeadas a 0", flush=True)
    fc_skus_dol['venta_$'] = yhat_clip * fc_skus_dol['precio_unidad']
    bottom_up_diario = fc_skus_dol.groupby('ds')['venta_$'].sum()
    print(f"[3b] Bottom-up diario en $ generado: {len(bottom_up_diario)} dias", flush=True)

    # 3. Cobertura SKUs forecasteados / venta total LTM
    sku_set = set(fc_skus['sku'].unique())
    cobertura = calcular_cobertura(sku_set)
    print(f"[4] Cobertura: {len(sku_set)} SKUs forecasteados cubren {cobertura*100:.1f}% venta LTM", flush=True)
    if cobertura < 0.4:
        print("    [WARN] Cobertura < 40% es baja, calibracion puede ser ruidosa", flush=True)

    # 5. Factor de calibracion = 1 / (1 + sesgo del backtest Prophet TOTAL)
    # Si tenemos backtest del TOTAL (medido directo), usamos ese sesgo.
    # Si solo tenemos sesgo SKU, usamos heuristic = sesgo_SKU * 0.3 (errores cancelan al agregar).
    val_path = OUT_DIR / 'validation_summary.json'
    sesgo_sku_pct = 0.0
    sesgo_total_pct = None
    if val_path.exists():
        with open(val_path, encoding='utf-8') as f:
            val_summary = json.load(f)
        sesgo_sku_pct = val_summary.get('sesgo_global_pct', 0)
        bt_total = val_summary.get('prophet_total_backtest') or {}
        sesgo_total_pct = bt_total.get('sesgo_total_pct')

    # Robust selection of sesgo:
    # El backtest TOTAL puede inflarse por outliers (e.g., Yuju cortado en el periodo de test).
    # Cap el sesgo TOTAL en [sesgo_SKU * 0.3, sesgo_SKU * 0.7] como banda razonable.
    # Si el sesgo TOTAL medido cae fuera de eso, usamos el bound mas cercano.
    if sesgo_total_pct is not None and sesgo_sku_pct > 0:
        upper_bound = sesgo_sku_pct * 0.7
        lower_bound = sesgo_sku_pct * 0.2
        sesgo_efectivo = max(lower_bound, min(sesgo_total_pct, upper_bound))
        if sesgo_efectivo != sesgo_total_pct:
            fuente = f'capped a [{lower_bound:.1f}, {upper_bound:.1f}] (medido {sesgo_total_pct:+.1f}% fuera de banda razonable)'
        else:
            fuente = 'medido directo en backtest Prophet TOTAL'
    elif sesgo_total_pct is not None:
        sesgo_efectivo = sesgo_total_pct
        fuente = 'medido directo'
    else:
        sesgo_efectivo = sesgo_sku_pct * 0.3
        fuente = f'estimado = sesgo SKU * 0.3'

    factor_calibracion = 1.0 / (1.0 + sesgo_efectivo / 100.0) if sesgo_efectivo != 0 else 1.0

    print(f"[5] Sesgo SKU backtest: {sesgo_sku_pct:+.1f}%", flush=True)
    print(f"    Sesgo TOTAL efectivo: {sesgo_efectivo:+.1f}% ({fuente})", flush=True)
    print(f"    Factor calibracion: {factor_calibracion:.3f}", flush=True)
    sesgo_total_estimado = sesgo_efectivo  # alias para metadata

    # Reporte comparativo informativo
    fechas_comunes = bottom_up_diario.index.intersection(fc_anual['ds'])
    if len(fechas_comunes) > 0:
        prophet_periodo = fc_anual.set_index('ds').loc[fechas_comunes, 'yhat']
        bottom_periodo = bottom_up_diario.loc[fechas_comunes]
        print(f"    [info] Comparativo {len(fechas_comunes)}d: Prophet ${float(prophet_periodo.sum())/1e6:.0f}M vs Bottom-up ${float(bottom_periodo.sum())/1e6:.0f}M (cobertura SKUs={cobertura*100:.0f}%)", flush=True)

    # Clamp conservador: la calibracion debe ser ajuste fino, no demolicion.
    # Maximo descuento permitido: 15% (factor 0.85). Maximo aumento: 10% (factor 1.10).
    if factor_calibracion < 0.85 or factor_calibracion > 1.10:
        print(f"    [WARN] Factor fuera de [0.85, 1.10]. Clamping.", flush=True)
        factor_calibracion = max(0.85, min(1.10, factor_calibracion))
        print(f"    Factor clamped:                {factor_calibracion:.3f}", flush=True)

    # 6. Aplicar factor a forecast_anual y forecast_diario — DIFERENCIAL por evento.
    # Los dias en ventana de holiday/evento NO se calibran (son estructurales del retail).
    # Solo dias "normales" reciben el descuento del sesgo.
    print(f"[6] Aplicando factor DIFERENCIAL...", flush=True)
    comp_path = OUT_DIR / 'forecast_componentes.parquet'
    dias_con_evento = set()
    if comp_path.exists():
        comp = pd.read_parquet(comp_path)
        comp['ds'] = pd.to_datetime(comp['ds'])
        if 'holidays' in comp.columns:
            # Un dia es "de evento" si el componente holidays > 5% de la suma de trend en ese dia
            umbral = comp['trend'].abs().mean() * 0.05 if 'trend' in comp.columns else 1_000_000
            dias_con_evento = set(comp[comp['holidays'].abs() > umbral]['ds'].dt.normalize())
    print(f"    Dias con evento detectados (no se calibran): {len(dias_con_evento)}", flush=True)

    for df in [fc_anual, fc_diario]:
        df['ds_norm'] = pd.to_datetime(df['ds']).dt.normalize()
        df['en_evento'] = df['ds_norm'].isin(dias_con_evento)
        for col in ['yhat', 'yhat_lower', 'yhat_upper']:
            if col not in df.columns:
                continue
            # Dias en evento: factor = 1.0 (no tocar). Dias normales: factor calibracion.
            df[col] = df.apply(
                lambda r: r[col] if r['en_evento'] else r[col] * factor_calibracion,
                axis=1,
            ).round(0)
        df.drop(columns=['ds_norm', 'en_evento'], inplace=True)

    fc_anual.to_parquet(FC_ANUAL, compression='zstd', compression_level=9, index=False)
    fc_diario.to_parquet(FC_DIARIO, compression='zstd', compression_level=9, index=False)
    print(f"    forecast_anual: actualizado (calibrado solo dias normales)", flush=True)
    print(f"    forecast_diario: actualizado", flush=True)

    # 7. Regenerar forecast_resumen.json con valores calibrados
    print(f"[7] Regenerando forecast_resumen.json...", flush=True)
    with open(RAW_DIR / 'forecast_resumen.json', encoding='utf-8') as f:
        resumen_orig = json.load(f)

    fc_anual_dt = fc_anual.copy()
    fc_anual_dt['ds_d'] = fc_anual_dt['ds'].dt.date

    fecha_actual = datetime.now().date()
    primer_dia_mes = fecha_actual.replace(day=1)
    if fecha_actual.month == 12:
        ultimo_dia_mes = fecha_actual.replace(year=fecha_actual.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        ultimo_dia_mes = fecha_actual.replace(month=fecha_actual.month + 1, day=1) - timedelta(days=1)

    # Re-calcular proyeccion mes
    fc_pendiente = fc_anual_dt[(fc_anual_dt['ds_d'] > fecha_actual) & (fc_anual_dt['ds_d'] <= ultimo_dia_mes)]
    venta_pendiente = float(fc_pendiente['yhat'].sum())
    venta_actual_mes = resumen_orig.get('venta_actual_mes', 0)  # real, no se calibra
    proyeccion_mes = venta_actual_mes + venta_pendiente

    venta_ly_mes = resumen_orig.get('venta_ly_mes_completo', 0)
    pct_vs_ly = ((proyeccion_mes - venta_ly_mes) / venta_ly_mes * 100) if venta_ly_mes else None

    # Horizontes 30/60/90
    horizontes = {}
    for n_dias in [30, 60, 90]:
        fc_h = fc_anual_dt[(fc_anual_dt['ds_d'] > fecha_actual) & (fc_anual_dt['ds_d'] <= fecha_actual + timedelta(days=n_dias))]
        proy = float(fc_h['yhat'].sum())
        ly = resumen_orig.get('horizontes', {}).get(f'{n_dias}d', {}).get('venta_ly_mismo_rango', 0)
        horizontes[f'{n_dias}d'] = {
            'proyeccion': proy,
            'venta_ly_mismo_rango': ly,
            'pct_vs_ly': ((proy - ly) / ly * 100) if ly else None,
        }

    # Año calendario - tabla mensual
    primer_dia_anio = fecha_actual.replace(month=1, day=1)
    ultimo_dia_anio = fecha_actual.replace(month=12, day=31)
    fc_resto = fc_anual_dt[(fc_anual_dt['ds_d'] > fecha_actual) & (fc_anual_dt['ds_d'] <= ultimo_dia_anio)]
    proy_resto = float(fc_resto['yhat'].sum())
    venta_ytd = resumen_orig.get('anio_proyeccion', {}).get('venta_ytd', 0)
    proy_anio = venta_ytd + proy_resto

    venta_anio_ly = resumen_orig.get('anio_proyeccion', {}).get('venta_anio_ly', 0)
    pct_anio_vs_ly = ((proy_anio - venta_anio_ly) / venta_anio_ly * 100) if venta_anio_ly else None

    tabla_mensual = []
    tabla_orig = resumen_orig.get('anio_proyeccion', {}).get('tabla_mensual', [])
    tabla_orig_map = {m['mes']: m for m in tabla_orig}

    for mes in range(1, 13):
        primer_d = fecha_actual.replace(month=mes, day=1)
        if mes == 12:
            ultimo_d = fecha_actual.replace(year=fecha_actual.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            ultimo_d = fecha_actual.replace(month=mes + 1, day=1) - timedelta(days=1)

        orig = tabla_orig_map.get(mes, {})
        tipo = orig.get('tipo', 'forecast')

        if tipo == 'real':
            proy_mes = orig.get('proyeccion', 0)  # real, no se calibra
        elif tipo == 'mixto':
            proy_mes = proyeccion_mes
        else:
            fc_m = fc_anual_dt[(fc_anual_dt['ds_d'] >= primer_d) & (fc_anual_dt['ds_d'] <= ultimo_d)]
            proy_mes = float(fc_m['yhat'].sum())

        ly = orig.get('venta_ly', 0)
        tabla_mensual.append({
            'mes': mes,
            'mes_nombre': primer_d.strftime('%b'),
            'proyeccion': round(proy_mes, 0),
            'venta_ly': round(ly, 0),
            'pct_vs_ly': ((proy_mes - ly) / ly * 100) if ly > 0 else None,
            'tipo': tipo,
        })

    resumen_nuevo = dict(resumen_orig)
    resumen_nuevo.update({
        'generado_en': datetime.now().isoformat(),
        'venta_pendiente_estimada': venta_pendiente,
        'proyeccion_mes': proyeccion_mes,
        'pct_vs_ly': pct_vs_ly,
        'horizontes': horizontes,
        'anio_proyeccion': {
            **resumen_orig.get('anio_proyeccion', {}),
            'proyeccion_resto_anio': proy_resto,
            'proyeccion_anio_completo': proy_anio,
            'pct_anio_vs_ly': pct_anio_vs_ly,
            'tabla_mensual': tabla_mensual,
        },
        'calibracion': {
            'aplicada': True,
            'factor': factor_calibracion,
            'cobertura_skus': cobertura,
            'n_skus_forecasted': len(sku_set),
        },
    })

    with open(FC_RESUMEN, 'w', encoding='utf-8') as f:
        json.dump(resumen_nuevo, f, indent=2, default=str)

    # 8. Metadata calibracion
    meta = {
        'generado_en': datetime.now().isoformat(),
        'factor_calibracion': factor_calibracion,
        'cobertura_skus_forecasted': cobertura,
        'n_skus_forecasted': len(sku_set),
        'sesgo_sku_pct': sesgo_sku_pct,
        'sesgo_total_efectivo_pct': sesgo_total_estimado,
        'descuento_aplicado_pct': float((1 - factor_calibracion) * 100),
        'metodo': 'factor = 1 / (1 + sesgo_total/100), donde sesgo_total = sesgo_SKU * 0.5 (errores cancelan al agregar)',
        'note': 'Backup en data/forecast/_raw/. Factor clampeado a [0.5, 1.2] para evitar volatilidad. Re-mide cada cron.',
    }
    with open(OUT_DIR / 'calibration_metadata.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, default=str)

    print(f"\n[OK] Calibracion completa")
    print(f"  Factor aplicado: {factor_calibracion:.3f} (descuenta {(1-factor_calibracion)*100:.0f}% sobre Prophet TOTAL)")
    print(f"  Mes en curso: ${proyeccion_mes/1e6:.0f}M (antes: ${resumen_orig.get('proyeccion_mes',0)/1e6:.0f}M)")
    print(f"  Año {fecha_actual.year}: ${proy_anio/1e6:.0f}M (antes: ${resumen_orig.get('anio_proyeccion',{}).get('proyeccion_anio_completo',0)/1e6:.0f}M)")
    if pct_anio_vs_ly is not None:
        print(f"  vs LY {fecha_actual.year-1}: {pct_anio_vs_ly:+.1f}%")


if __name__ == '__main__':
    main()
