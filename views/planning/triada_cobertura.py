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
    DATA_DIR,
    cargar_stock_diario,
    cargar_transito,
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
    Tabla maestra por SKU.
    Base: ventas_historico (todos los SKUs activos, sin depender de Prophet).
    Demanda calculada desde ventas reales (no forecast Prophet).

    Columnas principales:
      sku, producto, marca, categoria_padre, categoria_hijo,
      stock_actual,
      transito_30d / 60d / 90d / 180d
      ventas_6sem, demanda_diaria,
      demanda_30d / 60d / 90d / 180d  (extrapolado desde demanda diaria)
      venta_prom_3m                   (promedio mensual ultimos 3 meses disponibles)
      cobertura_6sem_meses, estado_6sem
      cobertura_fc3m_meses, estado_fc3m
    """

    # ── 1. Base: todos los SKUs con historial de ventas ───────────────
    # Cargamos solo los últimos 5 meses para limitar RAM en Streamlit Cloud.
    # Es suficiente para ventas_6sem (42 días) + prom_3m (3 meses).
    path_hist = DATA_DIR / "historico" / "ventas_historico.parquet"
    _corte_carga = _TODAY - pd.DateOffset(months=5)
    if path_hist.exists():
        import pyarrow.parquet as pq
        schema_cols = set(pq.ParquetFile(str(path_hist)).schema.names)
        cols_deseadas = ["fecha_venta", "sku", "producto", "marca",
                         "categoria_padre", "categoria_hijo", "categoria_comercial",
                         "cantidad"]
        cols = [c for c in cols_deseadas if c in schema_cols]
        df_v_full = pd.read_parquet(path_hist, columns=cols)
        df_v_full["fecha_venta"] = pd.to_datetime(df_v_full["fecha_venta"], errors="coerce")
        df_v_full["sku"]         = df_v_full["sku"].astype(str)
        df_v_full["cantidad"]    = pd.to_numeric(df_v_full.get("cantidad", 0), errors="coerce").fillna(0)
        df_v_full = df_v_full[df_v_full["sku"].notna() & (df_v_full["sku"] != "") & (df_v_full["sku"] != "nan")]
        # Metadatos desde historial completo (para no perder productos con venta hace >5m)
        df_meta_full = (
            df_v_full.sort_values("fecha_venta", ascending=False)
            [[c for c in ["sku", "producto", "marca", "categoria_padre",
                          "categoria_hijo", "categoria_comercial"] if c in df_v_full.columns]]
            .drop_duplicates("sku").copy()
        )
        # Ventas y demanda solo de los últimos 5 meses
        df_v = df_v_full[df_v_full["fecha_venta"] >= _corte_carga].copy()
    else:
        df_v_full = pd.DataFrame(columns=["fecha_venta", "sku", "producto", "marca",
                                           "categoria_padre", "categoria_hijo", "cantidad"])
        df_meta_full = df_v_full.copy()
        df_v = df_v_full.copy()

    # ── 2. Metadata por SKU (registro más reciente del historial completo) ─
    df_meta = df_meta_full.copy()

    # ── 3. Ventas 6 semanas (42 días) → demanda diaria y por horizonte ─
    corte_6sem = _TODAY - timedelta(days=42)
    df_6sem = df_v[(df_v["fecha_venta"] >= corte_6sem) & (df_v["fecha_venta"] < _TODAY)]

    ventas_6sem_agg = (
        df_6sem.groupby("sku")["cantidad"]
        .sum()
        .reset_index()
        .rename(columns={"cantidad": "ventas_6sem"})
    )
    df_meta = df_meta.merge(ventas_6sem_agg, on="sku", how="left")
    df_meta["ventas_6sem"]    = df_meta["ventas_6sem"].fillna(0).clip(lower=0)
    df_meta["demanda_diaria"] = (df_meta["ventas_6sem"] / 42).clip(lower=0)

    for h in _HORIZONTES:
        df_meta[f"demanda_{h}d"] = (df_meta["demanda_diaria"] * h).clip(lower=0)

    # ── 4. Promedio mensual — últimos 3 meses con datos disponibles ───
    df_v_copy = df_v.copy()
    df_v_copy["_mes"] = df_v_copy["fecha_venta"].dt.to_period("M")
    meses_disp = sorted(df_v_copy["_mes"].dropna().unique())
    ultimos_3 = meses_disp[-3:] if len(meses_disp) >= 3 else meses_disp
    df_3m = df_v_copy[df_v_copy["_mes"].isin(ultimos_3)]
    prom3m = (
        df_3m.groupby(["sku", "_mes"])["cantidad"]
        .sum()
        .reset_index()
        .groupby("sku")["cantidad"]
        .mean()
        .reset_index()
        .rename(columns={"cantidad": "venta_prom_3m"})
    )
    prom3m["venta_prom_3m"] = prom3m["venta_prom_3m"].clip(lower=0)
    df_meta = df_meta.merge(prom3m, on="sku", how="left")
    df_meta["venta_prom_3m"] = df_meta["venta_prom_3m"].fillna(0)

    # ── 5. Stock actual ───────────────────────────────────────────────
    # NOTA: stock_diario usa IDs Odoo (int) — no hace match con códigos de ventas.
    # Stock aparecerá en 0 hasta que extract_stock_historico.py sea corregido.
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
    df_meta = df_meta.merge(df_stock, on="sku", how="left")
    df_meta["stock_actual"] = df_meta["stock_actual"].fillna(0)

    # ── 6. Tránsito por horizonte ─────────────────────────────────────
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

    df_meta = df_meta.merge(df_transito, on="sku", how="left")
    for h in _HORIZONTES:
        col = f"transito_{h}d"
        if col in df_meta.columns:
            df_meta[col] = df_meta[col].fillna(0)

    df = df_meta.copy()

    # ── 7. Textos vacíos ──────────────────────────────────────────────
    for c in ["categoria_hijo", "categoria_comercial", "marca", "categoria_padre"]:
        if c in df.columns:
            df[c] = df[c].fillna("Sin clasificar").replace("", "Sin clasificar")

    # ── 8. Cobertura basada en ventas reales (rolling 6 semanas) ─────
    # Convertir ventas_6sem a tasa mensual: / 42 días × 30 días/mes
    demanda_mensual_6sem = (df["ventas_6sem"] / 42 * 30).clip(lower=0)
    df["cobertura_6sem_meses"] = np.where(
        demanda_mensual_6sem > 0,
        df["stock_actual"] / demanda_mensual_6sem,
        np.nan,
    )
    df["estado_6sem"] = df["cobertura_6sem_meses"].apply(_clasificar_meses)

    # ── 9. Cobertura proyectada (promedio mensual 3 meses históricos) ─
    df["cobertura_fc3m_meses"] = np.where(
        df["venta_prom_3m"] > 0,
        df["stock_actual"] / df["venta_prom_3m"],
        np.nan,
    )
    df["estado_fc3m"] = df["cobertura_fc3m_meses"].apply(_clasificar_meses)

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

    # ── KPIs Cobertura Proyectada (forecast promedio 3 meses) ────────
    n_total    = len(dff)
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

    # ── Gráfico distribución por estado (forecast promedio 3m) ───────
    estado_counts = (
        dff["estado_fc3m"]
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
    for i, (_, row) in enumerate(estado_counts.iterrows()):
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
            "ventas_6sem", "cobertura_6sem_meses", "estado_6sem",
            "venta_prom_3m", "cobertura_fc3m_meses", "estado_fc3m",
        ]
        cols_show = [c for c in cols_show if c in dff.columns]

        df_sku = dff[cols_show].copy()
        df_sku["cobertura_dias"]      = df_sku["cobertura_dias"].round(0)
        df_sku["cobertura_meses"]     = df_sku["cobertura_meses"].round(1)
        df_sku["demanda_diaria"]      = df_sku["demanda_diaria"].round(1)
        if "cobertura_6sem_meses" in df_sku.columns:
            df_sku["cobertura_6sem_meses"]  = df_sku["cobertura_6sem_meses"].round(1)
        if "cobertura_fc3m_meses" in df_sku.columns:
            df_sku["cobertura_fc3m_meses"] = df_sku["cobertura_fc3m_meses"].round(1)
        if "venta_prom_3m" in df_sku.columns:
            df_sku["venta_prom_3m"] = df_sku["venta_prom_3m"].round(1)
        df_sku = df_sku.sort_values("cobertura_fc3m_meses", ascending=True, na_position="last")

        st.caption(f"**{len(df_sku):,} SKUs** — ordenados por cobertura forecast 3m ascendente (más críticos primero)")

        style_cols = [c for c in ["estado", "estado_6sem", "estado_fc3m"] if c in df_sku.columns]
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
                "ventas_6sem":            st.column_config.NumberColumn("Ventas 6sem (u)",format="%d"),
                "cobertura_6sem_meses":   st.column_config.NumberColumn("Cob. Meses (6sem)", format="%.1f"),
                "estado_6sem":            st.column_config.TextColumn("Estado (6sem)",    width=110),
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
