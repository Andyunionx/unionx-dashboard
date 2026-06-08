#!/usr/bin/env python3
"""Pulso Diario UnionX — mail Lun-Vie 08:00 CLT con acumulado mes + YoY + Excel RAW.

Contenido:
- KPIs mes en curso hasta ayer (venta, margen, %M, %meta, gap)
- YoY mismo período mes 2025
- Por día del mes (cada día con venta/margen)
- Top canales acumulado mes con %Meta (V06 Análisis Metas vs Resultados)
- Top marcas/categorías
- Adjunto: Excel RAW acumulado mes hasta ayer (sin venta_neta)

Destinatarios via env EMAIL_TO (default 12).
"""
import io
import os
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
from enviar_pulso_cyber import _enviar_via_gmail, fmt_m

CHILE_TZ = timezone(timedelta(hours=-4))
EMAIL_TO = [e.strip() for e in os.environ.get('EMAIL_TO','andres@unionx.cl').split(',') if e.strip()]
EMAIL_FROM = os.environ.get('EMAIL_FROM','onboarding@resend.dev')


def cargar_metas_v06():
    """Lee metas canal × mes desde data/planificacion/metas_canal_mensuales_2026.json
    (extraído de Análisis Contribución V06). Devuelve dict {(año, mes, canal): meta_venta}.
    Refrescar JSON cuando Gabriela actualice V06."""
    import json
    path = PROJECT_ROOT / 'data' / 'planificacion' / 'metas_canal_mensuales_2026.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    metas = {}
    for r in data.get('metas', []):
        k = (int(r['ano']), int(r['mes']), str(r['canal']).strip())
        metas[k] = metas.get(k, 0) + float(r.get('meta_venta', 0))
    return metas


def cargar_data():
    """Histórico (foto fija hasta 2026-06-01) + mes_actual (2-jun en adelante).
    Para evitar duplicados, mes_actual se filtra a >= CUTOFF_HISTORICO."""
    # Leer cutoff de views/shared.py (fuente única de verdad)
    cutoff = '2026-06-02'
    try:
        shared_path = PROJECT_ROOT / 'views' / 'shared.py'
        if shared_path.exists():
            for line in shared_path.read_text(encoding='utf-8').splitlines():
                if line.strip().startswith('CUTOFF_HISTORICO'):
                    # CUTOFF_HISTORICO = '2026-06-02'  # comentario
                    val = line.split('=', 1)[1].strip().split('#')[0].strip().strip("'\"")
                    if len(val) == 10 and val[4] == '-':
                        cutoff = val
                    break
    except Exception:
        pass

    hist = pd.read_parquet(PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet')
    mes = pd.read_parquet(PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet')
    cols = [c for c in mes.columns if c in hist.columns]
    # mes_actual SOLO >= cutoff (evita duplicar con foto fija del histórico)
    mes_fv = pd.to_datetime(mes['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    mes = mes[mes_fv >= cutoff].copy()
    df = pd.concat([hist[cols], mes[cols]], ignore_index=True)
    df['fv'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    df['fv_dt'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.date
    return df


def render_html(df):
    metas = cargar_metas_v06()
    ahora_clt = datetime.now(CHILE_TZ)
    hoy = ahora_clt.date()
    ayer = hoy - timedelta(days=1)
    mes_actual = ayer.month
    ano_actual = ayer.year
    primer_dia = date(ano_actual, mes_actual, 1)
    dias_acum = (ayer - primer_dia).days + 1

    # Acumulado mes en curso (1 al día anterior)
    df_mes = df[(df['fv_dt'] >= primer_dia) & (df['fv_dt'] <= ayer)].copy()

    # YoY: mismo período año pasado
    primer_dia_ly = date(ano_actual-1, mes_actual, 1)
    ayer_ly = primer_dia_ly + timedelta(days=dias_acum-1)
    df_ly = df[(df['fv_dt'] >= primer_dia_ly) & (df['fv_dt'] <= ayer_ly)].copy()

    # KPIs
    b_ty = df_mes['venta_bruta'].sum(); n_ty = df_mes['venta_neta'].sum()
    m_ty = df_mes['margen_front'].sum(); u_ty = int(df_mes['cantidad'].sum())
    s_ty = df_mes['pedido'].nunique()
    pm_ty = m_ty/n_ty*100 if n_ty else 0

    b_ly = df_ly['venta_bruta'].sum(); m_ly = df_ly['margen_front'].sum()
    n_ly = df_ly['venta_neta'].sum()
    pm_ly = m_ly/n_ly*100 if n_ly else 0

    yoy_v = (b_ty/b_ly-1)*100 if b_ly else 0
    yoy_m = (m_ty/m_ly-1)*100 if m_ly else 0

    # Meta mes total
    meta_mes = sum(v for (a,m,c), v in metas.items() if a==ano_actual and m==mes_actual)
    pct_meta = b_ty/meta_mes*100 if meta_mes else 0
    gap_meta = b_ty - meta_mes

    def cl(v): return '#16A34A' if v>=0 else '#DC2626'

    # Por día del mes
    g_dia = df_mes.groupby('fv').agg(
        sos=('pedido','nunique'),
        uds=('cantidad','sum'),
        bruta=('venta_bruta','sum'),
        margen=('margen_front','sum'),
        neta=('venta_neta','sum'),
    ).reset_index().sort_values('fv')
    dias_rows = ''
    for _, r in g_dia.iterrows():
        pm = r['margen']/r['neta']*100 if r['neta'] else 0
        dias_rows += f'<tr><td>{r["fv"]}</td><td align="right">{int(r["sos"]):,}</td><td align="right">{int(r["uds"]):,}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td></tr>'

    # Top canales con %Meta V06
    g_can = df_mes.groupby('canal').agg(
        sos=('pedido','nunique'),
        bruta=('venta_bruta','sum'),
        neta=('venta_neta','sum'),
        margen=('margen_front','sum'),
    ).reset_index().sort_values('bruta', ascending=False).head(15)
    can_rows = ''
    for _, r in g_can.iterrows():
        meta_c = metas.get((ano_actual, mes_actual, r['canal']), 0)
        pm = r['margen']/r['neta']*100 if r['neta'] else 0
        pmeta = r['bruta']/meta_c*100 if meta_c else 0
        color = '#16A34A' if pmeta >= 80 else ('#EA580C' if pmeta >= 40 else '#DC2626')
        can_rows += f'<tr><td>{r["canal"][:24]}</td><td align="right">{int(r["sos"]):,}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td><td align="right">{fmt_m(meta_c) if meta_c else "—"}</td><td align="right" style="color:{color}">{pmeta:.1f}%</td></tr>'

    # Top marcas
    g_mar = df_mes.groupby('marca').agg(
        bruta=('venta_bruta','sum'),
        neta=('venta_neta','sum'),
        margen=('margen_front','sum'),
    ).reset_index().sort_values('bruta', ascending=False).head(10)
    mar_rows = ''
    for _, r in g_mar.iterrows():
        pm = r['margen']/r['neta']*100 if r['neta'] else 0
        sh = r['bruta']/b_ty*100 if b_ty else 0
        ent = str(r['marca'] or '(s/m)')[:30]
        mar_rows += f'<tr><td>{ent}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td><td align="right">{sh:.1f}%</td></tr>'

    # Top categorías
    g_cat = df_mes.groupby('categoria_hijo').agg(
        bruta=('venta_bruta','sum'),
        neta=('venta_neta','sum'),
        margen=('margen_front','sum'),
    ).reset_index().sort_values('bruta', ascending=False).head(10)
    cat_rows = ''
    for _, r in g_cat.iterrows():
        pm = r['margen']/r['neta']*100 if r['neta'] else 0
        sh = r['bruta']/b_ty*100 if b_ty else 0
        ent = str(r['categoria_hijo'] or '(s/cat)')[:30]
        cat_rows += f'<tr><td>{ent}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td><td align="right">{sh:.1f}%</td></tr>'

    mes_nom = ['','Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'][mes_actual]
    color_av = '#16A34A' if pct_meta >= 80 else ('#EA580C' if pct_meta >= 40 else '#DC2626')

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body style="font-family:-apple-system,Segoe UI,sans-serif;max-width:900px;margin:auto;color:#1E293B">

<h2 style="margin:0 0 4px 0">📊 Pulso Diario UnionX · {mes_nom} {ano_actual}</h2>
<p style="color:#64748B;margin:0 0 16px 0;font-size:0.9rem">Acumulado al cierre {ayer.strftime("%d-%b-%Y")} ({dias_acum} días)</p>

<div style="background:#F1F5F9;border-left:4px solid #2563EB;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Acumulado mes (al {ayer.strftime("%d-%b")})</div>
  <div style="font-size:1.7rem;font-weight:700;color:#1E40AF;margin:2px 0">{fmt_m(b_ty)}</div>
  <div style="font-size:0.88rem;color:#64748B">
    Meta {mes_nom}: {fmt_m(meta_mes)} · <b style="color:{color_av}">{pct_meta:.1f}%</b> · gap {fmt_m(gap_meta)} ·
    Margen Front {fmt_m(m_ty)} ({pm_ty:.1f}%) · {u_ty:,} uds · {s_ty:,} pedidos
  </div>
</div>

<div style="background:#FEF3C7;border-left:4px solid #EA580C;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">📊 YoY mismo período mes 2025 ({primer_dia_ly} a {ayer_ly})</div>
  <table style="width:100%;margin-top:6px;font-size:0.88rem">
    <tr><td>{mes_nom} 2026 al día {dias_acum}:</td><td align="right"><b>{fmt_m(b_ty)}</b> bruta · {fmt_m(m_ty)} margen ({pm_ty:.1f}%)</td></tr>
    <tr><td>{mes_nom} 2025 mismo período:</td><td align="right">{fmt_m(b_ly)} bruta · {fmt_m(m_ly)} margen ({pm_ly:.1f}%)</td></tr>
    <tr style="border-top:1px solid #E2E8F0"><td>YoY:</td><td align="right">Venta <span style="color:{cl(yoy_v)};font-weight:600">{yoy_v:+.1f}%</span> · Margen <span style="color:{cl(yoy_m)};font-weight:600">{yoy_m:+.1f}%</span></td></tr>
  </table>
</div>

<h3 style="margin:24px 0 8px 0;font-size:1rem">📅 Por día — {mes_nom} {ano_actual}</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.85rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Día</th><th align="right">SOs</th><th align="right">Uds</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th></tr></thead>
<tbody>{dias_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏆 Top 15 canales acumulado mes (vs Meta V06)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.83rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Canal</th><th align="right">SOs</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">Meta</th><th align="right">%Meta</th></tr></thead>
<tbody>{can_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏷️ Top 10 marcas acumulado mes</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.83rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Marca</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">%Share</th></tr></thead>
<tbody>{mar_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">📂 Top 10 categorías acumulado mes</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.83rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Categoría</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">%Share</th></tr></thead>
<tbody>{cat_rows}</tbody></table>

<hr style="border:none;border-top:1px solid #E2E8F0;margin:24px 0">
<p style="font-size:0.85rem;color:#64748B">
🔗 Dashboard live: <a href="https://unionx-ventas.streamlit.app">unionx-ventas.streamlit.app</a><br>
📎 Adjunto: Excel RAW {mes_nom} acumulado al {ayer.strftime("%d-%b")} (sin venta_neta).<br>
Fuente: parquet local (Odoo + CMR + manuales) · Sin Delivery_*.
</p>

<style>td,th{{padding:6px 8px;border-bottom:1px solid #E2E8F0}}</style>
</body></html>"""
    return html, b_ty, ayer, mes_nom


def generar_excel_mes(df, ayer):
    """Excel RAW acumulado mes 1 al ayer (sin venta_neta)."""
    primer_dia = date(ayer.year, ayer.month, 1)
    df_mes = df[(df['fv_dt'] >= primer_dia) & (df['fv_dt'] <= ayer)].copy()
    drop_cols = [c for c in ['venta_neta','fv','fv_dt'] if c in df_mes.columns]
    df_mes = df_mes.drop(columns=drop_cols)
    buf = io.BytesIO()
    sheet = f'{ayer.strftime("%Y-%m")} acum {ayer.strftime("%d")}'
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df_mes.to_excel(w, index=False, sheet_name=sheet[:31])
    return buf.getvalue(), len(df_mes)


def main():
    df = cargar_data()
    print(f'[1/3] Data cargada: {len(df):,} filas total', flush=True)

    html, b_mes, ayer, mes_nom = render_html(df)
    print(f'[2/3] HTML: {len(html):,} bytes | acum {mes_nom}: {fmt_m(b_mes)}', flush=True)

    xlsx_bytes, n = generar_excel_mes(df, ayer)
    print(f'[3/3] Excel acumulado mes: {n:,} filas (hasta {ayer})', flush=True)

    asunto = f'📊 Pulso Diario · {mes_nom} acum al {ayer.strftime("%d")} · {fmt_m(b_mes)}'
    # Filename del adjunto: "Reporte Comercial - Ventas y Margen YYYY-MM-DD.xlsx"
    fname = f'Reporte Comercial - Ventas y Margen {ayer.strftime("%Y-%m-%d")}'
    msg_id = _enviar_via_gmail(asunto, html, xlsx_bytes, fname, EMAIL_TO)
    print(f'[OK] enviado msg_id={msg_id}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
