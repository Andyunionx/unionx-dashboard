"""
ROI por producto (SKU) — UnionX · v4 (28-sep-2026, definiciones de Andrés).

Marco (literatura retail):
  GMROI        = margen directo / inventario promedio en bodega a costo          (Levy & Weitz)
  ROI capital  = contribución / capital empleado                                  (GMROII + DPP/ABC)
  EVA          = contribución − capital empleado × costo de capital               (ingreso residual)
  Días de caja = capital empleado / costo diario                                  (cash-to-cash)

Contribución = venta neta − costo
               − comisión venta  (marketplace: % Maestra Pricing · páginas propias: medios de pago)
               − envío / logística canal (marketplace: % Maestra Pricing · web: flete propio por m³)
               − marketing (marketplace: % Maestra Pricing · web / fidelización / B2B: supuesto)
               − costo de operación asignado: almacenaje (m³ en CA1), manipulación (unidades ponderadas
                 B2C / B2B / fulfillment), insumos (pedidos B2C desde bodega), postventa (unidades devueltas)
Capital      = anticipo en producción y tránsito + 100% en aduana + inventario promedio − créditos
               (importación: saldo al llegar el barco; flete + internación a 30 días · nacional: 30 días)

El Excel sale con FÓRMULAS: cada SKU se calcula desde la pestaña Supuestos (celdas amarillas).

Fuentes (todas solo lectura): RAW ventas · Maestra Productos (Drive) · Maestra Pricing (Drive) ·
PIs (Maestra Importaciones + tránsito) · stock diario Odoo · control_gestion (costo por centro) ·
medidas oficiales / maestro Loginsa.

Uso:  python roi_producto.py [--refresh]   (--refresh vuelve a bajar Drive, Odoo y stock)
Salida: data/outputs/ROI_Producto_UnionX_<fecha>.xlsx
"""
from __future__ import annotations

import argparse
import difflib
import io
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "roi"
OUT_DIR = ROOT / "data" / "outputs"

# ── Supuestos (editables también en la pestaña Supuestos del Excel y en el panel "Supuestos ROI" de Drive) ──
def _ventana_movil() -> tuple[str, str]:
    """Últimos 12 meses CERRADOS: hasta el 1° del mes en curso (excluyente). Si el histórico de ventas aún no
    trae el mes recién cerrado, se retrocede un mes. Override: env ROI_VENTANA_HASTA=AAAA-MM-01."""
    import os
    h = os.environ.get("ROI_VENTANA_HASTA", "").strip()
    if h:
        hasta = pd.Timestamp(h)
    else:
        hasta = pd.Timestamp.today().normalize().replace(day=1)
        try:
            mx = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet", columns=["fecha_venta"]).fecha_venta
            if pd.to_datetime(mx).max() < hasta - pd.Timedelta(days=1):
                hasta -= pd.DateOffset(months=1)
        except Exception:  # noqa: BLE001
            pass
    return str((hasta - pd.DateOffset(months=12)).date()), str(hasta.date())


VENTANA_DESDE, VENTANA_HASTA = _ventana_movil()   # HASTA excluyente
ALCANCE = "Todas las ventas"          # selector (Andrés 1-oct): "Todas las ventas" | "Digital + UnionX B2B"
ESCENARIO_DEF = "Mix real"
FID_PROG_DEF = "Todos (promedio ponderado)"
TASA_CAPITAL = 0.09
TC_USD = 946.0
TRANSITO_DIAS = {"Shenzhen": 55, "Ningbo": 45, "Incheon": 30}
TRANSITO_DEFAULT = 55
ADUANA_DIAS = 7
CREDITO_FLETE_INTERNACION_DIAS = 30
CREDITO_NACIONAL_DIAS = 30
FOB_SHARE_DEFAULT = 0.90              # FOB / landed cuando un importado no tiene costo USD (Maestra: ~0,93)
LT_PRODUCCION_DEFAULT = 35
PESO_B2C, PESO_B2B = 1.0, 0.53       # manipulación ABC: la unidad B2B/fulfillment promedio cuesta 53% de una B2C
IVA = 0.19
# Escenarios de canal (definición comercial: editables en Supuestos)
MKT_WEB, MKT_FID, MKT_B2B = 0.10, 0.0, 0.0
FACTOR_PRECIO = {"MKP": 1.0, "WEB": 1.0, "FID": 1.0}   # × precio de lista de la Pricing
ESCENARIOS = ["Mix real", "Solo marketplace", "Solo páginas web", "Solo fidelización", "Mix personalizado"]
MIX_DEFAULT = {"MKP": 0.60, "WEB": 0.25, "FID": 0.15}
TASAS_DESDE = "2026-08-01"
# Sensibilidad estándar: cuánto se mueve cada palanca para comparar cuál pesa más en cada SKU (editable en Supuestos)
SHOCK = {"precio": 0.05, "costo": 0.05, "mix": 0.10, "anticipo": 0.10, "prod": 10, "tran": 10, "inv": 0.20, "m3": 0.20,
         "uds": 0.10}
# Interacción entre palancas (Andrés 1-oct): el precio mueve unidades (elasticidad) y vender más no exige
# todo el inventario proporcional (solo INV_ACOMP: el resto es rotación más alta). Elasticidad 0 en la
# sensibilidad estándar para que el ranking sea comparable; se simula caso a caso en la Calculadora.
ELASTICIDAD = 0.0
INV_ACOMP = 0.75
PALANCAS = ["Precio", "Costo compra", "Mix canal", "Anticipo", "Saldo en Chile", "Producción", "Tránsito", "Rotación",
            "m³", "Unidades"]            # el RAW trae comisión/logística en la línea de venta desde ago-26
UMBRAL_ROTACION = 4.0                 # veces al año
UMBRAL_CONTRIB = 0.20                 # contribución / venta
TOL_COSTO = 0.03
STOCK_DESDE_MOVES = str((pd.Timestamp(VENTANA_DESDE) - pd.DateOffset(months=1)).date())
STOCK_ROI = CACHE / "stock_diario_roi.parquet"
BODEGA_PROPIA = "CA1"
EXCLUIR_PATRON = (r"respuesto|repuesto|dummy|personalizaci|post venta|compostable|bolsa|cinta embalaje|"
                  r"\bfilm\b|etiqueta|dice cup|corporativo")

SHEET_MAESTRA_PRODUCTOS = "1LskgqxkQXRza4gpRtOWWeeMh0uzkUTcg9JuN9xSMOh0"
FILE_MAESTRA_PRICING = "1gVJmFCR19KbYkZfds7fH-62rJ0Zpt32P"
FILE_MAESTRA_COMEX = "1Q9gtihNJkmExH328lXaw1kv_pP7yB0VK"   # Maestra Importaciones VIVA (Drive)
MAESTRA_IMPORT = CACHE / "maestra_importaciones.xlsx"         # se baja de Drive en cada corrida

POOL_ESPACIO = {"MEGACENTRO CORDILLERA", "ARRIENDO CORDILLERA", "GGCC MEGACENTRO CORDILLERA",
                "RACK RENTAL", "SEGURIDAD OFICINA", "MAQUINARIA", "MANUF RAC", "LICMAN"}
POOL_MANIPULACION_CUENTAS = {"OPERARIO", "JEFATURA-BODEGA", "COORDINACIÓN-INVENTARIO",
                             "COORDINACIÓN-LOGISTICA", "OPERARIO-CHOFER", "BONO HHEE", "BONO PROD",
                             "BONO BOD", "LEYES SOCIALES", "INDUMENTARIA", "EPP",
                             "VEHICULOS Y EQ. TRANSPORTE", "AUTOPISTAS", "COMBUSTIBLE", "MOVILIZACIÓN"}
POOL_MANIPULACION_PREFIJOS = ("OPERARIO-LOGISTICO", "OPERARIO-INVENTARIO")
P_ESP, P_MAN, P_PV, P_INS = "Almacenaje", "Manipulación", "Postventa / log. inversa", "Insumos"
P_NA = "No asignado a producto"
# Desde 6-oct-2026 control_gestion publica remuneraciones solo como total por equipo (el repo es público: sin
# nombres ni cargos; ver anonimizar_remuneraciones.py). Del sueldo de Operaciones sin Postventa, esta fracción
# es personal de bodega (pool Manipulación): medida con el detalle por cargo de la ventana oct-25 → sep-26,
# $138,5MM de $218,0MM. Recalcular con la nómina local si cambia la dotación de bodega.
SHARE_MANIPULACION_REM_OPERACIONES = 0.6352
FORMATO_SKU = ROOT / "data/comex/formato_importacion_sku.parquet"

CLASES = ["Estrella", "Nicho", "Volumen", "Paga justo", "No paga su capital", "Destruye valor", "Sin venta"]
# Segmentos (Andrés 1-oct): el ROI se lee sobre lo Activo; Out = capital por liberar; Consignación no usa capital;
# Solo stock = alarma (sin venta en la ventana). Todos quedan en 'ROI por SKU' para que los pools se repartan completos.
SEGMENTOS = ["Activo", "Out", "Consignación", "Solo stock"]
CAT_COMERCIAL_ORDEN = ["Diamante", "Oro", "Plata", "Bronce", "Nuevo", "Descontinuado", "Corporativo", "In/Out",
                       "Sin categoría"]


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def num(s):
    s = str(s).replace("$", "").replace(" ", "").strip()
    if s in ("", "nan", "-", "None"):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


# ── Descargas (solo lectura) ────────────────────────────────────────────────
def bajar_drive(refresh: bool):
    CACHE.mkdir(parents=True, exist_ok=True)
    f_prod, f_pric = CACHE / "maestra_productos_raw.parquet", CACHE / "maestra_pricing.xlsx"
    if not refresh and f_prod.exists() and f_pric.exists() and MAESTRA_IMPORT.exists():
        return
    sys.path.insert(0, str(ROOT))
    from drive_user_helpers import descargar_archivo
    descargar_archivo(FILE_MAESTRA_COMEX, MAESTRA_IMPORT)
    sys.path.insert(0, str(ROOT))
    import gspread
    from googleapiclient.http import MediaIoBaseDownload
    from drive_user_helpers import _credentials, _service
    sh = gspread.authorize(_credentials()).open_by_key(SHEET_MAESTRA_PRODUCTOS)
    hojas = []
    for ws in sh.worksheets():
        if ws.title.lower().startswith("copia"):
            pd.DataFrame(ws.get_all_values()).astype(str).to_parquet(CACHE / "copia_productos_raw.parquet")
            continue
        v = ws.get_all_values()
        if v:
            d = pd.DataFrame(v)
            d.insert(0, "_hoja", ws.title)
            hojas.append(d.astype(str))
    pd.concat(hojas, ignore_index=True).to_parquet(f_prod)
    req = _service().files().get_media(fileId=FILE_MAESTRA_PRICING, supportsAllDrives=True)
    with io.FileIO(f_pric, "wb") as fh:
        dl, done = MediaIoBaseDownload(fh, req), False
        while not done:
            _, done = dl.next_chunk()


def bajar_odoo(refresh: bool) -> pd.DataFrame:
    f = CACHE / "odoo_productos.parquet"
    if refresh or not f.exists():
        sys.path.insert(0, str(ROOT))
        import diagnostico_caja_odoo as dco
        rows = dco.conectar().search_read_paginated(
            "product.product", ["|", ("active", "=", True), ("active", "=", False)],
            ["id", "default_code", "name", "active", "standard_price", "volume"], page_size=2000)
        df = pd.DataFrame(rows)
        df["default_code"] = df["default_code"].map(lambda x: str(x).strip() if x else "")
        df["name"] = df["name"].map(lambda x: str(x) if x else "")
        df.to_parquet(f)
    return pd.read_parquet(f)


def plantillas_y_kits(refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Plantilla de cada variante (product_tmpl_id) y listas de materiales tipo kit (mrp.bom), solo lectura.
    Devuelve (plantillas: index=código → tmpl, plantilla) y (kits: pack, comp, qty)."""
    f_t, f_b = CACHE / "odoo_plantillas.parquet", CACHE / "odoo_kits.parquet"
    if refresh or not f_t.exists() or not f_b.exists():
        sys.path.insert(0, str(ROOT))
        import diagnostico_caja_odoo as dco
        cli = dco.conectar()
        pp = pd.DataFrame(cli.search_read_paginated(
            "product.product", ["|", ("active", "=", True), ("active", "=", False)],
            ["id", "default_code", "product_tmpl_id"], page_size=2000))
        pp["k"] = pp["default_code"].map(lambda x: str(x).strip().upper() if x else "")
        pp["tmpl"] = pp["product_tmpl_id"].map(lambda x: x[0] if isinstance(x, list) else None)
        pp["plantilla"] = pp["product_tmpl_id"].map(lambda x: x[1] if isinstance(x, list) else "")
        pp[["id", "k", "tmpl", "plantilla"]].to_parquet(f_t)
        boms = pd.DataFrame(cli.search_read_paginated("mrp.bom", [("type", "=", "phantom")],
                                                      ["id", "product_tmpl_id", "product_id"], page_size=2000))
        lines = pd.DataFrame(cli.search_read_paginated("mrp.bom.line", [("bom_id", "in", boms["id"].tolist())],
                                                       ["bom_id", "product_id", "product_qty"], page_size=2000)) \
            if len(boms) else pd.DataFrame(columns=["bom_id", "product_id", "product_qty"])
        cod = pp.set_index("id")["k"]
        rows = []
        for b in boms.itertuples():
            if isinstance(b.product_id, list):
                packs_ = [cod.get(b.product_id[0], "")]
            else:
                packs_ = pp.loc[pp["tmpl"] == b.product_tmpl_id[0], "k"].tolist()
            for l in lines[lines["bom_id"].map(lambda x: x[0]) == b.id].itertuples():
                comp = cod.get(l.product_id[0], "") if isinstance(l.product_id, list) else ""
                rows += [{"pack": p_, "comp": comp, "qty": float(l.product_qty)} for p_ in packs_ if p_ and comp]
        pd.DataFrame(rows, columns=["pack", "comp", "qty"]).to_parquet(f_b)
    t = pd.read_parquet(f_t)
    t = t[t["k"] != ""].drop_duplicates("k").set_index("k")
    return t, pd.read_parquet(f_b)


def generar_stock_roi(refresh: bool) -> pd.DataFrame:
    """Stock diario por product_id y bodega para la ventana, en caché propio (no pisa data/stock_historico).
    Se reconstruye desde Odoo si se pide o si el caché no cubre la ventana móvil."""
    cubre = False
    if STOCK_ROI.exists():
        f_ = pd.read_parquet(STOCK_ROI, columns=["fecha"])["fecha"]
        cubre = (f_.min() <= pd.Timestamp(VENTANA_DESDE) + pd.Timedelta(days=3)
                 and f_.max() >= pd.Timestamp(VENTANA_HASTA) - pd.Timedelta(days=3))
    if refresh or not cubre:
        import os
        if not os.environ.get("ANDRES_ODOO_PASSWORD"):
            p = ROOT / "odoo" / ".odoo_pass"
            if p.exists():
                os.environ["ANDRES_ODOO_PASSWORD"] = p.read_text().strip()
        sys.path.insert(0, str(ROOT))
        import extract_stock_historico as esh
        from datetime import datetime
        odoo = esh._conectar_odoo()
        loc_to_bodega, loc_ids = esh._obtener_locations_relevantes(odoo)
        quant_hoy = esh._snapshot_quant_actual(odoo, loc_ids)
        deltas, mes = [], pd.Timestamp(STOCK_DESDE_MOVES)
        while mes <= pd.Timestamp.now():
            dm = esh._extraer_movimientos_mes(odoo, loc_ids, mes.strftime("%Y-%m"))
            if not dm.empty:
                deltas.append(esh._expandir_movimientos_a_deltas(dm, loc_to_bodega))
            mes += pd.offsets.MonthBegin(1)
        d = pd.concat(deltas, ignore_index=True).groupby(["fecha", "sku", "bodega"], as_index=False)["delta"].sum()
        st = esh._reconstruir_saldo_diario(quant_hoy, d, loc_to_bodega, datetime.now(), STOCK_DESDE_MOVES)
        st["fecha"] = pd.to_datetime(st["fecha"])
        st = st[(st.fecha >= VENTANA_DESDE) & (st.fecha < VENTANA_HASTA)]
        st = st[st.cantidad != 0]
        st["cantidad"] = st["cantidad"].astype("float32")
        st["sku"] = st["sku"].astype("int32")
        st["bodega"] = st["bodega"].astype("category")
        st.to_parquet(STOCK_ROI, compression="zstd", index=False)
    return pd.read_parquet(STOCK_ROI)


# ── Maestras ────────────────────────────────────────────────────────────────
def cargar_pricing():
    x = pd.ExcelFile(CACHE / "maestra_pricing.xlsx")
    pr = x.parse("Pricing", header=1)
    pr = pr[pr["SKU"].notna()].copy()
    pr["sku"] = pr["SKU"].astype(str).str.strip().str.upper()
    for c in ["Comision % (TY) Neto", "Logistica % (TY) Neto", "Mkt % (TY) Neto", "Costo"]:
        pr[c] = pd.to_numeric(pr[c], errors="coerce")
    pr = pr.drop_duplicates("sku")
    # % TY reales: SKU con poca venta traen extremos (−132%, 1.239%) o 0 en packs → mediana de su categoría
    com, log, mkt = "Comision % (TY) Neto", "Logistica % (TY) Neto", "Mkt % (TY) Neto"
    valido = pr[com].between(0.01, 0.5) & pr[log].between(0, 0.35) & pr[mkt].between(0, 0.2)
    pr["pct_fuente"] = np.where(valido, "Maestra Pricing (SKU)", "Mediana categoría (Pricing)")
    for c in (com, log, mkt):
        med_cat = pr[valido].groupby("Categoria Padre")[c].median()
        pr[c] = pr[c].where(valido, pr["Categoria Padre"].map(med_cat)).fillna(pr.loc[valido, c].median())
    mae = x.parse("Maestra", header=0)
    mae["sku"] = mae["Sku"].astype(str).str.strip().str.upper()
    mae = mae.drop_duplicates("sku").set_index("sku")
    packs = x.parse("Packs", header=0)
    packs = packs[packs["Pack"].notna() & packs["SKU"].notna()].copy()
    packs["pack"] = packs["Pack"].astype(str).str.strip().str.upper()
    packs["comp"] = packs["SKU"].astype(str).str.strip().str.upper()
    packs["pvp"] = pd.to_numeric(packs["PVP Oferta MKT"], errors="coerce").fillna(0)
    return pr, mae, packs[["pack", "comp", "pvp"]]


def cargar_maestra_productos(pr: pd.DataFrame) -> pd.DataFrame:
    raw = pd.read_parquet(CACHE / "maestra_productos_raw.parquet")
    idx = dict(zip(pr["Descripcion"].map(norm), pr["sku"]))
    keys = list(idx)
    out = []
    for hoja, d in raw.groupby("_hoja", sort=False):
        d = d.drop(columns="_hoja").reset_index(drop=True)
        hdr = [str(h).strip() for h in d.iloc[0]]
        if "Sku" not in hdr:
            continue
        d.columns = [h if h else f"c{i}" for i, h in enumerate(hdr)]
        d = d.iloc[1:]
        d = d[d["Descripcion"].str.strip() != ""]
        d["hoja"] = hoja
        out.append(d)
    m = pd.concat(out, ignore_index=True)

    def mapea(r):
        s = str(r["Sku"]).strip()
        if s and s.lower() != "nan":
            return s.upper(), "sku"
        n = norm(r["Descripcion"])
        if n in idx:
            return idx[n], "descripcion"
        nums = set(re.findall(r"\d+", n))
        for c in difflib.get_close_matches(n, keys, n=3, cutoff=0.85):
            if set(re.findall(r"\d+", c)) == nums:
                return idx[c], "descripcion aprox."
        return None, "sin cruce"

    r = m.apply(mapea, axis=1, result_type="expand")
    m["sku"], m["cruce_sku"] = r[0], r[1]
    m["costo_usd_maestra"] = m["COSTO USD"].map(num)
    m["lt_produccion"] = m["LEAD TIME"].map(lambda s: num(re.sub(r"[^\d,\.]", "", str(s))))
    m["moq"] = m["MOQ"].map(num)
    m["tipo_pago"] = m["Tipo Pago"].str.strip()
    m["puerto"] = m["Puerto Origen"].str.strip()
    return m


def historial_pi(codigos_odoo: set | None = None) -> pd.DataFrame:
    mx = pd.read_excel(MAESTRA_IMPORT, sheet_name="Maestra")
    mx.columns = [str(c).strip() for c in mx.columns]
    emb = [c for c in mx.columns if "Embarque" in c][0]
    mx = mx[mx[emb].notna()].copy()
    sku_num = pd.to_numeric(mx["SKU"], errors="coerce").notna() & ~mx["SKU"].astype(str).str.match(r"^\d{10,}$")
    ok = mx[~sku_num].copy()
    ok["usd"] = pd.to_numeric(ok["Cost Unit"], errors="coerce")
    ok["qty"] = pd.to_numeric(ok["QTY"], errors="coerce")
    ok["sku"] = ok["SKU"].astype(str).str.strip().str.upper()
    ok["fuente"] = "Maestra Importaciones"
    m2s = (ok.dropna(subset=["Model"]).assign(model=lambda d: d["Model"].astype(str).str.strip().str.upper())
           .groupby("model")["sku"].agg(lambda s: s.mode().iat[0]))
    cor = mx[sku_num].copy()  # filas 2026 con columnas corridas: SKU=qty, NOMBRE=USD, sin SKU UnionX
    modelo = cor["Model"].astype(str).str.strip().str.upper()
    cor["sku"] = modelo.map(m2s)
    if codigos_odoo:  # a veces el "modelo" ya es el código UnionX
        cor["sku"] = cor["sku"].fillna(modelo.where(modelo.isin(codigos_odoo)))
    cor["qty"] = pd.to_numeric(cor["SKU"], errors="coerce")
    cor["usd"] = pd.to_numeric(cor["NOMBRE"], errors="coerce")
    cor["fuente"] = "Maestra Importaciones (modelo→SKU)"
    cols = [emb, "sku", "qty", "usd", "ETA", "fuente"]
    h = pd.concat([ok[cols], cor[cols]]).rename(columns={emb: "pi"})
    h["fecha"] = pd.to_datetime(h["ETA"], errors="coerce")
    ts = pd.read_parquet(ROOT / "data/comex/transito_sheet.parquet")
    ts = ts.rename(columns={"cantidad": "qty", "costo_unitario_usd": "usd"})
    ts["sku"] = ts["sku"].astype(str).str.strip().str.upper()
    ts["fecha"] = pd.to_datetime(ts["fecha_eta_bodega"], errors="coerce").fillna(
        pd.to_datetime(ts["fecha_embarque"], errors="coerce"))
    ts["fuente"] = "Importaciones Integrada (tránsito)"
    h = pd.concat([h[["pi", "sku", "qty", "usd", "fecha", "fuente"]], ts[["pi", "sku", "qty", "usd", "fecha", "fuente"]]])
    h["pi"] = h["pi"].astype(str).str.extract(r"(\d{2}TP\d{4})", expand=False).fillna(h["pi"].astype(str))
    h = h.dropna(subset=["sku", "usd"])
    h = h[(h.usd > 0) & (h.usd < 2000)].drop_duplicates(["pi", "sku", "usd", "qty"])
    return h.sort_values("fecha")


def auditar_costo(mp: pd.DataFrame, pi: pd.DataFrame) -> pd.DataFrame:
    ult = pi.groupby("sku").agg(pi_ultima=("pi", "last"), fecha_pi=("fecha", "last"), usd_ultima_pi=("usd", "last"),
                                n_pi=("pi", "nunique"), usd_min_hist=("usd", "min"), usd_max_hist=("usd", "max"))
    a = mp.merge(ult, left_on="sku", right_index=True, how="left")
    a["dif_pct"] = a["costo_usd_maestra"] / a["usd_ultima_pi"] - 1

    def est(r):
        if pd.isna(r.costo_usd_maestra):
            return "Sin costo en maestra"
        if pd.isna(r.usd_ultima_pi):
            return "Sin PI registrada"
        if abs(r.dif_pct) <= TOL_COSTO:
            return "OK"
        return "Maestra sobre última PI" if r.dif_pct > 0 else "Maestra bajo última PI"
    a["estado_costo"] = a.apply(est, axis=1)
    a["costo_usd_usado"] = a["usd_ultima_pi"].fillna(a["costo_usd_maestra"])
    return a


def copia_productos() -> pd.DataFrame:
    """Hoja 'Copia de Productos' de la Maestra (formato 2024: Units CTN, CBM/CTN, G.W/CTN, Packaging)."""
    f = CACHE / "copia_productos_raw.parquet"
    if not f.exists():
        return pd.DataFrame()
    c = pd.read_parquet(f)
    c.columns = [str(h).strip() for h in c.iloc[0]]
    c = c.iloc[1:]
    c = c[c["SKU"].astype(str).str.strip() != ""].copy()
    c["sku"] = c["SKU"].astype(str).str.strip().str.upper()
    for k, col in [("uds_caja", "Units CTN"), ("cbm_caja", "CBM / CTN"), ("gw_caja_kg", "G.W（kg)/CTN"),
                   ("gift_box_usd", "Packaging 2024"), ("costo_usd_2024", "Costo 2024")]:
        c[k] = c[col].map(num) if col in c.columns else None
    c["medida_caja_cm"] = c.get("CTN Size (CM)/CTN")
    return c.drop_duplicates("sku").set_index("sku")


def medidas() -> tuple[pd.Series, pd.Series]:
    """m³ por unidad: medidas oficiales → maestro enviado a Loginsa. Devuelve (m3, fuente)."""
    me = pd.read_parquet(ROOT / "data/comex/_medidas_oficiales.parquet")
    me["sku"] = me["SKU"].astype(str).str.strip().str.upper()
    me["m3"] = pd.to_numeric(me["L"], errors="coerce") * pd.to_numeric(me["A"], errors="coerce") * \
        pd.to_numeric(me["H"], errors="coerce") / 1e6
    of = me[me.m3 > 0].drop_duplicates("sku").set_index("sku")["m3"]
    lg_path = CACHE / "medidas_loginsa.parquet"
    lg = pd.read_parquet(lg_path).set_index("sku")["m3_lg"] if lg_path.exists() else pd.Series(dtype=float)
    lg = lg[~lg.index.isin(of.index)]
    m3 = pd.concat([of, lg])
    fuente = pd.Series("Medidas oficiales", index=of.index)._append(pd.Series("Maestro Loginsa", index=lg.index))
    return m3, fuente


# ── Pools del costo de operación (control_gestion, FCST = real) ─────────────
def pools_operacion():
    cg = pd.read_parquet(ROOT / "data/finanzas/control_gestion.parquet")
    x = cg[(cg.escenario == "FCST") & (cg.fecha >= VENTANA_DESDE) & (cg.fecha < VENTANA_HASTA)].copy()
    x["monto"] = -x["valor"] * 1000  # miles CLP negativos → CLP positivos
    cta = x["cuenta_analitica"].astype(str).str.strip().str.upper()
    cc = x["centro_costo"].astype(str).str.strip().str.upper()
    area = x["area"].astype(str).str.strip().str.upper()
    sub = x["sub_area"].astype(str).str.strip().str.upper()
    oper = area.eq("OPERACIONES") & x["kpi"].eq("GASTO")
    x["pool"] = None
    x.loc[oper & cta.isin(POOL_ESPACIO), "pool"] = P_ESP
    x.loc[oper & (cta.isin(POOL_MANIPULACION_CUENTAS) | cta.str.startswith(POOL_MANIPULACION_PREFIJOS)), "pool"] = P_MAN
    x.loc[oper & sub.eq("POSTVENTA"), "pool"] = P_PV
    x.loc[oper & x["pool"].isna(), "pool"] = P_NA
    x.loc[cc.eq("INSUMOS") & x["kpi"].eq("GASTO"), "pool"] = P_INS
    x = x[x["pool"].notna()].copy()
    # Remuneraciones publicadas sin cargo: Operaciones (salvo Postventa) se reparte Manipulación / No asignado
    agreg = (x["area"].astype(str).str.upper().eq("OPERACIONES") & x["kpi"].eq("GASTO")
             & x["centro_costo"].astype(str).str.upper().eq("REMUNERACIONES")
             & x["cuenta_analitica"].astype(str).str.strip().str.upper().eq("REMUNERACIONES")
             & ~x["sub_area"].astype(str).str.upper().eq("POSTVENTA"))
    if agreg.any():
        parte = x[agreg].copy()
        parte["monto"] *= SHARE_MANIPULACION_REM_OPERACIONES
        parte["pool"] = P_MAN
        x.loc[agreg, "monto"] *= 1 - SHARE_MANIPULACION_REM_OPERACIONES
        x = pd.concat([x, parte], ignore_index=True)
    # "JEFATURA" (nombre antiguo en LOGISTICA) = jefatura bodega + facturación → proporción de los meses nuevos
    cta = x["cuenta_analitica"].astype(str).str.strip().str.upper()
    jb = x.loc[cta.eq("JEFATURA-BODEGA"), "monto"].sum()
    jf = x.loc[cta.eq("JEFATURA-FACTURAC"), "monto"].sum()
    antigua = cta.eq("JEFATURA") & x["sub_area"].astype(str).str.upper().eq("LOGISTICA") & x["pool"].eq(P_NA)
    if antigua.any() and jb + jf > 0:
        parte = x[antigua].copy()
        parte["monto"] *= jb / (jb + jf)
        parte["pool"] = P_MAN
        parte["cuenta_analitica"] = "JEFATURA (antigua, parte bodega)"
        x.loc[antigua, "monto"] *= jf / (jb + jf)
        x.loc[antigua, "cuenta_analitica"] = "JEFATURA (antigua, parte facturación)"
        x = pd.concat([x, parte])
    det = x.groupby(["pool", "area", "sub_area", "centro_costo", "cuenta_analitica"], as_index=False)["monto"].sum()
    tot = det.groupby("pool")["monto"].sum()
    return det.sort_values(["pool", "monto"], ascending=[True, False]), tot


def dias_cobro() -> dict:
    """Días de cobro de la empresa (opción a): CxC comerciales promedio 12m / venta con IVA × 365."""
    kt = pd.read_parquet(ROOT / "data/finanzas/kt.parquet")
    c = kt[(kt.linea == "CxC comerciales") & (kt.fecha >= VENTANA_DESDE) & (kt.fecha < VENTANA_HASTA)].valor.mean() * 1000
    p = pd.read_parquet(ROOT / "data/finanzas/pyl_mensual.parquet")
    v = p[(p.linea == "Ingresos") & (p.fecha >= VENTANA_DESDE) & (p.fecha < VENTANA_HASTA)].valor.sum() * 1000
    return {"cxc_prom": c, "venta_eerr": v, "dias": c / (v * (1 + IVA)) * 365 if v else 0}


def tasas_canal(v: pd.DataFrame) -> dict:
    """Comisión y envío reales fuera de marketplace (RAW, línea de venta desde ago-26) y unidades por pedido.
    Fidelización: tasa por programa × venta 12m del programa (programas sin dato en el RAW = 0%)."""
    vt = v[v.tipo_movimiento.eq("Venta") & (v.cantidad > 0)]
    rec = vt[vt.fecha_venta >= TASAS_DESDE]
    tasa = rec.groupby("canal")[["venta_neta", "comision", "logistica"]].sum()
    tasa = tasa.assign(com=tasa.comision / tasa.venta_neta, env=tasa.logistica / tasa.venta_neta)
    v12 = vt.groupby(["neg", "canal"])["venta_neta"].sum()

    def pondera(neg):
        x = v12.loc[neg].to_frame("venta").join(tasa[["com", "env"]]).fillna(0)
        x = x[x.venta > 0]
        return x, float((x.venta * x.com).sum() / x.venta.sum()), float((x.venta * x.env).sum() / x.venta.sum())
    fid, fcom, fenv = pondera("fid")
    _, wcom, wenv = pondera("web")
    _, bcom, benv = pondera("b2b")
    upp = {k: float(vt[vt.neg == k].cantidad.sum() / max(vt[vt.neg == k].pedido.nunique(), 1)) for k in ["mkp", "web", "fid"]}
    fid = fid.sort_values("venta", ascending=False).reset_index().rename(columns={"canal": "programa"})
    return dict(web_com=wcom, web_env=wenv, b2b_com=bcom, b2b_env=benv, fid_com=fcom, fid_env=fenv,
                fid_prog=fid, upp=upp)


def conciliacion_eerr(s: pd.DataFrame) -> pd.DataFrame:
    """Cascada del ROI vs EERR contable (pyl_mensual) en la misma ventana: solo informativo."""
    p = pd.read_parquet(ROOT / "data/finanzas/pyl_mensual.parquet")
    x = p[(p.fecha >= VENTANA_DESDE) & (p.fecha < VENTANA_HASTA)].groupby("linea").valor.sum() * 1000
    g = lambda k: float(x.get(k, 0.0))
    filas = [
        ("Venta neta", g("Ingresos"), s.venta.sum()),
        ("Costo de venta", -g("Costo Directo de Venta"), s.costo.sum()),
        ("Comisión + envío (EERR: Comisión y Envío Grandes Cuentas)", -g("Comisión y Envío Grandes Cuentas"),
         s.comision.sum() + s.logistica.sum()),
        ("Marketing (EERR: Marketing Performance)", -g("Marketing Performance"), s.marketing.sum()),
        ("Flete, insumos y combustible (EERR, costo directo)", -g("Flete, insumos y combustible."), np.nan),
        ("Costo de operación asignado (en el EERR va dentro del GAV)", np.nan,
         s.almacenaje.sum() + s.manipulacion.sum() + s.insumos.sum() + s.postventa.sum()),
        ("Margen de contribución EERR / contribución ROI", g("Margen Contribución"), s.contribucion.sum()),
    ]
    return pd.DataFrame(filas, columns=["Línea", "EERR contable 12m ($)", "ROI 12m ($)"])


# ── Motor ───────────────────────────────────────────────────────────────────
def calcular(refresh=False):
    bajar_drive(refresh)
    prod = bajar_odoo(refresh)
    pr, mae_pr, packs = cargar_pricing()
    tmpl, kits = plantillas_y_kits(refresh)
    mp = cargar_maestra_productos(pr)
    pi = historial_pi(set(prod["default_code"].str.upper()) - {""})
    aud = auditar_costo(mp, pi)
    pools_det, pools = pools_operacion()

    v = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet")
    v = v[(v.fecha_venta >= VENTANA_DESDE) & (v.fecha_venta < VENTANA_HASTA)].copy()
    v["sku"] = v["sku"].astype(str).str.strip().str.upper()
    v = v[~v["sku"].isin(["", "0", "NAN", "NONE", "AD_VALOREM"])]
    v = v[~v["sku"].str.startswith(("DELIVERY", "MULTIVENDE")) & ~v["tipo_compra"].astype(str).eq("Envío")]
    neg = v["tipo_negocio"].astype(str).str.strip().str.lower()
    v["neg"] = np.select([neg.eq("marketplace"), neg.str.startswith("páginas"), neg.eq("fidelización"),
                          neg.isin(["distribución", "corporativo"])], ["mkp", "web", "fid", "b2b"], "otro")
    v["ff"] = v["bodega"].astype(str).str.contains("Fulfillment", case=False)
    ventas = v[v.tipo_movimiento.isin(["Venta", "Devolución"])].copy()

    # costo unitario landed: RAW (ponderado) → Pricing → Odoo; costo 0 en ventas se rellena
    cu_raw = (ventas[(ventas.costo_total > 0) & (ventas.cantidad > 0)].groupby("sku")
              [["costo_total", "cantidad"]].sum().pipe(lambda d: d.costo_total / d.cantidad))
    cu = cu_raw.combine_first(pr.set_index("sku")["Costo"].where(lambda s: s > 0))
    cu = cu.combine_first(prod.assign(k=prod.default_code.str.upper()).query("standard_price > 0")
                          .groupby("k")["standard_price"].median())
    sin_costo = (ventas.costo_total == 0) & (ventas.cantidad != 0) & \
        ~ventas.tipo_compra.astype(str).isin(["Consignación", "Envío"])
    ventas["costo"] = ventas["costo_total"] + np.where(sin_costo, ventas["sku"].map(cu) * ventas["cantidad"], 0)
    ventas["costo"] = ventas["costo"].fillna(ventas["costo_total"])

    # pedidos equivalentes (insumos): cada pedido B2C despachado desde bodega vale 1, repartido entre sus líneas
    b2c_bod = ventas.tipo_movimiento.eq("Venta") & ventas.neg.isin(["mkp", "web", "fid"]) & ~ventas.ff
    lineas = ventas[b2c_bod].groupby("pedido")["sku"].transform("size")
    ventas["pedido_eq"] = 0.0
    ventas.loc[b2c_bod, "pedido_eq"] = 1.0 / lineas

    # explotar packs a componentes (proporcional al PVP de cada componente)
    pk = packs.copy()
    pk["n"] = pk.groupby(["pack", "comp"])["comp"].transform("size")
    pk = pk.drop_duplicates(["pack", "comp"])
    # kits de Odoo (mrp.bom tipo kit) que no están en la hoja Packs de la Pricing: se explotan igual
    pvp_comp = pd.to_numeric(pr.set_index("sku")["PVP"], errors="coerce")
    ko = kits[~kits["pack"].isin(set(pk["pack"]))].groupby(["pack", "comp"], as_index=False)["qty"].sum()
    ko = ko.rename(columns={"qty": "n"}).assign(pvp=lambda d: d["comp"].map(pvp_comp).fillna(0))
    pk = pd.concat([pk, ko[["pack", "comp", "pvp", "n"]]], ignore_index=True)
    pack_sin_receta = sorted(set(ventas.loc[ventas["pack"].astype(str).str.strip().isin(["Si", "Sí"]), "sku"]) - set(pk["pack"]))
    pk["peso"] = (pk["pvp"] * pk["n"]).where(lambda s: s > 0, pk["n"])
    pk["share"] = pk["peso"] / pk.groupby("pack")["peso"].transform("sum")
    es_pack = ventas["sku"].isin(pk["pack"])
    base = ventas[~es_pack]
    ex = ventas[es_pack].merge(pk[["pack", "comp", "n", "share"]].rename(columns={"pack": "_pack"}),
                               left_on="sku", right_on="_pack")
    ex[["venta_neta", "costo", "pedido_eq"]] = ex[["venta_neta", "costo", "pedido_eq"]].mul(ex["share"], axis=0)
    ex["cantidad"] = ex["cantidad"] * ex["n"]
    ex["sku"] = ex["comp"]
    ventas = pd.concat([base, ex[base.columns]], ignore_index=True)

    def agregar(vx: pd.DataFrame) -> pd.DataFrame:
        vta = vx.tipo_movimiento.eq("Venta") & (vx.cantidad > 0)
        dev = vx.tipo_movimiento.eq("Devolución")
        g = vx.groupby("sku")
        by = lambda mask, col="cantidad": vx[mask].groupby("sku")[col].sum()
        return pd.DataFrame({
            "unidades": g["cantidad"].sum(),
            "venta": g["venta_neta"].sum(),
            "costo": g["costo"].sum(),
            "venta_mkp": by(vx.neg.eq("mkp"), "venta_neta"),
            "venta_web": by(vx.neg.eq("web"), "venta_neta"),
            "venta_fid": by(vx.neg.eq("fid"), "venta_neta"),
            "venta_b2b": by(vx.neg.eq("b2b"), "venta_neta"),
            "uds_b2c": by(vta & vx.neg.isin(["mkp", "web", "fid", "otro"]) & ~vx.ff),
            "uds_b2b": by(vta & vx.neg.eq("b2b") & ~vx.ff),
            "uds_ff": by(vta & vx.ff),
            "uds_web": by(vta & vx.neg.eq("web")),
            "pedidos_eq": g["pedido_eq"].sum(),
            "uds_dev": -by(dev),
        }).fillna(0)

    # alcance (selector, Andrés 1-oct): todas las ventas o solo digital + canal UnionX B2B
    s_full = agregar(ventas)
    digital = ALCANCE == "Digital + UnionX B2B"
    if digital:
        en = ventas.neg.isin(["mkp", "web", "fid", "otro"]) | ventas["canal"].astype(str).str.strip().str.lower().eq("unionx b2b")
        s = agregar(ventas[en])
    else:
        s = s_full.copy()
    # parte de las unidades de cada SKU que cae en el alcance (para repartir su inventario)
    r_alc = (s["unidades"].clip(lower=0) / s_full["unidades"].where(s_full["unidades"] > 0)).reindex(s_full.index)
    r_alc = r_alc.fillna(0).clip(0, 1) if digital else pd.Series(1.0, index=s_full.index)
    fuera_alcance = int(((s_full["venta"] > 0) & ~s_full.index.isin(s.index[s["venta"] > 0])).sum())
    info = v.sort_values("fecha_venta").groupby("sku")[["producto", "marca", "categoria_padre", "categoria_macro",
                                                         "tipo_compra", "estado_sku"]].last()
    s = s.join(info)

    # stock promedio (stock diario Odoo por product_id → código)
    st = generar_stock_roi(refresh)
    st = st[(st.fecha >= VENTANA_DESDE) & (st.fecha < VENTANA_HASTA)]
    st["sku"] = st["sku"].map(prod.set_index("id")["default_code"].str.upper())
    st = st[st["sku"].fillna("") != ""]
    st["cantidad"] = st["cantidad"].clip(lower=0)
    n_dias = (pd.Timestamp(VENTANA_HASTA) - pd.Timestamp(VENTANA_DESDE)).days
    s = s.join((st.groupby("sku")["cantidad"].sum() / n_dias).rename("stock_u"), how="outer")
    ca1 = st[st.bodega.astype(str).str.upper().str.startswith(BODEGA_PROPIA)]
    s = s.join((ca1.groupby("sku")["cantidad"].sum() / n_dias).rename("stock_ca1_u"))
    numc = ["unidades", "venta", "costo", "venta_mkp", "venta_web", "venta_fid", "venta_b2b", "uds_b2c", "uds_b2b",
            "uds_ff", "uds_web", "pedidos_eq", "uds_dev", "stock_u", "stock_ca1_u"]
    s[numc] = s[numc].fillna(0)
    factor_pools = {}
    if digital:
        # el inventario de cada SKU se reparte según la parte de sus unidades que cae en el alcance, y los pools de
        # operación se escalan a la parte de su driver que corresponde al alcance (no se cargan enteros a lo digital)
        r = s.index.to_series().map(r_alc).fillna(1.0)
        ca1_full = s["stock_ca1_u"].sum()
        s["stock_u"] *= r
        s["stock_ca1_u"] *= r
        man = lambda d: (d["uds_b2c"] + PESO_B2B * (d["uds_b2b"] + d["uds_ff"])).sum()
        rat = lambda a, b: float(a / b) if b else 1.0
        factor_pools = {P_ESP: rat(s["stock_ca1_u"].sum(), ca1_full), P_MAN: rat(man(s), man(s_full)),
                        P_INS: rat(s["pedidos_eq"].sum(), s_full["pedidos_eq"].sum()),
                        P_PV: rat(s["uds_dev"].sum(), s_full["uds_dev"].sum())}
        pools = pools.copy()
        for k_, f_ in factor_pools.items():
            if k_ in pools.index:
                pools[k_] *= f_
    nombres = prod.assign(k=prod.default_code.str.upper()).drop_duplicates("k").set_index("k")["name"]
    s["producto"] = s["producto"].fillna(s.index.to_series().map(nombres))
    s["marca"] = s["marca"].fillna(s.index.to_series().map(pr.set_index("sku")["Marca"])).fillna("Sin marca")
    s["costo_unit"] = s.index.to_series().map(cu)
    s["costo_unit"] = s["costo_unit"].fillna(s["costo"] / s["unidades"].where(lambda x: x > 0)).fillna(0)

    # universo: fuera lo que no es producto de venta (repuestos, dummies, corporativos, insumos)
    excluir = s["producto"].fillna("").str.contains(EXCLUIR_PATRON, case=False, regex=True)
    universo = (s["venta"] > 0) | (s["stock_u"] * s["costo_unit"] > 0)
    excluidos = s[excluir & universo][["producto", "marca", "venta", "stock_u"]].copy()
    s = s[universo & ~excluir].copy()

    # % comisión / envío / marketing de la Maestra Pricing (marketplace); fuera de Pricing → mediana categoría
    com, log, mkt = "Comision % (TY) Neto", "Logistica % (TY) Neto", "Mkt % (TY) Neto"
    pp = pr.set_index("sku")
    med = pr.groupby("Categoria Padre")[[com, log, mkt]].median()
    for k, c in [("com_pct", com), ("log_pct", log), ("mkt_pct", mkt)]:
        s[k] = s.index.to_series().map(pp[c])
        s[k] = s[k].fillna(s["categoria_padre"].map(med[c])).fillna(pr[c].median())
    s["pct_fuente"] = s.index.to_series().map(pp["pct_fuente"]).fillna("Mediana categoría (sin SKU en Pricing)")
    s["cat_comercial"] = s.index.to_series().map(pp["Categoria Comercial"]).fillna("Sin categoría")

    # medidas: oficiales → Loginsa → volumen Odoo → mediana de la categoría
    m3, m3f = medidas()
    m3o = prod.assign(k=prod.default_code.str.upper()).query("volume > 0").groupby("k")["volume"].median()
    idx = s.index.to_series()
    s["m3_unit"] = idx.map(m3).astype(float)
    s["m3_fuente"] = idx.map(m3f)
    falta = s["m3_unit"].isna()
    s.loc[falta, "m3_unit"] = idx[falta].map(m3o)
    s.loc[falta & s["m3_unit"].notna(), "m3_fuente"] = "Volumen Odoo (sin validar)"
    falta = s["m3_unit"].isna()
    s.loc[falta, "m3_unit"] = s["categoria_padre"].map(s.groupby("categoria_padre")["m3_unit"].median())
    s["m3_unit"] = s["m3_unit"].fillna(s["m3_unit"].median())
    s.loc[falta, "m3_fuente"] = "FALTA — mediana de la categoría"

    # unidades por caja master: último packing list de Steven → Copia de Productos (2024) → promedio (supuesto)
    fmt = pd.read_parquet(FORMATO_SKU) if FORMATO_SKU.exists() else pd.DataFrame(columns=["uds_caja"])
    cp = copia_productos()
    s["uds_caja"] = idx.map(fmt["uds_caja"]).astype(float)
    s["uds_caja_fuente"] = np.where(s["uds_caja"] > 0, "Packing list", None)
    if not cp.empty:
        f24 = s["uds_caja"].isna() & idx.map(cp["uds_caja"]).notna()
        s.loc[f24, "uds_caja"] = idx[f24].map(cp["uds_caja"])
        s.loc[f24, "uds_caja_fuente"] = "Copia de Productos (2024)"
    s.loc[~(s["uds_caja"] > 0), "uds_caja"] = np.nan
    s["uds_caja_fuente"] = s["uds_caja_fuente"].fillna("FALTA — promedio")

    # condiciones de compra: Maestra Productos → Maestra Pricing (FCST) → supuestos
    cond = aud.dropna(subset=["sku"]).drop_duplicates("sku").set_index("sku")
    s = s.join(cond[["costo_usd_maestra", "usd_ultima_pi", "estado_costo", "costo_usd_usado", "tipo_pago",
                     "lt_produccion", "moq", "puerto"]])
    fb = mae_pr.reindex(s.index)
    vacio = lambda c: s[c].fillna("").astype(str).str.strip().isin(["", "nan", "None"])
    s.loc[vacio("tipo_pago"), "tipo_pago"] = fb.loc[vacio("tipo_pago"), "Tipo Pago (FCST)"]
    s["lt_produccion"] = s["lt_produccion"].fillna(pd.to_numeric(fb["Lead Time (FCST)"], errors="coerce"))
    s["moq"] = s["moq"].fillna(pd.to_numeric(fb["MOQ (FCST)"], errors="coerce"))
    s.loc[vacio("puerto"), "puerto"] = fb.loc[vacio("puerto"), "Puerto Origen (FCST)"]
    s["usd_ultima_pi"] = s["usd_ultima_pi"].fillna(idx.map(pi.groupby("sku")["usd"].last()))
    s["costo_usd_usado"] = s["costo_usd_usado"].fillna(s["usd_ultima_pi"])
    tc = s["tipo_compra"].astype(str)
    importado = s["usd_ultima_pi"].notna() | s["costo_usd_maestra"].notna() | tc.eq("Importación")
    s["modelo_compra"] = np.select([tc.eq("Consignación") & ~importado, importado], ["Consignación", "Importación"],
                                   "Nacional")
    tp = s["tipo_pago"].fillna("").astype(str)
    mm = tp.str.extract(r"(\d+)\s*/\s*(\d+)")
    s["anticipo_pct"] = pd.to_numeric(mm[0], errors="coerce") / 100
    s["pago_fuente"] = np.where(s["anticipo_pct"].notna(), "Maestra", "Supuesto 30/70")
    s["anticipo_pct"] = s["anticipo_pct"].fillna(0.30)
    # saldo al proveedor (Andrés 29-sep): "xx/yy Credit" = contra BL en Chile (al llegar); el resto = al embarcar en origen
    s["saldo_en"] = np.where(tp.str.contains("credit", case=False), "Chile (BL)", "Origen")
    s["lt_fuente"] = np.where(s["lt_produccion"].notna(), "Maestra", f"Supuesto {LT_PRODUCCION_DEFAULT} días")
    s["lt_produccion"] = s["lt_produccion"].fillna(LT_PRODUCCION_DEFAULT)
    s["puerto"] = s["puerto"].fillna("").astype(str).str.strip().str.title().replace({"Nan": "", "None": ""})

    imp = s["modelo_compra"].eq("Importación")
    marcas_ = {
        "medidas": ~s["m3_fuente"].isin(["Medidas oficiales", "Maestro Loginsa"]),
        "uds por caja": s["uds_caja_fuente"].str.startswith("FALTA") & ((s["uds_b2b"] + s["uds_ff"]) > 0),
        "% Pricing": ~s["pct_fuente"].eq("Maestra Pricing (SKU)"),
        "tipo de pago": imp & s["pago_fuente"].ne("Maestra"),
        "lead time": imp & s["lt_fuente"].ne("Maestra"),
        "puerto": imp & s["puerto"].eq(""),
        "costo USD": imp & s["costo_usd_usado"].isna(),
    }
    s["supuestos"] = pd.DataFrame(marcas_).apply(lambda r: ", ".join(k for k, v in r.items() if v), axis=1)
    pvp = pr.set_index("sku")
    s["pvp_mkp"] = pd.to_numeric(idx.map(pvp["PVP"]), errors="coerce")
    s["pvp_web"] = pd.to_numeric(idx.map(pvp["PVP P.WEB"]), errors="coerce")
    s["precio_real"] = (s["venta"] / s["unidades"].where(s["unidades"] > 0)).fillna(0)

    # segmento (Activo / Out / Consignación / Solo stock), producto base, categorías y alarma de stock sin venta
    idx = s.index.to_series()
    est = s["estado_sku"].fillna("").astype(str).str.strip().str.lower()
    s["estado_sku"] = np.where(est.isin(["in", "out"]), est.str.capitalize(), "Sin dato")
    s["segmento"] = np.select([s["venta"] <= 0, s["modelo_compra"].eq("Consignación"), est.eq("out")],
                              ["Solo stock", "Consignación", "Out"], "Activo")
    s["plantilla"] = idx.map(tmpl["plantilla"]).fillna(s["producto"]).fillna(idx)
    orden = s.sort_values("venta", ascending=False)
    s["prim_var"] = (~orden.duplicated(["segmento", "plantilla"])).reindex(s.index).astype(int)
    sin_cat = lambda c: c.fillna("").astype(str).str.strip().replace({"": np.nan, "0": np.nan, "nan": np.nan})
    s["categoria_padre"] = sin_cat(s["categoria_padre"]).fillna(idx.map(pp["Categoria Padre"])).fillna("Sin categoría")
    s["categoria_macro"] = sin_cat(s["categoria_macro"]).fillna("Sin categoría")
    cierre = st[st["fecha"] == st["fecha"].max()]
    s["stock_cierre_u"] = idx.map(cierre.groupby("sku")["cantidad"].sum()).fillna(0)
    s["stock_cierre_ca1_u"] = idx.map(cierre[cierre.bodega.astype(str).str.upper().str.startswith(BODEGA_PROPIA)]
                                      .groupby("sku")["cantidad"].sum()).fillna(0)
    vh = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet", columns=["sku", "fecha_venta", "tipo_movimiento"])
    vh = vh[vh.tipo_movimiento.eq("Venta") & (vh.fecha_venta < VENTANA_HASTA)]
    s["ult_venta"] = idx.map(vh.assign(sku=vh.sku.astype(str).str.strip().str.upper()).groupby("sku")["fecha_venta"].max())
    s["ult_venta"] = pd.to_datetime(s["ult_venta"], errors="coerce")
    es_kit = idx.isin(set(pk["pack"]))
    s["alarma"] = np.where(s["segmento"].ne("Solo stock"), "",
                           np.where(es_kit, "Kit/pack con stock propio en Odoo (no debería tener)",
                                    np.where(s["ult_venta"].isna(), "Nunca vendido",
                                             "Sin venta desde " + s["ult_venta"].dt.strftime("%d-%m-%Y").fillna(""))))
    dc = dias_cobro()
    tc_ = tasas_canal(v)
    s = metricas(s, pools, dc["dias"], tc_, ESCENARIO_DEF)
    meta = dict(stock_hasta=str(st["fecha"].max().date()), pools=pools, dias_cobro=dc, tasas=tc_,
                pack_sin_receta=pack_sin_receta, alcance=ALCANCE, fuera_alcance=fuera_alcance,
                factor_pools=factor_pools, ventana=(VENTANA_DESDE, VENTANA_HASTA))
    return s, aud, pools_det, pools, excluidos, meta


def uds_caja_promedio(s: pd.DataFrame) -> float:
    """Unidades por caja promedio, ponderado por las unidades B2B + fulfillment de los SKU con dato."""
    w = (s["uds_b2b"] + s["uds_ff"]).where(s["uds_caja"] > 0, 0)
    return float((s["uds_caja"].fillna(0) * w).sum() / w.sum()) if w.sum() else 1.0


def metricas(s: pd.DataFrame, pools: pd.Series, dias: float, tc_: dict, escenario: str = "Mix real") -> pd.DataFrame:
    """Réplica en Python de las fórmulas del Excel (para verificar y para el resumen)."""
    s = s.copy()
    p = lambda k: float(pools.get(k, 0.0))
    ucp = uds_caja_promedio(s)
    w_caja = PESO_B2B * ucp
    s["uds_caja_ef"] = s["uds_caja"].where(s["uds_caja"] > 0, ucp)
    s["d_m3ca1"] = s["stock_ca1_u"] * s["m3_unit"]
    s["d_manip"] = s["uds_b2c"] * PESO_B2C + (s["uds_b2b"] + s["uds_ff"]) / s["uds_caja_ef"] * w_caja
    share = lambda col: s[col] / s[col].sum() if s[col].sum() else 0
    s["md"] = s["venta"] - s["costo"]
    # mix real: marketplace con % Pricing del SKU; web / fidelización / B2B con la tasa real de ese negocio
    s["comision"] = (s["venta_mkp"] * s["com_pct"] + s["venta_web"] * tc_["web_com"] + s["venta_fid"] * tc_["fid_com"]
                     + s["venta_b2b"] * tc_["b2b_com"])
    s["logistica"] = (s["venta_mkp"] * s["log_pct"] + s["venta_web"] * tc_["web_env"] + s["venta_fid"] * tc_["fid_env"]
                      + s["venta_b2b"] * tc_["b2b_env"])
    s["marketing"] = (s["venta_mkp"] * s["mkt_pct"] + s["venta_web"] * MKT_WEB + s["venta_fid"] * MKT_FID
                      + s["venta_b2b"] * MKT_B2B)
    s["almacenaje"] = p(P_ESP) * share("d_m3ca1")
    s["manipulacion"] = p(P_MAN) * share("d_manip")
    s["insumos"] = p(P_INS) * share("pedidos_eq")
    s["postventa"] = p(P_PV) * share("uds_dev")
    s["contribucion"] = s["md"] - s[["comision", "logistica", "marketing", "almacenaje", "manipulacion",
                                     "insumos", "postventa"]].sum(axis=1)
    vpos = s["venta"].where(s["venta"] > 0)
    s["md_pct"] = s["md"] / vpos
    s["contrib_pct"] = s["contribucion"] / vpos
    imp = s["modelo_compra"].eq("Importación")
    costo_d = s["costo"].clip(lower=0) / 365
    fob = np.where(s["costo_usd_usado"].fillna(0) > 0,
                   np.minimum(s["unidades"].clip(lower=0) * s["costo_usd_usado"].fillna(0) * TC_USD / 365, costo_d),
                   costo_d * FOB_SHARE_DEFAULT)
    fob_d = pd.Series(np.where(imp, fob, 0), index=s.index)
    s["transito_dias"] = np.where(imp, s["puerto"].map(TRANSITO_DIAS).fillna(TRANSITO_DEFAULT), 0)
    s["k_anticipo"] = np.where(imp, s["anticipo_pct"] * fob_d * s["lt_produccion"], 0)
    pagado_transito = np.where(s["saldo_en"].eq("Origen"), 1.0, s["anticipo_pct"])
    s["k_transito"] = np.where(imp, pagado_transito * fob_d * s["transito_dias"] + fob_d * ADUANA_DIAS, 0)
    s["k_bodega"] = np.where(s["modelo_compra"].eq("Consignación"), 0, s["stock_u"] * s["costo_unit"])
    s["credito"] = np.where(imp, (costo_d - fob_d).clip(lower=0) * max(0, CREDITO_FLETE_INTERNACION_DIAS - ADUANA_DIAS),
                            np.where(s["modelo_compra"].eq("Nacional"), costo_d * CREDITO_NACIONAL_DIAS, 0))
    s["k_cxc"] = s["venta"].clip(lower=0) / 365 * dias
    s["capital"] = (s["k_anticipo"] + s["k_transito"] + s["k_bodega"] + s["k_cxc"] - s["credito"]).clip(lower=0)
    s["costo_capital"] = s["capital"] * TASA_CAPITAL
    s["eva"] = s["contribucion"] - s["costo_capital"]
    kb = s["k_bodega"].where(s["k_bodega"] > 0)
    s["gmroi"] = s["md"] / kb
    s["roi_capital"] = s["contribucion"] / s["capital"].where(s["capital"] > 0)
    s["rotacion"] = s["costo"] / kb
    s["dias_caja"] = s["capital"] / costo_d.where(costo_d > 0)
    s["cobertura_moq"] = s["moq"] / (s["unidades"] / 12).where(s["unidades"] > 0)
    # escenarios: el mismo volumen vendido 100% por un canal (costo de operación a tasa por unidad / por pedido)
    uds = s["unidades"].clip(lower=0)
    tasa_man_u = p(P_MAN) / s["d_manip"].sum() * PESO_B2C if s["d_manip"].sum() else 0
    tasa_ins_ped = p(P_INS) / s["pedidos_eq"].sum() if s["pedidos_eq"].sum() else 0
    base_cap = s["k_anticipo"] + s["k_transito"] + s["k_bodega"] - s["credito"]
    lista = {"m": s["pvp_mkp"], "w": s["pvp_web"].where(s["pvp_web"] > 0, s["pvp_mkp"]), "f": s["pvp_mkp"]}
    fact = {"m": FACTOR_PRECIO["MKP"], "w": FACTOR_PRECIO["WEB"], "f": FACTOR_PRECIO["FID"]}
    tasa_c = {"m": s["com_pct"] + s["log_pct"] + s["mkt_pct"],
              "w": tc_["web_com"] + tc_["web_env"] + MKT_WEB,
              "f": tc_["fid_com"] + tc_["fid_env"] + MKT_FID}
    upp = {"m": tc_["upp"]["mkp"], "w": tc_["upp"]["web"], "f": tc_["upp"]["fid"]}
    for c in "mwf":
        s[f"precio_{c}"] = np.where(lista[c] > 0, lista[c] / (1 + IVA) * fact[c], s["precio_real"])
        s[f"venta_{c}_esc"] = uds * s[f"precio_{c}"]
        s[f"canal_{c}"] = s[f"venta_{c}_esc"] * tasa_c[c]
        s[f"oper_{c}"] = s["almacenaje"] + s["postventa"] + uds * tasa_man_u + uds / upp[c] * tasa_ins_ped
        s[f"contrib_{c}"] = s[f"venta_{c}_esc"] - s["costo"] - s[f"canal_{c}"] - s[f"oper_{c}"]
        s[f"capital_{c}"] = (base_cap + s[f"venta_{c}_esc"] / 365 * dias).clip(lower=0)
        s[f"eva_{c}"] = s[f"contrib_{c}"] - s[f"capital_{c}"] * TASA_CAPITAL
        s[f"roi_{c}"] = s[f"contrib_{c}"] / s[f"capital_{c}"].where(s[f"capital_{c}"] > 0)
        s[f"cpct_{c}"] = s[f"contrib_{c}"] / s[f"venta_{c}_esc"].where(s[f"venta_{c}_esc"] > 0)
    s["mejor_canal"] = np.where(uds <= 0, "", np.where(s["eva_m"] >= np.maximum(s["eva_w"], s["eva_f"]), "Marketplace",
                                                       np.where(s["eva_w"] >= s["eva_f"], "Páginas web", "Fidelización")))
    sel = {"Mix real": ("venta", "contribucion", "capital", "eva"), "Solo marketplace": ("venta_m_esc", "contrib_m", "capital_m", "eva_m"),
           "Solo páginas web": ("venta_w_esc", "contrib_w", "capital_w", "eva_w"),
           "Solo fidelización": ("venta_f_esc", "contrib_f", "capital_f", "eva_f")}
    if escenario in sel:
        for dst, src in zip(("venta_sel", "contrib_sel", "capital_sel", "eva_sel"), sel[escenario]):
            s[dst] = s[src]
    else:
        mx = MIX_DEFAULT
        for dst, k in [("venta_sel", "venta_{}_esc"), ("contrib_sel", "contrib_{}"), ("capital_sel", "capital_{}"), ("eva_sel", "eva_{}")]:
            s[dst] = mx["MKP"] * s[k.format("m")] + mx["WEB"] * s[k.format("w")] + mx["FID"] * s[k.format("f")]
    s["cpct_sel"] = s["contrib_sel"] / s["venta_sel"].where(s["venta_sel"] > 0)
    s["roi_sel"] = s["contrib_sel"] / s["capital_sel"].where(s["capital_sel"] > 0)
    rot, ctr = s["rotacion"].fillna(0), s["cpct_sel"].fillna(0)
    # sensibilidad estándar sobre el mix real: Δ EVA de cada palanca movida sola (fórmulas cerradas)
    V, CO, T_ = s["venta"], s["costo"], TASA_CAPITAL
    r_real = ((s["comision"] + s["logistica"] + s["marketing"]) / V.where(V > 0)).fillna(0)
    r_mkp = s["com_pct"] + s["log_pct"] + s["mkt_pct"]
    r_web = tc_["web_com"] + tc_["web_env"] + MKT_WEB
    sh_mkp = (s["venta_mkp"] / V.where(V > 0)).fillna(0).clip(lower=0)
    orig = s["saldo_en"].eq("Origen")
    fobd = pd.Series(fob_d, index=s.index)
    ant_ = s["anticipo_pct"].where(imp, 0)
    # precio con elasticidad: u = Δ unidades; g = Δ venta; costos variables siguen a u, el inventario a INV_ACOMP·u
    u_ = ELASTICIDAD * SHOCK["precio"]
    g_ = (1 + SHOCK["precio"]) * (1 + u_) - 1
    var_ = CO + s["manipulacion"] + s["insumos"] + s["postventa"]
    s["d_precio"] = (V * (1 - r_real) * g_ - u_ * var_ - INV_ACOMP * u_ * s["almacenaje"]
                     - T_ * (s["k_cxc"] * g_ + u_ * (s["k_anticipo"] + s["k_transito"] - s["credito"])
                             + INV_ACOMP * u_ * s["k_bodega"]))
    s["d_costo"] = SHOCK["costo"] * CO + T_ * SHOCK["costo"] * (s["k_anticipo"] + s["k_transito"] + s["k_bodega"] - s["credito"])
    s["d_mix"] = V * np.minimum(sh_mkp, SHOCK["mix"]) * (r_mkp - r_web)
    dx = np.minimum(ant_, SHOCK["anticipo"])
    s["d_anticipo"] = np.where(imp, T_ * dx * fobd * (s["lt_produccion"] + np.where(orig, 0, s["transito_dias"])), 0)
    s["d_saldo"] = np.where(imp & orig, T_ * (1 - ant_) * fobd * s["transito_dias"], 0)
    s["d_prod"] = np.where(imp, T_ * ant_ * fobd * np.minimum(SHOCK["prod"], s["lt_produccion"]), 0)
    s["d_tran"] = np.where(imp, T_ * np.where(orig, 1, ant_) * fobd * np.minimum(SHOCK["tran"], s["transito_dias"]), 0)
    s["d_inv"] = SHOCK["inv"] * s["almacenaje"] + T_ * SHOCK["inv"] * s["k_bodega"]
    s["d_m3"] = SHOCK["m3"] * s["almacenaje"]
    # unidades: todo escala salvo el inventario (y su almacenaje), que crece solo INV_ACOMP → sube la rotación
    s["d_uds"] = SHOCK["uds"] * s["eva"] + SHOCK["uds"] * (1 - INV_ACOMP) * (s["almacenaje"] + T_ * s["k_bodega"])
    dcols = ["d_precio", "d_costo", "d_mix", "d_anticipo", "d_saldo", "d_prod", "d_tran", "d_inv", "d_m3", "d_uds"]
    s["palanca_top"] = np.where(V > 0, np.array(PALANCAS)[s[dcols].values.argmax(axis=1)], "")
    s["clasificacion"] = np.select(
        [s["venta_sel"] <= 0, s["contrib_sel"] < 0, s["eva_sel"] < 0,
         (rot >= UMBRAL_ROTACION) & (ctr >= UMBRAL_CONTRIB), rot >= UMBRAL_ROTACION, ctr >= UMBRAL_CONTRIB],
        ["Sin venta", "Destruye valor", "No paga su capital", "Estrella", "Volumen", "Nicho"], "Paga justo")
    return s


# ── Excel con fórmulas ──────────────────────────────────────────────────────
# (clave, encabezado, tipo, formato, fórmula). tipo: "in" = dato de entrada, "f" = fórmula.
# En las fórmulas, {clave} se reemplaza por la columna y {r} por la fila.
P, M, X, D1, D2 = '#,##0', '0.0%', '0.00"x"', '#,##0.0', '0.00'
def _escenario_cols():
    """Columnas de los tres escenarios (mismo volumen vendido 100% por un canal)."""
    out = []
    defs = {
        "m": ("Marketplace", '=IF(N({pvp_mkp}{r})>0,{pvp_mkp}{r}/(1+IVA)*FACT_MKP,{precio_real}{r})',
              "({com_pct}{r}+{log_pct}{r}+{mkt_pct}{r})", "UPP_MKP"),
        "w": ("Páginas web", '=IF(N({pvp_web}{r})>0,{pvp_web}{r},IF(N({pvp_mkp}{r})>0,{pvp_mkp}{r},{precio_real}{r}*(1+IVA)))'
                             '/(1+IVA)*FACT_WEB', "(WEB_COM+WEB_ENV+WEB_MKT)", "UPP_WEB"),
        "f": ("Fidelización", '=IF(N({pvp_mkp}{r})>0,{pvp_mkp}{r}/(1+IVA)*FACT_FID,{precio_real}{r})',
              "(FID_COM+FID_ENV+FID_MKT)", "UPP_FID"),
    }
    for c, (nom, precio, tasa, upp) in defs.items():
        out += [
            (f"precio_{c}", f"{nom}: precio neto", "f", P, precio),
            (f"venta_{c}_esc", f"{nom}: venta", "f", P, f"=MAX({{unidades}}{{r}},0)*{{precio_{c}}}{{r}}"),
            (f"canal_{c}", f"{nom}: comisión + envío + marketing", "f", P, f"={{venta_{c}_esc}}{{r}}*{tasa}"),
            (f"oper_{c}", f"{nom}: costo de operación", "f", P,
             f"={{almacenaje}}{{r}}+{{postventa}}{{r}}+MAX({{unidades}}{{r}},0)*TASA_MANIP_U+MAX({{unidades}}{{r}},0)/{upp}*TASA_INS_PED"),
            (f"contrib_{c}", f"{nom}: contribución", "f", P,
             f"={{venta_{c}_esc}}{{r}}-{{costo}}{{r}}-{{canal_{c}}}{{r}}-{{oper_{c}}}{{r}}"),
            (f"cpct_{c}", f"{nom}: contribución %", "f", M,
             f'=IF({{venta_{c}_esc}}{{r}}>0,{{contrib_{c}}}{{r}}/{{venta_{c}_esc}}{{r}},"")'),
            (f"capital_{c}", f"{nom}: capital", "f", P,
             f"=MAX(0,{{k_anticipo}}{{r}}+{{k_transito}}{{r}}+{{k_bodega}}{{r}}+{{venta_{c}_esc}}{{r}}/365*DIAS_COBRO-{{credito}}{{r}})"),
            (f"roi_{c}", f"{nom}: ROI s/ capital", "f", X,
             f'=IF({{capital_{c}}}{{r}}>0,{{contrib_{c}}}{{r}}/{{capital_{c}}}{{r}},"")'),
            (f"eva_{c}", f"{nom}: EVA", "f", P, f"={{contrib_{c}}}{{r}}-{{capital_{c}}}{{r}}*TASA"),
        ]
    return out


def _sel(real, m, w, f):
    return (f'=IF(ESCENARIO="Mix real",{{{real}}}{{r}},IF(ESCENARIO="Solo marketplace",{{{m}}}{{r}},'
            f'IF(ESCENARIO="Solo páginas web",{{{w}}}{{r}},IF(ESCENARIO="Solo fidelización",{{{f}}}{{r}},'
            f'MIX_MKP*{{{m}}}{{r}}+MIX_WEB*{{{w}}}{{r}}+MIX_FID*{{{f}}}{{r}}))))')


COLUMNAS = [
    ("sku", "SKU", "in", None, None),
    ("producto", "Producto", "in", None, None),
    ("marca", "Marca", "in", None, None),
    ("cat_comercial", "Categoría comercial", "in", None, None),
    ("segmento", "Segmento", "in", None, None),
    # vista principal = escenario elegido en Supuestos
    ("clasificacion", "Clasificación financiera (escenario elegido)", "f", None,
     '=IF({venta_sel}{r}<=0,"Sin venta",IF({contrib_sel}{r}<0,"Destruye valor",IF({eva_sel}{r}<0,"No paga su capital",'
     'IF(AND(N({rotacion}{r})>=ROT_MIN,N({cpct_sel}{r})>=CTR_MIN),"Estrella",IF(N({rotacion}{r})>=ROT_MIN,'
     '"Volumen",IF(N({cpct_sel}{r})>=CTR_MIN,"Nicho","Paga justo"))))))'),
    ("mejor_canal", "Mejor canal (mayor EVA)", "f", None,
     '=IF({unidades}{r}<=0,"",IF({eva_m}{r}>=MAX({eva_w}{r},{eva_f}{r}),"Marketplace",'
     'IF({eva_w}{r}>={eva_f}{r},"Páginas web","Fidelización")))'),
    ("venta_sel", "Venta (escenario elegido)", "f", P, _sel("venta", "venta_m_esc", "venta_w_esc", "venta_f_esc")),
    ("contrib_sel", "Contribución (escenario elegido)", "f", P, _sel("contribucion", "contrib_m", "contrib_w", "contrib_f")),
    ("cpct_sel", "Contribución %", "f", M, '=IF({venta_sel}{r}>0,{contrib_sel}{r}/{venta_sel}{r},"")'),
    ("capital_sel", "Capital empleado", "f", P, _sel("capital", "capital_m", "capital_w", "capital_f")),
    ("roi_sel", "ROI s/ capital", "f", X, '=IF({capital_sel}{r}>0,{contrib_sel}{r}/{capital_sel}{r},"")'),
    ("eva_sel", "Valor económico (EVA)", "f", P, _sel("eva", "eva_m", "eva_w", "eva_f")),
    ("gmroi", "GMROI", "f", X, '=IF({k_bodega}{r}>0,{md}{r}/{k_bodega}{r},"")'),
    ("rotacion", "Rotación (veces/año)", "f", X, '=IF({k_bodega}{r}>0,{costo}{r}/{k_bodega}{r},"")'),
    ("dias_caja", "Días de caja (mix real)", "f", P, '=IF({costo_d}{r}>0,{capital}{r}/{costo_d}{r},"")'),
    ("cobertura_moq", "MOQ en meses de venta", "f", D1,
     '=IF(AND(N({moq}{r})>0,{unidades}{r}>0),{moq}{r}/({unidades}{r}/12),"")'),
    ("palanca_top", "Palanca que más mueve (sensibilidad estándar)", "f", None,
     '=IF({venta}{r}<=0,"",SUBSTITUTE(INDEX($' + "{d_precio}" + '$1:$' + "{d_uds}" + '$1,MATCH(MAX({d_precio}{r}:{d_uds}{r}),'
     '{d_precio}{r}:{d_uds}{r},0)),"Δ EVA · ",""))'),
    ("d_precio", "Δ EVA · Precio", "f", P,
     "={venta}{r}*(1-IF({venta}{r}>0,({comision}{r}+{logistica}{r}+{marketing}{r})/{venta}{r},0))"
     "*((1+SH_PRECIO)*(1+ELASTICIDAD*SH_PRECIO)-1)"
     "-ELASTICIDAD*SH_PRECIO*({costo}{r}+{manipulacion}{r}+{insumos}{r}+{postventa}{r})"
     "-INV_ACOMP*ELASTICIDAD*SH_PRECIO*{almacenaje}{r}"
     "-TASA*({k_cxc}{r}*((1+SH_PRECIO)*(1+ELASTICIDAD*SH_PRECIO)-1)"
     "+ELASTICIDAD*SH_PRECIO*({k_anticipo}{r}+{k_transito}{r}-{credito}{r})"
     "+INV_ACOMP*ELASTICIDAD*SH_PRECIO*{k_bodega}{r})"),
    ("d_costo", "Δ EVA · Costo compra", "f", P,
     "=SH_COSTO*{costo}{r}+TASA*SH_COSTO*({k_anticipo}{r}+{k_transito}{r}+{k_bodega}{r}-{credito}{r})"),
    ("d_mix", "Δ EVA · Mix canal", "f", P,
     "={venta}{r}*MIN(IF({venta}{r}>0,MAX({venta_mkp}{r},0)/{venta}{r},0),SH_MIX)*"
     "({com_pct}{r}+{log_pct}{r}+{mkt_pct}{r}-(WEB_COM+WEB_ENV+WEB_MKT))"),
    ("d_anticipo", "Δ EVA · Anticipo", "f", P,
     '=IF({modelo_compra}{r}="Importación",TASA*MIN({anticipo_pct}{r},SH_ANT)*{fob_d}{r}*({lt_prod}{r}'
     '+IF({saldo_en}{r}="Origen",0,{transito_dias}{r})),0)'),
    ("d_saldo", "Δ EVA · Saldo en Chile", "f", P,
     '=IF(AND({modelo_compra}{r}="Importación",{saldo_en}{r}="Origen"),TASA*(1-{anticipo_pct}{r})*{fob_d}{r}*{transito_dias}{r},0)'),
    ("d_prod", "Δ EVA · Producción", "f", P,
     '=IF({modelo_compra}{r}="Importación",TASA*{anticipo_pct}{r}*{fob_d}{r}*MIN(SH_PROD,{lt_prod}{r}),0)'),
    ("d_tran", "Δ EVA · Tránsito", "f", P,
     '=IF({modelo_compra}{r}="Importación",TASA*IF({saldo_en}{r}="Origen",1,{anticipo_pct}{r})*{fob_d}{r}'
     '*MIN(SH_TRAN,{transito_dias}{r}),0)'),
    ("d_inv", "Δ EVA · Rotación", "f", P, "=SH_INV*{almacenaje}{r}+TASA*SH_INV*{k_bodega}{r}"),
    ("d_m3", "Δ EVA · m³", "f", P, "=SH_M3*{almacenaje}{r}"),
    ("d_uds", "Δ EVA · Unidades", "f", P,
     "=SH_UDS*{eva}{r}+SH_UDS*(1-INV_ACOMP)*({almacenaje}{r}+TASA*{k_bodega}{r})"),
    # escenario MIX REAL (cascada)
    ("venta", "Mix real: venta neta", "in", P, None),
    ("costo", "Costo de venta (Odoo)", "in", P, None),
    ("md", "Margen directo", "f", P, "={venta}{r}-{costo}{r}"),
    ("md_pct", "Margen directo %", "f", M, '=IF({venta}{r}>0,{md}{r}/{venta}{r},"")'),
    ("comision", "Mix real: comisión venta", "f", P,
     "={venta_mkp}{r}*{com_pct}{r}+{venta_web}{r}*WEB_COM+{venta_fid}{r}*FID_COM_R+{venta_b2b}{r}*B2B_COM"),
    ("logistica", "Mix real: envío", "f", P,
     "={venta_mkp}{r}*{log_pct}{r}+{venta_web}{r}*WEB_ENV+{venta_fid}{r}*FID_ENV_R+{venta_b2b}{r}*B2B_ENV"),
    ("marketing", "Mix real: marketing", "f", P,
     "={venta_mkp}{r}*{mkt_pct}{r}+{venta_web}{r}*WEB_MKT+{venta_fid}{r}*FID_MKT+{venta_b2b}{r}*B2B_MKT"),
    ("almacenaje", "Almacenaje", "f", P, "=IF(TOT_M3CA1>0,POOL_ESP*{d_m3ca1}{r}/TOT_M3CA1,0)"),
    ("manipulacion", "Manipulación", "f", P, "=IF(TOT_MANIP>0,POOL_MAN*{d_manip}{r}/TOT_MANIP,0)"),
    ("insumos", "Insumos", "f", P, "=IF(TOT_PED>0,POOL_INS*{pedidos_eq}{r}/TOT_PED,0)"),
    ("postventa", "Postventa / log. inversa", "f", P, "=IF(TOT_DEV>0,POOL_PV*{uds_dev}{r}/TOT_DEV,0)"),
    ("contribucion", "Mix real: contribución", "f", P,
     "={md}{r}-{comision}{r}-{logistica}{r}-{marketing}{r}-{almacenaje}{r}-{manipulacion}{r}-{insumos}{r}-{postventa}{r}"),
    ("contrib_pct", "Mix real: contribución %", "f", M, '=IF({venta}{r}>0,{contribucion}{r}/{venta}{r},"")'),
    ("capital", "Mix real: capital", "f", P,
     "=MAX(0,{k_anticipo}{r}+{k_transito}{r}+{k_bodega}{r}+{k_cxc}{r}-{credito}{r})"),
    ("roi_capital", "Mix real: ROI s/ capital", "f", X, '=IF({capital}{r}>0,{contribucion}{r}/{capital}{r},"")'),
    ("eva", "Mix real: EVA", "f", P, "={contribucion}{r}-{costo_capital}{r}"),
    # escenarios 100% por canal
    *_escenario_cols(),
    # capital
    ("costo_d", "Costo diario", "f", P, "=MAX({costo}{r},0)/365"),
    ("fob_d", "FOB diario", "f", P,
     '=IF({modelo_compra}{r}="Importación",IF(N({costo_usd}{r})>0,MIN(MAX({unidades}{r},0)*{costo_usd}{r}*TC/365,'
     '{costo_d}{r}),{costo_d}{r}*FOB_DEF),0)'),
    ("transito_dias", "Días tránsito", "f", P,
     '=IF({modelo_compra}{r}="Importación",IFERROR(VLOOKUP({puerto}{r},PUERTOS,2,FALSE),TR_DEF),0)'),
    ("k_anticipo", "Capital: anticipo en producción", "f", P,
     '=IF({modelo_compra}{r}="Importación",{anticipo_pct}{r}*{fob_d}{r}*{lt_prod}{r},0)'),
    ("k_transito", "Capital: tránsito y aduana", "f", P,
     '=IF({modelo_compra}{r}="Importación",IF({saldo_en}{r}="Origen",1,{anticipo_pct}{r})*{fob_d}{r}*{transito_dias}{r}'
     '+{fob_d}{r}*ADUANA,0)'),
    ("k_bodega", "Capital: inventario promedio", "f", P,
     '=IF({modelo_compra}{r}="Consignación",0,{stock_u}{r}*{costo_unit}{r})'),
    ("k_cxc", "Capital: cuentas por cobrar (mix real)", "f", P, "=MAX({venta}{r},0)/365*DIAS_COBRO"),
    ("credito", "Crédito (flete/internación · proveedor)", "f", P,
     '=IF({modelo_compra}{r}="Importación",MAX({costo_d}{r}-{fob_d}{r},0)*MAX(0,CRED_FLETE-ADUANA),'
     'IF({modelo_compra}{r}="Nacional",{costo_d}{r}*CRED_NAC,0))'),
    ("costo_capital", "Costo del capital (mix real)", "f", P, "={capital}{r}*TASA"),
    # drivers
    ("d_m3ca1", "Driver: m³ promedio en CA1", "f", '0.000', "={stock_ca1_u}{r}*{m3_unit}{r}"),
    ("uds_caja_ef", "Uds por caja usadas", "f", D1, "=IF(N({uds_caja}{r})>0,{uds_caja}{r},UDS_CAJA_PROM)"),
    ("d_manip", "Driver: unidades ponderadas", "f", D1,
     "={uds_b2c}{r}*W_B2C+({uds_b2b}{r}+{uds_ff}{r})/{uds_caja_ef}{r}*W_CAJA"),
    # entradas
    ("categoria_padre", "Categoría", "in", None, None),
    ("categoria_macro", "Categoría macro", "in", None, None),
    ("plantilla", "Producto base (plantilla Odoo)", "in", None, None),
    ("prim_var", "1ª variante del producto (para contar productos)", "in", P, None),
    ("estado_sku", "Estado in/out (RAW)", "in", None, None),
    ("modelo_compra", "Tipo de compra", "in", None, None),
    ("tipo_pago", "Tipo de pago", "in", None, None),
    ("puerto", "Puerto", "in", None, None),
    ("supuestos", "Datos que faltan (usa supuesto)", "in", None, None),
    ("unidades", "Unidades netas", "in", P, None),
    ("venta_mkp", "Venta real marketplace", "in", P, None),
    ("venta_web", "Venta real páginas web", "in", P, None),
    ("venta_fid", "Venta real fidelización", "in", P, None),
    ("venta_b2b", "Venta real B2B", "in", P, None),
    ("precio_real", "Precio real promedio (neto)", "in", P, None),
    ("pvp_mkp", "PVP marketplace (Pricing, c/IVA)", "in", P, None),
    ("pvp_web", "PVP web (Pricing, c/IVA)", "in", P, None),
    ("com_pct", "Comisión % (Pricing)", "in", M, None),
    ("log_pct", "Logística % (Pricing)", "in", M, None),
    ("mkt_pct", "Marketing % (Pricing)", "in", M, None),
    ("pct_fuente", "Fuente % Pricing", "in", None, None),
    ("uds_b2c", "Uds B2C desde bodega", "in", P, None),
    ("uds_b2b", "Uds B2B", "in", P, None),
    ("uds_ff", "Uds fulfillment", "in", P, None),
    ("uds_caja", "Uds por caja master", "in", P, None),
    ("uds_caja_fuente", "Fuente uds por caja", "in", None, None),
    ("pedidos_eq", "Pedidos B2C (equivalentes)", "in", D1, None),
    ("uds_dev", "Uds devueltas", "in", P, None),
    ("stock_u", "Stock promedio (uds, todas las bodegas)", "in", D1, None),
    ("stock_ca1_u", "Stock promedio CA1 (uds)", "in", D1, None),
    ("m3_unit", "m³ por unidad", "in", '0.0000', None),
    ("m3_fuente", "Fuente medidas", "in", None, None),
    ("costo_unit", "Costo unitario landed", "in", P, None),
    ("costo_usd", "Costo USD (última PI)", "in", D2, None),
    ("estado_costo", "Auditoría costo USD", "in", None, None),
    ("anticipo_pct", "Anticipo %", "in", '0%', None),
    ("saldo_en", "Saldo al proveedor se paga en", "in", None, None),
    ("pago_fuente", "Fuente pago", "in", None, None),
    ("lt_prod", "Lead time producción (días)", "in", P, None),
    ("lt_fuente", "Fuente lead time", "in", None, None),
    ("moq", "MOQ", "in", P, None),
]
ENTRADA_DE = {"costo_usd": "costo_usd_usado", "lt_prod": "lt_produccion", "sku": None}


def exportar(s, aud, pools_det, pools, excluidos, conc, meta, sufijo: str = "") -> Path:
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.workbook.defined_name import DefinedName

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"ROI_Producto_UnionX_{date.today():%Y-%m-%d}{sufijo}.xlsx"
    NAVY, AMA, GRIS = "1F3864", "FFF2CC", "F2F2F2"
    H = PatternFill("solid", fgColor=NAVY)
    Y = PatternFill("solid", fgColor=AMA)
    B, W = Font(bold=True), Font(bold=True, color="FFFFFF")
    AZUL = Font(color="1F4E9E")
    fino = Border(bottom=Side(style="thin", color="D9D9D9"))
    wb = Workbook()

    def nombre(n, ref):
        dn = DefinedName(n, attr_text=ref)
        try:
            wb.defined_names[n] = dn
        except TypeError:
            wb.defined_names.append(dn)

    # ── Supuestos ──
    su = wb.active
    su.title = "Supuestos"
    su["A1"] = "Supuestos del ROI por producto — celdas amarillas se pueden editar y todo el libro se recalcula"
    su["A1"].font = Font(bold=True, size=13, color=NAVY)
    su["A2"] = (f"Ventana {VENTANA_DESDE} a {VENTANA_HASTA} (excl.) · ALCANCE: {meta.get('alcance', ALCANCE)} · "
                f"stock diario Odoo hasta {meta['stock_hasta']} · supuestos del panel 'Supuestos ROI' (Drive) · "
                "montos en CLP neto")
    fila = 4
    n_sku = len(s)
    col = {k: get_column_letter(i + 1) for i, (k, *_r) in enumerate(COLUMNAS)}
    rng = lambda k: f"'ROI por SKU'!${col[k]}$2:${col[k]}${n_sku + 1}"
    p = lambda k: float(pools.get(k, 0.0))
    tsa = meta["tasas"]
    bloques = [
        ("VISTA PRINCIPAL: ESCENARIO DE CANAL", [
            ("ESCENARIO", "Escenario (lista)", ESCENARIO_DEF, None,
             "Mix real · Solo marketplace · Solo páginas web · Solo fidelización · Mix personalizado"),
            ("MIX_MKP", "Mix personalizado: % marketplace", MIX_DEFAULT["MKP"], '0%', "solo aplica a 'Mix personalizado'; los 3 deben sumar 100%"),
            ("MIX_WEB", "Mix personalizado: % páginas web", MIX_DEFAULT["WEB"], '0%', ""),
            ("MIX_FID", "Mix personalizado: % fidelización", MIX_DEFAULT["FID"], '0%', ""),
        ]),
        ("PRECIO POR CANAL (definición comercial: factor × precio de lista de la Pricing)", [
            ("FACT_MKP", "Marketplace: factor sobre PVP", FACTOR_PRECIO["MKP"], D2, "referencia: el precio real promedio fue 1,00 × PVP"),
            ("FACT_WEB", "Páginas web: factor sobre PVP web", FACTOR_PRECIO["WEB"], D2, "referencia: el precio real promedio fue 0,95 × PVP"),
            ("FACT_FID", "Fidelización: factor sobre PVP marketplace", FACTOR_PRECIO["FID"], D2, "referencia: el precio real promedio fue 0,99 × PVP"),
        ]),
        ("COSTO DE CANAL FUERA DE MARKETPLACE (marketplace = % Pricing del SKU)", [
            ("WEB_COM", "Páginas web: comisión venta (medios de pago)", tsa["web_com"], '0.0%', "RAW desde ago-26"),
            ("WEB_ENV", "Páginas web: envío", tsa["web_env"], '0.0%', "RAW desde ago-26 (8,7%–12,2% según tienda)"),
            ("WEB_MKT", "Páginas web: marketing", MKT_WEB, '0.0%', "regla Andrés"),
            ("FID_MKT", "Fidelización: marketing", MKT_FID, '0.0%', "regla Andrés: no usa"),
            ("B2B_COM", "B2B (solo mix real): comisión", tsa["b2b_com"], '0.0%', "RAW desde ago-26, ponderado por venta 12m"),
            ("B2B_ENV", "B2B (solo mix real): envío", tsa["b2b_env"], '0.0%', ""),
            ("B2B_MKT", "B2B (solo mix real): marketing", MKT_B2B, '0.0%', "supuesto"),
            ("UPP_MKP", "Unidades por pedido: marketplace", tsa["upp"]["mkp"], D2, "para insumos por pedido"),
            ("UPP_WEB", "Unidades por pedido: páginas web", tsa["upp"]["web"], D2, ""),
            ("UPP_FID", "Unidades por pedido: fidelización", tsa["upp"]["fid"], D2, ""),
        ]),
        ("SENSIBILIDAD ESTÁNDAR (cuánto se mueve cada palanca para ver cuál pesa más)", [
            ("SH_PRECIO", "Precio de venta: + %", SHOCK["precio"], '0%', "sobre el mix real"),
            ("SH_COSTO", "Costo de compra: − %", SHOCK["costo"], '0%', ""),
            ("SH_MIX", "Mix: puntos de venta que pasan de marketplace a web", SHOCK["mix"], '0%', ""),
            ("SH_ANT", "Anticipo: − puntos", SHOCK["anticipo"], '0%', ""),
            ("SH_PROD", "Producción: − días", SHOCK["prod"], P, ""),
            ("SH_TRAN", "Tránsito: − días", SHOCK["tran"], P, ""),
            ("SH_INV", "Días de inventario: − %", SHOCK["inv"], '0%', ""),
            ("SH_M3", "m³ por unidad: − %", SHOCK["m3"], '0%', "maquila / empaque"),
            ("SH_UDS", "Unidades vendidas: + %", SHOCK["uds"], '0%', ""),
            ("ELASTICIDAD", "Elasticidad precio (Δ% unidades / Δ% precio)", ELASTICIDAD, D2,
             "0 = el precio no mueve unidades (ranking comparable). −1,5 = +5% precio → −7,5% unidades. Se simula por SKU en la Calculadora"),
            ("INV_ACOMP", "% del inventario que acompaña a la venta", INV_ACOMP, '0%',
             "Andrés 1-oct: 75%. 100% = vender más exige el mismo stock en días; 0% = mismo stock, más rotación"),
        ]),
        ("FINANCIAMIENTO", [
            ("TASA", "Costo de capital anual", TASA_CAPITAL, '0.0%', "Andrés 25-sep · implícita planilla: COMEX USD 8-11%, comercial ~8,5%"),
            ("TC", "Tipo de cambio (CLP/USD)", TC_USD, P, "para el FOB de importados"),
            ("ADUANA", "Días de aduana e ingreso a bodega", ADUANA_DIAS, P, "100% pagado en este tramo"),
            ("CRED_FLETE", "Días de pago de flete e internación (desde la llegada)", CREDITO_FLETE_INTERNACION_DIAS, P, "Andrés 25-sep"),
            ("CRED_NAC", "Días de crédito proveedor nacional", CREDITO_NACIONAL_DIAS, P, ""),
            ("FOB_DEF", "FOB / landed si el importado no tiene costo USD", FOB_SHARE_DEFAULT, '0%', "Maestra Importaciones: flete ~6%, gastos locales ~1,5%, derechos ≈0 (TLC China)"),
            ("TR_DEF", "Días de tránsito si no hay puerto", TRANSITO_DEFAULT, P, "Steven despacha desde Shenzhen"),
        ]),
        ("CUENTAS POR COBRAR (opción a: días de cobro de la empresa)", [
            ("DIAS_COBRO", "Días de cobro (CxC comerciales promedio / venta con IVA × 365)", meta["dias_cobro"]["dias"], D1,
             f"CxC promedio 12m ${meta['dias_cobro']['cxc_prom'] / 1e6:,.0f}M (planilla, hoja KT) · se aplica a la venta neta"),
        ]),
        ("COSTO DE OPERACIÓN (12 meses, control de gestión)", [
            ("POOL_ESP", "Almacenaje: arriendo, gastos comunes, racks, seguridad", p(P_ESP), P, "driver: m³ promedio en CA1"),
            ("POOL_MAN", "Manipulación: personal bodega, bonos, choferes, vehículos, combustible", p(P_MAN), P, "driver: unidades B2C + cajas B2B/fulfillment"),
            ("POOL_PV", "Postventa / logística inversa (sub-área POSTVENTA)", p(P_PV), P, "driver: unidades devueltas"),
            ("POOL_INS", "Insumos de embalaje (centro INSUMOS)", p(P_INS), P, "driver: pedidos B2C desde bodega"),
            ("NO_ASIG", "No asignado a producto (gerencia, facturación, sistemas, oficina)", p(P_NA), P, "informativo, no entra"),
        ]),
        ("MANIPULACIÓN (costeo ABC)", [
            ("W_B2C", "Peso de una unidad B2C (picking unitario)", PESO_B2C, D2, "base"),
            ("W_B2B", "Unidad B2B / fulfillment promedio vs B2C", PESO_B2B, D2, "ABC: cuesta 53% de una unidad B2C"),
            ("UDS_CAJA_PROM", "Unidades por caja promedio (B2B + fulfillment, con dato)", uds_caja_promedio(s), D1,
             "se usa en los SKU sin unidades por caja"),
            ("W_CAJA", "Peso de una caja B2B / fulfillment", "=W_B2B*UDS_CAJA_PROM", D2,
             "cada caja movida pesa lo mismo: más unidades por caja = menos costo por unidad"),
        ]),
        ("UMBRALES DE CLASIFICACIÓN", [
            ("ROT_MIN", "Rotación mínima para 'alta rotación' (veces/año)", UMBRAL_ROTACION, D1, "costo de venta / inventario promedio"),
            ("CTR_MIN", "Contribución mínima para 'margen alto' (% venta)", UMBRAL_CONTRIB, '0.0%', ""),
        ]),
    ]
    for titulo, items in bloques:
        su.cell(row=fila, column=1, value=titulo).font = Font(bold=True, color=NAVY)
        fila += 1
        for nm, desc, val, fmt, nota in items:
            su.cell(row=fila, column=1, value=desc)
            c = su.cell(row=fila, column=2, value=val)
            if fmt:
                c.number_format = fmt
            if nm != "NO_ASIG" and not str(val).startswith("="):
                c.fill = Y
            if nm == "ESCENARIO":
                from openpyxl.worksheet.datavalidation import DataValidation
                dv_e = DataValidation(type="list", formula1='"' + ",".join(ESCENARIOS) + '"', allow_blank=False)
                su.add_data_validation(dv_e)
                dv_e.add(c)
                c.font = Font(bold=True, color=NAVY)
            su.cell(row=fila, column=3, value=nota).font = Font(size=9, color="7F7F7F")
            nombre(nm, f"Supuestos!$B${fila}")
            fila += 1
        fila += 1
    su.cell(row=fila, column=1, value="DÍAS DE TRÁNSITO POR PUERTO").font = Font(bold=True, color=NAVY)
    fila += 1
    ini = fila
    for pto, d in TRANSITO_DIAS.items():
        su.cell(row=fila, column=1, value=pto)
        c = su.cell(row=fila, column=2, value=d)
        c.fill = Y
        fila += 1
    nombre("PUERTOS", f"Supuestos!$A${ini}:$B${fila - 1}")
    fila += 1
    # fidelización: programa elegido + tabla por programa
    su.cell(row=fila, column=1, value="FIDELIZACIÓN: PROGRAMA DEL ESCENARIO (definición comercial)").font = Font(bold=True, color=NAVY)
    fila += 1
    su.cell(row=fila, column=1, value="Programa (lista)")
    cprog = su.cell(row=fila, column=2, value=FID_PROG_DEF if FID_PROG_DEF in set(tsa["fid_prog"]["programa"])
                    else "Todos (promedio ponderado)")
    cprog.fill = Y
    nombre("FID_PROG", f"Supuestos!$B${fila}")
    fprog = fila
    fila += 2
    for j, h in enumerate(["Programa", "Venta 12m", "Comisión %", "Envío %"], 1):
        c = su.cell(row=fila, column=j, value=h)
        c.font, c.fill = W, H
    fila += 1
    t0 = fila
    progs = tsa["fid_prog"]
    n_p = len(progs)
    su.cell(row=fila, column=1, value="Todos (promedio ponderado)").font = B
    su.cell(row=fila, column=2, value=f"=SUM(B{t0 + 1}:B{t0 + n_p})").number_format = P
    su.cell(row=fila, column=3, value=f"=SUMPRODUCT(B{t0 + 1}:B{t0 + n_p},C{t0 + 1}:C{t0 + n_p})/B{t0}").number_format = '0.0%'
    su.cell(row=fila, column=4, value=f"=SUMPRODUCT(B{t0 + 1}:B{t0 + n_p},D{t0 + 1}:D{t0 + n_p})/B{t0}").number_format = '0.0%'
    nombre("FID_COM_R", f"Supuestos!$C${t0}")
    nombre("FID_ENV_R", f"Supuestos!$D${t0}")
    fila += 1
    for r_ in progs.itertuples(index=False):
        su.cell(row=fila, column=1, value=r_.programa)
        su.cell(row=fila, column=2, value=float(r_.venta)).number_format = P
        for j, val in [(3, r_.com), (4, r_.env)]:
            c = su.cell(row=fila, column=j, value=float(val))
            c.number_format, c.fill = '0.0%', Y
        fila += 1
    nombre("FID_TABLA", f"Supuestos!$A${t0}:$D${fila - 1}")
    su.cell(row=fprog, column=3, value="comisión y envío del programa elegido (RAW desde ago-26; sin dato = 0%)").font = Font(size=9, color="7F7F7F")
    su.cell(row=fprog + 1, column=1, value="Comisión / envío del programa elegido")
    c = su.cell(row=fprog + 1, column=2, value="=VLOOKUP(FID_PROG,FID_TABLA,3,FALSE)")
    c.number_format = '0.0%'
    nombre("FID_COM", f"Supuestos!$B${fprog + 1}")
    c = su.cell(row=fprog + 1, column=3, value="=VLOOKUP(FID_PROG,FID_TABLA,4,FALSE)")
    c.number_format = '0.0%'
    nombre("FID_ENV", f"Supuestos!$C${fprog + 1}")
    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", formula1=f"=$A${t0}:$A${fila - 1}", allow_blank=False)
    su.add_data_validation(dv)
    dv.add(cprog)
    fila += 1
    su.cell(row=fila, column=1, value="TOTALES DE LOS DRIVERS (calculados)").font = Font(bold=True, color=NAVY)
    fila += 1
    for nm, desc, k in [("TOT_M3CA1", "m³ promedio en CA1", "d_m3ca1"), ("TOT_MANIP", "Unidades ponderadas", "d_manip"),
                        ("TOT_PED", "Pedidos B2C equivalentes", "pedidos_eq"), ("TOT_DEV", "Unidades devueltas", "uds_dev")]:
        su.cell(row=fila, column=1, value=desc)
        c = su.cell(row=fila, column=2, value=f"=SUM({rng(k)})")
        c.number_format = D1
        nombre(nm, f"Supuestos!$B${fila}")
        fila += 1
    for nm, desc, fml in [("TASA_MANIP_U", "Manipulación por unidad B2C (escenarios)", "=IF(TOT_MANIP>0,POOL_MAN/TOT_MANIP*W_B2C,0)"),
                          ("TASA_INS_PED", "Insumos por pedido (escenarios)", "=IF(TOT_PED>0,POOL_INS/TOT_PED,0)")]:
        su.cell(row=fila, column=1, value=desc)
        c = su.cell(row=fila, column=2, value=fml)
        c.number_format = P
        nombre(nm, f"Supuestos!$B${fila}")
        fila += 1
    nombre("IVA", f"Supuestos!$B${fila}")
    su.cell(row=fila, column=1, value="IVA")
    su.cell(row=fila, column=2, value=IVA).number_format = '0%'
    fila += 1
    su.column_dimensions["A"].width = 64
    su.column_dimensions["B"].width = 16
    su.column_dimensions["C"].width = 80

    # ── ROI por SKU (fórmulas) ──
    ws = wb.create_sheet("ROI por SKU")
    orden_cat = {c: i for i, c in enumerate(CAT_COMERCIAL_ORDEN)}
    orden_seg = {c: i for i, c in enumerate(SEGMENTOS)}
    s = s.assign(_s=s["segmento"].map(orden_seg), _o=s["cat_comercial"].map(orden_cat).fillna(99)) \
        .sort_values(["_s", "_o", "venta"], ascending=[True, True, False])
    for j, (k, h, tipo, fmt, fml) in enumerate(COLUMNAS, 1):
        c = ws.cell(row=1, column=j, value=h)
        c.font, c.fill = W, (H if tipo == "f" else PatternFill("solid", fgColor="2E75B6"))
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, (sku, r) in enumerate(s.iterrows(), 2):
        for j, (k, h, tipo, fmt, fml) in enumerate(COLUMNAS, 1):
            if tipo == "f":
                val = fml.replace("{r}", str(i))
                for kk, letra in col.items():
                    val = val.replace("{" + kk + "}", letra)
            else:
                fuente = ENTRADA_DE.get(k, k)
                val = sku if fuente is None else r.get(fuente)
                if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
                    val = None
            c = ws.cell(row=i, column=j, value=val)
            if fmt:
                c.number_format = fmt
            if tipo == "in":
                c.font = AZUL
    for j, (k, h, *_r) in enumerate(COLUMNAS, 1):
        ws.column_dimensions[get_column_letter(j)].width = 40 if k == "producto" else max(11, min(24, len(h) * 0.8))
    ws.row_dimensions[1].height = 45
    ws.freeze_panes = "F2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS))}{n_sku + 1}"
    cl = f"{col['clasificacion']}2:{col['clasificacion']}{n_sku + 1}"
    for txt, color in [("Estrella", "C6EFCE"), ("Destruye valor", "FFC7CE"), ("No paga su capital", "FFEB9C"),
                       ("Sin venta", "E7E6E6")]:
        ws.conditional_formatting.add(cl, CellIsRule(operator="equal", formula=[f'"{txt}"'],
                                                     fill=PatternFill("solid", fgColor=color)))

    # ── Resumen (fórmulas SUMIFS) ──
    rs = wb.create_sheet("Resumen", 0)
    rs["A1"] = "ROI por producto — UnionX"
    rs["A1"].font = Font(bold=True, size=15, color=NAVY)
    n_act = int((s["segmento"] == "Activo").sum())
    rs["A2"] = (f"12 meses {VENTANA_DESDE} a {VENTANA_HASTA} · alcance: {meta.get('alcance', ALCANCE)} · "
                f"{n_sku:,} SKU en el libro, {n_act:,} activos · las tablas bajo "
                "'Resultado por segmento' son SOLO segmento Activo · escenario según Supuestos (celda ESCENARIO) · "
                "ver 'Cómo leer este análisis'").replace(",", ".")
    rs["A2"].font = Font(size=9, color="7F7F7F")
    R = lambda k: rng(k)

    def bloque(hoja, fila0, titulo, clave, valores, seg='"Activo"', col_extra=None, filtro=""):
        """Tabla SUMIFS por `clave`. seg = criterio de segmento (texto Excel o referencia a celda) o None = todos.
        filtro = criterios SUMIFS adicionales (",rango,criterio")."""
        hoja.cell(row=fila0, column=1, value=titulo).font = Font(bold=True, color=NAVY, size=12)
        hdr = [titulo.split(" por ")[-1].split(" (")[0].capitalize(), "SKU", "Productos", "Venta", "Margen directo",
               "Contribución", "Contribución %", "Capital", "ROI s/ capital", "EVA", "% de la venta"]
        if col_extra:
            hdr += [h for h, _k, _f in col_extra]
        for j, h in enumerate(hdr, 1):
            c = hoja.cell(row=fila0 + 1, column=j, value=h)
            c.font, c.fill = W, H
            c.alignment = Alignment(wrap_text=True, horizontal="center")
        f = fila0 + 2
        n_ = len(valores)
        for v_ in valores:
            hoja.cell(row=f, column=1, value=v_)
            crit = f'{R(clave)},$A{f}' + (f',{R("segmento")},{seg}' if seg else "") + filtro
            hoja.cell(row=f, column=2, value=f"=COUNTIFS({crit})")
            hoja.cell(row=f, column=3, value=f"=SUMIFS({R('prim_var')},{crit})")
            hoja.cell(row=f, column=4, value=f"=SUMIFS({R('venta_sel')},{crit})").number_format = P
            hoja.cell(row=f, column=5, value=f"=SUMIFS({R('md')},{crit})").number_format = P
            hoja.cell(row=f, column=6, value=f"=SUMIFS({R('contrib_sel')},{crit})").number_format = P
            hoja.cell(row=f, column=7, value=f'=IF(D{f}>0,F{f}/D{f},"")').number_format = M
            hoja.cell(row=f, column=8, value=f"=SUMIFS({R('capital_sel')},{crit})").number_format = P
            hoja.cell(row=f, column=9, value=f'=IF(H{f}>0,F{f}/H{f},"")').number_format = X
            hoja.cell(row=f, column=10, value=f"=SUMIFS({R('eva_sel')},{crit})").number_format = P
            hoja.cell(row=f, column=11, value=f"=IF(SUM($D${fila0 + 2}:$D${fila0 + 1 + n_})>0,"
                                              f"D{f}/SUM($D${fila0 + 2}:$D${fila0 + 1 + n_}),0)").number_format = M
            for j, (_h, fn, fmt_) in enumerate(col_extra or [], 12):
                hoja.cell(row=f, column=j, value=fn(f, crit, fila0 + 1)).number_format = fmt_ or "General"
            f += 1
        hoja.cell(row=f, column=1, value="Total").font = B
        for j, L in [(2, "B"), (3, "C"), (4, "D"), (5, "E"), (6, "F"), (8, "H"), (10, "J")]:
            c = hoja.cell(row=f, column=j, value=f"=SUM({L}{fila0 + 2}:{L}{f - 1})")
            c.font, c.number_format = B, P
        hoja.cell(row=f, column=7, value=f'=IF(D{f}>0,F{f}/D{f},"")').number_format = M
        hoja.cell(row=f, column=9, value=f'=IF(H{f}>0,F{f}/H{f},"")').number_format = X
        return f + 2

    tabla = lambda fila0, titulo, clave, valores, seg='"Activo"': bloque(rs, fila0, titulo, clave, valores, seg)
    f = tabla(4, "Resultado por segmento (todos los SKU)", "segmento", SEGMENTOS, seg=None)
    act = s[s["segmento"] == "Activo"]
    cats = [c for c in CAT_COMERCIAL_ORDEN if c in set(act["cat_comercial"])]
    f = tabla(f, "Resultado por categoría comercial (activos)", "cat_comercial", cats)
    f = tabla(f, "Resultado por clasificación financiera (activos)", "clasificacion", CLASES)
    f = tabla(f, "Resultado por mejor canal (activos)", "mejor_canal", ["Marketplace", "Páginas web", "Fidelización"])
    marcas = act.groupby("marca")["venta"].sum().sort_values(ascending=False).head(15).index.tolist()
    tabla(f, "Resultado por marca (top 15 activos por venta)", "marca", marcas)
    rs.column_dimensions["A"].width = 34
    for L in "BCDEFGHIJK":
        rs.column_dimensions[L].width = 15

    # ── Categorías (macro y categoría, con selector de segmento) ──
    cg = wb.create_sheet("Categorías", 1)
    cg["A1"] = "ROI por categoría"
    cg["A1"].font = Font(bold=True, size=15, color=NAVY)
    cg["A2"] = ("Segmento (lista) → cambia todas las tablas. 'Productos' cuenta productos base (plantilla Odoo), "
                "'SKU' cuenta variantes. Palanca dominante = la de mayor Δ EVA sumado en la categoría (sensibilidad estándar).")
    cg["A2"].font = Font(size=9, color="7F7F7F")
    cg["A3"] = "Segmento"
    cg["A3"].font = B
    cg["B3"] = "Activo"
    cg["B3"].fill, cg["B3"].font = Y, Font(bold=True, color=NAVY)
    from openpyxl.worksheet.datavalidation import DataValidation
    dvg = DataValidation(type="list", formula1='"' + ",".join(SEGMENTOS) + '"', allow_blank=False)
    cg.add_data_validation(dvg)
    dvg.add(cg["B3"])
    dk = ["d_precio", "d_costo", "d_mix", "d_anticipo", "d_saldo", "d_prod", "d_tran", "d_inv", "d_m3", "d_uds"]
    # L..P = indicadores · Q..Z = Δ EVA sumado de cada palanca (sensibilidad estándar) · P toma la mayor
    extra = [("Inventario promedio", lambda f_, crit, h_: f"=SUMIFS({R('k_bodega')},{crit})", P),
             ("Rotación (veces/año)", lambda f_, crit, h_: f'=IF(L{f_}>0,SUMIFS({R("costo")},{crit})/L{f_},"")', X),
             ("m³ promedio en CA1", lambda f_, crit, h_: f"=SUMIFS({R('d_m3ca1')},{crit})", D1),
             ("EVA por m³", lambda f_, crit, h_: f'=IF(N{f_}>0,J{f_}/N{f_},"")', P),
             ("Palanca dominante", lambda f_, crit, h_: (f'=IF(D{f_}<=0,"",SUBSTITUTE(INDEX($Q${h_}:$Z${h_},'
                                                         f'MATCH(MAX(Q{f_}:Z{f_}),Q{f_}:Z{f_},0)),"Δ EVA · ",""))'), None)]
    extra += [(f"Δ EVA · {p_}", (lambda k_: lambda f_, crit, h_: f"=SUMIFS({R(k_)},{crit})")(k_), P)
              for p_, k_ in zip(PALANCAS, dk)]
    macros = s.groupby("categoria_macro")["venta"].sum().sort_values(ascending=False).index.tolist()
    f = bloque(cg, 5, "Resultado por categoría macro", "categoria_macro", macros, seg="$B$3", col_extra=extra)
    cg.cell(row=f, column=1, value="Resultado por categoría (agrupado por macro)").font = Font(bold=True, color=NAVY, size=12)
    f += 1
    for mc in macros:
        padres = (s[s["categoria_macro"] == mc].groupby("categoria_padre")["venta"].sum()
                  .sort_values(ascending=False).index.tolist())
        f = bloque(cg, f, f"{mc} por categoría", "categoria_padre", padres, seg="$B$3", col_extra=extra,
                   filtro=f',{R("categoria_macro")},"{mc}"')
    cg.column_dimensions["A"].width = 32
    for j in range(2, 27):
        cg.column_dimensions[get_column_letter(j)].width = 14
    cg.freeze_panes = "B5"

    # ── Cómo leer ──
    cm = wb.create_sheet("Cómo leer este análisis", 1)
    cm.column_dimensions["A"].width = 34
    cm.column_dimensions["B"].width = 18
    cm.column_dimensions["C"].width = 100
    fila = 1
    cm.cell(row=fila, column=1, value="Cómo leer este análisis").font = Font(bold=True, size=14, color=NAVY)
    fila += 2
    textos = [
        ("LA PREGUNTA", "", "Por cada peso que tenemos amarrado en un producto, ¿cuánto nos devuelve al año?"),
        ("Contribución", "", "Venta neta − costo de venta (Odoo) − comisión, envío y marketing (% de la Maestra "
                             "Pricing del SKU) − costo de operación asignado (almacenaje, manipulación, insumos, postventa)."),
        ("Capital empleado", "", "Plata amarrada en promedio: anticipo al proveedor + mercadería en tránsito y aduana + "
                                 "inventario promedio + cuentas por cobrar − créditos (flete/internación a 30 días, "
                                 "proveedor nacional). En producción solo está pagado el anticipo; el saldo se paga al "
                                 "embarcar en origen (o al llegar a Chile contra BL si el pago es 'Credit'), así que un "
                                 "producto con más días de producción o tránsito amarra más capital."),
        ("Supuestos", "", "Cuando falta un dato de la maestra se usa un supuesto (columna 'Datos que faltan'); "
                          "ver el archivo de Auditoría de la Maestra de Productos."),
        ("ROI s/ capital", "", "Contribución / capital empleado. 1,5x = cada $1 amarrado genera $1,5 al año."),
        ("Valor económico (EVA)", "", "Contribución − capital × costo de capital. Positivo = el producto paga la plata que usa."),
        ("GMROI", "", "Margen directo / inventario promedio. Indicador estándar de retail para comparar con la industria."),
        ("Rotación", "", "Costo de venta / inventario promedio: cuántas veces al año se renueva el stock."),
        ("Días de caja", "", "Capital / costo diario: cuántos días está afuera cada peso invertido."),
        ("", "", ""),
        ("ESCENARIOS DE CANAL", "", "Cada SKU se calcula como si TODO su volumen de los 12 meses se vendiera por un solo canal: "
                                    "marketplace (% de la Maestra Pricing del SKU), páginas web o fidelización (tasas de Supuestos). "
                                    "Cambia el precio y el costo de canal; el volumen, el costo, el inventario y la bodega se mantienen."),
        ("Mix real", "", "Lo que efectivamente se vendió, cada venta con el costo de su canal."),
        ("Mejor canal", "", "El escenario con mayor valor económico (EVA): pista para un pricing diferenciado."),
        ("Selector", "", "Supuestos → ESCENARIO elige qué escenario alimenta la vista principal, la clasificación y el resumen "
                         "(Mix real, Solo marketplace, Solo páginas web, Solo fidelización o Mix personalizado con sus %)."),
        ("Precio por canal", "", "Definición comercial: factor × precio de lista de la Pricing (editable en Supuestos)."),
        ("Programa de fidelización", "", "Se elige en Supuestos (por defecto, todos ponderados por su venta)."),
        ("", "", ""),
        ("CLASIFICACIÓN FINANCIERA", "", "Se evalúa en este orden (la primera que se cumple), sobre el escenario elegido:"),
        ("Sin venta", "", "No vendió en los 12 meses; solo ocupa capital y bodega."),
        ("Destruye valor", "", "Contribución negativa: pierde plata antes de pagar el capital."),
        ("No paga su capital", "", "Contribución positiva pero menor que el costo de su capital (EVA < 0)."),
        ("Estrella", "", "Paga su capital, rotación ≥ umbral y contribución % ≥ umbral."),
        ("Volumen", "", "Paga su capital y rota sobre el umbral, pero con contribución % bajo el umbral."),
        ("Nicho", "", "Paga su capital con contribución % sobre el umbral, pero rota bajo el umbral."),
        ("Paga justo", "", "Paga su capital, pero rota y marginaliza bajo ambos umbrales."),
        ("Umbrales vigentes", "", "Se editan en Supuestos (ROT_MIN, CTR_MIN)."),
        ("", "", ""),
        ("CATEGORÍA COMERCIAL", "", "Viene tal cual de la Maestra Pricing (Diamante, Oro, Plata, Bronce, Nuevo, "
                                    "Descontinuado). No se modifica: la clasificación financiera es una segunda mirada."),
        ("", "", ""),
        ("SEGMENTOS", "", "Todos los SKU quedan en 'ROI por SKU' (así el costo de bodega se reparte completo), pero el ROI "
                          "se lee sobre lo Activo. El Resumen abre por segmento y el resto de sus tablas es solo Activo."),
        ("Activo", "", "Vendió en los 12 meses, no es consignación y su estado en el RAW no es 'out'."),
        ("Out", "", "Estado 'out' en el RAW: ya no se repone. Su inventario es capital por liberar (pestaña 'Out')."),
        ("Consignación", "", "No usa capital propio (el inventario es del proveedor): su ROI no es comparable."),
        ("Solo stock", "", "Sin venta en los 12 meses pero con stock: alarma para revisar (pestaña 'Alarma solo stock'), "
                           "incluye kits/packs con stock propio en Odoo, que no deberían tenerlo."),
        ("Productos vs SKU", "", "SKU = variante (color, talla). Productos = producto base (plantilla de Odoo)."),
        ("Packs", "", "La venta de un pack se reparte entre sus componentes (hoja Packs de la Maestra Pricing y, si no "
                      "está ahí, la lista de materiales tipo kit de Odoo), en proporción a su PVP."),
    ]
    for a_, b_, c_ in textos:
        cm.cell(row=fila, column=1, value=a_).font = Font(bold=True, color=NAVY) if a_.isupper() else Font(bold=bool(a_))
        cm.cell(row=fila, column=3, value=c_).alignment = Alignment(wrap_text=True)
        if a_ == "Umbrales vigentes":
            cm.cell(row=fila, column=2, value='=TEXT(ROT_MIN,"0.0")&"x · "&TEXT(CTR_MIN,"0%")')
        fila += 1
    # ── Palancas: cómo leerlas y cómo usarlas para definir la estrategia ──
    fila += 1
    cm.cell(row=fila, column=1, value="CÓMO LEER LAS PALANCAS").font = Font(bold=True, color=NAVY)
    fila += 1
    for a_, c_ in [
        ("La idea", "EVA = contribución − costo de capital × capital. Una palanca mejora el resultado, libera capital o ambas. "
                    "A cada SKU se le aplica cada palanca SOLA, en un movimiento estándar (editable en Supuestos, SH_*), y se "
                    "mide cuánto sube su EVA. La que más lo sube es su 'Palanca que más mueve'."),
        ("Por qué casi siempre gana el precio", "El precio actúa sobre el 100% de la venta; las palancas de capital solo sobre el "
                                               "costo de capital (9%) de la plata que liberan. Medido en EVA domina el precio; "
                                               "medido en ROI, rotación y condiciones de pago pesan tanto como el precio."),
        ("Advertencia 1", "'La que más mueve' no es 'la más fácil': el ranking dice dónde está el impacto; la factibilidad la pone "
                          "el equipo comercial y de compras."),
        ("Advertencia 2", "En la sensibilidad estándar el precio se mueve sin elasticidad (ELASTICIDAD = 0, mismas unidades): en SKU "
                          "con mucha competencia ese +5% es optimista. En la Calculadora se puede poner la elasticidad del SKU "
                          "(p. ej. −1,5) y ver el efecto en unidades, costos, inventario y rotación."),
        ("Palancas conectadas", "Vender más no exige todo el inventario proporcional: solo el % de INV_ACOMP (75%). Por eso "
                                "más unidades también sube la rotación. Con elasticidad, bajar precio vende más y rota más rápido."),
        ("Advertencia 3", "Los movimientos estándar son comparables, no equivalentes en esfuerzo: si en un SKU es realista otro "
                          "movimiento (p. ej. −30 días de producción), se prueba en la Calculadora con ese valor."),
    ]:
        cm.cell(row=fila, column=1, value=a_).font = B
        cm.cell(row=fila, column=3, value=c_).alignment = Alignment(wrap_text=True)
        fila += 1
    fila += 1
    hdr_p = ["Palanca", "Movimiento estándar", "Cómo actúa", "Familia", "Δ EVA cartera activa",
             "SKU activos donde es la que más mueve", "Decisión que habilita"]
    for j_, h in enumerate(hdr_p, 1):
        c = cm.cell(row=fila, column=j_, value=h)
        c.font, c.fill = W, H
        c.alignment = Alignment(wrap_text=True, horizontal="center")
    fila += 1
    seg_act = f',{rng("segmento")},"Activo"'
    tabla_pal = [
        ("Precio", "Resultado", '="+"&TEXT(SH_PRECIO,"0%")&" precio"', "Sube toda la venta y el margen; descuenta lo que se lleva el canal (% de la venta). "
         "Con elasticidad ≠ 0 también mueve las unidades, los costos variables, el inventario y la rotación.",
         "d_precio", "Revisar precios de lista y promociones; foco en SKU sin presión competitiva."),
        ("Costo compra", "Resultado", '="−"&TEXT(SH_COSTO,"0%")&" costo"', "Baja el costo de venta y vale menos el inventario, anticipo y tránsito.",
         "d_costo", "Renegociar con el proveedor, consolidar volumen, cambiar origen."),
        ("Mix canal", "Resultado", '=TEXT(SH_MIX,"0%")&" de marketplace a web"', "Ahorra la diferencia entre lo que cobra el marketplace y lo que cuesta vender en web.",
         "d_mix", "Empujar páginas propias y fidelización en los SKU donde el marketplace cobra más."),
        ("Anticipo", "Capital", '="−"&TEXT(SH_ANT,"0%")&" de anticipo"', "Menos plata pagada mientras se fabrica.",
         "d_anticipo", "Negociar condiciones de pago con el proveedor."),
        ("Saldo en Chile", "Capital", '="saldo contra BL en Chile"', "El saldo se paga al llegar y no al embarcar: el tránsito deja de amarrar plata.",
         "d_saldo", "Negociar pago contra BL (crédito) en vez de al embarque."),
        ("Producción", "Capital", '="−"&SH_PROD&" días"', "El anticipo queda menos días amarrado.",
         "d_prod", "Acordar lead time de fabricación más corto o pedir con stock del proveedor."),
        ("Tránsito", "Capital", '="−"&SH_TRAN&" días"', "La mercadería pagada queda menos días en el barco.",
         "d_tran", "Puerto más cercano, ruta directa, aéreo en SKU chicos de alto valor."),
        ("Rotación", "Capital", '="−"&TEXT(SH_INV,"0%")&" días de inventario"', "Menos inventario promedio y menos almacenaje.",
         "d_inv", "Comprar más seguido y en menos cantidad, revisar MOQ, liquidar sobrestock."),
        ("m³", "Resultado", '="−"&TEXT(SH_M3,"0%")&" de volumen"', "Baja el costo de almacenaje.",
         "d_m3", "Maquila, empaque más chico, desarmar gift box."),
        ("Unidades", "Volumen", '="+"&TEXT(SH_UDS,"0%")&" unidades"', "Venta, costo, comisiones, manipulación e insumos suben igual; "
         "el inventario sube solo el % que acompaña a la venta (INV_ACOMP), así que también sube la rotación.",
         "d_uds", "Más exposición, surtido y disponibilidad en los SKU que ya pagan su capital."),
    ]
    p0 = fila
    for nom, fam, mov, como, k_, dec in tabla_pal:
        cm.cell(row=fila, column=1, value=nom).font = B
        cm.cell(row=fila, column=2, value=mov)
        cm.cell(row=fila, column=3, value=como).alignment = Alignment(wrap_text=True, vertical="top")
        cm.cell(row=fila, column=4, value=fam)
        cm.cell(row=fila, column=5, value=f"=SUMIFS({rng(k_)}{seg_act})").number_format = P
        cm.cell(row=fila, column=6, value=f'=COUNTIFS({rng("palanca_top")},A{fila}{seg_act})').number_format = P
        cm.cell(row=fila, column=7, value=dec).alignment = Alignment(wrap_text=True, vertical="top")
        fila += 1
    cm.cell(row=fila, column=1, value="Total").font = B
    cm.cell(row=fila, column=6, value=f"=SUM(F{p0}:F{fila - 1})").number_format = P
    cm.conditional_formatting.add(f"E{p0}:E{fila - 1}", CellIsRule(operator="greaterThan", formula=["0"],
                                                                 fill=PatternFill("solid", fgColor="C6EFCE")))
    fila += 2
    cm.cell(row=fila, column=1, value="CÓMO USARLO PARA DEFINIR LA ESTRATEGIA").font = Font(bold=True, color=NAVY)
    fila += 1
    for a_, c_ in [
        ("1. Mirar la cartera", "Tabla de arriba: qué palancas suman más EVA y en cuántos SKU manda cada una."),
        ("2. Bajar a categoría", "Pestaña Categorías: palanca dominante y Δ EVA de cada palanca por macro y categoría."),
        ("3. Elegir los SKU", "En 'ROI por SKU', filtrar Segmento = Activo y 'Palanca que más mueve' = la palanca elegida; "
                              "ordenar por su columna Δ EVA."),
        ("4. Validar factibilidad", "Para cada SKU, ¿es realista ese movimiento? Probar el movimiento real en la Calculadora."),
        ("5. Asignar responsable", "Precio y mix = comercial · costo, anticipo, saldo, producción y tránsito = compras/COMEX · "
                                   "rotación y m³ = planificación y operaciones · unidades = comercial y marketing."),
        ("Frase guía", "El precio es lo que más plata deja, pero el capital es lo que más rentabilidad libera: con caja escasa, "
                       "rotación y condiciones de pago valen tanto como subir precios."),
    ]:
        cm.cell(row=fila, column=1, value=a_).font = B
        cm.cell(row=fila, column=3, value=c_).alignment = Alignment(wrap_text=True)
        fila += 1
    cm.column_dimensions["D"].width = 12
    cm.column_dimensions["E"].width = 16
    cm.column_dimensions["F"].width = 16
    cm.column_dimensions["G"].width = 52
    fila += 1
    cm.cell(row=fila, column=1, value="EJEMPLO RESUELTO").font = Font(bold=True, color=NAVY)
    cm.cell(row=fila, column=3, value="Escribe cualquier SKU en la celda amarilla y el cálculo se arma paso a paso.")
    fila += 1
    cm.cell(row=fila, column=1, value="SKU")
    ej = cm.cell(row=fila, column=2, value=s.sort_values("eva", ascending=False).index[0])
    ej.fill = Y
    fsku = fila
    fila += 1
    pasos = [("Producto", "producto", None), ("Categoría comercial", "cat_comercial", None),
             ("Venta neta", "venta", P), ("− Costo de venta", "costo", P), ("= Margen directo", "md", P),
             ("− Comisión venta", "comision", P), ("− Envío / logística canal", "logistica", P),
             ("− Marketing", "marketing", P), ("− Almacenaje", "almacenaje", P), ("− Manipulación", "manipulacion", P),
             ("− Insumos", "insumos", P), ("− Postventa", "postventa", P), ("= Contribución", "contribucion", P),
             ("Contribución %", "contrib_pct", M), ("Capital: anticipo", "k_anticipo", P),
             ("Capital: tránsito y aduana", "k_transito", P), ("Capital: inventario promedio", "k_bodega", P),
             ("Capital: cuentas por cobrar", "k_cxc", P),
             ("− Créditos", "credito", P), ("= Capital empleado", "capital", P), ("ROI s/ capital", "roi_capital", X),
             ("− Costo del capital (tasa × capital)", "costo_capital", P), ("= Valor económico (EVA)", "eva", P),
             ("Rotación", "rotacion", X), ("Días de caja", "dias_caja", P),
             ("Si todo se vendiera por marketplace: contribución", "contrib_m", P), ("   ROI s/ capital", "roi_m", X), ("   EVA", "eva_m", P),
             ("Si todo se vendiera por páginas web: contribución", "contrib_w", P), ("   ROI s/ capital", "roi_w", X), ("   EVA", "eva_w", P),
             ("Si todo se vendiera por fidelización: contribución", "contrib_f", P), ("   ROI s/ capital", "roi_f", X), ("   EVA", "eva_f", P),
             ("Mejor canal", "mejor_canal", None), ("Clasificación (escenario elegido)", "clasificacion", None)]
    for etq, k, fmt in pasos:
        cm.cell(row=fila, column=1, value=etq).font = B if etq.startswith("=") else Font()
        c = cm.cell(row=fila, column=2,
                    value=f"=IFERROR(INDEX({rng(k)},MATCH($B${fsku},{rng('sku')},0)),\"\")")
        if fmt:
            c.number_format = fmt
        fila += 1

    # ── Calculadora de palancas (por SKU) ──
    ca = wb.create_sheet("Calculadora", 2)
    ca.column_dimensions["A"].width = 44
    for L in "BCDEFGHIJKLMN":
        ca.column_dimensions[L].width = 15
    ca["A1"] = "Calculadora de palancas por SKU"
    ca["A1"].font = Font(bold=True, size=14, color=NAVY)
    ca["A2"] = ("Escribe el SKU, cambia los valores amarillos de la columna 'Nuevo valor' y compara: cada columna de la "
                "tabla aplica una palanca sola; la última, todas juntas. Base = mix real de los 12 meses.")
    ca["A2"].font = Font(size=9, color="7F7F7F")
    ca["A4"] = "SKU"
    ca["A4"].font = B
    sk_ = ca["B4"]
    sk_.value = s.sort_values("eva", ascending=False).index[0]
    sk_.fill, sk_.font = Y, Font(bold=True, color=NAVY)
    look = lambda k: f'IFERROR(INDEX({rng(k)},MATCH($B$4,{rng("sku")},0)),0)'
    for i_, (etq, k) in enumerate([("Producto", "producto"), ("Categoría comercial", "cat_comercial"),
                                   ("Tipo de compra", "modelo_compra"), ("Clasificación actual (escenario de la vista)", "clasificacion")], 5):
        ca.cell(row=i_, column=1, value=etq)
        ca.cell(row=i_, column=2, value="=" + look(k))
    # base oculta a la derecha (columnas P:Q): valores actuales del SKU
    base = [("U", "unidades"), ("V", "venta"), ("CO", "costo"), ("FOBD", "fob_d"), ("KB", "k_bodega"),
            ("ALM", "almacenaje"), ("MAN", "manipulacion"), ("INS", "insumos"), ("PV", "postventa"),
            ("CP", "com_pct"), ("LP", "log_pct"), ("MP", "mkt_pct"), ("VM", "venta_mkp"), ("VW", "venta_web"),
            ("VF", "venta_fid"), ("VB", "venta_b2b"), ("ANT", "anticipo_pct"), ("SAL", "saldo_en"), ("LT", "lt_prod"),
            ("TR", "transito_dias"), ("M3", "m3_unit"), ("MOD", "modelo_compra")]
    ca["P3"] = "Datos base del SKU (no editar)"
    ca["P3"].font = Font(size=8, color="7F7F7F")
    bref = {}
    for j_, (nm, k) in enumerate(base, 4):
        ca.cell(row=j_, column=16, value=nm).font = Font(size=8, color="7F7F7F")
        ca.cell(row=j_, column=17, value="=" + look(k)).font = Font(size=8, color="7F7F7F")
        bref[nm] = f"$Q${j_}"
    b_ = bref
    # bloque "¿por qué este resultado?" (filas reservadas, se escribe al final con las filas ya conocidas)
    DIAG0 = 10
    # palancas: actual vs nuevo valor
    fila = DIAG0 + 26
    ca.cell(row=fila, column=1, value="PALANCAS").font = Font(bold=True, color=NAVY)
    for j_, h in enumerate(["Palanca", "Actual", "Nuevo valor", "Qué representa"], 1):
        c = ca.cell(row=fila + 1, column=j_, value=h)
        c.font, c.fill = W, H
    pal = [
        ("precio", "1. Precio de venta neto por unidad", f"=IF({b_['U']}>0,{b_['V']}/{b_['U']},0)", P, "mejor precio de venta"),
        ("costo_u", "2. Costo de compra por unidad (landed)", f"=IF({b_['U']}>0,{b_['CO']}/{b_['U']},0)", P, "negociar con el proveedor"),
        ("mix_m", "3. Mix de canal: % marketplace", f"=IF({b_['V']}>0,{b_['VM']}/{b_['V']},0)", '0%', "vender por mejores canales (los 4 suman 100%)"),
        ("mix_w", "3. Mix de canal: % páginas web", f"=IF({b_['V']}>0,{b_['VW']}/{b_['V']},0)", '0%', ""),
        ("mix_f", "3. Mix de canal: % fidelización", f"=IF({b_['V']}>0,{b_['VF']}/{b_['V']},0)", '0%', ""),
        ("mix_b", "3. Mix de canal: % B2B", f"=IF({b_['V']}>0,{b_['VB']}/{b_['V']},0)", '0%', ""),
        ("ant", "4. Anticipo al proveedor (%)", f"={b_['ANT']}", '0%', "mejores condiciones de pago"),
        ("sal", "5. Saldo al proveedor se paga en", f"={b_['SAL']}", None, "Origen (al embarcar) o Chile (BL)"),
        ("lt", "6. Días de producción", f"={b_['LT']}", P, "fabricar más rápido"),
        ("tr", "7. Días de tránsito", f"={b_['TR']}", P, "puerto más rápido / aéreo"),
        ("dinv", "8. Días de inventario", f"=IF({b_['CO']}>0,{b_['KB']}/({b_['CO']}/365),0)", P, "rotar más rápido el inventario"),
        ("m3", "9. m³ por unidad", f"={b_['M3']}", '0.0000', "maquila o empaque con menos volumen"),
        ("u", "10. Unidades vendidas al año", f"={b_['U']}", P, "vender más"),
    ]
    palanca_de = {"precio": 1, "costo_u": 2, "mix_m": 3, "mix_w": 3, "mix_f": 3, "mix_b": 3, "ant": 4, "sal": 5,
                  "lt": 6, "tr": 7, "dinv": 8, "m3": 9, "u": 10}
    fila += 2
    ref = {}
    for k, etq, act, fmt_, nota in pal:
        ca.cell(row=fila, column=1, value=etq)
        a_ = ca.cell(row=fila, column=2, value=act)
        n_ = ca.cell(row=fila, column=3, value=f"=B{fila}")
        n_.fill = Y
        if fmt_:
            a_.number_format = n_.number_format = fmt_
        ca.cell(row=fila, column=4, value=nota).font = Font(size=9, color="7F7F7F")
        ref[k] = fila
        fila += 1
    from openpyxl.worksheet.datavalidation import DataValidation
    dvs = DataValidation(type="list", formula1='"Origen,Chile (BL)"', allow_blank=False)
    ca.add_data_validation(dvs)
    dvs.add(ca[f"C{ref['sal']}"])
    # parámetros de interacción (aplican a todas las columnas que mueven precio o unidades)
    re_, ra_ = fila, fila + 1
    for rr, etq, val, fmt_, nota in [
            (re_, "Elasticidad precio (supuesto)", "=ELASTICIDAD", D2,
             "cuánto cambian las unidades por cada 1% de precio (−1,5: +5% precio → −7,5% unidades)"),
            (ra_, "% del inventario que acompaña a la venta", "=INV_ACOMP", '0%',
             "si vendes más con el mismo stock, sube la rotación (100% = el stock crece igual que la venta)")]:
        ca.cell(row=rr, column=1, value=etq).font = Font(italic=True)
        a_ = ca.cell(row=rr, column=2, value=val)
        n_ = ca.cell(row=rr, column=3, value=f"=B{rr}")
        n_.fill = Y
        a_.number_format = n_.number_format = fmt_
        ca.cell(row=rr, column=4, value=nota).font = Font(size=9, color="7F7F7F")
    fila += 2
    ca.cell(row=fila, column=1, value="Chequeo mix (debe ser 100%)").font = Font(size=9, color="7F7F7F")
    ca.cell(row=fila, column=3, value=f"=C{ref['mix_m']}+C{ref['mix_w']}+C{ref['mix_f']}+C{ref['mix_b']}").number_format = '0%'
    fila += 2
    # tabla de resultados: Actual | cada palanca sola | todas
    cols = ["Actual"] + [f"{n}. {t}" for n, t in [(1, "Precio"), (2, "Costo compra"), (3, "Mix canal"), (4, "Anticipo"),
                                                   (5, "Saldo"), (6, "Producción"), (7, "Tránsito"), (8, "Rotación"),
                                                   (9, "m³"), (10, "Unidades")]] + ["Todas juntas"]
    ca.cell(row=fila, column=1, value="RESULTADO").font = Font(bold=True, color=NAVY)
    fila += 1
    hdr = fila
    ca.cell(row=hdr, column=1, value="").fill = H
    for j_, h in enumerate(cols, 2):
        c = ca.cell(row=hdr, column=j_, value=h)
        c.font, c.fill = W, H
        c.alignment = Alignment(wrap_text=True, horizontal="center")
    fila += 1
    prm = {}
    for k in ref:
        ca.cell(row=fila, column=1, value="   " + [e for kk, e, *_x in pal if kk == k][0]).font = Font(size=9, color="7F7F7F")
        for j_, h in enumerate(cols, 2):
            L = get_column_letter(j_)
            n_pal = j_ - 2
            if h == "Actual":
                val = f"=$B${ref[k]}"
            elif h == "Todas juntas" or n_pal == palanca_de[k]:
                val = f"=$C${ref[k]}"
            else:
                val = f"=$B${ref[k]}"
            c = ca.cell(row=fila, column=j_, value=val)
            c.font = Font(size=9, color="7F7F7F")
            fmt_ = [f for kk, e, a, f, n in pal if kk == k][0]
            if fmt_:
                c.number_format = fmt_
        prm[k] = fila
        fila += 1
    imp_ = f'{b_["MOD"]}="Importación"'
    uf = lambda L: f"IF({b_['U']}>0,{L}{{ue}}/{b_['U']},0)"          # unidades efectivas / actuales
    acomp = lambda L: f"(1+$C${ra_}*({uf(L)}-1))"                     # inventario que acompaña la venta
    met = [
        ("Unidades vendidas (con elasticidad)", lambda L: (
            f"={L}{prm['u']}*MAX(0,1+$C${re_}*IF($B${ref['precio']}>0,{L}{prm['precio']}/$B${ref['precio']}-1,0))"), P),
        ("Venta", lambda L: f"={L}{{ue}}*{L}{prm['precio']}", P),
        ("Costo de venta", lambda L: f"={L}{{ue}}*{L}{prm['costo_u']}", P),
        ("Margen directo", lambda L: f"={L}{{venta}}-{L}{{costo}}", P),
        ("Comisión + envío + marketing", lambda L: (
            f"={L}{{venta}}*({L}{prm['mix_m']}*({b_['CP']}+{b_['LP']}+{b_['MP']})+{L}{prm['mix_w']}*(WEB_COM+WEB_ENV+WEB_MKT)"
            f"+{L}{prm['mix_f']}*(FID_COM_R+FID_ENV_R+FID_MKT)+{L}{prm['mix_b']}*(B2B_COM+B2B_ENV+B2B_MKT))"), P),
        ("Almacenaje", lambda L: (f"={b_['ALM']}*IF({b_['M3']}>0,{L}{prm['m3']}/{b_['M3']},1)*"
                                  f"IF($B${ref['dinv']}>0,{L}{prm['dinv']}/$B${ref['dinv']},1)*{acomp(L)}"), P),
        ("Manipulación, insumos y postventa", lambda L: f"=({b_['MAN']}+{b_['INS']}+{b_['PV']})*{uf(L)}", P),
        ("Contribución", lambda L: f"={L}{{md}}-{L}{{canal}}-{L}{{alm}}-{L}{{oper}}", P),
        ("Contribución %", lambda L: f'=IF({L}{{venta}}>0,{L}{{contrib}}/{L}{{venta}},"")', M),
        ("   FOB diario", lambda L: (f"={b_['FOBD']}*{uf(L)}*IF($B${ref['costo_u']}>0,{L}{prm['costo_u']}/$B${ref['costo_u']},1)"), P),
        ("   Costo diario", lambda L: f"=MAX({L}{{costo}},0)/365", P),
        ("Capital: anticipo en producción", lambda L: f"=IF({imp_},{L}{prm['ant']}*{L}{{fob}}*{L}{prm['lt']},0)", P),
        ("Capital: tránsito y aduana", lambda L: (f'=IF({imp_},IF({L}{prm["sal"]}="Origen",1,{L}{prm["ant"]})*{L}{{fob}}*'
                                                  f"{L}{prm['tr']}+{L}{{fob}}*ADUANA,0)"), P),
        ("Capital: inventario", lambda L: (
            f'=IF({b_["MOD"]}="Consignación",0,$B{{cd}}*IF($B${ref["costo_u"]}>0,{L}{prm["costo_u"]}/$B${ref["costo_u"]},1)'
            f'*{acomp(L)}*{L}{prm["dinv"]})'), P),
        ("Capital: cuentas por cobrar", lambda L: f"=MAX({L}{{venta}},0)/365*DIAS_COBRO", P),
        ("Capital: (−) créditos", lambda L: (f"=IF({imp_},MAX({L}{{cd}}-{L}{{fob}},0)*MAX(0,CRED_FLETE-ADUANA),"
                                              f'IF({b_["MOD"]}="Nacional",{L}{{cd}}*CRED_NAC,0))'), P),
        ("Capital empleado", lambda L: f"=MAX(0,{L}{{ka}}+{L}{{kt}}+{L}{{kb}}+{L}{{kc}}-{L}{{kr}})", P),
        ("ROI s/ capital", lambda L: f'=IF({L}{{cap}}>0,{L}{{contrib}}/{L}{{cap}},"")', X),
        ("Valor económico (EVA)", lambda L: f"={L}{{contrib}}-{L}{{cap}}*TASA", P),
        ("Rotación (veces/año)", lambda L: f'=IF({L}{{kb}}>0,{L}{{costo}}/{L}{{kb}},"")', X),
        ("Clasificación financiera", lambda L: (
            f'=IF({L}{{venta}}<=0,"Sin venta",IF({L}{{contrib}}<0,"Destruye valor",IF({L}{{eva}}<0,"No paga su capital",'
            f'IF(AND(N({L}{{rot}})>=ROT_MIN,N({L}{{cpct}})>=CTR_MIN),"Estrella",IF(N({L}{{rot}})>=ROT_MIN,"Volumen",'
            f'IF(N({L}{{cpct}})>=CTR_MIN,"Nicho","Paga justo"))))))'), None),
        ("Cambio de ROI vs actual (puntos)", lambda L: f'=IF(AND(ISNUMBER({L}{{roi}}),ISNUMBER($B{{roi}})),{L}{{roi}}-$B{{roi}},"")', D2),
        ("Cambio de EVA vs actual", lambda L: f"={L}{{eva}}-$B{{eva}}", P),
    ]
    claves = ["ue", "venta", "costo", "md", "canal", "alm", "oper", "contrib", "cpct", "fob", "cd", "ka", "kt", "kb", "kc", "kr",
              "cap", "roi", "eva", "rot", "clas", "droi", "deva"]
    filas_met = {k: fila + i_ for i_, k in enumerate(claves)}
    for i_, (etq, fn, fmt_) in enumerate(met):
        r_ = fila + i_
        c0 = ca.cell(row=r_, column=1, value=etq)
        if etq in ("Contribución", "Capital empleado", "ROI s/ capital", "Valor económico (EVA)", "Clasificación financiera"):
            c0.font = B
        for j_ in range(2, 2 + len(cols)):
            L = get_column_letter(j_)
            fml = fn(L)
            for k, rr in filas_met.items():
                fml = fml.replace("{" + k + "}", str(rr))
            c = ca.cell(row=r_, column=j_, value=fml)
            if fmt_:
                c.number_format = fmt_
            if etq in ("ROI s/ capital", "Valor económico (EVA)", "Clasificación financiera"):
                c.font = B
    # colores en las filas de cambio vs actual
    from openpyxl.formatting.rule import CellIsRule as _CR
    ult_col = get_column_letter(1 + len(cols))
    for k_ in ("droi", "deva"):
        rng_c = f"C{filas_met[k_]}:{ult_col}{filas_met[k_]}"
        ca.conditional_formatting.add(rng_c, _CR(operator="greaterThan", formula=["0.0001"],
                                                 fill=PatternFill("solid", fgColor="C6EFCE")))
        ca.conditional_formatting.add(rng_c, _CR(operator="lessThan", formula=["-0.0001"],
                                                 fill=PatternFill("solid", fgColor="FFC7CE")))
    # ¿qué palanca mueve más a este SKU? (sensibilidad estándar de Supuestos)
    f_s = filas_met["deva"] + 3
    ca.cell(row=f_s, column=1, value="¿QUÉ PALANCA MUEVE MÁS A ESTE SKU? (cada una movida el estándar de Supuestos)").font = \
        Font(bold=True, color=NAVY)
    for j_, h in enumerate(["Palanca", "Movimiento estándar", "Cambio de EVA", "% del EVA actual", "Ranking"], 1):
        c = ca.cell(row=f_s + 1, column=j_, value=h)
        c.font, c.fill = W, H
    movs = [("Precio", "d_precio", '="+"&TEXT(SH_PRECIO,"0%")&" precio"'),
            ("Costo compra", "d_costo", '="−"&TEXT(SH_COSTO,"0%")&" costo"'),
            ("Mix canal", "d_mix", '=TEXT(SH_MIX,"0%")&" de marketplace a web"'),
            ("Anticipo", "d_antic" + "ipo", '="−"&TEXT(SH_ANT,"0%")&" de anticipo"'),
            ("Saldo en Chile", "d_saldo", '="saldo contra BL en Chile"'),
            ("Producción", "d_prod", '="−"&SH_PROD&" días"'),
            ("Tránsito", "d_tran", '="−"&SH_TRAN&" días"'),
            ("Rotación", "d_inv", '="−"&TEXT(SH_INV,"0%")&" días de inventario"'),
            ("m³", "d_m3", '="−"&TEXT(SH_M3,"0%")&" de volumen"'),
            ("Unidades", "d_uds", '="+"&TEXT(SH_UDS,"0%")&" unidades"')]
    r0_ = f_s + 2
    for i_, (nom, k_, mov) in enumerate(movs):
        r_ = r0_ + i_
        ca.cell(row=r_, column=1, value=nom)
        ca.cell(row=r_, column=2, value=mov)
        ca.cell(row=r_, column=3, value="=" + look(k_)).number_format = P
        ca.cell(row=r_, column=4, value=f'=IF($B${filas_met["eva"]}<>0,C{r_}/ABS($B${filas_met["eva"]}),"")').number_format = '0.0%'
        ca.cell(row=r_, column=5, value=f"=RANK(C{r_},$C${r0_}:$C${r0_ + 9})")
    ca.cell(row=r0_ + 10, column=1, value="Palanca que más mueve").font = B
    c = ca.cell(row=r0_ + 10, column=2, value=f"=INDEX($A${r0_}:$A${r0_ + 9},MATCH(MAX($C${r0_}:$C${r0_ + 9}),$C${r0_}:$C${r0_ + 9},0))")
    c.font = Font(bold=True, color=NAVY)
    ca.conditional_formatting.add(f"C{r0_}:C{r0_ + 9}", _CR(operator="greaterThan", formula=["0"],
                                                           fill=PatternFill("solid", fgColor="C6EFCE")))

    # ── ¿Por qué este resultado? ROI = contribución % × vueltas del capital (sin comparar contra promedios) ──
    fm_ = filas_met
    NV = ult_col                       # columna "Todas juntas" = con los nuevos valores
    gris = Font(size=9, color="7F7F7F")
    d = DIAG0
    ca.cell(row=d, column=1, value="¿POR QUÉ ESTE RESULTADO?").font = Font(bold=True, color=NAVY, size=12)
    r_frase = d + 1
    ca.merge_cells(start_row=r_frase, start_column=1, end_row=r_frase, end_column=13)
    ca.row_dimensions[r_frase].height = 48
    # ① cuánto deja cada $100 vendidos
    r1 = d + 3
    for j_, h in enumerate(["① Cuánto deja cada $100 vendidos", "Actual", "Con nuevos valores"], 1):
        c = ca.cell(row=r1, column=j_, value=h)
        c.font, c.fill = W, H
    por100 = lambda L, expr: f'=IFERROR(({expr})/{L}{fm_["venta"]}*100,0)'
    lineas1 = [("Costo de compra", lambda L: f"{L}{fm_['costo']}"),
               ("Canal: comisión + envío + marketing", lambda L: f"{L}{fm_['canal']}"),
               ("Operación: almacenaje, manipulación, insumos, postventa", lambda L: f"{L}{fm_['alm']}+{L}{fm_['oper']}"),
               ("= Queda (contribución)", lambda L: f"{L}{fm_['contrib']}")]
    for i_, (etq, ex) in enumerate(lineas1, 1):
        ca.cell(row=r1 + i_, column=1, value=etq).font = B if etq.startswith("=") else Font()
        for col_, L in [(2, "B"), (3, NV)]:
            c = ca.cell(row=r1 + i_, column=col_, value=por100(L, ex(L)))
            c.number_format = '"$"#,##0.0'
            if etq.startswith("="):
                c.font = B
    ca.cell(row=r1 + 5, column=1, value="Palancas que lo mueven: precio · costo de compra · mix de canal · m³").font = gris
    # ② dónde está amarrada la plata
    r2 = r1 + 7
    for j_, h in enumerate(["② Dónde está amarrada la plata", "Actual $", "% del capital", "Con nuevos valores $",
                            "% del capital"], 1):
        c = ca.cell(row=r2, column=j_, value=h)
        c.font, c.fill = W, H
        c.alignment = Alignment(wrap_text=True, horizontal="center")
    lineas2 = [("Bodega (inventario)", "kb"), ("Cuentas por cobrar", "kc"), ("Tránsito y aduana", "kt"),
               ("Anticipo en producción", "ka"), ("− Créditos (flete, internación, proveedor nacional)", "kr")]
    for i_, (etq, k_) in enumerate(lineas2, 1):
        rr = r2 + i_
        ca.cell(row=rr, column=1, value=etq)
        sg = "-" if k_ == "kr" else ""
        for col_, L in [(2, "B"), (4, NV)]:
            ca.cell(row=rr, column=col_, value=f"={sg}{L}{fm_[k_]}").number_format = P
            ca.cell(row=rr, column=col_ + 1,
                    value=f'=IFERROR({get_column_letter(col_)}{rr}/{L}{fm_["cap"]},0)').number_format = '0%'
    rcap = r2 + 6
    ca.cell(row=rcap, column=1, value="= Capital empleado").font = B
    for col_, L in [(2, "B"), (4, NV)]:
        c = ca.cell(row=rcap, column=col_, value=f"={L}{fm_['cap']}")
        c.number_format, c.font = P, B
    ca.cell(row=rcap + 1, column=1, value="Días de inventario")
    ca.cell(row=rcap + 1, column=2, value=f"=B{ref['dinv']}").number_format = P
    ca.cell(row=rcap + 1, column=4, value=f"=IFERROR({NV}{fm_['kb']}/{NV}{fm_['cd']},0)").number_format = P
    ca.cell(row=rcap + 2, column=1, value="Palancas que lo mueven: rotación · saldo en Chile · tránsito · producción · "
                                           "anticipo (los días de cobro son de la empresa, no del SKU)").font = gris
    # ③ ROI = contribución % × vueltas
    r3 = rcap + 4
    for j_, h in enumerate(["③ ROI = contribución % × vueltas del capital", "Actual", "Con nuevos valores"], 1):
        c = ca.cell(row=r3, column=j_, value=h)
        c.font, c.fill = W, H
    for i_, (etq, ex, fmt_) in enumerate([
            ("Contribución % (lo que queda de cada $1 vendido)", lambda L: f'=IFERROR({L}{fm_["contrib"]}/{L}{fm_["venta"]},0)', '0.0%'),
            ("Vueltas del capital al año (venta ÷ capital)", lambda L: f'=IFERROR({L}{fm_["venta"]}/{L}{fm_["cap"]},0)', D1),
            ("= ROI s/ capital", lambda L: f'=IFERROR({L}{fm_["contrib"]}/{L}{fm_["cap"]},0)', X)], 1):
        ca.cell(row=r3 + i_, column=1, value=etq).font = B if etq.startswith("=") else Font()
        for col_, L in [(2, "B"), (3, NV)]:
            c = ca.cell(row=r3 + i_, column=col_, value=ex(L))
            c.number_format = fmt_
            if etq.startswith("="):
                c.font = B
    assert r3 + 3 < DIAG0 + 26, "el bloque de diagnóstico pisa la tabla de palancas"
    # frase automática (FIXED usa el separador decimal de la configuración regional)
    c1, c2, c3 = r1 + 1, r1 + 3, r1 + 4
    k1, k4 = r2 + 1, r2 + 4
    mx1 = f"MATCH(MAX(B{c1}:B{c2}),B{c1}:B{c2},0)"
    mx2 = f"MATCH(MAX(C{k1}:C{k4}),C{k1}:C{k4},0)"
    frase = (f'=IF(B{fm_["venta"]}<=0,"Sin venta en los 12 meses: no hay resultado que explicar.",'
             f'"ROI "&FIXED(B{r3 + 3},2)&"x = deja $"&FIXED(B{c3},1)&" de cada $100 vendidos × el capital da "'
             f'&FIXED(B{r3 + 2},1)&" vueltas al año. El mayor costo es "'
             f'&INDEX({{"la compra","el canal","la operación"}},{mx1})&" ($"&FIXED(MAX(B{c1}:B{c2}),1)&" de cada $100) → palanca "'
             f'&INDEX({{"costo de compra","mix de canal o precio","m³ o rotación"}},{mx1})&". La plata está sobre todo en "'
             f'&INDEX({{"bodega","cuentas por cobrar","tránsito","anticipo"}},{mx2})&" ("&TEXT(MAX(C{k1}:C{k4}),"0%")&'
             f'IF({mx2}=1," · "&FIXED(B{rcap + 1},0)&" días de inventario","")&") → palanca "'
             f'&INDEX({{"rotación","precio (los días de cobro son de la empresa)","saldo en Chile o tránsito","anticipo o producción"}},{mx2})'
             f'&". Con el movimiento estándar, la que más sube el EVA es "&LOWER(B{r0_ + 10})&".")')
    c = ca.cell(row=r_frase, column=1, value=frase)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    c.font = Font(color=NAVY, size=11)
    c.fill = PatternFill("solid", fgColor="EEF2F7")
    ca.freeze_panes = "B5"

    # ── Conciliación con el EERR ──
    cc = wb.create_sheet("Conciliación EERR")
    cc["A1"] = "Cascada del ROI vs EERR contable, misma ventana (informativo: el ROI usa los % de la Maestra Pricing)"
    cc["A1"].font = Font(bold=True, color=NAVY)
    for j, h in enumerate(conc.columns, 1):
        c = cc.cell(row=3, column=j, value=h)
        c.font, c.fill = W, H
    for i, row in enumerate(conc.itertuples(index=False), 4):
        for j, val in enumerate(row, 1):
            c = cc.cell(row=i, column=j, value=None if isinstance(val, float) and np.isnan(val) else val)
            if j > 1:
                c.number_format = P
    cc.column_dimensions["A"].width = 70
    cc.column_dimensions["B"].width = 22
    cc.column_dimensions["C"].width = 22

    def hoja_valores(nombre_h, df, fmts, titulo=None):
        h = wb.create_sheet(nombre_h)
        f0 = 1
        if titulo:
            h.cell(row=1, column=1, value=titulo).font = Font(bold=True, color=NAVY)
            f0 = 3
        for j, c_ in enumerate(df.columns, 1):
            c = h.cell(row=f0, column=j, value=c_)
            c.font, c.fill = W, H
        for i, row in enumerate(df.itertuples(index=False), f0 + 1):
            for j, val in enumerate(row, 1):
                if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
                    val = None
                if isinstance(val, pd.Timestamp):
                    val = val.date()
                c = h.cell(row=i, column=j, value=val)
                if df.columns[j - 1] in fmts:
                    c.number_format = fmts[df.columns[j - 1]]
        for j, c_ in enumerate(df.columns, 1):
            h.column_dimensions[get_column_letter(j)].width = 40 if c_ in ("Producto", "Descripcion", "cuenta_analitica") else 16
        h.freeze_panes = h.cell(row=f0 + 1, column=1)
        h.auto_filter.ref = f"A{f0}:{get_column_letter(len(df.columns))}{f0 + len(df)}"

    sm = s[s["m3_fuente"].astype(str).str.startswith(("FALTA", "Volumen Odoo"))]
    sm = sm.sort_values(["venta", "stock_ca1_u"], ascending=False)
    sm = sm.assign(SKU=sm.index)[["SKU", "producto", "marca", "venta", "stock_ca1_u", "m3_fuente"]]
    sm.columns = ["SKU", "Producto", "Marca", "Venta 12m", "Stock promedio CA1 (uds)", "Situación"]
    hoja_valores("SKU sin medidas", sm, {"Venta 12m": P, "Stock promedio CA1 (uds)": D1},
                 "SKU sin medidas oficiales ni en el maestro Loginsa: completar alto × ancho × largo (cm) por unidad")
    s["stock_cierre_val"] = s["stock_cierre_u"].clip(lower=0) * s["costo_unit"]
    s["ult_venta_d"] = s["ult_venta"].dt.date
    so = s[s["segmento"] == "Out"].sort_values("stock_cierre_val", ascending=False)
    so = so.assign(SKU=so.index)[["SKU", "producto", "marca", "categoria_macro", "categoria_padre", "venta", "contribucion",
                                  "eva", "k_bodega", "stock_cierre_u", "stock_cierre_val", "ult_venta_d"]]
    so.columns = ["SKU", "Producto", "Marca", "Categoría macro", "Categoría", "Venta 12m", "Contribución (mix real)",
                  "EVA (mix real)", "Inventario promedio $", f"Stock al {meta['stock_hasta']} (uds)",
                  f"Stock al {meta['stock_hasta']} $", "Última venta"]
    hoja_valores("Out", so, {c: P for c in so.columns[5:11]},
                 f"OUT — capital por liberar: SKU que ya no se reponen. Stock al cierre "
                 f"${so.iloc[:, 10].sum() / 1e6:,.0f}M a costo".replace(",", "."))
    sa = s[s["segmento"] == "Solo stock"].sort_values("stock_cierre_val", ascending=False)
    sa = sa.assign(SKU=sa.index)[["SKU", "producto", "marca", "categoria_macro", "categoria_padre", "modelo_compra", "alarma",
                                  "ult_venta_d", "stock_cierre_u", "stock_cierre_ca1_u", "stock_cierre_val", "k_bodega"]]
    sa.columns = ["SKU", "Producto", "Marca", "Categoría macro", "Categoría", "Tipo de compra", "Alarma", "Última venta",
                  f"Stock al {meta['stock_hasta']} (uds)", "  en CA1 (uds)", f"Stock al {meta['stock_hasta']} $",
                  "Inventario promedio 12m $"]
    hoja_valores("Alarma solo stock", sa, {c: P for c in sa.columns[8:]},
                 f"ALARMA — SKU con stock y sin venta en los 12 meses ({len(sa):,} SKU · stock al cierre "
                 f"${sa.iloc[:, 10].sum() / 1e6:,.0f}M a costo): revisar si se liquidan, se publican o se castigan".replace(",", "."))
    ex = excluidos.assign(SKU=excluidos.index)[["SKU", "producto", "marca", "venta", "stock_u"]]
    ex.columns = ["SKU", "Producto", "Marca", "Venta 12m", "Stock promedio (uds)"]
    hoja_valores("Excluidos", ex, {"Venta 12m": P, "Stock promedio (uds)": D1},
                 "Fuera del análisis: no son productos de venta (repuestos, dummies, corporativos, insumos)")
    ac = aud[["hoja", "Marca", "sku", "cruce_sku", "Descripcion", "costo_usd_maestra", "usd_ultima_pi", "pi_ultima",
              "fecha_pi", "n_pi", "dif_pct", "estado_costo"]].copy()
    ac["_o"] = ac["dif_pct"].abs().fillna(-1)
    ac = ac.sort_values("_o", ascending=False).drop(columns="_o")
    hoja_valores("Auditoría costo USD", ac, {"costo_usd_maestra": D2, "usd_ultima_pi": D2, "dif_pct": M},
                 "COSTO USD de la Maestra Productos vs última PI registrada (el ROI usa la última PI)")
    # el detalle de pools por cuenta (sueldos por cargo) es confidencial: no va en el Excel compartible
    # etiquetas tipo "= Contribución": openpyxl las toma como fórmula (#¡REF! en Excel) → se guardan como texto
    for hoja_ in wb.worksheets:
        for fila_ in hoja_.iter_rows():
            for c_ in fila_:
                if c_.data_type == "f" and isinstance(c_.value, str) and re.match(r"^= [^\W\d]", c_.value):
                    c_.data_type = "s"
    wb.calculation.fullCalcOnLoad = True
    wb.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="rebaja Drive, catálogo Odoo y stock diario")
    ap.add_argument("--sufijo", default="", help="agrega un sufijo al nombre del Excel (p. ej. si el anterior está abierto)")
    ap.add_argument("--sin-panel", action="store_true", help="no lee el panel 'Supuestos ROI' de Drive")
    ap.add_argument("--alcance", choices=["Todas las ventas", "Digital + UnionX B2B"], help="pisa el alcance del panel")
    args = ap.parse_args()
    if not args.sin_panel:
        import roi_supuestos
        roi_supuestos.aplicar_panel(sys.modules[__name__])
    if args.alcance:
        ALCANCE = args.alcance
    s, aud, pools_det, pools, excluidos, meta = calcular(args.refresh)
    s.to_parquet(CACHE / "roi_sku.parquet")
    conc = conciliacion_eerr(s)
    print(pools.round(0).to_string())
    print(conc.to_string())
    out = exportar(s, aud, pools_det, pools, excluidos, conc, meta, args.sufijo)
    print("OK", out)
