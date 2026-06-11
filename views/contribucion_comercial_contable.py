"""
Comercial vs Contable — comparación lado a lado de las dos visiones.

Fuente: 'Análisis de Resultados' (tiene ambas columnas KAM y Contable).

La clave de la vista: la diferencia de contribución es multifactorial
(venta, margen directo, comisión venta, comisión envío, marketing).
Cada línea se muestra en $ Y en % sobre venta para aislar el factor:
si la contribución contable fue baja, acá se ve si fue por venta menor,
margen menor o una comisión específica más alta.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views.contribucion_loader import (
    cargar_hoja, parsear_columnas_numericas, fmt_pesos_M,
    render_contrib_filters, aplicar_filtros,
)


COLS_NUM = [
    # KAM (comercial)
    'Venta REAL KAM', 'Costo Venta KAM', 'Margen Directo KAM',
    'Comisión Venta KAM', 'Comisión Envío KAM', 'Marketing KAM',
    'Total Comisiones KAM', 'Resultado Contribución KAM',
    # Contable
    'Venta Real Contable', 'Costo Venta Contable', 'Margen Front Contable',
    'Comisión Venta Contable', 'Comisión Logística Contable', 'Marketing Contable',
    'Resultado Comisiones Contable', 'Total Contribución Contable',
]

# (label, col KAM, col Contable). El orden replica un P&L.
LINEAS_PYL = [
    ('Venta', 'Venta REAL KAM', 'Venta Real Contable'),
    ('Costo Venta', 'Costo Venta KAM', 'Costo Venta Contable'),
    ('Margen Directo', 'Margen Directo KAM', 'Margen Front Contable'),
    ('Comisión Venta', 'Comisión Venta KAM', 'Comisión Venta Contable'),
    ('Comisión Envío', 'Comisión Envío KAM', 'Comisión Logística Contable'),
    ('Marketing', 'Marketing KAM', 'Marketing Contable'),
    ('Total Comisiones', 'Total Comisiones KAM', 'Resultado Comisiones Contable'),
    ('Contribución', 'Resultado Contribución KAM', 'Total Contribución Contable'),
]

COLOR_KAM = '#1E40AF'
COLOR_CONT = '#94A3B8'


def _pct(monto, venta):
    return (monto / venta * 100) if venta else None


def _fmt_pct(v):
    return f"{v:.1f}%" if v is not None else "—"


def _tabla_pyl(df_f: pd.DataFrame) -> pd.DataFrame:
    """P&L comparativo: cada línea en $ y % sobre venta, con Δpp."""
    venta_kam = df_f['Venta REAL KAM'].sum()
    venta_cont = df_f['Venta Real Contable'].sum()
    rows = []
    for label, col_k, col_c in LINEAS_PYL:
        v_k = df_f[col_k].sum() if col_k in df_f.columns else 0
        v_c = df_f[col_c].sum() if col_c in df_f.columns else 0
        pct_k = _pct(v_k, venta_kam)
        pct_c = _pct(v_c, venta_cont)
        delta_pp = (pct_k - pct_c) if (pct_k is not None and pct_c is not None) else None
        rows.append({
            'Línea': label,
            'KAM $': v_k, 'KAM %Vta': pct_k,
            'Contable $': v_c, 'Contable %Vta': pct_c,
            'Δ $ (K-C)': v_k - v_c, 'Δ pp': delta_pp,
        })
    return pd.DataFrame(rows)


def render():
    with st.sidebar:
        st.markdown("### ⚖️ **Comercial vs Contable**")
        st.caption("Visión KAM vs Visión Contable")
        st.markdown("---")
        if st.button("🔄 Refrescar Sheet", width='stretch', type="primary", key="ccc_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("⚖️ Comercial vs Contable")
    st.caption("P&L comparativo en $ y % sobre venta — para aislar si la diferencia "
               "viene de la venta, el margen o una comisión específica")

    try:
        df = cargar_hoja("Análisis de Resultados")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return

    if df.empty:
        st.warning("Sin datos")
        return

    df = parsear_columnas_numericas(df, COLS_NUM)

    # Filtros al tope
    sel = render_contrib_filters(df, prefix="ccc")
    df_f = aplicar_filtros(df, sel)
    # Solo filas con alguna venta (las filas-mes vacías distorsionan los %)
    df_f = df_f[(df_f['Venta REAL KAM'] != 0) | (df_f['Venta Real Contable'] != 0)]
    st.caption(f"Filas filtradas: {len(df_f):,} de {len(df):,}")
    st.markdown("---")

    if df_f.empty:
        st.info("Sin filas con venta para los filtros seleccionados.")
        return

    # ============================================================
    # 1) P&L comparativo con % sobre venta
    # ============================================================
    st.markdown("### P&L comparativo — $ y % sobre venta")
    df_pyl = _tabla_pyl(df_f)

    df_show = df_pyl.copy()
    for c in ['KAM $', 'Contable $', 'Δ $ (K-C)']:
        df_show[c] = df_show[c].apply(fmt_pesos_M)
    df_show['KAM %Vta'] = df_show['KAM %Vta'].apply(_fmt_pct)
    df_show['Contable %Vta'] = df_show['Contable %Vta'].apply(_fmt_pct)
    df_show['Δ pp'] = df_show['Δ pp'].apply(lambda v: f"{v:+.1f}" if v is not None else "—")
    st.dataframe(df_show, width='stretch', hide_index=True)

    # ============================================================
    # 2) ¿Qué explica la diferencia? — Δpp por línea
    # ============================================================
    st.markdown("### ¿Qué explica la diferencia de contribución?")
    st.caption("Δ puntos porcentuales (KAM − Contable) de cada línea sobre su venta. "
               "Barras grandes = la línea que mueve la aguja.")
    df_delta = df_pyl[df_pyl['Línea'].isin(
        ['Costo Venta', 'Margen Directo', 'Comisión Venta', 'Comisión Envío', 'Marketing', 'Contribución']
    )].copy()
    colores = ['#DC2626' if (v is not None and abs(v) >= 3) else '#F59E0B' if (v is not None and abs(v) >= 1) else '#16A34A'
               for v in df_delta['Δ pp']]
    fig_d = go.Figure(go.Bar(
        x=df_delta['Línea'], y=df_delta['Δ pp'], marker_color=colores,
        text=[f"{v:+.1f}pp" if v is not None else "—" for v in df_delta['Δ pp']],
        textposition='outside',
    ))
    fig_d.update_layout(
        height=320, yaxis=dict(title='Δ pp (KAM − Contable)', zeroline=True, zerolinewidth=2),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(t=30, b=10),
    )
    st.plotly_chart(fig_d, width='stretch')

    # ============================================================
    # 3) Evolución mensual de % por comisión (KAM vs Contable)
    # ============================================================
    st.divider()
    st.markdown("### Evolución mensual — % de cada comisión sobre venta")
    st.caption("Respeta los filtros de canal/KAM/negocio pero muestra TODOS los meses "
               "(para comparar el mes en cuestión contra los anteriores). "
               "Línea continua = KAM · punteada = Contable.")

    sel_sin_mes = {**sel, 'mes': [], 'trim': []}
    df_t = aplicar_filtros(df, sel_sin_mes)
    df_t = df_t[(df_t['Venta REAL KAM'] != 0) | (df_t['Venta Real Contable'] != 0)].copy()
    df_t['Mes_num'] = pd.to_numeric(df_t['Mes'], errors='coerce')
    df_t = df_t.dropna(subset=['Mes_num'])

    g = df_t.groupby('Mes_num').agg(
        venta_k=('Venta REAL KAM', 'sum'), venta_c=('Venta Real Contable', 'sum'),
        cv_k=('Comisión Venta KAM', 'sum'), cv_c=('Comisión Venta Contable', 'sum'),
        ce_k=('Comisión Envío KAM', 'sum'), ce_c=('Comisión Logística Contable', 'sum'),
        mk_k=('Marketing KAM', 'sum'), mk_c=('Marketing Contable', 'sum'),
        md_k=('Margen Directo KAM', 'sum'), md_c=('Margen Front Contable', 'sum'),
        ct_k=('Resultado Contribución KAM', 'sum'), ct_c=('Total Contribución Contable', 'sum'),
    ).reset_index().sort_values('Mes_num')
    # Solo meses con venta en alguna vision
    g = g[(g['venta_k'] != 0) | (g['venta_c'] != 0)]

    series = [
        ('% Comisión Venta', 'cv_k', 'cv_c', '#DC2626'),
        ('% Comisión Envío', 'ce_k', 'ce_c', '#EA580C'),
        ('% Marketing', 'mk_k', 'mk_c', '#A855F7'),
        ('% Margen Directo', 'md_k', 'md_c', '#16A34A'),
        ('% Contribución', 'ct_k', 'ct_c', '#1E40AF'),
    ]
    visibles = st.multiselect(
        "Series", [s[0] for s in series],
        default=['% Comisión Venta', '% Comisión Envío', '% Marketing'],
        key="ccc_series",
    )

    MES_NOM = {1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun',
               7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'}
    x = [MES_NOM.get(int(m), str(int(m))) for m in g['Mes_num']]

    fig_t = go.Figure()
    for label, ck, cc, color in series:
        if label not in visibles:
            continue
        pct_k = (g[ck] / g['venta_k'] * 100).where(g['venta_k'] != 0)
        pct_c = (g[cc] / g['venta_c'] * 100).where(g['venta_c'] != 0)
        fig_t.add_trace(go.Scatter(
            x=x, y=pct_k, name=f"{label} KAM", mode='lines+markers',
            line=dict(color=color, width=2.5),
        ))
        fig_t.add_trace(go.Scatter(
            x=x, y=pct_c, name=f"{label} Contable", mode='lines+markers',
            line=dict(color=color, width=2, dash='dot'),
        ))
    fig_t.update_layout(
        height=420, yaxis=dict(title='% sobre venta', ticksuffix='%'),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(t=10, b=10),
    )
    st.plotly_chart(fig_t, width='stretch')

    # ============================================================
    # 4) Detalle por canal — % comisiones y Δpp
    # ============================================================
    st.divider()
    st.markdown("### Detalle por canal — % sobre venta y diferencias")
    st.caption("Ordenado por |Δ Contribución $|. Δpp = KAM − Contable sobre la venta de cada visión.")

    agg_canal = df_f.groupby('Canal').agg(
        venta_k=('Venta REAL KAM', 'sum'), venta_c=('Venta Real Contable', 'sum'),
        cv_k=('Comisión Venta KAM', 'sum'), cv_c=('Comisión Venta Contable', 'sum'),
        ce_k=('Comisión Envío KAM', 'sum'), ce_c=('Comisión Logística Contable', 'sum'),
        mk_k=('Marketing KAM', 'sum'), mk_c=('Marketing Contable', 'sum'),
        ct_k=('Resultado Contribución KAM', 'sum'), ct_c=('Total Contribución Contable', 'sum'),
    ).reset_index()
    agg_canal = agg_canal[(agg_canal['venta_k'] != 0) | (agg_canal['venta_c'] != 0)]
    agg_canal['delta_ct'] = agg_canal['ct_k'] - agg_canal['ct_c']
    agg_canal = agg_canal.sort_values('delta_ct', key=abs, ascending=False).head(20)

    rows_c = []
    for _, r in agg_canal.iterrows():
        def pp(col_k, col_c):
            pk = _pct(r[col_k], r['venta_k'])
            pc = _pct(r[col_c], r['venta_c'])
            if pk is None or pc is None:
                return "—"
            return f"{pk:.1f}% / {pc:.1f}% ({pk-pc:+.1f})"
        rows_c.append({
            'Canal': r['Canal'],
            'Venta K/C': f"{fmt_pesos_M(r['venta_k'])} / {fmt_pesos_M(r['venta_c'])}",
            'Com Venta K/C (Δpp)': pp('cv_k', 'cv_c'),
            'Com Envío K/C (Δpp)': pp('ce_k', 'ce_c'),
            'Marketing K/C (Δpp)': pp('mk_k', 'mk_c'),
            'Contrib K/C (Δpp)': pp('ct_k', 'ct_c'),
            'Δ Contrib $': fmt_pesos_M(r['delta_ct']),
        })
    st.dataframe(pd.DataFrame(rows_c), width='stretch', hide_index=True, height=420)
