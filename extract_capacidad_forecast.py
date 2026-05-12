#!/usr/bin/env python3
"""
Forecast de capacidad de bodega — m³ y pallets disponibles próximos 90 días.

Combina 3 fuentes:
  1. STOCK ACTUAL m³  → Odoo stock.quant × product.template.volume
  2. TRÁNSITO m³ por ETA → data/comex/dimensiones_skus.parquet (PI x ETA)
  3. SALIDAS m³ por día → data/forecast/forecast_skus_anchored.parquet × volumen unit

Asunciones (editables al inicio):
  - Posición pallet ≈ 1.0 × 1.2 × 1.5 m = 1.8 m³ útil
  - Pallet apilable ≈ 1.2 m³ (mismo umbral que extract_comex_dimensiones)
  - Capacidad bodega: si Andrés configuró m³ totales en data/ops_manuales/datos.json
    se usa ese; si no, asume # posiciones (de Odoo) × 1.8 m³.
  - Volumen unitario anómalo (>1 m³/unid): se EXCLUYE para no inflar el cálculo
    (ya documentado en extract_comex_dimensiones).

Output:
  - data/capacidad/forecast_diario.parquet
      (fecha, m3_ocupado, m3_disponible, m3_entrante_dia, m3_saliente_dia,
       pallets_ocupados, pallets_disp, pct_ocupacion, alerta)
  - data/capacidad/forecast_resumen.json (KPIs + eventos clave)

Cron: parte de sync_comex.yml (corre cada 3h tras tránsito + dimensiones).
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

from app.core.odoo_client import OdooClient  # noqa: E402

# ============= Configuración (editable) ====================================
HORIZONTE_DIAS = 90
M3_POR_POSICION = 1.0 * 1.2 * 1.5   # 1.8 m³ útil por posición pallet
M3_POR_PALLET = 1.2                  # pallet apilable
VOL_UNIT_ANOMALO_M3 = 1.0            # > este = mal cargado en Odoo, excluir
PCT_ALERTA = 90                      # % ocupación para alerta
PCT_CRITICO = 100                    # % ocupación para alerta crítica
# ============================================================================

OUT_DIR = PROJECT_ROOT / 'data' / 'capacidad'
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PARQUET = OUT_DIR / 'forecast_diario.parquet'
OUT_RESUMEN = OUT_DIR / 'forecast_resumen.json'

DIMENSIONES_PARQUET = PROJECT_ROOT / 'data' / 'comex' / 'dimensiones_skus.parquet'
FORECAST_PARQUET = PROJECT_ROOT / 'data' / 'forecast' / 'forecast_skus_anchored.parquet'
OPS_MANUALES = PROJECT_ROOT / 'data' / 'ops_manuales' / 'datos.json'

ODOO_URL = os.environ.get('ODOO_URL', 'https://unionxb2b.odoo.com')
ODOO_DB = os.environ.get('ODOO_DB', 'bmya-innovatek-sh-prd-6981800')
ODOO_USER = (os.environ.get('OPS_ODOO_USER', '').strip()
             or os.environ.get('ANDRES_ODOO_USER', '').strip()
             or 'andres@grupoeter.cl')
ODOO_PWD = (os.environ.get('OPS_ODOO_PASSWORD', '').strip()
            or os.environ.get('ANDRES_ODOO_PASSWORD', '').strip())


def _capacidad_bodega_m3() -> tuple[float, str]:
    """Devuelve (capacidad_m3, fuente). Prioriza override manual sobre asunción."""
    if OPS_MANUALES.exists():
        try:
            data = json.load(open(OPS_MANUALES, encoding='utf-8'))
            cap = data.get('capacidad_bodega', {})
            m3 = cap.get('m3_totales')
            if m3 and m3 > 0:
                return float(m3), 'manual (datos.json)'
        except Exception:
            pass
    return 0.0, 'auto'


def _posiciones_bodega(odoo: OdooClient) -> dict:
    """Réplica de uso_posiciones() del helper Stock LIVE: cuenta posiciones leaf
    de CA1/Stock y separa entre vacías vs con stock. Es la métrica REAL que ve
    Andrés en Stock LIVE > Uso de posiciones, no una asunción global.

    Returns: {total_posiciones, vacias, ocupadas, leaf_loc_names}
    """
    locs = odoo.search_read(
        'stock.location',
        [('usage', '=', 'internal'), ('complete_name', 'ilike', 'CA1/Stock/')],
        ['id', 'complete_name', 'child_ids', 'quant_ids'],
        limit=10000,
    )
    leaf = [l for l in locs if not l.get('child_ids')]
    if not leaf:
        return {'total_posiciones': 0, 'vacias': 0, 'ocupadas': 0,
                'vacias_lista': [], 'ocupadas_lista': []}
    vacias = [l['complete_name'].replace('CA1/Stock/', '')
              for l in leaf if not l.get('quant_ids')]
    ocupadas = [l['complete_name'].replace('CA1/Stock/', '')
                for l in leaf if l.get('quant_ids')]
    return {
        'total_posiciones': len(leaf),
        'vacias': len(vacias),
        'ocupadas': len(ocupadas),
        'vacias_lista': sorted(vacias),
        'ocupadas_lista': sorted(ocupadas),
    }


def _stock_actual_m3(odoo: OdooClient) -> tuple[float, dict, dict, dict, list]:
    """Calcula m³ del stock actual cruzando stock.quant con product.template.volume.

    Returns:
        (m3_total, qty_by_sku, vol_unit_by_sku, m3_by_sku, anomalies)
    """
    print(f"[1/5] Cargando stock.quant (location internal)...", flush=True)
    quants = odoo.search_read_paginated(
        'stock.quant',
        [('location_id.usage', '=', 'internal'), ('quantity', '>', 0)],
        ['product_id', 'quantity'],
        page_size=2000,
    )
    print(f"      {len(quants)} quants", flush=True)

    qty_by_pid = defaultdict(float)
    for q in quants:
        pid = q.get('product_id', [None])[0] if q.get('product_id') else None
        if pid:
            qty_by_pid[pid] += q.get('quantity', 0) or 0

    if not qty_by_pid:
        return 0.0, {}, {}, {}, []

    pids = sorted(qty_by_pid.keys())
    print(f"[2/5] Cargando product.product → product_tmpl_id ({len(pids)} pids)...", flush=True)
    prods = odoo.execute_in_batches(
        'product.product', pids,
        ['id', 'default_code', 'product_tmpl_id'],
        batch_size=500,
    )
    pid_to_tmpl = {p['id']: (p['product_tmpl_id'][0] if p.get('product_tmpl_id') else None,
                              p.get('default_code') or '')
                   for p in prods}

    tmpl_ids = sorted({t for t, _ in pid_to_tmpl.values() if t})
    print(f"[3/5] Cargando product.template ({len(tmpl_ids)}) → volume...", flush=True)
    tmpls = odoo.execute_in_batches(
        'product.template', tmpl_ids,
        ['id', 'volume', 'weight'],
        batch_size=500,
    )
    vol_by_tmpl = {t['id']: float(t.get('volume') or 0) for t in tmpls}

    m3_total = 0.0
    m3_by_sku = {}
    qty_by_sku = {}
    vol_unit_by_sku = {}
    anomalies = []
    for pid, qty in qty_by_pid.items():
        tmpl, sku = pid_to_tmpl.get(pid, (None, ''))
        if not tmpl or not sku:
            continue
        vol_unit = vol_by_tmpl.get(tmpl, 0)
        # Stock por SKU SIEMPRE (aunque vol esté en 0 o sea anómalo)
        qty_by_sku[sku] = qty_by_sku.get(sku, 0) + qty

        if vol_unit > VOL_UNIT_ANOMALO_M3:
            anomalies.append({'sku': sku, 'vol_unit_m3': vol_unit, 'qty': qty})
            continue
        # vol_unit confiable
        if vol_unit > 0:
            vol_unit_by_sku[sku] = vol_unit
        m3 = vol_unit * qty
        if m3 > 0:
            m3_total += m3
            m3_by_sku[sku] = m3_by_sku.get(sku, 0) + m3

    return m3_total, qty_by_sku, vol_unit_by_sku, m3_by_sku, anomalies


def _transito_por_eta() -> dict:
    """{fecha_eta: m3_entrante}. Usa volumen confiable (sin anómalos)."""
    if not DIMENSIONES_PARQUET.exists():
        print(f"  WARN: no existe {DIMENSIONES_PARQUET}", flush=True)
        return {}
    df = pd.read_parquet(DIMENSIONES_PARQUET)
    if 'volumen_total_m3_clean' not in df.columns:
        df['volumen_total_m3_clean'] = df['volumen_total_m3']
    df['fecha_eta_bodega'] = pd.to_datetime(df['fecha_eta_bodega'], errors='coerce')
    df = df.dropna(subset=['fecha_eta_bodega'])
    serie = df.groupby(df['fecha_eta_bodega'].dt.date)['volumen_total_m3_clean'].sum()
    return {pd.Timestamp(k).date(): float(v) for k, v in serie.items()}


def _salidas_por_dia(
    vol_unit_stock: dict,
    qty_stock: dict,
    dim_df: pd.DataFrame,
    transito_por_sku: dict,
) -> tuple[dict, dict]:
    """{fecha: m3_saliente}. Combina forecast venta × vol unit por SKU,
    limitado al stock + entradas acumuladas (no se puede vender lo que no hay).

    Cobertura volumen:
      1. vol_unit_stock (stock actual Odoo product.template.volume)
      2. dim_df (vol unit confiable de SKUs importados, override si difiere)
      3. fallback: mediana del universo (no promedio — outliers afectan menos)

    Returns:
        (salidas_m3_por_fecha, debug_info{cobertura, fallback_value, ...})
    """
    if not FORECAST_PARQUET.exists():
        print(f"  WARN: no existe {FORECAST_PARQUET}", flush=True)
        return {}, {}

    fc = pd.read_parquet(FORECAST_PARQUET)
    fc = fc[['ds', 'sku', 'yhat_anchored']].copy()
    fc['ds'] = pd.to_datetime(fc['ds'])
    fc = fc.dropna(subset=['ds', 'sku'])
    fc['sku'] = fc['sku'].astype(str)
    fc['yhat_anchored'] = fc['yhat_anchored'].clip(lower=0)

    # Vol unit consolidado: stock + tránsito (override con tránsito si existe)
    vol_unit_by_sku = dict(vol_unit_stock)  # base: stock Odoo
    if not dim_df.empty:
        if 'volumen_unit_m3_clean' not in dim_df.columns:
            dim_df['volumen_unit_m3_clean'] = dim_df.get('volumen_unit_m3', 0)
        for _, r in dim_df.dropna(subset=['sku']).drop_duplicates('sku').iterrows():
            sku = str(r['sku'])
            v = float(r.get('volumen_unit_m3_clean') or 0)
            if v > 0:
                vol_unit_by_sku[sku] = v

    # Fallback: mediana de los volúmenes válidos (robusto a outliers)
    vols = sorted([v for v in vol_unit_by_sku.values() if v and 0 < v < VOL_UNIT_ANOMALO_M3])
    vol_unit_fallback = vols[len(vols) // 2] if vols else 0.01
    print(f"      Vol unit cobertura: {len(vol_unit_by_sku)} SKUs con dato Odoo · "
          f"mediana fallback {vol_unit_fallback:.4f} m³/unid (5L approx)", flush=True)

    # Stock disponible por SKU + entradas acumuladas (cap realista)
    # Si no hay stock ni tránsito de un SKU, esa demanda no se cumple.
    stock_disp = dict(qty_stock)  # copia
    transito_pendiente_sku = dict(transito_por_sku)

    # Diccionario de salidas y de demanda no cubierta
    salidas = defaultdict(float)
    salidas_unidades = defaultdict(float)
    demanda_no_cubierta = defaultdict(float)
    skus_sin_vol = set()

    # Procesar forecast día por día (asume orden por fecha)
    fc_sorted = fc.sort_values('ds')
    for fecha, grp in fc_sorted.groupby(fc_sorted['ds'].dt.date):
        for _, r in grp.iterrows():
            sku = r['sku']
            demanda = float(r['yhat_anchored'])
            if demanda <= 0:
                continue

            # Cap por stock disponible
            disp = stock_disp.get(sku, 0)
            cumplido = min(demanda, disp)
            if cumplido < demanda:
                demanda_no_cubierta[fecha] += demanda - cumplido
            stock_disp[sku] = max(0, disp - cumplido)

            if cumplido <= 0:
                continue

            v = vol_unit_by_sku.get(sku, 0)
            if not v or v <= 0:
                v = vol_unit_fallback
                skus_sin_vol.add(sku)

            salidas[fecha] += v * cumplido
            salidas_unidades[fecha] += cumplido

    # Aplicar entradas de tránsito al stock disponible cuando llega ETA
    # (esto debería ser día por día para más precisión, pero para mantener
    # el modelo simple: las salidas ya capturadas usan stock inicial; para
    # afinar, ver TODO en el extractor).

    debug = {
        'sku_con_vol_odoo': len(vol_unit_by_sku),
        'sku_fallback': len(skus_sin_vol),
        'fallback_vol_m3': round(vol_unit_fallback, 5),
        'demanda_no_cubierta_unidades_total': round(sum(demanda_no_cubierta.values()), 0),
        'salidas_unidades_90d_total': round(sum(salidas_unidades.values()), 0),
    }
    return ({pd.Timestamp(k).date(): float(v) for k, v in salidas.items()}, debug)


def main():
    print(f"=== Extract Capacidad Forecast — {datetime.now().isoformat()} ===\n", flush=True)

    if not ODOO_PWD:
        print("[ERROR] ANDRES_ODOO_PASSWORD/OPS_ODOO_PASSWORD no seteado", flush=True)
        return 1

    odoo = OdooClient(url=ODOO_URL, db=ODOO_DB, username=ODOO_USER, password=ODOO_PWD, max_retries=3)
    odoo.authenticate()

    # 1. Stock actual m³
    m3_stock, qty_stock, vol_unit_stock, m3_by_sku, stock_anomalies = _stock_actual_m3(odoo)
    print(f"      m3 stock actual: {m3_stock:,.1f} (SKUs con stock: {len(qty_stock)}, "
          f"con vol Odoo: {len(vol_unit_stock)}, anómalos: {len(stock_anomalies)})", flush=True)

    # 2. Tránsito por ETA + por SKU (para cap salidas con stock futuro)
    print(f"\n[4/5] Cargando tránsito por ETA desde dimensiones COMEX...", flush=True)
    transito = _transito_por_eta()
    print(f"      {len(transito)} fechas con entradas, total m3: "
          f"{sum(transito.values()):,.1f}", flush=True)

    # Tránsito por SKU (cantidad acumulada por SKU desde tránsito)
    transito_por_sku = {}
    if DIMENSIONES_PARQUET.exists():
        dim_full = pd.read_parquet(DIMENSIONES_PARQUET)
        if 'sku' in dim_full.columns and 'cantidad' in dim_full.columns:
            transito_por_sku = (dim_full.dropna(subset=['sku'])
                                          .groupby('sku')['cantidad'].sum()
                                          .to_dict())

    # Stock disponible total por SKU = stock actual + lo que llega por tránsito
    # (modelo conservador: TODO el tránsito 90d se considera disponible para
    # capear las salidas, sino la demanda 90d sería irreal vs stock actual)
    stock_total_disponible = dict(qty_stock)
    for sku, cant in transito_por_sku.items():
        stock_total_disponible[sku] = stock_total_disponible.get(sku, 0) + cant

    # 3. Salidas diarias forecast (capeado por stock disponible)
    print(f"\n[5/5] Calculando salidas diarias forecast venta × vol unit (cap por stock)...", flush=True)
    dim_df = pd.read_parquet(DIMENSIONES_PARQUET) if DIMENSIONES_PARQUET.exists() else pd.DataFrame()
    salidas, salidas_debug = _salidas_por_dia(
        vol_unit_stock, stock_total_disponible, dim_df, transito_por_sku,
    )
    print(f"      {len(salidas)} días con salidas, total m3 (90d): "
          f"{sum(salidas.values()):,.1f}", flush=True)
    print(f"      Cobertura vol unit: {salidas_debug['sku_con_vol_odoo']} SKUs Odoo · "
          f"{salidas_debug['sku_fallback']} fallback (mediana {salidas_debug['fallback_vol_m3']:.4f})",
          flush=True)
    print(f"      Demanda NO cubierta (sin stock ni tránsito): "
          f"{salidas_debug['demanda_no_cubierta_unidades_total']:,.0f} unid", flush=True)

    # 4. Capacidad bodega (REAL: posiciones leaf CA1/Stock — misma data que usa
    # Stock LIVE > Uso de posiciones, no asunción global)
    print(f"\n[6/6] Cargando posiciones reales CA1/Stock (vacías vs ocupadas)...", flush=True)
    pos = _posiciones_bodega(odoo)
    print(f"      Total posiciones leaf: {pos['total_posiciones']} "
          f"(vacías {pos['vacias']} · ocupadas {pos['ocupadas']})", flush=True)

    cap_m3_override, cap_fuente_manual = _capacidad_bodega_m3()
    if cap_m3_override > 0:
        cap_m3 = cap_m3_override
        cap_fuente = cap_fuente_manual
    else:
        cap_m3 = pos['total_posiciones'] * M3_POR_POSICION
        cap_fuente = f'{pos["total_posiciones"]} pos CA1/Stock × {M3_POR_POSICION} m³'

    # 5. Construir serie temporal usando POSICIONES como métrica primaria
    # (es la unidad real que opera la bodega, no m³ teóricos).
    #
    # MODELO:
    #   - posiciones_ocupadas_HOY = pos['ocupadas'] (dato REAL de Odoo)
    #   - posiciones_libres_HOY = pos['vacias']
    #   - Cada día: pos_ocup_t = pos_ocup_t-1 + pallets_entrantes - pallets_salientes
    #   - Pallets entrantes = sum(pallets_estim de PIs con ETA en ese día)
    #   - Pallets salientes = m3_saliente / M3_POR_PALLET (forecast venta convertido)
    print(f"\nConstruyendo serie temporal {HORIZONTE_DIAS} días (posiciones reales)…", flush=True)
    hoy = datetime.now().date()

    # Convertir entradas (m³ -> pallets entrantes por día)
    entradas_pallets = {f: m / M3_POR_PALLET for f, m in transito.items()}

    rows = []
    pos_ocup = pos['ocupadas']
    pos_total = pos['total_posiciones']

    for i in range(HORIZONTE_DIAS + 1):
        fecha = hoy + timedelta(days=i)
        ent_m3 = transito.get(fecha, 0)
        sal_m3 = salidas.get(fecha, 0)
        ent_pal = entradas_pallets.get(fecha, 0)
        sal_pal = sal_m3 / M3_POR_PALLET if sal_m3 > 0 else 0

        pos_ocup = max(0, pos_ocup + ent_pal - sal_pal)
        pos_disp = max(0, pos_total - pos_ocup)
        pct = (pos_ocup / pos_total * 100) if pos_total > 0 else 0

        if pct >= PCT_CRITICO:
            alerta = '🔴 BODEGA LLENA'
        elif pct >= PCT_ALERTA:
            alerta = '🟠 ATENCIÓN'
        elif pct >= 70:
            alerta = '🟡 MONITOREO'
        else:
            alerta = '🟢 OK'

        rows.append({
            'fecha': fecha,
            'posiciones_ocupadas': round(pos_ocup, 1),
            'posiciones_disp': round(pos_disp, 1),
            'pallets_entrantes_dia': round(ent_pal, 1),
            'pallets_salientes_dia': round(sal_pal, 1),
            'm3_entrante_dia': round(ent_m3, 1),
            'm3_saliente_dia': round(sal_m3, 1),
            'pct_ocupacion': round(pct, 1),
            'alerta': alerta,
        })

    df_fc = pd.DataFrame(rows)
    df_fc.to_parquet(OUT_PARQUET, index=False)
    print(f"  parquet: {OUT_PARQUET}", flush=True)

    # 6. Eventos clave
    primer_critico = df_fc[df_fc['alerta'] == '🔴 BODEGA LLENA']
    primer_atencion = df_fc[df_fc['alerta'].isin(['🟠 ATENCIÓN', '🔴 BODEGA LLENA'])]
    pico = df_fc.loc[df_fc['posiciones_ocupadas'].idxmax()]
    minimo = df_fc.loc[df_fc['posiciones_ocupadas'].idxmin()]

    # Días con entrada de tránsito
    dias_entrada = [{'fecha': r['fecha'].isoformat(),
                      'pallets': r['pallets_entrantes_dia'],
                      'm3': r['m3_entrante_dia']}
                     for r in df_fc.to_dict('records') if r['pallets_entrantes_dia'] > 0]

    # Cruzar entradas con PIs específicas (para insights por embarque)
    pis_entrantes = []
    if DIMENSIONES_PARQUET.exists():
        try:
            from json import load as _jl
            with open(PROJECT_ROOT / 'data' / 'comex' / 'dimensiones_resumen.json',
                       encoding='utf-8') as f:
                dim_resumen = _jl(f)
            for pi_info in dim_resumen.get('por_pi', []):
                eta = pi_info.get('fecha_eta_bodega') or ''
                if not eta:
                    continue
                try:
                    eta_d = datetime.strptime(eta[:10], '%Y-%m-%d').date()
                except Exception:
                    continue
                # Solo PIs cuyo ETA está en el horizonte (incluye vencidas recientes)
                if (eta_d - hoy).days > HORIZONTE_DIAS:
                    continue
                pis_entrantes.append({
                    'pi': pi_info['pi'],
                    'fecha_eta': eta,
                    'pallets': pi_info.get('pallets_estim', 0),
                    'm3': pi_info.get('volumen_total_m3', 0),
                    'unidades': pi_info.get('unidades_totales', 0),
                    'transporte': pi_info.get('transporte', ''),
                })
        except Exception:
            pass

    # Resumen
    resumen = {
        'generado_en': datetime.now().isoformat(),
        'horizonte_dias': HORIZONTE_DIAS,
        # Capacidad expresada en POSICIONES REALES (CA1/Stock leaf)
        'capacidad_posiciones': pos['total_posiciones'],
        'capacidad_bodega_m3': cap_m3,
        'capacidad_fuente': cap_fuente,
        'asunciones': {
            'm3_por_posicion': M3_POR_POSICION,
            'm3_por_pallet_apilable': M3_POR_PALLET,
            'umbral_anomalo_m3_unidad': VOL_UNIT_ANOMALO_M3,
        },
        'estado_actual': {
            'posiciones_total': pos['total_posiciones'],
            'posiciones_ocupadas_hoy': pos['ocupadas'],
            'posiciones_libres_hoy': pos['vacias'],
            'pct_ocupacion_hoy': round(pos['ocupadas'] / pos['total_posiciones'] * 100, 1)
                                  if pos['total_posiciones'] else 0,
            'm3_stock_calculado': round(m3_stock, 1),
        },
        'pico_proyectado': {
            'fecha': pico['fecha'].isoformat(),
            'posiciones_ocupadas': pico['posiciones_ocupadas'],
            'pct_ocupacion': pico['pct_ocupacion'],
        },
        'minimo_proyectado': {
            'fecha': minimo['fecha'].isoformat(),
            'posiciones_ocupadas': minimo['posiciones_ocupadas'],
            'pct_ocupacion': minimo['pct_ocupacion'],
        },
        'primer_critico': (primer_critico.iloc[0]['fecha'].isoformat()
                            if not primer_critico.empty else None),
        'primer_atencion': (primer_atencion.iloc[0]['fecha'].isoformat()
                             if not primer_atencion.empty else None),
        'dias_con_entrada_transito': dias_entrada,
        'pis_entrantes': sorted(pis_entrantes, key=lambda x: x['fecha_eta']),
        'pallets_total_entrantes_horizonte': round(sum(entradas_pallets.values()), 1),
        'pallets_total_salientes_horizonte': round(sum(salidas.values()) / M3_POR_PALLET, 1),
        'm3_total_entrante_horizonte': round(sum(transito.values()), 1),
        'm3_total_saliente_horizonte': round(sum(salidas.values()), 1),
        'salidas_debug': salidas_debug,
        'stock_anomalies_count': len(stock_anomalies),
        'top_stock_anomalies': stock_anomalies[:10],
    }

    with open(OUT_RESUMEN, 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=str)
    print(f"  resumen: {OUT_RESUMEN}", flush=True)

    print(f"\n=== RESUMEN ===")
    print(f"  Capacidad bodega: {pos['total_posiciones']:,} posiciones CA1/Stock leaf [{cap_fuente}]")
    print(f"  Estado HOY: {pos['ocupadas']} ocupadas / {pos['vacias']} libres "
          f"({pos['ocupadas']/pos['total_posiciones']*100:.1f}% ocupación)"
          if pos['total_posiciones'] else "")
    print(f"  Pico {HORIZONTE_DIAS}d: {pico['posiciones_ocupadas']:,.0f} posiciones "
          f"({pico['pct_ocupacion']:.0f}%) el {pico['fecha']}")
    print(f"  Pallets entrantes próximos {HORIZONTE_DIAS}d: "
          f"{resumen['pallets_total_entrantes_horizonte']:,.0f} de {len(pis_entrantes)} PIs")
    if resumen['primer_critico']:
        print(f"  🔴 PRIMER CRÍTICO: {resumen['primer_critico']}")
    if resumen['primer_atencion']:
        print(f"  🟠 PRIMER ATENCIÓN: {resumen['primer_atencion']}")
    print(f"\nOK")
    return 0


if __name__ == '__main__':
    sys.exit(main())
