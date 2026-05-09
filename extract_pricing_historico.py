#!/usr/bin/env python3
"""
Pricing historico por SKU x canal x dia.

Como las listas de precio Odoo estan alteradas (memoria),
calculamos precio_lista_estimado desde el histórico real de ventas.

Genera:
- data/pricing_historico/pricing_diario.parquet
  columnas: fecha, sku, canal, precio_promedio_dia, precio_lista_estimado,
            descuento_efectivo, promo_activa
- data/pricing_historico/metadata.json

Formula:
  precio_dia = venta_bruta / cantidad (por SKU, canal, dia)
  precio_lista = percentil 90 movil 60 dias del precio_dia
  descuento_efectivo = max(0, 1 - precio_dia / precio_lista)
  promo_activa = descuento_efectivo > 0.10 por >= 3 dias consecutivos
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / 'data' / 'pricing_historico'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')
HIST_PARQUET = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'

if not URL or not TOKEN:
    print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no seteados", flush=True)
    sys.exit(1)

HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}


def _q(sql: str):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    r = requests.post(f"{URL}/v2/pipeline", json=body, headers=HEADERS, timeout=300)
    r.raise_for_status()
    res = r.json()['results'][0]
    if res.get('type') == 'error':
        raise RuntimeError(res['error']['message'])
    return res['response']['result']['rows']


def _val(row, idx):
    cell = row[idx]
    return None if cell.get('type') == 'null' else cell.get('value')


def cargar_ventas() -> pd.DataFrame:
    """Combina parquet historico (pre-abril) + Turso (april+) ya agregado por sku-canal-dia."""
    print("[1] Cargando ventas agregadas (sku x canal x dia)...", flush=True)

    df_hist = pd.DataFrame()
    if HIST_PARQUET.exists():
        df_h = pd.read_parquet(HIST_PARQUET, columns=['fecha_venta', 'sku', 'canal',
                                                        'venta_bruta', 'cantidad', 'tipo_movimiento'])
        df_h = df_h[df_h['tipo_movimiento'] == 'Venta'].copy()
        df_h['fecha_venta'] = pd.to_datetime(df_h['fecha_venta'], errors='coerce')
        df_h = df_h.dropna(subset=['fecha_venta'])
        # Agregar a nivel sku x canal x dia
        df_h['fecha'] = df_h['fecha_venta'].dt.date
        df_hist = df_h.groupby(['fecha', 'sku', 'canal'], as_index=False).agg(
            venta_bruta=('venta_bruta', 'sum'),
            cantidad=('cantidad', 'sum'),
        )
        df_hist['fecha_venta'] = pd.to_datetime(df_hist['fecha'])
        df_hist = df_hist[['fecha_venta', 'sku', 'canal', 'venta_bruta', 'cantidad']]
        print(f"   Parquet (agregado): {len(df_hist):,} (sku, canal, dia)", flush=True)

    # Query Turso ya agregada (mucho menos volumen que fila por fila)
    print("   Turso live (april+, agregado en SQL)...", flush=True)
    rows = _q("""
        SELECT fecha_venta, sku, canal,
               SUM(venta_bruta), SUM(cantidad)
        FROM ventas
        WHERE fecha_venta >= '2026-04-01' AND tipo_movimiento = 'Venta'
        GROUP BY fecha_venta, sku, canal
    """)
    df_live = pd.DataFrame([{
        'fecha_venta': pd.to_datetime(_val(r, 0)),
        'sku': _val(r, 1),
        'canal': _val(r, 2),
        'venta_bruta': float(_val(r, 3) or 0),
        'cantidad': float(_val(r, 4) or 0),
    } for r in rows])
    print(f"   Turso: {len(df_live):,} (sku, canal, dia)", flush=True)

    df = pd.concat([df_hist, df_live], ignore_index=True) if not df_hist.empty else df_live
    df = df[(df['cantidad'] > 0) & (df['venta_bruta'] > 0)]
    return df


def calcular_pricing(df: pd.DataFrame) -> pd.DataFrame:
    """Para cada (sku, canal, dia): precio promedio + lista estimada + descuento + promo."""
    print("[2] Calculando precio diario por (sku, canal)...", flush=True)
    # Precio diario (promedio ponderado por cantidad)
    df = df.copy()
    df['fecha'] = df['fecha_venta'].dt.date
    grp = df.groupby(['fecha', 'sku', 'canal'], as_index=False).agg(
        venta_bruta=('venta_bruta', 'sum'),
        cantidad=('cantidad', 'sum'),
    )
    grp['precio_promedio_dia'] = grp['venta_bruta'] / grp['cantidad']
    grp['fecha'] = pd.to_datetime(grp['fecha'])
    print(f"   {len(grp):,} (sku, canal, dia) con venta", flush=True)

    print("[3] Calculando precio_lista_estimado (percentil 90 movil 60d por sku x canal)...", flush=True)
    # Para cada (sku, canal): rolling P90 sobre 60 dias.
    # Mejor: agrupar por (sku, canal), ordenar por fecha y calcular rolling con quantile.
    grp = grp.sort_values(['sku', 'canal', 'fecha']).reset_index(drop=True)

    def _p90_movil(serie):
        # rolling 60d con percentil 90 (precio lista estimado)
        return serie.rolling(window=60, min_periods=5).quantile(0.90)

    grp['precio_lista_estimado'] = (
        grp.groupby(['sku', 'canal'])['precio_promedio_dia']
        .transform(_p90_movil)
    )
    # Si ventana inicial sin suficientes datos: usar max histórico hasta el momento
    grp['precio_lista_estimado'] = grp['precio_lista_estimado'].fillna(
        grp.groupby(['sku', 'canal'])['precio_promedio_dia'].cummax()
    )

    grp['descuento_efectivo'] = (
        1 - (grp['precio_promedio_dia'] / grp['precio_lista_estimado'])
    ).clip(lower=0).fillna(0)

    print("[4] Detectando promo_activa (descuento>10% por >=3 dias seguidos)...", flush=True)
    grp['promo_dia'] = (grp['descuento_efectivo'] > 0.10).astype(int)
    # Streak: en cada (sku, canal), contar dias consecutivos con promo_dia=1
    def _streak(s):
        # Devuelve la longitud de la racha actual de 1's
        groups = (s != s.shift()).cumsum()
        return s.groupby(groups).cumsum()

    grp['promo_streak'] = grp.groupby(['sku', 'canal'])['promo_dia'].transform(_streak)
    grp['promo_activa'] = (grp['promo_streak'] >= 3).astype(int)
    grp = grp.drop(columns=['promo_dia', 'promo_streak'])

    return grp


def main():
    print(f"=== Pricing historico — {datetime.now()} ===\n", flush=True)
    df = cargar_ventas()
    if df.empty:
        print("[ERROR] Sin ventas")
        sys.exit(1)
    pricing = calcular_pricing(df)

    print(f"\n[5] Guardando parquet...", flush=True)
    pricing['fecha'] = pd.to_datetime(pricing['fecha'])
    pricing['precio_promedio_dia'] = pricing['precio_promedio_dia'].astype('float32')
    pricing['precio_lista_estimado'] = pricing['precio_lista_estimado'].astype('float32')
    pricing['descuento_efectivo'] = pricing['descuento_efectivo'].astype('float32')
    pricing['cantidad'] = pricing['cantidad'].astype('float32')
    pricing['venta_bruta'] = pricing['venta_bruta'].astype('float32')
    pricing['promo_activa'] = pricing['promo_activa'].astype('int8')
    pricing['canal'] = pricing['canal'].astype('category')

    out = OUTPUT_DIR / 'pricing_diario.parquet'
    pricing.to_parquet(out, compression='zstd', compression_level=9, index=False)
    print(f"   {out}: {len(pricing):,} filas, {out.stat().st_size/1024/1024:.1f} MB", flush=True)

    meta = {
        'generado_en': datetime.now().isoformat(),
        'total_filas': len(pricing),
        'total_skus': pricing['sku'].nunique(),
        'total_canales': pricing['canal'].nunique(),
        'rango': [str(pricing['fecha'].min().date()), str(pricing['fecha'].max().date())],
        'promo_activa_pct': float((pricing['promo_activa'].sum() / len(pricing)) * 100),
        'desc_promedio_promo': float(pricing.loc[pricing['promo_activa'] == 1, 'descuento_efectivo'].mean() or 0),
    }
    with open(OUTPUT_DIR / 'metadata.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, default=str)

    print(f"\n[OK] Pricing historico generado")
    print(f"  SKUs: {meta['total_skus']:,} | Canales: {meta['total_canales']}")
    print(f"  Rango: {meta['rango'][0]} a {meta['rango'][1]}")
    print(f"  Promo activa: {meta['promo_activa_pct']:.1f}% de los registros")
    print(f"  Descuento promedio en promo: {meta['desc_promedio_promo']*100:.1f}%")


if __name__ == '__main__':
    main()
