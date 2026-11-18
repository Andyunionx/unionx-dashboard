"""Baja 'Planificación Financiera 2026.xlsx' desde Drive (solo lectura) a data/planillas/.

Lo usa GitHub Actions antes de extract_finanzas_planificacion.py, para que el dashboard de cierre
lea la última versión guardada en Drive sin depender del notebook de Andrés.
Busca por nombre dentro de su carpeta (el id cambia si se reemplaza el archivo); fallback al id conocido.
"""
import json
from pathlib import Path

from drive_user_helpers import _service, descargar_archivo

NOMBRE = "Planificación Financiera 2026.xlsx"
CARPETA_ID = "1t_RGuAZo0phf4830VSQWWdtk0AUVcFQG"
FILE_ID_CONOCIDO = "1fkeeYD__8pN31VLnv0IdmMC9pWNE2vgs"
DESTINO = Path(__file__).parent / "data" / "planillas" / NOMBRE
META = DESTINO.with_name("planilla_finanzas_meta.json")   # la lee cierre_mes.py: el correo dice qué versión se usó


def main():
    q = f"name = '{NOMBRE}' and '{CARPETA_ID}' in parents and trashed = false"
    r = _service().files().list(q=q, fields="files(id,modifiedTime)", orderBy="modifiedTime desc",
                                supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = r.get("files", [])
    fid = files[0]["id"] if files else FILE_ID_CONOCIDO
    print(f"[planilla] {NOMBRE} · id {fid} · modificada {files[0]['modifiedTime'] if files else '¿?'}", flush=True)
    META.unlink(missing_ok=True)
    descargar_archivo(fid, DESTINO)
    if files:
        META.write_text(json.dumps({"id": fid, "modificada": files[0]["modifiedTime"]}), encoding="utf-8")


if __name__ == "__main__":
    main()
