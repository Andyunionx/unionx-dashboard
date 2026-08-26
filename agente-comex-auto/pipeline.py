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

sys.stdout.reconfigure(encoding="utf-8")

COMMIT = os.environ.get("COMMIT_MODE", "0").strip() == "1"
DRY = not COMMIT

import estado as st              # noqa: E402
import fase1_correos            # noqa: E402
import fase2_seimex             # noqa: E402
import fase3_costeo             # noqa: E402
import fase4_odoo               # noqa: E402


def main():
    print(f"╔══ AGENTE COMEX AUTÓNOMO — modo {'COMMIT (escrituras ON)' if COMMIT else 'DRY-RUN'} ══╗\n")

    print("── FASE 1 · correos Steven ──")
    fase1_correos.escanear(dry_run=DRY)

    print("\n── FASE 2 · flete Seimex ──")
    fase2_seimex.procesar(dry_run=DRY)

    print("\n── FASE 3 · costeo + SKUs Odoo ──")
    fase3_costeo.procesar(dry_run=DRY)

    print("\n── FASE 4 · carga PO Odoo ──")
    fase4_odoo.procesar(dry_run=DRY)

    print("\n╚══ RESUMEN FINAL ══╝")
    print(st.resumen(st.cargar()))


if __name__ == "__main__":
    main()
