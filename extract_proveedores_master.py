#!/usr/bin/env python3
"""
Extractor: Maestro de Proveedores desde Google Sheet del tercero.

Una vez que el tercero (consultor Supply Chain) entregue el sheet maestro,
completar SHEET_ID + TAB_NAME y compartir el sheet en lectura con la
service account: union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com

Output: data/planificacion/proveedores_master.parquet

Schema esperado (ver data/planificacion/proveedores_master.template.md):
  proveedor_id, nombre, pais_origen, puerto_origen,
  contacto_nombre, contacto_email, contacto_whatsapp,
  moneda, incoterm, tipo_credito, dias_credito,
  dias_produccion_min, dias_produccion_max,
  dias_transito_min, dias_transito_max,
  moq_unidades, moq_usd, moq_cbm, comentarios
"""
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / 'data' / 'planificacion'
OUT_DIR.mkdir(parents=True, exist_ok=True)

CREDENTIALS = PROJECT_ROOT / 'credentials.json'

# ⚠️ PENDIENTE: completar cuando el tercero entregue el Drive
SHEET_ID = ''   # ej: '1Abc...XYZ'
TAB_NAME = ''   # ej: 'Maestro'

EXPECTED_COLS = [
    'proveedor_id', 'nombre', 'pais_origen', 'puerto_origen',
    'contacto_nombre', 'contacto_email', 'contacto_whatsapp',
    'moneda', 'incoterm', 'tipo_credito', 'dias_credito',
    'dias_produccion_min', 'dias_produccion_max',
    'dias_transito_min', 'dias_transito_max',
    'moq_unidades', 'moq_usd', 'moq_cbm', 'comentarios',
]


def _conectar_sheets():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly',
    ]
    creds = Credentials.from_service_account_file(str(CREDENTIALS), scopes=scopes)
    return gspread.authorize(creds)


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Trae solo columnas esperadas, casteos básicos, dedup por nombre."""
    df = df.copy()
    df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

    # Aliases comunes
    aliases = {
        'pais': 'pais_origen', 'puerto': 'puerto_origen',
        'email': 'contacto_email', 'whatsapp': 'contacto_whatsapp',
        'credito': 'tipo_credito', 'condicion_pago': 'tipo_credito',
        'lead_time_produccion': 'dias_produccion_max',
        'lead_time_transito': 'dias_transito_max',
    }
    df = df.rename(columns=aliases)

    # Asegurar columnas esperadas
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = None

    # Casteos numéricos (limpiando comas/$/espacios)
    num_cols = ['dias_credito', 'dias_produccion_min', 'dias_produccion_max',
                'dias_transito_min', 'dias_transito_max',
                'moq_unidades', 'moq_usd', 'moq_cbm']
    for c in num_cols:
        df[c] = pd.to_numeric(
            df[c].astype(str).str.replace(r'[^\d.\-]', '', regex=True),
            errors='coerce',
        )

    # Dedup por nombre (case-insensitive)
    df['_nombre_norm'] = df['nombre'].astype(str).str.strip().str.lower()
    df = df[df['_nombre_norm'] != '']
    df = df.drop_duplicates(subset='_nombre_norm', keep='first').drop(columns='_nombre_norm')

    return df[EXPECTED_COLS]


def main():
    if not SHEET_ID or not TAB_NAME:
        print("[WARN] SHEET_ID / TAB_NAME no configurados.")
        print("       Editar las constantes al inicio de este archivo cuando el tercero entregue el Drive.")
        print("       Mientras tanto, se puede llenar manualmente:")
        print(f"         {OUT_DIR / 'proveedores_master.parquet'}")
        print("       siguiendo el schema en proveedores_master.template.md")
        sys.exit(0)

    if not CREDENTIALS.exists():
        print(f"[ERROR] No existe {CREDENTIALS}")
        sys.exit(1)

    print(f"[1] Conectando al sheet {SHEET_ID} / tab '{TAB_NAME}'...")
    gc = _conectar_sheets()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB_NAME)
    rows = ws.get_all_records()
    df_raw = pd.DataFrame(rows)
    print(f"   {len(df_raw)} filas crudas leídas.")

    print("[2] Normalizando...")
    df = _normalizar(df_raw)
    print(f"   {len(df)} proveedores únicos.")

    out_path = OUT_DIR / 'proveedores_master.parquet'
    df.to_parquet(out_path, index=False)
    print(f"[OK] Guardado {out_path}")

    # Resumen para auditoría
    resumen = {
        'fecha_sync': pd.Timestamp.now().isoformat(),
        'proveedores': int(len(df)),
        'con_email': int(df['contacto_email'].notna().sum()),
        'con_lead_time': int(df['dias_produccion_max'].notna().sum()),
        'con_moq': int(df['moq_unidades'].notna().sum()),
    }
    with open(OUT_DIR / 'proveedores_master_resumen.json', 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2)
    print(f"[OK] Resumen: {json.dumps(resumen, indent=2)}")


if __name__ == '__main__':
    main()
