"""
Helper para distribuir el costo operativo (asociado a Grupo Eter como holding)
a cada CANAL de venta y, en cascada, a cada LÍNEA DE NEGOCIO.

Inputs:
  1. data/operaciones/costo_operativo.parquet — costos por CC × sub_area
  2. data/historico/ventas_historico.parquet  — pedidos/unidades/venta por canal y línea
  3. _ops_contrib_helper.contribucion_por_canal — venta/MD/contrib oficial KAM

Drivers soportados:
  - "pedidos"  → reparto proporcional a # pedidos del canal
  - "unidades" → reparto proporcional a # unidades despachadas
  - "venta"    → reparto proporcional a venta neta del canal
  - "equitativo" → reparto igual entre canales activos
  - "manual"   → permite override % por canal

Mapping default (driver natural por tipo de costo):
  REMUNERACIONES        → pedidos    (operadores procesan pedidos)
  INSUMOS               → unidades   (cartón/etiquetas escalan con unidades)
  ARRIENDOS             → pedidos    (proxy de uso de bodega; mejor sería m³)
  HONORARIOS            → venta      (asesoría/servicios escalan con venta)
  SEGUROS               → venta      (cobertura proporcional al stock movido)
  MOVILIZACIÓN          → pedidos    (despacho genera transporte)
  MANTENCIÓN ACTIVOS    → pedidos    (uso de equipos)
  GASTOS OFICINA        → venta      (servicios generales)
  SUSCRIPCIÓN/SW        → equitativo (SaaS independiente del volumen)
  BENEFICIOS PERSONAL   → pedidos    (proporcional al staff que mueve pedidos)
"""
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
COSTO_OP_PARQUET = PROJECT_ROOT / "data" / "operaciones" / "costo_operativo.parquet"
VENTAS_PARQUET = PROJECT_ROOT / "data" / "historico" / "ventas_historico.parquet"
PYL_PARQUET = PROJECT_ROOT / "data" / "finanzas" / "pyl_mensual.parquet"
CONTROL_GESTION_PARQUET = PROJECT_ROOT / "data" / "finanzas" / "control_gestion.parquet"


# ============================================================
# MAPPING DRIVER POR TIPO DE COSTO (defaults editables en la UI)
# ============================================================
DRIVER_DEFAULT_POR_CC = {
    "REMUNERACIONES":                "pedidos",
    "BENEFICIOS PERSONAL":           "pedidos",
    "HONORARIOS":                    "venta",
    # FIX 2026-05 (Andres): cambiado de 'unidades' a 'venta'. El driver
    # 'unidades' asignaba 27% del arriendo a Mercado Libre (porque mueve
    # 27% de unidades), lo cual sobreestima — ML mueve unidades chicas
    # rotativas, no ocupa 27% del espacio fisico real. 'venta' es mas
    # conservador hasta que tengamos data real de m³ x dias.
    "ARRIENDOS":                     "venta",
    "INSUMOS":                       "unidades",
    "SEGUROS":                       "venta",
    "MOVILIZACION TRANSPORTE Y COLACION": "pedidos",
    "MOVILIZACIÓN TRANSPORTE Y COLACIÓN": "pedidos",
    "MANTENCION ACTIVOS":            "pedidos",
    "MANTENCIÓN ACTIVOS":            "pedidos",
    "GASTOS OFICINA Y SERVICIOS":    "venta",
    "SUSCRIPCION Y PUBLICACIONES":   "equitativo",
    "SUSCRIPCIÓN Y PUBLICACIONES":   "equitativo",
}


# ============================================================
# DRIVERS POR ÁREA DEL GAV "PURO" (control_gestion sin operaciones)
# ============================================================
DRIVER_DEFAULT_POR_AREA_GAV = {
    "COMERCIAL":                  "venta",       # KAMs/comercial escalan con revenue
    "MARKETING":                  "venta",       # inversión proporcional al canal
    "FINANZAS Y ADMINISTRACION":  "venta",       # backoffice escala con volumen $$
    "FINANZAS Y ADMINISTRACIÓN":  "venta",
    "GRUPO ETER":                 "equitativo",  # holding apoya a todos por igual
    "LEGALES Y NOTARIALES":       "equitativo",  # servicios corporativos
    "UNIONX":                     "venta",
    "UNION X":                    "venta",
    "TIENDA":                     "venta",
}

# Áreas del control_gestion que SON operativas (ya están en costo_operativo,
# excluir para evitar duplicación)
AREAS_OPERATIVAS_EXCLUIR = {
    "OPERACIONES", "LOGISTICA", "POSTVENTA",
}


def driver_default_gav(area: str) -> str:
    """Driver para una sub-área del GAV (control de gestión)."""
    if not area:
        return "venta"
    a = area.upper().strip()
    return DRIVER_DEFAULT_POR_AREA_GAV.get(a, "venta")


def driver_default(centro_costo: str) -> str:
    """Retorna driver default para un CC dado."""
    if not centro_costo:
        return "venta"
    cc_norm = (centro_costo.upper().strip()
               .replace("Ó", "O").replace("Í", "I")
               .replace("Á", "A").replace("É", "E").replace("Ú", "U"))
    return DRIVER_DEFAULT_POR_CC.get(cc_norm, "venta")


# ============================================================
# CARGA DE INPUTS
# ============================================================
def _mtime_pyl_drive() -> float:
    """Mtime del P&L Drive (para invalidar cache cuando el cron actualiza)."""
    try:
        return CONTROL_GESTION_PARQUET.stat().st_mtime
    except (FileNotFoundError, OSError):
        return 0.0


def cargar_costos_operativos(year: int, meses: list[int] | None = None,
                              escenario: str = "FCST",
                              incluir_cuenta_analitica: bool = False) -> pd.DataFrame:
    """Devuelve costos operativos del P&L Drive (Control de Gestion)
    filtrados a area=OPERACIONES, en valores POSITIVOS y CLP enteros.

    FIX 2026-05 (Andres): antes leia data/operaciones/costo_operativo.parquet
    que tenia clasificacion rota (mezclaba GRUPO ETER, FIN/ADMIN, UNIONX
    bajo Costo Op + duplicaba con el GAV). Ahora lee la misma fuente que
    la vista de Operaciones (control_gestion.parquet con area=OPERACIONES),
    consistente con el fix de ops_costo_operativo.py.

    Si `incluir_cuenta_analitica=True`, agrupa tambien por cuenta_analitica.
    """
    return _cargar_costos_operativos_cached(
        year, tuple(meses) if meses else None, escenario,
        incluir_cuenta_analitica, _mtime_pyl_drive(),
    )


@st.cache_data(ttl=600, show_spinner=False)
def _cargar_costos_operativos_cached(year: int,
                                        meses: tuple | None,
                                        escenario: str,
                                        incluir_cuenta_analitica: bool,
                                        _mtime_key: float) -> pd.DataFrame:
    """Cacheado: invalidado cuando control_gestion.parquet cambia."""
    if not CONTROL_GESTION_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(CONTROL_GESTION_PARQUET)
    df = df[(df["year"] == year) &
            (df["escenario"] == escenario) &
            (df["kpi"] == "GASTO") &
            (df["area"] == "OPERACIONES")].copy()
    if meses:
        df = df[df["month"].isin(list(meses))]
    if df.empty:
        return pd.DataFrame()

    # FIX (Andres): sumar con SIGNO por (sub_area, CC, tipo_costo, [cta])
    # y tomar abs del NETO. Los positivos en el parquet son recuperos
    # que restan al neto — usar .abs() fila por fila inflaba el total.
    group_cols = ["sub_area", "centro_costo", "tipo_costo"]
    if incluir_cuenta_analitica and "cuenta_analitica" in df.columns:
        group_cols.append("cuenta_analitica")

    # Suma con signo en miles CLP del parquet
    agg = df.groupby(group_cols, as_index=False, dropna=False).agg(
        _suma_periodo=("valor", "sum"),
    )
    # abs del neto + convertir miles -> CLP enteros (× 1000)
    agg["monto"] = agg["_suma_periodo"].abs() * 1000
    agg = agg.drop(columns=["_suma_periodo"])
    agg = agg[agg["monto"] > 0].copy()
    agg = agg.sort_values("monto", ascending=False).reset_index(drop=True)
    return agg


@st.cache_data(ttl=600, show_spinner=False)
def cargar_ventas_canal_ln(year: int, meses: list[int] | None = None,
                            canales: list[str] | None = None,
                            kams: list[str] | None = None,
                            tipos_negocio: list[str] | None = None) -> pd.DataFrame:
    """Devuelve por (canal, tipo_negocio, kam): n_pedidos, n_unidades, venta_neta.

    Filtros opcionales para alinear con los del KAM.
    """
    if not VENTAS_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(VENTAS_PARQUET)
    df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce")
    df["year"] = df["fecha_venta"].dt.year
    df["month"] = df["fecha_venta"].dt.month
    f = df[df["year"] == year].copy()
    if meses:
        f = f[f["month"].isin(meses)]
    if f.empty:
        return pd.DataFrame()

    # Limpiar campos vacíos
    f["tipo_negocio"] = f["tipo_negocio"].fillna("(sin clasif)").replace("", "(sin clasif)")
    f["canal"] = f["canal"].fillna("(sin canal)").replace("", "(sin canal)")
    if "kam" in f.columns:
        f["kam"] = f["kam"].fillna("(sin KAM)").replace("", "(sin KAM)")

    # Aplicar filtros opcionales
    if canales:
        f = f[f["canal"].isin(canales)]
    if kams and "kam" in f.columns:
        f = f[f["kam"].isin(kams)]
    if tipos_negocio:
        f = f[f["tipo_negocio"].isin(tipos_negocio)]
    if f.empty:
        return pd.DataFrame()

    group_cols = ["canal", "tipo_negocio"]
    if "kam" in f.columns:
        group_cols.append("kam")

    agg = f.groupby(group_cols, as_index=False).agg(
        n_pedidos=("pedido", "nunique"),
        n_unidades=("cantidad", "sum"),
        venta_neta=("venta_neta", "sum"),
    )
    agg = agg[agg["venta_neta"] > 0].copy()
    return agg


@st.cache_data(ttl=600, show_spinner=False)
def cargar_gav_corporativo(year: int, meses: list[int] | None = None,
                            escenario: str = "FCST") -> pd.DataFrame:
    """Lee `control_gestion.parquet` y devuelve el GAV "puro" — solo áreas
    NO operativas (excluye OPERACIONES, LOGISTICA, POSTVENTA porque ya
    están en `costo_operativo.parquet` y se duplicarían).

    Retorna DataFrame con cols: [area, monto] en CLP enteros (positivos).
    """
    if not CONTROL_GESTION_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(CONTROL_GESTION_PARQUET)
    df = df[(df["year"] == year) &
            (df["escenario"] == escenario) &
            (df["kpi"] == "GASTO")].copy()
    if meses:
        df = df[df["month"].isin(meses)]
    if df.empty:
        return pd.DataFrame()

    # Excluir áreas operativas (ya en costo_operativo)
    def _norm(a):
        if not a:
            return ""
        return (str(a).upper().strip()
                .replace("Ó", "O").replace("Á", "A").replace("É", "E")
                .replace("Í", "I").replace("Ú", "U"))

    df["area_norm"] = df["area"].apply(_norm)
    df = df[~df["area_norm"].isin(AREAS_OPERATIVAS_EXCLUIR)].copy()
    if df.empty:
        return pd.DataFrame()

    # Convertir a positivo + CLP enteros (parquet en miles)
    df["valor_pos"] = df["valor"].abs() * 1000

    # Quitar áreas vacías
    df = df[df["area_norm"] != ""].copy()

    agg = df.groupby("area", as_index=False).agg(monto=("valor_pos", "sum"))
    agg = agg[agg["monto"] > 0].copy()
    agg = agg.sort_values("monto", ascending=False).reset_index(drop=True)
    return agg


# Alias retro-compat (la vista vieja la importaba como cargar_gav)
@st.cache_data(ttl=600, show_spinner=False)
def cargar_gav(year: int, meses: list[int] | None = None) -> float:
    """[DEPRECADO — usar cargar_gav_corporativo()] Devuelve el TOTAL del GAV
    puro en CLP enteros, sumando todas las áreas no operativas."""
    df = cargar_gav_corporativo(year, meses)
    if df.empty:
        return 0.0
    return float(df["monto"].sum())


def distribuir_monto_a_dimension(
    monto: float,
    df_ventas: pd.DataFrame,
    driver: str,
    dimension: str = "canal",
) -> dict:
    """Distribuye un monto único a la dimensión elegida usando un driver.

    dimension: "canal" | "tipo_negocio" | "kam"
    Retorna: {valor_dimension: monto_asignado}.
    """
    if df_ventas.empty or monto <= 0:
        return {}
    if dimension not in df_ventas.columns:
        return {}

    if driver == "pedidos":
        col = "n_pedidos"
    elif driver == "unidades":
        col = "n_unidades"
    elif driver == "venta":
        col = "venta_neta"
    elif driver == "equitativo":
        valores = df_ventas[dimension].unique()
        n = len(valores)
        return {v: monto / n for v in valores} if n > 0 else {}
    else:
        col = "venta_neta"

    agg = df_ventas.groupby(dimension)[col].sum()
    total = agg.sum()
    if total <= 0:
        n = len(agg)
        return {v: monto / n for v in agg.index} if n > 0 else {}
    return {v: monto * (agg[v] / total) for v in agg.index}


# ============================================================
# DISTRIBUCIÓN
# ============================================================
def calcular_pesos_canal(df_ventas: pd.DataFrame, driver: str) -> dict:
    """Devuelve {canal: peso} normalizado a 1.0 según driver."""
    if df_ventas.empty:
        return {}
    agg = df_ventas.groupby("canal", as_index=False).agg(
        n_pedidos=("n_pedidos", "sum"),
        n_unidades=("n_unidades", "sum"),
        venta_neta=("venta_neta", "sum"),
    )
    if driver == "pedidos":
        col = "n_pedidos"
    elif driver == "unidades":
        col = "n_unidades"
    elif driver == "venta":
        col = "venta_neta"
    elif driver == "equitativo":
        n = len(agg)
        return {row["canal"]: 1.0 / n for _, row in agg.iterrows()} if n > 0 else {}
    else:
        col = "venta_neta"  # fallback

    total = agg[col].sum()
    if total <= 0:
        n = len(agg)
        return {row["canal"]: 1.0 / n for _, row in agg.iterrows()} if n > 0 else {}
    return {row["canal"]: row[col] / total for _, row in agg.iterrows()}


def calcular_pesos_canal_ln(df_ventas: pd.DataFrame, driver: str) -> dict:
    """Devuelve {(canal, tipo_negocio): peso} para distribución por LN."""
    if df_ventas.empty:
        return {}
    if driver == "pedidos":
        col = "n_pedidos"
    elif driver == "unidades":
        col = "n_unidades"
    elif driver == "venta":
        col = "venta_neta"
    elif driver == "equitativo":
        n = len(df_ventas)
        return {(r["canal"], r["tipo_negocio"]): 1.0 / n
                for _, r in df_ventas.iterrows()} if n > 0 else {}
    else:
        col = "venta_neta"

    total = df_ventas[col].sum()
    if total <= 0:
        return {}
    return {(r["canal"], r["tipo_negocio"]): r[col] / total
            for _, r in df_ventas.iterrows()}


def distribuir_costo_a_canales(
    df_costos: pd.DataFrame,
    df_ventas: pd.DataFrame,
    driver_override: dict | None = None,
) -> pd.DataFrame:
    """
    Devuelve DataFrame en formato largo:
      [centro_costo, sub_area, tipo_costo, driver, canal, monto_asignado]

    driver_override: {centro_costo: driver} para sobrescribir defaults.
    """
    if df_costos.empty or df_ventas.empty:
        return pd.DataFrame()

    overrides = driver_override or {}
    rows = []
    for _, c in df_costos.iterrows():
        cc = c["centro_costo"]
        driver = overrides.get(cc, driver_default(cc))
        pesos = calcular_pesos_canal(df_ventas, driver)
        for canal, peso in pesos.items():
            rows.append({
                "centro_costo":  cc,
                "sub_area":      c["sub_area"],
                "tipo_costo":    c["tipo_costo"],
                "driver":        driver,
                "canal":         canal,
                "monto":         c["monto"] * peso,
            })

    return pd.DataFrame(rows)


def distribuir_costo_a_canal_ln(
    df_costos: pd.DataFrame,
    df_ventas: pd.DataFrame,
    driver_override: dict | None = None,
) -> pd.DataFrame:
    """Distribuye costos en cascada: primero a canal, luego a LN dentro del canal."""
    if df_costos.empty or df_ventas.empty:
        return pd.DataFrame()

    overrides = driver_override or {}
    rows = []
    for _, c in df_costos.iterrows():
        cc = c["centro_costo"]
        driver = overrides.get(cc, driver_default(cc))
        pesos = calcular_pesos_canal_ln(df_ventas, driver)
        for (canal, tipo_negocio), peso in pesos.items():
            rows.append({
                "centro_costo":   cc,
                "sub_area":       c["sub_area"],
                "tipo_costo":     c["tipo_costo"],
                "driver":         driver,
                "canal":          canal,
                "tipo_negocio":   tipo_negocio,
                "monto":          c["monto"] * peso,
            })
    return pd.DataFrame(rows)


# ============================================================
# CONSTRUCCIÓN P&L PIVOT
# ============================================================
def armar_pyl_por_canal(
    df_contrib_canal: pd.DataFrame,
    df_distrib: pd.DataFrame,
) -> pd.DataFrame:
    """
    Construye el P&L pivot por canal.

    Filas (en orden):
      Venta REAL · Costo Venta · Margen Directo · Comisiones · Contribución
      Costo Op asignado · EBIT · MC% · ROI%

    Columnas: cada canal + TOTAL.
    """
    if df_contrib_canal.empty:
        return pd.DataFrame()

    # Canal -> dict de KPIs financieros
    contrib = df_contrib_canal.set_index("canal")[
        ["venta", "costo", "margen_dir", "comisiones", "contribucion"]
    ].to_dict("index")

    # Canal -> costo operativo asignado
    costo_op = df_distrib.groupby("canal")["monto"].sum().to_dict() if not df_distrib.empty else {}

    canales = sorted(set(contrib.keys()) | set(costo_op.keys()))
    if not canales:
        return pd.DataFrame()

    rows = []
    for label in ["Venta REAL", "Costo Venta", "Margen Directo",
                  "Comisiones", "Contribución",
                  "Costo Op asignado", "EBIT", "MC %", "EBIT %"]:
        row = {"Línea P&L": label}
        for canal in canales:
            c = contrib.get(canal, {})
            venta = c.get("venta", 0)
            costo_venta = c.get("costo", 0)
            md = c.get("margen_dir", 0)
            com = c.get("comisiones", 0)
            contrib_v = c.get("contribucion", 0)
            cop = costo_op.get(canal, 0)
            ebit = contrib_v - cop

            if label == "Venta REAL":
                row[canal] = venta
            elif label == "Costo Venta":
                row[canal] = -costo_venta
            elif label == "Margen Directo":
                row[canal] = md
            elif label == "Comisiones":
                row[canal] = -com
            elif label == "Contribución":
                row[canal] = contrib_v
            elif label == "Costo Op asignado":
                row[canal] = -cop
            elif label == "EBIT":
                row[canal] = ebit
            elif label == "MC %":
                row[canal] = (contrib_v / venta * 100) if venta else 0
            elif label == "EBIT %":
                row[canal] = (ebit / venta * 100) if venta else 0
        # Total
        if label in ("MC %", "EBIT %"):
            ventas_total = sum(contrib.get(c, {}).get("venta", 0) for c in canales)
            if label == "MC %":
                num = sum(contrib.get(c, {}).get("contribucion", 0) for c in canales)
            else:
                num = sum(
                    contrib.get(c, {}).get("contribucion", 0) - costo_op.get(c, 0)
                    for c in canales
                )
            row["TOTAL"] = (num / ventas_total * 100) if ventas_total else 0
        else:
            row["TOTAL"] = sum(row[c] for c in canales)
        rows.append(row)

    return pd.DataFrame(rows)
