"""Baja 'Planificación Financiera 2026.xlsx' desde Drive (solo lectura) a data/planillas/.

Lo usa GitHub Actions antes de extract_finanzas_planificacion.py, para que el dashboard de cierre
lea la última versión guardada en Drive sin depender del notebook de Andrés.
Busca por nombre dentro de su carpeta (el id cambia si se reemplaza el archivo); fallback al id conocido.
"""
from pathlib import Path

from drive_user_helpers import _service, descargar_archivo

NOMBRE = "Planificación Financiera 2026.xlsx"
CARPETA_ID = "1t_RGuAZo0phf4830VSQWWdtk0AUVcFQG"
FILE_ID_CONOCIDO = "1fkeeYD__8pN31VLnv0IdmMC9pWNE2vgs"
DESTINO = Path(__file__).parent / "data" / "planillas" / NOMBRE


def main():
    q = f"name = '{NOMBRE}' and '{CARPETA_ID}' in parents and trashed = false"
    r = _service().files().list(q=q, fields="files(id,modifiedTime)", orderBy="modifiedTime desc",
                                supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = r.get("files", [])
    fid = files[0]["id"] if files else FILE_ID_CONOCIDO
    print(f"[planilla] {NOMBRE} · id {fid} · modificada {files[0]['modifiedTime'] if files else '¿?'}", flush=True)
    descargar_archivo(fid, DESTINO)


if __name__ == "__main__":
    main()
