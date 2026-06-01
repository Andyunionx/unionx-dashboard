#!/usr/bin/env python3
"""
Envía pulso Cyber UnionX cada 2h durante el evento (Lun 1-jun a Jue 4-jun 22h CLT).
Incluye HTML resumen + Excel RAW adjunto del día.

Diseñado para correr en GitHub Actions cron cada 2h (UTC).
El script filtra: solo envía si la hora actual cae en rango Lun 1-jun 06:00 CLT a
Jue 4-jun 22:00 CLT (fuera de eso, sale sin enviar).

Vars de entorno:
  LIBSQL_URL              — URL Turso
  LIBSQL_AUTH_TOKEN       — Token Turso
  RESEND_API_KEY          — API key Resend
  EMAIL_TO                — destinatarios (default: andres@unionx.cl,nicolas@unionx.cl)
  EMAIL_FROM              — remitente (default: onboarding@resend.dev)
  CYBER_PREBORRADOR       — si '1', prefija asunto con [PRE-BORRADOR]
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
    'EMAIL_TO', 'andres@unionx.cl,nicolas@unionx.cl'
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
CURVA_PCT = [0.30, 0.25, 0.20, 0.12, 0.08, 0.05]
META_TOTAL = 505_915_976
META_DIA_BRUTA = [META_TOTAL * p for p in CURVA_PCT]


def _check_rango():
    """Sale con código 0 sin enviar si estamos fuera del rango Cyber."""
    ahora = datetime.now(CHILE_TZ)
    if ahora < RANGO_INICIO:
        print(f"[SKIP] {ahora} < {RANGO_INICIO}: aún no empieza el rango Cyber", flush=True)
        return False
    if ahora > RANGO_FIN:
        print(f"[SKIP] {ahora} > {RANGO_FIN}: rango Cyber terminado", flush=True)
        return False
    return True


def turso_query(sql):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    r = requests.post(f"{URL}/v2/pipeline", json=body,
                      headers={'Authorization': f'Bearer {TOKEN}'}, timeout=60)
    r.raise_for_status()
    return r.json()['results'][0]['response']['result']


def descargar_resumen():
    """Carga datos Cyber: KPIs por día, canal, modalidad."""
    print("[1/4] Descargando data Cyber desde Turso...", flush=True)
    t0 = time.time()
    # Por día
    r1 = turso_query(
        "SELECT fecha_venta, COUNT(DISTINCT pedido) sos, ROUND(SUM(venta_bruta),0) bruta, "
        "ROUND(SUM(venta_neta),0) neta, ROUND(SUM(margen_final),0) margen, "
        "ROUND(SUM(cantidad),0) uds "
        f"FROM ventas WHERE fecha_venta IN ({','.join(repr(f) for f in CYBER_FECHAS)}) "
        "GROUP BY fecha_venta ORDER BY fecha_venta"
    )
    por_dia = [[c.get('value') if isinstance(c, dict) else c for c in row] for row in r1['rows']]

    # Por canal (todos los días Cyber agregados)
    r2 = turso_query(
        "SELECT canal, COUNT(DISTINCT pedido) sos, ROUND(SUM(venta_bruta),0) bruta, "
        "ROUND(SUM(margen_final),0) margen, ROUND(SUM(cantidad),0) uds "
        f"FROM ventas WHERE fecha_venta IN ({','.join(repr(f) for f in CYBER_FECHAS)}) "
        "GROUP BY canal ORDER BY bruta DESC LIMIT 10"
    )
    por_canal = [[c.get('value') if isinstance(c, dict) else c for c in row] for row in r2['rows']]

    # Por modalidad (fulfillment vs seller+flex)
    r3 = turso_query(
        "SELECT "
        "CASE WHEN LOWER(bodega) LIKE 'bodega fulfillment%' THEN 'Fulfillment' ELSE 'Seller + Flex' END mod, "
        "COUNT(DISTINCT pedido) sos, ROUND(SUM(venta_bruta),0) bruta, "
        "ROUND(SUM(margen_final),0) margen "
        f"FROM ventas WHERE fecha_venta IN ({','.join(repr(f) for f in CYBER_FECHAS)}) "
        "GROUP BY mod"
    )
    por_mod = [[c.get('value') if isinstance(c, dict) else c for c in row] for row in r3['rows']]

    print(f"      [OK] en {time.time()-t0:.1f}s", flush=True)
    return por_dia, por_canal, por_mod


def fmt_m(v):
    """Formato $X.X M / $X.X K / $X"""
    if v is None or v == 0:
        return '$0'
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.1f} M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.1f} K"
    return f"${v:,.0f}"


def render_html(por_dia, por_canal, por_mod):
    ahora_clt = datetime.now(CHILE_TZ)
    fecha_hora = ahora_clt.strftime('%d-%b-%Y %H:%M CLT')

    # Totales
    bruta_total = sum(float(d[2] or 0) for d in por_dia)
    margen_total = sum(float(d[4] or 0) for d in por_dia)
    neta_total = sum(float(d[3] or 0) for d in por_dia)
    uds_total = sum(int(d[5] or 0) for d in por_dia)
    sos_total = sum(int(d[1] or 0) for d in por_dia)
    avance_pct = bruta_total / META_TOTAL if META_TOTAL else 0
    margen_pct = (margen_total / neta_total) if neta_total else 0

    # Día de hoy
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
        d = next((d for d in por_dia if d[0] == fecha), None)
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

    # Top canales
    rows_can = []
    for c in por_canal[:8]:
        canal_n = c[0] or '?'
        s = int(c[1] or 0)
        b = float(c[2] or 0)
        m = float(c[3] or 0)
        u = int(c[4] or 0)
        rows_can.append(
            f'<tr><td>{canal_n}</td><td align="right">{s:,}</td>'
            f'<td align="right">{u:,}</td><td align="right">{fmt_m(b)}</td>'
            f'<td align="right">{fmt_m(m)}</td></tr>'
        )
    tabla_can = '\n'.join(rows_can)

    # Modalidad
    rows_mod = []
    for m in por_mod:
        mod_n = m[0] or '?'
        s = int(m[1] or 0)
        b = float(m[2] or 0)
        mg = float(m[3] or 0)
        share = b / bruta_total if bruta_total else 0
        rows_mod.append(
            f'<tr><td>{mod_n}</td><td align="right">{s:,}</td>'
            f'<td align="right">{fmt_m(b)}</td><td align="right">{fmt_m(mg)}</td>'
            f'<td align="right">{share*100:.1f}%</td></tr>'
        )
    tabla_mod = '\n'.join(rows_mod)

    color_avance = '#16A34A' if avance_pct >= 0.8 else ('#EA580C' if avance_pct >= 0.4 else '#DC2626')

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body style="font-family:-apple-system,Segoe UI,sans-serif;max-width:720px;margin:auto;color:#1E293B">

<h2 style="margin:0 0 4px 0">🛍️ Pulso Cyber UnionX 2026</h2>
<p style="color:#64748B;margin:0 0 16px 0;font-size:0.9rem">{fecha_hora}</p>

<div style="background:#F1F5F9;border-left:4px solid #2563EB;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Acumulado Cyber</div>
  <div style="font-size:1.6rem;font-weight:700;color:#1E40AF;margin:2px 0">{fmt_m(bruta_total)}</div>
  <div style="font-size:0.85rem;color:#64748B">
    Meta total: {fmt_m(META_TOTAL)} ·
    <span style="color:{color_avance};font-weight:600">{avance_pct*100:.1f}% avance</span> ·
    Margen {fmt_m(margen_total)} ({margen_pct*100:.1f}%) ·
    {uds_total:,} uds · {sos_total:,} pedidos
  </div>
</div>

<div style="background:#FEF3C7;border-left:4px solid #EA580C;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Hoy ({ahora_clt.strftime('%a %d-%b')})</div>
  <div style="font-size:1.4rem;font-weight:700;color:#9A3412;margin:2px 0">{fmt_m(bruta_hoy)}</div>
  <div style="font-size:0.85rem;color:#64748B">
    Meta día: {fmt_m(meta_hoy)} ·
    <span style="font-weight:600">{avance_hoy*100:.1f}%</span> del día ·
    Margen {fmt_m(margen_hoy)} · {uds_hoy:,} uds
  </div>
</div>

<h3 style="margin:24px 0 8px 0;font-size:1rem">📅 Por día (Curva diaria)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">
  <th align="left">Día</th><th align="right">SOs</th><th align="right">Uds</th>
  <th align="right">Bruta</th><th align="right">Margen</th>
  <th align="right">Meta</th><th align="right">Avance</th>
</tr></thead>
<tbody>
{tabla_dia}
</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏆 Top canales acumulado</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">
  <th align="left">Canal</th><th align="right">SOs</th><th align="right">Uds</th>
  <th align="right">Bruta</th><th align="right">Margen</th>
</tr></thead>
<tbody>
{tabla_can}
</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">📦 Modalidad (Fulfillment vs Seller+Flex)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0">
  <th align="left">Modalidad</th><th align="right">SOs</th>
  <th align="right">Bruta</th><th align="right">Margen</th><th align="right">Share</th>
</tr></thead>
<tbody>
{tabla_mod}
</tbody></table>

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
    """Excel RAW del día actual (Chile) — desde turso."""
    ahora_clt = datetime.now(CHILE_TZ)
    hoy_str = ahora_clt.strftime('%Y-%m-%d')
    print(f"[2/4] Descargando Excel RAW {hoy_str}...", flush=True)
    # Importar el helper de enviar_excel_diario
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
    print(f"[3/4] Enviando email a {EMAIL_TO}...", flush=True)
    asunto_prefix = '[PRE-BORRADOR] ' if PREBORRADOR else ''
    flecha = '📈' if avance_pct >= 0.5 else '📉'
    asunto = (f"{asunto_prefix}🛍️ Cyber UnionX · {datetime.now(CHILE_TZ).strftime('%H:%M')} · "
              f"{fmt_m(bruta_hoy)} hoy · {fmt_m(bruta_total)} acum {flecha}")

    attachment = {
        'filename': f'Raw Cyber {hoy_str}.xlsx',
        'content': base64.b64encode(xlsx_bytes).decode(),
    }
    payload = {
        'from': EMAIL_FROM,
        'to': EMAIL_TO,
        'subject': asunto,
        'html': html,
        'attachments': [attachment],
    }
    r = requests.post(
        'https://api.resend.com/emails',
        json=payload,
        headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
        timeout=60,
    )
    if r.status_code >= 300:
        print(f"[ERROR] Resend: {r.status_code} {r.text}", flush=True)
        return False
    print(f"      [OK] enviado ({r.json().get('id','?')})", flush=True)
    return True


def main():
    if not _check_rango():
        return 0
    if not URL or not TOKEN or not RESEND_API_KEY:
        print("[ERROR] Faltan vars de entorno (LIBSQL_URL/TOKEN/RESEND_API_KEY)", flush=True)
        return 1

    por_dia, por_canal, por_mod = descargar_resumen()
    html, bruta_total, bruta_hoy, avance_pct = render_html(por_dia, por_canal, por_mod)
    xlsx_bytes, n_filas, hoy_str = descargar_excel_raw_hoy()
    ok = enviar(html, xlsx_bytes, n_filas, hoy_str, bruta_total, bruta_hoy, avance_pct)
    print("[4/4] Done." if ok else "[4/4] FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
