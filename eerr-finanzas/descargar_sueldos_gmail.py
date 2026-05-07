"""
Descarga archivo de sueldos febrero desde Gmail
Usa credenciales OAuth configuradas en el proyecto
"""

import os
import base64
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

def descargar_sueldos_febrero():
    """Descarga archivo de sueldos febrero desde Gmail"""

    # Rutas
    ruta_credenciales = Path("../credentials.json")
    ruta_destino = Path("../datos_entrada/Sueldos_Febrero_2026.xlsx")

    if not ruta_credenciales.exists():
        print(f"[ERROR] No encontrado: {ruta_credenciales}")
        print("Descarga manual del email: 'liquidaciones de sueldo febrero 2026'")
        print("Archivo: '02.2026 CALCULO DE SUELDOS proceso.xlsx'")
        return False

    try:
        # Autenticación
        creds = Credentials.from_service_account_file(
            str(ruta_credenciales),
            scopes=['https://www.googleapis.com/auth/gmail.readonly']
        )

        service = build('gmail', 'v1', credentials=creds)

        # Buscar email de sueldos febrero
        print("\n[*] Buscando email de sueldos febrero...")
        results = service.users().messages().list(
            userId='me',
            q='subject:"liquidaciones de sueldo febrero" filename:xlsx'
        ).execute()

        messages = results.get('messages', [])
        if not messages:
            print("[AVISO] No encontrado email con sueldos febrero")
            return False

        # Leer primer resultado
        msg_id = messages[0]['id']
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()

        # Buscar adjunto Excel
        payload = msg['payload']
        if 'parts' in payload:
            for part in payload['parts']:
                if part['filename'] and '.xlsx' in part['filename']:
                    print(f"[OK] Encontrado: {part['filename']}")

                    # Descargar
                    file_id = part['body']['attachmentId']
                    att = service.users().messages().attachments().get(
                        userId='me',
                        messageId=msg_id,
                        id=file_id
                    ).execute()

                    data = base64.urlsafe_b64decode(att['data'])

                    # Guardar
                    ruta_destino.parent.mkdir(parents=True, exist_ok=True)
                    with open(ruta_destino, 'wb') as f:
                        f.write(data)

                    print(f"[OK] Descargado: {ruta_destino.name}")
                    return True

        print("[AVISO] No se encontró adjunto Excel en el email")
        return False

    except Exception as e:
        print(f"[ERROR] {e}")
        print("\nAlternativa: Descarga manual")
        print("1. Abre Gmail")
        print("2. Busca: 'liquidaciones de sueldo febrero'")
        print("3. Descarga: '02.2026 CALCULO DE SUELDOS proceso.xlsx'")
        print(f"4. Coloca en: {ruta_destino.parent}/")
        return False


if __name__ == "__main__":
    print("="*70)
    print("DESCARGAR SUELDOS FEBRERO DESDE GMAIL")
    print("="*70)

    exito = descargar_sueldos_febrero()

    if exito:
        print("\n[LISTO] Archivo de sueldos descargado")
    else:
        print("\n[INSTRUCCIONES]")
        print("1. Abre tu Gmail")
        print("2. Busca email con subject: 'liquidaciones de sueldo febrero'")
        print("3. Descarga el archivo: '02.2026 CALCULO DE SUELDOS proceso.xlsx'")
        print("4. Coloca en: UNION X - IA/datos_entrada/")
        print("5. Renómbralo a: 'Sueldos_Febrero_2026.xlsx'")
