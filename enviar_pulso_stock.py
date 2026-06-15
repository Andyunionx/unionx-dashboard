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
    "nicolas@unionx.cl,felipe@unionx.cl,andres@unionx.cl,maximiliano@unionx.cl,"
    "facturacion@unionx.cl,nicole@grupoeter.cl,martin@grupoeter.cl,sguzman@grupoeter.cl"
).split(",") if e.strip()]

AZ = "#1E3A5F"; GR = "#EBF0F8"
def clp(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,}".format(int(n)).replace(",", ".")


def construir_excel() -> bytes:
    """Inyecta la sábana fresca en la plantilla y deja el pivot listo
    (rango actualizado, refreshOnLoad, todas las bodegas visibles)."""
    det = pd.read_parquet(DETALLE)[COLS].copy()
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
    det = pd.read_parquet(DETALLE)
    sku = pd.read_parquet(SKUS).drop_duplicates("SKU")
    tot_val = det["Valor"].sum(); tot_uds = det["Disponible"].sum()
    sem = sku["Semaforo"].value_counts().to_dict()
    SEM = {"CRITICO": ("🔴", "críticos"), "BAJO": ("🟡", "bajos"),
           "OPTIMO": ("🟢", "óptimos"), "SOBRESTOCK": ("🔵", "sobrestock"),
           "SIN VENTA": ("⚪", "sin venta 90d")}
    alerta = " · ".join(f'{SEM[k][0]} {sem.get(k,0)} {SEM[k][1]}'
                        for k in ["CRITICO", "BAJO", "SOBRESTOCK", "SIN VENTA"])
    sobre_sv = (sku[sku["Semaforo"].isin(["SOBRESTOCK", "SIN VENTA"])]["Valor"].sum())
    html = f"""<div style="font-family:Arial,sans-serif;color:#222;max-width:680px;line-height:1.5;">
<h2 style="color:{AZ};margin-bottom:2px;">📦 Pulso Stock UnionX</h2>
<div style="color:#64748b;font-size:12px;">Foto al {{HOY}}</div>
<div style="font-size:14px;margin:12px 0;"><b>Inventario:</b> {clp(tot_val)} ·
{miles(tot_uds)} uds · {miles(sku['SKU'].nunique())} SKUs</div>
<div style="font-size:13px;margin:6px 0;">⚠️ <b>Alerta:</b> {alerta}</div>
<div style="background:{GR};border-left:4px solid {AZ};padding:10px 14px;margin:12px 0;font-size:13px;">
<b>{clp(sobre_sv)}</b> ({sobre_sv/tot_val*100:.0f}% del inventario) en sobrestock o sin venta 90d.</div>
<div style="font-size:13px;margin:12px 0;">📎 <b>Excel adjunto:</b> hoja <b>Resumen</b> con
<b>tabla dinámica interactiva por bodega</b> (arrastrá Marca/Categoría/SKU/Bodega; se refresca
sola al abrir) + hoja <b>Stock por Bodega</b> con la sábana completa para planificación.</div>
<div style="margin-top:16px;font-size:12px;color:#475569;">
🔗 Dashboard Stock LIVE: <a href="https://unionx-ventas.streamlit.app/ops_stock_live">unionx-ventas.streamlit.app/ops_stock_live</a></div>
</div>"""
    return html, clp(tot_val)


def main():
    hoy = datetime.datetime.now().strftime("%d-%b-%Y")
    xlsx = construir_excel()
    html, monto = construir_html()
    html = html.replace("{HOY}", hoy)
    fname = f"Pulso_Stock_por_Bodega_{datetime.datetime.now():%Y-%m-%d}.xlsx"
    asunto = f"📦 Pulso Stock UnionX · {monto} · {hoy}"
    print(f"Enviando a {len(EMAIL_TO)} destinatarios: {EMAIL_TO}", flush=True)
    msg_id = _enviar_via_gmail(asunto, html, xlsx, fname, EMAIL_TO)
    print("Enviado. msg_id:", msg_id, flush=True)
    return 0 if msg_id else 1


if __name__ == "__main__":
    sys.exit(main())
