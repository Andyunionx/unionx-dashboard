"""views/planning/analisis_planificacion.py
─────────────────────────────────────────────
Análisis mensual de planificación — replica las 7 hojas del análisis Excel mensual:
  1. 📊 Cómo Vamos     — Real vs Meta del mes actual (por Marca y Canal)
  2. 📈 Comp. Marcas   — YTD META | REAL | VAR% por Marca
  3. 📈 Comp. Canales  — YTD META | REAL | VAR% por Canal
  4. 💰 CST x Marca    — Proyección mensual a costo ($M) por Marca
  5. 🔴 Detalle Crítico — SKUs con cobertura < 1m
  6. 🚢 Tránsitos      — Embarques en tránsito agrupados por PI
  7. 🆕 Nuevos         — SKUs nuevos (sin stock) próximos a llegar
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import streamlit as st
from pathlib import Path

from views.planning._data_helpers import (
    DATA_DIR,
    cargar_ppto_canal,
    cargar_ppto_marca,
    cargar_costo_unit_sku,
    cargar_planif_transito_live,
    cargar_transito,
)
from views.planning.triada_cobertura import _preparar_datos

_TODAY = pd.Timestamp.today().normalize()

# ── Marca / Canal mappings ────────────────────────────────────────────
_TIPO_NEG_TO_PPTO: dict[str, str] = {
    'Marketplace':      'Marketplace',
    'Páginas propias':  'P.Web',
    'Fidelización':     'Fidelización',
    'Fidelización CMR': 'Fidelización',
    'Distribución':     'Distribución',
    'Corporativo':      'Corporativo',
}

_MARCA_TO_PPTO: dict[str, str] = {
    'Lhotse': 'Lhotse',    'lhotse': 'Lhotse',
    'Simplit': 'Simplit',  'SIMPLIT': 'Simplit',  'simplit': 'Simplit',
    'Levo': 'Levo',        'levo': 'Levo',        'LEVO': 'Levo',
    'Xroad': 'Xroad',      'xroad': 'Xroad',      'XROAD': 'Xroad',
    'Bandú': 'Bandú',      'Bandu': 'Bandú',      'bandú': 'Bandú',
    'T-Care': 'T-Care',    't-care': 'T-Care',
    'Dynamo TL': 'Dynamo Tools', 'Dynamo': 'Dynamo Tools',
    'Dinamo Tools': 'Dynamo Tools', 'Dynamo Tools': 'Dynamo Tools',
    'Purito': 'Purito',
}

# Canales canónicos del Excel (mismo orden y nombres)
_CANALES_DISPLAY = [
    'Corporativo',
    'Distribución',
    'UnionX B2B',
    'Fidelización',
    'Marketplace',
    'P.Web',
    'Tiendas Propias',
]


# ── Cached loaders ────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def _cargar_ventas_ytd() -> pd.DataFrame:
    """Ventas del año actual con columnas normalizadas para comparativo PPTO.
    Lee historico (meses cerrados) + mes_actual (mes corriente desde Turso sync).
    """
    need = ['fecha_venta', 'marca', 'tipo_negocio', 'canal', 'venta_neta', 'margen_front']
    path_hist = DATA_DIR / 'historico' / 'ventas_historico.parquet'
    path_mes  = DATA_DIR / 'historico' / 'ventas_mes_actual.parquet'

    def _safe_read(p):
        try:
            return pd.read_parquet(p, columns=need)
        except Exception:
            try:
                d = pd.read_parquet(p)
                return d[[c for c in need if c in d.columns]]
            except Exception:
                return None

    df_mes  = _safe_read(path_mes)  if path_mes.exists()  else None
    df_hist = _safe_read(path_hist) if path_hist.exists() else None

    # ventas_mes_actual cubre el mes corriente (live). Los meses cerrados están en
    # ventas_historico (congelados al cierre). Solo usamos mes_actual para el mes
    # en curso — si tiene datos de meses anteriores, los descartamos para no
    # pisar el histórico congelado (que tiene el dato definitivo).
    if df_mes is not None and not df_mes.empty:
        mes_corriente = _TODAY.to_period('M').strftime('%Y-%m')
        fechas_mes = pd.to_datetime(df_mes['fecha_venta'], errors='coerce')
        df_mes = df_mes[fechas_mes.dt.to_period('M').astype(str) == mes_corriente]

    dfs = [d for d in (df_hist, df_mes) if d is not None and not d.empty]
    if not dfs:
        return pd.DataFrame()
    try:
        df = pd.concat(dfs, ignore_index=True)
        df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce')
        df = df[df['fecha_venta'].dt.year == _TODAY.year].copy()
        df['mes']        = df['fecha_venta'].dt.to_period('M').astype(str)
        df['canal_ppto'] = df['tipo_negocio'].map(_TIPO_NEG_TO_PPTO).fillna('Otros')
        # Ventas Distribución cuyo canal real sea 'UnionX B2B' se separan de Distribución
        if 'canal' in df.columns:
            mask_b2b = (df['tipo_negocio'] == 'Distribución') & (df['canal'] == 'UnionX B2B')
            df.loc[mask_b2b, 'canal_ppto'] = 'UnionX B2B'
        df['marca_ppto'] = df['marca'].map(_MARCA_TO_PPTO).fillna('Prov. Nacionales')
        df['venta_neta']   = pd.to_numeric(df['venta_neta'],   errors='coerce').fillna(0).astype('float64')
        df['margen_front'] = pd.to_numeric(df['margen_front'], errors='coerce').fillna(0).astype('float64')
        return df[['mes', 'marca_ppto', 'canal_ppto', 'venta_neta', 'margen_front']]
    except Exception as e:
        st.toast(f"ventas YTD: {e}", icon="⚠️")
        return pd.DataFrame()


@st.cache_data(ttl=600, show_spinner=False)
def _build_transit_pivot() -> pd.DataFrame:
    """SKU × mes (YYYY-MM) → unidades de tránsito confirmado + FCST."""
    _df = cargar_planif_transito_live()
    if _df.empty:
        _base = DATA_DIR / 'planificacion' / 'snapshots' / 'planif_transito_baseline.parquet'
        if _base.exists():
            _df = pd.read_parquet(_base)
            _df.columns = [c.lower().replace(' ', '_') for c in _df.columns]
            if not {'sku', 'cantidad'}.issubset(_df.columns):
                _df = pd.DataFrame()
        if _df.empty:
            tr = cargar_transito()
            if 'status' in tr.columns:
                tr = tr[~tr['status'].str.contains('RFQ', na=False)]
            _df = tr

    if _df.empty:
        return pd.DataFrame()

    _df['sku']      = _df['sku'].astype(str)
    _df['cantidad'] = pd.to_numeric(_df['cantidad'], errors='coerce').fillna(0)
    _df['_eta']     = pd.to_datetime(_df.get('fecha_eta_bodega'), errors='coerce')

    def _mes_tr(fecha):
        if pd.isna(fecha):
            return None
        return (fecha if fecha.day <= 5 else fecha + pd.DateOffset(months=1)).strftime('%Y-%m')

    _df['mes_eta'] = _df['_eta'].apply(_mes_tr)
    _piv = (_df.dropna(subset=['mes_eta'])
             .pivot_table(index='sku', columns='mes_eta', values='cantidad', aggfunc='sum')
             .fillna(0))

    _fcst_path = DATA_DIR / 'planificacion' / 'snapshots' / 'planif_forecast_transito.parquet'
    if _fcst_path.exists():
        _df_f = pd.read_parquet(_fcst_path)
        _df_f['sku']      = _df_f['sku'].astype(str)
        _df_f['unidades'] = pd.to_numeric(_df_f['unidades'], errors='coerce').fillna(0)
        _piv_f = _df_f.pivot_table(index='sku', columns='mes', values='unidades', aggfunc='sum').fillna(0)
        for mc in _piv_f.columns:
            if mc not in _piv.columns:
                _piv[mc] = _piv_f[mc]

    return _piv


# ── Display helpers ───────────────────────────────────────────────────
def _fmt_m(v):
    return f"${v/1e6:.1f}M" if pd.notna(v) and v != 0 else ("$0.0M" if v == 0 else "—")

def _fmt_pct(v):
    return f"{v:+.1%}" if pd.notna(v) else "—"

def _color_pct(v):
    if pd.isna(v): return ''
    return 'color: #22c55e; font-weight:bold' if v >= 0 else 'color: #ef4444'

def _fmt_cob(v):
    if pd.isna(v): return "—"
    if v < 1:  return f"🔴 {v:.1f}m"
    if v < 2:  return f"🟡 {v:.1f}m"
    if v <= 4: return f"🟢 {v:.1f}m"
    return f"🟣 {v:.1f}m"

def _dl(df: pd.DataFrame, filename: str, label="⬇️ Descargar CSV"):
    st.download_button(label, data=df.to_csv(index=False, encoding='utf-8-sig'),
                       file_name=filename, mime='text/csv', use_container_width=True)


def _build_comp_table(real_piv, meta_piv, meses, dim_col, dims_filter=None):
    """Returns (df, meta_cols, real_cols, var_cols) for the META|REAL|VAR% table."""
    all_dims_raw = sorted(set(
        (real_piv.index.tolist() if not real_piv.empty else []) +
        (meta_piv.index.tolist() if not meta_piv.empty else [])
    ))
    all_dims = [d for d in all_dims_raw if dims_filter is None or d in set(dims_filter)]
    rows, mc, rc, vc = [], [], [], []

    for dim in all_dims:
        row = {dim_col: dim}
        tm = tr = 0.0
        for mes in meses:
            lbl = pd.Timestamp(mes + '-01').strftime('%b')
            m = float(meta_piv.at[dim, mes]) if (not meta_piv.empty and dim in meta_piv.index and mes in meta_piv.columns) else 0.0
            r = float(real_piv.at[dim, mes]) if (not real_piv.empty and dim in real_piv.index  and mes in real_piv.columns)  else 0.0
            row[f'{lbl} META'] = m
            row[f'{lbl} REAL'] = r
            row[f'{lbl} VAR%'] = (r / m - 1) if m > 0 else None
            tm += m; tr += r
        row['TOT META'] = tm
        row['TOT REAL'] = tr
        row['TOT VAR%'] = (tr / tm - 1) if tm > 0 else None
        rows.append(row)

    # Grand total row — sums only filtered dims
    tr_row = {dim_col: 'TOTAL'}
    t_m = t_r = 0.0
    for mes in meses:
        lbl = pd.Timestamp(mes + '-01').strftime('%b')
        m = sum(float(meta_piv.at[d, mes]) if (not meta_piv.empty and d in meta_piv.index and mes in meta_piv.columns) else 0.0 for d in all_dims)
        r = sum(float(real_piv.at[d, mes])  if (not real_piv.empty  and d in real_piv.index  and mes in real_piv.columns)  else 0.0 for d in all_dims)
        tr_row[f'{lbl} META'] = m; tr_row[f'{lbl} REAL'] = r
        tr_row[f'{lbl} VAR%'] = (r / m - 1) if m > 0 else None
        t_m += m; t_r += r
    tr_row['TOT META'] = t_m; tr_row['TOT REAL'] = t_r
    tr_row['TOT VAR%'] = (t_r / t_m - 1) if t_m > 0 else None
    rows.append(tr_row)

    for mes in meses:
        lbl = pd.Timestamp(mes + '-01').strftime('%b')
        mc.append(f'{lbl} META'); rc.append(f'{lbl} REAL'); vc.append(f'{lbl} VAR%')
    mc.append('TOT META'); rc.append('TOT REAL'); vc.append('TOT VAR%')

    return pd.DataFrame(rows), mc, rc, vc


def _show_comp(df, meta_cols, real_cols, var_cols, dim_col):
    fmt = {c: _fmt_m   for c in meta_cols + real_cols}
    fmt.update({c: _fmt_pct for c in var_cols})
    styler = (
        df.style
          .format(fmt)
          .map(_color_pct, subset=var_cols)
          .apply(lambda row: [
              'font-weight:bold;background-color:#1e2432;color:white' if row[dim_col] == 'TOTAL' else ''
              for _ in row
          ], axis=1)
    )
    st.dataframe(styler, use_container_width=True, hide_index=True,
                 height=min(600, 60 + len(df) * 35))


def _build_comp_agg(real_piv, meta_piv, meses, dim_col, dims_filter=None):
    """Aggregate Comp table: dim | VENTA META | VENTA REAL | % CUMPLIMIENTO."""
    all_dims_raw = sorted(set(
        (real_piv.index.tolist() if not real_piv.empty else []) +
        (meta_piv.index.tolist() if not meta_piv.empty else [])
    ))
    all_dims = [d for d in all_dims_raw if dims_filter is None or d in set(dims_filter)]
    rows = []
    for dim in all_dims:
        m_tot = sum(
            float(meta_piv.at[dim, mes]) if (not meta_piv.empty and dim in meta_piv.index and mes in meta_piv.columns) else 0.0
            for mes in meses
        )
        r_tot = sum(
            float(real_piv.at[dim, mes]) if (not real_piv.empty and dim in real_piv.index and mes in real_piv.columns) else 0.0
            for mes in meses
        )
        rows.append({dim_col: dim, 'VENTA META': m_tot, 'VENTA REAL': r_tot,
                     '% CUMPLIMIENTO': r_tot / m_tot if m_tot > 0 else None})
    t_m = sum(
        float(meta_piv.at[d, m]) if (not meta_piv.empty and d in meta_piv.index and m in meta_piv.columns) else 0.0
        for d in all_dims for m in meses
    )
    t_r = sum(
        float(real_piv.at[d, m]) if (not real_piv.empty and d in real_piv.index and m in real_piv.columns) else 0.0
        for d in all_dims for m in meses
    )
    rows.append({dim_col: 'TOTAL', 'VENTA META': t_m, 'VENTA REAL': t_r,
                 '% CUMPLIMIENTO': t_r / t_m if t_m > 0 else None})
    df = pd.DataFrame(rows)
    total_mask = df[dim_col] == 'TOTAL'
    df = pd.concat([
        df[~total_mask].sort_values('VENTA META', ascending=False),
        df[total_mask]
    ]).reset_index(drop=True)
    return df


def _show_comp_agg(df, dim_col):
    """Display aggregate Comp table. % CUMPLIMIENTO: verde ≥100%, amarillo ≥90%, naranja ≥70%, rojo <70%."""
    def _c_cumpl(v):
        if pd.isna(v): return ''
        if v >= 1.00: return 'color:#22c55e;font-weight:bold'
        if v >= 0.90: return 'color:#eab308;font-weight:bold'
        if v >= 0.70: return 'color:#f97316'
        return 'color:#ef4444'
    fmt = {
        'VENTA META': _fmt_m,
        'VENTA REAL': _fmt_m,
        '% CUMPLIMIENTO': lambda v: f"{v:.1%}" if pd.notna(v) else "—",
    }
    st.dataframe(
        df.style
          .format(fmt)
          .map(_c_cumpl, subset=['% CUMPLIMIENTO'])
          .apply(lambda row: [
              'font-weight:bold;background-color:#1e2432;color:white' if row[dim_col] == 'TOTAL' else ''
              for _ in row
          ], axis=1),
        use_container_width=True, hide_index=True,
        height=min(600, 60 + len(df) * 35),
    )


def _build_cv_table(real_piv, meta_piv, dim_col, meses_lin, dims_filter=None):
    """Cómo Vamos table with per-month linealidad and optional dimension filter.
    meses_lin: [(mes_str, linealidad_float), ...]
    """
    if len(meses_lin) == 1:
        mes0, lin0 = meses_lin[0]
        ts0   = pd.Timestamp(mes0 + '-01')
        dias0 = (ts0 + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
        dia0  = round(lin0 * dias0)
        lin_header = f'Meta Lineal\ndía {dia0}/{dias0}'
    else:
        lin_header = 'Meta Lineal\n(período)'

    all_dims_raw = sorted(set(
        (real_piv.index.tolist() if not real_piv.empty else []) +
        (meta_piv.index.tolist() if not meta_piv.empty else [])
    ))
    all_dims = [d for d in all_dims_raw if dims_filter is None or d in set(dims_filter)]

    rows = []
    t_m = t_r = t_mlin = 0.0
    for dim in all_dims:
        m_tot = r_tot = mlin_tot = 0.0
        for mes, lin in meses_lin:
            mv = float(meta_piv.at[dim, mes]) if (not meta_piv.empty and dim in meta_piv.index and mes in meta_piv.columns) else 0.0
            rv = float(real_piv.at[dim, mes])  if (not real_piv.empty  and dim in real_piv.index  and mes in real_piv.columns)  else 0.0
            m_tot += mv; r_tot += rv; mlin_tot += mv * lin
        t_m += m_tot; t_r += r_tot; t_mlin += mlin_tot
        rows.append({
            dim_col:         dim,
            'Meta Período':  m_tot,
            lin_header:      mlin_tot,
            'Real Acum.':    r_tot,
            'vs Lineal ($)': r_tot - mlin_tot,
            '% vs Lineal':   (r_tot / mlin_tot - 1) if mlin_tot > 0 else None,
            '% vs Meta':     (r_tot / m_tot - 1)    if m_tot > 0    else None,
        })
    rows.append({
        dim_col:         'TOTAL',
        'Meta Período':  t_m,
        lin_header:      t_mlin,
        'Real Acum.':    t_r,
        'vs Lineal ($)': t_r - t_mlin,
        '% vs Lineal':   (t_r / t_mlin - 1) if t_mlin > 0 else None,
        '% vs Meta':     (t_r / t_m - 1)    if t_m > 0    else None,
    })
    return pd.DataFrame(rows), lin_header


def _show_cv(df, dim_col, lin_header):
    """Display Cómo Vamos table with 5-level color on % vs Lineal."""
    money_cols = ['Meta Período', lin_header, 'Real Acum.', 'vs Lineal ($)']
    fmt = {c: _fmt_m for c in money_cols}
    fmt['% vs Lineal'] = _fmt_pct
    fmt['% vs Meta']   = _fmt_pct

    def _c5(v):
        if pd.isna(v): return ''
        if v >= 0.10:  return 'color:#22c55e;font-weight:bold'   # ≥110%
        if v >= -0.10: return 'color:#eab308;font-weight:bold'   # 90–110%
        if v >= -0.30: return 'color:#f97316'                    # 70–90%
        if v >= -0.50: return 'color:#ef4444'                    # 50–70%
        return 'color:#991b1b;font-weight:bold'                  # <50%

    st.dataframe(
        df.style
          .format(fmt)
          .map(_c5,        subset=['% vs Lineal'])
          .map(_color_pct, subset=['% vs Meta'])
          .apply(lambda row: [
              'font-weight:bold;background-color:#1e2432;color:white' if row[dim_col] == 'TOTAL' else ''
              for _ in row
          ], axis=1),
        use_container_width=True, hide_index=True,
        height=min(600, 60 + len(df) * 35),
    )


def _show_contrib(df, dim_col):
    """Display contribution table (Real only — no meta in PPTO)."""
    fmt = {
        'Real Acum.': _fmt_m,
        '% Margen': lambda v: f"{v:.1%}" if pd.notna(v) else "—",
    }
    st.dataframe(
        df.style
          .format(fmt)
          .apply(lambda row: [
              'font-weight:bold;background-color:#1e2432;color:white' if row[dim_col] == 'TOTAL' else ''
              for _ in row
          ], axis=1),
        use_container_width=True, hide_index=True,
        height=min(600, 60 + len(df) * 35),
    )


def _build_contrib_ytd(real_cb_piv, real_vn_piv, meses, dim_col, dims_filter=None):
    """Real YTD contribution table: dim | Ene ... | TOTAL | % Margen"""
    all_dims_raw = sorted(real_cb_piv.index.tolist()) if not real_cb_piv.empty else []
    all_dims = [d for d in all_dims_raw if dims_filter is None or d in set(dims_filter)]
    rows = []
    for dim in all_dims:
        row = {dim_col: dim}
        tot_cb = tot_vn = 0.0
        for mes in meses:
            lbl = pd.Timestamp(mes + '-01').strftime('%b')
            cb = float(real_cb_piv.at[dim, mes]) if (not real_cb_piv.empty and dim in real_cb_piv.index and mes in real_cb_piv.columns) else 0.0
            vn = float(real_vn_piv.at[dim, mes]) if (not real_vn_piv.empty and dim in real_vn_piv.index and mes in real_vn_piv.columns) else 0.0
            row[lbl] = cb
            tot_cb += cb; tot_vn += vn
        row['TOTAL'] = tot_cb
        row['% Margen'] = tot_cb / tot_vn if tot_vn > 0 else None
        rows.append(row)
    # Grand total row — sums only filtered dims
    row_t = {dim_col: 'TOTAL'}
    gt_cb = gt_vn = 0.0
    for mes in meses:
        lbl = pd.Timestamp(mes + '-01').strftime('%b')
        cb = sum(float(real_cb_piv.at[d, mes]) if (not real_cb_piv.empty and d in real_cb_piv.index and mes in real_cb_piv.columns) else 0.0 for d in all_dims)
        vn = sum(float(real_vn_piv.at[d, mes]) if (not real_vn_piv.empty and d in real_vn_piv.index and mes in real_vn_piv.columns) else 0.0 for d in all_dims)
        row_t[lbl] = cb; gt_cb += cb; gt_vn += vn
    row_t['TOTAL'] = gt_cb
    row_t['% Margen'] = gt_cb / gt_vn if gt_vn > 0 else None
    rows.append(row_t)
    df = pd.DataFrame(rows)
    total_mask = df[dim_col] == 'TOTAL'
    df = pd.concat([
        df[~total_mask].sort_values('TOTAL', ascending=False),
        df[total_mask]
    ]).reset_index(drop=True)
    return df


def _show_contrib_ytd(df, dim_col):
    """Display YTD contribution Real table with TOTAL row highlighted."""
    mon_cols = [c for c in df.columns if c not in (dim_col, '% Margen')]
    fmt = {c: _fmt_m for c in mon_cols}
    fmt['% Margen'] = lambda v: f"{v:.1%}" if pd.notna(v) else "—"
    st.dataframe(
        df.style
          .format(fmt)
          .apply(lambda row: [
              'font-weight:bold;background-color:#1e2432;color:white' if row[dim_col] == 'TOTAL' else ''
              for _ in row
          ], axis=1),
        use_container_width=True, hide_index=True,
        height=min(600, 60 + len(df) * 35),
    )


def _build_contrib_cv(real_cb_piv, real_vn_piv, dim_col, meses_lin, dims_filter=None):
    """Period-aggregated contribution for Cómo Vamos."""
    all_dims_raw = sorted(real_cb_piv.index.tolist() if not real_cb_piv.empty else [])
    all_dims = [d for d in all_dims_raw if dims_filter is None or d in set(dims_filter)]
    rows = []
    t_cb = t_vn = 0.0
    for dim in all_dims:
        cb_tot = vn_tot = 0.0
        for mes, _ in meses_lin:
            cb = float(real_cb_piv.at[dim, mes]) if (not real_cb_piv.empty and dim in real_cb_piv.index and mes in real_cb_piv.columns) else 0.0
            vn = float(real_vn_piv.at[dim, mes])  if (not real_vn_piv.empty  and dim in real_vn_piv.index  and mes in real_vn_piv.columns)  else 0.0
            cb_tot += cb; vn_tot += vn
        t_cb += cb_tot; t_vn += vn_tot
        rows.append({dim_col: dim, 'Real Acum.': cb_tot, '% Margen': cb_tot / vn_tot if vn_tot > 0 else None})
    rows.append({dim_col: 'TOTAL', 'Real Acum.': t_cb, '% Margen': t_cb / t_vn if t_vn > 0 else None})
    return pd.DataFrame(rows)


_Q_MAP = {'Q1': [1,2,3], 'Q2': [4,5,6], 'Q3': [7,8,9], 'Q4': [10,11,12]}


def _lin_for_mes(mes_str: str) -> float:
    """Linealidad 0→1 for a given month string 'YYYY-MM'."""
    cur = _TODAY.strftime('%Y-%m')
    if mes_str > cur:
        return 0.0
    if mes_str < cur:
        return 1.0
    ts   = pd.Timestamp(mes_str + '-01')
    dias = (ts + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
    return _TODAY.day / dias


def _periodo_filter(key_prefix: str, yr: str, meses_disp: list,
                    default_last: bool = True, full_quarter: bool = False) -> list:
    """Render period selector. Returns [(mes_str, linealidad), ...].

    full_quarter=True  → quarter selection returns all 3 months (including future, lin=0).
                         Use in Cómo Vamos to show the full Q budget vs elapsed real.
    full_quarter=False → quarter selection only returns months present in meses_disp.
                         Use in Comp. tabs to avoid showing -100% VAR% for future months.
    S1/S2/Año          → always returns all months of the period (including future with lin=0).
    """
    meses_yr = sorted([m for m in meses_disp if m.startswith(yr)])
    if not meses_yr:
        return []
    all_yr = [f'{yr}-{str(n).zfill(2)}' for n in range(1, 13)]
    s1_all = [m for m in all_yr if int(m[5:7]) <= 6]
    s2_all = [m for m in all_yr if int(m[5:7]) >= 7]
    # Build options: individual months first, then quarters, then semesters and full year
    opts = []  # (kind, value, label)
    for m in meses_yr:
        opts.append(('mes', m, pd.Timestamp(m + '-01').strftime('%b %Y')))
    for q, nums in _Q_MAP.items():
        if any(m for m in meses_yr if int(m[5:7]) in nums):
            opts.append(('q', q, f'{q} {yr}'))
    if any(m in meses_yr for m in s1_all):
        opts.append(('sem', 'S1', f'S1 {yr}'))
    if any(m in meses_yr for m in s2_all):
        opts.append(('sem', 'S2', f'S2 {yr}'))
    opts.append(('ano', yr, f'Año {yr}'))
    labels = [o[2] for o in opts]
    default_idx = (len(meses_yr) - 1) if default_last else 0
    sel = st.selectbox('Período', labels, index=default_idx, key=f'{key_prefix}_periodo')
    kind, val, _ = next(o for o in opts if o[2] == sel)
    if kind == 'mes':
        meses_sel = [val]
    elif kind == 'q':
        nums = _Q_MAP[val]
        if full_quarter:
            meses_sel = [f'{yr}-{str(n).zfill(2)}' for n in sorted(nums)]
        else:
            meses_sel = [m for m in meses_yr if int(m[5:7]) in nums]
    elif kind == 'sem':
        meses_sel = s1_all if val == 'S1' else s2_all
    else:  # ano
        meses_sel = all_yr
    return [(m, _lin_for_mes(m)) for m in meses_sel]


def _periodo_label(meses_lin: list, yr: str) -> str:
    """Human-readable label for a period."""
    if not meses_lin:
        return ''
    meses = [m for m, _ in meses_lin]
    if len(meses) == 1:
        return pd.Timestamp(meses[0] + '-01').strftime('%B %Y').upper()
    months_nums = sorted([int(m[5:7]) for m in meses])
    for q, nums in _Q_MAP.items():
        if months_nums == sorted(nums):
            return f'{q} {yr}'
    if months_nums == list(range(1, 7)):
        return f'S1 {yr}'
    if months_nums == list(range(7, 13)):
        return f'S2 {yr}'
    if months_nums == list(range(1, 13)):
        return f'AÑO {yr}'
    return ' · '.join(pd.Timestamp(m + '-01').strftime('%b') for m in meses) + f' {yr}'


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════
def render():
    st.title("📊 Análisis de Planificación")
    st.caption("Seguimiento comercial vs PPTO + estado supply chain.")

    with st.sidebar:
        if st.button("🔄 Limpiar cache", help="Fuerza recarga de datos desde disco"):
            cargar_ppto_canal.clear()
            cargar_ppto_marca.clear()
            _cargar_ventas_ytd.clear()
            st.rerun()

    # ── Load all data ─────────────────────────────────────────────────
    with st.spinner("Cargando datos..."):
        df_ventas     = _cargar_ventas_ytd()
        df_ppto_canal = cargar_ppto_canal()
        df_ppto_marca = cargar_ppto_marca()
        df_base       = _preparar_datos()
        costo_map     = cargar_costo_unit_sku()
        df_tr_raw     = cargar_transito()
        _tr_piv       = _build_transit_pivot()

    # ── Detect months ─────────────────────────────────────────────────
    meses_disp  = sorted(df_ventas['mes'].dropna().unique()) if not df_ventas.empty else []
    ultimo_mes  = meses_disp[-1] if meses_disp else (_TODAY - pd.DateOffset(months=1)).strftime('%Y-%m')
    yr          = str(_TODAY.year)

    ytd_meses = sorted({
        m for m in (df_ppto_canal['mes'].dropna().tolist() if not df_ppto_canal.empty else [])
        if m <= ultimo_mes and m.startswith(yr)
    }) if not df_ppto_canal.empty else meses_disp

    # ── Warnings ──────────────────────────────────────────────────────
    if df_ventas.empty:
        st.warning("⚠️ `data/historico/ventas_historico.parquet` no encontrado.")
    if df_ppto_canal.empty or df_ppto_marca.empty:
        st.warning("⚠️ Parquets PPTO no encontrados — ejecutar: `python extract_ppto_snapshot.py`")

    # ── Pre-build pivots ──────────────────────────────────────────────
    def _safe_piv(df, idx, col, val):
        if df.empty: return pd.DataFrame()
        return df.pivot_table(index=idx, columns=col, values=val, aggfunc='sum').fillna(0)

    real_marca_piv        = _safe_piv(df_ventas, 'marca_ppto', 'mes', 'venta_neta')
    real_canal_piv        = _safe_piv(df_ventas, 'canal_ppto', 'mes', 'venta_neta')
    real_contrib_piv      = _safe_piv(df_ventas, 'marca_ppto', 'mes', 'margen_front')
    real_contrib_canal_piv = _safe_piv(df_ventas, 'canal_ppto', 'mes', 'margen_front')
    meta_marca_piv        = _safe_piv(df_ppto_marca, 'marca', 'mes', 'meta_venta_neta')
    meta_canal_piv        = _safe_piv(df_ppto_canal, 'canal', 'mes', 'meta_venta_neta')

    # ── Planning horizon (6 months from today) ────────────────────────
    N_MESES = 6
    meses_plan  = [(_TODAY + pd.DateOffset(months=i)).strftime('%Y-%m') for i in range(N_MESES)]
    labels_plan = [(_TODAY + pd.DateOffset(months=i)).strftime('%b %y') for i in range(N_MESES)]

    # PPTO forecast by SKU
    _ppto_piv_plan = pd.DataFrame()
    _p_path = DATA_DIR / 'planificacion' / 'snapshots' / 'planif_forecast_manual.parquet'
    if _p_path.exists():
        _dp = pd.read_parquet(_p_path)
        _dp['sku']      = _dp['sku'].astype(str)
        _dp['unidades'] = pd.to_numeric(_dp['unidades'], errors='coerce').fillna(0)
        _ppto_piv_plan  = _dp.pivot_table(index='sku', columns='mes', values='unidades', aggfunc='sum').fillna(0)

    # ── TABS ──────────────────────────────────────────────────────────
    (tab_como, tab_comp_m, tab_comp_c,
     tab_cst, tab_crit, tab_tr, tab_nv) = st.tabs([
        "📊 Cómo Vamos",
        "📈 Comp. Marcas",
        "📈 Comp. Canales",
        "💰 CST x Marca",
        "🔴 Detalle Crítico",
        "🚢 Tránsitos",
        "🆕 Nuevos en Tránsito",
    ])

    # Dims disponibles (calculados una vez, reutilizados en los 3 tabs)
    _all_marcas = sorted(set(
        (real_marca_piv.index.tolist() if not real_marca_piv.empty else []) +
        (meta_marca_piv.index.tolist() if not meta_marca_piv.empty else [])
    ))
    _all_canales = _CANALES_DISPLAY

    # ════════════════════════════════════════════════════════════════
    # TAB 1: CÓMO VAMOS
    # ════════════════════════════════════════════════════════════════
    with tab_como:
        st.subheader(f"Cómo Vamos — {yr}")

        if not ytd_meses:
            st.info("Sin datos disponibles.")
        else:
            # ── Filtros ───────────────────────────────────────────────
            col_f1, col_f2, col_f3 = st.columns([2, 4, 4])
            with col_f1:
                meses_lin_cv = _periodo_filter('cv', yr, ytd_meses, full_quarter=True)
            with col_f2:
                marcas_cv = st.multiselect('Marcas', _all_marcas, default=_all_marcas, key='cv_marcas')
            with col_f3:
                canales_cv = st.multiselect('Canales', _all_canales, default=_all_canales, key='cv_canales')

            if not meses_lin_cv:
                st.info("Sin datos para el período seleccionado.")
            else:
                marcas_f  = marcas_cv  if marcas_cv  else _all_marcas
                canales_f = canales_cv if canales_cv else _all_canales
                per_lbl   = _periodo_label(meses_lin_cv, yr)

                # Linealidad info (solo mes único)
                if len(meses_lin_cv) == 1:
                    mes0, lin0 = meses_lin_cv[0]
                    ts0 = pd.Timestamp(mes0 + '-01')
                    dias0 = (ts0 + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
                    dia0  = round(lin0 * dias0)
                    st.info(f"📅 **{per_lbl}** · Linealidad día **{dia0}/{dias0}** = **{lin0:.1%}**")
                else:
                    st.info(f"📅 Período: **{per_lbl}** · " +
                            " | ".join(pd.Timestamp(m+'-01').strftime('%b') for m, _ in meses_lin_cv))

                # ── Resumen KPIs ──────────────────────────────────────
                def _sum_piv(piv, dims, meses_lin):
                    return sum(
                        (float(piv.at[d, m]) if (not piv.empty and d in piv.index and m in piv.columns) else 0.0)
                        for d in dims for m, _ in meses_lin
                    )
                def _sum_piv_lin(piv, dims, meses_lin):
                    return sum(
                        (float(piv.at[d, m]) if (not piv.empty and d in piv.index and m in piv.columns) else 0.0) * lin
                        for d in dims for m, lin in meses_lin
                    )

                t_meta_cv  = _sum_piv(meta_marca_piv, marcas_f, meses_lin_cv)
                t_real_cv  = _sum_piv(real_marca_piv, marcas_f, meses_lin_cv)
                t_mlin_cv  = _sum_piv_lin(meta_marca_piv, marcas_f, meses_lin_cv)
                t_cb_cv    = _sum_piv(real_contrib_piv, marcas_f, meses_lin_cv)

                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Meta Período VN", _fmt_m(t_meta_cv))
                c2.metric("Meta Lineal", _fmt_m(t_mlin_cv))
                c3.metric("Real Acum. VN", _fmt_m(t_real_cv),
                          delta=f"{t_real_cv/t_mlin_cv-1:+.1%} vs lineal" if t_mlin_cv > 0 else None)
                c4.metric("% vs Meta", f"{t_real_cv/t_meta_cv:.1%}" if t_meta_cv > 0 else "—")
                c5.metric("Contrib. Real", _fmt_m(t_cb_cv),
                          delta=f"{t_cb_cv/t_real_cv:.1%} margen" if t_real_cv > 0 else None,
                          delta_color="off")

                st.divider()

                # ── VN por Marca ──────────────────────────────────────
                st.markdown("#### Venta Neta por Marca")
                _mf = marcas_f if len(marcas_f) < len(_all_marcas) else None
                df_cv_m, lin_hdr = _build_cv_table(real_marca_piv, meta_marca_piv, 'Marca', meses_lin_cv, dims_filter=_mf)
                _show_cv(df_cv_m, 'Marca', lin_hdr)
                _dl(df_cv_m, f"cv_vn_marca_{per_lbl}.csv")

                st.divider()

                # ── Contribución por Marca ────────────────────────────
                st.markdown("#### Contribución Frontal por Marca")
                st.caption("_Meta contribución no disponible en PPTO._")
                df_cbm = _build_contrib_cv(real_contrib_piv, real_marca_piv, 'Marca', meses_lin_cv, dims_filter=_mf)
                _show_contrib(df_cbm, 'Marca')
                _dl(df_cbm, f"cv_contrib_marca_{per_lbl}.csv")

                st.divider()

                # ── VN por Canal ──────────────────────────────────────
                st.markdown("#### Venta Neta por Canal")
                _cf = canales_f if canales_f else _all_canales
                df_cv_c, lin_hdr_c = _build_cv_table(real_canal_piv, meta_canal_piv, 'Canal', meses_lin_cv, dims_filter=_cf)
                _show_cv(df_cv_c, 'Canal', lin_hdr_c)
                _dl(df_cv_c, f"cv_vn_canal_{per_lbl}.csv")

                st.divider()

                # ── Contribución por Canal ────────────────────────────
                st.markdown("#### Contribución Frontal por Canal")
                st.caption("_Meta contribución no disponible en PPTO._")
                df_cbc = _build_contrib_cv(real_contrib_canal_piv, real_canal_piv, 'Canal', meses_lin_cv, dims_filter=_cf)
                _show_contrib(df_cbc, 'Canal')
                _dl(df_cbc, f"cv_contrib_canal_{per_lbl}.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 2: COMP. MARCAS
    # ════════════════════════════════════════════════════════════════
    with tab_comp_m:
        st.subheader(f"Comparativo por Marca — {yr}")
        if not ytd_meses:
            st.info("Sin meses disponibles.")
        else:
            # ── Filtros ───────────────────────────────────────────────
            col_f1, col_f2 = st.columns([2, 5])
            with col_f1:
                meses_lin_cm = _periodo_filter('comp_m', yr, ytd_meses)
            with col_f2:
                marcas_cm = st.multiselect('Marcas', _all_marcas, default=_all_marcas, key='comp_m_marcas')

            if not meses_lin_cm:
                st.info("Sin datos para el período seleccionado.")
            else:
                marcas_f_cm = marcas_cm if marcas_cm else _all_marcas
                meses_cm    = [m for m, _ in meses_lin_cm]
                per_lbl_cm  = _periodo_label(meses_lin_cm, yr)

                # Nota linealidad último mes del período seleccionado
                _um_cm  = meses_cm[-1]
                _ts_cm  = pd.Timestamp(_um_cm + '-01')
                _dias_cm = (_ts_cm + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
                _dia_cm  = _TODAY.day if _um_cm >= _TODAY.strftime('%Y-%m') else _dias_cm
                _lin_cm  = _dia_cm / _dias_cm
                st.caption(
                    f"Período: **{per_lbl_cm}** "
                    f"({'parcial al día ' + str(_dia_cm) + ' de ' + str(_dias_cm) + ' — ' if _um_cm >= _TODAY.strftime('%Y-%m') else ''}"
                    f"linealidad {_lin_cm:.1%})  ·  Valores en $M CLP"
                )

                # ── Resumen KPIs ──────────────────────────────────────
                _mf_cm = marcas_f_cm if len(marcas_f_cm) < len(_all_marcas) else None
                t_meta_cm = sum(
                    (float(meta_marca_piv.at[d, m]) if (not meta_marca_piv.empty and d in meta_marca_piv.index and m in meta_marca_piv.columns) else 0.0)
                    for d in marcas_f_cm for m in meses_cm
                )
                t_real_cm = sum(
                    (float(real_marca_piv.at[d, m]) if (not real_marca_piv.empty and d in real_marca_piv.index and m in real_marca_piv.columns) else 0.0)
                    for d in marcas_f_cm for m in meses_cm
                )
                t_cb_cm = sum(
                    (float(real_contrib_piv.at[d, m]) if (not real_contrib_piv.empty and d in real_contrib_piv.index and m in real_contrib_piv.columns) else 0.0)
                    for d in marcas_f_cm for m in meses_cm
                )
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Meta Período VN", _fmt_m(t_meta_cm))
                c2.metric("Real Período VN", _fmt_m(t_real_cm),
                          delta=f"{t_real_cm/t_meta_cm-1:+.1%} vs meta" if t_meta_cm > 0 else None)
                c3.metric("Contrib. Real", _fmt_m(t_cb_cm))
                c4.metric("% Margen", f"{t_cb_cm/t_real_cm:.1%}" if t_real_cm > 0 else "—")

                st.divider()
                st.markdown("#### Venta Neta")
                df_vn = _build_comp_agg(real_marca_piv, meta_marca_piv, meses_cm, 'Marca', dims_filter=_mf_cm)
                _show_comp_agg(df_vn, 'Marca')
                _dl(df_vn, f"comp_marcas_vn_{per_lbl_cm}.csv")

                st.divider()
                st.markdown("#### Contribución Frontal")
                st.caption("_Real por mes (suma de margen\\_front desde Odoo). % Margen = Contribución Real / Venta Neta Real. Meta contribución no disponible._")
                df_cb_m = _build_contrib_ytd(real_contrib_piv, real_marca_piv, meses_cm, 'Marca', dims_filter=_mf_cm)
                _show_contrib_ytd(df_cb_m, 'Marca')
                _dl(df_cb_m, f"comp_marcas_contrib_{per_lbl_cm}.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 3: COMP. CANALES
    # ════════════════════════════════════════════════════════════════
    with tab_comp_c:
        st.subheader(f"Comparativo por Canal — {yr}")
        if not ytd_meses:
            st.info("Sin meses disponibles.")
        else:
            # ── Filtros ───────────────────────────────────────────────
            meses_lin_cc = _periodo_filter('comp_c', yr, ytd_meses)

            if not meses_lin_cc:
                st.info("Sin datos para el período seleccionado.")
            else:
                meses_cc     = [m for m, _ in meses_lin_cc]
                per_lbl_cc   = _periodo_label(meses_lin_cc, yr)

                _um_cc   = meses_cc[-1]
                _ts_cc   = pd.Timestamp(_um_cc + '-01')
                _dias_cc = (_ts_cc + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
                _dia_cc  = _TODAY.day if _um_cc >= _TODAY.strftime('%Y-%m') else _dias_cc
                _lin_cc  = _dia_cc / _dias_cc
                st.caption(
                    f"Período: **{per_lbl_cc}** "
                    f"({'parcial al día ' + str(_dia_cc) + ' de ' + str(_dias_cc) + ' — ' if _um_cc >= _TODAY.strftime('%Y-%m') else ''}"
                    f"linealidad {_lin_cc:.1%})  ·  Valores en $M CLP"
                )

                # ── Filtro canales (bajo el período, antes de las tablas) ──
                canales_cc   = st.multiselect('Canales', _all_canales, default=_all_canales, key='comp_c_canales')
                canales_f_cc = canales_cc if canales_cc else _all_canales
                _cf_cc       = canales_f_cc

                # ── Resumen KPIs ──────────────────────────────────────
                t_meta_cc = sum(
                    (float(meta_canal_piv.at[d, m]) if (not meta_canal_piv.empty and d in meta_canal_piv.index and m in meta_canal_piv.columns) else 0.0)
                    for d in canales_f_cc for m in meses_cc
                )
                t_real_cc = sum(
                    (float(real_canal_piv.at[d, m]) if (not real_canal_piv.empty and d in real_canal_piv.index and m in real_canal_piv.columns) else 0.0)
                    for d in canales_f_cc for m in meses_cc
                )
                t_cb_cc = sum(
                    (float(real_contrib_canal_piv.at[d, m]) if (not real_contrib_canal_piv.empty and d in real_contrib_canal_piv.index and m in real_contrib_canal_piv.columns) else 0.0)
                    for d in canales_f_cc for m in meses_cc
                )
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Meta Período VN", _fmt_m(t_meta_cc))
                c2.metric("Real Período VN", _fmt_m(t_real_cc),
                          delta=f"{t_real_cc/t_meta_cc-1:+.1%} vs meta" if t_meta_cc > 0 else None)
                c3.metric("Contrib. Real", _fmt_m(t_cb_cc))
                c4.metric("% Margen", f"{t_cb_cc/t_real_cc:.1%}" if t_real_cc > 0 else "—")

                st.divider()
                st.markdown("#### Venta Neta")
                df_vc = _build_comp_agg(real_canal_piv, meta_canal_piv, meses_cc, 'Canal', dims_filter=_cf_cc)
                _show_comp_agg(df_vc, 'Canal')
                _dl(df_vc, f"comp_canales_vn_{per_lbl_cc}.csv")

                st.divider()
                st.markdown("#### Contribución Frontal")
                st.caption("_Real por mes (suma de margen\\_front desde Odoo). % Margen = Contribución Real / Venta Neta Real. Meta contribución no disponible._")
                df_cb_c = _build_contrib_ytd(real_contrib_canal_piv, real_canal_piv, meses_cc, 'Canal', dims_filter=_cf_cc)
                _show_contrib_ytd(df_cb_c, 'Canal')
                _dl(df_cb_c, f"comp_canales_contrib_{per_lbl_cc}.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 4: CST x MARCA
    # ════════════════════════════════════════════════════════════════
    with tab_cst:
        st.subheader("💰 Cobertura a Costo por Marca")
        st.caption(f"Proyección {N_MESES} meses desde {_TODAY.strftime('%b %Y')}. Valores en $M CLP.")

        if df_base.empty:
            st.info("Sin datos de planificación disponibles.")
        else:
            _df_c = df_base[df_base['marca'].notna() & ~df_base['marca'].isin({'Sin clasificar', ''})].copy()
            _df_c['sku_s'] = _df_c['sku'].astype(str)
            _df_c['_cu']   = _df_c['sku_s'].map(costo_map).fillna(0)
            _df_c['_sk_c'] = _df_c['stock_actual'].astype(float) * _df_c['_cu']
            _df_c['_vt_c'] = _df_c['venta_prom_3m'].astype(float) * _df_c['_cu']

            # Pre-compute PPTO monthly arrays
            _all_skus = _df_c['sku_s'].values
            _ppto_arr = []
            for ms in meses_plan:
                _ppto_arr.append(
                    _ppto_piv_plan[ms].reindex(_all_skus, fill_value=0).values.astype(float)
                    if ms in _ppto_piv_plan.columns else np.zeros(len(_df_c))
                )

            brand_rows = []
            for marca, grp in _df_c.groupby('marca', sort=False):
                mask_g = np.isin(_all_skus, grp['sku_s'].values)
                sk_tot = grp['_sk_c'].sum() / 1e6
                vt_tot = grp['_vt_c'].sum() / 1e6
                cob_a  = round(sk_tot / vt_tot, 1) if vt_tot > 0 else None

                row_b = {'Marca': marca, 'Stock Hoy ($M)': round(sk_tot, 1), 'Cob. ACT': cob_a}

                _stk_v = grp['_sk_c'].values.astype(float).copy()
                for i, (ms, ml) in enumerate(zip(meses_plan, labels_plan)):
                    # Transit in cost
                    if ms in _tr_piv.columns:
                        _tr_u = _tr_piv[ms].reindex(grp['sku_s'], fill_value=0).values.astype(float)
                    else:
                        _tr_u = np.zeros(len(grp))
                    _tr_c = _tr_u * grp['_cu'].values
                    _tr_tot = _tr_c.sum() / 1e6

                    # Venta: use PPTO if available, else 3m avg
                    _vt_ppto = (_ppto_arr[i][mask_g] * grp['_cu'].values).sum() / 1e6
                    _vt_ms   = _vt_ppto if _vt_ppto > 0 else vt_tot

                    _stk_ini = _stk_v.sum() / 1e6
                    _stk_ped = _stk_ini + _tr_tot
                    _cob_m   = round(_stk_ped / _vt_ms, 1) if _vt_ms > 0 else None

                    _lbl = pd.Timestamp(ms + '-01').strftime('%b')
                    row_b[f'{_lbl} Stk($M)'] = round(_stk_ini, 1)
                    row_b[f'{_lbl} Leg($M)'] = round(_tr_tot, 1)
                    row_b[f'{_lbl} S+P($M)'] = round(_stk_ped, 1)
                    row_b[f'{_lbl} Vta($M)'] = round(_vt_ms, 1)
                    row_b[f'{_lbl} Cob.']    = _cob_m

                    # Next month stock
                    _vt_ppto_u = _ppto_arr[i][mask_g]
                    _stk_v     = np.maximum(0.0, _stk_v + _tr_c - _vt_ppto_u * grp['_cu'].values)

                brand_rows.append(row_b)

            df_cst_m = pd.DataFrame(brand_rows).sort_values('Stock Hoy ($M)', ascending=False)

            num_cst  = [c for c in df_cst_m.columns if '$M' in c]
            cob_cst  = [c for c in df_cst_m.columns if c.endswith('Cob.') or c == 'Cob. ACT']
            fmt_cst  = {c: (lambda v: f"${v:.1f}M" if pd.notna(v) else "—") for c in num_cst}
            fmt_cst.update({c: _fmt_cob for c in cob_cst})

            st.dataframe(
                df_cst_m.style.format(fmt_cst),
                use_container_width=True, hide_index=True
            )
            _dl(df_cst_m, f"cst_x_marca_{_TODAY.strftime('%Y-%m')}.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 5: DETALLE CRÍTICO
    # ════════════════════════════════════════════════════════════════
    with tab_crit:
        st.subheader("🔴 Detalle Crítico — Cobertura < 1 mes")

        if df_base.empty:
            st.info("Sin datos de planificación disponibles.")
        else:
            _df_cr = df_base[
                df_base['cobertura_fc3m_meses'].notna() &
                (df_base['cobertura_fc3m_meses'] < 1) &
                df_base['marca'].notna() &
                ~df_base['marca'].isin({'Sin clasificar', ''}) &
                (df_base['stock_actual'] > 0)
            ].copy()

            n_cr = len(_df_cr)
            c1c, c2c = st.columns(2)
            c1c.metric("SKUs críticos (<1m)", n_cr)
            c2c.metric("Marcas afectadas", _df_cr['marca'].nunique())

            if _df_cr.empty:
                st.success("✅ No hay SKUs con cobertura crítica en este momento.")
            else:
                # Add next-3m transit
                _df_cr['_cu'] = _df_cr['sku'].astype(str).map(costo_map).fillna(0)
                next3 = meses_plan[:3]
                for ms in next3:
                    lbl = pd.Timestamp(ms + '-01').strftime('%b')
                    _df_cr[f'Leg {lbl}'] = (
                        _tr_piv[ms].reindex(_df_cr['sku'].astype(str), fill_value=0).values.astype(int)
                        if ms in _tr_piv.columns else 0
                    )
                leg_cols = [f'Leg {pd.Timestamp(ms+"-01").strftime("%b")}' for ms in next3]
                _df_cr['Llegadas (u)'] = _df_cr[leg_cols].sum(axis=1)

                rename_cr = {
                    'marca': 'Marca', 'categoria_padre': 'Cat. Padre',
                    'sku': 'SKU', 'producto': 'Descripción',
                    'stock_actual': 'Stock (u)', 'venta_prom_3m': 'Vta/mes (u)',
                    'cobertura_fc3m_meses': 'Cob. (m)',
                }
                show_cr_cols = list(rename_cr.keys()) + leg_cols + ['Llegadas (u)']
                _df_cr_show = (
                    _df_cr[[c for c in show_cr_cols if c in _df_cr.columns]]
                    .rename(columns=rename_cr)
                    .sort_values('Cob. (m)')
                    .reset_index(drop=True)
                )
                fmt_cr = {
                    'Cob. (m)': _fmt_cob,
                    'Vta/mes (u)': lambda v: f"{v:.0f}" if pd.notna(v) else "—",
                }
                st.dataframe(_df_cr_show.style.format(fmt_cr), use_container_width=True, hide_index=True)
                _dl(_df_cr_show, f"detalle_critico_{_TODAY.strftime('%Y-%m')}.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 6: TRÁNSITOS POR EMBARQUE
    # ════════════════════════════════════════════════════════════════
    with tab_tr:
        st.subheader("🚢 Tránsitos por Embarque (PI)")

        if df_tr_raw.empty:
            st.info("Sin datos de tránsito COMEX disponibles.")
        else:
            _df_tr = df_tr_raw.copy()
            _df_tr['fecha_eta_bodega'] = pd.to_datetime(_df_tr['fecha_eta_bodega'], errors='coerce')
            _df_tr['cantidad'] = pd.to_numeric(_df_tr['cantidad'], errors='coerce').fillna(0)

            has_pi  = 'pi' in _df_tr.columns
            has_usd = 'costo_total_usd' in _df_tr.columns
            has_clp = 'costo_ingreso_clp' in _df_tr.columns

            if has_pi:
                agg = {'sku': 'nunique', 'cantidad': 'sum', 'fecha_eta_bodega': 'max'}
                if has_usd: agg['costo_total_usd'] = 'sum'
                if has_clp: agg['costo_ingreso_clp'] = 'sum'
                if 'status' in _df_tr.columns:
                    agg['status'] = lambda x: x.mode().iloc[0] if len(x) > 0 else '—'

                df_pi_grp = _df_tr.groupby('pi').agg(agg).reset_index()
                df_pi_grp.rename(columns={
                    'pi': 'PI', 'sku': 'N° SKUs', 'cantidad': 'Unidades',
                    'fecha_eta_bodega': 'ETA Bodega',
                    'costo_total_usd': 'USD Total',
                    'costo_ingreso_clp': 'CLP Total',
                    'status': 'Estado',
                }, inplace=True)
                df_pi_grp = df_pi_grp.sort_values('ETA Bodega', na_position='last')

                c1t, c2t, c3t = st.columns(3)
                c1t.metric("Embarques en tránsito", len(df_pi_grp))
                c2t.metric("SKUs únicos", int(_df_tr['sku'].nunique()))
                c3t.metric("Unidades totales", f"{int(_df_tr['cantidad'].sum()):,}")

                fmt_pi = {}
                if 'USD Total' in df_pi_grp.columns:
                    fmt_pi['USD Total'] = lambda v: f"${v:,.0f}" if pd.notna(v) else "—"
                if 'CLP Total' in df_pi_grp.columns:
                    fmt_pi['CLP Total'] = lambda v: f"${v/1e6:.1f}M" if pd.notna(v) else "—"
                if 'ETA Bodega' in df_pi_grp.columns:
                    fmt_pi['ETA Bodega'] = lambda v: v.strftime('%d/%m/%Y') if pd.notna(v) else "—"

                st.dataframe(df_pi_grp.style.format(fmt_pi), use_container_width=True, hide_index=True)
                _dl(df_pi_grp, f"transitos_por_embarque_{_TODAY.strftime('%Y-%m')}.csv")

                with st.expander("🔍 Detalle por SKU dentro de un PI"):
                    pi_list = df_pi_grp['PI'].tolist()
                    if pi_list:
                        pi_sel = st.selectbox("Seleccionar embarque", pi_list, key='pi_sel_tr')
                        df_det = _df_tr[_df_tr['pi'] == pi_sel].copy()
                        det_show = ['sku', 'cantidad', 'fecha_eta_bodega']
                        if has_usd: det_show.append('costo_total_usd')
                        if 'status' in df_det.columns: det_show.append('status')
                        st.dataframe(df_det[[c for c in det_show if c in df_det.columns]],
                                     use_container_width=True, hide_index=True)
            else:
                st.dataframe(_df_tr.head(500), use_container_width=True, hide_index=True)
                _dl(_df_tr, f"transitos_{_TODAY.strftime('%Y-%m')}.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 7: NUEVOS EN TRÁNSITO
    # ════════════════════════════════════════════════════════════════
    with tab_nv:
        st.subheader("🆕 Nuevos Productos en Tránsito")
        st.caption("SKUs con **Categoria Comercial = Nuevo** con llegadas en los próximos meses (FCST + COMEX).")

        if df_base.empty:
            st.info("Sin datos de planificación disponibles.")
        else:
            # ── Identify Nuevo SKUs via categoria_producto (= Categoria Comercial en FCST Excel) ──
            if 'categoria_producto' in df_base.columns:
                _df_nuevos_master = df_base[
                    df_base['categoria_producto'].str.strip().str.lower() == 'nuevo'
                ][['sku', 'producto', 'marca', 'categoria_padre', 'categoria_hijo',
                   'categoria_producto', 'stock_actual']].drop_duplicates('sku').copy()
            else:
                _df_nuevos_master = df_base[df_base['stock_actual'] == 0][
                    ['sku', 'producto', 'marca', 'categoria_padre', 'categoria_hijo', 'stock_actual']
                ].drop_duplicates('sku').copy()

            _df_nuevos_master['sku'] = _df_nuevos_master['sku'].astype(str)
            _nuevos_skus_set = set(_df_nuevos_master['sku'].unique())

            n_nuevos_master = len(_df_nuevos_master)
            st.metric("SKUs Nuevo (Categoria Comercial)", n_nuevos_master)

            if _tr_piv.empty and df_tr_raw.empty:
                st.info("Sin datos de tránsito disponibles.")
            else:
                # ── Build monthly arrivals from the combined transit pivot ──
                meses_futuros = [ms for ms in meses_plan if ms >= _TODAY.strftime('%Y-%m')]
                _tr_piv_nuevos = pd.DataFrame()
                if not _tr_piv.empty:
                    _tr_piv_nuevos = _tr_piv.loc[
                        _tr_piv.index.isin(_nuevos_skus_set),
                        [ms for ms in meses_futuros if ms in _tr_piv.columns]
                    ].copy()
                    # Keep only SKUs with at least 1 unit incoming
                    _tr_piv_nuevos = _tr_piv_nuevos[_tr_piv_nuevos.sum(axis=1) > 0]

                if _tr_piv_nuevos.empty:
                    st.info("✅ No hay nuevos SKUs con llegadas en el FCST o COMEX para los próximos meses.")
                else:
                    _tr_piv_nuevos.index.name = 'sku'
                    _df_nv_grid = _tr_piv_nuevos.reset_index().merge(
                        _df_nuevos_master, on='sku', how='left'
                    )

                    # Friendly column names for month arrivals
                    mes_rename_nv = {ms: pd.Timestamp(ms + '-01').strftime('%b %y') for ms in meses_futuros if ms in _df_nv_grid.columns}
                    _df_nv_grid = _df_nv_grid.rename(columns=mes_rename_nv)
                    _arrival_cols = list(mes_rename_nv.values())

                    # Total col
                    _df_nv_grid['Total (u)'] = _df_nv_grid[_arrival_cols].sum(axis=1)

                    # Ordered columns
                    base_cols = ['sku', 'producto', 'marca', 'categoria_padre', 'categoria_hijo']
                    if 'categoria_producto' in _df_nv_grid.columns:
                        base_cols.insert(3, 'categoria_producto')
                    base_cols += ['stock_actual']
                    rename_base = {
                        'sku': 'SKU', 'producto': 'Descripción', 'marca': 'Marca',
                        'categoria_padre': 'Cat. Padre', 'categoria_hijo': 'Cat. Hijo',
                        'categoria_producto': 'Cat. Comercial', 'stock_actual': 'Stock Hoy',
                    }
                    _df_nv_show = (
                        _df_nv_grid[[c for c in base_cols if c in _df_nv_grid.columns] + _arrival_cols + ['Total (u)']]
                        .rename(columns=rename_base)
                        .sort_values(['Marca', 'Total (u)'], ascending=[True, False])
                        .reset_index(drop=True)
                    )

                    n_con_llegada = len(_df_nv_show)
                    c1n, c2n, c3n = st.columns(3)
                    c1n.metric("Nuevos con llegadas", n_con_llegada)
                    c2n.metric("Total unidades", f"{int(_df_nv_show['Total (u)'].sum()):,}")
                    c3n.metric("Marcas", _df_nv_show['Marca'].nunique() if 'Marca' in _df_nv_show.columns else "—")

                    # Int format for arrival cols
                    fmt_nv_show = {c: lambda v: f"{int(v):,}" if pd.notna(v) and v > 0 else "—" for c in _arrival_cols + ['Total (u)']}
                    st.dataframe(
                        _df_nv_show.style.format(fmt_nv_show),
                        use_container_width=True, hide_index=True
                    )
                    _dl(_df_nv_show, f"nuevos_transito_{_TODAY.strftime('%Y-%m')}.csv")
