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
    cargar_costo_unit_sku,
    cargar_forecast_sku,
    cargar_forecast_manual_mensual,
    cargar_planif_master,
    cargar_planif_stock_baseline,
    cargar_planif_stock_live,
    cargar_planif_transito_live,
    cargar_stock_live_skus,
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
    Tabla maestra por SKU — alineada con Triada Proyectada para migración sin cambios.

    Fuentes (misma jerarquía que Triada):
      Base SKUs : cargar_planif_master()         → planif_master_sku (Turso/parquet)
      Stock     : cargar_planif_stock_live()      → cargar_planif_stock_baseline()
      Ventas    : ventas_historico.parquet         → rolling 42d → tasa mensual
      Vta/Mes   : planif_forecast_manual (PPTO)   → Prophet forecast → histórico
      Tránsito  : cargar_planif_transito_live()   → cargar_transito()
    """

    # ── 1. Base SKUs: planif_master_sku (igual que Triada Proyectada) ────
    df_master_raw = cargar_planif_master()
    if not df_master_raw.empty:
        # cargar_planif_master devuelve cols en lowercase desde Turso
        # o CamelCase desde parquet — normalizamos ambos
        col_map = {
            # parquet CamelCase → estándar
            "Sku": "sku", "SKU": "sku",
            "Descripcion": "producto", "descripcion": "producto",
            "Marca": "marca",
            "Categoria Padre": "categoria_padre", "categoria_padre": "categoria_padre",
            "Categoria Hijo":  "categoria_hijo",  "categoria_hijo":  "categoria_hijo",
        }
        df_master_raw = df_master_raw.rename(columns=col_map)
        for req in ["sku", "producto", "marca", "categoria_padre", "categoria_hijo"]:
            if req not in df_master_raw.columns:
                df_master_raw[req] = ""
        df_master_raw["sku"] = df_master_raw["sku"].astype(str)
        df_meta = df_master_raw[
            df_master_raw["sku"].notna() &
            (df_master_raw["sku"] != "") &
            (df_master_raw["sku"] != "nan") &
            (~df_master_raw["sku"].str.startswith("Total", na=False))
        ][["sku", "producto", "marca", "categoria_padre", "categoria_hijo"]
          ].drop_duplicates("sku").copy()
    else:
        df_meta = pd.DataFrame(columns=["sku", "producto", "marca",
                                         "categoria_padre", "categoria_hijo"])

    # ── 2. Stock — jerarquía de fuentes (más fresco primero) ─────────────
    # 1. data/stock/skus.parquet  (Stock LIVE, actualizado cada 3h por sync_stock.yml)
    # 2. planif_stock_live        (Turso diario)
    # 3. planif_stock_baseline    (snapshot FCST)
    df_stock = cargar_stock_live_skus()    # data/stock/skus.parquet
    if df_stock.empty:
        df_stock_t = cargar_planif_stock_live()
        if not df_stock_t.empty:
            df_stock = df_stock_t[["sku", "stock_total"]].rename(
                columns={"stock_total": "stock_actual"}
            )
        else:
            df_stock_bl = cargar_planif_stock_baseline()
            if not df_stock_bl.empty:
                df_stock_bl = df_stock_bl.rename(columns={
                    "SKU": "sku", "Sku": "sku",
                    "Stock total": "stock_actual", "stock_total": "stock_actual",
                })
                df_stock = df_stock_bl[["sku", "stock_actual"]].copy()
            else:
                df_stock = pd.DataFrame(columns=["sku", "stock_actual"])

    df_stock["sku"]          = df_stock["sku"].astype(str)
    df_stock["stock_actual"] = (
        pd.to_numeric(df_stock["stock_actual"], errors="coerce").fillna(0).clip(lower=0)
    )
    df_stock = df_stock.groupby("sku", as_index=False)["stock_actual"].sum()
    df_meta = df_meta.merge(df_stock, on="sku", how="left")
    df_meta["stock_actual"] = df_meta["stock_actual"].fillna(0)

    # ── 3. Ventas históricas (últimos 5 meses) ────────────────────────────
    path_hist     = DATA_DIR / "historico" / "ventas_historico.parquet"
    _corte_carga  = _TODAY - pd.DateOffset(months=5)
    if path_hist.exists():
        import pyarrow.parquet as pq
        schema_cols = set(pq.ParquetFile(str(path_hist)).schema.names)
        cols_v = [c for c in ["fecha_venta", "sku", "cantidad", "tipo_marca"]
                  if c in schema_cols]
        df_v = pd.read_parquet(path_hist, columns=cols_v)
        df_v["fecha_venta"] = pd.to_datetime(df_v["fecha_venta"], errors="coerce")
        df_v["sku"]         = df_v["sku"].astype(str)
        df_v["cantidad"]    = (
            pd.to_numeric(df_v.get("cantidad", 0), errors="coerce").fillna(0)
        )
        df_v = df_v[
            df_v["sku"].notna() & (df_v["sku"] != "") & (df_v["sku"] != "nan") &
            (df_v["fecha_venta"] >= _corte_carga)
        ]
        # tipo_marca: tomar el valor más reciente por SKU
        if "tipo_marca" in df_v.columns:
            tipo_marca_map = (
                df_v.sort_values("fecha_venta", ascending=False)
                [["sku", "tipo_marca"]].drop_duplicates("sku")
            )
            df_meta = df_meta.merge(tipo_marca_map, on="sku", how="left")
            df_meta["tipo_marca"] = df_meta["tipo_marca"].astype("object").fillna("Sin clasificar")
    else:
        df_v = pd.DataFrame(columns=["fecha_venta", "sku", "cantidad"])

    if "tipo_marca" not in df_meta.columns:
        df_meta["tipo_marca"] = "Sin clasificar"

    # ── 4. Ventas 6 semanas → tasa mensual (total_42d / 42 * 30) ─────────
    corte_6sem = _TODAY - timedelta(days=42)
    df_6sem = df_v[(df_v["fecha_venta"] >= corte_6sem) & (df_v["fecha_venta"] < _TODAY)]
    ventas_6sem_agg = (
        df_6sem.groupby("sku")["cantidad"].sum()
        .reset_index().rename(columns={"cantidad": "_ventas_42d"})
    )
    df_meta = df_meta.merge(ventas_6sem_agg, on="sku", how="left")
    df_meta["_ventas_42d"]    = df_meta["_ventas_42d"].fillna(0).clip(lower=0)
    df_meta["demanda_diaria"] = (df_meta["_ventas_42d"] / 42).clip(lower=0)
    df_meta["ventas_6sem"]    = (df_meta["demanda_diaria"] * 30).round(1)  # u/mes
    for h in _HORIZONTES:
        df_meta[f"demanda_{h}d"] = (df_meta["demanda_diaria"] * h).clip(lower=0)

    # ── 5. Vta/Mes = PPTO manual próximos 3m (mes actual + 2 sig.) ───────
    # Fuente principal: planif_forecast_manual ("Venta PPTO MES" del Excel FCST)
    # Fallback: promedio histórico últimos 3 meses (mientras no exista el PPTO)
    # NO usa Prophet — la proyección es siempre el PPTO de negocio.
    meses_3_obj = pd.period_range(_TODAY.to_period("M"), periods=3, freq="M")

    # 5a. Fallback histórico (hasta que Andrés cargue el FCST Excel a Turso)
    df_v["_mes"] = df_v["fecha_venta"].dt.to_period("M")
    meses_disp   = sorted(df_v["_mes"].dropna().unique())
    ultimos_3    = meses_disp[-3:] if len(meses_disp) >= 3 else meses_disp
    prom3m_hist  = (
        df_v[df_v["_mes"].isin(ultimos_3)]
        .groupby(["sku", "_mes"])["cantidad"].sum().reset_index()
        .groupby("sku")["cantidad"].mean().reset_index()
        .rename(columns={"cantidad": "venta_prom_3m"})
    )
    prom3m_hist["venta_prom_3m"] = prom3m_hist["venta_prom_3m"].clip(lower=0)
    df_meta = df_meta.merge(prom3m_hist, on="sku", how="left")
    df_meta["venta_prom_3m"] = df_meta["venta_prom_3m"].fillna(0)

    # 5b. PPTO manual (sobreescribe fallback cuando el Excel está cargado)
    # Lee directo del parquet para evitar el bug de _is_turso_blocked cuando
    # las credenciales Turso no están seteadas (app de Felipe vs Andrés).
    try:
        _path_ppto = DATA_DIR / "planificacion" / "snapshots" / "planif_forecast_manual.parquet"
        if _path_ppto.exists():
            df_ppto = pd.read_parquet(_path_ppto)
        else:
            df_ppto = cargar_forecast_manual_mensual()   # fallback Turso si no hay parquet
        if not df_ppto.empty:
            df_ppto["sku"]       = df_ppto["sku"].astype(str)
            df_ppto["_mes_per"]  = pd.to_datetime(
                df_ppto["mes"] + "-01", errors="coerce"
            ).dt.to_period("M")
            df_ppto["unidades"]  = (
                pd.to_numeric(df_ppto["unidades"], errors="coerce").fillna(0).clip(lower=0)
            )
            prom_ppto = (
                df_ppto[df_ppto["_mes_per"].isin(meses_3_obj)]
                .groupby(["sku", "_mes_per"])["unidades"].sum().reset_index()
                .groupby("sku")["unidades"].mean().reset_index()
                .rename(columns={"unidades": "_tmp"})
            )
            if not prom_ppto.empty:
                df_meta = df_meta.merge(prom_ppto, on="sku", how="left")
                m = df_meta["_tmp"].notna() & (df_meta["_tmp"] > 0)
                df_meta.loc[m, "venta_prom_3m"] = df_meta.loc[m, "_tmp"]
                df_meta.drop(columns=["_tmp"], inplace=True)
    except Exception:
        pass

    # ── 6. Tránsito live (Turso) → fallback comex/transito.parquet ───────
    df_tr_raw = cargar_planif_transito_live()
    if df_tr_raw.empty:
        df_tr_raw = cargar_transito()
    df_tr = df_tr_raw.copy()
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

    # ── 8. Cobertura basada en ventas reales (rolling 6 sem → tasa mensual) ─
    # ventas_6sem ya es tasa mensual (42d / 42 * 30), se usa directo
    df["cobertura_6sem_meses"] = np.where(
        df["ventas_6sem"] > 0,
        df["stock_actual"] / df["ventas_6sem"],
        np.nan,
    )
    df["estado_6sem"] = df["cobertura_6sem_meses"].apply(_clasificar_meses)

    # ── 9. Cobertura proyectada (forecast próximos 3m, con fallback hist.) ─
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
        width='stretch',
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
        solo_marca_propia = st.checkbox("Solo SKUs marca propia", value=True,
                                          help="Excluye SKUs sin marca asignada (Sin clasificar)")
        solo_con_stock   = st.checkbox("Solo SKUs con stock > 0", value=False)

    # ── Aplicar filtros y recalcular cobertura con horizonte ──────────
    dff = _calcular_cobertura(df_base, horizonte)

    if sel_marcas:
        dff = dff[dff["marca"].isin(sel_marcas)]
    if sel_cats:
        dff = dff[dff["categoria_padre"].isin(sel_cats)]
    if sel_estados:
        dff = dff[dff["estado"].isin(sel_estados)]
    if solo_marca_propia:
        # Usar marca del master directamente (no tipo_marca de ventas_historico)
        # Excluye solo "Sin clasificar" — productos nuevos sin historial siguen siendo propios
        _MARCAS_NO_PROPIAS = {"Sin clasificar", "sin clasificar", ""}
        dff = dff[~dff["marca"].isin(_MARCAS_NO_PROPIAS) & dff["marca"].notna()]
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
    tab_jer, tab_cst, tab_sku, tab_marca, tab_cat, tab_mx = st.tabs([
        "🌳 Jerárquico",
        "💰 A Costo ($M)",
        "🔍 Por SKU",
        "🏷️ Por Marca",
        "📂 Por Categoría",
        "📊 Marca × Categoría",
    ])

    # ── TAB 0 — Jerárquico con proyección mensual integrada ──────────
    with tab_jer:
        try:
            from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
            _aggrid_ok = True
        except ImportError:
            _aggrid_ok = False

        # ── Calcular proyección mensual (6 meses) ─────────────────────
        N_MESES_J = 6
        meses_j   = [_TODAY + pd.DateOffset(months=i) for i in range(N_MESES_J)]
        mes_strs_j  = [m.strftime("%Y-%m") for m in meses_j]
        mes_labels_j = [m.strftime("%b %y") for m in meses_j]

        _path_ppto_j = DATA_DIR / "planificacion" / "snapshots" / "planif_forecast_manual.parquet"
        if _path_ppto_j.exists():
            _df_p = pd.read_parquet(_path_ppto_j)
            _df_p["sku"] = _df_p["sku"].astype(str)
            _df_p["unidades"] = pd.to_numeric(_df_p["unidades"], errors="coerce").fillna(0)
            _ppto_piv = _df_p.pivot_table(index="sku", columns="mes", values="unidades", aggfunc="sum").fillna(0)
        else:
            _ppto_piv = pd.DataFrame()

        # Fuente de tránsito confirmado:
        # 1. planif_transito_live (Turso, diario) → más actualizado
        # 2. planif_transito_baseline (snapshot FCST Excel) → confirmados hasta jun
        # 3. comex/transito (solo si los anteriores están vacíos, filtrando RFQ)
        _df_tr_j = cargar_planif_transito_live()
        if _df_tr_j.empty:
            # Usar baseline del FCST (tránsito confirmado del Excel)
            _path_tr_base = DATA_DIR / "planificacion" / "snapshots" / "planif_transito_baseline.parquet"
            if _path_tr_base.exists():
                _df_tr_base = pd.read_parquet(_path_tr_base)
                # Normalizar nombre de columnas (baseline usa CamelCase)
                _df_tr_base.columns = [c.lower().replace(" ", "_") for c in _df_tr_base.columns]
                if "sku" in _df_tr_base.columns and "cantidad" in _df_tr_base.columns:
                    _df_tr_j = _df_tr_base[["sku", "cantidad", "fecha_eta_bodega"]].copy()
            if _df_tr_j.empty:
                # Último fallback: comex filtrando solo confirmados (excluye RFQ)
                _df_tr_comex = cargar_transito()
                if "status" in _df_tr_comex.columns:
                    _df_tr_comex = _df_tr_comex[~_df_tr_comex["status"].str.contains("RFQ", na=False)]
                _df_tr_j = _df_tr_comex

        _df_tr_j["sku"]      = _df_tr_j["sku"].astype(str)
        _df_tr_j["cantidad"] = pd.to_numeric(_df_tr_j["cantidad"], errors="coerce").fillna(0)
        _df_tr_j["_eta"]     = pd.to_datetime(_df_tr_j["fecha_eta_bodega"], errors="coerce")

        # Regla día 5: ETA 1-5 → mismo mes | ETA 6+ → mes siguiente
        def _mes_transito(fecha):
            if pd.isna(fecha):
                return None
            return (fecha if fecha.day <= 5 else fecha + pd.DateOffset(months=1)).strftime("%Y-%m")

        _df_tr_j["mes_eta"] = _df_tr_j["_eta"].apply(_mes_transito)
        _tr_piv = _df_tr_j.dropna(subset=["mes_eta"]).pivot_table(
            index="sku", columns="mes_eta", values="cantidad", aggfunc="sum"
        ).fillna(0) if not _df_tr_j.empty else pd.DataFrame()
        # Tránsito proyectado FCST (planif_forecast_transito.parquet)
        # Generado por extract_forecast_transito.py desde el Excel FCST.
        # Solo se usa para meses SIN datos en comex (fallback mes a mes).
        _path_tr_fcst = DATA_DIR / "planificacion" / "snapshots" / "planif_forecast_transito.parquet"
        if _path_tr_fcst.exists():
            _df_tr_fcst = pd.read_parquet(_path_tr_fcst)
            _df_tr_fcst["sku"]      = _df_tr_fcst["sku"].astype(str)
            _df_tr_fcst["unidades"] = pd.to_numeric(_df_tr_fcst["unidades"], errors="coerce").fillna(0)
            _tr_fcst_piv = _df_tr_fcst.pivot_table(
                index="sku", columns="mes", values="unidades", aggfunc="sum"
            ).fillna(0)
            # Agregar al pivot principal solo para meses no cubiertos por comex
            for _mc in _tr_fcst_piv.columns:
                if _mc not in _tr_piv.columns:
                    _tr_piv[_mc] = _tr_fcst_piv[_mc]
        # Si no existe el parquet FCST, los meses sin comex quedan en 0
        # → correr extract_forecast_transito.py con el Excel FCST para generarlo

        # Base del df para el grid
        df_jer = dff[["marca", "categoria_padre", "categoria_hijo",
                       "sku", "producto", "stock_actual", "venta_prom_3m"]].copy()
        _stock_v = df_jer["stock_actual"].values.astype(float).copy()

        # Pre-computar PPTO por mes (para promedio rolling 3m) — v2 jun-2026
        _skus_arr = df_jer["sku"].values
        _ppto_by_month = []
        for ms in mes_strs_j:
            if ms in _ppto_piv.columns:
                v = _ppto_piv[ms].reindex(_skus_arr, fill_value=0).values.astype(float)
            else:
                v = np.zeros(len(df_jer))
            _ppto_by_month.append(v)

        for i, (ms, ml) in enumerate(zip(mes_strs_j, mes_labels_j)):
            _venta = _ppto_by_month[i]   # PPTO específico del mes
            _tr    = (_tr_piv[ms].reindex(_skus_arr, fill_value=0).values.astype(float)
                      if ms in _tr_piv.columns else np.zeros(len(df_jer)))

            # Promedio rolling 3 meses: (PPTO_M + PPTO_M+1 + PPTO_M+2) / 3
            v0 = _ppto_by_month[i]
            v1 = _ppto_by_month[i+1] if i+1 < N_MESES_J else v0
            v2 = _ppto_by_month[i+2] if i+2 < N_MESES_J else v1
            _avg_ppto = (v0 + v1 + v2) / 3

            # Stock + Pedido = Stock Inicio + Llegadas
            _sp = _stock_v + _tr

            # Cobertura = (Stock + Llegadas) / promedio 3m PPTO
            _cob = np.where(_avg_ppto > 0, np.round(_sp / _avg_ppto, 1), np.nan)

            df_jer[f"si_{ms}"] = np.round(_stock_v).astype(int)  # Stock Inicial
            df_jer[f"tr_{ms}"] = np.round(_tr).astype(int)       # Llegadas/Tránsito
            df_jer[f"sp_{ms}"] = np.round(_sp).astype(int)       # Stock + Pedido
            df_jer[f"vt_{ms}"] = np.round(_venta, 1)             # Venta PPTO (mes específico)
            df_jer[f"cb_{ms}"] = _cob                            # Cobertura meses

            # Stock siguiente mes = stock - ventas + llegadas
            _stock_v = np.maximum(0.0, _stock_v - _venta + _tr)

        df_jer["_is_total"] = False   # columna auxiliar para estilo total
        df_jer = df_jer.sort_values(
            ["marca", "categoria_padre", "categoria_hijo"],
            ascending=[True, True, True], na_position="last"
        )

        if _aggrid_ok:
            gb = GridOptionsBuilder.from_dataframe(df_jer)
            gb.configure_column("marca",           rowGroup=True, hide=True)
            gb.configure_column("categoria_padre", rowGroup=True, hide=True)
            gb.configure_column("categoria_hijo",  rowGroup=True, hide=True)
            gb.configure_column("sku",             header_name="SKU",     width=140)
            gb.configure_column("producto",        header_name="Producto", width=200)
            gb.configure_column("stock_actual",  header_name="Stock Hoy", width=100, minWidth=90,
                                suppressSizeToFit=True,
                                type=["numericColumn"], enableValue=True, aggFunc="sum",
                                valueFormatter="x!=null?Math.round(x).toLocaleString():''")
            gb.configure_column("venta_prom_3m", header_name="Vta/Mes PPTO", width=110, minWidth=100,
                                suppressSizeToFit=True,
                                type=["numericColumn"], enableValue=True, aggFunc="sum",
                                valueFormatter="x!=null?Math.round(x).toLocaleString():''")

            # Ocultar columnas proyección individuales (se mostrarán como grupos)
            for ms in mes_strs_j:
                for pref in ["si_","vt_","tr_","sp_","cb_"]:
                    gb.configure_column(f"{pref}{ms}", hide=True)

            # Calcular altura exacta: filas visibles (marcas colapsadas) + header + total
            _n_top_rows = df_jer["marca"].dropna().nunique()
            _row_h      = 42   # AG-Grid default row height
            _header_h   = 60   # 2 niveles de header × 30px
            _grid_h     = _n_top_rows * _row_h + _header_h + _row_h + 6  # +1 fila total

            gb.configure_grid_options(
                groupDefaultExpanded=0,
                animateRows=True,
                suppressAggFuncInHeader=True,
                rowHeight=_row_h,
                headerHeight=30,
                groupHeaderHeight=30,
                autoGroupColumnDef={
                    "headerName": "Marca / Categoría",
                    "minWidth": 260,
                    "cellRendererParams": {"suppressCount": False},
                },
            )
            gb.configure_default_column(resizable=True, sortable=True, filter=True)
            gb.configure_column("_is_total", hide=True)   # ocultar columna auxiliar de estilo
            grid_options = gb.build()

            # Agregar grupos de columnas por mes directamente en columnDefs
            cob_formatter = JsCode("function(p){return p.value!=null?parseFloat(p.value).toFixed(1):''}")
            cob_style = JsCode("""
            function(p){
              if(p.value==null)return{};
              const v=parseFloat(p.value);
              if(v<1)  return{background:'#FF4B4B',color:'white'};
              if(v<2)  return{background:'#FFD700',color:'#333'};
              if(v<4)  return{background:'#52C41A',color:'white'};
              return{background:'#722ED1',color:'white'};
            }""")
            num_fmt = "x!=null?Math.round(x).toLocaleString():''"

            for _i_mes, (ms, ml) in enumerate(zip(mes_strs_j, mes_labels_j)):
                _si_header = "Stock Hoy" if _i_mes == 0 else "Stock Ini"
                mes_group = {
                    "headerName": ml,
                    "children": [
                        {"field": f"si_{ms}",  "headerName": _si_header,  "width": 90,  "minWidth": 75,
                         "suppressSizeToFit": True,
                         "type": ["numericColumn"], "enableValue": True, "aggFunc": "sum",
                         "valueFormatter": num_fmt},
                        {"field": f"tr_{ms}",  "headerName": "Llegadas",   "width": 80,  "minWidth": 70,
                         "suppressSizeToFit": True,
                         "type": ["numericColumn"], "enableValue": True, "aggFunc": "sum",
                         "valueFormatter": num_fmt},
                        {"field": f"sp_{ms}",  "headerName": "Stk+Ped",   "width": 80,  "minWidth": 70,
                         "suppressSizeToFit": True,
                         "type": ["numericColumn"], "enableValue": True, "aggFunc": "sum",
                         "valueFormatter": num_fmt},
                        {"field": f"vt_{ms}",  "headerName": "Vta PPTO",  "width": 80,  "minWidth": 70,
                         "suppressSizeToFit": True,
                         "type": ["numericColumn"], "enableValue": True, "aggFunc": "sum",
                         "valueFormatter": num_fmt},
                        {"field": f"cb_{ms}",  "headerName": "Cobert.",    "width": 72,  "minWidth": 62,
                         "suppressSizeToFit": True,
                         "type": ["numericColumn"], "enableValue": True, "aggFunc": "avg",
                         "valueFormatter": cob_formatter, "cellStyle": cob_style},
                    ]
                }
                grid_options["columnDefs"].append(mes_group)

            # ── Fila TOTAL como pinnedBottomRowData ───────────────────
            # pinnedBottomRowData = fila leaf sin expand, siempre al fondo
            # Altura exacta = filas visibles × row_h + header + pinned row
            total_row = {
                "marca": "", "categoria_padre": "", "categoria_hijo": "",
                "sku": "TOTAL GENERAL", "producto": "TOTAL GENERAL",
                "stock_actual": int(df_jer["stock_actual"].sum()),
                "venta_prom_3m": round(df_jer["venta_prom_3m"].sum(), 1),
                "_is_total": True,
            }
            for ms in mes_strs_j:
                si_col, vt_col = f"si_{ms}", f"vt_{ms}"
                tr_col, sp_col, cb_col = f"tr_{ms}", f"sp_{ms}", f"cb_{ms}"
                total_row[si_col] = int(df_jer[si_col].sum()) if si_col in df_jer.columns else 0
                total_row[tr_col] = int(df_jer[tr_col].sum()) if tr_col in df_jer.columns else 0
                total_row[sp_col] = int(df_jer[sp_col].sum()) if sp_col in df_jer.columns else 0
                total_row[vt_col] = round(df_jer[vt_col].sum(), 1) if vt_col in df_jer.columns else 0
                sp_sum = df_jer[sp_col].sum() if sp_col in df_jer.columns else 0
                vt_sum = df_jer[vt_col].sum() if vt_col in df_jer.columns else 0
                total_row[cb_col] = round(sp_sum / vt_sum, 1) if vt_sum > 0 else None

            grid_options["pinnedBottomRowData"] = [total_row]

            # Estilo para la fila total (bold + fondo gris)
            total_row_style = JsCode("""
            function(params) {
                if (params.node && params.node.rowPinned === 'bottom') {
                    return { fontWeight: 'bold', background: '#f0f0f0' };
                }
                return {};
            }""")
            grid_options["getRowStyle"] = total_row_style

            AgGrid(
                df_jer, gridOptions=grid_options,
                height=_grid_h,
                fit_columns_on_grid_load=False,
                allow_unsafe_jscode=True,
                theme="streamlit",
                key="aggrid_jerarquico",
            )
        else:
            st.info("streamlit-aggrid no disponible. Recargá la página.")
            st.dataframe(df_jer[["sku","producto","marca","stock_actual"]], width='stretch', height=400)

    # ── TAB 1 — A Costo ($M) — espejo exacto del Jerárquico con valores CIF ──
    with tab_cst:
        try:
            from st_aggrid import AgGrid, GridOptionsBuilder, JsCode as JsCode2
            _aggrid_cst_ok = True
        except ImportError:
            _aggrid_cst_ok = False

        _costo_map = cargar_costo_unit_sku()

        try:
            _df_cst = df_jer.copy()
        except NameError:
            st.warning("Cargá primero el tab Jerárquico para inicializar los datos.")
            _df_cst = pd.DataFrame()

        if not _df_cst.empty:
            _M  = 1_000_000
            _cu = _df_cst['sku'].map(_costo_map).fillna(0).values

            # Construir DataFrame MÍNIMO — solo columnas necesarias (igual que df_jer en Jerárquico)
            # Esto evita que columnas extra interfieran con la agregación de AG-Grid
            _id_cols = ['marca','categoria_padre','categoria_hijo','sku','producto','_is_total']
            _cst_data = {c: _df_cst[c].values for c in _id_cols if c in _df_cst.columns}
            # Usar _df_cst como fuente (tiene todas las columnas de df_jer)
            _cst_data['stock_cst_m']      = np.round(_df_cst['stock_actual'].values  * _cu / _M, 2)
            _cst_data['venta_prom_cst_m'] = np.round(_df_cst['venta_prom_3m'].values * _cu / _M, 2)
            for _ms in mes_strs_j:
                if f'si_{_ms}' in _df_cst.columns:
                    _cst_data[f'csi_{_ms}'] = np.round(_df_cst[f'si_{_ms}'].values * _cu / _M, 2)
                    _cst_data[f'ctr_{_ms}'] = np.round(_df_cst[f'tr_{_ms}'].values * _cu / _M, 2)
                    _cst_data[f'csp_{_ms}'] = np.round(_df_cst[f'sp_{_ms}'].values * _cu / _M, 2)
                    _cst_data[f'cvt_{_ms}'] = np.round(_df_cst[f'vt_{_ms}'].values * _cu / _M, 2)
                    _cst_data[f'cb_{_ms}']  = _df_cst[f'cb_{_ms}'].values
            _df_grid_cst = pd.DataFrame(_cst_data)  # DataFrame mínimo para AG-Grid

            if _aggrid_cst_ok:
                _mfmt2 = "x!=null?'$'+x.toLocaleString('es-CL',{minimumFractionDigits:1,maximumFractionDigits:1})+'M':''"

                gb2 = GridOptionsBuilder.from_dataframe(_df_grid_cst)
                gb2.configure_default_column(resizable=True, sortable=True, filter=True)

                # Columnas de identidad — misma estructura que versión funcional
                gb2.configure_column("marca",          header_name="Marca / Categoría", rowGroup=True, hide=True, pinned="left")
                gb2.configure_column("categoria_padre",header_name="Cat. Padre",         rowGroup=True, hide=True)
                gb2.configure_column("categoria_hijo", header_name="Cat. Hijo",          rowGroup=True, hide=True)
                gb2.configure_column("sku",            header_name="SKU",     width=140)
                gb2.configure_column("producto",       header_name="Producto", width=200)

                # Columnas fijas a costo
                gb2.configure_column("stock_cst_m",      header_name="Stock Hoy ($M)", width=115, minWidth=100,
                                     suppressSizeToFit=True,
                                     type=["numericColumn"], enableValue=True, aggFunc="sum",
                                     valueFormatter=_mfmt2)
                gb2.configure_column("venta_prom_cst_m", header_name="Vta/Mes ($M)",   width=105, minWidth=95,
                                     suppressSizeToFit=True,
                                     type=["numericColumn"], enableValue=True, aggFunc="sum",
                                     valueFormatter=_mfmt2)

                # Ocultar proyecciones individuales (se muestran en grupos)
                for _ms in mes_strs_j:
                    for _pref in ["csi_","ctr_","csp_","cvt_","si_","tr_","sp_","vt_","cb_"]:
                        gb2.configure_column(f"{_pref}{_ms}", hide=True)

                gb2.configure_column("_is_total",  hide=True)
                gb2.configure_column("costo_unit", hide=True)
                _go2 = gb2.build()

                # Opciones de agrupación — seteadas en _go2 post-build (igual que versión funcional)
                # autoGroupColumnDef pinned=left → Marca/Cat.Padre/Cat.Hijo quedan a la izquierda de SKU/Produto
                _go2["autoGroupColumnDef"]      = {"pinned": "left", "minWidth": 160, "cellRendererParams": {"suppressCount": False}}
                _go2["groupDisplayType"]        = "multipleColumns"
                _go2["groupDefaultExpanded"]    = 0
                _go2["suppressAggFuncInHeader"] = True
                _go2["rowHeight"]               = 28
                _go2["headerHeight"]            = 32
                _go2["groupHeaderHeight"]       = 28

                # Altura del grid
                _n_top_cst  = _df_grid_cst['marca'].dropna().nunique()
                _height_cst = min(max(_n_top_cst * 28 + 60 + 28 + 20, 300), 700)

                # Formatters de cobertura (iguales que Jerárquico)
                _cob_fmt2 = JsCode2("function(p){if(p.value==null||isNaN(p.value))return '';return p.value.toFixed(1)+'m';}")
                _cob_sty2 = JsCode2("""
                function(p){
                  var v=p.value;
                  if(v==null||isNaN(v)) return{};
                  if(v<1)  return{background:'#FF4B4B',color:'white'};
                  if(v<2)  return{background:'#FFD700',color:'#333'};
                  if(v<4)  return{background:'#52C41A',color:'white'};
                  return{background:'#722ED1',color:'white'};
                }""")

                # NO filtramos columnDefs — dejamos todo del build intacto
                # para preservar la agregación de group rows (stock_cst_m, venta_prom_cst_m)
                # Los meses se agregan como grupos abajo; el duplicate-field no afecta aggregation

                # Grupos de meses — misma estructura que Jerárquico
                for _i_cst, (_ms2, _ml2) in enumerate(zip(mes_strs_j, mes_labels_j)):
                    if f'csi_{_ms2}' not in _df_cst.columns:
                        continue
                    _csi_hdr = "Stock Hoy ($M)" if _i_cst == 0 else "Stk Ini ($M)"
                    _go2["columnDefs"].append({
                        "headerName": _ml2,
                        "children": [
                            {"field": f"csi_{_ms2}", "headerName": _csi_hdr,      "width": 110, "minWidth": 90,
                             "suppressSizeToFit": True,
                             "type": ["numericColumn"], "enableValue": True, "aggFunc": "sum",
                             "valueFormatter": _mfmt2},
                            {"field": f"ctr_{_ms2}", "headerName": "Llegadas ($M)", "width": 95, "minWidth": 80,
                             "suppressSizeToFit": True,
                             "type": ["numericColumn"], "enableValue": True, "aggFunc": "sum",
                             "valueFormatter": _mfmt2},
                            {"field": f"csp_{_ms2}", "headerName": "Stk+Ped ($M)", "width": 95, "minWidth": 80,
                             "suppressSizeToFit": True,
                             "type": ["numericColumn"], "enableValue": True, "aggFunc": "sum",
                             "valueFormatter": _mfmt2},
                            {"field": f"cvt_{_ms2}", "headerName": "Vta PPTO ($M)", "width": 100, "minWidth": 85,
                             "suppressSizeToFit": True,
                             "type": ["numericColumn"], "enableValue": True, "aggFunc": "sum",
                             "valueFormatter": _mfmt2},
                            {"field": f"cb_{_ms2}",  "headerName": "Cobert.",       "width": 72,  "minWidth": 62,
                             "suppressSizeToFit": True,
                             "type": ["numericColumn"], "enableValue": True, "aggFunc": "avg",
                             "valueFormatter": _cob_fmt2, "cellStyle": _cob_sty2},
                        ]
                    })

                # Fila TOTAL — misma estructura que Jerárquico
                _total_cst = {
                    "marca": "", "categoria_padre": "", "categoria_hijo": "",
                    "sku": "TOTAL GENERAL", "producto": "TOTAL GENERAL",
                    "stock_cst_m":      round(_df_grid_cst["stock_cst_m"].sum(), 2),
                    "venta_prom_cst_m": round(_df_grid_cst["venta_prom_cst_m"].sum(), 2),
                    "_is_total": True,
                }
                for _ms2 in mes_strs_j:
                    for _pref2 in ["csi_", "ctr_", "csp_", "cvt_"]:
                        _c2 = f"{_pref2}{_ms2}"
                        _total_cst[_c2] = round(_df_grid_cst[_c2].sum(), 2) if _c2 in _df_grid_cst.columns else 0
                    _cvt2 = f"cvt_{_ms2}"; _csp2 = f"csp_{_ms2}"; _cb2 = f"cb_{_ms2}"
                    _vs = _df_grid_cst[_cvt2].sum() if _cvt2 in _df_cst.columns else 0
                    _ss = _df_grid_cst[_csp2].sum() if _csp2 in _df_cst.columns else 0
                    _total_cst[_cb2] = round(_ss / _vs, 1) if _vs > 0 else None

                _go2["pinnedBottomRowData"] = [_total_cst]
                _go2["getRowStyle"] = JsCode2("""
                function(params){
                    if(params.node && params.node.rowPinned==='bottom')
                        return{fontWeight:'bold',background:'#f0f0f0'};
                    return{};
                }""")

                AgGrid(
                    _df_grid_cst,
                    gridOptions=_go2,
                    height=_height_cst,
                    fit_columns_on_grid_load=False,
                    allow_unsafe_jscode=True,
                    theme="streamlit",
                    key="aggrid_costo",
                )
            else:
                st.info("streamlit-aggrid no disponible.")
                st.dataframe(_df_grid_cst[["sku", "producto", "marca", "stock_cst_m"]])

    # ── TAB 2 — Por SKU ───────────────────────────────────────────────
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
            width='stretch',
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
                "ventas_6sem":            st.column_config.NumberColumn("Vta/Mes 6sem",  format="%.1f"),
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
