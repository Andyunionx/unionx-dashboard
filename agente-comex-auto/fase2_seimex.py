"""FASE 2 — Flete final desde el portal Seimex.

Regla (Andrés):
- Para cada embarque en fase 2, buscar su operación en Seimex por el número de PI.
- El PI se fusiona a la referencia Seimex (ej. "193-26 PI0423") RECIÉN al embarcarse,
  que es justo cuando el flete deja de estar vacío → aparición del PI = flete es FINAL.
- Si aparece con flete → guardar flete_usd + ETA, ETA bodega = eta_puerto + 5 días, → fase 3.
- Si no aparece o el flete sigue vacío → quedarse en fase 2 (reintenta al día siguiente).

Read-only: NO muta Gmail, Odoo ni Seimex. Solo consulta.
"""
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE.parent))          # raíz del repo → seimex_api.py
from seimex_api import SeimexAPI               # noqa: E402
import estado as st                            # noqa: E402

DIAS_PUERTO_A_BODEGA = 5                        # ETA bodega = ETA puerto + 5 (Andrés)


def _pi_code(embarque: str) -> str:
    """26TP0716 → 'PI0716' (así aparece fusionado en la referencia Seimex)."""
    m = re.search(r"(\d{4})$", embarque)
    return f"PI{m.group(1)}" if m else embarque


def _match_operacion(ops: list, embarque: str) -> dict | None:
    """Busca la operación cuya referencia contenga el PI del embarque (ej. 'PI0716')."""
    code = _pi_code(embarque).upper()
    digits = code[2:]
    cands = []
    for o in ops:
        ref = str(o.get("reference_number", "")).upper().replace(" ", "")
        prod = str(o.get("product", "")).upper().replace(" ", "")
        if code in ref or code in prod or re.search(rf"PI{digits}", ref + prod):
            cands.append(o)
    if not cands:
        return None
    cands.sort(key=lambda o: o.get("created_at", ""), reverse=True)
    return cands[0]


def _eta_bodega(eta_puerto: str) -> str | None:
    try:
        d = datetime.strptime(eta_puerto[:10], "%Y-%m-%d")
        return (d + timedelta(days=DIAS_PUERTO_A_BODEGA)).strftime("%Y-%m-%d")
    except Exception:
        return None


def procesar(dry_run: bool = True) -> dict:
    estado = st.cargar()
    pend = [e for e, r in estado.items() if r.get("fase") == 2]
    if not pend:
        print("No hay embarques en fase 2.")
        return estado

    print(f"Embarques en fase 2 (esperando flete): {pend}\n")
    api = SeimexAPI()
    ops = api.get_operations()
    print(f"Operaciones en Seimex: {len(ops)}\n")

    for emb in pend:
        reg = estado[emb]
        op = _match_operacion(ops, emb)
        if not op:
            st.log(reg, f"aún no aparece en Seimex (busqué {_pi_code(emb)}) → reintenta mañana")
            continue
        r = SeimexAPI.resumen_operacion(op)
        flete = r.get("quoted_freight_value")
        if not flete:
            st.log(reg, f"operación {r.get('reference')} existe pero flete AÚN vacío ({r.get('stage')}) → reintenta")
            continue
        # flete final disponible
        reg["seimex_ref"] = r.get("reference")
        reg["flete_usd"] = float(flete)
        reg["flete_moneda"] = r.get("quoted_freight_currency")
        reg["eta_puerto"] = r.get("eta")
        reg["eta_bodega"] = _eta_bodega(r.get("eta")) if r.get("eta") else None
        st.log(reg, f"flete FINAL {reg['flete_usd']:.0f} {reg['flete_moneda']} · ref {reg['seimex_ref']} · ETA {reg['eta_puerto']} → bodega {reg['eta_bodega']}")
        st.set_fase(reg, 3, "flete OK → costeo")

    st.guardar(estado)
    print("\nEstado actual:")
    print(st.resumen(estado))
    return estado


if __name__ == "__main__":
    dry = "--commit" not in sys.argv
    print(f"=== FASE 2 · flete Seimex {'(read-only)' if dry else '(commit)'} ===\n")
    procesar(dry_run=dry)
