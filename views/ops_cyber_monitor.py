"""
Monitor Cyber en vivo — Operaciones
Pedidos y unidades por hora vs meta diaria durante el Cyber 2026.

Fuente datos intradiarios: Odoo directo (stock.picking done hoy).
Fuente datos históricos:   volumen_inventario_hist.parquet.
Fuente metas:              data/planificacion/plan_cyber_2026.json
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views._ops_odoo_helper import get_ops_odoo_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
META_JSON    = PROJECT_ROOT / "data" / "planificacion" / "plan_cyber_2026.json"
WMS_PARQUET  = PROJECT_ROOT / "data" / "operaciones" / "volumen_inventario_hist.parquet"

CYBER_START = date(2026, 6, 1)
CYBER_END   = date(2026, 6, 6)
CYBER_DIAS  = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
CURVA_DIARIA = [0.30, 0.25, 0.20, 0.12, 0.08, 0.05]

# Curva intradiaria: distribución % de unidades por hora (8h-19h)
CURVA_HORA = {
    8: 0.05, 9: 0.10, 10: 0.12, 11: 0.13, 12: 0.12,
    13: 0.10, 14: 0.10, 15: 0.09, 16: 0.08, 17: 0.06,
    18: 0.05,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(v: float, prefix="", suffix="") -> str:
    if v >= 1_000_000:
        return f"{prefix}{v/1_000_000:.1f}M{suffix}"
    if v >= 1_000:
        return f"{prefix}{v/1_000:.1f}K{suffix}"
    return f"{prefix}{v:,.0f}{suffix}".replace(",", ".")


def _dia_cyber(d: date) -> int | None:
    if CYBER_START <= d <= CYBER_END:
        return (d - CYBER_START).days
    return None


@st.cache_data(ttl=600, show_spinner=False)
def _load_meta() -> dict:
    if not META_JSON.exists():
        return {"meta_total_uds": 20_486, "meta_equipo_uds": 12_464,
                "meta_full_uds": 8_022, "metas_canal": [], "curva_diaria": CURVA_DIARIA}
    data = json.loads(META_JSON.read_text(encoding="utf-8"))
    if not data.get("curva_diaria"):
        data["curva_diaria"] = CURVA_DIARIA
    # Extraer uds equipo (sin fulfillment) desde el resumen del planner
    resumen = data.get("resumen", {})
    def _parse_int(s):
        try:
            return int(str(s).replace(",", "").replace(".", "").replace("$", "").strip().split()[0])
        except Exception:
            return 0
    data["meta_equipo_uds"] = _parse_int(resumen.get("Unidades a cargo del equipo", "12464"))
    data["meta_full_uds"]   = _parse_int(resumen.get("Unidades vía Full Objetivo",   "8022"))
    return data


def _meta_dia(meta: dict, dia_idx: int) -> int:
    """Meta diaria usando SOLO unidades a cargo del equipo (sin fulfillment)."""
    curva = meta.get("curva_diaria") or CURVA_DIARIA
    if dia_idx >= len(curva):
        return 0
    item = curva[dia_idx]
    pct = item.get("pct", 0) if isinstance(item, dict) else float(item)
    return round(meta.get("meta_equipo_uds", 12_464) * pct)


def _meta_hora_acum(meta_dia_uds: int, hasta_hora: int) -> int:
    pct = sum(v for h, v in CURVA_HORA.items() if h <= hasta_hora)
    return round(meta_dia_uds * pct)


def _meta_hora_incremental(meta_dia_uds: int, hora: int) -> int:
    return round(meta_dia_uds * CURVA_HORA.get(hora, 0))


# ── Carga de datos ────────────────────────────────────────────────────────────

def _pickings_odoo(fecha: date) -> pd.DataFrame:
    """Consulta Odoo directo para pickings outgoing del día."""
    odoo = get_ops_odoo_client()
    if odoo is None:
        return pd.DataFrame()
    try:
        desde = f"{fecha} 00:00:00"
        hasta = f"{fecha} 23:59:59"
        picks = odoo.search_read(
            "stock.picking",
            [
                ("state", "=", "done"),
                ("picking_type_code", "=", "outgoing"),
                ("date_done", ">=", desde),
                ("date_done", "<=", hasta),
            ],
            ["name", "date_done", "partner_id"],
            limit=5000,
        )
        if not picks:
            return pd.DataFrame()
        rows = []
        for p in picks:
            dt = pd.to_datetime(p["date_done"])
            rows.append({
                "picking_id": p["id"],
                "name": p["name"],
                "fecha_done": dt,
                "hour": dt.hour,
                "partner": p["partner_id"][1] if p.get("partner_id") else "—",
            })
        return pd.DataFrame(rows)
    except Exception as e:
        st.warning(f"Odoo: {type(e).__name__}: {str(e)[:80]}")
        return pd.DataFrame()


def _pickings_odoo_con_lineas(fecha: date) -> pd.DataFrame:
    """Versión con n_unidades sumando move_ids (más lento, más preciso)."""
    odoo = get_ops_odoo_client()
    if odoo is None:
        return pd.DataFrame()
    try:
        desde = f"{fecha} 00:00:00"
        hasta = f"{fecha} 23:59:59"
        moves = odoo.search_read(
            "stock.move",
            [
                ("state", "=", "done"),
                ("picking_type_code", "=", "outgoing"),
                ("date", ">=", desde),
                ("date", "<=", hasta),
            ],
            ["picking_id", "date", "product_qty"],
            limit=50000,
        )
        if not moves:
            return pd.DataFrame()
        rows = []
        for m in moves:
            dt = pd.to_datetime(m["date"])
            pid = m["picking_id"][0] if m.get("picking_id") else None
            rows.append({
                "picking_id": pid,
                "fecha_done": dt,
                "hour": dt.hour,
                "n_unidades": float(m.get("product_qty") or 0),
            })
        df = pd.DataFrame(rows)
        return df.groupby(["picking_id", "hour", "fecha_done"]).agg(
            n_unidades=("n_unidades", "sum")
        ).reset_index()
    except Exception as e:
        st.warning(f"Odoo moves: {type(e).__name__}: {str(e)[:80]}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def _wms_cyber_historico() -> pd.DataFrame:
    """Datos Cyber históricos del parquet (días anteriores al hoy)."""
    if not WMS_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(WMS_PARQUET)
    df["fecha_done"] = pd.to_datetime(df["fecha_done"])
    df["date"] = df["fecha_done"].dt.date
    df["hour"] = df["fecha_done"].dt.hour
    mask = (
        (df["date"] >= CYBER_START)
        & (df["date"] <= CYBER_END)
        & (df["picking_type_code"] == "outgoing")
    )
    return df[mask].copy()


# ── Tabs ──────────────────────────────────────────────────────────────────────

def _tab_hoy(meta: dict, fecha: date):
    dia_idx = _dia_cyber(fecha)
    if dia_idx is None:
        st.info("El Cyber es del 1 al 6 de junio 2026.")
        return

    meta_d = _meta_dia(meta, dia_idx)
    dia_nombre = CYBER_DIAS[dia_idx]
    st.markdown(f"### 📅 {dia_nombre} {fecha.strftime('%d/%m')} — Meta: **{meta_d:,} uds**".replace(",", "."))

    # Botón refresh
    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        if st.button("🔄 Actualizar Odoo", key="cyber_refresh_hoy", use_container_width=True):
            st.cache_data.clear()
    with col_info:
        st.caption("Datos en vivo desde Odoo. Actualiza cada vez que presiones el botón.")

    with st.spinner("Consultando Odoo..."):
        df_moves = _pickings_odoo_con_lineas(fecha)

    if df_moves.empty:
        st.warning("Sin datos para hoy en Odoo. Puede que aún no haya despachos registrados.")
        df_moves = pd.DataFrame(columns=["picking_id", "hour", "n_unidades"])

    # Agregado por hora
    by_hora = df_moves.groupby("hour").agg(
        pedidos=("picking_id", "nunique"),
        uds=("n_unidades", "sum"),
    ).reindex(range(8, 20), fill_value=0).reset_index()
    by_hora.columns = ["hora", "pedidos", "uds"]
    by_hora["meta_hora"] = by_hora["hora"].apply(lambda h: _meta_hora_incremental(meta_d, h))
    by_hora["meta_acum"] = by_hora["meta_hora"].cumsum()
    by_hora["real_acum"] = by_hora["uds"].cumsum()

    uds_total   = int(by_hora["uds"].sum())
    ped_total   = int(df_moves["picking_id"].nunique()) if not df_moves.empty else 0
    avance_pct  = uds_total / meta_d * 100 if meta_d else 0
    hora_actual = datetime.now().hour
    meta_acum_ahora = _meta_hora_acum(meta_d, hora_actual)
    gap = uds_total - meta_acum_ahora

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pedidos despachados", f"{ped_total:,}".replace(",", "."))
    c2.metric("Unidades despachadas", f"{uds_total:,}".replace(",", "."),
              f"{avance_pct:.1f}% de meta día")
    color_gap = "normal" if gap >= 0 else "inverse"
    c3.metric("vs Meta acumulada", f"{gap:+,}".replace(",", "."),
              f"Meta acum. {hora_actual}h: {meta_acum_ahora:,}".replace(",", "."),
              delta_color=color_gap)
    # Proyección lineal
    horas_transcurridas = max(hora_actual - 8, 1)
    ritmo = uds_total / horas_transcurridas if horas_transcurridas > 0 else 0
    proyeccion = round(ritmo * (19 - 8))
    c4.metric("Proyección cierre", f"{proyeccion:,}".replace(",", "."),
              f"Ritmo: {ritmo:.0f} uds/h")

    st.markdown("---")

    # Gráfico hora × hora
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=by_hora["hora"], y=by_hora["uds"],
        name="Uds reales", marker_color="#1E40AF", opacity=0.85,
    ))
    fig.add_trace(go.Scatter(
        x=by_hora["hora"], y=by_hora["meta_acum"],
        name="Meta acumulada", mode="lines+markers",
        line=dict(color="#DC2626", width=2, dash="dash"),
    ))
    fig.add_trace(go.Scatter(
        x=by_hora["hora"], y=by_hora["real_acum"],
        name="Real acumulado", mode="lines+markers",
        line=dict(color="#16A34A", width=2),
    ))
    fig.update_layout(
        height=380, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(title="Hora", dtick=1, tickformat="%H:00"),
        yaxis=dict(title="Unidades"),
        legend=dict(orientation="h", y=1.08, x=0),
        margin=dict(t=30, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Tabla detalle
    st.markdown("#### Detalle por hora")
    df_show = by_hora.copy()
    df_show["hora"] = df_show["hora"].apply(lambda h: f"{h:02d}:00")
    df_show.columns = ["Hora", "Pedidos", "Uds reales", "Meta hora", "Meta acum", "Real acum"]
    df_show["Gap"] = df_show["Real acum"] - df_show["Meta acum"]
    st.dataframe(df_show, use_container_width=True, hide_index=True, height=350)


def _tab_acumulado_cyber(meta: dict):
    """Resumen acumulado todos los días del Cyber (parquet histórico)."""
    df = _wms_cyber_historico()

    st.markdown("### 📊 Acumulado Cyber 2026 (todos los días)")

    if df.empty:
        st.info("Sin datos históricos del Cyber en el parquet. Se cargan al día siguiente de cada jornada.")
        return

    by_dia = df.groupby("date").agg(
        pedidos=("picking_id", "nunique"),
        uds=("n_unidades", "sum"),
        lineas=("n_lineas", "sum"),
    ).reset_index()
    by_dia["dia_idx"] = by_dia["date"].apply(lambda d: _dia_cyber(d))
    by_dia["dia_nombre"] = by_dia["dia_idx"].apply(
        lambda i: CYBER_DIAS[i] if i is not None else "—"
    )
    by_dia["meta_uds"] = by_dia["dia_idx"].apply(
        lambda i: _meta_dia(meta, i) if i is not None else 0
    )
    by_dia["avance_pct"] = (by_dia["uds"] / by_dia["meta_uds"] * 100).round(1)

    meta_total = meta.get("meta_total_uds", 0)
    uds_total  = int(by_dia["uds"].sum())
    ped_total  = int(by_dia["pedidos"].sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Pedidos acumulados Cyber", f"{ped_total:,}".replace(",", "."))
    c2.metric("Unidades acumuladas", f"{uds_total:,}".replace(",", "."))
    c3.metric("Avance vs meta total", f"{uds_total/meta_total*100:.1f}%" if meta_total else "—",
              f"Meta: {meta_total:,} uds".replace(",", "."))

    st.markdown("---")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=by_dia["dia_nombre"], y=by_dia["uds"],
        name="Uds reales", marker_color="#1E40AF",
    ))
    fig.add_trace(go.Scatter(
        x=by_dia["dia_nombre"], y=by_dia["meta_uds"],
        name="Meta día", mode="lines+markers",
        line=dict(color="#DC2626", width=2, dash="dash"),
    ))
    fig.update_layout(
        height=340, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title="Unidades", legend=dict(orientation="h", y=1.08),
        margin=dict(t=30, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    df_show = by_dia[["dia_nombre", "date", "pedidos", "uds", "lineas", "meta_uds", "avance_pct"]].copy()
    df_show.columns = ["Día", "Fecha", "Pedidos", "Unidades", "Líneas", "Meta", "% Avance"]
    st.dataframe(df_show, use_container_width=True, hide_index=True)


def _tab_metas(meta: dict):
    """Tabla de metas por canal cargada desde el JSON."""
    st.markdown("### 🎯 Metas Cyber por canal")
    canales = meta.get("metas_canal", [])
    if not canales:
        st.info("Sin metas por canal en el JSON.")
        return

    df = pd.DataFrame(canales)
    total = df["meta_uds"].sum()
    df["% del total"] = (df["meta_uds"] / total * 100).round(1).astype(str) + "%"
    df["meta_venta"] = df["meta_venta"].apply(lambda v: f"${v/1e6:.1f}M")
    df.columns = ["Canal", "Modalidad", "Meta Uds", "Meta Venta", "Ticket meta", "% Total"]
    df = df[["Canal", "Modalidad", "Meta Uds", "% Total", "Meta Venta"]]

    c1, c2 = st.columns(2)
    meta_eq  = meta.get("meta_equipo_uds", 0)
    meta_ful = meta.get("meta_full_uds", 0)
    c1.metric("Meta bodega (equipo)", f"{meta_eq:,}".replace(",", "."),
              f"Sin fulfillment externo")
    c2.metric("Fulfillment externo", f"{meta_ful:,}".replace(",", "."),
              f"ML Full, Falabella Full, etc.")

    st.dataframe(df, use_container_width=True, hide_index=True, height=450)


# ── Entry point ───────────────────────────────────────────────────────────────

def render():
    hoy = date.today()
    meta = _load_meta()

    st.title("🚀 Cyber 2026 — Monitor Operacional")
    meta_eq  = meta.get("meta_equipo_uds", 0)
    meta_ful = meta.get("meta_full_uds", 0)
    meta_tot = meta.get("meta_total_uds", 0)
    st.caption(
        f"Cyber 1-6 jun 2026 · Meta bodega: **{meta_eq:,} uds** "
        f"({meta_ful:,} vía fulfillment externo · {meta_tot:,} total)"
        .replace(",", ".")
    )

    # Banner estado del Cyber
    if hoy < CYBER_START:
        dias_restantes = (CYBER_START - hoy).days
        st.info(f"⏳ El Cyber arranca en **{dias_restantes} días** ({CYBER_START.strftime('%d/%m/%Y')}). "
                "Acá verás el monitoreo en vivo cuando empiece.")
    elif hoy > CYBER_END:
        st.success("✅ Cyber 2026 finalizado. Viendo datos históricos.")
    else:
        dia_idx = _dia_cyber(hoy)
        st.success(f"🔴 **CYBER EN VIVO** — Día {dia_idx + 1}/6 · {CYBER_DIAS[dia_idx]}")

    tab_hoy, tab_acum, tab_metas = st.tabs([
        "⚡ Hoy en vivo",
        "📊 Acumulado Cyber",
        "🎯 Metas por canal",
    ])

    # Selector de fecha (para ver días anteriores del Cyber)
    with tab_hoy:
        fechas_cyber = [CYBER_START + timedelta(days=i) for i in range(6)]
        fechas_disponibles = [f for f in fechas_cyber if f <= hoy]
        if not fechas_disponibles:
            st.info("El Cyber aún no ha comenzado.")
        else:
            fecha_sel = st.selectbox(
                "Fecha",
                fechas_disponibles,
                index=len(fechas_disponibles) - 1,
                format_func=lambda d: f"{CYBER_DIAS[_dia_cyber(d)]} {d.strftime('%d/%m')}",
                key="cyber_fecha_sel",
            )
            _tab_hoy(meta, fecha_sel)

    with tab_acum:
        _tab_acumulado_cyber(meta)

    with tab_metas:
        _tab_metas(meta)
