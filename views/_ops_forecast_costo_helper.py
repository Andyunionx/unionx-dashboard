"""
Forecast estacional de Costo Operativo 2026 (basado en FCST de venta).

Andrés pidió: usar el forecast de venta del P&L (fcst_eerr.parquet) +
los ratios históricos de pedidos/unidades por venta, para proyectar el
costo operativo hasta diciembre 2026 reconociendo la estacionalidad
(Cyber, Navidad, etc.).

MODELO:
  Para cada CC:
    - FIJO → mantener constante (promedio últimos 3 meses cerrados)
    - VARIABLE → costo_unitario_histórico × driver_pronosticado(mes)
      - driver=pedidos → ratio (costo/pedido) × pedidos_pronost
      - driver=unidades → (costo/unidad) × unidades_pronost
      - driver=venta → (costo/$venta) × venta_pronost

  Andrés mencionó específicamente que HORAS EXTRAS y HONORARIOS son
  variables que deben escalar con el volumen (no son fijos).
"""
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FCST_EERR = PROJECT_ROOT / "data" / "finanzas" / "fcst_eerr.parquet"
VOLUMEN_HIST = PROJECT_ROOT / "data" / "operaciones" / "volumen_inventario_hist.parquet"
PYL_PARQUET = PROJECT_ROOT / "data" / "finanzas" / "control_gestion.parquet"


# ============================================================
# Sub-áreas operativas (deben coincidir con SUB_AREAS_PNL)
# ============================================================
SUB_AREAS_OPS = {"LOGISTICA", "OPERACIONES", "POSTVENTA",
                  "GRUPO ETER", "UNIONX", "UNION X"}

# Cuentas analíticas que aunque caen bajo REMUNERACIONES deben tratarse
# como VARIABLES (escalan con volumen), según indicación de Andrés.
CUENTAS_VARIABLES_FORZADAS = {
    "HORAS EXTRAS", "HORAS EXTRA",
    "HONORARIOS",  # también pueden venir como CC
}

# Driver por defecto para cada CC al proyectar (consistente con la vista
# fin_pyl_linea_negocio)
DRIVER_POR_CC = {
    "REMUNERACIONES": "pedidos",
    "BENEFICIOS PERSONAL": "pedidos",
    "HONORARIOS": "venta",
    "ARRIENDOS": "fijo",  # arriendo no escala mes a mes
    "INSUMOS": "unidades",
    "SEGUROS": "venta",
    "MOVILIZACION TRANSPORTE Y COLACION": "pedidos",
    "MOVILIZACIÓN TRANSPORTE Y COLACIÓN": "pedidos",
    "MANTENCION ACTIVOS": "pedidos",
    "MANTENCIÓN ACTIVOS": "pedidos",
    "GASTOS OFICINA Y SERVICIOS": "venta",
    "SUSCRIPCION Y PUBLICACIONES": "fijo",
    "SUSCRIPCIÓN Y PUBLICACIONES": "fijo",
    "DEPRECIACION": "fijo",
    "DEPRECIACIÓN": "fijo",
}


def _driver_cc(cc: str, cuenta_analitica: str = "",
                tipo_costo: str = "") -> str:
    """Determina el driver de proyección para un CC × cuenta."""
    cta_u = str(cuenta_analitica or "").upper().strip()
    # Cuentas analíticas que fuerzan a variable
    for kw in CUENTAS_VARIABLES_FORZADAS:
        if kw in cta_u:
            return "venta"  # horas extras y honorarios escalan con venta
    cc_u = (str(cc or "").upper().strip()
            .replace("Ó", "O").replace("Á", "A").replace("É", "E")
            .replace("Í", "I").replace("Ú", "U"))
    if cc_u in DRIVER_POR_CC:
        return DRIVER_POR_CC[cc_u]
    # Default según tipo_costo del Sheet
    if str(tipo_costo or "").upper().strip() == "FIJO":
        return "fijo"
    return "venta"  # default conservador para variables


# ============================================================
# CARGA DE INPUTS
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
def cargar_fcst_venta_mensual(year: int = 2026) -> pd.Series:
    """Devuelve Series indexed por mes (1-12) con la venta FCST del año.

    Suma 'Ingreso de Explotación' + 'Otros Ingresos' (consistente con
    el revenue total del P&L corporativo).
    """
    if not FCST_EERR.exists():
        return pd.Series(dtype=float)
    df = pd.read_parquet(FCST_EERR)
    df = df[df["year"] == year].copy()
    lineas_venta = df["linea"].str.contains("Ingreso", case=False, na=False)
    df_v = df[lineas_venta]
    if df_v.empty:
        return pd.Series(dtype=float)
    return df_v.groupby("month")["valor_fcst"].sum()


@st.cache_data(ttl=3600, show_spinner=False)
def calcular_ratios_historicos(meses_atras: int = 3) -> dict:
    """Devuelve dict con ratios operativos vs venta histórica.

    Returns:
      {
        "ratio_pedidos_por_mm_venta": float,
        "ratio_unidades_por_mm_venta": float,
        "ratio_lineas_por_mm_venta": float,
        "meses_usados": [...],
        "n_meses": int,
      }
    """
    if not VOLUMEN_HIST.exists() or not FCST_EERR.exists():
        return {}

    df_op = pd.read_parquet(VOLUMEN_HIST)
    df_op["fecha_done"] = pd.to_datetime(df_op["fecha_done"], errors="coerce")
    df_op = df_op[df_op["picking_type_code"] == "outgoing"].copy()
    df_op["mes_str"] = df_op["fecha_done"].dt.to_period("M").astype(str)

    df_fcst = pd.read_parquet(FCST_EERR)
    df_fcst_v = df_fcst[df_fcst["linea"].str.contains("Ingreso", case=False,
                                                          na=False)]

    # Identificar últimos N meses cerrados disponibles en el volumen
    from datetime import datetime
    hoy = datetime.now()
    meses_disp = sorted(df_op["mes_str"].unique(), reverse=True)
    # Excluir mes actual (incompleto) y futuros
    mes_actual = hoy.strftime("%Y-%m")
    meses_validos = [m for m in meses_disp if m < mes_actual][:meses_atras]

    if not meses_validos:
        return {}

    sumas = {"pedidos": 0, "unidades": 0, "lineas": 0, "venta": 0}
    for m_str in meses_validos:
        d_op = df_op[df_op["mes_str"] == m_str]
        y, m_n = int(m_str[:4]), int(m_str[5:7])
        v = float(df_fcst_v[(df_fcst_v["year"] == y)
                              & (df_fcst_v["month"] == m_n)]["valor_fcst"].sum())
        sumas["pedidos"] += d_op["picking_id"].nunique()
        sumas["unidades"] += float(d_op["n_unidades"].sum())
        sumas["lineas"] += int(d_op["n_lineas"].sum())
        sumas["venta"] += v

    venta_mm = sumas["venta"] / 1_000_000 if sumas["venta"] else 1
    return {
        "ratio_pedidos_por_mm_venta": sumas["pedidos"] / venta_mm,
        "ratio_unidades_por_mm_venta": sumas["unidades"] / venta_mm,
        "ratio_lineas_por_mm_venta": sumas["lineas"] / venta_mm,
        "meses_usados": meses_validos,
        "n_meses": len(meses_validos),
        "_sumas": sumas,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_costo_op_promedio(meses_atras: int = 3, year: int = 2026) -> pd.DataFrame:
    """Promedio mensual de costo por (CC, cuenta_analitica, tipo_costo)
    para los últimos N meses con FCST cerrado.

    Filtra a sub-áreas operativas. Devuelve cols:
      [centro_costo, cuenta_analitica, tipo_costo, costo_mensual_prom]
    """
    if not PYL_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(PYL_PARQUET)
    df = df[
        (df["year"] == year)
        & (df["escenario"] == "FCST")
        & (df["kpi"] == "GASTO")
        & (df["sub_area"].isin(SUB_AREAS_OPS))
    ].copy()
    if df.empty:
        return pd.DataFrame()

    from datetime import datetime
    hoy = datetime.now()
    meses_disp = sorted(df["month"].unique(), reverse=True)
    meses_cerrados = [m for m in meses_disp if m < hoy.month][:meses_atras]
    if not meses_cerrados:
        meses_cerrados = meses_disp[:meses_atras]

    df = df[df["month"].isin(meses_cerrados)].copy()
    df["valor_pos"] = df["valor"].abs()

    # Sumar canales/LN por (CC, cta, tipo_costo, mes) y promediar entre meses
    agg = (df.groupby(
        ["centro_costo", "cuenta_analitica", "tipo_costo", "month"],
        as_index=False, dropna=False)["valor_pos"].sum())
    prom = (agg.groupby(
        ["centro_costo", "cuenta_analitica", "tipo_costo"],
        as_index=False, dropna=False)["valor_pos"].mean()
        .rename(columns={"valor_pos": "costo_mensual_prom"}))
    prom = prom[prom["costo_mensual_prom"] > 0].copy()
    return prom


# ============================================================
# PROYECCIÓN
# ============================================================
def proyectar_costo_operativo(year: int = 2026,
                                 mes_desde: int = None,
                                 mes_hasta: int = 12,
                                 driver_override: dict = None) -> pd.DataFrame:
    """Proyecta el costo operativo mes a mes hasta diciembre.

    Args:
      mes_desde: si None, se toma mes_actual (proyecta meses futuros)
      mes_hasta: default 12 (diciembre)
      driver_override: dict {cc: driver} para sobrescribir defaults

    Returns DataFrame con cols:
      [mes, venta_fcst, pedidos_proy, unidades_proy,
       costo_op_fijo, costo_op_variable, costo_op_total,
       pct_sobre_venta]

    Todos los montos en MISMA UNIDAD = miles de CLP (M$).
    venta_fcst es la venta del mes en miles de CLP.
    """
    if mes_desde is None:
        from datetime import datetime
        mes_desde = datetime.now().month

    # Cargar inputs
    fcst_venta = cargar_fcst_venta_mensual(year)  # en CLP enteros
    ratios = calcular_ratios_historicos(meses_atras=3)
    df_costos = cargar_costo_op_promedio(meses_atras=3, year=year)  # en miles CLP

    if fcst_venta.empty or not ratios or df_costos.empty:
        return pd.DataFrame()

    ped_ratio = ratios["ratio_pedidos_por_mm_venta"]
    und_ratio = ratios["ratio_unidades_por_mm_venta"]
    meses_usados = ratios.get("meses_usados", [])  # strings tipo "2026-02"
    n_meses = max(ratios.get("n_meses", 1), 1)
    overrides = driver_override or {}

    # PROMEDIOS HISTÓRICOS (base para calcular factor de escalado)
    # meses_usados son strings "2026-02" → extraer número
    meses_num = [int(m_str[5:7]) for m_str in meses_usados]
    venta_prom_hist = sum(fcst_venta.get(mn, 0) for mn in meses_num) / n_meses
    # En MM para los ratios
    venta_prom_mm = venta_prom_hist / 1_000_000
    pedidos_prom_hist = venta_prom_mm * ped_ratio
    unidades_prom_hist = venta_prom_mm * und_ratio

    rows = []
    for m in range(mes_desde, mes_hasta + 1):
        venta_clp = float(fcst_venta.get(m, 0))  # CLP enteros
        venta_miles = venta_clp / 1_000  # M$ (miles)
        venta_mm = venta_clp / 1_000_000  # MM$
        pedidos = venta_mm * ped_ratio
        unidades = venta_mm * und_ratio

        costo_fijo = 0.0
        costo_var = 0.0
        for _, c in df_costos.iterrows():
            base = float(c["costo_mensual_prom"])  # en miles CLP
            cc = c["centro_costo"]
            cta = c["cuenta_analitica"]
            tcost = c["tipo_costo"]
            driver = overrides.get(cc, _driver_cc(cc, cta, tcost))

            if driver == "fijo":
                costo_fijo += base
            elif driver == "pedidos":
                factor = (pedidos / pedidos_prom_hist) if pedidos_prom_hist > 0 else 1.0
                costo_var += base * factor
            elif driver == "unidades":
                factor = (unidades / unidades_prom_hist) if unidades_prom_hist > 0 else 1.0
                costo_var += base * factor
            elif driver == "venta":
                factor = (venta_clp / venta_prom_hist) if venta_prom_hist > 0 else 1.0
                costo_var += base * factor
            else:
                costo_fijo += base  # fallback

        total = costo_fijo + costo_var  # en miles CLP
        pct = (total * 1000 / venta_clp * 100) if venta_clp else 0  # ambos en CLP
        rows.append({
            "mes": m,
            "venta_fcst_clp": venta_clp,        # CLP enteros (para mostrar en MM)
            "venta_fcst_mm": venta_mm,          # MM
            "pedidos_proy": pedidos,
            "unidades_proy": unidades,
            "costo_op_fijo": costo_fijo,        # miles CLP
            "costo_op_variable": costo_var,     # miles CLP
            "costo_op_total": total,            # miles CLP
            "pct_sobre_venta": pct,             # %
        })

    return pd.DataFrame(rows)
