"""
Dashboard de Stock UnionX — Streamlit App v2
Consulta Odoo en tiempo real. Semaforo 3 meses + Tasa de Ocupacion.

Uso:  streamlit run eerr-finanzas/stock_dashboard.py
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import xmlrpc.client
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "odoo", "odoo_config.json")

# Solo configurar pagina si corremos standalone (no embebido en otra pagina via runpy)
try:
    if not st.session_state.get("_embedded_context"):
        st.set_page_config(page_title="Stock UnionX", page_icon="📦", layout="wide", initial_sidebar_state="expanded")
except Exception:
    pass  # ya seteado, ignorar

# ============================================================
# CSS
# ============================================================
st.markdown("""
<style>
    .main .block-container {padding: 1.2rem 1.5rem 1rem 1.5rem; max-width: 100%;}
    section[data-testid="stSidebar"] {background: linear-gradient(180deg, #0D1B2A 0%, #1B2838 100%); width: 260px !important;}
    section[data-testid="stSidebar"] * {color: #CBD5E1 !important;}
    section[data-testid="stSidebar"] .stSelectbox label {font-size: 0.8rem !important; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;}
    section[data-testid="stSidebar"] hr {border-color: rgba(255,255,255,0.1) !important;}

    /* KPI Cards */
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

    /* Occupancy gauge */
    .occ-container {background: white; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #E2E8F0;}
    .occ-bar-bg {background: #E2E8F0; border-radius: 8px; height: 24px; overflow: hidden; position: relative;}
    .occ-bar-fill {height: 100%; border-radius: 8px; transition: width 0.5s;}
    .occ-label {font-size: 0.75rem; color: #64748B; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;}
    .occ-pct {font-size: 1.4rem; font-weight: 700; color: #1E293B;}

    /* Section headers */
    .section-header {
        font-size: 1rem; font-weight: 700; color: #1E293B; padding: 8px 0 6px 0;
        border-bottom: 2px solid #1F4E79; margin-bottom: 12px; letter-spacing: 0.3px;
    }

    /* Hide streamlit default stuff */
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .stDeployButton {display: none;}
    div[data-testid="stMetric"] {background: none !important; padding: 0 !important;}
</style>
""", unsafe_allow_html=True)

FULFILLMENT_KEYWORDS = ["BFML", "BFP", "BFR", "BFW", "Fulfillment", "fulfillment"]
MARKETING_KEYWORDS = ["Mk", "Marketing", "BMPE", "BMPN", "BMPVS"]
PV_OUTLET_KEYWORDS = ["BPV", "Post Venta", "Outlet", "Bo"]


# ============================================================
# DATA
# ============================================================
@st.cache_data(ttl=300, show_spinner="Cargando datos de Odoo...")
def load_odoo_data():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)["produccion"]
    url, db = cfg["url"], cfg["db_name"]
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, cfg["username"], cfg["password"], {})
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def batch_read(model, domain, fields, bs=500):
        ids = models.execute_kw(db, uid, cfg["password"], model, "search", [domain])
        out = []
        for i in range(0, len(ids), bs):
            out.extend(models.execute_kw(db, uid, cfg["password"], model, "read", [ids[i:i+bs]], {"fields": fields}))
        return out

    # Ubicaciones (todas internas, incluyendo sin stock para ocupacion)
    locs_raw = models.execute_kw(db, uid, cfg["password"], "stock.location", "search_read",
                                  [[["usage", "=", "internal"]]],
                                  {"fields": ["id", "complete_name", "name", "child_ids", "quant_ids"]})
    locations = {l["id"]: l for l in locs_raw}

    # Quants
    quants = batch_read("stock.quant",
                         [["location_id.usage", "=", "internal"], ["quantity", ">", 0]],
                         ["location_id", "product_id", "product_categ_id", "quantity",
                          "reserved_quantity", "available_quantity", "value"])

    # Productos
    prods = batch_read("product.product", [["is_storable", "=", True], ["active", "=", True]],
                        ["id", "name", "default_code", "categ_id", "brand_id",
                         "avg_cost", "standard_price", "list_price", "qty_available", "free_qty", "uom_id", "active"])
    products = {p["id"]: p for p in prods}

    # Ventas 90d (incluye 30d)
    f90 = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    f30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    sales = batch_read("sale.order.line",
                        [["order_id.date_order", ">=", f90], ["order_id.state", "in", ["sale", "done"]]],
                        ["product_id", "product_uom_qty", "price_subtotal", "order_id"])

    # Separar 30d y 90d
    # Necesitamos la fecha de cada orden para clasificar
    order_ids_90d = set()
    for s in sales:
        order_ids_90d.add(s["order_id"][0] if s["order_id"] else 0)

    # Obtener fechas de ordenes para clasificar 30d vs 90d
    order_dates = {}
    oid_list = list(order_ids_90d - {0})
    for i in range(0, len(oid_list), 500):
        batch = oid_list[i:i+500]
        orders = models.execute_kw(db, uid, cfg["password"], "sale.order", "read", [batch],
                                    {"fields": ["id", "date_order"]})
        for o in orders:
            order_dates[o["id"]] = o["date_order"][:10] if o["date_order"] else ""

    v30_qty = defaultdict(float)
    v30_cost = defaultdict(float)
    v90_qty = defaultdict(float)
    v90_cost = defaultdict(float)

    for s in sales:
        pid = s["product_id"][0] if s["product_id"] else None
        if not pid:
            continue
        oid = s["order_id"][0] if s["order_id"] else 0
        fecha = order_dates.get(oid, "")
        qty = s.get("product_uom_qty", 0) or 0
        subtotal = s.get("price_subtotal", 0) or 0

        v90_qty[pid] += qty
        v90_cost[pid] += subtotal
        if fecha >= f30:
            v30_qty[pid] += qty
            v30_cost[pid] += subtotal

    ventas = {
        "v30_qty": dict(v30_qty), "v30_cost": dict(v30_cost),
        "v90_qty": dict(v90_qty), "v90_cost": dict(v90_cost),
    }

    return locations, quants, products, ventas


def compute_occupancy(locations):
    """Calcula tasa de ocupacion. Posiciones fisicas = hijas directas de CA1/Stock."""
    positions = []  # lista de cada posicion con su estado

    for lid, loc in locations.items():
        cn = loc.get("complete_name", "")
        if not cn.startswith("CA1/Stock/"):
            continue
        is_leaf = len(loc.get("child_ids", [])) == 0
        if not is_leaf:
            continue

        has_stock = len(loc.get("quant_ids", [])) > 0
        n_quants = len(loc.get("quant_ids", []))
        pos_name = cn.replace("CA1/Stock/", "")

        positions.append({
            "Posicion": pos_name,
            "Ubicacion Completa": cn,
            "Estado": "Ocupada" if has_stock else "Vacia",
            "SKUs": n_quants,
        })

    total = len(positions)
    occupied = sum(1 for p in positions if p["Estado"] == "Ocupada")

    return {
        "positions": positions,
        "total": total,
        "occupied": occupied,
        "empty": total - occupied,
        "pct": round(occupied / total * 100, 1) if total > 0 else 0,
    }


def process(locations, quants, products, ventas):
    v30_qty = ventas["v30_qty"]
    v30_cost = ventas["v30_cost"]
    v90_qty = ventas["v90_qty"]
    v90_cost = ventas["v90_cost"]

    rows = []
    for q in quants:
        pid = q["product_id"][0] if q["product_id"] else None
        prod = products.get(pid, {})
        loc_id = q["location_id"][0] if q["location_id"] else None
        loc = locations.get(loc_id, {})
        cn = loc.get("complete_name", "?")
        parts = cn.split("/")
        parent = "/".join(parts[:2]).strip() if len(parts) >= 2 else cn

        cn_up = cn.upper()
        if any(k.upper() in cn_up for k in FULFILLMENT_KEYWORDS):
            lt = "Fulfillment"
        elif any(k.upper() in cn_up for k in MARKETING_KEYWORDS):
            lt = "Marketing"
        elif any(k.upper() in cn_up for k in PV_OUTLET_KEYWORDS):
            lt = "PV/Outlet"
        else:
            lt = "Planner"

        qty = q.get("quantity", 0) or 0
        res = q.get("reserved_quantity", 0) or 0
        avail = q.get("available_quantity", 0) or 0
        val = q.get("value", 0) or 0
        cu = prod.get("avg_cost", 0) or prod.get("standard_price", 0) or 0
        if qty > 0 and val == 0:
            val = qty * cu

        rows.append({
            "product_id": pid,
            "SKU": prod.get("default_code", "") or "",
            "Producto": prod.get("name", q["product_id"][1] if q["product_id"] else "?"),
            "Categoria": (prod.get("categ_id") or [0, ""])[1],
            "Marca": (prod.get("brand_id") or [0, ""])[1],
            "UdM": (prod.get("uom_id") or [0, ""])[1],
            "Bodega": parent, "Ubicacion": cn, "Tipo": lt,
            "Qty": qty, "Reservada": res, "Disponible": avail,
            "Costo Unit": cu, "Valor": val,
            "Vta 30d Qty": v30_qty.get(pid, 0),
            "Vta 30d $": v30_cost.get(pid, 0),
            "Vta 90d Qty": v90_qty.get(pid, 0),
            "Vta 90d $": v90_cost.get(pid, 0),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, pd.DataFrame()

    agg = df.groupby("product_id").agg({
        "SKU": "first", "Producto": "first", "Categoria": "first", "Marca": "first", "UdM": "first",
        "Qty": "sum", "Reservada": "sum", "Disponible": "sum",
        "Costo Unit": "first", "Valor": "sum",
        "Vta 30d Qty": "first", "Vta 30d $": "first",
        "Vta 90d Qty": "first", "Vta 90d $": "first",
        "Bodega": lambda x: ", ".join(sorted(set(x)))
    }).reset_index()

    # Dias de stock (basado en venta diaria 30d)
    agg["Vta Diaria"] = agg["Vta 30d Qty"] / 30
    agg["Dias Stock"] = agg.apply(lambda r: round(r["Qty"] / r["Vta Diaria"]) if r["Vta Diaria"] > 0 else 999, axis=1)

    # Rotacion en unidades: venta periodo / stock actual
    # Rot > 1 = rota mas de 1 vez en el periodo, Rot < 1 = no alcanza a rotar
    agg["Rot 30d Uds"] = agg.apply(lambda r: round(r["Vta 30d Qty"] / r["Qty"], 2) if r["Qty"] > 0 else 0, axis=1)
    agg["Rot 90d Uds"] = agg.apply(lambda r: round(r["Vta 90d Qty"] / r["Qty"], 2) if r["Qty"] > 0 else 0, axis=1)

    # Rotacion a costo: costo venta periodo / valor inventario actual
    # Usamos costo unitario * qty vendida como proxy de costo de venta
    agg["Costo Vta 30d"] = agg["Vta 30d Qty"] * agg["Costo Unit"]
    agg["Costo Vta 90d"] = agg["Vta 90d Qty"] * agg["Costo Unit"]
    agg["Rot 30d $"] = agg.apply(lambda r: round(r["Costo Vta 30d"] / r["Valor"], 2) if r["Valor"] > 0 else 0, axis=1)
    agg["Rot 90d $"] = agg.apply(lambda r: round(r["Costo Vta 90d"] / r["Valor"], 2) if r["Valor"] > 0 else 0, axis=1)

    def sem(r):
        if r["Qty"] == 0 and r["Vta 30d Qty"] > 0:
            return "🔴 QUIEBRE"
        if r["Dias Stock"] < 30:
            return "🔴 CRITICO"
        if r["Dias Stock"] < 90:
            return "🟡 BAJO"
        if r["Dias Stock"] <= 180:
            return "🟢 OPTIMO"
        if r["Dias Stock"] > 180 and r["Vta 30d Qty"] > 0:
            return "🔵 SOBRESTOCK"
        return "⚪ SIN VENTA"

    agg["Semaforo"] = agg.apply(sem, axis=1)
    return df, agg


# ============================================================
# RENDER HELPERS
# ============================================================
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
    if "QUIEBRE" in str(val) or "CRITICO" in str(val):
        return "background-color:#FEE2E2; color:#991B1B; font-weight:600"
    if "BAJO" in str(val):
        return "background-color:#FEF3C7; color:#92400E; font-weight:600"
    if "OPTIMO" in str(val):
        return "background-color:#D1FAE5; color:#065F46; font-weight:600"
    if "SOBRESTOCK" in str(val):
        return "background-color:#DBEAFE; color:#1E40AF; font-weight:600"
    return "color:#94A3B8"


# ============================================================
# MAIN APP
# ============================================================
def main():
    # ---- SIDEBAR ----
    with st.sidebar:
        st.markdown("### 📦 **Stock UnionX**")
        st.caption("Inventario en tiempo real")
        st.markdown("---")

        if st.button("🔄 Refrescar", use_container_width=True, type="primary"):
            st.cache_data.clear()
            st.rerun()

        st.markdown("##### Semaforo (target 3 meses)")
        st.markdown("""
        🔴 < 30 dias — Critico
        🟡 30-89 dias — Bajo
        🟢 90-180 dias — Optimo
        🔵 > 180 dias — Sobrestock
        ⚪ Sin venta reciente
        """)
        st.markdown("---")

    # ---- LOAD ----
    try:
        locations, quants, products, v30 = load_odoo_data()
    except Exception as e:
        st.error(f"Error Odoo: {e}")
        return

    df_det, df_sku = process(locations, quants, products, v30)
    occ = compute_occupancy(locations)

    if df_sku.empty:
        st.warning("Sin datos de stock")
        return

    # ---- SIDEBAR FILTERS ----
    with st.sidebar:
        st.markdown("##### Filtros")
        sku_options = sorted(df_sku["SKU"].dropna().unique().tolist())
        sku_f = st.multiselect("SKU", sku_options, default=[], placeholder="Buscar SKU...", key="sku")
        cat_f = st.selectbox("Categoria", ["Todas"] + sorted(df_sku["Categoria"].dropna().unique().tolist()), label_visibility="collapsed", key="cat")
        marca_f = st.selectbox("Marca", ["Todas"] + sorted(df_sku["Marca"].dropna().unique().tolist()), label_visibility="collapsed", key="marca")
        sem_f = st.selectbox("Semaforo", ["Todos"] + sorted(df_sku["Semaforo"].unique().tolist()), label_visibility="collapsed", key="sem")
        bod_f = st.selectbox("Bodega", ["Todas"] + sorted(df_det["Bodega"].unique().tolist()), label_visibility="collapsed", key="bod")

    df_f = df_sku.copy()
    if sku_f:
        df_f = df_f[df_f["SKU"].isin(sku_f)]
    if cat_f != "Todas":
        df_f = df_f[df_f["Categoria"] == cat_f]
    if marca_f != "Todas":
        df_f = df_f[df_f["Marca"] == marca_f]
    if sem_f != "Todos":
        df_f = df_f[df_f["Semaforo"] == sem_f]
    if bod_f != "Todas":
        df_f = df_f[df_f["Bodega"].str.contains(bod_f, na=False)]

    # ============================================================
    # HEADER
    # ============================================================
    st.markdown(f"<h2 style='margin:0 0 4px 0; color:#1E293B;'>📦 Dashboard de Stock</h2>", unsafe_allow_html=True)
    st.markdown(f"<span style='color:#94A3B8; font-size:0.8rem;'>{datetime.now().strftime('%d/%m/%Y %H:%M')} · Datos Odoo en tiempo real · Cache 5 min</span>", unsafe_allow_html=True)
    st.markdown("")

    # ============================================================
    # KPIs ROW
    # ============================================================
    total_val = df_f["Valor"].sum()
    total_qty = df_f["Qty"].sum()
    n_skus = len(df_f)
    n_quiebre = len(df_f[df_f["Semaforo"].str.contains("QUIEBRE|CRITICO")])
    n_bajo = len(df_f[df_f["Semaforo"].str.contains("BAJO")])
    n_optimo = len(df_f[df_f["Semaforo"].str.contains("OPTIMO")])
    n_sobre = len(df_f[df_f["Semaforo"].str.contains("SOBRESTOCK")])
    n_sinventa = len(df_f[df_f["Semaforo"].str.contains("SIN VENTA")])
    rot_30d_avg = df_f[df_f["Rot 30d Uds"] > 0]["Rot 30d Uds"].mean() if len(df_f[df_f["Rot 30d Uds"] > 0]) > 0 else 0
    rot_90d_avg = df_f[df_f["Rot 90d Uds"] > 0]["Rot 90d Uds"].mean() if len(df_f[df_f["Rot 90d Uds"] > 0]) > 0 else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.markdown(kpi_card("Valor Inventario", f"${total_val:,.0f}", f"{n_skus:,} SKUs activos", "blue"), unsafe_allow_html=True)
    with c2:
        st.markdown(kpi_card("Unidades", f"{total_qty:,.0f}", f"Costo prom ${total_val/n_skus:,.0f}/SKU" if n_skus else "", "blue"), unsafe_allow_html=True)
    with c3:
        st.markdown(kpi_card("Criticos / Quiebre", str(n_quiebre), "< 30 dias de stock", "red"), unsafe_allow_html=True)
    with c4:
        st.markdown(kpi_card("Bajo Stock", str(n_bajo), "30-89 dias, reponer", "orange"), unsafe_allow_html=True)
    with c5:
        st.markdown(kpi_card("Optimo", str(n_optimo), "90-180 dias", "green"), unsafe_allow_html=True)
    with c6:
        st.markdown(kpi_card("Sobrestock", str(n_sobre), f"> 180 dias · {n_sinventa} sin venta", "blue"), unsafe_allow_html=True)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ============================================================
    # ROW 2: OCUPACION + SEMAFORO + VALOR POR BODEGA
    # ============================================================
    col_occ, col_sem, col_bod = st.columns([1, 1, 1.5])

    with col_occ:
        st.markdown('<div class="section-header">🏭 Ocupacion CA1/Stock</div>', unsafe_allow_html=True)
        st.markdown(occ_bar("CA1/Stock", occ["occupied"], occ["total"]), unsafe_allow_html=True)
        st.markdown(f"""<div style="display:flex; gap:12px; margin-top:10px;">
            <div style="flex:1; text-align:center; background:#D1FAE5; border-radius:8px; padding:12px;">
                <div style="font-size:1.6rem; font-weight:700; color:#065F46;">{occ['occupied']}</div>
                <div style="font-size:0.75rem; color:#065F46;">Ocupadas</div>
            </div>
            <div style="flex:1; text-align:center; background:#FEE2E2; border-radius:8px; padding:12px;">
                <div style="font-size:1.6rem; font-weight:700; color:#991B1B;">{occ['empty']}</div>
                <div style="font-size:0.75rem; color:#991B1B;">Vacias</div>
            </div>
            <div style="flex:1; text-align:center; background:#DBEAFE; border-radius:8px; padding:12px;">
                <div style="font-size:1.6rem; font-weight:700; color:#1E40AF;">{occ['total']}</div>
                <div style="font-size:0.75rem; color:#1E40AF;">Total</div>
            </div>
        </div>""", unsafe_allow_html=True)

    with col_sem:
        st.markdown('<div class="section-header">🚦 Distribucion Semaforo</div>', unsafe_allow_html=True)
        sem_data = df_f["Semaforo"].value_counts().reset_index()
        sem_data.columns = ["Semaforo", "SKUs"]
        cmap = {"🔴 QUIEBRE": "#EF4444", "🔴 CRITICO": "#F87171", "🟡 BAJO": "#F59E0B",
                "🟢 OPTIMO": "#10B981", "🔵 SOBRESTOCK": "#3B82F6", "⚪ SIN VENTA": "#CBD5E1"}
        fig = px.pie(sem_data, names="Semaforo", values="SKUs", color="Semaforo",
                     color_discrete_map=cmap, hole=0.45)
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320,
                          legend=dict(orientation="h", yanchor="top", y=-0.05, font=dict(size=10)),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        fig.update_traces(textinfo="percent+value", textfont_size=11)
        st.plotly_chart(fig, use_container_width=True)

    with col_bod:
        st.markdown('<div class="section-header">💰 Valor por Bodega</div>', unsafe_allow_html=True)
        df_bod = df_det.groupby("Bodega").agg({"Valor": "sum"}).reset_index()
        df_bod = df_bod.sort_values("Valor", ascending=True).tail(12)
        fig_b = go.Figure(go.Bar(
            y=df_bod["Bodega"], x=df_bod["Valor"], orientation="h",
            marker_color="#1F4E79", text=df_bod["Valor"].apply(lambda x: f"${x/1e6:.1f}M"),
            textposition="outside", textfont=dict(size=10)
        ))
        fig_b.update_layout(margin=dict(t=10, b=10, l=10, r=60), height=320,
                            xaxis=dict(showgrid=True, gridcolor="#F1F5F9", title=""),
                            yaxis=dict(title=""), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_b, use_container_width=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ============================================================
    # TABS
    # ============================================================
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Stock Total", "🏭 Por Bodega", "📍 Ocupacion Detalle", "🚨 Alertas", "📈 Top Rotacion"
    ])

    with tab1:
        st.markdown('<div class="section-header">Stock Total Empresa</div>', unsafe_allow_html=True)
        cols = ["SKU", "Producto", "Categoria", "Marca", "Qty", "Reservada", "Disponible",
                "Costo Unit", "Valor", "Vta 30d Qty", "Vta 90d Qty", "Dias Stock",
                "Rot 30d Uds", "Rot 90d Uds", "Rot 30d $", "Rot 90d $", "Semaforo"]
        dfd = df_f[cols].sort_values("Valor", ascending=False)
        st.dataframe(
            dfd.style.map(color_sem, subset=["Semaforo"])
                .format({"Qty": "{:,.0f}", "Reservada": "{:,.0f}", "Disponible": "{:,.0f}",
                          "Costo Unit": "${:,.0f}", "Valor": "${:,.0f}",
                          "Vta 30d Qty": "{:,.0f}", "Vta 90d Qty": "{:,.0f}",
                          "Dias Stock": "{:,.0f}",
                          "Rot 30d Uds": "{:.2f}x", "Rot 90d Uds": "{:.2f}x",
                          "Rot 30d $": "{:.2f}x", "Rot 90d $": "{:.2f}x"}),
            height=550, use_container_width=True, hide_index=True
        )
        st.caption(f"{len(dfd):,} SKUs · Valor: ${dfd['Valor'].sum():,.0f} · Rot prom 30d: {rot_30d_avg:.2f}x · Rot prom 90d: {rot_90d_avg:.2f}x")

    with tab2:
        st.markdown('<div class="section-header">Detalle por Bodega y Ubicacion</div>', unsafe_allow_html=True)
        df_d2 = df_det.copy()
        if sku_f:
            df_d2 = df_d2[df_d2["SKU"].isin(sku_f)]
        if cat_f != "Todas":
            df_d2 = df_d2[df_d2["Categoria"] == cat_f]
        if bod_f != "Todas":
            df_d2 = df_d2[df_d2["Bodega"].str.contains(bod_f, na=False)]
        cols2 = ["Bodega", "Ubicacion", "Tipo", "SKU", "Producto", "Categoria", "Qty", "Reservada", "Disponible", "Costo Unit", "Valor"]
        st.dataframe(
            df_d2[cols2].sort_values(["Bodega", "Valor"], ascending=[True, False])
                .style.format({"Qty": "{:,.0f}", "Reservada": "{:,.0f}", "Disponible": "{:,.0f}",
                               "Costo Unit": "${:,.0f}", "Valor": "${:,.0f}"}),
            height=550, use_container_width=True, hide_index=True
        )
        st.caption(f"{len(df_d2):,} lineas")

    with tab3:
        st.markdown('<div class="section-header">📍 Posiciones CA1/Stock — Detalle de ocupacion</div>', unsafe_allow_html=True)

        # KPIs de ocupacion
        c_k1, c_k2, c_k3, c_k4 = st.columns(4)
        with c_k1:
            st.markdown(kpi_card("Total Posiciones", str(occ["total"]), "CA1/Stock", "blue"), unsafe_allow_html=True)
        with c_k2:
            st.markdown(kpi_card("Ocupadas", str(occ["occupied"]), f"{occ['pct']}%", "green"), unsafe_allow_html=True)
        with c_k3:
            st.markdown(kpi_card("Vacias", str(occ["empty"]), f"{100 - occ['pct']}%", "red"), unsafe_allow_html=True)
        with c_k4:
            st.markdown(kpi_card("% Ocupacion", f"{occ['pct']}%", "Target: <85%", "blue"), unsafe_allow_html=True)

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # Gauge chart + tabla
        c_o1, c_o2 = st.columns([1, 2])

        with c_o1:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=occ["pct"],
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
                title={"text": "Tasa de Ocupacion", "font": {"size": 14}},
            ))
            fig_gauge.update_layout(height=280, margin=dict(t=40, b=20, l=30, r=30),
                                     paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_gauge, use_container_width=True)

        with c_o2:
            df_pos = pd.DataFrame(occ["positions"]).sort_values("Posicion")

            def color_estado(val):
                if val == "Ocupada":
                    return "background-color:#D1FAE5; color:#065F46; font-weight:600"
                return "background-color:#FEE2E2; color:#991B1B; font-weight:600"

            # Filtro rapido
            estado_f = st.radio("Filtrar:", ["Todas", "Ocupadas", "Vacias"], horizontal=True, key="occ_filter")
            if estado_f == "Ocupadas":
                df_pos = df_pos[df_pos["Estado"] == "Ocupada"]
            elif estado_f == "Vacias":
                df_pos = df_pos[df_pos["Estado"] == "Vacia"]

            st.dataframe(
                df_pos[["Posicion", "Estado", "SKUs"]].style.map(color_estado, subset=["Estado"]),
                height=400, use_container_width=True, hide_index=True
            )
            st.caption(f"Mostrando {len(df_pos)} de {occ['total']} posiciones")

    with tab4:
        st.markdown('<div class="section-header">🚨 Alertas de Stock</div>', unsafe_allow_html=True)

        c_a1, c_a2 = st.columns(2)
        with c_a1:
            st.markdown("**🔴 Criticos / Quiebre** — necesitan atencion inmediata")
            df_al = df_f[df_f["Semaforo"].str.contains("QUIEBRE|CRITICO")].sort_values("Vta 30d Qty", ascending=False)
            if len(df_al) > 0:
                st.dataframe(
                    df_al[["SKU", "Producto", "Qty", "Vta 30d Qty", "Dias Stock", "Valor"]]
                    .style.format({"Qty": "{:,.0f}", "Vta 30d Qty": "{:,.0f}", "Valor": "${:,.0f}"}),
                    height=380, use_container_width=True, hide_index=True)
                st.error(f"{len(df_al)} SKUs en riesgo")
            else:
                st.success("Sin criticos")

        with c_a2:
            st.markdown("**🔵 Sobrestock** — capital inmovilizado")
            df_so = df_f[df_f["Semaforo"].str.contains("SOBRESTOCK")].sort_values("Valor", ascending=False)
            if len(df_so) > 0:
                st.dataframe(
                    df_so[["SKU", "Producto", "Qty", "Vta 30d Qty", "Dias Stock", "Valor"]]
                    .style.format({"Qty": "{:,.0f}", "Vta 30d Qty": "{:,.0f}", "Valor": "${:,.0f}"}),
                    height=380, use_container_width=True, hide_index=True)
                st.warning(f"{len(df_so)} SKUs · ${df_so['Valor'].sum():,.0f} inmovilizado")
            else:
                st.success("Sin sobrestock")

        st.markdown("**🟡 Bajo Stock** — reponer para llegar a 90 dias")
        df_bj = df_f[df_f["Semaforo"].str.contains("BAJO")].sort_values("Dias Stock")
        if len(df_bj) > 0:
            st.dataframe(
                df_bj[["SKU", "Producto", "Categoria", "Qty", "Vta 30d Qty", "Dias Stock", "Valor"]]
                .style.format({"Qty": "{:,.0f}", "Vta 30d Qty": "{:,.0f}", "Valor": "${:,.0f}"}),
                height=320, use_container_width=True, hide_index=True)
            st.info(f"{len(df_bj)} SKUs bajo stock")

    with tab5:
        st.markdown('<div class="section-header">📈 Rotacion de Inventario</div>', unsafe_allow_html=True)

        st.markdown("""
        > **Rotacion** = Venta del periodo / Stock actual. Si Rot = 1.0x, el inventario rota 1 vez en el periodo.
        > Rot > 1 = alta rotacion (se vende rapido). Rot < 0.3 = baja rotacion (stock lento).
        """)

        rot_tab1, rot_tab2 = st.tabs(["📊 Rotacion 30 dias", "📊 Rotacion 90 dias"])

        with rot_tab1:
            df_rot30 = df_f[df_f["Vta 30d Qty"] > 0].sort_values("Rot 30d Uds", ascending=False).head(25)
            if len(df_rot30) > 0:
                cmap_r = {"🔴 QUIEBRE": "#EF4444", "🔴 CRITICO": "#F87171", "🟡 BAJO": "#F59E0B",
                          "🟢 OPTIMO": "#10B981", "🔵 SOBRESTOCK": "#3B82F6", "⚪ SIN VENTA": "#CBD5E1"}
                df_chart = df_rot30.head(20).copy()
                df_chart["Label"] = df_chart.apply(
                    lambda r: (r["SKU"][:15] if r["SKU"] and not str(r["SKU"]).isdigit() else r["Producto"][:25]), axis=1)

                fig_r30 = px.bar(df_chart, x="Label", y="Rot 30d Uds", color="Semaforo",
                                 color_discrete_map=cmap_r, text="Rot 30d Uds",
                                 labels={"Label": "Producto", "Rot 30d Uds": "Rotacion 30d (veces)"})
                fig_r30.update_layout(xaxis_tickangle=-45, height=420, margin=dict(t=20, b=120),
                                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                      xaxis=dict(showgrid=False, type="category"),
                                      yaxis=dict(showgrid=True, gridcolor="#F1F5F9"))
                fig_r30.update_traces(texttemplate='%{text:.1f}x', textposition='outside', textfont_size=9)
                st.plotly_chart(fig_r30, use_container_width=True)

                st.dataframe(
                    df_rot30[["SKU", "Producto", "Categoria", "Qty", "Vta 30d Qty", "Rot 30d Uds",
                              "Costo Vta 30d", "Valor", "Rot 30d $", "Dias Stock", "Semaforo"]]
                    .style.map(color_sem, subset=["Semaforo"])
                    .format({"Qty": "{:,.0f}", "Vta 30d Qty": "{:,.0f}", "Rot 30d Uds": "{:.2f}x",
                             "Costo Vta 30d": "${:,.0f}", "Valor": "${:,.0f}", "Rot 30d $": "{:.2f}x",
                             "Dias Stock": "{:,.0f}"}),
                    height=400, use_container_width=True, hide_index=True)

        with rot_tab2:
            df_rot90 = df_f[df_f["Vta 90d Qty"] > 0].sort_values("Rot 90d Uds", ascending=False).head(25)
            if len(df_rot90) > 0:
                df_chart90 = df_rot90.head(20).copy()
                df_chart90["Label"] = df_chart90.apply(
                    lambda r: (r["SKU"][:15] if r["SKU"] and not str(r["SKU"]).isdigit() else r["Producto"][:25]), axis=1)

                fig_r90 = px.bar(df_chart90, x="Label", y="Rot 90d Uds", color="Semaforo",
                                 color_discrete_map=cmap_r, text="Rot 90d Uds",
                                 labels={"Label": "Producto", "Rot 90d Uds": "Rotacion 90d (veces)"})
                fig_r90.update_layout(xaxis_tickangle=-45, height=420, margin=dict(t=20, b=120),
                                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                      xaxis=dict(showgrid=False, type="category"),
                                      yaxis=dict(showgrid=True, gridcolor="#F1F5F9"))
                fig_r90.update_traces(texttemplate='%{text:.1f}x', textposition='outside', textfont_size=9)
                st.plotly_chart(fig_r90, use_container_width=True)

                st.dataframe(
                    df_rot90[["SKU", "Producto", "Categoria", "Qty", "Vta 90d Qty", "Rot 90d Uds",
                              "Costo Vta 90d", "Valor", "Rot 90d $", "Dias Stock", "Semaforo"]]
                    .style.map(color_sem, subset=["Semaforo"])
                    .format({"Qty": "{:,.0f}", "Vta 90d Qty": "{:,.0f}", "Rot 90d Uds": "{:.2f}x",
                             "Costo Vta 90d": "${:,.0f}", "Valor": "${:,.0f}", "Rot 90d $": "{:.2f}x",
                             "Dias Stock": "{:,.0f}"}),
                    height=400, use_container_width=True, hide_index=True)

    # Footer
    st.markdown("---")
    st.caption(f"Stock UnionX v2 · {datetime.now().strftime('%d/%m/%Y %H:%M')} · Odoo {locations and len(locations) or 0} ubicaciones · Cache 5 min")


if __name__ == "__main__":
    main()
