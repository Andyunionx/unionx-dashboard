"""
Parser del libro de compras del SII (Excel descargado del portal sii.cl).
Normaliza al esquema canónico: rut, razon_social, tipo_doc, folio, fecha,
monto_neto, iva, monto_total, glosa, archivo.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional
import pandas as pd

SII_TIPO_DOC = {
    30: "Factura", 33: "Factura Electronica", 34: "Factura Exenta Electronica",
    46: "Factura de Compra Electronica", 52: "Guia de Despacho Electronica",
    56: "Nota de Debito Electronica", 61: "Nota de Credito Electronica",
    110: "Factura de Exportacion Electronica", 111: "Nota de Debito de Exportacion",
    112: "Nota de Credito de Exportacion", 914: "Declaracion de Ingreso (Importacion)",
}


@dataclass
class CompraSII:
    rut: str
    razon_social: str
    tipo_doc: int
    tipo_doc_nombre: str
    folio: str
    fecha: Optional[date]
    monto_neto: float
    iva: float
    monto_total: float
    glosa: str = ""
    archivo: str = ""

    @property
    def match_key(self) -> str:
        return f"{self.rut}|{self.tipo_doc}|{self.folio}"

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.fecha:
            d["fecha"] = self.fecha.isoformat()
        return d


def normalizar_rut(rut) -> str:
    if rut is None:
        return ""
    s = str(rut).replace(".", "").replace(" ", "").upper().strip()
    if not s or s in ("NAN", "NONE"):
        return ""
    s = s.replace("-", "")
    if len(s) < 2:
        return ""
    return f"{s[:-1]}-{s[-1]}"


def _to_float(v) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(" ", "")
    if not s or s.upper() in ("NAN", "NONE", "-"):
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _to_date(v) -> Optional[date]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s or s.upper() in ("NAN", "NONE", "-"):
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_int(v) -> int:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return 0


def _detectar_columnas(df: pd.DataFrame) -> dict[str, str]:
    mapping = {}
    for col in df.columns:
        c = re.sub(r"\s+", " ", str(col).strip().upper())
        if "RUT" in c and "PROV" in c:
            mapping["rut"] = col
        elif c in ("RUT", "RUT EMISOR", "RUT PROVEEDOR"):
            mapping["rut"] = col
        elif ("RAZON" in c or "RAZÓN" in c) and "rut" in mapping:
            mapping["razon_social"] = col
        elif "RAZON SOCIAL" in c or "RAZÓN SOCIAL" in c:
            mapping["razon_social"] = col
        elif c in ("PROVEEDOR", "EMISOR"):
            mapping.setdefault("razon_social", col)
        elif "TIPO DOC" in c or c == "TIPO" or "TIPO DTE" in c:
            mapping["tipo_doc"] = col
        elif "FOLIO" in c or c in ("NRO", "NUMERO"):
            mapping.setdefault("folio", col)
        elif "FECHA DOC" in c or c in ("FECHA EMISION", "FECHA EMISIÓN"):
            mapping["fecha"] = col
        elif c == "FECHA":
            mapping.setdefault("fecha", col)
        elif "MONTO TOTAL" in c or c == "TOTAL":
            mapping["monto_total"] = col
        elif "MONTO NETO" in c or c == "NETO":
            mapping["monto_neto"] = col
        elif "IVA" in c or "I.V.A" in c:
            mapping.setdefault("iva", col)
        elif "GLOSA" in c or "DESCRIPCION" in c or "DESCRIPCIÓN" in c:
            mapping.setdefault("glosa", col)
    return mapping


def _leer_excel_robusto(archivo: Path) -> Optional[pd.DataFrame]:
    try:
        return pd.read_excel(archivo)
    except Exception:
        pass
    try:
        return pd.read_excel(archivo, engine="openpyxl")
    except Exception:
        return None


def parse_libro_sii(archivo: Path | str) -> list[CompraSII]:
    archivo = Path(archivo)
    df = _leer_excel_robusto(archivo)
    if df is None or df.empty:
        return []
    cols = _detectar_columnas(df)
    if "rut" not in cols:
        for skip in (1, 2, 3, 4, 5):
            try:
                df_alt = pd.read_excel(archivo, skiprows=skip)
                cols_alt = _detectar_columnas(df_alt)
                if "rut" in cols_alt:
                    df = df_alt; cols = cols_alt; break
            except Exception:
                continue
        if "rut" not in cols:
            return []

    out: list[CompraSII] = []
    for _, row in df.iterrows():
        rut = normalizar_rut(row.get(cols["rut"]))
        if not rut:
            continue
        tipo_doc = _to_int(row.get(cols.get("tipo_doc", ""), 33))
        out.append(CompraSII(
            rut=rut,
            razon_social=str(row.get(cols.get("razon_social", ""), "")).strip(),
            tipo_doc=tipo_doc,
            tipo_doc_nombre=SII_TIPO_DOC.get(tipo_doc, f"Tipo {tipo_doc}"),
            folio=str(_to_int(row.get(cols.get("folio", ""), 0))),
            fecha=_to_date(row.get(cols.get("fecha", ""), None)),
            monto_neto=_to_float(row.get(cols.get("monto_neto", ""), 0)),
            iva=_to_float(row.get(cols.get("iva", ""), 0)),
            monto_total=_to_float(row.get(cols.get("monto_total", ""), 0)),
            glosa=str(row.get(cols.get("glosa", ""), "") or "").strip(),
            archivo=archivo.name,
        ))
    return out


def cargar_directorio(carpeta: Path | str) -> list[CompraSII]:
    carpeta = Path(carpeta)
    todas: dict[str, CompraSII] = {}
    for archivo in sorted(carpeta.glob("*.xlsx")):
        if archivo.name.startswith("~"):
            continue
        try:
            for c in parse_libro_sii(archivo):
                todas[c.match_key] = c
        except Exception as e:
            print(f"  ! Error parseando {archivo.name}: {e}")
    return list(todas.values())
