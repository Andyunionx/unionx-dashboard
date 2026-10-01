"""Radar de Importaciones — Excel de decisión (descargable del hub).

Pensado para tres flujos de gestión de Andrés (29-sep-2026):
  1. Competitividad: "tengo un producto caro → ¿quién lo compra mejor, cuánto trae, a cuánto, cuánto demora
     y dónde pierdo contra él?"                                  → hoja '1 · Mi SKU vs mercado' + 'Competidores'
  2. Oportunidad: "quiero potenciar mi categoría → ¿qué se importa en ella (lo traiga o no) con volumen,
     crecimiento y costo que dejen margen?"                       → hoja '2 · Oportunidades'
  3. Logística: "demoro más o pago más flete que la mediana → ¿quién lo hace mejor y cómo?"
                                                                  → hoja '3 · Logística' + 'Competidores'
Formato aprobado por Andrés para modelos: Léeme · Supuestos (celdas naranjas editables, con fuente) ·
cálculo con FÓRMULAS (no valores pegados). Los agregados de la DIN son datos (MEDIDO); todo lo que depende
de un supuesto (TC, internación, referencia de precio, umbrales, precio de venta) es fórmula.
"""
from __future__ import annotations

import io
import json
import urllib.parse
from datetime import datetime

import pandas as pd

NARANJO = {"bg_color": "#FDF3E7", "font_color": "#B5651D", "bold": True, "border": 1, "border_color": "#B5651D"}
REFS = ("Mediana", "p25", "Mejor importador")


# ---------------------------------------------------------------- datos
MODOS = (("via", "via"), ("modalidad", "modalidad"), ("puerto", "puerto_embarque"), ("pais", "pais_origen"),
         ("forwarder", "forwarder"), ("naviera", "naviera"))


def _modos() -> str:
    """Valor principal (por CIF) de cada atributo logístico, por tipo × importador."""
    return ",\n         ".join(
        f"m_{a} AS (SELECT tipo, importador_key, arg_max(v, c) {a} FROM (SELECT tipo, importador_key, {c} v, "
        f"sum(cif_item) c FROM l WHERE {c} IS NOT NULL GROUP BY 1, 2, 3) GROUP BY 1, 2)" for a, c in MODOS)


def _mes_siguiente(m: str) -> str:
    y, mm = int(m[:4]), int(m[5:7])
    return f"{y + (mm == 12)}-{1 if mm == 12 else mm + 1:02d}-01"


def _v(v):
    """Valor escribible en Excel (numpy → Python); None si falta."""
    import numpy as np
    if v is None or v is pd.NA or v is pd.NaT or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, np.bool_) or isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if np.isnan(v) else float(v)
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    return v


def _dominante(q, w, p) -> str:
    return f"""d AS (SELECT tipo, arg_max(unidad_cmp, u) unidad FROM (
                   SELECT tipo, unidad_cmp, sum(unidades) u FROM mercado WHERE {w} AND unidades > 0 GROUP BY 1, 2)
                 GROUP BY 1)"""


def competidores(q, where, f: dict, ux: str, min_unid: int) -> pd.DataFrame:
    """Tipo × importador: precio por unidad comparable, volumen, logística y a quién compra (todo el mercado)."""
    fm = dict(f, importadores=[])
    w, p = where(fm)
    wl, pl = where(fm, alias="l")
    wt, pt = where(fm, alias="t")
    df = q(f"""
    WITH {_dominante(q, w, p)},
         l AS (SELECT l.*, d.unidad, (l.unidad_cmp = d.unidad AND l.unidades > 0) AS en_u
               FROM lineas l JOIN d USING (tipo) WHERE {wl} AND l.importador_key <> 'NI'),
         base AS (SELECT tipo, importador_key, any_value(unidad) unidad,
                         sum(unidades) FILTER (WHERE en_u) unidades, sum(fob_item) FILTER (WHERE en_u) fob_en_u,
                         sum(cif_item) FILTER (WHERE en_u) cif_en_u, sum(cif_item) cif,
                         count(DISTINCT id_operacion) n_din, count(DISTINCT mes) meses, max(mes) ultimo_mes
                  FROM l GROUP BY 1, 2),
         {_modos()},
         prov AS (SELECT tipo, importador_key,
                         arg_max(proveedor, c) FILTER (WHERE proveedor IS NOT NULL) prov,
                         max(c) FILTER (WHERE proveedor IS NOT NULL) / sum(c) prov_pct
                  FROM (SELECT tipo, importador_key, proveedor, sum(cif_item) c FROM l GROUP BY 1, 2, 3) GROUP BY 1, 2),
         prod AS (SELECT tipo, importador_key, string_agg(txt, ' · ' ORDER BY c DESC) trae FROM (
                     SELECT tipo, importador_key, txt, c, row_number() OVER (PARTITION BY tipo, importador_key ORDER BY c DESC) rn
                     FROM (SELECT tipo, importador_key,
                                  left(nombre, 30) || coalesce(' ' || nullif(left(modelo, 18), ''), '') ||
                                  coalesce(' US$' || CAST(round(sum(fob_item) FILTER (WHERE en_u) / sum(unidades) FILTER (WHERE en_u), 2) AS VARCHAR), '') txt,
                                  sum(cif_item) c
                           FROM l GROUP BY 1, 2, nombre, modelo))
                  WHERE rn <= 3 GROUP BY 1, 2),
         lg AS (SELECT t.tipo, t.importador_key,
                       sum(d.fob_din * t.cif / d.cif_din) fob_w, sum((d.flete_din + d.seguro_din) * t.cif / d.cif_din) fle_w,
                       median(d.dias_emb_din) FILTER (WHERE d.via LIKE '%MAR%') dias
                FROM (SELECT id_operacion, tipo, importador_key, sum(cif) cif FROM din_tipo t WHERE {wt} GROUP BY 1, 2, 3) t
                JOIN din d USING (id_operacion) WHERE d.cif_din > 0 GROUP BY 1, 2)
    SELECT b.*, m_via.via, m_modalidad.modalidad, m_puerto.puerto, m_pais.pais, m_forwarder.forwarder, m_naviera.naviera,
           pr.prov, pr.prov_pct, pd.trae, lg.fob_w, lg.fle_w, lg.dias, i.importador, i.rut_fmt, i.nivel
    FROM base b {' '.join(f'LEFT JOIN m_{a} USING (tipo, importador_key)' for a, _ in MODOS)}
    LEFT JOIN prov pr USING (tipo, importador_key)
    LEFT JOIN prod pd USING (tipo, importador_key) LEFT JOIN lg USING (tipo, importador_key)
    LEFT JOIN importadores i USING (importador_key)""", p + pl + pt)
    if df.empty:
        return df
    df["fob_u"] = df.fob_en_u / df.unidades
    df["cif_u"] = df.cif_en_u / df.unidades
    df["flete_pct"] = df.fle_w / df.fob_w
    df["lote"] = df.unidades / df.n_din
    df["es_ux"] = df.importador_key == ux
    try:   # total de la empresa con TODOS sus productos (el radar muestra solo nuestro universo)
        tt = q("SELECT importador_key, sum(cif_total) cif_total FROM imp_total WHERE mes BETWEEN ? AND ? GROUP BY 1",
               (f["desde"], f["hasta"]))
        df = df.merge(tt, on="importador_key", how="left")
    except Exception:
        df["cif_total"] = None
    df["importador"] = df.importador.fillna(df.importador_key)
    df.loc[df.es_ux, "importador"] = "UnionX"
    # precio plausible: dentro de 1/5–5× la mediana del tipo (fuera casi siempre = unidad mal declarada)
    ok = df[(df.unidades >= min_unid) & ~df.es_ux]
    med = ok.groupby("tipo").fob_u.median()
    m = df.tipo.map(med)
    df["plausible"] = df.fob_u.between(m / 5, m * 5) | m.isna()
    df = df[(df.unidades >= min_unid) | (df.cif >= 50_000) | df.es_ux]
    # por tipo: primero los precios plausibles (de más barato a más caro); los implausibles al final, marcados
    return df.sort_values(["tipo", "plausible", "fob_u"], ascending=[True, False, True], na_position="last").reset_index(drop=True)


def comparar_skus(nos: pd.DataFrame, comp: pd.DataFrame, min_unid: int, banda: float) -> pd.DataFrame:
    """Cada SKU contra los importadores del mismo tipo que compran en SU rango de precio (1/banda a banda × nuestro
    FOB): un tipo mezcla gamas (audífono gamer 7.1 vs audífono básico) y la mediana del tipo completo engaña.
    Comparables = no UnionX, ≥ mín. unidades, precio plausible. 'Mejor' = el más barato dentro de la banda."""
    c = comp[~comp.es_ux & (comp.unidades >= min_unid) & comp.plausible & comp.fob_u.notna()] if len(comp) else comp
    por_tipo = {tp: g.sort_values("fob_u") for tp, g in c.groupby("tipo")} if len(c) else {}
    campos = ("importador", "unidades", "fob_u", "cif_u", "flete_pct", "dias", "prov", "puerto", "forwarder", "naviera", "trae")
    filas = []
    for r in nos.itertuples():
        g, d = por_tipo.get(r.tipo), {}
        if g is not None and len(g):
            d["p50_tipo"], d["n_tipo"] = g.fob_u.median(), len(g)
            gb = g[(g.fob_u >= r.fob / banda) & (g.fob_u <= r.fob * banda)] if pd.notna(r.fob) and r.fob > 0 else g.iloc[0:0]
            if len(gb):
                d.update(n=len(gb), p25=gb.fob_u.quantile(0.25), p50=gb.fob_u.median(), percentil=(gb.fob_u < r.fob).mean())
                m = gb.iloc[0]
                d.update({"mejor_" + k: m[k] for k in campos})
                d["tres"] = " · ".join(f"{str(x.importador)[:32]} US${x.fob_u:.2f} ({int(x.unidades):,} u)".replace(",", ".")
                                       for x in gb.head(3).itertuples())
        filas.append(d)
    return pd.concat([nos.reset_index(drop=True), pd.DataFrame(filas)], axis=1)


def mis_skus(q, f: dict) -> pd.DataFrame:
    wn, pn = ["tipo IS NOT NULL", "sku <> ''", "NOT regexp_matches(upper(sku), '^MLL')",
              "NOT regexp_matches(upper(coalesce(producto, '')), 'MUESTRA')", "eta >= ? AND eta < ?"], \
             [f"{f['desde']}-01", _mes_siguiente(f["hasta"])]
    if f.get("skus"):
        wn.append(f"sku IN ({','.join('?' * len(f['skus']))})"); pn += f["skus"]
    else:
        if f["tipos"]:
            wn.append(f"tipo IN ({','.join('?' * len(f['tipos']))})"); pn += f["tipos"]
        if f["categorias"]:
            wn.append(f"categoria IN ({','.join('?' * len(f['categorias']))})"); pn += f["categorias"]
    t = q(f"""SELECT sku, arg_max(producto, eta) producto, arg_max(tipo, eta) tipo, arg_max(categoria, eta) categoria,
                     sum(qty) unidades, arg_max(embarque, eta) ultimo_embarque, max(eta) ultima_eta,
                     arg_max(fob_usd, eta) fob, arg_max(internado_clp, eta) internado_clp, arg_max(tc, eta) tc
              FROM nosotros WHERE {' AND '.join(wn)} GROUP BY sku""", tuple(pn))
    if len(t) and _existe(q, "ventas"):      # ventas y ROI por SKU (modelo ROI por producto, en validación)
        v = q("SELECT sku, vendidas_12m, precio_real, contrib_pct, roi_capital, cat_comercial FROM ventas")
        t = t.merge(v, on="sku", how="left")
    return t


def _existe(q, tabla: str) -> bool:
    return bool(q("SELECT count(*) n FROM information_schema.tables WHERE table_name = ?", (tabla,)).iloc[0]["n"])


def oportunidades(q, where, f: dict, comp: pd.DataFrame, ux: str, min_unid: int, top_n: int = 300) -> pd.DataFrame:
    """Todo lo que se importa en las categorías filtradas (lo traigamos o no): tamaño, crecimiento, concentración, costo."""
    y, m = int(f["hasta"][:4]), int(f["hasta"][5:7])
    ini12 = f"{y - 1}-{m + 1:02d}" if m < 12 else f"{y}-01"
    ini24 = f"{y - 2}-{m + 1:02d}" if m < 12 else f"{y - 1}-01"
    fin_ant = f"{y - 1}-{m:02d}"
    fo = dict(f, mirada="Ambas", importadores=[], desde=ini24, hasta=f["hasta"])
    w, p = where(fo)
    # unidades: solo grupos (mes × importador) con precio unitario plausible (1/5–5× la mediana del tipo); si no,
    # una declaración mal hecha (componentes contados como unidades) infla el total a miles de millones
    t = q(f"""
      WITH {_dominante(q, w, p)},
           med AS (SELECT m.tipo, median(m.fob_u / m.unidades) mu FROM mercado m JOIN d USING (tipo)
                   WHERE {w} AND m.unidades > 0 AND m.fob_u > 0 AND m.unidad_cmp = d.unidad GROUP BY 1),
           a AS (SELECT m.tipo, any_value(m.universo) universo, any_value(m.categoria) categoria,
                        sum(m.cif) FILTER (WHERE m.mes >= ?) cif12, sum(m.cif) FILTER (WHERE m.mes <= ?) cif12_ant,
                        sum(m.unidades) FILTER (WHERE m.mes >= ? AND m.unidad_cmp = d.unidad AND m.unidades > 0
                                                AND m.fob_u / m.unidades BETWEEN med.mu / 5 AND med.mu * 5) u12,
                        sum(m.cif) FILTER (WHERE m.mes >= ? AND m.importador_key = ?) cif12_ux,
                        any_value(d.unidad) unidad
                 FROM mercado m JOIN d USING (tipo) LEFT JOIN med USING (tipo) WHERE {w} GROUP BY 1),
           imp AS (SELECT tipo, importador_key, sum(cif) c FROM mercado WHERE {w} AND mes >= ? AND importador_key NOT IN ('NI')
                   GROUP BY 1, 2),
           conc AS (SELECT tipo, count(*) n_imp, sum(c) FILTER (WHERE rn <= 3) / sum(c) top3,
                           string_agg(importador || ' ' || CAST(CAST(round(100 * c / tot) AS INT) AS VARCHAR) || '%', ' · ' ORDER BY c DESC) FILTER (WHERE rn <= 3) top_imp
                    FROM (SELECT imp.*, coalesce(i.importador, imp.importador_key) importador, sum(c) OVER (PARTITION BY tipo) tot,
                                 row_number() OVER (PARTITION BY tipo ORDER BY c DESC) rn
                          FROM imp LEFT JOIN importadores i USING (importador_key)) GROUP BY 1),
           pv AS (SELECT tipo, string_agg(proveedor || ' ' || CAST(CAST(round(100 * c / tot) AS INT) AS VARCHAR) || '%', ' · ' ORDER BY c DESC) FILTER (WHERE rn <= 3) top_prov
                  FROM (SELECT tipo, proveedor, sum(cif) c, sum(sum(cif)) OVER (PARTITION BY tipo) tot,
                               row_number() OVER (PARTITION BY tipo ORDER BY sum(cif) DESC) rn
                        FROM proveedores WHERE {w} AND mes >= ? AND proveedor <> '(no declarado)' GROUP BY 1, 2) GROUP BY 1)
      SELECT a.*, conc.n_imp, conc.top3, conc.top_imp, pv.top_prov FROM a LEFT JOIN conc USING (tipo) LEFT JOIN pv USING (tipo)
      WHERE a.tipo <> 'Otros · resto'          -- agregado de lo adyacente menor: no es un producto
      ORDER BY a.cif12 DESC NULLS LAST LIMIT {top_n}""",
          p + p + (ini12, fin_ant, ini12, ini12, ux) + p + p + (ini12,) + p + (ini12,))
    if t.empty:
        return t
    c = comp[~comp.es_ux & (comp.unidades >= min_unid) & comp.plausible]
    pr = c.groupby("tipo").fob_u.agg(p25=lambda s: s.quantile(0.25), p50="median")
    lg = comp[~comp.es_ux].groupby("tipo").agg(fob_w=("fob_w", "sum"), fle_w=("fle_w", "sum"), dias=("dias", "median"))
    t = t.merge(pr, left_on="tipo", right_index=True, how="left").merge(lg, left_on="tipo", right_index=True, how="left")
    t["flete_pct"] = t.fle_w / t.fob_w
    return t


def proveedores_por_tipo(q, where, f: dict, ux: str, por_tipo: int = 25) -> pd.DataFrame:
    fm = dict(f, importadores=[])
    w, p = where(fm)
    wl, pl = where(fm, alias="l")
    return q(f"""
      WITH {_dominante(q, w, p)},
           l AS (SELECT l.*, (l.unidad_cmp = d.unidad AND l.unidades > 0) en_u, d.unidad FROM lineas l JOIN d USING (tipo)
                 WHERE {wl} AND l.proveedor IS NOT NULL),
           g AS (SELECT tipo, proveedor, any_value(proveedor_tipo) ptipo, any_value(unidad) unidad, sum(cif_item) cif,
                        sum(unidades) FILTER (WHERE en_u) u, sum(fob_item) FILTER (WHERE en_u) / sum(unidades) FILTER (WHERE en_u) fob_u,
                        count(DISTINCT importador_key) FILTER (WHERE importador_key <> 'NI') n_imp,
                        bool_or(importador_key = ?) ux, arg_max(pais_origen, cif_item) pais, arg_max(puerto_embarque, cif_item) puerto
                 FROM l GROUP BY 1, 2),
           ti AS (SELECT tipo, proveedor, string_agg(coalesce(i.importador, x.importador_key), ' · ' ORDER BY c DESC) FILTER (WHERE rn <= 3) imps
                  FROM (SELECT tipo, proveedor, importador_key, sum(cif_item) c,
                               row_number() OVER (PARTITION BY tipo, proveedor ORDER BY sum(cif_item) DESC) rn
                        FROM l WHERE importador_key <> 'NI' GROUP BY 1, 2, 3) x
                  LEFT JOIN importadores i USING (importador_key) GROUP BY 1, 2)
      SELECT * FROM (SELECT g.*, ti.imps, row_number() OVER (PARTITION BY g.tipo ORDER BY g.cif DESC) rk
                     FROM g LEFT JOIN ti USING (tipo, proveedor) WHERE g.cif >= 5000)
      WHERE rk <= {por_tipo} ORDER BY tipo, cif DESC""", p + pl + (ux,))


def tc_observado(defecto: float) -> tuple[float, str]:
    try:
        import requests
        r = requests.get("https://mindicador.cl/api/dolar", timeout=6).json()["serie"][0]
        return float(r["valor"]), f"Dólar observado mindicador.cl del {r['fecha'][:10]} (editable)"
    except Exception:
        return defecto, "Último TC de nuestros costeos (mindicador.cl no respondió; editable)"


# ---------------------------------------------------------------- Excel
def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def construir(q, where, f: dict, ux: str, min_unid: int = 500, sabana: pd.DataFrame | None = None,
              logistica: pd.DataFrame | None = None, filtros_txt: list | None = None, banda: float = 2.0) -> bytes:
    comp = competidores(q, where, f, ux, min_unid)
    nos = mis_skus(q, f)
    # oportunidades: TODA la categoría (núcleo + adyacente), aunque el hub esté mirando solo el núcleo
    comp_op = comp if f["mirada"] == "Ambas" else competidores(q, where, dict(f, mirada="Ambas"), ux, min_unid)
    opo = oportunidades(q, where, f, comp_op, ux, min_unid)
    precio_tipo = {}
    if _existe(q, "ventas"):   # nuestro precio real promedio por tipo (lo que vendemos), para precargar el margen
        precio_tipo = dict(q("""SELECT n.tipo, sum(v.venta_12m) / sum(v.vendidas_12m) p FROM ventas v
                                JOIN (SELECT sku, arg_max(tipo, eta) tipo FROM nosotros WHERE tipo IS NOT NULL GROUP BY 1) n USING (sku)
                                WHERE v.vendidas_12m > 0 AND v.venta_12m > 0 GROUP BY 1""").values.tolist())
    prov = proveedores_por_tipo(q, where, f, ux)
    ux_t = comp[comp.es_ux].set_index("tipo") if len(comp) else pd.DataFrame()
    meses = (int(f["hasta"][:4]) - int(f["desde"][:4])) * 12 + int(f["hasta"][5:7]) - int(f["desde"][5:7]) + 1
    tc_def = float(nos.tc.dropna().iloc[-1]) if len(nos) and nos.tc.notna().any() else 950.0
    tc, tc_src = tc_observado(tc_def)
    # gastos en Chile (puerto, agente, transporte a bodega) sobre CIF, medidos en NUESTROS precosteos (la Maestra
    # antigua trae filas con internado < CIF que lo distorsionan); si no hay precosteos en el período, todos
    internos = q("""SELECT sum(internado_usd * qty) FILTER (WHERE fuente = 'Precosteo') / sum(cif_usd * qty) FILTER (WHERE fuente = 'Precosteo') - 1 p,
                           median(internado_usd / cif_usd - 1) m
                    FROM nosotros WHERE eta >= ? AND eta < ? AND cif_usd > 0 AND internado_usd > 0""",
                 (f"{f['desde']}-01", _mes_siguiente(f["hasta"]))).iloc[0]
    internacion = next((float(v) for v in (internos["p"], internos["m"]) if v is not None and pd.notna(v) and 0.002 < v < 0.3), 0.02)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        wb = xw.book
        F = {
            "tit": wb.add_format({"bold": True, "font_size": 14, "font_color": "#1F3864"}),
            "sub": wb.add_format({"italic": True, "font_color": "#595959"}),
            "h": wb.add_format({"bold": True, "bg_color": "#1F3864", "font_color": "white", "text_wrap": True, "valign": "top", "border": 1}),
            "hf": wb.add_format({"bold": True, "bg_color": "#375623", "font_color": "white", "text_wrap": True, "valign": "top", "border": 1}),
            "he": wb.add_format({"bold": True, "bg_color": "#B5651D", "font_color": "white", "text_wrap": True, "valign": "top", "border": 1}),
            "ed": wb.add_format(NARANJO), "ed_pct": wb.add_format({**NARANJO, "num_format": "0.0%"}),
            "ed_n": wb.add_format({**NARANJO, "num_format": "#,##0.00"}), "ed_clp": wb.add_format({**NARANJO, "num_format": "#,##0"}),
            "usd": wb.add_format({"num_format": "#,##0.00"}), "usd0": wb.add_format({"num_format": "#,##0"}),
            "n0": wb.add_format({"num_format": "#,##0"}), "pct": wb.add_format({"num_format": "0.0%"}),
            "f_usd": wb.add_format({"num_format": "#,##0.00", "bg_color": "#EAF1DD"}), "f_usd0": wb.add_format({"num_format": "#,##0", "bg_color": "#EAF1DD"}),
            "f_pct": wb.add_format({"num_format": "0.0%", "bg_color": "#EAF1DD"}), "f_txt": wb.add_format({"bg_color": "#EAF1DD"}),
            "f_n": wb.add_format({"num_format": "0.0", "bg_color": "#EAF1DD"}),
            "txt": wb.add_format({"text_wrap": True, "valign": "top"}), "b": wb.add_format({"bold": True}),
            "ux": wb.add_format({"bold": True, "font_color": "#C00000"}),
        }

        # ------------------------------------------------ Léeme
        ws = wb.add_worksheet("Léeme")
        ws.set_column(0, 0, 30); ws.set_column(1, 1, 120)
        ws.write(0, 0, "Radar de Importaciones — Excel de decisión", F["tit"])
        ws.write(1, 0, f"Generado {datetime.now():%d-%m-%Y %H:%M} · DIN públicas de Aduana · costos UnionX = Maestra + precosteos", F["sub"])
        filas = [
            ("QUÉ RESPONDE", ""),
            ("1 · Mi SKU vs mercado", "Flujo de competitividad. Cada SKU nuestro contra los importadores que traen el MISMO tipo de producto: "
             "percentil de precio, quién compra más barato (sus unidades, FOB y CIF por unidad, flete, días, proveedor, "
             "puerto, forwarder, qué trae) y el AHORRO POTENCIAL al año si pagáramos el precio de referencia. 'Dónde pierdo' "
             "dice si la brecha es de precio, de flete o de tiempo. Ordenado por ahorro potencial."),
            ("2 · Oportunidades", "Flujo de oportunidad. Todo lo que se importa en las categorías filtradas —lo traigamos o no, en nuestras "
             "subpartidas (Núcleo) y en nuestras partidas (Adyacente)—: tamaño y crecimiento 12 meses, concentración, costo por unidad "
             "del mercado, flete y días. Escribe un PRECIO DE VENTA de referencia (columna naranja) y la planilla calcula costo puesto "
             "y margen bruto con fórmula."),
            ("3 · Logística", "Flujo de logística. Flete+seguro sobre FOB y días de embarque a DIN de cada importador por tipo de producto, "
             "contra UnionX (brecha con fórmula), con su vía, modalidad, puerto, forwarder y naviera: el 'cómo lo hace'."),
            ("Competidores", "La base de las tres: tipo × importador con precio, volumen, lote por DIN, logística y a quién compra. "
             "Filtrar por tipo con el autofiltro. Las columnas verdes comparan contra UnionX con fórmula."),
            ("Proveedores", "Con quién compra el mercado cada tipo: proveedor (vendedor extranjero declarado: fábrica o trading, NO el "
             "forwarder), cuántos importadores le compran, a cuánto, desde dónde, y si nosotros le compramos. Links de búsqueda para contacto."),
            ("Sábana", "Línea a línea de la DIN con los filtros del hub (MEDIDO), para verificar comparables a mano."),
            ("Ventas y ROI (hoja 1)", "Vendidas 12m, precio real neto, contribución % y ROI s/capital vienen del modelo 'ROI por producto' "
             "(sep-25→ago-26, EN VALIDACIÓN): sirven para partir por el SKU con ROI malo y mucho volumen. 'Margen extra' = lo que "
             "bajaría el FOB por unidad si pagáramos la referencia, al TC, sobre el precio real (no incluye el efecto en flete e internación)."),
            ("", ""),
            ("CÓMO SE LEE", ""),
            ("MEDIDO / DERIVADO / SUPUESTO", "MEDIDO = sale de la DIN o de nuestros costeos. DERIVADO = calculado (columnas verdes, con fórmula). "
             "SUPUESTO = hoja Supuestos (celdas naranjas, editables): al cambiarlas cambia todo lo calculado."),
            ("Importador", "Nombre INFERIDO (Aduana anonimiza). Evidencia: 🟢 verificada = ≥90% de su CIF en meses amarrados a su RUT "
             "por ≥2 códigos trazadores · 🟡 probable = parte de sus meses enganchados por 1 código + misma comuna, o por sus marcas."),
            ("Precio por unidad", "FOB de la DIN ÷ unidades comparables (unidad dominante del tipo). Si la DIN viene en kilos, las unidades salen "
             "de la observación 99 ('11 PIEZAS'). Se excluyen precios implausibles (fuera de 1/5–5× la mediana del tipo)."),
            ("Banda de precio", f"En 'Mi SKU' se compara solo contra quienes compran el tipo entre 1/{banda:g} y {banda:g} veces nuestro FOB "
             "(misma gama); la mediana del tipo completo queda como contexto. 'Mejor importador' = el más barato de la banda."),
            ("Comparables", f"Importadores con ≥ {min_unid:,} unidades del tipo en el período (parámetro del hub al generar). Un tipo mezcla "
             "calidades y tamaños: antes de decidir, mirar 'Qué trae' y la Sábana."),
            ("Días", "Fecha de aceptación de la DIN − fecha del conocimiento de embarque (BL), solo marítimo: tránsito + internación, "
             "no incluye producción."),
            ("Flete+seguro / FOB", "De la DIN (flete y seguro declarados), prorrateado por el peso del tipo en cada DIN. Depende de la densidad "
             "del producto: comparar dentro del mismo tipo."),
            ("Lo que NO está", "Courier (DHL, muestras), lo importado a nombre de terceros y el costo real de internación de los demás "
             "(se estima con el supuesto). Montos por empresa = piso."),
            ("", ""),
            ("FILTROS AL GENERAR", ""),
        ] + [(a, b) for a, b in (filtros_txt or [])]
        for i, (a, b) in enumerate(filas, start=3):
            ws.write(i, 0, a, F["b"] if b == "" and a else None)
            ws.write(i, 1, b, F["txt"])

        # ------------------------------------------------ Supuestos
        ws = wb.add_worksheet("Supuestos")
        ws.set_column(0, 0, 46); ws.set_column(1, 1, 18); ws.set_column(2, 2, 100)
        ws.write(0, 0, "SUPUESTOS DEL ANÁLISIS", F["tit"])
        ws.write(1, 0, "Celdas naranjas = editables. Todo lo calculado en las otras hojas se actualiza solo.", F["sub"])
        for j, h in enumerate(("Supuesto", "Valor", "De dónde sale")):
            ws.write(3, j, h, F["h"])
        sup = [
            ("TC", "Tipo de cambio (CLP por USD)", tc, F["ed_n"], tc_src),
            ("INTERNACION", "Gastos de internación y locales (% sobre CIF)", internacion, F["ed_pct"],
             "MEDIDO en nuestros costeos del período: internado ÷ CIF − 1 (ponderado). Se usa para estimar el costo puesto de otros."),
            ("IVA", "IVA", 0.19, F["ed_pct"], "Para pasar el precio de venta con IVA a neto (hoja Oportunidades)."),
            ("REF", "Precio de referencia para 'Mi SKU'", "Mediana", F["ed"],
             "Mediana / p25 / Mejor importador. Contra qué se mide la brecha y el ahorro potencial."),
            ("REF_OP", "Precio de mercado para 'Oportunidades'", "Mediana", F["ed"], "Mediana / p25 del FOB por unidad del mercado."),
            ("UMB_PRECIO", "Umbral 'pierdo en precio' (brecha FOB)", 0.10, F["ed_pct"], "Brecha FOB sobre la referencia a partir de la cual se marca 'Precio FOB'."),
            ("UMB_FLETE", "Umbral 'pierdo en flete' (puntos de flete+seguro/FOB)", 0.02, F["ed_pct"], "Diferencia de flete+seguro/FOB contra el mejor."),
            ("UMB_DIAS", "Umbral 'pierdo en tiempo' (días)", 7, F["ed_n"], "Días de embarque a DIN de diferencia contra el mejor."),
            ("MESES", "Meses del período filtrado", meses, F["n0"], f"Del filtro del hub ({f['desde']} → {f['hasta']}); para anualizar unidades."),
        ]
        for i, (nombre, etq, val, fmt, src) in enumerate(sup, start=4):
            ws.write(i, 0, etq)
            ws.write(i, 1, val, fmt)
            ws.write(i, 2, src, F["txt"])
            wb.define_name(nombre, f"=Supuestos!$B${i + 1}")
        r_ref = 4 + [s[0] for s in sup].index("REF")
        ws.data_validation(r_ref, 1, r_ref, 1, {"validate": "list", "source": list(REFS)})
        ws.data_validation(r_ref + 1, 1, r_ref + 1, 1, {"validate": "list", "source": list(REFS[:2])})
        ws.write(4 + len(sup) + 1, 0, f"Parámetros de generación (se cambian en el hub antes de descargar): mínimo de unidades para "
                                      f"comparar un importador = {min_unid:,} · banda de precio para 'Mi SKU' = 1/{banda:g} a {banda:g} veces nuestro FOB", F["sub"])

        # ------------------------------------------------ 1 · Mi SKU vs mercado
        ws = wb.add_worksheet("1 · Mi SKU vs mercado")
        # (clave, encabezado, ancho, formato): las fórmulas usan L1[clave] → letra, nunca letras a mano
        cols = [("sku", "SKU", 16, None), ("producto", "Producto", 40, None), ("tipo", "Tipo", 20, None),
                ("categoria", "Categoría", 14, None), ("unidad", "Unidad", 7, None),
                ("unidades", "Unidades compradas (período)", 11, F["n0"]), ("ultimo_embarque", "Último embarque", 11, None),
                ("fob", "Nuestro FOB US$/u (último)", 10, F["usd"]), ("internado_clp", "Nuestro internado CLP/u (último)", 11, F["n0"]),
                ("vendidas_12m", "Vendidas 12m (u) · modelo ROI", 10, F["n0"]),
                ("precio_real", "Precio real neto CLP/u · modelo ROI", 11, F["n0"]),
                ("contrib_pct", "Contribución % · modelo ROI", 9, F["pct"]), ("roi_capital", "ROI s/capital · modelo ROI", 8, F["usd"]),
                ("ux_flete", "Nuestro flete+seguro/FOB (tipo)", 10, F["pct"]), ("ux_dias", "Nuestros días (tipo)", 8, F["n0"]),
                ("n", f"Comparables en banda (1/{banda:g}–{banda:g}× nuestro FOB)", 11, F["n0"]),
                ("p25", "p25 banda US$/u", 10, F["usd"]), ("p50", "Mediana banda US$/u", 10, F["usd"]),
                ("percentil", "% de la banda que compra más barato", 10, F["pct"]),
                ("p50_tipo", "Mediana del tipo completo US$/u (contexto)", 11, F["usd"]),
                ("mejor_importador", "Mejor importador", 28, None), ("mejor_unidades", "Sus unidades", 10, F["n0"]),
                ("mejor_fob_u", "Su FOB US$/u", 9, F["usd"]), ("mejor_cif_u", "Su CIF US$/u", 9, F["usd"]),
                ("mejor_flete_pct", "Su flete+seguro/FOB", 9, F["pct"]), ("mejor_dias", "Sus días", 7, F["n0"]),
                ("mejor_prov", "Su proveedor principal", 22, None), ("mejor_puerto", "Su puerto", 16, None),
                ("mejor_forwarder", "Su forwarder", 20, None), ("mejor_naviera", "Su naviera", 18, None),
                ("mejor_trae", "Qué trae", 50, None), ("tres", "Los 3 más baratos", 60, None)]
        fcols = [("u_anio", "Unidades por año", 10, F["f_usd0"]), ("ref", "FOB referencia US$/u", 10, F["f_usd"]),
                 ("brecha", "Brecha FOB vs referencia", 9, F["f_pct"]), ("ahorro", "Ahorro potencial US$/año", 11, F["f_usd0"]),
                 ("ahorro_clp", "Ahorro potencial CLP/año", 13, F["f_usd0"]), ("pierdo", "Dónde pierdo", 22, F["f_txt"]),
                 ("mg_actual", "Margen bruto actual (1 − internado ÷ precio)", 10, F["f_pct"]),
                 ("mg_extra", "Margen extra si pagara la referencia (pts de venta)", 11, F["f_pct"])]
        L1 = {c[0]: _col(j) for j, c in enumerate(cols + fcols)}
        cols = [c[1:] for c in cols]
        fcols = [c[1:] for c in fcols]
        ws.write(0, 0, "Flujo 1 · Competitividad: mi SKU contra quienes traen el mismo tipo", F["tit"])
        ws.write(1, 0, f"Cada SKU se compara con quienes compran el mismo tipo en SU rango de precio (1/{banda:g} a {banda:g} veces nuestro FOB), "
                       "para no mezclar gamas. Verde = fórmula (depende de Supuestos). Ordenado por ahorro potencial. "
                       "Antes de decidir, revisar 'Qué trae'.", F["sub"])
        H = 3
        for j, (h, wd, _) in enumerate(cols + fcols):
            ws.write(H, j, h, F["h"] if j < len(cols) else F["hf"])
            ws.set_column(j, j, wd)
        t = comparar_skus(nos, comp, min_unid, banda) if len(nos) else pd.DataFrame()
        if len(t):
            t["ux_flete"] = t.tipo.map(ux_t["flete_pct"]) if len(ux_t) else None
            t["ux_dias"] = t.tipo.map(ux_t["dias"]) if len(ux_t) else None
            t["unidad"] = t.tipo.map(comp.groupby("tipo").unidad.first()) if len(comp) else None
            p50 = t["p50"] if "p50" in t else pd.Series(index=t.index, dtype=float)
            t["_ahorro"] = ((t.fob - p50).clip(lower=0) * t.unidades * 12 / meses).fillna(-1)
            t = t.sort_values("_ahorro", ascending=False).reset_index(drop=True)
        claves = [k_ for k_ in L1][:len(cols)]
        for i, r in t.iterrows() if len(t) else []:
            x, n = H + 1 + i, H + 2 + i
            for j, key in enumerate(claves):
                v = _v(r.get(key))
                if v is not None:
                    ws.write(x, j, v, cols[j][2])
            c = {k_: f"{L1[k_]}{n}" for k_ in L1}          # referencia de celda de esta fila por clave
            k = len(cols)
            ws.write_formula(x, k, f'=IF(ISNUMBER({c["unidades"]}),{c["unidades"]}*12/MESES,"")', F["f_usd0"])
            ws.write_formula(x, k + 1, f'=IFERROR(1/(1/CHOOSE(MATCH(REF,{{"Mediana","p25","Mejor importador"}},0),'
                                       f'{c["p50"]},{c["p25"]},{c["mejor_fob_u"]})),"")', F["f_usd"])
            ws.write_formula(x, k + 2, f'=IF(AND(ISNUMBER({c["ref"]}),ISNUMBER({c["fob"]})),IF({c["ref"]}>0,{c["fob"]}/{c["ref"]}-1,""),"")', F["f_pct"])
            ws.write_formula(x, k + 3, f'=IF(AND(ISNUMBER({c["brecha"]}),ISNUMBER({c["u_anio"]})),'
                                       f'MAX(0,{c["fob"]}-{c["ref"]})*{c["u_anio"]},"")', F["f_usd0"])
            ws.write_formula(x, k + 4, f'=IF(ISNUMBER({c["ahorro"]}),{c["ahorro"]}*TC,"")', F["f_usd0"])
            conds = (f'IF({c["brecha"]}>UMB_PRECIO,"Precio FOB","")',
                     f'IF(AND(ISNUMBER({c["ux_flete"]}),ISNUMBER({c["mejor_flete_pct"]})),'
                     f'IF({c["ux_flete"]}-{c["mejor_flete_pct"]}>UMB_FLETE,"Flete",""),"")',
                     f'IF(AND(ISNUMBER({c["ux_dias"]}),ISNUMBER({c["mejor_dias"]})),'
                     f'IF({c["ux_dias"]}-{c["mejor_dias"]}>UMB_DIAS,"Tiempo",""),"")')
            tj = f'_xlfn.TEXTJOIN(" · ",TRUE,{",".join(conds)})'
            ws.write_formula(x, k + 5, f'=IF(ISNUMBER({c["brecha"]}),IF({tj}="","Competitivo",{tj}),"")', F["f_txt"])
            ws.write_formula(x, k + 6, f'=IF(AND(ISNUMBER({c["precio_real"]}),ISNUMBER({c["internado_clp"]})),'
                                       f'IF({c["precio_real"]}>0,1-{c["internado_clp"]}/{c["precio_real"]},""),"")', F["f_pct"])
            # ahorro en CLP por unidad (FOB − referencia, al TC) ÷ precio: puntos de margen que se ganan en cada venta
            ws.write_formula(x, k + 7, f'=IF(AND(ISNUMBER({c["brecha"]}),ISNUMBER({c["precio_real"]})),'
                                       f'IF({c["precio_real"]}>0,MAX(0,{c["fob"]}-{c["ref"]})*TC/{c["precio_real"]},""),"")', F["f_pct"])
        ws.freeze_panes(H + 1, 2)
        ws.autofilter(H, 0, H + max(len(t), 1), len(cols) + len(fcols) - 1)

        # ------------------------------------------------ 2 · Oportunidades
        ws = wb.add_worksheet("2 · Oportunidades")
        cols2 = [("Tipo", 26, None), ("Categoría", 14, None), ("Mirada", 10, None), ("¿Lo traemos?", 8, None),
                 ("CIF UnionX 12m US$", 11, F["usd0"]), ("CIF mercado 12m US$", 13, F["usd0"]), ("CIF 12m año anterior US$", 13, F["usd0"]),
                 ("Unidad", 7, None), ("Unidades mercado 12m", 12, F["n0"]), ("Importadores identificados 12m", 11, F["n0"]),
                 ("Participación top 3", 9, F["pct"]), ("FOB/u p25 US$", 9, F["usd"]), ("FOB/u mediana US$", 9, F["usd"]),
                 ("Flete+seguro/FOB mercado", 9, F["pct"]), ("Días mercado (mediana)", 8, F["n0"]),
                 ("Principales importadores (12m)", 50, None), ("Principales proveedores (12m)", 50, None)]
        fcols2 = [("Crecimiento 12m", 9, F["f_pct"]), ("Precio venta ref. CLP c/IVA (escribir · precargado si lo vendemos)", 14, F["ed_clp"]),
                  ("Costo puesto estimado CLP/u", 12, F["f_usd0"]), ("Margen bruto CLP/u", 11, F["f_usd0"]), ("Margen bruto %", 9, F["f_pct"])]
        ws.write(0, 0, "Flujo 2 · Oportunidad: todo lo que se importa en la categoría (lo traigamos o no)", F["tit"])
        ws.write(1, 0, "Naranjo = precio de venta de referencia: si ya vendemos el tipo viene precargado con nuestro precio real promedio "
                       "12m × IVA (modelo ROI); si no, escríbelo → costo puesto y margen se calculan con los Supuestos. "
                       "Núcleo = en nuestras subpartidas · Adyacente = otros productos en nuestras partidas.", F["sub"])
        for j, (h, wd, _) in enumerate(cols2 + fcols2):
            ws.write(H, j, h, F["h"] if j < len(cols2) else (F["he"] if "escribir" in h else F["hf"]))
            ws.set_column(j, j, wd)
        for i, r in opo.iterrows() if len(opo) else []:
            x, n = H + 1 + i, H + 2 + i
            fila = [r.tipo, r.categoria, r.universo, "Sí" if (r.cif12_ux or 0) > 0 else "No", r.cif12_ux, r.cif12, r.cif12_ant,
                    r.unidad, r.u12, r.n_imp, r.top3, r.get("p25"), r.get("p50"), r.flete_pct, r.dias, r.top_imp, r.top_prov]
            for j, v in enumerate(map(_v, fila)):
                if v is not None:
                    ws.write(x, j, v, cols2[j][2])
            k = len(cols2)
            ws.write_formula(x, k, f"=IF(OR(F{n}=\"\",G{n}=\"\",G{n}=0),\"\",F{n}/G{n}-1)", F["f_pct"])
            pv_ = precio_tipo.get(r.tipo)
            if pv_:   # precargado: nuestro precio real neto promedio × (1 + IVA); editable
                ws.write_formula(x, k + 1, f"={pv_:.0f}*(1+IVA)", F["ed_clp"])
            else:
                ws.write_blank(x, k + 1, None, F["ed_clp"])
            ws.write_formula(x, k + 2, f"=IF(M{n}=\"\",\"\",CHOOSE(MATCH(REF_OP,{{\"Mediana\",\"p25\"}},0),M{n},L{n})*(1+IF(ISNUMBER(N{n}),N{n},0))*TC*(1+INTERNACION))", F["f_usd0"])
            ws.write_formula(x, k + 3, f"=IF(OR({_col(k + 1)}{n}=\"\",{_col(k + 2)}{n}=\"\"),\"\",{_col(k + 1)}{n}/(1+IVA)-{_col(k + 2)}{n})", F["f_usd0"])
            ws.write_formula(x, k + 4, f"=IF({_col(k + 3)}{n}=\"\",\"\",{_col(k + 3)}{n}/({_col(k + 1)}{n}/(1+IVA)))", F["f_pct"])
        ws.freeze_panes(H + 1, 1)
        ws.autofilter(H, 0, H + max(len(opo), 1), len(cols2) + len(fcols2) - 1)

        # ------------------------------------------------ Competidores (tipo × importador)
        ws = wb.add_worksheet("Competidores")
        cols3 = [("Tipo", 22, None), ("Importador", 30, None), ("RUT", 12, None), ("Evidencia", 9, None), ("Es UnionX", 6, None),
                 ("Unidad", 6, None), ("Unidades", 10, F["n0"]), ("FOB US$/u", 9, F["usd"]), ("CIF US$/u", 9, F["usd"]),
                 ("Precio plausible", 7, None), ("CIF US$", 12, F["usd0"]), ("DIN", 6, F["n0"]), ("Lote (u por DIN)", 9, F["n0"]),
                 ("Meses activos", 7, F["n0"]), ("Último mes", 8, None), ("Flete+seguro/FOB", 9, F["pct"]), ("Días BL→DIN", 7, F["n0"]),
                 ("Vía", 10, None), ("Modalidad", 18, None), ("Puerto embarque", 18, None), ("País origen", 12, None),
                 ("Forwarder", 22, None), ("Naviera", 20, None), ("Proveedor principal", 22, None), ("% CIF del proveedor", 8, F["pct"]),
                 ("Qué trae", 60, None), ("CIF total de la empresa US$ (todos sus productos)", 14, F["usd0"])]
        fcols3 = [("FOB/u UnionX (mismo tipo)", 9, F["f_usd"]), ("Brecha precio vs UnionX", 9, F["f_pct"]),
                  ("Flete UnionX (mismo tipo)", 9, F["f_pct"]), ("Brecha flete vs UnionX (pts)", 9, F["f_pct"]),
                  ("Días UnionX (mismo tipo)", 8, F["f_n"]), ("Brecha días vs UnionX", 8, F["f_n"])]
        ws.write(0, 0, "Competidores por tipo de producto: precio, volumen, logística y a quién compran", F["tit"])
        ws.write(1, 0, "Filtra 'Tipo' con el autofiltro. Brecha negativa = el otro lo hace mejor que UnionX (más barato, menos flete, menos días).", F["sub"])
        for j, (h, wd, _) in enumerate(cols3 + fcols3):
            ws.write(H, j, h, F["h"] if j < len(cols3) else F["hf"])
            ws.set_column(j, j, wd)
        ultima = H + len(comp)
        rng = lambda c: f"${c}${H + 2}:${c}${ultima + 1}"   # noqa: E731
        for i, r in comp.iterrows():
            x, n = H + 1 + i, H + 2 + i
            fila = [r.tipo, r.importador, r.rut_fmt, {"rut": "RUT", "verificada": "Verificada", "probable": "Probable"}.get(r.nivel, r.nivel),
                    "Sí" if r.es_ux else "No", r.unidad, r.unidades, r.fob_u, r.cif_u, "Sí" if r.plausible else "No", r.cif,
                    r.n_din, r.lote, r.meses, r.ultimo_mes, r.flete_pct, r.dias, r.via, r.modalidad, r.puerto, r.pais,
                    r.forwarder, r.naviera, r.prov, r.prov_pct, r.trae, r.get("cif_total")]
            for j, v in enumerate(map(_v, fila)):
                if v is not None:
                    ws.write(x, j, v, F["ux"] if (r.es_ux and j == 1) else cols3[j][2])
            k = len(cols3)
            ws.write_formula(x, k, f"=IFERROR(AVERAGEIFS({rng('H')},{rng('A')},A{n},{rng('E')},\"Sí\"),\"\")", F["f_usd"])
            ws.write_formula(x, k + 1, f"=IF(OR({_col(k)}{n}=\"\",NOT(ISNUMBER(H{n}))),\"\",H{n}/{_col(k)}{n}-1)", F["f_pct"])
            ws.write_formula(x, k + 2, f"=IFERROR(AVERAGEIFS({rng('P')},{rng('A')},A{n},{rng('E')},\"Sí\"),\"\")", F["f_pct"])
            ws.write_formula(x, k + 3, f"=IF(OR({_col(k + 2)}{n}=\"\",NOT(ISNUMBER(P{n}))),\"\",P{n}-{_col(k + 2)}{n})", F["f_pct"])
            ws.write_formula(x, k + 4, f"=IFERROR(AVERAGEIFS({rng('Q')},{rng('A')},A{n},{rng('E')},\"Sí\"),\"\")", F["f_n"])
            ws.write_formula(x, k + 5, f"=IF(OR({_col(k + 4)}{n}=\"\",NOT(ISNUMBER(Q{n}))),\"\",Q{n}-{_col(k + 4)}{n})", F["f_n"])
        ws.freeze_panes(H + 1, 2)
        ws.autofilter(H, 0, H + max(len(comp), 1), len(cols3) + len(fcols3) - 1)

        # ------------------------------------------------ 3 · Logística (por importador, todos los tipos filtrados)
        ws = wb.add_worksheet("3 · Logística")
        lg = logistica if logistica is not None else pd.DataFrame()
        cols4 = [("Importador", 34, None), ("DIN", 7, F["n0"]), ("Flete+seguro/FOB", 10, F["pct"]), ("Días BL→DIN (mediana)", 9, F["n0"]),
                 ("Forwarder principal", 26, None), ("Naviera principal", 24, None), ("Puerto principal", 22, None),
                 ("Modalidad principal", 20, None), ("CIF productos US$", 13, F["usd0"])]
        fcols4 = [("Brecha flete vs UnionX (pts)", 10, F["f_pct"]), ("Brecha días vs UnionX", 9, F["f_n"])]
        ws.write(0, 0, "Flujo 3 · Logística: flete y tiempo de cada importador en los productos filtrados, contra UnionX", F["tit"])
        ws.write(1, 0, "Para el detalle por tipo de producto (lo justo para comparar), usar la hoja Competidores.", F["sub"])
        for j, (h, wd, _) in enumerate(cols4 + fcols4):
            ws.write(H, j, h, F["h"] if j < len(cols4) else F["hf"])
            ws.set_column(j, j, wd)
        if len(lg):
            lg = lg.sort_values("CIF productos (US$)", ascending=False).reset_index(drop=True)
            fila_ux = next((H + 2 + i for i, nm in enumerate(lg["Importador"]) if str(nm).startswith("UnionX")), None)
            for i, r in lg.iterrows():
                x, n = H + 1 + i, H + 2 + i
                vals = [r["Importador"], r["DIN"], r["Flete+seguro / FOB"], r["Días embarque→DIN (mediana)"], r["Forwarder principal"],
                        r["Naviera principal"], r["Puerto principal"], r["Modalidad principal"], r["CIF productos (US$)"]]
                for j, v in enumerate(map(_v, vals)):
                    if v is not None:
                        ws.write(x, j, v, F["ux"] if (fila_ux == n and j == 0) else cols4[j][2])
                if fila_ux:
                    ws.write_formula(x, len(cols4), f"=IF(OR(NOT(ISNUMBER(C{n})),NOT(ISNUMBER($C${fila_ux}))),\"\",C{n}-$C${fila_ux})", F["f_pct"])
                    ws.write_formula(x, len(cols4) + 1, f"=IF(OR(NOT(ISNUMBER(D{n})),NOT(ISNUMBER($D${fila_ux}))),\"\",D{n}-$D${fila_ux})", F["f_n"])
            ws.autofilter(H, 0, H + len(lg), len(cols4) + len(fcols4) - 1)
        ws.freeze_panes(H + 1, 1)

        # ------------------------------------------------ Proveedores
        ws = wb.add_worksheet("Proveedores")
        cols5 = [("Tipo", 22, None), ("Proveedor", 30, None), ("Fábrica / trading (indicativo)", 16, None), ("País origen", 12, None),
                 ("Puerto principal", 18, None), ("Importadores que le compran", 9, F["n0"]), ("Principales importadores", 50, None),
                 ("Unidad", 6, None), ("Unidades", 10, F["n0"]), ("FOB US$/u", 9, F["usd"]), ("CIF US$", 12, F["usd0"]),
                 ("¿UnionX le compra?", 8, None), ("Buscar (Google)", 10, None), ("Buscar (Alibaba)", 10, None)]
        ws.write(0, 0, "Con quién compra el mercado: proveedores declarados por tipo de producto", F["tit"])
        ws.write(1, 0, "Proveedor = vendedor extranjero declarado en la DIN (fábrica o trading/agente), NO el forwarder. Nombre normalizado "
                       "(SHENZHEN TOPWILL = TOPWILL). Los links abren una búsqueda para ubicar el contacto: verificar antes de escribir.", F["sub"])
        for j, (h, wd, _) in enumerate(cols5):
            ws.write(H, j, h, F["h"])
            ws.set_column(j, j, wd)
        for i, r in prov.iterrows() if len(prov) else []:
            x = H + 1 + i
            vals = [r.tipo, r.proveedor, r.ptipo, r.pais, r.puerto, r.n_imp, r.imps, r.unidad, r.u, r.fob_u, r.cif, "Sí" if r.ux else "No"]
            for j, v in enumerate(map(_v, vals)):
                if v is not None:
                    ws.write(x, j, v, cols5[j][2])
            nom = str(r.proveedor).replace(" (solo ciudad)", "")
            gq = urllib.parse.quote_plus(f"{nom} {r.tipo} manufacturer China")
            aq = urllib.parse.quote_plus(nom)
            ws.write_url(x, 12, f"https://www.google.com/search?q={gq}", string="Google")
            ws.write_url(x, 13, f"https://www.alibaba.com/trade/search?SearchText={aq}", string="Alibaba")
        ws.freeze_panes(H + 1, 2)
        ws.autofilter(H, 0, H + max(len(prov), 1), len(cols5) - 1)

        # ------------------------------------------------ Sábana
        if sabana is not None:
            sabana.to_excel(xw, sheet_name="Sábana", index=False)
            ws = xw.sheets["Sábana"]
            ws.freeze_panes(1, 0)
            for j, col in enumerate(sabana.columns):
                largo = sabana[col].astype(str).str.len().quantile(0.9) if len(sabana) else 10
                ws.set_column(j, j, int(min(max(len(str(col)), largo) + 2, 44)))
            if len(sabana):
                ws.autofilter(0, 0, len(sabana), len(sabana.columns) - 1)
    return buf.getvalue()


# ---------------------------------------------------------------- Tamaño de empresas (pestaña del hub)
def tamano(rk: pd.DataFrame, rubros: pd.DataFrame, partidas: pd.DataFrame, capitulos: dict, meses: int,
           ux: str, filtros_txt: list, cobertura_txt: str, con_rubro: bool = False) -> bytes:
    """Ranking de empresas por TODO lo que importan (todos sus productos) + rubros y partidas de las más grandes.
    rk: salida de _ranking_empresas del hub (una fila por empresa, ordenada por puesto). con_rubro: el ranking
    se ordenó por el CIF en los rubros filtrados (agrega esa columna)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        wb = xw.book
        F = {
            "tit": wb.add_format({"bold": True, "font_size": 14, "font_color": "#1F3864"}),
            "sub": wb.add_format({"italic": True, "font_color": "#595959"}),
            "h": wb.add_format({"bold": True, "bg_color": "#1F3864", "font_color": "white", "text_wrap": True, "valign": "top", "border": 1}),
            "hf": wb.add_format({"bold": True, "bg_color": "#375623", "font_color": "white", "text_wrap": True, "valign": "top", "border": 1}),
            "usd0": wb.add_format({"num_format": "#,##0"}), "n0": wb.add_format({"num_format": "#,##0"}),
            "pct": wb.add_format({"num_format": "0.0%"}), "b": wb.add_format({"bold": True}),
            "txt": wb.add_format({"text_wrap": True, "valign": "top"}),
            "f_usd0": wb.add_format({"num_format": "#,##0", "bg_color": "#EAF1DD"}),
            "f_pct": wb.add_format({"num_format": "0.0%", "bg_color": "#EAF1DD"}),
            "f_x": wb.add_format({"num_format": "0.0\"×\"", "bg_color": "#EAF1DD"}),
            "ed": wb.add_format({**NARANJO, "num_format": "#,##0"}),
            "ux": wb.add_format({"bold": True, "font_color": "#C00000"}),
        }
        # ------------------------------------------------ Léeme
        ws = wb.add_worksheet("Léeme")
        ws.set_column(0, 0, 34); ws.set_column(1, 1, 110)
        ws.write(0, 0, "Radar de Importaciones — Tamaño de empresas", F["tit"])
        ws.write(1, 0, f"Generado {datetime.now():%d-%m-%Y %H:%M} · DIN públicas de Aduana (datos.gob.cl)", F["sub"])
        filas = [
            ("QUÉ RESPONDE", ""),
            ("Ranking", "Cuánto importa cada empresa en el período con TODOS sus productos (no solo lo que compite con lo "
             "nuestro): CIF, DIN, meses con importaciones, rubro principal, cuánto de eso es de nuestros tipos de producto "
             "(núcleo) y cuántas veces el tamaño de UnionX. Sirve para dimensionar a un competidor, cliente o proveedor."),
            ("Rubros", "Para las 300 empresas más grandes del ranking: su CIF por capítulo del arancel (85 = aparatos "
             "eléctricos y electrónicos, 94 = muebles e iluminación, 95 = juguetes y deporte, …)."),
            ("Partidas", "Para las mismas 300: sus 10 partidas (4 dígitos) de mayor CIF, con un producto de ejemplo."),
            ("", ""),
            ("CÓMO SE LEE", ""),
            ("Montos = piso", "Aduana publica al importador anonimizado; la empresa se reconstruye mes a mes con códigos trazadores. "
             "Lo que traiga sin identificar no se le atribuye: el tamaño real puede ser algo mayor, nunca menor."),
            ("Evidencia", "Se asigna mes a mes y aquí se pondera por el CIF del período: Verificada = ≥90% de su CIF en meses "
             "amarrados al RUT (declarado en jun-2024) por ≥2 códigos trazadores · Probable = hay meses enganchados por 1 código "
             "+ misma comuna o por sus marcas propias (entre paréntesis, cuánto está verificado) · Trazado = misma empresa mes "
             "a mes, sin RUT (no tiene nombre)."),
            ("CIF", "Costo + seguro + flete en US$, MEDIDO en la DIN. Columnas verdes = fórmula."),
            ("Cobertura", cobertura_txt),
            ("", ""),
            ("FILTROS AL GENERAR", ""),
        ] + [(a, b) for a, b in filtros_txt]
        for i, (a, b) in enumerate(filas, start=3):
            ws.write(i, 0, a, F["b"] if b == "" and a else None)
            ws.write(i, 1, b, F["txt"])
        x = 4 + len(filas)
        ws.write(x, 0, "Meses del período", F["b"]); ws.write(x, 1, meses, F["ed"])
        wb.define_name("MESES", f"='Léeme'!$B${x + 1}")
        ux_rut = rk.loc[rk.importador_key == ux, "rut_fmt"]
        ws.write(x + 1, 0, "CIF total UnionX en el período", F["b"])
        ws.write_formula(x + 1, 1, f"=SUMIFS(Ranking!$E:$E,Ranking!$C:$C,\"{ux_rut.iloc[0] if len(ux_rut) else '76.600.685-K'}\")", F["f_usd0"])
        wb.define_name("UX_CIF", f"='Léeme'!$B${x + 2}")

        # ------------------------------------------------ Ranking
        ws = wb.add_worksheet("Ranking")
        H = 3
        cols = [("Puesto", 7, F["n0"]), ("Empresa", 40, None), ("RUT", 13, None), ("Evidencia", 10, None),
                ("CIF total US$ (todos sus productos)", 15, F["usd0"]), ("DIN", 7, F["n0"]),
                ("Meses con importaciones", 9, F["n0"])]
        if con_rubro:
            cols.append(("CIF en el rubro filtrado US$", 14, F["usd0"]))
        cols += [("Rubro principal", 30, None), ("% del rubro principal", 9, F["pct"]),
                 ("CIF en nuestros tipos de producto US$ (núcleo)", 14, F["usd0"]), ("Var. ene–mes vs año anterior", 10, F["pct"])]
        fcols = [("Promedio mensual US$", 13, F["f_usd0"]), ("% en nuestros productos", 10, F["f_pct"]),
                 ("Veces el tamaño de UnionX", 10, F["f_x"])]
        ws.write(0, 0, "Tamaño de empresas: todo lo que importa cada una en el período", F["tit"])
        ws.write(1, 0, "Ordenado por CIF" + (" en el rubro filtrado" if con_rubro else " total") + ". UnionX en rojo. "
                 "Columnas verdes = fórmula (Léeme: MESES y UX_CIF).", F["sub"])
        for j, (h, wd, _) in enumerate(cols + fcols):
            ws.write(H, j, h, F["h"] if j < len(cols) else F["hf"])
            ws.set_column(j, j, wd)
        c_tot, c_nuc = "E", _col(len(cols) - 2)
        niv = {"rut": "RUT", "verificada": "Verificada", "probable": "Probable", "trazado": "Trazado"}
        for i, r in enumerate(rk.itertuples()):
            x_, n = H + 1 + i, H + 2 + i
            ev = niv.get(r.nivel, r.nivel)
            if r.nivel == "probable" and pd.notna(getattr(r, "pct_alta", None)):
                ev += f" ({100 * r.pct_alta:.0f}% verificado)"
            fila = [r.puesto, r.importador, r.rut_fmt, ev, r.cif_total, r.din, r.meses]
            if con_rubro:
                fila.append(r.cif_rubro)
            fila += [f"{r.hs2_top} · {capitulos.get(r.hs2_top, '')}" if isinstance(r.hs2_top, str) else None,
                     r.pct_top, r.cif_nuestro, r.var]
            for j, v in enumerate(map(_v, fila)):
                if v is not None:
                    ws.write(x_, j, v, F["ux"] if (r.importador_key == ux and j == 1) else cols[j][2])
            k = len(cols)
            ws.write_formula(x_, k, f"={c_tot}{n}/MESES", F["f_usd0"])
            ws.write_formula(x_, k + 1, f"=IF({c_tot}{n}>0,N({c_nuc}{n})/{c_tot}{n},\"\")", F["f_pct"])
            ws.write_formula(x_, k + 2, f"=IF(UX_CIF>0,{c_tot}{n}/UX_CIF,\"\")", F["f_x"])
        ws.freeze_panes(H + 1, 2)
        ws.autofilter(H, 0, H + max(len(rk), 1), len(cols) + len(fcols) - 1)

        # ------------------------------------------------ Rubros (top 300)
        nom = dict(zip(rk.importador_key, rk.importador))
        rut = dict(zip(rk.importador_key, rk.rut_fmt))
        ws = wb.add_worksheet("Rubros")
        cols2 = [("Empresa", 40, None), ("RUT", 13, None), ("Capítulo", 8, None), ("Rubro", 36, None), ("CIF US$", 14, F["usd0"])]
        ws.write(0, 0, "Rubros de las 300 empresas más grandes del ranking (capítulo del arancel)", F["tit"])
        for j, (h, wd, _) in enumerate(cols2 + [("% de la empresa", 10, None)]):
            ws.write(H, j, h, F["h"] if j < len(cols2) else F["hf"])
            ws.set_column(j, j, wd)
        ult = H + 1 + len(rubros)
        for i, r in enumerate(rubros.itertuples()):
            x_, n = H + 1 + i, H + 2 + i
            for j, v in enumerate(map(_v, [nom.get(r.importador_key), rut.get(r.importador_key), r.hs2,
                                           capitulos.get(r.hs2, ""), r.cif])):
                if v is not None:
                    ws.write(x_, j, v, cols2[j][2])
            ws.write_formula(x_, 5, f"=E{n}/SUMIFS($E${H + 2}:$E${ult},$A${H + 2}:$A${ult},A{n})", F["f_pct"])
        ws.freeze_panes(H + 1, 1)
        ws.autofilter(H, 0, H + max(len(rubros), 1), len(cols2))

        # ------------------------------------------------ Partidas (top 300 × top 10)
        ws = wb.add_worksheet("Partidas")
        cols3 = [("Empresa", 40, None), ("RUT", 13, None), ("Partida (4 díg.)", 9, None), ("Rubro", 30, None),
                 ("Producto de ejemplo", 44, None), ("CIF US$", 14, F["usd0"])]
        ws.write(0, 0, "Qué importa cada una: sus 10 partidas de mayor CIF en el período", F["tit"])
        for j, (h, wd, _) in enumerate(cols3):
            ws.write(H, j, h, F["h"])
            ws.set_column(j, j, wd)
        for i, r in enumerate(partidas.itertuples()):
            for j, v in enumerate(map(_v, [nom.get(r.importador_key), rut.get(r.importador_key), r.hs4,
                                           capitulos.get(str(r.hs4)[:2], ""), r.ejemplo, r.cif])):
                if v is not None:
                    ws.write(H + 1 + i, j, v, cols3[j][2])
        ws.freeze_panes(H + 1, 1)
        ws.autofilter(H, 0, H + max(len(partidas), 1), len(cols3) - 1)
    return buf.getvalue()
