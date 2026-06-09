"""
Opcion B — Obtiene DTEs del SII desde el detalle de Descargas Diferidas.

Reutiliza descarga_sii.descargar_detalle_compras() que ya funciona en produccion.
Si el detalle no esta listo, retorna lista vacia (la proxima corrida lo tendra).
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DTERecibido:
    rut_emisor: str
    razon_social: str
    tipo_doc: str
    folio: str
    fecha_emision: str
    monto_neto: float
    monto_iva: float
    monto_total: float
    xml_disponible: bool = False
    xml_bytes: Optional[bytes] = None
    error: Optional[str] = None


@dataclass
class ResultadoRCV:
    periodo: str
    total_sii: int = 0
    ya_en_odoo: int = 0
    importados: int = 0
    errores: list = field(default_factory=list)
    dtes: list = field(default_factory=list)


# Tipos de documento que se importan automaticamente a Odoo
TIPOS_AUTO_IMPORTAR = {"33", "34", "61"}

# Mapeo codigo SII → nombre legible
NOMBRE_TIPO_DOC = {
    "33": "Factura electrónica",
    "34": "Factura no afecta",
    "43": "Liquidación-Factura",
    "56": "Nota de débito",
    "61": "Nota de crédito",
}


def _parsear_excel_detalle(archivo: Path) -> list[dict]:
    """
    Parsea el Excel de Detalle de Compras del SII.

    Columnas esperadas (el SII puede variar el orden):
      RUT Proveedor | Razon Social | Tipo Doc | Folio | Fecha | Monto Neto | IVA | Total
    """
    try:
        import openpyxl
    except ImportError:
        return []

    wb = openpyxl.load_workbook(str(archivo), read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Detectar cabecera — primera fila con texto
    header_idx = 0
    for i, row in enumerate(rows):
        if any(isinstance(c, str) and len(str(c)) > 2 for c in row if c is not None):
            header_idx = i
            break

    headers = [str(c).strip().lower() if c else "" for c in rows[header_idx]]

    def _idx(*names):
        for n in names:
            for i, h in enumerate(headers):
                if n in h:
                    return i
        return None

    i_rut    = _idx("rut prov", "rut emi", "rut")
    i_razon  = _idx("razón", "razon", "nombre")
    i_tipo   = _idx("tipo doc", "codigo doc", "tipo")
    i_folio  = _idx("folio")
    i_fecha  = _idx("fecha doc", "fecha emi", "fecha")
    i_neto   = _idx("monto neto", "neto")
    i_iva    = _idx("iva", "impuesto")
    i_total  = _idx("monto total", "total")

    docs = []
    for row in rows[header_idx + 1:]:
        if not any(row):
            continue
        def val(idx):
            return row[idx] if idx is not None and idx < len(row) else None

        rut = str(val(i_rut) or "").strip()
        if not rut or rut.lower() in ("rut", "none", ""):
            continue

        try:
            neto  = float(str(val(i_neto)  or "0").replace(".", "").replace(",", ".").replace("$", "")) if i_neto  is not None else 0.0
            iva   = float(str(val(i_iva)   or "0").replace(".", "").replace(",", ".").replace("$", "")) if i_iva   is not None else 0.0
            total = float(str(val(i_total) or "0").replace(".", "").replace(",", ".").replace("$", "")) if i_total is not None else 0.0
        except (ValueError, AttributeError):
            neto = iva = total = 0.0

        fecha = val(i_fecha)
        if hasattr(fecha, "strftime"):
            fecha = fecha.strftime("%Y-%m-%d")
        else:
            fecha = str(fecha or "").strip()[:10]

        tipo_raw = str(val(i_tipo) or "").strip()
        # El SII a veces entrega el nombre completo; extraer solo el codigo si es numerico
        tipo = tipo_raw if tipo_raw.isdigit() else ""

        folio = str(val(i_folio) or "").strip().split(".")[0]  # quitar decimales si es float

        docs.append({
            "rut_emisor":   rut.replace(".", "").replace("-", "").upper(),
            "razon_social": str(val(i_razon) or "").strip(),
            "tipo_doc":     tipo,
            "folio":        folio,
            "fecha":        fecha,
            "monto_neto":   neto,
            "monto_iva":    iva,
            "monto_total":  total,
        })

    wb.close()
    return docs


def listar_y_descargar_rcv(year: int, month: int, rut: str, password: str,
                            folios_ya_en_odoo=None, headless: bool = False) -> ResultadoRCV:
    """
    Obtiene DTEs del mes desde el detalle SII.

    Flujo:
      1. Llama a descargar_detalle_compras() — reutiliza el scraper que ya funciona
      2. Si hay Excel descargado, lo parsea fila por fila
      3. Filtra los que ya estan en Odoo (folios_ya_en_odoo)
      4. Retorna solo los nuevos que corresponde importar
    """
    from src.actions.compras.descarga_sii import descargar_detalle_compras

    folios_ya_en_odoo = folios_ya_en_odoo or set()
    resultado = ResultadoRCV(periodo=f"{year:04d}-{month:02d}")

    # Intentar obtener el detalle (puede estar ya en disco de corridas anteriores)
    res_descarga = descargar_detalle_compras(
        year, month,
        rut=rut, password=password,
        headless=headless,
        esperar_generacion_seg=120,
    )

    if res_descarga.get("estado") == "solicitado":
        resultado.errores.append("Detalle SII solicitado — listo en próxima corrida")
        return resultado

    if res_descarga.get("estado") == "error" or not res_descarga.get("archivo"):
        resultado.errores.append(res_descarga.get("error", "Error desconocido al descargar detalle"))
        # Intentar leer archivo existente en disco como fallback
        from src.actions.compras.descarga_sii import DOWNLOADS_DIR
        archivo_disco = DOWNLOADS_DIR / f"detalle_compras_{year:04d}-{month:02d}.xlsx"
        if not archivo_disco.exists():
            return resultado
        archivo = archivo_disco
    else:
        archivo = res_descarga["archivo"]

    filas = _parsear_excel_detalle(Path(archivo))
    resultado.total_sii = len(filas)

    for fila in filas:
        folio = fila.get("folio", "")
        tipo  = fila.get("tipo_doc", "")

        dte = DTERecibido(
            rut_emisor=fila.get("rut_emisor", ""),
            razon_social=fila.get("razon_social", ""),
            tipo_doc=tipo,
            folio=folio,
            fecha_emision=fila.get("fecha", ""),
            monto_neto=fila.get("monto_neto", 0),
            monto_iva=fila.get("monto_iva", 0),
            monto_total=fila.get("monto_total", 0),
        )

        if folio in folios_ya_en_odoo:
            resultado.ya_en_odoo += 1
            continue

        if tipo and tipo not in TIPOS_AUTO_IMPORTAR:
            dte.error = f"Tipo {tipo} ({NOMBRE_TIPO_DOC.get(tipo, '?')}) no auto-importable"
            resultado.dtes.append(dte)
            continue

        # Sin XML (el detalle Excel no incluye el XML DTE individual)
        # importador_odoo.py crea la linea con los datos del Excel
        dte.xml_disponible = False
        resultado.dtes.append(dte)

    return resultado
