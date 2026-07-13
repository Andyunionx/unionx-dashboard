#!/usr/bin/env python3
"""
Extractor de Volumen de Inventario (Odoo stock.picking + stock.move).

Genera el snapshot HISTÓRICO para la vista "Total Pedidos B2B/B2C" del
tab Resumen de KPIs WMS. Ahorra tener que consultar 12 meses de Odoo en
cada page load (que tarda minutos).

Estrategia híbrida:
  - Este script genera `data/operaciones/volumen_inventario_hist.parquet`
    con TODOS los pickings done hasta hace 7 días.
  - La vista lee este parquet (instantáneo) + consulta Odoo solo los
    últimos 7 días (rápido, pocos registros).

Output:
  - data/operaciones/volumen_inventario_hist.parquet
  - data/operaciones/volumen_inventario_hist_resumen.json

Ejecución:
  python extract_volumen_inventario.py [--meses N]   # default 18 meses

Cron sugerido: diario a las 03:00 Chile (o semanal lunes 03:00).
"""
import argparse
import json
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

OUT_DIR = PROJECT_ROOT / "data" / "operaciones"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PARQUET = OUT_DIR / "volumen_inventario_hist.parquet"
OUT_RESUMEN = OUT_DIR / "volumen_inventario_hist_resumen.json"

# Hasta hace N días de buffer. Bajado de 7→2 (16-jun-2026) para que el Pulso
# KPI semanal tenga la semana anterior fresca. state="done" ya garantiza
# pickings cerrados; 2 días cubre ajustes/devoluciones en vuelo sin perder
# frescura. (Antes 7 días era muy conservador y dejaba el WMS ~1 semana atrás.)
DIAS_BUFFER_VIVO = 2

# Ubicaciones de las bodegas de fulfillment de marketplaces (ML, Falabella,
# Paris, Ripley, Walmart, Entel). Los despachos DESDE estas bodegas los ejecuta
# el marketplace, NO el equipo de bodega. Las reposiciones HACIA ellas sí las
# prepara el equipo.
_BF_LOCS = ("BFML", "BFFa", "BFP", "BFR", "BFW", "BFE")


def _clasificar_wms(ptn, code, lo, ld):
    """Clasifica un picking según el trabajo real del equipo de bodega.

    Devuelve una de las categorías (ver taxonomía acordada 13-jul-2026):
      pick_ca1 / pick_reserva          → numerador de PRODUCTIVIDAD
      entrega_ca1 / reposicion_fulfillment / entrega_reserva → ENTREGAS equipo
      reslotting / recepcion_putaway / interno_ca1_otro       → informativo
      fulfillment_marketplace / otra_bodega                   → EXCLUIR
    """
    ptn = ptn or ""
    lo = lo or ""
    ld = ld or ""
    car = "Carrascal" in ptn
    res = "Reserva Stock" in ptn
    ff = "Fulfillment" in ptn
    dest_bf = any(b in ld for b in _BF_LOCS)
    orig_bf = any(b in lo for b in _BF_LOCS)

    if code == "outgoing":
        if ff or orig_bf:                 # despacho desde bodega marketplace
            return "fulfillment_marketplace"
        if car:
            return "entrega_ca1"
        if res:
            return "entrega_reserva"
        return "otra_bodega"

    if code == "internal":
        if dest_bf:                       # reposición a fulfillment (la prepara el equipo)
            return "reposicion_fulfillment"
        if res:
            return "pick_reserva"
        if car:
            if "Output" in ld:            # pick a zona de salida
                return "pick_ca1"
            if "Input" in lo:             # putaway de recepción
                return "recepcion_putaway"
            if "Stock" in lo and "Stock" in ld:
                return "reslotting"
            return "interno_ca1_otro"
        return "otra_bodega"

    return "otra_bodega"


def _get_odoo():
    """Crea cliente Odoo desde env vars."""
    user = (os.environ.get("OPS_ODOO_USER", "").strip()
            or os.environ.get("ANDRES_ODOO_USER", "").strip()
            or "andres@grupoeter.cl")
    pwd = (os.environ.get("OPS_ODOO_PASSWORD", "").strip()
           or os.environ.get("ANDRES_ODOO_PASSWORD", "").strip())
    if not pwd:
        # Cargar .env si existe
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in ("ANDRES_ODOO_PASSWORD", "OPS_ODOO_PASSWORD") and not pwd:
                    pwd = v
    if not pwd:
        raise RuntimeError(
            "No hay credentials Odoo. Setear OPS_ODOO_PASSWORD o "
            "ANDRES_ODOO_PASSWORD."
        )

    url = os.environ.get("ODOO_URL", "https://unionxb2b.odoo.com")
    db = os.environ.get("ODOO_DB", "bmya-innovatek-sh-prd-6981800")

    from app.core.odoo_client import OdooClient
    client = OdooClient(url, db, user, pwd)
    client.authenticate()
    return client


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meses", type=int, default=12,
                    help="Cuántos meses atrás extraer (default 12)")
    args = ap.parse_args()

    print(f"=== Extract Volumen Inventario - {datetime.now().isoformat()} ===\n",
          flush=True)

    # Rango: desde hace N meses, hasta hace 7 días (buffer vivo)
    hasta_dt = datetime.now() - timedelta(days=DIAS_BUFFER_VIVO)
    desde_dt = (datetime.now().replace(day=1)
                - timedelta(days=args.meses * 31))
    desde = desde_dt.strftime("%Y-%m-%d")
    hasta = hasta_dt.strftime("%Y-%m-%d")
    print(f"[1] Rango: {desde} a {hasta} (ultimos 7 dias quedan para Odoo vivo)",
          flush=True)

    print(f"[2] Conectando Odoo...", flush=True)
    odoo = _get_odoo()
    print(f"    Conectado a Odoo OK", flush=True)

    print(f"[3] Consultando stock.picking (outgoing + internal, state=done)...",
          flush=True)
    pickings = odoo.search_read(
        "stock.picking",
        [("state", "=", "done"),
         ("date_done", ">=", desde),
         ("date_done", "<", hasta),
         ("picking_type_code", "in", ["outgoing", "internal"])],
        ["id", "name", "date_done", "scheduled_date", "picking_type_id", "partner_id",
         "picking_type_code"],
        limit=500000,
    )
    print(f"    {len(pickings):,} pickings", flush=True)
    if not pickings:
        print("[WARN] Sin pickings en el rango", flush=True)
        return 1

    df_p = pd.DataFrame(pickings)
    df_p["picking_id"] = df_p["id"]
    df_p["fecha_done"] = pd.to_datetime(df_p["date_done"], errors="coerce")
    df_p["scheduled_date"] = pd.to_datetime(df_p.get("scheduled_date"), errors="coerce")
    df_p["picking_type_name"] = df_p["picking_type_id"].apply(
        lambda x: x[1] if isinstance(x, list) and len(x) > 1 else "")
    df_p["partner_name"] = df_p["partner_id"].apply(
        lambda x: x[1] if isinstance(x, list) and len(x) > 1 else "")

    print(f"[4] Consultando stock.move agregados por picking + ubicación (read_group)...",
          flush=True)
    pids = df_p["picking_id"].tolist()
    chunk_size = 1000
    moves_rows = []
    for i in range(0, len(pids), chunk_size):
        chunk = pids[i:i + chunk_size]
        print(f"    chunk {i // chunk_size + 1}/{(len(pids) + chunk_size - 1) // chunk_size} "
              f"({len(chunk)} pickings)", flush=True)
        try:
            # Agrupamos por (picking, origen, destino) para poder clasificar el
            # flujo (pick / reposición fulfillment / reslotting / entrega). Un
            # picking normal trae un solo par de ubicaciones → una fila.
            rg = odoo._execute_with_retry(
                "read_group",
                "stock.move",
                [("picking_id", "in", chunk), ("state", "=", "done")],
                {"fields": ["picking_id", "product_uom_qty:sum"],
                 "groupby": ["picking_id", "location_id", "location_dest_id"],
                 "lazy": False},
            )
            for r in rg:
                pid_raw = r.get("picking_id")
                pid_val = pid_raw[0] if isinstance(pid_raw, list) else pid_raw
                lo = r.get("location_id")
                ld = r.get("location_dest_id")
                moves_rows.append({
                    "picking_id": pid_val,
                    "location_orig": lo[1] if isinstance(lo, list) and len(lo) > 1 else "",
                    "location_dest": ld[1] if isinstance(ld, list) and len(ld) > 1 else "",
                    "n_lineas": r.get("__count", 0),
                    "n_unidades": r.get("product_uom_qty", 0) or 0,
                })
        except Exception as e:
            print(f"    [ERR chunk] {type(e).__name__}: {e}", flush=True)
            continue

    cols_m = ["picking_id", "location_orig", "location_dest", "n_lineas", "n_unidades"]
    df_mv = pd.DataFrame(moves_rows) if moves_rows else pd.DataFrame(columns=cols_m)

    # Agregado a nivel picking: total uds/líneas + par de ubicaciones DOMINANTE
    # (el de mayor volumen), que usamos para clasificar el flujo.
    if len(df_mv):
        tot = (df_mv.groupby("picking_id")
               .agg(n_unidades=("n_unidades", "sum"),
                    n_lineas=("n_lineas", "sum")).reset_index())
        idx = df_mv.groupby("picking_id")["n_unidades"].idxmax()
        dom = df_mv.loc[idx, ["picking_id", "location_orig", "location_dest"]]
        df_m = tot.merge(dom, on="picking_id", how="left")
    else:
        df_m = pd.DataFrame(columns=["picking_id", "n_unidades", "n_lineas",
                                     "location_orig", "location_dest"])
    print(f"    {len(df_m):,} pickings con moves agregados", flush=True)

    print(f"\n[5] Merge + clasificar + guardar parquet...", flush=True)
    df = df_p.merge(df_m, on="picking_id", how="left")
    df["n_lineas"] = df["n_lineas"].fillna(0).astype(int)
    df["n_unidades"] = df["n_unidades"].fillna(0)
    df["location_orig"] = df["location_orig"].fillna("")
    df["location_dest"] = df["location_dest"].fillna("")
    df["categoria_wms"] = df.apply(
        lambda r: _clasificar_wms(r["picking_type_name"], r["picking_type_code"],
                                  r["location_orig"], r["location_dest"]), axis=1)

    df_out = df[["picking_id", "name", "fecha_done", "scheduled_date",
                 "picking_type_name", "partner_name", "picking_type_code",
                 "location_orig", "location_dest", "categoria_wms",
                 "n_unidades", "n_lineas"]].copy()
    df_out.to_parquet(OUT_PARQUET, index=False)
    print(f"    {OUT_PARQUET.relative_to(PROJECT_ROOT)} "
          f"({OUT_PARQUET.stat().st_size:,} bytes)", flush=True)

    # Resumen
    resumen = {
        "generado_en": datetime.now().isoformat(),
        "rango_desde": desde,
        "rango_hasta": hasta,
        "buffer_dias_vivo": DIAS_BUFFER_VIVO,
        "n_pickings": len(df_out),
        "fecha_done_min": str(df_out["fecha_done"].min()),
        "fecha_done_max": str(df_out["fecha_done"].max()),
        "n_unidades_total": float(df_out["n_unidades"].sum()),
        "n_lineas_total": int(df_out["n_lineas"].sum()),
        "top_picking_types": df_out["picking_type_name"].value_counts().head(10).to_dict(),
        "uds_por_categoria": df_out.groupby("categoria_wms")["n_unidades"].sum().round(0).to_dict(),
    }
    with open(OUT_RESUMEN, "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=str)
    print(f"    {OUT_RESUMEN.relative_to(PROJECT_ROOT)}", flush=True)

    print(f"\n=== RESUMEN ===")
    print(f"  Pickings: {len(df_out):,}")
    print(f"  Periodo: {desde} a {hasta}")
    print(f"  Unidades: {df_out['n_unidades'].sum():,.0f}")
    print(f"  Lineas: {df_out['n_lineas'].sum():,}")
    print(f"\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
