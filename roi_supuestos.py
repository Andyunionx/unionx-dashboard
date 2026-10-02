"""
Panel de supuestos del ROI por producto en Drive (Google Sheet "Supuestos ROI", carpeta "ROI UnionX").

El bot lo lee en cada corrida y pisa los valores por defecto de roi_producto.py; así lo que se edite no se
pierde al regenerar el Excel (Andrés 1-oct-2026). Columna "Valor" editable; el resto es informativo.

Uso:
  python roi_supuestos.py --crear    crea el panel (si no existe) con los valores actuales del código
  python roi_supuestos.py            muestra lo que se leería del panel
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent
CARPETA_ROI = "1S05wnO8UFkKptPed4P5wZ0VuGYUIIRr0"     # Drive "ROI UnionX"
NOMBRE_PANEL = "Supuestos ROI"
ALCANCES = ["Todas las ventas", "Digital + UnionX B2B"]


def definiciones(rp) -> list[tuple]:
    """(clave, descripción, valor por defecto, formato, opciones|None, nota). Las claves con '.' van a un dict."""
    return [
        ("ALCANCE", "Alcance de unidades y venta", rp.ALCANCE, "texto", ALCANCES,
         "Todas las ventas = digital + todo el B2B (Paris tienda, Vinoteca, concesionarios…). "
         "Digital + UnionX B2B = la venta recurrente del plan 2027"),
        ("ESCENARIO_DEF", "Escenario de canal de la vista principal", rp.ESCENARIO_DEF, "texto", rp.ESCENARIOS, ""),
        ("MIX_DEFAULT.MKP", "Mix personalizado: % marketplace", rp.MIX_DEFAULT["MKP"], "pct", None, "solo para 'Mix personalizado'"),
        ("MIX_DEFAULT.WEB", "Mix personalizado: % páginas web", rp.MIX_DEFAULT["WEB"], "pct", None, ""),
        ("MIX_DEFAULT.FID", "Mix personalizado: % fidelización", rp.MIX_DEFAULT["FID"], "pct", None, ""),
        ("FACTOR_PRECIO.MKP", "Precio marketplace: factor sobre PVP de la Pricing", rp.FACTOR_PRECIO["MKP"], "num", None, "definición comercial"),
        ("FACTOR_PRECIO.WEB", "Precio páginas web: factor sobre PVP web", rp.FACTOR_PRECIO["WEB"], "num", None, ""),
        ("FACTOR_PRECIO.FID", "Precio fidelización: factor sobre PVP marketplace", rp.FACTOR_PRECIO["FID"], "num", None, ""),
        ("FID_PROG_DEF", "Programa de fidelización del escenario", rp.FID_PROG_DEF, "texto", None, "nombre del programa o 'Todos (promedio ponderado)'"),
        ("MKT_WEB", "Marketing páginas web (% venta)", rp.MKT_WEB, "pct", None, "regla Andrés"),
        ("MKT_FID", "Marketing fidelización (% venta)", rp.MKT_FID, "pct", None, ""),
        ("MKT_B2B", "Marketing B2B (% venta)", rp.MKT_B2B, "pct", None, ""),
        ("TASA_CAPITAL", "Costo de capital anual", rp.TASA_CAPITAL, "pct", None, "Andrés 25-sep: 9%"),
        ("TC_USD", "Tipo de cambio (CLP/USD)", rp.TC_USD, "num", None, ""),
        ("ADUANA_DIAS", "Días de aduana e ingreso a bodega", rp.ADUANA_DIAS, "num", None, ""),
        ("CREDITO_FLETE_INTERNACION_DIAS", "Días de pago de flete e internación", rp.CREDITO_FLETE_INTERNACION_DIAS, "num", None, ""),
        ("CREDITO_NACIONAL_DIAS", "Días de crédito proveedor nacional", rp.CREDITO_NACIONAL_DIAS, "num", None, ""),
        ("FOB_SHARE_DEFAULT", "FOB / landed si el importado no tiene costo USD", rp.FOB_SHARE_DEFAULT, "pct", None, ""),
        ("LT_PRODUCCION_DEFAULT", "Días de producción si la maestra no trae lead time", rp.LT_PRODUCCION_DEFAULT, "num", None, ""),
        ("TRANSITO_DEFAULT", "Días de tránsito si no hay puerto", rp.TRANSITO_DEFAULT, "num", None, ""),
        *[(f"TRANSITO_DIAS.{p}", f"Días de tránsito desde {p}", d, "num", None, "") for p, d in rp.TRANSITO_DIAS.items()],
        ("PESO_B2B", "Manipulación: unidad B2B / fulfillment vs B2C", rp.PESO_B2B, "num", None, "ABC: 0,53"),
        ("ELASTICIDAD", "Elasticidad precio (sensibilidad estándar)", rp.ELASTICIDAD, "num", None, "0 = el precio no mueve unidades"),
        ("INV_ACOMP", "% del inventario que acompaña a la venta", rp.INV_ACOMP, "pct", None, "Andrés 1-oct: 75%"),
        *[(f"SHOCK.{k}", f"Sensibilidad estándar: {k}", v, "num", None, "") for k, v in rp.SHOCK.items()],
        ("UMBRAL_ROTACION", "Rotación mínima para 'alta rotación' (veces/año)", rp.UMBRAL_ROTACION, "num", None, ""),
        ("UMBRAL_CONTRIB", "Contribución mínima para 'margen alto'", rp.UMBRAL_CONTRIB, "pct", None, ""),
    ]


def _gc():
    sys.path.insert(0, str(ROOT))
    import gspread
    from drive_user_helpers import _credentials
    return gspread.authorize(_credentials())


def _buscar_panel():
    sys.path.insert(0, str(ROOT))
    from drive_user_helpers import _service
    q = (f"name='{NOMBRE_PANEL}' and '{CARPETA_ROI}' in parents and trashed=false and "
         "mimeType='application/vnd.google-apps.spreadsheet'")
    fs = _service().files().list(q=q, fields="files(id,modifiedTime)", supportsAllDrives=True,
                                 includeItemsFromAllDrives=True).execute()["files"]
    return fs[0] if fs else None


def crear_panel(rp) -> str:
    """Crea el panel con los valores actuales del código (no lo pisa si ya existe)."""
    f = _buscar_panel()
    if f:
        print("El panel ya existe:", f["id"])
        return f["id"]
    sys.path.insert(0, str(ROOT))
    from drive_user_helpers import _service
    meta = _service().files().create(body={"name": NOMBRE_PANEL, "parents": [CARPETA_ROI],
                                           "mimeType": "application/vnd.google-apps.spreadsheet"},
                                     fields="id", supportsAllDrives=True).execute()
    sh = _gc().open_by_key(meta["id"])
    ws = sh.sheet1
    ws.update_title("Supuestos")
    filas = [["Clave (no editar)", "Parámetro", "Valor", "Nota"]]
    filas += [[k, d, v, n] for k, d, v, _f, _o, n in definiciones(rp)]
    ws.update(values=filas, range_name="A1")
    req = [{"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1},
                           "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                                                          "backgroundColor": {"red": .12, "green": .22, "blue": .39}}},
                           "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
           {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": len(filas), "startColumnIndex": 2,
                                     "endColumnIndex": 3},
                           "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": .95, "blue": .8}}},
                           "fields": "userEnteredFormat.backgroundColor"}},
           {"updateSheetProperties": {"properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
                                      "fields": "gridProperties.frozenRowCount"}}]
    for i, (k, d, v, fmt, opc, n) in enumerate(definiciones(rp), 1):
        if opc:
            req.append({"setDataValidation": {
                "range": {"sheetId": ws.id, "startRowIndex": i, "endRowIndex": i + 1, "startColumnIndex": 2, "endColumnIndex": 3},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": o} for o in opc]},
                         "strict": True, "showCustomUi": True}}})
        if fmt == "pct":
            req.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": i, "endRowIndex": i + 1,
                                                 "startColumnIndex": 2, "endColumnIndex": 3},
                                       "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}},
                                       "fields": "userEnteredFormat.numberFormat"}})
    for col, px in [(0, 230), (1, 380), (2, 170), (3, 520)]:
        req.append({"updateDimensionProperties": {"range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": col,
                                                            "endIndex": col + 1},
                                                  "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    sh.batch_update({"requests": req})
    print("Panel creado:", meta["id"])
    return meta["id"]


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("%", "").replace(" ", "")
    pct = str(v).strip().endswith("%")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    x = float(s)
    return x / 100 if pct else x


def aplicar_panel(rp) -> dict:
    """Lee el panel y pisa los supuestos del módulo roi_producto. Devuelve {clave: valor} aplicados.
    Sin acceso al panel: se quedan los valores por defecto del código (se informa)."""
    try:
        f = _buscar_panel()
        if not f:
            print("[supuestos] sin panel en Drive: valores por defecto del código")
            return {}
        filas = _gc().open_by_key(f["id"]).sheet1.get_all_values(value_render_option="UNFORMATTED_VALUE")
    except Exception as e:  # noqa: BLE001
        print(f"[supuestos] no se pudo leer el panel ({e}): valores por defecto del código")
        return {}
    tipos = {k: (fmt, opc) for k, _d, _v, fmt, opc, _n in definiciones(rp)}
    aplicados = {}
    for fila in filas[1:]:
        if len(fila) < 3 or fila[0] not in tipos or str(fila[2]).strip() == "":
            continue
        k, v = fila[0], fila[2]
        fmt, opc = tipos[k]
        try:
            val = str(v).strip() if fmt == "texto" else _num(v)
        except ValueError:
            print(f"[supuestos] valor inválido en {k}: {v!r} → se mantiene el del código")
            continue
        if opc and val not in opc:
            print(f"[supuestos] {k}={val!r} no está en la lista → se mantiene el del código")
            continue
        if "." in k:
            dic, sub = k.split(".", 1)
            getattr(rp, dic)[sub] = val
        else:
            setattr(rp, k, val)
        aplicados[k] = val
    print(f"[supuestos] {len(aplicados)} supuestos leídos del panel '{NOMBRE_PANEL}'")
    return aplicados


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    import roi_producto as rp
    if "--crear" in sys.argv:
        crear_panel(rp)
    print(aplicar_panel(rp))
