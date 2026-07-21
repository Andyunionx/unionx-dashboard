# -*- coding: utf-8 -*-
"""Backfill del ORIGEN de las NC de junio en el histórico.

Las NC registradas en junio quedaron con fecha_venta = junio (no se linkeó la
venta original) → "Dev otro período 2026" y "Dev 2025" salían $0 al filtrar junio.
Se corrige trazando cada NC a su factura original en Odoo (reversed_entry_id →
invoice_date) y seteando fecha_venta/anio_venta/mes_venta al origen real.

Uso:  python backfill_nc_origen_junio.py           # dry-run
      python backfill_nc_origen_junio.py --apply   # aplica (backup .bak_ncorigen)
"""
import argparse, os
from pathlib import Path
import pandas as pd
import xmlrpc.client

ROOT = Path(__file__).resolve().parent
HIST = ROOT / "data" / "historico" / "ventas_historico.parquet"
DIAS = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}


def _odoo():
    pw = os.environ.get("ANDRES_ODOO_PASSWORD")
    if not pw:
        for envp in [".env", "eerr-finanzas/.env"]:
            p = ROOT / envp
            if p.exists():
                for ln in p.read_text().splitlines():
                    if ln.startswith("ANDRES_ODOO_PASSWORD"):
                        pw = ln.split("=", 1)[1].strip().strip('"').strip("'")
    url = "https://unionxb2b.odoo.com"; db = "bmya-innovatek-sh-prd-6981800"
    uid = xmlrpc.client.ServerProxy(url + "/xmlrpc/2/common").authenticate(db, "andres@grupoeter.cl", pw, {})
    return xmlrpc.client.ServerProxy(url + "/xmlrpc/2/object"), db, uid, pw


def origen_por_nc(docs):
    """docs: set de nombres de NC. Devuelve {nc_name: (anio, mes, fecha_iso)} del origen."""
    M, db, uid, pw = _odoo()
    docs = list(docs)
    ncs = []
    for i in range(0, len(docs), 300):
        ncs += M.execute_kw(db, uid, pw, "account.move", "search_read",
                            [[["name", "in", docs[i:i+300]], ["move_type", "=", "out_refund"]]],
                            {"fields": ["name", "reversed_entry_id", "invoice_date"]})
    orig_ids = list({r["reversed_entry_id"][0] for r in ncs if r.get("reversed_entry_id")})
    orig_date = {}
    for i in range(0, len(orig_ids), 300):
        for r in M.execute_kw(db, uid, pw, "account.move", "read", [orig_ids[i:i+300]], {"fields": ["invoice_date"]}):
            orig_date[r["id"]] = r.get("invoice_date")
    out = {}
    for r in ncs:
        rev = r.get("reversed_entry_id")
        d = orig_date.get(rev[0]) if rev else None
        d = d or r.get("invoice_date")   # sin reversed_entry_id → cae a la fecha de la NC
        if d:
            dt = pd.to_datetime(str(d)[:10], errors="coerce")
            if pd.notna(dt):
                out[r["name"]] = (dt.year, dt.month, dt.strftime("%Y-%m-%d"))
    return out


def main(apply=False):
    h = pd.read_parquet(HIST)
    fd = pd.to_datetime(h["fecha_documento"].astype(str).str[:10], format="%Y-%m-%d", errors="coerce")
    es_nc_jun = (h["tipo_movimiento"].astype(str) == "Devolución") & (fd.dt.year == 2026) & (fd.dt.month == 6)
    docs = set(h.loc[es_nc_jun, "documento"].astype(str).unique())
    print(f"NC registradas en junio: {int(es_nc_jun.sum())} filas / {len(docs)} documentos")

    mp = origen_por_nc(docs)
    print(f"Origen resuelto en Odoo: {len(mp)}/{len(docs)} NC")

    # aplicar: fecha_venta = origen
    fvn = h["fecha_venta"].copy()
    dv = h["documento"].astype(str)
    cambia = es_nc_jun & dv.isin(mp)
    nueva_fecha = dv.map(lambda x: mp[x][2] if x in mp else None)
    h_new = h.copy()
    h_new.loc[cambia, "fecha_venta"] = nueva_fecha[cambia].values
    # recomputar campos de fecha para las filas cambiadas
    fv2 = pd.to_datetime(h_new["fecha_venta"].astype(str).str[:10], format="%Y-%m-%d", errors="coerce")
    h_new.loc[cambia, "anio_venta"] = fv2[cambia].dt.year.astype("int64")
    h_new.loc[cambia, "mes_venta"] = fv2[cambia].dt.month.astype("int64")
    h_new.loc[cambia, "semana_venta"] = fv2[cambia].dt.isocalendar().week.astype("int64")
    h_new.loc[cambia, "dia_semana"] = fv2[cambia].dt.weekday.map(DIAS)

    # reporte: distribución de origen de las NC de junio (después)
    vn = pd.to_numeric(h_new["venta_neta"], errors="coerce").fillna(0)
    sub = h_new[es_nc_jun].copy()
    sy = pd.to_numeric(sub["anio_venta"], errors="coerce"); sm = pd.to_numeric(sub["mes_venta"], errors="coerce")
    svn = pd.to_numeric(sub["venta_neta"], errors="coerce").fillna(0)
    def f(x): return "$" + format(int(round(x)), ",").replace(",", ".")
    print(f"\n[después] NC junio por ORIGEN de la venta:")
    print("   origen jun-2026:", f(svn[(sy == 2026) & (sm == 6)].sum()))
    print("   origen otro mes 2026:", f(svn[(sy == 2026) & (sm != 6)].sum()))
    print("   origen 2025:", f(svn[sy <= 2025].sum()))
    print(f"   filas reclasificadas: {int(cambia.sum())}")

    if not apply:
        print("\n[DRY-RUN] no se escribió nada.")
        return
    import shutil
    shutil.copy2(str(HIST), str(HIST) + ".bak_ncorigen")
    h_new.to_parquet(HIST, index=False, compression="zstd")
    print(f"\n[OK] aplicado. Backup .bak_ncorigen ({len(h_new):,} filas)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    main(**vars(ap.parse_args()))
