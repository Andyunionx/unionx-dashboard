# -*- coding: utf-8 -*-
"""
Rellena la columna `marca` vacía en el histórico congelado usando heal_marca
(self-heal por SKU + prefijo). Quirúrgico: NO toca ninguna otra columna ni fila.

Uso:
  python fill_marca_historico.py            # dry-run (muestra qué cambiaría)
  python fill_marca_historico.py --apply    # aplica (con backup .bak_marca_<ts>)
"""
import argparse
import shutil
from pathlib import Path

import pandas as pd

from mejoras_raw_overlay import heal_marca

ROOT = Path(__file__).resolve().parent
PQ = ROOT / "data" / "historico" / "ventas_historico.parquet"


def main(apply=False, ts="manual"):
    df = pd.read_parquet(PQ)
    antes = df["marca"].astype(str).str.strip()
    antes = antes.mask(antes.str.lower().isin({"none", "nan", "false", "0", "-", "sin marca"}), "").copy()
    df = heal_marca(df, verbose=True)
    despues = df["marca"].astype(str).str.strip()
    cambio = (antes == "") & (despues != "")
    n = int(cambio.sum())
    print(f"\nFilas con marca rellenada: {n:,}")
    if n:
        det = pd.DataFrame({"sku": df.loc[cambio, "sku"].astype(str), "marca": despues[cambio]})
        resumen = det.groupby(["sku", "marca"]).size().rename("filas").reset_index()
        print(resumen.to_string(index=False))
    # sanity: solo cambió marca
    if not apply:
        print(f"\n[DRY-RUN] no se escribió nada. Total filas: {len(df):,}")
        return
    bak = PQ.with_name(PQ.stem + f".parquet.bak_marca_{ts}")
    shutil.copy2(PQ, bak)
    df.to_parquet(PQ, index=False)
    print(f"\n[OK] aplicado. Backup: {bak.name}  ({len(df):,} filas, {df.shape[1]} cols)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ts", default="manual")
    main(**vars(ap.parse_args()))
