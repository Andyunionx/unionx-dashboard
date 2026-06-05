#!/usr/bin/env python3
"""Cierre Cyber UnionX 2026 — recap post-evento (Lun 1-jun a Sáb 6-jun).
Dispara Lun 8-jun 08:00 CLT (UTC 12). One-shot.

Mail a los 12 destinatarios con:
- KPIs Cyber total + por día
- vs Meta total ($505.9M) + por canal/marca/categoría
- Top SKUs venta + margen
- YoY vs Cyber Jun 2025 (6d) + Oct 2025 ventana 6d
- LN breakdown
"""
import io
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
from enviar_pulso_cyber import _enviar_via_gmail, fmt_m

CHILE_TZ = timezone(timedelta(hours=-4))
META_TOTAL = 505_915_976
CYBER_FECHAS = ['2026-06-01','2026-06-02','2026-06-03','2026-06-04','2026-06-05','2026-06-06']
CYBER_LABELS = ['Lun 1-jun','Mar 2-jun','Mié 3-jun','Jue 4-jun','Vie 5-jun','Sáb 6-jun']
CURVA = [0.30,0.25,0.20,0.12,0.08,0.05]
META_DIA = [META_TOTAL*p for p in CURVA]
CYBER_2025_JUN = ['2025-06-02','2025-06-03','2025-06-04','2025-06-05','2025-06-06','2025-06-07']
CYBER_2025_OCT = ['2025-10-06','2025-10-07','2025-10-08','2025-10-09','2025-10-10','2025-10-11']

EMAIL_TO = [e.strip() for e in os.environ.get('EMAIL_TO','andres@unionx.cl').split(',') if e.strip()]
EMAIL_FROM = os.environ.get('EMAIL_FROM','onboarding@resend.dev')


def cargar_metas():
    """Lee metas_canal + metas_marca + metas_categoria del plan_cyber_2026.json."""
    path = PROJECT_ROOT / 'data' / 'planificacion' / 'plan_cyber_2026.json'
    if not path.exists():
        return {}, {}, {}
    p = json.loads(path.read_text(encoding='utf-8'))
    def _k(s): return str(s or '').strip().upper()
    mc = {m['canal']: float(m['meta_venta']) for m in p.get('metas_canal', [])}
    mm = {_k(m['marca']): float(m['meta_venta']) for m in p.get('metas_marca', [])}
    mk = {_k(m['categoria']): float(m['meta_venta']) for m in p.get('metas_categoria', [])}
    return mc, mm, mk


def cargar_data_cyber():
    """Combina histórico (1-jun) + mes_actual (2-jun+). Solo días Cyber."""
    hist = pd.read_parquet(PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet')
    mes = pd.read_parquet(PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet')
    hist['fv'] = pd.to_datetime(hist['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    mes['fv'] = pd.to_datetime(mes['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    h_cy = hist[hist['fv'].isin(CYBER_FECHAS)]
    m_cy = mes[mes['fv'].isin(CYBER_FECHAS)]
    cols = [c for c in m_cy.columns if c in h_cy.columns]
    df = pd.concat([h_cy[cols], m_cy[cols]], ignore_index=True)
    df['fv'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    return df, hist


def render_cierre_html(df, hist):
    metas_canal, metas_marca, metas_cat = cargar_metas()
    ahora = datetime.now(CHILE_TZ).strftime('%d-%b-%Y %H:%M CLT')

    # KPIs totales Cyber
    b_tot = df['venta_bruta'].sum()
    n_tot = df['venta_neta'].sum()
    m_tot = df['margen_front'].sum()
    u_tot = int(df['cantidad'].sum())
    s_tot = df['pedido'].nunique()
    pct_meta = b_tot/META_TOTAL*100
    pct_m = m_tot/n_tot*100 if n_tot else 0

    # Por día
    g_dia = df.groupby('fv').agg(
        sos=('pedido','nunique'),
        uds=('cantidad','sum'),
        bruta=('venta_bruta','sum'),
        margen=('margen_front','sum'),
        neta=('venta_neta','sum'),
    ).reset_index().sort_values('fv')

    dias_rows = ''
    for i, fecha in enumerate(CYBER_FECHAS):
        r = g_dia[g_dia['fv']==fecha]
        if len(r):
            b = float(r['bruta'].iloc[0]); ma = float(r['margen'].iloc[0]); n = float(r['neta'].iloc[0])
            sos = int(r['sos'].iloc[0]); uds = int(r['uds'].iloc[0])
        else:
            b=ma=n=0; sos=uds=0
        meta = META_DIA[i]
        av = b/meta*100 if meta else 0
        pm = ma/n*100 if n else 0
        color = '#16A34A' if av >= 80 else ('#EA580C' if av >= 40 else '#DC2626')
        dias_rows += f'<tr><td>{CYBER_LABELS[i]}</td><td align="right">{sos:,}</td><td align="right">{uds:,}</td><td align="right">{fmt_m(b)}</td><td align="right">{fmt_m(ma)}</td><td align="right">{pm:.1f}%</td><td align="right">{fmt_m(meta)}</td><td align="right" style="color:{color};font-weight:600">{av:.1f}%</td></tr>'

    # Top canales con %Meta canal
    g_can = df.groupby('canal').agg(
        sos=('pedido','nunique'),
        bruta=('venta_bruta','sum'),
        neta=('venta_neta','sum'),
        margen=('margen_front','sum'),
    ).reset_index().sort_values('bruta', ascending=False).head(15)
    can_rows = ''
    for _, r in g_can.iterrows():
        meta = metas_canal.get(r['canal'], 0)
        pm = r['margen']/r['neta']*100 if r['neta'] else 0
        pmeta = r['bruta']/meta*100 if meta else 0
        color = '#16A34A' if pmeta >= 80 else ('#EA580C' if pmeta >= 40 else '#DC2626')
        can_rows += f'<tr><td>{r["canal"][:24]}</td><td align="right">{int(r["sos"]):,}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td><td align="right">{fmt_m(meta) if meta else "—"}</td><td align="right" style="color:{color}">{pmeta:.1f}%</td></tr>'

    # Top marcas con %Meta marca
    def _matrix(col, meta_dict, label):
        g = df.groupby(col).agg(
            bruta=('venta_bruta','sum'),
            neta=('venta_neta','sum'),
            margen=('margen_front','sum'),
        ).reset_index().sort_values('bruta', ascending=False).head(10)
        rows = ''
        for _, r in g.iterrows():
            ent = str(r[col] or '').strip()
            meta = meta_dict.get(ent.upper(), 0)
            pm = r['margen']/r['neta']*100 if r['neta'] else 0
            pmeta = r['bruta']/meta*100 if meta else 0
            color = '#16A34A' if pmeta >= 80 else ('#EA580C' if pmeta >= 40 else '#DC2626')
            sh = r['bruta']/b_tot*100 if b_tot else 0
            rows += f'<tr><td>{ent[:30]}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td><td align="right">{sh:.1f}%</td><td align="right">{fmt_m(meta) if meta else "—"}</td><td align="right" style="color:{color}">{pmeta:.1f}%</td></tr>'
        return rows

    marcas_rows = _matrix('marca', metas_marca, 'marca')
    cats_rows = _matrix('categoria_hijo', metas_cat, 'categoría')

    # Top 10 SKUs
    g_sku = df.groupby(['sku','producto']).agg(
        uds=('cantidad','sum'),
        bruta=('venta_bruta','sum'),
        neta=('venta_neta','sum'),
        margen=('margen_front','sum'),
    ).reset_index()
    g_sku['pctm'] = g_sku.apply(lambda r: r['margen']/r['neta']*100 if r['neta'] else 0, axis=1)

    def _sku_table(ord_col):
        top = g_sku.sort_values(ord_col, ascending=False).head(10)
        rows = ''
        for _, r in top.iterrows():
            sh_v = r['bruta']/b_tot*100 if b_tot else 0
            sh_m = r['margen']/m_tot*100 if m_tot else 0
            rows += f'<tr><td>{str(r["sku"])[:14]}</td><td>{str(r["producto"])[:50]}</td><td align="right">{int(r["uds"]):,}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{r["pctm"]:.1f}%</td><td align="right">{sh_v:.1f}%</td><td align="right">{sh_m:.1f}%</td></tr>'
        return rows

    skus_venta_rows = _sku_table('bruta')
    skus_margen_rows = _sku_table('margen')

    # YoY
    hist['fv'] = pd.to_datetime(hist['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    cyb_jun_25 = hist[hist['fv'].isin(CYBER_2025_JUN)]
    cyb_oct_25 = hist[hist['fv'].isin(CYBER_2025_OCT)]
    b25j = cyb_jun_25['venta_bruta'].sum(); m25j = cyb_jun_25['margen_front'].sum(); n25j = cyb_jun_25['venta_neta'].sum()
    b25o = cyb_oct_25['venta_bruta'].sum(); m25o = cyb_oct_25['margen_front'].sum(); n25o = cyb_oct_25['venta_neta'].sum()
    yoy_jun_v = (b_tot/b25j-1)*100 if b25j else 0
    yoy_jun_m = (m_tot/m25j-1)*100 if m25j else 0
    yoy_oct_v = (b_tot/b25o-1)*100 if b25o else 0
    yoy_oct_m = (m_tot/m25o-1)*100 if m25o else 0
    def cl(v): return '#16A34A' if v>=0 else '#DC2626'

    # Línea de negocio
    g_ln = df.groupby('tipo_negocio').agg(
        bruta=('venta_bruta','sum'),
        neta=('venta_neta','sum'),
        margen=('margen_front','sum'),
    ).reset_index().sort_values('bruta', ascending=False)
    ln_rows = ''
    for _, r in g_ln.iterrows():
        if r['bruta']==0: continue
        pm = r['margen']/r['neta']*100 if r['neta'] else 0
        sh = r['bruta']/b_tot*100 if b_tot else 0
        ln_rows += f'<tr><td>{str(r["tipo_negocio"] or "(s/LN)")[:24]}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td><td align="right">{sh:.1f}%</td></tr>'

    # Modalidad
    df['_mod'] = df['bodega'].astype(str).str.lower().str.startswith('bodega fulfillment').map({True:'Fulfillment',False:'Seller+Flex'})
    g_mod = df.groupby('_mod').agg(
        sos=('pedido','nunique'),
        bruta=('venta_bruta','sum'),
        margen=('margen_front','sum'),
    ).reset_index()
    mod_rows = ''
    for _, r in g_mod.iterrows():
        sh = r['bruta']/b_tot*100 if b_tot else 0
        mod_rows += f'<tr><td>{r["_mod"]}</td><td align="right">{int(r["sos"]):,}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{sh:.1f}%</td></tr>'

    color_avance = '#16A34A' if pct_meta >= 80 else ('#EA580C' if pct_meta >= 40 else '#DC2626')

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body style="font-family:-apple-system,Segoe UI,sans-serif;max-width:900px;margin:auto;color:#1E293B">

<h2 style="margin:0 0 4px 0">🎯 Cierre Cyber UnionX 2026</h2>
<p style="color:#64748B;margin:0 0 16px 0;font-size:0.9rem">Lun 1-Jun a Sáb 6-Jun · Reporte generado {ahora}</p>

<div style="background:#F1F5F9;border-left:4px solid #2563EB;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Resultado Cyber 6 días</div>
  <div style="font-size:1.8rem;font-weight:700;color:#1E40AF;margin:2px 0">{fmt_m(b_tot)}</div>
  <div style="font-size:0.9rem;color:#64748B">
    Meta: {fmt_m(META_TOTAL)} · <b style="color:{color_avance}">{pct_meta:.1f}%</b> ·
    Margen Front {fmt_m(m_tot)} ({pct_m:.1f}%) · {u_tot:,} uds · {s_tot:,} pedidos
  </div>
</div>

<div style="background:#FEF3C7;border-left:4px solid #EA580C;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">📊 YoY vs Cyber 2025</div>
  <table style="width:100%;margin-top:6px;font-size:0.88rem">
    <tr><td>Cyber Jun 2025 (6d):</td><td align="right">{fmt_m(b25j)} bruta · {fmt_m(m25j)} margen ({(m25j/n25j*100 if n25j else 0):.1f}%)</td></tr>
    <tr><td>Cyber Oct 2025 (ventana 6d Lun-Sáb):</td><td align="right">{fmt_m(b25o)} bruta · {fmt_m(m25o)} margen ({(m25o/n25o*100 if n25o else 0):.1f}%)</td></tr>
    <tr style="border-top:1px solid #E2E8F0"><td>YoY vs Jun 2025:</td><td align="right">Venta <span style="color:{cl(yoy_jun_v)};font-weight:600">{yoy_jun_v:+.1f}%</span> · Margen <span style="color:{cl(yoy_jun_m)};font-weight:600">{yoy_jun_m:+.1f}%</span></td></tr>
    <tr><td>YoY vs Oct 2025:</td><td align="right">Venta <span style="color:{cl(yoy_oct_v)};font-weight:600">{yoy_oct_v:+.1f}%</span> · Margen <span style="color:{cl(yoy_oct_m)};font-weight:600">{yoy_oct_m:+.1f}%</span></td></tr>
  </table>
</div>

<h3 style="margin:24px 0 8px 0;font-size:1rem">📅 Por día Cyber</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Día</th><th align="right">SOs</th><th align="right">Uds</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">Meta</th><th align="right">%Meta</th></tr></thead>
<tbody>{dias_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏆 Top 15 canales (acumulado Cyber)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.85rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Canal</th><th align="right">SOs</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">Meta</th><th align="right">%Meta</th></tr></thead>
<tbody>{can_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏷️ Top 10 marcas (acumulado Cyber)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.85rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Marca</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">%Sh</th><th align="right">Meta</th><th align="right">%Meta</th></tr></thead>
<tbody>{marcas_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">📂 Top 10 categorías (acumulado Cyber)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.85rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Categoría</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">%Sh</th><th align="right">Meta</th><th align="right">%Meta</th></tr></thead>
<tbody>{cats_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">⭐ Top 10 SKUs por VENTA bruta</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.8rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">SKU</th><th align="left">Producto</th><th align="right">Uds</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">%Sh V</th><th align="right">%Sh M</th></tr></thead>
<tbody>{skus_venta_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">💰 Top 10 SKUs por MARGEN front</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.8rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">SKU</th><th align="left">Producto</th><th align="right">Uds</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">%Sh V</th><th align="right">%Sh M</th></tr></thead>
<tbody>{skus_margen_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏢 Línea de Negocio</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">LN</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">%Share</th></tr></thead>
<tbody>{ln_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">📦 Modalidad (Fulfillment vs Seller+Flex)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.88rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Modalidad</th><th align="right">SOs</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">Share</th></tr></thead>
<tbody>{mod_rows}</tbody></table>

<hr style="border:none;border-top:1px solid #E2E8F0;margin:24px 0">
<p style="font-size:0.85rem;color:#64748B">
🔗 Dashboard live: <a href="https://unionx-ventas.streamlit.app/ventas-cyber">unionx-ventas.streamlit.app/ventas-cyber</a><br>
📎 Adjunto: Excel RAW completo Cyber (1-jun a 6-jun, sin venta_neta).<br>
Fuente: parquet local (Odoo + CMR + manuales) · Sin Delivery_*.
</p>

<style>td,th{{padding:6px 8px;border-bottom:1px solid #E2E8F0}}</style>
</body></html>"""
    return html


def generar_excel_cyber(df):
    """Excel RAW Cyber completo (6 días), sin venta_neta."""
    df = df.copy()
    if 'venta_neta' in df.columns:
        df = df.drop(columns=['venta_neta'])
    if 'fv' in df.columns:
        df = df.drop(columns=['fv'])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Cyber 1-6 jun')
    return buf.getvalue(), len(df)


def main():
    df, hist = cargar_data_cyber()
    print(f'[1/3] Cyber: {len(df):,} filas, ${df["venta_bruta"].sum()/1e6:.2f}M bruta', flush=True)

    html = render_cierre_html(df, hist)
    print(f'[2/3] HTML generado: {len(html):,} bytes', flush=True)

    xlsx_bytes, n_xlsx = generar_excel_cyber(df)
    print(f'[3/3] Excel Cyber RAW: {n_xlsx:,} filas', flush=True)

    b_tot = df['venta_bruta'].sum()
    asunto = f'🎯 Cierre Cyber UnionX 2026 · {fmt_m(b_tot)} · {b_tot/META_TOTAL*100:.1f}% meta'
    msg_id = _enviar_via_gmail(asunto, html, xlsx_bytes, 'cyber_1-6_jun', EMAIL_TO)
    print(f'[OK] enviado msg_id={msg_id}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
