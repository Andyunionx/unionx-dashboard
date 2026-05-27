"""
Vista Bonos — Bodega (Logística + Coordinador Pedidos).

Dos equipos, dos fórmulas:

LOGÍSTICA  (3 pers × $60.000 = $180.000 pozo):
  Bono = Base × (OTIF×40% + Productividad×50% + Espíritu×10%)
  Productividad: líneas outgoing WMS / N personas vs meta

COORDINADOR PEDIDOS  (3 pers × $100.000 = $300.000 pozo):
  Bono = Base × (OTIF×30% + Productividad×30% + ErrorDespacho×30% + Espíritu×10%)
  Productividad: pedidos outgoing WMS / N personas vs meta

KPIs:
  OTIF            → auto desde Drive (OTIF Empresa M-1), igual que Facturación
  Productividad   → auto desde parquet WMS (volumen_inventario_hist.parquet)
  Error Despacho  → manual 0-100% (jefe) — solo Coordinador
  Espíritu MLL    → manual 0-100% (jefe)

Ratio pagable:
  OTIF + Productividad  → 90-100% (bajo 90% paga 0, lineal, cap 100%)
  Error Despacho        → 0-100% directo (escala completa)
  Espíritu MLL          → 0-100% directo
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WMS_PARQUET = PROJECT_ROOT / "data" / "operaciones" / "volumen_inventario_hist.parquet"

# ── Fórmulas oficiales ────────────────────────────────────────────────────────

LOGISTICA = {
    "key": "logistica",
    "label": "🏭 Logística",
    "n_default": 3,
    "bono_default": 60_000,
    "otif_peso": 0.40,
    "prod_peso": 0.50,
    "error_peso": None,
    "esp_peso": 0.10,
    "prod_metric": "lineas",      # sum(n_lineas) outgoing / N personas
    "meta_prod_default": 2_000,   # lineas/persona/mes (ajustable)
}

COORDINADOR = {
    "key": "coordinador",
    "label": "📋 Coordinador Pedidos",
    "n_default": 3,
    "bono_default": 100_000,
    "otif_peso": 0.30,
    "prod_peso": 0.30,
    "error_peso": 0.30,
    "esp_peso": 0.10,
    "prod_metric": "pedidos",     # count(pickings) outgoing / N personas
    "meta_prod_default": 200,     # pedidos/persona/mes (ajustable)
}

OTIF_OBJETIVO = 98.0
PROD_OBJETIVO = 90.0
RATIO_MIN = 90.0
RATIO_MAX = 100.0


# ── Helpers numéricos ─────────────────────────────────────────────────────────

def _safe_float(v, default: float = 0.0) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v, default: int = 0) -> int:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _factor_ratio(valor_pct, ratio_min=RATIO_MIN, ratio_max=RATIO_MAX) -> float:
    """Convierte KPI% a factor 0-1. Piso ratio_min, techo ratio_max."""
    if valor_pct is None or pd.isna(valor_pct):
        return 0.0
    try:
        v = float(valor_pct)
    except (TypeError, ValueError):
        return 0.0
    if v < ratio_min:
        return 0.0
    if v >= ratio_max:
        return 1.0
    return (v - ratio_min) / (ratio_max - ratio_min)


def _factor_directo(valor_pct) -> float:
    """Factor 0-1 proporcional directo (escala completa 0-100%)."""
    if valor_pct is None or pd.isna(valor_pct):
        return 0.0
    try:
        return max(0.0, min(1.0, float(valor_pct) / 100.0))
    except (TypeError, ValueError):
        return 0.0


def _fmt_num(v) -> str:
    if v is None or pd.isna(v) or v == 0:
        return "—"
    return f"${abs(v):,.0f}".replace(",", ".")


# ── Carga datos WMS ───────────────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def _wms_mensual() -> pd.DataFrame:
    """Devuelve DataFrame con lineas + pedidos outgoing por (year, month)."""
    if not WMS_PARQUET.exists():
        return pd.DataFrame(columns=["year", "month", "lineas", "pedidos"])
    df = pd.read_parquet(WMS_PARQUET)
    df["fecha_done"] = pd.to_datetime(df["fecha_done"], errors="coerce")
    df = df[df["picking_type_code"] == "outgoing"].dropna(subset=["fecha_done"])
    df["year"] = df["fecha_done"].dt.year
    df["month"] = df["fecha_done"].dt.month
    agg = df.groupby(["year", "month"], as_index=False).agg(
        lineas=("n_lineas", "sum"),
        pedidos=("picking_id", "nunique"),
    )
    return agg


def _prod_real(equipo_cfg: dict, year: int, month: int) -> float | None:
    """Retorna el KPI de productividad real del mes (métrica cruda, no %)."""
    df = _wms_mensual()
    if df.empty:
        return None
    row = df[(df["year"] == year) & (df["month"] == month)]
    if row.empty:
        return None
    return float(row[equipo_cfg["prod_metric"]].iloc[0])


# ── Carga/guarda config Turso ─────────────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def _load_config() -> pd.DataFrame:
    cols = ["mes", "equipo", "n_personas", "bono_persona_clp", "base_clp",
            "otif_pct", "meta_prod", "error_despacho_pct", "espiritu_mll_pct",
            "bono_pagado_real_clp", "observacion"]
    try:
        from views.alertas_helper import _query
        _query("""CREATE TABLE IF NOT EXISTS bonos_bodega_config (
            mes TEXT,
            equipo TEXT,
            n_personas INTEGER,
            bono_persona_clp REAL,
            base_clp REAL,
            otif_pct REAL,
            meta_prod REAL,
            error_despacho_pct REAL,
            espiritu_mll_pct REAL,
            bono_pagado_real_clp REAL,
            observacion TEXT,
            actualizado_en TEXT,
            PRIMARY KEY (mes, equipo)
        )""")
        for col, tipo in [("meta_prod", "REAL"), ("error_despacho_pct", "REAL")]:
            try:
                _query(f"ALTER TABLE bonos_bodega_config ADD COLUMN {col} {tipo}")
            except Exception:
                pass
        res = _query("""SELECT mes, equipo, n_personas, bono_persona_clp, base_clp,
                               otif_pct, meta_prod, error_despacho_pct, espiritu_mll_pct,
                               bono_pagado_real_clp, observacion
                        FROM bonos_bodega_config ORDER BY mes, equipo""")
        if not res or not res.get("rows"):
            return pd.DataFrame(columns=cols)
        rows = []
        for r in res["rows"]:
            def _v(i):
                c = r[i]
                return c.get("value") if c.get("type") != "null" else None
            rows.append({
                "mes": _v(0), "equipo": _v(1),
                "n_personas": int(_v(2)) if _v(2) else None,
                "bono_persona_clp": float(_v(3)) if _v(3) else None,
                "base_clp": float(_v(4) or 0),
                "otif_pct": float(_v(5)) if _v(5) is not None else None,
                "meta_prod": float(_v(6)) if _v(6) else None,
                "error_despacho_pct": float(_v(7)) if _v(7) is not None else None,
                "espiritu_mll_pct": float(_v(8)) if _v(8) is not None else None,
                "bono_pagado_real_clp": float(_v(9)) if _v(9) else None,
                "observacion": _v(10) or "",
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=cols)


def _save_config(mes: str, equipo: str, n_personas: int, bono_persona_clp: float,
                  otif_pct: float | None, meta_prod: float | None,
                  error_despacho_pct: float | None, espiritu_mll_pct: float | None,
                  bono_pagado_real_clp: float | None, observacion: str = "") -> bool:
    base_clp = n_personas * bono_persona_clp
    try:
        from views.alertas_helper import _query
        _query("""INSERT INTO bonos_bodega_config
                    (mes, equipo, n_personas, bono_persona_clp, base_clp,
                     otif_pct, meta_prod, error_despacho_pct, espiritu_mll_pct,
                     bono_pagado_real_clp, observacion, actualizado_en)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(mes, equipo) DO UPDATE SET
                    n_personas=excluded.n_personas,
                    bono_persona_clp=excluded.bono_persona_clp,
                    base_clp=excluded.base_clp,
                    otif_pct=excluded.otif_pct,
                    meta_prod=excluded.meta_prod,
                    error_despacho_pct=excluded.error_despacho_pct,
                    espiritu_mll_pct=excluded.espiritu_mll_pct,
                    bono_pagado_real_clp=excluded.bono_pagado_real_clp,
                    observacion=excluded.observacion,
                    actualizado_en=excluded.actualizado_en""",
               [mes, equipo, int(n_personas), float(bono_persona_clp), float(base_clp),
                float(otif_pct) if otif_pct is not None else None,
                float(meta_prod) if meta_prod else None,
                float(error_despacho_pct) if error_despacho_pct is not None else None,
                float(espiritu_mll_pct) if espiritu_mll_pct is not None else None,
                float(bono_pagado_real_clp) if bono_pagado_real_clp else None,
                observacion, datetime.now().isoformat()])
        return True
    except Exception as e:
        st.error(f"Error guardando config: {e}")
        return False


# ── OTIF automático desde Drive ───────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def _otif_drive(mes_iso: str) -> float | None:
    try:
        from views._ops_otif_drive import kpi_otif_resumen
        r = kpi_otif_resumen(mes=mes_iso)
        if r.get("error") or r.get("otif_empresa_pct") is None:
            return None
        return float(r["otif_empresa_pct"]) * 100
    except Exception:
        return None


# ── Cálculo bono ──────────────────────────────────────────────────────────────

def _calcular_bono(equipo_cfg: dict, base: float,
                    otif_pct: float, prod_pct: float,
                    error_pct: float | None, espiritu_pct: float) -> dict:
    f_otif = _factor_ratio(otif_pct)
    f_prod = _factor_ratio(prod_pct)
    f_error = _factor_directo(error_pct) if error_pct is not None else None
    f_esp = _factor_directo(espiritu_pct)

    factor = (f_otif * equipo_cfg["otif_peso"]
              + f_prod * equipo_cfg["prod_peso"]
              + f_esp * equipo_cfg["esp_peso"])
    if equipo_cfg["error_peso"] is not None and f_error is not None:
        factor += f_error * equipo_cfg["error_peso"]

    return {
        "otif_pct": otif_pct, "f_otif": f_otif,
        "aporta_otif": base * f_otif * equipo_cfg["otif_peso"],
        "prod_pct": prod_pct, "f_prod": f_prod,
        "aporta_prod": base * f_prod * equipo_cfg["prod_peso"],
        "error_pct": error_pct, "f_error": f_error,
        "aporta_error": (base * f_error * equipo_cfg["error_peso"]
                          if f_error is not None and equipo_cfg["error_peso"] else 0),
        "espiritu_pct": espiritu_pct, "f_esp": f_esp,
        "aporta_esp": base * f_esp * equipo_cfg["esp_peso"],
        "factor_total": factor,
        "bono_devengado": round(base * factor, -2),
    }


# ── Render por equipo ─────────────────────────────────────────────────────────

def _render_equipo(equipo_cfg: dict, df_cfg: pd.DataFrame, hoy: date):
    tab_res, tab_carga, tab_hist = st.tabs(["📊 Resumen", "💵 Carga Bonos", "📈 Historial"])

    with tab_res:
        _render_resumen(equipo_cfg, df_cfg, hoy)
    with tab_carga:
        _render_carga(equipo_cfg, df_cfg, hoy)
    with tab_hist:
        _render_historial(equipo_cfg, df_cfg)


def _render_resumen(equipo_cfg: dict, df_cfg: pd.DataFrame, hoy: date):
    key = equipo_cfg["key"]
    df_e = df_cfg[df_cfg["equipo"] == key] if not df_cfg.empty else pd.DataFrame()

    c1, c2 = st.columns([1, 1])
    with c1:
        anio_sel = st.selectbox("Año", [hoy.year - 1, hoy.year], index=1,
                                 key=f"res_anio_{key}")
    with c2:
        mes_sel = st.selectbox("Mes", list(range(1, 13)), index=hoy.month - 1,
                                key=f"res_mes_{key}")

    if st.button("🔄 Refrescar", key=f"res_ref_{key}"):
        st.cache_data.clear()
        st.rerun()

    mes_key = f"{anio_sel}-{mes_sel:02d}"
    cfg_row = {}
    if not df_e.empty:
        r = df_e[df_e["mes"] == mes_key]
        if not r.empty:
            cfg_row = r.iloc[0].to_dict()

    n_personas = _safe_int(cfg_row.get("n_personas"), equipo_cfg["n_default"])
    bono_persona = _safe_float(cfg_row.get("bono_persona_clp"), equipo_cfg["bono_default"])
    base_pozo = _safe_float(cfg_row.get("base_clp"), 0)
    if base_pozo == 0:
        base_pozo = n_personas * bono_persona

    meta_prod_cfg = _safe_float(cfg_row.get("meta_prod"), equipo_cfg["meta_prod_default"])
    otif_manual = cfg_row.get("otif_pct")
    error_manual = cfg_row.get("error_despacho_pct")
    espiritu_manual = cfg_row.get("espiritu_mll_pct")

    # Productividad real desde WMS
    prod_real_raw = _prod_real(equipo_cfg, anio_sel, mes_sel)
    if prod_real_raw is not None and n_personas > 0:
        prod_real_pp = prod_real_raw / n_personas
        prod_pct = (prod_real_pp / meta_prod_cfg * 100) if meta_prod_cfg > 0 else 0.0
    else:
        prod_real_pp = None
        prod_pct = 0.0

    # OTIF M-1
    m1_year = anio_sel if mes_sel > 1 else anio_sel - 1
    m1_month = mes_sel - 1 if mes_sel > 1 else 12
    m1_cerrado = (m1_year < hoy.year) or (m1_year == hoy.year and m1_month < hoy.month)
    mes_m1 = f"{m1_year}-{m1_month:02d}"
    otif_auto = _otif_drive(mes_m1) if m1_cerrado else None

    otif_manual_f = _safe_float(otif_manual, None) if otif_manual is not None else None
    if otif_manual_f is not None:
        otif_use, otif_fuente = otif_manual_f, "manual"
    elif otif_auto is not None:
        otif_use, otif_fuente = otif_auto, "auto"
    else:
        otif_use, otif_fuente = 0.0, "faltante" if m1_cerrado else "m1_no_cerrado"

    error_use = _safe_float(error_manual, 0.0) if error_manual is not None else 0.0
    esp_use = _safe_float(espiritu_manual, 0.0) if espiritu_manual is not None else 0.0

    r_bono = _calcular_bono(equipo_cfg, base_pozo, otif_use, prod_pct,
                              error_use if equipo_cfg["error_peso"] else None, esp_use)

    st.markdown(f"### 📅 KPIs del mes **{mes_key}**")
    col_n = 4 if equipo_cfg["error_peso"] else 4
    cols = st.columns(col_n)

    fuente_emoji = {"auto": "🤖", "manual": "📝", "faltante": "⚠️",
                     "m1_no_cerrado": "⏳"}[otif_fuente]
    cols[0].metric(f"OTIF (M-1) {fuente_emoji}", f"{otif_use:.1f}%",
                    f"Objetivo >{OTIF_OBJETIVO}%")

    metric_label = "Líneas/persona" if equipo_cfg["prod_metric"] == "lineas" else "Pedidos/persona"
    if prod_real_pp is not None:
        cols[1].metric(
            f"Productividad ({metric_label})",
            f"{prod_real_pp:,.0f}".replace(",", "."),
            f"{prod_pct:.1f}% de meta {meta_prod_cfg:,.0f}".replace(",", "."),
            delta_color="off" if prod_pct >= PROD_OBJETIVO else "inverse",
        )
    else:
        cols[1].metric("Productividad", "Sin datos WMS", "Carga meta manualmente")

    if equipo_cfg["error_peso"]:
        error_label = "Error Despacho" + (" 📝" if error_manual is not None else " ⚠️ FALTA")
        cols[2].metric(error_label, f"{error_use:.0f}%", "Nota 0-100% jefe")
        cols[3].metric(
            "Espíritu MLL" + (" 📝" if espiritu_manual is not None else " ⚠️ FALTA"),
            f"{esp_use:.0f}%", "Nota 0-100% jefe",
        )
    else:
        cols[2].metric(
            "Espíritu MLL" + (" 📝" if espiritu_manual is not None else " ⚠️ FALTA"),
            f"{esp_use:.0f}%", "Nota 0-100% jefe",
        )
        cols[3].metric("💰 Bono devengado",
                        f"${r_bono['bono_devengado']:,.0f}".replace(",", "."),
                        f"De pozo ${base_pozo:,.0f}".replace(",", "."))

    if equipo_cfg["error_peso"]:
        st.metric("💰 Bono devengado",
                   f"${r_bono['bono_devengado']:,.0f}".replace(",", "."),
                   f"De pozo ${base_pozo:,.0f}".replace(",", "."))

    # Avisos
    if otif_fuente == "auto":
        st.success(f"✅ OTIF de {mes_m1} traído automáticamente desde Drive ({otif_auto:.1f}%).")
    elif otif_fuente == "manual":
        st.info(f"📝 OTIF override manual ({otif_use:.1f}%). Para usar auto, bórrate en Carga Bonos.")
    elif otif_fuente == "m1_no_cerrado":
        st.info(f"⏳ M-1 ({mes_m1}) aún no cerrado — OTIF aparecerá automático cuando cierre.")

    faltantes = []
    if otif_fuente == "faltante":
        faltantes.append("OTIF")
    if espiritu_manual is None:
        faltantes.append("Espíritu MLL")
    if equipo_cfg["error_peso"] and error_manual is None:
        faltantes.append("Error Despacho")
    if faltantes:
        st.warning(f"⚠️ Falta **{' + '.join(faltantes)}** para {mes_key}. Cuenta como 0% mientras tanto.")

    st.divider()

    # Desglose bono
    st.markdown("### 🧮 Desglose del bono")
    filas = [
        {
            "KPI": f"OTIF (M-1 = {mes_m1})",
            "Peso": f"{equipo_cfg['otif_peso']*100:.0f}%",
            "Objetivo": f">{OTIF_OBJETIVO}%",
            "Real": f"{otif_use:.1f}%",
            "Ratio paga": f"{r_bono['f_otif']*100:.0f}%",
            "Aporta": _fmt_num(r_bono["aporta_otif"]),
        },
        {
            "KPI": f"Productividad ({metric_label})",
            "Peso": f"{equipo_cfg['prod_peso']*100:.0f}%",
            "Objetivo": f">{PROD_OBJETIVO}%",
            "Real": f"{prod_pct:.1f}%",
            "Ratio paga": f"{r_bono['f_prod']*100:.0f}%",
            "Aporta": _fmt_num(r_bono["aporta_prod"]),
        },
    ]
    if equipo_cfg["error_peso"]:
        filas.append({
            "KPI": "Error de Despacho",
            "Peso": f"{equipo_cfg['error_peso']*100:.0f}%",
            "Objetivo": "Sin errores",
            "Real": f"{error_use:.0f}%",
            "Ratio paga": f"{r_bono['f_error']*100:.0f}%" if r_bono['f_error'] is not None else "0%",
            "Aporta": _fmt_num(r_bono["aporta_error"]),
        })
    filas.append({
        "KPI": "Espíritu MLL",
        "Peso": f"{equipo_cfg['esp_peso']*100:.0f}%",
        "Objetivo": "100%",
        "Real": f"{esp_use:.0f}%",
        "Ratio paga": f"{r_bono['f_esp']*100:.0f}%",
        "Aporta": _fmt_num(r_bono["aporta_esp"]),
    })
    filas.append({
        "KPI": "**TOTAL**",
        "Peso": "**100%**",
        "Objetivo": "",
        "Real": "",
        "Ratio paga": f"**{r_bono['factor_total']*100:.0f}%**",
        "Aporta": f"**{_fmt_num(r_bono['bono_devengado'])}**",
    })
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

    # Productividad detalle
    if prod_real_pp is not None:
        st.divider()
        st.markdown(f"### 📦 Productividad detalle")
        p1, p2, p3, p4 = st.columns(4)
        total_label = "Líneas outgoing" if equipo_cfg["prod_metric"] == "lineas" else "Pedidos outgoing"
        p1.metric(total_label, f"{prod_real_raw:,.0f}".replace(",", "."),
                   f"WMS {mes_key}")
        p2.metric(f"Meta {metric_label}", f"{meta_prod_cfg:,.0f}".replace(",", "."),
                   "Configurable en Carga Bonos")
        p3.metric(f"Real {metric_label}", f"{prod_real_pp:,.0f}".replace(",", "."))
        falta = max(0, meta_prod_cfg - prod_real_pp)
        p4.metric("Faltan para meta", f"{falta:,.0f}".replace(",", "."),
                   delta_color="off" if falta == 0 else "inverse")
        st.caption(
            f"Productividad % = {metric_label} real ({prod_real_pp:,.0f}) / "
            f"meta ({meta_prod_cfg:,.0f}) × 100 = **{prod_pct:.1f}%**. "
            f"Para el 50% completo del bono: necesita ≥{RATIO_MAX:.0f}% de meta.".replace(",", ".")
        )


def _render_carga(equipo_cfg: dict, df_cfg: pd.DataFrame, hoy: date):
    key = equipo_cfg["key"]
    df_e = df_cfg[df_cfg["equipo"] == key] if not df_cfg.empty else pd.DataFrame()

    st.markdown("### 💵 Cargar bono mensual")
    st.caption(
        f"Define los parámetros del bono para cada mes. Pozo base: "
        f"**{equipo_cfg['n_default']} personas × ${equipo_cfg['bono_default']:,} = "
        f"${equipo_cfg['n_default'] * equipo_cfg['bono_default']:,}/mes**. "
        f"OTIF se jala automático desde Drive cuando M-1 está cerrado.".replace(",", ".")
    )

    cfg_dict = df_e.set_index("mes").to_dict("index") if not df_e.empty else {}

    with st.form(f"form_bono_{key}"):
        c1, c2 = st.columns(2)
        with c1:
            anio = st.selectbox("Año", [hoy.year - 1, hoy.year, hoy.year + 1],
                                 index=1, key=f"carga_anio_{key}")
        with c2:
            mes_n = st.selectbox("Mes", list(range(1, 13)),
                                  index=hoy.month - 1, key=f"carga_mes_{key}")
        mes_key = f"{anio}-{mes_n:02d}"
        mes_ant = f"{anio}-{mes_n-1:02d}" if mes_n > 1 else f"{anio-1}-12"
        st.caption(f"Bono de **{mes_key}** · OTIF evaluado contra **{mes_ant}**")

        otif_auto_f = _otif_drive(mes_ant)
        if otif_auto_f is not None:
            st.success(f"🤖 OTIF auto Drive ({mes_ant}): **{otif_auto_f:.1f}%**. "
                       f"Deja vacío para usar el auto, o pon un valor manual para override.")

        prev = cfg_dict.get(mes_key, {})
        prev_n = _safe_int(prev.get("n_personas"), equipo_cfg["n_default"])
        prev_bp = _safe_float(prev.get("bono_persona_clp"), equipo_cfg["bono_default"])
        prev_otif = _safe_float(prev.get("otif_pct"),
                                 otif_auto_f if otif_auto_f is not None else 0.0)
        prev_meta = _safe_float(prev.get("meta_prod"), equipo_cfg["meta_prod_default"])
        prev_error = _safe_float(prev.get("error_despacho_pct"), 100.0)
        prev_esp = _safe_float(prev.get("espiritu_mll_pct"), 100.0)
        prev_pag = _safe_float(prev.get("bono_pagado_real_clp"), 0)
        prev_obs = prev.get("observacion") or ""

        # Pozo
        st.markdown("**🎯 Pozo target**")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            n_personas = st.number_input("Personas", 1, 50, prev_n, 1,
                                          key=f"n_{key}")
        with pc2:
            bono_persona = st.number_input("Bono/persona CLP", 0, 5_000_000,
                                            int(prev_bp), 10_000, key=f"bp_{key}")
        with pc3:
            st.metric("Pozo total", f"${n_personas * bono_persona:,.0f}".replace(",", "."))

        st.divider()
        st.markdown("**📊 KPIs del mes**")

        k1, k2 = st.columns(2)
        with k1:
            otif_in = st.number_input(f"OTIF % — medido en {mes_ant}",
                                       0.0, 100.0, prev_otif, 0.1, key=f"otif_{key}",
                                       help=f"Objetivo >{OTIF_OBJETIVO}%. Ratio pagable 90-100%. "
                                            f"Déjalo en 0 para que use el auto Drive.")
        with k2:
            metric_noun = "líneas" if equipo_cfg["prod_metric"] == "lineas" else "pedidos"
            meta_in = st.number_input(
                f"Meta productividad ({metric_noun}/persona/mes)",
                1.0, 50_000.0, float(prev_meta), 50.0, key=f"meta_{key}",
                help=f"Meta de {metric_noun} por persona por mes. "
                     f"La productividad real se calcula automáticamente desde WMS.",
            )

        if equipo_cfg["error_peso"]:
            e1, e2 = st.columns(2)
            with e1:
                error_in = st.slider("Error de Despacho %", 0, 100, int(prev_error), 5,
                                      key=f"error_{key}",
                                      help="100% = sin errores en el mes. 0% = errores graves.")
            with e2:
                esp_in = st.slider("Espíritu MLL %", 0, 100, int(prev_esp), 5,
                                    key=f"esp_{key}")
        else:
            esp_in = st.slider("Espíritu MLL %", 0, 100, int(prev_esp), 5,
                                key=f"esp_{key}")
            error_in = None

        st.divider()
        st.markdown("**💵 Cierre del mes (opcional)**")
        c_pag, c_obs = st.columns(2)
        with c_pag:
            pag_in = st.number_input("Bono total pagado real (CLP)", 0, 50_000_000,
                                      int(prev_pag), 25_000, key=f"pag_{key}")
        with c_obs:
            obs_in = st.text_input("Observación", prev_obs, key=f"obs_{key}")

        submitted = st.form_submit_button("💾 Guardar / Actualizar", type="primary")
        if submitted:
            ok = _save_config(
                mes_key, key, n_personas, bono_persona,
                otif_pct=otif_in if otif_in > 0 else None,
                meta_prod=meta_in,
                error_despacho_pct=float(error_in) if error_in is not None else None,
                espiritu_mll_pct=float(esp_in),
                bono_pagado_real_clp=pag_in if pag_in > 0 else None,
                observacion=obs_in,
            )
            if ok:
                pozo = n_personas * bono_persona
                st.success(
                    f"✅ Guardado **{mes_key}** [{equipo_cfg['label']}]: "
                    f"{n_personas} pers × ${bono_persona:,.0f} = pozo ${pozo:,.0f} · "
                    f"OTIF {otif_in:.1f}% · Espíritu {esp_in}%".replace(",", ".")
                )
                st.cache_data.clear()
                st.rerun()

    # Tabla config persistida
    st.divider()
    st.markdown("**📋 Config persistida en Turso:**")
    if df_e.empty:
        st.info("Sin config guardada aún. Guarda un mes para empezar.")
    else:
        show = df_e.copy()
        show["n_personas"] = show["n_personas"].apply(
            lambda x: str(int(x)) if pd.notna(x) else "—")
        show["bono_persona_clp"] = show["bono_persona_clp"].apply(
            lambda x: f"${x:,.0f}".replace(",", ".") if pd.notna(x) else "—")
        show["base_clp"] = show["base_clp"].apply(
            lambda x: f"${x:,.0f}".replace(",", "."))
        show["otif_pct"] = show["otif_pct"].apply(
            lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        show["espiritu_mll_pct"] = show["espiritu_mll_pct"].apply(
            lambda x: f"{x:.0f}%" if pd.notna(x) else "—")
        show["bono_pagado_real_clp"] = show["bono_pagado_real_clp"].apply(
            lambda x: f"${x:,.0f}".replace(",", ".") if pd.notna(x) and x else "—")
        rename = {
            "mes": "Mes", "n_personas": "N",
            "bono_persona_clp": "Bono/pers", "base_clp": "Pozo",
            "otif_pct": "OTIF M-1", "meta_prod": "Meta prod",
            "espiritu_mll_pct": "Espíritu",
            "bono_pagado_real_clp": "Pagado real", "observacion": "Obs",
        }
        if equipo_cfg["error_peso"]:
            show["error_despacho_pct"] = show["error_despacho_pct"].apply(
                lambda x: f"{x:.0f}%" if pd.notna(x) else "—")
            rename["error_despacho_pct"] = "Error Desp"
        cols_show = [c for c in rename if c in show.columns]
        st.dataframe(show[cols_show].rename(columns=rename),
                     use_container_width=True, hide_index=True)


def _render_historial(equipo_cfg: dict, df_cfg: pd.DataFrame):
    key = equipo_cfg["key"]
    df_e = df_cfg[df_cfg["equipo"] == key] if not df_cfg.empty else pd.DataFrame()

    st.markdown("### 📈 Historial YTD")
    if df_e.empty:
        st.info("Sin datos históricos aún. Carga al menos un mes en 💵 Carga Bonos.")
        return

    hoy = date.today()
    rows = []
    for _, row in df_e.iterrows():
        try:
            anio, mes = int(row["mes"][:4]), int(row["mes"][5:7])
        except Exception:
            continue
        n_p = _safe_int(row.get("n_personas"), equipo_cfg["n_default"])
        bp = _safe_float(row.get("bono_persona_clp"), equipo_cfg["bono_default"])
        base = _safe_float(row.get("base_clp"), n_p * bp)

        prod_raw = _prod_real(equipo_cfg, anio, mes)
        meta_prod = _safe_float(row.get("meta_prod"), equipo_cfg["meta_prod_default"])
        if prod_raw and n_p and meta_prod:
            prod_pct = (prod_raw / n_p / meta_prod) * 100
        else:
            prod_pct = 0.0

        m1_year = anio if mes > 1 else anio - 1
        m1_month = mes - 1 if mes > 1 else 12
        m1_cerrado = (m1_year < hoy.year) or (m1_year == hoy.year and m1_month < hoy.month)
        otif_auto_h = _otif_drive(f"{m1_year}-{m1_month:02d}") if m1_cerrado else None
        otif_manual_h = row.get("otif_pct")
        otif_f = float(otif_manual_h) if pd.notna(otif_manual_h) and otif_manual_h else otif_auto_h or 0.0
        error_f = row.get("error_despacho_pct")
        esp_f = _safe_float(row.get("espiritu_mll_pct"), 0.0)

        r = _calcular_bono(equipo_cfg, base, otif_f, prod_pct,
                            float(error_f) if pd.notna(error_f) and error_f is not None else None,
                            esp_f)
        pagado = _safe_float(row.get("bono_pagado_real_clp"), 0)
        rows.append({
            "Mes": row["mes"],
            "Pozo": f"${base:,.0f}".replace(",", "."),
            "OTIF %": f"{otif_f:.1f}%",
            "Prod %": f"{prod_pct:.1f}%",
            "Factor": f"{r['factor_total']*100:.0f}%",
            "Devengado": f"${r['bono_devengado']:,.0f}".replace(",", "."),
            "Pagado real": f"${pagado:,.0f}".replace(",", ".") if pagado else "—",
            "Δ": (f"${pagado - r['bono_devengado']:,.0f}".replace(",", ".")
                    if pagado else "—"),
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        total_dev = sum(
            _safe_float(r["Devengado"].replace("$", "").replace(".", ""))
            for r in rows if r["Devengado"] != "—"
        )
        total_pag = sum(
            _safe_float(r["Pagado real"].replace("$", "").replace(".", ""))
            for r in rows if r["Pagado real"] != "—"
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Total devengado YTD", f"${total_dev:,.0f}".replace(",", "."))
        c2.metric("Total pagado YTD", f"${total_pag:,.0f}".replace(",", "."))
        if total_pag and total_dev:
            delta = total_pag - total_dev
            c3.metric("Δ Pagado vs Devengado",
                       f"${delta:,.0f}".replace(",", "."),
                       delta_color="off" if abs(delta) < 10_000 else "inverse")


# ── Entry point principal ─────────────────────────────────────────────────────

def render():
    st.title("🏭 Bonos — Bodega")
    st.caption(
        "**Logística:** OTIF 40% / Productividad 50% / Espíritu 10% · 3 pers × $60.000 · "
        "**Coordinador Pedidos:** OTIF 30% / Prod 30% / Error Despacho 30% / Espíritu 10% · "
        "3 pers × $100.000 · Productividad auto desde WMS."
    )

    df_cfg = _load_config()
    hoy = date.today()

    tab_log, tab_coord = st.tabs(["🏭 Logística", "📋 Coordinador Pedidos"])

    with tab_log:
        _render_equipo(LOGISTICA, df_cfg, hoy)

    with tab_coord:
        _render_equipo(COORDINADOR, df_cfg, hoy)
