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
    'Bandú': 'Lhotse',     'Bandu': 'Lhotse',     'bandú': 'Lhotse',
    'T-Care': 'Marcas Flash',
    'Dynamo TL': 'Marcas Flash', 'Dynamo': 'Marcas Flash',
    'Purito': 'Purito',
}


# ── Cached loaders ────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def _cargar_ventas_ytd() -> pd.DataFrame:
    """Ventas del año actual con columnas normalizadas para comparativo PPTO."""
    path = DATA_DIR / 'historico' / 'ventas_historico.parquet'
    if not path.exists():
        return pd.DataFrame()
    try:
        need = ['fecha_venta', 'marca', 'tipo_negocio', 'venta_neta', 'margen_front']
        df = pd.read_parquet(path, columns=need)
        df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce')
        df = df[df['fecha_venta'].dt.year == _TODAY.year].copy()
        df['mes']        = df['fecha_venta'].dt.to_period('M').astype(str)
        df['canal_ppto'] = df['tipo_negocio'].map(_TIPO_NEG_TO_PPTO).fillna('Otros')
        df['marca_ppto'] = df['marca'].map(_MARCA_TO_PPTO).fillna('Prov. Nacionales')
        df['venta_neta']   = pd.to_numeric(df['venta_neta'],   errors='coerce').fillna(0).astype('float64')
        df['margen_front'] = pd.to_numeric(df['margen_front'], errors='coerce').fillna(0).astype('float64')
        return df[['mes', 'marca_ppto', 'canal_ppto', 'venta_neta', 'margen_front']]
    except Exception as e:
        st.toast(f"ventas_historico: {e}", icon="⚠️")
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


def _build_comp_table(real_piv, meta_piv, meses, dim_col):
    """Returns (df, meta_cols, real_cols, var_cols) for the META|REAL|VAR% table."""
    all_dims = sorted(set(
        (real_piv.index.tolist() if not real_piv.empty else []) +
        (meta_piv.index.tolist() if not meta_piv.empty else [])
    ))
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

    # Grand total row
    tr_row = {dim_col: 'TOTAL'}
    t_m = t_r = 0.0
    for mes in meses:
        lbl = pd.Timestamp(mes + '-01').strftime('%b')
        m = float(meta_piv[mes].sum()) if (not meta_piv.empty and mes in meta_piv.columns) else 0.0
        r = float(real_piv[mes].sum())  if (not real_piv.empty  and mes in real_piv.columns)  else 0.0
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
              'font-weight:bold; background-color:#1e2432' if row[dim_col] == 'TOTAL' else ''
              for _ in row
          ], axis=1)
    )
    st.dataframe(styler, use_container_width=True, hide_index=True,
                 height=min(600, 60 + len(df) * 35))


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════
def render():
    st.title("📊 Análisis de Planificación")
    st.caption("Seguimiento comercial vs PPTO + estado supply chain.")

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

    real_marca_piv   = _safe_piv(df_ventas, 'marca_ppto', 'mes', 'venta_neta')
    real_canal_piv   = _safe_piv(df_ventas, 'canal_ppto', 'mes', 'venta_neta')
    real_contrib_piv = _safe_piv(df_ventas, 'marca_ppto', 'mes', 'margen_front')
    meta_marca_piv   = _safe_piv(df_ppto_marca, 'marca', 'mes', 'meta_venta_neta')
    meta_canal_piv   = _safe_piv(df_ppto_canal, 'canal', 'mes', 'meta_venta_neta')

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

    # ════════════════════════════════════════════════════════════════
    # TAB 1: CÓMO VAMOS
    # ════════════════════════════════════════════════════════════════
    with tab_como:
        mes_h = pd.Timestamp(ultimo_mes + '-01').strftime('%B %Y').upper()
        st.subheader(f"Cómo Vamos — {mes_h}")

        no_data = df_ventas.empty and df_ppto_marca.empty
        if no_data:
            st.info("Sin datos suficientes para el comparativo del mes.")
        else:
            # KPIs globales
            t_meta = float(meta_marca_piv[ultimo_mes].sum()) if ultimo_mes in meta_marca_piv.columns else 0.0
            t_real = float(real_marca_piv[ultimo_mes].sum()) if ultimo_mes in real_marca_piv.columns else 0.0
            t_cb   = float(real_contrib_piv[ultimo_mes].sum()) if ultimo_mes in real_contrib_piv.columns else 0.0
            var_g  = (t_real / t_meta - 1) if t_meta > 0 else None

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Meta VN", f"${t_meta/1e6:.1f}M")
            c2.metric("Real VN", f"${t_real/1e6:.1f}M",
                      delta=f"{var_g:+.1%}" if var_g is not None else None)
            c3.metric("Contrib. Frontal Real", f"${t_cb/1e6:.1f}M",
                      delta=f"{t_cb/t_real:.1%} margen" if t_real > 0 else None)
            c4.metric("Avance vs Meta", f"{t_real/t_meta:.0%}" if t_meta > 0 else "—")

            st.divider()

            # ── Tabla por Marca ────────────────────────────────────────
            st.markdown("#### Venta Neta por Marca")
            all_m = sorted(set(
                (real_marca_piv.index.tolist() if not real_marca_piv.empty else []) +
                (meta_marca_piv.index.tolist() if not meta_marca_piv.empty else [])
            ))
            rows_bm = []
            for m in all_m:
                meta_v  = float(meta_marca_piv.at[m, ultimo_mes]) if (m in meta_marca_piv.index and ultimo_mes in meta_marca_piv.columns) else 0.0
                real_v  = float(real_marca_piv.at[m, ultimo_mes])  if (m in real_marca_piv.index  and ultimo_mes in real_marca_piv.columns)  else 0.0
                cb_v    = float(real_contrib_piv.at[m, ultimo_mes]) if (m in real_contrib_piv.index and ultimo_mes in real_contrib_piv.columns) else 0.0
                rows_bm.append({
                    'Marca': m, 'Meta ($M)': meta_v, 'Real ($M)': real_v,
                    'vs Meta': (real_v / meta_v - 1) if meta_v > 0 else None,
                    'Contrib Real ($M)': cb_v,
                    '% Margen': (cb_v / real_v) if real_v > 0 else None,
                })
            df_bm = pd.DataFrame(rows_bm)
            if not df_bm.empty:
                fmt_bm = {
                    'Meta ($M)': _fmt_m, 'Real ($M)': _fmt_m, 'vs Meta': _fmt_pct,
                    'Contrib Real ($M)': _fmt_m,
                    '% Margen': lambda v: f"{v:.1%}" if pd.notna(v) else "—",
                }
                st.dataframe(
                    df_bm.style.format(fmt_bm).map(_color_pct, subset=['vs Meta']),
                    use_container_width=True, hide_index=True
                )
                _dl(df_bm, f"como_vamos_marca_{ultimo_mes}.csv")

            st.divider()

            # ── Tabla por Canal ────────────────────────────────────────
            st.markdown("#### Venta Neta por Canal")
            all_c = sorted(set(
                (real_canal_piv.index.tolist() if not real_canal_piv.empty else []) +
                (meta_canal_piv.index.tolist() if not meta_canal_piv.empty else [])
            ))
            rows_bc = []
            for c in all_c:
                meta_v = float(meta_canal_piv.at[c, ultimo_mes]) if (c in meta_canal_piv.index and ultimo_mes in meta_canal_piv.columns) else 0.0
                real_v = float(real_canal_piv.at[c, ultimo_mes])  if (c in real_canal_piv.index  and ultimo_mes in real_canal_piv.columns)  else 0.0
                rows_bc.append({
                    'Canal': c, 'Meta ($M)': meta_v, 'Real ($M)': real_v,
                    'vs Meta': (real_v / meta_v - 1) if meta_v > 0 else None,
                })
            df_bc = pd.DataFrame(rows_bc)
            if not df_bc.empty:
                fmt_bc = {'Meta ($M)': _fmt_m, 'Real ($M)': _fmt_m, 'vs Meta': _fmt_pct}
                st.dataframe(
                    df_bc.style.format(fmt_bc).map(_color_pct, subset=['vs Meta']),
                    use_container_width=True, hide_index=True
                )
                _dl(df_bc, f"como_vamos_canal_{ultimo_mes}.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 2: COMP. MARCAS
    # ════════════════════════════════════════════════════════════════
    with tab_comp_m:
        st.subheader(f"Comparativo por Marca — YTD {yr}")
        if not ytd_meses:
            st.info("Sin meses disponibles.")
        else:
            meses_lbl = " | ".join(pd.Timestamp(m + '-01').strftime('%b') for m in ytd_meses)
            st.caption(f"Meses: {meses_lbl}  ·  Valores en $M CLP")

            st.markdown("#### Venta Neta")
            df_vn, mc_vn, rc_vn, vc_vn = _build_comp_table(real_marca_piv, meta_marca_piv, ytd_meses, 'Marca')
            _show_comp(df_vn, mc_vn, rc_vn, vc_vn, 'Marca')
            _dl(df_vn, f"comp_marcas_venta_neta_{yr}.csv")

            st.divider()
            st.markdown("#### Contribución Frontal — Solo Real (meta no disponible por marca en PPTO)")
            all_m_cb = sorted(real_contrib_piv.index.tolist()) if not real_contrib_piv.empty else []
            rows_cb = []
            for m in all_m_cb:
                row_cb = {'Marca': m}
                tot = 0.0
                for mes in ytd_meses:
                    lbl = pd.Timestamp(mes + '-01').strftime('%b')
                    v = float(real_contrib_piv.at[m, mes]) if mes in real_contrib_piv.columns else 0.0
                    row_cb[lbl] = v; tot += v
                row_cb['TOTAL'] = tot
                tot_vn = sum(float(real_marca_piv.at[m, mes]) if mes in real_marca_piv.columns else 0.0 for mes in ytd_meses)
                row_cb['% Margen'] = tot / tot_vn if tot_vn > 0 else None
                rows_cb.append(row_cb)
            if rows_cb:
                df_cb = pd.DataFrame(rows_cb)
                num_cb = [c for c in df_cb.columns if c not in ('Marca', '% Margen')]
                fmt_cb = {c: _fmt_m for c in num_cb}
                fmt_cb['% Margen'] = lambda v: f"{v:.1%}" if pd.notna(v) else "—"
                st.dataframe(df_cb.style.format(fmt_cb), use_container_width=True, hide_index=True)
                _dl(df_cb, f"comp_marcas_contribucion_{yr}.csv")

    # ════════════════════════════════════════════════════════════════
    # TAB 3: COMP. CANALES
    # ════════════════════════════════════════════════════════════════
    with tab_comp_c:
        st.subheader(f"Comparativo por Canal — YTD {yr}")
        if not ytd_meses:
            st.info("Sin meses disponibles.")
        else:
            st.caption(f"Meses: {' | '.join(pd.Timestamp(m+'-01').strftime('%b') for m in ytd_meses)}  ·  Valores en $M CLP")
            st.markdown("#### Venta Neta")
            df_vc, mc_vc, rc_vc, vc_vc = _build_comp_table(real_canal_piv, meta_canal_piv, ytd_meses, 'Canal')
            _show_comp(df_vc, mc_vc, rc_vc, vc_vc, 'Canal')
            _dl(df_vc, f"comp_canales_{yr}.csv")

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
