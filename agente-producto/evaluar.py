"""Evalúa un producto: python evaluar.py cotizacion.json [--sin-radar]

cotizacion.json (los críticos son precio_usd, qty, uds_ctn, cbm_ctn y pvp_iva; el resto tiene supuesto por defecto):
  {"nombre": "...", "fabrica": "...", "precio_usd": 22.5, "incoterm": "EXW", "qty": 3500, "uds_ctn": 15, "cbm_ctn": 0.083,
   "puerto": "Xiamen", "modalidad": "Consolidado" | "Contenedor propio" | "LCL", "flete_contenedor_usd": 8550,
   "pvp_iva": 69990, "velocidad_mes": 300, "categoria_macro": "Fashion",
   "radar": {"tipo": "Mochilas outdoor", "arancel": "42029220", "palabras": ["NOTEBOOK"]}}
Salida en salidas/<nombre>_<fecha>/: informe.md, resultado.json (para otros agentes) y el Excel con fórmulas.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))
import informe  # noqa: E402
import motor as M  # noqa: E402


def correr(cot: dict, con_radar: bool = True, excel: bool = True) -> dict:
    par = M.cargar_parametros()
    p, _, falta = M.completar(cot, par)
    radar = None
    if con_radar and not falta:
        import radar_cruce as R
        if not p.get("precio_usd"):            # solo PVP: primero el costo máximo, y con ese costo se arma la banda del radar
            r0 = M.evaluar(cot, par, None)
            if r0["estado"] != "OK":
                return {**r0, "carpeta": None}
            p = r0["producto"]
        imp = M.importacion(p, par)
        rq = cot.get("radar") or {}
        radar = R.cruzar(fob_u=imp["fob_china_usd"] / p["qty"], tipo=rq.get("tipo"), arancel=rq.get("arancel") or p.get("arancel"),
                         palabras=rq.get("palabras"), unidad=rq.get("unidad", "U"), tc=par["tc"],
                         factor_internacion=(imp["agente_usd"] + imp["gastos_chile_clp"] / par["tc"]) / imp["cif_usd"])
    r = M.evaluar(cot, par, radar)
    nombre = re.sub(r"[^\w-]+", "_", str(cot.get("nombre", "producto")))[:40]
    out = AQUI / "salidas" / f"{nombre}_{date.today():%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "informe.md").write_text(informe.markdown(r), encoding="utf-8")
    informe.guardar_json(r, out / "resultado.json")
    if excel and r["estado"] == "OK":
        import excel_evaluacion as X
        X.armar(r, par, out / f"Evaluacion_{nombre}.xlsx")
    r["carpeta"] = str(out)
    return r


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cot = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    r = correr(cot, "--sin-radar" not in sys.argv, "--sin-excel" not in sys.argv)
    print(informe.markdown(r))
    print("\n→", r["carpeta"])
