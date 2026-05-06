#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test conexión a Google Sheets"""

import os
import sys
import json
from pathlib import Path

# Fix encoding para Windows
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Cargar credenciales
work_path = Path(__file__).parent
creds_file = work_path / "credentials.json"

print("\n" + "="*70)
print("TEST CONEXIÓN - Google Sheets API")
print("="*70 + "\n")

if not creds_file.exists():
    print("✗ credentials.json no encontrado")
    sys.exit(1)

try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    import gspread

    print("[1] Cargando credenciales...")
    creds = Credentials.from_service_account_file(
        str(creds_file),
        scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
    )
    print("  ✓ Credenciales cargadas")

    print("\n[2] Conectando a Google Sheets...")
    gc = gspread.authorize(creds)
    print("  ✓ gspread autorizado")

    # IDs de los archivos
    sheets_id = "1z-HLHEuj__HjNjf7hS4sIhU5QvoNiUJJ1BH965y4JEI"

    print(f"\n[3] Abriendo Google Sheet: {sheets_id[:20]}...")
    sheet = gc.open_by_key(sheets_id)
    print(f"  ✓ Sheet abierto: {sheet.title}")

    print(f"\n[4] Listando hojas disponibles...")
    worksheets = sheet.worksheets()
    for i, ws in enumerate(worksheets):
        print(f"  [{i}] {ws.title} (ID: {ws.id})")

    print("\n[5] Leyendo datos de primera hoja...")
    ws = sheet.get_worksheet(0)
    rows = ws.get_all_values()
    print(f"  ✓ {len(rows)} filas encontradas")
    if rows:
        print(f"  ✓ Primeras columnas: {rows[0][:3]}")

    print("\n" + "="*70)
    print("✅ CONEXIÓN A GOOGLE SHEETS: EXITOSA")
    print("="*70)
    print(f"""
RESUMEN:
  ✓ Service Account autorizado
  ✓ Google Sheets accesible
  ✓ {len(worksheets)} hojas disponibles
  ✓ Datos legibles

Sistema listo para iniciar triggers.
    """)

except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
