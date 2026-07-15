# -*- coding: utf-8 -*-
"""Fulfillment LIVE (Martín) — stock leído DIRECTO del seller center de cada
marketplace (NO Odoo), para alimentar el Pulso Stock y cruzar contra Odoo.

Fuente: mail "Pulso Fulfillment Marketplaces" (de martin@unionx.cl /
notificaciones@unionx.cl), adjunto Excel hoja 'Sabana' (Canal, SKU interno,
Producto, Stock disponible).

Uso:
  python fulfillment_live.py                 # baja último mail, refresca parquet + genera cruce
  python fulfillment_live.py --file X.xlsx   # usa un Excel local (sin Gmail)

El Pulso solo consume el live si FULFILLMENT_LIVE=1 (gated). Mientras el feed de
Martín siga en PRUEBA, se deja apagado: el cruce se puede correr igual.
"""
import os, sys, io, base64, re, argparse, datetime
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).parent
LIVE_PARQUET = PROJECT_ROOT / "data/stock/fulfillment_live.parquet"
DETALLE = PROJECT_ROOT / "data/stock/detalle.parquet"
OVERRIDE = PROJECT_ROOT / "data/costo_override.csv"
OUT_DIR = PROJECT_ROOT / "data/outputs"

# canal (texto de Martín) -> canal corto
CANAL_MAP = {
    "Mercado Libre (Full)": "Mercado Libre", "Falabella (FBF)": "Falabella",
    "Paris (FF)": "Paris", "Ripley (Fulfillment)": "Ripley", "Walmart": "Walmart",
}
# bodega Odoo (prefijo BF*) -> canal
BOD2CANAL = {"BFML": "Mercado Libre", "BFFa": "Falabella", "BFP": "Paris",
             "BFR": "Ripley", "BFW": "Walmart", "BFE": "Falabella"}
# canal -> bodega sintética para el Pulso
CANAL2BOD = {"Mercado Libre": "Fulfillment ML", "Falabella": "Fulfillment Fala",
             "Paris": "Fulfillment Paris", "Ripley": "Fulfillment Ripley",
             "Walmart": "Fulfillment Walmart"}


# ---------------------------------------------------------------- Gmail
def _gmail():
    import json
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = json.load(open(PROJECT_ROOT / "agente-comex/config/token.json"))
    creds = Credentials.from_authorized_user_info(tok)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def descargar_ultimo_excel(dest_dir: Path) -> Path | None:
    """Baja el adjunto del último 'Pulso Fulfillment Marketplaces'."""
    svc = _gmail()
    res = svc.users().messages().list(
        userId="me", q='subject:"Pulso Fulfillment Marketplaces" newer_than:4d',
        maxResults=5).execute().get("messages", [])
    for mm in res:
        d = svc.users().messages().get(userId="me", id=mm["id"], format="full").execute()

        def _atts(p, o):
            if p.get("filename"):
                o.append((p["filename"], p.get("body", {}).get("attachmentId")))
            for pt in p.get("parts", []) or []:
                _atts(pt, o)
            return o
        atts = [a for a in _atts(d["payload"], []) if a[0] and a[0].lower().endswith(".xlsx") and a[1]]
        if not atts:
            continue
        fn, aid = atts[0]
        at = svc.users().messages().attachments().get(userId="me", messageId=mm["id"], id=aid).execute()
        dest = dest_dir / ("fulfillment_martin_" + re.sub(r"[^A-Za-z0-9._-]", "_", fn))
        dest.write_bytes(base64.urlsafe_b64decode(at["data"]))
        return dest
    return None


# ---------------------------------------------------------------- parse
def parse_sabana(xlsx_path: Path) -> pd.DataFrame:
    """Excel de Martín -> DataFrame canal, sku, producto, qty."""
    df = pd.read_excel(xlsx_path, sheet_name="Sabana")
    df = df.rename(columns={"SKU interno": "sku", "Producto": "producto",
                            "Stock disponible": "qty"})
    df["canal"] = df["Canal"].map(CANAL_MAP).fillna(df["Canal"])
    df["sku"] = df["sku"].astype(str).str.strip()
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0)
    df = df[df["sku"].str.lower().ne("nan") & (df["sku"] != "")]
    return df.groupby(["canal", "sku"], as_index=False).agg(
        producto=("producto", "first"), qty=("qty", "sum"))


def cargar_live(file: Path | None = None, guardar: bool = True) -> pd.DataFrame:
    """Descarga (o usa archivo) + parsea + persiste fulfillment_live.parquet."""
    if file is None:
        file = descargar_ultimo_excel(OUT_DIR if OUT_DIR.exists() else PROJECT_ROOT)
        if file is None:
            raise RuntimeError("No se encontró el mail 'Pulso Fulfillment Marketplaces'.")
    live = parse_sabana(file)
    if guardar:
        LIVE_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        live.to_parquet(LIVE_PARQUET, index=False)
    return live


# ---------------------------------------------------------------- costo
def _mapa_costo() -> dict:
    """SKU -> costo unitario (Odoo detalle + fallback costo_override)."""
    m = {}
    if OVERRIDE.exists():
        ov = pd.read_csv(OVERRIDE)
        m.update(dict(zip(ov["sku"].astype(str), pd.to_numeric(ov["costo_unitario"], errors="coerce").fillna(0))))
    if DETALLE.exists():
        det = pd.read_parquet(DETALLE)
        cu = det.groupby(det["SKU"].astype(str))["Costo Unit"].max()
        for sku, c in cu.items():
            if c and c > 0:
                m[sku] = float(c)  # Odoo manda sobre override cuando existe
    return m


# ---------------------------------------------------------------- integración pulso
def aplicar_live(det: pd.DataFrame, live: pd.DataFrame | None = None) -> pd.DataFrame:
    """Reemplaza en `det` (sábana del Pulso) el fulfillment de Odoo por el LIVE de
    Martín. Walmart se mantiene desde Odoo (sin dato live). Valoriza con costo propio.
    Espera columnas del Pulso: Bodega, Ubicacion, Tipo, SKU, Producto, Categoria,
    Marca, Qty, Reservada, Disponible, Costo Unit, Valor."""
    if live is None:
        live = pd.read_parquet(LIVE_PARQUET) if LIVE_PARQUET.exists() else cargar_live()
    canales_live = set(live["canal"].unique())  # canales con dato live (Walmart NO)
    bcode = det["Bodega"].astype(str).str.split("/").str[0]
    canal_odoo = bcode.map(BOD2CANAL)
    # quitar de Odoo las bodegas fulfillment de los canales que SÍ trae Martín
    quitar = canal_odoo.isin(canales_live)
    base = det[~quitar].copy()

    costo = _mapa_costo()
    # atributos por SKU desde el detalle Odoo (para producto/categoria/marca si existen)
    attr = det.drop_duplicates("SKU").set_index(det.drop_duplicates("SKU")["SKU"].astype(str))
    filas = []
    for r in live.itertuples(index=False):
        sku = str(r.sku)
        cu = costo.get(sku, 0)
        a = attr.loc[sku] if sku in attr.index else None
        filas.append({
            "Bodega": CANAL2BOD.get(r.canal, "Fulfillment " + str(r.canal)),
            "Ubicacion": "Fulfillment (live)", "Tipo": "Fulfillment",
            "SKU": sku, "Producto": (a["Producto"] if a is not None else r.producto),
            "Categoria": (a["Categoria"] if a is not None else ""),
            "Marca": (a["Marca"] if a is not None else ""),
            "Qty": r.qty, "Reservada": 0, "Disponible": r.qty,
            "Costo Unit": cu, "Valor": cu * r.qty,
        })
    live_rows = pd.DataFrame(filas)[det.columns.tolist()]
    return pd.concat([base, live_rows], ignore_index=True)


# ---------------------------------------------------------------- cruce
def generar_cruce(live: pd.DataFrame | None = None) -> dict:
    """Devuelve {'resumen': df, 'detalle': df} Odoo fulfillment vs Martín live."""
    if live is None:
        live = pd.read_parquet(LIVE_PARQUET) if LIVE_PARQUET.exists() else cargar_live()
    det = pd.read_parquet(DETALLE)
    bcode = det["Bodega"].astype(str).str.split("/").str[0]
    odoo = det[bcode.isin(BOD2CANAL)].copy()
    odoo["canal"] = bcode[bcode.isin(BOD2CANAL)].map(BOD2CANAL)
    odoo["sku"] = odoo["SKU"].astype(str).str.strip()
    odoo_g = odoo.groupby(["canal", "sku"], as_index=False).agg(
        odoo_qty=("Disponible", "sum"), producto=("Producto", "first"), costo=("Costo Unit", "first"))
    mar_g = live.rename(columns={"qty": "martin_qty", "producto": "producto_m"})
    m = odoo_g.merge(mar_g, on=["canal", "sku"], how="outer", indicator=True)
    m["odoo_qty"] = m["odoo_qty"].fillna(0)
    m["martin_qty"] = m["martin_qty"].fillna(0)
    m["dif"] = m["odoo_qty"] - m["martin_qty"]
    m["estado"] = m["_merge"].map({"both": "ambos", "left_only": "solo Odoo", "right_only": "solo Martin"})
    resumen = m.groupby("canal", as_index=False).agg(
        odoo=("odoo_qty", "sum"), martin=("martin_qty", "sum"),
        skus_ambos=("estado", lambda s: (s == "ambos").sum()),
        solo_odoo=("estado", lambda s: (s == "solo Odoo").sum()),
        solo_martin=("estado", lambda s: (s == "solo Martin").sum()))
    resumen["dif"] = resumen["odoo"] - resumen["martin"]
    detalle = m[["canal", "sku", "producto", "producto_m", "odoo_qty", "martin_qty", "dif", "estado", "costo"]]
    return {"resumen": resumen, "detalle": detalle.sort_values(["canal", "dif"])}


def _escribir_cruce(w) -> None:
    c = generar_cruce()
    c["resumen"].rename(columns={"canal": "Canal", "odoo": "Odoo uds", "martin": "Martin uds",
                                 "dif": "Dif", "skus_ambos": "SKUs ambos", "solo_odoo": "Solo Odoo",
                                 "solo_martin": "Solo Martin"}).to_excel(w, sheet_name="Resumen", index=False)
    d = c["detalle"].copy()
    d.columns = ["Canal", "SKU", "Producto (Odoo)", "Producto (Martin)", "Odoo uds",
                 "Martin uds", "Dif", "Estado", "Costo Unit"]
    d.to_excel(w, sheet_name="Detalle SKU", index=False)


def cruce_bytes() -> bytes:
    """Comparativa Odoo vs live en memoria (para adjuntar al pulso)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        _escribir_cruce(w)
    return buf.getvalue()


def guardar_cruce_excel(path: Path | None = None) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    hoy = os.environ.get("CRUCE_FECHA") or datetime.date.today().strftime("%Y%m%d")
    path = path or (OUT_DIR / f"Cruce_Fulfillment_Odoo_vs_Martin_{hoy}.xlsx")
    with pd.ExcelWriter(path) as w:
        _escribir_cruce(w)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="Excel local de Martín (evita Gmail)")
    ap.add_argument("--no-cruce", action="store_true")
    a = ap.parse_args()
    live = cargar_live(Path(a.file) if a.file else None)
    print(f"[live] {len(live)} filas | {int(live['qty'].sum())} uds | canales={sorted(live['canal'].unique())}")
    if not a.no_cruce:
        p = guardar_cruce_excel()
        print(f"[cruce] guardado: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
