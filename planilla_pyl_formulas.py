# -*- coding: utf-8 -*-
"""
Genera el Excel 'PyL_Comercial_vs_Contable_H1.xlsx' (P&L Comercial vs Contable con
fórmulas + selectores Mes/Canal/KAM + reconciliación paso a paso).

La lógica vive en views/_conciliacion.py (compartida con la vista del dashboard).
Este script solo carga los datos vía gspread/parquet y arma el libro.
"""
import sys
from pathlib import Path

import duckdb
import gspread
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from views._conciliacion import construir_dataframes, construir_workbook  # noqa: E402

OUT = ROOT / "data" / "outputs" / "PyL_Comercial_vs_Contable_H1.xlsx"
PARQUET = ROOT / "data" / "historico" / "ventas_historico.parquet"
NC_DET = ROOT / "data" / "contabilidad" / "nc_detalle_h1.parquet"
SHEET_ID = "1O7bRbY3v7Wc8atMu2I4PJ-pgA_Sy0-g57-iz0CSu4m4"


def main():
    gc = gspread.service_account(filename=str(ROOT / "credentials.json"))
    sh = gc.open_by_key(SHEET_ID)
    raw = sh.worksheet("Análisis de Resultados").get_all_values()
    df_ar = pd.DataFrame(raw[1:], columns=range(len(raw[0])))
    gl = sh.worksheet("Detalle Glosas 2026").get_all_values()
    df_glosas = pd.DataFrame(gl[1:], columns=gl[0])
    nc_detalle = pd.read_parquet(NC_DET) if NC_DET.exists() else None
    nc2c = {}
    if nc_detalle is not None:
        rows = duckdb.connect().execute(f"""
            SELECT documento, canal FROM '{PARQUET.as_posix()}'
            WHERE tipo_movimiento='Devolución' GROUP BY documento, canal
            QUALIFY row_number() OVER (PARTITION BY documento ORDER BY SUM(abs(venta_bruta)) DESC)=1
        """).fetchall()
        nc2c = {d: c for d, c in rows}

    bundle = construir_dataframes(df_ar, df_glosas, nc_detalle, nc2c)
    wb = construir_workbook(bundle)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"✓ {OUT.relative_to(ROOT)}")
    print(f"  Datos {len(bundle['datos'])} | NC {len(bundle['nc_tab'])} | "
          f"Comisiones {len(bundle['com_tab'])} | canales {len(bundle['canales'])} | KAMs {bundle['kams']}")


if __name__ == "__main__":
    main()
