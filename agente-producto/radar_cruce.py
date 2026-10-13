"""Cruce del Agente Producto con el Radar de Importaciones (DIN públicas de Aduana, cubos del hub).

Qué entrega (últimos 12 meses publicados):
  · Distribución de precios FOB/u del tipo de producto y dónde queda nuestro FOB.
  · Competidores en una BANDA de precio comparable (0,5× a 1,5× nuestro FOB): unidades, DIN, FOB/u, última compra,
    tendencia contra los 12 meses previos, fábricas, forwarder y naviera.
  · Coincidencias por palabras clave con nivel de confianza:
      ALTA  = mismo tipo/partida, palabras clave (palabra completa) en la glosa y precio dentro de la banda
      MEDIA = mismo tipo/partida dentro de la banda de precio (sin palabras clave)
      BAJA  = palabras clave fuera del tipo/partida o fuera de la banda: no se usa para concluir.
  Solo la referencia ALTA (≥ 2 líneas) puede bloquear un COMPRAR; la MEDIA es una alerta.
El importador es INFERIDO (Aduana publica sin nombre): cada fila trae su nivel de evidencia. Nuestros costos internos no
salen de aquí; el internado de la competencia es una ESTIMACIÓN (su CIF + nuestros gastos de internación).
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

HUB = Path(os.environ.get("RADAR_HUB_DIR", "C:/Users/andre/radar_aduana/outputs/hub"))
UX = "RUT:76600685"
NIVEL_TXT = {"rut": "RUT declarado", "verificada": "Verificada", "probable": "Probable", "trazado": "Trazado sin nombre"}
BANDA = (1 / 1.5, 1.5)            # simétrica en escala de precios: ±50%


def _con():
    con = duckdb.connect()
    for t in ("lineas", "precios_dist"):
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{(HUB / f'{t}.parquet').as_posix()}')")
    return con


def cruzar(fob_u: float, tipo: str | None = None, arancel: str | None = None, palabras: list[str] | None = None,
           unidad: str = "U", unidades_anuales: float = 0.0, tc: float = 950.0, factor_internacion: float = 0.0) -> dict:
    """fob_u: nuestro FOB China por unidad (USD). factor_internacion: (agente + gastos Chile) / CIF de nuestra cascada."""
    if not (HUB / "lineas.parquet").exists():
        return {"disponible": False, "motivo": f"no encuentro los cubos del radar en {HUB}"}
    con = _con()
    hasta = con.execute("SELECT max(mes) FROM lineas").fetchone()[0]
    y, m = map(int, hasta.split("-"))
    mes = lambda k: f"{y + (m - 1 - k) // 12}-{(m - 1 - k) % 12 + 1:02d}"
    desde, desde_prev = mes(11), mes(23)
    palabras = [w.strip().upper() for w in (palabras or []) if w and w.strip()]
    glosa = "upper(concat_ws(' ', nombre, marca, modelo))"
    kw = " AND ".join(f"regexp_matches({glosa}, ?)" for _ in palabras) or "FALSE"
    import re as _re
    kw_params = [f"(^|[^A-Z0-9]){_re.escape(w)}([^A-Z0-9]|$)" for w in palabras]   # palabra completa: "40L" no es "240L"
    # sin tipo ni partida: se propone la partida más frecuente entre las líneas con las palabras clave
    supuesto_partida = None
    if not tipo and not arancel and palabras:
        r = con.execute(f"SELECT arancel, tipo, count(*) n FROM lineas WHERE mes >= ? AND {kw} GROUP BY 1, 2 ORDER BY n DESC LIMIT 1",
                        [desde, *kw_params]).fetchone()
        if r:
            arancel, tipo, supuesto_partida = r[0], r[1], f"partida {r[0]} / tipo '{r[1]}' (la más frecuente con esas palabras)"
    if not tipo and not arancel:
        return {"disponible": False, "motivo": "sin tipo, partida ni palabras clave para buscar"}
    filtro = []
    if tipo:
        filtro.append("tipo = ?")
    if arancel:
        filtro.append("arancel = ?")
    f_sql = " OR ".join(filtro)
    f_par = [x for x in (tipo, arancel) if x]
    base = con.execute(f"""SELECT mes, fecha_acep, id_operacion, importador_key, importador, nivel, tipo, arancel, nombre, marca, modelo,
                                  proveedor, proveedor_tipo, forwarder, naviera, unidad_cmp, unidades, kg_netos, fob_item, cif_item,
                                  fob_por_unidad, {kw} AS kw
                           FROM lineas WHERE mes >= ? AND ({f_sql}) AND unidad_cmp = ?""",
                       [*kw_params, desde_prev, *f_par, unidad]).df()
    if base.empty:
        return {"disponible": True, "sin_coincidencias": True, "hasta": hasta, "tipo": tipo, "arancel": arancel,
                "supuesto_partida": supuesto_partida, "competidores": [], "fabricas": [], "coincidencias": []}
    base["periodo"] = base.mes.ge(desde).map({True: "12m", False: "prev"})
    u12 = base[base.periodo.eq("12m")]
    # distribución de precios del tipo (ponderada por unidades) y posición de nuestro FOB
    q = u12.fob_por_unidad.quantile([.1, .25, .5, .75, .9]).round(2).to_dict()
    pos = float((u12.fob_por_unidad < fob_u).mean()) if len(u12) else None
    banda = base[base.fob_por_unidad.between(fob_u * BANDA[0], fob_u * BANDA[1])]
    b12 = banda[banda.periodo.eq("12m")]
    comp = []
    for k, g in b12[b12.importador_key.fillna("") != UX].groupby(b12.importador_key.fillna("NI"), sort=False):
        prev = banda[(banda.periodo == "prev") & (banda.importador_key.fillna("NI") == k)].unidades.sum()
        uds = g.unidades.sum()
        fobw = (g.fob_item.sum() / uds) if uds else None
        cifw = (g.cif_item.sum() / uds) if uds else None
        g2 = g.sort_values("fecha_acep")
        comp.append({"importador": g.importador.iloc[0] if k != "NI" else "No identificado",
                     "nivel": NIVEL_TXT.get(g.nivel.iloc[0], "Sin identificar") if k != "NI" else "Sin identificar",
                     "unidades_12m": float(uds), "din_12m": int(g.id_operacion.nunique()), "fob_u_prom": fobw,
                     "fob_u_ultimo": float(g2.fob_por_unidad.iloc[-1]), "ultima_compra": str(g2.fecha_acep.iloc[-1])[:10],
                     "cif_u_prom": cifw, "internado_u_estimado_clp": cifw * tc * (1 + factor_internacion) if cifw else None,
                     "dif_fob_pct": (fob_u / fobw - 1) if fobw else None, "unidades_12m_previos": float(prev),
                     "tendencia": ("nuevo" if prev == 0 else "creciendo" if uds > prev * 1.2 else "cayendo" if uds < prev * 0.8 else "estable"),
                     "fabricas": g.groupby("proveedor").unidades.sum().sort_values(ascending=False).head(3).index.tolist(),
                     "forwarder": g.forwarder.mode().iat[0] if g.forwarder.notna().any() else None,
                     "naviera": g.naviera.mode().iat[0] if g.naviera.notna().any() else None})
    comp.sort(key=lambda c: -c["unidades_12m"])
    # importadores que compraban en la banda y dejaron de hacerlo (12m previos sí, últimos 12m no)
    activos = {c["importador"] for c in comp}
    dejaron = (banda[(banda.periodo == "prev") & ~banda.importador.isin(activos) & (banda.importador_key.fillna("") != UX)]
               .groupby("importador").unidades.sum().sort_values(ascending=False).head(5))
    fab = (b12[(b12.importador_key.fillna("") != UX) & b12.proveedor.notna()].groupby(["proveedor", "proveedor_tipo"], dropna=False)
           .agg(unidades=("unidades", "sum"), importadores=("importador_key", "nunique"), fob_u=("fob_por_unidad", "median"))
           .reset_index().sort_values("unidades", ascending=False).head(10))
    # coincidencias por palabras clave (ALTA si misma partida; BAJA si otra partida)
    coinc = []
    # especificidad: si las palabras clave aparecen en más del 15% de las líneas del tipo, son genéricas ("ALUMINIO" en
    # baterías de cocina) y no identifican el mismo producto → sus coincidencias valen MEDIA, no ALTA
    share_kw = float(u12.kw.mean()) if palabras and len(u12) else 0.0
    genericas = share_kw > 0.15
    if palabras:
        kwl = con.execute(f"""SELECT mes, importador, nivel, importador_key, tipo, arancel, nombre, marca, modelo, proveedor, unidades,
                                     fob_por_unidad FROM lineas WHERE mes >= ? AND {kw} AND unidad_cmp = ? ORDER BY mes DESC LIMIT 400""",
                          [desde, *kw_params, unidad]).df()
        lo_b, hi_b = fob_u * BANDA[0], fob_u * BANDA[1]
        for r in kwl.itertuples():
            mismo = (arancel and r.arancel == arancel) or (tipo and r.tipo == tipo)
            conf = ("MEDIA" if genericas else "ALTA") if mismo and lo_b <= r.fob_por_unidad <= hi_b else "BAJA"
            coinc.append({"mes": r.mes, "importador": r.importador or "No identificado", "nivel": NIVEL_TXT.get(r.nivel, "Sin identificar"),
                          "es_unionx": r.importador_key == UX, "glosa": " ".join(str(x) for x in (r.nombre, r.marca, r.modelo) if x),
                          "proveedor": r.proveedor, "unidades": float(r.unidades), "fob_u": float(r.fob_por_unidad), "confianza": conf})
    coinc = sorted(coinc, key=lambda c: (c["confianza"] != "ALTA", c["es_unionx"]))   # ALTA primero (orden estable por mes desc)
    # referencia para la regla de decisión: ALTA de competidores identificados si hay; si no, la mediana de la banda (MEDIA)
    alta = [c for c in coinc if c["confianza"] == "ALTA" and not c["es_unionx"] and c["nivel"] != "Sin identificar"]
    if len(alta) >= 2:
        ref, ref_conf = float(pd.Series([c["fob_u"] for c in alta]).median()), "ALTA"
        ref_txt = f"mediana de {len(alta)} líneas de confianza ALTA (mismo producto según las palabras clave)"
    else:
        sel = b12[(b12.importador_key.fillna("") != UX)]
        ref = float((sel.fob_item.sum() / sel.unidades.sum())) if sel.unidades.sum() else None
        ref_conf, ref_txt = "MEDIA", "FOB promedio de los competidores en la banda de precio (productos de precio comparable, no el mismo producto)"
    nuestros = base[base.importador_key.fillna("").eq(UX) & base.periodo.eq("12m")]
    return {"disponible": True, "hasta": hasta, "desde": desde, "tipo": tipo, "arancel": arancel, "supuesto_partida": supuesto_partida,
            "unidad": unidad, "precios_tipo": q, "percentil_nuestro_fob": pos, "banda": [fob_u * BANDA[0], fob_u * BANDA[1]],
            "competidores": comp[:12], "dejaron_de_comprar": [{"importador": k, "unidades_12m_previos": float(v)} for k, v in dejaron.items()],
            "fabricas": fab.to_dict("records"), "coincidencias": coinc[:30], "fob_referencia_u": ref, "fob_referencia_txt": ref_txt, "fob_referencia_conf": ref_conf,
            "max_unidades_competidor_anual": max([c["unidades_12m"] for c in comp if c["importador"] != "No identificado"], default=0.0),
            "unidades_mercado_banda_12m": float(b12.unidades.sum()), "nuestras_unidades_12m": float(nuestros.unidades.sum()),
            "lineas_banda": int(len(b12)), "n_alta": sum(c["confianza"] == "ALTA" for c in coinc),
            "palabras_genericas": genericas, "share_palabras": share_kw}


def buscar_oportunidades(texto: str, meses: int = 12, limite: int = 60) -> pd.DataFrame:
    """Productos que importa la competencia (modo 'Oportunidad'): busca palabras en glosa, marca, modelo, importador y
    proveedor (todas las palabras, palabra completa) y agrupa por importador × producto × fábrica."""
    if not (HUB / "lineas.parquet").exists() or not texto.strip():
        return pd.DataFrame()
    import re as _re
    con = _con()
    hasta = con.execute("SELECT max(mes) FROM lineas").fetchone()[0]
    y, m = map(int, hasta.split("-"))
    desde = f"{y + (m - meses) // 12}-{(m - meses) % 12 + 1:02d}"
    import unicodedata
    texto = "".join(ch for ch in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(ch))   # la DIN viene sin tildes
    palabras = [w for w in _re.split(r"\s+", texto.strip().upper()) if w]
    campo = "upper(concat_ws(' ', nombre, marca, modelo, importador, proveedor))"
    cond = " AND ".join(f"regexp_matches({campo}, ?)" for _ in palabras)
    par = [f"(^|[^A-Z0-9]){_re.escape(w)}([^A-Z0-9]|$)" for w in palabras]
    d = con.execute(f"""
        SELECT coalesce(importador, 'No identificado') importador, any_value(nivel) nivel, tipo, arancel, unidad_cmp,
               trim(concat_ws(' ', nombre, marca, modelo)) producto, proveedor,
               sum(unidades) unidades, count(DISTINCT id_operacion) din, sum(fob_item) / nullif(sum(unidades), 0) fob_u,
               arg_max(fob_por_unidad, fecha_acep) fob_u_ultimo, max(fecha_acep) ultima, min(fecha_acep) primera,
               sum(kg_netos) / nullif(sum(unidades), 0) kg_u, sum(cif_item) / nullif(sum(unidades), 0) cif_u,
               any_value(forwarder) forwarder, any_value(naviera) naviera, any_value(importador_key) importador_key
        FROM lineas WHERE mes >= ? AND {cond}
        GROUP BY importador, tipo, arancel, unidad_cmp, producto, proveedor
        ORDER BY unidades DESC LIMIT {int(limite)}""", [desde, *par]).df()
    d["nivel"] = d.nivel.map(NIVEL_TXT).fillna("Sin identificar")
    d["es_unionx"] = d.importador_key.eq(UX)
    return d.drop(columns=["importador_key"])


def buscar_terminos(terminos: list[str], fuertes: list[str] | None = None, limite: int = 40) -> dict:
    """Búsqueda por puntaje en TODA la DIN (índice busqueda_din.parquet, últimos 12 meses), para el flujo por link.
    Peso 3: marca y códigos de modelo (palabras con dígitos); peso 1: el resto. Se queda con lo que suma al menos la mitad
    del mejor puntaje y trae una palabra fuerte o dos genéricas. Devuelve filas por importador × partida × glosa × fábrica,
    la partida más probable y el rango de precios por unidad de comparación."""
    import re as _re
    import unicodedata
    f = HUB / "busqueda_din.parquet"
    if not f.exists() or not terminos:
        return {"disponible": f.exists(), "filas": pd.DataFrame(), "partidas": [], "precios": {}}
    norm = lambda s: "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).upper().strip()
    fuertes = {norm(t) for t in (fuertes or [])}
    ts = [norm(t) for t in terminos if t and t.strip()]
    pat = lambda t: "(^|[^A-Z0-9])" + _re.escape(t).replace(r"\ ", "[ -]?") + "([^A-Z0-9]|$)"
    peso = {t: 3 if (t in fuertes or _re.search(r"\d", t)) else 1 for t in ts}
    con = duckdb.connect()
    con.execute("SET memory_limit='300MB'")
    con.execute("SET threads=2")
    campo = "glosa"                                   # el emisor es la naviera que emite el BL, no la fábrica
    score = " + ".join(f"CASE WHEN regexp_matches({campo}, ?) THEN {peso[t]} ELSE 0 END" for t in ts)
    fuerte = " OR ".join(f"regexp_matches({campo}, ?)" for t in ts if peso[t] == 3) or "FALSE"
    alguna = "regexp_matches(" + campo + ", ?)"
    union = "(" + "|".join(pat(t) for t in ts) + ")"
    params = [pat(t) for t in ts] + [pat(t) for t in ts if peso[t] == 3] + [union]
    d = con.execute(f"""
        WITH c AS (SELECT *, ({score}) puntaje, ({fuerte}) tiene_fuerte FROM read_parquet('{f.as_posix()}') WHERE {alguna})
        SELECT * FROM c""", params).df()
    if d.empty:
        return {"disponible": True, "filas": d, "partidas": [], "precios": {}}
    d["n_terminos"] = d.puntaje   # aproximación; se usa solo para el umbral
    tope = d.puntaje.max()
    d = d[(d.puntaje >= max(2, tope * 0.5)) & (d.tiene_fuerte | (d.puntaje >= 2))]
    imp = pd.read_parquet(HUB / "importadores.parquet", columns=["importador_key", "importador", "nivel"]) if (HUB / "importadores.parquet").exists() else None
    if imp is not None:
        d = d.merge(imp, on="importador_key", how="left")
    else:
        d["importador"], d["nivel"] = None, None
    d["importador"] = d.importador.fillna("No identificado")
    d["nivel"] = d.nivel.map(NIVEL_TXT).fillna("Sin identificar")
    d["es_unionx"] = d.importador_key.eq(UX)
    # la marca o fábrica viene en la glosa con el sufijo "-F" (ej. "PEG PEREGO-F", "FOODCHEM-F"): se toman hasta 2 palabras
    # justo antes, sin las palabras del producto ni los términos buscados
    genericas = ({w for t_ in ts if peso[t_] == 1 for w in t_.split()}
                 | {"DE", "DEL", "LA", "EL", "EN", "CON", "PARA", "Y", "I", "MINI", "JUGUETE", "CREAT"})

    def _fab(g: str):
        m_ = _re.search(r"([A-Z0-9.&' ]+?)-F(?:[\s,]|$)", g)
        if not m_:
            return None
        pal = [w for w in m_.group(1).split() if w not in genericas and len(w) > 1 and not _re.search(r"\d", w)]
        return " ".join(pal[-2:]) or None
    d["fabricante"] = d.glosa.map(_fab)
    d["fob_u"] = d.fob / d.cantidad.where(d.cantidad > 0)
    d["cif_u"] = d.cif / d.cantidad.where(d.cantidad > 0)
    d = d.sort_values(["puntaje", "fob"], ascending=False)
    # partida más probable: la que concentra más FOB entre los resultados del mejor puntaje
    top = d[d.puntaje >= tope]
    partidas = top.groupby("arancel").fob.sum().sort_values(ascending=False).head(3).index.tolist()
    precios = {}
    for u, g in d[d.arancel.isin(partidas)].groupby("unidad"):
        g = g[g.fob_u.notna()]
        if len(g):
            w = g.cantidad
            precios[u] = {"lineas": int(g.lineas.sum()), "cantidad": float(w.sum()), "fob_u_prom": float(g.fob.sum() / w.sum()),
                          "p25": float(g.fob_u.quantile(.25)), "p50": float(g.fob_u.median()), "p75": float(g.fob_u.quantile(.75))}
    d = d.rename(columns={"emisor": "naviera_bl"})
    if "kg_bruto_est" not in d:
        d["kg_bruto_est"] = None
    cols = ["importador", "nivel", "arancel", "glosa", "fabricante", "unidad", "cantidad", "din", "fob_u", "cif_u", "kg", "kg_bruto_est", "ultima", "naviera_bl",
            "puntaje", "es_unionx"]
    return {"disponible": True, "filas": d[cols].head(limite).reset_index(drop=True), "partidas": partidas, "precios": precios,
            "max_puntaje": int(tope), "terminos": ts}



def radar_desde_busqueda(res: dict, fob_u: float, partida: str, unidad: str, fuertes: list[str], tc: float,
                         factor_internacion: float = 0.0) -> dict:
    """Arma el cruce con la competencia (misma estructura que cruzar()) desde la búsqueda en toda la DIN: sirve para productos
    fuera del universo del radar (creatina, etc.). Competidores = misma partida y unidad, en la banda de precio ±50%."""
    d = res.get("filas")
    if d is None or d.empty:
        return {"disponible": True, "sin_coincidencias": True, "competidores": [], "fabricas": [], "coincidencias": []}
    import unicodedata
    norm = lambda s: "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).upper()
    x = d[(d.arancel == partida) & (d.unidad == unidad) & ~d.es_unionx & d.fob_u.notna()].copy()
    lo_b, hi_b = fob_u * BANDA[0], fob_u * BANDA[1]
    b = x[x.fob_u.between(lo_b, hi_b)]
    comp = []
    for imp_, g in b.groupby("importador", sort=False):
        u = g.cantidad.sum()
        fobw = float((g.fob_u * g.cantidad).sum() / u) if u else None
        cifw = float((g.cif_u * g.cantidad).sum() / u) if u else None
        comp.append({"importador": imp_, "nivel": g.nivel.iloc[0], "unidades_12m": float(u), "din_12m": int(g.din.sum()),
                     "fob_u_prom": fobw, "fob_u_ultimo": float(g.sort_values("ultima").fob_u.iloc[-1]),
                     "ultima_compra": str(g.ultima.max())[:10], "cif_u_prom": cifw,
                     "internado_u_estimado_clp": cifw * tc * (1 + factor_internacion) if cifw else None,
                     "dif_fob_pct": (fob_u / fobw - 1) if fobw else None, "unidades_12m_previos": 0.0, "tendencia": "—",
                     "fabricas": g.fabricante.dropna().unique().tolist()[:3], "forwarder": None, "naviera": g.naviera_bl.mode().iat[0] if g.naviera_bl.notna().any() else None})
    comp.sort(key=lambda c: -c["unidades_12m"])
    fs = {norm(f) for f in fuertes}
    alta = b[b.glosa.map(lambda s: any(f in s for f in fs))] if fs else b.iloc[0:0]
    coinc = [{"mes": str(r.ultima)[:7], "importador": r.importador, "nivel": r.nivel, "es_unionx": False, "glosa": r.glosa,
              "proveedor": r.fabricante, "unidades": float(r.cantidad), "fob_u": float(r.fob_u), "confianza": "ALTA"} for r in alta.itertuples()]
    if len(alta) >= 2:
        ref, conf, txt = float((alta.fob_u * alta.cantidad).sum() / alta.cantidad.sum()), "ALTA", f"FOB promedio de {len(alta)} líneas del mismo producto (marca o modelo)"
    elif len(b):
        ref, conf, txt = float((b.fob_u * b.cantidad).sum() / b.cantidad.sum()), "MEDIA", "FOB promedio de productos de precio comparable en la misma partida"
    else:
        ref, conf, txt = None, "MEDIA", "sin competidores en la banda de precio"
    fab = (b.dropna(subset=["fabricante"]).groupby("fabricante").agg(unidades=("cantidad", "sum"), fob_u=("fob_u", "median"))
           .reset_index().rename(columns={"fabricante": "proveedor"}).sort_values("unidades", ascending=False).head(10))
    q = x.fob_u.quantile([.1, .25, .5, .75, .9]).round(2).to_dict() if len(x) else {}
    return {"disponible": True, "sin_coincidencias": not len(x), "tipo": f"partida {partida}", "arancel": partida, "unidad": unidad,
            "desde": "últimos 12 meses", "hasta": "", "supuesto_partida": None, "precios_tipo": q,
            "percentil_nuestro_fob": float((x.fob_u < fob_u).mean()) if len(x) else None, "banda": [lo_b, hi_b],
            "competidores": comp[:12], "dejaron_de_comprar": [], "fabricas": fab.to_dict("records"), "coincidencias": coinc[:30],
            "fob_referencia_u": ref, "fob_referencia_txt": txt, "fob_referencia_conf": conf,
            "max_unidades_competidor_anual": max([c["unidades_12m"] for c in comp if c["importador"] != "No identificado"], default=0.0),
            "unidades_mercado_banda_12m": float(b.cantidad.sum()), "nuestras_unidades_12m": 0.0, "lineas_banda": int(len(b)),
            "n_alta": len(coinc), "palabras_genericas": False, "share_palabras": 0.0, "fuente": "DIN completa (índice de búsqueda)"}


def proveedor_origen(d: pd.DataFrame) -> pd.DataFrame:
    """A quién le compra la competencia: para cada fila del ranking (DIN), el proveedor declarado, país de origen, puerto de
    embarque y forwarder de las líneas del radar (lineas.parquet, solo categorías del universo del radar). Cruce: mismo
    importador y partida con FOB unitario ±2%. Sin cruce → vacío; cruce sin proveedor → 'no declarado'."""
    f = HUB / "lineas.parquet"
    vacio = pd.DataFrame({"proveedor_radar": None, "origen_radar": None}, index=d.index)
    if not f.exists() or d.empty:
        return vacio
    k = pd.DataFrame({"i": d.index, "importador": d.importador.astype(str), "arancel": d.arancel.astype(str),
                      "fob_u": pd.to_numeric(d.fob_u, errors="coerce")})
    con = duckdb.connect()
    con.register("k", k)
    m = con.execute(f"""
        SELECT k.i, coalesce(nullif(trim(l.proveedor_declarado), ''), nullif(trim(l.proveedor), '')) proveedor,
               l.pais_origen, l.puerto_embarque, l.forwarder, l.fecha_acep
        FROM k JOIN read_parquet('{f.as_posix()}') l
          ON l.importador = k.importador AND l.arancel = k.arancel
         AND k.fob_u > 0 AND abs(l.fob_por_unidad / k.fob_u - 1) < 0.02""").df()
    con.close()
    if m.empty:
        return vacio

    def moda(s):
        s = s.dropna().astype(str)
        s = s[~s.str.upper().isin(["", "NONE", "(NO DECLARADO)"])]
        return s.value_counts().index[0] if len(s) else None
    g = m.sort_values("fecha_acep").groupby("i")
    out = pd.DataFrame({"proveedor_radar": g.proveedor.agg(moda).fillna("no declarado"),
                        "pais": g.pais_origen.agg(moda), "puerto": g.puerto_embarque.agg(moda), "fwd": g.forwarder.agg(moda)})
    out["origen_radar"] = [" · ".join(x for x in (p, (pu or "").title()[:30] if pu and "NO ESPECIFICADO" not in pu.upper() else None,
                                                  f"forwarder {fw.title()}" if fw else None) if x)
                           for p, pu, fw in zip(out.pais, out.puerto, out.fwd)]
    return vacio.drop(columns=["proveedor_radar", "origen_radar"]).join(out[["proveedor_radar", "origen_radar"]])


def rankear_similitud(d: pd.DataFrame, ficha: dict, terminos_tipo: list[str] | None = None) -> pd.DataFrame:
    """Similitud 0–100 de cada línea de la DIN con la ficha técnica (reglas; la IA puede refinarla después):
    tipo de producto 40 · marca/modelo 15 · capacidad 15 · potencia 10 · peso por unidad 20 (la DIN trae kilos y unidades)."""
    import re as _re
    import unicodedata
    if d is None or d.empty:
        return d
    norm = lambda s: "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(ch)).upper()
    esp = (ficha or {}).get("especificaciones") or ficha or {}
    cap, pot, peso = esp.get("capacidad_ml"), esp.get("potencia_w"), esp.get("peso_kg")
    tipo = [norm(t) for t in (terminos_tipo or (ficha or {}).get("terminos_aduana") or []) if t]
    marca = [norm(x) for x in ((ficha or {}).get("marca"), (ficha or {}).get("modelo_fabrica")) if x]
    out = d.copy()
    neto = (out.kg / out.cantidad).where((out.unidad != "KG") & (out.kg > 0) & (out.cantidad > 0))
    bruto = (out.kg_bruto_est / out.cantidad).where((out.unidad != "KG") & (out.kg_bruto_est > 0) & (out.cantidad > 0)) / 1.15
    out["kg_u"] = neto.fillna(bruto)                  # neto declarado; si no hay, bruto estimado de la DIN ÷ 1,15 (embalaje)
    sims, razones = [], []
    for r in out.itertuples():
        g = norm(r.glosa)
        s, rz = 0.0, []
        if tipo:
            hit = [t for t in tipo if t in g]
            s += 40 * len(hit) / len(tipo)
            if hit:
                rz.append("tipo: " + ", ".join(hit[:3]).lower())
        if any(m and m in g for m in marca):
            s += 15
            rz.append("misma marca/modelo")
        m = _re.search(r"(\d{2,4})\s*ML\b", g) or _re.search(r"(\d(?:[.,]\d+)?)\s*(?:L|LT|LTS|LITROS?)\b", g)
        if cap and m:
            v = float(m.group(1).replace(",", ".")) * (1 if "ML" in m.group(0) else 1000)
            s += 15 * max(0.0, 1 - abs(v / cap - 1))
            rz.append(f"capacidad {v:.0f} ml")
        m = _re.search(r"(\d{2,4})\s*(?:W|WATTS?)\b", g)
        if pot and m:
            s += 10 * max(0.0, 1 - abs(float(m.group(1)) / pot - 1))
            rz.append(f"{m.group(1)} W")
        if peso and r.kg_u == r.kg_u and r.kg_u:
            s += 20 * max(0.0, 1 - abs(r.kg_u / peso - 1))
            rz.append(f"{r.kg_u:.2f} kg/u")
        sims.append(round(min(100.0, s)))
        razones.append(" · ".join(rz))
    out["similitud"], out["razon"] = sims, razones
    return out.sort_values(["similitud", "cantidad"], ascending=False).reset_index(drop=True)
