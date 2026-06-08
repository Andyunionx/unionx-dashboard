"""
Monitor Cyber en vivo — Operaciones
Pedidos y unidades por hora vs meta diaria durante el Cyber 2026.

Fuente datos: parquet directo (historico + mes actual) — sin depender de shared/SQLite/Turso.
Filtra bodegas propias — excluye fulfillment externo (ML Full, Falabella Full).
Fuente metas: data/planificacion/plan_cyber_2026.json
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
META_JSON    = PROJECT_ROOT / "data" / "planificacion" / "plan_cyber_2026.json"
SLA_CONFIG   = PROJECT_ROOT / "data" / "ops_manuales" / "cyber_sla_config.json"
HIST_PARQUET = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"
MES_PARQUET  = PROJECT_ROOT / "data" / "historico" / "ventas_mes_actual.parquet"
WMS_PARQUET  = PROJECT_ROOT / "data" / "operaciones" / "volumen_inventario_hist.parquet"

CYBER_START  = date(2026, 6, 1)
CYBER_END    = date(2026, 6, 6)
CYBER_DIAS   = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
CURVA_DIARIA = [0.30, 0.25, 0.20, 0.12, 0.08, 0.05]
CURVA_HORA   = {8: 0.05, 9: 0.10, 10: 0.12, 11: 0.13, 12: 0.12,
                13: 0.10, 14: 0.10, 15: 0.09, 16: 0.08, 17: 0.06, 18: 0.05}
_COLS = ["tipo_movimiento", "bodega", "pedido", "fecha_venta",
         "hora_venta_num", "cantidad", "canal"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dia_cyber(d: date):
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
    resumen = data.get("resumen", {})

    def _parse_int(s):
        try:
            return int(str(s).replace(",", "").replace(".", "").replace("$", "").strip().split()[0])
        except Exception:
            return 0

    data["meta_equipo_uds"] = _parse_int(resumen.get("Unidades a cargo del equipo", "12464"))
    data["meta_full_uds"]   = _parse_int(resumen.get("Unidades vía Full Objetivo", "8022"))
    return data


def _meta_dia(meta: dict, dia_idx: int) -> int:
    curva = meta.get("curva_diaria") or CURVA_DIARIA
    if dia_idx >= len(curva):
        return 0
    item = curva[dia_idx]
    pct = item.get("pct", 0) if isinstance(item, dict) else float(item)
    return round(meta.get("meta_equipo_uds", 12_464) * pct)


def _meta_hora_acum(meta_dia_uds: int, hasta_hora: int) -> int:
    return round(meta_dia_uds * sum(v for h, v in CURVA_HORA.items() if h <= hasta_hora))


def _meta_hora_incremental(meta_dia_uds: int, hora: int) -> int:
    return round(meta_dia_uds * CURVA_HORA.get(hora, 0))


# ── Carga de datos (parquet directo, sin shared/SQLite/Turso) ─────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _cargar_ventas_cyber() -> pd.DataFrame:
    """Lee parquets, filtra Cyber y bodega propia. Sin dependencias externas."""
    dfs = []
    for p in (HIST_PARQUET, MES_PARQUET):
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p, columns=[c for c in _COLS
                                              if c in pd.read_parquet(p, engine="pyarrow").columns],
                                 engine="pyarrow")
            dfs.append(df)
        except Exception:
            pass
    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True)
    df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce").dt.date
    mask = (
        (df["fecha_venta"] >= CYBER_START) &
        (df["fecha_venta"] <= CYBER_END) &
        (df.get("tipo_movimiento", pd.Series("", index=df.index)) != "Nota de crédito") &
        (~df["bodega"].str.lower().str.contains("fulfillment", na=False))
    )
    df = df[mask].copy()
    df["hora_venta_num"] = pd.to_numeric(df.get("hora_venta_num", 0), errors="coerce").fillna(0).astype(int)
    return df


def _ventas_dia(fecha: date) -> pd.DataFrame:
    df = _cargar_ventas_cyber()
    if df.empty:
        return pd.DataFrame()
    return df[df["fecha_venta"] == fecha].rename(columns={"hora_venta_num": "hour"})


def _ventas_cyber_historico() -> pd.DataFrame:
    df = _cargar_ventas_cyber()
    if df.empty:
        return pd.DataFrame()
    return df.rename(columns={"hora_venta_num": "hour"})


# ── Tabs ──────────────────────────────────────────────────────────────────────

def _tab_hoy(meta: dict, fecha: date):
    dia_idx = _dia_cyber(fecha)
    if dia_idx is None:
        st.info("El Cyber es del 1 al 6 de junio 2026.")
        return

    meta_d     = _meta_dia(meta, dia_idx)
    dia_nombre = CYBER_DIAS[dia_idx]
    st.markdown(f"### {dia_nombre} {fecha.strftime('%d/%m')} — Meta bodega: **{meta_d:,} uds**".replace(",", "."))

    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        if st.button("Actualizar", key="cyber_refresh_hoy", width='stretch'):
            _cargar_ventas_cyber.clear()
    with col_info:
        st.caption("Parquet actualizado cada ~15 min. Solo bodega propia, sin fulfillment externo.")

    df = _ventas_dia(fecha)
    if df.empty:
        st.warning("Sin ventas de bodega propia para esta fecha.")
        df = pd.DataFrame(columns=["pedido", "hour", "cantidad"])

    by_hora = df.groupby("hour").agg(
        pedidos=("pedido", "nunique"),
        uds=("cantidad", "sum"),
    ).reindex(range(8, 20), fill_value=0).reset_index()
    by_hora.columns = ["hora", "pedidos", "uds"]
    by_hora["meta_hora"] = by_hora["hora"].apply(lambda h: _meta_hora_incremental(meta_d, h))
    by_hora["meta_acum"] = by_hora["meta_hora"].cumsum()
    by_hora["real_acum"] = by_hora["uds"].cumsum()

    uds_total       = int(by_hora["uds"].sum())
    ped_total       = int(df["pedido"].nunique()) if not df.empty else 0
    avance_pct      = uds_total / meta_d * 100 if meta_d else 0
    hora_actual     = datetime.now().hour
    meta_acum_ahora = _meta_hora_acum(meta_d, hora_actual)
    gap             = uds_total - meta_acum_ahora
    horas_trans     = max(hora_actual - 8, 1)
    ritmo           = uds_total / horas_trans
    proyeccion      = round(ritmo * (19 - 8))
    avance_acum_pct = (uds_total / meta_acum_ahora * 100) if meta_acum_ahora else 0
    proy_pct        = (proyeccion / meta_d * 100) if meta_d else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pedidos", f"{ped_total:,}".replace(",", "."))
    c2.metric("% del día", f"{avance_pct:.1f}%",
              f"{uds_total:,} / {meta_d:,} uds".replace(",", "."))
    c3.metric("% vs meta acumulada", f"{avance_acum_pct:.1f}%",
              f"{gap:+,} uds · meta {hora_actual}h: {meta_acum_ahora:,}".replace(",", "."),
              delta_color="normal" if gap >= 0 else "inverse")
    c4.metric("Proyección cierre", f"{proy_pct:.1f}%",
              f"{proyeccion:,} uds · ritmo {ritmo:.0f}/h".replace(",", "."))

    st.markdown("---")

    fig = go.Figure()
    fig.add_trace(go.Bar(x=by_hora["hora"], y=by_hora["uds"],
                         name="Uds reales", marker_color="#1E40AF", opacity=0.85))
    fig.add_trace(go.Scatter(x=by_hora["hora"], y=by_hora["meta_acum"],
                             name="Meta acumulada", mode="lines+markers",
                             line=dict(color="#DC2626", width=2, dash="dash")))
    fig.add_trace(go.Scatter(x=by_hora["hora"], y=by_hora["real_acum"],
                             name="Real acumulado", mode="lines+markers",
                             line=dict(color="#16A34A", width=2)))
    fig.update_layout(height=360, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(title="Hora", dtick=1), yaxis=dict(title="Unidades"),
                      legend=dict(orientation="h", y=1.08), margin=dict(t=30, b=20))
    st.plotly_chart(fig, width='stretch')

    st.markdown("#### Detalle por hora")
    df_show = by_hora.copy()
    df_show["hora"]       = df_show["hora"].apply(lambda h: f"{h:02d}:00")
    df_show["gap"]        = df_show["real_acum"] - df_show["meta_acum"]
    df_show["avance_pct"] = df_show.apply(
        lambda r: f"{r['real_acum']/r['meta_acum']*100:.1f}%" if r["meta_acum"] > 0 else "—", axis=1)
    df_show.columns = ["Hora", "Pedidos", "Uds reales", "Meta hora",
                       "Meta acum", "Real acum", "Gap", "% Avance"]
    st.dataframe(df_show, width='stretch', hide_index=True, height=340)


def _tab_acumulado(meta: dict):
    st.markdown("### Acumulado Cyber 2026")
    df = _ventas_cyber_historico()
    if df.empty:
        st.info("Sin datos Cyber en los parquets aún.")
        return

    by_dia = df.groupby("fecha_venta").agg(
        pedidos=("pedido", "nunique"),
        uds=("cantidad", "sum"),
    ).reset_index()
    by_dia["dia_idx"]    = by_dia["fecha_venta"].apply(_dia_cyber)
    by_dia["dia_nombre"] = by_dia["dia_idx"].apply(lambda i: CYBER_DIAS[i] if i is not None else "—")
    by_dia["meta_uds"]   = by_dia["dia_idx"].apply(lambda i: _meta_dia(meta, i) if i is not None else 0)
    by_dia["avance_pct"] = (by_dia["uds"] / by_dia["meta_uds"] * 100).round(1)

    meta_total = meta.get("meta_equipo_uds", 0)
    uds_total  = int(by_dia["uds"].sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Pedidos acumulados", f"{int(by_dia['pedidos'].sum()):,}".replace(",", "."))
    c2.metric("Unidades acumuladas", f"{uds_total:,}".replace(",", "."))
    c3.metric("Avance vs meta total",
              f"{uds_total/meta_total*100:.1f}%" if meta_total else "—",
              f"Meta bodega: {meta_total:,} uds".replace(",", "."))

    st.markdown("---")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=by_dia["dia_nombre"], y=by_dia["uds"],
                         name="Uds reales", marker_color="#1E40AF"))
    fig.add_trace(go.Scatter(x=by_dia["dia_nombre"], y=by_dia["meta_uds"],
                             name="Meta día", mode="lines+markers",
                             line=dict(color="#DC2626", width=2, dash="dash")))
    fig.update_layout(height=320, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      yaxis_title="Unidades", legend=dict(orientation="h", y=1.08),
                      margin=dict(t=30, b=20))
    st.plotly_chart(fig, width='stretch')

    df_show = by_dia[["dia_nombre", "fecha_venta", "pedidos", "uds", "meta_uds", "avance_pct"]].copy()
    df_show.columns = ["Día", "Fecha", "Pedidos", "Unidades", "Meta", "% Avance"]
    st.dataframe(df_show, width='stretch', hide_index=True)


def _tab_metas(meta: dict):
    st.markdown("### Metas Cyber por canal")
    canales = meta.get("metas_canal", [])
    if not canales:
        st.info("Sin metas por canal.")
        return
    df = pd.DataFrame(canales)
    total    = df["meta_uds"].sum()
    meta_eq  = meta.get("meta_equipo_uds", 0)
    meta_ful = meta.get("meta_full_uds", 0)
    df["pct"]        = (df["meta_uds"] / total * 100).round(1).astype(str) + "%"
    df["meta_venta"] = df["meta_venta"].apply(lambda v: f"${v/1e6:.1f}M")
    c1, c2, c3 = st.columns(3)
    c1.metric("Meta total Cyber", f"{int(total):,}".replace(",", "."), "todos los canales")
    c2.metric("Meta bodega propia", f"{meta_eq:,}".replace(",", "."), "excluye fulfillment")
    c3.metric("Fulfillment externo", f"{meta_ful:,}".replace(",", "."), "ML Full, Falabella Full…")
    df = df.rename(columns={"canal": "Canal", "modalidad": "Modalidad",
                             "meta_uds": "Meta Uds", "meta_venta": "Meta Venta",
                             "ticket_meta": "Ticket", "pct": "% Total"})
    st.dataframe(df[["Canal", "Modalidad", "Meta Uds", "% Total", "Meta Venta"]],
                 width='stretch', hide_index=True, height=480)


# ── SLA / Backlog ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _load_sla_config() -> dict:
    if not SLA_CONFIG.exists():
        return {}
    return json.loads(SLA_CONFIG.read_text(encoding="utf-8")).get("canales", {})


def _corte_canal(canal: str, config: dict) -> tuple[str, str]:
    """Devuelve (corte_str_HH:MM, modalidad) para un canal dado."""
    c = config.get(canal) or config.get("_default", {"corte": "16:00", "modalidad": "nextday"})
    return c["corte"], c["modalidad"]


def _corte_a_hora(corte_str: str) -> int:
    """'14:00' → 14"""
    return int(corte_str.split(":")[0])


@st.cache_data(ttl=180, show_spinner=False)
def _wms_pickings_dia(fecha: date) -> pd.DataFrame:
    """Pickings outgoing del día desde el parquet WMS."""
    if not WMS_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(WMS_PARQUET)
    df["fecha_done"] = pd.to_datetime(df["fecha_done"], errors="coerce")
    df["date"] = df["fecha_done"].dt.date
    df["hour"] = df["fecha_done"].dt.hour
    mask = (df["date"] == fecha) & (df["picking_type_code"] == "outgoing")
    return df[mask][["picking_id", "hour", "n_unidades", "n_lineas"]].copy()


def _tab_backlog(fecha: date):
    """Tab Backlog SLA: pedidos urgentes (antes del corte) vs despachados."""
    sla = _load_sla_config()
    ahora_h = datetime.now().hour

    st.markdown(f"### Backlog SLA — {fecha.strftime('%d/%m/%Y')}")
    st.caption("Urgentes = pedidos recibidos ANTES del corte del canal (deben salir hoy). "
               "Programados = recibidos DESPUÉS del corte (salen mañana).")

    if st.button("Actualizar", key="sla_refresh", width='content'):
        _cargar_ventas_cyber.clear()
        _wms_pickings_dia.clear()

    df_v = _ventas_dia(fecha)
    df_wms = _wms_pickings_dia(fecha)

    if df_v.empty:
        st.warning("Sin datos de ventas para esta fecha.")
        return

    # Clasificar cada pedido como urgente/programado según corte de canal
    def clasificar(row):
        corte_str, modalidad = _corte_canal(row["canal"] if "canal" in row.index else "", sla)
        corte_h = _corte_a_hora(corte_str)
        hora_venta = int(row["hour"]) if pd.notna(row.get("hour")) else 0
        return "urgente" if hora_venta < corte_h else "programado"

    df_v["clasificacion"] = df_v.apply(clasificar, axis=1)
    df_v["canal"] = df_v.get("canal", "")

    # KPIs globales
    urgentes   = df_v[df_v["clasificacion"] == "urgente"]
    programados = df_v[df_v["clasificacion"] == "programado"]
    ped_urg    = urgentes["pedido"].nunique()
    uds_urg    = int(urgentes["cantidad"].sum())
    ped_prog   = programados["pedido"].nunique()
    uds_prog   = int(programados["cantidad"].sum())

    # Despachados WMS hoy
    uds_desp   = int(df_wms["n_unidades"].sum()) if not df_wms.empty else 0
    backlog    = max(0, uds_urg - uds_desp)
    pct_desp   = min(100, uds_desp / uds_urg * 100) if uds_urg else 0

    c1, c2, c3, c4 = st.columns(4)
    col_back = "#DC2626" if backlog > 200 else ("#EA580C" if backlog > 50 else "#16A34A")
    c1.metric("Pedidos urgentes (hoy)", f"{ped_urg:,}".replace(",", "."),
              f"{uds_urg:,} uds antes del corte".replace(",", "."))
    c2.metric("Despachados WMS", f"{uds_desp:,}".replace(",", "."),
              f"{pct_desp:.0f}% de urgentes")
    c3.metric("Backlog urgente", f"{backlog:,}".replace(",", "."),
              "uds pendientes de hoy", delta_color="inverse" if backlog > 0 else "off")
    c4.metric("Programados mañana", f"{ped_prog:,}".replace(",", "."),
              f"{uds_prog:,} uds".replace(",", "."))

    st.markdown("---")

    # Tabla por canal con corte y estado
    st.markdown("#### Por canal — estado SLA")
    rows = []
    for canal, grp in df_v.groupby("canal"):
        corte_str, modalidad = _corte_canal(canal, sla)
        corte_h = _corte_a_hora(corte_str)
        urg  = grp[grp["clasificacion"] == "urgente"]
        prog = grp[grp["clasificacion"] == "programado"]
        u_ped  = urg["pedido"].nunique()
        u_uds  = int(urg["cantidad"].sum())
        p_ped  = prog["pedido"].nunique()
        pasado = ahora_h >= corte_h
        estado = "🔒 Cerrado" if pasado else f"🟢 Abierto (cierra {corte_str})"
        rows.append({
            "Canal": canal,
            "Modalidad": modalidad,
            "Corte": corte_str,
            "Estado": estado,
            "Ped urgentes": u_ped,
            "Uds urgentes": u_uds,
            "Ped progr.": p_ped,
        })
    df_sla = pd.DataFrame(rows).sort_values(["Corte", "Canal"])
    st.dataframe(df_sla, width='stretch', hide_index=True, height=420)

    # Evolución backlog por hora
    st.markdown("#### Acumulado ventas urgentes vs despachos (por hora)")
    by_hora_v = urgentes.groupby("hour").agg(uds_v=("cantidad","sum")).reindex(range(0,24), fill_value=0).reset_index()
    by_hora_v["acum_v"] = by_hora_v["uds_v"].cumsum()

    if not df_wms.empty:
        by_hora_w = df_wms.groupby("hour").agg(uds_w=("n_unidades","sum")).reindex(range(0,24), fill_value=0).reset_index()
        by_hora_w["acum_w"] = by_hora_w["uds_w"].cumsum()
    else:
        by_hora_w = pd.DataFrame({"hour": range(24), "acum_w": [0]*24})

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=by_hora_v["hour"], y=by_hora_v["acum_v"],
                             name="Vendido urgente acum.", mode="lines+markers",
                             line=dict(color="#DC2626", width=2)))
    fig.add_trace(go.Scatter(x=by_hora_w["hour"], y=by_hora_w["acum_w"],
                             name="Despachado WMS acum.", mode="lines+markers",
                             line=dict(color="#16A34A", width=2)))
    fig.update_layout(height=300, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(title="Hora", dtick=1), yaxis=dict(title="Uds acumuladas"),
                      legend=dict(orientation="h", y=1.08), margin=dict(t=30, b=20))
    st.plotly_chart(fig, width='stretch')


# ── Entry point ───────────────────────────────────────────────────────────────

def render():
    hoy  = date.today()
    meta = _load_meta()

    meta_eq  = meta.get("meta_equipo_uds", 0)
    meta_ful = meta.get("meta_full_uds", 0)
    meta_tot = meta.get("meta_total_uds", 0)

    st.title("Cyber 2026 — Monitor Operacional")
    st.caption(
        f"Cyber 1-6 jun 2026 · Meta bodega: **{meta_eq:,} uds** "
        f"({meta_ful:,} fulfillment externo · {meta_tot:,} total)"
        .replace(",", ".")
    )

    if hoy < CYBER_START:
        st.info(f"El Cyber arranca en {(CYBER_START - hoy).days} días ({CYBER_START.strftime('%d/%m/%Y')}).")
    elif hoy > CYBER_END:
        st.success("Cyber 2026 finalizado.")
    else:
        dia_idx = _dia_cyber(hoy)
        st.success(f"CYBER EN VIVO — Día {dia_idx + 1}/6 · {CYBER_DIAS[dia_idx]}")

    tab_hoy, tab_sla, tab_acum, tab_metas = st.tabs([
        "Hoy en vivo", "Backlog SLA", "Acumulado Cyber", "Metas por canal"
    ])

    # Selector de fecha compartido
    fechas = [CYBER_START + timedelta(days=i) for i in range(7)
              if CYBER_START + timedelta(days=i) <= hoy]

    with tab_hoy:
        if not fechas:
            st.info("El Cyber aún no ha comenzado.")
        else:
            fecha_sel = st.selectbox(
                "Fecha", fechas, index=len(fechas) - 1,
                format_func=lambda d: f"{CYBER_DIAS[_dia_cyber(d)]} {d.strftime('%d/%m')}" if _dia_cyber(d) is not None else d.strftime('%d/%m'),
                key="cyber_fecha_sel",
            )
            _tab_hoy(meta, fecha_sel)

    with tab_sla:
        if not fechas:
            st.info("El Cyber aún no ha comenzado.")
        else:
            fecha_sla = st.selectbox(
                "Fecha", fechas, index=len(fechas) - 1,
                format_func=lambda d: f"{CYBER_DIAS[_dia_cyber(d)]} {d.strftime('%d/%m')}" if _dia_cyber(d) is not None else d.strftime('%d/%m'),
                key="cyber_fecha_sla",
            )
            _tab_backlog(fecha_sla)

    with tab_acum:
        _tab_acumulado(meta)

    with tab_metas:
        _tab_metas(meta)
