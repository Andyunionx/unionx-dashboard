# Maestra de Importaciones viva — sincronización local

El agente COMEX de la nube costea y crea la OC, pero **no toca la Maestra** (vive en Google Drive,
`COMEX/Planificaciones/Maestra Importaciones.xlsx`, y la usan personas). Esto corre en el PC de Andrés.

| Archivo | Qué hace |
|---|---|
| `maestra_sync.py` | Baja los precosteos del correo enviado + los del agente antiguo, filtra los embarques con OC, corrige SKU, arma la Maestra, valida, respalda y reemplaza |
| `maestra_xml.py` | Cirugía XML (openpyxl al guardar borra las matrices dinámicas y el complemento de Office) |
| `alias_sku.json` | Correcciones de SKU manuales, cada una con su fuente |

Programación: tarea diaria 09:30 en el Programador de tareas de Windows (`pythonw.exe maestra_sync.py --aplicar`),
la registra Andrés. Hasta entonces se corre a mano.

```
python maestra_sync.py              # vista previa en C:/Users/andre/comex_maestra/preview (no toca la Maestra)
python maestra_sync.py --aplicar    # respalda (C:/Users/andre/comex_maestra/backups, últimos 20) y reemplaza
```

Reglas:
- **Entra** un embarque cuando tiene OC (estado del agente en origin/main: fase 9 o `po_name`) o si lo costeó el
  agente antiguo. Por embarque gana el precosteo más reciente (el último que recibió el equipo).
- **SKU:** alias del estado del agente + `alias_sku.json`; si el "SKU" es una nota del PI queda en blanco; si viene
  en blanco y el modelo es un código de Odoo, se usa ese código. Los SKU que no existen en Odoo se informan en el log.
- **No escribe** si hay un `~$` de menos de 12 h (Excel abierto), si la Maestra cambió hace menos de 30 min o si
  cambió durante la corrida. Idempotente: una segunda corrida no agrega nada.
- Solo AGREGA embarques; no corrige filas ya cargadas.

Historia: la función `actualizar_maestra` de `costear_embarque.py` quedó desactivada el 29-sep-2026 (guardaba con
openpyxl y escribía columnas corridas: así se dañó la copia `data/comex/Maestra Importaciones V2…`).
