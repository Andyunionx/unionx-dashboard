# -*- coding: utf-8 -*-
"""Pulso Reposición Fulfillment v1 — sugerido semanal de carga a bodegas full.

Replica el modelo UME de Nicole (fórmulas validadas 100% contra su archivo
29-jul-2026: UME 5.031/5.031, Reposición 5.031/5.031) alimentado con:
  - Venta: RAW parquet (histórico + mes actual, cutoff fin de mes anterior)
  - Stock full live: feed seller center de Martín (misma base del Pulso Stock;
    ML/Fala/Paris/Ripley) + Walmart desde Odoo (BFW). Fallback: Odoo BF*.
  - Stock bodega principal: data/stock/detalle.parquet (CA1)
  - Tránsitos: data/planificacion/snapshots/planif_forecast_transito.parquet
  - Parámetros del KAM (Reglas, UME MIN, UME Manual, BLACKLIST, LARGE,
    Productos, Dimensiones): el Google Sheet de Nicole (panel de control),
    descargado fresco en cada corrida con drive_oauth_token.json.

Semántica (validada contra el archivo, no contra las definiciones):
  UME        = round_half_up_a_multiplo_2( promedio venta 6 semanas ISO
               completas, excluyendo semanas de evento 23 y 41 )
  UME MIN    = valor_tipo (default 2) x valor_marca (default 0)
  Objetivo   = max( max(UME, UME Manual) x cobertura(canal, large), UME MIN )
  Reposición = max(0, Objetivo - stock_full_live) ; 0 si Blacklist o Restricción
  OJO: el archivo de Nicole NO anula por estado OUT (las definiciones dicen que
  sí) -> v1 replica el archivo y lo reporta como advertencia.
  Restricción plan (v1, proxy): cobertura bodega principal en meses =
  (stock CA1 disponible + tránsito del mes) / (venta semanal total x 4.33);
  si < umbral del canal (Reglas) -> no enviar.

Uso: python pulso_reposicion_fulfillment.py [--no-download] [--no-live]
Salida: data/outputs/Pulso_Reposicion_Fulfillment_<fecha>.xlsx
"""
import os, sys, io, math, argparse, datetime, json
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
SHEET_ID = "1eyxR9KsCgDswZWuSi6DuLq6GqoomuvCc"
LOCAL_SHEET = ROOT / "data/outputs/NICOLE_fulfillment_sugeridos_UME.xlsx"
DETALLE = ROOT / "data/stock/detalle.parquet"
HIST = ROOT / "data/historico/ventas_historico.parquet"
MES = ROOT / "data/historico/ventas_mes_actual.parquet"
TRANSITO = ROOT / "data/planificacion/snapshots/planif_forecast_transito.parquet"
OUT_DIR = ROOT / "data/outputs"
CANALES = ["Mercado Libre", "Falabella", "Paris", "Walmart"]
SEM_EVENTO = {23, 41}
AZUL = "4884FC"


def descargar_sheet() -> None:
    """Refresca la copia local del panel de Nicole (best-effort).
    Credencial: env DRIVE_OAUTH_TOKEN_JSON (CI) o drive_oauth_token.json local."""
    import requests
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    tok_env = os.environ.get("DRIVE_OAUTH_TOKEN_JSON", "")
    if tok_env:
        import json as _json
        info = _json.loads(tok_env)
        creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
    else:
        creds = Credentials.from_authorized_user_file(str(ROOT / "drive_oauth_token.json"))
    if not creds.valid:
        creds.refresh(Request())
    r = requests.get(f"https://www.googleapis.com/drive/v3/files/{SHEET_ID}?alt=media",
                     headers={"Authorization": f"Bearer {creds.token}"}, timeout=120)
    r.raise_for_status()
    LOCAL_SHEET.write_bytes(r.content)
    print(f"[panel] sheet de Nicole refrescado ({len(r.content):,} bytes)")


def mult2(x: float) -> int:
    return max(0, int(math.floor(x / 2 + 0.5) * 2))


def semanas_l6w(hoy: datetime.date) -> list[int]:
    w = hoy.isocalendar()[1]
    return [s for s in range(w - 9, w) if s not in SEM_EVENTO][-6:]


def cargar_parametros():
    xl = pd.ExcelFile(LOCAL_SHEET)
    prod = xl.parse("Productos")
    prod.columns = [c.strip() for c in prod.columns]
    prod = prod.dropna(subset=["Sku"]).drop_duplicates("Sku")
    prod["Sku"] = prod["Sku"].astype(str).str.strip()

    reglas = xl.parse("Reglas").iloc[:5]
    reglas.columns = ["Canal", "cob", "cob_large", "restr"]
    reglas = reglas.set_index("Canal")

    umin = xl.parse("Ume MIN", header=0)
    t_tipo = dict(zip(umin.iloc[:, 0].astype(str).str.strip(),
                      pd.to_numeric(umin.iloc[:, 1], errors="coerce")))
    t_marca = dict(zip(umin.iloc[:, 3].astype(str).str.strip(),
                       pd.to_numeric(umin.iloc[:, 4], errors="coerce")))
    t_tipo = {k: v for k, v in t_tipo.items() if pd.notna(v)}
    t_marca = {k: v for k, v in t_marca.items() if pd.notna(v)}

    bl = xl.parse("BLACKLIST")
    bl.columns = [c.strip() for c in bl.columns]
    blset = {(str(r["Canal"]).strip(), str(r["SKU"]).strip())
             for _, r in bl.iterrows() if pd.to_numeric(r.get("Blacklist"), errors="coerce") == 1}

    lg = xl.parse("LARGE")
    lg.columns = [c.strip() for c in lg.columns]
    lgset = {(str(r["Canal"]).strip(), str(r["SKU"]).strip())
             for _, r in lg.iterrows() if pd.to_numeric(r.get("Large"), errors="coerce") == 1}

    # UME Manual vigente (vive en la hoja UME del panel)
    ume_tab = xl.parse("UME")
    ume_tab["UME Manual"] = pd.to_numeric(ume_tab["UME Manual"], errors="coerce")
    manual = ume_tab.dropna(subset=["UME Manual"])
    manual_map = {(str(r["Sku"]).strip(), str(r["Canal"]).strip()): float(r["UME Manual"])
                  for _, r in manual.iterrows()}

    # v1.1: Blacklist AUTORITATIVA = columna Blacklist de la hoja UME del panel
    # (incluye criterio manual del KAM + no-publicados que la pestaña BLACKLIST no trae).
    # La pestaña BLACKLIST se mantiene como complemento para SKU-canal nuevos.
    ume_tab["Blacklist"] = pd.to_numeric(ume_tab["Blacklist"], errors="coerce")
    bl_panel = {(str(r["Sku"]).strip(), str(r["Canal"]).strip()): int(r["Blacklist"])
                for _, r in ume_tab.iterrows() if pd.notna(r["Blacklist"])}

    # v1.1: cobertura de planificación desde la hoja Plan del panel (viene del
    # reporte de Felipe e incluye tránsitos con ETA bodega). Packs: cobertura por
    # componentes (hoja Mapeo packs, columna 'Cob pack').
    plan = xl.parse("Plan")
    plan.columns = [str(c).strip() for c in plan.columns]
    plan["SKU"] = plan["SKU"].astype(str).str.strip()
    cob_plan = dict(zip(plan["SKU"], pd.to_numeric(plan["Cob"], errors="coerce")))
    mp = xl.parse("Mapeo packs")
    mp.columns = [str(c).strip() for c in mp.columns]
    mp["Pack"] = mp["Pack"].astype(str).str.strip()
    cob_pack = mp.groupby("Pack")[["Cob pack"]].min()["Cob pack"].to_dict()
    ts_plan = str(plan.get("ETA\nBodega", pd.Series(dtype=object)).dropna().max())[:10]
    print(f"[panel] Plan: {len(plan)} SKUs con cobertura | Mapeo packs: {len(cob_pack)} packs | max ETA bodega: {ts_plan}")

    dim = xl.parse("Dimensiones")
    dim.columns = [str(c).strip() for c in dim.columns]
    dim["SKU"] = dim["SKU"].astype(str).str.strip()
    dim_m3 = dict(zip(dim["SKU"], pd.to_numeric(dim["Dim m3"], errors="coerce")))
    dim_kg = dict(zip(dim["SKU"], pd.to_numeric(dim["Peso"], errors="coerce")))
    return (prod, reglas, t_tipo, t_marca, blset, lgset, manual_map, dim_m3, dim_kg,
            ume_tab, bl_panel, cob_plan, cob_pack)


def cargar_venta(sem: list[int]) -> pd.DataFrame:
    """Unidades por SKU x canal x semana ISO (año actual, cutoff mes anterior)."""
    anio = datetime.date.today().year
    corte = datetime.date.today().replace(day=1).isoformat()
    cols = ["sku", "canal", "fecha_venta", "cantidad"]
    h = pd.read_parquet(HIST, columns=cols)
    h = h[h["fecha_venta"].astype(str) < corte]
    m = pd.read_parquet(MES, columns=cols)
    m = m[m["fecha_venta"].astype(str) >= corte]
    v = pd.concat([h, m], ignore_index=True)
    v["fecha_venta"] = pd.to_datetime(v["fecha_venta"])
    v = v[v["fecha_venta"].dt.year == anio]
    iso = v["fecha_venta"].dt.isocalendar()
    v["week"] = iso["week"].astype(int)
    v = v[v["week"].isin(sem)]
    v["sku"] = v["sku"].astype(str).str.strip()
    v["cantidad"] = pd.to_numeric(v["cantidad"], errors="coerce").fillna(0)
    return v


def stock_full_live(no_live: bool) -> tuple[pd.DataFrame, str, dict | None]:
    """Stock por canal x sku en bodegas full. Feed Martín (misma base del Pulso
    Stock) + Walmart desde Odoo. Fallback total: Odoo BF*. Devuelve además el
    cruce Odoo vs live para la hoja Cuadratura."""
    det = pd.read_parquet(DETALLE)
    bcode = det["Bodega"].astype(str).str.split("/").str[0]
    BOD2CANAL = {"BFML": "Mercado Libre", "BFFa": "Falabella", "BFP": "Paris",
                 "BFR": "Ripley", "BFW": "Walmart", "BFE": "Falabella"}
    odoo = det[bcode.isin(BOD2CANAL)].copy()
    odoo["canal"] = bcode[bcode.isin(BOD2CANAL)].map(BOD2CANAL)
    odoo["sku"] = odoo["SKU"].astype(str).str.strip()
    odoo_g = odoo.groupby(["canal", "sku"], as_index=False)["Disponible"].sum() \
                 .rename(columns={"Disponible": "qty"})
    fuente, cruce = "Odoo (fallback)", None
    if not no_live:
        try:
            import fulfillment_live as fl
            try:
                live = fl.cargar_live()          # baja el ultimo mail de Martín
                fuente = "Seller center (feed Martín, fresco)"
            except Exception as e:
                live = pd.read_parquet(fl.LIVE_PARQUET)
                fuente = f"Seller center (parquet local, feed no disponible: {type(e).__name__})"
            cruce = fl.generar_cruce(live)
            canales_live = set(live["canal"].unique())
            base = pd.concat([live.rename(columns={"qty": "qty"})[["canal", "sku", "qty"]],
                              odoo_g[~odoo_g["canal"].isin(canales_live)]], ignore_index=True)
            return base.groupby(["canal", "sku"], as_index=False)["qty"].sum(), fuente, cruce
        except Exception as e:
            print(f"[live][WARN] {type(e).__name__}: {e} -> usando Odoo BF*")
    return odoo_g, fuente, cruce


def stock_ca1() -> pd.Series:
    det = pd.read_parquet(DETALLE)
    ca1 = det[det["Bodega"].astype(str).str.startswith("CA1")]
    return ca1.groupby(ca1["SKU"].astype(str).str.strip())["Disponible"].sum()


def costo_envio(m3: float) -> int:
    if m3 <= 0:
        return 0
    pallets = math.ceil(m3 / 2) * 5500
    if m3 < 2.8:
        return pallets
    if m3 <= 7:
        return 80000 + pallets
    return 120000 + pallets


def construir(no_download=False, no_live=False) -> Path:
    hoy = datetime.date.today()
    sem = semanas_l6w(hoy)
    print(f"[pulso] {hoy} — semana ISO {hoy.isocalendar()[1]} — L6W: {sem}")
    if not no_download:
        try:
            descargar_sheet()
        except Exception as e:
            print(f"[panel][WARN] no se pudo refrescar el sheet: {e} -> uso copia local")

    (prod, reglas, t_tipo, t_marca, blset, lgset, manual_map, dim_m3, dim_kg,
     ume_nicole, bl_panel, cob_plan, cob_pack) = cargar_parametros()
    venta = cargar_venta(sem)
    full, fuente_live, cruce = stock_full_live(no_live)
    full_map = {(r.canal, r.sku): r.qty for r in full.itertuples(index=False)}
    ca1 = stock_ca1()
    ts_stock = datetime.datetime.fromtimestamp(DETALLE.stat().st_mtime).strftime("%d-%m-%Y %H:%M")

    # transito del mes en curso
    tr = pd.read_parquet(TRANSITO)
    tr_mes = tr[tr["mes"].astype(str) == hoy.strftime("%Y-%m")]
    transito = tr_mes.groupby(tr_mes["sku"].astype(str).str.strip())["unidades"].sum()

    # venta semanal por sku x canal (L6W) y total todos los canales
    v_canal = venta.groupby(["sku", "canal"])["cantidad"].sum() / len(sem)
    v_total = venta.groupby("sku")["cantidad"].sum() / len(sem)

    filas = []
    for p in prod.itertuples(index=False):
        sku = str(getattr(p, "Sku")).strip()
        tipo = str(getattr(p, "Tipo de producto", "") or "").strip() if hasattr(p, "Tipo de producto") else ""
        # namedtuple muta nombres con espacios -> usar indice de columnas
        d = dict(zip(prod.columns, p))
        tipo = str(d.get("Tipo de producto", "") or "").strip()
        marca = str(d.get("Marca", "") or "").strip()
        umin = (t_tipo.get(tipo, 2) or 0) * (t_marca.get(marca, 0) or 0)
        stock_p = float(ca1.get(sku, 0))
        tra = float(transito.get(sku, 0))
        es_pack = str(d.get("Pack", "")).strip().lower() in ("si", "sí")
        # v1.1: cobertura de planificación = hoja Plan del panel (incluye tránsito
        # con ETA); packs por componentes (Mapeo packs); sin Plan -> restringido.
        cob_sku = cob_pack.get(sku) if es_pack and sku in cob_pack else cob_plan.get(sku)
        for canal in CANALES:
            ume = mult2(float(v_canal.get((sku, canal), 0)))
            manual = manual_map.get((sku, canal))
            large = 1 if (canal, sku) in lgset else 0
            # v1.1: blacklist autoritativa del panel; fallback pestaña para nuevos
            black = bl_panel.get((sku, canal), 1 if (canal, sku) in blset else 0)
            cob = reglas.loc[canal, "cob_large"] if large else reglas.loc[canal, "cob"]
            objetivo = max(max(ume, manual or 0) * cob, umin)
            live_q = float(full_map.get((canal, sku), 0))
            restr = 1 if (cob_sku is None or pd.isna(cob_sku)
                          or cob_sku < reglas.loc[canal, "restr"]) else 0
            repo = 0 if (black or restr) else max(0, objetivo - live_q)
            m3 = (dim_m3.get(sku) or 0) * repo
            kg = (dim_kg.get(sku) or 0) * repo
            filas.append({
                "Categoría": d.get("Categoría", ""), "Tipo de producto": tipo,
                "Marca": marca, "Pack": d.get("Pack", ""), "In/Out": d.get("In/Out", ""),
                "Sku": sku, "Producto": d.get("Producto", ""),
                "Categoría Comercial": d.get("Categoría Comercial", ""), "Canal": canal,
                "UME": ume, "UME MIN": umin, "UME Manual": manual,
                "Blacklist": black, "Restricción": restr, "Large": large,
                "Stock objetivo full": objetivo, "Stock Full Live": live_q,
                "Reposición": repo, "Dim m3": round(m3, 4), "Dim peso": round(kg, 2),
                "Stock bodega principal": stock_p, "Tránsito mes": tra,
                "Cobertura plan (meses)": round(cob_sku, 2) if (cob_sku is not None and pd.notna(cob_sku)) else "SIN PLAN",
            })
    df = pd.DataFrame(filas)

    # ---- comparación contra la planilla vigente de Nicole
    un = ume_nicole.copy()
    un["Sku"] = un["Sku"].astype(str).str.strip()
    for c in ["UME", "Reposición"]:
        un[c] = pd.to_numeric(un[c], errors="coerce")
    comp = df.merge(un[["Sku", "Canal", "UME", "Reposición", "Restricción", "Stock Full Live"]],
                    on=["Sku", "Canal"], how="outer", suffixes=("_v1", "_planilla"), indicator=True)

    # ---- resumen por canal
    act = df[df["Reposición"] > 0]
    res = act.groupby("Canal").agg(
        SKUs=("Sku", "nunique"), Unidades=("Reposición", "sum"),
        m3=("Dim m3", "sum"), kg=("Dim peso", "sum")).reset_index()
    res["Costo envío est."] = res["m3"].apply(costo_envio)
    res["Tramo"] = res["m3"].apply(lambda x: "<2,8 m3 (solo pallets)" if x < 2.8
                                   else ("2,8-7 m3 ($80k)" if x <= 7 else ">12 m3 ($120k)" if x > 12 else "7-12 m3"))

    # ---- escribir excel
    fn = OUT_DIR / f"Pulso_Reposicion_Fulfillment_{hoy:%Y%m%d}.xlsx"
    from openpyxl.styles import Font, PatternFill
    with pd.ExcelWriter(fn, engine="openpyxl") as w:
        res.to_excel(w, sheet_name="Resumen canal", index=False)
        df.sort_values(["Canal", "Reposición"], ascending=[True, False]).to_excel(
            w, sheet_name="UME v1", index=False)
        if cruce is not None:
            cruce["resumen"].to_excel(w, sheet_name="Cuadratura", index=False)
            cruce["detalle"].head(3000).to_excel(w, sheet_name="Cuadratura detalle", index=False)
        stats = pd.DataFrame([
            ["Corrida", f"{hoy} (semana ISO {hoy.isocalendar()[1]})"],
            ["Semanas venta usadas (L6W)", str(sem)],
            ["Fuente venta", "RAW ventas UnionX (histórico + mes actual)"],
            ["Fuente stock full", fuente_live],
            ["Fuente stock bodega principal", f"Odoo CA1 (detalle.parquet {ts_stock})"],
            ["Parámetros KAM", "Planilla 'Fulfillment sugeridos' (Reglas/UME MIN/Manual/Blacklist/Large)"],
            ["UME match vs planilla", f"{int((comp['UME_v1'] == comp['UME_planilla']).sum())} de {len(comp)}"],
            ["Reposición match vs planilla", f"{int((comp['Reposición_v1'] == comp['Reposición_planilla']).sum())} de {len(comp)}"],
            ["", ""],
            ["ADVERTENCIA 1", "El archivo actual NO anula reposición para SKUs con estado OUT "
             "(las definiciones dicen que sí). v1 replica el archivo. Definir criterio."],
            ["ADVERTENCIA 2", "Restricción de planificación (v1.1): cobertura por SKU desde la hoja "
             "Plan del panel (reporte de planificación, incluye tránsitos con ETA bodega); packs por "
             "componentes (Mapeo packs); SKU sin Plan => restringido. Regla validada 95,3% contra la "
             "planilla. La frescura depende de que la hoja Plan esté actualizada."],
            ["ADVERTENCIA 3", "Ripley sin cobertura objetivo (Reglas=0) -> sin sugerido, igual que la planilla."],
            ["ADVERTENCIA 4", "Walmart sin feed seller center -> stock live desde Odoo (BFW)."],
            ["ADVERTENCIA 5", "Packs: gobernados por BLACKLIST (default). Mapeo por componentes queda para v2."],
        ], columns=["Item", "Detalle"])
        stats.to_excel(w, sheet_name="Metodología", index=False)
        # diferencias principales vs planilla
        difs = comp[(comp["Reposición_v1"].fillna(-1) != comp["Reposición_planilla"].fillna(-1))]
        difs = difs.sort_values("Reposición_v1", ascending=False).head(500)
        difs.drop(columns=["_merge"]).to_excel(w, sheet_name="Difs vs planilla", index=False)
        # formato encabezados
        for ws in w.book.worksheets:
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor=AZUL)
            ws.freeze_panes = "A2"
    tot = int(act["Reposición"].sum())
    print(f"[pulso] guardado {fn.name} | {len(act)} SKU-canal a reponer | {tot:,} uds | "
          f"UME match {int((comp['UME_v1']==comp['UME_planilla']).sum())}/{len(comp)}")
    return fn


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true", help="usa la copia local del sheet")
    ap.add_argument("--no-live", action="store_true", help="stock full solo desde Odoo")
    a = ap.parse_args()
    construir(no_download=a.no_download, no_live=a.no_live)
