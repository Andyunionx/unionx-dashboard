#!/usr/bin/env python3
"""
Calibracion del forecast TOTAL usando ANCLAS DE NEGOCIO por evento.

El usuario (Andres) dio multiplicadores empiricos para eventos clave:
- Cyber (CyberDay / CyberMonday)  = 1x mes normal de venta marketplaces+web
- Black Friday                     = 0.5x mes normal
- Navidad (periodo dic 5-25)       = 2x mes normal

Baseline: 1 mes normal marketplaces+web ~= $313M (promedio meses no-evento 2025).
Share online sobre venta total = 61% promedio.

Aplica ANCLAS exactas a cada evento:
- En la ventana del evento, ajusta yhat a la ancla esperada (escalando)
- Fuera de evento, aplica calibracion por sesgo (factor 0.85)

Genera:
- forecast_anual + diario + resumen (sobrescribe con valores anclados)
- anchored_metadata.json (lista de anclas aplicadas y delta vs Prophet raw)

Mantiene backup en data/forecast/_raw/.
"""
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / 'data' / 'forecast'
RAW_DIR = OUT_DIR / '_raw'
RAW_DIR.mkdir(parents=True, exist_ok=True)

FC_ANUAL = OUT_DIR / 'forecast_anual.parquet'
FC_DIARIO = OUT_DIR / 'forecast_diario.parquet'
FC_RESUMEN = OUT_DIR / 'forecast_resumen.json'

# === ANCLAS DE NEGOCIO (input del usuario) ===
# Andres: las tasas son contra meses normales DE 2026, no LY.
# Baseline: 1 mes de venta marketplaces+web normal 2026 = $312M
# (promedio ene+feb 2026, los meses cerrados mas limpios sin growth atipico ni eventos).
# Share online sobre total = 61% promedio.
#
# Solo 4 eventos con ancla EXPLICITA. Los demas (Dia Madre/Padre/FFPP/Niño/etc.)
# quedan indexados a la curva de crecimiento LY via holidays de Prophet.
BASELINE_ONLINE_MES = 312_000_000
SHARE_ONLINE = 0.61

# Multiplicadores por evento (proporcion del BASELINE_ONLINE_MES en la VENTANA del evento)
ANCLAS_2026 = [
    # (nombre, fecha_inicio, fecha_fin, multiplicador_online_sobre_baseline)
    ('cyber_day',    '2026-06-01', '2026-06-04', 1.0),   # Cyber Day = 1 mes normal en 4 dias
    ('cyber_monday', '2026-10-06', '2026-10-09', 1.0),   # CyberMonday = 1 mes normal
    ('black_friday', '2026-11-26', '2026-11-30', 0.5),   # Black Friday = 0.5 mes normal
    ('navidad',      '2026-12-05', '2026-12-25', 2.0),   # Navidad (21d) = 2 meses normales
]


def main():
    print(f"=== Forecast con ANCLAS de negocio — {datetime.now()} ===\n", flush=True)

    if not all(p.exists() for p in [FC_ANUAL, FC_DIARIO, FC_RESUMEN]):
        print("[ERROR] Faltan parquets. Correr extract_forecast.py primero")
        sys.exit(1)

    # Backup
    for p in [FC_ANUAL, FC_DIARIO, FC_RESUMEN]:
        bak = RAW_DIR / p.name
        if not bak.exists():
            shutil.copy2(p, bak)
            print(f"   Backup: {bak.name}", flush=True)

    fc_anual = pd.read_parquet(FC_ANUAL)
    fc_anual['ds'] = pd.to_datetime(fc_anual['ds'])
    fc_diario = pd.read_parquet(FC_DIARIO)
    fc_diario['ds'] = pd.to_datetime(fc_diario['ds'])

    print(f"[1] Loaded forecast_anual: {len(fc_anual):,} dias", flush=True)
    print(f"    Baseline online/mes: ${BASELINE_ONLINE_MES/1e6:.0f}M, share online: {SHARE_ONLINE*100:.0f}%", flush=True)

    fechas_evento_total = set()
    aplicaciones = []

    for nombre, fi, ff, mult in ANCLAS_2026:
        fi_ts = pd.Timestamp(fi)
        ff_ts = pd.Timestamp(ff)
        mask = (fc_anual['ds'] >= fi_ts) & (fc_anual['ds'] <= ff_ts)
        if not mask.any():
            print(f"   [skip] {nombre}: sin fechas en forecast", flush=True)
            continue

        # Ancla en venta TOTAL = (online_mes * mult) / share_online
        ancla_total = (BASELINE_ONLINE_MES * mult) / SHARE_ONLINE
        ancla_diaria = ancla_total / mask.sum()  # dias en la ventana

        # Lo que Prophet predice en la ventana
        prophet_ventana = fc_anual.loc[mask, 'yhat'].sum()
        factor = ancla_total / prophet_ventana if prophet_ventana > 0 else 1.0

        # Aplicar factor preservando la forma diaria de Prophet
        for col in ['yhat', 'yhat_lower', 'yhat_upper']:
            if col in fc_anual.columns:
                fc_anual.loc[mask, col] = (fc_anual.loc[mask, col] * factor).round(0)

        # Aplicar tambien a forecast_diario
        mask_d = (fc_diario['ds'] >= fi_ts) & (fc_diario['ds'] <= ff_ts)
        if mask_d.any():
            for col in ['yhat', 'yhat_lower', 'yhat_upper']:
                if col in fc_diario.columns:
                    fc_diario.loc[mask_d, col] = (fc_diario.loc[mask_d, col] * factor).round(0)

        # Marcar fechas para excluir de calibracion no-evento
        fechas_evento_total.update(fc_anual.loc[mask, 'ds'].dt.normalize().tolist())

        aplicaciones.append({
            'evento': nombre,
            'fecha_inicio': fi, 'fecha_fin': ff,
            'multiplicador': mult,
            'ancla_total_M': ancla_total / 1e6,
            'prophet_ventana_M': prophet_ventana / 1e6,
            'factor_aplicado': float(factor),
            'dias': int(mask.sum()),
        })
        print(f"   {nombre:>13} | {fi} -> {ff} | mult={mult:>3.1f} | "
              f"Prophet ${prophet_ventana/1e6:>5.0f}M -> Ancla ${ancla_total/1e6:>5.0f}M | factor={factor:.2f}", flush=True)

    # Tambien excluir de la calibracion los dias con holiday detectado por Prophet
    # (Dia Madre/Padre/FFPP/Niño/feriados Chile) — Andres: indexados a curva growth LY natural
    comp_path = OUT_DIR / 'forecast_componentes.parquet'
    if comp_path.exists():
        comp = pd.read_parquet(comp_path)
        comp['ds'] = pd.to_datetime(comp['ds'])
        if 'holidays' in comp.columns:
            umbral = comp['trend'].abs().mean() * 0.05 if 'trend' in comp.columns else 1_000_000
            dias_holiday = set(comp[comp['holidays'].abs() > umbral]['ds'].dt.normalize())
            fechas_evento_total.update(dias_holiday)
            print(f"\n[2a] {len(dias_holiday)} dias adicionales con holiday Prophet (no se calibran)", flush=True)

    print(f"\n[2b] Aplicando calibracion 0.85 a dias FUERA de eventos+holidays...", flush=True)
    mask_no_evento = ~fc_anual['ds'].dt.normalize().isin(fechas_evento_total)
    n_no_evento = mask_no_evento.sum()
    for col in ['yhat', 'yhat_lower', 'yhat_upper']:
        if col in fc_anual.columns:
            fc_anual.loc[mask_no_evento, col] = (fc_anual.loc[mask_no_evento, col] * 0.85).round(0)
    print(f"   {n_no_evento} dias normales calibrados x 0.85", flush=True)

    mask_no_evento_d = ~fc_diario['ds'].dt.normalize().isin(fechas_evento_total)
    for col in ['yhat', 'yhat_lower', 'yhat_upper']:
        if col in fc_diario.columns:
            fc_diario.loc[mask_no_evento_d, col] = (fc_diario.loc[mask_no_evento_d, col] * 0.85).round(0)

    # Guardar
    fc_anual.to_parquet(FC_ANUAL, compression='zstd', compression_level=9, index=False)
    fc_diario.to_parquet(FC_DIARIO, compression='zstd', compression_level=9, index=False)
    print(f"[3] Guardado forecast_anual + forecast_diario", flush=True)

    # Regenerar forecast_resumen.json
    print(f"[4] Regenerando forecast_resumen.json...", flush=True)
    with open(RAW_DIR / 'forecast_resumen.json', encoding='utf-8') as f:
        resumen_orig = json.load(f)

    fecha_actual = datetime.now().date()
    fc_anual['ds_d'] = fc_anual['ds'].dt.date

    primer_dia_mes = fecha_actual.replace(day=1)
    if fecha_actual.month == 12:
        ultimo_dia_mes = fecha_actual.replace(year=fecha_actual.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        ultimo_dia_mes = fecha_actual.replace(month=fecha_actual.month + 1, day=1) - timedelta(days=1)

    fc_pendiente = fc_anual[(fc_anual['ds_d'] > fecha_actual) & (fc_anual['ds_d'] <= ultimo_dia_mes)]
    venta_pendiente = float(fc_pendiente['yhat'].sum())
    venta_actual_mes = resumen_orig.get('venta_actual_mes', 0)
    proyeccion_mes = venta_actual_mes + venta_pendiente

    venta_ly_mes = resumen_orig.get('venta_ly_mes_completo', 0)
    pct_vs_ly = ((proyeccion_mes - venta_ly_mes) / venta_ly_mes * 100) if venta_ly_mes else None

    horizontes = {}
    for n_dias in [30, 60, 90]:
        fc_h = fc_anual[(fc_anual['ds_d'] > fecha_actual) & (fc_anual['ds_d'] <= fecha_actual + timedelta(days=n_dias))]
        proy = float(fc_h['yhat'].sum())
        ly = resumen_orig.get('horizontes', {}).get(f'{n_dias}d', {}).get('venta_ly_mismo_rango', 0)
        horizontes[f'{n_dias}d'] = {
            'proyeccion': proy,
            'venta_ly_mismo_rango': ly,
            'pct_vs_ly': ((proy - ly) / ly * 100) if ly else None,
        }

    # Año
    ultimo_dia_anio = fecha_actual.replace(month=12, day=31)
    fc_resto = fc_anual[(fc_anual['ds_d'] > fecha_actual) & (fc_anual['ds_d'] <= ultimo_dia_anio)]
    proy_resto = float(fc_resto['yhat'].sum())
    venta_ytd = resumen_orig.get('anio_proyeccion', {}).get('venta_ytd', 0)
    proy_anio = venta_ytd + proy_resto

    venta_anio_ly = resumen_orig.get('anio_proyeccion', {}).get('venta_anio_ly', 0)
    pct_anio_vs_ly = ((proy_anio - venta_anio_ly) / venta_anio_ly * 100) if venta_anio_ly else None

    # Tabla mensual
    tabla_orig = resumen_orig.get('anio_proyeccion', {}).get('tabla_mensual', [])
    tabla_orig_map = {m['mes']: m for m in tabla_orig}
    tabla_mensual = []
    for mes in range(1, 13):
        primer_d = fecha_actual.replace(month=mes, day=1)
        if mes == 12:
            ultimo_d = fecha_actual.replace(year=fecha_actual.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            ultimo_d = fecha_actual.replace(month=mes + 1, day=1) - timedelta(days=1)

        orig = tabla_orig_map.get(mes, {})
        tipo = orig.get('tipo', 'forecast')

        if tipo == 'real':
            proy_mes = orig.get('proyeccion', 0)
        elif tipo == 'mixto':
            proy_mes = proyeccion_mes
        else:
            fc_m = fc_anual[(fc_anual['ds_d'] >= primer_d) & (fc_anual['ds_d'] <= ultimo_d)]
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
        'anclas_aplicadas': aplicaciones,
    })

    with open(FC_RESUMEN, 'w', encoding='utf-8') as f:
        json.dump(resumen_nuevo, f, indent=2, default=str)

    meta = {
        'generado_en': datetime.now().isoformat(),
        'baseline_online_mes': BASELINE_ONLINE_MES,
        'share_online': SHARE_ONLINE,
        'anclas': aplicaciones,
        'factor_no_evento': 0.85,
        'metodo': 'Anclas de negocio definidas por gerencia: Cyber=1x mes, Black=0.5x, Navidad=2x mes (marketplaces+web)',
    }
    with open(OUT_DIR / 'anchored_metadata.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, default=str)

    print(f"\n[OK] Forecast con anclas generado")
    print(f"  Mes en curso: ${proyeccion_mes/1e6:.0f}M ({pct_vs_ly:+.1f}% vs LY)" if pct_vs_ly else f"  Mes en curso: ${proyeccion_mes/1e6:.0f}M")
    print(f"  Año 2026: ${proy_anio/1e6:.0f}M ({pct_anio_vs_ly:+.1f}% vs LY)" if pct_anio_vs_ly else f"  Año 2026: ${proy_anio/1e6:.0f}M")


if __name__ == '__main__':
    main()
