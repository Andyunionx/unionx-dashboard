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
    """Determina el driver de proyección para un CC × cuenta.

    Regla actualizada (segun feedback Andres 18/may):
      1. Respetar tipo_costo del parquet:
         - FIJO -> 'fijo' (no escala)
         - VARIABLE -> escalar segun driver del CC
      2. EXCEPCION: cuentas con HORAS EXTRA u HONORARIOS se fuerzan a
         variable aunque vengan FIJO (lo dijo Andres explicitamente).
      3. Para variables, driver segun CC en DRIVER_POR_CC.
         Default 'venta' si no esta listado.
    """
    cta_u = str(cuenta_analitica or "").upper().strip()
    tcost_u = str(tipo_costo or "").upper().strip()
    cc_u = (str(cc or "").upper().strip()
            .replace("Ó", "O").replace("Á", "A").replace("É", "E")
            .replace("Í", "I").replace("Ú", "U"))

    # 1. EXCEPCION: HE / HON siempre variables (driver = venta)
    for kw in CUENTAS_VARIABLES_FORZADAS:
        if kw in cta_u or kw in cc_u:
            return "venta"

    # 2. Respetar tipo_costo del parquet: FIJO = no escala
    if tcost_u == "FIJO":
        return "fijo"

    # 3. VARIABLE: buscar driver del CC (default = venta)
    if cc_u in DRIVER_POR_CC and DRIVER_POR_CC[cc_u] != "fijo":
        return DRIVER_POR_CC[cc_u]
    return "venta"  # default conservador para variables sin mapping


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
    n_meses_real = len(meses_cerrados)  # divisor real

    # Sumar canales/LN por (CC, cta, tipo_costo, mes)
    agg = (df.groupby(
        ["centro_costo", "cuenta_analitica", "tipo_costo", "month"],
        as_index=False, dropna=False)["valor_pos"].sum())
    # FIX: promediar dividiendo siempre por N meses (no por meses en que
    # aparece la cuenta). Si MEGACENTRO ARRIENDOS aparece 1 vez en 3
    # meses con $11MM, el promedio mensual real es $11/3 = $3.7MM, no $11MM.
    prom = (agg.groupby(
        ["centro_costo", "cuenta_analitica", "tipo_costo"],
        as_index=False, dropna=False)["valor_pos"].sum()
        .rename(columns={"valor_pos": "_suma_periodo"}))
    prom["costo_mensual_prom"] = prom["_suma_periodo"] / n_meses_real
    prom = prom.drop(columns=["_suma_periodo"])
    prom = prom[prom["costo_mensual_prom"] > 0].copy()
    return prom


# ============================================================
# PROYECCIÓN
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
def cargar_costo_op_real_mensual(year: int = 2026) -> pd.DataFrame:
    """Devuelve costo OP REAL por mes (sumando todos los CCs).

    Returns DataFrame con cols [mes, costo_op_fijo, costo_op_variable,
    costo_op_total] en miles de CLP. Solo meses con datos FCST > 0.
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
    df["valor_pos"] = df["valor"].abs()
    agg = (df.groupby(["month", "tipo_costo"], as_index=False, dropna=False)
             ["valor_pos"].sum())
    pivot = agg.pivot(index="month", columns="tipo_costo",
                       values="valor_pos").fillna(0).reset_index()
    if "FIJO" not in pivot.columns:
        pivot["FIJO"] = 0
    if "VARIABLE" not in pivot.columns:
        pivot["VARIABLE"] = 0
    pivot["costo_op_fijo"] = pivot["FIJO"]
    pivot["costo_op_variable"] = pivot["VARIABLE"]
    pivot["costo_op_total"] = pivot["FIJO"] + pivot["VARIABLE"]
    pivot["mes"] = pivot["month"]
    # Solo meses con datos (costo total > 0)
    pivot = pivot[pivot["costo_op_total"] > 0].copy()
    return pivot[["mes", "costo_op_fijo", "costo_op_variable",
                   "costo_op_total"]]


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_volumen_real_mensual(year: int = 2026) -> pd.DataFrame:
    """Devuelve pedidos y unidades REALES por mes desde el parquet
    de volumen inventario (snapshot Odoo).

    Returns DataFrame con cols [mes, pedidos_real, unidades_real].
    Solo cuenta outgoing (pedidos del cliente, no transferencias).
    """
    p = PROJECT_ROOT / "data" / "operaciones" / "volumen_inventario_hist.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df["fecha_done"] = pd.to_datetime(df["fecha_done"], errors="coerce")
    df = df[df["picking_type_code"] == "outgoing"].copy()
    df = df[df["fecha_done"].dt.year == year].copy()
    if df.empty:
        return pd.DataFrame()
    df["mes"] = df["fecha_done"].dt.month
    agg = df.groupby("mes", as_index=False).agg(
        pedidos_real=("picking_id", "nunique"),
        unidades_real=("n_unidades", "sum"),
    )
    return agg


def proyectar_costo_operativo(year: int = 2026,
                                 mes_desde: int = None,
                                 mes_hasta: int = 12,
                                 driver_override: dict = None) -> pd.DataFrame:
    """Proyecta el costo operativo mes a mes (compatibilidad legacy).
    Para vista anual con mix real+proyectado, usar proyectar_anual()."""
    if mes_desde is None:
        from datetime import datetime
        mes_desde = datetime.now().month
    df = proyectar_anual(year=year, driver_override=driver_override)
    if df.empty:
        return df
    return df[(df["mes"] >= mes_desde) & (df["mes"] <= mes_hasta)].copy()


def proyectar_anual(year: int = 2026,
                     driver_override: dict = None) -> pd.DataFrame:
    """Devuelve TODOS los meses del año (1-12) mezclando:
      - REAL: meses donde el P&L tiene FCST cerrado con datos
      - PROYECTADO: meses futuros sin FCST aún cargado

    Returns DataFrame con cols:
      [mes, tipo (Real/Proyectado), venta_fcst_clp, venta_fcst_mm,
       pedidos, unidades, costo_op_fijo, costo_op_variable,
       costo_op_total, pct_sobre_venta]

    Auto-update: cuando un mes pase de "no tiene FCST" a "tiene FCST
    cargado" en el Sheet del P&L, ese mes pasa de Proyectado a Real
    automáticamente (se actualiza al refrescar el cache).
    """
    fcst_venta = cargar_fcst_venta_mensual(year)
    ratios = calcular_ratios_historicos(meses_atras=3)
    df_costos_prom = cargar_costo_op_promedio(meses_atras=3, year=year)
    df_costos_real = cargar_costo_op_real_mensual(year=year)
    df_vol_real = cargar_volumen_real_mensual(year=year)

    if fcst_venta.empty or not ratios:
        return pd.DataFrame()

    # Meses con FCST cerrado en P&L Y mes calendario ya cerrado
    # (mes < mes_actual). El mes actual y futuros son "Proyectado"
    # aunque el FCST esté cargado, porque no es data real cerrada.
    from datetime import datetime
    hoy = datetime.now()
    mes_actual = hoy.month if year == hoy.year else 13  # años pasados: todo real
    meses_con_fcst = set(df_costos_real["mes"].tolist()) if not df_costos_real.empty else set()
    meses_real = {m for m in meses_con_fcst if m < mes_actual}

    ped_ratio = ratios["ratio_pedidos_por_mm_venta"]
    und_ratio = ratios["ratio_unidades_por_mm_venta"]
    meses_usados = ratios.get("meses_usados", [])
    n_meses = max(ratios.get("n_meses", 1), 1)
    overrides = driver_override or {}

    meses_num = [int(m_str[5:7]) for m_str in meses_usados]
    venta_prom_hist = sum(fcst_venta.get(mn, 0) for mn in meses_num) / n_meses
    venta_prom_mm = venta_prom_hist / 1_000_000
    pedidos_prom_hist = venta_prom_mm * ped_ratio
    unidades_prom_hist = venta_prom_mm * und_ratio

    # Volumen real por mes (para columna "pedidos real")
    vol_real_dict = (df_vol_real.set_index("mes").to_dict("index")
                       if not df_vol_real.empty else {})

    rows = []
    for m in range(1, 13):
        venta_clp = float(fcst_venta.get(m, 0))
        venta_mm = venta_clp / 1_000_000
        es_real = m in meses_real

        if es_real:
            tipo = "Real"
            # Costo: tomar el real del P&L
            r = df_costos_real[df_costos_real["mes"] == m].iloc[0]
            costo_fijo = float(r["costo_op_fijo"])
            costo_var = float(r["costo_op_variable"])
            # Pedidos/unidades: tomar reales del inventario si los hay,
            # sino estimar con ratio
            if m in vol_real_dict:
                pedidos = float(vol_real_dict[m]["pedidos_real"])
                unidades = float(vol_real_dict[m]["unidades_real"])
            else:
                pedidos = venta_mm * ped_ratio
                unidades = venta_mm * und_ratio
        else:
            tipo = "Proyectado"
            # Proyectar con el modelo
            pedidos = venta_mm * ped_ratio
            unidades = venta_mm * und_ratio
            costo_fijo = 0.0
            costo_var = 0.0
            if not df_costos_prom.empty:
                for _, c in df_costos_prom.iterrows():
                    base = float(c["costo_mensual_prom"])
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
                        costo_fijo += base

        total = costo_fijo + costo_var
        pct = (total * 1000 / venta_clp * 100) if venta_clp else 0
        rows.append({
            "mes": m,
            "tipo": tipo,
            "venta_fcst_clp": venta_clp,
            "venta_fcst_mm": venta_mm,
            "pedidos": pedidos,
            "unidades": unidades,
            # mantengo nombres "proy" para compat con el resto del código
            "pedidos_proy": pedidos,
            "unidades_proy": unidades,
            "costo_op_fijo": costo_fijo,
            "costo_op_variable": costo_var,
            "costo_op_total": total,
            "pct_sobre_venta": pct,
        })

    return pd.DataFrame(rows)
