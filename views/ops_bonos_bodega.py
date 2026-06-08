"""
Vista Bonos — Bodega (Logística + Coordinador Pedidos).

LOGÍSTICA  (3 pers × $60.000):
  Bono = Base × (OTIF×40% + Productividad×50% + Espíritu×10%)

COORDINADOR PEDIDOS  (3 pers × $100.000):
  Bono = Base × (OTIF×30% + Productividad×30% + ErrorDespacho×30% + Espíritu×10%)

Productividad: unidades_mes / N_personas / días_hábiles_mes
  → misma fórmula que KPI WMS (uds/persona/día)
OTIF: Drive Sheet snapshot (otif_empresa_pct) — la bodega no controla el courier
Error Despacho / Espíritu: manual del jefe
Ratio OTIF + Prod: piso 90% → 0, techo 100% → 1 (lineal)
Ratio Error + Espíritu: directo 0-100%
"""
from __future__ import annotations

import calendar as _cal
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WMS_PARQUET = PROJECT_ROOT / "data" / "operaciones" / "volumen_inventario_hist.parquet"
SNAPSHOT_FILE = PROJECT_ROOT / "data" / "kpis_wms" / "snapshot.json"

# ── Configuración equipos ─────────────────────────────────────────────────────

LOGISTICA = {
    "key": "logistica", "label": "🏭 Logística",
    "n_default": 3, "bono_default": 60_000,
    "otif_peso": 0.40, "prod_peso": 0.50, "error_peso": None, "esp_peso": 0.10,
    "meta_prod_default": 280,   # unidades/persona/día hábil (ref WMS: ~244)
}
COORDINADOR = {
    "key": "coordinador", "label": "📋 Coordinador Pedidos",
    "n_default": 3, "bono_default": 100_000,
    "otif_peso": 0.30, "prod_peso": 0.30, "error_peso": 0.30, "esp_peso": 0.10,
    "meta_prod_default": 280,
}

OTIF_OBJETIVO = 98.0
PROD_OBJETIVO = 90.0
RATIO_MIN, RATIO_MAX = 90.0, 100.0


# ── Helpers numéricos ─────────────────────────────────────────────────────────

def _safe_float(v, default=0.0):
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


def _factor_ratio(v) -> float:
    if v is None or pd.isna(v):
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f < RATIO_MIN:
        return 0.0
    if f >= RATIO_MAX:
        return 1.0
    return (f - RATIO_MIN) / (RATIO_MAX - RATIO_MIN)


def _factor_directo(v) -> float:
    if v is None or pd.isna(v):
        return 0.0
    try:
        return max(0.0, min(1.0, float(v) / 100.0))
    except (TypeError, ValueError):
        return 0.0


def _fmt_clp(v) -> str:
    if v is None or v == 0:
        return "—"
    return f"${abs(v):,.0f}".replace(",", ".")


def _dias_habiles(year: int, month: int) -> int:
    _, n = _cal.monthrange(year, month)
    return sum(1 for d in range(1, n + 1) if _cal.weekday(year, month, d) < 5)


# ── Datos WMS ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def _wms_mensual() -> pd.DataFrame:
    """Unidades + líneas + pedidos outgoing por (year, month) desde parquet."""
    if not WMS_PARQUET.exists():
        return pd.DataFrame(columns=["year", "month", "unidades", "lineas", "pedidos"])
    try:
        df = pd.read_parquet(WMS_PARQUET)
        df["fecha_done"] = pd.to_datetime(df["fecha_done"], errors="coerce")
        df = df[df["picking_type_code"] == "outgoing"].dropna(subset=["fecha_done"])
        df["year"] = df["fecha_done"].dt.year
        df["month"] = df["fecha_done"].dt.month

        def _agg(g):
            return pd.Series({
                "unidades": float(g["n_unidades"].sum()),
                "lineas": int(g["n_lineas"].sum()),
                "pedidos": int(g["picking_id"].nunique()),
            })

        return df.groupby(["year", "month"]).apply(_agg).reset_index()
    except Exception:
        return pd.DataFrame(columns=["year", "month", "unidades", "lineas", "pedidos"])


def _prod_mes(year: int, month: int, n_personas: int):
    """(uds_pers_dia, dias_hab, unidades_total) — misma fórmula que KPI WMS."""
    dh = _dias_habiles(year, month)
    df = _wms_mensual()
    if df.empty:
        return None, dh, 0
    row = df[(df["year"] == year) & (df["month"] == month)]
    if row.empty:
        return None, dh, 0
    unidades = float(row["unidades"].iloc[0])
    if n_personas <= 0 or dh <= 0:
        return None, dh, int(unidades)
    return round(unidades / n_personas / dh, 1), dh, int(unidades)


@st.cache_data(ttl=600, show_spinner=False)
def _meta_forecast(year: int, mes: int, n_personas: int):
    """Meta unidades/persona/día hábil desde forecast estacional P&L.
    Usa proyectar_anual: venta_fcst × ratio_unidades/MM_venta (estacional)."""
    try:
        from views._ops_forecast_costo_helper import proyectar_anual
        df = proyectar_anual(year=year)
        if df.empty:
            return None
        row = df[df["mes"] == mes]
        if row.empty:
            return None
        unidades = float(row["unidades"].iloc[0])
        dh = _dias_habiles(year, mes)
        if n_personas > 0 and dh > 0 and unidades > 0:
            return round(unidades / n_personas / dh, 1)
        return None
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _meta_rolling(year: int, month: int, n_personas: int):
    """Fallback: promedio últimos 3 meses de unidades/persona/día hábil."""
    df = _wms_mensual()
    if df.empty:
        return None
    valores = []
    for i in range(1, 4):
        m, y = month - i, year
        if m <= 0:
            m += 12; y -= 1
        row = df[(df["year"] == y) & (df["month"] == m)]
        if row.empty:
            continue
        dh = _dias_habiles(y, m)
        if n_personas > 0 and dh > 0:
            valores.append(float(row["unidades"].iloc[0]) / n_personas / dh)
    return round(sum(valores) / len(valores)) if valores else None


@st.cache_data(ttl=300, show_spinner=False)
def _otif_snapshot(year: int, month: int):
    """OTIF Empresa del snapshot Drive (otif_empresa_pct × 100)."""
    if not SNAPSHOT_FILE.exists():
        return None
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as f:
            snap = json.load(f)
        row = snap.get("otif_drive", {}).get("resumen_por_mes", {}).get(f"{year}-{month:02d}")
        if not row or row.get("error"):
            return None
        val = row.get("otif_empresa_pct")
        return round(float(val) * 100, 2) if val is not None else None
    except Exception:
        return None


# ── Config Turso ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def _load_config() -> pd.DataFrame:
    cols = ["mes", "equipo", "n_personas", "bono_persona_clp", "base_clp",
            "otif_pct", "meta_prod", "error_despacho_pct", "espiritu_mll_pct",
            "bono_pagado_real_clp", "observacion"]
    try:
        from views.alertas_helper import _query
        _query("""CREATE TABLE IF NOT EXISTS bonos_bodega_config (
            mes TEXT, equipo TEXT, n_personas INTEGER, bono_persona_clp REAL,
            base_clp REAL, otif_pct REAL, meta_prod REAL, error_despacho_pct REAL,
            espiritu_mll_pct REAL, bono_pagado_real_clp REAL, observacion TEXT,
            actualizado_en TEXT, PRIMARY KEY (mes, equipo))""")
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
            def _v(i, _r=r):
                c = _r[i]
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


def _save_config(mes, equipo, n_personas, bono_persona_clp,
                  otif_pct, meta_prod, error_despacho_pct, espiritu_mll_pct,
                  bono_pagado_real_clp, observacion="") -> bool:
    base_clp = n_personas * bono_persona_clp
    try:
        from views.alertas_helper import _query
        _query("""INSERT INTO bonos_bodega_config
                    (mes, equipo, n_personas, bono_persona_clp, base_clp,
                     otif_pct, meta_prod, error_despacho_pct, espiritu_mll_pct,
                     bono_pagado_real_clp, observacion, actualizado_en)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(mes, equipo) DO UPDATE SET
                    n_personas=excluded.n_personas, bono_persona_clp=excluded.bono_persona_clp,
                    base_clp=excluded.base_clp, otif_pct=excluded.otif_pct,
                    meta_prod=excluded.meta_prod, error_despacho_pct=excluded.error_despacho_pct,
                    espiritu_mll_pct=excluded.espiritu_mll_pct,
                    bono_pagado_real_clp=excluded.bono_pagado_real_clp,
                    observacion=excluded.observacion, actualizado_en=excluded.actualizado_en""",
               [mes, equipo, int(n_personas), float(bono_persona_clp), float(base_clp),
                float(otif_pct) if otif_pct is not None else None,
                float(meta_prod) if meta_prod else None,
                float(error_despacho_pct) if error_despacho_pct is not None else None,
                float(espiritu_mll_pct) if espiritu_mll_pct is not None else None,
                float(bono_pagado_real_clp) if bono_pagado_real_clp else None,
                observacion, datetime.now().isoformat()])
        return True
    except Exception as e:
        st.error(f"Error guardando: {e}")
        return False


# ── Cálculo bono ──────────────────────────────────────────────────────────────

def _calc_bono(cfg: dict, base: float, otif_pct: float, prod_pct: float,
                error_pct, espiritu_pct: float) -> dict:
    f_otif = _factor_ratio(otif_pct)
    f_prod = _factor_ratio(prod_pct)
    f_err = _factor_directo(error_pct) if error_pct is not None else None
    f_esp = _factor_directo(espiritu_pct)
    factor = f_otif * cfg["otif_peso"] + f_prod * cfg["prod_peso"] + f_esp * cfg["esp_peso"]
    if cfg["error_peso"] is not None and f_err is not None:
        factor += f_err * cfg["error_peso"]
    return {
        "f_otif": f_otif, "aporta_otif": base * f_otif * cfg["otif_peso"],
        "prod_pct": prod_pct, "f_prod": f_prod, "aporta_prod": base * f_prod * cfg["prod_peso"],
        "f_err": f_err, "aporta_err": (base * f_err * cfg["error_peso"]
                                        if f_err is not None and cfg["error_peso"] else 0),
        "f_esp": f_esp, "aporta_esp": base * f_esp * cfg["esp_peso"],
        "factor_total": factor, "bono_devengado": round(base * factor, -2),
    }


# ── Resumen tab ───────────────────────────────────────────────────────────────

def _tab_resumen(equipo_cfg: dict, df_cfg: pd.DataFrame, hoy: date):
    key = equipo_cfg["key"]
    df_e = df_cfg[df_cfg["equipo"] == key] if not df_cfg.empty else pd.DataFrame()
    cfg_dict = df_e.set_index("mes").to_dict("index") if not df_e.empty else {}

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        anio_sel = st.selectbox("Año", [hoy.year - 1, hoy.year], index=1, key=f"ra_{key}")
    with c2:
        mes_sel = st.selectbox("Mes", list(range(1, 13)), index=hoy.month - 1, key=f"rm_{key}")
    with c3:
        st.write("")
        if st.button("🔄 Refrescar", key=f"rr_{key}"):
            st.cache_data.clear(); st.rerun()

    mes_key = f"{anio_sel}-{mes_sel:02d}"
    cfg_mes = cfg_dict.get(mes_key, {})

    n_personas = _safe_int(cfg_mes.get("n_personas"), equipo_cfg["n_default"])
    bono_persona = _safe_float(cfg_mes.get("bono_persona_clp"), equipo_cfg["bono_default"])
    base_pozo = _safe_float(cfg_mes.get("base_clp"), 0) or n_personas * bono_persona

    # OTIF
    otif_auto = _otif_snapshot(anio_sel, mes_sel)
    otif_manual = _safe_float(cfg_mes.get("otif_pct"), None)
    if otif_manual is not None and otif_manual > 0:
        otif_use, otif_fuente = otif_manual, "manual"
    elif otif_auto is not None:
        otif_use, otif_fuente = otif_auto, "auto"
    else:
        otif_use, otif_fuente = 0.0, "sin_drive"

    # Productividad (misma fórmula que KPI WMS)
    prod_pp, dias_hab, uds_total = _prod_mes(anio_sel, mes_sel, n_personas)

    # Meta: override manual > forecast P&L > rolling 3m > default
    meta_manual = _safe_float(cfg_mes.get("meta_prod"), 0.0)
    if meta_manual > 0:
        meta, meta_src = meta_manual, "manual"
    else:
        meta_fcst = _meta_forecast(anio_sel, mes_sel, n_personas)
        if meta_fcst:
            meta, meta_src = meta_fcst, "forecast"
        else:
            meta_roll = _meta_rolling(anio_sel, mes_sel, n_personas)
            if meta_roll:
                meta, meta_src = float(meta_roll), "promedio 3m"
            else:
                meta, meta_src = float(equipo_cfg["meta_prod_default"]), "default"

    prod_pct = (prod_pp / meta * 100) if (prod_pp is not None and meta > 0) else 0.0

    error_manual = cfg_mes.get("error_despacho_pct")
    esp_manual = cfg_mes.get("espiritu_mll_pct")
    error_use = _safe_float(error_manual, 0.0) if error_manual is not None else 0.0
    esp_use = _safe_float(esp_manual, 0.0) if esp_manual is not None else 0.0

    r = _calc_bono(equipo_cfg, base_pozo, otif_use, prod_pct,
                    error_use if equipo_cfg["error_peso"] else None, esp_use)

    # ── Bloque 1: KPIs ────────────────────────────────────────────────────────
    st.markdown(f"### 📅 KPIs del mes {mes_key}")
    col1, col2, col3, col4 = st.columns(4)

    fuente_lbl = {"auto": "🤖", "manual": "📝", "sin_drive": "⚠️"}[otif_fuente]
    col1.metric(f"OTIF Empresa {fuente_lbl}", f"{otif_use:.1f}%",
                f"Objetivo >{OTIF_OBJETIVO}%",
                delta_color="off" if otif_use >= OTIF_OBJETIVO else "inverse")

    col2.metric("Productividad",
                f"{prod_pct:.1f}%" if prod_pp is not None else "Sin datos",
                f"Objetivo >{PROD_OBJETIVO}%" if prod_pp is not None else "Parquet no disponible",
                delta_color="off" if prod_pct >= PROD_OBJETIVO else "inverse")

    esp_lbl = "Espíritu MLL" + (" 📝" if esp_manual is not None else " ⚠️ FALTA")
    col3.metric(esp_lbl, f"{esp_use:.0f}%", "Nota 0-100% jefe")

    if equipo_cfg["error_peso"]:
        err_lbl = "Error Despacho" + (" 📝" if error_manual is not None else " ⚠️ FALTA")
        col4.metric(err_lbl, f"{error_use:.0f}%", "100% = sin errores")
        st.metric("💰 Bono devengado",
                   f"${r['bono_devengado']:,.0f}".replace(",", "."),
                   f"De pozo ${base_pozo:,.0f}".replace(",", "."))
    else:
        col4.metric("💰 Bono devengado",
                     f"${r['bono_devengado']:,.0f}".replace(",", "."),
                     f"De pozo ${base_pozo:,.0f}".replace(",", "."))

    if otif_fuente == "auto":
        st.success(f"✅ OTIF Empresa traído automáticamente desde Drive Sheet ({otif_auto:.1f}%) — mes {mes_key}.")
    elif otif_fuente == "manual":
        st.info(f"📝 OTIF override manual ({otif_use:.1f}%). Para usar auto Drive, bórralo en Carga Bonos.")
    elif otif_fuente == "sin_drive":
        st.warning(f"⚠️ OTIF no disponible para {mes_key}. Ingrésalo manualmente en Carga Bonos.")

    faltantes = []
    if otif_fuente == "sin_drive": faltantes.append("OTIF")
    if esp_manual is None: faltantes.append("Espíritu MLL")
    if equipo_cfg["error_peso"] and error_manual is None: faltantes.append("Error Despacho")
    if faltantes:
        st.warning(f"⚠️ Falta **{' + '.join(faltantes)}** para {mes_key}. Cuenta como 0%.")

    st.divider()

    # ── Bloque 2: Productividad detalle ──────────────────────────────────────
    st.markdown("### 📦 Productividad — detalle por persona")
    meta_pp = meta
    falta_uds = max(0.0, (meta_pp - (prod_pp or 0)) * n_personas * dias_hab)

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Unidades outgoing", f"{uds_total:,}".replace(",", "."), f"WMS {mes_key}")
    p2.metric(f"Meta/persona/día ({meta_src})", f"{meta_pp:.0f}")
    p3.metric("Real/persona/día",
              f"{prod_pp:.1f}" if prod_pp is not None else "—",
              f"{prod_pct:.1f}% de meta",
              delta_color="off")
    p4.metric("Faltan unidades para meta",
              f"~{falta_uds:,.0f}".replace(",", ".") if prod_pp is not None else "—",
              f"{dias_hab} días hábiles mes",
              delta_color="off" if falta_uds == 0 else "inverse")

    if prod_pp is not None:
        st.caption(
            f"Prod% = {prod_pp:.1f} real / meta {meta_pp:.0f} ({meta_src}) × 100 = **{prod_pct:.1f}%**. "
            f"Fórmula: {uds_total:,} unidades / {n_personas} personas / {dias_hab} días hábiles. "
            f"Piso {RATIO_MIN:.0f}% → bono 0; {RATIO_MAX:.0f}% → bono completo.".replace(",", ".")
        )

    st.divider()

    # ── Bloque 3: Desglose bono ───────────────────────────────────────────────
    st.markdown("### 🧮 Desglose del bono")
    filas = [
        {"KPI": f"OTIF Empresa (Drive {mes_key})", "Peso": f"{equipo_cfg['otif_peso']*100:.0f}%",
         "Objetivo": f">{OTIF_OBJETIVO}%", "Real": f"{otif_use:.1f}%",
         "Ratio paga": f"{r['f_otif']*100:.0f}%", "Aporta al bono": _fmt_clp(r["aporta_otif"])},
        {"KPI": "Productividad unid/pers/día", "Peso": f"{equipo_cfg['prod_peso']*100:.0f}%",
         "Objetivo": f">{PROD_OBJETIVO}% de meta {meta_pp:.0f}",
         "Real": f"{prod_pp:.1f} ({prod_pct:.1f}%)" if prod_pp is not None else "—",
         "Ratio paga": f"{r['f_prod']*100:.0f}%", "Aporta al bono": _fmt_clp(r["aporta_prod"])},
    ]
    if equipo_cfg["error_peso"]:
        filas.append({
            "KPI": "Error de Despacho", "Peso": f"{equipo_cfg['error_peso']*100:.0f}%",
            "Objetivo": "Sin errores (100%)", "Real": f"{error_use:.0f}%",
            "Ratio paga": f"{r['f_err']*100:.0f}%" if r['f_err'] is not None else "0%",
            "Aporta al bono": _fmt_clp(r["aporta_err"])})
    filas.append({
        "KPI": "Espíritu MLL", "Peso": f"{equipo_cfg['esp_peso']*100:.0f}%",
        "Objetivo": "100%", "Real": f"{esp_use:.0f}%",
        "Ratio paga": f"{r['f_esp']*100:.0f}%", "Aporta al bono": _fmt_clp(r["aporta_esp"])})
    filas.append({
        "KPI": "**TOTAL**", "Peso": "**100%**", "Objetivo": "", "Real": "",
        "Ratio paga": f"**{r['factor_total']*100:.0f}%**",
        "Aporta al bono": f"**{_fmt_clp(r['bono_devengado'])}**"})
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

    # ── Bloque 4: Evolución mensual ──────────────────────────────────────────
    st.divider()
    st.markdown(f"### 📈 Evolución mensual — Productividad y OTIF ({anio_sel})")
    st.caption(f"Objetivos: Productividad ≥ {PROD_OBJETIVO}% · OTIF ≥ {OTIF_OBJETIVO}%.")

    evo_rows = []
    for mm in range(1, 13):
        pp_m, dh_m, _ = _prod_mes(anio_sel, mm, n_personas)
        cfg_m = cfg_dict.get(f"{anio_sel}-{mm:02d}", {})
        meta_m_man = _safe_float(cfg_m.get("meta_prod"), 0.0)
        if meta_m_man > 0:
            meta_m = meta_m_man
        else:
            meta_m = float(_meta_forecast(anio_sel, mm, n_personas)
                           or _meta_rolling(anio_sel, mm, n_personas)
                           or equipo_cfg["meta_prod_default"])
        prod_m_pct = (pp_m / meta_m * 100) if (pp_m is not None and meta_m > 0) else None
        otif_m = (_safe_float(cfg_m.get("otif_pct"), None) or _otif_snapshot(anio_sel, mm))
        es_futuro = (anio_sel > hoy.year) or (anio_sel == hoy.year and mm > hoy.month)
        es_actual = (anio_sel == hoy.year and mm == hoy.month)

        evo_rows.append({
            "Mes": f"{anio_sel}-{mm:02d}",
            "Estado": "🔮 Futuro" if es_futuro else ("⏳ En curso" if es_actual else "✅ Cerrado"),
            "Unid/p/d real": f"{pp_m:.0f}" if (pp_m is not None and not es_futuro) else "—",
            "Meta": f"{meta_m:.0f}",
            "Prod %": (f"{prod_m_pct:.1f}%"
                       + (" 🟢" if prod_m_pct >= PROD_OBJETIVO else " 🔴")
                       + (" (parcial)" if es_actual else "")
                       ) if (prod_m_pct is not None and not es_futuro) else "—",
            "OTIF %": (f"{otif_m:.1f}%"
                       + (" 🟢" if otif_m >= OTIF_OBJETIVO else " 🔴")
                       ) if otif_m is not None else "—",
            "_p": prod_m_pct if not es_futuro else None,
            "_o": otif_m if not es_futuro else None,
        })

    df_evo = pd.DataFrame(evo_rows)
    st.dataframe(df_evo.drop(columns=["_p", "_o"]), use_container_width=True, hide_index=True)
    chart_df = df_evo.set_index("Mes")[["_p", "_o"]].rename(
        columns={"_p": "Productividad %", "_o": "OTIF %"})
    st.line_chart(chart_df, height=280)


# ── Carga bonos tab ───────────────────────────────────────────────────────────

def _tab_carga(equipo_cfg: dict, df_cfg: pd.DataFrame, hoy: date):
    key = equipo_cfg["key"]
    df_e = df_cfg[df_cfg["equipo"] == key] if not df_cfg.empty else pd.DataFrame()
    cfg_dict = df_e.set_index("mes").to_dict("index") if not df_e.empty else {}

    st.markdown("### 💵 Cargar bono mensual")
    st.caption(
        f"Pozo base: **{equipo_cfg['n_default']} personas × "
        f"${equipo_cfg['bono_default']:,} = "
        f"${equipo_cfg['n_default'] * equipo_cfg['bono_default']:,}/mes**. "
        "OTIF carga automático desde Drive Sheet.".replace(",", ".")
    )

    with st.form(f"form_{key}"):
        c1, c2 = st.columns(2)
        with c1:
            anio = st.selectbox("Año", [hoy.year - 1, hoy.year, hoy.year + 1], index=1, key=f"ca_{key}")
        with c2:
            mes_n = st.selectbox("Mes", list(range(1, 13)), index=hoy.month - 1, key=f"cm_{key}")
        mes_key = f"{anio}-{mes_n:02d}"

        otif_auto = _otif_snapshot(anio, mes_n)
        if otif_auto is not None:
            st.success(f"🤖 OTIF Empresa Drive ({mes_key}): **{otif_auto:.1f}%**. Deja override en 0 para usar automático.")

        meta_fcst_carga = _meta_forecast(anio, mes_n, equipo_cfg["n_default"])
        if meta_fcst_carga:
            st.info(f"🔮 Meta forecast estacional P&L: **{meta_fcst_carga:.0f} unid/pers/día**. "
                    f"Basada en venta FCST × ratio histórico. Deja en 0 para usar automático.")
        else:
            meta_roll = _meta_rolling(anio, mes_n, equipo_cfg["n_default"])
            if meta_roll:
                st.info(f"📊 Meta auto (promedio 3m, fallback): **{meta_roll:.0f} unid/pers/día**.")

        prev = cfg_dict.get(mes_key, {})
        prev_n = _safe_int(prev.get("n_personas"), equipo_cfg["n_default"])
        prev_bp = _safe_float(prev.get("bono_persona_clp"), equipo_cfg["bono_default"])
        prev_otif = _safe_float(prev.get("otif_pct"), otif_auto if otif_auto else 0.0)
        prev_meta = _safe_float(prev.get("meta_prod"), 0.0)
        prev_error = _safe_float(prev.get("error_despacho_pct"), 100.0)
        prev_esp = _safe_float(prev.get("espiritu_mll_pct"), 100.0)
        prev_pag = _safe_float(prev.get("bono_pagado_real_clp"), 0)
        prev_obs = prev.get("observacion") or ""

        st.markdown("**🎯 Pozo target**")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            n_p = st.number_input("Personas", 1, 50, prev_n, 1, key=f"np_{key}")
        with pc2:
            bp = st.number_input("Bono/persona CLP", 0, 5_000_000, int(prev_bp), 10_000, key=f"bp_{key}")
        with pc3:
            st.metric("Pozo total", f"${n_p * bp:,.0f}".replace(",", "."))

        st.divider()
        st.markdown("**📊 KPIs del mes**")
        k1, k2 = st.columns(2)
        with k1:
            otif_in = st.number_input("OTIF % override (0 = usar auto Drive)",
                                       0.0, 100.0, prev_otif, 0.1, key=f"oi_{key}")
        with k2:
            meta_in = st.number_input("Meta unid/pers/día override (0 = auto promedio 3m)",
                                       0.0, 5_000.0, float(prev_meta), 10.0, key=f"mi_{key}")

        if equipo_cfg["error_peso"]:
            e1, e2 = st.columns(2)
            with e1:
                err_in = st.slider("Error de Despacho %", 0, 100, int(prev_error), 5, key=f"ei_{key}",
                                    help="100% = sin errores. 0% = errores graves.")
            with e2:
                esp_in = st.slider("Espíritu MLL %", 0, 100, int(prev_esp), 5, key=f"esi_{key}")
        else:
            esp_in = st.slider("Espíritu MLL %", 0, 100, int(prev_esp), 5, key=f"esi_{key}")
            err_in = None

        st.divider()
        st.markdown("**💵 Cierre del mes (opcional)**")
        cp1, cp2 = st.columns(2)
        with cp1:
            pag_in = st.number_input("Bono total pagado real (CLP)", 0, 50_000_000, int(prev_pag), 25_000, key=f"pi_{key}")
        with cp2:
            obs_in = st.text_input("Observación", prev_obs, key=f"obsi_{key}")

        submitted = st.form_submit_button("💾 Guardar / Actualizar", type="primary")
        if submitted:
            ok = _save_config(
                mes_key, key, n_p, bp,
                otif_pct=otif_in if otif_in > 0 else None,
                meta_prod=meta_in if meta_in > 0 else None,
                error_despacho_pct=float(err_in) if err_in is not None else None,
                espiritu_mll_pct=float(esp_in),
                bono_pagado_real_clp=pag_in if pag_in > 0 else None,
                observacion=obs_in,
            )
            if ok:
                st.success(f"✅ Guardado **{mes_key}** [{equipo_cfg['label']}]: "
                           f"{n_p} pers × ${bp:,.0f} = ${n_p*bp:,.0f} · Espíritu {esp_in}%".replace(",", "."))
                st.cache_data.clear(); st.rerun()

    st.divider()
    st.markdown("**📋 Config en Turso:**")
    if df_e.empty:
        st.info("Sin config guardada aún.")
    else:
        show = df_e.copy()
        for col, fn in [
            ("n_personas", lambda x: str(int(x)) if pd.notna(x) else "—"),
            ("bono_persona_clp", lambda x: f"${x:,.0f}".replace(",", ".") if pd.notna(x) else "—"),
            ("base_clp", lambda x: f"${x:,.0f}".replace(",", ".")),
            ("otif_pct", lambda x: f"{x:.1f}%" if pd.notna(x) else "—"),
            ("espiritu_mll_pct", lambda x: f"{x:.0f}%" if pd.notna(x) else "—"),
            ("bono_pagado_real_clp", lambda x: f"${x:,.0f}".replace(",", ".") if (pd.notna(x) and x) else "—"),
        ]:
            show[col] = show[col].apply(fn)
        rename = {"mes": "Mes", "n_personas": "N", "bono_persona_clp": "Bono/pers",
                  "base_clp": "Pozo", "otif_pct": "OTIF", "meta_prod": "Meta",
                  "espiritu_mll_pct": "Espíritu", "bono_pagado_real_clp": "Pagado", "observacion": "Obs"}
        if equipo_cfg["error_peso"]:
            show["error_despacho_pct"] = show["error_despacho_pct"].apply(
                lambda x: f"{x:.0f}%" if pd.notna(x) else "—")
            rename["error_despacho_pct"] = "Error Desp"
        cols_show = [c for c in rename if c in show.columns]
        st.dataframe(show[cols_show].rename(columns=rename), use_container_width=True, hide_index=True)


# ── Historial tab ─────────────────────────────────────────────────────────────

def _tab_historial(equipo_cfg: dict, df_cfg: pd.DataFrame):
    key = equipo_cfg["key"]
    df_e = df_cfg[df_cfg["equipo"] == key] if not df_cfg.empty else pd.DataFrame()
    cfg_dict = df_e.set_index("mes").to_dict("index") if not df_e.empty else {}

    st.markdown("### 📈 Historial — simulador retroactivo")
    st.caption("Bono calculado para cada mes cerrado con datos reales WMS + OTIF Drive.")

    hoy = date.today()
    df_wms = _wms_mensual()
    if df_wms.empty:
        st.warning("Sin datos WMS disponibles.")
        return

    rows_num, rows_disp = [], []
    for _, wms_row in df_wms.sort_values(["year", "month"], ascending=False).iterrows():
        anio = int(wms_row["year"]); mes = int(wms_row["month"])
        if anio == hoy.year and mes == hoy.month:
            continue

        cfg = cfg_dict.get(f"{anio}-{mes:02d}", {})
        n_p = _safe_int(cfg.get("n_personas"), equipo_cfg["n_default"])
        bp = _safe_float(cfg.get("bono_persona_clp"), equipo_cfg["bono_default"])
        base = _safe_float(cfg.get("base_clp"), 0) or n_p * bp

        unidades = float(wms_row.get("unidades", 0))
        dh = _dias_habiles(anio, mes)
        prod_pp = round(unidades / n_p / dh, 1) if (n_p > 0 and dh > 0) else None

        meta_m = _safe_float(cfg.get("meta_prod"), 0.0)
        if not meta_m:
            meta_m = float(_meta_forecast(anio, mes, n_p)
                           or _meta_rolling(anio, mes, n_p)
                           or equipo_cfg["meta_prod_default"])
        prod_pct = (prod_pp / meta_m * 100) if (prod_pp and meta_m) else 0.0

        otif_auto = _otif_snapshot(anio, mes)
        otif_f = _safe_float(cfg.get("otif_pct"), 0.0) or (otif_auto or 0.0)
        esp_f = _safe_float(cfg.get("espiritu_mll_pct"), 0.0)
        err_raw = cfg.get("error_despacho_pct")
        err_f = float(err_raw) if (err_raw is not None and pd.notna(err_raw)) else None

        r = _calc_bono(equipo_cfg, base, otif_f, prod_pct, err_f, esp_f)
        pagado = _safe_float(cfg.get("bono_pagado_real_clp"), 0)

        rows_num.append({"mes_key": f"{anio}-{mes:02d}", "pozo": base,
                          "devengado": r["bono_devengado"], "pagado": pagado})
        rows_disp.append({
            "Mes": f"{anio}-{mes:02d}", "Pozo": _fmt_clp(base),
            "OTIF %": f"{otif_f:.1f}%" if otif_f else "—",
            "Unid/p/d": f"{prod_pp:.0f}" if prod_pp else "—",
            "Meta": f"{meta_m:.0f}", "Prod %": f"{prod_pct:.1f}%",
            "Espíritu": f"{esp_f:.0f}%" if esp_f else "—",
            "Factor": f"{r['factor_total']*100:.0f}%",
            "Devengado": _fmt_clp(r["bono_devengado"]),
            "Pagado": _fmt_clp(pagado) if pagado else "—",
        })

    if not rows_disp:
        st.info("Sin meses cerrados con data WMS aún.")
        return

    total_dev = sum(r["devengado"] for r in rows_num)
    total_pag = sum(r["pagado"] for r in rows_num)
    total_pozo = sum(r["pozo"] for r in rows_num)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total devengado", _fmt_clp(total_dev))
    c2.metric("Total pagado", _fmt_clp(total_pag) if total_pag else "Sin registros")
    c3.metric("Total pozo acum.", _fmt_clp(total_pozo))
    c4.metric("% pozo devengado", f"{total_dev/total_pozo*100:.1f}%" if total_pozo else "—")

    st.divider()
    df_chart = pd.DataFrame(rows_num).sort_values("mes_key")
    if not df_chart.empty:
        import altair as alt
        labels = {"pozo": "Pozo disponible", "devengado": "Devengado", "pagado": "Pagado real"}
        colores = {"pozo": "#d0d0d0", "devengado": "#1f77b4", "pagado": "#2ca02c"}
        df_melt = df_chart.melt(id_vars="mes_key", value_vars=["pozo", "devengado", "pagado"],
                                 var_name="tipo", value_name="valor")
        df_melt["tipo_label"] = df_melt["tipo"].map(labels)
        chart = (
            alt.Chart(df_melt).mark_bar(opacity=0.85)
            .encode(
                x=alt.X("mes_key:N", title="Mes", sort=None),
                y=alt.Y("valor:Q", title="CLP", axis=alt.Axis(format=",.0f")),
                color=alt.Color("tipo_label:N",
                                scale=alt.Scale(domain=list(labels.values()),
                                                range=list(colores.values())),
                                legend=alt.Legend(title="", orient="top")),
                xOffset="tipo_label:N",
                tooltip=["mes_key", "tipo_label", alt.Tooltip("valor:Q", format=",.0f", title="CLP")],
            )
            .properties(height=280, title=f"Bonos {equipo_cfg['label']}")
        )
        st.altair_chart(chart, use_container_width=True)

    st.dataframe(pd.DataFrame(rows_disp), use_container_width=True, hide_index=True)


# ── Entry point ───────────────────────────────────────────────────────────────

def render():
    st.title("🏭 Bonos — Bodega")
    st.caption(
        "**Logística:** OTIF 40% / Productividad 50% / Espíritu 10% · 3 pers × $60.000 · "
        "**Coordinador:** OTIF 30% / Prod 30% / Error Despacho 30% / Espíritu 10% · "
        "3 pers × $100.000 · Productividad = unidades / personas / días hábiles (igual que KPI WMS)."
    )

    df_cfg = _load_config()
    hoy = date.today()

    tab_log, tab_coord = st.tabs(["🏭 Logística", "📋 Coordinador Pedidos"])

    with tab_log:
        t1, t2, t3 = st.tabs(["📊 Resumen", "💵 Carga Bonos", "📈 Historial"])
        with t1:
            _tab_resumen(LOGISTICA, df_cfg, hoy)
        with t2:
            _tab_carga(LOGISTICA, df_cfg, hoy)
        with t3:
            _tab_historial(LOGISTICA, df_cfg)

    with tab_coord:
        t4, t5, t6 = st.tabs(["📊 Resumen", "💵 Carga Bonos", "📈 Historial"])
        with t4:
            _tab_resumen(COORDINADOR, df_cfg, hoy)
        with t5:
            _tab_carga(COORDINADOR, df_cfg, hoy)
        with t6:
            _tab_historial(COORDINADOR, df_cfg)
