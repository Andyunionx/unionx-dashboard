"""
vs Presupuesto — Presupuesto vs Resultado Contable vs Resultado Comercial.

Fuentes:
  - 'Analisis Meta vs Resultados': Meta (Presupuesto) + Resultado (Comercial/KAM).
  - 'Análisis de Resultados': Resultado Contable (col 18 venta, col 25 contribución).
"""
import unicodedata

import pandas as pd
import plotly.express as px
import streamlit as st

from views.contribucion_loader import (
    cargar_hoja, parse_numero, parsear_columnas_numericas, fmt_pesos_M, fmt_pesos,
    render_contrib_filters, aplicar_filtros,
)


COLS_NUM = ['Meta Venta', 'Resultado Venta', 'Meta Contribución', 'Resultado Contribución']


def _n(s):
    s = str(s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _num(v):
    """Formato chileno: 148.256.265 (miles con punto, sin decimales)."""
    if v is None or pd.isna(v):
        return "—"
    return f"{int(round(v)):,}".replace(",", ".")


def _cargar_contable() -> pd.DataFrame:
    """Resultado CONTABLE por dimensión, desde 'Análisis de Resultados' (acceso
    posicional: col 18 = Venta Real Contable, col 25 = Total Contribución Contable)."""
    cols = ['AÑO', 'Negocio', 'Canal', 'KAM', 'Mes', 'Trimestre',
            'Resultado Venta Contable', 'Resultado Contribución Contable']
    ar = cargar_hoja("Análisis de Resultados")
    if ar.empty or ar.shape[1] < 26:
        return pd.DataFrame(columns=cols)
    d = pd.DataFrame({
        'AÑO': ar.iloc[:, 0].astype(str).str.replace('.', '', regex=False).str.strip(),
        'Negocio': ar.iloc[:, 1].astype(str).str.strip(),
        'Canal': ar.iloc[:, 2].astype(str).str.strip(),
        'KAM': ar.iloc[:, 3].astype(str).str.strip(),
        'Mes': ar.iloc[:, 4].astype(str).str.split('.').str[0].str.strip(),
        'Resultado Venta Contable': ar.iloc[:, 18].apply(parse_numero),
        'Resultado Contribución Contable': ar.iloc[:, 25].apply(parse_numero),
    })
    # KAM en la hoja viene en MAYÚSCULAS ('TRINIDAD'); el df comercial lo normaliza a
    # Title Case ('Trinidad'). Igualar acá para que el filtro KAM matchee (si no, el
    # Contable queda en $0 al filtrar por KAM).
    d['KAM'] = d['KAM'].astype(str).str.strip().str.title()
    d['Trimestre'] = d['Mes'].apply(lambda m: f"Q{(int(m) - 1) // 3 + 1}" if str(m).isdigit() else '')
    return d


def render():
    with st.sidebar:
        st.markdown("### 🎯 **vs Presupuesto**")
        st.caption("Cumplimiento de meta")
        st.markdown("---")
        if st.button("🔄 Refrescar Sheet", width='stretch', type="primary", key="cmeta_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("🎯 Contribución vs Presupuesto")
    st.caption("Cumplimiento de Meta de Venta y Contribución por dimensión")

    try:
        df = cargar_hoja("Analisis Meta vs Resultados")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    if df.empty:
        st.warning("Sin datos")
        return

    df = parsear_columnas_numericas(df, COLS_NUM)

    # Fusionar KAM duplicados por capitalización (CLAUDIA/Claudia → Claudia).
    if 'KAM' in df.columns:
        df['KAM'] = df['KAM'].astype(str).str.strip().str.title()

    # Filtros al tope
    sel = render_contrib_filters(df, prefix="cmeta")
    df_f = aplicar_filtros(df, sel)
    st.caption(f"Filas filtradas: {len(df_f):,} de {len(df):,}")
    st.markdown("---")

    # ---- Resultado CONTABLE (Análisis de Resultados), filtrado igual que la meta ----
    cont = _cargar_contable()
    cont_f = aplicar_filtros(cont, sel)

    presup_v = df_f['Meta Venta'].sum() if 'Meta Venta' in df_f.columns else 0
    com_v = df_f['Resultado Venta'].sum() if 'Resultado Venta' in df_f.columns else 0
    presup_c = df_f['Meta Contribución'].sum() if 'Meta Contribución' in df_f.columns else 0
    com_c = df_f['Resultado Contribución'].sum() if 'Resultado Contribución' in df_f.columns else 0
    cont_v = cont_f['Resultado Venta Contable'].sum() if len(cont_f) else 0
    cont_c = cont_f['Resultado Contribución Contable'].sum() if len(cont_f) else 0

    def _pct(r, m):
        return (r / m * 100) if m else 0

    def _clr(p):
        return '🟢' if p >= 100 else ('🟡' if p >= 85 else '🔴')

    st.markdown("#### Venta — Presupuesto vs Contable vs Comercial")
    v = st.columns(5)
    v[0].metric("Presupuesto", fmt_pesos_M(presup_v))
    v[1].metric("Contable", fmt_pesos_M(cont_v))
    v[2].metric("Comercial", fmt_pesos_M(com_v))
    v[3].metric(f"{_clr(_pct(cont_v, presup_v))} % Contable", f"{_pct(cont_v, presup_v):.1f}%")
    v[4].metric(f"{_clr(_pct(com_v, presup_v))} % Comercial", f"{_pct(com_v, presup_v):.1f}%")

    st.markdown("#### Contribución — Presupuesto vs Contable vs Comercial")
    k = st.columns(5)
    k[0].metric("Presupuesto", fmt_pesos_M(presup_c))
    k[1].metric("Contable", fmt_pesos_M(cont_c))
    k[2].metric("Comercial", fmt_pesos_M(com_c))
    k[3].metric(f"{_clr(_pct(cont_c, presup_c))} % Contable", f"{_pct(cont_c, presup_c):.1f}%")
    k[4].metric(f"{_clr(_pct(com_c, presup_c))} % Comercial", f"{_pct(com_c, presup_c):.1f}%")

    st.divider()

    # ---- Por Trimestre: Presupuesto vs Contable vs Comercial ----
    if 'Trimestre' in df_f.columns:
        st.markdown("### Por Trimestre")
        gm = df_f.groupby('Trimestre').agg(
            Presupuesto_V=('Meta Venta', 'sum'), Comercial_V=('Resultado Venta', 'sum'),
            Presupuesto_C=('Meta Contribución', 'sum'), Comercial_C=('Resultado Contribución', 'sum'),
        ).reset_index()
        gc = (cont_f.groupby('Trimestre').agg(
            Contable_V=('Resultado Venta Contable', 'sum'),
            Contable_C=('Resultado Contribución Contable', 'sum')).reset_index()
            if len(cont_f) else pd.DataFrame(columns=['Trimestre', 'Contable_V', 'Contable_C']))
        g = gm.merge(gc, on='Trimestre', how='left').fillna(0).sort_values('Trimestre')
        CMAP = {'Presupuesto_V': '#94A3B8', 'Contable_V': '#1E40AF', 'Comercial_V': '#10B981',
                'Presupuesto_C': '#94A3B8', 'Contable_C': '#1E40AF', 'Comercial_C': '#10B981'}
        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(g, x='Trimestre', y=['Presupuesto_V', 'Contable_V', 'Comercial_V'],
                         barmode='group', title="Venta", color_discrete_map=CMAP)
            fig.update_layout(height=340, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                              yaxis=dict(tickformat=',.0f'), legend_title_text='')
            st.plotly_chart(fig, width='stretch')
        with c2:
            fig = px.bar(g, x='Trimestre', y=['Presupuesto_C', 'Contable_C', 'Comercial_C'],
                         barmode='group', title="Contribución", color_discrete_map=CMAP)
            fig.update_layout(height=340, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                              yaxis=dict(tickformat=',.0f'), legend_title_text='')
            st.plotly_chart(fig, width='stretch')

    st.divider()

    # Helper: arma tabla Presupuesto/Contable/Comercial agrupada por 'dim' (Negocio o Canal).
    MONEY_COLS = ['Presup. Venta', 'Contable Venta', 'Comercial Venta',
                  'Presup. Contrib', 'Contable Contrib', 'Comercial Contrib']

    def _tabla_por(dim):
        m = df_f.groupby(dim, as_index=False).agg(
            **{'Presup. Venta': ('Meta Venta', 'sum'), 'Comercial Venta': ('Resultado Venta', 'sum'),
               'Presup. Contrib': ('Meta Contribución', 'sum'), 'Comercial Contrib': ('Resultado Contribución', 'sum')})
        m['_k'] = m[dim].map(_n)
        if len(cont_f):
            c = cont_f.groupby(dim, as_index=False).agg(
                **{'Contable Venta': ('Resultado Venta Contable', 'sum'),
                   'Contable Contrib': ('Resultado Contribución Contable', 'sum')})
            c['_k'] = c[dim].map(_n)
            m = m.merge(c[['_k', 'Contable Venta', 'Contable Contrib']], on='_k', how='left')
        else:
            m = m.assign(**{'Contable Venta': 0.0, 'Contable Contrib': 0.0})
        m[['Contable Venta', 'Contable Contrib']] = m[['Contable Venta', 'Contable Contrib']].fillna(0)
        return m.drop(columns='_k')

    def _fmt(df_tbl, keys):
        out = df_tbl.copy()
        for c in MONEY_COLS:
            if c in out.columns:
                out[c] = out[c].map(_num)
        return out[keys + [c for c in MONEY_COLS if c in out.columns]]

    # ---- (4) Por Línea de Negocio ----
    st.markdown("### Por Línea de Negocio")
    tneg = _tabla_por('Negocio').sort_values('Comercial Venta', ascending=False)
    st.dataframe(_fmt(tneg, ['Negocio']), width='stretch', hide_index=True)

    st.divider()

    # ---- (5) Top Canales ----
    st.markdown("### Top Canales")
    n_top = st.slider("Top N canales (por venta comercial)", 5, 30, 15, key="cmeta_topn")
    tcanal = _tabla_por('Canal').sort_values('Comercial Venta', ascending=False)
    st.dataframe(_fmt(tcanal.head(n_top), ['Canal']), width='stretch', hide_index=True)

    st.divider()

    # ---- (3) Detalle por Canal (formato número) ----
    st.markdown("### Detalle por Canal (mensual)")
    meta_ag = df_f.groupby(['AÑO', 'Negocio', 'Canal', 'Mes'], as_index=False).agg(
        **{'Presup. Venta': ('Meta Venta', 'sum'), 'Comercial Venta': ('Resultado Venta', 'sum'),
           'Presup. Contrib': ('Meta Contribución', 'sum'), 'Comercial Contrib': ('Resultado Contribución', 'sum')})
    meta_ag['_k'] = meta_ag['AÑO'].astype(str) + '|' + meta_ag['Canal'].map(_n) + '|' + meta_ag['Mes'].astype(str)
    if len(cont_f):
        cont_ag = cont_f.groupby(['AÑO', 'Canal', 'Mes'], as_index=False).agg(
            **{'Contable Venta': ('Resultado Venta Contable', 'sum'),
               'Contable Contrib': ('Resultado Contribución Contable', 'sum')})
        cont_ag['_k'] = cont_ag['AÑO'].astype(str) + '|' + cont_ag['Canal'].map(_n) + '|' + cont_ag['Mes'].astype(str)
        tbl = meta_ag.merge(cont_ag[['_k', 'Contable Venta', 'Contable Contrib']], on='_k', how='left')
    else:
        tbl = meta_ag.assign(**{'Contable Venta': 0.0, 'Contable Contrib': 0.0})
    tbl[['Contable Venta', 'Contable Contrib']] = tbl[['Contable Venta', 'Contable Contrib']].fillna(0)
    st.dataframe(_fmt(tbl, ['AÑO', 'Negocio', 'Canal', 'Mes']), width='stretch', hide_index=True, height=460)
    st.caption("Presupuesto = Meta (hoja Meta vs Resultados) · Comercial = Resultado KAM · "
               "Contable = 'Análisis de Resultados' (venta col 18 / contribución col 25). Montos en pesos.")
