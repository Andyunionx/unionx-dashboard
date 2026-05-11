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
