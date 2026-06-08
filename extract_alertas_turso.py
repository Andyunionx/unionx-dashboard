#!/usr/bin/env python3
"""
Exporta la tabla `alertas` de Turso a parquet committeable.

Output: data/exports/alertas.parquet

Uso:
  python extract_alertas_turso.py

Requiere env vars:
  LIBSQL_URL          - URL de la base Turso
  LIBSQL_AUTH_TOKEN   - Token de auth

Pensado para alimentar el Hub (Vercel + Supabase) vía GitHub Raw.
Genera dump completo de la tabla, no incremental. Schema:
  id, fecha_creada, fecha_objetivo, fecha_resuelta,
  tipo, severity, titulo, mensaje, contexto, target_apps,
  status, resuelta_por

Workflow: .github/workflows/sync_alertas_export.yml (cron diario).
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / "data" / "exports"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PARQUET = OUT_DIR / "alertas.parquet"

COLS = [
    "id", "fecha_creada", "fecha_objetivo", "fecha_resuelta",
    "tipo", "severity", "titulo", "mensaje", "contexto",
    "target_apps", "status", "resuelta_por",
]


def main():
    url = os.environ.get("LIBSQL_URL", "").rstrip("/")
    token = os.environ.get("LIBSQL_AUTH_TOKEN", "")
    if not url or not token:
        print("[ERROR] Faltan LIBSQL_URL / LIBSQL_AUTH_TOKEN", flush=True)
        return 1

    cols_csv = ",".join(COLS)
    sql = f"SELECT {cols_csv} FROM alertas ORDER BY id DESC"
    body = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql}},
            {"type": "close"},
        ]
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    print(f"=== Export alertas Turso — {datetime.now().isoformat()} ===", flush=True)
    print(f"[1] Query Turso...", flush=True)
    r = requests.post(f"{url}/v2/pipeline", json=body, headers=headers, timeout=60)
    r.raise_for_status()
    payload = r.json()

    result = payload["results"][0]
    if result.get("type") == "error":
        msg = result.get("error", {}).get("message", "")
        if "BLOCKED" in msg or "blocked" in msg.lower():
            print(f"[WARN] Turso bloqueado por cuota: {msg}", flush=True)
            print("[WARN] Saltando export — el parquet anterior se mantiene", flush=True)
            return 0
        print(f"[ERROR] Turso: {msg}", flush=True)
        return 1

    response = result.get("response", {}).get("result", {})
    rows = response.get("rows", [])
    print(f"    {len(rows):,} filas recibidas", flush=True)

    if not rows:
        print("[WARN] Tabla alertas vacía", flush=True)
        df = pd.DataFrame(columns=COLS)
    else:
        flat = []
        for r_obj in rows:
            row = []
            for c in r_obj:
                if isinstance(c, dict):
                    row.append(c.get("value"))
                else:
                    row.append(c)
            flat.append(row)
        df = pd.DataFrame(flat, columns=COLS)

    # Tipos
    if not df.empty:
        df["id"] = pd.to_numeric(df["id"], errors="coerce").astype("Int64")
        for c in ("fecha_creada", "fecha_objetivo", "fecha_resuelta"):
            df[c] = pd.to_datetime(df[c], errors="coerce")

    print(f"[2] Guardando parquet...", flush=True)
    df.to_parquet(OUT_PARQUET, index=False)
    size = OUT_PARQUET.stat().st_size
    print(f"    {OUT_PARQUET.relative_to(PROJECT_ROOT)} ({size:,} bytes)", flush=True)

    print(f"\n=== RESUMEN ===", flush=True)
    print(f"  Filas totales: {len(df):,}", flush=True)
    if not df.empty:
        print(f"  Por status: {df['status'].value_counts().to_dict()}", flush=True)
        print(f"  Por severity: {df['severity'].value_counts().to_dict()}", flush=True)
        print(f"  Por target_apps: {df['target_apps'].value_counts().head(5).to_dict()}", flush=True)
        if df["fecha_creada"].notna().any():
            print(f"  Rango fechas: {df['fecha_creada'].min()} → {df['fecha_creada'].max()}", flush=True)
    print("\nOK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
