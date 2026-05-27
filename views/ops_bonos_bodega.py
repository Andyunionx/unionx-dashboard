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

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WMS_PARQUET = PROJECT_ROOT / "data" / "operaciones" / "volumen_inventario_hist.parquet"
SNAPSHOT_FILE = PROJECT_ROOT / "data" / "kpis_wms" / "snapshot.json"

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
    "prod_metric": "unidades",    # unidades outgoing / N personas / día operado
    "meta_prod_default": 450,     # unidades/persona/día (fallback si no hay forecast)
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
    "prod_metric": "unidades",    # unidades outgoing / N personas / día operado
    "meta_prod_default": 450,     # unidades/persona/día (fallback si no hay forecast)
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
    """Devuelve DataFrame con unidades + lineas + pedidos + días operados por (year, month)."""
    if not WMS_PARQUET.exists():
        return pd.DataFrame(columns=["year", "month", "unidades", "lineas", "pedidos", "dias_op"])
    df = pd.read_parquet(WMS_PARQUET)
    df["fecha_done"] = pd.to_datetime(df["fecha_done"], errors="coerce")
    df = df[df["picking_type_code"] == "outgoing"].dropna(subset=["fecha_done"])
    df["year"] = df["fecha_done"].dt.year
    df["month"] = df["fecha_done"].dt.month

    def _agg_mes(g):
        return pd.Series({
            "unidades": float(g["n_unidades"].sum()),
            "lineas": int(g["n_lineas"].sum()),
            "pedidos": int(g["picking_id"].nunique()),
            "dias_op": int(g["fecha_done"].dt.date.nunique()),
        })

    agg = df.groupby(["year", "month"]).apply(_agg_mes).reset_index()
    return agg


@st.cache_data(ttl=600, show_spinner=False)
def _meta_diaria_forecast(year: int, n_personas: int = 3) -> dict:
    """Meta unidades/persona/día desde el forecast estacional de costo operativo.
    Retorna {mes: meta_diaria}. Si falla, dict vacío (usa meta_prod_default)."""
    import calendar as _cal
    try:
        from views._ops_forecast_costo_helper import proyectar_anual
        df = proyectar_anual(year=year)
        if df.empty:
            return {}
        metas = {}
        for _, row in df.iterrows():
            mes = int(row["mes"])
            unidades = float(row.get("unidades", 0) or 0)
            _, n_dias = _cal.monthrange(year, mes)
            dias_hab = sum(1 for d in range(1, n_dias + 1)
                           if _cal.weekday(year, mes, d) < 5)
            if n_personas > 0 and dias_hab > 0 and unidades > 0:
                metas[mes] = round(unidades / n_personas / dias_hab, 1)
        return metas
    except Exception:
        return {}


def _prod_real_dia(year: int, month: int, n_personas: int) -> tuple[float | None, int]:
    """Retorna (unidades/persona/día real, días_operados) del mes desde WMS."""
    df = _wms_mensual()
    if df.empty:
        return None, 0
    row = df[(df["year"] == year) & (df["month"] == month)]
    if row.empty:
        return None, 0
    unidades = float(row["unidades"].iloc[0])
    dias_op = int(row["dias_op"].iloc[0])
    if dias_op == 0 or n_personas == 0:
        return None, dias_op
    return round(unidades / n_personas / dias_op, 1), dias_op


@st.cache_data(ttl=300, show_spinner=False)
def _otif_drive_snapshot(year: int, month: int) -> float | None:
    """Lee OTIF Empresa del snapshot pre-calculado (otif_drive → resumen_por_mes).
    Usa otif_empresa_pct × 100 — la bodega no controla courier externo."""
    if not SNAPSHOT_FILE.exists():
        return None
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as f:
            snap = json.load(f)
        mes_key = f"{year}-{month:02d}"
        resumen = snap.get("otif_drive", {}).get("resumen_por_mes", {})
        row = resumen.get(mes_key)
        if not row or row.get("error"):
            return None
        val = row.get("otif_empresa_pct")
        return round(float(val) * 100, 2) if val is not None else None
    except Exception:
        return None


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

    otif_manual = cfg_row.get("otif_pct")
    error_manual = cfg_row.get("error_despacho_pct")
    espiritu_manual = cfg_row.get("espiritu_mll_pct")

    # Meta diaria desde forecast (con fallback a config manual o default)
    metas_fcst = _meta_diaria_forecast(anio_sel, n_personas)
    meta_fcst = metas_fcst.get(mes_sel)
    meta_prod_cfg_manual = _safe_float(cfg_row.get("meta_prod"), 0.0)
    if meta_prod_cfg_manual > 0:
        meta_prod_cfg = meta_prod_cfg_manual   # override manual del jefe
        meta_fuente = "manual"
    elif meta_fcst:
        meta_prod_cfg = meta_fcst             # automático desde forecast
        meta_fuente = "forecast"
    else:
        meta_prod_cfg = equipo_cfg["meta_prod_default"]
        meta_fuente = "default"

    # Productividad real desde WMS (unidades/persona/día)
    prod_real_pp, dias_op = _prod_real_dia(anio_sel, mes_sel, n_personas)
    if prod_real_pp is not None:
        prod_pct = (prod_real_pp / meta_prod_cfg * 100) if meta_prod_cfg > 0 else 0.0
    else:
        prod_pct = 0.0

    # OTIF desde snapshot Drive (otif_empresa_pct del mes)
    otif_auto = _otif_drive_snapshot(anio_sel, mes_sel)

    otif_manual_f = _safe_float(otif_manual, None) if otif_manual is not None else None
    if otif_manual_f is not None:
        otif_use, otif_fuente = otif_manual_f, "manual"
    elif otif_auto is not None:
        otif_use, otif_fuente = otif_auto, "auto"
    else:
        otif_use, otif_fuente = 0.0, "sin_drive"

    error_use = _safe_float(error_manual, 0.0) if error_manual is not None else 0.0
    esp_use = _safe_float(espiritu_manual, 0.0) if espiritu_manual is not None else 0.0

    r_bono = _calcular_bono(equipo_cfg, base_pozo, otif_use, prod_pct,
                              error_use if equipo_cfg["error_peso"] else None, esp_use)

    st.markdown(f"### 📅 KPIs del mes **{mes_key}**")
    col_n = 4 if equipo_cfg["error_peso"] else 4
    cols = st.columns(col_n)

    fuente_emoji = {"auto": "🤖", "manual": "📝", "sin_drive": "⚠️"}[otif_fuente]
    cols[0].metric(f"OTIF Empresa {fuente_emoji}", f"{otif_use:.1f}%",
                    f"Objetivo >{OTIF_OBJETIVO}%")

    meta_emoji = {"forecast": "🔮", "manual": "📝", "default": "⚙️"}[meta_fuente]
    if prod_real_pp is not None:
        cols[1].metric(
            f"Prod. unid/pers/día",
            f"{prod_real_pp:,.1f}".replace(",", "."),
            f"{prod_pct:.1f}% de meta {meta_prod_cfg:.0f} {meta_emoji}",
            delta_color="off" if prod_pct >= PROD_OBJETIVO else "inverse",
        )
    else:
        cols[1].metric("Prod. unid/pers/día", "Sin datos WMS", "Parquet no disponible")

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
        st.success(f"✅ OTIF Empresa traído automáticamente desde Drive Sheet ({otif_auto:.1f}%) — mes {mes_key}.")
    elif otif_fuente == "manual":
        st.info(f"📝 OTIF override manual ({otif_use:.1f}%). Para usar Drive automático, bórralo en Carga Bonos.")
    elif otif_fuente == "sin_drive":
        st.warning(f"⚠️ OTIF no disponible en snapshot para {mes_key}. El mes puede estar abierto aún o faltar en el Drive Sheet. Ingrésalo manualmente.")

    faltantes = []
    if otif_fuente == "sin_drive":
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
    mes_key = f"{anio_sel}-{mes_sel:02d}"
    filas = [
        {
            "KPI": f"OTIF Empresa (Drive {mes_key})",
            "Peso": f"{equipo_cfg['otif_peso']*100:.0f}%",
            "Objetivo": f">{OTIF_OBJETIVO}%",
            "Real": f"{otif_use:.1f}%",
            "Ratio paga": f"{r_bono['f_otif']*100:.0f}%",
            "Aporta": _fmt_num(r_bono["aporta_otif"]),
        },
        {
            "KPI": f"Productividad (unid/pers/día)",
            "Peso": f"{equipo_cfg['prod_peso']*100:.0f}%",
            "Objetivo": f">{PROD_OBJETIVO}% de meta {meta_prod_cfg:.0f}",
            "Real": f"{prod_real_pp:.1f} ({prod_pct:.1f}%)" if prod_real_pp else "—",
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
        st.markdown("### 📦 Productividad detalle")
        p1, p2, p3, p4 = st.columns(4)
        df_wms = _wms_mensual()
        unidades_total = 0
        if not df_wms.empty:
            r = df_wms[(df_wms["year"] == anio_sel) & (df_wms["month"] == mes_sel)]
            if not r.empty:
                unidades_total = int(r["unidades"].iloc[0])
        p1.metric("Unidades outgoing", f"{unidades_total:,}".replace(",", "."),
                   f"WMS {mes_key}")
        p2.metric("Días operados", str(dias_op), f"Meta: {meta_prod_cfg:.0f} u/p/día {meta_emoji}")
        p3.metric("Real unid/pers/día", f"{prod_real_pp:.1f}")
        falta = max(0.0, meta_prod_cfg - prod_real_pp)
        p4.metric("Faltan para meta", f"{falta:.1f}",
                   delta_color="off" if falta == 0 else "inverse")
        fuente_txt = {"forecast": "forecast P&L estacional", "manual": "override manual",
                      "default": "valor por defecto"}[meta_fuente]
        st.caption(
            f"Productividad % = {prod_real_pp:.1f} real / meta {meta_prod_cfg:.0f} ({fuente_txt}) "
            f"× 100 = **{prod_pct:.1f}%**. Piso 90% de meta = bono 0; 100% = bono completo."
        )


def _render_carga(equipo_cfg: dict, df_cfg: pd.DataFrame, hoy: date):
    key = equipo_cfg["key"]
    df_e = df_cfg[df_cfg["equipo"] == key] if not df_cfg.empty else pd.DataFrame()

    st.markdown("### 💵 Cargar bono mensual")
    st.caption(
        f"Define los parámetros del bono para cada mes. Pozo base: "
        f"**{equipo_cfg['n_default']} personas × ${equipo_cfg['bono_default']:,} = "
        f"${equipo_cfg['n_default'] * equipo_cfg['bono_default']:,}/mes**. "
        f"OTIF se calcula automáticamente desde el parquet WMS (date_done ≤ scheduled_date).".replace(",", ".")
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
        st.caption(f"Bono de **{mes_key}** · OTIF calculado desde WMS del mismo mes")

        otif_auto_f = _otif_drive_snapshot(anio, mes_n)
        if otif_auto_f is not None:
            st.success(f"🤖 OTIF Empresa Drive ({mes_key}): **{otif_auto_f:.1f}%**. "
                       f"Deja el override en 0 para usar automático.")

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

        # Meta forecast como referencia
        metas_fcst_carga = _meta_diaria_forecast(anio, int(prev_n))
        meta_fcst_mes = metas_fcst_carga.get(mes_n)
        if meta_fcst_mes:
            st.info(f"🔮 Meta forecast estacional para {mes_key}: **{meta_fcst_mes:.0f} unid/pers/día** "
                    f"(basada en P&L FCST). Deja el override en 0 para usar automático.")

        k1, k2 = st.columns(2)
        with k1:
            otif_in = st.number_input(f"OTIF % override — {mes_key} (0 = usar auto Drive)",
                                       0.0, 100.0, prev_otif, 0.1, key=f"otif_{key}",
                                       help=f"Objetivo >{OTIF_OBJETIVO}%. Ratio pagable 90-100%. "
                                            f"Deja en 0 para usar OTIF Empresa del Drive Sheet.")
        with k2:
            meta_in = st.number_input(
                "Meta productividad override (unid/pers/día, 0 = usar forecast)",
                0.0, 5_000.0, float(prev_meta), 10.0, key=f"meta_{key}",
                help="Meta en unidades/persona/día. Deja en 0 para que use el forecast P&L estacional.",
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
    """Historial retroactivo: calcula bono real para todos los meses con data WMS,
    usando OTIF Drive + productividad WMS + metas del forecast estacional."""
    import calendar as _cal
    key = equipo_cfg["key"]
    df_e = df_cfg[df_cfg["equipo"] == key] if not df_cfg.empty else pd.DataFrame()

    st.markdown("### 📈 Historial — simulador retroactivo")
    st.caption(
        "Cada mes calcula el bono con datos reales de WMS + OTIF Drive. "
        "Los meses sin config en Carga Bonos usan los valores por defecto del equipo. "
        "El Espíritu MLL y Error Despacho sin carga manual cuentan como 0%."
    )

    hoy = date.today()
    df_wms = _wms_mensual()
    if df_wms.empty:
        st.warning("Sin datos WMS disponibles. El parquet de volumen no existe o está vacío.")
        return

    # Construir índice de config guardada
    cfg_idx = df_e.set_index("mes").to_dict("index") if not df_e.empty else {}

    # Iterar todos los meses con data WMS, más recientes primero
    df_wms_sorted = df_wms.sort_values(["year", "month"], ascending=False)
    rows_num = []   # para gráfico
    rows_disp = []  # para tabla

    for _, wms_row in df_wms_sorted.iterrows():
        anio = int(wms_row["year"])
        mes = int(wms_row["month"])
        mes_key = f"{anio}-{mes:02d}"

        # Saltar mes actual si incompleto (buffer 7 días)
        if anio == hoy.year and mes == hoy.month:
            continue

        cfg = cfg_idx.get(mes_key, {})
        n_p = _safe_int(cfg.get("n_personas"), equipo_cfg["n_default"])
        bp = _safe_float(cfg.get("bono_persona_clp"), equipo_cfg["bono_default"])
        base = _safe_float(cfg.get("base_clp"), 0) or n_p * bp

        # Productividad real: unidades/persona/día
        unidades = float(wms_row.get("unidades", 0))
        dias_op = int(wms_row.get("dias_op", 0))
        prod_real_d = round(unidades / n_p / dias_op, 1) if (n_p > 0 and dias_op > 0) else None

        # Meta desde forecast estacional
        metas_fcst = _meta_diaria_forecast(anio, n_p)
        meta_manual = _safe_float(cfg.get("meta_prod"), 0.0)
        meta_d = (meta_manual if meta_manual > 0
                  else metas_fcst.get(mes, equipo_cfg["meta_prod_default"]))
        prod_pct = (prod_real_d / meta_d * 100) if (prod_real_d and meta_d) else 0.0

        # OTIF Drive
        otif_auto = _otif_drive_snapshot(anio, mes)
        otif_manual_v = _safe_float(cfg.get("otif_pct"), 0.0)
        otif_f = otif_manual_v if otif_manual_v > 0 else (otif_auto or 0.0)

        # Espíritu y Error
        esp_f = _safe_float(cfg.get("espiritu_mll_pct"), 0.0)
        error_raw = cfg.get("error_despacho_pct")
        error_f = float(error_raw) if (error_raw is not None and pd.notna(error_raw)) else None

        r = _calcular_bono(equipo_cfg, base, otif_f, prod_pct, error_f, esp_f)
        pagado = _safe_float(cfg.get("bono_pagado_real_clp"), 0)

        rows_num.append({
            "mes_key": mes_key,
            "pozo": base,
            "devengado": r["bono_devengado"],
            "pagado": pagado,
        })
        rows_disp.append({
            "Mes": mes_key,
            "Pozo": f"${base:,.0f}".replace(",", "."),
            "OTIF %": f"{otif_f:.1f}%" if otif_f else "—",
            "Unid/p/día": f"{prod_real_d:.0f}" if prod_real_d else "—",
            "Meta/día": f"{meta_d:.0f}",
            "Prod %": f"{prod_pct:.1f}%",
            "Espíritu": f"{esp_f:.0f}%" if esp_f else "—",
            "Factor": f"{r['factor_total']*100:.0f}%",
            "Devengado": f"${r['bono_devengado']:,.0f}".replace(",", "."),
            "Pagado": f"${pagado:,.0f}".replace(",", ".") if pagado else "—",
        })

    if not rows_disp:
        st.info("Sin meses completos en el parquet WMS aún.")
        return

    # ── Métricas resumen ──────────────────────────────────────────────────────
    total_dev = sum(r["devengado"] for r in rows_num)
    total_pag = sum(r["pagado"] for r in rows_num)
    total_pozo = sum(r["pozo"] for r in rows_num)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total devengado", f"${total_dev:,.0f}".replace(",", "."))
    c2.metric("Total pagado", f"${total_pag:,.0f}".replace(",", ".") if total_pag else "Sin registros")
    c3.metric("Total pozo acum.", f"${total_pozo:,.0f}".replace(",", "."))
    eff = total_dev / total_pozo * 100 if total_pozo else 0
    c4.metric("% pozo devengado", f"{eff:.1f}%")

    # ── Gráfico devengado vs pozo ─────────────────────────────────────────────
    st.divider()
    df_chart = pd.DataFrame(rows_num).sort_values("mes_key")
    if not df_chart.empty:
        import altair as alt
        df_melt = df_chart.melt(id_vars="mes_key", value_vars=["pozo", "devengado", "pagado"],
                                 var_name="tipo", value_name="valor")
        labels = {"pozo": "Pozo disponible", "devengado": "Devengado", "pagado": "Pagado real"}
        colores = {"pozo": "#d0d0d0", "devengado": "#1f77b4", "pagado": "#2ca02c"}
        df_melt["tipo_label"] = df_melt["tipo"].map(labels)
        chart = (
            alt.Chart(df_melt)
            .mark_bar(opacity=0.85)
            .encode(
                x=alt.X("mes_key:N", title="Mes", sort=None),
                y=alt.Y("valor:Q", title="CLP", axis=alt.Axis(format=",.0f")),
                color=alt.Color("tipo_label:N",
                                scale=alt.Scale(domain=list(labels.values()),
                                                range=list(colores.values())),
                                legend=alt.Legend(title="", orient="top")),
                xOffset="tipo_label:N",
                tooltip=["mes_key", "tipo_label",
                          alt.Tooltip("valor:Q", format=",.0f", title="CLP")],
            )
            .properties(height=300, title=f"Bonos {equipo_cfg['label']} — devengado vs pozo")
        )
        st.altair_chart(chart, use_container_width=True)

    # ── Tabla detalle ─────────────────────────────────────────────────────────
    st.dataframe(pd.DataFrame(rows_disp), use_container_width=True, hide_index=True)


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
