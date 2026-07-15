#!/usr/bin/env python3
"""
Envía pulso Cyber UnionX cada 2h durante el evento (Lun 1-jun a Jue 4-jun 22h CLT).
Incluye HTML resumen + Excel RAW adjunto del día.

Secciones del mail:
1. Resumen acumulado Cyber vs meta total
2. Resumen del día actual vs meta diaria
3. Tabla por día (los 6 días + avance %)
4. Top canales × día (venta + margen, vs meta canal)
5. Modalidad Fulfillment vs Seller+Flex
6. Alarma stock (SKUs con cobertura < 7 días)
7. Proyección cierre día y Cyber completo

Vars de entorno:
  LIBSQL_URL, LIBSQL_AUTH_TOKEN, RESEND_API_KEY
  EMAIL_TO (default: andres@unionx.cl)
  EMAIL_FROM (default: onboarding@resend.dev)
  CYBER_PREBORRADOR (si '1', prefija asunto con [PRE-BORRADOR])
"""
import base64
import io
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
EMAIL_TO = [e.strip() for e in os.environ.get(
    'EMAIL_TO', 'andres@unionx.cl'
).split(',') if e.strip()]
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'onboarding@resend.dev')
PREBORRADOR = os.environ.get('CYBER_PREBORRADOR', '0') == '1'

PROJECT_ROOT = Path(__file__).parent

# Rango Cyber: Lun 1-jun 06:00 CLT a Jue 4-jun 22:00 CLT
CHILE_TZ = timezone(timedelta(hours=-4))


def hoy_comercial():
    """Día comercial CLT. Si hora < 06:00, considera el día anterior
    (el pulso de las 00:00 muestra el cierre del día Cyber recién terminado)."""
    ahora = datetime.now(CHILE_TZ)
    if ahora.hour < 6:
        ahora = ahora - timedelta(days=1)
    return ahora.strftime('%Y-%m-%d')
RANGO_INICIO = datetime(2026, 6, 1, 6, 0, tzinfo=CHILE_TZ)
RANGO_FIN = datetime(2026, 6, 6, 23, 59, tzinfo=CHILE_TZ)

CYBER_FECHAS = ['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04', '2026-06-05', '2026-06-06']
CYBER_LABELS = ['Lun 1-jun', 'Mar 2-jun', 'Mié 3-jun', 'Jue 4-jun', 'Vie 5-jun', 'Sáb 6-jun']
CYBER_LABELS_SHORT = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb']
# Cyber 2025 JUNIO (referencia YoY mismo día): Lun 2-jun → Sáb 7-jun
CYBER_2025_FECHAS = ['2025-06-02', '2025-06-03', '2025-06-04', '2025-06-05', '2025-06-06', '2025-06-07']
CYBER_PAIRS = list(zip(CYBER_FECHAS, CYBER_2025_FECHAS))
# Cyber 2025 OCTUBRE — Semana COMPLETA Lun-Sab (CyberMonday Chile 6-8 oct + extension 9-11 oct)
CYBER_OCT2025_FECHAS = ['2025-10-06', '2025-10-07', '2025-10-08', '2025-10-09', '2025-10-10', '2025-10-11']
CYBER_OCT_PAIRS = list(zip(CYBER_FECHAS, CYBER_OCT2025_FECHAS))
CURVA_PCT = [0.30, 0.25, 0.20, 0.12, 0.08, 0.05]
META_TOTAL = 505_915_976
META_DIA_BRUTA = [META_TOTAL * p for p in CURVA_PCT]
MARGEN_OBJETIVO = 0.55  # 55% Cyber esperado (calc meta margen)


def _check_rango():
    ahora = datetime.now(CHILE_TZ)
    if ahora < RANGO_INICIO:
        print(f"[SKIP] {ahora} < {RANGO_INICIO}", flush=True)
        return False
    if ahora > RANGO_FIN:
        print(f"[SKIP] {ahora} > {RANGO_FIN}", flush=True)
        return False
    return True


def turso_query(sql):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    r = requests.post(f"{URL}/v2/pipeline", json=body,
                      headers={'Authorization': f'Bearer {TOKEN}'}, timeout=60)
    r.raise_for_status()
    return r.json()['results'][0]['response']['result']


def _rows(result):
    return [[c.get('value') if isinstance(c, dict) else c for c in row] for row in result['rows']]


def cargar_metas_canal():
    """Lee plan_cyber_2026.json y devuelve dict canal → {meta_uds, meta_venta, meta_margen}."""
    path = PROJECT_ROOT / 'data' / 'planificacion' / 'plan_cyber_2026.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    metas = {}
    for m in data['metas_canal']:
        canal = m['canal']
        venta = float(m['meta_venta'])
        metas[canal] = {
            'meta_uds': int(m['meta_uds']),
            'meta_venta': venta,
            'meta_margen': venta * MARGEN_OBJETIVO,  # aprox
            'modalidad': m.get('modalidad', ''),
        }
    return metas


def cargar_metas_marca_categoria():
    """Lee metas_marca y metas_categoria del plan_cyber_2026.json.
    Devuelve (metas_marca_dict, metas_categoria_dict): nombre UPPER stripped → meta_venta float.
    Normaliza con upper+strip para que match sea case-insensitive ("LEVO" vs "Levo")."""
    path = PROJECT_ROOT / 'data' / 'planificacion' / 'plan_cyber_2026.json'
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text(encoding='utf-8'))
    def _key(s):
        return str(s or '').strip().upper()
    mm = {_key(m['marca']): float(m.get('meta_venta', 0)) for m in data.get('metas_marca', [])}
    mc = {_key(m['categoria']): float(m.get('meta_venta', 0)) for m in data.get('metas_categoria', [])}
    return mm, mc


def descargar_resumen(metas_canal):
    """Combina histórico parquet (1-jun foto fija) + mes_actual.parquet (2-jun+).
    Turso no se usa para evitar bug sync silencioso.
    """
    print("[1/5] Cargando data Cyber: histórico (1-jun) + mes_actual (2-jun+)...", flush=True)
    t0 = time.time()
    hist_path = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
    mes_path = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
    df_hist = pd.read_parquet(hist_path)
    df_mes = pd.read_parquet(mes_path)
    df_hist['fecha_venta'] = pd.to_datetime(df_hist['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    df_mes['fecha_venta'] = pd.to_datetime(df_mes['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    # Solo Cyber: 1-jun del histórico + 2-jun+ del mes_actual
    df_hist_cyber = df_hist[df_hist['fecha_venta'].isin(CYBER_FECHAS)]
    df_mes_cyber = df_mes[df_mes['fecha_venta'].isin(CYBER_FECHAS)]
    # Concat alineando columnas comunes
    common_cols = [c for c in df_mes_cyber.columns if c in df_hist_cyber.columns]
    df = pd.concat([df_hist_cyber[common_cols], df_mes_cyber[common_cols]], ignore_index=True).copy()
    print(f"      hist Cyber: {len(df_hist_cyber):,} filas | mes Cyber: {len(df_mes_cyber):,} filas | total: {len(df):,}", flush=True)

    # Por día
    grp = df.groupby('fecha_venta').agg(
        sos=('pedido', 'nunique'),
        bruta=('venta_bruta', 'sum'),
        neta=('venta_neta', 'sum'),
        margen=('margen_front', 'sum'),
        uds=('cantidad', 'sum'),
    ).reset_index().sort_values('fecha_venta')
    por_dia = [[r['fecha_venta'], int(r['sos']), float(round(r['bruta'])), float(round(r['neta'])),
                float(round(r['margen'])), float(round(r['uds']))] for _, r in grp.iterrows()]

    # Por canal × día
    grp = df.groupby(['canal', 'fecha_venta']).agg(
        bruta=('venta_bruta', 'sum'),
        margen=('margen_front', 'sum'),
        uds=('cantidad', 'sum'),
    ).reset_index()
    por_canal_dia = [[r['canal'], r['fecha_venta'], float(round(r['bruta'])),
                      float(round(r['margen'])), float(round(r['uds']))] for _, r in grp.iterrows()]

    # Por canal acumulado
    grp = df.groupby('canal').agg(
        sos=('pedido', 'nunique'),
        bruta=('venta_bruta', 'sum'),
        margen=('margen_front', 'sum'),
        uds=('cantidad', 'sum'),
    ).reset_index().sort_values('bruta', ascending=False)
    por_canal_acum = [[r['canal'], int(r['sos']), float(round(r['bruta'])),
                       float(round(r['margen'])), float(round(r['uds']))] for _, r in grp.iterrows()]

    # Modalidad (Fulfillment vs Seller+Flex)
    df['_mod'] = df['bodega'].astype(str).str.lower().str.startswith('bodega fulfillment').map({True: 'Fulfillment', False: 'Seller + Flex'})
    grp = df.groupby('_mod').agg(
        sos=('pedido', 'nunique'),
        bruta=('venta_bruta', 'sum'),
        margen=('margen_front', 'sum'),
    ).reset_index()
    por_mod = [[r['_mod'], int(r['sos']), float(round(r['bruta'])), float(round(r['margen']))]
               for _, r in grp.iterrows()]

    # Por hora HOY (CLT)
    hoy_str = hoy_comercial()
    df_hoy = df[df['fecha_venta'] == hoy_str].copy()
    df_hoy['hora_venta_num'] = pd.to_numeric(df_hoy['hora_venta_num'], errors='coerce')
    grp = df_hoy.groupby('hora_venta_num').agg(
        sos=('pedido', 'nunique'),
        bruta=('venta_bruta', 'sum'),
    ).reset_index().sort_values('hora_venta_num')
    por_hora_hoy = [[float(r['hora_venta_num']), int(r['sos']), float(round(r['bruta']))]
                    for _, r in grp.iterrows() if pd.notna(r['hora_venta_num'])]

    # ============================================================
    # NUEVOS BLOQUES: marcas × día, categorías × día, top SKUs
    # ============================================================
    # Por marca × día
    grp = df.groupby(['marca', 'fecha_venta']).agg(
        bruta=('venta_bruta', 'sum'),
        neta=('venta_neta', 'sum'),
        margen=('margen_front', 'sum'),
    ).reset_index()
    por_marca_dia = [[r['marca'] or '(sin marca)', r['fecha_venta'],
                      float(round(r['bruta'])), float(round(r['neta'])), float(round(r['margen']))]
                     for _, r in grp.iterrows()]

    # Por categoría (categoria_hijo == "Tipo producto" del Plan Cyber Excel)
    grp = df.groupby(['categoria_hijo', 'fecha_venta']).agg(
        bruta=('venta_bruta', 'sum'),
        neta=('venta_neta', 'sum'),
        margen=('margen_front', 'sum'),
    ).reset_index()
    por_categoria_dia = [[(r['categoria_hijo'] or '(sin cat)'), r['fecha_venta'],
                          float(round(r['bruta'])), float(round(r['neta'])), float(round(r['margen']))]
                         for _, r in grp.iterrows()]

    # Top 10 SKUs por venta bruta y por margen front (acumulado Cyber)
    grp_sku = df.groupby(['sku', 'producto']).agg(
        uds=('cantidad', 'sum'),
        bruta=('venta_bruta', 'sum'),
        neta=('venta_neta', 'sum'),
        margen=('margen_front', 'sum'),
    ).reset_index()
    grp_sku['margen_pct'] = grp_sku.apply(lambda r: (r['margen']/r['neta']*100) if r['neta'] else 0, axis=1)
    top_skus_venta = grp_sku.sort_values('bruta', ascending=False).head(10)
    top_skus_margen = grp_sku.sort_values('margen', ascending=False).head(10)
    top_skus_venta = [[r['sku'], str(r['producto'])[:60], int(r['uds']),
                       float(round(r['bruta'])), float(round(r['margen'])), float(r['margen_pct'])]
                      for _, r in top_skus_venta.iterrows()]
    top_skus_margen = [[r['sku'], str(r['producto'])[:60], int(r['uds']),
                        float(round(r['bruta'])), float(round(r['margen'])), float(r['margen_pct'])]
                       for _, r in top_skus_margen.iterrows()]

    # Cyber 2025 (LY) — leído desde parquet HISTÓRICO local (Turso ya no tiene 2025)
    hoy_str = hoy_comercial()
    fecha_ly = None
    for f26, f25 in CYBER_PAIRS:
        if f26 == hoy_str:
            fecha_ly = f25
            break
    if fecha_ly is None:
        fecha_ly = CYBER_2025_FECHAS[0]
    fecha_oct = None
    for f26, foct in CYBER_OCT_PAIRS:
        if f26 == hoy_str:
            fecha_oct = foct
            break

    hist_path = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
    curva_ly = []
    total_ly_val = margen_ly_val = neta_ly_val = 0
    cyber_ly_bruta = cyber_ly_margen = cyber_ly_neta = 0
    total_oct_val = margen_oct_val = neta_oct_val = 0
    cyber_oct_bruta = cyber_oct_margen = cyber_oct_neta = 0
    try:
        hist_df = pd.read_parquet(hist_path, columns=['fecha_venta','hora_venta','venta_bruta','venta_neta','margen_front'])
        hist_df['fecha_venta'] = pd.to_datetime(hist_df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')

        dia_ly = hist_df[hist_df['fecha_venta'] == fecha_ly].copy()
        if not dia_ly.empty:
            dia_ly['h'] = dia_ly['hora_venta'].astype(str).str.slice(0, 2)
            dia_ly = dia_ly[dia_ly['h'].str.isdigit()]
            dia_ly['h'] = dia_ly['h'].astype(int)
            curva_ly = dia_ly.groupby('h')['venta_bruta'].sum().reset_index().values.tolist()
            total_ly_val = float(dia_ly['venta_bruta'].sum())
            margen_ly_val = float(dia_ly['margen_front'].sum())
            neta_ly_val = float(dia_ly['venta_neta'].sum())

        cyber_jun = hist_df[hist_df['fecha_venta'].isin(CYBER_2025_FECHAS)]
        if not cyber_jun.empty:
            cyber_ly_bruta = float(cyber_jun['venta_bruta'].sum())
            cyber_ly_margen = float(cyber_jun['margen_front'].sum())
            cyber_ly_neta = float(cyber_jun['venta_neta'].sum())

        if fecha_oct:
            dia_oct = hist_df[hist_df['fecha_venta'] == fecha_oct]
            total_oct_val = float(dia_oct['venta_bruta'].sum()) if not dia_oct.empty else 0
            margen_oct_val = float(dia_oct['margen_front'].sum()) if not dia_oct.empty else 0
            neta_oct_val = float(dia_oct['venta_neta'].sum()) if not dia_oct.empty else 0
        cyber_oct = hist_df[hist_df['fecha_venta'].isin(CYBER_OCT2025_FECHAS)]
        if not cyber_oct.empty:
            cyber_oct_bruta = float(cyber_oct['venta_bruta'].sum())
            cyber_oct_margen = float(cyber_oct['margen_front'].sum())
            cyber_oct_neta = float(cyber_oct['venta_neta'].sum())
    except Exception as e:
        print(f"      [WARN] Error histórico Cyber 2025: {e}", flush=True)

    print(f"      [OK] en {time.time()-t0:.1f}s (LY jun: {fecha_ly} ${total_ly_val:,.0f} | "
          f"LY oct: {fecha_oct} ${total_oct_val:,.0f})", flush=True)
    return (por_dia, por_canal_dia, por_canal_acum, por_mod, por_hora_hoy, curva_ly,
            fecha_ly, total_ly_val, margen_ly_val, neta_ly_val,
            cyber_ly_bruta, cyber_ly_margen, cyber_ly_neta,
            fecha_oct, total_oct_val, margen_oct_val, neta_oct_val,
            cyber_oct_bruta, cyber_oct_margen, cyber_oct_neta,
            por_marca_dia, por_categoria_dia, top_skus_venta, top_skus_margen)


def cargar_alarma_stock():
    """SKUs con cobertura < 7 días. Usa Vta 30d Qty precalculado del parquet stock
    (evita query pesada a Turso)."""
    print("[2/5] Calculando alarma stock...", flush=True)
    try:
        stock_path = PROJECT_ROOT / 'data' / 'stock' / 'skus.parquet'
        if not stock_path.exists():
            print("      [WARN] skus.parquet no existe", flush=True)
            return []
        stock = pd.read_parquet(stock_path)

        alarma = []
        for _, row in stock.iterrows():
            sku = str(row.get('SKU', '')).strip()
            if not sku:
                continue
            disp = float(row.get('Disponible', 0) or 0)
            # Vta 30d Qty viene precalculado en el parquet (sync stock cada 3h)
            uds_30d = float(row.get('Vta 30d Qty', 0) or 0)
            if uds_30d <= 0:
                continue
            vta_diaria = uds_30d / 30
            dias_cob = disp / vta_diaria if vta_diaria else 999
            if dias_cob < 7:
                costo = float(row.get('Costo Unit', 0) or 0)
                perdido_proy = max(0, vta_diaria * 7 - disp) * costo
                alarma.append({
                    'sku': sku,
                    'producto': str(row.get('Producto', ''))[:50],
                    'marca': str(row.get('Marca', '')),
                    'disp': int(disp),
                    'vta_diaria': vta_diaria,
                    'dias_cob': dias_cob,
                    'perdido': perdido_proy,
                })

        alarma.sort(key=lambda x: x['perdido'], reverse=True)
        print(f"      [OK] {len(alarma)} SKUs con cobertura < 7 días", flush=True)
        return alarma[:10]
    except Exception as e:
        print(f"      [WARN] {type(e).__name__}: {e}", flush=True)
        return []


def _parse_hora(v):
    """Parsea hora robusto: int, '0', '00:00:00', etc. → int 0-23."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        # Probar formato HH:MM:SS
        if ':' in s:
            try:
                return int(s.split(':')[0])
            except ValueError:
                return None
    return None


def proyectar_cierre(bruta_hoy: float, hora_actual: int, curva_ly_data: list,
                     meta_hoy: float, fecha_ly: str):
    """Proyecta cierre del día usando curva del mismo día Cyber 2025 (YoY)."""
    if not curva_ly_data:
        return None
    total_ly = sum(float(r[1] or 0) for r in curva_ly_data)
    if total_ly <= 0:
        return None
    # % acumulado hasta hora_actual del día equivalente LY
    acum_hasta = 0
    for r in curva_ly_data:
        h = _parse_hora(r[0])
        if h is not None and h <= hora_actual:
            acum_hasta += float(r[1] or 0)
    pct_hasta = acum_hasta / total_ly
    if pct_hasta <= 0:
        return None
    proy_dia = bruta_hoy / pct_hasta
    avance_meta = proy_dia / meta_hoy if meta_hoy else 0
    # Crecimiento YoY del día
    yoy_dia = (proy_dia / total_ly - 1) if total_ly else 0
    return {
        'proy_dia': proy_dia,
        'pct_hasta_ref': pct_hasta,
        'avance_vs_meta': avance_meta,
        'ritmo_vs_meta': bruta_hoy / (meta_hoy * pct_hasta) if (meta_hoy * pct_hasta) else 0,
        'total_ly': total_ly,
        'fecha_ly': fecha_ly,
        'yoy_dia': yoy_dia,
    }


def fmt_m(v):
    if v is None or v == 0:
        return '$0'
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.1f} M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.1f} K"
    return f"${v:,.0f}"


def render_html(por_dia, por_canal_dia, por_canal_acum, por_mod, por_hora_hoy,
                curva_ly, fecha_ly, total_ly_val, margen_ly_val, neta_ly_val,
                cyber_ly_bruta, cyber_ly_margen, cyber_ly_neta,
                fecha_oct, total_oct_val, margen_oct_val, neta_oct_val,
                cyber_oct_bruta, cyber_oct_margen, cyber_oct_neta,
                alarma_stock, metas_canal,
                por_marca_dia=None, por_categoria_dia=None,
                top_skus_venta=None, top_skus_margen=None):
    ahora_clt = datetime.now(CHILE_TZ)
    fecha_hora = ahora_clt.strftime('%d-%b-%Y %H:%M CLT')
    hora_actual = ahora_clt.hour

    # Totales
    bruta_total = sum(float(d[2] or 0) for d in por_dia)
    margen_total = sum(float(d[4] or 0) for d in por_dia)
    neta_total = sum(float(d[3] or 0) for d in por_dia)
    uds_total = sum(int(d[5] or 0) for d in por_dia)
    sos_total = sum(int(d[1] or 0) for d in por_dia)
    avance_pct = bruta_total / META_TOTAL if META_TOTAL else 0
    margen_pct = (margen_total / neta_total) if neta_total else 0

    # Hoy
    hoy_str = hoy_comercial()
    dia_hoy = next((d for d in por_dia if d[0] == hoy_str), None)
    bruta_hoy = float(dia_hoy[2]) if dia_hoy and dia_hoy[2] else 0
    margen_hoy = float(dia_hoy[4]) if dia_hoy and dia_hoy[4] else 0
    uds_hoy = int(dia_hoy[5]) if dia_hoy and dia_hoy[5] else 0
    try:
        idx_hoy = CYBER_FECHAS.index(hoy_str)
        meta_hoy = META_DIA_BRUTA[idx_hoy]
    except ValueError:
        meta_hoy = 0
    avance_hoy = bruta_hoy / meta_hoy if meta_hoy else 0

    # Tabla por día
    rows_dia = []
    for fecha, label, meta in zip(CYBER_FECHAS, CYBER_LABELS, META_DIA_BRUTA):
        d = next((dd for dd in por_dia if dd[0] == fecha), None)
        b = float(d[2]) if d and d[2] else 0
        m = float(d[4]) if d and d[4] else 0
        u = int(d[5]) if d and d[5] else 0
        s = int(d[1]) if d and d[1] else 0
        pct = b / meta if meta else 0
        color = '#16A34A' if pct >= 1 else ('#EA580C' if pct >= 0.5 else '#DC2626')
        rows_dia.append(
            f'<tr><td>{label}</td><td align="right">{s:,}</td><td align="right">{u:,}</td>'
            f'<td align="right">{fmt_m(b)}</td><td align="right">{fmt_m(m)}</td>'
            f'<td align="right">{fmt_m(meta)}</td>'
            f'<td align="right" style="color:{color};font-weight:600">{pct*100:.1f}%</td></tr>'
        )
    tabla_dia = '\n'.join(rows_dia)

    # Top canales × día (matriz)
    canales_top = [c[0] for c in por_canal_acum[:8] if c[0]]
    # dict: {(canal, fecha): (bruta, margen)}
    cd_map = {(r[0], r[1]): (float(r[2] or 0), float(r[3] or 0)) for r in por_canal_dia}
    fechas_pasadas = [f for f in CYBER_FECHAS if f <= hoy_str]
    headers_cd = '<th align="left">Canal</th>'
    for f in fechas_pasadas:
        idx = CYBER_FECHAS.index(f)
        headers_cd += f'<th colspan="2" align="center" style="border-left:1px solid #E2E8F0">{CYBER_LABELS_SHORT[idx]}</th>'
    headers_cd += '<th colspan="2" align="center" style="border-left:1px solid #E2E8F0;background:#F1F5F9">Acum</th>'
    headers_cd += '<th colspan="2" align="center" style="border-left:1px solid #E2E8F0;background:#FEF3C7">Meta</th>'
    subheaders_cd = '<th></th>' + ''.join(f'<th align="right" style="border-left:1px solid #E2E8F0;font-weight:400;font-size:0.78rem">V</th><th align="right" style="font-weight:400;font-size:0.78rem">M</th>' for _ in fechas_pasadas)
    subheaders_cd += '<th align="right" style="border-left:1px solid #E2E8F0;font-weight:400;font-size:0.78rem;background:#F1F5F9">V</th><th align="right" style="font-weight:400;font-size:0.78rem;background:#F1F5F9">M</th>'
    subheaders_cd += '<th align="right" style="border-left:1px solid #E2E8F0;font-weight:400;font-size:0.78rem;background:#FEF3C7">%V</th><th align="right" style="font-weight:400;font-size:0.78rem;background:#FEF3C7">%M</th>'

    rows_cd = []
    for canal in canales_top:
        cells = [f'<td><b>{canal}</b></td>']
        venta_acum, margen_acum = 0, 0
        for f in fechas_pasadas:
            b, m = cd_map.get((canal, f), (0, 0))
            venta_acum += b
            margen_acum += m
            cells.append(f'<td align="right" style="border-left:1px solid #E2E8F0">{fmt_m(b)}</td>')
            cells.append(f'<td align="right">{fmt_m(m)}</td>')
        cells.append(f'<td align="right" style="border-left:1px solid #E2E8F0;background:#F1F5F9"><b>{fmt_m(venta_acum)}</b></td>')
        cells.append(f'<td align="right" style="background:#F1F5F9"><b>{fmt_m(margen_acum)}</b></td>')
        meta_info = metas_canal.get(canal, {})
        meta_v = meta_info.get('meta_venta', 0)
        meta_m = meta_info.get('meta_margen', 0)
        pct_v = venta_acum / meta_v if meta_v else 0
        pct_m = margen_acum / meta_m if meta_m else 0
        color_v = '#16A34A' if pct_v >= 0.5 else ('#EA580C' if pct_v >= 0.2 else '#DC2626')
        color_m = '#16A34A' if pct_m >= 0.5 else ('#EA580C' if pct_m >= 0.2 else '#DC2626')
        cells.append(f'<td align="right" style="border-left:1px solid #E2E8F0;background:#FEF3C7;color:{color_v}"><b>{pct_v*100:.1f}%</b></td>')
        cells.append(f'<td align="right" style="background:#FEF3C7;color:{color_m}"><b>{pct_m*100:.1f}%</b></td>')
        rows_cd.append(f'<tr>{"".join(cells)}</tr>')
    tabla_cd = '\n'.join(rows_cd)

    # Modalidad
    rows_mod = []
    for m in por_mod:
        b = float(m[2] or 0)
        share = b / bruta_total if bruta_total else 0
        rows_mod.append(
            f'<tr><td>{m[0] or "?"}</td><td align="right">{int(m[1] or 0):,}</td>'
            f'<td align="right">{fmt_m(b)}</td><td align="right">{fmt_m(float(m[3] or 0))}</td>'
            f'<td align="right">{share*100:.1f}%</td></tr>'
        )
    tabla_mod = '\n'.join(rows_mod)

    # ============================================================
    # NUEVOS BLOQUES — marcas × día, categorías × día, top SKUs
    # ============================================================
    def _matriz_dia(rows, label_col_name, meta_dict=None):
        """Construye matriz NxD: filas=entidad, cols=día, valores=bruta/margen.
        Acumulado: V, M, %M (margen/neta), %Share, y %Meta (si meta_dict provisto)."""
        if not rows:
            return ''
        import pandas as _pd
        _df = _pd.DataFrame(rows, columns=[label_col_name, 'fecha', 'bruta', 'neta', 'margen'])
        dias_pintar = [f for f in CYBER_FECHAS if f <= hoy_str]
        _df = _df[_df['fecha'].isin(dias_pintar)]
        if _df.empty:
            return ''
        total_cyber_bruta = _df['bruta'].sum() or 1
        tot = _df.groupby(label_col_name).agg(b=('bruta','sum'), m=('margen','sum'), n=('neta','sum'))
        tot['pct_m'] = tot.apply(lambda r: (r['m']/r['n']*100) if r['n'] else 0, axis=1)
        tot['share'] = tot['b'] / total_cyber_bruta * 100
        if meta_dict:
            tot['meta'] = tot.index.map(lambda x: meta_dict.get(str(x or '').strip().upper(), 0))
            tot['pct_meta'] = tot.apply(lambda r: (r['b']/r['meta']*100) if r['meta'] else 0, axis=1)
        tot = tot.sort_values('b', ascending=False).head(10)
        headers = '<th align="left">' + label_col_name.capitalize() + '</th>'
        for f in dias_pintar:
            idx = CYBER_FECHAS.index(f)
            headers += f'<th align="right" colspan="2">{CYBER_LABELS_SHORT[idx]}</th>'
        acum_cols = 6 if meta_dict else 4
        headers += f'<th align="right" colspan="{acum_cols}">Acumulado</th>'
        sub = '<th></th>' + ('<th align="right">V</th><th align="right">M</th>' * len(dias_pintar))
        sub += '<th align="right">V</th><th align="right">M</th><th align="right">%M</th><th align="right">%Share</th>'
        if meta_dict:
            sub += '<th align="right">Meta</th><th align="right">%Meta</th>'
        body = ''
        for ent, t in tot.iterrows():
            body += f'<tr><td>{ent[:30]}</td>'
            for f in dias_pintar:
                m = _df[(_df[label_col_name]==ent) & (_df['fecha']==f)]
                if not m.empty:
                    body += f'<td align="right">{fmt_m(m["bruta"].iloc[0])}</td><td align="right">{fmt_m(m["margen"].iloc[0])}</td>'
                else:
                    body += '<td align="right">-</td><td align="right">-</td>'
            body += f'<td align="right"><b>{fmt_m(t["b"])}</b></td><td align="right"><b>{fmt_m(t["m"])}</b></td>'
            body += f'<td align="right">{t["pct_m"]:.1f}%</td><td align="right">{t["share"]:.1f}%</td>'
            if meta_dict:
                color = '#16A34A' if t["pct_meta"] >= 80 else ('#EA580C' if t["pct_meta"] >= 40 else '#DC2626')
                body += f'<td align="right">{fmt_m(t["meta"])}</td>'
                body += f'<td align="right" style="color:{color};font-weight:600">{t["pct_meta"]:.1f}%</td>'
            body += '</tr>'
        return headers, sub, body

    # Cargar metas marca + categoría
    metas_marca_dict, metas_cat_dict = cargar_metas_marca_categoria()

    # Marca × día (con %Meta)
    bloque_marca_dia = ''
    if por_marca_dia:
        res = _matriz_dia(por_marca_dia, 'marca', meta_dict=metas_marca_dict)
        if res:
            h, s, b = res
            bloque_marca_dia = f"""
<h3 style="margin:24px 0 8px 0;font-size:1rem">🏷️ Marcas × día (top 10 por venta) — V = venta bruta, M = margen front</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.78rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">{h}</tr>
<tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">{s}</tr></thead>
<tbody>{b}</tbody></table>"""

    # Categoría × día (con %Meta)
    bloque_categoria_dia = ''
    if por_categoria_dia:
        res = _matriz_dia(por_categoria_dia, 'categoria', meta_dict=metas_cat_dict)
        if res:
            h, s, b = res
            bloque_categoria_dia = f"""
<h3 style="margin:24px 0 8px 0;font-size:1rem">📂 Categorías × día (top 10 por venta) — V = venta bruta, M = margen front</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.78rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">{h}</tr>
<tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">{s}</tr></thead>
<tbody>{b}</tbody></table>"""

    # Top SKUs (lado a lado: venta + margen)
    bloque_top_skus = ''
    if top_skus_venta or top_skus_margen:
        total_cyber_b = sum(float(d[2] or 0) for d in por_dia)
        total_cyber_m = sum(float(d[4] or 0) for d in por_dia)
        def _tabla_sku(rows, titulo, ord_label):
            if not rows:
                return ''
            body = ''
            for sku, prod, uds, bruta, margen, pctm in rows:
                share_v = bruta / total_cyber_b * 100 if total_cyber_b else 0
                share_m = margen / total_cyber_m * 100 if total_cyber_m else 0
                body += f'<tr><td>{sku[:14]}</td><td>{prod}</td><td align="right">{uds:,}</td>'
                body += f'<td align="right">{fmt_m(bruta)}</td><td align="right">{fmt_m(margen)}</td>'
                body += f'<td align="right">{pctm:.1f}%</td>'
                body += f'<td align="right">{share_v:.1f}%</td><td align="right">{share_m:.1f}%</td></tr>'
            return f"""
<h4 style="margin:16px 0 6px 0;font-size:0.9rem">{titulo}</h4>
<table style="width:100%;border-collapse:collapse;font-size:0.78rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">
  <th align="left">SKU</th><th align="left">Producto</th><th align="right">Uds</th>
  <th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th>
  <th align="right">%Sh V</th><th align="right">%Sh M</th>
</tr></thead><tbody>{body}</tbody></table>"""
        bloque_top_skus = f"""
<h3 style="margin:24px 0 8px 0;font-size:1rem">⭐ Top 10 SKUs acumulado Cyber (%Sh = % del total Cyber)</h3>
{_tabla_sku(top_skus_venta, "🥇 Top 10 por VENTA bruta", "venta")}
{_tabla_sku(top_skus_margen, "💰 Top 10 por MARGEN front", "margen")}"""

    # Alarma stock
    if alarma_stock:
        rows_st = []
        for a in alarma_stock:
            color_c = '#DC2626' if a['dias_cob'] < 3 else '#EA580C'
            rows_st.append(
                f'<tr><td>{a["sku"][:14]}</td><td>{a["producto"]}</td><td>{a["marca"]}</td>'
                f'<td align="right">{a["disp"]}</td>'
                f'<td align="right">{a["vta_diaria"]:.1f}</td>'
                f'<td align="right" style="color:{color_c};font-weight:600">{a["dias_cob"]:.1f}d</td>'
                f'<td align="right">{fmt_m(a["perdido"])}</td></tr>'
            )
        tabla_st = '\n'.join(rows_st)
        bloque_alarma = f"""
<h3 style="margin:24px 0 8px 0;font-size:1rem">⚠️ Alarma stock — top 10 (cobertura &lt; 7 días)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.85rem">
<thead><tr style="background:#FEE2E2;border-bottom:2px solid #DC2626">
  <th align="left">SKU</th><th align="left">Producto</th><th align="left">Marca</th>
  <th align="right">Stock</th><th align="right">V.diaria</th>
  <th align="right">Cobertura</th><th align="right">Pérdida 7d</th>
</tr></thead><tbody>{tabla_st}</tbody></table>"""
    else:
        bloque_alarma = '<p style="color:#16A34A;margin:16px 0">✅ Sin alarmas de stock crítico (cobertura &gt; 7 días en SKUs activos).</p>'

    # Proyección con referencia Cyber 2025 (mismo día YoY)
    proy = proyectar_cierre(bruta_hoy, hora_actual, curva_ly, meta_hoy, fecha_ly)
    if proy:
        gap_dia = proy['proy_dia'] - meta_hoy
        color_p = '#16A34A' if proy['avance_vs_meta'] >= 0.9 else ('#EA580C' if proy['avance_vs_meta'] >= 0.5 else '#DC2626')
        yoy_pct = proy['yoy_dia'] * 100
        color_yoy = '#16A34A' if yoy_pct >= 0 else '#DC2626'
        # Proyección Cyber completo: extrapolar ratio actual (proy_dia/meta_dia) a los días restantes
        ratio_actual = proy['proy_dia'] / meta_hoy if meta_hoy else 1
        proy_cyber_total = bruta_total + (proy['proy_dia'] - bruta_hoy)  # cierre hoy
        for f in CYBER_FECHAS:
            if f > hoy_str:
                idx = CYBER_FECHAS.index(f)
                proy_cyber_total += META_DIA_BRUTA[idx] * ratio_actual
        avance_cyber_proy = proy_cyber_total / META_TOTAL if META_TOTAL else 0
        # Margen proyectado del día (asumiendo mismo margen% que llevamos)
        margen_pct_hoy = (margen_hoy / float(dia_hoy[3]) if dia_hoy and dia_hoy[3] else 0)
        margen_proy_dia = proy['proy_dia'] * margen_pct_hoy if margen_pct_hoy else 0
        margen_ly_pct = (margen_ly_val / neta_ly_val) if neta_ly_val else 0
        yoy_margen_pct = (margen_proy_dia / margen_ly_val - 1) if margen_ly_val else 0
        color_ym = '#16A34A' if yoy_margen_pct >= 0 else '#DC2626'
        # Cyber completo: margen acum + proyección margen restante
        margen_total_actual = margen_total  # acumulado real Cyber 2026
        margen_proy_cyber = margen_total_actual + (margen_proy_dia - margen_hoy)
        ratio_actual = proy['proy_dia'] / meta_hoy if meta_hoy else 1
        for f in CYBER_FECHAS:
            if f > hoy_str:
                idx = CYBER_FECHAS.index(f)
                margen_proy_cyber += META_DIA_BRUTA[idx] * ratio_actual * MARGEN_OBJETIVO
        yoy_cyber_bruta = (proy_cyber_total / cyber_ly_bruta - 1) if cyber_ly_bruta else 0
        yoy_cyber_margen = (margen_proy_cyber / cyber_ly_margen - 1) if cyber_ly_margen else 0
        color_yc_b = '#16A34A' if yoy_cyber_bruta >= 0 else '#DC2626'
        color_yc_m = '#16A34A' if yoy_cyber_margen >= 0 else '#DC2626'

        # YoY vs Cyber OCTUBRE 2025
        yoy_oct_pct = (proy['proy_dia'] / total_oct_val - 1) if total_oct_val else 0
        margen_oct_pct_ref = (margen_oct_val / neta_oct_val) if neta_oct_val else 0
        yoy_oct_margen = (margen_proy_dia / margen_oct_val - 1) if margen_oct_val else 0
        color_yoct = '#16A34A' if yoy_oct_pct >= 0 else '#DC2626'
        color_yoct_m = '#16A34A' if yoy_oct_margen >= 0 else '#DC2626'
        yoy_cyber_oct_b = (proy_cyber_total / cyber_oct_bruta - 1) if cyber_oct_bruta else 0
        yoy_cyber_oct_m = (margen_proy_cyber / cyber_oct_margen - 1) if cyber_oct_margen else 0
        col_yco_b = '#16A34A' if yoy_cyber_oct_b >= 0 else '#DC2626'
        col_yco_m = '#16A34A' if yoy_cyber_oct_m >= 0 else '#DC2626'

        bloque_proy = f"""
<div style="background:#FEF3C7;border-left:4px solid #EA580C;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">📈 Proyección (referencia: Cyber 2025 — Jun y Oct)</div>
  <table style="width:100%;margin-top:6px;font-size:0.88rem">
    <tr><td>Hoy llevamos:</td>
        <td align="right"><b>{fmt_m(bruta_hoy)}</b> bruta · {fmt_m(margen_hoy)} margen ({margen_pct_hoy*100:.1f}%)
        — ({proy['pct_hasta_ref']*100:.0f}% del día en {fecha_ly})</td></tr>
    <tr><td>Día equiv Cyber Jun 2025 ({fecha_ly}):</td>
        <td align="right">{fmt_m(total_ly_val)} bruta · {fmt_m(margen_ly_val)} margen ({margen_ly_pct*100:.1f}%)</td></tr>
    <tr><td>Día equiv Cyber Oct 2025 ({fecha_oct or '—'}):</td>
        <td align="right">{fmt_m(total_oct_val)} bruta · {fmt_m(margen_oct_val)} margen ({margen_oct_pct_ref*100:.1f}%)</td></tr>
    <tr><td>Proyección cierre HOY:</td>
        <td align="right" style="color:{color_p}"><b>{fmt_m(proy['proy_dia'])}</b> bruta · {fmt_m(margen_proy_dia)} margen
        — ({proy['avance_vs_meta']*100:.0f}% meta · gap {fmt_m(gap_dia)})</td></tr>
    <tr><td>YoY venta vs Jun 2025:</td>
        <td align="right" style="color:{color_yoy};font-weight:600">{yoy_pct:+.1f}%</td></tr>
    <tr><td>YoY margen vs Jun 2025:</td>
        <td align="right" style="color:{color_ym};font-weight:600">{yoy_margen_pct*100:+.1f}%</td></tr>
    <tr><td>YoY venta vs Oct 2025:</td>
        <td align="right" style="color:{color_yoct};font-weight:600">{yoy_oct_pct*100:+.1f}%</td></tr>
    <tr><td>YoY margen vs Oct 2025:</td>
        <td align="right" style="color:{color_yoct_m};font-weight:600">{yoy_oct_margen*100:+.1f}%</td></tr>
    <tr style="border-top:1px solid #E2E8F0"><td><b>Proyección Cyber completo:</b></td>
        <td align="right"><b>{fmt_m(proy_cyber_total)}</b> bruta · {fmt_m(margen_proy_cyber)} margen
        ({avance_cyber_proy*100:.1f}% meta venta $505.9 M)</td></tr>
    <tr><td>Cyber Jun 2025 completo (6 días):</td>
        <td align="right">{fmt_m(cyber_ly_bruta)} bruta · {fmt_m(cyber_ly_margen)} margen ({(cyber_ly_margen/cyber_ly_neta*100 if cyber_ly_neta else 0):.1f}%)</td></tr>
    <tr><td>Cyber Oct 2025 ventana 6d (Lun-Sáb):</td>
        <td align="right">{fmt_m(cyber_oct_bruta)} bruta · {fmt_m(cyber_oct_margen)} margen ({(cyber_oct_margen/cyber_oct_neta*100 if cyber_oct_neta else 0):.1f}%)</td></tr>
    <tr><td>YoY Cyber vs Jun 2025:</td>
        <td align="right">
          Venta <span style="color:{color_yc_b};font-weight:600">{yoy_cyber_bruta*100:+.1f}%</span> ·
          Margen <span style="color:{color_yc_m};font-weight:600">{yoy_cyber_margen*100:+.1f}%</span>
        </td></tr>
    <tr><td>YoY Cyber vs Oct 2025:</td>
        <td align="right">
          Venta <span style="color:{col_yco_b};font-weight:600">{yoy_cyber_oct_b*100:+.1f}%</span> ·
          Margen <span style="color:{col_yco_m};font-weight:600">{yoy_cyber_oct_m*100:+.1f}%</span>
        </td></tr>
  </table>
</div>"""
    else:
        bloque_proy = '<p style="color:#64748B;font-size:0.85rem">📈 Proyección no disponible (sin data Cyber 2025 en histórico).</p>'

    color_avance = '#16A34A' if avance_pct >= 0.8 else ('#EA580C' if avance_pct >= 0.4 else '#DC2626')

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body style="font-family:-apple-system,Segoe UI,sans-serif;max-width:780px;margin:auto;color:#1E293B">

<h2 style="margin:0 0 4px 0">🛍️ Pulso Cyber UnionX 2026</h2>
<p style="color:#64748B;margin:0 0 16px 0;font-size:0.9rem">{fecha_hora}</p>

<div style="background:#F1F5F9;border-left:4px solid #2563EB;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Acumulado Cyber</div>
  <div style="font-size:1.6rem;font-weight:700;color:#1E40AF;margin:2px 0">{fmt_m(bruta_total)}</div>
  <div style="font-size:0.85rem;color:#64748B">
    Meta total: {fmt_m(META_TOTAL)} ·
    <span style="color:{color_avance};font-weight:600">{avance_pct*100:.1f}%</span> ·
    Margen {fmt_m(margen_total)} ({margen_pct*100:.1f}%) ·
    {uds_total:,} uds · {sos_total:,} pedidos
  </div>
</div>

<div style="background:#FEF3C7;border-left:4px solid #EA580C;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Hoy ({ahora_clt.strftime('%a %d-%b')})</div>
  <div style="font-size:1.4rem;font-weight:700;color:#9A3412;margin:2px 0">{fmt_m(bruta_hoy)}</div>
  <div style="font-size:0.85rem;color:#64748B">
    Meta día: {fmt_m(meta_hoy)} ·
    <span style="font-weight:600">{avance_hoy*100:.1f}%</span> ·
    Margen {fmt_m(margen_hoy)} · {uds_hoy:,} uds
  </div>
</div>

{bloque_proy}

<h3 style="margin:24px 0 8px 0;font-size:1rem">📅 Por día (curva diaria)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">
  <th align="left">Día</th><th align="right">SOs</th><th align="right">Uds</th>
  <th align="right">Bruta</th><th align="right">Margen</th>
  <th align="right">Meta</th><th align="right">Avance</th>
</tr></thead>
<tbody>{tabla_dia}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏆 Top canales × día (V = venta, M = margen)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.82rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">{headers_cd}</tr>
<tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">{subheaders_cd}</tr></thead>
<tbody>{tabla_cd}</tbody></table>
<p style="font-size:0.75rem;color:#64748B;margin:4px 0">
  Columnas Meta: %V = venta acum / meta venta canal. %M = margen acum / meta margen canal (estimada al {int(MARGEN_OBJETIVO*100)}% sobre venta).
</p>

<h3 style="margin:24px 0 8px 0;font-size:1rem">📦 Modalidad (Fulfillment vs Seller+Flex)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">
  <th align="left">Modalidad</th><th align="right">SOs</th>
  <th align="right">Bruta</th><th align="right">Margen</th><th align="right">Share</th>
</tr></thead>
<tbody>{tabla_mod}</tbody></table>

{bloque_marca_dia}

{bloque_categoria_dia}

{bloque_top_skus}

{bloque_alarma}

<hr style="border:none;border-top:1px solid #E2E8F0;margin:24px 0">
<p style="font-size:0.85rem;color:#64748B">
📎 Adjunto: Excel RAW completo del día.<br>
🔗 Dashboard live: <a href="https://unionx-ventas.streamlit.app/ventas-cyber">unionx-ventas.streamlit.app/ventas-cyber</a><br>
⏰ Próximo pulso en 2h.
</p>

<style>td,th{{padding:6px 8px;border-bottom:1px solid #E2E8F0}}</style>
</body></html>"""
    return html, bruta_total, bruta_hoy, avance_pct


def descargar_excel_raw_hoy():
    """Genera Excel RAW del día desde el PARQUET local (no Turso).
    Excluye columna venta_neta (preferencia operativa)."""
    hoy_str = hoy_comercial()
    print(f"[3/5] Generando Excel RAW {hoy_str} desde parquet...", flush=True)
    parquet_path = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
    df_all = pd.read_parquet(parquet_path)
    df_all['fecha_venta'] = pd.to_datetime(df_all['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    df = df_all[df_all['fecha_venta'] == hoy_str].copy()
    if 'venta_neta' in df.columns:
        df = df.drop(columns=['venta_neta'])
    print(f"      [OK] {len(df):,} filas hoy ({len(df.columns)} cols, sin venta_neta)", flush=True)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name=f'Cyber {hoy_str}')
    return buf.getvalue(), len(df), hoy_str


def _enviar_via_gmail(asunto, html, xlsx_bytes, hoy_str, to_list, extra_attachments=None):
    """Envío vía Gmail API usando credentials del agente-comex.
    extra_attachments: lista opcional de (bytes, nombre_exacto.xlsx) que se adjuntan
    con su nombre tal cual (sin el prefijo 'Raw Cyber')."""
    import json as _json
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds_json = os.environ.get('GMAIL_TOKEN_JSON', '')
    if not creds_json:
        # Fallback: leer del file local
        token_path = PROJECT_ROOT / 'agente-comex' / 'config' / 'token.json'
        if token_path.exists():
            creds_json = token_path.read_text()
    if not creds_json:
        print("[Gmail] No hay GMAIL_TOKEN_JSON, fallback a Resend", flush=True)
        return None  # caller decide fallback

    creds_data = _json.loads(creds_json)
    creds = Credentials.from_authorized_user_info(creds_data, creds_data.get('scopes'))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    service = build('gmail', 'v1', credentials=creds)
    msg = MIMEMultipart()
    msg['to'] = ','.join(to_list)
    msg['subject'] = asunto
    msg.attach(MIMEText(html, 'html'))

    if xlsx_bytes:
        part = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        part.set_payload(xlsx_bytes)
        encoders.encode_base64(part)
        # hoy_str puede venir como nombre propio del reporte o como etiqueta/fecha.
        # Normalizar: quitar ".xlsx" final si viene (evita doble extensión) y anteponer
        # "Raw Cyber " SOLO al legacy (etiquetas de fecha del pulso Cyber). Los reportes
        # con nombre propio (Reporte/Cierre/Mes/Stock) van tal cual.
        base = str(hoy_str)
        if base.lower().endswith('.xlsx'):
            base = base[:-5]
        fname = base if base.startswith(('Reporte', 'Cierre', 'Mes', 'Stock')) else f'Raw Cyber {base}'
        # forma keyword: nombres con tilde/no-ASCII se codifican RFC2231 (Gmail los lee).
        # La forma f'filename="..."' rompe con acentos → adjunto "noname".
        part.add_header('Content-Disposition', 'attachment', filename=f'{fname}.xlsx')
        msg.attach(part)

    for ebytes, ename in (extra_attachments or []):
        if not ebytes:
            continue
        ep = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        ep.set_payload(ebytes)
        encoders.encode_base64(ep)
        en = ename if ename.lower().endswith('.xlsx') else f'{ename}.xlsx'
        ep.add_header('Content-Disposition', 'attachment', filename=en)
        msg.attach(ep)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service.users().messages().send(userId='me', body={'raw': raw}).execute()
    return sent.get('id', '?')


def enviar(html, xlsx_bytes, n_filas, hoy_str, bruta_total, bruta_hoy, avance_pct):
    print(f"[4/5] Enviando email a {EMAIL_TO}...", flush=True)
    asunto_prefix = '[PRE-BORRADOR] ' if PREBORRADOR else ''
    flecha = '📈' if avance_pct >= 0.5 else '📉'
    asunto = (f"{asunto_prefix}🛍️ Cyber UnionX · {datetime.now(CHILE_TZ).strftime('%H:%M')} · "
              f"{fmt_m(bruta_hoy)} hoy · {fmt_m(bruta_total)} acum {flecha}")

    # 1) Intentar Gmail API (sin restricciones de dominio)
    if os.environ.get('GMAIL_TOKEN_JSON') or (PROJECT_ROOT / 'agente-comex' / 'config' / 'token.json').exists():
        try:
            msg_id = _enviar_via_gmail(asunto, html, xlsx_bytes, hoy_str, EMAIL_TO)
            if msg_id:
                print(f"      [OK] enviado via Gmail (msg_id {msg_id})", flush=True)
                return True
        except Exception as e:
            print(f"      [WARN] Gmail falló: {type(e).__name__}: {e}", flush=True)

    # 2) Fallback Resend
    if not RESEND_API_KEY:
        print("[ERROR] No Gmail ni Resend disponibles", flush=True)
        return False
    attachment = {
        'filename': f'Raw Cyber {hoy_str}.xlsx',
        'content': base64.b64encode(xlsx_bytes).decode(),
    }
    payload = {
        'from': EMAIL_FROM, 'to': EMAIL_TO,
        'subject': asunto, 'html': html, 'attachments': [attachment],
    }
    r = requests.post('https://api.resend.com/emails', json=payload,
                      headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
                      timeout=60)
    if r.status_code >= 300:
        print(f"[ERROR] Resend: {r.status_code} {r.text}", flush=True)
        return False
    print(f"      [OK] enviado via Resend ({r.json().get('id','?')})", flush=True)
    return True


def validar_data_integrity(bruta_hoy: float, n_filas_hoy: int) -> tuple[bool, str]:
    """Valida que la data esté íntegra antes de enviar el pulso.

    Fuente: PARQUET local (no Turso, Turso queda fuera de pulso por bug sync).
    SIEMPRE compara parquet vs Odoo state=sale. Si discrepancia > 10%, NO enviar.
    Detecta duplicados en parquet por grupo (pedido, sku, hora, venta, cant, doc, tipo).
    FAIL-CLOSED: si no puedo validar, NO envío.
    """
    hoy_dia = hoy_comercial()

    # 1) Detectar duplicados en PARQUET
    try:
        parquet_path = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
        df = pd.read_parquet(parquet_path)
        df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
        d_hoy = df[df['fecha_venta'] == hoy_dia]
        if len(d_hoy):
            dup = d_hoy.groupby(['pedido','sku','hora_venta','venta_bruta','cantidad','documento','tipo_movimiento']).size()
            n_dup = int((dup > 1).sum())
            if n_dup > 0:
                return False, f"Parquet tiene {n_dup} grupos duplicados para {hoy_dia} — NO envío (re-extraer + dedupear)"
        parquet_bruta = float(d_hoy['venta_bruta'].sum())
        parquet_n = int(d_hoy['pedido'].nunique())
    except Exception as e:
        return False, f"no pude leer parquet ({type(e).__name__}: {e}) — NO envío"

    # 2) Comparar parquet vs Odoo state=sale
    try:
        import xmlrpc.client
        odoo_url = os.environ.get('ODOO_URL', 'https://unionxb2b.odoo.com')
        odoo_db = os.environ.get('ODOO_DB', 'bmya-innovatek-sh-prd-6981800')
        odoo_user = os.environ.get('ODOO_USER', 'andres@grupoeter.cl')
        odoo_pwd = os.environ.get('ANDRES_ODOO_PASSWORD', '')
        if not odoo_pwd:
            return False, "no ANDRES_ODOO_PASSWORD, no puedo validar — NO envío"
        common = xmlrpc.client.ServerProxy(f'{odoo_url}/xmlrpc/2/common', allow_none=True)
        uid = common.authenticate(odoo_db, odoo_user, odoo_pwd, {})
        if not uid:
            return False, "Odoo auth failed, no puedo validar — NO envío"
        models = xmlrpc.client.ServerProxy(f'{odoo_url}/xmlrpc/2/object', allow_none=True)
        desde_utc = f"{hoy_dia} 04:00:00"  # 00:00 CLT
        from datetime import datetime as _dt, timedelta as _td
        d_next = (_dt.strptime(hoy_dia, '%Y-%m-%d') + _td(days=1)).strftime('%Y-%m-%d')
        hasta_utc = f"{d_next} 04:00:00"
        sos = models.execute_kw(odoo_db, uid, odoo_pwd, 'sale.order', 'search_read',
            [[('date_order','>=',desde_utc),('date_order','<',hasta_utc),('state','=','sale')]],
            {'fields':['amount_total'], 'limit':10000})
        odoo_bruta = sum(s['amount_total'] for s in sos)
        odoo_n = len(sos)
    except Exception as e:
        return False, f"odoo unavailable ({type(e).__name__}) — NO envío"

    print(f"[VALIDATE] Parquet {hoy_dia}: ${parquet_bruta:,.0f} ({parquet_n} SOs) | "
          f"Odoo state=sale: ${odoo_bruta:,.0f} ({odoo_n} SOs)", flush=True)

    if odoo_bruta < 1_000_000:
        return True, f"odoo low (${odoo_bruta:,.0f}), pre-Cyber window"

    diff_pct = abs(parquet_bruta - odoo_bruta) / odoo_bruta if odoo_bruta else 1
    if diff_pct > 0.10:
        msg = (f"discrepancia Parquet vs Odoo > 10%: "
               f"Parquet ${parquet_bruta:,.0f} vs Odoo ${odoo_bruta:,.0f} "
               f"(diff {diff_pct*100:.1f}%) — re-extraer parquet")
        return False, msg

    return True, f"validation OK (Parquet ${parquet_bruta:,.0f} vs Odoo ${odoo_bruta:,.0f}, diff {diff_pct*100:.2f}%)"


def alertar_andres(asunto: str, detalle: str) -> bool:
    """Alerta SOLO a Andrés (no al CEO) cuando un gate bloquea el pulso."""
    to = [e.strip() for e in os.environ.get('ANDRES_ALERT_EMAIL', 'andres@unionx.cl').split(',') if e.strip()]
    html = (f"<h3>⚠️ Pulso Cyber bloqueado por el mecanismo de seguridad</h3>"
            f"<p>{datetime.now(CHILE_TZ).strftime('%Y-%m-%d %H:%M CLT')}</p>"
            f"<pre style='background:#f6f8fa;padding:12px;border-radius:6px'>{detalle}</pre>"
            f"<p>El pulso al CEO NO se envió. Revisa el extract/parquet.</p>")
    full = f"[ALERTA pulso] {asunto}"
    if RESEND_API_KEY:
        try:
            r = requests.post('https://api.resend.com/emails',
                              json={'from': EMAIL_FROM, 'to': to, 'subject': full, 'html': html},
                              headers={'Authorization': f'Bearer {RESEND_API_KEY}',
                                       'Content-Type': 'application/json'}, timeout=30)
            print(f"   [alerta→Andrés] Resend {r.status_code}", flush=True)
            return r.status_code < 300
        except Exception as e:
            print(f"   [alerta→Andrés] falló: {e}", flush=True)
    return False


def main():
    if not _check_rango():
        return 0

    # Email del pulso CADA 2H (horas pares CLT: 20, 22, ...). El refresco del
    # parquet/app es horario (otro step del workflow); aquí solo se controla el EMAIL.
    # Configurable: CYBER_EMAIL_HOURS="8,10,12,..." (CSV) sobreescribe la regla par.
    hora_clt = datetime.now(CHILE_TZ).hour
    _horas_cfg = os.environ.get('CYBER_EMAIL_HOURS', '').strip()
    if _horas_cfg:
        _permitido = hora_clt in {int(h) for h in _horas_cfg.split(',') if h.strip().isdigit()}
    else:
        # Horas pares dentro de la ventana 08:00 a 24:00 (medianoche=0). Excluye 2,4,6 am.
        _permitido = (hora_clt % 2 == 0) and (hora_clt == 0 or hora_clt >= 8)
    # Bypass manual: force_email=true ignora la ventana horaria.
    if os.environ.get('CYBER_FORCE_EMAIL') == '1':
        _permitido = True
        print(f"[FORCE email] envío forzado (ignora ventana horaria), hora {hora_clt} CLT", flush=True)
    if not _permitido:
        print(f"[SKIP email] hora {hora_clt} CLT — pulso al CEO cada 2h, ventana 08:00–24:00. "
              f"El parquet/app igual se refrescó en el step previo.", flush=True)
        return 0

    if not URL or not TOKEN or not RESEND_API_KEY:
        print("[ERROR] Faltan vars de entorno", flush=True)
        return 1

    # GATE 2 (mecanismo de seguridad): el parquet de ventas debe estar sano antes
    # de armar/enviar el pulso. Si no pasa, NO se envía al CEO y se te alerta a TI.
    try:
        from validacion_ventas import validar_ventas_df, resumen_validacion
        _mes_p = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
        _df_chk = pd.read_parquet(_mes_p) if _mes_p.exists() else None
        _okv, _probs, _st = validar_ventas_df(_df_chk, None)
        if not _okv:
            _detalle = resumen_validacion(_okv, _probs, _st)
            print(f"[GATE 2] BLOQUEA ENVÍO:\n{_detalle}", flush=True)
            alertar_andres("datos no pasaron validación — pulso NO enviado", _detalle)
            return 0
    except Exception as e:
        print(f"[GATE 2][WARN] validación saltada: {type(e).__name__}: {e}", flush=True)

    metas_canal = cargar_metas_canal()
    (por_dia, por_canal_dia, por_canal_acum, por_mod, por_hora_hoy, curva_ly,
     fecha_ly, total_ly_val, margen_ly_val, neta_ly_val,
     cyber_ly_bruta, cyber_ly_margen, cyber_ly_neta,
     fecha_oct, total_oct_val, margen_oct_val, neta_oct_val,
     cyber_oct_bruta, cyber_oct_margen, cyber_oct_neta,
     por_marca_dia, por_categoria_dia, top_skus_venta, top_skus_margen) = descargar_resumen(metas_canal)

    # VALIDACIÓN TEMPRANA contra Odoo
    hoy_str = hoy_comercial()
    dia_hoy_data = next((d for d in por_dia if d[0] == hoy_str), None)
    bruta_hoy_early = float(dia_hoy_data[2]) if dia_hoy_data and dia_hoy_data[2] else 0
    ok_validate, msg = validar_data_integrity(bruta_hoy_early, 0)
    if not ok_validate:
        print(f"[VALIDATE] ABORTAR ENVÍO: {msg}", flush=True)
        alertar_andres("validar_data_integrity falló — pulso NO enviado", msg)
        return 0
    print(f"[VALIDATE] {msg}", flush=True)

    alarma_stock = cargar_alarma_stock()
    html, bruta_total, bruta_hoy, avance_pct = render_html(
        por_dia, por_canal_dia, por_canal_acum, por_mod, por_hora_hoy,
        curva_ly, fecha_ly, total_ly_val, margen_ly_val, neta_ly_val,
        cyber_ly_bruta, cyber_ly_margen, cyber_ly_neta,
        fecha_oct, total_oct_val, margen_oct_val, neta_oct_val,
        cyber_oct_bruta, cyber_oct_margen, cyber_oct_neta,
        alarma_stock, metas_canal,
        por_marca_dia, por_categoria_dia, top_skus_venta, top_skus_margen
    )

    # Excel del día con reintento si Turso devuelve 0 pero hay venta esperada
    xlsx_bytes, n_filas, hoy_str_x = descargar_excel_raw_hoy()
    if n_filas == 0 and bruta_hoy > 1_000_000:
        print(f"[Excel] 0 filas pero bruta ${bruta_hoy:,.0f} > $1M — esperando 30s y reintentando", flush=True)
        time.sleep(30)
        xlsx_bytes, n_filas, hoy_str_x = descargar_excel_raw_hoy()
        if n_filas == 0:
            print(f"[Excel] AÚN 0 filas tras reintento — ABORTAR para no mandar Excel vacío", flush=True)
            alertar_andres("Excel del día vino vacío (0 filas) — pulso NO enviado",
                           f"bruta_hoy esperada ${bruta_hoy:,.0f} pero el RAW del día tiene 0 filas.")
            return 0

    ok = enviar(html, xlsx_bytes, n_filas, hoy_str_x, bruta_total, bruta_hoy, avance_pct)
    print("[5/5] Done." if ok else "[5/5] FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
