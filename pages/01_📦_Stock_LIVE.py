"""
Página dedicada Stock LIVE — UI completa con KPIs cards + gauge + 5 sub-tabs.
Adaptada de eerr-finanzas/stock_dashboard.py para Streamlit Cloud (env vars).
Reutiliza StockAdvancedService para la lógica.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

# Streamlit Cloud: exponer secretos como env vars
for _key in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN', 'ANDRES_ODOO_PASSWORD'):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

from app.services.stock_advanced_service import StockAdvancedService
from app.core.odoo_client import OdooClient
from app.config import Config

st.set_page_config(page_title="Stock LIVE — UnionX", page_icon="📦", layout="wide")

# ============================================================
# AUTH GUARD: hereda sesión de la página principal
# ============================================================
if not st.session_state.get('authentication_status'):
    st.warning("Por favor ingresa al dashboard principal primero para autenticarte.")
    st.page_link("dashboard_ventas.py", label="← Volver al Dashboard Ventas", icon="🔙")
    st.stop()

# ============================================================
# CSS
# ============================================================
st.markdown("""
<style>
    .main .block-container {padding: 1.2rem 1.5rem 1rem 1.5rem; max-width: 100%;}
    .kpi-card {
        background: white; border-radius: 12px; padding: 18px 20px; text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #E2E8F0;
        transition: transform 0.15s; height: 100%;
    }
    .kpi-card:hover {transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1);}
    .kpi-label {font-size: 0.75rem; color: #64748B; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; margin-bottom: 4px;}
    .kpi-value {font-size: 1.6rem; font-weight: 700; color: #1E293B; line-height: 1.2;}
    .kpi-value.blue {color: #1F4E79;}
    .kpi-value.red {color: #DC2626;}
    .kpi-value.green {color: #16A34A;}
    .kpi-value.orange {color: #EA580C;}
    .kpi-sub {font-size: 0.72rem; color: #94A3B8; margin-top: 2px;}

    .occ-container {background: white; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #E2E8F0;}
    .occ-bar-bg {background: #E2E8F0; border-radius: 8px; height: 24px; overflow: hidden; position: relative;}
    .occ-bar-fill {height: 100%; border-radius: 8px; transition: width 0.5s;}
    .occ-label {font-size: 0.75rem; color: #64748B; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;}
    .occ-pct {font-size: 1.4rem; font-weight: 700; color: #1E293B;}

    .section-header {
        font-size: 1rem; font-weight: 700; color: #1E293B; padding: 8px 0 6px 0;
        border-bottom: 2px solid #1F4E79; margin-bottom: 12px; letter-spacing: 0.3px;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# DATA (cache 5 min — equivalente al APScheduler del modo Flask)
# ============================================================
@st.cache_data(ttl=300, show_spinner="Consultando Odoo… (puede tardar 30-60s la primera vez)")
def _stock_data():
    if not Config.ODOO_PASSWORD:
        raise RuntimeError("ANDRES_ODOO_PASSWORD no está seteado en Streamlit Cloud Secrets.")
    odoo = OdooClient(
        url=Config.ODOO_URL,
        db=Config.ODOO_DB,
        username=Config.ODOO_USER,
        password=Config.ODOO_PASSWORD,
    )
    service = StockAdvancedService(odoo)
    return service.extract_full(progress_callback=None)


# Mapping semáforo (sin emoji) → con emoji para display
SEM_DISPLAY = {
    'QUIEBRE': '🔴 QUIEBRE',
    'CRITICO': '🔴 CRITICO',
    'BAJO': '🟡 BAJO',
    'OPTIMO': '🟢 OPTIMO',
    'SOBRESTOCK': '🔵 SOBRESTOCK',
    'SIN VENTA': '⚪ SIN VENTA',
}


def kpi_card(label, value, sub="", color="blue"):
    return f"""<div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value {color}">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>"""


def occ_bar(label, occupied, total):
    pct = (occupied / total * 100) if total > 0 else 0
    color = "#16A34A" if pct < 80 else ("#EA580C" if pct < 95 else "#DC2626")
    return f"""<div class="occ-container" style="margin-bottom:8px;">
        <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px;">
            <span class="occ-label">{label}</span>
            <span class="occ-pct" style="color:{color}">{pct:.0f}%</span>
        </div>
        <div class="occ-bar-bg">
            <div class="occ-bar-fill" style="width:{min(pct,100):.0f}%; background:{color};"></div>
        </div>
        <div style="font-size:0.7rem; color:#94A3B8; margin-top:3px; text-align:right;">{occupied} / {total} posiciones</div>
    </div>"""


def color_sem(val):
    s = str(val)
    if "QUIEBRE" in s or "CRITICO" in s:
        return "background-color:#FEE2E2; color:#991B1B; font-weight:600"
    if "BAJO" in s:
        return "background-color:#FEF3C7; color:#92400E; font-weight:600"
    if "OPTIMO" in s:
        return "background-color:#D1FAE5; color:#065F46; font-weight:600"
    if "SOBRESTOCK" in s:
        return "background-color:#DBEAFE; color:#1E40AF; font-weight:600"
    return "color:#94A3B8"


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("### 📦 **Stock UnionX**")
    st.caption("Inventario en tiempo real")
    st.markdown("---")

    if st.button("🔄 Refrescar Odoo", use_container_width=True, type="primary"):
        _stock_data.clear()
        st.rerun()

    st.markdown("##### Semáforo (target 3 meses)")
    st.markdown("""
    🔴 < 30 días — Crítico
    🟡 30-89 días — Bajo
    🟢 90-180 días — Óptimo
    🔵 > 180 días — Sobrestock
    ⚪ Sin venta reciente
    """)
    st.markdown("---")


# ============================================================
# LOAD
# ============================================================
try:
    data = _stock_data()
except Exception as e:
    st.error(f"❌ Error consultando Odoo: {type(e).__name__}: {e}")
    st.stop()

df_sku = pd.DataFrame(data['skus'])
df_det = pd.DataFrame(data['detalle'])
occ = data['ocupacion']

if df_sku.empty:
    st.warning("Sin datos de stock")
    st.stop()

# Aplicar emoji al semáforo
df_sku['Semaforo'] = df_sku['Semaforo'].map(SEM_DISPLAY).fillna(df_sku['Semaforo'])
df_det['Semaforo'] = df_det.get('Semaforo', '').map(SEM_DISPLAY).fillna(df_det.get('Semaforo', '')) if 'Semaforo' in df_det.columns else None


# ============================================================
# SIDEBAR FILTERS
# ============================================================
with st.sidebar:
    st.markdown("##### Filtros")
    sku_options = sorted([s for s in df_sku['SKU'].dropna().unique() if s])
    sku_f = st.multiselect("SKU", sku_options, default=[], placeholder="Buscar SKU...", key="sku_filter")
    cat_f = st.selectbox("Categoría", ["Todas"] + sorted([c for c in df_sku['Categoria'].dropna().unique() if c]), key="cat_filter")
    marca_f = st.selectbox("Marca", ["Todas"] + sorted([m for m in df_sku['Marca'].dropna().unique() if m]), key="marca_filter")
    sem_options = sorted(df_sku['Semaforo'].dropna().unique().tolist())
    sem_f = st.selectbox("Semáforo", ["Todos"] + sem_options, key="sem_filter")
    bod_options = sorted([b for b in df_det['Bodega'].dropna().unique() if b]) if 'Bodega' in df_det.columns else []
    bod_f = st.selectbox("Bodega", ["Todas"] + bod_options, key="bod_filter")

# Apply filters
df_f = df_sku.copy()
if sku_f:
    df_f = df_f[df_f['SKU'].isin(sku_f)]
if cat_f != "Todas":
    df_f = df_f[df_f['Categoria'] == cat_f]
if marca_f != "Todas":
    df_f = df_f[df_f['Marca'] == marca_f]
if sem_f != "Todos":
    df_f = df_f[df_f['Semaforo'] == sem_f]
if bod_f != "Todas" and 'Bodega' in df_f.columns:
    df_f = df_f[df_f['Bodega'].astype(str).str.contains(bod_f, na=False)]


# ============================================================
# HEADER
# ============================================================
st.markdown("<h2 style='margin:0 0 4px 0; color:#1E293B;'>📦 Dashboard de Stock</h2>", unsafe_allow_html=True)
gen = data.get('metadata', {}).get('generado_en', datetime.now().isoformat())
try:
    gen_fmt = datetime.fromisoformat(gen).strftime('%d/%m/%Y %H:%M')
except Exception:
    gen_fmt = gen[:16]
st.markdown(f"<span style='color:#94A3B8; font-size:0.8rem;'>Generado: {gen_fmt} · Datos Odoo en tiempo real · Cache 5 min</span>", unsafe_allow_html=True)
st.markdown("")


# ============================================================
# KPIs ROW
# ============================================================
total_val = float(df_f['Valor'].sum()) if 'Valor' in df_f.columns else 0
total_qty = float(df_f['Qty'].sum()) if 'Qty' in df_f.columns else 0
n_skus = len(df_f)
n_quiebre = len(df_f[df_f['Semaforo'].str.contains('QUIEBRE|CRITICO', na=False)])
n_bajo = len(df_f[df_f['Semaforo'].str.contains('BAJO', na=False)])
n_optimo = len(df_f[df_f['Semaforo'].str.contains('OPTIMO', na=False)])
n_sobre = len(df_f[df_f['Semaforo'].str.contains('SOBRESTOCK', na=False)])
n_sinventa = len(df_f[df_f['Semaforo'].str.contains('SIN VENTA', na=False)])
rot_30d_avg = df_f[df_f['Rot 30d Uds'] > 0]['Rot 30d Uds'].mean() if 'Rot 30d Uds' in df_f.columns and len(df_f[df_f['Rot 30d Uds'] > 0]) > 0 else 0
rot_90d_avg = df_f[df_f['Rot 90d Uds'] > 0]['Rot 90d Uds'].mean() if 'Rot 90d Uds' in df_f.columns and len(df_f[df_f['Rot 90d Uds'] > 0]) > 0 else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    st.markdown(kpi_card("Valor Inventario", f"${total_val:,.0f}", f"{n_skus:,} SKUs activos", "blue"), unsafe_allow_html=True)
with c2:
    st.markdown(kpi_card("Unidades", f"{total_qty:,.0f}", f"Costo prom ${total_val/n_skus:,.0f}/SKU" if n_skus else "", "blue"), unsafe_allow_html=True)
with c3:
    st.markdown(kpi_card("Críticos / Quiebre", str(n_quiebre), "< 30 días de stock", "red"), unsafe_allow_html=True)
with c4:
    st.markdown(kpi_card("Bajo Stock", str(n_bajo), "30-89 días, reponer", "orange"), unsafe_allow_html=True)
with c5:
    st.markdown(kpi_card("Óptimo", str(n_optimo), "90-180 días", "green"), unsafe_allow_html=True)
with c6:
    st.markdown(kpi_card("Sobrestock", str(n_sobre), f"> 180 días · {n_sinventa} sin venta", "blue"), unsafe_allow_html=True)

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)


# ============================================================
# ROW 2: OCUPACION + SEMAFORO + VALOR POR BODEGA
# ============================================================
col_occ, col_sem, col_bod = st.columns([1, 1, 1.5])

with col_occ:
    st.markdown('<div class="section-header">🏭 Ocupación CA1/Stock</div>', unsafe_allow_html=True)
    st.markdown(occ_bar("CA1/Stock", occ.get('occupied', 0), occ.get('total', 0)), unsafe_allow_html=True)
    st.markdown(f"""<div style="display:flex; gap:12px; margin-top:10px;">
        <div style="flex:1; text-align:center; background:#D1FAE5; border-radius:8px; padding:12px;">
            <div style="font-size:1.6rem; font-weight:700; color:#065F46;">{occ.get('occupied', 0)}</div>
            <div style="font-size:0.75rem; color:#065F46;">Ocupadas</div>
        </div>
        <div style="flex:1; text-align:center; background:#FEE2E2; border-radius:8px; padding:12px;">
            <div style="font-size:1.6rem; font-weight:700; color:#991B1B;">{occ.get('empty', 0)}</div>
            <div style="font-size:0.75rem; color:#991B1B;">Vacías</div>
        </div>
        <div style="flex:1; text-align:center; background:#DBEAFE; border-radius:8px; padding:12px;">
            <div style="font-size:1.6rem; font-weight:700; color:#1E40AF;">{occ.get('total', 0)}</div>
            <div style="font-size:0.75rem; color:#1E40AF;">Total</div>
        </div>
    </div>""", unsafe_allow_html=True)

with col_sem:
    st.markdown('<div class="section-header">🚦 Distribución Semáforo</div>', unsafe_allow_html=True)
    sem_data = df_f['Semaforo'].value_counts().reset_index()
    sem_data.columns = ['Semaforo', 'SKUs']
    cmap = {
        '🔴 QUIEBRE': '#EF4444', '🔴 CRITICO': '#F87171', '🟡 BAJO': '#F59E0B',
        '🟢 OPTIMO': '#10B981', '🔵 SOBRESTOCK': '#3B82F6', '⚪ SIN VENTA': '#CBD5E1',
    }
    fig = px.pie(sem_data, names='Semaforo', values='SKUs', color='Semaforo',
                 color_discrete_map=cmap, hole=0.45)
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320,
                      legend=dict(orientation='h', yanchor='top', y=-0.05, font=dict(size=10)),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    fig.update_traces(textinfo='percent+value', textfont_size=11)
    st.plotly_chart(fig, use_container_width=True)

with col_bod:
    st.markdown('<div class="section-header">💰 Valor por Bodega</div>', unsafe_allow_html=True)
    if 'Bodega' in df_det.columns and 'Valor' in df_det.columns:
        df_bod = df_det.groupby('Bodega').agg({'Valor': 'sum'}).reset_index()
        df_bod = df_bod.sort_values('Valor', ascending=True).tail(12)
        fig_b = go.Figure(go.Bar(
            y=df_bod['Bodega'], x=df_bod['Valor'], orientation='h',
            marker_color='#1F4E79', text=df_bod['Valor'].apply(lambda x: f"${x/1e6:.1f}M"),
            textposition='outside', textfont=dict(size=10),
        ))
        fig_b.update_layout(margin=dict(t=10, b=10, l=10, r=60), height=320,
                            xaxis=dict(showgrid=True, gridcolor='#F1F5F9', title=''),
                            yaxis=dict(title=''), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_b, use_container_width=True)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


# ============================================================
# TABS
# ============================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Stock Total", "🏭 Por Bodega", "📍 Ocupación Detalle", "🚨 Alertas", "📈 Top Rotación",
])

with tab1:
    st.markdown('<div class="section-header">Stock Total Empresa</div>', unsafe_allow_html=True)
    cols = [c for c in [
        'SKU', 'Producto', 'Categoria', 'Marca', 'Qty', 'Reservada', 'Disponible',
        'Costo Unit', 'Valor', 'Vta 30d Qty', 'Vta 90d Qty', 'Dias Stock',
        'Rot 30d Uds', 'Rot 90d Uds', 'Rot 30d $', 'Rot 90d $', 'Semaforo',
    ] if c in df_f.columns]
    dfd = df_f[cols].sort_values('Valor', ascending=False) if 'Valor' in df_f.columns else df_f[cols]
    st.dataframe(
        dfd.style.map(color_sem, subset=['Semaforo']).format({
            'Qty': '{:,.0f}', 'Reservada': '{:,.0f}', 'Disponible': '{:,.0f}',
            'Costo Unit': '${:,.0f}', 'Valor': '${:,.0f}',
            'Vta 30d Qty': '{:,.0f}', 'Vta 90d Qty': '{:,.0f}',
            'Dias Stock': '{:,.0f}',
            'Rot 30d Uds': '{:.2f}x', 'Rot 90d Uds': '{:.2f}x',
            'Rot 30d $': '{:.2f}x', 'Rot 90d $': '{:.2f}x',
        }),
        height=550, use_container_width=True, hide_index=True,
    )
    st.caption(f"{len(dfd):,} SKUs · Valor: ${dfd['Valor'].sum() if 'Valor' in dfd.columns else 0:,.0f} · Rot prom 30d: {rot_30d_avg:.2f}x · Rot prom 90d: {rot_90d_avg:.2f}x")

with tab2:
    st.markdown('<div class="section-header">Detalle por Bodega y Ubicación</div>', unsafe_allow_html=True)
    df_d2 = df_det.copy()
    if sku_f and 'SKU' in df_d2.columns:
        df_d2 = df_d2[df_d2['SKU'].isin(sku_f)]
    if cat_f != "Todas" and 'Categoria' in df_d2.columns:
        df_d2 = df_d2[df_d2['Categoria'] == cat_f]
    if bod_f != "Todas" and 'Bodega' in df_d2.columns:
        df_d2 = df_d2[df_d2['Bodega'].astype(str).str.contains(bod_f, na=False)]
    cols2 = [c for c in ['Bodega', 'Ubicacion', 'Tipo', 'SKU', 'Producto', 'Categoria',
                          'Qty', 'Reservada', 'Disponible', 'Costo Unit', 'Valor'] if c in df_d2.columns]
    if 'Valor' in df_d2.columns:
        df_d2_sorted = df_d2[cols2].sort_values(['Bodega', 'Valor'], ascending=[True, False])
    else:
        df_d2_sorted = df_d2[cols2]
    st.dataframe(
        df_d2_sorted.style.format({
            'Qty': '{:,.0f}', 'Reservada': '{:,.0f}', 'Disponible': '{:,.0f}',
            'Costo Unit': '${:,.0f}', 'Valor': '${:,.0f}',
        }),
        height=550, use_container_width=True, hide_index=True,
    )
    st.caption(f"{len(df_d2):,} líneas")

with tab3:
    st.markdown('<div class="section-header">📍 Posiciones CA1/Stock — Detalle de ocupación</div>', unsafe_allow_html=True)

    c_k1, c_k2, c_k3, c_k4 = st.columns(4)
    with c_k1:
        st.markdown(kpi_card("Total Posiciones", str(occ.get('total', 0)), "CA1/Stock", "blue"), unsafe_allow_html=True)
    with c_k2:
        st.markdown(kpi_card("Ocupadas", str(occ.get('occupied', 0)), f"{occ.get('pct', 0)}%", "green"), unsafe_allow_html=True)
    with c_k3:
        st.markdown(kpi_card("Vacías", str(occ.get('empty', 0)), f"{100 - occ.get('pct', 0)}%", "red"), unsafe_allow_html=True)
    with c_k4:
        st.markdown(kpi_card("% Ocupación", f"{occ.get('pct', 0)}%", "Target: <85%", "blue"), unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    c_o1, c_o2 = st.columns([1, 2])

    with c_o1:
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=occ.get('pct', 0),
            number={"suffix": "%", "font": {"size": 40}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1},
                "bar": {"color": "#1F4E79"},
                "steps": [
                    {"range": [0, 70], "color": "#D1FAE5"},
                    {"range": [70, 85], "color": "#FEF3C7"},
                    {"range": [85, 100], "color": "#FEE2E2"},
                ],
                "threshold": {"line": {"color": "#EF4444", "width": 3}, "thickness": 0.8, "value": 85},
            },
            title={"text": "Tasa de Ocupación", "font": {"size": 14}},
        ))
        fig_gauge.update_layout(height=280, margin=dict(t=40, b=20, l=30, r=30),
                                paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_gauge, use_container_width=True)

    with c_o2:
        if occ.get('positions'):
            df_pos = pd.DataFrame(occ['positions']).sort_values('Posicion')

            def color_estado(val):
                if val == "Ocupada":
                    return "background-color:#D1FAE5; color:#065F46; font-weight:600"
                return "background-color:#FEE2E2; color:#991B1B; font-weight:600"

            estado_f = st.radio("Filtrar:", ["Todas", "Ocupadas", "Vacías"], horizontal=True, key="occ_filter")
            if estado_f == "Ocupadas":
                df_pos = df_pos[df_pos['Estado'] == 'Ocupada']
            elif estado_f == "Vacías":
                df_pos = df_pos[df_pos['Estado'] == 'Vacia']

            cols_pos = [c for c in ['Posicion', 'Estado', 'SKUs'] if c in df_pos.columns]
            st.dataframe(
                df_pos[cols_pos].style.map(color_estado, subset=['Estado']),
                height=400, use_container_width=True, hide_index=True,
            )
            st.caption(f"Mostrando {len(df_pos)} de {occ.get('total', 0)} posiciones")

with tab4:
    st.markdown('<div class="section-header">🚨 Alertas de Stock</div>', unsafe_allow_html=True)

    c_a1, c_a2 = st.columns(2)
    with c_a1:
        st.markdown("**🔴 Críticos / Quiebre** — necesitan atención inmediata")
        df_al = df_f[df_f['Semaforo'].str.contains('QUIEBRE|CRITICO', na=False)].sort_values('Vta 30d Qty', ascending=False) if 'Vta 30d Qty' in df_f.columns else df_f[df_f['Semaforo'].str.contains('QUIEBRE|CRITICO', na=False)]
        if len(df_al) > 0:
            cols_al = [c for c in ['SKU', 'Producto', 'Qty', 'Vta 30d Qty', 'Dias Stock', 'Valor'] if c in df_al.columns]
            st.dataframe(
                df_al[cols_al].style.format({
                    'Qty': '{:,.0f}', 'Vta 30d Qty': '{:,.0f}', 'Valor': '${:,.0f}',
                }),
                height=380, use_container_width=True, hide_index=True,
            )
            st.error(f"{len(df_al)} SKUs en riesgo")
        else:
            st.success("Sin críticos")

    with c_a2:
        st.markdown("**🔵 Sobrestock** — capital inmovilizado")
        df_so = df_f[df_f['Semaforo'].str.contains('SOBRESTOCK', na=False)].sort_values('Valor', ascending=False) if 'Valor' in df_f.columns else df_f[df_f['Semaforo'].str.contains('SOBRESTOCK', na=False)]
        if len(df_so) > 0:
            cols_so = [c for c in ['SKU', 'Producto', 'Qty', 'Vta 30d Qty', 'Dias Stock', 'Valor'] if c in df_so.columns]
            st.dataframe(
                df_so[cols_so].style.format({
                    'Qty': '{:,.0f}', 'Vta 30d Qty': '{:,.0f}', 'Valor': '${:,.0f}',
                }),
                height=380, use_container_width=True, hide_index=True,
            )
            st.warning(f"{len(df_so)} SKUs · ${df_so['Valor'].sum() if 'Valor' in df_so.columns else 0:,.0f} inmovilizado")
        else:
            st.success("Sin sobrestock")

    st.markdown("**🟡 Bajo Stock** — reponer para llegar a 90 días")
    df_bj = df_f[df_f['Semaforo'].str.contains('BAJO', na=False)].sort_values('Dias Stock') if 'Dias Stock' in df_f.columns else df_f[df_f['Semaforo'].str.contains('BAJO', na=False)]
    if len(df_bj) > 0:
        cols_bj = [c for c in ['SKU', 'Producto', 'Categoria', 'Qty', 'Vta 30d Qty', 'Dias Stock', 'Valor'] if c in df_bj.columns]
        st.dataframe(
            df_bj[cols_bj].style.format({
                'Qty': '{:,.0f}', 'Vta 30d Qty': '{:,.0f}', 'Valor': '${:,.0f}',
            }),
            height=320, use_container_width=True, hide_index=True,
        )
        st.info(f"{len(df_bj)} SKUs bajo stock")

with tab5:
    st.markdown('<div class="section-header">📈 Rotación de Inventario</div>', unsafe_allow_html=True)
    st.markdown("""
    > **Rotación** = Venta del período / Stock actual. Si Rot = 1.0x, el inventario rota 1 vez en el período.
    > Rot > 1 = alta rotación. Rot < 0.3 = baja rotación (stock lento).
    """)

    rot_tab1, rot_tab2 = st.tabs(["📊 Rotación 30 días", "📊 Rotación 90 días"])

    cmap_r = {
        '🔴 QUIEBRE': '#EF4444', '🔴 CRITICO': '#F87171', '🟡 BAJO': '#F59E0B',
        '🟢 OPTIMO': '#10B981', '🔵 SOBRESTOCK': '#3B82F6', '⚪ SIN VENTA': '#CBD5E1',
    }

    with rot_tab1:
        if 'Rot 30d Uds' in df_f.columns and 'Vta 30d Qty' in df_f.columns:
            df_rot30 = df_f[df_f['Vta 30d Qty'] > 0].sort_values('Rot 30d Uds', ascending=False).head(25)
            if len(df_rot30) > 0:
                df_chart = df_rot30.head(20).copy()
                df_chart['Label'] = df_chart.apply(
                    lambda r: (str(r['SKU'])[:15] if r.get('SKU') and not str(r['SKU']).isdigit() else str(r.get('Producto', ''))[:25]),
                    axis=1,
                )
                fig_r30 = px.bar(df_chart, x='Label', y='Rot 30d Uds', color='Semaforo',
                                 color_discrete_map=cmap_r, text='Rot 30d Uds',
                                 labels={'Label': 'Producto', 'Rot 30d Uds': 'Rotación 30d (veces)'})
                fig_r30.update_layout(xaxis_tickangle=-45, height=420, margin=dict(t=20, b=120),
                                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                      xaxis=dict(showgrid=False, type='category'),
                                      yaxis=dict(showgrid=True, gridcolor='#F1F5F9'))
                fig_r30.update_traces(texttemplate='%{text:.1f}x', textposition='outside', textfont_size=9)
                st.plotly_chart(fig_r30, use_container_width=True)

                cols_r30 = [c for c in ['SKU', 'Producto', 'Categoria', 'Qty', 'Vta 30d Qty', 'Rot 30d Uds',
                                         'Costo Vta 30d', 'Valor', 'Rot 30d $', 'Dias Stock', 'Semaforo'] if c in df_rot30.columns]
                st.dataframe(
                    df_rot30[cols_r30].style.map(color_sem, subset=['Semaforo']).format({
                        'Qty': '{:,.0f}', 'Vta 30d Qty': '{:,.0f}', 'Rot 30d Uds': '{:.2f}x',
                        'Costo Vta 30d': '${:,.0f}', 'Valor': '${:,.0f}', 'Rot 30d $': '{:.2f}x',
                        'Dias Stock': '{:,.0f}',
                    }),
                    height=400, use_container_width=True, hide_index=True,
                )

    with rot_tab2:
        if 'Rot 90d Uds' in df_f.columns and 'Vta 90d Qty' in df_f.columns:
            df_rot90 = df_f[df_f['Vta 90d Qty'] > 0].sort_values('Rot 90d Uds', ascending=False).head(25)
            if len(df_rot90) > 0:
                df_chart90 = df_rot90.head(20).copy()
                df_chart90['Label'] = df_chart90.apply(
                    lambda r: (str(r['SKU'])[:15] if r.get('SKU') and not str(r['SKU']).isdigit() else str(r.get('Producto', ''))[:25]),
                    axis=1,
                )
                fig_r90 = px.bar(df_chart90, x='Label', y='Rot 90d Uds', color='Semaforo',
                                 color_discrete_map=cmap_r, text='Rot 90d Uds',
                                 labels={'Label': 'Producto', 'Rot 90d Uds': 'Rotación 90d (veces)'})
                fig_r90.update_layout(xaxis_tickangle=-45, height=420, margin=dict(t=20, b=120),
                                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                      xaxis=dict(showgrid=False, type='category'),
                                      yaxis=dict(showgrid=True, gridcolor='#F1F5F9'))
                fig_r90.update_traces(texttemplate='%{text:.1f}x', textposition='outside', textfont_size=9)
                st.plotly_chart(fig_r90, use_container_width=True)

                cols_r90 = [c for c in ['SKU', 'Producto', 'Categoria', 'Qty', 'Vta 90d Qty', 'Rot 90d Uds',
                                         'Costo Vta 90d', 'Valor', 'Rot 90d $', 'Dias Stock', 'Semaforo'] if c in df_rot90.columns]
                st.dataframe(
                    df_rot90[cols_r90].style.map(color_sem, subset=['Semaforo']).format({
                        'Qty': '{:,.0f}', 'Vta 90d Qty': '{:,.0f}', 'Rot 90d Uds': '{:.2f}x',
                        'Costo Vta 90d': '${:,.0f}', 'Valor': '${:,.0f}', 'Rot 90d $': '{:.2f}x',
                        'Dias Stock': '{:,.0f}',
                    }),
                    height=400, use_container_width=True, hide_index=True,
                )

# Footer
st.markdown("---")
total_locs = data.get('metadata', {}).get('total_locations', 0)
st.caption(f"Stock UnionX · {datetime.now().strftime('%d/%m/%Y %H:%M')} · Odoo {total_locs} ubicaciones · Cache 5 min")
