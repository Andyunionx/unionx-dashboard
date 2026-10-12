"""Evaluador de productos (Agente Producto) — pedido de Sebastián Guzmán, 9-oct-2026.

Flujo por link (Andrés 9-oct): pegas el link de un producto (competencia en Chile, marketplace o proveedor de cualquier
parte) y:
  1. lee el producto y busca en TODA la DIN quién lo importa, a qué FOB y de qué marca/fábrica;
  2. obliga a poner el costo de compra o el PVP (al menos uno), propuestos desde el link o el FOB de la competencia;
  3. pide el resto de las partidas (lote, caja, flete, velocidad, mix…), con supuestos por defecto trazados;
  4. evalúa: veredicto, con este costo → PVP ideal, con este PVP → costo máximo, ROI del lote, competencia, Excel.
Costo internado = precosteo COMEX · contribución, capital y EVA = ROI por producto · comisión y logística = RAW real de la
categoría · marketing lineal 3%. El cálculo vive en agente-producto/ (validado: Excel = Python).
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

_AGENTE = Path(__file__).resolve().parent.parent / "agente-producto"
if str(_AGENTE) not in sys.path:
    sys.path.insert(0, str(_AGENTE))
import informe as INF  # noqa: E402
import link_producto as LP  # noqa: E402
import motor as M  # noqa: E402
import radar_cruce as R  # noqa: E402

PUERTOS = ["Shenzhen", "Ningbo", "Xiamen", "Qingdao", "Otro"]
MODALIDADES = ["Consolidado", "Contenedor propio", "LCL"]
COLOR = {"COMPRAR": "#1E6B5C", "NEGOCIAR": "#B5651D", "NO COMPRAR": "#B42318", "PRECIO OBJETIVO": "#1F3864",
         "COSTO OBJETIVO": "#1F3864", "NO VIABLE": "#B42318"}
ROL_TXT = {"pvp": "PVP de mercado (tienda chilena)", "costo": "costo de proveedor",
           "referencia": "precio de venta en el extranjero (solo referencia)"}


def clp(x):
    return "—" if x is None else f"${x:,.0f}".replace(",", ".")


def usd(x):
    return "—" if x is None or x != x else f"US${x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, d=1):
    return "—" if x is None else f"{x * 100:.{d}f}%".replace(".", ",")


def miles(x):
    return "—" if x is None or x != x else f"{x:,.0f}".replace(",", ".")


@st.cache_data(ttl=3600, show_spinner=False)
def _par():
    return M.cargar_parametros()


@st.cache_data(ttl=600, show_spinner=False, max_entries=30)
def _leer(url: str) -> dict:
    return LP.leer(url)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def _buscar(terminos: tuple, fuertes: tuple) -> dict:
    return R.buscar_terminos(list(terminos), list(fuertes))


@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def _similares(q: str) -> pd.DataFrame:
    return M.buscar_similares(q)


def _kg_del_nombre(nombre: str) -> float | None:
    """Contenido por unidad leído del nombre: '1Kg', '500 g', '2,5 kg'."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(KG|KILO|GRS|GR|G)\b", LP._sin_tilde(str(nombre or "")).upper())
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v if m.group(2).startswith("K") else v / 1000


# ── Paso 1: link → ficha técnica + origen → quién lo importa (ranking por similitud) ─────────────
@st.cache_data(ttl=1800, show_spinner=False, max_entries=30)
def _leer_completo(url: str) -> dict:
    return LP.leer_completo(url)


@st.cache_data(ttl=86400, show_spinner=False, max_entries=50)
def _ficha_ia(clave: str, link: dict) -> dict | None:
    import ia_producto as IA
    try:
        return IA.ficha(link)
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {str(e)[:150]}"}


@st.cache_data(ttl=86400, show_spinner=False, max_entries=30)
def _origen_ia(clave: str, ficha: dict, url: str | None) -> dict | None:
    import ia_producto as IA
    try:
        return IA.investigar_origen(ficha, url)
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {str(e)[:150]}"}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=30)
def _rank_ia(clave: str, ficha: dict, filas: tuple) -> dict | None:
    import ia_producto as IA
    try:
        return IA.rankear(ficha, [dict(f) for f in filas])
    except Exception:  # noqa: BLE001
        return None


def _ficha(link: dict) -> dict:
    """Ficha técnica: IA si hay API key; si no, patrones sobre la página y los PDF."""
    import ia_producto as IA
    pat = link.get("ficha_patrones") or {}
    base = {"nombre": link.get("nombre"), "marca": link.get("marca"), "terminos_aduana": link.get("terminos") or [],
            "especificaciones": {k: v for k, v in pat.items() if k in ("potencia_w", "capacidad_ml", "voltaje", "medidas_mm", "peso_kg")},
            "origen": pat.get("origen"), "fabricante_texto": pat.get("fabricante_texto"), "_fuente": "patrones (sin IA)"}
    if not IA.disponible():
        return base
    f = _ficha_ia(link.get("url") or link.get("nombre"), {k: v for k, v in link.items() if k != "imagen"})
    if not f or f.get("_error"):
        base["_fuente"] = f"patrones (la IA falló: {(f or {}).get('_error', 'sin respuesta')})"
        return base
    f.setdefault("especificaciones", {})
    for k, v in base["especificaciones"].items():          # lo que la IA no trajo, desde los patrones
        f["especificaciones"].setdefault(k, v)
    f["_fuente"] = "IA (Claude) sobre la página y sus PDF"
    return f


def _mostrar_ficha(f: dict, link: dict):
    esp = f.get("especificaciones") or {}
    filas = [("Tipo de producto", f.get("tipo_producto")), ("Marca", f.get("marca")), ("Dueño de la marca", f.get("dueno_marca")),
             ("Potencia", f"{esp['potencia_w']:g} W" if esp.get("potencia_w") else None),
             ("Capacidad", f"{esp['capacidad_ml']:g} ml" if esp.get("capacidad_ml") else None), ("Voltaje", esp.get("voltaje")),
             ("Medidas", " × ".join(f"{x:g}" for x in esp["medidas_mm"]) + " mm" if esp.get("medidas_mm") else None),
             ("Peso", f"{esp['peso_kg']:g} kg" if esp.get("peso_kg") else None),
             ("Materiales", ", ".join(esp.get("materiales") or []) or None), ("Funciones", ", ".join(esp.get("funciones") or []) or None),
             ("Colores", ", ".join(esp.get("colores") or []) or None), ("Certificaciones", ", ".join(esp.get("certificaciones") or []) or None),
             ("Origen", f.get("origen")), ("Fabricante (literal en el texto)", f.get("fabricante_texto")),
             ("Modelo de fábrica", f.get("modelo_fabrica")), ("Partida probable", f.get("partida_probable")),
             ("Como se declara en aduana", ", ".join(f.get("terminos_aduana") or []) or None)]
    filas = [(k, str(v)) for k, v in filas if v not in (None, "", [])]
    st.dataframe(pd.DataFrame(filas, columns=["Dato", "Valor"]), hide_index=True, width="stretch")
    st.caption(f"Ficha leída por {f.get('_fuente')}. PDF del sitio leídos: {len(link.get('pdfs') or [])}.")


def _mostrar_origen(o: dict):
    if o.get("_error"):
        st.warning(f"La investigación falló: {o['_error']}")
        return
    fc = o.get("fabricante_confirmado") or {}
    if fc.get("nombre"):
        st.success(f"Fabricante con evidencia directa: **{fc['nombre']}** — {fc.get('evidencia', '')} {fc.get('url', '')}")
    else:
        st.info("Ningún documento público nombra al fabricante: abajo, candidatos por nivel de coincidencia (no confirmados).")
    c = pd.DataFrame(o.get("candidatos") or [])
    if len(c):
        st.dataframe(c[[x for x in ("nombre", "ciudad", "tipo", "modelo", "coincidencia", "fob_min_usd", "fob_max_usd", "moq", "evidencia", "url")
                        if x in c]], hide_index=True, width="stretch")
    co = o.get("costo_origen_usd") or {}
    if co.get("min") or co.get("max"):
        st.markdown(f"**Costo de origen estimado:** {usd(co.get('min'))} – {usd(co.get('max'))} FOB ({co.get('base', '')})")
    if o.get("notas"):
        st.caption(o["notas"])


def _paso1():
    ss = st.session_state
    st.subheader("1 · Pega el link del producto")
    c1, c2 = st.columns([4, 1])
    url = c1.text_input("Link", key="ev_url", label_visibility="collapsed",
                        placeholder="https://… (competencia en Chile, Mercado Libre, proveedor en China, tienda extranjera)")
    if c2.button("Leer link", type="primary", width="stretch") and url.strip():
        with st.spinner("Leyendo la página y sus PDF…"):
            ss["ev_link"] = _leer_completo(url.strip())
        ss.pop("ev_resultado", None)
    with st.expander("No tengo link (o el sitio no se deja leer): escribir el producto"):
        c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
        n = c1.text_input("Producto", key="ev_m_nombre")
        mca = c2.text_input("Marca", key="ev_m_marca")
        pr = c3.number_input("Precio", value=None, min_value=0.0, key="ev_m_precio")
        mon = c4.selectbox("Moneda", ["CLP", "USD"], key="ev_m_moneda")
        if st.button("Usar estos datos") and n.strip():
            d = {"url": None, "tienda": "manual", "nombre": n, "marca": mca or None, "precio": pr, "moneda": mon, "sku": None,
                 "gtin": None, "imagen": None, "descripcion": "", "fuente_dato": "ingreso manual", "error": None,
                 "rol_precio": "pvp" if mon == "CLP" else "costo", "texto_pagina": n, "pdfs": [], "texto_pdfs": "",
                 "ficha_patrones": LP.ficha_por_patrones(n)}
            d["terminos"] = LP.terminos(d)
            ss["ev_link"] = d
            ss.pop("ev_resultado", None)
    link = ss.get("ev_link")
    if not link:
        return None
    clave = link.get("url") or link.get("nombre")
    if link.get("error"):
        st.warning(f"{link['error'][0].upper() + link['error'][1:]}. Completa lo que falte a mano (arriba).")
    c1, c2 = st.columns([1, 4])
    if link.get("imagen"):
        try:
            c1.image(link["imagen"], width=150)
        except Exception:  # noqa: BLE001
            pass
    c2.markdown(f"**{link.get('nombre') or '—'}**  \nMarca: {link.get('marca') or '—'} · tienda: {link.get('tienda')} · "
                f"código: {link.get('sku') or '—'}{(' · EAN ' + str(link['gtin'])) if link.get('gtin') else ''}")
    if link.get("precio"):
        precio_txt = clp(link["precio"]) if link.get("moneda") == "CLP" else f"{link.get('moneda') or ''} {miles(link['precio'])}"
        c2.markdown(f"Precio: **{precio_txt}** — {ROL_TXT.get(link.get('rol_precio'), '')} · leído de {link.get('fuente_dato')}")
    # ficha técnica y origen
    with st.spinner("Armando la ficha técnica…"):
        ficha = _ficha(link)
    ss["ev_ficha"] = ficha
    t1, t2 = st.tabs(["Ficha técnica", "Origen y fabricación"])
    with t1:
        _mostrar_ficha(ficha, link)
    with t2:
        import ia_producto as IA
        if not IA.disponible():
            st.info("La investigación de origen usa IA (Claude con búsqueda web): falta la API key (ANTHROPIC_API_KEY en los Secrets).")
        else:
            if st.button("Investigar origen y fabricación (1–2 minutos)", key=f"ev_inv_{clave}"):
                with st.spinner("Buscando fábrica, candidatos y costo de origen en la web…"):
                    ss[f"ev_origen_{clave}"] = _origen_ia(clave, {k: v for k, v in ficha.items() if not k.startswith("_")}, link.get("url"))
            if ss.get(f"ev_origen_{clave}"):
                _mostrar_origen(ss[f"ev_origen_{clave}"])
    # búsqueda en la DIN + ranking por similitud con la ficha
    st.markdown("**Quién trae el producto más parecido (DIN, últimos 12 meses, ordenado por similitud con la ficha)**")
    c1, c2 = st.columns([3, 2])
    terms_def = ficha.get("terminos_aduana") or link.get("terminos") or []
    terms_txt = c1.text_input("Palabras de búsqueda (separadas por coma; edítalas si hace falta)", value=", ".join(terms_def), key=f"ev_terms_{clave}")
    fuertes_txt = c2.text_input("Marca o modelo (pesan más)", value=LP._sin_tilde(ficha.get("marca") or link.get("marca") or "").upper(),
                                key=f"ev_fuertes_{clave}")
    terms = tuple(t.strip() for t in terms_txt.split(",") if t.strip())
    fuertes = tuple(t.strip() for t in fuertes_txt.split(",") if t.strip())
    base = {"link": link, "ficha": ficha, "res": None, "ref": None, "fuertes": fuertes}
    if not terms:
        return base
    with st.spinner("Buscando en la DIN y comparando con la ficha…"):
        res = _buscar(terms, fuertes)
    base["res"] = res
    d = res.get("filas")
    if d is None or d.empty:
        st.info("No encontré importaciones con esas palabras. Prueba con el nombre genérico en español (como se declara en aduana) o sin la marca.")
        return base
    d = R.rankear_similitud(d[~d.es_unionx], ficha, list(terms))
    if d.empty:
        st.info("Solo encontré importaciones nuestras con esas palabras.")
        return base
    import ia_producto as IA
    if IA.disponible():                                   # la IA afina el ranking de las 30 primeras (datos públicos de la DIN)
        top = d.head(30)
        filas = tuple(tuple({"i": int(i), "glosa": r.glosa, "partida": r.arancel, "unidad": r.unidad,
                             "kg_u": round(float(r.kg_u), 2) if r.kg_u == r.kg_u else None,
                             "fob_u": round(float(r.fob_u), 2) if r.fob_u == r.fob_u else None}.items()) for i, r in top.iterrows())
        rk = _rank_ia(clave, {k: v for k, v in ficha.items() if not k.startswith("_")}, filas)
        if rk:
            d["sim_ia"] = d.index.map(lambda i: (rk.get(i) or {}).get("similitud"))
            d["razon"] = [((rk.get(i) or {}).get("razon") or r) for i, r in zip(d.index, d.razon)]
            d["similitud"] = [round((a + b) / 2) if b == b and b is not None else a for a, b in zip(d.similitud, d.sim_ia)]
            d = d.sort_values(["similitud", "cantidad"], ascending=False)
    d = d.reset_index(drop=True)
    pr = res.get("precios", {})
    if pr:
        st.caption("FOB en las partidas más probables (" + ", ".join(res["partidas"]) + "): " + " · ".join(
            f"por {u.lower()}: p25 {usd(v['p25'])} · mediana {usd(v['p50'])} · p75 {usd(v['p75'])} ({miles(v['cantidad'])} {u.lower()})"
            for u, v in pr.items()))
    vista = d.assign(FOB=d.fob_u.map(usd), kgu=d.kg_u.map(lambda x: "—" if x is None or x != x else f"{x:.2f}"),
                     cant=d.cantidad.map(miles), ult=d.ultima.astype(str).str[:10])
    st.dataframe(vista[["similitud", "importador", "nivel", "glosa", "fabricante", "unidad", "cant", "kgu", "FOB", "ult", "razon"]]
                 .rename(columns={"nivel": "evidencia", "fabricante": "productor", "cant": "cantidad", "kgu": "kg/u", "ult": "última",
                                  "razon": "por qué"}),
                 hide_index=True, width="stretch", height=300)
    st.caption("Similitud 0–100 con la ficha (tipo, marca/modelo, capacidad, potencia y kg por unidad"
               + (", afinada con IA" if IA.disponible() else "") + "). Importador inferido: cada fila trae su nivel de evidencia.")
    et = [f"[{r.similitud}] {r.importador[:24]} · {r.glosa[:44]} · {usd(r.fob_u)}/{r.unidad.lower()} · {miles(r.cantidad)} {r.unidad.lower()}"
          for r in d.itertuples()]
    i = st.selectbox("Producto de referencia de la competencia (fija la partida y la comparación)", range(len(d)),
                     format_func=lambda k: et[k], key=f"ev_ref_{clave}")
    r = d.iloc[i]
    base["ref"] = {"partida": r.arancel, "unidad": r.unidad, "fob_u": float(r.fob_u) if r.fob_u == r.fob_u else None,
                   "importador": r.importador, "fabricante": r.fabricante, "glosa": r.glosa,
                   "kg_u": float(r.kg_u) if r.kg_u == r.kg_u and r.kg_u else None}
    return base


# ── Paso 2: costo o PVP (obligatorio) ───────────────────────────────────────
def _paso2(p1: dict):
    ss = st.session_state
    st.subheader("2 · Costo o PVP (al menos uno)")
    link, ref = p1["link"], p1.get("ref")
    clave = link.get("url") or link.get("nombre")
    kg_nombre = _kg_del_nombre(link.get("nombre"))
    k_pvp, k_cos, k_inc = f"ev_pvp_{clave}", f"ev_costo_{clave}", f"ev_inc_{clave}"
    if k_pvp not in ss:
        ss[k_pvp] = link["precio"] if link.get("rol_precio") == "pvp" and link.get("moneda") == "CLP" else None
    if k_cos not in ss:
        ss[k_cos] = link["precio"] if link.get("rol_precio") == "costo" and link.get("moneda") == "USD" else None
    if ref and ref.get("fob_u"):
        fob_ref = ref["fob_u"] * kg_nombre if ref["unidad"] == "KG" and kg_nombre else ref["fob_u"]
        txt = (f"{usd(ref['fob_u'])}/kg × {kg_nombre:g} kg = {usd(fob_ref)}" if ref["unidad"] == "KG" and kg_nombre
               else f"{usd(fob_ref)} por {ref['unidad'].lower()}")
        if st.button(f"Usar como costo el FOB de la competencia ({ref['importador'][:24]}: {txt})"):
            ss[k_cos], ss[k_inc] = round(fob_ref, 2), "FOB"
    kg_ref = _kg_del_nombre(ref.get("glosa")) if ref else None
    if ref and ref.get("unidad") != "KG" and kg_ref and kg_nombre and abs(kg_ref / kg_nombre - 1) > 0.2 and ref.get("fob_u"):
        st.warning(f"Ojo: la referencia es de {kg_ref:g} kg y tu producto de {kg_nombre:g} kg. Por kilo, la competencia paga "
                   f"{usd(ref['fob_u'] / kg_ref)}; para {kg_nombre:g} kg serían ~{usd(ref['fob_u'] / kg_ref * kg_nombre)} (aprox., sin escalar envase).")
    if ref and ref.get("unidad") == "KG":
        st.caption("La referencia está en kilos (granel): es materia prima. Si se compra así, al costo hay que sumarle envase y maquila; "
                   "si se compra el producto terminado, elige en el paso 1 una línea por unidad.")
    c1, c2, c3 = st.columns(3)
    pvp = c1.number_input("PVP con IVA (CLP)", min_value=0.0, format="%.0f", key=k_pvp,
                          help="Si viene del link de una tienda chilena, es su precio de mercado.")
    costo = c2.number_input("Costo de compra (USD por unidad)", min_value=0.0, format="%.2f", key=k_cos)
    incoterm = c3.selectbox("Incoterm", ["EXW", "FOB"], key=k_inc)
    if not pvp and not costo:
        st.warning("Para seguir, ingresa el costo de compra o el PVP. Con uno, el evaluador calcula el otro: "
                   "con este costo → PVP ideal; con este PVP → costo máximo.")
        return None
    st.caption("Modo: **" + ("costo y PVP → veredicto, más PVP ideal y costo máximo de referencia" if pvp and costo else
                             "solo PVP → calcula el costo máximo que se puede pagar" if pvp else "solo costo → calcula el PVP ideal") + "**.")
    return {"pvp": pvp or None, "costo": costo or None, "incoterm": incoterm, "kg_u": kg_nombre}


# ── Paso 3: otras partidas ──────────────────────────────────────────────────
def _paso3(p1: dict, p2: dict, par: dict):
    ss = st.session_state
    st.subheader("3 · Otras partidas")
    st.caption("Vacío = supuesto por defecto (SKU parecido, RAW de la categoría, ROI, Seimex o dólar del día); el resultado lista cada supuesto.")
    q = st.text_input("SKU nuestro parecido (opcional, muy recomendable): de sus ventas reales salen velocidad, precio real, mix y caja",
                      key="ev_q2", placeholder="ej. mochila notebook · bateria · proyector")
    if q.strip():
        d = _similares(q.strip())
        if d.empty:
            st.caption("Sin SKU con venta que calcen.")
        else:
            et = [f"{r.sku} · {r.producto[:50]} · {miles(r.u_mes)} u/mes · precio real {clp(r.precio_real)}" for r in d.itertuples()]
            i = st.selectbox("SKU similar", range(len(d)), format_func=lambda k: et[k], key="ev_sim_sel")
            if st.button("Usar este SKU"):
                ss["ev_sku_similar"], ss["ev_categoria_macro"] = d.iloc[i].sku, d.iloc[i].categoria_macro
    if ss.get("ev_sku_similar"):
        c1, c2 = st.columns([4, 1])
        c1.caption(f"SKU de referencia: **{ss['ev_sku_similar']}**")
        if c2.button("Quitar"):
            ss["ev_sku_similar"] = None
    cats = ["Todas"] + [c for c in par["categorias"] if c not in ("Todas", "Marketing")]
    link, ref = p1["link"], p1.get("ref") or {}
    with st.form("ev_form"):
        c1, c2, c3, c4 = st.columns(4)
        cat_ini = ss.get("ev_categoria_macro")
        categoria = c1.selectbox("Categoría (márgenes reales del RAW)", cats, index=cats.index(cat_ini) if cat_ini in cats else 0,
                                 format_func=lambda c: "Total empresa (sin categoría parecida)" if c == "Todas" else c)
        qty = c2.number_input("Unidades del lote", value=1000, min_value=1, step=50)
        vel = c3.number_input("Velocidad de venta (u/mes)", value=None, min_value=0.0, format="%.1f",
                              help="Vacío = la del SKU parecido o la mediana de la categoría (queda marcada como supuesto)")
        desc = c4.number_input("Descuento promedio (%)", value=None, min_value=0.0, max_value=90.0, format="%.1f",
                               help=f"Vacío = el real del SKU parecido o {par['descuento_prom']:.1%} (promedio importados)")
        c1, c2, c3, c4 = st.columns(4)
        uds = c1.number_input("Unidades por caja master", value=None, min_value=1, step=1)
        cbm = c2.number_input("Volumen de la caja (m³)", value=None, min_value=0.0, format="%.4f",
                              help=(f"La DIN informa ~{ref['kg_u']:.1f} kg por unidad" if ref.get("kg_u")
                                    else "Vacío = del SKU parecido o la mediana de la categoría"))
        puerto = c3.selectbox("Puerto de embarque", PUERTOS)
        modalidad = c4.selectbox("Modalidad", MODALIDADES)
        c1, c2, c3, c4 = st.columns(4)
        flete = c1.number_input("Flete 40HQ (USD)", value=None, min_value=0.0, format="%.0f",
                                help=f"Vacío = última cotización Seimex ({miles(par['fletes_40hq']['Shenzhen']['valor'])})")
        lcl = c2.number_input("LCL todo incluido (USD/m³)", value=None, min_value=0.0, format="%.0f")
        lt = c3.number_input("Producción (días)", value=int(par["lt_produccion_dias"]), min_value=0, step=5)
        via = c4.checkbox("Compra vía Steven (3%)", value=True)
        c1, c2, c3, c4 = st.columns(4)
        anticipo = c1.number_input("Anticipo (%)", value=par["anticipo_pct"] * 100, min_value=0.0, max_value=100.0, format="%.0f")
        saldo = c2.selectbox("Saldo a fábrica", ["Origen", "Chile"])
        tc = c3.number_input("Dólar", value=float(par["tc"]), min_value=0.0, format="%.2f")
        fb2b = c4.number_input("Precio B2B / lista (%)", value=100.0, min_value=0.0, max_value=150.0, format="%.0f")
        moq = st.number_input("MOQ de la fábrica (unidades, opcional)", value=None, min_value=0.0, format="%.0f")
        st.markdown("**Mix de canales (%)** — vacío = el del SKU parecido o 60/25/15")
        cs = st.columns(4)
        mx = [c.number_input(t, value=None, min_value=0.0, max_value=100.0, format="%.0f")
              for c, t in zip(cs, ("Marketplace", "Web", "Fidelización", "B2B"))]
        enviar = st.form_submit_button("4 · Evaluar", type="primary")
    if not enviar:
        return None
    cot = {"nombre": link.get("nombre") or "Producto", "fabrica": ref.get("fabricante") or link.get("marca") or "",
           "categoria_macro": categoria, "precio_usd": p2["costo"], "incoterm": p2["incoterm"], "via_steven": via, "qty": int(qty),
           "pvp_iva": p2["pvp"], "lt_produccion": int(lt), "puerto": puerto, "modalidad": modalidad, "anticipo_pct": anticipo / 100,
           "saldo_en": saldo, "factor_precio_b2b": fb2b / 100, "sku_similar": ss.get("ev_sku_similar")}
    for k, v in (("descuento", None if desc is None else desc / 100), ("velocidad_mes", vel), ("uds_ctn", uds), ("cbm_ctn", cbm),
                 ("flete_contenedor_usd", flete), ("flete_lcl_m3", lcl), ("moq", moq)):
        if v not in (None, 0):
            cot[k] = v
    if any(v not in (None, 0) for v in mx):
        cot["mix"] = dict(zip(("mkp", "web", "fid", "b2b"), [(v or 0) / 100 for v in mx]))
    return cot, tc


def correr(cot: dict, tc: float, p1: dict, p2: dict) -> dict:
    """Evalúa con el cruce de la competencia armado desde el producto de referencia elegido en el paso 1."""
    par = dict(M.cargar_parametros())
    par["tc"] = tc
    p, _, falta = M.completar(cot, par)
    if falta:
        return M.evaluar(cot, par, None)
    if not p.get("precio_usd"):                        # solo PVP: primero el costo máximo; con él se arma la banda
        r0 = M.evaluar(cot, par, None)
        if r0["estado"] != "OK":
            return r0
        p = r0["producto"]
    imp = M.importacion(p, par)
    fob_u = imp["fob_china_usd"] / p["qty"]
    fi = (imp["agente_usd"] + imp["gastos_chile_clp"] / par["tc"]) / imp["cif_usd"]
    ref = p1.get("ref")
    if ref and ref.get("partida"):
        unidad = ref["unidad"]
        kg_u = p2.get("kg_u")
        fob_cmp = fob_u / kg_u if unidad == "KG" and kg_u else fob_u
        radar = None
        if unidad in ("U", "SET", "PAR"):              # dentro del universo del radar: cruce completo (tendencia, forwarder)
            radar = R.cruzar(fob_u=fob_cmp, arancel=ref["partida"], palabras=list(p1.get("fuertes") or []), unidad=unidad,
                             tc=par["tc"], factor_internacion=fi)
        if not radar or not radar.get("disponible") or radar.get("sin_coincidencias") or not radar.get("competidores"):
            radar = R.radar_desde_busqueda(p1["res"], fob_cmp, ref["partida"], unidad, list(p1.get("fuertes") or []), par["tc"], fi)
        if unidad == "KG" and kg_u and radar.get("fob_referencia_u"):
            radar["fob_referencia_u"] *= kg_u           # la regla de decisión compara por unidad de venta
    else:
        radar = {"disponible": False, "motivo": "no se eligió un producto de referencia de la competencia"}
    return M.evaluar(cot, par, radar)


def _excel(r: dict) -> bytes:
    import excel_evaluacion as X
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "evaluacion.xlsx"
        X.armar(r, M.cargar_parametros(), f)
        return f.read_bytes()


def _resultado(r: dict):
    st.divider()
    if r["estado"] != "OK":
        st.error(INF.markdown(r))
        return
    p, an, lo = r["producto"], r["anual"], r["lote"]
    st.markdown(f"<h2 style='color:{COLOR.get(r['veredicto'], '#1F3864')};margin-bottom:0'>{r['veredicto']}</h2>", unsafe_allow_html=True)
    st.markdown(f"**{r['razon'][0].upper() + r['razon'][1:]}.**")
    c1, c2 = st.columns(2)
    c1.metric(f"Con este costo ({usd(p['precio_usd'])} {p['incoterm']}) → PVP ideal", f"{clp(r.get('pvp_ideal'))} con IVA")
    c2.metric(f"Con este PVP ({clp(p['pvp_iva'])}) → costo máximo de compra" + (" (tope: competencia)" if r["bloqueo_competencia"] else ""),
              f"{usd(r['fob_objetivo_usd'])} {p['incoterm']}")
    st.caption(f"Meta: pagar su capital (9%) en el escenario conservador y alcanzar la contribución de su categoría "
               f"({pct(r['benchmark_contrib_pct'])}). Veredicto a estos precios: **{r['veredicto_a_estos_precios']}**.")
    b, c = an["base"], an["conservador"]
    k = st.columns(6)
    k[0].metric("Costo internado/u", clp(r["importacion"]["costo_u"]), f"sobrecosto {pct(r['importacion']['sobrecosto_pct'])}", delta_color="off")
    k[1].metric("Contribución", pct(b["contrib_pct"]), f"categoría {pct(r['benchmark_contrib_pct'])}", delta_color="off")
    k[2].metric("EVA anual base", clp(b["eva"]), f"conservador {clp(c['eva'])}", delta_color="off")
    k[3].metric("ROI del lote (base)", pct(lo["base"]["roi_lote"]), f"anualizado {pct(lo['base']['roi_anualizado'])}", delta_color="off")
    k[4].metric("Payback", f"mes {lo['base']['payback_mes']}" if lo["base"]["payback_mes"] is not None else "no recupera")
    k[5].metric("Caja máxima", clp(lo["base"]["caja_necesaria"]))
    for a in r.get("alertas", []):
        st.warning(a[0].upper() + a[1:])
    lt_ = r.get("lotes") or {}
    if lt_.get("opciones"):
        rec = lt_.get("recomendado")
        st.markdown("#### Unidades a comprar" + (f" · recomendado **{miles(rec['unidades'])} u** (~{str(round(rec['meses_venta'], 1)).replace('.', ',')} meses de venta)"
                                                if rec else ""))
        tb = pd.DataFrame(lt_["opciones"])
        tb["recomendado"] = tb.unidades.eq(rec["unidades"]) if rec else False
        st.dataframe(tb.assign(unidades=tb.unidades.map(miles), meses_venta=tb.meses_venta.round(1), costo_u=tb.costo_u.map(clp),
                               inversion=tb.inversion.map(clp), roi_lote=tb.roi_lote.map(pct), roi_anualizado=tb.roi_anualizado.map(pct),
                               eva_anual=tb.eva_anual.map(clp), caja_maxima=tb.caja_maxima.map(clp))
                     [["recomendado", "unidades", "meses_venta", "costo_u", "inversion", "roi_lote", "roi_anualizado", "eva_anual", "caja_maxima",
                       "payback_mes", "cubre_reposicion", "cumple_moq"]], hide_index=True, width="stretch")
        st.caption("Recomendado = mejor ROI anualizado entre los lotes que cubren la reposición ("
                   + str(round(lt_["reposicion_meses"], 1)).replace(".", ",") + " meses: producción + tránsito + aduana) y el MOQ.")
    t = st.tabs(["Flujo del lote", "Competencia", "Informe completo", "Supuestos usados"])
    with t[0]:
        n = max(len(lo[e]["acumulado"]) for e in lo)
        df = pd.DataFrame({e.capitalize(): (lo[e]["acumulado"] + [lo[e]["acumulado"][-1]] * (n - len(lo[e]["acumulado"])))
                           for e in ("conservador", "base", "optimista")})
        df.index.name = "Mes"
        st.line_chart(df / 1e6, y_label="Flujo acumulado (MM CLP)")
        st.caption("Mes 0 = anticipo a fábrica. Incluye IVA de importación (se paga al llegar y se recupera el mes siguiente).")
    with t[1]:
        rad = r["radar"]
        if not rad.get("disponible"):
            st.info(f"Competencia pendiente: {rad.get('motivo', '')}")
        elif rad.get("sin_coincidencias") or not rad.get("competidores"):
            st.info("Sin competidores en la banda de precio de esa partida.")
        else:
            comp = pd.DataFrame(rad["competidores"])
            comp["fabricas"] = comp.fabricas.map(lambda x: ", ".join(map(str, x)))
            st.markdown(f"**Competidores con productos de precio comparable** ({usd(rad['banda'][0])}–{usd(rad['banda'][1])} por "
                        f"{str(rad.get('unidad', 'u')).lower()}) · fuente: {rad.get('fuente', 'radar de importaciones')}")
            st.dataframe(comp[["importador", "nivel", "unidades_12m", "din_12m", "fob_u_prom", "dif_fob_pct", "internado_u_estimado_clp",
                               "tendencia", "fabricas"]], hide_index=True, width="stretch")
            alta = [x for x in rad["coincidencias"] if x["confianza"] == "ALTA"]
            if alta:
                st.markdown("**Mismo producto (marca o modelo)**")
                st.dataframe(pd.DataFrame(alta)[["mes", "importador", "glosa", "proveedor", "unidades", "fob_u"]], hide_index=True, width="stretch")
            if rad.get("fabricas"):
                st.markdown("**Marcas y fábricas para cotizar**")
                st.dataframe(pd.DataFrame(rad["fabricas"]), hide_index=True, width="stretch")
    with t[2]:
        st.markdown(INF.markdown(r))
    with t[3]:
        st.markdown("\n".join(f"- {s}" for s in r["supuestos"]))
    c1, c2 = st.columns(2)
    c1.download_button("Descargar Excel (con fórmulas)", data=_excel(r),
                       file_name=f"evaluacion_{re.sub(r'[^0-9A-Za-z]+', '_', p.get('nombre', 'producto'))[:40]}.xlsx")
    c2.download_button("Descargar JSON (para otros agentes)", data=json.dumps(INF.json_agentes(r), ensure_ascii=False, default=float, indent=1),
                       file_name="evaluacion.json")


def render():
    st.title("🧮 Evaluador de productos")
    st.caption("Pega el link de un producto (competencia, marketplace o proveedor) y evalúa si conviene traerlo. "
               "Uso interno: trae nuestros costos y márgenes.")
    from views.ops_radar_importaciones import HUB, _asegurar_hub, _autorizado
    if not _autorizado():
        st.info("El Evaluador de productos tiene acceso restringido. Pídele acceso a Andrés.")
        return
    if not _asegurar_hub():                      # en la nube baja el zip privado del radar (cubos + parámetros del evaluador)
        return
    import os
    os.environ["AGENTE_PRODUCTO_HUB"] = str(HUB)
    try:                                         # la IA usa ANTHROPIC_API_KEY de los Secrets (si no está, todo sigue con reglas)
        if st.secrets.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:  # noqa: BLE001
        pass
    cfg = Path(HUB) / "ia_config.json"         # o del zip privado del radar (la publica radar-aduana/pipeline/publicar_nube.py)
    if not os.environ.get("ANTHROPIC_API_KEY") and cfg.exists():
        try:
            k = json.loads(cfg.read_text(encoding="utf-8")).get("ANTHROPIC_API_KEY")
            if k:
                os.environ["ANTHROPIC_API_KEY"] = k
        except Exception:  # noqa: BLE001
            pass
    R.HUB = Path(HUB)
    par = _par()
    p1 = _paso1()
    if not p1:
        return
    p2 = _paso2(p1)
    if not p2:
        return
    out = _paso3(p1, p2, par)
    if out is not None:
        cot, tc = out
        with st.spinner("Calculando…"):
            st.session_state["ev_resultado"] = correr(cot, tc, p1, p2)
    if st.session_state.get("ev_resultado"):
        _resultado(st.session_state["ev_resultado"])
