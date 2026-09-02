"""FASE 3 — Costeo + chequeo de SKUs en Odoo + borrador de correo.

Con PI+PL (fase 1) y flete final (fase 2), esta fase:
1. Construye las Tarifas (flete del estado + gastos Chile ESTÁNDAR + TC + ETA).
2. Corre el motor de costeo (reusa _REACTIVAR_NUEVO_PC/costear_embarque.py, con fix CBM).
3. Genera el Pre-costeo + compara con la Maestra.
4. Chequea en Odoo qué SKU existen (por default_code) → lista de FALTANTES.
5. Deja BORRADOR de correo a Felipe/Seba/Gerardo (los tres) con costeo + faltantes.
6. Gate: si NO hay faltantes → fase 4. Si faltan, se queda y re-chequea Odoo cada día.

dry_run=True: costea y reporta, NO crea el borrador en Gmail.
"""
import os
import re
import sys
import glob
import xmlrpc.client
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
REPO = BASE.parent
sys.path.insert(0, str(REPO / "_REACTIVAR_NUEVO_PC"))
sys.path.insert(0, str(BASE))  # GmailClient vendorizado en este paquete
import costear_embarque as ce           # noqa: E402
import estado as st                       # noqa: E402

# Gastos Chile ESTÁNDAR por contenedor (criterio fijado con Andrés) ≈ 912.187 CLP
CHILE_GASTOS = {
    "Gastos Puerto STI": 20000, "Flete Terrestre": 415000, "Seimex (local)": 238529,
    "Desconsolidación": 50000, "Gastos Despacho": 43658, "Gate In": 145000,
}
TC_ADUANA = 950.0
MAESTRA = REPO / "data" / "comex" / "Maestra Importaciones V2.xlsx"
OUT = BASE / "data" / "output"
DEST = ["felipe@unionx.cl", "sguzman@grupoeter.cl", "bodega@grupoeter.cl"]  # Gerardo por confirmar

PUERTOS = {"SZ": "Shenzhen", "NB": "Ningbo", "XI": "Xiamen"}


def resolver_archivos(reg) -> tuple[Path | None, Path | None]:
    """Devuelve (pi_path, pl_path): path del estado → repo → re-descarga de Gmail on-demand."""
    def buscar(doc):
        if not doc:
            return None
        if doc.get("path") and Path(doc["path"]).exists():
            return Path(doc["path"])
        fn = doc["filename"]
        # buscar por nombre en el repo (local)
        for base in [REPO / "data" / "comex" / "embarques", REPO / "agente-comex" / "data" / "inbox",
                     Path("C:/Users/andre/Downloads")]:
            hits = glob.glob(str(base / "**" / fn), recursive=True)
            if hits:
                return Path(hits[0])
        # re-descargar de Gmail (runner efímero en la nube)
        if doc.get("msg_id") and doc.get("attachment_id"):
            try:
                from gmail_client import GmailClient
                save_dir = BASE / "data" / "inbox" / (reg.get("embarque") or "tmp")
                return GmailClient().download_attachment(doc["msg_id"], doc["attachment_id"], fn, str(save_dir))
            except Exception as e:
                print(f"  (no pude re-descargar {fn} de Gmail: {e})")
        return None
    return buscar(reg.get("pi")), buscar(reg.get("pl"))


def construir_tarifas(reg, puerto: str) -> ce.Tarifas:
    return ce.Tarifas(
        puerto=puerto, puerto_nombre=PUERTOS.get(puerto, puerto),
        dolar=TC_ADUANA, fecha_eta=reg.get("eta_bodega") or reg.get("eta_puerto") or "",
        flete_total_usd=float(reg.get("flete_usd") or 0.0),
        gastos_chile_clp=dict(CHILE_GASTOS),
    )


def odoo_sku_check(productos) -> tuple[list, list]:
    """Devuelve (existentes, faltantes) por default_code en Odoo."""
    pwd = os.environ.get("ANDRES_ODOO_PASSWORD")
    url = "https://unionxb2b.odoo.com"; db = "bmya-innovatek-sh-prd-6981800"
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, "andres@grupoeter.cl", pwd, {})
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    skus = sorted({(p.sku or "").strip() for p in productos if (p.sku or "").strip()})
    existentes, faltantes = [], []
    for sku in skus:
        n = models.execute_kw(db, uid, pwd, "product.product", "search_count", [[["default_code", "=", sku]]])
        (existentes if n else faltantes).append(sku)
    return existentes, faltantes


def procesar_embarque(emb_num: str, reg: dict, dry_run: bool = True):
    pi_path, pl_path = resolver_archivos(reg)
    if not pi_path or not pl_path:
        st.log(reg, f"FALTA archivo local (PI={bool(pi_path)} PL={bool(pl_path)}) → no puedo costear aún")
        return
    print(f"\n--- Costeando {emb_num} ---\n  PI: {pi_path.name}\n  PL: {pl_path.name}")

    productos, inland, numero, puerto = ce.leer_pi(pi_path)
    ce.leer_pl(pl_path, productos)
    tar = construir_tarifas(reg, puerto)
    embq = ce.Embarque(numero=numero or emb_num, puerto=puerto,
                       puerto_nombre=PUERTOS.get(puerto, puerto),
                       productos=productos, inland_china=inland, tarifas=tar)
    ce.calcular_costeo(embq)
    if MAESTRA.exists():
        try: ce.comparar_con_maestra(embq, MAESTRA)
        except Exception as e: print(f"  (aviso: comparar_con_maestra falló: {e})")

    out_dir = OUT / emb_num; out_dir.mkdir(parents=True, exist_ok=True)
    precosteo = ce.generar_precosteo_xlsx(embq, out_dir)
    reg["costeo_path"] = str(precosteo)

    existentes, faltantes = odoo_sku_check(productos)
    sin_sku = sorted({p.model for p in productos if not (p.sku or "").strip()})  # productos sin código en el PI
    reg["skus"] = [p.sku for p in productos if p.sku]
    reg["skus_faltantes"] = faltantes
    reg["productos_sin_sku"] = sin_sku
    pendientes = len(faltantes) + len(sin_sku)
    st.log(reg, f"costeado · {len(productos)} prod · sobrecosto {embq.sobrecosto_pct:.1f}% · "
                f"internado {embq.total_internado_clp:,.0f} CLP · SKU por crear: {len(faltantes)} · sin SKU: {len(sin_sku)}")
    print(f"  SKU existentes: {len(existentes)} | POR CREAR: {faltantes or '—'} | SIN SKU en PI: {sin_sku or '—'}")

    if not dry_run:
        _crear_borrador(embq, reg, out_dir, faltantes, sin_sku)

    # gate a fase 4: TODOS los productos resueltos (SKU existente en Odoo Y ningún producto sin código)
    if pendientes == 0:
        st.set_fase(reg, 4, "todos los productos con SKU en Odoo → cargar PO")
    else:
        st.log(reg, f"pendientes ({len(faltantes)} por crear + {len(sin_sku)} sin código) → re-chequea Odoo mañana")


def _crear_borrador(embq, reg, out_dir, faltantes, sin_sku=None):
    from gmail_client import GmailClient
    sin_sku = sin_sku or []
    html_path = ce.generar_email_html(embq, out_dir)
    html = Path(html_path).read_text(encoding="utf-8")
    if faltantes:
        html += ("<div style='background:#fef9e7;border-left:4px solid #f1c40f;padding:12px;margin:16px 0'>"
                 f"<b>⚠️ SKU por crear en Odoo ({len(faltantes)}):</b> {', '.join(faltantes)}</div>")
    if sin_sku:
        html += ("<div style='background:#fdecea;border-left:4px solid #e74c3c;padding:12px;margin:16px 0'>"
                 f"<b>⚠️ Productos del PI SIN SKU ({len(sin_sku)}) — asignar código antes de cargar la PO:</b> "
                 f"{', '.join(sin_sku)}</div>")
    subj = f"[{embq.numero}] Costeo importación — {embq.puerto_nombre} — {embq.sobrecosto_pct:.1f}%"
    pend = len(faltantes) + len(sin_sku)
    if pend:
        subj += f" · {pend} SKU pendientes"
    gmail = GmailClient()
    draft_id = gmail.create_draft(to=", ".join(DEST), subject=subj, body_html=html)
    st.log(reg, f"borrador creado (draft {draft_id}) → {', '.join(DEST)}")


def procesar(dry_run: bool = True) -> dict:
    estado = st.cargar()
    pend = [e for e, r in estado.items() if r.get("fase") == 3]
    if not pend:
        print("No hay embarques en fase 3.")
        return estado
    print(f"Embarques en fase 3 (costeo): {pend}")
    for emb in pend:
        try:
            procesar_embarque(emb, estado[emb], dry_run=dry_run)
        except Exception as e:
            st.log(estado[emb], f"ERROR costeo: {type(e).__name__}: {e}")
    st.guardar(estado)
    print("\nEstado actual:")
    print(st.resumen(estado))
    return estado


if __name__ == "__main__":
    dry = "--commit" not in sys.argv
    print(f"=== FASE 3 · costeo + SKUs + borrador {'(dry-run, sin borrador)' if dry else '(commit)'} ===")
    procesar(dry_run=dry)
