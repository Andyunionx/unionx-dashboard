"""FASE 1 — Scrape de correos de Steven: detecta y empareja PI + PL por embarque.

Regla (Andrés):
- Lee mails de Steven (topwillsteven@163.com) con adjuntos.
- Empareja PI + PL por número de embarque (26TPxxxx), CRUZANDO correos (pueden venir separados).
- SIEMPRE deja el mail en NO LEÍDO + label "COMEX/Auto-Procesado" (nunca marca leído).
- Si un embarque ya tiene PI+PL → avanza a fase 2 (esperando flete Seimex).
- Si faltan docs, en la próxima corrida (día siguiente) vuelve a escanear.

dry_run=True: solo detecta y reporta, NO descarga, NO etiqueta, NO muta el inbox.
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
# Reusar el GmailClient del agente existente (mismo token/credenciales)
sys.path.insert(0, str(BASE.parent / "agente-comex" / "src"))
from gmail_client import GmailClient  # noqa: E402

import estado as st  # noqa: E402

STEVEN = "topwillsteven@163.com"
PROCESADO_LABEL = "COMEX/Auto-Procesado"
INBOX = BASE / "data" / "inbox"
# Tolerante a typos de Steven: 26TP0815 / 26T0816 (sin P) / "26 TP 0815" → normaliza a 26TP####
RE_EMB = re.compile(r"(2[56])\s*T\.?\s*P?\.?\s*(\d{4})", re.IGNORECASE)


def norm_emb(texto: str) -> str | None:
    m = RE_EMB.search(texto or "")
    return f"{m.group(1)}TP{m.group(2)}" if m else None


def clasificar_adjunto(filename: str) -> str | None:
    """PI / PL / None según el nombre del adjunto."""
    f = filename.upper()
    if not f.endswith((".XLS", ".XLSX")):
        return None
    if "PL" in f:          # los PL suelen llamarse "26TP0716PI PL.xlsx" → PL manda
        return "PL"
    if "PI" in f:
        return "PI"
    return None


def score_pi(filename: str) -> int:
    """Prioridad de variante de PI: A+B gana; si es A+B modificado, ese; luego el resto.
    (Regla Andrés 17-ago: para 0702 debe ser A+B.)"""
    f = filename.upper().replace(" ", "")
    s = 0
    if "A+B" in f:
        s += 10
    if "MODIFIED" in f or "MODIFICAD" in f:
        s += 1
    return s


def elegir_pi(candidatos: list) -> dict | None:
    """Elige EL PI a costear entre las variantes: mayor score, desempate por fecha más nueva."""
    if not candidatos:
        return None
    return sorted(candidatos, key=lambda d: (score_pi(d["filename"]), d.get("date", "")), reverse=True)[0]


def escanear(dry_run: bool = True) -> dict:
    """Corre la fase 1. Devuelve el estado actualizado."""
    gmail = GmailClient()
    estado = st.cargar()

    # Mails de Steven con adjuntos que este agente aún NO procesó.
    # Filtramos por AUSENCIA del label (no por unread) → así los dejamos sin leer.
    query_extra = None if dry_run else f"-label:{PROCESADO_LABEL}"
    correos = gmail.search_emails(
        sender=STEVEN, has_attachment=True, is_unread=False, max_results=40,
    )
    # (search_emails arma la query con from+has:attachment; el filtro de label lo
    #  aplicamos abajo revisando label_ids para no depender de que exista el label)

    print(f"Correos de Steven con adjuntos: {len(correos)}\n")
    nuevos_docs = 0

    for c in correos:
        # saltar los que ya procesamos (por label) — solo en modo commit,
        # para no crear el label ni mutar nada en dry-run
        if not dry_run and PROCESADO_LABEL_ID(gmail) in c.get("label_ids", []):
            continue

        emb_subj = norm_emb(c.get("subject", ""))
        # embarques presentes por NOMBRE de archivo (para decidir si el fallback al asunto es seguro)
        embs_por_archivo = {norm_emb(a["filename"]) for a in c.get("attachments", [])}
        embs_por_archivo.discard(None)
        ambiguo = len(embs_por_archivo) > 1  # el correo mezcla varios embarques

        encontrados = []
        for att in c.get("attachments", []):
            tipo = clasificar_adjunto(att["filename"])
            if not tipo:
                continue
            emb = norm_emb(att["filename"])
            if not emb:
                # sin número en el archivo → usar asunto SOLO si el correo no mezcla embarques
                if ambiguo:
                    print(f"  [omitido] adjunto sin embarque en nombre y correo mezcla varios: {att['filename']}")
                    continue
                emb = emb_subj
            if not emb:
                continue
            encontrados.append((emb, tipo, att))

        if not encontrados:
            continue

        for emb, tipo, att in encontrados:
            reg = st.get_embarque(estado, emb)
            lista = reg[f"{tipo.lower()}_candidatos"]
            if any(d["filename"] == att["filename"] for d in lista):
                continue  # ya lo teníamos
            doc = {"msg_id": c["id"], "filename": att["filename"],
                   "attachment_id": att["attachment_id"], "subject": c.get("subject", ""),
                   "date": c.get("date", "")}
            if not dry_run:
                save_dir = INBOX / emb
                path = gmail.download_attachment(c["id"], att["attachment_id"], att["filename"], str(save_dir))
                doc["path"] = str(path)
            lista.append(doc)
            nuevos_docs += 1
            # recomputar EL elegido: PI por regla A+B; PL por más nuevo
            if tipo == "PI":
                reg["pi"] = elegir_pi(reg["pi_candidatos"])
            else:
                reg["pl"] = sorted(reg["pl_candidatos"], key=lambda d: d.get("date", ""), reverse=True)[0]
            st.log(reg, f"{tipo} detectado: {att['filename']}" + (" (dry-run)" if dry_run else " · descargado"))

            # ¿completó PI+PL? → avanzar a fase 2
            if reg.get("pi") and reg.get("pl") and reg["fase"] == 1:
                st.set_fase(reg, 2, f"PI+PL completos (PI elegido: {reg['pi']['filename']}) → esperando flete Seimex")

        # dejar NO LEÍDO + label procesado (solo fuera de dry-run)
        if not dry_run:
            gmail.add_label(c["id"], PROCESADO_LABEL)  # NO llamamos mark_as_read → queda sin leer

    # El estado es un JSON local (no muta Gmail) → se persiste siempre para encadenar fases
    st.guardar(estado)

    print(f"\nDocumentos nuevos detectados: {nuevos_docs}")
    print("Estado actual:")
    print(st.resumen(estado))
    return estado


_LABEL_ID_CACHE = {}
def PROCESADO_LABEL_ID(gmail) -> str:
    if PROCESADO_LABEL not in _LABEL_ID_CACHE:
        try:
            _LABEL_ID_CACHE[PROCESADO_LABEL] = gmail._get_or_create_label(PROCESADO_LABEL)
        except Exception:
            _LABEL_ID_CACHE[PROCESADO_LABEL] = "__none__"
    return _LABEL_ID_CACHE[PROCESADO_LABEL]


if __name__ == "__main__":
    dry = "--commit" not in sys.argv
    print(f"=== FASE 1 · scrape correos Steven {'(DRY-RUN)' if dry else '(COMMIT)'} ===\n")
    escanear(dry_run=dry)
