"""Helpers para subir archivos a Drive usando OAuth USER (no service account).

Se autentica como andres@unionx.cl. Su quota se usa para guardar el archivo.
Token persistente: drive_oauth_token.json (local) o secret DRIVE_OAUTH_TOKEN_JSON
(GH Actions). El refresh_token nunca expira (a menos que el usuario revoque).
"""
import io
import json
import os
from pathlib import Path

import google.auth.transport.requests  # type: ignore
import google.oauth2.credentials  # type: ignore
import googleapiclient.discovery  # type: ignore
import googleapiclient.http  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent
TOKEN_FILE = PROJECT_ROOT / 'drive_oauth_token.json'
EXCEL_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
SCOPES = ['https://www.googleapis.com/auth/drive']


def _credentials() -> google.oauth2.credentials.Credentials:
    """Carga credenciales OAuth user. Refresca token si vencio."""
    env = os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '').strip()
    if env:
        data = json.loads(env)
    elif TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text(encoding='utf-8'))
    else:
        raise FileNotFoundError(
            'No hay token Drive. Setear DRIVE_OAUTH_TOKEN_JSON o '
            f'generar {TOKEN_FILE} con _drive_oauth_setup.py'
        )
    creds = google.oauth2.credentials.Credentials(
        token=data.get('token'),
        refresh_token=data.get('refresh_token'),
        token_uri=data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=data.get('client_id'),
        client_secret=data.get('client_secret'),
        scopes=data.get('scopes', SCOPES),
    )
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return creds


def _service():
    return googleapiclient.discovery.build(
        'drive', 'v3', credentials=_credentials(), cache_discovery=False
    )


def descargar_archivo(file_id: str, destino: Path) -> Path:
    """Baja un archivo de Drive (por file_id) a una ruta local. OAuth user.

    Usado en GitHub Actions para traer la plantilla de 172 MB que no esta
    en el repo (gitignored). En local no se usa: la plantilla ya existe.
    """
    svc = _service()
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.FileIO(str(destino), 'wb')
    downloader = googleapiclient.http.MediaIoBaseDownload(buf, req, chunksize=20 * 1024 * 1024)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f'   [drive_user] descarga {int(status.progress() * 100)}%', flush=True)
    buf.close()
    print(f'[drive_user] descargado {destino.name} ({destino.stat().st_size/1024/1024:.0f} MB)', flush=True)
    return destino


def subir_o_actualizar(local_path: Path, carpeta_id: str,
                       nombre_destino: str | None = None,
                       hacer_publico: bool = True) -> tuple[str, str]:
    """Sube o actualiza un archivo en Drive. Devuelve (file_id, link)."""
    svc = _service()
    name = nombre_destino or local_path.name

    q = f"'{carpeta_id}' in parents and name='{name}' and trashed=false"
    res = svc.files().list(
        q=q, fields='files(id,name)', pageSize=10,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = res.get('files', [])

    media = googleapiclient.http.MediaFileUpload(
        str(local_path), mimetype=EXCEL_MIME,
        resumable=True, chunksize=10 * 1024 * 1024,
    )

    if files:
        file_id = files[0]['id']
        svc.files().update(
            fileId=file_id, media_body=media, fields='id',
            supportsAllDrives=True,
        ).execute()
        print(f'[drive_user] UPDATE file_id={file_id}')
    else:
        body = {'name': name, 'parents': [carpeta_id]}
        res = svc.files().create(
            body=body, media_body=media, fields='id',
            supportsAllDrives=True,
        ).execute()
        file_id = res['id']
        print(f'[drive_user] CREATE file_id={file_id}')

    if hacer_publico:
        try:
            svc.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader'},
                supportsAllDrives=True,
            ).execute()
            print(f'[drive_user] perms anyone-reader OK')
        except Exception as e:
            if 'already' in str(e).lower() or 'duplicate' in str(e).lower():
                pass  # ya era publico
            else:
                print(f'[drive_user] perms WARN: {str(e)[:200]}')

    link = f'https://drive.google.com/file/d/{file_id}/view?usp=sharing'
    return file_id, link
