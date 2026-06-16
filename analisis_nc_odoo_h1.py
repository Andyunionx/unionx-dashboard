# -*- coding: utf-8 -*-
"""
Cruce de NOTAS DE CRÉDITO en Odoo para validar la hipótesis de devoluciones
de otros períodos (cierre H1 2026).

Para cada NC (account.move, move_type='out_refund', posted) emitida ene–may 2026,
usa `reversed_entry_id` → factura original → su `invoice_date` para determinar de
qué período es la VENTA original. Clasifica: mismo mes / mes previo 2026 / 2025 o
antes / sin vínculo. Así se cierra lo que el parquet dejó como "no trazable".

Salida: data/outputs/NC_Odoo_origen_H1_<stamp>.xlsx + resumen en consola.
"""
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "finanzas-unionx" / "backend"))
load_dotenv(ROOT / ".env")

from app.core.odoo_client import OdooClient   # noqa: E402
from app.config import Config                 # noqa: E402

OUTDIR = ROOT / "data" / "outputs"
PERIODO_INI = "2026-01-01"
PERIODO_FIN = "2026-05-31"
MES_NOM = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _id_de(val):
    """Many2one viene como [id, 'name'] o False."""
    if isinstance(val, (list, tuple)) and val:
        return val[0]
    return None


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
    print(f"Conectando a Odoo {Config.ODOO_URL} ({Config.ODOO_DB}) como {Config.ODOO_USER}…")
    odoo.authenticate()

    # 1) NC del período
    dom = [
        ("move_type", "=", "out_refund"),
        ("state", "=", "posted"),
        ("invoice_date", ">=", PERIODO_INI),
        ("invoice_date", "<=", PERIODO_FIN),
    ]
    flds = ["id", "name", "invoice_date", "amount_total", "amount_untaxed",
            "reversed_entry_id", "partner_id", "invoice_origin", "ref"]
    print("Descargando NC (out_refund, posted)…")
    ncs = odoo.search_read_paginated("account.move", dom, flds, page_size=400)
    print(f"  NC encontradas: {len(ncs)}")
    if not ncs:
        print("Sin NC en el período.")
        return

    # 2) Facturas originales referenciadas
    orig_ids = sorted({_id_de(n.get("reversed_entry_id")) for n in ncs} - {None})
    print(f"  Facturas originales referenciadas: {len(orig_ids)}")
    orig_fecha = {}
    if orig_ids:
        origs = odoo.execute_in_batches("account.move", orig_ids,
                                        ["id", "invoice_date", "date", "name"], batch_size=200)
        for o in origs:
            f = o.get("invoice_date") or o.get("date")
            if f:
                orig_fecha[o["id"]] = str(f)[:10]

    # 3) Clasificar cada NC por período de la venta original
    def periodo(fecha):  # 'YYYY-MM-DD' -> (anio, mes)
        return int(fecha[:4]), int(fecha[5:7])

    filas = []
    for n in ncs:
        nc_a, nc_m = periodo(str(n["invoice_date"])[:10])
        oid = _id_de(n.get("reversed_entry_id"))
        of = orig_fecha.get(oid) if oid else None
        if not of:
            origen = "Sin vínculo a factura original"
            o_a = o_m = None
        else:
            o_a, o_m = periodo(of)
            if o_a < 2026:
                origen = "Venta de 2025 o antes"
            elif (o_a, o_m) == (nc_a, nc_m):
                origen = "Venta del mismo mes"
            elif o_a == 2026 and o_m < nc_m:
                origen = "Venta de mes anterior (2026)"
            else:
                origen = "Otro período"
        filas.append({
            "NC": n.get("name"), "Mes NC": nc_m, "Fecha NC": str(n["invoice_date"])[:10],
            "Fecha venta original": of or "", "Origen": origen,
            "Neto": float(n.get("amount_untaxed") or 0),
            "Total": float(n.get("amount_total") or 0),
            "Cliente": (n.get("partner_id") or ["", ""])[1] if n.get("partner_id") else "",
        })
    df = pd.DataFrame(filas)

    # 4) Resúmenes
    por_origen = df.groupby("Origen", as_index=False).agg(
        NC=("NC", "count"), Neto=("Neto", "sum"), Total=("Total", "sum"))
    por_origen = por_origen.sort_values("Neto", ascending=False)
    por_mes_origen = df.groupby(["Mes NC", "Origen"], as_index=False).agg(
        NC=("NC", "count"), Neto=("Neto", "sum"))
    por_mes_origen["Mes NC"] = por_mes_origen["Mes NC"].map(lambda m: MES_NOM[int(m)])

    M = lambda v: f"${v/1e6:,.1f}M"
    tot_neto = df["Neto"].sum()
    print("\n=== NC H1 (ene–may 2026) por período de la venta original ===")
    print(f"  NC totales: {len(df)}  |  Neto total: {M(tot_neto)}")
    for _, r in por_origen.iterrows():
        pct = r["Neto"] / tot_neto * 100 if tot_neto else 0
        print(f"   - {r['Origen']:32s} {int(r['NC']):>5} NC   {M(r['Neto']):>10}  ({pct:4.1f}%)")
    otros = por_origen[por_origen["Origen"].isin(
        ["Venta de 2025 o antes", "Venta de mes anterior (2026)", "Otro período"])]["Neto"].sum()
    print(f"\n  >>> Devoluciones de OTRO PERÍODO (confirmado Odoo): {M(otros)} "
          f"({otros/tot_neto*100:.1f}% del neto de NC)")

    # 5) Snapshot parquet para que la vista del dashboard lo lea SIN llamar a Odoo
    snap_dir = ROOT / "data" / "contabilidad"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = df[["Mes NC", "Origen", "Neto", "Total"]].copy()
    snap_agg = snap.groupby(["Mes NC", "Origen"], as_index=False).agg(
        Neto=("Neto", "sum"), Total=("Total", "sum"), NC=("Origen", "size"))
    snap_path = snap_dir / "nc_origen_h1.parquet"
    snap_agg.to_parquet(snap_path, index=False)
    print(f"✓ Snapshot vista: {snap_path.relative_to(ROOT)}")
    # Detalle por NC (para pegar canal vía parquet en el análisis por canal)
    df[["NC", "Mes NC", "Fecha NC", "Fecha venta original", "Origen", "Neto", "Total"]].to_parquet(
        snap_dir / "nc_detalle_h1.parquet", index=False)
    print(f"✓ Detalle NC: data/contabilidad/nc_detalle_h1.parquet")

    # 6) Excel
    xlsx = OUTDIR / f"NC_Odoo_origen_H1_{stamp}.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        por_origen.to_excel(xw, sheet_name="Resumen_por_origen", index=False)
        por_mes_origen.to_excel(xw, sheet_name="Por_mes_y_origen", index=False)
        df.sort_values(["Mes NC", "Origen"]).to_excel(xw, sheet_name="Detalle_NC", index=False)
    print(f"\n✓ Excel: {xlsx.name}")
    return xlsx


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
