"""
Loader del forecast de ventas (generado por Prophet en GH Actions).

Conecta el forecast comercial (dashboard ventas) con la planificación
operacional (KPIs WMS). Lee:
  - data/forecast/forecast_resumen.json    (KPIs multi-horizonte)
  - data/forecast/forecast_anual.parquet   (proyección diaria 365d)
  - data/forecast/forecast_diario.parquet  (proyección diaria 90d)
  - data/forecast/forecast_canal.parquet   (proyección por canal)

El forecast Prophet ya incluye:
  - Trend
  - Estacionalidad semanal (días laborales vs fin de semana)
  - Estacionalidad anual (Cyber Day, Black Friday, Día Madre/Padre, FFPP, Navidad)
  - Holidays Chile

Esto reemplaza la proyección ingenua basada solo en histórico interno de picking,
que no captura estacionalidad ni eventos comerciales.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FC_DIR = PROJECT_ROOT / "data" / "forecast"


@st.cache_data(ttl=900, show_spinner=False)
def cargar_forecast_resumen() -> Dict:
    """Carga el JSON con KPIs multi-horizonte."""
    p = FC_DIR / "forecast_resumen.json"
    if not p.exists():
        return {"error": "forecast_resumen.json no existe — verificar GH Action"}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}


@st.cache_data(ttl=900, show_spinner=False)
def cargar_forecast_diario() -> pd.DataFrame:
    """Forecast diario completo (histórico + 365d adelante).

    Cols: ds (datetime), yhat, yhat_lower, yhat_upper (CLP)
    """
    p = FC_DIR / "forecast_anual.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


@st.cache_data(ttl=900, show_spinner=False)
def proyeccion_mensual_ventas(meses_adelante: int = 6) -> List[Dict]:
    """Proyección mensual en $ de los próximos N meses (incluye mes actual).

    Returns:
        [{mes_str, mes_num, anio, proyeccion_clp, banda_inferior, banda_superior,
          tipo (real/mixto/forecast)}, ...]
    """
    resumen = cargar_forecast_resumen()
    if "error" in resumen:
        return []

    tabla = resumen.get("anio_proyeccion", {}).get("tabla_mensual", [])
    if not tabla:
        return []

    anio = resumen.get("anio", datetime.now().year)
    hoy = datetime.now()
    mes_actual = hoy.month

    # Cargar daily para calcular bandas mensuales (sumar yhat_lower y yhat_upper por mes)
    df_d = cargar_forecast_diario()
    bandas = {}
    if not df_d.empty:
        df_d["mes"] = pd.to_datetime(df_d["ds"]).dt.month
        df_d["anio"] = pd.to_datetime(df_d["ds"]).dt.year
        # Solo año actual
        df_year = df_d[df_d["anio"] == anio]
        if not df_year.empty:
            grouped = df_year.groupby("mes").agg(
                yhat_lower_sum=("yhat_lower", "sum"),
                yhat_upper_sum=("yhat_upper", "sum"),
            )
            bandas = grouped.to_dict("index")

    out = []
    for r in tabla:
        m_num = r.get("mes")
        if m_num < mes_actual:
            continue  # Solo desde mes actual hacia adelante
        if len(out) >= meses_adelante:
            break
        b = bandas.get(m_num, {})
        out.append({
            "mes_str": f"{anio}-{m_num:02d}",
            "mes_num": m_num,
            "anio": anio,
            "mes_nombre": r.get("mes_nombre", ""),
            "proyeccion_clp": r.get("proyeccion", 0),
            "banda_inferior": b.get("yhat_lower_sum", 0),
            "banda_superior": b.get("yhat_upper_sum", 0),
            "venta_ly": r.get("venta_ly", 0),
            "pct_vs_ly": r.get("pct_vs_ly", 0),
            "tipo": r.get("tipo", ""),
        })
    return out


@st.cache_data(ttl=900, show_spinner=False)
def horizontes_resumen() -> Dict:
    """KPIs multi-horizonte (30d, 60d, 90d) del forecast."""
    res = cargar_forecast_resumen()
    if "error" in res:
        return {"error": res["error"]}
    return {
        "venta_actual_mes": res.get("venta_actual_mes", 0),
        "venta_pendiente_estimada": res.get("venta_pendiente_estimada", 0),
        "proyeccion_mes": res.get("proyeccion_mes", 0),
        "venta_ly_mes_completo": res.get("venta_ly_mes_completo", 0),
        "pct_vs_ly": res.get("pct_vs_ly", 0),
        "horizontes": res.get("horizontes", {}),
        "generado_en": res.get("generado_en", ""),
        "error": None,
    }
