#!/usr/bin/env python3
"""Sync parquet → Turso FAST: usa multi-VALUES bulk insert."""
import argparse
import os
import sys
import time
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

ROWS_PER_STMT = 500


def _to_arg(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, (int,)):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if hasattr(v, 'isoformat'):
        return {"type": "text", "value": v.strftime('%Y-%m-%d')}
    return {"type": "text", "value": str(v)}


def turso_exec(url, token, stmt, timeout=180, retries=3):
    body = {"requests": [{"type": "execute", "stmt": stmt}, {"type": "close"}]}
    last = None
    for i in range(retries):
        try:
            r = requests.post(
                f"{url.rstrip('/')}/v2/pipeline",
                json=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=timeout,
            )
            r.raise_for_status()
            payload = r.json()
            for res in payload.get("results", []):
                if res.get("type") == "error":
                    raise RuntimeError(res.get('error', {}).get('message'))
            return payload
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last = e
            time.sleep(3 * (i + 1))
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", help="YYYY-MM")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    url = os.environ.get("LIBSQL_URL", "").rstrip("/")
    token = os.environ.get("LIBSQL_AUTH_TOKEN", "")
    if not url or not token:
        print("[ERROR] Faltan env vars", flush=True)
        return 1

    print(f"=== FAST sync — {datetime.now().isoformat()} ===", flush=True)
    df = pd.read_parquet(PARQUET_PATH)
    df["fecha_venta"] = pd.to_datetime(df["fecha_venta"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["fecha_venta"].notna()].copy()

    if args.mes:
        df = df[df["fecha_venta"].str.startswith(args.mes)]
        if df.empty:
            print(f"[WARN] sin filas para {args.mes}", flush=True)
            return 0

    # GUARD: mayo y meses anteriores son FOTOS (viven en histórico parquet),
    # nunca tocar en Turso. Solo se sincroniza junio en adelante.
    pre_n = len(df)
    df = df[df["fecha_venta"] >= "2026-06-01"]
    if len(df) < pre_n:
        print(f"[GUARD] Filtradas {pre_n - len(df)} filas anteriores a junio (mayo es foto)", flush=True)
    if df.empty:
        print(f"[WARN] No hay filas >= 2026-06-01 para sincronizar a Turso", flush=True)
        return 0

    desde = df["fecha_venta"].min()
    hasta = df["fecha_venta"].max()
    print(f"  {len(df):,} filas, {desde} → {hasta}, ${df['venta_bruta'].sum():,.0f}", flush=True)

    for c in COLS:
        if c not in df.columns:
            df[c] = None
    df = df[COLS]

    if args.dry_run:
        return 0

    # DELETE
    print("[DELETE]", flush=True)
    turso_exec(url, token, {
        "sql": "DELETE FROM ventas WHERE fecha_venta >= ? AND fecha_venta <= ?",
        "args": [_to_arg(desde), _to_arg(hasta)],
    })

    # INSERT multi-VALUES
    print(f"[INSERT batch {ROWS_PER_STMT}]", flush=True)
    cols_csv = ",".join(COLS)
    single_placeholders = "(" + ",".join(["?"] * len(COLS)) + ")"
    rows = df.to_dict("records")
    total = len(rows)
    t0 = time.time()

    for i in range(0, total, ROWS_PER_STMT):
        batch = rows[i:i + ROWS_PER_STMT]
        values_sql = ",".join([single_placeholders] * len(batch))
        sql = f"INSERT INTO ventas ({cols_csv}) VALUES {values_sql}"
        args_list = []
        for r in batch:
            for c in COLS:
                args_list.append(_to_arg(r[c]))
        turso_exec(url, token, {"sql": sql, "args": args_list})
        done = min(i + ROWS_PER_STMT, total)
        rate = done / (time.time() - t0)
        eta = (total - done) / rate if rate else 0
        print(f"  {done:,}/{total:,} ({done*100//total}%) | {rate:.0f} r/s | ETA {eta:.0f}s", flush=True)

    # Verify
    res = turso_exec(url, token, {
        "sql": "SELECT COUNT(*), ROUND(SUM(venta_bruta),0) FROM ventas WHERE fecha_venta >= ? AND fecha_venta <= ?",
        "args": [_to_arg(desde), _to_arg(hasta)],
    })
    row = res["results"][0]["response"]["result"]["rows"][0]
    n = int(row[0].get("value", "0"))
    b = float(row[1].get("value", "0"))
    print(f"\n[VERIFY] Turso: {n:,} filas, ${b:,.0f} | Parquet: {total:,} filas, ${df['venta_bruta'].sum():,.0f}", flush=True)
    return 0 if n == total else 1


if __name__ == "__main__":
    sys.exit(main())
