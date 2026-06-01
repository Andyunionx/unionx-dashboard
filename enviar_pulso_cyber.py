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
RANGO_INICIO = datetime(2026, 6, 1, 6, 0, tzinfo=CHILE_TZ)
RANGO_FIN = datetime(2026, 6, 4, 22, 0, tzinfo=CHILE_TZ)

CYBER_FECHAS = ['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04', '2026-06-05', '2026-06-06']
CYBER_LABELS = ['Lun 1-jun', 'Mar 2-jun', 'Mié 3-jun', 'Jue 4-jun', 'Vie 5-jun', 'Sáb 6-jun']
CYBER_LABELS_SHORT = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb']
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


def descargar_resumen(metas_canal):
    print("[1/5] Descargando data Cyber desde Turso...", flush=True)
    t0 = time.time()
    fechas_sql = ','.join(repr(f) for f in CYBER_FECHAS)

    # Por día
    por_dia = _rows(turso_query(
        "SELECT fecha_venta, COUNT(DISTINCT pedido), ROUND(SUM(venta_bruta),0), "
        "ROUND(SUM(venta_neta),0), ROUND(SUM(margen_final),0), ROUND(SUM(cantidad),0) "
        f"FROM ventas WHERE fecha_venta IN ({fechas_sql}) "
        "GROUP BY fecha_venta ORDER BY fecha_venta"
    ))

    # Por canal × día (matriz)
    por_canal_dia = _rows(turso_query(
        "SELECT canal, fecha_venta, ROUND(SUM(venta_bruta),0), ROUND(SUM(margen_final),0), "
        "ROUND(SUM(cantidad),0) "
        f"FROM ventas WHERE fecha_venta IN ({fechas_sql}) "
        "GROUP BY canal, fecha_venta"
    ))

    # Por canal acumulado
    por_canal_acum = _rows(turso_query(
        "SELECT canal, COUNT(DISTINCT pedido), ROUND(SUM(venta_bruta),0), "
        "ROUND(SUM(margen_final),0), ROUND(SUM(cantidad),0) "
        f"FROM ventas WHERE fecha_venta IN ({fechas_sql}) "
        "GROUP BY canal ORDER BY 3 DESC"
    ))

    # Modalidad
    por_mod = _rows(turso_query(
        "SELECT CASE WHEN LOWER(bodega) LIKE 'bodega fulfillment%' THEN 'Fulfillment' "
        "ELSE 'Seller + Flex' END, COUNT(DISTINCT pedido), "
        "ROUND(SUM(venta_bruta),0), ROUND(SUM(margen_final),0) "
        f"FROM ventas WHERE fecha_venta IN ({fechas_sql}) GROUP BY 1"
    ))

    # Por hora HOY (CLT)
    hoy_str = datetime.now(CHILE_TZ).strftime('%Y-%m-%d')
    por_hora_hoy = _rows(turso_query(
        f"SELECT hora_venta_num, COUNT(DISTINCT pedido), ROUND(SUM(venta_bruta),0) "
        f"FROM ventas WHERE fecha_venta='{hoy_str}' "
        "GROUP BY hora_venta_num ORDER BY hora_venta_num"
    ))

    # Curva intradiaria del LUNES anterior (25-may) para proyección
    curva_lunes = _rows(turso_query(
        "SELECT hora_venta_num, ROUND(SUM(venta_bruta),0) "
        "FROM ventas WHERE fecha_venta='2026-05-25' "
        "GROUP BY hora_venta_num ORDER BY hora_venta_num"
    ))

    print(f"      [OK] en {time.time()-t0:.1f}s", flush=True)
    return por_dia, por_canal_dia, por_canal_acum, por_mod, por_hora_hoy, curva_lunes


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


def proyectar_cierre(bruta_hoy: float, hora_actual: int, curva_lunes_data: list, meta_hoy: float):
    """Proyecta cierre del día usando curva del lunes anterior (25-may) como referencia."""
    # curva_lunes_data: [(hora, bruta_hora), ...]
    if not curva_lunes_data:
        return None
    total_lunes = sum(float(r[1] or 0) for r in curva_lunes_data)
    if total_lunes <= 0:
        return None
    # % acumulado hasta hora_actual del lunes ref
    acum_hasta = sum(float(r[1] or 0) for r in curva_lunes_data if r[0] is not None and int(r[0]) <= hora_actual)
    pct_hasta = acum_hasta / total_lunes
    if pct_hasta <= 0:
        return None
    proy_dia = bruta_hoy / pct_hasta
    avance_meta = proy_dia / meta_hoy if meta_hoy else 0
    return {
        'proy_dia': proy_dia,
        'pct_hasta_ref': pct_hasta,
        'avance_vs_meta': avance_meta,
        'ritmo_vs_meta': bruta_hoy / (meta_hoy * pct_hasta) if (meta_hoy * pct_hasta) else 0,
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
                curva_lunes, alarma_stock, metas_canal):
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
    hoy_str = ahora_clt.strftime('%Y-%m-%d')
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

    # Proyección
    proy = proyectar_cierre(bruta_hoy, hora_actual, curva_lunes, meta_hoy)
    if proy:
        gap_dia = proy['proy_dia'] - meta_hoy
        color_p = '#16A34A' if proy['avance_vs_meta'] >= 0.9 else ('#EA580C' if proy['avance_vs_meta'] >= 0.5 else '#DC2626')
        ritmo_pct = (proy['ritmo_vs_meta'] - 1) * 100
        ritmo_txt = f"{ritmo_pct:+.1f}% vs lunes 25-may"
        # Proyección Cyber completo: extrapolar ratio actual a los días restantes
        dias_pendientes = sum(1 for f in CYBER_FECHAS if f > hoy_str)
        # Proyección lineal de todos los días restantes asumiendo mismo ratio
        if proy['ritmo_vs_meta'] > 0:
            proy_cyber_total = bruta_total + proy['proy_dia'] - bruta_hoy  # cierre hoy
            for f in CYBER_FECHAS:
                if f > hoy_str:
                    idx = CYBER_FECHAS.index(f)
                    proy_cyber_total += META_DIA_BRUTA[idx] * proy['ritmo_vs_meta']
        else:
            proy_cyber_total = bruta_total
        avance_cyber_proy = proy_cyber_total / META_TOTAL if META_TOTAL else 0
        bloque_proy = f"""
<div style="background:#FEF3C7;border-left:4px solid #EA580C;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">📈 Proyección</div>
  <table style="width:100%;margin-top:6px;font-size:0.88rem">
    <tr><td>Hoy llevamos:</td>
        <td align="right"><b>{fmt_m(bruta_hoy)}</b> ({proy['pct_hasta_ref']*100:.0f}% típico hasta {hora_actual}h CLT, ref lunes 25-may)</td></tr>
    <tr><td>Proyección cierre día:</td>
        <td align="right" style="color:{color_p}"><b>{fmt_m(proy['proy_dia'])}</b>
        ({proy['avance_vs_meta']*100:.0f}% meta diaria, gap {fmt_m(gap_dia)})</td></tr>
    <tr><td>Ritmo actual:</td><td align="right">{ritmo_txt}</td></tr>
    <tr><td>Proyección Cyber completo:</td>
        <td align="right"><b>{fmt_m(proy_cyber_total)}</b>
        ({avance_cyber_proy*100:.1f}% meta total $505.9 M)</td></tr>
  </table>
</div>"""
    else:
        bloque_proy = ""

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
    ahora_clt = datetime.now(CHILE_TZ)
    hoy_str = ahora_clt.strftime('%Y-%m-%d')
    print(f"[3/5] Descargando Excel RAW {hoy_str}...", flush=True)
    sys.path.insert(0, str(PROJECT_ROOT))
    from enviar_excel_diario import DB_COLS, DB_TO_RAW
    chunk = 80000
    all_rows = []
    last = 0
    while True:
        res = turso_query(
            f"SELECT rowid, {','.join(DB_COLS)} FROM ventas "
            f"WHERE fecha_venta = '{hoy_str}' AND rowid > {last} "
            f"ORDER BY rowid LIMIT {chunk}"
        )
        rows = res['rows']
        if not rows:
            break
        for r in rows:
            vals = [c.get('value') if isinstance(c, dict) else c for c in r]
            last = int(vals[0])
            all_rows.append(vals[1:])
        if len(rows) < chunk:
            break
    df = pd.DataFrame(all_rows, columns=DB_COLS).rename(columns=DB_TO_RAW)
    print(f"      [OK] {len(df):,} filas hoy", flush=True)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name=f'Cyber {hoy_str}')
    return buf.getvalue(), len(df), hoy_str


def enviar(html, xlsx_bytes, n_filas, hoy_str, bruta_total, bruta_hoy, avance_pct):
    print(f"[4/5] Enviando email a {EMAIL_TO}...", flush=True)
    asunto_prefix = '[PRE-BORRADOR] ' if PREBORRADOR else ''
    flecha = '📈' if avance_pct >= 0.5 else '📉'
    asunto = (f"{asunto_prefix}🛍️ Cyber UnionX · {datetime.now(CHILE_TZ).strftime('%H:%M')} · "
              f"{fmt_m(bruta_hoy)} hoy · {fmt_m(bruta_total)} acum {flecha}")
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
    print(f"      [OK] enviado ({r.json().get('id','?')})", flush=True)
    return True


def main():
    if not _check_rango():
        return 0
    if not URL or not TOKEN or not RESEND_API_KEY:
        print("[ERROR] Faltan vars de entorno", flush=True)
        return 1

    metas_canal = cargar_metas_canal()
    por_dia, por_canal_dia, por_canal_acum, por_mod, por_hora_hoy, curva_lunes = descargar_resumen(metas_canal)
    alarma_stock = cargar_alarma_stock()
    html, bruta_total, bruta_hoy, avance_pct = render_html(
        por_dia, por_canal_dia, por_canal_acum, por_mod, por_hora_hoy,
        curva_lunes, alarma_stock, metas_canal
    )
    xlsx_bytes, n_filas, hoy_str = descargar_excel_raw_hoy()
    ok = enviar(html, xlsx_bytes, n_filas, hoy_str, bruta_total, bruta_hoy, avance_pct)
    print("[5/5] Done." if ok else "[5/5] FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
