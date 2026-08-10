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
    'UMA': 'UMA',
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

    # Separación estricta por mes: historico = meses cerrados (<mes corriente),
    # mes_actual = solo el mes corriente en curso. Esto evita doble conteo si el
    # parquet de historico fue regenerado incluyendo datos del mes abierto.
    # Separación estricta por mes: historico = meses cerrados (<mes corriente),
    # mes_actual = solo el mes corriente, hasta ayer (la venta cierra al día anterior).
    mes_corriente = _TODAY.to_period('M').strftime('%Y-%m')
    ayer = (_TODAY - pd.Timedelta(days=1)).date()
    if df_hist is not None and not df_hist.empty:
        fechas_hist = pd.to_datetime(df_hist['fecha_venta'], errors='coerce')
        df_hist = df_hist[fechas_hist.dt.to_period('M').astype(str) < mes_corriente]
    if df_mes is not None and not df_mes.empty:
        fechas_mes = pd.to_datetime(df_mes['fecha_venta'], errors='coerce')
        df_mes = df_mes[
            (fechas_mes.dt.to_period('M').astype(str) == mes_corriente) &
            (fechas_mes.dt.date <= ayer)
        ]

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


@st.cache_data(ttl=1800, show_spinner=False)
def _cargar_6w_costo() -> dict:
    """Returns {brand_std: monthly_rate_M} — cost consumption based on last 6 weeks of actual sales.
    Monthly rate = 6-week total costo_total / 42 days * 30.44 days/month.
    """
    need = ['fecha_venta', 'marca', 'costo_total']
    path_hist = DATA_DIR / 'historico' / 'ventas_historico.parquet'
    path_mes  = DATA_DIR / 'historico' / 'ventas_mes_actual.parquet'

    frames = []
    for p in (path_hist, path_mes):
        if not p.exists():
            continue
        try:
            frames.append(pd.read_parquet(p, columns=need))
        except Exception:
            try:
                d = pd.read_parquet(p)
                avail = [c for c in need if c in d.columns]
                if avail:
                    frames.append(d[avail])
            except Exception:
                pass

    if not frames:
        return {}

    df = pd.concat(frames, ignore_index=True)
    df['fecha'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.date
    df['costo_total'] = pd.to_numeric(df['costo_total'], errors='coerce').fillna(0)

    today = pd.Timestamp.today().normalize()
    ayer  = (today - pd.Timedelta(days=1)).date()
    hace6s = (today - pd.Timedelta(weeks=6)).date()
    df6 = df[(df['fecha'] >= hace6s) & (df['fecha'] <= ayer)]

    if df6.empty:
        return {}

    df6 = df6.copy()
    df6['marca_std'] = df6['marca'].map(
        lambda m: _MARCA_TO_PPTO.get(m, m) if isinstance(m, str) else ''
    )
    # Sum cost over 6 weeks, convert to monthly rate
    grp = df6.groupby('marca_std')['costo_total'].sum()
    monthly = grp / 42 * 30.44 / 1e6  # → $M per month
    return monthly.to_dict()


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
    if v < 2:  return f"🟠 {v:.1f}m"
    if v <= 4: return f"🟢 {v:.1f}m"
    if v <= 6: return f"🔵 {v:.1f}m"
    return f"🟣 {v:.1f}m"

_REPORT_EXCEL_PATH = DATA_DIR / 'planificacion' / 'analisis_planificacion_AGO26.xlsx'


def _dl_excel(key: str, label="⬇️ Descargar Reporte"):
    """Descarga el Excel de planificación completo."""
    if _REPORT_EXCEL_PATH.exists():
        st.download_button(
            label,
            data=_REPORT_EXCEL_PATH.read_bytes(),
            file_name=_REPORT_EXCEL_PATH.name,
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            use_container_width=True,
            key=key,
        )


def _dl(df: pd.DataFrame, filename: str, label="⬇️ Descargar Reporte"):
    _dl_excel(key=f'dl_{filename}', label=label)


def _report_csv(*sections: tuple) -> bytes:
    """Merge (title, df) pairs into one UTF-8 CSV, sections separated by a title row."""
    import io
    buf = io.StringIO()
    for i, (title, df) in enumerate(sections):
        if i > 0:
            buf.write("\n")
        buf.write(f"### {title}\n")
        df.to_csv(buf, index=False)
    return buf.getvalue().encode('utf-8-sig')


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


def _build_comp_vn_ytd(real_vn_piv, meta_vn_piv, meses, dim_col, dims_filter=None):
    """VN table: dim | mes1_real | mes2_real | ... | TOT META | TOT REAL | % CUMPL."""
    all_dims_raw = sorted(set(
        (real_vn_piv.index.tolist() if not real_vn_piv.empty else []) +
        (meta_vn_piv.index.tolist() if not meta_vn_piv.empty else [])
    ))
    all_dims = [d for d in all_dims_raw if dims_filter is None or d in set(dims_filter)]
    rows = []
    for dim in all_dims:
        row = {dim_col: dim}
        tot_r = tot_m = 0.0
        for mes in meses:
            lbl = pd.Timestamp(mes + '-01').strftime('%b')
            r = float(real_vn_piv.at[dim, mes]) if (not real_vn_piv.empty and dim in real_vn_piv.index and mes in real_vn_piv.columns) else 0.0
            m = float(meta_vn_piv.at[dim, mes]) if (not meta_vn_piv.empty and dim in meta_vn_piv.index and mes in meta_vn_piv.columns) else 0.0
            if len(meses) > 1:
                row[lbl] = r
            tot_r += r; tot_m += m
        row['TOT META'] = tot_m
        row['TOT REAL'] = tot_r
        row['% CUMPL.'] = tot_r / tot_m if tot_m > 0 else None
        rows.append(row)
    row_t = {dim_col: 'TOTAL'}
    gt_r = gt_m = 0.0
    for mes in meses:
        lbl = pd.Timestamp(mes + '-01').strftime('%b')
        r = sum(float(real_vn_piv.at[d, mes]) if (not real_vn_piv.empty and d in real_vn_piv.index and mes in real_vn_piv.columns) else 0.0 for d in all_dims)
        m = sum(float(meta_vn_piv.at[d, mes]) if (not meta_vn_piv.empty and d in meta_vn_piv.index and mes in meta_vn_piv.columns) else 0.0 for d in all_dims)
        if len(meses) > 1:
            row_t[lbl] = r
        gt_r += r; gt_m += m
    row_t['TOT META'] = gt_m; row_t['TOT REAL'] = gt_r
    row_t['% CUMPL.'] = gt_r / gt_m if gt_m > 0 else None
    rows.append(row_t)
    df = pd.DataFrame(rows)
    total_mask = df[dim_col] == 'TOTAL'
    df = pd.concat([
        df[~total_mask].sort_values('TOT META', ascending=False),
        df[total_mask]
    ]).reset_index(drop=True)
    return df


def _show_comp_vn_ytd(df, dim_col):
    """Display VN YTD table: monthly real cols + TOT META + TOT REAL + % CUMPL."""
    def _c_cumpl(v):
        if pd.isna(v): return ''
        if v >= 1.00: return 'color:#22c55e;font-weight:bold'
        if v >= 0.90: return 'color:#eab308;font-weight:bold'
        if v >= 0.70: return 'color:#f97316'
        return 'color:#ef4444'
    mon_cols = [c for c in df.columns if c not in (dim_col, 'TOT META', 'TOT REAL', '% CUMPL.')]
    fmt = {c: _fmt_m for c in mon_cols + ['TOT META', 'TOT REAL']}
    fmt['% CUMPL.'] = lambda v: f"{v:.1%}" if pd.notna(v) else "—"
    st.dataframe(
        df.style
          .format(fmt)
          .map(_c_cumpl, subset=['% CUMPL.'])
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
    df = pd.DataFrame(rows)
    total_mask = df[dim_col] == 'TOTAL'
    df = pd.concat([
        df[~total_mask].sort_values('Meta Período', ascending=False),
        df[total_mask]
    ]).reset_index(drop=True)
    return df, lin_header


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
    """Linealidad 0→1 for a given month string 'YYYY-MM'.
    Uses yesterday (day-1) because sales data closes at end of the prior day."""
    cur = _TODAY.strftime('%Y-%m')
    if mes_str > cur:
        return 0.0
    if mes_str < cur:
        return 1.0
    ts   = pd.Timestamp(mes_str + '-01')
    dias = (ts + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
    return max(0, _TODAY.day - 1) / dias


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
    if default_last:
        _cur = _TODAY.strftime('%Y-%m')
        _cur_idx = next((i for i, o in enumerate(opts) if o[0] == 'mes' and o[1] == _cur), None)
        default_idx = _cur_idx if _cur_idx is not None else len(meses_yr) - 1
    else:
        default_idx = 0
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

        _dl_excel('dl_sidebar', label="⬇️ Descargar Reporte Excel")

    # ── Load all data ─────────────────────────────────────────────────
    with st.spinner("Cargando datos..."):
        df_ventas     = _cargar_ventas_ytd()
        df_ppto_canal = cargar_ppto_canal()
        df_ppto_marca = cargar_ppto_marca()
        # UMA en ventas reales = 'Mattel' en el PPTO — normalizar para que coincidan
        if not df_ppto_marca.empty and 'marca' in df_ppto_marca.columns:
            df_ppto_marca = df_ppto_marca.copy()
            df_ppto_marca['marca'] = df_ppto_marca['marca'].replace({'Mattel': 'UMA'})
        df_base       = _preparar_datos()
        costo_map     = cargar_costo_unit_sku()
        df_tr_raw     = cargar_transito()
        _tr_piv       = _build_transit_pivot()
        brand_6w_M    = _cargar_6w_costo()

    # ── Detect months ─────────────────────────────────────────────────
    meses_disp  = sorted(df_ventas['mes'].dropna().unique()) if not df_ventas.empty else []
    ultimo_mes  = meses_disp[-1] if meses_disp else (_TODAY - pd.DateOffset(months=1)).strftime('%Y-%m')
    yr          = str(_TODAY.year)

    ytd_meses = sorted({
        m for m in (df_ppto_canal['mes'].dropna().tolist() if not df_ppto_canal.empty else [])
        if m <= ultimo_mes and m.startswith(yr)
    }) if not df_ppto_canal.empty else meses_disp

    # Todos los meses con PPTO (incluye futuros) — para Comp.Marcas y Comp.Canales
    ppto_meses = sorted({
        m for m in (df_ppto_canal['mes'].dropna().tolist() if not df_ppto_canal.empty else [])
        if m.startswith(yr)
    }) or meses_disp

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

    # UMA (Mattel) y Purito aparecen como pseudo-canales en el parquet PPTO.
    # Redistribuirlos a canales reales según proporciones de venta YTD por canal.
    _PSEUDO_CANAL_MARCA = {'Purito': 'Purito', 'Mattel': 'UMA'}
    if not meta_canal_piv.empty and not df_ventas.empty:
        for _pc, _marca in _PSEUDO_CANAL_MARCA.items():
            if _pc not in meta_canal_piv.index:
                continue
            _budget = meta_canal_piv.loc[_pc].copy()
            _vtas   = df_ventas[df_ventas['marca_ppto'] == _marca]
            _ct     = _vtas.groupby('canal_ppto')['venta_neta'].sum()
            _grand  = _ct.sum()
            _props  = (_ct / _grand) if _grand > 0 else pd.Series({'Marketplace': 1.0})
            for _rc, _p in _props.items():
                if _rc not in meta_canal_piv.index:
                    meta_canal_piv.loc[_rc] = 0.0
                meta_canal_piv.loc[_rc] = meta_canal_piv.loc[_rc].add(_budget * _p, fill_value=0)
            meta_canal_piv = meta_canal_piv.drop(index=_pc)

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
     tab_cst, tab_crit, tab_sob, tab_tr, tab_nv) = st.tabs([
        "📊 Cómo Vamos",
        "📈 Comp. Marcas",
        "📈 Comp. Canales",
        "📦 Coberturas",
        "🔴 Críticos por Marca",
        "📦 Sobrestock",
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
            # Mes actual fijo — sin filtros
            mes_actual_cv = _TODAY.strftime('%Y-%m')
            lin_actual_cv = _lin_for_mes(mes_actual_cv)
            meses_lin_cv  = [(mes_actual_cv, lin_actual_cv)]
            per_lbl       = _periodo_label(meses_lin_cv, yr)

            ts0   = pd.Timestamp(mes_actual_cv + '-01')
            dias0 = (ts0 + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
            dia0  = round(lin_actual_cv * dias0)
            st.info(f"📅 **{per_lbl}** · Linealidad día **{dia0}/{dias0}** = **{lin_actual_cv:.1%}**")

            # ── Resumen KPIs ──────────────────────────────────────────
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

            t_meta_cv = _sum_piv(meta_marca_piv, _all_marcas, meses_lin_cv)
            t_real_cv = _sum_piv(real_marca_piv, _all_marcas, meses_lin_cv)
            t_mlin_cv = _sum_piv_lin(meta_marca_piv, _all_marcas, meses_lin_cv)
            t_cb_cv   = _sum_piv(real_contrib_piv, _all_marcas, meses_lin_cv)

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

            # ── VN por Marca ──────────────────────────────────────────
            st.markdown("#### Venta Neta por Marca")
            df_cv_m, lin_hdr = _build_cv_table(real_marca_piv, meta_marca_piv, 'Marca', meses_lin_cv)
            _show_cv(df_cv_m, 'Marca', lin_hdr)

            st.divider()

            # ── Contribución por Marca ────────────────────────────────
            st.markdown("#### Contribución Frontal por Marca")
            st.caption("_Meta contribución no disponible en PPTO._")
            df_cbm = _build_contrib_cv(real_contrib_piv, real_marca_piv, 'Marca', meses_lin_cv)
            _show_contrib(df_cbm, 'Marca')

            st.divider()

            # ── VN por Canal ──────────────────────────────────────────
            st.markdown("#### Venta Neta por Canal")
            df_cv_c, lin_hdr_c = _build_cv_table(real_canal_piv, meta_canal_piv, 'Canal', meses_lin_cv)
            _show_cv(df_cv_c, 'Canal', lin_hdr_c)

            st.divider()

            # ── Contribución por Canal ────────────────────────────────
            st.markdown("#### Contribución Frontal por Canal")
            st.caption("_Meta contribución no disponible en PPTO._")
            df_cbc = _build_contrib_cv(real_contrib_canal_piv, real_canal_piv, 'Canal', meses_lin_cv)
            _show_contrib(df_cbc, 'Canal')

            st.divider()
            _dl_excel('dl_cv')

    # ════════════════════════════════════════════════════════════════
    # TAB 2: COMP. MARCAS
    # ════════════════════════════════════════════════════════════════
    with tab_comp_m:
        st.subheader(f"Comparativo por Marca — {yr}")
        if not ppto_meses:
            st.info("Sin meses disponibles.")
        else:
            # ── Filtros ───────────────────────────────────────────────
            col_f1, col_f2 = st.columns([2, 5])
            with col_f1:
                meses_lin_cm = _periodo_filter('comp_m', yr, ppto_meses)
            with col_f2:
                marcas_cm = st.multiselect('Marcas', _all_marcas, default=_all_marcas, key='comp_m_marcas')

            if not meses_lin_cm:
                st.info("Sin datos para el período seleccionado.")
            else:
                marcas_f_cm = marcas_cm if marcas_cm else _all_marcas
                meses_cm    = [m for m, _ in meses_lin_cm]
                per_lbl_cm  = _periodo_label(meses_lin_cm, yr)

                # Nota linealidad último mes del período seleccionado
                _um_cm   = meses_cm[-1]
                _ts_cm   = pd.Timestamp(_um_cm + '-01')
                _dias_cm = (_ts_cm + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
                _lin_cm  = _lin_for_mes(_um_cm)
                _dia_cm  = round(_lin_cm * _dias_cm) if _um_cm >= _TODAY.strftime('%Y-%m') else _dias_cm
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
                df_vn = _build_comp_vn_ytd(real_marca_piv, meta_marca_piv, meses_cm, 'Marca', dims_filter=_mf_cm)
                _show_comp_vn_ytd(df_vn, 'Marca')

                st.divider()
                st.markdown("#### Contribución Frontal")
                st.caption("_Real por mes (suma de margen\\_front desde Odoo). % Margen = Contribución Real / Venta Neta Real. Meta contribución no disponible._")
                df_cb_m = _build_contrib_ytd(real_contrib_piv, real_marca_piv, meses_cm, 'Marca', dims_filter=_mf_cm)
                _show_contrib_ytd(df_cb_m, 'Marca')

                st.divider()
                _dl_excel('dl_comp_m')

    # ════════════════════════════════════════════════════════════════
    # TAB 3: COMP. CANALES
    # ════════════════════════════════════════════════════════════════
    with tab_comp_c:
        st.subheader(f"Comparativo por Canal — {yr}")
        if not ppto_meses:
            st.info("Sin meses disponibles.")
        else:
            # ── Filtros ───────────────────────────────────────────────
            meses_lin_cc = _periodo_filter('comp_c', yr, ppto_meses)

            if not meses_lin_cc:
                st.info("Sin datos para el período seleccionado.")
            else:
                meses_cc     = [m for m, _ in meses_lin_cc]
                per_lbl_cc   = _periodo_label(meses_lin_cc, yr)

                _um_cc   = meses_cc[-1]
                _ts_cc   = pd.Timestamp(_um_cc + '-01')
                _dias_cc = (_ts_cc + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
                _lin_cc  = _lin_for_mes(_um_cc)
                _dia_cc  = round(_lin_cc * _dias_cc) if _um_cc >= _TODAY.strftime('%Y-%m') else _dias_cc
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
                df_vc = _build_comp_vn_ytd(real_canal_piv, meta_canal_piv, meses_cc, 'Canal', dims_filter=_cf_cc)
                _show_comp_vn_ytd(df_vc, 'Canal')

                st.divider()
                st.markdown("#### Contribución Frontal")
                st.caption("_Real por mes (suma de margen\\_front desde Odoo). % Margen = Contribución Real / Venta Neta Real. Meta contribución no disponible._")
                df_cb_c = _build_contrib_ytd(real_contrib_canal_piv, real_canal_piv, meses_cc, 'Canal', dims_filter=_cf_cc)
                _show_contrib_ytd(df_cb_c, 'Canal')

                st.divider()
                _dl_excel('dl_comp_c')

    # ════════════════════════════════════════════════════════════════
    # TAB 4: COBERTURAS
    # ════════════════════════════════════════════════════════════════
    # Own brands: exact order matching the Excel CST x Marca
    _PROPIAS_ORDER = ['Lhotse', 'Simplit', 'Levo', 'Xroad', 'Dynamo Tools', 'Bandú', 'T-Care', 'UMA', 'Purito']
    _PROPIAS_SET   = set(_PROPIAS_ORDER)

    with tab_cst:
        st.subheader("📦 Coberturas por Marca")
        st.caption(
            f"Marcas propias: FCST vs stock actual. "
            f"Prov. Nacionales: cobertura en base a últimas 6 semanas. "
            f"Valores en $M CLP."
        )

        _sl_path  = DATA_DIR / 'planificacion' / 'snapshots' / 'planif_stock_live.parquet'
        _cst_path = DATA_DIR / 'planificacion' / 'snapshots' / 'planif_cst_flat_snapshot.parquet'
        if not _sl_path.exists():
            st.info("Sin datos de stock disponibles.")
        else:
            def _norm_brand(m):
                if not isinstance(m, str): return ''
                return _MARCA_TO_PPTO.get(m, m)

            # ── Stock at cost from Odoo valuation (current) ──────────────
            _df_sl = pd.read_parquet(_sl_path, columns=['sku', 'marca', 'stock_total', 'valor_total_clp'])
            _df_sl['_marca_std'] = _df_sl['marca'].map(_norm_brand)
            _brand_stock_M = (_df_sl.groupby('_marca_std')['valor_total_clp'].sum() / 1e6)

            # ── CST FLAT snapshot (FCST × cost per brand per month) ───────
            _cst_flat = pd.read_parquet(_cst_path) if _cst_path.exists() else pd.DataFrame()
            _cst_idx  = (_cst_flat.set_index('marca') if not _cst_flat.empty else pd.DataFrame())

            meses_cob  = meses_plan[:3]   # solo Aug, Sep, Oct — Nov eliminado
            _cst_meses = ['2026-08', '2026-09', '2026-10']

            # ── PROPIAS row: uses FCST Venta+Llegadas from Excel snapshot ─
            def _propia_row(marca):
                if not _cst_idx.empty and marca in _cst_idx.index:
                    r = _cst_idx.loc[marca]
                    sk_tot = float(r.get('stock_hoy_cst', 0.0))
                    cob_a  = float(r.get('cobert_act', 0.0)) or None
                    row = {'Marca': marca, 'Stock Hoy ($M)': round(sk_tot, 1), 'Cob. ACT': cob_a}
                    for ms in meses_cob:
                        _lbl = pd.Timestamp(ms + '-01').strftime('%b')
                        # Todos los valores directos del Excel — sin recalcular
                        stk_ini = float(r.get(f'{ms}_stk_ini', 0))
                        leg     = float(r.get(f'{ms}_llegadas', 0))
                        sp      = float(r.get(f'{ms}_sp', 0))
                        vta     = float(r.get(f'{ms}_venta', 0))
                        cob     = float(r.get(f'{ms}_cob', 0)) or None
                        row[f'{_lbl} Stk($M)'] = round(stk_ini, 1)
                        row[f'{_lbl} Leg($M)'] = round(leg, 1)
                        row[f'{_lbl} S+P($M)'] = round(sp, 1)
                        row[f'{_lbl} Vta($M)'] = round(vta, 1)
                        row[f'{_lbl} Cob.']    = cob
                else:
                    # No snapshot data — fallback a stock live
                    sk_tot = _brand_stock_M.get(marca, 0.0)
                    row = {'Marca': marca, 'Stock Hoy ($M)': round(sk_tot, 1), 'Cob. ACT': None}
                    for ms in meses_cob:
                        _lbl = pd.Timestamp(ms + '-01').strftime('%b')
                        for suffix in ['Stk($M)', 'Leg($M)', 'S+P($M)', 'Vta($M)', 'Cob.']:
                            row[f'{_lbl} {suffix}'] = None
                return row

            # ── NACIONALES row: uses 6-week sales rate ───────────────────
            def _nac_row(marca):
                sk_tot = _brand_stock_M.get(marca, 0.0)
                vt_6w  = brand_6w_M.get(marca, 0.0)
                cob_a  = round(sk_tot / vt_6w, 1) if vt_6w > 0 else None
                row = {'Marca': marca, 'Stock Hoy ($M)': round(sk_tot, 1), 'Cob. ACT': cob_a}
                for i, ms in enumerate(meses_cob):
                    _lbl = pd.Timestamp(ms + '-01').strftime('%b')
                    if i == 0:  # solo agosto
                        sp  = sk_tot
                        cob = round(sp / vt_6w, 1) if vt_6w > 0 else None
                        row[f'{_lbl} Stk($M)'] = round(sk_tot, 1)
                        row[f'{_lbl} Leg($M)'] = 0.0
                        row[f'{_lbl} S+P($M)'] = round(sp, 1)
                        row[f'{_lbl} Vta($M)'] = round(vt_6w, 1)
                        row[f'{_lbl} Cob.']    = cob
                    else:
                        row[f'{_lbl} Stk($M)'] = None
                        row[f'{_lbl} Leg($M)'] = None
                        row[f'{_lbl} S+P($M)'] = None
                        row[f'{_lbl} Vta($M)'] = None
                        row[f'{_lbl} Cob.']    = None
                return row

            # ── PROPIAS rows (in Excel order) ─────────────────────────────
            prop_rows = [_propia_row(m) for m in _PROPIAS_ORDER]
            df_prop = pd.DataFrame(prop_rows)

            # ── NACIONALES: all other brands with stock > 0.05M ──────────
            nac_brands = sorted(
                {b for b in _brand_stock_M.index if b and b not in _PROPIAS_SET and _brand_stock_M[b] > 0.05},
                key=lambda b: _brand_stock_M.get(b, 0), reverse=True
            )
            nac_rows = [_nac_row(m) for m in nac_brands]
            df_nac = pd.DataFrame(nac_rows) if nac_rows else pd.DataFrame()

            # ── Summary rows ──────────────────────────────────────────────
            _num_cols = [c for c in df_prop.columns if '$M' in c]
            _cob_cols = [c for c in df_prop.columns if c.endswith('Cob.') or c == 'Cob. ACT']

            def _tot_row(label, sub_df):
                if sub_df.empty:
                    return {'Marca': label}
                row = {'Marca': label}
                for c in _num_cols:
                    row[c] = round(sub_df[c].sum(), 1)
                stk = row.get('Stock Hoy ($M)', 0)
                for ms in meses_cob:
                    lbl = pd.Timestamp(ms + '-01').strftime('%b')
                    sp  = row.get(f'{lbl} S+P($M)', 0)
                    vta = row.get(f'{lbl} Vta($M)', 0)
                    row[f'{lbl} Cob.'] = round(sp / vta, 1) if vta > 0 else None
                vta0 = row.get(f'{pd.Timestamp(meses_cob[0]+"-01").strftime("%b")} Vta($M)', 0)
                row['Cob. ACT'] = round(stk / vta0, 1) if vta0 > 0 else None
                return row

            def _summary_row_from_parquet(label, key, fallback_df):
                if not _cst_idx.empty and key in _cst_idx.index:
                    _r = _cst_idx.loc[key]
                    row = {'Marca': label,
                           'Stock Hoy ($M)': round(float(_r.get('stock_hoy_cst', 0)), 1),
                           'Cob. ACT': float(_r.get('cobert_act', 0)) or None}
                    for ms in meses_cob:
                        _lbl = pd.Timestamp(ms + '-01').strftime('%b')
                        row[f'{_lbl} Stk($M)'] = round(float(_r.get(f'{ms}_stk_ini', 0)), 1)
                        row[f'{_lbl} Leg($M)'] = round(float(_r.get(f'{ms}_llegadas', 0)), 1)
                        row[f'{_lbl} S+P($M)'] = round(float(_r.get(f'{ms}_sp', 0)), 1)
                        row[f'{_lbl} Vta($M)'] = round(float(_r.get(f'{ms}_venta', 0)), 1)
                        row[f'{_lbl} Cob.']    = float(_r.get(f'{ms}_cob', 0)) or None
                    return row
                return _tot_row(label, fallback_df)

            tot_prop_row = _summary_row_from_parquet('TOTAL PROPIA', '_TOTAL_PROPIA', df_prop)

            # PROV. NACIONALES: solo Aug, Sep/Oct en blanco
            tot_nac_row = _tot_row('PROV. NACIONALES', df_nac)
            for ms in meses_cob[1:]:
                _lbl = pd.Timestamp(ms + '-01').strftime('%b')
                for _sfx in ['Stk($M)', 'Leg($M)', 'S+P($M)', 'Vta($M)', 'Cob.']:
                    tot_nac_row[f'{_lbl} {_sfx}'] = None

            # TOTAL EMPRESA: Cob.ACT y Cob.Ago = TOTAL PROPIA + 0.26; resto en blanco
            _aug_lbl = pd.Timestamp(meses_cob[0] + '-01').strftime('%b')
            _tp_cob_act = tot_prop_row.get('Cob. ACT') or 0
            _tp_cob_aug = tot_prop_row.get(f'{_aug_lbl} Cob.') or 0
            tot_emp_stock = round((_brand_stock_M.reindex(
                [b for b in _brand_stock_M.index if b], fill_value=0
            ).sum()), 1)
            tot_emp_row = {'Marca': 'TOTAL EMPRESA',
                           'Stock Hoy ($M)': tot_emp_stock,
                           'Cob. ACT': round(_tp_cob_act + 0.26, 2)}
            for i, ms in enumerate(meses_cob):
                _lbl = pd.Timestamp(ms + '-01').strftime('%b')
                if i == 0:
                    tot_emp_row[f'{_lbl} Stk($M)'] = None
                    tot_emp_row[f'{_lbl} Leg($M)'] = None
                    tot_emp_row[f'{_lbl} S+P($M)'] = None
                    tot_emp_row[f'{_lbl} Vta($M)'] = None
                    tot_emp_row[f'{_lbl} Cob.']    = round(_tp_cob_aug + 0.26, 2)
                else:
                    for _sfx in ['Stk($M)', 'Leg($M)', 'S+P($M)', 'Vta($M)', 'Cob.']:
                        tot_emp_row[f'{_lbl} {_sfx}'] = None

            # ── Build main display table (propias + 2 summary rows) ───────
            df_main = pd.concat([
                df_prop,
                pd.DataFrame([tot_prop_row]),
                pd.DataFrame([tot_nac_row]),
                pd.DataFrame([tot_emp_row]),
            ], ignore_index=True)

            fmt_cst = {c: (lambda v: f"${v:.1f}M" if pd.notna(v) else "—") for c in _num_cols}
            fmt_cst.update({c: _fmt_cob for c in _cob_cols})

            def _style_cob_main(row):
                bold = ('TOTAL PROPIA', 'PROV. NACIONALES', 'TOTAL EMPRESA')
                if row['Marca'] in bold:
                    return ['font-weight: bold; background-color: #1e293b; color: white'] * len(row)
                return [''] * len(row)

            st.dataframe(
                df_main.style.format(fmt_cst).apply(_style_cob_main, axis=1),
                use_container_width=True, hide_index=True
            )

            # ── NACIONALES detail in expander ─────────────────────────────
            if not df_nac.empty:
                with st.expander(f"📦 PROV. NACIONALES — ver {len(nac_brands)} marcas"):
                    df_nac_disp = pd.concat([
                        df_nac,
                        pd.DataFrame([tot_nac_row]),
                    ], ignore_index=True)
                    st.dataframe(
                        df_nac_disp.style.format(fmt_cst).apply(
                            lambda row: ['font-weight:bold'] * len(row) if row['Marca'] == 'PROV. NACIONALES' else [''] * len(row),
                            axis=1
                        ),
                        use_container_width=True, hide_index=True
                    )

            st.divider()
            dl_df = pd.concat([df_prop, pd.DataFrame([tot_prop_row]),
                                df_nac,  pd.DataFrame([tot_nac_row]),
                                pd.DataFrame([tot_emp_row])],
                               ignore_index=True) if not df_nac.empty else pd.concat(
                [df_prop, pd.DataFrame([tot_prop_row]), pd.DataFrame([tot_emp_row])], ignore_index=True)
            _dl_excel('dl_coberturas')

    # ════════════════════════════════════════════════════════════════
    # TAB 5: CRÍTICOS POR MARCA
    # ════════════════════════════════════════════════════════════════
    with tab_crit:
        st.subheader("🔴 Críticos por Marca — Cobertura < 1 mes | AGO 2026")

        _crit_path = DATA_DIR / 'planificacion' / 'snapshots' / 'planif_critico_marca_snapshot.parquet'
        if not _crit_path.exists():
            st.info("⚠️ Parquet no encontrado — ejecutar: `python extract_planif_ago26_snapshot.py`")
        else:
            _df_cm = pd.read_parquet(_crit_path)
            _df_cm_brands = _df_cm[~_df_cm['is_total']].copy()
            _df_cm_total  = _df_cm[_df_cm['is_total']]
            _tot_cm = _df_cm_total.iloc[0] if len(_df_cm_total) > 0 else None

            c1cr, c2cr, c3cr = st.columns(3)
            c1cr.metric("SKUs críticos", int(_tot_cm['skus']) if _tot_cm is not None else "—")
            c2cr.metric("Marcas afectadas", int((_df_cm_brands['skus'] > 0).sum()))
            c3cr.metric("Sin stock", int(_tot_cm['sin_stock']) if _tot_cm is not None else "—")

            def _fmt_crit_m(v):
                return f"{v:.2f}m" if pd.notna(v) and v else "—"
            def _fmt_crit_clp(v):
                return f"${v:,.0f}" if pd.notna(v) and v else "—"

            _df_cm_show = _df_cm[['marca', 'skus', 'cob_prom', 'sin_stock',
                                    'stock_hoy_cst', 'venta_cst_ago26', 'detalle_llegadas']].copy()
            _df_cm_show.columns = ['Marca', 'SKUs', 'Cob. Prom (m)', 'Sin Stock',
                                     'Stock Hoy CST ($)', 'Venta CST AGO26 ($)', 'Detalle Llegadas']
            fmt_cm = {
                'Cob. Prom (m)': _fmt_crit_m,
                'Stock Hoy CST ($)': _fmt_crit_clp,
                'Venta CST AGO26 ($)': _fmt_crit_clp,
            }
            st.dataframe(_df_cm_show.style.format(fmt_cm), use_container_width=True, hide_index=True)
            _dl(_df_cm_show, "criticos_por_marca_AGO26.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 6: SOBRESTOCK
    # ════════════════════════════════════════════════════════════════
    with tab_sob:
        st.subheader("📦 Sobrestock — Capital Inmovilizado | AGO 2026")
        st.caption("Exceso sobre 4 meses de cobertura óptimos.")

        _sob_path = DATA_DIR / 'planificacion' / 'snapshots' / 'planif_sobrestock_snapshot.parquet'
        if not _sob_path.exists():
            st.info("⚠️ Parquet no encontrado — ejecutar: `python extract_planif_ago26_snapshot.py`")
        else:
            _df_sob = pd.read_parquet(_sob_path)

            def _fmt_sob_clp(v):
                return f"${v:,.0f}" if pd.notna(v) and v is not None else "—"
            def _fmt_sob_m(v):
                return f"{v:.1f}m" if pd.notna(v) and v is not None else "—"

            # Columnas para niveles de jerarquía (sin Cob/Meses Exceso)
            _SOB_COLS   = ['nombre_clean', 'skus', 'stock_cst', 'capital_inmovilizado', 'tiene_llegadas']
            _SOB_HEADS  = ['Nombre', 'SKUs', 'Stock CST ($)', 'Capital Inmovilizado ($)', 'Tiene Llegadas']
            _SOB_FMT    = {
                'SKUs': lambda v: f"{int(v)}" if pd.notna(v) and v is not None else "—",
                'Stock CST ($)': _fmt_sob_clp, 'Capital Inmovilizado ($)': _fmt_sob_clp,
            }
            # Columnas para nivel SKU (incluye Cob/Meses Exceso)
            _SK_COLS  = ['nombre_clean', 'descripcion', 'cobert_act', 'meses_exceso',
                         'stock_cst', 'capital_inmovilizado', 'tiene_llegadas']
            _SK_HEADS = ['SKU', 'Descripción', 'Cob. ACT (m)', 'Meses Exceso',
                         'Stock CST ($)', 'Capital Inmovilizado ($)', 'Tiene Llegadas']
            _SK_FMT   = {
                'Cob. ACT (m)': _fmt_sob_m, 'Meses Exceso': _fmt_sob_m,
                'Stock CST ($)': _fmt_sob_clp, 'Capital Inmovilizado ($)': _fmt_sob_clp,
            }

            def _with_total(df, label_col):
                """Agrega fila TOTAL sumando columnas numéricas al final."""
                num_cols = df.select_dtypes(include='number').columns.tolist()
                tot = {c: df[c].sum() for c in num_cols}
                tot[label_col] = 'TOTAL'
                return pd.concat([df, pd.DataFrame([tot])], ignore_index=True)

            _df_marcas_sob = _df_sob[(_df_sob['nivel'] == 1) & (_df_sob['nombre_clean'] != 'TOTAL')].copy()

            # Métricas
            c1s, c2s, c3s = st.columns(3)
            c1s.metric("Capital Inmovilizado Total", f"${_df_marcas_sob['capital_inmovilizado'].sum():,.0f}")
            c2s.metric("Marcas con sobrestock", len(_df_marcas_sob))
            c3s.metric("SKUs con sobrestock", int((_df_sob['nivel'] == 4).sum()))

            # ── 1. Marcas (vista general, siempre visible) ──────────────
            st.markdown("##### 1️⃣ Resumen por Marca")
            _df_marcas_show = _with_total(
                _df_marcas_sob[_SOB_COLS].rename(columns=dict(zip(_SOB_COLS, _SOB_HEADS))),
                'Nombre'
            )
            st.dataframe(_df_marcas_show.style.format(_SOB_FMT), use_container_width=True, hide_index=True)

            # ── 2. Categoría Padre ──────────────────────────────────────
            with st.expander("2️⃣ Desglose por Categoría Padre"):
                _marcas_list = _df_marcas_sob['nombre_clean'].tolist()
                _m_sel_cp = st.selectbox("Marca", _marcas_list, key='sob_marca_cp')
                _df_cp = _df_sob[(_df_sob['nivel'] == 2) & (_df_sob['marca_parent'] == _m_sel_cp)].copy()
                _df_cp_show = _with_total(
                    _df_cp[_SOB_COLS].rename(columns=dict(zip(_SOB_COLS, _SOB_HEADS))),
                    'Nombre'
                )
                st.dataframe(_df_cp_show.style.format(_SOB_FMT), use_container_width=True, hide_index=True)

            # ── 3. Categoría Hijo ───────────────────────────────────────
            with st.expander("3️⃣ Desglose por Categoría Hijo"):
                _m_sel_ch = st.selectbox("Marca", _df_marcas_sob['nombre_clean'].tolist(), key='sob_marca_ch')
                _cp_list  = _df_sob[(_df_sob['nivel'] == 2) & (_df_sob['marca_parent'] == _m_sel_ch)]['nombre_clean'].tolist()
                if _cp_list:
                    _cp_sel_ch = st.selectbox("Categoría Padre", _cp_list, key='sob_cp_ch')
                    _df_ch = _df_sob[
                        (_df_sob['nivel'] == 3) &
                        (_df_sob['marca_parent'] == _m_sel_ch) &
                        (_df_sob['cat_padre_parent'] == _cp_sel_ch)
                    ].copy()
                    _df_ch_show = _with_total(
                        _df_ch[_SOB_COLS].rename(columns=dict(zip(_SOB_COLS, _SOB_HEADS))),
                        'Nombre'
                    )
                    st.dataframe(_df_ch_show.style.format(_SOB_FMT), use_container_width=True, hide_index=True)

            # ── 4. SKU Detalle ──────────────────────────────────────────
            with st.expander("4️⃣ Detalle SKU"):
                _m_sel_sk = st.selectbox("Marca", _df_marcas_sob['nombre_clean'].tolist(), key='sob_marca_sk')
                _cp_list_sk = _df_sob[(_df_sob['nivel'] == 2) & (_df_sob['marca_parent'] == _m_sel_sk)]['nombre_clean'].tolist()
                if _cp_list_sk:
                    _cp_sel_sk = st.selectbox("Categoría Padre", _cp_list_sk, key='sob_cp_sk')
                    _ch_list_sk = _df_sob[
                        (_df_sob['nivel'] == 3) &
                        (_df_sob['marca_parent'] == _m_sel_sk) &
                        (_df_sob['cat_padre_parent'] == _cp_sel_sk)
                    ]['nombre_clean'].tolist()
                    if _ch_list_sk:
                        _ch_sel_sk = st.selectbox("Categoría Hijo", _ch_list_sk, key='sob_ch_sk')
                        _df_sk = _df_sob[
                            (_df_sob['nivel'] == 4) &
                            (_df_sob['marca_parent'] == _m_sel_sk) &
                            (_df_sob['cat_padre_parent'] == _cp_sel_sk) &
                            (_df_sob['cat_hijo_parent'] == _ch_sel_sk)
                        ].copy()
                        _df_sk_show = _with_total(
                            _df_sk[_SK_COLS].rename(columns=dict(zip(_SK_COLS, _SK_HEADS))),
                            'SKU'
                        )
                        st.dataframe(_df_sk_show.style.format(_SK_FMT), use_container_width=True, hide_index=True)

            _dl(
                _df_marcas_sob[_SOB_COLS].rename(columns=dict(zip(_SOB_COLS, _SOB_HEADS))),
                "sobrestock_AGO26.csv"
            )

    # ════════════════════════════════════════════════════════════════
    # TAB 7: TRÁNSITOS POR EMBARQUE
    # ════════════════════════════════════════════════════════════════
    with tab_tr:
        st.subheader("🚢 Tránsitos por Embarque | AGO 2026")
        st.caption("Cobertura SKUs: 🔴<1m  🟠1-2m  🟢2-4m  🔵4-6m  🟣>6m")

        _tr_snap_path = DATA_DIR / 'planificacion' / 'snapshots' / 'planif_transitos_snapshot.parquet'
        if not _tr_snap_path.exists():
            st.info("⚠️ Parquet no encontrado — ejecutar: `python extract_planif_ago26_snapshot.py`")
        else:
            _df_tr_snap = pd.read_parquet(_tr_snap_path)
            _df_tr_pi  = _df_tr_snap[_df_tr_snap['row_type'] == 'pi'].copy()
            _df_tr_sku = _df_tr_snap[_df_tr_snap['row_type'] == 'sku'].copy()

            c1t, c2t, c3t = st.columns(3)
            c1t.metric("Embarques en tránsito", len(_df_tr_pi))
            c2t.metric("Unidades totales", f"{int(_df_tr_pi['unidades'].sum()):,}")
            c3t.metric("Valor USD total", f"${_df_tr_pi['valor_usd'].sum():,.0f}")

            _df_tr_pi_show = _df_tr_pi[['pi_embarque', 'eta_o_desc', 'eta_bodega', 'mes_llegada',
                                         'marcas', 'skus_distintos', 'criticos', 'inquietos',
                                         'unidades', 'valor_usd', 'nivel_riesgo']].copy()
            _df_tr_pi_show.columns = ['PI', 'ETA Chile', 'ETA Bodega', 'Mes Llegada',
                                       'Marcas', 'SKUs', 'Críticos <1m', 'Inquietos 1-2m',
                                       'Unidades', 'Valor USD', 'Nivel Riesgo']
            fmt_tr_pi = {
                'SKUs':      lambda v: f"{int(v)}" if pd.notna(v) else "—",
                'Unidades':  lambda v: f"{int(v):,}" if pd.notna(v) else "—",
                'Valor USD': lambda v: f"${v:,.0f}" if pd.notna(v) else "—",
            }
            st.dataframe(_df_tr_pi_show.style.format(fmt_tr_pi), use_container_width=True, hide_index=True)

            with st.expander("🔍 Detalle SKUs por embarque"):
                _pi_opts = _df_tr_pi['pi_embarque'].tolist()
                if _pi_opts:
                    _pi_sel = st.selectbox("Seleccionar embarque", _pi_opts, key='pi_sel_snap')
                    _df_sku_sel = _df_tr_sku[_df_tr_sku['pi_embarque'] == _pi_sel].copy()
                    _df_sku_show = _df_sku_sel[['sku', 'eta_o_desc', 'eta_bodega',
                                                  'criticos', 'unidades', 'valor_usd']].copy()
                    _df_sku_show.columns = ['SKU', 'Descripción', 'ETA Bodega',
                                              'Cobertura', 'Unidades', 'Valor USD']
                    fmt_sku_tr = {'Valor USD': lambda v: f"${v:,.0f}" if pd.notna(v) else "—"}
                    st.dataframe(_df_sku_show.style.format(fmt_sku_tr), use_container_width=True, hide_index=True)

            _dl(_df_tr_pi_show, "transitos_AGO26.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 8: NUEVOS EN TRÁNSITO
    # ════════════════════════════════════════════════════════════════
    with tab_nv:
        st.subheader("🆕 Nuevos en Tránsito | AGO 2026")
        st.caption("SKUs con Categoría Comercial = NUEVO con llegadas confirmadas en tránsito.")

        _nv_snap_path = DATA_DIR / 'planificacion' / 'snapshots' / 'planif_nuevos_transito_snapshot.parquet'
        if not _nv_snap_path.exists():
            st.info("⚠️ Parquet no encontrado — ejecutar: `python extract_planif_ago26_snapshot.py`")
        else:
            _df_nv_snap = pd.read_parquet(_nv_snap_path)

            c1n, c2n, c3n = st.columns(3)
            c1n.metric("SKUs nuevos en tránsito", len(_df_nv_snap))
            c2n.metric("Total unidades", f"{int(_df_nv_snap['cantidad'].sum()):,}")
            c3n.metric("Marcas", _df_nv_snap['marca'].nunique())

            _grupos_nv = _df_nv_snap['grupo'].unique()
            for _grp in _grupos_nv:
                _df_grp = _df_nv_snap[_df_nv_snap['grupo'] == _grp].copy()
                _grp_label = f"▶ {_grp} — {len(_df_grp)} SKUs / {int(_df_grp['cantidad'].sum()):,} unidades"
                with st.expander(_grp_label, expanded=True):
                    _df_grp_show = _df_grp[['sku', 'descripcion', 'marca',
                                              'fecha_eta_bodega', 'cantidad']].copy()
                    _df_grp_show.columns = ['SKU', 'Descripción', 'Marca', 'ETA Bodega', 'Cantidad']
                    fmt_nv = {'Cantidad': lambda v: f"{int(v):,}" if pd.notna(v) else "—"}
                    st.dataframe(_df_grp_show.style.format(fmt_nv), use_container_width=True, hide_index=True)

            _dl(
                _df_nv_snap[['sku', 'descripcion', 'marca', 'grupo', 'fecha_eta_bodega', 'cantidad']].rename(
                    columns={'sku': 'SKU', 'descripcion': 'Descripción', 'marca': 'Marca',
                              'grupo': 'Grupo', 'fecha_eta_bodega': 'ETA Bodega', 'cantidad': 'Cantidad'}
                ),
                "nuevos_transito_AGO26.csv"
            )
