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


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_otif_drive() -> pd.DataFrame:
    """Carga el Sheet OTIF y devuelve DataFrame normalizado.

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
        # En Streamlit Cloud: leer desde st.secrets["gcp_service_account"]
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
        ws = sh.worksheet(WORKSHEET_NAME)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[ops_otif_drive] Error leyendo Sheet: {e}")
        return pd.DataFrame()

    if not rows or len(rows) < 2:
        return pd.DataFrame()

    headers = [h.strip() for h in rows[0]]
    df = pd.DataFrame(rows[1:], columns=headers)

    # Limpiar columnas vacías y filas vacías
    df.columns = [c if c else f"col_{i}" for i, c in enumerate(df.columns)]
    df = df.dropna(subset=["FECHA"], how="all")
    df = df[df["FECHA"].astype(str).str.strip() != ""]

    # Normalizar fechas (puede venir 26/01/2026 o 26-01-2026)
    df["FECHA"] = pd.to_datetime(
        df["FECHA"].astype(str).str.replace("-", "/"),
        format="%d/%m/%Y", errors="coerce"
    )
    df = df.dropna(subset=["FECHA"])
    df["MES"] = df["FECHA"].dt.to_period("M").astype(str)

    # Normalizar estados
    df["Estado Empresa"] = df["Estado Empresa"].astype(str).str.strip()
    df["CUMPLIMIENTO COURIER"] = df["CUMPLIMIENTO COURIER"].astype(str).str.strip()
    df["empresa_a_tiempo"] = df["Estado Empresa"].str.lower().eq("a tiempo")
    df["courier_a_tiempo"] = df["CUMPLIMIENTO COURIER"].str.lower().eq("a tiempo")
    df["otif_total"] = df["empresa_a_tiempo"] & df["courier_a_tiempo"]

    # Días
    for col in ["D�AS EMPRESA", "DÍAS EMPRESA", "DIAS EMPRESA"]:
        if col in df.columns:
            df["dias_empresa"] = pd.to_numeric(df[col], errors="coerce")
            break
    for col in ["D�AS", "DÍAS", "DIAS"]:
        if col in df.columns:
            df["dias_courier"] = pd.to_numeric(df[col], errors="coerce")
            break

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
