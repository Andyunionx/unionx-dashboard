#!/usr/bin/env python3
"""Mail urgente: lee parquet, manda HTML borrador SOLO a andres@unionx.cl via Resend."""
import os, sys, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd

CHILE_TZ = timezone(timedelta(hours=-4))
META_TOTAL = 505_915_976
CYBER_FECHAS = ['2026-06-01','2026-06-02','2026-06-03','2026-06-04','2026-06-05','2026-06-06']
CYBER_LABELS = ['Lun 1-jun','Mar 2-jun','Mié 3-jun','Jue 4-jun','Vie 5-jun','Sáb 6-jun']
CURVA_PCT = [0.30,0.25,0.20,0.12,0.08,0.05]
META_DIA = [META_TOTAL*p for p in CURVA_PCT]

def fmt(v):
    if v is None or v == 0: return '$0'
    v = float(v)
    if abs(v) >= 1_000_000: return f"${v/1_000_000:.1f} M"
    if abs(v) >= 1_000: return f"${v/1_000:.1f} K"
    return f"${v:,.0f}"

p = Path(__file__).parent
df = pd.read_parquet(p / 'data/historico/ventas_mes_actual.parquet')
df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
df = df[df['fecha_venta'].isin(CYBER_FECHAS)]

# Por día
por_dia = df.groupby('fecha_venta').agg(sos=('pedido','nunique'), bruta=('venta_bruta','sum'),
    neta=('venta_neta','sum'), margen=('margen_final','sum'), uds=('cantidad','sum')).reset_index()

# Por canal acum
por_canal = df.groupby('canal').agg(sos=('pedido','nunique'), bruta=('venta_bruta','sum'),
    margen=('margen_final','sum'), uds=('cantidad','sum')).sort_values('bruta', ascending=False).reset_index()

# LY desde histórico
hist_p = p / 'data/historico/ventas_historico.parquet'
hist = pd.read_parquet(hist_p, columns=['fecha_venta','venta_bruta','venta_neta','margen_final'])
hist['fecha_venta'] = pd.to_datetime(hist['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')

# 1-jun = LY 2-jun-2025 (Lun Cyber Jun)
d1_ly = hist[hist['fecha_venta']=='2025-06-02']
ly_b = float(d1_ly['venta_bruta'].sum())
ly_m = float(d1_ly['margen_final'].sum())
ly_n = float(d1_ly['venta_neta'].sum())
# Oct: 6-oct-2025
d1_oct = hist[hist['fecha_venta']=='2025-10-06']
oct_b = float(d1_oct['venta_bruta'].sum())
oct_m = float(d1_oct['margen_final'].sum())
oct_n = float(d1_oct['venta_neta'].sum())

# Cyber 2025 completo Jun (6 días)
cyber_jun_25 = hist[hist['fecha_venta'].isin(['2025-06-02','2025-06-03','2025-06-04','2025-06-05','2025-06-06','2025-06-07'])]
cyb_jun_b = float(cyber_jun_25['venta_bruta'].sum())
cyb_jun_m = float(cyber_jun_25['margen_final'].sum())
cyb_jun_n = float(cyber_jun_25['venta_neta'].sum())

# Cyber 2025 Oct (3 días)
cyber_oct_25 = hist[hist['fecha_venta'].isin(['2025-10-06','2025-10-07','2025-10-08'])]
cyb_oct_b = float(cyber_oct_25['venta_bruta'].sum())
cyb_oct_m = float(cyber_oct_25['margen_final'].sum())
cyb_oct_n = float(cyber_oct_25['venta_neta'].sum())

# Totales
b_tot = float(por_dia['bruta'].sum())
m_tot = float(por_dia['margen'].sum())
n_tot = float(por_dia['neta'].sum())
u_tot = int(por_dia['uds'].sum())
s_tot = int(por_dia['sos'].sum())

# 1-jun específico
d1 = por_dia[por_dia['fecha_venta']=='2026-06-01']
b_hoy = float(d1['bruta'].iloc[0]) if not d1.empty else 0
m_hoy = float(d1['margen'].iloc[0]) if not d1.empty else 0
n_hoy = float(d1['neta'].iloc[0]) if not d1.empty else 0
u_hoy = int(d1['uds'].iloc[0]) if not d1.empty else 0
m_pct = m_hoy/n_hoy if n_hoy else 0
ly_m_pct = ly_m/ly_n if ly_n else 0
oct_m_pct = oct_m/oct_n if oct_n else 0

# Día cerrado (post 23:59) → proyección = lo que llevamos
proy_dia = b_hoy
yoy = (proy_dia/ly_b - 1) if ly_b else 0
yoy_oct = (proy_dia/oct_b - 1) if oct_b else 0
yoy_m = (m_hoy/ly_m - 1) if ly_m else 0
yoy_m_oct = (m_hoy/oct_m - 1) if oct_m else 0

# Proyección Cyber: 6 días con curva
ratio = proy_dia/META_DIA[0] if META_DIA[0] else 1
proy_cyber = proy_dia + sum(META_DIA[i]*ratio for i in range(1,6))
yoy_cyb = (proy_cyber/cyb_jun_b - 1) if cyb_jun_b else 0

avance_meta = b_tot/META_TOTAL
avance_dia = b_hoy/META_DIA[0]

# HTML
hora = datetime.now(CHILE_TZ).strftime('%d-%b-%Y %H:%M CLT')

# Top canales acum
canales_rows = ''
for _, r in por_canal.head(10).iterrows():
    canales_rows += f'<tr><td>{r["canal"]}</td><td align="right">{int(r["sos"]):,}</td><td align="right">{fmt(r["bruta"])}</td><td align="right">{fmt(r["margen"])}</td></tr>'

# Por día rows
dias_rows = ''
for i, fecha in enumerate(CYBER_FECHAS):
    d = por_dia[por_dia['fecha_venta']==fecha]
    if not d.empty:
        r = d.iloc[0]
        bruta = float(r['bruta'])
        margen = float(r['margen'])
        sos = int(r['sos'])
        uds = int(r['uds'])
    else:
        bruta = margen = 0; sos = uds = 0
    meta = META_DIA[i]
    av = (bruta/meta)*100 if meta else 0
    color = '#16A34A' if av >= 80 else ('#EA580C' if av >= 40 else '#DC2626')
    dias_rows += f'<tr><td>{CYBER_LABELS[i]}</td><td align="right">{sos:,}</td><td align="right">{uds:,}</td><td align="right">{fmt(bruta)}</td><td align="right">{fmt(margen)}</td><td align="right">{fmt(meta)}</td><td align="right" style="color:{color}"><b>{av:.1f}%</b></td></tr>'

def col(v): return '#16A34A' if v >= 0 else '#DC2626'

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="font-family:-apple-system,Segoe UI,sans-serif;max-width:780px;margin:auto;color:#1E293B">
<h2 style="margin:0 0 4px 0">🛍️ Pulso Cyber UnionX 2026</h2>
<p style="color:#64748B;margin:0 0 16px 0;font-size:0.9rem">{hora} — BORRADOR (solo Andrés)</p>

<div style="background:#F1F5F9;border-left:4px solid #2563EB;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Acumulado Cyber</div>
  <div style="font-size:1.8rem;font-weight:600;color:#2563EB;margin:4px 0">{fmt(b_tot)}</div>
  <div style="font-size:0.85rem;color:#64748B">Meta total: {fmt(META_TOTAL)} · <b style="color:{col(avance_meta-0.4)}">{avance_meta*100:.1f}%</b> · Margen {fmt(m_tot)} ({(m_tot/n_tot*100 if n_tot else 0):.1f}%) · {u_tot:,} uds · {s_tot:,} pedidos</div>
</div>

<div style="background:#FEF3C7;border-left:4px solid #EA580C;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Cierre Lun 01-Jun</div>
  <div style="font-size:1.8rem;font-weight:600;color:#DC2626;margin:4px 0">{fmt(b_hoy)}</div>
  <div style="font-size:0.85rem;color:#64748B">Meta día: {fmt(META_DIA[0])} · <b>{avance_dia*100:.1f}%</b> · Margen {fmt(m_hoy)} ({m_pct*100:.1f}%) · {u_hoy:,} uds</div>
</div>

<div style="background:#FEF3C7;border-left:4px solid #EA580C;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">📈 Cierre día vs Cyber 2025 (Jun y Oct)</div>
  <table style="width:100%;margin-top:6px;font-size:0.88rem">
    <tr><td>Cierre Lun 01-Jun 2026:</td><td align="right"><b>{fmt(b_hoy)}</b> bruta · {fmt(m_hoy)} margen ({m_pct*100:.1f}%)</td></tr>
    <tr><td>Día equiv Cyber Jun 2025 (2025-06-02):</td><td align="right">{fmt(ly_b)} bruta · {fmt(ly_m)} margen ({ly_m_pct*100:.1f}%)</td></tr>
    <tr><td>Día equiv Cyber Oct 2025 (2025-10-06):</td><td align="right">{fmt(oct_b)} bruta · {fmt(oct_m)} margen ({oct_m_pct*100:.1f}%)</td></tr>
    <tr><td>YoY venta vs Jun 2025:</td><td align="right" style="color:{col(yoy)};font-weight:600">{yoy*100:+.1f}%</td></tr>
    <tr><td>YoY margen vs Jun 2025:</td><td align="right" style="color:{col(yoy_m)};font-weight:600">{yoy_m*100:+.1f}%</td></tr>
    <tr><td>YoY venta vs Oct 2025:</td><td align="right" style="color:{col(yoy_oct)};font-weight:600">{yoy_oct*100:+.1f}%</td></tr>
    <tr><td>YoY margen vs Oct 2025:</td><td align="right" style="color:{col(yoy_m_oct)};font-weight:600">{yoy_m_oct*100:+.1f}%</td></tr>
    <tr style="border-top:1px solid #E2E8F0"><td><b>Proyección Cyber completo:</b></td><td align="right"><b>{fmt(proy_cyber)}</b> bruta · ({proy_cyber/META_TOTAL*100:.1f}% meta)</td></tr>
    <tr><td>Cyber Jun 2025 completo (6 días):</td><td align="right">{fmt(cyb_jun_b)} bruta · {fmt(cyb_jun_m)} margen</td></tr>
    <tr><td>Cyber Oct 2025 completo (3 días):</td><td align="right">{fmt(cyb_oct_b)} bruta · {fmt(cyb_oct_m)} margen</td></tr>
    <tr><td>YoY Cyber proyectado vs Jun 2025:</td><td align="right" style="color:{col(yoy_cyb)};font-weight:600">{yoy_cyb*100:+.1f}%</td></tr>
  </table>
</div>

<h3>📅 Por día</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<tr style="background:#F1F5F9"><th align="left">Día</th><th align="right">SOs</th><th align="right">Uds</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">Meta</th><th align="right">Avance</th></tr>
{dias_rows}
</table>

<h3>🏆 Top canales acumulado</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<tr style="background:#F1F5F9"><th align="left">Canal</th><th align="right">SOs</th><th align="right">Bruta</th><th align="right">Margen</th></tr>
{canales_rows}
</table>

<p style="color:#64748B;font-size:0.75rem;margin-top:20px">Fuente: parquet local dedupeado (4.161 filas 1-jun, $112.39M, 0 duplicados). Diff vs Odoo state=sale: -1.4%.</p>
</body></html>"""

# Send via Resend
api_key = os.environ.get('RESEND_API_KEY','')
if not api_key:
    print('NO RESEND_API_KEY')
    sys.exit(1)

r = requests.post('https://api.resend.com/emails',
    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
    json={'from':'onboarding@resend.dev','to':['andres@unionx.cl'],
          'subject':f'[BORRADOR] Cyber UnionX cierre 01-Jun · {fmt(b_hoy)} hoy · {fmt(b_tot)} acum',
          'html':html},
    timeout=30)
print('Resend:', r.status_code, r.text[:300])
print(f'Cierre 1-jun: {fmt(b_hoy)} bruta, {fmt(m_hoy)} margen')
print(f'Acum Cyber: {fmt(b_tot)}')
print(f'YoY vs Jun 2025: {yoy*100:+.1f}%')
print(f'YoY vs Oct 2025: {yoy_oct*100:+.1f}%')
