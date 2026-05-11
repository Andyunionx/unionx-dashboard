#!/usr/bin/env python3
"""
Forecast SKU x canal anchored (Fase 2):

1. Toma forecast_skus.parquet base (Prophet con regresores stock/pricing).
2. Aplica BOOST de evento por SKU usando elasticidad de su categoria:
   boost = (1 + |elasticidad_cat|) * descuento_esperado_evento
3. Aplica LIFT cross-product: si SKU A es bestseller en evento, sus SKUs
   complementarios (lift>2 en market basket) tambien se boostean.
4. Stock futuro = 1 siempre (asume disponibilidad — gap = senal de compra para Planificacion).
5. Reconcilia bottom-up: SKU -> Categoria -> Canal -> Empresa.
   Compara contra el TOTAL anchored y reporta gap.

Input:
- data/forecast/forecast_skus.parquet (base Prophet por SKU x canal)
- data/forecast/elasticidad_categoria.parquet
- data/forecast/market_basket.parquet
- data/forecast/forecast_resumen.json (TOTAL anchored para comparar)
- data/historico/ventas_historico.parquet (categoria por SKU)

Output:
- data/forecast/forecast_skus_anchored.parquet (yhat por SKU x canal x dia + boost por evento)
- data/forecast/forecast_demanda_por_evento.parquet (resumen demanda esperada por SKU x evento)
- data/forecast/reconciliation_bottom_up.json (suma bottom-up vs TOTAL anchored)
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / 'data' / 'forecast'

HIST_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'

# === Eventos con descuento esperado (alineado con extract_forecast_anchored) ===
EVENTOS_2026 = [
    # (nombre, fi, ff, descuento_esperado_promedio_del_evento)
    ('cyber_day',    '2026-06-01', '2026-06-04', 0.20),   # 20% descuento promedio
    ('cyber_monday', '2026-10-06', '2026-10-09', 0.22),
    ('black_friday', '2026-11-26', '2026-11-30', 0.18),
    ('navidad',      '2026-12-05', '2026-12-25', 0.10),   # navidad menos descuento, mas regalo
]


def main():
    print(f"=== Forecast SKU x canal ANCHORED (Fase 2) — {datetime.now()} ===\n", flush=True)

    # 1. Cargar base
    skus_path = OUT_DIR / 'forecast_skus.parquet'
    if not skus_path.exists():
        print("[ERROR] forecast_skus.parquet no existe. Correr extract_forecast_skus.py primero")
        sys.exit(1)
    fc_skus = pd.read_parquet(skus_path)
    fc_skus['ds'] = pd.to_datetime(fc_skus['ds'])
    fc_skus['sku'] = fc_skus['sku'].astype(str)
    print(f"[1] forecast_skus: {len(fc_skus):,} filas ({fc_skus['sku'].nunique()} SKUs × {fc_skus['canal'].nunique()} canales)", flush=True)

    # Filtrar futuro estricto
    hoy = pd.Timestamp(datetime.now().date())
    fc_skus = fc_skus[fc_skus['ds'] > hoy].copy()
    # Asumir stock futuro = 1 (demanda no restringida)
    # No hacemos nada explicito porque el Prophet base ya tenia regresor tuvo_stock=1 imputado
    # cuando no habia info historica futura. Aqui solo lo documentamos.
    print(f"    Futuro estricto: {len(fc_skus):,} filas, {fc_skus['ds'].nunique()} dias", flush=True)
    print(f"    [info] stock_futuro=1 asumido (forecast es demanda, no restringe por stock proyectado)", flush=True)

    # 2. Cargar elasticidad por categoria + meta SKU
    elast_path = OUT_DIR / 'elasticidad_categoria.parquet'
    if not elast_path.exists():
        print("[WARN] elasticidad_categoria no existe. Boost por evento sera uniforme")
        elast_cat = {}
    else:
        ec = pd.read_parquet(elast_path)
        elast_cat = dict(zip(ec['categoria_padre'].astype(str), ec['elasticidad'].astype(float)))
        print(f"[2] Elasticidad por categoria: {len(elast_cat)} categorias", flush=True)

    sku_meta = {}
    if HIST_PARQUET.exists():
        h = pd.read_parquet(HIST_PARQUET, columns=['sku', 'marca', 'categoria_padre', 'categoria_hijo', 'tipo_negocio', 'producto'])
        h['sku'] = h['sku'].astype(str)
        sku_meta = h.drop_duplicates('sku').set_index('sku').to_dict(orient='index')
        print(f"    SKU meta cargado: {len(sku_meta)} SKUs", flush=True)

    # 3. Cargar market basket para lift cross-product
    basket_path = OUT_DIR / 'market_basket.parquet'
    if not basket_path.exists():
        print("[WARN] market_basket no existe. Sin lift cross-product")
        basket_lift = {}
    else:
        mb = pd.read_parquet(basket_path)
        # Diccionario: sku_a -> [(sku_b, lift), ...] solo lift > 2
        basket_lift = defaultdict(list)
        for _, r in mb[mb['lift'] > 2].iterrows():
            basket_lift[str(r['sku_a'])].append((str(r['sku_b']), float(r['lift'])))
            basket_lift[str(r['sku_b'])].append((str(r['sku_a']), float(r['lift'])))
        print(f"[3] Market basket: {len(basket_lift)} SKUs con pares lift>2", flush=True)

    # 4. Aplicar boost por evento a nivel SKU
    print(f"\n[4] Calculando boost por evento por SKU...", flush=True)
    fc_skus['categoria_padre'] = fc_skus['sku'].map(lambda s: sku_meta.get(s, {}).get('categoria_padre') or '?')
    fc_skus['marca'] = fc_skus['sku'].map(lambda s: sku_meta.get(s, {}).get('marca') or '?')
    fc_skus['tipo_negocio'] = fc_skus['sku'].map(lambda s: sku_meta.get(s, {}).get('tipo_negocio') or '?')
    fc_skus['producto'] = fc_skus['sku'].map(lambda s: sku_meta.get(s, {}).get('producto') or '?')
    fc_skus['yhat_base'] = fc_skus['yhat']
    fc_skus['evento'] = None
    fc_skus['boost_evento'] = 1.0
    fc_skus['boost_basket'] = 1.0

    # Identificar bestsellers por evento (top 20% en venta historica anual)
    bestsellers = set()
    if HIST_PARQUET.exists():
        h = pd.read_parquet(HIST_PARQUET, columns=['sku', 'venta_bruta', 'tipo_movimiento', 'fecha_venta'])
        h = h[h['tipo_movimiento'] == 'Venta'].copy()
        h['sku'] = h['sku'].astype(str)
        h['fecha_venta'] = pd.to_datetime(h['fecha_venta'], errors='coerce')
        cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=365)
        h = h[h['fecha_venta'] >= cutoff]
        venta_sku = h.groupby('sku')['venta_bruta'].sum().sort_values(ascending=False)
        # Top 20% de SKUs por venta
        n_top = max(20, len(venta_sku) // 5)
        bestsellers = set(venta_sku.head(n_top).index)
        print(f"   Bestsellers (top 20% venta LTM): {len(bestsellers)}", flush=True)

    # Aplicar boost por evento
    for nombre, fi, ff, desc in EVENTOS_2026:
        fi_ts, ff_ts = pd.Timestamp(fi), pd.Timestamp(ff)
        mask_evt = (fc_skus['ds'] >= fi_ts) & (fc_skus['ds'] <= ff_ts)
        if not mask_evt.any():
            continue

        # Calculo de boost por SKU = 1 + |elasticidad_cat| * descuento_esperado
        # Productos elasticos (|e|>0.8) suben mas. Inelasticos (|e|<0.2) casi no.
        elast = fc_skus.loc[mask_evt, 'categoria_padre'].map(
            lambda c: abs(elast_cat.get(c, -0.3))  # default elasticidad moderada
        )
        boost = 1.0 + elast * desc
        # Cap: max boost 2.5x (productos super elasticos en eventos grandes)
        boost = boost.clip(upper=2.5)

        fc_skus.loc[mask_evt, 'evento'] = nombre
        fc_skus.loc[mask_evt, 'boost_evento'] = boost.values

        n_skus = fc_skus.loc[mask_evt, 'sku'].nunique()
        boost_avg = float(boost.mean())
        print(f"   {nombre:>13} | desc={desc*100:.0f}% | boost avg {boost_avg:.2f}x | {n_skus} SKUs", flush=True)

    # 5. Aplicar lift basket: si SKU es bestseller en un evento, sus complementarios suben
    print(f"\n[5] Aplicando lift basket cross-product...", flush=True)
    n_lift_aplicado = 0
    for nombre, fi, ff, _ in EVENTOS_2026:
        fi_ts, ff_ts = pd.Timestamp(fi), pd.Timestamp(ff)
        mask_evt = (fc_skus['ds'] >= fi_ts) & (fc_skus['ds'] <= ff_ts)
        if not mask_evt.any():
            continue

        skus_en_evento = set(fc_skus.loc[mask_evt, 'sku'].unique())
        bestsellers_evento = skus_en_evento & bestsellers

        # Cada SKU complementario de un bestseller recibe boost extra (suave)
        skus_con_lift = {}  # sku -> max lift normalizado
        for bs in bestsellers_evento:
            for sku_b, lift in basket_lift.get(bs, []):
                if sku_b in skus_en_evento:
                    # Boost lift = 1 + 0.05*log(lift). Lift=10 -> +0.12, lift=100 -> +0.23
                    boost_l = 1 + 0.05 * np.log(max(lift, 1.01))
                    skus_con_lift[sku_b] = max(skus_con_lift.get(sku_b, 1.0), boost_l)

        if skus_con_lift:
            for sku, boost_l in skus_con_lift.items():
                mask_sku = mask_evt & (fc_skus['sku'] == sku)
                fc_skus.loc[mask_sku, 'boost_basket'] = boost_l
            n_lift_aplicado += len(skus_con_lift)

    print(f"   Boost basket aplicado a {n_lift_aplicado} (sku, evento) pairs", flush=True)

    # 6. yhat final = yhat_base * boost_evento * boost_basket (clip por ratio historico)
    fc_skus['yhat_anchored_raw'] = fc_skus['yhat_base'] * fc_skus['boost_evento'] * fc_skus['boost_basket']

    # Anti-outlier: capear yhat por SKU si total proyectado >> historico real 365d
    print(f"\n[6a] Cap outliers vs historico real 365d...", flush=True)
    if HIST_PARQUET.exists():
        h = pd.read_parquet(HIST_PARQUET, columns=['sku', 'cantidad', 'tipo_movimiento', 'fecha_venta'])
        h = h[h['tipo_movimiento'] == 'Venta'].copy()
        h['sku'] = h['sku'].astype(str)
        h['fecha_venta'] = pd.to_datetime(h['fecha_venta'], errors='coerce')
        cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=365)
        h = h[h['fecha_venta'] >= cutoff]
        venta_hist_sku = h.groupby('sku')['cantidad'].sum()

        # Por SKU: calcular ratio proyectado / historico, capear si > 3
        proy_por_sku = fc_skus.groupby('sku')['yhat_anchored_raw'].sum()
        ratios = (proy_por_sku / venta_hist_sku.reindex(proy_por_sku.index).fillna(1).clip(lower=1))
        skus_outlier = ratios[ratios > 3].index
        if len(skus_outlier) > 0:
            print(f"   Outliers detectados: {len(skus_outlier)} SKUs con proyeccion > 3x historico", flush=True)
            for sku in skus_outlier[:5]:
                print(f"     {sku}: proy={proy_por_sku[sku]:.0f} vs hist={venta_hist_sku.get(sku, 0):.0f} (ratio={ratios[sku]:.1f}x)", flush=True)
            # Capear: cada SKU outlier reescalado para que ratio = 3
            for sku in skus_outlier:
                hist = venta_hist_sku.get(sku, 1)
                target = hist * 3  # max 3x historico
                proy = proy_por_sku[sku]
                if proy > target:
                    factor_cap = target / proy
                    mask = fc_skus['sku'] == sku
                    fc_skus.loc[mask, 'yhat_anchored_raw'] *= factor_cap

    fc_skus['yhat_anchored'] = fc_skus['yhat_anchored_raw'].clip(lower=0).round(0)
    fc_skus['delta_pct'] = ((fc_skus['yhat_anchored'] - fc_skus['yhat_base']) / fc_skus['yhat_base'].clip(lower=0.1) * 100).round(1)
    fc_skus = fc_skus.drop(columns=['yhat_anchored_raw'])

    # Output
    out_path = OUT_DIR / 'forecast_skus_anchored.parquet'
    cols_out = ['ds', 'sku', 'canal', 'producto', 'marca', 'categoria_padre', 'tipo_negocio',
                 'yhat_base', 'boost_evento', 'boost_basket', 'yhat_anchored', 'evento', 'delta_pct']
    fc_skus[cols_out].to_parquet(out_path, compression='zstd', compression_level=9, index=False)
    print(f"\n[6] {out_path.name}: {len(fc_skus):,} filas", flush=True)

    # 7. Resumen demanda por (sku, evento)
    demanda_evento = (fc_skus[fc_skus['evento'].notna()]
        .groupby(['sku', 'producto', 'categoria_padre', 'marca', 'canal', 'evento'], as_index=False, dropna=False)
        .agg(
            unidades_proyectadas=('yhat_anchored', 'sum'),
            unidades_base_sin_boost=('yhat_base', 'sum'),
            boost_promedio=('boost_evento', 'mean'),
            dias_evento=('ds', 'nunique'),
        ))
    demanda_evento['boost_lift_extra_pct'] = (
        (demanda_evento['unidades_proyectadas'] / demanda_evento['unidades_base_sin_boost'].clip(lower=0.1) - 1) * 100
    ).round(1)
    demanda_evento.to_parquet(OUT_DIR / 'forecast_demanda_por_evento.parquet',
                                compression='zstd', index=False)
    print(f"[7] forecast_demanda_por_evento: {len(demanda_evento):,} (sku, evento) pairs", flush=True)

    # 8. Reconciliacion bottom-up vs TOTAL anchored
    print(f"\n[8] Reconciliacion bottom-up...", flush=True)
    # Necesito convertir yhat_anchored (unidades) a $ usando precio reciente
    # Usar precio HISTORICO LTM (estable). El precio reciente 30d tiene outliers
    # cuando hay pocas ventas en el periodo (ej: una venta corporativa de un retail
    # infla el precio promedio absurdamente para SKUs de bajo precio).
    if HIST_PARQUET.exists():
        h = pd.read_parquet(HIST_PARQUET, columns=['sku', 'canal', 'cantidad', 'venta_bruta', 'tipo_movimiento', 'fecha_venta'])
        h = h[h['tipo_movimiento'] == 'Venta'].copy()
        h['sku'] = h['sku'].astype(str)
        h['fecha_venta'] = pd.to_datetime(h['fecha_venta'], errors='coerce')
        cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=365)
        h = h[(h['fecha_venta'] >= cutoff) & (h['cantidad'] > 0)]
        precios = h.groupby(['sku', 'canal'], observed=True).agg(
            venta_bruta=('venta_bruta', 'sum'), cantidad=('cantidad', 'sum')
        )
        precios['precio_unidad'] = precios['venta_bruta'] / precios['cantidad'].clip(lower=1)
        precios = precios['precio_unidad'].reset_index()
        print(f"   Precios LTM: {len(precios):,} (sku, canal) | mediana ${precios['precio_unidad'].median():,.0f}", flush=True)

        fc_dol = fc_skus.merge(precios, on=['sku', 'canal'], how='left')
        fc_dol['precio_unidad'] = fc_dol['precio_unidad'].fillna(fc_dol['precio_unidad'].median())
        fc_dol['venta_anchored_dol'] = fc_dol['yhat_anchored'].clip(lower=0) * fc_dol['precio_unidad']

        # Cap final por venta $ vs venta histórica $: si proyectado > 3x histórico → escalar
        venta_hist_sku = h.groupby('sku')['venta_bruta'].sum()
        proy_dol_sku = fc_dol.groupby('sku')['venta_anchored_dol'].sum()
        ratios = (proy_dol_sku / venta_hist_sku.reindex(proy_dol_sku.index).fillna(1).clip(lower=1))
        outliers_dol = ratios[ratios > 3].index
        if len(outliers_dol) > 0:
            print(f"   Cap final por venta_$ vs hist: {len(outliers_dol)} SKUs", flush=True)
            for sku in outliers_dol:
                hist_dol = venta_hist_sku.get(sku, 1)
                target_dol = hist_dol * 3
                proy_dol = proy_dol_sku[sku]
                if proy_dol > target_dol:
                    factor = target_dol / proy_dol
                    mask = fc_dol['sku'] == sku
                    fc_dol.loc[mask, 'venta_anchored_dol'] *= factor
                    fc_dol.loc[mask, 'yhat_anchored'] = (fc_dol.loc[mask, 'yhat_anchored'] * factor).round(0)

        bottom_up_total = float(fc_dol['venta_anchored_dol'].sum())

        # Rango bottom-up
        fc_dol['fecha_d'] = fc_dol['ds'].dt.normalize()
        bottom_up_desde = fc_dol['fecha_d'].min()
        bottom_up_hasta = fc_dol['fecha_d'].max()
        n_dias_bu = fc_dol['fecha_d'].nunique()

        # Comparar con TOTAL anchored MISMO RANGO (no todo el anio)
        resumen_path = OUT_DIR / 'forecast_resumen.json'
        gap_pct = None
        total_anchored_mismo_rango = None
        if resumen_path.exists():
            anual_path = OUT_DIR / 'forecast_anual.parquet'
            if anual_path.exists():
                anual = pd.read_parquet(anual_path)
                anual['ds'] = pd.to_datetime(anual['ds'])
                anual_rango = anual[(anual['ds'] >= bottom_up_desde) & (anual['ds'] <= bottom_up_hasta)]
                total_anchored_mismo_rango = float(anual_rango['yhat'].sum())
                if total_anchored_mismo_rango > 0:
                    gap_pct = (bottom_up_total - total_anchored_mismo_rango) / total_anchored_mismo_rango * 100

        print(f"   Bottom-up SKU x canal anchored ({n_dias_bu}d {bottom_up_desde.date()} -> {bottom_up_hasta.date()}):", flush=True)
        print(f"     ${bottom_up_total/1e6:>8,.0f}M", flush=True)
        if total_anchored_mismo_rango:
            print(f"   TOTAL anchored MISMO RANGO ({n_dias_bu}d): ${total_anchored_mismo_rango/1e6:>8,.0f}M", flush=True)
            print(f"   Gap (bottom-up cubre los SKUs top, gap=cola larga): {gap_pct:+.1f}%", flush=True)

        reco = {
            'generado_en': datetime.now().isoformat(),
            'bottom_up_skus_anchored_$': bottom_up_total,
            'total_anchored_mismo_rango_$': total_anchored_mismo_rango,
            'gap_pct': gap_pct,
            'rango_dias': n_dias_bu,
            'fecha_desde': str(bottom_up_desde.date()),
            'fecha_hasta': str(bottom_up_hasta.date()),
            'n_skus_forecasteados': int(fc_skus['sku'].nunique()),
            'n_pares_sku_canal': int(len(fc_skus[['sku', 'canal']].drop_duplicates())),
            'cobertura_estimada_pct': float(bottom_up_total / total_anchored_mismo_rango * 100) if total_anchored_mismo_rango else None,
            'note': 'Bottom-up cubre los SKUs forecasteados (top ~90% venta LY). Gap negativo esperado = cola larga no modelada.',
        }
    else:
        reco = {'error': 'pricing_historico no existe'}

    with open(OUT_DIR / 'reconciliation_bottom_up.json', 'w', encoding='utf-8') as f:
        json.dump(reco, f, indent=2, default=str)
    print(f"[9] reconciliation_bottom_up.json escrito", flush=True)

    print(f"\n[OK] Forecast SKU x canal anchored generado")


if __name__ == '__main__':
    main()
