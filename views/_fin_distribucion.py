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


# ════════════════════════════════════════════════════════════════════════════
# GAV DIRECTO POR CANAL/CATEGORÍA — Roadmap 2026-05
# Doc: docs/ROADMAP_GAV_DIRECTO_2026-05.md
# Marco teórico: Horngren, Datar & Rajan (2015), Cost Accounting 15ed, cap 14.
# ════════════════════════════════════════════════════════════════════════════

import json as _json

KAM_PARQUET = PROJECT_ROOT / "data" / "finanzas" / "contribucion_kam.parquet"

# Lista oficial de tipo_negocio (cost objects para distribución del GAV).
# Si Andrés modifica esta lista en el Sheet KAM, este código sigue funcionando
# porque consulta el universo desde los parquets — esta lista es solo fallback
# para el modo "equitativo" cuando no hay data de ventas.
TIPOS_NEGOCIO_OFICIALES = [
    "Marketplace", "Fidelización", "Páginas Propias",
    "Tiendas Propias", "Corporativo", "Distribución",
]

METODOS_VALIDOS = {
    "directo_canal", "directo_categoria", "mc_absoluto",
    "equitativo", "venta", "",  # "" = fallback heurístico
}


def _norm_tn(s: str) -> str:
    """Normaliza tipo_negocio para matching robusto (case/acentos)."""
    if not s or pd.isna(s):
        return ""
    return (str(s).strip().lower()
            .replace("á", "a").replace("é", "e").replace("í", "i")
            .replace("ó", "o").replace("ú", "u").replace("ñ", "n"))


@st.cache_data(ttl=600, show_spinner=False)
def cargar_mc_absoluto_por_tipo_negocio(year: int,
                                          meses: tuple | None = None
                                          ) -> dict:
    """Devuelve {tipo_negocio: mc_absoluto_CLP} leído del Sheet KAM.

    Se usa como driver `mc_absoluto` para distribuir gastos transversales
    (cat 2 del marco teórico). Razón: el IMA Statement 4B recomienda
    "benefits-received" sobre "ability to bear", y el MC absoluto es el
    proxy más razonable de capacidad de absorber overhead.

    MC <= 0 se excluye del reparto (se asigna 0 peso, evita distorsionar).
    """
    if not KAM_PARQUET.exists():
        return {}
    df = pd.read_parquet(KAM_PARQUET)
    df = df[df["year"] == year].copy()
    if meses:
        df = df[df["month"].isin(list(meses))]
    if df.empty or "resultado_contrib" not in df.columns:
        return {}

    agg = df.groupby("tipo_negocio")["resultado_contrib"].sum()
    # Solo positivos (MC negativo excluido del reparto)
    agg = agg[agg > 0]
    return agg.to_dict()


@st.cache_data(ttl=600, show_spinner=False)
def cargar_venta_por_categoria_tn(year: int,
                                    meses: tuple | None = None) -> pd.DataFrame:
    """Devuelve por (categoria_macro, tipo_negocio): venta_neta.

    Se usa como pesos en la cascada del modo `directo_categoria`:
    un cargo asignado a Pets se distribuye a los tipo_negocio según
    cuánto vendió Pets en cada uno.
    """
    if not VENTAS_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(VENTAS_PARQUET)
    df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce")
    f = df[df["fecha_venta"].dt.year == year].copy()
    if meses:
        f = f[f["fecha_venta"].dt.month.isin(list(meses))]
    if f.empty:
        return pd.DataFrame()

    f["tipo_negocio"] = f["tipo_negocio"].fillna("(sin clasif)").replace("", "(sin clasif)")
    f["categoria_macro"] = f["categoria_macro"].fillna("(sin cat)").replace("", "(sin cat)")
    # Limpiar valores ruidosos típicos
    f.loc[f["categoria_macro"].isin(["0", "(sin cat)"]), "categoria_macro"] = "(sin cat)"

    agg = f.groupby(["categoria_macro", "tipo_negocio"], as_index=False).agg(
        venta_neta=("venta_neta", "sum"),
    )
    agg = agg[agg["venta_neta"] > 0].copy()
    return agg


@st.cache_data(ttl=600, show_spinner=False)
def cargar_gav_con_mapping(year: int, meses: tuple | None = None,
                             escenario: str = "FCST") -> pd.DataFrame:
    """Versión extendida de `cargar_gav_corporativo` que incluye el mapping
    de distribución directa además del monto.

    Cols out: [area, sub_area, centro_costo, monto,
               metodo_asignacion, destino_tipo_negocio, destino_categoria,
               pct_asignacion, descripcion_cargo]

    Si el Sheet aún no tiene las cols nuevas → quedan vacías y la lógica
    de distribución cae al fallback heurístico (`venta`).
    """
    if not CONTROL_GESTION_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(CONTROL_GESTION_PARQUET)
    df = df[(df["year"] == year) &
            (df["escenario"] == escenario) &
            (df["kpi"] == "GASTO")].copy()
    if meses:
        df = df[df["month"].isin(list(meses))]
    if df.empty:
        return pd.DataFrame()

    # Excluir áreas operativas (ya en Costo OP)
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

    df["valor_pos"] = df["valor"].abs() * 1000

    # Agregar cols nuevas si no existen (backward compat)
    for col in ["metodo_asignacion", "destino_tipo_negocio", "destino_categoria",
                "pct_asignacion", "descripcion_cargo"]:
        if col not in df.columns:
            df[col] = ""

    # Agrupar por la mínima granularidad útil. El mapping vive a nivel
    # (area, sub_area, centro_costo, cuenta_analitica). Mantenemos cuenta
    # analítica si está, para que Andrés pueda etiquetar cargos específicos.
    group_cols = ["area", "sub_area", "centro_costo"]
    if "cuenta_analitica" in df.columns:
        group_cols.append("cuenta_analitica")
    # El mapping debe ser único por grupo. Si Andrés cargó varios métodos
    # para el mismo CC (ej: en distintos meses), tomamos el primero no vacío.
    def _first_non_empty(s):
        for v in s:
            if v and str(v).strip():
                return v
        return ""

    agg = df.groupby(group_cols, as_index=False, dropna=False).agg(
        monto=("valor_pos", "sum"),
        metodo_asignacion=("metodo_asignacion", _first_non_empty),
        destino_tipo_negocio=("destino_tipo_negocio", _first_non_empty),
        destino_categoria=("destino_categoria", _first_non_empty),
        pct_asignacion=("pct_asignacion", _first_non_empty),
        descripcion_cargo=("descripcion_cargo", _first_non_empty),
    )
    agg = agg[agg["monto"] > 0].copy()
    agg = agg.sort_values("monto", ascending=False).reset_index(drop=True)
    return agg


def _split_pct(json_or_csv: str, destinos_default: list[str]) -> dict:
    """Parsea split de porcentajes con varios formatos tolerantes:

    - JSON dict:  '{"Marketplace": 80, "Fidelización": 20}'
    - JSON list:  '[80, 20]' (se aplica a destinos_default en orden)
    - CSV simple: 'Marketplace;Fidelización' (split uniforme 50/50)
    - Vacío:      split uniforme entre destinos_default

    Devuelve {destino: peso_0a1}. Si los porcentajes no suman 100, normaliza.
    Si los destinos no están en destinos_default, los acepta igual (Andrés
    sabe mejor que el código qué tipo_negocio existe).
    """
    raw = (json_or_csv or "").strip()
    pesos: dict = {}

    if not raw:
        # Sin spec: uniforme sobre destinos_default
        if not destinos_default:
            return {}
        peso = 1.0 / len(destinos_default)
        return {d: peso for d in destinos_default}

    # Intentar JSON
    if raw.startswith("{") or raw.startswith("["):
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, dict):
                pesos = {str(k).strip(): float(v) for k, v in parsed.items()}
            elif isinstance(parsed, list):
                if len(parsed) == len(destinos_default):
                    pesos = {destinos_default[i]: float(parsed[i])
                             for i in range(len(parsed))}
        except (ValueError, TypeError):
            pass

    # Si no fue JSON o falló, intentar parse simple (split por ; o ,)
    if not pesos:
        # Si destinos_default tiene 1 solo elemento → 100% a ese
        if len(destinos_default) == 1:
            return {destinos_default[0]: 1.0}
        # Uniforme entre destinos_default
        if destinos_default:
            peso = 1.0 / len(destinos_default)
            return {d: peso for d in destinos_default}
        return {}

    # Normalizar a suma=1
    total = sum(pesos.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in pesos.items()}


def _parse_destinos_csv(s: str) -> list[str]:
    """'Marketplace;Fidelización' → ['Marketplace', 'Fidelización']"""
    if not s:
        return []
    return [x.strip() for x in str(s).replace(",", ";").split(";") if x.strip()]


def distribuir_gav_multi_modo(
    df_gav_mapping: pd.DataFrame,
    mc_por_tn: dict,
    df_venta_cat_tn: pd.DataFrame,
    tipos_negocio_universo: list[str] | None = None,
) -> pd.DataFrame:
    """Distribuye cada fila del GAV a tipo_negocio según su `metodo_asignacion`.

    Inputs:
        df_gav_mapping: output de `cargar_gav_con_mapping()`.
        mc_por_tn: output de `cargar_mc_absoluto_por_tipo_negocio()`.
        df_venta_cat_tn: output de `cargar_venta_por_categoria_tn()`.
        tipos_negocio_universo: lista oficial de tipo_negocio. Si None, se
            infiere de las claves de mc_por_tn (o TIPOS_NEGOCIO_OFICIALES
            como último recurso).

    Output (formato largo):
        [area, sub_area, centro_costo, descripcion_cargo, metodo,
         tipo_negocio, monto_asignado, nota]
    """
    if df_gav_mapping.empty:
        return pd.DataFrame()

    # Universo de tipo_negocio = unión de los que aparecen en MC>0, en ventas
    # por categoría y en la lista oficial. Garantiza que ningún canal queda
    # afuera del reparto equitativo solo porque tenga MC negativo o ventas 0.
    if tipos_negocio_universo is None:
        universo = set(TIPOS_NEGOCIO_OFICIALES)
        if mc_por_tn:
            universo.update(mc_por_tn.keys())
        if not df_venta_cat_tn.empty and "tipo_negocio" in df_venta_cat_tn.columns:
            universo.update(df_venta_cat_tn["tipo_negocio"].dropna().unique())
        # Excluir placeholders
        universo = {tn for tn in universo if tn and tn != "(sin clasif)"}
        tipos_negocio_universo = sorted(universo)

    rows = []
    for _, r in df_gav_mapping.iterrows():
        metodo_raw = (r.get("metodo_asignacion") or "").strip().lower() or "venta"
        monto = float(r["monto"])
        destinos_csv = r.get("destino_tipo_negocio", "") or ""
        destino_cat = (r.get("destino_categoria") or "").strip()
        pct_raw = r.get("pct_asignacion", "") or ""
        base = {
            "area":               r.get("area", ""),
            "sub_area":           r.get("sub_area", ""),
            "centro_costo":       r.get("centro_costo", ""),
            "descripcion_cargo":  r.get("descripcion_cargo", ""),
        }

        # Resolver pesos por tipo_negocio + nota (si hubo fallback)
        pesos_tn: dict = {}
        metodo_efectivo = metodo_raw
        nota = ""

        if metodo_raw == "directo_canal":
            destinos = _parse_destinos_csv(destinos_csv)
            if destinos:
                pesos_tn = _split_pct(pct_raw, destinos)
            else:
                metodo_efectivo = "venta"
                nota = "directo_canal sin destino — fallback a venta uniforme"

        elif metodo_raw == "directo_categoria":
            if not destino_cat or df_venta_cat_tn.empty:
                metodo_efectivo = "venta"
                nota = "directo_categoria sin destino — fallback a venta uniforme"
            else:
                ventas_cat = df_venta_cat_tn[
                    df_venta_cat_tn["categoria_macro"].str.lower() == destino_cat.lower()
                ]
                total = ventas_cat["venta_neta"].sum() if not ventas_cat.empty else 0
                if total <= 0:
                    metodo_efectivo = "equitativo"
                    nota = f"categoría '{destino_cat}' sin ventas — fallback equitativo"
                else:
                    pesos_tn = {vr["tipo_negocio"]: vr["venta_neta"] / total
                                for _, vr in ventas_cat.iterrows()}

        elif metodo_raw == "mc_absoluto":
            total_mc = sum(mc_por_tn.values()) if mc_por_tn else 0
            if total_mc <= 0:
                metodo_efectivo = "equitativo"
                nota = "MC absoluto no disponible — fallback equitativo"
            else:
                pesos_tn = {tn: mc / total_mc for tn, mc in mc_por_tn.items()}

        # Si llegamos acá con pesos vacíos y método sigue siendo "equitativo"
        # o "venta" → reparto uniforme entre el universo
        if not pesos_tn and metodo_efectivo in ("equitativo", "venta"):
            n = len(tipos_negocio_universo)
            if n > 0:
                peso = 1.0 / n
                pesos_tn = {tn: peso for tn in tipos_negocio_universo}
                if metodo_raw == "venta" and not nota:
                    nota = "sin método — fallback uniforme entre tipo_negocio"

        # Emitir filas
        for tn, peso in pesos_tn.items():
            rows.append({**base,
                          "metodo":          metodo_efectivo,
                          "tipo_negocio":    tn,
                          "monto_asignado":  monto * peso,
                          "nota":            nota})

    return pd.DataFrame(rows)


def resumen_cobertura_mapping(df_gav_mapping: pd.DataFrame) -> dict:
    """Devuelve stats de cuánto del GAV tiene método definido vs fallback."""
    if df_gav_mapping.empty:
        return {"total_mm": 0, "con_metodo_mm": 0, "pct_cobertura": 0,
                "por_metodo": {}}

    total = df_gav_mapping["monto"].sum()
    con_metodo_mask = df_gav_mapping["metodo_asignacion"].astype(str).str.strip() != ""
    con_metodo = df_gav_mapping.loc[con_metodo_mask, "monto"].sum()
    por_metodo = (df_gav_mapping.groupby(
        df_gav_mapping["metodo_asignacion"].replace("", "(sin método)")
    )["monto"].sum() / 1e6).round(1).to_dict()

    return {
        "total_mm": round(total / 1e6, 1),
        "con_metodo_mm": round(con_metodo / 1e6, 1),
        "pct_cobertura": round(con_metodo / total * 100, 0) if total > 0 else 0,
        "por_metodo": por_metodo,
    }
