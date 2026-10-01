"""
Radar de Importaciones — hub de supply chain (App Operaciones → COMEX).

Responde, con las DIN públicas de Aduana, ¿dónde tiene puntos de mejora nuestro supply chain?
comparando lo que traemos contra TODO el mercado de esos productos. Filtros globales:
mirada (núcleo / adyacente) · categoría · tipo de producto · importador · período.
UnionX se muestra SIEMPRE como comparativo, filtres lo que filtres.

Reglas de lectura:
  MEDIDO    sale de la DIN (CIF, FOB, cantidades, proveedor declarado, forwarder, naviera, fechas).
  DERIVADO  calculado (precio por unidad ponderado, flete % FOB, días embarque→DIN, participaciones).
  INFERIDO  el NOMBRE del importador (Aduana lo publica anonimizado): siempre con nivel de evidencia.
  Los montos por empresa son un piso: lo que traigan sin identificar no se les atribuye.

Datos: cubos precalculados por radar-aduana/pipeline/p9_cubos.py (dir RADAR_HUB_DIR).
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import threading
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from views import _fin_echarts as ECH
from views import _radar_excel as XL

_REPO = Path(__file__).resolve().parent.parent
_CANDIDATOS = ([Path(os.environ["RADAR_HUB_DIR"])] if os.environ.get("RADAR_HUB_DIR") else []) + [
    _REPO / "data" / "comex" / "radar", Path("C:/Users/andre/radar_aduana/outputs/hub")]
HUB = next((p for p in _CANDIDATOS if (p / "mercado.parquet").exists()), None)
# En Streamlit Cloud los cubos (214 MB, con nuestros costos) NO van en el repo: se bajan de un zip PRIVADO en Drive que
# publica radar-aduana/pipeline/publicar_nube.py, leído con la cuenta de servicio de la app ([gcp_service_account]).
EN_NUBE = HUB is None or os.environ.get("RADAR_FORZAR_NUBE") == "1"
if EN_NUBE:
    HUB = Path(tempfile.gettempdir()) / "radar_hub"
RADAR_HUB_FILE_ID = "1j0b6vqAQpd2w2BmsjKoNdg8QwHPOClDq"
# Primer borrador (30-sep-2026): solo Andrés + Nicolás, Felipe, Nicole, Martín y Seba (usuarios del login de App Ventas)
RADAR_USUARIOS = {"andres", "nicolas", "felipe", "nicole", "martin", "sguzman"}
TABLAS = ["importadores", "mercado", "imp_mes", "proveedores", "din", "din_tipo", "precios_dist", "nosotros", "lineas", "ventas",
          "imp_total", "imp_fuera", "imp_hs4"]
UX = "RUT:76600685"
NIVEL_TXT = {"rut": "RUT declarado", "verificada": "Verificada", "probable": "Probable",
             "trazado": "Trazado sin nombre", "NI": "No identificado"}
NIVEL_ICO = {"rut": "🟢", "verificada": "🟢", "probable": "🟡", "trazado": "⚪", "NI": "·"}
UNIDAD_TXT = {"U": "unidad", "SET": "set", "PAR": "par"}


# ============================================================
# Datos y formato
# ============================================================
@st.cache_resource(show_spinner=False)
def _con():
    con = duckdb.connect()
    if EN_NUBE:   # la app comparte ~1 GB de RAM con el resto de App Ventas (ya tuvo OOM): DuckDB acotado y a disco
        con.execute(f"SET memory_limit = '{os.environ.get('RADAR_DUCKDB_MEM', '200MB')}'")
        con.execute(f"SET threads = {int(os.environ.get('RADAR_DUCKDB_HILOS', '1'))}")
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = '{(Path(tempfile.gettempdir()) / 'radar_duckdb').as_posix()}'")
    for t in TABLAS:
        p = HUB / f"{t}.parquet"
        if p.exists():
            con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{p.as_posix()}')")
    return con


@st.cache_data(ttl=3600, show_spinner=False, max_entries=150)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return _con().cursor().execute(sql, list(params)).df()


# ============================================================
# Nube: cubos desde Drive + acceso restringido
# ============================================================
def _secreto(clave: str, defecto=None):
    """st.secrets sin reventar cuando no hay secrets.toml (corrida local)."""
    try:
        return st.secrets.get(clave, defecto)
    except Exception:
        return defecto


@st.cache_resource(show_spinner=False)
def _candado() -> threading.Lock:
    return threading.Lock()


def _token_drive() -> str:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    cr = service_account.Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=["https://www.googleapis.com/auth/drive.readonly"])
    cr.refresh(Request())
    return cr.token


@st.cache_data(ttl=3600, show_spinner=False)
def _version_remota() -> str:
    """modifiedTime del zip en Drive (se consulta a lo más una vez por hora)."""
    import requests
    fid = _secreto("RADAR_HUB_FILE_ID", RADAR_HUB_FILE_ID)
    r = requests.get(f"https://www.googleapis.com/drive/v3/files/{fid}", params={"fields": "modifiedTime"},
                     headers={"Authorization": f"Bearer {_token_drive()}"}, timeout=30)
    r.raise_for_status()
    return r.json()["modifiedTime"]


def _asegurar_hub() -> bool:
    """En la nube: baja y descomprime los cubos si no están o si hay una versión nueva en Drive."""
    if not EN_NUBE:
        return True
    marca = HUB / "_version.txt"
    try:
        remota = _version_remota()
    except Exception as e:  # sin red o sin credencial: se sigue con lo que haya en disco
        if (HUB / "mercado.parquet").exists():
            return True
        st.error(f"No pude leer los datos del radar desde Drive ({type(e).__name__}). Revisa que la app tenga "
                 "[gcp_service_account] en sus Secrets y que el archivo esté compartido con esa cuenta.")
        return False
    if marca.exists() and marca.read_text(encoding="utf-8") == remota and (HUB / "mercado.parquet").exists():
        return True
    import requests
    with _candado():
        if marca.exists() and marca.read_text(encoding="utf-8") == remota:
            return True
        with st.spinner("Bajando los datos del radar (una vez por actualización, ~200 MB)…"):
            HUB.mkdir(parents=True, exist_ok=True)
            tmp = HUB.parent / "radar_hub_descarga.zip"
            fid = _secreto("RADAR_HUB_FILE_ID", RADAR_HUB_FILE_ID)
            with requests.get(f"https://www.googleapis.com/drive/v3/files/{fid}", params={"alt": "media"},
                              headers={"Authorization": f"Bearer {_token_drive()}"}, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(tmp, "wb") as fh:
                    for trozo in r.iter_content(chunk_size=8 * 1024 * 1024):
                        fh.write(trozo)
            with zipfile.ZipFile(tmp) as z:
                z.extractall(HUB)
            tmp.unlink(missing_ok=True)
            marca.write_text(remota, encoding="utf-8")
        for f_ in (q, calidad, TABLAS_OK, _capitulos, _con):
            f_.clear()
    return True


def _autorizado() -> bool:
    """Borrador: solo los usuarios de RADAR_USUARIOS (login de App Ventas). En local (sin login) no aplica."""
    usuario = st.session_state.get("username")
    if not usuario:
        return True
    permitidos = {u.strip() for u in str(_secreto("RADAR_USUARIOS", "")).split(",") if u.strip()} or RADAR_USUARIOS
    return usuario in permitidos


@st.cache_data(ttl=3600, show_spinner=False)
def calidad() -> dict:
    p = HUB / "calidad.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def mm(v) -> str:
    return "—" if v is None or pd.isna(v) else f"US$ {ECH.es(v / 1e6, 1)} M"


def usd(v, dec=2) -> str:
    return "—" if v is None or pd.isna(v) else f"US$ {ECH.es(v, dec)}"


def pct(v, dec=1) -> str:
    return "—" if v is None or pd.isna(v) else f"{ECH.es(100 * v, dec)}%"


def mes_txt(m: str) -> str:
    n = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{n[int(m[5:7]) - 1]}-{m[2:4]}"


def ev_txt(nivel: str, pct_alta=None) -> str:
    """Evidencia de una empresa (ponderada por CIF): 🟢 verificada = ≥90% de su CIF en meses verificados."""
    base = f"{NIVEL_ICO.get(nivel, '')} {NIVEL_TXT.get(nivel, nivel)}"
    if nivel == "probable" and pct_alta is not None and pd.notna(pct_alta):
        base += f" ({pct(pct_alta, 0)} verificado)"
    return base


def _evidencia_periodo(k: str, d: str, h: str) -> str:
    """Meses del período por nivel de evidencia (el nivel se asigna mes a mes, no a la empresa)."""
    if k.startswith("TRZ:"):
        return "⚪ trazada sin RUT: misma empresa mes a mes por sus códigos, sin nombre"
    ev = q("""SELECT nivel, count(*) n, sum(cif_total) c FROM imp_total WHERE importador_key = ? AND mes BETWEEN ? AND ?
              GROUP BY 1""", (k, d, h))
    if ev.empty:
        return "sin importaciones identificadas en el período"
    alta = ev[ev.nivel.isin(["rut", "verificada"])]
    n_p = int(ev[ev.nivel == "probable"].n.sum())
    ico = "🟢" if alta.c.sum() >= 0.9 * ev.c.sum() else "🟡"
    txt = f"{ico} {int(alta.n.sum())} de {int(ev.n.sum())} meses del período verificados por ≥2 códigos trazadores"
    if n_p:
        txt += f", {n_p} probables (1 código + misma comuna, o marcas propias; {pct(1 - alta.c.sum() / ev.c.sum(), 0)} de su CIF)"
    return txt


def nombre_imp(k: str) -> str:
    if k == UX:
        return "UnionX"
    r = q("SELECT importador FROM importadores WHERE importador_key = ?", (k,))
    return r.importador.iloc[0] if len(r) else ("No identificados" if k == "NI" else k)


# ============================================================
# Filtros
# ============================================================
def _where(f: dict, con_importador=True, alias="") -> tuple[str, tuple]:
    a = f"{alias}." if alias else ""
    w, p = [f"{a}mes BETWEEN ? AND ?"], [f["desde"], f["hasta"]]
    if f["mirada"] != "Ambas":
        w.append(f"{a}universo = ?"); p.append(f["mirada"])
    if not f["vecinas"]:
        w.append(f"NOT coalesce({a}vecina, false)")
    if f["categorias"]:
        w.append(f"{a}categoria IN ({','.join('?' * len(f['categorias']))})"); p += f["categorias"]
    if f["tipos"]:
        w.append(f"{a}tipo IN ({','.join('?' * len(f['tipos']))})"); p += f["tipos"]
    if con_importador and f["importadores"]:
        w.append(f"{a}importador_key IN ({','.join('?' * len(f['importadores']))})"); p += f["importadores"]
    return " AND ".join(w), tuple(p)


def _ux(f: dict) -> dict:
    """Mismos filtros de producto y período, pero para UnionX (el comparativo permanente)."""
    return dict(f, importadores=[UX])


def _con_elegidos(opciones: list, key: str) -> list:
    """Opciones + lo ya elegido que no esté en ellas. La lista de categorías, tipos e importadores cambia con el período
    y la mirada; sin esto Streamlit borra la selección (Andrés elegía Builder, movía el período y, sin aviso, volvía a
    ver el mercado completo)."""
    previos = [x for x in (st.session_state.get(key) or []) if x not in opciones]
    return list(opciones) + previos


def _filtros() -> dict:
    meses = q("SELECT DISTINCT mes FROM mercado ORDER BY 1")["mes"].tolist()
    c1, c2, c3 = st.columns([1.1, 1.4, 2.5])
    mirada = c1.radio("Mirada", ["Núcleo", "Adyacente", "Ambas"], horizontal=True,
                      help="Núcleo = los tipos de producto que traemos, en nuestras subpartidas. "
                           "Adyacente = otros productos que se importan en nuestras mismas partidas (surtido).")
    vecinas = c1.toggle("Incluir partidas vecinas", value=False,
                        help="Mismo tipo de producto declarado en otra subpartida de la misma partida (4 dígitos).")
    desde, hasta = c2.select_slider("Período", options=meses, value=(meses[0], meses[-1]), format_func=mes_txt)
    base = {"mirada": mirada, "vecinas": vecinas, "desde": desde, "hasta": hasta,
            "categorias": [], "tipos": [], "importadores": []}
    w, p = _where(base, con_importador=False)
    cats = q(f"SELECT categoria, sum(cif) cif FROM mercado WHERE {w} GROUP BY 1 ORDER BY 2 DESC", p)
    base["categorias"] = c3.multiselect("Categoría", _con_elegidos(cats["categoria"].tolist(), "radar_cat"),
                                        placeholder="Todas", key="radar_cat")
    w, p = _where(base, con_importador=False)
    tipos = q(f"SELECT tipo, sum(cif) cif FROM mercado WHERE {w} GROUP BY 1 ORDER BY 2 DESC", p)
    tcif = dict(zip(tipos.tipo, tipos.cif))
    nos = q("""SELECT sku, arg_max(producto, eta) producto, arg_max(tipo, eta) tipo, sum(qty) u FROM nosotros
               WHERE tipo IS NOT NULL AND coalesce(sku, '') <> '' GROUP BY 1 ORDER BY u DESC""")
    nos["lab"] = [f"{r.sku} · {str(r.producto)[:42]} ({r.tipo})" for r in nos.itertuples()]
    lab_sku = dict(zip(nos.sku, nos.lab))
    d0, d1, d2 = st.columns([2, 2, 2])
    base["tipos"] = d0.multiselect("Tipo de producto", _con_elegidos(tipos["tipo"].tolist(), "radar_tipo"), placeholder="Todos",
                                   format_func=lambda t: f"{t} · {mm(tcif.get(t))}", key="radar_tipo")
    # Mi SKU con búsqueda EXACTA: la del multiselect de Streamlit calza letra a letra ("loza" traía 63 SKU de 12 tipos:
    # "Pantalón Mujer Lukla-W Navy Talla 44" calza l…o…z…a) y el mercado terminaba mezclando polerones con loza.
    # Si hay tipo elegido, solo se listan SKU de ese tipo.
    buscar = d1.text_input("Mi SKU (opcional): buscar por código, nombre o tipo", key="radar_sku_buscar",
                           placeholder="p. ej. loza · LVAUDGM · polerón",
                           help="Para partir desde un producto nuestro: filtra su tipo y, en Precios y en el Excel, lo compara "
                                "contra quienes compran ese tipo en su mismo rango de precio. Busca el texto tal cual.")
    pool = nos[nos.tipo.isin(base["tipos"])] if base["tipos"] else nos
    if buscar.strip():
        s_ = _sin_tildes(buscar.strip())
        pool = pool[pool.lab.map(_sin_tildes).str.contains(s_, regex=False)]
    base["skus"] = d1.multiselect("SKU", _con_elegidos(pool.sku.tolist(), "radar_sku"), key="radar_sku",
                                  placeholder=f"{len(pool)} SKU {'que calzan' if buscar.strip() else 'nuestros'} · elige uno o varios",
                                  format_func=lambda s_: lab_sku.get(s_, s_), label_visibility="collapsed")
    if base["skus"] and not base["tipos"]:
        base["tipos"] = sorted(set(nos[nos.sku.isin(base["skus"])].tipo))
        if len(base["tipos"]) > 1:
            st.warning(f"Tus SKU elegidos son de {len(base['tipos'])} tipos distintos ({', '.join(base['tipos'])}) y el "
                       "mercado de abajo los suma todos. Para mirar uno solo, elígelo en 'Tipo de producto'.")
        else:
            st.caption(f"Filtrando por el tipo de tus SKU: {base['tipos'][0]}")
    w, p = _where(base, con_importador=False)
    imps = q(f"""SELECT m.importador_key, coalesce(i.importador, 'No identificados') importador,
                        coalesce(i.nivel, 'NI') nivel, sum(m.cif) cif
                 FROM mercado m LEFT JOIN importadores i USING (importador_key)
                 WHERE {w} GROUP BY 1, 2, 3 ORDER BY (m.importador_key = '{UX}') DESC, cif DESC LIMIT 400""", p)
    lab = {r.importador_key: f"{NIVEL_ICO.get(r.nivel, '')} {r.importador} · {mm(r.cif)}" for r in imps.itertuples()}
    base["importadores"] = d2.multiselect(
        "Importador", _con_elegidos(imps["importador_key"].tolist(), "radar_imp"), placeholder="Todos (mercado completo)",
        format_func=lambda k: lab.get(k) or f"{nombre_imp(k)} · sin CIF en lo filtrado", key="radar_imp",
        help="🟢 RUT declarado o verificada por trazadores · 🟡 probable · ⚪ trazado sin nombre. "
             "'No identificados' agrupa el resto (su correlativo cambia cada mes).")
    return base


# ============================================================
# Métricas reutilizables
# ============================================================
def _resumen(f: dict) -> dict:
    """CIF, DIN, variación ene–mes vs año anterior, FOB por unidad (unidad dominante) para un filtro."""
    w, p = _where(f)
    k = q(f"SELECT sum(cif) cif FROM mercado WHERE {w}", p).iloc[0]
    n_din = q(f"SELECT count(DISTINCT id_operacion) n FROM din_tipo WHERE {w}", p).iloc[0]["n"]
    ult = f["hasta"]; y, m = int(ult[:4]), int(ult[5:7])
    wy, py = _where(dict(f, desde=f"{y}-01", hasta=ult))
    wp, pp = _where(dict(f, desde=f"{y - 1}-01", hasta=f"{y - 1}-{m:02d}"))
    cy = q(f"SELECT sum(cif) c FROM mercado WHERE {wy}", py).iloc[0]["c"]
    cp = q(f"SELECT sum(cif) c FROM mercado WHERE {wp}", pp).iloc[0]["c"]
    un = q(f"""SELECT unidad_cmp, sum(unidades) u, sum(fob_u) f FROM mercado WHERE {w} AND unidades > 0
               GROUP BY 1 ORDER BY u DESC LIMIT 1""", p)
    return {"cif": k.cif, "din": n_din, "var": (cy / cp - 1) if cy and cp else None,
            "pu": (un.f.iloc[0] / un.u.iloc[0]) if len(un) else None,
            "unidad": un.unidad_cmp.iloc[0] if len(un) else None}


def _dt(f: dict) -> tuple[str, tuple]:
    """CTE 'x': DIN que contienen productos del filtro, con el peso (CIF) de esos productos en cada DIN.
    Todo lo logístico se agrega en SQL: bajar las DIN a pandas eran ~100 MB por filtro en caché (App Ventas ~1 GB)."""
    w, p = _where(f, alias="t")
    return (f"x AS (SELECT d.*, dt.peso FROM din d JOIN (SELECT t.id_operacion, sum(t.cif) peso FROM din_tipo t "
            f"WHERE {w} GROUP BY 1) dt USING (id_operacion))"), p


def _log(f: dict) -> dict:
    """Flete+seguro / FOB ponderado por el CIF de los productos filtrados en cada DIN, y mediana de días (marítimo)."""
    cte, p = _dt(f)
    r = q(f"""WITH {cte} SELECT count(*) n, sum(fob_din * peso / nullif(cif_din, 0)) fob,
                     sum((flete_din + seguro_din) * peso / nullif(cif_din, 0)) fle,
                     median(dias_emb_din) FILTER (WHERE via LIKE '%MAR%') dias FROM x""", p).iloc[0]
    return {"n": int(r.n or 0), "flete": (r.fle / r.fob) if r.fob else None,
            "dias": None if pd.isna(r.dias) else float(r.dias)}


def _log_por(f: dict, campo: str) -> pd.Series:
    """CIF de los productos filtrados por valor de un atributo logístico (via, modalidad, forwarder, naviera, puerto)."""
    cte, p = _dt(f)
    g = q(f"WITH {cte} SELECT {campo} k, sum(peso) peso FROM x WHERE {campo} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC", p)
    return pd.Series(g.peso.values, index=g.k.values, dtype=float)


def q_sin_cache(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Para consultas que se usan una vez (armar un Excel): no quedan en la caché de la app."""
    return _con().cursor().execute(sql, list(params)).df()


def _plausibles(g: pd.DataFrame, col: str = "pu") -> pd.DataFrame:
    """Excluye precios implausibles (< 1/5 o > 5 veces la mediana del tipo): casi siempre unidades mal
    declaradas (sets o componentes contados como unidad). Regla de la Fase 7 del brief (outliers)."""
    if len(g) < 3:
        return g
    med = g[col].median()
    return g[(g[col] >= med / 5) & (g[col] <= med * 5)]


def _barras_linea(cats, nombre_b, vals_b, nombre_l, vals_l, u_b="US$ M", u_l="US$ M", height=340, mismo_eje=False):
    """Barras (selección) + línea (UnionX) con eje propio, para comparar escalas distintas. mismo_eje=True cuando
    lo que se compara es el tamaño (con dos ejes, una empresa 5 veces más grande se vería del mismo alto)."""
    opt = {
        "grid": {"left": 60, "right": 64, "top": 40, "bottom": 46},
        "tooltip": ECH._tooltip(),
        "legend": {"data": [nombre_b, nombre_l], "top": 4, "textStyle": {"color": ECH.MUTE, "fontSize": 11}},
        "xAxis": ECH._cat_axis(cats, rotate=40 if len(cats) > 14 else 0),
        "yAxis": ([ECH._val_axis(u_b)] if mismo_eje else
                  [ECH._val_axis(u_b), {**ECH._val_axis(u_l), "splitLine": {"show": False}}]),
        "series": [
            {"name": nombre_b, "type": "bar", "data": vals_b, "barMaxWidth": 26, "itemStyle": {"color": ECH.GRAY}},
            {"name": nombre_l, "type": "line", "yAxisIndex": 0 if mismo_eje else 1, "data": vals_l, "symbol": "circle",
             "symbolSize": 6, "lineStyle": {"width": 2.5, "color": ECH.EMF}, "itemStyle": {"color": ECH.EMF}},
        ],
    }
    ECH.render(opt, height=height)


# ============================================================
# Cabecera: KPIs selección vs UnionX + cobertura (la cobertura nunca se esconde)
# ============================================================
def _kpis(f: dict):
    sel = f["importadores"]
    et_sel = ("Mercado" if not sel else nombre_imp(sel[0]) if len(sel) == 1 else f"{len(sel)} importadores")
    rs, ru = _resumen(f), _resumen(_ux(f))
    w, p = _where(f)
    ds, du = _log(f), _log(_ux(f))
    if sel:
        # con importadores elegidos, "participación en la selección" no existe (UnionX no es parte de Builder): se
        # muestra cuántas veces UnionX es la selección y la participación de UnionX en el mercado de esos productos
        wm, pm = _where(f, con_importador=False)
        cif_m = q(f"SELECT sum(cif) c FROM mercado WHERE {wm}", pm).iloc[0]["c"]
        ext_s = ("Tamaño vs UnionX", f"{ECH.es(rs['cif'] / ru['cif'], 1)}×" if rs["cif"] and ru["cif"] else "—",
                 "CIF de la selección ÷ CIF de UnionX, en los mismos productos y período.")
        ext_u = ("Participación en el mercado", pct(ru["cif"] / cif_m, 2) if ru["cif"] and cif_m else "0%",
                 "CIF de UnionX ÷ CIF de TODO el mercado de estos productos y período (sin filtro de importador).")
    else:
        n_imp = q(f"SELECT avg(n) n FROM (SELECT mes, count(DISTINCT importador_id) n FROM imp_mes WHERE {w} GROUP BY 1)", p).iloc[0]["n"]
        ext_s = ("Importadores / mes", ECH.es(n_imp) if n_imp else "—", "Importadores distintos por mes (promedio), identificados o no.")
        ext_u = ("Participación en la selección", pct(ru["cif"] / rs["cif"], 2) if ru["cif"] and rs["cif"] else "0%",
                 "CIF de UnionX ÷ CIF de todo lo filtrado.")
    # con UNA empresa elegida, su total (todos sus productos) va como indicador al lado de lo filtrado: la cifra grande
    # sola (lo filtrado) no calzaba con el tamaño de la empresa (Andrés, 30-sep: Builder 3,8 M en pantalla vs 12,5 M)
    uno = len(sel) == 1 and "imp_total" in TABLAS_OK()
    per = (f["desde"], f["hasta"])
    tot_s = tot_u = None
    if uno:
        tot_s = q("SELECT sum(cif_total) c FROM imp_total WHERE importador_key = ? AND mes BETWEEN ? AND ?", (sel[0],) + per).iloc[0]["c"]
        tot_u = q("SELECT sum(cif_total) c FROM imp_total WHERE importador_key = ? AND mes BETWEEN ? AND ?", (UX,) + per).iloc[0]["c"]
    for etq, r, d, extra, tot_e in ((f"**{et_sel}**", rs, ds, ext_s, tot_s),
                                    ("**UnionX** · mismos productos y período", ru, du, ext_u, tot_u)):
        st.markdown(etq)
        c = st.columns(7 if uno else 6)
        c[0].metric("CIF en lo filtrado" if sel else "CIF", mm(r["cif"]),
                    help="Solo los productos que pasan los filtros de arriba (mirada, categoría, tipo), en el período elegido.")
        j = 0
        if uno:
            j = 1
            c[1].metric("CIF total (todos sus productos)", mm(tot_e),
                        help="Todo lo que importó en el período, lo compita o no con lo nuestro: la cifra para dimensionar la "
                             "empresa. Para compararla con otra fuente, usa el mismo período.")
        c[j + 1].metric(f"Var. ene–{mes_txt(f['hasta'])[:3]} vs año ant.", pct(r["var"]) if r["var"] is not None else "—")
        c[j + 2].metric("DIN en lo filtrado" if sel else "DIN", ECH.es(r["din"]) if r["din"] else "—")
        c[j + 3].metric(f"FOB por {UNIDAD_TXT.get(r['unidad'] or '', 'unidad')}", usd(r["pu"]) if len(f["tipos"]) == 1 else "—",
                        help="Se calcula solo con UN tipo de producto elegido: mezclar tipos no tiene sentido.")
        c[j + 4].metric("Flete+seguro / FOB", pct(d["flete"]))
        c[j + 5].metric(extra[0], extra[1], help=extra[2])
    if uno and tot_s:
        alcance = {"Núcleo": "lo que compite con lo que traemos nosotros",
                   "Adyacente": "lo que se importa en nuestras mismas partidas pero no traemos",
                   "Ambas": "lo que traemos nosotros más lo demás de nuestras mismas partidas"}[f["mirada"]]
        st.caption(f"ℹ️ Período **{mes_txt(f['desde'])} → {mes_txt(f['hasta'])}**: {et_sel} importó **{mm(tot_s)} en total** "
                   f"(todos sus productos); **{pct((rs['cif'] or 0) / tot_s, 0)}** es lo filtrado: {alcance}. Para comparar con "
                   "otra cifra, usa el mismo período. El detalle está en 'Ficha importador' y en 'Tamaño de empresas'.")
    # evidencia del MES en que se importó (no el mejor nivel que la empresa tuvo alguna vez)
    wa, pa = _where(f, alias="m")
    cov = q(f"""SELECT coalesce(t.nivel, 'NI') nivel, sum(m.cif) cif FROM mercado m
                LEFT JOIN imp_total t ON t.importador_key = m.importador_key AND t.mes = m.mes
                WHERE {wa} GROUP BY 1""", pa).set_index("nivel")["cif"]
    tot = cov.sum() or 1
    alta = (cov.get("rut", 0) + cov.get("verificada", 0)) / tot
    prob, traz = cov.get("probable", 0) / tot, cov.get("trazado", 0) / tot
    st.caption(f"**Cobertura de identificación del CIF filtrado:** 🟢 alta {pct(alta)} · 🟡 probable {pct(prob)} · "
               f"⚪ trazado sin nombre {pct(traz)} · sin identificar {pct(1 - alta - prob - traz)}. "
               "Nombres de importador = INFERIDOS (Aduana los anonimiza); totales por producto, país y período = MEDIDOS.")


# ============================================================
# Pestañas
# ============================================================
def _tab_resumen(f):
    w, p = _where(f)
    top = q(f"""SELECT coalesce(i.importador, 'No identificados') imp, coalesce(i.nivel,'NI') nivel, m.importador_key k, sum(m.cif) cif
                FROM mercado m LEFT JOIN importadores i USING (importador_key)
                WHERE {w} AND m.importador_key <> 'NI' GROUP BY 1, 2, 3 ORDER BY cif DESC LIMIT 15""", p)
    wu, pu = _where(_ux(f))
    ux = q(f"SELECT sum(cif) c FROM mercado WHERE {wu}", pu).iloc[0]["c"]
    if UX not in top.k.tolist() and ux:
        nivel_ux = q("SELECT nivel FROM importadores WHERE importador_key = ?", (UX,))
        top = pd.concat([top, pd.DataFrame([{"imp": "UnionX · Comercial Innovatek SpA", "k": UX, "cif": ux,
                                              "nivel": nivel_ux.nivel.iloc[0] if len(nivel_ux) else "verificada"}])])
    tipos = q(f"SELECT tipo, sum(cif) cif FROM mercado WHERE {w} GROUP BY 1 ORDER BY 2 DESC LIMIT 15", p)
    c1, c2 = st.columns(2)
    with c1:
        if len(top):
            lider = top.iloc[0]
            st.markdown(f"**{lider.imp} lidera lo filtrado con {mm(lider.cif)}**")
            items = [(f"{NIVEL_ICO.get(r.nivel, '')} {r.imp[:38]}", r.cif / 1e6, ECH.EMF if r.k == UX else ECH.GRAY)
                     for r in top.itertuples()]
            ECH.render(ECH.barras_h(items, unidad="US$ M", pct=True, dec=1, color_max=False), height=40 + 28 * len(items))
            st.caption("UnionX en azul (siempre incluido). Solo importadores con identidad.")
    with c2:
        if len(tipos):
            st.markdown(f"**{tipos.iloc[0].tipo} es el tipo de producto que más mueve: {mm(tipos.iloc[0].cif)}**")
            ECH.render(ECH.barras_h([(t.tipo[:40], t.cif / 1e6) for t in tipos.itertuples()], unidad="US$ M", dec=1),
                       height=40 + 28 * len(tipos))


def _tab_mercado(f):
    w, p = _where(f)
    wu, pu = _where(_ux(f))
    s = q(f"SELECT mes, sum(cif) cif FROM mercado WHERE {w} GROUP BY 1 ORDER BY 1", p)
    su = q(f"SELECT mes, sum(cif) cif FROM mercado WHERE {wu} GROUP BY 1 ORDER BY 1", pu)
    if s.empty:
        st.info("Sin datos para los filtros."); return
    s = s.merge(su.rename(columns={"cif": "ux"}), on="mes", how="left").fillna({"ux": 0})
    sel = f["importadores"]
    et = "Mercado" if not sel else nombre_imp(sel[0]) if len(sel) == 1 else "Selección"
    pico = s.loc[s.cif.idxmax()]
    st.markdown(f"**{et}: el mes más fuerte fue {mes_txt(pico.mes)} con {mm(pico.cif)} · UnionX en línea (eje derecho)**")
    _barras_linea([mes_txt(m) for m in s.mes], f"{et} (US$ M)", (s.cif / 1e6).round(3).tolist(),
                  "UnionX (US$ M)", (s.ux / 1e6).round(3).tolist())
    st.caption("Barras = lo seleccionado (eje izquierdo). Línea azul = UnionX con los mismos productos (eje derecho). "
               "Filtra un importador para compararlo mes a mes contra nosotros.")
    ult = f["hasta"]; y, m = int(ult[:4]), int(ult[5:7])
    st.markdown(f"**Comparación interanual · ene–{mes_txt(ult)[:3]} {y} vs {y - 1} (mismo período, sin mezclar temporadas)**")
    w2, p2 = _where(dict(f, desde=f"{y-1}-01", hasta=ult))
    yoy = q(f"""WITH b AS (SELECT tipo, left(mes,4) anio, unidad_cmp, sum(cif) cif, sum(fob_u) fob, sum(unidades) cant
                           FROM mercado WHERE {w2} AND substr(mes, 6, 2) <= ? GROUP BY 1, 2, 3),
                     u AS (SELECT tipo, arg_max(unidad_cmp, cant) unidad FROM b WHERE unidad_cmp IS NOT NULL GROUP BY 1)
                SELECT b.tipo, u.unidad,
                       sum(b.cif) FILTER (WHERE anio = ?) cif_ant, sum(b.cif) FILTER (WHERE anio = ?) cif_act,
                       sum(b.fob) FILTER (WHERE anio = ? AND b.unidad_cmp = u.unidad) fob_ant,
                       sum(b.cant) FILTER (WHERE anio = ? AND b.unidad_cmp = u.unidad) q_ant,
                       sum(b.fob) FILTER (WHERE anio = ? AND b.unidad_cmp = u.unidad) fob_act,
                       sum(b.cant) FILTER (WHERE anio = ? AND b.unidad_cmp = u.unidad) q_act
                FROM b LEFT JOIN u USING (tipo) GROUP BY 1, 2 ORDER BY cif_act DESC NULLS LAST LIMIT 25""",
            p2 + (f"{m:02d}", str(y - 1), str(y), str(y - 1), str(y - 1), str(y), str(y)))
    if not yoy.empty:
        pa, pb = yoy.fob_ant / yoy.q_ant, yoy.fob_act / yoy.q_act
        tabla = pd.DataFrame({
            "Tipo": yoy.tipo, "Unidad": yoy.unidad.map(lambda u: UNIDAD_TXT.get(u, "—")),
            f"CIF {y-1} (US$ M)": (yoy.cif_ant / 1e6).round(2), f"CIF {y} (US$ M)": (yoy.cif_act / 1e6).round(2),
            "Var. CIF": ((yoy.cif_act / yoy.cif_ant - 1) * 100).round(1),
            "Efecto precio (FOB por unidad)": ((pb / pa - 1) * 100).round(1),
            "Efecto volumen (unidades)": ((yoy.q_act / yoy.q_ant - 1) * 100).round(1),
        })
        st.dataframe(tabla, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.1f%%")
                                    for c in ["Var. CIF", "Efecto precio (FOB por unidad)", "Efecto volumen (unidades)"]})
        st.caption("DERIVADO. Unidades comparables (unidad, set o par): en líneas declaradas en kilo neto se usa la cantidad "
                   "física que la propia DIN trae en la observación 99.")


def _precio_importadores(f, tipo, unidad, limite=20) -> pd.DataFrame:
    w, p = _where(dict(f, tipos=[tipo]), alias="m")
    df = q(f"""SELECT m.importador_key k, coalesce(i.importador, 'No identificados') imp, coalesce(i.nivel,'NI') nivel,
                      sum(m.fob_u) fob, sum(m.unidades) cant, sum(m.cif) cif
               FROM mercado m LEFT JOIN importadores i USING (importador_key)
               WHERE {w} AND m.unidad_cmp = ? AND m.unidades > 0 GROUP BY 1, 2, 3
               ORDER BY cant DESC LIMIT {limite}""", p + (unidad,))
    df["pu"] = df.fob / df.cant
    return df


def _mi_sku(f: dict, min_unid: int = 500, banda: float = 2.0):
    """Flujo 1 en pantalla: mis SKU elegidos contra quienes compran su tipo en su mismo rango de precio."""
    comp = XL.competidores(q, _where, f, UX, min_unid)
    t = XL.comparar_skus(XL.mis_skus(q, f), comp, min_unid, banda)
    if t.empty:
        st.info("Sin costeos nuestros de esos SKU en el período."); return
    st.markdown(f"#### Mi SKU vs mercado · comparables = mismo tipo, entre 1/{banda:g} y {banda:g}× nuestro FOB, ≥{min_unid:,} u")
    for c in ("n", "p50", "percentil", "mejor_importador", "mejor_fob_u", "mejor_unidades", "mejor_dias", "mejor_prov",
              "mejor_forwarder", "mejor_trae", "p50_tipo"):
        if c not in t:
            t[c] = None
    st.dataframe(pd.DataFrame({
        "SKU": t.sku, "Producto": t.producto, "Nuestro FOB US$/u": t.fob.round(2), "Comparables": t.n,
        "Mediana banda US$/u": t.p50.astype(float).round(2), "% que compra más barato": (100 * t.percentil.astype(float)).round(0),
        "Mejor importador": t.mejor_importador, "Su FOB US$/u": t.mejor_fob_u.astype(float).round(2),
        "Sus unidades": t.mejor_unidades, "Sus días": t.mejor_dias, "Su proveedor": t.mejor_prov,
        "Su forwarder": t.mejor_forwarder, "Qué trae": t.mejor_trae,
        "Mediana del tipo completo": t.p50_tipo.astype(float).round(2)}),
        hide_index=True, width="stretch",
        column_config={"% que compra más barato": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=100)})
    st.caption("Para ver cómo lo hace el mejor (a quién compra, puerto, forwarder, días), ábrelo en 'Ficha importador'. "
               "El ahorro potencial por año, con supuestos editables, está en el Excel de decisión (hoja 1).")


def _tab_precios(f):
    if f.get("skus"):
        _mi_sku(f)
        st.divider()
    w, p = _where(dict(f, importadores=[]))
    tipos = q(f"SELECT tipo, sum(cif) cif FROM mercado WHERE {w} GROUP BY 1 ORDER BY 2 DESC", p)
    if tipos.empty:
        st.info("Sin datos para los filtros."); return
    ux_t = q(f"SELECT tipo FROM mercado WHERE {w} AND importador_key = '{UX}' GROUP BY 1 ORDER BY sum(cif) DESC LIMIT 1", p)
    lista = tipos.tipo.tolist()
    pref = (f["tipos"][0] if f["tipos"] and f["tipos"][0] in lista
            else ux_t.tipo.iloc[0] if len(ux_t) and ux_t.tipo.iloc[0] in lista else lista[0])
    t_sel = st.selectbox("Tipo de producto a comparar", lista, index=lista.index(pref),
                         help="Por defecto, el tipo donde más compramos nosotros.")
    wt, pt = _where(dict(f, tipos=[t_sel], importadores=[]))
    un = q(f"""SELECT unidad_cmp, sum(unidades) u FROM mercado WHERE {wt} AND unidades > 0
               GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", pt)
    if un.empty:
        st.info("Sin cantidades en unidades para este tipo."); return
    unidad = un.unidad_cmp.iloc[0]
    ut = UNIDAD_TXT.get(unidad, unidad)
    df = _precio_importadores(dict(f, importadores=[]), t_sel, unidad)
    if UX not in df.k.tolist():
        df = pd.concat([df, _precio_importadores(_ux(f), t_sel, unidad, limite=1)])
    otros_todos = df[(df.k != UX) & (df.k != "NI")]
    otros = _plausibles(otros_todos)
    n_fuera = len(otros_todos) - len(otros)
    df = df[df.k.isin(otros.k) | (df.k == UX) | (df.k == "NI")]
    med = otros.pu.median() if len(otros) else None
    uxr = df[df.k == UX]
    if len(uxr) and med:
        pos = (otros.pu < uxr.pu.iloc[0]).mean()
        st.markdown(f"**{t_sel}: UnionX paga {usd(uxr.pu.iloc[0])} por {ut} FOB · mediana de los importadores "
                    f"{usd(med)} · somos más caros que el {pct(pos, 0)} de ellos**")
    else:
        st.markdown(f"**{t_sel}: mediana de los importadores {usd(med)} por {ut} FOB**")
    items = [(f"{NIVEL_ICO.get(r.nivel, '')} {r.imp[:34]} ({ECH.es(r.cant)} {ut}s)", round(r.pu, 2),
              ECH.EMF if r.k == UX else ECH.GRAY) for r in df.sort_values("pu").itertuples()]
    ECH.render(ECH.barras_h(items, unidad=f"US$/{ut}", pct=False, dec=2, color_max=False), height=40 + 28 * len(items))
    st.caption(f"DERIVADO: FOB por {ut} ponderado (Σ FOB / Σ {ut}s) de los 20 importadores con más volumen + UnionX. "
               "Incluye líneas declaradas en kilo neto convertidas con la cantidad física de la propia DIN (obs. 99). "
               "Siguiente paso: en 'Ficha importador' ves CÓMO compra el que lo hace mejor."
               + (f" Se excluyeron {n_fuera} importadores con precio implausible (< 1/5 o > 5× la mediana: "
                  "unidades mal declaradas)." if n_fuera else ""))
    dist = q("""SELECT anio, p10, p25, p50, p75, p90, lineas FROM precios_dist
                WHERE tipo = ? AND unidad_cmp = ? AND universo = ? ORDER BY anio""",
             (t_sel, unidad, "Adyacente" if f["mirada"] == "Adyacente" else "Núcleo"))
    if not dist.empty:
        st.markdown(f"**Rango de precios por línea (p10–p90) · {t_sel}**")
        ECH.render(ECH.rango_h([(f"{r.anio} · mediana {ECH.es(r.p50, 2)}", round(r.p10, 2), round(r.p90, 2))
                                for r in dist.itertuples()], unidad=f"US$/{ut}"), height=60 + 40 * len(dist))
    nos = q("""SELECT sum(internado_usd * qty) / sum(qty) internado, sum(fob_usd * qty) / sum(qty) fob,
                      sum(qty) qty, max(embarque) ult FROM nosotros WHERE tipo = ?""", (t_sel,))
    if len(nos) and nos.iloc[0].qty:
        r = nos.iloc[0]
        st.info(f"**Nuestro costo (precosteos):** FOB {usd(r.fob)} · internado {usd(r.internado)} por unidad · "
                f"{ECH.es(r.qty)} u costeadas (último embarque {r.ult}). El internado suma flete, gastos Chile y TC: "
                "para comparar con otros importadores usa el FOB.")


def _tab_proveedores(f):
    w, p = _where(f)
    df = q(f"""SELECT proveedor, any_value(proveedor_tipo) tipo_prov, sum(cif) cif,
                      count(DISTINCT importador_key) FILTER (WHERE importador_key <> 'NI') imps, arg_max(pais_origen, cif) pais
               FROM proveedores WHERE {w} GROUP BY 1 ORDER BY cif DESC""", p)
    if df.empty:
        st.info("Sin datos para los filtros."); return
    st.info("**Proveedor = vendedor extranjero declarado en la DIN** (campo marca con sufijo -F): quien le factura al "
            "importador, sea fábrica o trading/agente (p.ej. Topwill es nuestro agente). **No es el forwarder**: el "
            "forwarder solo organiza el transporte (ver Logística). La DIN no dice si es fábrica o trading: la columna "
            "'Tipo' es indicativa por el nombre, salvo los verificados a mano.")
    tot = df.cif.sum()
    decl = df[df.proveedor != "(no declarado)"]
    st.markdown(f"**El {pct(decl.cif.sum() / tot)} del CIF trae el proveedor declarado**")
    c1, c2 = st.columns(2)
    with c1:
        top = decl.head(15)
        ECH.render(ECH.barras_h([(r.proveedor[:40], r.cif / 1e6) for r in top.itertuples()], unidad="US$ M", dec=1),
                   height=40 + 28 * len(top))
    with c2:
        tp = df.groupby("tipo_prov").cif.sum().sort_values(ascending=False)
        st.markdown("**Fábrica o trading** (indicativo)")
        ECH.render(ECH.barras_h([(str(k), v / 1e6) for k, v in tp.items()], unidad="US$ M", dec=1),
                   height=40 + 28 * len(tp))
    tabla = decl.head(80).assign(**{"CIF (US$ M)": lambda x: (x.cif / 1e6).round(3)})
    st.dataframe(tabla.rename(columns={"proveedor": "Proveedor declarado", "tipo_prov": "Tipo", "imps": "Importadores",
                                       "pais": "País de origen"})[["Proveedor declarado", "Tipo", "País de origen",
                                                                   "CIF (US$ M)", "Importadores"]],
                 hide_index=True, width="stretch", height=360)


def _tab_logistica(f):
    d = _log(f)
    du = _log(_ux(f))
    if not d["n"]:
        st.info("Sin DIN para los filtros."); return
    st.info("**Forwarder ≠ naviera.** El **forwarder** (NVOCC / agente de carga, p.ej. Shanghai Syntrans, SEKO) emite el "
            "B/L *house* y organiza el embarque; la **naviera** (Maersk, MSC, COSCO…) es la dueña del buque y emite el B/L "
            "*master*. Si en la DIN el emisor del documento es la misma línea, el embarque fue **directo con la línea**.")
    c = st.columns(4)
    c[0].metric("Flete+seguro / FOB · selección", pct(d["flete"]))
    c[1].metric("Flete+seguro / FOB · UnionX", pct(du["flete"]))
    c[2].metric("Días embarque→DIN · selección", ECH.es(d["dias"]) if d["dias"] is not None else "—")
    c[3].metric("Días embarque→DIN · UnionX", ECH.es(du["dias"]) if du["dias"] is not None else "—")
    st.caption("DERIVADO a nivel DIN, ponderado por el CIF de los productos filtrados. Flete y seguro = declarados en la DIN "
               "(sin agente de aduana, puerto ni transporte local). Días = documento de transporte → aceptación DIN (marítimo).")
    c1, c2, c3 = st.columns(3)
    for col, campo, titulo in ((c1, "forwarder", "Forwarder (emisor del B/L)"), (c2, "naviera", "Naviera / transportista"),
                               (c3, "puerto_embarque", "Puerto de embarque")):
        g = _log_por(f, campo).head(10)
        with col:
            st.markdown(f"**{titulo}**")
            ECH.render(ECH.barras_h([(str(k)[:30], v / 1e6) for k, v in g.items()], unidad="US$ M", dec=1),
                       height=40 + 28 * len(g))
    mod = _log_por(f, "modalidad")
    modu = _log_por(_ux(f), "modalidad") if du["n"] else pd.Series(dtype=float)
    vias = _log_por(f, "via")
    st.caption("Modalidad · selección: " + " · ".join(f"{k} {pct(v / mod.sum())}" for k, v in mod.items()) +
               (" | UnionX: " + " · ".join(f"{k} {pct(v / modu.sum())}" for k, v in modu.items()) if len(modu) else "") +
               "  ·  Vía: " + " · ".join(f"{k} {pct(v / vias.sum())}" for k, v in vias.items()))


def _tab_importadores(f):
    w, p = _where(f)
    df = q(f"""WITH m AS (SELECT importador_key, sum(cif) cif, count(DISTINCT mes) meses,
                                 arg_max(tipo, cif) tipo_top FROM mercado WHERE {w} AND importador_key <> 'NI' GROUP BY 1),
                    dn AS (SELECT importador_key, count(DISTINCT id_operacion) din FROM din_tipo WHERE {w} GROUP BY 1),
                    pr AS (SELECT importador_key,
                                  arg_max(proveedor, cif) FILTER (WHERE proveedor <> '(no declarado)') prov,
                                  max(cif) FILTER (WHERE proveedor <> '(no declarado)') / sum(cif) prov_pct FROM (
                              SELECT importador_key, proveedor, sum(cif) cif FROM proveedores
                              WHERE {w} GROUP BY 1, 2) GROUP BY 1)
               SELECT i.importador, i.rut_fmt, i.nivel, i.pct_alta, i.fuente_nombre, m.cif, dn.din, m.meses, m.tipo_top,
                      pr.prov, pr.prov_pct, tt.cif_total
               FROM m LEFT JOIN importadores i USING (importador_key) LEFT JOIN pr USING (importador_key)
               LEFT JOIN dn USING (importador_key)
               LEFT JOIN (SELECT importador_key, sum(cif_total) cif_total FROM imp_total WHERE mes BETWEEN ? AND ?
                          GROUP BY 1) tt USING (importador_key)
               ORDER BY m.cif DESC LIMIT 300""", p + p + p + (f["desde"], f["hasta"]))
    tot = q(f"SELECT sum(cif) c FROM mercado WHERE {w}", p).iloc[0]["c"] or 1
    df["Participación"] = (100 * df.cif / tot).round(2)
    df["CIF (US$ M)"] = (df.cif / 1e6).round(3)
    df["CIF total empresa (US$ M)"] = (df.cif_total / 1e6).round(3)
    df["% de la empresa en lo filtrado"] = (100 * df.cif / df.cif_total).round(0)
    df["Evidencia"] = [ev_txt(n, a) for n, a in zip(df.nivel, df.pct_alta)]
    # un proveedor que pesa <5% del CIF no es "el principal" (p.ej. 12 líneas entre 8.600 sin proveedor declarado)
    df["prov"] = [f"{pv} · {pct(pp, 0)}" if isinstance(pv, str) and pd.notna(pp) and pp >= 0.05 else "no declarado"
                  for pv, pp in zip(df.prov, df.prov_pct)]
    st.markdown(f"**{len(df)} importadores con identidad en lo filtrado** · para ver cómo trabaja cada uno, abre 'Ficha importador'")
    st.dataframe(df.rename(columns={"importador": "Importador", "rut_fmt": "RUT", "din": "DIN", "meses": "Meses activos",
                                    "tipo_top": "Tipo principal", "prov": "Proveedor principal",
                                    "fuente_nombre": "Fuente del nombre"})
                 [["Importador", "RUT", "Evidencia", "Fuente del nombre", "CIF (US$ M)", "Participación",
                   "CIF total empresa (US$ M)", "% de la empresa en lo filtrado", "DIN",
                   "Meses activos", "Tipo principal", "Proveedor principal"]],
                 hide_index=True, width="stretch", height=560,
                 column_config={"Participación": st.column_config.NumberColumn(format="%.2f%%")})
    st.caption("Evidencia (se asigna mes a mes y aquí se pondera por CIF): 🟢 verificada = ≥90% de su CIF en meses amarrados "
               "al RUT por ≥2 códigos trazadores · 🟡 probable = hay meses enganchados por 1 código + misma comuna o por sus "
               "marcas propias (entre paréntesis, cuánto está verificado) · ⚪ trazado sin nombre. Fuente del nombre: manual · "
               "SII (nómina de razón social) · Registro de Empresas · ChileCompra · solo RUT (personas naturales).")


def _total_empresa(k: str, f: dict, cif_filtrado, nombre: str):
    """Todo lo que importa la empresa en el período (todos sus productos) vs lo que se ve en el filtro (nuestros
    productos). Sin esto no cuadra con un análisis por empresa: p.ej. Builder US$ 12,5 M total vs US$ 5,6 M en núcleo."""
    if not {"imp_total", "imp_fuera"} <= set(TABLAS_OK()):
        return
    tot = q("SELECT sum(cif_total) c, sum(din_total) d FROM imp_total WHERE importador_key = ? AND mes BETWEEN ? AND ?",
            (k, f["desde"], f["hasta"])).iloc[0]
    if not tot.c:
        return
    part = (cif_filtrado or 0) / tot.c
    st.info(f"**{nombre} importa en total {mm(tot.c)} en {int(tot.d or 0)} DIN** en el período, con todos sus productos. "
            f"De eso, **{pct(part, 0)} ({mm(cif_filtrado)})** es de lo que muestra el filtro (los productos que traemos "
            "nosotros). El resto son productos que UnionX no importa.")
    fuera = q("""SELECT hs4, arg_max(ejemplo, cif) ejemplo, sum(cif) cif FROM imp_fuera
                 WHERE importador_key = ? AND mes BETWEEN ? AND ? GROUP BY 1 ORDER BY 3 DESC LIMIT 10""",
              (k, f["desde"], f["hasta"]))
    if len(fuera):
        with st.expander("¿Qué más importa? (fuera de lo que traemos nosotros)"):
            st.dataframe(pd.DataFrame({"Partida (4 díg.)": fuera.hs4, "Ejemplo de producto": fuera.ejemplo,
                                       "CIF (US$ M)": (fuera.cif / 1e6).round(3),
                                       "% del total de la empresa": (100 * fuera.cif / tot.c).round(1)}),
                         hide_index=True, width="stretch")


@st.cache_data(ttl=3600, show_spinner=False)
def TABLAS_OK() -> list:
    return [t for t in TABLAS if (HUB / f"{t}.parquet").exists()]


# ============================================================
# Tamaño de empresas: TODO lo que importa cada una (Andrés, 30-sep-2026: "en ninguna parte puedo ver cuánto importa
# total una empresa X, no solo comparando contra lo que nosotros traemos; sirve para dimensionarla")
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
def _capitulos() -> dict:
    p = HUB / "capitulos_sa.json"
    if not p.exists():
        return {}
    return {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def _sin_tildes(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").upper()


def _meses_rango(d: str, h: str) -> list:
    y, m, out = int(d[:4]), int(d[5:7]), []
    while f"{y}-{m:02d}" <= h:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _ranking_empresas(d: str, h: str, rubros: tuple = (), solo_rut: bool = True) -> pd.DataFrame:
    """Una fila por empresa con todo lo que importa en el período, ordenada por CIF total (o por el CIF en los rubros
    elegidos). Ignora los filtros de producto del hub. 'Nuestros productos' = núcleo sin partidas vecinas."""
    y, m = int(h[:4]), int(h[5:7])
    f_rub = f"hs2 IN ({','.join('?' * len(rubros))})" if rubros else "TRUE"
    df = q(f"""
        WITH t AS (SELECT importador_key, sum(cif_total) cif_total, sum(din_total) din, count(*) meses,
                          coalesce(sum(cif_total) FILTER (WHERE nivel IN ('rut', 'verificada')) / sum(cif_total), 0) pct_alta
                   FROM imp_total WHERE mes BETWEEN ? AND ? GROUP BY 1),
             r AS (SELECT importador_key, left(hs4, 2) hs2, sum(cif) cif FROM imp_hs4 WHERE mes BETWEEN ? AND ? GROUP BY 1, 2),
             rt AS (SELECT importador_key, arg_max(hs2, cif) hs2_top, max(cif) / sum(cif) pct_top,
                           sum(cif) FILTER (WHERE {f_rub}) cif_rubro FROM r GROUP BY 1),
             nu AS (SELECT importador_key, sum(cif) cif_nuestro FROM mercado
                    WHERE mes BETWEEN ? AND ? AND universo = 'Núcleo' AND NOT coalesce(vecina, false) GROUP BY 1),
             ya AS (SELECT importador_key, sum(cif_total) FILTER (WHERE mes BETWEEN ? AND ?) a,
                           sum(cif_total) FILTER (WHERE mes BETWEEN ? AND ?) b FROM imp_total GROUP BY 1)
        SELECT t.importador_key, i.importador, i.rut_fmt,
               CASE WHEN t.importador_key LIKE 'TRZ:%' THEN 'trazado' WHEN t.pct_alta >= 0.9 THEN 'verificada'
                    ELSE 'probable' END nivel, t.pct_alta, i.fuente_nombre, t.cif_total, t.din, t.meses,
               rt.hs2_top, rt.pct_top, rt.cif_rubro, nu.cif_nuestro, ya.a / nullif(ya.b, 0) - 1 AS var
        FROM t JOIN importadores i USING (importador_key) LEFT JOIN rt USING (importador_key)
        LEFT JOIN nu USING (importador_key) LEFT JOIN ya USING (importador_key)
        WHERE {"t.importador_key LIKE 'RUT:%'" if solo_rut else "TRUE"}""",
           (d, h, d, h) + tuple(rubros) + (d, h, f"{y}-01", h, f"{y - 1}-01", f"{y - 1}-{m:02d}"))
    orden = "cif_rubro" if rubros else "cif_total"
    df = df[df[orden].fillna(0) > 0].sort_values(orden, ascending=False).reset_index(drop=True)
    df["puesto"] = range(1, len(df) + 1)
    return df


def _cobertura_total(d: str, h: str) -> str:
    tot = sum((c.get("cif_din_musd") or 0) for c in calidad().get("cuadratura", []) if d <= c["mes"] <= h) * 1e6
    if not tot:
        return ""
    at = q("""SELECT sum(cif_total) FILTER (WHERE importador_key LIKE 'RUT:%') a,
                     sum(cif_total) FILTER (WHERE importador_key LIKE 'TRZ:%') b FROM imp_total WHERE mes BETWEEN ? AND ?""",
           (d, h)).iloc[0]
    return (f"Del CIF que importó Chile en el período ({mm(tot)}), {pct((at.a or 0) / tot, 0)} queda en una empresa con RUT y "
            f"{pct((at.b or 0) / tot, 0)} en empresas trazadas sin nombre; el resto no se atribuye. Por eso cada monto es un piso: "
            "lo que una empresa trae sin identificar no se le suma.")


def _excel_tamano(rk: pd.DataFrame, d: str, h: str, rubros: list, solo_rut: bool, cob_txt: str) -> bytes:
    cap = _capitulos()
    top = rk.head(300).importador_key.tolist()
    if UX in rk.importador_key.values and UX not in top:
        top.append(UX)
    ph = ",".join("?" * len(top))
    pos = {k_: i for i, k_ in enumerate(top)}
    rb = q_sin_cache(f"""SELECT importador_key, left(hs4, 2) hs2, sum(cif) cif FROM imp_hs4
               WHERE mes BETWEEN ? AND ? AND importador_key IN ({ph}) GROUP BY 1, 2""", (d, h) + tuple(top))
    rb = rb.assign(o=rb.importador_key.map(pos)).sort_values(["o", "cif"], ascending=[True, False])
    pt = q_sin_cache(f"""SELECT importador_key, hs4, arg_max(ejemplo, cif) ejemplo, sum(cif) cif FROM imp_hs4
               WHERE mes BETWEEN ? AND ? AND importador_key IN ({ph}) GROUP BY 1, 2
               QUALIFY row_number() OVER (PARTITION BY importador_key ORDER BY sum(cif) DESC) <= 10""", (d, h) + tuple(top))
    pt = pt.assign(o=pt.importador_key.map(pos)).sort_values(["o", "cif"], ascending=[True, False])
    filtros = [("Período", f"{mes_txt(d)} → {mes_txt(h)}"),
               ("Rubros", ", ".join(f"{x} {cap.get(x, '')}" for x in rubros) or "todos"),
               ("Empresas", "solo con RUT" if solo_rut else "con RUT + trazadas sin nombre"),
               ("Fuente", "DIN públicas de Aduana (datos.gob.cl) · nombres: Nómina de Razón Social del SII + Registro de Empresas")]
    return XL.tamano(rk, rb, pt, cap, len(_meses_rango(d, h)), UX, filtros, cob_txt, con_rubro=bool(rubros))


def _tab_tamano(f):
    if not {"imp_total", "imp_hs4"} <= set(TABLAS_OK()):
        st.info("Falta regenerar los cubos del radar (radar-aduana/pipeline/p9_cubos.py)."); return
    cap = _capitulos()
    d, h = f["desde"], f["hasta"]
    meses = _meses_rango(d, h)
    st.caption(f"Todo lo que importa cada empresa entre {mes_txt(d)} y {mes_txt(h)} ({len(meses)} meses), con TODOS sus "
               "productos. Esta pestaña usa solo el período de arriba: ignora mirada, categoría, tipo e importador.")
    rub = q("SELECT left(hs4, 2) hs2, sum(cif) cif FROM imp_hs4 WHERE mes BETWEEN ? AND ? GROUP BY 1 ORDER BY 2 DESC", (d, h))
    c1, c2, c3 = st.columns([2.2, 2.2, 1])
    buscar = c1.text_input("Buscar empresa (nombre o RUT)", placeholder="p. ej. Builder · 77.367.504 · Falabella", key="tam_buscar")
    rubros = c2.multiselect("Rubro (capítulo del arancel)", _con_elegidos(rub.hs2.tolist(), "tam_rubros"),
                            placeholder="Todos los rubros", key="tam_rubros",
                            format_func=lambda x: f"{x} · {cap.get(x, 'Capítulo ' + x)}",
                            help="Ordena por lo que cada empresa importa en esos rubros (p. ej. 85 = electrónica, 94 = muebles "
                                 "e iluminación). El total de cada empresa se sigue mostrando.")
    solo_rut = c3.toggle("Solo con RUT", value=True, key="tam_solo_rut",
                         help="Oculta las empresas trazadas sin nombre (⚪): son empresas reales, pero sin RUT.")
    rk = _ranking_empresas(d, h, tuple(rubros), solo_rut)
    if rk.empty:
        st.info("Sin empresas para el período y rubro."); return
    orden = "cif_rubro" if rubros else "cif_total"
    ux_tot = q("SELECT sum(cif_total) c FROM imp_total WHERE importador_key = ? AND mes BETWEEN ? AND ?", (UX, d, h)).iloc[0]["c"]
    ux_r = rk[rk.importador_key == UX]
    lider = rk.iloc[0]
    txt_rub = f" en {', '.join(cap.get(x, x).lower() for x in rubros)}" if rubros else ""
    st.markdown(f"**{ECH.es(len(rk))} empresas{' con RUT' if solo_rut else ''} importaron{txt_rub} en el período. La más grande es "
                f"{lider.importador} con {mm(lider[orden])}"
                + (f"; UnionX está en el puesto #{ECH.es(int(ux_r.puesto.iloc[0]))} con {mm(ux_r[orden].iloc[0])}**"
                   if len(ux_r) else "**"))

    vista = rk
    if buscar.strip():
        s_ = _sin_tildes(buscar.strip())
        m_ = rk.importador.map(_sin_tildes).str.contains(s_, regex=False, na=False)
        num = re.sub(r"[^0-9K]", "", s_)
        if len(num) >= 5:
            m_ |= rk.rut_fmt.fillna("").str.replace(".", "", regex=False).str.replace("-", "", regex=False).str.contains(num, regex=False)
        vista = rk[m_]
        if vista.empty:
            st.warning(f"No encontré '{buscar}' entre las empresas que importaron en el período"
                       + (" (prueba apagando 'Solo con RUT' o quitando el rubro)." if solo_rut or rubros else "."))
            return
    tabla = vista.head(300)
    if len(ux_r) and UX not in tabla.importador_key.values:
        tabla = pd.concat([tabla, ux_r])
    out = pd.DataFrame({
        "Puesto": tabla.puesto,
        "Empresa": [("🔵 " if k_ == UX else "") + str(n_) for k_, n_ in zip(tabla.importador_key, tabla.importador)],
        "RUT": tabla.rut_fmt,
        "Evidencia": [ev_txt(n_, a_) for n_, a_ in zip(tabla.nivel, tabla.pct_alta)],
    })
    if rubros:
        out["CIF en el rubro (US$ M)"] = (tabla.cif_rubro / 1e6).round(2)
    out["CIF total (US$ M)"] = (tabla.cif_total / 1e6).round(2)
    out["Promedio mensual (US$ M)"] = (tabla.cif_total / len(meses) / 1e6).round(3)
    out["DIN"] = tabla.din
    out["Meses con importaciones"] = tabla.meses
    col_var = f"Var. ene–{mes_txt(h)[:3]} {h[2:4]} vs {int(h[2:4]) - 1}"
    out[col_var] = (100 * tabla["var"]).round(0)
    out["Rubro principal"] = [f"{cap.get(x, x)} · {pct(p_, 0)}" if isinstance(x, str) else "—"
                              for x, p_ in zip(tabla.hs2_top, tabla.pct_top)]
    out["En nuestros productos"] = (100 * tabla.cif_nuestro.fillna(0) / tabla.cif_total).round(1)
    out["Veces UnionX"] = (tabla.cif_total / ux_tot).round(1) if ux_tot else None
    st.dataframe(out, hide_index=True, width="stretch", height=460, column_config={
        col_var: st.column_config.NumberColumn(format="%.0f%%", help="CIF de enero al último mes del período vs lo mismo del año anterior."),
        "En nuestros productos": st.column_config.NumberColumn(
            format="%.1f%%", help="Parte de su CIF que es de los tipos de producto que traemos nosotros (núcleo). "
                                  "0% = no compite con lo nuestro."),
        "Veces UnionX": st.column_config.NumberColumn(format="%.1f×", help="Su CIF total del período ÷ el de UnionX."),
    })
    cob_txt = _cobertura_total(d, h)
    st.caption(f"{'Primeras 300 de ' + ECH.es(len(vista)) + ' · ' if len(vista) > 300 else ''}UnionX (🔵) siempre al final como "
               f"referencia. {cob_txt}")

    # ---- detalle de una empresa
    st.markdown("#### Detalle de una empresa")
    opciones = list(dict.fromkeys(tabla.importador_key.tolist()))
    lab = {r.importador_key: f"#{r.puesto} · {NIVEL_ICO.get(r.nivel, '')} {r.importador} · {mm(r.cif_total)}"
           for r in tabla.itertuples()}
    k = st.selectbox("Empresa a dimensionar", opciones, format_func=lambda x: lab.get(x, x))
    fila = rk[rk.importador_key == k].iloc[0]
    meta = q("SELECT * FROM importadores WHERE importador_key = ?", (k,)).iloc[0]
    st.markdown(f"### {meta.importador}")
    st.caption(f"RUT {meta.rut_fmt or '—'} · nombre: {meta.fuente_nombre} · importa en {meta.meses} de los meses de la base "
               f"({mes_txt(meta.primer_mes)} → {mes_txt(meta.ultimo_mes)})  \nEvidencia: {_evidencia_periodo(k, d, h)}")
    nuestro = 0 if pd.isna(fila.cif_nuestro) else fila.cif_nuestro
    c = st.columns(6)
    c[0].metric("CIF total del período", mm(fila.cif_total))
    c[1].metric("Promedio mensual", mm(fila.cif_total / len(meses)))
    c[2].metric("DIN", ECH.es(fila.din))
    c[3].metric("Puesto", f"#{ECH.es(int(fila.puesto))}", help="Entre las empresas del ranking de arriba (mismo período, rubro y "
                                                               "'Solo con RUT').")
    c[4].metric("Tamaño vs UnionX", f"{ECH.es(fila.cif_total / ux_tot, 1)}×" if ux_tot and k != UX else "—")
    c[5].metric("En nuestros productos", pct(nuestro / fila.cif_total, 0),
                help="CIF en los tipos de producto que traemos (núcleo) sobre su total.")
    s = q("SELECT mes, sum(cif_total) cif FROM imp_total WHERE importador_key = ? AND mes BETWEEN ? AND ? GROUP BY 1", (k, d, h))
    su = q("SELECT mes, sum(cif_total) cif FROM imp_total WHERE importador_key = ? AND mes BETWEEN ? AND ? GROUP BY 1", (UX, d, h))
    ms, mu = dict(zip(s.mes, s.cif)), dict(zip(su.mes, su.cif))
    st.markdown("#### ¿Cuánto importa cada mes? (barras = la empresa · línea = UnionX, misma escala)")
    _barras_linea([mes_txt(m_) for m_ in meses], f"{meta.importador[:28]} (US$ M)", [round(ms.get(m_, 0) / 1e6, 3) for m_ in meses],
                  "UnionX (US$ M)", [round(mu.get(m_, 0) / 1e6, 3) for m_ in meses], height=300, mismo_eje=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### ¿En qué rubros?")
        rb = q("""SELECT left(hs4, 2) hs2, sum(cif) cif FROM imp_hs4 WHERE importador_key = ? AND mes BETWEEN ? AND ?
                  GROUP BY 1 ORDER BY 2 DESC""", (k, d, h))
        items = [(f"{r.hs2} · {cap.get(r.hs2, '')}"[:40], r.cif / 1e6) for r in rb.head(10).itertuples()]
        if len(rb) > 10:
            items.append(("Otros rubros", rb.cif.iloc[10:].sum() / 1e6))
        if items:
            ECH.render(ECH.barras_h(items, unidad="US$ M", pct=True, dec=2), height=40 + 28 * len(items))
    with c2:
        st.markdown("#### ¿Qué productos trae?")
        pt = q("""SELECT hs4, arg_max(ejemplo, cif) ejemplo, sum(cif) cif FROM imp_hs4 WHERE importador_key = ? AND mes BETWEEN ? AND ?
                  GROUP BY 1 ORDER BY 3 DESC LIMIT 15""", (k, d, h))
        st.dataframe(pd.DataFrame({"Partida": pt.hs4, "Rubro": pt.hs4.str[:2].map(lambda x: cap.get(x, x)),
                                   "Producto de ejemplo": pt.ejemplo, "CIF (US$ M)": (pt.cif / 1e6).round(3),
                                   "% de su total": (100 * pt.cif / fila.cif_total).round(1)}),
                     hide_index=True, width="stretch", height=420)
    if nuestro > 0 and k != UX:
        st.caption("Para ver cómo compra lo que compite con lo nuestro (proveedores, flete, días, precio por unidad), elígela en "
                   "el filtro Importador de arriba o en 'Ficha importador'.")

    with st.expander("⬇️ Excel del ranking (todas las empresas + rubros y partidas de las 300 más grandes)"):
        firma = (d, h, tuple(rubros), solo_rut)
        if st.button("Preparar Excel del ranking", key="tam_xlsx_btn"):
            with st.spinner("Armando el Excel…"):
                st.session_state["tam_xlsx"] = (firma, _excel_tamano(rk, d, h, rubros, solo_rut, cob_txt))
        prep = st.session_state.get("tam_xlsx")
        if prep and prep[0] == firma:
            st.download_button("Descargar Excel", data=prep[1], file_name=f"radar_tamano_empresas_{d}_{h}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="tam_xlsx_dl")


def _tab_ficha(f):
    """Cómo lo hace un importador: a quién compra, cómo trae, de dónde, quién forwardea, cuánto demora, a cuánto compra."""
    w, p = _where(dict(f, importadores=[]))
    imps = q(f"""SELECT m.importador_key k, coalesce(i.importador, m.importador_key) imp, coalesce(i.nivel,'NI') nivel, sum(m.cif) cif
                 FROM mercado m LEFT JOIN importadores i USING (importador_key)
                 WHERE {w} AND m.importador_key NOT IN ('NI', '{UX}') GROUP BY 1, 2, 3 ORDER BY cif DESC LIMIT 400""", p)
    if imps.empty:
        st.info("Sin importadores identificados para los filtros."); return
    keys = imps.k.tolist()
    pref = next((k for k in f["importadores"] if k in keys), keys[0])
    lab = {r.k: f"{NIVEL_ICO.get(r.nivel, '')} {r.imp} · {mm(r.cif)}" for r in imps.itertuples()}
    k = st.selectbox("Importador a analizar (siempre contra UnionX, con los mismos productos y período)", keys,
                     index=keys.index(pref), format_func=lambda x: lab.get(x, x))
    fi, fu = dict(f, importadores=[k]), _ux(f)
    meta = q("SELECT * FROM importadores WHERE importador_key = ?", (k,)).iloc[0]
    st.markdown(f"### {meta.importador}")
    st.caption(f"RUT {meta.rut_fmt or '—'} (declarado por la empresa en jun-2024) · nombre: {meta.fuente_nombre} · "
               f"activo en {meta.meses} meses ({mes_txt(meta.primer_mes)} → {mes_txt(meta.ultimo_mes)})  \n"
               f"Evidencia: {_evidencia_periodo(k, f['desde'], f['hasta'])}")
    ri, ru = _resumen(fi), _resumen(fu)
    di, du = _log(fi), _log(fu)
    mi, mu = _log_por(fi, "modalidad"), _log_por(fu, "modalidad")
    tabla_kpi = pd.DataFrame([
        {"Indicador": "CIF (US$ M)", "Ellos": ri["cif"] / 1e6 if ri["cif"] else None, "UnionX": ru["cif"] / 1e6 if ru["cif"] else None},
        {"Indicador": "DIN", "Ellos": ri["din"], "UnionX": ru["din"]},
        {"Indicador": "Flete + seguro / FOB (%)", "Ellos": 100 * di["flete"] if di["flete"] is not None else None,
         "UnionX": 100 * du["flete"] if du["flete"] is not None else None},
        {"Indicador": "Días embarque → DIN (mediana)", "Ellos": di["dias"], "UnionX": du["dias"]},
        {"Indicador": "Directo con la línea (% CIF)", "Ellos": 100 * mi.get("Directo con la línea", 0) / mi.sum() if mi.sum() else None,
         "UnionX": 100 * mu.get("Directo con la línea", 0) / mu.sum() if mu.sum() else None},
    ])
    st.dataframe(tabla_kpi, hide_index=True, width="stretch",
                 column_config={"Ellos": st.column_config.NumberColumn(format="%.1f"),
                                "UnionX": st.column_config.NumberColumn(format="%.1f")})
    _total_empresa(k, f, ri["cif"], meta.importador)

    st.markdown("#### ¿Qué trae y a cuánto lo compra?")
    wi, pi = _where(fi)
    t = q(f"""WITH b AS (SELECT tipo, unidad_cmp, sum(cif) cif, sum(fob_u) fob, sum(unidades) u FROM mercado WHERE {wi} GROUP BY 1, 2),
                   d AS (SELECT tipo, arg_max(unidad_cmp, u) unidad FROM b WHERE unidad_cmp IS NOT NULL GROUP BY 1)
              SELECT b.tipo, d.unidad, sum(b.cif) cif, sum(b.fob) FILTER (WHERE b.unidad_cmp = d.unidad) fob,
                     sum(b.u) FILTER (WHERE b.unidad_cmp = d.unidad) u
              FROM b LEFT JOIN d USING (tipo) GROUP BY 1, 2 ORDER BY cif DESC LIMIT 30""", pi)
    wu_, pu_ = _where(fu)
    tu = q(f"""SELECT tipo, unidad_cmp unidad, sum(fob_u) fob_ux, sum(unidades) u_ux FROM mercado WHERE {wu_} AND unidades > 0
               GROUP BY 1, 2""", pu_)
    t = t.merge(tu, on=["tipo", "unidad"], how="left")
    t["pu"], t["pu_ux"] = t.fob / t.u, t.fob_ux / t.u_ux
    st.dataframe(pd.DataFrame({
        "Tipo": t.tipo, "CIF (US$ M)": (t.cif / 1e6).round(3), "Unidades": t.u.round(0),
        "Unidad": t.unidad.map(lambda u: UNIDAD_TXT.get(u, "—")),
        "Su FOB/u (US$)": t.pu.round(2), "Nuestro FOB/u (US$)": t.pu_ux.round(2),
        "Nuestras unidades": t.u_ux.round(0),
        "Nosotros vs ellos": ((t.pu_ux / t.pu - 1) * 100).round(1),
    }), hide_index=True, width="stretch",
        column_config={"Nosotros vs ellos": st.column_config.NumberColumn(
            format="%.1f%%", help="Positivo = pagamos más que ellos por unidad (mismo tipo, misma unidad).")})

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### ¿A quién le compra?")
        pr = q(f"""SELECT proveedor, any_value(proveedor_tipo) tipo, arg_max(pais_origen, cif) pais, sum(cif) cif,
                          sum(cif) / sum(sum(cif)) OVER () peso
                   FROM proveedores WHERE {wi} GROUP BY 1 ORDER BY cif DESC LIMIT 12""", pi)
        st.dataframe(pr.assign(**{"% CIF": (100 * pr.peso).round(1)}).rename(
            columns={"proveedor": "Proveedor declarado", "tipo": "Fábrica / trading", "pais": "País"})
            [["Proveedor declarado", "Fábrica / trading", "País", "% CIF"]], hide_index=True, width="stretch")
        pux = q(f"""SELECT proveedor, sum(cif) cif, sum(cif) / sum(sum(cif)) OVER () peso FROM proveedores
                    WHERE {wu_} GROUP BY 1 ORDER BY 2 DESC LIMIT 3""", pu_)
        if len(pux):
            st.caption("UnionX compra a: " + " · ".join(f"{r.proveedor} ({pct(r.peso, 0)})" for r in pux.itertuples()))
    with c2:
        st.markdown("#### ¿Cómo y desde dónde lo trae?")
        filas = []
        for campo, titulo in (("via", "Vía"), ("modalidad", "Modalidad"), ("naviera", "Naviera / transportista"),
                              ("forwarder", "Forwarder"), ("puerto_embarque", "Puerto de embarque")):
            gi, gu = _log_por(fi, campo), _log_por(fu, campo)

            def fmt(g):
                return " · ".join(f"{str(k_)[:24]} {pct(v / g.sum(), 0)}" for k_, v in g.head(3).items()) if len(g) else "—"
            filas.append({"": titulo, "Ellos": fmt(gi), "UnionX": fmt(gu)})
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")

    st.markdown("#### ¿Cuándo compra? (barras = ellos · línea = UnionX)")
    si = q(f"SELECT mes, sum(cif) cif FROM mercado WHERE {wi} GROUP BY 1", pi)
    su = q(f"SELECT mes, sum(cif) cif FROM mercado WHERE {wu_} GROUP BY 1", pu_)
    meses = sorted(set(si.mes) | set(su.mes))
    mi_, mu_ = dict(zip(si.mes, si.cif)), dict(zip(su.mes, su.cif))
    if meses:
        _barras_linea([mes_txt(m) for m in meses], f"{meta.importador[:28]} (US$ M)", [round(mi_.get(m, 0) / 1e6, 3) for m in meses],
                      "UnionX (US$ M)", [round(mu_.get(m, 0) / 1e6, 3) for m in meses], height=300)


def _precios_por_importador(f: dict, min_unidades: int) -> pd.DataFrame:
    """FOB por unidad (unidad dominante del tipo) de cada importador identificado, con los filtros de período/mirada."""
    wm, pm = _where(dict(f, importadores=[], tipos=[]), alias="m")
    return q(f"""WITH d AS (SELECT tipo, arg_max(unidad_cmp, u) unidad FROM (
                              SELECT m.tipo, m.unidad_cmp, sum(m.unidades) u FROM mercado m WHERE {wm} AND m.unidades > 0 GROUP BY 1, 2)
                           GROUP BY 1)
                SELECT m.tipo, m.importador_key, sum(m.fob_u) / sum(m.unidades) pu, sum(m.unidades) cant
                FROM mercado m JOIN d ON d.tipo = m.tipo AND d.unidad = m.unidad_cmp
                WHERE {wm} AND m.unidades > 0 AND m.importador_key <> 'NI'
                GROUP BY 1, 2 HAVING sum(m.unidades) >= {min_unidades}""", pm + pm)


def _tab_nosotros(f):
    tipos_f = f["tipos"]
    w = "WHERE tipo IN (" + ",".join("?" * len(tipos_f)) + ")" if tipos_f else "WHERE tipo IS NOT NULL"
    nos = q(f"""SELECT tipo, sum(qty) qty, sum(fob_usd * qty) / sum(qty) fob, sum(internado_usd * qty) / sum(qty) internado,
                       sum(precio_usd * qty) / sum(qty) precio, count(DISTINCT embarque) embarques
                FROM nosotros {w} AND eta BETWEEN ? AND ? GROUP BY 1 ORDER BY sum(internado_usd * qty) DESC""",
            tuple(tipos_f) + (f"{f['desde']}-01", f"{f['hasta']}-28"))
    if nos.empty:
        st.info("Sin costeos nuestros para los filtros."); return
    nos["sobrecosto"] = nos.internado / nos.precio - 1
    imp = _precios_por_importador(f, 50)
    filas = []
    for tipo, g in imp.groupby("tipo"):
        ux, otros = g[g.importador_key == UX], _plausibles(g[g.importador_key != UX])
        if ux.empty or len(otros) < 3:
            continue
        pu = ux.pu.iloc[0]
        filas.append({"tipo": tipo, "fob_ux_din": pu, "mediana_otros": otros.pu.median(),
                      "percentil": (otros.pu < pu).mean(), "n_imp": len(otros)})
    mk = pd.DataFrame(filas, columns=["tipo", "fob_ux_din", "mediana_otros", "percentil", "n_imp"])
    t = nos.merge(mk, on="tipo", how="left")
    caros = t.dropna(subset=["percentil"]).sort_values("percentil", ascending=False)
    if len(caros):
        c0 = caros.iloc[0]
        st.markdown(f"**Donde quedamos más caros: {c0.tipo} — pagamos más que el {pct(c0.percentil, 0)} de los "
                    f"{int(c0.n_imp)} importadores identificados (FOB {usd(c0.fob_ux_din)} vs mediana {usd(c0.mediana_otros)})**")
    st.dataframe(pd.DataFrame({
        "Tipo": t.tipo, "Unidades costeadas": t.qty.round(0), "Embarques": t.embarques,
        "FOB DIN nuestro (US$/u)": t.fob_ux_din.round(2), "Mediana importadores (US$/u)": t.mediana_otros.round(2),
        "Percentil de precio": (100 * t.percentil).round(0), "Importadores comparados": t.n_imp,
        "FOB precosteo (US$/u)": t.fob.round(2), "Internado (US$/u)": t.internado.round(2),
        "Sobrecosto internación": (100 * t.sobrecosto).round(1),
    }), hide_index=True, width="stretch", height=520,
        column_config={"Percentil de precio": st.column_config.ProgressColumn(
                           format="%d", min_value=0, max_value=100,
                           help="% de importadores identificados que compran MÁS BARATO que nosotros (100 = somos los más caros)."),
                       "Sobrecosto internación": st.column_config.NumberColumn(format="%.1f%%")})
    st.caption("MEDIDO en nuestros costeos (Maestra ene-2024→feb-2026 + precosteos mar-2026→) y en las DIN. Precio de cada "
               "importador = FOB ponderado por unidad comparable, con ≥50 unidades; se compara contra la MEDIANA (no el "
               "promedio, que lo arrastra el volumen barato). Un tipo mezcla calidades: para decidir, bajar a la Ficha.")


def _tab_calidad():
    cal = calidad()
    if not cal:
        st.info("Sin metadatos de calidad."); return
    ide, uni = cal.get("identidad", {}), cal.get("universo", {})
    c = st.columns(4)
    c[0].metric("Meses cargados", len(cal.get("cuadratura", [])))
    c[1].metric("Nuestras líneas clasificadas", f"{ECH.es(uni.get('pct_cif_nuestro_clasificado'), 1)}% del CIF")
    c[2].metric("Claves trazadoras", ECH.es(ide.get("claves_estrictas")))
    c[3].metric("Empresas trazadas sin nombre", ECH.es(ide.get("empresas_trazadas")))
    st.markdown("**Cuadratura mensual contra la base agregada oficial de Aduana** (mismos tipos de operación)")
    cu = pd.DataFrame(cal.get("cuadratura", []))
    if len(cu):
        st.dataframe(cu.rename(columns={"mes": "Mes", "filas": "Líneas DIN", "cif_din_musd": "CIF DIN (US$ M)",
                                        "cif_oficial_musd": "CIF oficial (US$ M)", "dif_pct": "Diferencia %"}),
                     hide_index=True, width="stretch", height=300)
    st.markdown("**Cobertura de identificación (CIF)**")
    st.dataframe(pd.DataFrame(ide.get("cobertura", [])), hide_index=True, width="stretch")
    st.markdown("**Nuestras líneas sin tipo de producto (para afinar la taxonomía)**")
    st.dataframe(pd.DataFrame(uni.get("nuestras_sin_clasificar_top", [])), hide_index=True, width="stretch")
    with st.expander("Disponibilidad de campos en la fuente (Fase 2)"):
        st.dataframe(pd.DataFrame(cal.get("campos", [])), hide_index=True, width="stretch")
    with st.expander("Fuentes y reglas de lectura"):
        for k_, v in cal.get("fuentes", {}).items():
            st.markdown(f"- **{k_}**: {v}")
        st.markdown("- **MEDIDO** sale de la DIN · **DERIVADO** se calcula · **INFERIDO** = nombre del importador.\n"
                    "- El dataset DIN no trae courier (DHL/muestras), pago simultáneo ni vía postal (~1,5% del CIF importado).\n"
                    "- La comuna la declara el agente en cada DIN y cambia: es pista, no llave.\n"
                    "- Montos por empresa = piso (lo no identificado no se les atribuye).")


# ============================================================
# Descargable: Excel de decisión (views/_radar_excel.py) + sábana
# ============================================================
def _excel(f: dict, min_unid: int = 500, banda: float = 2.0, max_filas: int = 200_000) -> bytes:
    w, p = _where(f)
    sab = q_sin_cache(f"""SELECT mes AS "Mes", fecha_acep AS "Fecha aceptación", importador AS "Importador", nivel AS "Evidencia",
                       universo AS "Mirada", categoria AS "Categoría", tipo AS "Tipo de producto", arancel AS "Partida",
                       nombre AS "Nombre mercancía", marca AS "Marca", modelo AS "Modelo", codigo_prod AS "Código producto",
                       proveedor AS "Proveedor", proveedor_declarado AS "Proveedor (como se declaró)",
                       proveedor_tipo AS "Fábrica/trading", pais_origen AS "País origen",
                       puerto_embarque AS "Puerto embarque", via AS "Vía", forwarder AS "Forwarder", naviera AS "Naviera",
                       modalidad AS "Modalidad", unidad_cmp AS "Unidad", unidades AS "Unidades", kg_netos AS "Kg netos",
                       fob_item AS "FOB US$", cif_item AS "CIF US$", fob_por_unidad AS "FOB US$ por unidad",
                       dias_emb_din AS "Días embarque→DIN", id_operacion AS "Id DIN (anonimizado)"
                FROM lineas WHERE {w} ORDER BY cif_item DESC LIMIT {max_filas}""", p)
    # logística por importador, agregada en SQL (valor principal de cada atributo = el de más CIF de productos)
    cte, pl = _dt(f)
    modos = ",\n".join(f"m_{c} AS (SELECT importador_key, arg_max(v, s) {c} FROM (SELECT importador_key, {c} v, sum(peso) s "
                       f"FROM x WHERE {c} IS NOT NULL GROUP BY 1, 2) GROUP BY 1)"
                       for c in ("forwarder", "naviera", "puerto_embarque", "modalidad"))
    logi = q_sin_cache(f"""
        WITH {cte},
             g AS (SELECT importador_key, count(*) din, sum(peso) cif_prod, sum(fob_din * peso / nullif(cif_din, 0)) fob,
                          sum((flete_din + seguro_din) * peso / nullif(cif_din, 0)) fle,
                          median(dias_emb_din) FILTER (WHERE via LIKE '%MAR%') dias FROM x GROUP BY 1),
             {modos}
        SELECT coalesce(i.importador, 'No identificados') "Importador", g.din "DIN", g.fle / nullif(g.fob, 0) "Flete+seguro / FOB",
               g.dias "Días embarque→DIN (mediana)", m_forwarder.forwarder "Forwarder principal",
               m_naviera.naviera "Naviera principal", m_puerto_embarque.puerto_embarque "Puerto principal",
               m_modalidad.modalidad "Modalidad principal", g.cif_prod "CIF productos (US$)"
        FROM g LEFT JOIN importadores i USING (importador_key) LEFT JOIN m_forwarder USING (importador_key)
        LEFT JOIN m_naviera USING (importador_key) LEFT JOIN m_puerto_embarque USING (importador_key)
        LEFT JOIN m_modalidad USING (importador_key)""", pl)
    filtros = [("Período", f"{mes_txt(f['desde'])} → {mes_txt(f['hasta'])}"), ("Mirada", f["mirada"]),
               ("Partidas vecinas", "incluidas" if f["vecinas"] else "excluidas"),
               ("Categorías", ", ".join(f["categorias"]) or "todas"), ("Tipos", ", ".join(f["tipos"]) or "todos"),
               ("Mis SKU", ", ".join(f.get("skus") or []) or "todos los del tipo/categoría"),
               ("Importadores", ", ".join(nombre_imp(k) for k in f["importadores"]) or "todos (en Competidores se ve el mercado completo)"),
               ("Mínimo de unidades para comparar", f"{min_unid:,}"), ("Banda de precio (Mi SKU)", f"1/{banda:g} a {banda:g}× nuestro FOB"),
               ("Filas en la Sábana", f"{len(sab):,}" + (" (tope: las de mayor CIF)" if len(sab) >= max_filas else "")),
               ("Fuente", "DIN públicas de Aduana (datos.gob.cl) · costos UnionX: Maestra de Importaciones + precosteos")]
    return XL.construir(q_sin_cache, _where, f, UX, min_unid, sabana=sab, logistica=logi, filtros_txt=filtros, banda=banda)


def _descarga(f: dict):
    with st.expander("⬇️ Excel de decisión con los filtros actuales (competitividad · oportunidades · logística)"):
        st.caption("Hojas: Léeme · Supuestos (editables) · 1 Mi SKU vs mercado (quién compra mejor mi producto y cuánto ahorraría) · "
                   "2 Oportunidades (todo lo que se importa en la categoría, lo traigamos o no, con margen por fórmula) · "
                   "Competidores (tipo × importador: precio, volumen, logística, a quién compra) · 3 Logística · Proveedores · Sábana.")
        c1, c2 = st.columns(2)
        min_u = c1.number_input("Mínimo de unidades para comparar un importador", min_value=50, max_value=100_000,
                                value=500, step=50)
        banda = c2.select_slider("Banda de precio para 'Mi SKU'", options=[1.5, 2.0, 3.0, 5.0], value=2.0,
                                 format_func=lambda b: f"1/{b:g} a {b:g}× nuestro FOB",
                                 help="Compara cada SKU solo con quienes compran su tipo en ese rango de precio (misma gama).")
        if st.button("Preparar Excel", type="primary"):
            with st.spinner("Armando el Excel…"):
                # en la nube la Sábana va más corta: 60 mil líneas eran +210 MB de RAM en una app de ~1 GB compartida
                # con App Ventas (20 mil = +28 MB). El resto de las hojas va completo.
                st.session_state["radar_xlsx"] = _excel(f, int(min_u), float(banda), max_filas=20_000 if EN_NUBE else 200_000)
                import gc
                gc.collect()
        if st.session_state.get("radar_xlsx"):
            st.download_button("Descargar Excel", data=st.session_state["radar_xlsx"],
                               file_name=f"radar_decision_{f['desde']}_{f['hasta']}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ============================================================
def render():
    st.title("🛰️ Radar de Importaciones")
    if not _autorizado():
        st.info("El Radar de Importaciones está en borrador y por ahora solo lo ve un grupo reducido. Pídele acceso a Andrés.")
        return
    if not _asegurar_hub():
        return
    if not (HUB / "mercado.parquet").exists():
        st.warning("Aún no hay datos del radar (falta correr radar-aduana/pipeline/p9_cubos.py).")
        return
    if EN_NUBE:
        st.caption("🧪 Primer borrador: compártelo solo dentro del equipo (trae nuestros costos y márgenes).")
    cal = calidad()
    meses = [c["mes"] for c in cal.get("cuadratura", [])]
    st.caption(f"DIN públicas de Aduana · {mes_txt(meses[0]) if meses else ''} → {mes_txt(meses[-1]) if meses else ''} · "
               "lo que traemos vs todo el mercado de esos productos · UnionX siempre como comparativo")
    f = _filtros()
    _kpis(f)
    _descarga(f)
    tabs = st.tabs(["Resumen", "Mercado", "Precios", "Ficha importador", "Proveedores", "Logística", "Importadores",
                    "Tamaño de empresas", "Nosotros", "Calidad"])
    with tabs[0]:
        _tab_resumen(f)
    with tabs[1]:
        _tab_mercado(f)
    with tabs[2]:
        _tab_precios(f)
    with tabs[3]:
        _tab_ficha(f)
    with tabs[4]:
        _tab_proveedores(f)
    with tabs[5]:
        _tab_logistica(f)
    with tabs[6]:
        _tab_importadores(f)
    with tabs[7]:
        _tab_tamano(f)
    with tabs[8]:
        _tab_nosotros(f)
    with tabs[9]:
        _tab_calidad()
