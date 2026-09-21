# -*- coding: utf-8 -*-
"""Pulso Reposición Fulfillment — envío lunes 07:30 CLT (email_diario.yml, gate lunes).

Pipeline: tránsito vivo (Seimex×Odoo, tolerante a falla) → pulso (panel Nicole
fresco) → mail HTML estilo Pulso UnionX con el Excel adjunto.

Credenciales CI: ANDRES_ODOO_PASSWORD · DRIVE_OAUTH_TOKEN_JSON · GMAIL_TOKEN_JSON
(mismos secrets del Pulso Diario). SEIMEX_* opcional: si falta, el tránsito usa
el último parquet committeado y se avisa en el mail.
Destinatarios: env EMAIL_TO (default equipo reposición).
"""
import argparse, os, sys, json, datetime
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
from enviar_pulso_cyber import _enviar_via_gmail

AZ = "#1E3A5F"; GR = "#EBF0F8"; ROJO = "#B3261E"
EMAIL_TO = [e.strip() for e in os.environ.get(
    "EMAIL_TO",
    "nicole@unionx.cl,nicolas@unionx.cl,trinidad@unionx.cl,claudia@unionx.cl,andres@unionx.cl"
).split(",") if e.strip()]

def clp(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,.0f}".format(n).replace(",", ".")


FALA_TRANSITO = Path("data/stock/fala_transito_live.parquet")
WFS_LIVE = Path("data/stock/walmart_wfs_live.parquet")


def _fuentes_transito(hoy):
    """Estado de las fuentes de tránsito por canal que NO salen de Odoo.

    Si el scraper del Seller Center falla (login, 2FA, cambio de página), el
    pulso cae en silencio al fallback de Odoo, que para Falabella es
    estructuralmente CERO: las reposiciones a Fala no pasan por transferencias
    internas. El 21-09 eso hizo que el pulso sugiriera 616 uds ignorando 2.747 ya
    en camino. Esto lo detecta y lo saca al mail, en rojo."""
    avisos = []
    for canal, ruta, fuente in [("Falabella", FALA_TRANSITO, "Seller Center FBF (scraper)"),
                                ("Walmart", WFS_LIVE, "export WFS del Seller Center")]:
        if not ruta.exists():
            avisos.append((canal, f"sin archivo de {fuente}"))
            continue
        try:
            ts = pd.to_datetime(pd.read_parquet(ruta)["ts"].max())
            edad = (pd.Timestamp(hoy) - ts.normalize()).days
            if edad > 0:
                avisos.append((canal, f"{fuente} sin refrescar: último dato del {ts.date()} ({edad}d)"))
        except Exception as e:
            avisos.append((canal, f"{fuente} ilegible ({type(e).__name__})"))
    return avisos


def _html_aviso_transito(avisos):
    if not avisos:
        return ""
    filas = "".join(f"<li><b>{c}</b>: {d}. La sugerencia de este canal <b>no descuenta lo que ya está "
                    f"en camino</b> — revisarla contra el Seller Center antes de ejecutar.</li>"
                    for c, d in avisos)
    return (f'<div style="font-size:13px;margin:10px 0;padding:8px 12px;background:#FDECEA;'
            f'border-left:4px solid {ROJO};"><b>⚠ Tránsito no disponible en esta corrida</b>'
            f'<ul style="margin:6px 0 0 18px;padding:0;">{filas}</ul></div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-scrape", action="store_true",
                    help="no vuelve a correr el scraper FBF ni el ingest WFS (usa los parquets ya frescos)")
    ap.add_argument("--responder-hilo", metavar="THREAD_ID",
                    help="envía como respuesta dentro de esa cadena de Gmail (corrección de un pulso ya enviado)")
    ap.add_argument("--in-reply-to", metavar="MESSAGE_ID", help="Message-ID RFC del mail al que se responde")
    ap.add_argument("--to", help="destinatarios (coma) — reemplaza EMAIL_TO")
    ap.add_argument("--cc", help="copia (coma)")
    ap.add_argument("--correccion", metavar="HTML",
                    help="bloque HTML que va arriba del pulso explicando qué cambió")
    a = ap.parse_args()

    hoy = datetime.date.today()
    semana = hoy.isocalendar()[1]

    # 1) tránsito vivo (tolerante: sin SEIMEX_* usa el parquet existente)
    transito_ok = True
    try:
        import transito_vivo
        transito_vivo._cargar_env()
        ops = transito_vivo.operaciones_vivas()
        det = transito_vivo.pendientes_odoo(ops)
        if not det.empty:
            det = det.groupby(["sku", "eta", "pi", "oc", "oc_estado", "stage"], as_index=False)["unidades"].sum()
            ts = datetime.datetime.now().isoformat(timespec="seconds")
            det["ts_actualizado"] = ts
            det.to_parquet(transito_vivo.SNAP / "transito_vivo.parquet", index=False)
            mensual = det.assign(mes=det["eta"].str[:7]).groupby(["sku", "mes"], as_index=False)["unidades"].sum()
            mensual["ts_actualizado"] = ts
            mensual.to_parquet(transito_vivo.SNAP / "planif_forecast_transito.parquet", index=False)
    except Exception as e:
        transito_ok = False
        print(f"[transito][WARN] {type(e).__name__}: {e} — se usa el último snapshot", flush=True)

    if not a.sin_scrape:
        # 1b) stock FBF de Falabella (API Seller Center, tolerante: si falla, el pulso
        # cae al fallback Odoo/Martín para ese canal — y _fuentes_transito lo avisa)
        try:
            import scrape_fala_fbf
            scrape_fala_fbf.main()
        except Exception as e:
            print(f"[fbf][WARN] {type(e).__name__}: {e} — Falabella usa fallback", flush=True)

        # 1c) stock Walmart Full (WFS) desde el export del Seller Center que manda Trini
        # (tolerante: si no hay export reciente, Walmart cae al fallback Odoo BFW)
        try:
            import ingest_walmart_wfs
            ingest_walmart_wfs.main()
        except Exception as e:
            print(f"[wfs][WARN] {type(e).__name__}: {e} — Walmart usa fallback", flush=True)

    avisos_fuentes = _fuentes_transito(hoy)
    for c, d in avisos_fuentes:
        print(f"[transito][AVISO] {c}: {d}", flush=True)

    # 2) pulso
    from pulso_reposicion_fulfillment import construir, construir_excel_5pestanas
    fn = construir()
    xlsx = construir_excel_5pestanas(fn)   # 5 pestañas con fórmulas + tabla dinámica

    res = pd.read_excel(fn, sheet_name="Resumen canal")
    ume = pd.read_excel(fn, sheet_name="UME v2")
    tot_uds = res["Unidades"].sum(); tot_skus = int((ume["Reposición"] > 0).sum())
    tot_m3 = res["m3"].sum(); tot_costo = res["Costo envío est."].sum()

    # tránsito para el mail
    tr_html = ""
    try:
        tr = pd.read_parquet("data/planificacion/snapshots/transito_vivo.parquet")
        g = tr.groupby(["pi", "eta"], as_index=False)["unidades"].sum().sort_values("eta")
        filas = "".join(f"<tr><td style='padding:4px 10px;'>{r.pi}</td>"
                        f"<td style='padding:4px 10px;'>{str(r.eta)[:10]}</td>"
                        f"<td style='padding:4px 10px;text-align:right;'>{miles(r.unidades)}</td></tr>"
                        for r in g.itertuples(index=False))
        tr_html = f"""<div style="font-size:13px;margin:14px 0 4px;"><b>🚢 Tránsito vivo</b>
        ({miles(tr['unidades'].sum())} uds — ya considerado en la restricción de cobertura):</div>
        <table style="border-collapse:collapse;font-size:12px;">
        <tr style="background:{AZ};color:#fff;"><th style="padding:4px 10px;text-align:left;">PI</th>
        <th style="padding:4px 10px;">ETA</th><th style="padding:4px 10px;">Uds</th></tr>{filas}</table>"""
    except Exception:
        pass

    gaps_html = ""
    try:
        gaps = json.load(open("data/planificacion/snapshots/transito_gaps.json", encoding="utf-8"))
        if gaps:
            det = " · ".join(f"{g['pi']} (ETA {g['eta']})" for g in gaps)
            gaps_html = (f'<div style="font-size:13px;margin:10px 0;padding:8px 12px;background:#FDECEA;'
                         f'border-left:4px solid {ROJO};"><b>⚠ Embarques sin OC en Odoo</b> — sus SKUs no se '
                         f'pueden proyectar: {det}</div>')
    except Exception:
        pass

    filas_canal = "".join(
        f"""<tr style="background:{GR if i % 2 == 0 else '#fff'};">
        <td style="padding:6px 12px;">{r['Canal']}</td>
        <td style="padding:6px 12px;text-align:right;"><b>{miles(r['Unidades'])}</b></td>
        <td style="padding:6px 12px;text-align:right;">{miles(r['SKUs'])}</td>
        <td style="padding:6px 12px;text-align:right;">{r['m3']:.1f}</td>
        <td style="padding:6px 12px;text-align:right;">{clp(r['Costo envío est.'])}</td>
        <td style="padding:6px 12px;">{r['Tramo']}</td></tr>"""
        for i, (_, r) in enumerate(res.iterrows()))

    aviso_transito = "" if transito_ok else (
        f'<div style="font-size:12px;color:{ROJO};margin:6px 0;">⚠ El tránsito no se pudo refrescar en esta '
        f'corrida (se usó el último snapshot).</div>')

    correccion_html = a.correccion or ""
    titulo = "📦 Pulso Reposición Fulfillment" + (" — CORRECCIÓN" if correccion_html else "")

    html = f"""<div style="font-family:Arial,sans-serif;color:#222;max-width:720px;line-height:1.5;">
<h2 style="color:{AZ};margin-bottom:2px;">{titulo}</h2>
<div style="color:#64748b;font-size:12px;">Semana {semana} · {hoy.strftime('%d/%m/%Y')} · v1 en marcha blanca</div>
{correccion_html}
{_html_aviso_transito(avisos_fuentes)}

<div style="font-size:14px;margin:12px 0;"><b>Sugerido de la semana:</b> {miles(tot_uds)} unidades ·
{miles(tot_skus)} SKU-canal · {tot_m3:.1f} m³ · envío estimado {clp(tot_costo)}</div>

<table style="border-collapse:collapse;font-size:13px;margin:8px 0;">
<tr style="background:{AZ};color:#fff;">
  <th style="padding:6px 12px;text-align:left;">Canal</th>
  <th style="padding:6px 12px;">Unidades</th>
  <th style="padding:6px 12px;">SKUs</th>
  <th style="padding:6px 12px;">m³</th>
  <th style="padding:6px 12px;">Envío est.</th>
  <th style="padding:6px 12px;text-align:left;">Tramo</th></tr>
{filas_canal}
</table>
{gaps_html}
{tr_html}
{aviso_transito}

<div style="font-size:13px;margin:14px 0;">📎 <b>Excel adjunto — 5 pestañas con fórmulas:</b>
<b>1. Propuesta Reposición</b> (por fórmula: Máximo − Stock − Tránsito, topado a CA1) ·
<b>2. Stock inicial marketplace</b> · <b>3. Tránsito marketplace</b> ·
<b>4. CA1 disponible + Máximos</b> (la <b>UME Manual</b> es editable → el Máximo y la Propuesta se recalculan solos) ·
<b>5. Dinámica</b> (tabla dinámica de siempre). Debajo van <b>Datos</b>, <b>Resumen canal</b> y <b>Metodología</b>.</div>

<div style="font-size:12px;color:#475569;margin-top:14px;">Los parámetros comerciales (Reglas, UME MIN,
UME Manual, BLACKLIST, LARGE) se leen de la planilla de siempre en cada corrida — cualquier ajuste ahí queda
tomado el lunes siguiente. Feedback a este pulso: responder por esta cadena.</div>
</div>"""

    asunto = f"📦 Pulso Reposición Fulfillment · Semana {semana} · {miles(tot_uds)} uds · {hoy.strftime('%d-%m-%Y')}"
    fname = f"Reporte Reposicion Fulfillment semana {semana} - {hoy.strftime('%d-%m-%Y')}"
    to_list = [e.strip() for e in a.to.split(",") if e.strip()] if a.to else EMAIL_TO
    cc_list = [e.strip() for e in a.cc.split(",") if e.strip()] if a.cc else None
    if a.responder_hilo:
        asunto = "Re: " + asunto
        fname += " (corregido)"
    print(f"Enviando a {to_list}" + (f" cc {cc_list}" if cc_list else "") +
          (f" en hilo {a.responder_hilo}" if a.responder_hilo else "") + "...", flush=True)
    msg_id = _enviar_via_gmail(asunto, html, xlsx, fname, to_list, cc_list=cc_list,
                               thread_id=a.responder_hilo, in_reply_to=a.in_reply_to)
    print("Enviado. msg_id:", msg_id, flush=True)
    return 0 if msg_id else 1


if __name__ == "__main__":
    sys.exit(main())
