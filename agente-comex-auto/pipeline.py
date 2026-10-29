"""Runner del agente COMEX autónomo — corre las 4 fases en secuencia.

Pensado para el cron de GitHub Actions (diario). Cada fase avanza los embarques
que estén en su etapa; los que no cumplen condición se quedan y reintentan mañana.

COMMIT_MODE (env):
  "1" → escrituras ACTIVAS (Gmail: label+no-leído+borrador · Odoo: PO borrador)
  otro → DRY-RUN (no muta nada; solo actualiza el estado local para visibilidad)

Uso:  python pipeline.py
"""
import os
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8")

COMMIT = os.environ.get("COMMIT_MODE", "0").strip() == "1"
DRY = not COMMIT

import estado as st              # noqa: E402
import fase1_correos            # noqa: E402
import fase2_seimex             # noqa: E402
import fase3_costeo             # noqa: E402
import fase4_odoo               # noqa: E402
import vigia_maestra            # noqa: E402
import vigia_radar              # noqa: E402


ERRORES = []


def _correr(nombre, fn):
    """Una fase que falla (ej. login Seimex 401, 27-29 oct) no corta las demás: antes se perdían fase 3/4
    y el resumen del lunes. El error se acumula y la corrida termina en falla al final, para que se note."""
    try:
        fn()
    except Exception as e:
        traceback.print_exc()
        ERRORES.append(f"{nombre}: {type(e).__name__}: {e}")


def main():
    print(f"╔══ AGENTE COMEX AUTÓNOMO — modo {'COMMIT (escrituras ON)' if COMMIT else 'DRY-RUN'} ══╗\n")

    print("── FASE 1 · correos Steven ──")
    _correr("fase 1", lambda: fase1_correos.escanear(dry_run=DRY))

    print("\n── FASE 2 · flete Seimex ──")
    _correr("fase 2", lambda: fase2_seimex.procesar(dry_run=DRY))

    print("\n── VIGÍA · Maestra de Importaciones (la actualiza el PC; aquí se verifica el resultado) ──")
    try:
        vigia_maestra.revisar(st.cargar(), dry_run=DRY)
    except Exception as e:
        print(f"  (vigía falló: {type(e).__name__}: {e})")

    print("\n── VIGÍA · Radar de Importaciones (lo actualiza el PC; aquí se verifica que siga vivo) ──")
    try:
        vigia_radar.revisar(dry_run=DRY)
    except Exception as e:
        print(f"  (vigía radar falló: {type(e).__name__}: {e})")

    print("\n── FASE 3 · costeo + SKUs Odoo ──")
    _correr("fase 3", lambda: fase3_costeo.procesar(dry_run=DRY))

    print("\n── FASE 4 · carga PO Odoo ──")
    _correr("fase 4", lambda: fase4_odoo.procesar(dry_run=DRY))

    print("\n╚══ RESUMEN FINAL ══╝")
    print(st.resumen(st.cargar()))
    if ERRORES:
        print("\nFASES CON ERROR:\n  " + "\n  ".join(ERRORES))
        sys.exit(1)


if __name__ == "__main__":
    main()
