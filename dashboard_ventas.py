"""
Dashboard Ventas UnionX — análisis YoY (TY vs LY) + descarga RAW.

Vista General  | Vista Semanal  con filtros por categoría, marca, tipo negocio, canal.

Ejecutar:
    streamlit run dashboard_ventas.py
"""
import io
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
import streamlit_authenticator as stauth

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

# Streamlit Cloud: exponer secretos como env vars (db_client lee de os.environ)
for _key in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN'):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

from app.services.maestra_service import MaestraService
from db_client import get_db_path

DB_PATH = get_db_path()

st.set_page_config(
    page_title="Dashboard Ventas UnionX",
    page_icon="📊",
    layout="wide",
)

# ===== Autenticación =====
def _load_auth_config():
    """Carga config de auth desde st.secrets (cloud) o auth_config.yaml (local)."""
    if 'auth' in st.secrets:
        return dict(st.secrets['auth'])
    cfg_path = PROJECT_ROOT / 'auth_config.yaml'
    if cfg_path.exists():
        with open(cfg_path, encoding='utf-8') as f:
            return yaml.safe_load(f)
    return None

auth_config = _load_auth_config()
if auth_config:
    authenticator = stauth.Authenticate(
        auth_config['credentials'],
        auth_config['cookie']['name'],
        auth_config['cookie']['key'],
        auth_config['cookie']['expiry_days'],
    )
    try:
        authenticator.login(location='main', key='login_main')
    except Exception:
        pass

    if st.session_state.get('authentication_status') is False:
        st.error('Usuario o contraseña incorrectos')
        st.stop()
    elif st.session_state.get('authentication_status') is None:
        st.warning('Por favor ingresa tu usuario y contraseña')
        st.stop()
    # Autenticado
    with st.sidebar:
        authenticator.logout('Cerrar sesión', 'sidebar')
        st.write(f"👤 **{st.session_state.get('name', '')}**")

# ===== Helpers =====
def fmt_money(v):
    if v is None or pd.isna(v): return "-"
    return f"${int(round(v)):,}".replace(",", ".")

def fmt_int(v):
    if v is None or pd.isna(v): return "-"
    return f"{int(round(v)):,}".replace(",", ".")

def fmt_pct(v, decimals=1):
    if v is None or pd.isna(v): return "-"
    return f"{v:.{decimals}f}%"

@st.cache_resource
def get_service():
    return MaestraService(str(DB_PATH))

@st.cache_data(ttl=300)
def cached_filtros():
    return get_service().get_filtros_disponibles()

@st.cache_data(ttl=300)
def cached_kpis(desde, hasta, canal, marca, categoria, tipo_negocio, kam):
    p = {'fecha_desde': desde, 'fecha_hasta': hasta}
    if canal: p['canal'] = canal
    if marca: p['marca'] = marca
    if categoria: p['categoria'] = categoria
    if tipo_negocio: p['tipo_negocio'] = tipo_negocio
    if kam: p['kam'] = kam
    return get_service().get_kpis_yoy(p)

@st.cache_data(ttl=300)
def cached_mensual():
    return get_service().get_tendencia_mensual_yoy()

@st.cache_data(ttl=300)
def cached_diaria(anio, mes):
    return get_service().get_tendencia_diaria_yoy(anio, mes)

@st.cache_data(ttl=300)
def cached_semanal(anio, mes, canal, marca, categoria, tipo_negocio, kam):
    p = {}
    if canal: p['canal'] = canal
    if marca: p['marca'] = marca
    if categoria: p['categoria'] = categoria
    if tipo_negocio: p['tipo_negocio'] = tipo_negocio
    if kam: p['kam'] = kam
    return get_service().get_tendencia_semanal_yoy(anio, mes, p)

@st.cache_data(ttl=300)
def cached_canales(desde, hasta, canal, marca, categoria, tipo_negocio, kam):
    p = {'fecha_desde': desde, 'fecha_hasta': hasta}
    if canal: p['canal'] = canal
    if marca: p['marca'] = marca
    if categoria: p['categoria'] = categoria
    if tipo_negocio: p['tipo_negocio'] = tipo_negocio
    if kam: p['kam'] = kam
    return get_service().get_por_canal_yoy(p)

@st.cache_data(ttl=300)
def cached_top_skus(desde, hasta, canal, marca, categoria, tipo_negocio, kam, limit):
    p = {'fecha_desde': desde, 'fecha_hasta': hasta}
    if canal: p['canal'] = canal
    if marca: p['marca'] = marca
    if categoria: p['categoria'] = categoria
    if tipo_negocio: p['tipo_negocio'] = tipo_negocio
    if kam: p['kam'] = kam
    return get_service().get_top_skus_yoy(p, limit=limit)

@st.cache_data(ttl=60)
def cached_health():
    return get_service().health()


# ============================ Sidebar Filtros ============================
filtros_disp = cached_filtros()

st.sidebar.title("🎛️ Filtros")
st.sidebar.caption("Aplican a todos los KPIs, gráficos y tablas")

f_categoria = st.sidebar.selectbox(
    "Categoría",
    options=["(Todas)"] + filtros_disp['categorias'],
    index=0
)
f_marca = st.sidebar.selectbox(
    "Marca",
    options=["(Todas)"] + filtros_disp['marcas'],
    index=0
)
f_tipo_negocio = st.sidebar.selectbox(
    "Línea de Negocio",
    options=["(Todas)"] + filtros_disp['tipos_negocio'],
    index=0
)
f_kam = st.sidebar.selectbox(
    "KAM",
    options=["(Todos)"] + filtros_disp.get('kams', []),
    index=0
)
f_canal = st.sidebar.selectbox(
    "Canal de Venta",
    options=["(Todos)"] + filtros_disp['canales'],
    index=0
)

# Convertir a None si "(Todos/as)"
canal = None if f_canal.startswith("(") else f_canal
marca = None if f_marca.startswith("(") else f_marca
categoria = None if f_categoria.startswith("(") else f_categoria
tipo_negocio = None if f_tipo_negocio.startswith("(") else f_tipo_negocio
kam = None if f_kam.startswith("(") else f_kam

if any([canal, marca, categoria, tipo_negocio, kam]):
    activos = []
    if canal: activos.append(f"Canal={canal}")
    if marca: activos.append(f"Marca={marca}")
    if categoria: activos.append(f"Categoría={categoria}")
    if tipo_negocio: activos.append(f"Línea Negocio={tipo_negocio}")
    if kam: activos.append(f"KAM={kam}")
    st.sidebar.info("**Activos:** " + ", ".join(activos))

st.sidebar.divider()
if st.sidebar.button("🔄 Refrescar caché", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# ============================ Header ============================
col1, col2 = st.columns([3, 1])
with col1:
    st.title("📊 Dashboard Ventas UnionX")
    st.caption("Análisis YoY (Year over Year) — Venta Bruta CON IVA, Margen calculado vs Venta Neta")

with col2:
    health = cached_health()
    estado = health.get('estado', 'desconocido')
    emoji = {'ok': '🟢', 'atrasado': '🟡', 'falla': '🔴', 'desconocido': '⚪'}.get(estado, '⚪')
    atraso = health.get('atraso_horas')
    atraso_txt = f" ({atraso}h)" if atraso else ""
    st.metric("Estado sincronización", f"{emoji} {estado.upper()}{atraso_txt}",
              delta=f"DB: {fmt_int(health.get('filas_total', 0))} filas")

# ============================ TABS ============================
tab1, tab2 = st.tabs(["📈 Vista General", "📅 Vista Semanal"])

# =========================================================================
# TAB 1 — VISTA GENERAL
# =========================================================================
with tab1:
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        hoy = datetime.now().date()
        ini_mes = hoy.replace(day=1)
        rango = st.date_input(
            "Período de análisis (TY)",
            value=(ini_mes, hoy),
            max_value=hoy,
            format="YYYY-MM-DD",
            key="rango_general",
        )
    if isinstance(rango, tuple) and len(rango) == 2:
        desde, hasta = rango
    else:
        desde = ini_mes; hasta = hoy
    desde_str = desde.strftime('%Y-%m-%d')
    hasta_str = hasta.strftime('%Y-%m-%d')

    with c2:
        st.write(""); st.write("")
        st.caption(f"Comparado vs LY: {desde.replace(year=desde.year-1)} → {hasta.replace(year=hasta.year-1)}")

    # KPIs
    try:
        kpis = cached_kpis(desde_str, hasta_str, canal, marca, categoria, tipo_negocio, kam)
    except Exception as e:
        st.error(f"Error: {e}")
        st.stop()

    ty = kpis['ty']; ly = kpis['ly']; var = kpis['var_pct']
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Venta Bruta", fmt_money(ty['venta']),
                  delta=f"{var['venta']}% vs LY ({fmt_money(ly['venta'])})" if var['venta'] is not None else None,
                  help="Con IVA — comparable contra histórico")
    with col2:
        st.metric("Margen Final", fmt_money(ty['margen']),
                  delta=f"{var['margen']}% vs LY ({fmt_money(ly['margen'])})" if var['margen'] is not None else None)
    with col3:
        st.metric("% Margen", fmt_pct(ty['pct_margen']),
                  delta=f"{var['pct_margen']:+.1f} pts vs LY" if var['pct_margen'] is not None else None,
                  help="vs Venta NETA sin IVA")
    with col4:
        st.metric("Unidades", fmt_int(ty['unidades']),
                  delta=f"{var['unidades']}% vs LY ({fmt_int(ly['unidades'])})" if var['unidades'] is not None else None)

    st.divider()

    # Mensual
    st.subheader("📈 Evolución mensual: TY vs LY")
    mensual = cached_mensual()
    df_m = pd.DataFrame(mensual)
    df_m['mes_nombre'] = pd.Categorical(df_m['mes_nombre'],
        categories=['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'],
        ordered=True)
    import plotly.graph_objects as go
    fig_m = go.Figure()
    fig_m.add_trace(go.Scatter(x=df_m['mes_nombre'], y=df_m['venta_ly'],
        name='LY', mode='lines+markers', line=dict(color='#bfbfbf', width=2),
        fill='tozeroy', fillcolor='rgba(140, 140, 140, 0.2)'))
    fig_m.add_trace(go.Scatter(x=df_m['mes_nombre'], y=df_m['venta_ty'],
        name='TY', mode='lines+markers', line=dict(color='#1890ff', width=3),
        fill='tonexty', fillcolor='rgba(24, 144, 255, 0.3)'))
    fig_m.update_layout(height=350, hovermode='x unified',
        yaxis=dict(tickformat=',.0f', title='Venta Bruta ($)'),
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
    st.plotly_chart(fig_m, use_container_width=True)

    # Diaria
    st.subheader(f"📅 Tendencia diaria — {hasta.strftime('%B %Y')} vs LY")
    diaria = cached_diaria(hasta.year, hasta.month)
    df_d = pd.DataFrame(diaria)
    if len(df_d):
        fig_d = go.Figure()
        fig_d.add_trace(go.Scatter(x=df_d['dia'], y=df_d['venta_ly'],
            name='LY', mode='lines', line=dict(color='#8c8c8c', width=2, dash='dot')))
        fig_d.add_trace(go.Scatter(x=df_d['dia'], y=df_d['venta_ty'],
            name='TY', mode='lines+markers', line=dict(color='#1890ff', width=2)))
        fig_d.update_layout(height=300, hovermode='x unified',
            xaxis=dict(title='Día del mes'),
            yaxis=dict(tickformat=',.0f', title='Venta Bruta ($)'),
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
        st.plotly_chart(fig_d, use_container_width=True)

    st.divider()

    # Por canal / Top SKUs
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Por Canal (TY vs LY)")
        df_c = pd.DataFrame(cached_canales(desde_str, hasta_str, canal, marca, categoria, tipo_negocio, kam))
        if len(df_c):
            df_c['Var Venta %'] = df_c['var_venta_pct'].apply(lambda v: f"{v:+.1f}%" if v is not None else '—')
            df_c['Venta TY'] = df_c['venta_ty'].apply(fmt_money)
            df_c['Venta LY'] = df_c['venta_ly'].apply(fmt_money)
            df_c['% Mg'] = df_c['pct_margen'].apply(lambda v: f"{v:.1f}%" if v is not None else '—')
            st.dataframe(df_c[['canal', 'Venta TY', 'Venta LY', 'Var Venta %', '% Mg']],
                hide_index=True, use_container_width=True, height=400)
    with col_b:
        st.subheader("Top 20 SKUs")
        df_s = pd.DataFrame(cached_top_skus(desde_str, hasta_str, canal, marca, categoria, tipo_negocio, kam, 20))
        if len(df_s):
            df_s['Var %'] = df_s['var_venta_pct'].apply(lambda v: f"{v:+.1f}%" if v is not None else '—')
            df_s['Venta TY'] = df_s['venta'].apply(fmt_money)
            df_s['% Mg'] = df_s['pct_margen'].apply(lambda v: f"{v}%" if v is not None else '—')
            st.dataframe(df_s[['sku', 'producto', 'Venta TY', 'Var %', '% Mg']],
                hide_index=True, use_container_width=True, height=400)

# =========================================================================
# TAB 2 — VISTA SEMANAL
# =========================================================================
with tab2:
    st.subheader("📅 Análisis semanal")
    c1, c2 = st.columns([1, 1])
    with c1:
        anio_sel = st.selectbox("Año", options=[2026, 2025, 2024], index=0, key="anio_sem")
    with c2:
        mes_sel = st.selectbox("Mes",
            options=list(range(1, 13)),
            format_func=lambda m: ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                                    'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'][m-1],
            index=datetime.now().month - 1,
            key="mes_sem")

    sem = cached_semanal(anio_sel, mes_sel, canal, marca, categoria, tipo_negocio, kam)
    df_w = pd.DataFrame(sem)

    if len(df_w):
        # KPIs totales del mes
        ty_v = df_w['venta_ty'].sum()
        ly_v = df_w['venta_ly'].sum()
        ty_m = df_w['margen_ty'].sum()
        ly_m = df_w['margen_ly'].sum()
        ty_u = df_w['unidades_ty'].sum()
        ly_u = df_w['unidades_ly'].sum()
        var_v = (ty_v - ly_v) / abs(ly_v) * 100 if ly_v else 0
        var_m = (ty_m - ly_m) / abs(ly_m) * 100 if ly_m else 0
        var_u = (ty_u - ly_u) / abs(ly_u) * 100 if ly_u else 0

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Venta Bruta del mes", fmt_money(ty_v),
                      delta=f"{var_v:+.1f}% vs LY ({fmt_money(ly_v)})")
        with c2:
            st.metric("Margen Final del mes", fmt_money(ty_m),
                      delta=f"{var_m:+.1f}% vs LY")
        with c3:
            st.metric("Unidades del mes", fmt_int(ty_u),
                      delta=f"{var_u:+.1f}% vs LY")

        st.divider()

        # Gráfico de barras semanales
        st.markdown("##### Comparativa semanal")
        import plotly.graph_objects as go
        fig_w = go.Figure()
        fig_w.add_trace(go.Bar(name='LY', x=df_w['label'], y=df_w['venta_ly'],
                               marker_color='#bfbfbf'))
        fig_w.add_trace(go.Bar(name='TY', x=df_w['label'], y=df_w['venta_ty'],
                               marker_color='#1890ff'))
        fig_w.update_layout(barmode='group', height=350, hovermode='x',
            yaxis=dict(tickformat=',.0f', title='Venta Bruta ($)'),
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
        st.plotly_chart(fig_w, use_container_width=True)

        # Tabla detalle
        st.markdown("##### Detalle por semana")
        df_view = df_w.copy()
        df_view['Semana'] = df_view['label']
        df_view['Período'] = df_view['desde'] + ' → ' + df_view['hasta']
        df_view['Venta TY'] = df_view['venta_ty'].apply(fmt_money)
        df_view['Venta LY'] = df_view['venta_ly'].apply(fmt_money)
        df_view['Var %'] = df_view['var_venta_pct'].apply(lambda v: f"{v:+.1f}%" if v is not None else '—')
        df_view['Mg TY'] = df_view['margen_ty'].apply(fmt_money)
        df_view['Unid TY'] = df_view['unidades_ty'].apply(fmt_int)
        df_view['% Mg'] = (df_view['margen_ty'] / df_view['venta_neta_ty'].replace(0, 1) * 100).round(1).astype(str) + '%'
        st.dataframe(
            df_view[['Semana', 'Período', 'Venta TY', 'Venta LY', 'Var %', 'Mg TY', 'Unid TY', '% Mg']],
            hide_index=True, use_container_width=True
        )

# =========================================================================
# Descarga RAW
# =========================================================================
st.divider()
st.subheader("⬇️ Descargar RAW (41 columnas)")
col_d1, col_d2, col_d3 = st.columns([2, 2, 1])
with col_d1:
    rango_dl = st.date_input(
        "Período a descargar",
        value=(datetime.now().date().replace(day=1), datetime.now().date()),
        max_value=datetime.now().date(),
        format="YYYY-MM-DD",
        key="rango_dl",
    )
with col_d2:
    st.write("")
    st.caption("Excel con las 40 columnas RAW + columna 'Venta Neta' (sin IVA).")
with col_d3:
    st.write("")
    if isinstance(rango_dl, tuple) and len(rango_dl) == 2:
        d1, d2 = rango_dl
        if st.button("📥 Generar y descargar", use_container_width=True, type="primary"):
            with st.spinner('Generando Excel...'):
                df_raw = get_service().descargar_raw(d1.strftime('%Y-%m-%d'), d2.strftime('%Y-%m-%d'))
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as w:
                    df_raw.to_excel(w, index=False, sheet_name='RAW')
                output.seek(0)
                st.download_button(
                    label=f"💾 {len(df_raw):,} filas — Descargar Excel",
                    data=output,
                    file_name=f"Raw_ventas_Y_{d1}_{d2}.xlsx",
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    use_container_width=True,
                )

# Footer
st.caption(
    f"DB: {fmt_int(health.get('filas_total', 0))} filas · "
    f"Rango: {health.get('fecha_min')} → {health.get('fecha_max')} · "
    f"Última carga: {health.get('ultima_carga', '—')}"
)
