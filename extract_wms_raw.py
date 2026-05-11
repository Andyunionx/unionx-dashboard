"""
Extracción RAW de Odoo para KPIs WMS (1 vez al día).

Concepto: en vez de calcular cada KPI por separado consultando Odoo
múltiples veces, extraemos TODA la base de datos relevante en POCAS
queries grandes y guardamos como parquet. Después los cálculos
(Pick Acc, OTIF, Productividad, etc.) se hacen en memoria sobre esos
parquets — instantáneo, sin Odoo en runtime.

Output:
  data/wms_raw/pickings.parquet      — stock.picking (180d)
  data/wms_raw/moves.parquet         — stock.move (180d)
  data/wms_raw/sale_orders.parquet   — sale.order (180d)
  data/wms_raw/scraps.parquet        — stock.scrap (180d)
  data/wms_raw/ajustes_inv.parquet   — stock.move (Inventory adjustment, desde 2026-04)
  data/wms_raw/metadata.json         — info de extracción

Schedule: 1x/día (GH Action sync_wms_raw.yml a las 03:00 UTC = 00:00 Chile)
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "finanzas-unionx" / "backend"))

OUTPUT_DIR = PROJECT_ROOT / "data" / "wms_raw"
VENTANA_DIAS = 180  # Ventana base — cubre todas las queries (7/14/30/60/90/180)


def main():
    print(f"=== Extract WMS Raw — {datetime.now().isoformat()} ===", flush=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import pandas as pd
    from views._ops_odoo_helper import get_ops_odoo_client

    odoo = get_ops_odoo_client()
    if odoo is None:
        print("ERROR: Odoo no disponible (sin credenciales)", flush=True)
        return 1

    desde = (datetime.now() - timedelta(days=VENTANA_DIAS)).strftime("%Y-%m-%d")
    print(f"Ventana: últimos {VENTANA_DIAS} días (desde {desde})", flush=True)

    metadata = {
        "generado_en": datetime.now().isoformat(),
        "ventana_dias": VENTANA_DIAS,
        "desde": desde,
        "tablas": {},
    }

    # ============================================================
    # 1. PICKINGS (stock.picking) - todos los outgoing + incoming en ventana
    # ============================================================
    print("\n[1/5] Extrayendo pickings…", flush=True)
    t0 = time.time()
    try:
        pickings = odoo.search_read(
            "stock.picking",
            [("date_done", ">=", desde),
             ("state", "=", "done")],
            ["id", "name", "scheduled_date", "date_done", "state",
             "partner_id", "picking_type_code", "picking_type_id",
             "origin", "sale_id"],
            limit=100000,
        )
        df = pd.DataFrame(pickings)
        if not df.empty:
            # Aplanar tuplas Many2one (id, name) → 2 columnas
            for col in ["partner_id", "picking_type_id", "sale_id"]:
                if col in df.columns:
                    df[f"{col}_id"] = df[col].apply(lambda x: x[0] if isinstance(x, list) and x else None)
                    df[f"{col}_name"] = df[col].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else None)
                    df = df.drop(columns=[col])
        df.to_parquet(OUTPUT_DIR / "pickings.parquet", index=False)
        metadata["tablas"]["pickings"] = {
            "rows": len(df), "cols": list(df.columns),
            "tiempo_s": round(time.time() - t0, 1),
        }
        print(f"  OK: {len(df):,} pickings en {time.time() - t0:.1f}s", flush=True)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        metadata["tablas"]["pickings"] = {"error": str(e)[:200]}

    # ============================================================
    # 2. MOVES (stock.move) - paginado por chunks
    # ============================================================
    print("\n[2/5] Extrayendo moves…", flush=True)
    t0 = time.time()
    try:
        moves = odoo.search_read_paginated(
            "stock.move",
            [("date", ">=", desde),
             ("state", "=", "done")],
            ["id", "picking_id", "product_id", "product_uom_qty",
             "quantity", "state", "date", "location_id", "location_dest_id",
             "picking_type_id"],
            page_size=2000,
        )
        df = pd.DataFrame(moves)
        if not df.empty:
            for col in ["picking_id", "product_id", "location_id",
                        "location_dest_id", "picking_type_id"]:
                if col in df.columns:
                    df[f"{col}_id"] = df[col].apply(lambda x: x[0] if isinstance(x, list) and x else None)
                    df[f"{col}_name"] = df[col].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else None)
                    df = df.drop(columns=[col])
        df.to_parquet(OUTPUT_DIR / "moves.parquet", index=False)
        metadata["tablas"]["moves"] = {
            "rows": len(df), "cols": list(df.columns),
            "tiempo_s": round(time.time() - t0, 1),
        }
        print(f"  OK: {len(df):,} moves en {time.time() - t0:.1f}s", flush=True)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        metadata["tablas"]["moves"] = {"error": str(e)[:200]}

    # ============================================================
    # 3. SALE ORDERS (para OFR + OCT)
    # ============================================================
    print("\n[3/5] Extrayendo sale.orders…", flush=True)
    t0 = time.time()
    try:
        sos = odoo.search_read(
            "sale.order",
            [("date_order", ">=", desde),
             ("state", "in", ["sale", "done"])],
            ["id", "name", "date_order", "state", "partner_id",
             "amount_total", "picking_ids", "team_id"],
            limit=50000,
        )
        df = pd.DataFrame(sos)
        if not df.empty:
            for col in ["partner_id", "team_id"]:
                if col in df.columns:
                    df[f"{col}_id"] = df[col].apply(lambda x: x[0] if isinstance(x, list) and x else None)
                    df[f"{col}_name"] = df[col].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else None)
                    df = df.drop(columns=[col])
            # picking_ids es list, lo dejamos como string JSON
            if "picking_ids" in df.columns:
                df["picking_ids"] = df["picking_ids"].apply(lambda x: json.dumps(x) if x else "[]")
        df.to_parquet(OUTPUT_DIR / "sale_orders.parquet", index=False)
        metadata["tablas"]["sale_orders"] = {
            "rows": len(df), "cols": list(df.columns),
            "tiempo_s": round(time.time() - t0, 1),
        }
        print(f"  OK: {len(df):,} sale.orders en {time.time() - t0:.1f}s", flush=True)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        metadata["tablas"]["sale_orders"] = {"error": str(e)[:200]}

    # ============================================================
    # 4. SCRAPS (stock.scrap) - merma
    # ============================================================
    print("\n[4/5] Extrayendo scraps…", flush=True)
    t0 = time.time()
    try:
        scraps = odoo.search_read(
            "stock.scrap",
            [("date_done", ">=", desde),
             ("state", "=", "done")],
            ["id", "name", "date_done", "product_id", "scrap_qty",
             "location_id", "scrap_location_id", "move_id", "origin"],
            limit=20000,
        )
        df = pd.DataFrame(scraps)
        if not df.empty:
            for col in ["product_id", "location_id", "scrap_location_id", "move_id"]:
                if col in df.columns:
                    df[f"{col}_id"] = df[col].apply(lambda x: x[0] if isinstance(x, list) and x else None)
                    df[f"{col}_name"] = df[col].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else None)
                    df = df.drop(columns=[col])
        df.to_parquet(OUTPUT_DIR / "scraps.parquet", index=False)
        metadata["tablas"]["scraps"] = {
            "rows": len(df), "cols": list(df.columns),
            "tiempo_s": round(time.time() - t0, 1),
        }
        print(f"  OK: {len(df):,} scraps en {time.time() - t0:.1f}s", flush=True)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        metadata["tablas"]["scraps"] = {"error": str(e)[:200]}

    # ============================================================
    # 5. AJUSTES INVENTARIO (stock.move ubicación Inventory adjustment)
    # ============================================================
    print("\n[5/5] Extrayendo ajustes de inventario…", flush=True)
    t0 = time.time()
    try:
        ajustes = odoo.search_read(
            "stock.move",
            [("date", ">=", "2026-04-01"),
             ("state", "=", "done"),
             "|",
             ("location_id.name", "=", "Inventory adjustment"),
             ("location_dest_id.name", "=", "Inventory adjustment")],
            ["id", "name", "date", "product_id", "product_uom_qty",
             "quantity", "location_id", "location_dest_id", "value"],
            limit=50000,
        )
        df = pd.DataFrame(ajustes)
        if not df.empty:
            for col in ["product_id", "location_id", "location_dest_id"]:
                if col in df.columns:
                    df[f"{col}_id"] = df[col].apply(lambda x: x[0] if isinstance(x, list) and x else None)
                    df[f"{col}_name"] = df[col].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else None)
                    df = df.drop(columns=[col])
        df.to_parquet(OUTPUT_DIR / "ajustes_inv.parquet", index=False)
        metadata["tablas"]["ajustes_inv"] = {
            "rows": len(df), "cols": list(df.columns),
            "tiempo_s": round(time.time() - t0, 1),
        }
        print(f"  OK: {len(df):,} ajustes en {time.time() - t0:.1f}s", flush=True)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        metadata["tablas"]["ajustes_inv"] = {"error": str(e)[:200]}

    # ============================================================
    # METADATA
    # ============================================================
    with open(OUTPUT_DIR / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)

    total_rows = sum(t.get("rows", 0) for t in metadata["tablas"].values())
    print(f"\n=== Extracción completa ===", flush=True)
    print(f"Total filas extraídas: {total_rows:,}", flush=True)
    print(f"Output: {OUTPUT_DIR}", flush=True)

    n_errores = sum(1 for t in metadata["tablas"].values() if "error" in t)
    return 0 if n_errores == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
