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
    # SKU vacío pero con "[CODE]" en el nombre → recuperar el SKU (dato de origen:
    # detalle.parquet trae algunos productos sin default_code; el código va en el nombre).
    sku = det["SKU"].astype(str).str.strip()
    vacio = sku.str.lower().isin(["", "nan", "none"])
    if vacio.any():
        rescatado = det.loc[vacio, "Producto"].astype(str).str.extract(r"^\s*\[([^\]]+)\]", expand=False)
        det.loc[vacio, "SKU"] = rescatado.fillna("").values
        n = int((rescatado.fillna("") != "").sum())
        print(f"[pulso] SKU recuperado del nombre en {n} filas (de {int(vacio.sum())} sin SKU)", flush=True)
    return det


def construir_excel() -> bytes:
    """Inyecta la sábana fresca en la plantilla y deja el pivot con refreshOnLoad
    (se refresca solo al abrir en Excel) + bodegas visibles."""
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

    # Zip-surgery: garantizar rango + refreshOnLoad + bodegas visibles
    ref = f"A1:L{nrows}"
    zin = zipfile.ZipFile(buf, "r")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == "xl/pivotCache/pivotCacheDefinition1.xml":
                x = d.decode("utf-8")
                x = re.sub(r'(<worksheetSource ref=")[^"]+(")', r"\g<1>" + ref + r"\g<2>", x)
                if "refreshOnLoad" not in x.split(">")[0]:
                    x = re.sub(r"(<pivotCacheDefinition )", r'\g<1>refreshOnLoad="1" ', x, count=1)
                else:
                    x = re.sub(r'refreshOnLoad="[^"]*"', 'refreshOnLoad="1"', x)
                d = x.encode("utf-8")
            elif it.filename == "xl/pivotTables/pivotTable1.xml":
                x = d.decode("utf-8")
                x = re.sub(r'<pivotField[^>]*axis="axisCol"[^>]*>.*?</pivotField>',
                           lambda m: m.group(0).replace(' h="1"', ''), x, flags=re.S)
                d = x.encode("utf-8")
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
