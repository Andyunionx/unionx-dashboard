# -*- coding: utf-8 -*-
"""Snapshot de la planilla crossover (NC CONTABLES) -> parquet para la conciliación.

Lente contable de devoluciones: notas de crédito posteadas (account.move out_refund)
linkeadas a su factura original vía reversed_entry_id (ver analisis_nc_odoo_h1.py).
NO usar la Devolución del RAW operacional en la conciliación: cuenta anulaciones B2B
gigantes (Concesionarios autos, Paris tienda) + devoluciones sin NC posteada.

Fuente: data/outputs/Devoluciones_Crossover_por_partida_2026.xlsx (hoja 'Datos').
Salida: data/contabilidad/nc_crossover_h1.parquet
        (Canal, reg_mes, OrigenAnio, OrigenMes, venta, costo)  — venta/costo NEGATIVOS.

Regenerar cuando se actualice el crossover (p.ej. al entrar junio):
    python build_nc_crossover.py
"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "data" / "outputs" / "Devoluciones_Crossover_por_partida_2026.xlsx"
OUT = ROOT / "data" / "contabilidad" / "nc_crossover_h1.parquet"
HASTA = "2026-05"  # H1 ene-may (junio entra con su EERR)

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


def parse_origen(o):
    ol = str(o).strip().lower()
    if "2025" in ol or "antes" in ol:
        return 2025, 0
    if "no identificado" in ol:
        return 0, 0
    m = next((n for k, n in MESES.items() if k in ol), 0)
    return (2026, m) if m else (0, 0)


def main():
    d = pd.read_excel(SRC, "Datos")
    d = d[d["Mes NC"].astype(str) <= HASTA].copy()
    d[["OrigenAnio", "OrigenMes"]] = pd.DataFrame(d["Origen"].map(parse_origen).tolist(), index=d.index)
    d["reg_mes"] = d["Mes NC"].astype(str).str[5:7].astype(int)
    agg = (d.groupby(["Canal", "reg_mes", "OrigenAnio", "OrigenMes"], as_index=False)
           .agg(venta=("Venta", "sum"), costo=("Costo Prod.", "sum")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    agg.to_parquet(OUT, index=False)
    print(f"[OK] {OUT.relative_to(ROOT)}: {len(agg)} filas ({len(d)} partidas). "
          f"Total venta {d['Venta'].sum()/1e6:.1f}M / costo {d['Costo Prod.'].sum()/1e6:.1f}M")


if __name__ == "__main__":
    main()
