#!/usr/bin/env python3
"""
Sube el parquet de mes_actual a Turso para mantener ambas fuentes
sincronizadas. El parquet incluye inyecciones manuales (Sodimac
manual_externa, Walmart fulfillment, fixes puntuales como FAC 098241,
reclasificaciones Casa Mila→UnionX B2B, etc.) que el extract Odoo
crudo no contiene.

Estrategia: DELETE+INSERT del rango de fechas presente en el parquet.
Idempotente: se puede correr múltiples veces sin duplicar.

Uso:
  python sync_parquet_to_turso.py [--mes YYYY-MM] [--dry-run]

Env vars requeridas:
  LIBSQL_URL
  LIBSQL_AUTH_TOKEN

Por defecto sube TODAS las fechas presentes en el parquet (rango min..max).
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
PARQUET_PATH = PROJECT_ROOT / "data" / "historico" / "ventas_mes_actual.parquet"

COLS = [
    "tipo_movimiento", "bodega", "documento", "fecha_documento", "pedido",
    "estado_pedido", "tipo_despacho", "sku", "canal", "fecha_venta",
    "hora_venta", "producto", "categoria_macro", "categoria_padre",
    "categoria_hijo", "categoria_comercial", "estado_sku", "pack", "marca",
    "proveedor", "tipo_marca", "tipo_compra", "tipo_negocio", "kam",
    "estado_canal", "anio_venta", "mes_venta", "semana_venta", "dia_semana",
    "hora_venta_num", "cantidad", "venta_bruta", "venta_neta",
    "costo_unitario", "costo_total", "margen_front", "comision_pct",
    "comision", "logistica", "marketing", "margen_final",
]

BATCH_SIZE = 100
MAX_RETRIES = 3


def turso_pipeline(url: str, token: str, stmts: list, timeout: int = 180):
    """Ejecuta una secuencia de statements con retry en caso de timeout."""
    import time as _t
    body = {"requests": [{"type": "execute", "stmt": s} for s in stmts]}
    body["requests"].append({"type": "close"})
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(
                f"{url.rstrip('/')}/v2/pipeline",
                json=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=timeout,
            )
            r.raise_for_status()
            payload = r.json()
            for i, res in enumerate(payload.get("results", [])):
                if res.get("type") == "error":
                    raise RuntimeError(f"Turso stmt {i}: {res.get('error', {}).get('message')}")
            return payload
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            wait = 5 * (attempt + 1)
            print(f"    [retry {attempt+1}/{MAX_RETRIES}] {type(e).__name__}, esperando {wait}s...", flush=True)
            _t.sleep(wait)
    raise last_exc


def _to_arg(v):
    """Convierte valor Python a formato libsql args."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, (int,)):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if hasattr(v, 'isoformat'):  # pandas Timestamp/datetime
        return {"type": "text", "value": v.strftime('%Y-%m-%d')}
    return {"type": "text", "value": str(v)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", help="YYYY-MM. Default: rango total del parquet")
    ap.add_argument("--dry-run", action="store_true", help="No escribe Turso")
    args = ap.parse_args()

    url = os.environ.get("LIBSQL_URL", "").rstrip("/")
    token = os.environ.get("LIBSQL_AUTH_TOKEN", "")
    if not url or not token:
        print("[ERROR] Faltan LIBSQL_URL / LIBSQL_AUTH_TOKEN", flush=True)
        return 1

    if not PARQUET_PATH.exists():
        print(f"[ERROR] No existe {PARQUET_PATH}", flush=True)
        return 1

    print(f"=== Sync parquet → Turso — {datetime.now().isoformat()} ===", flush=True)
    print(f"[1] Leyendo {PARQUET_PATH}...", flush=True)
    df = pd.read_parquet(PARQUET_PATH)

    df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["fecha_venta"].notna()].copy()

    if args.mes:
        df = df[df["fecha_venta"].str.startswith(args.mes)]
        if df.empty:
            print(f"[WARN] No hay filas para mes {args.mes}", flush=True)
            return 0

    desde = df["fecha_venta"].min()
    hasta = df["fecha_venta"].max()
    print(f"    {len(df):,} filas, rango {desde} → {hasta}", flush=True)
    print(f"    Bruta total: ${df['venta_bruta'].sum():,.0f}", flush=True)

    # Asegurar que todas las cols existen
    for c in COLS:
        if c not in df.columns:
            df[c] = None
    df = df[COLS]

    if args.dry_run:
        print("[DRY-RUN] No escribe Turso.", flush=True)
        return 0

    # 1) DELETE rango
    print(f"\n[2] DELETE rango en Turso...", flush=True)
    del_stmt = {
        "sql": "DELETE FROM ventas WHERE fecha_venta >= ? AND fecha_venta <= ?",
        "args": [_to_arg(desde), _to_arg(hasta)],
    }
    turso_pipeline(url, token, [del_stmt])
    print(f"    DELETE OK ({desde} → {hasta})", flush=True)

    # 2) INSERT en batches
    cols_csv = ",".join(COLS)
    placeholders = ",".join(["?"] * len(COLS))
    insert_sql = f"INSERT INTO ventas ({cols_csv}) VALUES ({placeholders})"

    print(f"[3] INSERT en batches de {BATCH_SIZE}...", flush=True)
    rows = df.to_dict("records")
    total = len(rows)
    inserted = 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        stmts = []
        for r in batch:
            stmts.append({"sql": insert_sql, "args": [_to_arg(r[c]) for c in COLS]})
        turso_pipeline(url, token, stmts)
        inserted += len(batch)
        if i % (BATCH_SIZE * 10) == 0 or inserted == total:
            print(f"    {inserted:,}/{total:,} ({inserted*100//total}%)", flush=True)

    # 3) Verificación
    print(f"\n[4] Verificación...", flush=True)
    verify_stmt = {
        "sql": "SELECT COUNT(*) c, ROUND(SUM(venta_bruta),0) b FROM ventas WHERE fecha_venta >= ? AND fecha_venta <= ?",
        "args": [_to_arg(desde), _to_arg(hasta)],
    }
    res = turso_pipeline(url, token, [verify_stmt])
    row = res["results"][0]["response"]["result"]["rows"][0]
    n = int(row[0].get("value", "0")) if isinstance(row[0], dict) else int(row[0])
    b = float(row[1].get("value", "0")) if isinstance(row[1], dict) else float(row[1])
    print(f"    Turso: {n:,} filas, ${b:,.0f} bruta", flush=True)
    print(f"    Parquet: {total:,} filas, ${df['venta_bruta'].sum():,.0f} bruta", flush=True)
    if n == total:
        print(f"\nOK match", flush=True)
        return 0
    else:
        print(f"\n[WARN] desfase: {total - n} filas", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
