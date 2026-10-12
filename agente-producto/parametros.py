"""Parámetros por defecto del Agente Producto (Seba 9-oct-2026: "evaluar todos los factores de un producto para ver si es
rentable"). Cada parámetro sale de una fuente nuestra y queda con su origen en parametros.json, para que el agente nunca
use un número sin trazabilidad.

Fuentes:
  · Costeo de importación: motor de precosteo del agente COMEX (_REACTIVAR_NUEVO_PC/costear_embarque.py) y sus tarifas
    (agente-comex-auto/fase3_costeo.py): 3% Steven, agente de aduana 0,16% CIF, gastos Chile por contenedor.
  · Flete: última cotización de Seimex por puerto (API).  · Dólar: dólar observado del día (mindicador).
  · Costos de venta y operación, capital y EVA: corrida del ROI por producto (data/roi/roi_sku.parquet), mismas
    definiciones que roi_producto.py (costo de capital 9%, aduana 7 días, crédito flete 30 días, días de cobro).
Uso:  python parametros.py        (regenera parametros.json)
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).parent
REPO = AQUI.parent
SALIDA = AQUI / "parametros.json"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "_REACTIVAR_NUEVO_PC"))
sys.path.insert(0, str(REPO / "agente-comex-auto"))


def _p(valor, fuente, nota=""):
    return {"valor": valor, "fuente": fuente, **({"nota": nota} if nota else {})}


def dolar() -> dict:
    import requests
    try:
        s = requests.get("https://mindicador.cl/api/dolar", timeout=20).json()["serie"][0]
        return _p(round(float(s["valor"]), 2), f"Dólar observado {s['fecha'][:10]} (mindicador.cl)")
    except Exception as e:  # noqa: BLE001
        return _p(950.0, "Respaldo: TC fijo del costeo COMEX (fase3_costeo.TC_ADUANA)", f"sin dólar del día: {type(e).__name__}")


def fletes() -> dict:
    """Última cotización FCL de Seimex por puerto de origen (por fecha de creación de la operación)."""
    from seimex_api import SeimexAPI
    ops = SeimexAPI().get_operations()
    d = pd.DataFrame([{"origen": str(o.get("port_origin") or "").upper(), "carga": o.get("cargo_type"),
                       "cot": pd.to_numeric(o.get("quoted_freight_value"), errors="coerce"),
                       "creado": str(o.get("created_at"))[:10], "ref": o.get("reference_number")} for o in ops])
    d = d[d.carga.eq("FCL") & d.cot.notna()].sort_values("creado")
    # solo cotizaciones recientes: Xiamen y Qingdao tenían cotizaciones de 2025 (US$1.400–1.950), otro mercado de fletes
    d = d[pd.to_datetime(d.creado) >= pd.Timestamp(date.today()) - pd.Timedelta(days=120)]
    ult = d.iloc[-1]
    out = {}
    for puerto, patron in (("Shenzhen", "SHENZHEN|YANTIAN|SHEKOU"), ("Ningbo", "NINGBO|NIGNBO"), ("Xiamen", "XIAMEN"),
                           ("Qingdao", "QINGDAO")):
        x = d[d.origen.str.contains(patron, regex=True)]
        if len(x):
            u = x.iloc[-1]
            out[puerto] = _p(float(u.cot), f"Seimex: última cotización FCL desde {puerto} ({u.ref}, creada {u.creado})")
        else:
            out[puerto] = _p(float(ult.cot), f"Seimex: sin cotización reciente desde {puerto}; se usa la última de cualquier "
                                             f"puerto ({ult.ref}, creada {ult.creado})", "pedir cotización a Seimex")
    out["Otro"] = _p(float(ult.cot), f"Seimex: última cotización FCL de cualquier puerto ({ult.ref}, creada {ult.creado})")
    return out


def desde_roi() -> dict:
    """Tasas de operación, costos de venta por categoría y referencias, desde la última corrida del ROI."""
    s = pd.read_parquet(REPO / "data/roi/roi_sku.parquet")
    a = s[s.segmento.eq("Activo")]
    imp = a[a.modelo_compra.eq("Importación")]
    src = "ROI por producto (data/roi/roi_sku.parquet, SKU activos)"
    mkp_u = (a.unidades * (a.venta_mkp / a.venta.where(a.venta > 0)).fillna(0)).sum()
    out = {
        "almacenaje_m3_anio": _p(round(a.almacenaje.sum() / a.d_m3ca1.sum()), src, "pool de espacio / m³ de stock en Carrascal"),
        "manipulacion_u": _p(round(a.manipulacion.sum() / a.d_manip.sum(), 1), src, "pool de manipulación por unidad B2C equivalente"),
        "insumos_pedido": _p(round(a.insumos.sum() / a.pedidos_eq.sum(), 1), src, "pool de insumos por pedido"),
        "postventa_u_devuelta": _p(round(a.postventa.sum() / a.uds_dev.sum(), 1), src, "pool de postventa por unidad devuelta"),
        "uds_por_pedido": _p(round(a.uds_b2c.sum() / a.pedidos_eq.sum(), 3), src),
        "uds_caja_prom_b2b": _p(round(((a.uds_b2b + a.uds_ff) * a.uds_caja.where(a.uds_caja > 0)).sum()
                                      / (a.uds_b2b + a.uds_ff).where(a.uds_caja > 0).sum(), 2), src,
                                "unidades por caja promedio ponderado (manipulación por caja, igual que el ROI)"),
        "fulfillment_share_mkp": _p(round(a.uds_ff.sum() / mkp_u, 3), src, "parte de las unidades de marketplace que va a fulfillment (se manipula por caja)"),
    }
    pr = imp[(imp.pvp_mkp > 0) & (imp.precio_real > 0)]
    out["descuento_prom"] = _p(round(1 - (pr.precio_real * pr.unidades).sum() / (pr.pvp_mkp / 1.19 * pr.unidades).sum(), 3), src,
                               "precio real promedio vs precio de lista neto, ponderado por unidades (importados activos)")
    cat = {}
    for c, x in imp.groupby("categoria_macro"):
        if x.venta.sum() <= 0:
            continue
        cat[c] = {"contrib_pct": round(x.contribucion.sum() / x.venta.sum(), 4),
                  "com_pct": round(float(x.com_pct.median()), 4), "log_pct": round(float(x.log_pct.median()), 4),
                  "dev_pct": round(x.uds_dev.sum() / max(x.unidades.sum(), 1), 4),
                  "roi": round(x.contribucion.sum() / x.capital.sum(), 3), "skus": int(len(x)),
                  "uds_mes_mediana": round(float((x.unidades[x.unidades > 0] / 12).median()), 1),
                  "m3_u_mediana": round(float(x.m3_unit[x.m3_unit > 0].median()), 5) if (x.m3_unit > 0).any() else None}
    tot = {"contrib_pct": round(imp.contribucion.sum() / imp.venta.sum(), 4), "com_pct": round(float(imp.com_pct.median()), 4),
           "log_pct": round(float(imp.log_pct.median()), 4), "dev_pct": round(imp.uds_dev.sum() / imp.unidades.sum(), 4),
           "roi": round(imp.contribucion.sum() / imp.capital.sum(), 3), "skus": int(len(imp)),
           "uds_mes_mediana": round(float((imp.unidades[imp.unidades > 0] / 12).median()), 1),
           "m3_u_mediana": round(float(imp.m3_unit[imp.m3_unit > 0].median()), 5)}
    cat["Todas"] = tot
    out["categorias"] = _p(cat, src, "contribución de referencia y comisión/logística de marketplace (mediana de la Maestra Pricing) por categoría")
    return out


NEG = {"Marketplace": "mkp", "Páginas propias": "web", "Fidelización": "fid", "Distribución": "b2b", "Corporativo": "b2b"}
RAW_DESDE = "2026-08-01"      # desde agosto el RAW trae comisión, logística y marketing reales por pedido (antes: solo Falabella y ML)


def desde_raw() -> dict:
    """Margen final real por categoría y canal (RAW de ventas, Venta + Devolución desde ago-2026):
    margen final = venta − costo − comisión − logística − marketing."""
    import duckdb
    src = (f"read_parquet(['{(REPO / 'data/historico/ventas_historico.parquet').as_posix()}',"
           f"'{(REPO / 'data/historico/ventas_mes_actual.parquet').as_posix()}'], union_by_name=true)")
    d = duckdb.connect().execute(f"""SELECT categoria_macro, categoria_padre, tipo_negocio, sum(venta_neta) v, sum(costo_total) c,
                                            sum(comision) com, sum(logistica) log, sum(marketing) mkt, sum(margen_final) mf
                                     FROM {src} WHERE fecha_venta >= '{RAW_DESDE}' AND tipo_negocio IS NOT NULL
                                     GROUP BY ALL""").df()
    d["neg"] = d.tipo_negocio.map(NEG)
    d = d[d.neg.notna()]

    def resumen(x):
        v = x.v.sum()
        out = {"venta": round(float(v)), "margen_front": round(float(1 - x.c.sum() / v), 4) if v else None,
               "margen_final": round(float(x.mf.sum() / v), 4) if v else None, "por_canal": {}}
        for n, g in x.groupby("neg"):
            vv = g.v.sum()
            if vv > 0:
                out["por_canal"][n] = {"venta": round(float(vv)), "com": round(float(g.com.sum() / vv), 4),
                                       "log": round(float(g.log.sum() / vv), 4), "mkt": round(float(g.mkt.sum() / vv), 4),
                                       "margen_final": round(float(g.mf.sum() / vv), 4), "mix": round(float(vv / v), 4)}
        return out
    macro = {c: resumen(g) for c, g in d.groupby("categoria_macro")}
    padre = {f"{m} / {c}": resumen(g) for (m, c), g in d.groupby(["categoria_macro", "categoria_padre"]) if g.v.sum() > 5e6}
    macro["Todas"] = resumen(d)
    return {"raw_desde": _p(RAW_DESDE, "RAW de ventas"),
            "raw_categorias": _p(macro, f"RAW de ventas desde {RAW_DESDE} (margen final = venta − costo − comisión − logística − marketing)"),
            "raw_subcategorias": _p(padre, f"RAW de ventas desde {RAW_DESDE}, subcategorías con venta > $5 MM")}


def construir() -> dict:
    import costear_embarque as ce
    import roi_producto as rp
    from fase3_costeo import CHILE_GASTOS
    dc = rp.dias_cobro()
    fc = pd.read_parquet(Path("C:/Users/andre/comex_maestra/analisis/flete_centros.parquet"))
    fc = fc[(fc.fuente == "precosteo") & ~fc.aereo & fc.comision_steven.notna()].sort_values("eta").tail(12)
    fijo = (fc.inland_china - fc.comision_steven).median()
    p = {
        "generado": str(date.today()),
        "tc": dolar(),
        "iva": _p(0.19, "Ley"),
        # importación
        "comision_steven": _p(0.03, "Costeo COMEX (costear_embarque.calcular_costeo)", "3% sobre P×Q + local charge"),
        "local_charge_contenedor": _p(round(float(fijo) - 55, 1), "Mediana de los últimos 12 precosteos marítimos (inland China sin comisión) − Form F",
                                      "local charge + long vehicle por contenedor, USD"),
        "form_f": _p(55.0, "PI de Steven (línea FF)", "USD por embarque"),
        "capacidad_40hq_m3": _p(68.0, "Costeo COMEX (Tarifas.capacidad_40hq_cbm)"),
        "fletes_40hq": _p(fletes(), "Seimex API"),
        "flete_lcl_m3": _p(None, "Sin tarifa LCL vigente", "pedir cotización a Seimex; obligatorio si la modalidad es LCL"),
        "gastos_chile_contenedor": _p(float(sum(CHILE_GASTOS.values())), "Costeo COMEX (fase3_costeo.CHILE_GASTOS)", "CLP por contenedor"),
        "gastos_chile_lcl": _p(1418318.0, "Único LCL desde Shenzhen (25TP0124, mar-2025, Maestra)", "CLP por embarque LCL; 1 solo caso"),
        "agente_aduana_pct": _p(ce.PCT_AGENTE_ADUANA, "Costeo COMEX (PCT_AGENTE_ADUANA)", "sobre CIF"),
        "arancel_pct": _p(0.0, "TLC Chile–China con certificado de origen (Form F)", "6% si no hay certificado"),
        "seguro_pct": _p(0.0, "El costeo COMEX marítimo no carga seguro", "poner el % si se contrata"),
        # plazos (iguales al ROI)
        "transito_dias": _p(dict(rp.TRANSITO_DIAS, Xiamen=rp.TRANSITO_DEFAULT, Otro=rp.TRANSITO_DEFAULT), "ROI por producto (TRANSITO_DIAS)",
                            "medianas reales Seimex: Shenzhen 51, Ningbo 42,5, Xiamen 53"),
        "aduana_dias": _p(rp.ADUANA_DIAS, "ROI por producto"),
        "credito_flete_dias": _p(rp.CREDITO_FLETE_INTERNACION_DIAS, "ROI por producto", "flete e internación se pagan a 30 días"),
        "lt_produccion_dias": _p(rp.LT_PRODUCCION_DEFAULT, "ROI por producto (LT_PRODUCCION_DEFAULT)"),
        "anticipo_pct": _p(0.30, "Condición más común en la Maestra Productos (30/70)"),
        "saldo_en": _p("Origen", "ROI por producto (regla de pago: el saldo se paga en origen al embarcar)"),
        "dias_cobro": _p(round(float(dc["dias"]), 1), "ROI por producto (CxC comerciales / venta con IVA × 365)"),
        "iva_recupero_meses": _p(1, "Supuesto", "el IVA de importación se recupera como crédito fiscal el mes siguiente"),
        # venta
        "marketing_pct": _p(0.03, "Decisión Andrés 9-oct: lineal 3% (peso real de marketing en el EERR)", "no aplica a B2B"),
        "canal_web": _p({"com": 0.03, "log": 0.096}, "ROI por producto (tasas reales ponderadas por venta 12m)"),
        "canal_fid": _p({"com": 0.016, "log": 0.012}, "ROI por producto (fidelización, promedio ponderado)"),
        "canal_b2b": _p({"com": 0.007, "log": 0.009}, "ROI por producto (B2B)"),
        "mix_default": _p({"mkp": 0.60, "web": 0.25, "fid": 0.15, "b2b": 0.0}, "ROI por producto (MIX_DEFAULT del mix personalizado)"),
        "factor_precio_b2b": _p(1.0, "Supuesto", "precio B2B / precio de lista neto; poner el real si hay B2B en el mix"),
        "inventario_prom_factor": _p(0.5, "Supuesto", "stock promedio = 50% del lote (compra por lotes)"),
        "peso_b2b_manip": _p(rp.PESO_B2B, "ROI por producto (PESO_B2B, ABC)"),
        "tasa_capital": _p(rp.TASA_CAPITAL, "ROI por producto (definición Andrés)"),
        # escenarios y decisión
        "escenarios": _p({"conservador": {"vel": 0.70, "precio": 0.90, "tc": 1.10},
                          "base": {"vel": 1.0, "precio": 1.0, "tc": 1.0},
                          "optimista": {"vel": 1.20, "precio": 1.0, "tc": 1.0, "sin_descuento": True}}, "Prompt del agente (Seba)"),
        "umbral_competencia": _p(0.10, "Supuesto", "si nuestro FOB supera al de la competencia en más de esto, no puede ser COMPRAR"),
        "guerra_precios_factor": _p(5.0, "Supuesto", "si un competidor importa ≥ 5× nuestro volumen anual: conservador con precio −15%"),
    }
    p.update(desde_roi())
    p.update(desde_raw())
    return p


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = construir()
    SALIDA.write_text(json.dumps(p, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
    # copia para la nube: viaja en el zip privado del radar (radar-aduana/pipeline/publicar_nube.py empaqueta el hub)
    hub = Path("C:/Users/andre/radar_aduana/outputs/hub")
    if hub.exists():
        (hub / "parametros_producto.json").write_text(SALIDA.read_text(encoding="utf-8"), encoding="utf-8")
        cols = ["producto", "marca", "categoria_macro", "categoria_padre", "unidades", "venta", "venta_mkp", "venta_web", "venta_fid",
                "venta_b2b", "pvp_mkp", "precio_real", "com_pct", "log_pct", "contrib_pct", "m3_unit", "uds_caja"]
        pd.read_parquet(REPO / "data/roi/roi_sku.parquet")[cols].to_parquet(hub / "productos_roi.parquet")
        print(f"copia para la nube en {hub}")
    print(f"OK {SALIDA} · TC {p['tc']['valor']} · fletes {{{', '.join(f'{k}: {v['valor']}' for k, v in p['fletes_40hq']['valor'].items())}}}")
