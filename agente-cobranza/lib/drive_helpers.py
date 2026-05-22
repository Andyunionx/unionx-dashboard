"""
Helpers para bajar/subir Excel a Google Drive usando service account.

Usa `gcp_service_account` (mismo que ya usan los syncs de Finanzas):
  union-x-revenue-bot@union-x-revenue.iam.gserviceaccount.com

IMPORTANTE: cada archivo Excel del cliente debe estar COMPARTIDO con ese
service account con rol "Editor" para que el bot pueda leer/escribir.
Si falta el share, Drive devuelve 403 y el agente falla con mensaje claro.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Optional

import googleapiclient.discovery  # type: ignore
import googleapiclient.errors  # type: ignore
import googleapiclient.http  # type: ignore
from google.oauth2 import service_account  # type: ignore

SCOPES = [
    "https://www.googleapis.com/auth/drive",  # full drive (necesario para update)
]

EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# ID del folder "Trabajado clientes" compartido con el service account.
# El bot SOLO tiene acceso a este folder y sus subcarpetas — no a sus padres.
# Por eso las búsquedas empiezan acá, no desde "root" (Mi unidad).
# Si Andrés muda la carpeta o crea otra, cambiar este ID.
TRABAJADO_CLIENTES_FOLDER_ID = os.environ.get(
    "TRABAJADO_CLIENTES_FOLDER_ID",
    "19EsjfScn5YhJjNVMvT8Qkt3xZBGpGG16",
)


def _credentials() -> service_account.Credentials:
    """Obtiene credentials del service account.

    Busca en este orden:
      1. Variable de entorno GOOGLE_CREDENTIALS_JSON (contenido JSON)
      2. Archivo credentials.json en el root del repo
    """
    json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if json_str:
        import json as _json
        info = _json.loads(json_str)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    # Fallback: archivo local
    repo_root = Path(__file__).resolve().parent.parent.parent
    creds_file = repo_root / "credentials.json"
    if not creds_file.exists():
        raise FileNotFoundError(
            f"No se encontró credentials. Setear GOOGLE_CREDENTIALS_JSON env var "
            f"o crear {creds_file}"
        )
    return service_account.Credentials.from_service_account_file(
        str(creds_file), scopes=SCOPES
    )


def _drive_service():
    return googleapiclient.discovery.build(
        "drive", "v3", credentials=_credentials(), cache_discovery=False
    )


def buscar_archivo_por_path(drive_path: str,
                              folder_inicial_id: Optional[str] = None
                              ) -> Optional[dict]:
    """Busca un archivo en Drive por path **relativo al folder compartido**.

    drive_path: 'PARIS/PARIS 2026.xlsx' (relativo a "Trabajado clientes")

    Recorre la jerarquía carpeta por carpeta. Devuelve dict con id, name, mimeType
    o None si no existe.

    El `folder_inicial_id` default es `TRABAJADO_CLIENTES_FOLDER_ID` — la carpeta
    raíz que el bot tiene compartida.
    """
    svc = _drive_service()
    partes = [p for p in drive_path.split("/") if p]
    parent_id = folder_inicial_id or TRABAJADO_CLIENTES_FOLDER_ID

    for i, parte in enumerate(partes):
        es_ultima = (i == len(partes) - 1)
        # Query: archivos/carpetas con ese name dentro de parent
        q = (f"'{parent_id}' in parents and name='{parte}' "
              "and trashed=false")
        try:
            res = svc.files().list(
                q=q,
                fields="files(id,name,mimeType)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=10,
            ).execute()
        except googleapiclient.errors.HttpError as e:
            raise RuntimeError(f"Error Drive buscando '{parte}': {e}") from e

        files = res.get("files", [])
        if not files:
            return None

        if es_ultima:
            # Devolver el primer match (asumimos nombre único)
            return files[0]
        else:
            # Continuar buscando dentro de esta carpeta
            parent_id = files[0]["id"]

    return None


def buscar_carpeta_por_path(drive_path: str,
                              folder_inicial_id: Optional[str] = None
                              ) -> Optional[str]:
    """Busca una carpeta relativa a `Trabajado clientes` y devuelve su file_id.

    drive_path: ej 'PARIS' (relativo).  Vacío → devuelve folder raíz compartido.
    """
    if not drive_path:
        return folder_inicial_id or TRABAJADO_CLIENTES_FOLDER_ID
    svc = _drive_service()
    partes = [p for p in drive_path.split("/") if p]
    parent_id = folder_inicial_id or TRABAJADO_CLIENTES_FOLDER_ID
    for parte in partes:
        q = (f"'{parent_id}' in parents and name='{parte}' "
              "and mimeType='application/vnd.google-apps.folder' "
              "and trashed=false")
        res = svc.files().list(
            q=q,
            fields="files(id,name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageSize=10,
        ).execute()
        files = res.get("files", [])
        if not files:
            return None
        parent_id = files[0]["id"]
    return parent_id


def descargar_archivo(file_id: str, destino_local: Path) -> Path:
    """Baja un archivo de Drive (por id) a una ruta local."""
    svc = _drive_service()
    destino_local.parent.mkdir(parents=True, exist_ok=True)
    req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = googleapiclient.http.MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    destino_local.write_bytes(buf.getvalue())
    return destino_local


def subir_archivo(file_local: Path, drive_carpeta_id: str,
                    nombre_destino: Optional[str] = None) -> str:
    """Sube un archivo nuevo a Drive en la carpeta indicada. Devuelve file_id."""
    svc = _drive_service()
    name = nombre_destino or file_local.name
    media = googleapiclient.http.MediaFileUpload(
        str(file_local), mimetype=EXCEL_MIME, resumable=False
    )
    body = {"name": name, "parents": [drive_carpeta_id]}
    res = svc.files().create(
        body=body, media_body=media, fields="id",
        supportsAllDrives=True,
    ).execute()
    return res["id"]


def actualizar_archivo(file_id: str, file_local: Path) -> str:
    """Actualiza el contenido de un archivo existente preservando file_id,
    historial de versiones y permisos compartidos.
    """
    svc = _drive_service()
    media = googleapiclient.http.MediaFileUpload(
        str(file_local), mimetype=EXCEL_MIME, resumable=False
    )
    res = svc.files().update(
        fileId=file_id, media_body=media, fields="id",
        supportsAllDrives=True,
    ).execute()
    return res["id"]


def descargar_o_crear_actualizado(drive_path_original: str,
                                    output_suffix: str = "_ACTUALIZADO",
                                    workdir: Optional[Path] = None
                                    ) -> tuple[Path, str, str]:
    """Estrategia híbrida tipo Martín:

      1. Busca el archivo ORIGINAL en Drive (`drive_path_original`).
         Si no existe → falla.
      2. Lo baja a `workdir/<nombre>.xlsx`.
      3. Calcula el path del archivo ACTUALIZADO en la misma carpeta:
            <basename>_ACTUALIZADO.xlsx
      4. Si el ACTUALIZADO ya existe en Drive, devuelve su file_id (para
         hacer update conservando versiones).
         Si no, devuelve None en file_id_actualizado y luego se crea.

    Retorna: (path_local_original, file_id_original, file_id_actualizado_o_None)
    """
    if workdir is None:
        workdir = Path("/tmp") if Path("/tmp").exists() else Path(".")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # 1+2. Original
    info = buscar_archivo_por_path(drive_path_original)
    if not info:
        raise FileNotFoundError(
            f"No se encontró el archivo en Drive: {drive_path_original}\n"
            f"Verificar que existe y que está compartido con el service account."
        )
    nombre_local = info["name"]
    local_original = workdir / nombre_local
    descargar_archivo(info["id"], local_original)

    # 3+4. Actualizado (mismo dir que original, name modificado)
    carpeta_path = "/".join(drive_path_original.split("/")[:-1])
    base, ext = os.path.splitext(nombre_local)
    nombre_actualizado = f"{base}{output_suffix}{ext}"
    path_actualizado_full = f"{carpeta_path}/{nombre_actualizado}"

    info_act = buscar_archivo_por_path(path_actualizado_full)
    file_id_actualizado = info_act["id"] if info_act else None

    return (local_original, info["id"], file_id_actualizado)
