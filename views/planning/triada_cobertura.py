"""
views/planning/triada_cobertura.py
────────────────────────────────────────────────────────────────────────
Triada de Cobertura — funciona 100% con datos locales (sin Turso).

Calcula cobertura en días y meses por SKU cruzando:
  · Stock actual     → data/stock_historico/stock_diario.parquet (fecha más reciente)
  · Tránsito COMEX   → data/comex/transito.parquet
  · Demanda forecast → data/forecast/forecast_skus_anchored.parquet

Vistas: Total · Por SKU · Por Marca · Por Categoría · Marca × Categoría
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import streamlit as st

from views.planning._data_helpers import (
    cargar_forecast_sku,
    cargar_stock_diario,
    cargar_transito,
    cargar_ventas_historicas,
)

# ── Constantes ────────────────────────────────────────────────────────
_TODAY = pd.Timestamp.today().normalize()
_HORIZONTES = [30, 60, 90, 180]

_ESTADO_ORDEN      = ["CRÍTICO", "URGENTE", "AJUSTADO", "NORMAL", "HOLGADO", "SIN DEMANDA"]
_ESTADO_ORDEN_4SEM = ["CRÍTICO", "AJUSTADO", "NORMAL", "SOBRESTOCK", "SIN DEMANDA"]
_ESTADO_BG = {
    "CRÍTICO":     "background-color:#FF4B4B;color:white",
    "URGENTE":     "background-color:#FF8C00;color:white",
    "AJUSTADO":    "background-color:#FFD700;color:#333",
    "NORMAL":      "background-color:#52C41A;color:white",
    "HOLGADO":     "background-color:#1890FF;color:white",
    "SOBRESTOCK":  "background-color:#722ED1;color:white",
    "SIN DEMANDA": "background-color:#E8E8E8;color:#999",
}


def _clasificar(dias) -> str:
    if pd.isna(dias):
        return "SIN DEMANDA"
    d = float(dias)
    if d < 30:  return "CRÍTICO"
    if d < 60:  return "URGENTE"
    if d < 90:  return "AJUSTADO"
    if d < 180: return "NORMAL"
    return "HOLGADO"


def _clasificar_meses(meses) -> str:
    """Clasifica cobertura en meses (ventas reales 4 sem).
    < 1m → CRÍTICO | 1–2m → AJUSTADO | 2–4m → NORMAL | >4m → SOBRESTOCK
    """
    if pd.isna(meses):
        return "SIN DEMANDA"
    m = float(meses)
    if m < 1:  return "CRÍTICO"
    if m <= 2: return "AJUSTADO"
    if m <= 4: return "NORMAL"
    return "SOBRESTOCK"


def _style_estado(val: str) -> str:
    return _ESTADO_BG.get(val, "")


# ── Preparación de datos ──────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _preparar_datos() -> pd.DataFrame:
    """
    Tabla maestra por SKU. Columnas principales:
      sku, producto, marca, categoria_padre, categoria_hijo,
      stock_actual,
      transito_30d / 60d / 90d / 180d  (unidades con ETA ≤ fecha)
      demanda_30d / 60d / 90d / 180d   (forecast acumulado)
      demanda_diaria                    (promedio 90d)
    """

    # ── 1. Stock actual (última fecha disponible) ─────────────────────
    df_sh = cargar_stock_diario()
    ultima = df_sh["fecha"].max()
    df_stock = (
        df_sh[df_sh["fecha"] == ultima]
        .groupby("sku", as_index=False)["cantidad"]
        .sum()
        .rename(columns={"cantidad": "stock_actual"})
    )
    df_stock["stock_actual"] = df_stock["stock_actual"].clip(lower=0)
    df_stock["sku"] = df_stock["sku"].astype(str)

    # ── 2. Forecast demand por horizonte ─────────────────────────────
    df_f = cargar_forecast_sku().copy()
    df_f["ds"] = pd.to_datetime(df_f["ds"])
    df_f["sku"] = df_f["sku"].astype(str)
    df_f["yhat_anchored"] = pd.to_numeric(df_f["yhat_anchored"], errors="coerce").fillna(0).clip(lower=0)

    demanda_parts = []
    for h in _HORIZONTES:
        mask = (df_f["ds"] >= _TODAY) & (df_f["ds"] < _TODAY + timedelta(days=h))
        part = (
            df_f[mask]
            .groupby("sku")["yhat_anchored"]
            .sum()
            .reset_index()
            .rename(columns={"yhat_anchored": f"demanda_{h}d"})
        )
        demanda_parts.append(part)

    df_demanda = demanda_parts[0]
    for p in demanda_parts[1:]:
        df_demanda = df_demanda.merge(p, on="sku", how="outer")

    df_demanda["demanda_diaria"] = (df_demanda.get("demanda_90d", 0) / 90).clip(lower=0)

    # ── 2b. Forecast promedio próximos 3 meses (mes actual + 2 siguientes) ──
    # Fórmula: stock / ((venta_mes1 + venta_mes2 + venta_mes3) / 3)
    meses_3 = pd.period_range(_TODAY.to_period("M"), periods=3, freq="M")
    df_f["_mes"] = df_f["ds"].dt.to_period("M")
    df_f_3m = df_f[df_f["_mes"].isin(meses_3)].copy()
    monthly_fc = (
        df_f_3m.groupby(["sku", "_mes"])["yhat_anchored"]
        .sum()
        .reset_index()
    )
    df_prom3m = (
        monthly_fc.groupby("sku")["yhat_anchored"]
        .mean()
        .reset_index()
        .rename(columns={"yhat_anchored": "venta_prom_3m"})
    )
    df_prom3m["venta_prom_3m"] = df_prom3m["venta_prom_3m"].clip(lower=0)

    # ── 3. Tránsito por horizonte ─────────────────────────────────────
    df_tr = cargar_transito().copy()
    df_tr["sku"] = df_tr["sku"].astype(str)
    df_tr["fecha_eta_bodega"] = pd.to_datetime(df_tr["fecha_eta_bodega"])
    df_tr["cantidad"] = pd.to_numeric(df_tr["cantidad"], errors="coerce").fillna(0)

    transito_parts = []
    for h in _HORIZONTES:
        mask = df_tr["fecha_eta_bodega"] <= _TODAY + timedelta(days=h)
        part = (
            df_tr[mask]
            .groupby("sku")["cantidad"]
            .sum()
            .reset_index()
            .rename(columns={"cantidad": f"transito_{h}d"})
        )
        transito_parts.append(part)

    df_transito = transito_parts[0]
    for p in transito_parts[1:]:
        df_transito = df_transito.merge(p, on="sku", how="outer")

    # ── 4. Metadata SKU ───────────────────────────────────────────────
    df_meta = (
        df_f[["sku", "producto", "marca", "categoria_padre"]]
        .drop_duplicates("sku")
        .copy()
    )

    # categoria_hijo, categoria_comercial y ventas_4sem desde ventas_historico
    df_ventas_4sem = pd.DataFrame(columns=["sku", "ventas_4sem"])
    try:
        df_v = cargar_ventas_historicas()
        df_v["sku"] = df_v["sku"].astype(str)
        df_v = df_v[df_v["sku"].notna() & (df_v["sku"] != "") & (df_v["sku"] != "nan")]
        df_v["fecha_venta"] = pd.to_datetime(df_v["fecha_venta"])
        df_v["cantidad"]    = pd.to_numeric(df_v.get("cantidad", 0), errors="coerce").fillna(0)

        # Metadata: categorías desde la venta más reciente por SKU
        df_v_sorted = df_v.sort_values("fecha_venta", ascending=False)
        meta_cols = [c for c in ["sku", "categoria_hijo", "categoria_comercial"] if c in df_v_sorted.columns]
        df_meta_v = df_v_sorted[meta_cols].drop_duplicates("sku")
        df_meta = df_meta.merge(df_meta_v, on="sku", how="left")

        # Ventas últimas 4 semanas — ventana rolling de 28 días desde hoy
        corte_4sem = _TODAY - timedelta(days=28)
        df_ventas_4sem = (
            df_v[(df_v["fecha_venta"] >= corte_4sem) & (df_v["fecha_venta"] < _TODAY)]
            .groupby("sku")["cantidad"]
            .sum()
            .reset_index()
            .rename(columns={"cantidad": "ventas_4sem"})
        )
    except Exception:
        df_meta["categoria_hijo"]    = ""
        df_meta["categoria_comercial"] = ""

    # ── 5. Unir todo ──────────────────────────────────────────────────
    df = df_meta.copy()
    df = df.merge(df_stock,       on="sku", how="left")
    df = df.merge(df_demanda,     on="sku", how="left")
    df = df.merge(df_transito,    on="sku", how="left")
    df = df.merge(df_ventas_4sem, on="sku", how="left")
    df = df.merge(df_prom3m,      on="sku", how="left")

    fill_cols = (
        ["stock_actual", "demanda_diaria", "ventas_4sem", "venta_prom_3m"]
        + [f"demanda_{h}d"  for h in _HORIZONTES]
        + [f"transito_{h}d" for h in _HORIZONTES]
    )
    for col in fill_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    # ── 6a. Cobertura basada en ventas reales (rolling 4 semanas) ────
    df["cobertura_4sem_meses"] = np.where(
        df["ventas_4sem"] > 0,
        df["stock_actual"] / df["ventas_4sem"],
        np.nan,
    )
    df["estado_4sem"] = df["cobertura_4sem_meses"].apply(_clasificar_meses)

    # ── 6b. Cobertura proyectada (forecast promedio 3 meses) ─────────
    # Fórmula: stock_actual / promedio(mes_actual, mes+1, mes+2)
    df["cobertura_fc3m_meses"] = np.where(
        df["venta_prom_3m"] > 0,
        df["stock_actual"] / df["venta_prom_3m"],
        np.nan,
    )
    df["estado_fc3m"] = df["cobertura_fc3m_meses"].apply(_clasificar_meses)

    # ── 7. Textos vacíos ──────────────────────────────────────────────
    for c in ["categoria_hijo", "categoria_comercial", "marca", "categoria_padre"]:
        if c in df.columns:
            df[c] = df[c].fillna("Sin clasificar").replace("", "Sin clasificar")

    return df.reset_index(drop=True)


def _calcular_cobertura(df: pd.DataFrame, horizonte: int) -> pd.DataFrame:
    """Agrega columnas cobertura_dias, cobertura_meses y estado según horizonte."""
    col_tr = f"transito_{horizonte}d"
    if col_tr not in df.columns:
        col_tr = "transito_30d"

    df = df.copy()
    df["cobertura_dias"] = np.where(
        df["demanda_diaria"] > 0,
        (df["stock_actual"] + df[col_tr]) / df["demanda_diaria"],
        np.nan,
    )
    df["cobertura_meses"] = df["cobertura_dias"] / 30
    df["estado"] = df["cobertura_dias"].apply(_clasificar)
    return df


def _agrupar(df: pd.DataFrame, by: list) -> pd.DataFrame:
    """Agrega métricas por dimensión(es) y recalcula cobertura grupal."""
    agg_dict = {
        "skus":              ("sku",            "nunique"),
        "stock_actual":      ("stock_actual",   "sum"),
        "demanda_diaria":    ("demanda_diaria", "sum"),
    }
    for h in _HORIZONTES:
        if f"transito_{h}d" in df.columns:
            agg_dict[f"transito_{h}d"] = (f"transito_{h}d", "sum")
        if f"demanda_{h}d" in df.columns:
            agg_dict[f"demanda_{h}d"] = (f"demanda_{h}d", "sum")

    agg = df.groupby(by, as_index=False).agg(**agg_dict)

    # Cobertura a 30 días por defecto (se sobreescribe en render con horizonte)
    col_tr = "transito_30d" if "transito_30d" in agg.columns else "stock_actual"
    agg["cobertura_dias"] = np.where(
        agg["demanda_diaria"] > 0,
        (agg["stock_actual"] + agg[col_tr]) / agg["demanda_diaria"],
        np.nan,
    )
    agg["cobertura_meses"] = (agg["cobertura_dias"] / 30).round(1)
    agg["estado"] = agg["cobertura_dias"].apply(
        lambda x: _clasificar(x) if pd.notna(x) else "SIN DEMANDA"
    )

    # Conteo de SKUs por estado
    conteo = (
        df.groupby(by + ["estado"])["sku"]
        .nunique()
        .reset_index()
        .rename(columns={"sku": "n"})
    )
    pivot = (
        conteo.pivot_table(index=by, columns="estado", values="n", fill_value=0)
        .reset_index()
    )
    pivot.columns.name = None
    for e in _ESTADO_ORDEN:
        if e not in pivot.columns:
            pivot[e] = 0

    estado_cols_exist = [e for e in _ESTADO_ORDEN if e in pivot.columns]
    agg = agg.merge(pivot[by + estado_cols_exist], on=by, how="left")
    for e in estado_cols_exist:
        agg[e] = agg[e].fillna(0).astype(int)

    return agg


def _render_tabla_agg(
    agg: pd.DataFrame,
    dim_col: str,
    horizonte: int,
    extra_cols: list | None = None,
    key_suffix: str = "",
):
    """Renderiza tabla de agregación con colores de estado y botón de descarga."""
    # Recalcular cobertura con horizonte seleccionado
    col_tr = f"transito_{horizonte}d" if f"transito_{horizonte}d" in agg.columns else "transito_30d"
    agg = agg.copy()
    agg["cobertura_dias"] = np.where(
        agg["demanda_diaria"] > 0,
        (agg["stock_actual"] + agg[col_tr]) / agg["demanda_diaria"],
        np.nan,
    )
    agg["cobertura_meses"] = (agg["cobertura_dias"] / 30).round(1)
    agg["estado"] = agg["cobertura_dias"].apply(
        lambda x: _clasificar(x) if pd.notna(x) else "SIN DEMANDA"
    )
    agg = agg.sort_values("cobertura_dias", ascending=True, na_position="last")

    base = [dim_col] + (extra_cols or [])
    metric = [
        "skus", "stock_actual", col_tr,
        f"demanda_{horizonte}d", "cobertura_dias", "cobertura_meses", "estado",
    ]
    estado_cnt = [e for e in _ESTADO_ORDEN if e in agg.columns]
    show_cols = base + [c for c in metric if c in agg.columns] + estado_cnt
    df_show = agg[show_cols].copy()
    df_show["cobertura_dias"] = df_show["cobertura_dias"].round(0)

    col_cfg = {
        "skus":              st.column_config.NumberColumn("SKUs",            format="%d"),
        "stock_actual":      st.column_config.NumberColumn("Stock (u)",       format="%d"),
        col_tr:              st.column_config.NumberColumn(f"Tránsito ≤{horizonte}d", format="%d"),
        f"demanda_{horizonte}d": st.column_config.NumberColumn(f"Demanda {horizonte}d", format="%.0f"),
        "cobertura_dias":    st.column_config.NumberColumn("Cob. Días",       format="%.0f"),
        "cobertura_meses":   st.column_config.NumberColumn("Cob. Meses",      format="%.1f"),
        "estado":            st.column_config.TextColumn("Estado"),
    }
    for e in estado_cnt:
        col_cfg[e] = st.column_config.NumberColumn(e, format="%d", width="small")

    st.dataframe(
        df_show.style.map(_style_estado, subset=["estado"]),
        use_container_width=True,
        height=450,
        column_config=col_cfg,
    )

    csv = df_show.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Descargar CSV",
        data=csv,
        file_name=f"cobertura_{dim_col}_{horizonte}d_{pd.Timestamp.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        key=f"dl_{dim_col}_{horizonte}_{key_suffix}",
    )


# ── Render principal ──────────────────────────────────────────────────
def render():
    st.title("📦 Cobertura por Producto")
    st.caption(
        "Stock actual + tránsito COMEX entrante vs demanda proyectada (Prophet). "
        "Cobertura en días y meses por SKU, marca y categoría. "
        "Datos 100% locales — no requiere Turso."
    )

    with st.spinner("Cargando stock, tránsito y forecast…"):
        df_base = _preparar_datos()

    # ── Filtros ───────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 🔎 Filtros Cobertura")

        horizonte = st.selectbox(
            "Horizonte de tránsito",
            options=_HORIZONTES,
            index=0,
            format_func=lambda x: f"{x} días",
            help="Tránsito que llega dentro de este plazo se suma al stock disponible.",
        )

        marcas_disp = sorted(df_base["marca"].dropna().unique())
        sel_marcas = st.multiselect("Marca", options=marcas_disp, default=[])

        cats_disp = sorted(df_base["categoria_padre"].dropna().unique())
        sel_cats = st.multiselect("Categoría padre", options=cats_disp, default=[])

        sel_estados = st.multiselect(
            "Estado cobertura",
            options=_ESTADO_ORDEN,
            default=[],
            help="Dejar vacío = mostrar todos",
        )

        st.divider()
        solo_con_demanda = st.checkbox("Solo SKUs con demanda proyectada", value=True)
        solo_con_stock   = st.checkbox("Solo SKUs con stock > 0", value=False)

    # ── Aplicar filtros y recalcular cobertura con horizonte ──────────
    dff = _calcular_cobertura(df_base, horizonte)

    if sel_marcas:
        dff = dff[dff["marca"].isin(sel_marcas)]
    if sel_cats:
        dff = dff[dff["categoria_padre"].isin(sel_cats)]
    if sel_estados:
        dff = dff[dff["estado"].isin(sel_estados)]
    if solo_con_demanda:
        dff = dff[dff["demanda_diaria"] > 0]
    if solo_con_stock:
        dff = dff[dff["stock_actual"] > 0]

    if dff.empty:
        st.warning("Sin SKUs con los filtros seleccionados.")
        return

    # ── KPIs Forecast (Prophet) ───────────────────────────────────────
    n_total    = len(dff)
    n_critico  = (dff["estado"] == "CRÍTICO").sum()
    n_urgente  = (dff["estado"] == "URGENTE").sum()
    n_ajustado = (dff["estado"] == "AJUSTADO").sum()
    n_ok       = dff["estado"].isin(["NORMAL", "HOLGADO"]).sum()
    stock_tot  = int(dff["stock_actual"].sum())
    tr_tot     = int(dff[f"transito_{horizonte}d"].sum())

    st.caption("📊 **Cobertura basada en forecast (Prophet)**")
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("SKUs",                    f"{n_total:,}")
    c2.metric("🔴 CRÍTICO <30d",         f"{n_critico:,}")
    c3.metric("🟠 URGENTE <60d",         f"{n_urgente:,}")
    c4.metric("🟡 AJUSTADO <90d",        f"{n_ajustado:,}")
    c5.metric("🟢 NORMAL / HOLGADO",     f"{n_ok:,}")
    c6.metric("Stock actual (u)",        f"{stock_tot:,}")
    c7.metric(f"Tránsito ≤{horizonte}d", f"{tr_tot:,}")

    # ── KPIs Ventas Reales (últimas 4 semanas) ────────────────────────
    n4_critico   = (dff["estado_4sem"] == "CRÍTICO").sum()
    n4_ajustado  = (dff["estado_4sem"] == "AJUSTADO").sum()
    n4_normal    = (dff["estado_4sem"] == "NORMAL").sum()
    n4_sobre     = (dff["estado_4sem"] == "SOBRESTOCK").sum()
    n4_sin_dem   = (dff["estado_4sem"] == "SIN DEMANDA").sum()
    ventas_tot   = int(dff["ventas_4sem"].sum())

    st.caption("🛒 **Cobertura basada en ventas reales (últimas 4 semanas — rolling)**")
    r1, r2, r3, r4, r5, r6, r7 = st.columns(7)
    r1.metric("Con ventas 4sem",       f"{n_total - n4_sin_dem:,}")
    r2.metric("🔴 CRÍTICO  <1m",       f"{n4_critico:,}")
    r3.metric("🟡 AJUSTADO 1–2m",      f"{n4_ajustado:,}")
    r4.metric("🟢 NORMAL   2–4m",      f"{n4_normal:,}")
    r5.metric("🟣 SOBRESTOCK >4m",     f"{n4_sobre:,}")
    r6.metric("Ventas 4sem (u)",        f"{ventas_tot:,}")
    r7.metric("Sin venta reciente",     f"{n4_sin_dem:,}")

    # ── KPIs Cobertura Proyectada (forecast promedio 3 meses) ────────
    nfc_critico  = (dff["estado_fc3m"] == "CRÍTICO").sum()
    nfc_ajustado = (dff["estado_fc3m"] == "AJUSTADO").sum()
    nfc_normal   = (dff["estado_fc3m"] == "NORMAL").sum()
    nfc_sobre    = (dff["estado_fc3m"] == "SOBRESTOCK").sum()
    nfc_sin_dem  = (dff["estado_fc3m"] == "SIN DEMANDA").sum()

    mes_labels = []
    for i, p in enumerate(pd.period_range(_TODAY.to_period("M"), periods=3, freq="M")):
        if i == 0:
            mes_labels.append(p.strftime("%b"))
        else:
            mes_labels.append(p.strftime("%b"))
    meses_str = " + ".join(mes_labels) if mes_labels else "3 meses"

    st.caption(f"🔮 **Cobertura proyectada — forecast promedio próximos 3m** ({meses_str})")
    p1, p2, p3, p4, p5, p6, p7 = st.columns(7)
    p1.metric("Con forecast 3m",      f"{n_total - nfc_sin_dem:,}")
    p2.metric("🔴 CRÍTICO  <1m",      f"{nfc_critico:,}")
    p3.metric("🟡 AJUSTADO 1–2m",     f"{nfc_ajustado:,}")
    p4.metric("🟢 NORMAL   2–4m",     f"{nfc_normal:,}")
    p5.metric("🟣 SOBRESTOCK >4m",    f"{nfc_sobre:,}")
    p6.metric("Sin forecast",         f"{nfc_sin_dem:,}")
    p7.metric("",                     "")

    # ── Gráfico distribución por estado (ventas reales 4sem) ─────────
    estado_counts = (
        dff["estado_4sem"]
        .value_counts()
        .reindex(_ESTADO_ORDEN_4SEM, fill_value=0)
        .reset_index()
    )
    estado_counts.columns = ["Estado", "SKUs"]
    estado_counts = estado_counts[estado_counts["SKUs"] > 0]

    _COLORES = {
        "CRÍTICO":     "#FF4B4B",
        "URGENTE":     "#FF8C00",
        "AJUSTADO":    "#FFD700",
        "NORMAL":      "#52C41A",
        "HOLGADO":     "#1890FF",
        "SIN DEMANDA": "#AAAAAA",
    }

    cols_bar = st.columns(len(estado_counts))
    total = len(dff)
    for i, row in estado_counts.iterrows():
        pct = row["SKUs"] / total * 100 if total > 0 else 0
        cols_bar[i].markdown(
            f"<div style='text-align:center;padding:8px 4px;border-radius:8px;"
            f"background:{_COLORES.get(row['Estado'], '#ccc')};color:{'white' if row['Estado'] != 'AJUSTADO' else '#333'}'>"
            f"<b>{row['Estado']}</b><br>"
            f"<span style='font-size:1.5em;font-weight:bold'>{row['SKUs']}</span><br>"
            f"<span style='font-size:0.85em'>{pct:.0f}% del total</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────
    tab_sku, tab_marca, tab_cat, tab_mx = st.tabs([
        "🔍 Por SKU",
        "🏷️ Por Marca",
        "📂 Por Categoría",
        "📊 Marca × Categoría",
    ])

    # ── TAB 1 — Por SKU ───────────────────────────────────────────────
    with tab_sku:
        col_tr = f"transito_{horizonte}d"
        cols_show = [
            "sku", "producto", "marca",
            "categoria_padre", "categoria_hijo",
            "stock_actual", col_tr, "demanda_diaria",
            f"demanda_{horizonte}d",
            "cobertura_dias", "cobertura_meses", "estado",
            "ventas_4sem", "cobertura_4sem_meses", "estado_4sem",
            "venta_prom_3m", "cobertura_fc3m_meses", "estado_fc3m",
        ]
        cols_show = [c for c in cols_show if c in dff.columns]

        df_sku = dff[cols_show].copy()
        df_sku["cobertura_dias"]      = df_sku["cobertura_dias"].round(0)
        df_sku["cobertura_meses"]     = df_sku["cobertura_meses"].round(1)
        df_sku["demanda_diaria"]      = df_sku["demanda_diaria"].round(1)
        df_sku["cobertura_4sem_meses"]  = df_sku["cobertura_4sem_meses"].round(1)
        if "cobertura_fc3m_meses" in df_sku.columns:
            df_sku["cobertura_fc3m_meses"] = df_sku["cobertura_fc3m_meses"].round(1)
        if "venta_prom_3m" in df_sku.columns:
            df_sku["venta_prom_3m"] = df_sku["venta_prom_3m"].round(1)
        df_sku = df_sku.sort_values("cobertura_4sem_meses", ascending=True, na_position="last")

        st.caption(f"**{len(df_sku):,} SKUs** — ordenados por cobertura real 4sem ascendente (más críticos primero)")

        style_cols = [c for c in ["estado", "estado_4sem", "estado_fc3m"] if c in df_sku.columns]
        st.dataframe(
            df_sku.style.map(_style_estado, subset=style_cols),
            use_container_width=True,
            height=520,
            column_config={
                "sku":                    st.column_config.TextColumn("SKU",              width=130),
                "producto":               st.column_config.TextColumn("Producto",         width=200),
                "marca":                  st.column_config.TextColumn("Marca",            width=90),
                "categoria_padre":        st.column_config.TextColumn("Cat. Padre",       width=110),
                "categoria_hijo":         st.column_config.TextColumn("Cat. Hijo",        width=110),
                "stock_actual":           st.column_config.NumberColumn("Stock (u)",      format="%d"),
                col_tr:                   st.column_config.NumberColumn(f"Tránsito ≤{horizonte}d", format="%d"),
                "demanda_diaria":         st.column_config.NumberColumn("Dem. Diaria",    format="%.1f"),
                f"demanda_{horizonte}d":  st.column_config.NumberColumn(f"Demanda {horizonte}d", format="%.0f"),
                "cobertura_dias":         st.column_config.NumberColumn("Cob. Días (fc)", format="%.0f"),
                "cobertura_meses":        st.column_config.NumberColumn("Cob. Meses (fc)",format="%.1f"),
                "estado":                 st.column_config.TextColumn("Estado (fc)",      width=110),
                "ventas_4sem":            st.column_config.NumberColumn("Ventas 4sem (u)",format="%d"),
                "cobertura_4sem_meses":   st.column_config.NumberColumn("Cob. Meses (real)", format="%.1f"),
                "estado_4sem":            st.column_config.TextColumn("Estado (real)",    width=110),
                "venta_prom_3m":          st.column_config.NumberColumn("Venta Prom 3m (u)", format="%.1f"),
                "cobertura_fc3m_meses":   st.column_config.NumberColumn("Cob. Meses (fc3m)", format="%.1f"),
                "estado_fc3m":            st.column_config.TextColumn("Estado (fc3m)",    width=110),
            },
        )

        csv = df_sku.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Descargar CSV — Por SKU",
            data=csv,
            file_name=f"cobertura_sku_{horizonte}d_{pd.Timestamp.today().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            key="dl_sku",
        )

    # ── TAB 2 — Por Marca ─────────────────────────────────────────────
    with tab_marca:
        st.caption(f"Cobertura agregada por marca · horizonte tránsito: **{horizonte} días**")
        agg_marca = _agrupar(dff, ["marca"])
        _render_tabla_agg(agg_marca, "marca", horizonte, key_suffix="marca")

    # ── TAB 3 — Por Categoría ─────────────────────────────────────────
    with tab_cat:
        sub_padre, sub_hijo = st.tabs(["Categoría Padre", "Categoría Padre → Hijo"])

        with sub_padre:
            st.caption(f"Cobertura agregada por categoría padre · horizonte: **{horizonte} días**")
            agg_cp = _agrupar(dff, ["categoria_padre"])
            _render_tabla_agg(agg_cp, "categoria_padre", horizonte, key_suffix="cp")

        with sub_hijo:
            st.caption(f"Cobertura por categoría padre → hijo · horizonte: **{horizonte} días**")
            agg_ch = _agrupar(dff, ["categoria_padre", "categoria_hijo"])
            _render_tabla_agg(
                agg_ch, "categoria_padre", horizonte,
                extra_cols=["categoria_hijo"], key_suffix="ch"
            )

    # ── TAB 4 — Marca × Categoría ─────────────────────────────────────
    with tab_mx:
        st.caption(f"Cobertura por marca × categoría padre · horizonte: **{horizonte} días**")
        agg_mx = _agrupar(dff, ["marca", "categoria_padre"])
        _render_tabla_agg(
            agg_mx, "marca", horizonte,
            extra_cols=["categoria_padre"], key_suffix="mx"
        )
