# -*- coding: utf-8 -*-
"""Genera el crossover de devoluciones (NC) por partida desde el RAW, para análisis.

Una fila por NC (documento), clasificada por el período de la venta original
(fecha_venta). Scope = líneas de negocio Marketplace/Fidelización/Páginas propias +
canal UnionX B2B (mismo scope que la vista Conciliación). Ver [[conciliacion_comercial_contable]].

Salida: data/outputs/Devoluciones_Crossover_por_partida_2026_ACTUALIZADO.xlsx
Uso:    python gen_crossover_devoluciones.py
"""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = (ROOT / "data" / "historico" / "ventas_historico.parquet").as_posix()
OUT = ROOT / "data" / "outputs" / "Devoluciones_Crossover_por_partida_2026_ACTUALIZADO.xlsx"
MES_NOM = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
           "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
SCOPE = "(tipo_negocio IN ('Marketplace','Fidelización','Páginas propias') OR canal='UnionX B2B')"


def main():
    con = duckdb.connect()
    d = con.execute(f"""
        SELECT documento "Doc NC",
               any_value(pedido) "Doc Venta original", any_value(pedido) "Pedido/Ref",
               any_value(canal) "Canal", any_value(kam) "KAM",
               max(CAST(fecha_venta AS VARCHAR)) "Fecha venta orig",
               max(CAST(fecha_documento AS VARCHAR)) "Fecha NC",
               sum(TRY_CAST(venta_neta AS DOUBLE)) "Venta",
               sum(TRY_CAST(costo_total AS DOUBLE)) "Costo Prod.",
               sum(TRY_CAST(comision AS DOUBLE)) "Com. Venta",
               sum(TRY_CAST(logistica AS DOUBLE)) "Com. Envío",
               sum(TRY_CAST(marketing AS DOUBLE)) "Marketing",
               sum(TRY_CAST(margen_final AS DOUBLE)) "Contribución"
        FROM '{RAW}'
        WHERE tipo_movimiento='Devolución' AND substr(CAST(fecha_documento AS VARCHAR),1,4)='2026' AND {SCOPE}
        GROUP BY documento
    """).fetchdf()

    d["Mes NC"] = d["Fecha NC"].str[:7]
    d["Fecha venta orig"] = d["Fecha venta orig"].str[:10]
    d["Fecha NC"] = d["Fecha NC"].str[:10]
    d["Margen"] = d["Venta"] - d["Costo Prod."]

    def origen(r):
        fv, fnc = str(r["Fecha venta orig"]), str(r["Fecha NC"])
        if len(fv) < 7 or fv > fnc:                       # sin fecha u origen posterior a la NC
            return "Origen no identificado"
        a, m = int(fv[:4]), int(fv[5:7])
        if a == 2026 and 1 <= m <= 12:
            return f"{MES_NOM[m]} 2026"
        return "Venta 2025 o antes" if a <= 2025 else "Origen no identificado"
    d["Origen"] = d.apply(origen, axis=1)

    cols = ["Mes NC", "Doc NC", "Doc Venta original", "Pedido/Ref", "Canal", "KAM", "Origen",
            "Fecha venta orig", "Fecha NC", "Venta", "Costo Prod.", "Margen",
            "Com. Venta", "Com. Envío", "Marketing", "Contribución"]
    datos = d[cols].sort_values(["Mes NC", "Canal", "Doc NC"]).reset_index(drop=True)
    por_canal = datos.groupby("Canal", as_index=False).agg(NC=("Doc NC", "count"), Venta=("Venta", "sum"), Margen=("Margen", "sum")).sort_values("Venta")
    por_kam = datos.groupby("KAM", as_index=False).agg(NC=("Doc NC", "count"), Venta=("Venta", "sum"), Margen=("Margen", "sum")).sort_values("Venta")
    por_origen = datos.groupby("Origen", as_index=False).agg(NC=("Doc NC", "count"), Venta=("Venta", "sum"), Costo=("Costo Prod.", "sum"), Margen=("Margen", "sum"))
    por_mes_canal = datos.groupby(["Mes NC", "Canal"], as_index=False).agg(NC=("Doc NC", "count"), Venta=("Venta", "sum"), Margen=("Margen", "sum"))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        datos.to_excel(xw, sheet_name="Datos", index=False)
        por_canal.to_excel(xw, sheet_name="Por canal", index=False)
        por_kam.to_excel(xw, sheet_name="Por KAM", index=False)
        por_origen.to_excel(xw, sheet_name="Por origen", index=False)
        por_mes_canal.to_excel(xw, sheet_name="Por mes y canal", index=False)
    print(f"[OK] {OUT.name}: {len(datos)} NC | Venta {datos['Venta'].sum()/1e6:.1f}M | Margen {datos['Margen'].sum()/1e6:.1f}M")


if __name__ == "__main__":
    main()
