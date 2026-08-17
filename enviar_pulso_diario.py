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


# La meta de la base (V06 "Resultado vs Presupuesto") está en venta NETA.
# El pulso muestra venta BRUTA, así que la meta se lleva a bruta con el IVA
# (en los datos la bruta es exactamente neta × 1.19). Así el %Meta y el gap
# quedan bruta vs bruta. Si cambia el régimen de IVA, ajustar acá.
FACTOR_IVA_BRUTA = 1.19


def cargar_metas_v06():
    """Lee metas canal × mes desde data/planificacion/metas_canal_mensuales_2026.json
    (extraído de Análisis Contribución V06, pestaña 'Resultado vs Presupuesto').
    La meta del JSON está en NETA y se devuelve en BRUTA (× FACTOR_IVA_BRUTA)
    para comparar contra la venta bruta del pulso. Devuelve {(año, mes, canal): meta_bruta}.
    Refrescar JSON cuando Gabriela actualice V06."""
    import json
    path = PROJECT_ROOT / 'data' / 'planificacion' / 'metas_canal_mensuales_2026.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    metas = {}
    for r in data.get('metas', []):
        k = (int(r['ano']), int(r['mes']), str(r['canal']).strip())
        metas[k] = metas.get(k, 0) + float(r.get('meta_venta', 0)) * FACTOR_IVA_BRUTA
    return metas


def _norm_neg(s):
    import unicodedata
    s = str(s or '').strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def cargar_metas_negocio():
    """Meta de venta por (año, mes, línea de negocio) en BRUTA (× IVA), normalizada.
    Devuelve {(año, mes, negocio_norm): meta_bruta}."""
    import json
    path = PROJECT_ROOT / 'data' / 'planificacion' / 'metas_canal_mensuales_2026.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    metas = {}
    for r in data.get('metas', []):
        k = (int(r['ano']), int(r['mes']), _norm_neg(r.get('negocio', '')))
        metas[k] = metas.get(k, 0) + float(r.get('meta_venta', 0)) * FACTOR_IVA_BRUTA
    return metas


def cargar_presupuesto_corp_distrib():
    """Presupuesto mensual de Distribución y Corporativo (doc de Andrés), en NETA →
    BRUTA (×IVA). Devuelve {(2026, mes, negocio_norm): meta_bruta}. Sobrescribe las
    metas V06 para esas dos líneas (es la fuente autoritativa de sus presupuestos)."""
    path = PROJECT_ROOT / 'data' / 'Presupuesto Venta Distribución y Corporativo 2026.xlsx'
    if not path.exists():
        return {}
    MES_NUM = {'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
               'jul': 7, 'ago': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12}
    try:
        df = pd.read_excel(path, sheet_name=0)
    except Exception:
        return {}
    col_mes = {c: MES_NUM[str(c).strip().lower()[:3]] for c in df.columns
               if str(c).strip().lower()[:3] in MES_NUM}
    out = {}
    for _, r in df.iterrows():
        lin = str(r.get('Línea de Negocio', '') or '').strip()
        if lin not in ('Distribución', 'Corporativo'):
            continue
        for c, mnum in col_mes.items():
            v = pd.to_numeric(r.get(c), errors='coerce')
            if pd.notna(v) and v > 0:
                out[(2026, mnum, _norm_neg(lin))] = float(v) * FACTOR_IVA_BRUTA
    return out


def _yoy_cell(ty, ly):
    """Celda HTML de YoY (variación vs mismo período 2025). 'nuevo' si no hubo LY."""
    if not ly or ly <= 0:
        return '<td align="right" style="color:#94A3B8">nuevo</td>'
    v = (ty / ly - 1) * 100
    c = '#16A34A' if v >= 0 else '#DC2626'
    return f'<td align="right" style="color:{c};font-weight:600">{v:+.1f}%</td>'


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
    metas_neg = cargar_metas_negocio()
    metas_neg.update(cargar_presupuesto_corp_distrib())  # apertura Corp/Distrib (doc de Andrés)
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
    # YoY por breakdown: venta bruta LY (2025 mismo período) por llave. Misma base
    # que el pivot vivo (2026 vs 2025, mismo parquet).
    _lyn = df_ly.assign(_n=df_ly['tipo_negocio'].apply(_norm_neg))
    ly_neg = _lyn.groupby('_n')['venta_bruta'].sum().to_dict()
    ly_neg_m = _lyn.groupby('_n')['margen_front'].sum().to_dict()
    ly_can = df_ly.groupby('canal')['venta_bruta'].sum().to_dict()
    ly_can_m = df_ly.groupby('canal')['margen_front'].sum().to_dict()
    ly_mar = df_ly.groupby('marca')['venta_bruta'].sum().to_dict()
    ly_mar_m = df_ly.groupby('marca')['margen_front'].sum().to_dict()
    ly_cat = df_ly.groupby('categoria_hijo')['venta_bruta'].sum().to_dict()
    ly_cat_m = df_ly.groupby('categoria_hijo')['margen_front'].sum().to_dict()

    # KPIs
    b_ty = df_mes['venta_bruta'].sum(); n_ty = df_mes['venta_neta'].sum()
    m_ty = df_mes['margen_front'].sum(); u_ty = int(df_mes['cantidad'].sum())
    s_ty = df_mes['pedido'].nunique()
    pm_ty = m_ty/n_ty*100 if n_ty else 0
    # Devoluciones (NC) del mes: venta_bruta negativa. b_ty ya es NETO de ellas.
    dev_ty = df_mes.loc[df_mes['tipo_movimiento'] == 'Devolución', 'venta_bruta'].sum()
    venta_gross_ty = b_ty - dev_ty  # venta bruta ANTES de devoluciones

    # ── Margen Final (ago-2026+): margen front − comisión − logística (marketing FUERA).
    # comisión/logística vienen por fila del extract (Odoo real + matriz/tarifario);
    # margen_final = margen_front − com − log. Ver memoria channel_fee_structures.
    for _c in ('comision', 'logistica', 'margen_final'):
        if _c in df_mes.columns:
            df_mes[_c] = pd.to_numeric(df_mes[_c], errors='coerce').fillna(0)
        else:
            df_mes[_c] = 0.0
    com_ty = df_mes['comision'].sum()
    log_ty = df_mes['logistica'].sum()
    mfin_ty = df_mes['margen_final'].sum()
    pm_final = mfin_ty / n_ty * 100 if n_ty else 0
    tiene_mfinal = (com_ty + log_ty) > 0   # solo tiene sentido ago-2026+

    b_ly = df_ly['venta_bruta'].sum(); m_ly = df_ly['margen_front'].sum()
    n_ly = df_ly['venta_neta'].sum()
    pm_ly = m_ly/n_ly*100 if n_ly else 0

    yoy_v = (b_ty/b_ly-1)*100 if b_ly else 0
    yoy_m = (m_ty/m_ly-1)*100 if m_ly else 0

    # Meta mes total
    # Meta total = por canal V06 ($577M; ya incluye Corp/Distrib — Andrés 17-ago).
    meta_mes = sum(v for (a, m, c), v in metas.items() if a == ano_actual and m == mes_actual)
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
        can_rows += f'<tr><td>{r["canal"][:24]}</td><td align="right">{int(r["sos"]):,}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td><td align="right">{fmt_m(meta_c) if meta_c else "—"}</td><td align="right" style="color:{color}">{pmeta:.1f}%</td>{_yoy_cell(r["bruta"], ly_can.get(r["canal"], 0))}{_yoy_cell(r["margen"], ly_can_m.get(r["canal"], 0))}</tr>'

    # Por línea de negocio (vs Meta V06)
    df_mes = df_mes.copy()
    df_mes['_neg'] = df_mes['tipo_negocio'].apply(_norm_neg)
    g_neg = df_mes.groupby('tipo_negocio').agg(
        _neg=('_neg', 'first'),
        sos=('pedido', 'nunique'),
        bruta=('venta_bruta', 'sum'),
        neta=('venta_neta', 'sum'),
        margen=('margen_front', 'sum'),
    ).reset_index().sort_values('bruta', ascending=False)
    neg_rows = ''
    meta_neg_tot = 0
    for _, r in g_neg.iterrows():
        meta_n = metas_neg.get((ano_actual, mes_actual, r['_neg']), 0)
        meta_neg_tot += meta_n
        pm = r['margen'] / r['neta'] * 100 if r['neta'] else 0
        pmeta = r['bruta'] / meta_n * 100 if meta_n else 0
        color = '#16A34A' if pmeta >= 80 else ('#EA580C' if pmeta >= 40 else '#DC2626')
        neg = str(r['tipo_negocio'] or '(s/neg)')[:24]
        neg_rows += (f'<tr><td>{neg}</td><td align="right">{int(r["sos"]):,}</td>'
                     f'<td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td>'
                     f'<td align="right">{pm:.1f}%</td><td align="right">{fmt_m(meta_n) if meta_n else "—"}</td>'
                     f'<td align="right" style="color:{color}">{pmeta:.1f}%</td>'
                     f'{_yoy_cell(r["bruta"], ly_neg.get(r["_neg"], 0))}'
                     f'{_yoy_cell(r["margen"], ly_neg_m.get(r["_neg"], 0))}</tr>')
    # fila total — meta oficial $577M (canal V06), consistente con el headline; las
    # líneas individuales son la apertura (Corp/Distrib pueden sumar más: adelanto Sep).
    pmeta_t = b_ty / meta_mes * 100 if meta_mes else 0
    neg_rows += (f'<tr style="font-weight:700;background:#F8FAFC"><td>TOTAL</td><td align="right">{s_ty:,}</td>'
                 f'<td align="right">{fmt_m(b_ty)}</td><td align="right">{fmt_m(m_ty)}</td>'
                 f'<td align="right">{pm_ty:.1f}%</td><td align="right">{fmt_m(meta_mes)}</td>'
                 f'<td align="right">{pmeta_t:.1f}%</td>{_yoy_cell(b_ty, b_ly)}{_yoy_cell(m_ty, m_ly)}</tr>')

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
        mar_rows += f'<tr><td>{ent}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td><td align="right">{sh:.1f}%</td>{_yoy_cell(r["bruta"], ly_mar.get(r["marca"], 0))}{_yoy_cell(r["margen"], ly_mar_m.get(r["marca"], 0))}</tr>'

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
        cat_rows += f'<tr><td>{ent}</td><td align="right">{fmt_m(r["bruta"])}</td><td align="right">{fmt_m(r["margen"])}</td><td align="right">{pm:.1f}%</td><td align="right">{sh:.1f}%</td>{_yoy_cell(r["bruta"], ly_cat.get(r["categoria_hijo"], 0))}{_yoy_cell(r["margen"], ly_cat_m.get(r["categoria_hijo"], 0))}</tr>'

    # ── Sección Margen Final (ago-2026+): apertura venta→front→comisión→logística→final.
    # Solo se renderiza si hay comisión/logística en el período (evita ruido pre-agosto).
    def _mfin_rows(gcol, total_label=None):
        g = df_mes.groupby(gcol).agg(
            neta=('venta_neta', 'sum'), mf=('margen_front', 'sum'),
            com=('comision', 'sum'), log=('logistica', 'sum'), mfin=('margen_final', 'sum'),
        ).reset_index().sort_values('neta', ascending=False)
        g = g[g['neta'] != 0].head(15)
        rows = ''
        for _, r in g.iterrows():
            pmf = r['mfin'] / r['neta'] * 100 if r['neta'] else 0
            colp = '#16A34A' if pmf >= 25 else ('#EA580C' if pmf >= 12 else '#DC2626')
            ent = str(r[gcol] or '—')[:24]
            rows += (f'<tr><td>{ent}</td><td align="right">{fmt_m(r["neta"])}</td>'
                     f'<td align="right">{fmt_m(r["mf"])}</td><td align="right">{fmt_m(r["com"])}</td>'
                     f'<td align="right">{fmt_m(r["log"])}</td><td align="right"><b>{fmt_m(r["mfin"])}</b></td>'
                     f'<td align="right" style="color:{colp};font-weight:600">{pmf:.1f}%</td></tr>')
        if total_label:
            pmf_t = mfin_ty / n_ty * 100 if n_ty else 0
            rows += (f'<tr style="font-weight:700;background:#F8FAFC"><td>{total_label}</td>'
                     f'<td align="right">{fmt_m(n_ty)}</td><td align="right">{fmt_m(m_ty)}</td>'
                     f'<td align="right">{fmt_m(com_ty)}</td><td align="right">{fmt_m(log_ty)}</td>'
                     f'<td align="right">{fmt_m(mfin_ty)}</td><td align="right">{pmf_t:.1f}%</td></tr>')
        return rows

    if tiene_mfinal:
        _th = ('<thead><tr style="background:#F0FDF4;border-bottom:2px solid #BBF7D0">'
               '<th align="left">{d}</th><th align="right">Venta neta</th><th align="right">Mg Front</th>'
               '<th align="right">Comisión</th><th align="right">Logística</th><th align="right">Mg Final</th>'
               '<th align="right">%MFin</th></tr></thead>')
        # Box resumen (waterfall) — va como headline tras el YoY.
        _mfin_box = f"""
<div style="background:#F0FDF4;border-left:4px solid #16A34A;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#166534;text-transform:uppercase;letter-spacing:0.05em">💰 Margen Final (contribución directa) · ago-2026+</div>
  <div style="font-size:1.5rem;font-weight:700;color:#15803D;margin:2px 0">{fmt_m(mfin_ty)} <span style="font-size:0.9rem;font-weight:600;color:#64748B">({pm_final:.1f}% s/neta)</span></div>
  <div style="font-size:0.85rem;color:#64748B">Margen Front {fmt_m(m_ty)} ({pm_ty:.1f}%) − Comisión {fmt_m(com_ty)} − Logística {fmt_m(log_ty)} = <b>Margen Final {fmt_m(mfin_ty)}</b><br>
  <span style="font-size:0.8rem">Comisión: Odoo (ML/Paris/Ripley/Walmart) + tarifario Falabella/flat. Logística: Odoo marketplaces + tarifario BlueX (webs/B2B/LATAM/GRS). Marketing FUERA.</span></div>
</div>"""
        # Tabla margen final por línea de negocio — va DESPUÉS de "Por línea de negocio".
        _mfin_neg = f"""
<h3 style="margin:16px 0 8px 0;font-size:0.95rem;color:#15803D">💰 Margen Final por línea de negocio (ago-2026+)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.83rem">
{_th.replace('{d}', 'Línea de negocio')}
<tbody>{_mfin_rows('tipo_negocio', total_label='TOTAL')}</tbody></table>"""
        # Tabla margen final por canal — va DESPUÉS de "Top 15 canales".
        _mfin_can = f"""
<h3 style="margin:16px 0 8px 0;font-size:0.95rem;color:#15803D">💰 Margen Final — Top 15 canales (ago-2026+)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.83rem">
{_th.replace('{d}', 'Canal')}
<tbody>{_mfin_rows('canal')}</tbody></table>"""
    else:
        _mfin_box = _mfin_neg = _mfin_can = ''

    mes_nom = ['','Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'][mes_actual]
    color_av = '#16A34A' if pct_meta >= 80 else ('#EA580C' if pct_meta >= 40 else '#DC2626')

    _bc = os.environ.get('PULSO_CORRECCION', '').strip()
    _banner_correccion = (f'<div style="background:#FEF3C7;border-left:4px solid #D97706;padding:12px;border-radius:6px;margin:12px 0;font-size:0.9rem;color:#92400E"><b>⚠️ Corrección:</b> {_bc}</div>' if _bc else '')
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body style="font-family:-apple-system,Segoe UI,sans-serif;max-width:900px;margin:auto;color:#1E293B">

<h2 style="margin:0 0 4px 0">📊 Pulso Diario UnionX · {mes_nom} {ano_actual}</h2>
<p style="color:#64748B;margin:0 0 16px 0;font-size:0.9rem">Acumulado al cierre {ayer.strftime("%d-%b-%Y")} ({dias_acum} días)</p>
{_banner_correccion}

<div style="background:#F1F5F9;border-left:4px solid #2563EB;padding:14px;border-radius:6px;margin:16px 0">
  <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;letter-spacing:0.05em">Acumulado mes (al {ayer.strftime("%d-%b")})</div>
  <div style="font-size:1.7rem;font-weight:700;color:#1E40AF;margin:2px 0">{fmt_m(b_ty)} <span style="font-size:0.95rem;font-weight:600;color:#64748B">bruta · {fmt_m(n_ty)} neta</span></div>
  <div style="font-size:0.88rem;color:#64748B">
    Meta {mes_nom}: {fmt_m(meta_mes)} · <b style="color:{color_av}">{pct_meta:.1f}%</b> · gap {fmt_m(gap_meta)} ·
    Margen Front {fmt_m(m_ty)} ({pm_ty:.1f}%) · {u_ty:,} uds · {s_ty:,} pedidos<br>
    Venta bruta {fmt_m(venta_gross_ty)} · Devoluciones {fmt_m(dev_ty)} · = <b>{fmt_m(b_ty)}</b> neto de devoluciones
    {f'<br>💰 <b style="color:#15803D">Margen Final {fmt_m(mfin_ty)} ({pm_final:.1f}%)</b> — tras comisión {fmt_m(com_ty)} + logística {fmt_m(log_ty)} (marketing fuera)' if tiene_mfinal else ''}
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
{_mfin_box}
<h3 style="margin:24px 0 8px 0;font-size:1rem">📅 Por día — {mes_nom} {ano_actual}</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.85rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Día</th><th align="right">SOs</th><th align="right">Uds</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th></tr></thead>
<tbody>{dias_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏢 Por línea de negocio (vs Meta V06)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.83rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Línea de negocio</th><th align="right">SOs</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">Meta</th><th align="right">%Meta</th><th align="right">YoY Vta</th><th align="right">YoY Mg</th></tr></thead>
<tbody>{neg_rows}</tbody></table>
{_mfin_neg}

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏆 Top 15 canales acumulado mes (vs Meta V06)</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.83rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Canal</th><th align="right">SOs</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">Meta</th><th align="right">%Meta</th><th align="right">YoY Vta</th><th align="right">YoY Mg</th></tr></thead>
<tbody>{can_rows}</tbody></table>
{_mfin_can}

<h3 style="margin:24px 0 8px 0;font-size:1rem">🏷️ Top 10 marcas acumulado mes</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.83rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Marca</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">%Share</th><th align="right">YoY Vta</th><th align="right">YoY Mg</th></tr></thead>
<tbody>{mar_rows}</tbody></table>

<h3 style="margin:24px 0 8px 0;font-size:1rem">📂 Top 10 categorías acumulado mes</h3>
<table style="width:100%;border-collapse:collapse;font-size:0.83rem">
<thead><tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0"><th align="left">Categoría</th><th align="right">Bruta</th><th align="right">Margen</th><th align="right">%M</th><th align="right">%Share</th><th align="right">YoY Vta</th><th align="right">YoY Mg</th></tr></thead>
<tbody>{cat_rows}</tbody></table>

<hr style="border:none;border-top:1px solid #E2E8F0;margin:24px 0">
<p style="font-size:0.85rem;color:#64748B">
🔗 Dashboard live: <a href="https://unionx-ventas.streamlit.app">unionx-ventas.streamlit.app</a><br>
📊 Reporte Ventas Empresa 2026 vs 2025 (pivot viva): <a href="https://drive.google.com/file/d/1jcLmmLn4oHoen9FpL-UuWnYTxaYACQHL/view?usp=sharing">abrir en Drive</a><br>
📎 Adjunto: Excel RAW {mes_nom} acumulado al {ayer.strftime("%d-%b")} (sin venta_neta).<br>
Fuente: parquet local (Odoo + CMR + manuales) · Sin Delivery_*.
</p>

<style>td,th{{padding:6px 8px;border-bottom:1px solid #E2E8F0}}</style>
</body></html>"""
    return html, b_ty, ayer, mes_nom


def _resumen_margen_final(df_mes):
    """Apertura Venta→Front→Comisión→Logística→Final por línea de negocio y por canal.
    Devuelve DataFrame apilado (dos bloques) o None si no hay comisión/logística (pre-ago)."""
    d = df_mes.copy()
    for c in ('venta_neta', 'margen_front', 'comision', 'logistica', 'margen_final'):
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0) if c in d.columns else 0.0
    if (d['comision'].sum() + d['logistica'].sum()) == 0:
        return None

    def _bloque(gcol, titulo):
        g = d.groupby(gcol).agg(
            **{'Venta neta': ('venta_neta', 'sum'), 'Margen Front': ('margen_front', 'sum'),
               'Comisión': ('comision', 'sum'), 'Logística': ('logistica', 'sum'),
               'Margen Final': ('margen_final', 'sum')}).reset_index().rename(columns={gcol: 'Detalle'})
        g = g[g['Venta neta'] != 0].sort_values('Venta neta', ascending=False)
        g['% MFin'] = (g['Margen Final'] / g['Venta neta'] * 100).round(1)
        tot = pd.DataFrame([{'Detalle': 'TOTAL', 'Venta neta': g['Venta neta'].sum(),
                             'Margen Front': g['Margen Front'].sum(), 'Comisión': g['Comisión'].sum(),
                             'Logística': g['Logística'].sum(), 'Margen Final': g['Margen Final'].sum(),
                             '% MFin': round(g['Margen Final'].sum() / g['Venta neta'].sum() * 100, 1) if g['Venta neta'].sum() else 0}])
        cab = pd.DataFrame([{'Detalle': titulo}])
        return pd.concat([cab, g, tot], ignore_index=True)

    cols = ['Detalle', 'Venta neta', 'Margen Front', 'Comisión', 'Logística', 'Margen Final', '% MFin']
    blank = pd.DataFrame([{c: '' for c in cols}])
    out = pd.concat([_bloque('tipo_negocio', 'POR LÍNEA DE NEGOCIO'), blank,
                     _bloque('canal', 'POR CANAL')], ignore_index=True)
    return out[cols]


def generar_excel_mes(df, ayer):
    """Excel: hoja RAW acumulado mes (sin venta_neta) + hoja 'Resumen Margen Final'."""
    primer_dia = date(ayer.year, ayer.month, 1)
    df_full = df[(df['fv_dt'] >= primer_dia) & (df['fv_dt'] <= ayer)].copy()
    resumen = _resumen_margen_final(df_full)  # antes de dropear venta_neta
    drop_cols = [c for c in ['venta_neta', 'fv', 'fv_dt'] if c in df_full.columns]
    df_mes = df_full.drop(columns=drop_cols)
    buf = io.BytesIO()
    sheet = f'{ayer.strftime("%Y-%m")} acum {ayer.strftime("%d")}'
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df_mes.to_excel(w, index=False, sheet_name=sheet[:31])
        if resumen is not None:
            resumen.to_excel(w, index=False, sheet_name='Resumen Margen Final')
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
