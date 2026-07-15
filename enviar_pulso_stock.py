# -*- coding: utf-8 -*-
"""Pulso Stock UnionX — envío diario (Lun-Vie 07:30 CLT, junto al de ventas).

Genera el Excel con TABLA DINÁMICA NATIVA por bodega (sobre plantilla) +
sábana, refrescable al abrir, y lo envía por mail vía Gmail API
(_enviar_via_gmail, mismo mecanismo del pulso de ventas).

Fuente: data/stock/detalle.parquet (refrescado por sync_stock.yml c/3h).
Destinatarios: env EMAIL_TO (default = equipo stock).
"""
import os, sys, io, re, zipfile, datetime
from pathlib import Path
from xml.sax.saxutils import escape as _xesc
import pandas as pd
import openpyxl

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
from enviar_pulso_cyber import _enviar_via_gmail  # sender Gmail API (token CI o local)

TEMPLATE = PROJECT_ROOT / "data/templates/pulso_stock_template.xlsx"
DETALLE = PROJECT_ROOT / "data/stock/detalle.parquet"
SKUS = PROJECT_ROOT / "data/stock/skus.parquet"
COLS = ["Bodega", "Ubicacion", "Tipo", "SKU", "Producto", "Categoria",
        "Marca", "Qty", "Reservada", "Disponible", "Costo Unit", "Valor"]

EMAIL_TO = [e.strip() for e in os.environ.get(
    "EMAIL_TO",
    "nicolas@unionx.cl,nicole@grupoeter.cl,felipe@unionx.cl,sguzman@grupoeter.cl,"
    "martin@grupoeter.cl,gerardo@unionx.cl,facturacion@unionx.cl,trinidad@unionx.cl,"
    "ignacia@unionx.cl,claudia@unionx.cl,gabriela@grupoeter.cl,maximiliano@unionx.cl"
).split(",") if e.strip()]

AZ = "#1E3A5F"; GR = "#EBF0F8"
# Gated: si FULFILLMENT_LIVE=1, el fulfillment del pulso viene del LIVE de Martín
# (directo de cada marketplace, no Odoo); Walmart se mantiene desde Odoo. Mientras
# el feed de Martín siga en PRUEBA queda apagado (ver fulfillment_live.py).
FULFILLMENT_LIVE = os.environ.get("FULFILLMENT_LIVE", "0") == "1"
def clp(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,}".format(int(n)).replace(",", ".")


def _cargar_detalle() -> pd.DataFrame:
    """Sábana del pulso. Con FULFILLMENT_LIVE=1 reemplaza el fulfillment de Odoo
    por el live de Martín (fulfillment_live.aplicar_live)."""
    det = pd.read_parquet(DETALLE)[COLS].copy()
    if FULFILLMENT_LIVE:
        try:
            from fulfillment_live import aplicar_live
            det = aplicar_live(det)[COLS].copy()
            print("[pulso] fulfillment LIVE de Martín aplicado (Walmart desde Odoo)", flush=True)
        except Exception as e:
            print(f"[pulso][WARN] fulfillment live no aplicado, se usa Odoo: {type(e).__name__}: {e}", flush=True)
    return det


# --- Rebuild del pivotCache para que el pivot muestre la data FRESCA sin depender
# del refresh (Gmail preview / móvil / solo-lectura mostraban el cache viejo de la
# plantilla → números equivocados). Se regeneran sharedItems + records + los <items>
# del pivotTable, consistentes entre sí. Campos = COLS en ese orden.
_SHARED_IDX = [0, 2, 3, 4, 5, 6]   # Bodega, Tipo, SKU, Producto, Categoria, Marca
_INLINE_IDX = [1]                  # Ubicacion (inline <s>)
_INT_IDX = [7, 8, 9]               # Qty, Reservada, Disponible
def _xa(v):  # valor seguro para atributo XML
    return _xesc(str(v), {'"': "&quot;"})
def _sval(v):
    s = "" if v is None else str(v)
    return "" if s.strip().lower() in ("nan", "none", "nat") else s
def _fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _rebuild_pivot_cache(det, cachedef, records_xml, pivottable):
    """Regenera cacheDefinition (sharedItems) + records + items del pivotTable
    a partir de `det` (mismas columnas COLS, mismo orden que la hoja)."""
    det = det[COLS].reset_index(drop=True)
    shared_vals, shared_pos = {}, {}
    for i in _SHARED_IDX:
        uniq = list(dict.fromkeys(det[COLS[i]].map(_sval).tolist()))
        shared_vals[i] = uniq
        shared_pos[i] = {v: k for k, v in enumerate(uniq)}
    # records
    recs = []
    for row in det.itertuples(index=False):
        cells = []
        for i in range(len(COLS)):
            v = row[i]
            if i in _SHARED_IDX:
                cells.append('<x v="%d"/>' % shared_pos[i][_sval(v)])
            elif i in _INLINE_IDX:
                cells.append('<s v="%s"/>' % _xa(_sval(v)))
            elif i in _INT_IDX:
                cells.append('<n v="%d"/>' % int(round(_fnum(v))))
            else:
                cells.append('<n v="%r"/>' % _fnum(v))
        recs.append("<r>" + "".join(cells) + "</r>")
    new_rec = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
               '<pivotCacheRecords xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
               'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
               'count="%d">' % len(recs) + "".join(recs) + "</pivotCacheRecords>")
    # cacheDefinition sharedItems
    SI_RE = r'<sharedItems\b(?:[^>]*?/>|[^>]*?>.*?</sharedItems>)'
    cf = list(re.finditer(r'<cacheField\b.*?</cacheField>', cachedef, re.S))
    assert len(cf) == len(COLS)
    new_cd = cachedef
    for i in _SHARED_IDX:
        blk = cf[i].group(0)
        si = '<sharedItems count="%d">%s</sharedItems>' % (
            len(shared_vals[i]), "".join('<s v="%s"/>' % _xa(v) for v in shared_vals[i]))
        new_cd = new_cd.replace(blk, re.sub(SI_RE, si, blk, count=1, flags=re.S))
    new_cd = re.sub(r'recordCount="\d+"', 'recordCount="%d"' % len(recs), new_cd)
    # pivotTable <items>
    PF_RE = r'<pivotField\b(?:[^>]*?/>|[^>]*?>.*?</pivotField>)'
    pf = list(re.finditer(PF_RE, pivottable, re.S))
    assert len(pf) == len(COLS)
    new_pt = pivottable
    for i in _SHARED_IDX:
        blk = pf[i].group(0)
        if "<items" in blk:
            k = len(shared_vals[i])
            items = ('<items count="%d">' % (k + 1)
                     + "".join('<item x="%d"/>' % j for j in range(k)) + '<item t="default"/></items>')
            new_pt = new_pt.replace(blk, re.sub(r'<items\b.*?</items>', items, blk, count=1, flags=re.S))
    # bodegas (axisCol) visibles
    new_pt = re.sub(r'<pivotField[^>]*axis="axisCol"[^>]*>.*?</pivotField>',
                    lambda m: m.group(0).replace(' h="1"', ''), new_pt, flags=re.S)
    return new_cd, new_rec, new_pt


def construir_excel() -> bytes:
    """Inyecta la sábana fresca en la plantilla, regenera el pivotCache con esa
    data (para que el pivot NO muestre el cache viejo) y deja refreshOnLoad."""
    det = _cargar_detalle()
    det = det.sort_values(["Bodega", "Valor"], ascending=[True, False]).reset_index(drop=True)

    wb = openpyxl.load_workbook(TEMPLATE)
    ws = wb["Stock por Bodega"]
    ws.delete_rows(1, ws.max_row)
    ws.append(COLS)
    for row in det.itertuples(index=False):
        ws.append(list(row))
    nrows = len(det) + 1
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)

    ref = f"A1:L{nrows}"
    zin = zipfile.ZipFile(buf, "r")
    cd = zin.read("xl/pivotCache/pivotCacheDefinition1.xml").decode("utf-8")
    rec = zin.read("xl/pivotCache/pivotCacheRecords1.xml").decode("utf-8")
    pt = zin.read("xl/pivotTables/pivotTable1.xml").decode("utf-8")
    try:
        cd, rec, pt = _rebuild_pivot_cache(det, cd, rec, pt)
    except Exception as e:
        print(f"[pulso][WARN] rebuild pivotCache falló, se usa refreshOnLoad: {type(e).__name__}: {e}", flush=True)
        pt = re.sub(r'<pivotField[^>]*axis="axisCol"[^>]*>.*?</pivotField>',
                    lambda m: m.group(0).replace(' h="1"', ''), pt, flags=re.S)
    # rango + refreshOnLoad (siempre)
    cd = re.sub(r'(<worksheetSource ref=")[^"]+(")', r"\g<1>" + ref + r"\g<2>", cd)
    if "refreshOnLoad" not in cd.split(">")[0]:
        cd = re.sub(r"(<pivotCacheDefinition )", r'\g<1>refreshOnLoad="1" ', cd, count=1)
    else:
        cd = re.sub(r'refreshOnLoad="[^"]*"', 'refreshOnLoad="1"', cd)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == "xl/pivotCache/pivotCacheDefinition1.xml":
                d = cd.encode("utf-8")
            elif it.filename == "xl/pivotCache/pivotCacheRecords1.xml":
                d = rec.encode("utf-8")
            elif it.filename == "xl/pivotTables/pivotTable1.xml":
                d = pt.encode("utf-8")
            zout.writestr(it, d)
    zin.close()
    return out.getvalue()


def construir_html() -> tuple[str, str]:
    det = _cargar_detalle()
    sku = pd.read_parquet(SKUS).drop_duplicates("SKU")
    tot_val = det["Valor"].sum(); tot_uds = det["Disponible"].sum()
    n_sku = sku["SKU"].nunique()

    # Categorías (sobrias, sin conflación):
    cri = sku[sku["Semaforo"] == "CRITICO"]
    sob = sku[sku["Semaforo"] == "SOBRESTOCK"]
    # "Sin venta 90d" REAL = clasificado sin venta Y efectivamente 0 ventas en 90d
    # (filtra el ruido: SKUs marcados 'sin venta' que sí vendieron).
    sv = sku[(sku["Semaforo"] == "SIN VENTA") & (sku["Vta 90d Qty"].fillna(0) == 0)]

    html = f"""<div style="font-family:Arial,sans-serif;color:#222;max-width:680px;line-height:1.5;">
<h2 style="color:{AZ};margin-bottom:2px;">📦 Pulso Stock Live</h2>
<div style="color:#64748b;font-size:12px;">Foto al {{HOY}}</div>
<div style="font-size:14px;margin:12px 0;"><b>Inventario total:</b> {clp(tot_val)} ·
{miles(tot_uds)} uds · {miles(n_sku)} SKUs</div>

<table style="border-collapse:collapse;font-size:13px;margin:8px 0;">
<tr style="background:{AZ};color:#fff;">
  <th style="padding:6px 12px;text-align:left;">Foco</th>
  <th style="padding:6px 12px;text-align:right;">SKUs</th>
  <th style="padding:6px 12px;text-align:right;">Valor</th>
  <th style="padding:6px 12px;text-align:left;">Lectura</th></tr>
<tr style="background:{GR};">
  <td style="padding:6px 12px;">🔴 Quiebre crítico</td>
  <td style="padding:6px 12px;text-align:right;">{miles(len(cri))}</td>
  <td style="padding:6px 12px;text-align:right;">{clp(cri['Valor'].sum())}</td>
  <td style="padding:6px 12px;">Reponer: alta venta, stock bajo</td></tr>
<tr>
  <td style="padding:6px 12px;">🔵 Sobrestock</td>
  <td style="padding:6px 12px;text-align:right;">{miles(len(sob))}</td>
  <td style="padding:6px 12px;text-align:right;">{clp(sob['Valor'].sum())}</td>
  <td style="padding:6px 12px;">Lento, pero rotó {clp(sob['Vta 90d $'].sum())} en 90d</td></tr>
<tr style="background:{GR};">
  <td style="padding:6px 12px;">⚪ Sin venta 90d</td>
  <td style="padding:6px 12px;text-align:right;">{miles(len(sv))}</td>
  <td style="padding:6px 12px;text-align:right;">{clp(sv['Valor'].sum())}</td>
  <td style="padding:6px 12px;">Capital sin rotación — revisar liquidación</td></tr>
</table>

<div style="font-size:13px;margin:12px 0;">📎 <b>Excel adjunto (Pulso Stock LIVE):</b> hoja <b>Resumen</b> con
<b>tabla dinámica interactiva por bodega</b> (arrastrá Marca/Categoría/SKU/Bodega; se refresca
sola al abrir) + hoja <b>Stock por Bodega</b> con la sábana completa para planificación.</div>
<div style="margin-top:16px;font-size:12px;color:#475569;">
🔗 Dashboard Stock LIVE: <a href="https://unionx-ventas.streamlit.app/stock-live">unionx-ventas.streamlit.app/stock-live</a></div>
</div>"""
    return html, clp(tot_val)


def main():
    hoy = datetime.datetime.now().strftime("%d-%b-%Y")
    xlsx = construir_excel()
    html, monto = construir_html()
    html = html.replace("{HOY}", hoy)
    fname = "Stock live"  # empieza con "Stock" → sin prefijo "Raw Cyber"

    # 2º adjunto: comparativa Odoo vs live (solo cuando el live está activo)
    extra = []
    if FULFILLMENT_LIVE:
        try:
            from fulfillment_live import cruce_bytes, LIVE_PARQUET
            if LIVE_PARQUET.exists():
                extra = [(cruce_bytes(), "Comparación Stock Odoo vs live.xlsx")]
                print("[pulso] adjuntando comparativa Odoo vs live", flush=True)
        except Exception as e:
            print(f"[pulso][WARN] comparativa no adjuntada: {type(e).__name__}: {e}", flush=True)

    asunto = f"📦 Pulso Stock Live · {monto} · {hoy}"
    print(f"Enviando a {len(EMAIL_TO)} destinatarios: {EMAIL_TO}", flush=True)
    msg_id = _enviar_via_gmail(asunto, html, xlsx, fname, EMAIL_TO, extra_attachments=extra)
    print("Enviado. msg_id:", msg_id, flush=True)
    return 0 if msg_id else 1


if __name__ == "__main__":
    sys.exit(main())
