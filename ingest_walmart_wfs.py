# -*- coding: utf-8 -*-
"""Ingesta del stock Walmart Full (WFS) desde el export del Seller Center.

Walmart NO tiene feed live de Martín ni API directa; el stock real vive en el
Seller Center y Trini lo exporta como `inventory (N).xlsx` (Walmart WFS). Este
script busca el export más reciente en Gmail, lo parsea y deja un parquet que el
pulso de reposición usa para OVERRIDE del canal Walmart (igual patrón que
`scrape_fala_fbf` para Falabella).

Columnas del export WFS: Item name, GTIN, Item ID, SKU, Status, Daily sales,
Daily units sold, Available units, Reserved units, Inbound units, ...

- `Available units` -> stock Full real (reemplaza Odoo BFW).
- `Inbound units`   -> tránsito real hacia el Full (el "en camino" del canal;
  reemplaza el tránsito de Odoo para Walmart, parte del rediseño sem 35).

Mapeo de SKU: el SKU del Seller Center viene como `WFS<interno>` (a veces sin
prefijo). Se prefiere el match crudo contra el default_code de Odoo; si no, se
prueba sin el prefijo `WFS`. Los que no calzan se registran y se omiten.

Salida: data/stock/walmart_wfs_live.parquet (gitignored). Tolerante: si no hay
export o falla, no escribe y el pulso cae al fallback Odoo BFW para Walmart.
"""
import io
import re
import sys
import json
import base64
import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
TOKEN = ROOT / "agente-comex/config/token.json"
DETALLE = ROOT / "data/stock/detalle.parquet"
OUT = ROOT / "data/stock/walmart_wfs_live.parquet"
MAX_DIAS = 14  # si el export más reciente es más viejo que esto, se avisa

COLS_REQ = {"SKU", "Available units", "Inbound units"}


def _svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    info = json.load(open(TOKEN))
    creds = Credentials.from_authorized_user_info(info)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def _buscar_export(svc):
    """Devuelve (bytes, fecha, filename) del inventory WFS más reciente de Trini."""
    q = 'from:trinidad filename:inventory newer_than:45d'
    res = svc.users().messages().list(userId="me", q=q, maxResults=15).execute().get("messages", [])
    mejor = None  # (fecha_dt, bytes, filename)
    for mm in res:
        m = svc.users().messages().get(userId="me", id=mm["id"]).execute()
        fecha = datetime.datetime.fromtimestamp(int(m["internalDate"]) / 1000)

        def walk(p):
            for part in p.get("parts", []) or []:
                fn = part.get("filename", "")
                if fn.lower().startswith("inventory") and fn.lower().endswith(".xlsx") \
                        and part.get("body", {}).get("attachmentId"):
                    att = svc.users().messages().attachments().get(
                        userId="me", messageId=mm["id"], id=part["body"]["attachmentId"]).execute()
                    return (base64.urlsafe_b64decode(att["data"]), fn)
                r = walk(part)
                if r:
                    return r
            return None
        got = walk(m["payload"])
        if got and (mejor is None or fecha > mejor[0]):
            mejor = (fecha, got[0], got[1])
    return mejor


def main():
    try:
        svc = _svc()
    except Exception as e:
        print(f"[wfs][WARN] Gmail no disponible: {type(e).__name__}: {e}", flush=True)
        return 1
    try:
        mejor = _buscar_export(svc)
    except Exception as e:
        print(f"[wfs][WARN] búsqueda falló: {type(e).__name__}: {e}", flush=True)
        return 1
    if not mejor:
        print("[wfs][WARN] no se encontró export inventory de Walmart en 45d — Walmart usa fallback Odoo", flush=True)
        return 1
    fecha, data, fname = mejor
    dias = (datetime.datetime.now() - fecha).days
    aviso = f" ⚠ ({dias}d de antigüedad)" if dias > MAX_DIAS else ""
    print(f"[wfs] export: {fname} · {fecha:%Y-%m-%d}{aviso}", flush=True)

    try:
        w = pd.read_excel(io.BytesIO(data))
    except Exception as e:
        print(f"[wfs][WARN] no se pudo leer el xlsx: {type(e).__name__}: {e}", flush=True)
        return 1
    if not COLS_REQ.issubset(set(w.columns)):
        print(f"[wfs][WARN] faltan columnas {COLS_REQ - set(w.columns)} — formato cambió, se omite", flush=True)
        return 1

    w = w.copy()
    w["SKU"] = w["SKU"].astype(str).str.strip()
    w = w[w["SKU"].str.len() > 0]
    w["avail"] = pd.to_numeric(w["Available units"], errors="coerce").fillna(0).clip(lower=0)
    w["inb"] = pd.to_numeric(w["Inbound units"], errors="coerce").fillna(0).clip(lower=0)

    # Mapeo SKU WFS -> interno (default_code Odoo). Prefiere crudo, si no sin 'WFS'.
    det_sku = set()
    if DETALLE.exists():
        det = pd.read_parquet(DETALLE)
        det_sku = set(det["SKU"].astype(str).str.strip())

    def interno(s):
        if s in det_sku:
            return s
        st = re.sub(r"^WFS", "", s)
        return st  # si tampoco calza, se deja el stripped (mejor esfuerzo)

    w["sku"] = w["SKU"].map(interno)
    no_match = w[(~w["SKU"].isin(det_sku)) & (~w["sku"].isin(det_sku))]
    if len(no_match):
        ejemplos = no_match["SKU"].head(6).tolist()
        print(f"[wfs] {len(no_match)} SKU sin match en Odoo (se dejan best-effort): {ejemplos}", flush=True)

    out = (w.groupby("sku", as_index=False)
             .agg(qty=("avail", "sum"), inbound=("inb", "sum")))
    out["canal"] = "Walmart"
    out = out[["canal", "sku", "qty", "inbound"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print(f"[wfs] {len(out)} SKU · {out['qty'].sum():,.0f} disp · {out['inbound'].sum():,.0f} inbound "
          f"-> {OUT.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
