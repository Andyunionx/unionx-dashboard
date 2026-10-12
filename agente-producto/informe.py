"""Informe del Agente Producto: el formato que pidió Seba (veredicto → datos → costos → canales → sensibilidad → ROI →
radar → riesgos → recomendaciones → JSON para otros agentes). Corto y directo: el objetivo es decidir la compra."""
from __future__ import annotations

import json

from motor import CANAL_TXT, CANALES


def _clp(x):
    return "—" if x is None else f"${x:,.0f}".replace(",", ".")


def _usd(x, d=2):
    return "—" if x is None else f"US${x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x, d=1):
    return "—" if x is None else f"{x * 100:.{d}f}%".replace(".", ",")


def _x(x):
    return "—" if x is None else f"{x:.2f}x".replace(".", ",")


def tabla(cab, filas):
    return "\n".join(["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)] + ["| " + " | ".join(str(c) for c in f) + " |" for f in filas])


def markdown(r: dict) -> str:
    if r["estado"] == "NO VIABLE":
        return "## NO VIABLE\n\n" + r["razon"][0].upper() + r["razon"][1:] + "."
    if r["estado"] != "OK":
        return ("**Faltan datos para evaluar:** " + ", ".join(r["faltan"]) + "\n\nCon esos datos corro la evaluación completa.")
    p, imp, ch, an, lo, rad = r["producto"], r["importacion"], r["canales"], r["anual"], r["lote"], r["radar"]
    b, c, o = an["base"], an["conservador"], an["optimista"]
    q = p["qty"]
    out = [f"## {r['veredicto']} — {p.get('nombre', 'Producto')}", f"**{r['razon'][0].upper() + r['razon'][1:]}.**"]
    out.append(tabla(["Con este costo…", "…el PVP ideal es", "Con este PVP…", "…el costo máximo es"],
                     [(f"{_usd(p['precio_usd'])} {p['incoterm']}", f"{_clp(r.get('pvp_ideal'))} con IVA",
                       f"{_clp(p['pvp_iva'])} con IVA", f"{_usd(r['fob_objetivo_usd'])} {p['incoterm']}")]))
    out.append("Meta: pagar su capital (9%) en el escenario conservador y alcanzar la contribución de su categoría "
               f"({_pct(r['benchmark_contrib_pct'])}). Veredicto a estos precios: **{r['veredicto_a_estos_precios']}**.")
    # 2) datos de entrada
    sup = set(r["supuestos"])
    filas = [("Producto", p.get("nombre", "—")), ("Fábrica", p.get("fabrica", "—")), ("Precio de compra", f"{_usd(p['precio_usd'])} {p['incoterm']}"),
             ("Unidades del lote", f"{q:,.0f}".replace(",", ".")), ("Caja master", f"{p['uds_ctn']} u · {p['cbm_ctn']} m³"),
             ("Puerto / modalidad", f"{p['puerto']} · {p['modalidad']}"), ("Precio de venta (lista, con IVA)", _clp(p["pvp_iva"])),
             ("Descuento promedio", _pct(p["descuento"])), ("Velocidad de venta", f"{p['velocidad_mes']:,.0f} u/mes".replace(",", ".")),
             ("Mix", " · ".join(f"{CANAL_TXT[k]} {_pct(v, 0)}" for k, v in p["mix"].items() if v)),
             ("Pago a fábrica", f"{_pct(p['anticipo_pct'], 0)} anticipo, saldo en {p['saldo_en'].lower()}"),
             ("Producción", f"{p['lt_produccion']} días"), ("Dólar", _clp(imp["tc"]))]
    out += ["### Datos de entrada", tabla(["Dato", "Valor"], filas),
            "**Supuestos usados:** " + ("; ".join(r["supuestos"]) if r["supuestos"] else "ninguno") + "."]
    # 3) cascada
    cas = [("Fábrica (P×Q)", imp["pxq_usd"]), ("3% Steven", imp["comision_steven_usd"]), ("Local charge + Form F", imp["local_charge_usd"] + imp["form_f_usd"]),
           ("Flete", imp["flete_usd"]), ("Seguro", imp["seguro_usd"]), ("**CIF**", imp["cif_usd"]), ("Arancel", imp["arancel_usd"]),
           ("Agente de aduana", imp["agente_usd"]), ("Gastos Chile (puerto, transporte, desconsolidación)", imp["gastos_chile_clp"] / imp["tc"])]
    out += ["### Costo internado", tabla(["Concepto", "Lote", "Por unidad"],
                                         [(n, _usd(v, 0), _usd(v / q)) for n, v in cas]
                                         + [("**Costo internado**", _clp(imp["internado_clp"]), f"**{_clp(imp['costo_u'])}** ({_usd(imp['costo_u_usd'])})")]),
            f"{imp['cajas']} cajas · {imp['cbm']:.1f} m³ ({_pct(imp['cbm'] / 68, 0)} de un 40HQ) · sobrecosto {_pct(imp['sobrecosto_pct'])} · "
            f"IVA de importación {_clp(imp['iva_import_clp'])} (crédito fiscal: no es costo, sí caja)."]
    # 4) canales
    filas = []
    for k in CANALES:
        d = ch["detalle"][k]
        if not d["mix"]:
            continue
        cu = d["precio"] - imp["costo_u"] - d["canal_u"] - d["manip_u"] - d["insumos_u"] - d["postventa_u"] - b["almacenaje"] / b["unidades"]
        filas.append((CANAL_TXT[k], _pct(d["mix"], 0), _clp(d["precio"]), _pct(d["com"] + d["log"]), _pct(d["mkt"], 0),
                      _clp(d["manip_u"] + d["insumos_u"] + d["postventa_u"]), _clp(cu), _pct(cu / d["precio"] if d["precio"] else None)))
    out += ["### Márgenes por canal (precio neto, sin IVA)", tabla(["Canal", "Mix", "Precio neto", "Comisión + envío", "Marketing",
                                                                   "Operación/u", "Contribución/u", "%"], filas),
            f"Promedio: contribución {_clp(b['contrib_u'])}/u ({_pct(b['contrib_pct'])}) · markup {_x(b['markup'])} · "
            f"referencia de su categoría ({p['categoria_ref']}): {_pct(r['benchmark_contrib_pct'])}."]
    # 5) sensibilidad
    out += ["### Sensibilidad por unidad", tabla(["Caso", "Costo internado", "Contribución/u", "%"],
                                                 [(s["caso"], _clp(s["costo_u"]), _clp(s["contrib_u"]), _pct(s["contrib_pct"])) for s in r["sensibilidad"]])]
    # 6) ROI
    filas = []
    for nom, k in (("Conservador", "conservador"), ("Base", "base"), ("Optimista", "optimista")):
        a, l = an[k], lo[k]
        filas.append((nom, f"{a['velocidad_mes']:,.0f}".replace(",", "."), _clp(a["contribucion"]), _clp(a["capital"]), _x(a["roi"]),
                      _clp(a["eva"]), _pct(l["roi_lote"]), _pct(l["roi_anualizado"]), f"mes {l['payback_mes']}" if l["payback_mes"] is not None else "no recupera",
                      _clp(-l["exposicion_max"])))
    lb = lo["base"]
    out += ["### ROI proyectado", tabla(["Escenario", "u/mes", "Contribución anual", "Capital", "ROI s/capital", "EVA (9%)", "ROI lote",
                                         "ROI anualizado", "Payback", "Caja máxima"], filas),
            f"Base: el lote se vende en {str(round(lb['dias_inventario'] / 30, 1)).replace('.', ',')} meses · ciclo completo {lb['ciclo_meses']} meses (desde el anticipo hasta el último cobro) · "
            f"GMROI {_x(lb['gmroi_lote'])} · rotación {_x(b['rotacion'])}/año."]
    if c["eva"] <= 0:
        out.append(f"⚠️ En el escenario conservador el EVA es negativo: el producto no paga el costo de capital (9%).")
    for nom, k in (("conservador", "conservador"), ("base", "base")):
        if lo[k]["stock_sin_vender"] > 0:
            out.append(f"⚠️ Escenario {nom}: a los 5 años quedan {lo[k]['stock_sin_vender']:,.0f} unidades sin vender "
                       "(el ROI del lote las cuenta como pérdida).".replace(",", "."))
    # unidades a comprar
    lt_ = r.get("lotes") or {}
    if lt_.get("opciones"):
        rec = lt_.get("recomendado") or {}
        out += ["### Unidades a comprar", tabla(["Unidades", "Meses de venta", "Costo internado/u", "Inversión", "ROI lote", "ROI anualizado",
                                                  "EVA anual", "Caja máxima", "Payback"],
                [(("**" if f is rec else "") + f"{f['unidades']:,.0f}".replace(",", ".") + ("**" if f is rec else ""), f"{f['meses_venta']:.1f}".replace(".", ","),
                  _clp(f["costo_u"]), _clp(f["inversion"]), _pct(f["roi_lote"]), _pct(f["roi_anualizado"]), _clp(f["eva_anual"]),
                  _clp(f["caja_maxima"]), f"mes {f['payback_mes']}" if f["payback_mes"] is not None else "no recupera")
                 for f in lt_["opciones"]]),
                (f"Recomendado: **{rec['unidades']:,.0f} unidades**".replace(",", ".") + f" (mejor ROI anualizado entre los lotes que cubren la "
                 f"reposición de {lt_['reposicion_meses']:.1f} meses".replace(".", ",") + (f" y el MOQ de {lt_['moq']:,.0f}".replace(",", ".") if lt_.get("moq") else "") + ").")
                if rec else "Ningún lote cubre la reposición y el MOQ a esta velocidad."]
    # 7) radar
    out.append("### Cruce con el radar de importaciones")
    if not rad.get("disponible"):
        out.append(f"[PENDIENTE] {rad.get('motivo', 'radar no disponible')}. Sin el cruce no corresponde un COMPRAR.")
    elif rad.get("sin_coincidencias"):
        out.append("Sin importaciones de la competencia en ese tipo/partida en 12 meses: puede ser un producto no explotado o de poca demanda.")
    else:
        if rad.get("supuesto_partida"):
            out.append(f"[SUPUESTO] {rad['supuesto_partida']}.")
        pq = rad["precios_tipo"]
        out.append(f"Tipo **{rad['tipo']}** ({rad['desde']} a {rad['hasta']}): FOB/u p25 {_usd(pq.get(0.25))} · mediana {_usd(pq.get(0.5))} · "
                   f"p75 {_usd(pq.get(0.75))}. Nuestro FOB China {_usd(r['nuestro_fob_china_u'])} queda sobre el {_pct(rad['percentil_nuestro_fob'], 0)} del mercado.")
        filas = [(x["importador"][:34], x["nivel"], f"{x['unidades_12m']:,.0f}".replace(",", "."), x["din_12m"], _usd(x["fob_u_prom"]),
                  ("+" if (x["dif_fob_pct"] or 0) > 0 else "") + _pct(x["dif_fob_pct"], 0), _clp(x["internado_u_estimado_clp"]), x["tendencia"], ", ".join(map(str, x["fabricas"][:2])) or "—")
                 for x in rad["competidores"][:8]]
        out += [f"Competidores con productos de precio comparable ({_usd(rad['banda'][0])}–{_usd(rad['banda'][1])}/u):",
                tabla(["Importador", "Evidencia", "Unidades 12m", "DIN", "FOB/u", "Nuestro FOB vs ellos", "Internado/u (estimado)", "Tendencia", "Fábricas"], filas)]
        if rad.get("palabras_genericas"):
            out.append(f"Las palabras clave aparecen en el {_pct(rad['share_palabras'], 0)} de las líneas del tipo: son genéricas, "
                       "no identifican el mismo producto (sus coincidencias quedan en confianza MEDIA). Para un cruce exacto usar modelo, "
                       "capacidad o número de piezas.")
        alta = [x for x in rad["coincidencias"] if x["confianza"] == "ALTA"]
        if alta:
            out += ["Coincidencias del mismo producto (confianza ALTA):",
                    tabla(["Mes", "Importador", "Glosa", "Unidades", "FOB/u"],
                          [(x["mes"], x["importador"][:28], x["glosa"][:40], f"{x['unidades']:,.0f}".replace(",", "."), _usd(x["fob_u"])) for x in alta[:6]])]
        out.append(f"Referencia de la competencia: {_usd(rad['fob_referencia_u'])}/u ({rad['fob_referencia_txt']}).")
        if rad["fabricas"]:
            out.append("Fábricas para cotizar (proveedores de la competencia en esa banda): "
                       + ", ".join(f"{f['proveedor']} ({f['unidades']:,.0f} u)".replace(",", ".") for f in rad["fabricas"][:6]) + ".")
        if rad.get("dejaron_de_comprar"):
            out.append("Dejaron de importar en la banda: " + ", ".join(d["importador"] for d in rad["dejaron_de_comprar"][:3]) + ".")
    # 8) riesgos
    riesgos = [x[0].upper() + x[1:] for x in r.get("alertas", [])]
    if rad.get("disponible") and not rad.get("sin_coincidencias"):
        riesgos.append(f"Contraste de demanda: la competencia trajo {rad['unidades_mercado_banda_12m']:,.0f} u en 12 meses en esa banda de precio; "
                       f"nosotros proyectamos {b['unidades']:,.0f} u/año".replace(",", "."))
    if r.get("alerta_competencia"):
        riesgos.append(r["alerta_competencia"][0].upper() + r["alerta_competencia"][1:])
    if r["guerra_precios"]:
        riesgos.append("Hay competidores que importan ≥ 5 veces nuestro volumen anual: riesgo de guerra de precios (el conservador usa precio −15%)")
    if lb["dias_inventario"] and round(lb["dias_inventario"]) > 180:
        riesgos.append(f"El lote dura {lb['dias_inventario'] / 30:.0f} meses a esta velocidad: MOQ alto para la rotación")
    if p["mix"].get("mkp", 0) >= 0.8:
        riesgos.append("Depende de un solo canal (marketplace)")
    peor = r["sensibilidad"][-1]
    if peor["contrib_u"] <= 0:
        riesgos.append("En el escenario pesimista la contribución por unidad es negativa")
    peso_vol = (imp["flete_usd"] * imp["tc"] / q + b["almacenaje"] / max(b["unidades"], 1)) / imp["costo_u"]
    if peso_vol > 0.10:
        riesgos.append(f"Producto voluminoso para su valor: flete y almacenaje son el {_pct(peso_vol, 0)} del costo internado")
    riesgos.append("Revisar si requiere certificación SEC, ISP o SAG según el tipo de producto")
    out += ["### Riesgos y alertas", "\n".join(f"- {x}." for x in riesgos)]
    # 9) recomendaciones
    rec = []
    if r["fob_objetivo_usd"] is not None:
        rec.append(f"Precio de compra máximo para pagar su capital en el conservador y alcanzar la contribución de la categoría: "
                   f"**{_usd(r['fob_objetivo_usd'])} {p['incoterm']}**")
    ls = r.get("lote_sugerido")
    if ls:
        rec.append(f"Lote más chico: {ls['qty']:,.0f} u".replace(",", ".") + f" (~{ls['meses']:.0f} meses de venta) → costo internado "
                   f"{_clp(ls['costo_u'])}/u, EVA base {_clp(ls['eva_base'])} y conservador {_clp(ls['eva_conservador'])}"
                   + (f"; precio de compra máximo {_usd(ls['fob_objetivo'])}" if ls.get("fob_objetivo") is not None else ""))
    if p["modalidad"] == "Contenedor propio" and imp["cbm"] < 0.7 * 68:
        rec.append(f"Usa {_pct(imp['cbm'] / 68, 0)} del contenedor: consolidarlo con otros productos baja el costo")
    # solo canales con peso real en el mix (≥ 10%); B2B queda fuera si su precio es el supuesto (= lista)
    cand = [k for k in CANALES if ch["detalle"][k]["mix"] >= 0.10 and not (k == "b2b" and p["factor_precio_b2b"] == 1.0)]
    mejor = max(cand, key=lambda k: (ch["detalle"][k]["precio"] - ch["detalle"][k]["canal_u"]) / ch["detalle"][k]["precio"], default=None)
    if mejor:
        rec.append(f"Canal con mejor margen unitario: {CANAL_TXT[mejor]}")
    if rad.get("disponible") and rad.get("fabricas"):
        rec.append("Pedir cotización a: " + ", ".join(str(f["proveedor"]) for f in rad["fabricas"][:3]))
    out += ["### Recomendaciones", "\n".join(f"- {x}." for x in rec)]
    return "\n\n".join(out)


def json_agentes(r: dict) -> dict:
    """Bloque JSON para otros agentes (campos mínimos del prompt de Seba)."""
    if r["estado"] != "OK":
        return {"estado": r["estado"], "faltan": r["faltan"]}
    p, imp, an, lo, rad = r["producto"], r["importacion"], r["anual"], r["lote"], r["radar"]
    return {
        "producto": p.get("nombre"), "partida_arancelaria": p.get("arancel") or (rad.get("arancel") if rad else None),
        "inputs": {k: p.get(k) for k in ("precio_usd", "incoterm", "qty", "uds_ctn", "cbm_ctn", "puerto", "modalidad", "pvp_iva",
                                         "descuento", "velocidad_mes", "mix", "anticipo_pct", "saldo_en", "lt_produccion")},
        "supuestos": r["supuestos"],
        "costos": {k: imp[k] for k in ("tc", "pxq_usd", "comision_steven_usd", "local_charge_usd", "form_f_usd", "flete_usd", "seguro_usd",
                                       "cif_usd", "arancel_usd", "agente_usd", "gastos_chile_clp", "internado_clp", "costo_u", "costo_u_usd",
                                       "iva_import_clp", "sobrecosto_pct")},
        "margenes_por_canal": {k: {"precio_neto": d["precio"], "comision_envio_pct": d["com"] + d["log"], "marketing_pct": d["mkt"],
                                   "mix": d["mix"]} for k, d in r["canales"]["detalle"].items()},
        "roi_proyectado": {k: {"contribucion_anual": an[k]["contribucion"], "contrib_pct": an[k]["contrib_pct"], "capital": an[k]["capital"],
                               "eva": an[k]["eva"], "roi_capital": an[k]["roi"], "roi_lote": lo[k]["roi_lote"],
                               "roi_anualizado": lo[k]["roi_anualizado"], "payback_mes": lo[k]["payback_mes"],
                               "exposicion_max_caja": lo[k]["exposicion_max"]} for k in an},
        "cruce_radar": [{"competidor": x["importador"], "evidencia": x["nivel"], "fob_u": x["fob_u_prom"], "internado_u_estimado": x["internado_u_estimado_clp"],
                         "diferencia_pct": x["dif_fob_pct"], "fabricas": x["fabricas"], "confianza": "MEDIA"} for x in (rad.get("competidores") or [])]
                       + [{"competidor": x["importador"], "glosa": x["glosa"], "fob_u": x["fob_u"], "confianza": x["confianza"]}
                          for x in (rad.get("coincidencias") or []) if x["confianza"] == "ALTA"],
        "veredicto": r["veredicto"], "razon": r["razon"], "fob_objetivo": r["fob_objetivo_usd"], "pvp_ideal": r.get("pvp_ideal"),
        "unidades_a_comprar": (r.get("lotes") or {}).get("recomendado"), "lotes": (r.get("lotes") or {}).get("opciones"),
    }


def guardar_json(r: dict, path) -> None:
    path.write_text(json.dumps(json_agentes(r), indent=1, ensure_ascii=False, default=float), encoding="utf-8")
