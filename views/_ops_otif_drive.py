"""
Helper OTIF desde Google Sheet "RESUMEN MENSUAL OTIF".

URL: https://docs.google.com/spreadsheets/d/1OSvJ0sO4H4VgU9Ac0GW5mpCjdCJL2N61dcYZpkxFbCo
Worksheet principal: "REPORTE EMPRESA 2026"

Reemplaza la lógica anterior de OTIF que usaba stock.picking de Odoo.
Esta es la fuente OFICIAL de OTIF en UnionX.

Estructura del Sheet:
  - FECHA (venta)
  - CLIENTE (canal: KITCHEN CENTER, NDS, etc.)
  - CURIER (BLUEXPRESS, WELIVERY, etc.)
  - ORDEN (id pedido)
  - ESTADO CLIENTE (ENTREGADO, etc.)
  - ESTADO INTERNO (DESPACHADO, etc.)
  - FECHA COMPROMISO de entrega al curier
  - FECHA ENTREGADO A CURIER
  - DÍAS EMPRESA (diferencia: -1 = adelantado, 0 = on-time, >0 = tarde)
  - Estado Empresa ("A Tiempo" / "Tarde")
  - FECHA PROMESA COURIER
  - FECHA ENTREGA COURIER2
  - DÍAS (diferencia courier)
  - CUMPLIMIENTO COURIER ("A Tiempo" / "Tarde")
  - $ TASA DE CANCELACIÓN
  - $ TASA DE QUIEBRE
  - SKU, SERVICIO

KPIs derivados:
  - OTIF Empresa: % órdenes con Estado Empresa = "A Tiempo"
  - OTIF Courier: % órdenes con CUMPLIMIENTO COURIER = "A Tiempo"
  - OTIF Total (E2E): ambos a tiempo
  - Por canal/cliente, por courier, por mes
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHEET_ID = "1OSvJ0sO4H4VgU9Ac0GW5mpCjdCJL2N61dcYZpkxFbCo"
WORKSHEET_NAME = "REPORTE EMPRESA 2026"


def _normalizar_otif_df(rows: list, fecha_col_alt: str = None) -> pd.DataFrame:
    """Normaliza un DataFrame OTIF (independiente del año/sheet de origen).

    Args:
        rows: lista de filas (incluye header en row 0)
        fecha_col_alt: si la columna fecha tiene otro nombre (ej "Fecha venta" en 2025)
    """
    if not rows or len(rows) < 2:
        return pd.DataFrame()

    headers = [h.strip() for h in rows[0]]
    df = pd.DataFrame(rows[1:], columns=headers)
    df.columns = [c if c else f"col_{i}" for i, c in enumerate(df.columns)]

    # Renombrar columnas alternativas (para compat 2025 vs 2026)
    rename_map = {}
    if fecha_col_alt and fecha_col_alt in df.columns:
        rename_map[fecha_col_alt] = "FECHA"
    if "Concepto" in df.columns and "Estado Empresa" not in df.columns:
        rename_map["Concepto"] = "Estado Empresa"
    if "Fecha venta" in df.columns and "FECHA" not in df.columns:
        rename_map["Fecha venta"] = "FECHA"
    if "ESTADO" in df.columns and "ESTADO CLIENTE" not in df.columns:
        rename_map["ESTADO"] = "ESTADO CLIENTE"
    if "TIPO DE DESPACHO" in df.columns and "SERVICIO" not in df.columns:
        rename_map["TIPO DE DESPACHO"] = "SERVICIO"
    if rename_map:
        df = df.rename(columns=rename_map)

    if "FECHA" not in df.columns:
        return pd.DataFrame()

    # Limpiar filas vacías
    df = df.dropna(subset=["FECHA"], how="all")
    df = df[df["FECHA"].astype(str).str.strip() != ""]

    # Normalizar fechas
    df["FECHA"] = pd.to_datetime(
        df["FECHA"].astype(str).str.replace("-", "/"),
        format="%d/%m/%Y", errors="coerce"
    )
    df = df.dropna(subset=["FECHA"])
    df["MES"] = df["FECHA"].dt.to_period("M").astype(str)

    # Estado Empresa puede venir como "A Tiempo" / "Tarde" / "Demorado"
    if "Estado Empresa" in df.columns:
        df["Estado Empresa"] = df["Estado Empresa"].astype(str).str.strip()
        df["empresa_a_tiempo"] = df["Estado Empresa"].str.lower().eq("a tiempo")
    else:
        df["empresa_a_tiempo"] = False

    if "CUMPLIMIENTO COURIER" in df.columns:
        df["CUMPLIMIENTO COURIER"] = df["CUMPLIMIENTO COURIER"].astype(str).str.strip()
        df["courier_a_tiempo"] = df["CUMPLIMIENTO COURIER"].str.lower().eq("a tiempo")
    else:
        df["courier_a_tiempo"] = False

    df["otif_total"] = df["empresa_a_tiempo"] & df["courier_a_tiempo"]

    # Días (varios encodings posibles)
    for col in ["D�AS EMPRESA", "DÍAS EMPRESA", "DIAS EMPRESA"]:
        if col in df.columns:
            df["dias_empresa"] = pd.to_numeric(df[col], errors="coerce")
            break
    for col in ["D�AS", "DÍAS", "DIAS"]:
        if col in df.columns:
            df["dias_courier"] = pd.to_numeric(df[col], errors="coerce")
            break

    return df


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_otif_drive() -> pd.DataFrame:
    """Carga ambas hojas (2026 + 2025) y devuelve DataFrame combinado normalizado.

    Cache 1h. Se invalida con el botón "Refrescar Odoo" del sidebar
    o automáticamente cada hora.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return pd.DataFrame()

    # Credenciales: archivo local o secrets
    creds_path = PROJECT_ROOT / "credentials.json"
    if creds_path.exists():
        creds = Credentials.from_service_account_file(
            str(creds_path),
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly",
                    "https://www.googleapis.com/auth/drive.readonly"],
        )
    else:
        try:
            creds_info = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(
                creds_info,
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly",
                        "https://www.googleapis.com/auth/drive.readonly"],
            )
        except Exception:
            return pd.DataFrame()

    try:
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
    except Exception as e:
        print(f"[ops_otif_drive] Error abriendo Sheet: {e}")
        return pd.DataFrame()

    dfs = []

    # 1. 2026 — REPORTE EMPRESA 2026
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
        rows = ws.get_all_values()
        df_2026 = _normalizar_otif_df(rows)
        if not df_2026.empty:
            dfs.append(df_2026)
            print(f"[ops_otif_drive] {WORKSHEET_NAME}: {len(df_2026):,} filas")
    except Exception as e:
        print(f"[ops_otif_drive] Error leyendo {WORKSHEET_NAME}: {e}")

    # 2. 2025 — COMPILADO AÑO 2025 (estructura distinta, normalizada por _normalizar)
    for sheet_name in ["COMPILADO AÑO 2025", "COMPILADO A�O 2025"]:
        try:
            ws = sh.worksheet(sheet_name)
            rows = ws.get_all_values()
            df_2025 = _normalizar_otif_df(rows)
            if not df_2025.empty:
                dfs.append(df_2025)
                print(f"[ops_otif_drive] {sheet_name}: {len(df_2025):,} filas")
            break
        except Exception:
            continue

    if not dfs:
        return pd.DataFrame()

    # Concatenar y deduplicar por ORDEN si hubiera overlap
    df = pd.concat(dfs, ignore_index=True, sort=False)
    if "ORDEN" in df.columns:
        df = df.drop_duplicates(subset=["ORDEN", "FECHA"], keep="last")
    return df


def kpi_otif_resumen(mes: str = None) -> Dict:
    """KPIs principales OTIF para un mes (YYYY-MM) o todo el rango."""
    df = cargar_otif_drive()
    if df.empty:
        return {"error": "Sin datos del Sheet OTIF"}

    if mes:
        df = df[df["MES"] == mes]

    if df.empty:
        return {"error": f"Sin datos para {mes}"}

    n = len(df)
    n_emp = int(df["empresa_a_tiempo"].sum())
    n_cou = int(df["courier_a_tiempo"].sum())
    n_total = int(df["otif_total"].sum())

    return {
        "n_pedidos": n,
        "otif_empresa_pct": n_emp / n if n else 0,
        "otif_courier_pct": n_cou / n if n else 0,
        "otif_total_pct": n_total / n if n else 0,
        "n_empresa_ok": n_emp,
        "n_courier_ok": n_cou,
        "n_otif_ok": n_total,
        "dias_empresa_promedio": float(df["dias_empresa"].mean()) if "dias_empresa" in df.columns else None,
        "dias_courier_promedio": float(df["dias_courier"].mean()) if "dias_courier" in df.columns else None,
        "mes": mes,
        "error": None,
    }


def kpi_otif_por_mes() -> List[Dict]:
    """OTIF mensual (todos los meses con data)."""
    df = cargar_otif_drive()
    if df.empty:
        return []

    grouped = df.groupby("MES").agg(
        n_pedidos=("ORDEN", "count"),
        otif_empresa=("empresa_a_tiempo", "mean"),
        otif_courier=("courier_a_tiempo", "mean"),
        otif_total=("otif_total", "mean"),
    ).reset_index().sort_values("MES")
    grouped["otif_empresa_pct"] = (grouped["otif_empresa"] * 100).round(1)
    grouped["otif_courier_pct"] = (grouped["otif_courier"] * 100).round(1)
    grouped["otif_total_pct"] = (grouped["otif_total"] * 100).round(1)
    return grouped.to_dict("records")


def kpi_otif_por_cliente(mes: str = None, top_n: int = 20) -> List[Dict]:
    """OTIF por canal/cliente."""
    df = cargar_otif_drive()
    if df.empty:
        return []
    if mes:
        df = df[df["MES"] == mes]

    grouped = df.groupby("CLIENTE").agg(
        n_pedidos=("ORDEN", "count"),
        otif_empresa=("empresa_a_tiempo", "mean"),
        otif_courier=("courier_a_tiempo", "mean"),
        otif_total=("otif_total", "mean"),
    ).reset_index()
    grouped = grouped[grouped["n_pedidos"] >= 5]  # filtro ruido
    grouped["otif_empresa_pct"] = (grouped["otif_empresa"] * 100).round(1)
    grouped["otif_courier_pct"] = (grouped["otif_courier"] * 100).round(1)
    grouped["otif_total_pct"] = (grouped["otif_total"] * 100).round(1)
    grouped = grouped.sort_values("n_pedidos", ascending=False).head(top_n)
    return grouped.to_dict("records")


def kpi_otif_por_courier(mes: str = None) -> List[Dict]:
    """OTIF por courier."""
    df = cargar_otif_drive()
    if df.empty:
        return []
    if mes:
        df = df[df["MES"] == mes]

    grouped = df.groupby("CURIER").agg(
        n_pedidos=("ORDEN", "count"),
        otif_courier=("courier_a_tiempo", "mean"),
        dias_promedio=("dias_courier", "mean"),
    ).reset_index()
    grouped = grouped[grouped["n_pedidos"] >= 5]
    grouped["otif_courier_pct"] = (grouped["otif_courier"] * 100).round(1)
    grouped["dias_promedio"] = grouped["dias_promedio"].round(1)
    grouped = grouped.sort_values("n_pedidos", ascending=False)
    return grouped.to_dict("records")


def top_pedidos_tarde(mes: str = None, top_n: int = 50) -> List[Dict]:
    """Top pedidos con mayor atraso (días courier)."""
    df = cargar_otif_drive()
    if df.empty:
        return []
    if mes:
        df = df[df["MES"] == mes]

    if "dias_courier" not in df.columns:
        return []
    tarde = df[df["dias_courier"] > 0].copy()
    tarde = tarde.nlargest(top_n, "dias_courier")
    cols = ["FECHA", "ORDEN", "CLIENTE", "CURIER",
            "Estado Empresa", "CUMPLIMIENTO COURIER",
            "dias_empresa", "dias_courier"]
    cols = [c for c in cols if c in tarde.columns]
    tarde["FECHA"] = tarde["FECHA"].dt.strftime("%Y-%m-%d")
    return tarde[cols].to_dict("records")


def meses_disponibles() -> List[str]:
    """Lista de meses con data en el Sheet."""
    df = cargar_otif_drive()
    if df.empty:
        return []
    return sorted(df["MES"].unique().tolist(), reverse=True)


# ============================================================
# CORTE OTIF 26-25 (formato Apps Script)
# ============================================================
def cortes_otif_disponibles() -> List[Dict]:
    """Cortes mensuales tipo Apps Script: del 26 del mes anterior al 25 del mes objetivo.

    Returns: [{label, mes, anio, desde, hasta}, ...] ordenado descendente.
    """
    df = cargar_otif_drive()
    if df.empty:
        return []
    out = []
    meses_unicos = sorted(df["MES"].unique().tolist())
    nombres_es = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    for m_str in meses_unicos:
        try:
            anio, mes = map(int, m_str.split("-"))
        except Exception:
            continue
        # Corte = día 26 mes anterior → día 25 mes actual
        if mes == 1:
            desde = pd.Timestamp(year=anio - 1, month=12, day=26)
        else:
            desde = pd.Timestamp(year=anio, month=mes - 1, day=26)
        hasta = pd.Timestamp(year=anio, month=mes, day=25)
        label = f"Corte {nombres_es[mes-1]} {anio} ({desde.strftime('%d-%m')} al {hasta.strftime('%d-%m')})"
        out.append({"label": label, "mes": mes, "anio": anio,
                    "desde": desde.strftime("%Y-%m-%d"),
                    "hasta": hasta.strftime("%Y-%m-%d"),
                    "key": f"{anio}-{mes:02d}"})
    return sorted(out, key=lambda x: x["key"], reverse=True)


def _filtrar_corte(df: pd.DataFrame, desde: str, hasta: str,
                   courier: str = None, cliente: str = None,
                   servicio: str = None) -> pd.DataFrame:
    """Filtra df por corte y filtros opcionales."""
    f = df[(df["FECHA"] >= pd.Timestamp(desde)) & (df["FECHA"] <= pd.Timestamp(hasta))].copy()
    if courier and courier != "Todos":
        f = f[f["CURIER"].astype(str).str.strip().str.lower() == courier.strip().lower()]
    if cliente and cliente != "Todos":
        f = f[f["CLIENTE"].astype(str).str.strip().str.upper() == cliente.strip().upper()]
    if servicio and servicio != "Todos":
        f = f[f.get("SERVICIO", pd.Series([])).astype(str).str.strip().str.lower() == servicio.strip().lower()]
    return f


def dashboard_otif_corte(corte_key: str, courier: str = None,
                         cliente: str = None, servicio: str = None) -> Dict:
    """Dashboard OTIF completo para un corte (formato Apps Script).

    Returns dict con TODO lo que muestra el Apps Script:
      - resumen: $ cancelacion, $ quiebre, NS empresa, NS courier, OTIF total
      - por_cliente: tabla pivot con cliente x métricas
      - pareto_quiebres: top SKUs por $ quiebre con % acumulado
      - opciones_filtros: couriers, clientes, servicios disponibles
    """
    df = cargar_otif_drive()
    if df.empty:
        return {"error": "Sin datos del Sheet OTIF"}

    cortes = cortes_otif_disponibles()
    corte = next((c for c in cortes if c["key"] == corte_key), None)
    if not corte:
        return {"error": f"Corte {corte_key} no disponible"}

    # Opciones de filtros (basadas en TODO el rango, no solo el corte)
    f_all = df[(df["FECHA"] >= pd.Timestamp(corte["desde"])) &
               (df["FECHA"] <= pd.Timestamp(corte["hasta"]))].copy()
    opc_couriers = sorted([c for c in f_all["CURIER"].astype(str).str.strip().unique() if c])
    opc_clientes = sorted([c for c in f_all["CLIENTE"].astype(str).str.strip().unique() if c])
    opc_servicios = sorted([s for s in f_all.get("SERVICIO", pd.Series([])).astype(str).str.strip().unique() if s])

    # Aplicar filtros
    f = _filtrar_corte(df, corte["desde"], corte["hasta"], courier, cliente, servicio)
    if f.empty:
        return {
            "corte": corte,
            "n_ordenes": 0,
            "resumen": {"n_ordenes": 0, "cancelacion_clp": 0, "quiebre_clp": 0,
                         "n_canceladas": 0, "n_quiebres": 0,
                         "ns_empresa_pct": None, "ns_courier_pct": None,
                         "otif_total_pct": None, "n_empresa_ok": 0, "n_courier_ok": 0, "n_otif_ok": 0},
            "por_cliente": [], "pareto_quiebres": [],
            "opciones_filtros": {"couriers": opc_couriers, "clientes": opc_clientes,
                                  "servicios": opc_servicios},
            "error": None,
        }

    n = len(f)
    n_emp = int(f["empresa_a_tiempo"].sum())
    n_cou = int(f["courier_a_tiempo"].sum())
    n_total = int(f["otif_total"].sum())

    # $ Cancelación y $ Quiebre
    # IMPORTANTE: el Sheet usa formato chileno (coma como decimal, ej: "6705,88")
    # NO confundir con formato USA (coma como miles).
    def _parse_clp(serie):
        """Parsea montos CLP estilo chileno: '1.234,56' o '6705,88' o '8395'."""
        s = serie.astype(str).str.strip().str.replace("$", "", regex=False).str.replace(" ", "", regex=False)
        # Si tiene punto Y coma → formato chileno completo (punto=miles, coma=decimal)
        # Si solo coma → coma es decimal
        # Si solo punto → asumir decimal (raro)
        # Si ninguno → entero
        def _conv(v):
            if not v or v == "nan":
                return 0
            if "." in v and "," in v:
                # Chileno: 1.234,56 → 1234.56
                v = v.replace(".", "").replace(",", ".")
            elif "," in v:
                # Coma decimal: 6705,88 → 6705.88
                v = v.replace(",", ".")
            try:
                return float(v)
            except Exception:
                return 0
        return s.apply(_conv)

    canc_col = next((c for c in f.columns if "CANCELACI" in c.upper()), None)
    quie_col = next((c for c in f.columns if "QUIEBRE" in c.upper()), None)
    canc_serie = _parse_clp(f[canc_col]) if canc_col else pd.Series([0])
    quie_serie = _parse_clp(f[quie_col]) if quie_col else pd.Series([0])
    canc_clp = float(canc_serie.sum())
    quie_clp = float(quie_serie.sum())
    n_canc = int((canc_serie > 0).sum())
    n_quie = int((quie_serie > 0).sum())

    resumen = {
        "n_ordenes": n,
        "cancelacion_clp": canc_clp,
        "quiebre_clp": quie_clp,
        "n_canceladas": n_canc,
        "n_quiebres": n_quie,
        "ns_empresa_pct": n_emp / n if n else 0,
        "ns_courier_pct": n_cou / n if n else 0,
        "otif_total_pct": n_total / n if n else 0,
        "n_empresa_ok": n_emp,
        "n_courier_ok": n_cou,
        "n_otif_ok": n_total,
    }

    # Por cliente (pivot)
    g = f.groupby("CLIENTE").agg(
        ORDENES=("ORDEN", "count"),
        A_TPO_EMP=("empresa_a_tiempo", "sum"),
        A_TPO_COU=("courier_a_tiempo", "sum"),
        OTIF=("otif_total", "sum"),
    ).reset_index()
    g["NS_EMP_PCT"] = (g["A_TPO_EMP"] / g["ORDENES"]).round(4)
    g["NS_COU_PCT"] = (g["A_TPO_COU"] / g["ORDENES"]).round(4)
    g["OTIF_PCT"] = (g["OTIF"] / g["ORDENES"]).round(4)
    g = g.sort_values("ORDENES", ascending=False)
    por_cliente = g.to_dict("records")
    # Total
    if n > 0:
        por_cliente.append({
            "CLIENTE": "TOTAL", "ORDENES": n,
            "A_TPO_EMP": n_emp, "NS_EMP_PCT": n_emp / n,
            "A_TPO_COU": n_cou, "NS_COU_PCT": n_cou / n,
            "OTIF": n_total, "OTIF_PCT": n_total / n,
        })

    # Pareto de quiebres por SKU
    sku_col = next((c for c in f.columns if c.upper() == "SKU"), None)
    pareto = []
    if sku_col and quie_col:
        f_quie = f[quie_serie > 0].copy()
        if not f_quie.empty:
            f_quie["quiebre_num"] = _parse_clp(f_quie[quie_col])
            pareto_g = f_quie.groupby(sku_col).agg(
                monto=("quiebre_num", "sum"),
                n_ordenes=("ORDEN", "count"),
            ).reset_index().sort_values("monto", ascending=False)
            total_quiebre = pareto_g["monto"].sum()
            pareto_g["pct"] = pareto_g["monto"] / total_quiebre if total_quiebre else 0
            pareto_g["pct_acumulado"] = pareto_g["pct"].cumsum()
            pareto = pareto_g.head(20).to_dict("records")

    return {
        "corte": corte,
        "resumen": resumen,
        "por_cliente": por_cliente,
        "pareto_quiebres": pareto,
        "opciones_filtros": {
            "couriers": ["Todos"] + opc_couriers,
            "clientes": ["Todos"] + opc_clientes,
            "servicios": ["Todos"] + opc_servicios,
        },
        "filtros_aplicados": {
            "courier": courier or "Todos",
            "cliente": cliente or "Todos",
            "servicio": servicio or "Todos",
        },
        "error": None,
    }


# ============================================================
# YTD ACUMULADO + COMPARACIÓN DE COURIERS (base corte 26-25)
# ============================================================
_COU_MIN_PEDIDOS = 20   # umbral para descartar couriers marginales/ruido
_CORTE_MIN_ORDENES = 50  # umbral para descartar cortes ruido (fechas mal digitadas)

# Alias de couriers: consolida el mismo courier que aparece con nombres
# distintos en el Sheet (renombres, variantes). Se aplica ANTES del groupby
# para que el volumen y el NS% queden unificados. Editable a mano.
_COURIER_ALIAS = {
    "HDC": "HOME DELIVERY CORP",
    "HOME DELIVERY": "HOME DELIVERY CORP",
    "COLECTA 2": "COLECTA",
}


def _norm_courier(serie: pd.Series) -> pd.Series:
    """Normaliza nombre de courier: trim + mayúsculas + alias de consolidación."""
    s = serie.astype(str).str.strip().str.upper()
    return s.replace(_COURIER_ALIAS)


def cortes_validos(df: pd.DataFrame = None) -> List[Dict]:
    """Todos los cortes 26-25 CERRADOS (hasta <= hoy) y con volumen real.

    Descarta el corte en curso (mes actual sin cerrar) y los cortes ruido
    (meses mal digitados en el Sheet). Orden descendente por clave.
    """
    if df is None:
        df = cargar_otif_drive()
    if df.empty:
        return []
    hoy = pd.Timestamp(datetime.now().date())
    out = []
    for c in cortes_otif_disponibles():
        if pd.Timestamp(c["hasta"]) > hoy:
            continue  # corte aún no cierra
        f = df[(df["FECHA"] >= pd.Timestamp(c["desde"])) &
               (df["FECHA"] <= pd.Timestamp(c["hasta"]))]
        if len(f) >= _CORTE_MIN_ORDENES:
            out.append(c)
    return sorted(out, key=lambda x: x["key"], reverse=True)


def _cortes_cerrados(anio: int, df: pd.DataFrame) -> List[Dict]:
    """Cortes cerrados del año, ascendente (para acumular YTD)."""
    return sorted([c for c in cortes_validos(df) if c["anio"] == anio],
                  key=lambda x: x["key"])


def couriers_por_corte(corte_key: str) -> List[Dict]:
    """Desglose por courier DENTRO de un corte 26-25.

    Devuelve NS courier %, NS empresa %, OTIF total E2E % y volumen por courier.
    """
    df = cargar_otif_drive()
    if df.empty:
        return []
    corte = next((c for c in cortes_otif_disponibles() if c["key"] == corte_key), None)
    if not corte:
        return []
    f = df[(df["FECHA"] >= pd.Timestamp(corte["desde"])) &
           (df["FECHA"] <= pd.Timestamp(corte["hasta"]))].copy()
    if f.empty:
        return []
    f["CURIER"] = _norm_courier(f["CURIER"])
    f = f[f["CURIER"] != ""]
    g = f.groupby("CURIER").agg(
        n_pedidos=("ORDEN", "count"),
        empresa_ok=("empresa_a_tiempo", "sum"),
        courier_ok=("courier_a_tiempo", "sum"),
        otif_ok=("otif_total", "sum"),
    ).reset_index()
    g = g[g["n_pedidos"] >= _COU_MIN_PEDIDOS]
    if g.empty:
        return []
    g["ns_courier_pct"] = (g["courier_ok"] / g["n_pedidos"] * 100).round(1)
    g["ns_empresa_pct"] = (g["empresa_ok"] / g["n_pedidos"] * 100).round(1)
    g["otif_total_pct"] = (g["otif_ok"] / g["n_pedidos"] * 100).round(1)
    g = g.sort_values("n_pedidos", ascending=False)
    return g[["CURIER", "n_pedidos", "ns_courier_pct", "ns_empresa_pct",
              "otif_total_pct"]].to_dict("records")


def _aplica_filtros_otif(f: pd.DataFrame, courier: str = None,
                         cliente: str = None) -> pd.DataFrame:
    """Filtra por courier (nombre consolidado vía alias) y/o canal/cliente."""
    if courier and str(courier).strip().lower() not in ("", "todos"):
        f = f[_norm_courier(f["CURIER"]) == str(courier).strip().upper()]
    if cliente and str(cliente).strip().lower() not in ("", "todos"):
        f = f[f["CLIENTE"].astype(str).str.strip().str.upper() == str(cliente).strip().upper()]
    return f


def kpi_otif_ytd(anio: int = None, courier: str = None,
                 cliente: str = None) -> Dict:
    """OTIF acumulado del año (YTD) sobre base de cortes 26-25 cerrados.

    Filtros opcionales por courier (nombre consolidado) y/o canal (cliente).

    Returns:
      - resumen YTD (NS empresa / NS courier / OTIF total E2E, ponderado por órdenes)
      - trend: métricas por corte (para la curva mensual)
      - por_courier: ranking YTD por courier (NS courier %, OTIF E2E %, volumen)
      - opciones: {couriers, clientes} para poblar los filtros (sobre la
        ventana completa, independiente del filtro activo)
    """
    df = cargar_otif_drive()
    if df.empty:
        return {"error": "Sin datos del Sheet OTIF"}
    if anio is None:
        anios = {c["anio"] for c in cortes_otif_disponibles()}
        anio = max(anios) if anios else datetime.now().year
    cortes = _cortes_cerrados(anio, df)
    if not cortes:
        return {"error": f"Sin cortes cerrados con datos para {anio}", "anio": anio}

    d0 = min(pd.Timestamp(c["desde"]) for c in cortes)
    d1 = max(pd.Timestamp(c["hasta"]) for c in cortes)
    f_win = df[(df["FECHA"] >= d0) & (df["FECHA"] <= d1)].copy()

    # Opciones de filtro (sobre ventana COMPLETA, no la filtrada)
    cou_all = _norm_courier(f_win["CURIER"])
    opc_couriers = sorted([c for c in cou_all[cou_all != ""].value_counts()
                           [lambda s: s >= _COU_MIN_PEDIDOS].index.tolist() if c])
    cli_series = f_win["CLIENTE"].astype(str).str.strip().str.upper()
    opc_clientes = sorted([c for c in cli_series[cli_series != ""].value_counts()
                           [lambda s: s >= _COU_MIN_PEDIDOS].index.tolist()
                           if c and c != "NAN"])
    opciones = {"couriers": ["Todos"] + opc_couriers,
                "clientes": ["Todos"] + opc_clientes}

    # Aplicar filtros
    f = _aplica_filtros_otif(f_win, courier, cliente)

    n = len(f)
    if n == 0:
        return {
            "anio": anio, "cortes": [c["key"] for c in cortes],
            "ventana": {"desde": d0.strftime("%Y-%m-%d"), "hasta": d1.strftime("%Y-%m-%d")},
            "n_ordenes": 0, "n_empresa_ok": 0, "n_courier_ok": 0, "n_otif_ok": 0,
            "ns_empresa_pct": None, "ns_courier_pct": None, "otif_total_pct": None,
            "trend": [], "por_courier": [], "opciones": opciones,
            "filtros": {"courier": courier or "Todos", "cliente": cliente or "Todos"},
            "error": None,
        }
    n_emp = int(f["empresa_a_tiempo"].sum())
    n_cou = int(f["courier_a_tiempo"].sum())
    n_tot = int(f["otif_total"].sum())

    # Tendencia por corte (respeta filtros)
    trend = []
    for c in cortes:
        fc = f[(f["FECHA"] >= pd.Timestamp(c["desde"])) &
               (f["FECHA"] <= pd.Timestamp(c["hasta"]))]
        nc = len(fc)
        if nc == 0:
            continue
        trend.append({
            "key": c["key"], "mes": c["mes"], "anio": c["anio"],
            "label_corto": f"{c['mes']:02d}/{str(c['anio'])[2:]}",
            "n_ordenes": nc,
            "ns_empresa_pct": round(fc["empresa_a_tiempo"].mean() * 100, 1),
            "ns_courier_pct": round(fc["courier_a_tiempo"].mean() * 100, 1),
            "otif_total_pct": round(fc["otif_total"].mean() * 100, 1),
        })

    # Ranking por courier (dentro del filtro; útil p.ej. al filtrar por canal)
    gc = f.copy()
    gc["CURIER"] = _norm_courier(gc["CURIER"])
    gc = gc[gc["CURIER"] != ""]
    g = gc.groupby("CURIER").agg(
        n_pedidos=("ORDEN", "count"),
        courier_ok=("courier_a_tiempo", "sum"),
        otif_ok=("otif_total", "sum"),
        empresa_ok=("empresa_a_tiempo", "sum"),
    ).reset_index()
    g = g[g["n_pedidos"] >= _COU_MIN_PEDIDOS]
    if not g.empty:
        g["ns_courier_pct"] = (g["courier_ok"] / g["n_pedidos"] * 100).round(1)
        g["otif_total_pct"] = (g["otif_ok"] / g["n_pedidos"] * 100).round(1)
        g["ns_empresa_pct"] = (g["empresa_ok"] / g["n_pedidos"] * 100).round(1)
        g["pct_volumen"] = (g["n_pedidos"] / g["n_pedidos"].sum() * 100).round(1)
        g = g.sort_values("n_pedidos", ascending=False)
        por_courier = g[["CURIER", "n_pedidos", "pct_volumen", "ns_courier_pct",
                         "otif_total_pct", "ns_empresa_pct"]].to_dict("records")
    else:
        por_courier = []

    # Ranking YTD por canal/cliente (dentro del filtro; útil al filtrar por
    # courier para ver su desempeño multicanal)
    gk = f.copy()
    gk["CANAL"] = gk["CLIENTE"].astype(str).str.strip().str.upper()
    gk = gk[gk["CANAL"] != ""]
    gk = gk[gk["CANAL"] != "NAN"]
    gk2 = gk.groupby("CANAL").agg(
        n_pedidos=("ORDEN", "count"),
        courier_ok=("courier_a_tiempo", "sum"),
        otif_ok=("otif_total", "sum"),
        empresa_ok=("empresa_a_tiempo", "sum"),
    ).reset_index()
    gk2 = gk2[gk2["n_pedidos"] >= _COU_MIN_PEDIDOS]
    if not gk2.empty:
        gk2["ns_courier_pct"] = (gk2["courier_ok"] / gk2["n_pedidos"] * 100).round(1)
        gk2["otif_total_pct"] = (gk2["otif_ok"] / gk2["n_pedidos"] * 100).round(1)
        gk2["ns_empresa_pct"] = (gk2["empresa_ok"] / gk2["n_pedidos"] * 100).round(1)
        gk2["pct_volumen"] = (gk2["n_pedidos"] / gk2["n_pedidos"].sum() * 100).round(1)
        gk2 = gk2.sort_values("n_pedidos", ascending=False)
        por_canal = gk2[["CANAL", "n_pedidos", "pct_volumen", "ns_empresa_pct",
                         "ns_courier_pct", "otif_total_pct"]].to_dict("records")
    else:
        por_canal = []

    return {
        "anio": anio,
        "cortes": [c["key"] for c in cortes],
        "ventana": {"desde": d0.strftime("%Y-%m-%d"), "hasta": d1.strftime("%Y-%m-%d")},
        "n_ordenes": n,
        "n_empresa_ok": n_emp, "n_courier_ok": n_cou, "n_otif_ok": n_tot,
        "ns_empresa_pct": round(n_emp / n * 100, 1) if n else None,
        "ns_courier_pct": round(n_cou / n * 100, 1) if n else None,
        "otif_total_pct": round(n_tot / n * 100, 1) if n else None,
        "trend": trend,
        "por_courier": por_courier,
        "por_canal": por_canal,
        "opciones": opciones,
        "filtros": {"courier": courier or "Todos", "cliente": cliente or "Todos"},
        "error": None,
    }


def anios_otif_disponibles() -> List[int]:
    """Años con cortes en el Sheet, descendente."""
    return sorted({c["anio"] for c in cortes_otif_disponibles()}, reverse=True)
