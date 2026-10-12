"""Motor del Agente Producto: ¿conviene comprar este producto? (Seba 9-oct-2026).

Mismas definiciones que ya usa la empresa, para que el agente no diga una cosa y los reportes otra:
  · Costo internado = motor de precosteo del agente COMEX (costear_embarque.calcular_costeo): P×Q + 3% Steven sobre
    (P×Q + local charge) + local charge + Form F + flete por CBM + agente de aduana 0,16% del CIF + gastos Chile.
  · Contribución, capital, EVA = ROI por producto (roi_producto.metricas): contribución = venta − costo − comisión −
    logística − marketing − almacenaje − manipulación − insumos − postventa; capital = anticipo en producción + pagado
    en tránsito + aduana + inventario + CxC − crédito de flete/internación; EVA = contribución − 9% × capital.
  · Decisión (Andrés 9-oct, "igual que el ROI"): COMPRAR si el EVA del escenario conservador es positivo y la
    contribución base alcanza la de su categoría; NO COMPRAR si el EVA base no es positivo; si no, NEGOCIAR.
Todo en CLP salvo lo marcado USD. Los precios de venta vienen con IVA y se trabajan netos (÷ 1,19).
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

AQUI = Path(__file__).parent
CANALES = ("mkp", "web", "fid", "b2b")
CANAL_TXT = {"mkp": "Marketplace", "web": "Páginas web", "fid": "Fidelización", "b2b": "B2B"}


def redondear(x: float) -> int:
    """Redondeo hacia arriba en .5, igual que REDONDEAR de Excel (round() de Python redondea al par)."""
    return int(math.floor(x + 0.5))


# ── parámetros y entrada ────────────────────────────────────────────────────
def _dato(en_hub: str, local: Path) -> Path:
    """En la nube (App Ventas / Hub) los datos internos viajan en el zip PRIVADO del radar (nunca en el repo público)."""
    import os
    hub = os.environ.get("AGENTE_PRODUCTO_HUB")
    return Path(hub) / en_hub if hub and (Path(hub) / en_hub).exists() else local


def cargar_parametros(path: Path | None = None) -> dict:
    raw = json.loads((path or _dato("parametros_producto.json", AQUI / "parametros.json")).read_text(encoding="utf-8"))
    return {k: (v["valor"] if isinstance(v, dict) and "valor" in v else v) for k, v in raw.items()}


CRITICOS = ("qty",)            # además: precio de compra o precio de venta (al menos uno); la caja sale del SKU similar o de la categoría


def completar(prod: dict, par: dict) -> tuple[dict, list, list]:
    """Rellena lo que falta con los parámetros por defecto. Devuelve (producto, supuestos usados, faltantes críticos)."""
    p = copy.deepcopy(prod)
    sup, alertas = [], []
    sim = similar(p.get("sku_similar")) if p.get("sku_similar") else None
    if p.get("sku_similar") and sim is None:
        alertas.append(f"no encontré el SKU similar {p['sku_similar']} en el ROI")
    if sim:
        # lo que no viene en la cotización se toma de las ventas reales del producto parecido (ROI, últimos 12 meses)
        txt = f"del SKU similar {p['sku_similar']} ({sim['producto'][:40]})"
        for k, v, d in (("pvp_iva", sim["pvp"], f"precio de lista {txt}"), ("velocidad_mes", sim["vel"], f"velocidad {sim['vel']:.0f} u/mes {txt}"),
                        ("mix", sim["mix"], f"mix de canales {txt}"), ("categoria_macro", sim["cat"], f"categoría {txt}"),
                        ("descuento", sim["desc"], f"descuento real {sim['desc']:.1%} {txt}" if sim["desc"] is not None else "")):
            if p.get(k) in (None, "") and v is not None:
                p[k] = v
                if d:
                    sup.append(d)
    falta = [k for k in CRITICOS if p.get(k) in (None, "", 0)]
    if p.get("precio_usd") in (None, "", 0) and p.get("pvp_iva") in (None, "", 0):
        falta.append("precio de compra o precio de venta (al menos uno)")
    cats = par["categorias"]
    cat = p.get("categoria_macro") if p.get("categoria_macro") in cats else "Todas"
    if p.get("categoria_macro") not in cats:
        sup.append("categoria_macro → referencia de todos los importados")
    p["categoria_ref"] = cat

    def d(k, v, txt=None):
        if p.get(k) in (None, ""):
            p[k] = v
            sup.append(txt or f"{k} = {v}")
    if p.get("uds_ctn") in (None, "", 0) or p.get("cbm_ctn") in (None, "", 0):
        if sim and sim.get("m3_u"):
            u_c = sim.get("uds_caja") or 1
            p["uds_ctn"], p["cbm_ctn"] = u_c, sim["m3_u"] * u_c
            sup.append(f"caja master: {u_c:.0f} u y {sim['m3_u']:.4f} m³/u del SKU similar")
        else:
            m3 = cats[cat].get("m3_u_mediana") or cats["Todas"]["m3_u_mediana"]
            p["uds_ctn"], p["cbm_ctn"] = 1, m3
            sup.append(f"volumen por unidad = mediana de {cat} ({m3:.4f} m³/u); sin caja master")
            alertas.append("sin medidas de la caja master: el flete y el almacenaje son estimados")
    d("incoterm", "EXW")
    d("via_steven", True, "compra vía Steven (3% + local charge)")
    d("puerto", "Shenzhen")
    d("modalidad", "Consolidado", "modalidad: consolidado con otros productos en un 40HQ (paga su parte por CBM)")
    fl = par["fletes_40hq"]
    d("flete_contenedor_usd", (fl.get(p["puerto"]) or fl["Otro"])["valor"], f"flete 40HQ = última cotización Seimex ({p['puerto']})")
    d("descuento", par["descuento_prom"], f"descuento promedio sobre lista = {par['descuento_prom']:.1%} (real de los importados)")
    d("mix", dict(par["mix_default"]), "mix de canales 60% marketplace / 25% web / 15% fidelización (ROI)")
    d("factor_precio_b2b", par["factor_precio_b2b"])
    d("lt_produccion", par["lt_produccion_dias"], f"producción {par['lt_produccion_dias']} días")
    d("anticipo_pct", par["anticipo_pct"], "pago 30/70")
    d("saldo_en", par["saldo_en"], "saldo pagado en origen al embarcar")
    d("arancel_pct", par["arancel_pct"], "arancel 0% (TLC con certificado de origen)")
    d("seguro_pct", par["seguro_pct"])
    raw = par.get("raw_categorias", {})
    rc = raw.get(p.get("categoria_macro")) or raw.get("Todas", {})
    for c in CANALES:
        pc = (rc.get("por_canal") or {}).get(c)
        if not pc or pc["venta"] < 3e6:                        # poca venta del canal en la categoría → total de la empresa
            pc = raw.get("Todas", {}).get("por_canal", {}).get(c, {"com": 0.0, "log": 0.0})
            fuente = "total empresa"
        else:
            fuente = p.get("categoria_macro")
        d(f"com_{c}", pc["com"], f"comisión {CANAL_TXT[c].lower()} = RAW {fuente} ({pc['com']:.1%})")
        d(f"log_{c}", pc["log"], f"logística {CANAL_TXT[c].lower()} = RAW {fuente} ({pc['log']:.1%})")
    d("dev_pct", cats[cat]["dev_pct"], f"devoluciones = {cats[cat]['dev_pct']:.1%} de las unidades ({cat})")
    d("marketing_pct", par["marketing_pct"], "marketing lineal 3%")
    if p.get("velocidad_mes") in (None, "", 0):
        p["velocidad_mes"] = cats[cat]["uds_mes_mediana"]
        sup.append(f"velocidad de venta = mediana de los importados de {cat} ({p['velocidad_mes']:.0f} u/mes)")
        alertas.append(f"la velocidad de venta es un supuesto (mediana de {cat}): define el resultado, confirmarla o indicar un SKU similar")
    if p.get("modalidad") == "LCL" and not p.get("flete_lcl_m3"):
        falta.append("flete_lcl_m3 (tarifa LCL todo incluido por m³)")
    tot = sum(p["mix"].get(c, 0) for c in CANALES) or 1
    p["mix"] = {c: p["mix"].get(c, 0) / tot for c in CANALES}
    p["_alertas"] = alertas
    return p, sup, falta


def similar(sku: str) -> dict | None:
    """Ventas reales de un SKU nuestro parecido (corrida del ROI): velocidad, precio, mix, descuento y % de marketplace."""
    import pandas as pd
    f = _dato("productos_roi.parquet", AQUI.parent / "data/roi/roi_sku.parquet")
    if not f.exists():
        return None
    s = pd.read_parquet(f)
    if sku not in s.index:
        return None
    r = s.loc[sku]
    v = float(r.venta) if r.venta > 0 else 0
    mix = {"mkp": r.venta_mkp / v, "web": r.venta_web / v, "fid": r.venta_fid / v, "b2b": r.venta_b2b / v} if v else None
    ok = lambda x: float(x) if x == x and 0 < x < 0.5 else None
    pvp = float(r.pvp_mkp) if r.pvp_mkp > 0 else None
    return {"producto": str(r.producto), "vel": float(r.unidades) / 12 if r.unidades > 0 else None, "pvp": pvp, "mix": mix,
            "cat": str(r.categoria_macro), "desc": (1 - float(r.precio_real) / (pvp / 1.19)) if pvp and r.precio_real > 0 else None,
            "com": ok(r.com_pct), "log": ok(r.log_pct), "uds_caja": float(r.uds_caja) if r.uds_caja == r.uds_caja and r.uds_caja > 0 else None,
            "m3_u": float(r.m3_unit) if r.m3_unit == r.m3_unit and r.m3_unit > 0 else None}


# ── 1) costo internado (mismo cálculo que el precosteo COMEX) ───────────────
def importacion(p: dict, par: dict, tc: float | None = None, flete_mult: float = 1.0, precio_usd: float | None = None) -> dict:
    tc = tc or par["tc"]
    pu = p["precio_usd"] if precio_usd is None else precio_usd
    q = p["qty"]
    ctn = math.ceil(q / p["uds_ctn"])
    cbm = ctn * p["cbm_ctn"]
    cap = par["capacidad_40hq_m3"]
    if p["modalidad"] == "LCL":
        frac, n_cont = 0.0, 0
        flete = (p.get("flete_lcl_m3") or 0) * cbm * flete_mult
        local, ff, gastos = 0.0, par["form_f"], par["gastos_chile_lcl"]
    else:
        n_cont = math.ceil(cbm / cap) if p["modalidad"] == "Contenedor propio" else 0
        frac = n_cont if p["modalidad"] == "Contenedor propio" else cbm / cap
        flete = p["flete_contenedor_usd"] * frac * flete_mult
        local = par["local_charge_contenedor"] * frac
        ff = par["form_f"] * frac
        gastos = par["gastos_chile_contenedor"] * frac
    if str(p["incoterm"]).upper() == "FOB":
        local = 0.0                                   # el FOB ya trae los gastos hasta el puerto
    pxq = q * pu
    com = par["comision_steven"] * (pxq + local) if p["via_steven"] else 0.0
    china = com + local + ff
    seguro = p["seguro_pct"] * (pxq + china)
    cif = pxq + china + flete + seguro
    arancel = p["arancel_pct"] * cif
    agente = par["agente_aduana_pct"] * cif
    internado = (cif + arancel + agente) * tc + gastos
    return {"tc": tc, "cajas": ctn, "cbm": cbm, "fraccion_40hq": frac, "contenedores": n_cont, "pxq_usd": pxq,
            "comision_steven_usd": com, "local_charge_usd": local, "form_f_usd": ff, "inland_china_usd": china,
            "fob_china_usd": pxq + china, "flete_usd": flete, "seguro_usd": seguro, "cif_usd": cif, "arancel_usd": arancel,
            "agente_usd": agente, "gastos_chile_clp": gastos, "internado_clp": internado, "costo_u": internado / q,
            "costo_u_usd": internado / q / tc, "iva_import_clp": par["iva"] * (cif + arancel) * tc,
            "sobrecosto_pct": internado / (pxq * tc) - 1 if pxq else 0, "m3_u": p["cbm_ctn"] / p["uds_ctn"]}


# ── 2) venta y costos de venta/operación por unidad (tasas del ROI) ─────────
def canales(p: dict, par: dict, precio_mult: float = 1.0, sin_descuento: bool = False) -> dict:
    lista = p["pvp_iva"] / (1 + par["iva"])
    base = lista * (1 - (0 if sin_descuento else p["descuento"])) * precio_mult
    upp, ff = par["uds_por_pedido"], par["fulfillment_share_mkp"]
    manip_caja = par["manipulacion_u"] * par["peso_b2b_manip"] * par["uds_caja_prom_b2b"] / p["uds_ctn"]
    ins_ped = par["insumos_pedido"] / upp
    pv = p["dev_pct"] * par["postventa_u_devuelta"]
    tasas = {c: (p[f"com_{c}"], p[f"log_{c}"]) for c in CANALES}
    det = {}
    for c in CANALES:
        precio = base * (p["factor_precio_b2b"] if c == "b2b" else 1)
        com, log = tasas[c]
        mkt = 0.0 if c == "b2b" else p["marketing_pct"]
        manip = ((1 - ff) * par["manipulacion_u"] + ff * manip_caja) if c == "mkp" else (manip_caja if c == "b2b" else par["manipulacion_u"])
        ins = (1 - ff) * ins_ped if c == "mkp" else (0.0 if c == "b2b" else ins_ped)
        det[c] = {"mix": p["mix"][c], "precio": precio, "com": com, "log": log, "mkt": mkt,
                  "canal_u": precio * (com + log + mkt), "manip_u": manip, "insumos_u": ins,
                  "postventa_u": 0.0 if c == "b2b" else pv}
    w = lambda k: sum(det[c]["mix"] * det[c][k] for c in CANALES)
    return {"lista_neta": lista, "precio_base": base, "detalle": det, "precio_prom": w("precio"), "canal_u": w("canal_u"),
            "manip_u": w("manip_u"), "insumos_u": w("insumos_u"), "postventa_u": w("postventa_u")}


# ── 3) año tipo: contribución, capital, EVA (fórmulas de roi_producto.metricas) ─
def anual(p: dict, par: dict, esc: dict, flete_mult: float = 1.0, precio_usd: float | None = None) -> dict:
    tc = par["tc"] * esc.get("tc", 1)
    imp = importacion(p, par, tc, flete_mult, precio_usd)
    ch = canales(p, par, esc.get("precio", 1), esc.get("sin_descuento", False))
    pu = p["precio_usd"] if precio_usd is None else precio_usd
    vel = p["velocidad_mes"] * esc.get("vel", 1)
    u = vel * 12
    v = u * ch["precio_prom"]
    costo = u * imp["costo_u"]
    canal, manip, ins, pv = (u * ch[k] for k in ("canal_u", "manip_u", "insumos_u", "postventa_u"))
    stock = par["inventario_prom_factor"] * p["qty"]
    almac = stock * imp["m3_u"] * par["almacenaje_m3_anio"]
    contrib = v - costo - canal - manip - ins - pv - almac
    costo_d = costo / 365
    fob_d = min(u * pu * tc / 365, costo_d)
    tr = par["transito_dias"].get(p["puerto"], par["transito_dias"]["Otro"])
    k_ant = p["anticipo_pct"] * fob_d * p["lt_produccion"]
    k_tr = (1.0 if p["saldo_en"] == "Origen" else p["anticipo_pct"]) * fob_d * tr + fob_d * par["aduana_dias"]
    k_bod = stock * imp["costo_u"]
    credito = max(costo_d - fob_d, 0) * max(0, par["credito_flete_dias"] - par["aduana_dias"])
    k_cxc = v / 365 * par["dias_cobro"]
    capital = max(k_ant + k_tr + k_bod + k_cxc - credito, 0)
    eva = contrib - par["tasa_capital"] * capital
    return {"tc": tc, "velocidad_mes": vel, "unidades": u, "precio_prom": ch["precio_prom"], "costo_u": imp["costo_u"],
            "venta": v, "costo": costo, "margen_bruto": v - costo, "comision_log_mkt": canal, "manipulacion": manip,
            "insumos": ins, "postventa": pv, "almacenaje": almac, "contribucion": contrib,
            "contrib_pct": contrib / v if v else 0, "contrib_u": contrib / u if u else 0,
            "k_anticipo": k_ant, "k_transito": k_tr, "k_bodega": k_bod, "k_cxc": k_cxc, "credito": credito,
            "capital": capital, "costo_capital": par["tasa_capital"] * capital, "eva": eva,
            "roi": contrib / capital if capital else None, "gmroi": (v - costo) / k_bod if k_bod else None,
            "rotacion": costo / k_bod if k_bod else None, "markup": ch["precio_prom"] / imp["costo_u"] if imp["costo_u"] else None,
            "transito_dias": tr}


# ── 4) flujo de caja del lote, mes a mes ────────────────────────────────────
def flujo_lote(p: dict, par: dict, esc: dict, max_meses: int = 60) -> dict:
    tc = par["tc"] * esc.get("tc", 1)
    imp = importacion(p, par, tc)
    ch = canales(p, par, esc.get("precio", 1), esc.get("sin_descuento", False))
    vel = p["velocidad_mes"] * esc.get("vel", 1)
    tr = par["transito_dias"].get(p["puerto"], par["transito_dias"]["Otro"])
    m_emb = redondear(p["lt_produccion"] / 30)
    m_lleg = redondear((p["lt_produccion"] + tr) / 30)
    m_disp = redondear((p["lt_produccion"] + tr + par["aduana_dias"]) / 30)
    lag = redondear(par["dias_cobro"] / 30)
    m_cred = m_lleg + redondear(par["credito_flete_dias"] / 30)
    n = max_meses + lag + 2
    filas = {k: [0.0] * n for k in ("fabrica", "china", "flete_aduana_chile", "iva", "cobros", "costos_venta", "almacenaje")}
    pxq = imp["pxq_usd"] * tc
    filas["fabrica"][0] -= p["anticipo_pct"] * pxq
    filas["fabrica"][m_emb if p["saldo_en"] == "Origen" else m_lleg] -= (1 - p["anticipo_pct"]) * pxq
    filas["china"][m_emb] -= imp["inland_china_usd"] * tc
    filas["flete_aduana_chile"][m_lleg] -= imp["arancel_usd"] * tc
    filas["flete_aduana_chile"][m_cred] -= (imp["flete_usd"] + imp["seguro_usd"] + imp["agente_usd"]) * tc + imp["gastos_chile_clp"]
    filas["iva"][m_lleg] -= imp["iva_import_clp"]
    filas["iva"][m_lleg + par["iva_recupero_meses"]] += imp["iva_import_clp"]
    stock, vendidas, m, ult = float(p["qty"]), [0.0] * n, m_disp, 0
    neto_u = ch["precio_prom"] - ch["canal_u"]
    oper_u = ch["manip_u"] + ch["insumos_u"] + ch["postventa_u"]
    while stock > 1e-9 and m <= max_meses:
        filas["almacenaje"][m] -= stock * imp["m3_u"] * par["almacenaje_m3_anio"] / 12
        u = min(vel, stock)
        stock -= u
        vendidas[m] = u
        filas["costos_venta"][m] -= u * oper_u
        filas["cobros"][m + lag] += u * neto_u
        ult = m + lag
        m += 1
    neto = [sum(filas[k][i] for k in filas) for i in range(n)]
    acum, s = [], 0.0
    for x in neto:
        s += x
        acum.append(s)
    fin = max(ult, m_lleg + par["iva_recupero_meses"], m_cred)
    neto, acum = neto[:fin + 1], acum[:fin + 1]
    payback = next((i for i in range(1, len(acum)) if acum[i] >= 0 and min(acum[:i]) < 0), None)
    utilidad = acum[-1]
    inv = imp["internado_clp"]
    roi_lote = utilidad / inv if inv else 0
    ciclo = len(acum)
    vend = sum(vendidas)
    mb = vend * ch["precio_prom"] - vend * imp["costo_u"]
    return {"meses": {"embarque": m_emb, "llegada": m_lleg, "disponible": m_disp, "ultimo_cobro": ult},
            "filas": {k: v[:fin + 1] for k, v in filas.items()}, "unidades_vendidas": vendidas[:fin + 1],
            "neto": neto, "acumulado": acum, "utilidad": utilidad, "inversion": inv, "roi_lote": roi_lote,
            "roi_anualizado": (1 + roi_lote) ** (12 / ciclo) - 1 if roi_lote > -1 and ciclo else None,
            "ciclo_meses": ciclo, "payback_mes": payback, "exposicion_max": min(acum), "stock_sin_vender": stock,
            "dias_inventario": p["qty"] / vel * 30 if vel else None, "gmroi_lote": mb / (inv / 2) if inv else None,
            "caja_necesaria": -min(acum)}


# ── 5) sensibilidad, FOB objetivo y veredicto ───────────────────────────────
def escenarios(par: dict, guerra: bool = False) -> dict:
    e = copy.deepcopy(par["escenarios"])
    if guerra:
        e["conservador"]["precio"] = 0.85
    return e


def sensibilidad(p: dict, par: dict) -> list:
    casos = [("Base", {}, 1), ("Dólar +10%", {"tc": 1.1}, 1), ("Dólar −10%", {"tc": 0.9}, 1), ("Flete +30%", {}, 1.3),
             ("Flete −30%", {}, 0.7), ("Precio de venta −10%", {"precio": 0.9}, 1),
             ("Pesimista (dólar +10%, flete +30%, precio −10%)", {"tc": 1.1, "precio": 0.9}, 1.3)]
    out = []
    for nombre, esc, fm in casos:
        a = anual(p, par, esc, fm)
        out.append({"caso": nombre, "costo_u": a["costo_u"], "precio_prom": a["precio_prom"], "contrib_u": a["contrib_u"],
                    "contrib_pct": a["contrib_pct"], "eva": a["eva"]})
    return out


def fob_objetivo(p: dict, par: dict, esc: dict, bench: float, techo: float | None = None) -> float | None:
    """Precio de compra máximo (USD/u, mismo incoterm) con EVA conservador ≥ 0 y contribución base ≥ la de la categoría."""
    ok = lambda x: (anual(p, par, esc["conservador"], precio_usd=x)["eva"] >= 0
                    and anual(p, par, esc["base"], precio_usd=x)["contrib_pct"] >= bench)
    if not ok(0.0):
        return None
    lo, hi = 0.0, max(p["precio_usd"] * 3, 1.0)
    if ok(hi):
        return hi if techo is None else min(hi, techo)
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo if techo is None else min(lo, techo)


def lotes(p: dict, par: dict, esc: dict, moq: float | None = None) -> dict:
    """Unidades a comprar (Andrés 11-oct: mejor ROI anualizado). Opciones: meses de venta {reposición, 3, 6, 9, 12} y el MOQ,
    en cajas completas. Se recomienda el de mejor ROI anualizado del lote entre los que cubren el tiempo de reposición
    (producción + tránsito + aduana) y el MOQ; la tabla completa queda para decidir."""
    vel = p["velocidad_mes"]
    tr = par["transito_dias"].get(p["puerto"], par["transito_dias"]["Otro"])
    repos = (p["lt_produccion"] + tr + par["aduana_dias"]) / 30
    if not vel:
        return {"opciones": [], "recomendado": None, "reposicion_meses": repos}
    cand = sorted({math.ceil(repos), 3, 6, 9, 12})
    qs = {max(p["uds_ctn"], math.ceil(vel * m / p["uds_ctn"]) * p["uds_ctn"]) for m in cand}
    if moq:
        qs.add(math.ceil(moq / p["uds_ctn"]) * p["uds_ctn"])
    filas = []
    for q in sorted(qs):
        p2 = dict(p, qty=q)
        lo = flujo_lote(p2, par, esc["base"])
        an = anual(p2, par, esc["base"])
        filas.append({"unidades": q, "meses_venta": q / vel, "costo_u": an["costo_u"], "inversion": lo["inversion"],
                      "roi_lote": lo["roi_lote"], "roi_anualizado": lo["roi_anualizado"], "eva_anual": an["eva"],
                      "caja_maxima": lo["caja_necesaria"], "payback_mes": lo["payback_mes"], "sin_vender": lo["stock_sin_vender"],
                      "cubre_reposicion": q / vel >= repos - 1e-9, "cumple_moq": (not moq) or q >= moq})
    ok = [f for f in filas if f["cubre_reposicion"] and f["cumple_moq"] and f["roi_anualizado"] is not None]
    rec = max(ok, key=lambda f: f["roi_anualizado"]) if ok else None
    return {"opciones": filas, "recomendado": rec, "reposicion_meses": repos, "moq": moq}


def pvp_objetivo(p: dict, par: dict, esc: dict, bench: float) -> float | None:
    """Precio de lista mínimo (con IVA) para que, con este costo, pague su capital en el conservador y alcance la
    contribución de su categoría (misma meta que el veredicto)."""
    ok = lambda x: (anual(dict(p, pvp_iva=x), par, esc["conservador"])["eva"] >= 0
                    and anual(dict(p, pvp_iva=x), par, esc["base"])["contrib_pct"] >= bench)
    lo, hi = 0.0, importacion(p, par)["costo_u"] * (1 + par["iva"]) * 20
    if not ok(hi):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if ok(mid) else (mid, hi)
    return hi


def evaluar(prod: dict, par: dict | None = None, radar: dict | None = None) -> dict:
    """Tres modos (Andrés 9-oct: 'con ese costo, este PVP es el ideal; con ese PVP, este es el costo ideal'):
      · completo        → hay costo de compra y PVP: veredicto + PVP ideal y costo máximo como referencia
      · precio_objetivo → solo costo (cotización o FOB de la competencia): PVP ideal y evaluación a ese precio
      · costo_objetivo  → solo PVP objetivo: costo máximo de compra y evaluación a ese costo."""
    par = par or cargar_parametros()
    p, sup, falta = completar(prod, par)
    if falta:
        return {"estado": "FALTAN DATOS", "faltan": falta, "producto": p, "supuestos": sup}
    bench = par["categorias"][p["categoria_ref"]]["contrib_pct"]
    modo = "completo" if p.get("precio_usd") and p.get("pvp_iva") else ("precio_objetivo" if p.get("precio_usd") else "costo_objetivo")
    guerra = bool(radar and radar.get("max_unidades_competidor_anual", 0) >= par["guerra_precios_factor"] * p["velocidad_mes"] * 12)
    esc = escenarios(par, guerra)
    if modo == "precio_objetivo":
        pv = pvp_objetivo(p, par, esc, bench)
        if pv is None:
            return {"estado": "NO VIABLE", "faltan": [], "producto": p, "supuestos": sup,
                    "razon": "con este costo no hay precio que pague el capital (revisar velocidad o lote)"}
        p["pvp_iva"] = round(pv)
        sup.append(f"precio de lista = PVP ideal calculado ({p['pvp_iva']:,.0f})".replace(",", "."))
    elif modo == "costo_objetivo":
        p["precio_usd"] = p["pvp_iva"] / (1 + par["iva"]) / par["tc"]          # solo para acotar la búsqueda
        fo = fob_objetivo(p, par, esc, bench)
        if not fo:
            return {"estado": "NO VIABLE", "faltan": [], "producto": p, "supuestos": sup,
                    "razon": "a este precio de venta no hay costo de compra que pague el capital"}
        p["precio_usd"] = round(fo, 2)
        sup.append(f"precio de compra = costo máximo calculado (US${p['precio_usd']:.2f})")
    imp = importacion(p, par)
    ch = canales(p, par)
    res_anual = {k: anual(p, par, v) for k, v in esc.items()}
    res_lote = {k: flujo_lote(p, par, v) for k, v in esc.items()}
    sens = sensibilidad(p, par)
    nuestro_fob_u = imp["fob_china_usd"] / p["qty"]
    techo, bloqueo = None, False
    alerta_competencia = None
    if radar and radar.get("disponible") and radar.get("fob_referencia_u"):
        ref = radar["fob_referencia_u"]
        sobre = nuestro_fob_u / ref - 1
        if sobre > par["umbral_competencia"] and radar.get("fob_referencia_conf") != "ALTA":
            alerta_competencia = (f"nuestro FOB queda {sobre:.0%} sobre el promedio de los competidores con productos de precio "
                                  f"comparable (referencia MEDIA: no es el mismo producto)")
        if sobre > par["umbral_competencia"] and radar.get("fob_referencia_conf") == "ALTA":
            bloqueo = True
            # FOB China de referencia → precio de compra equivalente (descontando el inland China por unidad)
            techo = max(ref - (imp["inland_china_usd"] - imp["comision_steven_usd"]) / p["qty"], 0) / (1 + par["comision_steven"] * p["via_steven"])
    fob_obj = fob_objetivo(p, par, esc, bench, techo)
    pvp_ideal = pvp_objetivo(p, par, esc, bench)
    # lote sugerido: si el lote dura más de 12 meses, uno de 6 meses de venta base (en cajas completas)
    lote_sug = None
    if p["velocidad_mes"] and p["qty"] / p["velocidad_mes"] > 12:
        q2 = max(p["uds_ctn"], math.ceil(p["velocidad_mes"] * 6 / p["uds_ctn"]) * p["uds_ctn"])
        p2 = dict(p, qty=q2)
        a2 = {k: anual(p2, par, v) for k, v in esc.items()}
        lote_sug = {"qty": q2, "meses": q2 / p["velocidad_mes"], "costo_u": a2["base"]["costo_u"], "contrib_pct": a2["base"]["contrib_pct"],
                    "eva_base": a2["base"]["eva"], "eva_conservador": a2["conservador"]["eva"],
                    "fob_objetivo": fob_objetivo(p2, par, esc, bench, techo)}
    b, c = res_anual["base"], res_anual["conservador"]
    if b["contribucion"] <= 0:
        ver, razon = "NO COMPRAR", "la contribución es negativa: destruye valor"
    elif b["eva"] <= 0:
        ver, razon = "NO COMPRAR", "no paga su capital (EVA base negativo con costo de capital 9%)"
    elif c["eva"] > 0 and b["contrib_pct"] >= bench and not bloqueo and radar and radar.get("disponible"):
        ver, razon = "COMPRAR", f"paga su capital aun en el escenario conservador y su contribución ({b['contrib_pct']:.1%}) supera la de su categoría ({bench:.1%})"
    else:
        motivos = []
        if c["eva"] <= 0:
            motivos.append("en el escenario conservador no paga su capital")
        if b["contrib_pct"] < bench:
            motivos.append(f"contribución {b['contrib_pct']:.1%} bajo la de su categoría ({bench:.1%})")
        if bloqueo:
            motivos.append("la competencia compra más barato")
        if not (radar and radar.get("disponible")):
            motivos.append("cruce con el radar pendiente")
        ver, razon = "NEGOCIAR", "; ".join(motivos) or "revisar"
    if any("velocidad de venta es un supuesto" in x for x in p["_alertas"]) and ver == "COMPRAR":
        ver, razon = "NEGOCIAR", razon + "; pero la velocidad de venta es supuesta: confirmarla antes de comprar"
    ver_std = ver
    clp = lambda x: f"${x:,.0f}".replace(",", ".")
    usd = lambda x: f"US${x:.2f}".replace(".", ",")
    if modo == "precio_objetivo":
        ver = "PRECIO OBJETIVO"
        razon = (f"comprando a {usd(p['precio_usd'])} {p['incoterm']}, el precio de lista mínimo es {clp(p['pvp_iva'])} con IVA: "
                 "conviene si el mercado lo paga")
    elif modo == "costo_objetivo":
        ver = "COSTO OBJETIVO"
        razon = f"vendiendo a {clp(p['pvp_iva'])} con IVA, se puede pagar hasta {usd(p['precio_usd'])} {p['incoterm']}"
        ref = (radar or {}).get("fob_referencia_u")
        if ref:
            razon += (f"; la competencia compra el mismo producto a ~{usd(ref)} FOB" if radar.get("fob_referencia_conf") == "ALTA"
                      else f"; productos comparables de la competencia: ~{usd(ref)} FOB")
        if fob_obj is not None and fob_obj < p["precio_usd"] - 0.005:
            razon += f": para no quedar sobre ella, apuntar a {usd(fob_obj)} {p['incoterm']}"
    lts = lotes(p, par, esc, p.get("moq"))
    return {"estado": "OK", "modo": modo, "lotes": lts, "pvp_ideal": pvp_ideal, "veredicto_a_estos_precios": ver_std, "veredicto": ver, "razon": razon, "alertas": p["_alertas"], "fob_objetivo_usd": fob_obj, "producto": p, "supuestos": sup,
            "benchmark_contrib_pct": bench, "guerra_precios": guerra, "bloqueo_competencia": bloqueo, "lote_sugerido": lote_sug, "alerta_competencia": alerta_competencia,
            "importacion": imp, "canales": ch, "anual": res_anual, "lote": res_lote, "sensibilidad": sens,
            "nuestro_fob_china_u": nuestro_fob_u, "radar": radar or {"disponible": False}}


def buscar_similares(texto: str, limite: int = 25):
    """SKU nuestros parecidos (ventas reales 12m, corrida del ROI) para usar como referencia de velocidad, precio y mix."""
    import re as _re
    import pandas as pd
    f = _dato("productos_roi.parquet", AQUI.parent / "data/roi/roi_sku.parquet")
    if not f.exists() or not texto.strip():
        return pd.DataFrame()
    s = pd.read_parquet(f)
    import unicodedata
    sin_tilde = lambda x: "".join(ch for ch in unicodedata.normalize("NFKD", str(x)) if not unicodedata.combining(ch)).upper()
    txt = (s.index.astype(str) + " " + s["producto"].astype(str) + " " + s["marca"].astype(str) + " " + s["categoria_padre"].astype(str)).map(sin_tilde)
    ok = pd.Series(True, index=s.index)
    for w in _re.split(r"\s+", sin_tilde(texto.strip())):
        ok &= txt.str.contains(_re.escape(w), regex=True)
    x = s[ok & (s["unidades"] > 0)].copy()
    x["u_mes"] = x["unidades"] / 12
    out = x[["producto", "marca", "categoria_macro", "u_mes", "precio_real", "pvp_mkp", "contrib_pct", "m3_unit", "uds_caja"]]
    return out.sort_values("u_mes", ascending=False).head(limite).reset_index(names="sku")
