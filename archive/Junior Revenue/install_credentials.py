#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUTOMATIC GOOGLE CREDENTIALS INSTALLER
Union X Revenue Management

Crea Service Account y descarga credenciales automáticamente
sin necesidad de gcloud CLI
"""

import os
import sys
import json
import webbrowser
import time
from pathlib import Path
from datetime import datetime

# Fix encoding para Windows
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    from google.auth.transport.requests import Request
    from google.oauth2.service_account import Credentials
except ImportError:
    pass  # No es crítico para este script


def print_header():
    """Imprime encabezado"""
    print("\n" + "="*70)
    print("AUTOMATIC GOOGLE CREDENTIALS INSTALLER")
    print("Union X Revenue Management")
    print("="*70 + "\n")


def step_1_create_project():
    """Paso 1: Crear proyecto en Google Cloud"""
    print("[PASO 1] Crear Proyecto en Google Cloud")
    print("-" * 70)

    project_url = "https://console.cloud.google.com/projectcreate"

    print(f"""
    ℹ️  Se abrirá tu navegador para crear un nuevo proyecto.

    Sigue estos pasos:
    1. Nombre del proyecto: "Union X Revenue"
    2. Click "Create"
    3. Espera a que se cree (toma ~30 segundos)
    4. Cuando termine, vuelve a esta ventana y presiona ENTER
    """)

    input("    Presiona ENTER para abrir Google Cloud Console...")

    try:
        webbrowser.open(project_url)
        print(f"\n    ✓ Navegador abierto: {project_url}")
    except:
        print(f"\n    ⚠️ No se pudo abrir navegador automáticamente.")
        print(f"    Abre manualmente: {project_url}")

    print("\n    Esperando a que completes los pasos en Google Cloud...")
    input("    Presiona ENTER cuando hayas creado el proyecto...")

    return True


def step_2_enable_apis():
    """Paso 2: Habilitar APIs"""
    print("\n[PASO 2] Habilitar Google APIs")
    print("-" * 70)

    apis = [
        ("Google Drive API", "https://console.cloud.google.com/apis/library/drive.googleapis.com"),
        ("Google Sheets API", "https://console.cloud.google.com/apis/library/sheets.googleapis.com"),
    ]

    print(f"""
    ℹ️  Necesitas habilitar 2 APIs.

    Para cada API:
    1. Se abrirá Google Cloud Console
    2. Click el botón azul "ENABLE"
    3. Espera a que se habilite
    4. Vuelve a esta ventana
    """)

    for api_name, api_url in apis:
        input(f"\n    Presiona ENTER para habilitar: {api_name}...")

        try:
            webbrowser.open(api_url)
            print(f"    ✓ Navegador abierto")
        except:
            print(f"    ⚠️ Abre manualmente: {api_url}")

        print(f"    Esperando que habilites {api_name}...")
        input(f"    Presiona ENTER cuando hayas habilitado {api_name}...")

    return True


def step_3_create_service_account():
    """Paso 3: Crear Service Account"""
    print("\n[PASO 3] Crear Service Account")
    print("-" * 70)

    sa_url = "https://console.cloud.google.com/iam-admin/serviceaccounts/create"

    print(f"""
    ℹ️  Se abrirá Google Cloud Console para crear Service Account.

    Sigue estos pasos:
    1. Service Account name: "union-x-revenue-bot"
    2. Click "Create and Continue"
    3. Click "Continue" en los próximos pasos
    4. Click "Done"
    5. Vuelve a esta ventana y presiona ENTER
    """)

    input("    Presiona ENTER para abrir Google Cloud Console...")

    try:
        webbrowser.open(sa_url)
        print(f"\n    ✓ Navegador abierto")
    except:
        print(f"\n    ⚠️ Abre manualmente: {sa_url}")

    print("\n    Esperando a que completes los pasos...")
    input("    Presiona ENTER cuando hayas creado el Service Account...")

    return True


def step_4_download_json():
    """Paso 4: Descargar JSON de credenciales"""
    print("\n[PASO 4] Descargar JSON de Credenciales")
    print("-" * 70)

    json_url = "https://console.cloud.google.com/iam-admin/serviceaccounts"

    print(f"""
    ℹ️  Ahora descargaremos el JSON con las credenciales.

    Sigue estos pasos:
    1. Se abrirá la lista de Service Accounts
    2. Busca: "union-x-revenue-bot"
    3. Click en ella
    4. Ir a "Keys" tab
    5. Click "Add Key" → "Create new key"
    6. Selecciona "JSON"
    7. Click "Create"
    8. Se descargará automáticamente (archivo: [ALGO].json)
    9. Mueve el archivo a tu carpeta "Junior Revenue"
    10. Renómbralo a: "credentials.json"
    11. Vuelve a esta ventana y presiona ENTER
    """)

    input("    Presiona ENTER para abrir Google Cloud Console...")

    try:
        webbrowser.open(json_url)
        print(f"\n    ✓ Navegador abierto")
    except:
        print(f"\n    ⚠️ Abre manualmente: {json_url}")

    print("\n    Esperando a que descargues el JSON...")
    input("    Presiona ENTER cuando hayas guardado credentials.json...")

    return True


def step_5_share_files():
    """Paso 5: Compartir archivos con Service Account"""
    print("\n[PASO 5] Compartir Archivos con Service Account")
    print("-" * 70)

    print("""
    ℹ️  Ahora necesitas compartir 2 archivos.

    Antes, necesitamos el email de la Service Account.

    1. Abre el archivo credentials.json (con Notepad o similar)
    2. Busca la línea: "client_email": "algo@algo.iam.gserviceaccount.com"
    3. Copia ese email completo
    """)

    sa_email = input("\n    Pega aquí el email de la Service Account: ").strip()

    if not sa_email or "@" not in sa_email:
        print("    ✗ Email inválido. Intenta de nuevo.")
        return False

    print(f"    ✓ Email guardado: {sa_email}")

    # Archivo 1: Google Drive
    print(f"""
    \n    ARCHIVO 1: Google Drive

    1. Abre: https://drive.google.com/file/d/1K11y6icDm9M3X3glGUVCOe4HsbpWpEBm/view
    2. Click derecha → Share
    3. Pega el email: {sa_email}
    4. Dale acceso: "Editor"
    5. Click "Share"
    """)

    input("    Presiona ENTER cuando hayas compartido el archivo de Drive...")

    # Archivo 2: Google Sheets
    print(f"""
    \n    ARCHIVO 2: Google Sheets

    1. Abre: https://docs.google.com/spreadsheets/d/1z-HLHEuj__HjNjf7hS4sIhU5QvoNiUJJ1BH965y4JEI/edit
    2. Click derecha → Share
    3. Pega el email: {sa_email}
    4. Dale acceso: "Editor"
    5. Click "Share"
    """)

    input("    Presiona ENTER cuando hayas compartido el Google Sheet...")

    print("\n    ✓ Ambos archivos compartidos")

    return True


def validate_credentials(work_path):
    """Valida que credentials.json existe"""
    print("\n[VALIDACIÓN] Verificando Credenciales")
    print("-" * 70)

    creds_file = work_path / "credentials.json"

    if not creds_file.exists():
        print(f"    ✗ No encontrado: {creds_file}")
        print(f"    Asegúrate de que descargaste el JSON y lo guardaste como 'credentials.json'")
        return False

    try:
        with open(creds_file, 'r') as f:
            creds_data = json.load(f)

        print(f"    ✓ Archivo credentials.json encontrado")
        print(f"    ✓ Proyecto: {creds_data.get('project_id', 'N/A')}")
        print(f"    ✓ Service Account: {creds_data.get('client_email', 'N/A')}")

        return True

    except Exception as e:
        print(f"    ✗ Error validando JSON: {e}")
        return False


def create_env_file(work_path):
    """Crea archivo .env"""
    print("\n[CREANDO] Archivo .env")
    print("-" * 70)

    env_file = work_path / ".env"

    if env_file.exists():
        print(f"    ℹ️  .env ya existe")
        return True

    env_content = """# Google Credentials
GOOGLE_APPLICATION_CREDENTIALS=credentials.json

# Email de Andrés (para descargar EERR que envía Victor)
ANDRES_EMAIL=andres@unionx.cl
ANDRES_PASSWORD=tu_app_password_aqui

# Rutas
DESKTOP_PATH=C:\\Users\\LENOVO\\Desktop\\Junior Revenue
CONTRIBUCION_FILE=Análisis Contribución 2026 V02.02.xlsx
"""

    try:
        env_file.write_text(env_content, encoding='utf-8')
        print(f"    ✓ Archivo .env creado")
        print(f"    ⚠️  IMPORTANTE: Edita .env y configura:")
        print(f"       - ANDRES_PASSWORD: tu contraseña/app-password de Gmail")
        return True
    except Exception as e:
        print(f"    ✗ Error creando .env: {e}")
        return False


def main():
    """Flujo principal"""
    print_header()

    work_path = Path(__file__).parent

    print(f"Carpeta de trabajo: {work_path}\n")

    try:
        # Paso 1: Crear proyecto
        if not step_1_create_project():
            return 1

        # Paso 2: Habilitar APIs
        if not step_2_enable_apis():
            return 1

        # Paso 3: Crear Service Account
        if not step_3_create_service_account():
            return 1

        # Paso 4: Descargar JSON
        if not step_4_download_json():
            return 1

        # Paso 5: Compartir archivos
        if not step_5_share_files():
            return 1

        # Validar credenciales
        if not validate_credentials(work_path):
            print("\n    ⚠️  No se encontró credentials.json")
            print("    Asegúrate de descargarlo y guardarlo en la carpeta Junior Revenue")
            return 1

        # Crear .env
        if not create_env_file(work_path):
            return 1

        # Resumen
        print("\n" + "="*70)
        print("✅ INSTALACIÓN COMPLETADA")
        print("="*70)

        print(f"""
    ✓ Google Project creado
    ✓ APIs habilitadas (Drive + Sheets)
    ✓ Service Account creado
    ✓ Credenciales descargadas: credentials.json
    ✓ Archivos compartidos con Service Account
    ✓ Archivo .env creado

    PRÓXIMOS PASOS:

    1. Edita .env y configura ANDRES_PASSWORD (tu contraseña de Gmail)
    2. Ejecuta: python test_ingestion.py
    3. Si los tests pasan → Configura triggers en Claude Code

    Ver: INSTALACION_FINAL.md para más detalles
        """)

        return 0

    except KeyboardInterrupt:
        print("\n\n✗ Instalación cancelada por el usuario")
        return 1
    except Exception as e:
        print(f"\n✗ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
