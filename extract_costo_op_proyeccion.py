# -*- coding: utf-8 -*-
"""Genera data/finanzas/costo_op_proyeccion.parquet desde el Excel de costo op
ajustado (Detalle_Gasto_CC_Analitica), para que la app proyecte jun-dic con la
base con ajustes en vez del control_gestion crudo.

Scope: NÚCLEO operativo (sub-áreas Logística + Postventa + Operaciones), area=OPERACIONES.
Esquema compatible con control_gestion.parquet (overlay por mes/sub_area/CC/cuenta).
valor en MILES (Excel MM × 1000), signo negativo = gasto.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXCEL = ROOT / "data" / "outputs" / "Detalle_Gasto_CC_Analitica_2026.xlsx"
CG = ROOT / "data" / "finanzas" / "control_gestion.parquet"
OUT = ROOT / "data" / "finanzas" / "costo_op_proyeccion.parquet"

NUCLEO = ["LOGISTICA", "POSTVENTA", "OPERACIONES"]
MES_COL = {"Jun": 6, "Jul": 7, "Ago": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12}
MES_TXT = {6: "JUNIO", 7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE",
           11: "NOVIEMBRE", 12: "DICIEMBRE"}


def main():
    raw = pd.read_excel(EXCEL, header=None)
    ex = raw.iloc[3:].copy()
    ex.columns = ["CC", "SubArea", "Cuenta", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic", "Total"]
    ex = ex[ex["CC"].notna() & ~ex["CC"].astype(str).str.startswith("TOTAL") & ex["Cuenta"].notna()]
    ex = ex[ex["SubArea"].isin(NUCLEO)]
    for c in MES_COL:
        ex[c] = pd.to_numeric(ex[c], errors="coerce").fillna(0.0)

    # tipo_costo lookup desde control_gestion (dominante por centro_costo en OPERACIONES)
    tipo_map = {}
    if CG.exists():
        cg = pd.read_parquet(CG)
        opg = cg[(cg["area"] == "OPERACIONES") & (cg["kpi"] == "GASTO")]
        if "tipo_costo" in opg.columns:
            tipo_map = (opg.groupby("centro_costo")["tipo_costo"]
                        .agg(lambda s: s.dropna().mode().iloc[0] if not s.dropna().empty else "FIJO")
                        .to_dict())

    rows = []
    for _, row in ex.iterrows():
        cc = str(row["CC"]).strip()
        tipo = tipo_map.get(cc, "FIJO")
        for mcol, m in MES_COL.items():
            val_mm = float(row[mcol])
            if val_mm == 0:
                continue
            rows.append({
                "year": 2026, "month": m, "mes_text": MES_TXT[m],
                "escenario": "FCST", "kpi": "GASTO",
                "sub_area": str(row["SubArea"]).strip(), "area": "OPERACIONES",
                "tipo_costo": tipo, "centro_costo": cc,
                "cuenta_analitica": str(row["Cuenta"]).strip(),
                "valor": round(val_mm * 1000.0, 3),  # MM -> miles (signo negativo)
            })
    out = pd.DataFrame(rows)
    out["fecha"] = pd.to_datetime(out["year"].astype(str) + "-" + out["month"].astype(str) + "-01")
    out.to_parquet(OUT, index=False)
    tot = out["valor"].sum() / 1000.0
    print(f"OK {OUT.name}: {len(out)} filas | jun-dic núcleo = ${tot:,.1f}M | meses {sorted(out.month.unique())}")
    return out


if __name__ == "__main__":
    main()
