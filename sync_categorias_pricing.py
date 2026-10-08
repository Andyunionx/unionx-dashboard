# -*- coding: utf-8 -*-
"""Categoría padre/hijo por SKU desde la Maestra Pricing → data/planillas/categorias_pricing.csv.

La Maestra Pricing (Drive "Maestra Pricing.xlsx", hoja Pricing) es la fuente única de las categorías: la mantiene
Felipe (Andrés 8-oct-2026). El RAW la aplica en mejoras_raw_overlay.py (P1e) por encima de la Matriz de productos;
los SKU que no están en la Pricing quedan con la categoría de la Matriz.

Uso: python sync_categorias_pricing.py      (Drive con DRIVE_OAUTH_TOKEN_JSON o drive_oauth_token.json)
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
FILE_MAESTRA_PRICING = '1gVJmFCR19KbYkZfds7fH-62rJ0Zpt32P'
OUT = ROOT / 'data' / 'planillas' / 'categorias_pricing.csv'


def bajar() -> bytes:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    env = os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '').strip()
    creds = (Credentials.from_authorized_user_info(json.loads(env)) if env
             else Credentials.from_authorized_user_file(str(ROOT / 'drive_oauth_token.json')))
    if not creds.valid:
        creds.refresh(Request())
    drv = build('drive', 'v3', credentials=creds)
    b = io.BytesIO()
    dl = MediaIoBaseDownload(b, drv.files().get_media(fileId=FILE_MAESTRA_PRICING, supportsAllDrives=True))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return b.getvalue()


def categorias(xlsx: bytes) -> pd.DataFrame:
    p = pd.read_excel(io.BytesIO(xlsx), sheet_name='Pricing', header=1, dtype=str)
    out = pd.DataFrame({'sku': p['SKU'].fillna('').str.strip(),
                        'categoria_padre': p['Categoria Padre'].fillna('').str.strip(),
                        'categoria_hijo': p['Categoria Hijo'].fillna('').str.strip()})
    out = out[out['sku'].ne('') & out['categoria_padre'].ne('') & out['categoria_hijo'].ne('')
              & ~out['categoria_padre'].isin(['0', 'nan'])]
    return out.drop_duplicates('sku', keep='first').sort_values('sku').reset_index(drop=True)


def main():
    c = categorias(bajar())
    if len(c) < 500:          # una Pricing a medio guardar no pisa la copia buena
        raise SystemExit(f'[ABORTA] la Pricing trajo solo {len(c)} SKU con categoría')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c.to_csv(OUT, index=False, encoding='utf-8', lineterminator='\n')
    print(f'[OK] {OUT.name}: {len(c)} SKU · {c["categoria_padre"].nunique()} categorías padre')


if __name__ == '__main__':
    main()
