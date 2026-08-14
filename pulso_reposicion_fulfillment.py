# -*- coding: utf-8 -*-
"""Pulso Reposición Fulfillment v2 — sugerido semanal de carga a bodegas full.

v2 = especificación de la mesa de trabajo 11-08-2026 (mail Nicole 11-08 17:21):
  1. BASE DE PRODUCTOS: hoja "Maestra" del drive de PRICING (1gVJmFCR19...).
  2. VENTA/UME: RAW filtrado a canales DIGITALES (tipo_negocio Marketplace +
     Páginas propias + Fidelización), promedio L6W ISO sin semanas 23/41.
  3. COBERTURA (restricción de envío): stock CA1/Stock ÷ demanda semanal digital
     ×4,33, donde la demanda del SKU = venta directa + venta de packs que lo
     contienen (hoja "Packs" de Pricing). Regla Nicolás: cuidar ~1 mes de CA1
     (umbral por canal en hoja Reglas del panel de Nicole).
  4. STOCK FULL LIVE: feed seller center (Martín) + Walmart Odoo + **tránsito
     a fulls**: pickings internos PENDIENTES hacia bodegas BF* (los picks de
     Gerardo) se suman al stock del canal destino. [Pendiente: stock Fala desde
     la vista no-descarga (scraper de Claudia) cuando exista el feed.]
  5. Blacklist/LARGE/UME Manual/Reglas/UME MIN: siguen en el panel de Nicole
     (drive original, se actualiza los viernes) — se leen en cada corrida.

Semántica sugerido (v1.2, definiciones Nicole 03-08): objetivo = max(UME×cob
canal/large, UME MIN, UME Manual-directo); repo = múltiplo de 2; anulada por
Blacklist o Restricción (cobertura CA1 < umbral canal).

Uso: python pulso_reposicion_fulfillment.py [--no-download] [--no-live]
Salida: data/outputs/Pulso_Reposicion_Fulfillment_<fecha>.xlsx
"""
import os, sys, math, json, argparse, datetime
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
PANEL_ID = "1eyxR9KsCgDswZWuSi6DuLq6GqoomuvCc"   # panel Nicole (Reglas/BL/Large/Manual/MIN/Dim)
PRICING_ID = "1gVJmFCR19KbYkZfds7fH-62rJ0Zpt32P"  # drive Pricing (Maestra + Packs)
LOCAL_PANEL = ROOT / "data/outputs/NICOLE_fulfillment_sugeridos_UME.xlsx"
LOCAL_PRICING = ROOT / "data/outputs/PRICING_drive.xlsx"
TEMPLATE_DIN = ROOT / "data/templates/pulso_reposicion_template.xlsx"
DETALLE = ROOT / "data/stock/detalle.parquet"
HIST = ROOT / "data/historico/ventas_historico.parquet"
MES = ROOT / "data/historico/ventas_mes_actual.parquet"
OUT_DIR = ROOT / "data/outputs"
CANALES = ["Mercado Libre", "Falabella", "Paris", "Walmart"]
BOD2CANAL = {"BFML": "Mercado Libre", "BFFa": "Falabella", "BFP": "Paris",
             "BFR": "Ripley", "BFW": "Walmart", "BFE": "Falabella"}
DIGITAL = {"Marketplace", "Páginas propias", "Páginas Propias", "Fidelización"}
SEM_EVENTO = {23, 41}
AZUL = "4884FC"


def _drive_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    tok_env = os.environ.get("DRIVE_OAUTH_TOKEN_JSON", "")
    if tok_env:
        info = json.loads(tok_env)
        creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
    else:
        creds = Credentials.from_authorized_user_file(str(ROOT / "drive_oauth_token.json"))
    if not creds.valid:
        creds.refresh(Request())
    return creds


def descargar(fid: str, destino: Path) -> None:
    import requests
    creds = _drive_creds()
    H = {"Authorization": f"Bearer {creds.token}"}
    r = requests.get(f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media", headers=H, timeout=180)
    if not r.ok:
        r = requests.get(f"https://www.googleapis.com/drive/v3/files/{fid}/export"
                         f"?mimeType=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         headers=H, timeout=180)
    r.raise_for_status()
    destino.write_bytes(r.content)
    print(f"[drive] {destino.name} refrescado ({len(r.content):,} bytes)")


def mult2(x: float) -> int:
    return max(0, int(math.floor(x / 2 + 0.5) * 2))


def semanas_l6w(hoy: datetime.date) -> list[int]:
    w = hoy.isocalendar()[1]
    return [s for s in range(w - 9, w) if s not in SEM_EVENTO][-6:]


def cargar_parametros():
    """Panel Nicole: Reglas, UME MIN, UME Manual, Blacklist, Large, Dimensiones."""
    xl = pd.ExcelFile(LOCAL_PANEL)
    reglas = xl.parse("Reglas").iloc[:5]
    reglas.columns = ["Canal", "cob", "cob_large", "restr"]
    reglas = reglas.set_index("Canal")

    umin = xl.parse("Ume MIN", header=0)
    t_tipo = {str(k).strip(): v for k, v in zip(umin.iloc[:, 0], pd.to_numeric(umin.iloc[:, 1], errors="coerce")) if pd.notna(v)}
    t_marca = {str(k).strip(): v for k, v in zip(umin.iloc[:, 3], pd.to_numeric(umin.iloc[:, 4], errors="coerce")) if pd.notna(v)}

    bl = xl.parse("BLACKLIST")
    bl.columns = [c.strip() for c in bl.columns]
    blset = {(str(r["Canal"]).strip(), str(r["SKU"]).strip())
             for _, r in bl.iterrows() if pd.to_numeric(r.get("Blacklist"), errors="coerce") == 1}
    lg = xl.parse("LARGE")
    lg.columns = [c.strip() for c in lg.columns]
    lgset = {(str(r["Canal"]).strip(), str(r["SKU"]).strip())
             for _, r in lg.iterrows() if pd.to_numeric(r.get("Large"), errors="coerce") == 1}

    ume_tab = xl.parse("UME")
    ume_tab["UME Manual"] = pd.to_numeric(ume_tab["UME Manual"], errors="coerce")
    manual_map = {(str(r["Sku"]).strip(), str(r["Canal"]).strip()): float(r["UME Manual"])
                  for _, r in ume_tab.dropna(subset=["UME Manual"]).iterrows()}
    bl_panel = {(str(r["Sku"]).strip(), str(r["Canal"]).strip()): int(r["Blacklist"])
                for _, r in ume_tab.iterrows() if pd.notna(pd.to_numeric(r["Blacklist"], errors="coerce"))}

    dim = xl.parse("Dimensiones")
    dim.columns = [str(c).strip() for c in dim.columns]
    dim["SKU"] = dim["SKU"].astype(str).str.strip()
    dim_m3 = dict(zip(dim["SKU"], pd.to_numeric(dim["Dim m3"], errors="coerce")))
    dim_kg = dict(zip(dim["SKU"], pd.to_numeric(dim["Peso"], errors="coerce")))
    return reglas, t_tipo, t_marca, blset, lgset, manual_map, bl_panel, dim_m3, dim_kg, ume_tab


def cargar_pricing():
    """Drive Pricing: Maestra (base de productos) + Packs (componentes)."""
    xl = pd.ExcelFile(LOCAL_PRICING)
    prod = xl.parse("Maestra")
    prod.columns = [str(c).strip() for c in prod.columns]
    prod = prod.dropna(subset=["Sku"]).drop_duplicates("Sku")
    prod["Sku"] = prod["Sku"].astype(str).str.strip()
    packs = xl.parse("Packs")
    packs.columns = [str(c).strip() for c in packs.columns]
    packs["Pack"] = packs["Pack"].astype(str).str.strip()
    packs["SKU"] = packs["SKU"].astype(str).str.strip()
    # componentes por pack (cantidad = nº de filas repetidas del mismo SKU)
    comp = packs.groupby(["Pack", "SKU"]).size().rename("qty").reset_index()
    print(f"[pricing] Maestra: {len(prod)} SKUs | Packs: {comp['Pack'].nunique()} packs / {len(comp)} componentes")
    return prod, comp


def cargar_venta_digital(sem: list[int]) -> pd.DataFrame:
    """Unidades por SKU x canal x semana ISO, SOLO canales digitales."""
    anio = datetime.date.today().year
    corte = datetime.date.today().replace(day=1).isoformat()
    cols = ["sku", "canal", "fecha_venta", "cantidad", "tipo_negocio"]
    h = pd.read_parquet(HIST, columns=cols)
    h = h[h["fecha_venta"].astype(str) < corte]
    m = pd.read_parquet(MES, columns=cols)
    m = m[m["fecha_venta"].astype(str) >= corte]
    v = pd.concat([h, m], ignore_index=True)
    v = v[v["tipo_negocio"].isin(DIGITAL)]
    v["fecha_venta"] = pd.to_datetime(v["fecha_venta"])
    v = v[v["fecha_venta"].dt.year == anio]
    v["week"] = v["fecha_venta"].dt.isocalendar().week.astype(int)
    v = v[v["week"].isin(sem)]
    v["sku"] = v["sku"].astype(str).str.strip()
    v["cantidad"] = pd.to_numeric(v["cantidad"], errors="coerce").fillna(0)
    return v


def stock_full_live(no_live: bool):
    det = pd.read_parquet(DETALLE)
    bcode = det["Bodega"].astype(str).str.split("/").str[0]
    odoo = det[bcode.isin(BOD2CANAL)].copy()
    odoo["canal"] = bcode[bcode.isin(BOD2CANAL)].map(BOD2CANAL)
    odoo["sku"] = odoo["SKU"].astype(str).str.strip()
    odoo_g = odoo.groupby(["canal", "sku"], as_index=False)["Disponible"].sum().rename(columns={"Disponible": "qty"})
    fuente, cruce = "Odoo (fallback)", None
    if not no_live:
        try:
            import fulfillment_live as fl
            try:
                live = fl.cargar_live()
                fuente = "Seller center (feed Martín, fresco)"
            except Exception as e:
                live = pd.read_parquet(fl.LIVE_PARQUET)
                fuente = f"Seller center (parquet local; feed no disponible: {type(e).__name__})"
            cruce = fl.generar_cruce(live)
            canales_live = set(live["canal"].unique())
            base = pd.concat([live[["canal", "sku", "qty"]],
                              odoo_g[~odoo_g["canal"].isin(canales_live)]], ignore_index=True)
            return base.groupby(["canal", "sku"], as_index=False)["qty"].sum(), fuente, cruce
        except Exception as e:
            print(f"[live][WARN] {type(e).__name__}: {e} -> Odoo BF*")
    return odoo_g, fuente, cruce


def transito_a_fulls():
    """Picks internos PENDIENTES hacia bodegas BF* (reposiciones de Gerardo en
    camino que el seller center aún no refleja) → sumar al stock del canal."""
    import xmlrpc.client, time
    cfg = json.load(open(ROOT / "odoo/odoo_config.json"))["produccion"]
    pw = os.environ.get("ANDRES_ODOO_PASSWORD", "") or (ROOT / "odoo/.odoo_pass").read_text().strip()
    uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(cfg["db_name"], cfg["username"], pw, {})
    def rpc(model, method, args, kw=None):
        for i in range(3):
            try:
                return xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object").execute_kw(
                    cfg["db_name"], uid, pw, model, method, args, kw or {})
            except Exception:
                if i == 2:
                    raise
                time.sleep(5)
    mv = rpc("stock.move", "search_read",
             [[("state", "in", ["confirmed", "assigned", "waiting", "partially_available"]),
               ("location_dest_id.complete_name", "like", "BF")]],
             {"fields": ["product_id", "product_uom_qty", "location_dest_id"]})
    filas = []
    pids = list({m["product_id"][0] for m in mv if m["product_id"]})
    codes = {}
    for i in range(0, len(pids), 300):
        for p in rpc("product.product", "read", [pids[i:i+300]], {"fields": ["default_code"]}):
            codes[p["id"]] = str(p["default_code"] or "").strip()
    for m in mv:
        if not m["product_id"]:
            continue
        bod = str(m["location_dest_id"][1]).split("/")[0]
        canal = BOD2CANAL.get(bod)
        sku = codes.get(m["product_id"][0], "")
        if canal and sku:
            filas.append({"canal": canal, "sku": sku, "qty": m["product_uom_qty"]})
    df = pd.DataFrame(filas)
    tot = df["qty"].sum() if len(df) else 0
    print(f"[transito-fulls] {len(df)} líneas / {tot:,.0f} uds en camino a bodegas BF*")
    return df.groupby(["canal", "sku"])["qty"].sum().to_dict() if len(df) else {}


def construir(no_download=False, no_live=False) -> Path:
    hoy = datetime.date.today()
    sem = semanas_l6w(hoy)
    print(f"[pulso v2] {hoy} — semana ISO {hoy.isocalendar()[1]} — L6W: {sem}")
    if not no_download:
        for fid, dest in [(PANEL_ID, LOCAL_PANEL), (PRICING_ID, LOCAL_PRICING)]:
            try:
                descargar(fid, dest)
            except Exception as e:
                print(f"[drive][WARN] {dest.name}: {e} -> copia local")

    (reglas, t_tipo, t_marca, blset, lgset, manual_map, bl_panel,
     dim_m3, dim_kg, ume_nicole) = cargar_parametros()
    prod, comp = cargar_pricing()
    venta = cargar_venta_digital(sem)
    full, fuente_live, cruce = stock_full_live(no_live)
    full_map = {(r.canal, r.sku): r.qty for r in full.itertuples(index=False)}
    try:
        tr_fulls = transito_a_fulls()
    except Exception as e:
        print(f"[transito-fulls][WARN] {type(e).__name__}: {e}")
        tr_fulls = {}

    det = pd.read_parquet(DETALLE)
    ca1 = det[det["Bodega"].astype(str).str.startswith("CA1")]
    stock_ca1 = ca1.groupby(ca1["SKU"].astype(str).str.strip())["Disponible"].sum()

    # venta semanal por sku x canal (para UME) y demanda digital total con packs
    v_canal = venta.groupby(["sku", "canal"])["cantidad"].sum() / len(sem)
    v_sku = venta.groupby("sku")["cantidad"].sum() / len(sem)
    demanda = v_sku.copy()
    for r in comp.itertuples(index=False):
        vp = v_sku.get(r.Pack, 0)
        if vp:
            demanda[r.SKU] = demanda.get(r.SKU, 0) + vp * r.qty
    print(f"[demanda] SKUs con venta digital: {len(v_sku)} | con aporte de packs: "
          f"{sum(1 for r in comp.itertuples(index=False) if v_sku.get(r.Pack,0))}")

    filas = []
    for p in prod.itertuples(index=False):
        d = dict(zip(prod.columns, p))
        sku = str(d.get("Sku")).strip()
        tipo = str(d.get("Tipo de producto", "") or "").strip()
        marca = str(d.get("Marca", "") or "").strip()
        umin = (t_tipo.get(tipo, 2) or 0) * (t_marca.get(marca, 0) or 0)
        st_ca1 = float(stock_ca1.get(sku, 0))
        dem = float(demanda.get(sku, 0))
        cob_ca1 = st_ca1 / (dem * 4.33) if dem > 0 else np.inf
        # Cobertura OBJETIVO por SKU (Maestra Pricing, col 'Cob', en meses) y estado In/Out.
        # Confirmado Andrés 13-ago: Cob = meses objetivo (reemplaza cob por canal); out = no reponer.
        cob_obj_meses = pd.to_numeric(d.get("Cob"), errors="coerce")
        es_out = str(d.get("In/Out", "")).strip().lower() == "out"
        for canal in CANALES:
            ume = mult2(float(v_canal.get((sku, canal), 0)))
            manual = manual_map.get((sku, canal))
            large = 1 if (canal, sku) in lgset else 0
            black = bl_panel.get((sku, canal), 1 if (canal, sku) in blset else 0)
            # Objetivo por cobertura por CANAL (hoja Reglas). OJO: la col 'Cob' de la
            # Maestra resultó ser cobertura ACTUAL (llega a 158 meses), NO un objetivo,
            # así que NO se usa como target (inflaba el sugerido 17x). Se muestra como
            # informativa. Pendiente confirmar con comercial la fuente real del objetivo.
            cob = reglas.loc[canal, "cob_large"] if large else reglas.loc[canal, "cob"]
            candidatos = {"Venta": ume * cob, "Piso mínimo": umin, "Manual": manual or 0}
            origen = max(candidatos, key=candidatos.get)
            objetivo = candidatos[origen]
            live_q = float(full_map.get((canal, sku), 0)) + float(tr_fulls.get((canal, sku), 0))
            restr = 1 if cob_ca1 < reglas.loc[canal, "restr"] else 0
            repo = 0 if (black or restr or es_out) else mult2(max(0, objetivo - live_q))
            filas.append({
                "Categoría": d.get("Categoría", ""), "Tipo de producto": tipo, "Marca": marca,
                "Pack": d.get("Pack", ""), "In/Out": d.get("In/Out", ""), "Sku": sku,
                "Producto": d.get("Producto", ""), "Canal": canal,
                "UME": ume, "UME MIN": umin, "UME Manual": manual,
                "Blacklist": black, "Restricción": restr, "Large": large,
                "Origen del objetivo": origen if repo > 0 else "",
                "Stock objetivo full": objetivo,
                "Stock Full Live+tránsito": live_q, "Reposición": repo,
                "Dim m3": round((dim_m3.get(sku) or 0) * repo, 4),
                "Dim peso": round((dim_kg.get(sku) or 0) * repo, 2),
                "Stock CA1": st_ca1, "Demanda digital sem (c/packs)": round(dem, 2),
                "Cobertura CA1 (meses)": round(cob_ca1, 2) if np.isfinite(cob_ca1) else "",
                "Cob Maestra (info)": round(cob_obj_meses, 2) if pd.notna(cob_obj_meses) else "",
            })
    df = pd.DataFrame(filas)

    act = df[df["Reposición"] > 0]
    res = act.groupby("Canal").agg(SKUs=("Sku", "nunique"), Unidades=("Reposición", "sum"),
                                   m3=("Dim m3", "sum"), kg=("Dim peso", "sum")).reset_index()
    def costo_envio(m3):
        if m3 <= 0: return 0
        pallets = math.ceil(m3 / 2) * 5500
        return pallets if m3 < 2.8 else (80000 + pallets if m3 <= 7 else 120000 + pallets)
    res["Costo envío est."] = res["m3"].apply(costo_envio)
    res["Tramo"] = res["m3"].apply(lambda x: "<2,8 m3 (solo pallets)" if x < 2.8
                                   else ("2,8-7 m3 ($80k)" if x <= 7 else ">12 m3 ($120k)" if x > 12 else "7-12 m3"))

    fn = OUT_DIR / f"Pulso_Reposicion_Fulfillment_{hoy:%Y%m%d}.xlsx"
    from openpyxl.styles import Font, PatternFill
    with pd.ExcelWriter(fn, engine="openpyxl") as w:
        res.to_excel(w, sheet_name="Resumen canal", index=False)
        df.sort_values(["Canal", "Reposición"], ascending=[True, False]).to_excel(w, sheet_name="UME v2", index=False)
        if cruce is not None:
            cruce["resumen"].to_excel(w, sheet_name="Cuadratura", index=False)
            cruce["detalle"].head(3000).to_excel(w, sheet_name="Cuadratura detalle", index=False)
        stats = pd.DataFrame([
            ["Corrida", f"{hoy} (semana ISO {hoy.isocalendar()[1]}) — MOTOR v2 (mesa 11-08)"],
            ["Semanas venta (L6W)", str(sem)],
            ["Venta", "RAW, SOLO canales digitales: Marketplace + Páginas propias + Fidelización"],
            ["Base de productos", "Drive PRICING, hoja Maestra (refrescada en cada corrida). In/Out='out' NO repone."],
            ["Objetivo de stock full", "Cobertura por CANAL (hoja Reglas) × venta digital semanal. La col 'Cob' de "
             "la Maestra es cobertura ACTUAL (no objetivo) -> se muestra informativa, no se usa como target."],
            ["Cobertura (restricción)", "Stock CA1/Stock ÷ demanda digital semanal ×4,33; demanda = venta SKU + packs "
             "que lo contienen (hoja Packs de Pricing). Umbral por canal = hoja Reglas."],
            ["Stock full", f"{fuente_live} + TRÁNSITO a fulls (picks internos pendientes hacia BF*)"],
            ["Blacklist/Large/Manual/MIN", "Panel de Nicole (drive original, actualización de los viernes)"],
            ["", ""],
            ["PENDIENTE", "Stock Falabella desde vista no-descarga (scraper de Claudia): se integra cuando exista feed."],
        ], columns=["Item", "Detalle"])
        stats.to_excel(w, sheet_name="Metodología", index=False)
        for ws in w.book.worksheets:
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor=AZUL)
            ws.freeze_panes = "A2"
    tot = int(act["Reposición"].sum())
    print(f"[pulso v2] {fn.name} | {len(act)} SKU-canal | {tot:,} uds | "
          f"restricción activa en {int((df['Restricción']==1).sum())} filas")
    return fn


def construir_excel_dinamico(flat_path=None) -> bytes:
    """Reporte con TABLA DINÁMICA NATIVA (hoja 'Dinámica': Canal→Marca→SKU; valores
    Reposición/m³/Stock CA1/Demanda) sobre la sábana 'UME v2'. Inyecta en la plantilla
    (armada 1 vez con Excel COM) + zip-surgery (refreshOnLoad) — el runtime NO usa Excel.
    Copia además Resumen canal / Cuadratura / Metodología como hojas planas."""
    import io as _io, re as _re, zipfile as _zip
    import openpyxl
    from openpyxl.utils import get_column_letter
    if flat_path is None:
        flat_path = construir()
    xls = pd.ExcelFile(flat_path)
    sabana = xls.parse("UME v2")
    ncols = len(sabana.columns)

    def _clean(row):
        return [None if (isinstance(v, float) and pd.isna(v)) else v for v in row]

    wb = openpyxl.load_workbook(TEMPLATE_DIN)
    ws = wb["Datos"]
    ws.delete_rows(1, ws.max_row)
    ws.append(list(sabana.columns))
    for row in sabana.itertuples(index=False):
        ws.append(_clean(row))
    for sn in xls.sheet_names:
        if sn == "UME v2":
            continue
        d = xls.parse(sn)
        w = wb.create_sheet(sn[:31])
        w.append([str(c) for c in d.columns])
        for row in d.itertuples(index=False):
            w.append(_clean(row))
    buf = _io.BytesIO(); wb.save(buf); buf.seek(0)

    ref = f"A1:{get_column_letter(ncols)}{len(sabana) + 1}"
    zin = _zip.ZipFile(buf, "r"); out = _io.BytesIO()
    with _zip.ZipFile(out, "w", _zip.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == "xl/pivotCache/pivotCacheDefinition1.xml":
                x = d.decode("utf-8")
                x = _re.sub(r'(<worksheetSource ref=")[^"]+(")', r"\g<1>" + ref + r"\g<2>", x)
                if "refreshOnLoad" not in x.split(">")[0]:
                    x = _re.sub(r"(<pivotCacheDefinition )", r'\g<1>refreshOnLoad="1" ', x, count=1)
                else:
                    x = _re.sub(r'refreshOnLoad="[^"]*"', 'refreshOnLoad="1"', x)
                d = x.encode("utf-8")
            zout.writestr(it, d)
    zin.close()
    return out.getvalue()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--no-live", action="store_true")
    a = ap.parse_args()
    construir(no_download=a.no_download, no_live=a.no_live)
