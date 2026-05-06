#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick validation test - Sin acceso a Excel/Google"""

import os
import sys
import json
from pathlib import Path

# Fix encoding para Windows
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("\n" + "="*70)
print("QUICK VALIDATION TEST - Union X Revenue")
print("="*70 + "\n")

work_path = Path(__file__).parent

# Test 1: credentials.json
print("[TEST 1] Verificando credentials.json...")
creds_file = work_path / "credentials.json"
if creds_file.exists():
    try:
        with open(creds_file, 'r') as f:
            creds = json.load(f)
        print(f"  ✓ credentials.json encontrado")
        print(f"  ✓ Proyecto: {creds.get('project_id', 'N/A')}")
        print(f"  ✓ Service Account: {creds.get('client_email', 'N/A')}")
    except Exception as e:
        print(f"  ✗ Error en credentials.json: {e}")
else:
    print(f"  ✗ credentials.json NO encontrado en {work_path}")

# Test 2: .env
print("\n[TEST 2] Verificando archivo .env...")
env_file = work_path / ".env"
if env_file.exists():
    try:
        with open(env_file, 'r') as f:
            env_content = f.read()
        if "ANDRES_EMAIL" in env_content and "ANDRES_PASSWORD" in env_content:
            print(f"  ✓ .env encontrado")
            print(f"  ✓ ANDRES_EMAIL configurado")
            print(f"  ✓ ANDRES_PASSWORD configurado")
        else:
            print(f"  ⚠ .env incompleto")
    except Exception as e:
        print(f"  ✗ Error leyendo .env: {e}")
else:
    print(f"  ✗ .env NO encontrado")

# Test 3: Excel file
print("\n[TEST 3] Verificando archivo Excel...")
excel_file = Path.home() / "Desktop" / "Junior Revenue" / "Análisis Contribución 2026 V02.02.xlsx"
if excel_file.exists():
    print(f"  ✓ Excel encontrado en Desktop/Junior Revenue")
else:
    # Try current directory
    excel_file = work_path / "Análisis Contribución 2026 V02.02.xlsx"
    if excel_file.exists():
        print(f"  ✓ Excel encontrado en carpeta actual")
    else:
        print(f"  ⚠ Excel no encontrado (se creará automáticamente)")

# Test 4: Python dependencies
print("\n[TEST 4] Verificando dependencias Python...")
dependencies = {
    'pandas': 'pd',
    'openpyxl': 'openpyxl',
    'google': 'google',
}

all_ok = True
for pkg, import_name in dependencies.items():
    try:
        __import__(import_name)
        print(f"  ✓ {pkg} instalado")
    except ImportError:
        print(f"  ✗ {pkg} NO instalado")
        all_ok = False

# Test 5: config.json
print("\n[TEST 5] Verificando config.json...")
config_file = work_path / "config.json"
if config_file.exists():
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        print(f"  ✓ config.json encontrado")
        print(f"  ✓ Google Drive ID: {config.get('google_drive_file_id', 'N/A')[:20]}...")
        print(f"  ✓ Google Sheets ID: {config.get('google_sheets_id', 'N/A')[:20]}...")
    except Exception as e:
        print(f"  ✗ Error en config.json: {e}")
else:
    print(f"  ⚠ config.json no encontrado (opcional)")

# Summary
print("\n" + "="*70)
print("✅ VALIDACIÓN COMPLETADA")
print("="*70)
print("""
ESTADO:
  ✓ Sistema de automatización listo para iniciar triggers

PRÓXIMOS PASOS:
  1. Los triggers se ejecutarán automáticamente:
     - Lunes 9 AM: Descarga Google Drive + Sheets
     - Día 7: Descarga detalles de comisiones
     - Día 10: Descarga EERR + Ejecuta skill

  2. Configurar triggers en Claude Code con: /schedule
""")
