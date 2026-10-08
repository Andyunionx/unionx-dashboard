# -*- coding: utf-8 -*-
"""Actualiza la planilla de seguimiento del Cyber en Google Drive.

Corre 3 veces al día (08:00, 14:00, 18:00) en GitHub Actions: cyber_planilla.yml se dispara
al terminar cada pulso Cyber (que lanza cyber_reloj.py cada hora) y solo sigue en esas 3 horas.
También corre local (python actualizar_planilla_cyber.py) con drive_oauth_token.json.

Escribe SOLO las celdas de datos reales (venta por canal y unidades WMS).
Nunca toca supuestos, drivers de dotación ni fórmulas: lo que Andrés edite
se conserva.

Uso:  python actualizar.py            → actualiza con los datos de hoy
      python actualizar.py --dry-run  → calcula y muestra, sin escribir
"""
import io, sys, os, json, subprocess, datetime as dt, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

BASE = Path(__file__).resolve().parent          # raíz del repo (local en Drive o checkout de Actions)
SCRATCH = Path(os.environ.get("TEMP", str(Path.home()))) / "cyber_tracker"
SCRATCH.mkdir(exist_ok=True)
SHEET_ID = "1nG_-yoZjnF8RRyLS1EvwEH8fQmK31DjVVVewZkw79_s"
DRIVE_TOK = BASE / "drive_oauth_token.json"

# dias del Cyber -> columna en las hojas
DIAS = ["2026-10-05","2026-10-06","2026-10-07","2026-10-08",
        "2026-10-09","2026-10-10","2026-10-11"]
COL_REAL_P1 = ["C","F","I","L","O","R","U"]      # columna "Real" por dia
COL_P2      = ["B","C","D","E","F","G","H"]
CANALES_P1 = ["Mercado Libre","Falabella","Kitchen Center","Simplit web","Paris",
              "Ripley","Celmedia","Lhotse web","Walmart","CMR","Travel Duty",
              "UnionX web","LATAM Pass","Global Reward","Abc","Sawa",
              "Banco Bice","Hites"]

# Solo se comparan los canales que tenían plan en el Cyber. Lo demás (hoy, UnionX B2B)
# se excluye de la venta Y de los movimientos de bodega, para no mezclarlo con el plan.
import unicodedata as _ud
def _norm(x):
    return _ud.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().lower().strip()
PLANIFICADOS = {_norm(c) for c in [
    "Mercado Libre", "Falabella", "Kitchen Center", "Simplit web", "Paris", "Ripley",
    "Celmedia", "Lhotse web", "Walmart", "CMR", "Travel Duty", "El volcan", "UnionX web",
    "LATAM Pass", "Global Reward", "Abc", "Sawa", "Banco Bice", "Hites"]}


def pedidos_fuera_plan(d):
    return frozenset(d.loc[~d["canal"].map(_norm).isin(PLANIFICADOS), "pedido"].astype(str))


def solo_planificados(d):
    return d[d["canal"].map(_norm).isin(PLANIFICADOS)].copy()
CATS_P2 = ["entrega_ca1","pick_ca1","reposicion_fulfillment","fulfillment_marketplace",
           "reslotting","recepcion","otra_bodega"]
HOJA_DIA = {"2026-10-05":"C · Lun 5","2026-10-06":"C · Mar 6",
            "2026-10-07":"C · Mié 7","2026-10-08":"C · Jue 8",
            "2026-10-09":"C · Vie 9","2026-10-10":"C · Sáb 10"}
FF_BODEGAS = ["Bodega Fulfillment Falabella","Bodega Fulfillment Mercado Libre",
              "Bodega Fulfillment Paris","Bodega Fulfillment Walmart",
              "Bodega Fulfillment Ripley"]
_BF_LOCS = ("BFML","BFFa","BFP","BFR","BFW","BFE")


def log(*a):
    print(f"[{dt.datetime.now():%H:%M:%S}]", *a, flush=True)


# ---------------------------------------------------------------- 1) VENTA
def extraer_ventas():
    """Corre el pipeline de produccion y devuelve el RAW de octubre."""
    out = SCRATCH / "_raw"
    out.mkdir(exist_ok=True)
    destino = out / "ventas_cyber.parquet"          # --out es la RUTA DEL ARCHIVO
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, str(BASE / "extract_mes_actual_a_parquet.py"),
           "--mes", "2026-10", "--out", str(destino), "--skip-gate"]
    log("extrayendo ventas desde Odoo…")
    r = subprocess.run(cmd, cwd=str(BASE), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    if r.returncode != 0 or not destino.exists():
        log(f"ERROR en el extract · código {r.returncode} · parquet generado: {destino.exists()}")
        print("--- stdout (final) ---"); print((r.stdout or "(vacío)")[-3000:])
        print("--- stderr (final) ---"); print((r.stderr or "(vacío)")[-3000:])
        raise SystemExit(1)
    import pandas as pd
    d = pd.read_parquet(destino)
    d["fecha_venta"] = pd.to_datetime(d["fecha_venta"])
    log(f"RAW: {len(d):,} filas")
    return d


def pct_dia_transcurrido(d, dia, servicios=frozenset()):
    """Qué fracción de su venta llevaban, a la misma hora, los días del Cyber ya cerrados
    (promedio desde el lunes 5). Sirve para proyectar el cierre del día en curso.
    Devuelve (fracción en $, hora, fracción en unidades que cargan bodega)."""
    import pandas as pd
    d = d.copy()
    d["h"] = pd.to_numeric(d["hora_venta_num"], errors="coerce")
    f = d["fecha_venta"].dt.strftime("%Y-%m-%d")
    hoy = d[f == dia]
    cerrados = [x for x in DIAS if x < dia]
    if hoy.empty or not cerrados:
        return None
    hora = hoy["h"].max()
    uds = d[(d["tipo_movimiento"] == "Venta") & (~d["bodega"].isin(FF_BODEGAS))
            & (~d["sku"].astype(str).isin(servicios))]
    fu = uds["fecha_venta"].dt.strftime("%Y-%m-%d")
    p_pesos, p_uds = [], []
    for x in cerrados:
        dx = d[f == x]
        if dx["venta_bruta"].sum():
            p_pesos.append(dx[dx["h"] <= hora]["venta_bruta"].sum() / dx["venta_bruta"].sum())
        ux = uds[fu == x]
        if ux["cantidad"].sum():
            p_uds.append(ux[ux["h"] <= hora]["cantidad"].sum() / ux["cantidad"].sum())
    if not p_pesos:
        return None
    return (float(sum(p_pesos) / len(p_pesos)), int(hora),
            float(sum(p_uds) / len(p_uds)) if p_uds else None)


def agregar_ventas(d, servicios=frozenset()):
    """Devuelve (por_canal, por_dia) para las hojas P1 y C·<dia>.
    Las UNIDADES excluyen los productos tipo servicio (el cobro de envío Delivery_007 venía
    contado como unidad e inflaba 15-18% la carga de bodega); los $ y márgenes los incluyen."""
    import pandas as pd
    v = d[(d["tipo_movimiento"] == "Venta") & (~d["sku"].astype(str).isin(servicios))].copy()
    v["modalidad"] = v["bodega"].apply(
        lambda b: "Fulfillment" if b in FF_BODEGAS else "Carga bodega")
    cb = v[v["modalidad"] == "Carga bodega"]
    por_canal = (cb.groupby([cb["fecha_venta"].dt.strftime("%Y-%m-%d"), "canal"])
                   ["cantidad"].sum().unstack(fill_value=0))
    # venta y margen, total y carga bodega, por dia  (con NC netenadas: usa d, no v)
    def agg(df):
        return df.groupby(df["fecha_venta"].dt.strftime("%Y-%m-%d")).agg(
            bruta=("venta_bruta","sum"), neta=("venta_neta","sum"),
            mgf=("margen_front","sum"), mgl=("margen_final","sum"))
    dd = d.copy()
    dd["modalidad"] = dd["bodega"].apply(
        lambda b: "Fulfillment" if b in FF_BODEGAS else "Carga bodega")
    por_dia = {"total": agg(dd),
               "bodega": agg(dd[dd["modalidad"] == "Carga bodega"])}
    # mix acumulado del Cyber (lunes 5 a hoy): unidades que cargan bodega vs fulfillment
    acu = v[v["fecha_venta"] >= "2026-10-05"]
    mix = acu.groupby(["canal", "modalidad"])["cantidad"].sum().unstack(fill_value=0)
    return por_canal, por_dia, mix


# ---------------------------------------------------------------- 2) WMS
def clasificar_wms(ptn, code, lo, ld):
    """Copia textual de reporte_diario_operacion.clasificar_wms."""
    ptn, lo, ld = ptn or "", lo or "", ld or ""
    car = "Carrascal" in ptn; res = "Reserva Stock" in ptn; ff = "Fulfillment" in ptn
    dest_bf = any(b in ld for b in _BF_LOCS); orig_bf = any(b in lo for b in _BF_LOCS)
    if code == "outgoing":
        if ff or orig_bf: return "fulfillment_marketplace"
        if car: return "entrega_ca1"
        if res: return "entrega_reserva"
        return "otra_bodega"
    if code == "internal":
        if dest_bf: return "reposicion_fulfillment"
        if res: return "pick_reserva"
        if car:
            if "Output" in ld: return "pick_ca1"
            if "Input" in lo: return "recepcion_putaway"
            if "Stock" in lo and "Stock" in ld: return "reslotting"
            return "interno_ca1_otro"
        return "otra_bodega"
    if code == "incoming": return "recepcion"
    return "otra_bodega"


def _odoo():
    sys.path.insert(0, str(BASE / "finanzas-unionx" / "backend"))
    from dotenv import load_dotenv
    load_dotenv(str(BASE / ".env"))
    from app.core.odoo_client import OdooClient
    cli = OdooClient(os.getenv("ODOO_URL","https://unionxb2b.odoo.com"),
                     os.getenv("ODOO_DB","bmya-innovatek-sh-prd-6981800"),
                     os.getenv("OPS_ODOO_USER") or os.getenv("ANDRES_ODOO_USER","andres@grupoeter.cl"),
                     os.getenv("OPS_ODOO_PASSWORD") or os.getenv("ANDRES_ODOO_PASSWORD",""),
                     max_retries=6)
    cli.authenticate()
    return cli


def skus_servicio(cli, d):
    """SKUs del RAW que en Odoo son de tipo servicio (no se preparan en bodega)."""
    skus = sorted(set(d["sku"].dropna().astype(str)))
    out = set()
    for i in range(0, len(skus), 300):
        for p in cli.search_read("product.product",
                                 [("default_code", "in", skus[i:i + 300]), ("type", "=", "service"),
                                  ("active", "in", [True, False])], ["default_code"], 0):
            out.add(p["default_code"])
    return frozenset(out)


def extraer_wms(excluir=frozenset(), cli=None):
    cli = cli or _odoo()
    log("extrayendo WMS…")
    # ventana Chile (UTC-3) de todo el Cyber
    mv = cli.search_read("stock.move",
        [("state","=","done"),("date",">=","2026-10-05 03:00:00"),
         ("date","<","2026-10-12 03:00:00")],
        ["date","quantity","picking_type_id","location_id","location_dest_id","origin"], 0)
    log(f"{len(mv):,} movimientos")
    import collections, pandas as pd
    # resolver nombres de picking type y ubicaciones
    pt_ids = {m["picking_type_id"][0] for m in mv if m.get("picking_type_id")}
    pts = {p["id"]: (p["name"], p["code"]) for p in
           cli.search_read("stock.picking.type", [("id","in",list(pt_ids))],
                           ["name","code","warehouse_id"], 0)}
    # el nombre completo del tipo incluye la bodega
    whs = {p["id"]: (p.get("warehouse_id") or [0,""])[1] for p in
           cli.search_read("stock.picking.type", [("id","in",list(pt_ids))],
                           ["warehouse_id"], 0)}
    res = collections.defaultdict(lambda: collections.defaultdict(float))
    fuera = 0
    for m in mv:
        pt = m.get("picking_type_id")
        if not pt:
            continue
        if str(m.get("origin") or "") in excluir:
            fuera += m.get("quantity") or 0
            continue
        nombre, code = pts.get(pt[0], ("", ""))
        ptn = f"{whs.get(pt[0],'')}: {nombre}"
        lo = (m.get("location_id") or [0,""])[1]
        ld = (m.get("location_dest_id") or [0,""])[1]
        cat = clasificar_wms(ptn, code, lo, ld)
        # fecha en hora Chile
        fecha = (dt.datetime.strptime(m["date"], "%Y-%m-%d %H:%M:%S")
                 - dt.timedelta(hours=3)).strftime("%Y-%m-%d")
        res[fecha][cat] += m.get("quantity") or 0
    if fuera:
        log(f"   WMS: {fuera:,.0f} uds de pedidos fuera del plan excluidas")
    return res


# ---------------------------------------------------------------- 2b) ARRASTRE
HOJA_ARR = "Proyección + arrastre"
COL_ARR = {"2026-10-05": "B", "2026-10-06": "C", "2026-10-07": "D",
           "2026-10-08": "E", "2026-10-09": "F", "2026-10-10": "G"}


def medir_arrastre(cli, excluir=frozenset()):
    """Backlog de preparación (Pick de CA1 abierto) por día, solo canales planificados.
    Se reconstruye desde Odoo: un Pick está pendiente en el instante T si se creó antes
    de T y no estaba hecho en T. Devuelve {dia: {...}} para los días ya iniciados."""
    import pandas as pd
    from collections import defaultdict
    log("midiendo backlog de preparación…")
    pk = cli.search_read("stock.picking",
        [("picking_type_id", "=", 3), ("scheduled_date", ">=", "2026-10-01 03:00:00"),
         ("state", "!=", "cancel"),
         "|", ("state", "in", ["assigned", "confirmed", "waiting"]),
         ("date_done", ">=", "2026-10-05 03:00:00")],
        ["origin", "create_date", "date_done", "x_fecha_corte"], 0)
    pk = [p for p in pk if str(p.get("origin") or "") not in excluir]
    uds = defaultdict(float)
    ids = [p["id"] for p in pk]
    for i in range(0, len(ids), 400):
        for m in cli.search_read("stock.move", [("picking_id", "in", ids[i:i + 400]),
                                                ("state", "!=", "cancel")],
                                 ["picking_id", "product_uom_qty"], 0):
            uds[m["picking_id"][0]] += m["product_uom_qty"] or 0
    P = pd.DataFrame([{"c": pd.Timestamp(p["create_date"]),
                       "dn": pd.Timestamp(p["date_done"]) if p["date_done"] else pd.NaT,
                       "corte": pd.Timestamp(p["x_fecha_corte"]) if p.get("x_fecha_corte") else pd.NaT,
                       "uds": uds[p["id"]]} for p in pk])          # tiempos en UTC
    if P.empty:
        return {}
    ahora = pd.Timestamp.utcnow().tz_localize(None)

    def pendiente(t):
        return float(P.loc[(P.c < t) & (P.dn.isna() | (P.dn >= t)), "uds"].sum())

    def preparado(t0, t1):
        return float(P.loc[(P.dn >= t0) & (P.dn < t1), "uds"].sum())

    hoy = dt.date.today().isoformat()
    t_hoy = pd.Timestamp(hoy) + pd.Timedelta(hours=3)
    transcurrido = ahora - t_hoy
    out = {}
    for dia in COL_ARR:
        if dia > hoy:
            continue
        t0 = pd.Timestamp(dia) + pd.Timedelta(hours=3)            # 00:00 Chile
        t1 = min(t0 + pd.Timedelta(days=1), ahora)
        r = {"inicio": pendiente(t0), "preparado": preparado(t0, t1), "fin": pendiente(t1)}
        if dia == hoy:
            abiertos = P[P.dn.isna()]
            r["vencido"] = float(abiertos.loc[abiertos.corte < ahora, "uds"].sum())
            # qué fracción de su preparación llevaban los días cerrados a esta misma hora
            fr = []
            for x in [k for k in COL_ARR if k < hoy]:
                a0 = pd.Timestamp(x) + pd.Timedelta(hours=3)
                tot = preparado(a0, a0 + pd.Timedelta(days=1))
                if tot:
                    fr.append(preparado(a0, a0 + transcurrido) / tot)
            r["pct_prep"] = sum(fr) / len(fr) if fr else None
        else:
            r["pct_prep"] = 1.0
        out[dia] = r
    log(f"   backlog ahora: {out.get(hoy, {}).get('fin', 0):,.0f} uds por preparar")
    return out


# ---------------------------------------------------------------- 3) ESCRIBIR
_CACHE_HOJA = {}


def _es_hoja_real(sh, hoja):
    """True si la pestaña del día tiene estructura de venta real (no proyectada)."""
    if hoja in _CACHE_HOJA:
        return _CACHE_HOJA[hoja]
    try:
        r = sh.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range=f"'{hoja}'!A15").execute()
        txt = (r.get("values") or [[""]])[0][0] if r.get("values") else ""
    except Exception:
        txt = ""
    ok = str(txt).strip().lower().startswith("venta bruta")
    _CACHE_HOJA[hoja] = ok
    return ok


def escribir(por_canal, por_dia, wms, pct_hoy=None, mix=None, arr=None, dry=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = os.environ.get("DRIVE_OAUTH_TOKEN_JSON", "").strip()   # en Actions: secret del repo
    cr = (Credentials.from_authorized_user_info(json.loads(tok)) if tok
          else Credentials.from_authorized_user_file(str(DRIVE_TOK)))
    if not cr.valid and cr.refresh_token:
        cr.refresh(Request())
    sh = build("sheets", "v4", credentials=cr)
    updates = []

    hoy = dt.date.today().isoformat()
    for i, dia in enumerate(DIAS):
        if dia > hoy:
            continue
        # --- P1: columna Real del dia ---
        col = COL_REAL_P1[i]
        vals = []
        for canal in CANALES_P1:
            v = 0
            if dia in por_canal.index and canal in por_canal.columns:
                v = float(por_canal.loc[dia, canal])
            vals.append([round(v) if v else None])
        updates.append({"range": f"'P1 · Carga bodega'!{col}5:{col}{4 + len(CANALES_P1)}", "values": vals})

        # --- P2: columna del dia ---
        col2 = COL_P2[i]
        w = wms.get(dia, {})
        updates.append({"range": f"'P2 · WMS'!{col2}5:{col2}11",
                        "values": [[round(w.get(c, 0)) or None] for c in CATS_P2]})

        # --- C · <dia>: venta y margen, total y carga bodega ---
        hoja = HOJA_DIA.get(dia)
        # Blindaje: una pestaña de día PROYECTADO tiene "Forecast bruto del día"
        # en A15 y sus filas 15-19 son fórmulas. Escribir ahí las destruye.
        if hoja and not _es_hoja_real(sh, hoja):
            log(f"   {hoja}: aún es día proyectado, no se escribe")
            hoja = None
        if hoja and dia in por_dia["total"].index:
            t = por_dia["total"].loc[dia]
            b = (por_dia["bodega"].loc[dia]
                 if dia in por_dia["bodega"].index else None)
            filas = []
            for k in ("bruta","neta","mgf","mgl"):
                filas.append([round(t[k]), round(b[k]) if b is not None else None])
            updates.append({"range": f"'{hoja}'!B15:C18", "values": filas})
            # si el día está en curso, actualizar el % transcurrido (celda B20)
            if dia == hoy and pct_hoy:
                updates.append({"range": f"'{hoja}'!B20",
                                "values": [[round(pct_hoy[0], 4)]]})
                log(f"   {hoja}: {pct_hoy[0]:.1%} del día (hora {pct_hoy[1]})")
            elif dia < hoy:
                # día cerrado: si quedara el % parcial de la última corrida, el cierre
                # estimado dividiría la venta completa por ese % y la inflaría
                updates.append({"range": f"'{hoja}'!B20", "values": [[1]]})

    # --- P1 · Modalidad: acumulado del Cyber por canal (columnas C y D) ---
    if mix is not None:
        lab = sh.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range="'P1 · Modalidad'!A5:A60").execute().get("values", [])
        # las filas de canales terminan en TOTAL; así un canal agregado a mano también se llena
        corte = next((i for i, r in enumerate(lab) if r and str(r[0]).strip().upper() == "TOTAL"), len(lab))
        lab = lab[:corte]
        filas = []
        for row in lab:
            canal = row[0] if row else ""
            cb = float(mix.loc[canal, "Carga bodega"]) if canal in mix.index and "Carga bodega" in mix.columns else 0
            ff = float(mix.loc[canal, "Fulfillment"]) if canal in mix.index and "Fulfillment" in mix.columns else 0
            filas.append([round(cb), round(ff)])
        sin_fila = [c for c in mix.index if c not in {r[0] for r in lab if r}]
        if sin_fila:
            log(f"   P1 · Modalidad: canales con venta sin fila en la hoja: {sin_fila}")
        updates.append({"range": f"'P1 · Modalidad'!C5:D{4 + len(filas)}", "values": filas})
        updates.append({"range": "'P1 · Modalidad'!A2", "values": [[
            f"Acumulado del Cyber, del lunes 5 al {dt.date.today():%d-%m}. "
            f"Qué % de cada canal despachó el marketplace desde su propio stock, contra el supuesto del plan."]]})
    # --- Proyección + arrastre: solo los datos medidos (filas 45-51); el resto son fórmulas ---
    titulos = {x["properties"]["title"] for x in sh.spreadsheets().get(
        spreadsheetId=SHEET_ID, fields="sheets(properties(title))").execute()["sheets"]}
    if arr and HOJA_ARR in titulos:
        for dia, r in arr.items():
            c = COL_ARR[dia]
            if dia < hoy:
                pu, pp = 1, 1
            else:
                pu = round(pct_hoy[2], 4) if pct_hoy and pct_hoy[2] else ""
                pp = round(r["pct_prep"], 4) if r.get("pct_prep") is not None else ""
            updates.append({"range": f"'{HOJA_ARR}'!{c}45:{c}50", "values": [
                [pu], [pp], [round(r["inicio"])], [round(r["preparado"])], [round(r["fin"])],
                [round(r["vencido"]) if dia == hoy else ""]]})
        updates.append({"range": f"'{HOJA_ARR}'!B51", "values": [[
            f"Odoo, {dt.datetime.now():%d-%m %H:%M}"]]})
    elif arr:
        log(f"   no existe la pestaña '{HOJA_ARR}': no se escribe el arrastre")
    log(f"{len(updates)} rangos a escribir")
    if dry:
        for u in updates:
            print("   ", u["range"], "→", str(u["values"])[:90])
        return
    r = sh.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": updates}).execute()
    log(f"OK · {r.get('totalUpdatedCells')} celdas actualizadas")
    # sello de hora
    sh.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range="Resumen!A2",
        valueInputOption="USER_ENTERED",
        body={"values": [[f"Actualizado automáticamente el "
                          f"{dt.datetime.now():%d-%m-%Y a las %H:%M}. "
                          f"Pega nada: los datos reales entran solos."]]}).execute()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-ventas", action="store_true",
                    help="solo WMS, sin correr el extract (más rápido)")
    a = ap.parse_args()
    log("=== actualización planilla Cyber ===")
    if a.skip_ventas:
        import pandas as pd
        pqs = sorted((SCRATCH/"_raw").glob("*.parquet"), key=lambda p: p.stat().st_mtime)
        d = pd.read_parquet(pqs[-1]); d["fecha_venta"] = pd.to_datetime(d["fecha_venta"])
    else:
        d = extraer_ventas()
    excluir = pedidos_fuera_plan(d)
    d = solo_planificados(d)
    log(f"   fuera del plan: {len(excluir)} pedidos (se excluyen de venta y de bodega)")
    cli = _odoo()
    try:
        servicios = skus_servicio(cli, d)
    except Exception as e:
        log(f"   no se pudo leer el tipo de producto ({e}); se usa Delivery_007")
        servicios = frozenset({"Delivery_007"})
    log(f"   SKUs de servicio fuera de las unidades: {sorted(servicios)}")
    por_canal, por_dia, mix = agregar_ventas(d, servicios)
    wms = extraer_wms(excluir, cli)
    try:
        arr = medir_arrastre(cli, excluir)
    except Exception as e:                       # que una falla acá no bote el resto
        log(f"   ERROR midiendo arrastre: {e}")
        arr = None
    hoy = dt.date.today().isoformat()
    pct_hoy = pct_dia_transcurrido(d, hoy, servicios)
    escribir(por_canal, por_dia, wms, pct_hoy=pct_hoy, mix=mix, arr=arr, dry=a.dry_run)
    log("listo")


if __name__ == "__main__":
    main()
