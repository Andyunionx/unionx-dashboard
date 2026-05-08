"""
Página de análisis cruzado Stock × Ventas.
- Bestsellers + estado de stock
- Quiebres con demanda activa (alerta crítica)
- Sobrestock con baja venta (capital inmovilizado)
- Cobertura proyectada por canal
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))

for _key in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN', 'ANDRES_ODOO_PASSWORD'):
    if _key in st.secrets and not os.environ.get(_key):
        os.environ[_key] = str(st.secrets[_key])

from app.services.stock_advanced_service import StockAdvancedService
from app.core.odoo_client import OdooClient
from app.config import Config

import requests

st.set_page_config(page_title="Cruce Stock-Ventas — UnionX", page_icon="🔄", layout="wide")

# ==== Auth guard ====
if not st.session_state.get('authentication_status'):
    st.warning("Por favor ingresa al dashboard principal primero para autenticarte.")
    st.page_link("dashboard_ventas.py", label="← Volver al Dashboard Ventas", icon="🔙")
    st.stop()


# ==== Data loaders ====
@st.cache_data(ttl=300, show_spinner="Consultando Odoo (puede tomar 30-60s)…")
def _stock_data():
    if not Config.ODOO_PASSWORD:
        raise RuntimeError("ANDRES_ODOO_PASSWORD no está seteado en Streamlit Cloud Secrets.")
    odoo = OdooClient(
        url=Config.ODOO_URL,
        db=Config.ODOO_DB,
        username=Config.ODOO_USER,
        password=Config.ODOO_PASSWORD,
    )
    return StockAdvancedService(odoo).extract_full(progress_callback=None)


@st.cache_data(ttl=300, show_spinner="Consultando ventas por canal desde Turso…")
def _ventas_por_canal_30d():
    """Ventas últimos 30 días agregadas por SKU y canal desde Turso."""
    url = os.environ.get('LIBSQL_URL', '').rstrip('/')
    token = os.environ.get('LIBSQL_AUTH_TOKEN', '')
    if not url:
        return pd.DataFrame()

    desde = (datetime.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
    sql = f"""
        SELECT sku, canal, tipo_negocio,
               ROUND(SUM(cantidad), 0) as cantidad,
               ROUND(SUM(venta_bruta), 0) as venta
        FROM ventas
        WHERE fecha_venta >= '{desde}' AND tipo_movimiento = 'Venta'
        GROUP BY sku, canal, tipo_negocio
    """
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    r = requests.post(
        f"{url}/v2/pipeline",
        json=body,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        timeout=300,
    )
    r.raise_for_status()
    rows = r.json()['results'][0]['response']['result']['rows']
    if not rows:
        return pd.DataFrame()
    data = []
    for row in rows:
        data.append({
            'SKU': row[0]['value'],
            'Canal': row[1]['value'],
            'Tipo Negocio': row[2]['value'],
            'Cantidad': float(row[3]['value']) if row[3]['value'] else 0,
            'Venta': float(row[4]['value']) if row[4]['value'] else 0,
        })
    return pd.DataFrame(data)


SEM_DISPLAY = {
    'QUIEBRE': '🔴 QUIEBRE',
    'CRITICO': '🔴 CRITICO',
    'BAJO': '🟡 BAJO',
    'OPTIMO': '🟢 OPTIMO',
    'SOBRESTOCK': '🔵 SOBRESTOCK',
    'SIN VENTA': '⚪ SIN VENTA',
}


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


# ==== Header ====
st.markdown("# 🔄 Cruce Stock × Ventas")
st.caption("Análisis cruzado de inventario y demanda. Cache 5 min.")

with st.sidebar:
    st.markdown("### 🔄 **Cruce S×V**")
    st.caption("Stock × Demanda")
    st.markdown("---")
    if st.button("🔄 Refrescar todo", use_container_width=True, type="primary"):
        _stock_data.clear()
        _ventas_por_canal_30d.clear()
        st.rerun()

# ==== Load data ====
try:
    stock = _stock_data()
except Exception as e:
    st.error(f"❌ Error consultando Odoo: {type(e).__name__}: {e}")
    st.stop()

df_sku = pd.DataFrame(stock['skus'])
if df_sku.empty:
    st.warning("Sin datos de stock")
    st.stop()

# Aplicar emoji al semáforo
df_sku['Semaforo_emoji'] = df_sku['Semaforo'].map(SEM_DISPLAY).fillna(df_sku['Semaforo'])


# ==== Tabs ====
tab1, tab2, tab3, tab4 = st.tabs([
    "🔥 Bestsellers + Stock",
    "🚨 Quiebres con Demanda",
    "💰 Sobrestock con Baja Venta",
    "📊 Cobertura por Canal",
])


# ============================================================
# TAB 1: BESTSELLERS
# ============================================================
with tab1:
    st.markdown("### 🔥 Top 30 SKUs por Venta últimos 90 días")
    st.caption("Cruce con su stock actual y estado de cobertura")

    horizonte = st.radio("Horizonte de venta:", ["30 días", "90 días"], horizontal=True, key="bs_horiz")
    col_venta = 'Vta 30d $' if horizonte == "30 días" else 'Vta 90d $'
    col_qty = 'Vta 30d Qty' if horizonte == "30 días" else 'Vta 90d Qty'

    df_top = df_sku[df_sku[col_venta] > 0].sort_values(col_venta, ascending=False).head(30).copy()

    # Métrica resumen
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SKUs en top", len(df_top))
    c2.metric(f"Venta total {horizonte}", f"${df_top[col_venta].sum()/1e6:,.1f}M")
    c3.metric("Stock unidades", f"{df_top['Qty'].sum():,.0f}")
    c4.metric("Stock valor", f"${df_top['Valor'].sum()/1e6:,.1f}M")

    st.divider()

    # KPI semáforo de los top
    n_quiebre = (df_top['Semaforo'].str.contains('QUIEBRE|CRITICO', na=False)).sum()
    n_bajo = (df_top['Semaforo'] == 'BAJO').sum()
    n_optimo = (df_top['Semaforo'] == 'OPTIMO').sum()
    n_sobre = (df_top['Semaforo'] == 'SOBRESTOCK').sum()

    if n_quiebre > 0:
        st.error(f"⚠️ {n_quiebre} de los top 30 bestsellers están en **CRÍTICO/QUIEBRE** — riesgo alto de venta perdida")
    if n_bajo > 0:
        st.warning(f"⚠️ {n_bajo} bestsellers con stock BAJO (30-89 días) — programar reposición")
    if n_quiebre == 0 and n_bajo == 0:
        st.success("✅ Todos los bestsellers tienen stock saludable")

    st.divider()

    # Tabla
    cols = ['SKU', 'Producto', 'Categoria', 'Marca', col_qty, col_venta,
            'Qty', 'Valor', 'Dias Stock', 'Rot 30d Uds', 'Semaforo_emoji']
    cols = [c for c in cols if c in df_top.columns]
    df_show = df_top[cols].rename(columns={'Semaforo_emoji': 'Semáforo'})
    st.dataframe(
        df_show.style.map(color_sem, subset=['Semáforo']).format({
            col_qty: '{:,.0f}', col_venta: '${:,.0f}',
            'Qty': '{:,.0f}', 'Valor': '${:,.0f}',
            'Dias Stock': '{:,.0f}', 'Rot 30d Uds': '{:.2f}x',
        }),
        height=550, use_container_width=True, hide_index=True,
    )


# ============================================================
# TAB 2: QUIEBRES CON DEMANDA
# ============================================================
with tab2:
    st.markdown("### 🚨 Quiebres / Críticos con Demanda Activa")
    st.caption("SKUs sin stock o con < 30 días, pero que vendieron en últimos 30 días. **Acción: priorizar reposición.**")

    df_q = df_sku[
        df_sku['Semaforo'].str.contains('QUIEBRE|CRITICO', na=False)
        & (df_sku['Vta 30d Qty'] > 0)
    ].copy()

    if df_q.empty:
        st.success("✅ No hay SKUs en quiebre con demanda activa")
    else:
        # Estimación venta perdida = días faltantes × venta diaria × precio promedio
        df_q['Vta Diaria'] = df_q['Vta 30d Qty'] / 30
        df_q['Precio Prom'] = df_q['Vta 30d $'] / df_q['Vta 30d Qty'].replace(0, 1)
        # Asumiendo que tomará 30 días reponer, estimación de venta perdida
        df_q['Riesgo Venta 30d $'] = (df_q['Vta Diaria'] * 30 * df_q['Precio Prom']).round(0)

        c1, c2, c3 = st.columns(3)
        c1.metric("SKUs en riesgo", len(df_q))
        c2.metric("Venta últimos 30d", f"${df_q['Vta 30d $'].sum()/1e6:,.1f}M")
        c3.metric("Venta en riesgo (próximos 30d)", f"${df_q['Riesgo Venta 30d $'].sum()/1e6:,.1f}M",
                  help="Estimación: días sin reposición × venta diaria × precio promedio")

        st.divider()

        df_q = df_q.sort_values('Riesgo Venta 30d $', ascending=False)
        cols = ['SKU', 'Producto', 'Categoria', 'Marca', 'Qty', 'Vta 30d Qty',
                'Vta 30d $', 'Precio Prom', 'Riesgo Venta 30d $', 'Dias Stock', 'Semaforo_emoji']
        cols = [c for c in cols if c in df_q.columns]
        df_show = df_q[cols].rename(columns={'Semaforo_emoji': 'Semáforo'})
        st.dataframe(
            df_show.style.map(color_sem, subset=['Semáforo']).format({
                'Qty': '{:,.0f}', 'Vta 30d Qty': '{:,.0f}',
                'Vta 30d $': '${:,.0f}', 'Precio Prom': '${:,.0f}',
                'Riesgo Venta 30d $': '${:,.0f}', 'Dias Stock': '{:,.0f}',
            }),
            height=550, use_container_width=True, hide_index=True,
        )

        # Bar chart top riesgos
        st.markdown("#### Top 15 mayor riesgo de venta perdida")
        df_chart = df_q.head(15).copy()
        df_chart['Label'] = df_chart.apply(
            lambda r: (str(r['SKU'])[:20] if r.get('SKU') else str(r.get('Producto', ''))[:25]),
            axis=1,
        )
        fig = px.bar(df_chart, x='Label', y='Riesgo Venta 30d $',
                     color='Marca', text='Riesgo Venta 30d $',
                     labels={'Label': 'SKU', 'Riesgo Venta 30d $': 'Riesgo $'})
        fig.update_layout(xaxis_tickangle=-45, height=400, margin=dict(t=20, b=120),
                          paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside', textfont_size=9)
        st.plotly_chart(fig, use_container_width=True)


# ============================================================
# TAB 3: SOBRESTOCK CON BAJA VENTA
# ============================================================
with tab3:
    st.markdown("### 💰 Sobrestock con Baja o Cero Venta")
    st.caption("Capital inmovilizado: SKUs con stock alto y venta lenta o nula. **Acción: liquidación, promo, devolución.**")

    df_so = df_sku[df_sku['Semaforo'].str.contains('SOBRESTOCK|SIN VENTA', na=False)].copy()

    if df_so.empty:
        st.success("✅ No hay SKUs con sobrestock")
    else:
        # Métricas resumen
        n_total = len(df_so)
        n_sin_venta = (df_so['Semaforo'] == 'SIN VENTA').sum()
        valor_total = df_so['Valor'].sum()
        valor_sin_venta = df_so[df_so['Semaforo'] == 'SIN VENTA']['Valor'].sum()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("SKUs sobrestock/sin venta", n_total)
        c2.metric("De los cuales sin venta 30d", n_sin_venta)
        c3.metric("Capital inmovilizado total", f"${valor_total/1e6:,.1f}M")
        c4.metric("De los cuales sin venta", f"${valor_sin_venta/1e6:,.1f}M")

        st.divider()

        # Por categoría
        st.markdown("#### Capital inmovilizado por Categoría")
        df_cat = df_so.groupby('Categoria').agg({'Valor': 'sum', 'Qty': 'sum', 'SKU': 'count'}).reset_index()
        df_cat = df_cat.rename(columns={'SKU': 'N° SKUs'}).sort_values('Valor', ascending=False).head(15)

        fig_cat = px.bar(df_cat, x='Categoria', y='Valor', text='Valor',
                         labels={'Valor': 'Capital inmovilizado $'})
        fig_cat.update_layout(xaxis_tickangle=-45, height=400, margin=dict(t=20, b=80),
                              paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        fig_cat.update_traces(texttemplate='$%{text:,.0f}', textposition='outside', textfont_size=9,
                              marker_color='#3B82F6')
        st.plotly_chart(fig_cat, use_container_width=True)

        st.divider()

        # Por marca
        st.markdown("#### Capital inmovilizado por Marca")
        df_marca = df_so.groupby('Marca').agg({'Valor': 'sum', 'Qty': 'sum', 'SKU': 'count'}).reset_index()
        df_marca = df_marca.rename(columns={'SKU': 'N° SKUs'}).sort_values('Valor', ascending=False).head(15)
        st.dataframe(df_marca.style.format({'Valor': '${:,.0f}', 'Qty': '{:,.0f}'}),
                     use_container_width=True, hide_index=True)

        st.divider()

        # Tabla detalle
        st.markdown("#### Detalle de SKUs (ordenados por valor inmovilizado)")
        df_so = df_so.sort_values('Valor', ascending=False)
        cols = ['SKU', 'Producto', 'Categoria', 'Marca', 'Qty', 'Valor',
                'Vta 30d Qty', 'Vta 90d Qty', 'Dias Stock', 'Semaforo_emoji']
        cols = [c for c in cols if c in df_so.columns]
        df_show = df_so[cols].rename(columns={'Semaforo_emoji': 'Semáforo'})
        st.dataframe(
            df_show.style.map(color_sem, subset=['Semáforo']).format({
                'Qty': '{:,.0f}', 'Valor': '${:,.0f}',
                'Vta 30d Qty': '{:,.0f}', 'Vta 90d Qty': '{:,.0f}',
                'Dias Stock': '{:,.0f}',
            }),
            height=500, use_container_width=True, hide_index=True,
        )


# ============================================================
# TAB 4: COBERTURA POR CANAL
# ============================================================
with tab4:
    st.markdown("### 📊 Cobertura de Stock por Canal")
    st.caption("Cuánto stock soporta la venta de cada canal en los próximos 30 días")

    # Cargar ventas por canal desde Turso
    df_v_canal = _ventas_por_canal_30d()

    if df_v_canal.empty:
        st.warning("Sin ventas en últimos 30 días o error consultando Turso")
    else:
        # Resumen por canal
        st.markdown("#### Top 15 canales por venta últimos 30 días")
        df_canal_total = df_v_canal.groupby('Canal').agg({
            'Cantidad': 'sum',
            'Venta': 'sum',
            'SKU': 'nunique',
        }).reset_index().rename(columns={'SKU': 'SKUs distintos'})
        df_canal_total = df_canal_total.sort_values('Venta', ascending=False).head(15)

        fig_can = px.bar(df_canal_total, x='Canal', y='Venta', text='Venta',
                         labels={'Venta': 'Venta últimos 30d'},
                         color='Venta', color_continuous_scale='Blues')
        fig_can.update_layout(xaxis_tickangle=-45, height=400, margin=dict(t=20, b=100),
                              paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                              showlegend=False)
        fig_can.update_traces(texttemplate='$%{text:,.0f}', textposition='outside', textfont_size=9)
        st.plotly_chart(fig_can, use_container_width=True)

        st.divider()

        # Selector de canal para ver detalle
        canal_sel = st.selectbox(
            "Ver detalle de un canal específico:",
            options=['Todos'] + df_canal_total['Canal'].tolist(),
            key='cruce_canal_sel',
        )

        if canal_sel != 'Todos':
            df_v_filt = df_v_canal[df_v_canal['Canal'] == canal_sel].copy()
        else:
            df_v_filt = df_v_canal.copy()

        # Join con stock
        df_join = df_v_filt.merge(
            df_sku[['SKU', 'Producto', 'Marca', 'Qty', 'Valor', 'Vta 30d Qty', 'Dias Stock', 'Semaforo_emoji']],
            on='SKU', how='left',
        )

        # Stock proporcional (este canal vs venta total del SKU)
        df_join['% Venta este canal'] = (df_join['Cantidad'] / df_join['Vta 30d Qty'].replace(0, 1) * 100).round(1)

        # Cobertura proyectada (si solo viniera de este canal, cuántos días duraría stock)
        df_join['Cobertura este canal (días)'] = (df_join['Qty'] / (df_join['Cantidad'] / 30).replace(0, 1)).round(0)

        # KPIs canal
        venta_canal = df_v_filt['Venta'].sum()
        skus_canal = df_v_filt['SKU'].nunique()
        stock_total_skus = df_join['Qty'].sum() if 'Qty' in df_join.columns else 0
        valor_total_skus = df_join['Valor'].sum() if 'Valor' in df_join.columns else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Venta 30d", f"${venta_canal/1e6:,.1f}M")
        c2.metric("SKUs vendidos", skus_canal)
        c3.metric("Stock total (todos)", f"{stock_total_skus:,.0f}")
        c4.metric("Valor stock", f"${valor_total_skus/1e6:,.1f}M")

        st.divider()

        # Tabla
        cols = ['SKU', 'Producto', 'Marca', 'Canal', 'Cantidad', 'Venta', '% Venta este canal',
                'Qty', 'Vta 30d Qty', 'Dias Stock', 'Cobertura este canal (días)', 'Semaforo_emoji']
        cols = [c for c in cols if c in df_join.columns]
        df_show = df_join[cols].sort_values('Venta', ascending=False).rename(columns={'Semaforo_emoji': 'Semáforo'})
        st.dataframe(
            df_show.style.map(color_sem, subset=['Semáforo']).format({
                'Cantidad': '{:,.0f}', 'Venta': '${:,.0f}',
                '% Venta este canal': '{:.1f}%',
                'Qty': '{:,.0f}', 'Vta 30d Qty': '{:,.0f}',
                'Dias Stock': '{:,.0f}', 'Cobertura este canal (días)': '{:,.0f}',
            }),
            height=500, use_container_width=True, hide_index=True,
        )


st.markdown("---")
gen = stock.get('metadata', {}).get('generado_en', datetime.now().isoformat())
st.caption(f"Cruce Stock × Ventas · Generado: {gen[:19]} · Cache 5 min")
