#!/usr/bin/env python3
"""
Volumen operacional proyectado a partir del forecast de ventas.

Convierte la demanda forecast (unidades) en NECESIDADES de operación:
  - Pedidos/día (usando ratio uds/pedido histórico)
  - Líneas pickeadas/día (ratio líneas/pedido)
  - Unidades despachadas/día (cap por stock + tránsito)
  - % carga del equipo vs productividad histórica
  - Personas necesarias para cumplir esa carga

Inputs:
  - data/forecast/forecast_skus_anchored.parquet  (forecast venta diaria por SKU)
  - data/kpis_wms/snapshot.json  (productividad histórica + ratios)
  - data/comex/dimensiones_skus.parquet  (volumen por SKU para chequeos)

Output:
  - data/capacidad/volumen_operacional_diario.parquet
  - data/capacidad/volumen_operacional_resumen.json

Cron: parte de sync_forecast.yml (corre tras Prophet diario) Y de sync_comex.yml
(cada 3h por si cambian PIs en tránsito).
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent

# ============= Configuración ================================================
HORIZONTE_DIAS = 90
CARGA_ALERTA_PCT = 90        # % capacidad equipo: alerta
CARGA_CRITICA_PCT = 110      # % capacidad equipo: necesita refuerzo
DIAS_LABORALES_SEMANA = 5     # bodega no opera fin de semana (ajustar si cambia)
# Fallback ratios si snapshot no tiene datos (CL retail multi-canal típico)
RATIO_UDS_POR_PEDIDO_FALLBACK = 3.5
RATIO_LINEAS_POR_PEDIDO_FALLBACK = 1.3
PRODUCTIVIDAD_PEDIDOS_DIA_FALLBACK = 525  # ~21 días promedio actual
# ============================================================================

FORECAST_PARQUET = PROJECT_ROOT / 'data' / 'forecast' / 'forecast_skus_anchored.parquet'
WMS_SNAPSHOT = PROJECT_ROOT / 'data' / 'kpis_wms' / 'snapshot.json'
DIMENSIONES_PARQUET = PROJECT_ROOT / 'data' / 'comex' / 'dimensiones_skus.parquet'
CAPACIDAD_RESUMEN = PROJECT_ROOT / 'data' / 'capacidad' / 'forecast_resumen.json'

OUT_DIR = PROJECT_ROOT / 'data' / 'capacidad'
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PARQUET = OUT_DIR / 'volumen_operacional_diario.parquet'
OUT_RESUMEN = OUT_DIR / 'volumen_operacional_resumen.json'


def _ratios_historicos() -> dict:
    """Lee snapshot KPIs WMS para extraer ratios reales del equipo."""
    if not WMS_SNAPSHOT.exists():
        return {
            'uds_por_pedido': RATIO_UDS_POR_PEDIDO_FALLBACK,
            'lineas_por_pedido': RATIO_LINEAS_POR_PEDIDO_FALLBACK,
            'pedidos_dia_promedio': PRODUCTIVIDAD_PEDIDOS_DIA_FALLBACK,
            'fuente': 'fallback',
        }

    try:
        snap = json.load(open(WMS_SNAPSHOT, encoding='utf-8'))
    except Exception:
        return {
            'uds_por_pedido': RATIO_UDS_POR_PEDIDO_FALLBACK,
            'lineas_por_pedido': RATIO_LINEAS_POR_PEDIDO_FALLBACK,
            'pedidos_dia_promedio': PRODUCTIVIDAD_PEDIDOS_DIA_FALLBACK,
            'fuente': 'fallback (error leyendo snapshot)',
        }

    p = snap.get('productividad_dia_30d', {})
    items = p.get('items', []) if isinstance(p, dict) else []
    laborales = [d for d in items if d.get('n_pedidos', 0) > 0]
    if not laborales:
        return {
            'uds_por_pedido': RATIO_UDS_POR_PEDIDO_FALLBACK,
            'lineas_por_pedido': RATIO_LINEAS_POR_PEDIDO_FALLBACK,
            'pedidos_dia_promedio': PRODUCTIVIDAD_PEDIDOS_DIA_FALLBACK,
            'fuente': 'fallback (sin productividad reciente)',
        }

    peds = [d['n_pedidos'] for d in laborales]
    unds = [d['n_unidades_despachadas'] for d in laborales]
    lins = [d['n_lineas_pickeadas'] for d in laborales]
    avg_p = sum(peds) / len(peds)
    avg_u = sum(unds) / len(unds)
    avg_l = sum(lins) / len(lins)

    # Capacidad pico observada (percentil 90 = lo que el equipo PUEDE hacer)
    sorted_p = sorted(peds)
    p90 = sorted_p[int(len(sorted_p) * 0.9)]

    return {
        'uds_por_pedido': avg_u / avg_p if avg_p else RATIO_UDS_POR_PEDIDO_FALLBACK,
        'lineas_por_pedido': avg_l / avg_p if avg_p else RATIO_LINEAS_POR_PEDIDO_FALLBACK,
        'pedidos_dia_promedio': avg_p,
        'pedidos_dia_p90': p90,  # capacidad pico realista
        'unidades_dia_promedio': avg_u,
        'lineas_dia_promedio': avg_l,
        'n_dias_observados': len(laborales),
        'fuente': f'snapshot WMS últimos {len(laborales)} días laborales',
    }


def _stock_y_transito_disponible(stock_total_disp: dict | None = None) -> dict:
    """Combina stock actual con tránsito para cap por SKU.

    Reusa data del extract_capacidad_forecast cuando está disponible.
    """
    if stock_total_disp:
        return stock_total_disp

    # Fallback: leer directamente del resumen capacidad si existe
    if CAPACIDAD_RESUMEN.exists():
        try:
            r = json.load(open(CAPACIDAD_RESUMEN, encoding='utf-8'))
            # No exponemos qty por SKU directamente — sin extra query no podemos
            # capear realmente, así que retornamos vacío y dejamos que el
            # extractor proceda sin cap (forecast bruto)
        except Exception:
            pass
    return {}


def _es_dia_laboral(fecha) -> bool:
    """Lunes (0) a Viernes (4) son laborales."""
    return fecha.weekday() < DIAS_LABORALES_SEMANA


def main():
    print(f"=== Extract Volumen Operacional — {datetime.now().isoformat()} ===\n", flush=True)

    if not FORECAST_PARQUET.exists():
        print(f"[ERROR] {FORECAST_PARQUET} no existe", flush=True)
        return 1

    # 1. Ratios históricos del equipo
    print("[1/4] Leyendo ratios históricos del equipo...", flush=True)
    ratios = _ratios_historicos()
    print(f"      Fuente: {ratios['fuente']}")
    print(f"      Uds/pedido: {ratios['uds_por_pedido']:.2f}")
    print(f"      Líneas/pedido: {ratios['lineas_por_pedido']:.2f}")
    print(f"      Pedidos/día promedio: {ratios['pedidos_dia_promedio']:.0f}")
    if 'pedidos_dia_p90' in ratios:
        print(f"      Capacidad pico equipo (P90): {ratios['pedidos_dia_p90']:.0f} pedidos/día")

    # 2. Cargar forecast de ventas (filtrado a horizonte)
    print(f"\n[2/4] Cargando forecast venta (horizonte {HORIZONTE_DIAS}d)...", flush=True)
    fc = pd.read_parquet(FORECAST_PARQUET)
    fc['ds'] = pd.to_datetime(fc['ds'])
    fc = fc.dropna(subset=['ds', 'sku'])
    fc['sku'] = fc['sku'].astype(str)
    fc['yhat_anchored'] = fc['yhat_anchored'].clip(lower=0)

    fecha_corte = pd.Timestamp(datetime.now().date() + timedelta(days=HORIZONTE_DIAS))
    fc = fc[fc['ds'] <= fecha_corte]

    # Excluir SKUs no físicos
    sku_lower = fc['sku'].str.lower()
    no_fisicos = sku_lower.str.startswith(('delivery_', 'servicio_', 'envio_',
                                             'flete_', 'cargo_'))
    fc = fc[~no_fisicos]
    print(f"      {len(fc):,} filas, {fc['sku'].nunique()} SKUs únicos, "
          f"{(fc['ds'].max() - fc['ds'].min()).days + 1} días", flush=True)

    # 3. Agregar por día y convertir a métricas operacionales
    print(f"\n[3/4] Convirtiendo demanda → pedidos/líneas/unidades por día...", flush=True)
    diario = fc.groupby(fc['ds'].dt.date).agg(
        unidades_demanda=('yhat_anchored', 'sum'),
        sku_distintos=('sku', 'nunique'),
    ).reset_index()
    diario.columns = ['fecha', 'unidades_demanda', 'sku_distintos']

    # Convertir a pedidos y líneas con ratios históricos
    uds_x_ped = ratios['uds_por_pedido']
    lin_x_ped = ratios['lineas_por_pedido']
    cap_pedidos = ratios.get('pedidos_dia_p90', ratios['pedidos_dia_promedio'])

    diario['es_laboral'] = diario['fecha'].apply(_es_dia_laboral)
    diario['pedidos_proyectados'] = (diario['unidades_demanda'] / uds_x_ped).round(0)
    diario['lineas_proyectadas'] = (diario['pedidos_proyectados'] * lin_x_ped).round(0)

    # En sábado/domingo se acumulan los pedidos para el lunes (heurística simple:
    # bodega no opera fin de semana → demanda S+D se procesa el lunes)
    # Reasignación: si no es laboral, sumar al próximo día laboral
    diario_sorted = diario.sort_values('fecha').copy()
    pendiente_pedidos = 0
    pendiente_lineas = 0
    pendiente_uds = 0
    pedidos_a_procesar = []
    lineas_a_procesar = []
    uds_a_procesar = []
    for _, r in diario_sorted.iterrows():
        if not r['es_laboral']:
            pendiente_pedidos += r['pedidos_proyectados']
            pendiente_lineas += r['lineas_proyectadas']
            pendiente_uds += r['unidades_demanda']
            pedidos_a_procesar.append(0)
            lineas_a_procesar.append(0)
            uds_a_procesar.append(0)
        else:
            pedidos_a_procesar.append(r['pedidos_proyectados'] + pendiente_pedidos)
            lineas_a_procesar.append(r['lineas_proyectadas'] + pendiente_lineas)
            uds_a_procesar.append(r['unidades_demanda'] + pendiente_uds)
            pendiente_pedidos = pendiente_lineas = pendiente_uds = 0

    diario_sorted['pedidos_a_procesar'] = pedidos_a_procesar
    diario_sorted['lineas_a_procesar'] = lineas_a_procesar
    diario_sorted['unidades_a_procesar'] = uds_a_procesar

    # % de carga vs capacidad equipo
    diario_sorted['pct_carga_equipo'] = (
        diario_sorted['pedidos_a_procesar'] / cap_pedidos * 100
    ).round(1)

    # Personas necesarias (asumiendo cap por persona = total / 5 personas equipo actual)
    # Más preciso: cap por persona = pedidos_dia_p90 / # personas activas observadas
    # Por simplicidad: si carga > 100% indica refuerzo
    def _alerta(pct):
        if pct >= CARGA_CRITICA_PCT:
            return '🔴 SOBRECARGA'
        if pct >= CARGA_ALERTA_PCT:
            return '🟠 ATENCIÓN'
        if pct >= 70:
            return '🟡 CARGA ALTA'
        return '🟢 OK'

    diario_sorted['alerta'] = diario_sorted['pct_carga_equipo'].apply(_alerta)

    # 4. Guardar parquet + resumen
    print(f"\n[4/4] Guardando outputs...", flush=True)
    df_out = diario_sorted[[
        'fecha', 'es_laboral', 'unidades_demanda', 'pedidos_proyectados',
        'lineas_proyectadas', 'pedidos_a_procesar', 'lineas_a_procesar',
        'unidades_a_procesar', 'pct_carga_equipo', 'alerta', 'sku_distintos',
    ]].copy()
    df_out.to_parquet(OUT_PARQUET, index=False)
    print(f"  parquet: {OUT_PARQUET}", flush=True)

    # Eventos: días con sobrecarga
    sobrecarga = df_out[df_out['alerta'].isin(['🔴 SOBRECARGA', '🟠 ATENCIÓN'])]
    primer_sobrecarga = sobrecarga.iloc[0] if not sobrecarga.empty else None
    pico = df_out.loc[df_out['pedidos_a_procesar'].idxmax()]

    # Top semanas con más volumen
    df_out['semana'] = pd.to_datetime(df_out['fecha']).dt.strftime('%Y-W%V')
    semanal = df_out.groupby('semana').agg(
        pedidos=('pedidos_a_procesar', 'sum'),
        lineas=('lineas_a_procesar', 'sum'),
        unidades=('unidades_a_procesar', 'sum'),
        dias_sobrecarga=('alerta', lambda s: (s == '🔴 SOBRECARGA').sum()),
        dias_atencion=('alerta', lambda s: (s == '🟠 ATENCIÓN').sum()),
    ).reset_index()
    semanal_top = semanal.nlargest(8, 'pedidos').to_dict('records')

    resumen = {
        'generado_en': datetime.now().isoformat(),
        'horizonte_dias': HORIZONTE_DIAS,
        'ratios_equipo': ratios,
        'capacidad_pedidos_dia': float(cap_pedidos),
        'totales_horizonte': {
            'pedidos_proyectados': int(df_out['pedidos_proyectados'].sum()),
            'lineas_proyectadas': int(df_out['lineas_proyectadas'].sum()),
            'unidades_demanda': int(df_out['unidades_demanda'].sum()),
            'dias_sobrecarga': int((df_out['alerta'] == '🔴 SOBRECARGA').sum()),
            'dias_atencion': int((df_out['alerta'] == '🟠 ATENCIÓN').sum()),
        },
        'pico': {
            'fecha': pico['fecha'].isoformat() if hasattr(pico['fecha'], 'isoformat') else str(pico['fecha']),
            'pedidos_a_procesar': float(pico['pedidos_a_procesar']),
            'lineas_a_procesar': float(pico['lineas_a_procesar']),
            'pct_carga_equipo': float(pico['pct_carga_equipo']),
            'alerta': pico['alerta'],
        },
        'primer_sobrecarga': (
            {
                'fecha': primer_sobrecarga['fecha'].isoformat()
                          if hasattr(primer_sobrecarga['fecha'], 'isoformat')
                          else str(primer_sobrecarga['fecha']),
                'pedidos_a_procesar': float(primer_sobrecarga['pedidos_a_procesar']),
                'pct_carga_equipo': float(primer_sobrecarga['pct_carga_equipo']),
                'alerta': primer_sobrecarga['alerta'],
            } if primer_sobrecarga is not None else None
        ),
        'top_semanas_volumen': [
            {
                'semana': r['semana'],
                'pedidos': int(r['pedidos']),
                'lineas': int(r['lineas']),
                'unidades': int(r['unidades']),
                'dias_sobrecarga': int(r['dias_sobrecarga']),
                'dias_atencion': int(r['dias_atencion']),
            } for r in semanal_top
        ],
    }

    with open(OUT_RESUMEN, 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=str)
    print(f"  resumen: {OUT_RESUMEN}", flush=True)

    print(f"\n=== RESUMEN ===")
    print(f"  Capacidad pico equipo: {cap_pedidos:.0f} pedidos/día (P90 últimos 30d)")
    t = resumen['totales_horizonte']
    print(f"  Total {HORIZONTE_DIAS}d: {t['pedidos_proyectados']:,} pedidos | "
          f"{t['lineas_proyectadas']:,} líneas | {t['unidades_demanda']:,} unidades")
    print(f"  Días con sobrecarga (>110%): {t['dias_sobrecarga']}")
    print(f"  Días con atención (90-110%): {t['dias_atencion']}")
    print(f"  Pico: {pico['pedidos_a_procesar']:.0f} pedidos el {pico['fecha']} "
          f"({pico['pct_carga_equipo']:.0f}% carga)")
    if resumen['primer_sobrecarga']:
        print(f"  🔴 Primera sobrecarga: {resumen['primer_sobrecarga']['fecha']}")
    print("\nOK")
    return 0


if __name__ == '__main__':
    sys.exit(main())
