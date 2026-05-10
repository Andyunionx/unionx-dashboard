#!/usr/bin/env python3
"""
Calcula:
1. Elasticidad-precio por categoria_padre y por SKU (modelo log-log)
   beta = elasticidad. Si bajo precio 10% -> venta sube |beta|*10%
2. Complementariedad / market basket lift (pares de SKUs comprados juntos)

Output:
- data/forecast/elasticidad_categoria.parquet (categoria, beta, p_value, n_obs, intercept)
- data/forecast/elasticidad_sku.parquet (sku, canal, beta, p_value, n_obs)
- data/forecast/market_basket.parquet (sku_a, sku_b, n_pedidos_juntos, support, confidence_a_b, lift)
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from itertools import combinations
from collections import Counter

import numpy as np
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / 'data' / 'forecast'
OUT_DIR.mkdir(parents=True, exist_ok=True)

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')
HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}

HIST_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
PRICING_HIST = PROJECT_ROOT / 'data' / 'pricing_historico' / 'pricing_diario.parquet'


def _q(sql: str, retries: int = 3):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    import time
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


# ============================================================
# ELASTICIDAD-PRECIO (modelo log-log)
# ============================================================
def calcular_elasticidad():
    """Modelo log(cantidad) ~ alpha + beta*log(precio). beta = elasticidad."""
    print("[ELASTICIDAD] Cargando datos...", flush=True)
    pricing = pd.read_parquet(PRICING_HIST)
    pricing['fecha'] = pd.to_datetime(pricing['fecha'])
    pricing['sku'] = pricing['sku'].astype(str)

    # Filtrar registros utiles: precio > 0, cantidad > 0
    pricing = pricing[(pricing['precio_promedio_dia'] > 0) & (pricing['cantidad'] > 0)].copy()
    pricing['log_q'] = np.log(pricing['cantidad'])
    pricing['log_p'] = np.log(pricing['precio_promedio_dia'])

    # Mapear sku -> categoria_padre desde el parquet historico
    if HIST_PARQUET.exists():
        h = pd.read_parquet(HIST_PARQUET, columns=['sku', 'marca', 'categoria_padre'])
        h['sku'] = h['sku'].astype(str)
        sku_meta = h.drop_duplicates('sku').set_index('sku')
        pricing = pricing.join(sku_meta, on='sku', how='left')
    else:
        pricing['categoria_padre'] = None
        pricing['marca'] = None

    # === Elasticidad por categoria ===
    print("[ELASTICIDAD] Por categoria_padre (regresion log-log)...", flush=True)
    res_cat = []
    for cat, g in pricing.groupby('categoria_padre', observed=True):
        if not cat or len(g) < 100:  # minimo de obs para tener señal
            continue
        x = g['log_p'].values
        y = g['log_q'].values
        # Regresion simple OLS: y = a + b*x
        x_mean, y_mean = x.mean(), y.mean()
        cov = np.mean((x - x_mean) * (y - y_mean))
        var_x = np.var(x)
        if var_x < 1e-10:
            continue
        beta = cov / var_x
        alpha = y_mean - beta * x_mean
        # R2
        y_pred = alpha + beta * x
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y_mean) ** 2)
        r2 = 1 - ss_res / max(ss_tot, 1e-10)
        # SE de beta y t-stat
        n = len(g)
        se_beta = np.sqrt(ss_res / (n - 2)) / np.sqrt(np.sum((x - x_mean) ** 2)) if n > 2 else None
        t_stat = beta / se_beta if se_beta and se_beta > 0 else None
        res_cat.append({
            'categoria_padre': cat,
            'elasticidad': float(beta),
            'r2': float(r2),
            't_stat': float(t_stat) if t_stat is not None else None,
            'n_obs': int(n),
            'precio_promedio': float(g['precio_promedio_dia'].mean()),
            'cantidad_promedio': float(g['cantidad'].mean()),
        })
    df_cat = pd.DataFrame(res_cat).sort_values('elasticidad')

    print(f"[ELASTICIDAD] Categorias con elasticidad: {len(df_cat)}", flush=True)
    if not df_cat.empty:
        print(f"   Mas elastica: {df_cat.iloc[0]['categoria_padre']} (beta={df_cat.iloc[0]['elasticidad']:.2f})")
        print(f"   Mas inelastica: {df_cat.iloc[-1]['categoria_padre']} (beta={df_cat.iloc[-1]['elasticidad']:.2f})")

    df_cat.to_parquet(OUT_DIR / 'elasticidad_categoria.parquet',
                       compression='zstd', index=False)

    # === Elasticidad por SKU (top 100 con mas observaciones) ===
    print("[ELASTICIDAD] Top SKUs (regresion individual)...", flush=True)
    sku_counts = pricing.groupby(['sku', 'canal']).size().sort_values(ascending=False)
    top_pares = sku_counts[sku_counts >= 60].index.tolist()[:300]

    res_sku = []
    for sku, canal in top_pares:
        g = pricing[(pricing['sku'] == sku) & (pricing['canal'] == canal)]
        if len(g) < 60:
            continue
        x = g['log_p'].values
        y = g['log_q'].values
        x_mean, y_mean = x.mean(), y.mean()
        var_x = np.var(x)
        if var_x < 1e-6:
            continue
        cov = np.mean((x - x_mean) * (y - y_mean))
        beta = cov / var_x
        y_pred = beta * (x - x_mean) + y_mean
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y_mean) ** 2)
        r2 = 1 - ss_res / max(ss_tot, 1e-10)
        res_sku.append({
            'sku': sku, 'canal': canal,
            'elasticidad': float(beta),
            'r2': float(r2),
            'n_obs': int(len(g)),
            'precio_promedio': float(g['precio_promedio_dia'].mean()),
        })
    df_sku = pd.DataFrame(res_sku)
    df_sku.to_parquet(OUT_DIR / 'elasticidad_sku.parquet', compression='zstd', index=False)
    print(f"[ELASTICIDAD] {len(df_sku)} SKU x canal con regresion", flush=True)


# ============================================================
# MARKET BASKET (lift entre pares de SKUs)
# ============================================================
def calcular_market_basket():
    """Pares de SKUs frecuentemente comprados juntos en el mismo pedido.

    Lift > 1: comprados juntos mas que esperado por azar.
    """
    print("\n[BASKET] Cargando pedidos desde Turso (sample)...", flush=True)

    # Para mantenerlo manejable: pedidos de los ultimos 90 dias
    rows = _q("""
        SELECT pedido, sku, SUM(cantidad)
        FROM ventas
        WHERE tipo_movimiento = 'Venta'
          AND fecha_venta >= date('now', '-90 days')
          AND pedido IS NOT NULL AND pedido <> ''
          AND cantidad > 0
        GROUP BY pedido, sku
    """)
    print(f"   {len(rows):,} (pedido, sku) registros", flush=True)
    if not rows:
        print("[ERROR] Sin pedidos")
        return

    df = pd.DataFrame([{
        'pedido': _val(r, 0),
        'sku': str(_val(r, 1)),
    } for r in rows])

    # Pedidos con > 1 SKU (de lo contrario no hay basket)
    pedidos_multi = df.groupby('pedido').filter(lambda x: len(x) > 1)
    n_pedidos_multi = pedidos_multi['pedido'].nunique()
    print(f"   Pedidos multi-SKU: {n_pedidos_multi:,}", flush=True)

    if n_pedidos_multi < 100:
        print("[BASKET] Insuficientes pedidos multi-SKU para analisis robusto")
        return

    # Frecuencia individual de cada SKU
    sku_pedidos = df.groupby('sku')['pedido'].nunique()
    n_pedidos_total = df['pedido'].nunique()

    # Filtrar: solo SKUs presentes en al menos 30 pedidos (descartar cola larga)
    skus_relevantes = set(sku_pedidos[sku_pedidos >= 30].index)
    print(f"   SKUs relevantes (>=30 pedidos): {len(skus_relevantes):,}", flush=True)

    pedidos_filtrados = pedidos_multi[pedidos_multi['sku'].isin(skus_relevantes)]
    pedidos_filtrados_grp = pedidos_filtrados.groupby('pedido')['sku'].apply(list)

    # Contar pares co-ocurrentes
    print("   Contando pares co-ocurrentes...", flush=True)
    pares = Counter()
    for skus in pedidos_filtrados_grp:
        for a, b in combinations(sorted(set(skus)), 2):
            pares[(a, b)] += 1

    print(f"   Pares unicos: {len(pares):,}", flush=True)

    # Calcular lift / confidence solo para pares con >= 5 ocurrencias
    res = []
    for (a, b), n_juntos in pares.items():
        if n_juntos < 5:
            continue
        n_a = sku_pedidos.get(a, 0)
        n_b = sku_pedidos.get(b, 0)
        if n_a == 0 or n_b == 0:
            continue
        support = n_juntos / n_pedidos_total
        confidence_a_b = n_juntos / n_a  # P(B|A)
        confidence_b_a = n_juntos / n_b  # P(A|B)
        # Lift = P(A,B) / (P(A)*P(B))
        lift = (n_juntos * n_pedidos_total) / (n_a * n_b)
        res.append({
            'sku_a': a, 'sku_b': b,
            'n_pedidos_juntos': int(n_juntos),
            'n_pedidos_a': int(n_a),
            'n_pedidos_b': int(n_b),
            'support': float(support),
            'confidence_a_to_b': float(confidence_a_b),
            'confidence_b_to_a': float(confidence_b_a),
            'lift': float(lift),
        })
    df_basket = pd.DataFrame(res).sort_values('lift', ascending=False)
    df_basket.to_parquet(OUT_DIR / 'market_basket.parquet', compression='zstd', index=False)
    print(f"[BASKET] {len(df_basket):,} pares relevantes", flush=True)
    if not df_basket.empty:
        print(f"   Top 5 lift:")
        for _, r in df_basket.head(5).iterrows():
            print(f"     {r['sku_a']} <-> {r['sku_b']}: {r['n_pedidos_juntos']} juntos, lift={r['lift']:.1f}, conf={r['confidence_a_to_b']*100:.0f}%")


def main():
    print(f"=== Elasticidad + Market Basket — {datetime.now()} ===\n", flush=True)
    if PRICING_HIST.exists():
        calcular_elasticidad()
    else:
        print("[skip] elasticidad: no hay pricing_historico", flush=True)

    if URL and TOKEN:
        calcular_market_basket()
    else:
        print("[skip] market_basket: sin credenciales Turso", flush=True)

    print("\n[OK] Elasticidad + Basket generados")


if __name__ == '__main__':
    main()
