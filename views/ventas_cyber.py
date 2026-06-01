"""
Vista Cyber 2026 — pulso comercial del evento.

Secciones:
1. Venta y margen acumulado por día / hora / canal
2. Top 30 ventas y margen (con filtros)
3. Top 30 por categoría padre/hijo
4. Alarma stock < 1 semana cobertura (vs venta promedio 4 sem)
5. Resultado vs Meta (diario y acumulado)
6. Estatus por tipo de producto / categoría / marca

Fuentes EN VIVO:
- views.shared.get_local_db_path()  → SQLite local que combina histórico
   parquet + Turso live (alimentado por sync cada 5 min). Es la misma fuente
   "RAW vivo" que usa la Vista General.
- views.shared.cached_stock()       → Stock Odoo live (parquets refrescados
   cada 3h por GH Actions, fallback Odoo XML-RPC).
- data/planificacion/plan_cyber_20260514.xlsx (metas)
"""
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from views.shared import cached_stock, get_local_db_path

PROJECT_ROOT = Path(__file__).parent.parent

CYBER_START = date(2026, 6, 1)
CYBER_END = date(2026, 6, 6)
CYBER_START_STR = CYBER_START.strftime('%Y-%m-%d')
CYBER_END_STR = CYBER_END.strftime('%Y-%m-%d')
CYBER_DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
CURVA_PCT = [0.30, 0.25, 0.20, 0.12, 0.08, 0.05]

META_JSON = PROJECT_ROOT / 'data' / 'planificacion' / 'plan_cyber_2026.json'
META_XLSX = PROJECT_ROOT / 'data' / 'planificacion' / 'plan_cyber_20260514.xlsx'
SIM_PARQUET = PROJECT_ROOT / 'data' / 'planificacion' / 'cyber_simulacion.parquet'

VENTAS_COLS = [
    'fecha_venta', 'hora_venta_num', 'documento', 'pedido', 'tipo_movimiento',
    'sku', 'producto', 'canal', 'marca', 'proveedor', 'kam',
    'tipo_negocio', 'categoria_macro', 'categoria_padre', 'categoria_hijo',
    'bodega', 'tipo_despacho',
    'cantidad', 'venta_bruta', 'venta_neta', 'costo_total',
    'margen_front', 'margen_final',
]


# ============================================================
# LOADERS
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def load_metas() -> pd.DataFrame:
    """Metas por canal del plan Cyber. Prefiere JSON committeable;
    fallback al xlsx original si está disponible localmente."""
    if META_JSON.exists():
        data = json.loads(META_JSON.read_text(encoding='utf-8'))
        return pd.DataFrame(data.get('metas_canal', []))
    if META_XLSX.exists():
        df = pd.read_excel(META_XLSX, sheet_name='Volumen + Venta por canal')
        df = df.rename(columns={
            'Canal': 'canal', 'Modalidad': 'modalidad',
            'Un Cyber': 'meta_uds', 'Vta Cyber Total': 'meta_venta',
            'Ticket prom.': 'ticket_meta',
        })
        keep = ['canal', 'modalidad', 'meta_uds', 'meta_venta', 'ticket_meta']
        df = df[[c for c in keep if c in df.columns]]
        df = df[df['canal'].notna() & df['meta_venta'].notna()].copy()
        df = df[~df['canal'].astype(str).str.upper().str.startswith('TOTAL')]
        return df.reset_index(drop=True)
    return pd.DataFrame()


@st.cache_data(ttl=180, show_spinner="Consultando ventas Cyber en vivo…")
def load_ventas_cyber(include_sim: bool = False) -> pd.DataFrame:
    """Ventas del rango Cyber leídas EN VIVO desde el SQLite local
    (histórico parquet + Turso live). Si include_sim=True suma el parquet
    de simulación (datos sintéticos para previsualización)."""
    db_path = get_local_db_path()
    cols = ','.join(VENTAS_COLS)
    sql = f"SELECT {cols} FROM ventas WHERE fecha_venta BETWEEN ? AND ?"
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(sql, conn, params=(CYBER_START_STR, CYBER_END_STR))
    finally:
        conn.close()

    if include_sim and SIM_PARQUET.exists():
        sim = pd.read_parquet(SIM_PARQUET)
        sim = sim[[c for c in VENTAS_COLS if c in sim.columns]]
        df = pd.concat([df, sim], ignore_index=True)

    if df.empty:
        return df
    df['fecha_venta'] = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.date
    return df


@st.cache_data(ttl=300, show_spinner="Calculando promedio 4 semanas…")
def load_ventas_4sem() -> pd.DataFrame:
    """Últimas 4 semanas por SKU desde el SQLite local (RAW vivo).
    Solo registros tipo Venta (excluye NCs)."""
    db_path = get_local_db_path()
    desde = (date.today() - timedelta(days=28)).strftime('%Y-%m-%d')
    sql = """
        SELECT sku, SUM(cantidad) AS uds_28d
        FROM ventas
        WHERE fecha_venta >= ?
          AND (tipo_movimiento = 'Venta' OR tipo_movimiento IS NULL)
        GROUP BY sku
    """
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(sql, conn, params=(desde,))
    finally:
        conn.close()
    return df


def load_stock() -> pd.DataFrame:
    """Stock LIVE: usa el helper compartido (parquets 3h o Odoo fallback)."""
    try:
        data = cached_stock()
    except Exception as e:
        st.error(f"❌ Error consultando stock: {type(e).__name__}: {e}")
        return pd.DataFrame()
    df = pd.DataFrame(data.get('skus', []))
    return df


# ============================================================
# HELPERS
# ============================================================
def fmt_money(v) -> str:
    """Formato inteligente con 1 decimal: $526.5 M / $15.9 M / $1.5 K / $500"""
    if pd.isna(v) or v == 0:
        return '$0'
    abs_v = abs(v)
    if abs_v >= 1_000_000:
        s = f"{v/1_000_000:.1f}"
        return f"${s} M"
    if abs_v >= 1_000:
        s = f"{v/1_000:.1f}"
        return f"${s} K"
    return f"${v:,.0f}".replace(",", ".")


def fmt_pct(v) -> str:
    if pd.isna(v):
        return '—'
    return f"{v*100:.1f}%"


def es_fulfillment(bodega: str) -> bool:
    """True si la bodega es de fulfillment (marketplace entrega), False = seller/flex."""
    if not isinstance(bodega, str):
        return False
    return bodega.strip().lower().startswith('bodega fulfillment')


def add_aggregates(df: pd.DataFrame) -> pd.DataFrame:
    """Asegura que existan columnas usadas downstream."""
    if df.empty:
        return df
    for c in ('venta_bruta', 'venta_neta', 'margen_final', 'cantidad', 'costo_total'):
        if c not in df.columns:
            df[c] = 0
    return df


# ============================================================
# RENDER
# ============================================================
def render():
    st.title("🛍️ Cyber 2026 — Pulso comercial")
    st.caption(f"Rango: **{CYBER_START.strftime('%d-%b-%Y')}** a **{CYBER_END.strftime('%d-%b-%Y')}** · "
               f"Meta total: **$505.9 MM / 20.486 uds** · "
               f"Fuente: **RAW vivo** (Turso + histórico) — refresh 3 min · Stock Odoo live · "
               f"**Montos en miles (K)**")

    # Toggle modo simulación. Auto-activado si el Cyber aún no empezó.
    today = date.today()
    sim_default = today < CYBER_START
    with st.sidebar:
        st.markdown("### 🛍️ Cyber 2026")
        sim_on = st.toggle(
            "🧪 Modo simulación",
            value=sim_default, key="cyber_sim_toggle",
            help="Incluye datos sintéticos del lunes hasta las 12:00 (escenario hipotético). "
                 "Los documentos llevan prefijo 'SIM-' para distinguirlos. "
                 "Auto-activado mientras el Cyber no haya empezado.",
        )
        if sim_on:
            st.warning("🧪 Simulación ACTIVA — datos sintéticos")
        if st.button("🔄 Refrescar venta", use_container_width=True, key="cyber_refresh_venta"):
            load_ventas_cyber.clear()
            load_ventas_4sem.clear()
            st.rerun()

    ventas = add_aggregates(load_ventas_cyber(include_sim=sim_on))
    metas = load_metas()

    if ventas.empty and not sim_on:
        st.info("Aún no hay ventas registradas en el rango Cyber. Activa 🧪 simulación en la sidebar para previsualizar.")
    if today < CYBER_START:
        if sim_on:
            st.warning(f"⏳ Cyber empieza en {(CYBER_START - today).days} día(s). Mostrando datos SIMULADOS del lunes hasta las 12:00.")
        else:
            st.warning(f"⏳ Cyber empieza en {(CYBER_START - today).days} día(s). Activa simulación en sidebar para preview.")

    # ============================================================
    # HEADER KPIs vs META
    # ============================================================
    venta_bruta = ventas['venta_bruta'].sum() if not ventas.empty else 0
    venta_neta = ventas['venta_neta'].sum() if not ventas.empty else 0
    margen = ventas['margen_final'].sum() if not ventas.empty else 0
    uds = ventas['cantidad'].sum() if not ventas.empty else 0
    meta_total_venta = metas['meta_venta'].sum() if not metas.empty else 0
    meta_total_uds = metas['meta_uds'].sum() if not metas.empty else 0
    pct_avance = (venta_bruta / meta_total_venta) if meta_total_venta else 0
    margen_pct = (margen / venta_neta) if venta_neta else 0
    gap_meta = meta_total_venta - venta_bruta

    st.markdown("### 📊 Resumen vs Meta")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Venta bruta", fmt_money(venta_bruta), f"{pct_avance*100:.1f}% de meta")
    c2.metric("Margen $", fmt_money(margen), fmt_pct(margen_pct))
    c3.metric("Unidades", f"{uds:,.0f}",
              f"{((uds/meta_total_uds if meta_total_uds else 0)*100):.1f}% de meta")
    c4.metric("Meta venta", fmt_money(meta_total_venta))
    c5.metric("Gap a meta", fmt_money(gap_meta),
              delta=f"{-pct_avance*100:.1f}%" if gap_meta > 0 else "✓",
              delta_color="inverse")

    st.divider()

    tabs = st.tabs([
        "📈 Acumulado",
        "🏆 Top productos / categorías",
        "📦 Alarma stock",
        "🎯 Resultado vs Meta",
        "🔍 Estatus por dimensión",
    ])

    # ============================================================
    # TAB 1: Acumulado (día / hora / canal)
    # ============================================================
    with tabs[0]:
        _tab_acumulado(ventas)

    # ============================================================
    # TAB 2: Top productos / categorías
    # ============================================================
    with tabs[1]:
        _tab_top(ventas)

    # ============================================================
    # TAB 3: Alarma stock
    # ============================================================
    with tabs[2]:
        _tab_stock_alarma()

    # ============================================================
    # TAB 4: Resultado vs Meta
    # ============================================================
    with tabs[3]:
        _tab_vs_meta(ventas, metas)

    # ============================================================
    # TAB 5: Estatus por dimensión
    # ============================================================
    with tabs[4]:
        _tab_status_dim(ventas, metas)


# ============================================================
# TAB 1: Acumulado
# ============================================================
def _tab_acumulado(ventas: pd.DataFrame):
    st.subheader("Venta y margen acumulado")

    if ventas.empty:
        st.info("Sin datos.")
        return

    # Filtros día / hora / canal
    fechas_disp = sorted(ventas['fecha_venta'].dropna().unique())
    canales_disp = sorted(ventas['canal'].dropna().unique())

    f1, f2, f3 = st.columns([1.2, 1.5, 1.5])
    sel_dias = f1.multiselect(
        "Días", fechas_disp, default=fechas_disp,
        format_func=lambda d: d.strftime('%a %d-%b') if hasattr(d, 'strftime') else str(d),
        key='cyber_acum_dia',
    )
    hora_min, hora_max = f2.slider(
        "Rango horario", 0, 23, (0, 23), key='cyber_acum_hora',
    )
    sel_canales = f3.multiselect("Canal", canales_disp, default=[], key='cyber_acum_canal')

    df = ventas.copy()
    if sel_dias:
        df = df[df['fecha_venta'].isin(sel_dias)]
    if 'hora_venta_num' in df.columns:
        df = df[(df['hora_venta_num'].fillna(0) >= hora_min) & (df['hora_venta_num'].fillna(0) <= hora_max)]
    if sel_canales:
        df = df[df['canal'].isin(sel_canales)]

    if df.empty:
        st.info("Sin datos con esos filtros.")
        return

    # KPIs filtrados
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Bruta filtrada", fmt_money(df['venta_bruta'].sum()))
    k2.metric("Margen $", fmt_money(df['margen_final'].sum()))
    k3.metric("Margen %", fmt_pct(df['margen_final'].sum() / df['venta_neta'].sum() if df['venta_neta'].sum() else 0))
    k4.metric("Uds", f"{df['cantidad'].sum():,.0f}")

    # Por día
    st.markdown("**Por día**")
    g_dia = df.groupby('fecha_venta', as_index=False).agg(
        venta_bruta=('venta_bruta', 'sum'),
        venta_neta=('venta_neta', 'sum'),
        margen=('margen_final', 'sum'),
        uds=('cantidad', 'sum'),
    ).sort_values('fecha_venta')
    g_dia['margen_pct'] = g_dia['margen'] / g_dia['venta_neta'].replace(0, pd.NA)
    g_dia['venta_acum'] = g_dia['venta_bruta'].cumsum()
    g_dia['margen_acum'] = g_dia['margen'].cumsum()

    fig = go.Figure()
    fig.add_bar(x=g_dia['fecha_venta'], y=g_dia['venta_bruta'], name='Venta bruta',
                marker_color='#2563EB',
                hovertemplate='%{x}<br>%{y:,.0f}<extra></extra>')
    fig.add_trace(go.Scatter(x=g_dia['fecha_venta'], y=g_dia['margen'], name='Margen $',
                             mode='lines+markers', line=dict(color='#16A34A')))
    fig.add_trace(go.Scatter(x=g_dia['fecha_venta'], y=g_dia['venta_acum'], name='Acumulado',
                             mode='lines', line=dict(color='#EA580C', dash='dash')))
    fig.update_layout(height=350, hovermode='x unified',
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, x=0),
                      yaxis_title='CLP')
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        g_dia.assign(
            venta_bruta=g_dia['venta_bruta'].map(fmt_money),
            margen=g_dia['margen'].map(fmt_money),
            venta_acum=g_dia['venta_acum'].map(fmt_money),
            margen_acum=g_dia['margen_acum'].map(fmt_money),
            margen_pct=g_dia['margen_pct'].map(lambda x: fmt_pct(x) if pd.notna(x) else '—'),
            uds=g_dia['uds'].astype(int),
        )[['fecha_venta', 'venta_bruta', 'margen', 'margen_pct', 'uds', 'venta_acum', 'margen_acum']],
        use_container_width=True, hide_index=True,
    )

    # Por hora
    st.markdown("**Por hora**")
    if 'hora_venta_num' not in df.columns:
        st.caption("Falta columna hora_venta_num — corre el sync de mes actual.")
    else:
        g_hora = df.groupby('hora_venta_num', as_index=False).agg(
            venta=('venta_bruta', 'sum'),
            margen=('margen_final', 'sum'),
            uds=('cantidad', 'sum'),
        )
        fig2 = go.Figure()
        fig2.add_bar(x=g_hora['hora_venta_num'], y=g_hora['venta'], name='Venta',
                     marker_color='#2563EB')
        fig2.add_trace(go.Scatter(x=g_hora['hora_venta_num'], y=g_hora['margen'], name='Margen',
                                  mode='lines+markers', line=dict(color='#16A34A')))
        fig2.update_layout(height=280, xaxis_title='Hora', hovermode='x unified',
                           legend=dict(orientation='h', yanchor='bottom', y=1.02, x=0))
        st.plotly_chart(fig2, use_container_width=True)

    # Tabla por día × hora: venta y margen
    if 'hora_venta_num' in df.columns:
        st.markdown("**📋 Venta y Margen por Hora del Día**")
        # Pivot venta y margen
        pv_v = df.pivot_table(
            index='hora_venta_num', columns='fecha_venta',
            values='venta_bruta', aggfunc='sum', fill_value=0,
        ).reindex(range(24), fill_value=0)
        pv_m = df.pivot_table(
            index='hora_venta_num', columns='fecha_venta',
            values='margen_final', aggfunc='sum', fill_value=0,
        ).reindex(range(24), fill_value=0)

        # Construir tabla wide: por cada día, columnas Venta y Margen
        tabla = pd.DataFrame(index=range(24))
        tabla.index.name = 'Hora'
        for d in pv_v.columns:
            day_label = d.strftime('%a %d-%b') if hasattr(d, 'strftime') else str(d)
            tabla[f'{day_label} · Venta'] = pv_v[d].map(fmt_money)
            tabla[f'{day_label} · Margen'] = pv_m[d].map(fmt_money)
        # Fila TOTAL al final
        total_row = {}
        for d in pv_v.columns:
            day_label = d.strftime('%a %d-%b') if hasattr(d, 'strftime') else str(d)
            total_row[f'{day_label} · Venta'] = fmt_money(pv_v[d].sum())
            total_row[f'{day_label} · Margen'] = fmt_money(pv_m[d].sum())
        tabla.loc['TOTAL'] = total_row

        st.dataframe(tabla, use_container_width=True, height=min(880, 40 + 25*25))

    # Heatmap día × hora (visual)
    if 'hora_venta_num' in df.columns and len(sel_dias) > 1:
        st.markdown("**🔥 Heatmap día × hora (visual)**")
        pivot = df.pivot_table(
            index='hora_venta_num', columns='fecha_venta',
            values='venta_bruta', aggfunc='sum', fill_value=0,
        ).reindex(range(24), fill_value=0)
        fig_h = go.Figure(go.Heatmap(
            z=pivot.values, x=[d.strftime('%a %d') if hasattr(d, 'strftime') else str(d) for d in pivot.columns],
            y=pivot.index, colorscale='Blues',
            hovertemplate='%{x} %{y}h<br>$%{z:,.0f}<extra></extra>',
        ))
        fig_h.update_layout(height=420, yaxis_title='Hora', xaxis_title='')
        st.plotly_chart(fig_h, use_container_width=True)

    # Fulfillment vs Seller+Flex
    st.markdown("**📦 Fulfillment vs Seller + Flex**")
    df_f = df.copy()
    if 'bodega' not in df_f.columns:
        df_f['bodega'] = ''
    df_f['modalidad'] = df_f['bodega'].apply(
        lambda b: 'Fulfillment' if es_fulfillment(b) else 'Seller + Flex'
    )
    g_f = df_f.groupby('modalidad', as_index=False).agg(
        venta_bruta=('venta_bruta', 'sum'),
        venta_neta=('venta_neta', 'sum'),
        margen=('margen_final', 'sum'),
        uds=('cantidad', 'sum'),
        sos=('pedido', 'nunique'),
    )
    g_f['share'] = g_f['venta_bruta'] / g_f['venta_bruta'].sum() if g_f['venta_bruta'].sum() else 0
    g_f['margen_pct'] = g_f['margen'] / g_f['venta_neta'].replace(0, pd.NA)

    col_a, col_b = st.columns([1.5, 1])
    with col_a:
        st.dataframe(
            g_f.assign(
                venta_bruta=g_f['venta_bruta'].map(fmt_money),
                margen=g_f['margen'].map(fmt_money),
                share=g_f['share'].map(fmt_pct),
                margen_pct=g_f['margen_pct'].map(fmt_pct),
                uds=g_f['uds'].astype(int),
            )[['modalidad', 'sos', 'uds', 'venta_bruta', 'margen', 'margen_pct', 'share']],
            use_container_width=True, hide_index=True,
        )
    with col_b:
        if not g_f.empty:
            fig_f = go.Figure(go.Pie(
                labels=g_f['modalidad'], values=g_f['venta_bruta'],
                hole=0.5,
                marker=dict(colors=['#EA580C', '#2563EB']),
            ))
            fig_f.update_layout(height=220, margin=dict(t=10, b=10, l=10, r=10), showlegend=True)
            st.plotly_chart(fig_f, use_container_width=True)

    # Por canal
    st.markdown("**Por canal (en filtro)**")
    g_can = df.groupby('canal', as_index=False).agg(
        venta_bruta=('venta_bruta', 'sum'),
        margen=('margen_final', 'sum'),
        uds=('cantidad', 'sum'),
    ).sort_values('venta_bruta', ascending=False)
    g_can['margen_pct'] = g_can['margen'] / g_can['venta_bruta'].replace(0, pd.NA)

    col1, col2 = st.columns([1.2, 1])
    with col1:
        fig3 = px.bar(g_can, x='canal', y='venta_bruta', color='canal',
                      labels={'venta_bruta': 'Venta bruta', 'canal': ''}, height=350)
        fig3.update_layout(showlegend=False)
        st.plotly_chart(fig3, use_container_width=True)
    with col2:
        st.dataframe(
            g_can.assign(
                venta_bruta=g_can['venta_bruta'].map(fmt_money),
                margen=g_can['margen'].map(fmt_money),
                margen_pct=g_can['margen_pct'].map(fmt_pct),
                uds=g_can['uds'].astype(int),
            ),
            use_container_width=True, hide_index=True, height=350,
        )

    # Footer comparación final vs meta (con filtros aplicados)
    st.markdown("---")
    st.markdown("### 🎯 Cierre vs Meta (filtrado)")
    total_bruta = df['venta_bruta'].sum()
    total_margen = df['margen_final'].sum()
    total_uds = df['cantidad'].sum()
    total_neta = df['venta_neta'].sum()
    margen_pct_total = (total_margen / total_neta) if total_neta else 0
    # Meta proporcional al filtro (% curva de días seleccionados)
    if sel_dias:
        dias_idx = [(d - CYBER_START).days for d in sel_dias if hasattr(d, 'strftime')]
        pct_curva = sum(CURVA_PCT[i] for i in dias_idx if 0 <= i < len(CURVA_PCT))
    else:
        pct_curva = 1.0
    meta_filt = meta_total_venta * pct_curva
    avance = (total_bruta / meta_filt) if meta_filt else 0

    fc1, fc2, fc3, fc4 = st.columns(4)
    fc1.metric("Venta filtrada", fmt_money(total_bruta), f"{avance*100:.1f}% de meta")
    fc2.metric("Margen $", fmt_money(total_margen), fmt_pct(margen_pct_total))
    fc3.metric("Meta filtrada", fmt_money(meta_filt),
               help=f"Meta total × {pct_curva*100:.1f}% (curva diaria)")
    fc4.metric("Gap", fmt_money(meta_filt - total_bruta),
               delta=f"{(avance-1)*100:.1f}%" if meta_filt else "—",
               delta_color="normal")


# ============================================================
# TAB 2: Top
# ============================================================
def _tab_top(ventas: pd.DataFrame):
    st.subheader("Top 30")

    if ventas.empty:
        st.info("Sin datos.")
        return

    # Filtros compartidos
    f1, f2, f3, f4 = st.columns(4)
    canales = sorted(ventas['canal'].dropna().unique().tolist())
    marcas = sorted(ventas['marca'].dropna().unique().tolist()) if 'marca' in ventas.columns else []
    lineas = sorted(ventas['tipo_negocio'].dropna().unique().tolist()) if 'tipo_negocio' in ventas.columns else []
    macros = sorted(ventas['categoria_macro'].dropna().unique().tolist()) if 'categoria_macro' in ventas.columns else []

    sel_canal = f1.multiselect('Canal', canales, default=[], key='cyber_top_canal')
    sel_marca = f2.multiselect('Marca', marcas, default=[], key='cyber_top_marca')
    sel_linea = f3.multiselect('Línea negocio', lineas, default=[], key='cyber_top_linea')
    sel_macro = f4.multiselect('Categoría macro', macros, default=[], key='cyber_top_macro')

    df = ventas.copy()
    if sel_canal: df = df[df['canal'].isin(sel_canal)]
    if sel_marca and 'marca' in df.columns: df = df[df['marca'].isin(sel_marca)]
    if sel_linea and 'tipo_negocio' in df.columns: df = df[df['tipo_negocio'].isin(sel_linea)]
    if sel_macro and 'categoria_macro' in df.columns: df = df[df['categoria_macro'].isin(sel_macro)]

    metric = st.radio("Ordenar por", ['Venta bruta', 'Margen $'], horizontal=True, key='cyber_top_metric')
    sort_col = 'venta_bruta' if metric == 'Venta bruta' else 'margen'

    st.markdown("**Top 30 productos**")
    g_prod = df.groupby(['sku', 'producto'], as_index=False).agg(
        venta_bruta=('venta_bruta', 'sum'),
        margen=('margen_final', 'sum'),
        uds=('cantidad', 'sum'),
    )
    g_prod['margen_pct'] = g_prod['margen'] / g_prod['venta_bruta'].replace(0, pd.NA)
    g_prod = g_prod.sort_values(sort_col, ascending=False).head(30)
    st.dataframe(
        g_prod.assign(
            venta_bruta=g_prod['venta_bruta'].map(fmt_money),
            margen=g_prod['margen'].map(fmt_money),
            margen_pct=g_prod['margen_pct'].map(fmt_pct),
            uds=g_prod['uds'].astype(int),
        ),
        use_container_width=True, hide_index=True, height=420,
    )

    # Categoría padre
    st.markdown("**Top 30 categoría padre**")
    if 'categoria_padre' in df.columns:
        g_pad = df.groupby('categoria_padre', as_index=False).agg(
            venta_bruta=('venta_bruta', 'sum'),
            margen=('margen_final', 'sum'),
            uds=('cantidad', 'sum'),
        )
        g_pad['margen_pct'] = g_pad['margen'] / g_pad['venta_bruta'].replace(0, pd.NA)
        g_pad = g_pad.sort_values(sort_col, ascending=False).head(30)
        st.dataframe(
            g_pad.assign(
                venta_bruta=g_pad['venta_bruta'].map(fmt_money),
                margen=g_pad['margen'].map(fmt_money),
                margen_pct=g_pad['margen_pct'].map(fmt_pct),
                uds=g_pad['uds'].astype(int),
            ),
            use_container_width=True, hide_index=True, height=320,
        )

    # Categoría hijo
    st.markdown("**Top 30 categoría hijo**")
    if 'categoria_hijo' in df.columns:
        g_hij = df.groupby(['categoria_padre', 'categoria_hijo'], as_index=False).agg(
            venta_bruta=('venta_bruta', 'sum'),
            margen=('margen_final', 'sum'),
            uds=('cantidad', 'sum'),
        )
        g_hij['margen_pct'] = g_hij['margen'] / g_hij['venta_bruta'].replace(0, pd.NA)
        g_hij = g_hij.sort_values(sort_col, ascending=False).head(30)
        st.dataframe(
            g_hij.assign(
                venta_bruta=g_hij['venta_bruta'].map(fmt_money),
                margen=g_hij['margen'].map(fmt_money),
                margen_pct=g_hij['margen_pct'].map(fmt_pct),
                uds=g_hij['uds'].astype(int),
            ),
            use_container_width=True, hide_index=True, height=320,
        )


# ============================================================
# TAB 3: Alarma stock
# ============================================================
def _tab_stock_alarma():
    st.subheader("Alarma de cobertura < 1 semana")
    st.caption("Venta RAW vivo últimos 28 días (Turso) vs stock disponible Odoo live. "
               "Si cobertura < 7 días → alarma.")

    if st.button("🔄 Refrescar stock Odoo", key="cyber_stock_refresh"):
        cached_stock.clear()
        st.rerun()

    stock = load_stock()
    vt4 = load_ventas_4sem()

    if stock.empty:
        st.warning("No hay snapshot de stock disponible.")
        return
    if vt4.empty:
        st.warning("Sin ventas 28d en DB local.")
        return

    g_v = vt4.copy()
    g_v['vta_diaria'] = g_v['uds_28d'] / 28.0

    # Stock LIVE: el helper ya entrega SKUs agregados
    if 'SKU' not in stock.columns:
        st.warning("Stock parquet no tiene columna SKU.")
        return
    g_s = stock.rename(columns={
        'SKU': 'sku', 'Producto': 'producto', 'Marca': 'marca',
        'Categoria': 'categoria', 'Disponible': 'disponible', 'Costo Unit': 'costo',
    })
    keep = [c for c in ['sku', 'producto', 'marca', 'categoria', 'disponible', 'costo'] if c in g_s.columns]
    g_s = g_s[keep].copy()

    df = g_s.merge(g_v[['sku', 'vta_diaria', 'uds_28d']], on='sku', how='left')
    df['vta_diaria'] = df['vta_diaria'].fillna(0)
    df['uds_28d'] = df['uds_28d'].fillna(0)
    df['disponible'] = pd.to_numeric(df['disponible'], errors='coerce').fillna(0)
    df['dias_cobertura'] = df.apply(
        lambda r: (r['disponible'] / r['vta_diaria']) if r['vta_diaria'] > 0 else 999,
        axis=1,
    )

    # Filtrar SKUs con venta efectiva (descartar 0)
    activos = df[df['uds_28d'] > 0].copy()
    alarma = activos[activos['dias_cobertura'] < 7].copy()
    alarma = alarma.sort_values('dias_cobertura')

    c1, c2, c3 = st.columns(3)
    c1.metric("SKUs activos (28d)", f"{len(activos):,}")
    c2.metric("🚨 SKUs en alarma (<7d)", f"{len(alarma):,}")
    c3.metric("SKUs en quiebre (=0 stock)", f"{(activos['disponible']==0).sum():,}")

    if alarma.empty:
        st.success("Sin alertas críticas de cobertura.")
        return

    alarma['valor_perdido_proy'] = (alarma['vta_diaria'] * 7 - alarma['disponible']).clip(lower=0) * alarma['costo'].fillna(0)
    alarma_display = alarma[['sku', 'producto', 'marca', 'categoria',
                              'disponible', 'uds_28d', 'vta_diaria',
                              'dias_cobertura', 'valor_perdido_proy']].copy()
    alarma_display['disponible'] = alarma_display['disponible'].astype(int)
    alarma_display['uds_28d'] = alarma_display['uds_28d'].astype(int)
    alarma_display['vta_diaria'] = alarma_display['vta_diaria'].round(1)
    alarma_display['dias_cobertura'] = alarma_display['dias_cobertura'].round(1)
    alarma_display['valor_perdido_proy'] = alarma_display['valor_perdido_proy'].map(fmt_money)

    st.dataframe(alarma_display, use_container_width=True, hide_index=True, height=500)
    st.caption(f"Valor perdido proyectado = (venta esperada 7d − stock disponible) × costo unitario. "
               f"Total acumulado: {fmt_money(alarma['valor_perdido_proy'].sum())}")


# ============================================================
# TAB 4: Resultado vs Meta
# ============================================================
def _tab_vs_meta(ventas: pd.DataFrame, metas: pd.DataFrame):
    st.subheader("Resultado vs Meta")

    if metas.empty:
        st.warning(f"No se pudo leer meta (esperado en {META_JSON.name} o {META_XLSX.name})")
        return

    # Comparativo por canal
    if ventas.empty:
        actual = pd.DataFrame(columns=['canal', 'venta_real', 'uds_real'])
    else:
        actual = ventas.groupby('canal', as_index=False).agg(
            venta_real=('venta_bruta', 'sum'),
            uds_real=('cantidad', 'sum'),
        )

    cmp = metas.merge(actual, on='canal', how='left')
    cmp['venta_real'] = cmp['venta_real'].fillna(0)
    cmp['uds_real'] = cmp['uds_real'].fillna(0)
    cmp['avance_pct'] = cmp['venta_real'] / cmp['meta_venta']
    cmp['gap'] = cmp['meta_venta'] - cmp['venta_real']
    cmp = cmp.sort_values('meta_venta', ascending=False)

    fig = go.Figure()
    fig.add_bar(name='Meta', x=cmp['canal'], y=cmp['meta_venta'],
                marker_color='#94A3B8', text=cmp['meta_venta'].map(fmt_money), textposition='outside')
    fig.add_bar(name='Real', x=cmp['canal'], y=cmp['venta_real'],
                marker_color='#2563EB', text=cmp['venta_real'].map(fmt_money), textposition='outside')
    fig.update_layout(barmode='group', height=400, hovermode='x unified',
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, x=0))
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        cmp.assign(
            meta_venta=cmp['meta_venta'].map(fmt_money),
            venta_real=cmp['venta_real'].map(fmt_money),
            gap=cmp['gap'].map(fmt_money),
            avance_pct=cmp['avance_pct'].map(fmt_pct),
            meta_uds=cmp['meta_uds'].astype(int),
            uds_real=cmp['uds_real'].astype(int),
        )[['canal', 'modalidad', 'meta_uds', 'uds_real', 'meta_venta', 'venta_real', 'avance_pct', 'gap']],
        use_container_width=True, hide_index=True,
    )

    # Comparativo diario vs curva esperada
    st.markdown("---")
    st.markdown("**Avance diario vs curva esperada**")
    meta_total = metas['meta_venta'].sum()
    curva = pd.DataFrame({
        'fecha': pd.date_range(CYBER_START, CYBER_END).date,
        'dia_nombre': CYBER_DIAS,
        'pct': CURVA_PCT,
    })
    curva['meta_dia'] = curva['pct'] * meta_total
    curva['meta_acum'] = curva['meta_dia'].cumsum()

    if not ventas.empty:
        g_real = ventas.groupby('fecha_venta', as_index=False).agg(real=('venta_bruta', 'sum'))
        curva = curva.merge(g_real, left_on='fecha', right_on='fecha_venta', how='left')
        curva['real'] = curva['real'].fillna(0)
        curva['real_acum'] = curva['real'].cumsum()
    else:
        curva['real'] = 0
        curva['real_acum'] = 0

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=curva['fecha'], y=curva['meta_acum'], name='Meta acumulada',
                              mode='lines+markers', line=dict(color='#94A3B8', dash='dash')))
    fig2.add_trace(go.Scatter(x=curva['fecha'], y=curva['real_acum'], name='Real acumulado',
                              mode='lines+markers', line=dict(color='#2563EB', width=3)))
    fig2.update_layout(height=350, hovermode='x unified')
    st.plotly_chart(fig2, use_container_width=True)

    st.dataframe(
        curva.assign(
            meta_dia=curva['meta_dia'].map(fmt_money),
            meta_acum=curva['meta_acum'].map(fmt_money),
            real=curva['real'].map(fmt_money),
            real_acum=curva['real_acum'].map(fmt_money),
            pct=curva['pct'].map(lambda x: f"{x:.0%}"),
        )[['fecha', 'dia_nombre', 'pct', 'meta_dia', 'real', 'meta_acum', 'real_acum']],
        use_container_width=True, hide_index=True,
    )


# ============================================================
# TAB 5: Estatus por dimensión
# ============================================================
def _tab_status_dim(ventas: pd.DataFrame, metas: pd.DataFrame):
    st.subheader("Estatus de venta por dimensión")

    if ventas.empty:
        st.info("Aún sin venta Cyber.")
        return

    dim = st.radio("Dimensión", ['Línea negocio', 'Categoría macro', 'Categoría padre',
                                  'Marca', 'KAM', 'Proveedor'], horizontal=True, key='cyber_dim')

    dim_col = {
        'Línea negocio': 'tipo_negocio',
        'Categoría macro': 'categoria_macro',
        'Categoría padre': 'categoria_padre',
        'Marca': 'marca',
        'KAM': 'kam',
        'Proveedor': 'proveedor',
    }[dim]

    if dim_col not in ventas.columns:
        st.warning(f"Columna '{dim_col}' no disponible.")
        return

    g = ventas.groupby(dim_col, as_index=False).agg(
        venta_bruta=('venta_bruta', 'sum'),
        venta_neta=('venta_neta', 'sum'),
        margen=('margen_final', 'sum'),
        uds=('cantidad', 'sum'),
    )
    g['margen_pct'] = g['margen'] / g['venta_neta'].replace(0, pd.NA)
    g['share_pct'] = g['venta_bruta'] / g['venta_bruta'].sum()
    g = g.sort_values('venta_bruta', ascending=False)

    fig = px.bar(g, x=dim_col, y='venta_bruta', color='margen_pct',
                 color_continuous_scale='RdYlGn', range_color=[0, 0.4],
                 labels={'venta_bruta': 'Venta bruta', 'margen_pct': 'Margen %'},
                 height=400)
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        g.assign(
            venta_bruta=g['venta_bruta'].map(fmt_money),
            venta_neta=g['venta_neta'].map(fmt_money),
            margen=g['margen'].map(fmt_money),
            margen_pct=g['margen_pct'].map(fmt_pct),
            share_pct=g['share_pct'].map(fmt_pct),
            uds=g['uds'].astype(int),
        ),
        use_container_width=True, hide_index=True, height=400,
    )
